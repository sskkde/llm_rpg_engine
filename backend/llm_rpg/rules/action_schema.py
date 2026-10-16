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


# =============================================================================
# Phase 2: production authorization profile
# =============================================================================
#
# ``ACTION_SCHEMAS`` above only *declares* that an action type exists. Declaring
# an action is not a production grant: this phase authorizes a small, explicit
# set of (role, action_type) pairs that have a domain handler, and everything
# else declared-but-unauthorized must answer "unsupported / no effect" instead of
# pretending to succeed.
#
# The profile is the single registry both the prompt layer and the runtime check
# read, so the model is told exactly what it may propose and the runtime enforces
# exactly the same table.


class ActorRole(str, Enum):
    """Who is acting. The role decides the authorized action surface."""

    player = "player"
    npc = "npc"
    world = "world"
    scene = "scene"


class TimePolicy(str, Enum):
    """Who owns the elapsed world time of an action."""

    #: The engine computes the cost from the action class (existing time rules).
    ENGINE_ADJUDICATED = "engine_adjudicated"
    #: The action never advances world time by itself.
    NONE = "none"


class ProductionTargetKind(str, Enum):
    """Target kinds a production proposal may reference."""

    location = "location"
    npc = "npc"
    player = "player"
    scene = "scene"
    none = "none"


@dataclass(frozen=True)
class ActionPermission:
    """A production grant: role + action type + handler + cost policy.

    Attributes:
        action_type: Canonical action type (after wire-alias normalization).
        role: The acting role this grant belongs to.
        params_model: Name of the strict contract params DTO for this action.
        target_kinds: Target kinds the proposal may reference.
        handler: Domain resolution handler key (see ``core.action_resolution``).
        time_policy: Who owns elapsed world time for this action.
        note: Short human-readable boundary of what the grant does *not* allow.
    """

    action_type: str
    role: ActorRole
    params_model: str
    target_kinds: tuple[ProductionTargetKind, ...]
    handler: str
    time_policy: TimePolicy
    note: str = ""


def _permission(
    action_type: str,
    role: ActorRole,
    params_model: str,
    target_kinds: tuple[ProductionTargetKind, ...],
    handler: str,
    time_policy: TimePolicy = TimePolicy.ENGINE_ADJUDICATED,
    note: str = "",
) -> ActionPermission:
    return ActionPermission(
        action_type=action_type,
        role=role,
        params_model=params_model,
        target_kinds=target_kinds,
        handler=handler,
        time_policy=time_policy,
        note=note,
    )


#: The complete production grant table for this phase. See the implementation
#: plan section 3.1; the table is intentionally small.
PRODUCTION_ACTION_PERMISSIONS: dict[tuple[ActorRole, str], ActionPermission] = {
    (ActorRole.player, "move"): _permission(
        "move",
        ActorRole.player,
        "MoveIntentParams",
        (ProductionTargetKind.location,),
        "player_move",
        note="one currently selectable location; no other effect parameter",
    ),
    (ActorRole.player, "talk"): _permission(
        "talk",
        ActorRole.player,
        "TalkIntentParams",
        (ProductionTargetKind.npc, ProductionTargetKind.scene),
        "player_talk",
        note="speech only; no reply, relationship or quest reward is promised",
    ),
    (ActorRole.player, "inspect"): _permission(
        "inspect",
        ActorRole.player,
        "InspectIntentParams",
        (ProductionTargetKind.scene, ProductionTargetKind.npc),
        "player_inspect",
        note="existing visible information only; no discovery or reward",
    ),
    (ActorRole.player, "idle"): _permission(
        "idle",
        ActorRole.player,
        "IdleIntentParams",
        (ProductionTargetKind.none,),
        "player_idle",
        note="engine-owned duration; the wire carries no duration",
    ),
    (ActorRole.npc, "observe"): _permission(
        "observe",
        ActorRole.npc,
        "NPCObserveParams",
        (ProductionTargetKind.scene,),
        "npc_observe",
        note="controlled observation result only; no physical effect",
    ),
    (ActorRole.npc, "idle"): _permission(
        "idle",
        ActorRole.npc,
        "NPCIdleParams",
        (ProductionTargetKind.none,),
        "npc_idle",
        note="controlled wait result only; no physical effect",
    ),
    (ActorRole.npc, "talk"): _permission(
        "talk",
        ActorRole.npc,
        "NPCTalkParams",
        (ProductionTargetKind.npc, ProductionTargetKind.player),
        "npc_talk",
        note="the sentence proves it was said, not that its proposition is true",
    ),
    (ActorRole.npc, "refuse"): _permission(
        "refuse",
        ActorRole.npc,
        "NPCRefuseParams",
        (ProductionTargetKind.npc, ProductionTargetKind.player),
        "npc_refuse",
        note="the sentence proves it was said, not that its proposition is true",
    ),
}


#: Wire action-type aliases normalized to a canonical authorized action type.
PRODUCTION_ACTION_ALIASES: dict[str, str] = {
    "dialogue": "talk",
}


def normalize_production_action_type(action_type: str) -> str:
    """Normalize a wire action type to its canonical production action type."""
    if not action_type:
        return action_type
    return PRODUCTION_ACTION_ALIASES.get(action_type, action_type)


def resolve_production_permission(
    role: ActorRole | str,
    action_type: str,
) -> ActionPermission | None:
    """Return the production grant for a role/action pair, or ``None``.

    ``None`` means the action is not authorized for that role: the caller must
    treat it as unsupported/no-effect rather than executing anything.
    """
    try:
        role_value = role if isinstance(role, ActorRole) else ActorRole(role)
    except ValueError:
        return None
    return PRODUCTION_ACTION_PERMISSIONS.get(
        (role_value, normalize_production_action_type(action_type))
    )


def is_action_authorized(role: ActorRole | str, action_type: str) -> bool:
    """Whether this phase has a domain handler for the role/action pair."""
    return resolve_production_permission(role, action_type) is not None


def production_authorized_action_types(role: ActorRole | str) -> frozenset[str]:
    """All canonical action types authorized for a role."""
    try:
        role_value = role if isinstance(role, ActorRole) else ActorRole(role)
    except ValueError:
        return frozenset()
    return frozenset(
        action_type
        for (grant_role, action_type) in PRODUCTION_ACTION_PERMISSIONS
        if grant_role is role_value
    )


def declared_action_types() -> frozenset[str]:
    """The general action types declared by ``ACTION_SCHEMAS``."""
    return frozenset(action_type.value for action_type in ACTION_SCHEMAS)


def is_declared_but_unauthorized(role: ActorRole | str, action_type: str) -> bool:
    """True when the action is a known general type with no production grant.

    This is the ``unsupported`` case: the action keeps its input classification
    and its existing time cost, but produces no effect.
    """
    if action_type not in declared_action_types():
        return False
    return not is_action_authorized(role, action_type)
