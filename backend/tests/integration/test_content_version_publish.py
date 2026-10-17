from __future__ import annotations

import shutil
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from llm_rpg.content.runtime_models import build_compiled_rules
from llm_rpg.core.content_publish_service import (
    ContentPublishError,
    dry_run_content_pack,
    load_published_bundle,
    publish_content_pack_version,
)
from llm_rpg.core.content_rules import CompiledContentRules
from llm_rpg.core.content_runtime import (
    decode_content_step_conditions,
    is_content_conditions,
    load_content_runtime_context,
    read_content_run_state,
)
from llm_rpg.core.playthrough_instance_service import (
    _initialize_content_v1_state,
    create_content_v1_instance,
)
from llm_rpg.core.story_package_service import (
    create_story_package_version,
    publish_story_package_version,
)
from llm_rpg.core.turn_unit_of_work import TurnUnitOfWork
from llm_rpg.storage.repositories import StoryPackageVersionRepository
from llm_rpg.storage.models import (
    ItemTemplateModel,
    LocationModel,
    NPCTemplateModel,
    PlaythroughInstanceModel,
    QuestTemplateModel,
    ScheduledEventModel,
    SessionInventoryItemModel,
    SessionModel,
    SessionNPCStateModel,
    SessionPlayerStateModel,
    SessionStateModel,
    StoryPackageVersionModel,
    UserModel,
    WorldModel,
    generate_uuid,
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_MISTY_FORD = _REPO_ROOT / "content_packs" / "misty_ford"
_TRIAL_MICRO_CONFIG = _REPO_ROOT / "content_packs" / "trial_micro_config"


def _count(db, model) -> int:
    return db.query(model).count()


def _counts(db) -> dict[str, int]:
    return {
        "worlds": _count(db, WorldModel),
        "locations": _count(db, LocationModel),
        "npcs": _count(db, NPCTemplateModel),
        "items": _count(db, ItemTemplateModel),
        "quests": _count(db, QuestTemplateModel),
        "versions": _count(db, StoryPackageVersionModel),
    }


def _create_user(db) -> UserModel:
    user = UserModel(username=f"content-v1-{uuid.uuid4().hex[:12]}", is_admin=False)
    db.add(user)
    db.flush()
    return user


def _compiled_rules_for_version(db, version_id: str):
    bundle, runtime_hash = load_published_bundle(db, version_id=version_id)
    data = build_compiled_rules(bundle, binding_hash=runtime_hash)
    return bundle, runtime_hash, CompiledContentRules(data)


def _copy_pack(tmp_path: Path, *, name: str = "pack-copy") -> Path:
    destination = tmp_path / name
    shutil.copytree(_MISTY_FORD, destination)
    return destination


def _update_pack_version(pack_dir: Path, version: str) -> None:
    path = pack_dir / "pack.yaml"
    contents = path.read_text(encoding="utf-8")
    path.write_text(contents.replace("version: 1.0.0", f"version: {version}"), encoding="utf-8")


def test_dry_run_writes_nothing(db_session):
    before = _counts(db_session)

    result = dry_run_content_pack(_MISTY_FORD)

    after = _counts(db_session)
    assert after == before
    assert result.source_hash and len(result.source_hash) == 64
    assert result.runtime_hash and len(result.runtime_hash) == 64


def test_publish_materializes_independent_world_and_templates(db_session):
    result = publish_content_pack_version(db_session, pack_dir=_MISTY_FORD)

    world = db_session.get(WorldModel, result.world_id)
    spv = db_session.get(StoryPackageVersionModel, result.version_id)
    assert world is not None
    assert world.story_package_version_id == result.version_id
    assert world.ruleset_json["content_profile"]["id"] == "content_v1"
    assert db_session.query(LocationModel).filter_by(world_id=world.id).count() == 4
    assert db_session.query(NPCTemplateModel).filter_by(world_id=world.id).count() == 2
    assert db_session.query(ItemTemplateModel).filter_by(world_id=world.id).count() == 2
    assert db_session.query(QuestTemplateModel).filter_by(world_id=world.id).count() == 0
    assert spv is not None and spv.world_id == world.id
    assert spv.runtime_bundle_json is not None
    assert spv.runtime_hash and len(spv.runtime_hash) == 64
    assert spv.status == "published"


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("runtime_bundle_json", {"world": {"id": "tampered"}}),
        ("runtime_hash", "f" * 64),
        ("runtime_schema_version", 2),
        ("source_hash", "e" * 64),
        ("world_id", "replacement-world-id"),
        ("story_package_id", "replacement-package"),
        ("version", "9.9.9"),
    ],
)
def test_story_package_version_repository_freezes_published_semantic_fields(
    db_session, field, replacement
):
    world = WorldModel(
        code=f"repo-freeze-{uuid.uuid4().hex}",
        name="Repository freeze test world",
    )
    db_session.add(world)
    db_session.flush()
    published = create_story_package_version(
        db_session,
        story_package_id=f"repo-freeze-{uuid.uuid4().hex}",
        version="1.0.0",
    )
    published = publish_story_package_version(db_session, published.id)
    repository = StoryPackageVersionRepository(db_session)

    value = world.id if field == "world_id" else replacement
    with pytest.raises(ContentPublishError) as raised:
        repository.update(published.id, {field: value})
    assert raised.value.code == "CONTENT_FROZEN_VERSION"

    draft = create_story_package_version(
        db_session,
        story_package_id=f"repo-draft-{uuid.uuid4().hex}",
        version="1.0.0",
    )
    updated_draft = repository.update(draft.id, {field: value})
    assert getattr(updated_draft, field) == value


def test_story_package_version_repository_rejects_published_delete_and_allows_metadata(
    db_session,
):
    published = create_story_package_version(
        db_session,
        story_package_id=f"repo-delete-{uuid.uuid4().hex}",
        version="1.0.0",
    )
    published = publish_story_package_version(db_session, published.id)
    repository = StoryPackageVersionRepository(db_session)

    published_at = datetime(2026, 10, 17, 12, 0, 0)
    updated = repository.update(published.id, {"published_at": published_at})
    assert updated.published_at == published_at
    with pytest.raises(ContentPublishError) as raised:
        repository.delete(published.id)
    assert raised.value.code == "CONTENT_FROZEN_VERSION"

    draft = create_story_package_version(
        db_session,
        story_package_id=f"repo-delete-draft-{uuid.uuid4().hex}",
        version="1.0.0",
    )
    assert repository.delete(draft.id) is True


def test_publish_is_atomic_on_failure(db_session, monkeypatch):
    from llm_rpg.core import content_publish_service as service

    def fail_late(**_kwargs):
        raise RuntimeError("forced late template materialization failure")

    monkeypatch.setattr(service, "NPCTemplateModel", fail_late)
    with pytest.raises(RuntimeError, match="forced late"):
        service.publish_content_pack_version(db_session, pack_dir=_MISTY_FORD)

    assert _counts(db_session) == {
        "worlds": 0,
        "locations": 0,
        "npcs": 0,
        "items": 0,
        "quests": 0,
        "versions": 0,
    }
    assert db_session.query(StoryPackageVersionModel).filter_by(status="draft").count() == 0


def test_publish_same_version_conflict_does_not_overwrite(db_session, tmp_path):
    first = publish_content_pack_version(db_session, pack_dir=_MISTY_FORD)
    first_version = db_session.get(StoryPackageVersionModel, first.version_id)
    original_hash = first_version.runtime_hash
    original_bundle = first_version.runtime_bundle_json

    changed_pack = _copy_pack(tmp_path, name="changed-content")
    world_file = changed_pack / "world.yaml"
    world_file.write_text(
        world_file.read_text(encoding="utf-8").replace("name: 雾渡", "name: 雾渡新篇"),
        encoding="utf-8",
    )
    with pytest.raises(ContentPublishError) as raised:
        publish_content_pack_version(db_session, pack_dir=changed_pack)

    assert raised.value.code == "CONTENT_VERSION_CONFLICT"
    db_session.refresh(first_version)
    assert first_version.runtime_hash == original_hash
    assert first_version.runtime_bundle_json == original_bundle
    assert _count(db_session, WorldModel) == 1


def test_publish_same_content_is_idempotent(db_session):
    first = publish_content_pack_version(db_session, pack_dir=_MISTY_FORD)
    second = publish_content_pack_version(db_session, pack_dir=_MISTY_FORD)

    assert first.created is True
    assert second.created is False
    assert second.version_id == first.version_id
    assert second.world_id == first.world_id
    assert _count(db_session, WorldModel) == 1


def test_second_version_does_not_affect_first_instance(db_session, tmp_path):
    first = publish_content_pack_version(db_session, pack_dir=_MISTY_FORD)
    user = _create_user(db_session)
    instance = create_content_v1_instance(
        db_session, user_id=user.id, version_id=first.version_id
    )
    first_locations = [
        (row.id, row.code, row.parent_location_id)
        for row in db_session.query(LocationModel).filter_by(world_id=first.world_id).order_by(LocationModel.code)
    ]
    first_npcs = [
        (row.id, row.code, row.initial_location_id)
        for row in db_session.query(NPCTemplateModel).filter_by(world_id=first.world_id).order_by(NPCTemplateModel.code)
    ]
    first_instance = db_session.get(PlaythroughInstanceModel, instance["instance_id"])
    first_binding = dict(first_instance.config_json["__content_binding"])

    second_pack = _copy_pack(tmp_path, name="misty-ford-v2")
    _update_pack_version(second_pack, "1.1.0")
    second = publish_content_pack_version(db_session, pack_dir=second_pack)

    db_session.refresh(first_instance)
    assert first_instance.world_id == first.world_id
    assert first_instance.story_package_version_id == first.version_id
    assert first_instance.config_json["__content_binding"] == first_binding
    assert first_instance.config_json["__content_binding"]["runtime_hash"] == first.runtime_hash
    assert second.world_id != first.world_id
    assert second.version_id != first.version_id
    assert [
        (row.id, row.code, row.parent_location_id)
        for row in db_session.query(LocationModel).filter_by(world_id=first.world_id).order_by(LocationModel.code)
    ] == first_locations
    assert [
        (row.id, row.code, row.initial_location_id)
        for row in db_session.query(NPCTemplateModel).filter_by(world_id=first.world_id).order_by(NPCTemplateModel.code)
    ] == first_npcs


def test_load_published_bundle_rejects_legacy_and_corrupt(db_session):
    metadata_only = StoryPackageVersionModel(
        story_package_id="legacy-pack",
        version="1.0",
        status="published",
        manifest_json={"pack_id": "legacy-pack"},
    )
    db_session.add(metadata_only)
    db_session.flush()
    with pytest.raises(ContentPublishError) as missing:
        load_published_bundle(db_session, version_id=metadata_only.id)
    assert missing.value.code == "CONTENT_BUNDLE_MISSING"

    from llm_rpg.content.compiler import compute_runtime_hash

    corrupt_bundle = {"world": {"name": "before"}}
    corrupt = StoryPackageVersionModel(
        story_package_id="corrupt-pack",
        version="1.0",
        status="published",
        manifest_json={},
        runtime_bundle_json=corrupt_bundle,
        runtime_hash=compute_runtime_hash(corrupt_bundle),
        runtime_schema_version=1,
    )
    db_session.add(corrupt)
    db_session.flush()
    corrupt.runtime_bundle_json = {"world": {"name": "tampered"}}
    db_session.flush()
    with pytest.raises(ContentPublishError) as mismatch:
        load_published_bundle(db_session, version_id=corrupt.id)
    assert mismatch.value.code == "CONTENT_HASH_MISMATCH"

    draft_bundle = {"world": {"name": "draft"}}
    draft = StoryPackageVersionModel(
        story_package_id="draft-pack",
        version="1.0",
        status="draft",
        manifest_json={},
        runtime_bundle_json=draft_bundle,
        runtime_hash=compute_runtime_hash(draft_bundle),
        runtime_schema_version=1,
    )
    db_session.add(draft)
    db_session.flush()
    with pytest.raises(ContentPublishError) as unpublished:
        load_published_bundle(db_session, version_id=draft.id)
    assert unpublished.value.code == "CONTENT_VERSION_NOT_PUBLISHED"


def test_instance_initialization_failure_rolls_back_instance_rows(db_session, monkeypatch):
    from llm_rpg.core import playthrough_instance_service as service

    published = publish_content_pack_version(db_session, pack_dir=_MISTY_FORD)
    persisted_version = db_session.get(StoryPackageVersionModel, published.version_id)
    assert persisted_version is not None
    assert persisted_version.id == published.version_id
    assert persisted_version.runtime_bundle_json is not None
    assert persisted_version.runtime_hash == published.runtime_hash
    user = _create_user(db_session)
    original_initializer = service._initialize_content_v1_state

    def fail_after_initialization(*args, **kwargs):
        original_initializer(*args, **kwargs)
        raise RuntimeError("forced instance initialization failure")

    monkeypatch.setattr(service, "_initialize_content_v1_state", fail_after_initialization)
    before = (
        _count(db_session, PlaythroughInstanceModel),
        _count(db_session, SessionModel),
        _count(db_session, SessionStateModel),
        _count(db_session, SessionPlayerStateModel),
        _count(db_session, SessionNPCStateModel),
        _count(db_session, SessionInventoryItemModel),
    )
    with pytest.raises(RuntimeError, match="forced instance"):
        create_content_v1_instance(db_session, user_id=user.id, version_id=published.version_id)
    after = (
        _count(db_session, PlaythroughInstanceModel),
        _count(db_session, SessionModel),
        _count(db_session, SessionStateModel),
        _count(db_session, SessionPlayerStateModel),
        _count(db_session, SessionNPCStateModel),
        _count(db_session, SessionInventoryItemModel),
    )
    assert after == before


def test_instance_creation_is_atomic_and_binds_version(db_session):
    published = publish_content_pack_version(db_session, pack_dir=_MISTY_FORD)
    persisted_version = db_session.get(StoryPackageVersionModel, published.version_id)
    assert persisted_version is not None
    assert persisted_version.id == published.version_id
    assert persisted_version.runtime_bundle_json is not None
    assert persisted_version.runtime_hash == published.runtime_hash
    user = _create_user(db_session)

    result = create_content_v1_instance(
        db_session,
        user_id=user.id,
        version_id=published.version_id,
        story_package_id="misty_ford",
        config_json={"difficulty": "normal", "__content_binding": {"runtime_hash": "client-forgery"}},
    )
    instance = db_session.get(PlaythroughInstanceModel, result["instance_id"])
    session = db_session.get(SessionModel, result["session_id"])
    state = db_session.query(SessionStateModel).filter_by(session_id=session.id).one()
    content_state = read_content_run_state(
        state.global_flags_json,
        expected_binding_hash=published.runtime_hash,
    )
    assert session.story_package_version_id == published.version_id
    assert session.playthrough_instance_id == instance.id
    assert session.world_id == instance.world_id == published.world_id
    assert instance.root_session_id == session.id
    assert content_state is not None
    assert content_state.binding_hash == published.runtime_hash
    assert state.current_location_id == db_session.query(LocationModel).filter_by(
        world_id=published.world_id, code="east_bank"
    ).one().id
    assert dict(content_state.flags) == {"bridge_closed_once": False, "bridge_reopened": False}
    runtime_context = load_content_runtime_context(db_session, session_id=session.id)
    assert runtime_context.state.route_is_open("east_bank", "west_bank") is True

    npc_states = db_session.query(SessionNPCStateModel).filter_by(session_id=session.id).all()
    assert len(npc_states) == 2
    assert all(row.current_location_id is not None and row.status_flags["alive"] is True for row in npc_states)
    inventory = db_session.query(SessionInventoryItemModel).filter_by(session_id=session.id).all()
    assert {row.instance_key for row in inventory} == {"lantern", "herb_bundle"}
    assert all(row.quantity == 1 for row in inventory)
    assert instance.config_json["difficulty"] == "normal"
    assert instance.config_json["__content_binding"] == {
        "runtime_hash": published.runtime_hash,
        "bundle_schema_version": 1,
        "engine_rules_version": 1,
        "version_id": published.version_id,
    }


def test_admin_writes_freeze_published_content_but_preserve_legacy_contract(db_session, client):
    from passlib.context import CryptContext
    from llm_rpg.api.admin import (
        ItemTemplateDetail,
        LocationDetail,
        NPCTemplateDetail,
        QuestTemplateDetail,
        WorldDetail,
    )

    published = publish_content_pack_version(db_session, pack_dir=_MISTY_FORD)
    published_world = db_session.get(WorldModel, published.world_id)
    published_location = db_session.query(LocationModel).filter_by(world_id=published.world_id).first()
    published_npc = db_session.query(NPCTemplateModel).filter_by(world_id=published.world_id).first()
    published_item = db_session.query(ItemTemplateModel).filter_by(world_id=published.world_id).first()
    published_quest = QuestTemplateModel(
        world_id=published.world_id,
        code="admin_freeze_quest",
        name="Frozen quest",
        quest_type="content_v1",
    )
    db_session.add(published_quest)

    legacy_world = WorldModel(
        code=f"legacy-admin-{uuid.uuid4().hex[:12]}",
        name="Legacy world",
    )
    db_session.add(legacy_world)
    db_session.flush()
    legacy_location = LocationModel(
        world_id=legacy_world.id,
        code="legacy-location",
        name="Legacy location",
    )
    legacy_npc = NPCTemplateModel(
        world_id=legacy_world.id,
        code="legacy-npc",
        name="Legacy NPC",
    )
    legacy_item = ItemTemplateModel(
        world_id=legacy_world.id,
        code="legacy-item",
        name="Legacy item",
    )
    legacy_quest = QuestTemplateModel(
        world_id=legacy_world.id,
        code="legacy-quest",
        name="Legacy quest",
    )
    db_session.add_all([legacy_location, legacy_npc, legacy_item, legacy_quest])

    password = "Pass123!"
    admin = UserModel(
        username=f"content-admin-{uuid.uuid4().hex[:10]}",
        password_hash=CryptContext(schemes=["bcrypt"], deprecated="auto").hash(password),
        is_admin=True,
    )
    db_session.add(admin)
    db_session.flush()

    # Reuse the fixture Session for TestClient requests. A second Session on
    # StaticPool can commit the fixture's outer transaction and leak this Quest
    # row into later content-v1 tests.
    from llm_rpg.main import app
    from llm_rpg.storage.database import get_db

    previous_override = app.dependency_overrides.get(get_db)

    def use_fixture_session():
        yield db_session

    app.dependency_overrides[get_db] = use_fixture_session
    try:
        login = client.post("/auth/login", json={"username": admin.username, "password": password})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        operations = [
            (f"/admin/worlds/{published_world.id}", published_world.id, legacy_world.id, "World", WorldDetail),
            (f"/admin/locations/{published_location.id}", published_location.id, legacy_location.id, "Location", LocationDetail),
            (f"/admin/npc-templates/{published_npc.id}", published_npc.id, legacy_npc.id, "NPC", NPCTemplateDetail),
            (f"/admin/item-templates/{published_item.id}", published_item.id, legacy_item.id, "Item", ItemTemplateDetail),
            (f"/admin/quest-templates/{published_quest.id}", published_quest.id, legacy_quest.id, "Quest", QuestTemplateDetail),
        ]
        for path, _published_id, _legacy_id, label, _response_model in operations:
            response = client.patch(path, json={"name": f"Blocked {label}"}, headers=headers)
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "CONTENT_FROZEN_VERSION"

        legacy_entities = [legacy_world, legacy_location, legacy_npc, legacy_item, legacy_quest]
        for operation, entity in zip(operations, legacy_entities):
            path, _published_id, _legacy_id, label, response_model = operation
            response = client.patch(
                path.replace(_published_id, entity.id),
                json={"name": f"Updated {label}"},
                headers=headers,
            )
            assert response.status_code == 200
            payload = response.json()
            assert set(payload) == set(response_model.model_fields)
            assert payload["id"] == entity.id
            assert payload["name"] == f"Updated {label}"
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override


@pytest.mark.parametrize(
    ("pack_dir", "expected_step_count"),
    [(_MISTY_FORD, 4), (_TRIAL_MICRO_CONFIG, 6)],
)
def test_content_instance_schedules_initial_steps(db_session, pack_dir, expected_step_count):
    published = publish_content_pack_version(db_session, pack_dir=pack_dir)
    user = _create_user(db_session)
    created = create_content_v1_instance(
        db_session,
        user_id=user.id,
        version_id=published.version_id,
    )
    _, runtime_hash, rules = _compiled_rules_for_version(db_session, published.version_id)
    expected_steps = rules.initial_steps()
    initial_state = rules.initial_state()

    rows = db_session.query(ScheduledEventModel).filter_by(session_id=created["session_id"]).all()
    content_rows = [row for row in rows if is_content_conditions(row.trigger_conditions_json)]
    persisted_steps = [decode_content_step_conditions(row.trigger_conditions_json) for row in content_rows]
    persisted_keys = {step.step_key for step in persisted_steps}
    expected_keys = {step.step_key for step in expected_steps}

    assert len(expected_steps) == expected_step_count
    assert len(content_rows) == expected_step_count
    assert all(row.status == "pending" for row in content_rows)
    assert persisted_keys == expected_keys
    state_row = db_session.query(SessionStateModel).filter_by(session_id=created["session_id"]).one()
    run_state = read_content_run_state(
        state_row.global_flags_json,
        expected_binding_hash=runtime_hash,
    )
    assert run_state is not None
    assert set(run_state.pending_steps) == persisted_keys
    assert len(run_state.pending_steps) == expected_step_count
    assert run_state.logical_tick == initial_state.logical_tick
    assert run_state.next_event_seq == 0


def test_content_instance_initial_state_matches_bundle(db_session):
    published = publish_content_pack_version(db_session, pack_dir=_MISTY_FORD)
    locations = db_session.query(LocationModel).filter_by(world_id=published.world_id).all()
    locations_by_code = {row.code: row for row in locations}
    location_code_by_id = {row.id: row.code for row in locations}
    locations_before = {row.id: dict(row.access_rules or {}) for row in locations}
    user = _create_user(db_session)
    created = create_content_v1_instance(
        db_session,
        user_id=user.id,
        version_id=published.version_id,
    )
    _, runtime_hash, rules = _compiled_rules_for_version(db_session, published.version_id)
    initial_state = rules.initial_state()

    state_row = db_session.query(SessionStateModel).filter_by(session_id=created["session_id"]).one()
    player_state = db_session.query(SessionPlayerStateModel).filter_by(session_id=created["session_id"]).one()
    assert state_row.current_location_id == locations_by_code[initial_state.player_location_code].id
    assert bool(player_state.hp > 0) is initial_state.player_alive
    run_state = read_content_run_state(
        state_row.global_flags_json,
        expected_binding_hash=runtime_hash,
    )
    assert run_state is not None
    assert dict(run_state.flags) == initial_state.flags
    assert dict(run_state.route_overrides) == initial_state.route_overrides

    npc_templates = db_session.query(NPCTemplateModel).filter_by(world_id=published.world_id).all()
    npc_code_by_template_id = {row.id: row.code for row in npc_templates}
    npc_states = db_session.query(SessionNPCStateModel).filter_by(session_id=created["session_id"]).all()
    actual_npcs = {
        npc_code_by_template_id[row.npc_template_id]: (
            location_code_by_id[row.current_location_id],
            bool((row.status_flags or {}).get("alive", True)),
        )
        for row in npc_states
    }
    expected_npcs = {
        code: (initial_state.npc_positions[code], initial_state.npc_alive[code])
        for code in initial_state.npc_positions
    }
    assert actual_npcs == expected_npcs

    npc_code_by_state_id = {row.id: npc_code_by_template_id[row.npc_template_id] for row in npc_states}
    inventory = db_session.query(SessionInventoryItemModel).filter_by(session_id=created["session_id"]).all()
    actual_items = {}
    for row in inventory:
        if row.owner_type == "player":
            owner = "player"
        elif row.owner_type == "location":
            owner = f"location:{location_code_by_id[row.owner_ref_id]}"
        elif row.owner_type == "character":
            owner = f"character:{npc_code_by_state_id[row.owner_ref_id]}"
        else:
            owner = f"unsupported:{row.owner_type}"
        actual_items[row.instance_key] = (row.quantity, row.owner_type, owner)
    expected_items = {
        code: (
            item.quantity,
            item.owner_type,
            "player" if item.owner_type == "player" else f"{item.owner_type}:{item.owner_ref}",
        )
        for code, item in initial_state.item_instances.items()
    }
    assert actual_items == expected_items
    assert {row.id: dict(row.access_rules or {}) for row in locations} == locations_before


def test_content_instance_creates_own_baseline_rows(db_session):
    published = publish_content_pack_version(db_session, pack_dir=_MISTY_FORD)
    user = _create_user(db_session)
    created = create_content_v1_instance(
        db_session,
        user_id=user.id,
        version_id=published.version_id,
    )
    _, _, rules = _compiled_rules_for_version(db_session, published.version_id)
    initial_state = rules.initial_state()
    session_id = created["session_id"]

    assert db_session.query(SessionStateModel).filter_by(session_id=session_id).count() == 1
    assert db_session.query(SessionPlayerStateModel).filter_by(session_id=session_id).count() == 1
    npc_templates = db_session.query(NPCTemplateModel).filter_by(world_id=published.world_id).all()
    npc_code_by_template_id = {row.id: row.code for row in npc_templates}
    npc_states = db_session.query(SessionNPCStateModel).filter_by(session_id=session_id).all()
    assert len(npc_states) == len(rules.data.characters)
    actual_npcs = {
        npc_code_by_template_id[row.npc_template_id]: (
            row.current_location_id,
            bool((row.status_flags or {}).get("alive", True)),
        )
        for row in npc_states
    }
    locations_by_code = {
        row.code: row for row in db_session.query(LocationModel).filter_by(world_id=published.world_id).all()
    }
    expected_npcs = {
        code: (locations_by_code[initial_state.npc_positions[code]].id, initial_state.npc_alive[code])
        for code in initial_state.npc_positions
    }
    assert set(actual_npcs) == set(rules.data.characters)
    assert actual_npcs == expected_npcs


def test_content_instance_initialization_is_idempotent(db_session):
    published = publish_content_pack_version(db_session, pack_dir=_MISTY_FORD)
    user = _create_user(db_session)
    created = create_content_v1_instance(
        db_session,
        user_id=user.id,
        version_id=published.version_id,
    )
    _, runtime_hash, rules = _compiled_rules_for_version(db_session, published.version_id)
    world = db_session.get(WorldModel, created["world_id"])
    locations_by_code = {
        row.code: row for row in db_session.query(LocationModel).filter_by(world_id=world.id).all()
    }
    npcs_by_code = {
        row.code: row for row in db_session.query(NPCTemplateModel).filter_by(world_id=world.id).all()
    }
    items_by_code = {
        row.code: row for row in db_session.query(ItemTemplateModel).filter_by(world_id=world.id).all()
    }
    engine_rules_version = world.ruleset_json["content_profile"]["engine_rules_version"]
    session_id = created["session_id"]

    def row_counts():
        return (
            db_session.query(SessionStateModel).filter_by(session_id=session_id).count(),
            db_session.query(SessionPlayerStateModel).filter_by(session_id=session_id).count(),
            db_session.query(SessionNPCStateModel).filter_by(session_id=session_id).count(),
            db_session.query(SessionInventoryItemModel).filter_by(session_id=session_id).count(),
            db_session.query(ScheduledEventModel).filter_by(session_id=session_id).count(),
        )

    before = row_counts()
    with TurnUnitOfWork(db_session, guard_commits=True) as uow:
        _initialize_content_v1_state(
            db_session,
            session_id=session_id,
            rules=rules,
            runtime_hash=runtime_hash,
            engine_rules_version=engine_rules_version,
            locations_by_code=locations_by_code,
            npcs_by_code=npcs_by_code,
            items_by_code=items_by_code,
        )
        db_session.flush()
        uow.allow_commit()
        db_session.commit()
    assert row_counts() == before


def test_source_directory_removal_does_not_affect_published_version(db_session, tmp_path):
    source = _copy_pack(tmp_path, name="source-pack")
    published = publish_content_pack_version(db_session, pack_dir=source)
    shutil.move(str(source), str(tmp_path / "renamed-source"))

    bundle, runtime_hash = load_published_bundle(db_session, version_id=published.version_id)
    user = _create_user(db_session)
    instance = create_content_v1_instance(
        db_session, user_id=user.id, version_id=published.version_id
    )

    assert bundle["world"]["id"] == "misty_ford"
    assert runtime_hash == published.runtime_hash
    assert instance["world_id"] == published.world_id
    assert instance["version_id"] == published.version_id
