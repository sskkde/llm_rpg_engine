"""
Player Quests API routes for LLM RPG Engine.

Provides endpoints for players to view and manage their active quests.
All endpoints require valid JWT token matching session user.
"""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from starlette.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from ..storage.database import get_db
from ..storage.models import UserModel, SessionModel
from ..storage.repositories import (
    SessionRepository,
    SessionQuestStateRepository,
    QuestTemplateRepository,
    QuestStepRepository,
)
from ..services.quest_journal_service import QuestJournalService
from ..core.turn_concurrency import acquire_turn_lock
from .auth import get_current_active_user

router = APIRouter(prefix="/player/sessions/{session_id}", tags=["player-quests"])


# =============================================================================
# Pydantic Models
# =============================================================================

class QuestObjective(BaseModel):
    """A single quest objective with its completion status."""
    step_no: int
    objective: str
    completed: bool = False


class QuestListItem(BaseModel):
    """Summary view of a player's quest (used in list endpoint)."""
    quest_id: str
    title: str
    description: Optional[str] = None
    stage: int
    status: str
    objectives: List[QuestObjective] = []
    visibility: str = "hidden"


class QuestDetail(BaseModel):
    """Detailed view of a player's quest (used in detail/abandon endpoints)."""
    quest_id: str
    title: str
    description: Optional[str] = None
    quest_type: Optional[str] = None
    stage: int
    status: str
    objectives: List[QuestObjective] = []
    step_history: List[QuestObjective] = []
    progress: Dict[str, Any] = {}
    visibility: str = "hidden"
    last_updated_at: Optional[str] = None


# =============================================================================
# Helper Functions
# =============================================================================

def _get_session_and_verify_owner(
    session_id: str, current_user: UserModel, db: DBSession
) -> SessionModel:
    """Verify session exists and belongs to the current user."""
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return session


def _build_objectives(
    quest_template_id: str,
    progress_json: Dict[str, Any],
    db: DBSession,
    last_revealed_step_no: Optional[int] = None,
) -> List[QuestObjective]:
    """Build objective list with completion status from quest steps + progress.

    When last_revealed_step_no is provided, only steps with step_no <=
    last_revealed_step_no are returned.  When it is None, only step_no <= 1
    is returned (conservative default: show first step only).
    """
    step_repo = QuestStepRepository(db)
    steps = step_repo.get_by_quest(quest_template_id)

    if last_revealed_step_no is not None:
        steps = [s for s in steps if s.step_no <= last_revealed_step_no]
    else:
        steps = [s for s in steps if s.step_no <= 1]

    objectives = []
    for step in steps:
        completed = progress_json.get(f"step_{step.step_no}", False) if progress_json else False
        objectives.append(QuestObjective(
            step_no=step.step_no,
            objective=step.objective,
            completed=completed,
        ))
    return objectives


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/quests", response_model=List[QuestListItem])
def list_quests(
    session_id: str,
    status: Optional[str] = None,
    current_user: UserModel = Depends(get_current_active_user),
    db: DBSession = Depends(get_db),
):
    """
    List all quests for the player's session.

    Query Parameters:
    - status: Optional filter - 'active', 'completed', 'failed', or 'all'
      (no filter returns only active quests by default)

    Returns a list of quests with quest_id, title, description, stage, status,
    and objectives (with completion status).
    """
    _get_session_and_verify_owner(session_id, current_user, db)

    journal_service = QuestJournalService(db)
    quest_states = journal_service.list_visible_quests(
        session_id, status=status if status != "all" else None
    )

    result = []
    for qs in quest_states:
        template_repo = QuestTemplateRepository(db)
        template = template_repo.get_by_id(qs.quest_template_id)
        if not template:
            continue

        objectives = _build_objectives(
            qs.quest_template_id,
            qs.progress_json or {},
            db,
            last_revealed_step_no=qs.last_revealed_step_no,
        )

        result.append(QuestListItem(
            quest_id=qs.quest_template_id,
            title=template.name,
            description=template.summary,
            stage=qs.current_step_no,
            status=qs.status,
            objectives=objectives,
            visibility=qs.player_visibility,
        ))

    return result


@router.get("/quests/{quest_id}", response_model=QuestDetail)
def get_quest_detail(
    session_id: str,
    quest_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: DBSession = Depends(get_db),
):
    """
    Get detailed information about a specific quest.

    Returns the full quest state, template info, current objectives, and step history.
    Returns 404 if the quest is not found in this session.
    """
    _get_session_and_verify_owner(session_id, current_user, db)

    quest_state_repo = SessionQuestStateRepository(db)
    quest_state = quest_state_repo.get_by_session_and_quest(session_id, quest_id)

    if not quest_state:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Quest not found",
        )

    if quest_state.player_visibility == "hidden":
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Quest not found",
        )

    template_repo = QuestTemplateRepository(db)
    template = template_repo.get_by_id(quest_id)

    if not template:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Quest template not found",
        )

    progress = quest_state.progress_json or {}
    objectives = _build_objectives(
        quest_id, progress, db,
        last_revealed_step_no=quest_state.last_revealed_step_no,
    )
    step_history = objectives

    return QuestDetail(
        quest_id=quest_id,
        title=template.name,
        description=template.summary,
        quest_type=template.quest_type,
        stage=quest_state.current_step_no,
        status=quest_state.status,
        objectives=objectives,
        step_history=step_history,
        progress=progress,
        visibility=quest_state.player_visibility,
        last_updated_at=quest_state.last_updated_at.isoformat()
            if quest_state.last_updated_at else None,
    )


@router.delete("/quests/{quest_id}", response_model=QuestDetail)
def abandon_quest(
    session_id: str,
    quest_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: DBSession = Depends(get_db),
):
    """
    Abandon an active quest.

    Only quests with status 'active' can be abandoned.
    Completed or already-abandoned quests cannot be re-abandoned.

    Returns the updated quest state with status set to 'abandoned'.

    Concurrency protocol (W3): like the turn commit boundary, this non-turn writer
    takes the transaction-scoped session advisory lock before it reads the quest
    state, so it can never commit inside the turn's "re-verify -> commit" window.
    """
    _get_session_and_verify_owner(session_id, current_user, db)

    # Lock order is "session lock -> read -> validate -> write -> single commit".
    # Taking the lock after the ownership check but before any quest read removes the
    # old "read first, lock never" hazard: the value validated below is always the one
    # persisted under the lock. ``pg_advisory_xact_lock`` is transaction-scoped, so it
    # is held until the single commit inside ``update`` below releases it; no extra
    # commit is introduced to take the lock.
    acquire_turn_lock(db, session_id)

    # Re-read only after the lock. Expire whatever this Session already cached so the
    # status validation cannot run against a pre-lock snapshot of the quest state.
    db.expire_all()

    quest_state_repo = SessionQuestStateRepository(db)
    quest_state = quest_state_repo.get_by_session_and_quest(session_id, quest_id)

    if not quest_state:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Quest not found",
        )

    if quest_state.status != "active":
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot abandon quest with status '{quest_state.status}'. "
                "Only active quests can be abandoned."
            ),
        )

    updated = quest_state_repo.update(quest_state.id, {
        "status": "abandoned",
        "last_updated_at": datetime.now(timezone.utc),
    })

    template_repo = QuestTemplateRepository(db)
    template = template_repo.get_by_id(quest_id)

    progress = updated.progress_json or {}
    objectives = _build_objectives(
        quest_id, progress, db,
        last_revealed_step_no=updated.last_revealed_step_no,
    )

    return QuestDetail(
        quest_id=quest_id,
        title=template.name if template else "Unknown Quest",
        description=template.summary if template else None,
        quest_type=template.quest_type if template else None,
        stage=updated.current_step_no,
        status=updated.status,
        objectives=objectives,
        step_history=objectives,
        progress=progress,
        visibility=template.visibility if template else "hidden",
        last_updated_at=updated.last_updated_at.isoformat()
            if updated.last_updated_at else None,
    )
