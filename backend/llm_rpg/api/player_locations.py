"""Player Locations API - endpoints for querying known/accessible locations."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..storage.database import get_db
from ..storage.models import (
    LocationModel,
    SessionModel,
    SessionNPCStateModel,
    SessionInventoryItemModel,
    UserModel,
)
from ..storage.repositories import (
    SessionRepository,
    SessionStateRepository,
    SessionNPCStateRepository,
    SessionInventoryItemRepository,
    LocationRepository,
)
from .auth import get_current_active_user

router = APIRouter(prefix="/player/sessions", tags=["player-locations"])


def _verify_session_ownership(
    session_id: str,
    current_user: UserModel,
    db: Session,
) -> SessionModel:
    session_repo = SessionRepository(db)
    session = session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return session


def _is_location_hidden(location: LocationModel) -> bool:
    tags = location.tags or []
    if isinstance(tags, list):
        return "hidden" in tags or "secret" in tags
    return False


def _derive_danger_level(location: LocationModel) -> float:
    tags = location.tags or []
    access_rules = location.access_rules or {}

    if isinstance(tags, list):
        if "dangerous" in tags:
            return 0.7
        if "safe" in tags:
            return 0.0

    if isinstance(access_rules, dict):
        if access_rules.get("combat_level"):
            return 0.5
        if access_rules.get("boss_unlocked"):
            return 0.9

    return 0.0


def _accessible_location_ids(
    current_location_id: str,
    all_locations: List[LocationModel],
) -> List[str]:
    accessible: List[str] = []
    for loc in all_locations:
        if loc.id == current_location_id:
            accessible.append(loc.id)
            continue
        rules = loc.access_rules or {}
        if not isinstance(rules, dict):
            accessible.append(loc.id)
            continue
        if rules.get("always_accessible") is True:
            accessible.append(loc.id)
            continue
        has_blocker = any(
            v is not None and v is not False
            for v in rules.values()
        )
        if not has_blocker:
            accessible.append(loc.id)
    return accessible


class LocationListItem(BaseModel):
    location_id: str
    name: str
    description: Optional[str] = None
    connections: List[str] = []
    is_current: bool = False
    danger_level: float = 0.0


class NPCPresent(BaseModel):
    npc_id: str
    name: str
    mood: Optional[str] = None
    status_flags: Optional[dict] = None


class ItemPresent(BaseModel):
    item_id: str
    name: str
    quantity: int = 1


class LocationDetailResponse(BaseModel):
    location_id: str
    name: str
    description: Optional[str] = None
    tags: List[str] = []
    access_rules: Optional[dict] = None
    danger_level: float = 0.0
    connections: List[str] = []
    is_current: bool = False
    npcs_present: List[NPCPresent] = []
    items_present: List[ItemPresent] = []


@router.get(
    "/{session_id}/locations/current",
    response_model=LocationDetailResponse,
)
def get_current_location(
    session_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    session = _verify_session_ownership(session_id, current_user, db)

    state_repo = SessionStateRepository(db)
    session_state = state_repo.get_by_session(session_id)
    current_location_id = session_state.current_location_id if session_state else None

    if not current_location_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No current location set for this session",
        )

    location_repo = LocationRepository(db)
    location = location_repo.get_by_id(current_location_id)
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location {current_location_id} not found",
        )

    world_locations = location_repo.get_by_world(session.world_id)
    accessible_ids = _accessible_location_ids(current_location_id, world_locations)
    connections = [lid for lid in accessible_ids if lid != current_location_id]

    npc_repo = SessionNPCStateRepository(db)
    session_npcs = npc_repo.get_by_session(session_id)
    npcs_present = [
        NPCPresent(
            npc_id=npc.npc_template_id,
            name=getattr(npc.npc_template, "name", npc.npc_template_id) if npc.npc_template else npc.npc_template_id,
            mood=getattr(npc, "short_memory_summary", None),
            status_flags=npc.status_flags,
        )
        for npc in session_npcs
        if npc.current_location_id == current_location_id
    ]

    item_repo = SessionInventoryItemRepository(db)
    session_items = item_repo.get_by_session(session_id)
    items_present = [
        ItemPresent(
            item_id=item.item_template_id,
            name=getattr(item.item_template, "name", item.item_template_id) if item.item_template else item.item_template_id,
            quantity=item.quantity,
        )
        for item in session_items
        if item.owner_type == "location"
        and item.owner_ref_id == current_location_id
    ]

    return LocationDetailResponse(
        location_id=location.id,
        name=location.name,
        description=location.description,
        tags=location.tags or [],
        access_rules=location.access_rules,
        danger_level=_derive_danger_level(location),
        connections=connections,
        is_current=True,
        npcs_present=npcs_present,
        items_present=items_present,
    )


@router.get(
    "/{session_id}/locations/{location_id}",
    response_model=LocationDetailResponse,
)
def get_location_detail(
    session_id: str,
    location_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    session = _verify_session_ownership(session_id, current_user, db)

    location_repo = LocationRepository(db)
    location = location_repo.get_by_id(location_id)
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found",
        )

    if location.world_id != session.world_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found in this world",
        )

    state_repo = SessionStateRepository(db)
    session_state = state_repo.get_by_session(session_id)
    current_location_id = session_state.current_location_id if session_state else None
    is_current = (location.id == current_location_id)

    if _is_location_hidden(location) and not is_current:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found",
        )

    world_locations = location_repo.get_by_world(session.world_id)
    accessible_ids = _accessible_location_ids(location.id, world_locations)
    connections = [lid for lid in accessible_ids if lid != location.id]

    npc_repo = SessionNPCStateRepository(db)
    session_npcs = npc_repo.get_by_session(session_id)
    npcs_present = [
        NPCPresent(
            npc_id=npc.npc_template_id,
            name=getattr(npc.npc_template, "name", npc.npc_template_id) if npc.npc_template else npc.npc_template_id,
            mood=getattr(npc, "short_memory_summary", None),
            status_flags=npc.status_flags,
        )
        for npc in session_npcs
        if npc.current_location_id == location_id
    ]

    item_repo = SessionInventoryItemRepository(db)
    session_items = item_repo.get_by_session(session_id)
    items_present = [
        ItemPresent(
            item_id=item.item_template_id,
            name=getattr(item.item_template, "name", item.item_template_id) if item.item_template else item.item_template_id,
            quantity=item.quantity,
        )
        for item in session_items
        if item.owner_type == "location"
        and item.owner_ref_id == location_id
    ]

    return LocationDetailResponse(
        location_id=location.id,
        name=location.name,
        description=location.description,
        tags=location.tags or [],
        access_rules=location.access_rules,
        danger_level=_derive_danger_level(location),
        connections=connections,
        is_current=is_current,
        npcs_present=npcs_present,
        items_present=items_present,
    )


@router.get(
    "/{session_id}/locations",
    response_model=List[LocationListItem],
)
def list_locations(
    session_id: str,
    accessible: Optional[bool] = Query(None, description="Filter to only accessible locations"),
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    session = _verify_session_ownership(session_id, current_user, db)

    state_repo = SessionStateRepository(db)
    session_state = state_repo.get_by_session(session_id)
    current_location_id = session_state.current_location_id if session_state else None

    location_repo = LocationRepository(db)
    world_locations = location_repo.get_by_world(session.world_id)

    accessible_ids: Optional[List[str]] = None
    if accessible is True and current_location_id:
        accessible_ids = _accessible_location_ids(current_location_id, world_locations)

    result: List[LocationListItem] = []
    for loc in world_locations:
        is_current = (loc.id == current_location_id)
        if _is_location_hidden(loc) and not is_current:
            continue

        if accessible_ids is not None and loc.id not in accessible_ids:
            continue

        connections = [
            other.id for other in world_locations
            if other.id != loc.id and not _is_location_hidden(other)
        ]

        result.append(LocationListItem(
            location_id=loc.id,
            name=loc.name,
            description=loc.description,
            connections=connections,
            is_current=is_current,
            danger_level=_derive_danger_level(loc),
        ))

    return result
