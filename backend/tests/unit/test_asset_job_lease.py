"""Tests for AssetJobRepository lease/heartbeat/stale recovery/dead-letter methods."""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import AssetGenerationJobModel
from llm_rpg.storage.repositories import AssetJobRepository

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def _make_job(repo, job_id, **overrides):
    data = {
        "id": f"id-{job_id}",
        "job_id": job_id,
        "asset_type": "portrait",
        "session_id": "sess-1",
        "status": "pending",
    }
    data.update(overrides)
    return repo.create_job(data)


class TestClaimNextPendingWithLease:
    def test_claims_pending_job_and_sets_lease(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")

        job = repo.claim_next_pending_with_lease(worker_id="worker-a", lease_seconds=300)

        assert job is not None
        assert job.job_id == "job-1"
        assert job.status == "processing"
        assert job.lease_owner == "worker-a"
        assert job.lease_expires_at is not None
        assert job.heartbeat_at is not None
        assert job.started_at is not None

    def test_lease_expires_at_is_now_plus_seconds(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")

        before = datetime.now()
        job = repo.claim_next_pending_with_lease(worker_id="w", lease_seconds=600)
        after = datetime.now()

        expected_min = before + timedelta(seconds=600)
        expected_max = after + timedelta(seconds=600)
        assert expected_min <= job.lease_expires_at <= expected_max

    def test_returns_none_when_no_pending_jobs(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1", status="processing")

        job = repo.claim_next_pending_with_lease(worker_id="w")
        assert job is None

    def test_double_claim_prevented_by_where_guard(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")

        job1 = repo.claim_next_pending_with_lease(worker_id="worker-a")
        assert job1 is not None

        job2 = repo.claim_next_pending_with_lease(worker_id="worker-b")
        assert job2 is None

    def test_respects_priority_order(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "low", priority=200)
        _make_job(repo, "high", priority=10)

        job = repo.claim_next_pending_with_lease(worker_id="w")
        assert job.job_id == "high"

    def test_filters_by_provider_name(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-dalle", provider_name="dalle")
        _make_job(repo, "job-mock", provider_name="mock")

        job = repo.claim_next_pending_with_lease(worker_id="w", provider_name="mock")
        assert job is not None
        assert job.job_id == "job-mock"

    def test_existing_claim_next_pending_still_works(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")

        job = repo.claim_next_pending()
        assert job is not None
        assert job.status == "processing"


class TestHeartbeat:
    def test_heartbeat_updates_fields(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")
        repo.claim_next_pending_with_lease(worker_id="worker-a", lease_seconds=300)

        before = datetime.now()
        result = repo.heartbeat("job-1", worker_id="worker-a", lease_seconds=300)
        after = datetime.now()

        assert result is not None
        assert result.heartbeat_at >= before
        assert result.heartbeat_at <= after
        assert result.lease_expires_at >= before + timedelta(seconds=300)

    def test_heartbeat_rejected_for_wrong_worker(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")
        repo.claim_next_pending_with_lease(worker_id="worker-a", lease_seconds=300)

        result = repo.heartbeat("job-1", worker_id="worker-b")
        assert result is None

    def test_heartbeat_returns_none_for_unknown_job(self, db_session):
        repo = AssetJobRepository(db_session)
        result = repo.heartbeat("nonexistent", worker_id="w")
        assert result is None


class TestRecoverStaleJobs:
    def test_recovers_stale_processing_job(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")
        repo.claim_next_pending_with_lease(worker_id="worker-a", lease_seconds=300)

        job = repo.get_by_job_id("job-1")
        job.lease_expires_at = datetime.now() - timedelta(seconds=1)
        db_session.commit()

        now = datetime.now()
        count = repo.recover_stale_jobs(now)

        assert count == 1
        refreshed = repo.get_by_job_id("job-1")
        assert refreshed.status == "pending"
        assert refreshed.lease_owner is None
        assert refreshed.lease_expires_at is None
        assert refreshed.heartbeat_at is None
        assert refreshed.started_at is None

    def test_does_not_recover_active_lease(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")
        repo.claim_next_pending_with_lease(worker_id="worker-a", lease_seconds=300)

        now = datetime.now()
        count = repo.recover_stale_jobs(now)
        assert count == 0

        job = repo.get_by_job_id("job-1")
        assert job.status == "processing"
        assert job.lease_owner == "worker-a"

    def test_does_not_recover_pending_job(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")

        count = repo.recover_stale_jobs(datetime.now())
        assert count == 0

    def test_recover_multiple_stale_jobs(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")
        _make_job(repo, "job-2")
        repo.claim_next_pending_with_lease(worker_id="w", lease_seconds=300)
        repo.claim_next_pending_with_lease(worker_id="w", lease_seconds=300)

        for jid in ["job-1", "job-2"]:
            job = repo.get_by_job_id(jid)
            job.lease_expires_at = datetime.now() - timedelta(seconds=1)
            db_session.commit()

        count = repo.recover_stale_jobs(datetime.now())
        assert count == 2


class TestMarkDeadLetter:
    def test_marks_job_as_dead_lettered(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")
        repo.claim_next_pending_with_lease(worker_id="w", lease_seconds=300)

        result = repo.mark_dead_letter("job-1", reason="Max retries exceeded")

        assert result is not None
        assert result.status == "dead_lettered"
        assert result.dead_lettered_at is not None
        assert result.dead_letter_reason == "Max retries exceeded"
        assert result.lease_owner is None
        assert result.lease_expires_at is None
        assert result.heartbeat_at is None

    def test_returns_none_for_unknown_job(self, db_session):
        repo = AssetJobRepository(db_session)
        result = repo.mark_dead_letter("nonexistent", reason="test")
        assert result is None

    def test_dead_lettered_job_not_claimed(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")
        repo.mark_dead_letter("job-1", reason="test")

        job = repo.claim_next_pending_with_lease(worker_id="w")
        assert job is None


class TestListDeadLettered:
    def test_lists_dead_lettered_jobs(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")
        _make_job(repo, "job-2")

        repo.mark_dead_letter("job-1", reason="reason-1")
        repo.mark_dead_letter("job-2", reason="reason-2")

        jobs = repo.list_dead_lettered()
        assert len(jobs) == 2
        job_ids = {j.job_id for j in jobs}
        assert job_ids == {"job-1", "job-2"}

    def test_does_not_list_non_dead_lettered(self, db_session):
        repo = AssetJobRepository(db_session)
        _make_job(repo, "job-1")
        _make_job(repo, "job-2", status="failed")

        jobs = repo.list_dead_lettered()
        assert len(jobs) == 0

    def test_respects_limit_and_offset(self, db_session):
        repo = AssetJobRepository(db_session)
        for i in range(5):
            _make_job(repo, f"job-{i}")
            repo.mark_dead_letter(f"job-{i}", reason=f"reason-{i}")

        page1 = repo.list_dead_lettered(limit=2, offset=0)
        assert len(page1) == 2

        page2 = repo.list_dead_lettered(limit=2, offset=2)
        assert len(page2) == 2

        page3 = repo.list_dead_lettered(limit=2, offset=4)
        assert len(page3) == 1
