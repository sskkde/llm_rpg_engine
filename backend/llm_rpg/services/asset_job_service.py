"""Asset job service — cache-first async job submission and lifecycle management.

Provides submit/get/list/cancel/retry operations for asset generation jobs.
Never propagates exceptions to callers — always returns AssetResponse or AssetJobResponse.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Union

from sqlalchemy.exc import IntegrityError

from llm_rpg.models.assets import (
    AssetGenerationRequest,
    AssetGenerationStatus,
    AssetJobResponse,
    AssetJobStatus,
    AssetResponse,
    AssetType,
)
from llm_rpg.core.assets.cache_key import build_asset_cache_key
from llm_rpg.storage.repositories import AssetJobRepository, AssetRepository, AssetUsageLogRepository
from llm_rpg.services.asset_usage_service import AssetUsageService

logger = logging.getLogger(__name__)

_RETRY_BACKOFF_BASE_SECONDS = 30  # exponential backoff base in seconds


class AssetJobService:
    """Service for managing async asset generation jobs with cache-first logic.

    Cache-first: checks AssetRepository for completed assets before creating
    a new pending job. Never raises exceptions to callers.

    Note: Rate limiting is handled at the API layer (media.py), not in this service.
    """

    def __init__(
        self,
        job_repository: AssetJobRepository,
        asset_repository: AssetRepository,
    ):
        self._job_repo = job_repository
        self._asset_repo = asset_repository

    @staticmethod
    def _map_job_to_response(job) -> AssetJobResponse:
        """Map an AssetGenerationJobModel to AssetJobResponse."""
        return AssetJobResponse(
            job_id=job.job_id,
            asset_id=job.asset_id,
            asset_type=job.asset_type,
            status=AssetJobStatus(job.status),
            provider_name=job.provider_name,
            attempt_count=job.attempt_count or 0,
            max_attempts=job.max_attempts or 3,
            error_message=job.error_message,
            last_error_type=job.last_error_type,
            cache_key=job.cache_key,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    @staticmethod
    def _map_asset_to_response(asset, *, cache_hit: bool = True) -> AssetResponse:
        """Map an AssetModel to AssetResponse."""
        return AssetResponse(
            asset_id=asset.asset_id,
            asset_type=AssetType(asset.asset_type),
            generation_status=AssetGenerationStatus(asset.status),
            result_url=asset.result_url,
            error_message=asset.error_message,
            provider=asset.provider_name,
            cache_hit=cache_hit,
            created_at=asset.created_at,
            metadata=asset.metadata_json or {},
        )

    async def submit(
        self, request: AssetGenerationRequest
    ) -> Union[AssetResponse, AssetJobResponse]:
        """Submit an asset generation job with cache-first logic.

        1. Compute cache key and check for completed asset.
        2. If cache hit, return AssetResponse immediately.
        3. If cache miss, create a pending job and return AssetJobResponse.
        4. Handle IntegrityError for concurrent cache_key creation.

        Never raises exceptions.
        """
        cache_key = build_asset_cache_key(request)

        cached = self._asset_repo.get_ready_by_cache_key(cache_key)
        if cached is not None:
            return self._map_asset_to_response(cached, cache_hit=True)

        job_id = str(uuid.uuid4())
        now = datetime.now()

        try:
            self._job_repo.create_job({
                "id": str(uuid.uuid4()),
                "job_id": job_id,
                "asset_type": request.asset_type.value,
                "session_id": request.session_id,
                "status": AssetJobStatus.PENDING.value,
                "provider_name": request.provider or "mock",
                "request_json": {
                    "prompt": request.prompt,
                    "style": request.style,
                    "asset_type": request.asset_type.value,
                    "world_id": request.world_id,
                    "owner_entity_id": request.owner_entity_id,
                    "owner_entity_type": request.owner_entity_type,
                    **(request.metadata or {}),
                },
                "cache_key": cache_key,
                "attempt_count": 0,
                "max_attempts": 3,
                "created_at": now,
                "updated_at": now,
            })
        except IntegrityError:
            cached = self._asset_repo.get_ready_by_cache_key(cache_key)
            if cached is not None:
                return self._map_asset_to_response(cached, cache_hit=True)
            existing_job = self._job_repo.get_by_job_id(job_id)
            if existing_job is not None:
                return self._map_job_to_response(existing_job)
            return AssetJobResponse(
                job_id=job_id,
                asset_id=None,
                asset_type=request.asset_type.value,
                status=AssetJobStatus.FAILED,
                provider_name=request.provider or "mock",
                attempt_count=0,
                max_attempts=3,
                error_message="Concurrent creation conflict",
                last_error_type="IntegrityError",
                cache_key=cache_key,
                created_at=now,
                updated_at=now,
            )
        except Exception as exc:
            logger.warning("Unexpected error creating job %s: %s", job_id, exc)
            return AssetJobResponse(
                job_id=job_id,
                asset_id=None,
                asset_type=request.asset_type.value,
                status=AssetJobStatus.FAILED,
                provider_name=request.provider or "mock",
                attempt_count=0,
                max_attempts=3,
                error_message=str(exc) or "Unexpected error",
                last_error_type=type(exc).__name__,
                cache_key=cache_key,
                created_at=now,
                updated_at=now,
            )

        job = self._job_repo.get_by_job_id(job_id)
        if job is not None:
            # Record estimated usage for the new job (non-blocking)
            try:
                db = self._job_repo.db
                usage_service = AssetUsageService(
                    usage_log_repository=AssetUsageLogRepository(db),
                    asset_job_repository=AssetJobRepository(db),
                    asset_repository=AssetRepository(db),
                )
                provider_name = request.provider or "mock"
                usage_service.record_usage(
                    job_id=job_id,
                    provider_name=provider_name,
                    operation="generate",
                    estimated_cost=0.01,  # Default estimated cost per job
                )
            except Exception as usage_exc:
                logger.warning("Failed to record usage for job %s: %s", job_id, usage_exc)
            return self._map_job_to_response(job)

        return AssetJobResponse(
            job_id=job_id,
            asset_id=None,
            asset_type=request.asset_type.value,
            status=AssetJobStatus.PENDING,
            provider_name=request.provider or "mock",
            attempt_count=0,
            max_attempts=3,
            error_message=None,
            last_error_type=None,
            cache_key=cache_key,
            created_at=now,
            updated_at=now,
        )

    def get_job(self, job_id: str) -> Optional[AssetJobResponse]:
        """Get a job by its public job_id.

        Returns AssetJobResponse if found, None otherwise.
        """
        job = self._job_repo.get_by_job_id(job_id)
        if job is None:
            return None
        return self._map_job_to_response(job)

    def list_session_jobs(
        self,
        session_id: str,
        asset_type: Optional[str] = None,
    ) -> List[AssetJobResponse]:
        """List jobs for a session, ordered by created_at desc.

        Args:
            session_id: Session ID to filter by.
            asset_type: Optional asset type filter.

        Returns:
            List of AssetJobResponse objects.
        """
        jobs = self._job_repo.list_by_session(session_id, asset_type=asset_type)
        return [self._map_job_to_response(j) for j in jobs]

    def cancel_job(self, job_id: str) -> Optional[AssetJobResponse]:
        """Cancel a pending job.

        Only cancels if the job status is 'pending'.
        Returns AssetJobResponse if cancelled, None if job not found or not pending.
        """
        job = self._job_repo.get_by_job_id(job_id)
        if job is None:
            return None
        if job.status != AssetJobStatus.PENDING.value:
            return None
        cancelled = self._job_repo.cancel_job(job_id)
        if cancelled is None:
            return None
        return self._map_job_to_response(cancelled)

    def retry_job(self, job_id: str) -> Optional[AssetJobResponse]:
        """Retry a failed job.

        Only retries if the job status is 'failed'.
        Resets status to 'pending', clears error_message, and schedules
        a retry with exponential backoff based on attempt_count.

        Returns AssetJobResponse if retried, None if job not found or not failed.
        """
        job = self._job_repo.get_by_job_id(job_id)
        if job is None:
            return None
        if job.status != AssetJobStatus.FAILED.value:
            return None

        attempt = job.attempt_count or 0
        backoff_seconds = _RETRY_BACKOFF_BASE_SECONDS * (2 ** attempt)
        next_retry_at = datetime.now() + timedelta(seconds=backoff_seconds)

        self._job_repo.update_status(
            job_id,
            status=AssetJobStatus.PENDING.value,
            error_message=None,
            last_error_type=None,
        )
        retried = self._job_repo.schedule_retry(job_id, next_retry_at)
        if retried is None:
            return None
        return self._map_job_to_response(retried)
