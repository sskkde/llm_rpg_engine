"""
Quest Progression Module.

Handles visible quest state activation and deterministic quest progression
based on player actions (movement, NPC interaction). Updates quest progress
in progress_json, current_step_no, and status fields.

Key functions:
- check_quest_progression: Evaluates if action triggers quest progression
- get_visible_quests: Returns list of active visible quests
- advance_quest_step: Updates quest step and progress
- check_location_access: Validates quest requirements for gated locations
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, attributes

from ..storage.models import (
    QuestTemplateModel,
    QuestStepModel,
    SessionQuestStateModel,
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
    LocationModel,
)
from ..storage.repositories import (
    QuestTemplateRepository,
    QuestStepRepository,
    SessionQuestStateRepository,
    SessionRepository,
    SessionStateRepository,
    SessionPlayerStateRepository,
    LocationRepository,
)


@dataclass
class QuestProgress:
    """Represents quest progress state."""
    quest_id: str
    quest_template_id: str
    quest_name: str
    step_no: int
    progress: Dict[str, Any]
    status: str


@dataclass
class QuestProgressionResult:
    """Result of quest progression check."""
    triggered: bool
    quest_progress: Optional[QuestProgress] = None
    message: Optional[str] = None


class QuestProgressionError(Exception):
    """Raised when quest progression fails due to system errors."""
    
    def __init__(self, message: str, session_id: Optional[str] = None):
        self.session_id = session_id
        super().__init__(message)


def get_visible_quests(db: Session, session_id: str) -> List[SessionQuestStateModel]:
    """
    Get all active visible quests for a session.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        
    Returns:
        List of SessionQuestStateModel with status="active"
    """
    quest_state_repo = SessionQuestStateRepository(db)
    
    all_quest_states = quest_state_repo.get_by_session(session_id)
    
    visible_quests = [
        qs for qs in all_quest_states
        if qs.status == "active"
    ]
    
    return visible_quests


def advance_quest_step(
    db: Session,
    session_id: str,
    quest_template_id: str
) -> Optional[QuestProgress]:
    """
    Advance a quest to the next step.
    
    Increments current_step_no and updates progress_json.
    If the quest has no more steps, marks it as completed.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        quest_template_id: The quest template ID
        
    Returns:
        QuestProgress with updated state, or None if quest not found
    """
    quest_state_repo = SessionQuestStateRepository(db)
    quest_step_repo = QuestStepRepository(db)
    
    quest_state = quest_state_repo.get_by_session_and_quest(
        session_id, quest_template_id
    )
    
    if quest_state is None:
        return None
    
    if quest_state.status != "active":
        return None
    
    current_step_no = quest_state.current_step_no
    
    all_steps = quest_step_repo.get_by_quest(quest_template_id)
    max_step = max((s.step_no for s in all_steps), default=1)
    
    if current_step_no >= max_step:
        quest_state.status = "completed"
        new_progress = dict(quest_state.progress_json)
        new_progress["completed_at_step"] = current_step_no
        quest_state.progress_json = new_progress
    else:
        quest_state.current_step_no = current_step_no + 1
        new_progress = dict(quest_state.progress_json)
        new_progress["last_advanced"] = True
        quest_state.progress_json = new_progress
    
    db.commit()
    db.refresh(quest_state)
    
    quest_template = db.query(QuestTemplateModel).filter(
        QuestTemplateModel.id == quest_template_id
    ).first()
    
    return QuestProgress(
        quest_id=quest_state.id,
        quest_template_id=quest_template_id,
        quest_name=quest_template.name if quest_template else "Unknown",
        step_no=quest_state.current_step_no,
        progress=quest_state.progress_json,
        status=quest_state.status,
    )


def check_quest_progression(
    db: Session,
    session_id: str,
    action_context: Dict[str, Any]
) -> List[QuestProgressionResult]:
    """
    Check if an action triggers quest progression.
    
    Evaluates actions like movement and NPC interaction to determine
    if any quest should advance.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        action_context: Dict containing action details:
            - action_type: "movement" | "npc_interaction" | etc.
            - target_location_code: For movement actions
            - target_npc_id: For NPC interactions
            
    Returns:
        List of QuestProgressionResult for any triggered progressions
    """
    results: List[QuestProgressionResult] = []
    
    action_type = action_context.get("action_type")
    
    if action_type == "movement":
        target_location = action_context.get("target_location_code")
        
        if target_location == "trial_hall":
            result = _check_trial_hall_progression(db, session_id)
            if result:
                results.append(result)
    
    elif action_type == "npc_interaction":
        target_npc_id = action_context.get("target_npc_id")
        if target_npc_id:
            result = _check_npc_interaction_progression(
                db, session_id, target_npc_id
            )
            if result:
                results.append(result)
    
    return results


def _check_trial_hall_progression(
    db: Session,
    session_id: str
) -> Optional[QuestProgressionResult]:
    """
    Check if movement to trial_hall advances the first_trial quest.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        
    Returns:
        QuestProgressionResult if progression triggered, None otherwise
    """
    quest_state_repo = SessionQuestStateRepository(db)
    quest_template_repo = QuestTemplateRepository(db)
    
    session = db.query(SessionModel).filter(
        SessionModel.id == session_id
    ).first()
    
    if session is None:
        return None
    
    world_id = session.world_id
    
    first_trial_template = quest_template_repo.get_by_code(
        world_id, "first_trial"
    ) if hasattr(quest_template_repo, 'get_by_code') else None
    
    if first_trial_template is None:
        first_trial_template = db.query(QuestTemplateModel).filter(
            QuestTemplateModel.world_id == world_id,
            QuestTemplateModel.code == "first_trial"
        ).first()
    
    if first_trial_template is None:
        return None
    
    quest_state = quest_state_repo.get_by_session_and_quest(
        session_id, first_trial_template.id
    )
    
    if quest_state is None:
        return None
    
    if quest_state.status != "active":
        return None
    
    if quest_state.current_step_no == 1:
        progress = advance_quest_step(db, session_id, first_trial_template.id)
        
        if progress:
            return QuestProgressionResult(
                triggered=True,
                quest_progress=progress,
                message=f"进入试炼堂，任务「{first_trial_template.name}」推进到第{progress.step_no}步"
            )
    
    return None


def _check_npc_interaction_progression(
    db: Session,
    session_id: str,
    npc_template_id: str
) -> Optional[QuestProgressionResult]:
    """
    Check if NPC interaction triggers quest progression.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        npc_template_id: The NPC template ID
        
    Returns:
        QuestProgressionResult if progression triggered, None otherwise
    """
    return None


def check_location_access(
    db: Session,
    session_id: str,
    location_id: str
) -> bool:
    """
    Check if a location is accessible based on quest requirements.
    
    Evaluates quest completion flags and other requirements for
    gated locations.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        location_id: The location ID to check
        
    Returns:
        True if location is accessible, False otherwise
    """
    location_repo = LocationRepository(db)
    quest_state_repo = SessionQuestStateRepository(db)
    session_state_repo = SessionStateRepository(db)
    
    location = location_repo.get_by_id(location_id)
    
    if location is None:
        return False
    
    access_rules = location.access_rules or {}
    
    if not access_rules:
        return True
    
    if access_rules.get("always_accessible"):
        return True
    
    quest_requirement = access_rules.get("quest_requirement")
    if quest_requirement:
        session_state = session_state_repo.get_by_session(session_id)
        global_flags = session_state.global_flags_json if session_state else {}
        
        if quest_requirement in global_flags:
            return global_flags[quest_requirement]
        
        return False
    
    quest_completed = access_rules.get("quest_completed")
    if quest_completed:
        session = db.query(SessionModel).filter(
            SessionModel.id == session_id
        ).first()
        
        if session is None:
            return False
        
        quest_template = db.query(QuestTemplateModel).filter(
            QuestTemplateModel.world_id == session.world_id,
            QuestTemplateModel.code == quest_completed
        ).first()
        
        if quest_template is None:
            return False
        
        quest_state = quest_state_repo.get_by_session_and_quest(
            session_id, quest_template.id
        )
        
        if quest_state is None:
            return False
        
        return quest_state.status == "completed"
    
    return True


def get_quest_state_for_display(
    db: Session,
    session_id: str,
    quest_state_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get quest state formatted for display to player.
    
    Args:
        db: SQLAlchemy database session
        session_id: The session ID
        quest_state_id: The quest state ID
        
    Returns:
        Dict with quest info for display, or None if not found
    """
    quest_state_repo = SessionQuestStateRepository(db)
    quest_step_repo = QuestStepRepository(db)
    
    quest_state = quest_state_repo.get_by_id(quest_state_id)
    
    if quest_state is None:
        return None
    
    if quest_state.session_id != session_id:
        return None
    
    quest_template = db.query(QuestTemplateModel).filter(
        QuestTemplateModel.id == quest_state.quest_template_id
    ).first()
    
    if quest_template is None:
        return None
    
    current_step = quest_step_repo.get_by_quest(quest_template.id)
    current_step_obj = next(
        (s for s in current_step if s.step_no == quest_state.current_step_no),
        None
    )
    
    return {
        "quest_id": quest_state.id,
        "quest_name": quest_template.name,
        "quest_type": quest_template.quest_type,
        "status": quest_state.status,
        "current_step_no": quest_state.current_step_no,
        "current_objective": current_step_obj.objective if current_step_obj else None,
        "progress": quest_state.progress_json,
    }
