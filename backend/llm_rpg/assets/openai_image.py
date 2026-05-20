"""OpenAI Image provider with client abstraction.

Provides OpenAIClientProtocol for dependency injection, RealOpenAIClient
that wraps the openai SDK, and FakeOpenAIClient for testing without API calls.
The OpenAIImageProvider accepts a client via constructor injection and maps
provider errors to the ProviderError taxonomy.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from .interfaces import (
    AssetGenerationRequest,
    AssetGenerationResult,
    AssetProvider,
    AssetStatus,
    AssetType,
)
from .provider_errors import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
    ProviderValidationError,
)

logger = logging.getLogger(__name__)


@dataclass
class ImageResponse:
    """Normalized response from an OpenAI image generation call."""

    asset_url: str
    asset_id: str
    revised_prompt: Optional[str] = None


@runtime_checkable
class OpenAIClientProtocol(Protocol):
    """Protocol for OpenAI image generation clients.

    Enables dependency injection so tests can swap in FakeOpenAIClient
    without touching real API endpoints.
    """

    async def generate_image(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
    ) -> ImageResponse:
        """Generate an image and return a normalized response."""
        ...


class RealOpenAIClient:
    """OpenAI SDK client for DALL-E image generation.

    Reads OPENAI_API_KEY from the environment.  If the key is missing the
    constructor still succeeds — the error surfaces as a ProviderAuthError
    on the first generate_image() call (safe-failure pattern).
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._client = None

    def _ensure_client(self):
        """Lazily create the openai client, raising ProviderAuthError if no key."""
        if self._client is not None:
            return
        if not self._api_key:
            raise ProviderAuthError(
                provider_name="openai_image",
                error_code="missing_api_key",
                message="OPENAI_API_KEY not configured",
            )
        try:
            from openai import OpenAI  # noqa: WPS433
        except ImportError as exc:
            raise ProviderError(
                provider_name="openai_image",
                error_code="sdk_missing",
                message="openai package is not installed",
            ) from exc
        self._client = OpenAI(api_key=self._api_key)

    async def generate_image(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
    ) -> ImageResponse:
        """Generate an image via the OpenAI DALL-E API.

        Raises:
            ProviderAuthError: If the API key is missing or invalid.
            ProviderRateLimitError: If rate-limited by the API.
            ProviderTimeoutError: If the request times out.
            ProviderServerError: On 5xx responses.
            ProviderValidationError: On 400 responses.
            ProviderError: For any other unexpected error.
        """
        self._ensure_client()
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                self._sync_generate,
                prompt,
                size,
                quality,
                n,
            )
            return response
        except ProviderError:
            raise
        except Exception as exc:
            raise self._map_exception(exc) from exc

    def _sync_generate(
        self,
        prompt: str,
        size: str,
        quality: str,
        n: int,
    ) -> ImageResponse:
        """Synchronous generation call (executed in thread pool)."""
        try:
            result = self._client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                quality=quality,
                n=n,
            )
            data = result.data[0]
            return ImageResponse(
                asset_url=data.url,
                asset_id=getattr(data, "revised_prompt", None) or f"openai_{id(result)}",
                revised_prompt=getattr(data, "revised_prompt", None),
            )
        except Exception as exc:
            raise self._map_exception(exc) from exc

    @staticmethod
    def _map_exception(exc: Exception) -> ProviderError:
        """Map an openai SDK exception to the ProviderError taxonomy."""
        status_code = getattr(exc, "status_code", None)
        if status_code is not None:
            return ProviderError.from_provider_response(
                provider_name="openai_image",
                status_code=status_code,
                response_body=None,
            )

        exc_name = type(exc).__name__.lower()
        if "auth" in exc_name or "unauthorized" in exc_name or "forbidden" in exc_name:
            return ProviderAuthError(
                provider_name="openai_image",
                error_code="auth_error",
                message=str(exc),
            )
        if "rate" in exc_name or "ratelimit" in exc_name:
            return ProviderRateLimitError(
                provider_name="openai_image",
                error_code="rate_limited",
                message=str(exc),
            )
        if "timeout" in exc_name:
            return ProviderTimeoutError(
                provider_name="openai_image",
                error_code="timeout",
                message=str(exc),
            )
        return ProviderError(
            provider_name="openai_image",
            error_code="unexpected_error",
            message=str(exc),
        )


class FakeOpenAIClient:
    """Deterministic fake client for testing.

    Never makes real API calls.  Returns predictable URLs and asset IDs
    based on the input prompt.
    """

    def __init__(self) -> None:
        self._call_count: int = 0

    async def generate_image(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
    ) -> ImageResponse:
        """Return a deterministic fake image response."""
        self._call_count += 1
        prompt_hash = hash(prompt) & 0xFFFF_FFFF
        return ImageResponse(
            asset_url=f"https://fake-openai.local/images/{prompt_hash:08x}.png",
            asset_id=f"fake_openai_{self._call_count}",
            revised_prompt=f"[fake] {prompt}",
        )


class OpenAIImageProvider(AssetProvider):
    """OpenAI DALL-E image provider with client injection.

    Accepts an OpenAIClientProtocol instance via *client*.  If no client
    is provided the default is:
      - RealOpenAIClient if OPENAI_API_KEY is set
      - FakeOpenAIClient otherwise

    Missing API key → returns FAILED result with ProviderAuthError info
    (no uncaught exception).
    """

    provider_name = "openai_image"
    supported_asset_types = [AssetType.PORTRAIT, AssetType.SCENE]

    def __init__(self, client: Optional[OpenAIClientProtocol] = None) -> None:
        if client is not None:
            self._client = client
        elif os.environ.get("OPENAI_API_KEY"):
            self._client = RealOpenAIClient()
        else:
            self._client = FakeOpenAIClient()

        self._api_key_configured = bool(os.environ.get("OPENAI_API_KEY"))

    async def generate(self, request: AssetGenerationRequest) -> AssetGenerationResult:
        """Generate an asset using the injected client.

        Returns a structured FAILED result on any ProviderError — never
        raises an uncaught exception.
        """
        start = time.time()
        prompt = request.metadata.get("prompt", "")
        size = request.metadata.get("size", "1024x1024")
        quality = request.metadata.get("quality", "standard")

        try:
            response = await self._client.generate_image(
                prompt=prompt,
                size=size,
                quality=quality,
            )
            return AssetGenerationResult(
                request_id=request.request_id,
                status=AssetStatus.COMPLETED,
                asset_url=response.asset_url,
                asset_id=response.asset_id,
                metadata={
                    "provider": self.provider_name,
                    "api_key_configured": self._api_key_configured,
                    "asset_type": request.asset_type.value,
                    "revised_prompt": response.revised_prompt,
                },
                processing_time_ms=int((time.time() - start) * 1000),
            )
        except ProviderError as exc:
            logger.warning(
                "OpenAI image generation failed: provider=%s code=%s retryable=%s",
                exc.provider_name,
                exc.error_code,
                exc.retryable,
            )
            return AssetGenerationResult(
                request_id=request.request_id,
                status=AssetStatus.FAILED,
                error_message=exc.message,
                metadata={
                    "provider": self.provider_name,
                    "api_key_configured": self._api_key_configured,
                    "error_code": exc.error_code,
                    "error_type": type(exc).__name__,
                    "retryable": exc.retryable,
                },
                processing_time_ms=int((time.time() - start) * 1000),
            )
        except Exception as exc:
            logger.warning(
                "OpenAI image generation unexpected error: %s",
                type(exc).__name__,
            )
            return AssetGenerationResult(
                request_id=request.request_id,
                status=AssetStatus.FAILED,
                error_message="Unexpected error during image generation",
                metadata={
                    "provider": self.provider_name,
                    "api_key_configured": self._api_key_configured,
                    "error_type": type(exc).__name__,
                },
                processing_time_ms=int((time.time() - start) * 1000),
            )

    async def check_status(self, request_id: str) -> AssetStatus:
        """Check status — DALL-E returns synchronously so always COMPLETED."""
        return AssetStatus.COMPLETED if self._api_key_configured else AssetStatus.FAILED

    async def cancel(self, request_id: str) -> bool:
        """DALL-E generation is synchronous; cancellation not supported."""
        return False

    def get_provider_info(self) -> dict:
        """Return provider info WITHOUT exposing the API key."""
        return {
            "provider_name": self.provider_name,
            "supported_types": [t.value for t in self.supported_asset_types],
            "configured": self._api_key_configured,
            "api_key_configured": self._api_key_configured,
        }


def register_openai_image_provider(registry) -> None:
    """Register OpenAIImageProvider in a ProviderRegistry instance.

    Uses FakeOpenAIClient so registration never requires a real API key.
    The registry's capability check still reflects whether OPENAI_API_KEY
    is set in the environment.
    """
    from .provider_registry import ProviderCapability  # noqa: C0415

    client = FakeOpenAIClient()
    provider = OpenAIImageProvider(client=client)

    capability = ProviderCapability(
        provider_name="openai_image",
        supported_asset_types=[t.value for t in provider.supported_asset_types],
        enabled=bool(os.environ.get("OPENAI_API_KEY")),
        requires_api_key=True,
        configured=bool(os.environ.get("OPENAI_API_KEY")),
        supports_async=True,
        supports_cancel=False,
        supports_cost_estimate=False,
    )
    registry.register_provider(
        name="openai_image",
        provider_class=lambda: provider,  # type: ignore[arg-type]
        capability=capability,
    )
