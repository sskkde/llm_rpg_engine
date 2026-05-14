"""Tests for AssetRepository."""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import IntegrityError

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import AssetModel
from llm_rpg.storage.repositories import AssetRepository

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


class TestAssetRepository:
    def test_create_asset(self, db_session):
        repo = AssetRepository(db_session)
        asset = repo.create({
            "id": "asset-1",
            "asset_id": "pub-asset-1",
            "asset_type": "portrait",
            "status": "pending",
            "provider_name": "mock",
            "request_params": {"prompt": "test"},
            "cache_key": None,
        })
        assert asset.id == "asset-1"
        assert asset.asset_id == "pub-asset-1"

    def test_get_by_asset_id(self, db_session):
        repo = AssetRepository(db_session)
        repo.create({"id": "asset-1", "asset_id": "pub-1", "asset_type": "portrait"})
        asset = repo.get_by_asset_id("pub-1")
        assert asset is not None
        assert asset.asset_id == "pub-1"

    def test_get_ready_by_cache_key(self, db_session):
        repo = AssetRepository(db_session)
        repo.create({
            "id": "a1",
            "asset_id": "pub-1",
            "asset_type": "portrait",
            "cache_key": "ck-1",
            "status": "completed"
        })
        repo.create({
            "id": "a2",
            "asset_id": "pub-2",
            "asset_type": "portrait",
            "cache_key": "ck-2",
            "status": "failed"
        })

        ready = repo.get_ready_by_cache_key("ck-1")
        assert ready is not None
        assert ready.asset_id == "pub-1"

        not_ready = repo.get_ready_by_cache_key("ck-2")
        assert not_ready is None

    def test_list_by_session(self, db_session):
        repo = AssetRepository(db_session)
        repo.create({
            "id": "a1",
            "asset_id": "pub-1",
            "session_id": "s1",
            "asset_type": "portrait"
        })
        repo.create({
            "id": "a2",
            "asset_id": "pub-2",
            "session_id": "s1",
            "asset_type": "scene"
        })
        repo.create({
            "id": "a3",
            "asset_id": "pub-3",
            "session_id": "s2",
            "asset_type": "portrait"
        })

        all_s1 = repo.list_by_session("s1")
        assert len(all_s1) == 2

        portraits_s1 = repo.list_by_session("s1", asset_type="portrait")
        assert len(portraits_s1) == 1

    def test_update_status(self, db_session):
        repo = AssetRepository(db_session)
        repo.create({
            "id": "a1",
            "asset_id": "pub-1",
            "asset_type": "portrait",
            "status": "pending"
        })

        updated = repo.update_status(
            "pub-1",
            status="completed",
            result_url="https://example.com/asset.png"
        )
        assert updated is not None
        assert updated.status == "completed"
        assert updated.result_url == "https://example.com/asset.png"

    def test_cache_key_uniqueness(self, db_session):
        repo = AssetRepository(db_session)
        repo.create({
            "id": "a1",
            "asset_id": "pub-1",
            "asset_type": "portrait",
            "cache_key": "unique-key"
        })

        with pytest.raises(IntegrityError):
            repo.create({
                "id": "a2",
                "asset_id": "pub-2",
                "asset_type": "portrait",
                "cache_key": "unique-key"
            })

    def test_no_fk_constraints(self, db_session):
        repo = AssetRepository(db_session)
        asset = repo.create({
            "id": "fk-test",
            "asset_id": "pub-fk-test",
            "asset_type": "bgm",
            "owner_entity_id": "non-existent-entity-id",
            "owner_entity_type": "npc",
            "session_id": "non-existent-session",
            "world_id": "non-existent-world",
        })
        assert asset.id == "fk-test"
        assert asset.owner_entity_id == "non-existent-entity-id"

    def test_list_by_owner(self, db_session):
        repo = AssetRepository(db_session)
        repo.create({
            "id": "a1",
            "asset_id": "pub-1",
            "owner_entity_id": "npc-001",
            "owner_entity_type": "npc",
            "asset_type": "portrait"
        })
        repo.create({
            "id": "a2",
            "asset_id": "pub-2",
            "owner_entity_id": "npc-001",
            "owner_entity_type": "npc",
            "asset_type": "scene"
        })
        repo.create({
            "id": "a3",
            "asset_id": "pub-3",
            "owner_entity_id": "npc-002",
            "owner_entity_type": "npc",
            "asset_type": "portrait"
        })

        all_npc1 = repo.list_by_owner("npc-001")
        assert len(all_npc1) == 2

        npc1_portraits = repo.list_by_owner("npc-001", owner_entity_type="npc")
        assert len(npc1_portraits) == 2

    def test_update_status_with_error(self, db_session):
        repo = AssetRepository(db_session)
        repo.create({
            "id": "a1",
            "asset_id": "pub-1",
            "asset_type": "portrait",
            "status": "processing"
        })

        updated = repo.update_status(
            "pub-1",
            status="failed",
            error_message="Provider timeout"
        )
        assert updated is not None
        assert updated.status == "failed"
        assert updated.error_message == "Provider timeout"

    def test_asset_id_uniqueness(self, db_session):
        repo = AssetRepository(db_session)
        repo.create({
            "id": "a1",
            "asset_id": "pub-unique",
            "asset_type": "portrait"
        })

        with pytest.raises(IntegrityError):
            repo.create({
                "id": "a2",
                "asset_id": "pub-unique",
                "asset_type": "scene"
            })

    def test_nullable_cache_key(self, db_session):
        repo = AssetRepository(db_session)

        asset1 = repo.create({
            "id": "a1",
            "asset_id": "pub-1",
            "asset_type": "portrait",
            "cache_key": None
        })
        assert asset1.cache_key is None

        asset2 = repo.create({
            "id": "a2",
            "asset_id": "pub-2",
            "asset_type": "portrait",
            "cache_key": None
        })
        assert asset2.cache_key is None

    def test_default_status(self, db_session):
        repo = AssetRepository(db_session)
        asset = repo.create({
            "id": "a1",
            "asset_id": "pub-1",
            "asset_type": "portrait"
        })
        assert asset.status == "pending"

    def test_get_by_asset_id_not_found(self, db_session):
        repo = AssetRepository(db_session)
        asset = repo.get_by_asset_id("non-existent")
        assert asset is None

    def test_get_ready_by_cache_key_none_cache_key(self, db_session):
        repo = AssetRepository(db_session)
        repo.create({
            "id": "a1",
            "asset_id": "pub-1",
            "asset_type": "portrait",
            "cache_key": None,
            "status": "completed"
        })

        result = repo.get_ready_by_cache_key(None)
        assert result is None
