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
