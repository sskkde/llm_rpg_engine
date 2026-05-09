import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .models import (
    PlayerState,
    WorldState,
    CurrentSceneState,
    WorldTime,
    NPCState,
    NPCProfile,
    PhysicalState,
    MentalState,
)
from .core import (
    EventLog,
    CanonicalStateManager,
    PerspectiveService,
    NPCMemoryManager,
    LoreStore,
    SummaryManager,
    RetrievalSystem,
    ContextBuilder,
    ActionScheduler,
    Validator,
    MemoryWriter,
)
from .engines import WorldEngine, NPCEngine, NarrationEngine
from .api import auth, saves, sessions, game, streaming, world, combat, admin, debug, media


APP_ENV = os.getenv("APP_ENV", "development")
DEFAULT_CORS_ORIGINS = (
    "http://localhost:3005,http://127.0.0.1:3005,"
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:8000,http://127.0.0.1:8000,"
    "https://llm.nas-1.club:18080"
)

app = FastAPI(title="LLM RPG Engine", version="2.0.0")

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class MaintenanceModeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        if path.startswith("/admin") or path.startswith("/auth/login") or path.startswith("/auth/me"):
            return await call_next(request)
        
        if path.startswith("/docs") or path.startswith("/openapi.json") or path.startswith("/redoc"):
            return await call_next(request)
        
        try:
            from .storage.database import get_db
            from .services.settings import SystemSettingsService
            db_gen = get_db()
            db = next(db_gen)
            try:
                settings_service = SystemSettingsService(db)
                settings = settings_service.get_settings()
                if settings.maintenance_mode:
                    return JSONResponse(
                        status_code=503,
                        content={"detail": "System is in maintenance mode"}
                    )
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception:
            pass
        
        return await call_next(request)


app.add_middleware(MaintenanceModeMiddleware)

app.include_router(auth.router)
app.include_router(saves.router)
app.include_router(sessions.router)
app.include_router(game.router)
app.include_router(streaming.router)
app.include_router(world.router)
app.include_router(combat.router)
app.include_router(admin.router)
app.include_router(debug.router)
app.include_router(media.router)



class GameState:
    def __init__(self):
        self.event_log = EventLog()
        self.state_manager = CanonicalStateManager()
        self.perspective_service = PerspectiveService()
        self.npc_memory = NPCMemoryManager()
        self.lore_store = LoreStore()
        self.summary_manager = SummaryManager()
        self.retrieval_system = RetrievalSystem()
        self.context_builder = ContextBuilder(self.retrieval_system, self.perspective_service)
        self.action_scheduler = ActionScheduler()
        self.validator = Validator()
        self.memory_writer = MemoryWriter(self.event_log, self.npc_memory, self.summary_manager)
        
        self.world_engine = WorldEngine(self.state_manager, self.event_log)
        self.npc_engine = NPCEngine(self.state_manager, self.npc_memory, self.perspective_service, self.context_builder)
        self.narration_engine = NarrationEngine(self.state_manager, self.perspective_service, self.context_builder, self.validator)


game_state = GameState()


class Session:
    def __init__(self, session_id: str, game_id: str):
        self.session_id = session_id
        self.game_id = game_id
        self.turn_index = 0
        self.created_at = datetime.now()


sessions: Dict[str, Session] = {}


class InputModel(BaseModel):
    action: str


class TurnResult(BaseModel):
    narrative: str
    recommended_actions: List[str]
    state: dict


if APP_ENV in ("development", "testing"):
    @app.post("/dev/saves", response_model=str)
    def create_save_legacy() -> str:
        """
        DEPRECATED: Legacy dev-only endpoint, not authoritative.

        Use POST /saves for production save creation.
        This endpoint uses in-memory state and is not persisted.
        """
        session_id = str(uuid.uuid4())
        game_id = f"game_{session_id[:8]}"
        
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
        
        game_state.state_manager.initialize_game(
            game_id=game_id,
            player_state=player_state,
            world_state=world_state,
            scene_state=scene_state,
        )
        
        session = Session(session_id, game_id)
        sessions[session_id] = session
        
        return session_id
    
    @app.get("/dev/saves", response_model=List[str])
    def list_saves_legacy() -> List[str]:
        """DEPRECATED: Legacy dev-only endpoint. Use GET /saves."""
        return list(sessions.keys())
    
    @app.get("/dev/sessions/{session_id}/snapshot")
    def get_snapshot_legacy(session_id: str) -> dict:
        """
        DEPRECATED: Legacy dev-only endpoint, not authoritative.

        Use GET /sessions/{session_id}/snapshot for production.
        This endpoint uses in-memory state and is not persisted.
        """
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        state = game_state.state_manager.get_state(session.game_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Game state not found")
        
        return {
            "player_state": state.player_state.model_dump(),
            "world_state": state.world_state.model_dump(),
            "scene_state": state.current_scene_state.model_dump(),
        }
    
    @app.post("/dev/sessions/{session_id}/turn", response_model=TurnResult)
    def perform_turn_legacy(session_id: str, inp: InputModel) -> TurnResult:
        """
        DEPRECATED: Legacy dev-only endpoint, not authoritative.

        Use POST /game/sessions/{session_id}/turn for production.
        This endpoint uses in-memory state and bypasses execute_turn_service().
        """
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session.turn_index += 1
        
        state = game_state.state_manager.get_state(session.game_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Game state not found")
        
        world_event = game_state.world_engine.advance_time(session.game_id)
        
        game_state.event_log.record_event(
            transaction=game_state.event_log.start_turn(
                session_id=session.session_id,
                game_id=session.game_id,
                turn_index=session.turn_index,
                player_input=inp.action,
                world_time_before=world_event.time_before,
            ),
            event=world_event,
        )
        
        narrative = game_state.narration_engine.generate_narration(
            game_id=session.game_id,
            turn_index=session.turn_index,
            player_perspective=game_state.perspective_service.build_player_perspective(
                perspective_id="player_view",
                player_id="player",
            ),
            narrator_perspective=game_state.perspective_service.build_narrator_perspective(
                perspective_id="narrator_view",
                base_perspective_id="player_view",
            ),
        )
        
        recommended = [
            "观察四周",
            "与人交谈",
            "探索环境",
        ]
        
        return TurnResult(
            narrative=narrative,
            recommended_actions=recommended,
            state={
                "player_state": state.player_state.model_dump(),
                "world_state": state.world_state.model_dump(),
            },
        )

    @app.get("/dev/sessions/{session_id}/logs")
    def get_logs_legacy(session_id: str) -> List[str]:
        """DEPRECATED: Legacy dev-only endpoint. Use GET /debug/sessions/{session_id}/logs."""
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        events = game_state.event_log.get_session_events(session_id, limit=50)
        return [f"[{e.event_type}] {e.event_id}" for e in events]
