"""
Unit tests for Runtime Orchestration modules.

Tests:
- TurnOrchestrator
- GameSessionManager
- GameLoopController
- ModeController
- RetryController
- TransactionManager
"""

import pytest
from datetime import datetime

from llm_rpg.runtime import (
    TurnOrchestrator,
    GameSessionManager,
    GameLoopController,
    ModeController,
    GameMode,
    RetryController,
    TransactionManager,
)
from llm_rpg.runtime.transaction_manager import TransactionStatus
from llm_rpg.runtime.mode_controller import ModeTransitionError
from llm_rpg.runtime.game_loop_controller import LoopState, GameLoopError
from llm_rpg.runtime.retry_controller import (
    RetryPolicy,
    CircuitState,
    RetryConfig,
    CircuitBreakerConfig,
)


class TestTurnOrchestrator:
    """Tests for TurnOrchestrator."""
    
    def test_orchestrator_initialization(self):
        orchestrator = TurnOrchestrator()
        assert orchestrator is not None
        assert len(orchestrator.get_audit_log()) == 0
    
    def test_execute_turn_basic(self):
        orchestrator = TurnOrchestrator()
        state_context = {
            "world_time": {"calendar": "修仙历", "season": "春", "day": 1, "period": "辰时"},
            "player_location": "square",
        }
        
        result = orchestrator.execute_turn(
            session_id="test_session",
            game_id="test_game",
            turn_index=1,
            player_input="move to forest",
            state_context=state_context,
        )
        
        assert result is not None
        assert "transaction_id" in result
        assert result["turn_index"] == 1
        assert "success" in result
        assert "narration" in result
    
    def test_turn_has_transaction_id(self):
        orchestrator = TurnOrchestrator()
        state_context = {"world_time": {"calendar": "", "season": "春", "day": 1, "period": "辰时"}}
        
        result = orchestrator.execute_turn(
            session_id="sess_123",
            game_id="game_123",
            turn_index=1,
            player_input="test",
            state_context=state_context,
        )
        
        assert result["transaction_id"].startswith("turn_")
        assert len(result["transaction_id"]) > 5
    
    def test_audit_log_recorded(self):
        orchestrator = TurnOrchestrator()
        state_context = {"world_time": {"calendar": "", "season": "春", "day": 1, "period": "辰时"}}
        
        orchestrator.execute_turn(
            session_id="sess_123",
            game_id="game_123",
            turn_index=1,
            player_input="test",
            state_context=state_context,
        )
        
        audit_log = orchestrator.get_audit_log()
        assert len(audit_log) >= 1
    
    def test_clear_audit_log(self):
        orchestrator = TurnOrchestrator()
        state_context = {"world_time": {"calendar": "", "season": "春", "day": 1, "period": "辰时"}}
        
        orchestrator.execute_turn(
            session_id="sess_123",
            game_id="game_123",
            turn_index=1,
            player_input="test",
            state_context=state_context,
        )
        
        orchestrator.clear_audit_log()
        assert len(orchestrator.get_audit_log()) == 0
    
    def test_register_step_handler(self):
        orchestrator = TurnOrchestrator()
        handler_called = [False]
        
        def test_handler(context):
            handler_called[0] = True
            return {"test": True}
        
        orchestrator.register_step_handler(1, test_handler)
        state_context = {"world_time": {"calendar": "", "season": "春", "day": 1, "period": "辰时"}}
        
        orchestrator.execute_turn(
            session_id="sess_123",
            game_id="game_123",
            turn_index=1,
            player_input="test",
            state_context=state_context,
        )
        
        assert handler_called[0]


class TestGameSessionManager:
    """Tests for GameSessionManager."""
    
    def test_manager_initialization(self):
        manager = GameSessionManager()
        assert manager is not None
    
    def test_create_session(self):
        manager = GameSessionManager()
        session = manager.create_session(
            game_id="game_123",
            user_id="user_123",
            name="Test Session",
        )
        
        assert session is not None
        assert session.game_id == "game_123"
        assert session.user_id == "user_123"
        assert session.name == "Test Session"
        assert session.session_id.startswith("sess_")
    
    def test_get_session(self):
        manager = GameSessionManager()
        session = manager.create_session(game_id="game_123", user_id="user_123")
        
        retrieved = manager.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id
    
    def test_get_session_not_found(self):
        manager = GameSessionManager()
        retrieved = manager.get_session("nonexistent")
        assert retrieved is None
    
    def test_load_session(self):
        manager = GameSessionManager()
        session = manager.create_session(game_id="game_123", user_id="user_123")
        
        loaded = manager.load_session(session.session_id)
        assert loaded.state.value == "active"
    
    def test_load_session_not_found(self):
        manager = GameSessionManager()
        with pytest.raises(Exception):
            manager.load_session("nonexistent")
    
    def test_save_session(self):
        manager = GameSessionManager()
        session = manager.create_session(game_id="game_123", user_id="user_123")
        manager.load_session(session.session_id)
        
        result = manager.save_session(session.session_id)
        assert result is True
        assert session.state.value == "active"
    
    def test_pause_resume_session(self):
        manager = GameSessionManager()
        session = manager.create_session(game_id="game_123", user_id="user_123")
        manager.load_session(session.session_id)
        
        assert manager.pause_session(session.session_id) is True
        assert session.state.value == "paused"
        
        assert manager.resume_session(session.session_id) is True
        assert session.state.value == "active"
    
    def test_end_session(self):
        manager = GameSessionManager()
        session = manager.create_session(game_id="game_123", user_id="user_123")
        
        result = manager.end_session(session.session_id)
        assert result is True
        assert session.state.value == "ended"
    
    def test_delete_session(self):
        manager = GameSessionManager()
        session = manager.create_session(game_id="game_123", user_id="user_123")
        session_id = session.session_id
        
        result = manager.delete_session(session_id)
        assert result is True
        assert manager.get_session(session_id) is None
    
    def test_update_turn(self):
        manager = GameSessionManager()
        session = manager.create_session(game_id="game_123", user_id="user_123")
        
        result = manager.update_turn(session.session_id, 5)
        assert result is True
        assert session.current_turn == 5
    
    def test_list_user_sessions(self):
        manager = GameSessionManager()
        manager.create_session(game_id="game_1", user_id="user_123")
        manager.create_session(game_id="game_2", user_id="user_123")
        manager.create_session(game_id="game_3", user_id="other_user")
        
        sessions = manager.list_user_sessions("user_123")
        assert len(sessions) == 2
    
    def test_list_active_sessions(self):
        manager = GameSessionManager()
        session1 = manager.create_session(game_id="game_1", user_id="user_123")
        session2 = manager.create_session(game_id="game_2", user_id="user_123")
        manager.load_session(session1.session_id)
        manager.load_session(session2.session_id)
        
        active = manager.list_active_sessions()
        assert len(active) == 2


class TestGameLoopController:
    """Tests for GameLoopController."""
    
    def test_controller_initialization(self):
        controller = GameLoopController()
        assert controller is not None
        assert controller.get_state() == LoopState.STOPPED
    
    def test_initialize(self):
        controller = GameLoopController()
        controller.initialize(game_id="game_123")
        
        assert controller.get_state() == LoopState.INITIALIZING
    
    def test_start_stop(self):
        controller = GameLoopController()
        controller.initialize(game_id="game_123")
        
        controller.start()
        assert controller.get_state() == LoopState.RUNNING
        assert controller.is_running() is True
        
        controller.stop()
        assert controller.get_state() == LoopState.STOPPED
        assert controller.is_running() is False
    
    def test_pause_resume(self):
        controller = GameLoopController()
        controller.initialize(game_id="game_123")
        controller.start()
        
        controller.pause()
        assert controller.get_state() == LoopState.PAUSED
        assert controller.is_paused() is True
        
        controller.resume()
        assert controller.get_state() == LoopState.RUNNING
        assert controller.is_paused() is False
    
    def test_cannot_start_without_initialize(self):
        controller = GameLoopController()
        with pytest.raises(GameLoopError):
            controller.start()
    
    def test_tick(self):
        controller = GameLoopController()
        controller.initialize(game_id="game_123")
        controller.start()
        
        tick = controller.tick(mode="exploration", turn_index=1)
        
        assert tick.tick_number == 1
        assert tick.game_id == "game_123"
        assert tick.mode == "exploration"
        assert tick.turn_index == 1
    
    def test_tick_increments(self):
        controller = GameLoopController()
        controller.initialize(game_id="game_123")
        controller.start()
        
        tick1 = controller.tick(mode="exploration", turn_index=1)
        tick2 = controller.tick(mode="exploration", turn_index=2)
        
        assert tick2.tick_number == tick1.tick_number + 1
    
    def test_tick_history(self):
        controller = GameLoopController()
        controller.initialize(game_id="game_123")
        controller.start()
        
        controller.tick(mode="exploration", turn_index=1)
        controller.tick(mode="exploration", turn_index=2)
        
        history = controller.get_tick_history()
        assert len(history) == 2


class TestModeController:
    """Tests for ModeController."""
    
    def test_controller_initialization(self):
        controller = ModeController()
        assert controller is not None
        assert controller.get_current_mode() == GameMode.EXPLORATION
    
    def test_transition_to_valid(self):
        controller = ModeController()
        
        result = controller.transition_to(GameMode.COMBAT)
        assert controller.get_current_mode() == GameMode.COMBAT
        assert result.mode == GameMode.COMBAT
    
    def test_transition_to_invalid(self):
        controller = ModeController()
        controller.transition_to(GameMode.COMBAT)
        
        with pytest.raises(ModeTransitionError):
            controller.transition_to(GameMode.MENU)
    
    def test_can_transition_to(self):
        controller = ModeController()
        
        assert controller.can_transition_to(GameMode.COMBAT) is True
        assert controller.can_transition_to(GameMode.DIALOGUE) is True
    
    def test_force_transition(self):
        controller = ModeController()
        controller.transition_to(GameMode.COMBAT)
        
        result = controller.transition_to(GameMode.MENU, force=True)
        assert controller.get_current_mode() == GameMode.MENU
    
    def test_push_pop_mode(self):
        controller = ModeController()
        
        controller.push_mode(GameMode.DIALOGUE)
        assert controller.get_current_mode() == GameMode.DIALOGUE
        
        controller.pop_mode()
        assert controller.get_current_mode() == GameMode.EXPLORATION
    
    def test_is_action_allowed(self):
        controller = ModeController()
        controller.transition_to(GameMode.COMBAT)
        
        assert controller.is_action_allowed("attack") is True
        assert controller.is_action_allowed("move") is False
    
    def test_get_allowed_actions(self):
        controller = ModeController()
        controller.transition_to(GameMode.COMBAT)
        
        actions = controller.get_allowed_actions()
        assert "attack" in actions
        assert "defend" in actions
        assert "move" not in actions
    
    def test_mode_context(self):
        controller = ModeController()
        
        controller.set_mode_context("enemy_id", "npc_123")
        assert controller.get_mode_context("enemy_id") == "npc_123"
        assert controller.get_mode_context("nonexistent", "default") == "default"
    
    def test_transition_history(self):
        controller = ModeController()
        
        controller.transition_to(GameMode.COMBAT)
        controller.transition_to(GameMode.DIALOGUE)
        
        history = controller.get_transition_history()
        assert len(history) == 2


class TestRetryController:
    """Tests for RetryController."""
    
    def test_controller_initialization(self):
        controller = RetryController()
        assert controller is not None
    
    def test_successful_operation(self):
        controller = RetryController()
        
        def operation():
            return "success"
        
        result = controller.execute_with_retry(operation)
        assert result == "success"
    
    def test_retry_on_failure(self):
        controller = RetryController()
        attempts = [0]
        
        def failing_operation():
            attempts[0] += 1
            if attempts[0] < 2:
                raise Exception("Temporary failure")
            return "success"
        
        config = RetryConfig(max_attempts=3, base_delay=0.01)
        result = controller.execute_with_retry(operation=failing_operation, config=config)
        
        assert result == "success"
        assert attempts[0] == 2
    
    def test_exhausted_retries(self):
        controller = RetryController()
        
        def always_fails():
            raise Exception("Always fails")
        
        config = RetryConfig(max_attempts=2, base_delay=0.01)
        
        with pytest.raises(Exception, match="Always fails"):
            controller.execute_with_retry(operation=always_fails, config=config)
    
    def test_circuit_breaker(self):
        controller = RetryController()
        
        def always_fails():
            raise Exception("Failure")
        
        config = RetryConfig(max_attempts=1, base_delay=0.01)
        
        for _ in range(5):
            try:
                controller.execute_with_retry(
                    operation=always_fails,
                    config=config,
                    circuit_name="test_circuit"
                )
            except Exception:
                pass
        
        assert controller.get_circuit_state("test_circuit") == CircuitState.OPEN
    
    def test_reset_circuit(self):
        controller = RetryController()
        
        def always_fails():
            raise Exception("Failure")
        
        config = RetryConfig(max_attempts=1, base_delay=0.01)
        
        try:
            controller.execute_with_retry(
                operation=always_fails,
                config=config,
                circuit_name="test_circuit"
            )
        except Exception:
            pass
        
        controller.reset_circuit("test_circuit")
        assert controller.get_circuit_state("test_circuit") == CircuitState.CLOSED
    
    def test_stats_tracking(self):
        controller = RetryController()
        
        def operation():
            return "success"
        
        controller.execute_with_retry(operation)
        
        stats = controller.get_stats()
        assert stats.total_attempts == 1
        assert stats.successful_attempts == 1
    
    def test_reset_stats(self):
        controller = RetryController()
        
        def operation():
            return "success"
        
        controller.execute_with_retry(operation)
        controller.reset_stats()
        
        stats = controller.get_stats()
        assert stats.total_attempts == 0


class TestTransactionManager:
    """Tests for TransactionManager."""
    
    def test_manager_initialization(self):
        manager = TransactionManager()
        assert manager is not None
    
    def test_begin_transaction(self):
        manager = TransactionManager()
        txn = manager.begin_transaction(game_id="game_123", operation="move")
        
        assert txn is not None
        assert txn.game_id == "game_123"
        assert txn.operation == "move"
        assert txn.status == TransactionStatus.PENDING
        assert txn.transaction_id.startswith("txn_")
    
    def test_commit_transaction(self):
        manager = TransactionManager()
        txn = manager.begin_transaction(game_id="game_123", operation="move")
        
        result = manager.commit(txn.transaction_id)
        assert result is True
        assert txn.status == TransactionStatus.COMMITTED
    
    def test_rollback_transaction(self):
        manager = TransactionManager()
        txn = manager.begin_transaction(game_id="game_123", operation="move")
        
        result = manager.rollback(txn.transaction_id, "Test error")
        assert result is True
        assert txn.status == TransactionStatus.ROLLED_BACK
        assert txn.error == "Test error"
    
    def test_get_transaction(self):
        manager = TransactionManager()
        txn = manager.begin_transaction(game_id="game_123", operation="move")
        
        retrieved = manager.get_transaction(txn.transaction_id)
        assert retrieved is not None
        assert retrieved.transaction_id == txn.transaction_id
    
    def test_get_active_transactions(self):
        manager = TransactionManager()
        txn1 = manager.begin_transaction(game_id="game_123", operation="move")
        txn2 = manager.begin_transaction(game_id="game_123", operation="attack")
        
        active = manager.get_active_transactions(game_id="game_123")
        assert len(active) == 2
    
    def test_transaction_history(self):
        manager = TransactionManager()
        txn = manager.begin_transaction(game_id="game_123", operation="move")
        manager.commit(txn.transaction_id)
        
        history = manager.get_transaction_history()
        assert len(history) == 1
    
    def test_transaction_scope_success(self):
        manager = TransactionManager()
        
        with manager.transaction_scope(game_id="game_123", operation="move") as txn:
            txn.add_event({"type": "test"})
        
        assert txn.status == TransactionStatus.COMMITTED
    
    def test_transaction_scope_exception(self):
        manager = TransactionManager()
        
        with pytest.raises(ValueError):
            with manager.transaction_scope(game_id="game_123", operation="move") as txn:
                raise ValueError("Test error")
        
        history = manager.get_transaction_history()
        assert len(history) == 1
        assert history[0].status == TransactionStatus.ROLLED_BACK
    
    def test_abort_all_active(self):
        manager = TransactionManager()
        manager.begin_transaction(game_id="game_123", operation="move")
        manager.begin_transaction(game_id="game_123", operation="attack")
        
        aborted = manager.abort_all_active(game_id="game_123")
        assert aborted == 2
        
        active = manager.get_active_transactions(game_id="game_123")
        assert len(active) == 0
