"""
Turn Progression Audit Module for LLM RPG Engine.

Provides machine-readable audit metadata for debugging turn progression failures.
Records:
- Intent parse source (LLM vs keyword fallback)
- World/scene fallback reasons
- NPC skip reasons
- Validation failures
- Committed state deltas

All audit data is sanitized to ensure no secrets/API keys are exposed.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict

from sqlalchemy.orm import Session as DBSession


@dataclass
class TurnAudit:
    """
    Machine-readable audit metadata for a turn execution.
    
    Captures progression evidence for debugging failures:
    - Intent parse source and fallback reason
    - World/scene candidate generation status
    - NPC action counts and skip reasons
    - Validation failures
    - Committed state delta counts
    """
    # Intent parsing
    intent_type: Optional[str] = None
    intent_parse_source: str = "unknown"  # "llm", "keyword_fallback", "unknown"
    intent_fallback_reason: Optional[str] = None
    
    # World candidates
    world_candidates_count: int = 0
    world_fallback_used: bool = False
    world_fallback_reason: Optional[str] = None
    
    # Scene candidates
    scene_candidates_count: int = 0
    scene_fallback_used: bool = False
    scene_fallback_reason: Optional[str] = None
    
    # NPC actions
    npc_action_count: int = 0
    npc_skip_count: int = 0
    npc_skip_reasons: List[str] = field(default_factory=list)
    
    # Movement result
    movement_result: Optional[str] = None  # "success", "blocked", "none"
    
    # Scene status
    scene_status: str = "active"  # "active", "transitioned", "ended"
    
    # State deltas
    state_deltas_count: int = 0
    state_deltas_committed: int = 0
    
    # Validation
    validation_passed: bool = True
    validation_failures: List[str] = field(default_factory=list)
    
    # Proposal audits count
    proposal_audits_count: int = 0
    
    # Timing
    turn_duration_ms: Optional[int] = None
    
    # Metadata
    audit_id: str = field(default_factory=lambda: f"audit_{uuid.uuid4().hex[:8]}")
    created_at: datetime = field(default_factory=datetime.now)


def build_turn_audit(turn_result: Dict[str, Any]) -> TurnAudit:
    """
    Build TurnAudit from turn execution result.
    
    Args:
        turn_result: Dict returned by TurnOrchestrator.execute_turn()
        
    Returns:
        TurnAudit with machine-readable progression metadata
    """
    audit = TurnAudit()
    
    if "parsed_intent" in turn_result:
        parsed_intent = turn_result.get("parsed_intent")
        if parsed_intent:
            audit.intent_type = parsed_intent.get("intent_type", "unknown")
            audit.intent_parse_source = "llm"
        else:
            audit.intent_parse_source = "keyword_fallback"
            audit.intent_fallback_reason = "No parsed intent from LLM"
    
    audit.world_candidates_count = turn_result.get("world_candidates_count", 0)
    audit.world_fallback_used = turn_result.get("world_fallback_used", False)
    audit.world_fallback_reason = turn_result.get("world_fallback_reason")
    
    audit.scene_candidates_count = turn_result.get("scene_candidates_count", 0)
    audit.scene_fallback_used = turn_result.get("scene_fallback_used", False)
    audit.scene_fallback_reason = turn_result.get("scene_fallback_reason")
    
    audit.npc_action_count = turn_result.get("npc_action_count", 0)
    audit.npc_skip_count = turn_result.get("npc_skip_count", 0)
    audit.npc_skip_reasons = turn_result.get("npc_skip_reasons", [])
    
    audit.movement_result = turn_result.get("movement_result")
    audit.scene_status = turn_result.get("scene_status", "active")
    audit.state_deltas_count = turn_result.get("state_deltas_count", 0)
    audit.state_deltas_committed = turn_result.get("state_deltas_applied", 0)
    audit.validation_passed = turn_result.get("validation_passed", True)
    audit.validation_failures = turn_result.get("validation_failures", [])
    audit.proposal_audits_count = turn_result.get("proposal_audits", 0)
    audit.turn_duration_ms = turn_result.get("turn_duration_ms")
    
    return audit


def persist_turn_audit(
    db: DBSession,
    session_id: str,
    turn_no: int,
    audit: TurnAudit,
) -> str:
    """
    Persist turn audit to database for debugging.
    
    Stores audit in event_log.result_json for player-visible inspection.
    Does NOT block successful turn commits - failures are logged but don't fail the turn.
    
    Args:
        db: Database session
        session_id: Game session ID
        turn_no: Turn number
        audit: TurnAudit to persist
        
    Returns:
        audit_id of persisted record
    """
    from llm_rpg.storage.models import EventLogModel
    
    try:
        # Find or create event log entry for this turn
        event_log = db.query(EventLogModel).filter(
            EventLogModel.session_id == session_id,
            EventLogModel.turn_no == turn_no,
            EventLogModel.event_type == "turn_audit",
        ).first()
        
        if event_log:
            # Update existing entry
            event_log.result_json = {
                "turn_audit": sanitize_audit_data(asdict(audit)),
            }
        else:
            # Create new entry
            event_log = EventLogModel(
                id=audit.audit_id,
                session_id=session_id,
                turn_no=turn_no,
                event_type="turn_audit",
                result_json={
                    "turn_audit": sanitize_audit_data(asdict(audit)),
                },
                occurred_at=datetime.now(),
            )
            db.add(event_log)
        
        # Note: We don't commit here - let the caller handle transaction
        # This ensures audit persistence doesn't block turn commit
        
        return audit.audit_id
        
    except Exception as e:
        # Log error but don't fail the turn
        # Audit persistence failure should not block successful turn execution
        import logging
        logging.getLogger(__name__).warning(
            f"Failed to persist turn audit for session {session_id}, turn {turn_no}: {e}"
        )
        return audit.audit_id


def sanitize_audit_data(audit_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize audit data to ensure no secrets/API keys are exposed.
    
    Removes or masks sensitive fields:
    - API keys
    - Hidden identities (NPC secrets)
    - Raw LLM outputs containing sensitive data
    
    Converts datetime objects to ISO format strings for JSON serialization.
    
    Args:
        audit_dict: Raw audit dictionary
        
    Returns:
        Sanitized dictionary safe for player viewing
    """
    sanitized = {}
    
    for key, value in audit_dict.items():
        if key in ["api_key", "hidden_identity", "secret_info"]:
            continue
        
        if isinstance(value, datetime):
            sanitized[key] = value.isoformat()
        elif key in ["raw_output_preview", "raw_llm_output"]:
            if isinstance(value, str) and len(value) > 100:
                sanitized[key] = value[:100] + "...[SANITIZED]"
            else:
                sanitized[key] = value
        else:
            sanitized[key] = value
    
    return sanitized


def extract_progression_audit_from_result_json(
    result_json: Optional[Dict[str, Any]],
) -> Optional[TurnAudit]:
    """
    Extract TurnAudit from event log result_json.
    
    Args:
        result_json: Event log result_json field
        
    Returns:
        TurnAudit if present, None otherwise
    """
    if not result_json:
        return None
    
    turn_audit_data = result_json.get("turn_audit")
    if not turn_audit_data:
        return None
    
    try:
        return TurnAudit(**turn_audit_data)
    except Exception:
        # Invalid audit data
        return None