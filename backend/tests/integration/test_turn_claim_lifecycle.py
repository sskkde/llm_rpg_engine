"""Lifecycle coverage for database-backed turn claims (SQLite by default, optional PG)."""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel, EventLogModel, LocationModel, SaveSlotModel, SessionModel, TurnTransactionModel,
    UserModel, WorldModel,
)
from llm_rpg.core.turn_claim import (
    ClaimStatus, ClaimRejected, create_or_resume_claim, expire_or_steal_claim,
    heartbeat_claim, abort_claim, compute_request_fingerprint,
)


@pytest.fixture

def db():
    pg_url = os.getenv("PHASE1_TEST_DATABASE_URL") if os.getenv("PHASE1_REQUIRE_POSTGRES") == "1" else None
    if os.getenv("PHASE1_REQUIRE_POSTGRES") == "1" and not pg_url:
        pytest.fail("PHASE1_REQUIRE_POSTGRES=1 requires PHASE1_TEST_DATABASE_URL")
    engine = create_engine(pg_url or "sqlite:///:memory:", **({} if pg_url else {
        "connect_args": {"check_same_thread": False}, "poolclass": StaticPool,
    }))
    if pg_url:
        assert engine.dialect.name == "postgresql"
    if not pg_url:
        Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    suffix = uuid.uuid4().hex
    user = UserModel(id=f"u-{suffix}", username=f"u-{suffix}", email=f"{suffix}@test.invalid", password_hash="x", is_admin=False)
    world = WorldModel(id=f"w-{suffix}", code=f"w-{suffix}", name="Test", genre="test", lore_summary="", status="active")
    session.add_all([user, world]); session.flush()
    chapter = ChapterModel(id=f"c-{suffix}", world_id=world.id, chapter_no=1, name="Test", summary="")
    slot = SaveSlotModel(id=f"s-{suffix}", user_id=user.id, slot_number=1, name="Test")
    session.add_all([chapter, slot]); session.flush()
    location = LocationModel(id=f"l-{suffix}", world_id=world.id, chapter_id=chapter.id, code="loc", name="Loc", tags=[], description="")
    session.add(location); session.flush()
    session_rows = []
    for i in range(2):
        row = SessionModel(id=f"session-{i}-{suffix}", user_id=user.id, world_id=world.id, save_slot_id=slot.id, status="active")
        session.add(row); session_rows.append(row)
    session.commit()
    session_ids = [row.id for row in session_rows]
    fixture_ids = (location.id, chapter.id, slot.id, world.id, user.id)
    yield session, session_ids, factory
    session.close()
    if pg_url:
        cleanup = factory()
        cleanup.query(TurnTransactionModel).filter(TurnTransactionModel.session_id.in_(session_ids)).delete(synchronize_session=False)
        cleanup.query(EventLogModel).filter(EventLogModel.session_id.in_(session_ids)).delete(synchronize_session=False)
        cleanup.query(SessionModel).filter(SessionModel.id.in_(session_ids)).delete(synchronize_session=False)
        location_id, chapter_id, slot_id, world_id, user_id = fixture_ids
        cleanup.query(LocationModel).filter_by(id=location_id).delete(synchronize_session=False)
        cleanup.query(ChapterModel).filter_by(id=chapter_id).delete(synchronize_session=False)
        cleanup.query(SaveSlotModel).filter_by(id=slot_id).delete(synchronize_session=False)
        cleanup.query(WorldModel).filter_by(id=world_id).delete(synchronize_session=False)
        cleanup.query(UserModel).filter_by(id=user_id).delete(synchronize_session=False)
        cleanup.commit()
        cleanup.close()
    engine.dispose()


def test_same_key_active_resume_and_conflict_is_non_mutating(db):
    session, ids, _factory = db
    first = create_or_resume_claim(session, ids[0], "k", "fp", 1)
    assert first.status is ClaimStatus.NEW
    second = create_or_resume_claim(session, ids[0], "k", "fp", 1)
    assert second.status is ClaimStatus.ACTIVE_CONFLICT
    assert session.query(TurnTransactionModel).filter_by(session_id=ids[0]).count() == 1
    before = session.query(TurnTransactionModel).filter_by(session_id=ids[0]).one()
    snapshot = (before.id, before.status, before.request_fingerprint, before.fencing_generation, before.lease_expires_at)
    conflict = create_or_resume_claim(session, ids[0], "k", "different", 1)
    assert conflict.status is ClaimStatus.FINGERPRINT_CONFLICT
    session.expire_all(); after = session.query(TurnTransactionModel).filter_by(session_id=ids[0]).one()
    assert (after.id, after.status, after.request_fingerprint, after.fencing_generation, after.lease_expires_at) == snapshot


def test_committed_same_key_resumes_and_session_key_scope_isolated(db):
    session, ids, _factory = db
    a = create_or_resume_claim(session, ids[0], "same", "fp", 1)
    row = session.get(TurnTransactionModel, a.token.transaction_id)
    row.status = "committed"; session.commit()
    resumed = create_or_resume_claim(session, ids[0], "same", "fp", 1)
    assert resumed.status is ClaimStatus.RESUME_COMMITTED
    b = create_or_resume_claim(session, ids[1], "same", "fp", 1)
    assert b.status is ClaimStatus.NEW
    assert a.token.transaction_id != b.token.transaction_id
    assert session.query(TurnTransactionModel).filter(TurnTransactionModel.session_id.in_(ids)).count() == 2


def test_another_key_conflicts_while_lease_active(db):
    session, ids, _factory = db
    assert create_or_resume_claim(session, ids[0], "one", "fp1", 1).status is ClaimStatus.NEW
    assert create_or_resume_claim(session, ids[0], "two", "fp2", 2).status is ClaimStatus.ACTIVE_CONFLICT
    assert session.query(TurnTransactionModel).filter_by(session_id=ids[0]).count() == 1


def test_steal_fences_old_token_and_records_attempt(db):
    session, ids, _factory = db
    old = create_or_resume_claim(session, ids[0], "old", "fp-old", 1).token
    row = session.get(TurnTransactionModel, old.transaction_id)
    session.query(TurnTransactionModel).filter_by(id=row.id).update({TurnTransactionModel.lease_expires_at: func.current_timestamp()})
    session.commit()
    # Set explicitly far in the past across both dialects.
    row.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1); session.commit()
    new = expire_or_steal_claim(session, ids[0], "new", "fp-new", 1)
    assert new.status is ClaimStatus.NEW
    assert new.token.generation == 2
    session.refresh(row)
    history = row.attempt_history_json
    assert history[-1]["idempotency_key"] == "old"
    assert history[-1]["request_fingerprint"] == "fp-old"
    assert history[-1]["generation"] == 1
    stable = (row.idempotency_key, row.request_fingerprint, row.fencing_generation, row.status, row.lease_expires_at, row.attempt_history_json)
    with pytest.raises(ClaimRejected): heartbeat_claim(session, old)
    with pytest.raises(ClaimRejected): abort_claim(session, old, {"error": "stale"})
    session.refresh(row)
    assert (row.idempotency_key, row.request_fingerprint, row.fencing_generation, row.status, row.lease_expires_at, row.attempt_history_json) == stable
    superseded = create_or_resume_claim(session, ids[0], "old", "fp-old", 1)
    assert superseded.status is ClaimStatus.SUPERSEDED


def test_fingerprint_is_stable_and_action_text_is_significant():
    assert compute_request_fingerprint("move", {"b": 2, "a": 1}) == compute_request_fingerprint("move", {"a": 1, "b": 2})
    assert compute_request_fingerprint("move", {"a": None, "b": [None, 1]}) == compute_request_fingerprint("move", {"b": [None, 1]})
    assert compute_request_fingerprint("move", {"x": 1}) == compute_request_fingerprint("move", {"x": 1})  # REST/SSE transport is not an input.
    assert compute_request_fingerprint("Move", {}) != compute_request_fingerprint("move", {})
    assert compute_request_fingerprint(" move ", {}) != compute_request_fingerprint("move", {})


def test_postgres_second_connection_observes_committed_active_claim(db):
    session, ids, factory = db
    if session.get_bind().dialect.name != "postgresql":
        pytest.skip("requires two PostgreSQL connections")
    first = create_or_resume_claim(session, ids[0], "pg-key", "pg-fp", 1)
    session.commit()
    second_session = factory()
    try:
        assert second_session.connection() is not session.connection()
        outcome = create_or_resume_claim(second_session, ids[0], "other-key", "other-fp", 2)
        assert outcome.status is ClaimStatus.ACTIVE_CONFLICT
        assert second_session.query(TurnTransactionModel).filter_by(session_id=ids[0]).count() == 1
    finally:
        second_session.close()


def test_expired_same_key_is_recomputed_and_fences_old_token(db):
    session, ids, _factory = db
    old = create_or_resume_claim(session, ids[0], "same-expired", "fp-old", 1).token
    row = session.get(TurnTransactionModel, old.transaction_id)
    row.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    session.commit()

    outcome = create_or_resume_claim(session, ids[0], "same-expired", "fp-old", 1)

    assert outcome.status is ClaimStatus.NEW
    assert outcome.token.generation == old.generation + 1
    assert outcome.token.transaction_id == old.transaction_id
    assert session.query(TurnTransactionModel).filter_by(session_id=ids[0], status="pending").count() == 1
    with pytest.raises(ClaimRejected):
        heartbeat_claim(session, old)


def test_expired_pending_with_player_turn_fact_is_only_resumed(db):
    session, ids, _factory = db
    original = create_or_resume_claim(session, ids[0], "fact-key", "fact-fp", 1)
    row = session.get(TurnTransactionModel, original.token.transaction_id)
    row.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    session.add(EventLogModel(
        session_id=ids[0], turn_no=1, event_type="player_turn", input_text="fact"
    ))
    session.commit()

    outcome = create_or_resume_claim(session, ids[0], "retry-key", "retry-fp", 1)

    assert outcome.status is ClaimStatus.RESUME_COMMITTED
    session.refresh(row)
    assert (row.idempotency_key, row.request_fingerprint, row.fencing_generation) == ("fact-key", "fact-fp", 1)
    assert session.query(TurnTransactionModel).filter_by(session_id=ids[0], status="pending").count() == 1


def test_expired_pending_is_reused_for_same_turn_and_records_history(db):
    session, ids, _factory = db
    old = create_or_resume_claim(session, ids[0], "old-key", "old-fp", 1).token
    row = session.get(TurnTransactionModel, old.transaction_id)
    row.error_json = {"category": "failed", "token": "must-not-leak"}
    row.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    session.commit()

    outcome = create_or_resume_claim(session, ids[0], "new-key", "new-fp", 1)

    assert outcome.status is ClaimStatus.NEW
    assert outcome.token.transaction_id == old.transaction_id
    assert outcome.token.generation == old.generation + 1
    session.refresh(row)
    assert (row.idempotency_key, row.request_fingerprint, row.turn_no) == ("new-key", "new-fp", 1)
    assert row.attempt_history_json[-1] == {
        "idempotency_key": "old-key", "request_fingerprint": "old-fp", "generation": 1,
        "error": {"category": "failed"},
    }
    assert session.query(TurnTransactionModel).filter_by(session_id=ids[0], status="pending").count() == 1


def test_expired_pending_is_reused_when_turn_number_changes(db):
    session, ids, _factory = db
    old = create_or_resume_claim(session, ids[0], "old-different-turn", "old-fp", 1).token
    row = session.get(TurnTransactionModel, old.transaction_id)
    row.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    session.commit()

    outcome = create_or_resume_claim(session, ids[0], "new-different-turn", "new-fp", 2)

    assert outcome.status is ClaimStatus.NEW
    assert outcome.token.transaction_id == old.transaction_id
    assert outcome.token.generation == old.generation + 1
    session.refresh(row)
    assert (row.idempotency_key, row.request_fingerprint, row.turn_no) == ("new-different-turn", "new-fp", 2)
    assert row.attempt_history_json[-1]["generation"] == old.generation
    assert session.query(TurnTransactionModel).filter_by(session_id=ids[0], status="pending").count() == 1
