"""
Focused tests for InstanceSnapshot apply (restore) behaviour.

Covers:
- successful apply restores mutable runtime tables
- checksum mismatch rejects the apply
- INSTANCE_SNAPSHOT_ENABLED=false raises SnapshotApplyError
- pre-apply checkpoint snapshot is created before overwrite
- immutable audit/event/transaction logs are not mutated
- PlaythroughInstance.current_snapshot_id and SessionModel.resume_snapshot_id
  are updated after apply
- restore_snapshot delegates to apply_snapshot when flag on
- restore_snapshot falls back to read-only when flag off
- previously-missing fields are captured and restored:
  short_memory_summary, hidden_plan_state, bound_flag,
  revealed_at, reveal_source_event_id, last_revealed_step_no
- apply_snapshot is all-or-nothing: rollback on mid-apply failure
- compute_checksum is deterministic and sensitive to payload changes
"""

import os
import pytest
from datetime import datetime
from unittest.mock import patch
from sqlalchemy.orm import Session as DBSession, sessionmaker

from llm_rpg.storage.models import (
    WorldModel,
    UserModel,
    SessionModel,
    PlaythroughInstanceModel,
    InstanceSnapshotModel,
    SessionStateModel,
    SessionPlayerStateModel,
    SessionNPCStateModel,
    SessionQuestStateModel,
    SessionInventoryItemModel,
    EventLogModel,
    TurnTransactionModel,
    NPCTemplateModel,
    LocationModel,
    ItemTemplateModel,
    QuestTemplateModel,
    NPCMemoryScopeModel,
    NPCPrivateMemoryModel,
    generate_uuid,
)
from llm_rpg.storage.repositories import (
    WorldRepository,
    SessionRepository,
    PlaythroughInstanceRepository,
    InstanceSnapshotRepository,
    SessionStateRepository,
    SessionPlayerStateRepository,
    SessionNPCStateRepository,
    SessionQuestStateRepository,
    SessionInventoryItemRepository,
    EventLogRepository,
    TurnTransactionRepository,
    NPCTemplateRepository,
    LocationRepository,
    ItemTemplateRepository,
    QuestTemplateRepository,
    NPCMemoryScopeRepository,
    NPCPrivateMemoryRepository,
)
from llm_rpg.core.instance_snapshot_service import (
    build_session_snapshot_json,
    compute_checksum,
    create_baseline_snapshot,
    create_manual_snapshot,
    apply_snapshot,
    restore_snapshot,
    SnapshotApplyError,
    _SECRET_KEY_PATTERNS,
)
from llm_rpg.core.feature_flags import instance_snapshot_enabled


def _seed_world(db: DBSession) -> WorldModel:
    return WorldRepository(db).create({
        "code": f"apply-world-{generate_uuid()[:8]}",
        "name": "Apply Test World",
    })


def _seed_location(db: DBSession, world_id: str, code: str = "loc-apply") -> LocationModel:
    return LocationRepository(db).create({
        "world_id": world_id, "code": code, "name": f"Location {code}",
    })


def _seed_npc_template(db: DBSession, world_id: str, code: str = "npc-apply") -> NPCTemplateModel:
    return NPCTemplateRepository(db).create({
        "world_id": world_id, "code": code, "name": f"NPC {code}",
    })


def _seed_item_template(db: DBSession, world_id: str, code: str = "item-apply") -> ItemTemplateModel:
    return ItemTemplateRepository(db).create({
        "world_id": world_id, "code": code, "name": f"Item {code}",
    })


def _seed_quest_template(db: DBSession, world_id: str, code: str = "quest-apply") -> QuestTemplateModel:
    return QuestTemplateRepository(db).create({
        "world_id": world_id, "code": code, "name": f"Quest {code}",
    })


def _setup_session_with_state(db: DBSession, world: WorldModel) -> dict:
    """Create a session with full runtime state (session_state, player_state, npc, quest, inventory)."""
    loc = _seed_location(db, world.id)
    npc_tmpl = _seed_npc_template(db, world.id)
    item_tmpl = _seed_item_template(db, world.id)
    quest_tmpl = _seed_quest_template(db, world.id)

    session_repo = SessionRepository(db)
    session = session_repo.create({
        "user_id": "user-apply-test",
        "world_id": world.id,
        "status": "active",
        "current_chapter_id": None,
        "session_type": "instance",
        "runtime_status": "running",
    })

    ss_repo = SessionStateRepository(db)
    ss_repo.create({
        "session_id": session.id,
        "current_time": "辰时",
        "time_phase": "morning",
        "current_location_id": loc.id,
        "active_mode": "exploration",
        "global_flags_json": {"flag_a": True},
    })

    ps_repo = SessionPlayerStateRepository(db)
    ps_repo.create({
        "session_id": session.id,
        "realm_stage": "炼气一层",
        "hp": 100,
        "max_hp": 100,
        "stamina": 80,
        "spirit_power": 50,
        "relation_bias_json": {"npc-001": 0.5},
        "conditions_json": ["hungry"],
    })

    npc_repo = SessionNPCStateRepository(db)
    npc_repo.create({
        "session_id": session.id,
        "npc_template_id": npc_tmpl.id,
        "current_location_id": loc.id,
        "trust_score": 60,
        "suspicion_score": 5,
        "status_flags": {"met_player": True},
        "short_memory_summary": "Recalls meeting the player at dawn",
        "hidden_plan_state": "Planning to reveal secret at midnight",
    })

    quest_repo = SessionQuestStateRepository(db)
    revealed_ts = datetime(2025, 1, 15, 10, 30, 0)
    quest_repo.create({
        "session_id": session.id,
        "quest_template_id": quest_tmpl.id,
        "current_step_no": 2,
        "progress_json": {"steps_done": [1]},
        "status": "active",
        "player_visibility": "discovered",
        "revealed_at": revealed_ts,
        "reveal_source_event_id": "event-reveal-001",
        "last_revealed_step_no": 2,
    })

    inv_repo = SessionInventoryItemRepository(db)
    inv_repo.create({
        "session_id": session.id,
        "item_template_id": item_tmpl.id,
        "owner_type": "player",
        "owner_ref_id": None,
        "quantity": 3,
        "durability": 80,
        "bound_flag": True,
    })

    pi_repo = PlaythroughInstanceRepository(db)
    pi = pi_repo.create({
        "world_id": world.id,
        "instance_status": "active",
        "root_session_id": session.id,
    })
    session_repo.update(session.id, {"playthrough_instance_id": pi.id})

    return {
        "session": session,
        "playthrough_instance": pi,
        "location": loc,
        "npc_template": npc_tmpl,
        "item_template": item_tmpl,
        "quest_template": quest_tmpl,
    }


class TestApplySnapshotSuccessful:
    def test_apply_restores_session_state(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        ss_repo = SessionStateRepository(db_session)
        ss = ss_repo.get_by_session(setup["session"].id)
        ss_repo.update(ss.id, {
            "current_time": "午时",
            "time_phase": "afternoon",
            "active_mode": "combat",
            "global_flags_json": {"flag_a": False, "flag_b": True},
        })

        result = apply_snapshot(db_session, snap.id)
        assert result["applied_snapshot_id"] == snap.id
        assert result["checkpoint_snapshot_id"] is not None
        assert result["session_id"] == setup["session"].id

        ss_after = ss_repo.get_by_session(setup["session"].id)
        assert ss_after.current_time == "辰时"
        assert ss_after.time_phase == "morning"
        assert ss_after.active_mode == "exploration"
        assert ss_after.global_flags_json == {"flag_a": True}

    def test_apply_restores_player_state(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        ps_repo = SessionPlayerStateRepository(db_session)
        ps = ps_repo.get_by_session(setup["session"].id)
        ps_repo.update(ps.id, {"hp": 30, "stamina": 10})

        apply_snapshot(db_session, snap.id)

        ps_after = ps_repo.get_by_session(setup["session"].id)
        assert ps_after.hp == 100
        assert ps_after.stamina == 80
        assert ps_after.realm_stage == "炼气一层"

    def test_apply_restores_npc_states(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        npc_repo = SessionNPCStateRepository(db_session)
        npc = npc_repo.get_by_session_and_npc(setup["session"].id, setup["npc_template"].id)
        npc_repo.update(npc.id, {"trust_score": 10, "suspicion_score": 99})

        apply_snapshot(db_session, snap.id)

        npc_after = npc_repo.get_by_session_and_npc(setup["session"].id, setup["npc_template"].id)
        assert npc_after is not None
        assert npc_after.trust_score == 60
        assert npc_after.suspicion_score == 5

    def test_apply_restores_quest_states(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        quest_repo = SessionQuestStateRepository(db_session)
        quest = quest_repo.get_by_session_and_quest(setup["session"].id, setup["quest_template"].id)
        quest_repo.update(quest.id, {"current_step_no": 5, "status": "completed"})

        apply_snapshot(db_session, snap.id)

        quest_after = quest_repo.get_by_session_and_quest(setup["session"].id, setup["quest_template"].id)
        assert quest_after is not None
        assert quest_after.current_step_no == 2
        assert quest_after.status == "active"
        assert quest_after.player_visibility == "discovered"

    def test_apply_restores_inventory(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        inv_repo = SessionInventoryItemRepository(db_session)
        items_before = inv_repo.get_by_session(setup["session"].id)
        assert len(items_before) == 1
        inv_repo.update(items_before[0].id, {"quantity": 10})

        apply_snapshot(db_session, snap.id)

        items_after = inv_repo.get_by_session(setup["session"].id)
        assert len(items_after) == 1
        assert items_after[0].quantity == 3
        assert items_after[0].durability == 80

    def test_apply_updates_instance_current_snapshot_id(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        pi_repo = PlaythroughInstanceRepository(db_session)
        pi_repo.update(setup["playthrough_instance"].id, {"current_snapshot_id": None})

        apply_snapshot(db_session, snap.id)

        pi_after = pi_repo.get_by_id(setup["playthrough_instance"].id)
        assert pi_after.current_snapshot_id == snap.id

    def test_apply_updates_session_resume_snapshot_id(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        apply_snapshot(db_session, snap.id)

        session_repo = SessionRepository(db_session)
        session_after = session_repo.get_by_id(setup["session"].id)
        assert session_after.resume_snapshot_id == snap.id


class TestApplySnapshotChecksumMismatch:
    def test_checksum_mismatch_rejects_apply(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        loc = _seed_location(db_session, world.id)

        session_repo = SessionRepository(db_session)
        session = session_repo.create({
            "user_id": "user-csum-test",
            "world_id": world.id,
            "status": "active",
        })

        snap_repo = InstanceSnapshotRepository(db_session)
        snapshot_json = {"session_id": session.id, "session_state": {"active_mode": "exploration"}}
        bad_checksum = "0000000000000000000000000000000000000000000000000000000000000000"

        pi_repo = PlaythroughInstanceRepository(db_session)
        pi = pi_repo.create({
            "world_id": world.id,
            "root_session_id": session.id,
            "instance_status": "active",
        })
        session_repo.update(session.id, {"playthrough_instance_id": pi.id})

        snap = snap_repo.create({
            "playthrough_instance_id": pi.id,
            "session_id": session.id,
            "snapshot_kind": "manual",
            "turn_no": 3,
            "snapshot_json": snapshot_json,
            "checksum": bad_checksum,
        })

        with pytest.raises(SnapshotApplyError, match="Checksum mismatch"):
            apply_snapshot(db_session, snap.id)


class TestApplySnapshotFlagOff:
    def test_apply_raises_when_flag_off(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")
        world = _seed_world(db_session)
        loc = _seed_location(db_session, world.id)

        session_repo = SessionRepository(db_session)
        session = session_repo.create({
            "user_id": "user-flag-off",
            "world_id": world.id,
            "status": "active",
        })

        pi_repo = PlaythroughInstanceRepository(db_session)
        pi = pi_repo.create({
            "world_id": world.id,
            "root_session_id": session.id,
            "instance_status": "active",
        })
        session_repo.update(session.id, {"playthrough_instance_id": pi.id})

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=pi.id,
            session_id=session.id,
        )

        with pytest.raises(SnapshotApplyError, match="INSTANCE_SNAPSHOT_ENABLED is off"):
            apply_snapshot(db_session, snap.id)


class TestApplySnapshotCheckpoint:
    def test_checkpoint_created_before_apply(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        ss_repo = SessionStateRepository(db_session)
        ss = ss_repo.get_by_session(setup["session"].id)
        ss_repo.update(ss.id, {"active_mode": "combat"})

        result = apply_snapshot(db_session, snap.id)
        checkpoint_id = result["checkpoint_snapshot_id"]

        snap_repo = InstanceSnapshotRepository(db_session)
        checkpoint = snap_repo.get_by_id(checkpoint_id)
        assert checkpoint is not None
        assert checkpoint.snapshot_kind == "pre_apply_checkpoint"
        assert checkpoint.parent_snapshot_id == snap.id
        assert checkpoint.checksum is not None

        assert checkpoint.snapshot_json.get("session_state", {}).get("active_mode") == "combat"

    def test_snapshot_history_not_deleted_on_apply(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap1 = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )
        snap2 = create_manual_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
            turn_no=5,
        )

        snap_repo = InstanceSnapshotRepository(db_session)
        snapshots_before = snap_repo.list_by_instance(setup["playthrough_instance"].id)
        assert len(snapshots_before) == 2

        apply_snapshot(db_session, snap1.id)

        snapshots_after = snap_repo.list_by_instance(setup["playthrough_instance"].id)
        assert len(snapshots_after) == 3

        assert snap_repo.get_by_id(snap1.id) is not None
        assert snap_repo.get_by_id(snap2.id) is not None


class TestApplySnapshotNoAuditMutation:
    def test_event_logs_not_mutated_on_apply(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        event_repo = EventLogRepository(db_session)
        event = event_repo.create({
            "session_id": setup["session"].id,
            "turn_no": 1,
            "event_type": "player_action",
            "input_text": "观察四周",
        })
        event_id = event.id

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        ps_repo = SessionPlayerStateRepository(db_session)
        ps = ps_repo.get_by_session(setup["session"].id)
        ps_repo.update(ps.id, {"hp": 30})

        apply_snapshot(db_session, snap.id)

        event_after = event_repo.get_by_id(event_id)
        assert event_after is not None
        assert event_after.event_type == "player_action"
        assert event_after.input_text == "观察四周"

    def test_turn_transactions_not_mutated_on_apply(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        from datetime import datetime as dt
        txn_repo = TurnTransactionRepository(db_session)
        txn = txn_repo.create({
            "session_id": setup["session"].id,
            "turn_no": 1,
            "idempotency_key": f"idemp-{generate_uuid()[:8]}",
            "status": "committed",
            "started_at": dt.now(),
            "committed_at": dt.now(),
        })
        txn_id = txn.id

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        apply_snapshot(db_session, snap.id)

        txn_after = txn_repo.get_by_id(txn_id)
        assert txn_after is not None
        assert txn_after.status == "committed"


class TestRestoreSnapshotDelegation:
    def test_restore_delegates_to_apply_when_flag_on(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        ps_repo = SessionPlayerStateRepository(db_session)
        ps = ps_repo.get_by_session(setup["session"].id)
        ps_repo.update(ps.id, {"hp": 30})

        result = restore_snapshot(db_session, snap.id)

        assert result["applied_snapshot_id"] == snap.id
        assert result["checkpoint_snapshot_id"] is not None
        assert result["snapshot_kind"] == "baseline"
        assert result["turn_no"] == 0

        ps_after = ps_repo.get_by_session(setup["session"].id)
        assert ps_after.hp == 100

    def test_restore_fallback_read_only_when_flag_off(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")
        world = _seed_world(db_session)
        loc = _seed_location(db_session, world.id)

        session_repo = SessionRepository(db_session)
        session = session_repo.create({
            "user_id": "user-restore-readonly",
            "world_id": world.id,
            "status": "active",
        })

        pi_repo = PlaythroughInstanceRepository(db_session)
        pi = pi_repo.create({
            "world_id": world.id,
            "root_session_id": session.id,
            "instance_status": "active",
        })
        session_repo.update(session.id, {"playthrough_instance_id": pi.id})

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=pi.id,
            session_id=session.id,
        )

        result = restore_snapshot(db_session, snap.id)

        assert "snapshot_json" in result
        assert "checksum" in result
        assert result["snapshot_kind"] == "baseline"
        assert "applied_snapshot_id" not in result


class TestApplySnapshotNotFound:
    def test_apply_raises_for_nonexistent_snapshot(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        with pytest.raises(SnapshotApplyError, match="Snapshot not found"):
            apply_snapshot(db_session, "nonexistent-id")


# ---------------------------------------------------------------------------
# NEW: Field preservation tests (previously-missing mutable fields)
# ---------------------------------------------------------------------------

class TestFieldPreservationOnApply:
    """Verify that apply_snapshot restores fields that were previously missing
    from the snapshot payload: short_memory_summary, hidden_plan_state,
    bound_flag, revealed_at, reveal_source_event_id, last_revealed_step_no."""

    def test_npc_short_memory_summary_preserved(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        npc_repo = SessionNPCStateRepository(db_session)
        npc = npc_repo.get_by_session_and_npc(setup["session"].id, setup["npc_template"].id)
        npc_repo.update(npc.id, {"short_memory_summary": "OVERWRITTEN"})

        apply_snapshot(db_session, snap.id)

        npc_after = npc_repo.get_by_session_and_npc(setup["session"].id, setup["npc_template"].id)
        assert npc_after.short_memory_summary == "Recalls meeting the player at dawn"

    def test_npc_hidden_plan_state_preserved(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        npc_repo = SessionNPCStateRepository(db_session)
        npc = npc_repo.get_by_session_and_npc(setup["session"].id, setup["npc_template"].id)
        npc_repo.update(npc.id, {"hidden_plan_state": "OVERWRITTEN"})

        apply_snapshot(db_session, snap.id)

        npc_after = npc_repo.get_by_session_and_npc(setup["session"].id, setup["npc_template"].id)
        assert npc_after.hidden_plan_state == "Planning to reveal secret at midnight"

    def test_inventory_bound_flag_preserved(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        inv_repo = SessionInventoryItemRepository(db_session)
        items = inv_repo.get_by_session(setup["session"].id)
        assert items[0].bound_flag is True
        inv_repo.update(items[0].id, {"bound_flag": False})

        apply_snapshot(db_session, snap.id)

        items_after = inv_repo.get_by_session(setup["session"].id)
        assert items_after[0].bound_flag is True

    def test_quest_revealed_at_preserved(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        quest_repo = SessionQuestStateRepository(db_session)
        quest = quest_repo.get_by_session_and_quest(setup["session"].id, setup["quest_template"].id)
        quest_repo.update(quest.id, {"revealed_at": datetime(2099, 12, 31, 23, 59, 59)})

        apply_snapshot(db_session, snap.id)

        quest_after = quest_repo.get_by_session_and_quest(setup["session"].id, setup["quest_template"].id)
        assert quest_after.revealed_at is not None
        assert quest_after.revealed_at.year == 2025
        assert quest_after.revealed_at.month == 1
        assert quest_after.revealed_at.day == 15

    def test_quest_reveal_source_event_id_preserved(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        quest_repo = SessionQuestStateRepository(db_session)
        quest = quest_repo.get_by_session_and_quest(setup["session"].id, setup["quest_template"].id)
        quest_repo.update(quest.id, {"reveal_source_event_id": "OVERWRITTEN"})

        apply_snapshot(db_session, snap.id)

        quest_after = quest_repo.get_by_session_and_quest(setup["session"].id, setup["quest_template"].id)
        assert quest_after.reveal_source_event_id == "event-reveal-001"

    def test_quest_last_revealed_step_no_preserved(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        quest_repo = SessionQuestStateRepository(db_session)
        quest = quest_repo.get_by_session_and_quest(setup["session"].id, setup["quest_template"].id)
        quest_repo.update(quest.id, {"last_revealed_step_no": 99})

        apply_snapshot(db_session, snap.id)

        quest_after = quest_repo.get_by_session_and_quest(setup["session"].id, setup["quest_template"].id)
        assert quest_after.last_revealed_step_no == 2

    def test_snapshot_json_includes_all_npc_fields(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snapshot_json = build_session_snapshot_json(db_session, setup["session"].id)
        npc_entries = snapshot_json["npc_states"]
        assert len(npc_entries) == 1
        assert "short_memory_summary" in npc_entries[0]
        assert "hidden_plan_state" in npc_entries[0]
        assert npc_entries[0]["short_memory_summary"] == "Recalls meeting the player at dawn"
        assert npc_entries[0]["hidden_plan_state"] == "Planning to reveal secret at midnight"

    def test_snapshot_json_includes_all_inventory_fields(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snapshot_json = build_session_snapshot_json(db_session, setup["session"].id)
        inv_entries = snapshot_json["inventory"]
        assert len(inv_entries) == 1
        assert "bound_flag" in inv_entries[0]
        assert inv_entries[0]["bound_flag"] is True

    def test_snapshot_json_includes_all_quest_fields(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        snapshot_json = build_session_snapshot_json(db_session, setup["session"].id)
        quest_entries = snapshot_json["quest_states"]
        assert len(quest_entries) == 1
        assert "revealed_at" in quest_entries[0]
        assert "reveal_source_event_id" in quest_entries[0]
        assert "last_revealed_step_no" in quest_entries[0]
        assert quest_entries[0]["reveal_source_event_id"] == "event-reveal-001"
        assert quest_entries[0]["last_revealed_step_no"] == 2


# ---------------------------------------------------------------------------
# NEW: Rollback / atomicity tests
# ---------------------------------------------------------------------------

class TestApplySnapshotAtomicity:
    """Verify that apply_snapshot is all-or-nothing: on mid-apply failure,
    no partial changes survive.

    These tests use a dedicated DB session (separate from the conftest-
    managed one) because apply_snapshot calls db.commit()/db.rollback()
    which would deassociate the conftest wrapping transaction.
    """

    @pytest.fixture
    def _rollback_db(self, engine, monkeypatch):
        """Yield a dedicated session for rollback tests; clean up afterwards."""
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        conn = engine.connect()
        txn = conn.begin()
        sess = sessionmaker(bind=conn)()
        yield sess
        sess.close()
        txn.rollback()
        conn.close()

    def test_rollback_on_mid_apply_failure(self, _rollback_db):
        db = _rollback_db
        world = _seed_world(db)
        setup = _setup_session_with_state(db, world)
        session_id = setup["session"].id
        npc_template_id = setup["npc_template"].id

        snap = create_baseline_snapshot(
            db,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=session_id,
        )

        ss_repo = SessionStateRepository(db)
        ss_repo.update(ss_repo.get_by_session(session_id).id, {"active_mode": "combat"})

        npc_repo = SessionNPCStateRepository(db)
        npc_repo.update(
            npc_repo.get_by_session_and_npc(session_id, npc_template_id).id,
            {"trust_score": 99},
        )

        with patch.object(
            SessionQuestStateModel, "__init__",
            side_effect=RuntimeError("simulated mid-apply failure"),
        ):
            with pytest.raises(RuntimeError, match="simulated mid-apply failure"):
                apply_snapshot(db, snap.id)

        # After rollback, re-query to verify no partial restore survived
        ss_after = SessionStateRepository(db).get_by_session(session_id)
        assert ss_after is not None
        assert ss_after.active_mode == "combat"

        npc_after = SessionNPCStateRepository(db).get_by_session_and_npc(session_id, npc_template_id)
        assert npc_after is not None
        assert npc_after.trust_score == 99

    def test_no_checkpoint_persists_on_rollback(self, _rollback_db):
        db = _rollback_db
        world = _seed_world(db)
        setup = _setup_session_with_state(db, world)
        pi_id = setup["playthrough_instance"].id

        snap = create_baseline_snapshot(
            db,
            playthrough_instance_id=pi_id,
            session_id=setup["session"].id,
        )

        snap_repo = InstanceSnapshotRepository(db)
        baseline_count = len(snap_repo.list_by_instance(pi_id))

        with patch.object(
            SessionQuestStateModel, "__init__",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError):
                apply_snapshot(db, snap.id)

        # After rollback, no pre_apply_checkpoint should exist
        snapshots_after = InstanceSnapshotRepository(db).list_by_instance(pi_id)
        assert len(snapshots_after) == baseline_count


# ---------------------------------------------------------------------------
# NEW: Checksum behavior tests
# ---------------------------------------------------------------------------

class TestComputeChecksum:
    def test_deterministic(self):
        payload = {"session_id": "abc", "npc_states": [{"trust_score": 50}]}
        assert compute_checksum(payload) == compute_checksum(payload)

    def test_different_payloads_different_checksums(self):
        p1 = {"session_id": "abc", "npc_states": [{"trust_score": 50}]}
        p2 = {"session_id": "abc", "npc_states": [{"trust_score": 99}]}
        assert compute_checksum(p1) != compute_checksum(p2)

    def test_key_order_irrelevant(self):
        p1 = {"a": 1, "b": 2}
        p2 = {"b": 2, "a": 1}
        assert compute_checksum(p1) == compute_checksum(p2)

    def test_new_fields_change_checksum(self):
        p1 = {"npc_states": [{"npc_template_id": "x", "trust_score": 50}]}
        p2 = {"npc_states": [{"npc_template_id": "x", "trust_score": 50, "short_memory_summary": "memory"}]}
        assert compute_checksum(p1) != compute_checksum(p2)


def _seed_npc_memory_scope(db: DBSession, session_id: str, npc_template_id: str, npc_id: str):
    return NPCMemoryScopeRepository(db).create({
        "session_id": session_id,
        "npc_id": npc_id,
        "npc_template_id": npc_template_id,
        "profile_json": {"retention": "high"},
        "forget_curve_json": {"decay_rate": 0.1},
        "memory_count": 3,
    })


def _seed_npc_private_memory(db: DBSession, session_id: str, npc_template_id: str, npc_id: str):
    return NPCPrivateMemoryRepository(db).create({
        "session_id": session_id,
        "npc_id": npc_id,
        "npc_template_id": npc_template_id,
        "memory_text": "Saw the player steal the artifact",
        "content": "Saw the player steal the artifact",
        "memory_type": "episodic",
        "knowledge_source": "direct_observation",
        "source_ref": "event-001",
        "source_turn_no": 5,
        "salience": 0.9,
        "confidence": 0.8,
        "tags_json": ["theft", "player"],
        "memory_kind": "episodic",
        "importance": 0.9,
        "emotional_weight": 0.5,
        "current_strength": 1.0,
        "created_turn": 5,
        "last_accessed_turn": 5,
    })


class TestNPCMemorySnapshot:
    def test_snapshot_includes_npc_private_memories(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)
        npc_id = f"npc-{setup['npc_template'].id[:8]}"
        _seed_npc_private_memory(db_session, setup["session"].id, setup["npc_template"].id, npc_id)

        snapshot_json = build_session_snapshot_json(db_session, setup["session"].id)

        assert "npc_private_memories" in snapshot_json
        assert len(snapshot_json["npc_private_memories"]) == 1
        mem = snapshot_json["npc_private_memories"][0]
        assert mem["npc_id"] == npc_id
        assert mem["memory_text"] == "Saw the player steal the artifact"
        assert mem["memory_type"] == "episodic"
        assert mem["knowledge_source"] == "direct_observation"
        assert mem["source_ref"] == "event-001"
        assert mem["source_turn_no"] == 5
        assert mem["salience"] == 0.9
        assert mem["confidence"] == 0.8
        assert mem["tags_json"] == ["theft", "player"]
        assert mem["memory_kind"] == "episodic"

    def test_snapshot_includes_npc_memory_scopes(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)
        npc_id = f"npc-{setup['npc_template'].id[:8]}"
        _seed_npc_memory_scope(db_session, setup["session"].id, setup["npc_template"].id, npc_id)

        snapshot_json = build_session_snapshot_json(db_session, setup["session"].id)

        assert "npc_memory_scopes" in snapshot_json
        assert len(snapshot_json["npc_memory_scopes"]) == 1
        scope = snapshot_json["npc_memory_scopes"][0]
        assert scope["npc_id"] == npc_id
        assert scope["profile_json"] == {"retention": "high"}
        assert scope["forget_curve_json"] == {"decay_rate": 0.1}
        assert scope["memory_count"] == 3

    def test_apply_snapshot_restores_npc_private_memories(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)
        session_id = setup["session"].id
        npc_id = f"npc-{setup['npc_template'].id[:8]}"
        _seed_npc_private_memory(db_session, session_id, setup["npc_template"].id, npc_id)

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=session_id,
        )

        mem_repo = NPCPrivateMemoryRepository(db_session)
        memories_before = mem_repo.get_by_npc_template(session_id, setup["npc_template"].id)
        assert len(memories_before) == 1

        mem_repo.delete(memories_before[0].id)

        assert len(mem_repo.get_by_npc_template(session_id, setup["npc_template"].id)) == 0

        apply_snapshot(db_session, snap.id)

        memories_after = mem_repo.get_by_npc_template(session_id, setup["npc_template"].id)
        assert len(memories_after) == 1
        assert memories_after[0].memory_text == "Saw the player steal the artifact"
        assert memories_after[0].knowledge_source == "direct_observation"
        assert memories_after[0].salience == 0.9

    def test_apply_snapshot_does_not_delete_event_logs(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)

        event_repo = EventLogRepository(db_session)
        event = event_repo.create({
            "session_id": setup["session"].id,
            "turn_no": 1,
            "event_type": "player_action",
            "input_text": "探索古墓",
        })
        event_id = event.id

        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        apply_snapshot(db_session, snap.id)

        event_after = event_repo.get_by_id(event_id)
        assert event_after is not None
        assert event_after.event_type == "player_action"
        assert event_after.input_text == "探索古墓"

    def test_snapshot_checksum_changes_when_npc_memory_changes(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)
        session_id = setup["session"].id
        npc_id = f"npc-{setup['npc_template'].id[:8]}"

        snapshot1 = build_session_snapshot_json(db_session, session_id)
        checksum1 = compute_checksum(snapshot1)

        _seed_npc_private_memory(db_session, session_id, setup["npc_template"].id, npc_id)

        snapshot2 = build_session_snapshot_json(db_session, session_id)
        checksum2 = compute_checksum(snapshot2)

        assert checksum1 != checksum2

    def test_snapshot_scrubs_secret_fields_from_memory_payload(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)
        session_id = setup["session"].id
        npc_id = f"npc-{setup['npc_template'].id[:8]}"

        scope_repo = NPCMemoryScopeRepository(db_session)
        scope_repo.create({
            "session_id": session_id,
            "npc_id": npc_id,
            "npc_template_id": setup["npc_template"].id,
            "profile_json": {"api_key": "sk-secret-key-123", "safe_field": "ok"},
            "forget_curve_json": {"password": "hunter2", "decay_rate": 0.1},
            "memory_count": 1,
        })

        snapshot_json = build_session_snapshot_json(db_session, session_id)

        snapshot_str = str(snapshot_json)
        for pattern in _SECRET_KEY_PATTERNS:
            assert pattern not in snapshot_str.lower() or _no_secret_value_present(snapshot_json, pattern), \
                f"Secret pattern '{pattern}' found in snapshot JSON"

        scopes = snapshot_json.get("npc_memory_scopes", [])
        if scopes:
            assert "api_key" not in scopes[0].get("profile_json", {})
            assert "password" not in scopes[0].get("forget_curve_json", {})


def _no_secret_value_present(data, pattern):
    """Check that while the key pattern might appear, no secret value is stored."""
    if isinstance(data, dict):
        for k, v in data.items():
            if pattern in k.lower():
                return False
            if not _no_secret_value_present(v, pattern):
                return False
    elif isinstance(data, list):
        for item in data:
            if not _no_secret_value_present(item, pattern):
                return False
    return True


# ---------------------------------------------------------------------------
# Phase-3 rewind guards (append-only coverage)
# ---------------------------------------------------------------------------


def _rewind_sensitive_rows(db, session_id):
    rows = {}
    for model in (SessionNPCStateModel, SessionInventoryItemModel, SessionStateModel):
        records = db.query(model).filter_by(session_id=session_id).order_by(model.id).all()
        rows[model.__tablename__] = [
            tuple((column.name, getattr(record, column.name)) for column in model.__table__.columns)
            for record in records
        ]
    return rows


class TestPhase3SnapshotRewindGuards:
    def test_phase3_profile_refuses_apply_and_readonly_restore_without_writes(
        self, db_session, monkeypatch
    ):
        from llm_rpg.core.instance_snapshot_service import SnapshotRewindRefusedError
        from llm_rpg.core.time_simulation import (
            PROFILE_ID,
            PROFILE_RULESET_KEY,
            PROFILE_SCHEMA_VERSION,
        )

        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)
        world.ruleset_json = {
            PROFILE_RULESET_KEY: {
                "id": PROFILE_ID,
                "schema_version": PROFILE_SCHEMA_VERSION,
            }
        }
        db_session.commit()
        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )
        before = _rewind_sensitive_rows(db_session, setup["session"].id)
        snapshot_count = len(
            InstanceSnapshotRepository(db_session).list_by_instance(
                setup["playthrough_instance"].id
            )
        )

        with pytest.raises(SnapshotRewindRefusedError):
            apply_snapshot(db_session, snap.id)
        db_session.expire_all()
        assert _rewind_sensitive_rows(db_session, setup["session"].id) == before
        assert len(
            InstanceSnapshotRepository(db_session).list_by_instance(
                setup["playthrough_instance"].id
            )
        ) == snapshot_count

        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "false")
        with pytest.raises(SnapshotRewindRefusedError):
            restore_snapshot(db_session, snap.id)
        db_session.expire_all()
        assert _rewind_sensitive_rows(db_session, setup["session"].id) == before

    def test_existing_phase3_run_marker_refuses_apply_without_writes(
        self, db_session, monkeypatch
    ):
        from llm_rpg.core.instance_snapshot_service import SnapshotRewindRefusedError
        from llm_rpg.core.time_simulation import PHASE3_NAMESPACE

        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)
        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )

        state = SessionStateRepository(db_session).get_by_session(setup["session"].id)
        state.global_flags_json = {
            **state.global_flags_json,
            PHASE3_NAMESPACE: {"marker": "test"},
        }
        db_session.commit()
        before = _rewind_sensitive_rows(db_session, setup["session"].id)

        with pytest.raises(SnapshotRewindRefusedError):
            apply_snapshot(db_session, snap.id)
        db_session.expire_all()
        assert _rewind_sensitive_rows(db_session, setup["session"].id) == before

    def test_phase3_namespace_in_snapshot_payload_refuses_apply_without_writes(
        self, db_session, monkeypatch
    ):
        from llm_rpg.core.instance_snapshot_service import SnapshotRewindRefusedError
        from llm_rpg.core.time_simulation import PHASE3_NAMESPACE

        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)
        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )
        payload = dict(snap.snapshot_json)
        session_state = dict(payload["session_state"])
        global_flags = dict(session_state["global_flags_json"])
        global_flags[PHASE3_NAMESPACE] = {"marker": "payload"}
        session_state["global_flags_json"] = global_flags
        payload["session_state"] = session_state
        snap.snapshot_json = payload
        snap.checksum = compute_checksum(payload)
        db_session.commit()
        before = _rewind_sensitive_rows(db_session, setup["session"].id)

        with pytest.raises(SnapshotRewindRefusedError):
            apply_snapshot(db_session, snap.id)
        db_session.expire_all()
        assert _rewind_sensitive_rows(db_session, setup["session"].id) == before

    def test_ordinary_session_apply_remains_compatible(self, db_session, monkeypatch):
        monkeypatch.setenv("INSTANCE_SNAPSHOT_ENABLED", "true")
        world = _seed_world(db_session)
        setup = _setup_session_with_state(db_session, world)
        snap = create_baseline_snapshot(
            db_session,
            playthrough_instance_id=setup["playthrough_instance"].id,
            session_id=setup["session"].id,
        )
        state_repo = SessionStateRepository(db_session)
        state = state_repo.get_by_session(setup["session"].id)
        state_repo.update(state.id, {"active_mode": "combat"})

        result = apply_snapshot(db_session, snap.id)

        assert result["applied_snapshot_id"] == snap.id
        assert result["checkpoint_snapshot_id"]
        assert state_repo.get_by_session(setup["session"].id).active_mode == "exploration"
