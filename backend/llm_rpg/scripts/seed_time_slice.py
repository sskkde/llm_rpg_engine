#!/usr/bin/env python3
"""Seed the fixed, opt-in phase-3 time-simulation micro world.

Usage from ``backend/``::

    python -m llm_rpg.scripts.seed_time_slice

The seed is scoped to the phase-3 world's stable codes. It never rewrites an
existing row: matching rows are reused, while rows that disagree with the fixed
scenario definition fail closed with :class:`TimeSliceSeedConflictError`.
"""

from __future__ import annotations

import os
import sys
import uuid
from typing import Any, Dict, Iterable, Mapping, Sequence

# Keep the command runnable as ``python -m`` from the backend directory, just
# like seed_content.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.core.time_simulation_rules import (
    ITEM_SPEC,
    LOCATION_SPECS,
    MICRO_WORLD_CODE,
    NPC_SPECS,
    WORLD_SPEC,
    profile_marker,
)
from llm_rpg.storage.database import Base, DATABASE_URL
from llm_rpg.storage.models import (
    ItemTemplateModel,
    LocationModel,
    NPCTemplateModel,
    WorldModel,
)
from llm_rpg.storage.repositories import (
    ItemTemplateRepository,
    LocationRepository,
    NPCTemplateRepository,
    WorldRepository,
)


class TimeSliceSeedConflictError(ValueError):
    """An existing fixed-code row disagrees with the phase-3 seed definition."""

    def __init__(
        self,
        *,
        entity_type: str,
        code: str,
        conflicting_fields: Sequence[str],
    ) -> None:
        self.entity_type = entity_type
        self.code = code
        self.conflicting_fields = tuple(conflicting_fields)
        fields = ", ".join(self.conflicting_fields)
        super().__init__(
            f"phase-3 seed conflict for {entity_type} code {code!r}: {fields}"
        )


def _new_id() -> str:
    """Allocate stable IDs before preflight so parent links can be checked."""
    return str(uuid.uuid4())


def _index_existing_rows(
    rows: Iterable[Any], *, expected_codes: Iterable[str], entity_type: str
) -> Dict[str, Any]:
    """Index only this seed's fixed codes, rejecting pre-existing duplicates."""
    expected = set(expected_codes)
    indexed: Dict[str, Any] = {}
    for row in rows:
        if row.code not in expected:
            continue
        if row.code in indexed:
            raise TimeSliceSeedConflictError(
                entity_type=entity_type,
                code=row.code,
                conflicting_fields=("duplicate_rows",),
            )
        indexed[row.code] = row
    return indexed


def _validate_existing(
    existing: Any,
    *,
    entity_type: str,
    code: str,
    expected: Mapping[str, Any],
) -> None:
    conflicts = [
        field
        for field, expected_value in expected.items()
        if getattr(existing, field) != expected_value
    ]
    if conflicts:
        raise TimeSliceSeedConflictError(
            entity_type=entity_type,
            code=code,
            conflicting_fields=conflicts,
        )


def seed_time_slice(db: Session) -> Dict[str, Any]:
    """Idempotently create the fixed phase-3 micro world and return its IDs.

    The function flushes inserts but does not commit; transaction ownership stays
    with its caller. All existing fixed-code rows are checked before any inserts
    are staged, so a definition conflict never partially seeds or rewrites data.
    """
    world_repository = WorldRepository(db)
    location_repository = LocationRepository(db)
    npc_repository = NPCTemplateRepository(db)
    item_repository = ItemTemplateRepository(db)

    existing_world = world_repository.get_by_code(MICRO_WORLD_CODE)
    world_id = existing_world.id if existing_world is not None else _new_id()
    expected_world = {**WORLD_SPEC, "ruleset_json": profile_marker()}
    if existing_world is not None:
        _validate_existing(
            existing_world,
            entity_type="world",
            code=MICRO_WORLD_CODE,
            expected=expected_world,
        )

    location_codes = [spec.code for spec in LOCATION_SPECS]
    existing_locations = _index_existing_rows(
        location_repository.get_by_world(world_id),
        expected_codes=location_codes,
        entity_type="location",
    )
    location_ids = {
        spec.code: (
            existing_locations[spec.code].id
            if spec.code in existing_locations
            else _new_id()
        )
        for spec in LOCATION_SPECS
    }
    location_expected: Dict[str, Dict[str, Any]] = {}
    for spec in LOCATION_SPECS:
        parent_id = (
            location_ids[spec.parent_code] if spec.parent_code is not None else None
        )
        location_expected[spec.code] = {
            "world_id": world_id,
            "code": spec.code,
            "name": spec.name,
            "description": spec.description,
            "tags": list(spec.tags),
            "access_rules": {
                "always_accessible": True,
                "phase3_route_open": True,
            },
            "parent_location_id": parent_id,
        }
        existing = existing_locations.get(spec.code)
        if existing is not None:
            _validate_existing(
                existing,
                entity_type="location",
                code=spec.code,
                expected=location_expected[spec.code],
            )

    npc_codes = [spec.code for spec in NPC_SPECS]
    existing_npcs = _index_existing_rows(
        npc_repository.get_by_world(world_id),
        expected_codes=npc_codes,
        entity_type="npc_template",
    )
    npc_ids = {
        spec.code: existing_npcs[spec.code].id if spec.code in existing_npcs else _new_id()
        for spec in NPC_SPECS
    }
    npc_expected: Dict[str, Dict[str, Any]] = {}
    for spec in NPC_SPECS:
        npc_expected[spec.code] = {
            "world_id": world_id,
            "code": spec.code,
            "name": spec.name,
            "public_identity": spec.public_identity,
            "personality": spec.personality,
            "initial_location_id": location_ids[spec.initial_location_code],
        }
        existing = existing_npcs.get(spec.code)
        if existing is not None:
            _validate_existing(
                existing,
                entity_type="npc_template",
                code=spec.code,
                expected=npc_expected[spec.code],
            )

    existing_items = _index_existing_rows(
        item_repository.get_by_world(world_id),
        expected_codes=(ITEM_SPEC.code,),
        entity_type="item_template",
    )
    item_id = existing_items[ITEM_SPEC.code].id if ITEM_SPEC.code in existing_items else _new_id()
    item_expected = {
        "world_id": world_id,
        "code": ITEM_SPEC.code,
        "name": ITEM_SPEC.name,
        "item_type": ITEM_SPEC.item_type,
        "description": ITEM_SPEC.description,
    }
    existing_item = existing_items.get(ITEM_SPEC.code)
    if existing_item is not None:
        _validate_existing(
            existing_item,
            entity_type="item_template",
            code=ITEM_SPEC.code,
            expected=item_expected,
        )

    # All fixed-code rows have passed preflight. Insert with explicit IDs and
    # flush locations in spec order, ensuring each parent exists before a child.
    if existing_world is None:
        db.add(WorldModel(id=world_id, **expected_world))
        db.flush()

    for spec in LOCATION_SPECS:
        if spec.code in existing_locations:
            continue
        data = location_expected[spec.code]
        db.add(LocationModel(id=location_ids[spec.code], **data))
        db.flush()

    for spec in NPC_SPECS:
        if spec.code in existing_npcs:
            continue
        db.add(NPCTemplateModel(id=npc_ids[spec.code], **npc_expected[spec.code]))
    if ITEM_SPEC.code not in existing_items:
        db.add(ItemTemplateModel(id=item_id, **item_expected))
    db.flush()

    return {
        "world_id": world_id,
        "location_ids": location_ids,
        "npc_ids": npc_ids,
        "item_ids": {ITEM_SPEC.code: item_id},
    }


def main() -> int:
    """Run the seed using the same engine/session conventions as seed_content."""
    database_url = DATABASE_URL or "sqlite:///./seed.db"
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if "sqlite" in database_url else {},
        poolclass=StaticPool if "sqlite" in database_url else None,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        ids = seed_time_slice(db)
        db.commit()
        print(
            f"Seeded phase-3 world {MICRO_WORLD_CODE!r} "
            f"(id: {ids['world_id']})"
        )
        return 0
    except TimeSliceSeedConflictError as exc:
        db.rollback()
        print(f"Seed conflict: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
