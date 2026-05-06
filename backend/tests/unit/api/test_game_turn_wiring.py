"""
Unit tests for turn_factory module.

Tests verify:
- Single shared ProposalPipeline instance when LLMService is provided
- All engines receive the same pipeline instance
- Construction without LLMService uses None for all pipelines
- SceneEngine is always constructed
"""

import pytest
from unittest.mock import MagicMock, patch

from llm_rpg.api.turn_factory import build_turn_orchestrator
from llm_rpg.llm.service import LLMService, MockLLMProvider
from llm_rpg.llm.proposal_pipeline import ProposalPipeline


class TestTurnFactoryWithPipeline:
    """Tests for factory when LLMService is provided."""

    def test_turn_factory_constructs_single_shared_pipeline(self):
        """When LLMService is provided, one pipeline is shared by all engines."""
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        
        orchestrator = build_turn_orchestrator(llm_service=llm_service)
        
        # Verify orchestrator has pipeline
        assert orchestrator._proposal_pipeline is not None
        assert isinstance(orchestrator._proposal_pipeline, ProposalPipeline)
        
        # Verify all engines share the same pipeline instance
        orchestrator_pipeline = id(orchestrator._proposal_pipeline)
        world_pipeline = id(orchestrator._world_engine._proposal_pipeline)
        npc_pipeline = id(orchestrator._npc_engine._proposal_pipeline)
        narration_pipeline = id(orchestrator._narration_engine._proposal_pipeline)
        scene_pipeline = id(orchestrator._scene_engine._proposal_pipeline)
        
        assert orchestrator_pipeline == world_pipeline
        assert orchestrator_pipeline == npc_pipeline
        assert orchestrator_pipeline == narration_pipeline
        assert orchestrator_pipeline == scene_pipeline

    def test_scene_engine_is_constructed_with_pipeline(self):
        """SceneEngine is always constructed and receives pipeline when available."""
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        
        orchestrator = build_turn_orchestrator(llm_service=llm_service)
        
        assert orchestrator._scene_engine is not None
        assert orchestrator._scene_engine._proposal_pipeline is not None
        assert isinstance(orchestrator._scene_engine._proposal_pipeline, ProposalPipeline)

    def test_all_engines_receive_pipeline(self):
        """All four engines plus orchestrator receive the pipeline."""
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        
        orchestrator = build_turn_orchestrator(llm_service=llm_service)
        
        assert orchestrator._proposal_pipeline is not None
        assert orchestrator._world_engine._proposal_pipeline is not None
        assert orchestrator._npc_engine._proposal_pipeline is not None
        assert orchestrator._narration_engine._proposal_pipeline is not None
        assert orchestrator._scene_engine._proposal_pipeline is not None


class TestTurnFactoryWithoutPipeline:
    """Tests for factory when LLMService is not provided."""

    def test_turn_factory_constructs_without_pipeline_when_service_missing(self):
        """When LLMService is None, all engines have proposal_pipeline=None."""
        orchestrator = build_turn_orchestrator(llm_service=None)
        
        # Verify orchestrator has no pipeline
        assert orchestrator._proposal_pipeline is None
        
        # Verify all engines have None pipeline
        assert orchestrator._world_engine._proposal_pipeline is None
        assert orchestrator._npc_engine._proposal_pipeline is None
        assert orchestrator._narration_engine._proposal_pipeline is None
        assert orchestrator._scene_engine._proposal_pipeline is None

    def test_scene_engine_is_constructed_without_pipeline(self):
        """SceneEngine is constructed even without LLMService."""
        orchestrator = build_turn_orchestrator(llm_service=None)
        
        assert orchestrator._scene_engine is not None
        assert orchestrator._scene_engine._proposal_pipeline is None

    def test_orchestrator_has_all_dependencies(self):
        """Orchestrator is fully constructed with all required dependencies."""
        orchestrator = build_turn_orchestrator(llm_service=None)
        
        assert orchestrator._state_manager is not None
        assert orchestrator._event_log is not None
        assert orchestrator._action_scheduler is not None
        assert orchestrator._validator is not None
        assert orchestrator._perspective is not None
        assert orchestrator._context_builder is not None
        assert orchestrator._world_engine is not None
        assert orchestrator._npc_engine is not None
        assert orchestrator._narration_engine is not None
        assert orchestrator._scene_engine is not None
        assert orchestrator._memory_writer is not None


class TestTurnFactoryPipelineCreation:
    """Tests for ProposalPipeline creation behavior."""

    @patch('llm_rpg.api.turn_factory.create_proposal_pipeline')
    def test_create_proposal_pipeline_called_once(self, mock_create):
        """create_proposal_pipeline is called exactly once when LLMService is provided."""
        mock_pipeline = MagicMock(spec=ProposalPipeline)
        mock_create.return_value = mock_pipeline
        
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        
        orchestrator = build_turn_orchestrator(llm_service=llm_service)
        
        # Verify create_proposal_pipeline was called once
        mock_create.assert_called_once_with(llm_service=llm_service)
        
        # Verify the returned pipeline is used
        assert orchestrator._proposal_pipeline is mock_pipeline

    @patch('llm_rpg.api.turn_factory.create_proposal_pipeline')
    def test_create_proposal_pipeline_not_called_without_service(self, mock_create):
        """create_proposal_pipeline is not called when LLMService is None."""
        orchestrator = build_turn_orchestrator(llm_service=None)
        
        # Verify create_proposal_pipeline was not called
        mock_create.assert_not_called()
        
        # Verify no pipeline was created
        assert orchestrator._proposal_pipeline is None
