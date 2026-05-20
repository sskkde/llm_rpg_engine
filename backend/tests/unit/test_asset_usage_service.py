"""Unit tests for AssetUsageService."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from llm_rpg.storage.models import Base, AssetUsageLogModel, AssetGenerationJobModel
from llm_rpg.storage.repositories import AssetUsageLogRepository, AssetJobRepository, AssetRepository
from llm_rpg.services.asset_usage_service import AssetUsageService


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
def usage_repo(db_session):
    return AssetUsageLogRepository(db_session)


@pytest.fixture
def job_repo(db_session):
    return AssetJobRepository(db_session)


@pytest.fixture
def asset_repo(db_session):
    return AssetRepository(db_session)


@pytest.fixture
def service(usage_repo, job_repo, asset_repo):
    return AssetUsageService(
        usage_log_repository=usage_repo,
        asset_job_repository=job_repo,
        asset_repository=asset_repo,
    )


@pytest.fixture
def service_no_repos():
    return AssetUsageService()


def _create_job(job_repo, db_session, job_id="job-1", **overrides):
    now = datetime.now()
    data = {
        "id": "internal-1",
        "job_id": job_id,
        "asset_type": "portrait",
        "session_id": "session-1",
        "status": "pending",
        "provider_name": "mock",
        "request_json": {"prompt": "test"},
        "attempt_count": 0,
        "max_attempts": 3,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    job = job_repo.create_job(data)
    db_session.commit()
    return job


class TestRecordUsage:
    def test_record_usage_creates_log(self, service, usage_repo, db_session):
        result = service.record_usage(
            job_id="job-1",
            provider_name="mock",
            operation="generate",
            estimated_cost=0.05,
            actual_cost=0.04,
            session_id="session-1",
            asset_type="portrait",
            status="completed",
        )
        db_session.commit()

        assert result is not None
        assert "usage_id" in result
        assert "created_at" in result

        log = usage_repo.get_by_usage_id(result["usage_id"])
        assert log is not None
        assert log.job_id == "job-1"
        assert log.provider_name == "mock"
        assert log.operation == "generate"
        assert log.estimated_cost_usd == 0.05
        assert log.actual_cost_usd == 0.04

    def test_record_usage_enriches_from_job(self, service, job_repo, usage_repo, db_session):
        _create_job(job_repo, db_session, job_id="job-2", provider_name="openai_image")
        db_session.commit()

        result = service.record_usage(job_id="job-2", operation="generate", status="completed")
        db_session.commit()

        assert result is not None
        log = usage_repo.get_by_usage_id(result["usage_id"])
        assert log is not None
        assert log.provider_name == "openai_image"
        assert log.session_id == "session-1"
        assert log.asset_type == "portrait"

    def test_record_usage_without_service_returns_none(self, service_no_repos):
        result = service_no_repos.record_usage(
            job_id="job-1",
            provider_name="mock",
            operation="generate",
        )
        assert result is None

    def test_record_usage_on_failure(self, service, usage_repo, db_session):
        result = service.record_usage(
            job_id="job-failed",
            provider_name="mock",
            operation="generate",
            status="failed",
            metadata={"error_message": "Provider error", "error_type": "ProviderError"},
        )
        db_session.commit()

        assert result is not None
        log = usage_repo.get_by_usage_id(result["usage_id"])
        assert log is not None
        assert log.status == "failed"
        assert log.metadata_json.get("error_message") == "Provider error"


class TestGetSessionUsage:
    def test_get_session_usage_returns_logs(self, service, usage_repo, db_session):
        now = datetime.now()
        for i in range(3):
            usage_repo.create_usage_log({
                "id": f"internal-{i}",
                "usage_id": f"usage-{i}",
                "session_id": "session-1",
                "provider_name": "mock",
                "asset_type": "portrait",
                "operation": "generate",
                "estimated_cost_usd": 0.01 * (i + 1),
                "created_at": now,
            })
        db_session.commit()

        logs = service.get_session_usage("session-1", limit=10, offset=0)

        assert len(logs) == 3
        assert all(log["session_id"] == "session-1" for log in logs)

    def test_get_session_usage_empty_when_no_logs(self, service):
        logs = service.get_session_usage("nonexistent-session")
        assert logs == []

    def test_get_session_usage_without_repo_returns_empty(self, service_no_repos):
        logs = service_no_repos.get_session_usage("session-1")
        assert logs == []


class TestGetUserUsage:
    def test_get_user_usage_returns_logs(self, service, usage_repo, db_session):
        now = datetime.now()
        for i in range(2):
            usage_repo.create_usage_log({
                "id": f"internal-user-{i}",
                "usage_id": f"usage-user-{i}",
                "user_id": "user-1",
                "provider_name": "mock",
                "asset_type": "portrait",
                "operation": "generate",
                "created_at": now,
            })
        db_session.commit()

        logs = service.get_user_usage("user-1", limit=10)

        assert len(logs) == 2
        assert all(log["user_id"] == "user-1" for log in logs)


class TestGetProviderUsage:
    def test_get_provider_usage_returns_logs(self, service, usage_repo, db_session):
        now = datetime.now()
        usage_repo.create_usage_log({
            "id": "internal-provider-1",
            "usage_id": "usage-provider-1",
            "provider_name": "openai_image",
            "asset_type": "portrait",
            "operation": "generate",
            "actual_cost_usd": 0.02,
            "created_at": now,
        })
        db_session.commit()

        logs = service.get_provider_usage("openai_image", limit=10)

        assert len(logs) == 1
        assert logs[0]["provider_name"] == "openai_image"


class TestGetCostSummary:
    def test_get_cost_summary_aggregates_costs(self, service, usage_repo, db_session):
        now = datetime.now()
        for i in range(3):
            usage_repo.create_usage_log({
                "id": f"internal-summary-{i}",
                "usage_id": f"usage-summary-{i}",
                "session_id": "session-summary",
                "estimated_cost_usd": 0.01,
                "actual_cost_usd": 0.02,
                "created_at": now,
            })
        db_session.commit()

        summary = service.get_cost_summary(session_id="session-summary")

        assert summary["total_estimated"] == 0.03
        assert summary["total_actual"] == 0.06
        assert summary["count"] == 3

    def test_get_cost_summary_filters_by_provider(self, service, usage_repo, db_session):
        now = datetime.now()
        usage_repo.create_usage_log({
            "id": "internal-p1",
            "usage_id": "usage-p1",
            "provider_name": "mock",
            "estimated_cost_usd": 0.01,
            "actual_cost_usd": 0.01,
            "created_at": now,
        })
        usage_repo.create_usage_log({
            "id": "internal-p2",
            "usage_id": "usage-p2",
            "provider_name": "openai_image",
            "estimated_cost_usd": 0.05,
            "actual_cost_usd": 0.05,
            "created_at": now,
        })
        db_session.commit()

        summary = service.get_cost_summary(provider_name="mock")

        assert summary["count"] == 1
        assert summary["total_actual"] == 0.01

    def test_get_cost_summary_empty_returns_zeros(self, service):
        summary = service.get_cost_summary(session_id="nonexistent")
        assert summary == {"total_estimated": 0.0, "total_actual": 0.0, "count": 0}


class TestListAllUsage:
    def test_list_all_usage_paginates(self, service, usage_repo, db_session):
        now = datetime.now()
        for i in range(5):
            usage_repo.create_usage_log({
                "id": f"internal-list-{i}",
                "usage_id": f"usage-list-{i}",
                "provider_name": "mock",
                "created_at": now,
            })
        db_session.commit()

        result = service.list_all_usage(limit=3, offset=0)

        assert result["total"] == 5
        assert len(result["items"]) == 3

        result2 = service.list_all_usage(limit=3, offset=3)
        assert len(result2["items"]) == 2

    def test_list_all_usage_filters_by_session(self, service, usage_repo, db_session):
        now = datetime.now()
        usage_repo.create_usage_log({
            "id": "internal-filter-1",
            "usage_id": "usage-filter-1",
            "session_id": "session-a",
            "created_at": now,
        })
        usage_repo.create_usage_log({
            "id": "internal-filter-2",
            "usage_id": "usage-filter-2",
            "session_id": "session-b",
            "created_at": now,
        })
        db_session.commit()

        result = service.list_all_usage(session_id="session-a")

        assert result["total"] == 1
        assert result["items"][0]["session_id"] == "session-a"
