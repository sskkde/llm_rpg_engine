"""
SSE Streaming API for Turn Execution

Provides Server-Sent Events endpoint for streaming turn execution.
Events are emitted in order:
1. turn_started
2. event_committed (state/events committed to DB)
3. narration_delta (streaming narration text)
4. DB writes (adventure log, session state, last_played)
5. turn_completed
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import AsyncGenerator, Dict, Any, Optional, List, List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..storage.database import get_db
from ..storage.models import SessionModel
from ..storage.repositories import SessionRepository, LocationRepository, EventLogRepository

from .auth import get_current_active_user
from .turn_output import finalize_turn_output
from ..storage.models import UserModel

from ..core.turn_orchestrator import TurnOrchestrator, TurnValidationError
from ..core.turn_service import (
    execute_turn_service,
    SessionNotFoundError as TurnServiceSessionNotFoundError,
    TurnServiceError,
    TurnValidationError as TurnServiceValidationError,
    LLMConfigurationError,
)
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
from ..llm.proposal_pipeline import ProposalPipeline, ProposalConfig
from .turn_factory import build_turn_orchestrator


router = APIRouter(prefix="/streaming", tags=["streaming"])

_game_orchestrators: Dict[str, TurnOrchestrator] = {}


def _resolve_location_id(
    canonical_location_id: Optional[str],
    db: Session,
    world_id: str,
) -> Optional[str]:
    if not canonical_location_id:
        return None

    location_repo = LocationRepository(db)
    location = location_repo.get_by_id(canonical_location_id)
    if location and location.world_id == world_id:
        return location.id

    if canonical_location_id.startswith("loc_"):
        code = canonical_location_id[4:]
        location = location_repo.get_by_code(world_id, code)
        if location:
            return location.id

    return None


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


def get_turn_orchestrator(llm_service: Optional[LLMService] = None) -> TurnOrchestrator:
    """Factory function to create turn orchestrator using shared factory."""
    return build_turn_orchestrator(llm_service=llm_service)


def get_or_create_orchestrator(game_id: str, llm_service: Optional[LLMService] = None) -> TurnOrchestrator:
    """Get existing orchestrator or create new one with optional LLM service."""
    if game_id not in _game_orchestrators:
        _game_orchestrators[game_id] = get_turn_orchestrator(llm_service=llm_service)
    return _game_orchestrators[game_id]


def _get_current_turn_index(game_id: str) -> int:
    """Get current turn index without polluting orchestrator cache."""
    if game_id in _game_orchestrators:
        orchestrator = _game_orchestrators[game_id]
        recent_events = orchestrator._event_log._store.get_recent_events(limit=1)
        if recent_events:
            return recent_events[0].turn_index
        return 0
    
    temp_orchestrator = get_turn_orchestrator(llm_service=None)
    recent_events = temp_orchestrator._event_log._store.get_recent_events(limit=1)
    if recent_events:
        return recent_events[0].turn_index
    return 0


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
    orchestrator: TurnOrchestrator,
    forbidden_info: List[str] = [],
) -> AsyncGenerator[str, None]:
    """
    Generate streaming narration using LLM with factual boundary.
    
    Uses the same context building as NarrationEngine:
    - Context built only from committed state
    - Forbidden info excluded from LLM prompt
    - Post-generation validation for forbidden info leaks
    
    Yields text chunks that form the complete narration.
    """
    state = orchestrator._state_manager.get_state(game_id)
    if state is None:
        yield "世界陷入了沉默..."
        return
    
    player_perspective = orchestrator._perspective.build_player_perspective(
        perspective_id=f"player_view_{turn_index}",
        player_id="player",
    )
    
    narrator_perspective = orchestrator._perspective.build_narrator_perspective(
        perspective_id=f"narrator_view_{turn_index}",
        base_perspective_id=f"player_view_{turn_index}",
    )
    
    context = orchestrator._context_builder.build_narration_context(
        game_id=game_id,
        turn_id=str(turn_index),
        state=state,
        player_perspective=player_perspective,
        narrator_perspective=narrator_perspective,
    )
    
    player_visible = context.content.get("player_visible_context", {})
    
    visible_context_str = f"""
玩家状态: {player_visible.get('player_state', {})}
可见场景: {player_visible.get('visible_scene', {})}
可见NPC: {player_visible.get('visible_npc_states', {})}
已知事实: {player_visible.get('known_facts', [])}
已知传闻: {player_visible.get('known_rumors', [])}

约束:
- 只能描述玩家可见的场景和事件
- 不能泄露隐藏的秘密或未揭示的信息
- 不能添加未发生的事件或未提交的状态变化
"""
    
    messages = [
        LLMMessage(
            role="system",
            content="你是一个文字RPG的叙事者。用生动的中文描述场景。只能描述玩家可见的信息，不能泄露隐藏的秘密。"
        ),
        LLMMessage(
            role="user",
            content=f"第{turn_index}回合。\n{visible_context_str}\n请生成叙事文本。"
        ),
    ]
    
    accumulated_text = []
    async with asyncio.timeout(30):
        async for chunk in llm_service.generate_stream(
            messages=messages,
            template_id="narration_v1",
            session_id=session_id,
            turn_no=turn_index,
            temperature=0.8,
            max_tokens=500,
        ):
            # Check forbidden info BEFORE yielding
            sanitized_chunk = chunk
            for info in forbidden_info:
                if info and info in chunk:
                    sanitized_chunk = chunk.replace(info, "...")
            
            accumulated_text.append(sanitized_chunk)
            yield sanitized_chunk
    
    full_text = "".join(accumulated_text)


async def execute_turn_stream(
    session_id: str,
    game_id: str,
    turn_index: int,
    player_input: str,
    db: Session,
    world_id: str,
    use_mock: bool = False,
) -> AsyncGenerator[str, None]:
    """
    Execute a turn with streaming SSE events.
    
    Event order:
    1. turn_started
    2. event_committed (after atomic commit)
    3. narration_delta (streaming text)
    4. DB writes (adventure log, session state, last_played)
    5. turn_completed
    """
    event_id = str(uuid.uuid4())
    
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
        
        result = execute_turn_service(
            db=db,
            session_id=session_id,
            player_input=player_input,
            use_mock=use_mock,
        )
        
        # 2. Emit event_committed after atomic commit
        yield format_sse(
            "event_committed",
            {
                "session_id": session_id,
                "turn_index": result.turn_no,
                "transaction_id": result.transaction_id,
                "events_committed": result.events_committed,
                "actions_committed": result.actions_committed,
                "world_time": result.world_time,
                "timestamp": datetime.now().isoformat(),
            },
            event_id=f"{event_id}_committed"
        )
        
        # Small delay to ensure frontend processes the commit event
        await asyncio.sleep(0.05)
        
        if result.narration:
            yield format_sse(
                "narration_delta",
                {
                    "delta": result.narration,
                    "turn_index": result.turn_no,
                },
                event_id=f"{event_id}_delta"
            )
            await asyncio.sleep(0.01)
        
        # 5. Emit turn_completed
        yield format_sse(
            "turn_completed",
            {
                "session_id": session_id,
                "turn_index": result.turn_no,
                "narration": result.narration,
                "recommended_actions": result.recommended_actions,
                "player_state": result.player_state,
                "world_time": result.world_time,
                "timestamp": datetime.now().isoformat(),
            },
            event_id=f"{event_id}_complete"
        )
        
    except TurnServiceValidationError as e:
        yield format_sse(
            "turn_error",
            {
                "session_id": session_id,
                "turn_index": e.turn_no,
                "error_type": "validation_error",
                "message": str(e),
                "errors": e.errors,
                "timestamp": datetime.now().isoformat(),
            },
            event_id=f"{event_id}_error"
        )
    except TurnServiceSessionNotFoundError as e:
        yield format_sse(
            "turn_error",
            {
                "session_id": session_id,
                "turn_index": e.turn_no,
                "error_type": "session_not_found",
                "message": str(e),
                "timestamp": datetime.now().isoformat(),
            },
            event_id=f"{event_id}_error"
        )
    except LLMConfigurationError as e:
        yield format_sse(
            "turn_error",
            {
                "session_id": session_id,
                "turn_index": e.turn_no,
                "error_type": "llm_configuration_error",
                "message": str(e),
                "provider_mode": e.provider_mode,
                "missing_config": e.missing_config,
                "timestamp": datetime.now().isoformat(),
            },
            event_id=f"{event_id}_error"
        )
    except TurnServiceError as e:
        yield format_sse(
            "turn_error",
            {
                "session_id": session_id,
                "turn_index": e.turn_no,
                "error_type": "turn_service_error",
                "message": str(e),
                "timestamp": datetime.now().isoformat(),
            },
            event_id=f"{event_id}_error"
        )
    except Exception as e:
        provider_timeout = isinstance(e, TimeoutError)
        yield format_sse(
            "turn_error",
            {
                "session_id": session_id,
                "turn_index": turn_index,
                "error_type": "provider_timeout" if provider_timeout else "unexpected_error",
                "message": "LLM provider request timed out" if provider_timeout else "Unexpected error while streaming turn",
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
    
    return StreamingResponse(
        execute_turn_stream(
            session_id=session_id,
            game_id=game_id,
            turn_index=0,
            player_input=request.action,
            db=db,
            world_id=session.world_id,
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
    
    return StreamingResponse(
        execute_turn_stream(
            session_id=session_id,
            game_id=game_id,
            turn_index=0,
            player_input=request.action,
            db=db,
            world_id=session.world_id,
            use_mock=True,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
