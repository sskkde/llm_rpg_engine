"""
Integration tests for c1724b39-style regression scenarios.

Tests:
- Session with missing NPC/quest state is backfilled before turn
- After executing movement turn, persisted location changes
- Historical turn gaps do not reset or duplicate next turn
- Full progression from uninitialized state to successful movement
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
    NPCTemplateModel,
    QuestTemplateModel,
    UserModel,
    SaveSlotModel,
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
    SessionNPCStateModel,
    SessionQuestStateModel,
    EventLogModel,
)
from llm_rpg.core.session_initialization import (
    initialize_session_story_state,
    backfill_historical_sessions,
)
from llm_rpg.core.turn_service import (
    execute_turn_service,
    TurnResult,
    SessionNotFoundError,
)
from llm_rpg.core.movement_handler import handle_movement


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
def test_world(db: Session) -> WorldModel:
    """Create a test world."""
    world = WorldModel(
        id="test_world_c1724b39",
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
        id="test_chapter_c1724b39",
        world_id=test_world.id,
        chapter_no=1,
        name="第一章",
        summary="测试章节",
    )
    db.add(chapter)
    db.commit()
    return chapter


@pytest.fixture
def test_locations(db: Session, test_world: WorldModel, test_chapter: ChapterModel) -> dict:
    """Create test locations."""
    square = LocationModel(
        id="loc_square_c1724b39",
        world_id=test_world.id,
        chapter_id=test_chapter.id,
        code="square",
        name="宗门广场",
        tags=["public", "safe", "starting_point"],
        description="起始地点",
        access_rules={"always_accessible": True},
    )
    trial_hall = LocationModel(
        id="loc_trial_hall_c1724b39",
        world_id=test_world.id,
        chapter_id=test_chapter.id,
        code="trial_hall",
        name="试炼堂",
        tags=["public", "quest_hub"],
        description="试炼堂",
        access_rules={"time_restrictions": "daytime_only"},
    )
    forest = LocationModel(
        id="loc_forest_c1724b39",
        world_id=test_world.id,
        chapter_id=test_chapter.id,
        code="forest",
        name="山林试炼区",
        tags=["combat", "exploration"],
        description="山林试炼区",
        access_rules={},
    )
    db.add_all([square, trial_hall, forest])
    db.commit()
    return {"square": square, "trial_hall": trial_hall, "forest": forest}


@pytest.fixture
def test_npc_templates(db: Session, test_world: WorldModel) -> dict:
    """Create test NPC templates."""
    npc1 = NPCTemplateModel(
        id="npc_senior_c1724b39",
        world_id=test_world.id,
        code="senior_sister",
        name="柳师姐",
        role_type="guide",
        public_identity="外门师姐",
        hidden_identity="内门使者",
        personality="温和",
        speech_style="温婉",
        goals=["帮助新弟子"],
    )
    npc2 = NPCTemplateModel(
        id="npc_rival_c1724b39",
        world_id=test_world.id,
        code="male_competitor",
        name="江程",
        role_type="rival",
        public_identity="同期弟子",
        hidden_identity="潜在盟友",
        personality="自负",
        speech_style="豪爽",
        goals=["成为内门弟子"],
    )
    db.add_all([npc1, npc2])
    db.commit()
    return {"senior": npc1, "rival": npc2}


@pytest.fixture
def test_quest_templates(db: Session, test_world: WorldModel) -> dict:
    """Create test quest templates."""
    quest1 = QuestTemplateModel(
        id="quest_first_trial_c1724b39",
        world_id=test_world.id,
        code="first_trial",
        name="初次试炼",
        quest_type="main",
        summary="完成第一次试炼",
        visibility="visible",
    )
    quest2 = QuestTemplateModel(
        id="quest_investigate_c1724b39",
        world_id=test_world.id,
        code="investigate_anomaly",
        name="调查异变",
        quest_type="main",
        summary="调查异变真相",
        visibility="hidden",
    )
    quest3 = QuestTemplateModel(
        id="quest_side_c1724b39",
        world_id=test_world.id,
        code="help_senior",
        name="师姐的请求",
        quest_type="side",
        summary="帮助师姐",
        visibility="visible",
    )
    db.add_all([quest1, quest2, quest3])
    db.commit()
    return {"first_trial": quest1, "investigate": quest2, "side": quest3}


@pytest.fixture
def test_user(db: Session) -> UserModel:
    """Create a test user."""
    user = UserModel(
        id="user_c1724b39",
        username="testuser_c1724b39",
        email="test_c1724b39@example.com",
        password_hash="hashed",
        is_admin=False,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def test_save_slot(db: Session, test_user: UserModel) -> SaveSlotModel:
    """Create a test save slot."""
    slot = SaveSlotModel(
        id="slot_c1724b39",
        user_id=test_user.id,
        slot_number=1,
        name="测试存档",
    )
    db.add(slot)
    db.commit()
    return slot


# ---------------------------------------------------------------------------
# Test: c1724b39-shaped session backfills and advances
# ---------------------------------------------------------------------------


class TestC1724b39ShapedSessionBackfillsAndAdvances:
    """
    Regression test for c1724b39-style failure shape.
    
    Scenario:
    1. Active session exists with partial event logs
    2. No NPC/quest state rows exist
    3. Backfill is triggered before turn execution
    4. Movement turn executes successfully
    5. Persisted location changes
    """
    
    def test_c1724b39_shaped_session_backfills_and_advances(
        self,
        db: Session,
        test_user: UserModel,
        test_save_slot: SaveSlotModel,
        test_world: WorldModel,
        test_locations: dict,
        test_npc_templates: dict,
        test_quest_templates: dict,
    ):
        """
        Full regression test matching c1724b39 failure shape.
        
        Steps:
        1. Create session with partial state (missing NPC/quest rows)
        2. Create some event logs (simulating historical turns)
        3. Verify NPC/quest state is missing
        4. Execute turn (which triggers backfill internally)
        5. Verify backfill created missing rows
        6. Verify movement succeeded and location changed
        """
        # Step 1: Create session with partial state
        session = SessionModel(
            id="session_c1724b39_regression",
            user_id=test_user.id,
            save_slot_id=test_save_slot.id,
            world_id=test_world.id,
            current_chapter_id=test_chapter.id if 'test_chapter' in dir() else None,
            status="active",
        )
        db.add(session)
        db.commit()
        
        # Create session state with initial location
        session_state = SessionStateModel(
            id="state_c1724b39",
            session_id=session.id,
            current_time="修仙历 春 第1日 辰时",
            time_phase="辰时",
            current_location_id=test_locations["square"].id,
            active_mode="exploration",
            global_flags_json={},
        )
        db.add(session_state)
        
        # Create player state
        player_state = SessionPlayerStateModel(
            id="player_state_c1724b39",
            session_id=session.id,
            realm_stage="炼气一层",
            hp=100,
            max_hp=100,
            stamina=100,
            spirit_power=100,
        )
        db.add(player_state)
        db.commit()
        
        # Step 2: Create some historical event logs (turns 1-2)
        event1 = EventLogModel(
            id="event_c1724b39_1",
            session_id=session.id,
            turn_no=1,
            event_type="player_turn",
            input_text="观察四周",
            narrative_text="你环顾四周，发现自己站在宗门广场上。",
            result_json={"action_type": "inspect"},
        )
        event2 = EventLogModel(
            id="event_c1724b39_2",
            session_id=session.id,
            turn_no=2,
            event_type="player_turn",
            input_text="与师姐交谈",
            narrative_text="你与柳师姐交谈了几句。",
            result_json={"action_type": "talk"},
        )
        db.add_all([event1, event2])
        db.commit()
        
        # Step 3: Verify NPC/quest state is missing (c1724b39 failure shape)
        assert db.query(SessionNPCStateModel).filter_by(session_id=session.id).count() == 0
        assert db.query(SessionQuestStateModel).filter_by(session_id=session.id).count() == 0
        
        # Step 4: Execute turn (triggers backfill internally via turn_service)
        result = execute_turn_service(
            db=db,
            session_id=session.id,
            player_input="前往试炼堂",
        )
        
        # Step 5: Verify backfill created missing rows
        npc_states = db.query(SessionNPCStateModel).filter_by(session_id=session.id).all()
        assert len(npc_states) == 2  # Both NPC templates
        
        quest_states = db.query(SessionQuestStateModel).filter_by(session_id=session.id).all()
        assert len(quest_states) == 2  # Two visible quests (first_trial, side)
        
        # Step 6: Verify movement succeeded
        assert result.turn_no == 3  # Next turn after historical turns
        assert result.movement_result is not None
        assert result.movement_result.success is True
        assert result.movement_result.new_location_code == "trial_hall"
        
        # Verify persisted location changed
        updated_state = db.query(SessionStateModel).filter_by(session_id=session.id).first()
        assert updated_state.current_location_id == test_locations["trial_hall"].id
        
        # Verify event log was created
        event_count = db.query(EventLogModel).filter_by(session_id=session.id).count()
        assert event_count == 3  # 2 historical + 1 new


# ---------------------------------------------------------------------------
# Test: Historical turn gap does not reset or duplicate next turn
# ---------------------------------------------------------------------------


class TestHistoricalTurnGapHandling:
    """
    Test that gaps in historical turn numbers don't cause issues.
    
    Scenario:
    1. Session has event logs with gaps (turns 1, 3, 5)
    2. Next turn should be 6 (max + 1), not reset or duplicate
    """
    
    def test_existing_historical_turn_gap_does_not_reset_or_duplicate_next_turn(
        self,
        db: Session,
        test_user: UserModel,
        test_save_slot: SaveSlotModel,
        test_world: WorldModel,
        test_locations: dict,
        test_npc_templates: dict,
        test_quest_templates: dict,
    ):
        """
        Test that turn allocation handles gaps correctly.
        
        Steps:
        1. Create session with gapped event logs (turns 1, 3, 5)
        2. Execute turn
        3. Verify next turn is 6 (not reset to 2 or duplicate 5)
        """
        # Create session
        session = SessionModel(
            id="session_turn_gap_test",
            user_id=test_user.id,
            save_slot_id=test_save_slot.id,
            world_id=test_world.id,
            status="active",
        )
        db.add(session)
        db.commit()
        
        # Create session state
        session_state = SessionStateModel(
            id="state_turn_gap",
            session_id=session.id,
            current_time="修仙历 春 第1日 辰时",
            time_phase="辰时",
            current_location_id=test_locations["square"].id,
            active_mode="exploration",
            global_flags_json={},
        )
        db.add(session_state)
        
        # Create player state
        player_state = SessionPlayerStateModel(
            id="player_state_turn_gap",
            session_id=session.id,
            realm_stage="炼气一层",
            hp=100,
            max_hp=100,
            stamina=100,
            spirit_power=100,
        )
        db.add(player_state)
        db.commit()
        
        # Create gapped event logs (turns 1, 3, 5)
        event1 = EventLogModel(
            id="event_gap_1",
            session_id=session.id,
            turn_no=1,
            event_type="player_turn",
            input_text="观察",
            narrative_text="Turn 1",
            result_json={},
        )
        event3 = EventLogModel(
            id="event_gap_3",
            session_id=session.id,
            turn_no=3,
            event_type="player_turn",
            input_text="移动",
            narrative_text="Turn 3",
            result_json={},
        )
        event5 = EventLogModel(
            id="event_gap_5",
            session_id=session.id,
            turn_no=5,
            event_type="player_turn",
            input_text="等待",
            narrative_text="Turn 5",
            result_json={},
        )
        db.add_all([event1, event3, event5])
        db.commit()
        
        # Execute turn
        result = execute_turn_service(
            db=db,
            session_id=session.id,
            player_input="前往山林",
        )
        
        # Verify turn number is 6 (max + 1)
        assert result.turn_no == 6
        
        # Verify no duplicate turns were created
        turn_6_events = db.query(EventLogModel).filter(
            EventLogModel.session_id == session.id,
            EventLogModel.turn_no == 6,
        ).all()
        assert len(turn_6_events) == 1
        
        # Verify gaps still exist (not filled)
        turn_2_events = db.query(EventLogModel).filter(
            EventLogModel.session_id == session.id,
            EventLogModel.turn_no == 2,
        ).all()
        assert len(turn_2_events) == 0
        
        turn_4_events = db.query(EventLogModel).filter(
            EventLogModel.session_id == session.id,
            EventLogModel.turn_no == 4,
        ).all()
        assert len(turn_4_events) == 0


# ---------------------------------------------------------------------------
# Test: Backfill before movement ensures state consistency
# ---------------------------------------------------------------------------


class TestBackfillBeforeMovement:
    """
    Test that backfill happens before movement execution.
    
    This ensures that movement validation has access to complete state.
    """
    
    def test_backfill_creates_state_before_movement_validation(
        self,
        db: Session,
        test_user: UserModel,
        test_save_slot: SaveSlotModel,
        test_world: WorldModel,
        test_locations: dict,
        test_npc_templates: dict,
        test_quest_templates: dict,
    ):
        """
        Test that NPC/quest state exists before movement is validated.
        
        This prevents issues where movement validation depends on
        state that doesn't exist yet.
        """
        # Create session WITHOUT any state
        session = SessionModel(
            id="session_backfill_before_move",
            user_id=test_user.id,
            save_slot_id=test_save_slot.id,
            world_id=test_world.id,
            status="active",
        )
        db.add(session)
        db.commit()
        
        # Verify no state exists
        assert db.query(SessionStateModel).filter_by(session_id=session.id).first() is None
        assert db.query(SessionPlayerStateModel).filter_by(session_id=session.id).first() is None
        assert db.query(SessionNPCStateModel).filter_by(session_id=session.id).count() == 0
        assert db.query(SessionQuestStateModel).filter_by(session_id=session.id).count() == 0
        
        # Execute turn (should trigger backfill)
        result = execute_turn_service(
            db=db,
            session_id=session.id,
            player_input="前往试炼堂",
        )
        
        # Verify state was created
        assert db.query(SessionStateModel).filter_by(session_id=session.id).first() is not None
        assert db.query(SessionPlayerStateModel).filter_by(session_id=session.id).first() is not None
        assert db.query(SessionNPCStateModel).filter_by(session_id=session.id).count() == 2
        assert db.query(SessionQuestStateModel).filter_by(session_id=session.id).count() == 2
        
        # Verify movement executed
        assert result.movement_result is not None
        assert result.movement_result.success is True


# ---------------------------------------------------------------------------
# Test: Multiple sequential movements with backfill
# ---------------------------------------------------------------------------


class TestSequentialMovementsWithBackfill:
    """
    Test multiple sequential movements after backfill.
    
    This ensures that backfill doesn't interfere with subsequent turns.
    """
    
    def test_sequential_movements_after_backfill(
        self,
        db: Session,
        test_user: UserModel,
        test_save_slot: SaveSlotModel,
        test_world: WorldModel,
        test_locations: dict,
        test_npc_templates: dict,
        test_quest_templates: dict,
    ):
        """
        Test that multiple movements work correctly after backfill.
        """
        # Create session without state
        session = SessionModel(
            id="session_sequential_moves",
            user_id=test_user.id,
            save_slot_id=test_save_slot.id,
            world_id=test_world.id,
            status="active",
        )
        db.add(session)
        db.commit()
        
        # Execute first turn (triggers backfill)
        result1 = execute_turn_service(
            db=db,
            session_id=session.id,
            player_input="前往试炼堂",
        )
        
        assert result1.turn_no == 1
        assert result1.movement_result.success is True
        assert result1.movement_result.new_location_code == "trial_hall"
        
        # Execute second turn
        result2 = execute_turn_service(
            db=db,
            session_id=session.id,
            player_input="前往宗门广场",
        )
        
        assert result2.turn_no == 2
        assert result2.movement_result.success is True
        assert result2.movement_result.new_location_code == "square"
        
        # Execute third turn
        result3 = execute_turn_service(
            db=db,
            session_id=session.id,
            player_input="前往山林",
        )
        
        assert result3.turn_no == 3
        assert result3.movement_result.success is True
        assert result3.movement_result.new_location_code == "forest"
        
        # Verify final location
        final_state = db.query(SessionStateModel).filter_by(session_id=session.id).first()
        assert final_state.current_location_id == test_locations["forest"].id
        
        # Verify all events were logged
        event_count = db.query(EventLogModel).filter_by(session_id=session.id).count()
        assert event_count == 3


# ---------------------------------------------------------------------------
# Test: Backfill is idempotent
# ---------------------------------------------------------------------------


class TestBackfillIdempotencyInRegression:
    """
    Test that backfill doesn't create duplicate rows when run multiple times.
    """
    
    def test_backfill_idempotent_in_regression_scenario(
        self,
        db: Session,
        test_user: UserModel,
        test_save_slot: SaveSlotModel,
        test_world: WorldModel,
        test_locations: dict,
        test_npc_templates: dict,
        test_quest_templates: dict,
    ):
        """
        Test that running backfill multiple times doesn't create duplicates.
        """
        # Create session
        session = SessionModel(
            id="session_idempotent_backfill",
            user_id=test_user.id,
            save_slot_id=test_save_slot.id,
            world_id=test_world.id,
            status="active",
        )
        db.add(session)
        db.commit()
        
        # Run backfill twice
        initialize_session_story_state(db, session.id)
        initialize_session_story_state(db, session.id)
        
        # Verify no duplicates
        assert db.query(SessionStateModel).filter_by(session_id=session.id).count() == 1
        assert db.query(SessionPlayerStateModel).filter_by(session_id=session.id).count() == 1
        assert db.query(SessionNPCStateModel).filter_by(session_id=session.id).count() == 2
        assert db.query(SessionQuestStateModel).filter_by(session_id=session.id).count() == 2


# ---------------------------------------------------------------------------
# Test: Event log consistency after backfill and movement
# ---------------------------------------------------------------------------


class TestEventLogConsistencyAfterBackfill:
    """
    Test that event logs are consistent after backfill and movement.
    """
    
    def test_event_log_consistency(
        self,
        db: Session,
        test_user: UserModel,
        test_save_slot: SaveSlotModel,
        test_world: WorldModel,
        test_locations: dict,
        test_npc_templates: dict,
        test_quest_templates: dict,
    ):
        """
        Test that event logs correctly record movement after backfill.
        """
        # Create session with historical events
        session = SessionModel(
            id="session_event_consistency",
            user_id=test_user.id,
            save_slot_id=test_save_slot.id,
            world_id=test_world.id,
            status="active",
        )
        db.add(session)
        db.commit()
        
        # Create historical event
        event1 = EventLogModel(
            id="event_consistency_1",
            session_id=session.id,
            turn_no=1,
            event_type="player_turn",
            input_text="观察",
            narrative_text="Turn 1",
            result_json={"action_type": "inspect"},
        )
        db.add(event1)
        db.commit()
        
        # Execute movement turn
        result = execute_turn_service(
            db=db,
            session_id=session.id,
            player_input="前往试炼堂",
        )
        
        # Verify event log entry
        event2 = db.query(EventLogModel).filter(
            EventLogModel.session_id == session.id,
            EventLogModel.turn_no == 2,
        ).first()
        
        assert event2 is not None
        assert event2.event_type == "player_turn"
        assert event2.input_text == "前往试炼堂"
        assert event2.result_json is not None
        assert event2.result_json.get("movement_success") is True
        assert event2.result_json.get("new_location_id") == test_locations["trial_hall"].id
