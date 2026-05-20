"""Tests for AssetRateLimitEventRepository."""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import AssetRateLimitEventModel
from llm_rpg.storage.repositories import AssetRateLimitEventRepository

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


class TestAssetRateLimitEventRepository:
    def test_create_event(self, db_session):
        repo = AssetRateLimitEventRepository(db_session)
        event = repo.create_event({
            "id": "evt-1",
            "event_id": "pub-evt-1",
            "bucket_key": "user:123:portrait",
            "user_id": "user-123",
            "allowed": True,
            "limit_value": 10,
            "current_value": 3,
        })
        assert event.id == "evt-1"
        assert event.event_id == "pub-evt-1"
        assert event.bucket_key == "user:123:portrait"
        assert event.allowed is True

    def test_get_recent_events(self, db_session):
        repo = AssetRateLimitEventRepository(db_session)
        now = datetime.now()
        bucket_key = "user:123:portrait"
        
        repo.create_event({
            "id": "evt-1",
            "event_id": "pub-evt-1",
            "bucket_key": bucket_key,
            "created_at": now - timedelta(hours=2),
        })
        repo.create_event({
            "id": "evt-2",
            "event_id": "pub-evt-2",
            "bucket_key": bucket_key,
            "created_at": now - timedelta(minutes=30),
        })
        repo.create_event({
            "id": "evt-3",
            "event_id": "pub-evt-3",
            "bucket_key": "other:bucket",
            "created_at": now - timedelta(minutes=10),
        })

        since = now - timedelta(hours=1)
        events = repo.get_recent_events(bucket_key, since)
        assert len(events) == 1
        assert events[0].event_id == "pub-evt-2"

    def test_count_recent(self, db_session):
        repo = AssetRateLimitEventRepository(db_session)
        now = datetime.now()
        bucket_key = "user:123:portrait"
        
        repo.create_event({
            "id": "evt-1",
            "event_id": "pub-evt-1",
            "bucket_key": bucket_key,
            "created_at": now - timedelta(hours=2),
        })
        repo.create_event({
            "id": "evt-2",
            "event_id": "pub-evt-2",
            "bucket_key": bucket_key,
            "created_at": now - timedelta(minutes=30),
        })
        repo.create_event({
            "id": "evt-3",
            "event_id": "pub-evt-3",
            "bucket_key": bucket_key,
            "created_at": now - timedelta(minutes=10),
        })
        repo.create_event({
            "id": "evt-4",
            "event_id": "pub-evt-4",
            "bucket_key": "other:bucket",
            "created_at": now - timedelta(minutes=5),
        })

        since = now - timedelta(hours=1)
        count = repo.count_recent(bucket_key, since)
        assert count == 2

    def test_count_recent_empty(self, db_session):
        repo = AssetRateLimitEventRepository(db_session)
        count = repo.count_recent("nonexistent:bucket", datetime.now())
        assert count == 0

    def test_list_by_user(self, db_session):
        repo = AssetRateLimitEventRepository(db_session)
        repo.create_event({
            "id": "evt-1",
            "event_id": "pub-evt-1",
            "user_id": "user-123",
            "bucket_key": "user:123:portrait",
        })
        repo.create_event({
            "id": "evt-2",
            "event_id": "pub-evt-2",
            "user_id": "user-123",
            "bucket_key": "user:123:scene",
        })
        repo.create_event({
            "id": "evt-3",
            "event_id": "pub-evt-3",
            "user_id": "user-456",
            "bucket_key": "user:456:portrait",
        })

        events = repo.list_by_user("user-123")
        assert len(events) == 2
        assert all(e.user_id == "user-123" for e in events)

    def test_list_by_user_with_pagination(self, db_session):
        repo = AssetRateLimitEventRepository(db_session)
        for i in range(10):
            repo.create_event({
                "id": f"evt-{i}",
                "event_id": f"pub-evt-{i}",
                "user_id": "user-123",
                "bucket_key": f"bucket-{i}",
            })

        page1 = repo.list_by_user("user-123", limit=5, offset=0)
        assert len(page1) == 5

        page2 = repo.list_by_user("user-123", limit=5, offset=5)
        assert len(page2) == 5

    def test_list_by_user_empty(self, db_session):
        repo = AssetRateLimitEventRepository(db_session)
        events = repo.list_by_user("nonexistent-user")
        assert len(events) == 0

    def test_list_by_session(self, db_session):
        repo = AssetRateLimitEventRepository(db_session)
        repo.create_event({
            "id": "evt-1",
            "event_id": "pub-evt-1",
            "session_id": "sess-123",
            "bucket_key": "session:sess-123:portrait",
        })
        repo.create_event({
            "id": "evt-2",
            "event_id": "pub-evt-2",
            "session_id": "sess-123",
            "bucket_key": "session:sess-123:scene",
        })
        repo.create_event({
            "id": "evt-3",
            "event_id": "pub-evt-3",
            "session_id": "sess-456",
            "bucket_key": "session:sess-456:portrait",
        })

        events = repo.list_by_session("sess-123")
        assert len(events) == 2
        assert all(e.session_id == "sess-123" for e in events)

    def test_list_by_session_with_pagination(self, db_session):
        repo = AssetRateLimitEventRepository(db_session)
        for i in range(10):
            repo.create_event({
                "id": f"evt-{i}",
                "event_id": f"pub-evt-{i}",
                "session_id": "sess-123",
                "bucket_key": f"bucket-{i}",
            })

        page1 = repo.list_by_session("sess-123", limit=5, offset=0)
        assert len(page1) == 5

        page2 = repo.list_by_session("sess-123", limit=5, offset=5)
        assert len(page2) == 5

    def test_list_by_session_empty(self, db_session):
        repo = AssetRateLimitEventRepository(db_session)
        events = repo.list_by_session("nonexistent-session")
        assert len(events) == 0

    def test_event_fields(self, db_session):
        repo = AssetRateLimitEventRepository(db_session)
        now = datetime.now()
        reset_at = now + timedelta(hours=1)
        
        event = repo.create_event({
            "id": "evt-1",
            "event_id": "pub-evt-1",
            "user_id": "user-123",
            "session_id": "sess-456",
            "provider_name": "openai_image",
            "bucket_key": "user:123:portrait",
            "limit_type": "requests_per_hour",
            "allowed": False,
            "limit_value": 10,
            "current_value": 10,
            "reset_at": reset_at,
        })
        
        assert event.provider_name == "openai_image"
        assert event.limit_type == "requests_per_hour"
        assert event.allowed is False
        assert event.limit_value == 10
        assert event.current_value == 10
        assert event.reset_at is not None
        assert event.created_at is not None
