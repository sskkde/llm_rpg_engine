from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..storage.database import get_db
from ..storage.models import UserModel, SessionModel, SessionStateModel, SessionPlayerStateModel, EventLogModel
from ..storage.repositories import SessionRepository, SessionStateRepository, SessionPlayerStateRepository, EventLogRepository
from .auth import get_current_active_user
from .turn_output import recommended_actions_from_result

router = APIRouter(prefix="/sessions", tags=["sessions"])


class PlayerStateSnapshot(BaseModel):
    realm_stage: str
    hp: int
    max_hp: int
    stamina: int
    spirit_power: int
    conditions: List[str] = []


class SessionStateSnapshot(BaseModel):
    current_time: Optional[str] = None
    time_phase: Optional[str] = None
    active_mode: str
    current_location_id: Optional[str] = None


class SessionSnapshotResponse(BaseModel):
    session_id: str
    user_id: str
    world_id: str
    status: str
    save_slot_id: Optional[str] = None
    started_at: datetime
    last_played_at: datetime
    session_state: Optional[SessionStateSnapshot] = None
    player_state: Optional[PlayerStateSnapshot] = None


class LoadSessionResponse(BaseModel):
    session_id: str
    world_id: str
    message: str = "Session loaded successfully"


class AdventureLogEntryResponse(BaseModel):
    id: str
    turn_no: int
    event_type: str
    action: Optional[str] = None
    narration: str
    recommended_actions: List[str] = []
    occurred_at: datetime


class SessionListItem(BaseModel):
    id: str
    world_id: str
    save_slot_id: Optional[str] = None
    status: str
    started_at: datetime
    last_played_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[SessionListItem])
def list_sessions(
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    session_repo = SessionRepository(db)
    sessions = session_repo.get_by_user(current_user.id)
    
    return [
        SessionListItem(
            id=s.id,
            world_id=s.world_id,
            save_slot_id=s.save_slot_id,
            status=s.status,
            started_at=s.started_at,
            last_played_at=s.last_played_at
        )
        for s in sessions
    ]


@router.get("/{session_id}/snapshot", response_model=SessionSnapshotResponse)
def get_session_snapshot(
    session_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    
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
    
    state_repo = SessionStateRepository(db)
    player_repo = SessionPlayerStateRepository(db)
    
    session_state = state_repo.get_by_session(session_id)
    player_state = player_repo.get_by_session(session_id)
    
    snapshot = SessionSnapshotResponse(
        session_id=session.id,
        user_id=session.user_id,
        world_id=session.world_id,
        status=session.status,
        save_slot_id=session.save_slot_id,
        started_at=session.started_at,
        last_played_at=session.last_played_at,
    )
    
    if session_state:
        snapshot.session_state = SessionStateSnapshot(
            current_time=session_state.current_time,
            time_phase=session_state.time_phase,
            active_mode=session_state.active_mode,
            current_location_id=session_state.current_location_id
        )
    
    if player_state:
        conditions = player_state.conditions_json if player_state.conditions_json else []
        snapshot.player_state = PlayerStateSnapshot(
            realm_stage=player_state.realm_stage,
            hp=player_state.hp,
            max_hp=player_state.max_hp,
            stamina=player_state.stamina,
            spirit_power=player_state.spirit_power,
            conditions=conditions
        )
    
    return snapshot


@router.post("/{session_id}/load", response_model=LoadSessionResponse)
def load_session(
    session_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    
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
    
    session_repo.update_last_played(session_id)
    
    return LoadSessionResponse(
        session_id=session.id,
        world_id=session.world_id
    )


@router.get("/{session_id}/adventure-log", response_model=List[AdventureLogEntryResponse])
def get_adventure_log(
    session_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    
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
    
    event_log_repo = EventLogRepository(db)
    event_log_repo.ensure_initial_scene(session_id)
    
    entries = event_log_repo.get_by_session_ordered(session_id)
    
    return [
        AdventureLogEntryResponse(
            id=entry.id,
            turn_no=entry.turn_no,
            event_type=entry.event_type,
            action=entry.input_text,
            narration=entry.narrative_text or "",
            recommended_actions=recommended_actions_from_result(entry.result_json),
            occurred_at=entry.occurred_at
        )
        for entry in entries
    ]
