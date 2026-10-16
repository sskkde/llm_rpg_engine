"""PostgreSQL-only concurrency, fencing, and migration safety gates for turns.

This module intentionally fails when PostgreSQL is required but unavailable; it
never silently substitutes SQLite for the acceptance gate.
"""

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from llm_rpg.api.auth import get_current_active_user
from llm_rpg.core.turn_claim import (
    ClaimRejected,
    ClaimStatus,
    abort_claim,
    create_or_resume_claim,
    expire_or_steal_claim,
    heartbeat_claim,
)
from llm_rpg.main import app
from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    ChapterModel,
    EventLogModel,
    GameEventModel,
    LocationModel,
    SaveSlotModel,
    SessionModel,
    StateDeltaModel,
    TurnTransactionModel,
    UserModel,
    WorldModel,
)


@pytest.fixture
def pg_database(monkeypatch):
    """Create an isolated schema and independent PostgreSQL connections."""
    required = os.getenv("PHASE1_REQUIRE_POSTGRES") == "1"
    raw_url = os.getenv("PHASE1_TEST_DATABASE_URL")
    if required and not raw_url:
        pytest.fail("PHASE1_REQUIRE_POSTGRES=1 requires PHASE1_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("PostgreSQL foundation tests require PHASE1_TEST_DATABASE_URL")
    base_url = make_url(raw_url)
    if base_url.get_backend_name() != "postgresql":
        pytest.fail("PHASE1_TEST_DATABASE_URL must use PostgreSQL")
    assert base_url.drivername == "postgresql+psycopg2", "acceptance URL must explicitly use psycopg2"

    schema = "turn_foundation_" + uuid.uuid4().hex
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
    sessions = [SessionModel(id=f"session-{i}-{suffix}", user_id=user.id, world_id=world.id, save_slot_id=slot.id, current_chapter_id=chapter.id, status="active") for i in range(2)]
    db.add_all([location, *sessions])
    db.commit()
    db.close()

    session_ids = [row.id for row in sessions]
    yield engine, factory, session_ids, user.id, schema, admin_engine

    engine.dispose()
    with admin_engine.begin() as conn:
        # NOTE: URL-level "options=-csearch_path=..." isolation does not take effect for the
        # connections these tests use, so their rows land in the public schema. Clean them up
        # here; otherwise a later test (e.g. the 025 downgrade guard) starts from polluted state.
        conn.execute(text("DELETE FROM state_deltas WHERE session_id = ANY(:ids)"), {"ids": session_ids})
        # ``validation_reports``/``llm_stage_results`` reference ``turn_transactions``,
        # so they must be removed before the transactions themselves. Phase 2 records
        # an authorization validation report on the refusal path, which made this
        # pre-existing gap in the cleanup list observable.
        conn.execute(text("DELETE FROM validation_reports WHERE session_id = ANY(:ids)"), {"ids": session_ids})
        conn.execute(text("DELETE FROM validation_reports WHERE transaction_id IN (SELECT id FROM turn_transactions WHERE session_id = ANY(:ids))"), {"ids": session_ids})
        conn.execute(text("DELETE FROM llm_stage_results WHERE transaction_id IN (SELECT id FROM turn_transactions WHERE session_id = ANY(:ids))"), {"ids": session_ids})
        conn.execute(text("DELETE FROM game_events WHERE session_id = ANY(:ids)"), {"ids": session_ids})
        conn.execute(text("DELETE FROM event_logs WHERE session_id = ANY(:ids)"), {"ids": session_ids})
        conn.execute(text("DELETE FROM turn_transactions WHERE session_id = ANY(:ids)"), {"ids": session_ids})
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    admin_engine.dispose()


@pytest.fixture
def pg_app(pg_database, monkeypatch):
    engine, factory, session_ids, user_id, *_ = pg_database
    from llm_rpg.api import streaming

    # Endpoint requests, streaming worker sessions, and test-side observers all
    # use the fixture factory—not APP_ENV's SQLite engine.
    monkeypatch.setattr(streaming, "SessionLocal", factory)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    def override_user():
        return UserModel(id=user_id, username="pg-test", email="pg-test@example.invalid", is_admin=True)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = override_user
    with TestClient(app) as client:
        yield client, factory, session_ids
    app.dependency_overrides.clear()


def _thread_claim(factory, session_id, key, fingerprint, barrier):
    db = factory()
    try:
        barrier.wait(timeout=10)
        outcome = create_or_resume_claim(db, session_id, key, fingerprint, 1)
        db.commit()
        return outcome
    finally:
        db.close()


def test_same_key_concurrent_replay_has_one_durable_result(pg_app, monkeypatch):
    client, factory, sessions = pg_app
    session_id = sessions[0]
    claim_created = threading.Event()
    release_first = threading.Event()
    payload = {"action": "观察四周", "idempotency_key": "pg-same-key"}
    from llm_rpg.core import turn_service

    original_create_claim = turn_service.create_or_resume_claim
    first_call = True

    def hold_first_claim(db, *args, **kwargs):
        nonlocal first_call
        outcome = original_create_claim(db, *args, **kwargs)
        if first_call:
            first_call = False
            db.commit()
            claim_created.set()
            assert release_first.wait(timeout=10)
        return outcome

    monkeypatch.setattr(turn_service, "create_or_resume_claim", hold_first_claim)

    def request():
        started_at = time.monotonic()
        response = client.post(f"/game/sessions/{session_id}/turn", json=payload)
        return response, time.monotonic() - started_at

    with ThreadPoolExecutor(max_workers=1) as pool:
        first_request = pool.submit(request)
        assert claim_created.wait(timeout=10)
        observer = factory()
        try:
            claim = observer.query(TurnTransactionModel).filter_by(session_id=session_id).one()
            assert claim.status == "pending"
        finally:
            observer.close()
        conflict_response, conflict_elapsed = request()
        assert conflict_response.status_code == 409
        assert conflict_response.json()["detail"]["code"] == "turn_in_progress"
        assert not first_request.done()
        assert not release_first.is_set()
        release_first.set()
        success, _ = first_request.result(timeout=30)

    assert success.status_code == 200
    success_body = success.json()
    assert success_body["turn_index"] == 1
    observer = factory()
    try:
        assert observer.query(EventLogModel).filter_by(session_id=session_id, event_type="player_turn").count() == 1
        assert observer.query(TurnTransactionModel).filter_by(session_id=session_id).count() == 1
        committed = observer.query(TurnTransactionModel).filter_by(session_id=session_id).one()
        assert committed.status == "committed"
        assert committed.id == success_body["transaction_id"]
    finally:
        observer.close()

    replay = client.post(f"/game/sessions/{session_id}/turn", json=payload)
    assert replay.status_code == 200
    replay_body = replay.json()
    assert replay_body["turn_index"] == success_body["turn_index"]
    assert replay_body["transaction_id"] == success_body["transaction_id"]
    assert replay_body["narration"] == success_body["narration"]
    assert conflict_elapsed < 10


def test_different_key_race_returns_one_turn_in_progress(pg_database):
    _, factory, sessions, *_ = pg_database
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda key: _thread_claim(factory, sessions[0], key, f"fp-{key}", barrier), ("race-a", "race-b")))
    assert sorted(outcome.status.value for outcome in outcomes) == ["active_conflict", "new"]
    observer = factory()
    try:
        rows = observer.query(TurnTransactionModel).filter_by(session_id=sessions[0]).all()
        assert len(rows) == 1
        assert rows[0].status == "pending"
    finally:
        observer.close()


def test_same_key_claims_are_isolated_between_sessions(pg_database):
    _, factory, sessions, *_ = pg_database
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda session_id: _thread_claim(factory, session_id, "shared-key", "shared-fp", barrier), sessions))
    assert [o.status for o in outcomes] == [ClaimStatus.NEW, ClaimStatus.NEW]
    assert outcomes[0].token.transaction_id != outcomes[1].token.transaction_id
    observer = factory()
    try:
        rows = observer.query(TurnTransactionModel).filter(TurnTransactionModel.session_id.in_(sessions)).all()
        assert len(rows) == 2
        assert {row.session_id for row in rows} == set(sessions)
    finally:
        observer.close()


def test_expired_worker_is_fenced_after_takeover(pg_database):
    _, factory, sessions, *_ = pg_database
    session_id = sessions[0]
    old_db = factory()
    try:
        original = create_or_resume_claim(old_db, session_id, "old-worker", "old-fp", 1).token
        row = old_db.get(TurnTransactionModel, original.transaction_id)
        row.lease_expires_at = datetime.utcnow() - timedelta(seconds=5)
        old_db.commit()
    finally:
        old_db.close()

    takeover_db = factory()
    try:
        takeover = expire_or_steal_claim(takeover_db, session_id, "new-worker", "new-fp", 1)
        assert takeover.status is ClaimStatus.NEW
        takeover_db.commit()
        new_token = takeover.token
    finally:
        takeover_db.close()

    stale_db = factory()
    try:
        with pytest.raises(ClaimRejected):
            heartbeat_claim(stale_db, original)
        stale_db.rollback()
        with pytest.raises(ClaimRejected):
            abort_claim(stale_db, original, {"category": "stale-worker"})
        stale_db.rollback()
        with pytest.raises(ClaimRejected):
            from llm_rpg.core.turn_claim import _cas_token
            _cas_token(stale_db, original, {"status": "committed", "committed_at": datetime.utcnow()})
        stale_db.rollback()
    finally:
        stale_db.close()

    observer = factory()
    try:
        row = observer.get(TurnTransactionModel, new_token.transaction_id)
        assert row.idempotency_key == "new-worker"
        assert row.request_fingerprint == "new-fp"
        assert row.fencing_generation == new_token.generation == original.generation + 1
        assert row.status == "pending"
        assert row.lease_expires_at > datetime.utcnow()
    finally:
        observer.close()


def test_llm_wait_does_not_hold_advisory_lock_or_uncommitted_claim_row(pg_database):
    _, factory, sessions, *_ = pg_database
    session_id = sessions[0]
    worker = factory()
    outcome = create_or_resume_claim(worker, session_id, "waiting-llm", "waiting-fp", 1)
    worker.commit()
    barrier = threading.Barrier(2)
    finished = threading.Event()

    def llm_wait():
        barrier.wait(timeout=10)
        time.sleep(0.1)
        finished.set()

    thread = threading.Thread(target=llm_wait)
    thread.start()
    try:
        barrier.wait(timeout=10)
        third_connection = factory()
        try:
            # Same session lock succeeds while worker is notionally inside LLM.
            from llm_rpg.core.turn_concurrency import acquire_turn_lock
            acquire_turn_lock(third_connection, session_id, timeout_seconds=0)
            current = third_connection.query(TurnTransactionModel).filter_by(id=outcome.token.transaction_id).one()
            current.player_input = "third-connection-update"
            third_connection.commit()
        finally:
            third_connection.close()
        assert finished.wait(timeout=5)
    finally:
        thread.join(timeout=5)
        worker.close()
    observer = factory()
    try:
        row = observer.get(TurnTransactionModel, outcome.token.transaction_id)
        assert row.player_input == "third-connection-update"
        assert row.status == "pending"
    finally:
        observer.close()


def test_final_commit_exception_leaves_no_partial_turn_effects(pg_database, monkeypatch):
    _, factory, sessions, *_ = pg_database
    import llm_rpg.core.turn_service as service

    session_id = sessions[0]
    original_allow_commit = service.TurnUnitOfWork.allow_commit

    def fail_once_after_uow_commit_is_allowed(self):
        original_allow_commit(self)
        real_commit = self.db.commit
        failed = False

        def injected_commit_failure():
            nonlocal failed
            if not failed:
                failed = True
                raise RuntimeError("injected final commit failure")
            return real_commit()

        self.db.commit = injected_commit_failure

    monkeypatch.setattr(service.TurnUnitOfWork, "allow_commit", fail_once_after_uow_commit_is_allowed)
    db = factory()
    try:
        with pytest.raises(RuntimeError, match="injected final commit failure"):
            service.execute_turn_service(db, session_id, "等待", idempotency_key="commit-fails", use_mock=True)
    finally:
        db.close()
    observer = factory()
    try:
        claim = observer.query(TurnTransactionModel).filter_by(session_id=session_id, idempotency_key="commit-fails").one()
        assert claim.status == "aborted"
        assert observer.query(EventLogModel).filter_by(session_id=session_id, event_type="player_turn").count() == 0
        assert observer.query(GameEventModel).filter_by(transaction_id=claim.id).count() == 0
        assert observer.query(StateDeltaModel).filter_by(transaction_id=claim.id).count() == 0
    finally:
        observer.close()


def test_migration_025_history_adjudication_and_downgrade_guard(monkeypatch):
    """Exercise migration history in a disposable database, isolated from shared test state."""
    raw_url = os.getenv("PHASE1_TEST_DATABASE_URL")
    if not raw_url:
        if os.getenv("PHASE1_REQUIRE_POSTGRES") == "1":
            pytest.fail("PHASE1_REQUIRE_POSTGRES=1 requires PHASE1_TEST_DATABASE_URL")
        pytest.skip("PostgreSQL migration gate requires PHASE1_TEST_DATABASE_URL")
    base_url = make_url(raw_url)
    assert base_url.drivername == "postgresql+psycopg2"
    database_name = f"phase1_mig_{uuid.uuid4().hex}"
    admin_engine = create_engine(base_url)
    engine = None
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    try:
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f'CREATE DATABASE "{database_name}"'))

        database_url = base_url.set(database=database_name)
        rendered_url = database_url.render_as_string(hide_password=False)
        monkeypatch.setenv("DATABASE_URL", rendered_url)
        config.set_main_option("sqlalchemy.url", rendered_url.replace("%", "%%"))
        engine = create_engine(database_url)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        command.upgrade(config, "head")

        suffix = uuid.uuid4().hex
        user = UserModel(id=f"u-{suffix}", username=f"u-{suffix}", email=f"{suffix}@test.invalid", password_hash="x", is_admin=False)
        world = WorldModel(id=f"w-{suffix}", code=f"w-{suffix}", name="Test", genre="test", status="active")
        with factory() as db:
            db.add_all([user, world])
            db.flush()
            chapter = ChapterModel(id=f"c-{suffix}", world_id=world.id, chapter_no=1, name="Test", summary="")
            slot = SaveSlotModel(id=f"s-{suffix}", user_id=user.id, slot_number=1, name="Test")
            db.add_all([chapter, slot])
            db.flush()
            sessions = [SessionModel(id=f"session-{i}-{suffix}", user_id=user.id, world_id=world.id, save_slot_id=slot.id, current_chapter_id=chapter.id, status="active") for i in range(2)]
            db.add_all(sessions)
            db.commit()
        session_ids = [row.id for row in sessions]

        command.downgrade(config, "024")
        inspector = inspect(engine)
        legacy_columns = {column["name"] for column in inspector.get_columns("turn_transactions")}
        assert "request_fingerprint" not in legacy_columns
        assert "lease_expires_at" not in legacy_columns
        assert "fencing_generation" not in legacy_columns
        legacy_unique_columns = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("turn_transactions")}
        assert ("idempotency_key",) in legacy_unique_columns
        assert ("session_id", "idempotency_key") not in legacy_unique_columns

        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO turn_transactions (id, session_id, turn_no, idempotency_key, status, started_at)
                VALUES ('hist-event', :s0, 11, 'hist-event-key', 'aborted', now()),
                       ('hist-empty', :s0, 12, 'hist-empty-key', 'pending', now()),
                       ('hist-residue', :s0, 13, 'hist-residue-key', 'pending', now()),
                       ('hist-null', :s1, 14, 'hist-null-key', 'pending', now())"""), {"s0": session_ids[0], "s1": session_ids[1]})
            conn.execute(text("""INSERT INTO event_logs (id, session_id, turn_no, event_type, input_text, occurred_at)
                VALUES ('hist-player', :sid, 11, 'player_turn', 'already done', now())"""), {"sid": session_ids[0]})
            conn.execute(text("""INSERT INTO game_events (id, transaction_id, session_id, turn_no, event_type, occurred_at)
                VALUES ('hist-partial', 'hist-residue', :sid, 13, 'world_changed', now())"""), {"sid": session_ids[0]})
        command.upgrade(config, "head")
        with engine.begin() as conn:
            conn.execute(text("UPDATE turn_transactions SET lease_expires_at = now() - interval '1 minute' WHERE id IN ('hist-empty', 'hist-residue', 'hist-null')"))

        from llm_rpg.core.turn_claim import create_or_resume_claim
        check = factory()
        try:
            recovered = create_or_resume_claim(check, session_ids[0], "hist-event-key", "candidate-fp", 11)
            assert recovered.status is ClaimStatus.RESUME_COMMITTED
            assert check.query(EventLogModel).filter_by(session_id=session_ids[0], turn_no=11, event_type="player_turn").count() == 1
            expired = create_or_resume_claim(check, session_ids[0], "replacement-empty", "candidate-fp", 12)
            assert expired.status is ClaimStatus.EXPIRED
            empty = check.get(TurnTransactionModel, "hist-empty")
            assert (empty.idempotency_key, empty.status) == ("hist-empty-key", "expired")
            inconsistent = create_or_resume_claim(check, session_ids[0], "replacement-residue", "candidate-fp", 13)
            assert inconsistent.status is ClaimStatus.LEGACY_INCONSISTENT
            residue = check.get(TurnTransactionModel, "hist-residue")
            assert residue.status == "pending" and residue.idempotency_key == "hist-residue-key"
            assert check.query(GameEventModel).filter_by(id="hist-partial").count() == 1
            unknown = check.get(TurnTransactionModel, "hist-null")
            assert unknown.request_fingerprint is None
            null_result = create_or_resume_claim(check, session_ids[1], "hist-null-key", "candidate-fp", 14)
            assert null_result.status is ClaimStatus.LEGACY
            assert check.get(TurnTransactionModel, "hist-null").idempotency_key == "hist-null-key"
        finally:
            check.rollback()
            check.close()

        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO turn_transactions
                (id, session_id, turn_no, idempotency_key, request_fingerprint, status, started_at)
                VALUES ('cross-a', :s0, 20, 'cross-reused', 'fp-a', 'pending', now()),
                       ('cross-b', :s1, 20, 'cross-reused', 'fp-b', 'pending', now())"""),
                {"s0": session_ids[0], "s1": session_ids[1]})
        before_columns = {column["name"] for column in inspect(engine).get_columns("turn_transactions")}
        with engine.connect() as conn:
            before_rows = conn.execute(text("SELECT id, session_id, turn_no, idempotency_key, request_fingerprint, status FROM turn_transactions ORDER BY id")).all()
        with pytest.raises(RuntimeError, match="reused across sessions"):
            command.downgrade(config, "024")
        after_columns = {column["name"] for column in inspect(engine).get_columns("turn_transactions")}
        with engine.connect() as conn:
            after_rows = conn.execute(text("SELECT id, session_id, turn_no, idempotency_key, request_fingerprint, status FROM turn_transactions ORDER BY id")).all()
        assert after_columns == before_columns
        assert after_rows == before_rows

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM turn_transactions WHERE idempotency_key = 'cross-reused'"))
        command.downgrade(config, "024")
        command.upgrade(config, "head")
        upgraded_inspector = inspect(engine)
        assert {column["name"] for column in upgraded_inspector.get_columns("turn_transactions")} >= {
            "request_fingerprint", "lease_expires_at", "fencing_generation"
        }
        upgraded_unique_columns = {tuple(item["column_names"]) for item in upgraded_inspector.get_unique_constraints("turn_transactions")}
        assert ("session_id", "idempotency_key") in upgraded_unique_columns
        assert ("idempotency_key",) not in upgraded_unique_columns
    finally:
        if engine is not None:
            engine.dispose()
        try:
            with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
        finally:
            admin_engine.dispose()
