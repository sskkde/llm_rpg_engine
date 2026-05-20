"""Tests for AudioAssetProvider (P8)."""

import os
import pytest

from llm_rpg.assets.audio_provider import AudioAssetProvider
from llm_rpg.assets.interfaces import (
    AssetGenerationRequest,
    AssetStatus,
    AssetType,
)


@pytest.mark.asyncio
async def test_bgm_placeholder():
    """AudioAssetProvider returns placeholder URL for BGM."""
    provider = AudioAssetProvider()
    request = AssetGenerationRequest(
        asset_type=AssetType.BGM,
        request_id="test-bgm-001",
    )

    result = await provider.generate(request)

    assert result.status == AssetStatus.COMPLETED
    assert result.asset_url == "https://placeholder.audio/bgm/default.mp3"
    assert result.asset_id is not None
    assert result.metadata["placeholder"] is True
    assert result.metadata["asset_type"] == "bgm"


@pytest.mark.asyncio
async def test_sfx_placeholder():
    """AudioAssetProvider returns placeholder URL for SFX."""
    provider = AudioAssetProvider()
    request = AssetGenerationRequest(
        asset_type=AssetType.SFX,
        request_id="test-sfx-001",
    )

    result = await provider.generate(request)

    assert result.status == AssetStatus.COMPLETED
    assert result.asset_url == "https://placeholder.audio/sfx/default.mp3"
    assert result.asset_id is not None
    assert result.metadata["placeholder"] is True
    assert result.metadata["asset_type"] == "sfx"


def test_provider_disabled_by_default():
    """AudioAssetProvider is disabled by default."""
    # Ensure env var is not set
    original = os.environ.pop("ASSET_AUDIO_PROVIDER_ENABLED", None)

    try:
        provider = AudioAssetProvider()
        assert provider.enabled is False
    finally:
        if original is not None:
            os.environ["ASSET_AUDIO_PROVIDER_ENABLED"] = original


def test_provider_enabled_via_env():
    """AudioAssetProvider can be enabled via environment variable."""
    original = os.environ.get("ASSET_AUDIO_PROVIDER_ENABLED")

    try:
        os.environ["ASSET_AUDIO_PROVIDER_ENABLED"] = "true"
        provider = AudioAssetProvider()
        assert provider.enabled is True
    finally:
        if original is not None:
            os.environ["ASSET_AUDIO_PROVIDER_ENABLED"] = original
        else:
            os.environ.pop("ASSET_AUDIO_PROVIDER_ENABLED", None)


@pytest.mark.asyncio
async def test_check_status_completed():
    """check_status returns COMPLETED for generated assets."""
    provider = AudioAssetProvider()
    request = AssetGenerationRequest(
        asset_type=AssetType.BGM,
        request_id="test-status-001",
    )

    await provider.generate(request)
    status = await provider.check_status("test-status-001")

    assert status == AssetStatus.COMPLETED


@pytest.mark.asyncio
async def test_check_status_failed_for_unknown():
    """check_status returns FAILED for unknown request IDs."""
    provider = AudioAssetProvider()
    status = await provider.check_status("unknown-request-id")
    assert status == AssetStatus.FAILED


@pytest.mark.asyncio
async def test_cancel_returns_true_for_pending():
    """cancel returns True for pending requests."""
    provider = AudioAssetProvider()
    request = AssetGenerationRequest(
        asset_type=AssetType.BGM,
        request_id="test-cancel-001",
    )

    # Generate creates a COMPLETED request, so we need to manually set it to PENDING
    result = await provider.generate(request)
    result.status = AssetStatus.PENDING

    cancelled = await provider.cancel("test-cancel-001")
    assert cancelled is True


@pytest.mark.asyncio
async def test_cancel_returns_false_for_unknown():
    """cancel returns False for unknown request IDs."""
    provider = AudioAssetProvider()
    cancelled = await provider.cancel("unknown-request-id")
    assert cancelled is False


def test_supported_asset_types():
    """AudioAssetProvider supports BGM and SFX."""
    provider = AudioAssetProvider()
    assert AssetType.BGM in provider.supported_asset_types
    assert AssetType.SFX in provider.supported_asset_types
    assert AssetType.PORTRAIT not in provider.supported_asset_types
    assert AssetType.SCENE not in provider.supported_asset_types


def test_provider_name():
    """AudioAssetProvider has correct provider name."""
    provider = AudioAssetProvider()
    assert provider.provider_name == "audio_placeholder"
