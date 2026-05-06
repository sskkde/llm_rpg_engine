"""
Unit tests for LLM input intent stage in turn_service.

Tests cover:
- _is_input_intent_stage_enabled() feature flag
- _build_input_intent_context() context building
- _validate_input_intent_proposal() validation
- _execute_input_intent_stage() LLM stage execution
- Integration with execute_turn_service()
"""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

from llm_rpg.core.turn_service import (
    _is_input_intent_stage_enabled,
    _build_input_intent_context,
    _validate_input_intent_proposal,
    _execute_input_intent_stage,
    LLMStageResult,
)
from llm_rpg.models.states import CanonicalState, PlayerState
from llm_rpg.models.proposals import InputIntentProposal, ProposalAuditMetadata
from llm_rpg.llm.service import LLMService, MockLLMProvider


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock()


@pytest.fixture
def mock_canonical_state():
    """Create a mock canonical state."""
    player_state = MagicMock()
    player_state.name = "测试玩家"
    player_state.realm = "练气期"
    player_state.spiritual_power = 100
    
    state = MagicMock()
    state.player_state = player_state
    return state


class TestIsInputIntentStageEnabled:
    """Tests for _is_input_intent_stage_enabled feature flag."""

    def test_enabled_when_provider_not_mock(self, mock_db):
        with patch("llm_rpg.services.settings.SystemSettingsService") as mock_settings:
            mock_instance = MagicMock()
            mock_instance.get_provider_config.return_value = {"provider_mode": "openai"}
            mock_settings.return_value = mock_instance
            
            result = _is_input_intent_stage_enabled(mock_db)
            
            assert result is True

    def test_disabled_when_provider_is_mock(self, mock_db):
        with patch("llm_rpg.services.settings.SystemSettingsService") as mock_settings:
            mock_instance = MagicMock()
            mock_instance.get_provider_config.return_value = {"provider_mode": "mock"}
            mock_settings.return_value = mock_instance
            
            result = _is_input_intent_stage_enabled(mock_db)
            
            assert result is False

    def test_disabled_on_exception(self, mock_db):
        with patch("llm_rpg.services.settings.SystemSettingsService") as mock_settings:
            mock_settings.side_effect = Exception("Settings error")
            
            result = _is_input_intent_stage_enabled(mock_db)
            
            assert result is False


class TestBuildInputIntentContext:
    """Tests for _build_input_intent_context context building."""

    def test_context_includes_raw_input(self, mock_db, mock_canonical_state):
        with patch("llm_rpg.core.turn_service.SessionStateRepository") as mock_repo:
            mock_instance = MagicMock()
            mock_instance.get_by_session.return_value = None
            mock_repo.return_value = mock_instance
            
            with patch("llm_rpg.core.turn_service._get_visible_npcs", return_value=[]):
                result = _build_input_intent_context(
                    db=mock_db,
                    session_id="test_session",
                    canonical_state=mock_canonical_state,
                    raw_input="前往试炼堂",
                    current_location_id=None,
                )
                
                assert result["raw_input"] == "前往试炼堂"
                assert "constraints" in result

    def test_context_includes_current_location(self, mock_db, mock_canonical_state):
        with patch("llm_rpg.core.turn_service.SessionStateRepository") as mock_session_repo:
            mock_session = MagicMock()
            mock_session.current_location_id = "loc_001"
            mock_session.world_id = "world_001"
            mock_instance = MagicMock()
            mock_instance.get_by_session.return_value = mock_session
            mock_session_repo.return_value = mock_instance
            
            with patch("llm_rpg.core.turn_service.LocationRepository") as mock_loc_repo:
                mock_location = MagicMock()
                mock_location.id = "loc_001"
                mock_location.name = "山门"
                mock_location.code = "mountain_gate"
                mock_loc_instance = MagicMock()
                mock_loc_instance.get_by_id.return_value = mock_location
                mock_loc_instance.get_by_world.return_value = []
                mock_loc_repo.return_value = mock_loc_instance
                
                with patch("llm_rpg.core.turn_service._get_visible_npcs", return_value=[]):
                    result = _build_input_intent_context(
                        db=mock_db,
                        session_id="test_session",
                        canonical_state=mock_canonical_state,
                        raw_input="去东边",
                        current_location_id="loc_001",
                    )
                    
                    assert result["current_location_id"] == "loc_001"
                    assert result["current_location"]["name"] == "山门"


class TestValidateInputIntentProposal:
    """Tests for _validate_input_intent_proposal validation."""

    def test_valid_proposal_passes(self):
        proposal = MagicMock()
        proposal.intent_type = "move"
        proposal.target = "loc_001"
        proposal.risk_level = "low"
        
        is_valid, errors = _validate_input_intent_proposal(proposal, {})
        
        assert is_valid is True
        assert len(errors) == 0

    def test_none_proposal_fails(self):
        is_valid, errors = _validate_input_intent_proposal(None, {})
        
        assert is_valid is False
        assert "proposal is None" in errors

    def test_missing_intent_type_fails(self):
        proposal = MagicMock()
        del proposal.intent_type
        
        is_valid, errors = _validate_input_intent_proposal(proposal, {})
        
        assert is_valid is False
        assert any("intent_type" in e for e in errors)

    def test_invalid_intent_type_fails(self):
        proposal = MagicMock()
        proposal.intent_type = "invalid_type"
        
        is_valid, errors = _validate_input_intent_proposal(proposal, {})
        
        assert is_valid is False
        assert any("invalid intent_type" in e for e in errors)

    def test_invalid_risk_level_fails(self):
        proposal = MagicMock()
        proposal.intent_type = "move"
        proposal.target = "loc_001"
        proposal.risk_level = "extreme"
        
        is_valid, errors = _validate_input_intent_proposal(proposal, {})
        
        assert is_valid is False
        assert any("invalid risk_level" in e for e in errors)

    def test_move_without_target_fails(self):
        proposal = MagicMock()
        proposal.intent_type = "move"
        proposal.target = None
        
        is_valid, errors = _validate_input_intent_proposal(proposal, {})
        
        assert is_valid is False
        assert any("requires a target" in e for e in errors)

    def test_talk_without_target_passes(self):
        proposal = MagicMock()
        proposal.intent_type = "talk"
        proposal.target = None
        proposal.risk_level = "low"
        
        is_valid, errors = _validate_input_intent_proposal(proposal, {})
        
        assert is_valid is True


class TestExecuteInputIntentStage:
    """Tests for _execute_input_intent_stage LLM stage execution."""

    def test_disabled_stage_returns_disabled_result(self, mock_db, mock_canonical_state):
        with patch("llm_rpg.core.turn_service._is_input_intent_stage_enabled", return_value=False):
            result = _execute_input_intent_stage(
                db=mock_db,
                session_id="test_session",
                turn_no=1,
                canonical_state=mock_canonical_state,
                raw_input="前往试炼堂",
                current_location_id=None,
            )
            
            assert result.enabled is False
            assert result.accepted is False
            assert result.fallback_reason == "input_intent_stage_disabled"

    def test_valid_llm_proposal_accepted(self, mock_db, mock_canonical_state):
        mock_provider = MockLLMProvider()
        valid_json = json.dumps({
            "intent_type": "move",
            "target": "试炼堂",
            "risk_level": "low",
            "confidence": 0.9,
        })
        mock_provider.responses = {"玩家输入": valid_json}
        
        with patch("llm_rpg.core.turn_service._is_input_intent_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._build_input_intent_context", return_value={}):
                with patch("llm_rpg.services.settings.SystemSettingsService") as mock_settings:
                    mock_instance = MagicMock()
                    mock_instance.get_provider_config.return_value = {
                        "provider_mode": "openai",
                        "max_tokens": 200,
                        "temperature": 0.3,
                    }
                    mock_instance.get_effective_openai_key.return_value = "test_key"
                    mock_settings.return_value = mock_instance
                    
                    with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                        mock_create.return_value = LLMService(provider=mock_provider)
                        
                        result = _execute_input_intent_stage(
                            db=mock_db,
                            session_id="test_session",
                            turn_no=1,
                            canonical_state=mock_canonical_state,
                            raw_input="前往试炼堂",
                            current_location_id=None,
                        )
                        
                        assert result.enabled is True
                        assert result.stage_name == "input_intent"

    def test_malformed_llm_output_falls_back(self, mock_db, mock_canonical_state):
        mock_provider = MockLLMProvider()
        mock_provider.responses = {"玩家输入": "not valid json at all"}
        
        with patch("llm_rpg.core.turn_service._is_input_intent_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._build_input_intent_context", return_value={}):
                with patch("llm_rpg.services.settings.SystemSettingsService") as mock_settings:
                    mock_instance = MagicMock()
                    mock_instance.get_provider_config.return_value = {
                        "provider_mode": "openai",
                        "max_tokens": 200,
                        "temperature": 0.3,
                    }
                    mock_instance.get_effective_openai_key.return_value = "test_key"
                    mock_settings.return_value = mock_instance
                    
                    with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                        mock_create.return_value = LLMService(provider=mock_provider)
                        
                        result = _execute_input_intent_stage(
                            db=mock_db,
                            session_id="test_session",
                            turn_no=1,
                            canonical_state=mock_canonical_state,
                            raw_input="去东边",
                            current_location_id=None,
                        )
                        
                        assert result.accepted is False
                        assert result.fallback_reason is not None


class TestChineseMovementCommands:
    """Tests for Chinese movement command parsing."""

    def test_chinese_move_to_location(self, mock_db, mock_canonical_state):
        mock_provider = MockLLMProvider()
        valid_json = json.dumps({
            "intent_type": "move",
            "target": "试炼堂",
            "risk_level": "low",
            "confidence": 0.85,
        })
        mock_provider.responses = {"玩家输入": valid_json}
        
        with patch("llm_rpg.core.turn_service._is_input_intent_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._build_input_intent_context", return_value={}):
                with patch("llm_rpg.services.settings.SystemSettingsService") as mock_settings:
                    mock_instance = MagicMock()
                    mock_instance.get_provider_config.return_value = {
                        "provider_mode": "openai",
                        "max_tokens": 200,
                        "temperature": 0.3,
                    }
                    mock_instance.get_effective_openai_key.return_value = "test_key"
                    mock_settings.return_value = mock_instance
                    
                    with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                        mock_create.return_value = LLMService(provider=mock_provider)
                        
                        result = _execute_input_intent_stage(
                            db=mock_db,
                            session_id="test_session",
                            turn_no=1,
                            canonical_state=mock_canonical_state,
                            raw_input="前往试炼堂",
                            current_location_id=None,
                        )
                        
                        if result.accepted and result.parsed_proposal:
                            assert result.parsed_proposal["intent_type"] == "move"
                            assert result.parsed_proposal["target"] == "试炼堂"


class TestInspectionCommands:
    """Tests for inspection command parsing."""

    def test_inspect_command(self, mock_db, mock_canonical_state):
        mock_provider = MockLLMProvider()
        valid_json = json.dumps({
            "intent_type": "inspect",
            "target": "状态",
            "risk_level": "low",
            "confidence": 0.9,
        })
        mock_provider.responses = {"玩家输入": valid_json}
        
        with patch("llm_rpg.core.turn_service._is_input_intent_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._build_input_intent_context", return_value={}):
                with patch("llm_rpg.services.settings.SystemSettingsService") as mock_settings:
                    mock_instance = MagicMock()
                    mock_instance.get_provider_config.return_value = {
                        "provider_mode": "openai",
                        "max_tokens": 200,
                        "temperature": 0.3,
                    }
                    mock_instance.get_effective_openai_key.return_value = "test_key"
                    mock_settings.return_value = mock_instance
                    
                    with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                        mock_create.return_value = LLMService(provider=mock_provider)
                        
                        result = _execute_input_intent_stage(
                            db=mock_db,
                            session_id="test_session",
                            turn_no=1,
                            canonical_state=mock_canonical_state,
                            raw_input="查看状态",
                            current_location_id=None,
                        )
                        
                        if result.accepted and result.parsed_proposal:
                            assert result.parsed_proposal["intent_type"] == "inspect"


class TestDialogueCommands:
    """Tests for dialogue command parsing."""

    def test_talk_to_npc(self, mock_db, mock_canonical_state):
        mock_provider = MockLLMProvider()
        valid_json = json.dumps({
            "intent_type": "talk",
            "target": "师姐",
            "risk_level": "low",
            "confidence": 0.85,
        })
        mock_provider.responses = {"玩家输入": valid_json}
        
        with patch("llm_rpg.core.turn_service._is_input_intent_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._build_input_intent_context", return_value={}):
                with patch("llm_rpg.services.settings.SystemSettingsService") as mock_settings:
                    mock_instance = MagicMock()
                    mock_instance.get_provider_config.return_value = {
                        "provider_mode": "openai",
                        "max_tokens": 200,
                        "temperature": 0.3,
                    }
                    mock_instance.get_effective_openai_key.return_value = "test_key"
                    mock_settings.return_value = mock_instance
                    
                    with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                        mock_create.return_value = LLMService(provider=mock_provider)
                        
                        result = _execute_input_intent_stage(
                            db=mock_db,
                            session_id="test_session",
                            turn_no=1,
                            canonical_state=mock_canonical_state,
                            raw_input="询问师姐试炼规则",
                            current_location_id=None,
                        )
                        
                        if result.accepted and result.parsed_proposal:
                            assert result.parsed_proposal["intent_type"] == "talk"


class TestAmbiguousTargets:
    """Tests for ambiguous target handling."""

    def test_ambiguous_target_falls_back(self, mock_db, mock_canonical_state):
        mock_provider = MockLLMProvider()
        mock_provider.responses = {"玩家输入": "ambiguous response"}
        
        with patch("llm_rpg.core.turn_service._is_input_intent_stage_enabled", return_value=True):
            with patch("llm_rpg.core.turn_service._build_input_intent_context", return_value={}):
                with patch("llm_rpg.services.settings.SystemSettingsService") as mock_settings:
                    mock_instance = MagicMock()
                    mock_instance.get_provider_config.return_value = {
                        "provider_mode": "openai",
                        "max_tokens": 200,
                        "temperature": 0.3,
                    }
                    mock_instance.get_effective_openai_key.return_value = "test_key"
                    mock_settings.return_value = mock_instance
                    
                    with patch("llm_rpg.core.turn_service._create_llm_service_from_config") as mock_create:
                        mock_create.return_value = LLMService(provider=mock_provider)
                        
                        result = _execute_input_intent_stage(
                            db=mock_db,
                            session_id="test_session",
                            turn_no=1,
                            canonical_state=mock_canonical_state,
                            raw_input="去那边",
                            current_location_id=None,
                        )
                        
                        assert result.fallback_reason is not None
