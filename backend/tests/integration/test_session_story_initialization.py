"""
Integration tests for session story state initialization.

Tests the session_initializer/backfill path that ensures every active session
has required baseline rows before turn execution.
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
)
from llm_rpg.core.session_initialization import (
    initialize_session_story_state,
    backfill_historical_sessions,
    SessionInitializationError,
)


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
        id="test_world_1",
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
        id="test_chapter_1",
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
        id="loc_square",
        world_id=test_world.id,
        chapter_id=test_chapter.id,
        code="square",
        name="宗门广场",
        tags=["public", "safe", "starting_point"],
        description="起始地点",
    )
    forest = LocationModel(
        id="loc_forest",
        world_id=test_world.id,
        chapter_id=test_chapter.id,
        code="forest",
        name="山林",
        tags=["combat"],
        description="战斗区域",
    )
    db.add_all([square, forest])
    db.commit()
    return {"square": square, "forest": forest}


@pytest.fixture
def test_npc_templates(db: Session, test_world: WorldModel) -> dict:
    """Create test NPC templates."""
    npc1 = NPCTemplateModel(
        id="npc_senior",
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
        id="npc_rival",
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
        id="quest_first_trial",
        world_id=test_world.id,
        code="first_trial",
        name="初次试炼",
        quest_type="main",
        summary="完成第一次试炼",
        visibility="visible",
    )
    quest2 = QuestTemplateModel(
        id="quest_investigate",
        world_id=test_world.id,
        code="investigate_anomaly",
        name="调查异变",
        quest_type="main",
        summary="调查异变真相",
        visibility="hidden",
    )
    quest3 = QuestTemplateModel(
        id="quest_side",
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
def test_save_slot(db: Session, test_user: UserModel) -> SaveSlotModel:
    """Create a test save slot."""
    slot = SaveSlotModel(
        id="slot_1",
        user_id=test_user.id,
        slot_number=1,
        name="测试存档",
    )
    db.add(slot)
    db.commit()
    return slot


@pytest.fixture
def test_session(db: Session, test_user: UserModel, test_save_slot: SaveSlotModel, test_world: WorldModel) -> SessionModel:
    """Create a test session."""
    session = SessionModel(
        id="session_1",
        user_id=test_user.id,
        save_slot_id=test_save_slot.id,
        world_id=test_world.id,
        status="active",
    )
    db.add(session)
    db.commit()
    return session


class TestNewSessionInitialization:
    """Test that new sessions get all baseline rows."""
    
    def test_new_session_initializes_story_state(
        self,
        db: Session,
        test_session: SessionModel,
        test_locations: dict,
        test_npc_templates: dict,
        test_quest_templates: dict,
    ):
        """New session should get all baseline rows after initialization."""
        session_id = test_session.id
        
        assert db.query(SessionStateModel).filter_by(session_id=session_id).count() == 0
        assert db.query(SessionPlayerStateModel).filter_by(session_id=session_id).count() == 0
        assert db.query(SessionNPCStateModel).filter_by(session_id=session_id).count() == 0
        assert db.query(SessionQuestStateModel).filter_by(session_id=session_id).count() == 0
        
        initialize_session_story_state(db, session_id)
        
        session_state = db.query(SessionStateModel).filter_by(session_id=session_id).first()
        assert session_state is not None
        assert session_state.current_location_id == test_locations["square"].id
        assert session_state.active_mode == "exploration"
        
        player_state = db.query(SessionPlayerStateModel).filter_by(session_id=session_id).first()
        assert player_state is not None
        assert player_state.realm_stage == "炼气一层"
        assert player_state.hp == 100
        assert player_state.spirit_power == 100
        
        npc_states = db.query(SessionNPCStateModel).filter_by(session_id=session_id).all()
        assert len(npc_states) == 2
        npc_template_ids = {ns.npc_template_id for ns in npc_states}
        assert test_npc_templates["senior"].id in npc_template_ids
        assert test_npc_templates["rival"].id in npc_template_ids
        
        for ns in npc_states:
            assert ns.trust_score == 50
            assert ns.suspicion_score == 0
        
        quest_states = db.query(SessionQuestStateModel).filter_by(session_id=session_id).all()
        assert len(quest_states) == 2
        quest_template_ids = {qs.quest_template_id for qs in quest_states}
        assert test_quest_templates["first_trial"].id in quest_template_ids
        assert test_quest_templates["side"].id in quest_template_ids
        assert test_quest_templates["investigate"].id not in quest_template_ids
        
        for qs in quest_states:
            assert qs.status == "active"
            assert qs.current_step_no == 1


class TestIdempotency:
    """Test that running initialization twice is idempotent."""
    
    def test_backfill_existing_session_is_idempotent(
        self,
        db: Session,
        test_session: SessionModel,
        test_locations: dict,
        test_npc_templates: dict,
        test_quest_templates: dict,
    ):
        """Running initialization twice should leave row counts unchanged."""
        session_id = test_session.id
        
        initialize_session_story_state(db, session_id)
        
        session_state_count = db.query(SessionStateModel).filter_by(session_id=session_id).count()
        player_state_count = db.query(SessionPlayerStateModel).filter_by(session_id=session_id).count()
        npc_state_count = db.query(SessionNPCStateModel).filter_by(session_id=session_id).count()
        quest_state_count = db.query(SessionQuestStateModel).filter_by(session_id=session_id).count()
        
        assert session_state_count == 1
        assert player_state_count == 1
        assert npc_state_count == 2
        assert quest_state_count == 2
        
        initialize_session_story_state(db, session_id)
        
        assert db.query(SessionStateModel).filter_by(session_id=session_id).count() == session_state_count
        assert db.query(SessionPlayerStateModel).filter_by(session_id=session_id).count() == player_state_count
        assert db.query(SessionNPCStateModel).filter_by(session_id=session_id).count() == npc_state_count
        assert db.query(SessionQuestStateModel).filter_by(session_id=session_id).count() == quest_state_count


class TestHistoricalBackfill:
    """Test backfill of historical sessions."""
    
    def test_historical_session_backfill_populates_missing_rows(
        self,
        db: Session,
        test_user: UserModel,
        test_save_slot: SaveSlotModel,
        test_world: WorldModel,
        test_locations: dict,
        test_npc_templates: dict,
        test_quest_templates: dict,
    ):
        """Old session with missing rows should get backfilled."""
        session1 = SessionModel(
            id="old_session_1",
            user_id=test_user.id,
            save_slot_id=test_save_slot.id,
            world_id=test_world.id,
            status="active",
        )
        session2 = SessionModel(
            id="old_session_2",
            user_id=test_user.id,
            save_slot_id=test_save_slot.id,
            world_id=test_world.id,
            status="active",
        )
        db.add_all([session1, session2])
        db.commit()
        
        assert db.query(SessionStateModel).filter_by(session_id=session1.id).count() == 0
        assert db.query(SessionPlayerStateModel).filter_by(session_id=session2.id).count() == 0
        
        backfill_count = backfill_historical_sessions(db)
        
        assert backfill_count == 2
        
        assert db.query(SessionStateModel).filter_by(session_id=session1.id).count() == 1
        assert db.query(SessionPlayerStateModel).filter_by(session_id=session1.id).count() == 1
        assert db.query(SessionNPCStateModel).filter_by(session_id=session1.id).count() == 2
        assert db.query(SessionQuestStateModel).filter_by(session_id=session1.id).count() == 2
        
        assert db.query(SessionStateModel).filter_by(session_id=session2.id).count() == 1
        assert db.query(SessionPlayerStateModel).filter_by(session_id=session2.id).count() == 1
        assert db.query(SessionNPCStateModel).filter_by(session_id=session2.id).count() == 2
        assert db.query(SessionQuestStateModel).filter_by(session_id=session2.id).count() == 2
    
    def test_backfill_handles_orphan_sessions_gracefully(
        self,
        db: Session,
        test_user: UserModel,
        test_save_slot: SaveSlotModel,
        test_world: WorldModel,
    ):
        """Backfill should handle sessions with missing world content gracefully."""
        session = SessionModel(
            id="orphan_session",
            user_id=test_user.id,
            save_slot_id=test_save_slot.id,
            world_id="nonexistent_world",
            status="active",
        )
        db.add(session)
        db.commit()
        
        backfill_count = backfill_historical_sessions(db)
        
        assert backfill_count == 1
        
        assert db.query(SessionStateModel).filter_by(session_id=session.id).count() == 1
        assert db.query(SessionPlayerStateModel).filter_by(session_id=session.id).count() == 1
        assert db.query(SessionNPCStateModel).filter_by(session_id=session.id).count() == 0
        assert db.query(SessionQuestStateModel).filter_by(session_id=session.id).count() == 0


class TestErrorHandling:
    """Test error handling for session initialization."""
    
    def test_initialize_raises_for_nonexistent_session(self, db: Session):
        """Should raise SessionInitializationError for nonexistent session."""
        with pytest.raises(SessionInitializationError) as exc_info:
            initialize_session_story_state(db, "nonexistent_session")
        
        assert exc_info.value.session_id == "nonexistent_session"
        assert "not found" in str(exc_info.value)
