"""Tests for AssetQueueBackend implementations."""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import AssetGenerationJobModel
from llm_rpg.storage.repositories import AssetJobRepository
from llm_rpg.assets.queue import (
    InProcessAssetQueueBackend,
    RQAssetQueueBackend,
    CeleryAssetQueueBackend,
    get_queue_backend,
)

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def job_repo(db_session):
    return AssetJobRepository(db_session)


@pytest.fixture
def queue_backend(job_repo):
    return InProcessAssetQueueBackend(job_repo)


class TestInProcessAssetQueueBackend:
    def test_enqueue_existing_job(self, queue_backend, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
        })
        result = queue_backend.enqueue("pub-1")
        assert result is True

    def test_enqueue_nonexistent_job(self, queue_backend):
        result = queue_backend.enqueue("nonexistent")
        assert result is False

    def test_enqueue_updates_priority(self, queue_backend, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
            "priority": 100,
        })
        queue_backend.enqueue("pub-1", priority=50)
        job = job_repo.get_by_job_id("pub-1")
        assert job.priority == 50

    def test_enqueue_ensures_pending_status(self, queue_backend, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "completed",
        })
        queue_backend.enqueue("pub-1")
        job = job_repo.get_by_job_id("pub-1")
        assert job.status == "pending"

    def test_dequeue_returns_pending_job(self, queue_backend, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
        })
        job = queue_backend.dequeue()
        assert job is not None
        assert job.job_id == "pub-1"
        assert job.status == "processing"

    def test_dequeue_returns_none_when_no_pending(self, queue_backend, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "completed",
        })
        job = queue_backend.dequeue()
        assert job is None

    def test_dequeue_with_provider_filter(self, queue_backend, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
            "provider_name": "dalle",
        })
        job_repo.create_job({
            "id": "job-2",
            "job_id": "pub-2",
            "asset_type": "scene",
            "status": "pending",
            "provider_name": "stable-diffusion",
        })
        job = queue_backend.dequeue(provider_name="dalle")
        assert job is not None
        assert job.job_id == "pub-1"

    def test_dequeue_respects_priority(self, queue_backend, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
            "priority": 200,
        })
        job_repo.create_job({
            "id": "job-2",
            "job_id": "pub-2",
            "asset_type": "scene",
            "status": "pending",
            "priority": 50,
        })
        job = queue_backend.dequeue()
        assert job is not None
        assert job.job_id == "pub-2"

    def test_ack_marks_completed(self, queue_backend, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "processing",
        })
        result = queue_backend.ack("pub-1")
        assert result is True
        job = job_repo.get_by_job_id("pub-1")
        assert job.status == "completed"

    def test_ack_nonexistent_job(self, queue_backend):
        result = queue_backend.ack("nonexistent")
        assert result is False

    def test_nack_marks_failed(self, queue_backend, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "processing",
        })
        result = queue_backend.nack(
            "pub-1",
            error_message="Test error",
            error_type="TestError",
        )
        assert result is True
        job = job_repo.get_by_job_id("pub-1")
        assert job.status == "failed"
        assert job.error_message == "Test error"

    def test_nack_schedules_retry(self, queue_backend, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "processing",
            "attempt_count": 0,
        })
        retry_at = datetime.now() + timedelta(minutes=5)
        result = queue_backend.nack("pub-1", retry_at=retry_at)
        assert result is True
        job = job_repo.get_by_job_id("pub-1")
        assert job.status == "pending"
        assert job.attempt_count == 1

    def test_nack_nonexistent_job(self, queue_backend):
        result = queue_backend.nack("nonexistent")
        assert result is False

    def test_size(self, queue_backend, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
        })
        job_repo.create_job({
            "id": "job-2",
            "job_id": "pub-2",
            "asset_type": "scene",
            "status": "completed",
        })
        assert queue_backend.size() == 2

    def test_pending_count(self, queue_backend, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
        })
        job_repo.create_job({
            "id": "job-2",
            "job_id": "pub-2",
            "asset_type": "scene",
            "status": "completed",
        })
        job_repo.create_job({
            "id": "job-3",
            "job_id": "pub-3",
            "asset_type": "bgm",
            "status": "pending",
        })
        assert queue_backend.pending_count() == 2

    def test_full_enqueue_dequeue_ack_cycle(self, queue_backend, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
            "priority": 100,
        })
        
        assert queue_backend.enqueue("pub-1") is True
        assert queue_backend.pending_count() == 1
        
        job = queue_backend.dequeue()
        assert job is not None
        assert job.job_id == "pub-1"
        assert queue_backend.pending_count() == 0
        
        assert queue_backend.ack("pub-1") is True
        final_job = job_repo.get_by_job_id("pub-1")
        assert final_job.status == "completed"


class TestSQLiteCompatClaimNextPending:
    def test_claim_next_pending_works_with_sqlite(self, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
            "priority": 100,
        })
        job = job_repo.claim_next_pending()
        assert job is not None
        assert job.job_id == "pub-1"
        assert job.status == "processing"

    def test_claim_next_pending_atomic_update(self, job_repo):
        job_repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
        })
        job1 = job_repo.claim_next_pending()
        assert job1 is not None
        job2 = job_repo.claim_next_pending()
        assert job2 is None


class TestGetQueueBackend:
    def test_get_in_process_backend(self, job_repo):
        backend = get_queue_backend("in_process", job_repository=job_repo)
        assert isinstance(backend, InProcessAssetQueueBackend)

    def test_get_default_backend(self, job_repo):
        backend = get_queue_backend(job_repository=job_repo)
        assert isinstance(backend, InProcessAssetQueueBackend)

    def test_get_rq_backend_raises_not_implemented(self, job_repo):
        with pytest.raises(NotImplementedError) as exc_info:
            get_queue_backend("rq")
        assert "RQAssetQueueBackend" in str(exc_info.value)

    def test_get_celery_backend_raises_not_implemented(self, job_repo):
        with pytest.raises(NotImplementedError) as exc_info:
            get_queue_backend("celery")
        assert "CeleryAssetQueueBackend" in str(exc_info.value)

    def test_get_unknown_backend_raises_value_error(self, job_repo):
        with pytest.raises(ValueError) as exc_info:
            get_queue_backend("unknown")
        assert "Unknown queue backend" in str(exc_info.value)

    def test_in_process_requires_job_repository(self):
        with pytest.raises(ValueError) as exc_info:
            get_queue_backend("in_process")
        assert "job_repository is required" in str(exc_info.value)


class TestRQAssetQueueBackend:
    def test_init_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            RQAssetQueueBackend()


class TestCeleryAssetQueueBackend:
    def test_init_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            CeleryAssetQueueBackend()
