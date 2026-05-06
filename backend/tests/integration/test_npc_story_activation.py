"""
Integration tests for NPC story activation bridge.

Tests the npc_state_bridge module that creates NPCState and NPCMemoryScope
from database models, ensuring NPCs can participate in scene actions.
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
    UserModel,
    SaveSlotModel,
    SessionModel,
    SessionNPCStateModel,
)
from llm_rpg.core.npc_state_bridge import (
    NPCStateWithScope,
    build_npc_state_from_db,
    get_active_npcs_at_location,
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
    """Create test NPC templates with hidden identities."""
    elder = NPCTemplateModel(
        id="npc_elder",
        world_id=test_world.id,
        code="elder",
        name="长老",
        role_type="mentor",
        public_identity="宗门长老，德高望重",
        hidden_identity="实际上是魔教卧底",
        personality="严厉,正直,关心弟子",
        speech_style="文言文",
        goals=[
            {"id": "goal_1", "description": "保护宗门", "priority": 0.8},
            {"id": "goal_2", "description": "隐藏身份", "priority": 0.9},
        ],
    )
    merchant = NPCTemplateModel(
        id="npc_merchant",
        world_id=test_world.id,
        code="merchant",
        name="商人",
        role_type="trader",
        public_identity="行脚商人",
        hidden_identity=None,
        personality="精明,友好",
        speech_style="口语化",
        goals=[{"id": "goal_3", "description": "赚钱", "priority": 0.7}],
    )
    db.add_all([elder, merchant])
    db.commit()
    return {"elder": elder, "merchant": merchant}


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
def test_session(
    db: Session,
    test_user: UserModel,
    test_save_slot: SaveSlotModel,
    test_world: WorldModel,
    test_chapter: ChapterModel,
) -> SessionModel:
    """Create a test session."""
    session = SessionModel(
        id="session_1",
        user_id=test_user.id,
        save_slot_id=test_save_slot.id,
        world_id=test_world.id,
        current_chapter_id=test_chapter.id,
        status="active",
    )
    db.add(session)
    db.commit()
    return session


@pytest.fixture
def test_session_npc_states(
    db: Session,
    test_session: SessionModel,
    test_npc_templates: dict,
    test_locations: dict,
) -> dict:
    """Create test session NPC states."""
    elder_state = SessionNPCStateModel(
        id="snpc_elder",
        session_id=test_session.id,
        npc_template_id=test_npc_templates["elder"].id,
        current_location_id=test_locations["square"].id,
        trust_score=60,
        suspicion_score=10,
        status_flags={},
    )
    merchant_state = SessionNPCStateModel(
        id="snpc_merchant",
        session_id=test_session.id,
        npc_template_id=test_npc_templates["merchant"].id,
        current_location_id=test_locations["forest"].id,
        trust_score=50,
        suspicion_score=0,
        status_flags={},
    )
    db.add_all([elder_state, merchant_state])
    db.commit()
    return {"elder": elder_state, "merchant": merchant_state}


def test_backfill_creates_npc_state_and_scope(
    db: Session,
    test_session: SessionModel,
    test_npc_templates: dict,
    test_session_npc_states: dict,
):
    """NPC action path works after bridge creates state and scope."""
    result = build_npc_state_from_db(
        db=db,
        session_id=test_session.id,
        npc_template_id=test_npc_templates["elder"].id,
    )
    
    assert result is not None
    assert isinstance(result, NPCStateWithScope)
    assert result.npc_state is not None
    assert result.memory_scope is not None
    
    assert result.npc_state.npc_id == test_npc_templates["elder"].id
    assert result.npc_state.name == "长老"
    assert result.npc_state.status == "alive"
    assert result.npc_state.location_id == "loc_square"
    
    assert result.memory_scope.npc_id == test_npc_templates["elder"].id
    assert result.memory_scope.profile.name == "长老"
    assert len(result.memory_scope.goals.goals) == 2


def test_player_narration_does_not_leak_hidden_identity(
    db: Session,
    test_session: SessionModel,
    test_npc_templates: dict,
    test_session_npc_states: dict,
):
    """Hidden identity is stored separately and not in player-visible state."""
    result = build_npc_state_from_db(
        db=db,
        session_id=test_session.id,
        npc_template_id=test_npc_templates["elder"].id,
    )
    
    assert result is not None
    
    assert result.hidden_identity == "实际上是魔教卧底"
    
    assert result.npc_state.name == "长老"
    assert result.npc_state.mood in ["friendly", "warm", "neutral", "wary", "suspicious", "cold"]
    
    assert len(result.memory_scope.secrets.secrets) == 1
    assert result.memory_scope.secrets.secrets[0].content == "实际上是魔教卧底"
    assert result.memory_scope.secrets.secrets[0].willingness_to_reveal == 0.1
    
    merchant_result = build_npc_state_from_db(
        db=db,
        session_id=test_session.id,
        npc_template_id=test_npc_templates["merchant"].id,
    )
    assert merchant_result is not None
    assert merchant_result.hidden_identity is None
    assert len(merchant_result.memory_scope.secrets.secrets) == 0


def test_npcs_at_location_filtered(
    db: Session,
    test_session: SessionModel,
    test_locations: dict,
    test_npc_templates: dict,
    test_session_npc_states: dict,
):
    """Only NPCs at the specified location are returned."""
    square_npcs = get_active_npcs_at_location(
        db=db,
        session_id=test_session.id,
        location_id=test_locations["square"].id,
    )
    
    assert len(square_npcs) == 1
    assert square_npcs[0].npc_state.npc_id == test_npc_templates["elder"].id
    assert square_npcs[0].npc_state.name == "长老"
    
    forest_npcs = get_active_npcs_at_location(
        db=db,
        session_id=test_session.id,
        location_id=test_locations["forest"].id,
    )
    
    assert len(forest_npcs) == 1
    assert forest_npcs[0].npc_state.npc_id == test_npc_templates["merchant"].id
    assert forest_npcs[0].npc_state.name == "商人"
    
    empty_location_npcs = get_active_npcs_at_location(
        db=db,
        session_id=test_session.id,
        location_id="nonexistent_location",
    )
    
    assert len(empty_location_npcs) == 0


def test_missing_npc_template_handled(
    db: Session,
    test_session: SessionModel,
):
    """Gracefully handle missing NPC template."""
    result = build_npc_state_from_db(
        db=db,
        session_id=test_session.id,
        npc_template_id="nonexistent_template",
    )
    
    assert result is None


def test_missing_session_npc_state_handled(
    db: Session,
    test_session: SessionModel,
    test_npc_templates: dict,
):
    """Gracefully handle missing session NPC state."""
    new_npc = NPCTemplateModel(
        id="npc_new",
        world_id=test_session.world_id,
        code="new_npc",
        name="新NPC",
        role_type="minor",
        public_identity="新角色",
        hidden_identity=None,
        personality="神秘",
        speech_style="简洁",
        goals=[],
    )
    db.add(new_npc)
    db.commit()
    
    result = build_npc_state_from_db(
        db=db,
        session_id=test_session.id,
        npc_template_id=new_npc.id,
    )
    
    assert result is None


def test_mood_derived_from_trust_suspicion(
    db: Session,
    test_session: SessionModel,
    test_npc_templates: dict,
):
    """Mood is correctly derived from trust and suspicion scores."""
    npc_state = SessionNPCStateModel(
        id="snpc_trust_test",
        session_id=test_session.id,
        npc_template_id=test_npc_templates["elder"].id,
        current_location_id="loc_square",
        trust_score=85,
        suspicion_score=5,
        status_flags={},
    )
    db.add(npc_state)
    db.commit()
    
    result = build_npc_state_from_db(
        db=db,
        session_id=test_session.id,
        npc_template_id=test_npc_templates["elder"].id,
    )
    
    assert result is not None
    assert result.npc_state.mood == "friendly"
    assert result.npc_state.mental_state.trust_toward_player == 0.85
    assert result.npc_state.mental_state.suspicion_toward_player == 0.05
