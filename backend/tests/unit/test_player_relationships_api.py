import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    UserModel,
    WorldModel,
    SessionModel,
    NPCTemplateModel,
    SessionNPCStateModel,
    NPCRelationshipMemoryModel,
)
from llm_rpg.main import app

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import llm_rpg.storage.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db(engine) -> Session:
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="function")
def client(engine) -> TestClient:
    def override_get_db():
        SessionLocal = sessionmaker(bind=engine)
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_header(client, db) -> dict:
    username = f"test_{uuid.uuid4().hex[:8]}"
    password = "SecurePass123!"
    client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@test.com", "password": password},
    )
    resp = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_session(db, user_id, world_id, session_id):
    s = SessionModel(
        id=session_id,
        user_id=user_id,
        world_id=world_id,
        status="active",
    )
    db.add(s)
    db.flush()
    return s


def _create_npc_template(db, npc_id, world_id, name, code=None):
    t = NPCTemplateModel(
        id=npc_id,
        world_id=world_id,
        code=code or f"npc_{npc_id[:8]}",
        name=name,
        role_type="npc",
        public_identity="A mysterious figure",
    )
    db.add(t)
    db.flush()
    return t


def _create_npc_state(db, session_id, npc_template_id, trust=50, suspicion=0, status_flags=None):
    s = SessionNPCStateModel(
        id=f"npc_state_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        npc_template_id=npc_template_id,
        trust_score=trust,
        suspicion_score=suspicion,
        status_flags=status_flags or {},
    )
    db.add(s)
    db.flush()
    return s


def _create_relationship_memory(db, session_id, npc_id, target_id, turn, content):
    m = NPCRelationshipMemoryModel(
        id=f"rel_mem_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        npc_id=npc_id,
        target_id=target_id,
        content=content,
        created_turn=turn,
    )
    db.add(m)
    db.flush()
    return m


class TestListRelationships:
    def test_returns_empty_list_when_no_npcs(self, client, auth_header, db):
        world_id = f"w_{uuid.uuid4().hex[:8]}"
        db.add(WorldModel(id=world_id, code=f"wcode_{world_id[:6]}", name="Test World"))
        db.flush()

        user_resp = client.get("/auth/me", headers=auth_header)
        user_id = user_resp.json()["id"]

        session_id = f"s_{uuid.uuid4().hex[:8]}"
        _create_session(db, user_id, world_id, session_id)
        db.flush()

        resp = client.get(
            f"/player/sessions/{session_id}/relationships",
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["relationships"] == []

    def test_returns_relationships_list(self, client, auth_header, db):
        world_id = f"w_{uuid.uuid4().hex[:8]}"
        db.add(WorldModel(id=world_id, code=f"wcode_{world_id[:6]}", name="Test World"))
        db.flush()

        user_resp = client.get("/auth/me", headers=auth_header)
        user_id = user_resp.json()["id"]

        session_id = f"s_{uuid.uuid4().hex[:8]}"
        _create_session(db, user_id, world_id, session_id)

        npc_a = _create_npc_template(db, f"npc_{uuid.uuid4().hex[:8]}", world_id, "Elder Ming")
        npc_b = _create_npc_template(db, f"npc_{uuid.uuid4().hex[:8]}", world_id, "Sister Ling")
        _create_npc_state(db, session_id, npc_a.id, trust=80, status_flags={"respect_score": 70, "fear_score": 10})
        _create_npc_state(db, session_id, npc_b.id, trust=45, status_flags={"respect_score": 55, "fear_score": 30})
        _create_relationship_memory(db, session_id, npc_a.id, "player", 3, "Elder Ming taught you a technique")
        _create_relationship_memory(db, session_id, npc_b.id, "player", 5, "Sister Ling shared a secret")

        db.flush()

        resp = client.get(
            f"/player/sessions/{session_id}/relationships",
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["relationships"]) == 2

    def test_sorts_by_trust_descending_by_default(self, client, auth_header, db):
        world_id = f"w_{uuid.uuid4().hex[:8]}"
        db.add(WorldModel(id=world_id, code=f"wcode_{world_id[:6]}", name="Test World"))
        db.flush()

        user_resp = client.get("/auth/me", headers=auth_header)
        user_id = user_resp.json()["id"]

        session_id = f"s_{uuid.uuid4().hex[:8]}"
        _create_session(db, user_id, world_id, session_id)

        npc_a = _create_npc_template(db, f"npc_{uuid.uuid4().hex[:8]}", world_id, "NPC A")
        npc_b = _create_npc_template(db, f"npc_{uuid.uuid4().hex[:8]}", world_id, "NPC B")
        npc_c = _create_npc_template(db, f"npc_{uuid.uuid4().hex[:8]}", world_id, "NPC C")
        _create_npc_state(db, session_id, npc_a.id, trust=30)
        _create_npc_state(db, session_id, npc_b.id, trust=90)
        _create_npc_state(db, session_id, npc_c.id, trust=60)

        db.flush()

        resp = client.get(
            f"/player/sessions/{session_id}/relationships",
            headers=auth_header,
        )
        assert resp.status_code == 200
        scores = [r["trust_score"] for r in resp.json()["relationships"]]
        assert scores == [90, 60, 30]

    def test_sort_by_respect(self, client, auth_header, db):
        world_id = f"w_{uuid.uuid4().hex[:8]}"
        db.add(WorldModel(id=world_id, code=f"wcode_{world_id[:6]}", name="Test World"))
        db.flush()

        user_resp = client.get("/auth/me", headers=auth_header)
        user_id = user_resp.json()["id"]

        session_id = f"s_{uuid.uuid4().hex[:8]}"
        _create_session(db, user_id, world_id, session_id)

        npc_a = _create_npc_template(db, f"npc_{uuid.uuid4().hex[:8]}", world_id, "NPC A")
        npc_b = _create_npc_template(db, f"npc_{uuid.uuid4().hex[:8]}", world_id, "NPC B")
        _create_npc_state(db, session_id, npc_a.id, trust=50, status_flags={"respect_score": 80})
        _create_npc_state(db, session_id, npc_b.id, trust=50, status_flags={"respect_score": 40})

        db.flush()

        resp = client.get(
            f"/player/sessions/{session_id}/relationships?sort=respect",
            headers=auth_header,
        )
        assert resp.status_code == 200
        scores = [r["respect_score"] for r in resp.json()["relationships"]]
        assert scores == [80, 40]

    def test_rejects_invalid_sort_field(self, client, auth_header, db):
        world_id = f"w_{uuid.uuid4().hex[:8]}"
        db.add(WorldModel(id=world_id, code=f"wcode_{world_id[:6]}", name="Test World"))
        db.flush()

        user_resp = client.get("/auth/me", headers=auth_header)
        user_id = user_resp.json()["id"]

        session_id = f"s_{uuid.uuid4().hex[:8]}"
        _create_session(db, user_id, world_id, session_id)
        db.flush()

        resp = client.get(
            f"/player/sessions/{session_id}/relationships?sort=invalid",
            headers=auth_header,
        )
        assert resp.status_code == 400


class TestRelationshipDetail:
    def test_returns_detail_with_metrics(self, client, auth_header, db):
        world_id = f"w_{uuid.uuid4().hex[:8]}"
        db.add(WorldModel(id=world_id, code=f"wcode_{world_id[:6]}", name="Test World"))
        db.flush()

        user_resp = client.get("/auth/me", headers=auth_header)
        user_id = user_resp.json()["id"]

        session_id = f"s_{uuid.uuid4().hex[:8]}"
        _create_session(db, user_id, world_id, session_id)

        npc = _create_npc_template(
            db, f"npc_{uuid.uuid4().hex[:8]}", world_id,
            "Master Wei", code="master_wei",
        )
        _create_npc_state(
            db, session_id, npc.id,
            trust=75, suspicion=15,
            status_flags={"respect_score": 80, "fear_score": 5},
        )
        _create_relationship_memory(db, session_id, npc.id, "player", 1, "First meeting")
        _create_relationship_memory(db, session_id, npc.id, "player", 2, "Training session")

        db.flush()

        resp = client.get(
            f"/player/sessions/{session_id}/relationships/{npc.id}",
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["npc_id"] == npc.id
        assert data["npc_name"] == "Master Wei"
        assert data["trust_score"] == 75
        assert data["suspicion_score"] == 15
        assert data["respect_score"] == 80
        assert data["fear_score"] == 5
        assert len(data["interaction_history"]) == 2

    def test_returns_404_for_unknown_npc(self, client, auth_header, db):
        world_id = f"w_{uuid.uuid4().hex[:8]}"
        db.add(WorldModel(id=world_id, code=f"wcode_{world_id[:6]}", name="Test World"))
        db.flush()

        user_resp = client.get("/auth/me", headers=auth_header)
        user_id = user_resp.json()["id"]

        session_id = f"s_{uuid.uuid4().hex[:8]}"
        _create_session(db, user_id, world_id, session_id)
        db.flush()

        resp = client.get(
            f"/player/sessions/{session_id}/relationships/nonexistent_npc",
            headers=auth_header,
        )
        assert resp.status_code == 404

    def test_returns_404_for_npc_without_relationship_data(self, client, auth_header, db):
        world_id = f"w_{uuid.uuid4().hex[:8]}"
        db.add(WorldModel(id=world_id, code=f"wcode_{world_id[:6]}", name="Test World"))
        db.flush()

        user_resp = client.get("/auth/me", headers=auth_header)
        user_id = user_resp.json()["id"]

        session_id = f"s_{uuid.uuid4().hex[:8]}"
        _create_session(db, user_id, world_id, session_id)

        npc = _create_npc_template(db, f"npc_{uuid.uuid4().hex[:8]}", world_id, "Stranger")
        db.flush()

        resp = client.get(
            f"/player/sessions/{session_id}/relationships/{npc.id}",
            headers=auth_header,
        )
        assert resp.status_code == 404
        assert "No relationship data" in resp.json()["detail"]

    def test_history_limit_10_turns(self, client, auth_header, db):
        world_id = f"w_{uuid.uuid4().hex[:8]}"
        db.add(WorldModel(id=world_id, code=f"wcode_{world_id[:6]}", name="Test World"))
        db.flush()

        user_resp = client.get("/auth/me", headers=auth_header)
        user_id = user_resp.json()["id"]

        session_id = f"s_{uuid.uuid4().hex[:8]}"
        _create_session(db, user_id, world_id, session_id)

        npc = _create_npc_template(db, f"npc_{uuid.uuid4().hex[:8]}", world_id, "NPC")
        _create_npc_state(db, session_id, npc.id, trust=50)
        for t in range(1, 16):
            _create_relationship_memory(db, session_id, npc.id, "player", t, f"Event {t}")

        db.flush()

        resp = client.get(
            f"/player/sessions/{session_id}/relationships/{npc.id}",
            headers=auth_header,
        )
        assert resp.status_code == 200
        history = resp.json()["interaction_history"]
        assert len(history) == 10
        assert history[0]["turn"] == 6
        assert history[-1]["turn"] == 15


class TestRelationshipSummary:
    def test_summary_with_no_npcs(self, client, auth_header, db):
        world_id = f"w_{uuid.uuid4().hex[:8]}"
        db.add(WorldModel(id=world_id, code=f"wcode_{world_id[:6]}", name="Test World"))
        db.flush()

        user_resp = client.get("/auth/me", headers=auth_header)
        user_id = user_resp.json()["id"]

        session_id = f"s_{uuid.uuid4().hex[:8]}"
        _create_session(db, user_id, world_id, session_id)
        db.flush()

        resp = client.get(
            f"/player/sessions/{session_id}/relationships/summary",
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_npcs"] == 0
        assert data["highest_trust"] is None
        assert data["lowest_trust"] is None
        assert data["average_trust"] == 0.0
        assert data["average_respect"] == 0.0

    def test_summary_with_multiple_npcs(self, client, auth_header, db):
        world_id = f"w_{uuid.uuid4().hex[:8]}"
        db.add(WorldModel(id=world_id, code=f"wcode_{world_id[:6]}", name="Test World"))
        db.flush()

        user_resp = client.get("/auth/me", headers=auth_header)
        user_id = user_resp.json()["id"]

        session_id = f"s_{uuid.uuid4().hex[:8]}"
        _create_session(db, user_id, world_id, session_id)

        npc_a = _create_npc_template(db, f"npc_{uuid.uuid4().hex[:8]}", world_id, "High Trust NPC")
        npc_b = _create_npc_template(db, f"npc_{uuid.uuid4().hex[:8]}", world_id, "Low Trust NPC")
        npc_c = _create_npc_template(db, f"npc_{uuid.uuid4().hex[:8]}", world_id, "Mid Trust NPC")

        _create_npc_state(db, session_id, npc_a.id, trust=90, status_flags={"respect_score": 85})
        _create_npc_state(db, session_id, npc_b.id, trust=20, status_flags={"respect_score": 30})
        _create_npc_state(db, session_id, npc_c.id, trust=55, status_flags={"respect_score": 50})

        db.flush()

        resp = client.get(
            f"/player/sessions/{session_id}/relationships/summary",
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_npcs"] == 3
        assert data["highest_trust"]["npc_name"] == "High Trust NPC"
        assert data["highest_trust"]["trust_score"] == 90
        assert data["lowest_trust"]["npc_name"] == "Low Trust NPC"
        assert data["lowest_trust"]["trust_score"] == 20
        assert data["average_trust"] == 55.0
        assert data["average_respect"] == 55.0
