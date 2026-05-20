"""Asset rate limiting service with in-memory sliding window + DB event recording.

Provides rate limit checks for asset generation endpoints with:
- User-per-day limit
- User-per-minute limit
- Session-per-minute limit  
- Provider concurrency limit
- DB persistence for audit/debug
"""

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from llm_rpg.storage.repositories import AssetRateLimitEventRepository


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    user_per_minute: int = 10
    user_per_day: int = 200
    session_per_minute: int = 20
    provider_concurrency_limit: int = 3

    @classmethod
    def from_env(cls) -> "RateLimitConfig":
        """Load configuration from environment variables with defaults."""
        return cls(
            user_per_minute=int(os.getenv("ASSET_RATE_LIMIT_USER_PER_MINUTE", "10")),
            user_per_day=int(os.getenv("ASSET_RATE_LIMIT_USER_PER_DAY", "200")),
            session_per_minute=int(os.getenv("ASSET_RATE_LIMIT_SESSION_PER_MINUTE", "20")),
            provider_concurrency_limit=int(os.getenv("ASSET_PROVIDER_CONCURRENCY_LIMIT", "3")),
        )


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    allowed: bool
    limit_type: Optional[str] = None
    limit_value: Optional[int] = None
    current_value: Optional[int] = None
    reset_at: Optional[datetime] = None


class AssetRateLimiter:
    """Rate limiter with in-memory sliding window + DB event recording.
    
    Uses in-memory dict for sliding window state and DB for event recording.
    Single-process design (no threading locks for P8).
    """

    def __init__(
        self,
        rate_limit_event_repo: Optional[AssetRateLimitEventRepository] = None,
        config: Optional[RateLimitConfig] = None,
    ):
        self._repo = rate_limit_event_repo
        self._config = config or RateLimitConfig.from_env()
        
        # In-memory sliding window state: {bucket_key: [timestamps]}
        self._window_state: Dict[str, List[float]] = {}
        
        # Provider job tracking for concurrency: {provider_name: {job_id: status}}
        self._provider_jobs: Dict[str, Dict[str, str]] = {}
        
        # Cleanup interval (seconds)
        self._cleanup_interval = 60
        self._last_cleanup = time.time()

    def _get_minute_window_start(self, now: Optional[datetime] = None) -> datetime:
        """Get the start of the current minute window."""
        now = now or datetime.now()
        return now.replace(second=0, microsecond=0)

    def _get_minute_window_end(self, now: Optional[datetime] = None) -> datetime:
        """Get the end of the current minute window (start of next minute)."""
        start = self._get_minute_window_start(now)
        return start + timedelta(minutes=1)

    def _cleanup_old_entries(self) -> None:
        """Clean up old entries from in-memory state."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        
        # Keep entries up to 24h + buffer (86500s) for day-window buckets
        cutoff = now - 86500
        for key in list(self._window_state.keys()):
            self._window_state[key] = [
                ts for ts in self._window_state[key] if ts > cutoff
            ]
            if not self._window_state[key]:
                del self._window_state[key]
        
        # Clean up completed/failed jobs from provider tracking
        for provider in list(self._provider_jobs.keys()):
            self._provider_jobs[provider] = {
                job_id: status
                for job_id, status in self._provider_jobs[provider].items()
                if status in ("pending", "processing")
            }
            if not self._provider_jobs[provider]:
                del self._provider_jobs[provider]
        
        self._last_cleanup = now

    def _count_in_window(self, bucket_key: str, window_seconds: int = 60) -> int:
        """Count entries in the sliding window for a bucket key."""
        now = time.time()
        cutoff = now - window_seconds
        
        # Get timestamps from in-memory state
        timestamps = self._window_state.get(bucket_key, [])
        count = len([ts for ts in timestamps if ts > cutoff])
        
        # Also count from DB if repo is available
        if self._repo is not None:
            try:
                since = datetime.now() - timedelta(seconds=window_seconds)
                db_count = self._repo.count_recent(bucket_key, since)
                # Use DB count as authoritative (in-memory is just for optimization)
                return db_count
            except Exception:
                # Fall back to in-memory count if DB fails
                pass
        
        return count

    def check_rate_limit(
        self,
        user_id: str,
        session_id: Optional[str],
        provider_name: str,
    ) -> RateLimitResult:
        """Check rate limits for an asset generation request.
        
        Checks in order:
        1. User-per-day limit
        2. User-per-minute limit
        3. Session-per-minute limit
        4. Provider concurrency limit
        
        Returns RateLimitResult with allowed=True if all checks pass.
        Returns RateLimitResult with allowed=False and limit details if any check fails.
        """
        self._cleanup_old_entries()
        now = datetime.now()
        now_ts = time.time()
        reset_at = self._get_minute_window_end(now)
        
        # Check user-per-day
        day_bucket = f"user_day:{user_id}"
        day_count = self._count_in_window(day_bucket, 86400)
        if day_count >= self._config.user_per_day:
            return RateLimitResult(
                allowed=False,
                limit_type="user_per_day",
                limit_value=self._config.user_per_day,
                current_value=day_count,
                reset_at=now + timedelta(days=1),
            )
        
        # Check user-per-minute
        user_bucket = f"user:{user_id}"
        user_count = self._count_in_window(user_bucket, 60)
        if user_count >= self._config.user_per_minute:
            return RateLimitResult(
                allowed=False,
                limit_type="user_per_minute",
                limit_value=self._config.user_per_minute,
                current_value=user_count,
                reset_at=reset_at,
            )
        
        # Check session-per-minute (if session_id provided)
        if session_id:
            session_bucket = f"session:{session_id}"
            session_count = self._count_in_window(session_bucket, 60)
            if session_count >= self._config.session_per_minute:
                return RateLimitResult(
                    allowed=False,
                    limit_type="session_per_minute",
                    limit_value=self._config.session_per_minute,
                    current_value=session_count,
                    reset_at=reset_at,
                )
        
        # Check provider concurrency
        provider_jobs = self._provider_jobs.get(provider_name, {})
        processing_count = len([
            s for s in provider_jobs.values()
            if s in ("pending", "processing")
        ])
        if processing_count >= self._config.provider_concurrency_limit:
            return RateLimitResult(
                allowed=False,
                limit_type="provider_concurrency",
                limit_value=self._config.provider_concurrency_limit,
                current_value=processing_count,
                reset_at=now + timedelta(seconds=60),  # Approximate
            )
        
        # All checks passed - record in memory for sliding window
        self._window_state.setdefault(day_bucket, []).append(now_ts)
        self._window_state.setdefault(user_bucket, []).append(now_ts)
        if session_id:
            self._window_state.setdefault(f"session:{session_id}", []).append(now_ts)
        
        return RateLimitResult(
            allowed=True,
            limit_type=None,
            limit_value=None,
            current_value=None,
            reset_at=None,
        )

    def record_rate_limit_event(
        self,
        user_id: str,
        session_id: Optional[str],
        provider_name: str,
        allowed: bool,
        limit_type: Optional[str] = None,
        limit_value: Optional[int] = None,
        current_value: Optional[int] = None,
        reset_at: Optional[datetime] = None,
    ) -> Optional[Any]:
        """Record a rate limit event to DB for audit/debug.
        
        Returns the created event model if repo is available, None otherwise.
        """
        if self._repo is None:
            return None
        
        now = datetime.now()
        
        events_to_create = []
        
        day_bucket = f"user_day:{user_id}"
        events_to_create.append({
            "bucket_key": day_bucket,
            "limit_type": "user_per_day" if limit_type == "user_per_day" else None,
        })
        
        user_bucket = f"user:{user_id}"
        events_to_create.append({
            "bucket_key": user_bucket,
            "limit_type": "user_per_minute" if limit_type == "user_per_minute" else None,
        })
        
        if session_id:
            session_bucket = f"session:{session_id}"
            events_to_create.append({
                "bucket_key": session_bucket,
                "limit_type": "session_per_minute" if limit_type == "session_per_minute" else None,
            })
        
        created_events = []
        for event_info in events_to_create:
            event_data = {
                "id": str(uuid.uuid4()),
                "event_id": str(uuid.uuid4()),
                "user_id": user_id,
                "session_id": session_id,
                "provider_name": provider_name,
                "bucket_key": event_info["bucket_key"],
                "limit_type": event_info.get("limit_type") or limit_type,
                "allowed": allowed,
                "limit_value": limit_value,
                "current_value": current_value,
                "reset_at": reset_at,
                "created_at": now,
            }
            try:
                created = self._repo.create_event(event_data)
                if created:
                    created_events.append(created)
            except Exception:
                pass
        
        return created_events[0] if created_events else None

    def register_job(self, provider_name: str, job_id: str, status: str) -> None:
        """Register a job for provider concurrency tracking."""
        if provider_name not in self._provider_jobs:
            self._provider_jobs[provider_name] = {}
        self._provider_jobs[provider_name][job_id] = status

    def unregister_job(self, provider_name: str, job_id: str) -> None:
        """Unregister a job from provider concurrency tracking."""
        if provider_name in self._provider_jobs:
            self._provider_jobs[provider_name].pop(job_id, None)
