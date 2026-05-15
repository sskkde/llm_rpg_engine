"""Integration tests for game and asset integration API endpoints."""

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.repositories import AssetJobRepository, UserRepository
from llm_rpg.models.assets import AssetJobStatus
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
    user_repo = UserRepository(db_session)
    user = user_repo.create({
        "username": "test_game_asset_user",
        "email": "game_asset_test@example.com",
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


# =============================================================================
# Job Status Tests
# =============================================================================

@pytest.mark.integration
class TestGetJobStatus:
    """Tests for GET /media/jobs/{job_id}."""

    def test_get_job_status_returns_200(self, client):
        create_resp = client.post("/media/jobs/portraits", json={
            "npc_id": "npc-status-int",
        })
        assert create_resp.status_code == 200
        job_id = create_resp.json()["job_id"]

        get_resp = client.get(f"/media/jobs/{job_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["job_id"] == job_id
        assert "status" in data

    def test_get_job_status_not_found_returns_404(self, client):
        response = client.get("/media/jobs/nonexistent-job-id")
        assert response.status_code == 404


# =============================================================================
# List Session Jobs Tests
# =============================================================================

@pytest.mark.integration
class TestListSessionJobs:
    """Tests for GET /media/sessions/{session_id}/jobs."""

    def test_list_session_jobs_returns_correct_count(self, client):
        session_id = "session-list-int"

        client.post("/media/jobs/portraits", json={
            "npc_id": "npc-list-int-1",
            "session_id": session_id,
        })
        client.post("/media/jobs/scenes", json={
            "location_id": "loc-list-int-1",
            "session_id": session_id,
        })
        client.post("/media/jobs/bgm", json={
            "mood": "calm",
            "session_id": session_id,
        })

        response = client.get(f"/media/sessions/{session_id}/jobs")
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) >= 3

    def test_list_session_jobs_empty_for_new_session(self, client):
        response = client.get("/media/sessions/brand-new-session/jobs")
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) == 0

    def test_list_session_jobs_filter_by_asset_type(self, client):
        session_id = "session-filter-int"

        client.post("/media/jobs/portraits", json={
            "npc_id": "npc-filter-1",
            "session_id": session_id,
        })
        client.post("/media/jobs/portraits", json={
            "npc_id": "npc-filter-2",
            "session_id": session_id,
        })
        client.post("/media/jobs/scenes", json={
            "location_id": "loc-filter-1",
            "session_id": session_id,
        })

        response = client.get(f"/media/sessions/{session_id}/jobs?asset_type=portrait")
        assert response.status_code == 200
        jobs = response.json()
        for job in jobs:
            assert job["asset_type"] == "portrait"


# =============================================================================
# Retry Failed Job Tests
# =============================================================================

@pytest.mark.integration
class TestRetryFailedJob:
    """Tests for POST /media/jobs/{job_id}/retry."""

    def test_retry_failed_job_returns_pending(self, client, db_session):
        job_repo = AssetJobRepository(db_session)
        job_id = str(uuid.uuid4())
        job_repo.create_job({
            "id": str(uuid.uuid4()),
            "job_id": job_id,
            "asset_type": "portrait",
            "status": AssetJobStatus.FAILED.value,
            "provider_name": "mock",
            "request_json": {"npc_id": "npc-retry-int"},
            "attempt_count": 1,
            "max_attempts": 3,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "error_message": "Test failure",
        })
        db_session.commit()

        retry_resp = client.post(f"/media/jobs/{job_id}/retry")
        assert retry_resp.status_code == 200
        data = retry_resp.json()
        assert data["status"] == "pending"

    def test_retry_nonexistent_job_returns_404(self, client):
        response = client.post("/media/jobs/nonexistent-retry-id/retry")
        assert response.status_code == 404

    def test_retry_non_failed_job_returns_404(self, client):
        create_resp = client.post("/media/jobs/portraits", json={
            "npc_id": "npc-not-failed",
        })
        job_id = create_resp.json()["job_id"]

        retry_resp = client.post(f"/media/jobs/{job_id}/retry")
        assert retry_resp.status_code == 404


# =============================================================================
# Cancel Pending Job Tests
# =============================================================================

@pytest.mark.integration
class TestCancelPendingJob:
    """Tests for POST /media/jobs/{job_id}/cancel."""

    def test_cancel_pending_job_returns_cancelled(self, client, db_session):
        job_repo = AssetJobRepository(db_session)
        job_id = str(uuid.uuid4())
        job_repo.create_job({
            "id": str(uuid.uuid4()),
            "job_id": job_id,
            "asset_type": "scene",
            "status": AssetJobStatus.PENDING.value,
            "provider_name": "mock",
            "request_json": {"location_id": "loc-cancel-int"},
            "attempt_count": 0,
            "max_attempts": 3,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        })
        db_session.commit()

        cancel_resp = client.post(f"/media/jobs/{job_id}/cancel")
        assert cancel_resp.status_code == 200
        data = cancel_resp.json()
        assert data["status"] == "cancelled"

    def test_cancel_nonexistent_job_returns_404(self, client):
        response = client.post("/media/jobs/nonexistent-cancel-id/cancel")
        assert response.status_code == 404

    def test_cancel_completed_job_returns_404(self, client, db_session):
        job_repo = AssetJobRepository(db_session)
        job_id = str(uuid.uuid4())
        job_repo.create_job({
            "id": str(uuid.uuid4()),
            "job_id": job_id,
            "asset_type": "bgm",
            "status": AssetJobStatus.COMPLETED.value,
            "provider_name": "mock",
            "request_json": {"mood": "happy"},
            "attempt_count": 1,
            "max_attempts": 3,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        })
        db_session.commit()

        cancel_resp = client.post(f"/media/jobs/{job_id}/cancel")
        assert cancel_resp.status_code == 404


# =============================================================================
# Job Not Found Tests
# =============================================================================

@pytest.mark.integration
class TestJobNotFound:
    """Tests for 404 responses on non-existent jobs."""

    def test_job_not_found(self, client):
        response = client.get("/media/jobs/nonexistent-job-id")
        assert response.status_code == 404


# =============================================================================
# Async Mode Tests
# =============================================================================

@pytest.mark.integration
class TestAsyncMode:
    """Tests for async generation mode."""

    def test_async_mode_generates_job(self, client):
        response = client.post("/media/portraits/generate?mode=async", json={
            "npc_id": "npc-async-int",
            "style": "anime",
        })
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert "status" in data


# =============================================================================
# Sync Mode Tests
# =============================================================================

@pytest.mark.integration
class TestSyncMode:
    """Tests for sync generation mode."""

    def test_sync_mode_generates_asset(self, client):
        response = client.post("/media/portraits/generate?mode=sync", json={
            "npc_id": "npc-sync-int",
            "style": "realistic",
        })
        assert response.status_code == 200
        data = response.json()
        assert "asset_id" in data
        assert "generation_status" in data
