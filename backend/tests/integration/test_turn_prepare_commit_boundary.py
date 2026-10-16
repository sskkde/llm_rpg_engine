"""W0 red-light coverage: preparation must not run inside a business transaction.

Gap under test
--------------
``execute_turn_service`` enters ``TurnUnitOfWork`` at ``core/turn_service.py`` right
after the claim short transaction and *before* the first LLM stage, and
``initialize_session_story_state`` writes baseline rows at the same point. The turn
therefore holds an open, write-owning database transaction for the whole model-wait
window instead of the target "pure preparation -> final short transaction" flow.
Plan reference: ``.omo/plans/phase1-turn-foundation-completion.md`` (§2.1, §3 W2,
§4.2).

These tests are deliberately red until preparation stops touching the database.
They assert on real PostgreSQL server state (``pg_stat_activity`` / ``pg_locks``) and
real rows, never on helper exceptions. They require ``PHASE1_TEST_DATABASE_URL``;
without it they skip, and with ``PHASE1_REQUIRE_POSTGRES=1`` a missing URL is a hard
failure (never a silent SQLite substitution).
"""

from __future__ import annotations

import os
import threading
import uuid
from typing import Any, Dict, NamedTuple

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from llm_rpg.core import turn_service as service
from llm_rpg.core.turn_concurrency import _generate_lock_key
from llm_rpg.core.turn_service import compute_state_fingerprint, execute_turn_service
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel,
    LocationModel,
    SaveSlotModel,
    SessionModel,
    UserModel,
    WorldModel,
)


class PgEnv(NamedTuple):
    engine: Any
    factory: Any
    probe_factory: Any
    session_ids: list
    user_id: str
    schema: str
    admin_engine: Any
    suffix: str
    app_name: str


@pytest.fixture
def pg_database(monkeypatch):
    """Create an isolated schema and independent PostgreSQL connections."""
    required = os.getenv("PHASE1_REQUIRE_POSTGRES") == "1"
    raw_url = os.getenv("PHASE1_TEST_DATABASE_URL")
    if required and not raw_url:
        pytest.fail("PHASE1_REQUIRE_POSTGRES=1 requires PHASE1_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("prepare/commit boundary tests require PHASE1_TEST_DATABASE_URL")
    base_url = make_url(raw_url)
    if base_url.get_backend_name() != "postgresql":
        pytest.fail("PHASE1_TEST_DATABASE_URL must use PostgreSQL")
    assert base_url.drivername == "postgresql+psycopg2", "acceptance URL must explicitly use psycopg2"

    suffix = uuid.uuid4().hex
    schema = "turn_prepare_boundary_" + suffix
    admin_engine = create_engine(base_url)
    with admin_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = base_url.update_query_dict({"options": f"-csearch_path={schema},public"})
    # A unique application_name lets the probe find the turn's backend from
    # pg_stat_activity WITHOUT issuing a statement on the turn's own Session: any
    # statement there would autobegin a transaction and make the "no open business
    # transaction" observation describe the probe instead of the code under test.
    app_name = f"turn_prep_{suffix}"
    engine = create_engine(
        isolated_url,
        pool_size=8,
        max_overflow=4,
        connect_args={"application_name": app_name},
    )
    assert engine.dialect.name == "postgresql"
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    # Keep observation connections in a distinct pool. Once the turn correctly rolls
    # back its read transaction, its DBAPI connection returns to the application pool;
    # a probe from that same pool could otherwise borrow and observe its own backend.
    probe_engine = create_engine(isolated_url, pool_size=4, max_overflow=4)
    probe_factory = sessionmaker(bind=probe_engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

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
    sessions = [
        SessionModel(
            id=f"session-{i}-{suffix}",
            user_id=user.id,
            world_id=world.id,
            save_slot_id=slot.id,
            current_chapter_id=chapter.id,
            status="active",
        )
        for i in range(2)
    ]
    db.add_all([location, *sessions])
    db.commit()
    db.close()

    session_ids = [row.id for row in sessions]
    yield PgEnv(engine, factory, probe_factory, session_ids, user.id, schema, admin_engine, suffix, app_name)

    engine.dispose()
    probe_engine.dispose()
    # URL-level search_path isolation does not reliably apply to every pooled
    # connection, so remove this test's rows explicitly; teardown is best-effort and
    # must never mask the assertion result.
    cleanup = (
        ("DELETE FROM session_quest_states WHERE session_id = ANY(:ids)", {"ids": session_ids}),
        ("DELETE FROM session_npc_states WHERE session_id = ANY(:ids)", {"ids": session_ids}),
        ("DELETE FROM session_player_states WHERE session_id = ANY(:ids)", {"ids": session_ids}),
        ("DELETE FROM session_states WHERE session_id = ANY(:ids)", {"ids": session_ids}),
        ("DELETE FROM state_deltas WHERE session_id = ANY(:ids)", {"ids": session_ids}),
        (
            "DELETE FROM llm_stage_results WHERE transaction_id IN "
            "(SELECT id FROM turn_transactions WHERE session_id = ANY(:ids))",
            {"ids": session_ids},
        ),
        ("DELETE FROM game_events WHERE session_id = ANY(:ids)", {"ids": session_ids}),
        (
            "DELETE FROM validation_reports WHERE transaction_id IN "
            "(SELECT id FROM turn_transactions WHERE session_id = ANY(:ids))",
            {"ids": session_ids},
        ),
        ("DELETE FROM event_logs WHERE session_id = ANY(:ids)", {"ids": session_ids}),
        ("DELETE FROM turn_transactions WHERE session_id = ANY(:ids)", {"ids": session_ids}),
        ("DELETE FROM sessions WHERE id = ANY(:ids)", {"ids": session_ids}),
        ("DELETE FROM locations WHERE id = :loc", {"loc": f"l-{suffix}"}),
        ("DELETE FROM save_slots WHERE id = :slot", {"slot": f"s-{suffix}"}),
        ("DELETE FROM chapters WHERE id = :chapter", {"chapter": f"c-{suffix}"}),
        ("DELETE FROM worlds WHERE id = :world", {"world": f"w-{suffix}"}),
        ("DELETE FROM users WHERE id = :user", {"user": f"u-{suffix}"}),
    )
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for statement, params in cleanup:
            try:
                conn.execute(text(statement), params)
            except Exception as exc:  # pragma: no cover - diagnostics only
                print(f"cleanup skipped ({type(exc).__name__}): {statement}")
        try:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        except Exception as exc:  # pragma: no cover - diagnostics only
            print(f"schema drop skipped ({type(exc).__name__})")
    admin_engine.dispose()


class _PausedTurn:
    """Run one real turn in a background thread, paused at the first LLM stage."""

    def __init__(self, env: PgEnv, monkeypatch, session_id: str, key: str):
        self.env = env
        self.session_id = session_id
        self.key = key
        self.in_llm = threading.Event()
        self.release = threading.Event()
        self.marker = f"turn_probe_{uuid.uuid4().hex[:12]}"
        self.outcome: Dict[str, Any] = {}
        self.thread = threading.Thread(target=self._run, daemon=True)
        original = service._execute_input_intent_stage
        self._original = original

        def blocking(*args, **kwargs):
            db = kwargs.get("db")
            if db is None:
                db = args[0]
            # Deliberately NO SQL here: a statement on the turn's own Session would
            # autobegin a transaction and the probe would then be observing itself.
            # Only in-memory Session state is read (no statement, no transaction).
            self.pending["new"] = len(db.new)
            self.pending["dirty"] = len(db.dirty)
            self.pending["deleted"] = len(db.deleted)
            self.in_llm.set()
            assert self.release.wait(timeout=30), "turn thread was never released"
            return original(*args, **kwargs)

        self.pending: Dict[str, int] = {}
        monkeypatch.setattr(service, "_execute_input_intent_stage", blocking)

    def _run(self) -> None:
        db = self.env.factory()
        try:
            # Tag this connection so the probe can find it in pg_stat_activity without
            # issuing any statement on the turn's Session during the observation window.
            # The tag must be COMMITTED: PostgreSQL undoes a plain SET when the issuing
            # transaction rolls back, and there is no pending work to commit here.
            db.execute(text("SET application_name = :name"), {"name": self.marker})
            db.commit()
            self.outcome["result"] = execute_turn_service(
                db, self.session_id, "look around", idempotency_key=self.key, use_mock=True
            )
        except BaseException as exc:  # noqa: BLE001 - recorded for diagnostics
            self.outcome["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                db.close()
            except Exception:  # pragma: no cover - diagnostics only
                pass

    def start(self) -> "_PausedTurn":
        self.thread.start()
        assert self.in_llm.wait(timeout=60), f"turn never reached the first LLM stage: {self.outcome}"
        return self

    def resume(self) -> None:
        self.release.set()
        self.thread.join(timeout=120)


def _turn_backend_pid(probe, marker: str) -> int:
    """Find the turn's backend without touching the turn's own Session.

    The turn's connection is tagged with a unique ``application_name`` before the turn
    starts (``SET`` is session-level, so it survives the rollback that closes the
    tagging statement's transaction). Pooled connections from the fixture carry the
    engine-wide name instead, so exactly one row matches while the turn is parked.
    """
    rows = probe.execute(
        text("SELECT pid FROM pg_stat_activity WHERE application_name = :app"),
        {"app": marker},
    ).all()
    assert len(rows) == 1, (
        f"expected exactly one live turn backend for application_name={marker!r}, got {rows}"
    )
    return rows[0][0]


def _activity(probe, pid: int):
    return probe.execute(
        text("SELECT state, xact_start FROM pg_stat_activity WHERE pid = :pid"), {"pid": pid}
    ).first()


def _transaction_id_locks(probe, pid: int):
    return probe.execute(
        text(
            "SELECT locktype, mode, granted FROM pg_locks "
            "WHERE pid = :pid AND locktype = 'transactionid'"
        ),
        {"pid": pid},
    ).all()


def test_no_open_business_transaction_during_llm_wait(pg_database, monkeypatch):
    """During the model wait the turn must hold no open database transaction."""
    env: PgEnv = pg_database
    session_id = env.session_ids[0]
    turn = _PausedTurn(env, monkeypatch, session_id, "prep-open-tx").start()

    probe = env.probe_factory()
    try:
        pid = _turn_backend_pid(probe, turn.marker)
        row = _activity(probe, pid)
        assert row is not None, "the turn's backend connection disappeared during the model wait"
        state, xact_start = row
        print(f"turn backend pid={pid} state={state!r} xact_start={xact_start} pending={turn.pending}")
        assert state != "idle in transaction", (
            "the turn held an open database transaction across the model wait "
            f"(state={state!r}, xact_start={xact_start}, pending writes={turn.pending}); "
            "preparation must be pure so no business transaction is held while the model runs"
        )
        assert xact_start is None, (
            f"the turn's transaction was still open during the model wait (xact_start={xact_start})"
        )
    finally:
        probe.close()
        turn.resume()

    assert "error" not in turn.outcome, turn.outcome


def test_preparation_writes_no_game_state_before_the_final_transaction(pg_database, monkeypatch):
    """Preparation must not have written (or staged) game state while the model runs."""
    env: PgEnv = pg_database
    session_id = env.session_ids[0]
    turn = _PausedTurn(env, monkeypatch, session_id, "prep-no-writes").start()

    probe = env.probe_factory()
    try:
        pid = _turn_backend_pid(probe, turn.marker)
        locks = _transaction_id_locks(probe, pid)
        print(f"turn backend pid={pid} transactionid_locks={locks} pending={turn.pending}")
        assert turn.pending["new"] == 0, (
            f"preparation staged {turn.pending['new']} new rows before the model call; "
            "writes must be deferred to the final authoritative transaction"
        )
        assert locks == [], (
            f"preparation had already written game state (transaction id locks={locks}) "
            "before the final authoritative transaction"
        )
    finally:
        probe.close()
        turn.resume()

    assert "error" not in turn.outcome, turn.outcome


def test_third_connection_can_lock_and_write_during_llm_wait(pg_database, monkeypatch):
    """A third connection must be able to take the session lock and write while the model runs."""
    env: PgEnv = pg_database
    session_id = env.session_ids[0]

    # Pre-seed committed baseline state so the third connection has a real row to touch.
    seed = env.factory()
    try:
        service.initialize_session_story_state(seed, session_id)
        seed.commit()
    finally:
        seed.close()

    turn = _PausedTurn(env, monkeypatch, session_id, "prep-third-conn").start()

    probe = env.probe_factory()
    try:
        probe.execute(text("SET LOCAL lock_timeout = '2s'"))
        granted = probe.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": _generate_lock_key(session_id)},
        ).scalar()
        assert granted is True, (
            "the session advisory lock was still held during the model wait, so no other "
            "writer could make progress"
        )
        # "current_time" is a PostgreSQL reserved word, so use FOR UPDATE NOWAIT to
        # probe the row lock instead of writing the column.
        locked_rows = probe.execute(
            text(
                "SELECT id FROM session_states WHERE session_id = :sid FOR UPDATE NOWAIT"
            ),
            {"sid": session_id},
        ).all()
        assert len(locked_rows) == 1, (
            "a third connection could not lock this session's game state during the model wait "
            f"(rows={locked_rows}); the turn is holding row locks it must not hold"
        )
        probe.commit()
    finally:
        probe.close()
        turn.resume()

    assert "error" not in turn.outcome, turn.outcome


def test_persistent_state_is_unchanged_while_the_model_runs(pg_database, monkeypatch):
    """Preparation must not be visible to other connections (guard)."""
    env: PgEnv = pg_database
    session_id = env.session_ids[0]

    before = env.factory()
    try:
        fingerprint_before = compute_state_fingerprint(before, session_id)
    finally:
        before.close()

    turn = _PausedTurn(env, monkeypatch, session_id, "prep-fingerprint").start()

    probe = env.probe_factory()
    try:
        fingerprint_during = compute_state_fingerprint(probe, session_id)
        assert fingerprint_during == fingerprint_before, (
            "persisted state changed (and became visible to another connection) while the model ran"
        )
    finally:
        probe.close()
        turn.resume()

    assert "error" not in turn.outcome, turn.outcome


@pytest.mark.parametrize(
    "stage_name",
    ["_execute_input_intent_stage", "_execute_world_stage", "_execute_scene_stage", "_execute_npc_stage"],
)
def test_no_open_business_transaction_at_each_llm_stage(pg_database, monkeypatch, stage_name):
    """Each real LLM-stage entry must begin with an idle business connection."""
    env: PgEnv = pg_database
    session_id = env.session_ids[0]
    reached = threading.Event()
    release = threading.Event()
    marker = f"turn_stage_probe_{uuid.uuid4().hex[:12]}"
    outcome: Dict[str, Any] = {}
    original = getattr(service, stage_name)

    def blocking(*args, **kwargs):
        reached.set()
        assert release.wait(timeout=30), f"{stage_name} was never released"
        return original(*args, **kwargs)

    monkeypatch.setattr(service, stage_name, blocking)

    def run_turn():
        db = env.factory()
        try:
            db.execute(text("SET application_name = :name"), {"name": marker})
            db.commit()
            outcome["result"] = execute_turn_service(
                db, session_id, "look around", idempotency_key=f"stage-{stage_name}", use_mock=True
            )
        except BaseException as exc:  # noqa: BLE001 - recorded for diagnostics
            outcome["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            db.close()

    thread = threading.Thread(target=run_turn, daemon=True)
    thread.start()
    probe = env.probe_factory()
    try:
        assert reached.wait(timeout=60), f"turn never reached {stage_name}: {outcome}"
        pid = _turn_backend_pid(probe, marker)
        row = _activity(probe, pid)
        assert row is not None, "the turn's backend connection disappeared during the model wait"
        state, xact_start = row
        print(f"stage={stage_name} turn backend pid={pid} state={state!r} xact_start={xact_start}")
        assert state != "idle in transaction", (
            f"{stage_name} held an open database transaction before the model call "
            f"(state={state!r}, xact_start={xact_start})"
        )
        assert xact_start is None, (
            f"{stage_name} transaction was still open before model call (xact_start={xact_start})"
        )
    finally:
        probe.close()
        release.set()
        thread.join(timeout=120)
    assert not thread.is_alive(), f"turn thread did not finish after releasing {stage_name}"
    assert "error" not in outcome, outcome
