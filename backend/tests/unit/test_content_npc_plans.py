from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from llm_rpg.content.compiler import compile_pack_v2
from llm_rpg.content.loader_v2 import load_pack_v2
from llm_rpg.content.runtime_models import (
    CurrentPlanState,
    PlanStatus,
    build_compiled_rules,
)
from llm_rpg.core.content_rules import CompiledContentRules
from llm_rpg.core.npc_plan_policy import evaluate_condition, select_plan


REPO_ROOT = Path(__file__).resolve().parents[2].parent


def _load_rules(name: str) -> CompiledContentRules:
    pack = load_pack_v2(REPO_ROOT / "content_packs" / name)
    bundle = compile_pack_v2(pack)
    return CompiledContentRules(build_compiled_rules(bundle.runtime_bundle, binding_hash=bundle.runtime_hash))


def _selection(rules: CompiledContentRules, state: Any, actor: str, tick: int):
    return select_plan(
        data=rules.data,
        state=state,
        actor=actor,
        tick=tick,
        completion_condition_is_true=lambda condition: evaluate_condition(
            condition, data=rules.data, state=state, actor=actor
        ),
    )


def test_goal_tie_break_priority_preconditions_and_completion_filters() -> None:
    bundle = {
        "world": {"id": "world_test", "start_tick": 0},
        "locations": [{"id": "loc"}, {"id": "other"}],
        "routes": [],
        "characters": [{"id": "npc", "initial_location_id": "loc", "alive": True}],
        "items": [],
        "initial_state": {
            "player": {"location_id": "loc", "alive": True},
            "characters": [{"id": "npc", "location_id": "loc", "alive": True}],
            "items": [], "routes": [], "flags": {"ready": False},
        },
        "rules": [], "schedules": [],
        "goals": [
            {"id": "zeta", "character_id": "npc", "priority": 30, "preconditions": None, "completion": None, "recipe": "rz"},
            {"id": "alpha", "character_id": "npc", "priority": 30, "preconditions": None, "completion": None, "recipe": "ra"},
            {"id": "high_false", "character_id": "npc", "priority": 90, "preconditions": {"type": "flag_equals", "key": "ready", "value": True}, "completion": None, "recipe": "rh"},
            {"id": "already_done", "character_id": "npc", "priority": 80, "preconditions": None, "completion": {"type": "actor_at_location", "actor": "npc", "location": "loc"}, "recipe": "rd"},
        ],
        "recipes": [
            {"id": recipe, "steps": [{"action": "wait", "target": None, "ticks": 1}]}
            for recipe in ("rz", "ra", "rh", "rd")
        ],
        "knowledge_rules": [],
    }
    rules = CompiledContentRules(build_compiled_rules(bundle, binding_hash="test"))
    state = rules.initial_state()

    # higher-priority candidates are precondition-false or already complete;
    # the equal-priority tie is resolved by lexical id.
    assert _selection(rules, state, "npc", 1).goal_id == "alpha"
    state.flags["ready"] = True
    assert _selection(rules, state, "npc", 1).goal_id == "high_false"
    state.npc_positions["npc"] = "other"
    assert _selection(rules, state, "npc", 1).goal_id == "high_false"


def test_misty_ford_fallback_at_tick_five_and_primary_goal_after_reopen() -> None:
    rules = _load_rules("misty_ford")
    state = rules.initial_state()
    state.route_overrides["east_bank->west_bank"] = False
    closed = _selection(rules, state, "ferryman", 5)
    assert closed is not None
    assert closed.goal_id == "guard_bridge"
    assert closed.action == "wait"
    assert closed.ticks == 4

    state.route_overrides["east_bank->west_bank"] = True
    reopened = _selection(rules, state, "ferryman", 9)
    assert reopened is not None
    assert reopened.goal_id == "cross_bridge"
    assert reopened.action == "move"
    assert reopened.target == "west_bank"
    assert reopened.ticks == 3


def test_working_state_nested_containers_do_not_share_mutable_objects() -> None:
    rules = _load_rules("misty_ford")
    template = rules.initial_state()
    template.flags["nested"] = {"list": [1]}
    template.npc_current_plans["ferryman"] = CurrentPlanState(
        "cross_bridge", "goal", 1, 0, "wait", None, 0, 1, PlanStatus.WAITING.value
    )
    left = template.copy()
    right = template.copy()
    assert left.flags is not right.flags
    assert left.flags["nested"] is not right.flags["nested"]
    assert left.flags["nested"]["list"] is not right.flags["nested"]["list"]
    assert left.item_instances is not right.item_instances
    assert left.npc_current_plans is not right.npc_current_plans
    assert left.npc_current_plans["ferryman"] is not right.npc_current_plans["ferryman"]
    left.flags["nested"]["list"].append(2)
    left.route_overrides["east_bank->west_bank"] = False
    assert right.flags["nested"]["list"] == [1]
    assert right.route_overrides == {}
    assert template.flags["nested"]["list"] == [1]


def test_compiled_bundle_is_deeply_immutable() -> None:
    rules = _load_rules("misty_ford")
    with pytest.raises(TypeError):
        rules.data.routes[("east_bank", "west_bank")]["open"] = False
    with pytest.raises(TypeError):
        rules.data.initial_state["flags"]["bridge_closed_once"] = True
    with pytest.raises(AttributeError):
        rules.data.binding_hash = "mutable"


def test_herbalist_plan_policy_does_not_consult_bridge_route_override() -> None:
    rules = _load_rules("misty_ford")
    state = rules.initial_state()
    selection = _selection(rules, state, "herbalist", 5)
    assert selection is not None and selection.goal_id == "gather_herbs"

    class NoRouteKnowledge(dict):
        def __contains__(self, key: object) -> bool:
            raise AssertionError("NPC policy attempted to inspect global route override")

        def get(self, key: object, default: Any = None) -> Any:
            raise AssertionError("NPC policy attempted to inspect global route override")

        def items(self):
            raise AssertionError("NPC policy attempted to inspect global route override")

    state.route_overrides = NoRouteKnowledge({"east_bank->west_bank": False})  # type: ignore[assignment]
    selection_without_route_knowledge = _selection(rules, state, "herbalist", 5)
    assert selection_without_route_knowledge == selection
