"""
Integration tests for media provider routing.

Tests:
- Per-type env var routing (ASSET_PROVIDER_PORTRAIT, etc.)
- Fallback chain: PORTRAIT → IMAGE → DEFAULT → mock
- All env vars unset → mock for all types
"""

import os
import pytest

from llm_rpg.assets.interfaces import AssetType
from llm_rpg.assets.provider_resolver import (
    KNOWN_PROVIDERS,
    _resolve_chain,
    resolve_asset_provider_name,
)


# =============================================================================
# Tests: Per-Type Env Var Routing
# =============================================================================

class TestPerTypeEnvVarRouting:
    """Test per-type env var routing for asset providers."""

    def test_portrait_with_specific_env_var(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_PORTRAIT", "openai_image")
        assert resolve_asset_provider_name(AssetType.PORTRAIT) == "openai_image"

    def test_scene_with_specific_env_var(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_SCENE", "openai_image")
        assert resolve_asset_provider_name(AssetType.SCENE) == "openai_image"

    def test_bgm_with_specific_env_var(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_BGM", "audio_placeholder")
        assert resolve_asset_provider_name(AssetType.BGM) == "audio_placeholder"

    def test_sfx_with_specific_env_var(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_SFX", "audio_placeholder")
        assert resolve_asset_provider_name(AssetType.SFX) == "audio_placeholder"


# =============================================================================
# Tests: Portrait Fallback Chain
# =============================================================================

class TestPortraitFallbackChain:
    """Test PORTRAIT fallback chain: PORTRAIT → IMAGE → DEFAULT → mock."""

    def test_fallback_to_image(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_IMAGE", "openai_image")
        assert resolve_asset_provider_name(AssetType.PORTRAIT) == "openai_image"

    def test_fallback_to_default(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "mock")
        assert resolve_asset_provider_name(AssetType.PORTRAIT) == "mock"

    def test_fallback_chain_priority(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_PORTRAIT", "mock")
        monkeypatch.setenv("ASSET_PROVIDER_IMAGE", "openai_image")
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "audio_placeholder")
        assert resolve_asset_provider_name(AssetType.PORTRAIT) == "mock"

    def test_image_takes_priority_over_default(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_IMAGE", "openai_image")
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "audio_placeholder")
        assert resolve_asset_provider_name(AssetType.PORTRAIT) == "openai_image"


# =============================================================================
# Tests: Scene Fallback Chain
# =============================================================================

class TestSceneFallbackChain:
    """Test SCENE fallback chain: SCENE → IMAGE → DEFAULT → mock."""

    def test_fallback_to_image(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_IMAGE", "openai_image")
        assert resolve_asset_provider_name(AssetType.SCENE) == "openai_image"

    def test_fallback_to_default(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "mock")
        assert resolve_asset_provider_name(AssetType.SCENE) == "mock"

    def test_fallback_chain_priority(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_SCENE", "mock")
        monkeypatch.setenv("ASSET_PROVIDER_IMAGE", "openai_image")
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "audio_placeholder")
        assert resolve_asset_provider_name(AssetType.SCENE) == "mock"


# =============================================================================
# Tests: BGM Fallback Chain
# =============================================================================

class TestBGMFallbackChain:
    """Test BGM fallback chain: BGM → AUDIO → DEFAULT → mock."""

    def test_fallback_to_audio(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_AUDIO", "audio_placeholder")
        assert resolve_asset_provider_name(AssetType.BGM) == "audio_placeholder"

    def test_fallback_to_default(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "mock")
        assert resolve_asset_provider_name(AssetType.BGM) == "mock"

    def test_fallback_chain_priority(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_BGM", "audio_placeholder")
        monkeypatch.setenv("ASSET_PROVIDER_AUDIO", "mock")
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "mock")
        assert resolve_asset_provider_name(AssetType.BGM) == "audio_placeholder"


# =============================================================================
# Tests: SFX Fallback Chain
# =============================================================================

class TestSFXFallbackChain:
    """Test SFX fallback chain: SFX → AUDIO → DEFAULT → mock."""

    def test_fallback_to_audio(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_AUDIO", "audio_placeholder")
        assert resolve_asset_provider_name(AssetType.SFX) == "audio_placeholder"

    def test_fallback_to_default(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "mock")
        assert resolve_asset_provider_name(AssetType.SFX) == "mock"

    def test_fallback_chain_priority(self, monkeypatch):
        monkeypatch.setenv("ASSET_PROVIDER_SFX", "audio_placeholder")
        monkeypatch.setenv("ASSET_PROVIDER_AUDIO", "mock")
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "mock")
        assert resolve_asset_provider_name(AssetType.SFX) == "audio_placeholder"


# =============================================================================
# Tests: All Env Vars Unset
# =============================================================================

class TestAllEnvVarsUnset:
    """Test when all env vars are unset, returns mock."""

    def test_portrait_returns_mock(self, monkeypatch):
        for var in ["ASSET_PROVIDER_PORTRAIT", "ASSET_PROVIDER_IMAGE", "ASSET_PROVIDER_DEFAULT"]:
            monkeypatch.delenv(var, raising=False)
        assert resolve_asset_provider_name(AssetType.PORTRAIT) == "mock"

    def test_scene_returns_mock(self, monkeypatch):
        for var in ["ASSET_PROVIDER_SCENE", "ASSET_PROVIDER_IMAGE", "ASSET_PROVIDER_DEFAULT"]:
            monkeypatch.delenv(var, raising=False)
        assert resolve_asset_provider_name(AssetType.SCENE) == "mock"

    def test_bgm_returns_mock(self, monkeypatch):
        for var in ["ASSET_PROVIDER_BGM", "ASSET_PROVIDER_AUDIO", "ASSET_PROVIDER_DEFAULT"]:
            monkeypatch.delenv(var, raising=False)
        assert resolve_asset_provider_name(AssetType.BGM) == "mock"

    def test_sfx_returns_mock(self, monkeypatch):
        for var in ["ASSET_PROVIDER_SFX", "ASSET_PROVIDER_AUDIO", "ASSET_PROVIDER_DEFAULT"]:
            monkeypatch.delenv(var, raising=False)
        assert resolve_asset_provider_name(AssetType.SFX) == "mock"


# =============================================================================
# Tests: Unknown Provider Warning
# =============================================================================

class TestUnknownProviderWarning:
    """Test unknown provider name warning and fallback."""

    def test_unknown_provider_falls_back_to_next(self, monkeypatch, caplog):
        caplog.set_level("WARNING")
        monkeypatch.setenv("ASSET_PROVIDER_PORTRAIT", "unknown_provider")
        monkeypatch.setenv("ASSET_PROVIDER_IMAGE", "mock")

        result = resolve_asset_provider_name(AssetType.PORTRAIT)
        assert result == "mock"
        assert any(
            "Unknown provider 'unknown_provider'" in record.message
            for record in caplog.records
        )

    def test_unknown_provider_falls_back_to_mock(self, monkeypatch, caplog):
        caplog.set_level("WARNING")
        monkeypatch.setenv("ASSET_PROVIDER_PORTRAIT", "invalid")
        monkeypatch.setenv("ASSET_PROVIDER_IMAGE", "also_invalid")
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "still_invalid")

        result = resolve_asset_provider_name(AssetType.PORTRAIT)
        assert result == "mock"
        assert len(caplog.records) == 3


# =============================================================================
# Tests: _resolve_chain Helper
# =============================================================================

class TestResolveChainHelper:
    """Test _resolve_chain helper function."""

    def test_returns_first_valid_provider(self, monkeypatch):
        monkeypatch.setenv("FIRST_VAR", "mock")
        assert _resolve_chain("FIRST_VAR", "SECOND_VAR") == "mock"

    def test_returns_mock_when_no_env_vars_set(self, monkeypatch):
        monkeypatch.delenv("VAR1", raising=False)
        monkeypatch.delenv("VAR2", raising=False)
        assert _resolve_chain("VAR1", "VAR2") == "mock"

    def test_skips_empty_env_var(self, monkeypatch):
        monkeypatch.setenv("EMPTY_VAR", "")
        monkeypatch.setenv("VALID_VAR", "mock")
        assert _resolve_chain("EMPTY_VAR", "VALID_VAR") == "mock"

    def test_validates_against_known_providers(self, monkeypatch, caplog):
        caplog.set_level("WARNING")
        monkeypatch.setenv("INVALID_VAR", "not_a_real_provider")

        result = _resolve_chain("INVALID_VAR")
        assert result == "mock"
        assert any(
            "Unknown provider 'not_a_real_provider'" in record.message
            for record in caplog.records
        )


# =============================================================================
# Tests: KNOWN_PROVIDERS
# =============================================================================

class TestKnownProviders:
    """Test KNOWN_PROVIDERS constant."""

    def test_contains_expected_providers(self):
        assert "mock" in KNOWN_PROVIDERS
        assert "openai_image" in KNOWN_PROVIDERS
        assert "audio_placeholder" in KNOWN_PROVIDERS

    def test_has_three_providers(self):
        assert len(KNOWN_PROVIDERS) == 3


# =============================================================================
# Tests: Never Returns None
# =============================================================================

class TestNeverReturnsNone:
    """Test that resolver never returns None or raises."""

    def test_never_returns_none(self, monkeypatch):
        for var in list(os.environ.keys()):
            if var.startswith("ASSET_PROVIDER"):
                monkeypatch.delenv(var, raising=False)

        for asset_type in AssetType:
            result = resolve_asset_provider_name(asset_type)
            assert result is not None
            assert isinstance(result, str)
            assert result in KNOWN_PROVIDERS

    def test_never_raises_on_invalid_input(self):
        for asset_type in AssetType:
            result = resolve_asset_provider_name(asset_type)
            assert isinstance(result, str)
            assert len(result) > 0
