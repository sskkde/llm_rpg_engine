"""Integration coverage for the fixed phase-3 micro-world seed."""

from __future__ import annotations

from typing import Any, Dict

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.core.time_simulation import Phase3Profile, resolve_phase3_profile
from llm_rpg.core.time_simulation_rules import (
    ITEM_SPEC,
    LOCATION_SPECS,
    MICRO_WORLD_CODE,
    NPC_SPECS,
    WORLD_SPEC,
    profile_marker,
)
from llm_rpg.scripts.seed_content import seed_all_content
from llm_rpg.scripts.seed_time_slice import (
    TimeSliceSeedConflictError,
    seed_time_slice,
)
from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    ItemTemplateModel,
    LocationModel,
    NPCTemplateModel,
    WorldModel,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _micro_counts(db, world_id: str) -> Dict[str, int]:
    return {
        "worlds": db.query(WorldModel).filter(WorldModel.id == world_id).count(),
        "locations": db.query(LocationModel).filter(LocationModel.world_id == world_id).count(),
        "npcs": db.query(NPCTemplateModel).filter(NPCTemplateModel.world_id == world_id).count(),
        "items": db.query(ItemTemplateModel).filter(ItemTemplateModel.world_id == world_id).count(),
    }


def _world_snapshot(db, world_id: str) -> Dict[str, Any]:
    """Capture all columns in the default world's seed-owned rows."""
    models = (WorldModel, LocationModel, NPCTemplateModel, ItemTemplateModel)
    snapshot: Dict[str, Any] = {}
    for model in models:
        query = db.query(model)
        if model is WorldModel:
            rows = query.filter(model.id == world_id).all()
        else:
            rows = query.filter(model.world_id == world_id).all()
        values = [
            {column.name: getattr(row, column.name) for column in model.__table__.columns}
            for row in rows
        ]
        snapshot[model.__tablename__] = sorted(
            values, key=lambda row: (row.get("code", ""), row["id"])
        )
    return snapshot


def test_seed_time_slice_creates_fixed_world_content_and_profile_marker(db_session):
    ids = seed_time_slice(db_session)
    db_session.flush()

    world = db_session.query(WorldModel).filter_by(code=MICRO_WORLD_CODE).one()
    assert ids["world_id"] == world.id
    assert world.code == WORLD_SPEC["code"]
    assert world.name == WORLD_SPEC["name"]
    assert world.genre == WORLD_SPEC["genre"]
    assert world.lore_summary == WORLD_SPEC["lore_summary"]
    assert world.status == WORLD_SPEC["status"]
    assert world.ruleset_json == profile_marker()
    assert world.ruleset_json["phase3_profile"] == profile_marker()["phase3_profile"]

    locations = {
        row.code: row
        for row in db_session.query(LocationModel).filter_by(world_id=world.id).all()
    }
    assert len(locations) == 3
    assert set(locations) == {spec.code for spec in LOCATION_SPECS}
    assert set(ids["location_ids"]) == set(locations)
    for spec in LOCATION_SPECS:
        row = locations[spec.code]
        assert ids["location_ids"][spec.code] == row.id
        assert row.name == spec.name
        assert row.description == spec.description
        assert row.tags == list(spec.tags)
        assert row.access_rules == {
            "always_accessible": True,
            "phase3_route_open": True,
        }
        expected_parent_id = (
            ids["location_ids"][spec.parent_code]
            if spec.parent_code is not None
            else None
        )
        assert row.parent_location_id == expected_parent_id

    npcs = {
        row.code: row
        for row in db_session.query(NPCTemplateModel).filter_by(world_id=world.id).all()
    }
    assert len(npcs) == 2
    assert set(npcs) == {spec.code for spec in NPC_SPECS}
    assert set(ids["npc_ids"]) == set(npcs)
    for spec in NPC_SPECS:
        row = npcs[spec.code]
        assert ids["npc_ids"][spec.code] == row.id
        assert row.name == spec.name
        assert row.public_identity == spec.public_identity
        assert row.personality == spec.personality
        assert row.initial_location_id == ids["location_ids"][spec.initial_location_code]

    items = {
        row.code: row
        for row in db_session.query(ItemTemplateModel).filter_by(world_id=world.id).all()
    }
    assert len(items) == 1
    assert set(items) == {ITEM_SPEC.code}
    assert set(ids["item_ids"]) == {ITEM_SPEC.code}
    item = items[ITEM_SPEC.code]
    assert ids["item_ids"][ITEM_SPEC.code] == item.id
    assert item.name == ITEM_SPEC.name
    assert item.item_type == ITEM_SPEC.item_type
    assert item.description == ITEM_SPEC.description


def test_seed_time_slice_is_idempotent_and_preserves_ids(db_session):
    first_ids = seed_time_slice(db_session)
    counts_before = _micro_counts(db_session, first_ids["world_id"])

    second_ids = seed_time_slice(db_session)
    counts_after = _micro_counts(db_session, first_ids["world_id"])

    assert second_ids == first_ids
    assert counts_after == counts_before == {
        "worlds": 1,
        "locations": 3,
        "npcs": 2,
        "items": 1,
    }


def test_seed_time_slice_rejects_location_conflict_without_overwriting(db_session):
    ids = seed_time_slice(db_session)
    location_spec = LOCATION_SPECS[0]
    row = (
        db_session.query(LocationModel)
        .filter_by(world_id=ids["world_id"], code=location_spec.code)
        .one()
    )
    row.name = "用户手动修改的山门名称"
    db_session.flush()

    with pytest.raises(TimeSliceSeedConflictError) as captured:
        seed_time_slice(db_session)

    error = captured.value
    assert error.code == location_spec.code
    assert error.entity_type == "location"
    assert error.conflicting_fields == ("name",)
    assert row.name == "用户手动修改的山门名称"


def test_seed_time_slice_isolated_from_default_world(db_session):
    default_ids = seed_all_content(db_session)
    default_world = (
        db_session.query(WorldModel).filter_by(code="cultivation_trial_world").one()
    )
    before = _world_snapshot(db_session, default_world.id)
    default_counts_before = {
        table: len(rows) for table, rows in before.items()
    }

    micro_ids = seed_time_slice(db_session)
    after = _world_snapshot(db_session, default_world.id)

    assert default_ids["world_id"] == default_world.id
    assert micro_ids["world_id"] != default_world.id
    assert after == before
    assert {table: len(rows) for table, rows in after.items()} == default_counts_before
    assert _micro_counts(db_session, micro_ids["world_id"]) == {
        "worlds": 1,
        "locations": 3,
        "npcs": 2,
        "items": 1,
    }
    assert resolve_phase3_profile(default_world) is None


def test_seed_time_slice_binds_phase3_profile_only_to_micro_world(db_session):
    default_ids = seed_all_content(db_session)
    micro_ids = seed_time_slice(db_session)
    micro_world = db_session.query(WorldModel).filter_by(id=micro_ids["world_id"]).one()
    default_world = db_session.query(WorldModel).filter_by(id=default_ids["world_id"]).one()

    assert resolve_phase3_profile(micro_world) == Phase3Profile(
        id="trial_micro_v1", schema_version=1
    )
    assert resolve_phase3_profile(default_world) is None
