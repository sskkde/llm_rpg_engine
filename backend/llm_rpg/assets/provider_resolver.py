"""Asset provider resolver with per-type env var fallback chain.

Resolves the appropriate provider name for each asset type via
environment variable fallback chains, with validation and safe defaults.
"""

import logging
import os

from .interfaces import AssetType

logger = logging.getLogger(__name__)

# Known valid provider names (synchronized with provider_factory.py)
KNOWN_PROVIDERS = {"mock", "openai_image", "audio_placeholder"}


def resolve_asset_provider_name(asset_type: AssetType) -> str:
    """Resolve provider name for asset type via env var fallback chain.

    Each asset type has a specific fallback chain that groups similar
    asset types (image vs audio) before falling back to a global default.

    Args:
        asset_type: The type of asset being generated.

    Returns:
        A valid provider name (never None, never raises).

    Example fallback chains:
        PORTRAIT: ASSET_PROVIDER_PORTRAIT → IMAGE → DEFAULT → "mock"
        BGM: ASSET_PROVIDER_BGM → AUDIO → DEFAULT → "mock"
    """
    if asset_type == AssetType.PORTRAIT:
        return _resolve_chain("ASSET_PROVIDER_PORTRAIT", "ASSET_PROVIDER_IMAGE", "ASSET_PROVIDER_DEFAULT")
    if asset_type == AssetType.SCENE:
        return _resolve_chain("ASSET_PROVIDER_SCENE", "ASSET_PROVIDER_IMAGE", "ASSET_PROVIDER_DEFAULT")
    if asset_type == AssetType.BGM:
        return _resolve_chain("ASSET_PROVIDER_BGM", "ASSET_PROVIDER_AUDIO", "ASSET_PROVIDER_DEFAULT")
    if asset_type == AssetType.SFX:
        return _resolve_chain("ASSET_PROVIDER_SFX", "ASSET_PROVIDER_AUDIO", "ASSET_PROVIDER_DEFAULT")
    return os.getenv("ASSET_PROVIDER_DEFAULT") or "mock"


def _resolve_chain(*env_vars: str) -> str:
    """Try env vars in order, validate providers, fallback to mock.

    Args:
        *env_vars: Environment variable names to check in order.

    Returns:
        A valid provider name from the first set env var,
        or "mock" if none are set or contain unknown providers.
    """
    for var in env_vars:
        val = os.getenv(var)
        if val:
            if val in KNOWN_PROVIDERS:
                return val
            logger.warning(
                "Unknown provider '%s' from %s, falling back",
                val,
                var,
            )
    return "mock"
