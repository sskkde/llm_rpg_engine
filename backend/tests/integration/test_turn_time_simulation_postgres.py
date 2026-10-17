"""Phase-3 PostgreSQL-only gates (plan section 9.1).

SQLite/mock tests prove the slice's *logic*. They cannot prove that the advance's
writes really participate in one PostgreSQL transaction -- that a necessary write
failure rolls the cursor, the NPC positions, the token owner, the scheduled-step
states, the engine facts and their deltas back together, nor that the state
fingerprint still rejects a turn whose state moved while the model was answering.
This module fails (never silently degrades) when PostgreSQL is required.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from llm_rpg.core import time_simulation_rules as rules
from llm_rpg.core import turn_service
from llm_rpg.core.time_simulation import decode_run_state, PHASE3_NAMESPACE
from llm_rpg.core.time_simulation_persistence import load_simulation_context
from llm_rpg.scripts.seed_time_slice import seed_time_slice
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    EventLogModel,
    GameEventModel,
    SaveSlotModel,
    ScheduledEventModel,
    SessionInventoryItemModel,
    SessionModel,
    SessionNPCStateModel,
    SessionStateModel,
    StateDeltaModel,
    TurnTransactionModel,
    UserModel,
)

from .time_slice_fixtures import intent_stage_result, patch_intent_stage


@pytest.fixture
def pg_time_slice(monkeypatch):
    """An isolated PostgreSQL schema holding the seeded phase-3 slice world."""
    required = os.getenv("PHASE1_REQUIRE_POSTGRES") == "1"
    raw_url = os.getenv("PHASE1_TEST_DATABASE_URL")
    if required and not raw_url:
        pytest.fail("PHASE1_REQUIRE_POSTGRES=1 requires PHASE1_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("phase-3 PostgreSQL tests require PHASE1_TEST_DATABASE_URL")

    base_url = make_url(raw_url)
    if base_url.get_backend_name() != "postgresql":
        pytest.fail("PHASE1_TEST_DATABASE_URL must use PostgreSQL")
    assert base_url.drivername == "postgresql+psycopg2"

    schema = "turn_phase3_" + uuid.uuid4().hex
    admin_engine = create_engine(base_url)
    with admin_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = base_url.update_query_dict({"options": f"-csearch_path={schema},public"})
    engine = create_engine(isolated_url, pool_size=4, max_overflow=2)
    assert engine.dialect.name == "postgresql"
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    suffix = uuid.uuid4().hex
    db = factory()
    ids = seed_time_slice(db)
    user = UserModel(
        id=f"u-{suffix}",
        username=f"u-{suffix}",
        email=f"{suffix}@test.invalid",
        password_hash="x",
        is_admin=False,
    )
    slot = SaveSlotModel(id=f"slot-{suffix}", user_id=user.id, slot_number=1, name="存档")
    session = SessionModel(
        id=f"session-{suffix}",
        user_id=user.id,
        world_id=ids["world_id"],
        save_slot_id=slot.id,
        status="active",
    )
    db.add_all([user, slot, session])
    db.commit()
    session_id = session.id
    db.close()

    try:
        yield engine, factory, session_id, ids
    finally:
        engine.dispose()
        with admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def _phase3_idle_chain(monkeypatch) -> None:
    """Fix the input-intent output and keep the other stages off."""
    patch_intent_stage(monkeypatch, intent_stage_result("idle"))
    for name in (
        "_is_world_stage_enabled",
        "_is_scene_stage_enabled",
        "_is_npc_stage_enabled",
        "_is_narration_stage_enabled",
        "_is_memory_stage_enabled",
    ):
        monkeypatch.setattr(turn_service, name, lambda _db: False)


def _run(factory, session_id: str, player_input: str, **kwargs):
    db = factory()
    try:
        return turn_service.execute_turn_service(
            db, session_id, player_input, use_mock=True, **kwargs
        )
    finally:
        db.close()


def _cursor(factory, session_id: str):
    db = factory()
    try:
        row = db.query(SessionStateModel).filter_by(session_id=session_id).one()
        return decode_run_state((row.global_flags_json or {}).get(PHASE3_NAMESPACE))
    finally:
        db.close()


def _token_rows(factory, session_id: str):
    db = factory()
    try:
        return db.query(SessionInventoryItemModel).filter_by(session_id=session_id).all()
    finally:
        db.close()


def _npc_positions(factory, session_id: str):
    db = factory()
    try:
        return {
            row.npc_template_id: row.current_location_id
            for row in db.query(SessionNPCStateModel).filter_by(session_id=session_id)
        }
    finally:
        db.close()


def test_phase3_turn_commits_the_whole_timeline_in_one_transaction(
    pg_time_slice, monkeypatch
) -> None:
    engine, factory, session_id, ids = pg_time_slice
    _phase3_idle_chain(monkeypatch)

    result = _run(factory, session_id, "原地等待片刻")

    assert result.time_advance_result["actual_elapsed_minutes"] == 7
    assert result.time_advance_result["interrupted"] is True

    run_state = _cursor(factory, session_id)
    assert run_state.logical_tick == 7
    assert run_state.next_event_seq == 6

    token_rows = _token_rows(factory, session_id)
    assert len(token_rows) == 1
    assert token_rows[0].quantity == 1
    assert token_rows[0].owner_type == "npc"

    db = factory()
    try:
        npc_rows = {
            row.npc_template_id: row
            for row in db.query(SessionNPCStateModel).filter_by(session_id=session_id)
        }
        # A won the competition: the single token row now points at A's own state row.
        assert token_rows[0].owner_ref_id == npc_rows[ids["npc_ids"][rules.NPC_A_CODE]].id
        assert npc_rows[ids["npc_ids"][rules.NPC_A_CODE]].hidden_plan_state is not None

        scheduled = db.query(ScheduledEventModel).filter_by(session_id=session_id).all()
        statuses = {
            row.trigger_conditions_json[PHASE3_NAMESPACE]["step_key"]: row.status
            for row in scheduled
        }
        assert statuses["world.environment_interrupt@7"] == "triggered"
        assert statuses["npc_b.npc_take_item@5"] == "cancelled"
        assert statuses["npc_b.npc_travel_start@8"] == "pending"

        events = db.query(GameEventModel).filter_by(session_id=session_id).all()
        namespaced = [
            event for event in events if (event.result_json or {}).get(PHASE3_NAMESPACE)
        ]
        # The contract is that this turn's timeline carries sequences 0..5 exactly
        # once each. The physical row order of an unordered SELECT is NOT part of
        # that contract (PostgreSQL may return heap order, which varies with prior
        # inserts/DDL on the shared test database), so compare as a multiset.
        assert sorted(
            e.result_json[PHASE3_NAMESPACE]["sequence"] for e in namespaced
        ) == list(range(6))
        # Every delta points at a real engine event of the same transaction.
        deltas = db.query(StateDeltaModel).filter_by(session_id=session_id).all()
        assert deltas
        event_ids = {event.id for event in events}
        assert all(delta.source_event_id in event_ids for delta in deltas)
    finally:
        db.close()


def test_necessary_write_failure_rolls_back_the_whole_phase3_advance(
    pg_time_slice, monkeypatch
) -> None:
    engine, factory, session_id, ids = pg_time_slice
    _phase3_idle_chain(monkeypatch)

    first = _run(factory, session_id, "原地等待片刻")
    assert first.time_advance_result["actual_elapsed_minutes"] == 7
    cursor_before = _cursor(factory, session_id)
    owner_before = _token_rows(factory, session_id)[0].owner_ref_id

    def fail_after_the_advance(*_args, **_kwargs):
        raise RuntimeError("injected necessary-write failure after the advance")

    # ``update_last_played`` runs after the advance's writes, inside the same unit
    # of work, so this proves the cursor/owner/step/event/delta writes all roll back.
    monkeypatch.setattr(
        turn_service.SessionRepository, "update_last_played", fail_after_the_advance
    )

    with pytest.raises(RuntimeError, match="injected necessary-write failure"):
        _run(factory, session_id, "继续等待", idempotency_key="pg-phase3-rollback")

    assert _cursor(factory, session_id) == cursor_before
    token_rows = _token_rows(factory, session_id)
    assert len(token_rows) == 1
    assert token_rows[0].owner_ref_id == owner_before

    db = factory()
    try:
        assert (
            db.query(GameEventModel)
            .filter_by(session_id=session_id, turn_no=2)
            .count()
            == 0
        )
        assert (
            db.query(StateDeltaModel).filter_by(session_id=session_id, turn_no=2).count()
            == 0
        )
        assert (
            db.query(EventLogModel).filter_by(session_id=session_id, turn_no=2).count() == 0
        )
        claim = (
            db.query(TurnTransactionModel)
            .filter_by(session_id=session_id, idempotency_key="pg-phase3-rollback")
            .one()
        )
        assert claim.status == "aborted"
        # The first turn's durable timeline is untouched.
        assert (
            db.query(ScheduledEventModel)
            .filter_by(session_id=session_id, status="pending")
            .count()
            == 1
        )
    finally:
        db.close()


def test_state_change_during_the_model_wait_is_rejected_for_phase3(
    pg_time_slice, monkeypatch
) -> None:
    engine, factory, session_id, ids = pg_time_slice
    _phase3_idle_chain(monkeypatch)

    first = _run(factory, session_id, "原地等待片刻")
    assert first.time_advance_result["actual_elapsed_minutes"] == 7
    cursor_before = _cursor(factory, session_id)

    original_execute_stages = turn_service._execute_llm_stages

    def mutate_during_model_wait(**kwargs):
        mutator = factory()
        try:
            row = mutator.query(SessionStateModel).filter_by(session_id=session_id).one()
            row.global_flags_json = {**row.global_flags_json, "injected": True}
            mutator.commit()
        finally:
            mutator.close()
        return original_execute_stages(**kwargs)

    monkeypatch.setattr(turn_service, "_execute_llm_stages", mutate_during_model_wait)

    with pytest.raises(turn_service.TurnStateConflictError):
        _run(factory, session_id, "继续等待", idempotency_key="pg-phase3-conflict")

    # The rejected turn committed nothing: the cursor and the token owner stand.
    assert _cursor(factory, session_id).logical_tick == cursor_before.logical_tick
    token_rows = _token_rows(factory, session_id)
    assert len(token_rows) == 1
    db = factory()
    try:
        assert (
            db.query(GameEventModel)
            .filter_by(session_id=session_id, turn_no=2)
            .count()
            == 0
        )
    finally:
        db.close()


def test_phase3_context_rebuilds_from_the_database_alone(
    pg_time_slice, monkeypatch
) -> None:
    """A restart re-reads the slice from PostgreSQL; nothing lives in process state."""
    engine, factory, session_id, ids = pg_time_slice
    _phase3_idle_chain(monkeypatch)
    _run(factory, session_id, "原地等待片刻")

    db = factory()
    try:
        ctx = load_simulation_context(db, session_id)
        assert ctx.run_state.logical_tick == 7
        assert ctx.state.npc_positions[rules.NPC_A_CODE] == rules.LOCATION_TRIAL_PEAK
        assert ctx.state.item_owner_type == "npc"
        assert ctx.state.item_owner_ref == rules.NPC_A_CODE
        assert [row.step.step_key for row in ctx.pending_steps] == [
            "npc_b.npc_travel_start@8"
        ]
    finally:
        db.close()
