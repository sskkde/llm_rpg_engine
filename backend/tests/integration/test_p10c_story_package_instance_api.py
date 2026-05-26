"""
P10-C Phase 2 integration tests: StoryPackageVersion publish + PlaythroughInstance
instantiate + baseline InstanceSnapshot services and admin API.

Covers:
- create version → get version
- publish version
- instantiate published version → creates playthrough instance + session
- instantiate with INSTANCE_SNAPSHOT_ENABLED=false does not create snapshot
- instantiate with INSTANCE_SNAPSHOT_ENABLED=true creates baseline snapshot and checksum
- old save/session flow still works
- draft version cannot be instantiated
- no secrets in snapshot JSON
"""

import os
import pytest
from datetime import datetime

from sqlalchemy.orm import Session as DBSession

from llm_rpg.storage.models import (
    WorldModel,
    UserModel,
    SaveSlotModel,
    SessionModel,
    StoryPackageVersionModel,
    PlaythroughInstanceModel,
    InstanceSnapshotModel,
    NPCTemplateModel,
    LocationModel,
    generate_uuid,
)
from llm_rpg.storage.repositories import (
    WorldRepository,
    UserRepository,
    SaveSlotRepository,
    SessionRepository,
    StoryPackageVersionRepository,
    PlaythroughInstanceRepository,
    InstanceSnapshotRepository,
    NPCTemplateRepository,
    LocationRepository,
)
from llm_rpg.core.story_package_service import (
    create_story_package_version,
    get_story_package_version,
    publish_story_package_version,
    StoryPackageVersionError,
)
from llm_rpg.core.instance_snapshot_service import (
    build_session_snapshot_json,
    compute_checksum,
    create_baseline_snapshot,
    create_manual_snapshot,
    restore_snapshot,
)
from llm_rpg.core.playthrough_instance_service import (
    create_playthrough_from_version,
    PlaythroughInstanceError,
)
from llm_rpg.core.feature_flags import instance_snapshot_enabled


def _seed_world(db: DBSession) -> WorldModel:
    repo = WorldRepository(db)
    return repo.create({"code": f"test-world-{generate_uuid()[:8]}", "name": "Test World"})


def _seed_user(db: DBSession, is_admin: bool = True) -> UserModel:
    repo = UserRepository(db)
    return repo.create({
        "username": f"testuser-{generate_uuid()[:8]}",
        "is_admin": is_admin,
    })


def _seed_location(db: DBSession, world_id: str, code: str = "square") -> LocationModel:
    repo = LocationRepository(db)
    return repo.create({"world_id": world_id, "code": code, "name": f"Test {code}"})


def _seed_npc_template(db: DBSession, world_id: str, code: str = "npc-001") -> NPCTemplateModel:
    repo = NPCTemplateRepository(db)
    return repo.create({"world_id": world_id, "code": code, "name": f"NPC {code}"})


def _create_published_version(db: DBSession, world_id: str) -> StoryPackageVersionModel:
    spv = create_story_package_version(
        db,
        story_package_id="sp-integ",
        version="1.0.0",
        world_id=world_id,
        manifest_json={"world": "test"},
    )
    return publish_story_package_version(db, spv.id)


# =============================================================================
# Story Package Version Service Tests
# =============================================================================

class TestStoryPackageVersionService:
    def test_create_and_get(self, db_session):
        spv = create_story_package_version(
            db_session,
            story_package_id="sp-svc-1",
            version="1.0.0",
        )
        assert spv.id is not None
        assert spv.status == "draft"

        fetched = get_story_package_version(db_session, spv.id)
        assert fetched is not None
        assert fetched.story_package_id == "sp-svc-1"
        assert fetched.version == "1.0.0"

    def test_create_duplicate_raises(self, db_session):
        create_story_package_version(db_session, story_package_id="sp-dup", version="1.0.0")
        with pytest.raises(StoryPackageVersionError):
            create_story_package_version(db_session, story_package_id="sp-dup", version="1.0.0")

    def test_publish_draft(self, db_session):
        spv = create_story_package_version(
            db_session, story_package_id="sp-pub", version="1.0.0",
        )
        published = publish_story_package_version(db_session, spv.id)
        assert published.status == "published"
        assert published.published_at is not None

    def test_publish_nonexistent_raises(self, db_session):
        with pytest.raises(StoryPackageVersionError):
            publish_story_package_version(db_session, "nonexistent-id")

    def test_publish_already_published_raises(self, db_session):
        spv = create_story_package_version(
            db_session, story_package_id="sp-repub", version="1.0.0",
        )
        publish_story_package_version(db_session, spv.id)
        with pytest.raises(StoryPackageVersionError, match="must be 'draft'"):
            publish_story_package_version(db_session, spv.id)


# =============================================================================
# Instance Snapshot Service Tests
# =============================================================================

class TestInstanceSnapshotService:
    def test_compute_checksum_deterministic(self):
        data = {"session_id": "abc", "turn": 1}
        c1 = compute_checksum(data)
        c2 = compute_checksum(data)
        assert c1 == c2
        assert len(c1) == 64  # SHA-256 hex

    def test_compute_checksum_differs_for_different_data(self):
        c1 = compute_checksum({"a": 1})
        c2 = compute_checksum({"a": 2})
        assert c1 != c2

    def test_build_snapshot_json_no_secrets(self, db_session):
        world = _seed_world(db_session)
        loc = _seed_location(db_session, world.id)
        _seed_npc_template(db_session, world.id)

        session_repo = SessionRepository(db_session)
        session = session_repo.create({
            "user_id": "user-snap-test",
            "world_id": world.id,
            "status": "active",
        })

        snapshot = build_session_snapshot_json(db_session, session.id)

        # Should have session_id
        assert snapshot["session_id"] == session.id

        # Should NOT contain any secret keys
        import json
        serialized = json.dumps(snapshot).lower()
        for forbidden in ["api_key", "password", "secret", "token", "openai"]:
            assert forbidden not in serialized, f"Snapshot contains forbidden key: {forbidden}"

    def test_create_baseline_snapshot(self, db_session):
        world = _seed_world(db_session)
        _seed_location(db_session, world.id)
        _seed_npc_template(db_session, world.id)

        session_repo = SessionRepository(db_session)
        session = session_repo.create({
            "user_id": "user-bl-snap",
            "world_id": world.id,
            "status": "active",
        })

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id="pi-bl-test",
            session_id=session.id,
        )
        assert snap.id is not None
        assert snap.snapshot_kind == "baseline"
        assert snap.turn_no == 0
        assert snap.checksum is not None
        assert len(snap.checksum) == 64
        assert snap.snapshot_json is not None
        assert snap.snapshot_json.get("session_id") == session.id

    def test_create_manual_snapshot(self, db_session):
        world = _seed_world(db_session)
        _seed_location(db_session, world.id)

        session_repo = SessionRepository(db_session)
        session = session_repo.create({
            "user_id": "user-man-snap",
            "world_id": world.id,
            "status": "active",
        })

        snap = create_manual_snapshot(
            db_session,
            playthrough_instance_id="pi-man-test",
            session_id=session.id,
            turn_no=5,
        )
        assert snap.snapshot_kind == "manual"
        assert snap.turn_no == 5
        assert snap.checksum is not None

    def test_restore_snapshot_read_only(self, db_session):
        world = _seed_world(db_session)
        _seed_location(db_session, world.id)

        session_repo = SessionRepository(db_session)
        session = session_repo.create({
            "user_id": "user-restore",
            "world_id": world.id,
            "status": "active",
        })

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id="pi-restore",
            session_id=session.id,
        )

        result = restore_snapshot(db_session, snap.id)
        assert result["snapshot_kind"] == "baseline"
        assert result["checksum"] == snap.checksum
        assert result["snapshot_json"] is not None

    def test_restore_snapshot_not_found(self, db_session):
        with pytest.raises(ValueError, match="not found"):
            restore_snapshot(db_session, "nonexistent")


# =============================================================================
# Playthrough Instance Service Tests
# =============================================================================

class TestPlaythroughInstanceService:
    def test_instantiate_published_version(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")
        world = _seed_world(db_session)
        _seed_location(db_session, world.id)
        _seed_npc_template(db_session, world.id)

        published = _create_published_version(db_session, world.id)

        result = create_playthrough_from_version(
            db_session,
            version_id=published.id,
            user_id="user-instantiate",
        )

        assert result.playthrough_instance_id is not None
        assert result.session_id is not None
        assert result.baseline_snapshot_id is None  # flag off

        # Verify instance
        pi_repo = PlaythroughInstanceRepository(db_session)
        pi = pi_repo.get_by_id(result.playthrough_instance_id)
        assert pi is not None
        assert pi.root_session_id == result.session_id
        assert pi.story_package_version_id == published.id
        assert pi.world_id == world.id
        assert pi.instance_status == "active"

        # Verify session
        session_repo = SessionRepository(db_session)
        session = session_repo.get_by_id(result.session_id)
        assert session is not None
        assert session.playthrough_instance_id == pi.id
        assert session.story_package_version_id == published.id
        assert session.session_type == "instance"
        assert session.runtime_status == "running"

    def test_instantiate_with_snapshot_enabled(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        _seed_location(db_session, world.id)
        _seed_npc_template(db_session, world.id)

        published = _create_published_version(db_session, world.id)

        result = create_playthrough_from_version(
            db_session,
            version_id=published.id,
            user_id="user-snap-on",
        )

        assert result.baseline_snapshot_id is not None

        # Verify snapshot exists
        snap_repo = InstanceSnapshotRepository(db_session)
        snap = snap_repo.get_by_id(result.baseline_snapshot_id)
        assert snap is not None
        assert snap.snapshot_kind == "baseline"
        assert snap.checksum is not None

        # Verify instance has baseline_snapshot_id set
        pi_repo = PlaythroughInstanceRepository(db_session)
        pi = pi_repo.get_by_id(result.playthrough_instance_id)
        assert pi.baseline_snapshot_id == result.baseline_snapshot_id
        assert pi.current_snapshot_id == result.baseline_snapshot_id

        # Verify session entry_snapshot_id
        session_repo = SessionRepository(db_session)
        session = session_repo.get_by_id(result.session_id)
        assert session.entry_snapshot_id == result.baseline_snapshot_id

    def test_instantiate_flag_off_no_snapshot(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")
        world = _seed_world(db_session)
        _seed_location(db_session, world.id)
        _seed_npc_template(db_session, world.id)

        published = _create_published_version(db_session, world.id)

        result = create_playthrough_from_version(
            db_session,
            version_id=published.id,
            user_id="user-snap-off",
        )

        assert result.baseline_snapshot_id is None

        # Verify no snapshots exist for this instance
        snap_repo = InstanceSnapshotRepository(db_session)
        snaps = snap_repo.list_by_instance(result.playthrough_instance_id)
        assert len(snaps) == 0

    def test_instantiate_draft_raises(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")
        world = _seed_world(db_session)

        draft = create_story_package_version(
            db_session,
            story_package_id="sp-draft-inst",
            version="0.1.0",
            world_id=world.id,
        )

        with pytest.raises(PlaythroughInstanceError, match="must be 'published'"):
            create_playthrough_from_version(db_session, version_id=draft.id)

    def test_instantiate_nonexistent_raises(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")
        with pytest.raises(PlaythroughInstanceError, match="not found"):
            create_playthrough_from_version(db_session, version_id="nonexistent")

    def test_instantiate_no_world_id_raises(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")
        # Create a version without world_id
        spv_repo = StoryPackageVersionRepository(db_session)
        spv = spv_repo.create({
            "story_package_id": "sp-no-world",
            "version": "1.0.0",
            "status": "published",
            "published_at": datetime.now(),
            "world_id": None,
        })

        with pytest.raises(PlaythroughInstanceError, match="no world_id"):
            create_playthrough_from_version(db_session, version_id=spv.id)


# =============================================================================
# Old Save/Session Compatibility Tests
# =============================================================================

class TestOldSaveSessionCompatibility:
    def test_old_save_flow_still_works(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")
        monkeypatch.setenv("STORY_PACKAGE_INSTANCE_ENABLED", "false")

        world = _seed_world(db_session)
        user = _seed_user(db_session, is_admin=False)

        # Old save creation flow
        save_repo = SaveSlotRepository(db_session)
        slot = save_repo.create({
            "user_id": user.id,
            "slot_number": 1,
            "name": "Test Save",
        })
        assert slot.id is not None

        # Old session creation flow (no playthrough instance)
        session_repo = SessionRepository(db_session)
        session = session_repo.create({
            "user_id": user.id,
            "save_slot_id": slot.id,
            "world_id": world.id,
            "status": "active",
        })
        assert session.id is not None
        assert session.playthrough_instance_id is None
        assert session.story_package_version_id is None
        assert session.session_type is None
        assert session.runtime_status is None

    def test_old_session_initialization_still_works(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")
        monkeypatch.setenv("STORY_PACKAGE_INSTANCE_ENABLED", "false")

        from llm_rpg.core.session_initialization import initialize_session_story_state

        world = _seed_world(db_session)
        _seed_location(db_session, world.id)
        _seed_npc_template(db_session, world.id)

        session_repo = SessionRepository(db_session)
        session = session_repo.create({
            "user_id": "user-old-init",
            "world_id": world.id,
            "status": "active",
        })

        # Should not raise
        initialize_session_story_state(db_session, session.id)

        # Verify state was created
        from llm_rpg.storage.repositories import (
            SessionStateRepository,
            SessionPlayerStateRepository,
        )
        ss_repo = SessionStateRepository(db_session)
        ss = ss_repo.get_by_session(session.id)
        assert ss is not None

        ps_repo = SessionPlayerStateRepository(db_session)
        ps = ps_repo.get_by_session(session.id)
        assert ps is not None


# =============================================================================
# Admin API Endpoint Tests
# =============================================================================

class TestStoryPackageVersionAdminAPI:
    @pytest.fixture(autouse=True)
    def _setup_admin(self, client, engine):
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

        from sqlalchemy.orm import sessionmaker
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        try:
            self._admin_username = f"admin-p10c-{generate_uuid()[:8]}"
            self._admin_password = "AdminPass123!"
            user_repo = UserRepository(db)
            user_repo.create({
                "username": self._admin_username,
                "password_hash": pwd_context.hash(self._admin_password),
                "is_admin": True,
            })
            db.commit()
        finally:
            db.close()

        login_resp = client.post("/auth/login", json={
            "username": self._admin_username,
            "password": self._admin_password,
        })
        token = login_resp.json()["access_token"]
        self._headers = {"Authorization": f"Bearer {token}"}

    def test_create_version_api(self, client, db_session):
        world = _seed_world(db_session)

        resp = client.post(
            "/admin/story-package-versions",
            json={
                "story_package_id": "sp-api-1",
                "version": "1.0.0",
                "world_id": world.id,
            },
            headers=self._headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert data["story_package_id"] == "sp-api-1"

    def test_get_version_api(self, client, db_session):
        world = _seed_world(db_session)

        create_resp = client.post(
            "/admin/story-package-versions",
            json={
                "story_package_id": "sp-api-get",
                "version": "1.0.0",
                "world_id": world.id,
            },
            headers=self._headers,
        )
        version_id = create_resp.json()["id"]

        get_resp = client.get(
            f"/admin/story-package-versions/{version_id}",
            headers=self._headers,
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == version_id

    def test_publish_version_api(self, client, db_session):
        world = _seed_world(db_session)

        create_resp = client.post(
            "/admin/story-package-versions",
            json={
                "story_package_id": "sp-api-pub",
                "version": "1.0.0",
                "world_id": world.id,
            },
            headers=self._headers,
        )
        version_id = create_resp.json()["id"]

        pub_resp = client.post(
            f"/admin/story-package-versions/{version_id}/publish",
            headers=self._headers,
        )
        assert pub_resp.status_code == 200
        assert pub_resp.json()["status"] == "published"
        assert pub_resp.json()["published_at"] is not None

    def test_instantiate_version_api(self, client, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")
        world = _seed_world(db_session)
        _seed_location(db_session, world.id)
        _seed_npc_template(db_session, world.id)

        create_resp = client.post(
            "/admin/story-package-versions",
            json={
                "story_package_id": "sp-api-inst",
                "version": "1.0.0",
                "world_id": world.id,
            },
            headers=self._headers,
        )
        version_id = create_resp.json()["id"]

        client.post(
            f"/admin/story-package-versions/{version_id}/publish",
            headers=self._headers,
        )

        inst_resp = client.post(
            f"/admin/story-package-versions/{version_id}/instantiate",
            json={"user_id": "user-api-inst"},
            headers=self._headers,
        )
        assert inst_resp.status_code == 201
        data = inst_resp.json()
        assert data["playthrough_instance_id"] is not None
        assert data["session_id"] is not None
        assert data["baseline_snapshot_id"] is None

    def test_instantiate_with_snapshot_api(self, client, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        _seed_location(db_session, world.id)
        _seed_npc_template(db_session, world.id)

        create_resp = client.post(
            "/admin/story-package-versions",
            json={
                "story_package_id": "sp-api-snap",
                "version": "1.0.0",
                "world_id": world.id,
            },
            headers=self._headers,
        )
        version_id = create_resp.json()["id"]

        client.post(
            f"/admin/story-package-versions/{version_id}/publish",
            headers=self._headers,
        )

        inst_resp = client.post(
            f"/admin/story-package-versions/{version_id}/instantiate",
            json={"user_id": "user-api-snap"},
            headers=self._headers,
        )
        assert inst_resp.status_code == 201
        data = inst_resp.json()
        assert data["baseline_snapshot_id"] is not None

    def test_instantiate_draft_fails_api(self, client, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")
        world = _seed_world(db_session)

        create_resp = client.post(
            "/admin/story-package-versions",
            json={
                "story_package_id": "sp-api-draft",
                "version": "1.0.0",
                "world_id": world.id,
            },
            headers=self._headers,
        )
        version_id = create_resp.json()["id"]

        inst_resp = client.post(
            f"/admin/story-package-versions/{version_id}/instantiate",
            json={},
            headers=self._headers,
        )
        assert inst_resp.status_code == 422

    def test_get_nonexistent_version_404(self, client, db_session):
        resp = client.get(
            "/admin/story-package-versions/nonexistent-id",
            headers=self._headers,
        )
        assert resp.status_code == 404