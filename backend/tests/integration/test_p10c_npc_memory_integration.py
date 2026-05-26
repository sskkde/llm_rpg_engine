"""
P10-C Phase 6: Integration tests for NPC memory-first adapter/writer
wired into the turn_service production path.

Covers:
- _build_npc_context enriches major NPC context with private memories
- _build_npc_context returns un-enriched context when flag off
- _build_npc_context returns un-enriched context for minor NPC
- _persist_turn_memories writes source-bound NPCPrivateMemory rows
  for accepted NPC reactions with new_memory_candidates
- _persist_turn_memories skips writes when flag off
- _persist_turn_memories skips writes when no new_memory_candidates
- No writes for rejected NPC reactions
- No cross-NPC memory leakage
- Non-fatal: adapter/writer failures do not block NPC decisions
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.models import (
    UserModel,
    WorldModel,
    ChapterModel,
    LocationModel,
    NPCTemplateModel,
    SessionModel,
    SessionStateModel,
    SessionNPCStateModel,
    SessionPlayerStateModel,
    NPCPrivateMemoryModel,
    NPCMemoryScopeModel,
    SystemSettingsModel,
    generate_uuid,
)
from llm_rpg.storage.repositories import (
    NPCPrivateMemoryRepository,
    NPCMemoryScopeRepository,
)
from llm_rpg.models.states import (
    CanonicalState,
    WorldState,
    PlayerState,
    CurrentSceneState,
    NPCState,
)
from llm_rpg.models.events import WorldTime


def _make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal(), engine


def _seed_world(db, is_major=False):
    uid = generate_uuid()[:8]
    user = UserModel(id=f"u-{uid}", username=f"test-{uid}", email=f"t-{uid}@t.com", password_hash="h")
    world = WorldModel(id=f"w-{uid}", code=f"w-{uid}", name="World", genre="xianxia", status="active")
    chapter = ChapterModel(id=f"ch-{uid}", world_id=world.id, chapter_no=1, name="Ch1")
    location = LocationModel(
        id=f"loc-{uid}", world_id=world.id, chapter_id=chapter.id,
        code="square", name="广场", access_rules={"always_accessible": True},
    )
    npc_template = NPCTemplateModel(
        id=f"npc-t-{uid}", world_id=world.id, code="guide",
        name="柳师姐", role_type="guide",
        public_identity="宗门向导",
        hidden_identity="暗影组织间谍",
        personality="温和友善",
        goals=["保护新弟子"],
        is_major_npc=is_major,
        seed_memory_bundle_json=[
            {"text": "I remember the ancient ritual", "importance": 0.8}
        ] if is_major else None,
        memory_profile_json={"max_memories": 10} if is_major else None,
    )
    session_model = SessionModel(
        id=f"s-{uid}", user_id=user.id, save_slot_id=None,
        world_id=world.id, current_chapter_id=chapter.id, status="active",
    )
    session_state = SessionStateModel(
        session_id=session_model.id, current_location_id=location.id,
    )
    player_state = SessionPlayerStateModel(
        session_id=session_model.id,
    )
    npc_state = SessionNPCStateModel(
        id=f"ns-{uid}", session_id=session_model.id, npc_template_id=npc_template.id,
        current_location_id=location.id, trust_score=50,
        suspicion_score=0, status_flags={"status": "alive", "mood": "neutral"},
    )
    settings = SystemSettingsModel(
        id=f"sys-{uid}",
        debug_enabled=True,
        registration_enabled=True,
        maintenance_mode=False,
    )
    db.add_all([
        user, world, chapter, location, npc_template,
        session_model, session_state, player_state, npc_state, settings,
    ])
    db.commit()

    if is_major:
        scope_repo = NPCMemoryScopeRepository(db)
        scope_repo.idempotent_create({
            "session_id": session_model.id,
            "npc_id": npc_state.id,
            "npc_template_id": npc_template.id,
            "memory_count": 0,
        })

    return {
        "user": user, "world": world, "chapter": chapter,
        "location": location, "npc_template": npc_template,
        "session": session_model, "npc_state": npc_state,
    }


def _make_canonical_state(data):
    return CanonicalState(
        world_state=WorldState(
            entity_id=data["world"].id,
            world_id=data["world"].id,
            current_time=WorldTime(calendar="修仙历", season="春", day=1, hour=12, period="辰时"),
        ),
        player_state=PlayerState(entity_id="p1", name="玩家", location_id=data["location"].id),
        current_scene_state=CurrentSceneState(
            entity_id=data["location"].id,
            scene_id=data["location"].id,
            location_id=data["location"].id,
            active_actor_ids=["p1"],
        ),
        location_states={}, npc_states={}, quest_states={}, faction_states={},
    )


# ──────────────────────────────────────────────────────────────────────────────
# _build_npc_context enrichment integration
# ──────────────────────────────────────────────────────────────────────────────


class TestBuildNPCContextEnrichment:
    def test_major_npc_context_enriched_with_private_memories(self, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        db, engine = _make_db()
        try:
            data = _seed_world(db, is_major=True)
            state = _make_canonical_state(data)

            # Seed a private memory for the major NPC
            mem_repo = NPCPrivateMemoryRepository(db)
            mem_repo.create({
                "session_id": data["session"].id,
                "npc_id": data["npc_state"].id,
                "npc_template_id": data["npc_template"].id,
                "memory_type": "episodic",
                "content": "I remember the ancient ritual",
                "created_turn": 1,
                "last_accessed_turn": 1,
                "status": "active",
                "visibility": "npc_private",
            })

            from llm_rpg.core.turn_service import _build_npc_context
            context = _build_npc_context(
                db=db,
                session_id=data["session"].id,
                npc_id=data["npc_state"].id,
                npc_template_id=data["npc_template"].id,
                canonical_state=state,
                player_input="和师姐说话",
                action_type="talk",
                current_location_id=data["location"].id,
            )

            assert "retrieved_private_memories" in context
            assert "used_memory_ids" in context
            assert len(context["used_memory_ids"]) >= 1
        finally:
            db.close()
            engine.dispose()

    def test_flag_off_context_not_enriched(self, monkeypatch):
        monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
        db, engine = _make_db()
        try:
            data = _seed_world(db, is_major=True)
            state = _make_canonical_state(data)

            from llm_rpg.core.turn_service import _build_npc_context
            context = _build_npc_context(
                db=db,
                session_id=data["session"].id,
                npc_id=data["npc_state"].id,
                npc_template_id=data["npc_template"].id,
                canonical_state=state,
                player_input="和师姐说话",
                action_type="talk",
                current_location_id=data["location"].id,
            )

            assert "retrieved_private_memories" not in context
            assert "used_memory_ids" not in context
            # Legacy fields still present
            assert context.get("public_identity") == "宗门向导"
        finally:
            db.close()
            engine.dispose()

    def test_minor_npc_context_not_enriched(self, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        db, engine = _make_db()
        try:
            data = _seed_world(db, is_major=False)
            state = _make_canonical_state(data)

            from llm_rpg.core.turn_service import _build_npc_context
            context = _build_npc_context(
                db=db,
                session_id=data["session"].id,
                npc_id=data["npc_state"].id,
                npc_template_id=data["npc_template"].id,
                canonical_state=state,
                player_input="和师姐说话",
                action_type="talk",
                current_location_id=data["location"].id,
            )

            assert "retrieved_private_memories" not in context
            assert context.get("public_identity") == "宗门向导"
        finally:
            db.close()
            engine.dispose()


# ──────────────────────────────────────────────────────────────────────────────
# _persist_turn_memories post-commit memory write integration
# ──────────────────────────────────────────────────────────────────────────────


class TestPersistTurnMemoriesIntegration:
    def test_writes_private_memories_for_accepted_reaction(self, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        db, engine = _make_db()
        try:
            data = _seed_world(db, is_major=True)
            state = _make_canonical_state(data)
            npc_template_id = data["npc_template"].id
            session_id = data["session"].id

            from llm_rpg.core.turn_service import _persist_turn_memories
            npc_reactions = [{
                "npc_id": data["npc_state"].id,
                "npc_name": "柳师姐",
                "npc_template_id": npc_template_id,
                "accepted": True,
                "action_type": "talk",
                "summary": "NPC与玩家交谈",
                "visible_to_player": True,
                "new_memory_candidates": [
                    {
                        "memory_text": "I decided to trust the player",
                        "source_type": "decision",
                        "salience": 0.8,
                    }
                ],
                "used_memory_ids": [],
            }]

            result = _persist_turn_memories(
                db=db,
                session_id=session_id,
                turn_no=5,
                event_id=f"evt-{generate_uuid()[:8]}",
                action_type="talk",
                player_input="和师姐说话",
                current_location_id=data["location"].id,
                npc_reactions=npc_reactions,
                canonical_state=state,
            )

            assert result.get("p10c_private_memories_written", 0) >= 1

            # Verify NPCPrivateMemoryModel rows were written
            mem_repo = NPCPrivateMemoryRepository(db)
            rows = mem_repo.get_by_npc_template(session_id, npc_template_id)
            written = [r for r in rows if r.knowledge_source == "decision"]
            assert len(written) >= 1
            assert written[0].memory_text == "I decided to trust the player"
            assert written[0].source_turn_no == 5
            assert written[0].status == "active"
            assert written[0].visibility == "npc_private"
        finally:
            db.close()
            engine.dispose()

    def test_no_writes_when_flag_off(self, monkeypatch):
        monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
        db, engine = _make_db()
        try:
            data = _seed_world(db, is_major=True)
            state = _make_canonical_state(data)

            from llm_rpg.core.turn_service import _persist_turn_memories
            npc_reactions = [{
                "npc_id": data["npc_state"].id,
                "npc_name": "柳师姐",
                "npc_template_id": data["npc_template"].id,
                "accepted": True,
                "action_type": "talk",
                "summary": "NPC与玩家交谈",
                "new_memory_candidates": [
                    {"memory_text": "Should not be written", "source_type": "decision"}
                ],
            }]

            result = _persist_turn_memories(
                db=db,
                session_id=data["session"].id,
                turn_no=5,
                event_id=f"evt-{generate_uuid()[:8]}",
                action_type="talk",
                player_input="和师姐说话",
                canonical_state=state,
                npc_reactions=npc_reactions,
            )

            assert result.get("p10c_private_memories_written", 0) == 0
        finally:
            db.close()
            engine.dispose()

    def test_no_writes_when_no_candidates(self, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        db, engine = _make_db()
        try:
            data = _seed_world(db, is_major=True)
            state = _make_canonical_state(data)

            from llm_rpg.core.turn_service import _persist_turn_memories
            npc_reactions = [{
                "npc_id": data["npc_state"].id,
                "npc_name": "柳师姐",
                "npc_template_id": data["npc_template"].id,
                "accepted": True,
                "action_type": "talk",
                "summary": "NPC与玩家交谈",
            }]

            result = _persist_turn_memories(
                db=db,
                session_id=data["session"].id,
                turn_no=5,
                event_id=f"evt-{generate_uuid()[:8]}",
                action_type="talk",
                player_input="和师姐说话",
                canonical_state=state,
                npc_reactions=npc_reactions,
            )

            # Should succeed without p10c writes (no candidates)
            assert "p10c_private_memories_written" not in result or result.get("p10c_private_memories_written", 0) == 0
        finally:
            db.close()
            engine.dispose()

    def test_no_writes_for_rejected_reaction(self, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        db, engine = _make_db()
        try:
            data = _seed_world(db, is_major=True)
            state = _make_canonical_state(data)

            from llm_rpg.core.turn_service import _persist_turn_memories
            npc_reactions = [{
                "npc_id": data["npc_state"].id,
                "npc_name": "柳师姐",
                "npc_template_id": data["npc_template"].id,
                "accepted": False,
                "fallback_reason": "validation_failed",
                "action_type": "idle",
                "summary": "柳师姐等待着",
                "new_memory_candidates": [
                    {"memory_text": "Should not be written", "source_type": "decision"}
                ],
            }]

            result = _persist_turn_memories(
                db=db,
                session_id=data["session"].id,
                turn_no=5,
                event_id=f"evt-{generate_uuid()[:8]}",
                action_type="talk",
                player_input="和师姐说话",
                canonical_state=state,
                npc_reactions=npc_reactions,
            )

            # Rejected reactions are not processed by the NPC reaction loop at all
            # (the loop only processes accepted reactions)
            mem_repo = NPCPrivateMemoryRepository(db)
            rows = mem_repo.get_by_npc_template(data["session"].id, data["npc_template"].id)
            decision_rows = [r for r in rows if getattr(r, "knowledge_source", None) == "decision"]
            assert len(decision_rows) == 0
        finally:
            db.close()
            engine.dispose()

    def test_no_cross_npc_memory_leak(self, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        db, engine = _make_db()
        try:
            data = _seed_world(db, is_major=True)
            state = _make_canonical_state(data)

            # Create a second NPC in the same session
            npc2 = NPCTemplateModel(
                id=f"npc-t2-{generate_uuid()[:8]}",
                world_id=data["world"].id,
                code="other",
                name="其他NPC",
                role_type="npc",
                public_identity="普通弟子",
                personality="沉默",
                is_major_npc=True,
            )
            db.add(npc2)
            db.commit()
            db.refresh(npc2)

            scope_repo = NPCMemoryScopeRepository(db)
            scope_repo.idempotent_create({
                "session_id": data["session"].id,
                "npc_id": "other-npc-state",
                "npc_template_id": npc2.id,
                "memory_count": 0,
            })

            from llm_rpg.core.turn_service import _persist_turn_memories
            npc_reactions = [{
                "npc_id": data["npc_state"].id,
                "npc_name": "柳师姐",
                "npc_template_id": data["npc_template"].id,
                "accepted": True,
                "action_type": "talk",
                "summary": "NPC与玩家交谈",
                "new_memory_candidates": [
                    {"memory_text": "My own decision", "source_type": "decision"}
                ],
            }]

            result = _persist_turn_memories(
                db=db,
                session_id=data["session"].id,
                turn_no=5,
                event_id=f"evt-{generate_uuid()[:8]}",
                action_type="talk",
                player_input="和师姐说话",
                canonical_state=state,
                npc_reactions=npc_reactions,
            )

            # Written memories belong to npc_template_id of the reacting NPC, not npc2
            mem_repo = NPCPrivateMemoryRepository(db)
            npc2_rows = mem_repo.get_by_npc_template(data["session"].id, npc2.id)
            decision_rows = [r for r in npc2_rows if getattr(r, "knowledge_source", None) == "decision"]
            assert len(decision_rows) == 0
        finally:
            db.close()
            engine.dispose()


# ──────────────────────────────────────────────────────────────────────────────
# Non-fatal: adapter/writer failures do not block
# ──────────────────────────────────────────────────────────────────────────────


class TestNonFatalIntegration:
    def test_context_enrichment_failure_does_not_block(self, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        db, engine = _make_db()
        try:
            data = _seed_world(db, is_major=True)
            state = _make_canonical_state(data)

            # Patch the enrichment to raise
            with patch(
                "llm_rpg.core.npc_decision_adapter.enrich_major_npc_decision_context",
                side_effect=RuntimeError("DB error"),
            ):
                from llm_rpg.core.turn_service import _build_npc_context
                context = _build_npc_context(
                    db=db,
                    session_id=data["session"].id,
                    npc_id=data["npc_state"].id,
                    npc_template_id=data["npc_template"].id,
                    canonical_state=state,
                    player_input="和师姐说话",
                    action_type="talk",
                    current_location_id=data["location"].id,
                )

            # Context still built (un-enriched)
            assert context is not None
            assert context.get("public_identity") == "宗门向导"
        finally:
            db.close()
            engine.dispose()

    def test_normalization_failure_does_not_block(self, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        db, engine = _make_db()
        try:
            data = _seed_world(db, is_major=True)

            from llm_rpg.core.turn_service import _execute_npc_stage
            state = _make_canonical_state(data)

            # The mock provider will return some response; normalization failure
            # should not crash the stage
            with patch(
                "llm_rpg.core.npc_decision_adapter.normalize_npc_action_proposal",
                side_effect=RuntimeError("Normalization error"),
            ):
                # This should not raise - the except catches it
                # The stage may still fail for other reasons (no LLM provider),
                # but it shouldn't crash due to normalization
                try:
                    result = _execute_npc_stage(
                        db=db,
                        session_id=data["session"].id,
                        turn_no=1,
                        canonical_state=state,
                        player_input="和师姐说话",
                        action_type="talk",
                        current_location_id=data["location"].id,
                        use_mock=True,
                    )
                    # If it succeeds (mock provider), great
                except Exception as e:
                    # If it fails, it should NOT be RuntimeError("Normalization error")
                    assert "Normalization error" not in str(e)
        finally:
            db.close()
            engine.dispose()
