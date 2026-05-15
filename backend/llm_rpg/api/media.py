"""
Media API routes for LLM RPG Engine.

Real implementations using AssetGenerationService with mock providers.
No external API calls required for testing.
"""

import os
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from llm_rpg.models.assets import (
    AssetGenerationRequest as AssetGenRequest,
    AssetJobResponse,
    AssetJobStatus,
    AssetResponse,
    AssetType,
)
from llm_rpg.services.asset_generation_service import AssetGenerationService
from llm_rpg.services.asset_job_service import AssetJobService
from llm_rpg.storage.database import get_db
from llm_rpg.storage.repositories import AssetJobRepository, AssetRepository
from llm_rpg.api.auth import get_current_active_user

router = APIRouter(prefix="/media", tags=["media"])

_DEFAULT_MODE = os.getenv("ASSET_GENERATION_MODE", "sync")


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


class PortraitJobRequest(BaseModel):
    job_id: Optional[str] = Field(None, description="Optional job ID (auto-generated if not provided)")
    npc_id: str = Field(..., description="NPC template ID")
    style: Optional[str] = Field("anime", description="Art style for the portrait")
    expression: Optional[str] = Field("neutral", description="NPC expression")
    session_id: Optional[str] = Field(None, description="Session ID for context")
    world_id: Optional[str] = Field(None, description="World ID for context")


class SceneJobRequest(BaseModel):
    job_id: Optional[str] = Field(None, description="Optional job ID (auto-generated if not provided)")
    location_id: str = Field(..., description="Location ID")
    time_of_day: Optional[str] = Field("day", description="Time of day for scene")
    weather: Optional[str] = Field(None, description="Weather condition")
    session_id: Optional[str] = Field(None, description="Session ID for context")
    world_id: Optional[str] = Field(None, description="World ID for context")


class BGMJobRequest(BaseModel):
    job_id: Optional[str] = Field(None, description="Optional job ID (auto-generated if not provided)")
    location_id: Optional[str] = Field(None, description="Location ID for ambient music")
    mood: str = Field(..., description="Mood/theme for the music")
    duration_seconds: Optional[int] = Field(60, ge=10, le=300)
    session_id: Optional[str] = Field(None, description="Session ID for context")
    world_id: Optional[str] = Field(None, description="World ID for context")


def get_asset_service(db = Depends(get_db)) -> AssetGenerationService:
    repository = AssetRepository(db)
    return AssetGenerationService(repository=repository)


def get_asset_job_service(db = Depends(get_db)) -> AssetJobService:
    job_repo = AssetJobRepository(db)
    asset_repo = AssetRepository(db)
    return AssetJobService(job_repository=job_repo, asset_repository=asset_repo)


@router.post(
    "/portraits/generate",
    response_model=Union[AssetResponse, AssetJobResponse],
    summary="Generate character portrait",
)
async def generate_portrait(
    request: PortraitGenerateRequest,
    mode: str = Query(_DEFAULT_MODE, regex="^(sync|async)$", description="Generation mode: sync (immediate) or async (job)"),
    current_user = Depends(get_current_active_user),
    service: AssetGenerationService = Depends(get_asset_service),
    job_service: AssetJobService = Depends(get_asset_job_service),
):
    gen_request = AssetGenRequest(
        asset_type=AssetType.PORTRAIT,
        prompt=f"Portrait of NPC {request.npc_id}: style={request.style}, expression={request.expression}",
        style=request.style,
        session_id=request.session_id,
        world_id=request.world_id,
        owner_entity_id=request.npc_id,
        owner_entity_type="npc",
    )
    if mode == "async":
        return await job_service.submit(gen_request)
    result = await service.generate_asset(gen_request)
    return result


@router.post(
    "/scenes/generate",
    response_model=Union[AssetResponse, AssetJobResponse],
    summary="Generate scene image",
)
async def generate_scene(
    request: SceneGenerateRequest,
    mode: str = Query(_DEFAULT_MODE, regex="^(sync|async)$", description="Generation mode: sync (immediate) or async (job)"),
    current_user = Depends(get_current_active_user),
    service: AssetGenerationService = Depends(get_asset_service),
    job_service: AssetJobService = Depends(get_asset_job_service),
):
    gen_request = AssetGenRequest(
        asset_type=AssetType.SCENE,
        prompt=f"Scene of location {request.location_id}: time={request.time_of_day}, weather={request.weather or 'clear'}",
        style=request.time_of_day,
        session_id=request.session_id,
        world_id=request.world_id,
        owner_entity_id=request.location_id,
        owner_entity_type="location",
    )
    if mode == "async":
        return await job_service.submit(gen_request)
    result = await service.generate_asset(gen_request)
    return result


@router.post(
    "/bgm/generate",
    response_model=Union[AssetResponse, AssetJobResponse],
    summary="Generate background music",
)
async def generate_bgm(
    request: BGMGenerateRequest,
    mode: str = Query(_DEFAULT_MODE, regex="^(sync|async)$", description="Generation mode: sync (immediate) or async (job)"),
    current_user = Depends(get_current_active_user),
    service: AssetGenerationService = Depends(get_asset_service),
    job_service: AssetJobService = Depends(get_asset_job_service),
):
    gen_request = AssetGenRequest(
        asset_type=AssetType.BGM,
        prompt=f"BGM for mood={request.mood}, location={request.location_id or 'generic'}, duration={request.duration_seconds}s",
        session_id=request.session_id,
        world_id=request.world_id,
    )
    if mode == "async":
        return await job_service.submit(gen_request)
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


@router.post(
    "/jobs/portraits",
    response_model=Union[AssetResponse, AssetJobResponse],
    summary="Create portrait generation job",
)
async def create_portrait_job(
    request: PortraitJobRequest,
    current_user = Depends(get_current_active_user),
    job_service: AssetJobService = Depends(get_asset_job_service),
):
    gen_request = AssetGenRequest(
        asset_type=AssetType.PORTRAIT,
        prompt=f"Portrait of NPC {request.npc_id}: style={request.style}, expression={request.expression}",
        style=request.style,
        session_id=request.session_id,
        world_id=request.world_id,
        owner_entity_id=request.npc_id,
        owner_entity_type="npc",
    )
    result = await job_service.submit(gen_request)
    return result


@router.post(
    "/jobs/scenes",
    response_model=Union[AssetResponse, AssetJobResponse],
    summary="Create scene generation job",
)
async def create_scene_job(
    request: SceneJobRequest,
    current_user = Depends(get_current_active_user),
    job_service: AssetJobService = Depends(get_asset_job_service),
):
    gen_request = AssetGenRequest(
        asset_type=AssetType.SCENE,
        prompt=f"Scene of location {request.location_id}: time={request.time_of_day}, weather={request.weather or 'clear'}",
        style=request.time_of_day,
        session_id=request.session_id,
        world_id=request.world_id,
        owner_entity_id=request.location_id,
        owner_entity_type="location",
    )
    result = await job_service.submit(gen_request)
    return result


@router.post(
    "/jobs/bgm",
    response_model=Union[AssetResponse, AssetJobResponse],
    summary="Create BGM generation job",
)
async def create_bgm_job(
    request: BGMJobRequest,
    current_user = Depends(get_current_active_user),
    job_service: AssetJobService = Depends(get_asset_job_service),
):
    gen_request = AssetGenRequest(
        asset_type=AssetType.BGM,
        prompt=f"BGM for mood={request.mood}, location={request.location_id or 'generic'}, duration={request.duration_seconds}s",
        session_id=request.session_id,
        world_id=request.world_id,
    )
    result = await job_service.submit(gen_request)
    return result


@router.get(
    "/jobs/{job_id}",
    response_model=AssetJobResponse,
    summary="Get job status",
)
def get_job_status(
    job_id: str,
    current_user = Depends(get_current_active_user),
    job_service: AssetJobService = Depends(get_asset_job_service),
):
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
    return job


@router.get(
    "/sessions/{session_id}/jobs",
    response_model=List[AssetJobResponse],
    summary="List session jobs",
)
def list_session_jobs(
    session_id: str,
    asset_type: Optional[str] = None,
    current_user = Depends(get_current_active_user),
    job_service: AssetJobService = Depends(get_asset_job_service),
):
    return job_service.list_session_jobs(session_id, asset_type=asset_type)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=AssetJobResponse,
    summary="Retry failed job",
)
def retry_job(
    job_id: str,
    current_user = Depends(get_current_active_user),
    job_service: AssetJobService = Depends(get_asset_job_service),
):
    job = job_service.retry_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found or not in failed state",
        )
    return job


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=AssetJobResponse,
    summary="Cancel pending job",
)
def cancel_job(
    job_id: str,
    current_user = Depends(get_current_active_user),
    job_service: AssetJobService = Depends(get_asset_job_service),
):
    job = job_service.cancel_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found or not in pending state",
        )
    return job
