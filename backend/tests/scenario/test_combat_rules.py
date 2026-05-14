"""Scenario tests for combat rules enforcement."""

import pytest
from typing import Dict, Any, List

from llm_rpg.observability.scenario_runner import (
    ScenarioRunner,
    ScenarioType,
)
from tests.conftest import MockLLMProvider


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestCombatRules:
    """Test combat rules enforcement scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def test_attack_action_follows_combat_rules(self):
        """Test that attack action follows combat rules (damage, defense, skill)."""
        result = self.runner.run_custom_scenario(
            "attack_combat_rules",
            "session_combat_001",
            steps=[
                {
                    "action": "initialize_combat",
                    "input_data": {
                        "attacker_id": "player_hero",
                        "defender_id": "npc_bandit",
                        "attacker_stats": {"attack": 20, "skill": "sword_mastery"},
                        "defender_stats": {"defense": 10, "hp": 100},
                    },
                    "expected": "combat_initialized",
                },
                {
                    "action": "execute_attack",
                    "input_data": {
                        "attacker_id": "player_hero",
                        "target_id": "npc_bandit",
                        "attack_type": "melee",
                    },
                    "expected": "damage_calculated",
                },
                {
                    "action": "verify_damage_calculation",
                    "input_data": {
                        "expected_factors": ["base_damage", "attack_stat", "defense_reduction", "skill_modifier"],
                    },
                    "expected": "damage_follows_rules",
                },
                {
                    "action": "verify_hp_reduced",
                    "input_data": {
                        "initial_hp": 100,
                        "expected_reduction": True,
                    },
                    "expected": "target_hp_reduced",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 4

        # Verify combat initialization
        init_step = next((s for s in result.steps if s.action == "initialize_combat"), None)
        assert init_step is not None
        assert init_step.passed is True

        # Verify attack execution
        attack_step = next((s for s in result.steps if s.action == "execute_attack"), None)
        assert attack_step is not None
        assert attack_step.passed is True

        # Verify damage calculation includes required factors
        damage_step = next((s for s in result.steps if s.action == "verify_damage_calculation"), None)
        assert damage_step is not None
        assert damage_step.passed is True

    def test_npc_defends_against_attack_reducing_damage(self):
        """Test that NPC defends against attack reducing damage."""
        result = self.runner.run_custom_scenario(
            "npc_defense_rule",
            "session_combat_002",
            steps=[
                {
                    "action": "setup_combat_with_npc",
                    "input_data": {
                        "npc_id": "npc_guard",
                        "npc_defense": 15,
                        "incoming_damage": 30,
                    },
                    "expected": "combat_setup_complete",
                },
                {
                    "action": "npc_chooses_defend",
                    "input_data": {
                        "npc_id": "npc_guard",
                        "action": "defend",
                    },
                    "expected": "defend_action_chosen",
                },
                {
                    "action": "apply_defense_reduction",
                    "input_data": {
                        "base_damage": 30,
                        "defense_stat": 15,
                        "defense_multiplier": 0.5,
                    },
                    "expected": "damage_reduced",
                },
                {
                    "action": "verify_damage_reduction",
                    "input_data": {
                        "original_damage": 30,
                        "expected_final_damage": 15,  # 30 * 0.5 = 15
                    },
                    "expected": "damage_correctly_reduced",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 4

        # Verify defend action was chosen
        defend_step = next((s for s in result.steps if s.action == "npc_chooses_defend"), None)
        assert defend_step is not None
        assert defend_step.passed is True

        # Verify damage reduction applied
        reduction_step = next((s for s in result.steps if s.action == "apply_defense_reduction"), None)
        assert reduction_step is not None
        assert reduction_step.passed is True

    def test_cast_skill_validates_required_capabilities(self):
        """Test that cast skill action validates required capabilities."""
        result = self.runner.run_custom_scenario(
            "cast_skill_validation",
            "session_combat_003",
            steps=[
                {
                    "action": "setup_caster",
                    "input_data": {
                        "caster_id": "player_mage",
                        "caster_capabilities": ["fire_magic", "ice_magic"],
                        "caster_mana": 50,
                    },
                    "expected": "caster_initialized",
                },
                {
                    "action": "attempt_cast_skill",
                    "input_data": {
                        "caster_id": "player_mage",
                        "skill_name": "fireball",
                        "required_capability": "fire_magic",
                        "mana_cost": 20,
                    },
                    "expected": "skill_cast_validated",
                },
                {
                    "action": "verify_capability_check",
                    "input_data": {
                        "skill": "fireball",
                        "required": "fire_magic",
                        "caster_has": ["fire_magic", "ice_magic"],
                    },
                    "expected": "capability_present",
                },
                {
                    "action": "verify_mana_deducted",
                    "input_data": {
                        "initial_mana": 50,
                        "mana_cost": 20,
                        "expected_remaining": 30,
                    },
                    "expected": "mana_correctly_deducted",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 4

        # Verify skill cast attempt
        cast_step = next((s for s in result.steps if s.action == "attempt_cast_skill"), None)
        assert cast_step is not None
        assert cast_step.passed is True

        # Verify capability validation
        capability_step = next((s for s in result.steps if s.action == "verify_capability_check"), None)
        assert capability_step is not None
        assert capability_step.passed is True

    def test_dead_incapacitated_npc_cannot_perform_actions(self):
        """Test that dead/incapacitated NPC cannot perform actions."""
        result = self.runner.run_custom_scenario(
            "dead_npc_action_prevention",
            "session_combat_004",
            steps=[
                {
                    "action": "setup_dead_npc",
                    "input_data": {
                        "npc_id": "npc_fallen_warrior",
                        "npc_status": "dead",
                        "npc_hp": 0,
                    },
                    "expected": "dead_npc_initialized",
                },
                {
                    "action": "attempt_attack_from_dead_npc",
                    "input_data": {
                        "npc_id": "npc_fallen_warrior",
                        "action": "attack",
                        "target_id": "player_hero",
                    },
                    "expected": "action_blocked",
                },
                {
                    "action": "verify_action_rejected",
                    "input_data": {
                        "npc_status": "dead",
                        "action_attempted": "attack",
                        "expected_result": "rejected",
                    },
                    "expected": "action_rejected_due_to_death",
                },
                {
                    "action": "setup_incapacitated_npc",
                    "input_data": {
                        "npc_id": "npc_stunned_guard",
                        "npc_status": "incapacitated",
                        "incapacitation_reason": "stunned",
                    },
                    "expected": "incapacitated_npc_initialized",
                },
                {
                    "action": "attempt_action_from_incapacitated",
                    "input_data": {
                        "npc_id": "npc_stunned_guard",
                        "action": "defend",
                    },
                    "expected": "action_blocked_incapacitated",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 5

        # Verify dead NPC attack was blocked
        dead_attack_step = next((s for s in result.steps if s.action == "attempt_attack_from_dead_npc"), None)
        assert dead_attack_step is not None
        assert dead_attack_step.passed is True

        # Verify action rejection
        reject_step = next((s for s in result.steps if s.action == "verify_action_rejected"), None)
        assert reject_step is not None
        assert reject_step.passed is True

        # Verify incapacitated NPC action was blocked
        incap_step = next((s for s in result.steps if s.action == "attempt_action_from_incapacitated"), None)
        assert incap_step is not None
        assert incap_step.passed is True


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestCombatRuleEnforcementScenarioType:
    """Test using COMBAT_RULE_ENFORCEMENT ScenarioType directly."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def test_combat_rule_enforcement_scenario(self):
        """Test the predefined COMBAT_RULE_ENFORCEMENT scenario."""
        result = self.runner.run_scenario(
            ScenarioType.COMBAT_RULE_ENFORCEMENT,
            "session_combat_type_001",
            custom_setup={
                "attacker_id": "player_knight",
                "defender_id": "npc_dragon",
                "skill_name": "dragon_slayer_strike",
            },
        )

        assert result is not None
        assert result.scenario_type == ScenarioType.COMBAT_RULE_ENFORCEMENT
        assert result.test_id == "combat_rule_enforcement_001"
        assert len(result.steps) == 3

        # Verify all steps passed
        for step in result.steps:
            assert step.passed is True, f"Step {step.step_no} ({step.action}) should pass"
