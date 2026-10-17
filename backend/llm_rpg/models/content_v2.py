"""Strict immutable contracts for content pack schema v2 (``content_v1``)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from enum import Enum
from typing import Annotated, Any, Generic, Literal, TypeVar, Union

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

PACK_SCHEMA_VERSION = 2
BUNDLE_SCHEMA_VERSION = 1
ENGINE_RULES_VERSION = 1
CONTENT_PROFILE_ID = "content_v1"
CONTENT_NAMESPACE = "__content_simulation"


class ContentV2Error(Exception):
    """Raised for a rejected content definition."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


def _validate_stable_id(value: str) -> str:
    if value in {"player", "world"}:
        raise PydanticCustomError("content_reserved_id", "reserved stable id: {value}", {"value": value})
    return value


_OWNER_PATTERN = r"^(player|location:[a-z][a-z0-9_]{0,63}|character:[a-z][a-z0-9_]{0,63})$"


def _validate_owner_ref(value: str) -> str:
    import re

    if not re.fullmatch(r"(?:player|location:[a-z][a-z0-9_]{0,63}|character:[a-z][a-z0-9_]{0,63})", value):
        raise PydanticCustomError("content_invalid_owner", "invalid item owner reference: {value}", {"value": value})
    return value


StableId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$"),
    AfterValidator(_validate_stable_id),
    Field(json_schema_extra={"not": {"enum": ["player", "world"]}}),
]
ActorRef = Annotated[str, StringConstraints(pattern=r"^(player|[a-z][a-z0-9_]{0,63})$")]
OwnerRef = Annotated[
    str,
    AfterValidator(_validate_owner_ref),
    Field(json_schema_extra={"pattern": _OWNER_PATTERN}),
]
NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
TagString = Annotated[str, StringConstraints(min_length=1)]
FlagValue = Union[bool, int, str]


class TriggerType(str, Enum):
    ON_TIME_CROSSED = "on_time_crossed"
    ON_ACTION_COMPLETED = "on_action_completed"


class TriggerPhase(str, Enum):
    ENVIRONMENT = "environment"
    NPC_MOVE = "npc_move"
    ITEM = "item"
    PLAYER_CONTINUOUS = "player_continuous"


class ConditionType(str, Enum):
    FLAG_EQUALS = "flag_equals"
    ACTOR_ALIVE = "actor_alive"
    ACTOR_AT_LOCATION = "actor_at_location"
    ROUTE_OPEN = "route_open"
    ITEM_OWNER_IS = "item_owner_is"
    ITEM_HAS = "item_has"


class EffectType(str, Enum):
    FLAG_SET = "flag_set"
    ROUTE_SET_OPEN = "route_set_open"
    NPC_ACTION_START = "npc_action_start"
    PLAN_START = "plan_start"
    ITEM_TRANSFER = "item_transfer"
    ITEM_USE = "item_use"
    INTERRUPT = "interrupt"
    EMIT_EVENT = "emit_event"
    EVENT_SCHEDULE = "event_schedule"


class FirePolicyMode(str, Enum):
    ONCE_PER_INSTANCE = "once_per_instance"
    ONCE_PER_SOURCE_EVENT = "once_per_source_event"


class ObserverScope(str, Enum):
    ACTOR = "actor"
    AT_LOCATION = "at_location"
    ALL_ALIVE = "all_alive"


class MemoryKind(str, Enum):
    ACTION = "action"
    OBSERVATION = "observation"


class MemoryVisibility(str, Enum):
    NPC_PRIVATE = "npc_private"
    NPC_SHARED = "npc_shared"


class PlanAction(str, Enum):
    MOVE = "move"
    WAIT = "wait"
    TAKE = "take"
    USE = "use"
    TRANSFER = "transfer"


class GoalInitialStatus(str, Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"


class PlotBeatVisibility(str, Enum):
    HIDDEN = "hidden"
    CONDITIONAL = "conditional"
    REVEALED = "revealed"


class StrictModel(BaseModel):
    """Base for frozen content models; all schema extras are forbidden."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ContentV2Error:
            raise
        except ValidationError as exc:
            raise _content_error_from_validation(exc) from exc

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> Any:
        try:
            return super().model_validate(obj, **kwargs)
        except ContentV2Error:
            raise
        except ValidationError as exc:
            raise _content_error_from_validation(exc) from exc

    @model_validator(mode="before")
    @classmethod
    def _reject_non_finite_numbers(cls, value: Any) -> Any:
        _check_finite(value)
        if isinstance(value, dict):
            normalized = dict(value)
            for field_name, field_info in cls.model_fields.items():
                enum_type = field_info.annotation
                if (
                    field_name in normalized
                    and isinstance(normalized[field_name], str)
                    and isinstance(enum_type, type)
                    and issubclass(enum_type, Enum)
                ):
                    try:
                        normalized[field_name] = enum_type(normalized[field_name])
                    except ValueError as exc:
                        raise PydanticCustomError("enum", f"unsupported enum value for {field_name}") from exc
            return normalized
        return value

    @field_validator("tags", mode="after", check_fields=False)
    @classmethod
    def _require_unique_tags(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise PydanticCustomError("content_value_range", "tags must be unique")
        return value


RootValue = TypeVar("RootValue")


class StrictRootModel(RootModel[RootValue], Generic[RootValue]):
    """Frozen root-union model used for schema oneOf definitions."""

    model_config = ConfigDict(frozen=True, strict=True)

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ContentV2Error:
            raise
        except ValidationError as exc:
            raise _content_error_from_validation(exc) from exc

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> Any:
        try:
            return super().model_validate(obj, **kwargs)
        except ContentV2Error:
            raise
        except ValidationError as exc:
            raise _content_error_from_validation(exc) from exc


def _check_finite(value: Any, active: set[int] | None = None) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise PydanticCustomError("content_non_finite_number", "numbers must be finite")
    if active is None:
        active = set()
    if isinstance(value, (Mapping, list, tuple)):
        identity = id(value)
        if identity in active:
            return
        active.add(identity)
        try:
            if isinstance(value, Mapping):
                for key, item in value.items():
                    _check_finite(key, active)
                    _check_finite(item, active)
            else:
                for item in value:
                    _check_finite(item, active)
        finally:
            active.remove(identity)


def _content_error_from_validation(exc: ValidationError) -> ContentV2Error:
    details = exc.errors(include_url=False)
    known_condition_types = {
        "flag_equals", "actor_alive", "actor_at_location", "route_open", "item_owner_is", "item_has"
    }
    unknown_condition_types = [
        item for item in details
        if item.get("type") == "literal_error"
        and item.get("loc")
        and str(item["loc"][-1]) == "type"
        and item.get("input") not in known_condition_types
    ]
    if unknown_condition_types:
        item = unknown_condition_types[0]
        path = ".".join(str(part) for part in item.get("loc", ())) or "$"
        return ContentV2Error("CONTENT_UNSUPPORTED_FEATURE", path, str(item.get("msg", "unknown condition type")))
    # Prefer the most actionable rejection if a union reports several branches.
    priority = {
        "extra_forbidden": 0,
        "content_reserved_id": 1,
        "content_invalid_owner": 1,
        "content_non_finite_number": 1,
        "content_recipe_too_long": 1,
        "literal_error": 2,
        "enum": 2,
    }
    detail = min(details, key=lambda item: priority.get(item.get("type", ""), 10)) if details else {}
    error_type = str(detail.get("type", ""))
    loc = tuple(detail.get("loc", ()))
    path = ".".join(str(part) for part in loc) or "$"
    message = str(detail.get("msg", "invalid content"))
    input_value = detail.get("input")
    last = str(loc[-1]) if loc else ""

    if error_type == "extra_forbidden":
        code = "CONTENT_UNKNOWN_FIELD"
    elif error_type == "content_reserved_id":
        code = "CONTENT_RESERVED_ID"
    elif error_type == "content_invalid_owner":
        code = "CONTENT_CROSS_PACK_REF" if "/" in str(input_value) else "CONTENT_INVALID_OWNER"
    elif error_type == "content_non_finite_number":
        code = "CONTENT_NON_FINITE_NUMBER"
    elif error_type == "content_unsupported_feature":
        code = "CONTENT_UNSUPPORTED_FEATURE"
    elif error_type == "content_recipe_too_long" or (last == "steps" and error_type in {"too_long", "list_too_long"}):
        code = "CONTENT_RECIPE_TOO_LONG"
    elif last == "schema_version":
        code = "CONTENT_PACK_SCHEMA_UNSUPPORTED"
    elif last == "quantity" or error_type in {"literal_error", "enum", "union_tag_invalid", "union_tag_not_found"}:
        code = "CONTENT_UNSUPPORTED_FEATURE"
    elif error_type in {
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "string_too_short",
        "string_too_long",
        "too_short",
        "too_long",
        "list_too_short",
        "list_too_long",
        "content_value_range",
    }:
        code = "CONTENT_VALUE_RANGE"
    elif error_type == "string_pattern_mismatch":
        if input_value in {"player", "world"}:
            code = "CONTENT_RESERVED_ID"
        elif "/" in str(input_value) or ":" in str(input_value):
            code = "CONTENT_CROSS_PACK_REF"
        else:
            code = "CONTENT_TYPE_ERROR"
    else:
        code = "CONTENT_TYPE_ERROR"
    return ContentV2Error(code, path, message)


class PackManifest(StrictModel):
    schema_version: Literal[2]
    id: StableId
    name: NonEmptyString
    version: NonEmptyString
    description: str = ""
    author: str = ""
    genre: str = ""
    theme: str = ""
    tags: list[TagString] = Field(default_factory=list, json_schema_extra={"uniqueItems": True})


class WorldDef(StrictModel):
    id: StableId
    name: NonEmptyString
    description: str = ""
    tags: list[TagString] = Field(default_factory=list, json_schema_extra={"uniqueItems": True})
    enabled: bool = True
    genre: str = ""
    theme: str = ""
    lore_summary: str = ""
    status: Literal["active", "draft", "archived"] = "active"
    start_hour: int = Field(default=8, ge=0, le=23)
    start_minute: int = Field(default=0, ge=0, le=59)
    start_tick: int = Field(default=0, ge=0)


class AccessRulesDef(StrictModel):
    always_accessible: bool = True


class LocationDef(StrictModel):
    id: StableId
    name: NonEmptyString
    description: str = ""
    tags: list[TagString] = Field(default_factory=list, json_schema_extra={"uniqueItems": True})
    enabled: bool = True
    parent_id: StableId | None = None
    access_rules: AccessRulesDef = Field(default_factory=AccessRulesDef)


class RouteDef(StrictModel):
    from_: StableId = Field(alias="from")
    to: StableId
    open: bool = True
    travel_ticks: int = Field(default=1, ge=1)
    bidirectional: bool = False


class CharacterDef(StrictModel):
    id: StableId
    name: NonEmptyString
    description: str = ""
    tags: list[TagString] = Field(default_factory=list, json_schema_extra={"uniqueItems": True})
    enabled: bool = True
    public_identity: str = ""
    personality: str = ""
    initial_location_id: StableId
    alive: bool = True


class ItemDef(StrictModel):
    id: StableId
    name: NonEmptyString
    description: str = ""
    tags: list[TagString] = Field(default_factory=list, json_schema_extra={"uniqueItems": True})
    enabled: bool = True
    item_type: NonEmptyString
    quantity: Literal[1] = 1


class InitialPlayerDef(StrictModel):
    location_id: StableId
    alive: bool = True


class InitialCharacterDef(StrictModel):
    id: StableId
    location_id: StableId
    alive: bool = True


class InitialItemDef(StrictModel):
    id: StableId
    owner: OwnerRef


class InitialRouteDef(StrictModel):
    from_: StableId = Field(alias="from")
    to: StableId
    open: bool


class InitialScheduleDef(StrictModel):
    character_id: StableId
    activity: NonEmptyString
    location_id: StableId
    start_tick: int = Field(default=0, ge=0)


class InitialStateDef(StrictModel):
    player: InitialPlayerDef
    characters: list[InitialCharacterDef] = Field(default_factory=list)
    items: list[InitialItemDef] = Field(default_factory=list)
    routes: list[InitialRouteDef] = Field(default_factory=list)
    flags: dict[str, FlagValue] = Field(default_factory=dict)
    schedules: list[InitialScheduleDef] = Field(default_factory=list)


class _OnTimeCrossedTriggerDef(StrictModel):
    type: Literal["on_time_crossed"]
    due_tick: int = Field(ge=1)
    phase: TriggerPhase = TriggerPhase.ENVIRONMENT

    @field_validator("phase", mode="before")
    @classmethod
    def _parse_phase(cls, value: Any) -> TriggerPhase:
        if isinstance(value, TriggerPhase):
            return value
        try:
            return TriggerPhase(value)
        except (TypeError, ValueError) as exc:
            raise PydanticCustomError("enum", "unsupported trigger phase") from exc


class _OnActionCompletedTriggerDef(StrictModel):
    type: Literal["on_action_completed"]
    action: Literal["move", "idle"]
    actor: ActorRef
    location: StableId | None = None


_TriggerVariant = Annotated[Union[_OnTimeCrossedTriggerDef, _OnActionCompletedTriggerDef], Field(discriminator="type")]


class TriggerDef(StrictRootModel[_TriggerVariant]):
    pass


class ConditionAllDef(StrictModel):
    all: list["ConditionDef"] = Field(min_length=1)


class ConditionAnyDef(StrictModel):
    any: list["ConditionDef"] = Field(min_length=1)


class ConditionNotDef(StrictModel):
    not_: "ConditionDef" = Field(alias="not")


class FlagEqualsConditionDef(StrictModel):
    type: Literal["flag_equals"]
    key: StableId
    value: FlagValue


class ActorAliveConditionDef(StrictModel):
    type: Literal["actor_alive"]
    actor: ActorRef


class ActorAtLocationConditionDef(StrictModel):
    type: Literal["actor_at_location"]
    actor: ActorRef
    location: StableId


class RouteOpenConditionDef(StrictModel):
    type: Literal["route_open"]
    from_: StableId = Field(alias="from")
    to: StableId


class ItemOwnerIsConditionDef(StrictModel):
    type: Literal["item_owner_is"]
    item: StableId
    owner: OwnerRef


class ItemHasConditionDef(StrictModel):
    type: Literal["item_has"]
    item: StableId
    actor: ActorRef


_ConditionVariant = Union[
    ConditionAllDef,
    ConditionAnyDef,
    ConditionNotDef,
    FlagEqualsConditionDef,
    ActorAliveConditionDef,
    ActorAtLocationConditionDef,
    RouteOpenConditionDef,
    ItemOwnerIsConditionDef,
    ItemHasConditionDef,
]


class ConditionDef(StrictRootModel[_ConditionVariant]):
    @model_validator(mode="before")
    @classmethod
    def _dispatch_variant(cls, value: Any) -> Any:
        if isinstance(value, ConditionDef):
            return value.root
        condition_models = (
            ConditionAllDef,
            ConditionAnyDef,
            ConditionNotDef,
            FlagEqualsConditionDef,
            ActorAliveConditionDef,
            ActorAtLocationConditionDef,
            RouteOpenConditionDef,
            ItemOwnerIsConditionDef,
            ItemHasConditionDef,
        )
        if isinstance(value, condition_models):
            return value
        if isinstance(value, dict):
            if "all" in value:
                model = ConditionAllDef
            elif "any" in value:
                model = ConditionAnyDef
            elif "not" in value:
                model = ConditionNotDef
            else:
                model_by_type = {
                    "flag_equals": FlagEqualsConditionDef,
                    "actor_alive": ActorAliveConditionDef,
                    "actor_at_location": ActorAtLocationConditionDef,
                    "route_open": RouteOpenConditionDef,
                    "item_owner_is": ItemOwnerIsConditionDef,
                    "item_has": ItemHasConditionDef,
                }
                model = model_by_type.get(value.get("type"))
                if model is None and "type" in value:
                    raise PydanticCustomError("content_unsupported_feature", "unsupported condition type")
            if model is not None:
                return model.model_validate(value)
        return value


for _condition_model in (ConditionAllDef, ConditionAnyDef, ConditionNotDef):
    _condition_model.model_rebuild(_types_namespace={"ConditionDef": ConditionDef})


class FlagSetEffectDef(StrictModel):
    type: Literal["flag_set"]
    key: StableId
    value: FlagValue


class RouteSetOpenEffectDef(StrictModel):
    type: Literal["route_set_open"]
    from_: StableId = Field(alias="from")
    to: StableId
    open: bool


class NpcActionStartEffectDef(StrictModel):
    type: Literal["npc_action_start"]
    actor: StableId
    action: Literal["move", "wait"]
    target: StableId | None = None
    ticks: int | None = Field(default=None, ge=1)


class PlanStartEffectDef(StrictModel):
    type: Literal["plan_start"]
    actor: StableId
    goal: StableId


class ItemTransferEffectDef(StrictModel):
    type: Literal["item_transfer"]
    item: StableId
    to: OwnerRef


class ItemUseEffectDef(StrictModel):
    type: Literal["item_use"]
    item: StableId
    actor: ActorRef


class InterruptEffectDef(StrictModel):
    type: Literal["interrupt"]
    kind: NonEmptyString
    message: NonEmptyString


class EmitEventEffectDef(StrictModel):
    type: Literal["emit_event"]
    event_type: NonEmptyString
    payload: dict[str, Any] = Field(default_factory=dict)


class EventScheduleEffectDef(StrictModel):
    type: Literal["event_schedule"]
    rule: StableId
    tick: int = Field(ge=0)


_EffectVariant = Annotated[
    Union[
        FlagSetEffectDef,
        RouteSetOpenEffectDef,
        NpcActionStartEffectDef,
        PlanStartEffectDef,
        ItemTransferEffectDef,
        ItemUseEffectDef,
        InterruptEffectDef,
        EmitEventEffectDef,
        EventScheduleEffectDef,
    ],
    Field(discriminator="type"),
]


class EffectDef(StrictRootModel[_EffectVariant]):
    pass


class FirePolicyDef(StrictModel):
    mode: FirePolicyMode


class RuleDef(StrictModel):
    id: StableId
    name: str = ""
    description: str = ""
    tags: list[TagString] = Field(default_factory=list, json_schema_extra={"uniqueItems": True})
    enabled: bool = True
    trigger: TriggerDef
    condition: ConditionDef | None = None
    effects: list[EffectDef] = Field(min_length=1)
    fire_policy: FirePolicyDef
    priority: int = Field(default=0, ge=0, le=100)


class ScheduleDef(StrictModel):
    id: StableId
    character_id: StableId
    activity: NonEmptyString
    location_id: StableId
    at_tick: int = Field(ge=0)
    window_ticks: int = Field(default=1, ge=1)
    default_activity: bool = False


class PlanStepDef(StrictModel):
    action: PlanAction
    target: StableId | None = None
    ticks: int | None = Field(default=None, ge=1)


class PlanRecipeDef(StrictModel):
    id: StableId
    steps: list[PlanStepDef] = Field(min_length=1, max_length=16)


class GoalDef(StrictModel):
    id: StableId
    character_id: StableId | None = None
    priority: int = Field(ge=0, le=100)
    description: str = ""
    preconditions: ConditionDef | None = None
    completion: ConditionDef | None = None
    recipe: StableId
    initial_status: GoalInitialStatus = GoalInitialStatus.INACTIVE


class KnowledgeRuleDef(StrictModel):
    id: StableId
    source_event_types: list[NonEmptyString] = Field(min_length=1)
    observers: ObserverScope
    memory_kind: MemoryKind
    visibility: MemoryVisibility
    template: NonEmptyString


class QuestStepDef(StrictModel):
    id: StableId
    location_id: StableId


class QuestDef(StrictModel):
    id: StableId
    name: NonEmptyString
    description: str = ""
    steps: list[QuestStepDef] = Field(min_length=1)


class _PlotBeatFlagSetEffectDef(StrictModel):
    type: Literal["flag_set"]
    key: StableId
    value: FlagValue


class PlotBeatDef(StrictModel):
    id: StableId
    name: NonEmptyString
    description: str = ""
    trigger: TriggerDef
    effects: list[_PlotBeatFlagSetEffectDef] = Field(min_length=1)
    visibility: PlotBeatVisibility = PlotBeatVisibility.CONDITIONAL


class FactionGoalDef(StrictModel):
    goal_id: NonEmptyString
    description: NonEmptyString
    priority: int = Field(default=0, ge=0, le=100)
    status: str = "active"


class FactionRelationshipDef(StrictModel):
    target_faction_id: StableId
    relationship_type: str = "neutral"
    score: int = Field(default=0, ge=-100, le=100)


class FactionDef(StrictModel):
    id: StableId
    name: NonEmptyString
    description: str = ""
    tags: list[TagString] = Field(default_factory=list, json_schema_extra={"uniqueItems": True})
    enabled: bool = True
    ideology: str = ""
    visibility: Literal["public", "hidden", "secret"] = "public"
    goals: list[FactionGoalDef] = Field(default_factory=list)
    relationships: list[FactionRelationshipDef] = Field(default_factory=list)


class LocationsFile(StrictModel):
    locations: list[LocationDef]
    routes: list[RouteDef] = Field(default_factory=list)


class ContentPackV2(StrictModel):
    """Assembled in-memory content pack; section files are not retained."""

    manifest: PackManifest
    world: WorldDef
    locations: list[LocationDef]
    routes: list[RouteDef] = Field(default_factory=list)
    characters: list[CharacterDef] = Field(default_factory=list)
    items: list[ItemDef] = Field(default_factory=list)
    initial_state: InitialStateDef
    rules: list[RuleDef] = Field(default_factory=list)
    schedules: list[ScheduleDef] = Field(default_factory=list)
    goals: list[GoalDef] = Field(default_factory=list)
    recipes: list[PlanRecipeDef] = Field(default_factory=list)
    knowledge_rules: list[KnowledgeRuleDef] = Field(default_factory=list)
    quests: list[QuestDef] = Field(default_factory=list)
    plot_beats: list[PlotBeatDef] = Field(default_factory=list)
    factions: list[FactionDef] = Field(default_factory=list)
