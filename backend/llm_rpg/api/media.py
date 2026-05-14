"""
Media API routes for LLM RPG Engine.

Real implementations using AssetGenerationService with mock providers.
No external API calls required for testing.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from llm_rpg.models.assets import (
    AssetGenerationRequest as AssetGenRequest,
    AssetResponse,
    AssetType,
)
from llm_rpg.services.asset_generation_service import AssetGenerationService
from llm_rpg.storage.database import get_db
from llm_rpg.storage.repositories import AssetRepository
from llm_rpg.api.auth import get_current_active_user

router = APIRouter(prefix="/media", tags=["media"])


class PortraitGenerateRequest(BaseModel):
    npc_id: str = Field(..., description="NPC template ID")
    style: Optional[str] = Field("anime", description="Art style for the portrait")
    expression: Optional[str] = Field("neutral", description="NPC expression")
    session_id: Optional[str] = Field(None, description="Session ID for context")
    world_id: Optional[str] = Field(None, description="World ID for context")


class SceneGenerateRequest(BaseModel):
    location_id: str = Field(..., description="Location ID")
    time_of_day: Optional[str] = Field("day", description="Time of day for scene")
    weather: Optional[str] = Field(None, description="Weather condition")
    session_id: Optional[str] = Field(None, description="Session ID for context")
    world_id: Optional[str] = Field(None, description="World ID for context")


class BGMGenerateRequest(BaseModel):
    location_id: Optional[str] = Field(None, description="Location ID for ambient music")
    mood: str = Field(..., description="Mood/theme for the music")
    duration_seconds: Optional[int] = Field(60, ge=10, le=300)
    session_id: Optional[str] = Field(None, description="Session ID for context")
    world_id: Optional[str] = Field(None, description="World ID for context")


def get_asset_service(db = Depends(get_db)) -> AssetGenerationService:
    repository = AssetRepository(db)
    return AssetGenerationService(repository=repository)


@router.post(
    "/portraits/generate",
    response_model=AssetResponse,
    summary="Generate character portrait",
)
async def generate_portrait(
    request: PortraitGenerateRequest,
    current_user = Depends(get_current_active_user),
    service: AssetGenerationService = Depends(get_asset_service),
):
    """Generate an AI portrait for an NPC character."""
    gen_request = AssetGenRequest(
        asset_type=AssetType.PORTRAIT,
        prompt=f"Portrait of NPC {request.npc_id}: style={request.style}, expression={request.expression}",
        style=request.style,
        session_id=request.session_id,
        world_id=request.world_id,
        owner_entity_id=request.npc_id,
        owner_entity_type="npc",
    )
    result = await service.generate_asset(gen_request)
    return result


@router.post(
    "/scenes/generate",
    response_model=AssetResponse,
    summary="Generate scene image",
)
async def generate_scene(
    request: SceneGenerateRequest,
    current_user = Depends(get_current_active_user),
    service: AssetGenerationService = Depends(get_asset_service),
):
    """Generate a scene image for a location."""
    gen_request = AssetGenRequest(
        asset_type=AssetType.SCENE,
        prompt=f"Scene of location {request.location_id}: time={request.time_of_day}, weather={request.weather or 'clear'}",
        style=request.time_of_day,
        session_id=request.session_id,
        world_id=request.world_id,
        owner_entity_id=request.location_id,
        owner_entity_type="location",
    )
    result = await service.generate_asset(gen_request)
    return result


@router.post(
    "/bgm/generate",
    response_model=AssetResponse,
    summary="Generate background music",
)
async def generate_bgm(
    request: BGMGenerateRequest,
    current_user = Depends(get_current_active_user),
    service: AssetGenerationService = Depends(get_asset_service),
):
    """Generate background music based on mood and location."""
    gen_request = AssetGenRequest(
        asset_type=AssetType.BGM,
        prompt=f"BGM for mood={request.mood}, location={request.location_id or 'generic'}, duration={request.duration_seconds}s",
        session_id=request.session_id,
        world_id=request.world_id,
    )
    result = await service.generate_asset(gen_request)
    return result


@router.get(
    "/assets/{asset_id}",
    response_model=AssetResponse,
    summary="Get asset by ID",
)
def get_asset(
    asset_id: str,
    current_user = Depends(get_current_active_user),
    service: AssetGenerationService = Depends(get_asset_service),
):
    """Get an asset by its public ID."""
    asset = service.get_asset(asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset {asset_id} not found",
        )
    return asset


@router.get(
    "/sessions/{session_id}/assets",
    response_model=List[AssetResponse],
    summary="List session assets",
)
def list_session_assets(
    session_id: str,
    asset_type: Optional[str] = None,
    current_user = Depends(get_current_active_user),
    service: AssetGenerationService = Depends(get_asset_service),
):
    """List all assets for a session."""
    return service.list_session_assets(session_id, asset_type=asset_type)
