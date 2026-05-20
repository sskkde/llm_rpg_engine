"""Integration tests for asset rate limiting API.

Tests rate limit enforcement on media endpoints and 429 responses.
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


class TestAssetRateLimitEnforcement:
    """Test rate limit enforcement on asset generation endpoints."""

    def test_rate_limit_11_portrait_requests_10_succeed_11th_429(self, client, db_engine, user_data):
        """11 portrait requests in 1 minute: 10 succeed, 11th returns 429."""
        user_id = create_user_in_db(db_engine, user_data)
        headers = get_auth_header(client, user_data)
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "10")
            m.setenv("ASSET_RATE_LIMIT_SESSION_PER_MINUTE", "100")
            
            for i in range(10):
                response = client.post(
                    "/media/portraits/generate",
                    json={
                        "npc_id": f"npc_{i}",
                        "style": "anime",
                        "expression": "neutral",
                        "session_id": "test-session",
                    },
                    headers=headers,
                )
                assert response.status_code in [200, 201], f"Request {i+1} failed: {response.text}"
            
            response = client.post(
                "/media/portraits/generate",
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
            assert "reset_at" in detail

    def test_rate_limit_returns_retry_after_header(self, client, db_engine, user_data):
        """Rate limit response includes Retry-After header."""
        user_id = create_user_in_db(db_engine, user_data)
        headers = get_auth_header(client, user_data)
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "1")
            
            response = client.post(
                "/media/portraits/generate",
                json={
                    "npc_id": "npc_1",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": "test-session",
                },
                headers=headers,
            )
            assert response.status_code in [200, 201]
            
            response = client.post(
                "/media/portraits/generate",
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

    def test_rate_limit_session_limit_enforced(self, client, db_engine, user_data):
        """Session-per-minute limit is enforced."""
        unique_user = {
            "username": f"session_user_{uuid.uuid4().hex[:8]}",
            "email": f"session_user_{uuid.uuid4().hex[:8]}@example.com",
            "password": "TestPass123!",
        }
        user_id = create_user_in_db(db_engine, unique_user)
        headers = get_auth_header(client, unique_user)
        unique_session = f"session-limited-{uuid.uuid4().hex[:8]}"
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "100")
            m.setenv("ASSET_RATE_LIMIT_SESSION_PER_MINUTE", "2")
            
            for i in range(2):
                response = client.post(
                    "/media/scenes/generate",
                    json={
                        "location_id": f"loc_{i}",
                        "time_of_day": "day",
                        "session_id": unique_session,
                    },
                    headers=headers,
                )
                assert response.status_code in [200, 201], f"Request {i+1} failed: {response.text}"
            
            response = client.post(
                "/media/scenes/generate",
                json={
                    "location_id": "loc_3",
                    "time_of_day": "day",
                    "session_id": unique_session,
                },
                headers=headers,
            )
            assert response.status_code == 429
            detail = response.json()["detail"]
            assert detail.get("limit_type") == "session_per_minute"

    def test_rate_limit_different_users_independent(self, client, db_engine, user_data):
        """Different users have independent rate limits."""
        user_id_1 = create_user_in_db(db_engine, user_data)
        headers_1 = get_auth_header(client, user_data)
        
        user_data_2 = {
            "username": f"user2_{uuid.uuid4().hex[:8]}",
            "email": f"user2_{uuid.uuid4().hex[:8]}@example.com",
            "password": "TestPass123!",
        }
        user_id_2 = create_user_in_db(db_engine, user_data_2)
        headers_2 = get_auth_header(client, user_data_2)
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "2")
            
            for i in range(2):
                response = client.post(
                    "/media/portraits/generate",
                    json={
                        "npc_id": f"npc_{i}",
                        "style": "anime",
                        "expression": "neutral",
                        "session_id": "session1",
                    },
                    headers=headers_1,
                )
                assert response.status_code in [200, 201]
            
            response = client.post(
                "/media/portraits/generate",
                json={
                    "npc_id": "npc_exceed",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": "session1",
                },
                headers=headers_1,
            )
            assert response.status_code == 429
            
            response = client.post(
                "/media/portraits/generate",
                json={
                    "npc_id": "npc_other",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": "session2",
                },
                headers=headers_2,
            )
            assert response.status_code in [200, 201]

    def test_rate_limit_job_endpoints_enforced(self, client, db_engine, user_data):
        """Rate limiting is enforced on job creation endpoints."""
        user_id = create_user_in_db(db_engine, user_data)
        headers = get_auth_header(client, user_data)
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "2")
            
            for i in range(2):
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
                assert response.status_code in [200, 201]
            
            response = client.post(
                "/media/jobs/portraits",
                json={
                    "npc_id": "npc_3",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": "test-session",
                },
                headers=headers,
            )
            assert response.status_code == 429

    def test_rate_limit_bgm_endpoint_enforced(self, client, db_engine, user_data):
        """Rate limiting is enforced on BGM generation endpoint."""
        user_id = create_user_in_db(db_engine, user_data)
        headers = get_auth_header(client, user_data)
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "1")
            
            response = client.post(
                "/media/bgm/generate",
                json={
                    "mood": "peaceful",
                    "session_id": "test-session",
                },
                headers=headers,
            )
            assert response.status_code in [200, 201]
            
            response = client.post(
                "/media/bgm/generate",
                json={
                    "mood": "tense",
                    "session_id": "test-session",
                },
                headers=headers,
            )
            assert response.status_code == 429

    def test_rate_limit_scene_job_endpoint_enforced(self, client, db_engine, user_data):
        """Rate limiting is enforced on scene job endpoint."""
        user_id = create_user_in_db(db_engine, user_data)
        headers = get_auth_header(client, user_data)
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "1")
            
            response = client.post(
                "/media/jobs/scenes",
                json={
                    "location_id": "loc_1",
                    "time_of_day": "day",
                    "session_id": "test-session",
                },
                headers=headers,
            )
            assert response.status_code in [200, 201]
            
            response = client.post(
                "/media/jobs/scenes",
                json={
                    "location_id": "loc_2",
                    "time_of_day": "night",
                    "session_id": "test-session",
                },
                headers=headers,
            )
            assert response.status_code == 429

    def test_rate_limit_bgm_job_endpoint_enforced(self, client, db_engine, user_data):
        """Rate limiting is enforced on BGM job endpoint."""
        user_id = create_user_in_db(db_engine, user_data)
        headers = get_auth_header(client, user_data)
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "1")
            
            response = client.post(
                "/media/jobs/bgm",
                json={
                    "mood": "peaceful",
                    "session_id": "test-session",
                },
                headers=headers,
            )
            assert response.status_code in [200, 201]
            
            response = client.post(
                "/media/jobs/bgm",
                json={
                    "mood": "tense",
                    "session_id": "test-session",
                },
                headers=headers,
            )
            assert response.status_code == 429

    def test_rate_limit_429_error_structure(self, client, db_engine, user_data):
        """429 error has structured error details."""
        user_id = create_user_in_db(db_engine, user_data)
        headers = get_auth_header(client, user_data)
        unique_session = f"session-struct-{uuid.uuid4().hex[:8]}"
        
        with pytest.MonkeyPatch.context() as m:
            m.setenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "1")
            
            response = client.post(
                "/media/portraits/generate",
                json={
                    "npc_id": "npc_1",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": unique_session,
                },
                headers=headers,
            )
            assert response.status_code in [200, 201]
            
            response = client.post(
                "/media/portraits/generate",
                json={
                    "npc_id": "npc_2",
                    "style": "anime",
                    "expression": "neutral",
                    "session_id": unique_session,
                },
                headers=headers,
            )
            assert response.status_code == 429
            
            detail = response.json()["detail"]
            assert detail.get("code") == "asset_rate_limited"
            assert "limit_type" in detail
            assert "limit_value" in detail
            assert "reset_at" in detail
            
            from datetime import datetime
            reset_at = datetime.fromisoformat(detail["reset_at"].replace("Z", "+00:00"))
            assert reset_at > datetime.now(reset_at.tzinfo)
