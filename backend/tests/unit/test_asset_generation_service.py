"""Unit tests for AssetGenerationService."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.exc import IntegrityError

from llm_rpg.models.assets import (
    AssetGenerationRequest,
    AssetGenerationStatus,
    AssetResponse,
    AssetType,
)
from llm_rpg.assets.interfaces import (
    AssetGenerationResult,
    AssetStatus,
)
from llm_rpg.services.asset_generation_service import AssetGenerationService


def _make_cached_asset(
    asset_id="cached-1",
    asset_type="portrait",
    status="completed",
    result_url="https://example.com/portrait.png",
    error_message=None,
    provider_name="mock",
    cache_key="ck-abc",
    created_at=None,
    metadata_json=None,
):
    asset = MagicMock()
    asset.asset_id = asset_id
    asset.asset_type = asset_type
    asset.status = status
    asset.result_url = result_url
    asset.error_message = error_message
    asset.provider_name = provider_name
    asset.cache_key = cache_key
    asset.created_at = created_at or datetime.now()
    asset.metadata_json = metadata_json or {}
    return asset


@pytest.fixture
def mock_repo():
    return MagicMock()


@pytest.fixture
def service(mock_repo):
    return AssetGenerationService(repository=mock_repo)


# --- generate_asset ---


@pytest.mark.asyncio
async def test_generate_portrait_creates_asset(service, mock_repo):
    mock_repo.get_ready_by_cache_key.return_value = None
    mock_repo.create.return_value = MagicMock()

    request = AssetGenerationRequest(
        asset_type=AssetType.PORTRAIT,
        prompt="A brave warrior",
    )

    mock_result = AssetGenerationResult(
        request_id="any",
        status=AssetStatus.COMPLETED,
        asset_url="https://example.com/mock/portrait.png",
    )

    with patch(
        "llm_rpg.services.asset_generation_service.get_asset_provider"
    ) as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.generate = AsyncMock(return_value=mock_result)
        mock_get_provider.return_value = mock_provider

        response = await service.generate_asset(request)

    assert response.asset_type == AssetType.PORTRAIT
    assert response.generation_status == AssetGenerationStatus.COMPLETED
    assert response.result_url == "https://example.com/mock/portrait.png"
    assert response.cache_hit is False
    assert response.error_message is None
    mock_repo.create.assert_called_once()
    mock_repo.update_status.assert_called_once_with(
        asset_id=response.asset_id,
        status="completed",
        result_url="https://example.com/mock/portrait.png",
    )


@pytest.mark.asyncio
async def test_generate_returns_cached_on_second_request(service, mock_repo):
    cached = _make_cached_asset(
        asset_id="cached-1",
        asset_type="portrait",
        status="completed",
        result_url="https://example.com/cached.png",
    )
    mock_repo.get_ready_by_cache_key.return_value = cached

    request = AssetGenerationRequest(
        asset_type=AssetType.PORTRAIT,
        prompt="A brave warrior",
    )

    response = await service.generate_asset(request)

    assert response.asset_id == "cached-1"
    assert response.generation_status == AssetGenerationStatus.COMPLETED
    assert response.cache_hit is True
    assert response.result_url == "https://example.com/cached.png"
    mock_repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_provider_failure_returns_failed_asset(service, mock_repo):
    mock_repo.get_ready_by_cache_key.return_value = None
    mock_repo.create.return_value = MagicMock()

    request = AssetGenerationRequest(
        asset_type=AssetType.PORTRAIT,
        prompt="A brave warrior",
    )

    with patch(
        "llm_rpg.services.asset_generation_service.get_asset_provider"
    ) as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.generate = AsyncMock(side_effect=RuntimeError("API timeout"))
        mock_get_provider.return_value = mock_provider

        response = await service.generate_asset(request)

    assert response.generation_status == AssetGenerationStatus.FAILED
    assert "API timeout" in response.error_message
    assert response.cache_hit is False
    mock_repo.update_status.assert_called_once_with(
        asset_id=response.asset_id,
        status="failed",
        error_message="API timeout",
    )


@pytest.mark.asyncio
async def test_provider_returns_failed_status(service, mock_repo):
    mock_repo.get_ready_by_cache_key.return_value = None
    mock_repo.create.return_value = MagicMock()

    request = AssetGenerationRequest(
        asset_type=AssetType.SCENE,
        prompt="A dark forest",
    )

    mock_result = AssetGenerationResult(
        request_id="any",
        status=AssetStatus.FAILED,
        error_message="Content policy violation",
    )

    with patch(
        "llm_rpg.services.asset_generation_service.get_asset_provider"
    ) as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.generate = AsyncMock(return_value=mock_result)
        mock_get_provider.return_value = mock_provider

        response = await service.generate_asset(request)

    assert response.generation_status == AssetGenerationStatus.FAILED
    assert "Content policy violation" in response.error_message


@pytest.mark.asyncio
async def test_integrity_error_on_cache_key_collision(service, mock_repo):
    mock_repo.get_ready_by_cache_key.return_value = None
    mock_repo.create.side_effect = IntegrityError("stmt", "params", "orig")

    cached = _make_cached_asset(
        asset_id="existing-1",
        asset_type="portrait",
        status="completed",
        result_url="https://example.com/existing.png",
    )
    # After IntegrityError, re-query returns the existing asset
    mock_repo.get_ready_by_cache_key.side_effect = [None, cached]

    request = AssetGenerationRequest(
        asset_type=AssetType.PORTRAIT,
        prompt="A brave warrior",
    )

    response = await service.generate_asset(request)

    assert response.asset_id == "existing-1"
    assert response.generation_status == AssetGenerationStatus.COMPLETED
    assert response.cache_hit is True


@pytest.mark.asyncio
async def test_integrity_error_no_ready_asset(service, mock_repo):
    # First call: cache miss. Second call (after IntegrityError): still None
    mock_repo.get_ready_by_cache_key.side_effect = [None, None]
    mock_repo.create.side_effect = IntegrityError("stmt", "params", "orig")

    request = AssetGenerationRequest(
        asset_type=AssetType.PORTRAIT,
        prompt="A brave warrior",
    )

    response = await service.generate_asset(request)

    assert response.generation_status == AssetGenerationStatus.FAILED
    assert "Concurrent creation conflict" in response.error_message
    assert response.cache_hit is False


@pytest.mark.asyncio
async def test_generate_bgm_creates_asset(service, mock_repo):
    mock_repo.get_ready_by_cache_key.return_value = None
    mock_repo.create.return_value = MagicMock()

    request = AssetGenerationRequest(
        asset_type=AssetType.BGM,
        prompt="Epic battle music",
    )

    mock_result = AssetGenerationResult(
        request_id="any",
        status=AssetStatus.COMPLETED,
        asset_url="https://example.com/mock/bgm.mp3",
    )

    with patch(
        "llm_rpg.services.asset_generation_service.get_asset_provider"
    ) as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.generate = AsyncMock(return_value=mock_result)
        mock_get_provider.return_value = mock_provider

        response = await service.generate_asset(request)

    assert response.asset_type == AssetType.BGM
    assert response.generation_status == AssetGenerationStatus.COMPLETED
    assert response.result_url == "https://example.com/mock/bgm.mp3"


@pytest.mark.asyncio
async def test_provider_failure_update_status_also_fails(service, mock_repo):
    mock_repo.get_ready_by_cache_key.return_value = None
    mock_repo.create.return_value = MagicMock()
    mock_repo.update_status.side_effect = RuntimeError("DB down")

    request = AssetGenerationRequest(
        asset_type=AssetType.PORTRAIT,
        prompt="A brave warrior",
    )

    with patch(
        "llm_rpg.services.asset_generation_service.get_asset_provider"
    ) as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.generate = AsyncMock(side_effect=RuntimeError("API timeout"))
        mock_get_provider.return_value = mock_provider

        response = await service.generate_asset(request)

    assert response.generation_status == AssetGenerationStatus.FAILED
    assert "API timeout" in response.error_message


# --- get_asset ---


def test_get_asset_returns_correct_asset(service, mock_repo):
    cached = _make_cached_asset(
        asset_id="asset-42",
        asset_type="scene",
        status="completed",
        result_url="https://example.com/scene.png",
    )
    mock_repo.get_by_asset_id.return_value = cached

    response = service.get_asset("asset-42")

    assert response is not None
    assert response.asset_id == "asset-42"
    assert response.asset_type == AssetType.SCENE
    assert response.generation_status == AssetGenerationStatus.COMPLETED
    assert response.result_url == "https://example.com/scene.png"


def test_get_asset_returns_none_for_missing(service, mock_repo):
    mock_repo.get_by_asset_id.return_value = None

    response = service.get_asset("nonexistent")

    assert response is None


# --- list_session_assets ---


def test_list_session_assets_returns_list(service, mock_repo):
    assets = [
        _make_cached_asset(asset_id="a1", asset_type="portrait", status="completed"),
        _make_cached_asset(asset_id="a2", asset_type="bgm", status="completed"),
    ]
    mock_repo.list_by_session.return_value = assets

    result = service.list_session_assets("session-1")

    assert len(result) == 2
    assert result[0].asset_id == "a1"
    assert result[1].asset_id == "a2"
    assert result[0].asset_type == AssetType.PORTRAIT
    assert result[1].asset_type == AssetType.BGM


def test_list_session_assets_with_type_filter(service, mock_repo):
    mock_repo.list_by_session.return_value = []

    result = service.list_session_assets("session-1", asset_type="portrait")

    mock_repo.list_by_session.assert_called_once_with(
        "session-1", asset_type="portrait"
    )
    assert result == []


def test_list_session_assets_empty(service, mock_repo):
    mock_repo.list_by_session.return_value = []

    result = service.list_session_assets("session-1")

    assert result == []
