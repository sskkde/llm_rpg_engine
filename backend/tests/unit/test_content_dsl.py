from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from llm_rpg.content.compiler import compile_pack_v2
from llm_rpg.content.loader_v2 import load_pack_v2
from llm_rpg.content.runtime_models import (
    CurrentPlanState,
    ItemInstanceState,
    build_compiled_rules,
    compile_condition,
)
from llm_rpg.core.content_rules import (
    CompiledContentRules,
    ContentPlanReevaluationBudgetError,
)
from llm_rpg.core.npc_plan_policy import ConditionValue, evaluate_condition_value
from llm_rpg.core.time_simulation import (
    MAX_STEPS_PER_ADVANCE,
    PlayerActionKind,
    PlayerActionSpec,
    ScheduledStep,
    SimulationPhase,
    StepKind,
    StepStatus,
    TimeSimulationBudgetError,
    TimeSimulationStateError,
    WorkingState,
)
from llm_rpg.core.time_simulation_rules import SimulationEventDraft, StepEffect
from llm_rpg.core.world_advancer import WorldAdvancer


REPO_ROOT = Path(__file__).resolve().parents[2].parent


def _load_rules(name: str) -> CompiledContentRules:
    pack = load_pack_v2(REPO_ROOT / "content_packs" / name)
    compiled_bundle = compile_pack_v2(pack)
    data = build_compiled_rules(compiled_bundle.runtime_bundle, binding_hash=compiled_bundle.runtime_hash)
    return CompiledContentRules(data)


def _inspect(start: int, duration: int) -> PlayerActionSpec:
    # Inspect has no turn-service proposal in this pure test; model its continuous
    # interval as an idle-shaped action so environment interrupts cancel completion.
    return PlayerActionSpec(
        kind=PlayerActionKind.IDLE,
        action_type="inspect",
        start_tick=start,
        duration_minutes=duration,
    )


def _drive(
    rules: CompiledContentRules, durations: list[int], *, continuous: bool = True
) -> tuple[WorkingState, list[Any], list[ScheduledStep], list[Any]]:
    state = rules.initial_state()
    pending = rules.initial_steps()
    consumed: set[str] = set()
    events = []
    advances = []
    for duration in durations:
        action = _inspect(state.logical_tick, duration) if continuous else PlayerActionSpec(
            kind=PlayerActionKind.INSTANT,
            action_type="inspect",
            start_tick=state.logical_tick,
            duration_minutes=duration,
        )
        result = WorldAdvancer(rules).advance(
            state=state,
            player_action=action,
            pending_steps=pending,
            consumed_step_keys=consumed,
        )
        state = result.final_state
        pending = result.pending_steps
        consumed.update(outcome.step_key for outcome in result.consumed_steps)
        events.extend(result.events)
        advances.append(result)
    return state, events, pending, advances


def _payload(event: Any) -> dict[str, Any]:
    return event.public_payload or event.private_payload or {}


def _norm(event: Any) -> tuple[str, Any, Any, Any]:
    payload = _payload(event)
    actor = payload.get("npc_id", payload.get("actor"))
    return event.event_type, actor, event.tick, payload


def _key_events(events: list[Any]) -> list[tuple[str, Any, int, Any]]:
    wanted = {
        "npc_travel_started",
        "npc_arrived",
        "item_acquired",
        "item_take_failed",
        "item_use_failed",
        "world_interrupt",
    }
    return [
        (kind, actor, tick, payload)
        for kind, actor, tick, payload in map(_norm, events)
        if kind in wanted
    ]


def _event_step(rules: CompiledContentRules, rule_id: str, tick: int) -> ScheduledStep:
    rule = next(rule for rule in rules.data.rules if rule.id == rule_id)
    return ScheduledStep(
        step_key=f"rule:{rule_id}@{tick}",
        tick=tick,
        phase=rule.trigger.phase,
        actor_code="world",
        kind=StepKind.CONTENT_RULE_FIRE,
        payload={"rule": rule_id, "occurrence": str(tick)},
    )


def test_both_shipped_packs_compile() -> None:
    for name in ("trial_micro_config", "misty_ford"):
        rules = _load_rules(name)
        assert rules.data.binding_hash
        assert rules.initial_state().logical_tick == 0
        assert rules.initial_steps()


def test_trial_micro_config_golden_trace_a_and_unique_item() -> None:
    rules = _load_rules("trial_micro_config")
    # The third interval is interrupted at +7; the fourth begins at actual_end=7.
    state, events, _pending, advances = _drive(rules, [3, 3, 3, 5])
    sequence = _key_events(events)
    assert advances[0].profile_id == "content_v1"
    assert [(advance.start_tick, advance.target_tick, advance.actual_end_tick, advance.interrupted) for advance in advances] == [
        (0, 3, 3, False),
        (3, 6, 6, False),
        (6, 9, 7, True),
        (7, 12, 12, False),
    ]
    assert [event.event_type for event in advances[3].events if event.tick in {8, 9}] == [
        "npc_travel_started", "content_rule_fired", "npc_arrived", "plan_blocked"
    ]
    assert [(kind, actor, tick) for kind, actor, tick, _payload in sequence] == [
        ("npc_travel_started", "npc_a", 2),
        ("npc_arrived", "npc_a", 5),
        ("item_acquired", None, 5),
        ("item_take_failed", "npc_b", 5),
        ("item_use_failed", "npc_b", 6),
        ("world_interrupt", None, 7),
        ("npc_travel_started", "npc_b", 8),
        ("npc_arrived", "npc_b", 9),
    ]
    assert sequence[0][3]["expected_end_tick"] == 5
    assert sequence[2][3] == {"item": "trial_token", "from": "location:trial_peak", "to": "character:npc_a"}
    assert sequence[3][3]["reason"] == "already_taken"
    assert sequence[4][3]["reason"] == "not_owner"
    assert sequence[5][3]["kind"] == "trial_bell"
    assert sequence[6][3]["expected_end_tick"] == 9
    assert state.item_instances["trial_token"] == ItemInstanceState(
        "trial_token", 1, "character", "npc_a"
    )
    assert state.item_instances["trial_token"].quantity == 1


def test_misty_ford_golden_trace_b_route_failure_fallback_and_reopen() -> None:
    # `bridge` is a location; the dynamic passage is east_bank -> west_bank.
    rules = _load_rules("misty_ford")
    state, events, _pending, advances = _drive(rules, [3, 3, 3, 3])
    assert [(advance.start_tick, advance.target_tick, advance.actual_end_tick) for advance in advances] == [
        (0, 3, 3), (3, 6, 6), (6, 9, 9), (9, 12, 12)
    ]
    normalized = [_norm(event) for event in events]
    selected = [item for item in normalized if item[0] == "plan_selected"]
    key = [
        item for item in normalized
        if item[0] in {"npc_travel_started", "route_changed", "npc_travel_failed", "npc_wait_started", "npc_wait_completed", "npc_arrived", "plan_achieved"}
        or (item[0] == "plan_selected" and item[3].get("goal_id") in {"guard_bridge", "cross_bridge"})
    ]
    assert [(kind, tick, payload.get("goal_id")) for kind, _actor, tick, payload in key if kind == "plan_selected"] == [
        ("plan_selected", 2, "cross_bridge"),
        ("plan_selected", 5, "guard_bridge"),
        ("plan_selected", 9, "cross_bridge"),
    ]
    assert [(kind, tick, payload.get("expected_end_tick"), payload.get("reason")) for kind, _actor, tick, payload in key if kind in {"npc_travel_started", "npc_travel_failed", "npc_wait_started", "npc_wait_completed", "npc_arrived", "plan_achieved", "route_changed"}] == [
        ("npc_travel_started", 2, 5, None),
        ("route_changed", 4, None, None),
        ("npc_travel_failed", 5, None, "route_closed"),
        ("npc_wait_started", 5, 9, None),
        ("route_changed", 9, None, None),
        ("npc_wait_completed", 9, None, None),
        ("npc_travel_started", 9, 12, None),
        ("npc_arrived", 12, None, None),
        ("plan_achieved", 12, None, None),
    ]
    assert next(payload for kind, _actor, _tick, payload in key if kind == "route_changed")["open"] is False
    assert [payload["open"] for kind, _actor, _tick, payload in key if kind == "route_changed"] == [False, True]
    assert state.npc_positions["ferryman"] == "west_bank"
    assert state.npc_positions["herbalist"] == "watch_house"
    assert state.route_is_open("east_bank", "west_bank") is True
    route_event = next(event for event in events if event.event_type == "route_changed")
    route_advance = next(advance for advance in advances if route_event in advance.events)
    observer_cognition = [
        draft for draft in route_advance.cognition
        if draft.event_seq == route_event.seq
        and draft.tick == route_event.tick
        and draft.source_step_code == route_event.step_code
    ]
    observers = {draft.subject_ref for draft in observer_cognition}
    assert route_event.tick == 4
    assert _payload(route_event)["from"] == "east_bank"
    # No arrival/move completion has changed either location by tick 4; later
    # in this same advance the failed tick-5 recheck leaves ferryman at east_bank.
    assert not any(event.event_type == "npc_arrived" and event.tick <= 4 for event in events)
    assert observers == {"ferryman"}
    assert "herbalist" not in observers
    # At the event tick ferryman is at east_bank and herbalist at watch_house;
    # by the advance endpoint and final trace ferryman is west_bank, proving the
    # observer set was attached to the tick-4 event, not reconstructed at end.
    assert route_advance.final_state.npc_positions == {
        "ferryman": "east_bank", "herbalist": "watch_house"
    }
    assert state.npc_positions["ferryman"] == "west_bank"
    assert all(
        not (event.event_type == "npc_travel_started" and _payload(event).get("npc_id") == "herbalist")
        for event in events
    )
    # Keep a local reference to the plan selection events to ensure the full trace
    # includes actual selected goals, not just an inferred terminal position.
    assert selected


def test_all_atomic_conditions_have_true_false_unknown_and_not_preserves_unknown() -> None:
    rules = _load_rules("trial_micro_config")
    data = rules.data
    conditions = [
        {"type": "flag_equals", "key": "trial_interrupt_fired", "value": False},
        {"type": "actor_alive", "actor": "npc_a"},
        {"type": "actor_at_location", "actor": "npc_a", "location": "plaza"},
        {"type": "route_open", "from": "mountain_gate", "to": "plaza"},
        {"type": "item_owner_is", "item": "trial_token", "owner": "location:trial_peak"},
        {"type": "item_has", "item": "trial_token", "actor": "npc_a"},
    ]
    for raw in conditions:
        state = rules.initial_state()
        if raw["type"] == "item_has":
            state.item_instances["trial_token"] = ItemInstanceState("trial_token", 1, "character", "npc_a")
        node = compile_condition(raw)
        assert evaluate_condition_value(node, data=data, state=state, actor="npc_a") is ConditionValue.TRUE
        if raw["type"] == "flag_equals":
            state.flags[raw["key"]] = True
        elif raw["type"] == "actor_alive":
            state.npc_alive[raw["actor"]] = False
        elif raw["type"] == "actor_at_location":
            state.npc_positions[raw["actor"]] = "trial_peak"
        elif raw["type"] == "route_open":
            state.route_overrides["mountain_gate->plaza"] = False
        elif raw["type"] in {"item_owner_is", "item_has"}:
            state.item_instances[raw["item"]] = ItemInstanceState("trial_token", 1, "character", "npc_b")
        assert evaluate_condition_value(node, data=data, state=state, actor="npc_a") is ConditionValue.FALSE
        if raw["type"] == "flag_equals":
            state.flags.pop(raw["key"])
        elif raw["type"] == "actor_alive":
            state.npc_alive.pop(raw["actor"])
        elif raw["type"] == "actor_at_location":
            state.npc_positions.pop(raw["actor"])
        elif raw["type"] == "route_open":
            state.route_overrides.pop("mountain_gate->plaza")
            state.routes_open.pop("mountain_gate->plaza")
        else:
            state.item_instances.pop(raw["item"])
        assert evaluate_condition_value(node, data=data, state=state, actor="npc_a") is ConditionValue.UNKNOWN
        not_node = compile_condition({"not": raw})
        assert evaluate_condition_value(not_node, data=data, state=state, actor="npc_a") is ConditionValue.UNKNOWN


def test_only_true_rule_conditions_apply_and_failing_transfer_is_atomic() -> None:
    rules = _load_rules("trial_micro_config")
    state = rules.initial_state()
    state.npc_alive["npc_a"] = False
    effect = rules.apply_step(
        state=state,
        step=_event_step(rules, "npc_a_depart", 2),
        player_action=_inspect(0, 3),
    )
    assert effect.status == StepStatus.CANCELLED
    assert state.npc_current_plans == {}

    state = rules.initial_state()
    state.item_instances["trial_token"] = ItemInstanceState("trial_token", 1, "character", "npc_a")
    state.npc_positions["npc_a"] = "trial_peak"
    state.npc_positions["npc_b"] = "trial_peak"
    before = dict(state.item_instances)
    failed = rules.apply_step(
        state=state,
        step=ScheduledStep("take-b", 5, int(SimulationPhase.ITEM), "npc_b", StepKind.NPC_TAKE_ITEM, {"item": "trial_token"}),
        player_action=_inspect(0, 5),
    )
    assert failed.status == StepStatus.BLOCKED
    assert failed.events[0].event_type == "item_take_failed"
    assert _payload(failed.events[0])["reason"] == "already_taken"
    assert state.item_instances == before


def test_route_set_open_only_mutates_session_override() -> None:
    rules = _load_rules("misty_ford")
    state = rules.initial_state()
    base_route = rules.data.routes[("east_bank", "west_bank")]
    effect = rules.apply_step(
        state=state,
        step=_event_step(rules, "close_bridge", 4),
        player_action=_inspect(0, 4),
    )
    assert effect.events[0].event_type == "route_changed"
    assert state.route_overrides["east_bank->west_bank"] is False
    assert state.routes_open["east_bank->west_bank"] is True
    assert base_route["open"] is True


def test_backwards_derived_step_is_rejected() -> None:
    class BrokenRules:
        def player_completion_step(self, action: PlayerActionSpec):
            return None

        def apply_step(self, *, state: WorkingState, step: ScheduledStep, player_action: PlayerActionSpec) -> StepEffect:
            backward = ScheduledStep("backward", step.tick - 1, int(SimulationPhase.ITEM), "world", StepKind.CONTENT_RULE_FIRE, {"rule": "x", "occurrence": "1"})
            return StepEffect(status=StepStatus.APPLIED, derived_steps=(backward,))

    state = WorkingState(logical_tick=0)
    pending = [ScheduledStep("parent", 2, int(SimulationPhase.NPC_MOVE), "world", StepKind.CONTENT_RULE_FIRE, {"rule": "x", "occurrence": "2"})]
    with pytest.raises(TimeSimulationStateError):
        WorldAdvancer(BrokenRules()).advance(state=state, player_action=PlayerActionSpec(PlayerActionKind.INSTANT, "inspect", 0, 3), pending_steps=pending)


def test_advance_step_budget_and_plan_reevaluation_budget_codes() -> None:
    class EndlessRules:
        def player_completion_step(self, action: PlayerActionSpec):
            return None

        def apply_step(self, *, state: WorkingState, step: ScheduledStep, player_action: PlayerActionSpec) -> StepEffect:
            next_tick = step.tick + 1
            return StepEffect(status=StepStatus.APPLIED, derived_steps=(ScheduledStep(f"loop-{next_tick}", next_tick, int(SimulationPhase.NPC_MOVE), "world", StepKind.CONTENT_RULE_FIRE, {"rule": "x", "occurrence": str(next_tick)}),))

    with pytest.raises(TimeSimulationBudgetError):
        WorldAdvancer(EndlessRules()).advance(
            state=WorkingState(logical_tick=0),
            player_action=PlayerActionSpec(PlayerActionKind.INSTANT, "inspect", 0, MAX_STEPS_PER_ADVANCE + 1),
            pending_steps=[ScheduledStep("loop-1", 1, int(SimulationPhase.NPC_MOVE), "world", StepKind.CONTENT_RULE_FIRE, {"rule": "x", "occurrence": "1"})],
        )

    schedules = [
        {"id": f"s{index:02d}", "character_id": "npc", "activity": "patrol", "location_id": "loc", "at_tick": 2, "window_ticks": 1, "default_activity": False}
        for index in range(65)
    ]
    bundle = {
        "world": {"id": "w", "start_tick": 0},
        "locations": [{"id": "loc"}],
        "routes": [],
        "characters": [{"id": "npc", "initial_location_id": "loc", "alive": True}],
        "items": [],
        "initial_state": {"player": {"location_id": "loc", "alive": True}, "characters": [{"id": "npc", "location_id": "loc", "alive": True}], "items": [], "routes": [], "flags": {}},
        "rules": [],
        "schedules": schedules,
        "goals": [],
        "recipes": [],
        "knowledge_rules": [],
    }
    many_schedules = CompiledContentRules(build_compiled_rules(bundle, binding_hash="test"))
    with pytest.raises(ContentPlanReevaluationBudgetError) as caught:
        WorldAdvancer(many_schedules).advance(
            state=many_schedules.initial_state(),
            player_action=_inspect(0, 3),
            pending_steps=many_schedules.initial_steps(),
        )
    assert caught.value.code == "CONTENT_PLAN_REEVAL_BUDGET"


def test_determinism_input_immutability_and_single_vs_segmented_state() -> None:
    for name in ("trial_micro_config", "misty_ford"):
        rules = _load_rules(name)
        state = rules.initial_state()
        before_state = state.copy()
        before_data = repr(rules.data)
        # §11 compares the same 0→12 interval as one segment vs four; player
        # action event counts may differ, so only world fact state is compared.
        # Instant inspect keeps the +7 interrupt event observable without asking
        # this equivalence check to compare the deliberately truncated A turn.
        one_shot_action = PlayerActionSpec(PlayerActionKind.INSTANT, "inspect", 0, 12)
        first = WorldAdvancer(rules).advance(
            state=state,
            player_action=one_shot_action,
            pending_steps=rules.initial_steps(),
        )
        second = WorldAdvancer(rules).advance(
            state=state,
            player_action=one_shot_action,
            pending_steps=rules.initial_steps(),
        )
        assert state == before_state
        assert repr(rules.data) == before_data
        assert [(_norm(event)[:3], _norm(event)[3]) for event in first.events] == [
            (_norm(event)[:3], _norm(event)[3]) for event in second.events
        ]

        segmented_state, _events, _pending, _segments = _drive(rules, [3, 3, 3, 3], continuous=False)
        assert segmented_state.npc_positions == first.final_state.npc_positions
        for route in rules.data.routes:
            source, target = route
            assert segmented_state.route_is_open(source, target) == first.final_state.route_is_open(source, target)
        assert segmented_state.item_instances == first.final_state.item_instances


def test_frozen_compiled_rule_data_rejects_mutation() -> None:
    rules = _load_rules("misty_ford")
    with pytest.raises(TypeError):
        rules.data.routes[("east_bank", "west_bank")]["open"] = False
    with pytest.raises(AttributeError):
        rules.data.binding_hash = "changed"
