"""Deferred turn writes: plan during preparation, apply in the final transaction.

Phase-one W2 (``.omo/plans/phase1-turn-foundation-completion.md`` §3 W2) splits
``execute_turn_service`` into a pure preparation section and a single authoritative
final transaction. This module holds the in-memory plan for the "event class" writes
that preparation used to perform directly:

* validation reports (``validation_reports``),
* game events (``game_events``),
* the turn's own event-log row (``event_logs``).

Why a buffer instead of writing straight away
---------------------------------------------
Any write performed during preparation opens a business transaction, takes row
locks, and is visible to the shared Session for the whole model-wait window. The
plan therefore keeps the rows as plain data until the final write section.

Pre-allocated primary keys
--------------------------
Every planned row gets its primary key up front (``storage.models.generate_uuid``)
exactly as the direct write did. The key is what makes the plan usable *before* it
is durable: later readers (``core.turn_service`` overlay parameters such as
``_get_recent_events(planned_events=...)``) see the same row identity the database
will hold, so "flush before you can read it" stops being an implicit dependency.
``flush`` honours the pre-allocated key, so the planned row and the durable row are
the same entity.

Field-for-field compatibility
-----------------------------
The dataclasses mirror the SQLAlchemy columns name for name, and ``flush`` passes
``dataclasses.asdict(plan)`` to the very same repositories (and, for the event log,
the very same ``turn_allocation.commit_turn`` helper) that the direct writes used.
The durable rows are therefore identical to the previous behaviour; only the moment
of the write moved.

Transaction ownership
---------------------
``flush`` refuses to run outside a managed turn unit of work: outside one, the
repositories would each commit on their own, which is exactly the per-write commit
that invariant R1 forbids for the authoritative turn path.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..storage.models import generate_uuid
from ..storage.repositories import GameEventRepository, ValidationReportRepository
from .turn_allocation import commit_turn
from .turn_unit_of_work import is_managed

logger = logging.getLogger(__name__)


class TurnWriteBufferError(RuntimeError):
    """Raised when a turn write buffer is used outside its contract."""


@dataclass
class PlannedValidationReport:
    """A ``validation_reports`` row planned during preparation."""

    id: str
    transaction_id: str
    session_id: str
    turn_no: int
    scope: str
    target_ref_id: Optional[str] = None
    is_valid: bool = True
    errors_json: Optional[List[str]] = None
    warnings_json: Optional[List[str]] = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class PlannedGameEvent:
    """A ``game_events`` row planned during preparation.

    Field names match ``GameEventModel`` columns so the projection builders in
    ``core.turn_service`` can consume a planned row exactly like a flushed one.
    """

    id: str
    transaction_id: str
    session_id: str
    turn_no: int
    event_type: str
    actor_id: Optional[str] = None
    target_ids_json: Optional[List[str]] = None
    visibility_scope: Optional[str] = "player_visible"
    public_payload_json: Optional[Dict[str, Any]] = None
    private_payload_json: Optional[Dict[str, Any]] = None
    result_json: Optional[Dict[str, Any]] = None
    occurred_at: datetime = field(default_factory=datetime.now)


@dataclass
class PlannedModelCallLog:
    """A model_call_logs row planned during preparation; columns mirror the model."""

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
    request_payload: Optional[Dict[str, Any]] = None
    response_payload: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class PlannedEventLog:
    """An ``event_logs`` row planned during preparation.

    ``turn_no`` / ``event_type`` / ``narrative_text`` / ``input_text`` are the fields
    ``_get_recent_events`` reads, so a plan can stand in for the row it will become.
    """

    id: str
    session_id: str
    turn_no: int
    event_type: str
    input_text: Optional[str] = None
    structured_action: Optional[Dict[str, Any]] = None
    result_json: Optional[Dict[str, Any]] = None
    narrative_text: Optional[str] = None


class TurnWriteBuffer:
    """Collects planned turn writes and applies them inside the final transaction.

    Rows are applied in the order they were planned, per table, which reproduces the
    insertion order of the direct writes they replace.
    """

    def __init__(self) -> None:
        self.validation_reports: List[PlannedValidationReport] = []
        self.game_events: List[PlannedGameEvent] = []
        self.event_logs: List[PlannedEventLog] = []
        self.model_call_logs: List[PlannedModelCallLog] = []
        #: Pre-allocated engine-event ids of the phase-3 advance, keyed by the
        #: engine's own sequence number. The advance decides its facts during
        #: preparation while their rows land in the final write section; the ids
        #: must already be visible to the stages that may only *reference* events
        #: the engine has decided (``_planned_game_event_ids``).
        self.phase3_event_ids: Dict[int, str] = {}
        self._flushed_event_logs: Dict[str, Any] = {}
        self._flushed = False

    # -- planning ---------------------------------------------------------------

    def add_validation_report(
        self,
        transaction_id: str,
        session_id: str,
        turn_no: int,
        scope: str,
        target_ref_id: Optional[str] = None,
        is_valid: bool = True,
        errors_json: Optional[List[str]] = None,
        warnings_json: Optional[List[str]] = None,
    ) -> str:
        """Plan a validation report; returns its pre-allocated id.

        Mirrors ``turn_service._create_validation_report`` (same fields, same
        defaults); only the write is deferred.
        """
        plan = PlannedValidationReport(
            id=generate_uuid(),
            transaction_id=transaction_id,
            session_id=session_id,
            turn_no=turn_no,
            scope=scope,
            target_ref_id=target_ref_id,
            is_valid=is_valid,
            errors_json=errors_json,
            warnings_json=warnings_json,
        )
        self.validation_reports.append(plan)
        return plan.id

    def add_game_event(
        self,
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
    ) -> str:
        """Plan a game event; returns its pre-allocated id.

        Mirrors ``turn_service._create_game_event``. The timestamp is captured now,
        at the same point in the turn where the direct write used to happen, so
        ``occurred_at`` ordering is unchanged.
        """
        plan = PlannedGameEvent(
            id=generate_uuid(),
            transaction_id=transaction_id,
            session_id=session_id,
            turn_no=turn_no,
            event_type=event_type,
            actor_id=actor_id,
            target_ids_json=target_ids,
            visibility_scope=visibility_scope,
            public_payload_json=public_payload,
            private_payload_json=private_payload,
            result_json=result_json,
        )
        self.game_events.append(plan)
        return plan.id

    def add_model_call_log(
        self, *, id: str, session_id: str, turn_no: int, provider: Optional[str],
        model_name: Optional[str], prompt_type: Optional[str],
        input_tokens: Optional[int], output_tokens: Optional[int],
        cost_estimate: Optional[float], latency_ms: Optional[int],
        request_payload: Optional[Dict[str, Any]],
        response_payload: Optional[Dict[str, Any]],
    ) -> str:
        """Buffer a model-call audit and return its stable primary key."""
        plan = PlannedModelCallLog(
            id=id, session_id=session_id, turn_no=turn_no, provider=provider,
            model_name=model_name, prompt_type=prompt_type,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cost_estimate=cost_estimate, latency_ms=latency_ms,
            request_payload=request_payload, response_payload=response_payload,
        )
        self.model_call_logs.append(plan)
        return plan.id

    def add_event_log(
        self,
        session_id: str,
        turn_no: int,
        event_type: str,
        input_text: Optional[str] = None,
        result_json: Optional[Dict[str, Any]] = None,
        narrative_text: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> PlannedEventLog:
        """Plan the turn's event-log row; returns the plan (with its id).

        Mirrors what ``turn_allocation.commit_turn`` persists, including the
        ``structured_action`` idempotency marker. The row itself is created by
        ``commit_turn`` from ``flush`` so its conflict/idempotency semantics are
        preserved, using the pre-allocated id as the row's primary key.
        """
        structured_action = {"idempotency_key": idempotency_key} if idempotency_key else None
        plan = PlannedEventLog(
            id=generate_uuid(),
            session_id=session_id,
            turn_no=turn_no,
            event_type=event_type,
            input_text=input_text,
            structured_action=structured_action,
            result_json=result_json,
            narrative_text=narrative_text,
        )
        self.event_logs.append(plan)
        return plan

    # -- context overlays -------------------------------------------------------

    def planned_event_logs(self) -> List[PlannedEventLog]:
        """Planned event-log rows, for readers that must see this turn's event."""
        return list(self.event_logs)

    def planned_game_events(self) -> List[PlannedGameEvent]:
        """Planned game events, for readers that must see this turn's events."""
        return list(self.game_events)

    # -- applying ---------------------------------------------------------------

    def flush(self, db: Session) -> Dict[str, Any]:
        """Materialise every planned row; returns ``{planned_id: event_log_row}``.

        Must be called from the final write section, before the single authoritative
        ``db.commit()``: inside the managed turn unit of work the repositories only
        flush, so the whole plan lands in one transaction and one commit.
        """
        if self._flushed:
            raise TurnWriteBufferError("TurnWriteBuffer.flush() may only run once per turn")
        if not is_managed(db):
            raise TurnWriteBufferError(
                "TurnWriteBuffer.flush() requires a managed turn unit of work; "
                "unmanaged repositories would commit each planned row separately"
            )
        self._flushed = True

        from ..storage.models import ModelCallLogModel
        for plan in self.model_call_logs:
            db.add(ModelCallLogModel(**asdict(plan)))
        if self.model_call_logs:
            db.flush()

        validation_report_repo = ValidationReportRepository(db)
        for plan in self.validation_reports:
            # Phase 2: this runs inside the managed turn unit of work, where a
            # necessary write failure must propagate so the whole turn rolls back.
            # Logging and continuing would let a turn commit with missing audit rows
            # and -- because the final write section also persists the claim CAS --
            # leave a durable turn whose audit trail is incomplete.
            validation_report_repo.create(asdict(plan))

        game_event_repo = GameEventRepository(db)
        for plan in self.game_events:
            # Same rule as ``turn_service._create_game_event``: a fact event is a
            # necessary write inside the managed transaction.
            game_event_repo.create(asdict(plan))

        for plan in self.event_logs:
            structured_action = plan.structured_action or {}
            self._flushed_event_logs[plan.id] = commit_turn(
                db=db,
                session_id=plan.session_id,
                turn_no=plan.turn_no,
                event_type=plan.event_type,
                input_text=plan.input_text,
                result_json=plan.result_json,
                narrative_text=plan.narrative_text,
                idempotency_key=structured_action.get("idempotency_key"),
                event_id=plan.id,
            )

        return self._flushed_event_logs

    def persist_failed_model_audits(self, bind, generation: int) -> None:
        """Persist failed-attempt audits in a separate, generation-tagged transaction."""
        if not self.model_call_logs:
            return
        import re
        from sqlalchemy.orm import sessionmaker
        from ..storage.models import ModelCallLogModel

        def scrub(value: Any) -> str:
            value = str(value)
            value = re.sub(
                r"(?i)(password|token|secret|authorization)\s*[:=]\s*\S+",
                r"\1=[REDACTED]", value,
            )
            return value[:1000]

        audit_db = sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)()
        try:
            for plan in self.model_call_logs:
                request_payload = {
                    "generation": generation,
                    "prompt": scrub((plan.request_payload or {}).get("prompt", "")),
                }
                response_payload = {
                    "generation": generation,
                    "content": scrub((plan.response_payload or {}).get("content", "")),
                }
                audit_db.add(ModelCallLogModel(
                    id=plan.id, session_id=plan.session_id, turn_no=plan.turn_no,
                    provider=plan.provider, model_name=plan.model_name,
                    prompt_type=plan.prompt_type, input_tokens=plan.input_tokens,
                    output_tokens=plan.output_tokens, cost_estimate=plan.cost_estimate,
                    latency_ms=plan.latency_ms, request_payload=request_payload,
                    response_payload=response_payload, created_at=plan.created_at,
                ))
            audit_db.commit()
        except Exception as exc:
            audit_db.rollback()
            logger.warning("Failed to persist generation-bound model audit: %s", exc)
        finally:
            audit_db.close()

    def flushed_event_log(self, planned_id: str) -> Any:
        """Return the durable row created for a planned event-log id."""
        if planned_id not in self._flushed_event_logs:
            raise TurnWriteBufferError(
                f"Planned event log {planned_id} has not been flushed yet"
            )
        return self._flushed_event_logs[planned_id]
