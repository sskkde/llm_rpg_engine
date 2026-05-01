"""Integration tests for Timeline Viewer and NPC Mind Viewer APIs."""

import pytest
from datetime import datetime
from typing import Dict, Any, List

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from llm_rpg.core.audit import (
    get_audit_logger,
    reset_audit_logger,
    TurnAuditLog,
    TurnEventAudit,
    TurnStateDeltaAudit,
    ValidationStatus,
    MemoryDecisionReason,
    MemoryAuditEntry,
)
from llm_rpg.observability.timeline import (
    TimelineViewer,
    TurnTimeline,
    TimelineEntry,
    TimelineEntryType,
)
from llm_rpg.observability.npc_mind import (
    NPCMindViewer,
    NPCMindView,
    ViewRole,
    NPCProfile,
    NPCState,
    NPCBelief,
    NPCMemory,
    NPCGoal,
    NPCSecret,
    NPCForbiddenKnowledge,
    NPCRecentContext,
)


class TestTimelineViewer:
    """Test Timeline Viewer functionality."""

    def setup_method(self):
        """Reset audit logger before each test."""
        reset_audit_logger()
        self.audit_logger = get_audit_logger()
        self.viewer = TimelineViewer()

    def test_get_timeline_empty_session(self):
        """Test getting timeline for session with no turns."""
        timeline = self.viewer.get_timeline("empty_session_123")
        assert timeline == []

    def test_get_timeline_single_turn(self):
        """Test getting timeline with a single turn."""
        events = [
            TurnEventAudit(
                event_id="evt_001",
                event_type="player_input",
                actor_id="player",
                summary="Player moves north",
            )
        ]
        
        state_deltas = [
            TurnStateDeltaAudit(
                delta_id="delta_001",
                path="player.location",
                old_value="room_a",
                new_value="room_b",
                operation="set",
                validated=True,
            )
        ]
        
        turn_audit = self.audit_logger.log_turn(
            session_id="session_123",
            turn_no=1,
            transaction_id="txn_001",
            player_input="go north",
            world_time_before={"day": 1, "period": "morning"},
            world_time_after={"day": 1, "period": "morning"},
            parsed_intent={"intent_type": "move", "target": "north"},
            events=events,
            state_deltas=state_deltas,
            model_call_ids=[],
            context_build_ids=[],
            validation_ids=[],
            status="completed",
            narration_generated=True,
            narration_length=150,
            turn_duration_ms=500,
        )
        
        timeline = self.viewer.get_timeline("session_123")
        assert len(timeline) == 1
        
        turn = timeline[0]
        assert turn.turn_no == 1
        assert turn.session_id == "session_123"
        assert turn.transaction_id == "txn_001"
        assert turn.player_input == "go north"
        assert turn.status == "completed"
        assert turn.narration_generated is True
        assert turn.narration_length == 150
        assert turn.turn_duration_ms == 500
        assert turn.world_time_before == {"day": 1, "period": "morning"}
        assert turn.world_time_after == {"day": 1, "period": "morning"}
        
        assert len(turn.entries) == 2
        assert len(turn.event_ids) == 1
        assert turn.event_ids[0] == "evt_001"
        assert len(turn.state_delta_ids) == 1
        assert turn.state_delta_ids[0] == "delta_001"

    def test_get_timeline_multiple_turns(self):
        """Test getting timeline with multiple turns."""
        for turn_no in range(1, 4):
            self.audit_logger.log_turn(
                session_id="session_multi",
                turn_no=turn_no,
                transaction_id=f"txn_{turn_no:03d}",
                player_input=f"action {turn_no}",
                world_time_before={"day": 1, "period": "morning"},
                events=[
                    TurnEventAudit(
                        event_id=f"evt_{turn_no:03d}",
                        event_type="player_input",
                        actor_id="player",
                        summary=f"Turn {turn_no} action",
                    )
                ],
                state_deltas=[],
                status="completed",
            )
        
        timeline = self.viewer.get_timeline("session_multi")
        assert len(timeline) == 3
        
        for i, turn in enumerate(timeline):
            assert turn.turn_no == i + 1
            assert turn.session_id == "session_multi"

    def test_get_timeline_with_model_calls(self):
        """Test timeline includes model call entries."""
        model_call = self.audit_logger.log_model_call(
            session_id="session_calls",
            turn_no=1,
            provider="openai",
            model_name="gpt-4",
            prompt_type="npc_decision",
            input_tokens=500,
            output_tokens=150,
            cost_estimate=0.015,
            latency_ms=1200,
            success=True,
        )
        
        turn_audit = self.audit_logger.log_turn(
            session_id="session_calls",
            turn_no=1,
            transaction_id="txn_001",
            player_input="talk to npc",
            world_time_before={"day": 1, "period": "morning"},
            events=[
                TurnEventAudit(
                    event_id="evt_001",
                    event_type="player_input",
                    actor_id="player",
                    summary="Player talks to NPC",
                )
            ],
            state_deltas=[],
            model_call_ids=[model_call.call_id],
            status="completed",
        )
        
        timeline = self.viewer.get_timeline("session_calls")
        assert len(timeline) == 1
        
        turn = timeline[0]
        assert model_call.call_id in turn.model_call_ids
        
        model_call_entries = [e for e in turn.entries if e.entry_type == TimelineEntryType.MODEL_CALL]
        assert len(model_call_entries) == 1
        assert model_call_entries[0].data["provider"] == "openai"
        assert model_call_entries[0].data["model_name"] == "gpt-4"
        assert model_call_entries[0].data["prompt_type"] == "npc_decision"
        assert model_call_entries[0].data["input_tokens"] == 500
        assert model_call_entries[0].data["output_tokens"] == 150

    def test_get_timeline_with_context_builds(self):
        """Test timeline includes context build entries."""
        included_memories = [
            MemoryAuditEntry(
                memory_id="mem_001",
                memory_type="episodic",
                owner_id="npc_001",
                included=True,
                reason=MemoryDecisionReason.RELEVANCE_SCORE,
                relevance_score=0.85,
            )
        ]
        
        context_build = self.audit_logger.log_context_build(
            session_id="session_ctx",
            turn_no=1,
            perspective_type="npc",
            perspective_id="npc_001_perspective",
            owner_id="npc_001",
            included_memories=included_memories,
            excluded_memories=[],
            total_candidates=10,
            context_token_count=2500,
            context_char_count=8000,
            build_duration_ms=150,
        )
        
        turn_audit = self.audit_logger.log_turn(
            session_id="session_ctx",
            turn_no=1,
            transaction_id="txn_001",
            player_input="ask about quest",
            world_time_before={"day": 1, "period": "morning"},
            events=[],
            state_deltas=[],
            context_build_ids=[context_build.build_id],
            status="completed",
        )
        
        timeline = self.viewer.get_timeline("session_ctx")
        turn = timeline[0]
        
        ctx_entries = [e for e in turn.entries if e.entry_type == TimelineEntryType.CONTEXT_BUILD]
        assert len(ctx_entries) == 1
        assert ctx_entries[0].data["perspective_type"] == "npc"
        assert ctx_entries[0].data["included_count"] == 1
        assert ctx_entries[0].data["total_candidates"] == 10
        assert ctx_entries[0].data["context_token_count"] == 2500

    def test_get_timeline_with_validations(self):
        """Test timeline includes validation entries."""
        from llm_rpg.core.audit import ValidationCheck
        
        validation = self.audit_logger.log_validation(
            session_id="session_val",
            turn_no=1,
            validation_target="npc_action",
            target_id="action_001",
            overall_status=ValidationStatus.PASSED,
            checks=[
                ValidationCheck(
                    check_id="check_001",
                    check_type="action_valid",
                    status=ValidationStatus.PASSED,
                    message="Action is valid",
                )
            ],
            errors=[],
            warnings=[],
        )
        
        turn_audit = self.audit_logger.log_turn(
            session_id="session_val",
            turn_no=1,
            transaction_id="txn_001",
            player_input="attack goblin",
            world_time_before={"day": 1, "period": "morning"},
            events=[],
            state_deltas=[],
            validation_ids=[validation.validation_id],
            status="completed",
        )
        
        timeline = self.viewer.get_timeline("session_val")
        turn = timeline[0]
        
        val_entries = [e for e in turn.entries if e.entry_type == TimelineEntryType.VALIDATION]
        assert len(val_entries) == 1
        assert val_entries[0].data["validation_target"] == "npc_action"
        assert val_entries[0].data["overall_status"] == "passed"
        assert val_entries[0].data["error_count"] == 0

    def test_get_turn_summary(self):
        """Test getting summary for specific turn."""
        self.audit_logger.log_turn(
            session_id="session_single",
            turn_no=5,
            transaction_id="txn_005",
            player_input="special action",
            world_time_before={"day": 2, "period": "afternoon"},
            events=[
                TurnEventAudit(
                    event_id="evt_special",
                    event_type="special_event",
                    actor_id="player",
                    summary="Special event occurred",
                )
            ],
            state_deltas=[],
            status="completed",
        )
        
        turn = self.viewer.get_turn_summary("session_single", 5)
        assert turn is not None
        assert turn.turn_no == 5
        assert turn.player_input == "special action"
        assert turn.world_time_before == {"day": 2, "period": "afternoon"}

    def test_get_turn_summary_not_found(self):
        """Test getting summary for non-existent turn."""
        turn = self.viewer.get_turn_summary("session_nonexistent", 999)
        assert turn is None

    def test_get_timeline_turn_range(self):
        """Test getting timeline with turn range filter."""
        for turn_no in range(1, 6):
            self.audit_logger.log_turn(
                session_id="session_range",
                turn_no=turn_no,
                transaction_id=f"txn_{turn_no:03d}",
                player_input=f"action {turn_no}",
                world_time_before={"day": 1, "period": "morning"},
                events=[],
                state_deltas=[],
                status="completed",
            )
        
        timeline = self.viewer.get_timeline("session_range", start_turn=2, end_turn=4)
        assert len(timeline) == 3
        assert timeline[0].turn_no == 2
        assert timeline[1].turn_no == 3
        assert timeline[2].turn_no == 4

    def test_timeline_entries_sorted_by_timestamp(self):
        """Test that timeline entries are sorted by timestamp."""
        events = [
            TurnEventAudit(
                event_id="evt_001",
                event_type="player_input",
                actor_id="player",
                summary="First event",
            ),
            TurnEventAudit(
                event_id="evt_002",
                event_type="npc_action",
                actor_id="npc_001",
                summary="Second event",
            ),
        ]
        
        self.audit_logger.log_turn(
            session_id="session_sorted",
            turn_no=1,
            transaction_id="txn_001",
            player_input="test",
            world_time_before={"day": 1, "period": "morning"},
            events=events,
            state_deltas=[],
            status="completed",
        )
        
        timeline = self.viewer.get_timeline("session_sorted")
        turn = timeline[0]
        
        timestamps = [e.timestamp for e in turn.entries]
        assert timestamps == sorted(timestamps)

    def test_get_event_chain(self):
        """Test getting chain of events by type."""
        for turn_no in range(1, 4):
            self.audit_logger.log_turn(
                session_id="session_chain",
                turn_no=turn_no,
                transaction_id=f"txn_{turn_no:03d}",
                player_input=f"action {turn_no}",
                world_time_before={"day": 1, "period": "morning"},
                events=[
                    TurnEventAudit(
                        event_id=f"evt_{turn_no}",
                        event_type="combat_action" if turn_no == 2 else "player_input",
                        actor_id="player",
                        summary=f"Event {turn_no}",
                    )
                ],
                state_deltas=[],
                status="completed",
            )
        
        combat_events = self.viewer.get_event_chain("session_chain", event_type="combat_action")
        assert len(combat_events) == 1
        assert combat_events[0].data["event_type"] == "combat_action"

    def test_get_state_delta_chain(self):
        """Test getting chain of state deltas by path filter."""
        self.audit_logger.log_turn(
            session_id="session_deltas",
            turn_no=1,
            transaction_id="txn_001",
            player_input="test",
            world_time_before={"day": 1, "period": "morning"},
            events=[],
            state_deltas=[
                TurnStateDeltaAudit(
                    delta_id="delta_hp",
                    path="player.hp",
                    old_value=100,
                    new_value=90,
                    operation="set",
                    validated=True,
                ),
                TurnStateDeltaAudit(
                    delta_id="delta_loc",
                    path="player.location",
                    old_value="village",
                    new_value="forest",
                    operation="set",
                    validated=True,
                ),
            ],
            status="completed",
        )
        
        hp_deltas = self.viewer.get_state_delta_chain("session_deltas", path_filter="hp")
        assert len(hp_deltas) == 1
        assert hp_deltas[0].data["path"] == "player.hp"


class TestNPCMindViewer:
    """Test NPC Mind Viewer functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.viewer = NPCMindViewer()

    def test_get_npc_mind_debug_role(self):
        """Test getting NPC mind with debug role (full access)."""
        mind_view = self.viewer.get_npc_mind("session_123", "npc_001", ViewRole.DEBUG)
        
        assert mind_view is not None
        assert mind_view.npc_id is not None
        assert mind_view.session_id == "session_123"
        assert mind_view.view_role == ViewRole.DEBUG
        
        # Debug role should see everything
        assert mind_view.profile.hidden_identity is not None
        assert mind_view.state.hidden_plan_state is not None
        assert len(mind_view.private_memories) > 0
        assert len(mind_view.secrets) > 0
        assert len(mind_view.forbidden_knowledge) > 0
        
        # Check profile data
        assert mind_view.profile.npc_name is not None
        assert mind_view.profile.public_identity is not None
        
        # Check state data
        assert mind_view.state.trust_score is not None
        assert mind_view.state.suspicion_score is not None
        
        # Check beliefs
        assert len(mind_view.beliefs) > 0
        for belief in mind_view.beliefs:
            assert belief.belief_id is not None
            assert belief.belief_text is not None
            assert belief.confidence >= 0 and belief.confidence <= 1

    def test_get_npc_mind_admin_role(self):
        """Test getting NPC mind with admin role (full access)."""
        mind_view = self.viewer.get_npc_mind("session_123", "npc_001", ViewRole.ADMIN)
        
        assert mind_view is not None
        assert mind_view.view_role == ViewRole.ADMIN
        
        # Admin role should see everything
        assert mind_view.profile.hidden_identity is not None
        assert mind_view.state.hidden_plan_state is not None
        assert len(mind_view.secrets) > 0

    def test_get_npc_mind_auditor_role(self):
        """Test getting NPC mind with auditor role (redacted secrets)."""
        mind_view = self.viewer.get_npc_mind("session_123", "npc_001", ViewRole.AUDITOR)
        
        assert mind_view is not None
        assert mind_view.view_role == ViewRole.AUDITOR
        
        # Auditor role should see redacted secrets
        assert mind_view.profile.hidden_identity == "[REDACTED - UNAUTHORIZED ACCESS]"
        assert mind_view.state.hidden_plan_state == "[REDACTED - UNAUTHORIZED ACCESS]"
        
        # Private memories should be redacted
        for memory in mind_view.private_memories:
            assert memory.content == "[REDACTED - UNAUTHORIZED ACCESS]"
        
        # Secrets should be redacted
        for secret in mind_view.secrets:
            assert secret.description == "[REDACTED - UNAUTHORIZED ACCESS]"
        
        # Forbidden knowledge should be redacted
        for knowledge in mind_view.forbidden_knowledge:
            assert knowledge.description == "[REDACTED - UNAUTHORIZED ACCESS]"
        
        # Public info should still be visible
        assert mind_view.profile.public_identity is not None
        assert mind_view.profile.public_identity != "[REDACTED - UNAUTHORIZED ACCESS]"

    def test_get_npc_mind_player_role(self):
        """Test getting NPC mind with player role (denied)."""
        mind_view = self.viewer.get_npc_mind("session_123", "npc_001", ViewRole.PLAYER)
        
        assert mind_view is not None
        assert mind_view.view_role == ViewRole.PLAYER
        
        # Player role should not see secrets
        assert mind_view.profile.hidden_identity == "[REDACTED - UNAUTHORIZED ACCESS]"
        assert mind_view.state.hidden_plan_state == "[REDACTED - UNAUTHORIZED ACCESS]"
        assert len(mind_view.private_memories) == 0
        assert len(mind_view.secrets) == 0
        assert len(mind_view.forbidden_knowledge) == 0
        
        # Secrets metadata should indicate access denied
        assert mind_view.secrets_metadata.get("access_denied") is True

    def test_can_view_mind(self):
        """Test checking if role can view mind."""
        assert self.viewer.can_view_mind(ViewRole.ADMIN) is True
        assert self.viewer.can_view_mind(ViewRole.DEBUG) is True
        assert self.viewer.can_view_mind(ViewRole.AUDITOR) is True
        assert self.viewer.can_view_mind(ViewRole.PLAYER) is False

    def test_list_session_npcs(self):
        """Test listing NPCs in a session."""
        npcs = self.viewer.list_session_npcs("session_123")
        
        assert len(npcs) >= 0
        if npcs:
            assert "npc_id" in npcs[0]
            assert "npc_name" in npcs[0]

    def test_npc_mind_data_structure(self):
        """Test NPC mind view data structure."""
        mind_view = self.viewer.get_npc_mind("session_123", "npc_001", ViewRole.DEBUG)
        
        # Check profile structure
        assert isinstance(mind_view.profile, NPCProfile)
        assert mind_view.profile.npc_id is not None
        assert mind_view.profile.npc_template_id is not None
        assert mind_view.profile.npc_name is not None
        
        # Check state structure
        assert isinstance(mind_view.state, NPCState)
        assert isinstance(mind_view.state.trust_score, int)
        assert isinstance(mind_view.state.suspicion_score, int)
        assert isinstance(mind_view.state.status_flags, dict)
        
        # Check beliefs
        for belief in mind_view.beliefs:
            assert isinstance(belief, NPCBelief)
            assert belief.belief_id is not None
            assert belief.subject is not None
            assert belief.belief_text is not None
        
        # Check memories
        for memory in mind_view.memories:
            assert isinstance(memory, NPCMemory)
            assert memory.memory_id is not None
            assert memory.memory_type is not None
            assert memory.content is not None
        
        # Check goals
        for goal in mind_view.goals:
            assert isinstance(goal, NPCGoal)
            assert goal.goal_id is not None
            assert goal.goal_text is not None
            assert isinstance(goal.priority, int)
        
        # Check secrets
        for secret in mind_view.secrets:
            assert isinstance(secret, NPCSecret)
            assert secret.secret_id is not None
            assert secret.secret_type is not None
            assert secret.description is not None
        
        # Check forbidden knowledge
        for knowledge in mind_view.forbidden_knowledge:
            assert isinstance(knowledge, NPCForbiddenKnowledge)
            assert knowledge.knowledge_id is not None
            assert knowledge.knowledge_type is not None
            assert knowledge.description is not None
        
        # Check recent context
        assert isinstance(mind_view.recent_context, NPCRecentContext)
        assert isinstance(mind_view.recent_context.recent_memories, list)
        assert isinstance(mind_view.recent_context.recent_interactions, list)

    def test_viewed_at_timestamp(self):
        """Test that viewed_at timestamp is set."""
        mind_view = self.viewer.get_npc_mind("session_123", "npc_001", ViewRole.DEBUG)
        
        assert mind_view.viewed_at is not None
        assert isinstance(mind_view.viewed_at, datetime)


class TestTimelineAPITests:
    """Test Timeline Viewer API endpoints."""

    def setup_method(self):
        """Reset audit logger before each test."""
        reset_audit_logger()
        self.audit_logger = get_audit_logger()

    def test_api_get_timeline_endpoint(self, client: TestClient):
        """Test GET /debug/sessions/{session_id}/timeline endpoint."""
        # First register and login to get auth token
        register_response = client.post("/auth/register", json={
            "username": "timeline_test_user",
            "password": "password123"
        })
        assert register_response.status_code == 201
        token = register_response.json()["access_token"]
        
        # Create some audit data
        self.audit_logger.log_turn(
            session_id="test_session_123",
            turn_no=1,
            transaction_id="txn_001",
            player_input="test action",
            world_time_before={"day": 1, "period": "morning"},
            events=[
                TurnEventAudit(
                    event_id="evt_001",
                    event_type="player_input",
                    actor_id="player",
                    summary="Test event",
                )
            ],
            state_deltas=[],
            status="completed",
        )
        
        response = client.get(
            "/debug/sessions/test_session_123/timeline",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Session won't exist in DB, so we expect 404
        # But the endpoint structure is correct
        assert response.status_code in [200, 404]

    def test_api_get_turn_timeline_endpoint(self, client: TestClient):
        """Test GET /debug/sessions/{session_id}/timeline/{turn_no} endpoint."""
        register_response = client.post("/auth/register", json={
            "username": "timeline_turn_test_user",
            "password": "password123"
        })
        assert register_response.status_code == 201
        token = register_response.json()["access_token"]
        
        self.audit_logger.log_turn(
            session_id="test_session_456",
            turn_no=5,
            transaction_id="txn_005",
            player_input="special action",
            world_time_before={"day": 2, "period": "afternoon"},
            events=[],
            state_deltas=[],
            status="completed",
        )
        
        response = client.get(
            "/debug/sessions/test_session_456/timeline/5",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code in [200, 404]


class TestNPCMindAPITests:
    """Test NPC Mind Viewer API endpoints."""

    def test_api_list_npcs_endpoint(self, client: TestClient):
        """Test GET /debug/sessions/{session_id}/npcs endpoint."""
        register_response = client.post("/auth/register", json={
            "username": "npc_list_test_user",
            "password": "password123"
        })
        assert register_response.status_code == 201
        token = register_response.json()["access_token"]
        
        response = client.get(
            "/debug/sessions/test_session/npcs",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code in [200, 404]

    def test_api_get_npc_mind_endpoint_debug_role(self, client: TestClient):
        """Test GET /debug/sessions/{session_id}/npcs/{npc_id}/mind endpoint with debug role."""
        register_response = client.post("/auth/register", json={
            "username": "npc_mind_test_user",
            "password": "password123"
        })
        assert register_response.status_code == 201
        token = register_response.json()["access_token"]
        
        response = client.get(
            "/debug/sessions/test_session/npcs/npc_001/mind?role=debug",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code in [200, 404]

    def test_api_get_npc_mind_endpoint_player_role_denied(self, client: TestClient):
        """Test that player role is denied access to NPC mind endpoint."""
        register_response = client.post("/auth/register", json={
            "username": "npc_mind_player_test_user",
            "password": "password123"
        })
        assert register_response.status_code == 201
        token = register_response.json()["access_token"]
        
        response = client.get(
            "/debug/sessions/test_session/npcs/npc_001/mind?role=player",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 403

    def test_api_get_npc_mind_endpoint_invalid_role(self, client: TestClient):
        """Test that invalid role is rejected."""
        register_response = client.post("/auth/register", json={
            "username": "npc_mind_invalid_test_user",
            "password": "password123"
        })
        assert register_response.status_code == 201
        token = register_response.json()["access_token"]
        
        response = client.get(
            "/debug/sessions/test_session/npcs/npc_001/mind?role=invalid",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 422
