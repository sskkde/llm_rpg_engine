import os
import pytest
from datetime import datetime

from llm_rpg.storage.models import (
    WorldModel,
    LocationModel,
    NPCTemplateModel,
    SessionModel,
    SessionNPCStateModel,
    NPCPrivateMemoryModel,
    NPCMemoryScopeModel,
    generate_uuid,
)
from llm_rpg.storage.repositories import (
    NPCPrivateMemoryRepository,
    NPCMemoryScopeRepository,
    NPCTemplateRepository,
    SessionRepository,
    WorldRepository,
    LocationRepository,
)
from llm_rpg.core.npc_seed_memory_service import seed_major_npc_private_memories
from llm_rpg.core.feature_flags import npc_memory_first_enabled


def _create_world_with_npcs(db_session, major_npc_count=1, minor_npc_count=1):
    world = WorldModel(code=f"w-{generate_uuid()[:8]}", name="Test World")
    db_session.add(world)
    db_session.commit()
    db_session.refresh(world)

    location = LocationModel(world_id=world.id, code="square", name="Square")
    db_session.add(location)
    db_session.commit()
    db_session.refresh(location)

    major_npcs = []
    for i in range(major_npc_count):
        npc = NPCTemplateModel(
            world_id=world.id,
            code=f"major-npc-{i}",
            name=f"Major NPC {i}",
            is_major_npc=True,
            seed_memory_bundle_json=[
                {
                    "text": f"I remember the ancient pact {i}",
                    "memory_type": "episodic",
                    "importance": 0.8,
                    "salience": 0.9,
                    "tags": ["pact", "history"],
                    "entities": ["ancient_order"],
                    "confidence": 1.0,
                    "knowledge_source": "admin_seed",
                    "visibility": "npc_private",
                },
                {
                    "text": f"The old master taught me the forbidden technique {i}",
                    "memory_type": "semantic",
                    "importance": 0.9,
                    "short_summary": "Forbidden technique knowledge",
                },
            ],
            memory_profile_json={"retrieval_budget": 5},
        )
        db_session.add(npc)
        db_session.commit()
        db_session.refresh(npc)
        major_npcs.append(npc)

    minor_npcs = []
    for i in range(minor_npc_count):
        npc = NPCTemplateModel(
            world_id=world.id,
            code=f"minor-npc-{i}",
            name=f"Minor NPC {i}",
            is_major_npc=False,
        )
        db_session.add(npc)
        db_session.commit()
        db_session.refresh(npc)
        minor_npcs.append(npc)

    return world, location, major_npcs, minor_npcs


class TestNPCPrivateMemoryModelFirstPersonFields:
    def test_first_person_fields_default_none(self, db_session):
        mem = NPCPrivateMemoryModel(
            session_id="sess-001",
            npc_id="npc-001",
            memory_type="episodic",
            content="I saw something",
            created_turn=1,
            last_accessed_turn=1,
        )
        db_session.add(mem)
        db_session.commit()
        db_session.refresh(mem)

        assert mem.memory_kind is None
        assert mem.memory_text is None
        assert mem.short_summary is None
        assert mem.knowledge_source is None
        assert mem.source_id is None
        assert mem.source_ref is None
        assert mem.source_turn_no is None
        assert mem.salience is None
        assert mem.visibility is None
        assert mem.status == "active"
        assert mem.tags_json is None
        assert mem.entity_refs_json is None
        assert mem.location_id is None
        assert mem.world_time_text is None
        assert mem.world_time_json is None
        assert mem.npc_template_id is None
        assert mem.checksum is None
        assert mem.superseded_by is None
        assert mem.contradicts_memory_ids_json is None
        assert mem.recall_policy_json is None

    def test_first_person_fields_set_and_persist(self, db_session):
        mem = NPCPrivateMemoryModel(
            session_id="sess-002",
            npc_id="npc-002",
            npc_template_id="npt-002",
            memory_type="episodic",
            content="I witnessed the ritual",
            memory_kind="seed",
            memory_text="I witnessed the ritual at the temple",
            short_summary="Witnessed ritual",
            knowledge_source="admin_seed",
            source_id="evt_seed_npc_shaman",
            source_ref="evt_seed_npc_shaman",
            source_turn_no=0,
            salience=0.9,
            visibility="npc_private",
            status="active",
            tags_json=["ritual", "temple"],
            entity_refs_json=["temple", "shaman"],
            created_turn=0,
            last_accessed_turn=0,
        )
        db_session.add(mem)
        db_session.commit()
        db_session.refresh(mem)

        assert mem.memory_kind == "seed"
        assert mem.memory_text == "I witnessed the ritual at the temple"
        assert mem.short_summary == "Witnessed ritual"
        assert mem.knowledge_source == "admin_seed"
        assert mem.source_id == "evt_seed_npc_shaman"
        assert mem.source_turn_no == 0
        assert mem.salience == 0.9
        assert mem.visibility == "npc_private"
        assert mem.status == "active"
        assert mem.tags_json == ["ritual", "temple"]
        assert mem.entity_refs_json == ["temple", "shaman"]
        assert mem.npc_template_id == "npt-002"

    def test_legacy_fields_still_work(self, db_session):
        mem = NPCPrivateMemoryModel(
            session_id="sess-003",
            npc_id="npc-003",
            memory_type="episodic",
            content="Old style memory",
            source_event_ids_json=["evt-001"],
            entities_json=["entity-001"],
            importance=0.5,
            emotional_weight=0.2,
            confidence=0.8,
            current_strength=1.0,
            created_turn=3,
            last_accessed_turn=5,
            recall_count=2,
        )
        db_session.add(mem)
        db_session.commit()
        db_session.refresh(mem)

        assert mem.content == "Old style memory"
        assert mem.importance == 0.5
        assert mem.emotional_weight == 0.2
        assert mem.confidence == 0.8
        assert mem.current_strength == 1.0
        assert mem.recall_count == 2


class TestNPCMemoryScopeModelRetrievalFields:
    def test_retrieval_fields_default_none(self, db_session):
        scope = NPCMemoryScopeModel(
            session_id="sess-001",
            npc_id="npc-001",
        )
        db_session.add(scope)
        db_session.commit()
        db_session.refresh(scope)

        assert scope.npc_template_id is None
        assert scope.latest_summary_id is None
        assert scope.active_digest_text is None
        assert scope.memory_count is None or scope.memory_count == 0
        assert scope.last_compacted_turn is None or scope.last_compacted_turn == 0
        assert scope.retrieval_profile_json is None
        assert scope.prompt_budget_json is None

    def test_retrieval_fields_set_and_persist(self, db_session):
        scope = NPCMemoryScopeModel(
            session_id="sess-002",
            npc_id="npc-002",
            npc_template_id="npt-002",
            latest_summary_id="sum-001",
            active_digest_text="The shaman knows ancient rituals",
            memory_count=5,
            last_compacted_turn=3,
            retrieval_profile_json={"strategy": "recent_first"},
            prompt_budget_json={"max_memories": 10},
        )
        db_session.add(scope)
        db_session.commit()
        db_session.refresh(scope)

        assert scope.npc_template_id == "npt-002"
        assert scope.latest_summary_id == "sum-001"
        assert scope.active_digest_text == "The shaman knows ancient rituals"
        assert scope.memory_count == 5
        assert scope.last_compacted_turn == 3
        assert scope.retrieval_profile_json == {"strategy": "recent_first"}
        assert scope.prompt_budget_json == {"max_memories": 10}


class TestNPCPrivateMemoryRepositoryMethods:
    def test_get_active_memories(self, db_session):
        repo = NPCPrivateMemoryRepository(db_session)
        repo.create({
            "session_id": "sess-active",
            "npc_id": "npc-active",
            "memory_type": "episodic",
            "content": "Active memory",
            "created_turn": 1,
            "last_accessed_turn": 1,
            "status": "active",
        })
        repo.create({
            "session_id": "sess-active",
            "npc_id": "npc-active",
            "memory_type": "episodic",
            "content": "Superseded memory",
            "created_turn": 2,
            "last_accessed_turn": 2,
            "status": "superseded",
        })
        repo.create({
            "session_id": "sess-active",
            "npc_id": "npc-active",
            "memory_type": "episodic",
            "content": "Null status memory",
            "created_turn": 3,
            "last_accessed_turn": 3,
        })

        active = repo.get_active_memories("sess-active", "npc-active")
        assert len(active) == 2
        contents = {m.content for m in active}
        assert "Active memory" in contents
        assert "Null status memory" in contents
        assert "Superseded memory" not in contents

    def test_has_seed_memories(self, db_session):
        repo = NPCPrivateMemoryRepository(db_session)
        assert repo.has_seed_memories("sess-seed", "npc-seed") is False

        repo.create({
            "session_id": "sess-seed",
            "npc_id": "npc-seed",
            "memory_type": "episodic",
            "content": "Not a seed",
            "created_turn": 1,
            "last_accessed_turn": 1,
        })
        assert repo.has_seed_memories("sess-seed", "npc-seed") is False

        repo.create({
            "session_id": "sess-seed",
            "npc_id": "npc-seed",
            "memory_type": "episodic",
            "content": "Seed memory",
            "created_turn": 0,
            "last_accessed_turn": 0,
            "memory_kind": "seed",
        })
        assert repo.has_seed_memories("sess-seed", "npc-seed") is True

    def test_get_by_npc_template(self, db_session):
        repo = NPCPrivateMemoryRepository(db_session)
        repo.create({
            "session_id": "sess-npt",
            "npc_id": "npc-npt",
            "npc_template_id": "npt-001",
            "memory_type": "episodic",
            "content": "Memory for template",
            "created_turn": 1,
            "last_accessed_turn": 1,
        })
        repo.create({
            "session_id": "sess-npt",
            "npc_id": "npc-other",
            "npc_template_id": "npt-002",
            "memory_type": "episodic",
            "content": "Other template",
            "created_turn": 1,
            "last_accessed_turn": 1,
        })

        results = repo.get_by_npc_template("sess-npt", "npt-001")
        assert len(results) == 1
        assert results[0].npc_template_id == "npt-001"


class TestNPCMemoryScopeRepositoryMethods:
    def test_get_by_session_and_npc_template(self, db_session):
        repo = NPCMemoryScopeRepository(db_session)
        repo.create({
            "session_id": "sess-sct",
            "npc_id": "npc-sct",
            "npc_template_id": "npt-sct",
        })

        result = repo.get_by_session_and_npc_template("sess-sct", "npt-sct")
        assert result is not None
        assert result.npc_template_id == "npt-sct"

        missing = repo.get_by_session_and_npc_template("sess-sct", "npt-missing")
        assert missing is None

    def test_idempotent_create(self, db_session):
        repo = NPCMemoryScopeRepository(db_session)
        first = repo.idempotent_create({
            "session_id": "sess-idem",
            "npc_id": "npc-idem",
            "npc_template_id": "npt-idem",
            "profile_json": {"budget": 5},
        })
        assert first is not None

        second = repo.idempotent_create({
            "session_id": "sess-idem",
            "npc_id": "npc-idem",
            "npc_template_id": "npt-idem",
            "profile_json": {"budget": 10},
        })
        assert second.id == first.id
        # idempotent_create does NOT update existing
        assert second.profile_json == {"budget": 5}


class TestSeedMajorNPCPrivateMemories:
    def test_flag_off_no_seeding(self, db_session, monkeypatch):
        monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
        world, location, major_npcs, _ = _create_world_with_npcs(db_session)

        count = seed_major_npc_private_memories(
            db_session, "sess-no-flag", world.id
        )
        assert count == 0

    def test_flag_on_major_npc_gets_seed_memories(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, location, major_npcs, _ = _create_world_with_npcs(db_session)

        session = SessionModel(user_id="user-001", world_id=world.id, status="active")
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        count = seed_major_npc_private_memories(
            db_session, session.id, world.id
        )
        assert count == 2  # 2 seed memories in the bundle

        memory_repo = NPCPrivateMemoryRepository(db_session)
        memories = memory_repo.get_by_npc(session.id, major_npcs[0].id)
        assert len(memories) == 2

        seed_mem = memories[0]
        assert seed_mem.memory_kind == "seed"
        assert seed_mem.knowledge_source == "admin_seed"
        assert seed_mem.source_turn_no == 0
        assert seed_mem.source_ref.startswith("evt_seed_npc_")
        assert seed_mem.status == "active"
        assert seed_mem.visibility == "npc_private"
        assert seed_mem.npc_template_id == major_npcs[0].id
        # Legacy fields populated too
        assert seed_mem.content == "I remember the ancient pact 0"
        assert seed_mem.memory_type == "episodic"
        assert seed_mem.importance == 0.8

    def test_flag_on_minor_npc_no_seed_memories(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, location, major_npcs, minor_npcs = _create_world_with_npcs(db_session)

        session = SessionModel(user_id="user-002", world_id=world.id, status="active")
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        count = seed_major_npc_private_memories(
            db_session, session.id, world.id
        )
        # Only 1 major NPC with 2 seed entries
        assert count == 2

        memory_repo = NPCPrivateMemoryRepository(db_session)
        minor_memories = memory_repo.get_by_npc(session.id, minor_npcs[0].id)
        assert len(minor_memories) == 0

    def test_idempotent_seeding(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, location, major_npcs, _ = _create_world_with_npcs(db_session)

        session = SessionModel(user_id="user-003", world_id=world.id, status="active")
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        count1 = seed_major_npc_private_memories(
            db_session, session.id, world.id
        )
        assert count1 == 2

        count2 = seed_major_npc_private_memories(
            db_session, session.id, world.id
        )
        assert count2 == 0

        memory_repo = NPCPrivateMemoryRepository(db_session)
        memories = memory_repo.get_by_npc(session.id, major_npcs[0].id)
        assert len(memories) == 2  # Not doubled

    def test_scope_created_for_major_npc(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, location, major_npcs, _ = _create_world_with_npcs(db_session)

        session = SessionModel(user_id="user-004", world_id=world.id, status="active")
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        seed_major_npc_private_memories(db_session, session.id, world.id)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope = scope_repo.get_by_session_and_npc(session.id, major_npcs[0].id)
        assert scope is not None
        assert scope.npc_template_id == major_npcs[0].id
        assert scope.memory_count == 2
        assert scope.profile_json == {"retrieval_budget": 5}

    def test_scope_created_even_without_seed_bundle(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, location, major_npcs, _ = _create_world_with_npcs(db_session)

        # Create a major NPC without seed_memory_bundle_json
        major_no_bundle = NPCTemplateModel(
            world_id=world.id,
            code="major-no-bundle",
            name="Major No Bundle",
            is_major_npc=True,
            seed_memory_bundle_json=None,
        )
        db_session.add(major_no_bundle)
        db_session.commit()
        db_session.refresh(major_no_bundle)

        session = SessionModel(user_id="user-005", world_id=world.id, status="active")
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        count = seed_major_npc_private_memories(db_session, session.id, world.id)
        # Only the first major NPC has bundle (2 entries); second has none
        assert count == 2

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope = scope_repo.get_by_session_and_npc(session.id, major_no_bundle.id)
        assert scope is not None
        assert scope.memory_count == 0

    def test_multiple_major_npcs(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, location, major_npcs, _ = _create_world_with_npcs(
            db_session, major_npc_count=2, minor_npc_count=1
        )

        session = SessionModel(user_id="user-006", world_id=world.id, status="active")
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        count = seed_major_npc_private_memories(db_session, session.id, world.id)
        assert count == 4  # 2 major NPCs x 2 seed entries each


class TestInitializeSessionStoryStateWithSeedMemories:
    def test_initialize_creates_seed_memories_when_enabled(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, location, major_npcs, minor_npcs = _create_world_with_npcs(db_session)

        session_repo = SessionRepository(db_session)
        session = session_repo.create({
            "user_id": "user-seed-init",
            "world_id": world.id,
            "status": "active",
        })

        from llm_rpg.core.session_initialization import initialize_session_story_state
        initialize_session_story_state(db_session, session.id)

        memory_repo = NPCPrivateMemoryRepository(db_session)
        memories = memory_repo.get_by_npc(session.id, major_npcs[0].id)
        assert len(memories) == 2
        assert memories[0].memory_kind == "seed"

        # Minor NPC should NOT have seed memories
        minor_memories = memory_repo.get_by_npc(session.id, minor_npcs[0].id)
        assert len(minor_memories) == 0

    def test_initialize_no_seed_memories_when_disabled(self, db_session, monkeypatch):
        monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
        world, location, major_npcs, _ = _create_world_with_npcs(db_session)

        session_repo = SessionRepository(db_session)
        session = session_repo.create({
            "user_id": "user-seed-noflag",
            "world_id": world.id,
            "status": "active",
        })

        from llm_rpg.core.session_initialization import initialize_session_story_state
        initialize_session_story_state(db_session, session.id)

        memory_repo = NPCPrivateMemoryRepository(db_session)
        memories = memory_repo.get_by_npc(session.id, major_npcs[0].id)
        assert len(memories) == 0

    def test_initialize_idempotent_seed_memories(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, location, major_npcs, _ = _create_world_with_npcs(db_session)

        session_repo = SessionRepository(db_session)
        session = session_repo.create({
            "user_id": "user-seed-idem",
            "world_id": world.id,
            "status": "active",
        })

        from llm_rpg.core.session_initialization import initialize_session_story_state
        initialize_session_story_state(db_session, session.id)
        initialize_session_story_state(db_session, session.id)

        memory_repo = NPCPrivateMemoryRepository(db_session)
        memories = memory_repo.get_by_npc(session.id, major_npcs[0].id)
        assert len(memories) == 2  # Not doubled
