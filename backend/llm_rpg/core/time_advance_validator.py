"""
Time Advance Validator

Validates and clamps TimeAdvanceProposal elapsed_minutes against
per-category ranges. Out-of-range values are clamped and marked as adjusted.
"""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from .time_advance import TimeAdvanceProposal


class TimeAdvanceResult(BaseModel):
    """Result of validating a TimeAdvanceProposal.

    Attributes:
        accepted_elapsed_minutes: The clamped/accepted minutes value
        original_elapsed_minutes: The original proposed minutes value
        adjusted: Whether the value was clamped
        reason: Explanation if adjusted
        category: The time category used
        new_world_time: Placeholder for computed new world time (populated by caller)
    """

    accepted_elapsed_minutes: int = Field(..., ge=0)
    original_elapsed_minutes: int = Field(..., ge=0)
    adjusted: bool = Field(False)
    reason: str = Field("")
    category: str = Field("")
    new_world_time: Dict[str, Any] = Field(default_factory=dict)


class TimeAdvanceValidator:
    """Validates time advance proposals against category-specific ranges.

    CATEGORY_RANGES defines (min, max) minute bounds per time category.
    Values outside the range are clamped and the result is marked adjusted=True.
    """

    CATEGORY_RANGES: dict[str, tuple[int, int]] = {
        "inspect": (1, 5),
        "short_dialogue": (3, 15),
        "long_dialogue": (10, 45),
        "nearby_movement": (5, 30),
        "far_movement": (30, 180),
        "combat": (1, 10),
        "rest": (30, 480),
        "wait": (1, 1440),
        "unknown": (5, 15),
    }

    MAX_ELAPSED_MINUTES: int = 1440

    def validate(self, proposal: TimeAdvanceProposal) -> TimeAdvanceResult:
        """Validate and clamp a time advance proposal.

        Args:
            proposal: The time advance proposal to validate.

        Returns:
            TimeAdvanceResult with accepted (clamped) value and adjustment info.
        """
        category_range = self.CATEGORY_RANGES.get(proposal.time_category, (1, 15))
        min_val, max_val = category_range

        original = proposal.elapsed_minutes
        clamped = max(min_val, min(original, max_val))
        clamped = min(clamped, self.MAX_ELAPSED_MINUTES)

        adjusted = clamped != original
        reason = ""
        if adjusted:
            if original > max_val:
                reason = f"Clamped from {original} to {max_val} (max for {proposal.time_category})"
            elif original < min_val:
                reason = f"Clamped from {original} to {min_val} (min for {proposal.time_category})"

        return TimeAdvanceResult(
            accepted_elapsed_minutes=clamped,
            original_elapsed_minutes=original,
            adjusted=adjusted,
            reason=reason,
            category=proposal.time_category,
            new_world_time={},
        )
