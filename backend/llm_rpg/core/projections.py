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

from typing import Any, Generic, TypeVar

from ..models.events import GameEvent
from ..models.perspectives import (
    Perspective,
    PlayerPerspective,
    NPCPerspective,
    NarratorPerspective,
)
from .perception import PerceptionResolver, PerceptionResult

P = TypeVar("P", bound=Perspective)


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
