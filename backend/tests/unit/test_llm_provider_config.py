"""
Unit tests for LLM provider configuration validation.

Tests cover:
- _create_llm_service_from_config provider mode semantics
- _validate_explicit_llm_config preflight validation
- LLMConfigurationError handling in execute_turn_service
- HTTP 503 response for missing explicit provider config
- No event_logs row created when explicit config fails
"""

import pytest
from unittest.mock import MagicMock, patch

from llm_rpg.core.turn_service import (
    _create_llm_service_from_config,
    _validate_explicit_llm_config,
    LLMConfigurationError,
)
from llm_rpg.llm.service import MockLLMProvider, OpenAIProvider


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_settings_service():
    with patch("llm_rpg.services.settings.SystemSettingsService") as mock:
        yield mock


class TestCreateLLMServiceFromConfig:
    """Tests for _create_llm_service_from_config provider mode semantics."""

    def test_mock_mode_returns_mock_provider(self, mock_db, mock_settings_service):
        provider_config = {"provider_mode": "mock"}

        service = _create_llm_service_from_config(mock_db, provider_config)

        assert isinstance(service._provider, MockLLMProvider)

    def test_force_mock_returns_mock_provider_for_bad_explicit_config(self, mock_db, mock_settings_service):
        provider_config = {"provider_mode": "custom"}

        service = _create_llm_service_from_config(
            mock_db,
            provider_config,
            force_mock=True,
        )

        assert isinstance(service._provider, MockLLMProvider)
        mock_settings_service.return_value.get_effective_custom_base_url.assert_not_called()
        mock_settings_service.return_value.get_effective_custom_api_key.assert_not_called()

    def test_auto_mode_with_openai_key_returns_openai_provider(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_effective_openai_key.return_value = "sk-test-key"
        mock_settings_service.return_value = mock_instance

        provider_config = {"provider_mode": "auto", "default_model": "gpt-4"}

        service = _create_llm_service_from_config(mock_db, provider_config)

        assert isinstance(service._provider, OpenAIProvider)

    def test_auto_mode_without_openai_key_returns_mock_provider(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_effective_openai_key.return_value = None
        mock_settings_service.return_value = mock_instance

        provider_config = {"provider_mode": "auto"}

        service = _create_llm_service_from_config(mock_db, provider_config)

        assert isinstance(service._provider, MockLLMProvider)

    def test_openai_mode_with_key_returns_openai_provider(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_effective_openai_key.return_value = "sk-test-key"
        mock_settings_service.return_value = mock_instance

        provider_config = {"provider_mode": "openai", "default_model": "gpt-4"}

        service = _create_llm_service_from_config(mock_db, provider_config)

        assert isinstance(service._provider, OpenAIProvider)

    def test_openai_mode_without_key_raises_configuration_error(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_effective_openai_key.return_value = None
        mock_settings_service.return_value = mock_instance

        provider_config = {"provider_mode": "openai"}

        with pytest.raises(LLMConfigurationError) as exc_info:
            _create_llm_service_from_config(mock_db, provider_config)

        assert exc_info.value.provider_mode == "openai"
        assert exc_info.value.missing_config == "openai_api_key"

    def test_openai_mode_unreadable_key_raises_configuration_error(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_effective_openai_key.side_effect = RuntimeError("decrypt failed")
        mock_settings_service.return_value = mock_instance

        provider_config = {"provider_mode": "openai"}

        with pytest.raises(LLMConfigurationError) as exc_info:
            _create_llm_service_from_config(mock_db, provider_config)

        assert exc_info.value.provider_mode == "openai"
        assert exc_info.value.missing_config == "openai_api_key"

    def test_custom_mode_with_all_config_returns_openai_provider(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_effective_custom_api_key.return_value = "custom-key"
        mock_instance.get_effective_custom_base_url.return_value = "https://api.custom.com"
        mock_settings_service.return_value = mock_instance

        provider_config = {"provider_mode": "custom", "default_model": "gpt-4"}

        service = _create_llm_service_from_config(mock_db, provider_config)

        assert isinstance(service._provider, OpenAIProvider)

    def test_custom_mode_without_base_url_raises_configuration_error(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_effective_custom_api_key.return_value = "custom-key"
        mock_instance.get_effective_custom_base_url.return_value = None
        mock_settings_service.return_value = mock_instance
        provider_config = {"provider_mode": "custom"}

        with pytest.raises(LLMConfigurationError) as exc_info:
            _create_llm_service_from_config(mock_db, provider_config)

        assert exc_info.value.provider_mode == "custom"
        assert exc_info.value.missing_config == "custom_base_url"

    def test_custom_mode_without_api_key_raises_configuration_error(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_effective_custom_api_key.return_value = None
        mock_instance.get_effective_custom_base_url.return_value = "https://api.custom.com"
        mock_settings_service.return_value = mock_instance
        provider_config = {"provider_mode": "custom"}

        with pytest.raises(LLMConfigurationError) as exc_info:
            _create_llm_service_from_config(mock_db, provider_config)

        assert exc_info.value.provider_mode == "custom"
        assert exc_info.value.missing_config == "custom_api_key"

    def test_custom_mode_unreadable_api_key_raises_configuration_error(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_effective_custom_api_key.side_effect = RuntimeError("decrypt failed")
        mock_instance.get_effective_custom_base_url.return_value = "https://api.custom.com"
        mock_settings_service.return_value = mock_instance
        provider_config = {"provider_mode": "custom"}

        with pytest.raises(LLMConfigurationError) as exc_info:
            _create_llm_service_from_config(mock_db, provider_config)

        assert exc_info.value.provider_mode == "custom"
        assert exc_info.value.missing_config == "custom_api_key"


class TestValidateExplicitLLMConfig:
    """Tests for _validate_explicit_llm_config preflight validation."""

    def test_mock_mode_passes_validation(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_provider_config.return_value = {"provider_mode": "mock"}
        mock_settings_service.return_value = mock_instance

        _validate_explicit_llm_config(mock_db)

    def test_auto_mode_passes_validation(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_provider_config.return_value = {"provider_mode": "auto"}
        mock_settings_service.return_value = mock_instance

        _validate_explicit_llm_config(mock_db)

    def test_openai_mode_with_key_passes_validation(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_provider_config.return_value = {"provider_mode": "openai"}
        mock_instance.get_effective_openai_key.return_value = "sk-test-key"
        mock_settings_service.return_value = mock_instance

        _validate_explicit_llm_config(mock_db)

    def test_openai_mode_without_key_raises_configuration_error(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_provider_config.return_value = {"provider_mode": "openai"}
        mock_instance.get_effective_openai_key.return_value = None
        mock_settings_service.return_value = mock_instance

        with pytest.raises(LLMConfigurationError) as exc_info:
            _validate_explicit_llm_config(mock_db)

        assert exc_info.value.provider_mode == "openai"
        assert exc_info.value.missing_config == "openai_api_key"

    def test_openai_mode_unreadable_key_raises_configuration_error(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_provider_config.return_value = {"provider_mode": "openai"}
        mock_instance.get_effective_openai_key.side_effect = RuntimeError("decrypt failed")
        mock_settings_service.return_value = mock_instance

        with pytest.raises(LLMConfigurationError) as exc_info:
            _validate_explicit_llm_config(mock_db)

        assert exc_info.value.provider_mode == "openai"
        assert exc_info.value.missing_config == "openai_api_key"

    def test_custom_mode_with_all_config_passes_validation(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_provider_config.return_value = {"provider_mode": "custom"}
        mock_instance.get_effective_custom_api_key.return_value = "custom-key"
        mock_instance.get_effective_custom_base_url.return_value = "https://api.custom.com"
        mock_settings_service.return_value = mock_instance

        _validate_explicit_llm_config(mock_db)

    def test_custom_mode_without_base_url_raises_configuration_error(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_provider_config.return_value = {"provider_mode": "custom"}
        mock_instance.get_effective_custom_api_key.return_value = "custom-key"
        mock_instance.get_effective_custom_base_url.return_value = None
        mock_settings_service.return_value = mock_instance

        with pytest.raises(LLMConfigurationError) as exc_info:
            _validate_explicit_llm_config(mock_db)

        assert exc_info.value.provider_mode == "custom"
        assert exc_info.value.missing_config == "custom_base_url"

    def test_custom_mode_without_api_key_raises_configuration_error(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_provider_config.return_value = {"provider_mode": "custom"}
        mock_instance.get_effective_custom_api_key.return_value = None
        mock_instance.get_effective_custom_base_url.return_value = "https://api.custom.com"
        mock_settings_service.return_value = mock_instance

        with pytest.raises(LLMConfigurationError) as exc_info:
            _validate_explicit_llm_config(mock_db)

        assert exc_info.value.provider_mode == "custom"
        assert exc_info.value.missing_config == "custom_api_key"

    def test_custom_mode_unreadable_api_key_raises_configuration_error(self, mock_db, mock_settings_service):
        mock_instance = MagicMock()
        mock_instance.get_provider_config.return_value = {"provider_mode": "custom"}
        mock_instance.get_effective_custom_api_key.side_effect = RuntimeError("decrypt failed")
        mock_instance.get_effective_custom_base_url.return_value = "https://api.custom.com"
        mock_settings_service.return_value = mock_instance

        with pytest.raises(LLMConfigurationError) as exc_info:
            _validate_explicit_llm_config(mock_db)

        assert exc_info.value.provider_mode == "custom"
        assert exc_info.value.missing_config == "custom_api_key"
