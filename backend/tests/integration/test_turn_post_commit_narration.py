"""Post-commit narration boundary for the phase-1 completion plan (W0 red test).

Target design (`.omo/plans/phase1-turn-foundation-completion.md` §3 W4):
- The narration model call must happen **after** the authoritative fact commit,
  consuming only this turn's frozen, whitelisted context.
- The presentation CAS may only rewrite the presentation allowlist; fact fields
  in the stored snapshot must never change.
- Same-key recovery is read-only: it must not re-invoke the narration stage.
- A failed/blocked presentation finalize keeps the template and never undoes facts.

Status after the phase-1 completion waves: the narration stage is invoked after the
authoritative fact commit (observed order `['fact_commit_boundary', 'narration_stage']`),
so all five tests below pass. The ordering assertion remains as the regression guard
for that boundary.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.core import turn_service as service
from llm_rpg.core.turn_claim import ClaimToken
from llm_rpg.core.turn_service import (
    LLMStageResult,
    _finalize_turn_presentation,
    execute_turn_service,
)
from llm_rpg.core.turn_unit_of_work import TurnUnitOfWork
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel,
    EventLogModel,
    LocationModel,
    SaveSlotModel,
    SessionModel,
    TurnTransactionModel,
    UserModel,
    WorldModel,
)


@pytest.fixture
def wired_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    suffix = uuid.uuid4().hex
    user = UserModel(
        id=f"u-{suffix}", username=f"u-{suffix}", email=f"{suffix}@test.invalid",
        password_hash="x", is_admin=False,
    )
    world = WorldModel(
        id=f"w-{suffix}", code=f"w-{suffix}", name="Test", genre="test",
        lore_summary="", status="active",
    )
    db.add_all([user, world])
    db.flush()
    chapter = ChapterModel(id=f"c-{suffix}", world_id=world.id, chapter_no=1, name="Test", summary="")
    slot = SaveSlotModel(id=f"s-{suffix}", user_id=user.id, slot_number=1, name="Test")
    db.add_all([chapter, slot])
    db.flush()
    location = LocationModel(
        id=f"l-{suffix}", world_id=world.id, chapter_id=chapter.id, code="loc",
        name="Loc", tags=[], description="",
    )
    session = SessionModel(
        id=f"session-{suffix}", user_id=user.id, world_id=world.id,
        save_slot_id=slot.id, current_chapter_id=chapter.id, status="active",
    )
    db.add_all([location, session])
    db.commit()
    yield db, session.id
    db.close()
    engine.dispose()


def _narration_stage_recorder(events):
    """Record the narration stage invocation, then behave like a disabled stage."""

    def _record(*args, **kwargs):
        events.append("narration_stage")
        return LLMStageResult(
            stage_name="narration",
            enabled=False,
            timeout=30.0,
            accepted=False,
            fallback_reason="test_stub_disabled",
        )

    return _record


def test_narration_stage_call_happens_after_fact_commit(wired_db, monkeypatch):
    db, session_id = wired_db
    events = []

    monkeypatch.setattr(service, "_execute_narration_stage", _narration_stage_recorder(events))

    original_allow_commit = TurnUnitOfWork.allow_commit

    def _record_allow_commit(self):
        # allow_commit() is the last step before the single authoritative db.commit().
        events.append("fact_commit_boundary")
        return original_allow_commit(self)

    monkeypatch.setattr(TurnUnitOfWork, "allow_commit", _record_allow_commit)

    execute_turn_service(
        db, session_id, "look around", idempotency_key="narration-order", use_mock=True
    )

    assert "narration_stage" in events, (
        "the narration stage must still be reached in this flow; observed order: %r" % (events,)
    )
    assert "fact_commit_boundary" in events, (
        "the authoritative fact commit must happen; observed order: %r" % (events,)
    )
    assert events.index("narration_stage") > events.index("fact_commit_boundary"), (
        "narration model call must happen AFTER the authoritative fact commit; "
        "observed order: %r" % (events,)
    )


def test_same_key_recovery_does_not_call_narration_again(wired_db, monkeypatch):
    db, session_id = wired_db
    events = []
    monkeypatch.setattr(service, "_execute_narration_stage", _narration_stage_recorder(events))

    first = execute_turn_service(
        db, session_id, "look around", idempotency_key="narration-recovery", use_mock=True
    )
    calls_after_first = events.count("narration_stage")
    assert calls_after_first >= 1

    second = execute_turn_service(
        db, session_id, "look around", idempotency_key="narration-recovery", use_mock=True
    )

    assert second.turn_no == first.turn_no
    assert events.count("narration_stage") == calls_after_first, (
        "same-key recovery must be read-only and must not re-invoke the narration stage"
    )


def _seed_committed_turn(db, session_id, generation=2):
    txn = TurnTransactionModel(
        session_id=session_id,
        turn_no=1,
        idempotency_key="presentation-key",
        request_fingerprint="fp",
        lease_expires_at=None,
        fencing_generation=generation,
        attempt_history_json=[],
        status="committed",
        started_at=datetime.now(),
    )
    db.add(txn)
    db.flush()

    snapshot = {
        "version": 1,
        "turn_no": 1,
        "narration": "template text",
        "presentation_status": "template",
        "presentation_version": 0,
        "generation": generation,
        "transaction_id": txn.id,
        "recommended_actions": ["template-action"],
        "state_deltas": {"fact": "keep-me"},
        "world_time": {"day": 3, "period": "morning", "minute": 0},
        "events_committed": 1,
        "actions_committed": 1,
    }
    event = EventLogModel(
        session_id=session_id,
        turn_no=1,
        event_type="player_turn",
        result_json={
            "narration": "template text",
            "recommended_actions": ["template-action"],
            "presentation_status": "template",
            "presentation_version": 0,
            "turn_result_v1": snapshot,
        },
        narrative_text="template text",
    )
    db.add(event)
    db.commit()
    return txn, event


def test_presentation_cas_rejects_stale_generation_without_touching_facts(wired_db):
    db, session_id = wired_db
    txn, event = _seed_committed_turn(db, session_id, generation=2)

    stale_token = ClaimToken(
        transaction_id=txn.id,
        generation=1,  # stale generation: this worker was fenced
        session_id=session_id,
        idempotency_key="presentation-key",
        request_fingerprint="fp",
        turn_no=1,
    )
    before = db.query(EventLogModel).filter_by(id=event.id).one().result_json

    assert _finalize_turn_presentation(db, event.id, stale_token, "stale narration", ["stale"]) is False

    after = db.query(EventLogModel).filter_by(id=event.id).one().result_json
    assert after == before, "a fenced worker must not change any stored field"


def test_presentation_cas_updates_only_allowlisted_fields(wired_db):
    db, session_id = wired_db
    txn, event = _seed_committed_turn(db, session_id, generation=2)

    token = ClaimToken(
        transaction_id=txn.id,
        generation=2,
        session_id=session_id,
        idempotency_key="presentation-key",
        request_fingerprint="fp",
        turn_no=1,
    )

    assert _finalize_turn_presentation(db, event.id, token, "final narration", ["final-action"]) is True

    stored = db.query(EventLogModel).filter_by(id=event.id).one().result_json
    assert stored["narration"] == "final narration"
    assert stored["recommended_actions"] == ["final-action"]
    assert stored["presentation_status"] == "finalized"
    assert stored["presentation_version"] == 1

    snapshot = stored["turn_result_v1"]
    assert snapshot["narration"] == "final narration"
    assert snapshot["presentation_status"] == "finalized"
    assert snapshot["state_deltas"] == {"fact": "keep-me"}
    assert snapshot["world_time"] == {"day": 3, "period": "morning", "minute": 0}
    assert snapshot["events_committed"] == 1
    assert snapshot["actions_committed"] == 1


def test_narration_finalize_failure_keeps_template_and_facts(wired_db, monkeypatch):
    db, session_id = wired_db

    monkeypatch.setattr(service, "_finalize_turn_presentation", lambda *a, **k: False)

    result = execute_turn_service(
        db, session_id, "look around", idempotency_key="narration-fail", use_mock=True
    )

    assert result.recovery_status == "complete"
    assert result.presentation_version == 0

    stored = (
        db.query(EventLogModel)
        .filter_by(session_id=session_id, event_type="player_turn")
        .one()
        .result_json
    )
    assert stored["presentation_status"] == "template"
    assert stored["turn_result_v1"]["presentation_status"] == "template"
    assert stored["events_committed"] == 1
