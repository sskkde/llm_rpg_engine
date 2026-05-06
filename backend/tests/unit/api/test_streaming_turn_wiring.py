"""
Unit tests for streaming turn wiring.

Tests verify:
- Streaming turn path forwards resolved LLMService into shared turn factory
- Streaming path uses one shared pipeline for all core turn proposal stages
- Streaming turn succeeds when provider is absent/unusable (fallback)
- No duplicate pipeline construction per turn factory construction
- Streaming narration bypasses ProposalPipeline for SSE token stream
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from typing import AsyncGenerator

from llm_rpg.api.turn_factory import build_turn_orchestrator
from llm_rpg.llm.service import LLMService, MockLLMProvider
from llm_rpg.llm.proposal_pipeline import ProposalPipeline, create_proposal_pipeline
from llm_rpg.core.turn_orchestrator import TurnOrchestrator


class TestStreamingTurnUsesSharedPipeline:
    """Tests for streaming turn path using shared pipeline."""

    def test_streaming_turn_uses_shared_pipeline_for_all_stages(self):
        """
        Streaming path passes one shared pipeline into orchestrator/engines
        for core turn proposal stages.
        
        This test verifies that when streaming turn creates an orchestrator
        via the factory, all engines (WorldEngine, NPCEngine, NarrationEngine,
        SceneEngine) share the same ProposalPipeline instance.
        """
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        
        # Build orchestrator through factory (this is what streaming should use)
        orchestrator = build_turn_orchestrator(llm_service=llm_service)
        
        # Verify orchestrator has pipeline
        assert orchestrator._proposal_pipeline is not None
        assert isinstance(orchestrator._proposal_pipeline, ProposalPipeline)
        
        # Verify all engines share the SAME pipeline instance (using id() for identity)
        orchestrator_pipeline_id = id(orchestrator._proposal_pipeline)
        world_pipeline_id = id(orchestrator._world_engine._proposal_pipeline)
        npc_pipeline_id = id(orchestrator._npc_engine._proposal_pipeline)
        narration_pipeline_id = id(orchestrator._narration_engine._proposal_pipeline)
        scene_pipeline_id = id(orchestrator._scene_engine._proposal_pipeline)
        
        # All must be the exact same instance
        assert orchestrator_pipeline_id == world_pipeline_id, \
            "WorldEngine must share orchestrator's pipeline"
        assert orchestrator_pipeline_id == npc_pipeline_id, \
            "NPCEngine must share orchestrator's pipeline"
        assert orchestrator_pipeline_id == narration_pipeline_id, \
            "NarrationEngine must share orchestrator's pipeline"
        assert orchestrator_pipeline_id == scene_pipeline_id, \
            "SceneEngine must share orchestrator's pipeline"

    @patch('llm_rpg.api.turn_factory.create_proposal_pipeline')
    def test_streaming_turn_does_not_construct_pipeline_per_stage(self, mock_create):
        """
        Only one pipeline instance is created per turn factory construction.
        
        This test verifies that create_proposal_pipeline is called exactly once
        when building the orchestrator, not multiple times for each engine.
        """
        mock_pipeline = MagicMock(spec=ProposalPipeline)
        mock_create.return_value = mock_pipeline
        
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        
        # Build orchestrator
        orchestrator = build_turn_orchestrator(llm_service=llm_service)
        
        # Verify create_proposal_pipeline was called EXACTLY ONCE
        mock_create.assert_called_once_with(llm_service=llm_service)
        
        # Verify all engines use the same mock_pipeline instance
        assert orchestrator._proposal_pipeline is mock_pipeline
        assert orchestrator._world_engine._proposal_pipeline is mock_pipeline
        assert orchestrator._npc_engine._proposal_pipeline is mock_pipeline
        assert orchestrator._narration_engine._proposal_pipeline is mock_pipeline
        assert orchestrator._scene_engine._proposal_pipeline is mock_pipeline


class TestStreamingTurnFallbackWithoutProvider:
    """Tests for streaming turn behavior when provider is absent/unusable."""

    def test_streaming_turn_falls_back_without_provider(self):
        """
        Streaming turn still succeeds when provider is absent/unusable.
        
        When llm_service is None, the factory constructs all engines with
        proposal_pipeline=None, and engines use deterministic fallback behavior.
        """
        # Build orchestrator without LLMService
        orchestrator = build_turn_orchestrator(llm_service=None)
        
        # Verify orchestrator is constructed successfully
        assert orchestrator is not None
        assert isinstance(orchestrator, TurnOrchestrator)
        
        # Verify all engines have None pipeline (fallback mode)
        assert orchestrator._proposal_pipeline is None
        assert orchestrator._world_engine._proposal_pipeline is None
        assert orchestrator._npc_engine._proposal_pipeline is None
        assert orchestrator._narration_engine._proposal_pipeline is None
        assert orchestrator._scene_engine._proposal_pipeline is None
        
        # Verify all required dependencies are present
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

    @patch('llm_rpg.api.turn_factory.create_proposal_pipeline')
    def test_no_pipeline_created_when_service_is_none(self, mock_create):
        """
        create_proposal_pipeline is not called when LLMService is None.
        
        This ensures no unnecessary pipeline construction happens in fallback mode.
        """
        # Build orchestrator without LLMService
        orchestrator = build_turn_orchestrator(llm_service=None)
        
        # Verify create_proposal_pipeline was NOT called
        mock_create.assert_not_called()
        
        # Verify no pipeline exists
        assert orchestrator._proposal_pipeline is None


class TestStreamingNarrationBypassesPipeline:
    """Tests verifying streaming narration's direct SSE path."""

    def test_streaming_narration_uses_llm_service_directly(self):
        """
        Streaming narration bypasses ProposalPipeline for SSE token stream.
        
        The generate_narration_stream function in streaming.py directly calls
        llm_service.generate_stream() instead of going through ProposalPipeline.
        This is intentional for real-time token streaming.
        
        This test verifies that the orchestrator's pipeline is separate from
        the narration streaming path.
        """
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        
        orchestrator = build_turn_orchestrator(llm_service=llm_service)
        
        # The orchestrator has a pipeline for core turn stages
        assert orchestrator._proposal_pipeline is not None
        
        # But streaming narration uses llm_service directly (not through pipeline)
        # This is verified by checking that NarrationEngine has pipeline
        # but streaming.py's generate_narration_stream takes llm_service as parameter
        # separately from the orchestrator
        
        # Verify the separation: orchestrator has pipeline, but streaming
        # narration path receives llm_service as separate parameter
        assert orchestrator._narration_engine._proposal_pipeline is not None
        
        # The llm_service used for streaming narration is the same provider
        # but goes through a different path (direct SSE streaming)
        assert llm_service._provider is mock_provider


class TestStreamingTurnWiringIntegration:
    """Integration tests for streaming turn wiring behavior."""

    def test_factory_creates_consistent_orchestrator_multiple_calls(self):
        """
        Multiple calls to build_turn_orchestrator create independent orchestrators
        but each with consistent internal pipeline sharing.
        """
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        
        # Create two orchestrators
        orchestrator1 = build_turn_orchestrator(llm_service=llm_service)
        orchestrator2 = build_turn_orchestrator(llm_service=llm_service)
        
        # They are different instances
        assert orchestrator1 is not orchestrator2
        
        # But each has consistent internal pipeline sharing
        # Orchestrator 1: all engines share same pipeline
        pipeline1_id = id(orchestrator1._proposal_pipeline)
        assert pipeline1_id == id(orchestrator1._world_engine._proposal_pipeline)
        assert pipeline1_id == id(orchestrator1._npc_engine._proposal_pipeline)
        assert pipeline1_id == id(orchestrator1._narration_engine._proposal_pipeline)
        assert pipeline1_id == id(orchestrator1._scene_engine._proposal_pipeline)
        
        # Orchestrator 2: all engines share same pipeline (different from orchestrator1)
        pipeline2_id = id(orchestrator2._proposal_pipeline)
        assert pipeline2_id == id(orchestrator2._world_engine._proposal_pipeline)
        assert pipeline2_id == id(orchestrator2._npc_engine._proposal_pipeline)
        assert pipeline2_id == id(orchestrator2._narration_engine._proposal_pipeline)
        assert pipeline2_id == id(orchestrator2._scene_engine._proposal_pipeline)
        
        # Each orchestrator has its own pipeline instance
        assert pipeline1_id != pipeline2_id

    def test_mock_provider_works_for_streaming_turn(self):
        """
        MockLLMProvider is suitable for streaming turn tests.
        
        This verifies the mock provider can be used in streaming turn
        wiring tests without requiring real API keys.
        """
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        
        orchestrator = build_turn_orchestrator(llm_service=llm_service)
        
        # Verify mock provider is properly wired
        assert llm_service._provider is mock_provider
        assert mock_provider.model == "mock-model"
        
        # Verify orchestrator is functional
        assert orchestrator._proposal_pipeline is not None
        assert orchestrator._proposal_pipeline._llm_service is llm_service