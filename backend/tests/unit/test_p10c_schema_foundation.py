import os
import pytest
from datetime import datetime

from llm_rpg.storage.models import (
    StoryPackageVersionModel,
    PlaythroughInstanceModel,
    InstanceSnapshotModel,
    SessionModel,
    NPCTemplateModel,
    generate_uuid,
)
from llm_rpg.storage.repositories import (
    StoryPackageVersionRepository,
    PlaythroughInstanceRepository,
    InstanceSnapshotRepository,
)
from llm_rpg.core.feature_flags import (
    story_package_instance_enabled,
    instance_snapshot_enabled,
    npc_memory_first_enabled,
)


class TestStoryPackageVersionModel:
    def test_construction_defaults(self, db_session):
        spv = StoryPackageVersionModel(
            story_package_id="sp-001",
            version="1.0.0",
        )
        db_session.add(spv)
        db_session.commit()
        db_session.refresh(spv)

        assert spv.id is not None
        assert spv.story_package_id == "sp-001"
        assert spv.version == "1.0.0"
        assert spv.status == "draft"
        assert spv.manifest_json == {}
        assert spv.world_id is None
        assert spv.editor_schema_version is None
        assert spv.source_hash is None
        assert spv.published_at is None
        assert spv.created_at is not None
        assert spv.updated_at is not None

    def test_published_state(self, db_session):
        spv = StoryPackageVersionModel(
            story_package_id="sp-002",
            version="2.0.0",
            status="published",
            published_at=datetime.now(),
            manifest_json={"world": "test"},
        )
        db_session.add(spv)
        db_session.commit()
        db_session.refresh(spv)

        assert spv.status == "published"
        assert spv.published_at is not None
        assert spv.manifest_json == {"world": "test"}


class TestPlaythroughInstanceModel:
    def test_construction_defaults(self, db_session):
        pi = PlaythroughInstanceModel(
            world_id="world-001",
        )
        db_session.add(pi)
        db_session.commit()
        db_session.refresh(pi)

        assert pi.id is not None
        assert pi.world_id == "world-001"
        assert pi.story_package_version_id is None
        assert pi.user_id is None
        assert pi.root_session_id is None
        assert pi.baseline_snapshot_id is None
        assert pi.current_snapshot_id is None
        assert pi.current_turn_no == 0
        assert pi.instance_status == "active"
        assert pi.config_json == {}
        assert pi.created_at is not None
        assert pi.updated_at is not None

    def test_with_optional_fks(self, db_session):
        pi = PlaythroughInstanceModel(
            world_id="world-002",
            user_id="user-001",
            story_package_version_id="spv-001",
            config_json={"difficulty": "hard"},
        )
        db_session.add(pi)
        db_session.commit()
        db_session.refresh(pi)

        assert pi.user_id == "user-001"
        assert pi.config_json == {"difficulty": "hard"}


class TestInstanceSnapshotModel:
    def test_construction_defaults(self, db_session):
        snap = InstanceSnapshotModel(
            playthrough_instance_id="pi-001",
            session_id="sess-001",
            snapshot_kind="baseline",
        )
        db_session.add(snap)
        db_session.commit()
        db_session.refresh(snap)

        assert snap.id is not None
        assert snap.playthrough_instance_id == "pi-001"
        assert snap.session_id == "sess-001"
        assert snap.snapshot_kind == "baseline"
        assert snap.turn_no == 0
        assert snap.source_transaction_id is None
        assert snap.snapshot_json == {}
        assert snap.checksum is None
        assert snap.parent_snapshot_id is None
        assert snap.created_at is not None

    def test_checkpoint_snapshot(self, db_session):
        snap = InstanceSnapshotModel(
            playthrough_instance_id="pi-002",
            session_id="sess-002",
            snapshot_kind="checkpoint",
            turn_no=5,
            snapshot_json={"state": "snapshot"},
            checksum="abc123",
        )
        db_session.add(snap)
        db_session.commit()
        db_session.refresh(snap)

        assert snap.snapshot_kind == "checkpoint"
        assert snap.turn_no == 5
        assert snap.checksum == "abc123"


class TestSessionModelLineageColumns:
    def test_p10c_columns_default_none(self, db_session):
        session = SessionModel(
            user_id="user-001",
            world_id="world-001",
        )
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        assert session.playthrough_instance_id is None
        assert session.story_package_version_id is None
        assert session.entry_snapshot_id is None
        assert session.resume_snapshot_id is None
        assert session.session_type is None
        assert session.runtime_status is None

    def test_p10c_columns_set(self, db_session):
        session = SessionModel(
            user_id="user-002",
            world_id="world-001",
            playthrough_instance_id="pi-001",
            story_package_version_id="spv-001",
            session_type="instance",
            runtime_status="running",
        )
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        assert session.playthrough_instance_id == "pi-001"
        assert session.story_package_version_id == "spv-001"
        assert session.session_type == "instance"
        assert session.runtime_status == "running"


class TestNPCTemplateModelP10CColumns:
    def test_is_major_npc_default_false(self, db_session):
        npc = NPCTemplateModel(
            world_id="world-001",
            code="npc-001",
            name="Test NPC",
        )
        db_session.add(npc)
        db_session.commit()
        db_session.refresh(npc)

        assert npc.is_major_npc is False
        assert npc.memory_profile_json is None
        assert npc.seed_memory_bundle_json is None

    def test_is_major_npc_set_true(self, db_session):
        npc = NPCTemplateModel(
            world_id="world-001",
            code="npc-002",
            name="Major NPC",
            is_major_npc=True,
            memory_profile_json={"retrieval_budget": 5},
            seed_memory_bundle_json=[{"text": "I remember the old days"}],
        )
        db_session.add(npc)
        db_session.commit()
        db_session.refresh(npc)

        assert npc.is_major_npc is True
        assert npc.memory_profile_json == {"retrieval_budget": 5}
        assert npc.seed_memory_bundle_json == [{"text": "I remember the old days"}]

    def test_is_major_npc_false_compatible(self, db_session):
        npc = NPCTemplateModel(
            world_id="world-001",
            code="npc-003",
            name="Minor NPC",
            is_major_npc=False,
        )
        db_session.add(npc)
        db_session.commit()
        db_session.refresh(npc)

        assert npc.is_major_npc is False


class TestStoryPackageVersionRepository:
    def test_create_and_get(self, db_session):
        repo = StoryPackageVersionRepository(db_session)
        spv = repo.create({
            "story_package_id": "sp-repo-001",
            "version": "1.0.0",
            "status": "draft",
        })
        assert spv.id is not None

        fetched = repo.get_by_id(spv.id)
        assert fetched is not None
        assert fetched.story_package_id == "sp-repo-001"

    def test_get_latest_published(self, db_session):
        repo = StoryPackageVersionRepository(db_session)
        repo.create({
            "story_package_id": "sp-pub",
            "version": "1.0.0",
            "status": "draft",
        })
        published = repo.create({
            "story_package_id": "sp-pub",
            "version": "2.0.0",
            "status": "published",
            "published_at": datetime.now(),
        })
        result = repo.get_latest_published("sp-pub")
        assert result is not None
        assert result.version == "2.0.0"

    def test_get_by_story_package_and_version(self, db_session):
        repo = StoryPackageVersionRepository(db_session)
        repo.create({
            "story_package_id": "sp-ver",
            "version": "1.0.0",
        })
        repo.create({
            "story_package_id": "sp-ver",
            "version": "2.0.0",
        })
        result = repo.get_by_story_package_and_version("sp-ver", "1.0.0")
        assert result is not None
        assert result.version == "1.0.0"

    def test_list_by_story_package(self, db_session):
        repo = StoryPackageVersionRepository(db_session)
        repo.create({"story_package_id": "sp-list", "version": "1.0.0"})
        repo.create({"story_package_id": "sp-list", "version": "2.0.0"})
        results = repo.list_by_story_package("sp-list")
        assert len(results) == 2


class TestPlaythroughInstanceRepository:
    def test_create_and_get(self, db_session):
        repo = PlaythroughInstanceRepository(db_session)
        pi = repo.create({
            "world_id": "world-repo-001",
            "instance_status": "active",
        })
        assert pi.id is not None

        fetched = repo.get_by_id(pi.id)
        assert fetched is not None
        assert fetched.world_id == "world-repo-001"

    def test_get_by_root_session(self, db_session):
        repo = PlaythroughInstanceRepository(db_session)
        repo.create({
            "world_id": "world-rs",
            "root_session_id": "sess-rs-001",
        })
        result = repo.get_by_root_session("sess-rs-001")
        assert result is not None
        assert result.root_session_id == "sess-rs-001"

    def test_get_by_root_session_not_found(self, db_session):
        repo = PlaythroughInstanceRepository(db_session)
        result = repo.get_by_root_session("nonexistent")
        assert result is None

    def test_list_by_user(self, db_session):
        repo = PlaythroughInstanceRepository(db_session)
        repo.create({"world_id": "world-u", "user_id": "user-list"})
        repo.create({"world_id": "world-u2", "user_id": "user-list"})
        results = repo.list_by_user("user-list")
        assert len(results) == 2


class TestInstanceSnapshotRepository:
    def test_create_and_get(self, db_session):
        repo = InstanceSnapshotRepository(db_session)
        snap = repo.create({
            "playthrough_instance_id": "pi-snap",
            "session_id": "sess-snap",
            "snapshot_kind": "baseline",
        })
        assert snap.id is not None

        fetched = repo.get_by_id(snap.id)
        assert fetched is not None
        assert fetched.snapshot_kind == "baseline"

    def test_get_latest_snapshot(self, db_session):
        repo = InstanceSnapshotRepository(db_session)
        repo.create({
            "playthrough_instance_id": "pi-latest",
            "session_id": "sess-l1",
            "snapshot_kind": "baseline",
            "turn_no": 0,
        })
        repo.create({
            "playthrough_instance_id": "pi-latest",
            "session_id": "sess-l1",
            "snapshot_kind": "turn",
            "turn_no": 3,
        })
        result = repo.get_latest_snapshot("pi-latest")
        assert result is not None
        assert result.turn_no == 3

    def test_get_baseline_snapshot(self, db_session):
        repo = InstanceSnapshotRepository(db_session)
        repo.create({
            "playthrough_instance_id": "pi-bl",
            "session_id": "sess-bl",
            "snapshot_kind": "baseline",
            "turn_no": 0,
        })
        repo.create({
            "playthrough_instance_id": "pi-bl",
            "session_id": "sess-bl",
            "snapshot_kind": "turn",
            "turn_no": 1,
        })
        result = repo.get_baseline_snapshot("pi-bl")
        assert result is not None
        assert result.snapshot_kind == "baseline"

    def test_get_baseline_snapshot_not_found(self, db_session):
        repo = InstanceSnapshotRepository(db_session)
        repo.create({
            "playthrough_instance_id": "pi-nobl",
            "session_id": "sess-nobl",
            "snapshot_kind": "turn",
            "turn_no": 1,
        })
        result = repo.get_baseline_snapshot("pi-nobl")
        assert result is None

    def test_list_by_instance(self, db_session):
        repo = InstanceSnapshotRepository(db_session)
        repo.create({
            "playthrough_instance_id": "pi-list",
            "session_id": "sess-il",
            "snapshot_kind": "baseline",
            "turn_no": 0,
        })
        repo.create({
            "playthrough_instance_id": "pi-list",
            "session_id": "sess-il",
            "snapshot_kind": "checkpoint",
            "turn_no": 5,
        })
        results = repo.list_by_instance("pi-list")
        assert len(results) == 2

    def test_list_by_session(self, db_session):
        repo = InstanceSnapshotRepository(db_session)
        repo.create({
            "playthrough_instance_id": "pi-sl",
            "session_id": "sess-sl",
            "snapshot_kind": "baseline",
        })
        results = repo.list_by_session("sess-sl")
        assert len(results) == 1


class TestFeatureFlags:
    def test_story_package_instance_default_false(self, monkeypatch):
        monkeypatch.delenv("STORY_PACKAGE_INSTANCE_ENABLED", raising=False)
        assert story_package_instance_enabled() is False

    def test_story_package_instance_enabled_true(self, monkeypatch):
        monkeypatch.setenv("STORY_PACKAGE_INSTANCE_ENABLED", "true")
        assert story_package_instance_enabled() is True

    def test_story_package_instance_enabled_1(self, monkeypatch):
        monkeypatch.setenv("STORY_PACKAGE_INSTANCE_ENABLED", "1")
        assert story_package_instance_enabled() is True

    def test_instance_snapshot_default_false(self, monkeypatch):
        monkeypatch.delenv("INSTANCE_SNAPSHOT_ENABLED", raising=False)
        assert instance_snapshot_enabled() is False

    def test_instance_snapshot_enabled_true(self, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        assert instance_snapshot_enabled() is True

    def test_npc_memory_first_default_false(self, monkeypatch):
        monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
        assert npc_memory_first_enabled() is False

    def test_npc_memory_first_enabled_true(self, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        assert npc_memory_first_enabled() is True

    def test_npc_memory_first_enabled_yes(self, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "yes")
        assert npc_memory_first_enabled() is True

    def test_flags_off_no_runtime_change(self, monkeypatch):
        monkeypatch.delenv("STORY_PACKAGE_INSTANCE_ENABLED", raising=False)
        monkeypatch.delenv("INSTANCE_SNAPSHOT_ENABLED", raising=False)
        monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
        assert story_package_instance_enabled() is False
        assert instance_snapshot_enabled() is False
        assert npc_memory_first_enabled() is False
