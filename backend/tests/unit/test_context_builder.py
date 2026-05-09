"""
Unit tests for ContextBuilder.

Tests the context building functionality without requiring external services.
"""

import pytest
from unittest.mock import MagicMock

from llm_rpg.core.context_builder import ContextBuilder
from llm_rpg.models.common import ContextPack, MemoryQuery
from llm_rpg.models.states import CanonicalState


class TestContextBuilderImports:
    """Test that ContextBuilder and related classes can be imported."""
    
    def test_context_builder_import(self):
        """Test ContextBuilder class import."""
        from llm_rpg.core.context_builder import ContextBuilder
        assert ContextBuilder is not None
    
    def test_memory_query_import(self):
        """Test MemoryQuery is accessible from context_builder module."""
        # MemoryQuery should be imported in context_builder.py
        from llm_rpg.core.context_builder import MemoryQuery
        assert MemoryQuery is not None


class TestContextBuilderInitialization:
    """Test ContextBuilder initialization."""
    
    def test_context_builder_init(self, retrieval_system, perspective_service):
        """Test that ContextBuilder initializes correctly."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        assert builder._retrieval is retrieval_system
        assert builder._perspective is perspective_service


class TestContextBuilderBasic:
    """Basic tests for ContextBuilder functionality."""
    
    def test_build_world_context_returns_context_pack(
        self, retrieval_system, perspective_service, sample_game_id
    ):
        """Test that build_world_context returns a ContextPack."""
        builder = ContextBuilder(retrieval_system, perspective_service)
        
        # Create a minimal state
        from llm_rpg.models.states import (
            PlayerState, WorldState, CurrentSceneState, WorldTime
        )
        
        state = CanonicalState(
            game_id=sample_game_id,
            player_state=PlayerState(entity_id="player", name="TestPlayer", location_id="loc_test"),
            world_state=WorldState(
                entity_id="world",
                world_id=sample_game_id,
                current_time=WorldTime(calendar="Test", season="Spring", day=1, period="Morning")
            ),
            current_scene_state=CurrentSceneState(entity_id="scene", scene_id="test_scene", location_id="loc_test"),
            location_states={},
            npc_states={},
            quest_states={},
            faction_states={},
        )
        
        result = builder.build_world_context(
            game_id=sample_game_id,
            turn_id="turn_1",
            state=state,
        )
        
        assert isinstance(result, ContextPack)
        assert result.context_type == "world"
        assert result.context_id == f"world_{sample_game_id}_turn_1"
        assert "world_state" in result.content
        assert "player_state" in result.content


class TestMemoryRetrievalFunctions:
    """Test memory retrieval helper functions."""
    
    def test_retrieve_memories_for_narration_context_no_npc_memories(self, db_session):
        """Test that narration context retrieval excludes NPC subjective memories."""
        from llm_rpg.core.context_builder import _retrieve_memories_for_narration_context
        from llm_rpg.storage.models import MemorySummaryModel
        
        # Create world-level memory
        world_memory = MemorySummaryModel(
            id="sum_world_test",
            session_id="test_session",
            scope_type="world",
            summary_text="World chronicle entry",
            importance_score=0.8,
        )
        db_session.add(world_memory)
        
        # Create NPC subjective memory (should NOT be retrieved)
        npc_memory = MemorySummaryModel(
            id="sum_npc_test",
            session_id="test_session",
            scope_type="npc",
            scope_ref_id="npc_001",
            summary_text="NPC private thought",
            importance_score=0.9,
        )
        db_session.add(npc_memory)
        db_session.commit()
        
        memories = _retrieve_memories_for_narration_context(
            db=db_session,
            session_id="test_session",
            limit=5,
        )
        
        # Should only include world memory, NOT NPC memory
        assert len(memories) == 1
        assert memories[0]["summary_text"] == "World chronicle entry"
    
    def test_retrieve_memories_for_npc_context_includes_npc_memories(self, db_session):
        """Test that NPC context retrieval includes NPC subjective memories."""
        from llm_rpg.core.context_builder import _retrieve_memories_for_npc_context
        from llm_rpg.storage.models import MemorySummaryModel, MemoryFactModel
        
        # Create NPC subjective memory
        npc_memory = MemorySummaryModel(
            id="sum_npc_test2",
            session_id="test_session",
            scope_type="npc",
            scope_ref_id="npc_002",
            summary_text="NPC remembers player's kindness",
            importance_score=0.7,
        )
        db_session.add(npc_memory)
        
        # Create NPC belief fact
        npc_fact = MemoryFactModel(
            id="fact_npc_belief",
            session_id="test_session",
            fact_type="npc_belief",
            subject_ref="npc_002",
            fact_key="player_action_observation",
            fact_value="Player helped me",
            confidence=0.9,
        )
        db_session.add(npc_fact)
        db_session.commit()
        
        memories = _retrieve_memories_for_npc_context(
            db=db_session,
            session_id="test_session",
            npc_id="npc_002",
            limit=5,
        )
        
        # Should include NPC memory and belief
        assert len(memories) >= 1
        memory_texts = [m.get("summary_text", "") for m in memories]
        assert any("NPC remembers" in text for text in memory_texts)

    def test_retrieve_memories_for_npc_context_includes_own_db_backed_memories(self, db_session):
        """NPC context retrieval includes the target NPC's DB-backed subjective memory tables."""
        from llm_rpg.core.context_builder import _retrieve_memories_for_npc_context
        from llm_rpg.storage.models import (
            NPCBeliefModel,
            NPCPrivateMemoryModel,
            NPCSecretModel,
            NPCRelationshipMemoryModel,
        )
        
        db_session.add(NPCBeliefModel(
            id="belief_npc_a",
            session_id="test_session",
            npc_id="npc_a",
            belief_type="observation",
            content="NPC A believes the player carries a jade token",
            confidence=0.91,
            truth_status="unknown",
            source_event_id="evt_belief_a",
            created_turn=2,
            last_updated_turn=3,
        ))
        db_session.add(NPCPrivateMemoryModel(
            id="private_npc_a",
            session_id="test_session",
            npc_id="npc_a",
            memory_type="episodic",
            content="NPC A privately remembers the moonlit bargain",
            source_event_ids_json=["evt_private_a"],
            entities_json=["player", "npc_a"],
            importance=0.95,
            emotional_weight=0.4,
            confidence=0.88,
            current_strength=0.9,
            created_turn=4,
            last_accessed_turn=5,
        ))
        db_session.add(NPCSecretModel(
            id="secret_npc_a",
            session_id="test_session",
            npc_id="npc_a",
            content="NPC A hides the sect key under the altar",
            willingness_to_reveal=0.2,
            reveal_conditions_json=["trust_high"],
            status="hidden",
        ))
        db_session.add(NPCRelationshipMemoryModel(
            id="relationship_npc_a",
            session_id="test_session",
            npc_id="npc_a",
            target_id="player",
            content="NPC A trusts the player after the rescue",
            impact_json={"trust": 2},
            source_event_id="evt_relationship_a",
            created_turn=6,
        ))
        db_session.commit()
        
        memories = _retrieve_memories_for_npc_context(
            db=db_session,
            session_id="test_session",
            npc_id="npc_a",
            limit=5,
        )
        memory_text = str(memories)
        
        assert "jade token" in memory_text
        assert "moonlit bargain" in memory_text
        assert "sect key" in memory_text
        assert "after the rescue" in memory_text
        assert "evt_belief_a" in memory_text
        assert "evt_private_a" in memory_text
        assert "evt_relationship_a" in memory_text

    def test_retrieve_memories_for_npc_context_excludes_other_npc_private_memories(self, db_session):
        """NPC A must not receive NPC B's DB-backed private memories or secrets."""
        from llm_rpg.core.context_builder import _retrieve_memories_for_npc_context
        from llm_rpg.storage.models import NPCPrivateMemoryModel, NPCSecretModel
        
        db_session.add(NPCPrivateMemoryModel(
            id="private_npc_b",
            session_id="test_session",
            npc_id="npc_b",
            memory_type="episodic",
            content="NPC B private blackmail ledger",
            source_event_ids_json=["evt_private_b"],
            importance=1.0,
            emotional_weight=0.8,
            confidence=1.0,
            current_strength=1.0,
            created_turn=7,
            last_accessed_turn=7,
        ))
        db_session.add(NPCSecretModel(
            id="secret_npc_b",
            session_id="test_session",
            npc_id="npc_b",
            content="NPC B secretly serves the rival clan",
            willingness_to_reveal=0.0,
            status="hidden",
        ))
        db_session.commit()
        
        memories = _retrieve_memories_for_npc_context(
            db=db_session,
            session_id="test_session",
            npc_id="npc_a",
            limit=5,
        )
        memory_text = str(memories)
        
        assert "NPC B private blackmail ledger" not in memory_text
        assert "rival clan" not in memory_text

    def test_turn_service_npc_context_includes_only_target_npc_db_memories(self, db_session):
        """Runtime NPC stage context exposes target NPC DB memory without leaking other NPC private data."""
        from llm_rpg.core.turn_service import _build_npc_context
        from llm_rpg.models.states import CanonicalState, CurrentSceneState, PlayerState, WorldState, WorldTime
        from llm_rpg.storage.models import (
            WorldModel,
            SessionModel,
            NPCTemplateModel,
            SessionNPCStateModel,
            NPCPrivateMemoryModel,
        )
        
        db_session.add(WorldModel(id="world_context_test", code="world_context_test", name="World"))
        db_session.add(SessionModel(id="session_context_test", world_id="world_context_test", user_id="user_context_test"))
        db_session.add(NPCTemplateModel(
            id="template_a",
            world_id="world_context_test",
            code="npc_a",
            name="NPC A",
            public_identity="Outer disciple",
            role_type="ally",
        ))
        db_session.add(SessionNPCStateModel(
            id="npc_a",
            session_id="session_context_test",
            npc_template_id="template_a",
            current_location_id="loc_square",
        ))
        db_session.add(NPCPrivateMemoryModel(
            id="private_npc_a_context",
            session_id="session_context_test",
            npc_id="npc_a",
            memory_type="episodic",
            content="NPC A remembers the hidden favor",
            source_event_ids_json=["evt_a_context"],
            importance=0.9,
            emotional_weight=0.2,
            confidence=0.9,
            current_strength=0.9,
            created_turn=3,
            last_accessed_turn=3,
        ))
        db_session.add(NPCPrivateMemoryModel(
            id="private_npc_b_context",
            session_id="session_context_test",
            npc_id="npc_b",
            memory_type="episodic",
            content="NPC B remembers the forbidden betrayal",
            source_event_ids_json=["evt_b_context"],
            importance=1.0,
            emotional_weight=0.9,
            confidence=1.0,
            current_strength=1.0,
            created_turn=4,
            last_accessed_turn=4,
        ))
        db_session.commit()
        
        state = CanonicalState(
            player_state=PlayerState(entity_id="player", location_id="loc_square"),
            world_state=WorldState(
                entity_id="world",
                world_id="world_context_test",
                current_time=WorldTime(calendar="Test", season="Spring", day=1, period="Morning"),
            ),
            current_scene_state=CurrentSceneState(
                entity_id="scene",
                scene_id="scene_context_test",
                location_id="loc_square",
                active_actor_ids=["player", "npc_a"],
            ),
        )
        
        context = _build_npc_context(
            db=db_session,
            session_id="session_context_test",
            npc_id="npc_a",
            npc_template_id="template_a",
            canonical_state=state,
            player_input="观察",
            action_type="observe",
            current_location_id="loc_square",
        )
        context_text = str(context)
        
        assert "npc_db_memories" in context
        assert "hidden favor" in context_text
        assert "evt_a_context" in context_text
        assert "forbidden betrayal" not in context_text
        assert "evt_b_context" not in context_text

    def test_retrieve_memories_for_npc_context_keeps_generic_memory_summaries(self, db_session):
        """Adding DB-backed NPC tables does not remove existing memory_summaries retrieval."""
        from llm_rpg.core.context_builder import _retrieve_memories_for_npc_context
        from llm_rpg.storage.models import MemorySummaryModel, NPCPrivateMemoryModel
        
        db_session.add(MemorySummaryModel(
            id="sum_npc_generic",
            session_id="test_session",
            scope_type="npc",
            scope_ref_id="npc_a",
            summary_text="Generic NPC summary remains available",
            importance_score=0.7,
        ))
        db_session.add(NPCPrivateMemoryModel(
            id="private_npc_a_generic_test",
            session_id="test_session",
            npc_id="npc_a",
            memory_type="episodic",
            content="DB-backed private detail also available",
            importance=0.9,
            emotional_weight=0.1,
            confidence=0.9,
            current_strength=0.9,
            created_turn=8,
            last_accessed_turn=8,
        ))
        db_session.commit()
        
        memories = _retrieve_memories_for_npc_context(
            db=db_session,
            session_id="test_session",
            npc_id="npc_a",
            limit=5,
        )
        memory_text = str(memories)
        
        assert "Generic NPC summary remains available" in memory_text
        assert "DB-backed private detail also available" in memory_text
