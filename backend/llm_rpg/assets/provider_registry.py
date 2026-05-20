"""Provider capability registry for asset generation.

Wraps the existing provider_factory to expose provider metadata,
capability introspection, and health checks without replacing it.
"""

import os
from typing import Any

from pydantic import BaseModel

from .interfaces import AssetProvider


class ProviderCapability(BaseModel):
    """Metadata about a single asset provider's capabilities."""

    provider_name: str
    supported_asset_types: list[str]
    enabled: bool = True
    requires_api_key: bool = False
    configured: bool = False
    supports_async: bool = True
    supports_cancel: bool = False
    supports_cost_estimate: bool = False


_PROVIDER_CAPABILITY_DEFAULTS: dict[str, dict[str, Any]] = {
    "mock": {
        "requires_api_key": False,
        "supports_cancel": True,
        "supports_cost_estimate": False,
    },
    "openai_image": {
        "requires_api_key": True,
        "enabled": False,
        "supports_cancel": False,
        "supports_cost_estimate": False,
    },
    "audio_placeholder": {
        "requires_api_key": False,
        "enabled": False,
        "supports_cancel": True,
        "supports_cost_estimate": False,
    },
}


def _is_provider_configured(provider_name: str, provider_instance: AssetProvider) -> bool:
    """Determine whether a provider is configured for use.

    Only checks configuration/environment — never calls external APIs.
    """
    if provider_name == "openai_image":
        return bool(os.environ.get("OPENAI_API_KEY"))
    # Mock and unknown providers are always "configured"
    return True


def _build_capability(
    provider_instance: AssetProvider,
    overrides: dict[str, Any] | None = None,
) -> ProviderCapability:
    """Build a ProviderCapability from a live provider instance."""
    defaults = _PROVIDER_CAPABILITY_DEFAULTS.get(provider_instance.provider_name, {})
    if overrides:
        defaults = {**defaults, **overrides}

    configured = _is_provider_configured(provider_instance.provider_name, provider_instance)

    return ProviderCapability(
        provider_name=provider_instance.provider_name,
        supported_asset_types=[t.value for t in provider_instance.supported_asset_types],
        enabled=defaults.get("enabled", True),
        requires_api_key=defaults.get("requires_api_key", False),
        configured=configured,
        supports_async=defaults.get("supports_async", True),
        supports_cancel=defaults.get("supports_cancel", False),
        supports_cost_estimate=defaults.get("supports_cost_estimate", False),
    )


class ProviderRegistry:
    """Registry of asset provider capabilities.

    Wraps provider_factory and exposes introspection / health-check
    methods.  Does **not** replace provider_factory — existing callers
    continue to use it unchanged.
    """

    def __init__(self) -> None:
        self._providers: dict[str, AssetProvider] = {}
        self._capabilities: dict[str, ProviderCapability] = {}
        self._auto_register()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_provider(
        self,
        name: str,
        provider_class: type,
        capability: ProviderCapability | None = None,
    ) -> None:
        """Register a provider by name and class.

        If *capability* is omitted it is derived automatically from the
        provider instance and the static defaults.
        """
        provider_instance = provider_class()
        self._providers[name] = provider_instance
        if capability is None:
            capability = _build_capability(provider_instance)
        self._capabilities[name] = capability

    def _auto_register(self) -> None:
        """Auto-register the built-in providers via provider_factory."""
        # Import here to avoid circular imports at module level.
        from .provider_factory import get_asset_provider  # noqa: C0415

        # provider_factory exposes exactly these two providers.
        for name in ("mock", "openai_image", "audio_placeholder"):
            try:
                provider_instance = get_asset_provider(name)
                self._providers[name] = provider_instance
                self._capabilities[name] = _build_capability(provider_instance)
            except ValueError:
                # Unknown name — skip silently.
                pass

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_providers(self) -> list[ProviderCapability]:
        """Return capability metadata for every registered provider."""
        return list(self._capabilities.values())

    def get_provider_info(self, provider_name: str) -> ProviderCapability | None:
        """Return capability metadata for a single provider, or None."""
        return self._capabilities.get(provider_name)

    def get_available_provider(self, asset_type: str) -> str | None:
        """Find the first enabled **and** configured provider supporting *asset_type*.

        Returns the provider name, or None if no suitable provider exists.
        """
        for cap in self._capabilities.values():
            if cap.enabled and cap.configured and asset_type in cap.supported_asset_types:
                return cap.provider_name
        # Fallback: try enabled-but-unconfigured (e.g. mock always works).
        for cap in self._capabilities.values():
            if cap.enabled and asset_type in cap.supported_asset_types:
                return cap.provider_name
        return None

    # ------------------------------------------------------------------
    # Health check (configuration-only — no real API calls)
    # ------------------------------------------------------------------

    def check_provider_health(self, provider_name: str) -> dict[str, Any]:
        """Return a health dict for a provider.

        Checks configuration state only; never calls external APIs.
        """
        cap = self._capabilities.get(provider_name)
        if cap is None:
            return {
                "configured": False,
                "enabled": False,
                "last_error": f"Unknown provider: {provider_name}",
            }
        return {
            "configured": cap.configured,
            "enabled": cap.enabled,
            "last_error": None,
        }
