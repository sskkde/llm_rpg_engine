#!/usr/bin/env python3
"""
Content pack validation CLI.

Validates a content pack directory and reports issues.

Usage:
    cd backend && python -m llm_rpg.scripts.validate_content_pack <pack_dir>
    cd backend && python -m llm_rpg.scripts.validate_content_pack <pack_dir> --format json

Exit codes:
    0: Content pack is valid (no errors, may have warnings)
    1: Content pack has validation errors
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from llm_rpg.content.loader import ContentPackLoadError, load_content_pack
from llm_rpg.content.validator import ContentValidator
from llm_rpg.models.content_pack import ContentValidationReport


def format_issue_human(issue: Any) -> str:
    """Format a validation issue for human-readable output."""
    severity_marker = {
        "error": "❌ ERROR",
        "warning": "⚠️  WARNING",
        "info": "ℹ️  INFO",
    }.get(issue.severity, issue.severity.upper())
    
    return f"{severity_marker}: {issue.message}\n    Path: {issue.path}\n    Code: {issue.code}"


def format_report_human(report: ContentValidationReport, pack_dir: str) -> str:
    """Format validation report for human-readable output."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"Content Pack Validation Report: {pack_dir}")
    lines.append("=" * 60)
    
    if report.is_valid:
        lines.append("\n✅ VALID: Content pack passed all validations")
    else:
        lines.append("\n❌ INVALID: Content pack has validation errors")
    
    if report.issues:
        error_count = sum(1 for i in report.issues if i.severity == "error")
        warning_count = sum(1 for i in report.issues if i.severity == "warning")
        info_count = sum(1 for i in report.issues if i.severity == "info")
        
        lines.append(f"\nIssues found: {len(report.issues)}")
        if error_count:
            lines.append(f"  Errors: {error_count}")
        if warning_count:
            lines.append(f"  Warnings: {warning_count}")
        if info_count:
            lines.append(f"  Info: {info_count}")
        
        lines.append("\n" + "-" * 60)
        lines.append("Details:")
        lines.append("-" * 60)
        
        for issue in report.issues:
            lines.append(f"\n{format_issue_human(issue)}")
    else:
        lines.append("\nNo issues found.")
    
    lines.append("\n" + "=" * 60)
    
    return "\n".join(lines)


def format_report_json(report: ContentValidationReport) -> str:
    """Format validation report as JSON for stdout."""
    output: Dict[str, Any] = {
        "is_valid": report.is_valid,
        "has_errors": report.has_errors(),
        "has_warnings": report.has_warnings(),
        "issue_count": len(report.issues),
        "issues": [
            {
                "severity": issue.severity,
                "message": issue.message,
                "path": issue.path,
                "code": issue.code,
            }
            for issue in report.issues
        ],
    }
    return json.dumps(output, indent=2)


def main() -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Validate a content pack directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
    0: Content pack is valid (no errors, may have warnings)
    1: Content pack has validation errors
        """,
    )
    parser.add_argument(
        "pack_dir",
        type=str,
        help="Path to the content pack directory (must contain pack.yaml)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["human", "json"],
        default="human",
        help="Output format: 'human' (stderr) or 'json' (stdout). Default: human",
    )
    
    args = parser.parse_args()
    pack_dir = Path(args.pack_dir)
    
    if not pack_dir.exists():
        print(f"ERROR: Pack directory does not exist: {pack_dir}", file=sys.stderr)
        return 1
    
    if not pack_dir.is_dir():
        print(f"ERROR: Path is not a directory: {pack_dir}", file=sys.stderr)
        return 1
    
    try:
        pack = load_content_pack(pack_dir)
        print(f"Loaded content pack: {pack.manifest.name} v{pack.manifest.version}", file=sys.stderr)
    except ContentPackLoadError as e:
        print(f"ERROR: Failed to load content pack: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: Unexpected error loading content pack: {e}", file=sys.stderr)
        return 1
    
    validator = ContentValidator()
    report = validator.validate(pack)
    
    if args.format == "json":
        print(format_report_json(report))
    else:
        print(format_report_human(report, str(pack_dir)), file=sys.stderr)
    
    return 0 if not report.has_errors() else 1


if __name__ == "__main__":
    sys.exit(main())
