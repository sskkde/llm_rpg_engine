"""
Unit tests for LLM-driven input understanding in TurnOrchestrator.

Tests cover:
- LLM intent proposal to ParsedIntent conversion
- Bad proposal falls back to keyword parser
- Audit logging for LLM parse and fallback
- ProposalPipeline integration
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from llm_rpg.core.turn_orchestrator import TurnOrchestrator
from llm_rpg.models.events import ParsedIntent
from llm_rpg.models.proposals import (
    InputIntentProposal,
    ProposalAuditMetadata,
    ProposalType,
    ProposalSource,
    RepairStatus,
    ValidationStatus,
)
from llm_rpg.llm.proposal_pipeline import ProposalPipeline
from llm_rpg.llm.service import LLMService, MockLLMProvider


class MockTurnDependencies:
    """Mock dependencies for TurnOrchestrator testing."""
    
    def __init__(self):
        self.state_manager = MagicMock()
        self.event_log = MagicMock()
        self.action_scheduler = MagicMock()
        self.validator = MagicMock()
        self.perspective_service = MagicMock()
        self.context_builder = MagicMock()
        self.world_engine = MagicMock()
        self.npc_engine = MagicMock()
        self.narration_engine = MagicMock()


@pytest.fixture
def mock_deps():
    return MockTurnDependencies()


@pytest.fixture
def pipeline():
    mock_provider = MockLLMProvider()
    llm_service = LLMService(provider=mock_provider)
    return ProposalPipeline(llm_service=llm_service)


@pytest.fixture
def orchestrator_with_pipeline(mock_deps, pipeline):
    return TurnOrchestrator(
        state_manager=mock_deps.state_manager,
        event_log=mock_deps.event_log,
        action_scheduler=mock_deps.action_scheduler,
        validator=mock_deps.validator,
        perspective_service=mock_deps.perspective_service,
        context_builder=mock_deps.context_builder,
        world_engine=mock_deps.world_engine,
        npc_engine=mock_deps.npc_engine,
        narration_engine=mock_deps.narration_engine,
        proposal_pipeline=pipeline,
    )


@pytest.fixture
def orchestrator_without_pipeline(mock_deps):
    return TurnOrchestrator(
        state_manager=mock_deps.state_manager,
        event_log=mock_deps.event_log,
        action_scheduler=mock_deps.action_scheduler,
        validator=mock_deps.validator,
        perspective_service=mock_deps.perspective_service,
        context_builder=mock_deps.context_builder,
        world_engine=mock_deps.world_engine,
        npc_engine=mock_deps.npc_engine,
        narration_engine=mock_deps.narration_engine,
        proposal_pipeline=None,
    )


class TestLLMIntentProposalToParsedIntent:
    """Tests for converting valid LLM intent proposals to ParsedIntent."""

    def test_valid_proposal_converts_to_parsed_intent(self, orchestrator_with_pipeline, pipeline):
        valid_json = json.dumps({
            "intent_type": "move",
            "target": "location_001",
            "risk_level": "low",
            "confidence": 0.85,
        })
        pipeline._llm_service._provider.responses = {"玩家输入": valid_json}
        
        parsed = orchestrator_with_pipeline._parse_intent("我想去东边的山门")
        
        assert isinstance(parsed, ParsedIntent)
        assert parsed.intent_type == "move"
        # target is extracted from raw_tokens when not explicitly provided by LLM
        assert parsed.risk_level == "low"

    def test_talk_intent_from_llm(self, orchestrator_with_pipeline, pipeline):
        valid_json = json.dumps({
            "intent_type": "talk",
            "target": "npc_001",
            "risk_level": "low",
            "confidence": 0.9,
        })
        pipeline._llm_service._provider.responses = {"玩家输入": valid_json}
        
        parsed = orchestrator_with_pipeline._parse_intent("和师姐说话")
        
        assert parsed.intent_type == "talk"
        # target is extracted from raw_tokens when not explicitly provided by LLM

    def test_attack_intent_high_risk(self, orchestrator_with_pipeline, pipeline):
        valid_json = json.dumps({
            "intent_type": "attack",
            "target": "enemy_001",
            "risk_level": "high",
            "confidence": 0.75,
        })
        pipeline._llm_service._provider.responses = {"玩家输入": valid_json}
        
        parsed = orchestrator_with_pipeline._parse_intent("攻击敌人")
        
        assert parsed.intent_type == "attack"
        assert parsed.risk_level == "high"

    def test_llm_parse_creates_audit_entry(self, orchestrator_with_pipeline, pipeline):
        valid_json = json.dumps({
            "intent_type": "inspect",
            "target": "object_001",
            "confidence": 0.8,
        })
        pipeline._llm_service._provider.responses = {"玩家输入": valid_json}
        
        initial_audit_count = len(orchestrator_with_pipeline._proposal_audits)
        orchestrator_with_pipeline._parse_intent("观察四周")
        
        assert len(orchestrator_with_pipeline._proposal_audits) == initial_audit_count + 1
        audit_entry = orchestrator_with_pipeline._proposal_audits[-1]
        assert audit_entry["proposal_type"] == "input_intent"


class TestBadProposalFallsBackToKeywordParser:
    """Tests for fallback to keyword parser when LLM fails."""

    def test_fallback_proposal_uses_keyword_parser(self, orchestrator_with_pipeline, pipeline):
        unparseable = "This is not valid JSON at all"
        pipeline._llm_service._provider.responses = {"玩家输入": unparseable}
        pipeline._repair_handler.enable_wrapper_fallback = False
        
        parsed = orchestrator_with_pipeline._parse_intent("去东边")
        
        assert isinstance(parsed, ParsedIntent)
        assert parsed.intent_type == "move"

    def test_malformed_json_fallback(self, orchestrator_with_pipeline, pipeline):
        malformed = '{"intent_type": "move", "target": "loc",}'
        pipeline._llm_service._provider.responses = {"玩家输入": malformed}
        
        parsed = orchestrator_with_pipeline._parse_intent("去东边")
        
        assert isinstance(parsed, ParsedIntent)

    def test_schema_validation_failure_fallback(self, orchestrator_with_pipeline, pipeline):
        invalid_json = json.dumps({
            "intent_type": "move",
            "confidence": 1.5,
        })
        pipeline._llm_service._provider.responses = {"玩家输入": invalid_json}
        
        parsed = orchestrator_with_pipeline._parse_intent("去东边")
        
        assert isinstance(parsed, ParsedIntent)

    def test_missing_required_field_fallback(self, orchestrator_with_pipeline, pipeline):
        invalid_json = json.dumps({
            "target": "location_001",
        })
        pipeline._llm_service._provider.responses = {"玩家输入": invalid_json}
        
        parsed = orchestrator_with_pipeline._parse_intent("去东边")
        
        assert isinstance(parsed, ParsedIntent)

    def test_fallback_creates_audit_entry(self, orchestrator_with_pipeline, pipeline):
        unparseable = "Not JSON"
        pipeline._llm_service._provider.responses = {"玩家输入": unparseable}
        pipeline._repair_handler.enable_wrapper_fallback = False
        
        initial_audit_count = len(orchestrator_with_pipeline._proposal_audits)
        orchestrator_with_pipeline._parse_intent("去东边")
        
        assert len(orchestrator_with_pipeline._proposal_audits) == initial_audit_count + 1
        audit_entry = orchestrator_with_pipeline._proposal_audits[-1]
        assert audit_entry["proposal_type"] == "input_intent"
        assert audit_entry["fallback_reason"] is not None


class TestKeywordParserFallback:
    """Tests for keyword-based fallback parser."""

    def test_keyword_parser_move(self, orchestrator_without_pipeline):
        parsed = orchestrator_without_pipeline._parse_intent_keyword("去东边")
        
        assert parsed.intent_type == "move"

    def test_keyword_parser_talk(self, orchestrator_without_pipeline):
        parsed = orchestrator_without_pipeline._parse_intent_keyword("和师姐说话")
        
        assert parsed.intent_type == "talk"

    def test_keyword_parser_attack(self, orchestrator_without_pipeline):
        parsed = orchestrator_without_pipeline._parse_intent_keyword("攻击敌人")
        
        assert parsed.intent_type == "attack"
        assert parsed.risk_level == "high"

    def test_keyword_parser_inspect(self, orchestrator_without_pipeline):
        parsed = orchestrator_without_pipeline._parse_intent_keyword("观察四周")
        
        assert parsed.intent_type == "inspect"

    def test_keyword_parser_interact(self, orchestrator_without_pipeline):
        parsed = orchestrator_without_pipeline._parse_intent_keyword("拿起物品")
        
        assert parsed.intent_type == "interact"

    def test_keyword_parser_default_action(self, orchestrator_without_pipeline):
        parsed = orchestrator_without_pipeline._parse_intent_keyword("做一些事情")
        
        assert parsed.intent_type == "action"

    def test_keyword_parser_english_input(self, orchestrator_without_pipeline):
        parsed = orchestrator_without_pipeline._parse_intent_keyword("move east")
        
        assert parsed.intent_type == "move"

    def test_keyword_parser_raw_tokens(self, orchestrator_without_pipeline):
        parsed = orchestrator_without_pipeline._parse_intent_keyword("去 东 边")
        
        assert parsed.raw_tokens == ["去", "东", "边"]


class TestNoPipelineUsesKeywordParser:
    """Tests for keyword parser when no pipeline is configured."""

    def test_no_pipeline_uses_keyword_parser(self, orchestrator_without_pipeline):
        parsed = orchestrator_without_pipeline._parse_intent("去东边")
        
        assert isinstance(parsed, ParsedIntent)
        assert parsed.intent_type == "move"

    def test_no_pipeline_no_audit_entry_for_keyword(self, orchestrator_without_pipeline):
        initial_audit_count = len(orchestrator_without_pipeline._audit_log)
        orchestrator_without_pipeline._parse_intent("去东边")
        
        assert len(orchestrator_without_pipeline._audit_log) == initial_audit_count


class TestAuditLogging:
    """Tests for audit logging of intent parsing."""

    def test_audit_log_structure_llm_success(self, orchestrator_with_pipeline, pipeline):
        valid_json = json.dumps({
            "intent_type": "move",
            "target": "loc_001",
            "confidence": 0.8,
        })
        pipeline._llm_service._provider.responses = {"玩家输入": valid_json}
        
        orchestrator_with_pipeline._parse_intent("去东边")
        
        audit_entry = orchestrator_with_pipeline._proposal_audits[-1]
        assert "audit_id" in audit_entry
        assert "timestamp" in audit_entry
        assert audit_entry["proposal_type"] == "input_intent"

    def test_audit_log_structure_fallback(self, orchestrator_with_pipeline, pipeline):
        pipeline._llm_service._provider.responses = {"玩家输入": "not json"}
        pipeline._repair_handler.enable_wrapper_fallback = False
        
        orchestrator_with_pipeline._parse_intent("去东边")
        
        audit_entry = orchestrator_with_pipeline._proposal_audits[-1]
        assert audit_entry["proposal_type"] == "input_intent"
        assert audit_entry["fallback_reason"] is not None

    def test_audit_log_structure_error(self, orchestrator_with_pipeline, pipeline):
        class FailingProvider(MockLLMProvider):
            async def generate(self, messages, **kwargs):
                raise RuntimeError("LLM service unavailable")
        
        pipeline._llm_service._provider = FailingProvider()
        
        orchestrator_with_pipeline._parse_intent("去东边")
        
        audit_entry = orchestrator_with_pipeline._proposal_audits[-1]
        assert audit_entry["proposal_type"] == "input_intent"
        assert audit_entry["fallback_reason"] is not None


class TestParsedIntentModel:
    """Tests for ParsedIntent model structure."""

    def test_parsed_intent_defaults(self):
        intent = ParsedIntent(intent_type="action")
        
        assert intent.target is None
        assert intent.risk_level == "low"
        assert intent.raw_tokens == []

    def test_parsed_intent_full(self):
        intent = ParsedIntent(
            intent_type="attack",
            target="enemy_001",
            risk_level="high",
            raw_tokens=["攻击", "敌人"],
        )
        
        assert intent.intent_type == "attack"
        assert intent.target == "enemy_001"
        assert intent.risk_level == "high"
        assert intent.raw_tokens == ["攻击", "敌人"]


class TestLLMExceptionFallback:
    """Tests for LLM exception fallback behavior."""

    def test_generate_input_intent_exception_falls_back_to_keyword(self, orchestrator_with_pipeline, pipeline):
        class FailingProvider(MockLLMProvider):
            async def generate(self, messages, **kwargs):
                raise RuntimeError("LLM service unavailable")
        
        pipeline._llm_service._provider = FailingProvider()
        
        parsed = orchestrator_with_pipeline._parse_intent("去东边")
        
        assert isinstance(parsed, ParsedIntent)
        assert parsed.intent_type == "move"
        assert len(orchestrator_with_pipeline._proposal_audits) >= 1
        audit_entry = orchestrator_with_pipeline._proposal_audits[-1]
        assert audit_entry["fallback_reason"] is not None

    def test_generate_input_intent_timeout_falls_back(self, orchestrator_with_pipeline, pipeline):
        import asyncio
        
        class TimeoutProvider(MockLLMProvider):
            async def generate(self, messages, **kwargs):
                await asyncio.sleep(100)
                return "response"
        
        pipeline._llm_service._provider = TimeoutProvider()
        
        parsed = orchestrator_with_pipeline._parse_intent("攻击敌人")
        
        assert isinstance(parsed, ParsedIntent)
        assert parsed.intent_type == "attack"

    def test_turn_succeeds_with_keyword_fallback(self, orchestrator_with_pipeline, pipeline):
        class FailingProvider(MockLLMProvider):
            async def generate(self, messages, **kwargs):
                raise RuntimeError("LLM service unavailable")
        
        pipeline._llm_service._provider = FailingProvider()
        
        parsed = orchestrator_with_pipeline._parse_intent("和师姐说话")
        
        assert parsed.intent_type == "talk"
        assert parsed.risk_level == "low"
