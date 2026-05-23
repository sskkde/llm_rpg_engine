"""Unit tests for asset provider resolver with per-type env var fallback."""

import os

import pytest

from llm_rpg.assets.interfaces import AssetType
from llm_rpg.assets.provider_resolver import (
    KNOWN_PROVIDERS,
    _resolve_chain,
    resolve_asset_provider_name,
)


class TestResolveAssetProviderName:
    """Tests for resolve_asset_provider_name function."""

    def test_portrait_with_specific_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PORTRAIT with ASSET_PROVIDER_PORTRAIT set returns that value."""
        monkeypatch.setenv("ASSET_PROVIDER_PORTRAIT", "openai_image")
        assert resolve_asset_provider_name(AssetType.PORTRAIT) == "openai_image"

    def test_scene_with_specific_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SCENE with ASSET_PROVIDER_SCENE set returns that value."""
        monkeypatch.setenv("ASSET_PROVIDER_SCENE", "openai_image")
        assert resolve_asset_provider_name(AssetType.SCENE) == "openai_image"

    def test_bgm_with_specific_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BGM with ASSET_PROVIDER_BGM set returns that value."""
        monkeypatch.setenv("ASSET_PROVIDER_BGM", "audio_placeholder")
        assert resolve_asset_provider_name(AssetType.BGM) == "audio_placeholder"

    def test_sfx_with_specific_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SFX with ASSET_PROVIDER_SFX set returns that value."""
        monkeypatch.setenv("ASSET_PROVIDER_SFX", "audio_placeholder")
        assert resolve_asset_provider_name(AssetType.SFX) == "audio_placeholder"


class TestPortraitFallbackChain:
    """Tests for PORTRAIT fallback chain: PORTRAIT → IMAGE → DEFAULT → mock."""

    def test_fallback_to_image(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PORTRAIT falls back to ASSET_PROVIDER_IMAGE."""
        monkeypatch.setenv("ASSET_PROVIDER_IMAGE", "openai_image")
        assert resolve_asset_provider_name(AssetType.PORTRAIT) == "openai_image"

    def test_fallback_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PORTRAIT falls back to ASSET_PROVIDER_DEFAULT."""
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "mock")
        assert resolve_asset_provider_name(AssetType.PORTRAIT) == "mock"

    def test_fallback_chain_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PORTRAIT env var takes priority over IMAGE and DEFAULT."""
        monkeypatch.setenv("ASSET_PROVIDER_PORTRAIT", "mock")
        monkeypatch.setenv("ASSET_PROVIDER_IMAGE", "openai_image")
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "audio_placeholder")
        assert resolve_asset_provider_name(AssetType.PORTRAIT) == "mock"

    def test_image_takes_priority_over_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """IMAGE env var takes priority over DEFAULT."""
        monkeypatch.setenv("ASSET_PROVIDER_IMAGE", "openai_image")
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "audio_placeholder")
        assert resolve_asset_provider_name(AssetType.PORTRAIT) == "openai_image"


class TestSceneFallbackChain:
    """Tests for SCENE fallback chain: SCENE → IMAGE → DEFAULT → mock."""

    def test_fallback_to_image(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SCENE falls back to ASSET_PROVIDER_IMAGE."""
        monkeypatch.setenv("ASSET_PROVIDER_IMAGE", "openai_image")
        assert resolve_asset_provider_name(AssetType.SCENE) == "openai_image"

    def test_fallback_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SCENE falls back to ASSET_PROVIDER_DEFAULT."""
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "mock")
        assert resolve_asset_provider_name(AssetType.SCENE) == "mock"


class TestBGMFallbackChain:
    """Tests for BGM fallback chain: BGM → AUDIO → DEFAULT → mock."""

    def test_fallback_to_audio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BGM falls back to ASSET_PROVIDER_AUDIO."""
        monkeypatch.setenv("ASSET_PROVIDER_AUDIO", "audio_placeholder")
        assert resolve_asset_provider_name(AssetType.BGM) == "audio_placeholder"

    def test_fallback_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BGM falls back to ASSET_PROVIDER_DEFAULT."""
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "mock")
        assert resolve_asset_provider_name(AssetType.BGM) == "mock"

    def test_fallback_chain_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BGM env var takes priority over AUDIO and DEFAULT."""
        monkeypatch.setenv("ASSET_PROVIDER_BGM", "audio_placeholder")
        monkeypatch.setenv("ASSET_PROVIDER_AUDIO", "mock")
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "mock")
        assert resolve_asset_provider_name(AssetType.BGM) == "audio_placeholder"


class TestSFXFallbackChain:
    """Tests for SFX fallback chain: SFX → AUDIO → DEFAULT → mock."""

    def test_fallback_to_audio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SFX falls back to ASSET_PROVIDER_AUDIO."""
        monkeypatch.setenv("ASSET_PROVIDER_AUDIO", "audio_placeholder")
        assert resolve_asset_provider_name(AssetType.SFX) == "audio_placeholder"

    def test_fallback_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SFX falls back to ASSET_PROVIDER_DEFAULT."""
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "mock")
        assert resolve_asset_provider_name(AssetType.SFX) == "mock"


class TestAllEnvVarsUnset:
    """Tests when all env vars are unset."""

    def test_portrait_returns_mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PORTRAIT returns 'mock' when all env vars unset."""
        for var in [
            "ASSET_PROVIDER_PORTRAIT",
            "ASSET_PROVIDER_IMAGE",
            "ASSET_PROVIDER_DEFAULT",
        ]:
            monkeypatch.delenv(var, raising=False)
        assert resolve_asset_provider_name(AssetType.PORTRAIT) == "mock"

    def test_scene_returns_mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SCENE returns 'mock' when all env vars unset."""
        for var in [
            "ASSET_PROVIDER_SCENE",
            "ASSET_PROVIDER_IMAGE",
            "ASSET_PROVIDER_DEFAULT",
        ]:
            monkeypatch.delenv(var, raising=False)
        assert resolve_asset_provider_name(AssetType.SCENE) == "mock"

    def test_bgm_returns_mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BGM returns 'mock' when all env vars unset."""
        for var in [
            "ASSET_PROVIDER_BGM",
            "ASSET_PROVIDER_AUDIO",
            "ASSET_PROVIDER_DEFAULT",
        ]:
            monkeypatch.delenv(var, raising=False)
        assert resolve_asset_provider_name(AssetType.BGM) == "mock"

    def test_sfx_returns_mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SFX returns 'mock' when all env vars unset."""
        for var in [
            "ASSET_PROVIDER_SFX",
            "ASSET_PROVIDER_AUDIO",
            "ASSET_PROVIDER_DEFAULT",
        ]:
            monkeypatch.delenv(var, raising=False)
        assert resolve_asset_provider_name(AssetType.SFX) == "mock"


class TestUnknownProviderWarning:
    """Tests for unknown provider name warning and fallback."""

    def test_unknown_provider_logs_warning_and_falls_back(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Unknown provider name logs warning and falls back to next in chain."""
        caplog.set_level("WARNING")
        monkeypatch.setenv("ASSET_PROVIDER_PORTRAIT", "unknown_provider")
        monkeypatch.setenv("ASSET_PROVIDER_IMAGE", "mock")

        result = resolve_asset_provider_name(AssetType.PORTRAIT)
        assert result == "mock"
        assert any(
            "Unknown provider 'unknown_provider'" in record.message
            for record in caplog.records
        )

    def test_unknown_provider_falls_back_to_mock(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Unknown provider in all env vars falls back to 'mock'."""
        caplog.set_level("WARNING")
        monkeypatch.setenv("ASSET_PROVIDER_PORTRAIT", "invalid")
        monkeypatch.setenv("ASSET_PROVIDER_IMAGE", "also_invalid")
        monkeypatch.setenv("ASSET_PROVIDER_DEFAULT", "still_invalid")

        result = resolve_asset_provider_name(AssetType.PORTRAIT)
        assert result == "mock"
        assert len(caplog.records) == 3


class TestResolveChain:
    """Tests for _resolve_chain helper function."""

    def test_returns_first_valid_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_resolve_chain returns first set env var with valid provider."""
        monkeypatch.setenv("FIRST_VAR", "mock")
        assert _resolve_chain("FIRST_VAR", "SECOND_VAR") == "mock"

    def test_returns_mock_when_no_env_vars_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_resolve_chain returns 'mock' when no env vars are set."""
        monkeypatch.delenv("VAR1", raising=False)
        monkeypatch.delenv("VAR2", raising=False)
        assert _resolve_chain("VAR1", "VAR2") == "mock"

    def test_skips_empty_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_resolve_chain skips empty string env vars."""
        monkeypatch.setenv("EMPTY_VAR", "")
        monkeypatch.setenv("VALID_VAR", "mock")
        assert _resolve_chain("EMPTY_VAR", "VALID_VAR") == "mock"

    def test_validates_against_known_providers(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """_resolve_chain validates provider name against KNOWN_PROVIDERS."""
        caplog.set_level("WARNING")
        monkeypatch.setenv("INVALID_VAR", "not_a_real_provider")

        result = _resolve_chain("INVALID_VAR")
        assert result == "mock"
        assert any(
            "Unknown provider 'not_a_real_provider'" in record.message
            for record in caplog.records
        )


class TestKnownProviders:
    """Tests for KNOWN_PROVIDERS constant."""

    def test_contains_expected_providers(self) -> None:
        """KNOWN_PROVIDERS contains all expected provider names."""
        assert "mock" in KNOWN_PROVIDERS
        assert "openai_image" in KNOWN_PROVIDERS
        assert "audio_placeholder" in KNOWN_PROVIDERS

    def test_has_three_providers(self) -> None:
        """KNOWN_PROVIDERS has exactly three providers."""
        assert len(KNOWN_PROVIDERS) == 3


class TestNeverReturnsNone:
    """Tests that resolver never returns None or raises."""

    def test_never_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """resolve_asset_provider_name never returns None."""
        for var in list(os.environ.keys()):
            if var.startswith("ASSET_PROVIDER"):
                monkeypatch.delenv(var, raising=False)

        for asset_type in AssetType:
            result = resolve_asset_provider_name(asset_type)
            assert result is not None
            assert isinstance(result, str)
            assert result in KNOWN_PROVIDERS

    def test_never_raises_on_invalid_input(self) -> None:
        """resolve_asset_provider_name handles all AssetType values without raising."""
        for asset_type in AssetType:
            result = resolve_asset_provider_name(asset_type)
            assert isinstance(result, str)
            assert len(result) > 0
