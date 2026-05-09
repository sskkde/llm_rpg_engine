"""
Unit tests for ValidationContext and Validator.

Tests the ValidationContext dataclass and its integration with validation methods.
"""

import pytest
from unittest.mock import MagicMock
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.core.validation.narration_leak_validator import NarrationLeakValidator
from llm_rpg.core.validation.npc_knowledge_validator import NPCKnowledgeValidator
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
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    GameEventModel,
    NPCBeliefModel,
    NPCTemplateModel,
    NPCSecretModel,
    SessionModel,
    SessionNPCStateModel,
    TurnTransactionModel,
    UserModel,
    WorldModel,
)


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


@pytest.fixture
def npc_knowledge_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    session.add_all([
        UserModel(id="user_npc_knowledge", username="npc_knowledge", email="npc_knowledge@example.com", password_hash="hashed"),
        WorldModel(id="world_npc_knowledge", code="world_npc_knowledge", name="NPC知识世界"),
        SessionModel(id="session_npc_knowledge", user_id="user_npc_knowledge", world_id="world_npc_knowledge", status="active"),
        NPCTemplateModel(
            id="npc_alchemist",
            world_id="world_npc_knowledge",
            code="alchemist",
            name="丹师",
            public_identity="宗门丹师",
            hidden_identity="他其实是叛逃药王",
        ),
        NPCTemplateModel(
            id="npc_guard",
            world_id="world_npc_knowledge",
            code="guard",
            name="守卫",
            public_identity="山门守卫",
            hidden_identity="她其实是暗线密探",
        ),
        SessionNPCStateModel(
            id="npc_state_alchemist",
            session_id="session_npc_knowledge",
            npc_template_id="npc_alchemist",
            current_location_id="loc_tavern",
        ),
        SessionNPCStateModel(
            id="npc_state_guard",
            session_id="session_npc_knowledge",
            npc_template_id="npc_guard",
            current_location_id="loc_tavern",
        ),
        NPCSecretModel(
            id="secret_alchemist",
            session_id="session_npc_knowledge",
            npc_id="npc_alchemist",
            content="丹师把九转还魂丹藏在炉底暗格",
            status="hidden",
        ),
        NPCSecretModel(
            id="secret_guard",
            session_id="session_npc_knowledge",
            npc_id="npc_guard",
            content="守卫知道东门阵眼今晚失效",
            status="hidden",
        ),
        NPCBeliefModel(
            id="belief_guard_secret_access",
            session_id="session_npc_knowledge",
            npc_id="npc_guard",
            belief_type="perceived_secret",
            content="丹师把九转还魂丹藏在炉底暗格",
            confidence=0.9,
            truth_status="true",
            created_turn=1,
            last_updated_turn=1,
        ),
        NPCBeliefModel(
            id="belief_guard_public",
            session_id="session_npc_knowledge",
            npc_id="npc_guard",
            belief_type="public_fact",
            content="宗门广场每日辰时鸣钟",
            confidence=1.0,
            truth_status="true",
            created_turn=1,
            last_updated_turn=1,
        ),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def create_npc_knowledge_state() -> CanonicalState:
    state = create_sample_state()
    state.npc_states["npc_alchemist"] = NPCState(
        entity_id="npc_alchemist",
        npc_id="npc_alchemist",
        name="丹师",
        location_id="loc_tavern",
    )
    state.npc_states["npc_guard"] = NPCState(
        entity_id="npc_guard",
        npc_id="npc_guard",
        name="守卫",
        location_id="loc_tavern",
    )
    return state


@pytest.fixture
def narration_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    session.add_all([
        UserModel(id="user_narration", username="narration", email="narration@example.com", password_hash="hashed"),
        WorldModel(id="world_narration", code="world_narration", name="叙事世界"),
        SessionModel(id="session_narration", user_id="user_narration", world_id="world_narration", status="active"),
        NPCTemplateModel(
            id="npc_mentor",
            world_id="world_narration",
            code="mentor",
            name="柳师姐",
            public_identity="宗门师姐",
            hidden_identity="她其实是魔门卧底",
        ),
        SessionNPCStateModel(
            id="npc_state_mentor",
            session_id="session_narration",
            npc_template_id="npc_mentor",
            current_location_id="loc_tavern",
        ),
        NPCSecretModel(
            id="secret_mentor",
            session_id="session_narration",
            npc_id="npc_mentor",
            content="柳师姐藏着血契玉简",
            status="hidden",
        ),
        TurnTransactionModel(
            id="txn_narration",
            session_id="session_narration",
            turn_no=1,
            idempotency_key="txn_narration_key",
            status="committed",
            started_at=datetime.now(),
        ),
        GameEventModel(
            id="event_private",
            transaction_id="txn_narration",
            session_id="session_narration",
            turn_no=1,
            event_type="npc_private_thought",
            actor_id="npc_mentor",
            private_payload_json={"thought": "柳师姐准备午夜叛逃"},
            occurred_at=datetime.now(),
        ),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


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


class TestNarrationLeakValidatorDBBackedFacts:
    def test_db_backed_npc_secret_leak_is_rejected(self, narration_db):
        validator = NarrationLeakValidator()

        result = validator.validate_narration(
            text="柳师姐藏着血契玉简，不能让别人发现。",
            forbidden_info=[],
            db=narration_db,
            session_id="session_narration",
            npc_ids=["npc_mentor"],
        )

        assert not result.is_valid
        assert any("npc_secret:npc_mentor" in error for error in result.errors)

    def test_hidden_identity_exposure_is_rejected(self, narration_db):
        validator = NarrationLeakValidator()

        result = validator.validate_narration(
            text="柳师姐表面温和，但她其实是魔门卧底。",
            forbidden_info=[],
            db=narration_db,
            session_id="session_narration",
            npc_ids=["npc_mentor"],
        )

        assert not result.is_valid
        assert any("hidden_identity:npc_mentor" in error for error in result.errors)

    def test_private_payload_content_is_rejected(self, narration_db):
        validator = NarrationLeakValidator()

        result = validator.validate_narration(
            text="夜色中，柳师姐准备午夜叛逃。",
            forbidden_info=[],
            db=narration_db,
            session_id="session_narration",
        )

        assert not result.is_valid
        assert any("private_payload:event_private" in error for error in result.errors)

    def test_safe_player_visible_narration_is_accepted(self, narration_db):
        validator = NarrationLeakValidator()

        result = validator.validate_narration(
            text="柳师姐站在宗门广场，提醒你留意脚下青石。",
            forbidden_info=[],
            db=narration_db,
            session_id="session_narration",
            npc_ids=["npc_mentor"],
        )

        assert result.is_valid
        assert result.errors == []


class TestNPCKnowledgeValidatorDBBackedFacts:
    def test_unknown_secret_reference_is_rejected(self, npc_knowledge_db):
        validator = NPCKnowledgeValidator()

        result = validator.validate_knowledge(
            npc_id="npc_alchemist",
            knowledge="我知道守卫知道东门阵眼今晚失效，正好可以利用。",
            state=create_npc_knowledge_state(),
            db=npc_knowledge_db,
            session_id="session_npc_knowledge",
        )

        assert not result.is_valid
        assert any("npc_secret:npc_guard" in error for error in result.errors)

    def test_hidden_identity_exposure_is_rejected_without_access(self, npc_knowledge_db):
        validator = NPCKnowledgeValidator()

        result = validator.validate_knowledge(
            npc_id="npc_alchemist",
            knowledge="守卫表面寻常，但她其实是暗线密探。",
            state=create_npc_knowledge_state(),
            db=npc_knowledge_db,
            session_id="session_npc_knowledge",
        )

        assert not result.is_valid
        assert any("hidden_identity:npc_guard" in error for error in result.errors)

    def test_owned_secret_is_accepted(self, npc_knowledge_db):
        validator = NPCKnowledgeValidator()

        result = validator.validate_knowledge(
            npc_id="npc_alchemist",
            knowledge="丹师把九转还魂丹藏在炉底暗格，所以他要守住丹房。",
            state=create_npc_knowledge_state(),
            db=npc_knowledge_db,
            session_id="session_npc_knowledge",
        )

        assert result.is_valid
        assert result.errors == []

    def test_perceived_secret_in_belief_is_accepted(self, npc_knowledge_db):
        validator = NPCKnowledgeValidator()

        result = validator.validate_knowledge(
            npc_id="npc_guard",
            knowledge="她记得丹师把九转还魂丹藏在炉底暗格，因此加派人手。",
            state=create_npc_knowledge_state(),
            db=npc_knowledge_db,
            session_id="session_npc_knowledge",
        )

        assert result.is_valid
        assert result.errors == []

    def test_public_common_knowledge_is_not_blocked(self, npc_knowledge_db):
        validator = NPCKnowledgeValidator()

        result = validator.validate_knowledge(
            npc_id="npc_guard",
            knowledge="宗门广场每日辰时鸣钟，守卫准备按时开门。",
            state=create_npc_knowledge_state(),
            db=npc_knowledge_db,
            session_id="session_npc_knowledge",
        )

        assert result.is_valid
        assert result.errors == []


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
