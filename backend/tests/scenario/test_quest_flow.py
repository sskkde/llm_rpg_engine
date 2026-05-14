"""Scenario tests for quest flow validation."""

import pytest
from typing import Dict, Any, List

from llm_rpg.observability.scenario_runner import (
    ScenarioRunner,
    ScenarioType,
)
from tests.conftest import MockLLMProvider


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestQuestFlow:
    """Test quest flow validation scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def test_quest_stage_transitions_follow_legal_transitions(self):
        """Test that quest stage transitions follow legal transitions only (no skipping)."""
        result = self.runner.run_custom_scenario(
            "quest_legal_transitions",
            "session_quest_001",
            steps=[
                {
                    "action": "initialize_quest",
                    "input_data": {
                        "quest_id": "main_quest_rescue",
                        "stage_order": ["not_started", "accepted", "gather_info", "find_location", "rescue_target", "completed"],
                    },
                    "expected": "quest_initialized",
                },
                {
                    "action": "attempt_legal_transition",
                    "input_data": {
                        "quest_id": "main_quest_rescue",
                        "from_stage": "accepted",
                        "to_stage": "gather_info",
                    },
                    "expected": "transition_accepted",
                },
                {
                    "action": "verify_legal_transition_succeeded",
                    "input_data": {
                        "current_stage": "gather_info",
                        "transition_valid": True,
                    },
                    "expected": "stage_correctly_updated",
                },
                {
                    "action": "attempt_illegal_skip_transition",
                    "input_data": {
                        "quest_id": "main_quest_rescue",
                        "from_stage": "gather_info",
                        "to_stage": "completed",
                    },
                    "expected": "transition_rejected",
                },
                {
                    "action": "verify_illegal_transition_rejected",
                    "input_data": {
                        "current_stage": "gather_info",
                        "attempted_stage": "completed",
                        "skip_detected": True,
                    },
                    "expected": "skip_transition_blocked",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 5

        legal_step = next((s for s in result.steps if s.action == "attempt_legal_transition"), None)
        assert legal_step is not None
        assert legal_step.passed is True

        illegal_step = next((s for s in result.steps if s.action == "attempt_illegal_skip_transition"), None)
        assert illegal_step is not None
        assert illegal_step.passed is True

    def test_quest_required_facts_must_be_known_before_progression(self):
        """Test that quest required facts must be known before progression."""
        result = self.runner.run_custom_scenario(
            "quest_required_facts",
            "session_quest_002",
            steps=[
                {
                    "action": "setup_quest_with_required_facts",
                    "input_data": {
                        "quest_id": "quest_secret_passage",
                        "current_stage": "search_for_entrance",
                        "required_facts": ["ancient_map_location", "hidden_lever_mechanism"],
                        "known_facts": ["ancient_map_location"],
                    },
                    "expected": "quest_with_requirements_setup",
                },
                {
                    "action": "attempt_progression_without_all_facts",
                    "input_data": {
                        "quest_id": "quest_secret_passage",
                        "target_stage": "open_passage",
                        "missing_fact": "hidden_lever_mechanism",
                    },
                    "expected": "progression_blocked",
                },
                {
                    "action": "verify_progression_blocked_missing_fact",
                    "input_data": {
                        "required_facts": ["ancient_map_location", "hidden_lever_mechanism"],
                        "known_facts": ["ancient_map_location"],
                        "missing": ["hidden_lever_mechanism"],
                    },
                    "expected": "blocked_due_to_missing_fact",
                },
                {
                    "action": "discover_missing_fact",
                    "input_data": {
                        "fact_id": "hidden_lever_mechanism",
                        "discovery_method": "npc_dialogue",
                    },
                    "expected": "fact_discovered",
                },
                {
                    "action": "attempt_progression_with_all_facts",
                    "input_data": {
                        "quest_id": "quest_secret_passage",
                        "target_stage": "open_passage",
                        "known_facts": ["ancient_map_location", "hidden_lever_mechanism"],
                    },
                    "expected": "progression_allowed",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 5

        blocked_step = next((s for s in result.steps if s.action == "attempt_progression_without_all_facts"), None)
        assert blocked_step is not None
        assert blocked_step.passed is True

        allowed_step = next((s for s in result.steps if s.action == "attempt_progression_with_all_facts"), None)
        assert allowed_step is not None
        assert allowed_step.passed is True

    def test_quest_fail_conditions_trigger_failure_state(self):
        """Test that quest fail conditions trigger failure state."""
        result = self.runner.run_custom_scenario(
            "quest_fail_conditions",
            "session_quest_003",
            steps=[
                {
                    "action": "setup_quest_with_fail_conditions",
                    "input_data": {
                        "quest_id": "quest_escort_merchant",
                        "current_stage": "escorting",
                        "fail_conditions": ["merchant_dies", "time_exceeded", "merchant_abandoned"],
                    },
                    "expected": "quest_with_fail_conditions_setup",
                },
                {
                    "action": "trigger_fail_condition",
                    "input_data": {
                        "quest_id": "quest_escort_merchant",
                        "fail_condition": "merchant_dies",
                        "trigger_event": "merchant_killed_in_combat",
                    },
                    "expected": "fail_condition_triggered",
                },
                {
                    "action": "verify_quest_transitions_to_failed",
                    "input_data": {
                        "quest_id": "quest_escort_merchant",
                        "expected_status": "failed",
                        "failure_reason": "merchant_dies",
                    },
                    "expected": "quest_status_failed",
                },
                {
                    "action": "verify_no_further_progression_allowed",
                    "input_data": {
                        "quest_id": "quest_escort_merchant",
                        "quest_status": "failed",
                        "attempted_action": "continue_quest",
                    },
                    "expected": "progression_blocked_for_failed_quest",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 4

        trigger_step = next((s for s in result.steps if s.action == "trigger_fail_condition"), None)
        assert trigger_step is not None
        assert trigger_step.passed is True

        failed_step = next((s for s in result.steps if s.action == "verify_quest_transitions_to_failed"), None)
        assert failed_step is not None
        assert failed_step.passed is True

    def test_hidden_objectives_not_visible_until_revealed(self):
        """Test that hidden objectives are not visible to player until revealed."""
        result = self.runner.run_custom_scenario(
            "quest_hidden_objectives",
            "session_quest_004",
            steps=[
                {
                    "action": "setup_quest_with_hidden_objectives",
                    "input_data": {
                        "quest_id": "quest_mystery_investigation",
                        "visible_objectives": ["investigate_scene", "interview_witnesses"],
                        "hidden_objectives": [
                            {"id": "discover_true_culprit", "reveal_condition": "find_secret_letter"},
                            {"id": "expose_conspiracy", "reveal_condition": "discover_true_culprit"},
                        ],
                    },
                    "expected": "quest_with_hidden_objectives_setup",
                },
                {
                    "action": "get_player_visible_objectives_before_reveal",
                    "input_data": {
                        "quest_id": "quest_mystery_investigation",
                        "player_id": "player_detective",
                    },
                    "expected": "only_visible_objectives_shown",
                },
                {
                    "action": "verify_hidden_objectives_not_visible",
                    "input_data": {
                        "visible_objectives": ["investigate_scene", "interview_witnesses"],
                        "hidden_objectives": ["discover_true_culprit", "expose_conspiracy"],
                        "player_can_see_hidden": False,
                    },
                    "expected": "hidden_objectives_concealed",
                },
                {
                    "action": "trigger_reveal_condition",
                    "input_data": {
                        "quest_id": "quest_mystery_investigation",
                        "reveal_condition": "find_secret_letter",
                        "event": "player_found_secret_letter",
                    },
                    "expected": "reveal_condition_met",
                },
                {
                    "action": "verify_hidden_objective_revealed",
                    "input_data": {
                        "quest_id": "quest_mystery_investigation",
                        "newly_visible_objective": "discover_true_culprit",
                        "player_can_see": True,
                    },
                    "expected": "hidden_objective_now_visible",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 5

        hidden_step = next((s for s in result.steps if s.action == "verify_hidden_objectives_not_visible"), None)
        assert hidden_step is not None
        assert hidden_step.passed is True

        reveal_step = next((s for s in result.steps if s.action == "verify_hidden_objective_revealed"), None)
        assert reveal_step is not None
        assert reveal_step.passed is True


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestQuestFlowValidationScenarioType:
    """Test using QUEST_FLOW_VALIDATION ScenarioType directly."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def test_quest_flow_validation_scenario(self):
        """Test the predefined QUEST_FLOW_VALIDATION scenario."""
        result = self.runner.run_scenario(
            ScenarioType.QUEST_FLOW_VALIDATION,
            "session_quest_type_001",
            custom_setup={
                "quest_id": "quest_main_story",
                "valid_stages": ["not_started", "accepted", "in_progress", "completed"],
            },
        )

        assert result is not None
        assert result.scenario_type == ScenarioType.QUEST_FLOW_VALIDATION
        assert result.test_id == "quest_flow_validation_001"
        assert len(result.steps) == 3

        for step in result.steps:
            assert step.passed is True, f"Step {step.step_no} ({step.action}) should pass"
