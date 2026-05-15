"""Tests for AssetJobRepository."""

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
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


class TestAssetJobRepository:
    def test_create_and_get_job(self, db_session):
        repo = AssetJobRepository(db_session)
        job = repo.create_job({
            "id": "job-1",
            "job_id": "pub-job-1",
            "asset_type": "portrait",
            "session_id": "sess-1",
            "status": "pending",
        })
        assert job.id == "job-1"
        assert job.job_id == "pub-job-1"
        assert job.status == "pending"

        fetched = repo.get_by_job_id("pub-job-1")
        assert fetched is not None
        assert fetched.job_id == "pub-job-1"

    def test_list_by_session(self, db_session):
        repo = AssetJobRepository(db_session)
        repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "session_id": "sess-1",
            "asset_type": "portrait",
        })
        repo.create_job({
            "id": "job-2",
            "job_id": "pub-2",
            "session_id": "sess-1",
            "asset_type": "scene",
        })
        repo.create_job({
            "id": "job-3",
            "job_id": "pub-3",
            "session_id": "sess-2",
            "asset_type": "portrait",
        })

        jobs_s1 = repo.list_by_session("sess-1")
        assert len(jobs_s1) == 2

        jobs_s2 = repo.list_by_session("sess-2")
        assert len(jobs_s2) == 1

    def test_list_by_session_with_type_filter(self, db_session):
        repo = AssetJobRepository(db_session)
        repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "session_id": "sess-1",
            "asset_type": "portrait",
        })
        repo.create_job({
            "id": "job-2",
            "job_id": "pub-2",
            "session_id": "sess-1",
            "asset_type": "scene",
        })

        portraits = repo.list_by_session("sess-1", asset_type="portrait")
        assert len(portraits) == 1
        assert portraits[0].asset_type == "portrait"

    def test_claim_next_pending(self, db_session):
        repo = AssetJobRepository(db_session)
        repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
            "priority": 100,
        })
        repo.create_job({
            "id": "job-2",
            "job_id": "pub-2",
            "asset_type": "scene",
            "status": "completed",
            "priority": 50,
        })

        job = repo.claim_next_pending()
        assert job is not None
        assert job.job_id == "pub-1"
        assert job.status == "processing"
        assert job.started_at is not None

    def test_claim_next_pending_respects_priority(self, db_session):
        repo = AssetJobRepository(db_session)
        repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
            "priority": 200,
        })
        repo.create_job({
            "id": "job-2",
            "job_id": "pub-2",
            "asset_type": "scene",
            "status": "pending",
            "priority": 50,
        })

        job = repo.claim_next_pending()
        assert job is not None
        assert job.job_id == "pub-2"

    def test_claim_next_pending_with_provider_filter(self, db_session):
        repo = AssetJobRepository(db_session)
        repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
            "provider_name": "dalle",
        })
        repo.create_job({
            "id": "job-2",
            "job_id": "pub-2",
            "asset_type": "scene",
            "status": "pending",
            "provider_name": "stable-diffusion",
        })

        job = repo.claim_next_pending(provider_name="dalle")
        assert job is not None
        assert job.job_id == "pub-1"
        assert job.provider_name == "dalle"

    def test_claim_next_pending_returns_none_when_none_pending(self, db_session):
        repo = AssetJobRepository(db_session)
        repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "completed",
        })

        job = repo.claim_next_pending()
        assert job is None

    def test_update_status(self, db_session):
        repo = AssetJobRepository(db_session)
        repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
        })

        updated = repo.update_status(
            "pub-1",
            status="processing",
            error_message="test error"
        )
        assert updated is not None
        assert updated.status == "processing"
        assert updated.error_message == "test error"

    def test_mark_processing(self, db_session):
        repo = AssetJobRepository(db_session)
        repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
        })

        job = repo.mark_processing("pub-1")
        assert job is not None
        assert job.status == "processing"
        assert job.started_at is not None

    def test_mark_completed(self, db_session):
        repo = AssetJobRepository(db_session)
        repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "processing",
        })

        job = repo.mark_completed("pub-1", asset_id="asset-123")
        assert job is not None
        assert job.status == "completed"
        assert job.asset_id == "asset-123"
        assert job.completed_at is not None

    def test_mark_failed(self, db_session):
        repo = AssetJobRepository(db_session)
        repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "processing",
        })

        job = repo.mark_failed(
            "pub-1",
            error_message="Provider timeout",
            error_type="TimeoutError"
        )
        assert job is not None
        assert job.status == "failed"
        assert job.error_message == "Provider timeout"
        assert job.last_error_type == "TimeoutError"

    def test_mark_failed_with_retry(self, db_session):
        repo = AssetJobRepository(db_session)
        repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "processing",
        })

        retry_at = datetime.now() + timedelta(minutes=5)
        job = repo.mark_failed(
            "pub-1",
            error_message="Temporary error",
            retry_at=retry_at
        )
        assert job is not None
        assert job.status == "pending"
        assert job.next_retry_at is not None

    def test_schedule_retry(self, db_session):
        repo = AssetJobRepository(db_session)
        repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "failed",
            "attempt_count": 1,
        })

        retry_at = datetime.now() + timedelta(minutes=5)
        job = repo.schedule_retry("pub-1", next_retry_at=retry_at)
        assert job is not None
        assert job.attempt_count == 2
        assert job.status == "pending"
        assert job.next_retry_at is not None

    def test_cancel_job(self, db_session):
        repo = AssetJobRepository(db_session)
        repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending",
        })

        job = repo.cancel_job("pub-1")
        assert job is not None
        assert job.status == "cancelled"
        assert job.cancelled_at is not None

    def test_get_by_job_id_not_found(self, db_session):
        repo = AssetJobRepository(db_session)
        job = repo.get_by_job_id("non-existent")
        assert job is None

    def test_update_status_nonexistent_job(self, db_session):
        repo = AssetJobRepository(db_session)
        job = repo.update_status("non-existent", status="completed")
        assert job is None

    def test_default_values(self, db_session):
        repo = AssetJobRepository(db_session)
        job = repo.create_job({
            "id": "job-1",
            "job_id": "pub-1",
            "asset_type": "portrait",
        })
        assert job.status == "pending"
        assert job.attempt_count == 0
        assert job.max_attempts == 3
        assert job.priority == 100
