"""Validation module for LLM RPG Engine.

This module provides:
1. ValidationResult and ValidationCheck - unified result types
2. ValidationContext - context container for validation operations
3. StateDeltaValidator - state delta contract validation
4. Contract constants - allowed paths, operations, bounds

Future validators (MovementValidator, QuestValidator, etc.) will be added here.
"""

# Result types
from .result import (
    ValidationResult,
    ValidationCheck,
    passed_result,
    failed_result,
    combine_results,
    make_check,
)

# Context
from .context import ValidationContext

# State delta contract
from .state_delta_contract import (
    ALLOWED_DELTA_PATHS,
    ALLOWED_OPERATIONS,
    BLOCKED_DELTA_PATHS,
    NUMERIC_BOUNDS,
    SOURCE_EVENT_ID_EXCEPTIONS,
)

# Validators
from .state_delta_validator import StateDeltaValidator
from .movement_validator import MovementValidator
from .quest_validator import QuestValidator
from .npc_knowledge_validator import NPCKnowledgeValidator
from .narration_leak_validator import NarrationLeakValidator

__all__ = [
    # Result types
    "ValidationResult",
    "ValidationCheck",
    "passed_result",
    "failed_result",
    "combine_results",
    "make_check",
    # Context
    "ValidationContext",
    # Contract constants
    "ALLOWED_DELTA_PATHS",
    "BLOCKED_DELTA_PATHS",
    "ALLOWED_OPERATIONS",
    "NUMERIC_BOUNDS",
    "SOURCE_EVENT_ID_EXCEPTIONS",
    # Validators
    "StateDeltaValidator",
    "MovementValidator",
    "QuestValidator",
    "NPCKnowledgeValidator",
    "NarrationLeakValidator",
]
