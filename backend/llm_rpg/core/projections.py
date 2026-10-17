"""
Projection Builders - Filter events based on perspective.

This module provides projection builders that filter game events
based on different perspectives:
- PlayerVisibleProjectionBuilder: Only player-visible events
- NPCVisibleProjectionBuilder: Only events the NPC can perceive
- NarratorProjectionBuilder: Excludes private_payload from narration

The projection builders work with PerceptionResolver to determine
what information is visible to each perspective type.
"""

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from .content_runtime import CONTENT_NAMESPACE
from ..models.events import GameEvent
from ..models.perspectives import (
    Perspective,
    PlayerPerspective,
    NPCPerspective,
    NarratorPerspective,
)
from .perception import PerceptionResolver, PerceptionResult

P = TypeVar("P", bound=Perspective)

_CONTENT_PRIVATE_FIELDS = frozenset({
    CONTENT_NAMESPACE,
    "route_overrides",
    "pending_steps",
    "future_steps",
    "scheduled_steps",
    "pending_events",
    "future_events",
    "hidden_plan_state",
    "current_plan",
    "npc_current_plans",
    "npc_goals",
    "private_payload",
    "npc_private_memories",
    "owner_ref_id",
    "owner_ref",
    "owner_id",
    "owner_type",
    "owner",
    "item_owner",
    "owners",
    "hidden_identity",
    "short_memory_summary",
    "secret_plan",
    "private_payload_json",
})
_CONTENT_PUBLIC_STATUS_FIELDS = frozenset({
    "status",
    "mood",
    "alive",
    "is_alive",
    "activity",
    "visible_to_player",
})
_CONTENT_PUBLIC_NPC_FIELDS = frozenset({
    "name",
    "code",
    "role_type",
    "public_identity",
    "appearance",
    "mood",
    "status",
    "alive",
    "is_alive",
    "activity",
    "current_location_name",
    "current_location_code",
    "visible_to_player",
})


def _sanitize_content_value(value: Any) -> Any:
    if isinstance(value, dict):
        safe = {}
        for key, child in value.items():
            key_text = str(key)
            normalized = key_text.lower()
            if (
                key_text.startswith("__")
                or key_text in _CONTENT_PRIVATE_FIELDS
                or normalized.startswith("owner_")
                or normalized.startswith("hidden_")
                or normalized.startswith("private_")
            ):
                continue
            if normalized in {"public_status", "npc_status", "status_flags"}:
                safe[key] = project_content_public_status(child)
            else:
                safe[key] = _sanitize_content_value(child)
        return safe
    if isinstance(value, list):
        return [_sanitize_content_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_content_value(item) for item in value]
    return value


def project_content_public_status(status: Any) -> dict[str, Any]:
    """Whitelist the small status vocabulary safe for a player-facing view."""
    if not isinstance(status, dict):
        return {}
    return {
        key: _sanitize_content_value(value)
        for key, value in status.items()
        if key in _CONTENT_PUBLIC_STATUS_FIELDS
    }


def project_content_public_context(
    context: Any,
    *,
    visible_npc_ids: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Project content_v1 model/projection data without engine-private state.

    ``visible_npc_ids`` is an optional engine-computed allowlist; when supplied,
    NPC rows outside it are removed before projecting their public fields.
    """
    if not isinstance(context, dict):
        return {}
    projected = _sanitize_content_value(context)
    if "visible_npcs" in projected:
        rows = projected.get("visible_npcs")
        if not isinstance(rows, list):
            projected["visible_npcs"] = []
        else:
            projected["visible_npcs"] = [
                {
                    key: value
                    for key, value in row.items()
                    if key in _CONTENT_PUBLIC_NPC_FIELDS
                }
                for row in rows
                if isinstance(row, dict)
                and (visible_npc_ids is None or row.get("npc_id") in visible_npc_ids)
            ]
    return projected


@dataclass(frozen=True)
class ContentPublicVisibility:
    """One session-scoped allowlist for content_v1 player-facing projections."""

    current_location_id: str
    location_is_perceivable: bool
    perceivable_npc_codes: frozenset[str]
    perceivable_npc_template_ids: frozenset[str]
    perceivable_item_instance_keys: frozenset[str]
    known_npc_codes: frozenset[str]
    known_npc_template_ids: frozenset[str]


def resolve_content_public_visibility(
    db: Any,
    session: Any,
    *,
    location_id: str | None = None,
) -> ContentPublicVisibility | None:
    """Resolve content_v1 NPC/item visibility from committed, session-bound state.

    Per-event NPC knowledge is admitted only from ``player_visible`` event rows,
    whose scope was frozen by the engine when that event occurred (§9.1). Current
    scene contents are directly perceivable only at the player's current location;
    an open route (or ``always_accessible`` location metadata) permits travel but
    does not grant sight into another scene. No in-advance final-state overlay is
    consulted here.

    Return ``None`` for legacy/phase-3 sessions so their callers can preserve the
    existing response behavior exactly. A content marker/profile invokes the
    strict runtime loader and fails closed if its binding is damaged.
    """
    from ..storage.models import (
        GameEventModel,
        ItemTemplateModel,
        LocationModel,
        NPCTemplateModel,
        SessionStateModel,
        WorldModel,
    )

    world = db.get(WorldModel, session.world_id) if session.world_id else None
    ruleset = getattr(world, "ruleset_json", None)
    ruleset = ruleset if isinstance(ruleset, dict) else {}
    profile_present = "content_profile" in ruleset
    session_state = db.query(SessionStateModel).filter_by(session_id=session.id).one_or_none()
    flags = getattr(session_state, "global_flags_json", None)
    marker_present = isinstance(flags, dict) and CONTENT_NAMESPACE in flags
    if not profile_present and not marker_present:
        return None

    from .content_runtime import load_content_runtime_context

    runtime = load_content_runtime_context(db, session_id=session.id)
    location_rows = db.query(LocationModel).filter_by(world_id=runtime.binding.world_id).all()
    locations_by_code = {row.code: row for row in location_rows}
    location_codes_by_id = {row.id: row.code for row in location_rows}
    npc_rows = db.query(NPCTemplateModel).filter_by(world_id=runtime.binding.world_id).all()
    npcs_by_code = {row.code: row for row in npc_rows}
    item_rows = db.query(ItemTemplateModel).filter_by(world_id=runtime.binding.world_id).all()
    items_by_code = {row.code: row for row in item_rows}

    player_location_code = runtime.state.player_location_code
    current_location = locations_by_code.get(player_location_code)
    if current_location is None:
        return ContentPublicVisibility(
            current_location_id="",
            location_is_perceivable=False,
            perceivable_npc_codes=frozenset(),
            perceivable_npc_template_ids=frozenset(),
            perceivable_item_instance_keys=frozenset(),
            known_npc_codes=frozenset(),
            known_npc_template_ids=frozenset(),
        )

    requested_location_id = location_id or current_location.id
    requested_location_code = location_codes_by_id.get(requested_location_id)
    has_open_route = (
        requested_location_code == player_location_code
        or (
            requested_location_code is not None
            and runtime.state.route_is_open(player_location_code, requested_location_code)
        )
    )
    # An open edge is the session's route view, not a line-of-sight rule. Both
    # current-place identity and an open session route are required below, so a
    # remote always-accessible location never exposes its residents or items.
    location_is_perceivable = (
        requested_location_code == player_location_code and has_open_route
    )

    initial_state = runtime.rules.initial_state()
    event_rows = db.query(GameEventModel).filter_by(session_id=session.id).all()

    def _event_order(event: Any) -> tuple[Any, ...]:
        result = getattr(event, "result_json", None)
        engine_meta = result.get("engine_meta") if isinstance(result, dict) else None
        sequence = engine_meta.get("sequence") if isinstance(engine_meta, dict) else None
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            sequence = -1
        return (
            getattr(event, "turn_no", 0) or 0,
            sequence,
            getattr(event, "occurred_at", None),
        )

    event_rows.sort(key=_event_order)
    known_npc_codes = {
        code
        for code, npc_location in initial_state.npc_positions.items()
        if npc_location == initial_state.player_location_code
    }
    # Location knowledge follows the event-time visibility decision: a hidden NPC
    # move invalidates its previously known position; a later public movement can
    # establish a new one. Current row positions are only checked against that
    # public/baseline fact, never used to infer that a hidden move was perceived.
    npc_observed_locations: dict[str, str | None] = {}
    item_observed_owners = {
        code: f"{item.owner_type}:{item.owner_ref}"
        for code, item in initial_state.item_instances.items()
    }
    for event in event_rows:
        visible = getattr(event, "visibility_scope", None) == "player_visible"
        payload = getattr(event, "public_payload_json", None) if visible else None
        payload = payload if isinstance(payload, dict) else {}
        actor_code = getattr(event, "actor_id", None)
        if visible:
            if isinstance(actor_code, str) and actor_code in npcs_by_code:
                known_npc_codes.add(actor_code)
            for key in ("npc_id", "character_id", "actor", "target", "target_id"):
                npc_code = payload.get(key)
                if isinstance(npc_code, str) and npc_code in npcs_by_code:
                    known_npc_codes.add(npc_code)
        event_type = getattr(event, "event_type", None)
        npc_code = (
            actor_code
            if isinstance(actor_code, str) and actor_code in npcs_by_code
            else payload.get("npc_id")
        )
        if isinstance(npc_code, str) and npc_code in npcs_by_code and event_type in {
            "npc_travel_started", "npc_arrived", "npc_travel_failed",
        }:
            location_key = "to" if event_type == "npc_arrived" else "from"
            observed_location = payload.get(location_key)
            npc_observed_locations[npc_code] = (
                observed_location
                if visible and isinstance(observed_location, str)
                and observed_location in locations_by_code
                else None
            )
        if event_type == "item_acquired":
            item_code = payload.get("item")
            if (
                visible
                and isinstance(item_code, str)
                and item_code in items_by_code
                and isinstance(payload.get("to"), str)
            ):
                item_observed_owners[item_code] = payload["to"]
            elif not visible:
                # Hidden item transfers do not identify their item in the public
                # event row, so fail closed until a later public event re-establishes
                # an item's owner.
                item_observed_owners = {
                    code: None for code in item_observed_owners
                }

    perceivable_npc_codes: set[str] = set()
    perceivable_npc_template_ids: set[str] = set()
    perceivable_item_instance_keys: set[str] = set()
    if location_is_perceivable:
        for npc_code, npc_location in runtime.state.npc_positions.items():
            template = npcs_by_code.get(npc_code)
            if template is None or npc_location != requested_location_code:
                continue
            baseline_location = initial_state.npc_positions.get(npc_code)
            observed_location = npc_observed_locations.get(
                npc_code, baseline_location
            )
            if observed_location == requested_location_code:
                perceivable_npc_codes.add(npc_code)
                perceivable_npc_template_ids.add(template.id)
        for item_code, item_state in runtime.state.item_instances.items():
            if item_state.owner_type != "location" or item_state.owner_ref != requested_location_code:
                continue
            known_owner = item_observed_owners.get(item_code)
            if (
                item_code in items_by_code
                and known_owner == f"location:{requested_location_code}"
            ):
                perceivable_item_instance_keys.add(item_code)

    # Only player-visible event rows extend remembered NPC identities. Hidden
    # payloads, route overrides, plans, and future steps never enter this set.
    known_npc_codes.update(perceivable_npc_codes)
    known_npc_template_ids = {
        npcs_by_code[code].id for code in known_npc_codes if code in npcs_by_code
    }

    return ContentPublicVisibility(
        current_location_id=current_location.id,
        location_is_perceivable=location_is_perceivable,
        perceivable_npc_codes=frozenset(perceivable_npc_codes),
        perceivable_npc_template_ids=frozenset(perceivable_npc_template_ids),
        perceivable_item_instance_keys=frozenset(perceivable_item_instance_keys),
        known_npc_codes=frozenset(known_npc_codes),
        known_npc_template_ids=frozenset(known_npc_template_ids),
    )


class ProjectionBuilder(Generic[P]):
    """
    Base class for projection builders.
    
    Projection builders filter events and state information based on
    perspective rules, ensuring each entity only sees what they should.
    """
    
    _perception_resolver: PerceptionResolver
    
    def __init__(self, perception_resolver: PerceptionResolver | None = None):
        self._perception_resolver = perception_resolver or PerceptionResolver()
    
    def build_projection(
        self,
        events: list[GameEvent],
        perspective: P,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("Subclasses must implement build_projection")


class PlayerVisibleProjectionBuilder(ProjectionBuilder[PlayerPerspective]):
    """
    Builds projections containing only player-visible events.
    
    This builder filters events based on:
    1. Player's location (same location = direct observation)
    2. Event visibility scope (world events visible anywhere)
    3. Hidden events (never visible to player)
    4. Rumor propagation (events that spread to player's location)
    """
    
    def build_projection(
        self,
        events: list[GameEvent],
        perspective: PlayerPerspective,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if context is None:
            context = {}
        
        player_location_id: str = context.get("player_location_id", "unknown")
        current_turn: int = context.get("current_turn", 0)
        
        visible_events: list[dict[str, Any]] = []
        
        for event in events:
            event_visibility = self._perception_resolver.extract_event_visibility(event)
            
            result = self._perception_resolver.resolve_perception(
                event=event,
                event_visibility=event_visibility,
                observer_location_id=player_location_id,
                observer_perspective=perspective,
                current_turn=current_turn,
            )
            
            if result.can_perceive:
                visible_event = self._create_visible_event_dict(
                    event, result, include_private=False
                )
                visible_events.append(visible_event)
        
        return visible_events
    
    def _create_visible_event_dict(
        self,
        event: GameEvent,
        perception_result: PerceptionResult,
        include_private: bool = False,
    ) -> dict[str, Any]:
        event_dict = event.model_dump()
        
        if not include_private:
            self._remove_private_payload_recursive(event_dict)
        
        event_dict["_perception"] = {
            "type": perception_result.perception_type.value,
            "channel": perception_result.sensory_channel.value,
            "confidence": perception_result.confidence,
            "distance": perception_result.distance,
        }
        
        return event_dict
    
    def _remove_private_payload_recursive(self, data: dict[str, Any]) -> None:
        if "private_payload" in data:
            del data["private_payload"]
        
        for value in data.values():
            if isinstance(value, dict):
                self._remove_private_payload_recursive(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self._remove_private_payload_recursive(item)


class NPCVisibleProjectionBuilder(ProjectionBuilder[NPCPerspective]):
    """
    Builds projections containing only events an NPC can perceive.
    
    This builder filters events based on:
    1. NPC's location (same location = direct observation)
    2. NPC's knowledge state (known facts, rumors, secrets)
    3. Forbidden knowledge (events the NPC cannot know about)
    4. Event visibility scope
    5. Rumor propagation
    """
    
    def build_projection(
        self,
        events: list[GameEvent],
        perspective: NPCPerspective,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if context is None:
            context = {}
        
        npc_location_id: str = context.get("npc_location_id", "unknown")
        current_turn: int = context.get("current_turn", 0)
        
        visible_events: list[dict[str, Any]] = []
        
        for event in events:
            event_visibility = self._perception_resolver.extract_event_visibility(event)
            
            result = self._perception_resolver.resolve_perception(
                event=event,
                event_visibility=event_visibility,
                observer_location_id=npc_location_id,
                observer_perspective=perspective,
                current_turn=current_turn,
            )
            
            if result.can_perceive:
                visible_event = self._create_npc_visible_event_dict(
                    event, result, perspective
                )
                visible_events.append(visible_event)
        
        return visible_events
    
    def _create_npc_visible_event_dict(
        self,
        event: GameEvent,
        perception_result: PerceptionResult,
        perspective: NPCPerspective,
    ) -> dict[str, Any]:
        event_dict = event.model_dump()
        
        self._remove_private_payload_recursive(event_dict)
        
        event_dict["_perception"] = {
            "type": perception_result.perception_type.value,
            "channel": perception_result.sensory_channel.value,
            "confidence": perception_result.confidence,
            "distance": perception_result.distance,
        }
        
        event_dict["_npc_context"] = {
            "is_known_fact": self._is_known_fact(event, perspective),
            "matches_belief": self._matches_belief(event, perspective),
            "is_secret": self._is_secret(event, perspective),
        }
        
        return event_dict
    
    def _remove_private_payload_recursive(self, data: dict[str, Any]) -> None:
        if "private_payload" in data:
            del data["private_payload"]
        
        for value in data.values():
            if isinstance(value, dict):
                self._remove_private_payload_recursive(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self._remove_private_payload_recursive(item)
    
    def _is_known_fact(self, event: GameEvent, perspective: NPCPerspective) -> bool:
        event_id = event.event_id
        if event_id in perspective.known_facts:
            return True
        
        related_entities = event.metadata.get("related_entities", [])
        if isinstance(related_entities, list):
            for entity_id in related_entities:
                if isinstance(entity_id, str) and entity_id in perspective.known_facts:
                    return True
        
        return False
    
    def _matches_belief(self, event: GameEvent, perspective: NPCPerspective) -> bool:
        event_id = event.event_id
        if event_id in perspective.believed_rumors:
            return True
        
        event_content = str(event.metadata).lower()
        for rumor_id in perspective.believed_rumors:
            if rumor_id.lower() in event_content:
                return True
        
        return False
    
    def _is_secret(self, event: GameEvent, perspective: NPCPerspective) -> bool:
        event_id = event.event_id
        if event_id in perspective.secrets:
            return True
        
        secret_indicators = event.metadata.get("secret_indicators", [])
        if isinstance(secret_indicators, list):
            for indicator in secret_indicators:
                if isinstance(indicator, str) and indicator in perspective.secrets:
                    return True
        
        return False


class NarratorProjectionBuilder(ProjectionBuilder[NarratorPerspective]):
    """
    Builds projections for narration, excluding private_payload.
    
    The narrator projection is special because:
    1. It uses PlayerVisibleProjection (narrator only narrates what player sees)
    2. It ALWAYS excludes private_payload (narrator never reveals hidden info)
    3. It adds narration-specific metadata (tone, pacing, style hints)
    
    CRITICAL: The narrator should NEVER have access to:
    - private_payload from any event
    - Hidden lore not yet revealed to the player
    - NPC internal states or thoughts
    - World engine private calculations
    """
    
    _player_builder: PlayerVisibleProjectionBuilder
    
    def __init__(
        self,
        perception_resolver: PerceptionResolver | None = None,
        player_projection_builder: PlayerVisibleProjectionBuilder | None = None,
    ):
        super().__init__(perception_resolver)
        self._player_builder = player_projection_builder or PlayerVisibleProjectionBuilder(
            perception_resolver=self._perception_resolver
        )
    
    def build_projection(
        self,
        events: list[GameEvent],
        perspective: NarratorPerspective,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if context is None:
            context = {}
        
        player_perspective = context.get("player_perspective")
        if player_perspective is None:
            player_perspective = PlayerPerspective(
                perspective_id="player",
                owner_id="player",
            )
        
        player_visible_events = self._player_builder.build_projection(
            events=events,
            perspective=player_perspective,
            context=context,
        )
        
        narration_events: list[dict[str, Any]] = []
        for event_dict in player_visible_events:
            narration_event = self._create_narration_event_dict(
                event_dict, perspective
            )
            narration_events.append(narration_event)
        
        return narration_events
    
    def _create_narration_event_dict(
        self,
        event_dict: dict[str, Any],
        perspective: NarratorPerspective,
    ) -> dict[str, Any]:
        narration_dict = dict(event_dict)
        
        if "private_payload" in narration_dict:
            del narration_dict["private_payload"]
        
        self._remove_private_payload_recursive(narration_dict)
        
        narration_dict["_narration"] = {
            "tone": perspective.tone,
            "pacing": perspective.pacing,
            "style_requirements": perspective.style_requirements,
            "forbidden_info": perspective.forbidden_info,
            "allowed_hints": perspective.allowed_hints,
        }
        
        narration_dict["_foreshadowing"] = self._get_foreshadowing_hints(
            event_dict, perspective
        )
        
        return narration_dict
    
    def _remove_private_payload_recursive(self, data: dict[str, Any]) -> None:
        if "private_payload" in data:
            del data["private_payload"]
        
        for value in data.values():
            if isinstance(value, dict):
                self._remove_private_payload_recursive(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self._remove_private_payload_recursive(item)
    
    def _get_foreshadowing_hints(
        self,
        event_dict: dict[str, Any],
        perspective: NarratorPerspective,
    ) -> list[str]:
        hints: list[str] = []
        
        event_data = event_dict.get("metadata", {})
        
        for hint in perspective.allowed_hints:
            if hint.lower() in str(event_data).lower():
                hints.append(hint)
        
        return hints
    
    def build_narration_context(
        self,
        events: list[GameEvent],
        perspective: NarratorPerspective,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if context is None:
            context = {}
        
        narration_events = self.build_projection(events, perspective, context)
        
        narration_context: dict[str, Any] = {
            "events": narration_events,
            "narration_settings": {
                "tone": perspective.tone,
                "pacing": perspective.pacing,
                "style_requirements": perspective.style_requirements,
            },
            "constraints": {
                "forbidden_info": perspective.forbidden_info,
                "allowed_hints": perspective.allowed_hints,
                "never_reveal": [
                    "private_payload",
                    "hidden_lore",
                    "npc_internal_states",
                    "world_engine_calculations",
                ],
            },
        }
        
        return narration_context
