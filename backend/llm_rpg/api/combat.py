from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from ..core.combat import (
    get_combat_manager,
    CombatSession,
    CombatParticipant,
    CombatAction,
    CombatRound,
    CombatStatus,
    ActionType,
    ActorType,
    CombatActionPayload,
)
from ..storage.database import get_db
from ..storage.models import UserModel, SessionModel, CombatSessionModel, CombatRoundModel, CombatActionModel
from ..storage.repositories import SessionRepository, CombatSessionRepository, CombatRoundRepository, CombatActionRepository
from .auth import get_current_active_user

router = APIRouter(prefix="/combat", tags=["combat"])


class CombatParticipantRequest(BaseModel):
    actor_id: str = Field(..., description="Unique actor identifier")
    actor_type: str = Field(..., description="Type: player, npc, or environment")
    name: str = Field(..., description="Display name")
    hp: int = Field(default=100)
    max_hp: int = Field(default=100)
    initiative: int = Field(default=0)


class CombatActionRequest(BaseModel):
    action_type: str = Field(..., description="Type: attack, defend, skill, item, flee")
    target_id: Optional[str] = Field(None, description="Target actor ID")
    skill_id: Optional[str] = Field(None, description="Skill ID if using skill")
    item_id: Optional[str] = Field(None, description="Item ID if using item")
    description: Optional[str] = Field(None, description="Player description of action")


class CombatParticipantResponse(BaseModel):
    actor_id: str
    actor_type: str
    name: str
    hp: int
    max_hp: int
    initiative: int
    is_active: bool

    class Config:
        from_attributes = True


class CombatActionResponse(BaseModel):
    action_id: str
    actor_id: str
    actor_type: str
    action_type: str
    target_id: Optional[str] = None
    resolution: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CombatRoundResponse(BaseModel):
    round_id: str
    round_no: int
    initiative_order: List[str]
    actions: List[CombatActionResponse]
    is_complete: bool

    class Config:
        from_attributes = True


class CombatSessionResponse(BaseModel):
    combat_id: str
    session_id: str
    location_id: Optional[str] = None
    status: str
    participants: List[CombatParticipantResponse]
    current_round: CombatRoundResponse
    current_round_no: int
    winner: Optional[str] = None
    started_at: datetime

    class Config:
        from_attributes = True


class StartCombatRequest(BaseModel):
    session_id: str = Field(..., description="Game session ID")
    location_id: Optional[str] = Field(None, description="Location where combat occurs")
    participants: List[CombatParticipantRequest] = Field(..., description="Combat participants")
    narration_context: Optional[str] = Field(None, description="Context for LLM narration")


class StartCombatResponse(BaseModel):
    combat_id: str
    session_id: str
    status: str
    current_round_no: int
    participants: List[CombatParticipantResponse]
    message: str = "Combat started successfully"


class SubmitActionResponse(BaseModel):
    action_id: str
    combat_id: str
    round_no: int
    resolution: Dict[str, Any]
    combat_status: str
    message: str = "Action submitted successfully"


class EndCombatRequest(BaseModel):
    status: str = Field(..., description="End status: player_won, player_lost, escaped, draw")
    winner: Optional[str] = Field(None, description="Winner actor ID")


class EndCombatResponse(BaseModel):
    combat_id: str
    status: str
    winner: Optional[str] = None
    duration_rounds: int
    message: str = "Combat ended"


class CombatEventsResponse(BaseModel):
    combat_id: str
    events: List[Dict[str, Any]]


@router.post("/start", response_model=StartCombatResponse, status_code=status.HTTP_201_CREATED)
def start_combat(
    request: StartCombatRequest,
    current_user: UserModel = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(request.session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    manager = get_combat_manager()

    import uuid
    combat_id = str(uuid.uuid4())

    participants = [
        CombatParticipant(
            actor_id=p.actor_id,
            actor_type=ActorType(p.actor_type),
            name=p.name,
            hp=p.hp,
            max_hp=p.max_hp,
            initiative=p.initiative
        )
        for p in request.participants
    ]

    combat = manager.create_combat(
        combat_id=combat_id,
        session_id=request.session_id,
        location_id=request.location_id,
        participants=participants,
        narration_context=request.narration_context
    )

    combat_repo = CombatSessionRepository(db)
    combat_repo.create({
        "id": combat_id,
        "session_id": request.session_id,
        "location_id": request.location_id,
        "combat_status": "active",
        "started_at": datetime.now()
    })

    round_repo = CombatRoundRepository(db)
    round_1 = combat.rounds[0]
    round_repo.create({
        "id": round_1.round_id,
        "combat_session_id": combat_id,
        "round_no": 1,
        "initiative_order_json": round_1.initiative_order
    })

    return StartCombatResponse(
        combat_id=combat.combat_id,
        session_id=combat.session_id,
        status=combat.status.value,
        current_round_no=combat.current_round_no,
        participants=[
            CombatParticipantResponse(
                actor_id=p.actor_id,
                actor_type=p.actor_type.value,
                name=p.name,
                hp=p.hp,
                max_hp=p.max_hp,
                initiative=p.initiative,
                is_active=p.is_active
            )
            for p in combat.participants.values()
        ]
    )


@router.get("/{combat_id}", response_model=CombatSessionResponse)
def get_combat_state(
    combat_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    combat_repo = CombatSessionRepository(db)
    combat_record = combat_repo.get_by_id(combat_id)

    if not combat_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Combat not found"
        )

    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(combat_record.session_id)

    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    manager = get_combat_manager()
    combat = manager.get_combat(combat_id)

    if not combat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Combat session not in memory"
        )

    current_round = manager.get_current_round(combat_id)

    return CombatSessionResponse(
        combat_id=combat.combat_id,
        session_id=combat.session_id,
        location_id=combat.location_id,
        status=combat.status.value,
        participants=[
            CombatParticipantResponse(
                actor_id=p.actor_id,
                actor_type=p.actor_type.value,
                name=p.name,
                hp=p.hp,
                max_hp=p.max_hp,
                initiative=p.initiative,
                is_active=p.is_active
            )
            for p in combat.participants.values()
        ],
        current_round=CombatRoundResponse(
            round_id=current_round.round_id,
            round_no=current_round.round_no,
            initiative_order=current_round.initiative_order,
            actions=[
                CombatActionResponse(
                    action_id=a.action_id,
                    actor_id=a.actor_id,
                    actor_type=a.actor_type.value,
                    action_type=a.action_type.value,
                    target_id=a.payload.target_id,
                    resolution=a.resolution,
                    created_at=a.created_at
                )
                for a in current_round.actions
            ],
            is_complete=current_round.is_complete
        ) if current_round else None,
        current_round_no=combat.current_round_no,
        winner=combat.winner,
        started_at=combat.started_at
    )


@router.post("/{combat_id}/turn", response_model=SubmitActionResponse)
def submit_turn(
    combat_id: str,
    request: CombatActionRequest,
    actor_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    combat_repo = CombatSessionRepository(db)
    combat_record = combat_repo.get_by_id(combat_id)

    if not combat_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Combat not found"
        )

    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(combat_record.session_id)

    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    manager = get_combat_manager()

    try:
        action_type = ActionType(request.action_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action type: {request.action_type}"
        )

    payload = CombatActionPayload(
        target_id=request.target_id,
        skill_id=request.skill_id,
        item_id=request.item_id,
        description=request.description
    )

    is_valid, error_msg = manager.validate_action(
        combat_id=combat_id,
        actor_id=actor_id,
        action_type=action_type,
        payload=payload
    )

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    combat = manager.get_combat(combat_id)
    participant = combat.participants.get(actor_id)
    actor_type = participant.actor_type if participant else ActorType.PLAYER

    action = manager.commit_action(
        combat_id=combat_id,
        actor_id=actor_id,
        actor_type=actor_type,
        action_type=action_type,
        payload=payload
    )

    action_repo = CombatActionRepository(db)
    action_repo.create({
        "id": action.action_id,
        "combat_round_id": manager.get_current_round(combat_id).round_id,
        "actor_type": action_type.value,
        "actor_ref_id": actor_id,
        "action_type": action_type.value,
        "action_payload_json": payload.model_dump(exclude_none=True),
        "resolution_json": action.resolution
    })

    if combat.status != CombatStatus.ACTIVE:
        combat_repo.update_status(combat_id, combat.status.value, combat.winner)

    return SubmitActionResponse(
        action_id=action.action_id,
        combat_id=combat_id,
        round_no=manager.get_current_round(combat_id).round_no,
        resolution=action.resolution,
        combat_status=combat.status.value
    )


@router.post("/{combat_id}/end", response_model=EndCombatResponse)
def end_combat(
    combat_id: str,
    request: EndCombatRequest,
    current_user: UserModel = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    combat_repo = CombatSessionRepository(db)
    combat_record = combat_repo.get_by_id(combat_id)

    if not combat_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Combat not found"
        )

    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(combat_record.session_id)

    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    try:
        end_status = CombatStatus(request.status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status: {request.status}"
        )

    manager = get_combat_manager()
    combat = manager.end_combat(combat_id, end_status, request.winner)

    combat_repo.update_status(combat_id, end_status.value, request.winner)

    return EndCombatResponse(
        combat_id=combat_id,
        status=end_status.value,
        winner=request.winner,
        duration_rounds=combat.current_round_no
    )


@router.get("/{combat_id}/events", response_model=CombatEventsResponse)
def get_combat_events(
    combat_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    combat_repo = CombatSessionRepository(db)
    combat_record = combat_repo.get_by_id(combat_id)

    if not combat_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Combat not found"
        )

    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(combat_record.session_id)

    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    manager = get_combat_manager()
    events = manager.get_combat_events(combat_id)

    return CombatEventsResponse(
        combat_id=combat_id,
        events=[
            {
                "event_type": e.event_type,
                "round_no": e.round_no,
                "actor_id": e.actor_id,
                "details": e.details,
                "timestamp": e.timestamp.isoformat()
            }
            for e in events
        ]
    )
