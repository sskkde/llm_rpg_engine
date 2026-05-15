"""Unit tests for AssetJobRunner."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.repositories import AssetJobRepository
from llm_rpg.assets.interfaces import (
    AssetGenerationRequest,
    AssetGenerationResult,
    AssetStatus,
)
from llm_rpg.assets.retry_policy import RetryPolicy
from llm_rpg.assets.jobs import AssetJobRunner
from llm_rpg.models.assets import AssetJobStatus

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


@pytest.fixture
def job_repo(db_session):
    return AssetJobRepository(db_session)


@pytest.fixture
def retry_policy():
    return RetryPolicy()


@pytest.fixture
def runner(job_repo, retry_policy):
    return AssetJobRunner(job_repo, retry_policy)


def _insert_pending_job(job_repo, job_id="pub-1", provider_name="mock", **overrides):
    data = {
        "id": f"internal-{job_id}",
        "job_id": job_id,
        "asset_type": "portrait",
        "session_id": "sess-1",
        "status": "pending",
        "provider_name": provider_name,
        "request_json": {
            "asset_type": "portrait",
            "game_context": {"prompt": "a warrior"},
            "metadata": {},
        },
    }
    data.update(overrides)
    return job_repo.create_job(data)


class TestRunNextJob:
    @pytest.mark.asyncio
    async def test_run_next_job_no_pending(self, runner):
        result = await runner.run_next_job()
        assert result is None

    @pytest.mark.asyncio
    async def test_run_next_job_success(self, runner, job_repo):
        _insert_pending_job(job_repo)

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=AssetGenerationResult(
            request_id="pub-1",
            status=AssetStatus.COMPLETED,
            asset_url="https://example.com/mock/portrait.png",
            asset_id="asset-1",
        ))

        with patch("llm_rpg.assets.jobs.get_asset_provider", return_value=mock_provider):
            result = await runner.run_next_job()

        assert result is not None
        assert result.job_id == "pub-1"
        assert result.status == AssetJobStatus.COMPLETED
        assert result.asset_id == "asset-1"

        updated = job_repo.get_by_job_id("pub-1")
        assert updated.status == "completed"
        assert updated.asset_id == "asset-1"

    @pytest.mark.asyncio
    async def test_run_next_job_failure_retryable(self, runner, job_repo):
        _insert_pending_job(job_repo)

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=AssetGenerationResult(
            request_id="pub-1",
            status=AssetStatus.FAILED,
            error_message="Server error",
            metadata={"error_type": "5xxServerError", "status_code": 500},
        ))

        with patch("llm_rpg.assets.jobs.get_asset_provider", return_value=mock_provider):
            result = await runner.run_next_job()

        assert result is not None
        assert result.status == AssetJobStatus.PENDING

        updated = job_repo.get_by_job_id("pub-1")
        assert updated.status == "pending"
        assert updated.attempt_count == 1
        assert updated.next_retry_at is not None

    @pytest.mark.asyncio
    async def test_run_next_job_failure_non_retryable(self, runner, job_repo):
        _insert_pending_job(job_repo)

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=AssetGenerationResult(
            request_id="pub-1",
            status=AssetStatus.FAILED,
            error_message="Bad request",
            metadata={"error_type": "BadRequestError", "status_code": 400},
        ))

        with patch("llm_rpg.assets.jobs.get_asset_provider", return_value=mock_provider):
            result = await runner.run_next_job()

        assert result is not None
        assert result.status == AssetJobStatus.FAILED

        updated = job_repo.get_by_job_id("pub-1")
        assert updated.status == "failed"
        assert updated.error_message == "Bad request"
        assert updated.last_error_type == "BadRequestError"

    @pytest.mark.asyncio
    async def test_run_next_job_exception_handling(self, runner, job_repo):
        _insert_pending_job(job_repo)

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(side_effect=ConnectionError("Network down"))

        with patch("llm_rpg.assets.jobs.get_asset_provider", return_value=mock_provider):
            result = await runner.run_next_job()

        assert result is not None
        assert result.status == AssetJobStatus.PENDING

        updated = job_repo.get_by_job_id("pub-1")
        assert updated.status == "pending"
        assert updated.attempt_count == 1
        assert updated.next_retry_at is not None

    @pytest.mark.asyncio
    async def test_run_next_job_exception_non_retryable(self, runner, job_repo):
        _insert_pending_job(job_repo, attempt_count=3)

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(side_effect=ConnectionError("Network down"))

        with patch("llm_rpg.assets.jobs.get_asset_provider", return_value=mock_provider):
            result = await runner.run_next_job()

        assert result is not None
        assert result.status == AssetJobStatus.FAILED

        updated = job_repo.get_by_job_id("pub-1")
        assert updated.status == "failed"
        assert "Network down" in updated.error_message

    @pytest.mark.asyncio
    async def test_run_next_job_with_provider_filter(self, runner, job_repo):
        _insert_pending_job(job_repo, job_id="pub-1", provider_name="mock")
        _insert_pending_job(job_repo, job_id="pub-2", provider_name="dalle")

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=AssetGenerationResult(
            request_id="pub-1",
            status=AssetStatus.COMPLETED,
            asset_url="https://example.com/mock/portrait.png",
            asset_id="asset-1",
        ))

        with patch("llm_rpg.assets.jobs.get_asset_provider", return_value=mock_provider):
            result = await runner.run_next_job(provider_name="mock")

        assert result is not None
        assert result.job_id == "pub-1"

    @pytest.mark.asyncio
    async def test_run_next_job_provider_filter_no_match(self, runner, job_repo):
        _insert_pending_job(job_repo, job_id="pub-1", provider_name="dalle")

        result = await runner.run_next_job(provider_name="mock")
        assert result is None


class TestRunPendingBatch:
    @pytest.mark.asyncio
    async def test_run_pending_batch(self, runner, job_repo):
        for i in range(3):
            _insert_pending_job(
                job_repo,
                job_id=f"pub-{i}",
                provider_name="mock",
            )

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=AssetGenerationResult(
            request_id="pub-0",
            status=AssetStatus.COMPLETED,
            asset_url="https://example.com/mock/portrait.png",
            asset_id="asset-0",
        ))

        with patch("llm_rpg.assets.jobs.get_asset_provider", return_value=mock_provider):
            results = await runner.run_pending_batch(batch_size=5)

        assert len(results) == 3
        for r in results:
            assert r.status == AssetJobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_run_pending_batch_limited_by_batch_size(self, runner, job_repo):
        for i in range(5):
            _insert_pending_job(
                job_repo,
                job_id=f"pub-{i}",
                provider_name="mock",
            )

        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=AssetGenerationResult(
            request_id="pub-0",
            status=AssetStatus.COMPLETED,
            asset_url="https://example.com/mock/portrait.png",
            asset_id="asset-0",
        ))

        with patch("llm_rpg.assets.jobs.get_asset_provider", return_value=mock_provider):
            results = await runner.run_pending_batch(batch_size=2)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_run_pending_batch_empty_queue(self, runner):
        results = await runner.run_pending_batch(batch_size=5)
        assert results == []
