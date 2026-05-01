"""
Unit tests for Rule Engine.

Tests RuleEngine and all rule types:
- MovementRules
- QuestRules
- CombatRules
- DialogueRules
- WorldTimeRules
"""

import pytest
from datetime import datetime

from llm_rpg.rules import (
    RuleEngine,
    RuleResult,
    RulePriority,
    MovementRules,
    MovementCost,
    QuestRules,
    QuestProgression,
    CombatRules,
    CombatOutcome,
    DialogueRules,
    DialogueState,
    WorldTimeRules,
    TimeEffect,
)
from llm_rpg.rules.rule_engine import RuleType
from llm_rpg.rules.combat_rules import CombatActionType, CombatOutcomeType
from llm_rpg.rules.dialogue_rules import DialogueActionType
from llm_rpg.rules.quest_rules import QuestStatus


class TestRuleEngine:
    """Tests for RuleEngine."""
    
    def test_engine_initialization(self):
        engine = RuleEngine()
        assert engine is not None
        assert len(engine.get_registered_rules()) == 0
    
    def test_register_rule(self):
        engine = RuleEngine()
        
        def test_handler(context):
            return {"passed": True}
        
        rule_id = engine.register_rule(
            rule_type=RuleType.CUSTOM,
            handler=test_handler,
            description="Test rule",
        )
        
        assert rule_id.startswith("rule_")
        assert len(engine.get_registered_rules()) == 1
    
    def test_unregister_rule(self):
        engine = RuleEngine()
        
        def test_handler(context):
            return {"passed": True}
        
        rule_id = engine.register_rule(
            rule_type=RuleType.CUSTOM,
            handler=test_handler,
        )
        
        result = engine.unregister_rule(rule_id)
        assert result is True
        assert len(engine.get_registered_rules()) == 0
    
    def test_enable_disable_rule(self):
        engine = RuleEngine()
        
        def test_handler(context):
            return {"passed": True}
        
        rule_id = engine.register_rule(
            rule_type=RuleType.CUSTOM,
            handler=test_handler,
        )
        
        assert engine.disable_rule(rule_id) is True
        assert engine.enable_rule(rule_id) is True
    
    def test_evaluate_rule_passed(self):
        engine = RuleEngine()
        
        def passing_handler(context):
            return {"passed": True, "errors": [], "warnings": []}
        
        rule_id = engine.register_rule(
            rule_type=RuleType.CUSTOM,
            handler=passing_handler,
        )
        
        result = engine.evaluate_rule(rule_id, {})
        assert result is not None
        assert result.passed is True
    
    def test_evaluate_rule_failed(self):
        engine = RuleEngine()
        
        def failing_handler(context):
            return {"passed": False, "errors": ["Test error"], "warnings": []}
        
        rule_id = engine.register_rule(
            rule_type=RuleType.CUSTOM,
            handler=failing_handler,
        )
        
        result = engine.evaluate_rule(rule_id, {})
        assert result is not None
        assert result.passed is False
        assert "Test error" in result.errors
    
    def test_evaluate_rules_by_type(self):
        engine = RuleEngine()
        
        def handler1(context):
            return {"passed": True}
        
        def handler2(context):
            return {"passed": True}
        
        engine.register_rule(RuleType.MOVEMENT, handler1)
        engine.register_rule(RuleType.MOVEMENT, handler2)
        engine.register_rule(RuleType.COMBAT, handler1)
        
        results = engine.evaluate_rules_by_type(RuleType.MOVEMENT, {})
        assert len(results) == 2
    
    def test_validate_all(self):
        engine = RuleEngine()
        
        def passing_handler(context):
            return {"passed": True, "errors": [], "warnings": []}
        
        engine.register_rule(RuleType.CUSTOM, passing_handler)
        
        result = engine.validate_all({})
        assert result["valid"] is True
        assert result["total_rules"] == 1
        assert result["passed_rules"] == 1
    
    def test_validate_all_with_error(self):
        engine = RuleEngine()
        
        def failing_handler(context):
            return {"passed": False, "errors": ["Error"], "warnings": []}
        
        engine.register_rule(RuleType.CUSTOM, failing_handler)
        
        result = engine.validate_all({})
        assert result["valid"] is False
        assert result["failed_rules"] == 1
    
    def test_validation_history(self):
        engine = RuleEngine()
        
        def handler(context):
            return {"passed": True, "errors": [], "warnings": []}
        
        rule_id = engine.register_rule(RuleType.CUSTOM, handler)
        engine.evaluate_rule(rule_id, {})
        
        history = engine.get_validation_history()
        assert len(history) == 1
    
    def test_clear_history(self):
        engine = RuleEngine()
        
        def handler(context):
            return {"passed": True}
        
        rule_id = engine.register_rule(RuleType.CUSTOM, handler)
        engine.evaluate_rule(rule_id, {})
        engine.clear_history()
        
        assert len(engine.get_validation_history()) == 0
    
    def test_rule_with_modifications(self):
        engine = RuleEngine()
        
        def modifying_handler(context):
            return {
                "passed": True,
                "errors": [],
                "warnings": [],
                "modifications": {"damage": 10},
            }
        
        rule_id = engine.register_rule(RuleType.CUSTOM, modifying_handler)
        result = engine.evaluate_rule(rule_id, {})
        
        assert result.modifications == {"damage": 10}
    
    def test_rule_result_to_dict(self):
        result = RuleResult(
            rule_id="rule_1",
            rule_type=RuleType.CUSTOM,
            passed=True,
            errors=[],
            warnings=["Warning"],
            modifications={},
            priority=RulePriority.NORMAL,
            timestamp=datetime.now(),
        )
        
        data = result.to_dict()
        assert data["rule_id"] == "rule_1"
        assert data["passed"] is True
        assert data["priority"] == 2


class TestMovementRules:
    """Tests for MovementRules."""
    
    def test_rules_initialization(self):
        rules = MovementRules()
        assert rules is not None
    
    def test_validate_valid_movement(self):
        rules = MovementRules()
        game_state = {
            "current_mode": "exploration",
            "locations": {
                "forest": {"terrain": "forest"},
            },
            "player_fatigue": 0.0,
        }
        
        result = rules.validate_movement("square", "forest", game_state)
        assert result.valid is True
        assert result.total_cost() > 0
    
    def test_validate_blocked_location(self):
        rules = MovementRules()
        rules.block_location("blocked_area")
        
        game_state = {"current_mode": "exploration"}
        
        result = rules.validate_movement("square", "blocked_area", game_state)
        assert result.valid is False
        assert "blocked" in result.reason.lower()
    
    def test_validate_same_location(self):
        rules = MovementRules()
        game_state = {"current_mode": "exploration"}
        
        result = rules.validate_movement("forest", "forest", game_state)
        assert result.valid is False
    
    def test_validate_combat_mode(self):
        rules = MovementRules()
        game_state = {"current_mode": "combat"}
        
        result = rules.validate_movement("square", "forest", game_state)
        assert result.valid is False
        assert "combat" in result.reason.lower()
    
    def test_validate_required_items(self):
        rules = MovementRules()
        rules.set_required_items("secret_area", ["key"])
        
        game_state = {
            "current_mode": "exploration",
            "inventory": [],
        }
        
        result = rules.validate_movement("square", "secret_area", game_state)
        assert result.valid is False
        assert "Missing required items" in result.reason
    
    def test_can_move_to(self):
        rules = MovementRules()
        game_state = {"current_mode": "exploration"}
        
        assert rules.can_move_to("square", "forest", game_state) is True
    
    def test_get_valid_destinations(self):
        rules = MovementRules()
        game_state = {
            "current_mode": "exploration",
            "locations": {
                "square": {},
                "forest": {},
                "cave": {},
            },
        }
        
        destinations = rules.get_valid_destinations("square", game_state)
        assert len(destinations) == 2
        assert "forest" in destinations
        assert "cave" in destinations
    
    def test_movement_cost_calculation(self):
        cost = MovementCost(
            base_cost=10,
            terrain_modifier=1.5,
            fatigue_cost=2.0,
            time_cost=15,
            valid=True,
            reason="Test",
        )
        
        assert cost.total_cost() == 17.0
    
    def test_movement_cost_to_dict(self):
        cost = MovementCost(
            base_cost=10,
            terrain_modifier=1.0,
            fatigue_cost=0.0,
            time_cost=10,
            valid=True,
            reason="Test",
        )
        
        data = cost.to_dict()
        assert data["base_cost"] == 10
        assert data["valid"] is True


class TestQuestRules:
    """Tests for QuestRules."""
    
    def test_rules_initialization(self):
        rules = QuestRules()
        assert rules is not None
    
    def test_validate_progression_new_quest(self):
        rules = QuestRules()
        game_state = {
            "quest_states": {},
        }
        
        result = rules.validate_progression("quest_1", game_state)
        assert result.valid is True
        assert result.new_status == QuestStatus.ACTIVE
    
    def test_validate_progression_already_completed(self):
        rules = QuestRules()
        game_state = {
            "quest_states": {
                "quest_1": {"status": "completed"},
            },
        }
        
        result = rules.validate_progression("quest_1", game_state)
        assert result.valid is False
        assert "already completed" in result.reason.lower()
    
    def test_validate_progression_failed_quest(self):
        rules = QuestRules()
        game_state = {
            "quest_states": {
                "quest_1": {"status": "failed"},
            },
        }
        
        result = rules.validate_progression("quest_1", game_state)
        assert result.valid is False
    
    def test_validate_progression_with_prerequisites(self):
        rules = QuestRules()
        rules.set_prerequisites("quest_2", ["quest_1"])
        
        game_state = {
            "quest_states": {
                "quest_1": {"status": "not_started"},
            },
        }
        
        result = rules.validate_progression("quest_2", game_state)
        assert result.valid is False
        assert "Prerequisite" in result.reason
    
    def test_validate_progression_prerequisites_met(self):
        rules = QuestRules()
        rules.set_prerequisites("quest_2", ["quest_1"])
        
        game_state = {
            "quest_states": {
                "quest_1": {"status": "completed"},
            },
        }
        
        result = rules.validate_progression("quest_2", game_state)
        assert result.valid is True
    
    def test_validate_completion_success(self):
        rules = QuestRules()
        game_state = {
            "quest_states": {
                "quest_1": {
                    "status": "active",
                    "objectives": ["obj1", "obj2"],
                    "completed_objectives": ["obj1", "obj2"],
                },
            },
        }
        
        result = rules.validate_completion("quest_1", game_state)
        assert result.valid is True
        assert result.new_status == QuestStatus.COMPLETED
    
    def test_validate_completion_not_active(self):
        rules = QuestRules()
        game_state = {
            "quest_states": {
                "quest_1": {"status": "not_started"},
            },
        }
        
        result = rules.validate_completion("quest_1", game_state)
        assert result.valid is False
    
    def test_validate_completion_incomplete_objectives(self):
        rules = QuestRules()
        game_state = {
            "quest_states": {
                "quest_1": {
                    "status": "active",
                    "objectives": ["obj1", "obj2"],
                    "completed_objectives": ["obj1"],
                },
            },
        }
        
        result = rules.validate_completion("quest_1", game_state)
        assert result.valid is False
    
    def test_mutual_exclusion(self):
        rules = QuestRules()
        rules.set_mutual_exclusions("quest_a", ["quest_b"])
        
        game_state = {
            "quest_states": {
                "quest_b": {"status": "active"},
            },
        }
        
        result = rules.validate_progression("quest_a", game_state)
        assert result.valid is False
        assert "Mutually exclusive" in result.reason
    
    def test_can_start_quest(self):
        rules = QuestRules()
        game_state = {"quest_states": {}}
        
        assert rules.can_start_quest("quest_1", game_state) is True
    
    def test_quest_progression_to_dict(self):
        progression = QuestProgression(
            quest_id="quest_1",
            old_status=QuestStatus.NOT_STARTED,
            new_status=QuestStatus.ACTIVE,
            stage_changed=False,
            old_stage="",
            new_stage="",
            completed_objectives=[],
            new_objectives=[],
            valid=True,
            reason="Test",
        )
        
        data = progression.to_dict()
        assert data["quest_id"] == "quest_1"
        assert data["new_status"] == "active"


class TestCombatRules:
    """Tests for CombatRules."""
    
    def test_rules_initialization(self):
        rules = CombatRules()
        assert rules is not None
    
    def test_validate_action_not_in_combat(self):
        rules = CombatRules()
        game_state = {"current_mode": "exploration"}
        
        result = rules.validate_action(
            CombatActionType.ATTACK,
            "player",
            "enemy",
            game_state,
        )
        
        assert result.valid is False
        assert "combat" in result.reason.lower()
    
    def test_validate_attack_without_target(self):
        rules = CombatRules()
        game_state = {"current_mode": "combat"}
        
        result = rules.validate_action(
            CombatActionType.ATTACK,
            "player",
            None,
            game_state,
        )
        
        assert result.valid is False
        assert "Target required" in result.reason
    
    def test_validate_defend(self):
        rules = CombatRules()
        game_state = {"current_mode": "combat"}
        
        result = rules.validate_action(
            CombatActionType.DEFEND,
            "player",
            None,
            game_state,
        )
        
        assert result.valid is True
        assert result.outcome_type == CombatOutcomeType.BLOCKED
    
    def test_validate_flee(self):
        rules = CombatRules()
        game_state = {"current_mode": "combat"}
        
        result = rules.validate_action(
            CombatActionType.FLEE,
            "player",
            None,
            game_state,
        )
        
        assert result.valid is True
        assert result.action_type == CombatActionType.FLEE
    
    def test_can_perform_action(self):
        rules = CombatRules()
        
        assert rules.can_perform_action(
            CombatActionType.ATTACK,
            {"current_mode": "combat"}
        ) is True
        
        assert rules.can_perform_action(
            CombatActionType.ATTACK,
            {"current_mode": "exploration"}
        ) is False
    
    def test_set_base_damage(self):
        rules = CombatRules()
        rules.set_base_damage(CombatActionType.ATTACK, 20)
        
        game_state = {
            "current_mode": "combat",
            "combat_state": {
                "participants": ["player", "enemy"],
            },
        }
        result = rules.validate_action(
            CombatActionType.ATTACK,
            "player",
            "enemy",
            game_state,
        )
        
        assert result.damage == 20 or result.damage == 40  # Normal or critical
    
    def test_combat_outcome_to_dict(self):
        outcome = CombatOutcome(
            action_type=CombatActionType.ATTACK,
            outcome_type=CombatOutcomeType.HIT,
            damage=10,
            attacker_id="player",
            target_id="enemy",
            valid=True,
            reason="Hit",
            effects=[{"type": "damage"}],
        )
        
        data = outcome.to_dict()
        assert data["damage"] == 10
        assert data["valid"] is True


class TestDialogueRules:
    """Tests for DialogueRules."""
    
    def test_rules_initialization(self):
        rules = DialogueRules()
        assert rules is not None
    
    def test_validate_action_not_in_dialogue(self):
        rules = DialogueRules()
        game_state = {"current_mode": "exploration"}
        
        result = rules.validate_action(
            DialogueActionType.GREET,
            "npc_1",
            game_state,
        )
        
        assert result["valid"] is False
    
    def test_validate_action_npc_not_found(self):
        rules = DialogueRules()
        game_state = {
            "current_mode": "dialogue",
            "npc_states": {},
        }
        
        result = rules.validate_action(
            DialogueActionType.GREET,
            "npc_1",
            game_state,
        )
        
        assert result["valid"] is False
        assert "not found" in result["reason"].lower()
    
    def test_validate_greet(self):
        rules = DialogueRules()
        game_state = {
            "current_mode": "dialogue",
            "npc_states": {
                "npc_1": {
                    "mood": "neutral",
                    "trust_toward_player": 0.5,
                },
            },
        }
        
        result = rules.validate_action(
            DialogueActionType.GREET,
            "npc_1",
            game_state,
        )
        
        assert result["valid"] is True
    
    def test_validate_threaten_wrong_mood(self):
        rules = DialogueRules()
        game_state = {
            "current_mode": "dialogue",
            "npc_states": {
                "npc_1": {
                    "mood": "friendly",
                    "trust_toward_player": 0.5,
                },
            },
        }
        
        result = rules.validate_action(
            DialogueActionType.THREATEN,
            "npc_1",
            game_state,
        )
        
        assert result["valid"] is False
        assert "mood" in result["reason"].lower()
    
    def test_validate_ask_low_trust(self):
        rules = DialogueRules()
        game_state = {
            "current_mode": "dialogue",
            "npc_states": {
                "npc_1": {
                    "mood": "neutral",
                    "trust_toward_player": 0.1,
                },
            },
        }
        
        result = rules.validate_action(
            DialogueActionType.ASK,
            "npc_1",
            game_state,
        )
        
        assert result["valid"] is False
        assert "trust" in result["reason"].lower()
    
    def test_can_talk_to(self):
        rules = DialogueRules()
        game_state = {
            "player_location": "square",
            "npc_states": {
                "npc_1": {
                    "status": "alive",
                    "location_id": "square",
                },
            },
        }
        
        assert rules.can_talk_to("npc_1", game_state) is True
    
    def test_can_talk_to_wrong_location(self):
        rules = DialogueRules()
        game_state = {
            "player_location": "square",
            "npc_states": {
                "npc_1": {
                    "status": "alive",
                    "location_id": "forest",
                },
            },
        }
        
        assert rules.can_talk_to("npc_1", game_state) is False
    
    def test_can_talk_to_dead_npc(self):
        rules = DialogueRules()
        game_state = {
            "player_location": "square",
            "npc_states": {
                "npc_1": {
                    "status": "dead",
                    "location_id": "square",
                },
            },
        }
        
        assert rules.can_talk_to("npc_1", game_state) is False
    
    def test_get_available_actions(self):
        rules = DialogueRules()
        game_state = {
            "current_mode": "dialogue",
            "npc_states": {
                "npc_1": {
                    "mood": "neutral",
                    "trust_toward_player": 0.5,
                },
            },
        }
        
        actions = rules.get_available_actions("npc_1", game_state)
        assert len(actions) > 0
        assert DialogueActionType.GREET in actions
        assert DialogueActionType.END in actions


class TestWorldTimeRules:
    """Tests for WorldTimeRules."""
    
    def test_rules_initialization(self):
        rules = WorldTimeRules()
        assert rules is not None
    
    def test_advance_time_one_period(self):
        rules = WorldTimeRules()
        current_time = {
            "calendar": "修仙历",
            "season": "春",
            "day": 1,
            "period": "子时",
        }
        
        new_time = rules.advance_time(current_time, periods_to_advance=1)
        assert new_time["period"] == "丑时"
        assert new_time["day"] == 1
    
    def test_advance_time_multiple_periods(self):
        rules = WorldTimeRules()
        current_time = {
            "calendar": "修仙历",
            "season": "春",
            "day": 1,
            "period": "子时",
        }
        
        new_time = rules.advance_time(current_time, periods_to_advance=12)
        assert new_time["period"] == "子时"
        assert new_time["day"] == 2
    
    def test_advance_time_season_change(self):
        rules = WorldTimeRules()
        current_time = {
            "calendar": "修仙历",
            "season": "春",
            "day": 90,
            "period": "亥时",
        }
        
        new_time = rules.advance_time(current_time, periods_to_advance=2)
        assert new_time["season"] == "夏"
    
    def test_calculate_effects(self):
        rules = WorldTimeRules()
        world_time = {
            "period": "子时",
            "season": "春",
        }
        
        effects = rules.calculate_effects(world_time)
        assert len(effects) >= 1
    
    def test_get_action_time_cost(self):
        rules = WorldTimeRules()
        
        assert rules.get_action_time_cost("move") == 1
        assert rules.get_action_time_cost("combat") == 2
    
    def test_set_action_time_cost(self):
        rules = WorldTimeRules()
        rules.set_action_time_cost("move", 3)
        
        assert rules.get_action_time_cost("move") == 3
    
    def test_is_night_time(self):
        rules = WorldTimeRules()
        
        assert rules.is_night_time({"period": "子时"}) is True
        assert rules.is_night_time({"period": "午时"}) is False
    
    def test_is_day_time(self):
        rules = WorldTimeRules()
        
        assert rules.is_day_time({"period": "子时"}) is False
        assert rules.is_day_time({"period": "午时"}) is True
    
    def test_get_time_description(self):
        rules = WorldTimeRules()
        world_time = {
            "calendar": "修仙历",
            "season": "春",
            "day": 1,
            "period": "辰时",
        }
        
        desc = rules.get_time_description(world_time)
        assert "修仙历" in desc
        assert "春" in desc
        assert "辰时" in desc
    
    def test_add_period_effect(self):
        rules = WorldTimeRules()
        rules.add_period_effect("午时", {"type": "fatigue", "value": 0.5, "target": "player"})
        
        effects = rules.calculate_effects({"period": "午时"})
        assert len(effects) >= 1
    
    def test_time_effect_to_dict(self):
        effect = TimeEffect(
            effect_type="visibility",
            target_id="all",
            magnitude=-0.5,
            duration=1,
            description="Night visibility",
        )
        
        data = effect.to_dict()
        assert data["effect_type"] == "visibility"
        assert data["magnitude"] == -0.5
