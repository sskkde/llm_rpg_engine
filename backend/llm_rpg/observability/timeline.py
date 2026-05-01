from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class TimelineEntryType(str, Enum):
    EVENT = "event"
    STATE_DELTA = "state_delta"
    MODEL_CALL = "model_call"
    CONTEXT_BUILD = "context_build"
    VALIDATION = "validation"
    MEMORY_SUMMARY = "memory_summary"


class TimelineEntry(BaseModel):
    entry_id: str
    entry_type: TimelineEntryType
    turn_no: int
    timestamp: datetime
    data: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        from_attributes = True


class TurnTimeline(BaseModel):
    turn_no: int
    session_id: str
    transaction_id: Optional[str] = None
    player_input: Optional[str] = None
    world_time_before: Optional[Dict[str, Any]] = None
    world_time_after: Optional[Dict[str, Any]] = None
    entries: List[TimelineEntry] = Field(default_factory=list)
    event_ids: List[str] = Field(default_factory=list)
    state_delta_ids: List[str] = Field(default_factory=list)
    model_call_ids: List[str] = Field(default_factory=list)
    context_build_ids: List[str] = Field(default_factory=list)
    validation_ids: List[str] = Field(default_factory=list)
    summary_ids: List[str] = Field(default_factory=list)
    status: str = "completed"
    narration_generated: bool = False
    narration_length: int = 0
    turn_duration_ms: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class TimelineViewer:
    def __init__(
        self,
        audit_logger=None,
        db_session=None,
    ):
        self.audit_logger = audit_logger
        self.db = db_session
        self._timeline_cache: Dict[str, List[TurnTimeline]] = {}
    
    def get_timeline(
        self,
        session_id: str,
        start_turn: int = 1,
        end_turn: Optional[int] = None,
    ) -> List[TurnTimeline]:
        from ..core.audit import get_audit_logger
        
        audit = self.audit_logger or get_audit_logger()
        store = audit.get_store()
        
        turn_audits = store.get_turn_audits_by_session(session_id, limit=1000)
        
        timelines = []
        for turn_audit in turn_audits:
            if turn_audit.turn_no < start_turn:
                continue
            if end_turn and turn_audit.turn_no > end_turn:
                continue
            
            timeline = self._build_turn_timeline(turn_audit, store)
            timelines.append(timeline)
        
        timelines.sort(key=lambda t: t.turn_no)
        return timelines
    
    def _build_turn_timeline(
        self,
        turn_audit,
        store,
    ) -> TurnTimeline:
        entries = []
        
        for event in turn_audit.events:
            entries.append(TimelineEntry(
                entry_id=event.event_id,
                entry_type=TimelineEntryType.EVENT,
                turn_no=turn_audit.turn_no,
                timestamp=turn_audit.started_at or datetime.now(),
                data={
                    "event_type": event.event_type,
                    "actor_id": event.actor_id,
                    "summary": event.summary,
                }
            ))
        
        for delta in turn_audit.state_deltas:
            entries.append(TimelineEntry(
                entry_id=delta.delta_id,
                entry_type=TimelineEntryType.STATE_DELTA,
                turn_no=turn_audit.turn_no,
                timestamp=turn_audit.started_at or datetime.now(),
                data={
                    "path": delta.path,
                    "old_value": delta.old_value,
                    "new_value": delta.new_value,
                    "operation": delta.operation,
                    "validated": delta.validated,
                }
            ))
        
        for call_id in turn_audit.model_call_ids:
            call = store.get_model_call(call_id)
            if call:
                entries.append(TimelineEntry(
                    entry_id=call.call_id,
                    entry_type=TimelineEntryType.MODEL_CALL,
                    turn_no=turn_audit.turn_no,
                    timestamp=call.created_at,
                    data={
                        "provider": call.provider,
                        "model_name": call.model_name,
                        "prompt_type": call.prompt_type,
                        "input_tokens": call.input_tokens,
                        "output_tokens": call.output_tokens,
                        "cost_estimate": call.cost_estimate,
                        "latency_ms": call.latency_ms,
                        "success": call.success,
                    }
                ))
        
        for build_id in turn_audit.context_build_ids:
            build = store.get_context_build(build_id)
            if build:
                entries.append(TimelineEntry(
                    entry_id=build.build_id,
                    entry_type=TimelineEntryType.CONTEXT_BUILD,
                    turn_no=turn_audit.turn_no,
                    timestamp=build.created_at,
                    data={
                        "perspective_type": build.perspective_type,
                        "perspective_id": build.perspective_id,
                        "owner_id": build.owner_id,
                        "included_count": build.included_count,
                        "excluded_count": build.excluded_count,
                        "total_candidates": build.total_candidates,
                        "context_token_count": build.context_token_count,
                    }
                ))
        
        for validation_id in turn_audit.validation_ids:
            validation = store.get_validation(validation_id)
            if validation:
                entries.append(TimelineEntry(
                    entry_id=validation.validation_id,
                    entry_type=TimelineEntryType.VALIDATION,
                    turn_no=turn_audit.turn_no,
                    timestamp=validation.created_at,
                    data={
                        "validation_target": validation.validation_target,
                        "target_id": validation.target_id,
                        "overall_status": validation.overall_status.value,
                        "error_count": validation.error_count,
                        "warning_count": validation.warning_count,
                    }
                ))
        
        entries.sort(key=lambda e: e.timestamp)
        
        return TurnTimeline(
            turn_no=turn_audit.turn_no,
            session_id=turn_audit.session_id,
            transaction_id=turn_audit.transaction_id,
            player_input=turn_audit.player_input,
            world_time_before=turn_audit.world_time_before,
            world_time_after=turn_audit.world_time_after,
            entries=entries,
            event_ids=[e.event_id for e in turn_audit.events],
            state_delta_ids=[d.delta_id for d in turn_audit.state_deltas],
            model_call_ids=list(turn_audit.model_call_ids),
            context_build_ids=list(turn_audit.context_build_ids),
            validation_ids=list(turn_audit.validation_ids),
            summary_ids=[],
            status=turn_audit.status,
            narration_generated=turn_audit.narration_generated,
            narration_length=turn_audit.narration_length,
            turn_duration_ms=turn_audit.turn_duration_ms,
            started_at=turn_audit.started_at,
            completed_at=turn_audit.completed_at,
        )
    
    def get_turn_summary(
        self,
        session_id: str,
        turn_no: int,
    ) -> Optional[TurnTimeline]:
        from ..core.audit import get_audit_logger
        
        audit = self.audit_logger or get_audit_logger()
        store = audit.get_store()
        
        turn_audit = store.get_turn_audit_by_turn(session_id, turn_no)
        if not turn_audit:
            return None
        
        return self._build_turn_timeline(turn_audit, store)
    
    def get_event_chain(
        self,
        session_id: str,
        event_type: Optional[str] = None,
        start_turn: int = 1,
        end_turn: Optional[int] = None,
    ) -> List[TimelineEntry]:
        timeline = self.get_timeline(session_id, start_turn, end_turn)
        
        events = []
        for turn in timeline:
            for entry in turn.entries:
                if entry.entry_type == TimelineEntryType.EVENT:
                    if event_type is None or entry.data.get("event_type") == event_type:
                        events.append(entry)
        
        return events
    
    def get_state_delta_chain(
        self,
        session_id: str,
        path_filter: Optional[str] = None,
        start_turn: int = 1,
        end_turn: Optional[int] = None,
    ) -> List[TimelineEntry]:
        timeline = self.get_timeline(session_id, start_turn, end_turn)
        
        deltas = []
        for turn in timeline:
            for entry in turn.entries:
                if entry.entry_type == TimelineEntryType.STATE_DELTA:
                    if path_filter is None or path_filter in entry.data.get("path", ""):
                        deltas.append(entry)
        
        return deltas
