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
    """
    Initialize baseline story state rows for a session.
    
    This function creates the required baseline rows if they don't exist:
    - SessionStateModel with default location
    - SessionPlayerStateModel with default stats
    - SessionNPCStateModel rows for all NPCs in the world
    - SessionQuestStateModel rows for visible quests
    
    The function is idempotent - running twice leaves row counts unchanged.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID to initialize
        
    Raises:
        SessionInitializationError: If session not found or initialization fails
    """
    session_repo = SessionRepository(db)
    session_state_repo = SessionStateRepository(db)
    player_state_repo = SessionPlayerStateRepository(db)
    npc_state_repo = SessionNPCStateRepository(db)
    quest_state_repo = SessionQuestStateRepository(db)
    npc_template_repo = NPCTemplateRepository(db)
    quest_template_repo = QuestTemplateRepository(db)
    location_repo = LocationRepository(db)
    
    session = session_repo.get_by_id(session_id)
    if session is None:
        raise SessionInitializationError(
            f"Session not found: {session_id}",
            session_id=session_id,
        )
    
    world_id = session.world_id
    
    default_location = location_repo.get_by_code(world_id, "square")
    default_location_id = default_location.id if default_location else None
    
    existing_session_state = session_state_repo.get_by_session(session_id)
    if existing_session_state is None:
        session_state_repo.create_or_update({
            "session_id": session_id,
            "current_time": "修仙历 春 第1日 辰时",
            "time_phase": "辰时",
            "current_location_id": default_location_id,
            "active_mode": "exploration",
            "global_flags_json": {},
        })
    
    existing_player_state = player_state_repo.get_by_session(session_id)
    if existing_player_state is None:
        player_state_repo.create_or_update({
            "session_id": session_id,
            "realm_stage": "炼气一层",
            "hp": 100,
            "max_hp": 100,
            "stamina": 100,
            "spirit_power": 100,
            "relation_bias_json": {},
            "conditions_json": [],
        })
    
    npc_templates = npc_template_repo.get_by_world(world_id)
    
    for npc_template in npc_templates:
        existing_npc_state = npc_state_repo.get_by_session_and_npc(
            session_id, npc_template.id
        )
        
        if existing_npc_state is None:
            npc_location_id = default_location_id
            
            npc_state_repo.create_or_update({
                "session_id": session_id,
                "npc_template_id": npc_template.id,
                "current_location_id": npc_location_id,
                "trust_score": 50,
                "suspicion_score": 0,
                "status_flags": {},
                "short_memory_summary": None,
                "hidden_plan_state": None,
            })
    
    quest_templates = quest_template_repo.get_by_world(world_id)
    
    for quest_template in quest_templates:
        if quest_template.visibility != "visible":
            continue
        
        existing_quest_state = quest_state_repo.get_by_session_and_quest(
            session_id, quest_template.id
        )
        
        if existing_quest_state is None:
            quest_state_repo.create({
                "session_id": session_id,
                "quest_template_id": quest_template.id,
                "current_step_no": 1,
                "progress_json": {},
                "status": "active",
            })
    
    # P10-C Phase 4: Seed major NPC private memories when NPC_MEMORY_FIRST_ENABLED=true
    seed_major_npc_private_memories(db, session_id, world_id)


@dataclass
class SessionStoryStatePlan:
    """Read-only baseline inserts prepared for one turn."""

    session_id: str
    world_id: str
    session_state: Optional[Dict[str, Any]] = None
    player_state: Optional[Dict[str, Any]] = None
    npc_states: List[Dict[str, Any]] = field(default_factory=list)
    quest_states: List[Dict[str, Any]] = field(default_factory=list)
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


def plan_session_story_state(db: Session, session_id: str) -> SessionStoryStatePlan:
    """Read current rows and compute missing baseline rows without writing."""
    session = SessionRepository(db).get_by_id(session_id)
    if session is None:
        raise SessionInitializationError(f"Session not found: {session_id}", session_id=session_id)

    world_id = session.world_id
    default_location = LocationRepository(db).get_by_code(world_id, "square")
    default_location_id = default_location.id if default_location else None
    plan = SessionStoryStatePlan(session_id=session_id, world_id=world_id)

    if SessionStateRepository(db).get_by_session(session_id) is None:
        plan.session_state = {
            "id": generate_uuid(), "session_id": session_id,
            "current_time": "修仙历 春 第1日 辰时", "time_phase": "辰时",
            "current_location_id": default_location_id, "active_mode": "exploration",
            "global_flags_json": {},
        }
    if SessionPlayerStateRepository(db).get_by_session(session_id) is None:
        plan.player_state = {
            "id": generate_uuid(), "session_id": session_id, "realm_stage": "炼气一层",
            "hp": 100, "max_hp": 100, "stamina": 100, "spirit_power": 100,
            "relation_bias_json": {}, "conditions_json": [],
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
