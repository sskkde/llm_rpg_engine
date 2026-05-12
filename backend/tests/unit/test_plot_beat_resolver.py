"""Unit tests for PlotBeatResolver."""

import pytest

from llm_rpg.core.plot_beat_resolver import (
    ConditionEvaluation,
    EvaluatedPlotBeat,
    PlotBeatResolver,
)
from llm_rpg.models.content_pack import (
    PlotBeatCondition,
    PlotBeatDefinition,
    PlotBeatVisibility,
)


def make_condition(condition_type: str, **params) -> PlotBeatCondition:
    """Helper to create a PlotBeatCondition."""
    return PlotBeatCondition(type=condition_type, params=params)


def make_beat(
    beat_id: str = "test_beat",
    conditions: list = None,
    **kwargs,
) -> PlotBeatDefinition:
    """Helper to create a PlotBeatDefinition."""
    return PlotBeatDefinition(
        id=beat_id,
        title="Test Beat",
        world_id="test_world",
        conditions=conditions or [],
        **kwargs,
    )


class TestPlotBeatResolverBasics:
    """Basic resolver functionality tests."""

    def test_resolver_is_stateless(self):
        """Resolver should not maintain state between calls."""
        resolver = PlotBeatResolver()
        
        beat1 = make_beat("beat1", conditions=[
            make_condition("fact_known", fact_id="fact1"),
        ])
        beat2 = make_beat("beat2", conditions=[
            make_condition("fact_known", fact_id="fact2"),
        ])
        
        context1 = {"known_facts": ["fact1"]}
        context2 = {"known_facts": ["fact2"]}
        
        result1 = resolver.evaluate(beat1, context1)
        result2 = resolver.evaluate(beat2, context2)
        
        assert result1.eligible is True
        assert result2.eligible is True

    def test_empty_conditions_always_eligible(self):
        """Beat with no conditions should always be eligible."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[])
        
        result = resolver.evaluate(beat, {})
        
        assert result.eligible is True
        assert "No conditions" in result.reasons[0]

    def test_returns_evaluated_plot_beat(self):
        """Should return EvaluatedPlotBeat model."""
        resolver = PlotBeatResolver()
        beat = make_beat()
        
        result = resolver.evaluate(beat, {})
        
        assert isinstance(result, EvaluatedPlotBeat)
        assert result.beat_id == "test_beat"


class TestFactKnownCondition:
    """Tests for fact_known condition type."""

    def test_fact_known_when_present(self):
        """Should pass when fact is in known_facts."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("fact_known", fact_id="secret_door"),
        ])
        context = {"known_facts": ["secret_door", "treasure_location"]}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is True
        assert result.condition_evaluations[0].passed is True

    def test_fact_known_when_absent(self):
        """Should fail when fact is not in known_facts."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("fact_known", fact_id="secret_door"),
        ])
        context = {"known_facts": ["treasure_location"]}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is False
        assert result.condition_evaluations[0].passed is False
        assert "not known" in result.condition_evaluations[0].reason

    def test_fact_known_missing_fact_id_param(self):
        """Should fail when fact_id parameter is missing."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("fact_known"),
        ])
        context = {"known_facts": ["some_fact"]}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is False
        assert "Missing 'fact_id'" in result.condition_evaluations[0].reason


class TestStateEqualsCondition:
    """Tests for state_equals condition type."""

    def test_state_equals_match(self):
        """Should pass when state value matches."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("state_equals", key="boss_defeated", value=True),
        ])
        context = {"state": {"boss_defeated": True}}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is True

    def test_state_equals_mismatch(self):
        """Should fail when state value doesn't match."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("state_equals", key="boss_defeated", value=True),
        ])
        context = {"state": {"boss_defeated": False}}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is False
        assert "expected" in result.condition_evaluations[0].reason.lower()

    def test_state_equals_key_not_found(self):
        """Should fail when state key doesn't exist."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("state_equals", key="missing_key", value="any"),
        ])
        context = {"state": {}}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is False
        assert "not found" in result.condition_evaluations[0].reason

    def test_state_equals_missing_key_param(self):
        """Should fail when key parameter is missing."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("state_equals", value="test"),
        ])
        context = {"state": {"some_key": "test"}}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is False
        assert "Missing 'key'" in result.condition_evaluations[0].reason


class TestStateInCondition:
    """Tests for state_in condition type."""

    def test_state_in_values_match(self):
        """Should pass when state value is in values list."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("state_in", key="player_class", values=["warrior", "mage", "rogue"]),
        ])
        context = {"state": {"player_class": "mage"}}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is True

    def test_state_in_values_no_match(self):
        """Should fail when state value is not in values list."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("state_in", key="player_class", values=["warrior", "mage"]),
        ])
        context = {"state": {"player_class": "rogue"}}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is False
        assert "not in" in result.condition_evaluations[0].reason.lower()

    def test_state_in_missing_values_param(self):
        """Should handle missing values parameter."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("state_in", key="player_class"),
        ])
        context = {"state": {"player_class": "mage"}}
        
        result = resolver.evaluate(beat, context)
        
        # Empty values list should fail the match
        assert result.eligible is False


class TestQuestStageCondition:
    """Tests for quest_stage condition type."""

    def test_quest_stage_match(self):
        """Should pass when quest is at expected stage."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("quest_stage", quest_id="main_quest", stage=3),
        ])
        context = {"quest_stages": {"main_quest": 3, "side_quest": 1}}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is True

    def test_quest_stage_mismatch(self):
        """Should fail when quest is at different stage."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("quest_stage", quest_id="main_quest", stage=3),
        ])
        context = {"quest_stages": {"main_quest": 2}}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is False
        assert "expected" in result.condition_evaluations[0].reason.lower()

    def test_quest_stage_quest_not_found(self):
        """Should fail when quest is not in quest_stages."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("quest_stage", quest_id="unknown_quest", stage=1),
        ])
        context = {"quest_stages": {"main_quest": 1}}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is False
        assert "not found" in result.condition_evaluations[0].reason.lower()


class TestNpcPresentCondition:
    """Tests for npc_present condition type."""

    def test_npc_present_when_there(self):
        """Should pass when NPC is in npc_presence list."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("npc_present", npc_id="npc_blacksmith"),
        ])
        context = {"npc_presence": ["npc_blacksmith", "npc_merchant"]}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is True

    def test_npc_present_when_absent(self):
        """Should fail when NPC is not in npc_presence list."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("npc_present", npc_id="npc_blacksmith"),
        ])
        context = {"npc_presence": ["npc_merchant"]}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is False
        assert "not present" in result.condition_evaluations[0].reason.lower()


class TestLocationIsCondition:
    """Tests for location_is condition type."""

    def test_location_is_match(self):
        """Should pass when current location matches."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("location_is", location_id="loc_tavern"),
        ])
        context = {"current_location": "loc_tavern"}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is True

    def test_location_is_mismatch(self):
        """Should fail when current location doesn't match."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("location_is", location_id="loc_tavern"),
        ])
        context = {"current_location": "loc_forest"}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is False
        assert "expected" in result.condition_evaluations[0].reason.lower()


class TestUnknownConditionType:
    """Tests for unknown condition types."""

    def test_unknown_condition_type_rejected(self):
        """Should reject unknown condition types."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            PlotBeatCondition(type="invalid_condition", params={}),
        ])
        context = {}
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is False
        assert "Unknown condition type" in result.condition_evaluations[0].reason


class TestMultipleConditions:
    """Tests for beats with multiple conditions."""

    def test_all_conditions_pass(self):
        """Should be eligible when all conditions pass."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("fact_known", fact_id="secret"),
            make_condition("state_equals", key="level", value=5),
            make_condition("location_is", location_id="loc_dungeon"),
        ])
        context = {
            "known_facts": ["secret"],
            "state": {"level": 5},
            "current_location": "loc_dungeon",
        }
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is True
        assert "3 conditions passed" in result.reasons[0]

    def test_some_conditions_fail(self):
        """Should not be eligible when any condition fails."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("fact_known", fact_id="secret"),
            make_condition("state_equals", key="level", value=10),
            make_condition("location_is", location_id="loc_dungeon"),
        ])
        context = {
            "known_facts": ["secret"],
            "state": {"level": 5},
            "current_location": "loc_dungeon",
        }
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is False
        assert "1 of 3 conditions failed" in result.reasons[0]

    def test_all_conditions_fail(self):
        """Should not be eligible when all conditions fail."""
        resolver = PlotBeatResolver()
        beat = make_beat(conditions=[
            make_condition("fact_known", fact_id="secret"),
            make_condition("location_is", location_id="loc_dungeon"),
        ])
        context = {
            "known_facts": [],
            "current_location": "loc_tavern",
        }
        
        result = resolver.evaluate(beat, context)
        
        assert result.eligible is False
        assert "2 of 2 conditions failed" in result.reasons[0]


class TestConditionEvaluation:
    """Tests for ConditionEvaluation model."""

    def test_condition_evaluation_fields(self):
        """ConditionEvaluation should have required fields."""
        eval_ = ConditionEvaluation(
            condition_type="fact_known",
            passed=True,
            reason="Test reason",
        )
        
        assert eval_.condition_type == "fact_known"
        assert eval_.passed is True
        assert eval_.reason == "Test reason"


class TestEvaluatedPlotBeat:
    """Tests for EvaluatedPlotBeat model."""

    def test_evaluated_plot_beat_fields(self):
        """EvaluatedPlotBeat should have required fields."""
        result = EvaluatedPlotBeat(
            beat_id="test_beat",
            eligible=True,
            condition_evaluations=[],
            reasons=["All good"],
        )
        
        assert result.beat_id == "test_beat"
        assert result.eligible is True
        assert result.reasons == ["All good"]
