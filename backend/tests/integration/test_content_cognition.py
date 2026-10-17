"""Integration coverage for the content_v1 event-to-cognition read/write loop."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.core.content_cognition import (
    build_cognition_plan,
    write_content_cognition,
)
from llm_rpg.core.npc_decision_adapter import enrich_major_npc_decision_context
from llm_rpg.core.npc_memory_retrieval_service import (
    adapt_legacy_memory_row,
    retrieve_major_npc_memories,
)
from llm_rpg.core.time_simulation import CognitionSpec, SimulationEvent
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    GameEventModel,
    LocationModel,
    MemoryFactModel,
    NPCPrivateMemoryModel,
    NPCTemplateModel,
    SessionModel,
    SessionNPCStateModel,
    StoryPackageVersionModel,
    TurnTransactionModel,
    UserModel,
    WorldModel,
    generate_uuid,
)


_BINDING_HASH = "c" * 64
_MISTY_KNOWLEDGE_PATH = (
    Path(__file__).resolve().parents[3] / "content_packs" / "misty_ford" / "knowledge.yaml"
)


def _make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory(), factory, engine


def _seed_bound_world(db):
    token = generate_uuid()[:8]
    user = UserModel(
        id=f"user-{token}",
        username=f"cognition-{token}",
        email=f"cognition-{token}@example.test",
        password_hash="test",
    )
    world = WorldModel(
        id=f"world-{token}",
        code=f"misty-{token}",
        name="Misty Ford Test",
        genre="fantasy",
        status="active",
        ruleset_json={
            "content_profile": {
                "id": "content_v1",
                "schema_version": 1,
                "engine_rules_version": 1,
                "runtime_hash": _BINDING_HASH,
            }
        },
    )
    version = StoryPackageVersionModel(
        id=f"version-{token}",
        story_package_id=f"package-{token}",
        version="1.0.0",
        status="published",
        world_id=None,
        runtime_bundle_json={},
        runtime_hash=_BINDING_HASH,
        runtime_schema_version=1,
        published_at=datetime.now(),
    )
    db.add_all([user, world, version])
    db.flush()
    # Break the world/version FK cycle for SQLite, then set the final binding.
    world.story_package_version_id = version.id
    version.world_id = world.id
    db.flush()

    locations = {
        "east_bank": LocationModel(
            id=f"loc-east-{token}", world_id=world.id, code="east_bank", name="East Bank"
        ),
        "watch_house": LocationModel(
            id=f"loc-watch-{token}", world_id=world.id, code="watch_house", name="Watch House"
        ),
        "west_bank": LocationModel(
            id=f"loc-west-{token}", world_id=world.id, code="west_bank", name="West Bank"
        ),
    }
    db.add_all(locations.values())
    db.flush()

    templates = {
        "ferryman": NPCTemplateModel(
            id=f"npc-ferry-{token}",
            world_id=world.id,
            code="ferryman",
            name="Ferryman",
            is_major_npc=True,
            initial_location_id=locations["east_bank"].id,
        ),
        "herbalist": NPCTemplateModel(
            id=f"npc-herbalist-{token}",
            world_id=world.id,
            code="herbalist",
            name="Herbalist",
            is_major_npc=True,
            initial_location_id=locations["watch_house"].id,
        ),
    }
    db.add_all(templates.values())
    db.flush()
    states = {
        "ferryman": SessionNPCStateModel(
            id=f"state-ferry-{token}",
            session_id=f"session-{token}",
            npc_template_id=templates["ferryman"].id,
            current_location_id=locations["east_bank"].id,
            status_flags={"alive": True},
        ),
        "herbalist": SessionNPCStateModel(
            id=f"state-herbalist-{token}",
            session_id=f"session-{token}",
            npc_template_id=templates["herbalist"].id,
            current_location_id=locations["watch_house"].id,
            status_flags={"alive": True},
        ),
    }
    session = SessionModel(
        id=f"session-{token}",
        user_id=user.id,
        world_id=world.id,
        story_package_version_id=version.id,
        status="active",
    )
    # SessionNPCState rows reference the session; add it before flushing them.
    db.add(session)
    db.flush()
    db.add_all(states.values())
    transaction = TurnTransactionModel(
        id=f"transaction-{token}",
        session_id=session.id,
        turn_no=4,
        idempotency_key=f"cognition-{token}",
        status="committed",
        started_at=datetime.now(),
        committed_at=datetime.now(),
    )
    db.add(transaction)
    db.flush()
    return {
        "session": session,
        "world": world,
        "version": version,
        "locations": locations,
        "templates": templates,
        "states": states,
        "transaction": transaction,
    }


def _add_game_event(db, seeded, *, event_type, visibility_scope="hidden", payload=None, event_id=None):
    event_id = event_id or generate_uuid()
    payload = payload or {}
    event = GameEventModel(
        id=event_id,
        transaction_id=seeded["transaction"].id,
        session_id=seeded["session"].id,
        turn_no=4,
        event_type=event_type,
        actor_id="world",
        visibility_scope=visibility_scope,
        public_payload_json=payload if visibility_scope == "player_visible" else None,
        private_payload_json=payload if visibility_scope != "player_visible" else None,
        result_json={"tick": 4},
        occurred_at=datetime.now(),
    )
    db.add(event)
    db.flush()
    return event


def _misty_knowledge_rules():
    with _MISTY_KNOWLEDGE_PATH.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)["knowledge_rules"]


def _route_changed_plan(db, seeded):
    source_payload = {
        "from": "east_bank",
        "to": "west_bank",
        "open": False,
        "tick": 4,
    }
    game_event = _add_game_event(
        db,
        seeded,
        event_type="route_changed",
        visibility_scope="hidden",
        payload=source_payload,
    )
    event = SimulationEvent(
        seq=4,
        tick=4,
        phase=1,
        actor_code="world",
        step_code="rule:close_route@4",
        event_type="route_changed",
        visibility_scope="hidden",
        private_payload=source_payload,
    )
    cognition = CognitionSpec(
        seq=0,
        subject_type="npc",
        subject_ref="ferryman",
        tick=4,
        content="东岸通往西岸的桥路状态改变了。",
        visibility="npc_private",
        memory_kind="observation",
        source_step_code=event.step_code,
        event_seq=event.seq,
    )
    advance_result = SimpleNamespace(
        events=[event],
        cognition=[cognition],
        final_state=SimpleNamespace(
            npc_alive={"ferryman": True, "herbalist": True}
        ),
    )
    entries, player_entries = build_cognition_plan(
        advance_result=advance_result,
        knowledge_rules=_misty_knowledge_rules(),
        binding_hash=_BINDING_HASH,
        version_id=seeded["version"].id,
        tick_positions={4: {"ferryman": "east_bank", "herbalist": "watch_house"}},
        event_ids={event.seq: game_event.id},
    )
    return game_event, entries, player_entries


def _write_route_plan(db, seeded):
    game_event, entries, player_entries = _route_changed_plan(db, seeded)
    written = write_content_cognition(
        db,
        session_id=seeded["session"].id,
        version_id=seeded["version"].id,
        binding_hash=_BINDING_HASH,
        entries=entries,
        player_entries=player_entries,
    )
    return game_event, entries, player_entries, written


def _close(db, engine):
    db.close()
    engine.dispose()


def test_content_cognition_writes_standard_rows():
    db, _, engine = _make_db()
    try:
        seeded = _seed_bound_world(db)
        game_event, entries, _, written = _write_route_plan(db, seeded)
        rows = db.query(NPCPrivateMemoryModel).filter(
            NPCPrivateMemoryModel.session_id == seeded["session"].id
        ).all()

        assert written == 1
        assert len(entries) == 1
        assert len(rows) == 1
        row = rows[0]
        assert row.memory_type == "episodic"
        assert row.memory_kind == "observation"
        assert row.visibility == "npc_private"
        assert row.source_event_ids_json == [game_event.id]
        assert row.source_turn_no == game_event.turn_no
        assert row.location_id == seeded["locations"]["east_bank"].id
        assert row.derivation_key is not None
    finally:
        _close(db, engine)


def test_non_observer_gets_no_memory():
    db, _, engine = _make_db()
    try:
        seeded = _seed_bound_world(db)
        game_event, entries, _, _ = _write_route_plan(db, seeded)
        assert [entry.subject_ref for entry in entries] == ["ferryman"]
        ferryman_rows = [
            row for row in db.query(NPCPrivateMemoryModel).filter(
                NPCPrivateMemoryModel.session_id == seeded["session"].id,
                NPCPrivateMemoryModel.npc_template_id == seeded["templates"]["ferryman"].id,
            ).all()
            if game_event.id in (row.source_event_ids_json or [])
        ]
        herbalist_rows = [
            row for row in db.query(NPCPrivateMemoryModel).filter(
                NPCPrivateMemoryModel.session_id == seeded["session"].id,
                NPCPrivateMemoryModel.npc_template_id == seeded["templates"]["herbalist"].id,
            ).all()
            if game_event.id in (row.source_event_ids_json or [])
        ]
        assert len(ferryman_rows) == 1
        assert herbalist_rows == []
    finally:
        _close(db, engine)


def test_retrieval_closed_loop_across_db_sessions(monkeypatch):
    monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
    db, factory, engine = _make_db()
    try:
        seeded = _seed_bound_world(db)
        game_event, _, _, written = _write_route_plan(db, seeded)
        session_id = seeded["session"].id
        ferryman_template_id = seeded["templates"]["ferryman"].id
        herbalist_template_id = seeded["templates"]["herbalist"].id
        db.commit()
        db.close()

        # Deliberately use a new ORM session to prove retrieval is DB-backed.
        reopened = factory()
        try:
            ferryman_context = enrich_major_npc_decision_context(
                {}, reopened, session_id, ferryman_template_id, current_turn=5
            )
            herbalist_context = enrich_major_npc_decision_context(
                {}, reopened, session_id, herbalist_template_id, current_turn=5
            )
            memories = ferryman_context["retrieved_private_memories"]
            assert written == 1
            assert len(memories) == 1
            assert memories[0]["source_event_ids"] == [game_event.id]
            assert reopened.query(GameEventModel.id).filter(
                GameEventModel.id == memories[0]["source_event_ids"][0],
                GameEventModel.session_id == session_id,
            ).one()[0] == game_event.id
            assert herbalist_context["retrieved_private_memories"] == []
            assert herbalist_context["used_memory_ids"] == []
        finally:
            reopened.close()
    finally:
        engine.dispose()


def test_derivation_key_makes_writes_idempotent():
    db, _, engine = _make_db()
    try:
        seeded = _seed_bound_world(db)
        _, entries, player_entries = _route_changed_plan(db, seeded)
        first = write_content_cognition(
            db,
            session_id=seeded["session"].id,
            version_id=seeded["version"].id,
            binding_hash=_BINDING_HASH,
            entries=entries,
            player_entries=player_entries,
        )
        count_after_first = db.query(NPCPrivateMemoryModel).count()
        second = write_content_cognition(
            db,
            session_id=seeded["session"].id,
            version_id=seeded["version"].id,
            binding_hash=_BINDING_HASH,
            entries=entries,
            player_entries=player_entries,
        )
        count_after_second = db.query(NPCPrivateMemoryModel).count()
        assert first == 1
        assert second == 0
        assert count_after_second == count_after_first == 1
    finally:
        _close(db, engine)


def test_legacy_phase3_rows_remain_readable(monkeypatch):
    monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
    db, _, engine = _make_db()
    try:
        seeded = _seed_bound_world(db)
        event, _, _, _ = _write_route_plan(db, seeded)
        legacy = NPCPrivateMemoryModel(
            id=generate_uuid(),
            session_id=seeded["session"].id,
            npc_id=seeded["states"]["ferryman"].id,
            npc_template_id=seeded["templates"]["ferryman"].id,
            memory_type="action",
            content="Legacy phase-3 action",
            memory_text="Legacy phase-3 action",
            source_event_ids_json=[event.id],
            created_turn=4,
            last_accessed_turn=4,
            recall_count=0,
            memory_kind=None,
            visibility="private",
            status="active",
        )
        rejected = NPCPrivateMemoryModel(
            id=generate_uuid(),
            session_id=seeded["session"].id,
            npc_id=seeded["states"]["ferryman"].id,
            npc_template_id=seeded["templates"]["ferryman"].id,
            memory_type="episodic",
            content="Unknown visibility must remain hidden",
            memory_text="Unknown visibility must remain hidden",
            created_turn=4,
            last_accessed_turn=4,
            recall_count=0,
            visibility="unrecognized_visibility",
            status="active",
        )
        db.add_all([legacy, rejected])
        db.flush()
        before = tuple(db.execute(
            text("SELECT * FROM npc_private_memories WHERE id = :memory_id"),
            {"memory_id": legacy.id},
        ).one())

        result = retrieve_major_npc_memories(
            db, seeded["session"].id, seeded["templates"]["ferryman"].id
        )
        retrieved = next(memory for memory in result.memories if memory.memory_id == legacy.id)
        after = tuple(db.execute(
            text("SELECT * FROM npc_private_memories WHERE id = :memory_id"),
            {"memory_id": legacy.id},
        ).one())

        assert adapt_legacy_memory_row("action", "private") == ("episodic", "npc_private")
        assert adapt_legacy_memory_row("episodic", "npc_shared") == ("episodic", "npc_shared")
        assert adapt_legacy_memory_row("action", "unrecognized_visibility") == (
            "episodic", "unrecognized_visibility"
        )
        assert retrieved.memory_type == "episodic"
        assert retrieved.memory_kind == "action"
        assert retrieved.source_event_ids == [event.id]
        assert legacy.id in result.used_memory_ids
        assert rejected.id not in result.used_memory_ids
        assert before == after
    finally:
        _close(db, engine)


def test_player_knowledge_is_not_shared_into_npc_context(monkeypatch):
    monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
    db, _, engine = _make_db()
    try:
        seeded = _seed_bound_world(db)
        game_event = _add_game_event(
            db,
            seeded,
            event_type="player_action_completed",
            visibility_scope="player_visible",
            payload={"action_type": "idle", "action_kind": "idle", "tick": 4},
        )
        event = SimulationEvent(
            seq=7,
            tick=4,
            phase=4,
            actor_code="player",
            step_code="player.player_continuous_complete@4",
            event_type="player_action_completed",
            visibility_scope="player_visible",
            public_payload={"action_type": "idle", "action_kind": "idle", "tick": 4},
        )
        advance_result = SimpleNamespace(events=[event], cognition=[], final_state=SimpleNamespace(npc_alive={}))
        _, player_entries = build_cognition_plan(
            advance_result=advance_result,
            knowledge_rules=_misty_knowledge_rules(),
            binding_hash=_BINDING_HASH,
            version_id=seeded["version"].id,
            tick_positions={4: {"ferryman": "east_bank", "herbalist": "watch_house"}},
            event_ids={event.seq: game_event.id},
        )
        assert len(player_entries) == 1
        written = write_content_cognition(
            db,
            session_id=seeded["session"].id,
            version_id=seeded["version"].id,
            binding_hash=_BINDING_HASH,
            entries=(),
            player_entries=player_entries,
        )
        fact = db.query(MemoryFactModel).filter(
            MemoryFactModel.session_id == seeded["session"].id,
            MemoryFactModel.fact_type == "player_knowledge",
            MemoryFactModel.subject_ref == "player",
        ).one()
        db.commit()

        assert written == 1
        assert fact.source_event_id is None
        assert fact.source_game_event_id == game_event.id
        for template in seeded["templates"].values():
            context = enrich_major_npc_decision_context(
                {"memory_facts": [fact]},
                db,
                seeded["session"].id,
                template.id,
            )
            assert fact.id not in repr(context)
            assert "player_knowledge" not in repr(context)
    finally:
        _close(db, engine)


def test_flag_off_authorizes_no_memory(monkeypatch):
    monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
    db, _, engine = _make_db()
    try:
        seeded = _seed_bound_world(db)
        event, _, _, _ = _write_route_plan(db, seeded)
        memory = next(
            row for row in db.query(NPCPrivateMemoryModel).filter(
                NPCPrivateMemoryModel.session_id == seeded["session"].id,
            ).all()
            if event.id in (row.source_event_ids_json or [])
        )
        before_count = db.query(NPCPrivateMemoryModel).count()
        original_context = {"profile": {"name": "Ferryman"}}
        context = enrich_major_npc_decision_context(
            original_context,
            db,
            seeded["session"].id,
            seeded["templates"]["ferryman"].id,
        )
        retrieved = retrieve_major_npc_memories(
            db, seeded["session"].id, seeded["templates"]["ferryman"].id
        )
        assert context is original_context
        assert "retrieved_private_memories" not in context
        assert retrieved.memories == []
        assert retrieved.used_memory_ids == []
        assert db.query(NPCPrivateMemoryModel).count() == before_count == 1
        assert memory.id
    finally:
        _close(db, engine)
