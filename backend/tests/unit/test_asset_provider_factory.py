"""Tests for the asset provider factory."""
import os
import pytest
from llm_rpg.assets.provider_factory import get_asset_provider
from llm_rpg.assets import MockAssetProvider


class TestGetAssetProvider:
    def test_returns_mock_provider_by_default(self):
        provider = get_asset_provider("mock")
        assert isinstance(provider, MockAssetProvider)
    
    def test_returns_mock_provider_with_env_var(self):
        os.environ["ASSET_PROVIDER"] = "mock"
        provider = get_asset_provider()
        assert isinstance(provider, MockAssetProvider)
    
    def test_returns_mock_provider_when_env_not_set(self):
        if "ASSET_PROVIDER" in os.environ:
            del os.environ["ASSET_PROVIDER"]
        provider = get_asset_provider()
        assert isinstance(provider, MockAssetProvider)
    
    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown asset provider"):
            get_asset_provider("nonexistent")
    
    def test_provider_is_singleton_per_call(self):
        p1 = get_asset_provider("mock")
        p2 = get_asset_provider("mock")
        assert p1 is not p2
        assert isinstance(p1, MockAssetProvider)
        assert isinstance(p2, MockAssetProvider)
    
    def test_mock_provider_name(self):
        provider = get_asset_provider("mock")
        assert provider.provider_name == "mock"
