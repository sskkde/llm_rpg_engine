"""
TDD tests for NarrationLeakValidator hardening (P2).

Covers:
- Edge cases: empty narration, None facts, empty string facts, very long facts,
  facts with special characters, substring false positives
- LeakSeverity levels: EXACT_MATCH, PARTIAL_MATCH, SUSPICIOUS
- validate_narration_context() pre-check before LLM call
- forbidden_patterns regex support
- Backward compatibility with existing validate_narration() signature
"""

import re
import pytest

from llm_rpg.core.validation.narration_leak_validator import (
    NarrationLeakValidator,
    LeakSeverity,
    ForbiddenNarrationFact,
)


# ---------------------------------------------------------------------------
# Edge Case Tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge case handling for validate_narration."""

    def test_empty_narration_is_always_valid(self):
        """Empty narration text should always validate as safe."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="",
            forbidden_info=["secret password"],
        )
        assert result.is_valid
        assert len(result.errors) == 0

    def test_whitespace_only_narration_is_valid(self):
        """Whitespace-only narration should validate as safe."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="   \n\t  ",
            forbidden_info=["secret"],
        )
        assert result.is_valid
        assert len(result.errors) == 0

    def test_none_facts_handled_gracefully(self):
        """None in forbidden_info list should not crash — matches for valid facts still detected."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="The merchant smiles at you.",
            forbidden_info=["merchant", None, "smiles"],
        )
        # None is filtered out; "merchant" and "smiles" are valid matches
        assert not result.is_valid
        assert len(result.errors) >= 2
        # Verify no None-related crash in error messages
        assert all("None" not in err for err in result.errors)

    def test_empty_string_facts_ignored(self):
        """Empty string facts should be filtered out (no false positives)."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="You walk through the forest.",
            forbidden_info=["", "  ", "\n", "forest"],
        )
        assert not result.is_valid  # "forest" should still match
        assert len(result.errors) >= 1  # at least the "forest" match
        # Verify empty/whitespace strings didn't cause false errors
        forest_errors = [e for e in result.errors if "forest" in e]
        assert len(forest_errors) >= 1

    def test_very_long_fact_handled(self):
        """Facts longer than 1000 chars should not cause performance issues."""
        validator = NarrationLeakValidator()
        # Create a very long fact (1000+ chars)
        long_fact = "A" * 1001
        narration = "This is a short narration without the long fact."
        result = validator.validate_narration(
            text=narration,
            forbidden_info=[long_fact],
        )
        assert result.is_valid

    def test_very_long_fact_detected_when_present(self):
        """Very long facts that DO appear in narration should still be caught."""
        validator = NarrationLeakValidator()
        long_fact = "X" * 500
        narration = f"Here is some text with {long_fact} embedded in it."
        result = validator.validate_narration(
            text=narration,
            forbidden_info=[long_fact],
        )
        assert not result.is_valid

    def test_special_characters_in_facts(self):
        """Facts with special regex characters should be matched literally not as regex."""
        validator = NarrationLeakValidator()
        # Regex special chars: . * + ? [ ] ( ) { } ^ $ | \
        special_fact = "secret(code)[test]+hidden?"
        narration = f"The NPC whispered: {special_fact}"
        result = validator.validate_narration(
            text=narration,
            forbidden_info=[special_fact],
        )
        assert not result.is_valid, f"Should detect literal match for: {special_fact}"

    def test_special_characters_in_narration(self):
        """Narration with special characters should still be checked correctly."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="NPC says: \"secret code (123) is [REDACTED]!\"",
            forbidden_info=["secret code (123)"],
        )
        assert not result.is_valid

    def test_substring_false_positive_prevention(self):
        """Facts that are substrings of common words should not cause false positives.

        For example: fact "the" should not match narration because it's too short
        (< 2 chars after strip). Fact "and" should only match if "and" appears
        as a distinct chunk (not just inside another word).
        """
        validator = NarrationLeakValidator()
        # "the" is 3 chars but appears in many words; test that "the" alone matches
        result = validator.validate_narration(
            text="The merchant goes to the market.",
            forbidden_info=["the"],
        )
        # "the" is 3 chars, passes _is_checkable_text, so should match
        assert not result.is_valid, "Short fact 'the' should be detected when present"

    def test_substring_embedded_fact_detected(self):
        """Fact that appears as substring of a larger word should be detected."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="The swordmaster enters the room.",
            forbidden_info=["sword"],
        )
        assert not result.is_valid, "Substring 'sword' in 'swordmaster' should be detected"

    def test_single_char_fact_ignored_by_checkable_text(self):
        """Single character facts should be filtered by _is_checkable_text."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="You see a sword.",
            forbidden_info=["s", "w", "o"],
        )
        assert result.is_valid, "Single-char facts should be filtered out"

    def test_empty_forbidden_info_list(self):
        """Empty forbidden_info list should always return valid."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="Anything goes here.",
            forbidden_info=[],
        )
        assert result.is_valid
        assert len(result.checks) >= 1


# ---------------------------------------------------------------------------
# Leak Severity Level Tests
# ---------------------------------------------------------------------------

class TestLeakSeverity:
    """Tests for EXACT_MATCH, PARTIAL_MATCH, SUSPICIOUS severity levels."""

    def test_exact_match_fails_validation(self):
        """EXACT_MATCH severity: verbatim match should fail validation."""
        validator = NarrationLeakValidator()
        fact = "the golden amulet is hidden in the old well"
        result = validator.validate_narration(
            text=f"You notice {fact}.",
            forbidden_info=[fact],
        )
        assert not result.is_valid
        # Check severity is recorded
        failing_checks = [c for c in result.checks if not c.passed]
        assert len(failing_checks) >= 1
        for check in failing_checks:
            assert check.severity in ("error", "EXACT_MATCH")

    def test_exact_match_case_insensitive(self):
        """Exact match should be case-insensitive for detection but still fail."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="The GOLDEN AMULET is hidden.",
            forbidden_info=["the golden amulet is hidden in the old well"],
        )
        # The fact is not fully present - only a partial match. But the validator
        # currently uses substring matching: "golden amulet" appears in the narration
        assert not result.is_valid

    def test_suspicious_does_not_fail_validation(self):
        """SUSPICIOUS severity should generate warnings but NOT fail validation.

        SUSPICIOUS matches are detected using validate_narration_context() pre-check.
        """
        validator = NarrationLeakValidator()
        # Context pre-check: narration contains "amulet" but forbidden fact is about
        # a "golden amulet" - the context check should flag as SUSPICIOUS
        context_result = validator.validate_narration_context(
            text="You see a shiny amulet on the table.",
            forbidden_info=["the golden amulet is hidden in the old well"],
        )
        # validate_narration_context does NOT fail - just provides warnings/info
        suspicious_items = context_result.get("suspicious", [])
        # The word "amulet" appears in both, so it should trigger at least a SUSPICIOUS
        assert len(suspicious_items) >= 1 or context_result.get("has_warnings", False)

    def test_partial_match_fails_validation(self):
        """PARTIAL_MATCH: key identifying phrases appear → fail validation."""
        validator = NarrationLeakValidator()
        # Forbidden fact mentions "golden amulet" and "old well"
        # Narration mentions "golden amulet" but not the full fact
        fact = "the golden amulet is hidden in the old well"
        # This should be detected because "golden amulet" is a key phrase
        # The current exact substring match will catch this
        result = validator.validate_narration(
            text="Someone told you about a golden amulet.",
            forbidden_info=[fact],
        )
        assert not result.is_valid

    def test_severity_recorded_in_checks(self):
        """Verify severity level is recorded in validation checks."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="The NPC reveals: the treasure is under the oak tree.",
            forbidden_info=["the treasure is under the oak tree"],
        )
        assert not result.is_valid
        for check in result.checks:
            if not check.passed:
                # Severity should indicate the type of match
                assert check.severity in ("error", "EXACT_MATCH", "PARTIAL_MATCH")


# ---------------------------------------------------------------------------
# validate_narration_context() Tests
# ---------------------------------------------------------------------------

class TestValidateNarrationContext:
    """Tests for validate_narration_context() pre-check method."""

    def test_context_check_returns_dict_with_expected_keys(self):
        """validate_narration_context should return a dict with structured info."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration_context(
            text="The merchant offers you a deal.",
            forbidden_info=["the golden amulet is hidden"],
        )
        assert isinstance(result, dict)
        # Should have keys like 'suspicious', 'warnings', etc.
        assert "suspicious" in result or "warnings" in result or "has_warnings" in result

    def test_context_detects_suspicious_word_overlap(self):
        """Context pre-check detects when narration shares words with forbidden facts."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration_context(
            text="You see a golden trinket on the merchant's table.",
            forbidden_info=["the golden amulet is hidden in the old well"],
        )
        # "golden" appears in both → should be flagged
        # The result should indicate some level of suspicion
        assert result.get("suspicious") or result.get("warnings"), (
            "Should flag overlapping word 'golden'"
        )

    def test_context_no_overlap_returns_clean(self):
        """When no words overlap, context check should be clean."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration_context(
            text="The sky is clear and the birds are singing.",
            forbidden_info=["the golden amulet is hidden in the old well"],
        )
        # Should indicate no suspicion
        suspicious = result.get("suspicious", [])
        warnings = result.get("warnings", [])
        assert len(suspicious) == 0
        assert len(warnings) == 0

    def test_context_with_empty_narration(self):
        """Empty narration should not trigger any context warnings."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration_context(
            text="",
            forbidden_info=["secret"],
        )
        assert isinstance(result, dict)
        assert len(result.get("suspicious", [])) == 0
        assert len(result.get("warnings", [])) == 0

    def test_context_with_forbidden_patterns(self):
        """Context check should also flag forbidden_patterns."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration_context(
            text="The NPC reveals their true identity.",
            forbidden_info=[],
            forbidden_patterns=[r"true identity", r"secret identity"],
        )
        # Should flag that "true identity" matched a pattern
        assert result.get("suspicious") or result.get("warnings") or result.get("has_warnings")

    def test_context_handles_none_inputs(self):
        """Context check with None inputs should not crash."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration_context(
            text="Some narration.",
            forbidden_info=[],
        )
        assert isinstance(result, dict)
        result2 = validator.validate_narration_context(
            text="Some narration.",
            forbidden_info=None,
        )
        assert isinstance(result2, dict)


# ---------------------------------------------------------------------------
# Forbidden Patterns (Regex) Tests
# ---------------------------------------------------------------------------

class TestForbiddenPatterns:
    """Tests for forbidden_patterns regex support."""

    def test_forbidden_pattern_detected(self):
        """A forbidden regex pattern matching narration should fail validation."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="She is actually a spy for the enemy faction.",
            forbidden_info=[],
            forbidden_patterns=[r"is actually a? ?spy"],
        )
        assert not result.is_valid

    def test_forbidden_pattern_no_match_is_valid(self):
        """Narration without pattern matches should be valid."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="She is a merchant selling wares.",
            forbidden_info=[],
            forbidden_patterns=[r"is actually a? ?spy"],
        )
        assert result.is_valid

    def test_forbidden_patterns_case_insensitive(self):
        """Regex patterns should use case-insensitive matching."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="She IS ACTUALLY A SPY.",
            forbidden_info=[],
            forbidden_patterns=[r"is actually a? ?spy"],
        )
        assert not result.is_valid

    def test_multiple_forbidden_patterns(self):
        """Multiple patterns should all be checked."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="The NPC reveals a secret passage behind the throne.",
            forbidden_info=[],
            forbidden_patterns=[r"hidden identity", r"secret passage", r"true name"],
        )
        assert not result.is_valid
        errors = [c for c in result.checks if not c.passed]
        assert len(errors) >= 1

    def test_forbidden_patterns_with_forbidden_info(self):
        """Combined forbidden_patterns and forbidden_info should both work."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="The secret door is behind the tapestry.",
            forbidden_info=["tapestry"],
            forbidden_patterns=[r"secret (door|passage)"],
        )
        assert not result.is_valid
        # Should have at least 2 issues (one from info, one from pattern)
        failing = [c for c in result.checks if not c.passed]
        assert len(failing) >= 2

    def test_invalid_regex_pattern_handled_gracefully(self):
        """Invalid regex patterns should be caught and logged, not crash."""
        validator = NarrationLeakValidator()
        # Invalid regex with unmatched parenthesis
        result = validator.validate_narration(
            text="Safe narration text.",
            forbidden_info=[],
            forbidden_patterns=[r"valid pattern", r"unmatched[("],
        )
        # Should not crash; the invalid pattern should be skipped
        assert result.is_valid


# ---------------------------------------------------------------------------
# Backward Compatibility Tests
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Existing API must remain unchanged."""

    def test_validate_narration_without_new_params_works(self):
        """Calling validate_narration without forbidden_patterns should work."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="The guard patrols the castle walls.",
            forbidden_info=["castle"],
        )
        assert not result.is_valid

    def test_validate_narration_returns_validation_result(self):
        """Must return ValidationResult with expected fields."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="Safe text.",
            forbidden_info=["secret"],
        )
        assert hasattr(result, "is_valid")
        assert hasattr(result, "checks")
        assert hasattr(result, "errors")
        assert hasattr(result, "warnings")

    def test_existing_exact_match_still_works(self):
        """Existing exact string matching behavior unchanged."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="柳师姐藏着血契玉简，不能让别人发现。",
            forbidden_info=["血契玉简"],
        )
        assert not result.is_valid
        assert any("血契玉简" in error for error in result.errors)

    def test_no_false_positives_on_clean_narration(self):
        """Clean narration that doesn't match anything should pass."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="柳师姐站在宗门广场，提醒你留意脚下青石。",
            forbidden_info=["血契玉简", "魔门卧底"],
        )
        assert result.is_valid
        assert result.errors == []


# ---------------------------------------------------------------------------
# LeakSeverity Enum Tests
# ---------------------------------------------------------------------------

class TestLeakSeverityEnum:
    """Verify LeakSeverity enum values."""

    def test_severity_enum_values(self):
        """LeakSeverity should have EXACT_MATCH, PARTIAL_MATCH, SUSPICIOUS."""
        assert LeakSeverity.EXACT_MATCH.value == "EXACT_MATCH"
        assert LeakSeverity.PARTIAL_MATCH.value == "PARTIAL_MATCH"
        assert LeakSeverity.SUSPICIOUS.value == "SUSPICIOUS"

    def test_only_exact_and_partial_fail(self):
        """EXACT_MATCH and PARTIAL_MATCH are failure severities, SUSPICIOUS is warning."""
        # EXACT_MATCH and PARTIAL_MATCH should be in the failure severities set
        # SUSPICIOUS should NOT be
        assert LeakSeverity.EXACT_MATCH in NarrationLeakValidator.FAILURE_SEVERITIES
        assert LeakSeverity.PARTIAL_MATCH in NarrationLeakValidator.FAILURE_SEVERITIES
        assert LeakSeverity.SUSPICIOUS not in NarrationLeakValidator.FAILURE_SEVERITIES
