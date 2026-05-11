"""
PerceptionResolver Contract Tests

Tests for perception filtering that respects viewer perspective:
- World perspective sees everything (including hidden events)
- Player perspective cannot see hidden events
- NPC perspective respects forbidden knowledge
- Hidden events are never directly perceivable
- Different location handling with rumor propagation
"""

import pytest
from datetime import datetime

from llm_rpg.core.perception import (
    PerceptionResolver,
    PerceptionResult,
    PerceptionType,
    SensoryChannel,
    EventVisibility,
)
from llm_rpg.models.events import (
    GameEvent,
    EventType,
    SceneEvent,
    NPCActionEvent,
    PlayerInputEvent,
)
from llm_rpg.models.perspectives import (
    WorldPerspective,
    PlayerPerspective,
    NPCPerspective,
    PerspectiveType,
)


class TestPerceptionResolverBasics:
    """Test basic perception resolver functionality."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    @pytest.fixture
    def basic_event(self):
        return GameEvent(
            event_id="event_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            metadata={"location_id": "square"},
        )

    @pytest.fixture
    def visible_event_visibility(self, basic_event):
        return EventVisibility(
            event_id="event_001",
            location_id="square",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.VISUAL],
            is_hidden=False,
            can_propagate=True,
        )

    def test_world_perspective_sees_everything(
        self, resolver, basic_event, visible_event_visibility
    ):
        """WorldPerspective can see all events, including hidden ones."""
        world_perspective = WorldPerspective(
            perspective_id="world",
            owner_id="world",
        )

        result = resolver.resolve_perception(
            event=basic_event,
            event_visibility=visible_event_visibility,
            observer_location_id="different_location",
            observer_perspective=world_perspective,
        )

        assert result.can_perceive is True
        assert result.perception_type == PerceptionType.DIRECT_OBSERVATION
        assert "World perspective sees all" in result.reason

    def test_world_perspective_sees_hidden_events(self, resolver, basic_event):
        """WorldPerspective can see events marked as hidden."""
        world_perspective = WorldPerspective(
            perspective_id="world",
            owner_id="world",
        )

        hidden_visibility = EventVisibility(
            event_id="event_001",
            location_id="square",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.VISUAL],
            is_hidden=True,
            can_propagate=False,
        )

        result = resolver.resolve_perception(
            event=basic_event,
            event_visibility=hidden_visibility,
            observer_location_id="square",
            observer_perspective=world_perspective,
        )

        assert result.can_perceive is True
        assert result.perception_type == PerceptionType.DIRECT_OBSERVATION


class TestHiddenEventFiltering:
    """Test that hidden events are properly filtered for non-world perspectives."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    @pytest.fixture
    def hidden_event(self):
        return GameEvent(
            event_id="hidden_event_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            metadata={
                "location_id": "secret_chamber",
                "is_hidden": True,
            },
        )

    @pytest.fixture
    def hidden_visibility(self):
        return EventVisibility(
            event_id="hidden_event_001",
            location_id="secret_chamber",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.VISUAL],
            is_hidden=True,
            can_propagate=False,
        )

    def test_player_cannot_perceive_hidden_events(
        self, resolver, hidden_event, hidden_visibility
    ):
        """Player perspective cannot see hidden events."""
        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        result = resolver.resolve_perception(
            event=hidden_event,
            event_visibility=hidden_visibility,
            observer_location_id="secret_chamber",
            observer_perspective=player_perspective,
        )

        assert result.can_perceive is False
        assert result.perception_type == PerceptionType.HIDDEN
        assert "intentionally hidden" in result.reason.lower()

    def test_npc_cannot_perceive_hidden_events(
        self, resolver, hidden_event, hidden_visibility
    ):
        """NPC perspective cannot see hidden events."""
        npc_perspective = NPCPerspective(
            perspective_id="npc_1",
            owner_id="npc_1",
            npc_id="npc_1",
        )

        result = resolver.resolve_perception(
            event=hidden_event,
            event_visibility=hidden_visibility,
            observer_location_id="secret_chamber",
            observer_perspective=npc_perspective,
        )

        assert result.can_perceive is False
        assert result.perception_type == PerceptionType.HIDDEN


class TestForbiddenKnowledgeFiltering:
    """Test that forbidden knowledge is blocked for NPCs."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    @pytest.fixture
    def forbidden_event(self):
        return GameEvent(
            event_id="forbidden_event_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            metadata={"location_id": "square"},
        )

    @pytest.fixture
    def normal_visibility(self, forbidden_event):
        return EventVisibility(
            event_id="forbidden_event_001",
            location_id="square",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.VISUAL],
            is_hidden=False,
            can_propagate=True,
        )

    def test_npc_blocked_by_forbidden_knowledge(
        self, resolver, forbidden_event, normal_visibility
    ):
        """NPC cannot perceive events in their forbidden knowledge list."""
        npc_perspective = NPCPerspective(
            perspective_id="npc_1",
            owner_id="npc_1",
            npc_id="npc_1",
            forbidden_knowledge=["forbidden_event_001"],
        )

        result = resolver.resolve_perception(
            event=forbidden_event,
            event_visibility=normal_visibility,
            observer_location_id="square",
            observer_perspective=npc_perspective,
        )

        assert result.can_perceive is False
        assert result.perception_type == PerceptionType.FORBIDDEN
        assert "forbidden knowledge" in result.reason.lower()

    def test_npc_without_forbidden_knowledge_can_perceive(
        self, resolver, forbidden_event, normal_visibility
    ):
        """NPC without forbidden knowledge can perceive normally."""
        npc_perspective = NPCPerspective(
            perspective_id="npc_1",
            owner_id="npc_1",
            npc_id="npc_1",
            forbidden_knowledge=[],
        )

        result = resolver.resolve_perception(
            event=forbidden_event,
            event_visibility=normal_visibility,
            observer_location_id="square",
            observer_perspective=npc_perspective,
        )

        assert result.can_perceive is True
        assert result.perception_type == PerceptionType.DIRECT_OBSERVATION


class TestSameLocationPerception:
    """Test perception when observer is at the same location as the event."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    @pytest.fixture
    def visual_event(self):
        return GameEvent(
            event_id="visual_event_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            metadata={"location_id": "square"},
        )

    @pytest.fixture
    def visual_visibility(self):
        return EventVisibility(
            event_id="visual_event_001",
            location_id="square",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.VISUAL],
            is_hidden=False,
            can_propagate=True,
        )

    def test_same_location_visual_perception(
        self, resolver, visual_event, visual_visibility
    ):
        """Visual events at same location are directly observed."""
        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        result = resolver.resolve_perception(
            event=visual_event,
            event_visibility=visual_visibility,
            observer_location_id="square",
            observer_perspective=player_perspective,
        )

        assert result.can_perceive is True
        assert result.perception_type == PerceptionType.DIRECT_OBSERVATION
        assert result.sensory_channel == SensoryChannel.VISUAL
        assert result.confidence == 1.0

    def test_same_location_auditory_perception(self, resolver):
        """Auditory events at same location are heard."""
        event = GameEvent(
            event_id="auditory_event_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            metadata={"location_id": "square"},
        )

        auditory_visibility = EventVisibility(
            event_id="auditory_event_001",
            location_id="square",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.AUDITORY],
            is_hidden=False,
            can_propagate=True,
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        result = resolver.resolve_perception(
            event=event,
            event_visibility=auditory_visibility,
            observer_location_id="square",
            observer_perspective=player_perspective,
        )

        assert result.can_perceive is True
        assert result.perception_type == PerceptionType.HEARD
        assert result.sensory_channel == SensoryChannel.AUDITORY
        assert result.confidence < 1.0

    def test_world_scoped_events_visible_from_anywhere(self, resolver):
        """World-scoped events are visible from any location."""
        event = GameEvent(
            event_id="world_event_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            metadata={"location_id": "square"},
        )

        world_visibility = EventVisibility(
            event_id="world_event_001",
            location_id="square",
            visibility_scope="world",
            sensory_channels=[SensoryChannel.VISUAL],
            is_hidden=False,
            can_propagate=True,
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        result = resolver.resolve_perception(
            event=event,
            event_visibility=world_visibility,
            observer_location_id="different_location",
            observer_perspective=player_perspective,
        )

        assert result.can_perceive is True
        assert "World-scoped" in result.reason


class TestDifferentLocationPerception:
    """Test perception when observer is at a different location."""

    @pytest.fixture
    def resolver(self):
        resolver = PerceptionResolver()
        resolver.register_location_connection("square", "tavern")
        resolver.register_location_connection("tavern", "market")
        return resolver

    @pytest.fixture
    def local_event_visibility(self):
        return EventVisibility(
            event_id="local_event_001",
            location_id="square",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.VISUAL],
            is_hidden=False,
            can_propagate=True,
        )

    def test_location_scoped_events_not_visible_from_different_location(
        self, resolver, local_event_visibility
    ):
        """Location-scoped events are not visible from different locations."""
        event = GameEvent(
            event_id="local_event_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            metadata={"location_id": "square"},
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        result = resolver.resolve_perception(
            event=event,
            event_visibility=local_event_visibility,
            observer_location_id="tavern",
            observer_perspective=player_perspective,
        )

        assert result.can_perceive is False
        assert result.perception_type == PerceptionType.HIDDEN

    def test_non_propagating_events_not_visible_from_different_location(
        self, resolver
    ):
        """Events that cannot propagate are not visible from different locations."""
        event = GameEvent(
            event_id="non_propagating_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            metadata={"location_id": "square"},
        )

        non_propagating_visibility = EventVisibility(
            event_id="non_propagating_001",
            location_id="square",
            visibility_scope="region",
            sensory_channels=[SensoryChannel.VISUAL],
            is_hidden=False,
            can_propagate=False,
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        result = resolver.resolve_perception(
            event=event,
            event_visibility=non_propagating_visibility,
            observer_location_id="tavern",
            observer_perspective=player_perspective,
        )

        assert result.can_perceive is False
        assert "cannot propagate" in result.reason.lower()


class TestRumorPropagation:
    """Test rumor propagation across connected locations."""

    @pytest.fixture
    def resolver(self):
        resolver = PerceptionResolver()
        resolver.register_location_connection("square", "tavern")
        resolver.register_location_connection("tavern", "market")
        return resolver

    def test_rumor_propagates_to_connected_location(self, resolver):
        """Events can propagate as rumors to connected locations."""
        event = GameEvent(
            event_id="rumor_event_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            metadata={"location_id": "square"},
        )

        region_visibility = EventVisibility(
            event_id="rumor_event_001",
            location_id="square",
            visibility_scope="region",
            sensory_channels=[SensoryChannel.AUDITORY],
            is_hidden=False,
            can_propagate=True,
            propagation_delay_turns=0,
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        result = resolver.resolve_perception(
            event=event,
            event_visibility=region_visibility,
            observer_location_id="tavern",
            observer_perspective=player_perspective,
            current_turn=2,
        )

        assert result.can_perceive is True
        assert result.perception_type == PerceptionType.RUMOR
        assert result.sensory_channel == SensoryChannel.AUDITORY
        assert result.distance == 1
        assert result.confidence < 1.0

    def test_rumor_confidence_decreases_with_distance(self, resolver):
        """Rumor confidence decreases with distance from source."""
        event = GameEvent(
            event_id="distant_rumor_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            metadata={"location_id": "square"},
        )

        region_visibility = EventVisibility(
            event_id="distant_rumor_001",
            location_id="square",
            visibility_scope="region",
            sensory_channels=[SensoryChannel.AUDITORY],
            is_hidden=False,
            can_propagate=True,
            propagation_delay_turns=0,
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        result_near = resolver.resolve_perception(
            event=event,
            event_visibility=region_visibility,
            observer_location_id="tavern",
            observer_perspective=player_perspective,
            current_turn=2,
        )

        result_far = resolver.resolve_perception(
            event=event,
            event_visibility=region_visibility,
            observer_location_id="market",
            observer_perspective=player_perspective,
            current_turn=2,
        )

        assert result_near.distance == 1
        assert result_far.distance == 2
        assert result_near.confidence > result_far.confidence


class TestEventVisibilityExtraction:
    """Test extracting visibility metadata from events."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    def test_extract_visibility_from_scene_event(self, resolver):
        """Visibility is correctly extracted from SceneEvent."""
        event = SceneEvent(
            event_id="scene_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="scene_001",
            trigger="player_entered",
            summary="A mysterious figure appears.",
            visible_to_player=True,
            metadata={"location_id": "square"},
        )

        visibility = resolver.extract_event_visibility(event)

        assert visibility.event_id == "scene_001"
        assert visibility.location_id == "square"
        assert visibility.is_hidden is False

    def test_extract_visibility_from_hidden_scene_event(self, resolver):
        """Hidden SceneEvent is correctly marked."""
        event = SceneEvent(
            event_id="scene_hidden_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="scene_hidden_001",
            trigger="npc_secret_action",
            summary="NPC performs a secret ritual.",
            visible_to_player=False,
            metadata={"location_id": "secret_chamber"},
        )

        visibility = resolver.extract_event_visibility(event)

        assert visibility.is_hidden is True

    def test_extract_visibility_from_npc_action_event(self, resolver):
        """Visibility is correctly extracted from NPCActionEvent."""
        event = NPCActionEvent(
            event_id="npc_action_001",
            event_type=EventType.NPC_ACTION,
            turn_index=1,
            timestamp=datetime.now(),
            npc_id="npc_001",
            action_type="talk",
            summary="NPC speaks to the player.",
            visible_to_player=True,
            metadata={"location_id": "square"},
        )

        visibility = resolver.extract_event_visibility(event)

        assert visibility.actor_id == "npc_001"
        assert visibility.is_hidden is False

    def test_sensory_channels_determined_by_action_type(self, resolver):
        """Sensory channels are determined by NPC action type."""
        talk_event = NPCActionEvent(
            event_id="npc_talk_001",
            event_type=EventType.NPC_ACTION,
            turn_index=1,
            timestamp=datetime.now(),
            npc_id="npc_001",
            action_type="talk",
            summary="NPC speaks.",
            visible_to_player=True,
            metadata={"location_id": "square"},
        )

        sneak_event = NPCActionEvent(
            event_id="npc_sneak_001",
            event_type=EventType.NPC_ACTION,
            turn_index=1,
            timestamp=datetime.now(),
            npc_id="npc_001",
            action_type="sneak",
            summary="NPC sneaks away.",
            visible_to_player=True,
            metadata={"location_id": "square"},
        )

        talk_visibility = resolver.extract_event_visibility(talk_event)
        sneak_visibility = resolver.extract_event_visibility(sneak_event)

        assert SensoryChannel.AUDITORY in talk_visibility.sensory_channels
        assert SensoryChannel.VISUAL in sneak_visibility.sensory_channels


class TestEmptyNullInputHandling:
    """Test handling of empty or null inputs."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    def test_no_sensory_channels_means_hidden(self, resolver):
        """Events with no sensory channels cannot be perceived."""
        event = GameEvent(
            event_id="no_channel_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            metadata={"location_id": "square"},
        )

        no_channel_visibility = EventVisibility(
            event_id="no_channel_001",
            location_id="square",
            visibility_scope="location",
            sensory_channels=[],
            is_hidden=False,
            can_propagate=True,
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        result = resolver.resolve_perception(
            event=event,
            event_visibility=no_channel_visibility,
            observer_location_id="square",
            observer_perspective=player_perspective,
        )

        assert result.can_perceive is False
        assert "no perceivable sensory channels" in result.reason.lower()

    def test_none_perspective_allows_perception(self, resolver):
        """None perspective (unauthenticated) can still perceive non-hidden events."""
        event = GameEvent(
            event_id="anon_event_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            metadata={"location_id": "square"},
        )

        visibility = EventVisibility(
            event_id="anon_event_001",
            location_id="square",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.VISUAL],
            is_hidden=False,
            can_propagate=True,
        )

        result = resolver.resolve_perception(
            event=event,
            event_visibility=visibility,
            observer_location_id="square",
            observer_perspective=None,
        )

        assert result.can_perceive is True


class TestPerceptionDeterminism:
    """Test that perception is deterministic."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    def test_same_input_produces_same_output(self, resolver):
        """Same inputs always produce the same perception result."""
        event = GameEvent(
            event_id="deterministic_001",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            metadata={"location_id": "square"},
        )

        visibility = EventVisibility(
            event_id="deterministic_001",
            location_id="square",
            visibility_scope="location",
            sensory_channels=[SensoryChannel.VISUAL],
            is_hidden=False,
            can_propagate=True,
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        result1 = resolver.resolve_perception(
            event=event,
            event_visibility=visibility,
            observer_location_id="square",
            observer_perspective=player_perspective,
        )

        result2 = resolver.resolve_perception(
            event=event,
            event_visibility=visibility,
            observer_location_id="square",
            observer_perspective=player_perspective,
        )

        assert result1.can_perceive == result2.can_perceive
        assert result1.perception_type == result2.perception_type
        assert result1.sensory_channel == result2.sensory_channel
        assert result1.confidence == result2.confidence


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
