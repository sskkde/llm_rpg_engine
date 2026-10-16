"""W0 red-light coverage: the final fact commit is not fenced by the turn claim.

These tests drive the real production entry point ``execute_turn_service()`` against
PostgreSQL with genuinely independent connections and a real background worker thread.

They exist to expose two production gaps in the phase-1 turn foundation:

1. ``execute_turn_service()`` releases the claim lock in its short claim transaction
   (``core/turn_service.py`` — claim then ``db.commit()``) and never re-validates the
   claim token afterwards. The final fact commit calls
   ``TurnTransactionRepository.update_status(transaction_id, status="committed")``,
   which updates the row **by primary key only** — no ``fencing_generation``, lease or
   owner check. A worker whose lease expired and whose claim was taken over by another
   worker therefore still commits its facts and overwrites the successor's claim row.
2. ``heartbeat_claim()`` in ``core/turn_claim.py`` has **no production caller**: the
   lease is written once at claim time and never renewed while the worker sits in a
   long model call.

Every assertion here reads database rows (never only helper exceptions or HTTP status),
so a green result cannot be produced by unit-level fencing primitives alone.

PostgreSQL is mandatory for the acceptance run: without ``PHASE1_TEST_DATABASE_URL``
the module skips, and with ``PHASE1_REQUIRE_POSTGRES=1`` a missing URL fails hard
instead of silently degrading to SQLite.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Optional

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from llm_rpg.core import turn_service
from llm_rpg.core.turn_claim import (
    ClaimRejected,
    ClaimStatus,
    compute_request_fingerprint,
    expire_or_steal_claim,
)
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel,
    EventLogModel,
    GameEventModel,
    LocationModel,
    SaveSlotModel,
    SessionModel,
    TurnTransactionModel,
    UserModel,
    WorldModel,
)

pytestmark = pytest.mark.integration

# The worker thread must reach the LLM stage quickly; the harness must never be the
# reason a run hangs.
_ENTRY_TIMEOUT_SECONDS = 30.0
_RELEASE_TIMEOUT_SECONDS = 30.0
_WORKER_JOIN_TIMEOUT_SECONDS = 180.0
# Bound row-lock waits so a harness mistake fails loudly instead of hanging the suite.
_LOCK_TIMEOUT = "20s"


@pytest.fixture
def pg_turn_env():
    """Isolated PostgreSQL schema plus independent session factory (see test_turn_postgres_foundation)."""
    required = os.getenv("PHASE1_REQUIRE_POSTGRES") == "1"
    raw_url = os.getenv("PHASE1_TEST_DATABASE_URL")
    if required and not raw_url:
        pytest.fail("PHASE1_REQUIRE_POSTGRES=1 requires PHASE1_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("turn claim fencing tests require PHASE1_TEST_DATABASE_URL")
    base_url = make_url(raw_url)
    if base_url.get_backend_name() != "postgresql":
        pytest.fail("PHASE1_TEST_DATABASE_URL must use PostgreSQL")
    assert base_url.drivername == "postgresql+psycopg2", "acceptance URL must explicitly use psycopg2"

    schema = "turn_fencing_" + uuid.uuid4().hex
    admin_engine = create_engine(base_url)
    with admin_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = base_url.update_query_dict({"options": f"-csearch_path={schema},public"})
    engine = create_engine(isolated_url, pool_size=8, max_overflow=4)
    assert engine.dialect.name == "postgresql"
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    suffix = uuid.uuid4().hex
    db = factory()
    user = UserModel(id=f"u-{suffix}", username=f"u-{suffix}", email=f"{suffix}@test.invalid", password_hash="x", is_admin=False)
    world = WorldModel(id=f"w-{suffix}", code=f"w-{suffix}", name="Test", genre="test", status="active")
    db.add_all([user, world])
    db.flush()
    chapter = ChapterModel(id=f"c-{suffix}", world_id=world.id, chapter_no=1, name="Test", summary="")
    slot = SaveSlotModel(id=f"s-{suffix}", user_id=user.id, slot_number=1, name="Test")
    db.add_all([chapter, slot])
    db.flush()
    location = LocationModel(id=f"l-{suffix}", world_id=world.id, chapter_id=chapter.id, code="loc", name="Loc", tags=[], description="")
    session = SessionModel(id=f"session-{suffix}", user_id=user.id, world_id=world.id, save_slot_id=slot.id, current_chapter_id=chapter.id, status="active")
    db.add_all([location, session])
    db.commit()
    session_id = session.id
    db.close()

    yield engine, factory, session_id

    engine.dispose()
    try:
        with admin_engine.begin() as conn:
            # Mirror test_turn_postgres_foundation: URL-level search_path isolation can leave
            # rows in the public schema, so clean both places. Deletion order follows the
            # foreign keys onto turn_transactions (llm_stage_results, validation_reports) and
            # onto event_logs (memory_facts).
            conn.execute(text("DELETE FROM llm_stage_results WHERE transaction_id IN (SELECT id FROM turn_transactions WHERE session_id = :sid)"), {"sid": session_id})
            conn.execute(text("DELETE FROM validation_reports WHERE transaction_id IN (SELECT id FROM turn_transactions WHERE session_id = :sid)"), {"sid": session_id})
            conn.execute(text("DELETE FROM state_deltas WHERE session_id = :sid"), {"sid": session_id})
            conn.execute(text("DELETE FROM game_events WHERE session_id = :sid"), {"sid": session_id})
            conn.execute(text("DELETE FROM memory_facts WHERE session_id = :sid"), {"sid": session_id})
            conn.execute(text("DELETE FROM event_logs WHERE session_id = :sid"), {"sid": session_id})
            conn.execute(text("DELETE FROM turn_transactions WHERE session_id = :sid"), {"sid": session_id})
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def _install_blocking_llm_stage(monkeypatch, entered: threading.Event, release: threading.Event) -> None:
    """Block the real worker inside the model-call position of execute_turn_service.

    The call site resolves ``_execute_input_intent_stage`` through the module global, so
    patching the module attribute intercepts the production path without touching it.
    """
    original = turn_service._execute_input_intent_stage

    def blocking_stage(*args, **kwargs):
        entered.set()
        if not release.wait(timeout=_RELEASE_TIMEOUT_SECONDS):
            raise AssertionError("harness never released the blocked LLM stage")
        return original(*args, **kwargs)

    monkeypatch.setattr(turn_service, "_execute_input_intent_stage", blocking_stage)


def _start_worker(factory, session_id: str, action: str, idempotency_key: str):
    """Run one full execute_turn_service turn in a background thread with its own session."""
    errors: list = []
    results: list = []

    def run() -> None:
        db = factory()
        try:
            results.append(
                turn_service.execute_turn_service(
                    db, session_id, action, idempotency_key=idempotency_key, use_mock=True
                )
            )
        except BaseException as exc:  # noqa: BLE001 - the assertion below inspects the type
            errors.append(exc)
        finally:
            db.close()

    thread = threading.Thread(target=run, name="turn-worker", daemon=True)
    thread.start()
    return thread, errors, results


def _claim_row(factory, session_id: str) -> dict:
    db = factory()
    try:
        db.execute(text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
        row = db.execute(
            text(
                "SELECT id, idempotency_key, fencing_generation, status, lease_expires_at, turn_no "
                "FROM turn_transactions WHERE session_id = :sid"
            ),
            {"sid": session_id},
        ).mappings().all()
        return [dict(item) for item in row]
    finally:
        db.rollback()
        db.close()


def _is_claim_rejection(error: BaseException) -> bool:
    """Accept ClaimRejected itself or an equivalent error the service wrapped around it."""
    seen: set = set()
    current: Optional[BaseException] = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ClaimRejected):
            return True
        if getattr(current, "code", None) in {"claim_lost", "claim_rejected", "claim_superseded"}:
            return True
        current = current.__cause__ or current.__context__
    return False


def test_superseded_worker_cannot_commit_facts(pg_turn_env, monkeypatch):
    """A worker whose lease expired and whose claim was stolen must not commit facts.

    Worker A blocks inside its model call. An independent connection then expires A's
    lease and lets worker B take the claim over. When A is released it must lose the
    turn: no fact commit, no player_turn event, and B's claim row must survive intact.
    """
    _, factory, session_id = pg_turn_env
    entered = threading.Event()
    release = threading.Event()
    _install_blocking_llm_stage(monkeypatch, entered, release)

    thread, errors, results = _start_worker(factory, session_id, "look around", "key-A")
    takeover_row: Optional[dict] = None
    try:
        assert entered.wait(timeout=_ENTRY_TIMEOUT_SECONDS), (
            "worker A never reached the model-call position of execute_turn_service"
        )

        db_b = factory()
        try:
            # Expire A's lease, then let B steal the claim on its own connection.
            db_b.execute(text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
            db_b.execute(
                text(
                    "UPDATE turn_transactions SET lease_expires_at = now() - interval '1 minute' "
                    "WHERE session_id = :sid AND idempotency_key = 'key-A'"
                ),
                {"sid": session_id},
            )
            db_b.commit()

            db_b.execute(text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
            takeover = expire_or_steal_claim(
                db_b,
                session_id,
                "key-B",
                compute_request_fingerprint("other input", None),
                1,
            )
            assert takeover.status is ClaimStatus.NEW, (
                f"worker B could not take over the expired claim: {takeover.status}"
            )
            db_b.commit()
            takeover_row = db_b.execute(
                text(
                    "SELECT id, idempotency_key, fencing_generation, status "
                    "FROM turn_transactions WHERE session_id = :sid"
                ),
                {"sid": session_id},
            ).mappings().one()
            takeover_row = dict(takeover_row)
        finally:
            db_b.close()
    finally:
        release.set()
        thread.join(timeout=_WORKER_JOIN_TIMEOUT_SECONDS)

    assert not thread.is_alive(), "worker A never returned after being released"

    observer = factory()
    try:
        player_turns = observer.query(EventLogModel).filter_by(
            session_id=session_id, event_type="player_turn"
        ).all()
        game_events = observer.query(GameEventModel).filter_by(session_id=session_id).all()
        claim = observer.query(TurnTransactionModel).filter_by(session_id=session_id).one()
        observed = (
            f"worker_a_error={errors[0] if errors else None!r} "
            f"worker_a_returned={bool(results)} "
            f"player_turn_rows={[row.turn_no for row in player_turns]} "
            f"game_event_rows={len(game_events)} "
            f"claim_after=({claim.id}, {claim.idempotency_key}, {claim.fencing_generation}, "
            f"{claim.status}) "
            f"claim_after_takeover={tuple(takeover_row.values())}"
        )
    finally:
        observer.close()

    # (1) A must be fenced: it either raises a claim rejection or is stopped before returning.
    assert errors, (
        "superseded worker A returned a committed TurnResult instead of being fenced by "
        "the claim it no longer owns; " + observed
    )
    assert _is_claim_rejection(errors[0]), (
        "worker A failed for a reason unrelated to claim ownership, so this run does not "
        "demonstrate the fencing gap; " + observed
    )

    # (2) A must not have written its fact rows.
    assert not player_turns, (
        "superseded worker A committed a player_turn fact row after its claim was taken "
        "over by worker B; " + observed
    )

    # (3) B's claim ownership and status must survive untouched.
    assert (claim.idempotency_key, claim.fencing_generation) == (
        takeover_row["idempotency_key"], takeover_row["fencing_generation"],
    ), "superseded worker A rewrote the claim row owned by worker B; " + observed
    assert claim.status != "committed", (
        "superseded worker A marked worker B's pending claim row as committed; " + observed
    )


def test_long_model_call_renews_lease_while_blocked(pg_turn_env, monkeypatch):
    """The lease must be renewed repeatedly while a worker sits inside a long model call."""
    from llm_rpg.core import turn_claim

    monkeypatch.setattr(turn_claim, "LEASE_SECONDS", 3)
    monkeypatch.setattr(turn_claim, "HEARTBEAT_INTERVAL_SECONDS", 1)

    _, factory, session_id = pg_turn_env
    entered = threading.Event()
    release = threading.Event()
    _install_blocking_llm_stage(monkeypatch, entered, release)

    thread, errors, _ = _start_worker(factory, session_id, "look around", "key-long")
    samples: list = []
    try:
        assert entered.wait(timeout=_ENTRY_TIMEOUT_SECONDS), (
            "worker never reached the model-call position of execute_turn_service"
        )
        probe = factory()
        try:
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                row = probe.execute(
                    text(
                        "SELECT lease_expires_at, status FROM turn_transactions "
                        "WHERE session_id = :sid"
                    ),
                    {"sid": session_id},
                ).mappings().one_or_none()
                probe.rollback()
                samples.append(dict(row) if row is not None else None)
                time.sleep(0.5)
        finally:
            probe.close()
    finally:
        release.set()
        thread.join(timeout=_WORKER_JOIN_TIMEOUT_SECONDS)

    assert not thread.is_alive(), "worker never returned after being released"
    assert samples and samples[0] is not None, "no claim row was visible while the worker was blocked"

    leases = [sample["lease_expires_at"] for sample in samples]
    statuses = [sample["status"] for sample in samples]
    renewals = sum(
        1
        for earlier, later in zip(leases, leases[1:])
        if earlier is not None and later is not None and later > earlier
    )
    observed = (
        f"samples={len(samples)} renewals={renewals} "
        f"distinct_leases={len({lease for lease in leases if lease is not None})} "
        f"statuses={sorted(set(statuses))} worker_error={errors[0] if errors else None!r}"
    )

    assert renewals >= 2, (
        "the lease was never renewed while the worker was blocked inside the model call "
        "(heartbeat_claim has no production caller); " + observed
    )
    assert set(statuses) == {"pending"}, (
        "the claim row left the pending state while the worker was still running; " + observed
    )


def test_no_renewal_after_turn_returns(pg_turn_env, monkeypatch):
    """Once the turn has returned, the lease must stop moving (no leaked heartbeat)."""
    from llm_rpg.core import turn_claim

    lease_seconds = 3
    monkeypatch.setattr(turn_claim, "LEASE_SECONDS", lease_seconds)
    monkeypatch.setattr(turn_claim, "HEARTBEAT_INTERVAL_SECONDS", 1)

    _, factory, session_id = pg_turn_env
    db = factory()
    try:
        result = turn_service.execute_turn_service(
            db, session_id, "look around", idempotency_key="key-steady", use_mock=True
        )
    finally:
        db.close()
    assert result.transaction_id

    before = _claim_row(factory, session_id)
    assert len(before) == 1, f"expected exactly one claim row, got {before}"
    assert before[0]["status"] == "committed", (
        f"precondition failed: the turn did not commit, row={before[0]}"
    )
    time.sleep(2 * lease_seconds + 1)

    after = _claim_row(factory, session_id)
    observed = (
        f"lease_before={before[0]['lease_expires_at']} lease_after={after[0]['lease_expires_at']} "
        f"status_after={after[0]['status']} waited_seconds={2 * lease_seconds + 1}"
    )

    assert after[0]["lease_expires_at"] == before[0]["lease_expires_at"], (
        "the lease kept moving after the turn returned, so a heartbeat outlived its worker; "
        + observed
    )
    assert after[0]["status"] == "committed", observed
