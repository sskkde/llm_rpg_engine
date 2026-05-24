"""Unit tests for TimeAdvanceValidator and TimeAdvanceProposal."""

import pytest

from llm_rpg.core.time_advance import (
    DETERMINISTIC_DEFAULTS,
    INTENT_TO_TIME_CATEGORY,
    TimeAdvanceProposal,
)
from llm_rpg.core.time_advance_validator import (
    TimeAdvanceResult,
    TimeAdvanceValidator,
)
from llm_rpg.rules.action_schema import ActionType


# --- INTENT_TO_TIME_CATEGORY mapping tests ---

class TestIntentToTimeCategory:
    """Verify INTENT_TO_TIME_CATEGORY covers all 16 ActionType values."""

    ALL_ACTION_TYPES = [a.value for a in ActionType]

    def test_all_action_types_mapped(self):
        for action_type in self.ALL_ACTION_TYPES:
            assert action_type in INTENT_TO_TIME_CATEGORY, (
                f"ActionType '{action_type}' missing from INTENT_TO_TIME_CATEGORY"
            )

    def test_exactly_16_mappings(self):
        assert len(INTENT_TO_TIME_CATEGORY) == 16

    def test_specific_mappings(self):
        assert INTENT_TO_TIME_CATEGORY["move"] == "nearby_movement"
        assert INTENT_TO_TIME_CATEGORY["inspect"] == "inspect"
        assert INTENT_TO_TIME_CATEGORY["talk"] == "short_dialogue"
        assert INTENT_TO_TIME_CATEGORY["ask"] == "short_dialogue"
        assert INTENT_TO_TIME_CATEGORY["attack"] == "combat"
        assert INTENT_TO_TIME_CATEGORY["defend"] == "combat"
        assert INTENT_TO_TIME_CATEGORY["cast_skill"] == "combat"
        assert INTENT_TO_TIME_CATEGORY["use_item"] == "inspect"
        assert INTENT_TO_TIME_CATEGORY["take_item"] == "inspect"
        assert INTENT_TO_TIME_CATEGORY["give_item"] == "short_dialogue"
        assert INTENT_TO_TIME_CATEGORY["persuade"] == "long_dialogue"
        assert INTENT_TO_TIME_CATEGORY["hide"] == "inspect"
        assert INTENT_TO_TIME_CATEGORY["follow"] == "nearby_movement"
        assert INTENT_TO_TIME_CATEGORY["wait"] == "wait"
        assert INTENT_TO_TIME_CATEGORY["trigger_object"] == "inspect"
        assert INTENT_TO_TIME_CATEGORY["quest_progress"] == "short_dialogue"


# --- DETERMINISTIC_DEFAULTS tests ---

class TestDeterministicDefaults:
    """Verify DETERMINISTIC_DEFAULTS covers all categories from INTENT_TO_TIME_CATEGORY."""

    def test_all_mapped_categories_have_defaults(self):
        categories = set(INTENT_TO_TIME_CATEGORY.values())
        for category in categories:
            assert category in DETERMINISTIC_DEFAULTS, (
                f"Category '{category}' from INTENT_TO_TIME_CATEGORY missing from DETERMINISTIC_DEFAULTS"
            )

    def test_defaults_are_positive_integers(self):
        for category, minutes in DETERMINISTIC_DEFAULTS.items():
            assert isinstance(minutes, int) and minutes > 0, (
                f"DETERMINISTIC_DEFAULTS['{category}'] = {minutes}, expected positive int"
            )

    def test_extra_categories_beyond_mapping(self):
        categories_from_mapping = set(INTENT_TO_TIME_CATEGORY.values())
        extra = set(DETERMINISTIC_DEFAULTS.keys()) - categories_from_mapping
        assert extra == {"far_movement", "rest", "unknown"}


# --- CATEGORY_RANGES tests ---

class TestCategoryRanges:
    """Verify CATEGORY_RANGES for all categories."""

    def test_all_default_categories_have_ranges(self):
        for category in DETERMINISTIC_DEFAULTS:
            assert category in TimeAdvanceValidator.CATEGORY_RANGES, (
                f"Category '{category}' missing from CATEGORY_RANGES"
            )

    def test_ranges_are_valid_tuples(self):
        for category, (min_val, max_val) in TimeAdvanceValidator.CATEGORY_RANGES.items():
            assert min_val >= 0, f"Category '{category}' min={min_val}, must be >= 0"
            assert max_val > min_val, f"Category '{category}' max={max_val} must be > min={min_val}"

    def test_defaults_within_ranges(self):
        for category, default_minutes in DETERMINISTIC_DEFAULTS.items():
            min_val, max_val = TimeAdvanceValidator.CATEGORY_RANGES[category]
            assert min_val <= default_minutes <= max_val, (
                f"Default {default_minutes} for '{category}' outside range ({min_val}, {max_val})"
            )


# --- Validator clamping tests ---

class TestValidatorClamping:
    """Test validator clamps out-of-range values and marks adjusted=True."""

    def setup_method(self):
        self.validator = TimeAdvanceValidator()

    def test_clamp_above_max(self):
        proposal = TimeAdvanceProposal(
            elapsed_minutes=100,
            time_category="inspect",
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 5
        assert result.original_elapsed_minutes == 100
        assert result.adjusted is True
        assert "Clamped" in result.reason
        assert "max" in result.reason

    def test_clamp_below_min(self):
        proposal = TimeAdvanceProposal(
            elapsed_minutes=0,
            time_category="short_dialogue",
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 3
        assert result.original_elapsed_minutes == 0
        assert result.adjusted is True
        assert "Clamped" in result.reason
        assert "min" in result.reason

    def test_in_range_no_adjustment(self):
        proposal = TimeAdvanceProposal(
            elapsed_minutes=8,
            time_category="short_dialogue",
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 8
        assert result.original_elapsed_minutes == 8
        assert result.adjusted is False
        assert result.reason == ""

    def test_at_min_boundary(self):
        proposal = TimeAdvanceProposal(
            elapsed_minutes=3,
            time_category="short_dialogue",
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 3
        assert result.adjusted is False

    def test_at_max_boundary(self):
        proposal = TimeAdvanceProposal(
            elapsed_minutes=15,
            time_category="short_dialogue",
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 15
        assert result.adjusted is False


# --- elapsed_minutes=0 tests ---

class TestElapsedMinutesZero:
    """Test elapsed_minutes=0 returns original time unchanged (clamped to min)."""

    def setup_method(self):
        self.validator = TimeAdvanceValidator()

    def test_zero_clamped_to_category_min(self):
        proposal = TimeAdvanceProposal(
            elapsed_minutes=0,
            time_category="inspect",
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 1
        assert result.adjusted is True

    def test_zero_for_wait_category(self):
        proposal = TimeAdvanceProposal(
            elapsed_minutes=0,
            time_category="wait",
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 1
        assert result.adjusted is True


# --- MAX_ELAPSED_MINUTES cap test ---

class TestMaxElapsedMinutes:
    """Test MAX_ELAPSED_MINUTES cap is enforced."""

    def setup_method(self):
        self.validator = TimeAdvanceValidator()

    def test_wait_category_allows_up_to_1440(self):
        proposal = TimeAdvanceProposal(
            elapsed_minutes=1440,
            time_category="wait",
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 1440
        assert result.adjusted is False

    def test_rest_category_capped_by_own_max(self):
        proposal = TimeAdvanceProposal(
            elapsed_minutes=600,
            time_category="rest",
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 480
        assert result.adjusted is True

    def test_global_max_cap(self):
        proposal = TimeAdvanceProposal(
            elapsed_minutes=2000,
            time_category="wait",
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 1440
        assert result.adjusted is True


# --- Unknown category fallback test ---

class TestUnknownCategory:
    """Test unknown category falls back to (1, 15) range."""

    def setup_method(self):
        self.validator = TimeAdvanceValidator()

    def test_unknown_category_in_ranges(self):
        assert "unknown" in TimeAdvanceValidator.CATEGORY_RANGES
        assert TimeAdvanceValidator.CATEGORY_RANGES["unknown"] == (5, 15)

    def test_unmapped_category_falls_back(self):
        proposal = TimeAdvanceProposal(
            elapsed_minutes=50,
            time_category="nonexistent_category",
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 15
        assert result.adjusted is True

    def test_unmapped_category_below_fallback_min(self):
        proposal = TimeAdvanceProposal(
            elapsed_minutes=0,
            time_category="nonexistent_category",
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == 1
        assert result.adjusted is True


# --- TimeAdvanceProposal model tests ---

class TestTimeAdvanceProposal:
    """Test TimeAdvanceProposal model validation."""

    def test_valid_proposal(self):
        p = TimeAdvanceProposal(
            elapsed_minutes=10,
            time_category="inspect",
        )
        assert p.elapsed_minutes == 10
        assert p.time_category == "inspect"
        assert p.source == "deterministic"
        assert p.confidence == 0.0
        assert p.reason == ""
        assert p.display_hint is None

    def test_negative_elapsed_minutes_rejected(self):
        with pytest.raises(Exception):
            TimeAdvanceProposal(
                elapsed_minutes=-1,
                time_category="inspect",
            )

    def test_confidence_out_of_range_rejected(self):
        with pytest.raises(Exception):
            TimeAdvanceProposal(
                elapsed_minutes=5,
                time_category="inspect",
                confidence=1.5,
            )

    def test_custom_source(self):
        p = TimeAdvanceProposal(
            elapsed_minutes=10,
            time_category="inspect",
            source="explicit_llm",
        )
        assert p.source == "explicit_llm"


# --- TimeAdvanceResult model tests ---

class TestTimeAdvanceResult:
    """Test TimeAdvanceResult model."""

    def test_valid_result(self):
        r = TimeAdvanceResult(
            accepted_elapsed_minutes=5,
            original_elapsed_minutes=10,
            adjusted=True,
            reason="Clamped from 10 to 5",
            category="inspect",
        )
        assert r.accepted_elapsed_minutes == 5
        assert r.adjusted is True
        assert r.new_world_time == {}

    def test_negative_accepted_rejected(self):
        with pytest.raises(Exception):
            TimeAdvanceResult(
                accepted_elapsed_minutes=-1,
                original_elapsed_minutes=5,
                category="inspect",
            )


# --- Integration: full flow from ActionType to validated result ---

class TestFullFlow:
    """Integration test: ActionType → category → default → validated result."""

    def setup_method(self):
        self.validator = TimeAdvanceValidator()

    def test_move_action_flow(self):
        category = INTENT_TO_TIME_CATEGORY["move"]
        default_minutes = DETERMINISTIC_DEFAULTS[category]
        proposal = TimeAdvanceProposal(
            elapsed_minutes=default_minutes,
            time_category=category,
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == default_minutes
        assert result.adjusted is False

    def test_combat_action_flow(self):
        category = INTENT_TO_TIME_CATEGORY["attack"]
        default_minutes = DETERMINISTIC_DEFAULTS[category]
        proposal = TimeAdvanceProposal(
            elapsed_minutes=default_minutes,
            time_category=category,
        )
        result = self.validator.validate(proposal)
        assert result.accepted_elapsed_minutes == default_minutes
        assert result.adjusted is False

    def test_all_action_types_produce_valid_results(self):
        for action_type in ActionType:
            category = INTENT_TO_TIME_CATEGORY[action_type.value]
            default_minutes = DETERMINISTIC_DEFAULTS[category]
            proposal = TimeAdvanceProposal(
                elapsed_minutes=default_minutes,
                time_category=category,
            )
            result = self.validator.validate(proposal)
            assert result.accepted_elapsed_minutes == default_minutes
            assert result.adjusted is False
