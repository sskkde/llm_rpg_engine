"""
Game API - Turn Execution Endpoints

Provides endpoints for executing game turns with full transaction support.
"""

from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..storage.database import get_db
from ..storage.models import SessionModel, SessionStateModel, SessionPlayerStateModel
from ..storage.repositories import (
    SessionRepository,
    SessionStateRepository,
    SessionPlayerStateRepository,
    EventLogRepository,
    LocationRepository,
)

from .auth import get_current_active_user
from .turn_output import finalize_turn_output
from ..storage.models import UserModel

from ..core.turn_orchestrator import TurnOrchestrator, TurnValidationError
from ..core.event_log import EventLog
from ..core.canonical_state import CanonicalStateManager
from ..core.action_scheduler import ActionScheduler
from ..core.validator import Validator
from ..core.perspective import PerspectiveService
from ..core.context_builder import ContextBuilder
from ..core.retrieval import RetrievalSystem
from ..core.npc_memory import NPCMemoryManager
from ..core.lore_store import LoreStore
from ..core.summary import SummaryManager
from ..core.memory_writer import MemoryWriter

from ..engines.world_engine import WorldEngine
from ..engines.npc_engine import NPCEngine
from ..engines.narration_engine import NarrationEngine

from ..models.states import (
    CanonicalState,
    PlayerState,
    WorldState,
    CurrentSceneState,
    NPCState,
    LocationState,
)
from ..models.events import WorldTime


router = APIRouter(prefix="/game", tags=["game"])

# Cache for game orchestrators to persist state across requests
_game_orchestrators: dict[str, TurnOrchestrator] = {}


def _resolve_location_id(
    canonical_location_id: Optional[str],
    db: Session,
    session: SessionModel,
) -> Optional[str]:
    if not canonical_location_id:
        return None

    location_repo = LocationRepository(db)
    location = location_repo.get_by_id(canonical_location_id)
    if location and location.world_id == session.world_id:
        return location.id

    if canonical_location_id.startswith("loc_"):
        code = canonical_location_id[4:]
        location = location_repo.get_by_code(session.world_id, code)
        if location:
            return location.id

    return None


def get_or_create_orchestrator(game_id: str) -> TurnOrchestrator:
    """Get existing orchestrator or create new one for the game."""
    if game_id not in _game_orchestrators:
        _game_orchestrators[game_id] = get_turn_orchestrator()
    return _game_orchestrators[game_id]


class TurnRequest(BaseModel):
    action: str = Field(..., description="Player action input")


class TurnResponse(BaseModel):
    turn_index: int
    narration: str
    recommended_actions: List[str] = []
    world_time: dict
    player_state: dict
    events_committed: int
    actions_committed: int
    validation_passed: bool
    transaction_id: str


class ReplayRequest(BaseModel):
    start_turn: int = Field(default=1, description="Starting turn index")
    end_turn: Optional[int] = Field(None, description="Ending turn index (default: current)")


class ReplayResponse(BaseModel):
    game_id: str
    start_turn: int
    end_turn: int
    reconstructed_state: dict
    events_replayed: int


class AuditLogEntry(BaseModel):
    audit_id: str
    timestamp: str
    type: str
    transaction_id: Optional[str] = None
    errors: Optional[List[str]] = None


def get_turn_orchestrator():
    """Factory function to create turn orchestrator with all dependencies."""
    event_log = EventLog()
    state_manager = CanonicalStateManager()
    action_scheduler = ActionScheduler()
    validator = Validator()
    perspective_service = PerspectiveService()
    retrieval_system = RetrievalSystem()
    context_builder = ContextBuilder(retrieval_system, perspective_service)
    npc_memory = NPCMemoryManager()
    lore_store = LoreStore()
    summary_manager = SummaryManager()
    memory_writer = MemoryWriter(event_log, npc_memory, summary_manager)
    
    world_engine = WorldEngine(state_manager, event_log)
    npc_engine = NPCEngine(state_manager, npc_memory, perspective_service, context_builder)
    narration_engine = NarrationEngine(state_manager, perspective_service, context_builder, validator)
    
    return TurnOrchestrator(
        state_manager=state_manager,
        event_log=event_log,
        action_scheduler=action_scheduler,
        validator=validator,
        perspective_service=perspective_service,
        context_builder=context_builder,
        world_engine=world_engine,
        npc_engine=npc_engine,
        narration_engine=narration_engine,
    )


def _initialize_game_state(game_id: str, state_manager: CanonicalStateManager) -> CanonicalState:
    """Initialize a new game state with demo content."""
    world_time = WorldTime(
        calendar="青岚历",
        season="春",
        day=1,
        period="辰时",
    )

    player_state = PlayerState(
        entity_id="player",
        name="沈青",
        location_id="loc_square",
        flags={"turn_index": 0},
    )

    world_state = WorldState(
        entity_id="world",
        world_id=game_id,
        current_time=world_time,
    )

    scene_state = CurrentSceneState(
        entity_id="scene",
        scene_id="scene_square",
        location_id="loc_square",
        active_actor_ids=["player"],
    )

    canonical_state = state_manager.initialize_game(
        game_id=game_id,
        player_state=player_state,
        world_state=world_state,
        scene_state=scene_state,
    )

    canonical_state.npc_states["npc_senior_sister"] = NPCState(
        entity_id="npc_senior_sister",
        npc_id="npc_senior_sister",
        name="师姐凌月",
        location_id="loc_trial_hall",
        mood="calm",
    )

    canonical_state.location_states["loc_square"] = LocationState(
        entity_id="loc_square",
        location_id="loc_square",
        name="山门广场",
        known_to_player=True,
    )

    canonical_state.location_states["loc_trial_hall"] = LocationState(
        entity_id="loc_trial_hall",
        location_id="loc_trial_hall",
        name="试炼堂",
        known_to_player=True,
    )

    return canonical_state


@router.post("/sessions/{session_id}/turn", response_model=TurnResponse)
def execute_turn(
    session_id: str,
    request: TurnRequest,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Execute a game turn with full transaction support.
    
    The turn follows the deterministic pipeline:
    1. Parse player input
    2. World tick
    3. NPC decisions
    4. Conflict resolution
    5. Validation
    6. Atomic commit
    7. Narration generation
    
    If validation fails, no state changes are committed and an audit error is recorded.
    """
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    game_id = f"game_{session_id}"

    # Get or initialize turn index from orchestrator
    orchestrator = get_or_create_orchestrator(game_id)
    existing_state = orchestrator._state_manager.get_state(game_id)
    if existing_state is None:
        _initialize_game_state(game_id, orchestrator._state_manager)

    # Get current turn from event log
    recent_events = orchestrator._event_log._store.get_recent_events(limit=1)
    if recent_events:
        current_turn = recent_events[0].turn_index
    else:
        current_turn = 0

    next_turn = current_turn + 1

    try:
        result = orchestrator.execute_turn(
            session_id=session_id,
            game_id=game_id,
            turn_index=next_turn,
            player_input=request.action,
        )
        narration, recommended_actions = finalize_turn_output(
            result["narration"],
            forbidden_info=result.get("forbidden_info", []),
        )

        # Update session state in database
        state_repo = SessionStateRepository(db)
        resolved_location_id = _resolve_location_id(
            result["player_state"].get("location_id"),
            db,
            session,
        )
        state_repo.create_or_update({
            "session_id": session_id,
            "current_time": result["world_time"].get("period", "未知"),
            "time_phase": result["world_time"].get("period", "未知"),
            "active_mode": "exploration",
            "current_location_id": resolved_location_id,
        })
        
        # Update last played
        session_repo.update_last_played(session_id)
        
        # Create player_turn adventure log entry
        event_log_repo = EventLogRepository(db)
        event_log_repo.create_or_get_player_turn(
            session_id=session_id,
            turn_no=next_turn,
            input_text=request.action,
            narrative_text=narration,
            result_json={
                "transaction_id": result["transaction_id"],
                "recommended_actions": recommended_actions,
            },
        )
        
        return TurnResponse(
            turn_index=result["turn_index"],
            narration=narration,
            recommended_actions=recommended_actions,
            world_time=result["world_time"],
            player_state=result["player_state"],
            events_committed=result["events_committed"],
            actions_committed=result["actions_committed"],
            validation_passed=result["validation_passed"],
            transaction_id=result["transaction_id"],
        )
        
    except TurnValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": str(e),
                "errors": e.validation_result.errors,
                "warnings": e.validation_result.warnings,
                "audit_event_id": e.audit_event_id,
            }
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post("/sessions/{session_id}/replay", response_model=ReplayResponse)
def replay_turns(
    session_id: str,
    request: ReplayRequest,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Replay turns from event log to reconstruct canonical state.
    
    Used for:
    - State verification
    - Debugging
    - Recovery from snapshots
    """
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    game_id = f"game_{session_id}"
    orchestrator = get_or_create_orchestrator(game_id)

    # Initialize game state if not exists
    existing_state = orchestrator._state_manager.get_state(game_id)
    if existing_state is None:
        _initialize_game_state(game_id, orchestrator._state_manager)

    # Get current turn from event log
    recent_events = orchestrator._event_log._store.get_recent_events(limit=1)
    if recent_events:
        current_turn = recent_events[0].turn_index
    else:
        current_turn = 0

    end_turn = request.end_turn or current_turn

    if end_turn > current_turn:
        end_turn = current_turn
    
    try:
        reconstructed_state = orchestrator.replay_turns(
            game_id=game_id,
            start_turn=request.start_turn,
            end_turn=end_turn,
        )
        
        # Count events replayed
        events = orchestrator._event_log._store.get_events_in_range(
            request.start_turn, end_turn
        )
        
        return ReplayResponse(
            game_id=game_id,
            start_turn=request.start_turn,
            end_turn=end_turn,
            reconstructed_state={
                "player_state": reconstructed_state.player_state.model_dump(),
                "world_state": reconstructed_state.world_state.model_dump(),
                "scene_state": reconstructed_state.current_scene_state.model_dump(),
                "npc_count": len(reconstructed_state.npc_states),
                "location_count": len(reconstructed_state.location_states),
            },
            events_replayed=len(events),
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get("/sessions/{session_id}/audit-log")
def get_audit_log(
    session_id: str,
    transaction_id: Optional[str] = None,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get audit log for a session, optionally filtered by transaction."""
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    game_id = f"game_{session_id}"
    orchestrator = get_or_create_orchestrator(game_id)

    audit_entries = orchestrator.get_audit_log(transaction_id)
    
    return {
        "session_id": session_id,
        "game_id": game_id,
        "entries": audit_entries,
        "count": len(audit_entries),
    }
