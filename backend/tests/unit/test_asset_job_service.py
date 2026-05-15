"""Unit tests for AssetJobService."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from llm_rpg.models.assets import (
    AssetGenerationRequest,
    AssetGenerationStatus,
    AssetJobResponse,
    AssetJobStatus,
    AssetResponse,
    AssetType,
)
from llm_rpg.storage.models import Base, AssetModel, AssetGenerationJobModel
from llm_rpg.storage.repositories import AssetJobRepository, AssetRepository
from llm_rpg.services.asset_job_service import AssetJobService


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def job_repo(db_session):
    return AssetJobRepository(db_session)


@pytest.fixture
def asset_repo(db_session):
    return AssetRepository(db_session)


@pytest.fixture
def service(job_repo, asset_repo):
    return AssetJobService(job_repository=job_repo, asset_repository=asset_repo)


def _make_request(**overrides):
    defaults = {
        "asset_type": AssetType.PORTRAIT,
        "prompt": "A brave warrior",
        "session_id": "session-1",
    }
    defaults.update(overrides)
    return AssetGenerationRequest(**defaults)


def _insert_completed_asset(asset_repo, db_session, cache_key, asset_id="asset-1"):
    now = datetime.now()
    asset_repo.create({
        "id": "internal-1",
        "asset_id": asset_id,
        "asset_type": "portrait",
        "status": "completed",
        "session_id": "session-1",
        "provider_name": "mock",
        "cache_key": cache_key,
        "result_url": "https://example.com/portrait.png",
        "created_at": now,
        "updated_at": now,
    })
    db_session.commit()
    return asset_id


def _insert_job(job_repo, db_session, job_id="job-1", status="pending", **overrides):
    now = datetime.now()
    data = {
        "id": f"internal-{job_id}",
        "job_id": job_id,
        "asset_type": "portrait",
        "session_id": "session-1",
        "status": status,
        "provider_name": "mock",
        "cache_key": f"ck-{job_id}",
        "attempt_count": 0,
        "max_attempts": 3,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    job_repo.create_job(data)
    db_session.commit()
    return job_id


# --- submit ---


@pytest.mark.asyncio
async def test_submit_cache_hit(service, asset_repo, db_session):
    request = _make_request(prompt="A brave warrior")

    from llm_rpg.core.assets.cache_key import build_asset_cache_key
    cache_key = build_asset_cache_key(request)
    _insert_completed_asset(asset_repo, db_session, cache_key, asset_id="cached-asset-1")

    result = await service.submit(request)

    assert isinstance(result, AssetResponse)
    assert result.asset_id == "cached-asset-1"
    assert result.cache_hit is True
    assert result.generation_status == AssetGenerationStatus.COMPLETED


@pytest.mark.asyncio
async def test_submit_cache_miss(service, job_repo, db_session):
    request = _make_request(prompt="A unique dark forest scene")

    result = await service.submit(request)

    assert isinstance(result, AssetJobResponse)
    assert result.status == AssetJobStatus.PENDING
    assert result.asset_type == "portrait"
    assert result.provider_name == "mock"
    assert result.attempt_count == 0
    assert result.max_attempts == 3
    assert result.error_message is None


@pytest.mark.asyncio
async def test_submit_integrity_error_with_ready_asset(service, asset_repo, job_repo, db_session):
    request = _make_request(prompt="collision test")

    from llm_rpg.core.assets.cache_key import build_asset_cache_key
    cache_key = build_asset_cache_key(request)

    original_create_job = job_repo.create_job

    def create_with_integrity_error(data):
        _insert_completed_asset(asset_repo, db_session, cache_key, asset_id="concurrent-asset")
        raise IntegrityError("stmt", "params", "orig")

    job_repo.create_job = create_with_integrity_error

    result = await service.submit(request)

    assert isinstance(result, AssetResponse)
    assert result.asset_id == "concurrent-asset"
    assert result.cache_hit is True

    job_repo.create_job = original_create_job


# --- get_job ---


@pytest.mark.asyncio
async def test_get_job(service, job_repo, db_session):
    _insert_job(job_repo, db_session, job_id="job-get-1", status="pending")

    result = service.get_job("job-get-1")

    assert result is not None
    assert result.job_id == "job-get-1"
    assert result.status == AssetJobStatus.PENDING
    assert result.asset_type == "portrait"


def test_get_job_not_found(service):
    result = service.get_job("nonexistent-job")

    assert result is None


# --- list_session_jobs ---


@pytest.mark.asyncio
async def test_list_session_jobs(service, job_repo, db_session):
    _insert_job(job_repo, db_session, job_id="j1", session_id="sess-list", asset_type="portrait")
    _insert_job(job_repo, db_session, job_id="j2", session_id="sess-list", asset_type="scene")
    _insert_job(job_repo, db_session, job_id="j3", session_id="other-session", asset_type="portrait")

    result = service.list_session_jobs("sess-list")

    assert len(result) == 2
    job_ids = {r.job_id for r in result}
    assert job_ids == {"j1", "j2"}


@pytest.mark.asyncio
async def test_list_session_jobs_with_type_filter(service, job_repo, db_session):
    _insert_job(job_repo, db_session, job_id="j4", session_id="sess-filter", asset_type="portrait")
    _insert_job(job_repo, db_session, job_id="j5", session_id="sess-filter", asset_type="scene")

    result = service.list_session_jobs("sess-filter", asset_type="portrait")

    assert len(result) == 1
    assert result[0].job_id == "j4"
    assert result[0].asset_type == "portrait"


# --- cancel_job ---


@pytest.mark.asyncio
async def test_cancel_job(service, job_repo, db_session):
    _insert_job(job_repo, db_session, job_id="job-cancel-1", status="pending")

    result = service.cancel_job("job-cancel-1")

    assert result is not None
    assert result.job_id == "job-cancel-1"
    assert result.status == AssetJobStatus.CANCELLED


@pytest.mark.asyncio
async def test_cancel_job_non_pending(service, job_repo, db_session):
    _insert_job(job_repo, db_session, job_id="job-cancel-2", status="completed")

    result = service.cancel_job("job-cancel-2")

    assert result is None

    job = job_repo.get_by_job_id("job-cancel-2")
    assert job.status == "completed"


@pytest.mark.asyncio
async def test_cancel_job_not_found(service):
    result = service.cancel_job("nonexistent")

    assert result is None


# --- retry_job ---


@pytest.mark.asyncio
async def test_retry_job(service, job_repo, db_session):
    _insert_job(
        job_repo, db_session,
        job_id="job-retry-1",
        status="failed",
        error_message="Provider timeout",
        last_error_type="TimeoutError",
        attempt_count=1,
    )

    result = service.retry_job("job-retry-1")

    assert result is not None
    assert result.job_id == "job-retry-1"
    assert result.status == AssetJobStatus.PENDING
    assert result.attempt_count == 2
    assert result.error_message is None
    assert result.last_error_type is None


@pytest.mark.asyncio
async def test_retry_job_non_failed(service, job_repo, db_session):
    _insert_job(job_repo, db_session, job_id="job-retry-2", status="completed")

    result = service.retry_job("job-retry-2")

    assert result is None

    job = job_repo.get_by_job_id("job-retry-2")
    assert job.status == "completed"


@pytest.mark.asyncio
async def test_retry_job_not_found(service):
    result = service.retry_job("nonexistent")

    assert result is None


@pytest.mark.asyncio
async def test_retry_job_pending_not_retried(service, job_repo, db_session):
    _insert_job(job_repo, db_session, job_id="job-retry-3", status="pending")

    result = service.retry_job("job-retry-3")

    assert result is None

    job = job_repo.get_by_job_id("job-retry-3")
    assert job.status == "pending"
