#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from llm_rpg.content.importer import ContentImportService
from llm_rpg.storage.database import SessionLocal


def format_report_human(report, pack_dir: str) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append(f"Content Pack Import Report: {pack_dir}")
    lines.append("=" * 60)

    if report.dry_run:
        lines.append("\n📋 DRY RUN - No changes were made to the database")

    lines.append(f"\nPack: {report.pack_name} (ID: {report.pack_id})")

    if report.success:
        lines.append("\n✅ SUCCESS")
        lines.append(f"  Factions imported: {report.factions_imported}")
        lines.append(f"  Plot beats imported: {report.plot_beats_imported}")
        lines.append(f"  Total items: {report.imported_count}")
    else:
        lines.append("\n❌ FAILED")
        for error in report.errors:
            lines.append(f"  ERROR: {error}")

    if report.warnings:
        lines.append(f"\n⚠️  Warnings ({len(report.warnings)}):")
        for warning in report.warnings:
            lines.append(f"  {warning}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def format_report_json(report) -> str:
    output = {
        "success": report.success,
        "dry_run": report.dry_run,
        "pack_id": report.pack_id,
        "pack_name": report.pack_name,
        "imported_count": report.imported_count,
        "factions_imported": report.factions_imported,
        "plot_beats_imported": report.plot_beats_imported,
        "errors": report.errors,
        "warnings": report.warnings,
    }
    return json.dumps(output, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import a content pack into the database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
    0: Import succeeded
    1: Import failed (validation errors or database errors)
        """,
    )
    parser.add_argument(
        "pack_dir",
        type=str,
        help="Path to the content pack directory (must contain pack.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without writing to database",
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

    db = SessionLocal()
    try:
        service = ContentImportService(db)
        report = service.import_pack(pack_dir, dry_run=args.dry_run)

        if args.format == "json":
            print(format_report_json(report))
        else:
            print(format_report_human(report, str(pack_dir)), file=sys.stderr)

        return 0 if report.success else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
