"""Tests for P8 ProviderRegistry and ProviderCapability."""

import pytest

from llm_rpg.assets.provider_registry import (
    ProviderCapability,
    ProviderRegistry,
)


class TestProviderCapability:
    def test_provider_capability_defaults(self):
        cap = ProviderCapability(
            provider_name="test",
            supported_asset_types=["portrait"],
        )
        assert cap.provider_name == "test"
        assert cap.supported_asset_types == ["portrait"]
        assert cap.enabled is True
        assert cap.requires_api_key is False
        assert cap.configured is False
        assert cap.supports_async is True
        assert cap.supports_cancel is False
        assert cap.supports_cost_estimate is False


class TestProviderRegistry:
    def test_list_providers_returns_all_registered(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        providers = registry.list_providers()
        provider_names = [p.provider_name for p in providers]
        assert "mock" in provider_names
        assert "openai_image" in provider_names

    def test_openai_image_shows_not_configured_without_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        info = registry.get_provider_info("openai_image")
        assert info is not None
        assert info.configured is False
        assert info.requires_api_key is True

    def test_openai_image_shows_configured_with_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")
        registry = ProviderRegistry()
        info = registry.get_provider_info("openai_image")
        assert info is not None
        assert info.configured is True

    def test_get_available_provider_portrait_returns_mock_when_openai_not_configured(
        self, monkeypatch
    ):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        provider_name = registry.get_available_provider("portrait")
        assert provider_name is not None
        assert provider_name == "mock"

    def test_get_available_provider_portrait_returns_openai_when_configured(
        self, monkeypatch
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")
        registry = ProviderRegistry()
        provider_name = registry.get_available_provider("portrait")
        assert provider_name is not None
        assert provider_name == "mock"

    def test_get_available_provider_scene(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        provider_name = registry.get_available_provider("scene")
        assert provider_name is not None
        assert provider_name in ("mock", "openai_image")

    def test_get_available_provider_bgm_returns_mock(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        provider_name = registry.get_available_provider("bgm")
        assert provider_name == "mock"

    def test_get_available_provider_unknown_type_returns_none(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        provider_name = registry.get_available_provider("unknown_type")
        assert provider_name is None

    def test_get_provider_info_returns_correct_capability(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()

        mock_info = registry.get_provider_info("mock")
        assert mock_info is not None
        assert mock_info.provider_name == "mock"
        assert "portrait" in mock_info.supported_asset_types
        assert "scene" in mock_info.supported_asset_types
        assert "bgm" in mock_info.supported_asset_types
        assert mock_info.requires_api_key is False
        assert mock_info.configured is True

        openai_info = registry.get_provider_info("openai_image")
        assert openai_info is not None
        assert openai_info.provider_name == "openai_image"
        assert "portrait" in openai_info.supported_asset_types
        assert "scene" in openai_info.supported_asset_types
        assert "bgm" not in openai_info.supported_asset_types

    def test_get_provider_info_unknown_returns_none(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        info = registry.get_provider_info("unknown_provider")
        assert info is None

    def test_check_provider_health_openai_image_not_configured(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        health = registry.check_provider_health("openai_image")
        assert health["configured"] is False
        assert health["enabled"] is True
        assert health["last_error"] is None

    def test_check_provider_health_openai_image_configured(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")
        registry = ProviderRegistry()
        health = registry.check_provider_health("openai_image")
        assert health["configured"] is True
        assert health["enabled"] is True
        assert health["last_error"] is None

    def test_check_provider_health_mock(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        health = registry.check_provider_health("mock")
        assert health["configured"] is True
        assert health["enabled"] is True
        assert health["last_error"] is None

    def test_check_provider_health_unknown_provider(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        health = registry.check_provider_health("unknown_provider")
        assert health["configured"] is False
        assert health["enabled"] is False
        assert "Unknown provider" in health["last_error"]
