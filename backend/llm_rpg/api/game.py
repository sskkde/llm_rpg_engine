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
from .turn_factory import build_turn_orchestrator
from ..storage.models import UserModel

from ..core.turn_orchestrator import TurnOrchestrator, TurnValidationError
from ..core.turn_service import (
    execute_turn_service,
    SessionNotFoundError as TurnServiceSessionNotFoundError,
    TurnServiceError,
    TurnValidationError as TurnServiceValidationError,
)
from ..core.canonical_state import CanonicalStateManager
from ..llm.service import LLMService, MockLLMProvider, OpenAIProvider, get_llm_service
from ..services.settings import SystemSettingsService

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
# Cache key includes provider signature to rebuild when provider config changes
_game_orchestrators: dict[str, TurnOrchestrator] = {}
_orchestrator_provider_signatures: dict[str, str] = {}


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


def get_or_create_orchestrator(game_id: str, db: Session) -> TurnOrchestrator:
    """
    Get existing orchestrator or create new one for the game.
    
    Rebuilds orchestrator when provider configuration changes by comparing
    provider signatures. This ensures LLM provider changes are reflected
    without requiring server restart.
    """
    current_signature = _get_provider_signature(db)
    
    if game_id in _game_orchestrators:
        cached_signature = _orchestrator_provider_signatures.get(game_id, "")
        if cached_signature == current_signature:
            return _game_orchestrators[game_id]
    
    orchestrator = get_turn_orchestrator(db)
    _game_orchestrators[game_id] = orchestrator
    _orchestrator_provider_signatures[game_id] = current_signature
    return orchestrator


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


def _resolve_llm_service(db: Session) -> LLMService:
    """
    Resolve LLMService based on system settings.
    
    Uses the same provider resolution logic as streaming.py:
    - Check provider_mode from SystemSettingsService
    - Use MockLLMProvider for 'mock' mode or when no API key available
    - Use OpenAIProvider with custom settings for 'custom' mode
    - Use OpenAIProvider with effective OpenAI key for 'openai' mode
    - Fall back to MockLLMProvider if no valid configuration
    """
    settings_service = SystemSettingsService(db)
    provider_config = settings_service.get_provider_config()
    
    if provider_config["provider_mode"] == "mock":
        provider = MockLLMProvider()
    elif provider_config["provider_mode"] == "custom":
        custom_key = settings_service.get_effective_custom_api_key()
        custom_url = settings_service.get_effective_custom_base_url()
        if custom_url and custom_key:
            provider = OpenAIProvider(
                api_key=custom_key,
                base_url=custom_url,
                model=provider_config.get("default_model"),
                temperature=provider_config.get("temperature"),
                max_tokens=provider_config.get("max_tokens"),
            )
        else:
            provider = MockLLMProvider()
    else:
        effective_key = settings_service.get_effective_openai_key()
        if effective_key:
            provider = OpenAIProvider(
                api_key=effective_key,
                model=provider_config.get("default_model"),
                temperature=provider_config.get("temperature"),
                max_tokens=provider_config.get("max_tokens"),
            )
        else:
            provider = MockLLMProvider()
    
    return get_llm_service(provider=provider, db_session=db)


def _get_provider_signature(db: Session) -> str:
    """Generate a signature for the current provider configuration."""
    settings_service = SystemSettingsService(db)
    provider_config = settings_service.get_provider_config()
    return f"{provider_config['provider_mode']}:{provider_config.get('default_model', '')}"


def get_turn_orchestrator(db: Session) -> TurnOrchestrator:
    """Factory function to create turn orchestrator with LLM service."""
    llm_service = _resolve_llm_service(db)
    return build_turn_orchestrator(llm_service=llm_service)


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

    try:
        result = execute_turn_service(
            db=db,
            session_id=session_id,
            player_input=request.action,
        )

        return TurnResponse(
            turn_index=result.turn_no,
            narration=result.narration,
            recommended_actions=result.recommended_actions,
            world_time=result.world_time,
            player_state=result.player_state,
            events_committed=result.events_committed,
            actions_committed=result.actions_committed,
            validation_passed=result.validation_passed,
            transaction_id=result.transaction_id or "",
        )
    except TurnServiceValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": str(e),
                "errors": e.errors,
            },
        )
    except TurnServiceSessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except TurnServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
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
    orchestrator = get_or_create_orchestrator(game_id, db)

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
    orchestrator = get_or_create_orchestrator(game_id, db)

    audit_entries = orchestrator.get_audit_log(transaction_id)
    
    return {
        "session_id": session_id,
        "game_id": game_id,
        "entries": audit_entries,
        "count": len(audit_entries),
    }
