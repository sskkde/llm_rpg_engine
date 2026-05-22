"""
Integration tests for admin release-readiness API endpoint.
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


class TestReleaseReadinessAuthorization:
    def test_non_admin_gets_403_on_release_readiness(self, client, db_engine, admin_user_data, regular_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        create_user_in_db(db_engine, regular_user_data, is_admin=False)

        user_headers = get_auth_header(client, regular_user_data)

        response = client.get("/admin/release-readiness", headers=user_headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "Admin access required"

    def test_unauthenticated_gets_401_on_release_readiness(self, client):
        response = client.get("/admin/release-readiness")
        assert response.status_code == 401

    def test_admin_can_access_release_readiness(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/release-readiness", headers=headers)
        assert response.status_code == 200


class TestReleaseReadinessResponse:
    def test_release_readiness_returns_correct_json_shape(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/release-readiness", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert "migrations" in data
        assert "content" in data
        assert "env_vars" in data
        assert "test_gate" in data

    def test_migrations_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/release-readiness", headers=headers)
        assert response.status_code == 200

        data = response.json()
        migrations = data["migrations"]
        assert "current" in migrations
        assert "head" in migrations
        assert "up_to_date" in migrations

    def test_content_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/release-readiness", headers=headers)
        assert response.status_code == 200

        data = response.json()
        content = data["content"]
        assert "seeded" in content
        assert isinstance(content["seeded"], bool)

    def test_env_vars_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/release-readiness", headers=headers)
        assert response.status_code == 200

        data = response.json()
        env_vars = data["env_vars"]
        assert isinstance(env_vars, dict)
        assert "DATABASE_URL" in env_vars
        assert "SECRET_KEY" in env_vars
        assert "JWT_SECRET_KEY" in env_vars

    def test_env_vars_values_are_boolean(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/release-readiness", headers=headers)
        assert response.status_code == 200

        data = response.json()
        env_vars = data["env_vars"]
        for key, value in env_vars.items():
            assert isinstance(value, bool), f"env_vars[{key}] should be boolean, got {type(value)}"

    def test_test_gate_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/release-readiness", headers=headers)
        assert response.status_code == 200

        data = response.json()
        test_gate = data["test_gate"]
        assert "status" in test_gate
        assert isinstance(test_gate["status"], str)

    def test_content_not_seeded_initially(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/release-readiness", headers=headers)
        assert response.status_code == 200

        data = response.json()
        content = data["content"]
        assert content["seeded"] is False


class TestReleaseReadinessNoSecrets:
    def test_no_api_keys_exposed(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/release-readiness", headers=headers)
        assert response.status_code == 200

        data = response.json()
        env_vars = data["env_vars"]
        for key, value in env_vars.items():
            assert isinstance(value, bool), f"env_vars[{key}] should be boolean, not {type(value).__name__}"
            assert value in (True, False), f"env_vars[{key}] should be boolean, got {value!r}"

    def test_env_vars_only_boolean_values(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/release-readiness", headers=headers)
        assert response.status_code == 200

        data = response.json()
        env_vars = data["env_vars"]
        for key, value in env_vars.items():
            assert value in (True, False), f"env_vars[{key}] should be boolean, got {value!r}"


class TestReleaseReadinessGateMarker:
    def test_release_readiness_reads_gate_status_marker(self, client, db_engine, admin_user_data, tmp_path, monkeypatch):
        from llm_rpg.api import admin_ops

        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        marker_data = {
            "gate": "test-v1-release",
            "status": "pass",
            "commit": "abc1234",
            "ran_at": "2026-05-22T10:00:00+08:00",
        }
        marker_file = tmp_path / "v1_gate_status.json"
        marker_file.write_text(__import__("json").dumps(marker_data))

        def mock_check_test_gate():
            return {
                "status": "pass",
                "gate": "test-v1-release",
                "commit": "abc1234",
                "ran_at": "2026-05-22T10:00:00+08:00",
                "source": str(marker_file),
            }

        monkeypatch.setattr(admin_ops, "_check_test_gate", mock_check_test_gate)

        headers = get_auth_header(client, admin_user_data)
        response = client.get("/admin/release-readiness", headers=headers)
        assert response.status_code == 200

        data = response.json()
        test_gate = data["test_gate"]
        assert test_gate["status"] == "pass"
        assert test_gate["gate"] == "test-v1-release"
        assert test_gate["commit"] == "abc1234"

    def test_release_readiness_unknown_when_marker_missing(self, client, db_engine, admin_user_data, monkeypatch):
        from llm_rpg.api import admin_ops

        create_user_in_db(db_engine, admin_user_data, is_admin=True)

        def mock_check_test_gate():
            return {
                "status": "unknown",
                "message": "No release gate status marker found. Run make test-v1-release and update .release/v1_gate_status.json.",
            }

        monkeypatch.setattr(admin_ops, "_check_test_gate", mock_check_test_gate)

        headers = get_auth_header(client, admin_user_data)
        response = client.get("/admin/release-readiness", headers=headers)
        assert response.status_code == 200

        data = response.json()
        test_gate = data["test_gate"]
        assert test_gate["status"] == "unknown"
        assert "marker" in test_gate.get("message", "").lower() or "no release" in test_gate.get("message", "").lower()

    def test_release_readiness_requires_admin(self, client, db_engine, admin_user_data, regular_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        create_user_in_db(db_engine, regular_user_data, is_admin=False)

        user_headers = get_auth_header(client, regular_user_data)

        response = client.get("/admin/release-readiness", headers=user_headers)
        assert response.status_code == 403
