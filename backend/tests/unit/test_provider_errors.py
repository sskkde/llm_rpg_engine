"""Tests for provider error taxonomy."""

import pytest

from llm_rpg.assets.provider_errors import (
    ProviderError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderServerError,
    ProviderValidationError,
)


class TestProviderErrorHierarchy:
    """Test error subclass attributes."""

    def test_provider_auth_error_attributes(self):
        """Auth error should not be retryable with 401 status."""
        error = ProviderAuthError("openai", "auth_failed")
        assert error.retryable is False
        assert error.http_status == 401
        assert error.provider_name == "openai"
        assert error.error_code == "auth_failed"

    def test_provider_rate_limit_error_attributes(self):
        """Rate limit error should be retryable with 429 status."""
        error = ProviderRateLimitError("openai", "rate_exceeded")
        assert error.retryable is True
        assert error.http_status == 429
        assert error.provider_name == "openai"
        assert error.error_code == "rate_exceeded"

    def test_provider_timeout_error_attributes(self):
        """Timeout error should be retryable with 504 status."""
        error = ProviderTimeoutError("openai", "timeout")
        assert error.retryable is True
        assert error.http_status == 504
        assert error.provider_name == "openai"
        assert error.error_code == "timeout"

    def test_provider_server_error_attributes(self):
        """Server error should be retryable with 500 status."""
        error = ProviderServerError("openai", "internal_error")
        assert error.retryable is True
        assert error.http_status == 500
        assert error.provider_name == "openai"
        assert error.error_code == "internal_error"

    def test_provider_validation_error_attributes(self):
        """Validation error should not be retryable with 400 status."""
        error = ProviderValidationError("openai", "invalid_request")
        assert error.retryable is False
        assert error.http_status == 400
        assert error.provider_name == "openai"
        assert error.error_code == "invalid_request"


class TestToJobErrorType:
    """Test error type mapping for job tracking."""

    def test_auth_error_maps_to_auth_error(self):
        """Auth error should map to 'auth_error'."""
        error = ProviderAuthError("openai", "auth_failed")
        assert error.to_job_error_type() == "auth_error"

    def test_rate_limit_maps_to_rate_limited(self):
        """Rate limit error should map to 'rate_limited'."""
        error = ProviderRateLimitError("openai", "rate_exceeded")
        assert error.to_job_error_type() == "rate_limited"

    def test_timeout_maps_to_timeout(self):
        """Timeout error should map to 'timeout'."""
        error = ProviderTimeoutError("openai", "timeout")
        assert error.to_job_error_type() == "timeout"

    def test_server_error_maps_to_server_error(self):
        """Server error should map to 'server_error'."""
        error = ProviderServerError("openai", "internal_error")
        assert error.to_job_error_type() == "server_error"

    def test_validation_error_maps_to_bad_request(self):
        """Validation error should map to 'bad_request'."""
        error = ProviderValidationError("openai", "invalid_request")
        assert error.to_job_error_type() == "bad_request"

    def test_base_error_maps_to_provider_error(self):
        """Base provider error should map to 'provider_error'."""
        error = ProviderError("openai", "unknown")
        assert error.to_job_error_type() == "provider_error"


class TestFromProviderResponse:
    """Test error construction from HTTP responses."""

    def test_400_creates_validation_error(self):
        """HTTP 400 should create ProviderValidationError."""
        error = ProviderError.from_provider_response("openai", 400)
        assert isinstance(error, ProviderValidationError)
        assert error.retryable is False
        assert error.http_status == 400

    def test_401_creates_auth_error(self):
        """HTTP 401 should create ProviderAuthError."""
        error = ProviderError.from_provider_response("openai", 401)
        assert isinstance(error, ProviderAuthError)
        assert error.retryable is False

    def test_403_creates_auth_error(self):
        """HTTP 403 should create ProviderAuthError."""
        error = ProviderError.from_provider_response("openai", 403)
        assert isinstance(error, ProviderAuthError)
        assert error.retryable is False

    def test_429_creates_rate_limit_error(self):
        """HTTP 429 should create ProviderRateLimitError."""
        error = ProviderError.from_provider_response("openai", 429)
        assert isinstance(error, ProviderRateLimitError)
        assert error.retryable is True

    def test_504_creates_timeout_error(self):
        """HTTP 504 should create ProviderTimeoutError."""
        error = ProviderError.from_provider_response("openai", 504)
        assert isinstance(error, ProviderTimeoutError)
        assert error.retryable is True

    def test_500_creates_server_error(self):
        """HTTP 500 should create ProviderServerError."""
        error = ProviderError.from_provider_response("openai", 500)
        assert isinstance(error, ProviderServerError)
        assert error.retryable is True

    def test_502_creates_server_error(self):
        """HTTP 502 should create ProviderServerError."""
        error = ProviderError.from_provider_response("openai", 502)
        assert isinstance(error, ProviderServerError)
        assert error.retryable is True

    def test_503_creates_server_error(self):
        """HTTP 503 should create ProviderServerError."""
        error = ProviderError.from_provider_response("openai", 503)
        assert isinstance(error, ProviderServerError)
        assert error.retryable is True

    def test_unknown_status_creates_base_error(self):
        """Unknown status code should create base ProviderError."""
        error = ProviderError.from_provider_response("openai", 418)  # I'm a teapot
        assert isinstance(error, ProviderError)
        assert not isinstance(error, ProviderAuthError)
        assert error.retryable is False

    def test_extracts_message_from_response_body(self):
        """Should extract error message from response body."""
        error = ProviderError.from_provider_response(
            "openai",
            500,
            response_body={"error": "Internal server failure"},
        )
        assert error.message == "Internal server failure"

    def test_extracts_message_from_message_field(self):
        """Should extract message from 'message' field if 'error' not present."""
        error = ProviderError.from_provider_response(
            "openai",
            400,
            response_body={"message": "Invalid parameter"},
        )
        assert error.message == "Invalid parameter"


class TestErrorCatching:
    """Test that errors can be caught as ProviderError."""

    def test_auth_error_is_provider_error(self):
        """ProviderAuthError should be catchable as ProviderError."""
        with pytest.raises(ProviderError):
            raise ProviderAuthError("openai", "auth_failed")

    def test_rate_limit_error_is_provider_error(self):
        """ProviderRateLimitError should be catchable as ProviderError."""
        with pytest.raises(ProviderError):
            raise ProviderRateLimitError("openai", "rate_exceeded")

    def test_timeout_error_is_provider_error(self):
        """ProviderTimeoutError should be catchable as ProviderError."""
        with pytest.raises(ProviderError):
            raise ProviderTimeoutError("openai", "timeout")

    def test_server_error_is_provider_error(self):
        """ProviderServerError should be catchable as ProviderError."""
        with pytest.raises(ProviderError):
            raise ProviderServerError("openai", "internal_error")

    def test_validation_error_is_provider_error(self):
        """ProviderValidationError should be catchable as ProviderError."""
        with pytest.raises(ProviderError):
            raise ProviderValidationError("openai", "invalid_request")


class TestErrorMessageDefaults:
    """Test error message default behavior."""

    def test_default_message_is_class_name(self):
        """Error message should default to class name."""
        error = ProviderAuthError("openai", "auth_failed")
        assert error.message == "ProviderAuthError"

    def test_custom_message_overrides_default(self):
        """Custom message should override default."""
        error = ProviderAuthError("openai", "auth_failed", message="Invalid API key")
        assert error.message == "Invalid API key"

    def test_str_returns_message(self):
        """str(error) should return the message."""
        error = ProviderAuthError("openai", "auth_failed", message="Invalid API key")
        assert str(error) == "Invalid API key"
