"""
Player Inventory API - Endpoints for managing player inventory.

Provides read-only inventory access for game sessions.
Item mutations (add/remove/use) are handled by the turn system.
"""

from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..storage.database import get_db
from ..storage.models import (
    UserModel,
    SessionModel,
    SessionInventoryItemModel,
    ItemTemplateModel,
)
from ..storage.repositories import (
    SessionRepository,
    SessionInventoryItemRepository,
    ItemTemplateRepository,
)
from ..core.time_simulation_persistence import resolve_simulation_profile
from .auth import get_current_active_user


router = APIRouter(prefix="/player", tags=["player"])


class InventoryItemResponse(BaseModel):
    """Item in the player inventory list."""
    id: str
    name: str
    description: Optional[str] = None
    quantity: int
    rarity: Optional[str] = None
    item_type: Optional[str] = None
    effects: Optional[Dict[str, Any]] = None


class InventoryItemDetailResponse(BaseModel):
    """Detailed view of a single inventory item."""
    id: str
    name: str
    description: Optional[str] = None
    item_type: Optional[str] = None
    rarity: Optional[str] = None
    effects: Optional[Dict[str, Any]] = None
    quantity: int
    durability: Optional[int] = None
    bound_flag: bool = False


class InventoryCategoryBreakdown(BaseModel):
    consumable: int = 0
    equipment: int = 0
    quest_item: int = 0
    key_item: int = 0
    other: int = 0


class InventoryStatsResponse(BaseModel):
    """Inventory summary statistics."""
    total_items: int
    unique_items: int
    categories: InventoryCategoryBreakdown
    total_weight: float = 0.0


def _get_session_for_user(
    session_id: str,
    current_user: UserModel,
    db: Session,
) -> SessionModel:
    """Fetch session and verify ownership. Raises HTTPException on failure."""
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


def _build_item_response(
    inv_item: SessionInventoryItemModel,
    template: Optional[ItemTemplateModel],
) -> InventoryItemResponse:
    """Build an InventoryItemResponse from DB model + template."""
    return InventoryItemResponse(
        id=inv_item.id,
        name=template.name if template else "Unknown Item",
        description=template.description if template else None,
        quantity=inv_item.quantity,
        rarity=template.rarity if template else None,
        item_type=template.item_type if template else None,
        effects=template.effects_json if template else None,
    )


@router.get(
    "/sessions/{session_id}/inventory/stats",
    response_model=InventoryStatsResponse,
)
def get_inventory_stats(
    session_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get inventory summary statistics for the player in this session."""
    _get_session_for_user(session_id, current_user, db)

    inv_repo = SessionInventoryItemRepository(db)
    template_repo = ItemTemplateRepository(db)

    items = inv_repo.get_by_session(session_id)
    player_items = [i for i in items if i.owner_type == "player"]

    template_ids = set(i.item_template_id for i in player_items)
    templates: Dict[str, ItemTemplateModel] = {}
    for tid in template_ids:
        t = template_repo.get_by_id(tid)
        if t:
            templates[tid] = t

    total_items = sum(i.quantity for i in player_items)

    breakdown = InventoryCategoryBreakdown()
    for item in player_items:
        t = templates.get(item.item_template_id)
        cat = (t.item_type or "other") if t else "other"
        count = item.quantity
        if cat == "consumable":
            breakdown.consumable += count
        elif cat == "equipment":
            breakdown.equipment += count
        elif cat == "quest_item":
            breakdown.quest_item += count
        elif cat == "key_item":
            breakdown.key_item += count
        else:
            breakdown.other += count

    return InventoryStatsResponse(
        total_items=total_items,
        unique_items=len(template_ids),
        categories=breakdown,
    )


@router.get(
    "/sessions/{session_id}/inventory",
    response_model=List[InventoryItemResponse],
)
def list_inventory(
    session_id: str,
    category: Optional[str] = Query(
        None,
        description="Filter by item type (consumable, equipment, quest_item, key_item)",
    ),
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all items in the player inventory for this session."""
    _get_session_for_user(session_id, current_user, db)

    inv_repo = SessionInventoryItemRepository(db)
    template_repo = ItemTemplateRepository(db)

    items = inv_repo.get_by_session(session_id)
    player_items = [i for i in items if i.owner_type == "player"]

    result: List[InventoryItemResponse] = []
    for inv_item in player_items:
        template = template_repo.get_by_id(inv_item.item_template_id)

        if category and template:
            if template.item_type != category:
                continue
        elif category and not template:
            continue

        result.append(_build_item_response(inv_item, template))

    return result


@router.get(
    "/sessions/{session_id}/inventory/{item_id}",
    response_model=InventoryItemDetailResponse,
)
def get_inventory_item(
    session_id: str,
    item_id: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get detailed information about a specific inventory item."""
    session = _get_session_for_user(session_id, current_user, db)

    inv_repo = SessionInventoryItemRepository(db)
    inv_item = inv_repo.get_by_id(item_id)

    if not inv_item or inv_item.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found in inventory",
        )

    if (
        inv_item.owner_type != "player"
        and resolve_simulation_profile(db, session) is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found in inventory",
        )

    template_repo = ItemTemplateRepository(db)
    template = template_repo.get_by_id(inv_item.item_template_id)

    return InventoryItemDetailResponse(
        id=inv_item.id,
        name=template.name if template else "Unknown Item",
        description=template.description if template else None,
        item_type=template.item_type if template else None,
        rarity=template.rarity if template else None,
        effects=template.effects_json if template else None,
        quantity=inv_item.quantity,
        durability=inv_item.durability,
        bound_flag=inv_item.bound_flag,
    )
