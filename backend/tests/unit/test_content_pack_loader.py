"""Tests for content pack loader."""

import tempfile
from pathlib import Path

import pytest

from llm_rpg.content.loader import (
    ContentPackLoadError,
    load_content_pack,
    load_factions_from_yaml,
    load_plot_beats_from_yaml,
)


class TestLoadContentPack:
    """Tests for load_content_pack function."""

    def test_load_valid_content_pack(self):
        """Test loading a valid content pack."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir)
            
            (pack_dir / "pack.yaml").write_text("""
id: test_pack
name: Test Pack
version: 1.0.0
description: A test content pack
author: test
genre: fantasy
theme: adventure
tags:
  - test
created_at: "2026-01-01"
""")
            
            (pack_dir / "factions.yaml").write_text("""
factions:
  - id: test_faction
    name: Test Faction
    ideology: Test ideology
    goals:
      - Test goal
    relationships:
      other_faction: neutral
""")
            
            (pack_dir / "plot_beats.yaml").write_text("""
plot_beats:
  - id: test_beat
    name: Test Beat
    event_type: discovery
    trigger_conditions:
      location: test_location
    effects:
      - type: set_flag
        key: test_flag
        value: true
""")
            
            pack = load_content_pack(pack_dir)
            
            assert pack.manifest.id == "test_pack"
            assert pack.manifest.name == "Test Pack"
            assert pack.manifest.version == "1.0.0"
            assert len(pack.factions) == 1
            assert len(pack.plot_beats) == 1
            assert pack.factions[0].id == "test_faction"
            assert pack.plot_beats[0].id == "test_beat"

    def test_load_missing_pack_yaml(self):
        """Test error when pack.yaml is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir)
            
            with pytest.raises(ContentPackLoadError) as exc_info:
                load_content_pack(pack_dir)
            
            assert "pack.yaml not found" in str(exc_info.value)

    def test_load_invalid_yaml(self):
        """Test error when YAML is invalid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir)
            
            (pack_dir / "pack.yaml").write_text("""
id: test_pack
name: [invalid yaml
""")
            
            with pytest.raises(ContentPackLoadError) as exc_info:
                load_content_pack(pack_dir)
            
            assert "Invalid YAML" in str(exc_info.value)

    def test_load_empty_pack(self):
        """Test loading a pack with only pack.yaml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir)
            
            (pack_dir / "pack.yaml").write_text("""
id: empty_pack
name: Empty Pack
version: 0.0.1
""")
            
            pack = load_content_pack(pack_dir)
            
            assert pack.manifest.id == "empty_pack"
            assert len(pack.factions) == 0
            assert len(pack.plot_beats) == 0


class TestLoadFactionsFromYaml:
    """Tests for load_factions_from_yaml function."""

    def test_load_factions_with_simple_goals(self):
        """Test loading factions with simple string goals."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factions_path = Path(tmpdir) / "factions.yaml"
            factions_path.write_text("""
factions:
  - id: faction_a
    name: Faction A
    ideology: Test ideology
    goals:
      - First goal
      - Second goal
    relationships:
      faction_b: ally
""")
            
            factions = load_factions_from_yaml(factions_path, "test_world")
            
            assert len(factions) == 1
            assert factions[0].id == "faction_a"
            assert factions[0].name == "Faction A"
            assert factions[0].world_id == "test_world"
            assert len(factions[0].goals) == 2
            assert factions[0].goals[0].description == "First goal"
            assert len(factions[0].relationships) == 1
            assert factions[0].relationships[0].target_faction_id == "faction_b"
            assert factions[0].relationships[0].relationship_type == "ally"

    def test_load_factions_with_structured_goals(self):
        """Test loading factions with structured goal objects."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factions_path = Path(tmpdir) / "factions.yaml"
            factions_path.write_text("""
factions:
  - id: faction_a
    name: Faction A
    goals:
      - goal_id: goal_1
        description: Structured goal
        priority: 50
        status: active
""")
            
            factions = load_factions_from_yaml(factions_path, "test_world")
            
            assert len(factions) == 1
            assert factions[0].goals[0].goal_id == "goal_1"
            assert factions[0].goals[0].description == "Structured goal"
            assert factions[0].goals[0].priority == 50

    def test_load_factions_missing_file(self):
        """Test error when factions file is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factions_path = Path(tmpdir) / "missing.yaml"
            
            with pytest.raises(ContentPackLoadError) as exc_info:
                load_factions_from_yaml(factions_path, "test_world")
            
            assert "Factions file not found" in str(exc_info.value)

    def test_load_empty_factions(self):
        """Test loading empty factions file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factions_path = Path(tmpdir) / "factions.yaml"
            factions_path.write_text("factions: []")
            
            factions = load_factions_from_yaml(factions_path, "test_world")
            
            assert len(factions) == 0


class TestLoadPlotBeatsFromYaml:
    """Tests for load_plot_beats_from_yaml function."""

    def test_load_plot_beats_with_conditions(self):
        """Test loading plot beats with trigger conditions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            beats_path = Path(tmpdir) / "plot_beats.yaml"
            beats_path.write_text("""
plot_beats:
  - id: beat_1
    name: Test Beat
    event_type: discovery
    trigger_conditions:
      location: test_location
      event_flag: test_flag
      turn_minimum: 10
    effects:
      - type: set_flag
        key: result_flag
        value: true
""")
            
            beats = load_plot_beats_from_yaml(beats_path, "test_world")
            
            assert len(beats) == 1
            assert beats[0].id == "beat_1"
            assert beats[0].title == "Test Beat"
            assert beats[0].world_id == "test_world"
            assert len(beats[0].conditions) >= 1
            assert len(beats[0].effects) == 1

    def test_load_plot_beats_with_quest_stage(self):
        """Test loading plot beats with quest stage condition."""
        with tempfile.TemporaryDirectory() as tmpdir:
            beats_path = Path(tmpdir) / "plot_beats.yaml"
            beats_path.write_text("""
plot_beats:
  - id: beat_1
    name: Quest Beat
    trigger_conditions:
      quest_stage:
        quest: main_quest
        stage: 3
    effects: []
""")
            
            beats = load_plot_beats_from_yaml(beats_path, "test_world")
            
            assert len(beats) == 1
            quest_conditions = [c for c in beats[0].conditions if c.type == "quest_stage"]
            assert len(quest_conditions) == 1
            assert quest_conditions[0].params["quest_id"] == "main_quest"
            assert quest_conditions[0].params["stage"] == 3

    def test_load_plot_beats_missing_file(self):
        """Test error when plot beats file is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            beats_path = Path(tmpdir) / "missing.yaml"
            
            with pytest.raises(ContentPackLoadError) as exc_info:
                load_plot_beats_from_yaml(beats_path, "test_world")
            
            assert "Plot beats file not found" in str(exc_info.value)

    def test_load_plot_beats_with_npc_interaction(self):
        """Test loading plot beats with NPC interaction condition."""
        with tempfile.TemporaryDirectory() as tmpdir:
            beats_path = Path(tmpdir) / "plot_beats.yaml"
            beats_path.write_text("""
plot_beats:
  - id: beat_1
    name: NPC Beat
    trigger_conditions:
      npc_interaction: test_npc
    effects: []
""")
            
            beats = load_plot_beats_from_yaml(beats_path, "test_world")
            
            assert len(beats) == 1
            npc_conditions = [c for c in beats[0].conditions if c.type == "npc_present"]
            assert len(npc_conditions) == 1
            assert npc_conditions[0].params["npc_id"] == "test_npc"
