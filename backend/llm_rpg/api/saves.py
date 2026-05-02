from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..storage.database import get_db
from ..storage.models import UserModel, SaveSlotModel, SessionModel
from ..storage.repositories import SaveSlotRepository, SessionRepository, WorldRepository
from .auth import get_current_active_user

router = APIRouter(prefix="/saves", tags=["saves"])


class SaveSlotCreateRequest(BaseModel):
    slot_number: int = Field(..., ge=1, le=10, description="Save slot number (1-10)")
    name: Optional[str] = Field(None, max_length=100, description="Optional save slot name")


class SaveSlotUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=100, description="Optional save slot name")


class SaveSlotResponse(BaseModel):
    id: str
    user_id: str
    slot_number: int
    name: Optional[str] = None
    created_at: datetime
    session_count: int = 0

    class Config:
        from_attributes = True


class SessionSummaryResponse(BaseModel):
    id: str
    world_id: str
    status: str
    started_at: datetime
    last_played_at: datetime

    class Config:
        from_attributes = True


class SaveSlotDetailResponse(BaseModel):
    id: str
    user_id: str
    slot_number: int
    name: Optional[str] = None
    created_at: datetime
    sessions: List[SessionSummaryResponse] = []

    class Config:
        from_attributes = True


class ManualSaveRequest(BaseModel):
    world_id: str = Field(..., description="World ID to create session in")
    save_slot_id: Optional[str] = Field(None, description="Optional save slot to attach the new session to")
    current_chapter_id: Optional[str] = Field(None, description="Optional chapter ID")


class ManualSaveResponse(BaseModel):
    session_id: str
    save_slot_id: str
    message: str = "Game saved successfully"


@router.post("", response_model=SaveSlotResponse, status_code=status.HTTP_201_CREATED)
def create_save_slot(
    request: SaveSlotCreateRequest,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    save_repo = SaveSlotRepository(db)
    
    existing = save_repo.get_by_user_and_slot(current_user.id, request.slot_number)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Save slot {request.slot_number} already exists"
        )
    
    slot_data = {
        "user_id": current_user.id,
        "slot_number": request.slot_number,
        "name": request.name,
    }
    
    slot = save_repo.create(slot_data)
    
    return SaveSlotResponse(
        id=slot.id,
        user_id=slot.user_id,
        slot_number=slot.slot_number,
        name=slot.name,
        created_at=slot.created_at,
        session_count=len(slot.sessions) if hasattr(slot, 'sessions') else 0
    )


@router.get("", response_model=List[SaveSlotResponse])
def list_save_slots(
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    save_repo = SaveSlotRepository(db)
    slots = save_repo.get_by_user(current_user.id)
    
    return [
        SaveSlotResponse(
            id=slot.id,
            user_id=slot.user_id,
            slot_number=slot.slot_number,
            name=slot.name,
            created_at=slot.created_at,
            session_count=len(slot.sessions) if slot.sessions else 0
        )
        for slot in slots
    ]


@router.get("/{slot_id}", response_model=SaveSlotDetailResponse)
def get_save_slot(
    slot_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    save_repo = SaveSlotRepository(db)
    slot = save_repo.get_by_id(slot_id)
    
    if not slot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Save slot not found"
        )
    
    if slot.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    sessions = [
        SessionSummaryResponse(
            id=s.id,
            world_id=s.world_id,
            status=s.status,
            started_at=s.started_at,
            last_played_at=s.last_played_at
        )
        for s in (slot.sessions or [])
    ]
    
    return SaveSlotDetailResponse(
        id=slot.id,
        user_id=slot.user_id,
        slot_number=slot.slot_number,
        name=slot.name,
        created_at=slot.created_at,
        sessions=sessions
    )


@router.put("/{slot_id}", response_model=SaveSlotResponse)
def update_save_slot(
    slot_id: str,
    request: SaveSlotUpdateRequest,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    save_repo = SaveSlotRepository(db)
    slot = save_repo.get_by_id(slot_id)
    
    if not slot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Save slot not found"
        )
    
    if slot.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    update_data = {}
    if request.name is not None:
        update_data["name"] = request.name
    
    updated = save_repo.update(slot_id, update_data)
    
    return SaveSlotResponse(
        id=updated.id,
        user_id=updated.user_id,
        slot_number=updated.slot_number,
        name=updated.name,
        created_at=updated.created_at,
        session_count=len(updated.sessions) if updated.sessions else 0
    )


@router.delete("/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_save_slot(
    slot_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    save_repo = SaveSlotRepository(db)
    slot = save_repo.get_by_id(slot_id)
    
    if not slot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Save slot not found"
        )
    
    if slot.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    save_repo.delete(slot_id)
    return None


@router.post("/manual-save", response_model=ManualSaveResponse, status_code=status.HTTP_201_CREATED)
def create_manual_save(
    request: ManualSaveRequest,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    world_repo = WorldRepository(db)
    world = world_repo.get_by_id(request.world_id)
    
    if not world:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="World not found"
        )
    
    save_repo = SaveSlotRepository(db)
    
    if request.save_slot_id:
        slot = save_repo.get_by_id(request.save_slot_id)
        if not slot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Save slot not found"
            )
        if slot.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
    else:
        existing_slots = save_repo.get_by_user(current_user.id)
        if not existing_slots:
            slot = save_repo.create({
                "user_id": current_user.id,
                "slot_number": 1,
                "name": "Auto-created save slot"
            })
        else:
            slot = existing_slots[0]
    
    session_repo = SessionRepository(db)
    session = session_repo.create({
        "user_id": current_user.id,
        "save_slot_id": slot.id,
        "world_id": request.world_id,
        "current_chapter_id": request.current_chapter_id,
        "status": "active",
    })
    
    return ManualSaveResponse(
        session_id=session.id,
        save_slot_id=slot.id,
        message="Game saved successfully"
    )
