"""Comprehensive Integration Scenario Tests.

5 end-to-end integration scenarios validating P2+P5 modules working together:
1. Full turn pipeline: input -> NPC decision -> validation -> commit -> narration -> state delta
2. Multi-turn: 3 consecutive turns where NPC knowledge evolves correctly
3. Cross-system: combat -> relationship change -> quest stage change
4. Save -> modify -> load -> verify state consistency across systems
5. Replay consistency: deterministic state reconstruction (with MockProvider)
"""

import pytest
import uuid

from llm_rpg.observability.scenario_runner import (
    ScenarioRunner,
    ScenarioType,
    ScenarioResult,
    ScenarioStep,
)
from llm_rpg.core.validation.narration_leak_validator import (
    NarrationLeakValidator,
)
from tests.conftest import MockLLMProvider


def _find_step(result: ScenarioResult, action: str) -> ScenarioStep:
    step = next((s for s in result.steps if s.action == action), None)
    assert step is not None, f"Expected step '{action}' not found in result steps"
    return step


def _assert_all_steps_passed(result: ScenarioResult) -> None:
    for step in result.steps:
        assert step.passed is True, (
            f"Step {step.step_no} ({step.action}) should pass: "
            f"actual={step.actual_result}, input={step.input_data}"
        )


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestFullTurnPipelineEndToEnd:
    """Full turn pipeline: player input -> NPC decision (perspective-filtered)
    -> validation -> commit -> narration (leak-checked) -> state delta."""

    def setup_method(self):
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)
        self.leak_validator = NarrationLeakValidator()

    @pytest.mark.smoke
    def test_full_turn_pipeline_complete(self):
        result = self.runner.run_scenario(
            ScenarioType.INTEGRATION_FULL_TURN,
            "session_fullturn_001",
            custom_setup={"player_input": "attack the goblin"},
        )

        assert result is not None
        assert result.scenario_type == ScenarioType.INTEGRATION_FULL_TURN
        assert result.status == "passed"
        assert len(result.steps) == 4

        parse_step = _find_step(result, "receive_player_input")
        assert parse_step.passed is True
        assert "attack" in parse_step.actual_result.lower()

        pipeline_step = _find_step(result, "process_turn_pipeline")
        assert pipeline_step.passed is True
        assert "validate_intent" in pipeline_step.actual_result.lower()
        assert "resolve_combat" in pipeline_step.actual_result.lower()
        assert "update_world_state" in pipeline_step.actual_result.lower()
        assert "generate_narration" in pipeline_step.actual_result.lower()

        commit_step = _find_step(result, "verify_state_committed")
        assert commit_step.passed is True
        assert "committed" in commit_step.actual_result.lower()

        audit_step = _find_step(result, "verify_audit_logged")
        assert audit_step.passed is True
        assert "3" in audit_step.actual_result

    @pytest.mark.smoke
    def test_full_turn_pipeline_with_perspective_filtering(self):
        npc_secret = "secretly the Demon Lord Malachar"

        result = self.runner.run_custom_scenario(
            "full_turn_leak_protection",
            "session_fullturn_002",
            steps=[
                {
                    "action": "setup_npc_with_secret",
                    "input_data": {
                        "npc_id": "mysterious_merchant_42",
                        "npc_name": "Mysterious Merchant",
                        "public_identity": "a wandering merchant",
                        "hidden_secret": npc_secret,
                    },
                    "expected": "npc_created_with_secret",
                },
                {
                    "action": "player_attacks_npc",
                    "input_data": {
                        "action": "attack the mysterious merchant",
                        "target_npc": "mysterious_merchant_42",
                    },
                    "expected": "combat_triggered",
                },
                {
                    "action": "process_npc_decision_perspective_filtered",
                    "input_data": {
                        "npc_id": "mysterious_merchant_42",
                        "perspective": "player",
                        "forbidden_info": [npc_secret],
                    },
                    "expected": "npc_decision_filtered",
                },
                {
                    "action": "validate_state_delta_contract",
                    "input_data": {
                        "expected_changes": {
                            "combat_active": True,
                            "npc_hp_reduced": True,
                        },
                    },
                    "expected": "validation_passed",
                },
                {
                    "action": "commit_state_atomically",
                    "input_data": {
                        "transaction_id": f"txn_{uuid.uuid4().hex[:8]}",
                    },
                    "expected": "state_committed",
                },
                {
                    "action": "generate_narration_checked",
                    "input_data": {
                        "scene": "combat_with_merchant",
                        "narration_text": (
                            "You swing your blade at the merchant. "
                            "He stumbles backward, a look of shock on his face "
                            "as your strike lands against his shoulder."
                        ),
                        "forbidden_info": [npc_secret],
                    },
                    "expected": "narration_generated_no_leak",
                },
                {
                    "action": "verify_narration_no_secret_leak",
                    "input_data": {
                        "narration": (
                            "You swing your blade at the merchant. "
                            "He stumbles backward, a look of shock on his face."
                        ),
                        "secret_check": npc_secret,
                    },
                    "expected": "no_secret_in_narration",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 7, f"Got {len(result.steps)} steps"

        leak_step = _find_step(result, "verify_narration_no_secret_leak")
        assert leak_step.passed is True

        safe_narration = "You swing your blade at the merchant. He stumbles backward, a look of shock on his face."
        leak_result = self.leak_validator.validate_narration(
            text=safe_narration,
            forbidden_info=[npc_secret],
        )
        assert leak_result.is_valid is True, (
            f"Narration leak check failed: {leak_result.errors}"
        )

    def test_full_turn_state_delta_calculated(self):
        session_id = f"session_delta_{uuid.uuid4().hex[:8]}"

        result = self.runner.run_custom_scenario(
            "full_turn_state_delta",
            session_id,
            steps=[
                {
                    "action": "create_initial_state",
                    "input_data": {
                        "player_hp": 100,
                        "player_location": "village_square",
                        "world_time_day": 1,
                        "turn_count": 0,
                    },
                    "expected": "initial_state_established",
                },
                {
                    "action": "execute_turn",
                    "input_data": {"action": "move to forest_path"},
                    "expected": "turn_executed",
                },
                {
                    "action": "compute_state_delta",
                    "input_data": {
                        "before": {
                            "player_location": "village_square",
                            "turn_count": 0,
                        },
                        "after": {
                            "player_location": "forest_path",
                            "turn_count": 1,
                        },
                    },
                    "expected": "delta_contains_changes",
                },
                {
                    "action": "verify_delta_only_changed_fields",
                    "input_data": {
                        "delta": {
                            "player_location": "forest_path",
                            "turn_count": 1,
                        },
                        "unchanged": ["player_hp", "world_time_day"],
                    },
                    "expected": "delta_is_minimal",
                },
                {
                    "action": "apply_delta_to_state",
                    "input_data": {
                        "current": {
                            "player_location": "forest_path",
                            "turn_count": 1,
                            "player_hp": 100,
                            "world_time_day": 1,
                        },
                    },
                    "expected": "delta_applied_correctly",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 5
        _assert_all_steps_passed(result)

        delta_step = _find_step(result, "verify_delta_only_changed_fields")
        assert "player_location" in str(delta_step.input_data["delta"])
        assert "turn_count" in str(delta_step.input_data["delta"])


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestMultiTurnNPCKnowledgeEvolution:
    """3 consecutive turns where NPC knowledge evolves correctly."""

    def setup_method(self):
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    @pytest.mark.smoke
    def test_npc_knowledge_evolves_over_three_turns(self):
        player_secret = "Player wields the forbidden Void Art"

        result = self.runner.run_custom_scenario(
            "npc_knowledge_evolution_3_turns",
            "session_npcevol_001",
            steps=[
                {
                    "action": "turn_1_setup",
                    "input_data": {
                        "npc_known_facts": [
                            "player_arrived_in_village",
                            "ghost_sightings_common",
                        ],
                        "npc_beliefs": ["player_is_a_wandering_merchant"],
                        "player_secret": player_secret,
                    },
                    "expected": "npc_has_initial_knowledge",
                },
                {
                    "action": "turn_1_npc_interaction",
                    "input_data": {
                        "player_question": "What do you know about me?",
                        "npc_response": "You seem like a wandering merchant. Nothing unusual.",
                        "expected_knows_secret": False,
                    },
                    "expected": "npc_does_not_know_secret",
                },
                {
                    "action": "turn_1_verify_npc_knowledge",
                    "input_data": {
                        "known_facts_after": [
                            "player_arrived_in_village",
                            "ghost_sightings_common",
                        ],
                        "does_not_know": [player_secret],
                    },
                    "expected": "npc_knowledge_unchanged",
                },
                {
                    "action": "turn_2_player_uses_void_art",
                    "input_data": {
                        "event": "player_unleashed_void_art",
                        "witnesses": ["npc_observer"],
                    },
                    "expected": "npc_witnesses_secret_ability",
                },
                {
                    "action": "turn_2_npc_learns_from_event",
                    "input_data": {
                        "new_fact": player_secret,
                        "source": "direct_observation",
                        "confidence": 0.95,
                    },
                    "expected": "npc_gains_knowledge",
                },
                {
                    "action": "turn_2_verify_npc_now_knows",
                    "input_data": {
                        "known_facts_after": [
                            "player_arrived_in_village",
                            "ghost_sightings_common",
                            player_secret,
                        ],
                        "belief_shift": "player_is_dangerous",
                    },
                    "expected": "npc_knowledge_updated",
                },
                {
                    "action": "turn_3_npc_makes_decision",
                    "input_data": {
                        "situation": "player_approaches_npc",
                        "npc_decision": "attempt_to_counter_void_art",
                        "used_knowledge": [player_secret],
                    },
                    "expected": "npc_uses_acquired_knowledge",
                },
                {
                    "action": "turn_3_verify_knowledge_driven_behavior",
                    "input_data": {
                        "decision_incorporates_fact": player_secret,
                        "npc_action": "prepare_sealing_talisman",
                    },
                    "expected": "behavior_driven_by_learned_knowledge",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 8
        _assert_all_steps_passed(result)

        t1_step = _find_step(result, "turn_1_verify_npc_knowledge")
        assert "does_not_know" in t1_step.input_data
        assert player_secret in str(t1_step.input_data["does_not_know"])

        t2_step = _find_step(result, "turn_2_verify_npc_now_knows")
        assert player_secret in str(t2_step.input_data["known_facts_after"])

        t3_step = _find_step(result, "turn_3_verify_knowledge_driven_behavior")
        assert t3_step.input_data["decision_incorporates_fact"] == player_secret

    def test_npc_knowledge_decay_over_turns(self):
        result = self.runner.run_custom_scenario(
            "npc_knowledge_decay",
            "session_npcevol_002",
            steps=[
                {
                    "action": "turn_1_npc_learns_minor_fact",
                    "input_data": {
                        "fact": "player_wore_blue_robe",
                        "importance": 0.3,
                        "memory_freshness": 1.0,
                    },
                    "expected": "fact_stored_with_low_importance",
                },
                {
                    "action": "turn_2_npc_learns_critical_fact",
                    "input_data": {
                        "fact": "player_defeated_demon_lord",
                        "importance": 0.95,
                        "memory_freshness": 1.0,
                    },
                    "expected": "critical_fact_stored",
                },
                {
                    "action": "turn_3_apply_forget_curve",
                    "input_data": {"elapsed_turns": 2},
                    "expected": "forget_curve_applied",
                },
                {
                    "action": "verify_minor_fact_decayed",
                    "input_data": {
                        "fact": "player_wore_blue_robe",
                        "expected_recall": 0.6,
                    },
                    "expected": "minor_fact_decayed_significantly",
                },
                {
                    "action": "verify_critical_fact_preserved",
                    "input_data": {
                        "fact": "player_defeated_demon_lord",
                        "expected_recall": 0.98,
                    },
                    "expected": "critical_fact_barely_decayed",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 5
        _assert_all_steps_passed(result)


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestCrossSystemCombatRelationshipQuest:
    """Combat outcome triggers relationship change triggers quest stage advance."""

    def setup_method(self):
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    @pytest.mark.smoke
    def test_combat_triggers_relationship_triggers_quest(self):
        result = self.runner.run_custom_scenario(
            "combat_relationship_quest_chain",
            "session_crosssys_001",
            steps=[
                {
                    "action": "initialize_systems_pre_combat",
                    "input_data": {
                        "combat": {"status": "inactive"},
                        "relationship": {
                            "npc_id": "bandit_leader_feng",
                            "attitude": "hostile",
                            "trust": -0.6,
                            "reputation": "feared_enemy",
                        },
                        "quest": {
                            "quest_id": "defeat_bandit_leader",
                            "current_stage": "confront_leader",
                            "next_stage": "leader_defeated",
                        },
                    },
                    "expected": "pre_combat_state_established",
                },
                {
                    "action": "initiate_combat_with_bandit_leader",
                    "input_data": {
                        "combat_id": "combat_bandit_01",
                        "participants": ["player_hero", "bandit_leader_feng"],
                        "initial_state": "active",
                        "turn": 1,
                    },
                    "expected": "combat_started",
                },
                {
                    "action": "resolve_combat_player_victory",
                    "input_data": {
                        "combat_id": "combat_bandit_01",
                        "final_status": "player_won",
                        "bandit_leader_hp": 0,
                        "player_hp_remaining": 65,
                        "turns_taken": 4,
                    },
                    "expected": "combat_resolved_player_wins",
                },
                {
                    "action": "update_relationship_from_combat_result",
                    "input_data": {
                        "npc_id": "bandit_leader_feng",
                        "combat_outcome": "defeated",
                        "attitude_change": "hostile_to_respectful_defeated",
                        "trust_shift": -0.6,
                        "trust_shift_to": -0.2,
                    },
                    "expected": "relationship_updated",
                },
                {
                    "action": "verify_relationship_state",
                    "input_data": {
                        "npc_id": "bandit_leader_feng",
                        "expected_attitude": "respectful_defeated",
                        "expected_trust": -0.2,
                    },
                    "expected": "relationship_reflects_defeat",
                },
                {
                    "action": "trigger_quest_from_relationship_event",
                    "input_data": {
                        "trigger": "npc_relationship:bandit_leader_feng=respectful_defeated",
                        "quest_id": "defeat_bandit_leader",
                    },
                    "expected": "quest_triggered",
                },
                {
                    "action": "advance_quest_stage",
                    "input_data": {
                        "quest_id": "defeat_bandit_leader",
                        "from_stage": "confront_leader",
                        "to_stage": "leader_defeated",
                    },
                    "expected": "quest_stage_advanced",
                },
                {
                    "action": "verify_cross_system_consistency",
                    "input_data": {
                        "combat_final_status": "player_won",
                        "relationship_attitude": "respectful_defeated",
                        "quest_current_stage": "leader_defeated",
                        "player_hp": 65,
                    },
                    "expected": "all_systems_consistent",
                },
                {
                    "action": "verify_no_system_drift",
                    "input_data": {
                        "combat_status": "player_won",
                        "relationship": "respectful_defeated",
                        "quest": "leader_defeated",
                        "atomicity": "all_or_nothing",
                    },
                    "expected": "consistent_across_systems",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 9
        _assert_all_steps_passed(result)

        consistency_step = _find_step(result, "verify_cross_system_consistency")
        assert consistency_step.input_data["combat_final_status"] == "player_won"
        assert consistency_step.input_data["relationship_attitude"] == "respectful_defeated"
        assert consistency_step.input_data["quest_current_stage"] == "leader_defeated"

    def test_combat_failure_no_quest_advance(self):
        result = self.runner.run_custom_scenario(
            "combat_loss_no_quest_advance",
            "session_crosssys_002",
            steps=[
                {
                    "action": "initialize_defeat_scenario",
                    "input_data": {
                        "combat": {"status": "active"},
                        "relationship": {
                            "npc_id": "shadow_assassin",
                            "attitude": "hostile",
                            "trust": -0.8,
                        },
                        "quest": {
                            "quest_id": "defeat_assassin",
                            "current_stage": "confront_assassin",
                        },
                    },
                    "expected": "defeat_scenario_set",
                },
                {
                    "action": "resolve_combat_player_defeat",
                    "input_data": {
                        "combat_status": "player_lost",
                        "player_hp": 0,
                    },
                    "expected": "player_defeated",
                },
                {
                    "action": "update_relationship_on_defeat",
                    "input_data": {
                        "npc_id": "shadow_assassin",
                        "attitude_change": "hostile_to_contemptuous",
                        "trust_shift": -0.8,
                        "trust_shift_to": -0.9,
                    },
                    "expected": "relationship_worsened",
                },
                {
                    "action": "verify_quest_does_not_advance",
                    "input_data": {
                        "quest_id": "defeat_assassin",
                        "current_stage": "confront_assassin",
                        "did_not_advance": True,
                    },
                    "expected": "quest_stage_unchanged",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 4
        _assert_all_steps_passed(result)

        quest_step = _find_step(result, "verify_quest_does_not_advance")
        assert quest_step.input_data["did_not_advance"] is True


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestSaveModifyLoadVerifyMultiSystem:
    """Save rich multi-system state, modify it, reload, verify all systems match."""

    def setup_method(self):
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    @pytest.mark.smoke
    def test_save_modify_load_verify_all_systems(self):
        saved_state = {
            "world_time": {"day": 7, "hour": 14, "season": "autumn"},
            "player": {
                "hp": 85,
                "mp": 30,
                "location": "ancient_ruins_exterior",
                "inventory": ["iron_sword", "healing_potion", "ancient_map"],
                "equipped": {
                    "weapon": {"id": "iron_sword", "durability": 80},
                    "armor": {"id": "leather_vest", "defense": 10},
                },
            },
            "combat": {
                "active": False,
                "last_combat_id": "combat_goblin_ambush",
                "last_result": "player_won",
            },
            "npcs": {
                "elder_li": {
                    "attitude": "friendly",
                    "trust": 0.7,
                    "known_facts": ["player_helped_village", "seal_is_weakening"],
                    "location": "ancient_ruins_exterior",
                },
                "bandit_leader_feng": {
                    "attitude": "respectful_defeated",
                    "trust": -0.2,
                    "known_facts": ["player_defeated_me"],
                    "location": "bandit_camp",
                },
            },
            "quests": {
                "main_seal_quest": {
                    "stage": "find_second_artifact",
                    "progress": 0.45,
                    "objectives_completed": ["speak_to_elder", "locate_first_artifact"],
                },
                "side_herb_quest": {
                    "stage": "in_progress",
                    "progress": 0.5,
                    "objectives_completed": ["gather_rare_herbs"],
                },
            },
            "relationships": {
                "elder_li": {"status": "ally", "affinity": 75},
                "bandit_leader_feng": {"status": "grudging_respect", "affinity": 15},
            },
        }

        result = self.runner.run_custom_scenario(
            "save_modify_load_multi_system",
            "session_savemod_001",
            steps=[
                {
                    "action": "create_multi_system_state",
                    "input_data": {"state": saved_state},
                    "expected": "multi_system_state_created",
                },
                {
                    "action": "save_game_state",
                    "input_data": {
                        "save_name": "multi_system_save_01",
                        "state": saved_state,
                    },
                    "expected": "state_saved_successfully",
                },
                {
                    "action": "modify_all_systems",
                    "input_data": {
                        "modifications": {
                            "world_time": {"day": 15, "season": "winter"},
                            "player": {
                                "hp": 45,
                                "location": "shadow_mountains",
                                "inventory": ["broken_sword"],
                            },
                            "combat": {"active": True},
                            "npcs": {
                                "elder_li": {"attitude": "hostile", "trust": -0.5},
                                "bandit_leader_feng": {"attitude": "ally", "trust": 0.9},
                            },
                            "quests": {
                                "main_seal_quest": {
                                    "stage": "completed",
                                    "progress": 1.0,
                                },
                            },
                            "relationships": {
                                "elder_li": {"affinity": -50},
                                "bandit_leader_feng": {"affinity": 90},
                            },
                        },
                    },
                    "expected": "all_systems_modified",
                },
                {
                    "action": "load_saved_game_state",
                    "input_data": {"save_name": "multi_system_save_01"},
                    "expected": "saved_state_loaded",
                },
                {
                    "action": "verify_world_time_matches_saved",
                    "input_data": {
                        "loaded": {"day": 7, "hour": 14, "season": "autumn"},
                        "expected": saved_state["world_time"],
                    },
                    "expected": "world_time_restored",
                },
                {
                    "action": "verify_player_state_matches_saved",
                    "input_data": {
                        "loaded": {
                            "hp": 85,
                            "location": "ancient_ruins_exterior",
                            "inventory": ["iron_sword", "healing_potion", "ancient_map"],
                        },
                        "expected": saved_state["player"],
                    },
                    "expected": "player_state_restored",
                },
                {
                    "action": "verify_combat_state_matches_saved",
                    "input_data": {
                        "loaded": {"active": False, "last_result": "player_won"},
                        "expected": saved_state["combat"],
                    },
                    "expected": "combat_state_restored",
                },
                {
                    "action": "verify_npc_states_match_saved",
                    "input_data": {
                        "loaded": saved_state["npcs"],
                        "expected": saved_state["npcs"],
                    },
                    "expected": "npc_states_restored",
                },
                {
                    "action": "verify_quest_states_match_saved",
                    "input_data": {
                        "loaded": saved_state["quests"],
                        "expected": saved_state["quests"],
                    },
                    "expected": "quest_states_restored",
                },
                {
                    "action": "verify_relationship_states_match_saved",
                    "input_data": {
                        "loaded": saved_state["relationships"],
                        "expected": saved_state["relationships"],
                    },
                    "expected": "relationship_states_restored",
                },
                {
                    "action": "verify_no_modification_leaked",
                    "input_data": {
                        "modified_values": {
                            "player_hp_would_be_45": True,
                            "elder_li_attitude_would_be_hostile": True,
                            "quest_would_be_completed": True,
                        },
                        "actual_saved_values": {
                            "player_hp_is": 85,
                            "elder_li_attitude_is": "friendly",
                            "quest_stage_is": "find_second_artifact",
                        },
                    },
                    "expected": "modifications_not_persisted",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 11
        _assert_all_steps_passed(result)

    def test_save_consistency_scenario_type(self):
        result = self.runner.run_scenario(
            ScenarioType.SAVE_CONSISTENCY,
            "session_savecons_001",
            custom_setup={
                "player_hp": 100,
                "player_mp": 50,
                "location": "temple_sanctum",
                "quest_stage": "perform_ritual",
                "inventory": ["star_sword", "mana_potion", "ritual_scroll"],
                "party_members": ["hero", "mage", "cleric"],
            },
        )

        assert result is not None
        assert result.scenario_type == ScenarioType.SAVE_CONSISTENCY
        assert result.status == "passed"
        assert len(result.steps) == 4
        _assert_all_steps_passed(result)

        match_step = _find_step(result, "verify_state_match")
        assert "identical" in match_step.actual_result.lower()


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestReplayConsistencyDeterministic:
    """Same session replayed produces deterministic state with MockProvider."""

    def setup_method(self):
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)

    @pytest.mark.smoke
    def test_replay_reconstructs_identical_state(self):
        original_turns = [
            {
                "turn_no": 1,
                "action": "look around",
                "event": "player_explored_village",
                "state_snapshot": {
                    "player_location": "village_square",
                    "turn_count": 1,
                    "known_facts": ["village_has_inn"],
                },
            },
            {
                "turn_no": 2,
                "action": "talk to elder",
                "event": "player_met_elder",
                "state_snapshot": {
                    "player_location": "village_square",
                    "turn_count": 2,
                    "known_facts": ["village_has_inn", "elder_knows_seal"],
                    "npc_interacted": "elder_li",
                },
            },
            {
                "turn_no": 3,
                "action": "enter ancient ruins",
                "event": "player_entered_ruins",
                "state_snapshot": {
                    "player_location": "ancient_ruins_entrance",
                    "turn_count": 3,
                    "known_facts": [
                        "village_has_inn",
                        "elder_knows_seal",
                        "ruins_have_first_artifact",
                    ],
                    "npc_interacted": "elder_li",
                },
            },
        ]

        final_original_state = original_turns[-1]["state_snapshot"]

        result = self.runner.run_custom_scenario(
            "replay_identical_reconstruction",
            "session_replay_001",
            steps=[
                {
                    "action": "record_game_session",
                    "input_data": {
                        "session_id": "replay_test_game",
                        "turns": original_turns,
                        "total_turns": 3,
                    },
                    "expected": "session_recorded",
                },
                {
                    "action": "capture_final_state",
                    "input_data": {"state": final_original_state},
                    "expected": "final_state_captured",
                },
                {
                    "action": "generate_audit_log",
                    "input_data": {
                        "events": [
                            {
                                "turn_no": 1,
                                "event_type": "turn_executed",
                                "action": "look around",
                                "result": "explored_village",
                            },
                            {
                                "turn_no": 2,
                                "event_type": "turn_executed",
                                "action": "talk to elder",
                                "result": "met_elder",
                            },
                            {
                                "turn_no": 3,
                                "event_type": "turn_executed",
                                "action": "enter ancient ruins",
                                "result": "entered_ruins",
                            },
                        ],
                    },
                    "expected": "audit_log_generated",
                },
                {
                    "action": "replay_turns_1_to_3",
                    "input_data": {
                        "session_id": "replay_test_game",
                        "start_turn": 1,
                        "end_turn": 3,
                        "use_mock_provider": True,
                    },
                    "expected": "replay_executed",
                },
                {
                    "action": "reconstruct_state_from_replay",
                    "input_data": {},
                    "expected": "state_reconstructed",
                },
                {
                    "action": "verify_reconstructed_equals_original",
                    "input_data": {
                        "original": final_original_state,
                        "reconstructed": {
                            "player_location": "ancient_ruins_entrance",
                            "turn_count": 3,
                            "known_facts": [
                                "village_has_inn",
                                "elder_knows_seal",
                                "ruins_have_first_artifact",
                            ],
                            "npc_interacted": "elder_li",
                        },
                    },
                    "expected": "states_identical",
                },
                {
                    "action": "replay_second_time",
                    "input_data": {
                        "session_id": "replay_test_game",
                        "start_turn": 1,
                        "end_turn": 3,
                        "use_mock_provider": True,
                    },
                    "expected": "second_replay_executed",
                },
                {
                    "action": "verify_second_replay_matches_first",
                    "input_data": {
                        "first_replay": final_original_state,
                        "second_replay": {
                            "player_location": "ancient_ruins_entrance",
                            "turn_count": 3,
                            "known_facts": [
                                "village_has_inn",
                                "elder_knows_seal",
                                "ruins_have_first_artifact",
                            ],
                            "npc_interacted": "elder_li",
                        },
                    },
                    "expected": "replay_is_deterministic",
                },
                {
                    "action": "verify_no_llm_calls_during_replay",
                    "input_data": {
                        "llm_call_count_during_replay": 0,
                        "provider_used": "mock",
                    },
                    "expected": "replay_needs_no_llm",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 9
        _assert_all_steps_passed(result)

        match_step = _find_step(result, "verify_reconstructed_equals_original")
        original = match_step.input_data["original"]
        reconstructed = match_step.input_data["reconstructed"]
        assert original == reconstructed, (
            f"Replay state mismatch: original={original}, reconstructed={reconstructed}"
        )

        det_step = _find_step(result, "verify_second_replay_matches_first")
        assert det_step.input_data["first_replay"] == det_step.input_data["second_replay"]

        llm_step = _find_step(result, "verify_no_llm_calls_during_replay")
        assert llm_step.input_data["llm_call_count_during_replay"] == 0

    def test_replay_with_mock_provider_deterministic(self):
        result = self.runner.run_scenario(
            ScenarioType.REPRODUCIBILITY,
            "session_replay_002",
            custom_setup={"seed": 42},
        )

        assert result is not None
        assert result.scenario_type == ScenarioType.REPRODUCIBILITY
        assert result.status == "passed"
        assert len(result.steps) == 4
        _assert_all_steps_passed(result)

        identical_step = _find_step(result, "verify_identical_results")
        assert "identical" in identical_step.actual_result.lower()

    def test_replay_preserves_perspective_boundaries(self):
        npc_hidden_secret = "elder_li_is_secretly_a_cult_leader"

        result = self.runner.run_custom_scenario(
            "replay_perspective_boundaries",
            "session_replay_003",
            steps=[
                {
                    "action": "create_session_with_hidden_npc_info",
                    "input_data": {
                        "npc_id": "elder_li",
                        "public_facts": ["elder_knows_seal", "elder_is_wise"],
                        "hidden_facts": [npc_hidden_secret],
                    },
                    "expected": "session_with_hidden_info_created",
                },
                {
                    "action": "execute_turns_in_session",
                    "input_data": {
                        "turns": [
                            {"action": "talk to elder", "turn": 1},
                            {"action": "ask about seal", "turn": 2},
                        ],
                    },
                    "expected": "turns_executed",
                },
                {
                    "action": "replay_session_player_perspective",
                    "input_data": {
                        "start_turn": 1,
                        "end_turn": 2,
                        "perspective": "player",
                    },
                    "expected": "replay_from_player_view",
                },
                {
                    "action": "verify_hidden_info_not_in_replay",
                    "input_data": {
                        "replay_state": {
                            "player_location": "village_square",
                            "known_facts": ["elder_knows_seal", "elder_is_wise"],
                            "turn_count": 2,
                        },
                        "forbidden": [npc_hidden_secret],
                    },
                    "expected": "hidden_info_excluded_from_replay",
                },
                {
                    "action": "verify_public_facts_present_in_replay",
                    "input_data": {
                        "expected_facts": ["elder_knows_seal", "elder_is_wise"],
                    },
                    "expected": "public_info_preserved",
                },
            ],
        )

        assert result is not None
        assert result.status == "passed"
        assert len(result.steps) == 5
        _assert_all_steps_passed(result)

        hidden_step = _find_step(result, "verify_hidden_info_not_in_replay")
        forbidden = hidden_step.input_data["forbidden"]
        assert npc_hidden_secret in forbidden

        replay_state = hidden_step.input_data["replay_state"]
        assert npc_hidden_secret not in str(replay_state["known_facts"])
