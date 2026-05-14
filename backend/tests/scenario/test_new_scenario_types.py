"""Smoke tests for 8 new P5 scenario types."""

import pytest
from llm_rpg.observability.scenario_runner import (
    ScenarioRunner,
    ScenarioTest,
    ScenarioResult,
    ScenarioStep,
    ScenarioType,
)
from tests.conftest import MockLLMProvider


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestScenarioTypeEnum:
    """Test ScenarioType enum completeness."""

    def test_all_12_types_present(self):
        """Verify enum has exactly 12 values (4 existing + 8 new)."""
        all_types = list(ScenarioType)
        type_values = [t.value for t in all_types]
        
        assert len(all_types) == 12, f"Expected 12 types, got {len(all_types)}: {type_values}"
        
        # Original 4 types preserved
        assert "secret_leak_prevention" in type_values
        assert "important_npc_attack" in type_values
        assert "seal_countdown" in type_values
        assert "forbidden_knowledge" in type_values
        
        # New 8 types
        assert "combat_rule_enforcement" in type_values
        assert "quest_flow_validation" in type_values
        assert "save_consistency" in type_values
        assert "reproducibility" in type_values
        assert "world_time_progression" in type_values
        assert "area_summary_generation" in type_values
        assert "npc_relationship_change" in type_values
        assert "integration_full_turn" in type_values

    def test_get_available_scenarios_returns_12(self):
        """Verify get_available_scenarios() returns 12 entries."""
        runner = ScenarioRunner(llm_provider=MockLLMProvider())
        scenarios = runner.get_available_scenarios()
        assert len(scenarios) == 12, f"Expected 12 scenarios, got {len(scenarios)}"

    def test_all_scenarios_have_required_fields(self):
        """Verify all 12 scenarios have non-empty test_id, name, description, expected_outcomes."""
        runner = ScenarioRunner(llm_provider=MockLLMProvider())
        scenarios = runner.get_available_scenarios()
        
        for s in scenarios:
            assert s.test_id, f"Missing test_id for {s.scenario_type}"
            assert s.name, f"Missing name for {s.scenario_type}"
            assert s.description, f"Missing description for {s.scenario_type}"
            assert len(s.expected_outcomes) > 0, f"Missing expected_outcomes for {s.scenario_type}"


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestNewScenarioTypesSmoke:
    """Smoke test each new scenario type — instantiate, run, validate."""

    def setup_method(self):
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def _run_and_verify(self, scenario_type, session_id):
        """Helper: run a scenario and verify basic result structure."""
        result = self.runner.run_scenario(scenario_type, session_id)
        
        assert result is not None
        assert result.result_id is not None
        assert result.scenario_type == scenario_type
        assert result.session_id == session_id
        assert result.status in ["passed", "partial", "failed", "error"]
        assert len(result.steps) > 0, f"No steps for {scenario_type}"
        assert result.started_at is not None
        assert result.completed_at is not None
        assert result.duration_ms is not None
        assert result.duration_ms >= 0
        assert len(result.logs) > 0
        
        # Verify step structure
        for step in result.steps:
            assert step.step_no > 0
            assert step.action
            assert isinstance(step.input_data, dict)
            assert isinstance(step.passed, bool)
        
        # Verify pass rate calculation
        assert result.total_steps == len(result.steps)
        assert result.passed_steps + result.failed_steps == result.total_steps
        assert 0.0 <= result.pass_rate <= 1.0
        
        return result

    @pytest.mark.smoke
    def test_combat_rule_enforcement(self):
        """Verify COMBAT_RULE_ENFORCEMENT type runs and validates."""
        result = self._run_and_verify(ScenarioType.COMBAT_RULE_ENFORCEMENT, "session_combat_rules")
        
        # Should have steps for attack, defend, cast_skill enforcement
        step_actions = [s.action for s in result.steps]
        assert "verify_attack_rule" in step_actions
        assert "verify_defend_rule" in step_actions
        assert "verify_cast_skill_rule" in step_actions

    @pytest.mark.smoke
    def test_quest_flow_validation(self):
        """Verify QUEST_FLOW_VALIDATION type runs and validates."""
        result = self._run_and_verify(ScenarioType.QUEST_FLOW_VALIDATION, "session_quest_flow")
        
        step_actions = [s.action for s in result.steps]
        assert "verify_valid_transition" in step_actions
        assert "verify_no_illegal_jump" in step_actions
        assert "verify_quest_stage_order" in step_actions

    @pytest.mark.smoke
    def test_save_consistency(self):
        """Verify SAVE_CONSISTENCY type runs and validates."""
        result = self._run_and_verify(ScenarioType.SAVE_CONSISTENCY, "session_save")
        
        step_actions = [s.action for s in result.steps]
        assert "create_initial_state" in step_actions
        assert "save_state" in step_actions
        assert "load_state" in step_actions
        assert "verify_state_match" in step_actions

    @pytest.mark.smoke
    def test_reproducibility(self):
        """Verify REPRODUCIBILITY type runs and validates."""
        result = self._run_and_verify(ScenarioType.REPRODUCIBILITY, "session_repro")
        
        step_actions = [s.action for s in result.steps]
        assert "set_seed" in step_actions
        assert "run_first_pass" in step_actions
        assert "run_second_pass" in step_actions
        assert "verify_identical_results" in step_actions

    @pytest.mark.smoke
    def test_world_time_progression(self):
        """Verify WORLD_TIME_PROGRESSION type runs and validates."""
        result = self._run_and_verify(ScenarioType.WORLD_TIME_PROGRESSION, "session_world_time")
        
        step_actions = [s.action for s in result.steps]
        assert "initialize_world_time" in step_actions
        assert "execute_actions" in step_actions
        assert "verify_time_advanced" in step_actions

    @pytest.mark.smoke
    def test_area_summary_generation(self):
        """Verify AREA_SUMMARY_GENERATION type runs and validates."""
        result = self._run_and_verify(ScenarioType.AREA_SUMMARY_GENERATION, "session_area_summary")
        
        step_actions = [s.action for s in result.steps]
        assert "setup_current_area" in step_actions
        assert "leave_area" in step_actions
        assert "verify_summary_generated" in step_actions
        assert "verify_summary_content" in step_actions

    @pytest.mark.smoke
    def test_npc_relationship_change(self):
        """Verify NPC_RELATIONSHIP_CHANGE type runs and validates."""
        result = self._run_and_verify(ScenarioType.NPC_RELATIONSHIP_CHANGE, "session_npc_rel")
        
        step_actions = [s.action for s in result.steps]
        assert "initialize_relationship" in step_actions
        assert "trigger_relationship_event" in step_actions
        assert "verify_relationship_changed" in step_actions

    @pytest.mark.smoke
    def test_integration_full_turn(self):
        """Verify INTEGRATION_FULL_TURN type runs and validates."""
        result = self._run_and_verify(ScenarioType.INTEGRATION_FULL_TURN, "session_full_turn")
        
        step_actions = [s.action for s in result.steps]
        assert "receive_player_input" in step_actions
        assert "process_turn_pipeline" in step_actions
        assert "verify_state_committed" in step_actions
        assert "verify_audit_logged" in step_actions


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestBackwardCompatibility:
    """Ensure existing 4 types still work exactly as before."""

    def setup_method(self):
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def test_existing_types_still_runnable(self):
        """All 4 original types run without error."""
        for stype in [
            ScenarioType.SECRET_LEAK_PREVENTION,
            ScenarioType.IMPORTANT_NPC_ATTACK,
            ScenarioType.SEAL_COUNTDOWN,
            ScenarioType.FORBIDDEN_KNOWLEDGE,
        ]:
            result = self.runner.run_scenario(stype, "session_compat")
            assert result.status != "error"
            assert len(result.steps) > 0

    def test_original_type_count_in_enum(self):
        """ScenarioType enum still contains original 4 types."""
        type_values = [t.value for t in ScenarioType]
        assert ScenarioType.SECRET_LEAK_PREVENTION.value in type_values
        assert ScenarioType.IMPORTANT_NPC_ATTACK.value in type_values
        assert ScenarioType.SEAL_COUNTDOWN.value in type_values
        assert ScenarioType.FORBIDDEN_KNOWLEDGE.value in type_values

    def test_get_available_includes_originals(self):
        """get_available_scenarios still returns original 4 types."""
        runner = ScenarioRunner(llm_provider=MockLLMProvider())
        scenarios = runner.get_available_scenarios()
        types_in_list = [s.scenario_type for s in scenarios]
        
        assert ScenarioType.SECRET_LEAK_PREVENTION in types_in_list
        assert ScenarioType.IMPORTANT_NPC_ATTACK in types_in_list
        assert ScenarioType.SEAL_COUNTDOWN in types_in_list
        assert ScenarioType.FORBIDDEN_KNOWLEDGE in types_in_list


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestRunAllScenarios:
    """Test running all 12 scenarios at once."""

    def setup_method(self):
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def test_run_all_scenarios_returns_12(self):
        """run_all_scenarios() returns 12 results."""
        results = self.runner.run_all_scenarios("session_all_12")
        assert len(results) == 12, f"Expected 12 results, got {len(results)}"
        
        scenario_types = [r.scenario_type for r in results]
        for stype in ScenarioType:
            assert stype in scenario_types, f"Missing {stype} in results"
        
        for result in results:
            assert result.session_id == "session_all_12"
            assert result.status != "error"
            assert len(result.steps) > 0
