"""Asset queue backend abstraction for job processing.

Provides a Protocol for queue operations and implementations:
- InProcessAssetQueueBackend: Direct repository calls (for dev/testing)
- RQAssetQueueBackend: Shell for Redis Queue (NotImplementedError)
- CeleryAssetQueueBackend: Shell for Celery (NotImplementedError)
"""

import os
from datetime import datetime
from typing import Any, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from llm_rpg.storage.models import AssetGenerationJobModel


class AssetQueueBackend(Protocol):
    """Protocol defining the asset queue backend interface.
    
    Implementations must support:
    - enqueue: Add a job to the queue
    - dequeue: Claim the next pending job
    - ack: Mark a job as completed
    - nack: Mark a job as failed or schedule retry
    - size: Total job count
    - pending_count: Pending job count
    """
    
    def enqueue(self, job_id: str, priority: int = 100) -> bool:
        """Add a job to the queue.
        
        Args:
            job_id: The job ID to enqueue.
            priority: Job priority (lower = higher priority).
            
        Returns:
            True if enqueued successfully.
        """
        ...
    
    def dequeue(self, provider_name: Optional[str] = None) -> Optional["AssetGenerationJobModel"]:
        """Claim the next pending job.
        
        Args:
            provider_name: Optional filter for provider-specific jobs.
            
        Returns:
            The claimed job, or None if no pending jobs.
        """
        ...
    
    def ack(self, job_id: str) -> bool:
        """Acknowledge successful job completion.
        
        Args:
            job_id: The job ID to acknowledge.
            
        Returns:
            True if acknowledged successfully.
        """
        ...
    
    def nack(
        self, 
        job_id: str, 
        retry_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
        error_type: Optional[str] = None,
    ) -> bool:
        """Negative acknowledgement - mark job as failed or schedule retry.
        
        Args:
            job_id: The job ID to nack.
            retry_at: If provided, schedule retry at this time.
            error_message: Error message for failure.
            error_type: Error type classification.
            
        Returns:
            True if nacked successfully.
        """
        ...
    
    def size(self) -> int:
        """Return total number of jobs in the queue."""
        ...
    
    def pending_count(self) -> int:
        """Return number of pending jobs in the queue."""
        ...


class InProcessAssetQueueBackend:
    """In-process queue backend that wraps AssetJobRepository.
    
    This implementation directly calls the repository methods without
    any external queue system. Suitable for development, testing, and
    single-process deployments.
    """
    
    def __init__(
        self, 
        job_repository: Any,
        provider_name: Optional[str] = None,
    ):
        """Initialize the in-process queue backend.
        
        Args:
            job_repository: AssetJobRepository instance.
            provider_name: Optional default provider filter for dequeue.
        """
        self._repo = job_repository
        self._default_provider = provider_name
    
    def enqueue(self, job_id: str, priority: int = 100) -> bool:
        """Add a job to the queue by updating its status to pending.
        
        The job should already exist in the database. This method
        ensures it's in a pending state ready to be claimed.
        
        Args:
            job_id: The job ID to enqueue.
            priority: Job priority (lower = higher priority).
            
        Returns:
            True if enqueued successfully, False if job not found.
        """
        from llm_rpg.storage.models import AssetGenerationJobModel
        
        job = self._repo.get_by_job_id(job_id)
        if job is None:
            return False
        
        if job.priority != priority:
            job.priority = priority
            job.updated_at = datetime.now()
            self._repo.db.commit()
        
        if job.status != "pending":
            job.status = "pending"
            job.updated_at = datetime.now()
            self._repo.db.commit()
        
        return True
    
    def dequeue(
        self, 
        provider_name: Optional[str] = None
    ) -> Optional["AssetGenerationJobModel"]:
        """Claim the next pending job using the repository.
        
        Args:
            provider_name: Optional filter for provider-specific jobs.
                           Falls back to default provider if not specified.
            
        Returns:
            The claimed job, or None if no pending jobs.
        """
        provider = provider_name or self._default_provider
        return self._repo.claim_next_pending(provider)
    
    def ack(self, job_id: str) -> bool:
        """Mark job as completed.
        
        Args:
            job_id: The job ID to acknowledge.
            
        Returns:
            True if acknowledged successfully, False if job not found.
        """
        job = self._repo.get_by_job_id(job_id)
        if job is None:
            return False
        
        self._repo.update_status(job_id, "completed", completed_at=datetime.now())
        return True
    
    def nack(
        self, 
        job_id: str, 
        retry_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
        error_type: Optional[str] = None,
    ) -> bool:
        """Mark job as failed or schedule retry.
        
        Args:
            job_id: The job ID to nack.
            retry_at: If provided, schedule retry at this time.
            error_message: Error message for failure.
            error_type: Error type classification.
            
        Returns:
            True if nacked successfully, False if job not found.
        """
        job = self._repo.get_by_job_id(job_id)
        if job is None:
            return False
        
        if retry_at:
            self._repo.schedule_retry(job_id, retry_at)
        else:
            self._repo.mark_failed(
                job_id, 
                error_message or "Unknown error",
                error_type=error_type,
            )
        return True
    
    def size(self) -> int:
        """Return total number of jobs."""
        return self._repo.count_all()
    
    def pending_count(self) -> int:
        """Return number of pending jobs."""
        from llm_rpg.storage.models import AssetGenerationJobModel
        
        return self._repo.db.query(AssetGenerationJobModel).filter(
            AssetGenerationJobModel.status == "pending"
        ).count()


class RQAssetQueueBackend:
    """Redis Queue (RQ) backend - NOT YET IMPLEMENTED.
    
    This is a shell that raises NotImplementedError for all operations.
    Full implementation deferred to future phase.
    """
    
    def __init__(self, *args: Any, **kwargs: Any):
        """Initialize RQ backend - raises NotImplementedError."""
        raise NotImplementedError(
            "RQAssetQueueBackend is not implemented. "
            "Use 'in_process' backend or wait for future implementation."
        )
    
    def enqueue(self, job_id: str, priority: int = 100) -> bool:
        raise NotImplementedError("RQAssetQueueBackend.enqueue not implemented")
    
    def dequeue(self, provider_name: Optional[str] = None) -> Optional["AssetGenerationJobModel"]:
        raise NotImplementedError("RQAssetQueueBackend.dequeue not implemented")
    
    def ack(self, job_id: str) -> bool:
        raise NotImplementedError("RQAssetQueueBackend.ack not implemented")
    
    def nack(
        self, 
        job_id: str, 
        retry_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
        error_type: Optional[str] = None,
    ) -> bool:
        raise NotImplementedError("RQAssetQueueBackend.nack not implemented")
    
    def size(self) -> int:
        raise NotImplementedError("RQAssetQueueBackend.size not implemented")
    
    def pending_count(self) -> int:
        raise NotImplementedError("RQAssetQueueBackend.pending_count not implemented")


class CeleryAssetQueueBackend:
    """Celery backend - NOT YET IMPLEMENTED.
    
    This is a shell that raises NotImplementedError for all operations.
    Full implementation deferred to future phase.
    """
    
    def __init__(self, *args: Any, **kwargs: Any):
        """Initialize Celery backend - raises NotImplementedError."""
        raise NotImplementedError(
            "CeleryAssetQueueBackend is not implemented. "
            "Use 'in_process' backend or wait for future implementation."
        )
    
    def enqueue(self, job_id: str, priority: int = 100) -> bool:
        raise NotImplementedError("CeleryAssetQueueBackend.enqueue not implemented")
    
    def dequeue(self, provider_name: Optional[str] = None) -> Optional["AssetGenerationJobModel"]:
        raise NotImplementedError("CeleryAssetQueueBackend.dequeue not implemented")
    
    def ack(self, job_id: str) -> bool:
        raise NotImplementedError("CeleryAssetQueueBackend.ack not implemented")
    
    def nack(
        self, 
        job_id: str, 
        retry_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
        error_type: Optional[str] = None,
    ) -> bool:
        raise NotImplementedError("CeleryAssetQueueBackend.nack not implemented")
    
    def size(self) -> int:
        raise NotImplementedError("CeleryAssetQueueBackend.size not implemented")
    
    def pending_count(self) -> int:
        raise NotImplementedError("CeleryAssetQueueBackend.pending_count not implemented")


_BACKENDS = {
    "in_process": InProcessAssetQueueBackend,
    "rq": RQAssetQueueBackend,
    "celery": CeleryAssetQueueBackend,
}


def get_queue_backend(
    name: Optional[str] = None,
    job_repository: Optional[Any] = None,
    **kwargs: Any,
) -> AssetQueueBackend:
    """Get a queue backend by name.
    
    Args:
        name: Backend name. If None, reads ASSET_QUEUE_BACKEND env var.
              Defaults to "in_process" if env var is not set.
        job_repository: AssetJobRepository instance (required for in_process).
        **kwargs: Additional arguments passed to backend constructor.
        
    Returns:
        An instance of AssetQueueBackend.
        
    Raises:
        ValueError: If the backend name is unknown.
        NotImplementedError: If the backend is a shell (rq, celery).
    """
    if name is None:
        name = os.getenv("ASSET_QUEUE_BACKEND", "in_process")
    
    backend_class = _BACKENDS.get(name)
    if backend_class is None:
        raise ValueError(
            f"Unknown queue backend: '{name}'. "
            f"Available backends: {', '.join(sorted(_BACKENDS.keys()))}"
        )
    
    if name == "in_process":
        if job_repository is None:
            raise ValueError(
                "job_repository is required for InProcessAssetQueueBackend"
            )
        return backend_class(job_repository, **kwargs)
    
    return backend_class(**kwargs)
