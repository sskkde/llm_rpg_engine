"""
Turn Execution Service - PRODUCTION TURN PATH.

This module provides the authoritative turn execution service for all production
gameplay. Both REST and streaming endpoints route through execute_turn_service()
to ensure identical side effects for the same input.

Responsibilities:
- Session initialization (baseline story state rows)
- State reconstruction from DB
- Turn allocation (DB-authoritative numbering)
- Core turn execution (movement, scene, NPC, quest)
- State persistence (session_state, adventure log, recommended_actions)
- Error mapping

Production endpoints using this service:
- POST /game/sessions/{session_id}/turn (REST)
- POST /streaming/sessions/{session_id}/turn (SSE)

Key invariants:
- No state mutation without corresponding DB record
- Streaming may stream narration AFTER durable commit
- Both endpoints produce identical DB side effects

Note: runtime/turn_orchestrator.py is DEPRECATED and for reference only.
"""

import asyncio
import hashlib
import json
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, Dict, FrozenSet, List, Optional, Tuple, Literal

from .turn_progress import TurnProgressEvent, emit_stage
from datetime import datetime

TIME_ADVANCE_LLM_MODE = os.getenv("TIME_ADVANCE_LLM_MODE", "reuse")

from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker
from fastapi.encoders import jsonable_encoder

from .turn_concurrency import acquire_turn_lock

from .session_initialization import (
    initialize_session_story_state, plan_session_story_state, apply_session_story_state,
    SessionStoryStatePlan, SessionInitializationError,
)
from .turn_unit_of_work import TurnUnitOfWork, is_managed
from .state_reconstruction import reconstruct_canonical_state, StateReconstructionError
from .turn_allocation import (
    allocate_turn,
    get_current_turn_number,
    TurnAllocationError,
    TurnConflictError,
)
from .turn_preparation import TurnWriteBuffer
from .time_simulation import (
    ACTION_INTERRUPTED,
    PlayerActionKind,
    PlayerActionStatus,
    TimeSimulationError,
)
from .time_simulation_persistence import (
    SimulationContext,
    apply_simulation_advance,
    build_player_action_spec,
    load_simulation_context,
    npc_overlay_for_turn,
    plan_engine_event_ids,
    project_time_summary,
    resolve_simulation_profile,
)
from .content_runtime import (
    ContentRuntimeBinding,
    ContentRuntimeContext,
    ContentRuntimeError,
    apply_content_advance,
    load_content_runtime_context,
    read_content_binding,
)
from .movement_handler import handle_movement, MovementResult, MovementError
from .scene_action_generator import generate_recommended_actions
from .quest_progression import (
    check_quest_progression,
    effective_quest_status,
    QuestProgressionError,
    QuestStatePlan,
)
from .validator import Validator, ValidationContext
from .validation import (
    MovementValidator,
    QuestValidator,
    NPCKnowledgeValidator,
    NarrationLeakValidator,
)
from .validation.narration_leak_validator import ForbiddenNarrationFact
from .post_commit_memory_writer import (
    update_recall_stats_post_commit,
    write_post_commit_memories,
)
from ..engines.scene_transition import SceneTransitionResolver
from .perception import PerceptionResolver
from .projections import (
    PlayerVisibleProjectionBuilder,
    NPCVisibleProjectionBuilder,
    NarratorProjectionBuilder,
    project_content_public_context,
)
from ..engines.scheduled_event_processor import ScheduledEventProcessor

from ..storage.models import (
    SessionModel, SessionStateModel, SessionPlayerStateModel, SessionNPCStateModel,
    SessionInventoryItemModel, SessionQuestStateModel, SessionEventFlagModel,
    ScheduledEventModel, MemoryFactModel, NPCBeliefModel, NPCPrivateMemoryModel, NPCTemplateModel,
    GameEventModel, StateDeltaModel, WorldModel, PlaythroughInstanceModel,
    StoryPackageVersionModel, LocationModel, NPCTemplateModel, ItemTemplateModel,
    generate_uuid,
    NPCRelationshipMemoryModel, EventLogModel, MemorySummaryModel, TurnTransactionModel,
)
from . import turn_claim
from .turn_claim import (
    ClaimRejected,
    ClaimStatus,
    abort_claim,
    commit_claim,
    compute_request_fingerprint,
    create_or_resume_claim,
)
from .turn_claim_runtime import DEFAULT_TURN_BUDGET_SECONDS, ClaimHeartbeat, TurnBudget
from ..storage.repositories import (
    SessionRepository,
    SessionStateRepository,
    EventLogRepository,
    LocationRepository,
    SessionNPCStateRepository,
    NPCTemplateRepository,
    SessionQuestStateRepository,
    QuestTemplateRepository,
    MemorySummaryRepository,
    MemoryFactRepository,
    TurnTransactionRepository,
    GameEventRepository,
    StateDeltaRepository,
    LLMStageResultRepository,
    ValidationReportRepository,
    NPCBeliefRepository,
    NPCPrivateMemoryRepository,
    NPCSecretRepository,
    NPCRelationshipMemoryRepository,
)
from ..models.states import CanonicalState

from ..llm.service import LLMService, MockLLMProvider

# Phase 2: the LLM authority chain. A production model output is a strict
# contract, then an authorization decision, then a domain adjudication; the
# engine writes only what the last two produced.
from ..models.action_contract import (
    AUTHORIZED_PLAYER_ACTIONS,
    NarrationV2,
    NPCActionV2,
    PlayerIntentV2,
    SceneEventV2,
    WorldTickV2,
)
from ..rules.action_schema import ActorRole, normalize_production_action_type
from .action_authorization import (
    UNAVAILABLE_NPC_STATUSES,
    npc_canonical_key,
    AuthorizationContext,
    AuthorizationOutcome,
    authorize_deterministic_player_intent,
    authorize_npc_action,
    authorize_player_intent,
    authorize_scene_event,
    authorize_world_tick,
    build_player_perspective,
    location_canonical_key,
    resolve_npc_by_name,
    resolve_npc_template_reference,
)
from .action_reason import (
    ActionDetailCode,
    ActionReasonCode,
    ActionStatus,
    public_reason_for_detail,
)
from .action_resolution import (
    CognitionKind,
    MovementResolutionContext,
    ResolvedAction,
    ResolvedCognition,
    ResolvedEvent,
    ResolvedEventKind,
    reject_action,
    resolve_npc_action,
    resolve_player_action,
    resolve_scene_reference,
    resolve_world_reference,
)

logger = logging.getLogger(__name__)


def _end_read_transaction(db: Session) -> None:
    """Close a read-only preparation transaction before waiting on a model.

    The UoW guards commit but does not guard rollback. At these call sites W2-A1/A2/A3
    have moved all preparation writes into plans/buffers, so there are no pending writes
    to discard; rollback only releases the read transaction and its connection state.
    """
    if db.in_transaction():
        db.rollback()


# =============================================================================
# LLM Stage Contract
# =============================================================================

# Stage names for LLM-enabled turn stages
from ..models.llm_stage_routing import LLMStageName


@dataclass
class LLMStageResult:
    """
    Contract for a single LLM-enabled turn stage.
    
    This internal contract is used by execute_turn_service() to track
    LLM stage execution without changing the public API schema.
    
    Fields:
        stage_name: The stage identifier (narration, scene, npc, world, input_intent)
        enabled: Whether this stage was enabled (via feature flag)
        timeout: Timeout in seconds for this stage
        raw_outcome: Raw output from the LLM provider (truncated for storage)
        parsed_proposal: Parsed and validated proposal from the LLM
        accepted: Whether the proposal was accepted (passed validation)
        fallback_reason: Reason for using fallback (if applicable)
        validation_errors: List of validation errors (if rejected)
        model_call_id: DB identifier for the model_call_logs entry (if real provider call)
    
    Invariants:
        - If accepted is True, validation_errors must be empty
        - If fallback_reason is not None, raw_outcome may be empty
        - model_call_id is only set for real provider calls, not mocks
        - parsed_proposal is None if parsing failed or fallback used
    """
    stage_name: LLMStageName
    enabled: bool
    timeout: float
    raw_outcome: Optional[str] = None
    parsed_proposal: Optional[Dict[str, Any]] = None
    accepted: bool = False
    fallback_reason: Optional[str] = None
    validation_errors: List[str] = field(default_factory=list)
    model_call_id: Optional[str] = None
    provider_mode: Optional[str] = None  # Resolved provider mode
    default_model: Optional[str] = None  # Resolved model name
    config_source: Optional[str] = None  # Where config was resolved from
    fallback_used: bool = False  # Whether any fallback was used

    # Phase 2 production chain. ``contract`` holds the validated
    # contract_version=2 DTO (or, for the NPC stage, a dict of
    # ``{npc_id: NPCActionV2}``); it is deliberately excluded from
    # ``to_result_json_dict`` so no contract object ever reaches a JSON column.
    contract: Optional[Any] = None
    #: Stable contract reason code when the strict contract was not satisfied.
    contract_reason_code: Optional[str] = None
    #: Authorization outcome for this stage's proposal.
    authorization: Optional[Any] = None
    #: Engine adjudication of this stage's proposal.
    resolution: Optional[Any] = None

    def to_result_json_dict(self) -> Dict[str, Any]:
        """Convert LLMStageResult to a dict for storage in result_json."""
        return {
            "stage_name": self.stage_name,
            "enabled": self.enabled,
            "timeout": self.timeout,
            "accepted": self.accepted,
            "fallback_reason": self.fallback_reason,
            "validation_errors": self.validation_errors,
            "model_call_id": self.model_call_id,
            "provider_mode": self.provider_mode,
            "default_model": self.default_model,
            "config_source": self.config_source,
            "fallback_used": self.fallback_used,
            "contract_reason_code": self.contract_reason_code,
        }


class TurnServiceError(Exception):
    """Base exception for turn service errors."""

    def __init__(self, message: str, session_id: Optional[str] = None, turn_no: Optional[int] = None):
        self.session_id = session_id
        self.turn_no = turn_no
        super().__init__(message)


class TurnClaimConflictError(TurnServiceError):
    """A request cannot claim the current turn under its idempotency key."""

    def __init__(self, code: str, session_id: str):
        self.code = code
        super().__init__(f"Turn claim rejected: {code}", session_id=session_id)


class TurnBudgetExceededError(TurnServiceError):
    """The service-level turn budget expired before the authoritative commit.

    The budget bounds the whole turn, including the model-call wait, for every
    channel that enters ``execute_turn_service``. An overrun turn is never
    committed: this error is raised at the last check before the final write
    transaction, so no uncommitted result may reach the database.
    """

    code = "turn_budget_exceeded"

    def __init__(
        self,
        session_id: str,
        turn_no: Optional[int] = None,
        total_seconds: Optional[float] = None,
    ):
        self.total_seconds = total_seconds
        detail = "" if total_seconds is None else f" ({total_seconds:g}s budget)"
        super().__init__(
            f"Turn budget exceeded before commit{detail}",
            session_id=session_id,
            turn_no=turn_no,
        )


class TurnRecoveryIncompleteError(TurnServiceError):
    """A committed claim cannot be reconstructed from its persisted event snapshot."""

    code = "recovery_incomplete"


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


class LLMConfigurationError(TurnServiceError):
    """Raised when explicit LLM provider configuration is missing or invalid.

    This error is raised when provider_mode is 'openai' or 'custom' but the
    required API key or configuration is unavailable. Unlike 'auto' mode which
    falls back to MockLLMProvider, explicit modes fail loudly to alert operators.
    """

    def __init__(
        self,
        message: str,
        provider_mode: str,
        missing_config: str,
        session_id: Optional[str] = None,
        turn_no: Optional[int] = None,
    ):
        self.provider_mode = provider_mode
        self.missing_config = missing_config
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
    llm_stage_results: List[LLMStageResult] = field(default_factory=list)
    time_advance_result: Optional[Dict[str, Any]] = None
    idempotency_key: Optional[str] = None
    recovery_status: Optional[str] = None
    presentation_version: int = 0
    #: Phase 2 public action-resolution summary. Only committed turns carry a
    #: value; a recovered legacy snapshot without one reports ``None`` rather than
    #: running a fresh authorization or model call.
    action_resolution: Optional[Dict[str, Any]] = None


def _run_async_safe(coro):
    """
    Run an async coroutine safely, handling nested event loops.
    
    If called from within an already-running event loop (e.g., streaming endpoint),
    runs the coroutine in a separate thread with its own event loop.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    
    if loop is not None and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=180)
    else:
        return asyncio.run(coro)


def _is_narration_stage_enabled(db: Session) -> bool:
    """
    Check if LLM narration stage is enabled via SystemSettingsService.
    
    Narration is enabled when the provider_mode is not "mock",
    indicating a real LLM provider is configured.
    """
    try:
        from ..services.settings import SystemSettingsService
        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()
        provider_mode = provider_config.get("provider_mode", "mock")
        return provider_mode != "mock"
    except Exception:
        return False


def _is_scene_stage_enabled(db: Session) -> bool:
    """
    Check if LLM scene stage is enabled via SystemSettingsService.
    
    Scene stage is enabled when:
    1. provider_mode is not "mock" (real LLM provider configured)
    2. Scene stage is explicitly enabled in settings (future: feature flag)
    
    Currently uses the same condition as narration stage.
    """
    try:
        from ..services.settings import SystemSettingsService
        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()
        provider_mode = provider_config.get("provider_mode", "mock")
        return provider_mode != "mock"
    except Exception:
        return False


def _is_npc_stage_enabled(db: Session) -> bool:
    """
    Check if LLM NPC decision stage is enabled via SystemSettingsService.
    
    NPC stage is enabled when:
    1. provider_mode is not "mock" (real LLM provider configured)
    2. NPC stage is explicitly enabled in settings (future: feature flag)
    
    Currently uses the same condition as narration stage.
    """
    try:
        from ..services.settings import SystemSettingsService
        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()
        provider_mode = provider_config.get("provider_mode", "mock")
        return provider_mode != "mock"
    except Exception:
        return False


def _is_world_stage_enabled(db: Session) -> bool:
    """
    Check if LLM world progression stage is enabled via SystemSettingsService.
    
    World stage is enabled when:
    1. provider_mode is not "mock" (real LLM provider configured)
    2. World stage is explicitly enabled in settings (future: feature flag)
    
    Currently uses the same condition as narration/scene/NPC stages.
    """
    try:
        from ..services.settings import SystemSettingsService
        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()
        provider_mode = provider_config.get("provider_mode", "mock")
        return provider_mode != "mock"
    except Exception:
        return False


def _is_input_intent_stage_enabled(db: Session) -> bool:
    """
    Check if LLM input intent parsing stage is enabled via SystemSettingsService.
    
    Input intent stage is enabled when:
    1. provider_mode is not "mock" (real LLM provider configured)
    2. Input intent stage is explicitly enabled in settings (future: feature flag)
    
    Currently uses the same condition as other LLM stages.
    """
    try:
        from ..services.settings import SystemSettingsService
        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()
        provider_mode = provider_config.get("provider_mode", "mock")
        return provider_mode != "mock"
    except Exception:
        return False


def _build_input_intent_context(
    db: Session,
    session_id: str,
    canonical_state: CanonicalState,
    raw_input: str,
    current_location_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build context for LLM input intent parsing.
    
    Includes: raw input, current location, visible NPCs, available locations.
    Only player-visible facts — no hidden NPC info.
    """
    context: Dict[str, Any] = {
        "session_id": session_id,
        "raw_input": raw_input,
        "constraints": [
            "只能解析玩家输入为结构化意图",
            "意图类型必须是: move, talk, inspect, interact, attack, idle, unknown 之一",
            "目标必须是当前可见的实体或已知地点",
            "不能虚构不存在的目标",
        ],
    }
    
    session_state_repo = SessionStateRepository(db)
    session_state = _get_session_state_with_plan(db, session_id)
    
    if session_state:
        context["current_location_id"] = current_location_id or session_state.current_location_id
    else:
        context["current_location_id"] = current_location_id
    
    if context["current_location_id"]:
        location_repo = LocationRepository(db)
        location = location_repo.get_by_id(context["current_location_id"])
        if location:
            context["current_location"] = {
                "id": location.id,
                "name": location.name,
                "code": location.code,
            }
    
    visible_npcs = _get_visible_npcs(db, session_id, context.get("current_location_id"))
    context["visible_npcs"] = visible_npcs
    
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if session and session.world_id:
        location_repo = LocationRepository(db)
        all_locations = location_repo.get_by_world(session.world_id)
        # Phase 2: only places the player can actually reach are offered. A concealed
        # location must not be disclosed to the model merely by being listed, so the
        # prompt uses the same reachability rule the authorization layer enforces.
        from .action_authorization import location_is_reachable

        auth_ctx = _build_authorization_context(
            db=db,
            session_id=session_id,
            world_id=session.world_id,
            turn_no=0,
            canonical_state=canonical_state,
            current_location_id=context.get("current_location_id"),
        )
        context["available_locations"] = [
            {"id": loc.id, "name": loc.name, "code": loc.code}
            for loc in all_locations
            if location_is_reachable(auth_ctx, loc)[0]
        ]
    
    player_state = canonical_state.player_state
    context["player_state"] = {
        "name": player_state.name,
        "realm": player_state.realm,
        "location_id": context.get("current_location_id"),
    }
    
    return _content_public_context(db, session_id, context)


def _build_world_context_for_turn(
    db: Session,
    session_id: str,
    canonical_state: CanonicalState,
    current_location_id: Optional[str] = None,
    planned_events: Optional[List[Any]] = None,
    planned_quests: Optional[Dict[str, QuestStatePlan]] = None,
) -> Dict[str, Any]:
    """
    Build world context from committed state for world progression candidates.
    
    Includes: world time, location, session flags, quest state.
    Only player-visible / world-visible facts — no hidden NPC info.
    """
    context: Dict[str, Any] = {
        "session_id": session_id,
        "constraints": [
            "只能生成世界压力摘要、地点标记、任务计时器、预定事件提示、势力压力笔记",
            "不能直接修改玩家状态或隐藏NPC信息",
            "提案仅作为候选，不直接变更状态",
        ],
    }

    session_state_repo = SessionStateRepository(db)
    session_state = _get_session_state_with_plan(db, session_id)

    if session_state:
        context["world_time"] = _get_world_time(session_state)
        context["current_location_id"] = current_location_id or session_state.current_location_id
        # Internal-namespace flags (``__``-prefixed) are run-state carriers owned by
        # a specific subsystem -- the phase-3 slice keeps its tick cursor and
        # one-shot switches there. They are part of the session row, but they are
        # not part of any model context: the whitelist below is the only shape a
        # stage may see.
        context["global_flags"] = _public_global_flags(session_state.global_flags_json)
    else:
        context["world_time"] = _get_world_time(None)
        context["current_location_id"] = current_location_id
        context["global_flags"] = {}

    player_state = canonical_state.player_state
    context["player_state"] = {
        "name": player_state.name,
        "realm": player_state.realm,
        "location_id": context["current_location_id"],
    }

    if context["current_location_id"]:
        location_repo = LocationRepository(db)
        location = location_repo.get_by_id(context["current_location_id"])
        if location:
            context["current_location"] = {
                "name": location.name,
                "code": location.code,
            }

    active_quests = _get_active_quests(db, session_id, planned_quests=planned_quests)
    context["active_quests"] = active_quests

    recent_events = _get_recent_events(db, session_id, limit=3, planned_events=planned_events)
    context["recent_events"] = recent_events

    return _content_public_context(db, session_id, context)


# Allowed fields for world progression proposals (bounded validation)
_WORLD_PROPOSAL_ALLOWED_EVENT_FIELDS = {"event_type", "description", "effects", "importance", "visibility"}
_WORLD_PROPOSAL_ALLOWED_DELTA_PATHS = {
    "global_flags",
    "quest_progress",
    "location_flags",
    "scheduled_event_hints",
    "faction_pressure",
}


def _validate_world_proposal(proposal: Any) -> Tuple[bool, List[str]]:
    """
    Validate a world tick proposal. Only bounded fields are accepted.
    
    Checks:
    - proposal is not None
    - candidate_events have only allowed fields
    - state_deltas target only allowed paths
    - No forbidden info leaks
    """
    errors: List[str] = []

    if proposal is None:
        return (False, ["proposal is None"])

    if not hasattr(proposal, "candidate_events"):
        errors.append("proposal missing candidate_events")
    elif not isinstance(proposal.candidate_events, list):
        errors.append("candidate_events is not a list")
    else:
        for i, event in enumerate(proposal.candidate_events):
            if hasattr(event, "event_type") and not event.event_type:
                errors.append(f"candidate_event[{i}] has empty event_type")
            if hasattr(event, "description") and not event.description:
                errors.append(f"candidate_event[{i}] has empty description")

    if not hasattr(proposal, "state_deltas"):
        errors.append("proposal missing state_deltas")
    elif not isinstance(proposal.state_deltas, list):
        errors.append("state_deltas is not a list")
    else:
        for i, delta in enumerate(proposal.state_deltas):
            if hasattr(delta, "path"):
                path_root = delta.path.split(".")[0] if delta.path else ""
                if path_root not in _WORLD_PROPOSAL_ALLOWED_DELTA_PATHS:
                    errors.append(
                        f"state_delta[{i}] path '{delta.path}' not in allowed paths"
                    )

    if hasattr(proposal, "candidate_events") and isinstance(proposal.candidate_events, list):
        for i, event in enumerate(proposal.candidate_events):
            if hasattr(event, "description"):
                forbidden = ["隐藏身份", "真实身份", "hidden_identity", "secret_identity"]
                for pattern in forbidden:
                    if pattern in event.description:
                        errors.append(f"forbidden pattern in event[{i}] description: {pattern}")

    return (len(errors) == 0, errors)


_VALID_INTENT_TYPES = {"move", "talk", "inspect", "interact", "attack", "idle", "unknown", "action"}
_VALID_RISK_LEVELS = {"low", "medium", "high"}


def _validate_input_intent_proposal(
    proposal: Any,
    input_context: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    Validate an input intent proposal.
    
    Checks:
    - proposal is not None
    - intent_type is valid
    - risk_level is valid (if present)
    - target exists if intent_type requires it (move)
    
    Returns (is_valid, validation_errors).
    """
    errors: List[str] = []
    
    if proposal is None:
        return (False, ["proposal is None"])
    
    if not hasattr(proposal, "intent_type"):
        errors.append("proposal missing intent_type")
    elif not proposal.intent_type:
        errors.append("intent_type is empty")
    elif proposal.intent_type not in _VALID_INTENT_TYPES:
        errors.append(f"invalid intent_type: {proposal.intent_type}")
    
    if hasattr(proposal, "risk_level") and proposal.risk_level:
        if proposal.risk_level not in _VALID_RISK_LEVELS:
            errors.append(f"invalid risk_level: {proposal.risk_level}")
    
    if hasattr(proposal, "intent_type") and proposal.intent_type == "move":
        needs_clarification = getattr(proposal, "needs_clarification", False) is True
        if not hasattr(proposal, "target") or not proposal.target:
            if not needs_clarification:
                errors.append("move intent requires a target")
    
    return (len(errors) == 0, errors)



def _contract_fallback_reason(outcome: Any) -> str:
    """Map a production-contract outcome onto the existing fallback vocabulary.

    A contract-incompatible output is recorded explicitly (so an old template's
    answer is never silently reinterpreted), while "no output at all" keeps the
    pre-existing fallback wording used by the timeout/provider-error paths.
    """
    code = getattr(outcome, "reason_code", None) or "contract_unavailable"
    if getattr(outcome, "contract_incompatible", False):
        return f"contract_incompatible: {code}"
    detail = getattr(outcome, "detail", "") or ""
    if detail:
        return f"{code}: {detail[:200]}"
    return code


def _player_intent_projection(contract: PlayerIntentV2) -> Dict[str, Any]:
    """JSON-safe projection of a ``PlayerIntentV2`` for audit and existing readers.

    ``intent_type`` is the canonical action type so the pre-existing per-action
    time rules keep working unchanged; ``intent`` keeps the exact wire parameters.
    """
    from ..rules.action_schema import normalize_production_action_type

    intent = contract.intent
    return {
        "contract_version": 2,
        "intent_type": normalize_production_action_type(intent.action_type),
        "intent": intent.model_dump(mode="json"),
        "needs_clarification": contract.needs_clarification,
        "clarification_question": contract.clarification_question,
        "confidence": contract.confidence,
        "visibility": "player_visible",
    }


def _build_authorization_context(
    *,
    db: Session,
    session_id: str,
    world_id: str,
    turn_no: int,
    canonical_state: CanonicalState,
    current_location_id: Optional[str] = None,
    visible_npc_ids: Optional[Any] = None,
    available_memory_ids: Optional[Any] = None,
    allowed_event_ids: Optional[Any] = None,
    legal_recommended_actions: Optional[Any] = None,
) -> AuthorizationContext:
    """Build the read-only authorization context for one turn."""
    return AuthorizationContext(
        db=db,
        session_id=session_id,
        world_id=world_id,
        turn_no=turn_no,
        canonical_state=canonical_state,
        current_location_id=current_location_id,
        visible_npc_ids=frozenset(visible_npc_ids or ()),
        available_memory_ids=(
            None if available_memory_ids is None else frozenset(available_memory_ids)
        ),
        allowed_event_ids=frozenset(allowed_event_ids or ()),
        legal_recommended_actions=tuple(legal_recommended_actions or ()),
    )


def _public_global_flags(global_flags: Any) -> Dict[str, Any]:
    """Session flags as a model context may see them.

    A key in an internal namespace (``__``-prefixed) belongs to one subsystem's
    private run state and never leaves the database row it lives in.
    """
    if not isinstance(global_flags, dict):
        return {}
    return {
        key: value
        for key, value in global_flags.items()
        if not (isinstance(key, str) and key.startswith("__"))
    }


def _planned_game_event_ids(write_buffer: Optional[Any]) -> FrozenSet[str]:
    """Ids of this turn's already-decided engine fact events.

    A world/scene reference may only point at events the engine produced *in this
    turn*; an id from an earlier turn is not an execution grant. The phase-3
    advance decides its own facts during preparation, so its pre-allocated ids are
    part of this set even though the rows land in the final write section.
    """
    if write_buffer is None:
        planned_ids: FrozenSet[str] = frozenset()
    else:
        planned_ids = frozenset(
            planned.id
            for planned in write_buffer.planned_game_events()
            if getattr(planned, "id", None)
        )
    return planned_ids | frozenset(_phase3_planned_event_ids(write_buffer).values())


def _content_public_context(
    db: Session,
    session_id: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply the content runtime's player-safe context and same-session routes."""
    runtime = db.info.get("content_runtime_context")
    if runtime is None:
        return context
    state = runtime.state
    allowed_npc_ids = set()
    for npc_state in SessionNPCStateRepository(db).get_by_session(session_id):
        template = db.get(NPCTemplateModel, npc_state.npc_template_id)
        code = getattr(template, "code", None)
        if (
            isinstance(code, str)
            and code in state.npc_positions
            and state.npc_positions[code] == state.player_location_code
            and state.npc_is_alive(code)
        ):
            allowed_npc_ids.add(npc_state.id)

    projected = project_content_public_context(
        context,
        visible_npc_ids=allowed_npc_ids,
    )
    available_locations = projected.get("available_locations")
    if isinstance(available_locations, list):
        open_destinations = {
            destination
            for source, destination in runtime.rules.data.routes
            if source == state.player_location_code
            and state.route_is_open(source, destination)
        }
        projected["available_locations"] = [
            location
            for location in available_locations
            if isinstance(location, dict)
            and location.get("code") in open_destinations
        ]
    return projected


def _content_recommended_actions(db: Session, runtime: ContentRuntimeContext) -> List[str]:
    """Generate only player recommendations backed by the current route view."""
    source = runtime.state.player_location_code
    destinations = sorted(
        destination
        for origin, destination in runtime.rules.data.routes
        if origin == source and runtime.state.route_is_open(origin, destination)
    )
    if not destinations:
        return ["观察周围"]
    locations = db.query(LocationModel).filter(
        LocationModel.world_id == runtime.binding.world_id,
        LocationModel.code.in_(destinations),
    ).all()
    by_code = {location.code: location for location in locations}
    actions = [f"前往{by_code[code].name}" for code in destinations if code in by_code]
    return actions[:4] or ["观察周围"]


def _phase3_planned_event_ids(write_buffer: Optional[Any]) -> Dict[int, str]:
    """The advance's pre-allocated event ids, keyed by engine sequence."""
    if write_buffer is None:
        return {}
    planned = getattr(write_buffer, "phase3_event_ids", None)
    return planned if isinstance(planned, dict) else {}


def _apply_authorization_to_stage(
    stage_result: LLMStageResult,
    outcome: AuthorizationOutcome,
    *,
    scope: str,
) -> LLMStageResult:
    """Fold an authorization decision into a stage result.

    A rejected authorization makes the stage not-accepted with the coarse public
    reason code; the restricted detail stays in ``authorization`` for audit only.
    """
    stage_result.authorization = outcome
    if outcome.authorized:
        return stage_result
    stage_result.accepted = False
    reason = outcome.public_reason or ActionReasonCode.INVALID_PARAMS
    stage_result.fallback_reason = f"authorization_rejected: {reason.value}"
    stage_result.validation_errors = [f"{scope}:{outcome.detail_code}"] if outcome.detail_code else []
    return stage_result


#: Contract reason codes that mean "the model answered, but not in the contract".
_CONTRACT_INCOMPATIBLE_PREFIX = "contract_"


def _action_reason_override(
    *,
    resolution: Optional[ResolvedAction],
    intent_contract: Optional[PlayerIntentV2],
    input_intent_result: Optional[LLMStageResult],
) -> Optional[ActionReasonCode]:
    """Refine the public reason code for a fallback action.

    A contract-incompatible answer to an *authorized* action class is reported as
    ``contract_failure`` rather than as the coarse outcome the deterministic parse
    happened to produce, so the public summary distinguishes "the model was
    unusable" from "the player asked for something the engine cannot do". An
    unsupported action class keeps ``unsupported``: that is the more accurate
    statement about the action, and the contract failure stays in audit.
    """
    if resolution is None or resolution.accepted:
        return None
    if resolution.reason_code is ActionReasonCode.UNSUPPORTED:
        return None
    if intent_contract is not None:
        return None
    reason_code = getattr(input_intent_result, "contract_reason_code", None)
    if not reason_code or not str(reason_code).startswith(_CONTRACT_INCOMPATIBLE_PREFIX):
        return None
    return ActionReasonCode.CONTRACT_FAILURE


def _build_action_resolution_summary(
    *,
    action_type: str,
    resolution: Optional[ResolvedAction],
    authorization: Optional[AuthorizationOutcome],
    fallback_used: bool,
    status_override: Optional[ActionStatus] = None,
    reason_override: Optional[ActionReasonCode] = None,
) -> Dict[str, Any]:
    """Build the public ``action_resolution`` summary for a committed turn.

    Only three public statuses and four coarse public reason codes exist, so the
    summary never discloses whether a hidden entity exists. Restricted detail stays
    in the authorization/audit records.

    The summary is an *already-happened fact*: it is only written after the commit
    and is read back verbatim on a same-key recovery. A recovered legacy snapshot
    without one reports ``None`` instead of running a fresh authorization.
    """
    if status_override is not None:
        status = status_override
        reason_code = reason_override
    elif resolution is None:
        status = ActionStatus.REJECTED
        reason_code = reason_override or ActionReasonCode.INVALID_PARAMS
    elif resolution.status == ActionStatus.CLARIFICATION:
        status = ActionStatus.CLARIFICATION
        reason_code = None
    elif resolution.accepted:
        status = ActionStatus.ACCEPTED
        reason_code = None
    else:
        status = ActionStatus.REJECTED
        reason_code = resolution.reason_code or reason_override
        if reason_code is None and authorization is not None:
            reason_code = authorization.public_reason

    return {
        "version": 1,
        "action_type": normalize_production_action_type(action_type or "unknown"),
        "status": status.value,
        "reason_code": reason_code.value if reason_code else None,
        "fallback_used": bool(fallback_used),
    }


def _session_world_id(
    db: Session,
    session_id: str,
    canonical_state: Optional[CanonicalState] = None,
) -> str:
    """Resolve the world id for authorization without trusting caller input."""
    if canonical_state is not None:
        world_state = getattr(canonical_state, "world_state", None)
        world_id = getattr(world_state, "world_id", None)
        if world_id:
            return world_id
    session = SessionRepository(db).get_by_id(session_id)
    return session.world_id if session is not None else ""


def _world_tick_projection(contract: WorldTickV2) -> Dict[str, Any]:
    """JSON-safe projection of a ``WorldTickV2`` for audit and result_json.

    Deliberately contains no candidate events, effects, deltas or time fields: the
    world stage may only reference results the engine already decided.
    """
    return {
        "contract_version": 2,
        "referenced_event_ids": list(contract.referenced_event_ids),
        "display_hint": contract.display_hint,
        "confidence": contract.confidence,
    }


def _scene_event_projection(
    contract: SceneEventV2,
    authorization: Optional[AuthorizationOutcome] = None,
) -> Dict[str, Any]:
    """JSON-safe projection of an *authorized* ``SceneEventV2``.

    The recommended actions come from the authorization result, not from the raw
    contract: the engine keeps only the entries that exist in its own legal set, so
    a model-invented hint can never reach the player through this projection.
    """
    authorized_actions = (
        list(authorization.action.recommended_actions)
        if authorization is not None and authorization.authorized and authorization.action
        else []
    )
    authorized_refs = (
        list(authorization.action.referenced_event_ids)
        if authorization is not None and authorization.authorized and authorization.action
        else []
    )
    return {
        "contract_version": 2,
        "referenced_event_ids": authorized_refs,
        "recommended_actions": authorized_actions,
        "display_hint": contract.display_hint,
        "confidence": contract.confidence,
    }


def _npc_action_projection(
    contract: NPCActionV2,
    npc_id: str,
    npc_name: Optional[str],
    visible_to_player: bool,
) -> Dict[str, Any]:
    """JSON-safe projection of an authorized ``NPCActionV2``.

    The actor id is server-bound; the wire never supplied it. Model text stays in
    ``summary``/``visible_motivation``/``utterance``, which are presentation or
    quotation fields only.
    """
    from ..models.action_contract import NPC_ACTION_ALIASES

    return {
        "contract_version": 2,
        "npc_id": npc_id,
        "npc_name": npc_name,
        "action_type": NPC_ACTION_ALIASES.get(
            contract.action.action_type, contract.action.action_type
        ),
        "target_id": getattr(contract.action, "target_id", None),
        "utterance": getattr(contract.action, "utterance", None),
        "summary": contract.summary,
        "visible_motivation": contract.visible_motivation,
        "visible_to_player": visible_to_player,
        "used_memory_ids": list(contract.used_memory_ids),
        "confidence": contract.confidence,
    }


def _npc_fallback_reaction(
    npc_id: str,
    npc_name: Optional[str],
    reason: str,
    detail_code: Optional[ActionDetailCode] = None,
) -> Dict[str, Any]:
    """JSON-safe deterministic NPC fallback: the engine's observe/idle result.

    A failed NPC proposal falls back to an engine-owned wait; it never keeps a
    partially accepted model action, and it does not advance world time.
    """
    reaction: Dict[str, Any] = {
        "npc_id": npc_id,
        "npc_name": npc_name,
        "accepted": False,
        "fallback_reason": reason,
        "action_type": "idle",
        "summary": f"{npc_name}等待着",
    }
    if detail_code is not None:
        # Restricted-audit detail: never returned to clients.
        reaction["authorization_detail"] = detail_code.value
    return reaction


def _execute_input_intent_stage(
    db: Session,
    session_id: str,
    turn_no: int,
    canonical_state: CanonicalState,
    raw_input: str,
    current_location_id: Optional[str] = None,
    use_mock: bool = False,
) -> LLMStageResult:
    """
    Execute the input intent LLM stage.
    
    1. Check if enabled via feature flag
    2. Build input context from committed state
    3. Call ProposalPipeline.generate_input_intent()
    4. Validate parsed intent
    5. Return LLMStageResult with accepted/rejected status
    """
    from ..llm.proposal_pipeline import ProposalPipeline, ProposalConfig
    
    stage_name: LLMStageName = "input_intent"
    
    enabled = _is_input_intent_stage_enabled(db)
    if not enabled:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=False,
            timeout=15.0,
            accepted=False,
            fallback_reason="input_intent_stage_disabled",
        )
    
    input_context = _build_input_intent_context(
        db=db,
        session_id=session_id,
        canonical_state=canonical_state,
        raw_input=raw_input,
        current_location_id=current_location_id,
    )
    
    try:
        from ..services.settings import SystemSettingsService
        from ..llm.stage_provider_resolver import resolve_stage_llm_config
        
        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()
        
        stage_config = resolve_stage_llm_config(stage_name, provider_config, use_mock=use_mock)
        
        # Merge stage-level provider_mode/default_model into config for _create_llm_service_from_config
        merged_config = dict(provider_config)
        merged_config["provider_mode"] = stage_config.provider_mode
        merged_config["default_model"] = stage_config.default_model
        
        llm_service = _create_llm_service_from_config(
            db,
            merged_config,
            force_mock=use_mock,
        )
        
        pipeline_config = ProposalConfig(
            timeout_seconds=stage_config.timeout_seconds,
            max_tokens=stage_config.max_tokens,
            temperature=stage_config.temperature,
        )
        pipeline = ProposalPipeline(llm_service=llm_service, config=pipeline_config)
        
    except LLMConfigurationError:
        raise
    except Exception as e:
        logger.warning("Failed to configure LLM service for input intent stage: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            accepted=False,
            fallback_reason=f"llm_config_error: {str(e)[:200]}",
        )
    
    try:
        # input_context and provider configuration are plain data; no ORM attributes
        # are needed after ending the read transaction.
        _end_read_transaction(db)
        outcome = _run_async_safe(
            pipeline.generate_player_intent_production(
                raw_input=raw_input,
                context=input_context,
                prompt_template_id="input_intent_v2",
                session_id=session_id,
                turn_no=turn_no,
            )
        )

        if not outcome.accepted:
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=stage_config.timeout_seconds,
                accepted=False,
                fallback_reason=_contract_fallback_reason(outcome),
                raw_outcome=outcome.raw_output_preview or None,
                contract_reason_code=outcome.reason_code,
                validation_errors=[_contract_fallback_reason(outcome)],
            )

        contract: PlayerIntentV2 = outcome.contract  # type: ignore[assignment]
        parsed_proposal = _player_intent_projection(contract)

        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            raw_outcome=contract.model_dump_json()[:500],
            parsed_proposal=parsed_proposal,
            accepted=True,
            config_source=stage_config.config_source,
            fallback_used=stage_config.fallback_used,
            contract=contract,
        )
        
    except asyncio.TimeoutError:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            accepted=False,
            fallback_reason="timeout",
        )
    except Exception as e:
        logger.warning("LLM input intent stage failed: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            accepted=False,
            fallback_reason=f"error: {str(e)[:200]}",
        )


def _execute_world_stage(
    db: Session,
    session_id: str,
    turn_no: int,
    canonical_state: CanonicalState,
    current_location_id: Optional[str] = None,
    use_mock: bool = False,
    transaction_id: Optional[str] = None,
    write_buffer: Optional[TurnWriteBuffer] = None,
    planned_quests: Optional[Dict[str, QuestStatePlan]] = None,
) -> LLMStageResult:
    """
    Execute the world progression LLM stage.
    
    1. Check if enabled via feature flag
    2. Build world context from committed state
    3. Call ProposalPipeline.generate_world_tick()
    4. Validate candidates (bounded fields only)
    5. Return LLMStageResult with accepted/rejected status
    """
    from ..llm.proposal_pipeline import ProposalPipeline, ProposalConfig

    stage_name: LLMStageName = "world"

    enabled = _is_world_stage_enabled(db)
    if not enabled:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=False,
            timeout=30.0,
            accepted=False,
            fallback_reason="world_stage_disabled",
        )

    world_context = _build_world_context_for_turn(
        db=db,
        session_id=session_id,
        canonical_state=canonical_state,
        current_location_id=current_location_id,
        planned_events=write_buffer.planned_event_logs() if write_buffer else None,
        planned_quests=planned_quests,
    )

    try:
        from ..services.settings import SystemSettingsService
        from ..llm.stage_provider_resolver import resolve_stage_llm_config

        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()

        stage_config = resolve_stage_llm_config(stage_name, provider_config, use_mock=use_mock)

        # Merge stage-level provider_mode/default_model into config for _create_llm_service_from_config
        merged_config = dict(provider_config)
        merged_config["provider_mode"] = stage_config.provider_mode
        merged_config["default_model"] = stage_config.default_model

        llm_service = _create_llm_service_from_config(
            db,
            merged_config,
            force_mock=use_mock,
        )

        pipeline_config = ProposalConfig(
            timeout_seconds=stage_config.timeout_seconds,
            max_tokens=stage_config.max_tokens,
            temperature=stage_config.temperature,
        )
        pipeline = ProposalPipeline(llm_service=llm_service, config=pipeline_config)

    except LLMConfigurationError:
        raise
    except Exception as e:
        logger.warning("Failed to configure LLM service for world stage: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            accepted=False,
            fallback_reason=f"llm_config_error: {str(e)[:200]}",
        )

    # The engine event ids this turn already produced are the *only* legal
    # references, so the model is given exactly that list (an id it was not shown
    # can never be authorized).
    world_context["engine_event_ids"] = sorted(_planned_game_event_ids(write_buffer))

    try:
        # world_context and stage configuration are plain data, not ORM objects.
        _end_read_transaction(db)
        outcome = _run_async_safe(
            pipeline.generate_world_tick_production(
                world_context=world_context,
                prompt_template_id="world_tick_v2",
                session_id=session_id,
                turn_no=turn_no,
            )
        )

        if not outcome.accepted:
            if transaction_id:
                _create_validation_report(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    scope="proposal_world_tick",
                    target_ref_id=None,
                    is_valid=False,
                    errors_json=[_contract_fallback_reason(outcome)],
                    buffer=write_buffer,
                )
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=stage_config.timeout_seconds,
                accepted=False,
                fallback_reason=_contract_fallback_reason(outcome),
                raw_outcome=outcome.raw_output_preview or None,
                contract_reason_code=outcome.reason_code,
                validation_errors=[_contract_fallback_reason(outcome)],
            )

        contract: WorldTickV2 = outcome.contract  # type: ignore[assignment]
        allowed_event_ids = _planned_game_event_ids(write_buffer)
        auth_context = _build_authorization_context(
            db=db,
            session_id=session_id,
            world_id=_session_world_id(db, session_id, canonical_state),
            turn_no=turn_no,
            canonical_state=canonical_state,
            current_location_id=current_location_id,
            allowed_event_ids=allowed_event_ids,
        )
        authorization = authorize_world_tick(auth_context, contract)

        if not authorization.authorized:
            if transaction_id:
                _create_validation_report(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    scope="proposal_world_tick",
                    target_ref_id=None,
                    is_valid=False,
                    errors_json=[str(authorization.detail_code)],
                    buffer=write_buffer,
                )
            return _apply_authorization_to_stage(
                LLMStageResult(
                    stage_name=stage_name,
                    enabled=True,
                    timeout=stage_config.timeout_seconds,
                    raw_outcome=contract.model_dump_json()[:500],
                    contract=contract,
                    contract_reason_code=outcome.reason_code,
                    config_source=stage_config.config_source,
                    fallback_used=stage_config.fallback_used,
                ),
                authorization,
                scope="world_tick",
            )

        resolution = resolve_world_reference(authorization.action)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            raw_outcome=contract.model_dump_json()[:500],
            parsed_proposal=_world_tick_projection(contract),
            accepted=True,
            config_source=stage_config.config_source,
            fallback_used=stage_config.fallback_used,
            contract=contract,
            authorization=authorization,
            resolution=resolution,
        )

    except asyncio.TimeoutError:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            accepted=False,
            fallback_reason="timeout",
        )
    except Exception as e:
        logger.warning("LLM world stage failed: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            accepted=False,
            fallback_reason=f"error: {str(e)[:200]}",
        )


def _load_frozen_narration_forbidden_facts(
    db: Session,
    session_id: str,
    canonical_state: CanonicalState,
    story_plan: Optional[SessionStoryStatePlan] = None,
) -> List[ForbiddenNarrationFact]:
    """Load this turn's forbidden facts once, including baseline NPC overlays."""
    validator = NarrationLeakValidator()
    facts = validator._load_db_forbidden_facts(db, session_id, canonical_state, None)
    planned_npc_ids = [
        row.get("npc_template_id")
        for row in (story_plan.npc_states if story_plan is not None else [])
        if row.get("npc_template_id")
    ]
    if planned_npc_ids:
        for npc in db.query(NPCTemplateModel).filter(NPCTemplateModel.id.in_(planned_npc_ids)).all():
            if validator._is_checkable_text(npc.hidden_identity):
                facts.append(ForbiddenNarrationFact(npc.hidden_identity, f"hidden_identity:{npc.id}"))
    return validator._deduplicate_facts(facts)


def _build_narration_context(
    db: Session,
    session_id: str,
    canonical_state: CanonicalState,
    player_input: str,
    action_type: str,
    movement_result: Optional[MovementResult] = None,
    state_deltas: Optional[Dict[str, Any]] = None,
    current_location_id: Optional[str] = None,
    npc_reactions: Optional[List[Dict[str, Any]]] = None,
    planned_events: Optional[List[Any]] = None,
    planned_game_events: Optional[List[Any]] = None,
    planned_quests: Optional[Dict[str, QuestStatePlan]] = None,
) -> Dict[str, Any]:
    """
    Build narration context from committed state only.
    
    CRITICAL: Only includes player-visible facts. No hidden NPC info.
    Uses NarratorProjectionBuilder to ensure private_payload is never included.
    
    Context includes:
    - Session state (current location, world time)
    - Action result (movement success/blocked, quest progression)
    - Visible NPCs at location (public identity only, NO hidden_identity)
    - Narration events (filtered by NarratorProjectionBuilder, NO private_payload)
    - Current location details
    - State deltas from this turn
    - Relevant memory summaries (world/scene level, NO NPC subjective)
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        canonical_state: Reconstructed canonical state (read-only)
        player_input: The player's input text
        action_type: The parsed action type
        movement_result: Optional movement result from this turn
        state_deltas: Optional state deltas from this turn
        current_location_id: The current location ID after any movement
        planned_events: This turn's planned event-log rows (not yet written by the
            final transaction); merged so the context matches the pre-W2 behaviour
            where they were already flushed.
        planned_game_events: This turn's planned game events, merged into the same
            projection the database rows feed.
        
    Returns:
        Dict with narration context for LLM (private_payload excluded)
    """
    from ..models.events import GameEvent, EventType
    from ..models.perspectives import PlayerPerspective, NarratorPerspective
    
    context: Dict[str, Any] = {
        "session_id": session_id,
        "player_input": player_input,
        "action_type": action_type,
        "constraints": [
            "只能描述玩家可见的场景和事件",
            "不能泄露隐藏的秘密或未揭示的信息",
            "不能添加未发生的事件或未提交的状态变化",
            "叙事必须基于已提交的事实",
            "private_payload 严禁出现在叙事中",
        ],
    }
    
    session_state_repo = SessionStateRepository(db)
    session_state = _get_session_state_with_plan(db, session_id)
    
    if session_state:
        context["world_time"] = _get_world_time(session_state)
        context["current_location_id"] = current_location_id or session_state.current_location_id
        context["active_mode"] = session_state.active_mode
    else:
        context["world_time"] = _get_world_time(None)
        context["current_location_id"] = current_location_id
    
    player_state = canonical_state.player_state
    context["player_state"] = {
        "name": player_state.name,
        "realm": player_state.realm,
        "spiritual_power": player_state.spiritual_power,
        "location_id": context["current_location_id"],
    }
    
    if context["current_location_id"]:
        location_repo = LocationRepository(db)
        location = location_repo.get_by_id(context["current_location_id"])
        if location:
            context["current_location"] = {
                "name": location.name,
                "code": location.code,
                "description": location.description,
            }
    
    if movement_result:
        context["movement"] = {
            "success": movement_result.success,
            "new_location_name": movement_result.new_location_name,
            "new_location_code": movement_result.new_location_code,
            "blocked_reason": movement_result.blocked_reason,
            "narration_hint": movement_result.narration_hint,
        }
    
    if state_deltas:
        context["state_deltas"] = state_deltas
    
    visible_npcs = _get_visible_npcs(db, session_id, context.get("current_location_id"))
    context["visible_npcs"] = visible_npcs
    
    if state_deltas and "quest_progression" in state_deltas:
        context["quest_progression"] = state_deltas["quest_progression"]
    
    active_quests = _get_active_quests(db, session_id, planned_quests=planned_quests)
    context["active_quests"] = active_quests
    
    game_event_repo = GameEventRepository(db)
    planned_game_event_rows = [event for event in (planned_game_events or []) if event is not None]
    recent_event_models = _merge_planned_game_events(
        game_event_repo.get_by_session(session_id, limit=10 + len(planned_game_event_rows)),
        planned_game_event_rows,
        limit=10,
    )
    
    if recent_event_models:
        recent_game_events = []
        for em in recent_event_models:
            try:
                event = GameEvent(
                    event_id=em.id,
                    event_type=EventType(em.event_type),
                    turn_index=em.turn_no,
                    timestamp=em.occurred_at,
                    metadata=em.public_payload_json or {},
                )
                recent_game_events.append(event)
            except Exception:
                continue
        
        if recent_game_events:
            player_perspective = PlayerPerspective(
                perspective_id="player",
                owner_id="player",
                known_facts=getattr(player_state, "known_fact_ids", []),
            )
            
            narrator_perspective = NarratorPerspective(
                perspective_id="narrator",
                owner_id="narrator",
                base_perspective_id="player",
                tone="neutral",
                pacing="normal",
                forbidden_info=["hidden_identity", "secret_plan", "private_payload"],
                allowed_hints=["foreshadowing", "rumor"],
            )
            
            perception_resolver = PerceptionResolver()
            narrator_projection_builder = NarratorProjectionBuilder(perception_resolver)
            
            projection_context = {
                "player_location_id": context.get("current_location_id", "unknown"),
                "current_turn": canonical_state.world_state.current_turn if hasattr(canonical_state.world_state, 'current_turn') else 0,
                "player_perspective": player_perspective,
            }
            
            narration_events = narrator_projection_builder.build_projection(
                events=recent_game_events,
                perspective=narrator_perspective,
                context=projection_context,
            )
            
            context["narration_events"] = narration_events
        else:
            recent_events = _get_recent_events(
                db, session_id, limit=5, planned_events=planned_events
            )
            context["recent_events"] = recent_events
    else:
        recent_events = _get_recent_events(
            db, session_id, limit=5, planned_events=planned_events
        )
        context["recent_events"] = recent_events
    
    if npc_reactions:
        player_visible_reactions = [
            {
                "npc_name": r.get("npc_name"),
                "action_type": r.get("action_type"),
                "summary": r.get("summary"),
                "visible_motivation": r.get("visible_motivation"),
            }
            for r in npc_reactions
            if r.get("accepted") and r.get("visible_to_player", True)
        ]
        if player_visible_reactions:
            context["npc_reactions"] = player_visible_reactions
    
    memory_summaries = _retrieve_memories_for_context(
        db=db,
        session_id=session_id,
        scope_type="world",
        limit=3,
    )
    if memory_summaries:
        context["memory_context"] = memory_summaries
    
    return _content_public_context(db, session_id, context)


def _get_session_state_with_plan(db: Session, session_id: str) -> Any:
    """Use the read-only baseline overlay only when the durable row is absent."""
    state = SessionStateRepository(db).get_by_session(session_id)
    if state is None:
        plan = db.info.get("session_story_state_plan")
        if plan is not None and plan.session_id == session_id:
            return plan.session_state_overlay()
    return state


def _get_visible_npcs(
    db: Session,
    session_id: str,
    location_id: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Get visible NPCs at a location (public identity only).
    
    CRITICAL: Never includes hidden_identity from NPCTemplateModel.
    Only includes public_identity, name, and role_type.

    Phase 2: the stable ids the model may reference are included so the production
    prompt can list them. ``npc_id`` is the session-state id (the only NPC id
    namespace a player action may address); ``npc_template_id`` is exposed for
    audit/traceability and is *not* an addressable id.
    """
    if not location_id:
        return []
    
    npc_state_repo = SessionNPCStateRepository(db)
    npc_states = npc_state_repo.get_by_session(session_id)
    story_plan = db.info.get("session_story_state_plan")
    if story_plan is not None and story_plan.session_id == session_id:
        present_templates = {row.npc_template_id for row in npc_states}
        npc_states.extend(row for row in story_plan.npc_state_overlays() if row.npc_template_id not in present_templates)
    npc_states = _phase3_npc_projection(db, session_id, npc_states)

    visible_npcs = []
    npc_template_repo = NPCTemplateRepository(db)
    
    for npc_state in npc_states:
        if npc_state.current_location_id == location_id:
            status_flags = npc_state.status_flags or {}
            if str(status_flags.get("status", "alive")).lower() in UNAVAILABLE_NPC_STATUSES:
                continue
            npc_template = npc_template_repo.get_by_id(npc_state.npc_template_id)
            if npc_template:
                visible_npcs.append({
                    "npc_id": npc_state.id,
                    "npc_template_id": npc_state.npc_template_id,
                    "name": npc_template.name,
                    "public_identity": npc_template.public_identity,
                    "role_type": npc_template.role_type,
                    "mood": status_flags.get("mood", "neutral"),
                })
    
    return visible_npcs


def _get_active_quests(
    db: Session,
    session_id: str,
    planned_quests: Optional[Dict[str, QuestStatePlan]] = None,
) -> List[Dict[str, Any]]:
    """Get active quests for the session.

    ``planned_quests`` maps ``session_quest_states.id`` to this turn's planned
    progression update (``core/quest_progression.py``). Quest progression used to
    write its row during preparation, so this reader observed the post-advance
    status; while the write is pending the plan is applied here instead. The plan
    only replaces field values, so the row set, the iteration order and every
    returned field match what the query would have produced had the row already
    been written — including a quest that the advance completed and that must
    therefore disappear from the active list.
    """
    quest_state_repo = SessionQuestStateRepository(db)
    quest_states = quest_state_repo.get_by_session(session_id)
    story_plan = db.info.get("session_story_state_plan")
    if story_plan is not None and story_plan.session_id == session_id:
        present_templates = {row.quest_template_id for row in quest_states}
        quest_states.extend(row for row in story_plan.quest_state_overlays() if row.quest_template_id not in present_templates)
    
    active_quests = []
    quest_template_repo = QuestTemplateRepository(db)
    
    for qs in quest_states:
        status = effective_quest_status(qs, planned_quests)
        if status == "active":
            quest_template = quest_template_repo.get_by_id(qs.quest_template_id)
            if quest_template:
                plan = planned_quests.get(qs.id) if planned_quests else None
                active_quests.append({
                    "name": quest_template.name,
                    "current_step_no": plan.current_step_no if plan is not None else qs.current_step_no,
                    "status": status,
                })
    
    return active_quests


def _get_recent_events(
    db: Session,
    session_id: str,
    limit: int = 5,
    planned_events: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """Get recent event log entries for narration context.

    ``planned_events`` are this turn's event-log rows that preparation planned but
    the final transaction has not written yet (``core/turn_preparation.py``). They
    used to be flushed before the LLM stages, so the context builders saw them; the
    merge below reproduces that projection exactly.

    Equivalence: ``EventLogRepository.get_recent`` orders by ``turn_no`` DESC and
    takes ``limit`` rows, which this function then reverses. The planned rows belong
    to the current (highest) turn, so fetching ``limit + len(planned)`` database rows,
    merging and keeping the top ``limit`` by ``turn_no`` DESC yields the very same row
    set and order the query would have returned had they already been flushed — the
    planned rows simply occupy the slots they would have occupied.
    """
    planned = [event for event in (planned_events or []) if event is not None]

    event_log_repo = EventLogRepository(db)
    recent = event_log_repo.get_recent(session_id, limit=limit + len(planned))

    merged = list(recent) + planned
    # Stable sort: database rows keep their query order, planned rows (appended last)
    # stay after database rows of an equal turn_no.
    merged.sort(key=lambda event: event.turn_no, reverse=True)
    merged = merged[:limit]
    
    events = []
    for event in reversed(merged):
        events.append({
            "turn_no": event.turn_no,
            "event_type": event.event_type,
            "narrative_text": event.narrative_text,
            "input_text": event.input_text,
        })
    
    return events


def _merge_planned_game_events(
    db_rows: List[Any],
    planned_events: Optional[List[Any]],
    limit: int,
) -> List[Any]:
    """Merge planned game events into a ``GameEventRepository.get_by_session`` result.

    ``get_by_session`` orders by ``(turn_no, occurred_at)`` ascending and takes the
    first ``limit`` rows, so it returns the *oldest* rows. The planned events belong
    to the current (highest) turn and carry the ``occurred_at`` captured when the
    direct write used to happen, so fetching ``limit + len(planned)`` rows, merging
    and truncating to ``limit`` reproduces exactly the row set and order the query
    would have returned had they already been flushed.
    """
    planned = [event for event in (planned_events or []) if event is not None]
    if not planned:
        return db_rows

    merged = list(db_rows) + planned
    merged.sort(key=lambda event: (event.turn_no, event.occurred_at))
    return merged[:limit]


def _build_scene_context(
    db: Session,
    session_id: str,
    canonical_state: CanonicalState,
    player_input: str,
    action_type: str,
    movement_result: Optional[MovementResult] = None,
    state_deltas: Optional[Dict[str, Any]] = None,
    current_location_id: Optional[str] = None,
    planned_events: Optional[List[Any]] = None,
    planned_quests: Optional[Dict[str, QuestStatePlan]] = None,
) -> Dict[str, Any]:
    """
    Build scene context from committed state for scene candidate generation.
    
    Context includes:
    - Current location details
    - Player action type and input
    - Visible NPCs at location (public identity only)
    - Active quest states
    - Recent event log entries
    - Movement result (if any)
    - State deltas from this turn
    
    Returns a dict suitable for SceneEngine.generate_scene_candidates().
    """
    context: Dict[str, Any] = {
        "session_id": session_id,
        "player_input": player_input,
        "action_type": action_type,
    }
    
    session_state_repo = SessionStateRepository(db)
    session_state = _get_session_state_with_plan(db, session_id)
    
    context["current_location_id"] = current_location_id
    if session_state:
        context["world_time"] = _get_world_time(session_state)
        context["active_mode"] = session_state.active_mode
    else:
        context["world_time"] = _get_world_time(None)
    
    if current_location_id:
        location_repo = LocationRepository(db)
        location = location_repo.get_by_id(current_location_id)
        if location:
            context["current_location"] = {
                "id": location.id,
                "name": location.name,
                "code": location.code,
                "description": location.description,
            }
    
    if movement_result:
        context["movement"] = {
            "success": movement_result.success,
            "new_location_name": movement_result.new_location_name,
            "new_location_code": movement_result.new_location_code,
            "blocked_reason": movement_result.blocked_reason,
        }
    
    if state_deltas:
        context["state_deltas"] = state_deltas
    
    visible_npcs = _get_visible_npcs(db, session_id, current_location_id)
    context["visible_npcs"] = visible_npcs
    
    active_quests = _get_active_quests(db, session_id, planned_quests=planned_quests)
    context["active_quests"] = active_quests
    
    recent_events = _get_recent_events(db, session_id, limit=5, planned_events=planned_events)
    context["recent_events"] = recent_events
    
    player_state = canonical_state.player_state
    context["player_state"] = {
        "name": player_state.name,
        "realm": player_state.realm,
        "spiritual_power": player_state.spiritual_power,
        "location_id": current_location_id,
    }
    
    return _content_public_context(db, session_id, context)


def _get_active_npcs_at_location(
    db: Session,
    session_id: str,
    location_id: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Get active NPCs at a location for NPC decision stage.
    
    Returns NPCs that are:
    - At the current location
    - Alive (status == "alive")
    
    CRITICAL: Only includes public_identity, NEVER hidden_identity.
    """
    if not location_id:
        return []
    
    npc_state_repo = SessionNPCStateRepository(db)
    npc_states = npc_state_repo.get_by_session(session_id)
    story_plan = db.info.get("session_story_state_plan")
    if story_plan is not None and story_plan.session_id == session_id:
        present_templates = {row.npc_template_id for row in npc_states}
        npc_states.extend(row for row in story_plan.npc_state_overlays() if row.npc_template_id not in present_templates)
    npc_states = _phase3_npc_projection(db, session_id, npc_states)

    active_npcs = []
    npc_template_repo = NPCTemplateRepository(db)
    
    for npc_state in npc_states:
        if npc_state.current_location_id != location_id:
            continue
        
        status_flags = npc_state.status_flags or {}
        if status_flags.get("status", "alive") != "alive":
            continue
        
        npc_template = npc_template_repo.get_by_id(npc_state.npc_template_id)
        if not npc_template:
            continue
        
        active_npcs.append({
            "npc_id": npc_state.id,
            "npc_template_id": npc_state.npc_template_id,
            # ``CanonicalState.npc_states`` is keyed by the NPC's canonical key
            # (template code, falling back to the template id), while the session
            # state row id is the actor binding and the DB scope. Both are carried
            # explicitly so the two namespaces are never conflated.
            "npc_canonical_id": npc_canonical_key(npc_template),
            "name": npc_template.name,
            "public_identity": npc_template.public_identity,
            "role_type": npc_template.role_type,
            "personality": npc_template.personality,
            "goals": npc_template.goals or [],
            # NOTE: trust_score/suspicion_score intentionally excluded from
            # NPC decision context — P10-C Memory-first: NPC decisions must be
            # driven by first-person memories, not numeric relationship scores.
            # These fields remain in DB for mood derivation and player API.
            "is_major_npc": getattr(npc_template, "is_major_npc", False),
            "mood": status_flags.get("mood", "neutral"),
            "current_location_id": npc_state.current_location_id,
        })
    
    return active_npcs


def _build_npc_context(
    db: Session,
    session_id: str,
    npc_id: str,
    npc_template_id: str,
    canonical_state: CanonicalState,
    player_input: str,
    action_type: str,
    movement_result: Optional[MovementResult] = None,
    state_deltas: Optional[Dict[str, Any]] = None,
    current_location_id: Optional[str] = None,
    recent_npc_actions: Optional[List[Dict[str, Any]]] = None,
    planned_events: Optional[List[Any]] = None,
    planned_game_events: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Build NPC context for LLM NPC decision generation.
    
    CRITICAL: Only includes player-visible facts. No hidden NPC info.
    
    Context includes:
    - NPC public identity, personality, goals
    - Current location
    - Perceived events (filtered by NPCVisibleProjectionBuilder)
    - Perception constraints
    - Player action context
    - Other NPCs' visible reactions (from sequential processing)
    - NPC subjective memories (scoped by NPC ID)
    
    NEVER includes:
    - hidden_identity from NPCTemplateModel
    - hidden_plan_state from SessionNPCStateModel
    - private_payload from events
    - trust_score / suspicion_score (P10-C Memory-first: decisions driven by memories, not scores)
    """
    from ..models.events import GameEvent, EventType
    from ..models.perspectives import NPCPerspective
    
    npc_template_repo = NPCTemplateRepository(db)
    npc_template = npc_template_repo.get_by_id(npc_template_id)
    
    if not npc_template:
        return {}
    
    npc_state_repo = SessionNPCStateRepository(db)
    npc_states = npc_state_repo.get_by_session(session_id)
    story_plan = db.info.get("session_story_state_plan")
    if story_plan is not None and story_plan.session_id == session_id:
        present_templates = {row.npc_template_id for row in npc_states}
        npc_states.extend(row for row in story_plan.npc_state_overlays() if row.npc_template_id not in present_templates)
    npc_state = None
    for ns in npc_states:
        if ns.id == npc_id:
            npc_state = ns
            break

    # Phase 3: the advance's final position *overrides* the durable row, so the NPC
    # prompt describes the scene the player will be in when the turn commits rather
    # than a position the world already left behind.
    phase3_overlay = (db.info.get("phase3_npc_overlay") or {}).get("by_npc_state_id") or {}
    override = phase3_overlay.get(npc_id) if npc_id else None

    # Determine NPC location
    if override and override.get("current_location_id"):
        npc_location_id = override["current_location_id"]
    else:
        npc_location_id = npc_state.current_location_id if npc_state else current_location_id
    
    context: Dict[str, Any] = {
        "npc_id": npc_id,
        "npc_name": npc_template.name,
        "public_identity": npc_template.public_identity,
        "role_type": npc_template.role_type,
        "personality": npc_template.personality,
        "goals": npc_template.goals or [],
        "constraints": [
            "只能基于已知事实和可见信息做出决策",
            "不能泄露隐藏身份或秘密计划",
            "行动必须符合角色性格和目标",
        ],
    }
    
    if npc_state:
        # trust_score/suspicion_score intentionally excluded from NPC
        # decision context — P10-C Memory-first architecture
        status_flags = npc_state.status_flags or {}
        context["mood"] = status_flags.get("mood", "neutral")
        context["current_location_id"] = npc_location_id
    
    context["player_action"] = {
        "input": player_input,
        "action_type": action_type,
    }
    
    if movement_result:
        context["player_action"]["movement"] = {
            "success": movement_result.success,
            "new_location_name": movement_result.new_location_name,
        }
    
    if state_deltas:
        context["state_deltas"] = state_deltas
    
    # Use NPCVisibleProjectionBuilder to filter events for NPC perspective
    game_event_repo = GameEventRepository(db)
    planned_game_event_rows = [event for event in (planned_game_events or []) if event is not None]
    recent_event_models = _merge_planned_game_events(
        game_event_repo.get_by_session(session_id, limit=10 + len(planned_game_event_rows)),
        planned_game_event_rows,
        limit=10,
    )
    
    if recent_event_models:
        # Convert GameEventModel to GameEvent Pydantic model
        recent_game_events = []
        for em in recent_event_models:
            try:
                event = GameEvent(
                    event_id=em.id,
                    event_type=EventType(em.event_type),
                    turn_index=em.turn_no,
                    timestamp=em.occurred_at,
                    metadata=em.public_payload_json or {},
                )
                recent_game_events.append(event)
            except Exception:
                continue
        
        if recent_game_events:
            # Build NPC perspective for projection
            npc_perspective = NPCPerspective(
                perspective_id=f"npc_{npc_id}",
                owner_id=npc_id,
                npc_id=npc_id,
                known_facts=getattr(npc_state, "known_fact_ids", []) if npc_state else [],
                forbidden_knowledge=getattr(npc_template, "forbidden_knowledge", []) if npc_template else [],
            )
            
            # Create projection builder
            perception_resolver = PerceptionResolver()
            npc_projection_builder = NPCVisibleProjectionBuilder(perception_resolver)
            
            # Build projection context
            projection_context = {
                "npc_location_id": npc_location_id or "unknown",
                "current_turn": canonical_state.world_state.current_turn if hasattr(canonical_state.world_state, 'current_turn') else 0,
            }
            
            # Get perceived events filtered by NPC perspective
            perceived_events = npc_projection_builder.build_projection(
                events=recent_game_events,
                perspective=npc_perspective,
                context=projection_context,
            )
            
            context["perceived_events"] = perceived_events
            
            # Add perception constraints based on NPC perspective
            perception_constraints = [
                "只能感知当前位置发生的事件",
                "无法感知被标记为隐藏的事件",
                "无法获取禁止知识相关的事件",
            ]
            
            if npc_perspective.forbidden_knowledge:
                perception_constraints.append(
                    f"禁止知识: {', '.join(npc_perspective.forbidden_knowledge[:3])}"
                )
            
            context["perception_constraints"] = perception_constraints
        else:
            # Fallback to simple recent events if no GameEvent objects
            recent_events = _get_recent_events(
                db, session_id, limit=3, planned_events=planned_events
            )
            context["recent_events"] = recent_events
    else:
        # Fallback to simple recent events if no events in DB
        recent_events = _get_recent_events(
            db, session_id, limit=3, planned_events=planned_events
        )
        context["recent_events"] = recent_events
    
    if recent_npc_actions:
        context["recent_npc_reactions"] = [
            {
                "npc_name": action.get("npc_name"),
                "summary": action.get("summary"),
            }
            for action in recent_npc_actions
        ]
    
    # Retrieve NPC subjective memories (scoped by NPC ID)
    npc_memories = _retrieve_memories_for_context(
        db=db,
        session_id=session_id,
        scope_type="npc",
        scope_ref_id=npc_id,
        limit=5,
    )
    if npc_memories:
        context["subjective_memories"] = npc_memories
    
    npc_db_memories = _retrieve_npc_db_memories_for_context(
        db=db,
        session_id=session_id,
        npc_id=npc_id,
        limit=5,
    )
    if npc_db_memories:
        context["npc_db_memories"] = npc_db_memories
    
    # P10-C Phase 6: Enrich with retrieved private memories for major NPCs
    if npc_template_id:
        try:
            from .npc_decision_adapter import enrich_major_npc_decision_context
            context = enrich_major_npc_decision_context(
                npc_context=context,
                db=db,
                session_id=session_id,
                npc_template_id=npc_template_id,
                query=player_input,
                current_turn=canonical_state.world_state.current_turn if hasattr(canonical_state.world_state, 'current_turn') else 0,
            )
        except Exception:
            pass  # Non-fatal: fall through with un-enriched context
    
    return context


def _validate_npc_action(
    proposal: Any,
    npc_context: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    Validate an NPC action proposal.
    
    Checks:
    - proposal is not None
    - proposal has required fields (npc_id, action_type, summary)
    - No forbidden info leaks in summary/motivation
    - visibility is valid
    
    Returns (is_valid, validation_errors).
    """
    errors = []
    
    if proposal is None:
        return (False, ["proposal is None"])
    
    if not hasattr(proposal, "npc_id"):
        errors.append("proposal missing npc_id")
    
    if not hasattr(proposal, "action_type"):
        errors.append("proposal missing action_type")
    
    if not hasattr(proposal, "summary"):
        errors.append("proposal missing summary")
    
    if hasattr(proposal, "summary") and proposal.summary:
        forbidden_patterns = ["隐藏身份", "真实身份", "hidden_identity", "secret_identity"]
        for pattern in forbidden_patterns:
            if pattern in proposal.summary:
                errors.append(f"forbidden pattern in summary: {pattern}")
    
    if hasattr(proposal, "visible_motivation") and proposal.visible_motivation:
        forbidden_patterns = ["隐藏身份", "真实身份", "hidden_identity", "secret_identity"]
        for pattern in forbidden_patterns:
            if pattern in proposal.visible_motivation:
                errors.append(f"forbidden pattern in visible_motivation: {pattern}")
    
    if hasattr(proposal, "visibility"):
        valid_visibility = ["player_visible", "hidden", "gm_only"]
        if proposal.visibility not in valid_visibility:
            errors.append(f"invalid visibility: {proposal.visibility}")
    
    return (len(errors) == 0, errors)


def _execute_npc_stage(
    db: Session,
    session_id: str,
    turn_no: int,
    canonical_state: CanonicalState,
    player_input: str,
    action_type: str,
    movement_result: Optional[MovementResult] = None,
    state_deltas: Optional[Dict[str, Any]] = None,
    current_location_id: Optional[str] = None,
    recent_npc_actions: Optional[List[Dict[str, Any]]] = None,
    use_mock: bool = False,
    write_buffer: Optional[TurnWriteBuffer] = None,
) -> LLMStageResult:
    """
    Execute the NPC LLM stage.
    
    1. Check if enabled via feature flag
    2. Get active NPCs at current location
    3. For each active NPC, build context and call ProposalPipeline.generate_npc_action()
    4. Validate each NPC action
    5. Return LLMStageResult with accepted/rejected status and NPC reactions
    
    NPCs are processed sequentially, with each NPC seeing the reactions of previous NPCs.
    """
    from ..llm.proposal_pipeline import ProposalPipeline, ProposalConfig
    
    stage_name: LLMStageName = "npc"
    
    enabled = _is_npc_stage_enabled(db)
    if not enabled:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=False,
            timeout=30.0,
            accepted=False,
            fallback_reason="npc_stage_disabled",
        )
    
    active_npcs = _get_active_npcs_at_location(db, session_id, current_location_id)
    
    if not active_npcs:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=30.0,
            accepted=True,
            parsed_proposal={"npc_reactions": []},
        )
    
    try:
        from ..services.settings import SystemSettingsService
        from ..llm.stage_provider_resolver import resolve_stage_llm_config
        
        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()
        
        stage_config = resolve_stage_llm_config(stage_name, provider_config, use_mock=use_mock)
        
        # Merge stage-level provider_mode/default_model into config for _create_llm_service_from_config
        merged_config = dict(provider_config)
        merged_config["provider_mode"] = stage_config.provider_mode
        merged_config["default_model"] = stage_config.default_model
        
        llm_service = _create_llm_service_from_config(
            db,
            merged_config,
            force_mock=use_mock,
        )
        
        pipeline_config = ProposalConfig(
            timeout_seconds=stage_config.timeout_seconds,
            max_tokens=stage_config.max_tokens,
            temperature=stage_config.temperature,
        )
        pipeline = ProposalPipeline(llm_service=llm_service, config=pipeline_config)
        
    except LLMConfigurationError:
        raise
    except Exception as e:
        logger.warning("Failed to configure LLM service for NPC stage: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            accepted=False,
            fallback_reason=f"llm_config_error: {str(e)[:200]}",
        )
    
    npc_reactions: List[Dict[str, Any]] = []
    npc_contracts: Dict[str, Any] = {}
    npc_resolutions: Dict[str, ResolvedAction] = {}
    working_recent_actions = list(recent_npc_actions) if recent_npc_actions else []
    world_id_for_auth = _session_world_id(db, session_id, canonical_state)
    visible_npc_ids = {npc["npc_id"] for npc in active_npcs}
    allowed_event_ids = _planned_game_event_ids(write_buffer)
    
    for npc in active_npcs:
        npc_id = npc["npc_id"]
        npc_template_id = npc["npc_template_id"]
        npc_name = npc["name"]
        
        npc_context = _build_npc_context(
            db=db,
            session_id=session_id,
            npc_id=npc_id,
            npc_template_id=npc_template_id,
            canonical_state=canonical_state,
            player_input=player_input,
            action_type=action_type,
            movement_result=movement_result,
            state_deltas=state_deltas,
            current_location_id=current_location_id,
            recent_npc_actions=working_recent_actions,
            planned_events=write_buffer.planned_event_logs() if write_buffer else None,
            planned_game_events=write_buffer.planned_game_events() if write_buffer else None,
        )
        
        if not npc_context:
            continue
        
        try:
            # npc_context and the NPC fields retained from active_npcs are plain data.
            _end_read_transaction(db)
            outcome = _run_async_safe(
                pipeline.generate_npc_action_production(
                    npc_id=npc_id,
                    npc_context=npc_context,
                    prompt_template_id="npc_action_v2",
                    session_id=session_id,
                    turn_no=turn_no,
                )
            )
            
            if not outcome.accepted:
                npc_reactions.append(_npc_fallback_reaction(
                    npc_id, npc_name, _contract_fallback_reason(outcome)
                ))
                continue
            
            contract: NPCActionV2 = outcome.contract  # type: ignore[assignment]
            
            # The actor is bound here, from the stage's own iteration over this
            # session's active NPCs — never from the wire. The available memory set
            # is exactly what this call supplied (``None`` means "none supplied",
            # which permits no memory reference at all).
            auth_context = _build_authorization_context(
                db=db,
                session_id=session_id,
                world_id=world_id_for_auth,
                turn_no=turn_no,
                canonical_state=canonical_state,
                current_location_id=current_location_id,
                visible_npc_ids=visible_npc_ids,
                available_memory_ids=npc_context.get("used_memory_ids"),
                allowed_event_ids=allowed_event_ids,
            )
            authorization = authorize_npc_action(
                auth_context,
                contract,
                npc_id=npc_id,
                npc_template_id=npc_template_id,
                npc_name=npc_name,
            )
            
            if not authorization.authorized:
                # An unauthorized NPC reference is refused, never normalized into
                # an accepted action: memory ids, actor identity and targets are all
                # permission-bearing, so a failure here must not be softened.
                public_reason = authorization.public_reason or ActionReasonCode.INVALID_PARAMS
                npc_reactions.append(_npc_fallback_reaction(
                    npc_id,
                    npc_name,
                    f"authorization_rejected: {public_reason.value}",
                    detail_code=authorization.detail_code,
                ))
                continue
            
            action = authorization.action
            resolution = resolve_npc_action(action)
            reaction = _npc_action_projection(
                contract, npc_id, npc_name, action.visible_to_player
            )
            reaction["accepted"] = True
            reaction["npc_template_id"] = npc_template_id
            reaction["npc_canonical_id"] = npc.get("npc_canonical_id") or npc_id
            if action.used_memory_ids:
                reaction["used_memory_ids"] = list(action.used_memory_ids)
            
            npc_contracts[npc_id] = contract
            npc_resolutions[npc_id] = resolution
            
            if action.visible_to_player:
                working_recent_actions.append({
                    "npc_name": npc_name,
                    "summary": contract.summary,
                })
            
            npc_reactions.append(reaction)
            
        except asyncio.TimeoutError:
            npc_reactions.append(_npc_fallback_reaction(npc_id, npc_name, "timeout"))
        except Exception as e:
            logger.warning("NPC action generation failed for %s: %s", npc_id, e)
            npc_reactions.append(_npc_fallback_reaction(npc_id, npc_name, f"error: {str(e)[:200]}"))
    
    accepted_count = sum(1 for r in npc_reactions if r.get("accepted", False))
    
    return LLMStageResult(
        stage_name=stage_name,
        enabled=True,
        timeout=stage_config.timeout_seconds,
        raw_outcome=str(npc_reactions)[:500],
        parsed_proposal={"npc_reactions": npc_reactions},
        accepted=accepted_count > 0,
        config_source=stage_config.config_source,
        fallback_used=stage_config.fallback_used,
        contract=npc_contracts or None,
        resolution=npc_resolutions or None,
    )


def _execute_llm_stages(
    db: Session,
    session_id: str,
    turn_no: int,
    canonical_state: CanonicalState,
    player_input: str,
    action_type: str = "action",
    movement_result: Optional[MovementResult] = None,
    state_deltas: Optional[Dict[str, Any]] = None,
    current_location_id: Optional[str] = None,
    use_mock: bool = False,
    transaction_id: Optional[str] = None,
    progress_callback: Optional[Callable[[TurnProgressEvent], None]] = None,
    turn_event_callback: Optional[Callable[[dict], None]] = None,
    write_buffer: Optional[TurnWriteBuffer] = None,
    planned_quests: Optional[Dict[str, QuestStatePlan]] = None,
    deterministic_recommended_actions: Optional[List[str]] = None,
    *,
    narration_context_out: Dict[str, Any],
    narration_forbidden_info_out: Optional[List[Any]] = None,
) -> List[LLMStageResult]:
    """
    Execute LLM-enabled stages for a turn (excluding input_intent which runs earlier).
    
    Stage order:
    0. World stage - generate world progression candidates (pressure, flags, timers)
    1. Scene stage - generate scene event candidates and recommended actions
    2. NPC stage - generate NPC reactions (after scene, before narration)
    3. Narration stage - generate narrative text
    
    Note: input_intent stage runs before this function, in execute_turn_service().
    
    Each stage is feature-flagged via SystemSettingsService.
    Proposals are validated before acceptance.
    Fallback to deterministic behavior on timeout/parse failure/validation rejection.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        turn_no: The allocated turn number
        canonical_state: Reconstructed canonical state (read-only)
        player_input: The player's input text
        action_type: The parsed action type
        movement_result: Optional movement result from this turn
        state_deltas: Optional state deltas from this turn
        current_location_id: The current location ID after any movement
        progress_callback: Optional callback for progress events
        write_buffer: Optional preparation write buffer. Its planned rows are the
            rows this turn will write in the final transaction, so every context
            builder merges them in to keep seeing this turn's events exactly as it
            did when preparation flushed them.
        planned_quests: Optional map of this turn's planned quest-progression
            updates, merged into ``active_quests`` by the context builders for the
            same reason (see ``_get_active_quests``).
        
    Returns:
        List of LLMStageResult objects, one per stage executed
    """
    def _emit(stage: str, phase: str, **kw):
        if progress_callback:
            progress_callback(emit_stage(stage, phase, **kw))
    
    def _emit_turn_event(event: dict) -> None:
        if turn_event_callback:
            turn_event_callback(event)
    
    results: List[LLMStageResult] = []
    
    _emit("world_stage", "started")
    # A prior stage's post-model validation/audit may have read through this Session.
    _end_read_transaction(db)
    world_result = _execute_world_stage(
        db=db,
        session_id=session_id,
        turn_no=turn_no,
        canonical_state=canonical_state,
        current_location_id=current_location_id,
        use_mock=use_mock,
        transaction_id=transaction_id,
        write_buffer=write_buffer,
        planned_quests=planned_quests,
    )
    results.append(world_result)
    _emit("world_stage", "completed")
    
    _emit("scene_stage", "started")
    _end_read_transaction(db)
    scene_result = _execute_scene_stage(
        db=db,
        session_id=session_id,
        turn_no=turn_no,
        canonical_state=canonical_state,
        player_input=player_input,
        action_type=action_type,
        movement_result=movement_result,
        state_deltas=state_deltas,
        current_location_id=current_location_id,
        use_mock=use_mock,
        transaction_id=transaction_id,
        write_buffer=write_buffer,
        planned_quests=planned_quests,
        deterministic_recommended_actions=deterministic_recommended_actions,
    )
    results.append(scene_result)
    _emit("scene_stage", "completed")
    
    _emit("npc_stage", "started")
    _end_read_transaction(db)
    if db.info.get("content_runtime_context") is not None:
        # Content NPC plans advance only at deterministic engine boundaries. Build
        # their scoped decision contexts (including eligible private memories) for
        # the closed-loop read path, but do not submit LLM-managed NPC actions.
        content_npc_contexts = {}
        for npc in _get_active_npcs_at_location(db, session_id, current_location_id):
            content_npc_contexts[npc["npc_id"]] = _build_npc_context(
                db=db,
                session_id=session_id,
                npc_id=npc["npc_id"],
                npc_template_id=npc["npc_template_id"],
                canonical_state=canonical_state,
                player_input=player_input,
                action_type=action_type,
                movement_result=movement_result,
                state_deltas=state_deltas,
                current_location_id=current_location_id,
                planned_game_events=write_buffer.planned_game_events() if write_buffer else None,
            )
        db.info["content_npc_decision_contexts"] = content_npc_contexts
        npc_result = LLMStageResult(
            stage_name="npc",
            enabled=False,
            timeout=30.0,
            accepted=False,
            fallback_reason="content_v1_engine_managed",
            parsed_proposal={"npc_reactions": []},
        )
    else:
        npc_result = _execute_npc_stage(
            db=db,
            session_id=session_id,
            turn_no=turn_no,
            canonical_state=canonical_state,
            player_input=player_input,
            action_type=action_type,
            movement_result=movement_result,
            state_deltas=state_deltas,
            current_location_id=current_location_id,
            use_mock=use_mock,
            write_buffer=write_buffer,
        )
    results.append(npc_result)
    npc_name_for_progress: Optional[str] = None
    if npc_result.accepted and npc_result.parsed_proposal:
        npc_reactions = npc_result.parsed_proposal.get("npc_reactions", [])
        if npc_reactions:
            npc_name_for_progress = npc_reactions[0].get("npc_name")
    _emit("npc_stage", "completed", actor_name=npc_name_for_progress)
    
    npc_reactions_for_narration: List[Dict[str, Any]] = []
    if npc_result.accepted and npc_result.parsed_proposal:
        npc_reactions_for_narration = npc_result.parsed_proposal.get("npc_reactions", [])
    
    # Freeze the complete player-visible narration context while this turn's
    # preparation overlay is available. The later post-commit model call receives
    # only this plain-data snapshot and never reconstructs context from newer state.
    if narration_context_out is not None:
        frozen_context = _build_narration_context(
            db=db,
            session_id=session_id,
            canonical_state=canonical_state,
            player_input=player_input,
            action_type=action_type,
            movement_result=movement_result,
            state_deltas=state_deltas,
            current_location_id=current_location_id,
            planned_events=write_buffer.planned_event_logs() if write_buffer else None,
            planned_game_events=write_buffer.planned_game_events() if write_buffer else None,
            planned_quests=planned_quests,
        )
        if npc_reactions_for_narration:
            visible_reactions = [
                {
                    "npc_name": reaction.get("npc_name"),
                    "action_type": reaction.get("action_type"),
                    "summary": reaction.get("summary"),
                    "visible_to_player": reaction.get("visible_to_player", True),
                }
                for reaction in npc_reactions_for_narration
                if reaction.get("visible_to_player", True) and reaction.get("accepted", False)
            ]
            if visible_reactions:
                frozen_context["npc_reactions"] = visible_reactions
        narration_context_out.clear()
        narration_context_out.update(jsonable_encoder(frozen_context))
        # Freeze hidden facts separately; they are validation inputs only and are
        # never sent to the narration model as part of its visible context.
        narration_forbidden_info = _load_frozen_narration_forbidden_facts(
            db,
            session_id,
            canonical_state,
            db.info.get("session_story_state_plan"),
        )
        if narration_forbidden_info_out is not None:
            narration_forbidden_info_out.clear()
            narration_forbidden_info_out.extend(narration_forbidden_info)
    
    # Narration is deliberately not streamed here: the turn has not crossed
    # its durable commit boundary yet. The streaming endpoint emits the saved
    # TurnResult snapshot only after execute_turn_service returns.
    return results


def _execute_narration_stage(
    db: Session,
    session_id: str,
    turn_no: int,
    canonical_state: CanonicalState,
    player_input: str,
    action_type: str,
    movement_result: Optional[MovementResult] = None,
    state_deltas: Optional[Dict[str, Any]] = None,
    current_location_id: Optional[str] = None,
    npc_reactions: Optional[List[Dict[str, Any]]] = None,
    use_mock: bool = False,
    write_buffer: Optional[TurnWriteBuffer] = None,
    planned_quests: Optional[Dict[str, QuestStatePlan]] = None,
    frozen_context: Optional[Dict[str, Any]] = None,
) -> LLMStageResult:
    """
    Execute the narration LLM stage.
    
    1. Check if enabled via feature flag
    2. Build narration context from committed state
    3. Call LLM via ProposalPipeline.generate_narration()
    4. Validate output (non-empty, no forbidden info)
    5. Return LLMStageResult
    """
    from ..llm.proposal_pipeline import ProposalPipeline, ProposalConfig
    
    stage_name: LLMStageName = "narration"

    enabled = _is_narration_stage_enabled(db)
    if not enabled:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=False,
            timeout=30.0,
            accepted=False,
            fallback_reason="narration_stage_disabled",
        )
    
    narration_context = frozen_context
    if narration_context is None:
        # Preserve the historical standalone behavior for other callers/tests.
        narration_context = _build_narration_context(
            db=db,
            session_id=session_id,
            canonical_state=canonical_state,
            player_input=player_input,
            action_type=action_type,
            movement_result=movement_result,
            state_deltas=state_deltas,
            current_location_id=current_location_id,
            npc_reactions=npc_reactions,
            planned_events=write_buffer.planned_event_logs() if write_buffer else None,
            planned_game_events=write_buffer.planned_game_events() if write_buffer else None,
            planned_quests=planned_quests,
        )
        if npc_reactions:
            visible_reactions = [
                {
                    "npc_name": r.get("npc_name"),
                    "action_type": r.get("action_type"),
                    "summary": r.get("summary"),
                    "visible_to_player": r.get("visible_to_player", True),
                }
                for r in npc_reactions
                if r.get("visible_to_player", True) and r.get("accepted", False)
            ]
            if visible_reactions:
                narration_context["npc_reactions"] = visible_reactions
    
    try:
        from ..services.settings import SystemSettingsService
        from ..llm.stage_provider_resolver import resolve_stage_llm_config

        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()

        stage_config = resolve_stage_llm_config(stage_name, provider_config, use_mock=use_mock)

        # Merge stage-level provider_mode/default_model into config for _create_llm_service_from_config
        merged_config = dict(provider_config)
        merged_config["provider_mode"] = stage_config.provider_mode
        merged_config["default_model"] = stage_config.default_model

        llm_service = _create_llm_service_from_config(
            db,
            merged_config,
            force_mock=use_mock,
        )

        pipeline_config = ProposalConfig(
            timeout_seconds=stage_config.timeout_seconds,
            max_tokens=stage_config.max_tokens,
            temperature=stage_config.temperature,
        )
        pipeline = ProposalPipeline(llm_service=llm_service, config=pipeline_config)

    except LLMConfigurationError:
        raise
    except Exception as e:
        logger.warning("Failed to configure LLM service for narration: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            accepted=False,
            fallback_reason=f"llm_config_error: {str(e)[:200]}",
        )
    
    try:
        # narration_context is the complete plain-data model input.
        _end_read_transaction(db)
        outcome = _run_async_safe(
            pipeline.generate_narration_production(
                visible_context=narration_context,
                prompt_template_id="narration_v2",
                session_id=session_id,
                turn_no=turn_no,
            )
        )

        if not outcome.accepted:
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=stage_config.timeout_seconds,
                accepted=False,
                fallback_reason=_contract_fallback_reason(outcome),
                raw_outcome=outcome.raw_output_preview or None,
                contract_reason_code=outcome.reason_code,
                validation_errors=[_contract_fallback_reason(outcome)],
            )

        contract: NarrationV2 = outcome.contract  # type: ignore[assignment]
        narration_text = contract.text
        
        if not narration_text or not narration_text.strip():
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=stage_config.timeout_seconds,
                accepted=False,
                fallback_reason="empty_narration_text",
                raw_outcome=contract.model_dump_json()[:500],
            )
        
        forbidden_leaks = _check_forbidden_info_leaks(narration_context, narration_text)
        if forbidden_leaks:
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=stage_config.timeout_seconds,
                accepted=False,
                fallback_reason=f"forbidden_info_leak: {', '.join(forbidden_leaks[:3])}",
                raw_outcome=narration_text[:500],
                validation_errors=[f"Forbidden info detected: {info}" for info in forbidden_leaks],
            )
        
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            raw_outcome=narration_text[:500],
            parsed_proposal={"text": narration_text},
            accepted=True,
            config_source=stage_config.config_source,
            fallback_used=stage_config.fallback_used,
        )
        
    except asyncio.TimeoutError:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            accepted=False,
            fallback_reason="timeout",
        )
    except Exception as e:
        logger.warning("LLM narration stage failed: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            accepted=False,
            fallback_reason=f"error: {str(e)[:200]}",
        )


def _create_llm_service_from_config(
    db: Session,
    provider_config: Dict[str, Any],
    force_mock: bool = False,
) -> LLMService:
    """
    Create an LLMService configured from SystemSettingsService.
    
    Provider mode semantics:
    - 'mock': Always returns MockLLMProvider
    - 'auto': Uses OpenAI if key available, otherwise MockLLMProvider (silent fallback)
    - 'openai': Requires OpenAI API key; raises LLMConfigurationError if unavailable
    - 'custom': Requires custom base URL AND custom API key; raises LLMConfigurationError if either unavailable

    Raises:
        LLMConfigurationError: When 'openai' or 'custom' mode is configured but required
            credentials are unavailable.
    """
    from ..llm.service import OpenAIProvider
    
    if force_mock:
        return LLMService(provider=MockLLMProvider(), db_session=db)

    provider_mode = provider_config.get("provider_mode", "auto")
    default_model = provider_config.get("default_model", "gpt-4")
    
    from ..services.settings import SystemSettingsService
    settings_service = SystemSettingsService(db)
    
    if provider_mode == "mock":
        return LLMService(provider=MockLLMProvider(), db_session=db)

    if provider_mode == "custom":
        try:
            base_url = settings_service.get_effective_custom_base_url()
        except Exception as e:
            raise LLMConfigurationError(
                message=f"Custom provider mode requires readable custom_base_url configuration: {str(e)[:200]}",
                provider_mode="custom",
                missing_config="custom_base_url",
            ) from e

        try:
            api_key = settings_service.get_effective_custom_api_key()
        except Exception as e:
            raise LLMConfigurationError(
                message=f"Custom provider mode requires readable custom_api_key configuration: {str(e)[:200]}",
                provider_mode="custom",
                missing_config="custom_api_key",
            ) from e

        if not base_url:
            raise LLMConfigurationError(
                message="Custom provider mode requires custom_base_url configuration",
                provider_mode="custom",
                missing_config="custom_base_url",
            )
        if not api_key:
            raise LLMConfigurationError(
                message="Custom provider mode requires custom_api_key configuration",
                provider_mode="custom",
                missing_config="custom_api_key",
            )

        provider = OpenAIProvider(
            api_key=api_key,
            model=default_model,
            base_url=base_url,
        )
        return LLMService(provider=provider, db_session=db)

    if provider_mode == "openai":
        try:
            api_key = settings_service.get_effective_openai_key()
        except Exception as e:
            raise LLMConfigurationError(
                message=f"OpenAI provider mode requires readable OPENAI_API_KEY: {str(e)[:200]}",
                provider_mode="openai",
                missing_config="openai_api_key",
            ) from e

        if not api_key:
            raise LLMConfigurationError(
                message="OpenAI provider mode requires OPENAI_API_KEY",
                provider_mode="openai",
                missing_config="openai_api_key",
            )

        provider = OpenAIProvider(
            api_key=api_key,
            model=default_model,
        )
        return LLMService(provider=provider, db_session=db)

    # provider_mode == "auto" (or any unrecognized mode)
    api_key = settings_service.get_effective_openai_key()
    if api_key:
        provider = OpenAIProvider(
            api_key=api_key,
            model=default_model,
        )
        return LLMService(provider=provider, db_session=db)
    
    return LLMService(provider=MockLLMProvider(), db_session=db)


def _check_forbidden_info_leaks(
    narration_context: Dict[str, Any],
    narration_text: str,
) -> List[str]:
    """
    Check if narration text leaks forbidden information.
    
    Forbidden info includes:
    - NPC hidden_identity values
    - Any info that should not be player-visible
    """
    leaks = []
    
    visible_npcs = narration_context.get("visible_npcs", [])
    for npc in visible_npcs:
        hidden = npc.get("hidden_identity")
        if hidden and hidden in narration_text:
            leaks.append(f"hidden_identity leak: {hidden[:50]}")
    
    forbidden_patterns = [
        "隐藏身份",
        "真实身份",
        "秘密身份",
        "hidden_identity",
        "secret_identity",
    ]
    for pattern in forbidden_patterns:
        if pattern in narration_text:
            leaks.append(f"forbidden pattern: {pattern}")
    
    return leaks


def _validate_scene_proposal(
    proposal: Any,
    scene_context: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    Validate a scene event proposal.
    
    Checks:
    - proposal is not None
    - proposal has required fields (scene_id, candidate_events)
    - candidate_events have valid structure
    - No forbidden info leaks in event descriptions
    - recommended_actions (if present) is a list of strings, max 4
    
    Returns (is_valid, validation_errors).
    """
    errors = []
    
    if proposal is None:
        return (False, ["proposal is None"])
    
    if not hasattr(proposal, "scene_id"):
        errors.append("proposal missing scene_id")
    
    if not hasattr(proposal, "candidate_events"):
        errors.append("proposal missing candidate_events")
    else:
        candidate_events = proposal.candidate_events
        if not isinstance(candidate_events, list):
            errors.append("candidate_events is not a list")
        else:
            for i, event in enumerate(candidate_events):
                if not hasattr(event, "event_type"):
                    errors.append(f"candidate_event[{i}] missing event_type")
                if not hasattr(event, "description"):
                    errors.append(f"candidate_event[{i}] missing description")
    
    if hasattr(proposal, "recommended_actions"):
        rec_actions = proposal.recommended_actions
        if rec_actions is not None:
            if not isinstance(rec_actions, list):
                errors.append("recommended_actions is not a list")
            else:
                if len(rec_actions) > 4:
                    errors.append(f"recommended_actions has {len(rec_actions)} items, max 4")
                for i, action in enumerate(rec_actions):
                    if not isinstance(action, str):
                        errors.append(f"recommended_actions[{i}] is not a string")
    
    if hasattr(proposal, "candidate_events"):
        for event in proposal.candidate_events:
            if hasattr(event, "description"):
                desc = event.description
                forbidden_patterns = ["隐藏身份", "真实身份", "hidden_identity", "secret_identity"]
                for pattern in forbidden_patterns:
                    if pattern in desc:
                        errors.append(f"forbidden pattern in event description: {pattern}")
    
    return (len(errors) == 0, errors)


def _execute_scene_stage(
    db: Session,
    session_id: str,
    turn_no: int,
    canonical_state: CanonicalState,
    player_input: str,
    action_type: str,
    movement_result: Optional[MovementResult] = None,
    state_deltas: Optional[Dict[str, Any]] = None,
    current_location_id: Optional[str] = None,
    use_mock: bool = False,
    transaction_id: Optional[str] = None,
    write_buffer: Optional[TurnWriteBuffer] = None,
    planned_quests: Optional[Dict[str, QuestStatePlan]] = None,
    deterministic_recommended_actions: Optional[List[str]] = None,
) -> LLMStageResult:
    """
    Execute the scene LLM stage.
    
    1. Check if enabled via feature flag
    2. Build scene context from committed state
    3. Call the strict production contract (``SceneEventV2``)
    4. Authorize its references against this turn's engine events
    5. Return LLMStageResult with accepted/rejected status
    
    The scene stage may only organize results the engine already decided: it
    references this turn's engine events and selects from the engine's legal
    recommended actions. It never creates facts, effects or state changes.
    """
    from ..llm.proposal_pipeline import ProposalPipeline, ProposalConfig
    
    stage_name: LLMStageName = "scene"

    enabled = _is_scene_stage_enabled(db)
    if not enabled:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=False,
            timeout=30.0,
            accepted=False,
            fallback_reason="scene_stage_disabled",
        )
    
    scene_context = _build_scene_context(
        db=db,
        session_id=session_id,
        canonical_state=canonical_state,
        player_input=player_input,
        action_type=action_type,
        movement_result=movement_result,
        state_deltas=state_deltas,
        current_location_id=current_location_id,
        planned_events=write_buffer.planned_event_logs() if write_buffer else None,
        planned_quests=planned_quests,
    )
    # The engine's own recommended actions are the only legal set: the scene stage
    # may select from them but can never invent a player-facing hint.
    scene_context["deterministic_recommended_actions"] = list(
        deterministic_recommended_actions or []
    )
    scene_context["engine_event_ids"] = sorted(_planned_game_event_ids(write_buffer))
    
    try:
        from ..services.settings import SystemSettingsService
        from ..llm.stage_provider_resolver import resolve_stage_llm_config

        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()

        stage_config = resolve_stage_llm_config(stage_name, provider_config, use_mock=use_mock)

        # Merge stage-level provider_mode/default_model into config for _create_llm_service_from_config
        merged_config = dict(provider_config)
        merged_config["provider_mode"] = stage_config.provider_mode
        merged_config["default_model"] = stage_config.default_model

        llm_service = _create_llm_service_from_config(
            db,
            merged_config,
            force_mock=use_mock,
        )

        pipeline_config = ProposalConfig(
            timeout_seconds=stage_config.timeout_seconds,
            max_tokens=stage_config.max_tokens,
            temperature=stage_config.temperature,
        )
        pipeline = ProposalPipeline(llm_service=llm_service, config=pipeline_config)

    except LLMConfigurationError:
        raise
    except Exception as e:
        logger.warning("Failed to configure LLM service for scene stage: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            accepted=False,
            fallback_reason=f"llm_config_error: {str(e)[:200]}",
        )
    
    try:
        # scene_context and scene_id are plain data; no expired ORM value is reused.
        _end_read_transaction(db)
        scene_id = current_location_id or "unknown"

        outcome = _run_async_safe(
            pipeline.generate_scene_event_production(
                scene_id=scene_id,
                scene_context=scene_context,
                prompt_template_id="scene_event_v2",
                session_id=session_id,
                turn_no=turn_no,
            )
        )

        if not outcome.accepted:
            if transaction_id:
                _create_validation_report(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    scope="proposal_scene_event",
                    target_ref_id=scene_id,
                    is_valid=False,
                    errors_json=[_contract_fallback_reason(outcome)],
                    buffer=write_buffer,
                )
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=stage_config.timeout_seconds,
                accepted=False,
                fallback_reason=_contract_fallback_reason(outcome),
                raw_outcome=outcome.raw_output_preview or None,
                contract_reason_code=outcome.reason_code,
                validation_errors=[_contract_fallback_reason(outcome)],
            )

        contract: SceneEventV2 = outcome.contract  # type: ignore[assignment]
        allowed_event_ids = _planned_game_event_ids(write_buffer)
        auth_context = _build_authorization_context(
            db=db,
            session_id=session_id,
            world_id=_session_world_id(db, session_id, canonical_state),
            turn_no=turn_no,
            canonical_state=canonical_state,
            current_location_id=current_location_id,
            allowed_event_ids=allowed_event_ids,
            legal_recommended_actions=deterministic_recommended_actions,
        )
        authorization = authorize_scene_event(auth_context, contract)

        if not authorization.authorized:
            if transaction_id:
                _create_validation_report(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    scope="proposal_scene_event",
                    target_ref_id=scene_id,
                    is_valid=False,
                    errors_json=[str(authorization.detail_code)],
                    buffer=write_buffer,
                )
            return _apply_authorization_to_stage(
                LLMStageResult(
                    stage_name=stage_name,
                    enabled=True,
                    timeout=stage_config.timeout_seconds,
                    raw_outcome=contract.model_dump_json()[:500],
                    contract=contract,
                    contract_reason_code=outcome.reason_code,
                    config_source=stage_config.config_source,
                    fallback_used=stage_config.fallback_used,
                ),
                authorization,
                scope="scene_event",
            )

        resolution = resolve_scene_reference(authorization.action)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            raw_outcome=contract.model_dump_json()[:500],
            parsed_proposal=_scene_event_projection(contract, authorization),
            accepted=True,
            config_source=stage_config.config_source,
            fallback_used=stage_config.fallback_used,
            contract=contract,
            authorization=authorization,
            resolution=resolution,
        )
        
    except asyncio.TimeoutError:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            accepted=False,
            fallback_reason="timeout",
        )
    except Exception as e:
        logger.warning("LLM scene stage failed: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=stage_config.timeout_seconds,
            accepted=False,
            fallback_reason=f"error: {str(e)[:200]}",
        )


def _validate_explicit_llm_config(db: Session) -> None:
    """
    Validate that explicit LLM provider modes have required configuration.

    This preflight check runs before turn allocation to ensure that 'openai' or
    'custom' provider modes fail loudly before any DB writes occur.

    Raises:
        LLMConfigurationError: When explicit provider mode lacks required config.
    """
    from ..services.settings import SystemSettingsService

    settings_service = SystemSettingsService(db)
    provider_config = settings_service.get_provider_config()
    provider_mode = provider_config.get("provider_mode", "auto")

    if provider_mode in ("mock", "auto"):
        return

    if provider_mode == "openai":
        try:
            api_key = settings_service.get_effective_openai_key()
        except Exception as e:
            raise LLMConfigurationError(
                message=f"OpenAI provider mode requires readable OPENAI_API_KEY: {str(e)[:200]}",
                provider_mode="openai",
                missing_config="openai_api_key",
            ) from e

        if not api_key:
            raise LLMConfigurationError(
                message="OpenAI provider mode requires OPENAI_API_KEY",
                provider_mode="openai",
                missing_config="openai_api_key",
            )

    if provider_mode == "custom":
        try:
            base_url = settings_service.get_effective_custom_base_url()
        except Exception as e:
            raise LLMConfigurationError(
                message=f"Custom provider mode requires readable custom_base_url configuration: {str(e)[:200]}",
                provider_mode="custom",
                missing_config="custom_base_url",
            ) from e

        try:
            api_key = settings_service.get_effective_custom_api_key()
        except Exception as e:
            raise LLMConfigurationError(
                message=f"Custom provider mode requires readable custom_api_key configuration: {str(e)[:200]}",
                provider_mode="custom",
                missing_config="custom_api_key",
            ) from e

        if not base_url:
            raise LLMConfigurationError(
                message="Custom provider mode requires custom_base_url configuration",
                provider_mode="custom",
                missing_config="custom_base_url",
            )
        if not api_key:
            raise LLMConfigurationError(
                message="Custom provider mode requires custom_api_key configuration",
                provider_mode="custom",
                missing_config="custom_api_key",
            )


class TurnStateConflictError(TurnServiceError):
    """The authoritative session state changed while a turn was being prepared."""

    code = "state_conflict"

    def __init__(self, session_id: str):
        super().__init__("Turn state changed before commit", session_id=session_id)


# ---------------------------------------------------------------------------
# Phase-3 time simulation helpers (plan section 7.1)
#
# The slice's turn branch reuses the *existing* admission chain unchanged and
# only replaces the completion half: the player's move is admitted by the
# movement validator as before, and the world advancer then decides whether that
# move actually completes, is interrupted, or is refused at the moment of
# arrival. Nothing here runs for a world without the profile.
# ---------------------------------------------------------------------------


def _phase3_advance(ctx: SimulationContext, player_action: Any) -> Any:
    """Run the pure advancer over the slice's preloaded steps.

    The advancer is imported lazily so the legacy turn path never depends on the
    slice's kernel being importable.
    """
    from .world_advancer import WorldAdvancer

    return WorldAdvancer(ctx.rules).advance(
        state=ctx.state,
        player_action=player_action,
        pending_steps=[row.step for row in ctx.pending_steps],
        consumed_step_keys=ctx.consumed_step_keys,
        start_event_seq=ctx.run_state.next_event_seq,
    )


def _content_tick_positions(context: ContentRuntimeContext, result: Any) -> Dict[int, Dict[str, Any]]:
    """Freeze the content runtime's NPC position view at each event tick."""
    positions = dict(context.state.npc_positions)
    alive = dict(context.state.npc_alive)
    snapshots: Dict[int, Dict[str, Any]] = {}
    for event in sorted(result.events, key=lambda item: (item.tick, item.phase, item.seq)):
        payload = event.public_payload or event.private_payload or {}
        if event.event_type == "npc_arrived" and isinstance(payload, dict):
            actor = payload.get("npc_id") or event.actor_code
            destination = payload.get("to")
            if actor in positions and isinstance(destination, str):
                positions[actor] = destination
        snapshots[event.tick] = {
            "npc_positions": dict(positions),
            "npc_alive": dict(alive),
        }
    return snapshots


def _write_content_engine_events(
    db: Session,
    *,
    session_id: str,
    transaction_id: str,
    turn_no: int,
    result: Any,
    planned_event_ids: Dict[int, str],
) -> None:
    """Persist content engine facts/deltas using preplanned durable event IDs."""
    event_ids_by_step: Dict[str, str] = {}
    for engine_event in result.events:
        event_id = planned_event_ids[engine_event.seq]
        event_ids_by_step.setdefault(engine_event.step_code, event_id)
        db.add(GameEventModel(
            id=event_id,
            transaction_id=transaction_id,
            session_id=session_id,
            turn_no=turn_no,
            event_type=engine_event.event_type,
            actor_id=engine_event.actor_code,
            target_ids_json=list(engine_event.target_ids) or None,
            visibility_scope=engine_event.visibility_scope,
            public_payload_json=engine_event.public_payload,
            private_payload_json=engine_event.private_payload,
            result_json={
                **(engine_event.result_json or {}),
                "engine_meta": {
                    "profile": "content_v1",
                    "logical_tick": engine_event.tick,
                    "phase": int(engine_event.phase),
                    "sequence": engine_event.seq,
                },
            },
            occurred_at=datetime.now(),
        ))
    for delta in result.deltas:
        source_event_id = event_ids_by_step.get(delta.step_code)
        if source_event_id is None:
            raise ContentRuntimeError(
                "CONTENT_BINDING_MISMATCH",
                f"content delta for step {delta.step_code!r} has no causal engine event",
            )
        db.add(StateDeltaModel(
            id=generate_uuid(),
            transaction_id=transaction_id,
            source_event_id=source_event_id,
            session_id=session_id,
            turn_no=turn_no,
            path=f"content_v1.{delta.path}",
            operation=delta.operation,
            old_value_json=delta.old_value,
            new_value_json=delta.new_value,
            visibility_scope=delta.visibility_scope,
            validation_status="valid",
            created_at=datetime.now(),
        ))
    # Cognition verifies that its source GameEvents already exist in this UoW.
    db.flush()


def _phase3_engine_message(result: Any) -> str:
    """A non-disclosing engine sentence for an interrupted / unfinished action."""
    if getattr(result, "interrupted", False):
        return "试炼钟声响起，阵法扰动打断了你正在做的事。"
    return "你的行动没有完成。"


def _phase3_reconcile_movement(
    result: Any,
    original: Optional[MovementResult],
) -> Optional[MovementResult]:
    """Replace the *admission* result with the advance's actual completion.

    Admission answers "may this move start"; the advance answers "did it arrive".
    A move that was interrupted or refused at arrival must not keep the admitted
    success: no target location, no arrival task, no success narration and no
    success count.
    """
    if original is None:
        return None
    status = result.player_result.status
    if status == PlayerActionStatus.COMPLETED:
        return original
    message = result.player_result.detail_message or _phase3_engine_message(result)
    return MovementResult(
        success=False,
        blocked_reason=message,
        narration_hint=message,
        previous_location_id=original.previous_location_id,
    )


def _phase3_resolution_summary(
    *,
    action_type: str,
    result: Any,
    fallback_used: bool,
) -> Optional[Dict[str, Any]]:
    """The public action-resolution summary of a simulated turn.

    An interrupted or arrival-refused action is reported as a rejected action in
    the *existing* v1 public vocabulary (``rejected`` / ``target_unavailable``);
    the new internal ``ACTION_INTERRUPTED`` detail stays in restricted audit.
    """
    status = result.player_result.status
    if status == PlayerActionStatus.INTERRUPTED:
        return _build_action_resolution_summary(
            action_type=action_type,
            resolution=reject_action(
                None,
                ActionDetailCode.ACTION_INTERRUPTED,
                "the action was cut short by a perceivable world event",
                reason=ActionReasonCode.TARGET_UNAVAILABLE,
            ),
            authorization=None,
            fallback_used=fallback_used,
        )
    if status == PlayerActionStatus.REFUSED and result.player_result.detail_code:
        return _build_action_resolution_summary(
            action_type=action_type,
            resolution=reject_action(
                None,
                ActionDetailCode.DOMAIN_RULE_BLOCKED,
                result.player_result.detail_message or "the action did not complete",
                reason=ActionReasonCode.TARGET_UNAVAILABLE,
            ),
            authorization=None,
            fallback_used=fallback_used,
        )
    return None


def _phase3_npc_locations(db: Session, session_id: str) -> Dict[str, str]:
    """``session_npc_states.id`` -> the advance's final location, for this turn.

    Only populated while a phase-3 turn is being prepared; every other world gets
    an empty mapping, so this is a no-op for the legacy path.
    """
    overlay = db.info.get("phase3_npc_overlay")
    if not overlay or overlay.get("session_id") != session_id:
        return {}
    return {
        state_id: values.get("current_location_id")
        for state_id, values in (overlay.get("by_npc_state_id") or {}).items()
        if values.get("current_location_id")
    }


def _phase3_npc_projection(
    db: Session,
    session_id: str,
    npc_states: List[Any],
) -> List[Any]:
    """Reader-facing NPC rows with this turn's advance values applied.

    The overlay *overrides* the durable values instead of only filling gaps: the
    model context must describe the world the player will be in when the turn
    commits, and a stale persisted position must never authorize a present-NPC
    reaction. Detached copies are used so no ORM row is marked dirty during
    preparation.
    """
    overlay = db.info.get("phase3_npc_overlay")
    if not overlay or overlay.get("session_id") != session_id:
        return list(npc_states)
    by_state_id = overlay.get("by_npc_state_id") or {}
    projected: List[Any] = []
    for row in npc_states:
        override = by_state_id.get(getattr(row, "id", None))
        if not override:
            projected.append(row)
            continue
        projected.append(
            SimpleNamespace(
                id=row.id,
                npc_template_id=row.npc_template_id,
                current_location_id=override.get(
                    "current_location_id", row.current_location_id
                ),
                status_flags=override.get("status_flags", row.status_flags),
                hidden_plan_state=override.get("hidden_plan_state"),
                trust_score=getattr(row, "trust_score", None),
                suspicion_score=getattr(row, "suspicion_score", None),
                short_memory_summary=getattr(row, "short_memory_summary", None),
            )
        )
    return projected


def compute_state_fingerprint(db: Session, session_id: str) -> str:
    """Hash decision-relevant persisted state, including row membership."""
    models_and_fields = (
        (SessionModel, ("id", "world_id", "status", "current_chapter_id")),
        (SessionStateModel, ("id", "current_time", "time_phase", "current_location_id", "active_mode", "global_flags_json")),
        (SessionPlayerStateModel, ("id", "realm_stage", "hp", "max_hp", "stamina", "spirit_power", "relation_bias_json", "conditions_json")),
        (SessionNPCStateModel, ("id", "npc_template_id", "current_location_id", "trust_score", "suspicion_score", "status_flags", "short_memory_summary", "hidden_plan_state")),
        (SessionInventoryItemModel, ("id", "item_template_id", "owner_type", "owner_ref_id", "quantity", "durability", "bound_flag")),
        (SessionQuestStateModel, ("id", "quest_template_id", "current_step_no", "progress_json", "status", "player_visibility", "revealed_at", "reveal_source_event_id", "last_revealed_step_no")),
        (SessionEventFlagModel, ("id", "flag_key", "flag_value")),
        (ScheduledEventModel, ("id", "event_template_id", "trigger_time", "trigger_conditions_json", "status")),
        (MemoryFactModel, ("id", "fact_type", "subject_ref", "fact_key", "fact_value", "confidence", "source_event_id")),
        (NPCBeliefModel, ("id", "npc_id", "belief_type", "content", "confidence", "truth_status", "source_event_id", "created_turn", "last_updated_turn")),
        (NPCPrivateMemoryModel, ("id", "npc_id", "memory_type", "content", "source_event_ids_json", "entities_json", "importance", "emotional_weight", "confidence", "current_strength", "created_turn", "last_accessed_turn", "recall_count", "memory_kind", "memory_text", "short_summary", "knowledge_source", "source_id", "source_ref", "source_turn_no", "salience", "visibility", "status", "tags_json", "entity_refs_json", "location_id", "world_time_text", "world_time_json", "checksum", "superseded_by", "contradicts_memory_ids_json", "recall_policy_json")),
        (NPCRelationshipMemoryModel, ("id", "npc_id", "target_id", "content", "impact_json", "source_event_id", "created_turn")),
    )
    state = []
    for model, fields in models_and_fields:
        membership_column = model.id if model is SessionModel else model.session_id
        rows = db.query(model).filter(membership_column == session_id).all()
        state.append((model.__tablename__, sorted(
            [{field: getattr(row, field) for field in fields} for row in rows],
            key=lambda row: str(row["id"]),
        )))

    # A content_v1 session is pinned to a four-part immutable binding. Include the
    # instance, profile/world and published artifact/materialization in the same
    # optimistic fingerprint that is rechecked after the turn lock is acquired.
    session_row = db.get(SessionModel, session_id)
    world_row = db.get(WorldModel, session_row.world_id) if session_row is not None else None
    ruleset = getattr(world_row, "ruleset_json", None)
    content_profile = ruleset.get("content_profile") if isinstance(ruleset, dict) else None
    if isinstance(content_profile, dict) and content_profile.get("id") == "content_v1":
        instance_row = db.get(PlaythroughInstanceModel, session_row.playthrough_instance_id) if session_row.playthrough_instance_id else None
        version_row = db.get(StoryPackageVersionModel, session_row.story_package_version_id) if session_row.story_package_version_id else None
        binding_state: Dict[str, Any] = {
            "session": {
                "id": session_row.id,
                "world_id": session_row.world_id,
                "playthrough_instance_id": session_row.playthrough_instance_id,
                "story_package_version_id": session_row.story_package_version_id,
            },
            "world": None if world_row is None else {
                "id": world_row.id,
                "story_package_version_id": world_row.story_package_version_id,
                "ruleset_json": world_row.ruleset_json,
            },
            "instance": None if instance_row is None else {
                "id": instance_row.id,
                "world_id": instance_row.world_id,
                "story_package_version_id": instance_row.story_package_version_id,
                "config_json": instance_row.config_json,
            },
            "version": None if version_row is None else {
                "id": version_row.id,
                "story_package_id": version_row.story_package_id,
                "status": version_row.status,
                "world_id": version_row.world_id,
                "published_at": version_row.published_at,
                "runtime_bundle_json": version_row.runtime_bundle_json,
                "runtime_hash": version_row.runtime_hash,
                "runtime_schema_version": version_row.runtime_schema_version,
            },
        }
        materialized = (
            (LocationModel, ("id", "world_id", "code", "name", "description", "tags", "access_rules", "parent_location_id", "location_type", "environment_json", "discovery_rules_json", "scene_hooks_json")),
            (NPCTemplateModel, ("id", "world_id", "code", "name", "role_type", "public_identity", "hidden_identity", "personality", "goals", "initial_location_id", "decision_profile_json")),
            (ItemTemplateModel, ("id", "world_id", "code", "name", "item_type", "description", "effects_json", "ownership_rules_json", "visibility_rules_json", "use_effects_json")),
        )
        for model, fields in materialized:
            rows = db.query(model).filter(model.world_id == session_row.world_id).all()
            binding_state[model.__tablename__] = sorted(
                [{field: getattr(row, field) for field in fields} for row in rows],
                key=lambda row: str(row["id"]),
            )
        state.append(("content_binding_and_materialization", binding_state))

    encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def execute_turn_service(
    db: Session,
    session_id: str,
    player_input: str,
    idempotency_key: Optional[str] = None,
    use_mock: bool = False,
    progress_callback: Optional[Callable[[TurnProgressEvent], None]] = None,
    turn_event_callback: Optional[Callable[[dict], None]] = None,
    request_fingerprint: Optional[str] = None,
    claim_session_factory: Optional[Callable[[], Session]] = None,
    claim_budget: Optional[TurnBudget] = None,
) -> TurnResult:
    """
    Execute a turn with full transaction support.
    
    This is the unified entry point for both streaming and non-streaming endpoints.
    
    Pipeline:
    1. Initialize session story state if needed (idempotent)
    2. Reconstruct canonical state from DB
    3. Allocate turn number (DB-authoritative)
    4. Execute input_intent LLM stage (parse player input)
    5. Parse player input and determine action type (LLM or deterministic fallback)
    6. Execute action (movement, scene, NPC, quest)
    7. Commit turn to DB (adventure log, session state, recommended actions)
    8. Execute remaining LLM stages (world, scene, NPC, narration)
    9. Return TurnResult
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        player_input: The player's input text
        idempotency_key: Optional idempotency key for retries
        request_fingerprint: **Deprecated, transport-compatibility only.** The server
            always recomputes the fingerprint from the authoritative input
            (``compute_request_fingerprint(player_input, None)``); a client-supplied
            value never takes part in claim adjudication, because trusting it would let
            a caller forge a match and bypass same-key/different-input conflict
            detection. The claim row stores the recomputed value.
        claim_session_factory: Optional factory for the independent Session the claim
            heartbeat renews the lease from. Must connect to the same database.
        claim_budget: Optional service-level budget for this turn (default
            ``TurnBudget(DEFAULT_TURN_BUDGET_SECONDS)``, 600s unless
            ``TURN_TOTAL_BUDGET_SECONDS`` overrides it). Once expired, the lease stops
            being renewed and an uncommitted turn is refused with
            ``TurnBudgetExceededError``.
        turn_event_callback: Optional callback for post-commit turn events. Fact narration
            is emitted by the streaming endpoint only after the authoritative commit.
            The service does not send narration_delta through this callback.
        
    Returns:
        TurnResult with narration, recommended_actions, state_deltas, turn_no
        
    Raises:
        SessionNotFoundError: If session not found
        TurnValidationError: If validation fails
        TurnClaimConflictError: If the claim cannot be held under its idempotency key
        TurnBudgetExceededError: If the turn budget expired before the commit
        TurnServiceError: For other errors
    """
    def _emit(stage: str, phase: str, **kw):
        if progress_callback:
            progress_callback(emit_stage(stage, phase, **kw))
    
    def _emit_turn_event(event: dict) -> None:
        if turn_event_callback:
            turn_event_callback(event)
    
    # Step 1: Verify session exists
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    
    if session is None:
        raise SessionNotFoundError(
            f"Session not found: {session_id}",
            session_id=session_id,
        )
    
    world_id = session.world_id
    world_for_dispatch = db.get(WorldModel, world_id) if world_id else None
    dispatch_ruleset = getattr(world_for_dispatch, "ruleset_json", None)
    dispatch_ruleset = dispatch_ruleset if isinstance(dispatch_ruleset, dict) else {}
    dispatch_content_profile = dispatch_ruleset.get("content_profile")
    content_runtime_selected = (
        isinstance(dispatch_content_profile, dict)
        and dispatch_content_profile.get("id") == "content_v1"
    )
    if content_runtime_selected and "phase3_profile" in dispatch_ruleset:
        # This marker conflict is rejected before claim creation or any other write.
        raise ContentRuntimeError(
            "CONTENT_BINDING_CONFLICT",
            "world carries both content_v1 and phase-3 profiles",
        )

    # Claim before business preparation; turn number is assigned under its session lock.
    claim_key = idempotency_key if idempotency_key is not None else str(uuid.uuid4())
    # W1b: the fingerprint is always recomputed server-side from the authoritative
    # input (action text + the currently empty structured params, protocol v1). The
    # ``request_fingerprint`` argument is kept only so existing clients keep working;
    # adjudicating on it would let a caller send one forged value for two different
    # inputs and turn a same-key/different-input conflict into a silent replay.
    fingerprint = compute_request_fingerprint(player_input, None)
    outcome = create_or_resume_claim(db, session_id, claim_key, fingerprint)
    if outcome.status == ClaimStatus.NEW and outcome.token is not None:
        # Persist request metadata with the short claim transaction. The claim row
        # is otherwise read-only during the UoW, so lease takeover is not held up
        # by any later LLM call.
        claim_row = db.query(TurnTransactionModel).filter_by(
            id=outcome.token.transaction_id
        ).one()
        claim_session_state = SessionStateRepository(db).get_by_session(session_id)
        claim_row.player_input = player_input
        claim_row.world_time_before = _format_world_time(
            _get_world_time(claim_session_state)
        )
    db.commit()
    if outcome.status == ClaimStatus.RESUME_COMMITTED:
        existing = _get_existing_turn_result(db, session_id, outcome.token.turn_no if outcome.token else turn_no)
        if existing is None:
            raise TurnRecoveryIncompleteError(
                "Committed turn claim has no complete player_turn result snapshot",
                session_id=session_id,
                turn_no=outcome.token.turn_no if outcome.token else turn_no,
            )
        existing.idempotency_key = claim_key
        return existing
    conflicts = {
        ClaimStatus.FINGERPRINT_CONFLICT: "fingerprint_conflict",
        ClaimStatus.SUPERSEDED: "claim_superseded",
        ClaimStatus.ACTIVE_CONFLICT: "turn_in_progress",
        ClaimStatus.LEGACY_INCONSISTENT: "legacy_inconsistent",
        ClaimStatus.LEGACY: "legacy_claim",
        ClaimStatus.EXPIRED: "claim_expired",
    }
    if outcome.status in conflicts:
        raise TurnClaimConflictError(conflicts[outcome.status], session_id)
    claim_token = outcome.token
    if claim_token is None:
        raise TurnServiceError("Turn claim did not return a token", session_id=session_id)
    turn_no = claim_token.turn_no
    fp_before = compute_state_fingerprint(db, session_id)

    turn_uow = None
    heartbeat: Optional[ClaimHeartbeat] = None
    # Service-level budget for this turn: one monotonic deadline that covers every
    # channel (REST and SSE share this entry point) and the model-call wait inside it.
    budget = claim_budget if claim_budget is not None else TurnBudget(DEFAULT_TURN_BUDGET_SECONDS)
    # Tracks whether the single authoritative db.commit() was already attempted, so the
    # failure path can tell "receipt unknown" apart from "never tried to commit".
    authoritative_commit_attempted = False

    def _stop_heartbeat() -> None:
        if heartbeat is not None:
            heartbeat.stop()

    def _rollback_turn_uow(error: Exception) -> None:
        nonlocal turn_uow
        if turn_uow is not None:
            turn_uow.__exit__(type(error), error, error.__traceback__)
            turn_uow = None

    def _abort_before_execution(error: Exception) -> None:
        _stop_heartbeat()
        _rollback_turn_uow(error)
        try:
            abort_claim(db, claim_token, {"category": "preparation_failed", "type": type(error).__name__})
            db.commit()
        except Exception:
            db.rollback()

    # Preflight is deliberately after claim; failures must release the pending claim.
    try:
        if not use_mock:
            _validate_explicit_llm_config(db)
    except Exception as e:
        _abort_before_execution(e)
        raise

    # Own every authoritative write through the final transaction commit.
    turn_uow = TurnUnitOfWork(db, guard_commits=True)
    turn_uow.__enter__()

    # W2: preparation plans its "event class" writes (validation reports, game events
    # and this turn's event-log row) here instead of writing them. The plan is applied
    # in the final write section, inside this single unit of work, so preparation no
    # longer opens a business transaction or locks rows before the model runs.
    write_buffer = TurnWriteBuffer()
    db.info["turn_write_buffer"] = write_buffer

    # Renew the claim lease from an independent Session for the whole execution body,
    # so the model-wait window never holds a business transaction or the session lock.
    # The budget rides along: once it expires the heartbeat stops renewing, which is
    # what makes the lease run out for a turn that overran its service deadline.
    heartbeat = ClaimHeartbeat(
        claim_session_factory
        or sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False),
        claim_token,
        interval=turn_claim.HEARTBEAT_INTERVAL_SECONDS,
        budget=budget,
    )
    heartbeat.start()

    # Step 2: Initialize session story state if needed (idempotent)
    try:
        session_story_state_plan = plan_session_story_state(db, session_id)
    except Exception as e:
        _abort_before_execution(e)
        if isinstance(e, SessionInitializationError):
            raise TurnServiceError(f"Failed to initialize session: {str(e)}", session_id=session_id)
        if isinstance(e, TimeSimulationError):
            # A phase-3 world whose profile marker is unknown or damaged must fail
            # explicitly; initializing it as a legacy session would silently drop
            # the slice's baseline rows.
            raise TurnServiceError(f"Phase-3 initialization failed: {str(e)}", session_id=session_id)
        raise

    db.info["session_story_state_plan"] = session_story_state_plan

    # Step 3: Reconstruct canonical state from DB
    try:
        canonical_state = reconstruct_canonical_state(db, session_id, session_story_state_plan=session_story_state_plan)
        if canonical_state is None:
            raise TurnServiceError(f"Failed to reconstruct state for session: {session_id}", session_id=session_id)
    except Exception as e:
        _abort_before_execution(e)
        if isinstance(e, StateReconstructionError):
            raise TurnServiceError(f"State reconstruction failed: {str(e)}", session_id=session_id)
        raise

    # Step 4: retain allocate_turn's idempotency check, but the locked claim token
    # remains authoritative for numbering and can never be overwritten by this query.
    try:
        allocated_turn_no, is_new = allocate_turn(db, session_id, claim_key)
        if not is_new:
            existing_result = _get_existing_turn_result(db, session_id, allocated_turn_no)
            if existing_result:
                _abort_before_execution(
                    TurnServiceError("Turn already exists", session_id=session_id)
                )
                existing_result.idempotency_key = claim_key
                return existing_result
        if allocated_turn_no != claim_token.turn_no:
            raise TurnConflictError(session_id, claim_token.turn_no, allocated_turn_no)
    except TurnConflictError as e:
        _abort_before_execution(e)
        raise TurnClaimConflictError("turn_in_progress", session_id) from e
    except TurnAllocationError as e:
        _abort_before_execution(e)
        raise TurnServiceError(f"Turn allocation failed: {str(e)}", session_id=session_id)
    except Exception as e:
        _abort_before_execution(e)
        raise
    turn_no = claim_token.turn_no

    # Reuse the claim row; it is only written by the full-token CAS at commit time.
    transaction_id = claim_token.transaction_id
    
    try:
        # Get current location before input intent stage
        session_state_repo = SessionStateRepository(db)
        session_state = _get_session_state_with_plan(db, session_id)
        current_location_id = session_state.current_location_id if session_state else None

        # Phase 3: the slice is opt-in per world. A marker that exists but is
        # unknown or damaged fails this turn explicitly; it never falls back to the
        # legacy scheduler, which would treat the slice's namespaced conditions as
        # unconditional and fire the wrong events.
        try:
            phase3_profile = (
                None if content_runtime_selected else resolve_simulation_profile(db, session)
            )
        except TimeSimulationError as e:
            raise TurnServiceError(f"Phase-3 profile is unusable: {e}", session_id=session_id)

        # Content binding and runtime state are loaded in this managed read phase,
        # before input-intent/model execution. The first binding is retained for the
        # lock-time revalidation below.
        content_binding_prepared = None
        content_runtime_context: Optional[ContentRuntimeContext] = None
        content_result: Optional[Any] = None
        content_write_event_ids: Dict[int, str] = {}
        if content_runtime_selected:
            content_binding_prepared = read_content_binding(db, session_id=session_id)
            content_runtime_context = load_content_runtime_context(db, session_id=session_id)
            if content_binding_prepared != content_runtime_context.binding:
                raise ContentRuntimeError(
                    "CONTENT_BINDING_MISMATCH",
                    "content binding changed while loading runtime context",
                )
            db.info["content_runtime_context"] = content_runtime_context

        # The slice's advance, its write result and its NPC projection for this turn.
        phase3_context: Optional[SimulationContext] = None
        phase3_result: Optional[Any] = None
        phase3_write: Optional[Any] = None
        #: Set only when the *advance* refused or interrupted an action the admission
        #: chain had accepted; a refusal that already happened before the advance
        #: keeps its own public reason code.
        phase3_resolution_override: Optional[Dict[str, Any]] = None
        
        # Create ValidationContext for this turn.
        #
        # Phase 2: the production player actions must carry an *explicit*
        # perspective built from this session's committed state. Omitting it is what
        # let a move skip the discovery check, so the perspective is part of the
        # context itself and every validator that takes the context sees it.
        player_perspective = build_player_perspective(
            _build_authorization_context(
                db=db,
                session_id=session_id,
                world_id=_session_world_id(db, session_id, canonical_state),
                turn_no=turn_no,
                canonical_state=canonical_state,
                current_location_id=current_location_id,
            )
        )
        validation_context = ValidationContext.create(
            db=db,
            session_id=session_id,
            turn_no=turn_no,
            canonical_state=canonical_state,
            perspective=player_perspective,
            actor_id="player",
        )
        # current_location_id is already an ordinary string and the context carries
        # only the Session handle plus pure canonical data. W2-A1/A2/A3 leave no
        # preparation writes pending, so this rollback only closes the read transaction.
        _end_read_transaction(db)
        
        # Step 5: Execute input intent LLM stage (before deterministic parsing)
        _emit("input_intent", "started")
        input_intent_result = _execute_input_intent_stage(
            db=db,
            session_id=session_id,
            turn_no=turn_no,
            canonical_state=canonical_state,
            raw_input=player_input,
            current_location_id=current_location_id,
            use_mock=use_mock,
        )
        _emit("input_intent", "completed")

        # Record the intent validation outcome. The production intent was already
        # validated by the strict contract at parse time and is authorized below;
        # this row keeps the audit trail. There is deliberately no exception path
        # here that could leave the stage accepted: a validation/report failure
        # propagates and rolls the turn back instead of preserving an accepted
        # intent, and a rejected intent is downgraded before it is used.
        if input_intent_result.accepted and input_intent_result.parsed_proposal:
            intent_projection = input_intent_result.parsed_proposal
            is_valid_intent = (
                intent_projection.get("intent_type") in _VALID_INTENT_TYPES
                and isinstance(intent_projection.get("intent"), dict)
            )
            if not is_valid_intent:
                input_intent_result = LLMStageResult(
                    stage_name="input_intent",
                    enabled=input_intent_result.enabled,
                    timeout=input_intent_result.timeout,
                    accepted=False,
                    fallback_reason="validation_failed: malformed intent projection",
                    validation_errors=["malformed_intent_projection"],
                )
            _create_validation_report(
                db=db,
                transaction_id=transaction_id,
                session_id=session_id,
                turn_no=turn_no,
                scope="proposal_input_intent",
                is_valid=is_valid_intent,
                errors_json=None if is_valid_intent else ["malformed_intent_projection"],
                warnings_json=[],
                buffer=write_buffer,
            )
        
        # Only an accepted contract whose explicit marker asks for clarification can
        # request it. The question is bounded, must be player-visible, and still
        # passes the narration leak check; otherwise the deterministic template is
        # used. Hidden wording can never become the player-facing question.
        # The clarification marker is only honoured for an *authorized* action class.
        # Otherwise a model could answer "attack" with needs_clarification=true and
        # convert an unsupported action into a free zero-time clarification turn,
        # bypassing the refusal semantics of plan section 3.6.
        _clarification_intent_type = normalize_production_action_type(
            (input_intent_result.parsed_proposal or {}).get("intent_type") or ""
        )
        if (
            input_intent_result.accepted
            and input_intent_result.parsed_proposal
            and input_intent_result.parsed_proposal.get("needs_clarification") is True
            and _clarification_intent_type in AUTHORIZED_PLAYER_ACTIONS
        ):
            proposed_question = input_intent_result.parsed_proposal.get(
                "clarification_question"
            )
            if input_intent_result.parsed_proposal.get("visibility", "player_visible") != "player_visible":
                proposed_question = None
            if proposed_question:
                proposed_question = proposed_question.strip()[:240]
                frozen_facts = _load_frozen_narration_forbidden_facts(
                    db, session_id, canonical_state, session_story_state_plan
                )
                clarification_leak_validation = NarrationLeakValidator().validate_narration(
                    text=proposed_question,
                    forbidden_info=["隐藏身份", "真实身份", "hidden_identity", "secret_identity"],
                    state=canonical_state,
                    db=None,
                    session_id=session_id,
                    preloaded_forbidden_facts=frozen_facts,
                )
                if not clarification_leak_validation.is_valid:
                    _create_validation_report(
                        db=db,
                        transaction_id=transaction_id,
                        session_id=session_id,
                        turn_no=turn_no,
                        scope="narration_leak_validation",
                        target_ref_id="clarification_question",
                        is_valid=False,
                        errors_json=clarification_leak_validation.errors,
                        warnings_json=clarification_leak_validation.warnings,
                        buffer=write_buffer,
                    )
                    proposed_question = None
            return _commit_clarification_turn(
                db=db,
                session_id=session_id,
                player_input=player_input,
                claim_key=claim_key,
                claim_token=claim_token,
                turn_no=turn_no,
                transaction_id=transaction_id,
                fp_before=fp_before,
                world_time_before=_get_world_time(session_state),
                write_buffer=write_buffer,
                turn_uow=turn_uow,
                heartbeat=heartbeat,
                budget=budget,
                input_intent_result=input_intent_result,
                input_intent_metadata=input_intent_result.parsed_proposal,
                clarification_question=proposed_question,
            )

        # Step 6: Determine the player's action.
        #
        # Two sources are possible and they are handled differently on purpose:
        #
        # * The model produced an accepted ``PlayerIntentV2`` contract. Its
        #   references are then authorized against this turn's committed state
        #   (the model may only cite ids the context supplied, never a name).
        # * The model produced nothing usable (disabled stage, timeout, contract
        #   violation). Only then does the deterministic parser run, and it goes
        #   through the *same* authorization chain. No target or parameter from a
        #   rejected proposal is ever reused.
        _emit("action_resolving", "started")
        action_type = "action"
        target = None
        input_intent_metadata: Optional[Dict[str, Any]] = None
        input_intent_fallback_reason: Optional[str] = None

        auth_context = _build_authorization_context(
            db=db,
            session_id=session_id,
            world_id=_session_world_id(db, session_id, canonical_state),
            turn_no=turn_no,
            canonical_state=canonical_state,
            current_location_id=current_location_id,
            visible_npc_ids={npc["npc_id"] for npc in _get_visible_npcs(db, session_id, current_location_id)},
        )

        intent_contract: Optional[PlayerIntentV2] = None
        if input_intent_result.accepted and input_intent_result.contract is not None:
            intent_contract = input_intent_result.contract  # type: ignore[assignment]
            input_intent_metadata = input_intent_result.parsed_proposal

        if intent_contract is not None:
            # An accepted contract with an explicit clarification marker is the
            # only model-side way to ask for clarification (handled above); here it
            # is a plain action.
            action_type = normalize_production_action_type(intent_contract.intent.action_type)
            authorization = authorize_player_intent(auth_context, intent_contract)
        else:
            deterministic_action, deterministic_target = _parse_player_input(player_input)
            input_intent_fallback_reason = input_intent_result.fallback_reason
            action_type = normalize_production_action_type(deterministic_action)
            target = deterministic_target
            authorization = authorize_deterministic_player_intent(
                auth_context, deterministic_action, deterministic_target
            )

        if (
            content_runtime_context is not None
            and authorization.authorized
            and authorization.action is not None
            and authorization.action.handler == "player_move"
        ):
            source_code = content_runtime_context.state.player_location_code
            destination_code = authorization.action.target_location_code
            if (
                destination_code
                and destination_code != source_code
                and not content_runtime_context.state.route_is_open(source_code or "", destination_code)
            ):
                authorization = AuthorizationOutcome(
                    detail_code=ActionDetailCode.DOMAIN_RULE_BLOCKED,
                    detail_message="the route is closed in this session",
                )

        input_intent_result.authorization = authorization

        # A move whose target the player did not state is an explicitly ambiguous
        # instruction: it stays a zero-time clarification turn (no game action, no
        # world-time advance, no scheduling/NPC/memory work) rather than becoming a
        # rejected action.
        if (
            action_type == "move"
            and authorization.detail_code is ActionDetailCode.MISSING_TARGET
        ):
            return _commit_clarification_turn(
                db=db,
                session_id=session_id,
                player_input=player_input,
                claim_key=claim_key,
                claim_token=claim_token,
                turn_no=turn_no,
                transaction_id=transaction_id,
                fp_before=fp_before,
                world_time_before=_get_world_time(session_state),
                write_buffer=write_buffer,
                turn_uow=turn_uow,
                heartbeat=heartbeat,
                budget=budget,
                input_intent_result=input_intent_result,
                input_intent_metadata=input_intent_metadata,
                clarification_question=None,
                content_binding_prepared=content_binding_prepared,
            )

        # Step 6b: Adjudicate the action class's time cost exactly once.
        #
        # Phase 3 reuses this same validated *planned* duration to size the player's
        # continuous action. The advance may then truncate it (a perceivable world
        # interrupt); a truncated actual duration is never pushed back through the
        # validator, because clamping it again could lift it past the interrupt tick
        # and silently extend the turn.
        world_time_before = _get_world_time(session_state)
        elapsed_minutes = _resolve_elapsed_minutes(
            action_type=action_type,
            intent_result=input_intent_result,
        )

        from .time_advance import INTENT_TO_TIME_CATEGORY, TimeAdvanceProposal
        from .time_advance_validator import TimeAdvanceValidator

        _intent_type = None
        if input_intent_result is not None:
            _parsed = getattr(input_intent_result, "parsed_proposal", None)
            if _parsed and isinstance(_parsed, dict):
                _intent_type = _parsed.get("intent_type")
        if _intent_type is None and action_type:
            _intent_type = action_type
        _resolved_category = INTENT_TO_TIME_CATEGORY.get(_intent_type or "", "unknown")

        _time_proposal = TimeAdvanceProposal(
            elapsed_minutes=elapsed_minutes,
            time_category=_resolved_category,
        )
        _validator = TimeAdvanceValidator()
        _validator_result = _validator.validate(_time_proposal)

        # Step 7: Domain adjudication. The engine decides the actual result; the
        # model never supplies a delta, an effect, a success flag or a duration.
        movement_result: Optional[MovementResult] = None
        state_deltas: Dict[str, Any] = {}
        player_action_resolution: Optional[ResolvedAction] = None
        # Planned GameEvent id of a refused action, used as the delta's causal source.
        refused_action_event_id: Optional[str] = None
        # This turn's planned quest-progression updates (empty when nothing advanced);
        # ``check_quest_progression`` fills it in plan mode and Step 14a applies it.
        quest_plan: List[QuestStatePlan] = []

        if authorization.authorized:
            action = authorization.action
            target = action.target_location_code or action.target_npc_id or target
            if action.handler == "player_move":
                player_action_resolution = resolve_player_action(
                    action,
                    MovementResolutionContext(
                        db=db,
                        session_id=session_id,
                        turn_no=turn_no,
                        canonical_state=canonical_state,
                        validation_context=validation_context,
                        current_location_id=current_location_id,
                        defer_location_write=True,
                        planned_session_state=session_story_state_plan.session_state_overlay(),
                        planned_player_state=session_story_state_plan.player_state_overlay(),
                    ),
                )
                movement_result = player_action_resolution.movement_result
                if movement_result is not None and movement_result.success:
                    state_deltas["location_id"] = movement_result.new_location_id
                elif movement_result is not None:
                    state_deltas["blocked_reason"] = movement_result.blocked_reason
                for event in player_action_resolution.events:
                    if event.kind is ResolvedEventKind.MOVEMENT_BLOCKED:
                        _create_validation_report(
                            db=db,
                            transaction_id=transaction_id,
                            session_id=session_id,
                            turn_no=turn_no,
                            scope="movement_validation",
                            is_valid=False,
                            errors_json=[player_action_resolution.detail_message or "Movement blocked"],
                            warnings_json=[],
                            buffer=write_buffer,
                        )
            else:
                player_action_resolution = resolve_player_action(action, None)
        else:
            # Recognized but unauthorized / unavailable / handlerless: the action
            # effect is refused with the existing per-class time cost. This is not a
            # free clarification, and the refusal is not softened into success.
            player_action_resolution = reject_action(
                None,
                authorization.detail_code or ActionDetailCode.ACTION_NOT_AUTHORIZED,
                authorization.detail_message,
                reason=authorization.public_reason,
            )
            if intent_contract is not None:
                input_intent_result.accepted = False
                input_intent_result.fallback_reason = (
                    f"authorization_rejected: "
                    f"{(authorization.public_reason or ActionReasonCode.INVALID_PARAMS).value}"
                )
                input_intent_result.contract = None
                input_intent_result.parsed_proposal = None
            # Restricted audit: the refusal's *detailed* reason never leaves the
            # server, but the refusal itself must be traceable. A refused movement
            # keeps the existing "movement_validation" scope so the audit vocabulary
            # and its readers are unchanged; any other refusal is recorded as an
            # action-authorization report.
            _create_validation_report(
                db=db,
                transaction_id=transaction_id,
                session_id=session_id,
                turn_no=turn_no,
                scope=(
                    "movement_validation"
                    if action_type == "move"
                    else "action_authorization"
                ),
                target_ref_id=target if isinstance(target, str) else None,
                is_valid=False,
                errors_json=[str(player_action_resolution.detail_code)],
                warnings_json=[],
                buffer=write_buffer,
            )
            # A refused action is still an engine-decided outcome, so it gets its own
            # fact event. Without it the turn's time delta would have no action to
            # point at and would fall back to the narration presentation event, which
            # the plan forbids.
            refused_action_event_id = write_buffer.add_game_event(
                transaction_id=transaction_id,
                session_id=session_id,
                turn_no=turn_no,
                event_type="action_resolved",
                actor_id="player",
                target_ids=[target] if isinstance(target, str) else None,
                visibility_scope="player_visible",
                public_payload={
                    "action_type": normalize_production_action_type(action_type),
                    "status": "rejected",
                },
                result_json={
                    "reason_code": (
                        player_action_resolution.reason_code.value
                        if player_action_resolution.reason_code
                        else None
                    ),
                    "authorization_detail": str(player_action_resolution.detail_code),
                },
            )
            logger.warning(
                "Player action refused session=%s turn=%s detail=%s",
                session_id,
                turn_no,
                player_action_resolution.detail_code,
            )

        # A refused/unavailable action is a *committed failed turn*: it keeps the
        # existing action-class time semantics and reports the refusal as an
        # already-happened result. It is never reported as a success.

        _emit("action_resolving", "completed")

        # Step 7b: Phase-3 world advance.
        #
        # The admission chain above is untouched: it answered "may this action
        # start". The advancer now answers "what actually happened between the
        # start tick and the action's planned end", on one WorkingState shared by
        # the player action, the NPC steps and the item steps. It is pure -- it
        # plans events, deltas and the final state; the final write section applies
        # them inside the one authoritative transaction. Legacy worlds skip this
        # block entirely.
        if phase3_profile is not None:
            try:
                phase3_context = load_simulation_context(
                    db, session_id, plan=session_story_state_plan
                )
            except TimeSimulationError as e:
                # A run marker, plan or step row the engine cannot trust fails this
                # turn explicitly; it is never repaired by guessing a cursor and it
                # never falls back to the legacy scheduler.
                raise TurnServiceError(
                    f"Phase-3 state is unusable: {e}", session_id=session_id
                )
            _admitted = bool(
                player_action_resolution is not None
                and player_action_resolution.status == ActionStatus.ACCEPTED
            )
            _target_code: Optional[str] = None
            if _admitted and movement_result is not None and movement_result.success:
                _target_code = movement_result.new_location_code
            phase3_player_action = build_player_action_spec(
                phase3_context,
                action_type=action_type,
                duration_minutes=_validator_result.accepted_elapsed_minutes,
                target_location_code=_target_code,
                refused=not _admitted,
                detail_code=(
                    str(player_action_resolution.detail_code)
                    if player_action_resolution is not None
                    and player_action_resolution.detail_code is not None
                    else None
                ),
                detail_message=(
                    player_action_resolution.detail_message
                    if player_action_resolution is not None
                    else None
                ),
            )
            try:
                phase3_result = _phase3_advance(phase3_context, phase3_player_action)
            except TimeSimulationError as e:
                raise TurnServiceError(
                    f"Phase-3 advance failed: {e}", session_id=session_id
                )
            movement_result = _phase3_reconcile_movement(phase3_result, movement_result)
            state_deltas.pop("location_id", None)
            if (
                movement_result is not None
                and movement_result.success
                and movement_result.new_location_id
            ):
                state_deltas["location_id"] = movement_result.new_location_id
            elif movement_result is not None:
                state_deltas["blocked_reason"] = movement_result.blocked_reason
            if _admitted and phase3_result.player_result.status != PlayerActionStatus.COMPLETED:
                # The admission chain answered "may this start"; the advance answered
                # "it did not finish". The admission's own fact events must not
                # survive as committed facts -- no target position, no arrival task,
                # no success narration and no success count -- so the resolution is
                # replaced by an engine-authored refusal and its own audit event.
                _phase3_message = (
                    phase3_result.player_result.detail_message
                    or _phase3_engine_message(phase3_result)
                )
                _phase3_detail = (
                    ActionDetailCode.ACTION_INTERRUPTED
                    if phase3_result.player_result.status == PlayerActionStatus.INTERRUPTED
                    else ActionDetailCode.DOMAIN_RULE_BLOCKED
                )
                player_action_resolution = reject_action(
                    None,
                    _phase3_detail,
                    _phase3_message,
                    reason=ActionReasonCode.TARGET_UNAVAILABLE,
                )
                phase3_resolution_override = _phase3_resolution_summary(
                    action_type=action_type,
                    result=phase3_result,
                    fallback_used=intent_contract is None,
                )
                refused_action_event_id = write_buffer.add_game_event(
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    event_type="action_resolved",
                    actor_id="player",
                    target_ids=None,
                    visibility_scope="player_visible",
                    public_payload={
                        "action_type": normalize_production_action_type(action_type),
                        "status": "rejected",
                    },
                    result_json={
                        "reason_code": ActionReasonCode.TARGET_UNAVAILABLE.value,
                        "authorization_detail": str(_phase3_detail),
                    },
                )
            # Present-NPC readers (scene/NPC stages, recommendations) consume this
            # projection, never the stale persisted positions.
            db.info["phase3_npc_overlay"] = npc_overlay_for_turn(
                phase3_context, phase3_result
            )
            # Pre-allocate the durable ids of this turn's engine facts so a
            # world/scene stage may only reference events the engine has already
            # decided -- including the slice's own steps of this turn. The rows
            # themselves land in the final write section with these very ids.
            write_buffer.phase3_event_ids = plan_engine_event_ids(phase3_result)

        if content_runtime_context is not None:
            # The same admission result is adapted by the existing shared action
            # codec; only its cursor/rule source differs from the phase-3 context.
            from .world_advancer import WorldAdvancer

            def _classify_content_action(value: Optional[str]) -> str:
                normalized = (value or "").strip().lower()
                if normalized in {"move", "follow"}:
                    return PlayerActionKind.MOVE
                if normalized in {"wait", "idle", "action", "inspect"}:
                    return PlayerActionKind.IDLE
                return PlayerActionKind.INSTANT

            # Content's inspect slice is interruptible observational work; retain
            # the shared spec builder with content semantics only, without invoking
            # the phase-3 fixed TrialRules profile or the legacy scheduler.
            content_action_rules = SimpleNamespace(
                classify_player_action=_classify_content_action,
            )
            content_adjudication_context = SimpleNamespace(
                rules=content_action_rules,
                run_state=SimpleNamespace(logical_tick=content_runtime_context.run_state.logical_tick),
            )
            _admitted = bool(
                player_action_resolution is not None
                and player_action_resolution.status == ActionStatus.ACCEPTED
            )
            _target_code = None
            if _admitted and movement_result is not None and movement_result.success:
                _target_code = movement_result.new_location_code
            content_player_action = build_player_action_spec(
                content_adjudication_context,
                action_type=action_type,
                duration_minutes=_validator_result.accepted_elapsed_minutes,
                target_location_code=_target_code,
                refused=not _admitted,
                detail_code=(
                    str(player_action_resolution.detail_code)
                    if player_action_resolution is not None
                    and player_action_resolution.detail_code is not None
                    else None
                ),
                detail_message=(
                    player_action_resolution.detail_message
                    if player_action_resolution is not None
                    else None
                ),
            )
            content_result = WorldAdvancer(content_runtime_context.rules).advance(
                state=content_runtime_context.state,
                player_action=content_player_action,
                pending_steps=content_runtime_context.pending_steps,
                consumed_step_keys=content_runtime_context.consumed_step_keys,
                start_event_seq=content_runtime_context.start_event_seq,
            )
            content_write_event_ids = plan_engine_event_ids(content_result)
            db.info["content_event_ids"] = dict(content_write_event_ids)
            db.info["content_tick_positions"] = _content_tick_positions(
                content_runtime_context, content_result
            )
            movement_result = _phase3_reconcile_movement(content_result, movement_result)
            state_deltas.pop("location_id", None)
            if movement_result is not None and movement_result.success and movement_result.new_location_id:
                state_deltas["location_id"] = movement_result.new_location_id
            elif movement_result is not None:
                state_deltas["blocked_reason"] = movement_result.blocked_reason
            if _admitted and content_result.player_result.status != PlayerActionStatus.COMPLETED:
                _content_message = (
                    content_result.player_result.detail_message
                    or _phase3_engine_message(content_result)
                )
                _content_detail = (
                    ActionDetailCode.ACTION_INTERRUPTED
                    if content_result.player_result.status == PlayerActionStatus.INTERRUPTED
                    else ActionDetailCode.DOMAIN_RULE_BLOCKED
                )
                player_action_resolution = reject_action(
                    None,
                    _content_detail,
                    _content_message,
                    reason=ActionReasonCode.TARGET_UNAVAILABLE,
                )
                phase3_resolution_override = _phase3_resolution_summary(
                    action_type=action_type,
                    result=content_result,
                    fallback_used=intent_contract is None,
                )
                write_buffer.add_game_event(
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    event_type="action_resolved",
                    actor_id="player",
                    target_ids=None,
                    visibility_scope="player_visible",
                    public_payload={
                        "action_type": normalize_production_action_type(action_type),
                        "status": "rejected",
                    },
                    result_json={
                        "reason_code": ActionReasonCode.TARGET_UNAVAILABLE.value,
                        "authorization_detail": str(_content_detail),
                    },
                )

        # Step 8: Check quest progression
        if movement_result and movement_result.success:
            # Validate quest progression before checking
            # Build a minimal quest state for validation
            from llm_rpg.models.common import ProposedAction
            
            quest_validation_action = ProposedAction(
                action_id="turn-quest-check",
                actor_id="player",
                action_type="quest_progress",
                target_ids=[],
                summary="Check quest progression after movement",
            )
            quest_validator = QuestValidator()
            quest_validation = quest_validator.validate_quest_progress(
                action=quest_validation_action,
                quest_state=None,  # Will be filled from canonical_state.quest_states by the validator
                quest_template=None,
                context=validation_context,
            )
            
            if not quest_validation.is_valid:
                _create_validation_report(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    scope="quest_progression_validation",
                    is_valid=False,
                    errors_json=quest_validation.errors,
                    warnings_json=quest_validation.warnings,
                    buffer=write_buffer,
                )
                logger.warning("Quest progression validation failed: %s", quest_validation.errors)
            
            try:
                quest_results = check_quest_progression(
                    db=db,
                    session_id=session_id,
                    action_context={
                        "action_type": "movement",
                        "target_location_code": movement_result.new_location_code,
                    },
                    defer_write=True,
                    plan_out=quest_plan,
                    planned_quest_states=session_story_state_plan.quest_state_overlays(),
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
        
        # The planned quest-progression updates, keyed by session_quest_states.id.
        # Preparation readers that used to observe the already-written rows merge
        # these in; the rows themselves are written in the final write section.
        planned_quests: Dict[str, QuestStatePlan] = {
            plan.quest_state_id: plan for plan in quest_plan
        }
        
        # Step 9: Generate recommended actions (deterministic fallback)
        session_state = _get_session_state_with_plan(db, session_id)
        # Preserve ordinary values before subsequent stage rollbacks expire ORM state.
        session_state_id = session_state.id if session_state is not None else None
        
        current_location_id = None
        if session_state:
            current_location_id = session_state.current_location_id
        
        if movement_result and movement_result.success:
            current_location_id = movement_result.new_location_id
        
        deterministic_recommended_actions = generate_recommended_actions(
            db=db,
            session_id=session_id,
            location_id=current_location_id,
            planned_quests=planned_quests,
            planned_session_state=session_story_state_plan.session_state_overlay(),
            planned_player_state=session_story_state_plan.player_state_overlay(),
            planned_npc_states=session_story_state_plan.npc_state_overlays(),
            baseline_quest_states=session_story_state_plan.quest_state_overlays(),
            npc_location_overrides=_phase3_npc_locations(db, session_id),
        )
        if content_runtime_context is not None:
            deterministic_recommended_actions = _content_recommended_actions(
                db, content_runtime_context
            )
        
        # Step 10: Build template narration (fallback-safe placeholder)
        narration = _build_narration(
            player_input=player_input,
            action_type=action_type,
            movement_result=movement_result,
            canonical_state=canonical_state,
        )
        
        # Step 11: Advance world time for the committed turn.
        #
        # Phase 3: the calendar is a *projection* of the authoritative cursor. It is
        # computed once, from the turn's starting display time plus the advance's
        # ACTUAL elapsed minutes, so the cursor, the events, the deltas and the
        # response all describe the same real endpoint. ``WorldTime.total_minutes``
        # is never used to back-compute the cursor (it resets across seasons).
        world_time = _advance_world_time(
            world_time_before,
            elapsed_minutes=(
                phase3_result.actual_elapsed_minutes
                if phase3_result is not None
                else content_result.actual_elapsed_minutes
                if content_result is not None
                else _validator_result.accepted_elapsed_minutes
            ),
        )

        if phase3_result is not None:
            time_advance_result = project_time_summary(
                phase3_result,
                planned_elapsed_minutes=_validator_result.accepted_elapsed_minutes,
                original_elapsed_minutes=_validator_result.original_elapsed_minutes,
                adjusted=_validator_result.adjusted,
                reason=_validator_result.reason,
                category=_validator_result.category,
                new_world_time=world_time,
            )
        elif content_result is not None:
            time_advance_result = project_time_summary(
                content_result,
                planned_elapsed_minutes=_validator_result.accepted_elapsed_minutes,
                original_elapsed_minutes=_validator_result.original_elapsed_minutes,
                adjusted=_validator_result.adjusted,
                reason=_validator_result.reason,
                category=_validator_result.category,
                new_world_time=world_time,
            )
        else:
            time_advance_result = {
                "accepted_elapsed_minutes": _validator_result.accepted_elapsed_minutes,
                "original_elapsed_minutes": _validator_result.original_elapsed_minutes,
                "adjusted": _validator_result.adjusted,
                "reason": _validator_result.reason,
                "category": _validator_result.category,
                "new_world_time": world_time,
            }
        

        # Step 12: Get player state
        player_state = _get_player_state(canonical_state, current_location_id)
        
        # Step 13: Plan the turn's player_turn event log with template narration.
        # The row itself is written by ``write_buffer.flush`` in the final write
        # section (Step 14a); the plan already carries the pre-allocated id, turn
        # number and text so preparation-side readers can see this turn's event.
        # The progress events stay here: their names and order are part of the SSE
        # contract and must not move.
        _emit("committing", "started")
        planned_player_turn_event = write_buffer.add_event_log(
            session_id=session_id,
            turn_no=turn_no,
            event_type="player_turn",
            input_text=player_input,
            narrative_text=narration,
            result_json={
                "transaction_id": transaction_id,
                "recommended_actions": deterministic_recommended_actions,
                "state_deltas": state_deltas,
                "action_type": action_type,
                "movement_success": movement_result.success if movement_result else None,
                "new_location_id": movement_result.new_location_id if movement_result else None,
                "world_time_before": world_time_before,
                "world_time": world_time,
                "input_intent": input_intent_metadata,
                "input_intent_fallback_reason": input_intent_fallback_reason,
                "llm_stages": [],
            },
            idempotency_key=idempotency_key,
        )
        _emit("committing", "completed")
        
        # Step 13b: Plan the game_event for player_input
        write_buffer.add_game_event(
            transaction_id=transaction_id,
            session_id=session_id,
            turn_no=turn_no,
            event_type="player_input",
            actor_id="player",
            target_ids=[current_location_id] if current_location_id else None,
            visibility_scope="player_visible",
            public_payload={
                "input_text": player_input,
                "action_type": action_type,
                "target": target,
                "input_intent": input_intent_metadata,
            },
            result_json={
                "movement_success": movement_result.success if movement_result else None,
                "new_location_id": movement_result.new_location_id if movement_result else None,
            },
        )
        
        # Step 14: Execute preparation LLM stages. Narration context is frozen as
        # plain data now, but its model call is deferred until after fact commit.
        frozen_narration_context: Dict[str, Any] = {}
        frozen_narration_forbidden_info: List[Any] = []
        llm_stage_results = _execute_llm_stages(
            db=db,
            session_id=session_id,
            turn_no=turn_no,
            canonical_state=canonical_state,
            player_input=player_input,
            action_type=action_type,
            movement_result=movement_result,
            state_deltas=state_deltas,
            current_location_id=current_location_id,
            use_mock=use_mock,
            transaction_id=transaction_id,
            progress_callback=progress_callback,
            turn_event_callback=turn_event_callback,
            write_buffer=write_buffer,
            planned_quests=planned_quests,
            deterministic_recommended_actions=deterministic_recommended_actions,
            narration_context_out=frozen_narration_context,
            narration_forbidden_info_out=frozen_narration_forbidden_info,
        )

        # Stop independent claim renewal, enforce the budget, and begin the final
        # authoritative transaction with its lock and state revalidation before any
        # planned/validation/game-state write is applied.
        if not heartbeat.stop() or heartbeat.lost:
            raise TurnClaimConflictError("claim_lost", session_id)
        if budget.expired():
            raise TurnBudgetExceededError(
                session_id=session_id,
                turn_no=turn_no,
                total_seconds=budget.total_seconds,
            )
        _end_read_transaction(db)
        acquire_turn_lock(db, session_id)
        if content_binding_prepared is not None:
            # Re-resolve the complete Session → Instance → World → SPV binding only
            # after the lock is held. Runtime hash/version/world identity drift fails
            # closed before any preparation or game-state write is applied.
            locked_binding = read_content_binding(db, session_id=session_id)
            if locked_binding != content_binding_prepared:
                raise ContentRuntimeError(
                    "CONTENT_BINDING_MISMATCH",
                    "content session binding changed between preparation and locked write",
                )
        if db.get_bind().dialect.name != "sqlite" or content_binding_prepared is not None:
            fp_after = compute_state_fingerprint(db, session_id)
            if fp_after != fp_before:
                if content_binding_prepared is not None:
                    raise ContentRuntimeError(
                        "CONTENT_BINDING_MISMATCH",
                        "content binding or materialized definitions changed during turn preparation",
                    )
                raise TurnStateConflictError(session_id)
        
        # Step 14a: Apply the planned preparation writes, now inside the final write
        # section and before the single authoritative db.commit(). ``flush`` reuses
        # the same repositories/helper and the pre-allocated ids and applies the rows
        # in planning order, so validation_reports and game_events end up with exactly
        # the content and order the direct writes produced. It has to run *here*: the
        # rows must exist (in this transaction) before the Step 14b validators read
        # them — ``NarrationLeakValidator`` must keep seeing only this turn's
        # preparation events, never the ones created later in the final section.
        #
        # The two game-state writes preparation used to perform directly are applied
        # here as well, in their original relative order (movement, then quest
        # progression, then the buffered event rows), using the very same repository
        # calls and payloads, so the persisted rows are field-for-field what the
        # direct writes produced and every later reader in this transaction sees the
        # same state it saw before.
        apply_session_story_state(db, session_story_state_plan)
        if phase3_result is None and (
            session_state_id is not None
            and movement_result
            and movement_result.success
            and movement_result.new_location_id
        ):
            session_state_repo.update(session_state_id, {
                "current_location_id": movement_result.new_location_id,
            })
        if quest_plan:
            quest_state_repo = SessionQuestStateRepository(db)
            for quest_update in quest_plan:
                quest_state_repo.update(quest_update.quest_state_id, {
                    "current_step_no": quest_update.current_step_no,
                    "status": quest_update.status,
                    "progress_json": quest_update.progress_json,
                })
        if phase3_result is not None:
            # Phase 3: one advance, one apply. The cursor, the NPC positions and
            # plans, the token's owner, the scheduled-step states, the engine facts,
            # their deltas and the enabled necessary cognition all land here, inside
            # the single authoritative transaction -- a failure rolls the turn back
            # whole rather than committing a prefix of the timeline. It runs after
            # the buffered rows so the turn's own events keep their causal order
            # ahead of the world timeline they started.
            phase3_write = apply_simulation_advance(
                db,
                phase3_context,
                phase3_result,
                transaction_id=transaction_id,
                turn_no=turn_no,
                write_events=True,
                write_cognition=_is_memory_stage_enabled(db),
                planned_event_ids=write_buffer.phase3_event_ids,
            )
        if content_result is not None:
            _write_content_engine_events(
                db,
                session_id=session_id,
                transaction_id=transaction_id,
                turn_no=turn_no,
                result=content_result,
                planned_event_ids=content_write_event_ids,
            )
            apply_content_advance(
                db,
                session_id=session_id,
                context=content_runtime_context,
                advance_result=content_result,
                write_cognition=_is_memory_stage_enabled(db),
            )
        try:
            write_buffer.flush(db)
        except TurnAllocationError as e:
            raise TurnServiceError(
                f"Failed to commit turn: {str(e)}",
                session_id=session_id,
                turn_no=turn_no,
            )
        # The player_turn row is created here, in the final write section; every later
        # reference (event_log updates, memories, presentation CAS) uses this object.
        event = write_buffer.flushed_event_log(planned_player_turn_event.id)
        
        # Step 14b: Validate all proposals before committing
        #
        # Phase 2: authorization and domain adjudication already happened inside
        # each stage, so this section is a *structural* re-check of the accepted
        # projections plus the existing knowledge/leak validators. A failure here
        # must not preserve an accepted stage, and a validator *exception* is a
        # service error: it rolls the turn back instead of being logged and ignored.
        _emit("validation", "started")
        from ..models.proposals import (
            WorldTickProposal, SceneEventProposal, NPCActionProposal, NarrationProposal,
            CandidateEvent, StateDeltaCandidate, ProposalAuditMetadata, ProposalType, ProposalSource,
        )
        
        for stage_result in llm_stage_results:
            if not stage_result.accepted or not stage_result.parsed_proposal:
                continue
            
            if stage_result.stage_name == "world":
                world_proposal = WorldTickProposal(
                    time_description="",
                    candidate_events=[],
                    state_deltas=[],
                    audit=ProposalAuditMetadata(
                        proposal_type=ProposalType.WORLD_TICK,
                        source_engine=ProposalSource.WORLD_ENGINE,
                    ),
                )
                is_valid, errors, warnings = _validate_proposal(
                    db=db,
                    proposal=world_proposal,
                    proposal_type="world_tick",
                    validation_context=validation_context,
                    transaction_id=transaction_id,
                )
                if not is_valid:
                    # A reference-only world proposal can legitimately carry no
                    # candidates; only a structural failure rejects the stage.
                    logger.warning("World-stage projection validation failed: %s", errors)
                    stage_result.accepted = False
                    stage_result.validation_errors = errors
                    stage_result.fallback_reason = f"validation_failed: {', '.join(errors[:3])}"
                    
            elif stage_result.stage_name == "scene":
                scene_id = current_location_id or "unknown"
                scene_proposal = SceneEventProposal(
                    scene_id=scene_id,
                    candidate_events=[],
                    recommended_actions=list(
                        stage_result.parsed_proposal.get("recommended_actions", [])
                    ),
                    audit=ProposalAuditMetadata(
                        proposal_type=ProposalType.SCENE_EVENT,
                        source_engine=ProposalSource.SCENE_ENGINE,
                    ),
                )
                is_valid, errors, warnings = _validate_proposal(
                    db=db,
                    proposal=scene_proposal,
                    proposal_type="scene_event",
                    validation_context=validation_context,
                    transaction_id=transaction_id,
                )
                if not is_valid:
                    logger.warning("Scene-stage projection validation failed: %s", errors)
                    stage_result.accepted = False
                    stage_result.validation_errors = errors
                    stage_result.fallback_reason = f"validation_failed: {', '.join(errors[:3])}"
                    
            elif stage_result.stage_name == "npc":
                npc_reactions = stage_result.parsed_proposal.get("npc_reactions", [])
                npc_knowledge_validator = NPCKnowledgeValidator()
                for reaction in npc_reactions:
                    if not reaction.get("accepted"):
                        continue
                    npc_id = reaction.get("npc_id", "unknown")
                    npc_proposal = NPCActionProposal(
                        npc_id=npc_id,
                        npc_name=reaction.get("npc_name"),
                        action_type=reaction.get("action_type", "idle"),
                        summary=reaction.get("summary", ""),
                        visible_motivation=reaction.get("visible_motivation", ""),
                        audit=ProposalAuditMetadata(
                            proposal_type=ProposalType.NPC_ACTION,
                            source_engine=ProposalSource.NPC_ENGINE,
                        ),
                    )
                    
                    knowledge = "\n".join(
                        part for part in [
                            reaction.get("utterance", ""),
                            reaction.get("summary", ""),
                            reaction.get("visible_motivation", ""),
                        ]
                        if part
                    )
                    # Canonical NPC identity, not the session-state row id: the
                    # validator reads ``CanonicalState.npc_states``, which is keyed
                    # by the NPC's canonical key.
                    canonical_npc_id = reaction.get("npc_canonical_id") or npc_id
                    npc_knowledge_validation = npc_knowledge_validator.validate_knowledge(
                        npc_id=canonical_npc_id,
                        knowledge=knowledge,
                        state=canonical_state,
                        context=validation_context,
                    )
                    
                    if not npc_knowledge_validation.is_valid:
                        # The NPC text may not carry knowledge the NPC cannot have.
                        # The action itself stays adjudicated, but the text is
                        # dropped and the reaction is no longer accepted, so it can
                        # never become a fact or a cognition source.
                        _create_validation_report(
                            db=db,
                            transaction_id=transaction_id,
                            session_id=session_id,
                            turn_no=turn_no,
                            scope="npc_knowledge_validation",
                            target_ref_id=canonical_npc_id,
                            is_valid=False,
                            errors_json=npc_knowledge_validation.errors,
                            warnings_json=npc_knowledge_validation.warnings,
                        )
                        logger.warning(
                            "NPC knowledge validation failed for %s: %s",
                            canonical_npc_id,
                            npc_knowledge_validation.errors,
                        )
                        reaction["accepted"] = False
                        reaction["summary"] = ""
                        reaction["visible_motivation"] = ""
                        reaction["utterance"] = None
                        reaction["fallback_reason"] = (
                            "npc_knowledge_validation_failed: "
                            f"{', '.join(npc_knowledge_validation.errors[:3])}"
                        )
                        continue
                    
                    is_valid, errors, warnings = _validate_proposal(
                        db=db,
                        proposal=npc_proposal,
                        proposal_type="npc_action",
                        validation_context=validation_context,
                        transaction_id=transaction_id,
                    )
                    if not is_valid:
                        logger.warning(
                            "NPC projection validation failed for %s: %s", npc_id, errors
                        )
                        reaction["accepted"] = False
                        reaction["fallback_reason"] = f"validation_failed: {', '.join(errors[:3])}"
                        
            elif stage_result.stage_name == "narration":
                narration_leak_validator = NarrationLeakValidator()
                narration_text = stage_result.parsed_proposal.get("text", "")
                narration_proposal = NarrationProposal(
                    text=narration_text,
                    audit=ProposalAuditMetadata(
                        proposal_type=ProposalType.NARRATION,
                        source_engine=ProposalSource.NARRATION_ENGINE,
                    ),
                )
                
                forbidden_patterns = ["隐藏身份", "真实身份", "hidden_identity", "secret_identity"]
                narration_leak_validation = narration_leak_validator.validate_narration(
                    text=narration_text,
                    forbidden_info=forbidden_patterns,
                    state=canonical_state,
                    context=validation_context,
                    db=db,
                    session_id=session_id,
                )
                
                if not narration_leak_validation.is_valid:
                    _create_validation_report(
                        db=db,
                        transaction_id=transaction_id,
                        session_id=session_id,
                        turn_no=turn_no,
                        scope="narration_leak_validation",
                        is_valid=False,
                        errors_json=narration_leak_validation.errors,
                        warnings_json=narration_leak_validation.warnings,
                    )
                    logger.warning("Narration leak validation failed: %s", narration_leak_validation.errors)
                    stage_result.accepted = False
                    stage_result.validation_errors = narration_leak_validation.errors
                    stage_result.fallback_reason = f"leak_detected: {', '.join(narration_leak_validation.errors[:3])}"
                
                is_valid, errors, warnings = _validate_proposal(
                    db=db,
                    proposal=narration_proposal,
                    proposal_type="narration",
                    validation_context=validation_context,
                    transaction_id=transaction_id,
                )
                if not is_valid:
                    logger.warning("Narration proposal validation failed: %s", errors)
                    stage_result.accepted = False
                    stage_result.validation_errors = errors
                    stage_result.fallback_reason = f"validation_failed: {', '.join(errors[:3])}"
        _emit("validation", "completed")
        
        # Step 15: Determine final recommended actions, scene reference, NPC reactions
        # and the world-stage reference.
        #
        # Phase 2: these are *reference* projections, not facts. The world stage may
        # only point at events the engine already decided, and the scene stage may
        # only select from the engine's legal recommended actions, so an accepted
        # stage here can never invent world content.
        final_recommended_actions = deterministic_recommended_actions
        scene_event_summary: Optional[Dict[str, Any]] = None
        scene_fallback_reason: Optional[str] = None
        npc_reactions_for_json: List[Dict[str, Any]] = []
        npc_fallback_reason: Optional[str] = None
        world_progression: Optional[Dict[str, Any]] = None
        world_fallback_reason: Optional[str] = None
        world_reference: Optional[ResolvedAction] = None
        scene_reference: Optional[ResolvedAction] = None
        
        for stage_result in llm_stage_results:
            if stage_result.stage_name == "world":
                if stage_result.accepted and stage_result.parsed_proposal:
                    world_progression = stage_result.parsed_proposal
                    world_reference = stage_result.resolution
                else:
                    world_fallback_reason = stage_result.fallback_reason
            elif stage_result.stage_name == "scene":
                if stage_result.accepted and stage_result.parsed_proposal:
                    selected_actions = stage_result.parsed_proposal.get("recommended_actions", [])
                    if selected_actions and isinstance(selected_actions, list):
                        final_recommended_actions = selected_actions[:4]
                    scene_event_summary = {
                        "scene_id": current_location_id,
                        "contract_version": 2,
                        "referenced_event_ids": list(
                            stage_result.parsed_proposal.get("referenced_event_ids", [])
                        ),
                        "display_hint": stage_result.parsed_proposal.get("display_hint"),
                    }
                    scene_reference = stage_result.resolution
                else:
                    scene_fallback_reason = stage_result.fallback_reason
            elif stage_result.stage_name == "npc":
                if stage_result.accepted and stage_result.parsed_proposal:
                    npc_reactions_for_json = stage_result.parsed_proposal.get("npc_reactions", [])
                else:
                    npc_fallback_reason = stage_result.fallback_reason

        # Step 15b: The world stage may advise time, and the advice is recorded as
        # explicitly *not* adopted: world time is adjudicated once, before the stage,
        # from the action class alone. A model-supplied duration never settles time.
        # The production wire carries no time field at all, so this path only fires
        # for an internally injected stage result and stays a pure audit record.
        _world_stage_result = next(
            (sr for sr in llm_stage_results if sr.stage_name == "world" and sr.accepted),
            None,
        )
        if _world_stage_result is not None:
            _advised_minutes = _resolve_elapsed_minutes(
                action_type=action_type,
                intent_result=input_intent_result,
                world_result=_world_stage_result,
            )
            if _advised_minutes != _validator_result.accepted_elapsed_minutes:
                _advised_category = _resolved_category
                _world_cat = getattr(_world_stage_result, "parsed_proposal", {})
                if isinstance(_world_cat, dict) and _world_cat.get("time_category"):
                    _advised_category = _world_cat["time_category"]
                _advised_validator_result = _validator.validate(TimeAdvanceProposal(
                    elapsed_minutes=_advised_minutes,
                    time_category=_advised_category,
                ))
                time_advance_result["world_stage_suggestion"] = {
                    "original_elapsed_minutes": _advised_validator_result.original_elapsed_minutes,
                    "validated_elapsed_minutes": _advised_validator_result.accepted_elapsed_minutes,
                    "category": _advised_validator_result.category,
                    "adjusted": _advised_validator_result.adjusted,
                    "adopted": False,
                    "reason": "rejected_after_adjudication",
                }

        # Refresh only the adjudicated facts that were not knowable during the
        # preparation freeze; do not reread state after this turn is applied.
        frozen_narration_context["world_time"] = jsonable_encoder(world_time)
        frozen_narration_context["npc_reactions"] = [
            {
                "npc_name": reaction.get("npc_name"),
                "action_type": reaction.get("action_type"),
                "summary": reaction.get("summary"),
                "visible_to_player": reaction.get("visible_to_player", True),
            }
            for reaction in npc_reactions_for_json
            if reaction.get("accepted", False) and reaction.get("visible_to_player", True)
        ]

        # Scheduled-event settlement uses the single adjudicated world_time above.
        #
        # Phase 3 replaces this path entirely: the slice's own steps were already
        # settled by the advance, so calling the legacy processor here would settle
        # the same game time twice. The processor also refuses the slice's
        # namespaced rows outright, so a wiring mistake fails loudly instead of
        # firing a step whose conditions its legacy logic cannot read.
        scheduled_event_results: list[dict[str, Any]] = []
        if phase3_result is None and content_result is None:
            try:
                from ..models.events import WorldTime
                world_time_obj = WorldTime(
                    calendar=world_time.get("calendar", "修仙历"),
                    season=world_time.get("season", "春"),
                    day=_parse_world_day(world_time.get("day", "第1日")),
                    period=world_time.get("period", "辰时"),
                    hour=world_time.get("hour", 7),
                    minute=world_time.get("minute", 0),
                )
                scheduled_processor = ScheduledEventProcessor(db)
                scheduled_event_results = scheduled_processor.process_scheduled_events(
                    session_id=session_id,
                    world_time=world_time_obj,
                    current_turn=turn_no,
                    world_state=None,
                    transaction_id=transaction_id,
                )
                if scheduled_event_results:
                    logger.info(
                        "Fired %d scheduled events for session %s turn %d",
                        len(scheduled_event_results),
                        session_id,
                        turn_no,
                    )
            except Exception as e:
                if is_managed(db):
                    raise
                logger.warning(
                    "ScheduledEventProcessor failed for session %s turn %d: %s",
                    session_id,
                    turn_no,
                    e,
                )
        
        # Add this turn's adjudicated scheduler output to the frozen narration
        # snapshot without rereading session state.
        if scheduled_event_results:
            frozen_narration_context["scheduled_events"] = jsonable_encoder(
                scheduled_event_results
            )

        # The committed snapshot remains template narration until the post-commit
        # stage succeeds and the presentation CAS accepts its generation.
        final_narration = narration
        
        # Step 16b: Persist the engine's adjudicated fact events.
        #
        # Only events the domain resolution produced get a row. The previous
        # behaviour — turning model candidate events into world/scene fact events —
        # is gone: a world/scene proposal may only *reference* engine results, so a
        # model description can never be promoted into a committed fact.
        player_action_event_id: Optional[str] = refused_action_event_id
        if player_action_resolution is not None:
            for engine_event in player_action_resolution.events:
                if engine_event.game_event_type is None:
                    continue
                created_id = _create_game_event(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    event_type=engine_event.game_event_type,
                    actor_id=engine_event.actor_id,
                    target_ids=list(engine_event.target_ids) or None,
                    visibility_scope=engine_event.visibility_scope,
                    public_payload=engine_event.public_payload,
                    private_payload=engine_event.private_payload,
                    result_json=engine_event.result_json,
                )
                if engine_event.is_action_cause and created_id is not None:
                    player_action_event_id = created_id
        
        if world_reference is not None:
            for engine_event in world_reference.events:
                _create_game_event(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    event_type=engine_event.game_event_type or "world_tick",
                    actor_id=engine_event.actor_id,
                    target_ids=list(engine_event.target_ids) or None,
                    visibility_scope=engine_event.visibility_scope,
                    public_payload=engine_event.public_payload,
                    private_payload=engine_event.private_payload,
                    result_json=engine_event.result_json,
                )
        
        if scene_reference is not None:
            for engine_event in scene_reference.events:
                _create_game_event(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    event_type=engine_event.game_event_type or "scene",
                    actor_id=engine_event.actor_id,
                    target_ids=list(engine_event.target_ids) or None,
                    visibility_scope=engine_event.visibility_scope,
                    public_payload=engine_event.public_payload,
                    private_payload=engine_event.private_payload,
                    result_json=engine_event.result_json,
                )
        
        # GameEvent ids of this turn's npc_decision rows. These are used only for
        # the delta-causality audit; memory rows reference the EventLog id.
        npc_event_ids: Dict[str, str] = {}
        for npc_reaction in npc_reactions_for_json:
            npc_id = npc_reaction.get("npc_id")
            npc_name = npc_reaction.get("npc_name")
            action_type_npc = npc_reaction.get("action_type")
            summary = npc_reaction.get("summary")
            visible_to_player = npc_reaction.get("visible_to_player", True)
            accepted = bool(npc_reaction.get("accepted"))
            
            if accepted:
                # An accepted NPC action has an engine adjudication; it carries the
                # fact row. A refused/fallen-back proposal is recorded as a decision
                # audit with accepted=False and never as an NPC fact.
                npc_event = ResolvedEvent(
                    kind=ResolvedEventKind.NPC_OBSERVE,
                    actor_id=npc_id or "unknown",
                    action_type=action_type_npc or "idle",
                    game_event_type="npc_decision",
                    target_ids=("player",) if visible_to_player else (),
                    visibility_scope="player_visible" if visible_to_player else "hidden",
                    public_payload={
                        "npc_name": npc_name,
                        "action_type": action_type_npc,
                        "summary": summary,
                        "utterance": npc_reaction.get("utterance"),
                    } if visible_to_player else None,
                    private_payload={
                        "npc_name": npc_name,
                        "action_type": action_type_npc,
                        "summary": summary,
                        "visible_motivation": npc_reaction.get("visible_motivation"),
                    } if not visible_to_player else None,
                    result_json={
                        "physical_effect": False,
                        "used_memory_ids": list(npc_reaction.get("used_memory_ids", []) or []),
                    },
                )
            else:
                npc_event = ResolvedEvent(
                    kind=ResolvedEventKind.NPC_IDLE,
                    actor_id=npc_id or "unknown",
                    action_type="idle",
                    game_event_type="npc_decision",
                    target_ids=(),
                    visibility_scope="hidden",
                    private_payload={
                        "npc_name": npc_name,
                        "action_type": "idle",
                        "summary": None,
                    },
                    result_json={
                        "accepted": False,
                        "fallback_reason": npc_reaction.get("fallback_reason"),
                        "authorization_detail": npc_reaction.get("authorization_detail"),
                    },
                )
            
            created_npc_event_id = _create_game_event(
                db=db,
                transaction_id=transaction_id,
                session_id=session_id,
                turn_no=turn_no,
                event_type=npc_event.game_event_type or "npc_decision",
                actor_id=npc_event.actor_id,
                target_ids=list(npc_event.target_ids) or None,
                visibility_scope=npc_event.visibility_scope,
                public_payload=npc_event.public_payload,
                private_payload=npc_event.private_payload,
                result_json=npc_event.result_json,
            )
            if created_npc_event_id is not None and npc_id:
                npc_event_ids[npc_id] = created_npc_event_id
        
        narration_event_id = _create_game_event(
            db=db,
            transaction_id=transaction_id,
            session_id=session_id,
            turn_no=turn_no,
            event_type="narration",
            actor_id="narrator",
            target_ids=["player"],
            visibility_scope="player_visible",
            public_payload={
                "text": final_narration,
                "action_type": action_type,
            },
            result_json={
                "world_time": world_time,
                "location_id": current_location_id,
                "presentation_only": True,
            },
        )
        
        # Step 16c: Create state_delta records for the engine's adjudicated changes.
        #
        # The delta's causal source is the engine's *action* event, not the
        # narration presentation event: a delta must point at the real reason a
        # state changed. The narration event exists only for presentation and sits
        # on the same transaction, so it can never be mistaken for the cause.
        state_deltas_created = _create_state_deltas_for_turn(
            db=db,
            transaction_id=transaction_id,
            session_id=session_id,
            turn_no=turn_no,
            action_type=action_type,
            movement_result=movement_result,
            world_time_before=world_time_before,
            world_time_after=world_time,
            player_state_before=None,
            player_state_after=player_state,
            npc_states_before=None,
            npc_states_after=None,
            source_event_id=player_action_event_id or narration_event_id,
        )
        
        # Step 16d: Create llm_stage_result and validation_report records
        all_llm_stage_results = [input_intent_result] + llm_stage_results
        llm_stage_results_created = _create_llm_stage_results_for_turn(
            db=db,
            transaction_id=transaction_id,
            session_id=session_id,
            turn_no=turn_no,
            llm_stage_results=all_llm_stage_results,
        )
        
        # Step 17: Update result_json with the action-resolution summary, LLM stage
        # results, the scene reference and NPC reactions.
        # ``fallback_used`` describes the *action resolution*: True when the
        # player's action was not derived from an accepted production contract (a
        # model outage, a contract-incompatible answer, or a refused proposal whose
        # effect the deterministic path then re-derived). Individual stage fallbacks
        # are recorded per stage in ``llm_stages`` instead.
        action_resolution_summary = phase3_resolution_override
        if action_resolution_summary is None:
            action_resolution_summary = _build_action_resolution_summary(
                action_type=action_type,
                resolution=player_action_resolution,
                authorization=authorization,
                fallback_used=intent_contract is None,
                reason_override=_action_reason_override(
                    resolution=player_action_resolution,
                    intent_contract=intent_contract,
                    input_intent_result=input_intent_result,
                ),
            )
        llm_stages_json = [sr.to_result_json_dict() for sr in llm_stage_results]
        input_intent_stage_json = input_intent_result.to_result_json_dict()
        updated_result_json = {
            "transaction_id": transaction_id,
            "recommended_actions": final_recommended_actions,
            "state_deltas": state_deltas,
            "action_type": action_type,
            "action_resolution": action_resolution_summary,
            "movement_success": movement_result.success if movement_result else None,
            "new_location_id": movement_result.new_location_id if movement_result else None,
            "world_time_before": world_time_before,
            "world_time": world_time,
            "input_intent": input_intent_metadata,
            "input_intent_fallback_reason": input_intent_fallback_reason,
            "llm_stages": llm_stages_json,
            "input_intent_stage": input_intent_stage_json,
            "scene_event_summary": scene_event_summary,
            "scene_fallback_reason": scene_fallback_reason,
            "npc_reactions": npc_reactions_for_json,
            "npc_fallback_reason": npc_fallback_reason,
            "world_progression": world_progression,
            "world_fallback_reason": world_fallback_reason,
            "time_advance_result": time_advance_result,
            "player_state": player_state,
            "events_committed": 1,
            "actions_committed": 1 if movement_result and movement_result.success else 0,
            "validation_passed": True,
            "is_new_turn": is_new,
            "recovery_status": "complete",
            "presentation_status": "template",
            "presentation_version": 0,
            "turn_result_v1": {
                "version": 1,
                "turn_no": turn_no,
                "narration": narration,
                "presentation_status": "template",
                "generation": claim_token.generation,
                "recommended_actions": deterministic_recommended_actions,
                "state_deltas": state_deltas,
                "world_time": world_time,
                "player_state": player_state,
                "transaction_id": transaction_id,
                "events_committed": 1,
                "actions_committed": 1 if movement_result and movement_result.success else 0,
                "validation_passed": True,
                "is_new_turn": is_new,
                "recovery_status": "complete",
                "time_advance_result": time_advance_result,
                "presentation_version": 0,
                "action_resolution": action_resolution_summary,
            },
        }
        snapshot = updated_result_json["turn_result_v1"]
        # Persist the template representation first; final presentation is a post-commit CAS.
        updated_result_json["narration"] = narration
        updated_result_json["recommended_actions"] = deterministic_recommended_actions
        event_log_repo = EventLogRepository(db)
        event_log_repo.update(event.id, {"result_json": updated_result_json})
        
        # Step 18: Update session state with durable time and location changes
        session_state_update = {
            "session_id": session_id,
            "current_time": _format_world_time(world_time),
            "time_phase": world_time["period"],
        }
        if phase3_write is not None:
            # The advance's merged flags carry the cursor, the monotonic event
            # sequence and the finite one-shot switches. They are written in this
            # same authoritative transaction as the facts they describe.
            session_state_update["global_flags_json"] = phase3_write.global_flags_json
        if movement_result and movement_result.success and movement_result.new_location_id:
            session_state_update["current_location_id"] = movement_result.new_location_id
        session_state_repo.create_or_update(session_state_update)
        
        # Step 19: Update last played
        session_repo.update_last_played(session_id)
        
        memory_result = None
        if _is_memory_stage_enabled(db):
            memory_result = _persist_turn_memories(
                db=db,
                session_id=session_id,
                turn_no=turn_no,
                event_id=event.id,
                action_type=action_type,
                player_input=player_input,
                movement_result=movement_result,
                state_deltas=state_deltas,
                current_location_id=current_location_id,
                npc_reactions=npc_reactions_for_json,
                player_resolution=player_action_resolution,
                npc_resolutions=_npc_resolutions_for_turn(llm_stage_results),
                canonical_state=canonical_state,
            )
            
            if memory_result:
                updated_result_json["memory_persistence"] = {
                    "summaries_created": memory_result.get("summaries_created", 0),
                    "facts_created": memory_result.get("facts_created", 0),
                    "npc_memories_created": memory_result.get("npc_memories_created", 0),
                    "npc_beliefs_created": memory_result.get("npc_beliefs_created", 0),
                    "relationship_memories_created": memory_result.get("relationship_memories_created", 0),
                    "fallback_reason": memory_result.get("fallback_reason"),
                }
                event_log_repo.update(event.id, {"result_json": updated_result_json})
        
        # Final budget gate after the lock/revalidation/write work and immediately
        # before the full-token claim CAS. Expiry means no facts may commit.
        if budget.expired():
            raise TurnBudgetExceededError(
                session_id=session_id,
                turn_no=turn_no,
                total_seconds=budget.total_seconds,
            )
        # Fencing: only the exact worker that still owns this generation under a live
        # lease may mark the claim committed, in the same transaction as its facts.
        try:
            commit_claim(db, claim_token, world_time_after=_format_world_time(world_time))
        except ClaimRejected as exc:
            raise TurnClaimConflictError("claim_lost", session_id) from exc
        turn_uow.allow_commit()
        # From here on a failure means "commit receipt unknown", not "nothing happened".
        authoritative_commit_attempted = True
        db.commit()
        turn_uow.__exit__(None, None, None)
        turn_uow = None

        # The sole authoritative fact commit and UoW exit are complete. Only now
        # may narration invoke a model; it receives the preparation-frozen context.
        _emit("narration", "started")
        try:
            narration_result = _execute_narration_stage(
                db=db,
                session_id=session_id,
                turn_no=turn_no,
                canonical_state=canonical_state,
                player_input=player_input,
                action_type=action_type,
                movement_result=movement_result,
                state_deltas=state_deltas,
                current_location_id=current_location_id,
                npc_reactions=None,
                use_mock=use_mock,
                frozen_context=frozen_narration_context,
            )
        except Exception as narration_error:
            logger.warning("Post-commit narration failed: %s", narration_error)
            narration_result = LLMStageResult(
                stage_name="narration",
                enabled=True,
                timeout=30.0,
                accepted=False,
                fallback_reason=f"post_commit_error: {str(narration_error)[:200]}",
            )
        post_commit_leak_validation = None
        if narration_result.accepted and narration_result.parsed_proposal:
            candidate_text = narration_result.parsed_proposal.get("text", "")
            post_commit_leak_validation = NarrationLeakValidator().validate_narration(
                text=candidate_text,
                forbidden_info=[],
                state=canonical_state,
                db=None,
                session_id=None,
                preloaded_forbidden_facts=frozen_narration_forbidden_info,
                forbidden_patterns=[
                    "隐藏身份", "真实身份", "hidden_identity", "secret_identity"
                ],
            )
            if not post_commit_leak_validation.is_valid:
                narration_result.accepted = False
                narration_result.validation_errors = post_commit_leak_validation.errors
                narration_result.fallback_reason = (
                    "leak_detected: "
                    + ", ".join(post_commit_leak_validation.errors[:3])
                )
        _emit("narration", "completed")

        if narration_result.accepted and narration_result.parsed_proposal:
            candidate_text = narration_result.parsed_proposal.get("text")
            if candidate_text:
                final_narration = candidate_text

        # Post-commit stage audit is an independent short transaction. Do not
        # rewrite the fact event's llm_stages JSON with this presentation result.
        audit_db = sessionmaker(
            bind=db.get_bind(), autoflush=False, expire_on_commit=False
        )()
        try:
            if post_commit_leak_validation is not None and not post_commit_leak_validation.is_valid:
                _create_validation_report(
                    db=audit_db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    scope="narration_leak_validation",
                    is_valid=False,
                    errors_json=post_commit_leak_validation.errors,
                    warnings_json=post_commit_leak_validation.warnings,
                )
            _create_llm_stage_results_for_turn(
                db=audit_db,
                transaction_id=transaction_id,
                session_id=session_id,
                turn_no=turn_no,
                llm_stage_results=[narration_result],
            )
            audit_db.commit()
        except Exception as audit_error:
            audit_db.rollback()
            logger.warning("Failed to persist post-commit narration audit: %s", audit_error)
        finally:
            audit_db.close()

        presentation_finalized = _finalize_turn_presentation(
            db, event.id, claim_token, final_narration, final_recommended_actions,
            narration_event_id=narration_event_id,
        )
        if not presentation_finalized:
            final_narration = narration
            final_recommended_actions = deterministic_recommended_actions

        # Step 22: Return the same durable presentation snapshot used by retries and SSE.
        return TurnResult(
            turn_no=turn_no,
            narration=final_narration,
            recommended_actions=final_recommended_actions,
            state_deltas=state_deltas,
            world_time=world_time,
            player_state=player_state,
            transaction_id=transaction_id,
            events_committed=1,
            actions_committed=1 if movement_result and movement_result.success else 0,
            validation_passed=True,
            movement_result=movement_result,
            is_new_turn=is_new,
            llm_stage_results=[input_intent_result] + llm_stage_results + [narration_result],
            time_advance_result=time_advance_result,
            idempotency_key=claim_key,
            recovery_status="complete",
            presentation_version=1 if presentation_finalized else 0,
            action_resolution=action_resolution_summary,
        )
    
    except Exception as e:
        # Renewals stop before any terminal handling of the claim, so the aborted
        # short transaction cannot race a heartbeat that still owns the row.
        _stop_heartbeat()
        _rollback_turn_uow(e)
        if authoritative_commit_attempted and _claim_row_is_committed(db, claim_token):
            # The authoritative db.commit() raised, so the durable receipt is unknown:
            # the facts may or may not be committed. Never guess — neither by replaying
            # the turn nor by blindly marking the claim aborted (which would hide
            # committed facts behind an "aborted" row and invite a duplicate turn).
            # The database is the authority, so re-read the claim row: a committed row
            # means the turn is durable and this call takes the same read-only recovery
            # path as a same-key retry, reusing the persisted snapshot instead of
            # regenerating it.
            recovered = _get_existing_turn_result(db, session_id, claim_token.turn_no)
            if recovered is None:
                raise TurnRecoveryIncompleteError(
                    "Committed turn claim has no complete player_turn result snapshot",
                    session_id=session_id,
                    turn_no=claim_token.turn_no,
                ) from e
            recovered.idempotency_key = claim_key
            return recovered
        # A rolled-back attempt still retains a sanitized audit in an independent
        # short transaction, tagged with this worker's fencing generation.
        try:
            write_buffer.persist_failed_model_audits(db.get_bind(), claim_token.generation)
        except Exception:
            logger.warning("Failed to write independent model-call audit", exc_info=True)
        # Fence the same claim row as aborted in its own short transaction.
        try:
            abort_claim(db, claim_token, {"category": "turn_execution_failed", "type": type(e).__name__})
            db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        # Every exit path of the execution body stops and joins the heartbeat.
        _stop_heartbeat()
        if db.info.get("turn_write_buffer") is write_buffer:
            db.info.pop("turn_write_buffer", None)
        db.info.pop("phase3_npc_overlay", None)
        db.info.pop("content_runtime_context", None)
        db.info.pop("content_npc_decision_contexts", None)
        db.info.pop("content_event_ids", None)
        db.info.pop("content_tick_positions", None)


def _claim_row_is_committed(db: Session, token) -> bool:
    """Confirm an uncertain commit receipt by re-reading the claim row.

    Only used after the authoritative ``db.commit()`` raised. The Session is rolled
    back first so the read starts a fresh transaction and reflects durable state
    instead of the failed transaction's identity map. A missing row or a read error
    reports "not committed", which keeps the conservative abort path: the abort CAS
    itself still requires the full token, ``pending`` status and a live lease, so a
    taken-over or already-committed row is never overwritten.
    """
    try:
        db.rollback()
    except Exception:
        logger.warning("Rollback before commit-receipt confirmation failed", exc_info=True)
    try:
        row = db.query(TurnTransactionModel).filter_by(
            id=token.transaction_id,
            session_id=token.session_id,
        ).one_or_none()
        return (
            row is not None
            and row.status == "committed"
            and row.fencing_generation == token.generation
            and row.idempotency_key == token.idempotency_key
            and row.request_fingerprint == token.request_fingerprint
            and row.turn_no == token.turn_no
        )
    except Exception:
        db.rollback()
        logger.warning(
            "Could not confirm the commit receipt for claim %s",
            token.transaction_id,
            exc_info=True,
        )
        return False


def _finalize_turn_presentation(
    db: Session,
    event_id: str,
    claim_token,
    narration: str,
    recommended_actions: List[str],
    narration_event_id: Optional[str] = None,
) -> bool:
    """CAS-finalize only presentation fields after the fact transaction is durable."""
    try:
        transaction = db.query(TurnTransactionModel).filter_by(
            id=claim_token.transaction_id,
            session_id=claim_token.session_id,
        ).with_for_update().one_or_none()
        event = db.query(EventLogModel).filter_by(id=event_id).with_for_update().one_or_none()
        if (
            transaction is None
            or event is None
            or transaction.status != "committed"
            or transaction.fencing_generation != claim_token.generation
            or transaction.turn_no != claim_token.turn_no
        ):
            db.rollback()
            return False

        stored = dict(event.result_json or {})
        snapshot = stored.get("turn_result_v1")
        if not isinstance(snapshot, dict):
            db.rollback()
            return False
        if (
            snapshot.get("presentation_status") != "template"
            or snapshot.get("transaction_id") != claim_token.transaction_id
            or snapshot.get("generation") != claim_token.generation
            or snapshot.get("presentation_version") != 0
        ):
            db.rollback()
            return False

        # Preserve the entire fact-bearing JSON object; update only the presentation allowlist.
        updated_snapshot = dict(snapshot)
        updated_snapshot.update({
            "narration": narration,
            "recommended_actions": recommended_actions,
            "presentation_status": "finalized",
            "presentation_version": 1,
        })
        stored.update({
            "narration": narration,
            "recommended_actions": recommended_actions,
            "presentation_status": "finalized",
            "presentation_version": 1,
            "turn_result_v1": updated_snapshot,
        })
        event.narrative_text = narration
        event.result_json = stored
        if narration_event_id is not None:
            narration_event = db.query(GameEventModel).filter_by(
                id=narration_event_id,
                transaction_id=claim_token.transaction_id,
                session_id=claim_token.session_id,
                turn_no=claim_token.turn_no,
                event_type="narration",
            ).with_for_update().one_or_none()
            if narration_event is None:
                db.rollback()
                return False
            public_payload = dict(narration_event.public_payload_json or {})
            public_payload["text"] = narration
            narration_event.public_payload_json = public_payload
        db.commit()
        return True
    except Exception:
        # The fact commit has already succeeded; presentation failure must not undo it.
        db.rollback()
        logger.warning("Turn presentation CAS failed for event %s", event_id, exc_info=True)
        return False


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
    snapshot = result_json.get("turn_result_v1")
    if not isinstance(snapshot, dict):
        snapshot = result_json
    required = {"world_time", "player_state", "events_committed", "actions_committed"}
    legacy_partial = not required.issubset(snapshot)
    return TurnResult(
        turn_no=snapshot.get("turn_no", turn_no),
        narration=event.narrative_text or snapshot.get("narration", ""),
        recommended_actions=snapshot.get("recommended_actions", result_json.get("recommended_actions", [])),
        state_deltas=snapshot.get("state_deltas", result_json.get("state_deltas", {})),
        world_time=snapshot.get("world_time", {}),
        player_state=snapshot.get("player_state", {}),
        transaction_id=snapshot.get("transaction_id", result_json.get("transaction_id")),
        events_committed=snapshot.get("events_committed", 0),
        actions_committed=snapshot.get("actions_committed", 0),
        validation_passed=snapshot.get("validation_passed", False),
        is_new_turn=False,
        time_advance_result=snapshot.get("time_advance_result"),
        recovery_status="legacy_partial" if legacy_partial else snapshot.get("recovery_status", "complete"),
        presentation_version=snapshot.get("presentation_version", 0),
        # A same-key recovery is read-only: it returns the saved summary verbatim.
        # A legacy snapshot without one reports None rather than running a fresh
        # authorization or model call to reconstruct it.
        action_resolution=(
            snapshot.get("action_resolution")
            if isinstance(snapshot.get("action_resolution"), dict)
            else None
        ),
    )


def _commit_clarification_turn(
    db: Session,
    session_id: str,
    player_input: str,
    claim_key: str,
    claim_token: Any,
    turn_no: int,
    transaction_id: str,
    fp_before: str,
    world_time_before: Dict[str, Any],
    write_buffer: TurnWriteBuffer,
    turn_uow: TurnUnitOfWork,
    heartbeat: ClaimHeartbeat,
    budget: TurnBudget,
    input_intent_result: Optional[LLMStageResult] = None,
    input_intent_metadata: Optional[Dict[str, Any]] = None,
    clarification_question: Optional[str] = None,
    content_binding_prepared: Optional[ContentRuntimeBinding] = None,
) -> TurnResult:
    """Commit an explicitly ambiguous input as a zero-time, zero-action turn.

    This intentionally persists only the idempotent player_turn event and claim CAS;
    it does not initialize state or run action/world/scene/NPC/scheduling/memory work.
    """
    question = clarification_question.strip()[:240] if clarification_question else ""
    if not question:
        question = "你想前往哪里？请告诉我具体地点。"

    clarification_resolution = _build_action_resolution_summary(
        action_type="move",
        resolution=None,
        authorization=None,
        fallback_used=False,
        status_override=ActionStatus.CLARIFICATION,
    )

    if not heartbeat.stop() or heartbeat.lost:
        raise TurnClaimConflictError("claim_lost", session_id)
    if budget.expired():
        raise TurnBudgetExceededError(
            session_id=session_id,
            turn_no=turn_no,
            total_seconds=budget.total_seconds,
        )
    _end_read_transaction(db)
    acquire_turn_lock(db, session_id)
    if content_binding_prepared is not None:
        locked_binding = read_content_binding(db, session_id=session_id)
        if locked_binding != content_binding_prepared:
            raise ContentRuntimeError(
                "CONTENT_BINDING_MISMATCH",
                "content binding changed before the clarification turn commit",
            )
        if compute_state_fingerprint(db, session_id) != fp_before:
            raise TurnStateConflictError(session_id)
    elif db.get_bind().dialect.name != "sqlite":
        fp_after = compute_state_fingerprint(db, session_id)
        if fp_after != fp_before:
            raise TurnStateConflictError(session_id)

    time_advance_result = {
        "accepted_elapsed_minutes": 0,
        "original_elapsed_minutes": 0,
        "adjusted": False,
        "reason": "clarification_requires_no_time",
        "category": "clarification",
        "new_world_time": world_time_before,
        "needs_clarification": True,
        "clarification_question": question,
    }
    result_json = {
        "transaction_id": transaction_id,
        "recommended_actions": [],
        "state_deltas": {},
        "action_type": "clarification",
        "action_resolution": clarification_resolution,
        "world_time_before": world_time_before,
        "world_time": world_time_before,
        "input_intent": input_intent_metadata,
        "time_advance_result": time_advance_result,
        "events_committed": 1,
        "actions_committed": 0,
        "validation_passed": True,
        "is_new_turn": True,
        "recovery_status": "complete",
        "presentation_status": "template",
        "presentation_version": 0,
    }
    planned_event = write_buffer.add_event_log(
        session_id=session_id,
        turn_no=turn_no,
        event_type="player_turn",
        input_text=player_input,
        narrative_text=question,
        result_json=result_json,
        idempotency_key=claim_key,
    )
    event = write_buffer.flush(db)[planned_event.id]
    snapshot = {
        "version": 1,
        "turn_no": turn_no,
        "narration": question,
        "presentation_status": "template",
        "generation": claim_token.generation,
        "recommended_actions": [],
        "state_deltas": {},
        "world_time": world_time_before,
        "player_state": {},
        "transaction_id": transaction_id,
        "events_committed": 1,
        "actions_committed": 0,
        "validation_passed": True,
        "is_new_turn": True,
        "recovery_status": "complete",
        "time_advance_result": time_advance_result,
        "presentation_version": 0,
        "action_resolution": clarification_resolution,
    }
    result_json["turn_result_v1"] = snapshot
    event.result_json = result_json

    if budget.expired():
        raise TurnBudgetExceededError(
            session_id=session_id,
            turn_no=turn_no,
            total_seconds=budget.total_seconds,
        )
    try:
        commit_claim(db, claim_token, world_time_after=_format_world_time(world_time_before))
    except ClaimRejected as exc:
        raise TurnClaimConflictError("claim_lost", session_id) from exc
    turn_uow.allow_commit()
    try:
        db.commit()
    except Exception:
        if _claim_row_is_committed(db, claim_token):
            recovered = _get_existing_turn_result(db, session_id, turn_no)
            if recovered is not None:
                turn_uow.__exit__(None, None, None)
                recovered.idempotency_key = claim_key
                return recovered
        raise
    turn_uow.__exit__(None, None, None)

    finalized = _finalize_turn_presentation(db, event.id, claim_token, question, [])
    return TurnResult(
        turn_no=turn_no,
        narration=question,
        recommended_actions=[],
        state_deltas={},
        world_time=world_time_before,
        player_state={},
        transaction_id=transaction_id,
        events_committed=1,
        actions_committed=0,
        validation_passed=True,
        is_new_turn=True,
        llm_stage_results=[input_intent_result] if input_intent_result is not None else [],
        time_advance_result=time_advance_result,
        idempotency_key=claim_key,
        recovery_status="complete",
        presentation_version=1 if finalized else 0,
        action_resolution=clarification_resolution,
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
        time_parts = session_state.current_time.split()
        if len(time_parts) >= 4:
            result = {
                "calendar": time_parts[0],
                "season": time_parts[1],
                "day": time_parts[2],
                "period": time_parts[3],
            }
            # New format: "修仙历 春 第1日 辰时 07:00"
            if len(time_parts) >= 5:
                time_str = time_parts[4]
                if ":" in time_str:
                    try:
                        h, m = time_str.split(":")
                        result["hour"] = int(h)
                        result["minute"] = int(m)
                        day_int = _parse_world_day(result["day"])
                        result["total_minutes"] = (day_int - 1) * 1440 + result["hour"] * 60 + result["minute"]
                    except (ValueError, IndexError):
                        pass
            return result
    
    # Default world time
    return {
        "calendar": "修仙历",
        "season": "春",
        "day": "第1日",
        "period": "辰时",
    }


def _parse_world_day(day_value: Any) -> int:
    if isinstance(day_value, int):
        return day_value
    if isinstance(day_value, str):
        digits = "".join(ch for ch in day_value if ch.isdigit())
        if digits:
            return int(digits)
    return 1


def _resolve_elapsed_minutes(
    action_type: Optional[str] = None,
    intent_result: Optional[Any] = None,
    world_result: Optional[Any] = None,
) -> int:
    """Resolve elapsed minutes for time advancement.

    Priority:
    1. Extract from world_result.parsed_proposal.get("elapsed_minutes")
    2. Map intent_type to time_category via INTENT_TO_TIME_CATEGORY, then DETERMINISTIC_DEFAULTS
    3. Fallback: return 10 (default)
    """
    from .time_advance import DETERMINISTIC_DEFAULTS, INTENT_TO_TIME_CATEGORY

    if world_result is not None:
        parsed = getattr(world_result, "parsed_proposal", None)
        if parsed and isinstance(parsed, dict):
            em = parsed.get("elapsed_minutes")
            if isinstance(em, (int, float)) and em >= 0:
                return int(em)

    intent_type = None
    if intent_result is not None:
        parsed = getattr(intent_result, "parsed_proposal", None)
        if parsed and isinstance(parsed, dict):
            intent_type = parsed.get("intent_type")
    if intent_type is None and action_type:
        intent_type = action_type

    if intent_type and intent_type in INTENT_TO_TIME_CATEGORY:
        category = INTENT_TO_TIME_CATEGORY[intent_type]
        if category in DETERMINISTIC_DEFAULTS:
            return DETERMINISTIC_DEFAULTS[category]

    return 10


def _advance_world_time(world_time: Dict[str, Any], elapsed_minutes: Optional[int] = None) -> Dict[str, Any]:
    from ..models.events import WorldTime

    seasons = ["春", "夏", "秋", "冬"]

    if elapsed_minutes is None:
        # Old behavior: advance 1 period (2 hours)
        periods = [
            "子时", "丑时", "寅时", "卯时", "辰时", "巳时",
            "午时", "未时", "申时", "酉时", "戌时", "亥时",
        ]
        current_period = world_time.get("period", "辰时")
        try:
            current_index = periods.index(current_period)
        except ValueError:
            current_index = periods.index("辰时")

        next_index = (current_index + 1) % len(periods)
        day = _parse_world_day(world_time.get("day", "第1日"))
        season = world_time.get("season", "春")

        if next_index == 0:
            day += 1
            if day > 30:
                day = 1
                try:
                    season = seasons[(seasons.index(season) + 1) % 4]
                except ValueError:
                    season = "春"

        return {
            "calendar": world_time.get("calendar", "修仙历"),
            "season": season,
            "day": f"第{day}日",
            "period": periods[next_index],
        }

    # Minute-precision path
    if elapsed_minutes == 0:
        result = {
            "calendar": world_time.get("calendar", "修仙历"),
            "season": world_time.get("season", "春"),
            "day": world_time.get("day", "第1日"),
            "period": world_time.get("period", "辰时"),
        }
        hour = world_time.get("hour")
        minute = world_time.get("minute")
        if hour is not None and minute is not None:
            result["hour"] = hour
            result["minute"] = minute
            result["total_minutes"] = world_time.get("total_minutes", (_parse_world_day(result["day"]) - 1) * 1440 + hour * 60 + minute)
            result["display_text"] = f"{result['calendar']} {result['season']} {result['day']} {result['period']} {hour:02d}:{minute:02d}"
        return result

    calendar = world_time.get("calendar", "修仙历")
    season = world_time.get("season", "春")
    day = _parse_world_day(world_time.get("day", "第1日"))

    # Derive current hour/minute from world_time dict
    if "hour" in world_time and "minute" in world_time:
        current_hour = int(world_time["hour"])
        current_minute = int(world_time["minute"])
    else:
        current_hour = WorldTime.from_period(world_time.get("period", "辰时"))
        current_minute = 0

    total_minutes = (day - 1) * 1440 + current_hour * 60 + current_minute + elapsed_minutes
    new_day = total_minutes // 1440 + 1
    remaining = total_minutes % 1440
    new_hour = remaining // 60
    new_minute = remaining % 60
    new_period = WorldTime.derive_period(new_hour)

    # Season rollover: every 30 days
    while new_day > 30:
        new_day -= 30
        try:
            season = seasons[(seasons.index(season) + 1) % 4]
        except ValueError:
            season = "春"

    display_text = f"{calendar} {season} 第{new_day}日 {new_period} {new_hour:02d}:{new_minute:02d}"

    return {
        "calendar": calendar,
        "season": season,
        "day": f"第{new_day}日",
        "period": new_period,
        "hour": new_hour,
        "minute": new_minute,
        "total_minutes": total_minutes,
        "display_text": display_text,
    }


def _format_world_time(world_time: Dict[str, Any]) -> str:
    parts = [
        str(world_time.get("calendar", "修仙历")),
        str(world_time.get("season", "春")),
        str(world_time.get("day", "第1日")),
        str(world_time.get("period", "辰时")),
    ]
    hour = world_time.get("hour")
    minute = world_time.get("minute")
    if hour is not None and minute is not None:
        parts.append(f"{int(hour):02d}:{int(minute):02d}")
    return " ".join(parts)


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


def _is_memory_stage_enabled(db: Session) -> bool:
    """
    Check if memory persistence stage is enabled.
    
    Memory persistence is ALWAYS enabled because it uses already-computed
    deterministic data (turn results, state deltas) rather than LLM output.
    This decouples memory writes from LLM provider availability.
    
    Memory persistence should work in mock provider mode for testing.
    """
    return True


def _engine_action_record_text(action_type: str, npc_name: str) -> str:
    """Engine-authored one-line record of an adjudicated NPC action.

    Mirrors ``action_resolution._engine_action_record`` so the retrievable summary
    never contains model-authored prose.
    """
    if action_type == "observe":
        return f"{npc_name}观察了当前场景"
    if action_type == "idle":
        return f"{npc_name}在原地等待"
    return f"{npc_name}执行了{action_type}动作"


def _npc_resolutions_for_turn(
    llm_stage_results: List[LLMStageResult],
) -> Dict[str, ResolvedAction]:
    """Collect the per-NPC engine adjudications from this turn's stage results."""
    resolutions: Dict[str, ResolvedAction] = {}
    for stage_result in llm_stage_results or ():
        if stage_result.stage_name != "npc":
            continue
        if isinstance(stage_result.resolution, dict):
            resolutions.update(stage_result.resolution)
    return resolutions


def _engine_memory_candidates(
    resolution: Optional[ResolvedAction],
    npc_name: str,
    turn_no: int,
    source_event_id: str,
) -> List[Dict[str, Any]]:
    """Build engine-authored private-memory candidates from an adjudicated NPC action.

    Phase 2 boundary: the model no longer supplies ``memory_text``, ``source_id`` or
    ``source_turn_no``. Every candidate here is derived from the engine's own
    resolution of a committed event, so a memory can always be traced to a real
    fact, and a quotation is tagged as overheard speech rather than knowledge.
    """
    if resolution is None:
        return []

    candidates: List[Dict[str, Any]] = []
    for cognition in resolution.cognition:
        content = (cognition.content or "").strip()
        if not content or cognition.kind is CognitionKind.FACT:
            continue
        candidates.append({
            "memory_text": content,
            "knowledge_source": (
                "overheard_speech" if cognition.is_speech else "engine_adjudicated_event"
            ),
            "source_id": source_event_id,
            "source_ref": f"event_log:{source_event_id}",
            "source_turn_no": turn_no,
            "salience": cognition.importance,
            "confidence": cognition.confidence,
            "tags": ["engine_derived", "speech" if cognition.is_speech else "observation"],
            "memory_kind": "decision",
        })
    return candidates


def _persist_turn_memories(
    db: Session,
    session_id: str,
    turn_no: int,
    event_id: str,
    action_type: str,
    player_input: str,
    movement_result: Optional[MovementResult] = None,
    state_deltas: Optional[Dict[str, Any]] = None,
    current_location_id: Optional[str] = None,
    npc_reactions: Optional[List[Dict[str, Any]]] = None,
    player_resolution: Optional[ResolvedAction] = None,
    npc_resolutions: Optional[Dict[str, ResolvedAction]] = None,
    canonical_state: Optional[CanonicalState] = None,
) -> Dict[str, Any]:
    """
    Persist necessary cognition within the managed turn transaction.

    These summaries are retrieved as future-turn context; facts, beliefs and
    source-bound NPC memories likewise affect later decisions. Every write below is
    therefore required to commit atomically with the turn.

    Phase 2 fact/cognition boundary:

    * Facts, beliefs, private memories and recall statistics are derived from the
      engine's adjudicated resolutions of the events being committed in this same
      unit of work. Nothing is derived from free model text.
    * The turn summary is engine-derived. The raw player input is *not* copied into
      it: the input is already recorded as an input/speech record, and repeating it
      in a retrievable summary would let it read as an action-success fact.
    * A speech act produces a "heard X say ..." belief with ``belief_type="speech"``.
      It never becomes ``belief_type="fact"`` and never becomes a world truth.
    * The model's ``new_memory_candidates`` are gone: private memory content is
      authored by the engine from the adjudicated event.

    Returns metadata about persisted cognition. Managed write failures propagate.
    """
    from .memory_writer import MemoryWriter
    from .npc_memory import NPCMemoryManager
    from .summary import SummaryManager
    from .event_log import EventLog

    memory_summary_repo = MemorySummaryRepository(db)
    memory_fact_repo = MemoryFactRepository(db)
    npc_belief_repo = NPCBeliefRepository(db)
    npc_relationship_repo = NPCRelationshipMemoryRepository(db)

    result = {
        "summaries_created": 0,
        "facts_created": 0,
        "npc_memories_created": 0,
        "npc_beliefs_created": 0,
        "relationship_memories_created": 0,
        "fallback_reason": None,
    }

    try:
        event_log = EventLog()
        npc_memory = NPCMemoryManager(
            scope_repo=None,
            belief_repo=npc_belief_repo,
            memory_repo=None,
            secret_repo=None,
            relationship_repo=npc_relationship_repo,
            session_id=session_id,
        )
        summary_manager = SummaryManager()

        memory_writer = MemoryWriter(
            event_log=event_log,
            npc_memory_manager=npc_memory,
            summary_manager=summary_manager,
            memory_summary_repo=memory_summary_repo,
            memory_fact_repo=memory_fact_repo,
            npc_belief_repo=npc_belief_repo,
            npc_relationship_repo=npc_relationship_repo,
            session_id=session_id,
        )

        # 1. Engine-derived turn summary.
        summary_parts: List[str] = []
        if action_type:
            summary_parts.append(f"玩家执行了{action_type}动作")
        if player_resolution is not None and not player_resolution.accepted:
            reason = player_resolution.reason_code.value if player_resolution.reason_code else "rejected"
            summary_parts.append(f"该动作被拒绝（{reason}）")
        if movement_result and movement_result.success:
            summary_parts.append(f"移动到{movement_result.new_location_name}")
        if state_deltas and "quest_progression" in state_deltas:
            for qp in state_deltas["quest_progression"]:
                summary_parts.append(f"任务进展: {qp.get('quest_name', '未知任务')}")

        if summary_parts and canonical_state:
            from ..models.events import SceneEvent, EventType
            mock_events = [SceneEvent(
                event_id=event_id,
                event_type=EventType.SCENE_EVENT,
                turn_index=turn_no,
                scene_id=current_location_id or "unknown",
                trigger="player_action",
                summary="; ".join(summary_parts),
            )]

            memory_writer.write_turn_summary(
                turn_index=turn_no,
                events=mock_events,
                state=canonical_state,
            )
            result["summaries_created"] += 1

        # 2. Facts from the player action's engine adjudication.
        if player_resolution is not None:
            for index, cognition in enumerate(player_resolution.cognition):
                if cognition.kind is not CognitionKind.FACT:
                    continue
                fact_type = cognition.fact_type or "action"
                memory_writer._persist_fact_to_db(
                    fact_id=f"fact_{fact_type}_{session_id}_{turn_no}_{index}",
                    fact_type=fact_type,
                    subject_ref=cognition.subject_ref or "player",
                    fact_key=cognition.fact_key or fact_type,
                    fact_value=cognition.content,
                    confidence=cognition.confidence,
                    source_event_id=event_id,
                )
                result["facts_created"] += 1

        # 3. Quest progression facts: the existing rule-driven progression, whose
        #    values already come from the engine rather than from model text.
        if state_deltas and "quest_progression" in state_deltas:
            for i, qp in enumerate(state_deltas["quest_progression"]):
                quest_name = qp.get("quest_name", "unknown")
                memory_writer._persist_fact_to_db(
                    fact_id=f"fact_quest_{session_id}_{turn_no}_{i}",
                    fact_type="quest_progress",
                    subject_ref=quest_name,
                    fact_key="progression",
                    fact_value=qp.get("message", ""),
                    confidence=0.9,
                    source_event_id=event_id,
                )
                result["facts_created"] += 1

        # 4. NPC cognition from the adjudicated NPC resolutions.
        if npc_reactions and canonical_state:
            for reaction in npc_reactions:
                if not reaction.get("accepted") or not reaction.get("npc_id"):
                    continue

                npc_id = reaction.get("npc_id")
                npc_name = reaction.get("npc_name", "unknown")
                npc_template_id = reaction.get("npc_template_id") or npc_id
                summary = reaction.get("summary", "")
                resolution = (npc_resolutions or {}).get(npc_id)
                # ``memory_facts``/``npc_beliefs`` reference the turn's *EventLog*
                # row (their existing FK target), while ``state_deltas`` references
                # the engine *GameEvent*. The two id spaces are never mixed.
                source_event_id = event_id

                # The retrievable NPC summary is engine-authored: the model's
                # ``summary`` stays a player-facing description on the event payload
                # and is never copied into a retrievable memory record.
                engine_summary = (
                    _engine_action_record_text(
                        reaction.get("action_type", "idle"), npc_name
                    )
                    if resolution is not None
                    else ""
                )
                if engine_summary:
                    from ..models.events import NPCActionEvent, EventType
                    mock_events = [NPCActionEvent(
                        event_id=source_event_id,
                        event_type=EventType.NPC_ACTION,
                        turn_index=turn_no,
                        npc_id=npc_id,
                        action_type=reaction.get("action_type", "idle"),
                        summary=engine_summary,
                    )]

                    memory_writer.write_npc_subjective_summary(
                        npc_id=npc_id,
                        start_turn=turn_no,
                        end_turn=turn_no,
                        events=mock_events,
                        state=canonical_state,
                    )
                    result["npc_memories_created"] += 1

                for cognition in (resolution.cognition if resolution else []):
                    if cognition.kind is not CognitionKind.BELIEF:
                        continue
                    from ..models.events import SceneEvent, EventType
                    observed = SceneEvent(
                        event_id=source_event_id,
                        event_type=EventType.SCENE_EVENT,
                        turn_index=turn_no,
                        scene_id=current_location_id or "unknown",
                        trigger="npc_action",
                        summary=cognition.content,
                    )
                    memory_writer.write_npc_belief_update(
                        npc_id=npc_id,
                        observed_event=observed,
                        current_turn=turn_no,
                        belief_type=cognition.belief_type or "observation",
                        confidence=cognition.confidence,
                    )
                    result["npc_beliefs_created"] += 1

                # Engine-authored private memories (memory-first feature gate and
                # major-NPC scope still apply; the content is never model text).
                engine_candidates = _engine_memory_candidates(
                    resolution, npc_name, turn_no, source_event_id
                )
                if engine_candidates:
                    from ..models.proposals import (
                        NPCActionProposal,
                        ProposalAuditMetadata,
                        ProposalType,
                        ProposalSource,
                    )
                    write_proposal = NPCActionProposal(
                        npc_id=npc_id,
                        action_type=reaction.get("action_type", "idle"),
                        summary=summary,
                        new_memory_candidates=engine_candidates,
                        used_memory_ids=list(reaction.get("used_memory_ids", []) or []),
                        audit=ProposalAuditMetadata(
                            proposal_type=ProposalType.NPC_ACTION,
                            source_engine=ProposalSource.NPC_ENGINE,
                        ),
                    )
                    write_result = write_post_commit_memories(
                        db=db,
                        session_id=session_id,
                        npc_template_id=npc_template_id,
                        proposal=write_proposal,
                        committed_event_ids=[source_event_id],
                        source_turn_no=turn_no,
                    )
                    result["p10c_private_memories_written"] = (
                        result.get("p10c_private_memories_written", 0)
                        + len(write_result.written_ids)
                    )
                    if write_result.errors:
                        logger.warning(
                            "Private-memory write errors session=%s npc=%s: %s",
                            session_id, npc_id, write_result.errors,
                        )

                # Recall statistics for the memories this decision actually used.
                # The id set was validated against the set supplied to this call by
                # the authorization layer, and the check runs regardless of the
                # memory-first toggle.
                used_mem_ids = reaction.get("used_memory_ids")
                if used_mem_ids:
                    updated_count = update_recall_stats_post_commit(
                        db=db,
                        session_id=session_id,
                        npc_template_id=npc_template_id,
                        used_memory_ids=used_mem_ids,
                        current_turn=turn_no,
                    )
                    if updated_count > 0:
                        result["p10c_recall_stats_updated"] = (
                            result.get("p10c_recall_stats_updated", 0)
                            + updated_count
                        )

    except Exception as e:
        if is_managed(db):
            raise
        logger.warning("Memory persistence failed for session %s turn %s: %s", session_id, turn_no, e)
        result["fallback_reason"] = f"memory_write_error: {str(e)[:200]}"

    return result

def _retrieve_memories_for_context(
    db: Session,
    session_id: str,
    scope_type: str,
    scope_ref_id: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Retrieve relevant memory summaries for context building.
    
    Memory is retrieved based on scope:
    - world: World-level chronicles
    - session: Session-level summaries
    - scene: Scene-level summaries for location
    - npc: NPC subjective memory (scoped by NPC ID)
    
    CRITICAL: NPC subjective memory is NEVER returned for player/narrator contexts.
    """
    memory_summary_repo = MemorySummaryRepository(db)
    
    summaries = memory_summary_repo.get_by_scope(
        session_id=session_id,
        scope_type=scope_type,
        scope_ref_id=scope_ref_id,
    )
    
    # Sort by importance and limit
    sorted_summaries = sorted(
        summaries,
        key=lambda s: s.importance_score,
        reverse=True,
    )[:limit]
    
    return [
        {
            "summary_id": s.id,
            "summary_text": s.summary_text,
            "importance": s.importance_score,
            "turn_range": s.source_turn_range,
        }
        for s in sorted_summaries
    ]


def _retrieve_npc_db_memories_for_context(
    db: Session,
    session_id: str,
    npc_id: str,
    limit: int = 5,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Retrieve DB-backed subjective memory for a single NPC.
    
    CRITICAL: Every repository query is scoped by both session_id and npc_id.
    This data is intended for NPC decision context only; do not use it for
    narration/player-visible context construction.
    """
    from datetime import datetime as datetime_type
    
    belief_repo = NPCBeliefRepository(db)
    private_memory_repo = NPCPrivateMemoryRepository(db)
    secret_repo = NPCSecretRepository(db)
    relationship_repo = NPCRelationshipMemoryRepository(db)
    
    beliefs = sorted(
        belief_repo.get_by_npc(session_id=session_id, npc_id=npc_id),
        key=lambda belief: (belief.confidence, belief.last_updated_turn, belief.created_turn),
        reverse=True,
    )[:limit]
    private_memories = sorted(
        private_memory_repo.get_by_npc(session_id=session_id, npc_id=npc_id),
        key=lambda memory: (memory.importance, memory.current_strength, memory.created_turn),
        reverse=True,
    )[:limit]
    secrets = sorted(
        secret_repo.get_by_npc(session_id=session_id, npc_id=npc_id),
        key=lambda secret: (secret.willingness_to_reveal, secret.created_at),
        reverse=True,
    )[:limit]
    relationship_memories = sorted(
        relationship_repo.get_by_npc(session_id=session_id, npc_id=npc_id),
        key=lambda memory: memory.created_turn,
        reverse=True,
    )[:limit]
    
    result: Dict[str, List[Dict[str, Any]]] = {}
    
    if beliefs:
        result["beliefs"] = [
            {
                "belief_id": belief.id,
                "belief_type": belief.belief_type,
                "content": belief.content,
                "confidence": belief.confidence,
                "truth_status": belief.truth_status,
                "source_event_id": belief.source_event_id,
                "created_turn": belief.created_turn,
                "last_updated_turn": belief.last_updated_turn,
            }
            for belief in beliefs
        ]
    
    if private_memories:
        result["private_memories"] = [
            {
                "memory_id": memory.id,
                "memory_type": memory.memory_type,
                "content": memory.content,
                "source_event_ids": memory.source_event_ids_json or [],
                "entities": memory.entities_json or [],
                "importance": memory.importance,
                "emotional_weight": memory.emotional_weight,
                "confidence": memory.confidence,
                "current_strength": memory.current_strength,
                "created_turn": memory.created_turn,
                "last_accessed_turn": memory.last_accessed_turn,
                "recall_count": memory.recall_count,
            }
            for memory in private_memories
        ]
    
    if secrets:
        result["secrets"] = [
            {
                "secret_id": secret.id,
                "content": secret.content,
                "willingness_to_reveal": secret.willingness_to_reveal,
                "reveal_conditions": secret.reveal_conditions_json or [],
                "status": secret.status,
                "created_at": secret.created_at.isoformat() if isinstance(secret.created_at, datetime_type) else None,
            }
            for secret in secrets
        ]
    
    if relationship_memories:
        result["relationship_memories"] = [
            {
                "memory_id": memory.id,
                "target_id": memory.target_id,
                "content": memory.content,
                "impact": memory.impact_json or {},
                "source_event_id": memory.source_event_id,
                "created_turn": memory.created_turn,
            }
            for memory in relationship_memories
        ]
    
    return result


def _retrieve_facts_for_context(
    db: Session,
    session_id: str,
    fact_type: Optional[str] = None,
    subject_ref: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Retrieve relevant memory facts for context building.
    
    Facts are retrieved based on type and subject.
    """
    memory_fact_repo = MemoryFactRepository(db)
    
    facts = []
    if fact_type:
        facts = memory_fact_repo.get_by_type(session_id, fact_type)
    elif subject_ref:
        facts = memory_fact_repo.get_by_subject(session_id, subject_ref)
    else:
        facts = memory_fact_repo.get_by_session(session_id)
    
    # Sort by confidence and limit
    sorted_facts = sorted(
        facts,
        key=lambda f: f.confidence,
        reverse=True,
    )[:limit]
    
    return [
        {
            "fact_id": f.id,
            "fact_type": f.fact_type,
            "subject": f.subject_ref,
            "key": f.fact_key,
            "value": f.fact_value,
            "confidence": f.confidence,
        }
        for f in sorted_facts
    ]


def _create_game_event(
    db: Session,
    transaction_id: str,
    session_id: str,
    turn_no: int,
    event_type: str,
    actor_id: Optional[str] = None,
    target_ids: Optional[List[str]] = None,
    visibility_scope: Optional[str] = "player_visible",
    public_payload: Optional[Dict[str, Any]] = None,
    private_payload: Optional[Dict[str, Any]] = None,
    result_json: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Create a game_event record for event sourcing.
    
    Returns the created event ID, or None on failure.
    """
    from ..storage.models import generate_uuid
    
    game_event_repo = GameEventRepository(db)
    
    try:
        event = game_event_repo.create({
            "id": generate_uuid(),
            "transaction_id": transaction_id,
            "session_id": session_id,
            "turn_no": turn_no,
            "event_type": event_type,
            "actor_id": actor_id,
            "target_ids_json": target_ids,
            "visibility_scope": visibility_scope,
            "public_payload_json": public_payload,
            "private_payload_json": private_payload,
            "result_json": result_json,
            "occurred_at": datetime.now(),
        })
        return event.id
    except Exception as e:
        # A fact event is a necessary write: inside the managed turn transaction a
        # failure must propagate so the whole turn rolls back instead of leaving a
        # committed state whose event sourcing is missing.
        if is_managed(db):
            raise
        logger.warning("Failed to create game_event: %s", e)
        return None


def _create_state_delta(
    db: Session,
    transaction_id: str,
    session_id: str,
    turn_no: int,
    path: str,
    operation: str,
    old_value: Optional[Any] = None,
    new_value: Optional[Any] = None,
    source_event_id: Optional[str] = None,
    visibility_scope: Optional[str] = "player_visible",
    validation_status: Optional[str] = None,
) -> Optional[str]:
    """
    Create a state_delta record for event sourcing.
    
    Returns the created delta ID, or None on failure.
    """
    from ..storage.models import generate_uuid
    
    state_delta_repo = StateDeltaRepository(db)
    
    try:
        delta = state_delta_repo.create({
            "id": generate_uuid(),
            "transaction_id": transaction_id,
            "source_event_id": source_event_id,
            "session_id": session_id,
            "turn_no": turn_no,
            "path": path,
            "operation": operation,
            "old_value_json": old_value,
            "new_value_json": new_value,
            "visibility_scope": visibility_scope,
            "validation_status": validation_status,
            "created_at": datetime.now(),
        })
        return delta.id
    except Exception as e:
        # Delta audit rows are necessary writes for the same reason as fact
        # events: a managed-turn failure must roll the turn back, not be logged.
        if is_managed(db):
            raise
        logger.warning("Failed to create state_delta: %s", e)
        return None


def _create_state_deltas_for_turn(
    db: Session,
    transaction_id: str,
    session_id: str,
    turn_no: int,
    action_type: str,
    movement_result: Optional[MovementResult] = None,
    world_time_before: Optional[Dict[str, Any]] = None,
    world_time_after: Optional[Dict[str, Any]] = None,
    player_state_before: Optional[Dict[str, Any]] = None,
    player_state_after: Optional[Dict[str, Any]] = None,
    npc_states_before: Optional[Dict[str, Any]] = None,
    npc_states_after: Optional[Dict[str, Any]] = None,
    source_event_id: Optional[str] = None,
) -> int:
    """
    Create state_delta records for all state changes in a turn.
    
    Creates deltas for:
    - Location changes (if movement occurred)
    - World time changes
    - Player state changes
    - NPC state changes
    
    Returns the number of deltas created.
    """
    deltas_created = 0
    
    # 1. Location change delta
    if movement_result and movement_result.success:
        old_location = movement_result.old_location_id if hasattr(movement_result, 'old_location_id') else None
        _create_state_delta(
            db=db,
            transaction_id=transaction_id,
            session_id=session_id,
            turn_no=turn_no,
            path="session_state.current_location_id",
            operation="set",
            old_value=old_location,
            new_value=movement_result.new_location_id,
            source_event_id=source_event_id,
            visibility_scope="player_visible",
        )
        deltas_created += 1
    
    # 2. World time change delta
    if world_time_before and world_time_after:
        if world_time_before != world_time_after:
            _create_state_delta(
                db=db,
                transaction_id=transaction_id,
                session_id=session_id,
                turn_no=turn_no,
                path="session_state.world_time",
                operation="set",
                old_value=world_time_before,
                new_value=world_time_after,
                source_event_id=source_event_id,
                visibility_scope="player_visible",
            )
            deltas_created += 1
    
    # 3. Player state changes
    if player_state_before and player_state_after:
        for key in ["realm", "hp", "stamina", "spirit_power"]:
            old_val = player_state_before.get(key)
            new_val = player_state_after.get(key)
            if old_val != new_val:
                _create_state_delta(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    path=f"player_state.{key}",
                    operation="set",
                    old_value=old_val,
                    new_value=new_val,
                    source_event_id=source_event_id,
                    visibility_scope="player_visible",
                )
                deltas_created += 1
    
    # 4. NPC state changes
    if npc_states_before and npc_states_after:
        for npc_id, npc_after in npc_states_after.items():
            npc_before = npc_states_before.get(npc_id, {})
            for key in ["trust_score", "suspicion_score", "current_location_id"]:
                old_val = npc_before.get(key)
                new_val = npc_after.get(key)
                if old_val != new_val:
                    _create_state_delta(
                        db=db,
                        transaction_id=transaction_id,
                        session_id=session_id,
                        turn_no=turn_no,
                        path=f"npc_state.{npc_id}.{key}",
                        operation="set",
                        old_value=old_val,
                        new_value=new_val,
                        source_event_id=source_event_id,
                        visibility_scope="hidden",
                    )
                    deltas_created += 1
    
    return deltas_created


def _create_llm_stage_result(
    db: Session,
    transaction_id: str,
    session_id: str,
    turn_no: int,
    stage_name: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    prompt_template_id: Optional[str] = None,
    request_payload_ref: Optional[str] = None,
    raw_output_ref: Optional[str] = None,
    parsed_proposal_json: Optional[Dict[str, Any]] = None,
    accepted: Optional[bool] = None,
    fallback_reason: Optional[str] = None,
    validation_errors_json: Optional[List[str]] = None,
    latency_ms: Optional[int] = None,
) -> Optional[str]:
    """
    Create an llm_stage_result record for LLM stage tracking.
    
    Returns the created record ID, or None on failure.
    """
    from ..storage.models import generate_uuid
    
    llm_stage_result_repo = LLMStageResultRepository(db)
    
    try:
        record = llm_stage_result_repo.create({
            "id": generate_uuid(),
            "transaction_id": transaction_id,
            "session_id": session_id,
            "turn_no": turn_no,
            "stage_name": stage_name,
            "provider": provider,
            "model": model,
            "prompt_template_id": prompt_template_id,
            "request_payload_ref": request_payload_ref,
            "raw_output_ref": raw_output_ref,
            "parsed_proposal_json": parsed_proposal_json,
            "accepted": accepted,
            "fallback_reason": fallback_reason,
            "validation_errors_json": validation_errors_json,
            "latency_ms": latency_ms,
            "created_at": datetime.now(),
        })
        return record.id
    except Exception as e:
        # Necessary write inside the managed turn transaction: propagate so the turn
        # rolls back rather than committing with a missing audit row.
        if is_managed(db):
            raise
        logger.warning("Failed to create llm_stage_result: %s", e)
        return None


def _create_validation_report(
    db: Session,
    transaction_id: str,
    session_id: str,
    turn_no: int,
    scope: str,
    target_ref_id: Optional[str] = None,
    is_valid: bool = True,
    errors_json: Optional[List[str]] = None,
    warnings_json: Optional[List[str]] = None,
    buffer: Optional[TurnWriteBuffer] = None,
) -> Optional[str]:
    """
    Create a validation_report record for validation tracking.
    
    Returns the created record ID, or None on failure.

    When ``buffer`` is given (preparation section) the report is only planned and is
    written later, inside the final authoritative transaction; the returned id is the
    pre-allocated one. Without a buffer the write happens right here, exactly as
    before, which is what the final write section keeps doing.
    """
    if buffer is not None:
        return buffer.add_validation_report(
            transaction_id=transaction_id,
            session_id=session_id,
            turn_no=turn_no,
            scope=scope,
            target_ref_id=target_ref_id,
            is_valid=is_valid,
            errors_json=errors_json,
            warnings_json=warnings_json,
        )

    from ..storage.models import generate_uuid
    
    validation_report_repo = ValidationReportRepository(db)
    
    try:
        record = validation_report_repo.create({
            "id": generate_uuid(),
            "transaction_id": transaction_id,
            "session_id": session_id,
            "turn_no": turn_no,
            "scope": scope,
            "target_ref_id": target_ref_id,
            "is_valid": is_valid,
            "errors_json": errors_json,
            "warnings_json": warnings_json,
            "created_at": datetime.now(),
        })
        return record.id
    except Exception as e:
        # Necessary write inside the managed turn transaction: propagate so the turn
        # rolls back rather than committing with a missing audit row.
        if is_managed(db):
            raise
        logger.warning("Failed to create validation_report: %s", e)
        return None


def _validate_proposal(
    db: Session,
    proposal: Any,
    proposal_type: str,
    validation_context: ValidationContext,
    transaction_id: str,
    buffer: Optional[TurnWriteBuffer] = None,
) -> Tuple[bool, List[str], List[str]]:
    """
    Validate a proposal using ValidationContext and Validator.
    
    This function provides unified validation for all proposal types:
    - InputIntentProposal
    - WorldTickProposal
    - SceneEventProposal
    - NPCActionProposal
    - NarrationProposal
    
    Validation results are recorded in validation_reports table.
    
    Args:
        db: Database session
        proposal: The proposal object to validate
        proposal_type: Type of proposal (input_intent, world_tick, scene_event, npc_action, narration)
        validation_context: ValidationContext with state and metadata
        transaction_id: Transaction ID for tracking
        buffer: Optional preparation write buffer. When given (preparation section),
            the validation report is planned instead of written; the final write
            section passes no buffer and keeps writing directly, so its
            validation_reports content and order are unchanged.
        
    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    validator = Validator()
    errors: List[str] = []
    warnings: List[str] = []
    
    # Null check
    if proposal is None:
        errors.append(f"{proposal_type} proposal is None")
        _create_validation_report(
            db=db,
            transaction_id=transaction_id,
            session_id=validation_context.session_id,
            turn_no=validation_context.turn_no,
            scope=f"proposal_{proposal_type}",
            is_valid=False,
            errors_json=errors,
            warnings_json=warnings,
            buffer=buffer,
        )
        return (False, errors, warnings)
    
    # Type-specific validation
    if proposal_type == "input_intent":
        is_valid, type_errors = _validate_input_intent_proposal(proposal, {})
        errors.extend(type_errors)
        
    elif proposal_type == "world_tick":
        is_valid, type_errors = _validate_world_proposal(proposal)
        errors.extend(type_errors)
        
    elif proposal_type == "scene_event":
        is_valid, type_errors = _validate_scene_proposal(proposal, {})
        errors.extend(type_errors)
        
    elif proposal_type == "npc_action":
        is_valid, type_errors = _validate_npc_action(proposal, {})
        errors.extend(type_errors)
        
    elif proposal_type == "narration":
        # Narration validation: check text is non-empty and no forbidden info
        narration_text = getattr(proposal, "text", "") if hasattr(proposal, "text") else ""
        if not narration_text or not narration_text.strip():
            errors.append("narration text is empty")
        # Check for forbidden info leaks
        forbidden_patterns = ["隐藏身份", "真实身份", "hidden_identity", "secret_identity"]
        for pattern in forbidden_patterns:
            if pattern in narration_text:
                errors.append(f"forbidden pattern in narration: {pattern}")
    
    else:
        errors.append(f"unknown proposal type: {proposal_type}")
    
    # Validate state deltas if present
    if hasattr(proposal, "state_deltas") and proposal.state_deltas:
        for delta in proposal.state_deltas:
            if hasattr(delta, "path") and hasattr(delta, "value"):
                delta_result = validator.validate_state_delta(
                    delta_path=delta.path,
                    old_value=None,
                    new_value=delta.value,
                    state=validation_context.canonical_state,
                    context=validation_context,
                )
                if not delta_result.is_valid:
                    errors.extend(delta_result.errors)
                warnings.extend(delta_result.warnings)
    
    # Record validation result
    is_valid_final = len(errors) == 0
    _create_validation_report(
        db=db,
        transaction_id=transaction_id,
        session_id=validation_context.session_id,
        turn_no=validation_context.turn_no,
        scope=f"proposal_{proposal_type}",
        is_valid=is_valid_final,
        errors_json=errors if errors else None,
        warnings_json=warnings if warnings else None,
        buffer=buffer,
    )
    
    return (is_valid_final, errors, warnings)


def _create_llm_stage_results_for_turn(
    db: Session,
    transaction_id: str,
    session_id: str,
    turn_no: int,
    llm_stage_results: List[LLMStageResult],
) -> int:
    """
    Create llm_stage_result records for all LLM stages in a turn.
    
    Creates records for:
    - input_intent stage
    - world stage
    - scene stage
    - npc stage
    - narration stage
    
    Returns the number of records created.
    """
    records_created = 0
    
    for stage_result in llm_stage_results:
        record_id = _create_llm_stage_result(
            db=db,
            transaction_id=transaction_id,
            session_id=session_id,
            turn_no=turn_no,
            stage_name=stage_result.stage_name,
            provider=None,
            model=None,
            prompt_template_id=None,
            request_payload_ref=None,
            raw_output_ref=stage_result.raw_outcome[:500] if stage_result.raw_outcome else None,
            parsed_proposal_json=stage_result.parsed_proposal,
            accepted=stage_result.accepted,
            fallback_reason=stage_result.fallback_reason,
            validation_errors_json=stage_result.validation_errors if stage_result.validation_errors else None,
            latency_ms=int(stage_result.timeout * 1000) if stage_result.timeout else None,
        )
        if record_id:
            records_created += 1
            
            if stage_result.validation_errors:
                _create_validation_report(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    scope=f"llm_stage_{stage_result.stage_name}",
                    target_ref_id=record_id,
                    is_valid=stage_result.accepted,
                    errors_json=stage_result.validation_errors,
                )
    
    return records_created
