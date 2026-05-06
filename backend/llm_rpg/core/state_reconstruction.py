"""
State Reconstruction Module.

This module provides functionality to reconstruct CanonicalState from persisted DB rows.
It reads from: sessions, session_states, session_player_states, session_npc_states,
session_quest_states, locations, npc_templates, quest_templates, and event_logs.

The reconstructed state preserves:
- Current location
- Known locations
- Current chapter/world
- Active actors
- Visible quests
- World time

The existing in-memory CanonicalStateManager is treated as a cache only;
this module rebuilds it when missing.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models.states import (
    CanonicalState,
    PlayerState,
    WorldState,
    CurrentSceneState,
    LocationState,
    NPCState,
    QuestState,
    PhysicalState,
    MentalState,
)
from ..models.events import WorldTime
from ..storage.models import (
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
    SessionNPCStateModel,
    SessionQuestStateModel,
    LocationModel,
    NPCTemplateModel,
    QuestTemplateModel,
    WorldModel,
    ChapterModel,
    EventLogModel,
)
from ..storage.repositories import (
    SessionRepository,
    SessionStateRepository,
    SessionPlayerStateRepository,
    SessionNPCStateRepository,
    SessionQuestStateRepository,
    LocationRepository,
    NPCTemplateRepository,
    QuestTemplateRepository,
    WorldRepository,
    ChapterRepository,
    EventLogRepository,
)


class SessionNotFoundError(Exception):
    """Raised when a session cannot be found in the database."""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session not found: {session_id}")


class StateReconstructionError(Exception):
    """Raised when state reconstruction fails due to missing or invalid data."""
    
    def __init__(self, message: str, session_id: Optional[str] = None):
        self.session_id = session_id
        super().__init__(message)


def reconstruct_canonical_state(db: Session, session_id: str) -> Optional[CanonicalState]:
    """
    Reconstruct CanonicalState from persisted DB rows.
    
    This function reads from the database and builds the minimal CanonicalState
    required by TurnOrchestrator. It handles missing rows gracefully:
    - If session_state missing, uses defaults
    - If no NPC states, returns empty dict
    - If no quest states, returns empty dict
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID to reconstruct state for
        
    Returns:
        CanonicalState if session exists and reconstruction succeeds,
        None if session does not exist
        
    Raises:
        StateReconstructionError: If reconstruction fails due to invalid data
    """
    # Initialize repositories
    session_repo = SessionRepository(db)
    session_state_repo = SessionStateRepository(db)
    player_state_repo = SessionPlayerStateRepository(db)
    npc_state_repo = SessionNPCStateRepository(db)
    quest_state_repo = SessionQuestStateRepository(db)
    location_repo = LocationRepository(db)
    npc_template_repo = NPCTemplateRepository(db)
    quest_template_repo = QuestTemplateRepository(db)
    world_repo = WorldRepository(db)
    chapter_repo = ChapterRepository(db)
    event_log_repo = EventLogRepository(db)
    
    # Step 1: Get session - if missing, return None
    session = session_repo.get_by_id(session_id)
    if session is None:
        return None
    
    # Step 2: Get world and chapter
    world = world_repo.get_by_id(session.world_id)
    if world is None:
        raise StateReconstructionError(
            f"World not found for session: world_id={session.world_id}",
            session_id=session_id,
        )
    
    chapter = None
    if session.current_chapter_id:
        chapter = chapter_repo.get_by_id(session.current_chapter_id)
    
    # Step 3: Get session_state (may be missing for new sessions)
    session_state = session_state_repo.get_by_session(session_id)
    
    # Step 4: Get player_state (may be missing for new sessions)
    player_state_model = player_state_repo.get_by_session(session_id)
    
    # Step 5: Build WorldState
    world_state = _build_world_state(
        world=world,
        chapter=chapter,
        session_state=session_state,
    )
    
    # Step 6: Build PlayerState
    player_state = _build_player_state(
        session_state=session_state,
        player_state_model=player_state_model,
    )
    
    # Step 7: Build CurrentSceneState
    scene_state = _build_scene_state(
        session_state=session_state,
        session_id=session_id,
    )
    
    # Step 8: Build NPC states dict
    npc_states = _build_npc_states(
        db=db,
        session_id=session_id,
        npc_state_repo=npc_state_repo,
        npc_template_repo=npc_template_repo,
        location_repo=location_repo,
    )
    
    # Step 9: Build Quest states dict
    quest_states = _build_quest_states(
        session_id=session_id,
        quest_state_repo=quest_state_repo,
        quest_template_repo=quest_template_repo,
    )
    
    # Step 10: Build Location states dict (known locations)
    location_states = _build_location_states(
        world_id=world.id,
        session_state=session_state,
        location_repo=location_repo,
    )
    
    # Step 11: Construct CanonicalState
    canonical_state = CanonicalState(
        player_state=player_state,
        world_state=world_state,
        current_scene_state=scene_state,
        location_states=location_states,
        npc_states=npc_states,
        quest_states=quest_states,
        faction_states={},  # Not persisted yet
        relationship_states={},  # Not persisted yet
        inventory_states={},  # Not persisted yet
        combat_states={},  # Not persisted yet
        knowledge_states={},  # Not persisted yet
        schedule_states={},  # Not persisted yet
    )
    
    return canonical_state


def _build_world_state(
    world: WorldModel,
    chapter: Optional[ChapterModel],
    session_state: Optional[SessionStateModel],
) -> WorldState:
    """
    Build WorldState from DB models.
    
    Uses defaults for missing session_state fields.
    """
    # Parse world time from session_state or use defaults
    if session_state and session_state.current_time:
        # Parse time string format: "修仙历 春 第1日 辰时"
        time_parts = session_state.current_time.split()
        if len(time_parts) >= 4:
            calendar = time_parts[0]
            season = time_parts[1]
            day = int(time_parts[2].replace("第", "").replace("日", ""))
            period = time_parts[3]
        else:
            # Default values
            calendar = "修仙历"
            season = "春"
            day = 1
            period = session_state.time_phase or "辰时"
    else:
        calendar = "修仙历"
        season = "春"
        day = 1
        period = "辰时"
    
    world_time = WorldTime(
        calendar=calendar,
        season=season,
        day=day,
        period=period,
    )
    
    # Build global flags from session_state
    global_flags: Dict[str, Any] = {}
    if session_state and session_state.global_flags_json:
        global_flags = session_state.global_flags_json.copy()
    
    return WorldState(
        entity_id=f"world_{world.id}",
        world_id=world.id,
        current_time=world_time,
        global_flags=global_flags,
        active_world_events=[],  # Would need to query scheduled_events
        weather="晴",  # Default
        moon_phase="满月",  # Default
    )


def _build_player_state(
    session_state: Optional[SessionStateModel],
    player_state_model: Optional[SessionPlayerStateModel],
) -> PlayerState:
    """
    Build PlayerState from DB models.
    
    Uses defaults for missing fields.
    """
    # Get location from session_state or use default
    location_id = "loc_mountain_gate"  # Default starting location
    if session_state and session_state.current_location_id:
        location_id = session_state.current_location_id
    
    # Get realm and stats from player_state_model or use defaults
    realm = "炼气一层"
    spiritual_power = 100
    hp = 100
    max_hp = 100
    
    if player_state_model:
        realm = player_state_model.realm_stage or realm
        spiritual_power = player_state_model.spirit_power or spiritual_power
        hp = player_state_model.hp or hp
        max_hp = player_state_model.max_hp or max_hp
    
    return PlayerState(
        entity_id="player",
        location_id=location_id,
        name="玩家",
        realm=realm,
        spiritual_power=spiritual_power,
        inventory_ids=[],  # Would need to query session_inventory_items
        active_quest_ids=[],  # Would need to query session_quest_states with active status
        known_fact_ids=[],  # Would need to query memory_facts
        flags={},  # Would need to query session_event_flags
    )


def _build_scene_state(
    session_state: Optional[SessionStateModel],
    session_id: str,
) -> CurrentSceneState:
    """
    Build CurrentSceneState from session_state.
    
    Uses defaults for missing fields.
    """
    # Get location from session_state or use default
    location_id = "loc_mountain_gate"
    if session_state and session_state.current_location_id:
        location_id = session_state.current_location_id
    
    # Get active mode from session_state or use default
    scene_phase = "exploration"
    if session_state and session_state.active_mode:
        scene_phase = session_state.active_mode
    
    return CurrentSceneState(
        entity_id=f"scene_{session_id}",
        scene_id=f"scene_{session_id}",
        location_id=location_id,
        active_actor_ids=[],  # Would need to query NPCs at current location
        visible_object_ids=[],  # Would need to query items at current location
        danger_level=0.0,
        scene_phase=scene_phase,
        blocked_paths=[],  # Would need scene-specific data
        available_actions=[],  # Would be computed dynamically
    )


def _build_npc_states(
    db: Session,
    session_id: str,
    npc_state_repo: SessionNPCStateRepository,
    npc_template_repo: NPCTemplateRepository,
    location_repo: LocationRepository,
) -> Dict[str, NPCState]:
    """
    Build NPC states dict from session_npc_states and npc_templates.
    
    Returns empty dict if no NPC states exist.
    """
    npc_states: Dict[str, NPCState] = {}
    
    # Get all NPC states for this session
    session_npc_states = npc_state_repo.get_by_session(session_id)
    
    for snpc in session_npc_states:
        # Get NPC template for name and identity
        npc_template = npc_template_repo.get_by_id(snpc.npc_template_id)
        if npc_template is None:
            # Skip NPCs without templates
            continue
        
        # Get location name if available
        location_name = "未知地点"
        if snpc.current_location_id:
            location = location_repo.get_by_id(snpc.current_location_id)
            if location:
                location_name = location.name
        
        # Build NPC state
        npc_id = npc_template.code or npc_template.id
        
        # Build physical and mental states from DB values
        physical_state = PhysicalState(
            hp=100,  # Default
            max_hp=100,
            injured=False,
            fatigue=0.0,
        )
        
        mental_state = MentalState(
            fear=0.0,
            trust_toward_player=float(snpc.trust_score) / 100.0 if snpc.trust_score else 0.5,
            suspicion_toward_player=float(snpc.suspicion_score) / 100.0 if snpc.suspicion_score else 0.0,
            mood="neutral",  # Would need to derive from status_flags
        )
        
        npc_state = NPCState(
            entity_id=npc_id,
            npc_id=npc_id,
            name=npc_template.name,
            status="alive",  # Would need to check status_flags
            location_id=snpc.current_location_id or "loc_mountain_gate",
            mood=mental_state.mood,
            current_goal_ids=[],  # Would need to query hidden_plan_state
            current_action=None,
            physical_state=physical_state,
            mental_state=mental_state,
        )
        
        npc_states[npc_id] = npc_state
    
    return npc_states


def _build_quest_states(
    session_id: str,
    quest_state_repo: SessionQuestStateRepository,
    quest_template_repo: QuestTemplateRepository,
) -> Dict[str, QuestState]:
    """
    Build Quest states dict from session_quest_states and quest_templates.
    
    Returns empty dict if no quest states exist.
    """
    quest_states: Dict[str, QuestState] = {}
    
    # Get all quest states for this session
    session_quest_states = quest_state_repo.get_by_session(session_id)
    
    for sq in session_quest_states:
        # Get quest template for name and objectives
        quest_template = quest_template_repo.get_by_id(sq.quest_template_id)
        if quest_template is None:
            # Skip quests without templates
            continue
        
        quest_id = quest_template.code or quest_template.id
        
        # Build quest state
        quest_state = QuestState(
            entity_id=quest_id,
            quest_id=quest_id,
            name=quest_template.name,
            status=sq.status or "active",
            stage=str(sq.current_step_no) if sq.current_step_no else "1",
            known_objectives=[],  # Would need to query quest_steps
            hidden_objectives=[],  # Would need to query quest_steps with hidden visibility
            required_flags=sq.progress_json.copy() if sq.progress_json else {},
            next_possible_stages=[],  # Would need to compute from quest_steps
        )
        
        quest_states[quest_id] = quest_state
    
    return quest_states


def _build_location_states(
    world_id: str,
    session_state: Optional[SessionStateModel],
    location_repo: LocationRepository,
) -> Dict[str, LocationState]:
    """
    Build Location states dict for known locations.
    
    Currently returns all locations in the world.
    In future, should filter by player's known locations.
    """
    location_states: Dict[str, LocationState] = {}
    
    # Get all locations for this world
    locations = location_repo.get_by_world(world_id)
    
    for loc in locations:
        location_id = loc.code or loc.id
        
        # Determine if known to player
        # For now, mark starting location and nearby locations as known
        known_to_player = False
        if session_state and session_state.current_location_id:
            known_to_player = loc.id == session_state.current_location_id
        elif location_id == "loc_mountain_gate":
            known_to_player = True
        
        location_state = LocationState(
            entity_id=location_id,
            location_id=location_id,
            name=loc.name,
            status="normal",
            danger_level=0.0,
            population_mood="neutral",
            active_events=[],  # Would need to query scheduled_events
            known_to_player=known_to_player,
            last_updated_world_time=None,
        )
        
        location_states[location_id] = location_state
    
    return location_states


def get_latest_turn_number(db: Session, session_id: str) -> int:
    """
    Get the latest turn number for a session from event_logs.
    
    This is used for turn numbering and recovery.
    DB is authoritative for turn numbering.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        
    Returns:
        The latest turn number, or 0 if no events exist
    """
    event_log_repo = EventLogRepository(db)
    
    # Get recent events ordered by turn_no descending
    recent_events = event_log_repo.get_recent(session_id, limit=1)
    
    if recent_events and len(recent_events) > 0:
        return recent_events[0].turn_no
    
    return 0


def get_active_actors_at_location(
    db: Session,
    session_id: str,
    location_id: str,
) -> List[str]:
    """
    Get list of active actor IDs at a specific location.
    
    This includes player (if at location) and NPCs at the location.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        location_id: The location ID to check
        
    Returns:
        List of actor IDs at the location
    """
    actors: List[str] = []
    
    # Check if player is at this location
    session_state_repo = SessionStateRepository(db)
    session_state = session_state_repo.get_by_session(session_id)
    
    if session_state and session_state.current_location_id == location_id:
        actors.append("player")
    
    # Get NPCs at this location
    npc_state_repo = SessionNPCStateRepository(db)
    session_npc_states = npc_state_repo.get_by_session(session_id)
    
    for snpc in session_npc_states:
        if snpc.current_location_id == location_id:
            # Get NPC template to get NPC code/id
            npc_template_repo = NPCTemplateRepository(db)
            npc_template = npc_template_repo.get_by_id(snpc.npc_template_id)
            if npc_template:
                npc_id = npc_template.code or npc_template.id
                actors.append(npc_id)
    
    return actors