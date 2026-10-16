"""Integration coverage for single-point time adjudication in a turn."""

from .test_turn_service_fallback_contracts import (
    db,
    test_chapter,
    test_locations,
    test_npc_templates,
    test_player_state,
    test_quest_templates,
    test_session,
    test_session_state,
    test_user,
    test_world,
    test_save_slot,
)
from llm_rpg.core import turn_service
from llm_rpg.storage.models import EventLogModel


def test_world_stage_time_advice_is_validated_but_cannot_change_settled_time(
    db, test_session, test_session_state, test_player_state, test_locations,
    test_npc_templates, test_quest_templates, monkeypatch,
):
    settled_at = []

    def execute_stages(**_kwargs):
        return [turn_service.LLMStageResult(
            stage_name="world",
            enabled=True,
            timeout=1,
            parsed_proposal={"elapsed_minutes": 90, "time_category": "far_movement"},
            accepted=True,
        )]

    def process_scheduled_events(self, *, world_time, **_kwargs):
        settled_at.append(world_time)
        return [{"event_id": "scheduled-at-adjudicated-time"}]

    monkeypatch.setattr(turn_service, "_execute_llm_stages", execute_stages)
    monkeypatch.setattr(
        turn_service.ScheduledEventProcessor,
        "process_scheduled_events",
        process_scheduled_events,
    )

    result = turn_service.execute_turn_service(
        db, test_session.id, "观察四周", use_mock=True
    )

    assert settled_at, "scheduler must settle after time-advice validation"
    assert result.world_time == result.time_advance_result["new_world_time"]
    assert result.time_advance_result["accepted_elapsed_minutes"] == 3
    assert result.time_advance_result["world_stage_suggestion"]["validated_elapsed_minutes"] == 90
    assert result.time_advance_result["world_stage_suggestion"]["adopted"] is False
    assert settled_at[0].minute == result.world_time["minute"]

    event = db.query(EventLogModel).filter_by(
        session_id=test_session.id, turn_no=result.turn_no, event_type="player_turn"
    ).one()
    assert event.result_json["world_time"] == result.world_time
    assert event.result_json["time_advance_result"] == result.time_advance_result


def test_failed_action_keeps_existing_action_type_time_rule():
    # Existing behavior derives time from action type, not its success flag.
    assert turn_service._resolve_elapsed_minutes(action_type="attack") == 5


def test_unrecognized_intent_keeps_existing_unknown_category_time_rule(
    db, test_session, test_session_state, test_player_state, test_locations,
    test_npc_templates, test_quest_templates, monkeypatch,
):
    before = turn_service._get_world_time(test_session_state)
    monkeypatch.setattr(
        turn_service,
        "_execute_input_intent_stage",
        lambda **_kwargs: turn_service.LLMStageResult(
            stage_name="input_intent", enabled=False, timeout=1,
            accepted=False, fallback_reason="unrecognized",
        ),
    )
    monkeypatch.setattr(turn_service, "_execute_llm_stages", lambda **_kwargs: [])

    result = turn_service.execute_turn_service(
        db, test_session.id, "qzxv nonsense", use_mock=True
    )

    assert result.world_time != before
    assert result.time_advance_result["accepted_elapsed_minutes"] > 0


def test_deterministic_fallback_wait_advances_time_and_creates_delta(
    db, test_session, test_session_state, test_player_state, test_locations,
    test_npc_templates, test_quest_templates,
):
    from llm_rpg.storage.models import StateDeltaModel

    before = turn_service._get_world_time(test_session_state)
    result = turn_service.execute_turn_service(
        db, test_session.id, player_input="我等待",
        idempotency_key="fallback_wait_time_regression",
    )

    assert result.time_advance_result["accepted_elapsed_minutes"] > 0
    assert result.world_time != before
    deltas = db.query(StateDeltaModel).filter_by(
        session_id=test_session.id, turn_no=result.turn_no,
    ).all()
    assert any("time" in delta.path for delta in deltas)
