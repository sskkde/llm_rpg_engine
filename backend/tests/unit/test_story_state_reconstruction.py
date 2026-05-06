"""
Unit tests for State Reconstruction Module.

Tests the reconstruction of CanonicalState from persisted DB rows.
"""

import pytest
import uuid
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    WorldModel,
    ChapterModel,
    LocationModel,
    NPCTemplateModel,
    QuestTemplateModel,
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
    SessionNPCStateModel,
    SessionQuestStateModel,
    EventLogModel,
    UserModel,
    SaveSlotModel,
)
from llm_rpg.core.state_reconstruction import (
    reconstruct_canonical_state,
    get_latest_turn_number,
    get_active_actors_at_location,
    SessionNotFoundError,
    StateReconstructionError,
)


TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_session():
    """Create an in-memory SQLite database for each test."""
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    yield session
    
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def test_world(db_session):
    """Create a test world."""
    world = WorldModel(
        id=f"world_{uuid.uuid4().hex[:8]}",
        code="test_world",
        name="Test World",
        genre="xianxia",
        lore_summary="A test world for state reconstruction tests",
        status="active",
    )
    db_session.add(world)
    db_session.commit()
    return world


@pytest.fixture
def test_chapter(db_session, test_world):
    """Create a test chapter."""
    chapter = ChapterModel(
        id=f"chapter_{uuid.uuid4().hex[:8]}",
        world_id=test_world.id,
        chapter_no=1,
        name="Chapter 1: The Beginning",
        summary="The first chapter of the test world",
    )
    db_session.add(chapter)
    db_session.commit()
    return chapter


@pytest.fixture
def test_locations(db_session, test_world, test_chapter):
    """Create test locations."""
    locations = []
    for i, (code, name) in enumerate([
        ("loc_mountain_gate", "山门广场"),
        ("loc_trial_hall", "试炼堂"),
        ("loc_forest", "后山森林"),
    ]):
        loc = LocationModel(
            id=f"loc_{uuid.uuid4().hex[:8]}",
            world_id=test_world.id,
            chapter_id=test_chapter.id if i < 2 else None,
            code=code,
            name=name,
            tags=["outdoor"] if i == 0 else ["indoor"] if i == 1 else ["wild"],
            description=f"Test location: {name}",
        )
        db_session.add(loc)
        locations.append(loc)
    db_session.commit()
    return locations


@pytest.fixture
def test_npc_templates(db_session, test_world):
    """Create test NPC templates."""
    npcs = []
    for code, name, role in [
        ("npc_lingyue", "灵月师姐", "mentor"),
        ("npc_chen", "陈师兄", "senior"),
        ("npc_guard", "守门弟子", "guard"),
    ]:
        npc = NPCTemplateModel(
            id=f"npc_tpl_{uuid.uuid4().hex[:8]}",
            world_id=test_world.id,
            code=code,
            name=name,
            role_type=role,
            public_identity=f"Public identity of {name}",
            hidden_identity=f"Hidden identity of {name}",
            personality="Friendly and helpful",
            speech_style="Formal",
            goals=["Help the player"],
        )
        db_session.add(npc)
        npcs.append(npc)
    db_session.commit()
    return npcs


@pytest.fixture
def test_quest_templates(db_session, test_world):
    """Create test quest templates."""
    quests = []
    for code, name, quest_type in [
        ("quest_trial", "入门试炼", "main"),
        ("quest_training", "基础修行", "side"),
    ]:
        quest = QuestTemplateModel(
            id=f"quest_tpl_{uuid.uuid4().hex[:8]}",
            world_id=test_world.id,
            code=code,
            name=name,
            quest_type=quest_type,
            summary=f"Summary of {name}",
            visibility="visible" if quest_type == "main" else "hidden",
        )
        db_session.add(quest)
        quests.append(quest)
    db_session.commit()
    return quests


@pytest.fixture
def test_user(db_session):
    """Create a test user."""
    user = UserModel(
        id=f"user_{uuid.uuid4().hex[:8]}",
        username="test_user",
        email="test@example.com",
        password_hash="hashed_password",
        is_admin=False,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def test_save_slot(db_session, test_user):
    """Create a test save slot."""
    slot = SaveSlotModel(
        id=f"save_{uuid.uuid4().hex[:8]}",
        user_id=test_user.id,
        slot_number=1,
        name="Test Save",
    )
    db_session.add(slot)
    db_session.commit()
    return slot


class TestReconstructCanonicalState:
    """Tests for reconstruct_canonical_state function."""
    
    def test_missing_session_returns_none(self, db_session):
        """Test that missing session returns None, not an exception."""
        non_existent_id = str(uuid.uuid4())
        result = reconstruct_canonical_state(db_session, non_existent_id)
        
        assert result is None
    
    def test_reconstructs_new_session_with_defaults(
        self,
        db_session,
        test_world,
        test_chapter,
        test_locations,
        test_user,
    ):
        """Test reconstruction of a new session with minimal DB rows."""
        session = SessionModel(
            id=f"session_{uuid.uuid4().hex[:8]}",
            user_id=test_user.id,
            world_id=test_world.id,
            current_chapter_id=test_chapter.id,
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        
        result = reconstruct_canonical_state(db_session, session.id)
        
        assert result is not None
        assert result.player_state is not None
        assert result.world_state is not None
        assert result.current_scene_state is not None
        
        assert result.world_state.world_id == test_world.id
        assert result.player_state.location_id == "loc_mountain_gate"
        assert result.current_scene_state.scene_phase == "exploration"
        
        assert len(result.npc_states) == 0
        assert len(result.quest_states) == 0
        assert len(result.location_states) >= 0
    
    def test_reconstructs_partial_session_from_db(
        self,
        db_session,
        test_world,
        test_chapter,
        test_locations,
        test_npc_templates,
        test_quest_templates,
        test_user,
    ):
        """Test reconstruction of a partial session with some DB rows."""
        session = SessionModel(
            id=f"session_{uuid.uuid4().hex[:8]}",
            user_id=test_user.id,
            world_id=test_world.id,
            current_chapter_id=test_chapter.id,
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        
        session_state = SessionStateModel(
            id=f"ss_{uuid.uuid4().hex[:8]}",
            session_id=session.id,
            current_time="修仙历 春 第5日 午时",
            time_phase="午时",
            current_location_id=test_locations[1].id,
            active_mode="dialogue",
            global_flags_json={"flag1": True, "flag2": "value"},
        )
        db_session.add(session_state)
        
        player_state = SessionPlayerStateModel(
            id=f"ps_{uuid.uuid4().hex[:8]}",
            session_id=session.id,
            realm_stage="筑基初期",
            hp=80,
            max_hp=100,
            stamina=90,
            spirit_power=150,
        )
        db_session.add(player_state)
        
        npc_state = SessionNPCStateModel(
            id=f"ns_{uuid.uuid4().hex[:8]}",
            session_id=session.id,
            npc_template_id=test_npc_templates[0].id,
            current_location_id=test_locations[1].id,
            trust_score=75,
            suspicion_score=10,
            status_flags={"talked": True},
        )
        db_session.add(npc_state)
        
        quest_state = SessionQuestStateModel(
            id=f"qs_{uuid.uuid4().hex[:8]}",
            session_id=session.id,
            quest_template_id=test_quest_templates[0].id,
            current_step_no=2,
            progress_json={"step1_completed": True},
            status="active",
        )
        db_session.add(quest_state)
        
        db_session.commit()
        
        result = reconstruct_canonical_state(db_session, session.id)
        
        assert result is not None
        
        assert result.player_state.location_id == test_locations[1].id
        assert result.player_state.realm == "筑基初期"
        assert result.player_state.spiritual_power == 150
        
        assert result.world_state.current_time.day == 5
        assert result.world_state.current_time.period == "午时"
        assert result.world_state.global_flags.get("flag1") is True
        
        assert result.current_scene_state.location_id == test_locations[1].id
        assert result.current_scene_state.scene_phase == "dialogue"
        
        assert len(result.npc_states) == 1
        npc_id = test_npc_templates[0].code
        assert npc_id in result.npc_states
        assert result.npc_states[npc_id].name == test_npc_templates[0].name
        assert result.npc_states[npc_id].location_id == test_locations[1].id
        
        assert len(result.quest_states) == 1
        quest_id = test_quest_templates[0].code
        assert quest_id in result.quest_states
        assert result.quest_states[quest_id].name == test_quest_templates[0].name
        assert result.quest_states[quest_id].status == "active"
        assert result.quest_states[quest_id].stage == "2"
    
    def test_reconstruction_is_idempotent(
        self,
        db_session,
        test_world,
        test_chapter,
        test_locations,
        test_user,
    ):
        """Test that calling reconstruct twice returns same result without creating duplicate rows."""
        session = SessionModel(
            id=f"session_{uuid.uuid4().hex[:8]}",
            user_id=test_user.id,
            world_id=test_world.id,
            current_chapter_id=test_chapter.id,
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        
        session_state = SessionStateModel(
            id=f"ss_{uuid.uuid4().hex[:8]}",
            session_id=session.id,
            current_time="修仙历 春 第3日 辰时",
            current_location_id=test_locations[0].id,
        )
        db_session.add(session_state)
        db_session.commit()
        
        result1 = reconstruct_canonical_state(db_session, session.id)
        result2 = reconstruct_canonical_state(db_session, session.id)
        
        assert result1 is not None
        assert result2 is not None
        
        assert result1.player_state.location_id == result2.player_state.location_id
        assert result1.world_state.current_time.day == result2.world_state.current_time.day
        assert result1.world_state.current_time.period == result2.world_state.current_time.period
        
        session_states_count = db_session.query(SessionStateModel).filter(
            SessionStateModel.session_id == session.id
        ).count()
        assert session_states_count == 1
    
    def test_reconstruction_handles_missing_world_gracefully(
        self,
        db_session,
        test_user,
    ):
        """Test that reconstruction raises error when world is missing."""
        session = SessionModel(
            id=f"session_{uuid.uuid4().hex[:8]}",
            user_id=test_user.id,
            world_id="non_existent_world",
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        
        with pytest.raises(StateReconstructionError) as exc_info:
            reconstruct_canonical_state(db_session, session.id)
        
        assert "World not found" in str(exc_info.value)
    
    def test_reconstruction_with_multiple_npcs(
        self,
        db_session,
        test_world,
        test_locations,
        test_npc_templates,
        test_user,
    ):
        """Test reconstruction with multiple NPCs at different locations."""
        session = SessionModel(
            id=f"session_{uuid.uuid4().hex[:8]}",
            user_id=test_user.id,
            world_id=test_world.id,
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        
        for i, npc_tpl in enumerate(test_npc_templates):
            npc_state = SessionNPCStateModel(
                id=f"ns_{uuid.uuid4().hex[:8]}_{i}",
                session_id=session.id,
                npc_template_id=npc_tpl.id,
                current_location_id=test_locations[i % len(test_locations)].id,
                trust_score=50 + i * 10,
            )
            db_session.add(npc_state)
        db_session.commit()
        
        result = reconstruct_canonical_state(db_session, session.id)
        
        assert result is not None
        assert len(result.npc_states) == 3
        
        for npc_tpl in test_npc_templates:
            npc_id = npc_tpl.code
            assert npc_id in result.npc_states


class TestGetLatestTurnNumber:
    """Tests for get_latest_turn_number function."""
    
    def test_returns_zero_for_new_session(
        self,
        db_session,
        test_world,
        test_user,
    ):
        """Test that new session returns turn 0."""
        session = SessionModel(
            id=f"session_{uuid.uuid4().hex[:8]}",
            user_id=test_user.id,
            world_id=test_world.id,
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        
        turn = get_latest_turn_number(db_session, session.id)
        
        assert turn == 0
    
    def test_returns_latest_turn_from_event_logs(
        self,
        db_session,
        test_world,
        test_user,
    ):
        """Test that latest turn is retrieved from event logs."""
        session = SessionModel(
            id=f"session_{uuid.uuid4().hex[:8]}",
            user_id=test_user.id,
            world_id=test_world.id,
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        
        for turn_no in [1, 2, 3, 5, 7]:
            event = EventLogModel(
                id=f"evt_{uuid.uuid4().hex[:8]}_{turn_no}",
                session_id=session.id,
                turn_no=turn_no,
                event_type="player_turn",
                input_text=f"Action {turn_no}",
                narrative_text=f"Narrative {turn_no}",
            )
            db_session.add(event)
        db_session.commit()
        
        turn = get_latest_turn_number(db_session, session.id)
        
        assert turn == 7


class TestGetActiveActorsAtLocation:
    """Tests for get_active_actors_at_location function."""
    
    def test_returns_player_at_location(
        self,
        db_session,
        test_world,
        test_locations,
        test_user,
    ):
        """Test that player is included when at the location."""
        session = SessionModel(
            id=f"session_{uuid.uuid4().hex[:8]}",
            user_id=test_user.id,
            world_id=test_world.id,
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        
        session_state = SessionStateModel(
            id=f"ss_{uuid.uuid4().hex[:8]}",
            session_id=session.id,
            current_location_id=test_locations[0].id,
        )
        db_session.add(session_state)
        db_session.commit()
        
        actors = get_active_actors_at_location(
            db_session,
            session.id,
            test_locations[0].id,
        )
        
        assert "player" in actors
    
    def test_returns_npcs_at_location(
        self,
        db_session,
        test_world,
        test_locations,
        test_npc_templates,
        test_user,
    ):
        """Test that NPCs at location are included."""
        session = SessionModel(
            id=f"session_{uuid.uuid4().hex[:8]}",
            user_id=test_user.id,
            world_id=test_world.id,
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        
        npc_state = SessionNPCStateModel(
            id=f"ns_{uuid.uuid4().hex[:8]}",
            session_id=session.id,
            npc_template_id=test_npc_templates[0].id,
            current_location_id=test_locations[1].id,
        )
        db_session.add(npc_state)
        db_session.commit()
        
        actors = get_active_actors_at_location(
            db_session,
            session.id,
            test_locations[1].id,
        )
        
        assert test_npc_templates[0].code in actors
    
    def test_excludes_npcs_at_other_locations(
        self,
        db_session,
        test_world,
        test_locations,
        test_npc_templates,
        test_user,
    ):
        """Test that NPCs at other locations are excluded."""
        session = SessionModel(
            id=f"session_{uuid.uuid4().hex[:8]}",
            user_id=test_user.id,
            world_id=test_world.id,
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        
        for i, npc_tpl in enumerate(test_npc_templates):
            npc_state = SessionNPCStateModel(
                id=f"ns_{uuid.uuid4().hex[:8]}_{i}",
                session_id=session.id,
                npc_template_id=npc_tpl.id,
                current_location_id=test_locations[i].id,
            )
            db_session.add(npc_state)
        db_session.commit()
        
        actors = get_active_actors_at_location(
            db_session,
            session.id,
            test_locations[0].id,
        )
        
        assert test_npc_templates[0].code in actors
        assert test_npc_templates[1].code not in actors
        assert test_npc_templates[2].code not in actors


class TestStateReconstructionDoesNotMutate:
    """Tests ensuring reconstruction does not mutate source data."""
    
    def test_reconstruction_does_not_create_new_rows(
        self,
        db_session,
        test_world,
        test_chapter,
        test_locations,
        test_npc_templates,
        test_user,
    ):
        """Test that reconstruction is read-only and doesn't create new DB rows."""
        session = SessionModel(
            id=f"session_{uuid.uuid4().hex[:8]}",
            user_id=test_user.id,
            world_id=test_world.id,
            current_chapter_id=test_chapter.id,
            status="active",
        )
        db_session.add(session)
        db_session.commit()
        
        before_sessions = db_session.query(SessionModel).count()
        before_states = db_session.query(SessionStateModel).count()
        before_player = db_session.query(SessionPlayerStateModel).count()
        before_npc = db_session.query(SessionNPCStateModel).count()
        
        reconstruct_canonical_state(db_session, session.id)
        reconstruct_canonical_state(db_session, session.id)
        reconstruct_canonical_state(db_session, session.id)
        
        after_sessions = db_session.query(SessionModel).count()
        after_states = db_session.query(SessionStateModel).count()
        after_player = db_session.query(SessionPlayerStateModel).count()
        after_npc = db_session.query(SessionNPCStateModel).count()
        
        assert before_sessions == after_sessions
        assert before_states == after_states
        assert before_player == after_player
        assert before_npc == after_npc
