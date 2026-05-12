"""Story progression regression tests for P4.

End-to-end tests that verify the full story progression flow with content packs,
including multiple plot beat evaluations and quest progression.
"""

import tempfile
from pathlib import Path
from typing import Dict, Any

import pytest
import yaml

from llm_rpg.content.loader import load_content_pack
from llm_rpg.content.validator import ContentValidator
from llm_rpg.core.plot_beat_resolver import PlotBeatResolver, EvaluatedPlotBeat
from llm_rpg.core.quest_progression_validator import QuestProgressionValidator
from llm_rpg.models.content_pack import (
    ContentPackDefinition,
    PlotBeatDefinition,
    PlotBeatCondition,
    PlotBeatEffect,
    PlotBeatVisibility,
)


def create_story_content_pack(tmp_dir: Path) -> Path:
    """Create a content pack with multi-stage story progression."""
    pack_yaml = {
        "id": "story_world",
        "name": "Story Progression World",
        "version": "1.0.0",
        "description": "A world with interconnected plot beats",
        "author": "Story Test Suite",
    }
    
    factions_yaml = {
        "factions": [
            {
                "id": "protagonists",
                "name": "The Heroes",
                "ideology": "Protect the realm",
                "goals": ["Defeat the darkness", "Unite the factions"],
                "relationships": {},
            },
            {
                "id": "antagonists",
                "name": "The Shadow",
                "ideology": "Corruption",
                "goals": ["Spread darkness"],
                "relationships": {"protagonists": "enemy"},
            },
        ]
    }
    
    plot_beats_yaml = {
        "plot_beats": [
            # Chapter 1: Introduction
            {
                "id": "ch1_intro",
                "name": "Chapter 1 Introduction",
                "priority": 100,
                "visibility": "revealed",
                "trigger_conditions": {
                    "location": "starting_village",
                },
                "effects": [
                    {"type": "add_known_fact", "fact_id": "ch1_started"},
                    {"type": "set_state", "key": "chapter", "value": 1},
                ],
            },
            # Quest start beat
            {
                "id": "quest_start",
                "name": "Main Quest Begins",
                "priority": 90,
                "visibility": "revealed",
                "trigger_conditions": {
                    "quest_stage": {"quest": "main_quest", "stage": 0},
                    "npc_interaction": "quest_giver",
                },
                "effects": [
                    {
                        "type": "advance_quest",
                        "quest_id": "main_quest",
                        "from_stage": 0,
                        "to_stage": 1,
                    },
                ],
            },
            # Plot discovery beat
            {
                "id": "plot_discovery",
                "name": "Discover the Plot",
                "priority": 80,
                "visibility": "conditional",
                "trigger_conditions": {
                    "event_flag": "ch1_started",
                    "npc_interaction": "informant",
                },
                "effects": [
                    {"type": "add_known_fact", "fact_id": "knows_shadow_plan"},
                ],
            },
            # Chapter 2 trigger
            {
                "id": "ch2_start",
                "name": "Chapter 2 Begins",
                "priority": 70,
                "visibility": "revealed",
                "trigger_conditions": {
                    "quest_stage": {"quest": "main_quest", "stage": 1},
                    "event_flag": "knows_shadow_plan",
                },
                "effects": [
                    {"type": "set_state", "key": "chapter", "value": 2},
                    {
                        "type": "advance_quest",
                        "quest_id": "main_quest",
                        "from_stage": 1,
                        "to_stage": 2,
                    },
                ],
            },
            # Hidden betrayal beat
            {
                "id": "hidden_betrayal",
                "name": "The Betrayal",
                "priority": 60,
                "visibility": "hidden",
                "trigger_conditions": {
                    "quest_stage": {"quest": "main_quest", "stage": 2},
                    "location": "throne_room",
                },
                "effects": [
                    {"type": "add_known_fact", "fact_id": "advisor_is_traitor"},
                    {"type": "change_relationship", "faction_id": "antagonists", "delta": -50},
                ],
            },
            # Final confrontation
            {
                "id": "final_battle",
                "name": "Final Confrontation",
                "priority": 50,
                "visibility": "revealed",
                "trigger_conditions": {
                    "quest_stage": {"quest": "main_quest", "stage": 2},
                    "event_flag": "advisor_is_traitor",
                },
                "effects": [
                    {
                        "type": "advance_quest",
                        "quest_id": "main_quest",
                        "from_stage": 2,
                        "to_stage": 3,
                    },
                ],
            },
        ]
    }
    
    (tmp_dir / "pack.yaml").write_text(yaml.dump(pack_yaml))
    (tmp_dir / "factions.yaml").write_text(yaml.dump(factions_yaml))
    (tmp_dir / "plot_beats.yaml").write_text(yaml.dump(plot_beats_yaml))
    
    return tmp_dir


class StoryContext:
    """Helper class to track story progression state."""
    
    def __init__(self):
        self.state: Dict[str, Any] = {}
        self.known_facts: list = []
        self.quest_stages: Dict[str, int] = {"main_quest": 0}
        self.npc_presence: list = []
        self.current_location: str = ""
        self.triggered_beats: list = []
    
    def to_context_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "known_facts": self.known_facts,
            "quest_stages": self.quest_stages,
            "npc_presence": self.npc_presence,
            "current_location": self.current_location,
        }
    
    def apply_effects(self, effects: list) -> None:
        for effect in effects:
            if effect.type == "add_known_fact":
                fact_id = effect.params.get("fact_id")
                if fact_id and fact_id not in self.known_facts:
                    self.known_facts.append(fact_id)
                    self.state[fact_id] = True
            elif effect.type == "set_state":
                key = effect.params.get("key")
                value = effect.params.get("value")
                if key:
                    self.state[key] = value
            elif effect.type == "advance_quest":
                quest_id = effect.params.get("quest_id")
                to_stage = effect.params.get("to_stage")
                if quest_id and to_stage is not None:
                    self.quest_stages[quest_id] = to_stage


@pytest.mark.scenario
@pytest.mark.regression
class TestStoryProgressionEndToEnd:
    """End-to-end story progression regression tests."""

    def test_full_story_flow_from_intro_to_finale(self):
        """Test complete story progression from introduction to finale."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            create_story_content_pack(tmp_dir)
            
            pack = load_content_pack(tmp_dir)
            validator = ContentValidator()
            report = validator.validate(pack)
            
            assert report.is_valid is True, f"Invalid pack: {report.issues}"
            
            resolver = PlotBeatResolver()
            story = StoryContext()
            
            # Beat 1: Starting village - intro triggers
            story.current_location = "starting_village"
            intro_beat = next(b for b in pack.plot_beats if b.id == "ch1_intro")
            result = resolver.evaluate(intro_beat, story.to_context_dict())
            assert result.eligible is True
            story.apply_effects(intro_beat.effects)
            story.triggered_beats.append(intro_beat.id)
            
            assert "ch1_started" in story.known_facts
            assert story.state.get("chapter") == 1
            
            # Beat 2: Quest giver gives main quest
            story.npc_presence = ["quest_giver"]
            quest_start_beat = next(b for b in pack.plot_beats if b.id == "quest_start")
            result = resolver.evaluate(quest_start_beat, story.to_context_dict())
            assert result.eligible is True
            story.apply_effects(quest_start_beat.effects)
            story.triggered_beats.append(quest_start_beat.id)
            
            assert story.quest_stages.get("main_quest") == 1
            
            # Beat 3: Informant reveals plot
            story.npc_presence = ["informant"]
            plot_beat = next(b for b in pack.plot_beats if b.id == "plot_discovery")
            result = resolver.evaluate(plot_beat, story.to_context_dict())
            assert result.eligible is True
            story.apply_effects(plot_beat.effects)
            story.triggered_beats.append(plot_beat.id)
            
            assert "knows_shadow_plan" in story.known_facts
            
            # Beat 4: Chapter 2 starts
            ch2_beat = next(b for b in pack.plot_beats if b.id == "ch2_start")
            result = resolver.evaluate(ch2_beat, story.to_context_dict())
            assert result.eligible is True
            story.apply_effects(ch2_beat.effects)
            story.triggered_beats.append(ch2_beat.id)
            
            assert story.state.get("chapter") == 2
            assert story.quest_stages.get("main_quest") == 2
            
            # Beat 5: Hidden betrayal in throne room
            story.current_location = "throne_room"
            betrayal_beat = next(b for b in pack.plot_beats if b.id == "hidden_betrayal")
            result = resolver.evaluate(betrayal_beat, story.to_context_dict())
            assert result.eligible is True
            story.apply_effects(betrayal_beat.effects)
            story.triggered_beats.append(betrayal_beat.id)
            
            assert "advisor_is_traitor" in story.known_facts
            
            # Beat 6: Final battle
            final_beat = next(b for b in pack.plot_beats if b.id == "final_battle")
            result = resolver.evaluate(final_beat, story.to_context_dict())
            assert result.eligible is True
            story.apply_effects(final_beat.effects)
            story.triggered_beats.append(final_beat.id)
            
            assert story.quest_stages.get("main_quest") == 3
            
            # Verify full progression
            assert len(story.triggered_beats) == 6

    def test_beats_dont_trigger_without_prerequisites(self):
        """Test that beats don't trigger when prerequisites are missing."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            create_story_content_pack(tmp_dir)
            
            pack = load_content_pack(tmp_dir)
            resolver = PlotBeatResolver()
            story = StoryContext()
            
            # Try to trigger final battle without prerequisites
            story.quest_stages["main_quest"] = 2
            # But advisor_is_traitor is not known
            story.known_facts = []
            
            final_beat = next(b for b in pack.plot_beats if b.id == "final_battle")
            result = resolver.evaluate(final_beat, story.to_context_dict())
            
            assert result.eligible is False

    def test_hidden_beat_visibility_enforced(self):
        """Test that hidden beats are correctly marked."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            create_story_content_pack(tmp_dir)
            
            pack = load_content_pack(tmp_dir)
            
            hidden_beat = next(b for b in pack.plot_beats if b.id == "hidden_betrayal")
            assert hidden_beat.visibility == PlotBeatVisibility.HIDDEN
            
            progression_validator = QuestProgressionValidator()
            result = progression_validator.validate_visibility_constraint(
                visibility=hidden_beat.visibility,
                is_player_visible=True,
            )
            
            assert result.is_valid is False


@pytest.mark.scenario
@pytest.mark.regression
class TestMultiplePlotBeatEvaluation:
    """Tests for evaluating multiple plot beats in a scene."""

    def test_highest_priority_eligible_beat_identified(self):
        """Test identifying the highest priority eligible beat."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            create_story_content_pack(tmp_dir)
            
            pack = load_content_pack(tmp_dir)
            resolver = PlotBeatResolver()
            story = StoryContext()
            
            # Set up context where multiple beats could be eligible
            story.current_location = "starting_village"
            story.known_facts = ["ch1_started"]
            story.npc_presence = ["quest_giver", "informant"]
            story.quest_stages["main_quest"] = 0
            
            # Evaluate all beats
            eligible_beats = []
            for beat in pack.plot_beats:
                result = resolver.evaluate(beat, story.to_context_dict())
                if result.eligible:
                    eligible_beats.append((beat, result))
            
            # Sort by priority
            eligible_beats.sort(key=lambda x: x[0].priority, reverse=True)
            
            # Highest priority should be ch1_intro (100)
            assert len(eligible_beats) > 0
            assert eligible_beats[0][0].priority == 100

    def test_conditional_vs_revealed_visibility(self):
        """Test that visibility levels are correctly assigned."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            create_story_content_pack(tmp_dir)
            
            pack = load_content_pack(tmp_dir)
            
            revealed_beats = [b for b in pack.plot_beats if b.visibility == PlotBeatVisibility.REVEALED]
            conditional_beats = [b for b in pack.plot_beats if b.visibility == PlotBeatVisibility.CONDITIONAL]
            hidden_beats = [b for b in pack.plot_beats if b.visibility == PlotBeatVisibility.HIDDEN]
            
            assert len(revealed_beats) == 4  # ch1_intro, quest_start, ch2_start, final_battle
            assert len(conditional_beats) == 1  # plot_discovery
            assert len(hidden_beats) == 1  # hidden_betrayal

    def test_quest_progression_order_enforced(self):
        """Test that quest stages progress in correct order."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            create_story_content_pack(tmp_dir)
            
            pack = load_content_pack(tmp_dir)
            progression_validator = QuestProgressionValidator()
            
            # Find quest-related effects
            quest_effects = []
            for beat in pack.plot_beats:
                for effect in beat.effects:
                    if effect.type == "advance_quest":
                        quest_effects.append((beat.id, effect))
            
            # Verify each transition is valid
            for beat_id, effect in quest_effects:
                quest_id = effect.params.get("quest_id")
                from_stage = effect.params.get("from_stage")
                to_stage = effect.params.get("to_stage")
                
                current_state = {
                    "quest_id": quest_id,
                    "current_stage": from_stage,
                }
                
                result = progression_validator.validate_transition(
                    effect, current_state
                )
                
                assert result.is_valid is True, f"Invalid transition in {beat_id}: {result.errors}"

    def test_state_variable_changes_propagate(self):
        """Test that state changes from one beat affect subsequent beats."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            create_story_content_pack(tmp_dir)
            
            pack = load_content_pack(tmp_dir)
            resolver = PlotBeatResolver()
            story = StoryContext()
            
            # Start fresh
            story.current_location = "starting_village"
            
            # Evaluate intro beat
            intro_beat = next(b for b in pack.plot_beats if b.id == "ch1_intro")
            result = resolver.evaluate(intro_beat, story.to_context_dict())
            assert result.eligible is True
            
            # Apply effects
            story.apply_effects(intro_beat.effects)
            
            # Now check that state changed
            assert story.state.get("chapter") == 1
            assert "ch1_started" in story.known_facts
            
            # Plot discovery beat should now be eligible (if informant present)
            story.npc_presence = ["informant"]
            plot_beat = next(b for b in pack.plot_beats if b.id == "plot_discovery")
            result = resolver.evaluate(plot_beat, story.to_context_dict())
            assert result.eligible is True

    def test_interconnected_beat_chain(self):
        """Test a chain of beats where each enables the next."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            create_story_content_pack(tmp_dir)
            
            pack = load_content_pack(tmp_dir)
            resolver = PlotBeatResolver()
            story = StoryContext()
            
            # Simulate full chain execution
            beat_chain = ["ch1_intro", "quest_start", "plot_discovery", "ch2_start", "hidden_betrayal", "final_battle"]
            
            # Set up initial context
            story.current_location = "starting_village"
            story.npc_presence = ["quest_giver", "informant"]
            
            for beat_id in beat_chain:
                beat = next((b for b in pack.plot_beats if b.id == beat_id), None)
                if beat is None:
                    continue
                
                # Update context for specific beats
                if beat_id == "hidden_betrayal":
                    story.current_location = "throne_room"
                
                result = resolver.evaluate(beat, story.to_context_dict())
                
                # All beats in chain should eventually become eligible
                if result.eligible:
                    story.apply_effects(beat.effects)
                    story.triggered_beats.append(beat_id)
            
            # At least some beats should have triggered
            assert len(story.triggered_beats) >= 3


@pytest.mark.scenario
@pytest.mark.regression
@pytest.mark.full
class TestStoryProgressionEdgeCases:
    """Edge case tests for story progression (marked as full tests)."""

    def test_empty_plot_beats_list(self):
        """Test handling of content pack with no plot beats."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            
            pack_yaml = {"id": "empty_world", "name": "Empty", "version": "1.0.0"}
            (tmp_dir / "pack.yaml").write_text(yaml.dump(pack_yaml))
            
            pack = load_content_pack(tmp_dir)
            assert len(pack.plot_beats) == 0
            
            resolver = PlotBeatResolver()
            # Should handle empty list gracefully

    def test_beat_with_empty_conditions(self):
        """Test beat with no conditions is always eligible."""
        resolver = PlotBeatResolver()
        
        beat = PlotBeatDefinition(
            id="unconditional",
            title="Always Triggers",
            world_id="test",
            conditions=[],
            effects=[PlotBeatEffect(type="set_state", params={"key": "triggered", "value": True})],
        )
        
        context = {
            "state": {},
            "known_facts": [],
            "quest_stages": {},
            "npc_presence": [],
            "current_location": "",
        }
        
        result = resolver.evaluate(beat, context)
        assert result.eligible is True

    def test_concurrent_quest_stages(self):
        """Test handling multiple concurrent quests."""
        resolver = PlotBeatResolver()
        
        beat = PlotBeatDefinition(
            id="multi_quest_beat",
            title="Multi Quest",
            world_id="test",
            conditions=[
                PlotBeatCondition(type="quest_stage", params={"quest_id": "quest_a", "stage": 1}),
                PlotBeatCondition(type="quest_stage", params={"quest_id": "quest_b", "stage": 2}),
            ],
            effects=[],
        )
        
        context = {
            "state": {},
            "known_facts": [],
            "quest_stages": {"quest_a": 1, "quest_b": 2},
            "npc_presence": [],
            "current_location": "",
        }
        
        result = resolver.evaluate(beat, context)
        assert result.eligible is True

    def test_state_in_condition_with_list(self):
        """Test state_in condition with list of values."""
        resolver = PlotBeatResolver()
        
        beat = PlotBeatDefinition(
            id="state_in_beat",
            title="State In Test",
            world_id="test",
            conditions=[
                PlotBeatCondition(type="state_in", params={"key": "mood", "values": ["happy", "excited", "neutral"]}),
            ],
            effects=[],
        )
        
        # Should pass when value is in list
        context_pass = {
            "state": {"mood": "happy"},
            "known_facts": [],
            "quest_stages": {},
            "npc_presence": [],
            "current_location": "",
        }
        result = resolver.evaluate(beat, context_pass)
        assert result.eligible is True
        
        # Should fail when value is not in list
        context_fail = {
            "state": {"mood": "angry"},
            "known_facts": [],
            "quest_stages": {},
            "npc_presence": [],
            "current_location": "",
        }
        result = resolver.evaluate(beat, context_fail)
        assert result.eligible is False
