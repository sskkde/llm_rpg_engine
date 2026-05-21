"""
Unit tests for SkillRules.

Tests non-combat skill validation, effect resolution, and availability.
"""

import pytest

from llm_rpg.rules.skill_rules import SkillRules, SkillEffect, SKILL_DEFINITIONS, register_rules
from llm_rpg.rules.rule_engine import RuleEngine, RuleType


class TestValidateCastSkill:
    def test_cast_persuade_with_sufficient_spiritual_power(self):
        rules = SkillRules()
        player_state = {"spiritual_power": 100, "flags": {}}
        result = rules.validate_cast_skill("persuade", player_state)
        assert result.is_valid is True

    def test_cast_persuade_with_insufficient_spiritual_power(self):
        rules = SkillRules()
        player_state = {"spiritual_power": 10, "flags": {}}
        result = rules.validate_cast_skill("persuade", player_state)
        assert result.is_valid is False
        assert any("Insufficient spiritual_power" in e for e in result.errors)

    def test_cast_unknown_skill(self):
        rules = SkillRules()
        player_state = {"spiritual_power": 100, "flags": {}}
        result = rules.validate_cast_skill("nonexistent", player_state)
        assert result.is_valid is False
        assert any("does not exist" in e for e in result.errors)

    def test_cast_skill_on_cooldown(self):
        rules = SkillRules()
        rules.set_cooldown("persuade", 3)
        player_state = {"spiritual_power": 100, "flags": {}}
        result = rules.validate_cast_skill("persuade", player_state)
        assert result.is_valid is False
        assert any("cooldown" in e.lower() for e in result.errors)

    def test_cast_skill_missing_prerequisites(self):
        rules = SkillRules()
        rules.set_prerequisites("persuade", ["knows_persuasion"])
        player_state = {"spiritual_power": 100, "flags": {}}
        result = rules.validate_cast_skill("persuade", player_state)
        assert result.is_valid is False
        assert any("prerequisite" in e.lower() for e in result.errors)

    def test_cast_skill_with_prerequisites_met(self):
        rules = SkillRules()
        rules.set_prerequisites("persuade", ["knows_persuasion"])
        player_state = {"spiritual_power": 100, "flags": {"knows_persuasion": True}}
        result = rules.validate_cast_skill("persuade", player_state)
        assert result.is_valid is True


class TestGetAvailableSkills:
    def test_returns_all_skills_when_spiritual_power_sufficient(self):
        rules = SkillRules()
        player_state = {"spiritual_power": 100, "flags": {}}
        available = rules.get_available_skills(player_state)
        assert set(available) == set(SKILL_DEFINITIONS.keys())

    def test_filters_out_expensive_skills_when_low_spiritual_power(self):
        rules = SkillRules()
        player_state = {"spiritual_power": 25, "flags": {}}
        available = rules.get_available_skills(player_state)
        assert "hide" in available
        assert "persuade" not in available
        assert "heal" not in available

    def test_excludes_skills_on_cooldown(self):
        rules = SkillRules()
        rules.set_cooldown("hide", 2)
        player_state = {"spiritual_power": 100, "flags": {}}
        available = rules.get_available_skills(player_state)
        assert "hide" not in available
        assert "persuade" in available

    def test_excludes_skills_with_unmet_prerequisites(self):
        rules = SkillRules()
        rules.set_prerequisites("track", ["has_tracking_skill"])
        player_state = {"spiritual_power": 100, "flags": {}}
        available = rules.get_available_skills(player_state)
        assert "track" not in available


class TestResolveSkillEffect:
    def test_resolve_heal_returns_correct_heal_value(self):
        rules = SkillRules()
        caster_state = {"spiritual_power": 100}
        effect = rules.resolve_skill_effect("heal", caster_state)
        assert effect.heal == 30
        assert effect.skill_type == "support"
        assert effect.spiritual_power_cost == 40
        assert effect.state_changes["hp_change"] == 30

    def test_resolve_persuade_returns_attitude_shift(self):
        rules = SkillRules()
        caster_state = {"spiritual_power": 100}
        effect = rules.resolve_skill_effect("persuade", caster_state)
        assert effect.skill_type == "social"
        assert effect.spiritual_power_cost == 30
        assert len(effect.buffs) == 1
        assert effect.buffs[0]["type"] == "attitude_shift"

    def test_resolve_hide_returns_stealth_boost(self):
        rules = SkillRules()
        caster_state = {"spiritual_power": 100}
        effect = rules.resolve_skill_effect("hide", caster_state)
        assert effect.skill_type == "stealth"
        assert effect.state_changes["hidden"] is True
        assert any(b["type"] == "stealth" for b in effect.buffs)

    def test_resolve_track_returns_reveal_info(self):
        rules = SkillRules()
        caster_state = {"spiritual_power": 100}
        effect = rules.resolve_skill_effect("track", caster_state)
        assert effect.skill_type == "exploration"
        assert effect.state_changes["tracking_active"] is True

    def test_resolve_unknown_skill_returns_defaults(self):
        rules = SkillRules()
        caster_state = {"spiritual_power": 100}
        effect = rules.resolve_skill_effect("unknown_skill", caster_state)
        assert effect.skill_name == "unknown_skill"
        assert effect.skill_type == "unknown"
        assert effect.spiritual_power_cost == 0

    def test_skill_effect_to_dict(self):
        effect = SkillEffect(
            skill_name="heal",
            skill_type="support",
            spiritual_power_cost=40,
            heal=30,
        )
        data = effect.to_dict()
        assert data["skill_name"] == "heal"
        assert data["heal"] == 30
        assert data["spiritual_power_cost"] == 40


class TestCooldownManagement:
    def test_tick_cooldowns_decrements(self):
        rules = SkillRules()
        rules.set_cooldown("persuade", 3)
        rules.tick_cooldowns()
        player_state = {"spiritual_power": 100, "flags": {}}
        result = rules.validate_cast_skill("persuade", player_state)
        assert result.is_valid is False

    def test_tick_cooldowns_expires(self):
        rules = SkillRules()
        rules.set_cooldown("persuade", 1)
        rules.tick_cooldowns()
        player_state = {"spiritual_power": 100, "flags": {}}
        result = rules.validate_cast_skill("persuade", player_state)
        assert result.is_valid is True


class TestRegisterRules:
    def test_register_rules_with_engine(self):
        engine = RuleEngine()
        rule_ids = register_rules(engine)
        assert len(rule_ids) == 1
        assert rule_ids[0] == "skill_validate_cast"

    def test_registered_rule_evaluates(self):
        engine = RuleEngine()
        register_rules(engine)
        context = {
            "action": "persuade",
            "player_state": {"spiritual_power": 100, "flags": {}},
        }
        result = engine.evaluate_rule("skill_validate_cast", context)
        assert result is not None
        assert result.passed is True

    def test_registered_rule_fails_insufficient_sp(self):
        engine = RuleEngine()
        register_rules(engine)
        context = {
            "action": "persuade",
            "player_state": {"spiritual_power": 5, "flags": {}},
        }
        result = engine.evaluate_rule("skill_validate_cast", context)
        assert result is not None
        assert result.passed is False
