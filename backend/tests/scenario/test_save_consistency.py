"""Scenario tests for save consistency and reproducibility.

Tests verify that:
1. Save and reload produces identical game state
2. NPC memory scope is preserved correctly
3. Quest stages are preserved correctly
4. Combat state is preserved after save/reload
5. Multiple saves in same session don't corrupt state
6. Same random seed produces same LLM output
"""

import pytest

from llm_rpg.observability.scenario_runner import (
    ScenarioRunner,
    ScenarioType,
)
from tests.conftest import MockLLMProvider


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestSaveConsistency:
    """Test save and reload consistency scenarios."""

    mock_provider: MockLLMProvider
    runner: ScenarioRunner

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def test_save_and_reload_produces_identical_game_state(self):
        """Test that save and reload produces identical game state (all top-level keys match)."""
        result = self.runner.run_scenario(
            ScenarioType.SAVE_CONSISTENCY,
            "session_save_001",
            custom_setup={
                "player_hp": 100,
                "player_mp": 50,
                "location": "village_square",
                "quest_stage": "in_progress",
                "inventory": ["sword", "potion"],
                "party_members": ["hero", "mage"],
            },
        )

        assert result is not None
        assert result.scenario_type == ScenarioType.SAVE_CONSISTENCY
        assert result.test_id == "save_consistency_001"
        assert len(result.steps) == 4

        # Verify all steps passed
        for step in result.steps:
            assert step.passed is True, f"Step {step.step_no} ({step.action}) should pass"

        # Verify state match step specifically
        match_step = next((s for s in result.steps if s.action == "verify_state_match"), None)
        assert match_step is not None
        assert match_step.actual_result is not None
        assert "identical" in match_step.actual_result.lower()

    def test_save_and_reload_preserves_npc_memory_scope(self):
        """Test that save and reload preserves NPC memory scope correctly."""
        # Initial NPC state with memory scope
        npc_initial = {
            "npc_id": "npc_elder_sage",
            "name": "Elder Sage",
            "memory_scope": {
                "known_facts": ["village_history", "ancient_ritual"],
                "beliefs": ["player_is_trustworthy", "seal_is_weakening"],
                "secrets": ["true_purpose_of_seal"],
                "forget_curve": {"ancient_ritual": 0.95, "village_history": 0.80},
            },
            "location": "temple",
            "attitude": "friendly",
        }

        result = self.runner.run_custom_scenario(
            "npc_memory_scope_preservation",
            "session_save_002",
            steps=[
                {
                    "action": "create_npc_with_memory_scope",
                    "input_data": {"npc": npc_initial},
                    "expected": "npc_created_with_memory_scope",
                },
                {
                    "action": "save_game_state",
                    "input_data": {"npcs": [npc_initial]},
                    "expected": "state_saved",
                },
                {
                    "action": "reload_game_state",
                    "input_data": {},
                    "expected": "state_reloaded",
                },
                {
                    "action": "verify_npc_memory_scope_intact",
                    "input_data": {
                        "expected_known_facts": ["village_history", "ancient_ritual"],
                        "expected_beliefs": ["player_is_trustworthy", "seal_is_weakening"],
                        "expected_secrets": ["true_purpose_of_seal"],
                    },
                    "expected": "npc_memory_scope_preserved",
                },
                {
                    "action": "verify_forget_curve_preserved",
                    "input_data": {
                        "expected_curve": {"ancient_ritual": 0.95, "village_history": 0.80},
                    },
                    "expected": "forget_curve_intact",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 5

        # Verify memory scope step
        memory_step = next((s for s in result.steps if s.action == "verify_npc_memory_scope_intact"), None)
        assert memory_step is not None
        assert memory_step.passed is True

        # Verify forget curve step
        curve_step = next((s for s in result.steps if s.action == "verify_forget_curve_preserved"), None)
        assert curve_step is not None
        assert curve_step.passed is True

    def test_save_and_reload_preserves_quest_stages(self):
        """Test that save and reload preserves quest stages correctly."""
        # Multiple quests at different stages
        quests_initial = [
            {
                "quest_id": "main_quest_seal",
                "stage": "find_artifacts",
                "stage_order": ["not_started", "accepted", "find_artifacts", "perform_ritual", "completed"],
                "progress": 0.6,
                "objectives_completed": ["speak_to_elder", "locate_first_artifact"],
                "objectives_remaining": ["locate_second_artifact", "perform_ritual"],
            },
            {
                "quest_id": "side_quest_herbs",
                "stage": "in_progress",
                "stage_order": ["not_started", "accepted", "in_progress", "completed"],
                "progress": 0.5,
                "objectives_completed": ["gather_herbs"],
                "objectives_remaining": ["deliver_herbs"],
            },
            {
                "quest_id": "side_quest_blacksmith",
                "stage": "completed",
                "stage_order": ["not_started", "accepted", "in_progress", "completed"],
                "progress": 1.0,
                "objectives_completed": ["find_ore", "forge_sword", "deliver_sword"],
                "objectives_remaining": [],
            },
        ]

        result = self.runner.run_custom_scenario(
            "quest_stage_preservation",
            "session_save_003",
            steps=[
                {
                    "action": "create_quests_at_various_stages",
                    "input_data": {"quests": quests_initial},
                    "expected": "quests_created",
                },
                {
                    "action": "save_game_state",
                    "input_data": {"quests": quests_initial},
                    "expected": "state_saved",
                },
                {
                    "action": "reload_game_state",
                    "input_data": {},
                    "expected": "state_reloaded",
                },
                {
                    "action": "verify_main_quest_stage_preserved",
                    "input_data": {
                        "quest_id": "main_quest_seal",
                        "expected_stage": "find_artifacts",
                        "expected_progress": 0.6,
                    },
                    "expected": "main_quest_stage_correct",
                },
                {
                    "action": "verify_side_quest_in_progress_preserved",
                    "input_data": {
                        "quest_id": "side_quest_herbs",
                        "expected_stage": "in_progress",
                        "expected_objectives_completed": ["gather_herbs"],
                    },
                    "expected": "side_quest_progress_correct",
                },
                {
                    "action": "verify_completed_quest_stays_completed",
                    "input_data": {
                        "quest_id": "side_quest_blacksmith",
                        "expected_stage": "completed",
                        "expected_progress": 1.0,
                    },
                    "expected": "completed_quest_preserved",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 6

        # Verify all quest stage steps passed
        quest_steps = [s for s in result.steps if "quest" in s.action.lower() and "verify" in s.action.lower()]
        assert len(quest_steps) == 3
        for step in quest_steps:
            assert step.passed is True, f"Quest step {step.action} should pass"

    def test_save_after_combat_preserves_combat_state(self):
        """Test that save after combat and reload preserves combat state."""
        # Combat state with various details
        combat_state = {
            "combat_id": "combat_goblin_ambush_001",
            "status": "active",
            "turn": 3,
            "current_actor": "player_hero",
            "initiative_order": ["player_hero", "mage_companion", "goblin_scout_1", "goblin_scout_2"],
            "participants": [
                {
                    "entity_id": "player_hero",
                    "hp": 75,
                    "max_hp": 100,
                    "mp": 30,
                    "max_mp": 50,
                    "status_effects": [],
                    "position": {"x": 2, "y": 3},
                },
                {
                    "entity_id": "mage_companion",
                    "hp": 40,
                    "max_hp": 60,
                    "mp": 10,
                    "max_mp": 80,
                    "status_effects": ["burning"],
                    "position": {"x": 1, "y": 2},
                },
                {
                    "entity_id": "goblin_scout_1",
                    "hp": 5,
                    "max_hp": 25,
                    "mp": 0,
                    "max_mp": 0,
                    "status_effects": ["poisoned"],
                    "position": {"x": 4, "y": 3},
                },
                {
                    "entity_id": "goblin_scout_2",
                    "hp": 0,
                    "max_hp": 25,
                    "mp": 0,
                    "max_mp": 0,
                    "status_effects": [],
                    "position": {"x": 5, "y": 4},
                },
            ],
            "environmental_effects": ["fog", "difficult_terrain"],
            "loot_pending": ["goblin_ear", "rusty_dagger"],
        }

        result = self.runner.run_custom_scenario(
            "combat_state_preservation",
            "session_save_004",
            steps=[
                {
                    "action": "create_active_combat_session",
                    "input_data": {"combat": combat_state},
                    "expected": "combat_session_created",
                },
                {
                    "action": "save_game_state_mid_combat",
                    "input_data": {"combat": combat_state},
                    "expected": "combat_state_saved",
                },
                {
                    "action": "reload_game_state",
                    "input_data": {},
                    "expected": "state_reloaded",
                },
                {
                    "action": "verify_combat_status_preserved",
                    "input_data": {
                        "expected_status": "active",
                        "expected_turn": 3,
                    },
                    "expected": "combat_status_correct",
                },
                {
                    "action": "verify_participant_hp_mp_preserved",
                    "input_data": {
                        "player_hp": 75,
                        "mage_hp": 40,
                        "mage_mp": 10,
                    },
                    "expected": "hp_mp_values_correct",
                },
                {
                    "action": "verify_status_effects_preserved",
                    "input_data": {
                        "mage_effects": ["burning"],
                        "goblin_effects": ["poisoned"],
                    },
                    "expected": "status_effects_intact",
                },
                {
                    "action": "verify_initiative_order_preserved",
                    "input_data": {
                        "expected_order": ["player_hero", "mage_companion", "goblin_scout_1", "goblin_scout_2"],
                    },
                    "expected": "initiative_order_correct",
                },
                {
                    "action": "verify_loot_pending_preserved",
                    "input_data": {
                        "expected_loot": ["goblin_ear", "rusty_dagger"],
                    },
                    "expected": "loot_pending_intact",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 8

        # Verify combat-specific steps
        combat_verify_steps = [s for s in result.steps if "verify" in s.action and "combat" in s.action.lower()]
        for step in combat_verify_steps:
            assert step.passed is True, f"Combat verify step {step.action} should pass"

    def test_multiple_saves_same_session_no_corruption(self):
        """Test that multiple saves in same session don't corrupt state."""
        # Simulate multiple save operations
        initial_state = {
            "player_hp": 100,
            "player_mp": 50,
            "gold": 500,
            "location": "village_square",
            "quests": ["main_quest_001"],
            "turn_count": 0,
        }

        result = self.runner.run_custom_scenario(
            "multiple_saves_consistency",
            "session_save_005",
            steps=[
                {
                    "action": "create_initial_state",
                    "input_data": {"state": initial_state},
                    "expected": "initial_state_created",
                },
                {
                    "action": "first_save",
                    "input_data": {"save_slot": 1},
                    "expected": "first_save_completed",
                },
                {
                    "action": "modify_state_turn_1",
                    "input_data": {
                        "changes": {
                            "player_hp": 90,
                            "gold": 520,
                            "turn_count": 1,
                        }
                    },
                    "expected": "state_modified_turn_1",
                },
                {
                    "action": "second_save",
                    "input_data": {"save_slot": 2},
                    "expected": "second_save_completed",
                },
                {
                    "action": "modify_state_turn_2",
                    "input_data": {
                        "changes": {
                            "player_hp": 75,
                            "location": "forest_path",
                            "turn_count": 2,
                        }
                    },
                    "expected": "state_modified_turn_2",
                },
                {
                    "action": "third_save",
                    "input_data": {"save_slot": 3},
                    "expected": "third_save_completed",
                },
                {
                    "action": "load_first_save",
                    "input_data": {"save_slot": 1},
                    "expected": "first_save_loaded",
                },
                {
                    "action": "verify_first_save_state",
                    "input_data": {
                        "expected_hp": 100,
                        "expected_gold": 500,
                        "expected_turn_count": 0,
                    },
                    "expected": "first_save_state_correct",
                },
                {
                    "action": "load_second_save",
                    "input_data": {"save_slot": 2},
                    "expected": "second_save_loaded",
                },
                {
                    "action": "verify_second_save_state",
                    "input_data": {
                        "expected_hp": 90,
                        "expected_gold": 520,
                        "expected_turn_count": 1,
                    },
                    "expected": "second_save_state_correct",
                },
                {
                    "action": "load_third_save",
                    "input_data": {"save_slot": 3},
                    "expected": "third_save_loaded",
                },
                {
                    "action": "verify_third_save_state",
                    "input_data": {
                        "expected_hp": 75,
                        "expected_location": "forest_path",
                        "expected_turn_count": 2,
                    },
                    "expected": "third_save_state_correct",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 12

        # Verify all save/load verification steps passed
        verify_steps = [s for s in result.steps if "verify" in s.action and "save" in s.action.lower()]
        assert len(verify_steps) == 3
        for step in verify_steps:
            assert step.passed is True, f"Verify step {step.action} should pass"

    def test_same_random_seed_produces_same_llm_output(self):
        """Test that same random seed produces same LLM output (when using MockProvider)."""
        result = self.runner.run_scenario(
            ScenarioType.REPRODUCIBILITY,
            "session_save_006",
            custom_setup={
                "seed": 42,
            },
        )

        assert result is not None
        assert result.scenario_type == ScenarioType.REPRODUCIBILITY
        assert result.test_id == "reproducibility_001"
        assert len(result.steps) == 4

        # Verify all steps passed
        for step in result.steps:
            assert step.passed is True, f"Step {step.step_no} ({step.action}) should pass"

        # Verify identical results step
        identical_step = next((s for s in result.steps if s.action == "verify_identical_results"), None)
        assert identical_step is not None
        assert identical_step.actual_result is not None
        assert "identical" in identical_step.actual_result.lower()


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestSaveConsistencyDetailed:
    """Detailed tests for save consistency edge cases."""

    mock_provider: MockLLMProvider
    runner: ScenarioRunner

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    def test_save_preserves_nested_data_structures(self):
        """Test that save preserves deeply nested data structures."""
        nested_state = {
            "world": {
                "regions": {
                    "northern_lands": {
                        "cities": ["winterhold", "frostpeak"],
                        "dungeons": {
                            "ice_cavern": {"cleared": True, "loot_taken": ["frost_sword"]},
                            "frozen_tomb": {"cleared": False, "loot_taken": []},
                        },
                    },
                    "southern_reach": {
                        "cities": ["sunport", "desert_oasis"],
                        "dungeons": {},
                    },
                },
            },
            "player": {
                "equipment": {
                    "main_hand": {"id": "frost_sword", "enchantments": ["ice_damage", "sharpness"]},
                    "off_hand": None,
                    "armor": {
                        "head": {"id": "leather_helm", "defense": 5},
                        "chest": {"id": "chainmail", "defense": 15},
                    },
                },
            },
        }

        result = self.runner.run_custom_scenario(
            "nested_structure_preservation",
            "session_save_007",
            steps=[
                {
                    "action": "create_nested_state",
                    "input_data": {"state": nested_state},
                    "expected": "nested_state_created",
                },
                {
                    "action": "save_game_state",
                    "input_data": {"state": nested_state},
                    "expected": "state_saved",
                },
                {
                    "action": "reload_game_state",
                    "input_data": {},
                    "expected": "state_reloaded",
                },
                {
                    "action": "verify_world_regions_preserved",
                    "input_data": {
                        "expected_regions": ["northern_lands", "southern_reach"],
                    },
                    "expected": "regions_preserved",
                },
                {
                    "action": "verify_dungeon_cleared_status_preserved",
                    "input_data": {
                        "ice_cavern_cleared": True,
                        "frozen_tomb_cleared": False,
                    },
                    "expected": "dungeon_status_correct",
                },
                {
                    "action": "verify_equipment_enchantments_preserved",
                    "input_data": {
                        "enchantments": ["ice_damage", "sharpness"],
                    },
                    "expected": "enchantments_intact",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 6

    def test_save_preserves_temporal_data(self):
        """Test that save preserves temporal data correctly."""
        temporal_state = {
            "world_time": {
                "day": 15,
                "hour": 14,
                "minute": 30,
                "season": "spring",
                "year": 1247,
            },
            "timers": [
                {"id": "buff_haste", "remaining_turns": 3, "source": "potion"},
                {"id": "debuff_poison", "remaining_turns": 1, "source": "enemy"},
                {"id": "quest_countdown", "remaining_turns": 20, "source": "system"},
            ],
            "cooldowns": {
                "skill_fireball": {"remaining_turns": 2, "max_cooldown": 5},
                "skill_heal": {"remaining_turns": 0, "max_cooldown": 3},
            },
        }

        result = self.runner.run_custom_scenario(
            "temporal_data_preservation",
            "session_save_008",
            steps=[
                {
                    "action": "create_temporal_state",
                    "input_data": {"state": temporal_state},
                    "expected": "temporal_state_created",
                },
                {
                    "action": "save_game_state",
                    "input_data": {"state": temporal_state},
                    "expected": "state_saved",
                },
                {
                    "action": "reload_game_state",
                    "input_data": {},
                    "expected": "state_reloaded",
                },
                {
                    "action": "verify_world_time_preserved",
                    "input_data": {
                        "day": 15,
                        "hour": 14,
                        "season": "spring",
                    },
                    "expected": "world_time_correct",
                },
                {
                    "action": "verify_timers_preserved",
                    "input_data": {
                        "haste_turns": 3,
                        "poison_turns": 1,
                        "quest_turns": 20,
                    },
                    "expected": "timers_correct",
                },
                {
                    "action": "verify_cooldowns_preserved",
                    "input_data": {
                        "fireball_cooldown": 2,
                        "heal_cooldown": 0,
                    },
                    "expected": "cooldowns_correct",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 6
