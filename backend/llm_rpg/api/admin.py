"""
Admin API routes for LLM RPG Engine.

Provides CRUD operations for world configuration, templates, and content management.
All endpoints require admin role authentication.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from ..storage.database import get_db
from ..storage.models import (
    UserModel, WorldModel, ChapterModel, LocationModel,
    NPCTemplateModel, ItemTemplateModel, QuestTemplateModel,
    EventTemplateModel, PromptTemplateModel
)
from ..storage.repositories import (
    WorldRepository, ChapterRepository, LocationRepository,
    NPCTemplateRepository, ItemTemplateRepository, QuestTemplateRepository,
    EventTemplateRepository, PromptTemplateRepository
)
from .auth import get_current_active_user

router = APIRouter(prefix="/admin", tags=["admin"])


# =============================================================================
# Helper Functions
# =============================================================================

async def require_admin(
    current_user: UserModel = Depends(get_current_active_user)
) -> UserModel:
    """
    Dependency to require admin role.

    Raises:
        HTTPException: If user is not an admin
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


def require_admin_role(user: UserModel) -> None:
    """
    Verify user has admin role.

    Raises:
        HTTPException: If user is not an admin
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )


# =============================================================================
# Pydantic Models
# =============================================================================

# ----- World Models -----

class WorldListItem(BaseModel):
    id: str
    code: str
    name: str
    genre: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class WorldDetail(WorldListItem):
    lore_summary: Optional[str] = None


class WorldUpdateRequest(BaseModel):
    name: Optional[str] = None
    genre: Optional[str] = None
    lore_summary: Optional[str] = None
    status: Optional[str] = None


# ----- Chapter Models -----

class ChapterListItem(BaseModel):
    id: str
    world_id: str
    chapter_no: int
    name: str
    summary: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChapterDetail(ChapterListItem):
    start_conditions: Dict[str, Any] = {}


class ChapterUpdateRequest(BaseModel):
    name: Optional[str] = None
    summary: Optional[str] = None
    start_conditions: Optional[Dict[str, Any]] = None


# ----- Location Models -----

class LocationListItem(BaseModel):
    id: str
    world_id: str
    chapter_id: Optional[str] = None
    code: str
    name: str
    tags: List[str] = []
    created_at: datetime

    class Config:
        from_attributes = True


class LocationDetail(LocationListItem):
    description: Optional[str] = None
    access_rules: Dict[str, Any] = {}


class LocationUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    access_rules: Optional[Dict[str, Any]] = None


# ----- NPC Template Models -----

class NPCTemplateListItem(BaseModel):
    id: str
    world_id: str
    code: str
    name: str
    role_type: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class NPCTemplateDetail(NPCTemplateListItem):
    public_identity: Optional[str] = None
    hidden_identity: Optional[str] = None
    personality: Optional[str] = None
    speech_style: Optional[str] = None
    goals: List[str] = []


class NPCTemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    role_type: Optional[str] = None
    public_identity: Optional[str] = None
    hidden_identity: Optional[str] = None
    personality: Optional[str] = None
    speech_style: Optional[str] = None
    goals: Optional[List[str]] = None


# ----- Item Template Models -----

class ItemTemplateListItem(BaseModel):
    id: str
    world_id: str
    code: str
    name: str
    item_type: Optional[str] = None
    rarity: str
    created_at: datetime

    class Config:
        from_attributes = True


class ItemTemplateDetail(ItemTemplateListItem):
    description: Optional[str] = None
    effects: Dict[str, Any] = {}


class ItemTemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    item_type: Optional[str] = None
    rarity: Optional[str] = None
    description: Optional[str] = None
    effects: Optional[Dict[str, Any]] = None


# ----- Quest Template Models -----

class QuestTemplateListItem(BaseModel):
    id: str
    world_id: str
    code: str
    name: str
    quest_type: Optional[str] = None
    visibility: str
    created_at: datetime

    class Config:
        from_attributes = True


class QuestTemplateDetail(QuestTemplateListItem):
    summary: Optional[str] = None


class QuestTemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    quest_type: Optional[str] = None
    summary: Optional[str] = None
    visibility: Optional[str] = None


# ----- Event Template Models -----

class EventTemplateListItem(BaseModel):
    id: str
    world_id: Optional[str] = None
    code: str
    name: str
    event_type: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class EventTemplateDetail(EventTemplateListItem):
    trigger_conditions: Dict[str, Any] = {}
    effects: Dict[str, Any] = {}


class EventTemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    event_type: Optional[str] = None
    trigger_conditions: Optional[Dict[str, Any]] = None
    effects: Optional[Dict[str, Any]] = None


# ----- Prompt Template Models -----

class PromptTemplateListItem(BaseModel):
    id: str
    world_id: Optional[str] = None
    prompt_type: str
    version: str
    enabled_flag: bool
    created_at: datetime

    class Config:
        from_attributes = True


class PromptTemplateDetail(PromptTemplateListItem):
    content: str


class PromptTemplateUpdateRequest(BaseModel):
    content: Optional[str] = None
    version: Optional[str] = None
    enabled_flag: Optional[bool] = None


# =============================================================================
# World Routes
# =============================================================================

@router.get("/worlds", response_model=List[WorldListItem])
def list_worlds(
    skip: int = 0,
    limit: int = 100,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    List all worlds.

    Returns a paginated list of world configurations.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = WorldRepository(db)
    worlds = repo.get_all(skip=skip, limit=limit)
    return [WorldListItem.model_validate(w) for w in worlds]


@router.get("/worlds/{world_id}", response_model=WorldDetail)
def get_world(
    world_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get world details.

    Returns detailed information about a specific world.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = WorldRepository(db)
    world = repo.get_by_id(world_id)

    if not world:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="World not found"
        )

    return WorldDetail.model_validate(world)


@router.patch("/worlds/{world_id}", response_model=WorldDetail)
def update_world(
    world_id: str,
    request: WorldUpdateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Update world configuration.

    Updates world properties. Only provided fields are modified.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = WorldRepository(db)
    world = repo.get_by_id(world_id)

    if not world:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="World not found"
        )

    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        return WorldDetail.model_validate(world)

    updated = repo.update(world_id, update_data)
    return WorldDetail.model_validate(updated)


# =============================================================================
# Chapter Routes
# =============================================================================

@router.get("/chapters", response_model=List[ChapterListItem])
def list_chapters(
    world_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    List all chapters.

    Returns a paginated list of chapter configurations.
    Optionally filter by world_id.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = ChapterRepository(db)

    if world_id:
        chapters = repo.get_by_world(world_id)
    else:
        chapters = repo.get_all(skip=skip, limit=limit)

    return [ChapterListItem.model_validate(c) for c in chapters]


@router.get("/chapters/{chapter_id}", response_model=ChapterDetail)
def get_chapter(
    chapter_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get chapter details.

    Returns detailed information about a specific chapter.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = ChapterRepository(db)
    chapter = repo.get_by_id(chapter_id)

    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )

    return ChapterDetail.model_validate(chapter)


@router.patch("/chapters/{chapter_id}", response_model=ChapterDetail)
def update_chapter(
    chapter_id: str,
    request: ChapterUpdateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Update chapter configuration.

    Updates chapter properties. Only provided fields are modified.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = ChapterRepository(db)
    chapter = repo.get_by_id(chapter_id)

    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )

    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        return ChapterDetail.model_validate(chapter)

    updated = repo.update(chapter_id, update_data)
    return ChapterDetail.model_validate(updated)


# =============================================================================
# Location Routes
# =============================================================================

@router.get("/locations", response_model=List[LocationListItem])
def list_locations(
    world_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    List all locations.

    Returns a paginated list of location configurations.
    Optionally filter by world_id or chapter_id.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = LocationRepository(db)

    if chapter_id:
        locations = repo.get_by_chapter(chapter_id)
    elif world_id:
        locations = repo.get_by_world(world_id)
    else:
        locations = repo.get_all(skip=skip, limit=limit)

    return [LocationListItem.model_validate(loc) for loc in locations]


@router.get("/locations/{location_id}", response_model=LocationDetail)
def get_location(
    location_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get location details.

    Returns detailed information about a specific location.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = LocationRepository(db)
    location = repo.get_by_id(location_id)

    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found"
        )

    return LocationDetail.model_validate(location)


@router.patch("/locations/{location_id}", response_model=LocationDetail)
def update_location(
    location_id: str,
    request: LocationUpdateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Update location configuration.

    Updates location properties. Only provided fields are modified.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = LocationRepository(db)
    location = repo.get_by_id(location_id)

    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found"
        )

    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        return LocationDetail.model_validate(location)

    updated = repo.update(location_id, update_data)
    return LocationDetail.model_validate(updated)


# =============================================================================
# NPC Template Routes
# =============================================================================

@router.get("/npc-templates", response_model=List[NPCTemplateListItem])
def list_npc_templates(
    world_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    List all NPC templates.

    Returns a paginated list of NPC template configurations.
    Optionally filter by world_id.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = NPCTemplateRepository(db)

    if world_id:
        npcs = repo.get_by_world(world_id)
    else:
        npcs = repo.get_all(skip=skip, limit=limit)

    return [NPCTemplateListItem.model_validate(npc) for npc in npcs]


@router.get("/npc-templates/{npc_id}", response_model=NPCTemplateDetail)
def get_npc_template(
    npc_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get NPC template details.

    Returns detailed information about a specific NPC template.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = NPCTemplateRepository(db)
    npc = repo.get_by_id(npc_id)

    if not npc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NPC template not found"
        )

    return NPCTemplateDetail.model_validate(npc)


@router.patch("/npc-templates/{npc_id}", response_model=NPCTemplateDetail)
def update_npc_template(
    npc_id: str,
    request: NPCTemplateUpdateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Update NPC template configuration.

    Updates NPC template properties. Only provided fields are modified.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = NPCTemplateRepository(db)
    npc = repo.get_by_id(npc_id)

    if not npc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NPC template not found"
        )

    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        return NPCTemplateDetail.model_validate(npc)

    updated = repo.update(npc_id, update_data)
    return NPCTemplateDetail.model_validate(updated)


# =============================================================================
# Item Template Routes
# =============================================================================

@router.get("/item-templates", response_model=List[ItemTemplateListItem])
def list_item_templates(
    world_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    List all item templates.

    Returns a paginated list of item template configurations.
    Optionally filter by world_id.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = ItemTemplateRepository(db)

    if world_id:
        items = repo.get_by_world(world_id)
    else:
        items = repo.get_all(skip=skip, limit=limit)

    return [ItemTemplateListItem.model_validate(item) for item in items]


@router.get("/item-templates/{item_id}", response_model=ItemTemplateDetail)
def get_item_template(
    item_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get item template details.

    Returns detailed information about a specific item template.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = ItemTemplateRepository(db)
    item = repo.get_by_id(item_id)

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item template not found"
        )

    return ItemTemplateDetail.model_validate(item)


@router.patch("/item-templates/{item_id}", response_model=ItemTemplateDetail)
def update_item_template(
    item_id: str,
    request: ItemTemplateUpdateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Update item template configuration.

    Updates item template properties. Only provided fields are modified.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = ItemTemplateRepository(db)
    item = repo.get_by_id(item_id)

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item template not found"
        )

    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        return ItemTemplateDetail.model_validate(item)

    updated = repo.update(item_id, update_data)
    return ItemTemplateDetail.model_validate(updated)


# =============================================================================
# Quest Template Routes
# =============================================================================

@router.get("/quest-templates", response_model=List[QuestTemplateListItem])
def list_quest_templates(
    world_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    List all quest templates.

    Returns a paginated list of quest template configurations.
    Optionally filter by world_id.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = QuestTemplateRepository(db)

    if world_id:
        quests = repo.get_by_world(world_id)
    else:
        quests = repo.get_all(skip=skip, limit=limit)

    return [QuestTemplateListItem.model_validate(q) for q in quests]


@router.get("/quest-templates/{quest_id}", response_model=QuestTemplateDetail)
def get_quest_template(
    quest_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get quest template details.

    Returns detailed information about a specific quest template.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = QuestTemplateRepository(db)
    quest = repo.get_by_id(quest_id)

    if not quest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quest template not found"
        )

    return QuestTemplateDetail.model_validate(quest)


@router.patch("/quest-templates/{quest_id}", response_model=QuestTemplateDetail)
def update_quest_template(
    quest_id: str,
    request: QuestTemplateUpdateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Update quest template configuration.

    Updates quest template properties. Only provided fields are modified.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = QuestTemplateRepository(db)
    quest = repo.get_by_id(quest_id)

    if not quest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quest template not found"
        )

    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        return QuestTemplateDetail.model_validate(quest)

    updated = repo.update(quest_id, update_data)
    return QuestTemplateDetail.model_validate(updated)


# =============================================================================
# Event Template Routes
# =============================================================================

@router.get("/event-templates", response_model=List[EventTemplateListItem])
def list_event_templates(
    world_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    List all event templates.

    Returns a paginated list of event template configurations.
    Optionally filter by world_id.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = EventTemplateRepository(db)

    if world_id:
        events = repo.get_by_world(world_id)
    else:
        events = repo.get_all(skip=skip, limit=limit)

    return [EventTemplateListItem.model_validate(e) for e in events]


@router.get("/event-templates/{event_id}", response_model=EventTemplateDetail)
def get_event_template(
    event_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get event template details.

    Returns detailed information about a specific event template.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = EventTemplateRepository(db)
    event = repo.get_by_id(event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event template not found"
        )

    return EventTemplateDetail.model_validate(event)


@router.patch("/event-templates/{event_id}", response_model=EventTemplateDetail)
def update_event_template(
    event_id: str,
    request: EventTemplateUpdateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Update event template configuration.

    Updates event template properties. Only provided fields are modified.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = EventTemplateRepository(db)
    event = repo.get_by_id(event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event template not found"
        )

    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        return EventTemplateDetail.model_validate(event)

    updated = repo.update(event_id, update_data)
    return EventTemplateDetail.model_validate(updated)


# =============================================================================
# Prompt Template Routes
# =============================================================================

@router.get("/prompt-templates", response_model=List[PromptTemplateListItem])
def list_prompt_templates(
    world_id: Optional[str] = None,
    prompt_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    List all prompt templates.

    Returns a paginated list of prompt template configurations.
    Optionally filter by world_id or prompt_type.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = PromptTemplateRepository(db)

    if prompt_type:
        templates = repo.get_by_type(prompt_type, world_id)
    elif world_id:
        # Filter by world_id manually since get_by_type requires prompt_type
        all_templates = repo.get_all(skip=skip, limit=limit)
        templates = [t for t in all_templates if t.world_id == world_id or t.world_id is None]
    else:
        templates = repo.get_all(skip=skip, limit=limit)

    return [PromptTemplateListItem.model_validate(t) for t in templates]


@router.get("/prompt-templates/{template_id}", response_model=PromptTemplateDetail)
def get_prompt_template(
    template_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get prompt template details.

    Returns detailed information about a specific prompt template.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = PromptTemplateRepository(db)
    template = repo.get_by_id(template_id)

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt template not found"
        )

    return PromptTemplateDetail.model_validate(template)


@router.patch("/prompt-templates/{template_id}", response_model=PromptTemplateDetail)
def update_prompt_template(
    template_id: str,
    request: PromptTemplateUpdateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Update prompt template configuration.

    Updates prompt template properties. Only provided fields are modified.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = PromptTemplateRepository(db)
    template = repo.get_by_id(template_id)

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt template not found"
        )

    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        return PromptTemplateDetail.model_validate(template)

    updated = repo.update(template_id, update_data)
    return PromptTemplateDetail.model_validate(updated)


# =============================================================================
# System Settings Models
# =============================================================================

class OpenAIKeyMetadata(BaseModel):
    configured: bool
    last4: Optional[str] = None
    secret_updated_at: Optional[str] = None
    secret_cleared_at: Optional[str] = None


class LLMSettingsResponse(BaseModel):
    provider_mode: str
    default_model: Optional[str] = None
    temperature: float
    max_tokens: int
    openai_api_key: OpenAIKeyMetadata
    custom_base_url: Optional[str] = None
    custom_api_key: OpenAIKeyMetadata


class OpsSettingsResponse(BaseModel):
    registration_enabled: bool
    maintenance_mode: bool
    debug_enabled: bool


class SystemSettingsResponse(BaseModel):
    llm: LLMSettingsResponse
    ops: OpsSettingsResponse
    updated_at: Optional[str] = None
    updated_by_user_id: Optional[str] = None


class OpenAIKeyAction(BaseModel):
    action: str
    value: Optional[str] = None


class LLMSettingsUpdate(BaseModel):
    provider_mode: Optional[str] = None
    default_model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    openai_api_key: Optional[OpenAIKeyAction] = None
    custom_base_url: Optional[str] = None
    custom_api_key: Optional[OpenAIKeyAction] = None


class OpsSettingsUpdate(BaseModel):
    registration_enabled: Optional[bool] = None
    maintenance_mode: Optional[bool] = None
    debug_enabled: Optional[bool] = None


class SystemSettingsUpdateRequest(BaseModel):
    llm: Optional[LLMSettingsUpdate] = None
    ops: Optional[OpsSettingsUpdate] = None


# =============================================================================
# System Settings Endpoints
# =============================================================================

@router.get("/system-settings", response_model=SystemSettingsResponse)
def get_system_settings(
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    require_admin_role(current_user)
    from ..services.settings import SystemSettingsService
    service = SystemSettingsService(db)
    return service.get_settings_dict()


@router.patch("/system-settings", response_model=SystemSettingsResponse)
def update_system_settings(
    request: SystemSettingsUpdateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    require_admin_role(current_user)
    from ..services.settings import SystemSettingsService
    service = SystemSettingsService(db)
    
    update_data = request.model_dump(exclude_unset=True)
    
    if "llm" in update_data and update_data["llm"] is not None:
        llm_data = update_data["llm"]
        settings = service.get_settings()
        provider_mode = llm_data.get("provider_mode", settings.provider_mode)

        openai_key_available = bool(service.get_effective_openai_key())
        openai_key_data = llm_data.get("openai_api_key")
        if openai_key_data:
            if openai_key_data.get("action") == "set" and openai_key_data.get("value"):
                openai_key_available = True
            elif openai_key_data.get("action") == "clear":
                openai_key_available = False

        custom_url = settings.custom_base_url
        if "custom_base_url" in llm_data:
            try:
                custom_url = service._normalize_custom_base_url(llm_data["custom_base_url"])
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(e)
                )

        custom_key_available = bool(service.get_effective_custom_api_key())
        custom_key_data = llm_data.get("custom_api_key")
        if custom_key_data:
            if custom_key_data.get("action") == "set" and custom_key_data.get("value"):
                custom_key_available = True
            elif custom_key_data.get("action") == "clear":
                custom_key_available = False

        if provider_mode == "openai":
            if not openai_key_available:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Cannot set provider_mode to openai without an effective API key"
                )

        if provider_mode == "custom":
            if not custom_url:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Cannot set provider_mode to custom without a custom_base_url"
                )
            if not custom_key_available:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Cannot set provider_mode to custom without an effective custom API key"
                )
    
    try:
        return service.update_settings(update_data, current_user.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        from ..services.settings import MissingEncryptionKeyError
        if isinstance(e, MissingEncryptionKeyError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e)
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update settings"
        )
