"""
Debug API routes for LLM RPG Engine.

Provides debugging and logging endpoints for monitoring sessions,
viewing state snapshots, and auditing system behavior.
All endpoints require admin role authentication.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import desc

from ..storage.database import get_db
from ..storage.models import (
    UserModel, SessionModel, EventLogModel, ModelCallLogModel,
    SessionStateModel, SessionPlayerStateModel, SessionNPCStateModel,
    SessionInventoryItemModel, SessionQuestStateModel
)
from ..storage.repositories import (
    SessionRepository, EventLogRepository, ModelCallLogRepository,
    SessionStateRepository, SessionPlayerStateRepository, SessionNPCStateRepository,
    SessionInventoryItemRepository, SessionQuestStateRepository
)
from ..core.audit import (
    get_audit_logger, AuditLogger, ContextBuildAudit, ValidationResultAudit,
    TurnAuditLog, ModelCallLog, ErrorLogEntry, MemoryAuditEntry,
    ValidationCheck, ValidationStatus, ErrorSeverity
)
from ..core.replay import (
    get_replay_store, ReplayStore, ReplayResult, ReplayStep, ReplayEvent,
    StateSnapshot, ReplayPerspective, ReplayError
)
from ..observability.timeline import TimelineViewer, TurnTimeline, TimelineEntry
from ..observability.npc_mind import NPCMindViewer, NPCMindView, ViewRole
from .auth import get_current_active_user

router = APIRouter(prefix="/debug", tags=["debug"])


async def require_debug_admin(
    current_user: UserModel = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
) -> UserModel:
    from ..services.settings import SystemSettingsService
    settings_service = SystemSettingsService(db)
    settings = settings_service.get_settings()
    
    if not settings.debug_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Debug endpoints are disabled"
        )
    
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for debug endpoints"
        )
    return current_user


class DebugSessionLogEntry(BaseModel):
    id: str
    turn_no: int
    event_type: str
    input_text: Optional[str] = None
    structured_action: Optional[Dict[str, Any]] = None
    result_json: Optional[Dict[str, Any]] = None
    narrative_text: Optional[str] = None
    occurred_at: datetime

    class Config:
        from_attributes = True


class DebugSessionLogsResponse(BaseModel):
    session_id: str
    total_count: int
    logs: List[DebugSessionLogEntry]


class DebugNPCState(BaseModel):
    id: str
    npc_template_id: str
    npc_name: str
    current_location_id: Optional[str] = None
    trust_score: int
    suspicion_score: int
    status_flags: Dict[str, Any]
    short_memory_summary: Optional[str] = None
    hidden_plan_state: Optional[str] = None


class DebugInventoryItem(BaseModel):
    id: str
    item_template_id: str
    item_name: str
    owner_type: str
    owner_ref_id: Optional[str] = None
    quantity: int
    durability: Optional[int] = None
    bound_flag: bool


class DebugQuestState(BaseModel):
    id: str
    quest_template_id: str
    quest_name: str
    current_step_no: int
    progress: Dict[str, Any]
    status: str
    last_updated_at: datetime


class DebugSessionStateResponse(BaseModel):
    session_id: str
    user_id: str
    world_id: str
    current_chapter_id: Optional[str] = None
    status: str
    started_at: datetime
    last_played_at: datetime

    # Session State
    current_time: Optional[str] = None
    time_phase: Optional[str] = None
    current_location_id: Optional[str] = None
    active_mode: str
    global_flags: Dict[str, Any]

    # Player State
    player_realm_stage: str
    player_hp: int
    player_max_hp: int
    player_stamina: int
    player_spirit_power: int
    player_relation_bias: Dict[str, Any]
    player_conditions: List[str]

    # Related States
    npc_states: List[DebugNPCState]
    inventory_items: List[DebugInventoryItem]
    quest_states: List[DebugQuestState]


class DebugModelCallEntry(BaseModel):
    id: str
    session_id: str
    turn_no: int
    provider: Optional[str] = None
    model_name: Optional[str] = None
    prompt_type: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_estimate: Optional[float] = None
    latency_ms: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DebugModelCallsResponse(BaseModel):
    total_count: int
    total_cost: float
    calls: List[DebugModelCallEntry]


class DebugErrorEntry(BaseModel):
    timestamp: datetime
    error_type: str
    message: str
    details: Optional[Dict[str, Any]] = None


class DebugErrorsResponse(BaseModel):
    total_count: int
    errors: List[DebugErrorEntry]


# Audit Response Models
class MemoryAuditResponse(BaseModel):
    memory_id: str
    memory_type: str
    owner_id: str
    included: bool
    reason: str
    relevance_score: Optional[float] = None
    importance_score: Optional[float] = None
    recency_score: Optional[float] = None
    perspective_filter_applied: bool = False
    forbidden_knowledge_flag: bool = False
    notes: Optional[str] = None


class ContextBuildAuditResponse(BaseModel):
    build_id: str
    session_id: str
    turn_no: int
    perspective_type: str
    perspective_id: str
    owner_id: Optional[str] = None
    included_memories: List[MemoryAuditResponse]
    excluded_memories: List[MemoryAuditResponse]
    total_candidates: int
    included_count: int
    excluded_count: int
    context_token_count: int
    context_char_count: int
    build_duration_ms: int
    created_at: datetime


class ValidationCheckResponse(BaseModel):
    check_id: str
    check_type: str
    status: str
    message: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class ValidationResultAuditResponse(BaseModel):
    validation_id: str
    session_id: str
    turn_no: int
    validation_target: str
    target_id: Optional[str] = None
    overall_status: str
    checks: List[ValidationCheckResponse]
    error_count: int
    warning_count: int
    errors: List[str]
    warnings: List[str]
    transaction_id: Optional[str] = None
    created_at: datetime


class StateDeltaAuditResponse(BaseModel):
    delta_id: str
    path: str
    old_value: Any
    new_value: Any
    operation: str
    validated: bool


class TurnEventAuditResponse(BaseModel):
    event_id: str
    event_type: str
    actor_id: Optional[str] = None
    summary: Optional[str] = None


class TurnDebugResponse(BaseModel):
    audit_id: str
    session_id: str
    turn_no: int
    transaction_id: str
    player_input: str
    parsed_intent: Optional[Dict[str, Any]] = None
    world_time_before: Dict[str, Any]
    world_time_after: Optional[Dict[str, Any]] = None
    events: List[TurnEventAuditResponse]
    state_deltas: List[StateDeltaAuditResponse]
    context_build_ids: List[str]
    model_call_ids: List[str]
    validation_ids: List[str]
    status: str
    narration_generated: bool
    narration_length: int
    turn_duration_ms: Optional[int] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class ReplayEventResponse(BaseModel):
    event_id: str
    event_type: str
    turn_no: int
    timestamp: datetime
    actor_id: Optional[str] = None
    summary: Optional[str] = None
    visible_to_player: bool = True
    data: Dict[str, Any] = Field(default_factory=dict)


class ReplayStepResponse(BaseModel):
    step_no: int
    turn_no: int
    player_input: Optional[str] = None
    state_before: Dict[str, Any]
    state_after: Dict[str, Any]
    events: List[ReplayEventResponse]
    state_deltas: List[Dict[str, Any]]
    duration_ms: Optional[int] = None
    timestamp: datetime


class ReplayResultResponse(BaseModel):
    replay_id: str
    session_id: str
    start_turn: int
    end_turn: int
    perspective: str
    steps: List[ReplayStepResponse]
    final_state: Dict[str, Any]
    total_steps: int
    total_events: int
    total_state_deltas: int
    success: bool
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    replay_duration_ms: Optional[int] = None


class SnapshotResponse(BaseModel):
    snapshot_id: str
    session_id: str
    turn_no: int
    world_state: Dict[str, Any]
    player_state: Dict[str, Any]
    npc_states: Dict[str, Dict[str, Any]]
    location_states: Dict[str, Dict[str, Any]]
    quest_states: Dict[str, Dict[str, Any]]
    faction_states: Dict[str, Dict[str, Any]]
    created_at: datetime
    snapshot_type: str


def require_admin_role(user: UserModel) -> None:
    """Verify user has admin role for debug access."""
    pass


@router.get("/sessions/{session_id}/logs", response_model=DebugSessionLogsResponse)
def get_session_logs(
    session_id: str,
    limit: int = Query(100, ge=1, le=1000),
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get session event logs.

    Returns event logs for a specific session with full details.
    Requires admin role.
    """
    require_admin_role(current_user)

    # Verify session exists
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Get event logs
    logs = db.query(EventLogModel).filter(
        EventLogModel.session_id == session_id
    ).order_by(desc(EventLogModel.turn_no), desc(EventLogModel.occurred_at)).limit(limit).all()

    return DebugSessionLogsResponse(
        session_id=session_id,
        total_count=len(logs),
        logs=[DebugSessionLogEntry.model_validate(log) for log in logs]
    )


@router.get("/sessions/{session_id}/state", response_model=DebugSessionStateResponse)
def get_session_state(
    session_id: str,
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get complete session state snapshot.

    Returns full session state including player, NPCs, inventory, and quests.
    Requires admin role.
    """
    require_admin_role(current_user)

    # Get session
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Get session state
    session_state = db.query(SessionStateModel).filter(
        SessionStateModel.session_id == session_id
    ).first()

    # Get player state
    player_state = db.query(SessionPlayerStateModel).filter(
        SessionPlayerStateModel.session_id == session_id
    ).first()

    # Get NPC states with names
    npc_states_raw = db.query(SessionNPCStateModel).filter(
        SessionNPCStateModel.session_id == session_id
    ).all()

    npc_states = []
    for npc in npc_states_raw:
        npc_name = npc.npc_template.name if npc.npc_template else "Unknown"
        npc_states.append(DebugNPCState(
            id=npc.id,
            npc_template_id=npc.npc_template_id,
            npc_name=npc_name,
            current_location_id=npc.current_location_id,
            trust_score=npc.trust_score,
            suspicion_score=npc.suspicion_score,
            status_flags=npc.status_flags or {},
            short_memory_summary=npc.short_memory_summary,
            hidden_plan_state=npc.hidden_plan_state
        ))

    # Get inventory items with names
    inventory_raw = db.query(SessionInventoryItemModel).filter(
        SessionInventoryItemModel.session_id == session_id
    ).all()

    inventory_items = []
    for item in inventory_raw:
        item_name = item.item_template.name if item.item_template else "Unknown"
        inventory_items.append(DebugInventoryItem(
            id=item.id,
            item_template_id=item.item_template_id,
            item_name=item_name,
            owner_type=item.owner_type,
            owner_ref_id=item.owner_ref_id,
            quantity=item.quantity,
            durability=item.durability,
            bound_flag=item.bound_flag
        ))

    # Get quest states with names
    quest_states_raw = db.query(SessionQuestStateModel).filter(
        SessionQuestStateModel.session_id == session_id
    ).all()

    quest_states = []
    for quest in quest_states_raw:
        quest_name = quest.quest_template.name if quest.quest_template else "Unknown"
        quest_states.append(DebugQuestState(
            id=quest.id,
            quest_template_id=quest.quest_template_id,
            quest_name=quest_name,
            current_step_no=quest.current_step_no,
            progress=quest.progress_json or {},
            status=quest.status,
            last_updated_at=quest.last_updated_at
        ))

    return DebugSessionStateResponse(
        session_id=session_id,
        user_id=session.user_id,
        world_id=session.world_id,
        current_chapter_id=session.current_chapter_id,
        status=session.status,
        started_at=session.started_at,
        last_played_at=session.last_played_at,
        current_time=session_state.current_time if session_state else None,
        time_phase=session_state.time_phase if session_state else None,
        current_location_id=session_state.current_location_id if session_state else None,
        active_mode=session_state.active_mode if session_state else "exploration",
        global_flags=session_state.global_flags_json if session_state else {},
        player_realm_stage=player_state.realm_stage if player_state else "炼气一层",
        player_hp=player_state.hp if player_state else 100,
        player_max_hp=player_state.max_hp if player_state else 100,
        player_stamina=player_state.stamina if player_state else 100,
        player_spirit_power=player_state.spirit_power if player_state else 100,
        player_relation_bias=player_state.relation_bias_json if player_state else {},
        player_conditions=player_state.conditions_json if player_state else [],
        npc_states=npc_states,
        inventory_items=inventory_items,
        quest_states=quest_states
    )


@router.get("/model-calls", response_model=DebugModelCallsResponse)
def get_model_calls(
    session_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get model call summaries.

    Returns audit logs of LLM calls with token usage and costs.
    Optionally filter by session_id.
    Requires admin role.
    """
    require_admin_role(current_user)

    query = db.query(ModelCallLogModel)

    if session_id:
        query = query.filter(ModelCallLogModel.session_id == session_id)

    calls = query.order_by(desc(ModelCallLogModel.created_at)).limit(limit).all()

    total_cost = sum(call.cost_estimate or 0 for call in calls)

    return DebugModelCallsResponse(
        total_count=len(calls),
        total_cost=total_cost,
        calls=[DebugModelCallEntry.model_validate(call) for call in calls]
    )


@router.get("/errors", response_model=DebugErrorsResponse)
def get_recent_errors(
    limit: int = Query(50, ge=1, le=500),
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get recent errors.

    Returns recent system errors from event logs.
    Requires admin role.
    """
    require_admin_role(current_user)

    # Query for error-type events in event logs
    # Since we don't have a dedicated error log table, we look for error events
    error_logs = db.query(EventLogModel).filter(
        EventLogModel.event_type.in_(["error", "validation_error", "system_error"])
    ).order_by(desc(EventLogModel.occurred_at)).limit(limit).all()

    errors = []
    for log in error_logs:
        error_data = DebugErrorEntry(
            timestamp=log.occurred_at,
            error_type=log.event_type,
            message=log.narrative_text or "Unknown error",
            details=log.result_json
        )
        errors.append(error_data)

    # If no error events found, return empty list
    return DebugErrorsResponse(
        total_count=len(errors),
        errors=errors
    )


@router.get("/sessions/{session_id}/turns/{turn_no}", response_model=TurnDebugResponse)
def get_turn_debug(
    session_id: str,
    turn_no: int,
    current_user: UserModel = Depends(require_debug_admin),
):
    """
    Get detailed debug information for a specific turn.

    Returns turn audit data including:
    - Context build IDs
    - Included/excluded memory IDs with reasons
    - Validation checks
    - Model call IDs
    - State delta IDs

    Requires admin role.
    """
    require_admin_role(current_user)

    audit_logger = get_audit_logger()
    store = audit_logger.get_store()

    turn_audit = store.get_turn_audit_by_turn(session_id, turn_no)

    if not turn_audit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Turn audit not found for session {session_id}, turn {turn_no}"
        )

    return TurnDebugResponse(
        audit_id=turn_audit.audit_id,
        session_id=turn_audit.session_id,
        turn_no=turn_audit.turn_no,
        transaction_id=turn_audit.transaction_id,
        player_input=turn_audit.player_input,
        parsed_intent=turn_audit.parsed_intent,
        world_time_before=turn_audit.world_time_before,
        world_time_after=turn_audit.world_time_after,
        events=[
            TurnEventAuditResponse(
                event_id=e.event_id,
                event_type=e.event_type,
                actor_id=e.actor_id,
                summary=e.summary,
            )
            for e in turn_audit.events
        ],
        state_deltas=[
            StateDeltaAuditResponse(
                delta_id=d.delta_id,
                path=d.path,
                old_value=d.old_value,
                new_value=d.new_value,
                operation=d.operation,
                validated=d.validated,
            )
            for d in turn_audit.state_deltas
        ],
        context_build_ids=turn_audit.context_build_ids,
        model_call_ids=turn_audit.model_call_ids,
        validation_ids=turn_audit.validation_ids,
        status=turn_audit.status,
        narration_generated=turn_audit.narration_generated,
        narration_length=turn_audit.narration_length,
        turn_duration_ms=turn_audit.turn_duration_ms,
        started_at=turn_audit.started_at,
        completed_at=turn_audit.completed_at,
    )


@router.get("/sessions/{session_id}/context-builds/{build_id}", response_model=ContextBuildAuditResponse)
def get_context_build_audit(
    session_id: str,
    build_id: str,
    current_user: UserModel = Depends(require_debug_admin),
):
    """
    Get context build audit details.

    Returns memory inclusion/exclusion decisions with reasons.
    Requires admin role.
    """
    require_admin_role(current_user)

    audit_logger = get_audit_logger()
    store = audit_logger.get_store()

    build_audit = store.get_context_build(build_id)

    if not build_audit or build_audit.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Context build audit not found: {build_id}"
        )

    return ContextBuildAuditResponse(
        build_id=build_audit.build_id,
        session_id=build_audit.session_id,
        turn_no=build_audit.turn_no,
        perspective_type=build_audit.perspective_type,
        perspective_id=build_audit.perspective_id,
        owner_id=build_audit.owner_id,
        included_memories=[
            MemoryAuditResponse(
                memory_id=m.memory_id,
                memory_type=m.memory_type,
                owner_id=m.owner_id,
                included=m.included,
                reason=m.reason.value,
                relevance_score=m.relevance_score,
                importance_score=m.importance_score,
                recency_score=m.recency_score,
                perspective_filter_applied=m.perspective_filter_applied,
                forbidden_knowledge_flag=m.forbidden_knowledge_flag,
                notes=m.notes,
            )
            for m in build_audit.included_memories
        ],
        excluded_memories=[
            MemoryAuditResponse(
                memory_id=m.memory_id,
                memory_type=m.memory_type,
                owner_id=m.owner_id,
                included=m.included,
                reason=m.reason.value,
                relevance_score=m.relevance_score,
                importance_score=m.importance_score,
                recency_score=m.recency_score,
                perspective_filter_applied=m.perspective_filter_applied,
                forbidden_knowledge_flag=m.forbidden_knowledge_flag,
                notes=m.notes,
            )
            for m in build_audit.excluded_memories
        ],
        total_candidates=build_audit.total_candidates,
        included_count=build_audit.included_count,
        excluded_count=build_audit.excluded_count,
        context_token_count=build_audit.context_token_count,
        context_char_count=build_audit.context_char_count,
        build_duration_ms=build_audit.build_duration_ms,
        created_at=build_audit.created_at,
    )


@router.get("/sessions/{session_id}/validations/{validation_id}", response_model=ValidationResultAuditResponse)
def get_validation_audit(
    session_id: str,
    validation_id: str,
    current_user: UserModel = Depends(require_debug_admin),
):
    """
    Get validation result audit details.

    Returns validation checks and results.
    Requires admin role.
    """
    require_admin_role(current_user)

    audit_logger = get_audit_logger()
    store = audit_logger.get_store()

    validation_audit = store.get_validation(validation_id)

    if not validation_audit or validation_audit.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Validation audit not found: {validation_id}"
        )

    return ValidationResultAuditResponse(
        validation_id=validation_audit.validation_id,
        session_id=validation_audit.session_id,
        turn_no=validation_audit.turn_no,
        validation_target=validation_audit.validation_target,
        target_id=validation_audit.target_id,
        overall_status=validation_audit.overall_status.value,
        checks=[
            ValidationCheckResponse(
                check_id=c.check_id,
                check_type=c.check_type,
                status=c.status.value,
                message=c.message,
                details=c.details,
            )
            for c in validation_audit.checks
        ],
        error_count=validation_audit.error_count,
        warning_count=validation_audit.warning_count,
        errors=validation_audit.errors,
        warnings=validation_audit.warnings,
        transaction_id=validation_audit.transaction_id,
        created_at=validation_audit.created_at,
    )


@router.post("/sessions/{session_id}/replay", response_model=ReplayResultResponse)
def replay_session_turns(
    session_id: str,
    start_turn: int = Query(1, ge=1),
    end_turn: int = Query(..., ge=1),
    perspective: str = Query("admin", regex="^(admin|player|auditor)$"),
    snapshot_id: Optional[str] = None,
    current_user: UserModel = Depends(require_debug_admin),
):
    """
    Replay session turns.

    Reconstructs state by replaying events from start_turn to end_turn.
    Perspective controls what information is visible:
    - admin: Full access, sees hidden info
    - player: Player view, no hidden info
    - auditor: Audit view, sees audit data but not hidden lore

    Requires admin role.
    """
    require_admin_role(current_user)

    replay_store = get_replay_store()
    replay_engine = replay_store.get_replay_engine()

    replay_perspective = ReplayPerspective(perspective)

    # Create mock events for testing/demo purposes
    # In production, this would fetch from event log
    mock_events = []
    for turn in range(start_turn, end_turn + 1):
        mock_events.append(ReplayEvent(
            event_id=f"evt_input_{turn:06d}",
            event_type="player_input",
            turn_no=turn,
            timestamp=datetime.now(),
            actor_id="player",
            summary=f"Player input for turn {turn}",
            visible_to_player=True,
            data={"raw_input": f"Test input turn {turn}"},
        ))

    try:
        if snapshot_id:
            result = replay_engine.replay_from_snapshot(
                session_id=session_id,
                snapshot_id=snapshot_id,
                target_turn=end_turn,
                events=mock_events,
                perspective=replay_perspective,
            )
        else:
            result = replay_engine.replay_turn_range(
                session_id=session_id,
                start_turn=start_turn,
                end_turn=end_turn,
                events=mock_events,
                perspective=replay_perspective,
            )

        return ReplayResultResponse(
            replay_id=result.replay_id,
            session_id=result.session_id,
            start_turn=result.start_turn,
            end_turn=result.end_turn,
            perspective=result.perspective.value,
            steps=[
                ReplayStepResponse(
                    step_no=s.step_no,
                    turn_no=s.turn_no,
                    player_input=s.player_input,
                    state_before=s.state_before,
                    state_after=s.state_after,
                    events=[
                        ReplayEventResponse(
                            event_id=e.event_id,
                            event_type=e.event_type,
                            turn_no=e.turn_no,
                            timestamp=e.timestamp,
                            actor_id=e.actor_id,
                            summary=e.summary,
                            visible_to_player=e.visible_to_player,
                            data=e.data,
                        )
                        for e in s.events
                    ],
                    state_deltas=s.state_deltas,
                    duration_ms=s.duration_ms,
                    timestamp=s.timestamp,
                )
                for s in result.steps
            ],
            final_state=result.final_state,
            total_steps=result.total_steps,
            total_events=result.total_events,
            total_state_deltas=result.total_state_deltas,
            success=result.success,
            error_message=result.error_message,
            started_at=result.started_at,
            completed_at=result.completed_at,
            replay_duration_ms=result.replay_duration_ms,
        )
    except ReplayError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/sessions/{session_id}/snapshots", response_model=SnapshotResponse)
def create_state_snapshot(
    session_id: str,
    turn_no: int,
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db),
):
    """
    Create a state snapshot for replay.

    Captures current game state at the specified turn.
    Requires admin role.
    """
    require_admin_role(current_user)

    # Verify session exists
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Get session state
    session_state = db.query(SessionStateModel).filter(
        SessionStateModel.session_id == session_id
    ).first()

    player_state = db.query(SessionPlayerStateModel).filter(
        SessionPlayerStateModel.session_id == session_id
    ).first()

    npc_states_raw = db.query(SessionNPCStateModel).filter(
        SessionNPCStateModel.session_id == session_id
    ).all()

    npc_states = {}
    for npc in npc_states_raw:
        npc_states[npc.npc_template_id] = {
            "id": npc.id,
            "npc_template_id": npc.npc_template_id,
            "current_location_id": npc.current_location_id,
            "trust_score": npc.trust_score,
            "suspicion_score": npc.suspicion_score,
            "status_flags": npc.status_flags or {},
            "short_memory_summary": npc.short_memory_summary,
            "hidden_plan_state": npc.hidden_plan_state,
        }

    replay_store = get_replay_store()
    snapshot = replay_store.create_snapshot(
        session_id=session_id,
        turn_no=turn_no,
        world_state={
            "current_time": session_state.current_time if session_state else None,
            "time_phase": session_state.time_phase if session_state else None,
            "current_location_id": session_state.current_location_id if session_state else None,
            "active_mode": session_state.active_mode if session_state else "exploration",
            "global_flags": session_state.global_flags_json if session_state else {},
        },
        player_state={
            "realm_stage": player_state.realm_stage if player_state else "炼气一层",
            "hp": player_state.hp if player_state else 100,
            "max_hp": player_state.max_hp if player_state else 100,
            "stamina": player_state.stamina if player_state else 100,
            "spirit_power": player_state.spirit_power if player_state else 100,
            "relation_bias": player_state.relation_bias_json if player_state else {},
            "conditions": player_state.conditions_json if player_state else [],
        },
        npc_states=npc_states,
    )

    return SnapshotResponse(
        snapshot_id=snapshot.snapshot_id,
        session_id=snapshot.session_id,
        turn_no=snapshot.turn_no,
        world_state=snapshot.world_state,
        player_state=snapshot.player_state,
        npc_states=snapshot.npc_states,
        location_states=snapshot.location_states,
        quest_states=snapshot.quest_states,
        faction_states=snapshot.faction_states,
        created_at=snapshot.created_at,
        snapshot_type=snapshot.snapshot_type,
    )


class TimelineEntryResponse(BaseModel):
    entry_id: str
    entry_type: str
    turn_no: int
    timestamp: datetime
    data: Dict[str, Any]

    class Config:
        from_attributes = True


class TurnTimelineResponse(BaseModel):
    turn_no: int
    session_id: str
    transaction_id: Optional[str] = None
    player_input: Optional[str] = None
    world_time_before: Optional[Dict[str, Any]] = None
    world_time_after: Optional[Dict[str, Any]] = None
    entries: List[TimelineEntryResponse]
    event_ids: List[str]
    state_delta_ids: List[str]
    model_call_ids: List[str]
    context_build_ids: List[str]
    validation_ids: List[str]
    summary_ids: List[str]
    status: str
    narration_generated: bool
    narration_length: int
    turn_duration_ms: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TimelineResponse(BaseModel):
    session_id: str
    total_turns: int
    turns: List[TurnTimelineResponse]

    class Config:
        from_attributes = True


class NPCBeliefResponse(BaseModel):
    belief_id: str
    subject: str
    belief_text: str
    confidence: float
    source_event_id: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NPCMemoryResponse(BaseModel):
    memory_id: str
    memory_type: str
    content: str
    importance_score: float
    recency_score: float
    source_event_id: Optional[str] = None
    created_at: Optional[datetime] = None
    is_private: bool

    class Config:
        from_attributes = True


class NPCGoalResponse(BaseModel):
    goal_id: str
    goal_text: str
    priority: int
    status: str
    progress: float

    class Config:
        from_attributes = True


class NPCSecretResponse(BaseModel):
    secret_id: str
    secret_type: str
    description: str
    is_revealed: bool
    revealed_to: List[str]

    class Config:
        from_attributes = True


class NPCForbiddenKnowledgeResponse(BaseModel):
    knowledge_id: str
    knowledge_type: str
    description: str
    source: Optional[str] = None

    class Config:
        from_attributes = True


class NPCRecentContextResponse(BaseModel):
    recent_memories: List[NPCMemoryResponse]
    recent_interactions: List[Dict[str, Any]]
    current_focus: Optional[str] = None
    emotional_state: Optional[str] = None

    class Config:
        from_attributes = True


class NPCMindProfileResponse(BaseModel):
    npc_id: str
    npc_template_id: str
    npc_name: str
    public_identity: Optional[str] = None
    hidden_identity: Optional[str] = None
    personality: Optional[str] = None
    speech_style: Optional[str] = None
    role_type: Optional[str] = None

    class Config:
        from_attributes = True


class NPCMindStateResponse(BaseModel):
    current_location_id: Optional[str] = None
    trust_score: int
    suspicion_score: int
    status_flags: Dict[str, Any]
    short_memory_summary: Optional[str] = None
    hidden_plan_state: Optional[str] = None

    class Config:
        from_attributes = True


class NPCMindViewResponse(BaseModel):
    npc_id: str
    session_id: str
    profile: NPCMindProfileResponse
    state: NPCMindStateResponse
    beliefs: List[NPCBeliefResponse]
    memories: List[NPCMemoryResponse]
    private_memories: List[NPCMemoryResponse]
    recent_context: NPCRecentContextResponse
    goals: List[NPCGoalResponse]
    secrets: List[NPCSecretResponse]
    forbidden_knowledge: List[NPCForbiddenKnowledgeResponse]
    secrets_metadata: Dict[str, Any]
    viewed_at: datetime
    view_role: str

    class Config:
        from_attributes = True


class NPCListResponse(BaseModel):
    npcs: List[Dict[str, Any]]
    total: int

    class Config:
        from_attributes = True


@router.get("/sessions/{session_id}/timeline", response_model=TimelineResponse)
def get_session_timeline(
    session_id: str,
    start_turn: int = Query(1, ge=1),
    end_turn: Optional[int] = Query(None, ge=1),
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db)
):
    require_admin_role(current_user)

    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    viewer = TimelineViewer(db_session=db)
    turns = viewer.get_timeline(session_id, start_turn, end_turn)

    return TimelineResponse(
        session_id=session_id,
        total_turns=len(turns),
        turns=[
            TurnTimelineResponse(
                turn_no=t.turn_no,
                session_id=t.session_id,
                transaction_id=t.transaction_id,
                player_input=t.player_input,
                world_time_before=t.world_time_before,
                world_time_after=t.world_time_after,
                entries=[
                    TimelineEntryResponse(
                        entry_id=e.entry_id,
                        entry_type=e.entry_type.value,
                        turn_no=e.turn_no,
                        timestamp=e.timestamp,
                        data=e.data,
                    )
                    for e in t.entries
                ],
                event_ids=t.event_ids,
                state_delta_ids=t.state_delta_ids,
                model_call_ids=t.model_call_ids,
                context_build_ids=t.context_build_ids,
                validation_ids=t.validation_ids,
                summary_ids=t.summary_ids,
                status=t.status,
                narration_generated=t.narration_generated,
                narration_length=t.narration_length,
                turn_duration_ms=t.turn_duration_ms,
                started_at=t.started_at,
                completed_at=t.completed_at,
            )
            for t in turns
        ],
    )


@router.get("/sessions/{session_id}/timeline/{turn_no}", response_model=TurnTimelineResponse)
def get_turn_timeline(
    session_id: str,
    turn_no: int,
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db)
):
    require_admin_role(current_user)

    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    viewer = TimelineViewer(db_session=db)
    turn = viewer.get_turn_summary(session_id, turn_no)

    if not turn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Turn {turn_no} not found"
        )

    return TurnTimelineResponse(
        turn_no=turn.turn_no,
        session_id=turn.session_id,
        transaction_id=turn.transaction_id,
        player_input=turn.player_input,
        world_time_before=turn.world_time_before,
        world_time_after=turn.world_time_after,
        entries=[
            TimelineEntryResponse(
                entry_id=e.entry_id,
                entry_type=e.entry_type.value,
                turn_no=e.turn_no,
                timestamp=e.timestamp,
                data=e.data,
            )
            for e in turn.entries
        ],
        event_ids=turn.event_ids,
        state_delta_ids=turn.state_delta_ids,
        model_call_ids=turn.model_call_ids,
        context_build_ids=turn.context_build_ids,
        validation_ids=turn.validation_ids,
        summary_ids=turn.summary_ids,
        status=turn.status,
        narration_generated=turn.narration_generated,
        narration_length=turn.narration_length,
        turn_duration_ms=turn.turn_duration_ms,
        started_at=turn.started_at,
        completed_at=turn.completed_at,
    )


@router.get("/sessions/{session_id}/npcs", response_model=NPCListResponse)
def list_session_npcs(
    session_id: str,
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db)
):
    require_admin_role(current_user)

    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    viewer = NPCMindViewer(db_session=db)
    npcs = viewer.list_session_npcs(session_id)

    return NPCListResponse(
        npcs=npcs,
        total=len(npcs),
    )


@router.get("/sessions/{session_id}/npcs/{npc_id}/mind", response_model=NPCMindViewResponse)
def get_npc_mind(
    session_id: str,
    npc_id: str,
    role: str = Query("debug", regex="^(player|admin|debug|auditor)$"),
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db)
):
    view_role = ViewRole(role)

    if view_role == ViewRole.PLAYER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Player role cannot view NPC mind directly"
        )

    require_admin_role(current_user)

    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    viewer = NPCMindViewer(db_session=db)

    if not viewer.can_view_mind(view_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"View role '{role}' not authorized for NPC mind viewing"
        )

    mind_view = viewer.get_npc_mind(session_id, npc_id, view_role)

    if not mind_view:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NPC {npc_id} not found in session"
        )

    return NPCMindViewResponse(
        npc_id=mind_view.npc_id,
        session_id=mind_view.session_id,
        profile=NPCMindProfileResponse(
            npc_id=mind_view.profile.npc_id,
            npc_template_id=mind_view.profile.npc_template_id,
            npc_name=mind_view.profile.npc_name,
            public_identity=mind_view.profile.public_identity,
            hidden_identity=mind_view.profile.hidden_identity,
            personality=mind_view.profile.personality,
            speech_style=mind_view.profile.speech_style,
            role_type=mind_view.profile.role_type,
        ),
        state=NPCMindStateResponse(
            current_location_id=mind_view.state.current_location_id,
            trust_score=mind_view.state.trust_score,
            suspicion_score=mind_view.state.suspicion_score,
            status_flags=mind_view.state.status_flags,
            short_memory_summary=mind_view.state.short_memory_summary,
            hidden_plan_state=mind_view.state.hidden_plan_state,
        ),
        beliefs=[
            NPCBeliefResponse(
                belief_id=b.belief_id,
                subject=b.subject,
                belief_text=b.belief_text,
                confidence=b.confidence,
                source_event_id=b.source_event_id,
                created_at=b.created_at,
            )
            for b in mind_view.beliefs
        ],
        memories=[
            NPCMemoryResponse(
                memory_id=m.memory_id,
                memory_type=m.memory_type,
                content=m.content,
                importance_score=m.importance_score,
                recency_score=m.recency_score,
                source_event_id=m.source_event_id,
                created_at=m.created_at,
                is_private=m.is_private,
            )
            for m in mind_view.memories
        ],
        private_memories=[
            NPCMemoryResponse(
                memory_id=m.memory_id,
                memory_type=m.memory_type,
                content=m.content,
                importance_score=m.importance_score,
                recency_score=m.recency_score,
                source_event_id=m.source_event_id,
                created_at=m.created_at,
                is_private=m.is_private,
            )
            for m in mind_view.private_memories
        ],
        recent_context=NPCRecentContextResponse(
            recent_memories=[
                NPCMemoryResponse(
                    memory_id=m.memory_id,
                    memory_type=m.memory_type,
                    content=m.content,
                    importance_score=m.importance_score,
                    recency_score=m.recency_score,
                    source_event_id=m.source_event_id,
                    created_at=m.created_at,
                    is_private=m.is_private,
                )
                for m in mind_view.recent_context.recent_memories
            ],
            recent_interactions=mind_view.recent_context.recent_interactions,
            current_focus=mind_view.recent_context.current_focus,
            emotional_state=mind_view.recent_context.emotional_state,
        ),
        goals=[
            NPCGoalResponse(
                goal_id=g.goal_id,
                goal_text=g.goal_text,
                priority=g.priority,
                status=g.status,
                progress=g.progress,
            )
            for g in mind_view.goals
        ],
        secrets=[
            NPCSecretResponse(
                secret_id=s.secret_id,
                secret_type=s.secret_type,
                description=s.description,
                is_revealed=s.is_revealed,
                revealed_to=s.revealed_to,
            )
            for s in mind_view.secrets
        ],
        forbidden_knowledge=[
            NPCForbiddenKnowledgeResponse(
                knowledge_id=k.knowledge_id,
                knowledge_type=k.knowledge_type,
                description=k.description,
                source=k.source,
            )
            for k in mind_view.forbidden_knowledge
        ],
        secrets_metadata=mind_view.secrets_metadata,
        viewed_at=mind_view.viewed_at,
        view_role=mind_view.view_role.value,
    )
