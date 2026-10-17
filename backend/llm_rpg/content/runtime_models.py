"""Immutable compiled runtime models for the content_v1 pure rules layer.

This module deliberately imports no ``core`` module: compiled configuration is
an immutable boundary between content validation and the simulation kernel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple

from llm_rpg.models.content_v2 import ContentV2Error


@dataclass(frozen=True)
class ItemInstanceState:
    code: str
    quantity: int
    owner_type: str  # "player" | "location" | "character"
    owner_ref: str


class PlanStatus(str, Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    TRAVELING = "traveling"
    WAITING = "waiting"
    BLOCKED = "blocked"
    ACHIEVED = "achieved"
    FAILED = "failed"


@dataclass(frozen=True)
class CurrentPlanState:
    goal_id: str
    source: str  # "goal" | "schedule"
    generation: int
    recipe_step: int
    action: str  # move|wait|take|use|transfer
    target: Optional[str]
    start_tick: int
    expected_end_tick: int
    status: str
    failure_code: Optional[str] = None


@dataclass(frozen=True)
class CompiledTrigger:
    kind: str  # "on_time_crossed" | "on_action_completed"
    due_tick: Optional[int]
    phase: int
    action: Optional[str]
    actor: Optional[str]
    location: Optional[str]


@dataclass(frozen=True)
class CompiledRule:
    id: str
    priority: int
    trigger: CompiledTrigger
    condition: Any
    effects: tuple
    fire_mode: str  # "once_per_instance" | "once_per_source_event"


@dataclass(frozen=True)
class CompiledContentRulesData:
    binding_hash: str
    world: Mapping[str, Any]
    locations: Mapping[str, Mapping[str, Any]]
    routes: Mapping[Tuple[str, str], Mapping[str, Any]]
    characters: Mapping[str, Mapping[str, Any]]
    items: Mapping[str, Mapping[str, Any]]
    declared_flags: Mapping[str, Any]
    rules: Tuple[CompiledRule, ...]
    schedules: Tuple[Mapping[str, Any], ...]
    goals: Tuple[Mapping[str, Any], ...]
    recipes: Mapping[str, Mapping[str, Any]]
    knowledge_rules: Tuple[Mapping[str, Any], ...]
    initial_state: Mapping[str, Any]

    def location_ids(self) -> frozenset[str]:
        return frozenset(self.locations)

    def character_ids(self) -> frozenset[str]:
        return frozenset(self.characters)

    def item_ids(self) -> frozenset[str]:
        return frozenset(self.items)


# The profile's phase names intentionally map to literal frozen contract values;
# importing SimulationPhase here would create a content -> core dependency.
_PHASE_BY_NAME = {
    "environment": 1,
    "npc_move": 2,
    "item": 3,
    "player_continuous": 4,
}
_CONDITION_TYPES = frozenset(
    {
        "flag_equals",
        "actor_alive",
        "actor_at_location",
        "route_open",
        "item_owner_is",
        "item_has",
    }
)
_EFFECT_TYPES = frozenset(
    {
        "flag_set",
        "route_set_open",
        "npc_action_start",
        "plan_start",
        "item_transfer",
        "item_use",
        "interrupt",
        "emit_event",
        "event_schedule",
    }
)
_FIRE_MODES = frozenset({"once_per_instance", "once_per_source_event"})
_EVENT_PAYLOAD_KEYS = {
    "content_rule_fired": frozenset({"rule", "occurrence", "tick", "effects_applied"}),
    "route_changed": frozenset({"from", "to", "open", "tick"}),
    "flag_changed": frozenset({"key", "old_value", "new_value", "tick"}),
    "npc_travel_started": frozenset({"npc_id", "from", "to", "expected_end_tick"}),
    "npc_arrived": frozenset({"npc_id", "from", "to"}),
    "npc_wait_started": frozenset({"npc_id", "location", "expected_end_tick"}),
    "npc_wait_completed": frozenset({"npc_id", "location"}),
    "npc_travel_failed": frozenset({"npc_id", "from", "to", "reason"}),
    "item_acquired": frozenset({"item", "from", "to"}),
    "item_take_failed": frozenset({"item", "actor", "reason"}),
    "item_used": frozenset({"item", "actor", "effect"}),
    "item_use_failed": frozenset({"item", "actor", "reason"}),
    "world_interrupt": frozenset({"kind", "message", "tick"}),
    "plan_selected": frozenset(
        {"npc_id", "goal_id", "priority", "source", "generation", "recipe_step", "action", "target", "expected_end_tick"}
    ),
    "plan_failed": frozenset({"npc_id", "goal_id", "generation", "recipe_step", "failure_code"}),
    "plan_achieved": frozenset({"npc_id", "goal_id", "generation"}),
    "plan_blocked": frozenset({"npc_id", "reason"}),
    "player_move_completed": frozenset({"from", "to", "arrival_task", "tick"}),
    "player_action_completed": frozenset({"action_type", "action_kind", "tick"}),
}
_RULE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _unsupported(path: str, message: str) -> ContentV2Error:
    return ContentV2Error("CONTENT_UNSUPPORTED_FEATURE", path, message)


def _plain(value: Any) -> Any:
    """Normalize StrictModel/enum values to their canonical JSON-shaped form."""
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if hasattr(value, "root") and not isinstance(value, Mapping):
        return _plain(value.root)
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _freeze(value: Any) -> Any:
    """Recursively freeze arbitrary canonical JSON values."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child) for child in value)
    return value


_MAPPING_MARKER = "__content_v1_mapping__"


def _freeze_tree(value: Any) -> Any:
    """Return an unambiguous, hash-safe tuple tree for condition/effect values."""
    if isinstance(value, Mapping):
        return (_MAPPING_MARKER, tuple((key, _freeze_tree(child)) for key, child in sorted(value.items())))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_tree(child) for child in value)
    return value


def _fields(node: Any, *, path: str) -> dict[str, Any]:
    value = _plain(node)
    if not isinstance(value, Mapping):
        raise _unsupported(path, "expected an object node")
    return dict(value)


def compile_condition(node: Any) -> Any:
    """Compile a supported condition into a frozen ``(operator, args)`` tree."""
    node_count = 0

    def compile_node(current: Any, depth: int) -> Any:
        nonlocal node_count
        node_count += 1
        if depth > 8:
            raise ContentV2Error("CONTENT_CONDITION_TOO_DEEP", "condition", "condition depth exceeds 8")
        if node_count > 128:
            raise ContentV2Error("CONTENT_CONDITION_TOO_LARGE", "condition", "condition node count exceeds 128")
        if current is None:
            return ("const", True)
        if isinstance(current, tuple) and current and isinstance(current[0], str):
            return current
        value = _fields(current, path="condition")
        compound_keys = [key for key in ("all", "any", "not") if key in value]
        if compound_keys:
            if len(compound_keys) != 1:
                raise _unsupported("condition", "compound condition operators are mutually exclusive")
            operator = compound_keys[0]
            if set(value) != {operator}:
                raise _unsupported("condition", f"unknown compound fields: {sorted(set(value) - {operator})}")
            if operator in {"all", "any"}:
                children = value[operator]
                if not isinstance(children, (list, tuple)) or not children:
                    raise _unsupported(f"condition.{operator}", "expected a non-empty list")
                return (operator, tuple(compile_node(child, depth + 1) for child in children))
            return ("not", compile_node(value["not"], depth + 1))

        condition_type = value.get("type")
        if condition_type not in _CONDITION_TYPES:
            raise _unsupported("condition.type", f"unknown condition type {condition_type!r}")
        expected_fields = {
            "flag_equals": {"type", "key", "value"},
            "actor_alive": {"type", "actor"},
            "actor_at_location": {"type", "actor", "location"},
            "route_open": {"type", "from", "to"},
            "item_owner_is": {"type", "item", "owner"},
            "item_has": {"type", "item", "actor"},
        }[condition_type]
        unknown = set(value) - expected_fields
        if unknown:
            raise _unsupported("condition", f"unknown fields: {sorted(unknown)}")
        args = tuple((key, _freeze_tree(child)) for key, child in sorted(value.items()) if key != "type")
        return (condition_type, args)

    return compile_node(node, 1)


def compile_effect(effect: Any) -> Any:
    """Compile a supported effect into an immutable operator/field tuple."""
    value = _fields(effect, path="effect")
    effect_type = value.get("type")
    if effect_type not in _EFFECT_TYPES:
        raise _unsupported("effect.type", f"unknown effect type {effect_type!r}")
    expected_fields = {
        "flag_set": {"type", "key", "value"},
        "route_set_open": {"type", "from", "to", "open"},
        "npc_action_start": {"type", "actor", "action", "target", "ticks"},
        "plan_start": {"type", "actor", "goal"},
        "item_transfer": {"type", "item", "to"},
        "item_use": {"type", "item", "actor"},
        "interrupt": {"type", "kind", "message"},
        "emit_event": {"type", "event_type", "payload"},
        "event_schedule": {"type", "rule", "tick"},
    }[effect_type]
    unknown = set(value) - expected_fields
    if unknown:
        raise _unsupported("effect", f"unknown fields: {sorted(unknown)}")
    if effect_type == "npc_action_start" and value.get("action") not in {"move", "wait"}:
        raise _unsupported("effect.action", f"unknown NPC action {value.get('action')!r}")
    if effect_type == "emit_event":
        event_type = value.get("event_type")
        allowed = _EVENT_PAYLOAD_KEYS.get(event_type)
        payload = value.get("payload", {})
        if allowed is None:
            raise _unsupported("effect.event_type", f"event type {event_type!r} is not in the frozen vocabulary")
        if not isinstance(payload, Mapping) or set(payload) != allowed:
            raise _unsupported(
                "effect.payload",
                f"{event_type!r} payload must have exactly {sorted(allowed)}",
            )
    args = tuple((key, _freeze_tree(child)) for key, child in sorted(value.items()) if key != "type")
    return (effect_type, args)


def _argument_map(node: Any) -> dict[str, Any]:
    return dict(node[1])


def _flag_condition_keys(node: Any) -> tuple[str, ...]:
    operator, args = node
    if operator == "flag_equals":
        return (str(_argument_map(node).get("key")),)
    if operator in {"all", "any"}:
        return tuple(key for child in args for key in _flag_condition_keys(child))
    if operator == "not":
        return _flag_condition_keys(args)
    return ()


def _thaw_tree(value: Any) -> Any:
    if isinstance(value, tuple) and len(value) == 2 and value[0] == _MAPPING_MARKER:
        return {key: _thaw_tree(child) for key, child in value[1]}
    if isinstance(value, tuple):
        return [_thaw_tree(child) for child in value]
    return value


def _raw_effect_args(effect: Any) -> dict[str, Any]:
    return {key: _thaw_tree(value) for key, value in effect[1]}


def build_compiled_rules(
    runtime_bundle: Mapping[str, Any], *, binding_hash: str
) -> CompiledContentRulesData:
    """Build a deeply immutable execution model from the canonical runtime bundle."""
    if not isinstance(runtime_bundle, Mapping):
        raise ContentV2Error("CONTENT_TYPE_ERROR", "runtime_bundle", "expected a mapping")
    bundle = _plain(runtime_bundle)
    world = bundle.get("world", {})
    locations = {entry["id"]: entry for entry in bundle.get("locations", [])}
    characters = {entry["id"]: entry for entry in bundle.get("characters", [])}
    items = {entry["id"]: entry for entry in bundle.get("items", [])}
    initial_state = bundle.get("initial_state", {})
    declared_flags = initial_state.get("flags", {})

    directed_routes: dict[tuple[str, str], dict[str, Any]] = {}
    for index, route in enumerate(bundle.get("routes", [])):
        source = route.get("from", route.get("from_"))
        target = route.get("to")
        if not isinstance(source, str) or not isinstance(target, str):
            raise ContentV2Error("CONTENT_TYPE_ERROR", f"routes.{index}", "route endpoints must be strings")
        normalized = dict(route)
        normalized["from"] = source
        normalized["to"] = target
        normalized["bidirectional"] = False
        directed_routes[(source, target)] = normalized
        if route.get("bidirectional") is True and source != target:
            reverse = dict(normalized)
            reverse["from"], reverse["to"] = target, source
            directed_routes[(target, source)] = reverse

    rule_specs: dict[str, Mapping[str, Any]] = {}
    rules: list[CompiledRule] = []
    for index, raw_rule in enumerate(bundle.get("rules", [])):
        path = f"rules.{index}"
        rule_id = raw_rule.get("id")
        if not isinstance(rule_id, str) or not _RULE_ID.fullmatch(rule_id) or rule_id in {"player", "world"}:
            raise _unsupported(f"{path}.id", f"unknown or invalid rule id {rule_id!r}")
        if rule_id in rule_specs:
            raise _unsupported(f"{path}.id", f"duplicate rule id {rule_id!r}")
        rule_specs[rule_id] = raw_rule

    for index, raw_rule in enumerate(bundle.get("rules", [])):
        path = f"rules.{index}"
        rule_id = raw_rule["id"]
        trigger = raw_rule.get("trigger")
        if not isinstance(trigger, Mapping):
            raise _unsupported(f"{path}.trigger", "trigger must be an object")
        trigger_type = trigger.get("type")
        if trigger_type == "on_time_crossed":
            phase_name = trigger.get("phase", "environment")
            phase = _PHASE_BY_NAME.get(phase_name)
            if phase is None:
                raise _unsupported(f"{path}.trigger.phase", f"unknown trigger phase {phase_name!r}")
            compiled_trigger = CompiledTrigger(
                kind=trigger_type,
                due_tick=trigger.get("due_tick"),
                phase=phase,
                action=None,
                actor=None,
                location=None,
            )
        elif trigger_type == "on_action_completed":
            action = trigger.get("action")
            actor = trigger.get("actor")
            if action not in {"move", "idle"} or not isinstance(actor, str):
                raise _unsupported(f"{path}.trigger", "invalid on_action_completed trigger")
            # Player continuous completions use phase 4; NPC move/wait completion
            # is phase 2, matching the frozen schedule vocabulary.
            phase = 4 if actor == "player" else 2
            compiled_trigger = CompiledTrigger(
                kind=trigger_type,
                due_tick=None,
                phase=phase,
                action=action,
                actor=actor,
                location=trigger.get("location"),
            )
        else:
            raise _unsupported(f"{path}.trigger.type", f"unknown trigger type {trigger_type!r}")

        fire_policy = raw_rule.get("fire_policy", {})
        fire_mode = fire_policy.get("mode") if isinstance(fire_policy, Mapping) else None
        if fire_mode not in _FIRE_MODES:
            raise _unsupported(f"{path}.fire_policy.mode", f"unknown fire mode {fire_mode!r}")

        condition = compile_condition(raw_rule.get("condition"))
        for key in _flag_condition_keys(condition):
            if key not in declared_flags:
                raise ContentV2Error("CONTENT_UNDECLARED_FLAG", f"{path}.condition.key", f"flag {key!r} is not declared")
        effects = []
        for effect_index, raw_effect in enumerate(raw_rule.get("effects", [])):
            compiled_effect = compile_effect(raw_effect)
            effect_args = _argument_map(compiled_effect)
            if compiled_effect[0] == "flag_set" and effect_args.get("key") not in declared_flags:
                raise ContentV2Error(
                    "CONTENT_UNDECLARED_FLAG",
                    f"{path}.effects.{effect_index}.key",
                    f"flag {effect_args.get('key')!r} is not declared",
                )
            effects.append(compiled_effect)
        if raw_rule.get("enabled", True) is True:
            rules.append(
                CompiledRule(
                    id=rule_id,
                    priority=int(raw_rule.get("priority", 0)),
                    trigger=compiled_trigger,
                    condition=condition,
                    effects=tuple(effects),
                    fire_mode=fire_mode,
                )
            )

    active_rule_ids = {rule.id for rule in rules}
    for recipe_index, recipe in enumerate(bundle.get("recipes", [])):
        if len(recipe.get("steps", ())) > 16:
            raise ContentV2Error("CONTENT_RECIPE_TOO_LONG", f"recipes.{recipe_index}.steps", "recipe exceeds 16 steps")
    for rule in rules:
        for effect in rule.effects:
            if effect[0] == "event_schedule":
                target_rule = _argument_map(effect).get("rule")
                if target_rule not in active_rule_ids:
                    raise _unsupported(f"rules.{rule.id}.effects", f"unknown scheduled rule id {target_rule!r}")
                target = next(candidate for candidate in rules if candidate.id == target_rule)
                if target.trigger.kind != "on_time_crossed":
                    raise _unsupported(
                        f"rules.{rule.id}.effects",
                        "event_schedule may target only an on_time_crossed rule",
                    )

    data = CompiledContentRulesData(
        binding_hash=str(binding_hash),
        world=_freeze(world),
        locations=_freeze(locations),
        routes=_freeze(directed_routes),
        characters=_freeze(characters),
        items=_freeze(items),
        declared_flags=_freeze(declared_flags),
        rules=tuple(rules),
        schedules=tuple(_freeze(entry) for entry in bundle.get("schedules", [])),
        goals=tuple(_freeze(entry) for entry in bundle.get("goals", [])),
        recipes=_freeze({entry["id"]: entry for entry in bundle.get("recipes", [])}),
        knowledge_rules=tuple(_freeze(entry) for entry in bundle.get("knowledge_rules", [])),
        initial_state=_freeze(initial_state),
    )
    return data


__all__ = [
    "ItemInstanceState",
    "PlanStatus",
    "CurrentPlanState",
    "CompiledTrigger",
    "CompiledRule",
    "CompiledContentRulesData",
    "build_compiled_rules",
    "compile_condition",
    "compile_effect",
]
