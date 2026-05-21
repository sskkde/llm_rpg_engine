"""
Skill Rules

Validates non-combat skill usage and resolves skill effects.
Supports social, stealth, exploration, and support skills.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from llm_rpg.models.common import ValidationResult, ValidationCheck
from llm_rpg.rules.rule_engine import RuleEngine, RuleType, RulePriority


SKILL_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "persuade": {
        "cost": 30,
        "type": "social",
        "description": "Persuade an NPC",
        "effect_value": 0,
        "effect_type": "attitude_shift",
    },
    "hide": {
        "cost": 20,
        "type": "stealth",
        "description": "Hide from enemies",
        "effect_value": 0,
        "effect_type": "stealth_boost",
    },
    "track": {
        "cost": 25,
        "type": "exploration",
        "description": "Track targets or resources",
        "effect_value": 0,
        "effect_type": "reveal_info",
    },
    "heal": {
        "cost": 40,
        "type": "support",
        "description": "Heal self or ally",
        "effect_value": 30,
        "effect_type": "heal",
    },
}


@dataclass
class SkillEffect:
    """Represents the resolved effect of a skill usage."""
    skill_name: str
    skill_type: str
    spiritual_power_cost: int
    damage: int = 0
    heal: int = 0
    buffs: List[Dict[str, Any]] = field(default_factory=list)
    debuffs: List[Dict[str, Any]] = field(default_factory=list)
    state_changes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "skill_type": self.skill_type,
            "spiritual_power_cost": self.spiritual_power_cost,
            "damage": self.damage,
            "heal": self.heal,
            "buffs": self.buffs,
            "debuffs": self.debuffs,
            "state_changes": self.state_changes,
        }


class SkillRules:
    """
    Validates non-combat skill usage and resolves skill effects.

    Rules:
    - Player must have sufficient spiritual_power to cast a skill
    - Skill must exist in SKILL_DEFINITIONS
    - Skill must not be on cooldown (if cooldown tracking exists)
    - Pre-requisite conditions must be met (flags, location, etc.)
    """

    def __init__(self):
        self._skill_definitions: Dict[str, Dict[str, Any]] = dict(SKILL_DEFINITIONS)
        self._cooldowns: Dict[str, int] = {}  # skill_name -> turns remaining
        self._prerequisites: Dict[str, List[str]] = {}  # skill_name -> list of required flags

    def validate_cast_skill(
        self,
        action: str,
        player_state: Dict[str, Any],
        npc_target_state: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """
        Validate whether a player can cast a skill.

        Args:
            action: Skill name to cast
            player_state: Player state dict with spiritual_power, realm, flags, etc.
            npc_target_state: Optional NPC target state for targeted skills

        Returns:
            ValidationResult with is_valid and detailed checks
        """
        checks: List[ValidationCheck] = []
        errors: List[str] = []

        # Check 1: Skill exists
        if action not in self._skill_definitions:
            checks.append(ValidationCheck(
                check_name="skill_exists",
                passed=False,
                reason=f"Skill '{action}' does not exist",
                severity="error",
            ))
            errors.append(f"Skill '{action}' does not exist")
            return ValidationResult(is_valid=False, checks=checks, errors=errors)

        skill_def = self._skill_definitions[action]
        cost = skill_def["cost"]

        # Check 2: Sufficient spiritual_power
        spiritual_power = player_state.get("spiritual_power", 0)
        has_sufficient_sp = spiritual_power >= cost
        checks.append(ValidationCheck(
            check_name="spiritual_power",
            passed=has_sufficient_sp,
            reason=(
                f"Sufficient spiritual_power ({spiritual_power} >= {cost})"
                if has_sufficient_sp
                else f"Insufficient spiritual_power ({spiritual_power} < {cost})"
            ),
            severity="error" if not has_sufficient_sp else "info",
        ))
        if not has_sufficient_sp:
            errors.append(f"Insufficient spiritual_power: need {cost}, have {spiritual_power}")

        # Check 3: Cooldown
        cooldown_remaining = self._cooldowns.get(action, 0)
        not_on_cooldown = cooldown_remaining <= 0
        checks.append(ValidationCheck(
            check_name="cooldown",
            passed=not_on_cooldown,
            reason=(
                "Skill not on cooldown"
                if not_on_cooldown
                else f"Skill on cooldown for {cooldown_remaining} more turns"
            ),
            severity="error" if not not_on_cooldown else "info",
        ))
        if not not_on_cooldown:
            errors.append(f"Skill '{action}' is on cooldown for {cooldown_remaining} more turns")

        # Check 4: Prerequisites (required flags)
        required_flags = self._prerequisites.get(action, [])
        player_flags = player_state.get("flags", {})
        missing_flags = [
            f for f in required_flags
            if not player_flags.get(f, False)
        ]
        prereqs_met = len(missing_flags) == 0
        checks.append(ValidationCheck(
            check_name="prerequisites",
            passed=prereqs_met,
            reason=(
                "All prerequisites met"
                if prereqs_met
                else f"Missing prerequisite flags: {missing_flags}"
            ),
            severity="error" if not prereqs_met else "info",
        ))
        if not prereqs_met:
            errors.append(f"Missing prerequisite flags: {missing_flags}")

        is_valid = has_sufficient_sp and not_on_cooldown and prereqs_met
        return ValidationResult(is_valid=is_valid, checks=checks, errors=errors)

    def resolve_skill_effect(
        self,
        skill_name: str,
        caster_state: Dict[str, Any],
        target_state: Optional[Dict[str, Any]] = None,
    ) -> SkillEffect:
        """
        Resolve the effect of a skill after successful validation.

        Args:
            skill_name: Name of the skill being used
            caster_state: State of the skill caster
            target_state: Optional state of the target

        Returns:
            SkillEffect dataclass with resolved effects
        """
        skill_def = self._skill_definitions.get(skill_name, {})
        skill_type = skill_def.get("type", "unknown")
        cost = skill_def.get("cost", 0)
        effect_type = skill_def.get("effect_type", "")
        effect_value = skill_def.get("effect_value", 0)

        effect = SkillEffect(
            skill_name=skill_name,
            skill_type=skill_type,
            spiritual_power_cost=cost,
        )

        if effect_type == "heal":
            effect.heal = effect_value
            effect.state_changes["hp_change"] = effect_value

        elif effect_type == "attitude_shift":
            effect.buffs.append({
                "type": "attitude_shift",
                "target": "npc",
                "value": 1,
                "description": "NPC attitude improved",
            })
            effect.state_changes["attitude_shift"] = 1

        elif effect_type == "stealth_boost":
            effect.buffs.append({
                "type": "stealth",
                "target": "self",
                "value": 1,
                "duration": 3,
                "description": "Hidden from enemies",
            })
            effect.state_changes["hidden"] = True

        elif effect_type == "reveal_info":
            effect.state_changes["tracking_active"] = True
            effect.buffs.append({
                "type": "tracking",
                "target": "self",
                "value": 1,
                "duration": 2,
                "description": "Tracking targets or resources",
            })

        return effect

    def get_available_skills(self, player_state: Dict[str, Any]) -> List[str]:
        """
        Return list of skill names the player can currently use.

        A skill is available if:
        - It exists in SKILL_DEFINITIONS
        - Player has sufficient spiritual_power
        - Skill is not on cooldown
        - Prerequisites are met

        Args:
            player_state: Player state dict

        Returns:
            List of available skill names
        """
        available: List[str] = []
        spiritual_power = player_state.get("spiritual_power", 0)
        player_flags = player_state.get("flags", {})

        for skill_name, skill_def in self._skill_definitions.items():
            cost = skill_def["cost"]
            if spiritual_power < cost:
                continue

            cooldown_remaining = self._cooldowns.get(skill_name, 0)
            if cooldown_remaining > 0:
                continue

            required_flags = self._prerequisites.get(skill_name, [])
            missing_flags = [
                f for f in required_flags
                if not player_flags.get(f, False)
            ]
            if missing_flags:
                continue

            available.append(skill_name)

        return available

    def set_cooldown(self, skill_name: str, turns: int) -> None:
        """Set cooldown for a skill."""
        self._cooldowns[skill_name] = turns

    def tick_cooldowns(self) -> None:
        """Advance all cooldowns by one turn."""
        expired = []
        for skill_name, turns in self._cooldowns.items():
            if turns <= 1:
                expired.append(skill_name)
            else:
                self._cooldowns[skill_name] = turns - 1
        for skill_name in expired:
            del self._cooldowns[skill_name]

    def set_prerequisites(self, skill_name: str, required_flags: List[str]) -> None:
        """Set prerequisite flags for a skill."""
        self._prerequisites[skill_name] = required_flags

    def add_skill(self, name: str, definition: Dict[str, Any]) -> None:
        """Add a new skill definition at runtime."""
        self._skill_definitions[name] = definition


def register_rules(rule_engine: RuleEngine) -> List[str]:
    """
    Register SkillRules methods with the RuleEngine.

    Args:
        rule_engine: The RuleEngine instance to register with

    Returns:
        List of registered rule IDs
    """
    skill_rules = SkillRules()
    rule_ids: List[str] = []

    def validate_cast_skill_handler(context: Dict[str, Any]) -> Dict[str, Any]:
        action = context.get("action", "")
        player_state = context.get("player_state", {})
        npc_target_state = context.get("npc_target_state")
        result = skill_rules.validate_cast_skill(action, player_state, npc_target_state)
        return {
            "passed": result.is_valid,
            "errors": result.errors,
            "warnings": result.warnings,
            "modifications": {
                "skill_action": action,
                "checks": [c.model_dump() for c in result.checks],
            },
        }

    rule_id = rule_engine.register_rule(
        rule_type=RuleType.CUSTOM,
        handler=validate_cast_skill_handler,
        rule_id="skill_validate_cast",
        priority=RulePriority.NORMAL,
        description="Validate non-combat skill casting",
    )
    rule_ids.append(rule_id)

    return rule_ids
