"""
Tests for the unified proposal pipeline.

Tests cover:
- Valid proposal parsing for all types
- Malformed output repair and fallback
- Schema validation failure handling
- Timeout handling
- Fallback generation
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from llm_rpg.models.proposals import (
    InputIntentProposal,
    WorldTickProposal,
    SceneEventProposal,
    NPCActionProposal,
    NarrationProposal,
    ProposalType,
    ProposalSource,
    ProposalAuditMetadata,
    RepairStatus,
    ValidationStatus,
)
from llm_rpg.llm.proposal_pipeline import (
    ProposalPipeline,
    ProposalConfig,
    ProposalPipelineError,
    ProposalTimeoutError,
    create_proposal_pipeline,
)
from llm_rpg.llm.service import LLMService, LLMMessage, LLMResponse, MockLLMProvider
from llm_rpg.llm.repair import RetryRepairHandler


class TestProposalModels:
    """Tests for proposal model creation and validation."""

    def test_input_intent_proposal_creation(self):
        proposal = InputIntentProposal(
            intent_type="move",
            target="location_001",
            risk_level="low",
            confidence=0.8,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.INPUT_INTENT,
                source_engine=ProposalSource.INPUT_ENGINE,
            ),
        )
        assert proposal.intent_type == "move"
        assert proposal.target == "location_001"
        assert proposal.confidence == 0.8
        assert proposal.is_fallback == False
        assert proposal.audit.proposal_type == ProposalType.INPUT_INTENT

    def test_world_tick_proposal_creation(self):
        proposal = WorldTickProposal(
            time_delta_turns=1,
            time_description="时间缓缓流逝",
            candidate_events=[],
            confidence=0.7,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.WORLD_TICK,
                source_engine=ProposalSource.WORLD_ENGINE,
            ),
        )
        assert proposal.time_delta_turns == 1
        assert proposal.confidence == 0.7
        assert proposal.is_fallback == False

    def test_scene_event_proposal_creation(self):
        proposal = SceneEventProposal(
            scene_id="scene_001",
            candidate_events=[],
            confidence=0.6,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.SCENE_EVENT,
                source_engine=ProposalSource.SCENE_ENGINE,
            ),
        )
        assert proposal.scene_id == "scene_001"
        assert proposal.confidence == 0.6

    def test_npc_action_proposal_creation(self):
        proposal = NPCActionProposal(
            npc_id="npc_001",
            action_type="talk",
            summary="NPC与玩家交谈",
            confidence=0.75,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.NPC_ACTION,
                source_engine=ProposalSource.NPC_ENGINE,
            ),
        )
        assert proposal.npc_id == "npc_001"
        assert proposal.action_type == "talk"
        assert proposal.confidence == 0.75

    def test_narration_proposal_creation(self):
        proposal = NarrationProposal(
            text="场景在你眼前展开...",
            tone="neutral",
            confidence=0.8,
            audit=ProposalAuditMetadata(
                proposal_type=ProposalType.NARRATION,
                source_engine=ProposalSource.NARRATION_ENGINE,
            ),
        )
        assert proposal.text == "场景在你眼前展开..."
        assert proposal.tone == "neutral"
        assert proposal.hidden_info_check_passed == True


class TestProposalPipelineValidParsing:
    """Tests for valid proposal parsing."""

    @pytest.fixture
    def pipeline(self):
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        return ProposalPipeline(llm_service=llm_service)

    @pytest.mark.asyncio
    async def test_generate_input_intent_valid_json(self, pipeline):
        valid_json = json.dumps({
            "intent_type": "move",
            "target": "location_001",
            "risk_level": "low",
            "confidence": 0.8,
        })
        
        pipeline._llm_service._provider.responses = {"玩家输入": valid_json}
        
        proposal = await pipeline.generate_input_intent(
            raw_input="我想去东边的山门",
            session_id="session_001",
            turn_no=1,
        )
        
        assert isinstance(proposal, InputIntentProposal)
        assert proposal.intent_type == "move"
        assert proposal.target == "location_001"
        assert proposal.is_fallback == False

    @pytest.mark.asyncio
    async def test_generate_world_tick_valid_json(self, pipeline):
        valid_json = json.dumps({
            "time_delta_turns": 1,
            "time_description": "时间推进",
            "candidate_events": [],
            "confidence": 0.7,
        })
        
        pipeline._llm_service._provider.responses = {"世界上下文": valid_json}
        
        proposal = await pipeline.generate_world_tick(
            world_context={"current_time": "辰时"},
            session_id="session_001",
            turn_no=1,
        )
        
        assert isinstance(proposal, WorldTickProposal)
        assert proposal.time_delta_turns == 1
        assert proposal.is_fallback == False

    @pytest.mark.asyncio
    async def test_generate_scene_event_valid_json(self, pipeline):
        valid_json = json.dumps({
            "scene_id": "scene_001",
            "candidate_events": [],
            "confidence": 0.6,
        })
        
        pipeline._llm_service._provider.responses = {"场景id": valid_json}
        
        proposal = await pipeline.generate_scene_event(
            scene_id="scene_001",
            scene_context={"location": "山门广场"},
            session_id="session_001",
            turn_no=1,
        )
        
        assert isinstance(proposal, SceneEventProposal)
        assert proposal.scene_id == "scene_001"
        assert proposal.is_fallback == False

    @pytest.mark.asyncio
    async def test_generate_npc_action_valid_json(self, pipeline):
        valid_json = json.dumps({
            "npc_id": "npc_001",
            "action_type": "talk",
            "summary": "NPC向玩家打招呼",
            "confidence": 0.75,
        })
        
        pipeline._llm_service._provider.responses = {"npc id": valid_json}
        
        proposal = await pipeline.generate_npc_action(
            npc_id="npc_001",
            npc_context={"mood": "friendly"},
            session_id="session_001",
            turn_no=1,
        )
        
        assert isinstance(proposal, NPCActionProposal)
        assert proposal.npc_id == "npc_001"
        assert proposal.action_type == "talk"
        assert proposal.is_fallback == False

    @pytest.mark.asyncio
    async def test_generate_narration_valid_json(self, pipeline):
        valid_json = json.dumps({
            "text": "晨雾散去，山门广场显得格外宁静。",
            "tone": "peaceful",
            "confidence": 0.8,
        })
        
        pipeline._llm_service._provider.responses = {"可见上下文": valid_json}
        
        proposal = await pipeline.generate_narration(
            visible_context={"scene": "山门广场"},
            session_id="session_001",
            turn_no=1,
        )
        
        assert isinstance(proposal, NarrationProposal)
        assert proposal.text == "晨雾散去，山门广场显得格外宁静。"
        assert proposal.tone == "peaceful"
        assert proposal.is_fallback == False


class TestProposalPipelineMalformedOutput:
    """Tests for malformed output handling."""

    @pytest.fixture
    def pipeline(self):
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        return ProposalPipeline(llm_service=llm_service)

    @pytest.mark.asyncio
    async def test_malformed_json_with_trailing_comma_repair(self, pipeline):
        malformed_json = '{"intent_type": "move", "target": "location_001",}'
        
        pipeline._llm_service._provider.responses = {"玩家输入": malformed_json}
        
        proposal = await pipeline.generate_input_intent(
            raw_input="去东边",
            session_id="session_001",
            turn_no=1,
        )
        
        assert isinstance(proposal, InputIntentProposal)
        assert proposal.intent_type == "move"
        assert proposal.audit.repair_status == RepairStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_json_in_markdown_code_block(self, pipeline):
        markdown_json = '''
```json
{
    "intent_type": "talk",
    "target": "npc_001",
    "confidence": 0.8
}
```
'''
        
        pipeline._llm_service._provider.responses = {"玩家输入": markdown_json}
        
        proposal = await pipeline.generate_input_intent(
            raw_input="和师姐说话",
            session_id="session_001",
            turn_no=1,
        )
        
        assert isinstance(proposal, InputIntentProposal)
        assert proposal.intent_type == "talk"

    @pytest.mark.asyncio
    async def test_completely_unparseable_output_fallback(self, pipeline):
        unparseable = "This is not JSON at all, just plain text."
        
        pipeline._llm_service._provider.responses = {"玩家输入": unparseable}
        
        pipeline._repair_handler.enable_wrapper_fallback = False
        
        proposal = await pipeline.generate_input_intent(
            raw_input="去东边",
            session_id="session_001",
            turn_no=1,
        )
        
        assert isinstance(proposal, InputIntentProposal)
        assert proposal.is_fallback == True
        assert proposal.intent_type == "unknown"
        assert proposal.audit.fallback_used == True


class TestProposalPipelineSchemaValidation:
    """Tests for schema validation failure handling."""

    @pytest.fixture
    def pipeline(self):
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        return ProposalPipeline(llm_service=llm_service)

    @pytest.mark.asyncio
    async def test_invalid_confidence_value_fallback(self, pipeline):
        invalid_json = json.dumps({
            "intent_type": "move",
            "confidence": 1.5,
        })
        
        pipeline._llm_service._provider.responses = {"玩家输入": invalid_json}
        
        proposal = await pipeline.generate_input_intent(
            raw_input="去东边",
            session_id="session_001",
            turn_no=1,
        )
        
        assert isinstance(proposal, InputIntentProposal)
        assert proposal.is_fallback == True
        assert proposal.audit.validation_status == ValidationStatus.FAILED

    @pytest.mark.asyncio
    async def test_missing_required_field_fallback(self, pipeline):
        invalid_json = json.dumps({
            "target": "location_001",
        })
        
        pipeline._llm_service._provider.responses = {"玩家输入": invalid_json}
        
        proposal = await pipeline.generate_input_intent(
            raw_input="去东边",
            session_id="session_001",
            turn_no=1,
        )
        
        assert isinstance(proposal, InputIntentProposal)
        assert proposal.is_fallback == True
        assert proposal.audit.validation_status == ValidationStatus.FAILED

    @pytest.mark.asyncio
    async def test_missing_required_field_fallback(self, pipeline):
        invalid_json = json.dumps({
            "target": "location_001",
        })
        
        pipeline._llm_service._provider.responses = {"玩家输入": invalid_json}
        
        proposal = await pipeline.generate_input_intent(
            raw_input="去东边",
            session_id="session_001",
            turn_no=1,
        )
        
        assert isinstance(proposal, InputIntentProposal)
        assert proposal.is_fallback == True


class TestProposalPipelineTimeout:
    """Tests for timeout handling."""

    @pytest.fixture
    def slow_pipeline(self):
        class SlowMockProvider(MockLLMProvider):
            async def generate(self, messages, **kwargs):
                await asyncio.sleep(5)
                return super().generate(messages, **kwargs)
        
        slow_provider = SlowMockProvider()
        llm_service = LLMService(provider=slow_provider)
        config = ProposalConfig(timeout_seconds=0.1)
        return ProposalPipeline(llm_service=llm_service, config=config)

    @pytest.mark.asyncio
    async def test_timeout_returns_fallback(self, slow_pipeline):
        proposal = await slow_pipeline.generate_input_intent(
            raw_input="去东边",
            session_id="session_001",
            turn_no=1,
        )
        
        assert isinstance(proposal, InputIntentProposal)
        assert proposal.is_fallback == True
        assert proposal.audit.fallback_reason == "Timeout exceeded"


class TestProposalPipelineFallbacks:
    """Tests for fallback generation."""

    def test_create_fallback_input_intent(self):
        from llm_rpg.models.proposals import create_fallback_input_intent
        
        proposal = create_fallback_input_intent(
            raw_input="我想去东边",
            reason="LLM call failed",
        )
        
        assert isinstance(proposal, InputIntentProposal)
        assert proposal.intent_type == "unknown"
        assert proposal.is_fallback == True
        assert proposal.audit.fallback_used == True
        assert proposal.audit.fallback_reason == "LLM call failed"

    def test_create_fallback_world_tick(self):
        from llm_rpg.models.proposals import create_fallback_world_tick
        
        proposal = create_fallback_world_tick(reason="Timeout")
        
        assert isinstance(proposal, WorldTickProposal)
        assert proposal.time_delta_turns == 1
        assert proposal.is_fallback == True

    def test_create_fallback_scene_event(self):
        from llm_rpg.models.proposals import create_fallback_scene_event
        
        proposal = create_fallback_scene_event(
            scene_id="scene_001",
            reason="Parse error",
        )
        
        assert isinstance(proposal, SceneEventProposal)
        assert proposal.scene_id == "scene_001"
        assert proposal.is_fallback == True

    def test_create_fallback_npc_action(self):
        from llm_rpg.models.proposals import create_fallback_npc_action
        
        proposal = create_fallback_npc_action(
            npc_id="npc_001",
            reason="Schema validation failed",
        )
        
        assert isinstance(proposal, NPCActionProposal)
        assert proposal.npc_id == "npc_001"
        assert proposal.action_type == "idle"
        assert proposal.is_fallback == True

    def test_create_fallback_narration(self):
        from llm_rpg.models.proposals import create_fallback_narration
        
        proposal = create_fallback_narration(reason="LLM unavailable")
        
        assert isinstance(proposal, NarrationProposal)
        assert proposal.text == "场景在你眼前展开..."
        assert proposal.is_fallback == True


class TestProposalAuditMetadata:
    """Tests for audit metadata."""

    def test_audit_metadata_defaults(self):
        audit = ProposalAuditMetadata(
            proposal_type=ProposalType.INPUT_INTENT,
            source_engine=ProposalSource.INPUT_ENGINE,
        )
        
        assert audit.repair_status == RepairStatus.NONE
        assert audit.validation_status == ValidationStatus.PENDING
        assert audit.fallback_used == False
        assert audit.repair_attempts == 0

    def test_audit_metadata_with_repair(self):
        audit = ProposalAuditMetadata(
            proposal_type=ProposalType.NPC_ACTION,
            source_engine=ProposalSource.NPC_ENGINE,
            repair_status=RepairStatus.SUCCESS,
            repair_attempts=2,
            repair_strategies_tried=["extract_json", "fix_trailing_commas"],
        )
        
        assert audit.repair_status == RepairStatus.SUCCESS
        assert audit.repair_attempts == 2
        assert len(audit.repair_strategies_tried) == 2


class TestProposalPipelineFactory:
    """Tests for pipeline factory function."""

    def test_create_pipeline_with_defaults(self):
        pipeline = create_proposal_pipeline()
        
        assert isinstance(pipeline, ProposalPipeline)
        assert pipeline._llm_service is not None

    def test_create_pipeline_with_custom_config(self):
        config = ProposalConfig(
            timeout_seconds=60.0,
            max_tokens=2000,
            temperature=0.5,
        )
        
        pipeline = create_proposal_pipeline(config=config)
        
        assert pipeline._config.timeout_seconds == 60.0
        assert pipeline._config.max_tokens == 2000
        assert pipeline._config.temperature == 0.5


class TestProposalTypeMapping:
    """Tests for proposal type to source engine mapping."""

    @pytest.fixture
    def pipeline(self):
        mock_provider = MockLLMProvider()
        llm_service = LLMService(provider=mock_provider)
        return ProposalPipeline(llm_service=llm_service)

    def test_input_intent_source_engine(self, pipeline):
        source = pipeline._get_source_engine(ProposalType.INPUT_INTENT)
        assert source == ProposalSource.INPUT_ENGINE

    def test_world_tick_source_engine(self, pipeline):
        source = pipeline._get_source_engine(ProposalType.WORLD_TICK)
        assert source == ProposalSource.WORLD_ENGINE

    def test_scene_event_source_engine(self, pipeline):
        source = pipeline._get_source_engine(ProposalType.SCENE_EVENT)
        assert source == ProposalSource.SCENE_ENGINE

    def test_npc_action_source_engine(self, pipeline):
        source = pipeline._get_source_engine(ProposalType.NPC_ACTION)
        assert source == ProposalSource.NPC_ENGINE

    def test_narration_source_engine(self, pipeline):
        source = pipeline._get_source_engine(ProposalType.NARRATION)
        assert source == ProposalSource.NARRATION_ENGINE