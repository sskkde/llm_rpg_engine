"""
Integration tests for quest progression flow.

Tests visible quest activation, deterministic progression based on actions,
and quest-based location access control.
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
    QuestStepModel,
    UserModel,
    SaveSlotModel,
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
    SessionQuestStateModel,
)
from llm_rpg.core.quest_progression import (
    QuestProgress,
    QuestProgressionResult,
    QuestProgressionError,
    check_quest_progression,
    get_visible_quests,
    advance_quest_step,
    check_location_access,
)
from llm_rpg.core.session_initialization import initialize_session_story_state


@pytest.fixture
def db():
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
def test_locations(db: Session, test_world: WorldModel, test_chapter: ChapterModel) -> dict:
    square = LocationModel(
        id="loc_square",
        world_id=test_world.id,
        chapter_id=test_chapter.id,
        code="square",
        name="宗门广场",
        description="宗门广场",
        access_rules={"always_accessible": True},
    )
    trial_hall = LocationModel(
        id="loc_trial_hall",
        world_id=test_world.id,
        chapter_id=test_chapter.id,
        code="trial_hall",
        name="试炼堂",
        description="试炼堂",
        access_rules={"always_accessible": True},
    )
    secret_gate = LocationModel(
        id="loc_secret_gate",
        world_id=test_world.id,
        chapter_id=test_chapter.id,
        code="secret_gate",
        name="秘境入口",
        description="秘境入口",
        access_rules={"quest_completed": "first_trial"},
    )
    db.add_all([square, trial_hall, secret_gate])
    db.commit()
    return {
        "square": square,
        "trial_hall": trial_hall,
        "secret_gate": secret_gate,
    }


@pytest.fixture
def test_npc_templates(db: Session, test_world: WorldModel) -> list:
    npc1 = NPCTemplateModel(
        id="npc_elder",
        world_id=test_world.id,
        code="elder_zhang",
        name="张长老",
        role="长老",
        personality="严厉",
        hidden_identity=None,
    )
    db.add(npc1)
    db.commit()
    return [npc1]


@pytest.fixture
def test_quest_templates(db: Session, test_world: WorldModel) -> dict:
    first_trial = QuestTemplateModel(
        id="quest_first_trial",
        world_id=test_world.id,
        code="first_trial",
        name="初试炼",
        quest_type="main",
        summary="完成初次试炼",
        visibility="visible",
    )
    hidden_quest = QuestTemplateModel(
        id="quest_hidden",
        world_id=test_world.id,
        code="hidden_secret",
        name="隐藏秘密",
        quest_type="side",
        summary="发现隐藏的秘密",
        visibility="hidden",
    )
    db.add_all([first_trial, hidden_quest])
    db.commit()
    
    step1 = QuestStepModel(
        id="step_1",
        quest_template_id=first_trial.id,
        step_no=1,
        objective="前往试炼堂",
        success_conditions={},
    )
    step2 = QuestStepModel(
        id="step_2",
        quest_template_id=first_trial.id,
        step_no=2,
        objective="完成试炼",
        success_conditions={},
    )
    db.add_all([step1, step2])
    db.commit()
    
    return {
        "first_trial": first_trial,
        "hidden": hidden_quest,
    }


@pytest.fixture
def test_save_slot(db: Session, test_user: UserModel) -> SaveSlotModel:
    save_slot = SaveSlotModel(
        id="save_1",
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
    test_save_slot: SaveSlotModel
) -> SessionModel:
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


class TestTrialHallAdvancesFirstTrialProgress:
    """Test that movement to trial_hall advances the first_trial quest."""
    
    def test_movement_to_trial_hall_advances_quest_step(
        self,
        db: Session,
        test_session: SessionModel,
        test_quest_templates: dict,
        test_locations: dict,
    ):
        initialize_session_story_state(db, test_session.id)
        
        quest_states = db.query(SessionQuestStateModel).filter(
            SessionQuestStateModel.session_id == test_session.id
        ).all()
        
        first_trial_state = next(
            (qs for qs in quest_states 
             if qs.quest_template_id == test_quest_templates["first_trial"].id),
            None
        )
        
        assert first_trial_state is not None
        assert first_trial_state.current_step_no == 1
        assert first_trial_state.status == "active"
        
        action_context = {
            "action_type": "movement",
            "target_location_code": "trial_hall",
        }
        
        results = check_quest_progression(db, test_session.id, action_context)
        
        assert len(results) == 1
        assert results[0].triggered is True
        assert results[0].quest_progress is not None
        assert results[0].quest_progress.step_no == 2
        
        db.refresh(first_trial_state)
        assert first_trial_state.current_step_no == 2
    
    def test_second_movement_does_not_advance_further(
        self,
        db: Session,
        test_session: SessionModel,
        test_quest_templates: dict,
    ):
        initialize_session_story_state(db, test_session.id)
        
        action_context = {
            "action_type": "movement",
            "target_location_code": "trial_hall",
        }
        
        results1 = check_quest_progression(db, test_session.id, action_context)
        assert len(results1) == 1
        assert results1[0].quest_progress.step_no == 2
        
        results2 = check_quest_progression(db, test_session.id, action_context)
        
        assert len(results2) == 0


class TestHiddenQuestNotAutoActivated:
    """Test that hidden quests stay hidden and are not auto-activated."""
    
    def test_hidden_quest_not_in_visible_quests(
        self,
        db: Session,
        test_session: SessionModel,
        test_quest_templates: dict,
    ):
        initialize_session_story_state(db, test_session.id)
        
        visible_quests = get_visible_quests(db, test_session.id)
        
        visible_quest_ids = [qs.quest_template_id for qs in visible_quests]
        
        assert test_quest_templates["first_trial"].id in visible_quest_ids
        assert test_quest_templates["hidden"].id not in visible_quest_ids
    
    def test_hidden_quest_not_created_during_initialization(
        self,
        db: Session,
        test_session: SessionModel,
        test_quest_templates: dict,
    ):
        initialize_session_story_state(db, test_session.id)
        
        all_quest_states = db.query(SessionQuestStateModel).filter(
            SessionQuestStateModel.session_id == test_session.id
        ).all()
        
        quest_template_ids = [qs.quest_template_id for qs in all_quest_states]
        
        assert test_quest_templates["first_trial"].id in quest_template_ids
        assert test_quest_templates["hidden"].id not in quest_template_ids


class TestQuestProgressionPersists:
    """Test that quest progress is saved to database."""
    
    def test_advance_quest_step_persists_to_db(
        self,
        db: Session,
        test_session: SessionModel,
        test_quest_templates: dict,
    ):
        initialize_session_story_state(db, test_session.id)
        
        first_trial_id = test_quest_templates["first_trial"].id
        
        progress = advance_quest_step(db, test_session.id, first_trial_id)
        
        assert progress is not None
        assert progress.step_no == 2
        assert progress.status == "active"
        
        db.expire_all()
        
        quest_state = db.query(SessionQuestStateModel).filter(
            SessionQuestStateModel.session_id == test_session.id,
            SessionQuestStateModel.quest_template_id == first_trial_id,
        ).first()
        
        assert quest_state is not None
        assert quest_state.current_step_no == 2
        assert quest_state.status == "active"
        assert "last_advanced" in quest_state.progress_json
    
    def test_quest_completion_persists(
        self,
        db: Session,
        test_session: SessionModel,
        test_quest_templates: dict,
    ):
        initialize_session_story_state(db, test_session.id)
        
        first_trial_id = test_quest_templates["first_trial"].id
        
        progress1 = advance_quest_step(db, test_session.id, first_trial_id)
        assert progress1.step_no == 2
        
        progress2 = advance_quest_step(db, test_session.id, first_trial_id)
        
        assert progress2.status == "completed"
        
        db.expire_all()
        
        quest_state = db.query(SessionQuestStateModel).filter(
            SessionQuestStateModel.session_id == test_session.id,
            SessionQuestStateModel.quest_template_id == first_trial_id,
        ).first()
        
        assert quest_state.status == "completed"
        assert "completed_at_step" in quest_state.progress_json


class TestGatedLocationChecksQuestFlags:
    """Test that gated locations check quest completion flags."""
    
    def test_location_without_quest_requirement_is_accessible(
        self,
        db: Session,
        test_session: SessionModel,
        test_locations: dict,
    ):
        initialize_session_story_state(db, test_session.id)
        
        can_access = check_location_access(
            db, test_session.id, test_locations["square"].id
        )
        
        assert can_access is True
    
    def test_gated_location_blocked_without_quest_completion(
        self,
        db: Session,
        test_session: SessionModel,
        test_locations: dict,
        test_quest_templates: dict,
    ):
        initialize_session_story_state(db, test_session.id)
        
        can_access = check_location_access(
            db, test_session.id, test_locations["secret_gate"].id
        )
        
        assert can_access is False
    
    def test_gated_location_accessible_after_quest_completion(
        self,
        db: Session,
        test_session: SessionModel,
        test_locations: dict,
        test_quest_templates: dict,
    ):
        initialize_session_story_state(db, test_session.id)
        
        first_trial_id = test_quest_templates["first_trial"].id
        
        advance_quest_step(db, test_session.id, first_trial_id)
        advance_quest_step(db, test_session.id, first_trial_id)
        
        can_access = check_location_access(
            db, test_session.id, test_locations["secret_gate"].id
        )
        
        assert can_access is True
    
    def test_nonexistent_location_returns_false(
        self,
        db: Session,
        test_session: SessionModel,
    ):
        can_access = check_location_access(db, test_session.id, "nonexistent_id")
        
        assert can_access is False
