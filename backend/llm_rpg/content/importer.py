from pathlib import Path
from typing import List

from sqlalchemy.orm import Session

from llm_rpg.content.loader import load_content_pack, ContentPackLoadError
from llm_rpg.content.validator import ContentValidator
from llm_rpg.models.content_pack import (
    ContentImportReport,
    ContentPackDefinition,
    FactionDefinition,
    PlotBeatDefinition,
)
from llm_rpg.storage.repositories import FactionRepository, PlotBeatRepository


class ContentImportService:
    def __init__(self, db: Session):
        self.db = db
        self.faction_repo = FactionRepository(db)
        self.plot_beat_repo = PlotBeatRepository(db)
        self.validator = ContentValidator()

    def import_pack(self, pack_dir: Path, dry_run: bool = False) -> ContentImportReport:
        try:
            pack = load_content_pack(Path(pack_dir))
        except ContentPackLoadError as e:
            return ContentImportReport(
                success=False,
                errors=[f"Failed to load content pack: {e}"],
                dry_run=dry_run,
            )
        except Exception as e:
            return ContentImportReport(
                success=False,
                errors=[f"Unexpected error loading pack: {e}"],
                dry_run=dry_run,
            )

        validation_report = self.validator.validate(pack)

        if validation_report.has_errors():
            errors = [
                f"{issue.path}: {issue.message}"
                for issue in validation_report.issues
                if issue.severity == "error"
            ]
            return ContentImportReport(
                success=False,
                errors=errors,
                dry_run=dry_run,
                pack_id=pack.manifest.id,
                pack_name=pack.manifest.name,
            )

        warnings = [
            f"{issue.path}: {issue.message}"
            for issue in validation_report.issues
            if issue.severity == "warning"
        ]

        if dry_run:
            return ContentImportReport(
                success=True,
                imported_count=len(pack.factions) + len(pack.plot_beats),
                factions_imported=len(pack.factions),
                plot_beats_imported=len(pack.plot_beats),
                warnings=warnings,
                dry_run=True,
                pack_id=pack.manifest.id,
                pack_name=pack.manifest.name,
            )

        try:
            factions_imported = self._import_factions(pack.factions)
            plot_beats_imported = self._import_plot_beats(pack.plot_beats)
        except Exception as e:
            return ContentImportReport(
                success=False,
                errors=[f"Database error during import: {e}"],
                dry_run=False,
                pack_id=pack.manifest.id,
                pack_name=pack.manifest.name,
            )

        return ContentImportReport(
            success=True,
            imported_count=factions_imported + plot_beats_imported,
            factions_imported=factions_imported,
            plot_beats_imported=plot_beats_imported,
            warnings=warnings,
            dry_run=False,
            pack_id=pack.manifest.id,
            pack_name=pack.manifest.name,
        )

    def _import_factions(self, factions: List[FactionDefinition]) -> int:
        count = 0
        for faction in factions:
            data = self._faction_to_dict(faction)
            self.faction_repo.upsert_definition(data)
            count += 1
        return count

    def _import_plot_beats(self, plot_beats: List[PlotBeatDefinition]) -> int:
        count = 0
        for beat in plot_beats:
            data = self._plot_beat_to_dict(beat)
            self.plot_beat_repo.upsert_definition(data)
            count += 1
        return count

    def _faction_to_dict(self, faction: FactionDefinition) -> dict:
        return {
            "logical_id": faction.id,
            "world_id": faction.world_id,
            "name": faction.name,
            "ideology": faction.ideology,
            "goals": [g.model_dump() for g in faction.goals],
            "relationships": [r.model_dump() for r in faction.relationships],
            "visibility": faction.visibility,
            "status": "active",
        }

    def _plot_beat_to_dict(self, beat: PlotBeatDefinition) -> dict:
        return {
            "logical_id": beat.id,
            "world_id": beat.world_id,
            "title": beat.title,
            "conditions": [c.model_dump() for c in beat.conditions],
            "effects": [e.model_dump() for e in beat.effects],
            "priority": beat.priority,
            "visibility": beat.visibility.value,
            "status": beat.status,
        }
