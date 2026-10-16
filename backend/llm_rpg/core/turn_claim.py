"""Short-lived, database-authoritative fencing primitives for turn claims.

Action text is deliberately significant: action casing and surrounding whitespace
are preserved in the request fingerprint contract. Transport/auth data is excluded.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Optional

from sqlalchemy import func, text, update
from sqlalchemy.orm import Session

from .turn_concurrency import acquire_turn_lock
from ..storage.models import EventLogModel, GameEventModel, StateDeltaModel, TurnTransactionModel

HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("TURN_CLAIM_HEARTBEAT_INTERVAL_SECONDS", "15"))
LEASE_SECONDS = int(os.getenv("TURN_CLAIM_LEASE_SECONDS", "90"))


class ClaimStatus(str, Enum):
    NEW = "new"
    RESUME_COMMITTED = "resume_committed"
    FINGERPRINT_CONFLICT = "fingerprint_conflict"
    ACTIVE_CONFLICT = "active_conflict"
    SUPERSEDED = "superseded"
    LEGACY_INCONSISTENT = "legacy_inconsistent"
    LEGACY = "legacy"
    EXPIRED = "expired"


@dataclass(frozen=True)
class ClaimToken:
    transaction_id: str
    generation: int
    session_id: str
    idempotency_key: str
    request_fingerprint: str
    turn_no: int


@dataclass(frozen=True)
class ClaimOutcome:
    status: ClaimStatus
    token: Optional[ClaimToken] = None


class ClaimRejected(RuntimeError):
    """Token lost its lease, was fenced, or no longer names a pending row."""


def compute_request_fingerprint(
    action: str, structured_params: Optional[dict], protocol_version: str = "v1"
) -> str:
    """Hash stable normalized structured input; transport and credentials are absent."""
    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(value[key]) for key in sorted(value) if value[key] is not None}
        if isinstance(value, list):
            return [normalize(item) for item in value if item is not None]
        return value

    payload = {"protocol_version": protocol_version, "action": action,
               "structured_params": normalize(structured_params or {})}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def db_now(db: Session) -> datetime:
    """Read authoritative database clock (never use application time for decisions).

    PostgreSQL uses ``clock_timestamp()`` (statement time) rather than ``now()``
    (transaction start time), so lease issue, renewal, comparison and the commit
    timestamp all reflect the real moment even inside a long-running transaction.
    SQLite keeps its explicit test clock.
    """
    dialect = db.get_bind().dialect.name
    statement = "SELECT clock_timestamp()" if dialect == "postgresql" else "SELECT CURRENT_TIMESTAMP"
    value = db.execute(text(statement)).scalar_one()
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=None) if value.tzinfo else value


def _lock_session(db: Session, session_id: str) -> None:
    # Session-scoped advisory lock precedes all transaction-row reads/writes.
    acquire_turn_lock(db, session_id, timeout_seconds=0)


def _token(row: TurnTransactionModel) -> ClaimToken:
    return ClaimToken(row.id, int(row.fencing_generation or 1), row.session_id,
                      row.idempotency_key, row.request_fingerprint or "", row.turn_no)


def _expired(row: TurnTransactionModel, now: datetime) -> bool:
    return row.lease_expires_at is not None and row.lease_expires_at <= now


def _adjudicate_history(db: Session, row: TurnTransactionModel) -> Optional[ClaimOutcome]:
    """Resolve persisted effects before any retry/takeover can mutate a historical claim."""
    # Deliberately preserve W1 legacy adjudication: a player_turn at this claimed
    # number is authoritative even when the transaction marker/key is stale. The
    # service now assigns numbers only after taking the per-session lock, removing
    # the stale-number collision path that could expose a competitor's result.
    player_turn = db.query(EventLogModel.id).filter_by(
        session_id=row.session_id, turn_no=row.turn_no, event_type="player_turn"
    ).first()
    if player_turn:
        return ClaimOutcome(ClaimStatus.RESUME_COMMITTED, _token(row))

    # Residue means any transaction-linked or same-turn game/state write, or any
    # event_log other than the player_turn marker. Such partial effects are
    # evidence to stop for manual inspection, never grounds for replay/cleanup.
    residue = (
        db.query(GameEventModel.id).filter(
            (GameEventModel.transaction_id == row.id)
            | ((GameEventModel.session_id == row.session_id) & (GameEventModel.turn_no == row.turn_no))
        ).first()
        or db.query(StateDeltaModel.id).filter(
            (StateDeltaModel.transaction_id == row.id)
            | ((StateDeltaModel.session_id == row.session_id) & (StateDeltaModel.turn_no == row.turn_no))
        ).first()
        or db.query(EventLogModel.id).filter(
            EventLogModel.session_id == row.session_id,
            EventLogModel.turn_no == row.turn_no,
            EventLogModel.event_type != "player_turn",
        ).first()
    )
    if residue:
        return ClaimOutcome(ClaimStatus.LEGACY_INCONSISTENT)
    return None


def create_or_resume_claim(
    db: Session, session_id: str, idempotency_key: str, request_fingerprint: str,
    turn_no: Optional[int] = None, now: Optional[datetime] = None,
) -> ClaimOutcome:
    """Create or classify a key under the per-session lock; caller owns commit/rollback."""
    _lock_session(db, session_id)
    current = now or db_now(db)
    if turn_no is None:
        max_turn = db.query(func.max(EventLogModel.turn_no)).filter(
            EventLogModel.session_id == session_id
        ).scalar()
        turn_no = (max_turn or 0) + 1
    rows = db.query(TurnTransactionModel).filter_by(session_id=session_id).with_for_update().all()
    for row in rows:
        history = row.attempt_history_json or []
        if row.idempotency_key != idempotency_key and any(item.get("idempotency_key") == idempotency_key for item in history):
            return ClaimOutcome(ClaimStatus.SUPERSEDED)
    same = next((row for row in rows if row.idempotency_key == idempotency_key), None)
    if same:
        if same.request_fingerprint is not None and same.request_fingerprint != request_fingerprint:
            return ClaimOutcome(ClaimStatus.FINGERPRINT_CONFLICT)
        adjudication = _adjudicate_history(db, same)
        if adjudication is not None:
            return adjudication
        if same.request_fingerprint is None:
            # Same-key input cannot be checked against a pre-fingerprint row.
            return ClaimOutcome(ClaimStatus.LEGACY)
        if same.status == "committed":
            return ClaimOutcome(ClaimStatus.RESUME_COMMITTED, _token(same))
    for row in rows:
        if row.turn_no != turn_no:
            continue
        adjudication = _adjudicate_history(db, row)
        if adjudication is not None:
            return adjudication
    active = next((row for row in rows if row.status == "pending" and not _expired(row, current)), None)
    if active:
        return ClaimOutcome(ClaimStatus.ACTIVE_CONFLICT)
    occupied = next((row for row in rows if row.turn_no == turn_no and row.status == "committed"), None)
    if occupied:
        committed_fact = db.query(EventLogModel.id).filter_by(
            session_id=session_id, turn_no=turn_no, event_type="player_turn"
        ).first()
        return ClaimOutcome(
            ClaimStatus.RESUME_COMMITTED if committed_fact else ClaimStatus.LEGACY_INCONSISTENT,
            _token(occupied) if committed_fact else None,
        )
    expired_pending = next((row for row in rows if row.status == "pending" and _expired(row, current)), None)
    if expired_pending:
        adjudication = _adjudicate_history(db, expired_pending)
        if adjudication is not None:
            return adjudication
        if expired_pending.request_fingerprint is None:
            # Pre-fingerprint rows cannot be safely retried with a different key;
            # no recorded effects means safely retire the lease without deleting or rekeying.
            expired_pending.status = "expired"
            db.flush()
            return ClaimOutcome(ClaimStatus.EXPIRED)
        return _takeover_expired_claim(
            db, expired_pending, session_id, idempotency_key, request_fingerprint, turn_no, current
        )
    if same:
        # Aborted claims may safely be retried in place; expired pending claims use explicit steal API.
        if same.status == "aborted":
            result = db.execute(update(TurnTransactionModel).where(
                TurnTransactionModel.id == same.id, TurnTransactionModel.session_id == session_id,
                TurnTransactionModel.idempotency_key == idempotency_key,
                TurnTransactionModel.request_fingerprint == request_fingerprint,
                TurnTransactionModel.fencing_generation == same.fencing_generation,
                TurnTransactionModel.status == "aborted",
            ).values(status="pending", lease_expires_at=current + timedelta(seconds=LEASE_SECONDS),
                     fencing_generation=(same.fencing_generation or 0) + 1, aborted_at=None,
                     error_json=None).execution_options(synchronize_session=False))
            if result.rowcount != 1:
                raise ClaimRejected("claim retry CAS failed")
            db.expire(same); db.refresh(same)
            return ClaimOutcome(ClaimStatus.NEW, _token(same))
        return ClaimOutcome(ClaimStatus.ACTIVE_CONFLICT)
    aborted = next((row for row in rows if row.status == "aborted" and row.turn_no == turn_no), None)
    if aborted:
        history = list(aborted.attempt_history_json or [])
        history.append({"idempotency_key": aborted.idempotency_key,
                        "request_fingerprint": aborted.request_fingerprint,
                        "generation": aborted.fencing_generation,
                        "error": _sanitize_error(aborted.error_json or {"category": "aborted"})})
        result = db.execute(update(TurnTransactionModel).where(
            TurnTransactionModel.id == aborted.id, TurnTransactionModel.session_id == session_id,
            TurnTransactionModel.idempotency_key == aborted.idempotency_key,
            TurnTransactionModel.request_fingerprint == aborted.request_fingerprint,
            TurnTransactionModel.turn_no == aborted.turn_no,
            TurnTransactionModel.fencing_generation == aborted.fencing_generation,
            TurnTransactionModel.status == "aborted",
        ).values(idempotency_key=idempotency_key, request_fingerprint=request_fingerprint,
                 fencing_generation=(aborted.fencing_generation or 0) + 1,
                 lease_expires_at=current + timedelta(seconds=LEASE_SECONDS),
                 attempt_history_json=history, status="pending", started_at=current,
                 aborted_at=None, error_json=None).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise ClaimRejected("aborted claim takeover CAS failed")
        db.expire(aborted); db.refresh(aborted)
        return ClaimOutcome(ClaimStatus.NEW, _token(aborted))
    row = TurnTransactionModel(
        session_id=session_id, turn_no=turn_no, idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        lease_expires_at=current + timedelta(seconds=LEASE_SECONDS), fencing_generation=1,
        attempt_history_json=[], status="pending", started_at=current,
    )
    db.add(row)
    db.flush()
    return ClaimOutcome(ClaimStatus.NEW, _token(row))


def _cas_token(db: Session, token: ClaimToken, values: dict | Callable[[datetime], dict], *, require_live: bool = True) -> None:
    _lock_session(db, token.session_id)
    current = db_now(db)
    if callable(values):
        values = values(current)
    stmt = update(TurnTransactionModel).where(
        TurnTransactionModel.id == token.transaction_id,
        TurnTransactionModel.session_id == token.session_id,
        TurnTransactionModel.idempotency_key == token.idempotency_key,
        TurnTransactionModel.request_fingerprint == token.request_fingerprint,
        TurnTransactionModel.turn_no == token.turn_no,
        TurnTransactionModel.fencing_generation == token.generation,
        TurnTransactionModel.status == "pending",
    )
    if require_live:
        # Evaluate lease validity at UPDATE execution time, not against the earlier
        # Python-bound db_now() value (which may become stale while the worker pauses).
        lease_clock = func.clock_timestamp() if db.get_bind().dialect.name == "postgresql" else func.current_timestamp()
        stmt = stmt.where(TurnTransactionModel.lease_expires_at > lease_clock)
    result = db.execute(stmt.values(**values))
    if result.rowcount != 1:
        raise ClaimRejected("claim token CAS rejected")


def heartbeat_claim(db: Session, token: ClaimToken) -> None:
    _cas_token(db, token, lambda current: {"lease_expires_at": current + timedelta(seconds=LEASE_SECONDS)})


def commit_claim(db: Session, token: ClaimToken, *, world_time_after: Optional[str] = None) -> None:
    """CAS the claim row to committed inside the caller's authoritative transaction.

    The update matches the full token (transaction id, session, idempotency key,
    request fingerprint, turn number and fencing generation) and still requires the
    row to be ``pending`` under a live lease, so a superseded worker can never mark a
    claim it no longer owns. The caller owns the transaction: a rejection rolls the
    whole turn back instead of leaving a partial commit.
    """
    _cas_token(db, token, lambda current: {
        "status": "committed",
        "committed_at": current,
        "world_time_after": world_time_after,
    })


def _sanitize_error(error_info) -> dict:
    """Keep only short safe diagnostic fields; omit arbitrary exception text/secrets."""
    if isinstance(error_info, dict):
        allowed = {key: value for key, value in error_info.items() if key in {"code", "category", "type"}}
        return {str(k)[:40]: re.sub(r"(?i)(password|token|secret|authorization)\s*[:=]\s*\S+", r"\1=[REDACTED]", str(v))[:160]
                for k, v in allowed.items()}
    return {"category": type(error_info).__name__[:80]}


def abort_claim(db: Session, token: ClaimToken, error_info) -> None:
    safe_error = _sanitize_error(error_info)
    _cas_token(db, token, lambda current: {"status": "aborted", "aborted_at": current,
                                          "lease_expires_at": current, "error_json": safe_error})


def _takeover_expired_claim(
    db: Session, row: TurnTransactionModel, session_id: str, idempotency_key: str,
    request_fingerprint: str, turn_no: int, current: datetime,
) -> ClaimOutcome:
    history = list(row.attempt_history_json or [])
    history.append({"idempotency_key": row.idempotency_key, "request_fingerprint": row.request_fingerprint,
                    "generation": row.fencing_generation,
                    "error": _sanitize_error(row.error_json or {"category": "lease_expired"})})
    result = db.execute(update(TurnTransactionModel).where(
        TurnTransactionModel.id == row.id, TurnTransactionModel.session_id == session_id,
        TurnTransactionModel.idempotency_key == row.idempotency_key,
        TurnTransactionModel.request_fingerprint == row.request_fingerprint,
        TurnTransactionModel.turn_no == row.turn_no,
        TurnTransactionModel.fencing_generation == row.fencing_generation,
        TurnTransactionModel.status == "pending", TurnTransactionModel.lease_expires_at <= current,
    ).values(idempotency_key=idempotency_key, request_fingerprint=request_fingerprint,
             turn_no=turn_no, fencing_generation=(row.fencing_generation or 0) + 1,
             lease_expires_at=current + timedelta(seconds=LEASE_SECONDS), attempt_history_json=history,
             started_at=current, aborted_at=None, error_json=None).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise ClaimRejected("expired claim takeover CAS failed")
    db.expire(row)
    db.refresh(row)
    return ClaimOutcome(ClaimStatus.NEW, _token(row))


def expire_or_steal_claim(
    db: Session, session_id: str, idempotency_key: str, request_fingerprint: str, turn_no: int,
) -> ClaimOutcome:
    """Explicit takeover API sharing create_or_resume_claim's expired-row CAS semantics."""
    _lock_session(db, session_id)
    current = db_now(db)
    row = db.query(TurnTransactionModel).filter_by(session_id=session_id, status="pending").order_by(TurnTransactionModel.turn_no.desc()).with_for_update().first()
    if row is None or row.lease_expires_at is None or row.lease_expires_at > current:
        return ClaimOutcome(ClaimStatus.ACTIVE_CONFLICT)
    adjudication = _adjudicate_history(db, row)
    if adjudication is not None:
        return adjudication
    if row.request_fingerprint is None:
        row.status = "expired"
        db.flush()
        return ClaimOutcome(ClaimStatus.EXPIRED)
    return _takeover_expired_claim(db, row, session_id, idempotency_key, request_fingerprint, turn_no, current)
