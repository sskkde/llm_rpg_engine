"""Service-level wiring coverage for durable turn claims."""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.core.turn_claim import create_or_resume_claim, compute_request_fingerprint
from llm_rpg.core.turn_service import (
    TurnClaimConflictError, TurnRecoveryIncompleteError, execute_turn_service,
)
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel, EventLogModel, LocationModel, SaveSlotModel, SessionModel,
    TurnTransactionModel, UserModel, WorldModel,
)


@pytest.fixture
def wired_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    suffix = uuid.uuid4().hex
    user = UserModel(id=f"u-{suffix}", username=f"u-{suffix}", email=f"{suffix}@test.invalid", password_hash="x", is_admin=False)
    world = WorldModel(id=f"w-{suffix}", code=f"w-{suffix}", name="Test", genre="test", lore_summary="", status="active")
    db.add_all([user, world]); db.flush()
    chapter = ChapterModel(id=f"c-{suffix}", world_id=world.id, chapter_no=1, name="Test", summary="")
    slot = SaveSlotModel(id=f"s-{suffix}", user_id=user.id, slot_number=1, name="Test")
    db.add_all([chapter, slot]); db.flush()
    location = LocationModel(id=f"l-{suffix}", world_id=world.id, chapter_id=chapter.id, code="loc", name="Loc", tags=[], description="")
    session = SessionModel(id=f"session-{suffix}", user_id=user.id, world_id=world.id, save_slot_id=slot.id, current_chapter_id=chapter.id, status="active")
    db.add_all([location, session]); db.commit()
    yield db, session.id
    db.close(); engine.dispose()


def test_same_key_retry_resumes_without_new_event(wired_db):
    db, session_id = wired_db
    first = execute_turn_service(db, session_id, "look around", idempotency_key="retry-key", use_mock=True)
    before = db.query(EventLogModel).filter_by(session_id=session_id).count()
    second = execute_turn_service(db, session_id, "look around", idempotency_key="retry-key", use_mock=True)
    assert second.turn_no == first.turn_no
    assert db.query(EventLogModel).filter_by(session_id=session_id).count() == before
    assert db.query(TurnTransactionModel).filter_by(session_id=session_id).count() == 1


def test_unkeyed_claim_uses_uuid_key(wired_db):
    db, session_id = wired_db
    execute_turn_service(db, session_id, "look around", use_mock=True)
    claim = db.query(TurnTransactionModel).filter_by(session_id=session_id).one()
    assert claim.idempotency_key == str(uuid.UUID(claim.idempotency_key))
    assert not claim.idempotency_key.startswith("auto_")


def test_same_key_different_fingerprint_is_conflict_without_side_effect(wired_db):
    db, session_id = wired_db
    execute_turn_service(db, session_id, "look around", idempotency_key="fingerprint-key", use_mock=True)
    before_events = db.query(EventLogModel).filter_by(session_id=session_id).count()
    before_claims = db.query(TurnTransactionModel).filter_by(session_id=session_id).count()
    with pytest.raises(TurnClaimConflictError) as exc:
        execute_turn_service(db, session_id, "go north", idempotency_key="fingerprint-key", use_mock=True)
    assert exc.value.code == "fingerprint_conflict"
    assert db.query(EventLogModel).filter_by(session_id=session_id).count() == before_events
    assert db.query(TurnTransactionModel).filter_by(session_id=session_id).count() == before_claims


def test_other_active_claim_blocks_before_business_execution(wired_db, monkeypatch):
    import llm_rpg.core.turn_service as service
    db, session_id = wired_db
    fp = compute_request_fingerprint("look around", None)
    outcome = create_or_resume_claim(db, session_id, "active-key", fp, 1)
    db.commit()
    called = False
    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("business preparation must not run")
    monkeypatch.setattr(service, "initialize_session_story_state", forbidden)
    with pytest.raises(TurnClaimConflictError) as exc:
        service.execute_turn_service(db, session_id, "different input", use_mock=True)
    assert exc.value.code == "turn_in_progress"
    assert called is False
    assert db.query(TurnTransactionModel).filter_by(session_id=session_id).count() == 1


def test_committed_claim_without_event_is_explicit_and_not_duplicated(wired_db):
    db, session_id = wired_db
    outcome = create_or_resume_claim(
        db, session_id, "committed-without-event", compute_request_fingerprint("old", None), 1
    )
    db.query(TurnTransactionModel).filter_by(id=outcome.token.transaction_id).update({"status": "committed"})
    db.commit()

    with pytest.raises(TurnClaimConflictError) as exc:
        execute_turn_service(db, session_id, "new input", use_mock=True)

    assert exc.value.code == "legacy_inconsistent"
    rows = db.query(TurnTransactionModel).filter_by(session_id=session_id, turn_no=1).all()
    assert len(rows) == 1
    assert db.query(EventLogModel).filter_by(session_id=session_id, event_type="player_turn").count() == 0


def test_same_key_committed_claim_without_event_never_returns_none(wired_db):
    db, session_id = wired_db
    outcome = create_or_resume_claim(
        db, session_id, "missing-event", compute_request_fingerprint("old", None), 1
    )
    db.query(TurnTransactionModel).filter_by(id=outcome.token.transaction_id).update({"status": "committed"})
    db.commit()

    with pytest.raises(TurnRecoveryIncompleteError) as exc:
        execute_turn_service(db, session_id, "old", idempotency_key="missing-event", use_mock=True)

    assert exc.value.code == "recovery_incomplete"
    assert db.query(TurnTransactionModel).filter_by(session_id=session_id).count() == 1


def test_preflight_failure_aborts_claim(wired_db, monkeypatch):
    import llm_rpg.core.turn_service as service
    db, session_id = wired_db
    def fail(_db):
        raise RuntimeError("preflight failure")
    monkeypatch.setattr(service, "_validate_explicit_llm_config", fail)
    with pytest.raises(RuntimeError, match="preflight failure"):
        service.execute_turn_service(db, session_id, "look around", idempotency_key="preflight-key")
    row = db.query(TurnTransactionModel).filter_by(session_id=session_id).one()
    assert row.status == "aborted"
    assert row.error_json == {"category": "preparation_failed", "type": "RuntimeError"}
