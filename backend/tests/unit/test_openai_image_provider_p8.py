"""Tests for P8 OpenAI image provider client abstraction.

Covers:
- FakeOpenAIClient generates deterministic responses
- RealOpenAIClient maps errors to ProviderError taxonomy
- OpenAIImageProvider with client injection
- Missing OPENAI_API_KEY → FAILED result with ProviderAuthError
- API key never appears in logs or error messages
- Provider registered in ProviderRegistry with correct capabilities
"""

from unittest.mock import MagicMock

import pytest

from llm_rpg.assets.interfaces import (
    AssetGenerationRequest,
    AssetStatus,
    AssetType,
)
from llm_rpg.assets.openai_image import (
    FakeOpenAIClient,
    ImageResponse,
    OpenAIClientProtocol,
    OpenAIImageProvider,
    RealOpenAIClient,
    register_openai_image_provider,
)
from llm_rpg.assets.provider_errors import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
    ProviderValidationError,
)
from llm_rpg.assets.provider_registry import ProviderRegistry


def _make_request(
    asset_type: AssetType = AssetType.PORTRAIT,
    prompt: str = "a warrior in armor",
    **metadata_overrides: str,
) -> AssetGenerationRequest:
    metadata = {"prompt": prompt, **metadata_overrides}
    return AssetGenerationRequest(
        asset_type=asset_type,
        request_id="test-req-001",
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# FakeOpenAIClient
# ---------------------------------------------------------------------------

class TestFakeOpenAIClient:

    @pytest.mark.asyncio
    async def test_returns_image_response(self):
        client = FakeOpenAIClient()
        resp = await client.generate_image(prompt="a dragon")
        assert isinstance(resp, ImageResponse)
        assert resp.asset_url.startswith("https://fake-openai.local/images/")
        assert resp.asset_id.startswith("fake_openai_")
        assert resp.revised_prompt == "[fake] a dragon"

    @pytest.mark.asyncio
    async def test_deterministic_urls_for_same_prompt(self):
        client = FakeOpenAIClient()
        r1 = await client.generate_image(prompt="castle")
        r2 = await client.generate_image(prompt="castle")
        assert r1.asset_url == r2.asset_url

    @pytest.mark.asyncio
    async def test_different_prompts_different_urls(self):
        client = FakeOpenAIClient()
        r1 = await client.generate_image(prompt="castle")
        r2 = await client.generate_image(prompt="forest")
        assert r1.asset_url != r2.asset_url

    @pytest.mark.asyncio
    async def test_call_count_increments(self):
        client = FakeOpenAIClient()
        assert client._call_count == 0
        _r = await client.generate_image(prompt="a")
        assert client._call_count == 1
        _r = await client.generate_image(prompt="b")
        assert client._call_count == 2

    @pytest.mark.asyncio
    async def test_asset_ids_are_unique(self):
        client = FakeOpenAIClient()
        r1 = await client.generate_image(prompt="x")
        r2 = await client.generate_image(prompt="x")
        assert r1.asset_id != r2.asset_id

    def test_satisfies_protocol(self):
        assert isinstance(FakeOpenAIClient(), OpenAIClientProtocol)


# ---------------------------------------------------------------------------
# RealOpenAIClient error mapping
# ---------------------------------------------------------------------------

class TestRealOpenAIClientErrorMapping:

    def test_missing_key_raises_auth_error(self):
        import os
        original = os.environ.pop("OPENAI_API_KEY", None)
        try:
            client = RealOpenAIClient(api_key=None)
            with pytest.raises(ProviderAuthError) as exc_info:
                client._ensure_client()
            assert exc_info.value.error_code == "missing_api_key"
        finally:
            if original is not None:
                os.environ["OPENAI_API_KEY"] = original

    def test_map_exception_with_status_code_401(self):
        exc = MagicMock(status_code=401)
        result = RealOpenAIClient._map_exception(exc)
        assert isinstance(result, ProviderAuthError)
        assert result.retryable is False

    def test_map_exception_with_status_code_429(self):
        exc = MagicMock(status_code=429)
        result = RealOpenAIClient._map_exception(exc)
        assert isinstance(result, ProviderRateLimitError)
        assert result.retryable is True

    def test_map_exception_with_status_code_504(self):
        exc = MagicMock(status_code=504)
        result = RealOpenAIClient._map_exception(exc)
        assert isinstance(result, ProviderTimeoutError)
        assert result.retryable is True

    def test_map_exception_with_status_code_500(self):
        exc = MagicMock(status_code=500)
        result = RealOpenAIClient._map_exception(exc)
        assert isinstance(result, ProviderServerError)
        assert result.retryable is True

    def test_map_exception_with_status_code_400(self):
        exc = MagicMock(status_code=400)
        result = RealOpenAIClient._map_exception(exc)
        assert isinstance(result, ProviderValidationError)
        assert result.retryable is False

    def test_map_exception_by_name_auth(self):
        AuthExc = type("AuthenticationError", (Exception,), {})
        exc = AuthExc("auth fail")
        result = RealOpenAIClient._map_exception(exc)
        assert isinstance(result, ProviderAuthError)

    def test_map_exception_by_name_rate(self):
        RateExc = type("RateLimitError", (Exception,), {})
        exc = RateExc("rate exceeded")
        result = RealOpenAIClient._map_exception(exc)
        assert isinstance(result, ProviderRateLimitError)

    def test_map_exception_by_name_timeout(self):
        TimeoutExc = type("TimeoutError", (Exception,), {})
        exc = TimeoutExc("timeout")
        result = RealOpenAIClient._map_exception(exc)
        assert isinstance(result, ProviderTimeoutError)

    def test_map_exception_fallback(self):
        exc = RuntimeError("something weird")
        result = RealOpenAIClient._map_exception(exc)
        assert isinstance(result, ProviderError)
        assert not isinstance(result, ProviderAuthError)


# ---------------------------------------------------------------------------
# OpenAIImageProvider with FakeOpenAIClient
# ---------------------------------------------------------------------------

class TestOpenAIImageProviderFakeClient:

    @pytest.mark.asyncio
    async def test_generate_returns_completed(self):
        provider = OpenAIImageProvider(client=FakeOpenAIClient())
        request = _make_request()
        result = await provider.generate(request)
        assert result.status == AssetStatus.COMPLETED
        assert result.asset_url is not None
        assert result.asset_id is not None
        assert result.request_id == "test-req-001"

    @pytest.mark.asyncio
    async def test_generate_metadata_contains_provider_info(self):
        provider = OpenAIImageProvider(client=FakeOpenAIClient())
        request = _make_request()
        result = await provider.generate(request)
        assert result.metadata["provider"] == "openai_image"
        assert "api_key_configured" in result.metadata
        assert result.metadata["asset_type"] == "portrait"

    @pytest.mark.asyncio
    async def test_generate_portrait_and_scene(self):
        for asset_type in (AssetType.PORTRAIT, AssetType.SCENE):
            provider = OpenAIImageProvider(client=FakeOpenAIClient())
            request = _make_request(asset_type=asset_type)
            result = await provider.generate(request)
            assert result.status == AssetStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_check_status_returns_asset_status(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        provider = OpenAIImageProvider(client=FakeOpenAIClient())
        status = await provider.check_status("any-id")
        assert status == AssetStatus.FAILED

    @pytest.mark.asyncio
    async def test_cancel_returns_false(self):
        provider = OpenAIImageProvider(client=FakeOpenAIClient())
        assert await provider.cancel("any-id") is False

    def test_supports_portrait_and_scene(self):
        provider = OpenAIImageProvider(client=FakeOpenAIClient())
        assert provider.supports(AssetType.PORTRAIT)
        assert provider.supports(AssetType.SCENE)
        assert not provider.supports(AssetType.BGM)


# ---------------------------------------------------------------------------
# Missing OPENAI_API_KEY → auth error in FAILED result
# ---------------------------------------------------------------------------

def _make_auth_raising_client():
    """Return a client that raises ProviderAuthError (simulates missing key)."""

    class _AuthClient:
        async def generate_image(
            self,
            prompt: str,
            size: str = "1024x1024",
            quality: str = "standard",
            n: int = 1,
        ) -> ImageResponse:
            raise ProviderAuthError(
                provider_name="openai_image",
                error_code="missing_api_key",
                message="OPENAI_API_KEY not configured",
            )

    return _AuthClient()


class TestMissingApiKey:

    @pytest.mark.asyncio
    async def test_no_key_returns_failed_with_auth_error(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        provider = OpenAIImageProvider(client=_make_auth_raising_client())
        request = _make_request()
        result = await provider.generate(request)

        assert result.status == AssetStatus.FAILED
        assert result.error_message is not None
        assert "not configured" in result.error_message
        assert result.metadata.get("error_type") == "ProviderAuthError"
        assert result.metadata.get("retryable") is False

    @pytest.mark.asyncio
    async def test_no_key_no_uncaught_exception(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        provider = OpenAIImageProvider(client=_make_auth_raising_client())
        request = _make_request()
        result = await provider.generate(request)
        assert result.status == AssetStatus.FAILED

    @pytest.mark.asyncio
    async def test_default_no_key_uses_fake_client_in_testing_env(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("APP_ENV", "testing")
        provider = OpenAIImageProvider()
        assert isinstance(provider._client, FakeOpenAIClient)

    @pytest.mark.asyncio
    async def test_default_with_key_uses_real_client(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key")
        provider = OpenAIImageProvider()
        assert isinstance(provider._client, RealOpenAIClient)


# ---------------------------------------------------------------------------
# API key never leaked in logs or error messages
# ---------------------------------------------------------------------------

class TestApiKeyNeverLeaked:

    @pytest.mark.asyncio
    async def test_error_message_does_not_contain_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        provider = OpenAIImageProvider(client=_make_auth_raising_client())
        request = _make_request()
        result = await provider.generate(request)

        assert result.error_message is not None
        assert "sk-" not in result.error_message

    def test_provider_info_does_not_expose_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key-12345")
        provider = OpenAIImageProvider(client=FakeOpenAIClient())
        info = provider.get_provider_info()
        info_str = str(info)
        assert "sk-super-secret-key-12345" not in info_str
        assert "sk-" not in info_str

    @pytest.mark.asyncio
    async def test_metadata_does_not_contain_key_value(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key-12345")
        provider = OpenAIImageProvider(client=FakeOpenAIClient())
        request = _make_request()
        result = await provider.generate(request)
        result_str = str(result.metadata)
        assert "sk-super-secret-key-12345" not in result_str
        assert "sk-" not in result_str


# ---------------------------------------------------------------------------
# Provider error mapping through provider
# ---------------------------------------------------------------------------

def _make_error_client(
    error: ProviderError,
) -> OpenAIClientProtocol:
    """Create a client that raises a specific ProviderError."""

    class _ErrorClient:
        async def generate_image(
            self,
            prompt: str,
            size: str = "1024x1024",
            quality: str = "standard",
            n: int = 1,
        ) -> ImageResponse:
            raise error

    return _ErrorClient()


class TestProviderErrorMapping:

    @pytest.mark.asyncio
    async def test_rate_limit_error_returns_failed(self):
        error = ProviderRateLimitError(
            provider_name="openai_image",
            error_code="rate_limited",
            message="Rate limit exceeded",
        )
        provider = OpenAIImageProvider(client=_make_error_client(error))
        result = await provider.generate(_make_request())
        assert result.status == AssetStatus.FAILED
        assert result.metadata["error_type"] == "ProviderRateLimitError"
        assert result.metadata["retryable"] is True

    @pytest.mark.asyncio
    async def test_server_error_returns_failed(self):
        error = ProviderServerError(
            provider_name="openai_image",
            error_code="server_error",
            message="Internal server error",
        )
        provider = OpenAIImageProvider(client=_make_error_client(error))
        result = await provider.generate(_make_request())
        assert result.status == AssetStatus.FAILED
        assert result.metadata["error_type"] == "ProviderServerError"
        assert result.metadata["retryable"] is True

    @pytest.mark.asyncio
    async def test_timeout_error_returns_failed(self):
        error = ProviderTimeoutError(
            provider_name="openai_image",
            error_code="timeout",
            message="Request timed out",
        )
        provider = OpenAIImageProvider(client=_make_error_client(error))
        result = await provider.generate(_make_request())
        assert result.status == AssetStatus.FAILED
        assert result.metadata["error_type"] == "ProviderTimeoutError"
        assert result.metadata["retryable"] is True

    @pytest.mark.asyncio
    async def test_validation_error_returns_failed(self):
        error = ProviderValidationError(
            provider_name="openai_image",
            error_code="bad_request",
            message="Invalid request",
        )
        provider = OpenAIImageProvider(client=_make_error_client(error))
        result = await provider.generate(_make_request())
        assert result.status == AssetStatus.FAILED
        assert result.metadata["error_type"] == "ProviderValidationError"
        assert result.metadata["retryable"] is False

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_failed(self):
        class BrokenClient:
            async def generate_image(
                self,
                prompt: str,
                size: str = "1024x1024",
                quality: str = "standard",
                n: int = 1,
            ) -> ImageResponse:
                raise RuntimeError("unexpected failure")

        provider = OpenAIImageProvider(client=BrokenClient())
        result = await provider.generate(_make_request())
        assert result.status == AssetStatus.FAILED
        assert result.error_message == "Unexpected error during image generation"
        assert result.metadata["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------

class TestRegistryIntegration:

    def test_register_openai_image_provider(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        register_openai_image_provider(registry)

        info = registry.get_provider_info("openai_image")
        assert info is not None
        assert info.provider_name == "openai_image"
        assert info.requires_api_key is True
        assert "portrait" in info.supported_asset_types
        assert "scene" in info.supported_asset_types

    def test_register_with_key_configured(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        registry = ProviderRegistry()
        register_openai_image_provider(registry)

        info = registry.get_provider_info("openai_image")
        assert info is not None
        assert info.configured is True

    def test_register_without_key_not_configured(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        register_openai_image_provider(registry)

        info = registry.get_provider_info("openai_image")
        assert info is not None
        assert info.configured is False

    def test_auto_register_includes_openai_image(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        providers = registry.list_providers()
        names = [p.provider_name for p in providers]
        assert "openai_image" in names

    def test_registered_provider_exists(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        register_openai_image_provider(registry)

        provider = registry._providers.get("openai_image")
        assert provider is not None

    @pytest.mark.asyncio
    async def test_registered_provider_generates_with_fake_client(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        registry = ProviderRegistry()
        register_openai_image_provider(registry)

        provider = registry._providers["openai_image"]
        request = _make_request()
        result = await provider.generate(request)
        assert result.status == AssetStatus.COMPLETED


# ---------------------------------------------------------------------------
# OpenAIClientProtocol compliance
# ---------------------------------------------------------------------------

class TestProtocolCompliance:

    def test_real_client_satisfies_protocol(self):
        client = RealOpenAIClient(api_key="sk-test")
        assert isinstance(client, OpenAIClientProtocol)

    def test_fake_client_satisfies_protocol(self):
        client = FakeOpenAIClient()
        assert isinstance(client, OpenAIClientProtocol)

    def test_custom_client_satisfies_protocol(self):
        class CustomClient:
            async def generate_image(
                self,
                prompt: str,
                size: str = "1024x1024",
                quality: str = "standard",
                n: int = 1,
            ) -> ImageResponse:
                return ImageResponse(asset_url="custom", asset_id="custom")

        assert isinstance(CustomClient(), OpenAIClientProtocol)


# ---------------------------------------------------------------------------
# Production no-key scenario: structured FAILED result
# ---------------------------------------------------------------------------

class TestProductionNoKeyBehavior:

    @pytest.mark.asyncio
    async def test_openai_provider_testing_uses_fake_client_without_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("APP_ENV", "testing")
        provider = OpenAIImageProvider()
        assert isinstance(provider._client, FakeOpenAIClient)
        request = _make_request()
        result = await provider.generate(request)
        assert result.status == AssetStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_openai_provider_production_without_key_fails_safely(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("ASSET_OPENAI_FAKE_FALLBACK", raising=False)
        provider = OpenAIImageProvider()
        assert provider._client is None
        request = _make_request()
        result = await provider.generate(request)
        assert result.status == AssetStatus.FAILED
        assert result.error_message == "OPENAI_API_KEY not configured"
        assert result.metadata["error_code"] == "missing_api_key"
        assert result.metadata["error_type"] == "ProviderAuthError"
        assert result.metadata["retryable"] is False
        assert result.metadata["api_key_configured"] is False
        assert result.processing_time_ms == 0

    @pytest.mark.asyncio
    async def test_openai_provider_with_injected_fake_client_succeeds(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        provider = OpenAIImageProvider(client=FakeOpenAIClient())
        request = _make_request()
        result = await provider.generate(request)
        assert result.status == AssetStatus.COMPLETED
        assert result.asset_url is not None

    @pytest.mark.asyncio
    async def test_production_no_key_check_status_returns_failed(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("ASSET_OPENAI_FAKE_FALLBACK", raising=False)
        provider = OpenAIImageProvider()
        status = await provider.check_status("any-id")
        assert status == AssetStatus.FAILED

    @pytest.mark.asyncio
    async def test_fake_fallback_env_var_enables_fake_client(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.setenv("ASSET_OPENAI_FAKE_FALLBACK", "true")
        provider = OpenAIImageProvider()
        assert isinstance(provider._client, FakeOpenAIClient)
