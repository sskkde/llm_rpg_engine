"""Phase 2 PostgreSQL-only gates for the LLM authority chain.

SQLite/mock tests prove the *logic* of the contract -> authorization ->
adjudication chain. They cannot prove that a necessary write failure really rolls
the whole turn back under a real PostgreSQL transaction, nor that the
state-fingerprint revalidation still rejects a turn whose state moved while the
model was answering. Both are required by the implementation plan (section 5) and
are gated here: this module fails, never silently degrades, when PostgreSQL is
required but unavailable.
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from llm_rpg.core import turn_service
from llm_rpg.llm.proposal_pipeline import ProductionContractOutcome, ProposalPipeline
from llm_rpg.models.action_contract import PlayerIntentV2
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel,
    EventLogModel,
    GameEventModel,
    LocationModel,
    NPCTemplateModel,
    SaveSlotModel,
    SessionModel,
    SessionNPCStateModel,
    SessionPlayerStateModel,
    SessionStateModel,
    StateDeltaModel,
    TurnTransactionModel,
    UserModel,
    WorldModel,
)


@pytest.fixture
def pg_authority(monkeypatch):
    """An isolated PostgreSQL world for the authority-chain gates."""
    required = os.getenv("PHASE1_REQUIRE_POSTGRES") == "1"
    raw_url = os.getenv("PHASE1_TEST_DATABASE_URL")
    if required and not raw_url:
        pytest.fail("PHASE1_REQUIRE_POSTGRES=1 requires PHASE1_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("authority PostgreSQL tests require PHASE1_TEST_DATABASE_URL")

    base_url = make_url(raw_url)
    if base_url.get_backend_name() != "postgresql":
        pytest.fail("PHASE1_TEST_DATABASE_URL must use PostgreSQL")
    assert base_url.drivername == "postgresql+psycopg2"

    schema = "turn_authority_" + uuid.uuid4().hex
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
    user = UserModel(
        id=f"u-{suffix}", username=f"u-{suffix}", email=f"{suffix}@test.invalid",
        password_hash="x", is_admin=False,
    )
    world = WorldModel(
        id=f"w-{suffix}", code=f"w-{suffix}", name="测试世界", genre="xianxia", status="active",
    )
    db.add_all([user, world])
    db.flush()
    chapter = ChapterModel(id=f"c-{suffix}", world_id=world.id, chapter_no=1, name="第一章")
    slot = SaveSlotModel(id=f"slot-{suffix}", user_id=user.id, slot_number=1, name="存档")
    session = SessionModel(
        id=f"session-{suffix}", user_id=user.id, world_id=world.id, save_slot_id=slot.id,
        current_chapter_id=chapter.id, status="active",
    )
    db.add_all([chapter, slot, session])
    db.flush()

    square = LocationModel(
        id=f"loc-square-{suffix}", world_id=world.id, chapter_id=chapter.id,
        code="square", name="宗门广场", tags=["public", "starting_point"],
        access_rules={"always_accessible": True},
    )
    hall = LocationModel(
        id=f"loc-hall-{suffix}", world_id=world.id, chapter_id=chapter.id,
        code="trial_hall", name="试炼堂", tags=["public"],
        access_rules={"always_accessible": True},
    )
    guide = NPCTemplateModel(
        id=f"npc-guide-{suffix}", world_id=world.id, code="guide", name="向导",
        role_type="guide", is_major_npc=True,
    )
    db.add_all([square, hall, guide])
    db.flush()
    db.add(SessionNPCStateModel(
        id=f"snpc-guide-{suffix}", session_id=session.id, npc_template_id=guide.id,
        current_location_id=square.id, status_flags={"status": "alive"},
    ))
    db.add(SessionStateModel(
        id=f"ss-{suffix}", session_id=session.id, current_location_id=square.id,
        current_time="第1日 辰时", time_phase="辰时", active_mode="exploration",
        global_flags_json={},
    ))
    db.add(SessionPlayerStateModel(
        id=f"sps-{suffix}", session_id=session.id, realm_stage="炼气一层",
        hp=100, max_hp=100, stamina=100, spirit_power=100,
    ))
    db.commit()
    session_id = session.id
    db.close()

    yield engine, factory, session_id, square.id, hall.id

    engine.dispose()
    with admin_engine.begin() as conn:
        # Child rows first: ``memory_facts``/``npc_beliefs`` reference ``event_logs``
        # and ``state_deltas`` references ``game_events``.
        for table in (
            "state_deltas", "validation_reports", "llm_stage_results",
            "memory_facts", "memory_summaries", "npc_beliefs", "npc_private_memories",
            "game_events", "event_logs", "turn_transactions",
        ):
            conn.execute(
                text(f"DELETE FROM {table} WHERE session_id = :sid"), {"sid": session_id}
            )
        conn.execute(text("DELETE FROM session_npc_states WHERE session_id = :sid"), {"sid": session_id})
        conn.execute(text("DELETE FROM session_player_states WHERE session_id = :sid"), {"sid": session_id})
        conn.execute(text("DELETE FROM session_states WHERE session_id = :sid"), {"sid": session_id})
        conn.execute(text("DELETE FROM sessions WHERE id = :sid"), {"sid": session_id})
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    admin_engine.dispose()


def _authority_chain(monkeypatch, intent: PlayerIntentV2):
    """Route the production chain to a fixed legal intent and a quiet narration."""
    async def fake_player_intent(*_args, **_kwargs):
        return ProductionContractOutcome(contract=intent)

    async def fake_narration(*_args, **_kwargs):
        from llm_rpg.models.action_contract import NarrationV2

        return ProductionContractOutcome(
            contract=NarrationV2(contract_version=2, text="你静静地站着。")
        )

    monkeypatch.setattr(
        ProposalPipeline, "generate_player_intent_production", fake_player_intent
    )
    monkeypatch.setattr(
        ProposalPipeline, "generate_narration_production", fake_narration
    )
    for name in (
        "_is_input_intent_stage_enabled",
        "_is_narration_stage_enabled",
        "_is_memory_stage_enabled",
    ):
        monkeypatch.setattr(turn_service, name, lambda _db: True)
    for name in (
        "_is_world_stage_enabled",
        "_is_scene_stage_enabled",
        "_is_npc_stage_enabled",
    ):
        monkeypatch.setattr(turn_service, name, lambda _db: False)
    monkeypatch.setattr(turn_service, "_validate_explicit_llm_config", lambda _db: None)


def test_necessary_write_failure_rolls_back_the_whole_turn(pg_authority, monkeypatch):
    """A fact-event write failure must abort the turn, not degrade to a fallback."""
    engine, factory, session_id, square_id, hall_id = pg_authority
    _authority_chain(
        monkeypatch,
        PlayerIntentV2(contract_version=2, intent={"action_type": "idle"}),
    )

    original_create_game_event = turn_service._create_game_event
    calls = {"n": 0}

    def failing_create_game_event(*args, **kwargs):
        calls["n"] += 1
        # The player action's cause event is the first fact event of the turn.
        if calls["n"] == 1:
            raise RuntimeError("injected necessary-write failure")
        return original_create_game_event(*args, **kwargs)

    monkeypatch.setattr(turn_service, "_create_game_event", failing_create_game_event)

    db = factory()
    try:
        with pytest.raises(RuntimeError, match="injected necessary-write failure"):
            turn_service.execute_turn_service(
                db, session_id, "我等待", idempotency_key="pg-necessary-write"
            )
    finally:
        db.close()

    verify = factory()
    try:
        # Nothing from the failed turn may be durable...
        for model in (EventLogModel, GameEventModel, StateDeltaModel):
            assert verify.query(model).filter_by(session_id=session_id).count() == 0, (
                model.__tablename__
            )
        # ...and the claim is fenced as aborted rather than left pending.
        claim = verify.query(TurnTransactionModel).filter_by(session_id=session_id).one()
        assert claim.status == "aborted"
    finally:
        verify.close()


def test_state_change_before_commit_is_rejected(pg_authority, monkeypatch):
    """A concurrent state change invalidates the turn instead of committing stale facts."""
    engine, factory, session_id, square_id, hall_id = pg_authority
    _authority_chain(
        monkeypatch,
        PlayerIntentV2(
            contract_version=2,
            intent={"action_type": "move", "target_location_id": hall_id},
        ),
    )

    original_narration = turn_service._execute_narration_stage

    def mutate_state_then_continue(*args, **kwargs):
        # The authoritative commit has already happened by this point, so this
        # mutation is only used to prove the *revalidation* path below; the real
        # gate is exercised by the second call.
        return original_narration(*args, **kwargs)

    monkeypatch.setattr(turn_service, "_execute_narration_stage", mutate_state_then_continue)

    # Mutate the session state between the fingerprint snapshot and the final
    # write section, from an independent session, so the fingerprint changes.
    original_execute_stages = turn_service._execute_llm_stages

    def mutate_during_model_wait(**kwargs):
        mutator = factory()
        try:
            row = mutator.query(SessionStateModel).filter_by(session_id=session_id).one()
            row.global_flags_json = {"injected": True}
            mutator.commit()
        finally:
            mutator.close()
        return original_execute_stages(**kwargs)

    monkeypatch.setattr(turn_service, "_execute_llm_stages", mutate_during_model_wait)

    db = factory()
    try:
        with pytest.raises(turn_service.TurnStateConflictError):
            turn_service.execute_turn_service(
                db, session_id, "去试炼堂", idempotency_key="pg-state-conflict"
            )
    finally:
        db.close()

    verify = factory()
    try:
        # The turn must not have committed a location change on stale state.
        state = verify.query(SessionStateModel).filter_by(session_id=session_id).one()
        assert state.current_location_id == square_id
        assert verify.query(EventLogModel).filter_by(session_id=session_id).count() == 0
        claim = verify.query(TurnTransactionModel).filter_by(session_id=session_id).one()
        assert claim.status == "aborted"
    finally:
        verify.close()


def test_legal_move_commits_with_engine_action_delta_source(pg_authority, monkeypatch):
    """Under real PostgreSQL the adjudicated move commits and its delta cause is real."""
    engine, factory, session_id, square_id, hall_id = pg_authority
    _authority_chain(
        monkeypatch,
        PlayerIntentV2(
            contract_version=2,
            intent={"action_type": "move", "target_location_id": hall_id},
        ),
    )

    db = factory()
    try:
        result = turn_service.execute_turn_service(
            db, session_id, "去试炼堂", idempotency_key="pg-legal-move"
        )
    finally:
        db.close()

    assert result.action_resolution["status"] == "accepted"
    assert result.action_resolution["reason_code"] is None

    verify = factory()
    try:
        state = verify.query(SessionStateModel).filter_by(session_id=session_id).one()
        assert state.current_location_id == hall_id

        deltas = verify.query(StateDeltaModel).filter_by(session_id=session_id).all()
        assert deltas
        event_ids = {
            row.id for row in verify.query(GameEventModel).filter_by(
                session_id=session_id
            ).all()
        }
        for delta in deltas:
            assert delta.source_event_id in event_ids
            source = verify.query(GameEventModel).filter_by(id=delta.source_event_id).one()
            assert source.event_type != "narration"
    finally:
        verify.close()
