"""
Scene Action Generator

Generates rule-based recommended actions for the current scene.
Derives available actions from location access_rules, active quests,
and visible NPCs at the current location.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..storage.models import (
    LocationModel,
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
    SessionNPCStateModel,
    NPCTemplateModel,
    SessionQuestStateModel,
    QuestTemplateModel,
)
from ..storage.repositories import (
    LocationRepository,
    SessionRepository,
    SessionStateRepository,
    SessionPlayerStateRepository,
    SessionNPCStateRepository,
    NPCTemplateRepository,
    SessionQuestStateRepository,
    QuestTemplateRepository,
)
from ..models.states import CurrentSceneState


# ---------------------------------------------------------------------------
# Movement action templates (Chinese)
# ---------------------------------------------------------------------------
MOVEMENT_ACTION_TEMPLATE = "前往{name}"


def _check_location_accessible(
    access_rules: Dict[str, Any],
    player_state: Optional[SessionPlayerStateModel],
    session_state: Optional[SessionStateModel],
    session: SessionModel,
    global_flags: Dict[str, Any],
) -> bool:
    """Check if a location is accessible based on its access_rules.
    
    Reuses the same logic as movement_handler._check_access_rules.
    Returns True if accessible, False otherwise.
    """
    if not access_rules:
        return True

    # always_accessible short-circuits everything
    if access_rules.get("always_accessible"):
        return True

    # player_level check
    player_level = access_rules.get("player_level")
    if player_level and player_state:
        level_hierarchy = {
            "outer_disciple": 1,
            "inner_disciple": 2,
            "core_disciple": 3,
            "elder": 4,
        }
        required = level_hierarchy.get(player_level, 0)
        current_realm = player_state.realm_stage or ""
        # Map realm_stage strings to numeric levels
        current_level = 0
        if "内门" in current_realm or "inner" in current_realm.lower():
            current_level = 2
        elif "核心" in current_realm or "core" in current_realm.lower():
            current_level = 3
        elif "长老" in current_realm or "elder" in current_realm.lower():
            current_level = 4
        elif "外门" in current_realm or "outer" in current_realm.lower() or "炼气" in current_realm:
            current_level = 1

        if current_level < required:
            return False

    # time_restrictions check
    time_restriction = access_rules.get("time_restrictions")
    if time_restriction == "daytime_only":
        time_phase = session_state.time_phase if session_state else None
        if time_phase:
            daytime_phases = {"辰时", "巳时", "午时", "未时", "申时"}
            if time_phase not in daytime_phases:
                return False

    # chapter check
    required_chapter = access_rules.get("chapter")
    if required_chapter is not None:
        current_chapter_no = None
        if session.current_chapter_id:
            current_chapter_no = global_flags.get("current_chapter_no")
        if current_chapter_no is None:
            current_chapter_no = 1
        if current_chapter_no < required_chapter:
            return False

    # quest_trigger check
    quest_trigger = access_rules.get("quest_trigger")
    if quest_trigger is not None:
        if not global_flags.get(f"quest_trigger_{quest_trigger}"):
            return False

    # item_required check
    item_required = access_rules.get("item_required")
    if item_required is not None:
        if not global_flags.get(f"has_item_{item_required}"):
            return False

    # quest_completed check
    quest_completed = access_rules.get("quest_completed")
    if quest_completed is not None:
        if not global_flags.get(f"quest_completed_{quest_completed}"):
            return False

    # boss_unlocked check
    boss_unlocked = access_rules.get("boss_unlocked")
    if boss_unlocked is True:
        if not global_flags.get("boss_unlocked"):
            return False

    # combat_level check
    combat_level = access_rules.get("combat_level")
    if combat_level and player_state:
        combat_hierarchy = {
            "novice": 0,
            "apprentice": 1,
            "journeyman": 2,
            "expert": 3,
        }
        required_combat = combat_hierarchy.get(combat_level, 0)
        current_combat = combat_hierarchy.get(
            global_flags.get("combat_level", "novice"), 0
        )
        if current_combat < required_combat:
            return False

    # quest_requirement check (None means no requirement)
    quest_requirement = access_rules.get("quest_requirement")
    if quest_requirement is not None:
        if not global_flags.get(f"quest_active_{quest_requirement}"):
            return False

    return True


def generate_recommended_actions(
    db: Session,
    session_id: str,
    location_id: Optional[str] = None,
) -> List[str]:
    """Generate rule-based recommended actions for the current scene.
    
    Derives available actions from:
    1. Legal movement actions based on location access_rules
    2. Quest-relevant actions from active quests
    3. NPC interaction actions for visible NPCs
    
    Args:
        db: SQLAlchemy database session.
        session_id: The active session ID.
        location_id: Optional location ID. If None, uses current location from session state.
    
    Returns:
        List of recommended action strings (max 4).
    """
    session_repo = SessionRepository(db)
    session_state_repo = SessionStateRepository(db)
    player_state_repo = SessionPlayerStateRepository(db)
    location_repo = LocationRepository(db)
    npc_state_repo = SessionNPCStateRepository(db)
    npc_template_repo = NPCTemplateRepository(db)
    quest_state_repo = SessionQuestStateRepository(db)
    quest_template_repo = QuestTemplateRepository(db)
    
    # 1. Load session
    session = session_repo.get_by_id(session_id)
    if session is None:
        return []
    
    world_id = session.world_id
    
    # 2. Determine current location
    session_state = session_state_repo.get_by_session(session_id)
    current_location_id = location_id
    if current_location_id is None:
        if session_state:
            current_location_id = session_state.current_location_id
    
    if current_location_id is None:
        # Default to square if no location set
        square_location = location_repo.get_by_code(world_id, "square")
        if square_location:
            current_location_id = square_location.id
        else:
            return []
    
    # 3. Load current location
    current_location = location_repo.get_by_id(current_location_id)
    if current_location is None:
        return []
    
    # 4. Load player state
    player_state = player_state_repo.get_by_session(session_id)
    
    # 5. Get global flags
    global_flags = {}
    if session_state and session_state.global_flags_json:
        global_flags = session_state.global_flags_json
    
    # 6. Generate movement actions from all world locations
    all_locations = location_repo.get_by_world(world_id)
    recommended_actions: List[str] = []
    
    for loc in all_locations:
        # Skip current location
        if loc.id == current_location_id:
            continue
        
        # Check if location is accessible
        access_rules = loc.access_rules or {}
        is_accessible = _check_location_accessible(
            access_rules,
            player_state,
            session_state,
            session,
            global_flags,
        )
        
        if is_accessible:
            action = MOVEMENT_ACTION_TEMPLATE.format(name=loc.name)
            recommended_actions.append(action)
    
    # 7. Add NPC interaction actions for NPCs at current location
    npc_states = npc_state_repo.get_by_session(session_id)
    for npc_state in npc_states:
        if npc_state.current_location_id == current_location_id:
            npc_template = npc_template_repo.get_by_id(npc_state.npc_template_id)
            if npc_template:
                # Add interaction action
                action = f"与{npc_template.name}交谈"
                recommended_actions.append(action)
    
    # 8. Add quest-relevant actions from active quests
    quest_states = quest_state_repo.get_by_session(session_id)
    for quest_state in quest_states:
        if quest_state.status == "active":
            quest_template = quest_template_repo.get_by_id(quest_state.quest_template_id)
            if quest_template:
                # Add quest action hint
                action = f"查看任务：{quest_template.name}"
                recommended_actions.append(action)
    
    # 9. Deduplicate and limit to 4 actions
    seen = set()
    unique_actions = []
    for action in recommended_actions:
        if action not in seen:
            seen.add(action)
            unique_actions.append(action)
    
    return unique_actions[:4]


def get_active_scene_state(
    db: Session,
    session_id: str,
) -> Optional[CurrentSceneState]:
    """Build and return the active scene state for a session.
    
    Derives scene state from:
    - Current location from session_state
    - Active actors (player + NPCs at location)
    - Available actions from generate_recommended_actions
    
    Args:
        db: SQLAlchemy database session.
        session_id: The active session ID.
    
    Returns:
        CurrentSceneState if session exists, None otherwise.
    """
    session_repo = SessionRepository(db)
    session_state_repo = SessionStateRepository(db)
    location_repo = LocationRepository(db)
    npc_state_repo = SessionNPCStateRepository(db)
    
    # 1. Load session
    session = session_repo.get_by_id(session_id)
    if session is None:
        return None
    
    world_id = session.world_id
    
    # 2. Load session state
    session_state = session_state_repo.get_by_session(session_id)
    
    # 3. Determine current location
    current_location_id = None
    if session_state:
        current_location_id = session_state.current_location_id
    
    if current_location_id is None:
        # Default to square if no location set
        square_location = location_repo.get_by_code(world_id, "square")
        if square_location:
            current_location_id = square_location.id
        else:
            return None
    
    # 4. Load current location
    current_location = location_repo.get_by_id(current_location_id)
    if current_location is None:
        return None
    
    # 5. Get active actors (player + NPCs at location)
    active_actor_ids = ["player"]
    npc_states = npc_state_repo.get_by_session(session_id)
    for npc_state in npc_states:
        if npc_state.current_location_id == current_location_id:
            active_actor_ids.append(f"npc_{npc_state.npc_template_id}")
    
    # 6. Generate recommended actions
    recommended_actions = generate_recommended_actions(
        db, session_id, current_location_id
    )
    
    # 7. Build scene state
    scene_id = f"scene_{current_location.code}"
    
    return CurrentSceneState(
        entity_id="scene",
        scene_id=scene_id,
        location_id=current_location_id,
        active_actor_ids=active_actor_ids,
        visible_object_ids=[],
        danger_level=0.0,
        scene_phase="exploration",
        blocked_paths=[],
        available_actions=recommended_actions,
    )
