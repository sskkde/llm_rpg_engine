"""
Tests for player-facing story package instantiate endpoint and NPC memory
recall-stat updates.

Covers:
- Successful instantiation of latest published version
- Unauthenticated access returns 401
- Feature flag off returns 403
- No published version returns 404
- Draft versions are not selectable
- User ownership of created playthrough/session
- Latest version selection when multiple published versions exist
- Recall stats: selected memories get recall_count incremented
- Recall stats: unselected memories remain unchanged
- Recall stats: skipped when current_turn <= 0
- Response excludes admin-only fields (baseline_snapshot_id)
"""

import os
import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, get_db
from llm_rpg.storage.models import (
    WorldModel,
    LocationModel,
    NPCTemplateModel,
    SessionModel,
    NPCPrivateMemoryModel,
    NPCMemoryScopeModel,
    UserModel,
    SystemSettingsModel,
    StoryPackageVersionModel,
    PlaythroughInstanceModel,
    generate_uuid,
)
from llm_rpg.storage.repositories import (
    NPCPrivateMemoryRepository,
    StoryPackageVersionRepository,
    PlaythroughInstanceRepository,
    SessionRepository,
)
from llm_rpg.main import app


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


def _make_client(engine):
    from fastapi.testclient import TestClient

    def override_get_db():
        connection = engine.connect()
        db = sessionmaker(bind=connection)()
        try:
            yield db
        finally:
            db.close()
            connection.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return client


def _ensure_settings(engine):
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        settings = db.query(SystemSettingsModel).first()
        if not settings:
            settings = SystemSettingsModel(
                id="settings-test",
                debug_enabled=True,
                registration_enabled=True,
                maintenance_mode=False,
            )
            db.add(settings)
        else:
            settings.registration_enabled = True
        db.commit()
    finally:
        db.close()


def _register_user(client, username=None):
    uname = username or f"user-{generate_uuid()[:6]}"
    resp = client.post("/auth/register", json={
        "username": uname,
        "email": f"{uname}@test.com",
        "password": "UserPass123!",
    })
    assert resp.status_code in (200, 201)
    token = resp.json()["access_token"]
    user_id = resp.json()["user"]["id"]
    return token, user_id, uname


def _make_world_with_published_version(db, story_package_id="pkg-test", version="1.0", status="published"):
    world = WorldModel(code=f"w-{generate_uuid()[:8]}", name="Test World")
    db.add(world)
    db.commit()
    db.refresh(world)

    location = LocationModel(world_id=world.id, code="square", name="Square")
    db.add(location)
    db.commit()
    db.refresh(location)

    now = datetime.now()
    spv = StoryPackageVersionModel(
        story_package_id=story_package_id,
        version=version,
        status=status,
        world_id=world.id,
        manifest_json={"pack_name": "test"},
        published_at=now if status == "published" else None,
    )
    db.add(spv)
    db.commit()
    db.refresh(spv)
    return world, spv


class TestPlayerInstantiateSuccess:
    def test_successful_instantiation(self, monkeypatch):
        monkeypatch.setenv("STORY_PACKAGE_INSTANCE_ENABLED", "true")
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")

        engine = _make_engine()
        client = _make_client(engine)
        _ensure_settings(engine)

        token, user_id, _ = _register_user(client)
        headers = {"Authorization": f"Bearer {token}"}

        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        try:
            world, spv = _make_world_with_published_version(db)
            sp_id = spv.story_package_id
        finally:
            db.close()

        resp = client.post(
            "/sessions/instantiate",
            json={"story_package_id": sp_id},
            headers=headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "playthrough_instance_id" in data
        assert "session_id" in data
        assert "baseline_snapshot_id" not in data

        pi_id = data["playthrough_instance_id"]
        session_id = data["session_id"]

        db = SessionLocal()
        try:
            pi_repo = PlaythroughInstanceRepository(db)
            pi = pi_repo.get_by_id(pi_id)
            assert pi is not None
            assert pi.user_id == user_id

            sess_repo = SessionRepository(db)
            sess = sess_repo.get_by_id(session_id)
            assert sess is not None
            assert sess.user_id == user_id
        finally:
            db.close()

        app.dependency_overrides.clear()


class TestPlayerInstantiateAuth:
    def test_unauthenticated_returns_401(self, monkeypatch):
        monkeypatch.setenv("STORY_PACKAGE_INSTANCE_ENABLED", "true")
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")

        engine = _make_engine()
        client = _make_client(engine)
        _ensure_settings(engine)

        resp = client.post(
            "/sessions/instantiate",
            json={"story_package_id": "pkg-test"},
        )
        assert resp.status_code == 401

        app.dependency_overrides.clear()


class TestPlayerInstantiateFlagOff:
    def test_flag_off_returns_403(self, monkeypatch):
        monkeypatch.delenv("STORY_PACKAGE_INSTANCE_ENABLED", raising=False)

        engine = _make_engine()
        client = _make_client(engine)
        _ensure_settings(engine)

        token, _, _ = _register_user(client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/sessions/instantiate",
            json={"story_package_id": "pkg-test"},
            headers=headers,
        )
        assert resp.status_code == 403
        assert "not enabled" in resp.json()["detail"].lower()

        app.dependency_overrides.clear()


class TestPlayerInstantiateNoPublished:
    def test_no_published_version_returns_404(self, monkeypatch):
        monkeypatch.setenv("STORY_PACKAGE_INSTANCE_ENABLED", "true")
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")

        engine = _make_engine()
        client = _make_client(engine)
        _ensure_settings(engine)

        token, _, _ = _register_user(client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/sessions/instantiate",
            json={"story_package_id": "nonexistent-pkg"},
            headers=headers,
        )
        assert resp.status_code == 404

        app.dependency_overrides.clear()

    def test_draft_version_not_selectable(self, monkeypatch):
        monkeypatch.setenv("STORY_PACKAGE_INSTANCE_ENABLED", "true")
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")

        engine = _make_engine()
        client = _make_client(engine)
        _ensure_settings(engine)

        token, _, _ = _register_user(client)
        headers = {"Authorization": f"Bearer {token}"}

        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        try:
            world, spv = _make_world_with_published_version(
                db, story_package_id="pkg-draft", status="draft",
            )
            sp_id = spv.story_package_id
        finally:
            db.close()

        resp = client.post(
            "/sessions/instantiate",
            json={"story_package_id": sp_id},
            headers=headers,
        )
        assert resp.status_code == 404

        app.dependency_overrides.clear()


class TestPlayerInstantiateUserOwnership:
    def test_playthrough_and_session_owned_by_user(self, monkeypatch):
        monkeypatch.setenv("STORY_PACKAGE_INSTANCE_ENABLED", "true")
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")

        engine = _make_engine()
        client = _make_client(engine)
        _ensure_settings(engine)

        token, user_id, _ = _register_user(client)
        headers = {"Authorization": f"Bearer {token}"}

        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        try:
            world, spv = _make_world_with_published_version(db)
            sp_id = spv.story_package_id
        finally:
            db.close()

        resp = client.post(
            "/sessions/instantiate",
            json={"story_package_id": sp_id},
            headers=headers,
        )
        assert resp.status_code == 201
        data = resp.json()

        db = SessionLocal()
        try:
            pi_repo = PlaythroughInstanceRepository(db)
            pi = pi_repo.get_by_id(data["playthrough_instance_id"])
            assert pi.user_id == user_id

            sess_repo = SessionRepository(db)
            sess = sess_repo.get_by_id(data["session_id"])
            assert sess.user_id == user_id
        finally:
            db.close()

        app.dependency_overrides.clear()


class TestPlayerInstantiateLatestVersion:
    def test_selects_latest_published_version(self, monkeypatch):
        monkeypatch.setenv("STORY_PACKAGE_INSTANCE_ENABLED", "true")
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")

        engine = _make_engine()
        client = _make_client(engine)
        _ensure_settings(engine)

        token, _, _ = _register_user(client)
        headers = {"Authorization": f"Bearer {token}"}

        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        try:
            world = WorldModel(code=f"w-{generate_uuid()[:8]}", name="Test World")
            db.add(world)
            db.commit()
            db.refresh(world)

            location = LocationModel(world_id=world.id, code="square", name="Square")
            db.add(location)
            db.commit()

            pkg_id = "pkg-multi"

            from datetime import timedelta
            old_time = datetime.now() - timedelta(days=10)
            recent_time = datetime.now()

            old_spv = StoryPackageVersionModel(
                story_package_id=pkg_id,
                version="1.0",
                status="published",
                world_id=world.id,
                manifest_json={"pack_name": "old"},
                published_at=old_time,
            )
            db.add(old_spv)
            db.commit()
            db.refresh(old_spv)

            recent_spv = StoryPackageVersionModel(
                story_package_id=pkg_id,
                version="2.0",
                status="published",
                world_id=world.id,
                manifest_json={"pack_name": "recent"},
                published_at=recent_time,
            )
            db.add(recent_spv)
            db.commit()
            db.refresh(recent_spv)

            recent_spv_id = recent_spv.id
        finally:
            db.close()

        resp = client.post(
            "/sessions/instantiate",
            json={"story_package_id": pkg_id},
            headers=headers,
        )
        assert resp.status_code == 201
        data = resp.json()

        db = SessionLocal()
        try:
            pi_repo = PlaythroughInstanceRepository(db)
            pi = pi_repo.get_by_id(data["playthrough_instance_id"])
            assert pi.story_package_version_id == recent_spv_id
        finally:
            db.close()

        app.dependency_overrides.clear()

    def test_ignores_draft_when_published_exists(self, monkeypatch):
        monkeypatch.setenv("STORY_PACKAGE_INSTANCE_ENABLED", "true")
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")

        engine = _make_engine()
        client = _make_client(engine)
        _ensure_settings(engine)

        token, _, _ = _register_user(client)
        headers = {"Authorization": f"Bearer {token}"}

        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        try:
            world = WorldModel(code=f"w-{generate_uuid()[:8]}", name="Test World")
            db.add(world)
            db.commit()
            db.refresh(world)

            location = LocationModel(world_id=world.id, code="square", name="Square")
            db.add(location)
            db.commit()

            pkg_id = "pkg-mixed"

            published_spv = StoryPackageVersionModel(
                story_package_id=pkg_id,
                version="1.0",
                status="published",
                world_id=world.id,
                manifest_json={},
                published_at=datetime.now(),
            )
            db.add(published_spv)
            db.commit()
            db.refresh(published_spv)

            draft_spv = StoryPackageVersionModel(
                story_package_id=pkg_id,
                version="2.0",
                status="draft",
                world_id=world.id,
                manifest_json={},
            )
            db.add(draft_spv)
            db.commit()
            db.refresh(draft_spv)

            published_spv_id = published_spv.id
        finally:
            db.close()

        resp = client.post(
            "/sessions/instantiate",
            json={"story_package_id": pkg_id},
            headers=headers,
        )
        assert resp.status_code == 201
        data = resp.json()

        db = SessionLocal()
        try:
            pi_repo = PlaythroughInstanceRepository(db)
            pi = pi_repo.get_by_id(data["playthrough_instance_id"])
            assert pi.story_package_version_id == published_spv_id
        finally:
            db.close()

        app.dependency_overrides.clear()


class TestPlayerInstantiateResponseExcludesAdminFields:
    def test_response_has_no_admin_fields(self, monkeypatch):
        monkeypatch.setenv("STORY_PACKAGE_INSTANCE_ENABLED", "true")
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")

        engine = _make_engine()
        client = _make_client(engine)
        _ensure_settings(engine)

        token, _, _ = _register_user(client)
        headers = {"Authorization": f"Bearer {token}"}

        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        try:
            world, spv = _make_world_with_published_version(db)
            sp_id = spv.story_package_id
        finally:
            db.close()

        resp = client.post(
            "/sessions/instantiate",
            json={"story_package_id": sp_id},
            headers=headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        admin_fields = {"baseline_snapshot_id", "editor_schema_version", "source_hash"}
        for field_name in admin_fields:
            assert field_name not in data

        app.dependency_overrides.clear()


# =========================================================================
# Recall-stat tests (NPC memory retrieval service)
# =========================================================================

def _make_world_session_npcs(db, major_count=1):
    world = WorldModel(code=f"w-{generate_uuid()[:8]}", name="Test World")
    db.add(world)
    db.commit()
    db.refresh(world)

    location = LocationModel(world_id=world.id, code="square", name="Square")
    db.add(location)
    db.commit()
    db.refresh(location)

    session = SessionModel(user_id="user-test", world_id=world.id, status="active")
    db.add(session)
    db.commit()
    db.refresh(session)

    major_npcs = []
    for i in range(major_count):
        npc = NPCTemplateModel(
            world_id=world.id,
            code=f"major-{i}",
            name=f"Major NPC {i}",
            is_major_npc=True,
            memory_profile_json={"max_memories": 10},
        )
        db.add(npc)
        db.commit()
        db.refresh(npc)
        major_npcs.append(npc)

    return world, session, major_npcs


def _add_private_memory(db, session_id, npc_template_id, **kwargs):
    npc_id = kwargs.pop("npc_id", npc_template_id)
    memory_type = kwargs.pop("memory_type", "episodic")
    content = kwargs.pop("content", "Test memory")
    created_turn = kwargs.pop("created_turn", 1)
    data = {
        "session_id": session_id,
        "npc_id": npc_id,
        "npc_template_id": npc_template_id,
        "memory_type": memory_type,
        "content": content,
        "created_turn": created_turn,
        "last_accessed_turn": created_turn,
    }
    data.update(kwargs)
    repo = NPCPrivateMemoryRepository(db)
    return repo.create(data)


class TestRecallIncrementsSelected:
    def test_retrieval_default_does_not_commit_recall(self, db_session, monkeypatch):
        """Pure retrieval (default) must NOT persist recall stats."""
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs = _make_world_session_npcs(db_session)

        m1 = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="High salience", status="active", visibility="npc_private",
            importance=0.9, salience=0.9, source_turn_no=5,
        )

        from llm_rpg.core.npc_memory_retrieval_service import retrieve_major_npc_memories
        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
            current_turn=10, budget=1,
        )

        assert result.selected_count == 1
        db_session.refresh(m1)
        assert m1.recall_count == 0
        assert "recall_updated_count" not in result.retrieval_audit
        assert result.retrieval_audit.get("recall_eligible_count") == 1

    def test_opt_in_updates_selected_memories(self, db_session, monkeypatch):
        """Explicit opt-in update_recall_stats=True still works."""
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs = _make_world_session_npcs(db_session)

        m1 = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="High salience", status="active", visibility="npc_private",
            importance=0.9, salience=0.9, source_turn_no=5,
        )
        m2 = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Low salience", status="active", visibility="npc_private",
            importance=0.1, salience=0.1, source_turn_no=5,
        )

        from llm_rpg.core.npc_memory_retrieval_service import retrieve_major_npc_memories
        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
            current_turn=10, budget=1, update_recall_stats=True,
        )

        assert result.selected_count == 1

        db_session.refresh(m1)
        db_session.refresh(m2)

        if m1.id in result.used_memory_ids:
            assert m1.recall_count == 1
            assert m1.last_accessed_turn == 10
            assert m2.recall_count == 0
        else:
            assert m2.recall_count == 1
            assert m2.last_accessed_turn == 10
            assert m1.recall_count == 0

    def test_all_selected_memories_updated_with_opt_in(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs = _make_world_session_npcs(db_session)

        m1 = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Memory A", status="active", visibility="npc_private",
            importance=0.8, salience=0.8, source_turn_no=3,
        )
        m2 = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Memory B", status="active", visibility="npc_private",
            importance=0.7, salience=0.7, source_turn_no=4,
        )

        from llm_rpg.core.npc_memory_retrieval_service import retrieve_major_npc_memories
        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
            current_turn=7, budget=10, update_recall_stats=True,
        )

        assert result.selected_count == 2

        db_session.refresh(m1)
        db_session.refresh(m2)

        assert m1.recall_count == 1
        assert m1.last_accessed_turn == 7
        assert m2.recall_count == 1
        assert m2.last_accessed_turn == 7

        assert result.retrieval_audit.get("recall_updated_count") == 2


class TestRecallUnselectedUnchanged:
    def test_unselected_memories_unchanged_with_opt_in(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs = _make_world_session_npcs(db_session)

        m_selected = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Selected memory", status="active", visibility="npc_private",
            importance=0.9, salience=0.9, source_turn_no=5,
        )
        m_unselected = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Unselected memory", status="active", visibility="npc_private",
            importance=0.1, salience=0.1, source_turn_no=1,
        )

        from llm_rpg.core.npc_memory_retrieval_service import retrieve_major_npc_memories
        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
            current_turn=10, budget=1, update_recall_stats=True,
        )

        db_session.refresh(m_unselected)
        assert m_unselected.recall_count == 0
        assert m_unselected.last_accessed_turn == 1

        db_session.refresh(m_selected)
        assert m_selected.recall_count == 1


class TestRecallSkippedWhenNoTurn:
    def test_no_recall_update_when_current_turn_zero(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs = _make_world_session_npcs(db_session)

        m = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Test memory", status="active", visibility="npc_private",
            importance=0.5, salience=0.5, source_turn_no=3,
        )

        from llm_rpg.core.npc_memory_retrieval_service import retrieve_major_npc_memories
        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
            current_turn=0,
        )

        db_session.refresh(m)
        assert m.recall_count == 0
        assert "recall_updated_count" not in result.retrieval_audit
        assert "recall_eligible_count" not in result.retrieval_audit

    def test_no_recall_update_when_current_turn_negative(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs = _make_world_session_npcs(db_session)

        m = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Test memory", status="active", visibility="npc_private",
            importance=0.5, salience=0.5, source_turn_no=3,
        )

        from llm_rpg.core.npc_memory_retrieval_service import retrieve_major_npc_memories
        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
            current_turn=-1,
        )

        db_session.refresh(m)
        assert m.recall_count == 0


class TestRecallCumulativeUpdates:
    def test_multiple_opt_in_retrievals_accumulate_recall(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs = _make_world_session_npcs(db_session)

        m = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Important memory", status="active", visibility="npc_private",
            importance=0.9, salience=0.9, source_turn_no=1,
        )

        from llm_rpg.core.npc_memory_retrieval_service import retrieve_major_npc_memories

        retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
            current_turn=5, update_recall_stats=True,
        )
        db_session.refresh(m)
        assert m.recall_count == 1
        assert m.last_accessed_turn == 5

        retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
            current_turn=10, update_recall_stats=True,
        )
        db_session.refresh(m)
        assert m.recall_count == 2
        assert m.last_accessed_turn == 10

    def test_batch_post_commit_update_recall_stats(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs = _make_world_session_npcs(db_session)

        m1 = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Memory A", status="active", visibility="npc_private",
            importance=0.8, salience=0.8, source_turn_no=3,
        )
        m2 = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Memory B", status="active", visibility="npc_private",
            importance=0.7, salience=0.7, source_turn_no=4,
        )

        from llm_rpg.core.npc_memory_retrieval_service import batch_update_recall_stats
        updated = batch_update_recall_stats(
            db_session, [m1.id, m2.id], current_turn=7,
        )
        assert updated == 2

        db_session.refresh(m1)
        db_session.refresh(m2)
        assert m1.recall_count == 1
        assert m1.last_accessed_turn == 7
        assert m2.recall_count == 1
        assert m2.last_accessed_turn == 7

    def test_post_commit_recall_stats_via_writer(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs = _make_world_session_npcs(db_session)

        m = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Memory for writer", status="active", visibility="npc_private",
            importance=0.8, salience=0.8, source_turn_no=3,
        )

        from llm_rpg.core.post_commit_memory_writer import update_recall_stats_post_commit
        updated = update_recall_stats_post_commit(
            db_session, session.id, major_npcs[0].id,
            used_memory_ids=[m.id], current_turn=7,
        )
        assert updated == 1

        db_session.refresh(m)
        assert m.recall_count == 1
        assert m.last_accessed_turn == 7

    def test_default_retrieval_then_batch_commit(self, db_session, monkeypatch):
        """Simulate the full safe path: retrieve (no stats), then batch update after commit."""
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs = _make_world_session_npcs(db_session)

        m = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Safe path memory", status="active", visibility="npc_private",
            importance=0.9, salience=0.9, source_turn_no=1,
        )

        from llm_rpg.core.npc_memory_retrieval_service import retrieve_major_npc_memories, batch_update_recall_stats

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
            current_turn=5,
        )
        assert result.used_memory_ids == [m.id]
        db_session.refresh(m)
        assert m.recall_count == 0

        batch_update_recall_stats(db_session, result.used_memory_ids, current_turn=5)
        db_session.refresh(m)
        assert m.recall_count == 1
        assert m.last_accessed_turn == 5
