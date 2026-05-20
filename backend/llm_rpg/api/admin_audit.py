"""
Admin Audit API routes for LLM RPG Engine.

Provides admin-only read endpoints for audit logs, model calls, context builds,
validations, errors, and data export.
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
    UserModel, SessionModel, EventLogModel, ModelCallAuditLogModel,
    ContextBuildAuditLogModel, ValidationAuditLogModel, ErrorAuditLogModel
)
from .auth import get_current_active_user

router = APIRouter(prefix="/admin/audit", tags=["admin-audit"])


# =============================================================================
# Helper Functions
# =============================================================================

async def require_admin(
    current_user: UserModel = Depends(get_current_active_user)
) -> UserModel:
    """
    Dependency to require admin role.

    Raises:
        HTTPException: If user is not an admin
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


def derive_severity_from_event_type(event_type: str) -> Optional[str]:
    """Derive severity level from event type."""
    error_types = ["error", "validation_error", "system_error", "critical"]
    warning_types = ["warning", "validation_warning"]
    
    event_lower = event_type.lower()
    if any(et in event_lower for et in error_types):
        return "high"
    if any(wt in event_lower for wt in warning_types):
        return "medium"
    return "low"


# =============================================================================
# Pydantic Models
# =============================================================================

class AuditSessionLog(BaseModel):
    """Session log entry for admin audit."""
    id: str
    event_type: str
    turn_no: int
    severity: Optional[str] = None
    narrative_text: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    """Paginated response for session logs."""
    total: int
    items: List[AuditSessionLog]


class ModelCallSummary(BaseModel):
    """Model call summary for admin audit."""
    id: str
    model_name: Optional[str] = None
    prompt_type: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    cost_estimate: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ModelCallListResponse(BaseModel):
    """Paginated response for model calls."""
    total: int
    items: List[ModelCallSummary]


class ContextBuildSummary(BaseModel):
    """Context build summary for admin audit."""
    id: str
    turn_no: int
    perspective_type: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ContextBuildListResponse(BaseModel):
    """Paginated response for context builds."""
    total: int
    items: List[ContextBuildSummary]


class ValidationSummary(BaseModel):
    """Validation summary for admin audit."""
    id: str
    turn_no: int
    validation_type: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ValidationListResponse(BaseModel):
    """Paginated response for validations."""
    total: int
    items: List[ValidationSummary]


class AuditErrorLog(BaseModel):
    """Error log entry for admin audit."""
    id: str
    error_type: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ErrorListResponse(BaseModel):
    """Paginated response for errors."""
    total: int
    items: List[AuditErrorLog]


class ExportEntry(BaseModel):
    """Export entry for JSONL-ready format."""
    timestamp: datetime
    event_type: str
    turn_no: Optional[int] = None
    data: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/sessions/{session_id}/logs", response_model=AuditLogListResponse)
def list_session_logs(
    session_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    event_type: Optional[str] = Query(None),
    turn_no: Optional[int] = Query(None),
    from_turn: Optional[int] = Query(None, description="Filter by minimum turn number"),
    to_turn: Optional[int] = Query(None, description="Filter by maximum turn number"),
    severity: Optional[str] = Query(None),
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get session event logs with pagination and filters.

    Returns paginated event logs for a specific session.
    Supports filtering by event_type, turn_no, from_turn, to_turn, and severity.
    Requires admin role.
    """
    # Verify session exists
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Build query with filters
    query = db.query(EventLogModel).filter(EventLogModel.session_id == session_id)
    
    if event_type:
        query = query.filter(EventLogModel.event_type == event_type)
    
    if turn_no is not None:
        query = query.filter(EventLogModel.turn_no == turn_no)
    
    if from_turn is not None:
        query = query.filter(EventLogModel.turn_no >= from_turn)
    
    if to_turn is not None:
        query = query.filter(EventLogModel.turn_no <= to_turn)

    # Get total count
    total = query.count()

    # Get paginated results
    logs = query.order_by(
        desc(EventLogModel.turn_no), 
        desc(EventLogModel.occurred_at)
    ).offset(skip).limit(limit).all()

    # Build response with derived severity
    items = []
    for log in logs:
        derived_severity = derive_severity_from_event_type(log.event_type)
        # Apply severity filter if specified
        if severity and derived_severity != severity:
            continue
        items.append(AuditSessionLog(
            id=log.id,
            event_type=log.event_type,
            turn_no=log.turn_no,
            severity=derived_severity,
            narrative_text=log.narrative_text,
            created_at=log.occurred_at
        ))

    # Recalculate total if severity filter was applied
    if severity:
        total = len(items)

    return AuditLogListResponse(total=total, items=items)


@router.get("/sessions/{session_id}/model-calls", response_model=ModelCallListResponse)
def list_model_calls(
    session_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get model call audit logs for a session.

    Returns paginated model call summaries.
    NEVER exposes API keys or raw prompts that contain secrets.
    Requires admin role.
    """
    # Verify session exists
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Query model call audit logs
    query = db.query(ModelCallAuditLogModel).filter(
        ModelCallAuditLogModel.session_id == session_id
    )

    total = query.count()

    calls = query.order_by(
        desc(ModelCallAuditLogModel.created_at)
    ).offset(skip).limit(limit).all()

    items = [
        ModelCallSummary(
            id=call.call_id,
            model_name=call.model_name,
            prompt_type=call.prompt_type,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            latency_ms=call.latency_ms,
            cost_estimate=call.cost_estimate,
            created_at=call.created_at
        )
        for call in calls
    ]

    return ModelCallListResponse(total=total, items=items)


@router.get("/sessions/{session_id}/context-builds", response_model=ContextBuildListResponse)
def list_context_builds(
    session_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get context build audit logs for a session.

    Returns paginated context build summaries.
    Requires admin role.
    """
    # Verify session exists
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Query context build audit logs
    query = db.query(ContextBuildAuditLogModel).filter(
        ContextBuildAuditLogModel.session_id == session_id
    )

    total = query.count()

    builds = query.order_by(
        desc(ContextBuildAuditLogModel.created_at)
    ).offset(skip).limit(limit).all()

    items = [
        ContextBuildSummary(
            id=build.build_id,
            turn_no=build.turn_no,
            perspective_type=build.perspective_type,
            created_at=build.created_at
        )
        for build in builds
    ]

    return ContextBuildListResponse(total=total, items=items)


@router.get("/sessions/{session_id}/validations", response_model=ValidationListResponse)
def list_validations(
    session_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get validation audit logs for a session.

    Returns paginated validation summaries.
    Requires admin role.
    """
    # Verify session exists
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Query validation audit logs
    query = db.query(ValidationAuditLogModel).filter(
        ValidationAuditLogModel.session_id == session_id
    )

    total = query.count()

    validations = query.order_by(
        desc(ValidationAuditLogModel.created_at)
    ).offset(skip).limit(limit).all()

    items = [
        ValidationSummary(
            id=val.validation_id,
            turn_no=val.turn_no,
            validation_type=val.validation_type,
            created_at=val.created_at
        )
        for val in validations
    ]

    return ValidationListResponse(total=total, items=items)


@router.get("/sessions/{session_id}/errors", response_model=ErrorListResponse)
def list_errors(
    session_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    event_type: Optional[str] = Query(None),
    turn_no: Optional[int] = Query(None),
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get error audit logs for a session.

    Returns paginated error entries.
    Supports filtering by event_type and turn_no.
    Requires admin role.
    """
    # Verify session exists
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Query error audit logs
    query = db.query(ErrorAuditLogModel).filter(
        ErrorAuditLogModel.session_id == session_id
    )

    if event_type:
        query = query.filter(ErrorAuditLogModel.error_type == event_type)

    total = query.count()

    errors = query.order_by(
        desc(ErrorAuditLogModel.created_at)
    ).offset(skip).limit(limit).all()

    items = [
        AuditErrorLog(
            id=err.error_id,
            error_type=err.error_type,
            created_at=err.created_at
        )
        for err in errors
    ]

    # Apply turn_no filter from payload_json if specified
    if turn_no is not None:
        filtered_items = []
        for err in errors:
            payload = err.payload_json or {}
            if payload.get("turn_no") == turn_no:
                filtered_items.append(AuditErrorLog(
                    id=err.error_id,
                    error_type=err.error_type,
                    created_at=err.created_at
                ))
        items = filtered_items
        total = len(items)

    return ErrorListResponse(total=total, items=items)


@router.get("/export", response_model=List[ExportEntry])
def export_audit_data(
    session_id: Optional[str] = Query(None),
    from_turn: Optional[int] = Query(None),
    to_turn: Optional[int] = Query(None),
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Export session audit data as JSONL-ready format.

    Returns array of objects with timestamp, event_type, turn_no, and data.
    No API keys or secrets in export.
    Requires admin role.
    """
    entries: List[ExportEntry] = []

    # Export event logs
    event_query = db.query(EventLogModel)
    if session_id:
        event_query = event_query.filter(EventLogModel.session_id == session_id)
    if from_turn is not None:
        event_query = event_query.filter(EventLogModel.turn_no >= from_turn)
    if to_turn is not None:
        event_query = event_query.filter(EventLogModel.turn_no <= to_turn)

    event_logs = event_query.order_by(EventLogModel.occurred_at).all()

    for log in event_logs:
        # Build safe data dict (exclude sensitive fields)
        safe_data = {
            "session_id": log.session_id,
            "event_type": log.event_type,
        }
        if log.input_text:
            # Truncate potentially long input
            safe_data["input_preview"] = log.input_text[:200] if len(log.input_text) > 200 else log.input_text
        if log.narrative_text:
            safe_data["narrative_preview"] = log.narrative_text[:200] if len(log.narrative_text) > 200 else log.narrative_text

        entries.append(ExportEntry(
            timestamp=log.occurred_at,
            event_type=log.event_type,
            turn_no=log.turn_no,
            data=safe_data
        ))

    # Export model call audit logs
    model_query = db.query(ModelCallAuditLogModel)
    if session_id:
        model_query = model_query.filter(ModelCallAuditLogModel.session_id == session_id)
    if from_turn is not None:
        model_query = model_query.filter(ModelCallAuditLogModel.turn_no >= from_turn)
    if to_turn is not None:
        model_query = model_query.filter(ModelCallAuditLogModel.turn_no <= to_turn)

    model_calls = model_query.order_by(ModelCallAuditLogModel.created_at).all()

    for call in model_calls:
        # Build safe data dict (NEVER expose API keys)
        safe_data = {
            "session_id": call.session_id,
            "provider": call.provider,
            "model_name": call.model_name,
            "prompt_type": call.prompt_type,
            "input_tokens": call.input_tokens,
            "output_tokens": call.output_tokens,
            "total_tokens": call.total_tokens,
            "cost_estimate": call.cost_estimate,
            "latency_ms": call.latency_ms,
            "success": call.success,
        }

        entries.append(ExportEntry(
            timestamp=call.created_at,
            event_type="model_call",
            turn_no=call.turn_no,
            data=safe_data
        ))

    # Sort all entries by timestamp
    entries.sort(key=lambda e: e.timestamp)

    return entries
