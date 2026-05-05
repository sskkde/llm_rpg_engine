"""
Integration tests for admin system settings API.
"""

import pytest
import uuid
import os
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import UserModel
from llm_rpg.storage.repositories import UserRepository
from llm_rpg.main import app


TEST_DATABASE_URL = "sqlite:///:memory:"
TEST_SECRET_KEY = "9ZN0QXljgbzFqrLOwoFYkA2BDnIdZ13Ao_izV_AoNFY="


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


class TestSystemSettingsAPI:
    def test_admin_get_returns_default_settings(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/system-settings", headers=headers)
        assert response.status_code == 200

        data = response.json()
        assert "llm" in data
        assert "ops" in data
        assert data["llm"]["provider_mode"] == "auto"
        assert data["llm"]["default_model"] == "gpt-4"
        assert data["llm"]["temperature"] == 0.7
        assert data["llm"]["max_tokens"] == 2000
        assert data["llm"]["openai_api_key"]["configured"] is False
        assert data["llm"]["openai_api_key"]["last4"] is None
        assert data["ops"]["registration_enabled"] is True
        assert data["ops"]["maintenance_mode"] is False
        assert data["ops"]["debug_enabled"] is True

    def test_non_admin_get_returns_403(self, client, db_engine, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)

        response = client.get("/admin/system-settings", headers=headers)
        assert response.status_code == 403

    def test_non_admin_patch_returns_403(self, client, db_engine, regular_user_data):
        create_user_in_db(db_engine, regular_user_data, is_admin=False)
        headers = get_auth_header(client, regular_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"provider_mode": "mock"}
        })
        assert response.status_code == 403

    def test_update_provider_mode(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"provider_mode": "mock"}
        })
        assert response.status_code == 200
        assert response.json()["llm"]["provider_mode"] == "mock"

    def test_update_ops_settings(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "ops": {
                "maintenance_mode": True,
                "registration_enabled": False,
            }
        })
        assert response.status_code == 200
        assert response.json()["ops"]["maintenance_mode"] is True
        assert response.json()["ops"]["registration_enabled"] is False

    def test_preserves_explicit_false(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        client.patch("/admin/system-settings", headers=headers, json={
            "ops": {"maintenance_mode": True}
        })

        response = client.patch("/admin/system-settings", headers=headers, json={
            "ops": {"registration_enabled": False}
        })
        assert response.status_code == 200
        assert response.json()["ops"]["maintenance_mode"] is True
        assert response.json()["ops"]["registration_enabled"] is False

    def test_invalid_provider_mode_returns_422(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"provider_mode": "invalid"}
        })
        assert response.status_code == 422

    def test_invalid_temperature_returns_422(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"temperature": 3.0}
        })
        assert response.status_code == 422

    def test_invalid_max_tokens_returns_422(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"max_tokens": 10000}
        })
        assert response.status_code == 422

    @patch.dict(os.environ, {"SYSTEM_SETTINGS_SECRET_KEY": TEST_SECRET_KEY})
    def test_secret_set_returns_only_metadata(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {
                "openai_api_key": {
                    "action": "set",
                    "value": "sk-test1234567890abcdef"
                }
            }
        })
        assert response.status_code == 200

        data = response.json()
        assert data["llm"]["openai_api_key"]["configured"] is True
        assert data["llm"]["openai_api_key"]["last4"] == "cdef"
        assert "sk-test1234567890abcdef" not in str(data)

        get_response = client.get("/admin/system-settings", headers=headers)
        assert get_response.status_code == 200
        get_data = get_response.json()
        assert get_data["llm"]["openai_api_key"]["configured"] is True
        assert get_data["llm"]["openai_api_key"]["last4"] == "cdef"
        assert "sk-test1234567890abcdef" not in str(get_data)

    @patch.dict(os.environ, {"SYSTEM_SETTINGS_SECRET_KEY": TEST_SECRET_KEY})
    def test_secret_clear_returns_configured_false(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        client.patch("/admin/system-settings", headers=headers, json={
            "llm": {
                "openai_api_key": {
                    "action": "set",
                    "value": "sk-test1234567890abcdef"
                }
            }
        })

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {
                "openai_api_key": {
                    "action": "clear"
                }
            }
        })
        assert response.status_code == 200

        data = response.json()
        assert data["llm"]["openai_api_key"]["configured"] is False
        assert data["llm"]["openai_api_key"]["last4"] is None

    def test_openai_provider_without_effective_key_returns_422(self, client, db_engine, admin_user_data, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "")

        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"provider_mode": "openai"}
        })
        assert response.status_code == 422

    def test_custom_provider_response_includes_custom_fields(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.get("/admin/system-settings", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "custom_base_url" in data["llm"]
        assert "custom_api_key" in data["llm"]
        assert data["llm"]["custom_base_url"] is None
        assert data["llm"]["custom_api_key"]["configured"] is False

    @patch.dict(os.environ, {"SYSTEM_SETTINGS_SECRET_KEY": TEST_SECRET_KEY})
    def test_custom_api_key_set_returns_only_metadata(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {
                "custom_api_key": {
                    "action": "set",
                    "value": "custom-secret-12345"
                }
            }
        })
        assert response.status_code == 200
        data = response.json()
        assert data["llm"]["custom_api_key"]["configured"] is True
        assert data["llm"]["custom_api_key"]["last4"] == "2345"
        assert "custom-secret-12345" not in str(data)

    def test_custom_mode_missing_url_returns_422(self, client, db_engine, admin_user_data, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", "")
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"provider_mode": "custom"}
        })
        assert response.status_code == 422

    @patch.dict(os.environ, {"SYSTEM_SETTINGS_SECRET_KEY": TEST_SECRET_KEY})
    def test_custom_mode_missing_key_returns_422(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"custom_base_url": "https://api.example.com"}
        })

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"provider_mode": "custom"}
        })
        assert response.status_code == 422

    @patch.dict(os.environ, {"SYSTEM_SETTINGS_SECRET_KEY": TEST_SECRET_KEY})
    def test_custom_mode_success_with_url_and_key_in_one_request(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {
                "provider_mode": "custom",
                "custom_base_url": "https://api.example.com/v1",
                "custom_api_key": {
                    "action": "set",
                    "value": "custom-key-in-request"
                }
            }
        })
        assert response.status_code == 200
        data = response.json()
        assert data["llm"]["provider_mode"] == "custom"
        assert data["llm"]["custom_base_url"] == "https://api.example.com/v1"
        assert data["llm"]["custom_api_key"]["configured"] is True
        assert "custom-key-in-request" not in str(data)

    def test_custom_base_url_rejects_invalid_scheme(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"custom_base_url": "ftp://example.com"}
        })
        assert response.status_code == 422

    def test_custom_base_url_rejects_credentials(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"custom_base_url": "https://user:pass@example.com"}
        })
        assert response.status_code == 422

    def test_custom_base_url_rejects_missing_hostname(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"custom_base_url": "https:///v1"}
        })
        assert response.status_code == 422
        assert "hostname" in response.json()["detail"]

    def test_custom_base_url_rejects_http_in_production(self, client, db_engine, admin_user_data, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"custom_base_url": "http://api.example.com/v1"}
        })
        assert response.status_code == 422
        assert "https" in response.json()["detail"]

    def test_custom_base_url_rejects_private_ip_in_production(self, client, db_engine, admin_user_data, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"custom_base_url": "https://127.0.0.1/v1"}
        })
        assert response.status_code == 422
        assert "private or local" in response.json()["detail"]

    @patch.dict(os.environ, {"SYSTEM_SETTINGS_SECRET_KEY": TEST_SECRET_KEY})
    def test_custom_api_key_clear(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"custom_api_key": {"action": "set", "value": "key-to-clear"}}
        })

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"custom_api_key": {"action": "clear"}}
        })
        assert response.status_code == 200
        assert response.json()["llm"]["custom_api_key"]["configured"] is False

    def test_custom_base_url_set_and_retrieved(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"custom_base_url": "https://api.example.com/v1"}
        })
        assert response.status_code == 200
        assert response.json()["llm"]["custom_base_url"] == "https://api.example.com/v1"

        get_response = client.get("/admin/system-settings", headers=headers)
        assert get_response.json()["llm"]["custom_base_url"] == "https://api.example.com/v1"

    def test_custom_base_url_invalid_scheme_returns_422(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"custom_base_url": "ftp://api.example.com"}
        })
        assert response.status_code == 422

    def test_custom_base_url_with_credentials_returns_422(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {"custom_base_url": "https://user:pass@api.example.com/v1"}
        })
        assert response.status_code == 422

    @patch.dict(os.environ, {"SYSTEM_SETTINGS_SECRET_KEY": TEST_SECRET_KEY})
    def test_custom_api_key_set_and_redacted(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {
                "custom_api_key": {
                    "action": "set",
                    "value": "custom-key-12345678"
                }
            }
        })
        assert response.status_code == 200

        data = response.json()
        assert data["llm"]["custom_api_key"]["configured"] is True
        assert data["llm"]["custom_api_key"]["last4"] == "5678"
        assert "custom-key-12345678" not in str(data)

    def test_custom_provider_without_url_returns_422(self, client, db_engine, admin_user_data, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)

        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {
                "provider_mode": "custom",
                "custom_api_key": {
                    "action": "set",
                    "value": "custom-key-12345678"
                }
            }
        })
        assert response.status_code == 422
        assert "custom_base_url" in response.json()["detail"]

    def test_custom_provider_without_key_returns_422(self, client, db_engine, admin_user_data, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", "")

        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {
                "provider_mode": "custom",
                "custom_base_url": "https://api.example.com/v1"
            }
        })
        assert response.status_code == 422
        assert "custom API key" in response.json()["detail"]

    def test_custom_api_key_set_without_encryption_key_returns_422(self, client, db_engine, admin_user_data, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", "")

        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {
                "custom_api_key": {
                    "action": "set",
                    "value": "custom-key-12345678"
                }
            }
        })
        assert response.status_code == 422
        assert "encryption key" in response.json()["detail"]

    def test_openai_api_key_set_without_encryption_key_returns_422(self, client, db_engine, admin_user_data, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", "")

        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {
                "openai_api_key": {
                    "action": "set",
                    "value": "sk-test1234567890abcdef"
                }
            }
        })
        assert response.status_code == 422
        assert "encryption key" in response.json()["detail"]

    @patch.dict(os.environ, {"SYSTEM_SETTINGS_SECRET_KEY": TEST_SECRET_KEY})
    def test_custom_provider_with_url_and_key_in_same_request(self, client, db_engine, admin_user_data):
        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {
                "provider_mode": "custom",
                "custom_base_url": "https://api.example.com/v1",
                "custom_api_key": {
                    "action": "set",
                    "value": "custom-key-12345678"
                }
            }
        })
        assert response.status_code == 200
        assert response.json()["llm"]["provider_mode"] == "custom"
        assert response.json()["llm"]["custom_base_url"] == "https://api.example.com/v1"
        assert response.json()["llm"]["custom_api_key"]["configured"] is True
        assert response.json()["llm"]["custom_api_key"]["last4"] == "5678"

    @patch.dict(os.environ, {"SYSTEM_SETTINGS_SECRET_KEY": TEST_SECRET_KEY})
    def test_openai_provider_with_key_set_in_same_request(self, client, db_engine, admin_user_data, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "")

        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        response = client.patch("/admin/system-settings", headers=headers, json={
            "llm": {
                "provider_mode": "openai",
                "openai_api_key": {
                    "action": "set",
                    "value": "sk-test1234567890abcdef"
                }
            }
        })
        assert response.status_code == 200
        assert response.json()["llm"]["provider_mode"] == "openai"
        assert response.json()["llm"]["openai_api_key"]["configured"] is True


class TestOpsControls:
    def test_registration_toggle_blocks_register_only(self, client, db_engine, admin_user_data, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", "")

        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        headers = get_auth_header(client, admin_user_data)

        client.patch("/admin/system-settings", headers=headers, json={
            "ops": {"registration_enabled": False}
        })

        register_response = client.post("/auth/register", json={
            "username": f"newuser_{uuid.uuid4().hex[:8]}",
            "password": "NewPass123!",
        })
        assert register_response.status_code == 403

        login_response = client.post("/auth/login", json={
            "username": admin_user_data["username"],
            "password": admin_user_data["password"],
        })
        assert login_response.status_code == 200

    def test_maintenance_blocks_player_routes_but_not_admin_settings(self, client, db_engine, admin_user_data, regular_user_data, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", "")

        create_user_in_db(db_engine, admin_user_data, is_admin=True)
        create_user_in_db(db_engine, regular_user_data, is_admin=False)

        admin_headers = get_auth_header(client, admin_user_data)
        user_headers = get_auth_header(client, regular_user_data)

        client.patch("/admin/system-settings", headers=admin_headers, json={
            "ops": {"maintenance_mode": True}
        })

        admin_response = client.get("/admin/system-settings", headers=admin_headers)
        assert admin_response.status_code == 200

        user_response = client.get("/saves", headers=user_headers)
        assert user_response.status_code == 503
