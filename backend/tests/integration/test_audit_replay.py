"""Integration tests for audit logging and replay functionality."""

import pytest
from datetime import datetime
from typing import Dict, Any, List

from llm_rpg.core.audit import (
    get_audit_logger,
    reset_audit_logger,
    AuditLogger,
    AuditStore,
    ModelCallLog,
    ContextBuildAudit,
    ValidationResultAudit,
    TurnAuditLog,
    ErrorLogEntry,
    MemoryAuditEntry,
    ValidationCheck,
    ValidationStatus,
    ErrorSeverity,
    MemoryDecisionReason,
    TurnStateDeltaAudit,
    TurnEventAudit,
    ProposalAuditEntry,
)
from llm_rpg.core.replay import (
    get_replay_store,
    reset_replay_store,
    ReplayStore,
    ReplayEngine,
    ReplayResult,
    ReplayEvent,
    ReplayPerspective,
    StateSnapshot,
    ReplayError,
    StateReconstructor,
    StateDelta,
)


class TestAuditLogging:
    """Test audit logging functionality."""

    def setup_method(self):
        """Reset audit logger before each test."""
        reset_audit_logger()
        self.audit_logger = get_audit_logger()
        self.store = self.audit_logger.get_store()

    def test_log_model_call_success(self):
        """Test logging a successful model call."""
        log = self.audit_logger.log_model_call(
            session_id="session_123",
            turn_no=5,
            provider="openai",
            model_name="gpt-4",
            prompt_type="npc_decision",
            input_tokens=500,
            output_tokens=150,
            cost_estimate=0.015,
            latency_ms=1200,
            success=True,
        )

        assert log.call_id is not None
        assert log.session_id == "session_123"
        assert log.turn_no == 5
        assert log.provider == "openai"
        assert log.model_name == "gpt-4"
        assert log.prompt_type == "npc_decision"
        assert log.input_tokens == 500
        assert log.output_tokens == 150
        assert log.total_tokens == 650
        assert log.cost_estimate == 0.015
        assert log.latency_ms == 1200
        assert log.success is True
        assert log.error_message is None

        # Verify stored
        stored = self.store.get_model_call(log.call_id)
        assert stored is not None
        assert stored.call_id == log.call_id

    def test_log_model_call_failure(self):
        """Test logging a failed model call."""
        log = self.audit_logger.log_model_call(
            session_id="session_123",
            turn_no=5,
            provider="openai",
            model_name="gpt-4",
            prompt_type="narration",
            input_tokens=1000,
            output_tokens=0,
            cost_estimate=0.0,
            latency_ms=30000,
            success=False,
            error_message="Timeout after 30 seconds",
        )

        assert log.success is False
        assert log.error_message == "Timeout after 30 seconds"
        assert log.output_tokens == 0

    def test_log_context_build_with_memory_decisions(self):
        """Test logging context build with included/excluded memories."""
        included_memories = [
            MemoryAuditEntry(
                memory_id="mem_001",
                memory_type="episodic",
                owner_id="npc_001",
                included=True,
                reason=MemoryDecisionReason.RELEVANCE_SCORE,
                relevance_score=0.85,
                importance_score=0.7,
                notes="Highly relevant to current scene",
            ),
            MemoryAuditEntry(
                memory_id="mem_002",
                memory_type="semantic",
                owner_id="npc_001",
                included=True,
                reason=MemoryDecisionReason.ENTITY_VISIBLE,
                relevance_score=0.6,
                notes="Entity is visible to NPC",
            ),
        ]

        excluded_memories = [
            MemoryAuditEntry(
                memory_id="mem_003",
                memory_type="episodic",
                owner_id="npc_001",
                included=False,
                reason=MemoryDecisionReason.PERSPECTIVE_FILTERED,
                relevance_score=0.3,
                perspective_filter_applied=True,
                notes="Filtered by perspective - NPC cannot know this",
            ),
            MemoryAuditEntry(
                memory_id="mem_004",
                memory_type="secret",
                owner_id="npc_001",
                included=False,
                reason=MemoryDecisionReason.FORBIDDEN_KNOWLEDGE,
                forbidden_knowledge_flag=True,
                notes="Forbidden knowledge - would break narrative",
            ),
        ]

        audit = self.audit_logger.log_context_build(
            session_id="session_123",
            turn_no=5,
            perspective_type="npc",
            perspective_id="npc_001_perspective",
            owner_id="npc_001",
            included_memories=included_memories,
            excluded_memories=excluded_memories,
            total_candidates=10,
            context_token_count=2500,
            context_char_count=8000,
            build_duration_ms=150,
        )

        assert audit.build_id is not None
        assert audit.session_id == "session_123"
        assert audit.turn_no == 5
        assert audit.perspective_type == "npc"
        assert audit.included_count == 2
        assert audit.excluded_count == 2
        assert audit.total_candidates == 10
        assert len(audit.included_memories) == 2
        assert len(audit.excluded_memories) == 2

        # Verify reasons are recorded
        assert audit.included_memories[0].reason == MemoryDecisionReason.RELEVANCE_SCORE
        assert audit.excluded_memories[0].reason == MemoryDecisionReason.PERSPECTIVE_FILTERED
        assert audit.excluded_memories[1].reason == MemoryDecisionReason.FORBIDDEN_KNOWLEDGE

        # Verify stored
        stored = self.store.get_context_build(audit.build_id)
        assert stored is not None
        assert stored.build_id == audit.build_id

    def test_log_validation_result(self):
        """Test logging validation results with checks."""
        checks = [
            ValidationCheck(
                check_id="check_001",
                check_type="action_valid",
                status=ValidationStatus.PASSED,
                message="Action is valid",
            ),
            ValidationCheck(
                check_id="check_002",
                check_type="state_delta_valid",
                status=ValidationStatus.PASSED,
                message="State delta is valid",
            ),
            ValidationCheck(
                check_id="check_003",
                check_type="perspective_check",
                status=ValidationStatus.WARNING,
                message="NPC may have limited visibility",
            ),
        ]

        audit = self.audit_logger.log_validation(
            session_id="session_123",
            turn_no=5,
            validation_target="npc_action",
            target_id="action_001",
            overall_status=ValidationStatus.PASSED,
            checks=checks,
            errors=[],
            warnings=["NPC may have limited visibility"],
            transaction_id="txn_001",
        )

        assert audit.validation_id is not None
        assert audit.overall_status == ValidationStatus.PASSED
        assert audit.error_count == 0
        assert audit.warning_count == 1
        assert len(audit.checks) == 3
        assert audit.checks[0].status == ValidationStatus.PASSED
        assert audit.checks[2].status == ValidationStatus.WARNING

        # Verify stored
        stored = self.store.get_validation(audit.validation_id)
        assert stored is not None

    def test_log_validation_failure(self):
        """Test logging failed validation."""
        checks = [
            ValidationCheck(
                check_id="check_001",
                check_type="action_valid",
                status=ValidationStatus.FAILED,
                message="Invalid action type",
                details={"action_type": "invalid_type"},
            ),
        ]

        audit = self.audit_logger.log_validation(
            session_id="session_123",
            turn_no=5,
            validation_target="player_action",
            target_id="action_002",
            overall_status=ValidationStatus.FAILED,
            checks=checks,
            errors=["Invalid action type: invalid_type"],
            warnings=[],
        )

        assert audit.overall_status == ValidationStatus.FAILED
        assert audit.error_count == 1
        assert audit.warning_count == 0
        assert len(audit.errors) == 1

    def test_log_complete_turn(self):
        """Test logging a complete turn with all components."""
        events = [
            TurnEventAudit(
                event_id="evt_001",
                event_type="player_input",
                actor_id="player",
                summary="Player moves north",
            ),
            TurnEventAudit(
                event_id="evt_002",
                event_type="npc_action",
                actor_id="npc_001",
                summary="NPC follows player",
            ),
        ]

        state_deltas = [
            TurnStateDeltaAudit(
                delta_id="delta_001",
                path="player.location",
                old_value="room_a",
                new_value="room_b",
                operation="set",
                validated=True,
            ),
            TurnStateDeltaAudit(
                delta_id="delta_002",
                path="npc_001.location",
                old_value="room_a",
                new_value="room_b",
                operation="set",
                validated=True,
            ),
        ]

        audit = self.audit_logger.log_turn(
            session_id="session_123",
            turn_no=5,
            transaction_id="txn_001",
            player_input="go north",
            world_time_before={"day": 1, "period": "morning"},
            world_time_after={"day": 1, "period": "afternoon"},
            parsed_intent={"intent_type": "move", "target": "north"},
            events=events,
            state_deltas=state_deltas,
            model_call_ids=["call_001", "call_002"],
            context_build_ids=["ctx_001"],
            validation_ids=["val_001"],
            status="completed",
            narration_generated=True,
            narration_length=250,
            turn_duration_ms=2000,
        )

        assert audit.audit_id is not None
        assert audit.session_id == "session_123"
        assert audit.turn_no == 5
        assert audit.transaction_id == "txn_001"
        assert audit.player_input == "go north"
        assert len(audit.events) == 2
        assert len(audit.state_deltas) == 2
        assert len(audit.model_call_ids) == 2
        assert len(audit.context_build_ids) == 1
        assert len(audit.validation_ids) == 1
        assert audit.narration_generated is True
        assert audit.narration_length == 250
        assert audit.status == "completed"

        # Verify stored and retrievable by turn
        stored = self.store.get_turn_audit(audit.audit_id)
        assert stored is not None

        by_turn = self.store.get_turn_audit_by_turn("session_123", 5)
        assert by_turn is not None
        assert by_turn.audit_id == audit.audit_id

    def test_log_error(self):
        """Test logging errors."""
        error = self.audit_logger.log_error(
            error_type="ValidationError",
            message="Action validation failed",
            severity=ErrorSeverity.ERROR,
            session_id="session_123",
            turn_no=5,
            component="validator",
            operation="validate_action",
            transaction_id="txn_001",
            context={"action_id": "action_001"},
            recovered=True,
            recovery_action="rolled_back_transaction",
        )

        assert error.error_id is not None
        assert error.severity == ErrorSeverity.ERROR
        assert error.error_type == "ValidationError"
        assert error.message == "Action validation failed"
        assert error.component == "validator"
        assert error.operation == "validate_action"
        assert error.session_id == "session_123"
        assert error.turn_no == 5
        assert error.recovered is True
        assert error.recovery_action == "rolled_back_transaction"

        # Verify stored
        stored = self.store.get_error(error.error_id)
        assert stored is not None

    def test_log_critical_error(self):
        """Test logging critical errors."""
        error = self.audit_logger.log_error(
            error_type="SystemError",
            message="Database connection lost",
            severity=ErrorSeverity.CRITICAL,
            component="database",
            operation="commit_transaction",
            recovered=False,
        )

        assert error.severity == ErrorSeverity.CRITICAL
        assert error.recovered is False

    def test_error_stack_trace_sanitization(self):
        """Test that stack traces are sanitized to remove secrets."""
        stack_trace = """
        File "app.py", line 45, in call_api
            api_key = "sk-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz"
            password = "super_secret_password_123"
            headers = {"Authorization": "Bearer token_secret_value_here"}
            response = requests.post(url, headers=headers, api_key=api_key)
        """

        error = self.audit_logger.log_error(
            error_type="APIError",
            message="API call failed",
            severity=ErrorSeverity.ERROR,
            stack_trace=stack_trace,
        )

        # Verify secrets are redacted
        assert "sk-abc123" not in (error.stack_trace or "")
        assert "***REDACTED***" in (error.stack_trace or "")
        assert "super_secret_password_123" not in (error.stack_trace or "")
        assert "token_secret_value_here" not in (error.stack_trace or "")


class TestReplayFunctionality:
    """Test replay functionality."""

    def setup_method(self):
        """Reset replay store before each test."""
        reset_replay_store()
        self.replay_store = get_replay_store()
        self.replay_engine = self.replay_store.get_replay_engine()
        self.state_reconstructor = self.replay_store.get_state_reconstructor()

    def test_create_snapshot(self):
        """Test creating a state snapshot."""
        world_state = {"current_time": "Day 1 Morning", "weather": "sunny"}
        player_state = {"hp": 100, "location": "village"}
        npc_states = {
            "npc_001": {"name": "Villager", "mood": "friendly", "hidden_plan_state": "secret_plan"},
        }

        snapshot = self.replay_store.create_snapshot(
            session_id="session_123",
            turn_no=10,
            world_state=world_state,
            player_state=player_state,
            npc_states=npc_states,
            snapshot_type="checkpoint",
        )

        assert snapshot.snapshot_id is not None
        assert snapshot.session_id == "session_123"
        assert snapshot.turn_no == 10
        assert snapshot.world_state == world_state
        assert snapshot.player_state == player_state
        assert snapshot.npc_states == npc_states
        assert snapshot.snapshot_type == "checkpoint"

        # Verify retrievable
        stored = self.state_reconstructor.get_snapshot(snapshot.snapshot_id)
        assert stored is not None
        assert stored.snapshot_id == snapshot.snapshot_id

    def test_replay_from_snapshot_admin_perspective(self):
        """Test replay from snapshot with admin perspective (sees hidden info)."""
        # Create snapshot
        snapshot = self.replay_store.create_snapshot(
            session_id="session_123",
            turn_no=10,
            world_state={"current_time": "Day 1 Morning"},
            player_state={"hp": 100},
            npc_states={
                "npc_001": {
                    "name": "Villager",
                    "mood": "friendly",
                    "hidden_plan_state": "secret_plan_to_betray",
                    "secrets": ["knows about treasure"],
                },
            },
        )

        # Create events for replay
        events = [
            ReplayEvent(
                event_id="evt_011",
                event_type="player_input",
                turn_no=11,
                timestamp=datetime.now(),
                actor_id="player",
                summary="Player talks to villager",
                visible_to_player=True,
                data={
                    "raw_input": "talk to villager",
                    "state_deltas": [
                        {"path": "player.location", "old_value": "square", "new_value": "house", "operation": "set"},
                    ],
                },
            ),
            ReplayEvent(
                event_id="evt_012",
                event_type="npc_action",
                turn_no=11,
                timestamp=datetime.now(),
                actor_id="npc_001",
                summary="NPC reacts",
                visible_to_player=True,
            ),
        ]

        result = self.replay_engine.replay_from_snapshot(
            session_id="session_123",
            snapshot_id=snapshot.snapshot_id,
            target_turn=11,
            events=events,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.replay_id is not None
        assert result.session_id == "session_123"
        assert result.start_turn == 10
        assert result.end_turn == 11
        assert result.perspective == ReplayPerspective.ADMIN
        assert result.success is True
        assert len(result.steps) == 1

        # Admin should see hidden info
        final_state = result.final_state
        assert "npc_states" in final_state
        npc_data = final_state["npc_states"].get("npc_001", {})
        # Admin sees hidden plan state
        assert "hidden_plan_state" in npc_data
        assert npc_data["hidden_plan_state"] == "secret_plan_to_betray"

    def test_replay_from_snapshot_player_perspective(self):
        """Test replay from snapshot with player perspective (no hidden info)."""
        # Create snapshot with hidden info
        snapshot = self.replay_store.create_snapshot(
            session_id="session_123",
            turn_no=10,
            world_state={"current_time": "Day 1 Morning"},
            player_state={"hp": 100},
            npc_states={
                "npc_001": {
                    "name": "Villager",
                    "mood": "friendly",
                    "hidden_plan_state": "secret_plan_to_betray",
                    "secrets": ["knows about treasure"],
                    "forbidden_knowledge": ["true_nature_of_world"],
                },
            },
        )

        events = [
            ReplayEvent(
                event_id="evt_011",
                event_type="player_input",
                turn_no=11,
                timestamp=datetime.now(),
                actor_id="player",
                summary="Player talks to villager",
                visible_to_player=True,
                data={"raw_input": "talk to villager"},
            ),
        ]

        result = self.replay_engine.replay_from_snapshot(
            session_id="session_123",
            snapshot_id=snapshot.snapshot_id,
            target_turn=11,
            events=events,
            perspective=ReplayPerspective.PLAYER,
        )

        assert result.perspective == ReplayPerspective.PLAYER
        assert result.success is True

        # Player should NOT see hidden info
        final_state = result.final_state
        npc_data = final_state.get("npc_states", {}).get("npc_001", {})
        assert "hidden_plan_state" not in npc_data
        assert "secrets" not in npc_data
        assert "forbidden_knowledge" not in npc_data

        # But should see public info
        assert npc_data.get("name") == "Villager"
        assert npc_data.get("mood") == "friendly"

    def test_replay_from_snapshot_auditor_perspective(self):
        """Test replay from snapshot with auditor perspective (redacted hidden info)."""
        snapshot = self.replay_store.create_snapshot(
            session_id="session_123",
            turn_no=10,
            world_state={"current_time": "Day 1 Morning"},
            player_state={"hp": 100},
            npc_states={
                "npc_001": {
                    "name": "Villager",
                    "mood": "friendly",
                    "hidden_plan_state": "secret_plan_to_betray",
                },
            },
        )

        events = [
            ReplayEvent(
                event_id="evt_011",
                event_type="player_input",
                turn_no=11,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={},
            ),
        ]

        result = self.replay_engine.replay_from_snapshot(
            session_id="session_123",
            snapshot_id=snapshot.snapshot_id,
            target_turn=11,
            events=events,
            perspective=ReplayPerspective.AUDITOR,
        )

        assert result.perspective == ReplayPerspective.AUDITOR

        # Auditor should see redacted hidden info
        final_state = result.final_state
        npc_data = final_state.get("npc_states", {}).get("npc_001", {})
        assert "hidden_plan_state" in npc_data
        assert npc_data["hidden_plan_state"] == "[REDACTED - AUDITOR VIEW]"

    def test_replay_turn_range(self):
        """Test replaying a range of turns."""
        base_state = {
            "world_state": {"current_time": "Day 1 Morning"},
            "player_state": {"hp": 100, "location": "village"},
            "npc_states": {},
        }

        events = [
            ReplayEvent(
                event_id="evt_001",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={
                    "raw_input": "go north",
                    "state_deltas": [
                        {"path": "player_state.location", "old_value": "village", "new_value": "forest", "operation": "set"},
                    ],
                },
            ),
            ReplayEvent(
                event_id="evt_002",
                event_type="player_input",
                turn_no=2,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={
                    "raw_input": "search area",
                    "state_deltas": [
                        {"path": "player_state.items", "old_value": [], "new_value": ["stick"], "operation": "set"},
                    ],
                },
            ),
            ReplayEvent(
                event_id="evt_003",
                event_type="player_input",
                turn_no=3,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={
                    "raw_input": "rest",
                    "state_deltas": [
                        {"path": "player_state.hp", "old_value": 100, "new_value": 110, "operation": "set"},
                    ],
                },
            ),
        ]

        result = self.replay_engine.replay_turn_range(
            session_id="session_123",
            start_turn=1,
            end_turn=3,
            events=events,
            base_state=base_state,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.replay_id is not None
        assert result.start_turn == 1
        assert result.end_turn == 3
        assert result.total_steps == 3
        assert result.total_events == 3
        assert result.total_state_deltas == 3

        # Verify state progression
        final_state = result.final_state
        assert final_state["player_state"]["location"] == "forest"
        assert final_state["player_state"]["items"] == ["stick"]
        assert final_state["player_state"]["hp"] == 110

    def test_replay_state_continuity_check(self):
        """Test that replay verifies state continuity between steps."""
        base_state = {
            "player_state": {"hp": 100},
        }

        events = [
            ReplayEvent(
                event_id="evt_001",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={
                    "state_deltas": [
                        {"path": "player_state.hp", "old_value": 100, "new_value": 90, "operation": "set"},
                    ],
                },
            ),
        ]

        result = self.replay_engine.replay_turn_range(
            session_id="session_123",
            start_turn=1,
            end_turn=1,
            events=events,
            base_state=base_state,
            perspective=ReplayPerspective.ADMIN,
        )

        # Verify consistency
        report = self.replay_engine.verify_replay_consistency(result)
        assert report["consistent"] is True
        assert len(report["checks"]) > 0

    def test_replay_with_invalid_snapshot(self):
        """Test replay fails with invalid snapshot."""
        with pytest.raises(ReplayError) as exc_info:
            self.replay_engine.replay_from_snapshot(
                session_id="session_123",
                snapshot_id="invalid_snapshot_id",
                target_turn=11,
                events=[],
                perspective=ReplayPerspective.ADMIN,
            )

        assert "Snapshot not found" in str(exc_info.value)

    def test_state_comparison(self):
        """Test state comparison functionality."""
        expected = {
            "player": {"hp": 100, "location": "village"},
            "world": {"time": "morning"},
        }

        actual = {
            "player": {"hp": 90, "location": "village"},
            "world": {"time": "afternoon"},
        }

        differences = self.replay_engine.compare_states(expected, actual)

        assert len(differences) == 2

        # Check HP difference
        hp_diff = next((d for d in differences if d["path"] == "player.hp"), None)
        assert hp_diff is not None
        assert hp_diff["expected"] == 100
        assert hp_diff["actual"] == 90
        assert hp_diff["type"] == "value_mismatch"

        # Check time difference
        time_diff = next((d for d in differences if d["path"] == "world.time"), None)
        assert time_diff is not None
        assert time_diff["expected"] == "morning"
        assert time_diff["actual"] == "afternoon"

    def test_state_reconstruction_with_deltas(self):
        """Test state reconstruction from base state and deltas."""
        base_state = {
            "player": {"hp": 100, "location": "village", "items": []},
            "npcs": {
                "npc_001": {"mood": "neutral"},
            },
        }

        deltas = [
            StateDelta(path="player.hp", old_value=100, new_value=90, operation="set"),
            StateDelta(path="player.location", old_value="village", new_value="forest", operation="set"),
            StateDelta(path="player.items", old_value=None, new_value="sword", operation="add"),
            StateDelta(path="npcs.npc_001.mood", old_value="neutral", new_value="friendly", operation="set"),
        ]

        reconstructed = self.state_reconstructor.reconstruct_state(base_state, deltas)

        assert reconstructed["player"]["hp"] == 90
        assert reconstructed["player"]["location"] == "forest"
        assert "sword" in reconstructed["player"]["items"]
        assert reconstructed["npcs"]["npc_001"]["mood"] == "friendly"

    def test_get_replay_by_id(self):
        """Test retrieving replay by ID."""
        base_state = {"player_state": {"hp": 100}}

        result = self.replay_engine.replay_turn_range(
            session_id="session_123",
            start_turn=1,
            end_turn=1,
            events=[
                ReplayEvent(
                    event_id="evt_001",
                    event_type="player_input",
                    turn_no=1,
                    timestamp=datetime.now(),
                    visible_to_player=True,
                    data={},
                ),
            ],
            base_state=base_state,
            perspective=ReplayPerspective.ADMIN,
        )

        # Retrieve replay
        retrieved = self.replay_engine.get_replay(result.replay_id)
        assert retrieved is not None
        assert retrieved.replay_id == result.replay_id


class TestIntegrationAuditReplay:
    """Integration tests combining audit and replay."""

    def setup_method(self):
        """Reset both audit and replay systems."""
        reset_audit_logger()
        reset_replay_store()
        self.audit_logger = get_audit_logger()
        self.replay_store = get_replay_store()

    def test_turn_audit_with_replay_verification(self):
        """Test that turn audit data can be used with replay for verification."""
        # Create a snapshot
        snapshot = self.replay_store.create_snapshot(
            session_id="session_123",
            turn_no=10,
            world_state={"current_time": "Day 1 Morning"},
            player_state={"hp": 100, "location": "village"},
        )

        # Log a turn with state changes
        state_deltas = [
            TurnStateDeltaAudit(
                delta_id="delta_001",
                path="player.location",
                old_value="village",
                new_value="forest",
                operation="set",
                validated=True,
            ),
        ]

        turn_audit = self.audit_logger.log_turn(
            session_id="session_123",
            turn_no=11,
            transaction_id="txn_011",
            player_input="go to forest",
            world_time_before={"day": 1, "period": "morning"},
            world_time_after={"day": 1, "period": "afternoon"},
            state_deltas=state_deltas,
            status="completed",
        )

        # Create replay events based on turn audit
        events = [
            ReplayEvent(
                event_id="evt_011",
                event_type="player_input",
                turn_no=11,
                timestamp=datetime.now(),
                actor_id="player",
                summary="Player moves to forest",
                visible_to_player=True,
                data={
                    "raw_input": "go to forest",
                    "state_deltas": [
                        {"path": "player.location", "old_value": "village", "new_value": "forest", "operation": "set"},
                    ],
                },
            ),
        ]

        # Replay from snapshot
        result = self.replay_store.replay_from_snapshot(
            session_id="session_123",
            snapshot_id=snapshot.snapshot_id,
            target_turn=11,
            events=events,
            perspective=ReplayPerspective.ADMIN,
        )

        # Verify replay matches audit
        assert result.success is True
        assert len(result.steps) == 1
        assert result.steps[0].player_input == turn_audit.player_input

        # Verify state change was applied
        assert result.final_state["player"]["location"] == "forest"

    def test_model_call_failure_in_replay_context(self):
        """Test that model call failures are properly audited and don't break replay."""
        # Log a failed model call
        failed_call = self.audit_logger.log_model_call(
            session_id="session_123",
            turn_no=5,
            provider="openai",
            model_name="gpt-4",
            prompt_type="narration",
            input_tokens=1000,
            output_tokens=0,
            cost_estimate=0.0,
            latency_ms=30000,
            success=False,
            error_message="Rate limit exceeded",
        )

        # Verify the failed call is stored
        stored_call = self.audit_logger.get_store().get_model_call(failed_call.call_id)
        assert stored_call is not None
        assert stored_call.success is False
        assert stored_call.error_message == "Rate limit exceeded"

        # Create a snapshot and replay (model call failure shouldn't affect replay)
        snapshot = self.replay_store.create_snapshot(
            session_id="session_123",
            turn_no=4,
            world_state={"current_time": "Day 1"},
            player_state={"hp": 100},
        )

        events = [
            ReplayEvent(
                event_id="evt_005",
                event_type="player_input",
                turn_no=5,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={"raw_input": "test input"},
            ),
        ]

        result = self.replay_store.replay_from_snapshot(
            session_id="session_123",
            snapshot_id=snapshot.snapshot_id,
            target_turn=5,
            events=events,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.success is True


class TestProposalAudit:
    """Test proposal audit functionality."""

    def setup_method(self):
        """Reset audit logger before each test."""
        reset_audit_logger()
        self.audit_logger = get_audit_logger()
        self.store = self.audit_logger.get_store()

    def test_log_proposal_success(self):
        """Test logging a successful proposal."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=5,
            proposal_type="input_intent",
            prompt_template_id="intent_parse_v1",
            model_name="gpt-4",
            input_tokens=500,
            output_tokens=150,
            latency_ms=800,
            raw_output_preview='{"intent_type": "move", "target": "north"}',
            parsed_proposal={"intent_type": "move", "target": "north"},
            confidence=0.85,
        )

        assert audit.audit_id is not None
        assert audit.session_id == "session_001"
        assert audit.turn_no == 5
        assert audit.proposal_type == "input_intent"
        assert audit.prompt_template_id == "intent_parse_v1"
        assert audit.parse_success is True
        assert audit.validation_passed is True
        assert audit.fallback_used is False
        assert audit.confidence == 0.85

        stored = self.store.get_proposal_audit(audit.audit_id)
        assert stored is not None
        assert stored.audit_id == audit.audit_id

    def test_log_proposal_with_fallback(self):
        """Test logging a proposal that used fallback."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=5,
            proposal_type="npc_action",
            fallback_used=True,
            fallback_reason="LLM timeout after 30s",
            fallback_strategy="goal_idle_behavior",
            confidence=0.0,
        )

        assert audit.fallback_used is True
        assert audit.fallback_reason == "LLM timeout after 30s"
        assert audit.fallback_strategy == "goal_idle_behavior"
        assert audit.confidence == 0.0

    def test_log_proposal_with_rejection(self):
        """Test logging a rejected proposal."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=5,
            proposal_type="scene_event",
            rejected=True,
            rejection_reason="Invalid scene scope - global event not allowed",
            validation_errors=["Scene proposal cannot create global events"],
            validation_passed=False,
        )

        assert audit.rejected is True
        assert audit.rejection_reason == "Invalid scene scope - global event not allowed"
        assert len(audit.validation_errors) == 1
        assert audit.validation_passed is False

    def test_log_proposal_with_repair(self):
        """Test logging a proposal that required repair."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=5,
            proposal_type="world_tick",
            parse_success=False,
            repair_attempts=2,
            repair_strategies_tried=["json_fix", "schema_correction"],
            repair_success=True,
            raw_output_preview='{"time_delta": 1, "events": [}',
        )

        assert audit.parse_success is False
        assert audit.repair_attempts == 2
        assert len(audit.repair_strategies_tried) == 2
        assert audit.repair_success is True

    def test_log_proposal_with_perspective_check(self):
        """Test logging a proposal with perspective safety check."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=5,
            proposal_type="narration",
            perspective_check_passed=False,
            forbidden_info_detected=["npc_001_secret_identity", "hidden_treasure_location"],
            validation_errors=["Narration contains forbidden information"],
        )

        assert audit.perspective_check_passed is False
        assert len(audit.forbidden_info_detected) == 2
        assert "npc_001_secret_identity" in audit.forbidden_info_detected

    def test_get_proposal_audits_by_turn(self):
        """Test retrieving proposal audits by turn."""
        self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=5,
            proposal_type="input_intent",
        )
        self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=5,
            proposal_type="npc_action",
        )
        self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=6,
            proposal_type="scene_event",
        )

        turn_5_audits = self.store.get_proposal_audits_by_turn("session_001", 5)
        assert len(turn_5_audits) == 2

        turn_6_audits = self.store.get_proposal_audits_by_turn("session_001", 6)
        assert len(turn_6_audits) == 1

    def test_get_proposal_audits_by_type(self):
        """Test filtering proposal audits by type."""
        self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=5,
            proposal_type="input_intent",
        )
        self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=5,
            proposal_type="npc_action",
        )
        self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=6,
            proposal_type="input_intent",
        )

        intent_audits = self.store.get_proposal_audits_by_session(
            "session_001",
            proposal_type="input_intent",
        )
        assert len(intent_audits) == 2

        npc_audits = self.store.get_proposal_audits_by_session(
            "session_001",
            proposal_type="npc_action",
        )
        assert len(npc_audits) == 1

    def test_proposal_audit_committed_event_ids(self):
        """Test that committed event IDs are recorded."""
        audit = self.audit_logger.log_proposal(
            session_id="session_001",
            turn_no=5,
            proposal_type="scene_event",
            committed_event_ids=["evt_001", "evt_002", "evt_003"],
        )

        assert len(audit.committed_event_ids) == 3
        assert "evt_001" in audit.committed_event_ids
        assert "evt_002" in audit.committed_event_ids
        assert "evt_003" in audit.committed_event_ids


class TestReplayWithProposalAudits:
    """Test replay with proposal audit data."""

    def setup_method(self):
        """Reset both audit and replay systems."""
        reset_audit_logger()
        reset_replay_store()
        self.audit_logger = get_audit_logger()
        self.replay_store = get_replay_store()
        self.replay_engine = self.replay_store.get_replay_engine()

    def test_replay_with_proposal_audits_no_llm_recall(self):
        """Test that replay uses proposal audit data without re-calling LLM."""
        snapshot = self.replay_store.create_snapshot(
            session_id="session_001",
            turn_no=10,
            world_state={"current_time": "Day 1"},
            player_state={"hp": 100},
        )

        proposal_audits = {
            11: [
                {
                    "audit_id": "prop_001",
                    "proposal_type": "input_intent",
                    "parsed_proposal": {"intent_type": "move", "target": "north"},
                    "confidence": 0.85,
                    "fallback_used": False,
                },
                {
                    "audit_id": "prop_002",
                    "proposal_type": "npc_action",
                    "parsed_proposal": {"action_type": "idle"},
                    "confidence": 0.5,
                    "fallback_used": False,
                },
            ],
        }

        events = [
            ReplayEvent(
                event_id="evt_011",
                event_type="player_input",
                turn_no=11,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={"raw_input": "go north"},
            ),
        ]

        result = self.replay_engine.replay_with_proposal_audits(
            session_id="session_001",
            start_turn=11,
            end_turn=11,
            events=events,
            proposal_audits=proposal_audits,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.success is True
        assert len(result.steps) == 1
        assert len(result.steps[0].proposal_audits) == 2

    def test_get_proposal_audit_summary(self):
        """Test summarizing proposal audits for a turn."""
        proposal_audits = [
            {
                "proposal_type": "input_intent",
                "confidence": 0.85,
                "fallback_used": False,
                "rejected": False,
            },
            {
                "proposal_type": "npc_action",
                "confidence": 0.5,
                "fallback_used": True,
                "fallback_reason": "timeout",
                "rejected": False,
            },
            {
                "proposal_type": "scene_event",
                "confidence": 0.7,
                "fallback_used": False,
                "rejected": True,
                "rejection_reason": "invalid scope",
            },
        ]

        summary = self.replay_engine.get_proposal_audit_summary(proposal_audits)

        assert summary["total"] == 3
        assert summary["by_type"]["input_intent"] == 1
        assert summary["by_type"]["npc_action"] == 1
        assert summary["by_type"]["scene_event"] == 1
        assert summary["fallbacks"] == 1
        assert summary["rejections"] == 1
        assert 0.6 < summary["avg_confidence"] < 0.7


class TestReplayWithLLMStageMetadata:
    """Test replay with LLM stage metadata from result_json."""

    def setup_method(self):
        """Reset both audit and replay systems."""
        reset_audit_logger()
        reset_replay_store()
        self.audit_logger = get_audit_logger()
        self.replay_store = get_replay_store()
        self.replay_engine = self.replay_store.get_replay_engine()

    def test_replay_extract_llm_stage_metadata(self):
        result_json = {
            "llm_stages": [
                {
                    "stage_name": "input_intent",
                    "enabled": True,
                    "timeout": 15.0,
                    "accepted": True,
                    "fallback_reason": None,
                    "validation_errors": [],
                    "model_call_id": "mc_001",
                },
                {
                    "stage_name": "world",
                    "enabled": True,
                    "timeout": 30.0,
                    "accepted": True,
                    "fallback_reason": None,
                    "validation_errors": [],
                    "model_call_id": "mc_002",
                },
                {
                    "stage_name": "npc",
                    "enabled": True,
                    "timeout": 30.0,
                    "accepted": False,
                    "fallback_reason": "validation_failed",
                    "validation_errors": ["Invalid action type"],
                    "model_call_id": None,
                },
            ],
        }

        metadata = self.replay_engine.extract_llm_stage_metadata(
            result_json, ReplayPerspective.ADMIN
        )

        assert len(metadata) == 3
        assert metadata[0].stage_name == "input_intent"
        assert metadata[0].accepted is True
        assert metadata[2].accepted is False
        assert metadata[2].fallback_reason == "validation_failed"

    def test_replay_extract_llm_stage_metadata_empty(self):
        metadata = self.replay_engine.extract_llm_stage_metadata(
            None, ReplayPerspective.ADMIN
        )
        assert metadata == []

        metadata = self.replay_engine.extract_llm_stage_metadata(
            {}, ReplayPerspective.ADMIN
        )
        assert metadata == []

    def test_replay_step_includes_llm_stages(self):
        result_json = {
            "llm_stages": [
                {
                    "stage_name": "narration",
                    "enabled": True,
                    "accepted": True,
                    "fallback_reason": None,
                },
            ],
            "parsed_intent": {"intent_type": "talk"},
        }

        events = [
            ReplayEvent(
                event_id="evt_llm_1",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={
                    "raw_input": "talk to npc",
                    "result_json": result_json,
                },
            ),
        ]

        result = self.replay_engine.replay_turn_range(
            session_id="session_llm_test",
            start_turn=1,
            end_turn=1,
            events=events,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.success is True
        assert len(result.steps) == 1
        assert len(result.steps[0].llm_stages) == 1
        assert result.steps[0].llm_stages[0].stage_name == "narration"

    def test_replay_result_metadata_extraction(self):
        result_json = {
            "world_progression": {"time_delta": 1},
            "npc_reactions": [
                {"npc_name": "Guide", "action_type": "talk", "hidden_motivation": "secret"}
            ],
            "parsed_intent": {"intent_type": "move"},
            "raw_prompt": "should not be included",
        }

        metadata = self.replay_engine.extract_result_metadata(
            result_json, ReplayPerspective.ADMIN
        )

        assert "world_progression" in metadata
        assert "npc_reactions" in metadata
        assert "parsed_intent" in metadata
        assert "raw_prompt" not in metadata

    def test_replay_result_metadata_player_perspective_filters_hidden(self):
        result_json = {
            "npc_reactions": [
                {
                    "npc_name": "Guide",
                    "action_type": "talk",
                    "hidden_motivation": "secret plan",
                    "internal_state": "suspicious",
                    "summary": "greets player",
                }
            ],
        }

        metadata = self.replay_engine.extract_result_metadata(
            result_json, ReplayPerspective.PLAYER
        )

        assert "npc_reactions" in metadata
        reaction = metadata["npc_reactions"][0]
        assert "hidden_motivation" not in reaction
        assert "internal_state" not in reaction
        assert reaction.get("summary") == "greets player"

    def test_replay_with_full_llm_stages(self):
        result_json = {
            "llm_stages": [
                {"stage_name": "input_intent", "enabled": True, "accepted": True},
                {"stage_name": "world", "enabled": True, "accepted": True},
                {"stage_name": "scene", "enabled": True, "accepted": False, "fallback_reason": "timeout"},
                {"stage_name": "npc", "enabled": True, "accepted": True},
                {"stage_name": "narration", "enabled": True, "accepted": True},
            ],
            "world_progression": {"time_delta": 1},
            "npc_reactions": [{"npc_name": "NPC", "action_type": "idle"}],
            "parsed_intent": {"intent_type": "move"},
            "memory_persistence": {"facts_written": 2},
        }

        events = [
            ReplayEvent(
                event_id="evt_full_llm",
                event_type="player_input",
                turn_no=1,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={
                    "raw_input": "move north",
                    "result_json": result_json,
                    "state_deltas": [
                        {"path": "player_state.location", "old_value": "A", "new_value": "B", "operation": "set"},
                    ],
                },
            ),
        ]

        result = self.replay_engine.replay_turn_range(
            session_id="session_full_llm",
            start_turn=1,
            end_turn=1,
            events=events,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.success is True
        assert len(result.steps[0].llm_stages) == 5
        assert result.steps[0].result_metadata.get("parsed_intent") is not None

    def test_replay_from_snapshot_with_llm_stages(self):
        snapshot = self.replay_store.create_snapshot(
            session_id="session_snapshot_llm",
            turn_no=10,
            world_state={"current_time": "Day 1"},
            player_state={"hp": 100},
        )

        result_json = {
            "llm_stages": [
                {"stage_name": "narration", "enabled": True, "accepted": True},
            ],
        }

        events = [
            ReplayEvent(
                event_id="evt_snapshot_llm",
                event_type="player_input",
                turn_no=11,
                timestamp=datetime.now(),
                visible_to_player=True,
                data={
                    "raw_input": "rest",
                    "result_json": result_json,
                },
            ),
        ]

        result = self.replay_store.replay_from_snapshot(
            session_id="session_snapshot_llm",
            snapshot_id=snapshot.snapshot_id,
            target_turn=11,
            events=events,
            perspective=ReplayPerspective.ADMIN,
        )

        assert result.success is True
        assert len(result.steps) == 1
        assert len(result.steps[0].llm_stages) == 1
