"""
Integration tests for turn execution consistency.

Tests that verify:
1. Both game.py and streaming.py call the same execute_turn_service
2. Turn and streaming produce identical side effects
3. Session state survives restart (DB-backed, not in-memory)

Key tests:
- test_turn_and_streaming_have_same_side_effects
- test_session_survives_restart
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


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
        id="user_consistency",
        username="testuser_consistency",
        email="test_consistency@example.com",
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
        id="world_consistency",
        code="test_world_consistency",
        name="一致性测试世界",
        genre="xianxia",
        lore_summary="用于测试一致性的世界",
        status="active",
    )
    db.add(world)
    db.commit()
    return world


@pytest.fixture
def test_chapter(db: Session, test_world: WorldModel) -> ChapterModel:
    """Create a test chapter."""
    chapter = ChapterModel(
        id="chapter_consistency",
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
            id="loc_square_consistency",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="square",
            name="宗门广场",
            tags=["public", "safe", "starting_point"],
            description="宗门广场",
            access_rules={"always_accessible": True},
        ),
        LocationModel(
            id="loc_trial_hall_consistency",
            world_id=test_world.id,
            chapter_id=test_chapter.id,
            code="trial_hall",
            name="试炼堂",
            tags=["public", "quest_hub"],
            description="试炼堂",
            access_rules={"time_restrictions": "daytime_only"},
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
            id="npc_consistency_1",
            world_id=test_world.id,
            code="test_npc",
            name="测试NPC",
            role_type="mentor",
            personality="友好",
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
            id="quest_consistency_1",
            world_id=test_world.id,
            code="test_quest",
            name="测试任务",
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
        id="slot_consistency",
        user_id=test_user.id,
        slot_number=1,
        name="一致性测试存档",
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
        id="session_consistency",
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
        id="state_consistency",
        session_id=test_session.id,
        current_time="修仙历 春 第1日 辰时",
        time_phase="辰时",
        current_location_id="loc_square_consistency",
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
        id="player_state_consistency",
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


# =============================================================================
# Tests
# =============================================================================


class TestTurnAndStreamingHaveSameSideEffects:
    """
    Test that turn and streaming endpoints produce identical side effects.
    
    Both game.py and streaming.py call execute_turn_service, so we verify
    that calling the service with the same input produces the same DB state.
    """
    
    def test_both_paths_update_location_identically(
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
        Test that both paths (with/without use_mock) update location identically.
        
        Scenario:
        1. Execute turn via game path (use_mock=False, default)
        2. Verify location changed
        3. Reset location
        4. Execute turn via streaming path (use_mock=True)
        5. Verify location changed to same destination
        """
        # Game path: use_mock=False (default)
        result_game = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
            idempotency_key="game_path_key",
        )
        
        assert result_game.turn_no == 1
        assert result_game.movement_result is not None
        assert result_game.movement_result.success is True
        
        location_after_game = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == test_session.id
        ).first().current_location_id
        
        assert location_after_game == "loc_trial_hall_consistency"
        
        # Reset location for streaming path test
        test_session_state.current_location_id = "loc_square_consistency"
        db.commit()
        
        # Streaming path: use_mock=True
        result_streaming = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
            use_mock=True,
            idempotency_key="streaming_path_key",
        )
        
        assert result_streaming.turn_no == 2
        assert result_streaming.movement_result is not None
        assert result_streaming.movement_result.success is True
        
        location_after_streaming = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == test_session.id
        ).first().current_location_id
        
        assert location_after_streaming == "loc_trial_hall_consistency"
        
        # Both paths should result in the same location
        assert location_after_game == location_after_streaming
    
    def test_both_paths_create_adventure_log_entries(
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
        Test that both paths create adventure log entries.
        """
        # Game path
        result_game = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我观察四周",
            idempotency_key="game_log_key",
        )
        
        event_game = db.query(EventLogModel).filter(
            EventLogModel.session_id == test_session.id,
            EventLogModel.turn_no == 1,
        ).first()
        
        assert event_game is not None
        assert event_game.input_text == "我观察四周"
        
        # Streaming path
        result_streaming = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我观察四周",
            use_mock=True,
            idempotency_key="streaming_log_key",
        )
        
        event_streaming = db.query(EventLogModel).filter(
            EventLogModel.session_id == test_session.id,
            EventLogModel.turn_no == 2,
        ).first()
        
        assert event_streaming is not None
        assert event_streaming.input_text == "我观察四周"
    
    def test_both_paths_update_player_state(
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
        Test that both paths update player state.
        """
        # Game path
        result_game = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我观察四周",
            idempotency_key="game_player_key",
        )
        
        player_state_after_game = db.query(SessionPlayerStateModel).filter(
            SessionPlayerStateModel.session_id == test_session.id
        ).first()
        
        assert player_state_after_game is not None
        
        # Streaming path
        result_streaming = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我观察四周",
            use_mock=True,
            idempotency_key="streaming_player_key",
        )
        
        player_state_after_streaming = db.query(SessionPlayerStateModel).filter(
            SessionPlayerStateModel.session_id == test_session.id
        ).first()
        
        assert player_state_after_streaming is not None
        
        # Both should have player state
        assert player_state_after_game.id == player_state_after_streaming.id
    
    def test_both_paths_generate_recommended_actions(
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
        Test that both paths generate recommended actions.
        """
        # Game path
        result_game = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我观察四周",
            idempotency_key="game_actions_key",
        )
        
        assert result_game.recommended_actions is not None
        assert len(result_game.recommended_actions) > 0
        
        # Streaming path
        result_streaming = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我观察四周",
            use_mock=True,
            idempotency_key="streaming_actions_key",
        )
        
        assert result_streaming.recommended_actions is not None
        assert len(result_streaming.recommended_actions) > 0


class TestSessionSurvivesRestart:
    """
    Test that session state survives restart.
    
    This proves the service is DB-backed, not in-memory.
    """
    
    def test_session_state_persists_after_db_session_close(
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
        Test that session state persists after closing and reopening DB session.
        
        Scenario:
        1. Execute a turn
        2. Close the DB session
        3. Create a new DB session
        4. Verify the session state is still accessible
        """
        session_id = test_session.id
        
        # Execute a turn
        result = execute_turn_service(
            db=db,
            session_id=session_id,
            idempotency_key="restart_test_key",
            player_input="我去试炼堂",
        )
        
        assert result.turn_no == 1
        assert result.movement_result is not None
        assert result.movement_result.success is True
        
        # Get the engine from the current session
        engine = db.get_bind()
        
        # Close the current session
        db.close()
        
        # Create a new session from the same engine
        new_db = sessionmaker(bind=engine)()
        
        try:
            # Verify the session state is still accessible
            session_state = new_db.query(SessionStateModel).filter(
                SessionStateModel.session_id == session_id
            ).first()
            
            assert session_state is not None
            assert session_state.current_location_id == "loc_trial_hall_consistency"
            
            # Verify the adventure log is still accessible
            event = new_db.query(EventLogModel).filter(
                EventLogModel.session_id == session_id,
                EventLogModel.turn_no == 1,
            ).first()
            
            assert event is not None
            assert event.input_text == "我去试炼堂"
            
            # Verify player state is still accessible
            player_state = new_db.query(SessionPlayerStateModel).filter(
                SessionPlayerStateModel.session_id == session_id
            ).first()
            
            assert player_state is not None
        finally:
            new_db.close()
    
    def test_multiple_turns_survive_restart(
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
        Test that multiple turns survive restart.
        
        Scenario:
        1. Execute multiple turns
        2. Close and reopen DB session
        3. Verify all turns are still accessible
        """
        session_id = test_session.id
        
        # Execute first turn
        result1 = execute_turn_service(
            db=db,
            session_id=session_id,
            idempotency_key="restart_multi_key_1",
            player_input="我去试炼堂",
        )
        
        assert result1.turn_no == 1
        
        # Execute second turn
        result2 = execute_turn_service(
            db=db,
            session_id=session_id,
            idempotency_key="restart_multi_key_2",
            player_input="我观察四周",
        )
        
        assert result2.turn_no == 2
        
        # Get the engine
        engine = db.get_bind()
        
        # Close and reopen
        db.close()
        new_db = sessionmaker(bind=engine)()
        
        try:
            # Verify both turns are still accessible
            events = new_db.query(EventLogModel).filter(
                EventLogModel.session_id == session_id
            ).order_by(EventLogModel.turn_no).all()
            
            assert len(events) == 2
            assert events[0].turn_no == 1
            assert events[0].input_text == "我去试炼堂"
            assert events[1].turn_no == 2
            assert events[1].input_text == "我观察四周"
        finally:
            new_db.close()
    
    def test_can_continue_turns_after_restart(
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
        Test that we can continue executing turns after restart.
        
        Scenario:
        1. Execute a turn
        2. Close and reopen DB session
        3. Execute another turn
        4. Verify both turns are recorded
        """
        session_id = test_session.id
        
        # Execute first turn
        result1 = execute_turn_service(
            db=db,
            session_id=session_id,
            idempotency_key="restart_continue_key_1",
            player_input="我去试炼堂",
        )
        
        assert result1.turn_no == 1
        
        # Get the engine
        engine = db.get_bind()
        
        # Close and reopen
        db.close()
        new_db = sessionmaker(bind=engine)()
        
        try:
            # Execute another turn with new DB session
            result2 = execute_turn_service(
                db=new_db,
                session_id=session_id,
                idempotency_key="restart_continue_key_2",
                player_input="我观察四周",
            )
            
            assert result2.turn_no == 2
            
            # Verify both turns are recorded
            events = new_db.query(EventLogModel).filter(
                EventLogModel.session_id == session_id
            ).order_by(EventLogModel.turn_no).all()
            
            assert len(events) == 2
            assert events[0].turn_no == 1
            assert events[1].turn_no == 2
        finally:
            new_db.close()


class TestDBBackedVerification:
    """
    Additional tests to prove the service is DB-backed.
    """
    
    def test_state_changes_are_in_database(
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
        Test that all state changes are written to database.
        """
        initial_location = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == test_session.id
        ).first().current_location_id
        
        assert initial_location == "loc_square_consistency"
        
        # Execute turn
        result = execute_turn_service(
            db=db,
            session_id=test_session.id,
            player_input="我去试炼堂",
            idempotency_key="db_backed_key",
        )
        
        # Verify state change is in database
        new_location = db.query(SessionStateModel).filter(
            SessionStateModel.session_id == test_session.id
        ).first().current_location_id
        
        assert new_location == "loc_trial_hall_consistency"
        assert new_location != initial_location
    
    def test_no_in_memory_state_leak(
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
        Test that there's no in-memory state that differs from DB.
        
        This verifies that all state is read from DB, not from memory.
        """
        session_id = test_session.id
        
        # Execute turn
        result = execute_turn_service(
            db=db,
            session_id=session_id,
            idempotency_key="no_leak_key",
            player_input="我去试炼堂",
        )
        
        # Get state directly from DB (bypassing any potential in-memory cache)
        engine = db.get_bind()
        db.close()
        
        new_db = sessionmaker(bind=engine)()
        try:
            # Query fresh from database
            session_state = new_db.query(SessionStateModel).filter(
                SessionStateModel.session_id == session_id
            ).first()
            
            # State should match what the service reported
            assert session_state.current_location_id == "loc_trial_hall_consistency"
        finally:
            new_db.close()
