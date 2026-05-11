"""
ProjectionBuilder Contract Tests

Tests for projection builders that filter events based on perspective:
- PlayerVisibleProjectionBuilder excludes private_payload
- NPCVisibleProjectionBuilder excludes private_payload and respects NPC context
- NarratorProjectionBuilder never reveals private_payload (recursive removal)
- Projections do not mutate source state objects
- Projections produce deterministic output
"""

import pytest
from datetime import datetime
from copy import deepcopy

from llm_rpg.core.projections import (
    ProjectionBuilder,
    PlayerVisibleProjectionBuilder,
    NPCVisibleProjectionBuilder,
    NarratorProjectionBuilder,
)
from llm_rpg.core.perception import PerceptionResolver, SensoryChannel
from llm_rpg.models.events import (
    GameEvent,
    EventType,
    SceneEvent,
    NPCActionEvent,
)
from llm_rpg.models.perspectives import (
    PlayerPerspective,
    NPCPerspective,
    NarratorPerspective,
)


class TestPlayerVisibleProjectionBuilder:
    """Test PlayerVisibleProjectionBuilder functionality."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    @pytest.fixture
    def builder(self, resolver):
        return PlayerVisibleProjectionBuilder(perception_resolver=resolver)

    @pytest.fixture
    def sample_events(self):
        return [
            SceneEvent(
                event_id="scene_001",
                event_type=EventType.SCENE_EVENT,
                turn_index=1,
                timestamp=datetime.now(),
                scene_id="scene_001",
                trigger="player_entered",
                summary="A mysterious figure appears.",
                visible_to_player=True,
                metadata={
                    "location_id": "square",
                    "private_payload": {"secret_info": "The figure is a demon"},
                },
            ),
            SceneEvent(
                event_id="scene_002",
                event_type=EventType.SCENE_EVENT,
                turn_index=2,
                timestamp=datetime.now(),
                scene_id="scene_002",
                trigger="npc_action",
                summary="The figure speaks.",
                visible_to_player=True,
                metadata={
                    "location_id": "square",
                    "private_payload": {"hidden_identity": "demon_lord"},
                },
            ),
        ]

    def test_player_projection_excludes_private_payload(
        self, builder, sample_events
    ):
        """Player-visible projections must not include private_payload."""
        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
        }

        projections = builder.build_projection(
            events=sample_events,
            perspective=player_perspective,
            context=context,
        )

        assert len(projections) > 0

        for proj in projections:
            assert "private_payload" not in proj
            assert "secret_info" not in str(proj)
            assert "hidden_identity" not in str(proj)

    def test_player_projection_includes_perception_metadata(
        self, builder, sample_events
    ):
        """Projections include perception metadata."""
        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
        }

        projections = builder.build_projection(
            events=sample_events,
            perspective=player_perspective,
            context=context,
        )

        for proj in projections:
            assert "_perception" in proj
            assert "type" in proj["_perception"]
            assert "channel" in proj["_perception"]
            assert "confidence" in proj["_perception"]

    def test_player_projection_filters_by_location(self, builder):
        """Player only sees events at their location (unless world-scoped)."""
        events = [
            SceneEvent(
                event_id="local_event",
                event_type=EventType.SCENE_EVENT,
                turn_index=1,
                timestamp=datetime.now(),
                scene_id="scene_001",
                trigger="test",
                summary="Local event.",
                visible_to_player=True,
                metadata={"location_id": "square"},
            ),
            SceneEvent(
                event_id="remote_event",
                event_type=EventType.SCENE_EVENT,
                turn_index=1,
                timestamp=datetime.now(),
                scene_id="scene_002",
                trigger="test",
                summary="Remote event.",
                visible_to_player=True,
                metadata={"location_id": "tavern"},
            ),
        ]

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
        }

        projections = builder.build_projection(
            events=events,
            perspective=player_perspective,
            context=context,
        )

        event_ids = [p["event_id"] for p in projections]
        assert "local_event" in event_ids
        assert "remote_event" not in event_ids


class TestNPCVisibleProjectionBuilder:
    """Test NPCVisibleProjectionBuilder functionality."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    @pytest.fixture
    def builder(self, resolver):
        return NPCVisibleProjectionBuilder(perception_resolver=resolver)

    @pytest.fixture
    def sample_events(self):
        return [
            NPCActionEvent(
                event_id="npc_action_001",
                event_type=EventType.NPC_ACTION,
                turn_index=1,
                timestamp=datetime.now(),
                npc_id="npc_001",
                action_type="talk",
                summary="NPC speaks.",
                visible_to_player=True,
                metadata={
                    "location_id": "square",
                    "private_payload": {"internal_thought": "I hate this player"},
                },
            ),
        ]

    def test_npc_projection_excludes_private_payload(self, builder, sample_events):
        """NPC-visible projections must not include private_payload."""
        npc_perspective = NPCPerspective(
            perspective_id="npc_002",
            owner_id="npc_002",
            npc_id="npc_002",
        )

        context = {
            "npc_location_id": "square",
            "current_turn": 1,
        }

        projections = builder.build_projection(
            events=sample_events,
            perspective=npc_perspective,
            context=context,
        )

        for proj in projections:
            assert "private_payload" not in proj
            assert "internal_thought" not in str(proj)

    def test_npc_projection_includes_npc_context(self, builder, sample_events):
        """NPC projections include NPC-specific context metadata."""
        npc_perspective = NPCPerspective(
            perspective_id="npc_002",
            owner_id="npc_002",
            npc_id="npc_002",
            known_facts=["fact_001"],
            believed_rumors=["rumor_001"],
            secrets=["secret_001"],
        )

        context = {
            "npc_location_id": "square",
            "current_turn": 1,
        }

        projections = builder.build_projection(
            events=sample_events,
            perspective=npc_perspective,
            context=context,
        )

        for proj in projections:
            assert "_npc_context" in proj
            assert "is_known_fact" in proj["_npc_context"]
            assert "matches_belief" in proj["_npc_context"]
            assert "is_secret" in proj["_npc_context"]


class TestNarratorProjectionBuilder:
    """Test NarratorProjectionBuilder functionality."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    @pytest.fixture
    def player_builder(self, resolver):
        return PlayerVisibleProjectionBuilder(perception_resolver=resolver)

    @pytest.fixture
    def narrator_builder(self, resolver, player_builder):
        return NarratorProjectionBuilder(
            perception_resolver=resolver,
            player_projection_builder=player_builder,
        )

    @pytest.fixture
    def events_with_nested_private_payload(self):
        return [
            SceneEvent(
                event_id="narration_001",
                event_type=EventType.SCENE_EVENT,
                turn_index=1,
                timestamp=datetime.now(),
                scene_id="scene_001",
                trigger="test",
                summary="A scene unfolds.",
                visible_to_player=True,
                metadata={
                    "location_id": "square",
                    "private_payload": {"secret": "hidden truth"},
                    "nested": {
                        "data": "visible",
                        "private_payload": {"another_secret": "deeper hidden"},
                    },
                },
            ),
        ]

    def test_narrator_never_includes_private_payload(
        self, narrator_builder, events_with_nested_private_payload
    ):
        """Narrator projections must NEVER contain private_payload."""
        narrator_perspective = NarratorPerspective(
            perspective_id="narrator",
            owner_id="narrator",
            base_perspective_id="player_1",
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
            "player_perspective": player_perspective,
        }

        projections = narrator_builder.build_projection(
            events=events_with_nested_private_payload,
            perspective=narrator_perspective,
            context=context,
        )

        for proj in projections:
            assert "private_payload" not in proj
            assert "secret" not in str(proj)
            assert "hidden truth" not in str(proj)

    def test_narrator_removes_nested_private_payload(
        self, narrator_builder, events_with_nested_private_payload
    ):
        """Narrator projections recursively remove private_payload from nested structures."""
        narrator_perspective = NarratorPerspective(
            perspective_id="narrator",
            owner_id="narrator",
            base_perspective_id="player_1",
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
            "player_perspective": player_perspective,
        }

        projections = narrator_builder.build_projection(
            events=events_with_nested_private_payload,
            perspective=narrator_perspective,
            context=context,
        )

        for proj in projections:
            if "nested" in proj:
                assert "private_payload" not in proj["nested"]
                assert "another_secret" not in str(proj.get("nested", {}))

    def test_narrator_includes_narration_metadata(
        self, narrator_builder, events_with_nested_private_payload
    ):
        """Narrator projections include narration-specific metadata."""
        narrator_perspective = NarratorPerspective(
            perspective_id="narrator",
            owner_id="narrator",
            base_perspective_id="player_1",
            tone="mysterious",
            pacing="slow",
            forbidden_info=["secret_truth"],
            allowed_hints=["mysterious_figure"],
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
            "player_perspective": player_perspective,
        }

        projections = narrator_builder.build_projection(
            events=events_with_nested_private_payload,
            perspective=narrator_perspective,
            context=context,
        )

        for proj in projections:
            assert "_narration" in proj
            assert proj["_narration"]["tone"] == "mysterious"
            assert proj["_narration"]["pacing"] == "slow"
            assert "forbidden_info" in proj["_narration"]

    def test_narrator_build_narration_context(
        self, narrator_builder, events_with_nested_private_payload
    ):
        """build_narration_context returns complete narration context."""
        narrator_perspective = NarratorPerspective(
            perspective_id="narrator",
            owner_id="narrator",
            base_perspective_id="player_1",
            tone="dramatic",
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
            "player_perspective": player_perspective,
        }

        narration_context = narrator_builder.build_narration_context(
            events=events_with_nested_private_payload,
            perspective=narrator_perspective,
            context=context,
        )

        assert "events" in narration_context
        assert "narration_settings" in narration_context
        assert "constraints" in narration_context
        assert "never_reveal" in narration_context["constraints"]
        assert "private_payload" in narration_context["constraints"]["never_reveal"]


class TestProjectionImmutability:
    """Test that projections do not mutate source state objects."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    @pytest.fixture
    def player_builder(self, resolver):
        return PlayerVisibleProjectionBuilder(perception_resolver=resolver)

    @pytest.fixture
    def npc_builder(self, resolver):
        return NPCVisibleProjectionBuilder(perception_resolver=resolver)

    @pytest.fixture
    def narrator_builder(self, resolver, player_builder):
        return NarratorProjectionBuilder(
            perception_resolver=resolver,
            player_projection_builder=player_builder,
        )

    @pytest.fixture
    def event_with_payload(self):
        return SceneEvent(
            event_id="immutable_test",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="scene_001",
            trigger="test",
            summary="Test event.",
            visible_to_player=True,
            metadata={
                "location_id": "square",
                "private_payload": {"secret": "should_not_change"},
                "other_data": "visible",
            },
        )

    def test_player_projection_does_not_mutate_source(
        self, player_builder, event_with_payload
    ):
        """PlayerVisibleProjectionBuilder must not mutate source events."""
        original_metadata = deepcopy(event_with_payload.metadata)

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
        }

        player_builder.build_projection(
            events=[event_with_payload],
            perspective=player_perspective,
            context=context,
        )

        assert event_with_payload.metadata == original_metadata
        assert "private_payload" in event_with_payload.metadata

    def test_npc_projection_does_not_mutate_source(
        self, npc_builder, event_with_payload
    ):
        """NPCVisibleProjectionBuilder must not mutate source events."""
        original_metadata = deepcopy(event_with_payload.metadata)

        npc_perspective = NPCPerspective(
            perspective_id="npc_1",
            owner_id="npc_1",
            npc_id="npc_1",
        )

        context = {
            "npc_location_id": "square",
            "current_turn": 1,
        }

        npc_builder.build_projection(
            events=[event_with_payload],
            perspective=npc_perspective,
            context=context,
        )

        assert event_with_payload.metadata == original_metadata
        assert "private_payload" in event_with_payload.metadata

    def test_narrator_projection_does_not_mutate_source(
        self, narrator_builder, event_with_payload
    ):
        """NarratorProjectionBuilder must not mutate source events."""
        original_metadata = deepcopy(event_with_payload.metadata)

        narrator_perspective = NarratorPerspective(
            perspective_id="narrator",
            owner_id="narrator",
            base_perspective_id="player_1",
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
            "player_perspective": player_perspective,
        }

        narrator_builder.build_projection(
            events=[event_with_payload],
            perspective=narrator_perspective,
            context=context,
        )

        assert event_with_payload.metadata == original_metadata
        assert "private_payload" in event_with_payload.metadata


class TestProjectionDeterminism:
    """Test that projections produce deterministic output."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    @pytest.fixture
    def player_builder(self, resolver):
        return PlayerVisibleProjectionBuilder(perception_resolver=resolver)

    @pytest.fixture
    def sample_events(self):
        return [
            SceneEvent(
                event_id="determinism_test",
                event_type=EventType.SCENE_EVENT,
                turn_index=1,
                timestamp=datetime.now(),
                scene_id="scene_001",
                trigger="test",
                summary="Test event.",
                visible_to_player=True,
                metadata={
                    "location_id": "square",
                    "private_payload": {"secret": "hidden"},
                },
            ),
        ]

    def test_player_projection_is_deterministic(
        self, player_builder, sample_events
    ):
        """Same inputs produce same outputs for player projection."""
        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
        }

        result1 = player_builder.build_projection(
            events=sample_events,
            perspective=player_perspective,
            context=context,
        )

        result2 = player_builder.build_projection(
            events=sample_events,
            perspective=player_perspective,
            context=context,
        )

        assert len(result1) == len(result2)
        for p1, p2 in zip(result1, result2):
            assert p1["event_id"] == p2["event_id"]
            assert p1.keys() == p2.keys()

    def test_projection_order_is_preserved(self, player_builder):
        """Projection order matches input event order."""
        events = [
            SceneEvent(
                event_id=f"event_{i:03d}",
                event_type=EventType.SCENE_EVENT,
                turn_index=i,
                timestamp=datetime.now(),
                scene_id=f"scene_{i}",
                trigger="test",
                summary=f"Event {i}.",
                visible_to_player=True,
                metadata={"location_id": "square"},
            )
            for i in range(5)
        ]

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
        }

        projections = player_builder.build_projection(
            events=events,
            perspective=player_perspective,
            context=context,
        )

        event_ids = [p["event_id"] for p in projections]
        assert event_ids == sorted(event_ids)


class TestHiddenDataFieldsExclusion:
    """Test that hidden data fields are properly excluded from projections."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    @pytest.fixture
    def player_builder(self, resolver):
        return PlayerVisibleProjectionBuilder(perception_resolver=resolver)

    @pytest.fixture
    def npc_builder(self, resolver):
        return NPCVisibleProjectionBuilder(perception_resolver=resolver)

    @pytest.fixture
    def narrator_builder(self, resolver, player_builder):
        return NarratorProjectionBuilder(
            perception_resolver=resolver,
            player_projection_builder=player_builder,
        )

    @pytest.fixture
    def event_with_multiple_secrets(self):
        return SceneEvent(
            event_id="multi_secret_event",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="scene_001",
            trigger="test",
            summary="Event with multiple secrets.",
            visible_to_player=True,
            metadata={
                "location_id": "square",
                "private_payload": {
                    "hidden_identity": "demon_lord",
                    "secret_mission": "destroy_world",
                    "private_payload": {"nested_secret": "even_more_hidden"},
                },
            },
        )

    def test_player_excludes_all_private_payload_fields(
        self, player_builder, event_with_multiple_secrets
    ):
        """Player projection excludes all private_payload content."""
        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
        }

        projections = player_builder.build_projection(
            events=[event_with_multiple_secrets],
            perspective=player_perspective,
            context=context,
        )

        proj_str = str(projections)
        assert "hidden_identity" not in proj_str
        assert "secret_mission" not in proj_str
        assert "demon_lord" not in proj_str
        assert "destroy_world" not in proj_str

    def test_npc_excludes_all_private_payload_fields(
        self, npc_builder, event_with_multiple_secrets
    ):
        """NPC projection excludes all private_payload content."""
        npc_perspective = NPCPerspective(
            perspective_id="npc_1",
            owner_id="npc_1",
            npc_id="npc_1",
        )

        context = {
            "npc_location_id": "square",
            "current_turn": 1,
        }

        projections = npc_builder.build_projection(
            events=[event_with_multiple_secrets],
            perspective=npc_perspective,
            context=context,
        )

        proj_str = str(projections)
        assert "hidden_identity" not in proj_str
        assert "secret_mission" not in proj_str

    def test_narrator_excludes_all_private_payload_fields(
        self, narrator_builder, event_with_multiple_secrets
    ):
        """Narrator projection excludes all private_payload content."""
        narrator_perspective = NarratorPerspective(
            perspective_id="narrator",
            owner_id="narrator",
            base_perspective_id="player_1",
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
            "player_perspective": player_perspective,
        }

        projections = narrator_builder.build_projection(
            events=[event_with_multiple_secrets],
            perspective=narrator_perspective,
            context=context,
        )

        proj_str = str(projections)
        assert "hidden_identity" not in proj_str
        assert "secret_mission" not in proj_str
        assert "demon_lord" not in proj_str


class TestEmptyInputHandling:
    """Test handling of empty or edge-case inputs."""

    @pytest.fixture
    def resolver(self):
        return PerceptionResolver()

    @pytest.fixture
    def player_builder(self, resolver):
        return PlayerVisibleProjectionBuilder(perception_resolver=resolver)

    @pytest.fixture
    def npc_builder(self, resolver):
        return NPCVisibleProjectionBuilder(perception_resolver=resolver)

    def test_empty_events_list_returns_empty_projection(
        self, player_builder, npc_builder
    ):
        """Empty events list returns empty projection."""
        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        npc_perspective = NPCPerspective(
            perspective_id="npc_1",
            owner_id="npc_1",
            npc_id="npc_1",
        )

        context = {
            "player_location_id": "square",
            "current_turn": 1,
        }

        player_result = player_builder.build_projection(
            events=[],
            perspective=player_perspective,
            context=context,
        )

        npc_result = npc_builder.build_projection(
            events=[],
            perspective=npc_perspective,
            context={"npc_location_id": "square", "current_turn": 1},
        )

        assert player_result == []
        assert npc_result == []

    def test_none_context_uses_defaults(self, player_builder):
        """None context is handled with defaults."""
        event = SceneEvent(
            event_id="default_context_test",
            event_type=EventType.SCENE_EVENT,
            turn_index=1,
            timestamp=datetime.now(),
            scene_id="scene_001",
            trigger="test",
            summary="Test.",
            visible_to_player=True,
            metadata={"location_id": "unknown"},
        )

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        result = player_builder.build_projection(
            events=[event],
            perspective=player_perspective,
            context=None,
        )

        assert isinstance(result, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
