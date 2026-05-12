import pytest
import tempfile
from pathlib import Path
from sqlalchemy.orm import Session

from llm_rpg.content.importer import ContentImportService
from llm_rpg.storage.models import WorldModel, FactionModel, PlotBeatModel
from llm_rpg.storage.repositories import FactionRepository, PlotBeatRepository


PACK_ID = "test_pack"


@pytest.fixture
def test_world(db_session: Session) -> WorldModel:
    world = WorldModel(
        id=PACK_ID,
        code="test_pack",
        name="Test World",
        genre="xianxia",
        status="active"
    )
    db_session.add(world)
    db_session.commit()
    db_session.refresh(world)
    return world


@pytest.fixture
def valid_pack_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        pack_dir = Path(tmpdir)
        
        pack_yaml = pack_dir / "pack.yaml"
        pack_yaml.write_text(f"""id: {PACK_ID}
name: Test Pack
version: 1.0.0
description: A test content pack
author: test
""")
        
        factions_yaml = pack_dir / "factions.yaml"
        factions_yaml.write_text("""factions:
  - id: faction_a
    name: Faction A
    ideology: Test ideology
    goals:
      - goal_id: g1
        description: Test goal
    relationships: {}
    visibility: public
  - id: faction_b
    name: Faction B
    ideology: Another ideology
    goals: []
    relationships:
      faction_a: ally
    visibility: public
""")
        
        plot_beats_yaml = pack_dir / "plot_beats.yaml"
        plot_beats_yaml.write_text("""plot_beats:
  - id: beat_1
    name: Test Beat 1
    priority: 50
    visibility: conditional
    trigger_conditions:
      location: test_location
    effects:
      - type: set_flag
        key: test_flag
        value: true
  - id: beat_2
    name: Test Beat 2
    priority: 30
    visibility: hidden
    trigger_conditions: {}
    effects: []
""")
        
        yield pack_dir


@pytest.fixture
def invalid_pack_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        pack_dir = Path(tmpdir)
        
        pack_yaml = pack_dir / "pack.yaml"
        pack_yaml.write_text("""id: invalid_pack
name: Invalid Pack
version: 1.0.0
""")
        
        factions_yaml = pack_dir / "factions.yaml"
        factions_yaml.write_text("""factions:
  - id: duplicate_id
    name: First Faction
    goals: []
    relationships: {}
  - id: duplicate_id
    name: Second Faction
    goals: []
    relationships: {}
""")
        
        yield pack_dir


@pytest.fixture
def pack_with_bad_reference() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        pack_dir = Path(tmpdir)
        
        pack_yaml = pack_dir / "pack.yaml"
        pack_yaml.write_text("""id: bad_ref_pack
name: Bad Reference Pack
version: 1.0.0
""")
        
        factions_yaml = pack_dir / "factions.yaml"
        factions_yaml.write_text("""factions:
  - id: faction_a
    name: Faction A
    goals: []
    relationships:
      nonexistent_faction: ally
    visibility: public
""")
        
        yield pack_dir


class TestContentImportServiceDryRun:
    def test_dry_run_does_not_write_to_db(self, db_session: Session, test_world: WorldModel, valid_pack_dir: Path):
        service = ContentImportService(db_session)
        faction_repo = FactionRepository(db_session)
        plot_beat_repo = PlotBeatRepository(db_session)
        
        factions_before = faction_repo.list_by_world(test_world.id)
        beats_before = plot_beat_repo.list_by_world(test_world.id)
        
        report = service.import_pack(valid_pack_dir, dry_run=True)
        
        assert report.success is True
        assert report.dry_run is True
        assert report.factions_imported == 2
        assert report.plot_beats_imported == 2
        
        factions_after = faction_repo.list_by_world(test_world.id)
        beats_after = plot_beat_repo.list_by_world(test_world.id)
        
        assert len(factions_before) == len(factions_after)
        assert len(beats_before) == len(beats_after)


class TestContentImportServiceImport:
    def test_import_writes_factions_and_plot_beats(self, db_session: Session, test_world: WorldModel, valid_pack_dir: Path):
        service = ContentImportService(db_session)
        faction_repo = FactionRepository(db_session)
        plot_beat_repo = PlotBeatRepository(db_session)
        
        report = service.import_pack(valid_pack_dir, dry_run=False)
        
        assert report.success is True
        assert report.dry_run is False
        assert report.factions_imported == 2
        assert report.plot_beats_imported == 2
        assert report.imported_count == 4
        
        factions = faction_repo.list_by_world(test_world.id)
        assert len(factions) == 2
        
        faction_a = faction_repo.get_by_logical_id(test_world.id, "faction_a")
        assert faction_a is not None
        assert faction_a.name == "Faction A"
        
        faction_b = faction_repo.get_by_logical_id(test_world.id, "faction_b")
        assert faction_b is not None
        assert faction_b.name == "Faction B"
        
        beats = plot_beat_repo.list_by_world(test_world.id)
        assert len(beats) == 2
        
        beat_1 = plot_beat_repo.get_by_logical_id(test_world.id, "beat_1")
        assert beat_1 is not None
        assert beat_1.title == "Test Beat 1"


class TestContentImportServiceIdempotency:
    def test_re_import_is_idempotent(self, db_session: Session, test_world: WorldModel, valid_pack_dir: Path):
        service = ContentImportService(db_session)
        faction_repo = FactionRepository(db_session)
        plot_beat_repo = PlotBeatRepository(db_session)
        
        report1 = service.import_pack(valid_pack_dir, dry_run=False)
        assert report1.success is True
        
        factions_1 = faction_repo.list_by_world(test_world.id)
        beats_1 = plot_beat_repo.list_by_world(test_world.id)
        
        report2 = service.import_pack(valid_pack_dir, dry_run=False)
        assert report2.success is True
        
        factions_2 = faction_repo.list_by_world(test_world.id)
        beats_2 = plot_beat_repo.list_by_world(test_world.id)
        
        assert len(factions_1) == len(factions_2) == 2
        assert len(beats_1) == len(beats_2) == 2


class TestContentImportServiceValidation:
    def test_invalid_pack_does_not_write_to_db(self, db_session: Session, test_world: WorldModel, invalid_pack_dir: Path):
        service = ContentImportService(db_session)
        faction_repo = FactionRepository(db_session)
        
        factions_before = faction_repo.list_by_world(test_world.id)
        
        report = service.import_pack(invalid_pack_dir, dry_run=False)
        
        assert report.success is False
        assert len(report.errors) > 0
        assert any("duplicate" in e.lower() for e in report.errors)
        
        factions_after = faction_repo.list_by_world(test_world.id)
        assert len(factions_before) == len(factions_after)
    
    def test_pack_with_bad_reference_reports_errors(self, db_session: Session, test_world: WorldModel, pack_with_bad_reference: Path):
        service = ContentImportService(db_session)
        
        report = service.import_pack(pack_with_bad_reference, dry_run=False)
        
        assert report.success is False
        assert len(report.errors) > 0
        assert any("unknown" in e.lower() or "invalid" in e.lower() or "reference" in e.lower() for e in report.errors)


class TestContentImportServiceMissingPack:
    def test_missing_pack_yaml_returns_error(self, db_session: Session, test_world: WorldModel):
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir)
            
            service = ContentImportService(db_session)
            report = service.import_pack(pack_dir, dry_run=False)
            
            assert report.success is False
            assert len(report.errors) > 0
            assert any("not found" in e.lower() or "pack.yaml" in e.lower() for e in report.errors)
    
    def test_nonexistent_directory_returns_error(self, db_session: Session, test_world: WorldModel):
        service = ContentImportService(db_session)
        report = service.import_pack(Path("/nonexistent/path"), dry_run=False)
        
        assert report.success is False
        assert len(report.errors) > 0
