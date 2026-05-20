"""Integration tests for portrait prewarm API endpoints."""

import pytest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.main import app
from llm_rpg.api.auth import get_current_active_user


TEST_DATABASE_URL = "sqlite:///:memory:"


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
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def test_user(db_session):
    from llm_rpg.storage.repositories import UserRepository
    user_repo = UserRepository(db_session)
    user = user_repo.create({
        "username": "test_prewarm_user",
        "email": "prewarm_test@example.com",
        "password_hash": "hashed_password",
    })
    db_session.commit()
    return user


@pytest.fixture(scope="function")
def client(db_engine, db_session, test_user):
    def override_get_db():
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_current_user():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = override_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_test_world(db_session):
    from llm_rpg.storage.repositories import WorldRepository
    world_repo = WorldRepository(db_session)
    world = world_repo.create({
        "code": f"test_world_{uuid.uuid4().hex[:8]}",
        "name": "Test World",
        "genre": "xianxia",
    })
    db_session.commit()
    return world


def _create_test_location(db_session, world_id, chapter_id=None):
    from llm_rpg.storage.repositories import LocationRepository
    location_repo = LocationRepository(db_session)
    location = location_repo.create({
        "code": f"test_loc_{uuid.uuid4().hex[:8]}",
        "name": "Test Location",
        "world_id": world_id,
        "chapter_id": chapter_id,
        "tags": ["indoor"],
    })
    db_session.commit()
    return location


def _create_test_npc_template(db_session, world_id, name_suffix=""):
    from llm_rpg.storage.repositories import NPCTemplateRepository
    npc_repo = NPCTemplateRepository(db_session)
    npc = npc_repo.create({
        "code": f"test_npc_{uuid.uuid4().hex[:8]}_{name_suffix}",
        "name": f"Test NPC {name_suffix}",
        "world_id": world_id,
        "role_type": "villager",
        "personality": "Friendly and helpful",
        "appearance": "Tall with dark hair",
    })
    db_session.commit()
    return npc


def _create_test_session(db_session, user_id, world_id):
    from llm_rpg.storage.repositories import SessionRepository
    session_repo = SessionRepository(db_session)
    session = session_repo.create({
        "user_id": user_id,
        "world_id": world_id,
        "status": "active",
    })
    db_session.commit()
    return session


def _create_test_session_state(db_session, session_id, current_location_id):
    from llm_rpg.storage.repositories import SessionStateRepository
    state_repo = SessionStateRepository(db_session)
    state = state_repo.create({
        "session_id": session_id,
        "current_location_id": current_location_id,
    })
    db_session.commit()
    return state


def _create_test_npc_state(db_session, session_id, npc_template_id, current_location_id):
    from llm_rpg.storage.repositories import SessionNPCStateRepository
    npc_state_repo = SessionNPCStateRepository(db_session)
    npc_state = npc_state_repo.create({
        "session_id": session_id,
        "npc_template_id": npc_template_id,
        "current_location_id": current_location_id,
        "trust_score": 50,
        "suspicion_score": 0,
    })
    db_session.commit()
    return npc_state


def test_prewarm_generates_for_location_npcs(client, db_session, test_user):
    world = _create_test_world(db_session)
    location = _create_test_location(db_session, world.id)
    session = _create_test_session(db_session, test_user.id, world.id)
    _create_test_session_state(db_session, session.id, location.id)

    npc1 = _create_test_npc_template(db_session, world.id, "1")
    npc2 = _create_test_npc_template(db_session, world.id, "2")
    _create_test_npc_state(db_session, session.id, npc1.id, location.id)
    _create_test_npc_state(db_session, session.id, npc2.id, location.id)

    response = client.post(f"/media/sessions/{session.id}/prewarm-portraits")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("completed", "partial_failure")
    assert data["total"] == 2
    assert data["pending"] + data["completed"] == 2
    assert data["failed"] == 0
    assert len(data["npc_ids"]) == 2


def test_prewarm_cache_first(client, db_session, test_user):
    world = _create_test_world(db_session)
    location = _create_test_location(db_session, world.id)
    session = _create_test_session(db_session, test_user.id, world.id)
    _create_test_session_state(db_session, session.id, location.id)

    npc = _create_test_npc_template(db_session, world.id, "cached")
    _create_test_npc_state(db_session, session.id, npc.id, location.id)

    response1 = client.post(f"/media/sessions/{session.id}/prewarm-portraits")
    assert response1.status_code == 200
    data1 = response1.json()
    assert data1["total"] == 1

    response2 = client.post(f"/media/sessions/{session.id}/prewarm-portraits")
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["total"] == 1
    assert data2["pending"] + data2["completed"] == 1


def test_prewarm_max_npcs(client, db_session, test_user):
    world = _create_test_world(db_session)
    location = _create_test_location(db_session, world.id)
    session = _create_test_session(db_session, test_user.id, world.id)
    _create_test_session_state(db_session, session.id, location.id)

    for i in range(5):
        npc = _create_test_npc_template(db_session, world.id, str(i))
        _create_test_npc_state(db_session, session.id, npc.id, location.id)

    with patch("llm_rpg.api.media._PREWARM_MAX_NPCS", 2):
        response = client.post(f"/media/sessions/{session.id}/prewarm-portraits")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["npc_ids"]) == 2


def test_prewarm_failure_isolation(client, db_session, test_user):
    world = _create_test_world(db_session)
    location = _create_test_location(db_session, world.id)
    session = _create_test_session(db_session, test_user.id, world.id)
    _create_test_session_state(db_session, session.id, location.id)

    npc1 = _create_test_npc_template(db_session, world.id, "good1")
    npc2 = _create_test_npc_template(db_session, world.id, "good2")
    npc3 = _create_test_npc_template(db_session, world.id, "good3")
    _create_test_npc_state(db_session, session.id, npc1.id, location.id)
    _create_test_npc_state(db_session, session.id, npc2.id, location.id)
    _create_test_npc_state(db_session, session.id, npc3.id, location.id)

    failing_npc_id = npc2.id

    with patch("llm_rpg.api.media.build_portrait_context") as mock_build:
        def side_effect(session_id, npc_id, db):
            if npc_id == failing_npc_id:
                raise ValueError("Simulated failure")
            from llm_rpg.services.npc_portrait_prompt import PortraitContext
            return PortraitContext(npc_id=npc_id, npc_name=f"NPC {npc_id}")

        mock_build.side_effect = side_effect

        response = client.post(f"/media/sessions/{session.id}/prewarm-portraits")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial_failure"
    assert data["failed"] >= 1
    assert data["pending"] + data["completed"] + data["failed"] == data["total"]
    assert failing_npc_id not in data["npc_ids"] or data["failed"] >= 1


def test_prewarm_status_returns_counts(client, db_session, test_user):
    world = _create_test_world(db_session)
    location = _create_test_location(db_session, world.id)
    session = _create_test_session(db_session, test_user.id, world.id)
    _create_test_session_state(db_session, session.id, location.id)

    npc1 = _create_test_npc_template(db_session, world.id, "status1")
    npc2 = _create_test_npc_template(db_session, world.id, "status2")
    _create_test_npc_state(db_session, session.id, npc1.id, location.id)
    _create_test_npc_state(db_session, session.id, npc2.id, location.id)

    prewarm_resp = client.post(f"/media/sessions/{session.id}/prewarm-portraits")
    assert prewarm_resp.status_code == 200

    status_resp = client.get(f"/media/sessions/{session.id}/prewarm-status")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["total"] >= 2
    assert "pending" in data
    assert "processing" in data
    assert "completed" in data
    assert "failed" in data
    assert len(data["npc_ids"]) >= 2


def test_prewarm_session_not_found(client):
    fake_session_id = str(uuid.uuid4())
    response = client.post(f"/media/sessions/{fake_session_id}/prewarm-portraits")
    assert response.status_code == 404


def test_prewarm_no_current_location(client, db_session, test_user):
    world = _create_test_world(db_session)
    session = _create_test_session(db_session, test_user.id, world.id)
    _create_test_session_state(db_session, session.id, None)

    npc = _create_test_npc_template(db_session, world.id, "no_loc")
    _create_test_npc_state(db_session, session.id, npc.id, None)

    response = client.post(f"/media/sessions/{session.id}/prewarm-portraits")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["pending"] == 0
    assert data["completed"] == 0
    assert data["failed"] == 0
    assert data["npc_ids"] == []


def test_prewarm_only_npcs_at_current_location(client, db_session, test_user):
    world = _create_test_world(db_session)
    location1 = _create_test_location(db_session, world.id)
    location2 = _create_test_location(db_session, world.id)

    session = _create_test_session(db_session, test_user.id, world.id)
    _create_test_session_state(db_session, session.id, location1.id)

    npc_at_loc1 = _create_test_npc_template(db_session, world.id, "at_loc1")
    npc_at_loc2 = _create_test_npc_template(db_session, world.id, "at_loc2")
    _create_test_npc_state(db_session, session.id, npc_at_loc1.id, location1.id)
    _create_test_npc_state(db_session, session.id, npc_at_loc2.id, location2.id)

    response = client.post(f"/media/sessions/{session.id}/prewarm-portraits")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert npc_at_loc1.id in data["npc_ids"]
    assert npc_at_loc2.id not in data["npc_ids"]
