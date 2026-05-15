"""In-process job runner for asset generation jobs.

Claims pending jobs and processes them through the configured provider.
No Celery/RQ — runs in the current process synchronously.
"""

import logging
from typing import List, Optional

from llm_rpg.assets.interfaces import (
    AssetGenerationRequest,
    AssetGenerationResult,
    AssetStatus,
    AssetType,
)
from llm_rpg.assets.provider_factory import get_asset_provider
from llm_rpg.assets.retry_policy import RetryPolicy
from llm_rpg.models.assets import AssetJobResponse, AssetJobStatus
from llm_rpg.storage.repositories import AssetJobRepository

logger = logging.getLogger(__name__)


class AssetJobRunner:
    """In-process job runner for asset generation jobs."""

    def __init__(
        self,
        job_repository: AssetJobRepository,
        retry_policy: RetryPolicy,
    ):
        self._job_repo = job_repository
        self._retry_policy = retry_policy

    async def run_next_job(
        self, provider_name: Optional[str] = None
    ) -> Optional[AssetJobResponse]:
        """Claim and process the next pending job.

        Args:
            provider_name: Optional filter to only claim jobs for this provider.

        Returns:
            AssetJobResponse for the processed job, or None if no pending jobs.
        """
        job = self._job_repo.claim_next_pending(provider_name)
        if job is None:
            return None

        try:
            provider = get_asset_provider(job.provider_name)
            request = self._build_generation_request(job)
            result: AssetGenerationResult = await provider.generate(request)

            if result.status == AssetStatus.COMPLETED:
                self._job_repo.mark_completed(job.job_id, result.asset_id or "")
            else:
                error_msg = result.error_message or f"Provider returned status: {result.status.value}"
                error_type = result.metadata.get("error_type") if result.metadata else None
                status_code = result.metadata.get("status_code") if result.metadata else None

                if self._retry_policy.should_retry(
                    attempt_count=job.attempt_count,
                    error_type=error_type,
                    status_code=status_code,
                ):
                    next_retry_at = self._retry_policy.get_next_retry_at(job.attempt_count)
                    self._job_repo.schedule_retry(job.job_id, next_retry_at)
                else:
                    self._job_repo.mark_failed(job.job_id, error_msg, error_type=error_type)

        except Exception as exc:
            error_msg = str(exc) or "Unknown provider error"
            error_type = type(exc).__name__
            logger.warning(f"Asset job {job.job_id} failed with exception: {error_msg}")

            if self._retry_policy.should_retry(
                attempt_count=job.attempt_count,
                error_type=error_type,
            ):
                next_retry_at = self._retry_policy.get_next_retry_at(job.attempt_count)
                self._job_repo.schedule_retry(job.job_id, next_retry_at)
            else:
                self._job_repo.mark_failed(job.job_id, error_msg, error_type=error_type)

        updated_job = self._job_repo.get_by_job_id(job.job_id)
        if updated_job is None:
            return None
        return self._map_job_to_response(updated_job)

    async def run_pending_batch(
        self, batch_size: int = 5, provider_name: Optional[str] = None
    ) -> List[AssetJobResponse]:
        """Run up to batch_size jobs in sequence.

        Args:
            batch_size: Maximum number of jobs to process.
            provider_name: Optional provider filter.

        Returns:
            List of AssetJobResponse for processed jobs.
        """
        results: List[AssetJobResponse] = []
        for _ in range(batch_size):
            result = await self.run_next_job(provider_name)
            if result is None:
                break
            results.append(result)
        return results

    def _build_generation_request(self, job) -> AssetGenerationRequest:
        """Reconstruct AssetGenerationRequest from job's request_json."""
        request_json = job.request_json or {}
        return AssetGenerationRequest(
            asset_type=AssetType(request_json.get("asset_type", job.asset_type)),
            request_id=job.job_id,
            session_id=job.session_id,
            game_context=request_json.get("game_context", {}),
            metadata=request_json.get("metadata", {}),
        )

    @staticmethod
    def _map_job_to_response(job) -> AssetJobResponse:
        """Map an AssetGenerationJobModel to AssetJobResponse."""
        return AssetJobResponse(
            job_id=job.job_id,
            asset_id=job.asset_id,
            asset_type=job.asset_type,
            status=AssetJobStatus(job.status),
            provider_name=job.provider_name,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            error_message=job.error_message,
            last_error_type=job.last_error_type,
            cache_key=job.cache_key,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
