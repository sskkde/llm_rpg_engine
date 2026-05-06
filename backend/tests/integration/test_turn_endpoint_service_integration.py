"""
Regression tests for real turn endpoints using the durable turn service.

These tests intentionally call FastAPI routes instead of calling
execute_turn_service directly, so they catch API integration drift.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.api.auth import get_current_active_user
from llm_rpg.main import app
from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    ChapterModel,
    EventLogModel,
    LocationModel,
    NPCTemplateModel,
    QuestTemplateModel,
    SaveSlotModel,
    SessionModel,
    SessionNPCStateModel,
    SessionPlayerStateModel,
    SessionQuestStateModel,
    SessionStateModel,
    UserModel,
    WorldModel,
)


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db(db_engine):
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seeded_session(db: Session) -> SessionModel:
    user = UserModel(
        id="endpoint_user",
        username="endpoint_user",
        email="endpoint@example.com",
        password_hash="hashed",
        is_admin=True,
    )
    world = WorldModel(
        id="endpoint_world",
        code="endpoint_world",
        name="端点测试世界",
        genre="xianxia",
        status="active",
    )
    chapter = ChapterModel(
        id="endpoint_chapter",
        world_id=world.id,
        chapter_no=1,
        name="初入宗门",
    )
    square = LocationModel(
        id="endpoint_square",
        world_id=world.id,
        chapter_id=chapter.id,
        code="square",
        name="宗门广场",
        access_rules={"always_accessible": True},
    )
    trial_hall = LocationModel(
        id="endpoint_trial_hall",
        world_id=world.id,
        chapter_id=chapter.id,
        code="trial_hall",
        name="试炼堂",
        access_rules={"time_restrictions": "daytime_only"},
    )
    herb_garden = LocationModel(
        id="endpoint_herb_garden",
        world_id=world.id,
        chapter_id=chapter.id,
        code="herb_garden",
        name="药园",
        access_rules={"quest_requirement": None},
    )
    npc = NPCTemplateModel(
        id="endpoint_npc_senior",
        world_id=world.id,
        code="senior_sister",
        name="柳师姐",
        role_type="guide",
        hidden_identity="隐藏身份不应泄露",
    )
    quest = QuestTemplateModel(
        id="endpoint_quest_trial",
        world_id=world.id,
        code="first_trial",
        name="初次试炼",
        quest_type="main",
        visibility="visible",
    )
    slot = SaveSlotModel(
        id="endpoint_slot",
        user_id=user.id,
        slot_number=1,
        name="端点测试存档",
    )
    session = SessionModel(
        id="endpoint_session",
        user_id=user.id,
        save_slot_id=slot.id,
        world_id=world.id,
        current_chapter_id=chapter.id,
        status="active",
    )

    db.add_all([
        user,
        world,
        chapter,
        square,
        trial_hall,
        herb_garden,
        npc,
        quest,
        slot,
        session,
    ])
    db.commit()
    return session


@pytest.fixture
def client(db_engine, seeded_session: SessionModel):
    SessionLocal = sessionmaker(bind=db_engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_current_user():
        return UserModel(
            id=seeded_session.user_id,
            username="endpoint_user",
            email="endpoint@example.com",
            is_admin=True,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = override_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _event_payloads(raw_sse: str):
    payloads = []
    event_name = None
    for line in raw_sse.splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            payloads.append((event_name, json.loads(line.removeprefix("data: "))))
    return payloads


def test_game_turn_endpoint_uses_turn_service_and_backfills_state(
    client: TestClient,
    db: Session,
    seeded_session: SessionModel,
):
    response = client.post(
        f"/game/sessions/{seeded_session.id}/turn",
        json={"action": "前往试炼堂"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["turn_index"] == 1
    assert data["validation_passed"] is True
    assert data["recommended_actions"]
    assert data["player_state"]["location_id"] == "endpoint_trial_hall"

    db.expire_all()
    session_state = db.query(SessionStateModel).filter_by(session_id=seeded_session.id).one()
    assert session_state.current_location_id == "endpoint_trial_hall"
    assert db.query(SessionPlayerStateModel).filter_by(session_id=seeded_session.id).count() == 1
    assert db.query(SessionNPCStateModel).filter_by(session_id=seeded_session.id).count() == 1
    assert db.query(SessionQuestStateModel).filter_by(session_id=seeded_session.id).count() == 1

    event = db.query(EventLogModel).filter_by(
        session_id=seeded_session.id,
        turn_no=1,
        event_type="player_turn",
    ).one()
    assert event.result_json["recommended_actions"]
    assert event.result_json["movement_success"] is True


def test_streaming_mock_endpoint_uses_turn_service_once(
    client: TestClient,
    db: Session,
    seeded_session: SessionModel,
):
    with client.stream(
        "POST",
        f"/streaming/sessions/{seeded_session.id}/turn/mock",
        json={"action": "前往试炼堂"},
    ) as response:
        assert response.status_code == 200
        raw_sse = "".join(response.iter_text())

    payloads = _event_payloads(raw_sse)
    event_names = [name for name, _ in payloads]
    assert "turn_started" in event_names
    assert "event_committed" in event_names
    assert "narration_delta" in event_names
    assert "turn_completed" in event_names

    committed = next(data for name, data in payloads if name == "event_committed")
    completed = next(data for name, data in payloads if name == "turn_completed")
    assert committed["turn_index"] == 1
    assert completed["turn_index"] == 1
    assert completed["recommended_actions"]

    db.expire_all()
    assert db.query(EventLogModel).filter_by(
        session_id=seeded_session.id,
        turn_no=1,
        event_type="player_turn",
    ).count() == 1
    assert db.query(SessionPlayerStateModel).filter_by(session_id=seeded_session.id).count() == 1
    assert db.query(SessionNPCStateModel).filter_by(session_id=seeded_session.id).count() == 1
    assert db.query(SessionQuestStateModel).filter_by(session_id=seeded_session.id).count() == 1
