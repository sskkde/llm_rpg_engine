"""W1b coverage: the service-level turn budget and the server-owned request fingerprint.

Two phase-1 completion gaps are pinned here (`.omo/plans/phase1-turn-foundation-completion.md`
§3 W1, §4.1/§4.8; design `.omo/evidence/phase1/20261015-p1-completion/w1-design.md` §2.3/§2.4):

1. ``TurnBudget`` existed in ``core/turn_claim_runtime.py`` but was never wired into
   ``execute_turn_service``: a turn that overran the service deadline still committed its
   facts, and the heartbeat renewed the lease forever.
2. ``execute_turn_service`` adjudicated the **client-supplied** ``request_fingerprint``,
   so a caller could send one forged value for two different inputs under the same
   idempotency key and turn a same-key/different-input conflict into a silent replay of
   the earlier turn.

Every assertion reads durable rows (claim row, event log, game events, state deltas)
rather than helper exceptions or HTTP status alone. SQLite with the mock provider is
sufficient for both: neither the budget nor the fingerprint needs real concurrency. The
complementary control — that a small heartbeat interval really does renew the lease —
lives in ``test_turn_claim_service_fencing.py`` (PostgreSQL, independent connections).
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import NamedTuple

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.core import turn_claim, turn_service
from llm_rpg.core.turn_claim import compute_request_fingerprint
from llm_rpg.core.turn_claim_runtime import TurnBudget
from llm_rpg.core.turn_service import (
    TurnBudgetExceededError,
    TurnClaimConflictError,
    execute_turn_service,
)
from llm_rpg.core.turn_unit_of_work import TurnUnitOfWork
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel,
    EventLogModel,
    GameEventModel,
    LocationModel,
    SaveSlotModel,
    SessionModel,
    SessionStateModel,
    StateDeltaModel,
    TurnTransactionModel,
    UserModel,
    WorldModel,
)

pytestmark = pytest.mark.integration


class Wired(NamedTuple):
    """One seeded in-memory database plus the session under test."""

    db: Session
    session_id: str
    user_id: str
    engine: Engine
    session_factory: sessionmaker


@pytest.fixture
def wired():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
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
    yield Wired(db=db, session_id=session.id, user_id=user.id, engine=engine, session_factory=factory)
    db.close()
    engine.dispose()


@pytest.fixture
def client(wired, monkeypatch):
    """TestClient bound to the same in-memory database as ``wired``."""
    from fastapi.testclient import TestClient

    from llm_rpg.api import streaming
    from llm_rpg.api.auth import get_current_active_user
    from llm_rpg.main import app
    from llm_rpg.storage.database import get_db

    monkeypatch.setattr(streaming, "SessionLocal", wired.session_factory)

    def override_get_db():
        session = wired.session_factory()
        try:
            yield session
        finally:
            session.close()

    def override_current_user():
        return UserModel(
            id=wired.user_id, username="w1b", email="w1b@test.invalid",
            password_hash="x", is_admin=False,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = override_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _durable_state(db: Session, session_id: str) -> dict:
    """Snapshot every fact row a turn could write, read from a fresh transaction."""
    db.rollback()
    session_state = db.query(SessionStateModel).filter_by(session_id=session_id).one_or_none()
    return {
        "player_turn_events": db.query(EventLogModel).filter_by(
            session_id=session_id, event_type="player_turn"
        ).count(),
        "event_logs": db.query(EventLogModel).filter_by(session_id=session_id).count(),
        "game_events": db.query(GameEventModel).filter_by(session_id=session_id).count(),
        "state_deltas": db.query(StateDeltaModel).filter_by(session_id=session_id).count(),
        "claims": db.query(TurnTransactionModel).filter_by(session_id=session_id).count(),
        "current_time": None if session_state is None else session_state.current_time,
    }


def _claim_row(db: Session, session_id: str, idempotency_key: str) -> TurnTransactionModel:
    db.rollback()
    return db.query(TurnTransactionModel).filter_by(
        session_id=session_id, idempotency_key=idempotency_key
    ).one()


def _raw_lease(db: Session, session_id: str):
    """Read the lease straight from SQL so a stale identity map cannot hide a renewal."""
    return db.execute(
        text("SELECT lease_expires_at FROM turn_transactions WHERE session_id = :sid"),
        {"sid": session_id},
    ).scalar_one()


def _install_slow_llm_stage(monkeypatch, db, session_id, block_seconds, samples) -> None:
    """Block the turn inside its model-call position while sampling the raw lease."""
    original = turn_service._execute_input_intent_stage

    def slow_stage(*args, **kwargs):
        samples.append(_raw_lease(db, session_id))
        time.sleep(block_seconds)
        samples.append(_raw_lease(db, session_id))
        return original(*args, **kwargs)

    monkeypatch.setattr(turn_service, "_execute_input_intent_stage", slow_stage)


class _CountingBudget(TurnBudget):
    """Budget that records how often ``expired()`` was consulted, and by which thread."""

    def __init__(self, total_seconds: float) -> None:
        super().__init__(total_seconds)
        self.expired_checks = 0
        self.check_threads: set = set()
        self._lock = threading.Lock()

    def expired(self) -> bool:
        with self._lock:
            self.expired_checks += 1
            self.check_threads.add(threading.current_thread().name)
        return super().expired()


# --------------------------------------------------------------------------------------
# 1. Request fingerprint: the client value never adjudicates.
# --------------------------------------------------------------------------------------


def test_forged_client_fingerprint_cannot_bypass_same_key_conflict(wired):
    """A forged client fingerprint must not turn a conflict into a silent replay.

    The same idempotency key is used for two different inputs, and the caller sends the
    *same* client fingerprint both times. On the pre-W1b behaviour the second call matched
    the stored client value, was classified ``resume_committed`` and returned the first
    turn's result for the second input without any conflict. The service must instead
    recompute the fingerprint from the authoritative input and reject the request.
    """
    db, session_id = wired.db, wired.session_id
    forged_client_value = "canonical-shared-by-the-client"

    first = execute_turn_service(
        db, session_id, "look around", idempotency_key="forged-fingerprint-key",
        request_fingerprint=forged_client_value, use_mock=True,
    )
    assert first.turn_no == 1
    stored = _claim_row(db, session_id, "forged-fingerprint-key")
    assert stored.request_fingerprint == compute_request_fingerprint("look around", None), (
        "the claim row must store the server-recomputed fingerprint, never the client value"
    )
    assert stored.request_fingerprint != forged_client_value

    before = _durable_state(db, session_id)
    with pytest.raises(TurnClaimConflictError) as exc:
        execute_turn_service(
            db, session_id, "go north", idempotency_key="forged-fingerprint-key",
            request_fingerprint=forged_client_value, use_mock=True,
        )
    after = _durable_state(db, session_id)

    assert exc.value.code == "fingerprint_conflict", (
        "a forged client fingerprint made a same-key/different-input request look like a "
        f"retry; observed code={exc.value.code!r}"
    )
    assert after == before, (
        f"the rejected request wrote durable state: before={before} after={after}"
    )
    assert after["player_turn_events"] == 1


def test_same_key_same_input_recovery_ignores_client_fingerprint(wired):
    """Legitimate same-key recovery stays read-only and does not trust the client value."""
    db, session_id = wired.db, wired.session_id

    first = execute_turn_service(
        db, session_id, "look around", idempotency_key="recovery-fingerprint-key",
        request_fingerprint="client-value-one", use_mock=True,
    )
    before = _durable_state(db, session_id)
    second = execute_turn_service(
        db, session_id, "look around", idempotency_key="recovery-fingerprint-key",
        request_fingerprint="client-value-two-different", use_mock=True,
    )
    after = _durable_state(db, session_id)

    assert second.turn_no == first.turn_no == 1
    assert second.transaction_id == first.transaction_id, (
        "same-key recovery must reuse the persisted snapshot of the same turn"
    )
    assert after == before, (
        f"same-key recovery must be read-only: before={before} after={after}"
    )
    assert after["player_turn_events"] == 1


# --------------------------------------------------------------------------------------
# 2. Service budget: an expired budget refuses the uncommitted turn.
# --------------------------------------------------------------------------------------


def test_expired_budget_refuses_uncommitted_turn_and_stops_renewals(wired, monkeypatch):
    """A turn that overran its service budget must not commit, and must stop renewing.

    The budget is expired from the start (``total_seconds=0``) while the heartbeat runs
    on a deliberately tiny interval, so the renewing thread really does wake up during
    the blocked model call — it just must not renew. The lease is sampled straight from
    SQL on both sides of the block.
    """
    db, session_id = wired.db, wired.session_id
    # A tiny interval plus a lease long enough to stay valid proves the heartbeat had
    # every opportunity to renew and chose not to.
    monkeypatch.setattr(turn_claim, "HEARTBEAT_INTERVAL_SECONDS", 0.05)
    budget = _CountingBudget(total_seconds=0)
    samples: list = []
    _install_slow_llm_stage(monkeypatch, db, session_id, 0.5, samples)

    with pytest.raises(TurnBudgetExceededError) as exc:
        execute_turn_service(
            db, session_id, "look around", idempotency_key="budget-key",
            claim_budget=budget, use_mock=True,
        )

    assert exc.value.code == "turn_budget_exceeded"
    assert exc.value.session_id == session_id

    state = _durable_state(db, session_id)
    claim = _claim_row(db, session_id, "budget-key")
    observed = (
        f"error={exc.value!r} claim_status={claim.status} lease={claim.lease_expires_at} "
        f"durable={state} lease_samples={samples} expired_checks={budget.expired_checks} "
        f"check_threads={sorted(budget.check_threads)}"
    )

    assert state["player_turn_events"] == 0, (
        "the over-budget turn committed a player_turn fact row; " + observed
    )
    assert state["game_events"] == 0 and state["state_deltas"] == 0, (
        "the over-budget turn left partial game/state writes behind; " + observed
    )
    assert claim.status != "committed", (
        "the over-budget turn marked its claim committed; " + observed
    )
    assert len(samples) == 2 and samples[0] is not None, (
        "the harness never sampled the lease on both sides of the blocked model call; "
        + observed
    )
    assert samples[0] == samples[1], (
        "the lease was renewed while the service budget was already exhausted; " + observed
    )
    assert budget.expired_checks >= 2, (
        "the heartbeat thread never consulted the budget, so this run does not show that "
        "the budget is what stopped the renewals; " + observed
    )
    assert len(budget.check_threads) >= 2, (
        "only the turn thread checked the budget; the renewing thread never woke up; "
        + observed
    )


def test_turn_within_budget_commits_normally(wired):
    """Guard: the budget wiring must not disturb a turn that finishes in time."""
    db, session_id = wired.db, wired.session_id

    result = execute_turn_service(
        db, session_id, "look around", idempotency_key="in-budget-key",
        claim_budget=TurnBudget(total_seconds=600), use_mock=True,
    )

    state = _durable_state(db, session_id)
    claim = _claim_row(db, session_id, "in-budget-key")
    assert result.turn_no == 1
    assert result.recovery_status == "complete"
    assert state["player_turn_events"] == 1
    assert claim.status == "committed"

    # The same must hold for the default budget used by both HTTP channels.
    default_budget_result = execute_turn_service(
        db, session_id, "look around", idempotency_key="default-budget-key", use_mock=True,
    )
    assert default_budget_result.turn_no == 2
    assert _claim_row(db, session_id, "default-budget-key").status == "committed"


# --------------------------------------------------------------------------------------
# 3. Failure path: an uncertain commit receipt is confirmed by query, never guessed.
# --------------------------------------------------------------------------------------


def test_uncertain_commit_receipt_is_confirmed_by_query_not_blind_abort(wired, monkeypatch):
    """When ``db.commit()`` raises after the facts became durable, confirm by query.

    The wrapper commits for real and then loses the receipt (raises). Marking the claim
    aborted or replaying the turn here would hide committed facts behind an aborted row
    and invite a duplicate turn, so the service must re-read the claim row and take the
    read-only recovery path.
    """
    db, session_id = wired.db, wired.session_id
    original_allow_commit = TurnUnitOfWork.allow_commit
    real_commit: dict = {}

    def allow_commit_with_lost_receipt(self):
        original_allow_commit(self)
        bound_commit = self.db.commit
        real_commit["bound"] = bound_commit

        def commit_then_fail():
            bound_commit()  # durable facts; only the receipt to the caller is lost
            raise RuntimeError("commit receipt lost")

        self.db.commit = commit_then_fail

    monkeypatch.setattr(TurnUnitOfWork, "allow_commit", allow_commit_with_lost_receipt)

    result = execute_turn_service(
        db, session_id, "look around", idempotency_key="lost-receipt-key", use_mock=True,
    )
    db.commit = real_commit["bound"]  # restore the session for the assertions below

    state = _durable_state(db, session_id)
    claim = _claim_row(db, session_id, "lost-receipt-key")
    observed = f"result={result!r} claim_status={claim.status} durable={state}"

    assert result.turn_no == 1, observed
    assert result.recovery_status == "complete", (
        "the uncertain commit receipt did not take the read-only recovery path; " + observed
    )
    assert claim.status == "committed", (
        "the claim row was aborted although the facts had been committed; " + observed
    )
    assert state["player_turn_events"] == 1, (
        "the recovery path must reuse the persisted snapshot, not replay the turn; " + observed
    )


# --------------------------------------------------------------------------------------
# 4. API mapping: structured timeout on both channels, no uncommitted success payload.
# --------------------------------------------------------------------------------------


def test_budget_error_maps_to_rest_504_and_sse_error_event(wired, client, monkeypatch):
    """REST answers 504 with the structured code; SSE emits one error event and ends."""
    from llm_rpg.api import game, streaming

    def raise_budget_error(*args, **kwargs):
        raise TurnBudgetExceededError(
            session_id=wired.session_id, turn_no=1, total_seconds=0.0
        )

    monkeypatch.setattr(game, "execute_turn_service", raise_budget_error)
    monkeypatch.setattr(streaming, "execute_turn_service", raise_budget_error)

    rest = client.post(
        f"/game/sessions/{wired.session_id}/turn",
        json={"action": "观察四周", "idempotency_key": "budget-mapping-key"},
    )
    assert rest.status_code == 504, rest.text
    assert rest.json()["detail"]["code"] == "turn_budget_exceeded"
    assert "Turn budget exceeded" in rest.json()["detail"]["message"]

    with client.stream(
        "POST",
        f"/streaming/sessions/{wired.session_id}/turn/mock",
        json={"action": "观察四周", "idempotency_key": "budget-mapping-key"},
    ) as response:
        body = "".join(response.iter_text())
        assert response.status_code == 200

    assert "event: error" in body, body
    assert '"code": "turn_budget_exceeded"' in body, body
    assert "event: turn_completed" not in body, body
