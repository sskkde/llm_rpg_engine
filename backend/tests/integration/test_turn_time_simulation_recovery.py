"""Phase-3 recovery, replay and fail-closed gates (plan section 9.1).

Two different things are covered here and they must stay apart:

* normal continuation / restart recovery -- the slice is rebuilt from the database
  and a same-key retry returns the *saved* result without re-seeding, re-simulating,
  re-writing memory or calling a model;
* fail-closed adjudication of a marker or run state the engine cannot trust -- an
  unknown profile, a damaged structure, business state without a run marker, a
  foreign pending row or a broken unique-item invariant must refuse the turn rather
  than guess a cursor or silently fall back to the legacy scheduler.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

import pytest
from sqlalchemy.orm import sessionmaker

from llm_rpg.core import time_simulation_rules as rules
from llm_rpg.core import turn_service
from llm_rpg.core.time_simulation import (
    PHASE3_NAMESPACE,
    TimeSimulationProfileError,
    resolve_phase3_profile,
)
from llm_rpg.core.time_simulation_persistence import load_simulation_context
from llm_rpg.scripts.seed_time_slice import seed_time_slice
from llm_rpg.storage.models import (
    EventLogModel,
    GameEventModel,
    ModelCallLogModel,
    NPCPrivateMemoryModel,
    ScheduledEventModel,
    SessionInventoryItemModel,
    SessionModel,
    SessionStateModel,
    StateDeltaModel,
    WorldModel,
)

from .time_slice_fixtures import (
    TimeSliceSession,
    intent_stage_result,
    patch_intent_stage,
    run_turn,
    time_slice,  # noqa: F401 - re-exported so pytest can resolve the fixture
)

TOKEN_STEP_KEYS = {
    "npc_a.npc_travel_start@2",
    "npc_a.npc_take_item@5",
    "npc_b.npc_take_item@5",
    "npc_b.npc_use_item@6",
    "world.environment_interrupt@7",
    "npc_b.npc_travel_start@8",
}


def _counts(time_slice: TimeSliceSession) -> Dict[str, int]:
    db = time_slice.db
    return {
        "scheduled": db.query(ScheduledEventModel).filter_by(session_id=time_slice.session_id).count(),
        "game_events": db.query(GameEventModel).filter_by(session_id=time_slice.session_id).count(),
        "deltas": db.query(StateDeltaModel).filter_by(session_id=time_slice.session_id).count(),
        "event_logs": db.query(EventLogModel).filter_by(session_id=time_slice.session_id).count(),
        "token_rows": db.query(SessionInventoryItemModel).filter_by(session_id=time_slice.session_id).count(),
        "npc_memories": db.query(NPCPrivateMemoryModel).filter_by(session_id=time_slice.session_id).count(),
        # Tripwire: a same-key replay must not reach a model at all.
        "model_calls": db.query(ModelCallLogModel).filter_by(session_id=time_slice.session_id).count(),
    }


def _world_with_marker(time_slice: TimeSliceSession, marker: Any) -> str:
    """A second world in the same database carrying a specific profile marker."""
    suffix = uuid.uuid4().hex
    world = WorldModel(
        id=f"w-{suffix}",
        code=f"w-{suffix}",
        name="标记世界",
        genre="xianxia",
        status="active",
        ruleset_json={"phase3_profile": marker},
    )
    session = SessionModel(
        id=f"session-{suffix}",
        user_id=time_slice.db.query(SessionModel).get(time_slice.session_id).user_id,
        world_id=world.id,
        status="active",
    )
    time_slice.db.add_all([world, session])
    time_slice.db.commit()
    return session.id


# ---------------------------------------------------------------------------
# Restart recovery and same-key replay
# ---------------------------------------------------------------------------


def test_restart_rebuilds_the_slice_from_the_database_alone(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    patch_intent_stage(monkeypatch, intent_stage_result("idle"))
    run_turn(time_slice, "原地等待片刻")

    # A brand-new Session over the same database: no identity map, no turn-time
    # ``db.info`` overlay, no process cache.
    fresh = sessionmaker(bind=time_slice.db.get_bind())()
    try:
        assert fresh.info.get("session_story_state_plan") is None
        ctx = load_simulation_context(fresh, time_slice.session_id)
        assert ctx.run_state.logical_tick == 7
        assert ctx.run_state.next_event_seq == 6
        assert ctx.state.npc_positions[rules.NPC_A_CODE] == rules.LOCATION_TRIAL_PEAK
        assert ctx.state.npc_positions[rules.NPC_B_CODE] == rules.LOCATION_TRIAL_PEAK
        assert ctx.state.item_owner_type == "npc"
        assert ctx.state.item_owner_ref == rules.NPC_A_CODE
        assert ctx.state.npc_plans[rules.NPC_A_CODE].status == "arrived"
        assert [row.step.step_key for row in ctx.pending_steps] == [
            "npc_b.npc_travel_start@8"
        ]
        assert ctx.consumed_step_keys >= {
            "npc_a.npc_travel_start@2",
            "npc_a.npc_travel_arrive@5",
            "world.environment_interrupt@7",
        }
    finally:
        fresh.close()

    # And the next turn continues from the rebuilt cursor.
    second = run_turn(time_slice, "继续等待")
    assert second.time_advance_result["actual_elapsed_minutes"] == 10
    assert time_slice.run_state().logical_tick == 17
    assert time_slice.npc_location_code(rules.NPC_B_CODE) == rules.LOCATION_PLAZA


def test_same_key_replay_returns_the_saved_result_without_re_simulating(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    patch_intent_stage(monkeypatch, intent_stage_result("idle"))
    first = run_turn(time_slice, "原地等待片刻", idempotency_key="p3-replay-key")
    assert first.time_advance_result["actual_elapsed_minutes"] == 7

    before = _counts(time_slice)
    cursor_before = time_slice.run_state()

    replay = run_turn(time_slice, "原地等待片刻", idempotency_key="p3-replay-key")

    assert replay.turn_no == first.turn_no
    assert replay.time_advance_result == first.time_advance_result
    assert replay.action_resolution == first.action_resolution
    assert _counts(time_slice) == before
    assert time_slice.run_state() == cursor_before
    assert time_slice.token_rows()[0].owner_ref_id == time_slice.npc_row(
        rules.NPC_A_CODE
    ).id


# ---------------------------------------------------------------------------
# Fail-closed profile markers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "marker",
    [
        "broken",
        {"id": "trial_micro_v1"},
        {"schema_version": 1},
        {"id": "other_profile_v1", "schema_version": 1},
        {"id": "trial_micro_v1", "schema_version": 2},
        {"id": "trial_micro_v1", "schema_version": 1, "extra": True},
    ],
)
def test_damaged_or_unknown_profile_marker_is_refused(
    time_slice: TimeSliceSession, marker: Any
) -> None:
    session_id = _world_with_marker(time_slice, marker)
    session = time_slice.db.query(SessionModel).get(session_id)
    world = time_slice.db.query(WorldModel).get(session.world_id)

    with pytest.raises(TimeSimulationProfileError):
        resolve_phase3_profile(world)

    with pytest.raises(turn_service.TurnServiceError):
        turn_service.execute_turn_service(
            time_slice.db, session_id, "观察四周", use_mock=True
        )


def test_ruleset_that_is_not_an_object_is_refused(time_slice: TimeSliceSession) -> None:
    class _World:
        ruleset_json = ["not", "an", "object"]

    with pytest.raises(TimeSimulationProfileError):
        resolve_phase3_profile(_World())


def test_world_without_a_marker_stays_on_the_legacy_path(
    time_slice: TimeSliceSession,
) -> None:
    class _World:
        ruleset_json = {"combat": "d100"}

    assert resolve_phase3_profile(_World()) is None


# ---------------------------------------------------------------------------
# Fail-closed run state and step rows
# ---------------------------------------------------------------------------


def test_business_state_without_a_run_marker_is_refused(
    time_slice: TimeSliceSession,
) -> None:
    """Existing state plus a missing marker must never be guessed into a cursor."""
    time_slice.db.add(
        SessionStateModel(
            id=f"ss-{uuid.uuid4().hex}",
            session_id=time_slice.session_id,
            current_location_id=time_slice.location_id(rules.LOCATION_MOUNTAIN_GATE),
            current_time="修仙历 春 第1日 辰时 08:00",
            time_phase="辰时",
            active_mode="exploration",
            global_flags_json={},
        )
    )
    time_slice.db.add(
        EventLogModel(
            id=f"el-{uuid.uuid4().hex}",
            session_id=time_slice.session_id,
            turn_no=1,
            event_type="player_turn",
            result_json={"action_type": "inspect"},
            narrative_text="旧回合",
        )
    )
    time_slice.db.commit()

    with pytest.raises(turn_service.TurnServiceError):
        run_turn(time_slice, "观察四周")


@pytest.mark.parametrize(
    "run_state",
    [
        {"schema_version": 1},
        {"schema_version": 1, "profile_id": rules.PROFILE_ID},
        {"schema_version": 1, "profile_id": rules.PROFILE_ID, "logical_tick": -1, "next_event_seq": 0, "one_shot": {}},
        {"schema_version": 1, "profile_id": "other_profile_v1", "logical_tick": 0, "next_event_seq": 0, "one_shot": {}},
        {"schema_version": 2, "profile_id": rules.PROFILE_ID, "logical_tick": 0, "next_event_seq": 0, "one_shot": {}},
        {"schema_version": 1, "profile_id": rules.PROFILE_ID, "logical_tick": 0, "next_event_seq": 0, "one_shot": {"k": "not-a-bool"}},
        "not-an-object",
    ],
)
def test_damaged_run_state_is_refused(
    time_slice: TimeSliceSession, run_state: Any
) -> None:
    time_slice.db.add(
        SessionStateModel(
            id=f"ss-{uuid.uuid4().hex}",
            session_id=time_slice.session_id,
            current_location_id=time_slice.location_id(rules.LOCATION_MOUNTAIN_GATE),
            current_time="修仙历 春 第1日 辰时 08:00",
            time_phase="辰时",
            active_mode="exploration",
            global_flags_json={PHASE3_NAMESPACE: run_state},
        )
    )
    time_slice.db.commit()

    with pytest.raises(turn_service.TurnServiceError):
        run_turn(time_slice, "观察四周")


def test_foreign_pending_scheduled_row_is_refused(
    time_slice: TimeSliceSession,
) -> None:
    """A row outside the slice namespace is refused, never silently dropped."""
    time_slice.db.add(
        ScheduledEventModel(
            id=f"se-{uuid.uuid4().hex}",
            session_id=time_slice.session_id,
            trigger_conditions_json={"world_time": {"period": "午时"}},
            status="pending",
        )
    )
    time_slice.db.commit()

    with pytest.raises(turn_service.TurnServiceError):
        run_turn(time_slice, "观察四周")


def test_damaged_namespaced_step_row_is_refused(
    time_slice: TimeSliceSession,
) -> None:
    time_slice.db.add(
        ScheduledEventModel(
            id=f"se-{uuid.uuid4().hex}",
            session_id=time_slice.session_id,
            trigger_conditions_json={PHASE3_NAMESPACE: {"schema_version": 1}},
            status="pending",
        )
    )
    time_slice.db.commit()

    with pytest.raises(turn_service.TurnServiceError):
        run_turn(time_slice, "观察四周")


def test_duplicate_token_rows_are_refused_not_cleaned_up(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    """The unique-item invariant is refused when broken; nothing is auto-repaired."""
    patch_intent_stage(monkeypatch, intent_stage_result("inspect"))
    run_turn(time_slice, "观察四周")

    token = time_slice.token_rows()[0]
    time_slice.db.add(
        SessionInventoryItemModel(
            id=f"inv-{uuid.uuid4().hex}",
            session_id=time_slice.session_id,
            item_template_id=token.item_template_id,
            owner_type="player",
            owner_ref_id="player",
            quantity=1,
        )
    )
    time_slice.db.commit()
    assert len(time_slice.token_rows()) == 2

    with pytest.raises(turn_service.TurnServiceError):
        run_turn(time_slice, "观察四周")
    # The duplicate is still there: adjudication must not silently delete data.
    assert len(time_slice.token_rows()) == 2


def test_npc_standing_outside_the_slice_locations_is_refused(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    patch_intent_stage(monkeypatch, intent_stage_result("inspect"))
    run_turn(time_slice, "观察四周")

    row = time_slice.npc_row(rules.NPC_B_CODE)
    row.current_location_id = "loc-outside-the-slice"
    time_slice.db.commit()

    with pytest.raises(turn_service.TurnServiceError):
        run_turn(time_slice, "观察四周")


def test_missing_token_row_in_an_existing_session_is_refused(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    patch_intent_stage(monkeypatch, intent_stage_result("inspect"))
    run_turn(time_slice, "观察四周")

    for row in time_slice.token_rows():
        time_slice.db.delete(row)
    time_slice.db.commit()

    with pytest.raises(turn_service.TurnServiceError):
        run_turn(time_slice, "观察四周")


# ---------------------------------------------------------------------------
# Business rows without a run marker, illegal owners, damaged cursor
# ---------------------------------------------------------------------------


def test_orphan_npc_rows_without_a_run_marker_are_refused(
    time_slice: TimeSliceSession,
) -> None:
    """Orphan business rows mean the session already ran; a tick-0 cursor is a guess."""
    from llm_rpg.storage.repositories import SessionNPCStateRepository

    template_id = time_slice.npc_ids[rules.NPC_A_CODE]
    time_slice.db.add(
        SessionNPCStateRepository(time_slice.db).model(
            id=f"snpc-{uuid.uuid4().hex}",
            session_id=time_slice.session_id,
            npc_template_id=template_id,
            current_location_id=time_slice.location_id(rules.LOCATION_TRIAL_PEAK),
            status_flags={},
        )
    )
    time_slice.db.commit()

    with pytest.raises(turn_service.TurnServiceError):
        run_turn(time_slice, "观察四周")


def test_orphan_scheduled_rows_without_a_run_marker_are_refused(
    time_slice: TimeSliceSession,
) -> None:
    from llm_rpg.core.time_simulation import encode_step_conditions
    from llm_rpg.core.time_simulation_rules import build_trial_rules

    step = build_trial_rules().initial_steps()[0]
    time_slice.db.add(
        ScheduledEventModel(
            id=f"se-{uuid.uuid4().hex}",
            session_id=time_slice.session_id,
            trigger_conditions_json=encode_step_conditions(step),
            status="triggered",
        )
    )
    time_slice.db.commit()

    with pytest.raises(turn_service.TurnServiceError):
        run_turn(time_slice, "观察四周")


def _seed_slice(time_slice: TimeSliceSession, monkeypatch) -> None:
    patch_intent_stage(monkeypatch, intent_stage_result("inspect"))
    run_turn(time_slice, "观察四周")


def test_npc_template_id_is_not_a_valid_token_owner(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    """An owner reference must be a session NPC state row, never a template id."""
    _seed_slice(time_slice, monkeypatch)
    row = time_slice.token_owner()
    row.owner_type = "npc"
    row.owner_ref_id = time_slice.npc_ids[rules.NPC_A_CODE]
    time_slice.db.commit()

    with pytest.raises(turn_service.TurnServiceError):
        run_turn(time_slice, "观察四周")


def test_foreign_npc_reference_is_not_a_valid_token_owner(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    _seed_slice(time_slice, monkeypatch)
    row = time_slice.token_owner()
    row.owner_type = "npc"
    row.owner_ref_id = f"snpc-{uuid.uuid4().hex}"
    time_slice.db.commit()

    with pytest.raises(turn_service.TurnServiceError):
        run_turn(time_slice, "观察四周")


def test_player_owned_token_with_a_foreign_reference_is_refused(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    """A junk player reference must not be silently normalised into ownership."""
    _seed_slice(time_slice, monkeypatch)
    row = time_slice.token_owner()
    row.owner_type = "player"
    row.owner_ref_id = f"not-a-player-{uuid.uuid4().hex}"
    time_slice.db.commit()

    with pytest.raises(turn_service.TurnServiceError):
        run_turn(time_slice, "观察四周")


def test_event_cursor_inconsistent_with_the_timeline_is_refused(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    """The stored event cursor must match the durable engine timeline."""
    _seed_slice(time_slice, monkeypatch)
    state = time_slice.run_state()
    assert state.next_event_seq > 0

    row = time_slice.session_state()
    flags = dict(row.global_flags_json)
    flags[PHASE3_NAMESPACE] = {**flags[PHASE3_NAMESPACE], "next_event_seq": 0}
    row.global_flags_json = flags
    time_slice.db.commit()

    with pytest.raises(turn_service.TurnServiceError):
        run_turn(time_slice, "观察四周")
