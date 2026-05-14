"""Tests for asset cache key resolver."""

import pytest

from llm_rpg.core.assets.cache_key import build_asset_cache_key
from llm_rpg.models.assets import AssetGenerationRequest, AssetType


class TestCacheKeyDeterminism:
    """Cache keys must be deterministic for the same semantic request."""

    def test_same_request_same_key(self):
        req1 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
        )
        req2 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
        )
        assert build_asset_cache_key(req1) == build_asset_cache_key(req2)

    def test_different_prompt_different_key(self):
        req1 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
        )
        req2 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A wise mage",
        )
        assert build_asset_cache_key(req1) != build_asset_cache_key(req2)

    def test_different_asset_type_different_key(self):
        req1 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
        )
        req2 = AssetGenerationRequest(
            asset_type=AssetType.SCENE,
            prompt="A brave warrior",
        )
        assert build_asset_cache_key(req1) != build_asset_cache_key(req2)

    def test_style_affects_key(self):
        req1 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
            style="anime",
        )
        req2 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
            style="realistic",
        )
        assert build_asset_cache_key(req1) != build_asset_cache_key(req2)

    def test_provider_affects_key(self):
        req1 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
            provider="mock",
        )
        req2 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
            provider="dalle",
        )
        assert build_asset_cache_key(req1) != build_asset_cache_key(req2)

    def test_session_scoped(self):
        req = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
            session_id="session-1",
        )
        unscoped = build_asset_cache_key(req, session_scoped=False)
        scoped = build_asset_cache_key(req, session_scoped=True)
        assert unscoped != scoped

    def test_session_scoped_matches(self):
        req1 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
            session_id="session-1",
        )
        req2 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
            session_id="session-1",
        )
        assert build_asset_cache_key(req1, session_scoped=True) == build_asset_cache_key(
            req2, session_scoped=True
        )

    def test_not_session_scoped_differs_for_diff_sessions(self):
        req1 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
            session_id="session-1",
        )
        req2 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
            session_id="session-2",
        )
        assert build_asset_cache_key(req1) == build_asset_cache_key(req2)

    def test_bgm_asset_type(self):
        req = AssetGenerationRequest(
            asset_type=AssetType.BGM,
            prompt="Calm forest ambient music",
        )
        key = build_asset_cache_key(req)
        assert isinstance(key, str)
        assert len(key) == 64

    def test_empty_metadata_is_stable(self):
        req1 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
            metadata={},
        )
        req2 = AssetGenerationRequest(
            asset_type=AssetType.PORTRAIT,
            prompt="A brave warrior",
        )
        assert build_asset_cache_key(req1) == build_asset_cache_key(req2)
