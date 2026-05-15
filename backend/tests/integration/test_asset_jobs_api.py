"""Integration tests for Asset Job API endpoints."""

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.main import app
from llm_rpg.api.auth import get_current_active_user
from llm_rpg.models.assets import AssetJobStatus


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
        "username": "test_job_user",
        "email": "job_test@example.com",
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


def test_create_portrait_job(client):
    response = client.post("/media/jobs/portraits", json={
        "npc_id": "npc-job-1",
        "style": "anime",
        "expression": "happy",
    })
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["asset_type"] == "portrait"
    assert data["status"] in ("pending", "completed")


def test_create_scene_job(client):
    response = client.post("/media/jobs/scenes", json={
        "location_id": "loc-job-1",
        "time_of_day": "night",
        "weather": "rain",
    })
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["asset_type"] == "scene"


def test_create_bgm_job(client):
    response = client.post("/media/jobs/bgm", json={
        "mood": "mysterious",
        "duration_seconds": 90,
    })
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["asset_type"] == "bgm"


def test_get_job_status(client):
    create_resp = client.post("/media/jobs/portraits", json={
        "npc_id": "npc-status-test",
    })
    assert create_resp.status_code == 200
    job_id = create_resp.json()["job_id"]
    
    get_resp = client.get(f"/media/jobs/{job_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["job_id"] == job_id
    assert "status" in data


def test_get_job_status_not_found(client):
    response = client.get("/media/jobs/nonexistent-job-id")
    assert response.status_code == 404


def test_list_session_jobs(client):
    session_id = "session-jobs-test"
    
    client.post("/media/jobs/portraits", json={
        "npc_id": "npc-list-1",
        "session_id": session_id,
    })
    client.post("/media/jobs/scenes", json={
        "location_id": "loc-list-1",
        "session_id": session_id,
    })
    
    response = client.get(f"/media/sessions/{session_id}/jobs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2


def test_cancel_job(client, db_engine):
    from llm_rpg.storage.repositories import AssetJobRepository
    from sqlalchemy.orm import Session
    
    create_resp = client.post("/media/jobs/portraits", json={
        "npc_id": "npc-cancel-test",
    })
    assert create_resp.status_code == 200
    job_id = create_resp.json()["job_id"]
    
    if create_resp.json()["status"] == "pending":
        cancel_resp = client.post(f"/media/jobs/{job_id}/cancel")
        assert cancel_resp.status_code == 200
        data = cancel_resp.json()
        assert data["status"] == "cancelled"


def test_retry_job(client, db_session):
    from llm_rpg.storage.repositories import AssetJobRepository
    from llm_rpg.models.assets import AssetJobStatus
    import uuid
    from datetime import datetime
    
    job_repo = AssetJobRepository(db_session)
    job_id = str(uuid.uuid4())
    job_repo.create_job({
        "id": str(uuid.uuid4()),
        "job_id": job_id,
        "asset_type": "portrait",
        "status": AssetJobStatus.FAILED.value,
        "provider_name": "mock",
        "request_json": {"prompt": "test"},
        "attempt_count": 1,
        "max_attempts": 3,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    })
    db_session.commit()
    
    retry_resp = client.post(f"/media/jobs/{job_id}/retry")
    assert retry_resp.status_code == 200
    data = retry_resp.json()
    assert data["status"] == "pending"


def test_p6_sync_mode(client):
    response = client.post("/media/portraits/generate?mode=sync", json={
        "npc_id": "npc-sync-test",
        "style": "anime",
    })
    assert response.status_code == 200
    data = response.json()
    assert "asset_id" in data
    assert "generation_status" in data


def test_p6_async_mode(client):
    response = client.post("/media/portraits/generate?mode=async", json={
        "npc_id": "npc-async-test",
        "style": "anime",
    })
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert "status" in data


def test_auth_required(db_engine):
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
        response = test_client.post("/media/jobs/portraits", json={
            "npc_id": "npc-no-auth",
        })
        assert response.status_code == 401
    
    app.dependency_overrides.clear()
