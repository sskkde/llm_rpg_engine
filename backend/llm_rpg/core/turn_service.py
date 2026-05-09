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
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Literal
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
from .validator import Validator, ValidationContext
from .validation import (
    MovementValidator,
    QuestValidator,
    NPCKnowledgeValidator,
    NarrationLeakValidator,
)
from ..engines.scene_transition import SceneTransitionResolver
from .perception import PerceptionResolver
from .projections import (
    PlayerVisibleProjectionBuilder,
    NPCVisibleProjectionBuilder,
    NarratorProjectionBuilder,
)
from ..engines.scheduled_event_processor import ScheduledEventProcessor

from ..storage.models import SessionModel, EventLogModel, MemorySummaryModel, MemoryFactModel
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

logger = logging.getLogger(__name__)


# =============================================================================
# LLM Stage Contract
# =============================================================================

# Stage names for LLM-enabled turn stages
LLMStageName = Literal["narration", "scene", "npc", "world", "input_intent"]


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
        }


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
    session_state = session_state_repo.get_by_session(session_id)
    
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
        context["available_locations"] = [
            {"id": loc.id, "name": loc.name, "code": loc.code}
            for loc in all_locations
        ]
    
    player_state = canonical_state.player_state
    context["player_state"] = {
        "name": player_state.name,
        "realm": player_state.realm,
        "location_id": context.get("current_location_id"),
    }
    
    return context


def _build_world_context_for_turn(
    db: Session,
    session_id: str,
    canonical_state: CanonicalState,
    current_location_id: Optional[str] = None,
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
    session_state = session_state_repo.get_by_session(session_id)

    if session_state:
        context["world_time"] = _get_world_time(session_state)
        context["current_location_id"] = current_location_id or session_state.current_location_id
        context["global_flags"] = session_state.global_flags_json or {}
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

    active_quests = _get_active_quests(db, session_id)
    context["active_quests"] = active_quests

    recent_events = _get_recent_events(db, session_id, limit=3)
    context["recent_events"] = recent_events

    return context


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
        if not hasattr(proposal, "target") or not proposal.target:
            errors.append("move intent requires a target")
    
    return (len(errors) == 0, errors)



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
    timeout = 15.0
    
    enabled = _is_input_intent_stage_enabled(db)
    if not enabled:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=False,
            timeout=timeout,
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
        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()
        
        llm_service = _create_llm_service_from_config(
            db,
            provider_config,
            force_mock=use_mock,
        )
        
        pipeline_config = ProposalConfig(
            timeout_seconds=timeout,
            max_tokens=provider_config.get("max_tokens", 200),
            temperature=provider_config.get("temperature", 0.3),
        )
        pipeline = ProposalPipeline(llm_service=llm_service, config=pipeline_config)
        
    except LLMConfigurationError:
        raise
    except Exception as e:
        logger.warning("Failed to configure LLM service for input intent stage: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            accepted=False,
            fallback_reason=f"llm_config_error: {str(e)[:200]}",
        )
    
    try:
        proposal = _run_async_safe(
            pipeline.generate_input_intent(
                raw_input=raw_input,
                prompt_template_id="input_intent_v1",
                session_id=session_id,
                turn_no=turn_no,
                context=input_context,
            )
        )
        
        is_valid, validation_errors = _validate_input_intent_proposal(proposal, input_context)
        
        if not is_valid:
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=timeout,
                accepted=False,
                fallback_reason=f"validation_failed: {', '.join(validation_errors[:3])}",
                raw_outcome=str(proposal)[:500] if proposal else None,
                validation_errors=validation_errors,
            )
        
        is_fallback = getattr(proposal, "is_fallback", False)
        if is_fallback:
            fallback_reason = "llm_proposal_fallback"
            audit = getattr(proposal, "audit", None)
            if audit and hasattr(audit, "fallback_reason") and audit.fallback_reason:
                fallback_reason = f"llm_proposal_fallback: {audit.fallback_reason[:200]}"
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=timeout,
                accepted=False,
                fallback_reason=fallback_reason,
                raw_outcome=str(proposal)[:500] if proposal else None,
            )
        
        parsed_proposal: Dict[str, Any] = {
            "intent_type": getattr(proposal, "intent_type", "unknown"),
            "target": getattr(proposal, "target", None),
            "target_type": getattr(proposal, "target_type", None),
            "risk_level": getattr(proposal, "risk_level", "low"),
            "raw_tokens": getattr(proposal, "raw_tokens", []),
            "confidence": getattr(proposal, "confidence", 0.5),
            "parameters": getattr(proposal, "parameters", {}),
        }
        
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            raw_outcome=str(proposal)[:500],
            parsed_proposal=parsed_proposal,
            accepted=True,
        )
        
    except asyncio.TimeoutError:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            accepted=False,
            fallback_reason="timeout",
        )
    except Exception as e:
        logger.warning("LLM input intent stage failed: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
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
    timeout = 30.0

    enabled = _is_world_stage_enabled(db)
    if not enabled:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=False,
            timeout=timeout,
            accepted=False,
            fallback_reason="world_stage_disabled",
        )

    world_context = _build_world_context_for_turn(
        db=db,
        session_id=session_id,
        canonical_state=canonical_state,
        current_location_id=current_location_id,
    )

    try:
        from ..services.settings import SystemSettingsService
        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()

        llm_service = _create_llm_service_from_config(
            db,
            provider_config,
            force_mock=use_mock,
        )

        pipeline_config = ProposalConfig(
            timeout_seconds=timeout,
            max_tokens=provider_config.get("max_tokens", 500),
            temperature=provider_config.get("temperature", 0.8),
        )
        pipeline = ProposalPipeline(llm_service=llm_service, config=pipeline_config)

    except LLMConfigurationError:
        raise
    except Exception as e:
        logger.warning("Failed to configure LLM service for world stage: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            accepted=False,
            fallback_reason=f"llm_config_error: {str(e)[:200]}",
        )

    try:
        proposal = _run_async_safe(
            pipeline.generate_world_tick(
                world_context=world_context,
                prompt_template_id="world_tick_v1",
                session_id=session_id,
                turn_no=turn_no,
            )
        )

        is_valid, validation_errors = _validate_world_proposal(proposal)

        if not is_valid:
            if transaction_id:
                _create_validation_report(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    scope="proposal_world_tick",
                    target_ref_id=None,
                    is_valid=False,
                    errors_json=validation_errors,
                )
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=timeout,
                accepted=False,
                fallback_reason=f"validation_failed: {', '.join(validation_errors[:3])}",
                raw_outcome=str(proposal)[:500] if proposal else None,
                validation_errors=validation_errors,
            )

        is_fallback = getattr(proposal, "is_fallback", False)
        if is_fallback:
            fallback_reason = "llm_proposal_fallback"
            audit = getattr(proposal, "audit", None)
            if audit and hasattr(audit, "fallback_reason") and audit.fallback_reason:
                fallback_reason = f"llm_proposal_fallback: {audit.fallback_reason[:200]}"
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=timeout,
                accepted=False,
                fallback_reason=fallback_reason,
                raw_outcome=str(proposal)[:500] if proposal else None,
            )

        parsed_proposal: Dict[str, Any] = {
            "time_description": getattr(proposal, "time_description", ""),
            "candidate_events": [
                {
                    "event_type": getattr(e, "event_type", "unknown"),
                    "description": getattr(e, "description", ""),
                    "effects": getattr(e, "effects", {}),
                    "importance": getattr(e, "importance", 0.5),
                    "visibility": getattr(e, "visibility", "player_visible"),
                }
                for e in proposal.candidate_events
            ],
            "state_deltas": [
                {
                    "path": getattr(d, "path", ""),
                    "operation": getattr(d, "operation", "set"),
                    "value": getattr(d, "value", None),
                    "reason": getattr(d, "reason", ""),
                }
                for d in proposal.state_deltas
            ],
            "confidence": getattr(proposal, "confidence", 0.5),
        }

        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            raw_outcome=str(proposal)[:500],
            parsed_proposal=parsed_proposal,
            accepted=True,
        )

    except asyncio.TimeoutError:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            accepted=False,
            fallback_reason="timeout",
        )
    except Exception as e:
        logger.warning("LLM world stage failed: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            accepted=False,
            fallback_reason=f"error: {str(e)[:200]}",
        )


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
    session_state = session_state_repo.get_by_session(session_id)
    
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
    
    active_quests = _get_active_quests(db, session_id)
    context["active_quests"] = active_quests
    
    game_event_repo = GameEventRepository(db)
    recent_event_models = game_event_repo.get_by_session(session_id, limit=10)
    
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
            recent_events = _get_recent_events(db, session_id, limit=5)
            context["recent_events"] = recent_events
    else:
        recent_events = _get_recent_events(db, session_id, limit=5)
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
    
    return context


def _get_visible_npcs(
    db: Session,
    session_id: str,
    location_id: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Get visible NPCs at a location (public identity only).
    
    CRITICAL: Never includes hidden_identity from NPCTemplateModel.
    Only includes public_identity, name, and role_type.
    """
    if not location_id:
        return []
    
    npc_state_repo = SessionNPCStateRepository(db)
    npc_states = npc_state_repo.get_by_session(session_id)
    
    visible_npcs = []
    npc_template_repo = NPCTemplateRepository(db)
    
    for npc_state in npc_states:
        if npc_state.current_location_id == location_id:
            npc_template = npc_template_repo.get_by_id(npc_state.npc_template_id)
            if npc_template:
                visible_npcs.append({
                    "name": npc_template.name,
                    "public_identity": npc_template.public_identity,
                    "role_type": npc_template.role_type,
                    "mood": npc_state.status_flags.get("mood", "neutral") if npc_state.status_flags else "neutral",
                })
    
    return visible_npcs


def _get_active_quests(db: Session, session_id: str) -> List[Dict[str, Any]]:
    """Get active quests for the session."""
    quest_state_repo = SessionQuestStateRepository(db)
    quest_states = quest_state_repo.get_by_session(session_id)
    
    active_quests = []
    quest_template_repo = QuestTemplateRepository(db)
    
    for qs in quest_states:
        if qs.status == "active":
            quest_template = quest_template_repo.get_by_id(qs.quest_template_id)
            if quest_template:
                active_quests.append({
                    "name": quest_template.name,
                    "current_step_no": qs.current_step_no,
                    "status": qs.status,
                })
    
    return active_quests


def _get_recent_events(
    db: Session,
    session_id: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Get recent event log entries for narration context."""
    event_log_repo = EventLogRepository(db)
    recent = event_log_repo.get_recent(session_id, limit=limit)
    
    events = []
    for event in reversed(recent):
        events.append({
            "turn_no": event.turn_no,
            "event_type": event.event_type,
            "narrative_text": event.narrative_text,
            "input_text": event.input_text,
        })
    
    return events


def _build_scene_context(
    db: Session,
    session_id: str,
    canonical_state: CanonicalState,
    player_input: str,
    action_type: str,
    movement_result: Optional[MovementResult] = None,
    state_deltas: Optional[Dict[str, Any]] = None,
    current_location_id: Optional[str] = None,
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
    session_state = session_state_repo.get_by_session(session_id)
    
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
    
    active_quests = _get_active_quests(db, session_id)
    context["active_quests"] = active_quests
    
    recent_events = _get_recent_events(db, session_id, limit=5)
    context["recent_events"] = recent_events
    
    player_state = canonical_state.player_state
    context["player_state"] = {
        "name": player_state.name,
        "realm": player_state.realm,
        "spiritual_power": player_state.spiritual_power,
        "location_id": current_location_id,
    }
    
    return context


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
            "name": npc_template.name,
            "public_identity": npc_template.public_identity,
            "role_type": npc_template.role_type,
            "personality": npc_template.personality,
            "goals": npc_template.goals or [],
            "trust_score": npc_state.trust_score,
            "suspicion_score": npc_state.suspicion_score,
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
) -> Dict[str, Any]:
    """
    Build NPC context for LLM NPC decision generation.
    
    CRITICAL: Only includes player-visible facts. No hidden NPC info.
    
    Context includes:
    - NPC public identity, personality, goals
    - Relationship scores (trust, suspicion)
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
    """
    from ..models.events import GameEvent, EventType
    from ..models.perspectives import NPCPerspective
    
    npc_template_repo = NPCTemplateRepository(db)
    npc_template = npc_template_repo.get_by_id(npc_template_id)
    
    if not npc_template:
        return {}
    
    npc_state_repo = SessionNPCStateRepository(db)
    npc_states = npc_state_repo.get_by_session(session_id)
    npc_state = None
    for ns in npc_states:
        if ns.id == npc_id:
            npc_state = ns
            break
    
    # Determine NPC location
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
        context["trust_score"] = npc_state.trust_score
        context["suspicion_score"] = npc_state.suspicion_score
        status_flags = npc_state.status_flags or {}
        context["mood"] = status_flags.get("mood", "neutral")
        context["current_location_id"] = npc_state.current_location_id
    
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
    recent_event_models = game_event_repo.get_by_session(session_id, limit=10)
    
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
            recent_events = _get_recent_events(db, session_id, limit=3)
            context["recent_events"] = recent_events
    else:
        # Fallback to simple recent events if no events in DB
        recent_events = _get_recent_events(db, session_id, limit=3)
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
    timeout = 30.0
    
    enabled = _is_npc_stage_enabled(db)
    if not enabled:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=False,
            timeout=timeout,
            accepted=False,
            fallback_reason="npc_stage_disabled",
        )
    
    active_npcs = _get_active_npcs_at_location(db, session_id, current_location_id)
    
    if not active_npcs:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            accepted=True,
            parsed_proposal={"npc_reactions": []},
        )
    
    try:
        from ..services.settings import SystemSettingsService
        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()
        
        llm_service = _create_llm_service_from_config(
            db,
            provider_config,
            force_mock=use_mock,
        )
        
        pipeline_config = ProposalConfig(
            timeout_seconds=timeout,
            max_tokens=provider_config.get("max_tokens", 500),
            temperature=provider_config.get("temperature", 0.8),
        )
        pipeline = ProposalPipeline(llm_service=llm_service, config=pipeline_config)
        
    except LLMConfigurationError:
        raise
    except Exception as e:
        logger.warning("Failed to configure LLM service for NPC stage: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            accepted=False,
            fallback_reason=f"llm_config_error: {str(e)[:200]}",
        )
    
    npc_reactions: List[Dict[str, Any]] = []
    working_recent_actions = list(recent_npc_actions) if recent_npc_actions else []
    
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
        )
        
        if not npc_context:
            continue
        
        try:
            proposal = _run_async_safe(
                pipeline.generate_npc_action(
                    npc_id=npc_id,
                    npc_context=npc_context,
                    prompt_template_id="npc_action_v1",
                    session_id=session_id,
                    turn_no=turn_no,
                )
            )
            
            is_valid, validation_errors = _validate_npc_action(proposal, npc_context)
            
            if not is_valid:
                npc_reactions.append({
                    "npc_id": npc_id,
                    "npc_name": npc_name,
                    "accepted": False,
                    "fallback_reason": f"validation_failed: {', '.join(validation_errors[:3])}",
                    "action_type": "idle",
                    "summary": f"{npc_name}等待着",
                })
                continue
            
            is_fallback = getattr(proposal, "is_fallback", False)
            if is_fallback:
                fallback_reason = "llm_proposal_fallback"
                audit = getattr(proposal, "audit", None)
                if audit and hasattr(audit, "fallback_reason") and audit.fallback_reason:
                    fallback_reason = f"llm_proposal_fallback: {audit.fallback_reason[:200]}"
                
                npc_reactions.append({
                    "npc_id": npc_id,
                    "npc_name": npc_name,
                    "accepted": False,
                    "fallback_reason": fallback_reason,
                    "action_type": getattr(proposal, "action_type", "idle"),
                    "summary": getattr(proposal, "summary", f"{npc_name}等待着"),
                })
                continue
            
            visibility = getattr(proposal, "visibility", "player_visible")
            visible_to_player = visibility == "player_visible"
            
            reaction = {
                "npc_id": npc_id,
                "npc_name": npc_name,
                "accepted": True,
                "action_type": proposal.action_type,
                "summary": proposal.summary,
                "visible_to_player": visible_to_player,
                "visible_motivation": getattr(proposal, "visible_motivation", ""),
            }
            
            if visible_to_player:
                working_recent_actions.append({
                    "npc_name": npc_name,
                    "summary": proposal.summary,
                })
            
            npc_reactions.append(reaction)
            
        except asyncio.TimeoutError:
            npc_reactions.append({
                "npc_id": npc_id,
                "npc_name": npc_name,
                "accepted": False,
                "fallback_reason": "timeout",
                "action_type": "idle",
                "summary": f"{npc_name}等待着",
            })
        except Exception as e:
            logger.warning("NPC action generation failed for %s: %s", npc_id, e)
            npc_reactions.append({
                "npc_id": npc_id,
                "npc_name": npc_name,
                "accepted": False,
                "fallback_reason": f"error: {str(e)[:200]}",
                "action_type": "idle",
                "summary": f"{npc_name}等待着",
            })
    
    accepted_count = sum(1 for r in npc_reactions if r.get("accepted", False))
    
    return LLMStageResult(
        stage_name=stage_name,
        enabled=True,
        timeout=timeout,
        raw_outcome=str(npc_reactions)[:500],
        parsed_proposal={"npc_reactions": npc_reactions},
        accepted=accepted_count > 0,
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
        
    Returns:
        List of LLMStageResult objects, one per stage executed
    """
    results: List[LLMStageResult] = []
    
    world_result = _execute_world_stage(
        db=db,
        session_id=session_id,
        turn_no=turn_no,
        canonical_state=canonical_state,
        current_location_id=current_location_id,
        use_mock=use_mock,
        transaction_id=transaction_id,
    )
    results.append(world_result)
    
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
    )
    results.append(scene_result)
    
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
    )
    results.append(npc_result)
    
    npc_reactions_for_narration: List[Dict[str, Any]] = []
    if npc_result.accepted and npc_result.parsed_proposal:
        npc_reactions_for_narration = npc_result.parsed_proposal.get("npc_reactions", [])
    
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
        npc_reactions=npc_reactions_for_narration,
        use_mock=use_mock,
    )
    results.append(narration_result)
    
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
    timeout = 30.0
    
    enabled = _is_narration_stage_enabled(db)
    if not enabled:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=False,
            timeout=timeout,
            accepted=False,
            fallback_reason="narration_stage_disabled",
        )
    
    narration_context = _build_narration_context(
        db=db,
        session_id=session_id,
        canonical_state=canonical_state,
        player_input=player_input,
        action_type=action_type,
        movement_result=movement_result,
        state_deltas=state_deltas,
        current_location_id=current_location_id,
    )
    
    # Expose player-visible NPC reactions to narration context
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
        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()
        
        llm_service = _create_llm_service_from_config(
            db,
            provider_config,
            force_mock=use_mock,
        )
        
        pipeline_config = ProposalConfig(
            timeout_seconds=timeout,
            max_tokens=provider_config.get("max_tokens", 500),
            temperature=provider_config.get("temperature", 0.8),
        )
        pipeline = ProposalPipeline(llm_service=llm_service, config=pipeline_config)
        
    except LLMConfigurationError:
        raise
    except Exception as e:
        logger.warning("Failed to configure LLM service for narration: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            accepted=False,
            fallback_reason=f"llm_config_error: {str(e)[:200]}",
        )
    
    try:
        proposal = _run_async_safe(
            pipeline.generate_narration(
                visible_context=narration_context,
                prompt_template_id="narration_v1",
                session_id=session_id,
                turn_no=turn_no,
            )
        )
        
        narration_text = proposal.text if hasattr(proposal, "text") else ""
        
        if not narration_text or not narration_text.strip():
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=timeout,
                accepted=False,
                fallback_reason="empty_narration_text",
                raw_outcome=str(proposal)[:500] if proposal else None,
            )
        
        forbidden_leaks = _check_forbidden_info_leaks(narration_context, narration_text)
        if forbidden_leaks:
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=timeout,
                accepted=False,
                fallback_reason=f"forbidden_info_leak: {', '.join(forbidden_leaks[:3])}",
                raw_outcome=narration_text[:500],
                validation_errors=[f"Forbidden info detected: {info}" for info in forbidden_leaks],
            )
        
        is_fallback = getattr(proposal, "is_fallback", False)
        if is_fallback:
            fallback_reason = "llm_proposal_fallback"
            audit = getattr(proposal, "audit", None)
            if audit and hasattr(audit, "fallback_reason") and audit.fallback_reason:
                fallback_reason = f"llm_proposal_fallback: {audit.fallback_reason[:200]}"
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=timeout,
                accepted=False,
                fallback_reason=fallback_reason,
                raw_outcome=narration_text[:500],
            )
        
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            raw_outcome=narration_text[:500],
            parsed_proposal={"text": narration_text},
            accepted=True,
        )
        
    except asyncio.TimeoutError:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            accepted=False,
            fallback_reason="timeout",
        )
    except Exception as e:
        logger.warning("LLM narration stage failed: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
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
) -> LLMStageResult:
    """
    Execute the scene LLM stage.
    
    1. Check if enabled via feature flag
    2. Build scene context from committed state
    3. Call ProposalPipeline.generate_scene_event()
    4. Validate output
    5. Return LLMStageResult with accepted/rejected status
    
    The scene stage generates candidate scene events and recommended actions.
    It does NOT mutate any state - proposals are candidates only.
    """
    from ..llm.proposal_pipeline import ProposalPipeline, ProposalConfig
    
    stage_name: LLMStageName = "scene"
    timeout = 30.0
    
    enabled = _is_scene_stage_enabled(db)
    if not enabled:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=False,
            timeout=timeout,
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
    )
    
    try:
        from ..services.settings import SystemSettingsService
        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()
        
        llm_service = _create_llm_service_from_config(
            db,
            provider_config,
            force_mock=use_mock,
        )
        
        pipeline_config = ProposalConfig(
            timeout_seconds=timeout,
            max_tokens=provider_config.get("max_tokens", 500),
            temperature=provider_config.get("temperature", 0.8),
        )
        pipeline = ProposalPipeline(llm_service=llm_service, config=pipeline_config)
        
    except LLMConfigurationError:
        raise
    except Exception as e:
        logger.warning("Failed to configure LLM service for scene stage: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            accepted=False,
            fallback_reason=f"llm_config_error: {str(e)[:200]}",
        )
    
    try:
        scene_id = current_location_id or "unknown"
        
        proposal = _run_async_safe(
            pipeline.generate_scene_event(
                scene_id=scene_id,
                scene_context=scene_context,
                prompt_template_id="scene_event_v1",
                session_id=session_id,
                turn_no=turn_no,
            )
        )
        
        is_valid, validation_errors = _validate_scene_proposal(proposal, scene_context)
        
        if not is_valid:
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=timeout,
                accepted=False,
                fallback_reason=f"validation_failed: {', '.join(validation_errors[:3])}",
                raw_outcome=str(proposal)[:500] if proposal else None,
                validation_errors=validation_errors,
            )
        
        is_fallback = getattr(proposal, "is_fallback", False)
        if is_fallback:
            fallback_reason = "llm_proposal_fallback"
            audit = getattr(proposal, "audit", None)
            if audit and hasattr(audit, "fallback_reason") and audit.fallback_reason:
                fallback_reason = f"llm_proposal_fallback: {audit.fallback_reason[:200]}"
            return LLMStageResult(
                stage_name=stage_name,
                enabled=True,
                timeout=timeout,
                accepted=False,
                fallback_reason=fallback_reason,
                raw_outcome=str(proposal)[:500],
            )
        
        parsed_proposal: Dict[str, Any] = {
            "scene_id": proposal.scene_id,
            "scene_name": getattr(proposal, "scene_name", None),
            "candidate_events": [
                {
                    "event_type": e.event_type,
                    "description": e.description,
                    "importance": getattr(e, "importance", 0.5),
                }
                for e in proposal.candidate_events
            ],
        }
        
        if hasattr(proposal, "recommended_actions") and proposal.recommended_actions:
            parsed_proposal["recommended_actions"] = proposal.recommended_actions[:4]
        
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            raw_outcome=str(proposal)[:500],
            parsed_proposal=parsed_proposal,
            accepted=True,
        )
        
    except asyncio.TimeoutError:
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
            accepted=False,
            fallback_reason="timeout",
        )
    except Exception as e:
        logger.warning("LLM scene stage failed: %s", e)
        return LLMStageResult(
            stage_name=stage_name,
            enabled=True,
            timeout=timeout,
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


def execute_turn_service(
    db: Session,
    session_id: str,
    player_input: str,
    idempotency_key: Optional[str] = None,
    use_mock: bool = False,
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

    # Preflight: Validate explicit LLM provider config before any DB writes.
    # Mock-only call paths intentionally bypass global provider settings.
    if not use_mock:
        _validate_explicit_llm_config(db)
    
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
    
    # Step 4b: Create turn_transaction record (status=pending)
    turn_transaction_repo = TurnTransactionRepository(db)
    world_time_before_str = _format_world_time(_get_world_time(None))
    turn_transaction = turn_transaction_repo.create({
        "session_id": session_id,
        "turn_no": turn_no,
        "idempotency_key": idempotency_key or f"auto_{session_id}_{turn_no}",
        "status": "pending",
        "player_input": player_input,
        "world_time_before": world_time_before_str,
        "started_at": datetime.now(),
    })
    transaction_id = turn_transaction.id
    
    try:
        # Get current location before input intent stage
        session_state_repo = SessionStateRepository(db)
        session_state = session_state_repo.get_by_session(session_id)
        current_location_id = session_state.current_location_id if session_state else None
        
        # Create ValidationContext for this turn
        validation_context = ValidationContext.create(
            db=db,
            session_id=session_id,
            turn_no=turn_no,
            canonical_state=canonical_state,
        )
        
        # Step 5: Execute input intent LLM stage (before deterministic parsing)
        input_intent_result = _execute_input_intent_stage(
            db=db,
            session_id=session_id,
            turn_no=turn_no,
            canonical_state=canonical_state,
            raw_input=player_input,
            current_location_id=current_location_id,
            use_mock=use_mock,
        )
        
        # Validate InputIntentProposal before using it
        if input_intent_result.accepted and input_intent_result.parsed_proposal:
            from ..models.proposals import InputIntentProposal
            try:
                intent_proposal = InputIntentProposal(
                    intent_type=input_intent_result.parsed_proposal.get("intent_type", "unknown"),
                    target=input_intent_result.parsed_proposal.get("target"),
                    target_type=input_intent_result.parsed_proposal.get("target_type"),
                    risk_level=input_intent_result.parsed_proposal.get("risk_level", "low"),
                    confidence=input_intent_result.parsed_proposal.get("confidence", 0.5),
                    audit=type('obj', (object,), {
                        'proposal_type': 'input_intent',
                        'source_engine': 'input_engine',
                    })(),
                )
                is_valid_intent, intent_errors, intent_warnings = _validate_proposal(
                    db=db,
                    proposal=intent_proposal,
                    proposal_type="input_intent",
                    validation_context=validation_context,
                    transaction_id=transaction_id,
                )
                if not is_valid_intent:
                    logger.warning("InputIntentProposal validation failed: %s", intent_errors)
                    input_intent_result = LLMStageResult(
                        stage_name="input_intent",
                        enabled=input_intent_result.enabled,
                        timeout=input_intent_result.timeout,
                        accepted=False,
                        fallback_reason=f"validation_failed: {', '.join(intent_errors[:3])}",
                        validation_errors=intent_errors,
                    )
            except Exception as e:
                logger.warning("Failed to validate InputIntentProposal: %s", e)
        
        # Step 6: Parse player input and determine action type
        # Use LLM intent if accepted, otherwise fall back to deterministic parser
        action_type = "action"
        target = None
        input_intent_metadata: Optional[Dict[str, Any]] = None
        input_intent_fallback_reason: Optional[str] = None
        
        if input_intent_result.accepted and input_intent_result.parsed_proposal:
            parsed_intent = input_intent_result.parsed_proposal
            action_type = parsed_intent.get("intent_type", "action")
            target = parsed_intent.get("target")
            input_intent_metadata = parsed_intent
        else:
            # Fallback to deterministic parser
            action_type, target = _parse_player_input(player_input)
            input_intent_fallback_reason = input_intent_result.fallback_reason
        
        # Step 7: Execute action
        movement_result: Optional[MovementResult] = None
        state_deltas: Dict[str, Any] = {}
        
        if action_type == "move" and target:
            from_location_id = current_location_id or ""
            
            # Resolve target location code for validation
            from .movement_handler import _resolve_location_code
            resolved_target_code = _resolve_location_code(target)
            target_location_id = resolved_target_code or target
            
            # Step 7a: Check scene transition blocked paths first
            scene_transition_resolver = SceneTransitionResolver()
            game_state_for_transition = {
                "player_location": from_location_id,
                "current_turn": turn_no,
            }
            can_move, blocked_reason = scene_transition_resolver.can_move_to(
                from_location=from_location_id,
                to_location=target_location_id,
                game_state=game_state_for_transition,
            )
            
            if not can_move:
                # Scene transition blocked - record validation report and game event
                _create_validation_report(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    scope="scene_transition_validation",
                    is_valid=False,
                    errors_json=[blocked_reason or "Movement blocked by scene"],
                    warnings_json=[],
                )
                _create_game_event(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    event_type="movement_blocked",
                    actor_id="player",
                    target_ids=[target_location_id],
                    visibility_scope="player_visible",
                    public_payload={
                        "from_location_id": from_location_id,
                        "to_location_id": target_location_id,
                        "blocked_reason": blocked_reason,
                    },
                )
                logger.warning("Scene transition blocked: %s", blocked_reason)
                movement_result = MovementResult(
                    success=False,
                    blocked_reason=blocked_reason or "Movement blocked by scene",
                    previous_location_id=from_location_id,
                )
            else:
                # Step 7b: Validate movement with MovementValidator
                movement_validator = MovementValidator()
                movement_validation = movement_validator.validate_movement(
                    actor_id="player",
                    from_location_id=from_location_id,
                    to_location_id=target_location_id,
                    state=canonical_state,
                    context=validation_context,
                )
                
                if not movement_validation.is_valid:
                    # Record validation failure
                    _create_validation_report(
                        db=db,
                        transaction_id=transaction_id,
                        session_id=session_id,
                        turn_no=turn_no,
                        scope="movement_validation",
                        is_valid=False,
                        errors_json=movement_validation.errors,
                        warnings_json=movement_validation.warnings,
                    )
                    logger.warning("Movement validation failed: %s", movement_validation.errors)
                    movement_result = MovementResult(
                        success=False,
                        blocked_reason=movement_validation.errors[0] if movement_validation.errors else "Movement validation failed",
                        previous_location_id=from_location_id,
                    )
                else:
                    # Handle movement
                    movement_result = handle_movement(db, session_id, target)
            
            if movement_result.success:
                state_deltas["location_id"] = movement_result.new_location_id
            else:
                # Blocked movement - no state mutation
                state_deltas["blocked_reason"] = movement_result.blocked_reason
        
        # Step 8: Check quest progression
        if movement_result and movement_result.success:
            # Validate quest progression before checking
            quest_validator = QuestValidator()
            quest_validation = quest_validator.validate_quest_progress(
                quest_id="current",
                new_stage=0,  # Placeholder - actual stage determined by quest system
                state=canonical_state,
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
        
        # Step 9: Generate recommended actions (deterministic fallback)
        session_state = session_state_repo.get_by_session(session_id)
        
        current_location_id = None
        if session_state:
            current_location_id = session_state.current_location_id
        
        if movement_result and movement_result.success:
            current_location_id = movement_result.new_location_id
        
        deterministic_recommended_actions = generate_recommended_actions(
            db=db,
            session_id=session_id,
            location_id=current_location_id,
        )
        
        # Step 10: Build template narration (fallback-safe placeholder)
        narration = _build_narration(
            player_input=player_input,
            action_type=action_type,
            movement_result=movement_result,
            canonical_state=canonical_state,
        )
        
        # Step 11: Advance world time for the committed turn
        world_time_before = _get_world_time(session_state)
        world_time = _advance_world_time(world_time_before)
        
        # Step 11b: Process scheduled events with new world time
        scheduled_event_results: list[dict[str, Any]] = []
        try:
            from ..models.events import WorldTime
            world_time_obj = WorldTime(
                calendar=world_time.get("calendar", "修仙历"),
                season=world_time.get("season", "春"),
                day=_parse_world_day(world_time.get("day", "第1日")),
                period=world_time.get("period", "辰时"),
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
            logger.warning(
                "ScheduledEventProcessor failed for session %s turn %d: %s",
                session_id,
                turn_no,
                e,
            )
        
        # Step 12: Get player state
        player_state = _get_player_state(canonical_state, current_location_id)
        
        # Step 13: Commit turn to DB with template narration (durable commit first)
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
        except TurnAllocationError as e:
            raise TurnServiceError(
                f"Failed to commit turn: {str(e)}",
                session_id=session_id,
                turn_no=turn_no,
            )
        
        # Step 13b: Create game_event for player_input
        _create_game_event(
            db=db,
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
        
        # Step 14: Execute LLM stages (scene before narration)
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
        )
        
        # Step 14b: Validate all proposals before committing
        from ..models.proposals import (
            WorldTickProposal, SceneEventProposal, NPCActionProposal, NarrationProposal,
            CandidateEvent, StateDeltaCandidate, ProposalAuditMetadata, ProposalType, ProposalSource,
        )
        
        for stage_result in llm_stage_results:
            if not stage_result.accepted or not stage_result.parsed_proposal:
                continue
            
            if stage_result.stage_name == "world":
                try:
                    candidate_events = [
                        CandidateEvent(
                            event_type=e.get("event_type", "unknown"),
                            description=e.get("description", ""),
                            effects=e.get("effects", {}),
                            importance=e.get("importance", 0.5),
                        )
                        for e in stage_result.parsed_proposal.get("candidate_events", [])
                    ]
                    state_deltas_list = [
                        StateDeltaCandidate(
                            path=d.get("path", ""),
                            operation=d.get("operation", "set"),
                            value=d.get("value"),
                        )
                        for d in stage_result.parsed_proposal.get("state_deltas", [])
                    ]
                    world_proposal = WorldTickProposal(
                        time_description=stage_result.parsed_proposal.get("time_description", ""),
                        candidate_events=candidate_events,
                        state_deltas=state_deltas_list,
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
                        logger.warning("WorldTickProposal validation failed: %s", errors)
                        stage_result.accepted = False
                        stage_result.validation_errors = errors
                        stage_result.fallback_reason = f"validation_failed: {', '.join(errors[:3])}"
                except Exception as e:
                    logger.warning("Failed to validate WorldTickProposal: %s", e)
                    
            elif stage_result.stage_name == "scene":
                try:
                    scene_id = stage_result.parsed_proposal.get("scene_id", "unknown")
                    candidate_events = [
                        CandidateEvent(
                            event_type=e.get("event_type", "unknown"),
                            description=e.get("description", ""),
                        )
                        for e in stage_result.parsed_proposal.get("candidate_events", [])
                    ]
                    scene_proposal = SceneEventProposal(
                        scene_id=scene_id,
                        scene_name=stage_result.parsed_proposal.get("scene_name"),
                        candidate_events=candidate_events,
                        recommended_actions=stage_result.parsed_proposal.get("recommended_actions", []),
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
                        logger.warning("SceneEventProposal validation failed: %s", errors)
                        stage_result.accepted = False
                        stage_result.validation_errors = errors
                        stage_result.fallback_reason = f"validation_failed: {', '.join(errors[:3])}"
                except Exception as e:
                    logger.warning("Failed to validate SceneEventProposal: %s", e)
                    
            elif stage_result.stage_name == "npc":
                npc_reactions = stage_result.parsed_proposal.get("npc_reactions", [])
                npc_knowledge_validator = NPCKnowledgeValidator()
                for reaction in npc_reactions:
                    if not reaction.get("accepted"):
                        continue
                    try:
                        npc_proposal = NPCActionProposal(
                            npc_id=reaction.get("npc_id", "unknown"),
                            npc_name=reaction.get("npc_name"),
                            action_type=reaction.get("action_type", "idle"),
                            summary=reaction.get("summary", ""),
                            visible_motivation=reaction.get("visible_motivation", ""),
                            audit=ProposalAuditMetadata(
                                proposal_type=ProposalType.NPC_ACTION,
                                source_engine=ProposalSource.NPC_ENGINE,
                            ),
                        )
                        
                        npc_id = reaction.get("npc_id", "unknown")
                        knowledge = "\n".join(
                            part for part in [
                                reaction.get("summary", ""),
                                reaction.get("visible_motivation", ""),
                            ]
                            if part
                        )
                        npc_knowledge_validation = npc_knowledge_validator.validate_knowledge(
                            npc_id=npc_id,
                            knowledge=knowledge,
                            state=canonical_state,
                            context=validation_context,
                        )
                        
                        if not npc_knowledge_validation.is_valid:
                            _create_validation_report(
                                db=db,
                                transaction_id=transaction_id,
                                session_id=session_id,
                                turn_no=turn_no,
                                scope="npc_knowledge_validation",
                                target_ref_id=npc_id,
                                is_valid=False,
                                errors_json=npc_knowledge_validation.errors,
                                warnings_json=npc_knowledge_validation.warnings,
                            )
                            logger.warning("NPC knowledge validation failed for %s: %s", npc_id, npc_knowledge_validation.errors)
                            reaction["accepted"] = False
                            reaction["fallback_reason"] = f"npc_knowledge_validation_failed: {', '.join(npc_knowledge_validation.errors[:3])}"
                            continue
                        
                        is_valid, errors, warnings = _validate_proposal(
                            db=db,
                            proposal=npc_proposal,
                            proposal_type="npc_action",
                            validation_context=validation_context,
                            transaction_id=transaction_id,
                        )
                        if not is_valid:
                            logger.warning("NPCActionProposal validation failed for %s: %s", reaction.get("npc_id"), errors)
                            reaction["accepted"] = False
                            reaction["fallback_reason"] = f"validation_failed: {', '.join(errors[:3])}"
                    except Exception as e:
                        logger.warning("Failed to validate NPCActionProposal: %s", e)
                        
            elif stage_result.stage_name == "narration":
                narration_leak_validator = NarrationLeakValidator()
                try:
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
                        logger.warning("NarrationProposal validation failed: %s", errors)
                        stage_result.accepted = False
                        stage_result.validation_errors = errors
                        stage_result.fallback_reason = f"validation_failed: {', '.join(errors[:3])}"
                except Exception as e:
                    logger.warning("Failed to validate NarrationProposal: %s", e)
        
        # Step 15: Determine final recommended actions, scene summary, NPC reactions, and world progression
        final_recommended_actions = deterministic_recommended_actions
        scene_event_summary: Optional[Dict[str, Any]] = None
        scene_fallback_reason: Optional[str] = None
        npc_reactions_for_json: List[Dict[str, Any]] = []
        npc_fallback_reason: Optional[str] = None
        world_progression: Optional[Dict[str, Any]] = None
        world_fallback_reason: Optional[str] = None
        
        for stage_result in llm_stage_results:
            if stage_result.stage_name == "world":
                if stage_result.accepted and stage_result.parsed_proposal:
                    world_progression = stage_result.parsed_proposal
                else:
                    world_fallback_reason = stage_result.fallback_reason
            elif stage_result.stage_name == "scene":
                if stage_result.accepted and stage_result.parsed_proposal:
                    scene_recommended = stage_result.parsed_proposal.get("recommended_actions", [])
                    if scene_recommended and isinstance(scene_recommended, list):
                        final_recommended_actions = scene_recommended[:4]
                    scene_event_summary = {
                        "scene_id": stage_result.parsed_proposal.get("scene_id"),
                        "scene_name": stage_result.parsed_proposal.get("scene_name"),
                        "candidate_events": stage_result.parsed_proposal.get("candidate_events", []),
                    }
                else:
                    scene_fallback_reason = stage_result.fallback_reason
            elif stage_result.stage_name == "npc":
                if stage_result.accepted and stage_result.parsed_proposal:
                    npc_reactions_for_json = stage_result.parsed_proposal.get("npc_reactions", [])
                else:
                    npc_fallback_reason = stage_result.fallback_reason
        
        # Step 16: If LLM narration accepted, update EventLogModel.narrative_text
        final_narration = narration
        for stage_result in llm_stage_results:
            if stage_result.stage_name == "narration" and stage_result.accepted:
                if stage_result.parsed_proposal and "text" in stage_result.parsed_proposal:
                    final_narration = stage_result.parsed_proposal["text"]
                    event_log_repo = EventLogRepository(db)
                    event_log_repo.update(event.id, {"narrative_text": final_narration})
        
        # Step 16b: Create game_events for world_tick, scene, NPC, and narration
        if world_progression:
            candidate_events = world_progression.get("candidate_events", [])
            for i, world_event in enumerate(candidate_events[:3]):
                _create_game_event(
                    db=db,
                    transaction_id=transaction_id,
                    session_id=session_id,
                    turn_no=turn_no,
                    event_type="world_tick",
                    actor_id="world_engine",
                    target_ids=None,
                    visibility_scope=world_event.get("visibility", "player_visible"),
                    public_payload={
                        "event_type": world_event.get("event_type"),
                        "description": world_event.get("description"),
                        "importance": world_event.get("importance", 0.5),
                    },
                    result_json={"effects": world_event.get("effects", {})},
                )
        
        if scene_event_summary:
            _create_game_event(
                db=db,
                transaction_id=transaction_id,
                session_id=session_id,
                turn_no=turn_no,
                event_type="scene",
                actor_id="scene_engine",
                target_ids=[scene_event_summary.get("scene_id")] if scene_event_summary.get("scene_id") else None,
                visibility_scope="player_visible",
                public_payload={
                    "scene_id": scene_event_summary.get("scene_id"),
                    "scene_name": scene_event_summary.get("scene_name"),
                    "candidate_events": scene_event_summary.get("candidate_events", []),
                },
                result_json={"fallback_reason": scene_fallback_reason},
            )
        
        for npc_reaction in npc_reactions_for_json:
            npc_id = npc_reaction.get("npc_id")
            npc_name = npc_reaction.get("npc_name")
            action_type_npc = npc_reaction.get("action_type")
            summary = npc_reaction.get("summary")
            visible_to_player = npc_reaction.get("visible_to_player", True)
            
            _create_game_event(
                db=db,
                transaction_id=transaction_id,
                session_id=session_id,
                turn_no=turn_no,
                event_type="npc_decision",
                actor_id=npc_id,
                target_ids=["player"] if visible_to_player else None,
                visibility_scope="player_visible" if visible_to_player else "hidden",
                public_payload={
                    "npc_name": npc_name,
                    "action_type": action_type_npc,
                    "summary": summary,
                } if visible_to_player else None,
                private_payload={
                    "npc_name": npc_name,
                    "action_type": action_type_npc,
                    "summary": summary,
                    "visible_motivation": npc_reaction.get("visible_motivation"),
                } if not visible_to_player else None,
                result_json={
                    "accepted": npc_reaction.get("accepted"),
                    "fallback_reason": npc_reaction.get("fallback_reason"),
                },
            )
        
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
            },
        )
        
        # Step 16c: Create state_delta records for state changes
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
            source_event_id=narration_event_id,
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
        
        # Step 17: Update result_json with LLM stage results, scene summary, and NPC reactions
        llm_stages_json = [sr.to_result_json_dict() for sr in llm_stage_results]
        input_intent_stage_json = input_intent_result.to_result_json_dict()
        updated_result_json = {
            "transaction_id": transaction_id,
            "recommended_actions": final_recommended_actions,
            "state_deltas": state_deltas,
            "action_type": action_type,
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
        }
        event_log_repo = EventLogRepository(db)
        event_log_repo.update(event.id, {"result_json": updated_result_json})
        
        # Step 18: Update session state with durable time and location changes
        session_state_update = {
            "session_id": session_id,
            "current_time": _format_world_time(world_time),
            "time_phase": world_time["period"],
        }
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
                world_progression=world_progression,
                scene_event_summary=scene_event_summary,
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
        
        # Step 21: Mark transaction as committed
        turn_transaction_repo.update_status(
            transaction_id,
            status="committed",
            world_time_after=_format_world_time(world_time),
        )
        
        # Step 22: Return result
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
            llm_stage_results=[input_intent_result] + llm_stage_results,
        )
    
    except Exception as e:
        # Mark transaction as aborted on any failure
        turn_transaction_repo.update_status(
            transaction_id,
            status="aborted",
            error_json={"error": str(e)[:500], "type": type(e).__name__},
        )
        raise


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


def _parse_world_day(day_value: Any) -> int:
    if isinstance(day_value, int):
        return day_value
    if isinstance(day_value, str):
        digits = "".join(ch for ch in day_value if ch.isdigit())
        if digits:
            return int(digits)
    return 1


def _advance_world_time(world_time: Dict[str, Any]) -> Dict[str, Any]:
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
    if next_index == 0:
        day += 1

    return {
        "calendar": world_time.get("calendar", "修仙历"),
        "season": world_time.get("season", "春"),
        "day": f"第{day}日",
        "period": periods[next_index],
    }


def _format_world_time(world_time: Dict[str, Any]) -> str:
    return " ".join([
        str(world_time.get("calendar", "修仙历")),
        str(world_time.get("season", "春")),
        str(world_time.get("day", "第1日")),
        str(world_time.get("period", "辰时")),
    ])


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
    world_progression: Optional[Dict[str, Any]] = None,
    scene_event_summary: Optional[Dict[str, Any]] = None,
    canonical_state: Optional[CanonicalState] = None,
) -> Dict[str, Any]:
    """
    Persist perspective-aware memory summaries and facts after a successful turn.
    
    Uses MemoryWriter to write to DB tables:
    - memory_summaries: World Chronicle, Scene Summary, NPC Subjective Summary
    - memory_facts: Location changes, quest progression, NPC beliefs
    - npc_beliefs: NPC belief updates after observed events
    - npc_relationship_memories: Relationship memory updates
    
    NPC subjective memory is NEVER included in player-visible output.
    
    Returns metadata about memory write success/failure (non-fatal).
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
        
        summary_parts = []
        if action_type:
            summary_parts.append(f"玩家执行了{action_type}动作")
        if player_input:
            summary_parts.append(f"输入: {player_input[:100]}")
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
        
        if current_location_id and scene_event_summary and canonical_state:
            candidate_events = scene_event_summary.get("candidate_events", [])
            from ..models.events import SceneEvent, EventType
            mock_events = [
                SceneEvent(
                    event_id=f"scene_{i}",
                    event_type=EventType.SCENE_EVENT,
                    turn_index=turn_no,
                    scene_id=current_location_id,
                    trigger=e.get("event_type", "scene"),
                    summary=e.get("description", ""),
                )
                for i, e in enumerate(candidate_events[:3])
            ]
            
            memory_writer.write_scene_summary(
                scene_id=current_location_id,
                start_turn=turn_no,
                end_turn=turn_no,
                events=mock_events,
                state=canonical_state,
            )
            result["summaries_created"] += 1
        
        if state_deltas:
            if "location_id" in state_deltas:
                memory_writer._persist_fact_to_db(
                    fact_id=f"fact_loc_{session_id}_{turn_no}",
                    fact_type="location_change",
                    subject_ref="player",
                    fact_key="current_location",
                    fact_value=state_deltas["location_id"],
                    confidence=1.0,
                    source_event_id=event_id,
                )
                result["facts_created"] += 1
            
            if "quest_progression" in state_deltas:
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
        
        if npc_reactions and canonical_state:
            for reaction in npc_reactions:
                if reaction.get("accepted") and reaction.get("npc_id"):
                    npc_id = reaction.get("npc_id")
                    npc_name = reaction.get("npc_name", "unknown")
                    summary = reaction.get("summary", "")
                    
                    from ..models.events import NPCActionEvent, EventType
                    mock_events = [NPCActionEvent(
                        event_id=f"npc_{npc_id}_{turn_no}",
                        event_type=EventType.NPC_ACTION,
                        turn_index=turn_no,
                        npc_id=npc_id,
                        action_type=reaction.get("action_type", "idle"),
                        summary=summary,
                    )]
                    
                    memory_writer.write_npc_subjective_summary(
                        npc_id=npc_id,
                        start_turn=turn_no,
                        end_turn=turn_no,
                        events=mock_events,
                        state=canonical_state,
                    )
                    result["npc_memories_created"] += 1
                    
                    if action_type and summary:
                        mock_event = SceneEvent(
                            event_id=event_id,
                            event_type=EventType.SCENE_EVENT,
                            turn_index=turn_no,
                            scene_id=current_location_id or "unknown",
                            trigger="player_action",
                            summary=f"玩家执行了{action_type}: {summary[:100]}",
                        )
                        
                        memory_writer.write_npc_belief_update(
                            npc_id=npc_id,
                            observed_event=mock_event,
                            current_turn=turn_no,
                            belief_type="fact",
                            confidence=0.8,
                        )
                        result["npc_beliefs_created"] += 1
        
        if world_progression:
            candidate_events = world_progression.get("candidate_events", [])
            for i, event in enumerate(candidate_events[:3]):
                event_type = event.get("event_type", "unknown")
                description = event.get("description", "")
                if description:
                    memory_writer._persist_fact_to_db(
                        fact_id=f"fact_world_{session_id}_{turn_no}_{i}",
                        fact_type="world_event",
                        subject_ref="world",
                        fact_key=event_type,
                        fact_value=description[:200],
                        confidence=event.get("importance", 0.5),
                        source_event_id=event_id,
                    )
                    result["facts_created"] += 1
        
    except Exception as e:
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
) -> Optional[str]:
    """
    Create a validation_report record for validation tracking.
    
    Returns the created record ID, or None on failure.
    """
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
        logger.warning("Failed to create validation_report: %s", e)
        return None


def _validate_proposal(
    db: Session,
    proposal: Any,
    proposal_type: str,
    validation_context: ValidationContext,
    transaction_id: str,
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
