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

from typing import Optional

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
