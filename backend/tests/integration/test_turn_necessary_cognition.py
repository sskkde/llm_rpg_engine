"""Necessary cognition is atomic with the authoritative turn commit."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from llm_rpg.core import turn_service
from llm_rpg.core.npc_memory_retrieval_service import batch_update_recall_stats
from llm_rpg.core.post_commit_memory_writer import _update_scope_count
from llm_rpg.core.turn_unit_of_work import TurnUnitOfWork
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel,
    EventLogModel,
    LocationModel,
    GameEventModel,
    MemoryFactModel,
    MemorySummaryModel,
    NPCBeliefModel,
    NPCPrivateMemoryModel,
    NPCMemoryScopeModel,
    NPCRelationshipMemoryModel,
    NPCTemplateModel,
    QuestTemplateModel,
    SaveSlotModel,
    SessionModel,
    StateDeltaModel,
    TurnTransactionModel,
    UserModel,
    WorldModel,
)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'necessary-cognition.sqlite'}", poolclass=NullPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    yield factory
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def seeded_session(session_factory):
    db = session_factory()
    user = UserModel(id="cognition-user", username="cognition-user", email="cognition@example.com", password_hash="x")
    world = WorldModel(id="cognition-world", code="cognition-world", name="测试世界", genre="xianxia", status="active")
    chapter = ChapterModel(id="cognition-chapter", world_id=world.id, chapter_no=1, name="测试章")
    location = LocationModel(id="cognition-location", world_id=world.id, chapter_id=chapter.id, code="square", name="广场", access_rules={"always_accessible": True})
    npc = NPCTemplateModel(id="cognition-npc", world_id=world.id, code="guide", name="向导", role_type="guide")
    quest = QuestTemplateModel(id="cognition-quest", world_id=world.id, code="quest", name="任务", quest_type="main", visibility="visible")
    slot = SaveSlotModel(id="cognition-slot", user_id=user.id, slot_number=1, name="测试存档")
    session = SessionModel(id="cognition-session", user_id=user.id, save_slot_id=slot.id, world_id=world.id, current_chapter_id=chapter.id, status="active")
    db.add_all([user, world, chapter, location, npc, quest, slot, session])
    db.commit()
    session_id = session.id
    db.close()
    return session_id


def test_required_cognition_write_failure_aborts_and_rolls_back_turn(session_factory, seeded_session, monkeypatch):
    def fail_required_write(*_args, **_kwargs):
        raise RuntimeError("injected necessary cognition failure")

    monkeypatch.setattr(turn_service.MemorySummaryRepository, "create", fail_required_write)
    db = session_factory()
    with pytest.raises(RuntimeError, match="injected necessary cognition failure"):
        turn_service.execute_turn_service(db, seeded_session, "观察四周", use_mock=True)
    db.close()

    verify = session_factory()
    try:
        for model in (
            EventLogModel, GameEventModel, StateDeltaModel, MemorySummaryModel,
            MemoryFactModel, NPCBeliefModel, NPCPrivateMemoryModel, NPCRelationshipMemoryModel,
        ):
            assert verify.query(model).filter_by(session_id=seeded_session).count() == 0, model.__tablename__
        claim = verify.query(TurnTransactionModel).filter_by(session_id=seeded_session).one()
        assert claim.status == "aborted"
    finally:
        verify.close()


def test_recall_and_scope_updates_remain_uncommitted_inside_managed_turn(session_factory, seeded_session):
    db = session_factory()
    memory = NPCPrivateMemoryModel(
        id="recall-memory", session_id=seeded_session, npc_id="cognition-npc", memory_type="episodic",
        content="用来验证召回统计", created_turn=1, last_accessed_turn=1, recall_count=0,
    )
    scope = NPCMemoryScopeModel(
        id="cognition-scope", session_id=seeded_session, npc_id="cognition-npc",
        npc_template_id="cognition-npc", memory_count=0,
    )
    db.add_all([memory, scope])
    db.commit()
    with TurnUnitOfWork(db):
        assert batch_update_recall_stats(db, [memory.id], 2) == 1
        _update_scope_count(db, seeded_session, "cognition-npc", 1)
        observer = session_factory()
        try:
            persisted = observer.get(NPCPrivateMemoryModel, memory.id)
            persisted_scope = observer.get(NPCMemoryScopeModel, scope.id)
            assert persisted.recall_count == 0
            assert persisted.last_accessed_turn == 1
            assert persisted_scope.memory_count == 0
        finally:
            observer.close()
    db.commit()
    observer = session_factory()
    try:
        persisted = observer.get(NPCPrivateMemoryModel, memory.id)
        persisted_scope = observer.get(NPCMemoryScopeModel, scope.id)
        assert persisted.recall_count == 1
        assert persisted.last_accessed_turn == 2
        assert persisted_scope.memory_count == 1
    finally:
        observer.close()
        db.close()


def test_managed_scheduled_event_failure_aborts_turn(session_factory, seeded_session, monkeypatch):
    def fail_schedule(*_args, **_kwargs):
        raise RuntimeError("injected scheduled-event write failure")

    monkeypatch.setattr(turn_service.ScheduledEventProcessor, "process_scheduled_events", fail_schedule)
    db = session_factory()
    with pytest.raises(RuntimeError, match="injected scheduled-event write failure"):
        turn_service.execute_turn_service(db, seeded_session, "观察四周", use_mock=True)
    db.close()

    verify = session_factory()
    try:
        for model in (EventLogModel, GameEventModel, StateDeltaModel):
            assert verify.query(model).filter_by(session_id=seeded_session).count() == 0, model.__tablename__
        claim = verify.query(TurnTransactionModel).filter_by(session_id=seeded_session).one()
        assert claim.status == "aborted"
    finally:
        verify.close()


def test_successful_turn_commits_cognition_with_turn_facts(session_factory, seeded_session, monkeypatch):
    original_persist = turn_service._persist_turn_memories

    def persist_with_fact(**kwargs):
        world_progression = dict(kwargs.get("world_progression") or {})
        world_progression["candidate_events"] = list(world_progression.get("candidate_events") or []) + [
            {"event_type": "cognition_test", "description": "同批提交的必要认知事实"}
        ]
        kwargs["world_progression"] = world_progression
        return original_persist(**kwargs)

    monkeypatch.setattr(turn_service, "_persist_turn_memories", persist_with_fact)
    db = session_factory()
    result = turn_service.execute_turn_service(db, seeded_session, "观察四周", use_mock=True)
    assert result.turn_no == 1
    db.close()

    verify = session_factory()
    try:
        assert verify.query(EventLogModel).filter_by(session_id=seeded_session, turn_no=1).count() > 0
        summaries = verify.query(MemorySummaryModel).filter_by(session_id=seeded_session).count()
        facts = verify.query(MemoryFactModel).filter_by(session_id=seeded_session).count()
        assert summaries > 0
        assert facts > 0
    finally:
        verify.close()
