"""Immutable transaction contract tests for the authoritative turn service."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.core import turn_service
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel, EventLogModel, LocationModel, NPCTemplateModel,
    QuestTemplateModel, SaveSlotModel, SessionModel, UserModel, WorldModel,
)


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def seeded_session(db_engine):
    db = sessionmaker(bind=db_engine)()
    user = UserModel(id="atomic-user", username="atomic-user", email="atomic@example.com", password_hash="x")
    world = WorldModel(id="atomic-world", code="atomic-world", name="测试世界", genre="xianxia", status="active")
    chapter = ChapterModel(id="atomic-chapter", world_id=world.id, chapter_no=1, name="测试章")
    location = LocationModel(id="atomic-location", world_id=world.id, chapter_id=chapter.id, code="square", name="广场", access_rules={"always_accessible": True})
    npc = NPCTemplateModel(id="atomic-npc", world_id=world.id, code="guide", name="向导", role_type="guide")
    quest = QuestTemplateModel(id="atomic-quest", world_id=world.id, code="quest", name="任务", quest_type="main", visibility="visible")
    slot = SaveSlotModel(id="atomic-slot", user_id=user.id, slot_number=1, name="测试存档")
    session = SessionModel(id="atomic-session", user_id=user.id, save_slot_id=slot.id, world_id=world.id, current_chapter_id=chapter.id, status="active")
    db.add_all([user, world, chapter, location, npc, quest, slot, session])
    db.commit()
    session_id = session.id
    db.close()
    return session_id


def test_late_write_failure_leaves_no_half_turn(db_engine, seeded_session, monkeypatch):
    """Contract: later required-write failure must roll back all authoritative turn rows."""
    db = sessionmaker(bind=db_engine)()

    def fail_after_player_turn(*_args, **_kwargs):
        raise RuntimeError("injected failure after commit_turn")

    monkeypatch.setattr(turn_service.SessionRepository, "update_last_played", fail_after_player_turn)
    try:
        turn_service.execute_turn_service(db, seeded_session, "观察四周", use_mock=True)
    except RuntimeError as exc:
        assert "injected failure after commit_turn" in str(exc)
    finally:
        db.close()

    verify = sessionmaker(bind=db_engine)()
    try:
        leftovers = verify.query(EventLogModel).filter_by(session_id=seeded_session, turn_no=1).all()
        assert leftovers == [], (
            "T0 atomicity contract: a failure in a later required write must not leave "
            f"player_turn/game-effect rows committed; observed {[(row.event_type, row.id) for row in leftovers]}"
        )
    finally:
        verify.close()
