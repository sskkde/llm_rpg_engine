"""Integration tests for asset job rate limiting.

Tests rate limit enforcement on job creation endpoints with DB event recording.
"""

import os
import pytest
import uuid
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.main import app
from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import UserModel
from llm_rpg.storage.repositories import AssetRateLimitEventRepository


TEST_DATABASE_URL = "sqlite:///:memory:"


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
def client(db_engine):
    def override_get_db():
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def user_data():
    return {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "email": f"user_{uuid.uuid4().hex[:8]}@example.com",
        "password": "TestPass123!",
    }


def create_user_in_db(db_engine, user_data, is_admin=False):
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        user = UserModel(
            id=str(uuid.uuid4()),
            username=user_data["username"],
            email=user_data["email"],
            password_hash=pwd_context.hash(user_data["password"]),
            is_admin=is_admin,
        )
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


def get_auth_header(client, user_data):
    response = client.post("/auth/login", json={
        "username": user_data["username"],
        "password": user_data["password"],
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestAssetJobRateLimit:
    """Test rate limit enforcement on asset job creation endpoints."""

    def test_rate_limit_enforced_at_creation(self, client, db_engine, user_data):
        """Make 11 create_portrait_job POST requests: first 10 succeed, 11th returns 429."""
        user_id = create_user_in_db(db_engine, user_data)
        headers = get_auth_header(client, user_data)
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "10")
            m.setenv("ASSET_RATE_LIMIT_SESSION_PER_MINUTE", "100")
            
            # First 10 requests should succeed
            for i in range(10):
                response = client.post(
                    "/media/jobs/portraits",
                    json={
                        "npc_id": f"npc_{i}",
                        "style": "anime",
                        "expression": "neutral",
                        "session_id": "test-session",
                    },
                    headers=headers,
                )
                assert response.status_code in [200, 201, 202], f"Request {i+1} failed: {response.text}"
            
            # 11th request should be rate limited
            response = client.post(
                "/media/jobs/portraits",
                json={
                    "npc_id": "npc_11",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": "test-session",
                },
                headers=headers,
            )
            assert response.status_code == 429, f"Expected 429, got {response.status_code}"
            
            detail = response.json()["detail"]
            assert detail.get("code") == "asset_rate_limited"
            assert detail.get("limit_type") == "user_per_minute"
            assert detail.get("limit_value") == 10

    def test_retry_after_header(self, client, db_engine, user_data):
        """Assert 429 response includes Retry-After header."""
        user_id = create_user_in_db(db_engine, user_data)
        headers = get_auth_header(client, user_data)
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "1")
            
            # First request succeeds
            response = client.post(
                "/media/jobs/portraits",
                json={
                    "npc_id": "npc_1",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": "test-session",
                },
                headers=headers,
            )
            assert response.status_code in [200, 201, 202]
            
            # Second request is rate limited
            response = client.post(
                "/media/jobs/portraits",
                json={
                    "npc_id": "npc_2",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": "test-session",
                },
                headers=headers,
            )
            assert response.status_code == 429
            assert "retry-after" in response.headers
            retry_after = int(response.headers["retry-after"])
            assert 0 < retry_after <= 60

    def test_rate_limit_events_recorded(self, client, db_engine, user_data, db_session):
        """After rate-limited request, query AssetRateLimitEventRepository, assert denied event exists."""
        user_id = create_user_in_db(db_engine, user_data)
        headers = get_auth_header(client, user_data)
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "2")
            
            # Make requests up to limit
            for i in range(2):
                response = client.post(
                    "/media/jobs/portraits",
                    json={
                        "npc_id": f"npc_{i}",
                        "style": "anime",
                        "expression": "neutral",
                        "session_id": session_id,
                    },
                    headers=headers,
                )
                assert response.status_code in [200, 201, 202]
            
            # Make rate-limited request
            response = client.post(
                "/media/jobs/portraits",
                json={
                    "npc_id": "npc_exceed",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": session_id,
                },
                headers=headers,
            )
            assert response.status_code == 429
        
        # Query DB for rate limit events
        repo = AssetRateLimitEventRepository(db_session)
        events = repo.list_by_user(user_id, limit=20)
        
        # Should have events recorded
        assert len(events) >= 1, "Expected at least one rate limit event"
        
        # Find denied event
        denied_events = [e for e in events if e.allowed is False]
        assert len(denied_events) >= 1, "Expected at least one denied event"
        
        denied_event = denied_events[0]
        assert denied_event.user_id == user_id
        assert denied_event.limit_type == "user_per_minute"
        assert denied_event.limit_value == 2
        assert denied_event.session_id == session_id

    def test_different_users_independent_limits(self, client, db_engine, user_data):
        """Two different users, each can make 10 requests independently."""
        # User 1
        user_id_1 = create_user_in_db(db_engine, user_data)
        headers_1 = get_auth_header(client, user_data)
        
        # User 2
        user_data_2 = {
            "username": f"user2_{uuid.uuid4().hex[:8]}",
            "email": f"user2_{uuid.uuid4().hex[:8]}@example.com",
            "password": "TestPass123!",
        }
        user_id_2 = create_user_in_db(db_engine, user_data_2)
        headers_2 = get_auth_header(client, user_data_2)
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "10")
            
            # User 1 makes 10 requests
            for i in range(10):
                response = client.post(
                    "/media/jobs/portraits",
                    json={
                        "npc_id": f"npc_{i}",
                        "style": "anime",
                        "expression": "neutral",
                        "session_id": "session1",
                    },
                    headers=headers_1,
                )
                assert response.status_code in [200, 201, 202]
            
            # User 1's 11th request is rate limited
            response = client.post(
                "/media/jobs/portraits",
                json={
                    "npc_id": "npc_exceed",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": "session1",
                },
                headers=headers_1,
            )
            assert response.status_code == 429
            
            # User 2 can still make requests (independent limit)
            for i in range(10):
                response = client.post(
                    "/media/jobs/portraits",
                    json={
                        "npc_id": f"npc_other_{i}",
                        "style": "anime",
                        "expression": "neutral",
                        "session_id": "session2",
                    },
                    headers=headers_2,
                )
                assert response.status_code in [200, 201, 202], f"User 2 request {i+1} failed"

    def test_rate_limit_by_session(self, client, db_engine, user_data):
        """Session-level limit enforced separately from user limit."""
        user_id = create_user_in_db(db_engine, user_data)
        headers = get_auth_header(client, user_data)
        session_1 = f"session-1-{uuid.uuid4().hex[:8]}"
        session_2 = f"session-2-{uuid.uuid4().hex[:8]}"
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "100")  # High user limit
            m.setenv("ASSET_RATE_LIMIT_SESSION_PER_MINUTE", "3")  # Low session limit
            
            # Session 1: 3 requests succeed
            for i in range(3):
                response = client.post(
                    "/media/jobs/scenes",
                    json={
                        "location_id": f"loc_{i}",
                        "time_of_day": "day",
                        "session_id": session_1,
                    },
                    headers=headers,
                )
                assert response.status_code in [200, 201, 202]
            
            # Session 1: 4th request is rate limited
            response = client.post(
                "/media/jobs/scenes",
                json={
                    "location_id": "loc_exceed",
                    "time_of_day": "day",
                    "session_id": session_1,
                },
                headers=headers,
            )
            assert response.status_code == 429
            detail = response.json()["detail"]
            assert detail.get("limit_type") == "session_per_minute"
            
            # Session 2: can still make requests (independent session limit)
            for i in range(3):
                response = client.post(
                    "/media/jobs/scenes",
                    json={
                        "location_id": f"loc_other_{i}",
                        "time_of_day": "day",
                        "session_id": session_2,
                    },
                    headers=headers,
                )
                assert response.status_code in [200, 201, 202]

    def test_rate_limit_allows_allowed_events_recorded(self, client, db_engine, user_data, db_session):
        """Both allowed and denied events are recorded in asset_rate_limit_events."""
        user_id = create_user_in_db(db_engine, user_data)
        headers = get_auth_header(client, user_data)
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "2")
            
            # Make allowed request
            response = client.post(
                "/media/jobs/portraits",
                json={
                    "npc_id": "npc_1",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": session_id,
                },
                headers=headers,
            )
            assert response.status_code in [200, 201, 202]
            
            # Make another allowed request
            response = client.post(
                "/media/jobs/portraits",
                json={
                    "npc_id": "npc_2",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": session_id,
                },
                headers=headers,
            )
            assert response.status_code in [200, 201, 202]
            
            # Make denied request
            response = client.post(
                "/media/jobs/portraits",
                json={
                    "npc_id": "npc_3",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": session_id,
                },
                headers=headers,
            )
            assert response.status_code == 429
        
        # Query DB for rate limit events
        repo = AssetRateLimitEventRepository(db_session)
        events = repo.list_by_user(user_id, limit=20)
        
        # Should have both allowed and denied events
        allowed_events = [e for e in events if e.allowed is True]
        denied_events = [e for e in events if e.allowed is False]
        
        assert len(allowed_events) >= 1, "Expected at least one allowed event"
        assert len(denied_events) >= 1, "Expected at least one denied event"
