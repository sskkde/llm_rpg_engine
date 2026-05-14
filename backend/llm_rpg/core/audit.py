"""
Audit Logging System for LLM RPG Engine.

Provides comprehensive audit trails for:
- Model calls (LLM invocations with token usage and cost)
- Turn transactions (player inputs, events, state changes)
- Context builds (memory inclusion/exclusion with reasons)
- Validation results (pass/fail checks)
- Error logs (unexpected errors and failures)

All audit data is sanitized to ensure no secrets/API keys are logged.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class AuditEventType(str, Enum):
    """Types of audit events."""
    MODEL_CALL = "model_call"
    TURN_AUDIT = "turn_audit"
    CONTEXT_BUILD = "context_build"
    VALIDATION_RESULT = "validation_result"
    ERROR_LOG = "error_log"


class ValidationStatus(str, Enum):
    """Validation result status."""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


class MemoryDecisionReason(str, Enum):
    """Reasons for including or excluding memories."""
    RELEVANCE_SCORE = "relevance_score"
    PERSPECTIVE_FILTERED = "perspective_filtered"
    IMPORTANCE_THRESHOLD = "importance_threshold"
    TIME_RANGE_MATCH = "time_range_match"
    ENTITY_VISIBLE = "entity_visible"
    ENTITY_HIDDEN = "entity_hidden"
    FORBIDDEN_KNOWLEDGE = "forbidden_knowledge"
    RECENCY_PRIORITY = "recency_priority"
    EXPLICITLY_REQUESTED = "explicitly_requested"


class ModelCallLog(BaseModel):
    """Log entry for an LLM model call."""
    call_id: str = Field(..., description="Unique call identifier")
    session_id: str = Field(..., description="Game session ID")
    turn_no: int = Field(..., description="Turn number when call was made")
    
    # Model information (sanitized - no API keys)
    provider: str = Field(..., description="LLM provider name")
    model_name: str = Field(..., description="Model name/version")
    prompt_type: str = Field(..., description="Type of prompt (npc_decision, narration, etc.)")
    
    # Token usage
    input_tokens: int = Field(default=0, description="Number of input tokens")
    output_tokens: int = Field(default=0, description="Number of output tokens")
    total_tokens: int = Field(default=0, description="Total tokens used")
    
    # Cost and performance
    cost_estimate: Optional[float] = Field(None, description="Estimated cost in USD")
    latency_ms: int = Field(default=0, description="Call latency in milliseconds")
    
    # Status
    success: bool = Field(default=True, description="Whether the call succeeded")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    
    # Context IDs
    context_build_id: Optional[str] = Field(None, description="ID of context build that triggered this call")
    
    created_at: datetime = Field(default_factory=datetime.now)


class MemoryAuditEntry(BaseModel):
    """Audit entry for a single memory decision."""
    memory_id: str = Field(..., description="Memory identifier")
    memory_type: str = Field(..., description="Type of memory")
    owner_id: str = Field(..., description="Memory owner")
    
    # Decision
    included: bool = Field(..., description="Whether memory was included")
    reason: MemoryDecisionReason = Field(..., description="Reason for decision")
    
    # Scores
    relevance_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    importance_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    recency_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    
    # Additional context
    perspective_filter_applied: bool = Field(default=False)
    forbidden_knowledge_flag: bool = Field(default=False)
    notes: Optional[str] = Field(None, description="Additional notes")


class ContextBuildAudit(BaseModel):
    """Audit log for context building process."""
    build_id: str = Field(..., description="Unique build identifier")
    session_id: str = Field(..., description="Game session ID")
    turn_no: int = Field(..., description="Turn number")
    
    # Build parameters
    perspective_type: str = Field(..., description="Type of perspective (player, npc, world, narrator)")
    perspective_id: str = Field(..., description="Perspective identifier")
    owner_id: Optional[str] = Field(None, description="Context owner (e.g., NPC ID)")
    
    # Memory decisions
    included_memories: List[MemoryAuditEntry] = Field(default_factory=list)
    excluded_memories: List[MemoryAuditEntry] = Field(default_factory=list)
    
    # Statistics
    total_candidates: int = Field(default=0, description="Total memories considered")
    included_count: int = Field(default=0)
    excluded_count: int = Field(default=0)
    
    # Context metrics
    context_token_count: int = Field(default=0)
    context_char_count: int = Field(default=0)
    
    # Timing
    build_duration_ms: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.now)


class ValidationCheck(BaseModel):
    """Individual validation check result."""
    check_id: str = Field(..., description="Check identifier")
    check_type: str = Field(..., description="Type of validation check")
    status: ValidationStatus = Field(...)
    message: Optional[str] = Field(None)
    details: Dict[str, Any] = Field(default_factory=dict)


class ValidationResultAudit(BaseModel):
    """Audit log for validation results."""
    validation_id: str = Field(..., description="Unique validation identifier")
    session_id: str = Field(..., description="Game session ID")
    turn_no: int = Field(..., description="Turn number")
    
    # What was validated
    validation_target: str = Field(..., description="Type of target (action, state_delta, etc.)")
    target_id: Optional[str] = Field(None, description="Identifier of validated object")
    
    # Results
    overall_status: ValidationStatus = Field(...)
    checks: List[ValidationCheck] = Field(default_factory=list)
    
    # Errors and warnings
    error_count: int = Field(default=0)
    warning_count: int = Field(default=0)
    
    # Details
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    
    # Transaction info
    transaction_id: Optional[str] = Field(None)
    
    created_at: datetime = Field(default_factory=datetime.now)


class TurnStateDeltaAudit(BaseModel):
    """Audit entry for state delta in a turn."""
    delta_id: str = Field(..., description="Delta identifier")
    path: str = Field(..., description="State path")
    old_value: Any = Field(...)
    new_value: Any = Field(...)
    operation: str = Field(...)
    validated: bool = Field(default=False)


class TurnEventAudit(BaseModel):
    """Audit entry for events in a turn."""
    event_id: str = Field(..., description="Event identifier")
    event_type: str = Field(..., description="Event type")
    actor_id: Optional[str] = Field(None)
    summary: Optional[str] = Field(None)


class TurnAuditLog(BaseModel):
    """Comprehensive audit log for a turn."""
    audit_id: str = Field(..., description="Unique audit identifier")
    session_id: str = Field(..., description="Game session ID")
    turn_no: int = Field(..., description="Turn number")
    transaction_id: str = Field(..., description="Transaction ID")
    
    # Input
    player_input: str = Field(..., description="Player input text")
    parsed_intent: Optional[Dict[str, Any]] = Field(None, description="Parsed player intent")
    
    # Timeline
    world_time_before: Dict[str, Any] = Field(...)
    world_time_after: Optional[Dict[str, Any]] = Field(None)
    
    # Events
    events: List[TurnEventAudit] = Field(default_factory=list)
    
    # State changes
    state_deltas: List[TurnStateDeltaAudit] = Field(default_factory=list)
    
    # Model calls during turn
    model_call_ids: List[str] = Field(default_factory=list)
    
    # Context builds during turn
    context_build_ids: List[str] = Field(default_factory=list)
    
    # Validation results
    validation_ids: List[str] = Field(default_factory=list)
    
    # Status
    status: str = Field(default="completed", description="completed, failed, rolled_back")
    
    # Narration
    narration_generated: bool = Field(default=False)
    narration_length: int = Field(default=0)
    
    # Timing
    turn_duration_ms: Optional[int] = Field(None)
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = Field(None)


class ErrorSeverity(str, Enum):
    """Error severity levels."""
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ErrorLogEntry(BaseModel):
    """Log entry for errors and exceptions."""
    error_id: str = Field(..., description="Unique error identifier")
    session_id: Optional[str] = Field(None, description="Game session ID if applicable")
    turn_no: Optional[int] = Field(None, description="Turn number if applicable")
    
    # Error info
    severity: ErrorSeverity = Field(...)
    error_type: str = Field(..., description="Exception type or error category")
    message: str = Field(..., description="Error message")
    
    # Context
    component: str = Field(..., description="Component where error occurred")
    operation: Optional[str] = Field(None, description="Operation being performed")
    
    # Trace (sanitized - no sensitive data)
    stack_trace: Optional[str] = Field(None)
    
    # Related IDs
    transaction_id: Optional[str] = Field(None)
    context_build_id: Optional[str] = Field(None)
    model_call_id: Optional[str] = Field(None)
    
    # Additional context
    context: Dict[str, Any] = Field(default_factory=dict)
    
    # Recovery
    recovered: bool = Field(default=False, description="Whether error was recovered from")
    recovery_action: Optional[str] = Field(None)
    
    created_at: datetime = Field(default_factory=datetime.now)


class ProposalAuditEntry(BaseModel):
    """Audit entry for LLM proposal processing.
    
    Records enough data for replay without re-calling LLM:
    - prompt/template id
    - proposal type
    - raw output reference
    - parsed proposal
    - repair trace
    - rejection reason
    - fallback reason
    - committed event ids
    """
    audit_id: str = Field(..., description="Unique audit identifier")
    session_id: Optional[str] = Field(None, description="Game session ID")
    turn_no: int = Field(..., description="Turn number")
    
    # Proposal identification
    proposal_type: str = Field(..., description="Type: input_intent, world_tick, scene_event, npc_action, narration")
    proposal_id: Optional[str] = Field(None, description="Proposal ID from ProposalAuditMetadata")
    
    # LLM call info
    prompt_template_id: Optional[str] = Field(None, description="Template ID used for prompt")
    model_name: Optional[str] = Field(None, description="Model used")
    input_tokens: int = Field(default=0, description="Input token count")
    output_tokens: int = Field(default=0, description="Output token count")
    latency_ms: int = Field(default=0, description="LLM call latency")
    
    # Raw output (truncated for storage)
    raw_output_preview: str = Field(default="", description="First 200 chars of raw LLM output")
    raw_output_hash: Optional[str] = Field(None, description="Hash of full raw output for reference")
    
    # Parsed result
    parsed_proposal: Optional[Dict[str, Any]] = Field(None, description="Parsed proposal data")
    parse_success: bool = Field(default=True, description="Whether parsing succeeded")
    
    # Repair trace
    repair_attempts: int = Field(default=0, description="Number of repair attempts")
    repair_strategies_tried: List[str] = Field(default_factory=list, description="Repair strategies attempted")
    repair_success: bool = Field(default=True, description="Whether repair succeeded")
    
    # Validation
    validation_passed: bool = Field(default=True, description="Whether validation passed")
    validation_errors: List[str] = Field(default_factory=list, description="Validation errors")
    validation_warnings: List[str] = Field(default_factory=list, description="Validation warnings")
    
    # Rejection/Fallback
    rejected: bool = Field(default=False, description="Whether proposal was rejected")
    rejection_reason: Optional[str] = Field(None, description="Reason for rejection")
    fallback_used: bool = Field(default=False, description="Whether fallback was used")
    fallback_reason: Optional[str] = Field(None, description="Reason for fallback")
    fallback_strategy: Optional[str] = Field(None, description="Fallback strategy used")
    
    # Committed events
    committed_event_ids: List[str] = Field(default_factory=list, description="Event IDs committed from this proposal")
    
    # Confidence
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Proposal confidence score")
    
    # Perspective safety
    perspective_check_passed: bool = Field(default=True, description="Whether perspective safety check passed")
    forbidden_info_detected: List[str] = Field(default_factory=list, description="Forbidden info found in proposal")
    
    created_at: datetime = Field(default_factory=datetime.now)


class AuditStore:
    """In-memory storage for audit logs with optional DB persistence for model calls."""
    
    def __init__(self, db_session=None):
        self._model_calls: Dict[str, ModelCallLog] = {}
        self._context_builds: Dict[str, ContextBuildAudit] = {}
        self._validations: Dict[str, ValidationResultAudit] = {}
        self._turn_audits: Dict[str, TurnAuditLog] = {}
        self._proposal_audits: Dict[str, ProposalAuditEntry] = {}
        self._errors: Dict[str, ErrorLogEntry] = {}
        
        # Indexes
        self._model_calls_by_session: Dict[str, List[str]] = {}
        self._context_builds_by_session: Dict[str, List[str]] = {}
        self._validations_by_session: Dict[str, List[str]] = {}
        self._turn_audits_by_session: Dict[str, List[str]] = {}
        self._proposal_audits_by_session: Dict[str, List[str]] = {}
        self._errors_by_session: Dict[str, List[str]] = {}
        
        self._turn_audits_by_turn: Dict[tuple, str] = {}  # (session_id, turn_no) -> audit_id
        self._proposal_audits_by_turn: Dict[tuple, List[str]] = {}  # (session_id, turn_no) -> [audit_ids]
        
        # DB session for model call persistence
        self._db_session = db_session
    
    def get_proposal_audit(self, audit_id: str) -> Optional[ProposalAuditEntry]:
        """Get a proposal audit entry by ID."""
        return self._proposal_audits.get(audit_id)
    
    def get_proposal_audits_by_turn(
        self,
        session_id: str,
        turn_no: int,
    ) -> List[ProposalAuditEntry]:
        """Get all proposal audits for a specific turn."""
        key = (session_id, turn_no)
        audit_ids = self._proposal_audits_by_turn.get(key, [])
        return [self._proposal_audits[aid] for aid in audit_ids if aid in self._proposal_audits]
    
    def get_proposal_audits_by_session(
        self,
        session_id: str,
        proposal_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[ProposalAuditEntry]:
        """Get proposal audits for a session, optionally filtered by type."""
        audit_ids = self._proposal_audits_by_session.get(session_id, [])
        audits = [self._proposal_audits[aid] for aid in audit_ids if aid in self._proposal_audits]
        
        if proposal_type:
            audits = [a for a in audits if a.proposal_type == proposal_type]
        
        audits.sort(key=lambda a: a.created_at, reverse=True)
        return audits[:limit]
    
    def store_model_call(self, log: ModelCallLog) -> str:
        """Store a model call log."""
        self._model_calls[log.call_id] = log
        
        if log.session_id not in self._model_calls_by_session:
            self._model_calls_by_session[log.session_id] = []
        self._model_calls_by_session[log.session_id].append(log.call_id)
        
        if self._db_session is not None:
            self._persist_model_call_to_db(log)
        
        return log.call_id
    
    def _persist_model_call_to_db(self, log: ModelCallLog) -> None:
        """Persist a model call log to the database."""
        from llm_rpg.storage.models import ModelCallAuditLogModel
        try:
            db_log = ModelCallAuditLogModel(
                call_id=log.call_id,
                session_id=log.session_id,
                turn_no=log.turn_no,
                provider=log.provider,
                model_name=log.model_name,
                prompt_type=log.prompt_type,
                input_tokens=log.input_tokens,
                output_tokens=log.output_tokens,
                total_tokens=log.total_tokens,
                cost_estimate=log.cost_estimate,
                latency_ms=log.latency_ms,
                success=log.success,
                error_message=log.error_message,
                context_build_id=log.context_build_id,
                created_at=log.created_at,
            )
            self._db_session.add(db_log)
            self._db_session.commit()
        except Exception:
            self._db_session.rollback()
            raise

    def _persist_proposal_to_db(self, audit: ProposalAuditEntry) -> None:
        from llm_rpg.storage.models import ProposalAuditLogModel
        try:
            db_log = ProposalAuditLogModel(
                audit_id=audit.audit_id,
                session_id=audit.session_id,
                turn_no=audit.turn_no,
                proposal_type=audit.proposal_type,
                payload_json=audit.model_dump(mode='json'),
            )
            self._db_session.add(db_log)
            self._db_session.commit()
        except Exception:
            self._db_session.rollback()
            raise

    def _persist_context_build_to_db(self, audit: ContextBuildAudit) -> None:
        from llm_rpg.storage.models import ContextBuildAuditLogModel
        try:
            db_log = ContextBuildAuditLogModel(
                build_id=audit.build_id,
                session_id=audit.session_id,
                turn_no=audit.turn_no,
                perspective_type=audit.perspective_type,
                payload_json=audit.model_dump(mode='json'),
            )
            self._db_session.add(db_log)
            self._db_session.commit()
        except Exception:
            self._db_session.rollback()
            raise

    def _persist_validation_to_db(self, audit: ValidationResultAudit) -> None:
        from llm_rpg.storage.models import ValidationAuditLogModel
        try:
            db_log = ValidationAuditLogModel(
                validation_id=audit.validation_id,
                session_id=audit.session_id,
                turn_no=audit.turn_no,
                validation_type=audit.validation_target,
                payload_json=audit.model_dump(mode='json'),
            )
            self._db_session.add(db_log)
            self._db_session.commit()
        except Exception:
            self._db_session.rollback()
            raise

    def _persist_turn_audit_to_db(self, audit: TurnAuditLog) -> None:
        from llm_rpg.storage.models import TurnAuditLogModel
        try:
            db_log = TurnAuditLogModel(
                audit_id=audit.audit_id,
                session_id=audit.session_id,
                turn_no=audit.turn_no,
                payload_json=audit.model_dump(mode='json'),
            )
            self._db_session.add(db_log)
            self._db_session.commit()
        except Exception:
            self._db_session.rollback()
            raise

    def _persist_error_to_db(self, error: ErrorLogEntry) -> None:
        from llm_rpg.storage.models import ErrorAuditLogModel
        try:
            db_log = ErrorAuditLogModel(
                error_id=error.error_id,
                session_id=error.session_id,
                error_type=error.error_type,
                payload_json=error.model_dump(mode='json'),
            )
            self._db_session.add(db_log)
            self._db_session.commit()
        except Exception:
            self._db_session.rollback()
            raise
    
    def store_context_build(self, audit: ContextBuildAudit) -> str:
        """Store a context build audit."""
        self._context_builds[audit.build_id] = audit
        
        if audit.session_id not in self._context_builds_by_session:
            self._context_builds_by_session[audit.session_id] = []
        self._context_builds_by_session[audit.session_id].append(audit.build_id)
        
        if self._db_session is not None:
            self._persist_context_build_to_db(audit)
        
        return audit.build_id
    
    def store_validation(self, audit: ValidationResultAudit) -> str:
        """Store a validation result audit."""
        self._validations[audit.validation_id] = audit
        
        if audit.session_id not in self._validations_by_session:
            self._validations_by_session[audit.session_id] = []
        self._validations_by_session[audit.session_id].append(audit.validation_id)
        
        if self._db_session is not None:
            self._persist_validation_to_db(audit)
        
        return audit.validation_id
    
    def store_turn_audit(self, audit: TurnAuditLog) -> str:
        """Store a turn audit log."""
        self._turn_audits[audit.audit_id] = audit
        
        if audit.session_id not in self._turn_audits_by_session:
            self._turn_audits_by_session[audit.session_id] = []
        self._turn_audits_by_session[audit.session_id].append(audit.audit_id)
        
        # Index by (session_id, turn_no)
        key = (audit.session_id, audit.turn_no)
        self._turn_audits_by_turn[key] = audit.audit_id
        
        if self._db_session is not None:
            self._persist_turn_audit_to_db(audit)
        
        return audit.audit_id
    
    def store_proposal_audit(self, audit: ProposalAuditEntry) -> str:
        """Store a proposal audit entry."""
        self._proposal_audits[audit.audit_id] = audit
        
        if audit.session_id is None:
            if self._db_session is not None:
                self._persist_proposal_to_db(audit)
            return audit.audit_id
        
        if audit.session_id not in self._proposal_audits_by_session:
            self._proposal_audits_by_session[audit.session_id] = []
        self._proposal_audits_by_session[audit.session_id].append(audit.audit_id)
        
        key = (audit.session_id, audit.turn_no)
        if key not in self._proposal_audits_by_turn:
            self._proposal_audits_by_turn[key] = []
        self._proposal_audits_by_turn[key].append(audit.audit_id)
        
        if self._db_session is not None:
            self._persist_proposal_to_db(audit)
        
        return audit.audit_id
    
    def store_error(self, error: ErrorLogEntry) -> str:
        """Store an error log entry."""
        self._errors[error.error_id] = error
        
        if error.session_id:
            if error.session_id not in self._errors_by_session:
                self._errors_by_session[error.session_id] = []
            self._errors_by_session[error.session_id].append(error.error_id)
        
        if self._db_session is not None:
            self._persist_error_to_db(error)
        
        return error.error_id
    
    def get_model_call(self, call_id: str) -> Optional[ModelCallLog]:
        """Get a model call log by ID."""
        return self._model_calls.get(call_id)
    
    def get_context_build(self, build_id: str) -> Optional[ContextBuildAudit]:
        """Get a context build audit by ID."""
        return self._context_builds.get(build_id)
    
    def get_validation(self, validation_id: str) -> Optional[ValidationResultAudit]:
        """Get a validation result audit by ID."""
        return self._validations.get(validation_id)
    
    def get_turn_audit(self, audit_id: str) -> Optional[TurnAuditLog]:
        """Get a turn audit log by ID."""
        return self._turn_audits.get(audit_id)
    
    def get_turn_audit_by_turn(self, session_id: str, turn_no: int) -> Optional[TurnAuditLog]:
        """Get turn audit by session and turn number."""
        key = (session_id, turn_no)
        audit_id = self._turn_audits_by_turn.get(key)
        if audit_id:
            return self._turn_audits.get(audit_id)
        return None
    
    def get_error(self, error_id: str) -> Optional[ErrorLogEntry]:
        """Get an error log entry by ID."""
        return self._errors.get(error_id)
    
    def get_model_calls_by_session(
        self,
        session_id: str,
        limit: int = 100
    ) -> List[ModelCallLog]:
        """Get model calls for a session."""
        call_ids = self._model_calls_by_session.get(session_id, [])
        calls = [self._model_calls[cid] for cid in call_ids if cid in self._model_calls]
        calls.sort(key=lambda c: c.created_at, reverse=True)
        return calls[:limit]
    
    def get_model_calls_all(
        self,
        limit: int = 100
    ) -> List[ModelCallLog]:
        """Get all model calls, preferring DB query when available."""
        if self._db_session is not None:
            from llm_rpg.storage.models import ModelCallAuditLogModel
            from sqlalchemy import desc
            db_results = self._db_session.query(ModelCallAuditLogModel).order_by(
                desc(ModelCallAuditLogModel.created_at)
            ).limit(limit).all()
            return [
                ModelCallLog(
                    call_id=r.call_id,
                    session_id=r.session_id,
                    turn_no=r.turn_no,
                    provider=r.provider or "",
                    model_name=r.model_name or "",
                    prompt_type=r.prompt_type or "",
                    input_tokens=r.input_tokens or 0,
                    output_tokens=r.output_tokens or 0,
                    total_tokens=r.total_tokens or 0,
                    cost_estimate=r.cost_estimate,
                    latency_ms=r.latency_ms or 0,
                    success=r.success if r.success is not None else True,
                    error_message=r.error_message,
                    context_build_id=r.context_build_id,
                    created_at=r.created_at,
                )
                for r in db_results
            ]
        # Fallback to in-memory
        calls = list(self._model_calls.values())
        calls.sort(key=lambda c: c.created_at, reverse=True)
        return calls[:limit]
    
    def get_model_calls_from_db(
        self,
        session_id: str,
        limit: int = 100
    ) -> List[ModelCallLog]:
        """Get model calls for a session from the database."""
        if self._db_session is None:
            return self.get_model_calls_by_session(session_id, limit)
        from llm_rpg.storage.models import ModelCallAuditLogModel
        from sqlalchemy import desc
        db_results = self._db_session.query(ModelCallAuditLogModel).filter(
            ModelCallAuditLogModel.session_id == session_id
        ).order_by(
            desc(ModelCallAuditLogModel.created_at)
        ).limit(limit).all()
        return [
            ModelCallLog(
                call_id=r.call_id,
                session_id=r.session_id,
                turn_no=r.turn_no,
                provider=r.provider or "",
                model_name=r.model_name or "",
                prompt_type=r.prompt_type or "",
                input_tokens=r.input_tokens or 0,
                output_tokens=r.output_tokens or 0,
                total_tokens=r.total_tokens or 0,
                cost_estimate=r.cost_estimate,
                latency_ms=r.latency_ms or 0,
                success=r.success if r.success is not None else True,
                error_message=r.error_message,
                context_build_id=r.context_build_id,
                created_at=r.created_at,
            )
            for r in db_results
        ]
    
    def get_context_builds_by_session(
        self,
        session_id: str,
        limit: int = 100
    ) -> List[ContextBuildAudit]:
        """Get context builds for a session."""
        build_ids = self._context_builds_by_session.get(session_id, [])
        builds = [self._context_builds[bid] for bid in build_ids if bid in self._context_builds]
        builds.sort(key=lambda b: b.created_at, reverse=True)
        return builds[:limit]
    
    def get_validations_by_session(
        self,
        session_id: str,
        limit: int = 100
    ) -> List[ValidationResultAudit]:
        """Get validation results for a session."""
        validation_ids = self._validations_by_session.get(session_id, [])
        validations = [self._validations[vid] for vid in validation_ids if vid in self._validations]
        validations.sort(key=lambda v: v.created_at, reverse=True)
        return validations[:limit]
    
    def get_turn_audits_by_session(
        self,
        session_id: str,
        limit: int = 100
    ) -> List[TurnAuditLog]:
        """Get turn audits for a session."""
        audit_ids = self._turn_audits_by_session.get(session_id, [])
        audits = [self._turn_audits[aid] for aid in audit_ids if aid in self._turn_audits]
        audits.sort(key=lambda a: a.turn_no, reverse=True)
        return audits[:limit]
    
    def get_errors_by_session(
        self,
        session_id: str,
        severity: Optional[ErrorSeverity] = None,
        limit: int = 100
    ) -> List[ErrorLogEntry]:
        """Get errors for a session."""
        error_ids = self._errors_by_session.get(session_id, [])
        errors = [self._errors[eid] for eid in error_ids if eid in self._errors]
        
        if severity:
            errors = [e for e in errors if e.severity == severity]
        
        errors.sort(key=lambda e: e.created_at, reverse=True)
        return errors[:limit]
    
    def get_all_errors(
        self,
        severity: Optional[ErrorSeverity] = None,
        limit: int = 100
    ) -> List[ErrorLogEntry]:
        """Get all errors."""
        errors = list(self._errors.values())
        
        if severity:
            errors = [e for e in errors if e.severity == severity]
        
        errors.sort(key=lambda e: e.created_at, reverse=True)
        return errors[:limit]
    
    def clear_session(self, session_id: str) -> None:
        """Clear all audit data for a session."""
        # Clear model calls
        for call_id in self._model_calls_by_session.get(session_id, []):
            self._model_calls.pop(call_id, None)
        self._model_calls_by_session.pop(session_id, None)
        
        # Clear context builds
        for build_id in self._context_builds_by_session.get(session_id, []):
            self._context_builds.pop(build_id, None)
        self._context_builds_by_session.pop(session_id, None)
        
        # Clear validations
        for vid in self._validations_by_session.get(session_id, []):
            self._validations.pop(vid, None)
        self._validations_by_session.pop(session_id, None)
        
        # Clear turn audits
        for audit_id in self._turn_audits_by_session.get(session_id, []):
            audit = self._turn_audits.pop(audit_id, None)
            if audit:
                key = (audit.session_id, audit.turn_no)
                self._turn_audits_by_turn.pop(key, None)
        self._turn_audits_by_session.pop(session_id, None)
        
        # Clear errors
        for eid in self._errors_by_session.get(session_id, []):
            self._errors.pop(eid, None)
        self._errors_by_session.pop(session_id, None)
        
        # Clear model calls from DB
        if self._db_session is not None:
            from llm_rpg.storage.models import ModelCallAuditLogModel
            try:
                self._db_session.query(ModelCallAuditLogModel).filter(
                    ModelCallAuditLogModel.session_id == session_id
                ).delete()
                self._db_session.commit()
            except Exception:
                self._db_session.rollback()
                raise


class AuditLogger:
    """Main audit logging interface."""
    
    def __init__(self, store: Optional[AuditStore] = None, db_session=None):
        self._store = store or AuditStore(db_session=db_session)
    
    def log_model_call(
        self,
        session_id: str,
        turn_no: int,
        provider: str,
        model_name: str,
        prompt_type: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_estimate: Optional[float] = None,
        latency_ms: int = 0,
        success: bool = True,
        error_message: Optional[str] = None,
        context_build_id: Optional[str] = None,
    ) -> ModelCallLog:
        """Log an LLM model call."""
        log = ModelCallLog(
            call_id=f"call_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            turn_no=turn_no,
            provider=provider,
            model_name=model_name,
            prompt_type=prompt_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_estimate=cost_estimate,
            latency_ms=latency_ms,
            success=success,
            error_message=error_message,
            context_build_id=context_build_id,
        )
        self._store.store_model_call(log)
        return log
    
    def log_context_build(
        self,
        session_id: str,
        turn_no: int,
        perspective_type: str,
        perspective_id: str,
        owner_id: Optional[str] = None,
        included_memories: Optional[List[MemoryAuditEntry]] = None,
        excluded_memories: Optional[List[MemoryAuditEntry]] = None,
        total_candidates: int = 0,
        context_token_count: int = 0,
        context_char_count: int = 0,
        build_duration_ms: int = 0,
    ) -> ContextBuildAudit:
        """Log a context build with memory decisions."""
        included = included_memories or []
        excluded = excluded_memories or []
        
        audit = ContextBuildAudit(
            build_id=f"ctx_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            turn_no=turn_no,
            perspective_type=perspective_type,
            perspective_id=perspective_id,
            owner_id=owner_id,
            included_memories=included,
            excluded_memories=excluded,
            total_candidates=total_candidates,
            included_count=len(included),
            excluded_count=len(excluded),
            context_token_count=context_token_count,
            context_char_count=context_char_count,
            build_duration_ms=build_duration_ms,
        )
        self._store.store_context_build(audit)
        return audit
    
    def log_validation(
        self,
        session_id: str,
        turn_no: int,
        validation_target: str,
        target_id: Optional[str] = None,
        overall_status: ValidationStatus = ValidationStatus.PASSED,
        checks: Optional[List[ValidationCheck]] = None,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
        transaction_id: Optional[str] = None,
    ) -> ValidationResultAudit:
        """Log a validation result."""
        check_list = checks or []
        
        audit = ValidationResultAudit(
            validation_id=f"val_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            turn_no=turn_no,
            validation_target=validation_target,
            target_id=target_id,
            overall_status=overall_status,
            checks=check_list,
            error_count=len(errors) if errors else sum(1 for c in check_list if c.status == ValidationStatus.FAILED),
            warning_count=len(warnings) if warnings else sum(1 for c in check_list if c.status == ValidationStatus.WARNING),
            errors=errors or [],
            warnings=warnings or [],
            transaction_id=transaction_id,
        )
        self._store.store_validation(audit)
        return audit
    
    def log_turn(
        self,
        session_id: str,
        turn_no: int,
        transaction_id: str,
        player_input: str,
        world_time_before: Dict[str, Any],
        world_time_after: Optional[Dict[str, Any]] = None,
        parsed_intent: Optional[Dict[str, Any]] = None,
        events: Optional[List[TurnEventAudit]] = None,
        state_deltas: Optional[List[TurnStateDeltaAudit]] = None,
        model_call_ids: Optional[List[str]] = None,
        context_build_ids: Optional[List[str]] = None,
        validation_ids: Optional[List[str]] = None,
        status: str = "completed",
        narration_generated: bool = False,
        narration_length: int = 0,
        turn_duration_ms: Optional[int] = None,
    ) -> TurnAuditLog:
        """Log a complete turn audit."""
        audit = TurnAuditLog(
            audit_id=f"turn_audit_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            turn_no=turn_no,
            transaction_id=transaction_id,
            player_input=player_input,
            parsed_intent=parsed_intent,
            world_time_before=world_time_before,
            world_time_after=world_time_after,
            events=events or [],
            state_deltas=state_deltas or [],
            model_call_ids=model_call_ids or [],
            context_build_ids=context_build_ids or [],
            validation_ids=validation_ids or [],
            status=status,
            narration_generated=narration_generated,
            narration_length=narration_length,
            turn_duration_ms=turn_duration_ms,
            completed_at=datetime.now() if status == "completed" else None,
        )
        self._store.store_turn_audit(audit)
        return audit
    
    def log_error(
        self,
        error_type: str,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        session_id: Optional[str] = None,
        turn_no: Optional[int] = None,
        component: str = "unknown",
        operation: Optional[str] = None,
        stack_trace: Optional[str] = None,
        transaction_id: Optional[str] = None,
        context_build_id: Optional[str] = None,
        model_call_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        recovered: bool = False,
        recovery_action: Optional[str] = None,
    ) -> ErrorLogEntry:
        """Log an error or exception."""
        # Sanitize stack trace to remove sensitive info
        sanitized_trace = self._sanitize_stack_trace(stack_trace) if stack_trace else None
        
        error = ErrorLogEntry(
            error_id=f"err_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            turn_no=turn_no,
            severity=severity,
            error_type=error_type,
            message=message,
            component=component,
            operation=operation,
            stack_trace=sanitized_trace,
            transaction_id=transaction_id,
            context_build_id=context_build_id,
            model_call_id=model_call_id,
            context=context or {},
            recovered=recovered,
            recovery_action=recovery_action,
        )
        self._store.store_error(error)
        return error
    
    def _sanitize_stack_trace(self, trace: str) -> str:
        """Sanitize stack trace to remove sensitive information."""
        # Remove API keys, passwords, tokens
        import re
        
        # Pattern for common secret formats
        patterns = [
            (r'(api[_-]?key["\']?\s*[:=]\s*["\']?)[\w-]+', r'\1***REDACTED***'),
            (r'(password["\']?\s*[:=]\s*["\']?)[^\s,}"\']+', r'\1***REDACTED***'),
            (r'(token["\']?\s*[:=]\s*["\']?)[\w-]+', r'\1***REDACTED***'),
            (r'(secret["\']?\s*[:=]\s*["\']?)[\w-]+', r'\1***REDACTED***'),
            (r'sk-[a-zA-Z0-9]{48}', r'***REDACTED_API_KEY***'),
            (r'Bearer\s+[\w-]+', r'Bearer ***REDACTED***'),
        ]
        
        sanitized = trace
        for pattern, replacement in patterns:
            sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
        
        return sanitized
    
    def log_proposal(
        self,
        session_id: Optional[str],
        turn_no: int,
        proposal_type: str,
        proposal_id: Optional[str] = None,
        prompt_template_id: Optional[str] = None,
        model_name: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        raw_output_preview: str = "",
        raw_output_hash: Optional[str] = None,
        parsed_proposal: Optional[Dict[str, Any]] = None,
        parse_success: bool = True,
        repair_attempts: int = 0,
        repair_strategies_tried: Optional[List[str]] = None,
        repair_success: bool = True,
        validation_passed: bool = True,
        validation_errors: Optional[List[str]] = None,
        validation_warnings: Optional[List[str]] = None,
        rejected: bool = False,
        rejection_reason: Optional[str] = None,
        fallback_used: bool = False,
        fallback_reason: Optional[str] = None,
        fallback_strategy: Optional[str] = None,
        committed_event_ids: Optional[List[str]] = None,
        confidence: float = 0.5,
        perspective_check_passed: bool = True,
        forbidden_info_detected: Optional[List[str]] = None,
    ) -> ProposalAuditEntry:
        """Log an LLM proposal with full audit trail for replay."""
        audit = ProposalAuditEntry(
            audit_id=f"prop_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            turn_no=turn_no,
            proposal_type=proposal_type,
            proposal_id=proposal_id,
            prompt_template_id=prompt_template_id,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            raw_output_preview=raw_output_preview[:200] if raw_output_preview else "",
            raw_output_hash=raw_output_hash,
            parsed_proposal=parsed_proposal,
            parse_success=parse_success,
            repair_attempts=repair_attempts,
            repair_strategies_tried=repair_strategies_tried or [],
            repair_success=repair_success,
            validation_passed=validation_passed,
            validation_errors=validation_errors or [],
            validation_warnings=validation_warnings or [],
            rejected=rejected,
            rejection_reason=rejection_reason,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            fallback_strategy=fallback_strategy,
            committed_event_ids=committed_event_ids or [],
            confidence=confidence,
            perspective_check_passed=perspective_check_passed,
            forbidden_info_detected=forbidden_info_detected or [],
        )
        self._store.store_proposal_audit(audit)
        return audit
    
    def get_store(self) -> AuditStore:
        """Get the underlying audit store."""
        return self._store


# Global audit logger instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get or create the global audit logger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def reset_audit_logger() -> None:
    """Reset the global audit logger (useful for testing)."""
    global _audit_logger
    _audit_logger = AuditLogger()
