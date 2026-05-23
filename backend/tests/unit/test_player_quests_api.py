import pytest
import uuid

from fastapi.testclient import TestClient
from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    UserModel,
    WorldModel,
    QuestTemplateModel,
    QuestStepModel,
    SessionModel,
    SessionQuestStateModel,
)
from llm_rpg.storage.repositories import (
    UserRepository,
    WorldRepository,
    QuestTemplateRepository,
    QuestStepRepository,
    SessionRepository,
    SessionQuestStateRepository,
)
from llm_rpg.main import app

TEST_DATABASE_URL = "sqlite:///:memory:"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def client(db_engine):
    def override_get_db():
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _new_db(db_engine) -> Session:
    return sessionmaker(bind=db_engine)()


def _make_user(db: Session, username: str, is_admin: bool = False) -> UserModel:
    return UserRepository(db).create({
        "username": username,
        "email": f"{username}@test.local",
        "password_hash": pwd_context.hash("testpass123"),
        "is_admin": is_admin,
    })


def _make_world(db: Session, code: str, name: str) -> WorldModel:
    return WorldRepository(db).create({"code": code, "name": name, "status": "active"})


def _make_quest_template(db: Session, world_id: str, code: str, name: str,
                          quest_type: str = "main", visibility: str = "visible",
                          summary: str = None) -> QuestTemplateModel:
    return QuestTemplateRepository(db).create({
        "world_id": world_id,
        "code": code,
        "name": name,
        "quest_type": quest_type,
        "visibility": visibility,
        "summary": summary,
    })


def _make_quest_step(db: Session, quest_template_id: str, step_no: int,
                     objective: str) -> QuestStepModel:
    return QuestStepRepository(db).create({
        "quest_template_id": quest_template_id,
        "step_no": step_no,
        "objective": objective,
    })


def _make_session(db: Session, user_id: str, world_id: str) -> SessionModel:
    return SessionRepository(db).create({
        "user_id": user_id,
        "world_id": world_id,
        "status": "active",
    })


def _make_quest_state(db: Session, session_id: str, quest_template_id: str,
                      status: str = "active", current_step_no: int = 1,
                      progress_json: dict = None,
                      player_visibility: str = "discovered") -> SessionQuestStateModel:
    return SessionQuestStateRepository(db).create({
        "session_id": session_id,
        "quest_template_id": quest_template_id,
        "current_step_no": current_step_no,
        "status": status,
        "progress_json": progress_json or {},
        "player_visibility": player_visibility,
    })


def _get_token(client: TestClient, username: str, password: str = "testpass123") -> str:
    resp = client.post("/auth/login", json={
        "username": username,
        "password": password,
    })
    assert resp.status_code == 200, f"Login failed: {resp.json()}"
    return resp.json()["access_token"]


def test_get_quests_returns_list(db_engine, client):
    db = _new_db(db_engine)
    try:
        world = _make_world(db, "w1", "Test World")
        user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
        db.commit()

        session = _make_session(db, user.id, world.id)
        qt1 = _make_quest_template(db, world.id, "q_a", "Quest A")
        qt2 = _make_quest_template(db, world.id, "q_b", "Quest B")
        _make_quest_step(db, qt1.id, 1, "Step A1")
        _make_quest_step(db, qt2.id, 1, "Step B1")
        _make_quest_state(db, session.id, qt1.id, "active")
        _make_quest_state(db, session.id, qt2.id, "active")
        db.commit()

        session_id = session.id
        qt1_id = qt1.id
        qt2_id = qt2.id
        token = _get_token(client, user.username)
    finally:
        db.close()

    resp = client.get(
        f"/player/sessions/{session_id}/quests",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    quest_ids = {q["quest_id"] for q in data}
    assert quest_ids == {qt1_id, qt2_id}
    assert "title" in data[0]
    assert "objectives" in data[0]


def test_get_quests_status_filter(db_engine, client):
    db = _new_db(db_engine)
    try:
        world = _make_world(db, "w2", "Filter World")
        user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
        db.commit()

        session = _make_session(db, user.id, world.id)
        qt_active = _make_quest_template(db, world.id, "q_active", "Active Quest")
        qt_done = _make_quest_template(db, world.id, "q_done", "Done Quest")
        _make_quest_step(db, qt_active.id, 1, "Do it")
        _make_quest_step(db, qt_done.id, 1, "Done")
        _make_quest_state(db, session.id, qt_active.id, "active")
        _make_quest_state(db, session.id, qt_done.id, "completed")
        db.commit()

        session_id = session.id
        qt_active_id = qt_active.id
        qt_done_id = qt_done.id
        token = _get_token(client, user.username)
    finally:
        db.close()

    base = f"/player/sessions/{session_id}/quests"
    headers = {"Authorization": f"Bearer {token}"}

    resp_active = client.get(f"{base}?status=active", headers=headers)
    assert resp_active.status_code == 200
    data = resp_active.json()
    assert len(data) == 1
    assert data[0]["quest_id"] == qt_active_id
    assert data[0]["status"] == "active"

    resp_done = client.get(f"{base}?status=completed", headers=headers)
    assert resp_done.status_code == 200
    data = resp_done.json()
    assert len(data) == 1
    assert data[0]["quest_id"] == qt_done_id
    assert data[0]["status"] == "completed"

    resp_all = client.get(f"{base}?status=all", headers=headers)
    assert resp_all.status_code == 200
    assert len(resp_all.json()) == 2

    resp_no_filter = client.get(base, headers=headers)
    assert resp_no_filter.status_code == 200
    assert len(resp_no_filter.json()) == 2


def test_get_quest_detail_correct_fields(db_engine, client):
    db = _new_db(db_engine)
    try:
        world = _make_world(db, "w3", "Detail World")
        user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
        db.commit()

        session = _make_session(db, user.id, world.id)
        qt = _make_quest_template(db, world.id, "q_det", "Detailed Quest",
                                  quest_type="main", visibility="visible",
                                  summary="A test quest")
        _make_quest_step(db, qt.id, 1, "Step one")
        _make_quest_step(db, qt.id, 2, "Step two")
        _make_quest_state(db, session.id, qt.id, "active",
                          current_step_no=2,
                          progress_json={"step_1": True})
        db.commit()

        session_id = session.id
        qt_id = qt.id
        token = _get_token(client, user.username)
    finally:
        db.close()

    resp = client.get(
        f"/player/sessions/{session_id}/quests/{qt_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["quest_id"] == qt_id
    assert data["title"] == "Detailed Quest"
    assert data["description"] == "A test quest"
    assert data["quest_type"] == "main"
    assert data["stage"] == 2
    assert data["status"] == "active"
    assert data["visibility"] == "discovered"
    assert data["progress"] == {"step_1": True}
    assert len(data["objectives"]) == 2
    assert data["objectives"][0]["completed"] is True
    assert data["objectives"][1]["completed"] is False
    assert len(data["step_history"]) == 2
    assert data["last_updated_at"] is not None


def test_get_quest_detail_404_unknown(db_engine, client):
    db = _new_db(db_engine)
    try:
        world = _make_world(db, "w4", "404 World")
        user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
        db.commit()

        session = _make_session(db, user.id, world.id)
        db.commit()

        session_id = session.id
        token = _get_token(client, user.username)
    finally:
        db.close()

    resp = client.get(
        f"/player/sessions/{session_id}/quests/nonexistent-quest-uuid",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_delete_abandons_active_quest(db_engine, client):
    db = _new_db(db_engine)
    try:
        world = _make_world(db, "w5", "Abandon World")
        user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
        db.commit()

        session = _make_session(db, user.id, world.id)
        qt = _make_quest_template(db, world.id, "q_ab", "Abandonable")
        _make_quest_step(db, qt.id, 1, "First step")
        _make_quest_state(db, session.id, qt.id, "active")
        db.commit()

        session_id = session.id
        qt_id = qt.id
        token = _get_token(client, user.username)
    finally:
        db.close()

    resp = client.delete(
        f"/player/sessions/{session_id}/quests/{qt_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "abandoned"
    assert data["quest_id"] == qt_id

    db2 = _new_db(db_engine)
    try:
        qs = SessionQuestStateRepository(db2).get_by_session_and_quest(
            session_id, qt_id
        )
        assert qs is not None
        assert qs.status == "abandoned"
    finally:
        db2.close()


def test_delete_rejects_completed_quest(db_engine, client):
    db = _new_db(db_engine)
    try:
        world = _make_world(db, "w6", "Reject World")
        user = _make_user(db, f"u_{uuid.uuid4().hex[:6]}")
        db.commit()

        session = _make_session(db, user.id, world.id)
        qt = _make_quest_template(db, world.id, "q_done", "Finished Quest")
        _make_quest_step(db, qt.id, 1, "All done")
        _make_quest_state(db, session.id, qt.id, "completed")
        db.commit()

        session_id = session.id
        qt_id = qt.id
        token = _get_token(client, user.username)
    finally:
        db.close()

    resp = client.delete(
        f"/player/sessions/{session_id}/quests/{qt_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "cannot abandon" in resp.json()["detail"].lower()
