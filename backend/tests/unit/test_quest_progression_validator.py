"""Unit tests for QuestProgressionValidator."""

import pytest

from llm_rpg.core.quest_progression_validator import QuestProgressionValidator
from llm_rpg.models.common import ValidationResult
from llm_rpg.models.content_pack import (
    EFFECTS,
    PlotBeatEffect,
    PlotBeatVisibility,
)


def make_effect(effect_type: str, **params) -> PlotBeatEffect:
    """Helper to create a PlotBeatEffect."""
    return PlotBeatEffect(type=effect_type, params=params)


class TestLegalStageTransition:
    """Tests for legal quest stage transitions."""

    def test_valid_stage_transition(self):
        """Should pass when from_stage matches current stage."""
        validator = QuestProgressionValidator()
        effect = make_effect(
            "advance_quest",
            quest_id="main_quest",
            from_stage=2,
            to_stage=3,
        )
        current_state = {
            "quest_id": "main_quest",
            "current_stage": 2,
        }
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_valid_transition_with_quest_definition(self):
        """Should pass when target stage exists in quest definition."""
        validator = QuestProgressionValidator()
        effect = make_effect(
            "advance_quest",
            quest_id="main_quest",
            from_stage=1,
            to_stage=2,
        )
        current_state = {
            "quest_id": "main_quest",
            "current_stage": 1,
        }
        quest_def = {"stages": [1, 2, 3, 4]}
        
        result = validator.validate_transition(effect, current_state, quest_def)
        
        assert result.is_valid is True


class TestIllegalStageTransition:
    """Tests for illegal quest stage transitions."""

    def test_stage_mismatch_rejected(self):
        """Should reject when from_stage doesn't match current stage."""
        validator = QuestProgressionValidator()
        effect = make_effect(
            "advance_quest",
            quest_id="main_quest",
            from_stage=3,
            to_stage=4,
        )
        current_state = {
            "quest_id": "main_quest",
            "current_stage": 2,  # Mismatch
        }
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is False
        assert any("mismatch" in e.lower() for e in result.errors)

    def test_quest_id_mismatch_rejected(self):
        """Should reject when quest_id doesn't match."""
        validator = QuestProgressionValidator()
        effect = make_effect(
            "advance_quest",
            quest_id="main_quest",
            from_stage=1,
            to_stage=2,
        )
        current_state = {
            "quest_id": "side_quest",  # Different quest
            "current_stage": 1,
        }
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is False
        assert any("mismatch" in e.lower() or "id" in e.lower() for e in result.errors)

    def test_invalid_target_stage_rejected(self):
        """Should reject when to_stage doesn't exist in quest definition."""
        validator = QuestProgressionValidator()
        effect = make_effect(
            "advance_quest",
            quest_id="main_quest",
            from_stage=2,
            to_stage=99,  # Non-existent stage
        )
        current_state = {
            "quest_id": "main_quest",
            "current_stage": 2,
        }
        quest_def = {"stages": [1, 2, 3]}  # No stage 99
        
        result = validator.validate_transition(effect, current_state, quest_def)
        
        assert result.is_valid is False
        assert any("does not exist" in e.lower() for e in result.errors)


class TestUnknownEffectType:
    """Tests for unknown effect types."""

    def test_unknown_effect_type_rejected(self):
        """Should reject unknown effect types."""
        validator = QuestProgressionValidator()
        effect = PlotBeatEffect(type="invalid_effect", params={})
        current_state = {"quest_id": "test", "current_stage": 1}
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is False
        assert any("Unknown effect type" in e for e in result.errors)

    def test_effect_type_whitelist_validation(self):
        """Should validate against EFFECTS constant."""
        validator = QuestProgressionValidator()
        
        for valid_type in EFFECTS:
            effect = make_effect(valid_type)
            result = validator.validate_effect_type_whitelist(effect)
            assert result.is_valid is True

    def test_effect_type_not_in_whitelist(self):
        """Should reject effect types not in whitelist."""
        validator = QuestProgressionValidator()
        effect = PlotBeatEffect(type="custom_effect", params={})
        
        result = validator.validate_effect_type_whitelist(effect)
        
        assert result.is_valid is False


class TestMissingParameters:
    """Tests for missing required parameters."""

    def test_missing_quest_id(self):
        """Should reject when quest_id is missing."""
        validator = QuestProgressionValidator()
        effect = make_effect("advance_quest", from_stage=1, to_stage=2)
        current_state = {"quest_id": "main", "current_stage": 1}
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is False
        assert any("quest_id" in e.lower() for e in result.errors)

    def test_missing_from_stage(self):
        """Should reject when from_stage is missing."""
        validator = QuestProgressionValidator()
        effect = make_effect("advance_quest", quest_id="main", to_stage=2)
        current_state = {"quest_id": "main", "current_stage": 1}
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is False
        assert any("from_stage" in e.lower() for e in result.errors)

    def test_missing_to_stage(self):
        """Should reject when to_stage is missing."""
        validator = QuestProgressionValidator()
        effect = make_effect("advance_quest", quest_id="main", from_stage=1)
        current_state = {"quest_id": "main", "current_stage": 1}
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is False
        assert any("to_stage" in e.lower() for e in result.errors)


class TestHiddenVisibilityConstraint:
    """Tests for hidden plot beat visibility constraint."""

    def test_hidden_beat_not_player_visible(self):
        """Hidden plot beats must not be player-visible."""
        validator = QuestProgressionValidator()
        
        result = validator.validate_visibility_constraint(
            visibility=PlotBeatVisibility.HIDDEN,
            is_player_visible=True,
        )
        
        assert result.is_valid is False
        assert any("not be player-visible" in e.lower() for e in result.errors)

    def test_hidden_beat_player_invisible(self):
        """Hidden plot beats can be player-invisible."""
        validator = QuestProgressionValidator()
        
        result = validator.validate_visibility_constraint(
            visibility=PlotBeatVisibility.HIDDEN,
            is_player_visible=False,
        )
        
        assert result.is_valid is True

    def test_revealed_beat_can_be_visible(self):
        """Revealed plot beats can be player-visible."""
        validator = QuestProgressionValidator()
        
        result = validator.validate_visibility_constraint(
            visibility=PlotBeatVisibility.REVEALED,
            is_player_visible=True,
        )
        
        assert result.is_valid is True

    def test_conditional_beat_can_be_visible(self):
        """Conditional plot beats can be player-visible."""
        validator = QuestProgressionValidator()
        
        result = validator.validate_visibility_constraint(
            visibility=PlotBeatVisibility.CONDITIONAL,
            is_player_visible=True,
        )
        
        assert result.is_valid is True


class TestOtherEffectTypes:
    """Tests for other effect types."""

    def test_add_known_fact_effect_valid(self):
        """Should validate add_known_fact effect."""
        validator = QuestProgressionValidator()
        effect = make_effect("add_known_fact", fact_id="secret_info")
        current_state = {"quest_id": "test", "current_stage": 1}
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is True

    def test_set_state_effect_valid(self):
        """Should validate set_state effect."""
        validator = QuestProgressionValidator()
        effect = make_effect("set_state", key="door_open", value=True)
        current_state = {}
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is True

    def test_emit_event_effect_valid(self):
        """Should validate emit_event effect."""
        validator = QuestProgressionValidator()
        effect = make_effect("emit_event", event_type="world_tick")
        current_state = {}
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is True

    def test_change_relationship_effect_valid(self):
        """Should validate change_relationship effect."""
        validator = QuestProgressionValidator()
        effect = make_effect(
            "change_relationship",
            faction_id="guild_mages",
            delta=-10,
        )
        current_state = {}
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is True

    def test_add_memory_effect_valid(self):
        """Should validate add_memory effect."""
        validator = QuestProgressionValidator()
        effect = make_effect("add_memory", content="Player discovered the truth")
        current_state = {}
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is True


class TestEffectParamsValidation:
    """Tests for effect parameter validation."""

    def test_add_known_fact_missing_fact_id(self):
        """Should reject add_known_fact without fact_id."""
        validator = QuestProgressionValidator()
        effect = make_effect("add_known_fact")
        current_state = {}
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is False

    def test_set_state_missing_key(self):
        """Should reject set_state without key."""
        validator = QuestProgressionValidator()
        effect = make_effect("set_state", value="test")
        current_state = {}
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is False

    def test_change_relationship_missing_faction_id(self):
        """Should reject change_relationship without faction_id."""
        validator = QuestProgressionValidator()
        effect = make_effect("change_relationship", delta=-5)
        current_state = {}
        
        result = validator.validate_transition(effect, current_state)
        
        assert result.is_valid is False


class TestValidationResultStructure:
    """Tests for ValidationResult structure."""

    def test_returns_validation_result(self):
        """Should return ValidationResult model."""
        validator = QuestProgressionValidator()
        effect = make_effect("advance_quest", quest_id="test", from_stage=1, to_stage=2)
        current_state = {"quest_id": "test", "current_stage": 1}
        
        result = validator.validate_transition(effect, current_state)
        
        assert isinstance(result, ValidationResult)
        assert hasattr(result, "is_valid")
        assert hasattr(result, "checks")
        assert hasattr(result, "errors")

    def test_includes_check_details(self):
        """Should include check details in result."""
        validator = QuestProgressionValidator()
        effect = make_effect("advance_quest", quest_id="test", from_stage=1, to_stage=2)
        current_state = {"quest_id": "test", "current_stage": 1}
        
        result = validator.validate_transition(effect, current_state)
        
        assert len(result.checks) > 0
        assert all(hasattr(c, "check_name") for c in result.checks)
        assert all(hasattr(c, "passed") for c in result.checks)


class TestQuestDefinitionStageFormats:
    """Tests for different quest definition stage formats."""

    def test_stages_as_list(self):
        """Should handle stages as list."""
        validator = QuestProgressionValidator()
        effect = make_effect(
            "advance_quest",
            quest_id="quest1",
            from_stage=1,
            to_stage=2,
        )
        current_state = {"quest_id": "quest1", "current_stage": 1}
        quest_def = {"stages": [1, 2, 3]}
        
        result = validator.validate_transition(effect, current_state, quest_def)
        
        assert result.is_valid is True

    def test_stages_as_dict_with_int_keys(self):
        """Should handle stages as dict with int keys."""
        validator = QuestProgressionValidator()
        effect = make_effect(
            "advance_quest",
            quest_id="quest1",
            from_stage=1,
            to_stage=2,
        )
        current_state = {"quest_id": "quest1", "current_stage": 1}
        quest_def = {"stages": {1: "Start", 2: "Middle", 3: "End"}}
        
        result = validator.validate_transition(effect, current_state, quest_def)
        
        assert result.is_valid is True

    def test_stages_as_dict_with_string_keys(self):
        """Should handle stages as dict with string keys."""
        validator = QuestProgressionValidator()
        effect = make_effect(
            "advance_quest",
            quest_id="quest1",
            from_stage=1,
            to_stage=2,
        )
        current_state = {"quest_id": "quest1", "current_stage": 1}
        quest_def = {"stages": {"1": "Start", "2": "Middle", "3": "End"}}
        
        result = validator.validate_transition(effect, current_state, quest_def)
        
        assert result.is_valid is True
