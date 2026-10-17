"""
NPC Decision Adapter (P10-C Phase 6).

Additive adapter that:
- Enriches major NPC decision context with retrieved private memories
  when NPC_MEMORY_FIRST_ENABLED=true.
- Normalizes NPCActionProposal to include used_memory_ids and
  new_memory_candidates with safe defaults.
- Validates used_memory_ids belong to the same session + NPC and were
  available for that decision.
- Filters out invalid/cross-session/cross-NPC memory IDs.

Does not modify legacy proposal fields or behavior when flag is off.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session as DBSession

from ..models.proposals import NPCActionProposal
from ..storage.models import NPCPrivateMemoryModel, NPCTemplateModel
from ..storage.repositories import (
    NPCPrivateMemoryRepository,
    NPCTemplateRepository,
)
from .feature_flags import npc_memory_first_enabled
from .npc_memory_retrieval_service import (
    enrich_npc_context_with_memories,
    retrieve_major_npc_memories,
    RetrievalResult,
)

logger = logging.getLogger(__name__)

_NON_TRIVIAL_ACTION_TYPES: Set[str] = {
    "talk", "dialogue", "attack", "reveal", "cooperate", "refuse", "move", "interact",
}


_REMOVED_PLAYER_KNOWLEDGE = object()


def _exclude_player_knowledge(value: Any) -> Any:
    """Remove player-scoped MemoryFact projections before NPC retrieval/context use."""
    if getattr(value, "fact_type", None) == "player_knowledge":
        return _REMOVED_PLAYER_KNOWLEDGE
    if isinstance(value, dict):
        if value.get("fact_type") == "player_knowledge":
            return _REMOVED_PLAYER_KNOWLEDGE
        filtered: Dict[str, Any] = {}
        for key, child in value.items():
            if key == "player_knowledge":
                continue
            safe_child = _exclude_player_knowledge(child)
            if safe_child is not _REMOVED_PLAYER_KNOWLEDGE:
                filtered[key] = safe_child
        return filtered
    if isinstance(value, list):
        result = []
        for child in value:
            safe_child = _exclude_player_knowledge(child)
            if safe_child is not _REMOVED_PLAYER_KNOWLEDGE:
                result.append(safe_child)
        return result
    if isinstance(value, tuple):
        result = []
        for child in value:
            safe_child = _exclude_player_knowledge(child)
            if safe_child is not _REMOVED_PLAYER_KNOWLEDGE:
                result.append(safe_child)
        return tuple(result)
    return value


@dataclass
class NormalizationResult:
    proposal: NPCActionProposal
    valid_used_memory_ids: List[str] = field(default_factory=list)
    invalid_used_memory_ids: List[str] = field(default_factory=list)
    filtered_candidates: List[Dict[str, Any]] = field(default_factory=list)
    dropped_candidates: List[Dict[str, Any]] = field(default_factory=list)


def enrich_major_npc_decision_context(
    npc_context: Dict[str, Any],
    db: DBSession,
    session_id: str,
    npc_template_id: str,
    query: str = "",
    current_turn: int = 0,
    budget: Optional[int] = None,
    update_recall_stats: bool = False,
) -> Dict[str, Any]:
    """Enrich NPC decision context with retrieved private memories.

    Only enriches when NPC_MEMORY_FIRST_ENABLED=true and NPC is major.
    Returns original context unchanged otherwise.
    """
    if not npc_memory_first_enabled():
        return npc_context

    npc_template_repo = NPCTemplateRepository(db)
    npc_template = npc_template_repo.get_by_id(npc_template_id)
    if npc_template is None or not npc_template.is_major_npc:
        return npc_context

    try:
        # MemoryFact.player_knowledge belongs only to the player. Remove any
        # pre-projected player facts before NPC-scoped retrieval runs; the
        # retrieval service then filters by NPC ownership and its visibility whitelist.
        npc_safe_context = _exclude_player_knowledge(npc_context)
        return enrich_npc_context_with_memories(
            npc_context=npc_safe_context,
            db=db,
            session_id=session_id,
            npc_template_id=npc_template_id,
            query=query,
            current_turn=current_turn,
            budget=budget,
            update_recall_stats=update_recall_stats,
        )
    except Exception as e:
        logger.warning(
            "Memory enrichment failed for session=%s npc=%s: %s",
            session_id, npc_template_id, e,
        )
        return npc_context


def normalize_npc_action_proposal(
    proposal: NPCActionProposal,
    db: DBSession,
    session_id: str,
    npc_template_id: str,
    available_memory_ids: Optional[List[str]] = None,
    current_turn: int = 0,
    is_major_npc: bool = False,
) -> NormalizationResult:
    """Normalize an NPCActionProposal to include Phase 6 fields.

    - Ensures used_memory_ids and new_memory_candidates exist (default empty).
    - Validates used_memory_ids: must belong to same session + NPC, must be
      in available_memory_ids if provided.
    - Filters new_memory_candidates: must have memory_text and source_type.
    - Enforces memory grounding: major NPC non-trivial actions without valid
      used_memory_ids fall back to observe.
    - Returns NormalizationResult with valid/invalid breakdown.
    """
    used_ids = list(proposal.used_memory_ids) if proposal.used_memory_ids else []
    candidates = list(proposal.new_memory_candidates) if proposal.new_memory_candidates else []

    if not npc_memory_first_enabled():
        return NormalizationResult(
            proposal=proposal,
            valid_used_memory_ids=[],
            invalid_used_memory_ids=[],
            filtered_candidates=[],
            dropped_candidates=[],
        )

    valid_ids: List[str] = []
    invalid_ids: List[str] = []

    if used_ids:
        available_set: Optional[Set[str]] = set(available_memory_ids) if available_memory_ids else None
        owned_ids = _fetch_owned_memory_ids(db, session_id, npc_template_id)

        for mid in used_ids:
            if mid not in owned_ids:
                invalid_ids.append(mid)
                continue
            if available_set is not None and mid not in available_set:
                invalid_ids.append(mid)
                continue
            valid_ids.append(mid)

    filtered_cands: List[Dict[str, Any]] = []
    dropped_cands: List[Dict[str, Any]] = []

    for cand in candidates:
        if not isinstance(cand, dict):
            dropped_cands.append(cand)
            continue
        memory_text = cand.get("memory_text")
        if not memory_text or not str(memory_text).strip():
            dropped_cands.append(cand)
            continue
        knowledge_source = cand.get("knowledge_source") or cand.get("source_type")
        if not knowledge_source or not str(knowledge_source).strip():
            dropped_cands.append(cand)
            continue
        cand = dict(cand)
        cand["knowledge_source"] = knowledge_source
        filtered_cands.append(cand)

    update_fields: Dict[str, Any] = {
        "used_memory_ids": valid_ids,
        "new_memory_candidates": filtered_cands,
    }

    if (
        is_major_npc
        and proposal.action_type in _NON_TRIVIAL_ACTION_TYPES
        and len(valid_ids) == 0
    ):
        logger.warning(
            "Major NPC non-trivial action without valid memories: "
            "session=%s npc=%s action_type=%s — falling back to observe",
            session_id, npc_template_id, proposal.action_type,
        )
        update_fields["action_type"] = "observe"
        update_fields["summary"] = "NPC谨慎观察周围情况"
        audit = dict(proposal.decision_audit) if proposal.decision_audit else {}
        audit["fallback_used"] = True
        audit["fallback_reason"] = "no_valid_memories_for_non_trivial_action"
        update_fields["decision_audit"] = audit

    updated_proposal = proposal.model_copy(update=update_fields)

    return NormalizationResult(
        proposal=updated_proposal,
        valid_used_memory_ids=valid_ids,
        invalid_used_memory_ids=invalid_ids,
        filtered_candidates=filtered_cands,
        dropped_candidates=dropped_cands,
    )


def _fetch_owned_memory_ids(
    db: DBSession,
    session_id: str,
    npc_template_id: str,
) -> Set[str]:
    """Fetch all memory IDs owned by this session + NPC template."""
    repo = NPCPrivateMemoryRepository(db)
    rows = repo.get_by_npc_template(session_id, npc_template_id)
    return {str(row.id) for row in rows}
