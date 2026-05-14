"""Asset provider factory for selecting and instantiating asset providers."""

import os

from .interfaces import AssetProvider
from . import MockAssetProvider


def get_asset_provider(
    name: str | None = None,
) -> AssetProvider:
    """Get an asset provider by name.
    
    Args:
        name: Provider name. If None, reads ASSET_PROVIDER env var.
              Defaults to "mock" if env var is not set.
    
    Returns:
        An instance of AssetProvider.
    
    Raises:
        ValueError: If the provider name is unknown.
    """
    if name is None:
        name = os.getenv("ASSET_PROVIDER", "mock")
    
    providers = {
        "mock": MockAssetProvider,
    }
    
    provider_class = providers.get(name)
    if provider_class is None:
        raise ValueError(
            f"Unknown asset provider: '{name}'. Available providers: {', '.join(sorted(providers.keys()))}"
        )
    
    return provider_class()
