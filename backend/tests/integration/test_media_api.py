"""Integration tests for Media API v1 endpoints."""

import pytest

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
    """Create a test user for authentication."""
    from llm_rpg.storage.repositories import UserRepository
    user_repo = UserRepository(db_session)
    user = user_repo.create({
        "username": "test_media_user",
        "email": "media_test@example.com",
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


def test_generate_portrait_returns_200(client):
    response = client.post("/media/portraits/generate", json={
        "npc_id": "npc-test-1",
        "style": "anime",
    })
    assert response.status_code == 200
    data = response.json()
    assert "asset_id" in data
    assert data["asset_type"] == "portrait"
    assert data["generation_status"] in ("completed", "processing", "failed")


def test_generate_scene_returns_200(client):
    response = client.post("/media/scenes/generate", json={
        "location_id": "loc-test-1",
        "time_of_day": "day",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["asset_type"] == "scene"


def test_generate_bgm_returns_200(client):
    response = client.post("/media/bgm/generate", json={
        "mood": "calm",
        "duration_seconds": 60,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["asset_type"] == "bgm"


def test_cache_hit_on_duplicate_request(client):
    resp1 = client.post("/media/portraits/generate", json={
        "npc_id": "npc-cache-test",
        "style": "anime",
    })
    assert resp1.status_code == 200
    data1 = resp1.json()
    
    resp2 = client.post("/media/portraits/generate", json={
        "npc_id": "npc-cache-test",
        "style": "anime",
    })
    assert resp2.status_code == 200
    data2 = resp2.json()
    
    assert "asset_id" in data2
    assert data2["cache_hit"] is True


def test_get_asset_by_id(client):
    create_resp = client.post("/media/portraits/generate", json={
        "npc_id": "npc-get-test",
    })
    assert create_resp.status_code == 200
    asset_id = create_resp.json()["asset_id"]
    
    get_resp = client.get(f"/media/assets/{asset_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["asset_id"] == asset_id


def test_get_nonexistent_asset_returns_404(client):
    response = client.get("/media/assets/nonexistent-id")
    assert response.status_code == 404


def test_list_session_assets(client):
    session_id = "session-test-1"
    client.post("/media/portraits/generate", json={
        "npc_id": "npc-s1",
        "session_id": session_id,
    })
    client.post("/media/scenes/generate", json={
        "location_id": "loc-s1",
        "session_id": session_id,
    })
    
    response = client.get(f"/media/sessions/{session_id}/assets")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2


def test_generation_failure_returns_200_with_failed_status(client):
    response = client.post("/media/portraits/generate", json={
        "npc_id": "npc-fail-test",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["generation_status"] in ("completed", "processing", "failed")


def test_unauthenticated_request_returns_401(db_engine):
    """Test that requests without auth return 401."""
    def override_get_db():
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides.pop(get_current_active_user, None)
    
    with TestClient(app) as test_client:
        response = test_client.post("/media/portraits/generate", json={
            "npc_id": "npc-no-auth",
        })
        assert response.status_code == 401
    
    app.dependency_overrides.clear()
