import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml


def run_cli(pack_dir: Path, dry_run: bool = False, format_arg: str = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "llm_rpg.scripts.import_content_pack", str(pack_dir)]
    if dry_run:
        cmd.append("--dry-run")
    if format_arg:
        cmd.extend(["--format", format_arg])
    
    env = {
        "APP_ENV": "testing",
        "DATABASE_URL": "sqlite:///:memory:",
    }
    
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,
        env={**dict(subprocess.os.environ), **env},
    )


def create_valid_pack(tmp_dir: Path) -> Path:
    pack_dir = tmp_dir / "valid_pack"
    pack_dir.mkdir()
    
    pack_yaml = {
        "id": "valid_pack",
        "name": "Valid Pack",
        "version": "1.0.0",
        "description": "A valid pack",
        "author": "Test",
    }
    with open(pack_dir / "pack.yaml", "w") as f:
        yaml.dump(pack_yaml, f)
    
    factions_yaml = {
        "factions": [
            {
                "id": "faction_a",
                "name": "Faction A",
                "ideology": "test",
                "relationships": {"faction_b": "ally"},
            },
            {
                "id": "faction_b",
                "name": "Faction B",
                "ideology": "test",
                "relationships": {"faction_a": "ally"},
            },
        ]
    }
    with open(pack_dir / "factions.yaml", "w") as f:
        yaml.dump(factions_yaml, f)
    
    plot_beats_yaml = {
        "plot_beats": [
            {
                "id": "beat_1",
                "name": "Test Beat",
                "trigger_conditions": {"location": "test_loc"},
                "effects": [{"type": "set_flag", "flag": "test_flag"}],
            }
        ]
    }
    with open(pack_dir / "plot_beats.yaml", "w") as f:
        yaml.dump(plot_beats_yaml, f)
    
    return pack_dir


def create_invalid_pack(tmp_dir: Path) -> Path:
    pack_dir = tmp_dir / "invalid_pack"
    pack_dir.mkdir()
    
    pack_yaml = {
        "id": "invalid_pack",
        "name": "Invalid Pack",
        "version": "1.0.0",
    }
    with open(pack_dir / "pack.yaml", "w") as f:
        yaml.dump(pack_yaml, f)
    
    factions_yaml = {
        "factions": [
            {"id": "faction_a", "name": "Faction A"},
            {"id": "faction_a", "name": "Duplicate Faction"},
        ]
    }
    with open(pack_dir / "factions.yaml", "w") as f:
        yaml.dump(factions_yaml, f)
    
    return pack_dir


class TestImportContentPackCLI:
    def test_valid_pack_dry_run_returns_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            valid_pack = create_valid_pack(tmp_path)
            result = run_cli(valid_pack, dry_run=True)
            assert result.returncode == 0, f"stderr: {result.stderr}"
    
    def test_dry_run_flag_indicated_in_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            valid_pack = create_valid_pack(tmp_path)
            result = run_cli(valid_pack, dry_run=True)
            assert "DRY RUN" in result.stderr or "dry_run" in result.stdout.lower()
    
    def test_json_output_is_parseable_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            valid_pack = create_valid_pack(tmp_path)
            result = run_cli(valid_pack, dry_run=True, format_arg="json")
            
            assert result.returncode == 0, f"stderr: {result.stderr}"
            data = json.loads(result.stdout)
            assert data["success"] is True
            assert data["dry_run"] is True
            assert data["factions_imported"] == 2
            assert data["plot_beats_imported"] == 1
    
    def test_invalid_pack_exits_with_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            invalid_pack = create_invalid_pack(tmp_path)
            result = run_cli(invalid_pack, dry_run=True)
            assert result.returncode == 1, f"Expected exit 1. stderr: {result.stderr}"
    
    def test_invalid_pack_json_shows_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            invalid_pack = create_invalid_pack(tmp_path)
            result = run_cli(invalid_pack, dry_run=True, format_arg="json")
            
            assert result.returncode == 1
            data = json.loads(result.stdout)
            assert data["success"] is False
            assert len(data["errors"]) > 0
    
    def test_missing_pack_dir_returns_exit_1(self):
        result = run_cli(Path("/nonexistent/path"))
        assert result.returncode == 1
        assert "does not exist" in result.stderr
    
    def test_missing_pack_yaml_returns_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            empty_dir = tmp_path / "empty_pack"
            empty_dir.mkdir()
            result = run_cli(empty_dir, dry_run=True)
            assert result.returncode == 1
    
    def test_json_output_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            valid_pack = create_valid_pack(tmp_path)
            result = run_cli(valid_pack, dry_run=True, format_arg="json")
            data = json.loads(result.stdout)
            
            assert "success" in data
            assert "dry_run" in data
            assert "pack_id" in data
            assert "pack_name" in data
            assert "imported_count" in data
            assert "factions_imported" in data
            assert "plot_beats_imported" in data
            assert "errors" in data
            assert "warnings" in data
    
    def test_human_format_reports_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            valid_pack = create_valid_pack(tmp_path)
            result = run_cli(valid_pack, dry_run=True, format_arg="human")
            
            assert "Factions imported: 2" in result.stderr
            assert "Plot beats imported: 1" in result.stderr
