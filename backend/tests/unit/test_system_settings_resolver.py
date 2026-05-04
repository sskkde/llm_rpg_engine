"""
Unit tests for system settings persistence and encryption.
"""

import pytest
import os
import uuid
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import SystemSettingsModel, UserModel
from llm_rpg.storage.repositories import SystemSettingsRepository, UserRepository
from llm_rpg.services.settings import (
    SystemSettingsService,
    SecretEncryptionService,
    MissingEncryptionKeyError,
    EncryptionError,
)


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


@pytest.fixture
def sample_user_data():
    return {
        "username": f"testuser_{uuid.uuid4().hex[:8]}",
        "email": f"test_{uuid.uuid4().hex[:8]}@example.com",
        "password_hash": "hashed_password",
    }


class TestSystemSettingsPersistence:
    def test_get_singleton_creates_default_row(self, db_session):
        repo = SystemSettingsRepository(db_session)
        settings = repo.get_singleton()
        
        assert settings is not None
        assert settings.id is not None
        assert settings.provider_mode == "auto"
        assert settings.default_model == "gpt-4"
        assert settings.temperature == 0.7
        assert settings.max_tokens == 2000
        assert settings.registration_enabled is True
        assert settings.maintenance_mode is False
        assert settings.debug_enabled is True
        assert settings.openai_api_key_encrypted is None
        assert settings.openai_api_key_last4 is None

    def test_get_singleton_returns_existing_row(self, db_session):
        repo = SystemSettingsRepository(db_session)
        settings1 = repo.get_singleton()
        settings2 = repo.get_singleton()
        
        assert settings1.id == settings2.id

    def test_update_singleton_updates_fields(self, db_session):
        repo = SystemSettingsRepository(db_session)
        
        update_data = {
            "provider_mode": "openai",
            "temperature": 0.5,
            "maintenance_mode": True,
        }
        updated = repo.update_singleton(update_data)
        
        assert updated.provider_mode == "openai"
        assert updated.temperature == 0.5
        assert updated.maintenance_mode is True
        assert updated.default_model == "gpt-4"

    def test_update_singleton_preserves_user_id(self, db_session, db_engine, sample_user_data):
        SessionLocal = sessionmaker(bind=db_engine)
        db = SessionLocal()
        try:
            user_repo = UserRepository(db)
            user = user_repo.create(sample_user_data)
            db.commit()
            user_id = user.id
        finally:
            db.close()
        
        repo = SystemSettingsRepository(db_session)
        updated = repo.update_singleton({"provider_mode": "mock"}, user_id)
        
        assert updated.updated_by_user_id == user_id


TEST_SECRET_KEY = "9ZN0QXljgbzFqrLOwoFYkA2BDnIdZ13Ao_izV_AoNFY="


class TestSecretEncryption:
    def test_openai_key_encrypted_and_redacted(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)
        
        service = SystemSettingsService(db_session)
        
        result = service.update_settings({
            "llm": {
                "openai_api_key": {
                    "action": "set",
                    "value": "sk-test1234567890abcdef"
                }
            }
        })
        
        assert result["llm"]["openai_api_key"]["configured"] is True
        assert result["llm"]["openai_api_key"]["last4"] == "cdef"
        assert "sk-test1234567890abcdef" not in str(result)
        
        settings = service.get_settings()
        assert settings.openai_api_key_encrypted is not None
        assert settings.openai_api_key_encrypted != b"sk-test1234567890abcdef"

    def test_missing_encryption_key_rejects_secret_set(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", "")
        
        service = SystemSettingsService(db_session)
        
        with pytest.raises(MissingEncryptionKeyError):
            service.update_settings({
                "llm": {
                    "openai_api_key": {
                        "action": "set",
                        "value": "sk-test1234567890abcdef"
                    }
                }
            })
        
        settings = service.get_settings()
        assert settings.openai_api_key_encrypted is None

    def test_clear_secret(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)
        
        service = SystemSettingsService(db_session)
        
        service.update_settings({
            "llm": {
                "openai_api_key": {
                    "action": "set",
                    "value": "sk-test1234567890abcdef"
                }
            }
        })
        
        result = service.update_settings({
            "llm": {
                "openai_api_key": {
                    "action": "clear"
                }
            }
        })
        
        assert result["llm"]["openai_api_key"]["configured"] is False
        assert result["llm"]["openai_api_key"]["last4"] is None

    def test_keep_secret_action(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)
        
        service = SystemSettingsService(db_session)
        
        service.update_settings({
            "llm": {
                "openai_api_key": {
                    "action": "set",
                    "value": "sk-test1234567890abcdef"
                }
            }
        })
        
        result = service.update_settings({
            "llm": {
                "openai_api_key": {
                    "action": "keep"
                }
            }
        })
        
        assert result["llm"]["openai_api_key"]["configured"] is True
        assert result["llm"]["openai_api_key"]["last4"] == "cdef"


class TestEncryptionService:
    def test_encrypt_decrypt_round_trip(self, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)
        
        service = SecretEncryptionService()
        plaintext = "sk-test1234567890abcdef"
        
        encrypted = service.encrypt(plaintext)
        decrypted = service.decrypt(encrypted)
        
        assert decrypted == plaintext
        assert encrypted != plaintext.encode()

    def test_missing_key_raises_error(self, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", "")
        
        service = SecretEncryptionService()
        
        assert service.is_available is False
        
        with pytest.raises(MissingEncryptionKeyError):
            service.encrypt("test")

    def test_get_last4(self, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)
        
        service = SecretEncryptionService()
        
        assert service.get_last4("sk-test1234567890abcdef") == "cdef"
        assert service.get_last4("abc") == "abc"
        assert service.get_last4("ab") == "ab"


class TestSettingsServiceValidation:
    def test_invalid_provider_mode(self, db_session):
        service = SystemSettingsService(db_session)
        
        with pytest.raises(ValueError, match="Invalid provider_mode"):
            service.update_settings({
                "llm": {
                    "provider_mode": "invalid"
                }
            })

    def test_invalid_temperature_range(self, db_session):
        service = SystemSettingsService(db_session)
        
        with pytest.raises(ValueError, match="temperature must be between"):
            service.update_settings({
                "llm": {
                    "temperature": 3.0
                }
            })

    def test_invalid_max_tokens_range(self, db_session):
        service = SystemSettingsService(db_session)
        
        with pytest.raises(ValueError, match="max_tokens must be between"):
            service.update_settings({
                "llm": {
                    "max_tokens": 10000
                }
            })

    def test_invalid_secret_action(self, db_session):
        service = SystemSettingsService(db_session)
        
        with pytest.raises(ValueError, match="Invalid secret action"):
            service.update_settings({
                "llm": {
                    "openai_api_key": {
                        "action": "invalid"
                    }
                }
            })

    def test_set_secret_without_value(self, db_session):
        service = SystemSettingsService(db_session)
        
        with pytest.raises(ValueError, match="Secret value required"):
            service.update_settings({
                "llm": {
                    "openai_api_key": {
                        "action": "set"
                    }
                }
            })


class TestLLMSettingsResolution:
    def test_provider_mode_mock_applies_next_request(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        
        service = SystemSettingsService(db_session)
        
        service.update_settings({
            "llm": {"provider_mode": "mock"}
        })
        
        config = service.get_provider_config()
        assert config["provider_mode"] == "mock"

    def test_auto_mode_prefers_db_secret_over_env(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)
        monkeypatch.setenv("OPENAI_API_KEY", "env-key-1234")
        
        service = SystemSettingsService(db_session)
        
        service.update_settings({
            "llm": {
                "openai_api_key": {
                    "action": "set",
                    "value": "db-key-5678"
                }
            }
        })
        
        effective_key = service.get_effective_openai_key()
        assert effective_key == "db-key-5678"
        assert effective_key != "env-key-1234"

    def test_auto_mode_falls_back_to_env_key(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "env-key-1234")
        
        service = SystemSettingsService(db_session)
        
        effective_key = service.get_effective_openai_key()
        assert effective_key == "env-key-1234"

    def test_provider_config_returns_all_settings(self, db_session):
        service = SystemSettingsService(db_session)
        
        service.update_settings({
            "llm": {
                "provider_mode": "openai",
                "default_model": "gpt-3.5-turbo",
                "temperature": 0.5,
                "max_tokens": 1000,
            }
        })
        
        config = service.get_provider_config()
        assert config["provider_mode"] == "openai"
        assert config["default_model"] == "gpt-3.5-turbo"
        assert config["temperature"] == 0.5
        assert config["max_tokens"] == 1000
