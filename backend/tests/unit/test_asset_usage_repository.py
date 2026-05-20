"""Tests for AssetUsageLogRepository."""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import AssetUsageLogModel
from llm_rpg.storage.repositories import AssetUsageLogRepository

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


class TestAssetUsageLogRepository:
    def test_create_and_get_usage_log(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        log = repo.create_usage_log({
            "id": "log-1",
            "usage_id": "usage-1",
            "session_id": "sess-1",
            "provider_name": "dalle",
            "asset_type": "portrait",
            "operation": "generate",
            "estimated_cost_usd": 0.04,
            "actual_cost_usd": 0.04,
        })
        assert log.id == "log-1"
        assert log.usage_id == "usage-1"
        assert log.provider_name == "dalle"

        fetched = repo.get_by_usage_id("usage-1")
        assert fetched is not None
        assert fetched.usage_id == "usage-1"

    def test_get_by_usage_id_not_found(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        log = repo.get_by_usage_id("non-existent")
        assert log is None

    def test_list_by_session(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        repo.create_usage_log({
            "id": "log-1",
            "usage_id": "usage-1",
            "session_id": "sess-1",
            "provider_name": "dalle",
        })
        repo.create_usage_log({
            "id": "log-2",
            "usage_id": "usage-2",
            "session_id": "sess-1",
            "provider_name": "stable-diffusion",
        })
        repo.create_usage_log({
            "id": "log-3",
            "usage_id": "usage-3",
            "session_id": "sess-2",
            "provider_name": "dalle",
        })

        logs_s1 = repo.list_by_session("sess-1")
        assert len(logs_s1) == 2

        logs_s2 = repo.list_by_session("sess-2")
        assert len(logs_s2) == 1

    def test_list_by_session_with_pagination(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        for i in range(10):
            repo.create_usage_log({
                "id": f"log-{i}",
                "usage_id": f"usage-{i}",
                "session_id": "sess-1",
            })

        page1 = repo.list_by_session("sess-1", limit=5, offset=0)
        assert len(page1) == 5

        page2 = repo.list_by_session("sess-1", limit=5, offset=5)
        assert len(page2) == 5

        page3 = repo.list_by_session("sess-1", limit=5, offset=10)
        assert len(page3) == 0

    def test_list_by_user(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        repo.create_usage_log({
            "id": "log-1",
            "usage_id": "usage-1",
            "user_id": "user-1",
        })
        repo.create_usage_log({
            "id": "log-2",
            "usage_id": "usage-2",
            "user_id": "user-2",
        })

        logs_u1 = repo.list_by_user("user-1")
        assert len(logs_u1) == 1

        logs_u2 = repo.list_by_user("user-2")
        assert len(logs_u2) == 1

    def test_list_by_user_with_pagination(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        for i in range(10):
            repo.create_usage_log({
                "id": f"log-{i}",
                "usage_id": f"usage-{i}",
                "user_id": "user-1",
            })

        page1 = repo.list_by_user("user-1", limit=3, offset=0)
        assert len(page1) == 3

        page2 = repo.list_by_user("user-1", limit=3, offset=3)
        assert len(page2) == 3

    def test_list_by_provider(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        repo.create_usage_log({
            "id": "log-1",
            "usage_id": "usage-1",
            "provider_name": "dalle",
        })
        repo.create_usage_log({
            "id": "log-2",
            "usage_id": "usage-2",
            "provider_name": "stable-diffusion",
        })
        repo.create_usage_log({
            "id": "log-3",
            "usage_id": "usage-3",
            "provider_name": "dalle",
        })

        logs_dalle = repo.list_by_provider("dalle")
        assert len(logs_dalle) == 2

        logs_sd = repo.list_by_provider("stable-diffusion")
        assert len(logs_sd) == 1

    def test_list_by_provider_with_pagination(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        for i in range(10):
            repo.create_usage_log({
                "id": f"log-{i}",
                "usage_id": f"usage-{i}",
                "provider_name": "dalle",
            })

        page1 = repo.list_by_provider("dalle", limit=4, offset=0)
        assert len(page1) == 4

        page2 = repo.list_by_provider("dalle", limit=4, offset=4)
        assert len(page2) == 4

    def test_get_cost_summary_by_session(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        repo.create_usage_log({
            "id": "log-1",
            "usage_id": "usage-1",
            "session_id": "sess-1",
            "estimated_cost_usd": 0.04,
            "actual_cost_usd": 0.04,
        })
        repo.create_usage_log({
            "id": "log-2",
            "usage_id": "usage-2",
            "session_id": "sess-1",
            "estimated_cost_usd": 0.08,
            "actual_cost_usd": 0.07,
        })
        repo.create_usage_log({
            "id": "log-3",
            "usage_id": "usage-3",
            "session_id": "sess-2",
            "estimated_cost_usd": 0.10,
            "actual_cost_usd": 0.10,
        })

        summary = repo.get_cost_summary(session_id="sess-1")
        assert summary["total_estimated"] == pytest.approx(0.12)
        assert summary["total_actual"] == pytest.approx(0.11)
        assert summary["count"] == 2

    def test_get_cost_summary_by_user(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        repo.create_usage_log({
            "id": "log-1",
            "usage_id": "usage-1",
            "user_id": "user-1",
            "estimated_cost_usd": 0.05,
            "actual_cost_usd": 0.05,
        })
        repo.create_usage_log({
            "id": "log-2",
            "usage_id": "usage-2",
            "user_id": "user-1",
            "estimated_cost_usd": 0.03,
            "actual_cost_usd": 0.03,
        })

        summary = repo.get_cost_summary(user_id="user-1")
        assert summary["total_estimated"] == 0.08
        assert summary["total_actual"] == 0.08
        assert summary["count"] == 2

    def test_get_cost_summary_by_provider(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        repo.create_usage_log({
            "id": "log-1",
            "usage_id": "usage-1",
            "provider_name": "dalle",
            "estimated_cost_usd": 0.04,
            "actual_cost_usd": 0.04,
        })
        repo.create_usage_log({
            "id": "log-2",
            "usage_id": "usage-2",
            "provider_name": "dalle",
            "estimated_cost_usd": 0.04,
            "actual_cost_usd": 0.04,
        })
        repo.create_usage_log({
            "id": "log-3",
            "usage_id": "usage-3",
            "provider_name": "stable-diffusion",
            "estimated_cost_usd": 0.02,
            "actual_cost_usd": 0.02,
        })

        summary = repo.get_cost_summary(provider_name="dalle")
        assert summary["total_estimated"] == 0.08
        assert summary["total_actual"] == 0.08
        assert summary["count"] == 2

    def test_get_cost_summary_combined_filters(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        repo.create_usage_log({
            "id": "log-1",
            "usage_id": "usage-1",
            "session_id": "sess-1",
            "user_id": "user-1",
            "provider_name": "dalle",
            "estimated_cost_usd": 0.04,
            "actual_cost_usd": 0.04,
        })
        repo.create_usage_log({
            "id": "log-2",
            "usage_id": "usage-2",
            "session_id": "sess-1",
            "user_id": "user-1",
            "provider_name": "stable-diffusion",
            "estimated_cost_usd": 0.02,
            "actual_cost_usd": 0.02,
        })
        repo.create_usage_log({
            "id": "log-3",
            "usage_id": "usage-3",
            "session_id": "sess-1",
            "user_id": "user-2",
            "provider_name": "dalle",
            "estimated_cost_usd": 0.04,
            "actual_cost_usd": 0.04,
        })

        summary = repo.get_cost_summary(
            session_id="sess-1",
            user_id="user-1",
            provider_name="dalle"
        )
        assert summary["total_estimated"] == 0.04
        assert summary["total_actual"] == 0.04
        assert summary["count"] == 1

    def test_get_cost_summary_empty(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        summary = repo.get_cost_summary(session_id="non-existent")
        assert summary["total_estimated"] == 0
        assert summary["total_actual"] == 0
        assert summary["count"] == 0

    def test_get_cost_summary_handles_null_costs(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        repo.create_usage_log({
            "id": "log-1",
            "usage_id": "usage-1",
            "session_id": "sess-1",
        })
        repo.create_usage_log({
            "id": "log-2",
            "usage_id": "usage-2",
            "session_id": "sess-1",
            "estimated_cost_usd": 0.04,
        })
        repo.create_usage_log({
            "id": "log-3",
            "usage_id": "usage-3",
            "session_id": "sess-1",
            "actual_cost_usd": 0.03,
        })

        summary = repo.get_cost_summary(session_id="sess-1")
        assert summary["total_estimated"] == 0.04
        assert summary["total_actual"] == 0.03
        assert summary["count"] == 3

    def test_default_values(self, db_session):
        repo = AssetUsageLogRepository(db_session)
        log = repo.create_usage_log({
            "id": "log-1",
            "usage_id": "usage-1",
        })
        assert log.currency == "USD"
        assert log.metadata_json == {}
        assert log.created_at is not None
