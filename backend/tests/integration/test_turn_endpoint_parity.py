"""
Integration tests for turn endpoint parity.

Tests that /game/sessions/{session_id}/turn and /streaming/sessions/{session_id}/turn
produce identical side effects by verifying the shared turn_service behavior.

Key tests:
- test_game_and_streaming_turns_persist_equivalent_side_effects
- test_game_and_streaming_blocked_move_do_not_mutate_location
- test_turn_service_handles_movement
- test_turn_service_handles_initialization
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    WorldModel,
    ChapterModel,
    LocationModel,
    UserModel,
    SaveSlotModel,
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
    SessionNPCStateModel,
    NPCTemplateModel,
    SessionQuestStateModel,
    QuestTemplateModel,
    EventLogModel,
)
from llm_rpg.core.turn_service import (
    execute_turn_service,
    TurnResult,
    TurnServiceError,
    SessionNotFoundError,
)
from llm_rpg.core.turn_allocation import commit_turn


@pytest.fixture
def db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass= StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def test_user(db: Session) -> UserModel:
    """Create a test user."""
    user = UserModel(
        id="user_1",
        username="testuser",
        email="test@example.com",
        password_hash="hashed",
        is_admin=False,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def test_world(db: Session) -> WorldModel:
    """Create a test world."""
    world = WorldModel(
        id="world_1",
        code="test_world",
        name="测试世界",
        genre="xianxia",
        lore_summary="测试用世界",
        status="active",
    )
    db.add(world)
    db.commit()
    return world


@pytest.fixture
def test_chapter(db: Session, test_world: WorldModel) -> ChapterModel:
    """Create a test chapter."""
    chapter = ChapterModel(
        id="chapter_1",
        world_id=test_world.id,
        chapter_no=1,
        name="第一章",
        summary="测试章节",
    )
    db.add(chapter)
    db.commit()
    return chapter


@pytest.fixture
def test_locations(db: Session, test_world: WorldModel, test_chapter: ChapterModel):
    """Create test locations."""
    locations = [
        LocationModel(
            id="loc_square",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="square",
            name="宗门广场",
            tags=["public", "safe", "starting_point"],
            description="宗门广场",
            access_rules={"always_accessible": True},
        ),
        LocationModel(
            id="loc_trial_hall",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="trial_hall",
            name="试炼堂",
            tags=["public", "quest_hub"],
            description="试炼堂",
            access_rules={"time_restrictions": "daytime_only"},
        ),
        LocationModel(
            id="loc_forest",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="forest",
            name="山林试炼区",
            tags=["combat", "exploration"],
            description="山林试炼区",
            access_rules={"combat_level": "apprentice"},
        ),
    ]
    for loc in locations:
        db.add(loc)
    db.commit()
    return locations


@pytest.fixture
def test_npc_templates(db: Session, test_world: WorldModel):
    """Create test NPC templates."""
    npcs = [
        NPCTemplateModel(
            id="npc_senior_sister",
            world_id=test_world.id,
            code="senior_sister",
            name="师姐凌月",
            role_type="mentor",
            personality="冷静",
        ),
    ]
    for npc in npcs:
        db.add(npc)
    db.commit()
    return npcs


@pytest.fixture
def test_quest_templates(db: Session, test_world: WorldModel):
    """Create test quest templates."""
    quests = [
        QuestTemplateModel(
            id="quest_first_trial",
            world_id=test_world.id,
            code="first_trial",
            name="初次试炼",
            quest_type="main",
            visibility="visible",
        ),
    ]
    for quest in quests:
        db.add(quest)
    db.commit()
    return quests


@pytest.fixture
def test_save_slot(db: Session, test_user: UserModel) -> SaveSlotModel:
    """Create a test save slot."""
    save_slot = SaveSlotModel(
        id="slot_1",
        user_id=test_user.id,
        slot_number=1,
        name="测试存档",
    )
    db.add(save_slot)
    db.commit()
    return save_slot


@pytest.fixture
def test_session(
    db: Session,
    test_user: UserModel,
    test_world: WorldModel,
    test_save_slot: SaveSlotModel,
) -> SessionModel:
    """Create a test session."""
    session = SessionModel(
        id="session_1",
        user_id=test_user.id,
        world_id=test_world.id,
        save_slot_id=test_save_slot.id,
        status="active",
    )
    db.add(session)
    db.commit()
    return session


@pytest.fixture
def test_session_state(
    db: Session,
    test_session: SessionModel,
) -> SessionStateModel:
    """Create a test session state."""
    state = SessionStateModel(
        id="state_1",
        session_id=test_session.id,
        current_time="修仙历 春 第1日 辰时",
        time_phase="辰时",
        current_location_id="loc_square",
        active_mode="exploration",
        global_flags_json={},
    )
    db.add(state)
    db.commit()
    return state


@pytest.fixture
def test_player_state(
    db: Session,
    test_session: SessionModel,
) -> SessionPlayerStateModel:
    """Create a test player state."""
    state = SessionPlayerStateModel(
        id="player_state_1",
        session_id=test_session.id,
        realm_stage="炼气一层",
        hp=100,
        max_hp=100,
        stamina=100,
        spirit_power=100,
    )
    db.add(state)
    db.commit()
    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTurnServiceHandlesInitialization:
    """Test that turn service initializes session state if needed."""
    
    def test_turn_service_creates_missing_session_state(
        self,
        db: Session,
        test_session: SessionModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that turn service creates missing session_state rows.
        
        Scenario:
        1. Session exists but has no session_state
        2. Execute turn
        3. Verify session_state is created
        """
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我观察四周",
        )
        
        assert result.turn_no == 1
        assert result.validation_passed is True
        
        session_state = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == test_session.id
        ).first()
        
        assert session_state is not None
        assert session_state.current_location_id is not None
    
    def test_turn_service_creates_missing_player_state(
        self,
        db: Session,
        test_session: SessionModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that turn service creates missing player_state rows.
        """
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我观察四周",
        )
        
        assert result.turn_no == 1
        
        player_state = db.query(SessionPlayerStateModel).filter(
            SessionPlayerStateModel.session_id == test_session.id
        ).first()
        
        assert player_state is not None
        assert player_state.realm_stage == "炼气一层"
    
    def test_turn_service_creates_missing_npc_states(
        self,
        db: Session,
        test_session: SessionModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that turn service creates missing NPC state rows.
        """
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我观察四周",
        )
        
        assert result.turn_no == 1
        
        npc_states = db.query(SessionNPCStateModel).filter(
            SessionNPCStateModel.session_id == test_session.id
        ).all()
        
        assert len(npc_states) == 1
        assert npc_states[0].npc_template_id == "npc_senior_sister"


class TestTurnServiceHandlesMovement:
    """Test that turn service handles movement correctly."""
    
    def test_turn_service_movement_updates_location(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that movement action updates session location.
        
        Scenario:
        1. Player is at square (loc_square)
        2. Execute turn with movement to trial_hall
        3. Verify location is updated to trial_hall
        """
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
        )
        
        assert result.turn_no == 1
        assert result.movement_result is not None
        assert result.movement_result.success is True
        assert result.movement_result.new_location_code == "trial_hall"
        
        session_state = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == test_session.id
        ).first()
        
        assert session_state.current_location_id == "loc_trial_hall"
    
    def test_turn_service_movement_persists_adventure_log(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that movement action persists adventure log entry.
        """
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
        )
        
        event = db.query(EventLogModel).filter(
            EventLogModel.session_id == test_session.id,
            EventLogModel.turn_no == 1,
            EventLogModel.event_type == "player_turn",
        ).first()
        
        assert event is not None
        assert event.input_text == "我去试炼堂"
        assert event.narrative_text is not None
        assert "试炼堂" in event.narrative_text or "你来到了" in event.narrative_text
    
    def test_turn_service_movement_generates_recommended_actions(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that turn service generates recommended actions.
        """
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
        )
        
        assert result.recommended_actions is not None
        assert len(result.recommended_actions) > 0


class TestGameAndStreamingTurnsPersistEquivalentSideEffects:
    """Test that game and streaming endpoints produce identical side effects."""
    
    def test_both_endpoints_produce_same_location_change(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that both endpoints produce the same location change.
        
        This simulates what would happen if both endpoints called
        execute_turn_service with the same input.
        """
        # Simulate first call (like /game endpoint)
        result1 = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
            idempotency_key="test_key_1",
        )
        
        location_after_first = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == test_session.id
        ).first().current_location_id
        
        # Reset location for second test
        test_session_state.current_location_id = "loc_square"
        db.commit()
        
        # Simulate second call (like /streaming endpoint)
        result2 = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
            idempotency_key="test_key_2",
        )
        
        location_after_second = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == test_session.id
        ).first().current_location_id
        
        # Both should produce the same location change
        assert location_after_first == "loc_trial_hall"
        assert location_after_second == "loc_trial_hall"
    
    def test_both_endpoints_produce_same_adventure_log(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that both endpoints produce the same adventure log entries.
        """
        # First call
        result1 = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
            idempotency_key="test_key_1",
        )
        
        event1 = db.query(EventLogModel).filter(
            EventLogModel.session_id == test_session.id,
            EventLogModel.turn_no == 1,
        ).first()
        
        # Second call with different idempotency key (turn 2)
        result2 = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
            idempotency_key="test_key_2",
        )
        
        event2 = db.query(EventLogModel).filter(
            EventLogModel.session_id == test_session.id,
            EventLogModel.turn_no == 2,
        ).first()
        
        # Both should have adventure log entries
        assert event1 is not None
        assert event2 is not None
        assert event1.input_text == "我去试炼堂"
        assert event2.input_text == "我去试炼堂"


class TestGameAndStreamingBlockedMoveDoNotMutateLocation:
    """Test that blocked movements do not mutate location."""
    
    def test_blocked_movement_does_not_update_location(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that blocked movement does not update session location.
        
        Scenario:
        1. Player is at square (loc_square)
        2. Try to move to forest (requires combat_level: apprentice)
        3. Movement is blocked
        4. Location should remain at square
        """
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去山林",
        )
        
        assert result.turn_no == 1
        assert result.movement_result is not None
        assert result.movement_result.success is False
        assert result.movement_result.blocked_reason is not None
        
        session_state = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == test_session.id
        ).first()
        
        assert session_state.current_location_id == "loc_square"
    
    def test_blocked_movement_still_creates_adventure_log(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that blocked movement still creates adventure log entry.
        
        Even blocked movements should be recorded for audit purposes.
        """
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去山林",
        )
        
        event = db.query(EventLogModel).filter(
            EventLogModel.session_id == test_session.id,
            EventLogModel.turn_no == 1,
            EventLogModel.event_type == "player_turn",
        ).first()
        
        assert event is not None
        assert event.input_text == "我去山林"
        
        result_json = event.result_json
        assert result_json is not None
        assert result_json.get("movement_success") is False
    
    def test_blocked_movement_state_deltas_contain_reason(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that blocked movement state deltas contain blocked reason.
        """
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去山林",
        )
        
        assert result.state_deltas is not None
        assert "blocked_reason" in result.state_deltas


class TestIdempotency:
    """Test idempotency key behavior."""
    
    def test_same_idempotency_key_returns_same_turn(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that same idempotency key returns the same turn.
        """
        # First call
        result1 = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
            idempotency_key="idem_key_1",
        )
        
        # Second call with same key
        result2 = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
            idempotency_key="idem_key_1",
        )
        
        assert result1.turn_no == result2.turn_no
        assert result2.is_new_turn is False
    
    def test_different_idempotency_keys_produce_different_turns(
        self,
        db: Session,
        test_session: SessionModel,
        test_session_state: SessionStateModel,
        test_player_state: SessionPlayerStateModel,
        test_locations,
        test_npc_templates,
        test_quest_templates,
    ):
        """
        Test that different idempotency keys produce different turns.
        """
        result1 = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
            idempotency_key="idem_key_1",
        )
        
        result2 = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
            idempotency_key="idem_key_2",
        )
        
        assert result1.turn_no == 1
        assert result2.turn_no == 2


class TestErrorHandling:
    """Test error handling."""
    
    def test_missing_session_raises_error(
        self,
        db: Session,
    ):
        """
        Test that missing session raises SessionNotFoundError.
        """
        with pytest.raises(SessionNotFoundError):
            execute_turn_service(
                db=db,
                session_id="nonexistent_session",
                player_input="我观察四周",
            )
    
    def test_turn_service_handles_missing_world_gracefully(
        self,
        db: Session,
        test_user: UserModel,
        test_save_slot: SaveSlotModel,
    ):
        """
        Test that turn service handles missing world gracefully.
        """
        session = SessionModel(
            id="session_no_world",
            user_id=test_user.id,
            world_id="nonexistent_world",
            save_slot_id=test_save_slot.id,
            status="active",
        )
        db.add(session)
        db.commit()
        
        with pytest.raises(TurnServiceError):
            execute_turn_service(
                db=db,
                session_id="session_no_world",
                player_input="我观察四周",
            )
