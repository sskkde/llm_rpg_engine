"""
Unit tests for ValidationContext and Validator.

Tests the ValidationContext dataclass and its integration with validation methods.
"""

import pytest
from unittest.mock import MagicMock

from llm_rpg.core.validator import Validator, ValidationContext
from llm_rpg.models.states import (
    CanonicalState,
    PlayerState,
    WorldState,
    CurrentSceneState,
    NPCState,
    LocationState,
    WorldTime,
)
from llm_rpg.models.perspectives import NPCPerspective, PerspectiveType
from llm_rpg.models.common import ProposedAction


def create_sample_state() -> CanonicalState:
    """Create a sample CanonicalState for testing."""
    return CanonicalState(
        player_state=PlayerState(
            entity_id="player",
            name="TestPlayer",
            location_id="loc_tavern",
        ),
        world_state=WorldState(
            entity_id="world",
            world_id="world_1",
            current_time=WorldTime(
                calendar="Test",
                season="Spring",
                day=1,
                period="Morning",
            ),
        ),
        current_scene_state=CurrentSceneState(
            entity_id="scene",
            scene_id="scene_1",
            location_id="loc_tavern",
        ),
        location_states={
            "loc_tavern": LocationState(
                entity_id="loc_tavern",
                location_id="loc_tavern",
                name="Tavern",
            ),
        },
        npc_states={
            "npc_merchant": NPCState(
                entity_id="npc_merchant",
                npc_id="npc_merchant",
                name="Merchant",
                location_id="loc_tavern",
            ),
        },
    )


class TestValidationContextDataclass:
    """Test ValidationContext dataclass creation and fields."""

    def test_validation_context_creation(self):
        """Test creating ValidationContext with all fields."""
        db = MagicMock()
        state = create_sample_state()
        
        context = ValidationContext(
            db=db,
            session_id="session_1",
            turn_no=5,
            canonical_state=state,
            perspective=None,
            source_event_id="event_1",
            actor_id="player",
        )
        
        assert context.db is db
        assert context.session_id == "session_1"
        assert context.turn_no == 5
        assert context.canonical_state is state
        assert context.perspective is None
        assert context.source_event_id == "event_1"
        assert context.actor_id == "player"

    def test_validation_context_defaults(self):
        """Test ValidationContext with optional fields defaulted."""
        db = MagicMock()
        state = create_sample_state()
        
        context = ValidationContext(
            db=db,
            session_id="session_1",
            turn_no=1,
            canonical_state=state,
        )
        
        assert context.perspective is None
        assert context.source_event_id is None
        assert context.actor_id is None

    def test_validation_context_with_perspective(self):
        """Test ValidationContext with NPCPerspective."""
        db = MagicMock()
        state = create_sample_state()
        perspective = NPCPerspective(
            perspective_id="perspective_npc_merchant",
            perspective_type=PerspectiveType.NPC,
            owner_id="npc_merchant",
            npc_id="npc_merchant",
        )
        
        context = ValidationContext(
            db=db,
            session_id="session_1",
            turn_no=1,
            canonical_state=state,
            perspective=perspective,
        )
        
        assert context.perspective is perspective
        assert context.perspective.npc_id == "npc_merchant"


class TestValidationContextFactory:
    """Test ValidationContext.create() factory method."""

    def test_factory_method_basic(self):
        """Test factory method creates ValidationContext correctly."""
        db = MagicMock()
        state = create_sample_state()
        
        context = ValidationContext.create(
            db=db,
            session_id="session_2",
            turn_no=10,
            canonical_state=state,
        )
        
        assert isinstance(context, ValidationContext)
        assert context.db is db
        assert context.session_id == "session_2"
        assert context.turn_no == 10
        assert context.canonical_state is state

    def test_factory_method_with_all_fields(self):
        """Test factory method with all optional fields."""
        db = MagicMock()
        state = create_sample_state()
        perspective = NPCPerspective(
            perspective_id="perspective_npc_merchant",
            perspective_type=PerspectiveType.NPC,
            owner_id="npc_merchant",
            npc_id="npc_merchant",
        )
        
        context = ValidationContext.create(
            db=db,
            session_id="session_3",
            turn_no=3,
            canonical_state=state,
            perspective=perspective,
            source_event_id="event_42",
            actor_id="npc_merchant",
        )
        
        assert context.perspective is perspective
        assert context.source_event_id == "event_42"
        assert context.actor_id == "npc_merchant"


class TestValidatorWithValidationContext:
    """Test Validator methods accepting ValidationContext."""

    def test_validate_action_with_context(self):
        """Test validate_action accepts ValidationContext."""
        validator = Validator()
        state = create_sample_state()
        db = MagicMock()
        
        context = ValidationContext.create(
            db=db,
            session_id="session_1",
            turn_no=1,
            canonical_state=state,
        )
        
        action = ProposedAction(
            action_id="action_1",
            action_type="move",
            actor_id="player",
            target_ids=["loc_tavern"],
            summary="Move to tavern",
        )
        
        result = validator.validate_action(action, state, context=context)
        
        assert result is not None
        assert hasattr(result, "is_valid")

    def test_validate_action_context_overrides_state(self):
        """Test that context.canonical_state overrides state parameter."""
        validator = Validator()
        state1 = create_sample_state()
        state2 = create_sample_state()
        state2.npc_states["npc_guard"] = NPCState(
            entity_id="npc_guard",
            npc_id="npc_guard",
            name="Guard",
            location_id="loc_tavern",
        )
        db = MagicMock()
        
        context = ValidationContext.create(
            db=db,
            session_id="session_1",
            turn_no=1,
            canonical_state=state2,
        )
        
        action = ProposedAction(
            action_id="action_1",
            action_type="talk",
            actor_id="player",
            target_ids=["npc_guard"],
            summary="Talk to guard",
        )
        
        result = validator.validate_action(action, state1, context=context)
        
        assert result.is_valid

    def test_validate_state_delta_with_context(self):
        """Test validate_state_delta accepts ValidationContext."""
        validator = Validator()
        state = create_sample_state()
        db = MagicMock()
        
        context = ValidationContext.create(
            db=db,
            session_id="session_1",
            turn_no=1,
            canonical_state=state,
        )
        
        result = validator.validate_state_delta(
            delta_path="npcs.npc_merchant.hp",
            old_value=100,
            new_value=80,
            state=state,
            context=context,
        )
        
        assert result is not None

    def test_validate_perspective_knowledge_with_context(self):
        """Test validate_perspective_knowledge accepts ValidationContext."""
        validator = Validator()
        state = create_sample_state()
        db = MagicMock()
        
        context = ValidationContext.create(
            db=db,
            session_id="session_1",
            turn_no=1,
            canonical_state=state,
        )
        
        result = validator.validate_perspective_knowledge(
            npc_id="npc_merchant",
            knowledge="secret_trade_route",
            state=state,
            context=context,
        )
        
        assert result.is_valid

    def test_validate_candidate_event_with_context(self):
        """Test validate_candidate_event accepts ValidationContext."""
        validator = Validator()
        state = create_sample_state()
        db = MagicMock()
        
        context = ValidationContext.create(
            db=db,
            session_id="session_1",
            turn_no=1,
            canonical_state=state,
        )
        
        result = validator.validate_candidate_event(
            event_type="npc_action",
            description="Merchant sells goods",
            target_entity_ids=["npc_merchant"],
            effects={},
            state=state,
            context=context,
        )
        
        assert result is not None


class TestValidatorBackwardCompatibility:
    """Test that Validator methods work without ValidationContext."""

    def test_validate_action_without_context(self):
        """Test validate_action works without ValidationContext (backward compat)."""
        validator = Validator()
        state = create_sample_state()
        
        action = ProposedAction(
            action_id="action_1",
            action_type="move",
            actor_id="player",
            target_ids=["loc_tavern"],
            summary="Move to tavern",
        )
        
        result = validator.validate_action(action, state)
        
        assert result is not None

    def test_validate_state_delta_without_context(self):
        """Test validate_state_delta works without ValidationContext."""
        validator = Validator()
        state = create_sample_state()
        
        result = validator.validate_state_delta(
            delta_path="npcs.npc_merchant.hp",
            old_value=100,
            new_value=80,
            state=state,
        )
        
        assert result is not None

    def test_validate_perspective_knowledge_without_context(self):
        """Test validate_perspective_knowledge works without ValidationContext."""
        validator = Validator()
        state = create_sample_state()
        
        result = validator.validate_perspective_knowledge(
            npc_id="npc_merchant",
            knowledge="secret_trade_route",
            state=state,
        )
        
        assert result.is_valid

    def test_validate_candidate_event_without_context(self):
        """Test validate_candidate_event works without ValidationContext."""
        validator = Validator()
        state = create_sample_state()
        
        result = validator.validate_candidate_event(
            event_type="npc_action",
            description="Merchant sells goods",
            target_entity_ids=["npc_merchant"],
            effects={},
            state=state,
        )
        
        assert result is not None
