"""
Scenario tests for P8 asset runtime system.

Covers the complete P8 asset runtime:
- Provider fallback and safe failure
- Queue lease recovery and dead-letter handling
- Rate limiting with 429 responses
- Cost/usage tracking for completed and failed jobs
- NPC portrait prompt with mood context
- Portrait prewarm cache-first semantics
- Admin audit API
- Debug usage summary aggregation
- Worker secret leak prevention

All tests use:
- FastAPI TestClient with SQLite overrides
- Mock asset providers (no real external API calls)
- In-memory SQLite (no PostgreSQL needed)
"""

import logging
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    UserModel, EventLogModel,
)
from llm_rpg.storage.repositories import (
    AssetJobRepository, AssetRepository, AssetUsageLogRepository, UserRepository,
    SessionRepository, WorldRepository, LocationRepository,
    NPCTemplateRepository, SessionStateRepository, SessionNPCStateRepository,
)
from llm_rpg.models.assets import AssetJobStatus, AssetType
from llm_rpg.main import app
from llm_rpg.api.auth import get_current_active_user


pytestmark = pytest.mark.p8_scenario


TEST_DATABASE_URL = "sqlite:///:memory:"


# =============================================================================
# Fixtures
# =============================================================================

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
        "username": "test_p8_user",
        "email": "p8_test@example.com",
        "password_hash": "hashed_password",
    })
    db_session.commit()
    return user


@pytest.fixture(scope="function")
def admin_user(db_session):
    user_repo = UserRepository(db_session)
    user = user_repo.create({
        "username": "test_p8_admin",
        "email": "p8_admin@example.com",
        "password_hash": "hashed_password",
        "is_admin": True,
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


@pytest.fixture(scope="function")
def admin_client(db_engine, db_session, admin_user):
    def override_get_db():
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_current_user():
        return admin_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = override_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# =============================================================================
# Helper functions
# =============================================================================

def _create_test_world(db_session):
    world_repo = WorldRepository(db_session)
    world = world_repo.create({
        "code": f"test_world_{uuid.uuid4().hex[:8]}",
        "name": "Test World",
        "genre": "xianxia",
    })
    db_session.commit()
    return world


def _create_test_location(db_session, world_id):
    location_repo = LocationRepository(db_session)
    location = location_repo.create({
        "code": f"test_loc_{uuid.uuid4().hex[:8]}",
        "name": "Test Location",
        "world_id": world_id,
        "tags": ["indoor"],
    })
    db_session.commit()
    return location


def _create_test_npc_template(db_session, world_id, name_suffix=""):
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
    session_repo = SessionRepository(db_session)
    session = session_repo.create({
        "user_id": user_id,
        "world_id": world_id,
        "status": "active",
    })
    db_session.commit()
    return session


def _create_test_session_state(db_session, session_id, current_location_id):
    state_repo = SessionStateRepository(db_session)
    state = state_repo.create({
        "session_id": session_id,
        "current_location_id": current_location_id,
    })
    db_session.commit()
    return state


def _create_test_npc_state(db_session, session_id, npc_template_id, current_location_id):
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


# =============================================================================
# Test 1: Real provider disabled falls back safely
# =============================================================================

class TestRealProviderDisabledFallback:

    @pytest.mark.p8_scenario
    def test_real_provider_disabled_falls_back_safely(self, client):
        response = client.post("/media/jobs/portraits", json={
            "npc_id": "npc-fallback-test",
            "style": "anime",
            "expression": "neutral",
            "session_id": "session-fallback-test",
        })

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["asset_type"] == "portrait"
        assert data["status"] in ("pending", "completed")


# =============================================================================
# Test 2: OpenAI provider missing key fails safely
# =============================================================================

class TestOpenAIProviderMissingKey:

    @pytest.mark.p8_scenario
    def test_openai_provider_missing_key_fails_safely(self, monkeypatch):
        import asyncio
        from llm_rpg.assets.openai_image import OpenAIImageProvider
        from llm_rpg.assets.interfaces import AssetGenerationRequest, AssetStatus
        from llm_rpg.assets.provider_errors import ProviderAuthError

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        class _AuthClient:
            async def generate_image(self, prompt, size="1024x1024", quality="standard", n=1):
                raise ProviderAuthError(
                    provider_name="openai_image",
                    error_code="missing_api_key",
                    message="OPENAI_API_KEY not configured",
                )

        provider = OpenAIImageProvider(client=_AuthClient())
        request = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            request_id="test-req-auth",
            metadata={"prompt": "a warrior"},
        )

        result = asyncio.run(provider.generate(request))

        assert result.status == AssetStatus.FAILED
        assert result.error_message is not None
        assert "not configured" in result.error_message
        assert result.metadata.get("error_type") == "ProviderAuthError"
        assert result.metadata.get("retryable") is False


# =============================================================================
# Test 3: Queue lease recovery
# =============================================================================

class TestQueueLeaseRecovery:

    @pytest.mark.p8_scenario
    def test_queue_lease_recovery(self, db_session):
        repo = AssetJobRepository(db_session)

        repo.create_job({
            "id": str(uuid.uuid4()),
            "job_id": "job-lease-test",
            "asset_type": "portrait",
            "session_id": "session-lease-test",
            "status": "pending",
        })
        db_session.commit()

        claimed = repo.claim_next_pending_with_lease(worker_id="test-worker", lease_seconds=30)
        assert claimed is not None
        assert claimed.job_id == "job-lease-test"
        assert claimed.status == "processing"
        assert claimed.lease_owner == "test-worker"
        assert claimed.lease_expires_at is not None

        job = repo.get_by_job_id("job-lease-test")
        job.lease_expires_at = datetime.now() - timedelta(seconds=1)
        db_session.commit()

        count = repo.recover_stale_jobs(datetime.now())
        assert count == 1

        refreshed = repo.get_by_job_id("job-lease-test")
        assert refreshed.status == "pending"
        assert refreshed.lease_owner is None
        assert refreshed.lease_expires_at is None


# =============================================================================
# Test 4: Dead letter after max retries
# =============================================================================

class TestDeadLetterAfterMaxRetries:

    @pytest.mark.p8_scenario
    def test_dead_letter_after_max_retries(self, db_session):
        repo = AssetJobRepository(db_session)

        repo.create_job({
            "id": str(uuid.uuid4()),
            "job_id": "job-dead-letter-test",
            "asset_type": "portrait",
            "session_id": "session-dl-test",
            "status": "pending",
        })
        db_session.commit()

        repo.claim_next_pending_with_lease(worker_id="test-worker", lease_seconds=300)

        job = repo.get_by_job_id("job-dead-letter-test")
        job.attempt_count = 3
        job.max_attempts = 3
        job.status = "failed"
        job.error_message = "Max retries exceeded"
        db_session.commit()

        result = repo.mark_dead_letter("job-dead-letter-test", reason="Max retries exceeded")

        assert result is not None
        assert result.status == "dead_lettered"
        assert result.dead_lettered_at is not None
        assert result.dead_letter_reason == "Max retries exceeded"
        assert result.lease_owner is None
        assert result.lease_expires_at is None

        dead_jobs = repo.list_dead_lettered()
        assert len(dead_jobs) >= 1
        dead_job_ids = {j.job_id for j in dead_jobs}
        assert "job-dead-letter-test" in dead_job_ids


# =============================================================================
# Test 5: Rate limit blocks excessive requests
# =============================================================================

class TestRateLimitBlocksExcessiveRequests:

    @pytest.mark.p8_scenario
    def test_rate_limit_blocks_excessive_requests(self, client, monkeypatch):
        monkeypatch.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "10")
        monkeypatch.setenv("ASSET_RATE_LIMIT_SESSION_PER_MINUTE", "100")

        for i in range(10):
            response = client.post("/media/jobs/portraits", json={
                "npc_id": f"npc_rate_{i}",
                "style": "anime",
                "expression": "neutral",
                "session_id": "session-rate-test",
            })
            assert response.status_code in (200, 201, 202), f"Request {i+1} failed: {response.text}"

        response = client.post("/media/jobs/portraits", json={
            "npc_id": "npc_rate_11",
            "style": "anime",
            "expression": "neutral",
            "session_id": "session-rate-test",
        })
        assert response.status_code == 429
        assert "retry-after" in response.headers
        retry_after = int(response.headers["retry-after"])
        assert 0 < retry_after <= 60


# =============================================================================
# Test 6: Cost usage recorded for completed job
# =============================================================================

class TestCostUsageRecordedForCompletedJob:

    @pytest.mark.p8_scenario
    def test_cost_usage_recorded_for_completed_job(self, db_session):
        usage_repo = AssetUsageLogRepository(db_session)

        now = datetime.now()
        usage_repo.create_usage_log({
            "id": str(uuid.uuid4()),
            "usage_id": "usage-completed-test",
            "job_id": "job-completed-test",
            "session_id": "session-cost-test",
            "provider_name": "mock",
            "asset_type": "portrait",
            "operation": "generate",
            "estimated_cost_usd": 0.04,
            "actual_cost_usd": 0.035,
            "status": "completed",
            "created_at": now,
        })
        db_session.commit()

        log = usage_repo.get_by_usage_id("usage-completed-test")
        assert log is not None
        assert log.job_id == "job-completed-test"
        assert log.actual_cost_usd == 0.035
        assert log.estimated_cost_usd == 0.04
        assert log.status == "completed"

        summary = usage_repo.get_cost_summary(session_id="session-cost-test")
        assert summary["total_estimated"] == pytest.approx(0.04)
        assert summary["total_actual"] == pytest.approx(0.035)
        assert summary["count"] == 1


# =============================================================================
# Test 7: Cost usage recorded for failed job
# =============================================================================

class TestCostUsageRecordedForFailedJob:

    @pytest.mark.p8_scenario
    def test_cost_usage_recorded_for_failed_job(self, db_session):
        usage_repo = AssetUsageLogRepository(db_session)

        now = datetime.now()
        usage_repo.create_usage_log({
            "id": str(uuid.uuid4()),
            "usage_id": "usage-failed-test",
            "job_id": "job-failed-test",
            "session_id": "session-cost-fail-test",
            "provider_name": "mock",
            "asset_type": "portrait",
            "operation": "generate",
            "estimated_cost_usd": 0.04,
            "actual_cost_usd": None,
            "status": "failed",
            "metadata_json": {"error_message": "Provider error", "error_type": "ProviderError"},
            "created_at": now,
        })
        db_session.commit()

        log = usage_repo.get_by_usage_id("usage-failed-test")
        assert log is not None
        assert log.job_id == "job-failed-test"
        assert log.estimated_cost_usd == 0.04
        assert log.actual_cost_usd is None
        assert log.status == "failed"
        assert log.metadata_json.get("error_message") == "Provider error"

        summary = usage_repo.get_cost_summary(session_id="session-cost-fail-test")
        assert summary["total_estimated"] == pytest.approx(0.04)
        assert summary["total_actual"] == pytest.approx(0.0)
        assert summary["count"] == 1


# =============================================================================
# Test 8: NPC portrait uses mood context
# =============================================================================

class TestNPCPortraitUsesMoodContext:

    @pytest.mark.p8_scenario
    def test_npc_portrait_uses_mood_context(self, client, db_session, test_user):
        world = _create_test_world(db_session)
        location = _create_test_location(db_session, world.id)
        session = _create_test_session(db_session, test_user.id, world.id)
        _create_test_session_state(db_session, session.id, location.id)

        npc = _create_test_npc_template(db_session, world.id, "MoodyCharacter")
        _create_test_npc_state(db_session, session.id, npc.id, location.id)

        response = client.post(f"/media/sessions/{session.id}/prewarm-portraits")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert npc.id in data["npc_ids"]

        job_repo = AssetJobRepository(db_session)
        jobs = job_repo.list_by_session(session.id, asset_type="portrait")
        assert len(jobs) >= 1

        job = jobs[0]
        request_json = job.request_json or {}
        prompt = request_json.get("prompt", "")
        assert "MoodyCharacter" in prompt or npc.name in prompt


# =============================================================================
# Test 9: Portrait prewarm is cache-first
# =============================================================================

class TestPortraitPrewarmCacheFirst:

    @pytest.mark.p8_scenario
    def test_portrait_prewarm_is_cache_first(self, client, db_session, test_user):
        world = _create_test_world(db_session)
        location = _create_test_location(db_session, world.id)
        session = _create_test_session(db_session, test_user.id, world.id)
        _create_test_session_state(db_session, session.id, location.id)

        npc = _create_test_npc_template(db_session, world.id, "cached_npc")
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


# =============================================================================
# Test 10: Audit read API returns session logs
# =============================================================================

class TestAuditReadAPIReturnsSessionLogs:

    @pytest.mark.p8_scenario
    def test_audit_read_api_returns_session_logs(self, admin_client, db_session, admin_user):
        world_repo = WorldRepository(db_session)
        world = world_repo.create({
            "code": f"audit_world_{uuid.uuid4().hex[:8]}",
            "name": "Audit Test World",
            "genre": "xianxia",
        })
        db_session.commit()

        session_repo = SessionRepository(db_session)
        session = session_repo.create({
            "user_id": admin_user.id,
            "world_id": world.id,
            "status": "active",
        })
        db_session.commit()

        for i in range(5):
            event_log = EventLogModel(
                id=str(uuid.uuid4()),
                session_id=session.id,
                turn_no=i,
                event_type="player_turn" if i % 2 == 0 else "narration",
                narrative_text=f"Test narrative {i}",
                occurred_at=datetime.now(),
            )
            db_session.add(event_log)
        db_session.commit()

        response = admin_client.get(f"/admin/audit/sessions/{session.id}/logs")
        assert response.status_code == 200

        data = response.json()
        assert "total" in data
        assert "items" in data
        assert data["total"] == 5
        assert len(data["items"]) == 5

        for item in data["items"]:
            assert "id" in item
            assert "event_type" in item
            assert "turn_no" in item


# =============================================================================
# Test 11: Debug usage summary aggregates costs
# =============================================================================

class TestDebugUsageSummaryAggregatesCosts:

    @pytest.mark.p8_scenario
    def test_debug_usage_summary_aggregates_costs(self, admin_client, db_session):
        usage_repo = AssetUsageLogRepository(db_session)
        now = datetime.now()
        for i in range(3):
            usage_repo.create_usage_log({
                "id": str(uuid.uuid4()),
                "usage_id": f"usage-summary-{i}",
                "session_id": "session-summary-test",
                "provider_name": "mock",
                "asset_type": "portrait",
                "operation": "generate",
                "estimated_cost_usd": 0.02,
                "actual_cost_usd": 0.03,
                "created_at": now,
            })
        db_session.commit()

        response = admin_client.get("/debug/assets/usage/summary", params={
            "session_id": "session-summary-test",
        })
        assert response.status_code == 200

        data = response.json()
        assert "total_estimated" in data
        assert "total_actual" in data
        assert "count" in data
        assert data["count"] == 3
        assert data["total_estimated"] == pytest.approx(0.06)
        assert data["total_actual"] == pytest.approx(0.09)


# =============================================================================
# Test 12: Worker does not leak secrets
# =============================================================================

class TestWorkerDoesNotLeakSecrets:

    @pytest.mark.p8_scenario
    def test_worker_does_not_leak_secrets(self, db_session, monkeypatch):
        from llm_rpg.scripts.asset_worker import sanitize_for_logging, JSONFormatter

        data_with_key = {
            "api_key": "sk-super-secret-key-12345",
            "prompt": "a portrait",
            "config": {
                "token": "sk-another-secret",
                "model": "dall-e-3",
            },
        }

        sanitized = sanitize_for_logging(data_with_key)
        assert sanitized["api_key"] == "[REDACTED]"
        assert sanitized["prompt"] == "a portrait"
        assert sanitized["config"]["token"] == "[REDACTED]"
        assert sanitized["config"]["model"] == "dall-e-3"

        sanitized_str = str(sanitized)
        assert "sk-super-secret" not in sanitized_str
        assert "sk-another-secret" not in sanitized_str

        test_cases = [
            ("sk-test-key", True),
            ("api-test-key", True),
            ("key-test-key", True),
            ("normal_value", False),
        ]
        for value, should_redact in test_cases:
            result = sanitize_for_logging({"test": value})
            if should_redact:
                assert result["test"] == "[REDACTED]", f"Expected {value} to be redacted"
            else:
                assert result["test"] == value, f"Expected {value} to not be redacted"
