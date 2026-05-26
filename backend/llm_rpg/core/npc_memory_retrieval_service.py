"""
Major NPC Memory Retrieval Service (P10-C Phase 5).

Provides deterministic lexical/recent/salience scoring over active
NPCPrivateMemoryModel rows for a given session + npc_template_id.

Hard constraints:
- Filter strictly by session_id + npc_template_id, status/visibility, never
  return other NPC memories.
- No vector/embedding/provider calls.
- All scoring is deterministic and SQLite-compatible.
- Return structured results with memory id, text/summary, score, reason/signals,
  source fields, tags/entity refs, and no secrets.
"""

from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from ..storage.models import NPCPrivateMemoryModel, NPCMemoryScopeModel, NPCTemplateModel
from ..storage.repositories import (
    NPCPrivateMemoryRepository,
    NPCMemoryScopeRepository,
    NPCTemplateRepository,
)
from .feature_flags import npc_memory_first_enabled


@dataclass
class RetrievedMemory:

    memory_id: str
    text: str
    summary: Optional[str]
    score: float
    reason: str
    signals: Dict[str, float] = field(default_factory=dict)
    memory_kind: Optional[str] = None
    knowledge_source: Optional[str] = None
    source_turn_no: Optional[int] = None
    tags: List[str] = field(default_factory=list)
    entity_refs: List[str] = field(default_factory=list)
    location_id: Optional[str] = None


@dataclass
class RetrievalResult:
    """Full retrieval result for one NPC in one session."""

    session_id: str
    npc_template_id: str
    memories: List[RetrievedMemory] = field(default_factory=list)
    used_memory_ids: List[str] = field(default_factory=list)
    total_candidates: int = 0
    selected_count: int = 0
    retrieval_audit: Dict[str, Any] = field(default_factory=dict)


_W_SALIENCE = 0.30
_W_RECENCY = 0.30
_W_LEXICAL = 0.25
_W_CONFIDENCE = 0.15
_DEFAULT_BUDGET = 10


def _recency_score(source_turn_no: Optional[int], current_turn: int) -> float:
    if source_turn_no is None or current_turn <= 0:
        return 0.5
    age = max(0, current_turn - source_turn_no)
    return math.exp(-age / 20.0)  # half-life ~20 turns


def _lexical_score(text: str, query: str) -> float:
    if not query or not text:
        return 0.0

    text_lower = text.lower()
    query_lower = query.lower()

    bonus = 0.3 if query_lower in text_lower else 0.0

    query_terms = set(re.findall(r"\w+", query_lower))
    text_terms = set(re.findall(r"\w+", text_lower))

    if not query_terms:
        return 0.0

    overlap = len(query_terms & text_terms) / len(query_terms)
    return min(1.0, overlap + bonus)


def _salience_score(salience: Optional[float], importance: Optional[float]) -> float:
    if salience is not None:
        return max(0.0, min(1.0, float(salience)))
    if importance is not None:
        return max(0.0, min(1.0, float(importance)))
    return 0.5


def _confidence_score(confidence: Optional[float], current_strength: Optional[float]) -> float:
    if confidence is not None:
        return max(0.0, min(1.0, float(confidence)))
    if current_strength is not None:
        return max(0.0, min(1.0, float(current_strength)))
    return 0.8


def retrieve_major_npc_memories(
    db: DBSession,
    session_id: str,
    npc_template_id: str,
    query: str = "",
    current_turn: int = 0,
    budget: Optional[int] = None,
    update_recall_stats: bool = False,
) -> RetrievalResult:
    """Retrieve and score active private memories for a major NPC.

    Filters by session_id + npc_template_id, status active/None,
    visibility npc_private/npc_shared/None. Scoring: salience, recency,
    lexical, confidence. Returns RetrievalResult with audit payload.

    By default (update_recall_stats=False), retrieval is pure and does
    NOT commit recall stats (recall_count, last_accessed_turn). This
    prevents N per-memory commits in the hot path and avoids persisting
    recall even if the turn later fails. Recall stats should be updated
    only after the NPC action path has been committed, via
    batch_update_recall_stats or the post-commit memory writer path.
    Set update_recall_stats=True only for explicit opt-in safe paths
    (e.g. direct debug/audit calls that intentionally flush stats).
    """
    if not npc_memory_first_enabled():
        return RetrievalResult(
            session_id=session_id,
            npc_template_id=npc_template_id,
            total_candidates=0,
            selected_count=0,
            retrieval_audit={"flag_enabled": False, "reason": "NPC_MEMORY_FIRST_ENABLED is off"},
        )

    npc_template_repo = NPCTemplateRepository(db)
    npc_template = npc_template_repo.get_by_id(npc_template_id)
    if npc_template is None or not npc_template.is_major_npc:
        return RetrievalResult(
            session_id=session_id,
            npc_template_id=npc_template_id,
            total_candidates=0,
            selected_count=0,
            retrieval_audit={
                "flag_enabled": True,
                "reason": "NPC is not major (is_major_npc is False or missing)",
            },
        )

    if budget is None:
        scope_repo = NPCMemoryScopeRepository(db)
        scope = scope_repo.get_by_session_and_npc_template(session_id, npc_template_id)
        profile = scope.retrieval_profile_json if scope and scope.retrieval_profile_json else {}
        budget = profile.get("max_memories", _DEFAULT_BUDGET)

    memory_repo = NPCPrivateMemoryRepository(db)

    all_memories = memory_repo.get_by_npc_template(session_id, npc_template_id)

    candidates: List[NPCPrivateMemoryModel] = []
    for m in all_memories:
        if m.status not in ("active", None):
            continue
        if m.visibility not in ("npc_private", "npc_shared", None):
            continue
        candidates.append(m)

    total_candidates = len(candidates)

    scored: List[tuple] = []
    for m in candidates:
        text = m.memory_text or m.content or ""
        summary = m.short_summary

        s_sal = _salience_score(m.salience, m.importance)
        s_rec = _recency_score(m.source_turn_no, current_turn)
        s_lex = _lexical_score(text, query) if query else 0.0
        s_con = _confidence_score(m.confidence, m.current_strength)

        combined = (
            _W_SALIENCE * s_sal
            + _W_RECENCY * s_rec
            + _W_LEXICAL * s_lex
            + _W_CONFIDENCE * s_con
        )

        signals = {
            "salience": round(s_sal, 4),
            "recency": round(s_rec, 4),
            "lexical": round(s_lex, 4),
            "confidence": round(s_con, 4),
        }

        parts = []
        if s_sal >= 0.7:
            parts.append("high_salience")
        if s_rec >= 0.7:
            parts.append("recent")
        if s_lex >= 0.5:
            parts.append("lexical_match")
        if s_con >= 0.9:
            parts.append("high_confidence")
        reason = "+".join(parts) if parts else "baseline"

        rm = RetrievedMemory(
            memory_id=m.id,
            text=text,
            summary=summary,
            score=round(combined, 4),
            reason=reason,
            signals=signals,
            memory_kind=m.memory_kind,
            knowledge_source=m.knowledge_source,
            source_turn_no=m.source_turn_no,
            tags=m.tags_json or [],
            entity_refs=m.entity_refs_json or [],
            location_id=m.location_id,
        )
        scored.append((combined, rm))

    scored.sort(key=lambda t: (t[0], t[1].source_turn_no or 0), reverse=True)

    selected = scored[:budget]
    memories = [rm for _, rm in selected]
    used_memory_ids = [rm.memory_id for rm in memories]

    audit: Dict[str, Any] = {
        "flag_enabled": True,
        "npc_is_major": True,
        "query_provided": bool(query),
        "current_turn": current_turn,
        "budget": budget,
        "total_candidates": total_candidates,
        "selected_count": len(memories),
        "scoring_weights": {
            "salience": _W_SALIENCE,
            "recency": _W_RECENCY,
            "lexical": _W_LEXICAL,
            "confidence": _W_CONFIDENCE,
        },
    }

    if current_turn > 0 and used_memory_ids:
        audit["recall_eligible_count"] = len(used_memory_ids)
        if update_recall_stats:
            for mid in used_memory_ids:
                memory_repo.update_recall(mid, current_turn)
            audit["recall_updated_count"] = len(used_memory_ids)

    return RetrievalResult(
        session_id=session_id,
        npc_template_id=npc_template_id,
        memories=memories,
        used_memory_ids=used_memory_ids,
        total_candidates=total_candidates,
        selected_count=len(memories),
        retrieval_audit=audit,
    )


def enrich_npc_context_with_memories(
    npc_context: Dict[str, Any],
    db: DBSession,
    session_id: str,
    npc_template_id: str,
    query: str = "",
    current_turn: int = 0,
    budget: Optional[int] = None,
    update_recall_stats: bool = False,
) -> Dict[str, Any]:
    """Additively enrich npc_context with retrieved private memories.

    Adds retrieved_private_memories, used_memory_ids, memory_retrieval_audit.
    Does not overwrite existing keys.
    """
    result = retrieve_major_npc_memories(
        db=db,
        session_id=session_id,
        npc_template_id=npc_template_id,
        query=query,
        current_turn=current_turn,
        budget=budget,
        update_recall_stats=update_recall_stats,
    )

    enriched = dict(npc_context)  # shallow copy, never mutates input
    enriched["retrieved_private_memories"] = [
        {
            "memory_id": rm.memory_id,
            "text": rm.text,
            "summary": rm.summary,
            "score": rm.score,
            "reason": rm.reason,
            "signals": rm.signals,
            "memory_kind": rm.memory_kind,
            "knowledge_source": rm.knowledge_source,
            "source_turn_no": rm.source_turn_no,
            "tags": rm.tags,
            "entity_refs": rm.entity_refs,
            "location_id": rm.location_id,
        }
        for rm in result.memories
    ]
    enriched["used_memory_ids"] = result.used_memory_ids
    enriched["memory_retrieval_audit"] = result.retrieval_audit

    return enriched


def batch_update_recall_stats(
    db: DBSession,
    memory_ids: List[str],
    current_turn: int,
) -> int:
    """Batch-update recall stats for a list of memory IDs after commit.

    This is the safe post-commit path for updating recall_count and
    last_accessed_turn. It performs a single commit for all updates
    rather than N individual commits.

    Returns the number of memories actually updated.
    """
    if not memory_ids or current_turn <= 0:
        return 0

    memory_repo = NPCPrivateMemoryRepository(db)
    updated = 0
    for mid in memory_ids:
        memory = memory_repo.get_by_id(mid)
        if memory:
            memory.recall_count += 1
            memory.last_accessed_turn = current_turn
            updated += 1

    if updated > 0:
        db.commit()

    return updated