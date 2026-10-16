"""W0 red-light coverage: non-turn session writers must share the turn session lock.

Gap under test
--------------
``execute_turn_service`` holds the transaction-scoped session advisory lock
(``acquire_turn_lock`` -> ``pg_advisory_xact_lock``) only around the final
"re-read persisted state / verify fingerprint -> commit" window
(``core/turn_service.py`` acquire at the commit boundary, fingerprint re-check,
then ``allow_commit()`` / ``db.commit()``).

Writers that live outside the turn path (today: abandoning a quest via
``api/player_quests.abandon_quest``) read, then write, then commit without ever
taking that session lock. They can therefore land inside the re-verify -> commit
window, i.e. after the turn's fingerprint re-check already passed, so the turn
commits a world state it never validated. Plan reference:
``.omo/plans/phase1-turn-foundation-completion.md`` (§2.1 lock protocol, §3 W3,
§4.3 item 3).

These tests are deliberately red until such writers follow the same
transaction-scoped session lock protocol. They assert on real PostgreSQL rows and
real blocking behaviour, never on helper exceptions or HTTP status codes. They
require ``PHASE1_TEST_DATABASE_URL``; without it they skip, and with
``PHASE1_REQUIRE_POSTGRES=1`` a missing URL is a hard failure (never a silent
SQLite substitution).
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

from llm_rpg.api.player_quests import abandon_quest
from llm_rpg.core.turn_concurrency import _generate_lock_key
from llm_rpg.core.turn_service import execute_turn_service
from llm_rpg.core.turn_unit_of_work import TurnUnitOfWork, is_managed
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel,
    LocationModel,
    QuestTemplateModel,
    SaveSlotModel,
    SessionModel,
    SessionQuestStateModel,
    UserModel,
    WorldModel,
)
from llm_rpg.storage.repositories import SessionQuestStateRepository


class PgEnv(NamedTuple):
    engine: Any
    factory: Any
    session_ids: list
    user_id: str
    schema: str
    admin_engine: Any
    suffix: str


@pytest.fixture
def pg_database(monkeypatch):
    """Create an isolated schema and independent PostgreSQL connections.

    Mirrors the established PostgreSQL acceptance fixture so that lock/window
    assertions run on a real server with independent connections.
    """
    required = os.getenv("PHASE1_REQUIRE_POSTGRES") == "1"
    raw_url = os.getenv("PHASE1_TEST_DATABASE_URL")
    if required and not raw_url:
        pytest.fail("PHASE1_REQUIRE_POSTGRES=1 requires PHASE1_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("session writer locking tests require PHASE1_TEST_DATABASE_URL")
    base_url = make_url(raw_url)
    if base_url.get_backend_name() != "postgresql":
        pytest.fail("PHASE1_TEST_DATABASE_URL must use PostgreSQL")
    assert base_url.drivername == "postgresql+psycopg2", "acceptance URL must explicitly use psycopg2"

    suffix = uuid.uuid4().hex
    schema = "turn_writer_lock_" + suffix
    admin_engine = create_engine(base_url)
    with admin_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = base_url.update_query_dict({"options": f"-csearch_path={schema},public"})
    engine = create_engine(isolated_url, pool_size=8, max_overflow=4)
    assert engine.dialect.name == "postgresql"
    factory = sessionmaker(bind=engine, expire_on_commit=False)
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
    yield PgEnv(engine, factory, session_ids, user.id, schema, admin_engine, suffix)

    engine.dispose()
    # NOTE: URL-level "options=-csearch_path=..." isolation does not take effect for the
    # connections these tests use, so rows can land in the public schema; clean them up
    # so a later test never starts from polluted state. Each statement is best-effort:
    # teardown must never mask the assertion result.
    cleanup = (
        ("DELETE FROM session_quest_states WHERE session_id = ANY(:ids)", {"ids": session_ids}),
        ("DELETE FROM quest_templates WHERE id LIKE :prefix", {"prefix": f"quest-{suffix}%"}),
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


def _seed_active_quest(env: PgEnv, session_id: str) -> tuple[str, str]:
    """Seed one real active quest state row for ``session_id``."""
    db = env.factory()
    try:
        session = db.get(SessionModel, session_id)
        assert session is not None
        quest_id = f"quest-{env.suffix}-{uuid.uuid4().hex}"
        template = QuestTemplateModel(
            id=quest_id,
            world_id=session.world_id,
            code=f"q-{uuid.uuid4().hex}",
            name="Seeded Quest",
            quest_type="side",
            summary="seeded for session writer locking coverage",
            visibility="discovered",
        )
        state_id = f"sqs-{env.suffix}-{uuid.uuid4().hex}"
        state = SessionQuestStateModel(
            id=state_id,
            session_id=session_id,
            quest_template_id=quest_id,
            current_step_no=1,
            progress_json={},
            status="active",
            player_visibility="discovered",
        )
        db.add_all([template, state])
        db.commit()
        return quest_id, state_id
    finally:
        db.close()


def _assert_advisory_lock_held(env: PgEnv, key: int) -> None:
    """Prove the session advisory lock is really held by another transaction."""
    probe = env.factory()
    try:
        granted = probe.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}
        ).scalar()
        probe.rollback()
    finally:
        probe.close()
    assert not granted, (
        f"test setup failed: session advisory lock key {key} was not held by the locking transaction"
    )


def _run_abandon_quest(
    env: PgEnv,
    session_id: str,
    quest_id: str,
    started: threading.Event,
    finished: threading.Event,
    outcome: Dict[str, Any],
) -> None:
    """Exercise the real abandon-quest write path on its own connection."""
    db = env.factory()
    try:
        user = UserModel(
            id=env.user_id,
            username="pg-test",
            email="pg-test@example.invalid",
            password_hash="x",
            is_admin=True,
        )
        started.set()
        outcome["detail"] = abandon_quest(session_id, quest_id, current_user=user, db=db)
    except BaseException as exc:  # noqa: BLE001 - recorded for diagnostics
        outcome["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        finished.set()
        try:
            db.close()
        except Exception:  # pragma: no cover - diagnostics only
            pass


def test_abandon_quest_blocks_on_session_lock(pg_database):
    """A non-turn writer must wait for the session lock instead of racing it."""
    env: PgEnv = pg_database
    session_id = env.session_ids[0]
    quest_id, state_id = _seed_active_quest(env, session_id)
    lock_key = _generate_lock_key(session_id)

    lock_db = env.factory()
    writer = None
    started = threading.Event()
    finished = threading.Event()
    outcome: Dict[str, Any] = {}
    try:
        # Hold the session advisory lock in an open transaction, exactly as the turn
        # commit boundary does.
        lock_db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        _assert_advisory_lock_held(env, lock_key)

        writer = threading.Thread(
            target=_run_abandon_quest,
            args=(env, session_id, quest_id, started, finished, outcome),
            daemon=True,
        )
        writer.start()
        try:
            assert started.wait(timeout=5), f"writer thread never entered abandon_quest: {outcome}"
            completed_while_locked = finished.wait(timeout=3.0)
            print(
                "abandon_quest_completed_while_session_lock_held="
                f"{completed_while_locked} outcome={outcome}"
            )
            assert not completed_while_locked, (
                "abandon_quest committed while another transaction held the session advisory lock "
                f"(key={lock_key}, session={session_id}). The non-turn writer takes no session lock, "
                "so it can land inside the turn's re-verify -> commit window and commit a world "
                "state the turn never re-validated."
            )
        finally:
            lock_db.commit()  # releases the transaction-scoped advisory lock
            writer.join(timeout=10)
    finally:
        lock_db.close()

    assert finished.is_set(), "abandon_quest never finished after the session lock was released"
    assert "error" not in outcome, outcome
    assert outcome["detail"].status == "abandoned"
    observer = env.factory()
    try:
        row = observer.query(SessionQuestStateModel).filter_by(id=state_id).one()
        assert row.status == "abandoned"
    finally:
        observer.close()


def test_abandon_quest_cannot_cross_reverify_window(pg_database, monkeypatch):
    """A non-turn writer must not commit after the turn's fingerprint re-check."""
    env: PgEnv = pg_database
    session_id = env.session_ids[0]
    lock_key = _generate_lock_key(session_id)

    reached_boundary = threading.Event()
    release_turn = threading.Event()
    original_allow_commit = TurnUnitOfWork.allow_commit

    def paused_allow_commit(self):
        # allow_commit() is called after acquire_turn_lock() and after the fresh-connection
        # fingerprint re-check, so reaching it means the turn holds the session lock and has
        # already accepted the persisted state it is about to commit.
        reached_boundary.set()
        release_turn.wait(timeout=30)
        return original_allow_commit(self)

    monkeypatch.setattr(TurnUnitOfWork, "allow_commit", paused_allow_commit)

    turn_outcome: Dict[str, Any] = {}

    def run_turn() -> None:
        db = env.factory()
        try:
            turn_outcome["result"] = execute_turn_service(
                db, session_id, "look around", idempotency_key="win-key", use_mock=True
            )
        except BaseException as exc:  # noqa: BLE001 - recorded for diagnostics
            turn_outcome["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                db.close()
            except Exception:  # pragma: no cover - diagnostics only
                pass

    turn_thread = threading.Thread(target=run_turn, daemon=True)
    turn_thread.start()

    writer = None
    started = threading.Event()
    finished = threading.Event()
    outcome: Dict[str, Any] = {}
    state_id = None
    try:
        if not reached_boundary.wait(timeout=30):
            pytest.fail(
                "turn worker never reached the final commit boundary (allow_commit): "
                f"{turn_outcome}"
            )
        _assert_advisory_lock_held(env, lock_key)

        # Seed the quest *after* the re-check so the only thing that can block the
        # writer is the session lock itself, never a row lock taken by the turn.
        quest_id, state_id = _seed_active_quest(env, session_id)

        writer = threading.Thread(
            target=_run_abandon_quest,
            args=(env, session_id, quest_id, started, finished, outcome),
            daemon=True,
        )
        writer.start()
        assert started.wait(timeout=5), f"writer thread never entered abandon_quest: {outcome}"
        completed_inside_window = finished.wait(timeout=3.0)
        print(
            "abandon_quest_completed_inside_reverify_window="
            f"{completed_inside_window} outcome={outcome}"
        )
        assert not completed_inside_window, (
            "abandon_quest committed inside the turn's re-verify -> commit window "
            f"(session={session_id}, lock key={lock_key}). The turn already re-read and accepted "
            "the persisted state, and the non-turn writer takes no session lock, so the committed "
            "turn silently overwrites / races this change."
        )
    finally:
        release_turn.set()
        turn_thread.join(timeout=30)
        if writer is not None:
            writer.join(timeout=10)

    assert "error" not in turn_outcome, turn_outcome
    assert turn_outcome["result"].turn_no == 1
    assert finished.is_set(), "abandon_quest never finished after the turn released the session lock"
    assert "error" not in outcome, outcome
    assert outcome["detail"].status == "abandoned"
    assert state_id is not None
    observer = env.factory()
    try:
        row = observer.query(SessionQuestStateModel).filter_by(id=state_id).one()
        assert row.status == "abandoned"
    finally:
        observer.close()


def test_managed_turn_uow_rejects_self_commit(pg_database):
    """A writer embedded in a managed turn UoW must flush, never commit on its own."""
    env: PgEnv = pg_database
    session_id = env.session_ids[0]
    quest_id, state_id = _seed_active_quest(env, session_id)

    db = env.factory()
    try:
        repo = SessionQuestStateRepository(db)
        state = repo.get_by_session_and_quest(session_id, quest_id)
        assert state is not None and state.status == "active"
        original_commit = db.commit

        with TurnUnitOfWork(db, guard_commits=True):
            assert is_managed(db)
            assert db.commit == db.flush, (
                "guarded turn UoW must substitute flush for commit inside the managed scope"
            )
            updated = repo.update(state.id, {"status": "abandoned"})
            assert updated.status == "abandoned"
            observer = env.factory()
            try:
                visible = observer.query(SessionQuestStateModel).filter_by(id=state_id).one().status
            finally:
                observer.close()
            assert visible == "active", (
                "a writer embedded in a managed turn UoW must not commit on its own; "
                f"the row became durable as {visible!r} before the authoritative commit"
            )

        assert db.commit == original_commit, "guarded UoW must restore Session.commit on exit"
        assert db.commit != db.flush

        db.commit()
        observer = env.factory()
        try:
            assert observer.query(SessionQuestStateModel).filter_by(id=state_id).one().status == "abandoned"
        finally:
            observer.close()
    finally:
        db.close()
