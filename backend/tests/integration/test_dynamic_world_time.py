"""
Integration tests for dynamic world time advancement.

Tests:
- "look around" (inspect) advances 1-5 minutes
- "talk to NPC" (short_dialogue) advances 3-15 minutes
- "move to far location" (far_movement) advances 30-180 minutes
- "rest" advances 30-480 minutes
- Midnight rollover (hour=23:30 + 60min → day+1, hour=0:30)
- Season boundary (day=30 + 子时 → day=1, season advances)
- Old period field still readable
- _resolve_elapsed_minutes reuses world stage output when available
"""

import pytest
from typing import Dict, Any

from llm_rpg.core.time_advance import (
    DETERMINISTIC_DEFAULTS,
    INTENT_TO_TIME_CATEGORY,
    TimeAdvanceProposal,
)
from llm_rpg.core.time_advance_validator import (
    TimeAdvanceResult,
    TimeAdvanceValidator,
)


# =============================================================================
# Helper to call _advance_world_time
# =============================================================================

def _advance_world_time(world_time: Dict[str, Any], elapsed_minutes: int) -> Dict[str, Any]:
    """Call the real _advance_world_time from turn_service."""
    from llm_rpg.core.turn_service import _advance_world_time as real_advance
    return real_advance(world_time, elapsed_minutes)


def _resolve_elapsed_minutes(
    action_type: str = None,
    intent_result: Any = None,
    world_result: Any = None,
) -> int:
    """Call the real _resolve_elapsed_minutes from turn_service."""
    from llm_rpg.core.turn_service import _resolve_elapsed_minutes as real_resolve
    return real_resolve(action_type, intent_result, world_result)


# =============================================================================
# Tests: Action Type to Time Category Mapping
# =============================================================================

class TestActionTypeToTimeCategory:
    """Test action types map to correct time categories."""

    def test_inspect_maps_to_inspect_category(self):
        assert INTENT_TO_TIME_CATEGORY["inspect"] == "inspect"

    def test_talk_maps_to_short_dialogue(self):
        assert INTENT_TO_TIME_CATEGORY["talk"] == "short_dialogue"

    def test_ask_maps_to_short_dialogue(self):
        assert INTENT_TO_TIME_CATEGORY["ask"] == "short_dialogue"

    def test_persuade_maps_to_long_dialogue(self):
        assert INTENT_TO_TIME_CATEGORY["persuade"] == "long_dialogue"

    def test_move_maps_to_nearby_movement(self):
        assert INTENT_TO_TIME_CATEGORY["move"] == "nearby_movement"

    def test_follow_maps_to_nearby_movement(self):
        assert INTENT_TO_TIME_CATEGORY["follow"] == "nearby_movement"

    def test_attack_maps_to_combat(self):
        assert INTENT_TO_TIME_CATEGORY["attack"] == "combat"

    def test_wait_maps_to_wait(self):
        assert INTENT_TO_TIME_CATEGORY["wait"] == "wait"


# =============================================================================
# Tests: Time Category Ranges
# =============================================================================

class TestTimeCategoryRanges:
    """Test time category ranges are correctly defined."""

    def test_inspect_range_1_to_5_minutes(self):
        validator = TimeAdvanceValidator()
        assert validator.CATEGORY_RANGES["inspect"] == (1, 5)

    def test_short_dialogue_range_3_to_15_minutes(self):
        validator = TimeAdvanceValidator()
        assert validator.CATEGORY_RANGES["short_dialogue"] == (3, 15)

    def test_long_dialogue_range_10_to_45_minutes(self):
        validator = TimeAdvanceValidator()
        assert validator.CATEGORY_RANGES["long_dialogue"] == (10, 45)

    def test_nearby_movement_range_5_to_30_minutes(self):
        validator = TimeAdvanceValidator()
        assert validator.CATEGORY_RANGES["nearby_movement"] == (5, 30)

    def test_far_movement_range_30_to_180_minutes(self):
        validator = TimeAdvanceValidator()
        assert validator.CATEGORY_RANGES["far_movement"] == (30, 180)

    def test_rest_range_30_to_480_minutes(self):
        validator = TimeAdvanceValidator()
        assert validator.CATEGORY_RANGES["rest"] == (30, 480)

    def test_combat_range_1_to_10_minutes(self):
        validator = TimeAdvanceValidator()
        assert validator.CATEGORY_RANGES["combat"] == (1, 10)


# =============================================================================
# Tests: Validator Clamping
# =============================================================================

class TestValidatorClamping:
    """Test TimeAdvanceValidator clamps values to category ranges."""

    def test_inspect_clamped_to_max_5(self):
        validator = TimeAdvanceValidator()
        proposal = TimeAdvanceProposal(
            elapsed_minutes=100,
            time_category="inspect",
        )
        result = validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 5
        assert result.adjusted is True

    def test_short_dialogue_clamped_to_range(self):
        validator = TimeAdvanceValidator()
        proposal = TimeAdvanceProposal(
            elapsed_minutes=2,
            time_category="short_dialogue",
        )
        result = validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 3
        assert result.adjusted is True

    def test_far_movement_clamped_to_max_180(self):
        validator = TimeAdvanceValidator()
        proposal = TimeAdvanceProposal(
            elapsed_minutes=500,
            time_category="far_movement",
        )
        result = validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 180
        assert result.adjusted is True

    def test_rest_clamped_to_max_480(self):
        validator = TimeAdvanceValidator()
        proposal = TimeAdvanceProposal(
            elapsed_minutes=600,
            time_category="rest",
        )
        result = validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 480
        assert result.adjusted is True

    def test_in_range_not_adjusted(self):
        validator = TimeAdvanceValidator()
        proposal = TimeAdvanceProposal(
            elapsed_minutes=10,
            time_category="short_dialogue",
        )
        result = validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 10
        assert result.adjusted is False


# =============================================================================
# Tests: World Time Advancement
# =============================================================================

class TestWorldTimeAdvancement:
    """Test _advance_world_time function."""

    def test_advance_within_same_hour(self):
        world_time = {
            "calendar": "青岚历",
            "season": "春",
            "day": "第1日",
            "period": "辰时",
            "hour": 9,
            "minute": 0,
        }
        result = _advance_world_time(world_time, 30)
        assert result["hour"] == 9
        assert result["minute"] == 30
        assert result["day"] == "第1日"
        assert result["season"] == "春"

    def test_advance_crosses_hour_boundary(self):
        world_time = {
            "calendar": "青岚历",
            "season": "春",
            "day": "第1日",
            "period": "辰时",
            "hour": 9,
            "minute": 45,
        }
        result = _advance_world_time(world_time, 30)
        assert result["hour"] == 10
        assert result["minute"] == 15
        assert result["day"] == "第1日"

    def test_midnight_rollover(self):
        world_time = {
            "calendar": "青岚历",
            "season": "春",
            "day": "第1日",
            "period": "亥时",
            "hour": 23,
            "minute": 30,
        }
        result = _advance_world_time(world_time, 60)
        assert result["hour"] == 0
        assert result["minute"] == 30
        assert result["day"] == "第2日"

    def test_midnight_rollover_period_changes(self):
        world_time = {
            "calendar": "青岚历",
            "season": "春",
            "day": "第1日",
            "period": "亥时",
            "hour": 23,
            "minute": 30,
        }
        result = _advance_world_time(world_time, 60)
        assert result["period"] == "子时"

    def test_season_boundary_day_30(self):
        world_time = {
            "calendar": "青岚历",
            "season": "春",
            "day": "第30日",
            "period": "亥时",
            "hour": 23,
            "minute": 0,
        }
        result = _advance_world_time(world_time, 120)
        assert result["day"] == "第1日"
        assert result["season"] == "夏"

    def test_season_boundary_winter_to_spring(self):
        world_time = {
            "calendar": "青岚历",
            "season": "冬",
            "day": "第30日",
            "period": "亥时",
            "hour": 23,
            "minute": 0,
        }
        result = _advance_world_time(world_time, 120)
        assert result["day"] == "第1日"
        assert result["season"] == "春"

    def test_elapsed_minutes_zero_no_change(self):
        world_time = {
            "calendar": "青岚历",
            "season": "春",
            "day": "第5日",
            "period": "午时",
            "hour": 12,
            "minute": 30,
        }
        result = _advance_world_time(world_time, 0)
        assert result["hour"] == 12
        assert result["minute"] == 30
        assert result["day"] == "第5日"
        assert result["season"] == "春"

    def test_result_includes_display_text(self):
        world_time = {
            "calendar": "青岚历",
            "season": "春",
            "day": "第1日",
            "period": "辰时",
            "hour": 9,
            "minute": 0,
        }
        result = _advance_world_time(world_time, 30)
        assert "display_text" in result
        assert "青岚历" in result["display_text"]
        assert "春" in result["display_text"]


# =============================================================================
# Tests: Period Field Backward Compatibility
# =============================================================================

class TestPeriodFieldBackwardCompat:
    """Test old period field is still readable."""

    def test_result_includes_period(self):
        world_time = {
            "calendar": "青岚历",
            "season": "春",
            "day": "第1日",
            "period": "辰时",
            "hour": 9,
            "minute": 0,
        }
        result = _advance_world_time(world_time, 30)
        assert "period" in result
        assert result["period"] in [
            "子时", "丑时", "寅时", "卯时", "辰时", "巳时",
            "午时", "未时", "申时", "酉时", "戌时", "亥时",
        ]

    def test_period_derived_from_hour(self):
        world_time = {
            "calendar": "青岚历",
            "season": "春",
            "day": "第1日",
            "period": "辰时",
            "hour": 9,
            "minute": 0,
        }
        result = _advance_world_time(world_time, 60)
        assert result["hour"] == 10
        assert result["period"] == "巳时"

    def test_old_behavior_elapsed_minutes_none(self):
        world_time = {
            "calendar": "青岚历",
            "season": "春",
            "day": "第1日",
            "period": "辰时",
        }
        from llm_rpg.core.turn_service import _advance_world_time as real_advance
        result = real_advance(world_time, elapsed_minutes=None)
        assert "period" in result
        assert result["period"] == "巳时"


# =============================================================================
# Tests: _resolve_elapsed_minutes
# =============================================================================

class TestResolveElapsedMinutes:
    """Test _resolve_elapsed_minutes function."""

    def test_fallback_to_deterministic_default(self):
        minutes = _resolve_elapsed_minutes(action_type="inspect")
        assert minutes == DETERMINISTIC_DEFAULTS["inspect"]

    def test_talk_uses_short_dialogue_default(self):
        minutes = _resolve_elapsed_minutes(action_type="talk")
        assert minutes == DETERMINISTIC_DEFAULTS["short_dialogue"]

    def test_persuade_uses_long_dialogue_default(self):
        minutes = _resolve_elapsed_minutes(action_type="persuade")
        assert minutes == DETERMINISTIC_DEFAULTS["long_dialogue"]

    def test_move_uses_nearby_movement_default(self):
        minutes = _resolve_elapsed_minutes(action_type="move")
        assert minutes == DETERMINISTIC_DEFAULTS["nearby_movement"]

    def test_wait_uses_wait_default(self):
        minutes = _resolve_elapsed_minutes(action_type="wait")
        assert minutes == DETERMINISTIC_DEFAULTS["wait"]

    def test_unknown_action_falls_back_to_10(self):
        minutes = _resolve_elapsed_minutes(action_type="unknown_action_xyz")
        assert minutes == 10

    def test_world_result_takes_priority(self):
        class MockWorldResult:
            parsed_proposal = {"elapsed_minutes": 42}

        minutes = _resolve_elapsed_minutes(
            action_type="inspect",
            world_result=MockWorldResult(),
        )
        assert minutes == 42

    def test_intent_result_used_when_no_world_result(self):
        class MockIntentResult:
            parsed_proposal = {"intent_type": "talk"}

        minutes = _resolve_elapsed_minutes(
            action_type="inspect",
            intent_result=MockIntentResult(),
        )
        assert minutes == DETERMINISTIC_DEFAULTS["short_dialogue"]


# =============================================================================
# Tests: Full Flow - Action to Time Advance
# =============================================================================

class TestFullFlowActionToTimeAdvance:
    """Test full flow from action type to time advancement."""

    def test_inspect_action_advances_1_to_5_minutes(self):
        validator = TimeAdvanceValidator()
        category = INTENT_TO_TIME_CATEGORY["inspect"]
        default = DETERMINISTIC_DEFAULTS[category]
        proposal = TimeAdvanceProposal(
            elapsed_minutes=default,
            time_category=category,
        )
        result = validator.validate(proposal)
        assert 1 <= result.accepted_elapsed_minutes <= 5

    def test_talk_action_advances_3_to_15_minutes(self):
        validator = TimeAdvanceValidator()
        category = INTENT_TO_TIME_CATEGORY["talk"]
        default = DETERMINISTIC_DEFAULTS[category]
        proposal = TimeAdvanceProposal(
            elapsed_minutes=default,
            time_category=category,
        )
        result = validator.validate(proposal)
        assert 3 <= result.accepted_elapsed_minutes <= 15

    def test_persuade_action_advances_10_to_45_minutes(self):
        validator = TimeAdvanceValidator()
        category = INTENT_TO_TIME_CATEGORY["persuade"]
        default = DETERMINISTIC_DEFAULTS[category]
        proposal = TimeAdvanceProposal(
            elapsed_minutes=default,
            time_category=category,
        )
        result = validator.validate(proposal)
        assert 10 <= result.accepted_elapsed_minutes <= 45

    def test_far_movement_advances_30_to_180_minutes(self):
        validator = TimeAdvanceValidator()
        category = "far_movement"
        default = DETERMINISTIC_DEFAULTS[category]
        proposal = TimeAdvanceProposal(
            elapsed_minutes=default,
            time_category=category,
        )
        result = validator.validate(proposal)
        assert 30 <= result.accepted_elapsed_minutes <= 180

    def test_rest_advances_30_to_480_minutes(self):
        validator = TimeAdvanceValidator()
        category = "rest"
        default = DETERMINISTIC_DEFAULTS[category]
        proposal = TimeAdvanceProposal(
            elapsed_minutes=default,
            time_category=category,
        )
        result = validator.validate(proposal)
        assert 30 <= result.accepted_elapsed_minutes <= 480
