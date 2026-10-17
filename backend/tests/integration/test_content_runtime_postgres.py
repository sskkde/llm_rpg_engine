"""PostgreSQL-only migration and nullable constraint gates for content_v1."""

import os
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from llm_rpg.storage.models import (
    ChapterModel,
    GameEventModel,
    ItemTemplateModel,
    MemoryFactModel,
    NPCPrivateMemoryModel,
    NPCTemplateModel,
    SaveSlotModel,
    SessionInventoryItemModel,
    SessionModel,
    StoryPackageVersionModel,
    TurnTransactionModel,
    UserModel,
    WorldModel,
)


TABLES = (
    "story_package_versions",
    "session_inventory_items",
    "npc_private_memories",
    "memory_facts",
)


@pytest.fixture
def pg_database(monkeypatch):
    """Create a disposable database derived only from PHASE1_TEST_DATABASE_URL."""
    required = os.getenv("PHASE1_REQUIRE_POSTGRES") == "1"
    raw_url = os.getenv("PHASE1_TEST_DATABASE_URL")
    if required and not raw_url:
        pytest.fail("PHASE1_REQUIRE_POSTGRES=1 requires PHASE1_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("Phase-4 content runtime tests require PHASE1_TEST_DATABASE_URL")
    base_url = make_url(raw_url)
    if base_url.get_backend_name() != "postgresql":
        pytest.fail("PHASE1_TEST_DATABASE_URL must use PostgreSQL")
    assert base_url.drivername == "postgresql+psycopg2", "acceptance URL must explicitly use psycopg2"

    database_name = f"phase4_content_{uuid.uuid4().hex}"
    admin_engine = create_engine(base_url)
    engine = None
    database_created = False
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    try:
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f'CREATE DATABASE "{database_name}"'))
        database_created = True

        database_url = base_url.set(database=database_name)
        rendered_url = database_url.render_as_string(hide_password=False)
        monkeypatch.setenv("DATABASE_URL", rendered_url)
        config.set_main_option("sqlalchemy.url", rendered_url.replace("%", "%%"))
        engine = create_engine(database_url)
        command.upgrade(config, "025")
        yield engine, config
    finally:
        if engine is not None:
            engine.dispose()
        if database_created:
            with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
        admin_engine.dispose()


def _seed_pre_026_rows(engine, suffix):
    """Insert one legacy row into each target table using only pre-026 columns."""
    stamp = datetime(2025, 1, 2, 3, 4, 5)
    ids = {
        "user": f"u-{suffix}",
        "world": f"w-{suffix}",
        "chapter": f"c-{suffix}",
        "slot": f"slot-{suffix}",
        "session": f"session-{suffix}",
        "version": f"version-{suffix}",
        "item": f"item-{suffix}",
        "npc_template": f"npc-template-{suffix}",
        "inventory": f"inventory-{suffix}",
        "npc_memory": f"npc-memory-{suffix}",
        "transaction": f"transaction-{suffix}",
        "game_event": f"game-event-{suffix}",
        "memory_fact": f"memory-fact-{suffix}",
    }
    with engine.begin() as conn:
        conn.execute(
            insert(UserModel.__table__).values(
                id=ids["user"],
                username=f"user-{suffix}",
                email=f"{suffix}@test.invalid",
                password_hash="legacy-password-hash",
                is_admin=False,
            )
        )
        conn.execute(
            insert(WorldModel.__table__).values(
                id=ids["world"],
                code=f"world-{suffix}",
                name="Legacy world",
                genre="test",
                status="active",
            )
        )
        conn.execute(
            insert(ChapterModel.__table__).values(
                id=ids["chapter"],
                world_id=ids["world"],
                chapter_no=1,
                name="Legacy chapter",
                summary="preserve this summary",
            )
        )
        conn.execute(
            insert(SaveSlotModel.__table__).values(
                id=ids["slot"],
                user_id=ids["user"],
                slot_number=1,
                name="Legacy slot",
            )
        )
        conn.execute(
            insert(StoryPackageVersionModel.__table__).values(
                id=ids["version"],
                story_package_id=f"package-{suffix}",
                version="1.0.0",
                status="published",
                world_id=ids["world"],
                manifest_json={"legacy": "manifest"},
                source_hash="legacy-source-hash",
            )
        )
        conn.execute(
            insert(SessionModel.__table__).values(
                id=ids["session"],
                user_id=ids["user"],
                save_slot_id=ids["slot"],
                world_id=ids["world"],
                current_chapter_id=ids["chapter"],
                status="active",
            )
        )
        conn.execute(
            insert(ItemTemplateModel.__table__).values(
                id=ids["item"],
                world_id=ids["world"],
                code=f"item-{suffix}",
                name="Legacy item",
            )
        )
        conn.execute(
            insert(NPCTemplateModel.__table__).values(
                id=ids["npc_template"],
                world_id=ids["world"],
                code=f"npc-{suffix}",
                name="Legacy NPC",
            )
        )
        conn.execute(
            insert(SessionInventoryItemModel.__table__).values(
                id=ids["inventory"],
                session_id=ids["session"],
                item_template_id=ids["item"],
                owner_type="player",
                owner_ref_id=None,
                quantity=1,
                bound_flag=False,
            )
        )
        conn.execute(
            insert(NPCPrivateMemoryModel.__table__).values(
                id=ids["npc_memory"],
                session_id=ids["session"],
                npc_id=ids["npc_template"],
                npc_template_id=ids["npc_template"],
                memory_type="episodic",
                content="preserve this memory",
                source_event_ids_json=[ids["game_event"]],
                importance=0.5,
                emotional_weight=0.0,
                confidence=1.0,
                current_strength=1.0,
                created_turn=1,
                last_accessed_turn=1,
            )
        )
        conn.execute(
            insert(TurnTransactionModel.__table__).values(
                id=ids["transaction"],
                session_id=ids["session"],
                turn_no=1,
                idempotency_key=f"turn-{suffix}",
                status="committed",
                started_at=stamp,
                committed_at=stamp,
            )
        )
        conn.execute(
            insert(GameEventModel.__table__).values(
                id=ids["game_event"],
                transaction_id=ids["transaction"],
                session_id=ids["session"],
                turn_no=1,
                event_type="legacy_event",
                occurred_at=stamp,
            )
        )
        conn.execute(
            insert(MemoryFactModel.__table__).values(
                id=ids["memory_fact"],
                session_id=ids["session"],
                fact_type="legacy_fact",
                subject_ref="player",
                fact_key="legacy-key",
                fact_value="preserve this fact",
                confidence=1.0,
                source_event_id=None,
            )
        )
    return ids


def _legacy_columns(engine):
    inspector = inspect(engine)
    return {
        table: [column["name"] for column in inspector.get_columns(table)]
        for table in TABLES
    }


def _capture_legacy_rows(engine, columns_by_table):
    captured = {}
    with engine.connect() as conn:
        for table, columns in columns_by_table.items():
            names = ", ".join(f'"{column}"' for column in columns)
            rows = conn.execute(
                text(f'SELECT {names} FROM "{table}" ORDER BY "id"')
            ).fetchall()
            captured[table] = [tuple(row) for row in rows]
    return captured


def _insert_one(engine, model, values):
    with engine.begin() as conn:
        conn.execute(insert(model.__table__).values(**values))


def _inventory_values(ids, row_id, instance_key):
    return {
        "id": row_id,
        "session_id": ids["session"],
        "item_template_id": ids["item"],
        "owner_type": "player",
        "owner_ref_id": None,
        "quantity": 1,
        "bound_flag": False,
        "instance_key": instance_key,
    }


def _npc_memory_values(ids, row_id, derivation_key):
    return {
        "id": row_id,
        "session_id": ids["session"],
        "npc_id": ids["npc_template"],
        "npc_template_id": ids["npc_template"],
        "memory_type": "episodic",
        "content": "derived memory",
        "importance": 0.5,
        "emotional_weight": 0.0,
        "confidence": 1.0,
        "current_strength": 1.0,
        "created_turn": 2,
        "last_accessed_turn": 2,
        "derivation_key": derivation_key,
    }


def _memory_fact_values(ids, row_id, derivation_key, fact_key):
    return {
        "id": row_id,
        "session_id": ids["session"],
        "fact_type": "player_knowledge",
        "subject_ref": "player",
        "fact_key": fact_key,
        "fact_value": "derived fact",
        "confidence": 1.0,
        "source_event_id": None,
        "source_game_event_id": None,
        "derivation_key": derivation_key,
    }


def test_migration_head_is_026():
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    assert ScriptDirectory.from_config(config).get_current_head() == "026"


def test_upgrade_preserves_existing_rows_and_null_columns(pg_database):
    engine, config = pg_database
    ids = _seed_pre_026_rows(engine, uuid.uuid4().hex)
    columns = _legacy_columns(engine)
    before = _capture_legacy_rows(engine, columns)
    before_counts = {table: len(rows) for table, rows in before.items()}

    command.upgrade(config, "026")

    after = _capture_legacy_rows(engine, columns)
    after_counts = {table: len(rows) for table, rows in after.items()}
    assert after_counts == before_counts
    assert after == before
    new_columns = {
        "story_package_versions": ("runtime_bundle_json", "runtime_hash", "runtime_schema_version"),
        "session_inventory_items": ("instance_key",),
        "npc_private_memories": ("derivation_key",),
        "memory_facts": ("source_game_event_id", "derivation_key"),
    }
    id_keys = {
        "story_package_versions": "version",
        "session_inventory_items": "inventory",
        "npc_private_memories": "npc_memory",
        "memory_facts": "memory_fact",
    }
    with engine.connect() as conn:
        for table, column_names in new_columns.items():
            selected = ", ".join(f'"{column}"' for column in column_names)
            row = conn.execute(
                text(f'SELECT {selected} FROM "{table}" WHERE id = :id'),
                {"id": ids[id_keys[table]]},
            ).one()
            assert tuple(row) == (None,) * len(column_names)


def test_unique_constraints_allow_multiple_nulls(pg_database):
    engine, config = pg_database
    ids = _seed_pre_026_rows(engine, uuid.uuid4().hex)
    command.upgrade(config, "026")

    null_ids = [f"inventory-null-{uuid.uuid4().hex}" for _ in range(2)]
    for row_id in null_ids:
        _insert_one(engine, SessionInventoryItemModel, _inventory_values(ids, row_id, None))
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM session_inventory_items WHERE id IN (:first, :second)"),
            {"first": null_ids[0], "second": null_ids[1]},
        ).scalar_one()
    assert count == 2

    duplicate_key = f"instance-{uuid.uuid4().hex}"
    _insert_one(
        engine,
        SessionInventoryItemModel,
        _inventory_values(ids, f"inventory-key-a-{uuid.uuid4().hex}", duplicate_key),
    )
    with pytest.raises(IntegrityError):
        _insert_one(
            engine,
            SessionInventoryItemModel,
            _inventory_values(ids, f"inventory-key-b-{uuid.uuid4().hex}", duplicate_key),
        )
    constraints = inspect(engine).get_unique_constraints("session_inventory_items")
    assert any(
        item["name"] == "uq_session_inventory_items_session_instance_key"
        and item["column_names"] == ["session_id", "instance_key"]
        for item in constraints
    )


def test_derivation_key_uniqueness(pg_database):
    engine, config = pg_database
    ids = _seed_pre_026_rows(engine, uuid.uuid4().hex)
    command.upgrade(config, "026")

    npc_null_ids = [f"npc-null-{uuid.uuid4().hex}" for _ in range(2)]
    for row_id in npc_null_ids:
        _insert_one(engine, NPCPrivateMemoryModel, _npc_memory_values(ids, row_id, None))
    fact_null_ids = [f"fact-null-{uuid.uuid4().hex}" for _ in range(2)]
    for row_id in fact_null_ids:
        _insert_one(
            engine,
            MemoryFactModel,
            _memory_fact_values(ids, row_id, None, f"null-{row_id}"),
        )
    with engine.connect() as conn:
        npc_null_count = conn.execute(
            text("SELECT COUNT(*) FROM npc_private_memories WHERE id IN (:first, :second)"),
            {"first": npc_null_ids[0], "second": npc_null_ids[1]},
        ).scalar_one()
        fact_null_count = conn.execute(
            text("SELECT COUNT(*) FROM memory_facts WHERE id IN (:first, :second)"),
            {"first": fact_null_ids[0], "second": fact_null_ids[1]},
        ).scalar_one()
    assert npc_null_count == 2
    assert fact_null_count == 2

    npc_key = f"npc-derivation-{uuid.uuid4().hex}"
    _insert_one(
        engine,
        NPCPrivateMemoryModel,
        _npc_memory_values(ids, f"npc-key-a-{uuid.uuid4().hex}", npc_key),
    )
    with pytest.raises(IntegrityError):
        _insert_one(
            engine,
            NPCPrivateMemoryModel,
            _npc_memory_values(ids, f"npc-key-b-{uuid.uuid4().hex}", npc_key),
        )

    fact_key = f"fact-derivation-{uuid.uuid4().hex}"
    _insert_one(
        engine,
        MemoryFactModel,
        _memory_fact_values(ids, f"fact-key-a-{uuid.uuid4().hex}", fact_key, "key-a"),
    )
    with pytest.raises(IntegrityError):
        _insert_one(
            engine,
            MemoryFactModel,
            _memory_fact_values(ids, f"fact-key-b-{uuid.uuid4().hex}", fact_key, "key-b"),
        )

    npc_constraints = inspect(engine).get_unique_constraints("npc_private_memories")
    fact_constraints = inspect(engine).get_unique_constraints("memory_facts")
    assert any(
        item["name"] == "uq_npc_private_memories_session_npc_derivation"
        and item["column_names"] == ["session_id", "npc_id", "derivation_key"]
        for item in npc_constraints
    )
    assert any(
        item["name"] == "uq_memory_facts_session_subject_derivation"
        and item["column_names"] == ["session_id", "subject_ref", "derivation_key"]
        for item in fact_constraints
    )


def test_memory_fact_source_game_event_fk_is_real(pg_database):
    engine, config = pg_database
    ids = _seed_pre_026_rows(engine, uuid.uuid4().hex)
    command.upgrade(config, "026")

    with pytest.raises(IntegrityError):
        _insert_one(
            engine,
            MemoryFactModel,
            _memory_fact_values(
                ids,
                f"fact-invalid-fk-{uuid.uuid4().hex}",
                None,
                "invalid-source",
            )
            | {"source_game_event_id": f"missing-{uuid.uuid4().hex}"},
        )
    valid_id = f"fact-valid-fk-{uuid.uuid4().hex}"
    _insert_one(
        engine,
        MemoryFactModel,
        _memory_fact_values(ids, valid_id, None, "valid-source")
        | {"source_game_event_id": ids["game_event"]},
    )
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT source_game_event_id FROM memory_facts WHERE id = :id"),
            {"id": valid_id},
        ).scalar_one() == ids["game_event"]
    foreign_keys = inspect(engine).get_foreign_keys("memory_facts")
    assert any(
        item["name"] == "fk_memory_facts_source_game_event_id"
        and item["constrained_columns"] == ["source_game_event_id"]
        and item["referred_table"] == "game_events"
        and item["referred_columns"] == ["id"]
        for item in foreign_keys
    )


def test_downgrade_removes_only_new_objects(pg_database):
    engine, config = pg_database
    _seed_pre_026_rows(engine, uuid.uuid4().hex)
    columns = _legacy_columns(engine)
    before = _capture_legacy_rows(engine, columns)
    before_counts = {table: len(rows) for table, rows in before.items()}

    command.upgrade(config, "026")
    command.downgrade(config, "025")

    inspector = inspect(engine)
    new_columns = {
        "story_package_versions": {"runtime_bundle_json", "runtime_hash", "runtime_schema_version"},
        "session_inventory_items": {"instance_key"},
        "npc_private_memories": {"derivation_key"},
        "memory_facts": {"source_game_event_id", "derivation_key"},
    }
    for table, names in new_columns.items():
        actual_columns = {column["name"] for column in inspector.get_columns(table)}
        assert names.isdisjoint(actual_columns)
    new_constraints = {
        "session_inventory_items": {"uq_session_inventory_items_session_instance_key"},
        "npc_private_memories": {"uq_npc_private_memories_session_npc_derivation"},
        "memory_facts": {
            "uq_memory_facts_session_subject_derivation",
            "fk_memory_facts_source_game_event_id",
        },
    }
    for table, names in new_constraints.items():
        unique_names = {item["name"] for item in inspector.get_unique_constraints(table)}
        foreign_key_names = {item["name"] for item in inspector.get_foreign_keys(table)}
        assert names.isdisjoint(unique_names | foreign_key_names)

    after = _capture_legacy_rows(engine, columns)
    after_counts = {table: len(rows) for table, rows in after.items()}
    assert after_counts == before_counts
    assert after == before
