"""
Turn Allocation Service.

This module provides DB-authoritative turn allocation and commit functionality.
It ensures idempotent turn numbering by querying persisted event_logs,
not in-memory caches.

Key features:
- DB-authoritative turn numbering via SELECT MAX(turn_no)
- Idempotency key support for retry scenarios
- Transaction boundaries around turn persistence
- Conflict detection for concurrent requests
"""

from typing import Optional, Tuple, Dict, Any
from datetime import datetime

from sqlalchemy import func, and_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..storage.models import EventLogModel
from ..storage.repositories import EventLogRepository


class TurnAllocationError(Exception):
    """Raised when turn allocation fails."""
    
    def __init__(self, message: str, session_id: Optional[str] = None):
        self.session_id = session_id
        super().__init__(message)


class TurnConflictError(TurnAllocationError):
    """Raised when concurrent turn allocation conflicts."""
    
    def __init__(self, session_id: str, attempted_turn: int, existing_turn: int):
        self.attempted_turn = attempted_turn
        self.existing_turn = existing_turn
        super().__init__(
            f"Turn conflict: attempted turn {attempted_turn} but turn {existing_turn} already exists for session {session_id}",
            session_id=session_id,
        )


def allocate_turn(
    db: Session,
    session_id: str,
    idempotency_key: Optional[str] = None,
) -> Tuple[int, bool]:
    """
    Allocate the next turn number for a session.
    
    This function queries the DB for the authoritative turn number,
    ensuring consistency even after orchestrator cache reset.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID to allocate a turn for
        idempotency_key: Optional key for idempotent retries.
                        If provided and a turn exists with this key,
                        returns the existing turn instead of allocating new.
                        
    Returns:
        Tuple of (turn_no, is_new):
        - turn_no: The allocated turn number
        - is_new: True if this is a newly allocated turn, False if reused
        
    Raises:
        TurnAllocationError: If allocation fails
        TurnConflictError: If concurrent allocation detected (no idempotency key)
        
    Example:
        # First request
        turn_no, is_new = allocate_turn(db, "session_123")
        # Returns (1, True)
        
        # Retry with idempotency key
        turn_no, is_new = allocate_turn(db, "session_123", idempotency_key="req_abc")
        # Returns (1, False) - reuses existing turn
        
        # Concurrent request without key
        turn_no, is_new = allocate_turn(db, "session_123")
        # May raise TurnConflictError if another request committed first
    """
    event_log_repo = EventLogRepository(db)
    
    # Step 1: Check for existing turn with idempotency key
    if idempotency_key:
        # Look for existing turn with this idempotency key
        # Idempotency keys are stored in structured_action metadata
        existing = db.query(EventLogModel).filter(
            and_(
                EventLogModel.session_id == session_id,
                EventLogModel.structured_action.isnot(None),
            )
        ).all()
        
        for event in existing:
            if event.structured_action:
                structured = event.structured_action
                if isinstance(structured, dict) and structured.get("idempotency_key") == idempotency_key:
                    # Found existing turn with this key - return it
                    return (event.turn_no, False)
    
    # Step 2: Get current max turn from DB (authoritative source)
    max_turn_result = db.query(func.max(EventLogModel.turn_no)).filter(
        EventLogModel.session_id == session_id
    ).scalar()
    
    current_max_turn = max_turn_result if max_turn_result is not None else 0
    next_turn = current_max_turn + 1
    
    # Step 3: Check for concurrent allocation
    # If a turn already exists at next_turn without our idempotency key,
    # another request got there first
    existing_at_next = event_log_repo.get_by_session_turn_event(
        session_id, next_turn, "player_turn"
    )
    
    if existing_at_next:
        # Another request already allocated this turn
        if idempotency_key:
            # With idempotency key, check if it's ours
            if existing_at_next.structured_action:
                structured = existing_at_next.structured_action
                if isinstance(structured, dict) and structured.get("idempotency_key") == idempotency_key:
                    return (next_turn, False)
        
        # Conflict - another request got this turn
        raise TurnConflictError(
            session_id=session_id,
            attempted_turn=next_turn,
            existing_turn=next_turn,
        )
    
    # Step 4: Return allocated turn
    # Note: We don't persist here - commit_turn does that
    # This allows the caller to validate before committing
    return (next_turn, True)


def commit_turn(
    db: Session,
    session_id: str,
    turn_no: int,
    event_type: str,
    input_text: Optional[str] = None,
    result_json: Optional[Dict[str, Any]] = None,
    narrative_text: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> EventLogModel:
    """
    Commit a turn event to the database.
    
    This function persists turn data within a transaction boundary.
    It handles unique constraint violations gracefully for idempotency.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        turn_no: The turn number
        event_type: The event type (e.g., "player_turn", "initial_scene")
        input_text: Optional player input text
        result_json: Optional structured result data
        narrative_text: Optional narrative text
        idempotency_key: Optional idempotency key for retries
        
    Returns:
        The created or existing EventLogModel
        
    Raises:
        TurnAllocationError: If commit fails
        
    Example:
        event = commit_turn(
            db=db,
            session_id="session_123",
            turn_no=1,
            event_type="player_turn",
            input_text="我走向山林",
            result_json={"location": "forest"},
            narrative_text="你走向山林深处...",
            idempotency_key="req_abc",
        )
    """
    event_log_repo = EventLogRepository(db)
    
    # Step 1: Check if event already exists (idempotency)
    existing = event_log_repo.get_by_session_turn_event(session_id, turn_no, event_type)
    if existing:
        # Event already committed - return it for idempotency
        return existing
    
    # Step 2: Build structured_action with idempotency key if provided
    structured_action = None
    if idempotency_key:
        structured_action = {"idempotency_key": idempotency_key}
    
    # Step 3: Create event log entry
    try:
        event = event_log_repo.create({
            "session_id": session_id,
            "turn_no": turn_no,
            "event_type": event_type,
            "input_text": input_text,
            "structured_action": structured_action,
            "result_json": result_json,
            "narrative_text": narrative_text,
        })
        db.commit()
        return event
        
    except IntegrityError as e:
        db.rollback()
        
        # Check if it's a unique constraint violation
        # This can happen with concurrent requests
        if "uq_event_logs_session_turn_type" in str(e) or "UNIQUE constraint failed" in str(e):
            # Another request committed first - fetch and return existing
            existing = event_log_repo.get_by_session_turn_event(session_id, turn_no, event_type)
            if existing:
                return existing
        
        # Re-raise other integrity errors
        raise TurnAllocationError(
            f"Failed to commit turn {turn_no} for session {session_id}: {str(e)}",
            session_id=session_id,
        )
    
    except Exception as e:
        db.rollback()
        raise TurnAllocationError(
            f"Failed to commit turn {turn_no} for session {session_id}: {str(e)}",
            session_id=session_id,
        )


def get_current_turn_number(db: Session, session_id: str) -> int:
    """
    Get the current turn number for a session from the DB.
    
    This is a convenience function that queries the DB for the max turn_no.
    It's used by endpoints that need to know the current turn without allocating.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        
    Returns:
        The current turn number (max turn_no from event_logs), or 0 if no events
    """
    max_turn_result = db.query(func.max(EventLogModel.turn_no)).filter(
        EventLogModel.session_id == session_id
    ).scalar()
    
    return max_turn_result if max_turn_result is not None else 0
