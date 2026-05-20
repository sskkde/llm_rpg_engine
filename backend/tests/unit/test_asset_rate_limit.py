"""Unit tests for asset_rate_limit.py."""

import os
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from llm_rpg.services.asset_rate_limit import (
    AssetRateLimiter,
    RateLimitConfig,
    RateLimitResult,
)


class TestRateLimitConfig:
    def test_default_values(self):
        config = RateLimitConfig()
        assert config.user_per_minute == 10
        assert config.user_per_day == 200
        assert config.session_per_minute == 20
        assert config.provider_concurrency_limit == 3

    def test_from_env_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = RateLimitConfig.from_env()
            assert config.user_per_minute == 10
            assert config.session_per_minute == 20

    def test_from_env_custom_values(self):
        env = {
            "ASSET_RATE_LIMIT_USER_PER_MINUTE": "5",
            "ASSET_RATE_LIMIT_SESSION_PER_MINUTE": "10",
            "ASSET_PROVIDER_CONCURRENCY_LIMIT": "2",
        }
        with patch.dict(os.environ, env, clear=True):
            config = RateLimitConfig.from_env()
            assert config.user_per_minute == 5
            assert config.session_per_minute == 10
            assert config.provider_concurrency_limit == 2


class TestRateLimitResult:
    def test_allowed_result(self):
        result = RateLimitResult(allowed=True)
        assert result.allowed is True
        assert result.limit_type is None
        assert result.limit_value is None

    def test_denied_result(self):
        reset_at = datetime.now() + timedelta(minutes=1)
        result = RateLimitResult(
            allowed=False,
            limit_type="user_per_minute",
            limit_value=10,
            current_value=11,
            reset_at=reset_at,
        )
        assert result.allowed is False
        assert result.limit_type == "user_per_minute"
        assert result.limit_value == 10
        assert result.current_value == 11
        assert result.reset_at == reset_at


class TestAssetRateLimiter:
    def test_init_default_config(self):
        limiter = AssetRateLimiter()
        assert limiter._config.user_per_minute == 10
        assert limiter._config.session_per_minute == 20

    def test_init_custom_config(self):
        config = RateLimitConfig(user_per_minute=5, session_per_minute=10)
        limiter = AssetRateLimiter(config=config)
        assert limiter._config.user_per_minute == 5
        assert limiter._config.session_per_minute == 10

    def test_rate_limit_allows_within_limit(self):
        limiter = AssetRateLimiter()
        result = limiter.check_rate_limit(
            user_id="user1",
            session_id="session1",
            provider_name="mock",
        )
        assert result.allowed is True

    def test_rate_limit_blocks_user_per_minute_excess(self):
        config = RateLimitConfig(user_per_minute=3, session_per_minute=100)
        limiter = AssetRateLimiter(config=config)
        
        for i in range(3):
            result = limiter.check_rate_limit(
                user_id="user1",
                session_id="session1",
                provider_name="mock",
            )
            assert result.allowed is True, f"Request {i+1} should be allowed"
        
        result = limiter.check_rate_limit(
            user_id="user1",
            session_id="session1",
            provider_name="mock",
        )
        assert result.allowed is False
        assert result.limit_type == "user_per_minute"
        assert result.limit_value == 3

    def test_rate_limit_blocks_session_per_minute_excess(self):
        config = RateLimitConfig(user_per_minute=100, session_per_minute=2)
        limiter = AssetRateLimiter(config=config)
        
        for i in range(2):
            result = limiter.check_rate_limit(
                user_id="user1",
                session_id="session1",
                provider_name="mock",
            )
            assert result.allowed is True, f"Request {i+1} should be allowed"
        
        result = limiter.check_rate_limit(
            user_id="user1",
            session_id="session1",
            provider_name="mock",
        )
        assert result.allowed is False
        assert result.limit_type == "session_per_minute"
        assert result.limit_value == 2

    def test_rate_limit_blocks_provider_concurrency(self):
        config = RateLimitConfig(
            user_per_minute=100,
            session_per_minute=100,
            provider_concurrency_limit=2,
        )
        limiter = AssetRateLimiter(config=config)
        
        limiter.register_job("mock", "job1", "pending")
        limiter.register_job("mock", "job2", "processing")
        
        result = limiter.check_rate_limit(
            user_id="user1",
            session_id="session1",
            provider_name="mock",
        )
        assert result.allowed is False
        assert result.limit_type == "provider_concurrency"
        assert result.limit_value == 2

    def test_rate_limit_resets_after_window(self):
        config = RateLimitConfig(user_per_minute=2, session_per_minute=100)
        limiter = AssetRateLimiter(config=config)
        
        now = time.time()
        with patch.object(time, 'time', return_value=now):
            for i in range(2):
                result = limiter.check_rate_limit(
                    user_id="user1",
                    session_id="session1",
                    provider_name="mock",
                )
                assert result.allowed is True
        
        with patch.object(time, 'time', return_value=now + 61):
            limiter._cleanup_old_entries()
            limiter._last_cleanup = now + 61 - limiter._cleanup_interval - 1
            
            result = limiter.check_rate_limit(
                user_id="user1",
                session_id="session1",
                provider_name="mock",
            )
            assert result.allowed is True

    def test_different_users_independent_limits(self):
        config = RateLimitConfig(user_per_minute=2, session_per_minute=100)
        limiter = AssetRateLimiter(config=config)
        
        for i in range(2):
            result = limiter.check_rate_limit(
                user_id="user1",
                session_id="session1",
                provider_name="mock",
            )
            assert result.allowed is True
        
        result = limiter.check_rate_limit(
            user_id="user1",
            session_id="session1",
            provider_name="mock",
        )
        assert result.allowed is False
        
        result = limiter.check_rate_limit(
            user_id="user2",
            session_id="session2",
            provider_name="mock",
        )
        assert result.allowed is True

    def test_record_rate_limit_event_with_repo(self):
        mock_repo = MagicMock()
        mock_repo.create_event.return_value = MagicMock(event_id="evt-123")
        
        limiter = AssetRateLimiter(rate_limit_event_repo=mock_repo)
        reset_at = datetime.now() + timedelta(minutes=1)
        
        result = limiter.record_rate_limit_event(
            user_id="user1",
            session_id="session1",
            provider_name="mock",
            allowed=False,
            limit_type="user_per_minute",
            limit_value=10,
            current_value=11,
            reset_at=reset_at,
        )
        
        assert result is not None
        assert mock_repo.create_event.call_count == 2
        first_call_data = mock_repo.create_event.call_args_list[0][0][0]
        assert first_call_data["user_id"] == "user1"
        assert first_call_data["allowed"] is False
        assert first_call_data["limit_type"] == "user_per_minute"
        second_call_data = mock_repo.create_event.call_args_list[1][0][0]
        assert second_call_data["bucket_key"] == "session:session1"

    def test_record_rate_limit_event_without_repo(self):
        limiter = AssetRateLimiter(rate_limit_event_repo=None)
        result = limiter.record_rate_limit_event(
            user_id="user1",
            session_id="session1",
            provider_name="mock",
            allowed=True,
        )
        assert result is None

    def test_record_rate_limit_event_repo_failure(self):
        mock_repo = MagicMock()
        mock_repo.create_event.side_effect = Exception("DB error")
        
        limiter = AssetRateLimiter(rate_limit_event_repo=mock_repo)
        result = limiter.record_rate_limit_event(
            user_id="user1",
            session_id="session1",
            provider_name="mock",
            allowed=True,
        )
        assert result is None

    def test_register_and_unregister_job(self):
        limiter = AssetRateLimiter()
        
        limiter.register_job("mock", "job1", "pending")
        assert "job1" in limiter._provider_jobs["mock"]
        assert limiter._provider_jobs["mock"]["job1"] == "pending"
        
        limiter.unregister_job("mock", "job1")
        assert "job1" not in limiter._provider_jobs["mock"]

    def test_cleanup_old_entries(self):
        limiter = AssetRateLimiter()
        now = time.time()
        
        limiter._window_state["test_key"] = [now - 200, now - 150, now - 10]
        limiter._last_cleanup = now - limiter._cleanup_interval - 1
        
        with patch.object(time, 'time', return_value=now):
            limiter._cleanup_old_entries()
        
        assert len(limiter._window_state["test_key"]) == 1

    def test_count_in_window_with_repo(self):
        mock_repo = MagicMock()
        mock_repo.count_recent.return_value = 5
        
        limiter = AssetRateLimiter(rate_limit_event_repo=mock_repo)
        limiter._window_state["user:user1"] = [time.time()] * 3
        
        count = limiter._count_in_window("user:user1", 60)
        assert count == 5
        mock_repo.count_recent.assert_called_once()

    def test_count_in_window_repo_fallback(self):
        mock_repo = MagicMock()
        mock_repo.count_recent.side_effect = Exception("DB error")
        
        now = time.time()
        limiter = AssetRateLimiter(rate_limit_event_repo=mock_repo)
        limiter._window_state["user:user1"] = [now, now - 10, now - 20]
        
        count = limiter._count_in_window("user:user1", 60)
        assert count == 3

    def test_no_session_id_skips_session_check(self):
        config = RateLimitConfig(user_per_minute=100, session_per_minute=1)
        limiter = AssetRateLimiter(config=config)
        
        for i in range(5):
            result = limiter.check_rate_limit(
                user_id="user1",
                session_id=None,
                provider_name="mock",
            )
            assert result.allowed is True

    def test_check_rate_limit_resets_at_calculation(self):
        limiter = AssetRateLimiter()
        config = RateLimitConfig(user_per_minute=1)
        limiter._config = config
        
        limiter.check_rate_limit(
            user_id="user1",
            session_id="session1",
            provider_name="mock",
        )
        
        result = limiter.check_rate_limit(
            user_id="user1",
            session_id="session1",
            provider_name="mock",
        )
        
        assert result.allowed is False
        assert result.reset_at is not None
        
        now = datetime.now()
        expected_reset = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        delta = abs((result.reset_at - expected_reset).total_seconds())
        assert delta < 2
