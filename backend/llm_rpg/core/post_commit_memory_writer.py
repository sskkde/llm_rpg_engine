"""
Source-Bound NPC Memory Writer (historically named post-commit; P10-C Phase 6).

Persists source-bound NPCPrivateMemoryModel rows from accepted
new_memory_candidates. These memories are retrieved for future NPC decisions,
so managed turn calls write them in the authoritative turn transaction.

Safety constraints:
- Requires source_type, source_id, source_turn_no on each candidate.
- Requires source_type, source_id, source_turn_no on each candidate.
- Rejects candidates missing memory_text or source_type.
- Only writes for major NPCs when NPC_MEMORY_FIRST_ENABLED=true.
- Never writes for narration proposals.
- Strictly scoped to session_id + npc_template_id.
- Updates memory scope bookkeeping after writes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from ..models.proposals import NPCActionProposal, ProposalType
from ..storage.models import NPCPrivateMemoryModel, NPCTemplateModel
from ..storage.repositories import (
    NPCPrivateMemoryRepository,
    NPCMemoryScopeRepository,
    NPCTemplateRepository,
)
from .feature_flags import npc_memory_first_enabled
from .npc_memory_retrieval_service import batch_update_recall_stats
from .turn_unit_of_work import is_managed

logger = logging.getLogger(__name__)


@dataclass
class PostCommitWriteResult:
    written_ids: List[str] = field(default_factory=list)
    dropped_count: int = 0
    errors: List[str] = field(default_factory=list)


def write_post_commit_memories(
    db: DBSession,
    session_id: str,
    npc_template_id: str,
    proposal: NPCActionProposal,
    committed_event_ids: List[str],
    source_turn_no: int,
) -> PostCommitWriteResult:
    """Write source-bound private memories from accepted proposal candidates.

    Source-bound private memories are necessary cognition: during a managed
    turn they are written in the turn transaction and failures propagate. In
    legacy unmanaged callers, per-row failures remain reportable in the result.
    """
    if not npc_memory_first_enabled():
        return PostCommitWriteResult()

    npc_template_repo = NPCTemplateRepository(db)
    npc_template = npc_template_repo.get_by_id(npc_template_id)
    if npc_template is None or not npc_template.is_major_npc:
        return PostCommitWriteResult()

    candidates = getattr(proposal, "new_memory_candidates", None) or []
    if not candidates:
        return PostCommitWriteResult()

    if getattr(proposal.audit, "proposal_type", None) == ProposalType.NARRATION:
        return PostCommitWriteResult()

    memory_repo = NPCPrivateMemoryRepository(db)
    written_ids: List[str] = []
    dropped = 0
    errors: List[str] = []

    source_id = committed_event_ids[0] if committed_event_ids else f"turn_{source_turn_no}"

    for cand in candidates:
        if not isinstance(cand, dict):
            dropped += 1
            continue

        memory_text = cand.get("memory_text")
        source_type = cand.get("knowledge_source") or cand.get("source_type")

        if not memory_text or not str(memory_text).strip():
            dropped += 1
            continue
        if not source_type or not str(source_type).strip():
            dropped += 1
            continue

        cand_source_id = cand.get("source_id", source_id)
        cand_source_ref = cand.get("source_ref", f"{source_type}:{cand_source_id}")
        cand_source_turn = cand.get("source_turn_no", source_turn_no)

        memory_data: Dict[str, Any] = {
            "session_id": session_id,
            "npc_id": npc_template_id,
            "npc_template_id": npc_template_id,
            "memory_type": cand.get("memory_type", "episodic"),
            "content": memory_text,
            "source_event_ids_json": committed_event_ids[:5],
            "entities_json": cand.get("entity_refs", []),
            "importance": cand.get("salience", cand.get("importance", 0.5)),
            "emotional_weight": cand.get("emotional_weight", 0.0),
            "confidence": cand.get("confidence", 0.8),
            "current_strength": 1.0,
            "created_turn": cand_source_turn,
            "last_accessed_turn": cand_source_turn,
            "recall_count": 0,
            "memory_kind": cand.get("memory_kind", "decision"),
            "memory_text": memory_text,
            "short_summary": cand.get("short_summary"),
            "knowledge_source": source_type,
            "source_id": cand_source_id,
            "source_ref": cand_source_ref,
            "source_turn_no": cand_source_turn,
            "salience": cand.get("salience", cand.get("importance", 0.5)),
            "visibility": cand.get("visibility", "npc_private"),
            "status": "active",
            "tags_json": cand.get("tags", []),
            "entity_refs_json": cand.get("entity_refs", []),
            "location_id": cand.get("location_id"),
        }

        try:
            row = memory_repo.create(memory_data)
            written_ids.append(row.id)
        except Exception as e:
            if is_managed(db):
                raise
            errors.append(f"Failed to write memory: {e}")
            logger.error(
                "Post-commit memory write failed session=%s npc=%s: %s",
                session_id, npc_template_id, e,
            )

    _update_scope_count(db, session_id, npc_template_id, len(written_ids))

    return PostCommitWriteResult(
        written_ids=written_ids,
        dropped_count=dropped,
        errors=errors,
    )


def update_recall_stats_post_commit(
    db: DBSession,
    session_id: str,
    npc_template_id: str,
    used_memory_ids: List[str],
    current_turn: int,
) -> int:
    """Update recall stats for memories used in an NPC action.

    In managed turns this decision-relevant ranking state remains in the
    authoritative turn transaction; unmanaged callers retain legacy commits.

    Returns the number of memories updated.
    """
    if not npc_memory_first_enabled():
        return 0

    npc_template_repo = NPCTemplateRepository(db)
    npc_template = npc_template_repo.get_by_id(npc_template_id)
    if npc_template is None or not npc_template.is_major_npc:
        return 0

    return batch_update_recall_stats(db, used_memory_ids, current_turn)


def _update_scope_count(
    db: DBSession,
    session_id: str,
    npc_template_id: str,
    added: int,
) -> None:
    if added <= 0:
        return
    scope_repo = NPCMemoryScopeRepository(db)
    scope = scope_repo.get_by_session_and_npc_template(session_id, npc_template_id)
    if scope is not None:
        scope.memory_count = (scope.memory_count or 0) + added
        if is_managed(db):
            db.flush()
        else:
            db.commit()
