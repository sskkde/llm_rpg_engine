"""Deterministic, finite Schedule/Goal/CurrentPlan selection policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Optional

from llm_rpg.content.runtime_models import CompiledContentRulesData, compile_condition


class ConditionValue(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PlanSelection:
    goal_id: str
    source: str
    recipe_step: int
    action: str
    target: Optional[str]
    ticks: int


def _attr_or_item(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _condition_args(node: Any) -> dict[str, Any]:
    return dict(node[1])


def _owner_parts(owner: Any) -> Optional[tuple[str, str]]:
    if owner == "player":
        return ("player", "player")
    if isinstance(owner, str) and ":" in owner:
        owner_type, owner_ref = owner.split(":", 1)
        if owner_type in {"location", "character"} and owner_ref:
            return owner_type, owner_ref
    return None


def evaluate_condition_value(
    node: Any,
    *,
    data: CompiledContentRulesData,
    state: Any,
    actor: str,
) -> ConditionValue:
    """Evaluate all closed DSL conditions using three-valued logic."""
    if node is None:
        return ConditionValue.TRUE
    if not (isinstance(node, tuple) and len(node) == 2 and isinstance(node[0], str)):
        node = compile_condition(node)
    operator, raw_args = node

    if operator == "const":
        return ConditionValue.TRUE if raw_args is True else ConditionValue.FALSE
    if operator == "not":
        child = evaluate_condition_value(raw_args, data=data, state=state, actor=actor)
        if child is ConditionValue.UNKNOWN:
            return child
        return ConditionValue.FALSE if child is ConditionValue.TRUE else ConditionValue.TRUE
    if operator in {"all", "any"}:
        values = [
            evaluate_condition_value(child, data=data, state=state, actor=actor)
            for child in raw_args
        ]
        if operator == "all":
            if ConditionValue.FALSE in values:
                return ConditionValue.FALSE
            return ConditionValue.TRUE if all(value is ConditionValue.TRUE for value in values) else ConditionValue.UNKNOWN
        if ConditionValue.TRUE in values:
            return ConditionValue.TRUE
        return ConditionValue.FALSE if all(value is ConditionValue.FALSE for value in values) else ConditionValue.UNKNOWN

    args = _condition_args(node)
    if operator == "flag_equals":
        flags = _attr_or_item(state, "flags", {})
        key = args["key"]
        if key not in flags:
            return ConditionValue.UNKNOWN
        return ConditionValue.TRUE if flags[key] == args["value"] else ConditionValue.FALSE

    if operator == "actor_alive":
        subject = args["actor"]
        if subject == "player":
            value = _attr_or_item(state, "player_alive")
        else:
            alive = _attr_or_item(state, "npc_alive", {})
            value = alive.get(subject) if isinstance(alive, Mapping) else None
        if value is None:
            return ConditionValue.UNKNOWN
        return ConditionValue.TRUE if value is True else ConditionValue.FALSE

    if operator == "actor_at_location":
        subject = args["actor"]
        if subject == "player":
            location = _attr_or_item(state, "player_location_code")
        else:
            positions = _attr_or_item(state, "npc_positions", {})
            location = positions.get(subject) if isinstance(positions, Mapping) else None
        if location is None or location == "":
            return ConditionValue.UNKNOWN
        return ConditionValue.TRUE if location == args["location"] else ConditionValue.FALSE

    if operator == "route_open":
        source, target = args["from"], args["to"]
        key = f"{source}->{target}"
        overrides = _attr_or_item(state, "route_overrides", {})
        routes_open = _attr_or_item(state, "routes_open", {})
        if isinstance(overrides, Mapping) and key in overrides:
            opened = overrides[key]
        elif isinstance(routes_open, Mapping) and key in routes_open:
            opened = routes_open[key]
        else:
            return ConditionValue.UNKNOWN
        if opened is None:
            return ConditionValue.UNKNOWN
        return ConditionValue.TRUE if opened is True else ConditionValue.FALSE

    if operator in {"item_owner_is", "item_has"}:
        item_instances = _attr_or_item(state, "item_instances", {})
        item = item_instances.get(args["item"]) if isinstance(item_instances, Mapping) else None
        if item is None:
            return ConditionValue.UNKNOWN
        owner_type = _attr_or_item(item, "owner_type")
        owner_ref = _attr_or_item(item, "owner_ref")
        if owner_type is None or owner_ref is None:
            return ConditionValue.UNKNOWN
        if operator == "item_owner_is":
            expected = _owner_parts(args["owner"])
            if expected is None:
                return ConditionValue.UNKNOWN
            return (
                ConditionValue.TRUE
                if (owner_type, owner_ref) == expected
                else ConditionValue.FALSE
            )
        subject = args["actor"]
        if subject != "player" and subject not in data.character_ids():
            return ConditionValue.UNKNOWN
        owns = (owner_type, owner_ref) == (("player", "player") if subject == "player" else ("character", subject))
        return ConditionValue.TRUE if owns else ConditionValue.FALSE

    # The compiler rejects this branch; keep runtime evaluation fail-closed.
    return ConditionValue.UNKNOWN


def evaluate_condition(
    node: Any,
    *,
    data: CompiledContentRulesData,
    state: Any,
    actor: str,
) -> bool:
    """Convenience predicate that treats FALSE and UNKNOWN as not satisfied."""
    return evaluate_condition_value(node, data=data, state=state, actor=actor) is ConditionValue.TRUE


def _route_ticks(data: CompiledContentRulesData, state: Any, actor: str, target: str) -> int:
    positions = _attr_or_item(state, "npc_positions", {})
    source = positions.get(actor) if isinstance(positions, Mapping) else None
    route = data.routes.get((source, target)) if source is not None else None
    ticks = route.get("travel_ticks") if route is not None else None
    return ticks if isinstance(ticks, int) and not isinstance(ticks, bool) and ticks > 0 else 1


def select_plan(
    *,
    data: CompiledContentRulesData,
    state: Any,
    actor: str,
    tick: int,
    completion_condition_is_true: Callable[[Any], bool],
) -> Optional[PlanSelection]:
    """Apply the frozen goal filter and priority/id tie-break for one actor."""
    candidates = []
    for goal in data.goals:
        goal_actor = goal.get("character_id")
        if goal_actor is not None and goal_actor != actor:
            continue
        if not evaluate_condition(goal.get("preconditions"), data=data, state=state, actor=actor):
            continue
        completion = goal.get("completion")
        if completion is not None and completion_condition_is_true(completion):
            continue
        candidates.append(goal)
    if not candidates:
        return None

    chosen = sorted(candidates, key=lambda item: (-int(item.get("priority", 0)), str(item["id"])))[0]
    recipe_id = chosen.get("recipe")
    recipe = data.recipes.get(recipe_id)
    if recipe is None:
        raise ValueError(f"goal {chosen['id']!r} references missing recipe {recipe_id!r}")
    steps = recipe.get("steps", ())
    if not steps:
        raise ValueError(f"recipe {recipe_id!r} has no first step")
    first = steps[0]
    action = first.get("action")
    if hasattr(action, "value"):
        action = action.value
    target = first.get("target")
    ticks = first.get("ticks")
    if ticks is None:
        ticks = _route_ticks(data, state, actor, target) if action == "move" and target else 1
    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 1:
        raise ValueError(f"recipe {recipe_id!r} has invalid first-step ticks {ticks!r}")
    return PlanSelection(
        goal_id=str(chosen["id"]),
        source="goal",
        recipe_step=0,
        action=str(action),
        target=target,
        ticks=ticks,
    )


__all__ = [
    "ConditionValue",
    "PlanSelection",
    "evaluate_condition_value",
    "evaluate_condition",
    "select_plan",
]
