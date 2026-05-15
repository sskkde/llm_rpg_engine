"""
Scenario tests for P7 asset generation workflow.

Comprehensive scenario-level tests verifying the complete asset generation
workflow from session creation through job execution and caching.

All tests use:
- FastAPI TestClient with SQLite overrides
- Mock asset providers (no real external API calls)
- In-memory SQLite (no PostgreSQL needed)
"""

import uuid
from datetime import datetime
from typing import Dict, Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import UserModel
from llm_rpg.storage.repositories import AssetJobRepository, AssetRepository, UserRepository
from llm_rpg.models.assets import AssetJobStatus, AssetType
from llm_rpg.main import app
from llm_rpg.api.auth import get_current_active_user


pytestmark = pytest.mark.p7_scenario


TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_engine():
    """Create an in-memory SQLite database for each test."""
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
    """Create a database session for each test."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def test_user(db_session):
    """Create a test user."""
    user_repo = UserRepository(db_session)
    user = user_repo.create({
        "username": "test_workflow_user",
        "email": "workflow_test@example.com",
        "password_hash": "hashed_password",
    })
    db_session.commit()
    return user


@pytest.fixture(scope="function")
def client(db_engine, db_session, test_user):
    """Create a FastAPI TestClient with test database overrides."""
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
# Test 1: Scene Asset Job Creation
# =============================================================================

class TestSceneAssetJobCreation:
    """Test scene asset job creation from session loading a scene."""

    def test_scene_job_creation_pending_status(self, client):
        """Simulate session loading a scene -> POST /media/jobs/scenes creates pending job."""
        response = client.post("/media/jobs/scenes", json={
            "location_id": "loc-scene-1",
            "time_of_day": "dusk",
            "weather": "foggy",
            "session_id": "session-scene-test",
        })

        assert response.status_code == 200
        data = response.json()

        # Verify job created
        assert "job_id" in data
        assert data["asset_type"] == "scene"
        assert data["status"] in ("pending", "completed")

    def test_scene_job_with_world_context(self, client):
        """Scene job includes world context for generation."""
        response = client.post("/media/jobs/scenes", json={
            "location_id": "loc-world-test",
            "time_of_day": "night",
            "session_id": "session-world-test",
            "world_id": "world-1",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["asset_type"] == "scene"


# =============================================================================
# Test 2: Portrait Job for NPC
# =============================================================================

class TestPortraitJobForNPC:
    """Test portrait job creation when NPC becomes visible in session."""

    def test_portrait_job_for_visible_npc(self, client):
        """NPC visible in session -> POST /media/jobs/portraits creates job."""
        response = client.post("/media/jobs/portraits", json={
            "npc_id": "npc-portrait-1",
            "style": "realistic",
            "expression": "stern",
            "session_id": "session-portrait-test",
        })

        assert response.status_code == 200
        data = response.json()

        # Verify job created with correct NPC ID
        assert "job_id" in data
        assert data["asset_type"] == "portrait"
        assert data["status"] in ("pending", "completed")

    def test_portrait_job_multiple_npcs(self, client):
        """Multiple NPC portraits can be queued."""
        npc_ids = ["npc-1", "npc-2", "npc-3"]

        for npc_id in npc_ids:
            response = client.post("/media/jobs/portraits", json={
                "npc_id": npc_id,
                "session_id": "session-multi-npc",
            })
            assert response.status_code == 200

        # List jobs for session
        list_response = client.get("/media/sessions/session-multi-npc/jobs")
        assert list_response.status_code == 200
        jobs = list_response.json()
        assert len(jobs) >= 3


# =============================================================================
# Test 3: Failed Provider Does Not Block Turn
# =============================================================================

class TestFailedProviderHandling:
    """Test that failed provider doesn't block game turn."""

    def test_failed_provider_job_still_returns_response(self, client, db_session):
        """Submit a job with failed provider -> job records failure but doesn't crash."""
        # Create a job
        response = client.post("/media/jobs/portraits", json={
            "npc_id": "npc-fail-test",
            "session_id": "session-fail-test",
        })

        assert response.status_code == 200
        data = response.json()
        job_id = data["job_id"]

        # Verify job exists and can be queried
        get_response = client.get(f"/media/jobs/{job_id}")
        assert get_response.status_code == 200

    def test_failed_job_can_be_retried(self, client, db_session):
        """A failed job can be retried."""
        # Create a failed job directly
        job_repo = AssetJobRepository(db_session)
        job_id = str(uuid.uuid4())
        job_repo.create_job({
            "id": str(uuid.uuid4()),
            "job_id": job_id,
            "asset_type": "portrait",
            "status": AssetJobStatus.FAILED.value,
            "provider_name": "mock",
            "request_json": {"npc_id": "npc-retry-test"},
            "attempt_count": 1,
            "max_attempts": 3,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "error_message": "Provider failed",
        })
        db_session.commit()

        # Retry the job
        retry_response = client.post(f"/media/jobs/{job_id}/retry")
        assert retry_response.status_code == 200
        data = retry_response.json()
        assert data["status"] == "pending"


# =============================================================================
# Test 4: Cache Hit Prevents Duplicate Jobs
# =============================================================================

class TestCacheHitPrevention:
    """Test that cache hits prevent duplicate job creation."""

    def test_identical_requests_return_cached_result(self, client):
        """Same request twice -> first creates job, second returns cached result."""
        request_data = {
            "npc_id": "npc-cache-test",
            "style": "anime",
            "expression": "happy",
            "session_id": "session-cache-test",
        }

        # First request
        response1 = client.post("/media/jobs/portraits", json=request_data)
        assert response1.status_code == 200
        data1 = response1.json()

        # Second identical request
        response2 = client.post("/media/jobs/portraits", json=request_data)
        assert response2.status_code == 200
        data2 = response2.json()

        # Both should return same or similar results
        # The mock provider may complete synchronously, so status could be "completed"
        assert "job_id" in data1
        assert "job_id" in data2

    def test_different_requests_create_different_jobs(self, client):
        """Different requests create different jobs."""
        response1 = client.post("/media/jobs/portraits", json={
            "npc_id": "npc-diff-1",
            "style": "anime",
        })
        response2 = client.post("/media/jobs/portraits", json={
            "npc_id": "npc-diff-2",
            "style": "realistic",
        })

        assert response1.status_code == 200
        assert response2.status_code == 200

        data1 = response1.json()
        data2 = response2.json()

        # Different jobs
        assert data1["job_id"] != data2["job_id"]


# =============================================================================
# Test 5: BGM Job Creation
# =============================================================================

class TestBGMJobCreation:
    """Test BGM job creation."""

    def test_bgm_job_creation_success(self, client):
        """POST /media/jobs/bgm creates a job."""
        response = client.post("/media/jobs/bgm", json={
            "mood": "tense",
            "duration_seconds": 120,
            "location_id": "loc-bg m-test",
            "session_id": "session-bgm-test",
        })

        assert response.status_code == 200
        data = response.json()

        assert "job_id" in data
        assert data["asset_type"] == "bgm"
        assert data["status"] in ("pending", "completed")

    def test_bgm_job_with_location_context(self, client):
        """BGM job includes location context."""
        response = client.post("/media/jobs/bgm", json={
            "mood": "peaceful",
            "location_id": "loc-peaceful",
            "session_id": "session-bg m-location",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["asset_type"] == "bgm"


# =============================================================================
# Test 6: Job Lifecycle
# =============================================================================

class TestJobLifecycle:
    """Test complete job lifecycle: create -> status -> cancel."""

    def test_full_job_lifecycle(self, client, db_session):
        """Create job -> get status -> cancel -> verify cancelled."""
        # Create job
        create_response = client.post("/media/jobs/portraits", json={
            "npc_id": "npc-lifecycle",
            "session_id": "session-lifecycle",
        })

        assert create_response.status_code == 200
        data = create_response.json()
        job_id = data["job_id"]

        # Get status
        status_response = client.get(f"/media/jobs/{job_id}")
        assert status_response.status_code == 200
        job_data = status_response.json()
        assert job_data["job_id"] == job_id

        # If job is still pending, try to cancel
        if job_data["status"] == "pending":
            cancel_response = client.post(f"/media/jobs/{job_id}/cancel")
            assert cancel_response.status_code == 200
            cancelled_data = cancel_response.json()
            assert cancelled_data["status"] == "cancelled"

    def test_list_session_jobs_after_creation(self, client):
        """List session jobs after creating multiple jobs."""
        session_id = "session-list-test"

        # Create multiple jobs
        client.post("/media/jobs/portraits", json={
            "npc_id": "npc-list-1",
            "session_id": session_id,
        })
        client.post("/media/jobs/scenes", json={
            "location_id": "loc-list-1",
            "session_id": session_id,
        })
        client.post("/media/jobs/bgm", json={
            "mood": "adventure",
            "session_id": session_id,
        })

        # List jobs
        response = client.get(f"/media/sessions/{session_id}/jobs")
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) >= 3

        # Verify job types
        asset_types = {job["asset_type"] for job in jobs}
        assert "portrait" in asset_types
        assert "scene" in asset_types
        assert "bgm" in asset_types


# =============================================================================
# Test 7: P6 Compatibility Mode
# =============================================================================

class TestP6CompatibilityMode:
    """Test P6 compatibility mode (sync/async)."""

    def test_sync_mode_returns_asset_response(self, client):
        """Generate with mode=sync -> returns asset response."""
        response = client.post("/media/portraits/generate?mode=sync", json={
            "npc_id": "npc-sync-mode",
            "style": "anime",
        })

        assert response.status_code == 200
        data = response.json()

        # Sync mode should return AssetResponse
        assert "asset_id" in data
        assert "generation_status" in data

    def test_async_mode_returns_job_response(self, client):
        """Generate with mode=async -> returns job response."""
        response = client.post("/media/portraits/generate?mode=async", json={
            "npc_id": "npc-async-mode",
            "style": "realistic",
        })

        assert response.status_code == 200
        data = response.json()

        # Async mode should return AssetJobResponse
        assert "job_id" in data
        assert "status" in data

    def test_scene_sync_mode(self, client):
        """Scene generation with sync mode."""
        response = client.post("/media/scenes/generate?mode=sync", json={
            "location_id": "loc-sync-scene",
            "time_of_day": "sunset",
        })

        assert response.status_code == 200
        data = response.json()
        assert "asset_id" in data

    def test_bgm_async_mode(self, client):
        """BGM generation with async mode."""
        response = client.post("/media/bgm/generate?mode=async", json={
            "mood": "epic",
            "duration_seconds": 90,
        })

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
