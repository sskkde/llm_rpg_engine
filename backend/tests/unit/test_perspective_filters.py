"""
Perspective Filter Leak Tests

Tests to ensure hidden lore facts never leak into inappropriate contexts.

Test Coverage:
- WorldPerspective can see everything (baseline)
- PlayerPerspective only sees known facts/rumors
- NPCPerspective only sees known facts/beliefs/secrets
- NarratorPerspective uses PlayerVisibleProjection only
- Hidden lore with reveal conditions stays hidden until triggered
"""

import pytest
from typing import List

from llm_rpg.models.lore import LoreEntry, LoreCategory, LoreView
from llm_rpg.models.perspectives import (
    WorldPerspective,
    PlayerPerspective,
    NPCPerspective,
    NarratorPerspective,
    VisibilityLevel,
)
from llm_rpg.models.memories import (
    Memory,
    MemoryType,
    NPCProfile,
    NPCBeliefState,
    NPCKnowledgeState,
    NPCMemoryScope,
    NPCGoals,
    NPCSecrets,
    NPCRecentContext,
)
from llm_rpg.models.common import MemoryQuery, ContextPack, RetrievalResult
from llm_rpg.models.states import (
    CanonicalState,
    WorldState,
    PlayerState,
    CurrentSceneState,
    NPCState,
)
from llm_rpg.core.perspective import PerspectiveService
from llm_rpg.core.retrieval import RetrievalSystem
from llm_rpg.core.context_builder import ContextBuilder


class TestPerspectiveFiltering:
    """Test perspective-based content filtering."""

    @pytest.fixture
    def perspective_service(self):
        return PerspectiveService()

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    @pytest.fixture
    def context_builder(self, retrieval_system, perspective_service):
        return ContextBuilder(retrieval_system, perspective_service)

    @pytest.fixture
    def hidden_lore(self):
        """Create hidden lore that should not be visible to players/NPCs."""
        return LoreEntry(
            lore_id="secret_conspiracy",
            title="The Elder Conspiracy",
            category=LoreCategory.HISTORY,
            canonical_content="The elders have been secretly controlling the sect for 500 years.",
            public_content=None,
            rumor_versions=["Some say the elders have secrets..."],
            known_by=["world", "elder_1", "elder_2"],
            hidden_from_player_until=["player_discovers_temple"],
            reveal_conditions=["player_enters_secret_chamber"],
            tags=["secret", "conspiracy", "elders"],
        )

    @pytest.fixture
    def public_lore(self):
        """Create public lore visible to everyone."""
        return LoreEntry(
            lore_id="public_history",
            title="History of the Sect",
            category=LoreCategory.HISTORY,
            canonical_content="The sect was founded 1000 years ago.",
            public_content="The sect has a long history.",
            rumor_versions=[],
            known_by=["world", "player", "npc_1"],
            tags=["history", "public"],
        )

    def test_world_perspective_sees_everything(self, perspective_service, hidden_lore):
        """WorldPerspective should see hidden lore."""
        world_perspective = perspective_service.build_world_perspective()

        lore_views = perspective_service.filter_lore_for_perspective(
            [hidden_lore], world_perspective
        )

        assert len(lore_views) == 1
        assert lore_views[0].lore_id == "secret_conspiracy"
        assert lore_views[0].visibility_level == "full"
        assert "secretly controlling" in lore_views[0].content

    def test_player_perspective_cannot_see_hidden_lore(
        self, perspective_service, hidden_lore
    ):
        """Player without knowledge should not see hidden lore."""
        player_perspective = perspective_service.build_player_perspective(
            perspective_id="player_1",
            player_id="player_1",
            known_facts=["public_history"],
            known_rumors=[],
        )

        lore_views = perspective_service.filter_lore_for_perspective(
            [hidden_lore], player_perspective
        )

        assert len(lore_views) == 0
        assert "secretly controlling" not in str(lore_views)

    def test_player_perspective_sees_known_facts(
        self, perspective_service, public_lore
    ):
        """Player should see facts they know."""
        player_perspective = perspective_service.build_player_perspective(
            perspective_id="player_1",
            player_id="player_1",
            known_facts=["public_history"],
            known_rumors=[],
        )

        lore_views = perspective_service.filter_lore_for_perspective(
            [public_lore], player_perspective
        )

        assert len(lore_views) == 1
        assert lore_views[0].lore_id == "public_history"
        assert lore_views[0].visibility_level == "full"

    def test_player_perspective_sees_rumors_as_rumors(
        self, perspective_service, hidden_lore
    ):
        """Player should see rumors with reduced confidence."""
        player_perspective = perspective_service.build_player_perspective(
            perspective_id="player_1",
            player_id="player_1",
            known_facts=[],
            known_rumors=["secret_conspiracy"],
        )

        lore_views = perspective_service.filter_lore_for_perspective(
            [hidden_lore], player_perspective
        )

        assert len(lore_views) == 1
        assert lore_views[0].is_rumor is True
        assert lore_views[0].confidence == 0.5

    def test_npc_perspective_cannot_see_forbidden_knowledge(
        self, perspective_service, hidden_lore
    ):
        """NPC should not see forbidden knowledge."""
        npc_perspective = perspective_service.build_npc_perspective(
            perspective_id="npc_1",
            npc_id="npc_1",
            known_facts=["public_history"],
            believed_rumors=[],
            forbidden_knowledge=["secret_conspiracy"],
        )

        lore_views = perspective_service.filter_lore_for_perspective(
            [hidden_lore], npc_perspective
        )

        assert len(lore_views) == 0

    def test_npc_perspective_sees_known_facts(
        self, perspective_service, hidden_lore
    ):
        """NPC should see facts they know."""
        npc_perspective = perspective_service.build_npc_perspective(
            perspective_id="elder_1",
            npc_id="elder_1",
            known_facts=["secret_conspiracy"],
            believed_rumors=[],
        )

        lore_views = perspective_service.filter_lore_for_perspective(
            [hidden_lore], npc_perspective
        )

        assert len(lore_views) == 1
        assert lore_views[0].visibility_level == "full"
        assert "secretly controlling" in lore_views[0].content

    def test_npc_perspective_sees_known_facts(self, perspective_service, hidden_lore):
        """NPC should see known facts (secrets are treated as known facts when filtering lore)."""
        npc_perspective = perspective_service.build_npc_perspective(
            perspective_id="npc_1",
            npc_id="npc_1",
            known_facts=["secret_conspiracy"],  # Secrets work through known_facts for lore
            believed_rumors=[],
        )

        lore_views = perspective_service.filter_lore_for_perspective(
            [hidden_lore], npc_perspective
        )

        assert len(lore_views) == 1
        assert lore_views[0].visibility_level == "full"

    def test_npc_perspective_sees_believed_rumors(
        self, perspective_service, hidden_lore
    ):
        """NPC should see rumors they believe."""
        npc_perspective = perspective_service.build_npc_perspective(
            perspective_id="npc_1",
            npc_id="npc_1",
            known_facts=[],
            believed_rumors=["secret_conspiracy"],
        )

        lore_views = perspective_service.filter_lore_for_perspective(
            [hidden_lore], npc_perspective
        )

        assert len(lore_views) == 1
        assert lore_views[0].is_rumor is True


class TestRetrievalPerspectiveFiltering:
    """Test perspective filtering in retrieval system."""

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    @pytest.fixture
    def secret_memory(self):
        return Memory(
            memory_id="mem_secret_1",
            owner_type="npc",
            owner_id="elder_1",
            memory_type=MemoryType.SECRET,
            content="The conspiracy meeting at midnight",
            entities=["elder_1", "secret_chamber"],
            importance=0.9,
            created_turn=1,
            last_accessed_turn=1,
        )

    def test_retrieval_filters_hidden_memories_for_player(
        self, retrieval_system, secret_memory
    ):
        """Player perspective should not retrieve secret memories."""
        retrieval_system.index_memory(secret_memory)

        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
            known_facts=[],
            known_rumors=[],
        )

        results = retrieval_system.hybrid_retrieve(
            query=MemoryQuery(
                query_text="conspiracy",
                limit=10,
            ),
            perspective=player_perspective,
        )

        assert len(results) == 0
        assert "conspiracy meeting" not in str(results)

    def test_retrieval_shows_memories_to_owner(self, retrieval_system, secret_memory):
        """NPC owner should see their own memories."""
        retrieval_system.index_memory(secret_memory)

        npc_perspective = NPCPerspective(
            perspective_id="elder_1",
            owner_id="elder_1",
            npc_id="elder_1",
            known_facts=["mem_secret_1"],
            secrets=["mem_secret_1"],
        )

        results = retrieval_system.hybrid_retrieve(
            query=MemoryQuery(
                owner_id="elder_1",
                owner_type="npc",
                limit=10,
            ),
            perspective=npc_perspective,
        )

        assert len(results) == 1
        assert results[0].memory_id == "mem_secret_1"

    def test_world_perspective_sees_all_memories(
        self, retrieval_system, secret_memory
    ):
        """World perspective should see all memories."""
        retrieval_system.index_memory(secret_memory)

        world_perspective = WorldPerspective(
            perspective_id="world",
            owner_id="world",
        )

        results = retrieval_system.hybrid_retrieve(
            query=MemoryQuery(limit=10),
            perspective=world_perspective,
        )

        assert len(results) == 1
        assert results[0].memory_id == "mem_secret_1"


class TestContextBuilderPerspectiveLeak:
    """Test ContextBuilder does not leak hidden information."""

    @pytest.fixture
    def perspective_service(self):
        return PerspectiveService()

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    @pytest.fixture
    def context_builder(self, retrieval_system, perspective_service):
        return ContextBuilder(retrieval_system, perspective_service)

    @pytest.fixture
    def hidden_lore(self):
        return LoreEntry(
            lore_id="hidden_truth",
            title="The Hidden Truth",
            category=LoreCategory.MAIN_PLOT,
            canonical_content="The master is actually a demon in disguise.",
            public_content=None,
            rumor_versions=["Some suspect the master is not what he seems..."],
            known_by=["world", "demon_lord"],
            hidden_from_player_until=["player_reaches_core"],
            tags=["secret", "demon", "master"],
        )

    @pytest.fixture
    def mock_state(self):
        """Create minimal mock state for context building."""
        from llm_rpg.models.events import WorldTime
        return CanonicalState(
            world_state=WorldState(
                entity_id="world_1",
                world_id="test_world",
                current_time=WorldTime(calendar="standard", season="spring", day=1, hour=12, period="morning"),
            ),
            player_state=PlayerState(
                entity_id="player_1",
                name="Test Player",
                location_id="square",
            ),
            current_scene_state=CurrentSceneState(
                entity_id="square",
                scene_id="square",
                location_id="square",
                active_actor_ids=["player_1"],
            ),
            location_states={},
            npc_states={},
            quest_states={},
            faction_states={},
        )

    @pytest.fixture
    def mock_npc_scope(self):
        """Create minimal NPC scope for testing."""
        return NPCMemoryScope(
            npc_id="test_npc",
            profile=NPCProfile(
                npc_id="test_npc",
                name="Test NPC",
            ),
            belief_state=NPCBeliefState(npc_id="test_npc"),
            recent_context=NPCRecentContext(npc_id="test_npc"),
            secrets=NPCSecrets(npc_id="test_npc"),
            knowledge_state=NPCKnowledgeState(npc_id="test_npc"),
            goals=NPCGoals(npc_id="test_npc"),
        )

    def test_npc_context_excludes_hidden_lore(
        self, context_builder, mock_state, mock_npc_scope, hidden_lore
    ):
        """NPC context should never include hidden lore facts."""
        # NPC doesn't know the hidden truth
        context = context_builder.build_npc_context(
            npc_id="test_npc",
            game_id="game_1",
            turn_id="turn_1",
            state=mock_state,
            npc_scope=mock_npc_scope,
            relevant_lore=[hidden_lore],
        )

        context_str = str(context.content)
        assert "demon in disguise" not in context_str
        assert "Hidden Truth" not in context_str

    def test_npc_context_includes_known_facts(
        self, context_builder, mock_state, hidden_lore
    ):
        """NPC context should include lore the NPC knows."""
        npc_scope = NPCMemoryScope(
            npc_id="informed_npc",
            profile=NPCProfile(
                npc_id="informed_npc",
                name="Informed NPC",
            ),
            belief_state=NPCBeliefState(npc_id="informed_npc"),
            recent_context=NPCRecentContext(npc_id="informed_npc"),
            secrets=NPCSecrets(npc_id="informed_npc"),
            knowledge_state=NPCKnowledgeState(
                npc_id="informed_npc",
                known_facts=["hidden_truth"],
            ),
            goals=NPCGoals(npc_id="informed_npc"),
        )

        context = context_builder.build_npc_context(
            npc_id="informed_npc",
            game_id="game_1",
            turn_id="turn_1",
            state=mock_state,
            npc_scope=npc_scope,
            relevant_lore=[hidden_lore],
        )

        context_str = str(context.content)
        assert "demon in disguise" in context_str

    def test_narrator_context_uses_player_visible_projection(
        self, context_builder, mock_state, hidden_lore
    ):
        """Narrator context should use PlayerVisibleProjection (not see hidden lore)."""
        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
            known_facts=[],
            known_rumors=[],
        )

        narrator_perspective = NarratorPerspective(
            perspective_id="narrator",
            owner_id="narrator",
            base_perspective_id="player_1",
            forbidden_info=["hidden_truth"],
        )

        context = context_builder.build_narration_context(
            game_id="game_1",
            turn_id="turn_1",
            state=mock_state,
            player_perspective=player_perspective,
            narrator_perspective=narrator_perspective,
        )

        context_str = str(context.content)
        # The actual secret content should NOT be in the context
        assert "demon in disguise" not in context_str
        # The lore_context should be empty (no lore views since player knows nothing)
        assert context.content.get("lore_context") == []

    def test_narrator_context_no_raw_hidden_lore(
        self, context_builder, mock_state, hidden_lore
    ):
        """
        CRITICAL: Narrator context should NEVER contain raw hidden lore.

        This tests the requirement that hidden lore known only to WorldPerspective
        never appears in narrator contexts.
        """
        player_perspective = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
            known_facts=[],  # Player knows nothing
            known_rumors=[],
        )

        narrator_perspective = NarratorPerspective(
            perspective_id="narrator",
            owner_id="narrator",
            base_perspective_id="player_1",
        )

        context = context_builder.build_narration_context(
            game_id="game_1",
            turn_id="turn_1",
            state=mock_state,
            player_perspective=player_perspective,
            narrator_perspective=narrator_perspective,
        )

        context_str = str(context.content)
        assert "master is actually a demon" not in context_str
        assert "demon in disguise" not in context_str
        assert "hidden_truth" not in context_str


class TestStateConsistencyFilter:
    """Test that old summaries don't override canonical state."""

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    def test_outdated_memories_marked(self, retrieval_system):
        """Old memories should be marked as potentially outdated."""
        old_memory = Memory(
            memory_id="mem_old",
            owner_type="npc",
            owner_id="npc_1",
            memory_type=MemoryType.EPISODIC,
            content="NPC was at location A",
            importance=0.4,
            created_turn=1,
            last_accessed_turn=1,
        )

        retrieval_system.index_memory(old_memory)

        results = retrieval_system.apply_state_consistency_filter(
            [
                RetrievalResult(
                    memory_id="mem_old",
                    content="NPC was at location A",
                    score=0.8,
                    source="memory",
                    metadata={"created_turn": 1, "importance": 0.4},
                )
            ],
            current_state={"current_turn": 10},
        )

        assert len(results) == 1
        assert results[0].metadata.get("potentially_outdated") is True
        assert results[0].score < 0.8

    def test_important_memories_not_penalized(self, retrieval_system):
        """Important memories should not be marked as outdated even if old."""
        results = retrieval_system.apply_state_consistency_filter(
            [
                RetrievalResult(
                    memory_id="mem_important",
                    content="Critical plot event",
                    score=0.9,
                    source="memory",
                    metadata={"created_turn": 1, "importance": 0.9},
                )
            ],
            current_state={"current_turn": 10},
        )

        assert len(results) == 1
        assert results[0].metadata.get("potentially_outdated") is None


class TestEmbeddingsFallback:
    """Test pgvector fallback with stored embeddings."""

    @pytest.fixture
    def retrieval_system(self):
        return RetrievalSystem()

    def test_embedding_storage_fallback(self, retrieval_system):
        """Retrieval system can store embeddings as fallback for pgvector."""
        embedding = [0.1, 0.2, 0.3, 0.4, 0.5]

        retrieval_system.store_embedding("test_id", embedding)
        retrieved = retrieval_system.get_embedding("test_id")

        assert retrieved == embedding

    def test_cosine_similarity_computation(self, retrieval_system):
        """Cosine similarity is computed correctly."""
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [1.0, 0.0, 0.0]
        vec3 = [0.0, 1.0, 0.0]

        # Same vectors = 1.0
        sim1 = retrieval_system._compute_cosine_similarity(vec1, vec2)
        assert sim1 == 1.0

        # Orthogonal vectors = 0.0
        sim2 = retrieval_system._compute_cosine_similarity(vec1, vec3)
        assert sim2 == 0.0

    def test_embedding_based_scoring(self, retrieval_system):
        """Memories with similar embeddings get higher scores."""
        memory = Memory(
            memory_id="mem_1",
            owner_type="npc",
            owner_id="npc_1",
            memory_type=MemoryType.EPISODIC,
            content="Test memory",
            importance=0.5,
            created_turn=1,
            last_accessed_turn=1,
        )

        retrieval_system.index_memory(memory, embedding=[1.0, 0.0, 0.0])
        retrieval_system.store_embedding("query:test query", [1.0, 0.0, 0.0])

        results = retrieval_system.retrieve_memories(
            MemoryQuery(
                query_text="test query",
                limit=10,
            )
        )

        assert len(results) == 1
        assert results[0].memory_id == "mem_1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
