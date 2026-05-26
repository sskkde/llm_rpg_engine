"""
NPC Seed Memory Initialization Module.

Creates first-person, source-bound private memory rows for major NPCs
from NPCTemplateModel.seed_memory_bundle_json during session/playthrough
initialization. Idempotent: re-running does not duplicate seed memories.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from ..storage.models import NPCTemplateModel
from ..storage.repositories import (
    NPCPrivateMemoryRepository,
    NPCMemoryScopeRepository,
    NPCTemplateRepository,
)
from .feature_flags import npc_memory_first_enabled


def seed_major_npc_private_memories(
    db: DBSession,
    session_id: str,
    world_id: str,
) -> int:
    """
    Create seed memory rows for major NPCs in a session.

    For each major NPC (is_major_npc=True) with a seed_memory_bundle_json,
    create NPCPrivateMemoryModel rows with first-person/source-bound fields
    and an NPCMemoryScopeModel row for retrieval bookkeeping.

    Idempotent: if seed memories already exist for an NPC in this session,
    skip that NPC entirely.

    Args:
        db: SQLAlchemy database session.
        session_id: The session ID being initialized.
        world_id: The world ID to filter NPC templates.

    Returns:
        Number of seed memory rows created (0 if flag off or no major NPCs).
    """
    if not npc_memory_first_enabled():
        return 0

    npc_template_repo = NPCTemplateRepository(db)
    memory_repo = NPCPrivateMemoryRepository(db)
    scope_repo = NPCMemoryScopeRepository(db)

    npc_templates = npc_template_repo.get_by_world(world_id)
    created_count = 0

    for npc_template in npc_templates:
        if not npc_template.is_major_npc:
            continue

        npc_id = npc_template.id
        bundle = npc_template.seed_memory_bundle_json
        if not bundle or not isinstance(bundle, list):
            # Create scope even without seed memories (idempotent)
            scope_repo.idempotent_create({
                "session_id": session_id,
                "npc_id": npc_id,
                "npc_template_id": npc_template.id,
                "profile_json": npc_template.memory_profile_json or {},
                "memory_count": 0,
                "last_compacted_turn": 0,
            })
            continue

        # Idempotent: skip if seed memories already exist
        if memory_repo.has_seed_memories(session_id, npc_id):
            # Ensure scope exists too
            scope_repo.idempotent_create({
                "session_id": session_id,
                "npc_id": npc_id,
                "npc_template_id": npc_template.id,
                "profile_json": npc_template.memory_profile_json or {},
            })
            continue

        # Create scope row (idempotent)
        scope_repo.idempotent_create({
            "session_id": session_id,
            "npc_id": npc_id,
            "npc_template_id": npc_template.id,
            "profile_json": npc_template.memory_profile_json or {},
            "memory_count": len(bundle),
            "last_compacted_turn": 0,
        })

        source_ref = f"evt_seed_npc_{npc_template.code}"

        for entry in bundle:
            if not isinstance(entry, dict):
                continue

            memory_text = entry.get("text", entry.get("content", ""))
            if not memory_text:
                continue

            memory_data: Dict[str, Any] = {
                "session_id": session_id,
                "npc_id": npc_id,
                "npc_template_id": npc_template.id,
                # Legacy fields (populated for backward compatibility)
                "memory_type": entry.get("memory_type", "episodic"),
                "content": memory_text,
                "source_event_ids_json": [source_ref],
                "entities_json": entry.get("entities", []),
                "importance": entry.get("importance", entry.get("salience", 0.7)),
                "emotional_weight": entry.get("emotional_weight", 0.0),
                "confidence": entry.get("confidence", 1.0),
                "current_strength": 1.0,
                "created_turn": 0,
                "last_accessed_turn": 0,
                "recall_count": 0,
                # First-person / source-bound fields
                "memory_kind": "seed",
                "memory_text": memory_text,
                "short_summary": entry.get("short_summary"),
                "knowledge_source": entry.get("knowledge_source", "admin_seed"),
                "source_id": source_ref,
                "source_ref": source_ref,
                "source_turn_no": 0,
                "salience": entry.get("salience", entry.get("importance", 0.7)),
                "visibility": entry.get("visibility", "npc_private"),
                "status": "active",
                "tags_json": entry.get("tags", []),
                "entity_refs_json": entry.get("entities", entry.get("entity_refs", [])),
                "location_id": entry.get("location_id"),
                "world_time_text": entry.get("world_time_text"),
                "world_time_json": entry.get("world_time_json"),
            }
            memory_repo.create(memory_data)
            created_count += 1

    return created_count