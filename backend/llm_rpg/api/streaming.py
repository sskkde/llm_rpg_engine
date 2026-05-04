"""
SSE Streaming API for Turn Execution

Provides Server-Sent Events endpoint for streaming turn execution.
Events are emitted in order:
1. turn_started
2. event_committed (state/events committed to DB)
3. narration_delta (streaming narration text)
4. turn_completed
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import AsyncGenerator, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..storage.database import get_db
from ..storage.models import SessionModel
from ..storage.repositories import SessionRepository

from .auth import get_current_active_user
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

from ..llm.service import (
    get_llm_service,
    MockLLMProvider,
    LLMMessage,
    LLMService,
)
from ..llm.parsers import OutputParser, ParsedNarration


router = APIRouter(prefix="/streaming", tags=["streaming"])

_game_orchestrators: Dict[str, TurnOrchestrator] = {}


class SSEEvent(BaseModel):
    """SSE event structure."""
    event: str
    data: Dict[str, Any]
    id: Optional[str] = None


def format_sse(event: str, data: Dict[str, Any], event_id: Optional[str] = None) -> str:
    """Format data as SSE message."""
    def json_serial(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")
    
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False, default=json_serial)}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def get_turn_orchestrator() -> TurnOrchestrator:
    """Factory function to create turn orchestrator."""
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


def get_or_create_orchestrator(game_id: str) -> TurnOrchestrator:
    """Get existing orchestrator or create new one."""
    if game_id not in _game_orchestrators:
        _game_orchestrators[game_id] = get_turn_orchestrator()
    return _game_orchestrators[game_id]


def _initialize_game_state(game_id: str, state_manager: CanonicalStateManager):
    """Initialize game state with demo content."""
    from ..models.states import (
        PlayerState, WorldState, CurrentSceneState,
        NPCState, LocationState, WorldTime
    )
    
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


class StreamTurnRequest(BaseModel):
    """Request to stream a turn."""
    action: str = Field(..., description="Player action input")


async def generate_narration_stream(
    game_id: str,
    turn_index: int,
    session_id: str,
    llm_service: LLMService,
) -> AsyncGenerator[str, None]:
    """
    Generate streaming narration using LLM.
    
    Yields text chunks that form the complete narration.
    """
    messages = [
        LLMMessage(
            role="system",
            content="你是一个文字RPG的叙事者。用生动的中文描述场景。"
        ),
        LLMMessage(
            role="user",
            content=f"第{turn_index}回合，请描述山门广场的场景。"
        ),
    ]
    
    async for chunk in llm_service.generate_stream(
        messages=messages,
        template_id="narration_v1",
        session_id=session_id,
        turn_no=turn_index,
        temperature=0.8,
        max_tokens=500,
    ):
        yield chunk


async def execute_turn_stream(
    session_id: str,
    game_id: str,
    turn_index: int,
    player_input: str,
    db: Session,
    use_mock: bool = False,
) -> AsyncGenerator[str, None]:
    """
    Execute a turn with streaming SSE events.
    
    Event order:
    1. turn_started
    2. event_committed (after atomic commit)
    3. narration_delta (streaming text)
    4. turn_completed
    """
    event_id = str(uuid.uuid4())
    
    # Initialize LLM service based on system settings
    from ..services.settings import SystemSettingsService
    settings_service = SystemSettingsService(db)
    provider_config = settings_service.get_provider_config()
    
    if use_mock or provider_config["provider_mode"] == "mock":
        provider = MockLLMProvider()
    else:
        effective_key = settings_service.get_effective_openai_key()
        if effective_key:
            from ..llm.service import OpenAIProvider
            provider = OpenAIProvider(
                api_key=effective_key,
                model=provider_config.get("default_model"),
                temperature=provider_config.get("temperature"),
                max_tokens=provider_config.get("max_tokens"),
            )
        elif provider_config["provider_mode"] == "openai":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No effective OpenAI API key available"
            )
        else:
            provider = MockLLMProvider()
    
    llm_service = get_llm_service(provider=provider, db_session=db)
    
    try:
        # 1. Emit turn_started
        yield format_sse(
            "turn_started",
            {
                "session_id": session_id,
                "turn_index": turn_index,
                "player_input": player_input,
                "timestamp": datetime.now().isoformat(),
            },
            event_id=f"{event_id}_start"
        )
        
        # Get orchestrator
        orchestrator = get_or_create_orchestrator(game_id)
        
        # Initialize game state if needed
        existing_state = orchestrator._state_manager.get_state(game_id)
        if existing_state is None:
            _initialize_game_state(game_id, orchestrator._state_manager)
        
        # Execute turn (non-streaming for the core logic)
        result = orchestrator.execute_turn(
            session_id=session_id,
            game_id=game_id,
            turn_index=turn_index,
            player_input=player_input,
        )
        
        # 2. Emit event_committed after atomic commit
        yield format_sse(
            "event_committed",
            {
                "session_id": session_id,
                "turn_index": turn_index,
                "transaction_id": result.get("transaction_id"),
                "events_committed": result.get("events_committed", 0),
                "actions_committed": result.get("actions_committed", 0),
                "world_time": result.get("world_time"),
                "timestamp": datetime.now().isoformat(),
            },
            event_id=f"{event_id}_committed"
        )
        
        # Small delay to ensure frontend processes the commit event
        await asyncio.sleep(0.05)
        
        # 3. Stream narration_delta
        accumulated_narration = []
        async for chunk in generate_narration_stream(
            game_id=game_id,
            turn_index=turn_index,
            session_id=session_id,
            llm_service=llm_service,
        ):
            accumulated_narration.append(chunk)
            yield format_sse(
                "narration_delta",
                {
                    "delta": chunk,
                    "turn_index": turn_index,
                },
                event_id=f"{event_id}_delta"
            )
            # Small delay for natural streaming effect
            await asyncio.sleep(0.01)
        
        # Get full narration
        full_narration = "".join(accumulated_narration) if accumulated_narration else result.get("narration", "")
        
        # 4. Emit turn_completed
        yield format_sse(
            "turn_completed",
            {
                "session_id": session_id,
                "turn_index": turn_index,
                "narration": full_narration,
                "player_state": result.get("player_state"),
                "world_time": result.get("world_time"),
                "timestamp": datetime.now().isoformat(),
            },
            event_id=f"{event_id}_complete"
        )
        
        from ..storage.repositories import SessionStateRepository
        state_repo = SessionStateRepository(db)
        state_repo.create_or_update({
            "session_id": session_id,
            "current_time": result["world_time"].get("period", "未知"),
            "time_phase": result["world_time"].get("period", "未知"),
            "active_mode": "exploration",
            "current_location_id": result["player_state"].get("location_id"),
        })
        
        session_repo = SessionRepository(db)
        session_repo.update_last_played(session_id)
        
    except TurnValidationError as e:
        yield format_sse(
            "turn_error",
            {
                "session_id": session_id,
                "turn_index": turn_index,
                "error_type": "validation_error",
                "message": str(e),
                "errors": e.validation_result.errors if e.validation_result else [],
                "audit_event_id": e.audit_event_id,
                "timestamp": datetime.now().isoformat(),
            },
            event_id=f"{event_id}_error"
        )
    except Exception as e:
        yield format_sse(
            "turn_error",
            {
                "session_id": session_id,
                "turn_index": turn_index,
                "error_type": "unexpected_error",
                "message": str(e),
                "timestamp": datetime.now().isoformat(),
            },
            event_id=f"{event_id}_error"
        )


@router.post("/sessions/{session_id}/turn")
async def stream_turn(
    session_id: str,
    request: StreamTurnRequest,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Stream a turn execution using SSE.
    
    Events emitted in order:
    - turn_started: Turn execution begins
    - event_committed: State/events committed to DB (durable)
    - narration_delta: Streaming narration text chunks
    - turn_completed: Turn execution complete
    
    The narration is streamed AFTER the durable commit,
    ensuring state is persisted before any response is sent.
    """
    # Verify session exists and belongs to user
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
    
    # Get current turn index
    orchestrator = get_or_create_orchestrator(game_id)
    recent_events = orchestrator._event_log._store.get_recent_events(limit=1)
    if recent_events:
        current_turn = recent_events[0].turn_index
    else:
        current_turn = 0
    next_turn = current_turn + 1
    
    return StreamingResponse(
        execute_turn_stream(
            session_id=session_id,
            game_id=game_id,
            turn_index=next_turn,
            player_input=request.action,
            db=db,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/sessions/{session_id}/turn/mock")
async def stream_turn_mock(
    session_id: str,
    request: StreamTurnRequest,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Stream a turn using mock LLM provider (no API key required).
    
    Same event order as the main endpoint, but uses MockLLMProvider
    for testing without real API keys.
    """
    # Verify session exists and belongs to user
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
    
    # Get current turn index
    orchestrator = get_or_create_orchestrator(game_id)
    recent_events = orchestrator._event_log._store.get_recent_events(limit=1)
    if recent_events:
        current_turn = recent_events[0].turn_index
    else:
        current_turn = 0
    next_turn = current_turn + 1
    
    return StreamingResponse(
        execute_turn_stream(
            session_id=session_id,
            game_id=game_id,
            turn_index=next_turn,
            player_input=request.action,
            db=db,
            use_mock=True,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
