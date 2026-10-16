"""Runtime adjudication of rows created before claim fingerprints were available."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from llm_rpg.core.turn_claim import ClaimStatus, create_or_resume_claim
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    EventLogModel,
    GameEventModel,
    SessionModel,
    TurnTransactionModel,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    game_session = SessionModel(id="legacy-session", user_id="user", world_id="world")
    session.add(game_session)
    session.flush()
    yield session, game_session.id
    session.close()
    engine.dispose()


def _claim(db, session_id, *, fingerprint="known-fingerprint", key="old-key", status="pending"):
    row = TurnTransactionModel(
        session_id=session_id,
        turn_no=1,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        lease_expires_at=datetime.now() - timedelta(days=1),
        fencing_generation=3,
        attempt_history_json=[],
        status=status,
        started_at=datetime.now() - timedelta(days=2),
    )
    db.add(row)
    db.flush()
    return row


def _snapshot(row):
    return (
        row.id,
        row.idempotency_key,
        row.request_fingerprint,
        row.fencing_generation,
        row.status,
    )


def test_aborted_claim_with_player_turn_is_only_resumed(db):
    session, session_id = db
    row = _claim(session, session_id, status="aborted")
    session.add(EventLogModel(
        session_id=session_id,
        turn_no=1,
        event_type="player_turn",
        input_text="already committed input",
    ))
    session.commit()
    before = _snapshot(row)

    outcome = create_or_resume_claim(session, session_id, "old-key", "known-fingerprint", 1)

    assert outcome.status is ClaimStatus.RESUME_COMMITTED
    session.refresh(row)
    assert _snapshot(row) == before


def test_old_pending_without_events_or_residue_is_marked_expired(db):
    session, session_id = db
    row = _claim(session, session_id, fingerprint=None)
    before_id, before_key, before_fp, before_generation, _ = _snapshot(row)
    session.commit()

    outcome = create_or_resume_claim(session, session_id, "replacement-key", "new-fingerprint", 1)

    assert outcome.status is ClaimStatus.EXPIRED
    session.refresh(row)
    assert session.query(TurnTransactionModel).filter_by(id=row.id).one()
    assert (row.id, row.idempotency_key, row.request_fingerprint, row.fencing_generation) == (
        before_id, before_key, before_fp, before_generation
    )
    assert row.status == "expired"


def test_pending_with_partial_game_event_is_not_taken_over_or_cleaned(db):
    session, session_id = db
    row = _claim(session, session_id)
    session.add(GameEventModel(
        transaction_id=row.id,
        session_id=session_id,
        turn_no=1,
        event_type="world_changed",
        occurred_at=datetime.now(),
    ))
    session.commit()
    before = _snapshot(row)

    outcome = create_or_resume_claim(session, session_id, "replacement-key", "new-fingerprint", 1)

    assert outcome.status is ClaimStatus.LEGACY_INCONSISTENT
    session.refresh(row)
    assert _snapshot(row) == before
    assert session.query(GameEventModel).filter_by(transaction_id=row.id).count() == 1


def test_null_fingerprint_same_key_is_rejected_as_legacy(db):
    session, session_id = db
    row = _claim(session, session_id, fingerprint=None)
    session.commit()
    before = _snapshot(row)

    outcome = create_or_resume_claim(session, session_id, "old-key", "cannot-verify", 1)

    assert outcome.status is ClaimStatus.LEGACY
    session.refresh(row)
    assert _snapshot(row) == before
