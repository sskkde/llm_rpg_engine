"""Narration Leak Validator Module.

This module will provide validation for narration content to prevent
information leaks. Currently a placeholder for future implementation.

Expected validation checks:
- No forbidden information in narration
- No meta-game information exposed
- Perspective-appropriate content
- No future plot spoilers
"""

from typing import List, Optional

from ...models.common import ValidationResult
from ...models.states import CanonicalState
from .context import ValidationContext
from .result import make_check


class NarrationLeakValidator:
    """Validator for narration content to prevent information leaks.

    This is a placeholder implementation. Full implementation will include:
    - Forbidden information detection
    - Meta-game exposure prevention
    - Perspective filtering
    - Spoiler detection
    """

    def validate_narration(
        self,
        text: str,
        forbidden_info: List[str],
        state: Optional[CanonicalState] = None,
        context: Optional[ValidationContext] = None,
    ) -> ValidationResult:
        """Validate narration for information leaks.

        Args:
            text: Narration text to validate
            forbidden_info: List of forbidden information patterns
            state: Current canonical state (optional)
            context: Optional validation context

        Returns:
            ValidationResult indicating if narration is safe
        """
        if context is not None and state is None:
            state = context.canonical_state

        checks = []
        errors = []

        for info in forbidden_info:
            if info.lower() in text.lower():
                checks.append(make_check(
                    "narration_leak_check",
                    passed=False,
                    reason=f"Narration contains forbidden information: {info}",
                    severity="error",
                ))
                errors.append(f"Narration contains forbidden information: {info}")
            else:
                checks.append(make_check(
                    "narration_leak_check",
                    passed=True,
                ))

        return ValidationResult(
            is_valid=len(errors) == 0,
            checks=checks,
            errors=errors,
        )


__all__ = ["NarrationLeakValidator"]