"""
Unit tests for action_schema module.
"""

import pytest

from llm_rpg.rules.action_schema import (
    ActionType,
    TargetType,
    ActionSchema,
    ACTION_SCHEMAS,
    validate_action_schema,
)


class TestActionType:
    """Tests for ActionType enum."""

    def test_action_type_has_16_values(self):
        """Test that ActionType has exactly 16 values."""
        assert len(ActionType) == 16

    def test_action_type_values(self):
        """Test that ActionType has all expected values."""
        expected = {
            "move", "inspect", "talk", "ask", "use_item", "take_item",
            "give_item", "attack", "defend", "cast_skill", "persuade",
            "hide", "follow", "wait", "trigger_object", "quest_progress",
        }
        actual = {e.value for e in ActionType}
        assert actual == expected


class TestTargetType:
    """Tests for TargetType enum."""

    def test_target_type_has_5_values(self):
        """Test that TargetType has exactly 5 values."""
        assert len(TargetType) == 5

    def test_target_type_values(self):
        """Test that TargetType has all expected values."""
        expected = {"location", "npc", "item", "self", "none"}
        actual = {e.value for e in TargetType}
        assert actual == expected


class TestActionSchema:
    """Tests for ActionSchema dataclass."""

    def test_action_schema_creation(self):
        """Test creating an ActionSchema."""
        schema = ActionSchema(
            action_type=ActionType.move,
            required_fields=["target_ids"],
            optional_fields=[],
            valid_targets=[TargetType.location],
            description="Move to a location",
        )
        assert schema.action_type == ActionType.move
        assert schema.required_fields == ["target_ids"]
        assert schema.optional_fields == []
        assert schema.valid_targets == [TargetType.location]
        assert schema.description == "Move to a location"


class TestActionSchemasRegistry:
    """Tests for ACTION_SCHEMAS registry."""

    def test_all_16_action_types_have_schemas(self):
        """Test that all 16 action types have entries in ACTION_SCHEMAS."""
        assert len(ACTION_SCHEMAS) == 16
        for action_type in ActionType:
            assert action_type in ACTION_SCHEMAS, f"Missing schema for {action_type}"

    def test_use_item_has_item_id_in_required_fields(self):
        """Test that use_item has item_id in required_fields."""
        schema = ACTION_SCHEMAS[ActionType.use_item]
        assert "item_id" in schema.required_fields

    def test_move_has_target_ids_in_required_fields(self):
        """Test that move has target_ids in required_fields."""
        schema = ACTION_SCHEMAS[ActionType.move]
        assert "target_ids" in schema.required_fields

    def test_talk_has_npc_target(self):
        """Test that talk only targets NPCs."""
        schema = ACTION_SCHEMAS[ActionType.talk]
        assert TargetType.npc in schema.valid_targets
        assert len(schema.valid_targets) == 1


class TestValidateActionSchema:
    """Tests for validate_action_schema function."""

    def test_valid_move_action_passes(self):
        """Test 1: Valid move action passes."""
        action = {
            "action_type": "move",
            "target_ids": ["location_1"],
        }
        result = validate_action_schema(action)
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_move_without_target_ids_fails(self):
        """Test 2: Move without target_ids fails."""
        action = {
            "action_type": "move",
        }
        result = validate_action_schema(action)
        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_valid_attack_with_target_passes(self):
        """Test 3: Valid attack with target passes."""
        action = {
            "action_type": "attack",
            "target_ids": ["npc_1"],
        }
        result = validate_action_schema(action)
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_talk_without_target_fails(self):
        """Test 4: Talk without target fails."""
        action = {
            "action_type": "talk",
        }
        result = validate_action_schema(action)
        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_valid_use_item_with_item_id_passes(self):
        """Test 5: Valid use_item with item_id passes."""
        action = {
            "action_type": "use_item",
            "item_id": "item_1",
        }
        result = validate_action_schema(action)
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_unknown_action_type_fails(self):
        """Test 6: Unknown action_type fails."""
        action = {
            "action_type": "unknown_action",
        }
        result = validate_action_schema(action)
        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_missing_action_type_fails(self):
        """Test that action without action_type fails."""
        action = {
            "target_ids": ["npc_1"],
        }
        result = validate_action_schema(action)
        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_defend_has_no_required_fields(self):
        """Test that defend action passes with no fields."""
        action = {
            "action_type": "defend",
        }
        result = validate_action_schema(action)
        assert result.is_valid is True

    def test_cast_skill_requires_skill_name(self):
        """Test that cast_skill requires skill_name."""
        action = {
            "action_type": "cast_skill",
        }
        result = validate_action_schema(action)
        assert result.is_valid is False

        action_with_skill = {
            "action_type": "cast_skill",
            "skill_name": "fireball",
        }
        result = validate_action_schema(action_with_skill)
        assert result.is_valid is True
