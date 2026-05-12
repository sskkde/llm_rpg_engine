"""Tests for content pack validator."""

import pytest

from llm_rpg.content.validator import ContentValidator
from llm_rpg.models.content_pack import (
    ContentPackDefinition,
    ContentPackManifest,
    FactionDefinition,
    FactionGoalDefinition,
    FactionRelationshipDefinition,
    PlotBeatCondition,
    PlotBeatDefinition,
    PlotBeatEffect,
    PlotBeatVisibility,
)


def make_faction(
    faction_id: str,
    name: str = "Test Faction",
    world_id: str = "test_world",
    goals: list = None,
    relationships: list = None,
) -> FactionDefinition:
    return FactionDefinition(
        id=faction_id,
        name=name,
        world_id=world_id,
        goals=goals or [],
        relationships=relationships or [],
    )


def make_plot_beat(
    beat_id: str,
    title: str = "Test Beat",
    world_id: str = "test_world",
    conditions: list = None,
    effects: list = None,
) -> PlotBeatDefinition:
    return PlotBeatDefinition(
        id=beat_id,
        title=title,
        world_id=world_id,
        conditions=conditions or [],
        effects=effects or [],
    )


def make_pack(
    factions: list = None,
    plot_beats: list = None,
) -> ContentPackDefinition:
    return ContentPackDefinition(
        manifest=ContentPackManifest(
            id="test_pack",
            name="Test Pack",
            version="1.0.0",
        ),
        factions=factions or [],
        plot_beats=plot_beats or [],
    )


class TestValidateIdUniqueness:
    """Tests for validate_id_uniqueness method."""

    def test_valid_pack_passes(self):
        validator = ContentValidator()
        factions = [
            make_faction("faction_a"),
            make_faction("faction_b"),
        ]
        plot_beats = [
            make_plot_beat("beat_a"),
            make_plot_beat("beat_b"),
        ]
        
        issues = validator.validate_id_uniqueness(factions, plot_beats)
        
        assert len(issues) == 0

    def test_duplicate_faction_ids_return_error(self):
        validator = ContentValidator()
        factions = [
            make_faction("duplicate_id"),
            make_faction("duplicate_id"),
        ]
        plot_beats = []
        
        issues = validator.validate_id_uniqueness(factions, plot_beats)
        
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].code == "DUPLICATE_FACTION_ID"
        assert "duplicate_id" in issues[0].message

    def test_duplicate_plot_beat_ids_return_error(self):
        validator = ContentValidator()
        factions = []
        plot_beats = [
            make_plot_beat("duplicate_beat"),
            make_plot_beat("duplicate_beat"),
        ]
        
        issues = validator.validate_id_uniqueness(factions, plot_beats)
        
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].code == "DUPLICATE_PLOT_BEAT_ID"
        assert "duplicate_beat" in issues[0].message


class TestValidateReferenceIntegrity:
    """Tests for validate_reference_integrity method."""

    def test_valid_references_pass(self):
        validator = ContentValidator()
        factions = [
            make_faction("faction_a", relationships=[
                FactionRelationshipDefinition(
                    target_faction_id="faction_b",
                    relationship_type="ally",
                    score=50,
                )
            ]),
            make_faction("faction_b"),
        ]
        plot_beats = []
        
        issues = validator.validate_reference_integrity(factions, plot_beats)
        
        assert len(issues) == 0

    def test_bad_faction_reference_returns_error(self):
        validator = ContentValidator()
        factions = [
            make_faction("faction_a", relationships=[
                FactionRelationshipDefinition(
                    target_faction_id="nonexistent_faction",
                    relationship_type="ally",
                    score=50,
                )
            ]),
        ]
        plot_beats = []
        
        issues = validator.validate_reference_integrity(factions, plot_beats)
        
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].code == "INVALID_FACTION_REFERENCE"
        assert "nonexistent_faction" in issues[0].message

    def test_bad_npc_reference_returns_error(self):
        validator = ContentValidator()
        factions = []
        plot_beats = [
            make_plot_beat("beat_a", conditions=[
                PlotBeatCondition(type="npc_present", params={"npc_id": "nonexistent_npc"}),
            ]),
        ]
        npcs = [type("NPC", (), {"id": "existing_npc"})]
        
        issues = validator.validate_reference_integrity(
            factions, plot_beats, npcs=npcs
        )
        
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].code == "INVALID_NPC_REFERENCE"

    def test_bad_location_reference_returns_error(self):
        validator = ContentValidator()
        factions = []
        plot_beats = [
            make_plot_beat("beat_a", conditions=[
                PlotBeatCondition(type="location_is", params={"location_id": "nonexistent_location"}),
            ]),
        ]
        locations = [type("Location", (), {"id": "existing_location"})]
        
        issues = validator.validate_reference_integrity(
            factions, plot_beats, locations=locations
        )
        
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].code == "INVALID_LOCATION_REFERENCE"


class TestValidateConditionWhitelist:
    """Tests for validate_condition_whitelist method."""

    def test_valid_conditions_pass(self):
        validator = ContentValidator()
        plot_beats = [
            make_plot_beat("beat_a", conditions=[
                PlotBeatCondition(type="fact_known", params={"fact_id": "test"}),
                PlotBeatCondition(type="state_equals", params={"key": "test", "value": True}),
                PlotBeatCondition(type="quest_stage", params={"quest_id": "q1", "stage": 1}),
            ]),
        ]
        
        issues = validator.validate_condition_whitelist(plot_beats)
        
        assert len(issues) == 0

    def test_unknown_condition_type_returns_error(self):
        validator = ContentValidator()
        plot_beats = [
            make_plot_beat("beat_a", conditions=[
                PlotBeatCondition(type="unknown_condition", params={}),
            ]),
        ]
        
        issues = validator.validate_condition_whitelist(plot_beats)
        
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].code == "UNKNOWN_CONDITION_TYPE"
        assert "unknown_condition" in issues[0].message

    def test_multiple_unknown_conditions_return_multiple_errors(self):
        validator = ContentValidator()
        plot_beats = [
            make_plot_beat("beat_a", conditions=[
                PlotBeatCondition(type="unknown_1", params={}),
                PlotBeatCondition(type="unknown_2", params={}),
            ]),
        ]
        
        issues = validator.validate_condition_whitelist(plot_beats)
        
        assert len(issues) == 2


class TestValidateEffectWhitelist:
    """Tests for validate_effect_whitelist method."""

    def test_valid_effects_pass(self):
        validator = ContentValidator()
        plot_beats = [
            make_plot_beat("beat_a", effects=[
                PlotBeatEffect(type="add_known_fact", params={"fact_id": "test"}),
                PlotBeatEffect(type="advance_quest", params={"quest_id": "q1"}),
                PlotBeatEffect(type="set_state", params={"key": "test", "value": True}),
            ]),
        ]
        
        issues = validator.validate_effect_whitelist(plot_beats)
        
        assert len(issues) == 0

    def test_unknown_effect_type_returns_error(self):
        validator = ContentValidator()
        plot_beats = [
            make_plot_beat("beat_a", effects=[
                PlotBeatEffect(type="unknown_effect", params={}),
            ]),
        ]
        
        issues = validator.validate_effect_whitelist(plot_beats)
        
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].code == "UNKNOWN_EFFECT_TYPE"
        assert "unknown_effect" in issues[0].message

    def test_multiple_unknown_effects_return_multiple_errors(self):
        validator = ContentValidator()
        plot_beats = [
            make_plot_beat("beat_a", effects=[
                PlotBeatEffect(type="unknown_1", params={}),
                PlotBeatEffect(type="unknown_2", params={}),
            ]),
        ]
        
        issues = validator.validate_effect_whitelist(plot_beats)
        
        assert len(issues) == 2


class TestValidate:
    """Tests for the main validate method."""

    def test_valid_pack_passes_all_validations(self):
        validator = ContentValidator()
        pack = make_pack(
            factions=[
                make_faction("faction_a"),
                make_faction("faction_b"),
            ],
            plot_beats=[
                make_plot_beat("beat_a", conditions=[
                    PlotBeatCondition(type="fact_known", params={}),
                ], effects=[
                    PlotBeatEffect(type="set_state", params={}),
                ]),
            ],
        )
        
        report = validator.validate(pack)
        
        assert report.is_valid is True
        assert len(report.issues) == 0

    def test_invalid_pack_with_multiple_issues(self):
        validator = ContentValidator()
        pack = make_pack(
            factions=[
                make_faction("duplicate"),
                make_faction("duplicate"),
            ],
            plot_beats=[
                make_plot_beat("beat_a", conditions=[
                    PlotBeatCondition(type="unknown_condition", params={}),
                ], effects=[
                    PlotBeatEffect(type="unknown_effect", params={}),
                ]),
            ],
        )
        
        report = validator.validate(pack)
        
        assert report.is_valid is False
        assert len(report.issues) >= 3
        assert report.has_errors() is True

    def test_report_has_errors_method(self):
        validator = ContentValidator()
        pack = make_pack(
            factions=[
                make_faction("faction_a"),
            ],
            plot_beats=[
                make_plot_beat("beat_a", conditions=[
                    PlotBeatCondition(type="unknown_condition", params={}),
                ]),
            ],
        )
        
        report = validator.validate(pack)
        
        assert report.has_errors() is True
        assert report.has_warnings() is False
