import pytest
import uuid
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    WorldModel,
    ChapterModel,
    LocationModel,
    NPCTemplateModel,
    ItemTemplateModel,
    QuestTemplateModel,
    QuestStepModel,
    UserModel,
    SaveSlotModel,
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
    EventLogModel,
    MemoryFactModel,
    MemorySummaryModel,
)
from llm_rpg.storage.repositories import (
    WorldRepository,
    ChapterRepository,
    LocationRepository,
    NPCTemplateRepository,
    ItemTemplateRepository,
    QuestTemplateRepository,
    QuestStepRepository,
    UserRepository,
    SaveSlotRepository,
    SessionRepository,
    SessionStateRepository,
    SessionPlayerStateRepository,
    EventLogRepository,
    MemoryFactRepository,
    MemorySummaryRepository,
)


TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_session():
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


@pytest.fixture
def sample_world_data():
    return {
        "code": "xiuxian_world",
        "name": "修仙世界",
        "genre": "xianxia",
        "lore_summary": "一个充满灵气的修仙世界",
        "status": "active",
    }


@pytest.fixture
def sample_user_data():
    return {
        "username": f"test_user_{uuid.uuid4().hex[:8]}",
        "email": f"test_{uuid.uuid4().hex[:8]}@example.com",
    }


class TestWorldRepository:
    def test_create_world(self, db_session, sample_world_data):
        repo = WorldRepository(db_session)
        world = repo.create(sample_world_data)
        assert world.id is not None
        assert world.code == sample_world_data["code"]
        assert world.name == sample_world_data["name"]

    def test_get_world_by_id(self, db_session, sample_world_data):
        repo = WorldRepository(db_session)
        created = repo.create(sample_world_data)
        fetched = repo.get_by_id(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_world_by_code(self, db_session, sample_world_data):
        repo = WorldRepository(db_session)
        created = repo.create(sample_world_data)
        fetched = repo.get_by_code(sample_world_data["code"])
        assert fetched is not None
        assert fetched.code == sample_world_data["code"]

    def test_get_active_worlds(self, db_session):
        repo = WorldRepository(db_session)
        repo.create({"code": "active1", "name": "Active 1", "status": "active"})
        repo.create({"code": "inactive", "name": "Inactive", "status": "inactive"})
        active = repo.get_active()
        assert len(active) == 1
        assert active[0].code == "active1"

    def test_update_world(self, db_session, sample_world_data):
        repo = WorldRepository(db_session)
        created = repo.create(sample_world_data)
        updated = repo.update(created.id, {"name": "Updated Name"})
        assert updated is not None
        assert updated.name == "Updated Name"

    def test_delete_world(self, db_session, sample_world_data):
        repo = WorldRepository(db_session)
        created = repo.create(sample_world_data)
        deleted = repo.delete(created.id)
        assert deleted is True
        assert repo.get_by_id(created.id) is None


class TestChapterRepository:
    def test_create_chapter(self, db_session, sample_world_data):
        world_repo = WorldRepository(db_session)
        world = world_repo.create(sample_world_data)
        
        repo = ChapterRepository(db_session)
        chapter_data = {
            "world_id": world.id,
            "chapter_no": 1,
            "name": "第一章：初入修仙",
            "summary": "主角开始修仙之旅",
        }
        chapter = repo.create(chapter_data)
        assert chapter.id is not None
        assert chapter.world_id == world.id
        assert chapter.chapter_no == 1

    def test_get_chapters_by_world(self, db_session, sample_world_data):
        world_repo = WorldRepository(db_session)
        world = world_repo.create(sample_world_data)
        
        repo = ChapterRepository(db_session)
        repo.create({"world_id": world.id, "chapter_no": 1, "name": "第一章"})
        repo.create({"world_id": world.id, "chapter_no": 2, "name": "第二章"})
        
        chapters = repo.get_by_world(world.id)
        assert len(chapters) == 2
        assert chapters[0].chapter_no == 1
        assert chapters[1].chapter_no == 2


class TestLocationRepository:
    def test_create_location(self, db_session, sample_world_data):
        world_repo = WorldRepository(db_session)
        world = world_repo.create(sample_world_data)
        
        repo = LocationRepository(db_session)
        location_data = {
            "world_id": world.id,
            "code": "square",
            "name": "广场",
            "description": "修仙宗门的广场",
        }
        location = repo.create(location_data)
        assert location.id is not None
        assert location.code == "square"

    def test_get_locations_by_world(self, db_session, sample_world_data):
        world_repo = WorldRepository(db_session)
        world = world_repo.create(sample_world_data)
        
        repo = LocationRepository(db_session)
        repo.create({"world_id": world.id, "code": "loc1", "name": "Location 1"})
        repo.create({"world_id": world.id, "code": "loc2", "name": "Location 2"})
        
        locations = repo.get_by_world(world.id)
        assert len(locations) == 2


class TestNPCTemplateRepository:
    def test_create_npc_template(self, db_session, sample_world_data):
        world_repo = WorldRepository(db_session)
        world = world_repo.create(sample_world_data)
        
        repo = NPCTemplateRepository(db_session)
        npc_data = {
            "world_id": world.id,
            "code": "master",
            "name": "掌门",
            "role_type": "mentor",
            "personality": "慈祥而严厉",
        }
        npc = repo.create(npc_data)
        assert npc.id is not None
        assert npc.name == "掌门"

    def test_get_npc_by_code(self, db_session, sample_world_data):
        world_repo = WorldRepository(db_session)
        world = world_repo.create(sample_world_data)
        
        repo = NPCTemplateRepository(db_session)
        repo.create({
            "world_id": world.id,
            "code": "npc1",
            "name": "NPC 1",
        })
        
        npc = repo.get_by_code(world.id, "npc1")
        assert npc is not None
        assert npc.code == "npc1"


class TestItemTemplateRepository:
    def test_create_item_template(self, db_session, sample_world_data):
        world_repo = WorldRepository(db_session)
        world = world_repo.create(sample_world_data)
        
        repo = ItemTemplateRepository(db_session)
        item_data = {
            "world_id": world.id,
            "code": "spirit_stone",
            "name": "灵石",
            "item_type": "currency",
            "rarity": "common",
        }
        item = repo.create(item_data)
        assert item.id is not None
        assert item.name == "灵石"


class TestQuestTemplateRepository:
    def test_create_quest_template(self, db_session, sample_world_data):
        world_repo = WorldRepository(db_session)
        world = world_repo.create(sample_world_data)
        
        repo = QuestTemplateRepository(db_session)
        quest_data = {
            "world_id": world.id,
            "code": "first_quest",
            "name": "初入宗门",
            "quest_type": "main",
        }
        quest = repo.create(quest_data)
        assert quest.id is not None
        assert quest.name == "初入宗门"


class TestQuestStepRepository:
    def test_create_quest_step(self, db_session, sample_world_data):
        world_repo = WorldRepository(db_session)
        world = world_repo.create(sample_world_data)
        
        quest_repo = QuestTemplateRepository(db_session)
        quest = quest_repo.create({
            "world_id": world.id,
            "code": "quest1",
            "name": "Quest 1",
        })
        
        repo = QuestStepRepository(db_session)
        step_data = {
            "quest_template_id": quest.id,
            "step_no": 1,
            "objective": "找到掌门",
        }
        step = repo.create(step_data)
        assert step.id is not None
        assert step.step_no == 1


class TestUserRepository:
    def test_create_user(self, db_session, sample_user_data):
        repo = UserRepository(db_session)
        user = repo.create(sample_user_data)
        assert user.id is not None
        assert user.username == sample_user_data["username"]

    def test_get_user_by_username(self, db_session, sample_user_data):
        repo = UserRepository(db_session)
        repo.create(sample_user_data)
        user = repo.get_by_username(sample_user_data["username"])
        assert user is not None
        assert user.username == sample_user_data["username"]


class TestSaveSlotRepository:
    def test_create_save_slot(self, db_session, sample_user_data):
        user_repo = UserRepository(db_session)
        user = user_repo.create(sample_user_data)
        
        repo = SaveSlotRepository(db_session)
        slot_data = {
            "user_id": user.id,
            "slot_number": 1,
            "name": "存档1",
        }
        slot = repo.create(slot_data)
        assert slot.id is not None
        assert slot.slot_number == 1

    def test_get_save_slots_by_user(self, db_session, sample_user_data):
        user_repo = UserRepository(db_session)
        user = user_repo.create(sample_user_data)
        
        repo = SaveSlotRepository(db_session)
        repo.create({"user_id": user.id, "slot_number": 1, "name": "Slot 1"})
        repo.create({"user_id": user.id, "slot_number": 2, "name": "Slot 2"})
        
        slots = repo.get_by_user(user.id)
        assert len(slots) == 2


class TestSessionRepository:
    def test_create_session(self, db_session, sample_user_data, sample_world_data):
        user_repo = UserRepository(db_session)
        world_repo = WorldRepository(db_session)
        user = user_repo.create(sample_user_data)
        world = world_repo.create(sample_world_data)
        
        repo = SessionRepository(db_session)
        session_data = {
            "user_id": user.id,
            "world_id": world.id,
            "status": "active",
        }
        session = repo.create(session_data)
        assert session.id is not None
        assert session.user_id == user.id
        assert session.status == "active"

    def test_get_sessions_by_user(self, db_session, sample_user_data, sample_world_data):
        user_repo = UserRepository(db_session)
        world_repo = WorldRepository(db_session)
        user = user_repo.create(sample_user_data)
        world = world_repo.create(sample_world_data)
        
        repo = SessionRepository(db_session)
        repo.create({"user_id": user.id, "world_id": world.id})
        repo.create({"user_id": user.id, "world_id": world.id})
        
        sessions = repo.get_by_user(user.id)
        assert len(sessions) == 2

    def test_get_active_sessions(self, db_session, sample_user_data, sample_world_data):
        user_repo = UserRepository(db_session)
        world_repo = WorldRepository(db_session)
        user = user_repo.create(sample_user_data)
        world = world_repo.create(sample_world_data)
        
        repo = SessionRepository(db_session)
        repo.create({"user_id": user.id, "world_id": world.id, "status": "active"})
        repo.create({"user_id": user.id, "world_id": world.id, "status": "completed"})
        
        active = repo.get_active_by_user(user.id)
        assert len(active) == 1


class TestSessionStateRepository:
    def test_create_or_update_session_state(self, db_session, sample_user_data, sample_world_data):
        user_repo = UserRepository(db_session)
        world_repo = WorldRepository(db_session)
        session_repo = SessionRepository(db_session)
        
        user = user_repo.create(sample_user_data)
        world = world_repo.create(sample_world_data)
        session = session_repo.create({"user_id": user.id, "world_id": world.id})
        
        repo = SessionStateRepository(db_session)
        state_data = {
            "session_id": session.id,
            "current_time": "子时",
            "time_phase": "night",
            "active_mode": "exploration",
        }
        state = repo.create_or_update(state_data)
        assert state is not None
        assert state.session_id == session.id
        
        updated = repo.create_or_update({
            "session_id": session.id,
            "active_mode": "combat",
        })
        assert updated.active_mode == "combat"


class TestSessionPlayerStateRepository:
    def test_create_player_state(self, db_session, sample_user_data, sample_world_data):
        user_repo = UserRepository(db_session)
        world_repo = WorldRepository(db_session)
        session_repo = SessionRepository(db_session)
        
        user = user_repo.create(sample_user_data)
        world = world_repo.create(sample_world_data)
        session = session_repo.create({"user_id": user.id, "world_id": world.id})
        
        repo = SessionPlayerStateRepository(db_session)
        state_data = {
            "session_id": session.id,
            "realm_stage": "炼气一层",
            "hp": 100,
            "max_hp": 100,
        }
        state = repo.create_or_update(state_data)
        assert state is not None
        assert state.hp == 100
        assert state.realm_stage == "炼气一层"


class TestEventLogRepository:
    def test_create_event_log(self, db_session, sample_user_data, sample_world_data):
        user_repo = UserRepository(db_session)
        world_repo = WorldRepository(db_session)
        session_repo = SessionRepository(db_session)
        
        user = user_repo.create(sample_user_data)
        world = world_repo.create(sample_world_data)
        session = session_repo.create({"user_id": user.id, "world_id": world.id})
        
        repo = EventLogRepository(db_session)
        event_data = {
            "session_id": session.id,
            "turn_no": 1,
            "event_type": "player_input",
            "input_text": "观察四周",
        }
        event = repo.create(event_data)
        assert event.id is not None
        assert event.turn_no == 1

    def test_get_events_by_session(self, db_session, sample_user_data, sample_world_data):
        user_repo = UserRepository(db_session)
        world_repo = WorldRepository(db_session)
        session_repo = SessionRepository(db_session)
        
        user = user_repo.create(sample_user_data)
        world = world_repo.create(sample_world_data)
        session = session_repo.create({"user_id": user.id, "world_id": world.id})
        
        repo = EventLogRepository(db_session)
        repo.create({"session_id": session.id, "turn_no": 1, "event_type": "type1"})
        repo.create({"session_id": session.id, "turn_no": 2, "event_type": "type2"})
        
        events = repo.get_by_session(session.id)
        assert len(events) == 2

    def test_get_recent_events(self, db_session, sample_user_data, sample_world_data):
        user_repo = UserRepository(db_session)
        world_repo = WorldRepository(db_session)
        session_repo = SessionRepository(db_session)
        
        user = user_repo.create(sample_user_data)
        world = world_repo.create(sample_world_data)
        session = session_repo.create({"user_id": user.id, "world_id": world.id})
        
        repo = EventLogRepository(db_session)
        for i in range(1, 6):
            repo.create({
                "session_id": session.id,
                "turn_no": i,
                "event_type": f"type{i}",
            })
        
        recent = repo.get_recent(session.id, limit=3)
        assert len(recent) == 3


class TestMemoryFactRepository:
    def test_create_memory_fact(self, db_session, sample_user_data, sample_world_data):
        user_repo = UserRepository(db_session)
        world_repo = WorldRepository(db_session)
        session_repo = SessionRepository(db_session)
        
        user = user_repo.create(sample_user_data)
        world = world_repo.create(sample_world_data)
        session = session_repo.create({"user_id": user.id, "world_id": world.id})
        
        repo = MemoryFactRepository(db_session)
        fact_data = {
            "session_id": session.id,
            "fact_type": "knowledge",
            "subject_ref": "player",
            "fact_key": "knows_secret",
            "fact_value": "true",
            "confidence": 1.0,
        }
        fact = repo.create(fact_data)
        assert fact.id is not None
        assert fact.fact_key == "knows_secret"

    def test_get_facts_by_type(self, db_session, sample_user_data, sample_world_data):
        user_repo = UserRepository(db_session)
        world_repo = WorldRepository(db_session)
        session_repo = SessionRepository(db_session)
        
        user = user_repo.create(sample_user_data)
        world = world_repo.create(sample_world_data)
        session = session_repo.create({"user_id": user.id, "world_id": world.id})
        
        repo = MemoryFactRepository(db_session)
        repo.create({
            "session_id": session.id,
            "fact_type": "knowledge",
            "fact_key": "key1",
        })
        repo.create({
            "session_id": session.id,
            "fact_type": "knowledge",
            "fact_key": "key2",
        })
        repo.create({
            "session_id": session.id,
            "fact_type": "belief",
            "fact_key": "key3",
        })
        
        knowledge = repo.get_by_type(session.id, "knowledge")
        assert len(knowledge) == 2


class TestMemorySummaryRepository:
    def test_create_memory_summary(self, db_session, sample_user_data, sample_world_data):
        user_repo = UserRepository(db_session)
        world_repo = WorldRepository(db_session)
        session_repo = SessionRepository(db_session)
        
        user = user_repo.create(sample_user_data)
        world = world_repo.create(sample_world_data)
        session = session_repo.create({"user_id": user.id, "world_id": world.id})
        
        repo = MemorySummaryRepository(db_session)
        summary_data = {
            "session_id": session.id,
            "scope_type": "session",
            "summary_text": "玩家刚刚进入宗门",
            "importance_score": 0.8,
        }
        summary = repo.create(summary_data)
        assert summary.id is not None
        assert summary.importance_score == 0.8

    def test_get_summaries_by_scope(self, db_session, sample_user_data, sample_world_data):
        user_repo = UserRepository(db_session)
        world_repo = WorldRepository(db_session)
        session_repo = SessionRepository(db_session)
        
        user = user_repo.create(sample_user_data)
        world = world_repo.create(sample_world_data)
        session = session_repo.create({"user_id": user.id, "world_id": world.id})
        
        repo = MemorySummaryRepository(db_session)
        repo.create({
            "session_id": session.id,
            "scope_type": "session",
            "summary_text": "Summary 1",
        })
        repo.create({
            "session_id": session.id,
            "scope_type": "npc",
            "scope_ref_id": "npc1",
            "summary_text": "Summary 2",
        })
        
        session_summaries = repo.get_by_scope(session.id, "session")
        assert len(session_summaries) == 1
