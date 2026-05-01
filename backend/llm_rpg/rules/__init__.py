"""
Rule Engine Module

Provides explicit rule boundaries for game mechanics:
- RuleEngine: Main rule evaluation and validation
- MovementRules: Movement validation and cost calculation
- QuestRules: Quest progression and completion
- CombatRules: Combat validation and resolution
- DialogueRules: Dialogue validation and state management
- WorldTimeRules: World time advancement and effects
"""

from .rule_engine import RuleEngine, RuleResult, RulePriority
from .movement_rules import MovementRules, MovementCost
from .quest_rules import QuestRules, QuestProgression
from .combat_rules import CombatRules, CombatOutcome
from .dialogue_rules import DialogueRules, DialogueState
from .world_time_rules import WorldTimeRules, TimeEffect

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
]
