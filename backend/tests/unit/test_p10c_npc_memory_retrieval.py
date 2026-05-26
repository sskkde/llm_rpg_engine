"""
P10-C Phase 5: Major NPC Memory Retrieval tests.

Covers:
- Self-only filtering (session + npc_template_id isolation)
- Lexical match ranking
- Salience/recency tie-breaks
- Flag-off fallback/empty
- Non-major NPC empty/fallback
- Debug endpoint auth/safe response
- Context enrichment shape
"""

import os
import pytest
from datetime import datetime
from sqlalchemy.orm import sessionmaker

from llm_rpg.storage.models import (
    WorldModel,
    LocationModel,
    NPCTemplateModel,
    SessionModel,
    SessionNPCStateModel,
    NPCPrivateMemoryModel,
    NPCMemoryScopeModel,
    UserModel,
    SystemSettingsModel,
    generate_uuid,
)
from llm_rpg.storage.repositories import (
    NPCPrivateMemoryRepository,
    NPCMemoryScopeRepository,
    NPCTemplateRepository,
    SessionRepository,
    WorldRepository,
)
from llm_rpg.core.npc_memory_retrieval_service import (
    retrieve_major_npc_memories,
    enrich_npc_context_with_memories,
    RetrievalResult,
    RetrievedMemory,
)
from llm_rpg.core.npc_seed_memory_service import seed_major_npc_private_memories
from llm_rpg.core.feature_flags import npc_memory_first_enabled


def _make_world_session_npcs(db, major_count=1, minor_count=0):
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
            seed_memory_bundle_json=[
                {
                    "text": f"Seed memory for major NPC {i}",
                    "importance": 0.7,
                    "tags": ["seed"],
                    "entities": [f"npc_{i}"],
                }
            ],
            memory_profile_json={"max_memories": 10},
        )
        db.add(npc)
        db.commit()
        db.refresh(npc)
        major_npcs.append(npc)

    minor_npcs = []
    for i in range(minor_count):
        npc = NPCTemplateModel(
            world_id=world.id,
            code=f"minor-{i}",
            name=f"Minor NPC {i}",
            is_major_npc=False,
        )
        db.add(npc)
        db.commit()
        db.refresh(npc)
        minor_npcs.append(npc)

    return world, session, major_npcs, minor_npcs


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


class TestSelfOnlyFiltering:
    """Memories from other sessions or NPCs must never appear."""

    def test_other_session_memories_excluded(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="This session memory", status="active", visibility="npc_private",
        )

        other_session = SessionModel(user_id="user-other", world_id=world.id, status="active")
        db_session.add(other_session)
        db_session.commit()
        db_session.refresh(other_session)

        _add_private_memory(
            db_session, other_session.id, major_npcs[0].id,
            content="Other session memory", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(db_session, session.id, major_npcs[0].id)
        assert result.total_candidates == 1
        assert result.memories[0].text == "This session memory"

    def test_other_npc_memories_excluded(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session, major_count=2)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="NPC 0 memory", status="active", visibility="npc_private",
        )
        _add_private_memory(
            db_session, session.id, major_npcs[1].id,
            content="NPC 1 memory", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(db_session, session.id, major_npcs[0].id)
        assert result.total_candidates == 1
        assert result.memories[0].text == "NPC 0 memory"

    def test_superseded_memories_excluded(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Active memory", status="active", visibility="npc_private",
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Superseded memory", status="superseded", visibility="npc_private",
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Archived memory", status="archived", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(db_session, session.id, major_npcs[0].id)
        assert result.total_candidates == 1
        assert result.memories[0].text == "Active memory"


class TestLexicalMatchRanking:
    """Lexical scoring should boost memories matching query terms."""

    def test_query_matching_memory_ranks_higher(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="The ancient sword of fire", status="active", visibility="npc_private",
            importance=0.5, salience=0.5, source_turn_no=1,
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="A calm day by the river", status="active", visibility="npc_private",
            importance=0.5, salience=0.5, source_turn_no=1,
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
            query="ancient sword",
        )
        assert len(result.memories) == 2
        assert "sword" in result.memories[0].text.lower()
        assert result.memories[0].signals["lexical"] > result.memories[1].signals["lexical"]

    def test_no_query_zero_lexical(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Some memory", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(db_session, session.id, major_npcs[0].id)
        assert result.memories[0].signals["lexical"] == 0.0


class TestSalienceRecencyTiebreaks:
    """Higher salience and more recent memories should rank higher."""

    def test_higher_salience_ranks_higher(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Low salience", status="active", visibility="npc_private",
            importance=0.3, salience=0.3, source_turn_no=1,
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="High salience", status="active", visibility="npc_private",
            importance=0.9, salience=0.9, source_turn_no=1,
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id, current_turn=2,
        )
        assert result.memories[0].text == "High salience"
        assert result.memories[0].score > result.memories[1].score

    def test_more_recent_ranks_higher(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Old memory", status="active", visibility="npc_private",
            importance=0.5, salience=0.5, source_turn_no=1,
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Recent memory", status="active", visibility="npc_private",
            importance=0.5, salience=0.5, source_turn_no=10,
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id, current_turn=12,
        )
        assert result.memories[0].text == "Recent memory"

    def test_budget_limits_results(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        for i in range(5):
            _add_private_memory(
                db_session, session.id, major_npcs[0].id,
                content=f"Memory {i}", status="active", visibility="npc_private",
                importance=0.5, salience=0.5, source_turn_no=i,
            )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id, budget=2,
        )
        assert result.selected_count == 2
        assert result.total_candidates == 5


class TestFlagOffFallback:
    """When NPC_MEMORY_FIRST_ENABLED is off, retrieval returns empty."""

    def test_flag_off_returns_empty(self, db_session, monkeypatch):
        monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Should not appear", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(db_session, session.id, major_npcs[0].id)
        assert result.total_candidates == 0
        assert result.selected_count == 0
        assert result.memories == []
        assert result.retrieval_audit.get("flag_enabled") is False


class TestNonMajorNPCFallback:
    """Non-major NPCs should get empty results even with flag on."""

    def test_minor_npc_returns_empty(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, minor_npcs = _make_world_session_npcs(
            db_session, major_count=1, minor_count=1,
        )

        _add_private_memory(
            db_session, session.id, minor_npcs[0].id,
            content="Minor NPC memory", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(db_session, session.id, minor_npcs[0].id)
        assert result.total_candidates == 0
        assert result.selected_count == 0
        assert result.retrieval_audit.get("reason", "").startswith("NPC is not major")

    def test_nonexistent_npc_returns_empty(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        result = retrieve_major_npc_memories(db_session, "fake-session", "fake-npc")
        assert result.total_candidates == 0
        assert result.selected_count == 0


class TestContextEnrichmentShape:
    """enrich_npc_context_with_memories adds keys additively."""

    def test_enrichment_adds_keys(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Enriched memory", status="active", visibility="npc_private",
        )

        original = {"profile": {"name": "Test"}, "existing_key": "kept"}
        enriched = enrich_npc_context_with_memories(
            original, db_session, session.id, major_npcs[0].id,
        )

        assert enriched["existing_key"] == "kept"
        assert "retrieved_private_memories" in enriched
        assert "used_memory_ids" in enriched
        assert "memory_retrieval_audit" in enriched
        assert len(enriched["retrieved_private_memories"]) == 1
        assert enriched["retrieved_private_memories"][0]["text"] == "Enriched memory"
        assert enriched["memory_retrieval_audit"]["flag_enabled"] is True

    def test_enrichment_does_not_mutate_input(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Test", status="active", visibility="npc_private",
        )

        original = {"key": "value"}
        enrich_npc_context_with_memories(
            original, db_session, session.id, major_npcs[0].id,
        )
        assert "retrieved_private_memories" not in original

    def test_enrichment_flag_off_adds_empty(self, db_session, monkeypatch):
        monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        original = {"key": "value"}
        enriched = enrich_npc_context_with_memories(
            original, db_session, session.id, major_npcs[0].id,
        )
        assert enriched["retrieved_private_memories"] == []
        assert enriched["used_memory_ids"] == []


class TestRetrievalResultStructure:
    """Verify returned structure has all required fields and no secrets."""

    def test_no_secrets_in_result(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Memory content", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(db_session, session.id, major_npcs[0].id)

        secret_fields = {"api_key", "secret", "password", "token"}
        for mem in result.memories:
            mem_dict = mem.__dict__
            for field_name in secret_fields:
                assert field_name not in mem_dict

    def test_audit_payload_structure(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Memory", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
            query="test", current_turn=5,
        )

        audit = result.retrieval_audit
        assert audit["flag_enabled"] is True
        assert audit["npc_is_major"] is True
        assert audit["query_provided"] is True
        assert audit["current_turn"] == 5
        assert "scoring_weights" in audit
        assert audit["scoring_weights"]["salience"] == 0.30
        assert audit["total_candidates"] == 1
        assert audit["selected_count"] == 1


class TestDebugEndpointAuth:
    """Debug endpoint requires admin + debug_enabled."""

    @pytest.fixture
    def _setup_client(self):
        from sqlalchemy import create_engine as _ce
        from sqlalchemy.orm import sessionmaker as _sm
        from sqlalchemy.pool import StaticPool as _SP
        from llm_rpg.storage.database import Base as _Base, get_db as _get_db
        from llm_rpg.main import app as _app

        _engine = _ce(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=_SP,
        )
        _Base.metadata.create_all(bind=_engine)

        def _override_get_db():
            _SessionLocal = _sm(bind=_engine)
            _db = _SessionLocal()
            try:
                yield _db
            finally:
                _db.close()

        _app.dependency_overrides[_get_db] = _override_get_db
        from fastapi.testclient import TestClient as _TC
        with _TC(_app) as _client:
            yield _client, _engine
        _app.dependency_overrides.clear()

    def _ensure_settings(self, engine):
        from sqlalchemy.orm import Session as _S
        _SessionLocal = sessionmaker(bind=engine)
        db = _SessionLocal()
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
                settings.debug_enabled = True
            db.commit()
        finally:
            db.close()

    def test_unauthenticated_returns_401(self, _setup_client, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        client, engine = _setup_client
        self._ensure_settings(engine)
        response = client.get("/debug/sessions/fake-session/npcs/fake-npc/memory-retrieval")
        assert response.status_code in (401, 403)

    def test_non_admin_returns_403(self, _setup_client, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        client, engine = _setup_client
        self._ensure_settings(engine)

        uname = f"nonadmin-{generate_uuid()[:6]}"
        resp = client.post("/auth/register", json={
            "username": uname,
            "email": f"{uname}@test.com",
            "password": "UserPass123!",
        })
        assert resp.status_code in (200, 201)

        login_resp = client.post("/auth/login", json={
            "username": uname,
            "password": "UserPass123!",
        })
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get(
            "/debug/sessions/fake-session/npcs/fake-npc/memory-retrieval",
            headers=headers,
        )
        assert response.status_code == 403

    def test_admin_gets_safe_response(self, _setup_client, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        client, engine = _setup_client
        self._ensure_settings(engine)

        uname = f"admintest-{generate_uuid()[:6]}"
        resp = client.post("/auth/register", json={
            "username": uname,
            "email": f"{uname}@test.com",
            "password": "AdminPass123!",
        })
        assert resp.status_code in (200, 201)

        _SessionLocal = sessionmaker(bind=engine)
        db = _SessionLocal()
        try:
            user = db.query(UserModel).filter(UserModel.username == uname).first()
            user.is_admin = True
            db.commit()
            user_id = user.id
        finally:
            db.close()

        login_resp = client.post("/auth/login", json={
            "username": uname,
            "password": "AdminPass123!",
        })
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        db = _SessionLocal()
        try:
            world = WorldModel(code=f"w-{generate_uuid()[:8]}", name="Test World")
            db.add(world)
            db.commit()
            db.refresh(world)

            location = LocationModel(world_id=world.id, code="sq", name="Square")
            db.add(location)
            db.commit()

            session = SessionModel(user_id=user_id, world_id=world.id, status="active")
            db.add(session)
            db.commit()
            db.refresh(session)

            npc = NPCTemplateModel(
                world_id=world.id, code="mnpc", name="Major NPC",
                is_major_npc=True,
            )
            db.add(npc)
            db.commit()
            db.refresh(npc)

            memory = NPCPrivateMemoryModel(
                session_id=session.id,
                npc_id=npc.id,
                npc_template_id=npc.id,
                memory_type="episodic",
                content="Admin-visible memory",
                status="active",
                visibility="npc_private",
                created_turn=1,
                last_accessed_turn=1,
            )
            db.add(memory)
            db.commit()

            session_id = session.id
            npc_id = npc.id
        finally:
            db.close()

        response = client.get(
            f"/debug/sessions/{session_id}/npcs/{npc_id}/memory-retrieval",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "memories" in data
        assert "retrieval_audit" in data
        assert "used_memory_ids" in data
        secret_fields = {"api_key", "secret", "password", "token"}
        for field_name in secret_fields:
            assert field_name not in data

    def test_nonexistent_session_returns_404(self, _setup_client, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        client, engine = _setup_client
        self._ensure_settings(engine)

        uname = f"admin404-{generate_uuid()[:6]}"
        resp = client.post("/auth/register", json={
            "username": uname,
            "email": f"{uname}@test.com",
            "password": "AdminPass123!",
        })
        assert resp.status_code in (200, 201)

        _SessionLocal = sessionmaker(bind=engine)
        db = _SessionLocal()
        try:
            user = db.query(UserModel).filter(UserModel.username == uname).first()
            user.is_admin = True
            db.commit()
        finally:
            db.close()

        login_resp = client.post("/auth/login", json={
            "username": uname,
            "password": "AdminPass123!",
        })
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get(
            "/debug/sessions/nonexistent/npcs/fake/memory-retrieval",
            headers=headers,
        )
        assert response.status_code == 404


class TestLegacyFieldFallback:
    """When new Phase 4 fields are absent, legacy fields are used."""

    def test_uses_legacy_importance_when_salience_missing(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Legacy importance memory", status="active", visibility="npc_private",
            importance=0.9, salience=None, source_turn_no=5,
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id, current_turn=6,
        )
        assert result.memories[0].signals["salience"] == 0.9

    def test_uses_content_when_memory_text_missing(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Legacy content", memory_text=None,
            status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(db_session, session.id, major_npcs[0].id)
        assert result.memories[0].text == "Legacy content"


class TestVisibilityFilter:
    """Only npc_private, npc_shared, and None visibility are accessible."""

    def test_gm_only_visibility_excluded(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Private memory", status="active", visibility="npc_private",
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="GM-only memory", status="active", visibility="gm_only",
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Shared memory", status="active", visibility="npc_shared",
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Null visibility memory", status="active", visibility=None,
        )

        result = retrieve_major_npc_memories(db_session, session.id, major_npcs[0].id)
        assert result.total_candidates == 3
        texts = [m.text for m in result.memories]
        assert "Private memory" in texts
        assert "Shared memory" in texts
        assert "Null visibility memory" in texts
        assert "GM-only memory" not in texts
