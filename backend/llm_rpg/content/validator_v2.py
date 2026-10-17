"""Compile-time reference and cross-section validation for content v2 packs."""

from __future__ import annotations

from collections import defaultdict
from string import Formatter
from typing import Any

from pydantic import RootModel

from llm_rpg.models.content_v2 import (
    ActorAliveConditionDef,
    ActorAtLocationConditionDef,
    ConditionAllDef,
    ConditionAnyDef,
    ConditionDef,
    ConditionNotDef,
    ContentPackV2,
    ContentV2Error,
    EventScheduleEffectDef,
    FlagEqualsConditionDef,
    FlagSetEffectDef,
    ItemHasConditionDef,
    ItemOwnerIsConditionDef,
    ItemTransferEffectDef,
    ItemUseEffectDef,
    NpcActionStartEffectDef,
    PlanStartEffectDef,
    RouteOpenConditionDef,
    RouteSetOpenEffectDef,
    TriggerDef,
)

_ALLOWED_PLACEHOLDERS = {"actor", "target", "item", "location"}


def _unwrap_root(value: Any) -> Any:
    return value.root if isinstance(value, RootModel) else value


def validate_pack_v2(pack: ContentPackV2) -> list[ContentV2Error]:
    """Return all detected content errors without stopping at the first one."""
    issues: list[ContentV2Error] = []
    all_ids: dict[str, tuple[str, str]] = {}
    kinds_by_id: dict[str, set[str]] = defaultdict(set)

    def add_identity(object_id: str, kind: str, path: str) -> None:
        prior = all_ids.get(object_id)
        if prior is not None:
            issues.append(ContentV2Error(
                "CONTENT_DUPLICATE_ID",
                path,
                f"id {object_id!r} duplicates {prior[0]!r} at {prior[1]}",
            ))
        else:
            all_ids[object_id] = (kind, path)
        kinds_by_id[object_id].add(kind)

    # Only authored definitions participate in reference-kind resolution.
    add_identity(pack.world.id, "world", "world.id")
    for kind, section in (
        ("location", "locations"),
        ("character", "characters"),
        ("item", "items"),
        ("rule", "rules"),
        ("schedule", "schedules"),
        ("goal", "goals"),
        ("recipe", "recipes"),
        ("knowledge_rule", "knowledge_rules"),
        ("quest", "quests"),
        ("plot_beat", "plot_beats"),
        ("faction", "factions"),
    ):
        for index, definition in enumerate(getattr(pack, section)):
            add_identity(definition.id, kind, f"{section}.{index}.id")
    # Quest steps have stable IDs too, but are not top-level reference kinds.
    for quest_index, quest in enumerate(pack.quests):
        for step_index, step in enumerate(quest.steps):
            add_identity(step.id, "quest_step", f"quests.{quest_index}.steps.{step_index}.id")

    def reference(value: Any, expected_kind: str, path: str) -> None:
        if not isinstance(value, str):
            return
        if "/" in value or ":" in value:
            issues.append(ContentV2Error(
                "CONTENT_CROSS_PACK_REF",
                path,
                f"cross-pack reference {value!r} is not supported",
            ))
            return
        actual_kinds = kinds_by_id.get(value)
        if not actual_kinds:
            issues.append(ContentV2Error(
                "CONTENT_DANGLING_REF",
                path,
                f"{expected_kind} reference {value!r} does not exist",
            ))
        elif expected_kind not in actual_kinds:
            actual = ", ".join(sorted(actual_kinds))
            issues.append(ContentV2Error(
                "CONTENT_KIND_MISMATCH",
                path,
                f"expected {expected_kind}, found {actual} for {value!r}",
            ))

    def owner_reference(owner: Any, path: str) -> None:
        if not isinstance(owner, str):
            return
        if owner == "player":
            return
        if owner.startswith("location:"):
            reference(owner[len("location:"):], "location", path)
        elif owner.startswith("character:"):
            reference(owner[len("character:"):], "character", path)
        else:
            issues.append(ContentV2Error(
                "CONTENT_INVALID_OWNER",
                path,
                f"invalid owner {owner!r}; expected player, location:<id>, or character:<id>",
            ))

    def actor_reference(actor: Any, path: str) -> None:
        if actor != "player":
            reference(actor, "character", path)

    def validate_trigger(trigger: TriggerDef, path: str) -> None:
        trigger = _unwrap_root(trigger)
        if getattr(trigger, "type", None) == "on_action_completed":
            actor_reference(getattr(trigger, "actor", None), f"{path}.actor")
            location = getattr(trigger, "location", None)
            if location is not None:
                reference(location, "location", f"{path}.location")

    def validate_condition(condition: ConditionDef | None, path: str) -> None:
        if condition is None:
            return
        condition = _unwrap_root(condition)
        node_count = 0
        deepest = 0

        def walk(node: Any, node_path: str, depth: int) -> None:
            nonlocal node_count, deepest
            node = _unwrap_root(node)
            node_count += 1
            deepest = max(deepest, depth)
            if isinstance(node, (ConditionAllDef, ConditionAnyDef)):
                key = "all" if isinstance(node, ConditionAllDef) else "any"
                for index, child in enumerate(getattr(node, key)):
                    walk(child, f"{node_path}.{key}.{index}", depth + 1)
            elif isinstance(node, ConditionNotDef):
                walk(node.not_, f"{node_path}.not", depth + 1)
            elif isinstance(node, FlagEqualsConditionDef):
                if node.key not in pack.initial_state.flags:
                    issues.append(ContentV2Error(
                        "CONTENT_UNDECLARED_FLAG",
                        f"{node_path}.key",
                        f"flag {node.key!r} is not declared in initial_state.flags",
                    ))
            elif isinstance(node, ActorAliveConditionDef):
                actor_reference(node.actor, f"{node_path}.actor")
            elif isinstance(node, ActorAtLocationConditionDef):
                actor_reference(node.actor, f"{node_path}.actor")
                reference(node.location, "location", f"{node_path}.location")
            elif isinstance(node, RouteOpenConditionDef):
                reference(node.from_, "location", f"{node_path}.from")
                reference(node.to, "location", f"{node_path}.to")
            elif isinstance(node, ItemOwnerIsConditionDef):
                reference(node.item, "item", f"{node_path}.item")
                owner_reference(node.owner, f"{node_path}.owner")
            elif isinstance(node, ItemHasConditionDef):
                reference(node.item, "item", f"{node_path}.item")
                actor_reference(node.actor, f"{node_path}.actor")

        walk(condition, path, 1)
        if deepest > 8:
            issues.append(ContentV2Error(
                "CONTENT_CONDITION_TOO_DEEP",
                path,
                f"condition depth {deepest} exceeds maximum 8",
            ))
        if node_count > 128:
            issues.append(ContentV2Error(
                "CONTENT_CONDITION_TOO_LARGE",
                path,
                f"condition node count {node_count} exceeds maximum 128",
            ))

    def validate_effect(effect: Any, path: str) -> None:
        effect = _unwrap_root(effect)
        if isinstance(effect, FlagSetEffectDef):
            if effect.key not in pack.initial_state.flags:
                issues.append(ContentV2Error(
                    "CONTENT_UNDECLARED_FLAG",
                    f"{path}.key",
                    f"flag {effect.key!r} is not declared in initial_state.flags",
                ))
        elif isinstance(effect, RouteSetOpenEffectDef):
            reference(effect.from_, "location", f"{path}.from")
            reference(effect.to, "location", f"{path}.to")
        elif isinstance(effect, NpcActionStartEffectDef):
            reference(effect.actor, "character", f"{path}.actor")
            if effect.target is not None and effect.action == "move":
                reference(effect.target, "location", f"{path}.target")
        elif isinstance(effect, PlanStartEffectDef):
            reference(effect.actor, "character", f"{path}.actor")
            reference(effect.goal, "goal", f"{path}.goal")
        elif isinstance(effect, (ItemTransferEffectDef, ItemUseEffectDef)):
            reference(effect.item, "item", f"{path}.item")
            if isinstance(effect, ItemTransferEffectDef):
                owner_reference(effect.to, f"{path}.to")
            else:
                actor_reference(effect.actor, f"{path}.actor")
        elif isinstance(effect, EventScheduleEffectDef):
            reference(effect.rule, "rule", f"{path}.rule")

    # Shared authored-definition references.
    for index, location in enumerate(pack.locations):
        if location.parent_id is not None:
            reference(location.parent_id, "location", f"locations.{index}.parent_id")
    for index, route in enumerate(pack.routes):
        reference(route.from_, "location", f"routes.{index}.from")
        reference(route.to, "location", f"routes.{index}.to")
    for index, character in enumerate(pack.characters):
        reference(character.initial_location_id, "location", f"characters.{index}.initial_location_id")
    for index, item in enumerate(pack.items):
        if item.quantity != 1:
            issues.append(ContentV2Error(
                "CONTENT_UNSUPPORTED_FEATURE",
                f"items.{index}.quantity",
                "stacked items are not supported; quantity must be 1",
            ))

    # Initial state references and owner syntax.
    reference(pack.initial_state.player.location_id, "location", "initial_state.player.location_id")
    for index, character in enumerate(pack.initial_state.characters):
        reference(character.id, "character", f"initial_state.characters.{index}.id")
        reference(character.location_id, "location", f"initial_state.characters.{index}.location_id")
    for index, item in enumerate(pack.initial_state.items):
        reference(item.id, "item", f"initial_state.items.{index}.id")
        owner_reference(item.owner, f"initial_state.items.{index}.owner")
    for index, route in enumerate(pack.initial_state.routes):
        reference(route.from_, "location", f"initial_state.routes.{index}.from")
        reference(route.to, "location", f"initial_state.routes.{index}.to")
    for index, schedule in enumerate(pack.initial_state.schedules):
        reference(schedule.character_id, "character", f"initial_state.schedules.{index}.character_id")
        reference(schedule.location_id, "location", f"initial_state.schedules.{index}.location_id")

    # Expand bidirectional routes before duplicate-directed-edge detection.
    route_edges: dict[tuple[str, str], int] = {}
    for index, route in enumerate(pack.routes):
        directions = [(route.from_, route.to)]
        if route.bidirectional and route.from_ != route.to:
            directions.append((route.to, route.from_))
        for edge in directions:
            prior = route_edges.get(edge)
            if prior is not None:
                issues.append(ContentV2Error(
                    "CONTENT_DUPLICATE_ROUTE",
                    f"routes.{index}",
                    f"duplicate directed route {edge[0]!r} -> {edge[1]!r} (first declared at routes.{prior})",
                ))
            else:
                route_edges[edge] = index

    names: dict[str, int] = {}
    for index, location in enumerate(pack.locations):
        alias = location.name.strip().casefold()
        prior = names.get(alias)
        if alias and prior is not None:
            issues.append(ContentV2Error(
                "CONTENT_AMBIGUOUS_ALIAS",
                f"locations.{index}.name",
                f"location name {location.name!r} duplicates locations.{prior}.name",
            ))
        elif alias:
            names[alias] = index

    # Rule triggers, conditions, and effects.
    for index, rule in enumerate(pack.rules):
        path = f"rules.{index}"
        validate_trigger(rule.trigger, f"{path}.trigger")
        validate_condition(rule.condition, f"{path}.condition")
        for effect_index, effect in enumerate(rule.effects):
            validate_effect(effect, f"{path}.effects.{effect_index}")

    # Schedules reference both a character and a destination, and their
    # half-open time windows must not overlap for the same character.
    by_character: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for index, schedule in enumerate(pack.schedules):
        reference(schedule.character_id, "character", f"schedules.{index}.character_id")
        reference(schedule.location_id, "location", f"schedules.{index}.location_id")
        start = schedule.at_tick
        end = start + schedule.window_ticks
        by_character[schedule.character_id].append((start, end, index))
    for character_id, windows in by_character.items():
        windows.sort()
        for left_index, left in enumerate(windows):
            for right in windows[left_index + 1:]:
                if right[0] >= left[1]:
                    break
                issues.append(ContentV2Error(
                    "CONTENT_SCHEDULE_OVERLAP",
                    f"schedules.{right[2]}",
                    f"schedule window overlaps another window for character {character_id!r}",
                ))

    for index, goal in enumerate(pack.goals):
        if goal.character_id is not None:
            reference(goal.character_id, "character", f"goals.{index}.character_id")
        reference(goal.recipe, "recipe", f"goals.{index}.recipe")
        validate_condition(goal.preconditions, f"goals.{index}.preconditions")
        validate_condition(goal.completion, f"goals.{index}.completion")

    for index, recipe in enumerate(pack.recipes):
        if len(recipe.steps) > 16:
            issues.append(ContentV2Error(
                "CONTENT_RECIPE_TOO_LONG",
                f"recipes.{index}.steps",
                f"recipe contains {len(recipe.steps)} steps; maximum is 16",
            ))
        for step_index, step in enumerate(recipe.steps):
            if step.target is None:
                continue
            if step.action.value == "move":
                reference(step.target, "location", f"recipes.{index}.steps.{step_index}.target")
            elif step.action.value in {"take", "use", "transfer"}:
                reference(step.target, "item", f"recipes.{index}.steps.{step_index}.target")

    allowed_placeholders = _ALLOWED_PLACEHOLDERS
    for index, knowledge_rule in enumerate(pack.knowledge_rules):
        try:
            fields = [field_name for _literal, field_name, _spec, _conversion in Formatter().parse(knowledge_rule.template)]
        except ValueError as exc:
            issues.append(ContentV2Error(
                "CONTENT_UNKNOWN_PLACEHOLDER",
                f"knowledge_rules.{index}.template",
                f"malformed template placeholder: {exc}",
            ))
            continue
        for field_name in fields:
            if field_name is not None and field_name not in allowed_placeholders:
                issues.append(ContentV2Error(
                    "CONTENT_UNKNOWN_PLACEHOLDER",
                    f"knowledge_rules.{index}.template",
                    f"unknown template placeholder {{{field_name}}}",
                ))

    for index, quest in enumerate(pack.quests):
        for step_index, step in enumerate(quest.steps):
            reference(step.location_id, "location", f"quests.{index}.steps.{step_index}.location_id")

    for index, beat in enumerate(pack.plot_beats):
        path = f"plot_beats.{index}"
        validate_trigger(beat.trigger, f"{path}.trigger")
        for effect_index, effect in enumerate(beat.effects):
            if effect.key not in pack.initial_state.flags:
                issues.append(ContentV2Error(
                    "CONTENT_UNDECLARED_FLAG",
                    f"{path}.effects.{effect_index}.key",
                    f"flag {effect.key!r} is not declared in initial_state.flags",
                ))

    for faction_index, faction in enumerate(pack.factions):
        for relationship_index, relationship in enumerate(faction.relationships):
            reference(
                relationship.target_faction_id,
                "faction",
                f"factions.{faction_index}.relationships.{relationship_index}.target_faction_id",
            )

    return issues
