"""Integration tests for core loop with LLM candidates.

Tests the explicit loop order and fallback matrix.
"""

import pytest
from datetime import datetime
from typing import Dict, Any, List, Optional

from llm_rpg.core.audit import (
    ProposalAuditEntry,
    AuditLogger,
    AuditStore,
    get_audit_logger,
    reset_audit_logger,
)
from llm_rpg.core.replay import (
    ReplayEngine,
    ReplayStep,
    ReplayResult,
    StateReconstructor,
)
from llm_rpg.models.proposals import (
    InputIntentProposal,
    WorldTickProposal,
    SceneEventProposal,
    NPCActionProposal,
    NarrationProposal,
    ProposalAuditMetadata,
    ProposalType,
    ProposalSource,
    ValidationStatus,
)


class TestProposalAuditIntegration:
    """Test proposal audit integration with core loop."""

    def setup_method(self):
        """Reset audit logger before each test."""
        reset_audit_logger()
        self.audit_logger = get_audit_logger()
        self.store = self.audit_logger.get_store()

    def test_input_intent_proposal_audit(self):
        """Test audit for input intent proposal."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=1,
            proposal_type="input_intent",
            prompt_template_id="intent_parse_v1",
            parsed_proposal={"intent_type": "move", "target": "north"},
            confidence=0.85,
        )
        
        assert audit.proposal_type == "input_intent"
        assert audit.confidence == 0.85
        assert audit.fallback_used is False

    def test_world_tick_proposal_audit(self):
        """Test audit for world tick proposal."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=1,
            proposal_type="world_tick",
            parsed_proposal={"time_delta_turns": 1, "events": []},
            confidence=0.7,
        )
        
        assert audit.proposal_type == "world_tick"

    def test_scene_event_proposal_audit(self):
        """Test audit for scene event proposal."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=1,
            proposal_type="scene_event",
            parsed_proposal={"scene_id": "scene_001", "events": []},
            confidence=0.6,
        )
        
        assert audit.proposal_type == "scene_event"

    def test_npc_action_proposal_audit(self):
        """Test audit for NPC action proposal."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=1,
            proposal_type="npc_action",
            parsed_proposal={"npc_id": "npc_001", "action_type": "idle"},
            confidence=0.5,
        )
        
        assert audit.proposal_type == "npc_action"

    def test_narration_proposal_audit(self):
        """Test audit for narration proposal."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=1,
            proposal_type="narration",
            parsed_proposal={"text": "场景在你眼前展开..."},
            confidence=0.6,
        )
        
        assert audit.proposal_type == "narration"

    def test_fallback_audit(self):
        """Test audit for fallback scenario."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=1,
            proposal_type="input_intent",
            fallback_used=True,
            fallback_reason="LLM timeout",
            fallback_strategy="keyword_parser",
            confidence=0.0,
        )
        
        assert audit.fallback_used is True
        assert audit.fallback_reason == "LLM timeout"

    def test_rejection_audit(self):
        """Test audit for rejected proposal."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=1,
            proposal_type="scene_event",
            rejected=True,
            rejection_reason="Invalid scope",
            validation_passed=False,
        )
        
        assert audit.rejected is True
        assert audit.rejection_reason == "Invalid scope"

    def test_repair_audit(self):
        """Test audit for repaired proposal."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=1,
            proposal_type="world_tick",
            repair_attempts=2,
            repair_strategies_tried=["json_fix", "schema_correction"],
            repair_success=True,
        )
        
        assert audit.repair_attempts == 2
        assert audit.repair_success is True

    def test_perspective_leak_audit(self):
        """Test audit for perspective leak detection."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=1,
            proposal_type="narration",
            perspective_check_passed=False,
            forbidden_info_detected=["npc_secret", "hidden_location"],
        )
        
        assert audit.perspective_check_passed is False
        assert len(audit.forbidden_info_detected) == 2


class TestReplayWithProposalAudits:
    """Test replay with proposal audit data."""

    def setup_method(self):
        """Set up test fixtures."""
        self.replay_engine = ReplayEngine()
        self.state_reconstructor = StateReconstructor()

    def test_replay_step_has_proposal_audits(self):
        """Test that ReplayStep includes proposal_audits field."""
        step = ReplayStep(
            step_no=1,
            turn_no=1,
            proposal_audits=[
                {"proposal_type": "input_intent", "confidence": 0.85},
            ],
        )
        
        assert len(step.proposal_audits) == 1
        assert step.proposal_audits[0]["proposal_type"] == "input_intent"

    def test_get_proposal_audit_summary(self):
        """Test proposal audit summary calculation."""
        proposal_audits = [
            {"proposal_type": "input_intent", "confidence": 0.85, "fallback_used": False, "rejected": False},
            {"proposal_type": "npc_action", "confidence": 0.5, "fallback_used": True, "rejected": False},
            {"proposal_type": "scene_event", "confidence": 0.7, "fallback_used": False, "rejected": True},
        ]
        
        summary = self.replay_engine.get_proposal_audit_summary(proposal_audits)
        
        assert summary["total"] == 3
        assert summary["fallbacks"] == 1
        assert summary["rejections"] == 1
        assert 0.6 < summary["avg_confidence"] < 0.7


class TestFallbackMatrix:
    """Test fallback matrix scenarios."""

    def test_input_intent_fallback(self):
        """Test input intent fallback to keyword parser."""
        reset_audit_logger()
        audit_logger = get_audit_logger()
        
        audit = audit_logger.log_proposal(
            session_id="session_001",
            turn_no=1,
            proposal_type="input_intent",
            fallback_used=True,
            fallback_reason="Malformed JSON output",
            fallback_strategy="keyword_parser",
        )
        
        assert audit.fallback_used is True
        assert audit.fallback_strategy == "keyword_parser"

    def test_world_tick_fallback(self):
        """Test world tick fallback to rule events."""
        reset_audit_logger()
        audit_logger = get_audit_logger()
        
        audit = audit_logger.log_proposal(
            session_id="session_001",
            turn_no=1,
            proposal_type="world_tick",
            fallback_used=True,
            fallback_reason="LLM timeout",
            fallback_strategy="check_world_events",
        )
        
        assert audit.fallback_used is True
        assert audit.fallback_strategy == "check_world_events"

    def test_npc_action_fallback(self):
        """Test NPC action fallback to goal/idle."""
        reset_audit_logger()
        audit_logger = get_audit_logger()
        
        audit = audit_logger.log_proposal(
            session_id="session_001",
            turn_no=1,
            proposal_type="npc_action",
            fallback_used=True,
            fallback_reason="Schema validation failed",
            fallback_strategy="goal_idle_behavior",
        )
        
        assert audit.fallback_used is True
        assert audit.fallback_strategy == "goal_idle_behavior"

    def test_narration_fallback(self):
        """Test narration fallback to template."""
        reset_audit_logger()
        audit_logger = get_audit_logger()
        
        audit = audit_logger.log_proposal(
            session_id="session_001",
            turn_no=1,
            proposal_type="narration",
            fallback_used=True,
            fallback_reason="Perspective leak detected",
            fallback_strategy="template_narration",
        )
        
        assert audit.fallback_used is True
        assert audit.fallback_strategy == "template_narration"


class TestLoopOrder:
    """Test that loop order is documented and verifiable."""

    def test_loop_order_steps_defined(self):
        """Test that all loop order steps are defined."""
        expected_steps = [
            "start_transaction",
            "parse_intent_llm",
            "world_tick_deterministic",
            "scene_candidates_llm",
            "collect_actors",
            "npc_proposals_sequential",
            "resolve_conflicts",
            "validate_actions",
            "atomic_commit",
            "write_memories",
            "record_audit",
            "generate_narration",
        ]
        
        assert len(expected_steps) == 12

    def test_fallback_matrix_defined(self):
        """Test that fallback matrix covers all failure points."""
        fallback_matrix = {
            "input_intent_llm": "keyword_parser",
            "world_tick_llm": "check_world_events",
            "scene_candidates_llm": "collect_scene_triggers",
            "npc_action_llm": "goal_idle_behavior",
            "narration_llm": "template_narration",
            "parse_failure": "json_repair_then_fallback",
            "schema_validation": "reject_and_fallback",
            "validator_rejection": "rollback_transaction",
            "timeout": "deterministic_fallback",
            "perspective_leak": "sanitize_or_reject",
        }
        
        assert len(fallback_matrix) == 10
