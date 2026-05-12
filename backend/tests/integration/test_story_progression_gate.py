"""Integration tests for Story Progression Gate.

End-to-end tests that verify:
- Content pack loading
- Content validation
- Plot beat evaluation
- Quest progression validation
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from llm_rpg.content.loader import load_content_pack
from llm_rpg.content.validator import ContentValidator
from llm_rpg.core.plot_beat_resolver import PlotBeatResolver
from llm_rpg.core.quest_progression_validator import QuestProgressionValidator
from llm_rpg.models.content_pack import (
    PlotBeatCondition,
    PlotBeatDefinition,
    PlotBeatEffect,
    PlotBeatVisibility,
)


def create_test_content_pack(tmp_dir: Path) -> Path:
    """Create a test content pack in a temporary directory."""
    pack_yaml = {
        "id": "test_world",
        "name": "Test World",
        "version": "1.0.0",
        "description": "A test world for integration testing",
        "author": "Test Suite",
    }
    
    factions_yaml = {
        "factions": [
            {
                "id": "guild_mages",
                "name": "Mages Guild",
                "ideology": "Pursuit of magical knowledge",
                "goals": [
                    "Recruit talented apprentices",
                    {"goal_id": "research", "description": "Conduct arcane research", "priority": 80},
                ],
                "relationships": {
                    "guild_warriors": "rival",
                },
            },
            {
                "id": "guild_warriors",
                "name": "Warriors Guild",
                "ideology": "Strength and honor",
                "goals": ["Train elite soldiers"],
                "relationships": {
                    "guild_mages": "rival",
                },
            },
        ]
    }
    
    plot_beats_yaml = {
        "plot_beats": [
            {
                "id": "intro_beat",
                "name": "Introduction",
                "priority": 100,
                "visibility": "revealed",
                "trigger_conditions": {
                    "location": "loc_tavern",
                },
                "effects": [
                    {"type": "add_known_fact", "fact_id": "met_barkeep"},
                ],
            },
            {
                "id": "quest_beat",
                "name": "Quest Available",
                "priority": 50,
                "visibility": "conditional",
                "trigger_conditions": {
                    "quest_stage": {"quest": "main_quest", "stage": 1},
                    "npc_interaction": "npc_elder",
                },
                "effects": [
                    {
                        "type": "advance_quest",
                        "quest_id": "main_quest",
                        "from_stage": 1,
                        "to_stage": 2,
                    },
                ],
            },
            {
                "id": "secret_beat",
                "name": "Secret Discovery",
                "priority": 30,
                "visibility": "hidden",
                "trigger_conditions": {
                    "location": "loc_secret_passage",
                    "event_flag": "found_key",
                },
                "effects": [
                    {"type": "add_known_fact", "fact_id": "treasure_location"},
                ],
            },
        ]
    }
    
    (tmp_dir / "pack.yaml").write_text(yaml.dump(pack_yaml))
    (tmp_dir / "factions.yaml").write_text(yaml.dump(factions_yaml))
    (tmp_dir / "plot_beats.yaml").write_text(yaml.dump(plot_beats_yaml))
    
    return tmp_dir


class TestStoryProgressionGateIntegration:
    """End-to-end integration tests for story progression."""

    def test_full_workflow(self):
        """Test complete workflow: load -> validate -> evaluate -> check progression."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            pack_dir = create_test_content_pack(tmp_dir)
            
            # Step 1: Load content pack
            pack = load_content_pack(pack_dir)
            
            assert pack.manifest.id == "test_world"
            assert len(pack.factions) == 2
            assert len(pack.plot_beats) == 3
            
            # Step 2: Validate content pack
            validator = ContentValidator()
            report = validator.validate(pack)
            
            assert report.is_valid is True
            assert len(report.issues) == 0 or all(
                i.severity != "error" for i in report.issues
            )
            
            # Step 3: Evaluate plot beats
            resolver = PlotBeatResolver()
            
            # Test intro beat - should be eligible at tavern
            intro_beat = next(b for b in pack.plot_beats if b.id == "intro_beat")
            context_at_tavern = {
                "state": {},
                "known_facts": [],
                "quest_stages": {},
                "npc_presence": [],
                "current_location": "loc_tavern",
            }
            
            result = resolver.evaluate(intro_beat, context_at_tavern)
            assert result.eligible is True
            
            # Test quest beat - should be eligible when quest is at stage 1 and elder present
            quest_beat = next(b for b in pack.plot_beats if b.id == "quest_beat")
            context_ready_for_quest = {
                "state": {},
                "known_facts": [],
                "quest_stages": {"main_quest": 1},
                "npc_presence": ["npc_elder"],
                "current_location": "loc_village",
            }
            
            result = resolver.evaluate(quest_beat, context_ready_for_quest)
            assert result.eligible is True
            
            # Step 4: Check quest progression
            progression_validator = QuestProgressionValidator()
            
            # Get the advance_quest effect
            advance_effect = quest_beat.effects[0]
            current_quest_state = {
                "quest_id": "main_quest",
                "current_stage": 1,
            }
            quest_definition = {"stages": [1, 2, 3, 4]}
            
            validation = progression_validator.validate_transition(
                advance_effect, current_quest_state, quest_definition
            )
            assert validation.is_valid is True

    def test_evaluate_beat_with_failed_conditions(self):
        """Test that beats with unmet conditions are not eligible."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            pack_dir = create_test_content_pack(tmp_dir)
            
            pack = load_content_pack(pack_dir)
            resolver = PlotBeatResolver()
            
            # Test quest beat - should NOT be eligible when quest is at different stage
            quest_beat = next(b for b in pack.plot_beats if b.id == "quest_beat")
            context_wrong_stage = {
                "state": {},
                "known_facts": [],
                "quest_stages": {"main_quest": 2},  # Wrong stage
                "npc_presence": ["npc_elder"],
                "current_location": "loc_village",
            }
            
            result = resolver.evaluate(quest_beat, context_wrong_stage)
            assert result.eligible is False
            assert len(result.condition_evaluations) == 2  # quest_stage + npc_present
            assert any(not e.passed for e in result.condition_evaluations)

    def test_evaluate_beat_at_wrong_location(self):
        """Test that beats with wrong location condition fail."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            pack_dir = create_test_content_pack(tmp_dir)
            
            pack = load_content_pack(pack_dir)
            resolver = PlotBeatResolver()
            
            # Test intro beat - should NOT be eligible at wrong location
            intro_beat = next(b for b in pack.plot_beats if b.id == "intro_beat")
            context_wrong_location = {
                "state": {},
                "known_facts": [],
                "quest_stages": {},
                "npc_presence": [],
                "current_location": "loc_forest",  # Not tavern
            }
            
            result = resolver.evaluate(intro_beat, context_wrong_location)
            assert result.eligible is False

    def test_hidden_beat_visibility_constraint(self):
        """Test that hidden beats cannot be player-visible."""
        progression_validator = QuestProgressionValidator()
        
        result = progression_validator.validate_visibility_constraint(
            visibility=PlotBeatVisibility.HIDDEN,
            is_player_visible=True,
        )
        
        assert result.is_valid is False
        assert "not be player-visible" in result.errors[0].lower()

    def test_illegal_quest_progression(self):
        """Test that illegal quest progression is rejected."""
        progression_validator = QuestProgressionValidator()
        
        effect = PlotBeatEffect(
            type="advance_quest",
            params={
                "quest_id": "main_quest",
                "from_stage": 2,
                "to_stage": 3,
            },
        )
        
        # Current state is at stage 1, not 2
        current_state = {
            "quest_id": "main_quest",
            "current_stage": 1,
        }
        
        result = progression_validator.validate_transition(effect, current_state)
        assert result.is_valid is False

    def test_unknown_effect_type_rejected(self):
        """Test that unknown effect types are rejected."""
        progression_validator = QuestProgressionValidator()
        
        effect = PlotBeatEffect(
            type="custom_effect",
            params={"custom_param": "value"},
        )
        
        current_state = {"quest_id": "test", "current_stage": 1}
        result = progression_validator.validate_transition(effect, current_state)
        
        assert result.is_valid is False
        assert "Unknown effect type" in result.errors[0]

    def test_faction_relationship_validation(self):
        """Test that faction references are validated."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            
            # Create pack with broken faction reference
            pack_yaml = {
                "id": "test_world",
                "name": "Test World",
                "version": "1.0.0",
            }
            
            factions_yaml = {
                "factions": [
                    {
                        "id": "guild_mages",
                        "name": "Mages Guild",
                        "relationships": {
                            "unknown_faction": "enemy",  # Invalid reference
                        },
                    },
                ]
            }
            
            (tmp_dir / "pack.yaml").write_text(yaml.dump(pack_yaml))
            (tmp_dir / "factions.yaml").write_text(yaml.dump(factions_yaml))
            
            pack = load_content_pack(tmp_dir)
            validator = ContentValidator()
            report = validator.validate(pack)
            
            # Should have error about unknown faction reference
            assert report.is_valid is False
            assert any("unknown faction" in i.message.lower() for i in report.issues)

    def test_duplicate_id_validation(self):
        """Test that duplicate IDs are detected."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            
            pack_yaml = {
                "id": "test_world",
                "name": "Test World",
                "version": "1.0.0",
            }
            
            factions_yaml = {
                "factions": [
                    {"id": "duplicate_id", "name": "First Faction"},
                    {"id": "duplicate_id", "name": "Second Faction"},
                ]
            }
            
            (tmp_dir / "pack.yaml").write_text(yaml.dump(pack_yaml))
            (tmp_dir / "factions.yaml").write_text(yaml.dump(factions_yaml))
            
            pack = load_content_pack(tmp_dir)
            validator = ContentValidator()
            report = validator.validate(pack)
            
            assert report.is_valid is False
            assert any("duplicate" in i.message.lower() for i in report.issues)

    def test_multiple_conditions_all_pass(self):
        """Test beat evaluation when all conditions pass."""
        resolver = PlotBeatResolver()
        
        beat = PlotBeatDefinition(
            id="multi_condition_beat",
            title="Multi-Condition Test",
            world_id="test",
            conditions=[
                PlotBeatCondition(type="fact_known", params={"fact_id": "secret"}),
                PlotBeatCondition(type="location_is", params={"location_id": "loc_tavern"}),
                PlotBeatCondition(type="npc_present", params={"npc_id": "npc_elder"}),
            ],
            effects=[],
        )
        
        context = {
            "known_facts": ["secret"],
            "current_location": "loc_tavern",
            "npc_presence": ["npc_elder"],
            "state": {},
            "quest_stages": {},
        }
        
        result = resolver.evaluate(beat, context)
        assert result.eligible is True
        assert "3 conditions passed" in result.reasons[0]

    def test_quest_stage_transition_to_nonexistent_stage(self):
        """Test that transition to non-existent stage is rejected."""
        progression_validator = QuestProgressionValidator()
        
        effect = PlotBeatEffect(
            type="advance_quest",
            params={
                "quest_id": "main_quest",
                "from_stage": 1,
                "to_stage": 99,  # Non-existent
            },
        )
        
        current_state = {"quest_id": "main_quest", "current_stage": 1}
        quest_def = {"stages": [1, 2, 3]}  # No stage 99
        
        result = progression_validator.validate_transition(
            effect, current_state, quest_def
        )
        
        assert result.is_valid is False
        assert any("does not exist" in e.lower() for e in result.errors)
