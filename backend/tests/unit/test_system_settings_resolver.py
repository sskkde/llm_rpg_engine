"""
Unit tests for system settings persistence and encryption.
"""

import pytest
import os
import socket
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

    def test_encrypt_returns_text_token(self, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)

        service = SecretEncryptionService()
        encrypted = service.encrypt("sk-test1234567890abcdef")

        assert isinstance(encrypted, str)
        assert encrypted.startswith("gAAAA")

    def test_decrypts_legacy_hex_text_token(self, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)

        service = SecretEncryptionService()
        encrypted = service.encrypt("sk-test1234567890abcdef")
        legacy_hex_text = "\\x" + encrypted.encode().hex()

        assert service.decrypt(legacy_hex_text) == "sk-test1234567890abcdef"

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

    def test_custom_provider_mode_accepted(self, db_session):
        service = SystemSettingsService(db_session)

        result = service.update_settings({
            "llm": {
                "provider_mode": "custom"
            }
        })

        assert result["llm"]["provider_mode"] == "custom"

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


class TestCustomProviderSettings:
    def test_custom_base_url_set_and_retrieved(self, db_session):
        service = SystemSettingsService(db_session)

        result = service.update_settings({
            "llm": {
                "custom_base_url": "https://api.example.com/v1"
            }
        })

        assert result["llm"]["custom_base_url"] == "https://api.example.com/v1"

    def test_custom_base_url_trimmed(self, db_session):
        service = SystemSettingsService(db_session)

        result = service.update_settings({
            "llm": {
                "custom_base_url": "  https://api.example.com/v1  "
            }
        })

        assert result["llm"]["custom_base_url"] == "https://api.example.com/v1"

    def test_custom_base_url_empty_string_becomes_none(self, db_session):
        service = SystemSettingsService(db_session)

        service.update_settings({
            "llm": {
                "custom_base_url": "https://api.example.com/v1"
            }
        })

        result = service.update_settings({
            "llm": {
                "custom_base_url": "   "
            }
        })

        assert result["llm"]["custom_base_url"] is None

    def test_custom_base_url_invalid_scheme(self, db_session):
        service = SystemSettingsService(db_session)

        with pytest.raises(ValueError, match="must use http:// or https://"):
            service.update_settings({
                "llm": {
                    "custom_base_url": "ftp://api.example.com"
                }
            })

    def test_custom_base_url_with_credentials_rejected(self, db_session):
        service = SystemSettingsService(db_session)

        with pytest.raises(ValueError, match="must not contain username or password"):
            service.update_settings({
                "llm": {
                    "custom_base_url": "https://user:pass@api.example.com/v1"
                }
            })

    def test_custom_base_url_without_hostname_rejected(self, db_session):
        service = SystemSettingsService(db_session)

        with pytest.raises(ValueError, match="must include a hostname"):
            service.update_settings({
                "llm": {
                    "custom_base_url": "https:///v1"
                }
            })

    def test_custom_base_url_requires_https_in_production(self, db_session, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        service = SystemSettingsService(db_session)

        with pytest.raises(ValueError, match="must use https:// in production"):
            service.update_settings({
                "llm": {
                    "custom_base_url": "http://api.example.com/v1"
                }
            })

    def test_custom_base_url_rejects_private_ip_in_production(self, db_session, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        service = SystemSettingsService(db_session)

        with pytest.raises(ValueError, match="private or local addresses"):
            service.update_settings({
                "llm": {
                    "custom_base_url": "https://127.0.0.1/v1"
                }
            })

    def test_custom_base_url_rejects_hostname_resolving_private_in_production(self, db_session, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setattr("llm_rpg.services.settings.socket.getaddrinfo", lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ])
        service = SystemSettingsService(db_session)

        with pytest.raises(ValueError, match="resolve to private or local addresses"):
            service.update_settings({
                "llm": {
                    "custom_base_url": "https://api.example.com/v1"
                }
            })

    def test_custom_api_key_encrypted_and_redacted(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)

        service = SystemSettingsService(db_session)

        result = service.update_settings({
            "llm": {
                "custom_api_key": {
                    "action": "set",
                    "value": "custom-key-12345678"
                }
            }
        })

        assert result["llm"]["custom_api_key"]["configured"] is True
        assert result["llm"]["custom_api_key"]["last4"] == "5678"
        assert "custom-key-12345678" not in str(result)

        settings = service.get_settings()
        assert settings.custom_api_key_encrypted is not None
        assert settings.custom_api_key_encrypted != b"custom-key-12345678"

    def test_custom_api_key_clear(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)

        service = SystemSettingsService(db_session)

        service.update_settings({
            "llm": {
                "custom_api_key": {
                    "action": "set",
                    "value": "custom-key-12345678"
                }
            }
        })

        result = service.update_settings({
            "llm": {
                "custom_api_key": {
                    "action": "clear"
                }
            }
        })

        assert result["llm"]["custom_api_key"]["configured"] is False
        assert result["llm"]["custom_api_key"]["last4"] is None

    def test_get_effective_custom_api_key(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)

        service = SystemSettingsService(db_session)

        service.update_settings({
            "llm": {
                "custom_api_key": {
                    "action": "set",
                    "value": "custom-key-12345678"
                }
            }
        })

        effective_key = service.get_effective_custom_api_key()
        assert effective_key == "custom-key-12345678"

    def test_get_effective_custom_base_url(self, db_session):
        service = SystemSettingsService(db_session)

        service.update_settings({
            "llm": {
                "custom_base_url": "https://api.example.com/v1"
            }
        })

        effective_url = service.get_effective_custom_base_url()
        assert effective_url == "https://api.example.com/v1"

    def test_custom_api_key_does_not_fall_back_to_openai_env(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)
        monkeypatch.setenv("OPENAI_API_KEY", "openai-env-key")

        service = SystemSettingsService(db_session)

        effective_key = service.get_effective_custom_api_key()
        assert effective_key is None

    def test_provider_config_includes_custom_base_url(self, db_session):
        service = SystemSettingsService(db_session)

        service.update_settings({
            "llm": {
                "custom_base_url": "https://api.example.com/v1"
            }
        })

        config = service.get_provider_config()
        assert config["custom_base_url"] == "https://api.example.com/v1"


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

    def test_custom_provider_mode_accepted(self, db_session):
        service = SystemSettingsService(db_session)
        result = service.update_settings({"llm": {"provider_mode": "custom"}})
        assert result["llm"]["provider_mode"] == "custom"

    def test_custom_base_url_set_and_trimmed(self, db_session):
        service = SystemSettingsService(db_session)
        result = service.update_settings({
            "llm": {"custom_base_url": "  https://api.example.com/v1  "}
        })
        assert result["llm"]["custom_base_url"] == "https://api.example.com/v1"

    def test_custom_base_url_empty_string_becomes_none(self, db_session):
        service = SystemSettingsService(db_session)
        service.update_settings({"llm": {"custom_base_url": "https://api.example.com"}})
        result = service.update_settings({"llm": {"custom_base_url": ""}})
        assert result["llm"]["custom_base_url"] is None

    def test_custom_base_url_none_clears(self, db_session):
        service = SystemSettingsService(db_session)
        service.update_settings({"llm": {"custom_base_url": "https://api.example.com"}})
        result = service.update_settings({"llm": {"custom_base_url": None}})
        assert result["llm"]["custom_base_url"] is None

    def test_custom_base_url_rejects_ftp_scheme(self, db_session):
        service = SystemSettingsService(db_session)
        with pytest.raises(ValueError, match="http:// or https://"):
            service.update_settings({"llm": {"custom_base_url": "ftp://example.com"}})

    def test_custom_base_url_rejects_credentials(self, db_session):
        service = SystemSettingsService(db_session)
        with pytest.raises(ValueError, match="username or password"):
            service.update_settings({"llm": {"custom_base_url": "https://user:pass@example.com"}})

    def test_custom_base_url_rejects_missing_hostname(self, db_session):
        service = SystemSettingsService(db_session)
        with pytest.raises(ValueError, match="hostname"):
            service.update_settings({"llm": {"custom_base_url": "https://"}})

    def test_custom_api_key_encrypted_and_redacted(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)
        service = SystemSettingsService(db_session)
        result = service.update_settings({
            "llm": {
                "custom_api_key": {
                    "action": "set",
                    "value": "custom-secret-key-12345"
                }
            }
        })
        assert result["llm"]["custom_api_key"]["configured"] is True
        assert result["llm"]["custom_api_key"]["last4"] == "2345"
        assert "custom-secret-key-12345" not in str(result)

    def test_custom_api_key_clear(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)
        service = SystemSettingsService(db_session)
        service.update_settings({
            "llm": {"custom_api_key": {"action": "set", "value": "key-to-clear"}}
        })
        result = service.update_settings({
            "llm": {"custom_api_key": {"action": "clear"}}
        })
        assert result["llm"]["custom_api_key"]["configured"] is False
        assert result["llm"]["custom_api_key"]["last4"] is None

    def test_get_effective_custom_api_key_returns_decrypted(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)
        service = SystemSettingsService(db_session)
        service.update_settings({
            "llm": {"custom_api_key": {"action": "set", "value": "my-custom-key"}}
        })
        assert service.get_effective_custom_api_key() == "my-custom-key"

    def test_get_effective_custom_api_key_no_fallback_to_openai(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-fallback")
        service = SystemSettingsService(db_session)
        assert service.get_effective_custom_api_key() is None

    def test_get_effective_custom_base_url(self, db_session):
        service = SystemSettingsService(db_session)
        service.update_settings({"llm": {"custom_base_url": "https://api.example.com"}})
        assert service.get_effective_custom_base_url() == "https://api.example.com"

    def test_get_effective_custom_base_url_none_when_unset(self, db_session):
        service = SystemSettingsService(db_session)
        assert service.get_effective_custom_base_url() is None

    def test_provider_config_includes_custom_base_url(self, db_session):
        service = SystemSettingsService(db_session)
        service.update_settings({"llm": {"custom_base_url": "https://api.example.com"}})
        config = service.get_provider_config()
        assert config["custom_base_url"] == "https://api.example.com"

    def test_settings_dict_includes_custom_fields(self, db_session, monkeypatch):
        monkeypatch.setenv("SYSTEM_SETTINGS_SECRET_KEY", TEST_SECRET_KEY)
        service = SystemSettingsService(db_session)
        service.update_settings({
            "llm": {
                "custom_base_url": "https://api.example.com",
                "custom_api_key": {"action": "set", "value": "custom-key-12345"}
            }
        })
        result = service.get_settings_dict()
        assert result["llm"]["custom_base_url"] == "https://api.example.com"
        assert result["llm"]["custom_api_key"]["configured"] is True
        assert result["llm"]["custom_api_key"]["last4"] == "2345"
        assert "custom-key-12345" not in str(result)
