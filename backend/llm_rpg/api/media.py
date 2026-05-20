"""
Media API routes for LLM RPG Engine.

Real implementations using AssetGenerationService with mock providers.
No external API calls required for testing.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from llm_rpg.models.assets import (
    AssetGenerationRequest as AssetGenRequest,
    AssetJobResponse,
    AssetJobStatus,
    AssetResponse,
    AssetType,
)
from llm_rpg.observability.npc_mind import NPCMindViewer
from llm_rpg.services.asset_generation_service import AssetGenerationService
from llm_rpg.services.asset_job_service import AssetJobService
from llm_rpg.services.asset_rate_limit import AssetRateLimiter, RateLimitResult
from llm_rpg.services.npc_portrait_prompt import (
    build_portrait_context,
    build_portrait_prompt,
)
from llm_rpg.storage.database import get_db
from llm_rpg.storage.repositories import (
    AssetJobRepository,
    AssetRateLimitEventRepository,
    AssetRepository,
    SessionStateRepository,
)
from llm_rpg.api.auth import get_current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/media", tags=["media"])

_DEFAULT_MODE = os.getenv("ASSET_GENERATION_MODE", "sync")
_PREWARM_MAX_NPCS = int(os.getenv("ASSET_PREWARM_MAX_NPCS", "5"))


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


class PrewarmPortraitsResponse(BaseModel):
    """Response for portrait prewarm operation."""
    status: str = Field(..., description="Prewarm status: 'completed' or 'partial_failure'")
    total: int = Field(..., description="Total NPCs considered")
    pending: int = Field(..., description="Jobs submitted (pending)")
    completed: int = Field(..., description="Already cached (skipped)")
    failed: int = Field(..., description="Failed to process")
    npc_ids: List[str] = Field(default_factory=list, description="NPC IDs processed")


class PrewarmStatusResponse(BaseModel):
    """Response for prewarm status check."""
    total: int = Field(..., description="Total portrait jobs for session")
    pending: int = Field(..., description="Jobs in pending state")
    processing: int = Field(..., description="Jobs in processing state")
    completed: int = Field(..., description="Jobs in completed state")
    failed: int = Field(..., description="Jobs in failed state")
    npc_ids: List[str] = Field(default_factory=list, description="NPC IDs with portrait jobs")


def get_asset_service(db = Depends(get_db)) -> AssetGenerationService:
    repository = AssetRepository(db)
    return AssetGenerationService(repository=repository)


def get_asset_job_service(db = Depends(get_db)) -> AssetJobService:
    job_repo = AssetJobRepository(db)
    asset_repo = AssetRepository(db)
    return AssetJobService(job_repository=job_repo, asset_repository=asset_repo)


def get_rate_limiter(db: Session = Depends(get_db)) -> AssetRateLimiter:
    repo = AssetRateLimitEventRepository(db)
    return AssetRateLimiter(rate_limit_event_repo=repo)


def _resolve_provider_name(asset_type: AssetType) -> str:
    """Resolve the provider name for a given asset type.

    Checks ASSET_PROVIDER env var first, then falls back to
    ProviderRegistry.get_available_provider(), then defaults to "mock".
    """
    configured = os.getenv("ASSET_PROVIDER")
    if configured:
        return configured
    try:
        from llm_rpg.assets.provider_registry import ProviderRegistry
        registry = ProviderRegistry()
        provider = registry.get_available_provider(asset_type.value)
        return provider or "mock"
    except Exception:
        return "mock"


def _enforce_rate_limit(
    rate_limiter: AssetRateLimiter,
    user_id: str,
    session_id: Optional[str],
    provider_name: str,
) -> None:
    """Check rate limit and raise 429 if exceeded. Records event to DB."""
    result = rate_limiter.check_rate_limit(user_id, session_id, provider_name)
    rate_limiter.record_rate_limit_event(
        user_id=user_id,
        session_id=session_id,
        provider_name=provider_name,
        allowed=result.allowed,
        limit_type=result.limit_type,
        limit_value=result.limit_value,
        current_value=result.current_value,
        reset_at=result.reset_at,
    )
    if not result.allowed:
        retry_after = 60
        if result.reset_at:
            delta = (result.reset_at - datetime.now()).total_seconds()
            retry_after = max(1, int(delta))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "asset_rate_limited",
                "limit_type": result.limit_type,
                "limit_value": result.limit_value,
                "reset_at": result.reset_at.isoformat() if result.reset_at else None,
            },
            headers={"Retry-After": str(retry_after)},
        )


def _build_rich_portrait_prompt(
    session_id: Optional[str],
    npc_id: str,
    style: Optional[str],
    expression: Optional[str],
    db: Session,
) -> str:
    """Build rich portrait prompt via NPC context; fallback to trivial prompt on missing session or error."""
    trivial = f"Portrait of NPC {npc_id}: style={style}, expression={expression}"
    if not session_id:
        return trivial
    try:
        context = build_portrait_context(session_id, npc_id, db)
        return build_portrait_prompt(context)
    except Exception:
        logger.warning("Portrait context build failed for npc_id=%s, session_id=%s; using trivial prompt", npc_id, session_id, exc_info=True)
        return trivial


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
    rate_limiter: AssetRateLimiter = Depends(get_rate_limiter),
    db: Session = Depends(get_db),
):
    _enforce_rate_limit(
        rate_limiter=rate_limiter,
        user_id=current_user.id,
        session_id=request.session_id,
        provider_name=_resolve_provider_name(AssetType.PORTRAIT),
    )
    prompt = _build_rich_portrait_prompt(
        session_id=request.session_id,
        npc_id=request.npc_id,
        style=request.style,
        expression=request.expression,
        db=db,
    )
    gen_request = AssetGenRequest(
        asset_type=AssetType.PORTRAIT,
        prompt=prompt,
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
    rate_limiter: AssetRateLimiter = Depends(get_rate_limiter),
):
    _enforce_rate_limit(
        rate_limiter=rate_limiter,
        user_id=current_user.id,
        session_id=request.session_id,
        provider_name=_resolve_provider_name(AssetType.SCENE),
    )
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
    rate_limiter: AssetRateLimiter = Depends(get_rate_limiter),
):
    _enforce_rate_limit(
        rate_limiter=rate_limiter,
        user_id=current_user.id,
        session_id=request.session_id,
        provider_name=_resolve_provider_name(AssetType.BGM),
    )
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
    rate_limiter: AssetRateLimiter = Depends(get_rate_limiter),
    db: Session = Depends(get_db),
):
    _enforce_rate_limit(
        rate_limiter=rate_limiter,
        user_id=current_user.id,
        session_id=request.session_id,
        provider_name=_resolve_provider_name(AssetType.PORTRAIT),
    )
    prompt = _build_rich_portrait_prompt(
        session_id=request.session_id,
        npc_id=request.npc_id,
        style=request.style,
        expression=request.expression,
        db=db,
    )
    gen_request = AssetGenRequest(
        asset_type=AssetType.PORTRAIT,
        prompt=prompt,
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
    rate_limiter: AssetRateLimiter = Depends(get_rate_limiter),
):
    _enforce_rate_limit(
        rate_limiter=rate_limiter,
        user_id=current_user.id,
        session_id=request.session_id,
        provider_name=_resolve_provider_name(AssetType.SCENE),
    )
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
    rate_limiter: AssetRateLimiter = Depends(get_rate_limiter),
):
    _enforce_rate_limit(
        rate_limiter=rate_limiter,
        user_id=current_user.id,
        session_id=request.session_id,
        provider_name=_resolve_provider_name(AssetType.BGM),
    )
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


@router.post(
    "/sessions/{session_id}/prewarm-portraits",
    response_model=PrewarmPortraitsResponse,
    summary="Prewarm portraits for NPCs at current location",
)
async def prewarm_portraits(
    session_id: str,
    current_user = Depends(get_current_active_user),
    job_service: AssetJobService = Depends(get_asset_job_service),
    db: Session = Depends(get_db),
):
    session_state_repo = SessionStateRepository(db)
    session_state = session_state_repo.get_by_session(session_id)
    if session_state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    current_location_id = session_state.current_location_id
    if not current_location_id:
        return PrewarmPortraitsResponse(
            status="completed",
            total=0,
            pending=0,
            completed=0,
            failed=0,
            npc_ids=[],
        )

    npc_viewer = NPCMindViewer(db)
    all_npcs = npc_viewer.list_session_npcs(session_id)

    location_npcs = [
        npc for npc in all_npcs
        if npc.get("current_location_id") == current_location_id
    ]

    max_npcs = _PREWARM_MAX_NPCS
    npcs_to_process = location_npcs[:max_npcs]

    total = len(npcs_to_process)
    pending = 0
    completed = 0
    failed = 0
    processed_npc_ids: List[str] = []

    for npc in npcs_to_process:
        npc_id = npc.get("npc_id")
        if not npc_id:
            continue

        try:
            context = build_portrait_context(session_id, npc_id, db)
            prompt = build_portrait_prompt(context)

            gen_request = AssetGenRequest(
                asset_type=AssetType.PORTRAIT,
                prompt=prompt,
                style=None,
                session_id=session_id,
                world_id=None,
                owner_entity_id=npc_id,
                owner_entity_type="npc",
            )

            result = await job_service.submit(gen_request)
            processed_npc_ids.append(npc_id)

            if isinstance(result, AssetResponse):
                completed += 1
            elif isinstance(result, AssetJobResponse):
                if result.status == AssetJobStatus.PENDING:
                    pending += 1
                elif result.status == AssetJobStatus.FAILED:
                    failed += 1
                else:
                    pending += 1
        except Exception as exc:
            logger.warning(
                "Portrait prewarm failed for npc_id=%s, session_id=%s: %s",
                npc_id, session_id, exc, exc_info=True
            )
            failed += 1

    status_val = "completed" if failed == 0 else "partial_failure"
    return PrewarmPortraitsResponse(
        status=status_val,
        total=total,
        pending=pending,
        completed=completed,
        failed=failed,
        npc_ids=processed_npc_ids,
    )


@router.get(
    "/sessions/{session_id}/prewarm-status",
    response_model=PrewarmStatusResponse,
    summary="Get portrait prewarm status for session",
)
def get_prewarm_status(
    session_id: str,
    current_user = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    job_repo = AssetJobRepository(db)
    job_models = job_repo.list_by_session(session_id, asset_type=AssetType.PORTRAIT.value)

    total = len(job_models)
    pending = 0
    processing = 0
    completed = 0
    failed = 0
    npc_ids: List[str] = []

    for job in job_models:
        status_val = job.status
        if status_val == AssetJobStatus.PENDING.value:
            pending += 1
        elif status_val == AssetJobStatus.PROCESSING.value:
            processing += 1
        elif status_val == AssetJobStatus.COMPLETED.value:
            completed += 1
        elif status_val == AssetJobStatus.FAILED.value:
            failed += 1

        request_json = job.request_json or {}
        owner_entity_id = request_json.get("owner_entity_id")
        if owner_entity_id and owner_entity_id not in npc_ids:
            npc_ids.append(owner_entity_id)

    return PrewarmStatusResponse(
        total=total,
        pending=pending,
        processing=processing,
        completed=completed,
        failed=failed,
        npc_ids=npc_ids,
    )
