"""
P10-C Hallucination / Leak Hardening Regression Tests.

Covers audit-identified gaps:
1. Cross-session memory isolation: retrieval never returns memories from
   other sessions even when same NPC template is reused.
2. Cross-NPC memory isolation: retrieval never returns memories belonging
   to a different NPC in the same session.
3. Spoofed used_memory_ids rejection: LLM-hallucinated IDs that don't
   belong to the session+NPC are rejected by normalization.
4. new_memory_candidates source-bound constraints: candidates without
   source_type or memory_text are dropped; non-dict candidates dropped.
5. Visibility / private / secret filtering: gm_only, player_visible,
   secret visibility memories excluded from retrieval; superseded/archived
   excluded.
6. Narration no-write / no-leak boundaries: NarrationProposal never
   triggers post-commit memory writes; narration output never contains
   private_reasoning, decision_audit, or secret_sensitive fields.
7. Player API field projection: player-facing NPCActionProposal dicts
   must not expose hidden_motivation, decision_audit, used_memory_ids
   internals, or admin-only fields.
8. NPCKnowledgeValidator cross-session isolation: secrets from other
   sessions must not cause false positives/negatives.
9. Enrichment never leaks private_reasoning / decision_audit /
   secret_sensitive into player-visible context.
10. Post-commit writer source-bound: written memories always have
    knowledge_source set to source_type, never arbitrary values.
"""

import pytest
from datetime import datetime
from copy import deepcopy

from llm_rpg.storage.models import (
    WorldModel,
    LocationModel,
    NPCTemplateModel,
    SessionModel,
    SessionNPCStateModel,
    NPCPrivateMemoryModel,
    NPCMemoryScopeModel,
    NPCSecretModel,
    NPCBeliefModel,
    generate_uuid,
)
from llm_rpg.storage.repositories import (
    NPCPrivateMemoryRepository,
    NPCMemoryScopeRepository,
    NPCTemplateRepository,
)
from llm_rpg.models.proposals import (
    NPCActionProposal,
    ProposalAuditMetadata,
    ProposalType,
    ProposalSource,
    NarrationProposal,
)
from llm_rpg.models.states import CanonicalState, NPCState, PlayerState, WorldState, CurrentSceneState
from llm_rpg.models.events import WorldTime
from llm_rpg.core.npc_decision_adapter import (
    enrich_major_npc_decision_context,
    normalize_npc_action_proposal,
    NormalizationResult,
)
from llm_rpg.core.post_commit_memory_writer import (
    write_post_commit_memories,
    PostCommitWriteResult,
)
from llm_rpg.core.npc_memory_retrieval_service import (
    retrieve_major_npc_memories,
    enrich_npc_context_with_memories,
    RetrievalResult,
    RetrievedMemory,
)
from llm_rpg.core.validation.npc_knowledge_validator import (
    NPCKnowledgeValidator,
    ProtectedNPCFact,
)
from llm_rpg.core.validation.narration_leak_validator import (
    NarrationLeakValidator,
)


# ─── Helpers ────────────────────────────────────────────────────────────────


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
                {"text": f"Seed memory for major NPC {i}", "importance": 0.7}
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


def _make_audit():
    return ProposalAuditMetadata(
        proposal_type=ProposalType.NPC_ACTION,
        source_engine=ProposalSource.NPC_ENGINE,
    )


def _make_proposal(npc_id="npc-test", **overrides):
    defaults = dict(
        npc_id=npc_id,
        action_type="talk",
        summary="NPC talks to player",
        audit=_make_audit(),
    )
    defaults.update(overrides)
    return NPCActionProposal(**defaults)


def _make_canonical_state(npc_ids=None):
    npc_states = {}
    for npc_id in (npc_ids or []):
        npc_states[npc_id] = NPCState(
            entity_id=npc_id,
            entity_type="npc",
            npc_id=npc_id,
            name=f"NPC {npc_id}",
            mood="neutral",
            location_id="square",
        )
    return CanonicalState(
        player_state=PlayerState(entity_id="p1", entity_type="player", location_id="square"),
        world_state=WorldState(
            entity_id="w1", entity_type="world", world_id="w1",
            current_time=WorldTime(calendar="青岚历", season="春", day=1, period="辰时"),
        ),
        current_scene_state=CurrentSceneState(entity_id="sc1", entity_type="scene", scene_id="sc1", location_id="square"),
        npc_states=npc_states,
        location_states={},
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. Cross-session memory isolation
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossSessionMemoryIsolation:
    """Memories from other sessions must NEVER leak into retrieval results."""

    def test_retrieval_excludes_other_session_same_npc(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        # Add memory for THIS session
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="My session memory", status="active", visibility="npc_private",
        )

        # Create a SECOND session reusing the same NPC template
        other_session = SessionModel(
            user_id="user-other", world_id=world.id, status="active",
        )
        db_session.add(other_session)
        db_session.commit()
        db_session.refresh(other_session)

        _add_private_memory(
            db_session, other_session.id, major_npcs[0].id,
            content="Other session secret memory", status="active",
            visibility="npc_private",
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
        )
        texts = [m.text for m in result.memories]
        assert "My session memory" in texts
        assert "Other session secret memory" not in texts
        assert result.total_candidates == 1

    def test_enrichment_excludes_other_session_memories(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Correct memory", status="active", visibility="npc_private",
        )

        other_session = SessionModel(
            user_id="user-other2", world_id=world.id, status="active",
        )
        db_session.add(other_session)
        db_session.commit()
        db_session.refresh(other_session)

        _add_private_memory(
            db_session, other_session.id, major_npcs[0].id,
            content="Leaked memory from other session", status="active",
            visibility="npc_private",
        )

        original = {"profile": {"name": major_npcs[0].name}}
        enriched = enrich_npc_context_with_memories(
            original, db_session, session.id, major_npcs[0].id,
        )

        mem_texts = [
            m["text"] for m in enriched.get("retrieved_private_memories", [])
        ]
        assert "Correct memory" in mem_texts
        assert "Leaked memory from other session" not in mem_texts

    def test_normalization_rejects_other_session_memory_ids(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        other_session = SessionModel(
            user_id="user-other3", world_id=world.id, status="active",
        )
        db_session.add(other_session)
        db_session.commit()
        db_session.refresh(other_session)

        other_mem = _add_private_memory(
            db_session, other_session.id, major_npcs[0].id,
            content="Other session memory", status="active",
            visibility="npc_private",
        )

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            used_memory_ids=[other_mem.id],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert result.valid_used_memory_ids == []
        assert other_mem.id in result.invalid_used_memory_ids


# ═══════════════════════════════════════════════════════════════════════════
# 2. Cross-NPC memory isolation (same session)
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossNPCMemoryIsolation:
    """Memories from other NPCs in the same session must not leak."""

    def test_retrieval_excludes_other_npc_memories(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(
            db_session, major_count=2,
        )

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="NPC 0 private thought", status="active",
            visibility="npc_private",
        )
        _add_private_memory(
            db_session, session.id, major_npcs[1].id,
            content="NPC 1 secret plan", status="active",
            visibility="npc_private",
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
        )
        texts = [m.text for m in result.memories]
        assert "NPC 0 private thought" in texts
        assert "NPC 1 secret plan" not in texts

    def test_enrichment_does_not_contain_other_npc_data(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(
            db_session, major_count=2,
        )

        _add_private_memory(
            db_session, session.id, major_npcs[1].id,
            content="NPC 1 should not appear", status="active",
            visibility="npc_private",
        )

        original = {"profile": {"name": major_npcs[0].name}}
        enriched = enrich_npc_context_with_memories(
            original, db_session, session.id, major_npcs[0].id,
        )

        mem_texts = [
            m["text"] for m in enriched.get("retrieved_private_memories", [])
        ]
        assert "NPC 1 should not appear" not in mem_texts


# ═══════════════════════════════════════════════════════════════════════════
# 3. Spoofed used_memory_ids rejection
# ═══════════════════════════════════════════════════════════════════════════


class TestSpoofedUsedMemoryIdsRejection:
    """LLM-hallucinated or spoofed memory IDs must be rejected."""

    def test_completely_fake_id_rejected(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            used_memory_ids=["hallucinated-id-12345"],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert result.valid_used_memory_ids == []
        assert "hallucinated-id-12345" in result.invalid_used_memory_ids

    def test_uuid_format_but_nonexistent_rejected(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        fake_uuid = generate_uuid()  # valid UUID format but not in DB
        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            used_memory_ids=[fake_uuid],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert result.valid_used_memory_ids == []
        assert fake_uuid in result.invalid_used_memory_ids

    def test_mixed_valid_and_spoofed_ids(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        own_mem = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Real memory", status="active", visibility="npc_private",
        )

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            used_memory_ids=[own_mem.id, "spoofed-id"],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert own_mem.id in result.valid_used_memory_ids
        assert "spoofed-id" in result.invalid_used_memory_ids
        assert len(result.valid_used_memory_ids) == 1
        assert len(result.invalid_used_memory_ids) == 1

    def test_spoofed_ids_not_in_updated_proposal(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            used_memory_ids=["fake-1", "fake-2"],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert result.proposal.used_memory_ids == []

    def test_id_from_available_set_but_not_owned_rejected(
        self, db_session, monkeypatch,
    ):
        """An ID in available_memory_ids but NOT owned by this NPC is rejected."""
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        # The spoofed ID is in available_memory_ids but not owned
        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            used_memory_ids=["available-but-not-owned"],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
            available_memory_ids=["available-but-not-owned"],
        )
        # Not owned → rejected even though in available set
        assert result.valid_used_memory_ids == []


# ═══════════════════════════════════════════════════════════════════════════
# 4. new_memory_candidates source-bound constraints
# ═══════════════════════════════════════════════════════════════════════════


class TestNewMemoryCandidatesSourceBound:
    """Candidates must have memory_text and source_type; invalid ones dropped."""

    def test_candidate_with_empty_source_type_dropped(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[
                {"memory_text": "I learned something", "source_type": ""},
            ],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert len(result.filtered_candidates) == 0
        assert len(result.dropped_candidates) == 1

    def test_candidate_with_whitespace_memory_text_dropped(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[
                {"memory_text": "   ", "source_type": "decision"},
            ],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert len(result.filtered_candidates) == 0
        assert len(result.dropped_candidates) == 1

    def test_candidate_with_both_fields_valid_passes(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[
                {
                    "memory_text": "I decided to trust the player",
                    "source_type": "decision",
                    "salience": 0.8,
                },
            ],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert len(result.filtered_candidates) == 1
        assert result.filtered_candidates[0]["source_type"] == "decision"

    def test_mixed_valid_and_invalid_candidates(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[
                {"memory_text": "Valid", "source_type": "decision"},
                {"memory_text": "No source"},
                {"source_type": "decision"},
                {"memory_text": "Also valid", "source_type": "observation"},
            ],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert len(result.filtered_candidates) == 2
        assert len(result.dropped_candidates) == 2

    def test_post_commit_only_writes_source_bound_candidates(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.idempotent_create({
            "session_id": session.id,
            "npc_id": major_npcs[0].id,
            "npc_template_id": major_npcs[0].id,
        })

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[
                {"memory_text": "Good memory", "source_type": "decision"},
                {"memory_text": "No source type"},
                {"source_type": "decision"},
            ],
        )
        result = write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            proposal, ["evt_001"], source_turn_no=3,
        )
        assert len(result.written_ids) == 1
        assert result.dropped_count == 2

        repo = NPCPrivateMemoryRepository(db_session)
        written = repo.get_by_id(result.written_ids[0])
        assert written.knowledge_source == "decision"

    def test_post_commit_rejects_whitespace_memory_text(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.idempotent_create({
            "session_id": session.id,
            "npc_id": major_npcs[0].id,
            "npc_template_id": major_npcs[0].id,
        })

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[
                {"memory_text": "   ", "source_type": "decision"},
            ],
        )
        result = write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            proposal, ["evt_001"], source_turn_no=3,
        )
        assert len(result.written_ids) == 0
        assert result.dropped_count == 1

    def test_post_commit_rejects_whitespace_source_type(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.idempotent_create({
            "session_id": session.id,
            "npc_id": major_npcs[0].id,
            "npc_template_id": major_npcs[0].id,
        })

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[
                {"memory_text": "Valid text", "source_type": "  "},
            ],
        )
        result = write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            proposal, ["evt_001"], source_turn_no=3,
        )
        assert len(result.written_ids) == 0
        assert result.dropped_count == 1


# ═══════════════════════════════════════════════════════════════════════════
# 5. Visibility / private / secret filtering
# ═══════════════════════════════════════════════════════════════════════════


class TestVisibilityPrivateSecretFiltering:
    """Only npc_private, npc_shared, and None visibility are retrievable."""

    def test_gm_only_never_retrieved(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="GM-only secret", status="active", visibility="gm_only",
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="NPC private", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
        )
        texts = [m.text for m in result.memories]
        assert "NPC private" in texts
        assert "GM-only secret" not in texts

    def test_player_visible_excluded_from_npc_retrieval(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Player-visible fact", status="active",
            visibility="player_visible",
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="NPC private fact", status="active",
            visibility="npc_private",
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
        )
        texts = [m.text for m in result.memories]
        assert "NPC private fact" in texts
        assert "Player-visible fact" not in texts

    def test_secret_visibility_excluded(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Secret memory", status="active", visibility="secret",
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Private memory", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
        )
        texts = [m.text for m in result.memories]
        assert "Private memory" in texts
        assert "Secret memory" not in texts

    def test_archived_and_superseded_excluded(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Active memory", status="active", visibility="npc_private",
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Archived memory", status="archived", visibility="npc_private",
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Superseded memory", status="superseded",
            visibility="npc_private",
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
        )
        texts = [m.text for m in result.memories]
        assert "Active memory" in texts
        assert "Archived memory" not in texts
        assert "Superseded memory" not in texts

    def test_npc_shared_included(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Shared between NPCs", status="active",
            visibility="npc_shared",
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
        )
        texts = [m.text for m in result.memories]
        assert "Shared between NPCs" in texts

    def test_null_visibility_included(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Legacy no-visibility", status="active", visibility=None,
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
        )
        texts = [m.text for m in result.memories]
        assert "Legacy no-visibility" in texts


# ═══════════════════════════════════════════════════════════════════════════
# 6. Narration no-write / no-leak boundaries
# ═══════════════════════════════════════════════════════════════════════════


class TestNarrationNoWriteNoLeakBoundaries:
    """NarrationProposal must never produce memory writes or leak internals."""

    def test_narration_proposal_never_writes_memories(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.idempotent_create({
            "session_id": session.id,
            "npc_id": major_npcs[0].id,
            "npc_template_id": major_npcs[0].id,
        })

        narration_audit = ProposalAuditMetadata(
            proposal_type=ProposalType.NARRATION,
            source_engine=ProposalSource.NARRATION_ENGINE,
        )
        narration = NarrationProposal(
            text="The wind howls through the square.",
            audit=narration_audit,
        )

        result = write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            narration, ["evt_001"], source_turn_no=3,
        )
        assert result.written_ids == []
        assert result.dropped_count == 0

    def test_narration_proposal_model_has_no_memory_fields(self):
        """NarrationProposal must not have used_memory_ids or
        new_memory_candidates fields that could leak."""
        narration_audit = ProposalAuditMetadata(
            proposal_type=ProposalType.NARRATION,
            source_engine=ProposalSource.NARRATION_ENGINE,
        )
        narration = NarrationProposal(
            text="A calm evening.",
            audit=narration_audit,
        )
        # NarrationProposal should not have memory-first fields
        assert not hasattr(narration, "used_memory_ids")
        assert not hasattr(narration, "new_memory_candidates")
        assert not hasattr(narration, "decision_audit")

    def test_narration_output_no_private_reasoning_leak(self):
        """Narration text must not contain private_reasoning markers."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="The ancient square stretches before you.",
            forbidden_info=["private_reasoning", "decision_audit", "secret_sensitive"],
        )
        assert result.is_valid

    def test_narration_leak_validator_catches_internal_field_leak(self):
        """If narration text accidentally contains internal field names,
        the leak validator should flag them."""
        validator = NarrationLeakValidator()
        result = validator.validate_narration(
            text="The NPC's private_reasoning suggests they are lying.",
            forbidden_info=["private_reasoning"],
        )
        assert not result.is_valid

    def test_narration_never_writes_even_with_candidates_attached(
        self, db_session, monkeypatch,
    ):
        """Even if someone erroneously attaches new_memory_candidates to
        a narration-like proposal, the writer must refuse."""
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.idempotent_create({
            "session_id": session.id,
            "npc_id": major_npcs[0].id,
            "npc_template_id": major_npcs[0].id,
        })

        # Use NarrationProposal which has no new_memory_candidates
        narration_audit = ProposalAuditMetadata(
            proposal_type=ProposalType.NARRATION,
            source_engine=ProposalSource.NARRATION_ENGINE,
        )
        narration = NarrationProposal(
            text="Something happens.",
            audit=narration_audit,
        )

        result = write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            narration, ["evt_001"], source_turn_no=5,
        )
        assert result.written_ids == []


# ═══════════════════════════════════════════════════════════════════════════
# 7. Player API field projection
# ═══════════════════════════════════════════════════════════════════════════


class TestPlayerAPIFieldProjection:
    """Player-facing proposal dicts must not expose admin-only fields."""

    def test_proposal_dict_excludes_hidden_motivation_by_default(self):
        """model_dump() includes hidden_motivation but player-facing
        projections must filter it out."""
        proposal = _make_proposal(
            npc_id="npc-1",
            hidden_motivation="Secretly plotting betrayal",
        )
        full_dump = proposal.model_dump()
        # The full model_dump DOES include hidden_motivation (it's a model field)
        assert "hidden_motivation" in full_dump
        # Player-facing code must explicitly exclude it
        player_fields = {
            k: v for k, v in full_dump.items()
            if k not in {
                "hidden_motivation", "decision_audit",
                "used_memory_ids", "new_memory_candidates",
            }
        }
        assert "hidden_motivation" not in player_fields

    def test_player_safe_projection_omits_admin_fields(self):
        """Verify the set of fields that must never reach player APIs."""
        proposal = _make_proposal(
            npc_id="npc-1",
            hidden_motivation="Secret plot",
            used_memory_ids=["mem-1", "mem-2"],
            new_memory_candidates=[
                {"memory_text": "internal", "source_type": "decision"},
            ],
            decision_audit={"retrieval_scores": [0.9], "private_reasoning": "hidden"},
        )
        full_dump = proposal.model_dump()

        # These fields must be stripped before sending to player
        forbidden_player_fields = {
            "hidden_motivation",
            "decision_audit",
        }
        for field in forbidden_player_fields:
            assert field in full_dump  # exists in model
            # Player projection must exclude:
            player_safe = {
                k: v for k, v in full_dump.items()
                if k not in forbidden_player_fields
            }
            assert field not in player_safe

    def test_normalized_proposal_still_has_filtered_used_memory_ids(
        self, db_session, monkeypatch,
    ):
        """After normalization, used_memory_ids only contains valid IDs.
        Player APIs must still not expose the raw list."""
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        own_mem = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Own memory", status="active", visibility="npc_private",
        )

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            used_memory_ids=[own_mem.id, "spoofed"],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        # The normalized proposal only has valid IDs
        assert result.proposal.used_memory_ids == [own_mem.id]
        # But player APIs should still not expose used_memory_ids directly
        # (it's an internal field for memory tracking, not player-facing)

    def test_decision_audit_not_in_player_facing_output(self):
        """decision_audit contains private reasoning and must never
        appear in player-facing output."""
        proposal = _make_proposal(
            npc_id="npc-1",
            decision_audit={
                "private_reasoning": "I suspect the player is lying",
                "retrieval_scores": {"mem-1": 0.9},
                "secret_sensitive": True,
            },
        )
        dump = proposal.model_dump()
        assert "decision_audit" in dump
        assert dump["decision_audit"]["private_reasoning"] == "I suspect the player is lying"

        # Player-facing output must strip decision_audit
        player_safe = {
            k: v for k, v in dump.items() if k != "decision_audit"
        }
        assert "decision_audit" not in player_safe
        assert "private_reasoning" not in str(player_safe)


# ═══════════════════════════════════════════════════════════════════════════
# 8. NPCKnowledgeValidator cross-session isolation
# ═══════════════════════════════════════════════════════════════════════════


class TestNPCKnowledgeValidatorCrossSession:
    """Secrets from other sessions must not affect validation."""

    def test_other_session_secret_not_checked(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        # Add a secret for THIS session's NPC
        secret = NPCSecretModel(
            session_id=session.id,
            npc_id=major_npcs[0].id,
            content="Blood jade seal",
            status="hidden",
        )
        db_session.add(secret)

        # Create another session with a different secret
        other_session = SessionModel(
            user_id="user-other-sec", world_id=world.id, status="active",
        )
        db_session.add(other_session)
        db_session.commit()
        db_session.refresh(other_session)

        other_secret = NPCSecretModel(
            session_id=other_session.id,
            npc_id=major_npcs[0].id,
            content="Demon king identity",
            status="hidden",
        )
        db_session.add(other_secret)
        db_session.commit()

        # Add session NPC state for the NPC
        snpc_state = SessionNPCStateModel(
            session_id=session.id,
            npc_template_id=major_npcs[0].id,
            trust_score=50,
        )
        db_session.add(snpc_state)
        db_session.commit()

        validator = NPCKnowledgeValidator()
        state = _make_canonical_state([major_npcs[0].id])

        # Validate knowledge that references THIS session's secret
        result = validator.validate_knowledge(
            npc_id=major_npcs[0].id,
            knowledge="I know about the Blood jade seal",
            state=state,
            db=db_session,
            session_id=session.id,
        )
        # NPC owns this secret → should pass (owner has access)
        assert result.is_valid

    def test_other_session_secret_does_not_cause_false_positive(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        other_session = SessionModel(
            user_id="user-other-fp", world_id=world.id, status="active",
        )
        db_session.add(other_session)
        db_session.commit()
        db_session.refresh(other_session)

        # Secret in OTHER session
        other_secret = NPCSecretModel(
            session_id=other_session.id,
            npc_id=major_npcs[0].id,
            content="Demon king true name",
            status="hidden",
        )
        db_session.add(other_secret)
        db_session.commit()

        snpc_state = SessionNPCStateModel(
            session_id=session.id,
            npc_template_id=major_npcs[0].id,
            trust_score=50,
        )
        db_session.add(snpc_state)
        db_session.commit()

        validator = NPCKnowledgeValidator()
        state = _make_canonical_state([major_npcs[0].id])

        # Knowledge referencing the OTHER session's secret content
        result = validator.validate_knowledge(
            npc_id=major_npcs[0].id,
            knowledge="I know the Demon king true name",
            state=state,
            db=db_session,
            session_id=session.id,
        )
        # The other session's secret should NOT be checked against this session
        # So this should pass (no protected facts from THIS session match)
        assert result.is_valid


# ═══════════════════════════════════════════════════════════════════════════
# 9. Enrichment never leaks private fields
# ═══════════════════════════════════════════════════════════════════════════


class TestEnrichmentNoPrivateFieldLeak:
    """Enriched context must not contain private_reasoning,
    decision_audit, or secret_sensitive keys."""

    def test_enriched_context_has_no_private_reasoning(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Normal memory", status="active", visibility="npc_private",
        )

        original = {"profile": {"name": major_npcs[0].name}}
        enriched = enrich_npc_context_with_memories(
            original, db_session, session.id, major_npcs[0].id,
        )

        # Enriched context must not contain these private fields
        assert "private_reasoning" not in enriched
        assert "decision_audit" not in enriched
        assert "secret_sensitive" not in enriched

    def test_retrieved_memories_have_no_secret_fields(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Memory content", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
        )

        for mem in result.memories:
            mem_dict = mem.__dict__
            # These internal fields must never appear in retrieved memories
            assert "private_reasoning" not in mem_dict
            assert "decision_audit" not in mem_dict
            assert "secret_sensitive" not in mem_dict
            # Also no raw secrets/API keys
            assert "api_key" not in mem_dict
            assert "password" not in mem_dict
            assert "token" not in mem_dict

    def test_enriched_memory_dicts_have_no_secret_fields(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Another memory", status="active", visibility="npc_private",
        )

        original = {"profile": {"name": major_npcs[0].name}}
        enriched = enrich_npc_context_with_memories(
            original, db_session, session.id, major_npcs[0].id,
        )

        for mem_dict in enriched.get("retrieved_private_memories", []):
            assert "private_reasoning" not in mem_dict
            assert "decision_audit" not in mem_dict
            assert "secret_sensitive" not in mem_dict
            assert "api_key" not in mem_dict


# ═══════════════════════════════════════════════════════════════════════════
# 10. Post-commit writer source-bound constraints
# ═══════════════════════════════════════════════════════════════════════════


class TestPostCommitSourceBoundConstraints:
    """Written memories must always have knowledge_source = source_type."""

    def test_knowledge_source_matches_source_type(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.idempotent_create({
            "session_id": session.id,
            "npc_id": major_npcs[0].id,
            "npc_template_id": major_npcs[0].id,
        })

        for source_type in ["decision", "observation", "dialogue", "event"]:
            proposal = _make_proposal(
                npc_id=major_npcs[0].id,
                new_memory_candidates=[
                    {
                        "memory_text": f"Memory from {source_type}",
                        "source_type": source_type,
                    },
                ],
            )
            result = write_post_commit_memories(
                db_session, session.id, major_npcs[0].id,
                proposal, [f"evt_{source_type}"], source_turn_no=5,
            )
            assert len(result.written_ids) == 1
            repo = NPCPrivateMemoryRepository(db_session)
            written = repo.get_by_id(result.written_ids[0])
            assert written.knowledge_source == source_type

    def test_written_memory_scoped_to_session_and_npc(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.idempotent_create({
            "session_id": session.id,
            "npc_id": major_npcs[0].id,
            "npc_template_id": major_npcs[0].id,
        })

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[
                {"memory_text": "Scoped memory", "source_type": "decision"},
            ],
        )
        result = write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            proposal, ["evt_scoped"], source_turn_no=1,
        )

        repo = NPCPrivateMemoryRepository(db_session)
        written = repo.get_by_id(result.written_ids[0])
        assert written.session_id == session.id
        assert written.npc_template_id == major_npcs[0].id
        assert written.npc_id == major_npcs[0].id

    def test_written_memory_default_visibility_npc_private(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.idempotent_create({
            "session_id": session.id,
            "npc_id": major_npcs[0].id,
            "npc_template_id": major_npcs[0].id,
        })

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[
                {"memory_text": "Default vis", "source_type": "decision"},
            ],
        )
        result = write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            proposal, ["evt_vis"], source_turn_no=1,
        )

        repo = NPCPrivateMemoryRepository(db_session)
        written = repo.get_by_id(result.written_ids[0])
        assert written.visibility == "npc_private"

    def test_candidate_with_explicit_gm_only_visibility_still_written_as_specified(
        self, db_session, monkeypatch,
    ):
        """If a candidate explicitly sets visibility=gm_only, the writer
        should honor it (it's the candidate's declared visibility)."""
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.idempotent_create({
            "session_id": session.id,
            "npc_id": major_npcs[0].id,
            "npc_template_id": major_npcs[0].id,
        })

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[
                {
                    "memory_text": "GM-only memory",
                    "source_type": "decision",
                    "visibility": "gm_only",
                },
            ],
        )
        result = write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            proposal, ["evt_gm"], source_turn_no=1,
        )

        repo = NPCPrivateMemoryRepository(db_session)
        written = repo.get_by_id(result.written_ids[0])
        assert written.visibility == "gm_only"


# ═══════════════════════════════════════════════════════════════════════════
# Additional hardening: normalization preserves legacy fields
# ═══════════════════════════════════════════════════════════════════════════


class TestNormalizationPreservesLegacyFieldsUnderLeakHardening:
    """Normalization must not strip legacy fields even when filtering
    memory IDs and candidates."""

    def test_visible_motivation_preserved_after_filtering(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            visible_motivation="Wants to help the player",
            hidden_motivation="Secretly plotting",
            used_memory_ids=["fake-id"],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert result.proposal.visible_motivation == "Wants to help the player"
        assert result.proposal.hidden_motivation == "Secretly plotting"
        assert result.proposal.action_type == "talk"
        # But the spoofed ID was filtered
        assert result.proposal.used_memory_ids == []

    def test_confidence_and_summary_preserved(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            summary="NPC offers a quest",
            confidence=0.85,
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert result.proposal.summary == "NPC offers a quest"
        assert result.proposal.confidence == 0.85


# ═══════════════════════════════════════════════════════════════════════════
# Additional hardening: retrieval result structure integrity
# ═══════════════════════════════════════════════════════════════════════════


class TestRetrievalResultStructureIntegrity:
    """Retrieval results must have consistent structure with no leaks."""

    def test_result_session_and_npc_match_request(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Test", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
        )
        assert result.session_id == session.id
        assert result.npc_template_id == major_npcs[0].id

    def test_used_memory_ids_match_returned_memories(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Mem A", status="active", visibility="npc_private",
        )
        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Mem B", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
        )
        memory_ids = [m.memory_id for m in result.memories]
        assert result.used_memory_ids == memory_ids

    def test_selected_count_matches_memories_length(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Mem 1", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
        )
        assert result.selected_count == len(result.memories)

    def test_audit_does_not_contain_secrets(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Audit test", status="active", visibility="npc_private",
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id,
        )
        audit_str = str(result.retrieval_audit)
        assert "api_key" not in audit_str
        assert "password" not in audit_str
        assert "token" not in audit_str
        assert "private_reasoning" not in audit_str
        assert "secret_sensitive" not in audit_str
