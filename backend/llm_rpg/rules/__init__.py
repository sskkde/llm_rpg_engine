"""
Rule Engine Module

Provides explicit rule boundaries for game mechanics:
- RuleEngine: Main rule evaluation and validation
- MovementRules: Movement validation and cost calculation
- QuestRules: Quest progression and completion
- CombatRules: Combat validation and resolution
- DialogueRules: Dialogue validation and state management
- WorldTimeRules: World time advancement and effects
- ItemRules: Item use/give/take validation and effect resolution
- SkillRules: Skill cast validation and effect resolution
"""

from .rule_engine import RuleEngine, RuleResult, RulePriority
from .movement_rules import MovementRules, MovementCost
from .quest_rules import QuestRules, QuestProgression
from .combat_rules import CombatRules, CombatOutcome
from .dialogue_rules import DialogueRules, DialogueState
from .world_time_rules import WorldTimeRules, TimeEffect
from .item_rules import ItemRules, ItemEffect
from .skill_rules import SkillRules, SkillEffect
from .action_schema import ActionSchema, ActionType, TargetType, ACTION_SCHEMAS, validate_action_schema

__all__ = [
    "RuleEngine",
    "RuleResult",
    "RulePriority",
    "MovementRules",
    "MovementCost",
    "QuestRules",
    "QuestProgression",
    "CombatRules",
    "CombatOutcome",
    "DialogueRules",
    "DialogueState",
    "WorldTimeRules",
    "TimeEffect",
    "ItemRules",
    "ItemEffect",
    "SkillRules",
    "SkillEffect",
    "ActionSchema",
    "ActionType",
    "TargetType",
    "ACTION_SCHEMAS",
    "validate_action_schema",
]
