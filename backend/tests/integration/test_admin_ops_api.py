"""
Integration tests for admin operations API endpoints (health and metrics).
"""

import pytest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import UserModel
from llm_rpg.storage.repositories import UserRepository
from llm_rpg.main import app


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
def admin_user_data():
    return {
        "username": f"admin_{uuid.uuid4().hex[:8]}",
        "email": f"admin_{uuid.uuid4().hex[:8]}@example.com",
        "password": "AdminPass123!",
    }


@pytest.fixture
def regular_user_data():
    return {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "email": f"user_{uuid.uuid4().hex[:8]}@example.com",
        "password": "UserPass123!",
    }


def create_user_in_db(db_engine, user_data, is_admin=False):
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    SessionLocal = sessionmaker(bind=db_engine)
    db = SessionLocal()
    try:
        user_repo = UserRepository(db)
        user = user_repo.create({
            "username": user_data["username"],
            "email": user_data["email"],
            "password_hash": pwd_context.hash(user_data["password"]),
            "is_admin": is_admin,
        })
        db.commit()
        return user.id
    finally:
        db.close()


def get_auth_header(client, user_data):
    response = client.post("/auth/login", json={
        "username": user_data["username"],
        "password": user_data["password"],
    })
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestHealthEndpointAuthorization:
    def test_non_admin_gets_403_on_health(self, client, db_engine, admin_user_data, regular_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        create_user_in_db(db_engine, regular_user_data, is_admin=False)

        user_headers = get_auth_header(client, regular_user_data)

        response = client.get("/admin/health", headers=user_headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "Admin access required"

    def test_unauthenticated_gets_401_on_health(self, client):
        response = client.get("/admin/health")
        assert response.status_code == 401

    def test_admin_can_access_health(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/health", headers=headers)
        assert response.status_code == 200


class TestHealthEndpointResponse:
    def test_health_returns_correct_json_shape(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/health", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert "db" in data
        assert "redis" in data
        assert "provider" in data
        assert "uptime_seconds" in data

        assert "status" in data["db"]
        assert "status" in data["redis"]
        assert "status" in data["provider"]
        assert isinstance(data["uptime_seconds"], int)

    def test_health_db_status_ok(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/health", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["db"]["status"] == "ok"

    def test_health_redis_status(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/health", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["redis"]["status"] in ("ok", "error", "disabled")

    def test_health_provider_status(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/health", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["provider"]["status"] in ("ok", "warning", "error")

    def test_health_uptime_positive(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/health", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["uptime_seconds"] >= 0


class TestMetricsEndpointAuthorization:
    def test_non_admin_gets_403_on_metrics(self, client, db_engine, admin_user_data, regular_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        create_user_in_db(db_engine, regular_user_data, is_admin=False)

        user_headers = get_auth_header(client, regular_user_data)

        response = client.get("/admin/metrics", headers=user_headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "Admin access required"

    def test_unauthenticated_gets_401_on_metrics(self, client):
        response = client.get("/admin/metrics")
        assert response.status_code == 401

    def test_admin_can_access_metrics(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200


class TestMetricsEndpointResponse:
    def test_metrics_returns_correct_json_shape(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert "api_latency" in data
        assert "llm_calls" in data
        assert "validator" in data
        assert "turns" in data
        assert "rate_limit" in data
        assert "sessions" in data

    def test_metrics_api_latency_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        latency = data["api_latency"]
        assert "avg_ms" in latency
        assert "p50_ms" in latency
        assert "p95_ms" in latency
        assert "p99_ms" in latency
        assert "count" in latency

    def test_metrics_llm_calls_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        llm = data["llm_calls"]
        assert "total_count" in llm
        assert "success_count" in llm
        assert "failure_count" in llm
        assert "failure_rate" in llm

    def test_metrics_validator_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        validator = data["validator"]
        assert "rejection_count" in validator
        assert "validation_count" in validator

    def test_metrics_turns_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        turns = data["turns"]
        assert "success_count" in turns
        assert "failure_count" in turns

    def test_metrics_rate_limit_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        rate_limit = data["rate_limit"]
        assert "hit_count" in rate_limit

    def test_metrics_sessions_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        sessions = data["sessions"]
        assert "active_count" in sessions

    def test_metrics_placeholder_values(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/metrics", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert data["api_latency"]["avg_ms"] == 0
        assert data["llm_calls"]["total_count"] == 0
        assert data["validator"]["rejection_count"] == 0
        assert data["turns"]["success_count"] == 0
        assert data["rate_limit"]["hit_count"] == 0
