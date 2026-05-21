"""
Action Schema Module

Defines formal schemas for all action types in the game system.
Provides validation functions for action structure and fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..core.validation.result import passed_result, failed_result, ValidationResult


class ActionType(str, Enum):
    """All possible action types in the game system."""
    move = "move"
    inspect = "inspect"
    talk = "talk"
    ask = "ask"
    use_item = "use_item"
    take_item = "take_item"
    give_item = "give_item"
    attack = "attack"
    defend = "defend"
    cast_skill = "cast_skill"
    persuade = "persuade"
    hide = "hide"
    follow = "follow"
    wait = "wait"
    trigger_object = "trigger_object"
    quest_progress = "quest_progress"


class TargetType(str, Enum):
    """Types of targets for actions."""
    location = "location"
    npc = "npc"
    item = "item"
    self_type = "self"  # "self" is a reserved keyword, use self_type
    none = "none"


@dataclass
class ActionSchema:
    """Schema definition for an action type."""
    action_type: ActionType
    required_fields: list[str] = field(default_factory=list)
    optional_fields: list[str] = field(default_factory=list)
    valid_targets: list[TargetType] = field(default_factory=list)
    description: str = ""


# Registry of all action schemas
ACTION_SCHEMAS: dict[ActionType, ActionSchema] = {
    ActionType.move: ActionSchema(
        action_type=ActionType.move,
        required_fields=["target_ids"],
        optional_fields=[],
        valid_targets=[TargetType.location],
        description="Move to a location",
    ),
    ActionType.inspect: ActionSchema(
        action_type=ActionType.inspect,
        required_fields=["target_ids"],
        optional_fields=[],
        valid_targets=[TargetType.location, TargetType.npc, TargetType.item],
        description="Inspect a location, NPC, or item",
    ),
    ActionType.talk: ActionSchema(
        action_type=ActionType.talk,
        required_fields=["target_ids"],
        optional_fields=["dialogue_topic"],
        valid_targets=[TargetType.npc],
        description="Talk to an NPC",
    ),
    ActionType.ask: ActionSchema(
        action_type=ActionType.ask,
        required_fields=["target_ids"],
        optional_fields=["question"],
        valid_targets=[TargetType.npc],
        description="Ask an NPC a question",
    ),
    ActionType.use_item: ActionSchema(
        action_type=ActionType.use_item,
        required_fields=["item_id"],
        optional_fields=["target_ids", "quantity"],
        valid_targets=[TargetType.self_type, TargetType.npc],
        description="Use an item on self or an NPC",
    ),
    ActionType.take_item: ActionSchema(
        action_type=ActionType.take_item,
        required_fields=["item_id"],
        optional_fields=["quantity"],
        valid_targets=[TargetType.item],
        description="Take an item from a location",
    ),
    ActionType.give_item: ActionSchema(
        action_type=ActionType.give_item,
        required_fields=["item_id", "target_ids"],
        optional_fields=["quantity"],
        valid_targets=[TargetType.npc, TargetType.item],
        description="Give an item to an NPC",
    ),
    ActionType.attack: ActionSchema(
        action_type=ActionType.attack,
        required_fields=["target_ids"],
        optional_fields=["attack_type", "weapon_id"],
        valid_targets=[TargetType.npc],
        description="Attack an NPC",
    ),
    ActionType.defend: ActionSchema(
        action_type=ActionType.defend,
        required_fields=[],
        optional_fields=["defend_type"],
        valid_targets=[TargetType.none],
        description="Defend against attacks",
    ),
    ActionType.cast_skill: ActionSchema(
        action_type=ActionType.cast_skill,
        required_fields=["skill_name"],
        optional_fields=["target_ids"],
        valid_targets=[TargetType.npc, TargetType.self_type],
        description="Cast a skill on self or an NPC",
    ),
    ActionType.persuade: ActionSchema(
        action_type=ActionType.persuade,
        required_fields=["target_ids"],
        optional_fields=["approach"],
        valid_targets=[TargetType.npc],
        description="Persuade an NPC",
    ),
    ActionType.hide: ActionSchema(
        action_type=ActionType.hide,
        required_fields=[],
        optional_fields=["location_id"],
        valid_targets=[TargetType.none],
        description="Hide from enemies",
    ),
    ActionType.follow: ActionSchema(
        action_type=ActionType.follow,
        required_fields=["target_ids"],
        optional_fields=[],
        valid_targets=[TargetType.npc],
        description="Follow an NPC",
    ),
    ActionType.wait: ActionSchema(
        action_type=ActionType.wait,
        required_fields=[],
        optional_fields=["duration"],
        valid_targets=[TargetType.none],
        description="Wait for some time",
    ),
    ActionType.trigger_object: ActionSchema(
        action_type=ActionType.trigger_object,
        required_fields=["item_id"],
        optional_fields=[],
        valid_targets=[TargetType.item],
        description="Trigger or interact with an object",
    ),
    ActionType.quest_progress: ActionSchema(
        action_type=ActionType.quest_progress,
        required_fields=["quest_id"],
        optional_fields=["step_id"],
        valid_targets=[TargetType.none],
        description="Progress a quest",
    ),
}


def validate_action_schema(action: dict[str, Any]) -> ValidationResult:
    """
    Validate an action against its schema definition.
    
    Args:
        action: Dict with at least 'action_type' key and other fields
        
    Returns:
        ValidationResult with is_valid and detailed checks
    """
    # Check action_type exists
    action_type_str = action.get("action_type")
    if not action_type_str:
        return failed_result(
            "action_type_present",
            "Action must have an 'action_type' field",
        )
    
    # Check action_type is valid
    try:
        action_type = ActionType(action_type_str)
    except ValueError:
        return failed_result(
            "action_type_valid",
            f"Unknown action_type: '{action_type_str}'",
        )
    
    # Get schema
    schema = ACTION_SCHEMAS.get(action_type)
    if schema is None:
        return failed_result(
            "schema_exists",
            f"No schema defined for action_type: '{action_type_str}'",
        )
    
    # Check required fields
    missing_fields = []
    for req_field in schema.required_fields:
        if req_field not in action or action[req_field] is None:
            missing_fields.append(req_field)
    
    if missing_fields:
        return failed_result(
            "required_fields",
            f"Missing required fields: {missing_fields}",
        )
    
    # All checks passed
    return passed_result(
        "action_schema_valid",
        f"Action '{action_type_str}' passes schema validation",
    )
