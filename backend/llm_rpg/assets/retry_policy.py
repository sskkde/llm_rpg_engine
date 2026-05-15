"""Retry policy for asset generation jobs.

Determines if/when to retry a failed asset generation job based on
error type, HTTP status code, and attempt count.
"""

from datetime import datetime, timedelta
from typing import Optional


class RetryPolicy:
    """Determines if/when to retry a failed asset generation job."""

    DEFAULT_MAX_ATTEMPTS = 3
    BACKOFF_SECONDS = [30, 120, 600]  # 30s, 2m, 10m

    # Non-retryable error patterns (case-insensitive substring match)
    NON_RETRYABLE_PATTERNS = [
        "4xx",
        "bad_request",
        "unauthorized",
        "forbidden",
        "not_found",
        "rate_limited",
    ]

    # Retryable error patterns (case-insensitive substring match)
    RETRYABLE_PATTERNS = [
        "5xx",
        "timeout",
        "connection",
        "unavailable",
        "server_error",
        "service_error",
    ]

    def should_retry(
        self,
        attempt_count: int,
        error_type: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> bool:
        """Determine whether a failed job should be retried.

        Args:
            attempt_count: Number of attempts already made (0-based from the job's
                attempt_count field, which is incremented *before* this check in
                schedule_retry, so we compare against max_attempts).
            error_type: Optional error type string (e.g. "TimeoutError").
            status_code: Optional HTTP status code from the provider.

        Returns:
            True if the job should be retried, False otherwise.
        """
        # Don't retry if max attempts reached
        if attempt_count >= self.DEFAULT_MAX_ATTEMPTS:
            return False

        # Don't retry on 4xx client errors
        if status_code is not None and 400 <= status_code < 500:
            return False

        if error_type is not None:
            error_normalized = error_type.lower().replace("_", "").replace("-", "")

            for pattern in self.NON_RETRYABLE_PATTERNS:
                pattern_normalized = pattern.lower().replace("_", "").replace("-", "")
                if pattern_normalized in error_normalized:
                    return False

            for pattern in self.RETRYABLE_PATTERNS:
                pattern_normalized = pattern.lower().replace("_", "").replace("-", "")
                if pattern_normalized in error_normalized:
                    return True

        # Default: retry if we haven't exhausted attempts and no non-retryable signal
        return True

    def get_next_retry_delay(self, attempt_count: int) -> int:
        """Get the backoff delay in seconds for the given attempt.

        Args:
            attempt_count: Current attempt count (0-based index into BACKOFF_SECONDS).

        Returns:
            Delay in seconds. Capped at the last value in BACKOFF_SECONDS
            if attempt_count exceeds the array length.
        """
        if attempt_count < len(self.BACKOFF_SECONDS):
            return self.BACKOFF_SECONDS[attempt_count]
        return self.BACKOFF_SECONDS[-1]

    def get_next_retry_at(self, attempt_count: int) -> datetime:
        """Calculate the next retry time.

        Args:
            attempt_count: Current attempt count (0-based).

        Returns:
            datetime representing when the next retry should occur.
        """
        delay = self.get_next_retry_delay(attempt_count)
        return datetime.now() + timedelta(seconds=delay)
