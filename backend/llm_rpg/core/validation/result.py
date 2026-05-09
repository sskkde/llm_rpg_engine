"""Unified Validation Result Module.

This module provides a unified interface for validation results across all validators.
It re-exports ValidationResult and ValidationCheck from models/common for convenience,
and provides helper functions for creating common validation results.

Design Principles:
- Single source of truth: ValidationResult is defined in models/common.py
- This module re-exports for convenience and adds helper utilities
- All validators should use this module for creating results
"""

from ...models.common import ValidationCheck, ValidationResult


def passed_result(
    check_name: str,
    reason: str = "",
    severity: str = "info",
) -> ValidationResult:
    """Create a simple passed ValidationResult with one check.

    Args:
        check_name: Name of the validation check
        reason: Optional reason/message
        severity: Severity level (info, warning, error)

    Returns:
        ValidationResult with is_valid=True
    """
    return ValidationResult(
        is_valid=True,
        checks=[ValidationCheck(
            check_name=check_name,
            passed=True,
            reason=reason,
            severity=severity,
        )],
        errors=[],
        warnings=[],
    )


def failed_result(
    check_name: str,
    reason: str,
    severity: str = "error",
) -> ValidationResult:
    """Create a simple failed ValidationResult with one check.

    Args:
        check_name: Name of the validation check
        reason: Reason for failure
        severity: Severity level (default: error)

    Returns:
        ValidationResult with is_valid=False and one error
    """
    return ValidationResult(
        is_valid=False,
        checks=[ValidationCheck(
            check_name=check_name,
            passed=False,
            reason=reason,
            severity=severity,
        )],
        errors=[reason],
        warnings=[],
    )


def combine_results(results: list[ValidationResult]) -> ValidationResult:
    """Combine multiple ValidationResult into one.

    Args:
        results: List of ValidationResult to combine

    Returns:
        Combined ValidationResult with all checks, errors, and warnings
    """
    all_checks: list[ValidationCheck] = []
    all_errors: list[str] = []
    all_warnings: list[str] = []

    for result in results:
        all_checks.extend(result.checks)
        all_errors.extend(result.errors)
        all_warnings.extend(result.warnings)

    return ValidationResult(
        is_valid=len(all_errors) == 0,
        checks=all_checks,
        errors=all_errors,
        warnings=all_warnings,
    )


def make_check(
    check_name: str,
    passed: bool,
    reason: str = "",
    severity: str = "error",
) -> ValidationCheck:
    """Create a ValidationCheck instance.

    Args:
        check_name: Name of the check
        passed: Whether the check passed
        reason: Reason/message
        severity: Severity level

    Returns:
        ValidationCheck instance
    """
    return ValidationCheck(
        check_name=check_name,
        passed=passed,
        reason=reason,
        severity=severity,
    )


__all__ = [
    "ValidationResult",
    "ValidationCheck",
    "passed_result",
    "failed_result",
    "combine_results",
    "make_check",
]