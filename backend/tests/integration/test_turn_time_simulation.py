"""Phase-3 acceptance: the three formal turn trajectories (plan section 6).

Every test here drives the *production* entry point
(``core.turn_service.execute_turn_service``) against a real seeded slice session.
Nothing is asserted from a helper's return value alone: the committed rows are
read back, so an implementation that only "looks right" cannot pass.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

import pytest

from llm_rpg.core import time_simulation_rules as rules
from llm_rpg.core import turn_service
from llm_rpg.core.time_simulation import (
    PlayerActionKind,
    PlayerActionSpec,
    ScheduledStep,
    SimulationPhase,
    StepKind,
    travel_step_key,
)
from llm_rpg.core.time_simulation_persistence import project_time_summary
from llm_rpg.core.world_advancer import WorldAdvancer
from llm_rpg.storage.models import (
    ModelCallLogModel,
    ScheduledEventModel,
    SessionModel,
    ValidationReportModel,
)

from .time_slice_fixtures import (
    TimeSliceSession,
    intent_stage_result,
    patch_intent_stage,
    run_turn,
    time_slice,  # noqa: F401 - re-exported so pytest can resolve the fixture
)

STEP_A_DEPART = travel_step_key(rules.NPC_A_CODE, StepKind.NPC_TRAVEL_START, 2)
STEP_A_ARRIVE = travel_step_key(rules.NPC_A_CODE, StepKind.NPC_TRAVEL_ARRIVE, 5)
STEP_A_TAKE = travel_step_key(rules.NPC_A_CODE, StepKind.NPC_TAKE_ITEM, 5)
STEP_B_TAKE = travel_step_key(rules.NPC_B_CODE, StepKind.NPC_TAKE_ITEM, 5)
STEP_B_USE = travel_step_key(rules.NPC_B_CODE, StepKind.NPC_USE_ITEM, 6)
STEP_INTERRUPT = travel_step_key("world", StepKind.ENVIRONMENT_INTERRUPT, 7)
STEP_B_DEPART = travel_step_key(rules.NPC_B_CODE, StepKind.NPC_TRAVEL_START, 8)
STEP_B_ARRIVE = travel_step_key(rules.NPC_B_CODE, StepKind.NPC_TRAVEL_ARRIVE, 9)


def _hidden_engine_events(time_slice: TimeSliceSession) -> List[Any]:
    return [
        event
        for event in time_slice.game_events()
        if (event.visibility_scope or "player_visible") != "player_visible"
    ]


def _movement_reports(time_slice: TimeSliceSession) -> List[Any]:
    return (
        time_slice.db.query(ValidationReportModel)
        .filter_by(session_id=time_slice.session_id, scope="movement_validation")
        .all()
    )


def _second_session(time_slice: TimeSliceSession) -> str:
    """A second session in the *same* world, for determinism comparisons."""
    suffix = uuid.uuid4().hex
    row = SessionModel(
        id=f"session-{suffix}",
        user_id=time_slice.db.query(SessionModel).get(time_slice.session_id).user_id,
        world_id=time_slice.world_id,
        status="active",
    )
    time_slice.db.add(row)
    time_slice.db.commit()
    return row.id


def _token_owner_code(time_slice: TimeSliceSession) -> str:
    """The token's owner as a *stable* slice code, not a per-session row id."""
    row = time_slice.token_owner()
    if row.owner_type == "npc":
        for spec in rules.NPC_SPECS:
            if time_slice.npc_row(spec.code).id == row.owner_ref_id:
                return f"npc:{spec.code}"
        return "npc:unknown"
    if row.owner_type == "location":
        return f"location:{time_slice.location_code(row.owner_ref_id)}"
    return f"{row.owner_type}:{row.owner_ref_id}"


# ---------------------------------------------------------------------------
# Trajectory 1: idle10 -> interrupted at +7 -> next idle
# ---------------------------------------------------------------------------


def test_trajectory_idle_is_interrupted_at_seven_and_world_advanced_offstage(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    patch_intent_stage(monkeypatch, intent_stage_result("idle"))
    result = run_turn(time_slice, "原地等待片刻")

    summary = result.time_advance_result
    assert summary["planned_elapsed_minutes"] == 10
    assert summary["actual_elapsed_minutes"] == 7
    assert summary["accepted_elapsed_minutes"] == 7
    assert summary["interrupted"] is True
    assert summary["player_action_status"] == "interrupted"
    assert result.world_time == summary["new_world_time"]
    assert (result.world_time["hour"], result.world_time["minute"]) == (8, 7)

    # The cursor, the response and the committed display time all describe the
    # same real endpoint.
    assert time_slice.run_state().logical_tick == 7
    assert time_slice.session_state().current_time.endswith("08:07")

    # The player was interrupted: the action is not reported as accepted.
    assert result.action_resolution["status"] == "rejected"
    assert result.action_resolution["reason_code"] == "target_unavailable"

    # The world moved on without the player: the token competition is settled.
    assert time_slice.npc_location_code(rules.NPC_A_CODE) == rules.LOCATION_TRIAL_PEAK
    assert time_slice.npc_location_code(rules.NPC_B_CODE) == rules.LOCATION_TRIAL_PEAK
    token = time_slice.token_owner()
    assert token.quantity == 1
    assert token.owner_type == "npc"
    assert token.owner_ref_id == time_slice.npc_row(rules.NPC_A_CODE).id

    statuses = time_slice.step_statuses()
    assert statuses[STEP_A_DEPART] == "triggered"
    assert statuses[STEP_A_ARRIVE] == "triggered"
    assert statuses[STEP_A_TAKE] == "triggered"
    assert statuses[STEP_B_TAKE] == "cancelled"
    assert statuses[STEP_B_USE] == "cancelled"
    assert statuses[STEP_INTERRUPT] == "triggered"
    assert statuses[STEP_B_DEPART] == "pending"
    assert time_slice.pending_step_keys() == [STEP_B_DEPART]

    # Off-stage work is hidden; only the perceivable interrupt is public.
    hidden_types = {event.event_type for event in _hidden_engine_events(time_slice)}
    assert {"npc_travel_started", "npc_arrived", "item_acquired", "item_take_failed",
            "item_use_failed"} <= hidden_types
    assert time_slice.game_events("world_interrupt")[0].visibility_scope == "player_visible"


def test_trajectory_idle_second_turn_resumes_future_steps_exactly_once(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    patch_intent_stage(monkeypatch, intent_stage_result("idle"))
    run_turn(time_slice, "原地等待片刻")
    assert time_slice.pending_step_keys() == [STEP_B_DEPART]

    result = run_turn(time_slice, "继续等待")

    assert result.time_advance_result["interrupted"] is False
    assert result.time_advance_result["actual_elapsed_minutes"] == 10
    assert time_slice.run_state().logical_tick == 17
    assert time_slice.npc_location_code(rules.NPC_B_CODE) == rules.LOCATION_PLAZA

    statuses = time_slice.step_statuses()
    assert statuses[STEP_B_DEPART] == "triggered"
    assert statuses[STEP_B_ARRIVE] == "triggered"
    assert time_slice.pending_step_keys() == []
    # Each future step ran exactly once, in one row each.
    assert len([r for r in time_slice.scheduled_rows()
                if r.trigger_conditions_json.get("__phase3_simulation")]) == 8
    assert len(time_slice.game_events("npc_arrived")) == 2


# ---------------------------------------------------------------------------
# Trajectory 2: inspect3 -> idle10 (resume mid-itinerary, no repeated departure)
# ---------------------------------------------------------------------------


def test_trajectory_inspect_then_idle_resumes_from_three_without_repeating_departure(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    patch_intent_stage(monkeypatch, intent_stage_result("inspect"))
    first = run_turn(time_slice, "观察四周")

    assert first.time_advance_result["actual_elapsed_minutes"] == 3
    assert time_slice.run_state().logical_tick == 3
    assert time_slice.npc_location_code(rules.NPC_A_CODE) == rules.LOCATION_PLAZA
    statuses = time_slice.step_statuses()
    assert statuses[STEP_A_DEPART] == "triggered"
    assert statuses[STEP_A_ARRIVE] == "pending"
    assert statuses[STEP_B_TAKE] == "pending"

    patch_intent_stage(monkeypatch, intent_stage_result("idle"))
    second = run_turn(time_slice, "原地等待片刻")

    # The turn starts at the persisted cursor +3 and is cut short at +7.
    assert second.time_advance_result["actual_elapsed_minutes"] == 4
    assert second.time_advance_result["interrupted"] is True
    assert time_slice.run_state().logical_tick == 7
    # The itinerary continued from +3 to +5 and the departure did not repeat.
    assert time_slice.npc_location_code(rules.NPC_A_CODE) == rules.LOCATION_TRIAL_PEAK
    assert time_slice.token_owner().owner_ref_id == time_slice.npc_row(rules.NPC_A_CODE).id
    assert len(time_slice.game_events("npc_travel_started")) == 1
    assert time_slice.step_statuses()[STEP_A_ARRIVE] == "triggered"


# ---------------------------------------------------------------------------
# Trajectory 3: move15 -> interrupted at +7 (no arrival, no task, no count)
# ---------------------------------------------------------------------------


def test_trajectory_move_is_admitted_but_interrupted_before_arrival(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    patch_intent_stage(
        monkeypatch,
        intent_stage_result("move", target_location_id=time_slice.location_id(rules.LOCATION_PLAZA)),
    )
    result = run_turn(time_slice, "前往广场")

    summary = result.time_advance_result
    assert summary["planned_elapsed_minutes"] == 15
    assert summary["actual_elapsed_minutes"] == 7
    assert summary["interrupted"] is True
    assert "arrival_task_code" not in summary

    # The move was *admitted* (no movement validation report) but did not arrive.
    assert _movement_reports(time_slice) == []
    assert result.movement_result is not None
    assert result.movement_result.success is False
    assert time_slice.player_location_code() == rules.LOCATION_MOUNTAIN_GATE
    assert time_slice.session_state().current_location_id == time_slice.location_id(
        rules.LOCATION_MOUNTAIN_GATE
    )

    assert "location_id" not in result.state_deltas
    assert result.action_resolution["status"] == "rejected"
    assert result.action_resolution["reason_code"] == "target_unavailable"
    # No success fact, no arrival fact, and the success counter stays at zero.
    assert time_slice.game_events("player_move_completed") == []
    committed = time_slice.turn_result(result.turn_no)
    assert committed["actions_committed"] == 0
    assert committed["movement_success"] is False
    assert committed["time_advance_result"]["actual_elapsed_minutes"] == 7


# ---------------------------------------------------------------------------
# Determinism and no-model guarantees
# ---------------------------------------------------------------------------


def _normalized_timeline(time_slice: TimeSliceSession) -> List[Dict[str, Any]]:
    return [
        {
            "turn_no": event.turn_no,
            "event_type": event.event_type,
            "actor_id": event.actor_id,
            "visibility_scope": event.visibility_scope,
            "tick": (event.result_json or {}).get("__phase3_simulation", {}).get("logical_tick"),
            "step_key": (event.result_json or {}).get("__phase3_simulation", {}).get("step_key"),
            "sequence": (event.result_json or {}).get("__phase3_simulation", {}).get("sequence"),
        }
        for event in time_slice.game_events()
        if (event.result_json or {}).get("__phase3_simulation")
    ]


def test_same_initial_state_and_action_produce_the_same_engine_timeline(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    patch_intent_stage(monkeypatch, intent_stage_result("idle"))
    run_turn(time_slice, "原地等待片刻")
    first_timeline = _normalized_timeline(time_slice)
    first_cursor = time_slice.run_state().logical_tick
    first_owner = _token_owner_code(time_slice)

    other_id = _second_session(time_slice)
    from llm_rpg.core import turn_service as service

    service.execute_turn_service(
        time_slice.db, other_id, "原地等待片刻", use_mock=True
    )

    other = TimeSliceSession(time_slice.db, {**time_slice.ids, "session_id": other_id})
    assert _normalized_timeline(other) == first_timeline
    assert other.run_state().logical_tick == first_cursor
    assert _token_owner_code(other) == first_owner == f"npc:{rules.NPC_A_CODE}"
    # Sequences continue monotonically from the stored cursor.
    assert [entry["sequence"] for entry in first_timeline] == list(range(len(first_timeline)))


def test_world_advances_without_any_model_call(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    """The slice must not need per-turn LLM custody: the deterministic path runs it."""
    for name in (
        "_is_input_intent_stage_enabled",
        "_is_world_stage_enabled",
        "_is_scene_stage_enabled",
        "_is_npc_stage_enabled",
        "_is_narration_stage_enabled",
        "_is_memory_stage_enabled",
    ):
        monkeypatch.setattr(turn_service, name, lambda _db: False)

    result = run_turn(time_slice, "前往广场")

    assert result.time_advance_result["interrupted"] is True
    assert result.time_advance_result["actual_elapsed_minutes"] == 7
    assert time_slice.npc_location_code(rules.NPC_A_CODE) == rules.LOCATION_TRIAL_PEAK
    assert _token_owner_code(time_slice) == f"npc:{rules.NPC_A_CODE}"
    assert (
        time_slice.db.query(ModelCallLogModel)
        .filter_by(session_id=time_slice.session_id)
        .count()
        == 0
    )


def test_clarification_turn_initializes_no_slice_rows(
    time_slice: TimeSliceSession,
) -> None:
    """A zero-time clarification must not write any baseline row (plan 3.1/4.2)."""
    result = run_turn(time_slice, "移动")

    assert result.time_advance_result["needs_clarification"] is True
    assert result.time_advance_result["accepted_elapsed_minutes"] == 0
    assert time_slice.session_state() is None
    assert time_slice.token_rows() == []
    assert time_slice.scheduled_rows() == []

    # The next real turn initializes the slice and advances it.
    follow_up = run_turn(time_slice, "观察四周")
    assert follow_up.time_advance_result["actual_elapsed_minutes"] == 3
    assert time_slice.session_state() is not None
    assert len(time_slice.token_rows()) == 1
    assert time_slice.scheduled_rows() != []
    assert time_slice.run_state().logical_tick == 3


# ---------------------------------------------------------------------------
# Truncation and calendar projection
# ---------------------------------------------------------------------------


def test_truncated_actual_duration_is_never_reclamped_to_the_category_minimum() -> None:
    """A cut-short action must not be pushed back past the interrupt tick."""
    trial_rules = rules.build_trial_rules()
    early_interrupt = ScheduledStep(
        step_key=travel_step_key("world", StepKind.ENVIRONMENT_INTERRUPT, 3),
        tick=3,
        phase=int(SimulationPhase.ENVIRONMENT),
        actor_code="world",
        kind=StepKind.ENVIRONMENT_INTERRUPT,
        payload={"one_shot_key": rules.INTERRUPT_ONE_SHOT_KEY},
    )
    result = WorldAdvancer(trial_rules).advance(
        state=trial_rules.initial_state(),
        player_action=PlayerActionSpec(
            kind=PlayerActionKind.IDLE,
            action_type="action",
            start_tick=0,
            duration_minutes=10,
        ),
        pending_steps=[early_interrupt],
    )

    assert result.actual_elapsed_minutes == 3
    summary = project_time_summary(
        result,
        planned_elapsed_minutes=10,
        original_elapsed_minutes=10,
        adjusted=False,
        reason="",
        category="unknown",
        new_world_time={"hour": 8, "minute": 3},
    )
    # The "unknown" category's minimum is 5; the actual 3 must survive untouched.
    assert summary["accepted_elapsed_minutes"] == 3
    assert summary["actual_elapsed_minutes"] == 3
    assert summary["adjusted"] is True
    assert summary["interrupted"] is True


def test_calendar_projection_rolls_midnight_and_season_from_actual_minutes() -> None:
    """The calendar is a display projection; the cursor stays ``logical_tick``."""
    before = {
        "calendar": "修仙历",
        "season": "春",
        "day": "第30日",
        "period": "亥时",
        "hour": 23,
        "minute": 30,
        "total_minutes": 29 * 1440 + 23 * 60 + 30,
    }
    after = turn_service._advance_world_time(before, elapsed_minutes=45)

    assert (after["day"], after["hour"], after["minute"]) == ("第1日", 0, 15)
    # Day 31 rolls into the next season and the day counter restarts at 1;
    # ``total_minutes`` (a season-relative value) is deliberately not used to
    # derive the cursor.
    assert after["season"] == "夏"
    assert after["period"] == "子时"


# ---------------------------------------------------------------------------
# Causality, shared-column safety and model-context whitelist
# ---------------------------------------------------------------------------


def test_every_delta_points_at_the_engine_event_of_its_own_step(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    """Events and deltas carry *independent* sequences; they must not be conflated."""
    from llm_rpg.core.time_simulation import PHASE3_NAMESPACE
    from llm_rpg.storage.models import GameEventModel, StateDeltaModel

    patch_intent_stage(monkeypatch, intent_stage_result("idle"))
    run_turn(time_slice, "原地等待片刻")

    events = {
        event.id: (event.result_json or {}).get(PHASE3_NAMESPACE, {}).get("step_key")
        for event in time_slice.db.query(GameEventModel)
        .filter_by(session_id=time_slice.session_id)
        .all()
    }
    deltas = (
        time_slice.db.query(StateDeltaModel)
        .filter_by(session_id=time_slice.session_id)
        .all()
    )
    assert deltas, "the advance must record its state changes"

    # The interrupt's delta must point at the interrupt's own fact event, not at
    # whatever event happens to share its sequence number.
    by_path = {delta.path: delta for delta in deltas}
    assert events[by_path["phase3.world.flags.trial_interrupt"].source_event_id] == STEP_INTERRUPT
    assert events[by_path["phase3.npcs.npc_a.location"].source_event_id] == STEP_A_ARRIVE
    assert events[by_path["phase3.inventory.trial_token.owner"].source_event_id] == STEP_A_TAKE


def test_legacy_hidden_plan_text_is_never_overwritten(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    """The shared column may hold another subsystem's text; it is left untouched."""
    patch_intent_stage(monkeypatch, intent_stage_result("inspect"))
    run_turn(time_slice, "观察四周")

    legacy_text = "另一个子系统的计划：去藏经阁"
    row = time_slice.npc_row(rules.NPC_B_CODE)
    row.hidden_plan_state = legacy_text
    time_slice.db.commit()

    patch_intent_stage(monkeypatch, intent_stage_result("idle"))
    run_turn(time_slice, "原地等待片刻")

    # B never started a journey in this turn (its +8 step is still pending), so the
    # slice has nothing of its own to write and must not clear the column.
    refreshed = time_slice.npc_row(rules.NPC_B_CODE)
    assert refreshed.hidden_plan_state == legacy_text


def test_world_stage_context_never_carries_internal_run_state(
    time_slice: TimeSliceSession, monkeypatch
) -> None:
    """The model context is a whitelist: internal namespaces never reach a stage."""
    from llm_rpg.core.time_simulation import PHASE3_NAMESPACE

    captured: List[Dict[str, Any]] = []
    original = turn_service._build_world_context_for_turn

    def capture(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        context = original(*args, **kwargs)
        captured.append(context)
        return context

    monkeypatch.setattr(turn_service, "_build_world_context_for_turn", capture)
    patch_intent_stage(monkeypatch, intent_stage_result("idle"))
    run_turn(time_slice, "原地等待片刻")

    assert captured, "the world context must have been built"
    for context in captured:
        flags = context.get("global_flags") or {}
        assert PHASE3_NAMESPACE not in flags
        assert not any(isinstance(key, str) and key.startswith("__") for key in flags)
    # The cursor itself is still durable; only the model-facing projection hides it.
    assert time_slice.run_state().logical_tick == 7
