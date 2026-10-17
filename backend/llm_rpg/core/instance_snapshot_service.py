"""
Instance Snapshot service helpers.

Provides snapshot JSON building, checksum computation, baseline/manual
snapshot creation, and snapshot apply (restore) logic. Snapshots capture
enough session state to be useful (session, session_state, player_state,
npc_states, quest_states, inventory, memory summary counts) without leaking
API keys or secrets.

Apply behaviour is feature-gated by INSTANCE_SNAPSHOT_ENABLED. When the
flag is on, ``apply_snapshot`` reverts mutable runtime tables from a
previously captured snapshot, creates a pre-apply checkpoint, and updates
PlaythroughInstance.current_snapshot_id / SessionModel.resume_snapshot_id.
Immutable audit / event / transaction logs are never modified.

The apply operation is all-or-nothing within a single database transaction.
All mutations use low-level ``db.add`` / ``db.delete`` / ``db.flush``
instead of BaseRepository helpers (which auto-commit per operation).  A
single ``db.commit()`` is issued at the end; on any exception the session
is rolled back so no partial restore can survive.
"""

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from ..core.feature_flags import instance_snapshot_enabled
from ..core.time_simulation import PHASE3_NAMESPACE
from ..core.content_runtime import CONTENT_NAMESPACE
from ..core.time_simulation_persistence import resolve_simulation_profile
from ..storage.models import (
    InstanceSnapshotModel,
    PlaythroughInstanceModel,
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
    SessionNPCStateModel,
    SessionQuestStateModel,
    SessionInventoryItemModel,
    MemorySummaryModel,
    NPCMemoryScopeModel,
    NPCPrivateMemoryModel,
    WorldModel,
)
from ..storage.repositories import (
    InstanceSnapshotRepository,
    PlaythroughInstanceRepository,
    SessionRepository,
    SessionStateRepository,
    SessionPlayerStateRepository,
    SessionNPCStateRepository,
    SessionQuestStateRepository,
    SessionInventoryItemRepository,
    MemorySummaryRepository,
    NPCMemoryScopeRepository,
    NPCPrivateMemoryRepository,
)


# Keys that must never appear in snapshot JSON payloads.
_SECRET_KEY_PATTERNS = (
    "api_key",
    "api_key_encrypted",
    "api_key_last4",
    "secret",
    "password",
    "password_hash",
    "token",
    "openai",
    "custom_api_key",
)


def _scrub_secrets(data: Any) -> Any:
    """Recursively remove dict entries whose keys match secret patterns."""
    if isinstance(data, dict):
        return {
            k: _scrub_secrets(v)
            for k, v in data.items()
            if not any(pat in k.lower() for pat in _SECRET_KEY_PATTERNS)
        }
    if isinstance(data, list):
        return [_scrub_secrets(item) for item in data]
    return data


class SnapshotApplyError(Exception):
    """Raised when a snapshot operation is unsupported or fails."""


class SnapshotRewindRefusedError(SnapshotApplyError):
    """Raised when snapshot rewind could corrupt a deterministic simulation."""


class ContentSnapshotUnsupportedError(SnapshotRewindRefusedError):
    """Content run-state is not represented by the legacy snapshot contract."""

    code = "CONTENT_SNAPSHOT_UNSUPPORTED"

    def __init__(self):
        super().__init__(f"{self.code}: content_v1 snapshots are not supported")


def _contains_content_namespace(value: Any) -> bool:
    if isinstance(value, dict):
        return CONTENT_NAMESPACE in value or any(
            _contains_content_namespace(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_content_namespace(child) for child in value)
    return False


def _refuse_content_snapshot_rewind(
    db: DBSession,
    session_id: str,
    snapshot_payload: Any = None,
) -> None:
    """Reject content_v1 snapshots before reading or applying mutable state."""
    if _contains_content_namespace(snapshot_payload):
        raise ContentSnapshotUnsupportedError()
    session = SessionRepository(db).get_by_id(session_id)
    if session is None:
        return
    session_state = SessionStateRepository(db).get_by_session(session_id)
    global_flags = getattr(session_state, "global_flags_json", None)
    if isinstance(global_flags, dict) and CONTENT_NAMESPACE in global_flags:
        raise ContentSnapshotUnsupportedError()
    world = db.get(WorldModel, session.world_id) if session.world_id else None
    ruleset = getattr(world, "ruleset_json", None)
    profile = ruleset.get("content_profile") if isinstance(ruleset, dict) else None
    if isinstance(profile, dict) and profile.get("id") == "content_v1":
        raise ContentSnapshotUnsupportedError()


def compute_checksum(snapshot_json: Dict[str, Any]) -> str:
    """
    Compute a deterministic SHA-256 checksum of the snapshot JSON.

    The JSON is serialized with sort_keys=True for determinism.
    """
    canonical = json.dumps(snapshot_json, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_session_snapshot_json(
    db: DBSession,
    session_id: str,
) -> Dict[str, Any]:
    """
    Build a snapshot JSON payload for a session's current state.

    Captures: session metadata, session_state, player_state, npc_states,
    quest_states, inventory items, memory summary counts, NPC memory scopes,
    and NPC private memories.
    All secret-bearing keys are scrubbed.

    Args:
        db: SQLAlchemy session.
        session_id: The session to snapshot.

    Returns:
        A dict suitable for InstanceSnapshotModel.snapshot_json.
    """
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)

    snapshot: Dict[str, Any] = {"session_id": session_id}

    if session is not None:
        snapshot["session"] = _scrub_secrets({
            "id": session.id,
            "user_id": session.user_id,
            "world_id": session.world_id,
            "status": session.status,
            "current_chapter_id": session.current_chapter_id,
            "session_type": session.session_type,
            "runtime_status": session.runtime_status,
            "playthrough_instance_id": session.playthrough_instance_id,
            "story_package_version_id": session.story_package_version_id,
        })

    # Session state
    session_state_repo = SessionStateRepository(db)
    ss = session_state_repo.get_by_session(session_id)
    if ss is not None:
        snapshot["session_state"] = _scrub_secrets({
            "current_time": ss.current_time,
            "time_phase": ss.time_phase,
            "current_location_id": ss.current_location_id,
            "active_mode": ss.active_mode,
            "global_flags_json": ss.global_flags_json,
        })

    # Player state
    player_state_repo = SessionPlayerStateRepository(db)
    ps = player_state_repo.get_by_session(session_id)
    if ps is not None:
        snapshot["player_state"] = _scrub_secrets({
            "realm_stage": ps.realm_stage,
            "hp": ps.hp,
            "max_hp": ps.max_hp,
            "stamina": ps.stamina,
            "spirit_power": ps.spirit_power,
            "relation_bias_json": ps.relation_bias_json,
            "conditions_json": ps.conditions_json,
        })

    # NPC states (list) — includes short_memory_summary and hidden_plan_state
    npc_state_repo = SessionNPCStateRepository(db)
    npc_states = npc_state_repo.get_by_session(session_id)
    snapshot["npc_states"] = [
        _scrub_secrets({
            "npc_template_id": ns.npc_template_id,
            "current_location_id": ns.current_location_id,
            "trust_score": ns.trust_score,
            "suspicion_score": ns.suspicion_score,
            "status_flags": ns.status_flags,
            "short_memory_summary": ns.short_memory_summary,
            "hidden_plan_state": ns.hidden_plan_state,
        })
        for ns in npc_states
    ]

    # Quest states (list) — includes revealed_at, reveal_source_event_id,
    # last_revealed_step_no
    quest_state_repo = SessionQuestStateRepository(db)
    quest_states = quest_state_repo.get_by_session(session_id)
    snapshot["quest_states"] = [
        _scrub_secrets({
            "quest_template_id": qs.quest_template_id,
            "current_step_no": qs.current_step_no,
            "progress_json": qs.progress_json,
            "status": qs.status,
            "player_visibility": qs.player_visibility,
            "revealed_at": qs.revealed_at.isoformat() if qs.revealed_at else None,
            "reveal_source_event_id": qs.reveal_source_event_id,
            "last_revealed_step_no": qs.last_revealed_step_no,
        })
        for qs in quest_states
    ]

    # Inventory items (list) — includes bound_flag
    inventory_repo = SessionInventoryItemRepository(db)
    inv_items = inventory_repo.get_by_session(session_id)
    snapshot["inventory"] = [
        _scrub_secrets({
            "item_template_id": ii.item_template_id,
            "owner_type": ii.owner_type,
            "owner_ref_id": ii.owner_ref_id,
            "quantity": ii.quantity,
            "durability": ii.durability,
            "bound_flag": ii.bound_flag,
        })
        for ii in inv_items
    ]

    # Memory summary counts (lightweight, not full text)
    memory_repo = MemorySummaryRepository(db)
    memory_summaries = memory_repo.get_by_session(session_id)
    snapshot["memory_summary_count"] = len(memory_summaries)

    # NPC memory scopes and private memories (P10-C Memory-first)
    npc_memory_scope_repo = NPCMemoryScopeRepository(db)
    npc_private_memory_repo = NPCPrivateMemoryRepository(db)

    npc_memory_scopes = []
    npc_private_memories = []

    for ns in npc_states:
        # Memory scopes
        scope = npc_memory_scope_repo.get_by_session_and_npc_template(
            session_id, ns.npc_template_id
        )
        if scope:
            npc_memory_scopes.append(_scrub_secrets({
                "npc_id": scope.npc_id,
                "npc_template_id": scope.npc_template_id,
                "profile_json": scope.profile_json,
                "forget_curve_json": scope.forget_curve_json,
                "memory_count": scope.memory_count,
            }))

        # Private memories for this NPC
        memories = npc_private_memory_repo.get_by_npc_template(
            session_id, ns.npc_template_id
        )
        for m in memories:
            npc_private_memories.append(_scrub_secrets({
                "npc_id": m.npc_id,
                "npc_template_id": m.npc_template_id,
                "memory_text": m.memory_text,
                "content": m.content,
                "memory_type": m.memory_type,
                "importance": m.importance,
                "emotional_weight": m.emotional_weight,
                "confidence": m.confidence,
                "current_strength": m.current_strength,
                "created_turn": m.created_turn,
                "last_accessed_turn": m.last_accessed_turn,
                "recall_count": m.recall_count,
                "knowledge_source": m.knowledge_source,
                "source_ref": m.source_ref,
                "source_turn_no": m.source_turn_no,
                "salience": m.salience,
                "tags_json": m.tags_json,
                "memory_kind": m.memory_kind,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }))

    snapshot["npc_memory_scopes"] = npc_memory_scopes
    snapshot["npc_private_memories"] = npc_private_memories

    return snapshot


def create_baseline_snapshot(
    db: DBSession,
    playthrough_instance_id: str,
    session_id: str,
    parent_snapshot_id: Optional[str] = None,
) -> InstanceSnapshotModel:
    """
    Create a baseline InstanceSnapshot for a playthrough instance.

    Builds the snapshot JSON from the current session state, computes
    a checksum, and persists the InstanceSnapshotModel.

    Args:
        db: SQLAlchemy session.
        playthrough_instance_id: The playthrough instance this snapshot belongs to.
        session_id: The session to snapshot.
        parent_snapshot_id: Optional parent snapshot ID.

    Returns:
        The newly created InstanceSnapshotModel.
    """
    # A baseline is a read-only creation-time capture, not a rewind. Content_v1
    # remains blocked in apply/restore because replaying its payload would rewind
    # state without re-running the event-time visibility and route invariants.
    snapshot_json = build_session_snapshot_json(db, session_id)
    checksum = compute_checksum(snapshot_json)

    repo = InstanceSnapshotRepository(db)
    return repo.create({
        "playthrough_instance_id": playthrough_instance_id,
        "session_id": session_id,
        "snapshot_kind": "baseline",
        "turn_no": 0,
        "snapshot_json": snapshot_json,
        "checksum": checksum,
        "parent_snapshot_id": parent_snapshot_id,
    })


def create_manual_snapshot(
    db: DBSession,
    playthrough_instance_id: str,
    session_id: str,
    turn_no: int = 0,
    parent_snapshot_id: Optional[str] = None,
    source_transaction_id: Optional[str] = None,
) -> InstanceSnapshotModel:
    """
    Create a manual InstanceSnapshot for a playthrough instance.

    Args:
        db: SQLAlchemy session.
        playthrough_instance_id: The playthrough instance.
        session_id: The session to snapshot.
        turn_no: Current turn number.
        parent_snapshot_id: Optional parent snapshot ID.
        source_transaction_id: Optional source turn transaction ID.

    Returns:
        The newly created InstanceSnapshotModel.
    """
    _refuse_content_snapshot_rewind(db, session_id)
    snapshot_json = build_session_snapshot_json(db, session_id)
    checksum = compute_checksum(snapshot_json)

    repo = InstanceSnapshotRepository(db)
    return repo.create({
        "playthrough_instance_id": playthrough_instance_id,
        "session_id": session_id,
        "snapshot_kind": "manual",
        "turn_no": turn_no,
        "snapshot_json": snapshot_json,
        "checksum": checksum,
        "parent_snapshot_id": parent_snapshot_id,
        "source_transaction_id": source_transaction_id,
    })


def _contains_phase3_namespace(value: Any) -> bool:
    if isinstance(value, dict):
        return PHASE3_NAMESPACE in value or any(
            _contains_phase3_namespace(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_phase3_namespace(child) for child in value)
    return False


def _refuse_phase3_snapshot_rewind(
    db: DBSession,
    session_id: str,
    snapshot_payload: Any,
) -> None:
    """Fail closed before mutation for phase-3 sessions or payloads."""
    if _contains_phase3_namespace(snapshot_payload):
        raise SnapshotRewindRefusedError(
            "Snapshot rewind is not supported for phase-3 simulation payloads"
        )

    session = SessionRepository(db).get_by_id(session_id)
    if session is None:
        return

    session_state = SessionStateRepository(db).get_by_session(session_id)
    global_flags = getattr(session_state, "global_flags_json", None)
    if isinstance(global_flags, dict) and PHASE3_NAMESPACE in global_flags:
        raise SnapshotRewindRefusedError(
            "Snapshot rewind is not supported for sessions with a phase-3 run marker"
        )

    if resolve_simulation_profile(db, session) is not None:
        raise SnapshotRewindRefusedError(
            "Snapshot rewind is not supported for phase-3 simulation worlds"
        )


def _parse_optional_datetime(value: Any) -> Optional[datetime]:
    """Parse a value that may be an ISO-format datetime string or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return None


def apply_snapshot(
    db: DBSession,
    snapshot_id: str,
) -> Dict[str, Any]:
    """
    Apply an InstanceSnapshot payload back to session runtime tables.

    All-or-nothing: the entire operation runs inside a nested transaction
    (savepoint). Mutations use ``db.add`` / ``db.delete`` / ``db.flush``
    (never BaseRepository helpers which auto-commit). The nested transaction
    ensures atomicity: on any exception, the savepoint is rolled back so no
    partial restore can survive. A final ``db.commit()`` is issued only after
    every step succeeds.

    Steps (all gated on INSTANCE_SNAPSHOT_ENABLED):
    1. Load the snapshot; reject if not found.
    2. Verify checksum; reject on mismatch.
    3. Begin a nested transaction (savepoint).
    4. Create a pre-apply checkpoint snapshot of current state.
     5. Overwrite mutable runtime tables from snapshot JSON:
        session_state, player_state, npc_states, quest_states, inventory,
        NPC memory scopes, NPC private memories.
    6. Update PlaythroughInstance.current_snapshot_id and
       SessionModel.resume_snapshot_id.
    7. Commit the nested transaction, then commit the outer transaction.
    8. Return result dict.

    Immutable tables (event_logs, turn_transactions, model_call_logs, etc.)
    are never modified.

    Raises:
        SnapshotApplyError: If flag off, snapshot not found, or checksum mismatch.
        SnapshotRewindRefusedError: If phase-3 state or payload is detected.
    """
    if not instance_snapshot_enabled():
        raise SnapshotApplyError("INSTANCE_SNAPSHOT_ENABLED is off; apply not allowed")

    snap_repo = InstanceSnapshotRepository(db)
    snap = snap_repo.get_by_id(snapshot_id)
    if snap is None:
        raise SnapshotApplyError(f"Snapshot not found: {snapshot_id}")

    session_id = snap.snapshot_json.get("session_id") or snap.session_id
    _refuse_content_snapshot_rewind(db, session_id, snap.snapshot_json)
    _refuse_phase3_snapshot_rewind(db, session_id, snap.snapshot_json)
    if snap.session_id != session_id:
        _refuse_content_snapshot_rewind(db, snap.session_id, snap.snapshot_json)
        _refuse_phase3_snapshot_rewind(db, snap.session_id, snap.snapshot_json)

    expected_checksum = compute_checksum(snap.snapshot_json)
    if snap.checksum != expected_checksum:
        raise SnapshotApplyError(
            f"Checksum mismatch for snapshot {snapshot_id}: "
            f"stored={snap.checksum}, computed={expected_checksum}"
        )

    pi_id = snap.playthrough_instance_id

    with db.begin_nested():
        checkpoint_json = build_session_snapshot_json(db, session_id)
        checkpoint_checksum = compute_checksum(checkpoint_json)
        checkpoint = InstanceSnapshotModel(
            playthrough_instance_id=pi_id,
            session_id=session_id,
            snapshot_kind="pre_apply_checkpoint",
            turn_no=snap.turn_no,
            snapshot_json=checkpoint_json,
            checksum=checkpoint_checksum,
            parent_snapshot_id=snapshot_id,
        )
        db.add(checkpoint)
        db.flush()

        payload = snap.snapshot_json

        ss_data = payload.get("session_state")
        if ss_data is not None:
            existing_ss = (
                db.query(SessionStateModel)
                .filter(SessionStateModel.session_id == session_id)
                .first()
            )
            if existing_ss is not None:
                existing_ss.current_time = ss_data.get("current_time")
                existing_ss.time_phase = ss_data.get("time_phase")
                existing_ss.current_location_id = ss_data.get("current_location_id")
                existing_ss.active_mode = ss_data.get("active_mode")
                existing_ss.global_flags_json = ss_data.get("global_flags_json")
            else:
                db.add(SessionStateModel(
                    session_id=session_id,
                    current_time=ss_data.get("current_time"),
                    time_phase=ss_data.get("time_phase"),
                    current_location_id=ss_data.get("current_location_id"),
                    active_mode=ss_data.get("active_mode"),
                    global_flags_json=ss_data.get("global_flags_json"),
                ))

        ps_data = payload.get("player_state")
        if ps_data is not None:
            existing_ps = (
                db.query(SessionPlayerStateModel)
                .filter(SessionPlayerStateModel.session_id == session_id)
                .first()
            )
            if existing_ps is not None:
                existing_ps.realm_stage = ps_data.get("realm_stage")
                existing_ps.hp = ps_data.get("hp")
                existing_ps.max_hp = ps_data.get("max_hp")
                existing_ps.stamina = ps_data.get("stamina")
                existing_ps.spirit_power = ps_data.get("spirit_power")
                existing_ps.relation_bias_json = ps_data.get("relation_bias_json")
                existing_ps.conditions_json = ps_data.get("conditions_json")
            else:
                db.add(SessionPlayerStateModel(
                    session_id=session_id,
                    realm_stage=ps_data.get("realm_stage"),
                    hp=ps_data.get("hp"),
                    max_hp=ps_data.get("max_hp"),
                    stamina=ps_data.get("stamina"),
                    spirit_power=ps_data.get("spirit_power"),
                    relation_bias_json=ps_data.get("relation_bias_json"),
                    conditions_json=ps_data.get("conditions_json"),
                ))

        for existing_npc in db.query(SessionNPCStateModel).filter(
            SessionNPCStateModel.session_id == session_id
        ).all():
            db.delete(existing_npc)
        db.flush()
        for ns_data in payload.get("npc_states", []):
            db.add(SessionNPCStateModel(
                session_id=session_id,
                npc_template_id=ns_data["npc_template_id"],
                current_location_id=ns_data.get("current_location_id"),
                trust_score=ns_data.get("trust_score", 50),
                suspicion_score=ns_data.get("suspicion_score", 0),
                status_flags=ns_data.get("status_flags", {}),
                short_memory_summary=ns_data.get("short_memory_summary"),
                hidden_plan_state=ns_data.get("hidden_plan_state"),
            ))

        for existing_qs in db.query(SessionQuestStateModel).filter(
            SessionQuestStateModel.session_id == session_id
        ).all():
            db.delete(existing_qs)
        db.flush()
        for qs_data in payload.get("quest_states", []):
            db.add(SessionQuestStateModel(
                session_id=session_id,
                quest_template_id=qs_data["quest_template_id"],
                current_step_no=qs_data.get("current_step_no", 1),
                progress_json=qs_data.get("progress_json", {}),
                status=qs_data.get("status", "active"),
                player_visibility=qs_data.get("player_visibility", "hidden"),
                revealed_at=_parse_optional_datetime(qs_data.get("revealed_at")),
                reveal_source_event_id=qs_data.get("reveal_source_event_id"),
                last_revealed_step_no=qs_data.get("last_revealed_step_no"),
            ))

        for existing_inv in db.query(SessionInventoryItemModel).filter(
            SessionInventoryItemModel.session_id == session_id
        ).all():
            db.delete(existing_inv)
        db.flush()
        for inv_data in payload.get("inventory", []):
            db.add(SessionInventoryItemModel(
                session_id=session_id,
                item_template_id=inv_data["item_template_id"],
                owner_type=inv_data.get("owner_type", "player"),
                owner_ref_id=inv_data.get("owner_ref_id"),
                quantity=inv_data.get("quantity", 1),
                durability=inv_data.get("durability"),
                bound_flag=inv_data.get("bound_flag", False),
            ))

        # NPC memory scopes and private memories (P10-C Memory-first)
        for existing_scope in db.query(NPCMemoryScopeModel).filter(
            NPCMemoryScopeModel.session_id == session_id
        ).all():
            db.delete(existing_scope)

        for existing_mem in db.query(NPCPrivateMemoryModel).filter(
            NPCPrivateMemoryModel.session_id == session_id
        ).all():
            db.delete(existing_mem)
        db.flush()

        for scope_data in payload.get("npc_memory_scopes", []):
            db.add(NPCMemoryScopeModel(
                session_id=session_id,
                npc_id=scope_data["npc_id"],
                npc_template_id=scope_data.get("npc_template_id"),
                profile_json=scope_data.get("profile_json"),
                forget_curve_json=scope_data.get("forget_curve_json"),
                memory_count=scope_data.get("memory_count", 0),
            ))

        for mem_data in payload.get("npc_private_memories", []):
            db.add(NPCPrivateMemoryModel(
                session_id=session_id,
                npc_id=mem_data["npc_id"],
                npc_template_id=mem_data.get("npc_template_id"),
                memory_text=mem_data.get("memory_text"),
                content=mem_data.get("content", ""),
                memory_type=mem_data.get("memory_type", "episodic"),
                importance=mem_data.get("importance", 0.5),
                emotional_weight=mem_data.get("emotional_weight", 0.0),
                confidence=mem_data.get("confidence", 1.0),
                current_strength=mem_data.get("current_strength", 1.0),
                created_turn=mem_data.get("created_turn", 0),
                last_accessed_turn=mem_data.get("last_accessed_turn", 0),
                recall_count=mem_data.get("recall_count", 0),
                knowledge_source=mem_data.get("knowledge_source"),
                source_ref=mem_data.get("source_ref"),
                source_turn_no=mem_data.get("source_turn_no"),
                salience=mem_data.get("salience", 0.5),
                tags_json=mem_data.get("tags_json"),
                memory_kind=mem_data.get("memory_kind"),
            ))
        db.flush()

        pi = db.query(PlaythroughInstanceModel).filter(
            PlaythroughInstanceModel.id == pi_id
        ).first()
        if pi is not None:
            pi.current_snapshot_id = snapshot_id

        session_obj = db.query(SessionModel).filter(
            SessionModel.id == session_id
        ).first()
        if session_obj is not None:
            session_obj.resume_snapshot_id = snapshot_id

    db.commit()

    return {
        "applied_snapshot_id": snapshot_id,
        "checkpoint_snapshot_id": checkpoint.id,
        "session_id": session_id,
        "playthrough_instance_id": pi_id,
    }


def restore_snapshot(
    db: DBSession,
    snapshot_id: str,
) -> Dict[str, Any]:
    """
    Restore (apply) an InstanceSnapshot to session runtime state.

    When INSTANCE_SNAPSHOT_ENABLED is on, this applies the snapshot payload
    to the mutable runtime tables (session_state, player_state, npc_states,
    quest_states, inventory), creates a pre-apply checkpoint, and updates
    instance/session pointers.

    When the flag is off, ordinary sessions fall back to read-only verification
    (returns snapshot_json, checksum, snapshot_kind without mutation). Phase-3
    snapshots are refused in either mode rather than presented as restored.

    Raises:
        ValueError: If snapshot not found (read-only path).
        SnapshotApplyError: If flag on and checksum mismatch or other apply error.
        SnapshotRewindRefusedError: If phase-3 state or payload is detected.
    """
    if instance_snapshot_enabled():
        try:
            result = apply_snapshot(db, snapshot_id)
        except SnapshotApplyError as e:
            if "not found" in str(e).lower():
                raise ValueError(str(e))
            raise
        snap_repo = InstanceSnapshotRepository(db)
        snap = snap_repo.get_by_id(snapshot_id)
        result["snapshot_kind"] = snap.snapshot_kind if snap else None
        result["turn_no"] = snap.turn_no if snap else None
        result["checksum"] = snap.checksum if snap else None
        result["snapshot_json"] = snap.snapshot_json if snap else None
        return result

    repo = InstanceSnapshotRepository(db)
    snap = repo.get_by_id(snapshot_id)
    if snap is None:
        raise ValueError(f"Snapshot not found: {snapshot_id}")

    session_id = snap.snapshot_json.get("session_id") or snap.session_id
    _refuse_content_snapshot_rewind(db, session_id, snap.snapshot_json)
    _refuse_phase3_snapshot_rewind(db, session_id, snap.snapshot_json)
    if snap.session_id != session_id:
        _refuse_content_snapshot_rewind(db, snap.session_id, snap.snapshot_json)
        _refuse_phase3_snapshot_rewind(db, snap.session_id, snap.snapshot_json)

    return {
        "snapshot_json": snap.snapshot_json,
        "checksum": snap.checksum,
        "snapshot_kind": snap.snapshot_kind,
        "turn_no": snap.turn_no,
    }
