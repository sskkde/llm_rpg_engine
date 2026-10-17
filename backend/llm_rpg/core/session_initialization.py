"""
Session Story State Initialization Module.

This module provides functionality to initialize baseline story state rows
for active game sessions. It ensures every session has the required baseline
rows before turn execution:
- SessionStateModel (with default location)
- SessionPlayerStateModel (with default stats)
- SessionNPCStateModel rows for relevant seed NPC templates
- SessionQuestStateModel rows for visible quests

The initialization is idempotent - running twice does NOT create duplicate rows.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..storage.models import (
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
    SessionNPCStateModel,
    SessionQuestStateModel,
    SessionInventoryItemModel,
    ScheduledEventModel,
    NPCTemplateModel,
    QuestTemplateModel,
    LocationModel,
    generate_uuid,
)
from ..storage.repositories import (
    SessionRepository,
    SessionStateRepository,
    SessionPlayerStateRepository,
    SessionNPCStateRepository,
    SessionQuestStateRepository,
    SessionInventoryItemRepository,
    ScheduledEventRepository,
    NPCTemplateRepository,
    QuestTemplateRepository,
    LocationRepository,
)
from .npc_seed_memory_service import seed_major_npc_private_memories


class SessionInitializationError(Exception):
    """Raised when session initialization fails."""
    
    def __init__(self, message: str, session_id: Optional[str] = None):
        self.session_id = session_id
        super().__init__(message)


def initialize_session_story_state(db: Session, session_id: str) -> None:
    """Initialize baseline story state rows for a session.

    This function creates the required baseline rows if they don't exist:
    - SessionStateModel with default location
    - SessionPlayerStateModel with default stats
    - SessionNPCStateModel rows for all NPCs in the world
    - SessionQuestStateModel rows for visible quests
    - (phase 3) the slice's inventory row, scheduled steps and run cursor

    The function is idempotent - running twice leaves row counts unchanged.

    It is deliberately a thin wrapper over ``plan_session_story_state`` +
    ``apply_session_story_state``: the turn path already defers those same rows
    into its final transaction, and having one implementation is what keeps the
    eager and deferred baselines from drifting apart.

    Args:
        db: SQLAlchemy database session
        session_id: The session ID to initialize

    Raises:
        SessionInitializationError: If session not found or initialization fails
    """
    plan = plan_session_story_state(db, session_id)
    apply_session_story_state(db, plan)


@dataclass
class SessionStoryStatePlan:
    """Read-only baseline inserts prepared for one turn.

    Phase 3 adds two deferred row groups to the same plan so a slice session's
    first turn writes its inventory row, its scheduled steps and its run cursor
    inside the single authoritative transaction -- and a clarification turn,
    which never applies the plan, writes none of them.
    """

    session_id: str
    world_id: str
    session_state: Optional[Dict[str, Any]] = None
    player_state: Optional[Dict[str, Any]] = None
    npc_states: List[Dict[str, Any]] = field(default_factory=list)
    quest_states: List[Dict[str, Any]] = field(default_factory=list)
    inventory_items: List[Dict[str, Any]] = field(default_factory=list)
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)
    seed_memory_plan: List[str] = field(default_factory=list)
    seed_memories_enabled: bool = False

    def session_state_overlay(self) -> Optional[SessionStateModel]:
        return SessionStateModel(**self.session_state) if self.session_state else None

    def player_state_overlay(self) -> Optional[SessionPlayerStateModel]:
        return SessionPlayerStateModel(**self.player_state) if self.player_state else None

    def npc_state_overlays(self) -> List[SessionNPCStateModel]:
        return [SessionNPCStateModel(**row) for row in self.npc_states]

    def quest_state_overlays(self) -> List[SessionQuestStateModel]:
        return [SessionQuestStateModel(**row) for row in self.quest_states]

    def inventory_item_overlays(self) -> List[SessionInventoryItemModel]:
        return [SessionInventoryItemModel(**row) for row in self.inventory_items]

    def scheduled_event_overlays(self) -> List[ScheduledEventModel]:
        return [ScheduledEventModel(**row) for row in self.scheduled_events]


def plan_session_story_state(db: Session, session_id: str) -> SessionStoryStatePlan:
    """Read current rows and compute missing baseline rows without writing."""
    session = SessionRepository(db).get_by_id(session_id)
    if session is None:
        raise SessionInitializationError(f"Session not found: {session_id}", session_id=session_id)

    world_id = session.world_id
    plan = SessionStoryStatePlan(session_id=session_id, world_id=world_id)

    # Phase 3: a slice world has its own baseline (its own starting location, its
    # own run cursor, its own scheduled steps). The generic "square" defaults do
    # not exist there, so the slice plans those groups instead.
    from .time_simulation_persistence import plan_phase3_baseline

    phase3_baseline = plan_phase3_baseline(db, session_id, world_id)
    if phase3_baseline is not None:
        plan.session_state = phase3_baseline.session_state
        plan.npc_states = list(phase3_baseline.npc_states)
        plan.inventory_items = list(phase3_baseline.inventory_items)
        plan.scheduled_events = list(phase3_baseline.scheduled_events)
    else:
        default_location = LocationRepository(db).get_by_code(world_id, "square")
        default_location_id = default_location.id if default_location else None

        if SessionStateRepository(db).get_by_session(session_id) is None:
            plan.session_state = {
                "id": generate_uuid(), "session_id": session_id,
                "current_time": "修仙历 春 第1日 辰时", "time_phase": "辰时",
                "current_location_id": default_location_id, "active_mode": "exploration",
                "global_flags_json": {},
            }

        npc_repo = SessionNPCStateRepository(db)
        for template in NPCTemplateRepository(db).get_by_world(world_id):
            if npc_repo.get_by_session_and_npc(session_id, template.id) is None:
                plan.npc_states.append({
                    "id": generate_uuid(), "session_id": session_id,
                    "npc_template_id": template.id, "current_location_id": default_location_id,
                    "trust_score": 50, "suspicion_score": 0, "status_flags": {},
                    "short_memory_summary": None, "hidden_plan_state": None,
                })

    if SessionPlayerStateRepository(db).get_by_session(session_id) is None:
        plan.player_state = {
            "id": generate_uuid(), "session_id": session_id, "realm_stage": "炼气一层",
            "hp": 100, "max_hp": 100, "stamina": 100, "spirit_power": 100,
            "relation_bias_json": {}, "conditions_json": [],
        }

    quest_repo = SessionQuestStateRepository(db)
    for template in QuestTemplateRepository(db).get_by_world(world_id):
        if template.visibility != "visible":
            continue
        if quest_repo.get_by_session_and_quest(session_id, template.id) is None:
            plan.quest_states.append({
                "id": generate_uuid(), "session_id": session_id,
                "quest_template_id": template.id, "current_step_no": 1,
                "progress_json": {}, "status": "active",
            })

    # Capture which major NPC seed records are eligible now; actual idempotent writes
    # still use the existing service in the final transaction.
    from .feature_flags import npc_memory_first_enabled
    plan.seed_memories_enabled = npc_memory_first_enabled()
    if plan.seed_memories_enabled:
        from ..storage.repositories import NPCPrivateMemoryRepository
        memory_repo = NPCPrivateMemoryRepository(db)
        for template in NPCTemplateRepository(db).get_by_world(world_id):
            if template.is_major_npc and not memory_repo.has_seed_memories(session_id, template.id):
                plan.seed_memory_plan.append(template.id)
    return plan


def apply_session_story_state(db: Session, plan: SessionStoryStatePlan) -> None:
    """Insert missing baseline rows and apply seed memories inside final UoW."""
    state_repo = SessionStateRepository(db)
    if plan.session_state and state_repo.get_by_session(plan.session_id) is None:
        state_repo.create(plan.session_state)
    player_repo = SessionPlayerStateRepository(db)
    if plan.player_state and player_repo.get_by_session(plan.session_id) is None:
        player_repo.create(plan.player_state)
    npc_repo = SessionNPCStateRepository(db)
    for row in plan.npc_states:
        if npc_repo.get_by_session_and_npc(plan.session_id, row["npc_template_id"]) is None:
            npc_repo.create(row)
    quest_repo = SessionQuestStateRepository(db)
    for row in plan.quest_states:
        if quest_repo.get_by_session_and_quest(plan.session_id, row["quest_template_id"]) is None:
            quest_repo.create(row)
    # Phase 3: the slice's inventory row and scheduled steps are baseline rows too.
    # The plan already decided which ones are missing, so this only creates them.
    inventory_repo = SessionInventoryItemRepository(db)
    for row in plan.inventory_items:
        if inventory_repo.get_by_id(row["id"]) is None:
            inventory_repo.create(row)
    scheduled_repo = ScheduledEventRepository(db)
    for row in plan.scheduled_events:
        if scheduled_repo.get_by_id(row["id"]) is None:
            scheduled_repo.create(row)
    if plan.seed_memories_enabled:
        seed_major_npc_private_memories(db, plan.session_id, plan.world_id)


def backfill_historical_sessions(db: Session) -> int:
    """
    Backfill baseline story state rows for all active historical sessions.
    
    This function finds all active sessions and calls initialize_session_story_state
    for each. It's useful for migrating existing sessions that may be missing
    baseline rows.
    
    Args:
        db: SQLAlchemy database session
        
    Returns:
        The count of sessions that were backfilled
        
    Note:
        This function does NOT distinguish between sessions that needed
        initialization vs. sessions that were already initialized.
        It simply calls initialize_session_story_state for all active sessions.
    """
    active_sessions = db.query(SessionModel).filter(
        SessionModel.status == "active"
    ).all()
    
    backfill_count = 0
    
    for session in active_sessions:
        try:
            initialize_session_story_state(db, session.id)
            backfill_count += 1
        except SessionInitializationError:
            continue
    
    return backfill_count
