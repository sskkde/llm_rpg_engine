"""
Debug API routes for LLM RPG Engine.

Provides debugging and logging endpoints for monitoring sessions,
viewing state snapshots, and auditing system behavior.
All endpoints require admin role authentication.
"""

import hashlib
import json

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
    ValidationCheck, ValidationStatus, ErrorSeverity, ProposalAuditEntry
)
from ..core.replay import (
    get_replay_store, ReplayStore, ReplayResult, ReplayStep, ReplayEvent,
    StateSnapshot, ReplayPerspective, ReplayError
)
from ..core.replay_report import (
    get_replay_report_builder, ReplayReportBuilder, ReplayReport,
    StateDiff, StateDiffEntry
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


class LLMStageEvidenceResponse(BaseModel):
    """Evidence from a single LLM-enabled turn stage."""
    stage_name: str
    enabled: bool
    timeout: float
    accepted: bool
    fallback_reason: Optional[str] = None
    validation_errors: List[str] = []
    model_call_id: Optional[str] = None


class ContextHashEntry(BaseModel):
    """A context build hash for fingerprinting injected context."""
    build_id: str
    context_hash: str


class ModelCallReference(BaseModel):
    """Lightweight model call reference for turn debug."""
    call_id: str
    prompt_type: Optional[str] = None
    model_name: Optional[str] = None
    provider: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_estimate: Optional[float] = None
    latency_ms: Optional[int] = None


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
    # LLM Stage Evidence
    llm_stages: List[LLMStageEvidenceResponse] = []
    fallback_reasons: List[str] = []
    # Prompt-specific enhancements
    prompt_template_ids: List[str] = []
    context_hashes: List[ContextHashEntry] = []
    model_call_references: List[ModelCallReference] = []


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


class PromptTemplateUsageEntry(BaseModel):
    """A prompt template as used in a proposal."""
    prompt_template_id: str
    proposal_type: str
    turn_no: int
    model_name: Optional[str] = None
    confidence: Optional[float] = None


class PromptInspectorModelCallEntry(BaseModel):
    """Model call entry for prompt inspector."""
    call_id: str
    turn_no: int
    prompt_type: Optional[str] = None
    model_name: Optional[str] = None
    provider: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_estimate: Optional[float] = None
    latency_ms: Optional[int] = None
    success: bool = True
    created_at: datetime


class PromptInspectorContextBuildEntry(BaseModel):
    """Context build entry for prompt inspector."""
    build_id: str
    turn_no: int
    perspective_type: str
    perspective_id: str
    included_memories: List[MemoryAuditResponse]
    excluded_memories: List[MemoryAuditResponse]
    total_candidates: int
    included_count: int
    excluded_count: int
    context_token_count: int
    build_duration_ms: int


class ProposalInspectorEntry(BaseModel):
    """Proposal audit entry for prompt inspector."""
    audit_id: str
    turn_no: int
    proposal_type: str
    prompt_template_id: Optional[str] = None
    model_name: Optional[str] = None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    raw_output_preview: str
    raw_output_hash: Optional[str] = None
    parsed_proposal: Optional[Dict[str, Any]] = None
    parse_success: bool
    repair_attempts: int
    repair_strategies_tried: List[str]
    repair_success: bool
    validation_passed: bool
    validation_errors: List[str]
    validation_warnings: List[str]
    rejected: bool
    rejection_reason: Optional[str] = None
    fallback_used: bool
    fallback_reason: Optional[str] = None
    fallback_strategy: Optional[str] = None
    confidence: float
    perspective_check_passed: bool
    forbidden_info_detected: List[str]


class ValidationInspectorEntry(BaseModel):
    """Validation audit entry for prompt inspector."""
    validation_id: str
    turn_no: int
    validation_target: str
    overall_status: str
    checks: List[ValidationCheckResponse]
    error_count: int
    warning_count: int
    errors: List[str]
    warnings: List[str]


class PromptInspectorAggregates(BaseModel):
    """Aggregated metrics for prompt inspector."""
    total_tokens_used: int
    total_cost: float
    total_latency_ms: int
    total_model_calls: int
    call_success_rate: float
    repair_success_rate: float


class PromptInspectorResponse(BaseModel):
    """Aggregated prompt-related data for a session."""
    session_id: str
    total_turns: int
    prompt_templates: List[PromptTemplateUsageEntry]
    model_calls: List[PromptInspectorModelCallEntry]
    context_builds: List[PromptInspectorContextBuildEntry]
    proposals: List[ProposalInspectorEntry]
    validations: List[ValidationInspectorEntry]
    aggregates: PromptInspectorAggregates


def require_admin_role(user: UserModel) -> None:
    """Verify user has admin role for debug access."""
    pass


@router.get("/sessions/{session_id}/logs", response_model=DebugSessionLogsResponse)
def get_session_logs(
    session_id: str,
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get session event logs.

    Returns event logs for a specific session with full details.
    Supports pagination via limit and offset parameters.
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

    total_count = db.query(EventLogModel).filter(
        EventLogModel.session_id == session_id
    ).count()

    logs = db.query(EventLogModel).filter(
        EventLogModel.session_id == session_id
    ).order_by(desc(EventLogModel.turn_no), desc(EventLogModel.occurred_at)).offset(offset).limit(limit).all()

    return DebugSessionLogsResponse(
        session_id=session_id,
        total_count=total_count,
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
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get model call summaries.

    Returns audit logs of LLM calls with token usage and costs.
    Optionally filter by session_id.
    Supports pagination via limit and offset parameters.
    Requires admin role.
    """
    require_admin_role(current_user)

    query = db.query(ModelCallLogModel)

    if session_id:
        query = query.filter(ModelCallLogModel.session_id == session_id)

    total_count = query.count()
    calls = query.order_by(desc(ModelCallLogModel.created_at)).offset(offset).limit(limit).all()

    total_cost = sum(call.cost_estimate or 0 for call in calls)

    return DebugModelCallsResponse(
        total_count=total_count,
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
    db: DBSession = Depends(get_db),
):
    """
    Get detailed debug information for a specific turn.

    Returns turn audit data including:
    - Context build IDs
    - Included/excluded memory IDs with reasons
    - Validation checks
    - Model call IDs
    - State delta IDs
    - LLM stage evidence (accepted/rejected proposals, fallback reasons)

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

    llm_stages = []
    fallback_reasons = []

    event_log_repo = EventLogRepository(db)
    event_logs = event_log_repo.get_by_turn(session_id, turn_no)
    event_log = event_logs[0] if event_logs else None

    if event_log and event_log.result_json:
        result_json = event_log.result_json

        llm_stages_data = result_json.get("llm_stages", [])
        for stage_data in llm_stages_data:
            llm_stages.append(LLMStageEvidenceResponse(
                stage_name=stage_data.get("stage_name", ""),
                enabled=stage_data.get("enabled", False),
                timeout=stage_data.get("timeout", 0.0),
                accepted=stage_data.get("accepted", False),
                fallback_reason=stage_data.get("fallback_reason"),
                validation_errors=stage_data.get("validation_errors", []),
                model_call_id=stage_data.get("model_call_id"),
            ))

        for stage_name in ["world", "scene", "npc", "narration"]:
            fallback_key = f"{stage_name}_fallback_reason"
            if fallback_key in result_json:
                fallback_reasons.append(f"{stage_name}: {result_json[fallback_key]}")

    # Collect prompt template IDs from proposal audits for this turn
    prompt_template_ids: List[str] = []
    proposals = store.get_proposal_audits_by_turn(session_id, turn_no)
    for prop in proposals:
        if prop.prompt_template_id and prop.prompt_template_id not in prompt_template_ids:
            prompt_template_ids.append(prop.prompt_template_id)

    # Compute context hashes for each context build ID
    context_hashes: List[ContextHashEntry] = []
    for ctx_build_id in turn_audit.context_build_ids:
        ctx_build = store.get_context_build(ctx_build_id)
        if ctx_build:
            hash_source = {
                "build_id": ctx_build.build_id,
                "perspective_type": ctx_build.perspective_type,
                "perspective_id": ctx_build.perspective_id,
                "included_memory_ids": sorted([m.memory_id for m in ctx_build.included_memories]),
                "excluded_memory_ids": sorted([m.memory_id for m in ctx_build.excluded_memories]),
                "total_candidates": ctx_build.total_candidates,
                "context_token_count": ctx_build.context_token_count,
            }
            ctx_hash = hashlib.sha256(
                json.dumps(hash_source, sort_keys=True, default=str).encode()
            ).hexdigest()
            context_hashes.append(ContextHashEntry(
                build_id=ctx_build_id,
                context_hash=ctx_hash,
            ))

    # Build model call references from the stored model call logs
    model_call_references: List[ModelCallReference] = []
    for call_id in turn_audit.model_call_ids:
        model_call = store.get_model_call(call_id)
        if model_call:
            model_call_references.append(ModelCallReference(
                call_id=model_call.call_id,
                prompt_type=model_call.prompt_type,
                model_name=model_call.model_name,
                provider=model_call.provider,
                input_tokens=model_call.input_tokens,
                output_tokens=model_call.output_tokens,
                cost_estimate=model_call.cost_estimate,
                latency_ms=model_call.latency_ms,
            ))

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
        llm_stages=llm_stages,
        fallback_reasons=fallback_reasons,
        prompt_template_ids=prompt_template_ids,
        context_hashes=context_hashes,
        model_call_references=model_call_references,
    )


@router.get("/sessions/{session_id}/prompt-inspector", response_model=PromptInspectorResponse)
def get_prompt_inspector(
    session_id: str,
    start_turn: Optional[int] = Query(None, ge=1),
    end_turn: Optional[int] = Query(None, ge=1),
    prompt_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db),
):
    """
    Get aggregated prompt-related data for a session.

    Aggregates all prompt-relevant audit data including:
    - Prompt templates used (from ProposalAuditEntry)
    - Context build decisions (included/excluded memories with reasons)
    - Raw LLM output previews and parsed results
    - Repair traces (attempts, strategies, success)
    - Validation results
    - Token usage, cost, latency aggregates

    Supports filtering by turn_range (start_turn, end_turn) and prompt_type.
    Supports pagination via limit and offset parameters.

    Requires admin role.
    """
    require_admin_role(current_user)

    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    audit_logger = get_audit_logger()
    store = audit_logger.get_store()

    # Collect proposals for this session
    proposal_audits = store.get_proposal_audits_by_session(session_id, limit=1000)

    # Filter by turn range
    if start_turn is not None:
        proposal_audits = [p for p in proposal_audits if p.turn_no >= start_turn]
    if end_turn is not None:
        proposal_audits = [p for p in proposal_audits if p.turn_no <= end_turn]

    # Filter by prompt type (match against proposal_type)
    if prompt_type:
        proposal_audits = [p for p in proposal_audits if p.proposal_type == prompt_type]

    # Determine affected turn numbers
    affected_turns = sorted(set(p.turn_no for p in proposal_audits))

    # Collect model calls filtered by the same turn range and prompt_type
    all_model_calls = store.get_model_calls_by_session(session_id, limit=1000)
    # Also check in-memory calls that might be indexed differently
    model_call_ids_from_turns: set = set()
    for turn_no in affected_turns:
        turn_audit = store.get_turn_audit_by_turn(session_id, turn_no)
        if turn_audit:
            model_call_ids_from_turns.update(turn_audit.model_call_ids)

    model_calls: List[PromptInspectorModelCallEntry] = []
    seen_call_ids: set = set()
    for call in all_model_calls:
        if call.call_id in seen_call_ids:
            continue
        if start_turn is not None and call.turn_no < start_turn:
            continue
        if end_turn is not None and call.turn_no > end_turn:
            continue
        if prompt_type and call.prompt_type != prompt_type:
            continue
        seen_call_ids.add(call.call_id)
        model_calls.append(PromptInspectorModelCallEntry(
            call_id=call.call_id,
            turn_no=call.turn_no,
            prompt_type=call.prompt_type,
            model_name=call.model_name,
            provider=call.provider,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cost_estimate=call.cost_estimate,
            latency_ms=call.latency_ms,
            success=call.success,
            created_at=call.created_at,
        ))

    # Also resolve from turn audit model_call_ids for calls not yet seen
    for call_id in model_call_ids_from_turns:
        if call_id in seen_call_ids:
            continue
        call = store.get_model_call(call_id)
        if call:
            if prompt_type and call.prompt_type != prompt_type:
                continue
            seen_call_ids.add(call.call_id)
            model_calls.append(PromptInspectorModelCallEntry(
                call_id=call.call_id,
                turn_no=call.turn_no,
                prompt_type=call.prompt_type,
                model_name=call.model_name,
                provider=call.provider,
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                cost_estimate=call.cost_estimate,
                latency_ms=call.latency_ms,
                success=call.success,
                created_at=call.created_at,
            ))

    # Collect context builds for affected turns
    context_builds: List[PromptInspectorContextBuildEntry] = []
    all_ctx_builds = store.get_context_builds_by_session(session_id, limit=1000)
    # Also collect from turn audits
    ctx_build_ids_from_turns: set = set()
    for turn_no in affected_turns:
        turn_audit = store.get_turn_audit_by_turn(session_id, turn_no)
        if turn_audit:
            ctx_build_ids_from_turns.update(turn_audit.context_build_ids)

    seen_ctx_ids: set = set()
    for ctx in all_ctx_builds:
        if ctx.build_id in seen_ctx_ids:
            continue
        if start_turn is not None and ctx.turn_no < start_turn:
            continue
        if end_turn is not None and ctx.turn_no > end_turn:
            continue
        seen_ctx_ids.add(ctx.build_id)
        context_builds.append(PromptInspectorContextBuildEntry(
            build_id=ctx.build_id,
            turn_no=ctx.turn_no,
            perspective_type=ctx.perspective_type,
            perspective_id=ctx.perspective_id,
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
                for m in ctx.included_memories
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
                for m in ctx.excluded_memories
            ],
            total_candidates=ctx.total_candidates,
            included_count=ctx.included_count,
            excluded_count=ctx.excluded_count,
            context_token_count=ctx.context_token_count,
            build_duration_ms=ctx.build_duration_ms,
        ))

    for ctx_build_id in ctx_build_ids_from_turns:
        if ctx_build_id in seen_ctx_ids:
            continue
        ctx = store.get_context_build(ctx_build_id)
        if ctx:
            if start_turn is not None and ctx.turn_no < start_turn:
                continue
            if end_turn is not None and ctx.turn_no > end_turn:
                continue
            seen_ctx_ids.add(ctx.build_id)
            context_builds.append(PromptInspectorContextBuildEntry(
                build_id=ctx.build_id,
                turn_no=ctx.turn_no,
                perspective_type=ctx.perspective_type,
                perspective_id=ctx.perspective_id,
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
                    for m in ctx.included_memories
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
                    for m in ctx.excluded_memories
                ],
                total_candidates=ctx.total_candidates,
                included_count=ctx.included_count,
                excluded_count=ctx.excluded_count,
                context_token_count=ctx.context_token_count,
                build_duration_ms=ctx.build_duration_ms,
            ))

    # Collect proposals
    proposals: List[ProposalInspectorEntry] = []
    for prop in proposal_audits:
        proposals.append(ProposalInspectorEntry(
            audit_id=prop.audit_id,
            turn_no=prop.turn_no,
            proposal_type=prop.proposal_type,
            prompt_template_id=prop.prompt_template_id,
            model_name=prop.model_name,
            input_tokens=prop.input_tokens,
            output_tokens=prop.output_tokens,
            latency_ms=prop.latency_ms,
            raw_output_preview=prop.raw_output_preview,
            raw_output_hash=prop.raw_output_hash,
            parsed_proposal=prop.parsed_proposal,
            parse_success=prop.parse_success,
            repair_attempts=prop.repair_attempts,
            repair_strategies_tried=prop.repair_strategies_tried,
            repair_success=prop.repair_success,
            validation_passed=prop.validation_passed,
            validation_errors=prop.validation_errors,
            validation_warnings=getattr(prop, 'validation_warnings', []),
            rejected=prop.rejected,
            rejection_reason=prop.rejection_reason,
            fallback_used=prop.fallback_used,
            fallback_reason=prop.fallback_reason,
            fallback_strategy=prop.fallback_strategy,
            confidence=prop.confidence,
            perspective_check_passed=prop.perspective_check_passed,
            forbidden_info_detected=getattr(prop, 'forbidden_info_detected', []),
        ))

    # Collect prompt templates used
    prompt_templates: List[PromptTemplateUsageEntry] = []
    for prop in proposal_audits:
        if prop.prompt_template_id:
            prompt_templates.append(PromptTemplateUsageEntry(
                prompt_template_id=prop.prompt_template_id,
                proposal_type=prop.proposal_type,
                turn_no=prop.turn_no,
                model_name=prop.model_name,
                confidence=prop.confidence,
            ))

    # Collect validations for affected turns
    validations: List[ValidationInspectorEntry] = []
    all_validations = store.get_validations_by_session(session_id, limit=1000)
    for val in all_validations:
        if start_turn is not None and val.turn_no < start_turn:
            continue
        if end_turn is not None and val.turn_no > end_turn:
            continue
        validations.append(ValidationInspectorEntry(
            validation_id=val.validation_id,
            turn_no=val.turn_no,
            validation_target=val.validation_target,
            overall_status=val.overall_status.value,
            checks=[
                ValidationCheckResponse(
                    check_id=c.check_id,
                    check_type=c.check_type,
                    status=c.status.value,
                    message=c.message,
                    details=c.details,
                )
                for c in val.checks
            ],
            error_count=val.error_count,
            warning_count=val.warning_count,
            errors=val.errors,
            warnings=val.warnings,
        ))

    model_calls = model_calls[offset:offset + limit]
    context_builds = context_builds[offset:offset + limit]
    proposals = proposals[offset:offset + limit]
    validations = validations[offset:offset + limit]
    prompt_templates = prompt_templates[offset:offset + limit]

    total_tokens = sum(call.input_tokens or 0 + call.output_tokens or 0 for call in model_calls)
    total_cost = sum(call.cost_estimate or 0 for call in model_calls)
    total_latency = sum(call.latency_ms or 0 for call in model_calls)
    total_calls = len(model_calls)
    successful_calls = sum(1 for call in model_calls if call.success)
    call_success_rate = (successful_calls / total_calls * 100) if total_calls > 0 else 100.0
    total_repairs = sum(p.repair_attempts for p in proposals)
    successful_repairs = sum(1 for p in proposals if p.repair_attempts > 0 and p.repair_success)
    repair_success_rate = (
        (successful_repairs / total_repairs * 100) if total_repairs > 0 else 100.0
    )

    aggregates = PromptInspectorAggregates(
        total_tokens_used=total_tokens,
        total_cost=round(total_cost, 6),
        total_latency_ms=total_latency,
        total_model_calls=total_calls,
        call_success_rate=round(call_success_rate, 2),
        repair_success_rate=round(repair_success_rate, 2),
    )

    return PromptInspectorResponse(
        session_id=session_id,
        total_turns=len(affected_turns),
        prompt_templates=prompt_templates,
        model_calls=model_calls,
        context_builds=context_builds,
        proposals=proposals,
        validations=validations,
        aggregates=aggregates,
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
    llm_stages: List[LLMStageEvidenceResponse] = []
    fallback_reasons: List[str] = []

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
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
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
    all_turns = viewer.get_timeline(session_id, start_turn, end_turn)
    total_turns = len(all_turns)
    turns = all_turns[offset:offset + limit]

    return TimelineResponse(
        session_id=session_id,
        total_turns=total_turns,
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

    llm_stages = []
    fallback_reasons = []

    event_log_repo = EventLogRepository(db)
    event_logs = event_log_repo.get_by_turn(session_id, turn_no)
    event_log = event_logs[0] if event_logs else None

    if event_log and event_log.result_json:
        result_json = event_log.result_json

        llm_stages_data = result_json.get("llm_stages", [])
        for stage_data in llm_stages_data:
            llm_stages.append(LLMStageEvidenceResponse(
                stage_name=stage_data.get("stage_name", ""),
                enabled=stage_data.get("enabled", False),
                timeout=stage_data.get("timeout", 0.0),
                accepted=stage_data.get("accepted", False),
                fallback_reason=stage_data.get("fallback_reason"),
                validation_errors=stage_data.get("validation_errors", []),
                model_call_id=stage_data.get("model_call_id"),
            ))

        for stage_name in ["world", "scene", "npc", "narration"]:
            fallback_key = f"{stage_name}_fallback_reason"
            if fallback_key in result_json:
                fallback_reasons.append(f"{stage_name}: {result_json[fallback_key]}")

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
        llm_stages=llm_stages,
        fallback_reasons=fallback_reasons,
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


class StateDiffEntryResponse(BaseModel):
    path: str
    operation: str
    old_value: Any
    new_value: Any


class StateDiffResponse(BaseModel):
    entries: List[StateDiffEntryResponse]
    added_keys: List[str]
    removed_keys: List[str]
    changed_keys: List[str]


class ReplayReportResponse(BaseModel):
    session_id: str
    snapshot_id: Optional[str] = None
    from_turn: int
    to_turn: int
    replayed_event_count: int
    deterministic: bool
    llm_calls_made: int
    state_diff: StateDiffResponse
    warnings: List[str]
    created_at: datetime


@router.post("/sessions/{session_id}/replay-report", response_model=ReplayReportResponse)
def get_replay_report(
    session_id: str,
    start_turn: int = Query(1, ge=1),
    end_turn: int = Query(..., ge=1),
    perspective: str = Query("admin", regex="^(admin|player|auditor)$"),
    snapshot_id: Optional[str] = None,
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db),
):
    """
    Generate a replay report with state diff.
    
    Returns a human-readable and machine-parseable report showing:
    - State differences between start_turn and end_turn
    - Whether the replay was deterministic (no LLM calls made)
    - Any warnings during replay
    
    Does NOT call LLM - uses only existing logged data.
    
    Perspective controls what information is visible:
    - admin: Full access, sees hidden info
    - player: Player view, no hidden info
    - auditor: Audit view, sees audit data but not hidden lore
    
    Requires admin role.
    """
    require_admin_role(current_user)
    
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    replay_perspective = ReplayPerspective(perspective)
    builder = get_replay_report_builder()
    
    report = builder.build_report(
        session_id=session_id,
        from_turn=start_turn,
        to_turn=end_turn,
        snapshot_id=snapshot_id,
        perspective=replay_perspective,
    )
    
    return ReplayReportResponse(
        session_id=report.session_id,
        snapshot_id=report.snapshot_id,
        from_turn=report.from_turn,
        to_turn=report.to_turn,
        replayed_event_count=report.replayed_event_count,
        deterministic=report.deterministic,
        llm_calls_made=report.llm_calls_made,
        state_diff=StateDiffResponse(
            entries=[
                StateDiffEntryResponse(
                    path=e.path,
                    operation=e.operation,
                    old_value=e.old_value,
                    new_value=e.new_value,
                )
                for e in report.state_diff.entries
            ],
            added_keys=report.state_diff.added_keys,
            removed_keys=report.state_diff.removed_keys,
            changed_keys=report.state_diff.changed_keys,
        ),
        warnings=report.warnings,
        created_at=report.created_at,
    )


# =============================================================================
# Asset Debug Endpoints
# =============================================================================

class AssetDebugResponse(BaseModel):
    """Debug response for asset information."""
    asset_id: str
    asset_type: str
    generation_status: str
    result_url: Optional[str] = None
    error_message: Optional[str] = None
    provider: Optional[str] = None
    cache_hit: bool = False
    created_at: str

    class Config:
        from_attributes = True


@router.get(
    "/sessions/{session_id}/assets",
    response_model=List[AssetDebugResponse],
    summary="List session assets (admin)",
)
def list_session_assets_debug(
    session_id: str,
    asset_type: Optional[str] = Query(None, description="Filter by asset type"),
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db),
):
    """List all assets for a session. Admin only."""
    require_admin_role(current_user)

    # Verify session exists
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    from llm_rpg.storage.repositories import AssetRepository
    from llm_rpg.services.asset_generation_service import AssetGenerationService

    service = AssetGenerationService(AssetRepository(db))
    assets = service.list_session_assets(session_id, asset_type=asset_type)

    return [
        AssetDebugResponse(
            asset_id=a.asset_id,
            asset_type=a.asset_type.value if hasattr(a.asset_type, 'value') else a.asset_type,
            generation_status=a.generation_status.value if hasattr(a.generation_status, 'value') else a.generation_status,
            result_url=a.result_url,
            error_message=a.error_message,
            provider=a.provider,
            cache_hit=a.cache_hit,
            created_at=a.created_at.isoformat() if hasattr(a.created_at, 'isoformat') else str(a.created_at),
        )
        for a in assets
    ]


@router.get(
    "/assets/{asset_id}",
    response_model=AssetDebugResponse,
    summary="Get asset detail (admin)",
)
def get_asset_debug(
    asset_id: str,
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db),
):
    """Get detailed asset info. Admin only."""
    require_admin_role(current_user)

    from llm_rpg.storage.repositories import AssetRepository
    from llm_rpg.services.asset_generation_service import AssetGenerationService

    service = AssetGenerationService(AssetRepository(db))
    asset = service.get_asset(asset_id)

    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset {asset_id} not found"
        )

    return AssetDebugResponse(
        asset_id=asset.asset_id,
        asset_type=asset.asset_type.value if hasattr(asset.asset_type, 'value') else asset.asset_type,
        generation_status=asset.generation_status.value if hasattr(asset.generation_status, 'value') else asset.generation_status,
        result_url=asset.result_url,
        error_message=asset.error_message,
        provider=asset.provider,
        cache_hit=asset.cache_hit,
        created_at=asset.created_at.isoformat() if hasattr(asset.created_at, 'isoformat') else str(asset.created_at),
    )


@router.get(
    "/assets/session/{session_id}",
    response_model=List[AssetDebugResponse],
    summary="List session assets (admin, compatibility path)",
)
def list_session_assets_debug_compat(
    session_id: str,
    asset_type: Optional[str] = Query(None, description="Filter by asset type"),
    current_user: UserModel = Depends(require_debug_admin),
    db: DBSession = Depends(get_db),
):
    """List all assets for a session. Admin only. Compatibility path."""
    return list_session_assets_debug(
        session_id=session_id,
        asset_type=asset_type,
        current_user=current_user,
        db=db,
    )
