"""Unit tests for content pack Pydantic v2 schema models."""

import pytest
from datetime import datetime

from llm_rpg.models.content_pack import (
    CONDITIONS,
    EFFECTS,
    ContentFileRefs,
    ContentPackDefinition,
    ContentPackManifest,
    ContentValidationIssue,
    ContentValidationReport,
    FactionDefinition,
    FactionGoalDefinition,
    FactionRelationshipDefinition,
    PlotBeatCondition,
    PlotBeatDefinition,
    PlotBeatEffect,
    PlotBeatVisibility,
)


class TestConstants:
    def test_conditions_whitelist(self):
        assert "fact_known" in CONDITIONS
        assert "state_equals" in CONDITIONS
        assert "state_in" in CONDITIONS
        assert "quest_stage" in CONDITIONS
        assert "npc_present" in CONDITIONS
        assert "location_is" in CONDITIONS
        assert len(CONDITIONS) == 6

    def test_effects_whitelist(self):
        assert "add_known_fact" in EFFECTS
        assert "advance_quest" in EFFECTS
        assert "set_state" in EFFECTS
        assert "emit_event" in EFFECTS
        assert "change_relationship" in EFFECTS
        assert "add_memory" in EFFECTS
        assert len(EFFECTS) == 6


class TestPlotBeatVisibility:
    def test_enum_values(self):
        assert PlotBeatVisibility.HIDDEN == "hidden"
        assert PlotBeatVisibility.CONDITIONAL == "conditional"
        assert PlotBeatVisibility.REVEALED == "revealed"

    def test_enum_from_string(self):
        assert PlotBeatVisibility("hidden") is PlotBeatVisibility.HIDDEN
        assert PlotBeatVisibility("conditional") is PlotBeatVisibility.CONDITIONAL
        assert PlotBeatVisibility("revealed") is PlotBeatVisibility.REVEALED

    def test_enum_member_count(self):
        assert len(PlotBeatVisibility) == 3


class TestContentPackManifest:
    def test_create_with_required_fields(self):
        m = ContentPackManifest(id="pack-1", name="Test Pack", version="1.0.0")
        assert m.id == "pack-1"
        assert m.name == "Test Pack"
        assert m.version == "1.0.0"
        assert m.description == ""
        assert m.author == ""
        assert isinstance(m.created_at, datetime)

    def test_create_with_all_fields(self):
        now = datetime(2026, 1, 1, 12, 0, 0)
        m = ContentPackManifest(
            id="pack-2",
            name="Full Pack",
            version="2.0.0",
            description="A full test pack",
            author="Test Author",
            created_at=now,
        )
        assert m.created_at == now

    def test_model_validate(self):
        data = {"id": "p", "name": "n", "version": "1.0.0"}
        m = ContentPackManifest.model_validate(data)
        assert m.id == "p"


class TestFactionGoalDefinition:
    def test_create_with_required_fields(self):
        g = FactionGoalDefinition(goal_id="g1", description="Conquer territory")
        assert g.goal_id == "g1"
        assert g.priority == 0
        assert g.status == "active"

    def test_create_with_all_fields(self):
        g = FactionGoalDefinition(
            goal_id="g2",
            description="Defend the realm",
            priority=75,
            status="completed",
        )
        assert g.priority == 75
        assert g.status == "completed"

    def test_priority_bounds(self):
        FactionGoalDefinition(goal_id="g3", description="t", priority=0)
        FactionGoalDefinition(goal_id="g4", description="t", priority=100)
        with pytest.raises(Exception):
            FactionGoalDefinition(goal_id="g5", description="t", priority=-1)
        with pytest.raises(Exception):
            FactionGoalDefinition(goal_id="g6", description="t", priority=101)


class TestFactionRelationshipDefinition:
    def test_create_with_required_fields(self):
        r = FactionRelationshipDefinition(target_faction_id="f2")
        assert r.target_faction_id == "f2"
        assert r.relationship_type == "neutral"
        assert r.score == 0

    def test_score_bounds(self):
        FactionRelationshipDefinition(target_faction_id="f2", score=-100)
        FactionRelationshipDefinition(target_faction_id="f2", score=100)
        with pytest.raises(Exception):
            FactionRelationshipDefinition(target_faction_id="f2", score=-101)
        with pytest.raises(Exception):
            FactionRelationshipDefinition(target_faction_id="f2", score=101)


class TestFactionDefinition:
    def test_create_with_required_fields(self):
        f = FactionDefinition(id="f1", name="Iron Order", world_id="w1")
        assert f.id == "f1"
        assert f.name == "Iron Order"
        assert f.world_id == "w1"
        assert f.ideology == ""
        assert f.goals == []
        assert f.relationships == []
        assert f.visibility == "public"

    def test_create_with_goals_and_relationships(self):
        f = FactionDefinition(
            id="f2",
            name="Shadow Syndicate",
            world_id="w1",
            ideology="Power through secrecy",
            goals=[
                FactionGoalDefinition(goal_id="g1", description="Control trade", priority=80),
            ],
            relationships=[
                FactionRelationshipDefinition(
                    target_faction_id="f1",
                    relationship_type="rival",
                    score=-50,
                ),
            ],
            visibility="hidden",
        )
        assert len(f.goals) == 1
        assert f.goals[0].goal_id == "g1"
        assert len(f.relationships) == 1
        assert f.relationships[0].relationship_type == "rival"

    def test_from_yaml_like_dict(self):
        data = {
            "id": "cult-of-dawn",
            "name": "黎明教团",
            "world_id": "xiuxian-world",
            "ideology": "追求长生不老",
            "goals": [
                {"goal_id": "cg1", "description": "Obtain the sacred artifact", "priority": 90, "status": "active"},
                {"goal_id": "cg2", "description": "Recruit new disciples", "priority": 40, "status": "active"},
            ],
            "relationships": [
                {"target_faction_id": "iron-order", "relationship_type": "enemy", "score": -80},
            ],
            "visibility": "secret",
        }
        f = FactionDefinition.model_validate(data)
        assert f.name == "黎明教团"
        assert len(f.goals) == 2
        assert f.goals[0].priority == 90
        assert f.relationships[0].score == -80


class TestPlotBeatDefinition:
    def test_create_with_required_fields(self):
        p = PlotBeatDefinition(id="pb1", title="The Awakening", world_id="w1")
        assert p.id == "pb1"
        assert p.conditions == []
        assert p.effects == []
        assert p.priority == 0
        assert p.visibility == PlotBeatVisibility.CONDITIONAL
        assert p.status == "pending"

    def test_create_with_conditions_and_effects(self):
        p = PlotBeatDefinition(
            id="pb2",
            title="Betrayal at Dawn",
            world_id="w1",
            conditions=[
                PlotBeatCondition(type="fact_known", params={"fact_id": "f1"}),
                PlotBeatCondition(type="quest_stage", params={"quest_id": "q1", "stage": "act2"}),
            ],
            effects=[
                PlotBeatEffect(type="add_known_fact", params={"fact_id": "f2"}),
                PlotBeatEffect(type="change_relationship", params={"faction_id": "f1", "delta": -20}),
            ],
            priority=60,
            visibility=PlotBeatVisibility.HIDDEN,
            status="active",
        )
        assert len(p.conditions) == 2
        assert p.conditions[0].type == "fact_known"
        assert len(p.effects) == 2
        assert p.effects[1].params["delta"] == -20
        assert p.visibility == PlotBeatVisibility.HIDDEN

    def test_from_yaml_like_dict(self):
        data = {
            "id": "pb-assassination",
            "title": "暗杀阴谋",
            "world_id": "xiuxian-world",
            "conditions": [
                {"type": "npc_present", "params": {"npc_id": "npc-shadow"}},
                {"type": "state_equals", "params": {"key": "shadow_threat", "value": "high"}},
            ],
            "effects": [
                {"type": "advance_quest", "params": {"quest_id": "q-main", "stage": "crisis"}},
                {"type": "emit_event", "params": {"event_type": "assassination_attempt"}},
            ],
            "priority": 85,
            "visibility": "hidden",
            "status": "pending",
        }
        p = PlotBeatDefinition.model_validate(data)
        assert p.title == "暗杀阴谋"
        assert len(p.conditions) == 2
        assert p.conditions[0].type == "npc_present"
        assert len(p.effects) == 2
        assert p.visibility == PlotBeatVisibility.HIDDEN


class TestContentFileRefs:
    def test_create_empty(self):
        refs = ContentFileRefs()
        assert refs.factions == []
        assert refs.plot_beats == []

    def test_create_with_paths(self):
        refs = ContentFileRefs(
            factions=["factions/iron_order.yaml"],
            plot_beats=["plot/awakening.yaml"],
        )
        assert len(refs.factions) == 1
        assert len(refs.plot_beats) == 1


class TestContentPackDefinition:
    def test_create_with_manifest_only(self):
        manifest = ContentPackManifest(id="cp1", name="Test", version="1.0.0")
        cp = ContentPackDefinition(manifest=manifest)
        assert cp.manifest.id == "cp1"
        assert cp.factions == []
        assert cp.plot_beats == []
        assert cp.file_refs is None

    def test_create_full_pack(self):
        manifest = ContentPackManifest(id="cp2", name="Full Pack", version="1.0.0")
        faction = FactionDefinition(id="f1", name="Order", world_id="w1")
        beat = PlotBeatDefinition(id="pb1", title="Start", world_id="w1")
        refs = ContentFileRefs(factions=["f1.yaml"])

        cp = ContentPackDefinition(
            manifest=manifest,
            factions=[faction],
            plot_beats=[beat],
            file_refs=refs,
            metadata={"source": "test"},
        )
        assert len(cp.factions) == 1
        assert len(cp.plot_beats) == 1
        assert cp.file_refs is not None
        assert cp.file_refs.factions == ["f1.yaml"]
        assert cp.metadata["source"] == "test"

    def test_model_validate_from_dict(self):
        data = {
            "manifest": {"id": "cp3", "name": "Dict Pack", "version": "0.1.0"},
            "factions": [
                {
                    "id": "f1",
                    "name": "Cult",
                    "world_id": "w1",
                    "goals": [
                        {"goal_id": "g1", "description": "Spread influence", "priority": 70},
                    ],
                },
            ],
            "plot_beats": [
                {
                    "id": "pb1",
                    "title": "First Contact",
                    "world_id": "w1",
                    "conditions": [{"type": "location_is", "params": {"location_id": "loc1"}}],
                    "effects": [{"type": "add_known_fact", "params": {"fact_id": "fact1"}}],
                },
            ],
        }
        cp = ContentPackDefinition.model_validate(data)
        assert cp.manifest.name == "Dict Pack"
        assert cp.factions[0].goals[0].priority == 70
        assert cp.plot_beats[0].conditions[0].type == "location_is"


class TestContentValidationIssue:
    def test_create(self):
        issue = ContentValidationIssue(
            severity="error",
            message="Missing required field",
            path="factions[0].name",
            code="MISSING_FIELD",
        )
        assert issue.severity == "error"
        assert issue.code == "MISSING_FIELD"

    def test_model_validate(self):
        data = {
            "severity": "warning",
            "message": "Unknown condition type",
            "path": "plot_beats[0].conditions[0].type",
            "code": "UNKNOWN_CONDITION",
        }
        issue = ContentValidationIssue.model_validate(data)
        assert issue.severity == "warning"


class TestContentValidationReport:
    def test_valid_report(self):
        report = ContentValidationReport(is_valid=True)
        assert report.is_valid is True
        assert report.issues == []
        assert report.has_errors() is False
        assert report.has_warnings() is False

    def test_report_with_errors(self):
        report = ContentValidationReport(
            is_valid=False,
            issues=[
                ContentValidationIssue(
                    severity="error",
                    message="Missing field",
                    path="factions[0]",
                    code="MISSING_FIELD",
                ),
                ContentValidationIssue(
                    severity="warning",
                    message="Unknown effect",
                    path="plot_beats[0]",
                    code="UNKNOWN_EFFECT",
                ),
            ],
        )
        assert report.is_valid is False
        assert report.has_errors() is True
        assert report.has_warnings() is True

    def test_report_with_only_warnings(self):
        report = ContentValidationReport(
            is_valid=True,
            issues=[
                ContentValidationIssue(
                    severity="warning",
                    message="Deprecated field",
                    path="manifest",
                    code="DEPRECATED",
                ),
            ],
        )
        assert report.has_errors() is False
        assert report.has_warnings() is True

    def test_model_validate_from_dict(self):
        data = {
            "is_valid": False,
            "issues": [
                {
                    "severity": "error",
                    "message": "Invalid condition",
                    "path": "plot_beats[2].conditions[0]",
                    "code": "INVALID_CONDITION",
                },
            ],
        }
        report = ContentValidationReport.model_validate(data)
        assert report.is_valid is False
        assert len(report.issues) == 1
