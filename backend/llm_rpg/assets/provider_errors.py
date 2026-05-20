"""Provider error taxonomy for asset generation.

Defines a hierarchy of exceptions for provider errors with:
- provider_name: Which provider raised the error
- error_code: Machine-readable error code
- retryable: Whether the error is recoverable
- http_status: HTTP status code if applicable
"""

from typing import Optional


class ProviderError(Exception):
    """Base exception for all provider errors.

    Attributes:
        provider_name: Name of the provider that raised the error.
        error_code: Machine-readable error code.
        message: Human-readable error message.
        retryable: Whether the operation can be retried.
        http_status: HTTP status code if applicable.
    """

    retryable: bool = False
    http_status: Optional[int] = None

    def __init__(
        self,
        provider_name: str,
        error_code: str,
        message: Optional[str] = None,
    ):
        self.provider_name = provider_name
        self.error_code = error_code
        self.message = message or self.__class__.__name__
        super().__init__(self.message)

    def to_job_error_type(self) -> str:
        """Map error to job error type for last_error_type field.

        Returns:
            Error type string for use in AssetJobRunner.
        """
        return "provider_error"

    @classmethod
    def from_provider_response(
        cls,
        provider_name: str,
        status_code: int,
        response_body: Optional[dict] = None,
    ) -> "ProviderError":
        """Create appropriate error from HTTP response.

        Args:
            provider_name: Name of the provider.
            status_code: HTTP status code.
            response_body: Optional response body for error details.

        Returns:
            Appropriate ProviderError subclass instance.
        """
        error_code = f"http_{status_code}"
        message = None
        if response_body:
            message = response_body.get("error") or response_body.get("message")

        if status_code == 400:
            return ProviderValidationError(
                provider_name=provider_name,
                error_code=error_code,
                message=message or "Validation error",
            )
        elif status_code in (401, 403):
            return ProviderAuthError(
                provider_name=provider_name,
                error_code=error_code,
                message=message or "Authentication error",
            )
        elif status_code == 429:
            return ProviderRateLimitError(
                provider_name=provider_name,
                error_code=error_code,
                message=message or "Rate limit exceeded",
            )
        elif status_code == 504:
            return ProviderTimeoutError(
                provider_name=provider_name,
                error_code=error_code,
                message=message or "Request timed out",
            )
        elif 500 <= status_code < 600:
            return ProviderServerError(
                provider_name=provider_name,
                error_code=error_code,
                message=message or "Server error",
            )
        else:
            return ProviderError(
                provider_name=provider_name,
                error_code=error_code,
                message=message or f"Provider error: {status_code}",
            )


class ProviderAuthError(ProviderError):
    """Authentication/authorization error (401, 403).

    These errors should NOT be retried as credentials are invalid.
    """

    retryable = False
    http_status = 401

    def to_job_error_type(self) -> str:
        return "auth_error"


class ProviderRateLimitError(ProviderError):
    """Rate limit exceeded error (429).

    These errors CAN be retried after a backoff period.
    """

    retryable = True
    http_status = 429

    def to_job_error_type(self) -> str:
        return "rate_limited"


class ProviderTimeoutError(ProviderError):
    """Request timeout error (504).

    These errors CAN be retried as they may be transient.
    """

    retryable = True
    http_status = 504

    def to_job_error_type(self) -> str:
        return "timeout"


class ProviderServerError(ProviderError):
    """Server-side error (5xx).

    These errors CAN be retried as they may be transient.
    """

    retryable = True
    http_status = 500

    def to_job_error_type(self) -> str:
        return "server_error"


class ProviderValidationError(ProviderError):
    """Client validation error (400).

    These errors should NOT be retried as the request is invalid.
    """

    retryable = False
    http_status = 400

    def to_job_error_type(self) -> str:
        return "bad_request"
