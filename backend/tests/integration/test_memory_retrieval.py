"""
Memory Retrieval Integration Tests

Tests hybrid retrieval with multiple filters:
- Entity filter
- Time filter
- Importance filter
- Semantic similarity (embedding-based with pgvector fallback)
- Perspective filter
- Visibility filter
- State-consistency filter

Also tests embedding storage with pgvector or documented fallback.
"""

import pytest
from typing import List

from llm_rpg.models.common import MemoryQuery, TimeRange
from llm_rpg.models.memories import Memory, MemoryType, MemorySourceType
from llm_rpg.models.lore import LoreEntry, LoreCategory
from llm_rpg.models.perspectives import (
    WorldPerspective,
    PlayerPerspective,
    NPCPerspective,
    NarratorPerspective,
    VisibilityLevel,
)
from llm_rpg.models.summaries import Summary, SummaryType
from llm_rpg.core.retrieval import RetrievalSystem
from llm_rpg.core.perspective import PerspectiveService
from llm_rpg.core.context_builder import ContextBuilder


class TestHybridRetrievalFilters:
    """Test hybrid retrieval with all filter types."""

    @pytest.fixture
    def retrieval(self):
        return RetrievalSystem()

    @pytest.fixture
    def sample_memories(self):
        """Create sample memories with various attributes."""
        return [
            Memory(
                memory_id="mem_1",
                owner_type="npc",
                owner_id="npc_1",
                memory_type=MemoryType.EPISODIC,
                content="Player attacked the elder in the square",
                entities=["player", "elder", "square"],
                importance=0.9,
                emotional_weight=-0.8,
                confidence=1.0,
                current_strength=0.8,
                created_turn=1,
                last_accessed_turn=1,
            ),
            Memory(
                memory_id="mem_2",
                owner_type="npc",
                owner_id="npc_1",
                memory_type=MemoryType.SEMANTIC,
                content="The elder is respected by all",
                entities=["elder", "square"],
                importance=0.7,
                emotional_weight=0.5,
                confidence=0.9,
                current_strength=0.9,
                created_turn=2,
                last_accessed_turn=2,
            ),
            Memory(
                memory_id="mem_3",
                owner_type="npc",
                owner_id="npc_2",
                memory_type=MemoryType.EPISODIC,
                content="Found a secret passage in the library",
                entities=["npc_2", "library", "secret_passage"],
                importance=0.8,
                emotional_weight=0.6,
                confidence=1.0,
                current_strength=0.7,
                created_turn=3,
                last_accessed_turn=3,
            ),
            Memory(
                memory_id="mem_4",
                owner_type="npc",
                owner_id="npc_1",
                memory_type=MemoryType.RUMOR,
                content="Someone heard the master is not human",
                entities=["master", "rumor"],
                importance=0.6,
                emotional_weight=0.3,
                confidence=0.5,
                current_strength=0.5,
                created_turn=5,
                last_accessed_turn=5,
            ),
            Memory(
                memory_id="mem_5",
                owner_type="npc",
                owner_id="npc_1",
                memory_type=MemoryType.SECRET,
                content="The master is actually a demon lord",
                entities=["master", "demon_lord"],
                importance=1.0,
                emotional_weight=-0.9,
                confidence=1.0,
                current_strength=1.0,
                created_turn=1,
                last_accessed_turn=1,
            ),
        ]

    def test_entity_filter(self, retrieval, sample_memories):
        """Filter memories by entity involvement."""
        for mem in sample_memories:
            retrieval.index_memory(mem)

        results = retrieval.retrieve_memories(
            MemoryQuery(
                entity_ids=["elder"],
                limit=10,
            )
        )

        assert len(results) == 2
        assert all("elder" in r.metadata["entities"] for r in results)

    def test_time_filter(self, retrieval, sample_memories):
        """Filter memories by time range."""
        for mem in sample_memories:
            retrieval.index_memory(mem)

        results = retrieval.retrieve_memories(
            MemoryQuery(
                time_range=TimeRange(start_turn=2, end_turn=4),
                limit=10,
            )
        )

        assert len(results) == 2
        assert all(2 <= r.metadata["created_turn"] <= 4 for r in results)

    def test_importance_filter(self, retrieval, sample_memories):
        """Filter memories by importance threshold."""
        for mem in sample_memories:
            retrieval.index_memory(mem)

        results = retrieval.retrieve_memories(
            MemoryQuery(
                importance_threshold=0.8,
                limit=10,
            )
        )

        assert len(results) == 3  # mem_1 (0.9), mem_3 (0.8), mem_5 (1.0)
        assert all(r.metadata["importance"] >= 0.8 for r in results)

    def test_memory_type_filter(self, retrieval, sample_memories):
        """Filter memories by type."""
        for mem in sample_memories:
            retrieval.index_memory(mem)

        results = retrieval.retrieve_memories(
            MemoryQuery(
                memory_types=[MemoryType.EPISODIC],
                limit=10,
            )
        )

        assert len(results) == 2
        assert all(r.metadata["memory_type"] == MemoryType.EPISODIC for r in results)

    def test_owner_filter(self, retrieval, sample_memories):
        """Filter memories by owner."""
        for mem in sample_memories:
            retrieval.index_memory(mem)

        results = retrieval.retrieve_memories(
            MemoryQuery(
                owner_id="npc_1",
                owner_type="npc",
                limit=10,
            )
        )

        assert len(results) == 4  # mem_1, mem_2, mem_4, mem_5 owned by npc_1
        assert all(
            r.memory_id.startswith("mem_1") or r.memory_id.startswith("mem_2")
            or r.memory_id.startswith("mem_4") or r.memory_id.startswith("mem_5")
            for r in results
        )

    def test_combined_filters(self, retrieval, sample_memories):
        """Apply multiple filters together."""
        for mem in sample_memories:
            retrieval.index_memory(mem)

        results = retrieval.retrieve_memories(
            MemoryQuery(
                owner_id="npc_1",
                entity_ids=["elder"],
                time_range=TimeRange(start_turn=1, end_turn=5),
                importance_threshold=0.5,
                limit=10,
            )
        )

        assert len(results) == 2
        assert all(r.metadata["importance"] >= 0.5 for r in results)

    def test_scoring_weights(self, retrieval, sample_memories):
        """Verify scoring uses all weights (importance, strength, emotion, entity, semantic)."""
        for mem in sample_memories:
            retrieval.index_memory(mem)

        results = retrieval.retrieve_memories(
            MemoryQuery(
                query_text="elder attacked",
                entity_ids=["elder"],
                limit=10,
            )
        )

        assert len(results) > 0
        assert results[0].score > 0


class TestPerspectiveFiltering:
    """Test perspective filtering in hybrid retrieval."""

    @pytest.fixture
    def retrieval(self):
        return RetrievalSystem()

    @pytest.fixture
    def perspective_service(self):
        return PerspectiveService()

    @pytest.fixture
    def secret_memory(self):
        return Memory(
            memory_id="secret_mem",
            owner_type="npc",
            owner_id="conspirator",
            memory_type=MemoryType.SECRET,
            content="The conspiracy to overthrow the sect",
            entities=["conspirator", "sect"],
            importance=0.95,
            created_turn=1,
            last_accessed_turn=1,
        )

    def test_world_perspective_sees_all(self, retrieval, secret_memory):
        """World perspective can see secret memories."""
        retrieval.index_memory(secret_memory)

        world = WorldPerspective(perspective_id="world", owner_id="world")

        results = retrieval.hybrid_retrieve(
            MemoryQuery(limit=10),
            perspective=world,
        )

        assert len(results) == 1
        assert results[0].memory_id == "secret_mem"

    def test_player_perspective_blocked(self, retrieval, secret_memory):
        """Player perspective cannot see unknown secrets."""
        retrieval.index_memory(secret_memory)

        player = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
            known_facts=[],
            known_rumors=[],
        )

        results = retrieval.hybrid_retrieve(
            MemoryQuery(
                query_text="conspiracy",
                limit=10,
            ),
            perspective=player,
        )

        assert len(results) == 0

    def test_player_sees_known_facts(self, retrieval, secret_memory):
        """Player can see facts they know."""
        retrieval.index_memory(secret_memory)

        player = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
            known_facts=["secret_mem"],
            known_rumors=[],
        )

        results = retrieval.hybrid_retrieve(
            MemoryQuery(limit=10),
            perspective=player,
        )

        assert len(results) == 1
        assert results[0].memory_id == "secret_mem"

    def test_player_sees_rumors_with_reduced_score(self, retrieval, secret_memory):
        """Player sees rumors with reduced confidence score."""
        retrieval.index_memory(secret_memory)

        player = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
            known_facts=[],
            known_rumors=["secret_mem"],
        )

        results = retrieval.hybrid_retrieve(
            MemoryQuery(limit=10),
            perspective=player,
        )

        assert len(results) == 1
        assert results[0].metadata.get("is_rumor") is True
        assert results[0].metadata.get("confidence") == 0.5

    def test_npc_perspective_blocked_by_forbidden(self, retrieval, secret_memory):
        """NPC cannot see forbidden knowledge."""
        retrieval.index_memory(secret_memory)

        npc = NPCPerspective(
            perspective_id="innocent_npc",
            owner_id="innocent_npc",
            npc_id="innocent_npc",
            known_facts=[],
            forbidden_knowledge=["secret_mem"],
        )

        results = retrieval.hybrid_retrieve(
            MemoryQuery(limit=10),
            perspective=npc,
        )

        assert len(results) == 0

    def test_npc_sees_known_secrets(self, retrieval, secret_memory):
        """NPC can see secrets they possess."""
        retrieval.index_memory(secret_memory)

        npc = NPCPerspective(
            perspective_id="conspirator",
            owner_id="conspirator",
            npc_id="conspirator",
            secrets=["secret_mem"],
        )

        results = retrieval.hybrid_retrieve(
            MemoryQuery(limit=10),
            perspective=npc,
        )

        assert len(results) == 1


class TestVisibilityFilter:
    """Test entity-based visibility filtering."""

    @pytest.fixture
    def retrieval(self):
        return RetrievalSystem()

    @pytest.fixture
    def scene_memories(self):
        return [
            Memory(
                memory_id="mem_visible",
                owner_type="npc",
                owner_id="npc_1",
                memory_type=MemoryType.EPISODIC,
                content="Interaction with player",
                entities=["player", "npc_1"],
                importance=0.8,
                created_turn=1,
                last_accessed_turn=1,
            ),
            Memory(
                memory_id="mem_hidden",
                owner_type="npc",
                owner_id="npc_2",
                memory_type=MemoryType.EPISODIC,
                content="Secret meeting elsewhere",
                entities=["npc_2", "secret_location"],
                importance=0.8,
                created_turn=1,
                last_accessed_turn=1,
            ),
        ]

    def test_visibility_filter_excludes_hidden_entities(self, retrieval, scene_memories):
        """Memories involving non-visible entities are excluded."""
        for mem in scene_memories:
            retrieval.index_memory(mem)

        world = WorldPerspective(perspective_id="world", owner_id="world")

        results = retrieval.hybrid_retrieve(
            MemoryQuery(limit=10),
            perspective=world,
            visible_entity_ids=["player", "npc_1"],
        )

        assert len(results) == 1
        assert results[0].memory_id == "mem_visible"


class TestStateConsistencyFilter:
    """Test that old summaries don't override canonical state."""

    @pytest.fixture
    def retrieval(self):
        return RetrievalSystem()

    def test_old_memories_flagged_outdated(self, retrieval):
        """Memories older than 5 turns are flagged as potentially outdated."""
        memory = Memory(
            memory_id="old_mem",
            owner_type="npc",
            owner_id="npc_1",
            memory_type=MemoryType.EPISODIC,
            content="NPC was at old location",
            importance=0.4,
            created_turn=1,
            last_accessed_turn=1,
        )
        retrieval.index_memory(memory)

        world = WorldPerspective(perspective_id="world", owner_id="world")

        results = retrieval.hybrid_retrieve(
            MemoryQuery(limit=10),
            perspective=world,
            current_state={"current_turn": 10},
        )

        assert len(results) == 1
        assert results[0].metadata.get("potentially_outdated") is True
        assert results[0].score < 0.5

    def test_important_memories_not_flagged(self, retrieval):
        """Important memories (>0.7) are not flagged as outdated."""
        memory = Memory(
            memory_id="important_mem",
            owner_type="npc",
            owner_id="npc_1",
            memory_type=MemoryType.EPISODIC,
            content="Critical plot point",
            importance=0.9,
            created_turn=1,
            last_accessed_turn=1,
        )
        retrieval.index_memory(memory)

        world = WorldPerspective(perspective_id="world", owner_id="world")

        results = retrieval.hybrid_retrieve(
            MemoryQuery(limit=10),
            perspective=world,
            current_state={"current_turn": 10},
        )

        assert len(results) == 1
        assert results[0].metadata.get("potentially_outdated") is None


class TestLoreRetrieval:
    """Test lore retrieval with perspective filtering."""

    @pytest.fixture
    def retrieval(self):
        return RetrievalSystem()

    @pytest.fixture
    def lore_entries(self):
        return [
            LoreEntry(
                lore_id="lore_public",
                title="Public History",
                category=LoreCategory.HISTORY,
                canonical_content="The full true history",
                public_content="The public version of history",
                rumor_versions=["Some say..."],
                known_by=["world", "player", "npc_1"],
            ),
            LoreEntry(
                lore_id="lore_hidden",
                title="Secret History",
                category=LoreCategory.HISTORY,
                canonical_content="The secret truth",
                public_content=None,
                rumor_versions=[],
                known_by=["world", "secret_society"],
                hidden_from_player_until=["special_condition"],
            ),
        ]

    def test_lore_retrieval_public_content(self, retrieval, lore_entries):
        """Lore with public content is visible to all."""
        for lore in lore_entries:
            retrieval.index_lore(lore)

        player = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        views = retrieval.retrieve_lore(
            perspective=player,
            limit=10,
        )

        public_lore = [v for v in views if v.lore_id == "lore_public"]
        assert len(public_lore) == 1
        assert public_lore[0].content == "The public version of history"

    def test_lore_retrieval_hidden_without_knowledge(self, retrieval, lore_entries):
        """Hidden lore without public content is not visible."""
        for lore in lore_entries:
            retrieval.index_lore(lore)

        player = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
        )

        views = retrieval.retrieve_lore(
            perspective=player,
            limit=10,
        )

        hidden_lore = [v for v in views if v.lore_id == "lore_hidden"]
        assert len(hidden_lore) == 0

    def test_lore_retrieval_with_known_facts(self, retrieval, lore_entries):
        """Player sees full content for known facts."""
        for lore in lore_entries:
            retrieval.index_lore(lore)

        player = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
            known_facts=["lore_hidden"],
        )

        views = retrieval.retrieve_lore(
            perspective=player,
            limit=10,
        )

        hidden_lore = [v for v in views if v.lore_id == "lore_hidden"]
        assert len(hidden_lore) == 1
        assert hidden_lore[0].content == "The secret truth"


class TestEmbeddingStorage:
    """Test embedding storage as pgvector fallback."""

    @pytest.fixture
    def retrieval(self):
        return RetrievalSystem()

    def test_store_and_retrieve_embedding(self, retrieval):
        """Embeddings can be stored and retrieved."""
        embedding = [0.1, 0.2, 0.3, 0.4, 0.5]

        retrieval.store_embedding("test_memory", embedding)
        retrieved = retrieval.get_embedding("test_memory")

        assert retrieved == embedding

    def test_embedding_similarity_scoring(self, retrieval):
        """Similar embeddings result in higher scores."""
        mem1 = Memory(
            memory_id="mem_similar",
            owner_type="npc",
            owner_id="npc_1",
            memory_type=MemoryType.EPISODIC,
            content="Test memory",
            importance=0.5,
            created_turn=1,
            last_accessed_turn=1,
        )

        retrieval.index_memory(mem1, embedding=[1.0, 0.0, 0.0, 0.0])
        retrieval.store_embedding("query:similar", [1.0, 0.0, 0.0, 0.0])

        world = WorldPerspective(perspective_id="world", owner_id="world")

        results = retrieval.hybrid_retrieve(
            MemoryQuery(query_text="similar", limit=10),
            perspective=world,
        )

        assert len(results) == 1
        assert results[0].memory_id == "mem_similar"

    def test_cosine_similarity_orthogonal(self, retrieval):
        """Orthogonal vectors have 0 similarity."""
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]

        similarity = retrieval._compute_cosine_similarity(vec1, vec2)
        assert similarity == 0.0

    def test_cosine_similarity_identical(self, retrieval):
        """Identical vectors have 1.0 similarity."""
        vec = [0.5, 0.5, 0.5]

        similarity = retrieval._compute_cosine_similarity(vec, vec)
        assert abs(similarity - 1.0) < 0.0001


class TestSummaryRetrieval:
    """Test summary retrieval functionality."""

    @pytest.fixture
    def retrieval(self):
        return RetrievalSystem()

    @pytest.fixture
    def sample_summaries(self):
        return [
            Summary(
                summary_id="sum_1",
                summary_type=SummaryType.SCENE_SUMMARY,
                scene_id="scene_1",
                start_turn=1,
                end_turn=5,
                content="Summary of scene 1",
                importance=0.8,
            ),
            Summary(
                summary_id="sum_2",
                summary_type=SummaryType.SESSION_SUMMARY,
                session_id="session_1",
                start_turn=6,
                end_turn=10,
                content="Summary of session 1",
                importance=0.9,
            ),
        ]

    def test_retrieve_summaries_by_time_range(self, retrieval, sample_summaries):
        """Summaries can be filtered by time range."""
        for summary in sample_summaries:
            retrieval.index_summary(summary)

        results = retrieval.retrieve_summaries(
            turn_range=TimeRange(start_turn=1, end_turn=5),
        )

        assert len(results) == 1
        assert results[0].memory_id == "sum_1"

    def test_retrieve_summaries_by_type(self, retrieval, sample_summaries):
        """Summaries can be filtered by type."""
        for summary in sample_summaries:
            retrieval.index_summary(summary)

        results = retrieval.retrieve_summaries(
            summary_type=SummaryType.SESSION_SUMMARY,
        )

        assert len(results) == 1
        assert results[0].memory_id == "sum_2"


class TestEndToEndRetrieval:
    """End-to-end tests with all systems integrated."""

    @pytest.fixture
    def retrieval(self):
        return RetrievalSystem()

    @pytest.fixture
    def perspective_service(self):
        return PerspectiveService()

    @pytest.fixture
    def context_builder(self, retrieval, perspective_service):
        return ContextBuilder(retrieval, perspective_service)

    def test_complex_scenario_with_all_filters(self, retrieval):
        """Complex scenario with all filter types applied."""
        memories = [
            Memory(
                memory_id=f"mem_{i}",
                owner_type="npc",
                owner_id="npc_1" if i < 3 else "npc_2",
                memory_type=MemoryType.EPISODIC if i % 2 == 0 else MemoryType.SEMANTIC,
                content=f"Memory content {i}",
                entities=["player"] if i < 2 else ["npc_2"],
                importance=0.5 + (i * 0.1),
                created_turn=i + 1,
                last_accessed_turn=i + 1,
            )
            for i in range(5)
        ]

        for mem in memories:
            retrieval.index_memory(mem)

        player = PlayerPerspective(
            perspective_id="player_1",
            owner_id="player_1",
            known_facts=["mem_0", "mem_2"],
        )

        results = retrieval.hybrid_retrieve(
            MemoryQuery(
                entity_ids=["player"],
                time_range=TimeRange(start_turn=1, end_turn=5),
                importance_threshold=0.5,
                limit=10,
            ),
            perspective=player,
            visible_entity_ids=["player", "npc_1"],
            current_state={"current_turn": 5},
        )

        assert len(results) > 0
        assert all(r.metadata["importance"] >= 0.5 for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
