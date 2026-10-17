from __future__ import annotations

from typing import Callable, Optional

import pytest

from llm_rpg.core.time_simulation import (
    ACTION_INTERRUPTED,
    PlayerActionKind,
    PlayerActionSpec,
    PlayerActionStatus,
    ScheduledStep,
    SimulationPhase,
    StepKind,
    StepStatus,
    TimeSimulationBudgetError,
    TimeSimulationStateError,
    WorkingState,
    travel_step_key,
)
from llm_rpg.core.time_simulation_rules import (
    NPC_A_CODE,
    NPC_B_CODE,
    StepEffect,
    build_trial_rules,
)
from llm_rpg.core.world_advancer import WorldAdvancer


class FakeRules:
    """Small controllable rules object for queue-boundary tests."""

    def __init__(
        self,
        effect_factory: Optional[
            Callable[[WorkingState, ScheduledStep, PlayerActionSpec], StepEffect]
        ] = None,
    ) -> None:
        self.base = build_trial_rules(interrupt_enabled=False)
        self.effect_factory = effect_factory
        self.applied: list[str] = []

    def player_completion_step(self, player_action: PlayerActionSpec):
        return self.base.player_completion_step(player_action)

    def apply_step(
        self,
        *,
        state: WorkingState,
        step: ScheduledStep,
        player_action: PlayerActionSpec,
    ) -> StepEffect:
        self.applied.append(step.step_key)
        if self.effect_factory is not None:
            return self.effect_factory(state, step, player_action)
        return StepEffect(status=StepStatus.APPLIED)


def _action(
    kind: str = PlayerActionKind.INSTANT,
    *,
    start: int = 0,
    duration: int = 5,
    target: Optional[str] = None,
) -> PlayerActionSpec:
    return PlayerActionSpec(
        kind=kind,
        action_type="test_action",
        start_tick=start,
        duration_minutes=duration,
        target_location_code=target,
    )


def _step(
    key: str,
    tick: int,
    phase: int,
    *,
    actor: str = "test_actor",
    kind: Optional[str] = None,
) -> ScheduledStep:
    default_kinds = {
        int(SimulationPhase.ENVIRONMENT): StepKind.ENVIRONMENT_INTERRUPT,
        int(SimulationPhase.NPC_MOVE): StepKind.NPC_TRAVEL_START,
        int(SimulationPhase.ITEM): StepKind.NPC_TAKE_ITEM,
        int(SimulationPhase.PLAYER_CONTINUOUS): StepKind.PLAYER_CONTINUOUS_COMPLETE,
    }
    return ScheduledStep(
        step_key=key,
        tick=tick,
        phase=phase,
        actor_code=actor,
        kind=kind or default_kinds[int(phase)],
        payload={},
    )


def test_same_tick_steps_run_in_phase_order() -> None:
    rules = FakeRules()
    state = rules.base.initial_state()
    steps = [
        _step("item", 5, SimulationPhase.ITEM, actor="c"),
        _step("npc", 5, SimulationPhase.NPC_MOVE, actor="b"),
        _step("environment", 5, SimulationPhase.ENVIRONMENT, actor="z"),
    ]

    result = WorldAdvancer(rules).advance(
        state=state,
        player_action=_action(PlayerActionKind.IDLE, duration=5),
        pending_steps=steps,
    )

    assert rules.applied == [
        "environment",
        "npc",
        "item",
        travel_step_key("player", StepKind.PLAYER_CONTINUOUS_COMPLETE, 5),
    ]
    assert result.actual_end_tick == 5


def test_same_tick_shared_state_awards_unique_token_to_first_npc() -> None:
    rules = build_trial_rules(interrupt_enabled=False)
    result = WorldAdvancer(rules).advance(
        state=rules.initial_state(),
        player_action=_action(PlayerActionKind.IDLE, duration=10),
        pending_steps=rules.initial_steps(),
    )

    assert result.final_state.npc_positions[NPC_A_CODE] == "trial_peak"
    assert result.final_state.item_quantity == 1
    assert result.final_state.item_owner_type == "npc"
    assert result.final_state.item_owner_ref == NPC_A_CODE
    contest_events = [event.event_type for event in result.events if event.tick == 5]
    assert contest_events == ["npc_arrived", "item_acquired", "item_take_failed"]
    losing_event = next(event for event in result.events if event.event_type == "item_take_failed")
    assert losing_event.result_json == {
        "status": StepStatus.BLOCKED,
        "owner_type": "npc",
        "owner_ref": NPC_A_CODE,
    }


def test_step_exactly_at_target_tick_is_processed() -> None:
    rules = FakeRules()
    step = _step("at-target", 5, SimulationPhase.ENVIRONMENT)

    result = WorldAdvancer(rules).advance(
        state=rules.base.initial_state(),
        player_action=_action(duration=5),
        pending_steps=[step],
    )

    assert rules.applied == ["at-target"]
    assert [outcome.step_key for outcome in result.consumed_steps] == ["at-target"]
    assert result.pending_steps == []


def test_pending_step_at_start_tick_raises_state_error() -> None:
    rules = FakeRules()
    with pytest.raises(TimeSimulationStateError):
        WorldAdvancer(rules).advance(
            state=rules.base.initial_state(),
            player_action=_action(start=0, duration=5),
            pending_steps=[_step("at-start", 0, SimulationPhase.ITEM)],
        )


def test_consumed_step_keys_are_skipped_from_processing_and_pending() -> None:
    rules = FakeRules()
    result = WorldAdvancer(rules).advance(
        state=rules.base.initial_state(),
        player_action=_action(duration=5),
        pending_steps=[
            _step("already-consumed-in-range", 3, SimulationPhase.ITEM),
            _step("already-consumed-future", 8, SimulationPhase.ITEM),
        ],
        consumed_step_keys={"already-consumed-in-range", "already-consumed-future"},
    )

    assert rules.applied == []
    assert result.consumed_steps == []
    assert result.pending_steps == []


def test_zero_duration_continuous_action_raises_state_error() -> None:
    rules = FakeRules()
    with pytest.raises(TimeSimulationStateError):
        WorldAdvancer(rules).advance(
            state=rules.base.initial_state(),
            player_action=_action(PlayerActionKind.IDLE, duration=0),
        )


def test_state_logical_tick_must_match_action_start() -> None:
    rules = FakeRules()
    state = rules.base.initial_state()
    state.logical_tick = 1

    with pytest.raises(TimeSimulationStateError):
        WorldAdvancer(rules).advance(
            state=state,
            player_action=_action(start=0, duration=5),
        )


def test_departure_derives_and_processes_arrival_at_target() -> None:
    rules = build_trial_rules(interrupt_enabled=False)
    departure = rules.initial_steps()[0]

    result = WorldAdvancer(rules).advance(
        state=rules.initial_state(),
        player_action=_action(duration=5),
        pending_steps=[departure],
    )

    arrival_key = travel_step_key(NPC_A_CODE, StepKind.NPC_TRAVEL_ARRIVE, 5)
    assert [outcome.step_key for outcome in result.consumed_steps] == [
        departure.step_key,
        arrival_key,
    ]
    assert result.final_state.npc_positions[NPC_A_CODE] == "trial_peak"


def test_derived_step_in_past_raises_state_error() -> None:
    parent = _step("parent", 2, SimulationPhase.NPC_MOVE)
    past = _step("past", 1, SimulationPhase.ITEM)
    rules = FakeRules(
        lambda _state, step, _action: StepEffect(
            status=StepStatus.APPLIED,
            derived_steps=(past,) if step.step_key == parent.step_key else (),
        )
    )

    with pytest.raises(TimeSimulationStateError):
        WorldAdvancer(rules).advance(
            state=rules.base.initial_state(),
            player_action=_action(duration=3),
            pending_steps=[parent],
        )


def test_same_tick_derived_earlier_phase_raises_state_error() -> None:
    parent = _step("parent", 2, SimulationPhase.NPC_MOVE)
    earlier_phase = _step("earlier", 2, SimulationPhase.ENVIRONMENT)
    rules = FakeRules(
        lambda _state, step, _action: StepEffect(
            status=StepStatus.APPLIED,
            derived_steps=(earlier_phase,) if step.step_key == parent.step_key else (),
        )
    )

    with pytest.raises(TimeSimulationStateError):
        WorldAdvancer(rules).advance(
            state=rules.base.initial_state(),
            player_action=_action(duration=3),
            pending_steps=[parent],
        )


def test_duplicate_derived_step_key_is_processed_once() -> None:
    parent = _step("parent", 2, SimulationPhase.NPC_MOVE)
    queued = _step("duplicate", 3, SimulationPhase.ITEM, actor="queued")
    derived_duplicate = _step("duplicate", 3, SimulationPhase.ITEM, actor="derived")
    rules = FakeRules(
        lambda _state, step, _action: StepEffect(
            status=StepStatus.APPLIED,
            derived_steps=(derived_duplicate,) if step.step_key == parent.step_key else (),
        )
    )

    result = WorldAdvancer(rules).advance(
        state=rules.base.initial_state(),
        player_action=_action(duration=3),
        pending_steps=[parent, queued],
    )

    assert rules.applied == ["parent", "duplicate"]
    assert [step.step_key for step in result.consumed_steps] == ["parent", "duplicate"]


def test_unbounded_derivation_exceeds_step_budget() -> None:
    def derive_forever(_state: WorkingState, step: ScheduledStep, _action: PlayerActionSpec):
        next_tick = step.tick + 1
        return StepEffect(
            status=StepStatus.APPLIED,
            derived_steps=(
                _step(f"generated-{next_tick}", next_tick, SimulationPhase.NPC_MOVE),
            ),
        )

    rules = FakeRules(derive_forever)
    with pytest.raises(TimeSimulationBudgetError):
        WorldAdvancer(rules, max_steps=2).advance(
            state=rules.base.initial_state(),
            player_action=_action(duration=10),
            pending_steps=[_step("generated-1", 1, SimulationPhase.NPC_MOVE)],
        )


def test_interrupt_cancels_completion_and_preserves_later_pending_steps() -> None:
    rules = build_trial_rules()
    steps = rules.initial_steps()
    # The fixed schedule derives +9 from +8; include an independently pending
    # +9 row here to directly verify retention of both future ticks on truncation.
    steps.append(
        ScheduledStep(
            step_key=travel_step_key(NPC_B_CODE, StepKind.NPC_TRAVEL_ARRIVE, 9),
            tick=9,
            phase=int(SimulationPhase.NPC_MOVE),
            actor_code=NPC_B_CODE,
            kind=StepKind.NPC_TRAVEL_ARRIVE,
            payload={"from": "trial_peak", "to": "mountain_gate", "plan_step_key": "later"},
        )
    )

    result = WorldAdvancer(rules).advance(
        state=rules.initial_state(),
        player_action=_action(PlayerActionKind.IDLE, duration=10),
        pending_steps=steps,
    )

    completion_key = travel_step_key("player", StepKind.PLAYER_CONTINUOUS_COMPLETE, 10)
    assert result.actual_end_tick == 7
    assert result.interrupted is True
    assert result.player_result.status == PlayerActionStatus.INTERRUPTED
    assert result.player_result.detail_code == ACTION_INTERRUPTED
    assert result.player_result.location_code == "mountain_gate"
    assert result.player_result.arrival_task_code is None
    assert result.final_state.player_location_code == "mountain_gate"
    assert result.final_state.logical_tick == 7
    cancelled = next(item for item in result.consumed_steps if item.step_key == completion_key)
    assert cancelled.status == StepStatus.CANCELLED
    assert cancelled.detail_code == ACTION_INTERRUPTED
    assert [(step.tick, step.actor_code) for step in result.pending_steps] == [
        (8, NPC_B_CODE),
        (9, NPC_B_CODE),
    ]


def test_interrupt_drains_later_phases_at_same_tick() -> None:
    interrupt_step = _step("interrupt", 3, SimulationPhase.ENVIRONMENT)
    later_step = _step("same-tick-later", 3, SimulationPhase.ITEM)
    future_step = _step("future", 4, SimulationPhase.ITEM)

    def interrupt_once(_state: WorkingState, step: ScheduledStep, _action: PlayerActionSpec):
        return StepEffect(
            status=StepStatus.APPLIED,
            interrupts_player=step.step_key == interrupt_step.step_key,
        )

    rules = FakeRules(interrupt_once)
    result = WorldAdvancer(rules).advance(
        state=rules.base.initial_state(),
        player_action=_action(PlayerActionKind.IDLE, duration=5),
        pending_steps=[future_step, later_step, interrupt_step],
    )

    assert rules.applied == ["interrupt", "same-tick-later"]
    assert result.interrupted is True
    assert result.actual_end_tick == 3
    assert [step.step_key for step in result.pending_steps] == ["future"]


def test_state_and_pending_inputs_are_not_mutated() -> None:
    rules = build_trial_rules(interrupt_enabled=False)
    state = rules.initial_state()
    before_state = state.copy()
    pending = rules.initial_steps()
    before_pending = list(pending)

    WorldAdvancer(rules).advance(
        state=state,
        player_action=_action(PlayerActionKind.IDLE, duration=10),
        pending_steps=pending,
    )

    assert state == before_state
    assert pending == before_pending


def test_instant_action_has_no_completion_and_advances_to_target() -> None:
    rules = FakeRules()
    result = WorldAdvancer(rules).advance(
        state=rules.base.initial_state(),
        player_action=_action(PlayerActionKind.INSTANT, duration=3),
    )

    assert result.actual_end_tick == 3
    assert result.player_result.status == PlayerActionStatus.COMPLETED
    assert result.consumed_steps == []
    assert rules.applied == []


def test_refused_continuous_action_skips_completion_but_advances_time() -> None:
    rules = build_trial_rules(interrupt_enabled=False)
    action = PlayerActionSpec(
        kind=PlayerActionKind.IDLE,
        action_type="wait",
        start_tick=0,
        duration_minutes=10,
        refused=True,
        detail_code="action_not_allowed",
    )

    result = WorldAdvancer(rules).advance(
        state=rules.initial_state(),
        player_action=action,
        pending_steps=rules.initial_steps(),
    )

    assert result.actual_end_tick == 10
    assert result.player_result.status == PlayerActionStatus.REFUSED
    assert result.player_result.detail_code == "action_not_allowed"
    assert all(step.kind != StepKind.PLAYER_CONTINUOUS_COMPLETE for step in result.consumed_steps)


def test_move15_completes_at_plaza_when_interrupts_disabled() -> None:
    rules = build_trial_rules(interrupt_enabled=False)
    result = WorldAdvancer(rules).advance(
        state=rules.initial_state(),
        player_action=_action(
            PlayerActionKind.MOVE,
            duration=15,
            target="plaza",
        ),
        pending_steps=rules.initial_steps(),
    )

    assert result.actual_end_tick == 15
    assert result.player_result.status == PlayerActionStatus.COMPLETED
    assert result.final_state.player_location_code == "plaza"
    assert result.player_result.location_code == "plaza"
    assert result.player_result.arrival_task_code == "task_arrive_plaza"


def test_move15_interrupted_before_completion_keeps_original_location() -> None:
    rules = build_trial_rules()
    result = WorldAdvancer(rules).advance(
        state=rules.initial_state(),
        player_action=_action(
            PlayerActionKind.MOVE,
            duration=15,
            target="plaza",
        ),
        pending_steps=rules.initial_steps(),
    )

    assert result.actual_end_tick == 7
    assert result.interrupted is True
    assert result.final_state.player_location_code == "mountain_gate"
    assert result.player_result.location_code == "mountain_gate"
    assert result.player_result.arrival_task_code is None
    assert result.player_result.status == PlayerActionStatus.INTERRUPTED


def test_event_delta_and_cognition_sequences_reference_processed_steps() -> None:
    rules = build_trial_rules(interrupt_enabled=False)
    departure = rules.initial_steps()[0]
    result = WorldAdvancer(rules).advance(
        state=rules.initial_state(),
        player_action=_action(duration=5),
        pending_steps=[departure],
    )

    assert [event.seq for event in result.events] == list(range(len(result.events)))
    assert [delta.seq for delta in result.deltas] == list(range(len(result.deltas)))
    assert [item.seq for item in result.cognition] == list(range(len(result.cognition)))
    assert result.next_event_seq == len(result.events)
    for item in result.cognition:
        event = result.events[item.event_seq]
        assert item.tick == event.tick
        assert item.source_step_code == event.step_code
    assert result.events[0].step_code == departure.step_key
    assert result.deltas[0].step_code == departure.step_key
