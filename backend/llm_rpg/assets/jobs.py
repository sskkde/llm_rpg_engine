"""In-process job runner for asset generation jobs.

Claims pending jobs and processes them through the configured provider.
No Celery/RQ — runs in the current process synchronously.
"""

import asyncio
import logging
import os
import socket
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from llm_rpg.assets.interfaces import (
    AssetGenerationRequest,
    AssetGenerationResult,
    AssetStatus,
    AssetType,
)
from llm_rpg.assets.provider_factory import get_asset_provider
from llm_rpg.assets.retry_policy import RetryPolicy
from llm_rpg.models.assets import AssetJobResponse, AssetJobStatus
from llm_rpg.storage.repositories import AssetJobRepository, AssetRepository

if TYPE_CHECKING:
    from llm_rpg.services.asset_usage_service import AssetUsageService

logger = logging.getLogger(__name__)


class AssetJobRunner:
    """In-process job runner for asset generation jobs."""

    def __init__(
        self,
        job_repository: AssetJobRepository,
        asset_repository: AssetRepository,
        retry_policy: RetryPolicy,
        usage_service: Optional["AssetUsageService"] = None,
        worker_id: Optional[str] = None,
        lease_seconds: int = 300,
        heartbeat_interval: float = 30.0,
    ):
        self._job_repo = job_repository
        self._asset_repo = asset_repository
        self._retry_policy = retry_policy
        self._usage_service = usage_service
        self.worker_id = worker_id or f"worker-{socket.gethostname()}-{os.getpid()}"
        self.lease_seconds = lease_seconds
        self.heartbeat_interval = heartbeat_interval

    async def run_next_job(
        self, provider_name: Optional[str] = None
    ) -> Optional[AssetJobResponse]:
        """Claim and process the next pending job.

        Args:
            provider_name: Optional filter to only claim jobs for this provider.

        Returns:
            AssetJobResponse for the processed job, or None if no pending jobs.
        """
        self._job_repo.recover_stale_jobs(datetime.now())

        job = self._job_repo.claim_next_pending_with_lease(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            provider_name=provider_name,
        )
        if job is None:
            return None

        try:
            provider = get_asset_provider(job.provider_name)
            request = self._build_generation_request(job)

            heartbeat_task = asyncio.ensure_future(
                self._heartbeat_loop(job.job_id, self.worker_id, self.lease_seconds)
            )
            try:
                result: AssetGenerationResult = await provider.generate(request)
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            self._job_repo.heartbeat(job.job_id, self.worker_id, self.lease_seconds)

            if result.status == AssetStatus.COMPLETED:
                asset_id = result.asset_id or job.job_id
                asset = self._asset_repo.get_by_asset_id(asset_id)
                if asset is None:
                    from llm_rpg.storage.models import AssetModel
                    asset = AssetModel(
                        asset_id=asset_id,
                        asset_type=job.asset_type,
                        status="completed",
                        session_id=job.session_id,
                        provider_name=job.provider_name,
                        cache_key=job.cache_key,
                        result_url=result.asset_url,
                        request_params=job.request_json or {},
                        metadata_json=result.metadata or {},
                    )
                    self._asset_repo.db.add(asset)
                    self._asset_repo.db.commit()
                    self._asset_repo.db.refresh(asset)
                else:
                    self._asset_repo.update_status(
                        asset_id=asset_id,
                        status="completed",
                        result_url=result.asset_url,
                    )
                self._job_repo.mark_completed(job.job_id, asset_id)
                self._record_usage(
                    job=job,
                    operation="generate",
                    status="completed",
                    actual_cost=result.metadata.get("cost_usd") if result.metadata else None,
                )
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
                    self._dead_letter_or_fail(job, error_msg, error_type)

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
                self._dead_letter_or_fail(job, error_msg, error_type)

        updated_job = self._job_repo.get_by_job_id(job.job_id)
        if updated_job is None:
            return None
        return self._map_job_to_response(updated_job)

    def _dead_letter_or_fail(self, job, error_msg: str, error_type: Optional[str] = None):
        if job.attempt_count >= job.max_attempts:
            reason = f"Max retries exceeded ({job.attempt_count}/{job.max_attempts}): {error_type or 'unknown'}"
            self._job_repo.mark_dead_letter(job.job_id, reason)
        else:
            self._job_repo.mark_failed(job.job_id, error_msg, error_type=error_type)
        self._record_usage(
            job=job,
            operation="generate",
            status="failed",
            metadata={"error_message": error_msg, "error_type": error_type},
        )

    async def _heartbeat_loop(self, job_id: str, worker_id: str, lease_seconds: int):
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            self._job_repo.heartbeat(job_id, worker_id, lease_seconds)

    def _record_usage(
        self,
        job,
        operation: str,
        status: str,
        actual_cost: Optional[float] = None,
        metadata: Optional[dict] = None,
    ):
        if self._usage_service is None:
            return
        try:
            self._usage_service.record_usage(
                job_id=job.job_id,
                provider_name=job.provider_name,
                operation=operation,
                estimated_cost=job.estimated_cost_usd,
                actual_cost=actual_cost,
                session_id=job.session_id,
                asset_id=job.asset_id,
                asset_type=job.asset_type,
                status=status,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning("Failed to record usage for job %s: %s", job.job_id, exc)

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
