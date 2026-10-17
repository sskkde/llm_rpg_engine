"""Compatibility, no-op initialization, binding failures and safe projections."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.core.content_publish_service import publish_content_pack_version
from llm_rpg.core.content_runtime import CONTENT_NAMESPACE, ContentRuntimeError
from llm_rpg.core.instance_snapshot_service import (
    ContentSnapshotUnsupportedError,
    compute_checksum,
    create_baseline_snapshot,
    create_manual_snapshot,
    apply_snapshot,
)
from llm_rpg.core.playthrough_instance_service import create_content_v1_instance
from llm_rpg.core.session_initialization import (
    initialize_session_story_state,
    plan_session_story_state,
)
from llm_rpg.core.turn_service import execute_turn_service
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ChapterModel,
    InstanceSnapshotModel,
    LocationModel,
    NPCTemplateModel,
    QuestTemplateModel,
    SaveSlotModel,
    ScheduledEventModel,
    SessionInventoryItemModel,
    SessionModel,
    SessionNPCStateModel,
    SessionPlayerStateModel,
    SessionQuestStateModel,
    SessionStateModel,
    StoryPackageVersionModel,
    TurnTransactionModel,
    UserModel,
    WorldModel,
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_MISTY_FORD = _REPO_ROOT / "content_packs" / "misty_ford"


@pytest.fixture
def runtime_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        yield db, factory
    finally:
        db.close()
        engine.dispose()


def _user(db) -> UserModel:
    token = uuid.uuid4().hex[:12]
    user = UserModel(username=f"content-compat-{token}", is_admin=False)
    db.add(user)
    db.flush()
    return user


def _content_instance(db) -> dict:
    version_id = publish_content_pack_version(db, pack_dir=_MISTY_FORD).version_id
    return create_content_v1_instance(db, user_id=_user(db).id, version_id=version_id)


def _row_snapshot(db, session_id: str) -> dict[str, list[dict]]:
    models_and_fields = (
        (SessionStateModel, ("id", "session_id", "current_time", "time_phase", "current_location_id", "active_mode", "global_flags_json")),
        (SessionPlayerStateModel, ("id", "session_id", "realm_stage", "hp", "stamina", "spirit_power", "conditions_json")),
        (SessionNPCStateModel, ("id", "session_id", "npc_template_id", "current_location_id", "status_flags", "hidden_plan_state")),
        (SessionQuestStateModel, ("id", "session_id", "quest_template_id", "status", "progress_json")),
        (SessionInventoryItemModel, ("id", "session_id", "item_template_id", "owner_type", "owner_ref_id", "instance_key")),
        (ScheduledEventModel, ("id", "session_id", "status", "trigger_conditions_json")),
    )
    result = {}
    for model, fields in models_and_fields:
        rows = db.query(model).filter_by(session_id=session_id).all()
        result[model.__tablename__] = sorted(
            [{field: getattr(row, field) for field in fields} for row in rows],
            key=lambda row: row["id"],
        )
    return result


def test_generic_initializer_does_not_touch_content_v1(runtime_db):
    db, _ = runtime_db
    created = _content_instance(db)
    session_id = created["session_id"]
    before = _row_snapshot(db, session_id)

    plan = plan_session_story_state(db, session_id)
    assert plan.session_state is None
    assert plan.player_state is None
    assert plan.npc_states == []
    assert plan.quest_states == []
    assert plan.inventory_items == []
    assert plan.scheduled_events == []
    initialize_session_story_state(db, session_id)

    after = _row_snapshot(db, session_id)
    assert after == before
    assert db.query(LocationModel).filter_by(world_id=created["world_id"], code="square").count() == 0
    state = db.query(SessionStateModel).filter_by(session_id=session_id).one()
    start = db.query(LocationModel).filter_by(world_id=created["world_id"], code="east_bank").one()
    assert state.current_location_id == start.id
    assert state.global_flags_json[CONTENT_NAMESPACE]["profile_id"] == "content_v1"


def test_legacy_initializer_keeps_square_and_generic_seed_behavior(runtime_db):
    db, _ = runtime_db
    user = _user(db)
    world = WorldModel(
        id=f"legacy-world-{uuid.uuid4().hex[:8]}",
        code=f"legacy-{uuid.uuid4().hex[:8]}",
        name="Legacy compatibility",
        genre="fantasy",
        status="active",
    )
    db.add(world)
    db.flush()
    chapter = ChapterModel(
        id=f"chapter-{uuid.uuid4().hex[:8]}",
        world_id=world.id,
        chapter_no=1,
        name="Chapter",
        summary="legacy seed",
    )
    square = LocationModel(
        id=f"square-{uuid.uuid4().hex[:8]}",
        world_id=world.id,
        chapter_id=chapter.id,
        code="square",
        name="Square",
    )
    npc = NPCTemplateModel(
        id=f"npc-{uuid.uuid4().hex[:8]}",
        world_id=world.id,
        code="legacy_npc",
        name="Legacy NPC",
        initial_location_id=square.id,
    )
    quest = QuestTemplateModel(
        id=f"quest-{uuid.uuid4().hex[:8]}",
        world_id=world.id,
        code="legacy_quest",
        name="Visible quest",
        visibility="visible",
    )
    slot = SaveSlotModel(
        id=f"slot-{uuid.uuid4().hex[:8]}",
        user_id=user.id,
        slot_number=1,
        name="legacy",
    )
    db.add_all([chapter, square, npc, quest, slot])
    db.flush()
    session = SessionModel(
        id=f"session-{uuid.uuid4().hex[:8]}",
        user_id=user.id,
        save_slot_id=slot.id,
        world_id=world.id,
        status="active",
    )
    db.add(session)
    db.flush()

    plan = plan_session_story_state(db, session.id)
    assert plan.session_state["current_location_id"] == square.id
    assert plan.npc_states[0]["npc_template_id"] == npc.id
    assert plan.quest_states[0]["quest_template_id"] == quest.id
    initialize_session_story_state(db, session.id)
    assert db.query(SessionStateModel).filter_by(session_id=session.id).one().current_location_id == square.id
    assert db.query(SessionNPCStateModel).filter_by(session_id=session.id, npc_template_id=npc.id).count() == 1
    assert db.query(SessionQuestStateModel).filter_by(session_id=session.id, quest_template_id=quest.id).count() == 1


def test_content_and_phase3_markers_fail_before_turn_claim(runtime_db):
    db, _ = runtime_db
    created = _content_instance(db)
    session_id = created["session_id"]
    world = db.get(WorldModel, created["world_id"])
    ruleset = dict(world.ruleset_json)
    ruleset["phase3_profile"] = {"id": "phase3"}
    world.ruleset_json = ruleset
    db.flush()

    with pytest.raises(ContentRuntimeError) as exc:
        execute_turn_service(db=db, session_id=session_id, player_input="inspect", use_mock=True)
    assert exc.value.code == "CONTENT_BINDING_CONFLICT"
    assert db.query(TurnTransactionModel).filter_by(session_id=session_id).count() == 0


def test_content_binding_corruption_fails_closed_without_legacy_fallback(runtime_db):
    db, _ = runtime_db
    created = _content_instance(db)
    session_id = created["session_id"]
    world = db.get(WorldModel, created["world_id"])
    profile = dict(world.ruleset_json["content_profile"])
    profile["runtime_hash"] = "f" * 64
    world.ruleset_json = {**world.ruleset_json, "content_profile": profile}
    db.flush()

    with pytest.raises(ContentRuntimeError) as exc:
        execute_turn_service(db=db, session_id=session_id, player_input="inspect", use_mock=True)
    assert exc.value.code == "CONTENT_BINDING_MISMATCH"
    assert db.query(TurnTransactionModel).filter_by(session_id=session_id).count() == 1
    assert db.query(SessionStateModel).filter_by(session_id=session_id).one().current_location_id


def test_content_baseline_snapshot_allowed_but_rewind_rejected(runtime_db, monkeypatch):
    db, _ = runtime_db
    monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
    created = _content_instance(db)
    session_id = created["session_id"]
    instance_id = created["instance_id"]
    factory_baseline = db.query(InstanceSnapshotModel).filter_by(
        session_id=session_id,
        snapshot_kind="baseline",
    ).one()
    assert factory_baseline.snapshot_json["session_id"] == session_id

    # Baseline capture is safe: it records creation-time state without restoring it;
    # rewind remains unsafe because it would replay state outside content_v1's event rules.
    baseline = create_baseline_snapshot(db, instance_id, session_id)
    assert baseline.snapshot_kind == "baseline"
    assert baseline.snapshot_json["session_id"] == session_id

    with pytest.raises(ContentSnapshotUnsupportedError) as exc:
        create_manual_snapshot(db, instance_id, session_id)
    assert exc.value.code == "CONTENT_SNAPSHOT_UNSUPPORTED"

    payload = {
        "session_id": session_id,
        "session_state": {
            "global_flags_json": {CONTENT_NAMESPACE: {"profile_id": "content_v1"}},
        },
    }
    snapshot = InstanceSnapshotModel(
        id=f"snapshot-{uuid.uuid4().hex[:8]}",
        playthrough_instance_id=instance_id,
        session_id=session_id,
        snapshot_kind="manual",
        turn_no=0,
        snapshot_json=payload,
        checksum=compute_checksum(payload),
        created_at=datetime.now(),
    )
    db.add(snapshot)
    db.flush()
    with pytest.raises(ContentSnapshotUnsupportedError) as exc:
        apply_snapshot(db, snapshot.id)
    assert exc.value.code == "CONTENT_SNAPSHOT_UNSUPPORTED"
    assert db.get(SessionStateModel, db.query(SessionStateModel).filter_by(session_id=session_id).one().id)


def test_projection_whitelists_content_status_and_hides_private_runtime_data():
    from llm_rpg.core.projections import project_content_public_context

    projected = project_content_public_context({
        "__content_simulation": {"route_overrides": {"east_bank->west_bank": False}},
        "route_overrides": {"east_bank->west_bank": False},
        "future_steps": [{"step_key": "rule:secret@99"}],
        "status_flags": {
            "mood": "calm",
            "short_memory_summary": "not public",
            "secret_plan": "hidden",
        },
        "visible_npcs": [
            {"npc_id": "seen", "name": "Ferryman", "public_identity": "public", "hidden_identity": "private"},
            {"npc_id": "unseen", "name": "Herbalist", "owner_ref_id": "npc-private"},
        ],
    }, visible_npc_ids={"seen"})
    rendered = str(projected)
    assert "route_overrides" not in rendered
    assert "future_steps" not in rendered
    assert "not public" not in rendered
    assert "hidden_identity" not in rendered
    assert "Herbalist" not in rendered
    assert projected["status_flags"] == {"mood": "calm"}
    assert projected["visible_npcs"] == [
        {"name": "Ferryman", "public_identity": "public"}
    ]
