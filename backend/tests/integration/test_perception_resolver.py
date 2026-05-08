"""
Integration tests for PerceptionResolver.

Tests verify that:
- Offscreen events are not visible to players
- Same-location events are directly observed
- Sound events are heard at same location
- Events propagate as rumors across locations
"""

import pytest
from datetime import datetime

from llm_rpg.core.perception import (
    PerceptionResolver,
    EventVisibility,
    SensoryChannel,
    PerceptionType,
)
from llm_rpg.models.events import (
    GameEvent,
    SceneEvent,
    NPCActionEvent,
    PlayerInputEvent,
    EventType,
)
from llm_rpg.models.perspectives import (
    PlayerPerspective,
    NPCPerspective,
    WorldPerspective,
)
from llm_rpg.models.states import (
    CanonicalState,
    PlayerState,
    WorldState,
    CurrentSceneState,
    NPCState,
)
from llm_rpg.models.events import WorldTime


class TestOffscreenEventNotVisibleToPlayer:
    """Test that events happening elsewhere are not visible to the player."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    @pytest.fixture
    def player_perspective(self):
        return PlayerPerspective(
            perspective_id="player",
            owner_id="player",
            known_facts=[],
            known_rumors=[],
        )

    def test_offscreen_event_not_visible_to_player(self, resolver, player_perspective):
        """Player at location A should not see events at location B."""
        event = SceneEvent(
            event_id="scene_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="tavern",
            trigger="NPC conversation",
            summary="NPCs discuss secret plans",
            visible_to_player=True,
            metadata={"location_id": "tavern"},
        )
        
        event_visibility = EventVisibility(
            event_id="scene_001",
            location_id="tavern",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.VISUAL, SensoryChannel.AUDITORY],
        )
        
        result = resolver.resolve_perception(
            event=event,
            event_visibility=event_visibility,
            observer_location_id="forest",
            observer_perspective=player_perspective,
            current_turn=1,
        )
        
        assert result.can_perceive is False
        assert result.perception_type == PerceptionType.HIDDEN
        assert "different location" in result.reason.lower()

    def test_same_location_visible_event_directly_observed(self, resolver, player_perspective):
        """Player at same location as event should directly observe it."""
        event = SceneEvent(
            event_id="scene_002",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="square",
            trigger="Public announcement",
            summary="Town crier announces news",
            visible_to_player=True,
            metadata={"location_id": "square"},
        )
        
        event_visibility = EventVisibility(
            event_id="scene_002",
            location_id="square",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.VISUAL, SensoryChannel.AUDITORY],
        )
        
        result = resolver.resolve_perception(
            event=event,
            event_visibility=event_visibility,
            observer_location_id="square",
            observer_perspective=player_perspective,
            current_turn=1,
        )
        
        assert result.can_perceive is True
        assert result.perception_type == PerceptionType.DIRECT_OBSERVATION
        assert result.sensory_channel == SensoryChannel.VISUAL

    def test_same_location_sound_event_heard(self, resolver, player_perspective):
        """Sound-only events at same location should be heard, not seen."""
        event = NPCActionEvent(
            event_id="action_001",
            event_type=EventType.NPC_ACTION,
            turn_index=1,
            timestamp=datetime.now(),
            npc_id="npc_guard",
            action_type="shout",
            summary="Guard shouts a warning",
            visible_to_player=True,
            metadata={"location_id": "gate"},
        )
        
        event_visibility = EventVisibility(
            event_id="action_001",
            location_id="gate",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.AUDITORY],
        )
        
        result = resolver.resolve_perception(
            event=event,
            event_visibility=event_visibility,
            observer_location_id="gate",
            observer_perspective=player_perspective,
            current_turn=1,
        )
        
        assert result.can_perceive is True
        assert result.perception_type == PerceptionType.HEARD
        assert result.sensory_channel == SensoryChannel.AUDITORY

    def test_hidden_event_not_perceivable(self, resolver, player_perspective):
        """Hidden events should not be perceivable even at same location."""
        event = NPCActionEvent(
            event_id="action_002",
            event_type=EventType.NPC_ACTION,
            turn_index=1,
            timestamp=datetime.now(),
            npc_id="npc_spy",
            action_type="whisper",
            summary="Spy passes secret message",
            visible_to_player=False,
            metadata={"location_id": "alley"},
        )
        
        event_visibility = EventVisibility(
            event_id="action_002",
            location_id="alley",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.AUDITORY],
            is_hidden=True,
        )
        
        result = resolver.resolve_perception(
            event=event,
            event_visibility=event_visibility,
            observer_location_id="alley",
            observer_perspective=player_perspective,
            current_turn=1,
        )
        
        assert result.can_perceive is False
        assert result.perception_type == PerceptionType.HIDDEN

    def test_world_scoped_event_visible_everywhere(self, resolver, player_perspective):
        """World-scoped events should be visible from any location."""
        event = SceneEvent(
            event_id="scene_003",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="world_event",
            trigger="Major world event",
            summary="The sky turns red across the land",
            visible_to_player=True,
            metadata={"location_id": "mountain_peak"},
        )
        
        event_visibility = EventVisibility(
            event_id="scene_003",
            location_id="mountain_peak",
            visibility_scope="world",
            sensory_channels=[SensoryChannel.VISUAL],
        )
        
        result = resolver.resolve_perception(
            event=event,
            event_visibility=event_visibility,
            observer_location_id="distant_village",
            observer_perspective=player_perspective,
            current_turn=1,
        )
        
        assert result.can_perceive is True
        assert result.perception_type == PerceptionType.DIRECT_OBSERVATION


class TestRumorPropagation:
    """Test that events propagate as rumors across connected locations."""

    @pytest.fixture
    def resolver(self):
        r = PerceptionResolver()
        r.register_location_connection("village", "forest")
        r.register_location_connection("forest", "cave")
        r.register_location_connection("cave", "mountain")
        return r

    @pytest.fixture
    def player_perspective(self):
        return PlayerPerspective(
            perspective_id="player",
            owner_id="player",
            known_facts=[],
            known_rumors=[],
        )

    def test_rumor_propagates_to_connected_location(self, resolver, player_perspective):
        """Events should propagate as rumors to connected locations."""
        event = SceneEvent(
            event_id="scene_004",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="village_square",
            trigger="Village gossip",
            summary="Villagers discuss the strange lights",
            visible_to_player=True,
            metadata={"location_id": "village"},
        )
        
        event_visibility = EventVisibility(
            event_id="scene_004",
            location_id="village",
            visibility_scope="region",
            sensory_channels=[SensoryChannel.AUDITORY],
            can_propagate=True,
            propagation_delay_turns=0,
        )
        
        result = resolver.resolve_perception(
            event=event,
            event_visibility=event_visibility,
            observer_location_id="forest",
            observer_perspective=player_perspective,
            current_turn=1,
        )
        
        assert result.can_perceive is True
        assert result.perception_type == PerceptionType.RUMOR
        assert result.distance == 1
        assert result.confidence < 1.0

    def test_rumor_confidence_decreases_with_distance(self, resolver, player_perspective):
        """Rumor confidence should decrease with more hops."""
        event = SceneEvent(
            event_id="scene_005",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="village_square",
            trigger="Village news",
            summary="Important announcement",
            visible_to_player=True,
            metadata={"location_id": "village"},
        )
        
        event_visibility = EventVisibility(
            event_id="scene_005",
            location_id="village",
            visibility_scope="region",
            sensory_channels=[SensoryChannel.AUDITORY],
            can_propagate=True,
            propagation_delay_turns=0,
        )
        
        result_forest = resolver.resolve_perception(
            event=event,
            event_visibility=event_visibility,
            observer_location_id="forest",
            observer_perspective=player_perspective,
            current_turn=1,
        )
        
        result_mountain = resolver.resolve_perception(
            event=event,
            event_visibility=event_visibility,
            observer_location_id="mountain",
            observer_perspective=player_perspective,
            current_turn=1,
        )
        
        assert result_forest.distance == 1
        assert result_mountain.distance == 3
        assert result_mountain.confidence < result_forest.confidence

    def test_no_propagation_without_connection(self, resolver, player_perspective):
        """Events should not propagate to unconnected locations."""
        event = SceneEvent(
            event_id="scene_006",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="village_square",
            trigger="Local event",
            summary="Village festival",
            visible_to_player=True,
            metadata={"location_id": "village"},
        )
        
        event_visibility = EventVisibility(
            event_id="scene_006",
            location_id="village",
            visibility_scope="region",
            sensory_channels=[SensoryChannel.AUDITORY],
            can_propagate=True,
        )
        
        result = resolver.resolve_perception(
            event=event,
            event_visibility=event_visibility,
            observer_location_id="isolated_island",
            observer_perspective=player_perspective,
            current_turn=1,
        )
        
        assert result.can_perceive is False
        assert "no connection" in result.reason.lower()

    def test_propagation_delay_blocks_early_perception(self, resolver, player_perspective):
        """Events with propagation delay should not be perceived immediately."""
        event = SceneEvent(
            event_id="scene_007",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="village_square",
            trigger="Secret meeting",
            summary="Hidden council decision",
            visible_to_player=True,
            metadata={"location_id": "village"},
        )
        
        event_visibility = EventVisibility(
            event_id="scene_007",
            location_id="village",
            visibility_scope="region",
            sensory_channels=[SensoryChannel.AUDITORY],
            can_propagate=True,
            propagation_delay_turns=2,
        )
        
        result_early = resolver.resolve_perception(
            event=event,
            event_visibility=event_visibility,
            observer_location_id="forest",
            observer_perspective=player_perspective,
            current_turn=1,
        )
        
        result_late = resolver.resolve_perception(
            event=event,
            event_visibility=event_visibility,
            observer_location_id="forest",
            observer_perspective=player_perspective,
            current_turn=4,
        )
        
        assert result_early.can_perceive is False
        assert result_late.can_perceive is True


class TestNPCPerception:
    """Test NPC-specific perception rules."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    def test_npc_forbidden_knowledge_blocked(self, resolver):
        """NPC should not perceive forbidden knowledge events."""
        npc_perspective = NPCPerspective(
            perspective_id="npc_1",
            owner_id="npc_1",
            npc_id="npc_1",
            known_facts=[],
            believed_rumors=[],
            forbidden_knowledge=["event_secret"],
        )
        
        event = SceneEvent(
            event_id="event_secret",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="secret_chamber",
            trigger="Secret ritual",
            summary="The dark ritual is performed",
            visible_to_player=False,
            metadata={"location_id": "temple"},
        )
        
        event_visibility = EventVisibility(
            event_id="event_secret",
            location_id="temple",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.VISUAL],
        )
        
        result = resolver.resolve_perception(
            event=event,
            event_visibility=event_visibility,
            observer_location_id="temple",
            observer_perspective=npc_perspective,
            current_turn=1,
        )
        
        assert result.can_perceive is False
        assert result.perception_type == PerceptionType.FORBIDDEN

    def test_world_perspective_sees_all(self, resolver):
        """World perspective should see all events."""
        world_perspective = WorldPerspective(
            perspective_id="world",
            owner_id="world",
        )
        
        event = SceneEvent(
            event_id="scene_hidden",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="hidden_place",
            trigger="Hidden event",
            summary="Something happens in secret",
            visible_to_player=False,
            metadata={"location_id": "nowhere"},
        )
        
        event_visibility = EventVisibility(
            event_id="scene_hidden",
            location_id="nowhere",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.VISUAL],
            is_hidden=True,
        )
        
        result = resolver.resolve_perception(
            event=event,
            event_visibility=event_visibility,
            observer_location_id="anywhere",
            observer_perspective=world_perspective,
            current_turn=1,
        )
        
        assert result.can_perceive is True


class TestEventVisibilityExtraction:
    """Test automatic extraction of event visibility metadata."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    def test_extract_visibility_from_scene_event(self, resolver):
        """Should extract visibility from SceneEvent."""
        event = SceneEvent(
            event_id="scene_008",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="market",
            trigger="Market activity",
            summary="Busy market day",
            visible_to_player=True,
            metadata={"location_id": "market_square"},
        )
        
        visibility = resolver.extract_event_visibility(event)
        
        assert visibility.event_id == "scene_008"
        assert visibility.location_id == "market_square"
        assert visibility.is_hidden is False
        assert SensoryChannel.VISUAL in visibility.sensory_channels

    def test_extract_visibility_from_hidden_scene_event(self, resolver):
        """Hidden SceneEvent should have is_hidden=True."""
        event = SceneEvent(
            event_id="scene_009",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="secret_meeting",
            trigger="Secret meeting",
            summary="Hidden council",
            visible_to_player=False,
            metadata={"location_id": "council_chamber"},
        )
        
        visibility = resolver.extract_event_visibility(event)
        
        assert visibility.is_hidden is True

    def test_extract_visibility_from_npc_action(self, resolver):
        """Should extract visibility from NPCActionEvent."""
        event = NPCActionEvent(
            event_id="action_003",
            event_type=EventType.NPC_ACTION,
            turn_index=1,
            timestamp=datetime.now(),
            npc_id="npc_merchant",
            action_type="talk",
            summary="Merchant haggles",
            visible_to_player=True,
            metadata={"location_id": "shop"},
        )
        
        visibility = resolver.extract_event_visibility(event)
        
        assert visibility.event_id == "action_003"
        assert visibility.actor_id == "npc_merchant"
        assert SensoryChannel.AUDITORY in visibility.sensory_channels

    def test_extract_sensory_channels_from_sneak_action(self, resolver):
        """Sneak actions should only have visual channel."""
        event = NPCActionEvent(
            event_id="action_004",
            event_type=EventType.NPC_ACTION,
            turn_index=1,
            timestamp=datetime.now(),
            npc_id="npc_thief",
            action_type="sneak",
            summary="Thief sneaks around",
            visible_to_player=True,
            metadata={"location_id": "alley"},
        )
        
        visibility = resolver.extract_event_visibility(event)
        
        assert SensoryChannel.VISUAL in visibility.sensory_channels
        assert SensoryChannel.AUDITORY not in visibility.sensory_channels


class TestGetPerceivers:
    """Test getting all perceivers of an event."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    @pytest.fixture
    def mock_state(self):
        return CanonicalState(
            world_state=WorldState(
                entity_id="world_1",
                world_id="test_world",
                current_time=WorldTime(
                    calendar="standard",
                    season="spring",
                    day=1,
                    hour=12,
                    period="morning",
                ),
            ),
            player_state=PlayerState(
                entity_id="player_1",
                name="Test Player",
                location_id="tavern",
            ),
            current_scene_state=CurrentSceneState(
                entity_id="tavern",
                scene_id="tavern",
                location_id="tavern",
                active_actor_ids=["player_1"],
            ),
            location_states={},
            npc_states={
                "npc_1": NPCState(
                    entity_id="npc_1",
                    npc_id="npc_1",
                    name="NPC at tavern",
                    location_id="tavern",
                ),
                "npc_2": NPCState(
                    entity_id="npc_2",
                    npc_id="npc_2",
                    name="NPC elsewhere",
                    location_id="forest",
                ),
            },
            quest_states={},
            faction_states={},
        )

    def test_get_perceivers_returns_all_entities(self, resolver, mock_state):
        """Should return perception results for all entities."""
        event = SceneEvent(
            event_id="scene_010",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="tavern",
            trigger="Bar fight",
            summary="A fight breaks out",
            visible_to_player=True,
            metadata={"location_id": "tavern"},
        )
        
        event_visibility = EventVisibility(
            event_id="scene_010",
            location_id="tavern",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.VISUAL, SensoryChannel.AUDITORY],
        )
        
        perceivers = resolver.get_perceivers(event, event_visibility, mock_state)
        
        assert "player" in perceivers
        assert "npc_1" in perceivers
        assert "npc_2" in perceivers
        
        assert perceivers["player"].can_perceive is True
        assert perceivers["npc_1"].can_perceive is True
        assert perceivers["npc_2"].can_perceive is False


class TestIsOffscreenEventVisibleToPlayer:
    """Test the convenience method for player visibility checks."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    def test_offscreen_event_not_visible(self, resolver):
        """Offscreen event should not be visible to player."""
        event = SceneEvent(
            event_id="scene_011",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="distant_land",
            trigger="Distant event",
            summary="Something happens far away",
            visible_to_player=True,
            metadata={"location_id": "distant_land"},
        )
        
        is_visible = resolver.is_offscreen_event_visible_to_player(
            event=event,
            player_location_id="home",
            current_turn=1,
        )
        
        assert is_visible is False

    def test_same_location_event_visible(self, resolver):
        """Event at player's location should be visible."""
        event = SceneEvent(
            event_id="scene_012",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="home",
            trigger="Local event",
            summary="Something happens nearby",
            visible_to_player=True,
            metadata={"location_id": "home"},
        )
        
        is_visible = resolver.is_offscreen_event_visible_to_player(
            event=event,
            player_location_id="home",
            current_turn=1,
        )
        
        assert is_visible is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
