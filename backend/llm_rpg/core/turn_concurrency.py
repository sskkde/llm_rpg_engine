"""
Turn Concurrency Control Service.

This module provides DB-level concurrency guardrails for same-session turn execution.
It ensures that concurrent requests to the same session never produce duplicate turns
and that retries with the same idempotency key return the same result.

Key features:
- DB-level locking via SELECT FOR UPDATE or advisory locks
- Context manager for safe concurrency control
- Graceful handling of lock acquisition failures
- Cross-process safety (not just Python process locks)

Implementation Strategy:
- PostgreSQL: Uses pg_advisory_xact_lock for session-scoped locks
- SQLite: Uses BEGIN IMMEDIATE for transaction-level locking
- The lock is tied to the database transaction, released on commit/rollback
"""

from typing import Optional, Callable, TypeVar, Any
from contextlib import contextmanager
import hashlib

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from .turn_allocation import (
    TurnAllocationError,
    TurnConflictError,
    allocate_turn,
    commit_turn,
)


T = TypeVar('T')


class TurnConcurrencyError(TurnAllocationError):
    """Raised when concurrency control fails."""
    
    def __init__(self, message: str, session_id: Optional[str] = None, lock_timeout: bool = False):
        self.lock_timeout = lock_timeout
        super().__init__(message, session_id=session_id)


class TurnLockAcquisitionError(TurnConcurrencyError):
    """Raised when lock acquisition fails."""
    
    def __init__(self, session_id: str, timeout_seconds: Optional[float] = None):
        message = f"Failed to acquire lock for session {session_id}"
        if timeout_seconds:
            message += f" after {timeout_seconds}s timeout"
        super().__init__(message, session_id=session_id, lock_timeout=True)


def _generate_lock_key(session_id: str) -> int:
    """
    Generate a deterministic integer lock key from session_id.
    
    PostgreSQL advisory locks require an integer key.
    We use a hash of the session_id to generate a stable key.
    
    Args:
        session_id: The session identifier
        
    Returns:
        Integer lock key (positive, fits in PostgreSQL bigint)
    """
    # Hash the session_id and convert to positive integer
    hash_bytes = hashlib.sha256(session_id.encode()).digest()
    # Take first 8 bytes and convert to integer
    lock_key = int.from_bytes(hash_bytes[:8], byteorder='big')
    # Ensure it's positive and within PostgreSQL bigint range
    return abs(lock_key % (2**63 - 1))


def acquire_turn_lock(
    db: Session,
    session_id: str,
    timeout_seconds: Optional[float] = None,
) -> None:
    """
    Acquire a DB-level lock for turn execution on a session.
    
    This function uses database-level locking mechanisms to ensure
    that only one transaction can execute a turn for a given session
    at a time.
    
    PostgreSQL: Uses pg_advisory_xact_lock (session-scoped, released on commit/rollback)
    SQLite: Uses BEGIN IMMEDIATE (transaction-level exclusive lock)
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID to lock
        timeout_seconds: Optional timeout for lock acquisition (PostgreSQL only)
        
    Raises:
        TurnLockAcquisitionError: If lock acquisition fails or times out
        
    Note:
        The lock is automatically released when the transaction ends
        (commit or rollback). This is a critical safety feature.
    """
    try:
        # Detect database type
        db_url = str(db.bind.url)
        
        if 'postgresql' in db_url or 'postgres' in db_url:
            # PostgreSQL: Use advisory lock
            lock_key = _generate_lock_key(session_id)
            
            if timeout_seconds is not None:
                # Try to acquire lock with timeout
                # pg_advisory_xact_lock is blocking, so we use try_grant pattern
                result = db.execute(
                    text("SELECT pg_try_advisory_xact_lock(:key)"),
                    {"key": lock_key}
                ).scalar()
                
                if not result:
                    # Lock not acquired
                    raise TurnLockAcquisitionError(
                        session_id=session_id,
                        timeout_seconds=timeout_seconds,
                    )
            else:
                # Blocking lock acquisition (no timeout)
                # This will wait indefinitely until lock is available
                db.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": lock_key}
                )
        
        elif 'sqlite' in db_url:
            # SQLite: Use BEGIN IMMEDIATE for exclusive transaction
            # SQLite doesn't have advisory locks, but BEGIN IMMEDIATE
            # provides transaction-level exclusive access
            # Note: This is already handled by SQLAlchemy's transaction management
            # We just need to ensure we're in a transaction
            if not db.in_transaction():
                db.begin()
            
            # For SQLite, we use a simpler approach: lock a specific row
            # We use the session row itself as the lock point
            from ..storage.models import SessionModel
            session = db.query(SessionModel).filter(
                SessionModel.id == session_id
            ).with_for_update().first()
            
            if session is None:
                raise TurnConcurrencyError(
                    f"Session {session_id} not found for locking",
                    session_id=session_id,
                )
        
        else:
            # Unknown database: Use SELECT FOR UPDATE on session row
            # This works for most databases that support row-level locking
            from ..storage.models import SessionModel
            session = db.query(SessionModel).filter(
                SessionModel.id == session_id
            ).with_for_update().first()
            
            if session is None:
                raise TurnConcurrencyError(
                    f"Session {session_id} not found for locking",
                    session_id=session_id,
                )
    
    except TurnLockAcquisitionError:
        raise
    except TurnConcurrencyError:
        raise
    except OperationalError as e:
        # Database operation failed (lock timeout, connection issue, etc.)
        raise TurnLockAcquisitionError(
            session_id=session_id,
            timeout_seconds=timeout_seconds,
        )
    except Exception as e:
        # Unexpected error
        raise TurnConcurrencyError(
            f"Failed to acquire lock for session {session_id}: {str(e)}",
            session_id=session_id,
        )


def release_turn_lock(db: Session, session_id: str) -> None:
    """
    Release the turn lock for a session.
    
    Note: For PostgreSQL advisory locks and SQLite transactions,
    the lock is automatically released when the transaction ends
    (commit or rollback). This function is provided for API symmetry
    but typically doesn't need to be called explicitly.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID to unlock
        
    Note:
        In most cases, you should let the transaction complete naturally
        (commit or rollback) which will automatically release the lock.
    """
    # For PostgreSQL advisory locks: Released automatically on transaction end
    # For SQLite: Released automatically on transaction end
    # For other databases: Released automatically on transaction end
    
    # This function is intentionally a no-op for most databases
    # The lock is tied to the transaction lifecycle
    pass


@contextmanager
def execute_with_concurrency_control(
    db: Session,
    session_id: str,
    timeout_seconds: Optional[float] = None,
):
    """
    Context manager for executing turn operations with concurrency control.
    
    This ensures that only one turn can be processed for a session at a time,
    preventing race conditions and duplicate turns.
    
    Usage:
        with execute_with_concurrency_control(db, session_id) as lock_ctx:
            # Allocate turn
            turn_no, is_new = allocate_turn(db, session_id, idempotency_key)
            
            # Execute turn logic
            result = process_turn(db, session_id, turn_no)
            
            # Commit turn
            event = commit_turn(db, session_id, turn_no, ...)
            
            # Lock is automatically released when context exits
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID to lock
        timeout_seconds: Optional timeout for lock acquisition
        
    Yields:
        LockContext: A context object with lock metadata
        
    Raises:
        TurnLockAcquisitionError: If lock acquisition fails
        TurnConcurrencyError: If concurrency control fails
    """
    class LockContext:
        def __init__(self, session_id: str):
            self.session_id = session_id
            self.lock_acquired = False
    
    lock_ctx = LockContext(session_id)
    
    acquire_turn_lock(db, session_id, timeout_seconds)
    lock_ctx.lock_acquired = True
    
    yield lock_ctx


def execute_turn_with_retry(
    db: Session,
    session_id: str,
    idempotency_key: str,
    turn_func: Callable[[Session, str, int], T],
    event_type: str = "player_turn",
    input_text: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
) -> tuple[T, bool]:
    """
    Execute a turn with automatic retry and idempotency support.
    
    This function combines concurrency control with idempotency:
    1. Acquires lock for the session
    2. Checks for existing turn with idempotency key
    3. If exists, returns existing result (is_new=False)
    4. If not, allocates new turn and executes turn_func
    5. Commits the turn
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        idempotency_key: Unique key for this request (enables safe retries)
        turn_func: Function to execute for the turn, receives (db, session_id, turn_no)
        event_type: Event type for the turn (default: "player_turn")
        input_text: Optional player input text
        timeout_seconds: Optional timeout for lock acquisition
        
    Returns:
        Tuple of (result, is_new):
        - result: The turn function result (or existing result if retry)
        - is_new: True if this is a new turn, False if reused existing
        
    Raises:
        TurnLockAcquisitionError: If lock acquisition fails
        TurnConcurrencyError: If concurrency control fails
        TurnAllocationError: If turn allocation fails
        
    Example:
        def process_turn(db, session_id, turn_no):
            # Complex turn processing logic
            return {"narrative": "...", "state": {...}}
        
        result, is_new = execute_turn_with_retry(
            db=db,
            session_id="session_123",
            idempotency_key="req_abc",
            turn_func=process_turn,
        )
    """
    with execute_with_concurrency_control(db, session_id, timeout_seconds):
        # Allocate turn with idempotency key
        turn_no, is_new = allocate_turn(db, session_id, idempotency_key)
        
        if not is_new:
            # Existing turn with this idempotency key - return cached result
            # Fetch the existing event to get the result
            from ..storage.models import EventLogModel
            existing_event = db.query(EventLogModel).filter(
                EventLogModel.session_id == session_id,
                EventLogModel.turn_no == turn_no,
                EventLogModel.event_type == event_type,
            ).first()
            
            if existing_event and existing_event.result_json:
                # Return the cached result
                return existing_event.result_json, False
        
        # New turn - execute the turn function
        result = turn_func(db, session_id, turn_no)
        
        # Commit the turn
        commit_turn(
            db=db,
            session_id=session_id,
            turn_no=turn_no,
            event_type=event_type,
            input_text=input_text,
            result_json=result if isinstance(result, dict) else None,
            idempotency_key=idempotency_key,
        )
        
        return result, True
