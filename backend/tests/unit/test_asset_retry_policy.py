"""Unit tests for RetryPolicy."""

from datetime import datetime, timedelta

from llm_rpg.assets.retry_policy import RetryPolicy


class TestShouldRetry:
    def test_max_attempts(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=3) is False

    def test_should_retry_4xx(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, status_code=400) is False

    def test_should_retry_5xx(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, status_code=500) is True

    def test_should_retry_timeout(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, error_type="TimeoutError") is True

    def test_should_retry_unavailable(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, error_type="ServiceUnavailable") is True

    def test_should_not_retry_bad_request(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, error_type="BadRequestError") is False

    def test_should_not_retry_unauthorized(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, error_type="UnauthorizedError") is False

    def test_should_not_retry_forbidden(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, error_type="ForbiddenError") is False

    def test_should_not_retry_not_found(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, error_type="NotFoundError") is False

    def test_should_not_retry_rate_limited(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, error_type="RateLimitedError") is False

    def test_should_retry_connection_error(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, error_type="ConnectionError") is True

    def test_should_retry_server_error(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, error_type="ServerError") is True

    def test_should_retry_service_error(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, error_type="ServiceError") is True

    def test_should_retry_4xx_error_type(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, error_type="4xxClientError") is False

    def test_should_retry_5xx_error_type(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, error_type="5xxServerError") is True

    def test_default_retry_when_no_signals(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0) is True

    def test_max_attempts_overrides_retryable_error(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=3, error_type="TimeoutError") is False

    def test_4xx_overrides_retryable_error_type(self):
        policy = RetryPolicy()
        assert policy.should_retry(attempt_count=0, error_type="TimeoutError", status_code=400) is False


class TestGetNextRetryDelay:
    def test_get_next_retry_delay_first(self):
        policy = RetryPolicy()
        assert policy.get_next_retry_delay(0) == 30

    def test_get_next_retry_delay_second(self):
        policy = RetryPolicy()
        assert policy.get_next_retry_delay(1) == 120

    def test_get_next_retry_delay_third(self):
        policy = RetryPolicy()
        assert policy.get_next_retry_delay(2) == 600

    def test_get_next_retry_delay_beyond(self):
        policy = RetryPolicy()
        assert policy.get_next_retry_delay(5) == 600


class TestGetNextRetryAt:
    def test_get_next_retry_at(self):
        policy = RetryPolicy()
        before = datetime.now()
        result = policy.get_next_retry_at(0)
        after = datetime.now() + timedelta(seconds=1)
        expected_earliest = before + timedelta(seconds=30)
        expected_latest = after + timedelta(seconds=30)
        assert expected_earliest <= result <= expected_latest

    def test_get_next_retry_at_second_attempt(self):
        policy = RetryPolicy()
        before = datetime.now()
        result = policy.get_next_retry_at(1)
        after = datetime.now() + timedelta(seconds=1)
        expected_earliest = before + timedelta(seconds=120)
        expected_latest = after + timedelta(seconds=120)
        assert expected_earliest <= result <= expected_latest
