"""Validation Context Module.

This module defines ValidationContext - a container for all state and metadata
needed during validation operations.

Design Principles:
- ValidationContext is a dataclass, not a service
- It holds all context needed for validation in one place
- Factory method provides convenient construction
"""

from dataclasses import dataclass
from typing import Any, Optional

from ...models.states import CanonicalState
from ...models.perspectives import Perspective


@dataclass
class ValidationContext:
    """Context for validation operations containing all necessary state and metadata.

    Attributes:
        db: Database session for queries
        session_id: Game session ID
        turn_no: Current turn number
        canonical_state: Current canonical state
        perspective: Optional perspective for filtering
        source_event_id: Source event that triggered validation
        actor_id: Actor performing the action
    """
    db: Any
    session_id: str
    turn_no: int
    canonical_state: CanonicalState
    perspective: Optional[Perspective] = None
    source_event_id: Optional[str] = None
    actor_id: Optional[str] = None

    @classmethod
    def create(
        cls,
        db: Any,
        session_id: str,
        turn_no: int,
        canonical_state: CanonicalState,
        perspective: Optional[Perspective] = None,
        source_event_id: Optional[str] = None,
        actor_id: Optional[str] = None,
    ) -> "ValidationContext":
        """Factory method to create a ValidationContext.

        Args:
            db: Database session
            session_id: Game session ID
            turn_no: Current turn number
            canonical_state: Current canonical state
            perspective: Optional perspective for filtering
            source_event_id: Source event that triggered validation
            actor_id: Actor performing the action

        Returns:
            ValidationContext instance
        """
        return cls(
            db=db,
            session_id=session_id,
            turn_no=turn_no,
            canonical_state=canonical_state,
            perspective=perspective,
            source_event_id=source_event_id,
            actor_id=actor_id,
        )


__all__ = ["ValidationContext"]