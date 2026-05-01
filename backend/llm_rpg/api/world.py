"""
World API routes for the LLM RPG Engine.

Provides endpoints for retrieving world state and configuration from the database.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..storage.database import get_db
from ..storage.repositories import (
    WorldRepository,
    ChapterRepository,
    LocationRepository,
    NPCTemplateRepository,
    ItemTemplateRepository,
    QuestTemplateRepository,
    EventTemplateRepository,
    PromptTemplateRepository,
)

router = APIRouter(prefix="/world", tags=["world"])


class WorldResponse(BaseModel):
    id: str
    code: str
    name: str
    genre: Optional[str] = None
    lore_summary: Optional[str] = None
    status: str
    
    class Config:
        from_attributes = True


class ChapterResponse(BaseModel):
    id: str
    chapter_no: int
    name: str
    summary: Optional[str] = None
    start_conditions: dict = Field(default_factory=dict)
    
    class Config:
        from_attributes = True


class LocationResponse(BaseModel):
    id: str
    code: str
    name: str
    tags: list = Field(default_factory=list)
    description: Optional[str] = None
    access_rules: dict = Field(default_factory=dict)
    chapter_id: Optional[str] = None
    
    class Config:
        from_attributes = True


class NPCResponse(BaseModel):
    id: str
    code: str
    name: str
    role_type: Optional[str] = None
    public_identity: Optional[str] = None
    hidden_identity: Optional[str] = None
    personality: Optional[str] = None
    speech_style: Optional[str] = None
    goals: list = Field(default_factory=list)
    
    class Config:
        from_attributes = True


class ItemResponse(BaseModel):
    id: str
    code: str
    name: str
    item_type: Optional[str] = None
    rarity: str = "common"
    description: Optional[str] = None
    
    class Config:
        from_attributes = True


class QuestResponse(BaseModel):
    id: str
    code: str
    name: str
    quest_type: Optional[str] = None
    summary: Optional[str] = None
    visibility: str = "hidden"
    
    class Config:
        from_attributes = True


class EventTemplateResponse(BaseModel):
    id: str
    code: str
    name: str
    event_type: Optional[str] = None
    trigger_conditions: dict = Field(default_factory=dict)
    
    class Config:
        from_attributes = True


class PromptTemplateResponse(BaseModel):
    id: str
    prompt_type: str
    version: str
    content: str
    enabled_flag: bool = True
    
    class Config:
        from_attributes = True


class EndingResponse(BaseModel):
    id: str
    code: str
    name: str
    summary: Optional[str] = None
    
    class Config:
        from_attributes = True


class WorldStateResponse(BaseModel):
    world: WorldResponse
    chapters: List[ChapterResponse]
    locations: List[LocationResponse]
    npcs: List[NPCResponse]
    items: List[ItemResponse]
    quests: List[QuestResponse]
    endings: List[EndingResponse]
    event_templates: List[EventTemplateResponse]
    prompt_templates: List[PromptTemplateResponse]


class WorldSummaryResponse(BaseModel):
    world_count: int
    chapter_count: int
    location_count: int
    npc_count: int
    item_count: int
    quest_count: int
    ending_count: int
    event_template_count: int
    prompt_template_count: int


@router.get("/state", response_model=WorldStateResponse)
def get_world_state(db: Session = Depends(get_db)):
    """
    Get the current world state from the database.
    
    Returns world metadata, chapters, locations, NPCs, items, quests, and endings.
    """
    world_repo = WorldRepository(db)
    chapter_repo = ChapterRepository(db)
    location_repo = LocationRepository(db)
    npc_repo = NPCTemplateRepository(db)
    item_repo = ItemTemplateRepository(db)
    quest_repo = QuestTemplateRepository(db)
    event_repo = EventTemplateRepository(db)
    prompt_repo = PromptTemplateRepository(db)
    
    active_worlds = world_repo.get_active()
    if not active_worlds:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active world found. Run seed_content.py first."
        )
    
    world = active_worlds[0]
    world_id = world.id
    
    chapters = chapter_repo.get_by_world(world_id)
    locations = location_repo.get_by_world(world_id)
    npcs = npc_repo.get_by_world(world_id)
    items = item_repo.get_by_world(world_id)
    quests = quest_repo.get_by_world(world_id)
    events = event_repo.get_by_world(world_id)
    
    prompts = []
    for prompt_type in ["narration", "npc_dialogue", "intent_parsing", "combat_narration", "memory_summary"]:
        prompts.extend(prompt_repo.get_by_type(prompt_type, world_id))
    
    endings = [q for q in quests if q.quest_type == "ending"]
    regular_quests = [q for q in quests if q.quest_type != "ending"]
    
    return WorldStateResponse(
        world=WorldResponse.from_orm(world),
        chapters=[ChapterResponse.from_orm(c) for c in chapters],
        locations=[LocationResponse.from_orm(l) for l in locations],
        npcs=[NPCResponse.from_orm(n) for n in npcs],
        items=[ItemResponse.from_orm(i) for i in items],
        quests=[QuestResponse.from_orm(q) for q in regular_quests],
        endings=[EndingResponse(
            id=q.id,
            code=q.code,
            name=q.name,
            summary=q.summary,
        ) for q in endings],
        event_templates=[EventTemplateResponse.from_orm(e) for e in events],
        prompt_templates=[PromptTemplateResponse.from_orm(p) for p in prompts],
    )


@router.get("/summary", response_model=WorldSummaryResponse)
def get_world_summary(db: Session = Depends(get_db)):
    """
    Get a summary count of all world content.
    
    Returns counts of worlds, chapters, locations, NPCs, items, quests, and endings.
    """
    world_repo = WorldRepository(db)
    chapter_repo = ChapterRepository(db)
    location_repo = LocationRepository(db)
    npc_repo = NPCTemplateRepository(db)
    item_repo = ItemTemplateRepository(db)
    quest_repo = QuestTemplateRepository(db)
    event_repo = EventTemplateRepository(db)
    prompt_repo = PromptTemplateRepository(db)
    
    active_worlds = world_repo.get_active()
    if not active_worlds:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active world found. Run seed_content.py first."
        )
    
    world_id = active_worlds[0].id
    
    all_quests = quest_repo.get_by_world(world_id)
    endings = [q for q in all_quests if q.quest_type == "ending"]
    
    prompts = []
    for prompt_type in ["narration", "npc_dialogue", "intent_parsing", "combat_narration", "memory_summary"]:
        prompts.extend(prompt_repo.get_by_type(prompt_type, world_id))
    
    return WorldSummaryResponse(
        world_count=len(active_worlds),
        chapter_count=len(chapter_repo.get_by_world(world_id)),
        location_count=len(location_repo.get_by_world(world_id)),
        npc_count=len(npc_repo.get_by_world(world_id)),
        item_count=len(item_repo.get_by_world(world_id)),
        quest_count=len(all_quests),
        ending_count=len(endings),
        event_template_count=len(event_repo.get_by_world(world_id)),
        prompt_template_count=len(prompts),
    )


@router.get("/chapters/{chapter_id}", response_model=ChapterResponse)
def get_chapter(chapter_id: str, db: Session = Depends(get_db)):
    """Get a specific chapter by ID."""
    chapter_repo = ChapterRepository(db)
    chapter = chapter_repo.get_by_id(chapter_id)
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    return ChapterResponse.from_orm(chapter)


@router.get("/locations/{location_id}", response_model=LocationResponse)
def get_location(location_id: str, db: Session = Depends(get_db)):
    """Get a specific location by ID."""
    location_repo = LocationRepository(db)
    location = location_repo.get_by_id(location_id)
    
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found"
        )
    
    return LocationResponse.from_orm(location)


@router.get("/npcs/{npc_id}", response_model=NPCResponse)
def get_npc(npc_id: str, db: Session = Depends(get_db)):
    """Get a specific NPC template by ID."""
    npc_repo = NPCTemplateRepository(db)
    npc = npc_repo.get_by_id(npc_id)
    
    if not npc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NPC not found"
        )
    
    return NPCResponse.from_orm(npc)


@router.get("/quests/{quest_id}", response_model=QuestResponse)
def get_quest(quest_id: str, db: Session = Depends(get_db)):
    """Get a specific quest by ID."""
    quest_repo = QuestTemplateRepository(db)
    quest = quest_repo.get_by_id(quest_id)
    
    if not quest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quest not found"
        )
    
    return QuestResponse.from_orm(quest)
