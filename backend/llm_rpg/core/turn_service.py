"""
Turn Execution Service.

This module provides a unified turn execution service that handles:
- Session initialization (baseline story state rows)
- State reconstruction from DB
- Turn allocation (DB-authoritative numbering)
- Core turn execution (movement, scene, NPC, quest)
- State persistence (session_state, adventure log, recommended_actions)
- Error mapping

Both /game/sessions/{session_id}/turn and /streaming/sessions/{session_id}/turn
should call this service to ensure identical side effects for the same input.

Key invariants:
- No state mutation without corresponding DB record
- Streaming may stream narration AFTER durable commit
- Both endpoints produce identical DB side effects
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from sqlalchemy.orm import Session

from .session_initialization import initialize_session_story_state, SessionInitializationError
from .state_reconstruction import reconstruct_canonical_state, StateReconstructionError
from .turn_allocation import (
    allocate_turn,
    commit_turn,
    get_current_turn_number,
    TurnAllocationError,
    TurnConflictError,
)
from .movement_handler import handle_movement, MovementResult, MovementError
from .scene_action_generator import generate_recommended_actions
from .quest_progression import check_quest_progression, QuestProgressionError

from ..storage.models import SessionModel, EventLogModel
from ..storage.repositories import (
    SessionRepository,
    SessionStateRepository,
    EventLogRepository,
    LocationRepository,
)
from ..models.states import CanonicalState


class TurnServiceError(Exception):
    """Base exception for turn service errors."""
    
    def __init__(self, message: str, session_id: Optional[str] = None, turn_no: Optional[int] = None):
        self.session_id = session_id
        self.turn_no = turn_no
        super().__init__(message)


class SessionNotFoundError(TurnServiceError):
    """Raised when session is not found."""
    pass


class TurnValidationError(TurnServiceError):
    """Raised when turn validation fails."""
    
    def __init__(
        self,
        message: str,
        errors: List[str],
        session_id: Optional[str] = None,
        turn_no: Optional[int] = None,
    ):
        self.errors = errors
        super().__init__(message, session_id, turn_no)


@dataclass
class TurnResult:
    """Result of a turn execution."""
    
    turn_no: int
    narration: str
    recommended_actions: List[str] = field(default_factory=list)
    state_deltas: Dict[str, Any] = field(default_factory=dict)
    world_time: Dict[str, Any] = field(default_factory=dict)
    player_state: Dict[str, Any] = field(default_factory=dict)
    transaction_id: Optional[str] = None
    events_committed: int = 0
    actions_committed: int = 0
    validation_passed: bool = True
    movement_result: Optional[MovementResult] = None
    is_new_turn: bool = True


def execute_turn_service(
    db: Session,
    session_id: str,
    player_input: str,
    idempotency_key: Optional[str] = None,
) -> TurnResult:
    """
    Execute a turn with full transaction support.
    
    This is the unified entry point for both streaming and non-streaming endpoints.
    
    Pipeline:
    1. Initialize session story state if needed (idempotent)
    2. Reconstruct canonical state from DB
    3. Allocate turn number (DB-authoritative)
    4. Parse player input and determine action type
    5. Execute action (movement, scene, NPC, quest)
    6. Commit turn to DB (adventure log, session state, recommended actions)
    7. Return TurnResult
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        player_input: The player's input text
        idempotency_key: Optional idempotency key for retries
        
    Returns:
        TurnResult with narration, recommended_actions, state_deltas, turn_no
        
    Raises:
        SessionNotFoundError: If session not found
        TurnValidationError: If validation fails
        TurnServiceError: For other errors
    """
    # Step 1: Verify session exists
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    
    if session is None:
        raise SessionNotFoundError(
            f"Session not found: {session_id}",
            session_id=session_id,
        )
    
    world_id = session.world_id
    
    # Step 2: Initialize session story state if needed (idempotent)
    try:
        initialize_session_story_state(db, session_id)
    except SessionInitializationError as e:
        raise TurnServiceError(
            f"Failed to initialize session: {str(e)}",
            session_id=session_id,
        )
    
    # Step 3: Reconstruct canonical state from DB
    # This is used for context building, not for mutation
    try:
        canonical_state = reconstruct_canonical_state(db, session_id)
        if canonical_state is None:
            raise TurnServiceError(
                f"Failed to reconstruct state for session: {session_id}",
                session_id=session_id,
            )
    except StateReconstructionError as e:
        raise TurnServiceError(
            f"State reconstruction failed: {str(e)}",
            session_id=session_id,
        )
    
    # Step 4: Allocate turn number (DB-authoritative)
    try:
        turn_no, is_new = allocate_turn(db, session_id, idempotency_key)
    except TurnConflictError as e:
        raise TurnServiceError(
            f"Turn conflict: {str(e)}",
            session_id=session_id,
        )
    except TurnAllocationError as e:
        raise TurnServiceError(
            f"Turn allocation failed: {str(e)}",
            session_id=session_id,
        )
    
    # If this is a retry with idempotency key and turn already exists,
    # return the existing turn result
    if not is_new:
        existing_result = _get_existing_turn_result(db, session_id, turn_no)
        if existing_result:
            return existing_result
    
    # Step 5: Parse player input and determine action type
    action_type, target = _parse_player_input(player_input)
    
    # Step 6: Execute action
    movement_result: Optional[MovementResult] = None
    state_deltas: Dict[str, Any] = {}
    
    if action_type == "move" and target:
        # Handle movement
        movement_result = handle_movement(db, session_id, target)
        
        if movement_result.success:
            state_deltas["location_id"] = movement_result.new_location_id
        else:
            # Blocked movement - no state mutation
            state_deltas["blocked_reason"] = movement_result.blocked_reason
    
    # Step 7: Check quest progression
    if movement_result and movement_result.success:
        try:
            quest_results = check_quest_progression(
                db=db,
                session_id=session_id,
                action_context={
                    "action_type": "movement",
                    "target_location_code": movement_result.new_location_code,
                },
            )
            # Quest progression results can be used for narration context
            state_deltas["quest_progression"] = [
                {"quest_name": r.quest_progress.quest_name, "message": r.message}
                for r in quest_results
                if r.triggered and r.quest_progress
            ]
        except QuestProgressionError:
            # Quest progression failure should not block the turn
            pass
    
    # Step 8: Generate recommended actions
    session_state_repo = SessionStateRepository(db)
    session_state = session_state_repo.get_by_session(session_id)
    
    current_location_id = None
    if session_state:
        current_location_id = session_state.current_location_id
    
    if movement_result and movement_result.success:
        current_location_id = movement_result.new_location_id
    
    recommended_actions = generate_recommended_actions(
        db=db,
        session_id=session_id,
        location_id=current_location_id,
    )
    
    # Step 9: Build narration
    narration = _build_narration(
        player_input=player_input,
        action_type=action_type,
        movement_result=movement_result,
        canonical_state=canonical_state,
    )
    
    # Step 10: Get world time from session state
    world_time = _get_world_time(session_state)
    
    # Step 11: Get player state
    player_state = _get_player_state(canonical_state, current_location_id)
    
    # Step 12: Commit turn to DB
    transaction_id = f"txn_{session_id}_{turn_no}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    try:
        event = commit_turn(
            db=db,
            session_id=session_id,
            turn_no=turn_no,
            event_type="player_turn",
            input_text=player_input,
            narrative_text=narration,
            result_json={
                "transaction_id": transaction_id,
                "recommended_actions": recommended_actions,
                "state_deltas": state_deltas,
                "action_type": action_type,
                "movement_success": movement_result.success if movement_result else None,
                "new_location_id": movement_result.new_location_id if movement_result else None,
            },
            idempotency_key=idempotency_key,
        )
    except TurnAllocationError as e:
        raise TurnServiceError(
            f"Failed to commit turn: {str(e)}",
            session_id=session_id,
            turn_no=turn_no,
        )
    
    # Step 13: Update session state if movement succeeded
    if movement_result and movement_result.success and movement_result.new_location_id:
        session_state_repo.create_or_update({
            "session_id": session_id,
            "current_location_id": movement_result.new_location_id,
        })
    
    # Step 14: Update last played
    session_repo.update_last_played(session_id)
    
    # Step 15: Return result
    return TurnResult(
        turn_no=turn_no,
        narration=narration,
        recommended_actions=recommended_actions,
        state_deltas=state_deltas,
        world_time=world_time,
        player_state=player_state,
        transaction_id=transaction_id,
        events_committed=1,
        actions_committed=1 if movement_result and movement_result.success else 0,
        validation_passed=True,
        movement_result=movement_result,
        is_new_turn=is_new,
    )


def _get_existing_turn_result(
    db: Session,
    session_id: str,
    turn_no: int,
) -> Optional[TurnResult]:
    """
    Get existing turn result for idempotency.
    
    Returns None if turn doesn't exist or is incomplete.
    """
    event_log_repo = EventLogRepository(db)
    event = event_log_repo.get_by_session_turn_event(session_id, turn_no, "player_turn")
    
    if event is None:
        return None
    
    if not event.result_json:
        return None
    
    result_json = event.result_json
    
    return TurnResult(
        turn_no=turn_no,
        narration=event.narrative_text or "",
        recommended_actions=result_json.get("recommended_actions", []),
        state_deltas=result_json.get("state_deltas", {}),
        world_time={},
        player_state={},
        transaction_id=result_json.get("transaction_id"),
        events_committed=1,
        actions_committed=1,
        validation_passed=True,
        is_new_turn=False,
    )


def _parse_player_input(player_input: str) -> Tuple[str, Optional[str]]:
    """
    Parse player input to determine action type and target.
    
    Returns (action_type, target) tuple.
    """
    input_lower = player_input.lower().strip()
    
    # Movement keywords
    move_keywords = ["走", "去", "前往", "移动", "move", "go", "walk"]
    for keyword in move_keywords:
        if keyword in input_lower:
            # Extract target location
            # Simple heuristic: take the rest of the input after the keyword
            target = input_lower.split(keyword)[-1].strip()
            # Remove common particles
            target = target.replace("到", "").replace("向", "").strip()
            return ("move", target if target else None)
    
    # Talk keywords
    talk_keywords = ["说", "问", "交谈", "talk", "speak", "ask"]
    for keyword in talk_keywords:
        if keyword in input_lower:
            return ("talk", None)
    
    # Inspect keywords
    inspect_keywords = ["看", "观察", "检查", "inspect", "look", "observe"]
    for keyword in inspect_keywords:
        if keyword in input_lower:
            return ("inspect", None)
    
    # Attack keywords
    attack_keywords = ["打", "攻击", "战斗", "attack", "fight"]
    for keyword in attack_keywords:
        if keyword in input_lower:
            return ("attack", None)
    
    # Default to general action
    return ("action", None)


def _build_narration(
    player_input: str,
    action_type: str,
    movement_result: Optional[MovementResult],
    canonical_state: CanonicalState,
) -> str:
    """
    Build narration text for the turn.
    
    Uses movement result if available, otherwise generates generic narration.
    """
    if movement_result:
        if movement_result.success:
            return movement_result.narration_hint or f"你来到了{movement_result.new_location_name}。"
        else:
            return movement_result.narration_hint or f"你无法前往那里。{movement_result.blocked_reason or ''}"
    
    # Generic narration for non-movement actions
    if action_type == "talk":
        return "你试图与人交谈。"
    elif action_type == "inspect":
        return "你仔细观察周围的环境。"
    elif action_type == "attack":
        return "你准备战斗。"
    else:
        return f"你{player_input}。"


def _get_world_time(session_state) -> Dict[str, Any]:
    """Get world time from session state."""
    if session_state and session_state.current_time:
        # Parse time string format: "修仙历 春 第1日 辰时"
        time_parts = session_state.current_time.split()
        if len(time_parts) >= 4:
            return {
                "calendar": time_parts[0],
                "season": time_parts[1],
                "day": time_parts[2],
                "period": time_parts[3],
            }
    
    # Default world time
    return {
        "calendar": "修仙历",
        "season": "春",
        "day": "第1日",
        "period": "辰时",
    }


def _get_player_state(
    canonical_state: CanonicalState,
    current_location_id: Optional[str],
) -> Dict[str, Any]:
    """Get player state dict from canonical state."""
    player_state = canonical_state.player_state
    
    return {
        "entity_id": player_state.entity_id,
        "name": player_state.name,
        "location_id": current_location_id or player_state.location_id,
        "realm": player_state.realm,
        "spiritual_power": player_state.spiritual_power,
    }
