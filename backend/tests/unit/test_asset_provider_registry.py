"""Tests for asset provider registry and factory."""

import pytest

from llm_rpg.assets.provider_factory import get_asset_provider
from llm_rpg.assets.interfaces import (
    AssetGenerationRequest,
    AssetType,
    AssetStatus,
    MockAssetProvider,
)
from llm_rpg.assets.openai_image import OpenAIImageProvider


class TestProviderFactory:
    def test_get_mock_provider(self):
        """get_asset_provider('mock') returns MockAssetProvider instance."""
        provider = get_asset_provider("mock")
        assert isinstance(provider, MockAssetProvider)
        assert provider.provider_name == "mock"
    
    def test_get_openai_image_provider(self):
        """get_asset_provider('openai_image') returns OpenAIImageProvider instance."""
        provider = get_asset_provider("openai_image")
        assert isinstance(provider, OpenAIImageProvider)
        assert provider.provider_name == "openai_image"
    
    def test_get_provider_default(self, monkeypatch):
        """get_asset_provider() without ASSET_PROVIDER env returns mock."""
        monkeypatch.delenv("ASSET_PROVIDER", raising=False)
        provider = get_asset_provider()
        assert isinstance(provider, MockAssetProvider)
    
    def test_unknown_provider(self):
        """Unknown provider name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_asset_provider("unknown_provider")
        assert "Unknown asset provider" in str(exc_info.value)
        assert "unknown_provider" in str(exc_info.value)


class TestOpenAIImageProvider:
    @pytest.mark.asyncio
    async def test_openai_image_no_key(self, monkeypatch):
        """Without OPENAI_API_KEY, generate returns FAILED with descriptive error."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        provider = OpenAIImageProvider()
        
        request = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            request_id="test-123",
        )
        result = await provider.generate(request)
        
        assert result.status == AssetStatus.FAILED
        assert result.error_message is not None
        assert "OPENAI_API_KEY not configured" in result.error_message
        assert result.asset_url is None
    
    @pytest.mark.asyncio
    async def test_openai_image_with_key(self, monkeypatch):
        """With OPENAI_API_KEY set, generate returns COMPLETED with mock URL."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345")
        provider = OpenAIImageProvider()
        
        request = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            request_id="test-456",
        )
        result = await provider.generate(request)
        
        assert result.status == AssetStatus.COMPLETED
        assert result.asset_url is not None
        assert "stub" in result.asset_url
        assert result.asset_id == "openai_test-456"
        assert result.metadata["api_key_configured"] is True
    
    def test_openai_image_supports_portrait(self):
        """OpenAIImageProvider supports PORTRAIT asset type."""
        provider = OpenAIImageProvider()
        assert provider.supports(AssetType.PORTRAIT) is True
    
    def test_openai_image_supports_scene(self):
        """OpenAIImageProvider supports SCENE asset type."""
        provider = OpenAIImageProvider()
        assert provider.supports(AssetType.SCENE) is True
    
    def test_openai_image_not_supports_bgm(self):
        """OpenAIImageProvider does NOT support BGM asset type."""
        provider = OpenAIImageProvider()
        assert provider.supports(AssetType.BGM) is False
    
    def test_get_provider_info_no_key_leakage(self, monkeypatch):
        """get_provider_info() does NOT expose API key value."""
        monkeypatch.setenv("OPENAI_API_KEY", "super-secret-key-do-not-leak")
        provider = OpenAIImageProvider()
        
        info = provider.get_provider_info()
        
        assert info["provider_name"] == "openai_image"
        assert "portrait" in info["supported_types"]
        assert "scene" in info["supported_types"]
        assert info["api_key_configured"] is True
        # CRITICAL: API key must NOT be in the response
        assert "super-secret-key-do-not-leak" not in str(info)
        assert "api_key" not in info  # No raw api_key field
    
    @pytest.mark.asyncio
    async def test_check_status_with_key(self, monkeypatch):
        """check_status returns COMPLETED when API key is set."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        provider = OpenAIImageProvider()
        
        status = await provider.check_status("any-request-id")
        assert status == AssetStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_check_status_without_key(self, monkeypatch):
        """check_status returns FAILED when API key is not set."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        provider = OpenAIImageProvider()
        
        status = await provider.check_status("any-request-id")
        assert status == AssetStatus.FAILED
    
    @pytest.mark.asyncio
    async def test_cancel_always_returns_false(self, monkeypatch):
        """cancel() always returns False (stub implementation)."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        provider = OpenAIImageProvider()
        
        result = await provider.cancel("any-request-id")
        assert result is False
