"""Unit coverage for the fixed phase-3 rule set (plan section 9.1).

These tests exercise ``TrialRules`` directly -- the domain half of the slice --
so a rule bug is reported as a rule bug instead of as an opaque turn failure.
Covered: NPC itineraries, death and blocking, the unique token's competition and
latest-owner reads, the finite one-shot interrupt, and the visibility rule.
"""

from __future__ import annotations

import pytest

from llm_rpg.core import time_simulation_rules as rules
from llm_rpg.core.time_simulation import (
    NPCTravelPlan,
    PlanStatus,
    PlayerActionKind,
    PlayerActionSpec,
    ScheduledStep,
    SimulationPhase,
    StepKind,
    StepStatus,
    TimeSimulationStateError,
    decode_npc_plan,
    decode_step_conditions,
    encode_npc_plan,
    encode_step_conditions,
    travel_step_key,
)


@pytest.fixture
def trial():
    return rules.build_trial_rules()


def _step(actor: str, kind: str, tick: int, payload: dict) -> ScheduledStep:
    return ScheduledStep(
        step_key=travel_step_key(actor, kind, tick),
        tick=tick,
        phase=int(_PHASE_BY_KIND[kind]),
        actor_code=actor,
        kind=kind,
        payload=payload,
    )


_PHASE_BY_KIND = {
    StepKind.NPC_TRAVEL_START: SimulationPhase.NPC_MOVE,
    StepKind.NPC_TRAVEL_ARRIVE: SimulationPhase.NPC_MOVE,
    StepKind.NPC_TAKE_ITEM: SimulationPhase.ITEM,
    StepKind.NPC_USE_ITEM: SimulationPhase.ITEM,
    StepKind.ENVIRONMENT_INTERRUPT: SimulationPhase.ENVIRONMENT,
    StepKind.PLAYER_CONTINUOUS_COMPLETE: SimulationPhase.PLAYER_CONTINUOUS,
}


def _idle(duration: int = 10) -> PlayerActionSpec:
    return PlayerActionSpec(
        kind=PlayerActionKind.IDLE,
        action_type="idle",
        start_tick=0,
        duration_minutes=duration,
    )


def _move(target: str, duration: int = 15) -> PlayerActionSpec:
    return PlayerActionSpec(
        kind=PlayerActionKind.MOVE,
        action_type="move",
        start_tick=0,
        duration_minutes=duration,
        target_location_code=target,
    )


# ---------------------------------------------------------------------------
# Fixed scenario data
# ---------------------------------------------------------------------------


def test_profile_marker_matches_the_frozen_structure() -> None:
    assert rules.profile_marker() == {
        "phase3_profile": {"id": "trial_micro_v1", "schema_version": 1}
    }


def test_initial_state_is_the_documented_start() -> None:
    state = rules.build_trial_rules().initial_state()

    assert state.logical_tick == rules.START_TICK
    assert state.player_location_code == rules.LOCATION_MOUNTAIN_GATE
    assert state.npc_positions == {
        rules.NPC_A_CODE: rules.LOCATION_PLAZA,
        rules.NPC_B_CODE: rules.LOCATION_TRIAL_PEAK,
    }
    assert state.item_code == rules.TOKEN_ITEM_CODE
    assert state.item_quantity == 1
    assert state.item_owner_type == "location"
    assert state.item_owner_ref == rules.LOCATION_TRIAL_PEAK
    assert state.one_shot == {}


def test_initial_schedule_is_the_documented_tick_table() -> None:
    steps = rules.build_trial_rules().initial_steps()

    assert [(s.tick, int(s.phase), s.actor_code, s.kind) for s in steps] == [
        (2, 2, rules.NPC_A_CODE, StepKind.NPC_TRAVEL_START),
        (5, 3, rules.NPC_A_CODE, StepKind.NPC_TAKE_ITEM),
        (5, 3, rules.NPC_B_CODE, StepKind.NPC_TAKE_ITEM),
        (6, 3, rules.NPC_B_CODE, StepKind.NPC_USE_ITEM),
        (7, 1, "world", StepKind.ENVIRONMENT_INTERRUPT),
        (8, 2, rules.NPC_B_CODE, StepKind.NPC_TRAVEL_START),
    ]


def test_interrupt_disabled_variant_drops_only_the_interrupt_step() -> None:
    steps = rules.build_trial_rules(interrupt_enabled=False).initial_steps()

    assert all(s.kind != StepKind.ENVIRONMENT_INTERRUPT for s in steps)
    assert len(steps) == len(rules.build_trial_rules().initial_steps()) - 1


def test_step_conditions_round_trip_through_the_namespace() -> None:
    step = rules.build_trial_rules().initial_steps()[0]
    encoded = encode_step_conditions(step)

    assert rules.PHASE3_NAMESPACE in encoded
    assert decode_step_conditions(encoded) == step


def test_npc_plan_round_trips_and_legacy_text_is_left_alone() -> None:
    plan = NPCTravelPlan(
        from_code=rules.LOCATION_PLAZA,
        to_code=rules.LOCATION_TRIAL_PEAK,
        start_tick=2,
        expected_end_tick=5,
        step_key="npc_a.npc_travel_start@2",
        status=PlanStatus.TRAVELING,
    )
    assert decode_npc_plan(encode_npc_plan(plan)) == plan
    # Another subsystem's free text is neither interpreted nor an error.
    assert decode_npc_plan("自由文本计划：去广场") is None
    assert decode_npc_plan(None) is None


# ---------------------------------------------------------------------------
# Player action classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action_type,expected",
    [
        ("move", PlayerActionKind.MOVE),
        ("follow", PlayerActionKind.MOVE),
        ("idle", PlayerActionKind.IDLE),
        ("wait", PlayerActionKind.IDLE),
        ("action", PlayerActionKind.IDLE),
        ("inspect", PlayerActionKind.INSTANT),
        ("talk", PlayerActionKind.INSTANT),
        ("attack", PlayerActionKind.INSTANT),
        (None, PlayerActionKind.INSTANT),
    ],
)
def test_action_classification(trial, action_type, expected) -> None:
    assert trial.classify_player_action(action_type) == expected


def test_completion_step_exists_only_for_continuous_actions(trial) -> None:
    assert trial.player_completion_step(_idle()).tick == 10
    assert trial.player_completion_step(_move(rules.LOCATION_PLAZA)).tick == 15
    instant = PlayerActionSpec(
        kind=PlayerActionKind.INSTANT,
        action_type="inspect",
        start_tick=0,
        duration_minutes=3,
    )
    assert trial.player_completion_step(instant) is None


# ---------------------------------------------------------------------------
# NPC itinerary
# ---------------------------------------------------------------------------


def test_travel_start_derives_the_arrival_and_marks_the_plan_traveling(trial) -> None:
    state = trial.initial_state()
    step = _step(
        rules.NPC_A_CODE,
        StepKind.NPC_TRAVEL_START,
        2,
        {"from": rules.LOCATION_PLAZA, "to": rules.LOCATION_TRIAL_PEAK, "expected_end": 5},
    )

    effect = trial.apply_step(state=state, step=step, player_action=_idle())

    assert effect.status == StepStatus.APPLIED
    assert [s.step_key for s in effect.derived_steps] == [
        travel_step_key(rules.NPC_A_CODE, StepKind.NPC_TRAVEL_ARRIVE, 5)
    ]
    plan = state.npc_plans[rules.NPC_A_CODE]
    assert plan.status == PlanStatus.TRAVELING
    # The departure alone must not move the NPC.
    assert state.npc_positions[rules.NPC_A_CODE] == rules.LOCATION_PLAZA
    assert effect.events[0].event_type == "npc_travel_started"
    assert effect.events[0].visibility_scope == "hidden"


def test_travel_start_is_visible_when_the_player_stands_at_the_origin(trial) -> None:
    state = trial.initial_state()
    state.player_location_code = rules.LOCATION_PLAZA
    step = _step(
        rules.NPC_A_CODE,
        StepKind.NPC_TRAVEL_START,
        2,
        {"from": rules.LOCATION_PLAZA, "to": rules.LOCATION_TRIAL_PEAK, "expected_end": 5},
    )

    effect = trial.apply_step(state=state, step=step, player_action=_idle())

    assert effect.events[0].visibility_scope == "player_visible"
    assert effect.events[0].public_payload["to"] == rules.LOCATION_TRIAL_PEAK


def test_arrival_moves_the_npc_and_closes_the_plan(trial) -> None:
    state = trial.initial_state()
    start = _step(
        rules.NPC_A_CODE,
        StepKind.NPC_TRAVEL_START,
        2,
        {"from": rules.LOCATION_PLAZA, "to": rules.LOCATION_TRIAL_PEAK, "expected_end": 5},
    )
    trial.apply_step(state=state, step=start, player_action=_idle())

    effect = trial.apply_step(
        state=state, step=_arrive_step(start.step_key), player_action=_idle()
    )

    assert effect.status == StepStatus.APPLIED
    assert state.npc_positions[rules.NPC_A_CODE] == rules.LOCATION_TRIAL_PEAK
    assert state.npc_plans[rules.NPC_A_CODE].status == PlanStatus.ARRIVED
    assert effect.events[0].event_type == "npc_arrived"


def _arrive_step(plan_step_key: str, tick: int = 5) -> ScheduledStep:
    return _step(
        rules.NPC_A_CODE,
        StepKind.NPC_TRAVEL_ARRIVE,
        tick,
        {
            "from": rules.LOCATION_PLAZA,
            "to": rules.LOCATION_TRIAL_PEAK,
            "plan_step_key": plan_step_key,
        },
    )


def test_npc_dying_in_transit_is_cancelled_and_not_teleported(trial) -> None:
    state = trial.initial_state()
    start = _step(
        rules.NPC_A_CODE,
        StepKind.NPC_TRAVEL_START,
        2,
        {"from": rules.LOCATION_PLAZA, "to": rules.LOCATION_TRIAL_PEAK, "expected_end": 5},
    )
    trial.apply_step(state=state, step=start, player_action=_idle())
    state.npc_alive[rules.NPC_A_CODE] = False

    effect = trial.apply_step(
        state=state, step=_arrive_step(start.step_key), player_action=_idle()
    )

    assert effect.status == StepStatus.BLOCKED
    assert effect.detail_code == "npc_died_in_transit"
    assert state.npc_positions[rules.NPC_A_CODE] == rules.LOCATION_PLAZA
    assert state.npc_plans[rules.NPC_A_CODE].status == PlanStatus.CANCELLED


def test_route_closed_mid_journey_cancels_the_arrival(trial) -> None:
    state = trial.initial_state()
    start = _step(
        rules.NPC_A_CODE,
        StepKind.NPC_TRAVEL_START,
        2,
        {"from": rules.LOCATION_PLAZA, "to": rules.LOCATION_TRIAL_PEAK, "expected_end": 5},
    )
    trial.apply_step(state=state, step=start, player_action=_idle())
    state.routes_open[rules.ROUTE_PLAZA_TO_PEAK] = False

    effect = trial.apply_step(
        state=state, step=_arrive_step(start.step_key), player_action=_idle()
    )

    assert effect.status == StepStatus.BLOCKED
    assert state.npc_positions[rules.NPC_A_CODE] == rules.LOCATION_PLAZA
    assert state.npc_plans[rules.NPC_A_CODE].status == PlanStatus.CANCELLED


def test_travel_start_is_blocked_when_the_route_is_closed(trial) -> None:
    state = trial.initial_state()
    state.routes_open[rules.ROUTE_PLAZA_TO_PEAK] = False
    step = _step(
        rules.NPC_A_CODE,
        StepKind.NPC_TRAVEL_START,
        2,
        {"from": rules.LOCATION_PLAZA, "to": rules.LOCATION_TRIAL_PEAK, "expected_end": 5},
    )

    effect = trial.apply_step(state=state, step=step, player_action=_idle())

    assert effect.status == StepStatus.BLOCKED
    assert effect.detail_code == "route_closed"
    # A journey that never started leaves no plan behind and derives no arrival.
    assert state.npc_plans[rules.NPC_A_CODE] is None
    assert effect.derived_steps == ()
    assert state.npc_positions[rules.NPC_A_CODE] == rules.LOCATION_PLAZA
    # A blocked step still leaves an audit event, but never a public one.
    assert effect.events[0].event_type == "phase3_step_blocked"
    assert effect.events[0].visibility_scope == "hidden"


def test_travel_start_is_blocked_while_already_traveling(trial) -> None:
    state = trial.initial_state()
    start = _step(
        rules.NPC_A_CODE,
        StepKind.NPC_TRAVEL_START,
        2,
        {"from": rules.LOCATION_PLAZA, "to": rules.LOCATION_TRIAL_PEAK, "expected_end": 5},
    )
    trial.apply_step(state=state, step=start, player_action=_idle())

    again = trial.apply_step(
        state=state,
        step=_step(
            rules.NPC_A_CODE,
            StepKind.NPC_TRAVEL_START,
            3,
            {"from": rules.LOCATION_PLAZA, "to": rules.LOCATION_TRIAL_PEAK, "expected_end": 6},
        ),
        player_action=_idle(),
    )

    assert again.status == StepStatus.BLOCKED
    assert again.detail_code == "already_traveling"
    assert state.npc_plans[rules.NPC_A_CODE].step_key == start.step_key


def test_travel_start_without_a_matching_plan_is_blocked(trial) -> None:
    state = trial.initial_state()
    step = _step(
        rules.NPC_A_CODE,
        StepKind.NPC_TRAVEL_ARRIVE,
        5,
        {"from": rules.LOCATION_PLAZA, "to": rules.LOCATION_TRIAL_PEAK, "plan_step_key": "nope"},
    )

    effect = trial.apply_step(state=state, step=step, player_action=_idle())

    assert effect.status == StepStatus.BLOCKED
    assert effect.detail_code == "plan_missing"


# ---------------------------------------------------------------------------
# Unique token
# ---------------------------------------------------------------------------


def test_first_taker_wins_and_the_second_is_refused_without_a_copy(trial) -> None:
    state = trial.initial_state()
    state.npc_positions[rules.NPC_A_CODE] = rules.LOCATION_TRIAL_PEAK

    first = trial.apply_step(
        state=state,
        step=_step(rules.NPC_A_CODE, StepKind.NPC_TAKE_ITEM, 5, {"item": rules.TOKEN_ITEM_CODE}),
        player_action=_idle(),
    )
    second = trial.apply_step(
        state=state,
        step=_step(rules.NPC_B_CODE, StepKind.NPC_TAKE_ITEM, 5, {"item": rules.TOKEN_ITEM_CODE}),
        player_action=_idle(),
    )

    assert first.status == StepStatus.APPLIED
    assert state.item_owner_type == "npc"
    assert state.item_owner_ref == rules.NPC_A_CODE
    assert state.item_quantity == 1
    assert second.status == StepStatus.BLOCKED
    assert second.detail_code == "item_already_owned"
    assert state.item_owner_ref == rules.NPC_A_CODE
    # The loser remembers the *latest* owner, not a stale one.
    assert "npc_a" in second.events[0].cognition[0].content


def test_use_reads_the_latest_owner_and_fails_for_the_loser(trial) -> None:
    state = trial.initial_state()
    state.item_owner_type = "npc"
    state.item_owner_ref = rules.NPC_A_CODE

    effect = trial.apply_step(
        state=state,
        step=_step(rules.NPC_B_CODE, StepKind.NPC_USE_ITEM, 6, {"item": rules.TOKEN_ITEM_CODE}),
        player_action=_idle(),
    )

    assert effect.status == StepStatus.BLOCKED
    assert effect.detail_code == "item_not_owned"
    assert effect.events[0].event_type == "item_use_failed"
    assert effect.events[0].result_json["owner_ref"] == rules.NPC_A_CODE


def test_owner_can_use_the_token_once(trial) -> None:
    state = trial.initial_state()
    state.item_owner_type = "npc"
    state.item_owner_ref = rules.NPC_A_CODE
    step = _step(rules.NPC_A_CODE, StepKind.NPC_USE_ITEM, 6, {"item": rules.TOKEN_ITEM_CODE})

    first = trial.apply_step(state=state, step=step, player_action=_idle())
    second = trial.apply_step(state=state, step=step, player_action=_idle())

    assert first.status == StepStatus.APPLIED
    assert first.events[0].event_type == "item_used"
    assert second.status == StepStatus.CANCELLED
    assert second.detail_code == "already_used"


def test_taking_from_a_wrong_location_is_blocked(trial) -> None:
    state = trial.initial_state()
    # A stays at the plaza; the token is at the peak.
    effect = trial.apply_step(
        state=state,
        step=_step(rules.NPC_A_CODE, StepKind.NPC_TAKE_ITEM, 5, {"item": rules.TOKEN_ITEM_CODE}),
        player_action=_idle(),
    )

    assert effect.status == StepStatus.BLOCKED
    assert effect.detail_code == "actor_not_at_item"
    assert state.item_owner_type == "location"


def test_broken_unique_item_quantity_is_an_error_not_a_guess(trial) -> None:
    state = trial.initial_state()
    state.item_quantity = 2

    with pytest.raises(TimeSimulationStateError):
        trial.apply_step(
            state=state,
            step=_step(rules.NPC_A_CODE, StepKind.NPC_TAKE_ITEM, 5, {"item": rules.TOKEN_ITEM_CODE}),
            player_action=_idle(),
        )


# ---------------------------------------------------------------------------
# Interrupt
# ---------------------------------------------------------------------------


def test_interrupt_fires_once_and_is_then_cancelled(trial) -> None:
    state = trial.initial_state()
    step = _step(
        "world",
        StepKind.ENVIRONMENT_INTERRUPT,
        7,
        {"one_shot_key": rules.INTERRUPT_ONE_SHOT_KEY},
    )

    first = trial.apply_step(state=state, step=step, player_action=_idle())
    second = trial.apply_step(state=state, step=step, player_action=_idle())

    assert first.status == StepStatus.APPLIED
    assert first.interrupts_player is True
    assert state.one_shot[rules.INTERRUPT_ONE_SHOT_KEY] is True
    # The bell is perceivable from anywhere in the slice; that is what makes the
    # interruption fair rather than a hidden timeout.
    assert first.events[0].visibility_scope == "player_visible"
    assert second.status == StepStatus.CANCELLED
    assert second.detail_code == "already_fired"
    assert second.interrupts_player is False


def test_interrupt_is_remembered_by_every_living_npc(trial) -> None:
    state = trial.initial_state()
    state.npc_alive[rules.NPC_B_CODE] = False

    effect = trial.apply_step(
        state=state,
        step=_step(
            "world",
            StepKind.ENVIRONMENT_INTERRUPT,
            7,
            {"one_shot_key": rules.INTERRUPT_ONE_SHOT_KEY},
        ),
        player_action=_idle(),
    )

    subjects = {draft.subject_ref for draft in effect.events[0].cognition}
    assert subjects == {rules.NPC_A_CODE}


# ---------------------------------------------------------------------------
# Player completion
# ---------------------------------------------------------------------------


def test_player_move_completion_sets_the_location_and_the_arrival_task(trial) -> None:
    state = trial.initial_state()
    action = _move(rules.LOCATION_PLAZA)
    step = trial.player_completion_step(action)

    effect = trial.apply_step(state=state, step=step, player_action=action)

    assert effect.status == StepStatus.APPLIED
    assert state.player_location_code == rules.LOCATION_PLAZA
    assert state.player_arrival_task_code == rules.ARRIVAL_TASK_BY_LOCATION[rules.LOCATION_PLAZA]
    assert effect.events[0].event_type == "player_move_completed"


def test_player_move_completion_is_blocked_when_the_route_is_closed(trial) -> None:
    state = trial.initial_state()
    state.routes_open[rules.ROUTE_GATE_TO_PLAZA] = False
    action = _move(rules.LOCATION_PLAZA)
    step = trial.player_completion_step(action)

    effect = trial.apply_step(state=state, step=step, player_action=action)

    assert effect.status == StepStatus.BLOCKED
    assert effect.detail_code == "route_closed"
    assert state.player_location_code == rules.LOCATION_MOUNTAIN_GATE
    assert state.player_arrival_task_code is None


def test_player_move_completion_rejects_a_mismatched_action_kind(trial) -> None:
    state = trial.initial_state()
    action = _move(rules.LOCATION_PLAZA)
    step = trial.player_completion_step(action)
    mismatched = _idle()

    with pytest.raises(TimeSimulationStateError):
        trial.apply_step(state=state, step=step, player_action=mismatched)


def test_unknown_step_kind_is_rejected(trial) -> None:
    with pytest.raises(TimeSimulationStateError):
        ScheduledStep(
            step_key="x.unknown@1",
            tick=1,
            phase=int(SimulationPhase.ITEM),
            actor_code="x",
            kind="not_a_kind",
            payload={},
        )
