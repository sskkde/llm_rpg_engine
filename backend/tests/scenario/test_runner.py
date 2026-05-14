"""Integration tests for Scenario Test Runner."""

import pytest
from datetime import datetime
from typing import Dict, Any, List

from llm_rpg.observability.scenario_runner import (
    ScenarioRunner,
    ScenarioTest,
    ScenarioResult,
    ScenarioStep,
    ScenarioType,
)
from tests.conftest import MockLLMProvider


@pytest.mark.scenario
class TestScenarioRunner:
    """Test Scenario Runner functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    @pytest.mark.smoke
    def test_get_available_scenarios(self):
        """Test getting list of available scenarios."""
        scenarios = self.runner.get_available_scenarios()
        
        assert len(scenarios) == 12
        
        scenario_types = [s.scenario_type for s in scenarios]
        assert ScenarioType.SECRET_LEAK_PREVENTION in scenario_types
        assert ScenarioType.IMPORTANT_NPC_ATTACK in scenario_types
        assert ScenarioType.SEAL_COUNTDOWN in scenario_types
        assert ScenarioType.FORBIDDEN_KNOWLEDGE in scenario_types
        
        for scenario in scenarios:
            assert scenario.test_id is not None
            assert scenario.name is not None
            assert scenario.description is not None
            assert len(scenario.expected_outcomes) > 0

    @pytest.mark.smoke
    def test_run_secret_leak_prevention_scenario(self):
        """Test running secret leak prevention scenario."""
        result = self.runner.run_scenario(
            ScenarioType.SECRET_LEAK_PREVENTION,
            "session_001",
            custom_setup={
                "npc_id": "npc_test_villager",
                "npc_name": "Mysterious Villager",
                "hidden_identity": "Secretly a demon lord",
            }
        )
        
        assert result is not None
        assert result.result_id is not None
        assert result.scenario_type == ScenarioType.SECRET_LEAK_PREVENTION
        assert result.session_id == "session_001"
        assert result.test_id == "secret_leak_prevention_001"
        
        # Check result status
        assert result.status in ["passed", "partial", "failed"]
        
        # Check steps
        assert len(result.steps) == 3
        
        # Verify step structure
        for step in result.steps:
            assert step.step_no > 0
            assert step.action is not None
            assert step.expected_result is not None
            assert step.actual_result is not None
            assert isinstance(step.passed, bool)
        
        # Check pass rate calculation
        assert result.total_steps == 3
        assert result.passed_steps + result.failed_steps == result.total_steps
        assert 0.0 <= result.pass_rate <= 1.0
        
        # Check timing
        assert result.started_at is not None
        assert result.completed_at is not None
        assert result.duration_ms is not None
        assert result.duration_ms >= 0
        
        # Check logs
        assert len(result.logs) > 0

    @pytest.mark.smoke
    def test_run_important_npc_attack_scenario(self):
        """Test running important NPC attack scenario."""
        result = self.runner.run_scenario(
            ScenarioType.IMPORTANT_NPC_ATTACK,
            "session_002",
            custom_setup={
                "npc_id": "npc_important_merchant",
                "npc_name": "Important Merchant",
            }
        )
        
        assert result is not None
        assert result.scenario_type == ScenarioType.IMPORTANT_NPC_ATTACK
        assert result.test_id == "important_npc_attack_001"
        assert len(result.steps) == 3
        
        # Verify combat-related steps
        step_actions = [s.action for s in result.steps]
        assert "initiate_combat" in step_actions
        assert "npc_combat_response" in step_actions
        assert "verify_world_state_update" in step_actions

    @pytest.mark.smoke
    def test_run_seal_countdown_scenario(self):
        """Test running seal countdown scenario."""
        result = self.runner.run_scenario(
            ScenarioType.SEAL_COUNTDOWN,
            "session_003",
            custom_setup={
                "initial_countdown": 10,
                "turns": 3,
            }
        )
        
        assert result is not None
        assert result.scenario_type == ScenarioType.SEAL_COUNTDOWN
        assert result.test_id == "seal_countdown_001"
        assert len(result.steps) == 3
        
        # Find the advance_turns step
        advance_step = next((s for s in result.steps if s.action == "advance_turns"), None)
        assert advance_step is not None
        
        # Verify countdown progression
        expected_countdown = 10 - 3
        assert "7" in advance_step.actual_result or str(expected_countdown) in advance_step.actual_result

    @pytest.mark.smoke
    def test_run_forbidden_knowledge_scenario(self):
        """Test running forbidden knowledge scenario."""
        result = self.runner.run_scenario(
            ScenarioType.FORBIDDEN_KNOWLEDGE,
            "session_004",
            custom_setup={
                "npc_id": "npc_elder_sage",
                "forbidden_info": "The world ends tomorrow",
            }
        )
        
        assert result is not None
        assert result.scenario_type == ScenarioType.FORBIDDEN_KNOWLEDGE
        assert result.test_id == "forbidden_knowledge_001"
        assert len(result.steps) == 3
        
        # Verify forbidden knowledge check step
        forbidden_step = next((s for s in result.steps if s.action == "player_asks_about_future"), None)
        assert forbidden_step is not None
        assert not forbidden_step.input_data["question"].lower() in forbidden_step.actual_result.lower()

    def test_run_all_scenarios(self):
        """Test running all scenarios at once."""
        results = self.runner.run_all_scenarios("session_all")
        
        assert len(results) == 12
        
        scenario_types = [r.scenario_type for r in results]
        assert ScenarioType.SECRET_LEAK_PREVENTION in scenario_types
        assert ScenarioType.IMPORTANT_NPC_ATTACK in scenario_types
        assert ScenarioType.SEAL_COUNTDOWN in scenario_types
        assert ScenarioType.FORBIDDEN_KNOWLEDGE in scenario_types
        
        for result in results:
            assert result.session_id == "session_all"
            assert result.status in ["passed", "partial", "failed"]

    def test_get_result(self):
        """Test retrieving scenario result by ID."""
        result = self.runner.run_scenario(
            ScenarioType.SECRET_LEAK_PREVENTION,
            "session_005"
        )
        
        retrieved = self.runner.get_result(result.result_id)
        assert retrieved is not None
        assert retrieved.result_id == result.result_id
        assert retrieved.scenario_type == result.scenario_type

    def test_get_result_not_found(self):
        """Test retrieving non-existent result."""
        result = self.runner.get_result("nonexistent_id")
        assert result is None

    def test_get_all_results(self):
        """Test getting all scenario results."""
        initial_results = self.runner.get_all_results()
        initial_count = len(initial_results)
        
        self.runner.run_scenario(ScenarioType.SECRET_LEAK_PREVENTION, "session_006")
        self.runner.run_scenario(ScenarioType.SEAL_COUNTDOWN, "session_007")
        
        all_results = self.runner.get_all_results()
        assert len(all_results) == initial_count + 2

    def test_scenario_result_pass_calculation(self):
        """Test pass/fail calculation in scenario result."""
        result = self.runner.run_scenario(
            ScenarioType.SECRET_LEAK_PREVENTION,
            "session_008"
        )
        
        # Verify calculation
        if result.total_steps > 0:
            expected_rate = result.passed_steps / result.total_steps
            assert result.pass_rate == expected_rate
        
        # Verify status logic
        if result.failed_steps == 0 and result.total_steps > 0:
            assert result.status == "passed"
        elif result.failed_steps < result.total_steps:
            assert result.status == "partial"
        else:
            assert result.status == "failed"

    def test_scenario_with_mock_llm_responses(self):
        """Test scenario with predefined mock LLM responses."""
        self.mock_provider.set_response(
            "dialogue",
            "I am but a simple villager with no secrets."
        )
        
        result = self.runner.run_scenario(
            ScenarioType.SECRET_LEAK_PREVENTION,
            "session_009",
            custom_setup={
                "hidden_identity": "demon lord",
            }
        )
        
        assert result is not None
        # Mock response should not contain the hidden identity
        for step in result.steps:
            if "demon lord" in step.actual_result.lower():
                assert not step.passed

    def test_scenario_step_structure(self):
        """Test scenario step data structure."""
        result = self.runner.run_scenario(
            ScenarioType.SEAL_COUNTDOWN,
            "session_010"
        )
        
        for step in result.steps:
            assert isinstance(step, ScenarioStep)
            assert isinstance(step.step_no, int)
            assert isinstance(step.action, str)
            assert isinstance(step.input_data, dict)
            assert isinstance(step.passed, bool)
            
            # Input data should not be empty
            assert len(step.input_data) > 0

    def test_scenario_logs(self):
        """Test scenario logging."""
        result = self.runner.run_scenario(
            ScenarioType.IMPORTANT_NPC_ATTACK,
            "session_011"
        )
        
        assert len(result.logs) > 0
        
        # Each step should generate at least one log entry
        assert len(result.logs) >= len(result.steps)
        
        # Log entries should contain status information
        for log in result.logs:
            assert isinstance(log, str)

    def test_unknown_scenario_type(self):
        """Test handling of unknown scenario type."""
        result = self.runner.run_scenario("unknown_scenario_type", "session_012")
        
        assert result.status == "failed"
        assert "Unknown scenario type" in result.logs[0]

    def test_scenario_timing(self):
        """Test scenario timing information."""
        result = self.runner.run_scenario(
            ScenarioType.FORBIDDEN_KNOWLEDGE,
            "session_013"
        )
        
        assert result.started_at is not None
        assert result.completed_at is not None
        assert result.duration_ms is not None
        
        # Duration should be non-negative
        assert result.duration_ms >= 0
        
        # Completed should be after started
        if result.started_at and result.completed_at:
            assert result.completed_at >= result.started_at


@pytest.mark.scenario
class TestSecretLeakPreventionScenario:
    """Test secret leak prevention scenario specifics."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def test_secret_not_revealed_in_response(self):
        """Test that NPC doesn't reveal secret in dialogue."""
        secret = "demon lord"
        self.mock_provider.set_response("dialogue", "I am a simple villager.")
        
        result = self.runner.run_scenario(
            ScenarioType.SECRET_LEAK_PREVENTION,
            "session_secret_001",
            custom_setup={
                "hidden_identity": secret,
            }
        )
        
        simulate_step = next((s for s in result.steps if s.action == "simulate_player_interrogation"), None)
        assert simulate_step is not None
        assert simulate_step.passed is True
        assert secret not in simulate_step.actual_result.lower()

    def test_perspective_filtering(self):
        """Test that player perspective doesn't see hidden info."""
        result = self.runner.run_scenario(
            ScenarioType.SECRET_LEAK_PREVENTION,
            "session_secret_002"
        )
        
        perspective_step = next((s for s in result.steps if s.action == "verify_perspective_filtering"), None)
        assert perspective_step is not None
        assert perspective_step.passed is True


@pytest.mark.scenario
class TestSealCountdownScenario:
    """Test seal countdown scenario specifics."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def test_countdown_decrements_correctly(self):
        """Test that seal countdown decrements by correct amount."""
        initial = 10
        turns = 3
        
        result = self.runner.run_scenario(
            ScenarioType.SEAL_COUNTDOWN,
            "session_seal_001",
            custom_setup={
                "initial_countdown": initial,
                "turns": turns,
            }
        )
        
        advance_step = next((s for s in result.steps if s.action == "advance_turns"), None)
        assert advance_step is not None
        assert advance_step.passed is True
        
        # Countdown should be initial - turns
        expected_final = initial - turns
        assert str(expected_final) in advance_step.actual_result

    def test_world_time_advances(self):
        """Test that world time advances correctly."""
        result = self.runner.run_scenario(
            ScenarioType.SEAL_COUNTDOWN,
            "session_seal_002",
            custom_setup={
                "initial_countdown": 10,
                "turns": 3,
            }
        )
        
        time_step = next((s for s in result.steps if s.action == "verify_time_progression"), None)
        assert time_step is not None
        
        # Time should advance by 2 hours per turn
        expected_hour = 8 + (3 * 2)  # 14
        assert time_step.passed is True
        assert str(expected_hour) in time_step.actual_result or "14" in time_step.actual_result


@pytest.mark.scenario
class TestImportantNPCAttackScenario:
    """Test important NPC attack scenario specifics."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.mock_provider.set_response("combat_action", "I will defend myself fiercely!")
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def test_combat_session_starts(self):
        """Test that combat session starts correctly."""
        result = self.runner.run_scenario(
            ScenarioType.IMPORTANT_NPC_ATTACK,
            "session_combat_001"
        )
        
        combat_step = next((s for s in result.steps if s.action == "initiate_combat"), None)
        assert combat_step is not None
        assert combat_step.passed is True
        assert "active" in combat_step.actual_result.lower()

    def test_npc_combat_response_valid(self):
        """Test that NPC responds with valid combat action."""
        result = self.runner.run_scenario(
            ScenarioType.IMPORTANT_NPC_ATTACK,
            "session_combat_002"
        )
        
        response_step = next((s for s in result.steps if s.action == "npc_combat_response"), None)
        assert response_step is not None
        assert response_step.passed is True
        
        # Valid actions include defend, attack, flee, dodge
        valid_words = ["defend", "attack", "flee", "dodge"]
        assert any(word in response_step.actual_result.lower() for word in valid_words)


@pytest.mark.scenario
class TestForbiddenKnowledgeScenario:
    """Test forbidden knowledge scenario specifics."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.mock_provider.set_response("dialogue", "The future is uncertain.")
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def test_forbidden_knowledge_not_exposed(self):
        """Test that forbidden knowledge is not exposed to player."""
        forbidden = "The world ends tomorrow"
        
        result = self.runner.run_scenario(
            ScenarioType.FORBIDDEN_KNOWLEDGE,
            "session_knowledge_001",
            custom_setup={
                "forbidden_info": forbidden,
            }
        )
        
        ask_step = next((s for s in result.steps if s.action == "player_asks_about_future"), None)
        assert ask_step is not None
        assert ask_step.passed is True
        assert forbidden.lower() not in ask_step.actual_result.lower()

    def test_perspective_boundaries_maintained(self):
        """Test that perspective boundaries are maintained."""
        result = self.runner.run_scenario(
            ScenarioType.FORBIDDEN_KNOWLEDGE,
            "session_knowledge_002"
        )
        
        boundary_step = next((s for s in result.steps if s.action == "verify_perspective_boundaries"), None)
        assert boundary_step is not None
        assert boundary_step.passed is True
        assert "blocked" in boundary_step.actual_result.lower()


@pytest.mark.scenario
class TestMockLLMProviderIntegration:
    """Test MockLLMProvider integration with scenarios."""

    def test_mock_provider_responses(self):
        """Test that mock provider returns deterministic responses."""
        provider = MockLLMProvider()
        
        # Set specific responses
        provider.set_response("npc_dialogue", "NPC dialogue response")
        provider.set_response("combat_action", "Combat action response")
        
        runner = ScenarioRunner(llm_provider=provider)
        
        # Run scenario that uses these responses
        result = runner.run_scenario(
            ScenarioType.IMPORTANT_NPC_ATTACK,
            "session_mock_001"
        )
        
        assert result is not None
        # Verify responses were used
        combat_step = next((s for s in result.steps if s.action == "npc_combat_response"), None)
        assert combat_step is not None
        assert "response" in combat_step.actual_result.lower()

    def test_mock_provider_default_responses(self):
        """Test mock provider default responses."""
        provider = MockLLMProvider()
        
        narrative = provider.generate("Generate a narrative description")
        assert "cobblestones" in narrative or "ancient" in narrative.lower()
        
        action = provider.generate("What action should the NPC take?")
        assert "action" in action.lower() or "decision" in action.lower()

    def test_mock_provider_json_generation(self):
        """Test mock provider JSON generation."""
        provider = MockLLMProvider()
        
        result = provider.generate_json('{"type": "test"}')
        assert isinstance(result, dict)


@pytest.mark.scenario
class TestCoreLoopScenarios:
    """Test core game loop scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    @pytest.mark.smoke
    def test_core_loop_order_explicit(self):
        """Test that core loop executes in documented order."""
        result = self.runner.run_custom_scenario(
            "core_loop_order_test",
            "session_core_001",
            steps=[
                {"action": "start_transaction", "expected": "transaction_created"},
                {"action": "parse_intent_llm", "expected": "intent_parsed"},
                {"action": "world_tick_deterministic", "expected": "time_advanced"},
                {"action": "scene_candidates_llm", "expected": "candidates_generated"},
                {"action": "collect_actors", "expected": "actors_collected"},
                {"action": "npc_proposals_sequential", "expected": "npc_decisions"},
                {"action": "resolve_conflicts", "expected": "conflicts_resolved"},
                {"action": "validate_actions", "expected": "validation_passed"},
                {"action": "atomic_commit", "expected": "state_committed"},
                {"action": "write_memories", "expected": "chronicle_written"},
                {"action": "record_audit", "expected": "audit_logged"},
                {"action": "generate_narration", "expected": "narration_output"},
            ]
        )
        
        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 12

    @pytest.mark.smoke
    def test_fallback_matrix_coverage(self):
        """Test all fallback scenarios in fallback matrix."""
        result = self.runner.run_custom_scenario(
            "fallback_matrix_test",
            "session_fallback_001",
            steps=[
                {"action": "test_intent_fallback", "expected": "keyword_parser_used"},
                {"action": "test_world_fallback", "expected": "rule_events_used"},
                {"action": "test_scene_fallback", "expected": "triggers_used"},
                {"action": "test_npc_fallback", "expected": "goal_idle_used"},
                {"action": "test_narration_fallback", "expected": "template_used"},
                {"action": "test_parse_failure", "expected": "repair_or_fallback"},
                {"action": "test_validator_rejection", "expected": "rollback"},
                {"action": "test_timeout", "expected": "deterministic_fallback"},
                {"action": "test_perspective_leak", "expected": "sanitized_or_rejected"},
            ]
        )
        
        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 9

    def test_memory_writes_complete(self):
        """Test that all memory types are written."""
        result = self.runner.run_custom_scenario(
            "memory_writes_test",
            "session_memory_001",
            steps=[
                {"action": "execute_turn", "expected": "turn_completed"},
                {"action": "verify_world_chronicle", "expected": "chronicle_exists"},
                {"action": "verify_scene_summary", "expected": "scene_summary_exists"},
                {"action": "verify_npc_subjective", "expected": "npc_summaries_exist"},
            ]
        )
        
        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 4

    @pytest.mark.smoke
    def test_audit_replay_no_llm_recall(self):
        """Test that audit data enables replay without LLM."""
        result = self.runner.run_custom_scenario(
            "audit_replay_test",
            "session_audit_001",
            steps=[
                {"action": "execute_turn_with_proposals", "expected": "proposals_logged"},
                {"action": "verify_proposal_audits", "expected": "all_fields_present"},
                {"action": "replay_from_audit", "expected": "replay_success"},
                {"action": "verify_no_llm_calls", "expected": "zero_llm_calls"},
            ]
        )
        
        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 4

    def test_working_state_for_npc_decisions(self):
        """Test that NPC decisions use working state, not canonical."""
        result = self.runner.run_custom_scenario(
            "npc_working_state_test",
            "session_npc_001",
            steps=[
                {"action": "npc_a_decision", "expected": "npc_a_proposal"},
                {"action": "apply_to_working_state", "expected": "working_state_updated"},
                {"action": "npc_b_decision", "expected": "npc_b_sees_npc_a_effect"},
                {"action": "verify_canonical_unchanged", "expected": "canonical_intact"},
                {"action": "atomic_commit", "expected": "both_committed"},
            ]
        )
        
        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 5
