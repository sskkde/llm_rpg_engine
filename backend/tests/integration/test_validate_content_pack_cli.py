"""Integration tests for validate_content_pack CLI script."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml


VALID_PACK_DIR = Path(__file__).resolve().parent.parent.parent.parent / "content_packs" / "qinglan_xianxia"


def run_cli(pack_dir: Path, format_arg: str = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "llm_rpg.scripts.validate_content_pack", str(pack_dir)]
    if format_arg:
        cmd.extend(["--format", format_arg])
    
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,
    )


def create_bad_pack(tmp_dir: Path) -> Path:
    pack_dir = tmp_dir / "bad_pack"
    pack_dir.mkdir()
    
    pack_yaml = {
        "id": "bad_pack",
        "name": "Bad Pack",
        "version": "1.0.0",
        "description": "A pack with errors",
        "author": "Test",
    }
    with open(pack_dir / "pack.yaml", "w") as f:
        yaml.dump(pack_yaml, f)
    
    factions_yaml = {
        "factions": [
            {"id": "faction_a", "name": "Faction A", "ideology": "test"},
            {"id": "faction_a", "name": "Faction A Duplicate", "ideology": "test"},
        ]
    }
    with open(pack_dir / "factions.yaml", "w") as f:
        yaml.dump(factions_yaml, f)
    
    plot_beats_yaml = {
        "plot_beats": [
            {
                "id": "beat_1",
                "name": "Test Beat",
                "trigger_conditions": {"location": "nowhere"},
                "effects": [{"type": "invalid_effect_type"}],
            }
        ]
    }
    with open(pack_dir / "plot_beats.yaml", "w") as f:
        yaml.dump(plot_beats_yaml, f)
    
    return pack_dir


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


class TestValidateContentPackCLI:
    def test_valid_content_pack_returns_exit_0(self):
        """Valid content pack should return exit code 0."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            valid_pack = create_valid_pack(tmp_path)
            result = run_cli(valid_pack)
            assert result.returncode == 0, f"stderr: {result.stderr}"
    
    def test_valid_pack_human_output_to_stderr(self):
        """Human format output should go to stderr."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            valid_pack = create_valid_pack(tmp_path)
            result = run_cli(valid_pack, format_arg="human")
            assert "VALID" in result.stderr or "valid" in result.stderr.lower()
    
    def test_json_output_is_parseable(self):
        """JSON output should be valid JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            valid_pack = create_valid_pack(tmp_path)
            result = run_cli(valid_pack, format_arg="json")
            assert result.returncode == 0, f"stderr: {result.stderr}"
            
            data = json.loads(result.stdout)
            assert "is_valid" in data
            assert "issues" in data
            assert isinstance(data["issues"], list)
    
    def test_json_format_flag_works(self):
        """--format json should produce JSON output on stdout."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            valid_pack = create_valid_pack(tmp_path)
            result = run_cli(valid_pack, format_arg="json")
            
            assert result.returncode == 0
            assert result.stdout.strip().startswith("{")
            
            data = json.loads(result.stdout)
            assert data["is_valid"] is True
    
    def test_bad_pack_returns_exit_1(self):
        """Content pack with errors should return exit code 1."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_pack = create_bad_pack(tmp_path)
            result = run_cli(bad_pack)
            assert result.returncode == 1, f"Expected exit 1 for bad pack. stderr: {result.stderr}"
    
    def test_bad_pack_json_has_errors(self):
        """Bad pack JSON output should indicate errors."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_pack = create_bad_pack(tmp_path)
            result = run_cli(bad_pack, format_arg="json")
            
            assert result.returncode == 1
            data = json.loads(result.stdout)
            assert data["is_valid"] is False
            assert data["has_errors"] is True
            assert len(data["issues"]) > 0
    
    def test_missing_pack_dir_returns_exit_1(self):
        """Missing pack directory should return exit code 1."""
        result = run_cli(Path("/nonexistent/path"))
        assert result.returncode == 1
        assert "does not exist" in result.stderr
    
    def test_json_output_structure(self):
        """JSON output should have expected structure."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            valid_pack = create_valid_pack(tmp_path)
            result = run_cli(valid_pack, format_arg="json")
            data = json.loads(result.stdout)
            
            assert "is_valid" in data
            assert "has_errors" in data
            assert "has_warnings" in data
            assert "issue_count" in data
            assert "issues" in data
            
            if data["issues"]:
                issue = data["issues"][0]
                assert "severity" in issue
                assert "message" in issue
                assert "path" in issue
                assert "code" in issue
    
    def test_valid_pack_json_no_errors(self):
        """Valid pack JSON should have no errors."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            valid_pack = create_valid_pack(tmp_path)
            result = run_cli(valid_pack, format_arg="json")
            data = json.loads(result.stdout)
            
            assert data["is_valid"] is True
            assert data["has_errors"] is False
    
    def test_qinglan_xianxia_pack_loads(self):
        """Qinglan xianxia pack should load successfully (may have validation errors)."""
        result = run_cli(VALID_PACK_DIR, format_arg="json")
        assert result.stdout.strip().startswith("{")
        data = json.loads(result.stdout)
        assert "is_valid" in data
        assert "issues" in data
