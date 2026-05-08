"""
PerceptionResolver - Determines who can perceive what events.

This module implements perception rules for the perspective-aware memory system:
- Same location + visible event → direct observation
- Same location + sound event → heard
- Different location + message propagation → rumor

The resolver works with the existing PerspectiveService to determine
what entities (players, NPCs) can perceive based on:
1. Location proximity
2. Event visibility scope
3. Sensory channels (visual, auditory, etc.)
4. Message propagation rules
"""

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field

from ..models.events import (
    GameEvent,
    SceneEvent,
    NPCActionEvent,
    PlayerInputEvent,
)
from ..models.perspectives import (
    Perspective,
    WorldPerspective,
    PlayerPerspective,
    NPCPerspective,
)
from ..models.states import CanonicalState


class SensoryChannel(str, Enum):
    """Sensory channels through which events can be perceived."""
    VISUAL = "visual"
    AUDITORY = "auditory"
    OLFACTORY = "olfactory"
    TACTILE = "tactile"
    TELEPATHIC = "telepathic"
    NONE = "none"  # Events that cannot be directly perceived


class PerceptionType(str, Enum):
    """Types of perception results."""
    DIRECT_OBSERVATION = "direct_observation"  # Saw it happen
    HEARD = "heard"  # Heard about it (sound traveled)
    RUMOR = "rumor"  # Heard through message propagation
    HIDDEN = "hidden"  # Cannot perceive
    FORBIDDEN = "forbidden"  # Explicitly forbidden knowledge


@dataclass
class PerceptionResult:
    """Result of a perception check."""
    can_perceive: bool
    perception_type: PerceptionType
    sensory_channel: SensoryChannel
    confidence: float = 1.0
    reason: str = ""
    perceived_content: str | None = None
    distance: int = 0  # 0 = same location, 1+ = number of hops


class EventVisibility(BaseModel):
    """Visibility metadata for an event."""
    event_id: str = Field(..., description="Event ID")
    location_id: str = Field(..., description="Where the event occurred")
    visibility_scope: str = Field(default="location", description="Visibility scope: location, region, world")
    sensory_channels: list[SensoryChannel] = Field(default_factory=lambda: [SensoryChannel.VISUAL])
    is_hidden: bool = Field(default=False, description="Whether event is intentionally hidden")
    can_propagate: bool = Field(default=True, description="Whether event can spread as rumor")
    propagation_delay_turns: int = Field(default=0, description="Turns before rumor spreads")
    actor_id: str | None = Field(default=None, description="Who caused the event")


class PerceptionResolver:
    """
    Resolves who can perceive what events based on location, visibility, and sensory channels.
    
    Perception Rules:
    1. Same location + visible event → direct observation
    2. Same location + sound event → heard
    3. Different location + message propagation → rumor
    4. Hidden events → not perceivable (unless explicitly known)
    5. Forbidden knowledge → blocked regardless of other factors
    
    The resolver does NOT modify existing PerspectiveService - it works alongside it.
    """
    
    def __init__(self):
        self._location_graph: dict[str, set[str]] = {}
        self._propagation_state: dict[str, dict[str, int]] = {}
    
    def register_location_connection(self, location_a: str, location_b: str) -> None:
        """Register that two locations are connected (for rumor propagation)."""
        if location_a not in self._location_graph:
            self._location_graph[location_a] = set()
        if location_b not in self._location_graph:
            self._location_graph[location_b] = set()
        self._location_graph[location_a].add(location_b)
        self._location_graph[location_b].add(location_a)
    
    def resolve_perception(
        self,
        event: GameEvent,
        event_visibility: EventVisibility,
        observer_location_id: str,
        observer_perspective: Perspective | None = None,
        current_turn: int = 0,
    ) -> PerceptionResult:
        """
        Determine if an observer can perceive an event.
        
        Args:
            event: The game event to check
            event_visibility: Visibility metadata for the event
            observer_location_id: Where the observer is located
            observer_perspective: The observer's perspective (for knowledge checks)
            current_turn: Current game turn (for propagation timing)
        
        Returns:
            PerceptionResult indicating if and how the event was perceived
        """
        # World perspective sees everything (even hidden events)
        if isinstance(observer_perspective, WorldPerspective):
            return PerceptionResult(
                can_perceive=True,
                perception_type=PerceptionType.DIRECT_OBSERVATION,
                sensory_channel=SensoryChannel.VISUAL,
                reason="World perspective sees all",
            )
        
        # Hidden events are never directly perceivable
        if event_visibility.is_hidden:
            return PerceptionResult(
                can_perceive=False,
                perception_type=PerceptionType.HIDDEN,
                sensory_channel=SensoryChannel.NONE,
                reason="Event is intentionally hidden",
            )
        
        # Check forbidden knowledge for NPCs
        if isinstance(observer_perspective, NPCPerspective):
            if event.event_id in observer_perspective.forbidden_knowledge:
                return PerceptionResult(
                    can_perceive=False,
                    perception_type=PerceptionType.FORBIDDEN,
                    sensory_channel=SensoryChannel.NONE,
                    reason="Event is forbidden knowledge for this NPC",
                )
        
        # Same location - direct perception
        if observer_location_id == event_visibility.location_id:
            return self._resolve_same_location(event_visibility, observer_perspective)
        
        # Different location - check propagation
        return self._resolve_different_location(
            event,
            event_visibility,
            observer_location_id,
            observer_perspective,
            current_turn,
        )
    
    def _resolve_same_location(
        self,
        event_visibility: EventVisibility,
        observer_perspective: Perspective | None,
    ) -> PerceptionResult:
        """Resolve perception when observer is at the same location as the event."""
        # Check visibility scope
        if event_visibility.visibility_scope == "world":
            # World-scoped events are visible to everyone
            return PerceptionResult(
                can_perceive=True,
                perception_type=PerceptionType.DIRECT_OBSERVATION,
                sensory_channel=event_visibility.sensory_channels[0] if event_visibility.sensory_channels else SensoryChannel.VISUAL,
                reason="World-scoped event visible at same location",
            )
        
        # Check sensory channels
        if SensoryChannel.VISUAL in event_visibility.sensory_channels:
            return PerceptionResult(
                can_perceive=True,
                perception_type=PerceptionType.DIRECT_OBSERVATION,
                sensory_channel=SensoryChannel.VISUAL,
                reason="Direct visual observation at same location",
            )
        
        if SensoryChannel.AUDITORY in event_visibility.sensory_channels:
            return PerceptionResult(
                can_perceive=True,
                perception_type=PerceptionType.HEARD,
                sensory_channel=SensoryChannel.AUDITORY,
                confidence=0.8,  # Slightly less reliable than visual
                reason="Heard event at same location",
            )
        
        # Other sensory channels
        if event_visibility.sensory_channels:
            return PerceptionResult(
                can_perceive=True,
                perception_type=PerceptionType.DIRECT_OBSERVATION,
                sensory_channel=event_visibility.sensory_channels[0],
                confidence=0.7,
                reason=f"Perceived via {event_visibility.sensory_channels[0].value} at same location",
            )
        
        # No sensory channels - cannot perceive
        return PerceptionResult(
            can_perceive=False,
            perception_type=PerceptionType.HIDDEN,
            sensory_channel=SensoryChannel.NONE,
            reason="Event has no perceivable sensory channels",
        )
    
    def _resolve_different_location(
        self,
        event: GameEvent,
        event_visibility: EventVisibility,
        observer_location_id: str,
        observer_perspective: Perspective | None,
        current_turn: int,
    ) -> PerceptionResult:
        """Resolve perception when observer is at a different location."""
        # World-scoped events are visible from anywhere
        if event_visibility.visibility_scope == "world":
            return PerceptionResult(
                can_perceive=True,
                perception_type=PerceptionType.DIRECT_OBSERVATION,
                sensory_channel=event_visibility.sensory_channels[0] if event_visibility.sensory_channels else SensoryChannel.VISUAL,
                reason="World-scoped event visible from any location",
            )
        
        # Check if event can propagate
        if not event_visibility.can_propagate:
            return PerceptionResult(
                can_perceive=False,
                perception_type=PerceptionType.HIDDEN,
                sensory_channel=SensoryChannel.NONE,
                reason="Event cannot propagate beyond its location",
            )
        
        # Check visibility scope
        if event_visibility.visibility_scope == "location":
            return PerceptionResult(
                can_perceive=False,
                perception_type=PerceptionType.HIDDEN,
                sensory_channel=SensoryChannel.NONE,
                reason="Location-scoped event not perceivable from different location",
            )
        
        # Check propagation delay
        event_turn = event.turn_index
        turns_since_event = current_turn - event_turn
        if turns_since_event < event_visibility.propagation_delay_turns:
            return PerceptionResult(
                can_perceive=False,
                perception_type=PerceptionType.HIDDEN,
                sensory_channel=SensoryChannel.NONE,
                reason=f"Event not yet propagated (need {event_visibility.propagation_delay_turns} turns)",
            )
        
        # Calculate distance for rumor propagation
        distance = self._calculate_distance(
            event_visibility.location_id,
            observer_location_id,
        )
        
        if distance is None:
            # No path between locations
            return PerceptionResult(
                can_perceive=False,
                perception_type=PerceptionType.HIDDEN,
                sensory_channel=SensoryChannel.NONE,
                reason="No connection between locations for propagation",
            )
        
        # Rumor propagation - confidence decreases with distance
        confidence = max(0.1, 1.0 - (distance * 0.2))
        
        return PerceptionResult(
            can_perceive=True,
            perception_type=PerceptionType.RUMOR,
            sensory_channel=SensoryChannel.AUDITORY,
            confidence=confidence,
            distance=distance,
            reason=f"Event propagated as rumor (distance: {distance})",
        )
    
    def _calculate_distance(self, from_location: str, to_location: str) -> int | None:
        """
        Calculate the shortest path distance between two locations.
        
        Uses BFS to find the shortest path in the location graph.
        Returns None if no path exists.
        """
        if from_location == to_location:
            return 0
        
        if from_location not in self._location_graph or to_location not in self._location_graph:
            return None
        
        # BFS to find shortest path
        visited = {from_location}
        queue = [(from_location, 0)]
        
        while queue:
            current, distance = queue.pop(0)
            
            for neighbor in self._location_graph.get(current, set()):
                if neighbor == to_location:
                    return distance + 1
                
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, distance + 1))
        
        return None  # No path found
    
    def get_perceivers(
        self,
        event: GameEvent,
        event_visibility: EventVisibility,
        state: CanonicalState,
        current_turn: int = 0,
    ) -> dict[str, PerceptionResult]:
        """
        Get all entities that can perceive an event.
        
        Args:
            event: The game event
            event_visibility: Visibility metadata
            state: Current canonical state (contains all entity locations)
            current_turn: Current game turn
        
        Returns:
            Dict mapping entity IDs to their perception results
        """
        perceivers = {}
        
        # Check player
        player_location = state.player_state.location_id
        player_perspective = PlayerPerspective(
            perspective_id="player",
            owner_id="player",
            known_facts=state.player_state.known_fact_ids,
        )
        
        player_result = self.resolve_perception(
            event,
            event_visibility,
            player_location,
            player_perspective,
            current_turn,
        )
        perceivers["player"] = player_result
        
        # Check all NPCs
        for npc_id, npc_state in state.npc_states.items():
            npc_perspective = NPCPerspective(
                perspective_id=npc_id,
                owner_id=npc_id,
                npc_id=npc_id,
            )
            
            npc_result = self.resolve_perception(
                event,
                event_visibility,
                npc_state.location_id,
                npc_perspective,
                current_turn,
            )
            perceivers[npc_id] = npc_result
        
        return perceivers
    
    def extract_event_visibility(self, event: GameEvent) -> EventVisibility:
        """
        Extract visibility metadata from a game event.
        
        This method determines the visibility properties of an event
        based on its type and metadata.
        """
        event_id = event.event_id
        location_id = event.metadata.get("location_id", "unknown")
        visibility_scope = event.metadata.get("visibility_scope", "location")
        is_hidden = event.metadata.get("is_hidden", False)
        can_propagate = event.metadata.get("can_propagate", True)
        propagation_delay = event.metadata.get("propagation_delay_turns", 0)
        actor_id = event.metadata.get("actor_id")
        
        # Determine sensory channels based on event type
        sensory_channels = self._determine_sensory_channels(event)
        
        # Special handling for specific event types
        if isinstance(event, SceneEvent):
            location_id = event.metadata.get("location_id", "unknown")
            is_hidden = not event.visible_to_player
            visibility_scope = event.metadata.get("visibility_scope", "location")
        
        elif isinstance(event, NPCActionEvent):
            location_id = event.metadata.get("location_id", "unknown")
            is_hidden = not event.visible_to_player
            actor_id = event.npc_id
        
        elif isinstance(event, PlayerInputEvent):
            location_id = event.metadata.get("location_id", "unknown")
            actor_id = event.actor_id
        
        return EventVisibility(
            event_id=event_id,
            location_id=location_id,
            visibility_scope=visibility_scope,
            sensory_channels=sensory_channels,
            is_hidden=is_hidden,
            can_propagate=can_propagate,
            propagation_delay_turns=propagation_delay,
            actor_id=actor_id,
        )
    
    def _determine_sensory_channels(self, event: GameEvent) -> list[SensoryChannel]:
        """Determine which sensory channels an event uses."""
        # Check if explicitly specified in metadata
        if "sensory_channels" in event.metadata:
            channels = []
            for ch in event.metadata["sensory_channels"]:
                try:
                    channels.append(SensoryChannel(ch))
                except ValueError:
                    pass
            if channels:
                return channels
        
        # Default based on event type
        if isinstance(event, SceneEvent):
            return [SensoryChannel.VISUAL, SensoryChannel.AUDITORY]
        
        if isinstance(event, NPCActionEvent):
            action_type = event.action_type.lower()
            if action_type in ["talk", "speak", "shout", "whisper"]:
                return [SensoryChannel.AUDITORY]
            elif action_type in ["sneak", "hide", "steal"]:
                return [SensoryChannel.VISUAL]  # Harder to perceive
            else:
                return [SensoryChannel.VISUAL, SensoryChannel.AUDITORY]
        
        if isinstance(event, PlayerInputEvent):
            return [SensoryChannel.VISUAL, SensoryChannel.AUDITORY]
        
        # Default: visual
        return [SensoryChannel.VISUAL]
    
    def is_offscreen_event_visible_to_player(
        self,
        event: GameEvent,
        player_location_id: str,
        current_turn: int = 0,
    ) -> bool:
        """
        Check if an offscreen event (event not at player's location) is visible to the player.
        
        This is a convenience method for the common case of checking player visibility.
        
        Args:
            event: The game event to check
            player_location_id: Player's current location
            current_turn: Current game turn
        
        Returns:
            True if the player can perceive the event, False otherwise
        """
        event_visibility = self.extract_event_visibility(event)
        
        player_perspective = PlayerPerspective(
            perspective_id="player",
            owner_id="player",
        )
        
        result = self.resolve_perception(
            event,
            event_visibility,
            player_location_id,
            player_perspective,
            current_turn,
        )
        
        return result.can_perceive
