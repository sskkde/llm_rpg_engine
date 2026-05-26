"""
P10-C Phase 6: NPC Decision Adapter + Post-Commit Memory Write tests.

Covers:
- Flag off → legacy proposal fields unchanged, no new fields populated
- Major NPC context enrichment with retrieved memory IDs
- Proposal normalization defaults (empty lists when fields absent)
- Invalid used_memory_ids filtered/rejected
- Post-commit writes produce source-bound NPCPrivateMemoryModel rows
- No writes for minor NPC or flag off
- No cross-session/NPC memory use
- Narration proposals never produce memory rows
- Candidate without source_type rejected
- Candidate without memory_text rejected
"""

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
)
from llm_rpg.models.proposals import (
    NPCActionProposal,
    ProposalAuditMetadata,
    ProposalType,
    ProposalSource,
    NarrationProposal,
)
from llm_rpg.core.npc_decision_adapter import (
    enrich_major_npc_decision_context,
    normalize_npc_action_proposal,
    NormalizationResult,
)
from llm_rpg.core.post_commit_memory_writer import (
    write_post_commit_memories,
    update_recall_stats_post_commit,
    PostCommitWriteResult,
)
from llm_rpg.core.npc_memory_retrieval_service import (
    retrieve_major_npc_memories,
)
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


# ──────────────────────────────────────────────────────────────────────────────
# Flag off → legacy behavior
# ──────────────────────────────────────────────────────────────────────────────


class TestFlagOffLegacyBehavior:
    def test_proposal_has_default_empty_fields(self):
        proposal = _make_proposal()
        assert proposal.used_memory_ids == []
        assert proposal.new_memory_candidates == []
        assert proposal.decision_audit is None

    def test_enrichment_returns_original_context_when_flag_off(self, db_session, monkeypatch):
        monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        original = {"profile": {"name": "Test NPC"}}
        result = enrich_major_npc_decision_context(
            original, db_session, session.id, major_npcs[0].id,
        )
        assert result is original

    def test_normalization_returns_empty_when_flag_off(self, db_session, monkeypatch):
        monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            used_memory_ids=["fake-id"],
            new_memory_candidates=[{"memory_text": "test", "source_type": "decision"}],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert result.valid_used_memory_ids == []
        assert result.filtered_candidates == []

    def test_post_commit_no_writes_when_flag_off(self, db_session, monkeypatch):
        monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[
                {"memory_text": "I learned something", "source_type": "decision"}
            ],
        )
        result = write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            proposal, ["evt_001"], source_turn_no=5,
        )
        assert result.written_ids == []
        assert result.dropped_count == 0


# ──────────────────────────────────────────────────────────────────────────────
# Major NPC context enrichment
# ──────────────────────────────────────────────────────────────────────────────


class TestMajorNPCContextEnrichment:
    def test_context_includes_retrieved_memory_ids(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        mem = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="I remember the ancient ritual",
            status="active", visibility="npc_private",
        )

        original = {"profile": {"name": major_npcs[0].name}}
        enriched = enrich_major_npc_decision_context(
            original, db_session, session.id, major_npcs[0].id,
        )

        assert "retrieved_private_memories" in enriched
        assert "used_memory_ids" in enriched
        assert len(enriched["used_memory_ids"]) >= 1
        assert enriched["used_memory_ids"][0] == mem.id

    def test_enrichment_does_not_mutate_original(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Test memory", status="active", visibility="npc_private",
        )

        original = {"key": "value"}
        enrich_major_npc_decision_context(
            original, db_session, session.id, major_npcs[0].id,
        )
        assert "retrieved_private_memories" not in original

    def test_minor_npc_no_enrichment(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, _, minor_npcs = _make_world_session_npcs(
            db_session, major_count=0, minor_count=1,
        )

        original = {"key": "value"}
        enriched = enrich_major_npc_decision_context(
            original, db_session, session.id, minor_npcs[0].id,
        )
        assert enriched is original


# ──────────────────────────────────────────────────────────────────────────────
# Proposal normalization defaults
# ──────────────────────────────────────────────────────────────────────────────


class TestProposalNormalizationDefaults:
    def test_missing_fields_default_to_empty(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(npc_id=major_npcs[0].id)
        assert proposal.used_memory_ids == []
        assert proposal.new_memory_candidates == []

    def test_normalization_preserves_legacy_fields(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            visible_motivation="Wants to help",
            hidden_motivation="Secretly plotting",
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert result.proposal.visible_motivation == "Wants to help"
        assert result.proposal.hidden_motivation == "Secretly plotting"
        assert result.proposal.action_type == "talk"

    def test_normalization_preserves_valid_candidates(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        valid_cand = {
            "memory_text": "I decided to help the player",
            "source_type": "decision",
            "salience": 0.8,
        }
        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[valid_cand],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert len(result.filtered_candidates) == 1
        assert result.filtered_candidates[0]["memory_text"] == "I decided to help the player"


# ──────────────────────────────────────────────────────────────────────────────
# Invalid used_memory_ids filtered/rejected
# ──────────────────────────────────────────────────────────────────────────────


class TestInvalidUsedMemoryIdsFiltered:
    def test_nonexistent_memory_id_rejected(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            used_memory_ids=["nonexistent-memory-id"],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert result.valid_used_memory_ids == []
        assert "nonexistent-memory-id" in result.invalid_used_memory_ids

    def test_other_npc_memory_id_rejected(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session, major_count=2)

        other_mem = _add_private_memory(
            db_session, session.id, major_npcs[1].id,
            content="Other NPC memory", status="active", visibility="npc_private",
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

    def test_own_memory_id_accepted(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        own_mem = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Own memory", status="active", visibility="npc_private",
        )

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            used_memory_ids=[own_mem.id],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert own_mem.id in result.valid_used_memory_ids
        assert result.proposal.used_memory_ids == [own_mem.id]

    def test_available_memory_ids_filter(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        own_mem = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Own memory", status="active", visibility="npc_private",
        )

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            used_memory_ids=[own_mem.id],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
            available_memory_ids=["other-id"],
        )
        assert result.valid_used_memory_ids == []
        assert own_mem.id in result.invalid_used_memory_ids


# ──────────────────────────────────────────────────────────────────────────────
# Candidate validation
# ──────────────────────────────────────────────────────────────────────────────


class TestCandidateValidation:
    def test_candidate_without_memory_text_dropped(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[{"source_type": "decision"}],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert len(result.filtered_candidates) == 0
        assert len(result.dropped_candidates) == 1

    def test_candidate_without_source_type_dropped(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[{"memory_text": "Some text"}],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert len(result.filtered_candidates) == 0
        assert len(result.dropped_candidates) == 1

    def test_non_dict_candidate_dropped(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        # Pydantic validates new_memory_candidates as List[Dict], so non-dict
        # items are rejected at construction. Test with an empty dict instead,
        # which passes Pydantic but lacks required fields.
        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[{}],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert len(result.filtered_candidates) == 0
        assert len(result.dropped_candidates) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Post-commit source-bound memory writes
# ──────────────────────────────────────────────────────────────────────────────


class TestPostCommitMemoryWrites:
    def test_writes_source_bound_memory_rows(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.idempotent_create({
            "session_id": session.id,
            "npc_id": major_npcs[0].id,
            "npc_template_id": major_npcs[0].id,
        })

        candidate = {
            "memory_text": "I chose to trust the player",
            "source_type": "decision",
            "salience": 0.8,
            "confidence": 0.9,
            "tags": ["trust", "decision"],
            "entity_refs": ["player"],
        }
        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[candidate],
        )

        result = write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            proposal, ["evt_committed_001"], source_turn_no=5,
        )

        assert len(result.written_ids) == 1
        assert result.dropped_count == 0

        repo = NPCPrivateMemoryRepository(db_session)
        written = repo.get_by_id(result.written_ids[0])
        assert written is not None
        assert written.memory_text == "I chose to trust the player"
        assert written.knowledge_source == "decision"
        assert written.source_turn_no == 5
        assert written.status == "active"
        assert written.visibility == "npc_private"
        assert written.memory_kind == "decision"
        assert written.source_id == "evt_committed_001"
        assert written.source_ref == "decision:evt_committed_001"
        assert written.npc_template_id == major_npcs[0].id
        assert written.session_id == session.id

    def test_writes_update_scope_count(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.idempotent_create({
            "session_id": session.id,
            "npc_id": major_npcs[0].id,
            "npc_template_id": major_npcs[0].id,
            "memory_count": 0,
        })

        candidate = {
            "memory_text": "New memory",
            "source_type": "decision",
        }
        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[candidate],
        )

        write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            proposal, ["evt_001"], source_turn_no=3,
        )

        scope = scope_repo.get_by_session_and_npc_template(session.id, major_npcs[0].id)
        assert scope.memory_count == 1

    def test_candidate_without_source_type_not_written(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.idempotent_create({
            "session_id": session.id,
            "npc_id": major_npcs[0].id,
            "npc_template_id": major_npcs[0].id,
        })

        candidate = {"memory_text": "I did something", "source_type": ""}
        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[candidate],
        )

        result = write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            proposal, ["evt_001"], source_turn_no=3,
        )
        assert len(result.written_ids) == 0
        assert result.dropped_count == 1


# ──────────────────────────────────────────────────────────────────────────────
# No writes for minor NPC / flag off
# ──────────────────────────────────────────────────────────────────────────────


class TestNoWritesForMinorNPCOrFlagOff:
    def test_minor_npc_no_writes(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, _, minor_npcs = _make_world_session_npcs(
            db_session, major_count=0, minor_count=1,
        )

        candidate = {
            "memory_text": "Minor memory",
            "source_type": "decision",
        }
        proposal = _make_proposal(
            npc_id=minor_npcs[0].id,
            new_memory_candidates=[candidate],
        )

        result = write_post_commit_memories(
            db_session, session.id, minor_npcs[0].id,
            proposal, ["evt_001"], source_turn_no=3,
        )
        assert result.written_ids == []

    def test_flag_off_no_writes(self, db_session, monkeypatch):
        monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        candidate = {
            "memory_text": "Should not be written",
            "source_type": "decision",
        }
        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[candidate],
        )

        result = write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            proposal, ["evt_001"], source_turn_no=3,
        )
        assert result.written_ids == []


# ──────────────────────────────────────────────────────────────────────────────
# No cross-session/NPC memory use
# ──────────────────────────────────────────────────────────────────────────────


class TestCrossSessionNPCIsolation:
    def test_other_session_memory_ids_rejected(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        other_session = SessionModel(user_id="user-other", world_id=world.id, status="active")
        db_session.add(other_session)
        db_session.commit()
        db_session.refresh(other_session)

        other_mem = _add_private_memory(
            db_session, other_session.id, major_npcs[0].id,
            content="Other session memory", status="active", visibility="npc_private",
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

    def test_other_npc_memory_ids_rejected(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session, major_count=2)

        other_mem = _add_private_memory(
            db_session, session.id, major_npcs[1].id,
            content="Other NPC memory", status="active", visibility="npc_private",
        )

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            used_memory_ids=[other_mem.id],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
        )
        assert result.valid_used_memory_ids == []

    def test_post_commit_writes_scoped_to_correct_npc(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session, major_count=2)

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.idempotent_create({
            "session_id": session.id,
            "npc_id": major_npcs[0].id,
            "npc_template_id": major_npcs[0].id,
        })

        candidate = {
            "memory_text": "NPC 0 memory",
            "source_type": "decision",
        }
        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            new_memory_candidates=[candidate],
        )

        result = write_post_commit_memories(
            db_session, session.id, major_npcs[0].id,
            proposal, ["evt_001"], source_turn_no=3,
        )

        assert len(result.written_ids) == 1
        repo = NPCPrivateMemoryRepository(db_session)
        written = repo.get_by_id(result.written_ids[0])
        assert written.npc_template_id == major_npcs[0].id
        assert written.session_id == session.id


# ──────────────────────────────────────────────────────────────────────────────
# Narration never produces memory rows
# ──────────────────────────────────────────────────────────────────────────────


class TestNarrationNeverProducesMemories:
    def test_narration_proposal_no_writes(self, db_session, monkeypatch):
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


# ──────────────────────────────────────────────────────────────────────────────
# Fallback proposal compatibility
# ──────────────────────────────────────────────────────────────────────────────


class TestFallbackProposalCompatibility:
    def test_fallback_proposal_has_empty_memory_fields(self):
        from llm_rpg.models.proposals import create_fallback_npc_action
        fallback = create_fallback_npc_action(npc_id="npc-test")
        assert fallback.used_memory_ids == []
        assert fallback.new_memory_candidates == []
        assert fallback.decision_audit is None
        assert fallback.is_fallback is True

    def test_old_proposal_construction_still_works(self):
        proposal = NPCActionProposal(
            npc_id="npc-1",
            action_type="idle",
            summary="NPC idles",
            audit=_make_audit(),
        )
        assert proposal.used_memory_ids == []
        assert proposal.new_memory_candidates == []
        assert proposal.decision_audit is None
        assert proposal.visible_motivation == ""


# ──────────────────────────────────────────────────────────────────────────────
# Post-commit recall stats update
# ──────────────────────────────────────────────────────────────────────────────


class TestPostCommitRecallStatsUpdate:
    def test_update_recall_stats_post_commit_updates_memories(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        m1 = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Used memory A", status="active", visibility="npc_private",
            importance=0.8, salience=0.8, source_turn_no=3,
        )
        m2 = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Used memory B", status="active", visibility="npc_private",
            importance=0.7, salience=0.7, source_turn_no=4,
        )

        updated = update_recall_stats_post_commit(
            db_session, session.id, major_npcs[0].id,
            used_memory_ids=[m1.id, m2.id], current_turn=7,
        )
        assert updated == 2

        db_session.refresh(m1)
        db_session.refresh(m2)
        assert m1.recall_count == 1
        assert m1.last_accessed_turn == 7
        assert m2.recall_count == 1
        assert m2.last_accessed_turn == 7

    def test_update_recall_stats_post_commit_noop_for_minor_npc(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, _, minor_npcs = _make_world_session_npcs(
            db_session, major_count=0, minor_count=1,
        )

        m = _add_private_memory(
            db_session, session.id, minor_npcs[0].id,
            content="Minor memory", status="active", visibility="npc_private",
        )

        updated = update_recall_stats_post_commit(
            db_session, session.id, minor_npcs[0].id,
            used_memory_ids=[m.id], current_turn=5,
        )
        assert updated == 0

        db_session.refresh(m)
        assert m.recall_count == 0

    def test_update_recall_stats_post_commit_noop_flag_off(self, db_session, monkeypatch):
        monkeypatch.delenv("NPC_MEMORY_FIRST_ENABLED", raising=False)
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        m = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Memory", status="active", visibility="npc_private",
        )

        updated = update_recall_stats_post_commit(
            db_session, session.id, major_npcs[0].id,
            used_memory_ids=[m.id], current_turn=5,
        )
        assert updated == 0

    def test_retrieval_default_no_auto_commit_then_post_commit(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        m = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Retrieved memory", status="active", visibility="npc_private",
            importance=0.8, salience=0.8, source_turn_no=3,
        )

        result = retrieve_major_npc_memories(
            db_session, session.id, major_npcs[0].id, current_turn=7,
        )
        assert m.id in result.used_memory_ids
        db_session.refresh(m)
        assert m.recall_count == 0

        update_recall_stats_post_commit(
            db_session, session.id, major_npcs[0].id,
            used_memory_ids=result.used_memory_ids, current_turn=7,
        )
        db_session.refresh(m)
        assert m.recall_count == 1
        assert m.last_accessed_turn == 7


# ──────────────────────────────────────────────────────────────────────────────
# C3: used_memory_ids enforcement for major NPC non-trivial actions
# ──────────────────────────────────────────────────────────────────────────────


class TestMajorNPCNonTrivialActionEnforcement:
    @pytest.mark.parametrize("action_type", [
        "talk", "dialogue", "attack", "reveal", "cooperate", "refuse", "move", "interact",
    ])
    def test_major_npc_non_trivial_action_requires_memory_reference(
        self, db_session, monkeypatch, action_type,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            action_type=action_type,
            summary=f"NPC does {action_type}",
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
            is_major_npc=True,
        )
        assert result.proposal.action_type == "observe"
        assert "谨慎观察" in result.proposal.summary
        assert result.proposal.decision_audit is not None
        assert result.proposal.decision_audit.get("fallback_used") is True
        assert result.proposal.decision_audit.get("fallback_reason") == "no_valid_memories_for_non_trivial_action"

    @pytest.mark.parametrize("action_type", ["idle", "observe"])
    def test_major_npc_idle_observe_allows_empty_memory_ids(
        self, db_session, monkeypatch, action_type,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            action_type=action_type,
            summary=f"NPC does {action_type}",
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
            is_major_npc=True,
        )
        assert result.proposal.action_type == action_type
        assert result.proposal.decision_audit is None

    def test_major_npc_non_trivial_action_with_valid_memory_ids_passes(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        own_mem = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="I remember the player", status="active", visibility="npc_private",
        )

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            action_type="talk",
            summary="NPC talks to player",
            used_memory_ids=[own_mem.id],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
            is_major_npc=True,
        )
        assert result.proposal.action_type == "talk"
        assert own_mem.id in result.valid_used_memory_ids
        assert result.proposal.decision_audit is None

    def test_non_major_npc_non_trivial_action_allows_empty_memory_ids(
        self, db_session, monkeypatch,
    ):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, _, minor_npcs = _make_world_session_npcs(
            db_session, major_count=0, minor_count=1,
        )

        proposal = _make_proposal(
            npc_id=minor_npcs[0].id,
            action_type="talk",
            summary="Minor NPC talks",
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, minor_npcs[0].id,
            is_major_npc=False,
        )
        assert result.proposal.action_type == "talk"

    def test_major_npc_rejects_cross_npc_memory_id(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session, major_count=2)

        other_mem = _add_private_memory(
            db_session, session.id, major_npcs[1].id,
            content="Other NPC memory", status="active", visibility="npc_private",
        )

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            action_type="talk",
            summary="NPC talks",
            used_memory_ids=[other_mem.id],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
            is_major_npc=True,
        )
        assert result.proposal.action_type == "observe"
        assert other_mem.id in result.invalid_used_memory_ids
        assert len(result.valid_used_memory_ids) == 0

    def test_major_npc_rejects_unavailable_memory_id(self, db_session, monkeypatch):
        monkeypatch.setenv("NPC_MEMORY_FIRST_ENABLED", "true")
        world, session, major_npcs, _ = _make_world_session_npcs(db_session)

        own_mem = _add_private_memory(
            db_session, session.id, major_npcs[0].id,
            content="Own memory but unavailable", status="active", visibility="npc_private",
        )

        proposal = _make_proposal(
            npc_id=major_npcs[0].id,
            action_type="talk",
            summary="NPC talks",
            used_memory_ids=[own_mem.id],
        )
        result = normalize_npc_action_proposal(
            proposal, db_session, session.id, major_npcs[0].id,
            available_memory_ids=["some-other-id"],
            is_major_npc=True,
        )
        assert result.proposal.action_type == "observe"
        assert own_mem.id in result.invalid_used_memory_ids
        assert len(result.valid_used_memory_ids) == 0


# ──────────────────────────────────────────────────────────────────────────────
# C2: Prompt memory-first rules and output fields
# ──────────────────────────────────────────────────────────────────────────────


class TestPromptMemoryFirstRules:
    def test_prompt_includes_memory_first_rules(self):
        from llm_rpg.llm.proposal_pipeline import ProposalPipeline
        from llm_rpg.llm.proposal_pipeline import LLMMessage

        pipeline = ProposalPipeline.__new__(ProposalPipeline)

        import asyncio
        messages = asyncio.get_event_loop().run_until_complete(
            self._capture_messages(pipeline)
        )

        user_content = messages[-1].content
        system_content = messages[0].content

        assert "只能基于NPC当前可见事实和retrieved_private_memories做出决策" in system_content
        assert "如果没有相关记忆，不得虚构经历" in system_content
        assert "major NPC的非idle/observe行为必须引用至少一个used_memory_ids" in system_content
        assert "new_memory_candidates必须使用第一人称视角" in system_content
        assert "summary和visible_motivation不得泄露玩家不可见秘密" in system_content

    def test_prompt_includes_used_memory_ids_output_field(self):
        from llm_rpg.llm.proposal_pipeline import ProposalPipeline

        pipeline = ProposalPipeline.__new__(ProposalPipeline)

        import asyncio
        messages = asyncio.get_event_loop().run_until_complete(
            self._capture_messages(pipeline)
        )

        user_content = messages[-1].content

        assert "used_memory_ids" in user_content
        assert "new_memory_candidates" in user_content
        assert "decision_audit" in user_content
        assert "reasoning_basis" in user_content
        assert "memory_count_used" in user_content
        assert "fallback_used" in user_content
        assert "memory_text" in user_content
        assert "knowledge_source" in user_content

    async def _capture_messages(self, pipeline):
        captured = []

        original_generate_proposal = pipeline.generate_proposal

        async def fake_generate_proposal(**kwargs):
            captured.extend(kwargs["prompt_messages"])
            from llm_rpg.models.proposals import (
                NPCActionProposal,
                ProposalAuditMetadata,
                ProposalType,
                ProposalSource,
            )
            return NPCActionProposal(
                npc_id="test",
                action_type="idle",
                summary="test",
                audit=ProposalAuditMetadata(
                    proposal_type=ProposalType.NPC_ACTION,
                    source_engine=ProposalSource.NPC_ENGINE,
                ),
            )

        pipeline.generate_proposal = fake_generate_proposal
        await pipeline.generate_npc_action(
            npc_id="test-npc",
            npc_context={"profile": {"name": "Test"}},
        )
        return captured
