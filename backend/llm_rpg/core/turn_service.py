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

from ..storage.models import SessionModel, EventLogModel
from ..storage.repositories import (
    SessionRepository,
    SessionStateRepository,
    EventLogRepository,
    LocationRepository,
    SessionNPCStateRepository,
    NPCTemplateRepository,
    SessionQuestStateRepository,
    QuestTemplateRepository,
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
            return future.result(timeout=60)
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


def _build_narration_context(
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
    Build narration context from committed state only.
    
    CRITICAL: Only includes player-visible facts. No hidden NPC info.
    
    Context includes:
    - Session state (current location, world time)
    - Action result (movement success/blocked, quest progression)
    - Visible NPCs at location (public identity only, NO hidden_identity)
    - Recent event log entries (last 5 turns)
    - Current location details
    - State deltas from this turn
    
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
        Dict with narration context for LLM
    """
    context: Dict[str, Any] = {
        "session_id": session_id,
        "player_input": player_input,
        "action_type": action_type,
        "constraints": [
            "只能描述玩家可见的场景和事件",
            "不能泄露隐藏的秘密或未揭示的信息",
            "不能添加未发生的事件或未提交的状态变化",
            "叙事必须基于已提交的事实",
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
    
    recent_events = _get_recent_events(db, session_id, limit=5)
    context["recent_events"] = recent_events
    
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
) -> List[LLMStageResult]:
    """
    Execute LLM-enabled stages for a turn.
    
    Stage order (scene runs before narration):
    1. Scene stage - generate scene event candidates and recommended actions
    2. Narration stage - generate narrative text
    
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
    )
    results.append(scene_result)
    
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
    
    try:
        from ..services.settings import SystemSettingsService
        settings_service = SystemSettingsService(db)
        provider_config = settings_service.get_provider_config()
        
        llm_service = _create_llm_service_from_config(db, provider_config)
        
        pipeline_config = ProposalConfig(
            timeout_seconds=timeout,
            max_tokens=provider_config.get("max_tokens", 500),
            temperature=provider_config.get("temperature", 0.8),
        )
        pipeline = ProposalPipeline(llm_service=llm_service, config=pipeline_config)
        
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
) -> LLMService:
    """
    Create an LLMService configured from SystemSettingsService.
    
    Uses the provider_mode and API keys from settings.
    """
    from ..llm.service import OpenAIProvider
    
    provider_mode = provider_config.get("provider_mode", "auto")
    default_model = provider_config.get("default_model", "gpt-4")
    custom_base_url = provider_config.get("custom_base_url")
    
    from ..services.settings import SystemSettingsService
    settings_service = SystemSettingsService(db)
    
    if provider_mode == "custom" and custom_base_url:
        api_key = settings_service.get_effective_custom_api_key()
        if api_key:
            provider = OpenAIProvider(
                api_key=api_key,
                model=default_model,
                base_url=custom_base_url,
            )
            return LLMService(provider=provider, db_session=db)
    
    if provider_mode in ("openai", "auto"):
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
        
        llm_service = _create_llm_service_from_config(db, provider_config)
        
        pipeline_config = ProposalConfig(
            timeout_seconds=timeout,
            max_tokens=provider_config.get("max_tokens", 500),
            temperature=provider_config.get("temperature", 0.8),
        )
        pipeline = ProposalPipeline(llm_service=llm_service, config=pipeline_config)
        
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
    
    # Step 8: Generate recommended actions (deterministic fallback)
    session_state_repo = SessionStateRepository(db)
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
    
    # Step 9: Build template narration (fallback-safe placeholder)
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
    
    # Step 12: Commit turn to DB with template narration (durable commit first)
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
                "recommended_actions": deterministic_recommended_actions,
                "state_deltas": state_deltas,
                "action_type": action_type,
                "movement_success": movement_result.success if movement_result else None,
                "new_location_id": movement_result.new_location_id if movement_result else None,
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
    
    # Step 13: Execute LLM stages (scene before narration)
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
    )
    
    # Step 14: Determine final recommended actions and scene event summary
    final_recommended_actions = deterministic_recommended_actions
    scene_event_summary: Optional[Dict[str, Any]] = None
    scene_fallback_reason: Optional[str] = None
    
    for stage_result in llm_stage_results:
        if stage_result.stage_name == "scene":
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
    
    # Step 15: If LLM narration accepted, update EventLogModel.narrative_text
    final_narration = narration
    for stage_result in llm_stage_results:
        if stage_result.stage_name == "narration" and stage_result.accepted:
            if stage_result.parsed_proposal and "text" in stage_result.parsed_proposal:
                final_narration = stage_result.parsed_proposal["text"]
                event_log_repo = EventLogRepository(db)
                event_log_repo.update(event.id, {"narrative_text": final_narration})
    
    # Step 16: Update result_json with LLM stage results and scene summary
    llm_stages_json = [sr.to_result_json_dict() for sr in llm_stage_results]
    updated_result_json = {
        "transaction_id": transaction_id,
        "recommended_actions": final_recommended_actions,
        "state_deltas": state_deltas,
        "action_type": action_type,
        "movement_success": movement_result.success if movement_result else None,
        "new_location_id": movement_result.new_location_id if movement_result else None,
        "llm_stages": llm_stages_json,
        "scene_event_summary": scene_event_summary,
        "scene_fallback_reason": scene_fallback_reason,
    }
    event_log_repo = EventLogRepository(db)
    event_log_repo.update(event.id, {"result_json": updated_result_json})
    
    # Step 17: Update session state if movement succeeded
    if movement_result and movement_result.success and movement_result.new_location_id:
        session_state_repo.create_or_update({
            "session_id": session_id,
            "current_location_id": movement_result.new_location_id,
        })
    
    # Step 18: Update last played
    session_repo.update_last_played(session_id)
    
    # Step 19: Return result
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
        llm_stage_results=llm_stage_results,
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
