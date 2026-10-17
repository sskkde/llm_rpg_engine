"""SQLite recovery and fail-closed checks for the content_v1 runtime adapter."""

from __future__ import annotations

import copy
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.core.content_publish_service import publish_content_pack_version
from llm_rpg.core.content_runtime import (
    CONTENT_RUN_STATE_SCHEMA_VERSION,
    CONTENT_NAMESPACE,
    ContentRunState,
    ContentRuntimeError,
    apply_content_advance,
    decode_content_npc_plan,
    encode_content_npc_plan,
    encode_content_run_state,
    encode_content_step_conditions,
    is_content_conditions,
    load_content_runtime_context,
    merge_content_run_state,
    read_content_binding,
    read_content_run_state,
)
from llm_rpg.core.playthrough_instance_service import create_content_v1_instance
from llm_rpg.content.runtime_models import CurrentPlanState
from llm_rpg.core.time_simulation import (
    PHASE3_NAMESPACE,
    PlayerActionKind,
    PlayerActionSpec,
    ScheduledStep,
    SimulationRunState,
    StepKind,
    encode_run_state,
    encode_step_conditions,
    is_phase3_conditions,
    read_run_state,
)
from llm_rpg.core.turn_unit_of_work import TurnUnitOfWork
from llm_rpg.core.world_advancer import WorldAdvancer
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    LocationModel,
    PlaythroughInstanceModel,
    ScheduledEventModel,
    SessionInventoryItemModel,
    SessionModel,
    SessionNPCStateModel,
    SessionStateModel,
    StoryPackageVersionModel,
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


def _create_user(db) -> UserModel:
    user = UserModel(username=f"content-runtime-{uuid.uuid4().hex[:12]}", is_admin=False)
    db.add(user)
    db.flush()
    return user


def _published_instance(db, *, version_id: str | None = None, user_id: str | None = None):
    if version_id is None:
        version_id = publish_content_pack_version(db, pack_dir=_MISTY_FORD).version_id
    user_id = user_id or _create_user(db).id
    created = create_content_v1_instance(db, user_id=user_id, version_id=version_id)
    return version_id, created


def _fresh_context(db, session_id: str):
    """Model a fresh content runtime (no content marker); reads stay write-free."""
    row = db.query(SessionStateModel).filter_by(session_id=session_id).one()
    flags = dict(row.global_flags_json or {})
    flags.pop(CONTENT_NAMESPACE, None)
    row.global_flags_json = flags
    db.commit()
    return load_content_runtime_context(db, session_id=session_id)


def _advance(context, minutes: int = 6):
    action = PlayerActionSpec(
        kind=PlayerActionKind.IDLE,
        action_type="inspect",
        start_tick=context.state.logical_tick,
        duration_minutes=minutes,
    )
    return WorldAdvancer(context.rules).advance(
        state=context.state,
        player_action=action,
        pending_steps=context.pending_steps,
        consumed_step_keys=context.consumed_step_keys,
        start_event_seq=context.start_event_seq,
    )


def _carrier_snapshot(db, session_id: str):
    state = db.query(SessionStateModel).filter_by(session_id=session_id).one()
    npcs = db.query(SessionNPCStateModel).filter_by(session_id=session_id).order_by(
        SessionNPCStateModel.npc_template_id
    ).all()
    items = db.query(SessionInventoryItemModel).filter_by(session_id=session_id).order_by(
        SessionInventoryItemModel.instance_key
    ).all()
    steps = db.query(ScheduledEventModel).filter_by(session_id=session_id).order_by(
        ScheduledEventModel.id
    ).all()
    return (
        copy.deepcopy(state.global_flags_json),
        state.current_location_id,
        tuple((row.npc_template_id, row.current_location_id, copy.deepcopy(row.status_flags), row.hidden_plan_state) for row in npcs),
        tuple((row.instance_key, row.owner_type, row.owner_ref_id, row.quantity) for row in items),
        tuple((row.trigger_conditions_json, row.status) for row in steps),
    )


def _item_owners(context):
    return {
        code: (item.owner_type, item.owner_ref)
        for code, item in context.state.item_instances.items()
    }


def test_advance_survives_new_db_session(runtime_db):
    db, factory = runtime_db
    version_id, created = _published_instance(db)
    session_id = created["session_id"]
    before_rows = (
        db.query(SessionNPCStateModel).filter_by(session_id=session_id).count(),
        db.query(SessionInventoryItemModel).filter_by(session_id=session_id).count(),
        db.query(ScheduledEventModel).filter_by(session_id=session_id).count(),
    )
    context = load_content_runtime_context(db, session_id=session_id)
    # Loading the factory's baseline twice is read-only and creates no duplicates.
    again = load_content_runtime_context(db, session_id=session_id)
    assert again.state.logical_tick == context.state.logical_tick
    assert [step.step_key for step in again.pending_steps] == [step.step_key for step in context.pending_steps]
    assert (
        db.query(SessionNPCStateModel).filter_by(session_id=session_id).count(),
        db.query(SessionInventoryItemModel).filter_by(session_id=session_id).count(),
        db.query(ScheduledEventModel).filter_by(session_id=session_id).count(),
    ) == before_rows

    result = _advance(context, 6)
    with TurnUnitOfWork(db):
        apply_content_advance(
            db,
            session_id=session_id,
            context=context,
            advance_result=result,
        )
    db.commit()
    expected_npcs = dict(result.final_state.npc_positions)
    expected_routes = dict(result.final_state.route_overrides)
    expected_owners = {
        code: (item.owner_type, item.owner_ref)
        for code, item in result.final_state.item_instances.items()
    }

    # A distinct ORM Session has no old identity map or context object to lean on.
    db.close()
    reopened = factory()
    try:
        recovered = load_content_runtime_context(reopened, session_id=session_id)
        assert recovered.run_state.logical_tick == result.actual_end_tick
        assert recovered.state.logical_tick == result.actual_end_tick
        assert recovered.state.npc_positions == expected_npcs
        assert recovered.state.route_overrides == expected_routes
        assert _item_owners(recovered) == expected_owners
        assert recovered.start_event_seq == result.next_event_seq
    finally:
        reopened.close()


def test_run_state_is_namespaced_and_phase3_codec_ignores_it():
    content_step = ScheduledStep(
        step_key="rule:close_bridge@4",
        tick=4,
        phase=1,
        actor_code="world",
        kind=StepKind.CONTENT_RULE_FIRE,
        payload={"rule": "close_bridge", "occurrence": "4"},
    )
    content_blob = encode_content_step_conditions(content_step)
    phase3_step = ScheduledStep(
        step_key="world.environment_interrupt@7",
        tick=7,
        phase=1,
        actor_code="world",
        kind=StepKind.ENVIRONMENT_INTERRUPT,
        payload={"kind": "bell"},
    )
    phase3_blob = encode_step_conditions(phase3_step)
    assert is_content_conditions(content_blob) is True
    assert is_phase3_conditions(content_blob) is False
    assert is_content_conditions(phase3_blob) is False
    assert is_phase3_conditions(phase3_blob) is True

    plan = CurrentPlanState(
        goal_id="cross_bridge",
        source="goal",
        generation=2,
        recipe_step=0,
        action="move",
        target="west_bank",
        start_tick=2,
        expected_end_tick=5,
        status="traveling",
        failure_code=None,
    )
    decoded_plan = decode_content_npc_plan(
        encode_content_npc_plan(plan, binding_hash="a" * 64),
        expected_binding_hash="a" * 64,
    )
    assert decoded_plan == plan

    state = ContentRunState(
        schema_version=CONTENT_RUN_STATE_SCHEMA_VERSION,
        profile_id="content_v1",
        binding_hash="a" * 64,
        engine_rules_version=1,
        logical_tick=4,
        next_event_seq=2,
        rules_fired={"close_bridge|4": "4"},
        flags={"bridge_closed_once": True},
        route_overrides={"east_bank->west_bank": False},
        pending_steps=("schedule:ferryman_patrol@8",),
    )
    original_flags = {
        "ordinary": {"nested": [1, 2, 3]},
        PHASE3_NAMESPACE: {"opaque": "phase-3"},
        "unrelated": True,
    }
    before = copy.deepcopy(original_flags)
    merged = merge_content_run_state(original_flags, state)
    assert merged is not original_flags
    assert merged["ordinary"] == before["ordinary"]
    assert merged[PHASE3_NAMESPACE] == before[PHASE3_NAMESPACE]
    assert merged["unrelated"] == before["unrelated"]
    assert original_flags == before
    assert set(merged[CONTENT_NAMESPACE]) == {
        "schema_version",
        "profile_id",
        "binding_hash",
        "engine_rules_version",
        "logical_tick",
        "next_event_seq",
        "rules_fired",
        "flags",
        "route_overrides",
        "pending_steps",
    }
    assert read_run_state({CONTENT_NAMESPACE: encode_content_run_state(state)}) is None
    phase3_run_state = encode_run_state(SimulationRunState(logical_tick=4, next_event_seq=2))
    assert read_content_run_state(
        {PHASE3_NAMESPACE: phase3_run_state}, expected_binding_hash="a" * 64
    ) is None


def _corrupt_case(body: dict, case: str) -> dict:
    result = copy.deepcopy(body)
    if case == "missing key":
        result.pop("flags")
    elif case == "extra key":
        result["unexpected"] = "no"
    elif case == "wrong schema_version":
        result["schema_version"] = 2
    elif case == "wrong profile_id":
        result["profile_id"] = "trial_micro_v1"
    elif case == "wrong binding_hash":
        result["binding_hash"] = "f" * 64
    else:  # pragma: no cover - parametrization guard
        raise AssertionError(case)
    return result


@pytest.mark.parametrize(
    "case",
    ["missing key", "extra key", "wrong schema_version", "wrong profile_id", "wrong binding_hash"],
)
def test_corrupt_run_state_fails_closed(runtime_db, case):
    db, _ = runtime_db
    _, created = _published_instance(db)
    session_id = created["session_id"]
    row = db.query(SessionStateModel).filter_by(session_id=session_id).one()
    original = copy.deepcopy(row.global_flags_json[CONTENT_NAMESPACE])
    row.global_flags_json = {
        **dict(row.global_flags_json),
        CONTENT_NAMESPACE: _corrupt_case(original, case),
    }
    db.commit()
    before = _carrier_snapshot(db, session_id)

    with pytest.raises(ContentRuntimeError) as raised:
        load_content_runtime_context(db, session_id=session_id)
    assert raised.value.code in {"CONTENT_RUN_STATE_CORRUPT", "CONTENT_HASH_MISMATCH"}
    assert _carrier_snapshot(db, session_id) == before


@pytest.mark.parametrize(
    "tamper",
    [
        "instance_config_version_id",
        "instance_config_runtime_hash",
        "instance_config_bundle_schema_version",
        "instance_config_engine_rules_version",
        "world_version_binding",
    ],
)
def test_binding_mismatch_fails_closed(runtime_db, tamper):
    db, _ = runtime_db
    version_id, created = _published_instance(db)
    session_id = created["session_id"]
    if tamper.startswith("instance_config_"):
        instance = db.get(PlaythroughInstanceModel, created["instance_id"])
        config = copy.deepcopy(instance.config_json)
        binding_field = tamper.removeprefix("instance_config_")
        tampered_values = {
            "version_id": "different-version-id",
            "runtime_hash": "f" * 64,
            "bundle_schema_version": 2,
            "engine_rules_version": 2,
        }
        config["__content_binding"][binding_field] = tampered_values[binding_field]
        instance.config_json = config
    else:
        world = db.get(WorldModel, created["world_id"])
        other_version = StoryPackageVersionModel(
            id=f"other-{uuid.uuid4().hex}",
            story_package_id="other-package",
            version="1.0.0",
            status="draft",
            runtime_bundle_json=None,
            runtime_hash=None,
        )
        db.add(other_version)
        db.flush()
        world.story_package_version_id = other_version.id
    db.commit()

    with pytest.raises(ContentRuntimeError) as raised:
        read_content_binding(db, session_id=session_id)
    assert raised.value.code == "CONTENT_BINDING_MISMATCH"
    assert version_id == created["version_id"]


def test_route_overrides_are_session_scoped(runtime_db):
    db, _ = runtime_db
    version_id = publish_content_pack_version(db, pack_dir=_MISTY_FORD).version_id
    user = _create_user(db)
    instance_a = create_content_v1_instance(db, user_id=user.id, version_id=version_id)
    instance_b = create_content_v1_instance(db, user_id=user.id, version_id=version_id)
    locations_before = {
        row.code: copy.deepcopy(row.access_rules)
        for row in db.query(LocationModel).filter_by(world_id=instance_a["world_id"]).all()
    }

    fresh_counts = (
        db.query(SessionNPCStateModel).filter_by(session_id=instance_a["session_id"]).count(),
        db.query(SessionInventoryItemModel).filter_by(session_id=instance_a["session_id"]).count(),
        db.query(ScheduledEventModel).filter_by(session_id=instance_a["session_id"]).count(),
    )
    context_a = _fresh_context(db, instance_a["session_id"])
    fresh_again = load_content_runtime_context(db, session_id=instance_a["session_id"])
    assert [step.step_key for step in fresh_again.pending_steps] == [step.step_key for step in context_a.pending_steps]
    assert (
        db.query(SessionNPCStateModel).filter_by(session_id=instance_a["session_id"]).count(),
        db.query(SessionInventoryItemModel).filter_by(session_id=instance_a["session_id"]).count(),
        db.query(ScheduledEventModel).filter_by(session_id=instance_a["session_id"]).count(),
    ) == fresh_counts
    result_a = _advance(context_a, 6)
    with TurnUnitOfWork(db):
        apply_content_advance(
            db,
            session_id=instance_a["session_id"],
            context=context_a,
            advance_result=result_a,
        )
    db.commit()

    context_b = load_content_runtime_context(db, session_id=instance_b["session_id"])
    context_a_reloaded = load_content_runtime_context(db, session_id=instance_a["session_id"])
    assert context_a_reloaded.state.route_is_open("east_bank", "west_bank") is False
    assert context_b.state.route_is_open("east_bank", "west_bank") is True
    assert {
        row.code: row.access_rules
        for row in db.query(LocationModel).filter_by(world_id=instance_a["world_id"]).all()
    } == locations_before


def test_no_second_commit(runtime_db):
    db, _ = runtime_db
    _, created = _published_instance(db)
    session_id = created["session_id"]
    context = _fresh_context(db, session_id)
    result = _advance(context, 1)
    with TurnUnitOfWork(db):
        apply_content_advance(
            db,
            session_id=session_id,
            context=context,
            advance_result=result,
        )
    # If the adapter had committed, this caller rollback could not remove its cursor.
    db.rollback()
    persisted = db.query(SessionStateModel).filter_by(session_id=session_id).one()
    assert CONTENT_NAMESPACE not in (persisted.global_flags_json or {})


def test_missing_or_draft_version_rejected(runtime_db):
    db, _ = runtime_db
    draft_id, draft_instance = _published_instance(db)
    draft = db.get(StoryPackageVersionModel, draft_id)
    draft.status = "draft"
    db.commit()
    with pytest.raises(ContentRuntimeError) as unpublished:
        load_content_runtime_context(db, session_id=draft_instance["session_id"])
    assert unpublished.value.code == "CONTENT_VERSION_NOT_PUBLISHED"

    draft.status = "published"
    db.commit()
    metadata_id, metadata_instance = _published_instance(db, version_id=draft_id)
    metadata = db.get(StoryPackageVersionModel, metadata_id)
    metadata.runtime_bundle_json = None
    db.commit()
    with pytest.raises(ContentRuntimeError) as missing:
        load_content_runtime_context(db, session_id=metadata_instance["session_id"])
    assert missing.value.code == "CONTENT_BUNDLE_MISSING"


def test_phase3_codec_is_not_used_to_decode_content_run_state(runtime_db):
    """The two run-state namespaces remain disjoint even with both in one carrier."""
    db, _ = runtime_db
    _, created = _published_instance(db)
    binding = read_content_binding(db, session_id=created["session_id"])
    state = ContentRunState(
        schema_version=1,
        profile_id="content_v1",
        binding_hash=binding.runtime_hash,
        engine_rules_version=binding.engine_rules_version,
        logical_tick=0,
        next_event_seq=0,
        rules_fired={},
        flags={},
        route_overrides={},
        pending_steps=(),
    )
    phase3 = encode_run_state(SimulationRunState(logical_tick=0, next_event_seq=0))
    merged = merge_content_run_state({PHASE3_NAMESPACE: phase3}, state)
    # The phase-3 codec sees no phase-3 run-state change when reading its own key.
    assert merged[PHASE3_NAMESPACE] == phase3
    assert encode_content_run_state(state)["profile_id"] == "content_v1"
