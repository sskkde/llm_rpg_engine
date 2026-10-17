"""
Admin API routes for content management (Factions, PlotBeats, ContentPacks).

Provides CRUD operations for factions, plot beats, and content pack import.
All endpoints require admin role authentication.
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session as DBSession

from ..storage.database import get_db
from ..storage.models import UserModel, FactionModel, PlotBeatModel
from ..storage.repositories import (
    FactionRepository,
    PlotBeatRepository,
    StoryPackageVersionRepository,
)
from .admin import require_admin, require_admin_role

router = APIRouter(prefix="/admin", tags=["admin"])


# =============================================================================
# Path Validation Helper
# =============================================================================

def validate_content_pack_path(path: str) -> Path:
    """
    Validate that the path is a safe content pack path.
    
    Args:
        path: The path to validate
        
    Returns:
        Resolved Path object
        
    Raises:
        HTTPException: If path contains traversal or doesn't start with content_packs/
    """
    if not path.startswith("content_packs/"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Path must start with 'content_packs/'"
        )

    repo_root = Path(__file__).resolve().parents[3]
    content_packs_root = (repo_root / "content_packs").resolve()
    resolved_path = (repo_root / path).resolve()

    if resolved_path == content_packs_root or not resolved_path.is_relative_to(content_packs_root):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Path traversal not allowed"
        )

    return resolved_path


# =============================================================================
# Faction Pydantic Models
# =============================================================================

class FactionGoalModel(BaseModel):
    goal_id: str
    description: str
    priority: int = 0
    status: str = "active"


class FactionRelationshipModel(BaseModel):
    target_faction_id: str
    relationship_type: str = "neutral"
    score: int = 0


class FactionListItem(BaseModel):
    id: str
    logical_id: str
    world_id: str
    name: str
    visibility: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class FactionDetail(FactionListItem):
    ideology: Dict[str, Any] = {}
    goals: List[FactionGoalModel] = []
    relationships: List[FactionRelationshipModel] = []


class FactionCreateRequest(BaseModel):
    logical_id: str = Field(..., min_length=1)
    world_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    ideology: Optional[Dict[str, Any]] = None
    goals: Optional[List[FactionGoalModel]] = None
    relationships: Optional[List[FactionRelationshipModel]] = None
    visibility: str = "public"
    status: str = "active"


class FactionUpdateRequest(BaseModel):
    name: Optional[str] = None
    ideology: Optional[Dict[str, Any]] = None
    goals: Optional[List[FactionGoalModel]] = None
    relationships: Optional[List[FactionRelationshipModel]] = None
    visibility: Optional[str] = None
    status: Optional[str] = None

    @model_validator(mode='before')
    @classmethod
    def reject_logical_id(cls, data):
        if data and 'logical_id' in data:
            raise ValueError('logical_id cannot be changed')
        return data


# =============================================================================
# Plot Beat Pydantic Models
# =============================================================================

class PlotBeatConditionModel(BaseModel):
    type: str
    params: Dict[str, Any] = {}


class PlotBeatEffectModel(BaseModel):
    type: str
    params: Dict[str, Any] = {}


class PlotBeatListItem(BaseModel):
    id: str
    logical_id: str
    world_id: str
    title: str
    priority: int
    visibility: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class PlotBeatDetail(PlotBeatListItem):
    conditions: List[PlotBeatConditionModel] = []
    effects: List[PlotBeatEffectModel] = []


class PlotBeatCreateRequest(BaseModel):
    logical_id: str = Field(..., min_length=1)
    world_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    conditions: Optional[List[PlotBeatConditionModel]] = None
    effects: Optional[List[PlotBeatEffectModel]] = None
    priority: int = 0
    visibility: str = "conditional"
    status: str = "pending"


class PlotBeatUpdateRequest(BaseModel):
    title: Optional[str] = None
    conditions: Optional[List[PlotBeatConditionModel]] = None
    effects: Optional[List[PlotBeatEffectModel]] = None
    priority: Optional[int] = None
    visibility: Optional[str] = None
    status: Optional[str] = None

    @model_validator(mode='before')
    @classmethod
    def reject_logical_id(cls, data):
        if data and 'logical_id' in data:
            raise ValueError('logical_id cannot be changed')
        return data


# =============================================================================
# Content Pack Pydantic Models
# =============================================================================

class ContentPackPathRequest(BaseModel):
    path: str = Field(..., description="Path to content pack directory")


class ContentPackValidateResponse(BaseModel):
    is_valid: bool
    issues: List[Dict[str, Any]] = []
    pack_id: Optional[str] = None
    pack_name: Optional[str] = None


class ContentPackImportResponse(BaseModel):
    success: bool
    imported_count: int = 0
    factions_imported: int = 0
    plot_beats_imported: int = 0
    errors: List[str] = []
    warnings: List[str] = []
    dry_run: bool = False
    pack_id: Optional[str] = None
    pack_name: Optional[str] = None
    version_id: Optional[str] = None
    manifest_json: Optional[Dict[str, Any]] = None


class ContentPackPublishAsVersionRequest(BaseModel):
    path: str = Field(..., description="Path to content pack directory")
    world_id: Optional[str] = None
    publish: bool = Field(default=False, description="If true, publish the version immediately after creation")


class ContentPackPublishRequest(BaseModel):
    version: Optional[str] = None
    dry_run: Optional[bool] = None


class ContentPackPublishResponse(BaseModel):
    dry_run: bool = False
    package_id: Optional[str] = None
    pack_version: Optional[str] = None
    source_hash: Optional[str] = None
    runtime_hash: Optional[str] = None
    bundle_schema_version: Optional[int] = None
    engine_rules_version: Optional[int] = None
    counts: Optional[Dict[str, int]] = None
    ref_map: Optional[Dict[str, str]] = None
    version_id: Optional[str] = None
    world_id: Optional[str] = None
    created: Optional[bool] = None


def _raise_content_publish_http(error) -> None:
    status_code = (
        status.HTTP_409_CONFLICT
        if error.code in {"CONTENT_FROZEN_VERSION", "CONTENT_VERSION_CONFLICT", "CONTENT_WORLD_ALREADY_BOUND"}
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    raise HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.message, "path": error.path},
    )


def _assert_world_content_mutable(db: DBSession, world_id: str) -> None:
    from ..core.content_publish_service import assert_world_content_mutable, ContentPublishError

    try:
        assert_world_content_mutable(db, world_id)
    except ContentPublishError as error:
        _raise_content_publish_http(error)


def _guard_legacy_pack_targets(db: DBSession, pack_path: Path) -> None:
    """Preflight the v1 import target worlds before its importer writes rows."""
    from ..content.loader import load_content_pack, ContentPackLoadError

    try:
        legacy_pack = load_content_pack(pack_path)
    except ContentPackLoadError:
        # Keep the v1 import service's existing load-error response unchanged.
        return
    for definition in [*legacy_pack.factions, *legacy_pack.plot_beats]:
        _assert_world_content_mutable(db, definition.world_id)


# =============================================================================
# Faction Routes
# =============================================================================

@router.get("/factions", response_model=List[FactionListItem])
def list_factions(
    world_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    List all factions.
    
    Returns a paginated list of factions.
    Optionally filter by world_id.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = FactionRepository(db)
    
    if world_id:
        factions = repo.list_by_world(world_id)
    else:
        factions = repo.get_all(skip=skip, limit=limit)
    
    return [FactionListItem.model_validate(f) for f in factions]


@router.post("/factions", response_model=FactionDetail, status_code=status.HTTP_201_CREATED)
def create_faction(
    request: FactionCreateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Create a new faction.
    
    Requires admin role.
    """
    require_admin_role(current_user)
    _assert_world_content_mutable(db, request.world_id)
    repo = FactionRepository(db)
    
    # Check if faction with this logical_id already exists in this world
    existing = repo.get_by_logical_id(request.world_id, request.logical_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Faction with logical_id '{request.logical_id}' already exists in this world"
        )
    
    data = request.model_dump()
    if data.get("ideology") is None:
        data["ideology"] = {}
    if data.get("goals") is None:
        data["goals"] = []
    if data.get("relationships") is None:
        data["relationships"] = []
    
    # Convert Pydantic models to dicts for JSON columns
    if data.get("goals"):
        data["goals"] = [g.model_dump() if hasattr(g, 'model_dump') else g for g in data["goals"]]
    if data.get("relationships"):
        data["relationships"] = [r.model_dump() if hasattr(r, 'model_dump') else r for r in data["relationships"]]
    
    faction = repo.create(data)
    return FactionDetail.model_validate(faction)


@router.get("/factions/{faction_id}", response_model=FactionDetail)
def get_faction(
    faction_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get faction details.
    
    Returns detailed information about a specific faction.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = FactionRepository(db)
    faction = repo.get_by_id(faction_id)
    
    if not faction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Faction not found"
        )
    
    return FactionDetail.model_validate(faction)


@router.patch("/factions/{faction_id}", response_model=FactionDetail)
def update_faction(
    faction_id: str,
    request: FactionUpdateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Update faction configuration.
    
    Updates faction properties. Only provided fields are modified.
    logical_id cannot be changed.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = FactionRepository(db)
    faction = repo.get_by_id(faction_id)
    
    if not faction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Faction not found"
        )
    _assert_world_content_mutable(db, faction.world_id)
    
    update_data = request.model_dump(exclude_unset=True)
    
    # Explicitly reject logical_id changes
    if "logical_id" in update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="logical_id cannot be changed"
        )
    
    if not update_data:
        return FactionDetail.model_validate(faction)
    
    # Convert Pydantic models to dicts for JSON columns
    if "goals" in update_data and update_data["goals"]:
        update_data["goals"] = [g.model_dump() if hasattr(g, 'model_dump') else g for g in update_data["goals"]]
    if "relationships" in update_data and update_data["relationships"]:
        update_data["relationships"] = [r.model_dump() if hasattr(r, 'model_dump') else r for r in update_data["relationships"]]
    
    updated = repo.update(faction_id, update_data)
    return FactionDetail.model_validate(updated)


@router.delete("/factions/{faction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_faction(
    faction_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Delete a faction.
    
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = FactionRepository(db)
    faction = repo.get_by_id(faction_id)
    
    if not faction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Faction not found"
        )
    _assert_world_content_mutable(db, faction.world_id)
    
    repo.delete(faction_id)
    return None


# =============================================================================
# Plot Beat Routes
# =============================================================================

@router.get("/plot-beats", response_model=List[PlotBeatListItem])
def list_plot_beats(
    world_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    List all plot beats.
    
    Returns a paginated list of plot beats.
    Optionally filter by world_id.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = PlotBeatRepository(db)
    
    if world_id:
        plot_beats = repo.list_by_world(world_id)
    else:
        plot_beats = repo.get_all(skip=skip, limit=limit)
    
    return [PlotBeatListItem.model_validate(pb) for pb in plot_beats]


@router.post("/plot-beats", response_model=PlotBeatDetail, status_code=status.HTTP_201_CREATED)
def create_plot_beat(
    request: PlotBeatCreateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Create a new plot beat.
    
    Requires admin role.
    """
    require_admin_role(current_user)
    _assert_world_content_mutable(db, request.world_id)
    repo = PlotBeatRepository(db)
    
    # Check if plot beat with this logical_id already exists in this world
    existing = repo.get_by_logical_id(request.world_id, request.logical_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Plot beat with logical_id '{request.logical_id}' already exists in this world"
        )
    
    data = request.model_dump()
    if data.get("conditions") is None:
        data["conditions"] = []
    if data.get("effects") is None:
        data["effects"] = []
    
    # Convert Pydantic models to dicts for JSON columns
    if data.get("conditions"):
        data["conditions"] = [c.model_dump() if hasattr(c, 'model_dump') else c for c in data["conditions"]]
    if data.get("effects"):
        data["effects"] = [e.model_dump() if hasattr(e, 'model_dump') else e for e in data["effects"]]
    
    plot_beat = repo.create(data)
    return PlotBeatDetail.model_validate(plot_beat)


@router.get("/plot-beats/{beat_id}", response_model=PlotBeatDetail)
def get_plot_beat(
    beat_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get plot beat details.
    
    Returns detailed information about a specific plot beat.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = PlotBeatRepository(db)
    plot_beat = repo.get_by_id(beat_id)
    
    if not plot_beat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plot beat not found"
        )
    
    return PlotBeatDetail.model_validate(plot_beat)


@router.patch("/plot-beats/{beat_id}", response_model=PlotBeatDetail)
def update_plot_beat(
    beat_id: str,
    request: PlotBeatUpdateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Update plot beat configuration.
    
    Updates plot beat properties. Only provided fields are modified.
    logical_id cannot be changed.
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = PlotBeatRepository(db)
    plot_beat = repo.get_by_id(beat_id)
    
    if not plot_beat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plot beat not found"
        )
    _assert_world_content_mutable(db, plot_beat.world_id)
    
    update_data = request.model_dump(exclude_unset=True)
    
    # Explicitly reject logical_id changes
    if "logical_id" in update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="logical_id cannot be changed"
        )
    
    if not update_data:
        return PlotBeatDetail.model_validate(plot_beat)
    
    # Convert Pydantic models to dicts for JSON columns
    if "conditions" in update_data and update_data["conditions"]:
        update_data["conditions"] = [c.model_dump() if hasattr(c, 'model_dump') else c for c in update_data["conditions"]]
    if "effects" in update_data and update_data["effects"]:
        update_data["effects"] = [e.model_dump() if hasattr(e, 'model_dump') else e for e in update_data["effects"]]
    
    updated = repo.update(beat_id, update_data)
    return PlotBeatDetail.model_validate(updated)


@router.delete("/plot-beats/{beat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plot_beat(
    beat_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Delete a plot beat.
    
    Requires admin role.
    """
    require_admin_role(current_user)
    repo = PlotBeatRepository(db)
    plot_beat = repo.get_by_id(beat_id)
    
    if not plot_beat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plot beat not found"
        )
    _assert_world_content_mutable(db, plot_beat.world_id)
    
    repo.delete(beat_id)
    return None


# =============================================================================
# Content Pack Routes
# =============================================================================

@router.post("/content-packs/validate", response_model=ContentPackValidateResponse)
def validate_content_pack(
    request: ContentPackPathRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Validate a content pack by path.
    
    Validates the content pack without importing it.
    Path must start with 'content_packs/' and cannot contain '../'.
    Requires admin role.
    """
    require_admin_role(current_user)
    
    # Validate path
    pack_path = validate_content_pack_path(request.path)
    
    try:
        from ..content.loader import load_content_pack, ContentPackLoadError
        from ..content.validator import ContentValidator
        
        pack = load_content_pack(pack_path)
        validator = ContentValidator()
        report = validator.validate(pack)
        
        return ContentPackValidateResponse(
            is_valid=report.is_valid,
            issues=[
                {
                    "severity": issue.severity,
                    "message": issue.message,
                    "path": issue.path,
                    "code": issue.code,
                }
                for issue in report.issues
            ],
            pack_id=pack.manifest.id,
            pack_name=pack.manifest.name,
        )
    except ContentPackLoadError as e:
        return ContentPackValidateResponse(
            is_valid=False,
            issues=[{
                "severity": "error",
                "message": str(e),
                "path": request.path,
                "code": "LOAD_ERROR",
            }],
        )
    except Exception as e:
        return ContentPackValidateResponse(
            is_valid=False,
            issues=[{
                "severity": "error",
                "message": f"Unexpected error: {e}",
                "path": request.path,
                "code": "UNEXPECTED_ERROR",
            }],
        )


@router.post("/content-packs/import", response_model=ContentPackImportResponse)
def import_content_pack(
    request: ContentPackPathRequest,
    dry_run: bool = Query(False, description="If true, validate without importing"),
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Import a content pack by path.
    
    Imports factions and plot beats from the content pack.
    Supports dry_run query parameter to validate without importing.
    Path must start with 'content_packs/' and cannot contain '../'.
    Requires admin role.
    """
    require_admin_role(current_user)
    
    # Validate path
    pack_path = validate_content_pack_path(request.path)
    
    try:
        if not dry_run:
            _guard_legacy_pack_targets(db, pack_path)

        from ..content.importer import ContentImportService
        
        service = ContentImportService(db)
        report = service.import_pack(pack_path, dry_run=dry_run)
        
        return ContentPackImportResponse(
            success=report.success,
            imported_count=report.imported_count,
            factions_imported=report.factions_imported,
            plot_beats_imported=report.plot_beats_imported,
            errors=report.errors,
            warnings=report.warnings,
            dry_run=report.dry_run,
            pack_id=report.pack_id,
            pack_name=report.pack_name,
        )
    except HTTPException:
        raise
    except Exception as e:
        return ContentPackImportResponse(
            success=False,
            errors=[f"Import failed: {e}"],
            dry_run=dry_run,
        )


@router.post("/content-packs/publish-as-version", response_model=ContentPackImportResponse)
def publish_content_pack_as_version(
    request: ContentPackPublishAsVersionRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Import a content pack and create a StoryPackageVersion from it.

    Imports factions and plot_beats (same as /content-packs/import),
    then creates a draft StoryPackageVersion row with manifest built from
    the loaded pack. Optionally publishes the version immediately.

    Path must start with 'content_packs/' and cannot contain '../'.
    Requires admin role.
    """
    require_admin_role(current_user)

    pack_path = validate_content_pack_path(request.path)
    if request.world_id:
        _assert_world_content_mutable(db, request.world_id)
    _guard_legacy_pack_targets(db, pack_path)

    try:
        from ..content.importer import ContentImportService

        service = ContentImportService(db)
        report = service.import_pack_as_version(
            pack_path,
            world_id=request.world_id,
            dry_run=False,
        )

        if request.publish and report.version_id:
            from ..core.story_package_service import (
                publish_story_package_version,
                StoryPackageVersionError,
            )
            try:
                publish_story_package_version(db, report.version_id)
            except StoryPackageVersionError:
                pass

        return ContentPackImportResponse(
            success=report.success,
            imported_count=report.imported_count,
            factions_imported=report.factions_imported,
            plot_beats_imported=report.plot_beats_imported,
            errors=report.errors,
            warnings=report.warnings,
            dry_run=report.dry_run,
            pack_id=report.pack_id,
            pack_name=report.pack_name,
            version_id=report.version_id,
            manifest_json=report.manifest_json,
        )
    except Exception as e:
        return ContentPackImportResponse(
            success=False,
            errors=[f"Import/publish-as-version failed: {e}"],
        )


@router.post(
    "/content-packs/{pack_id}/publish",
    response_model=ContentPackPublishResponse,
    response_model_exclude_none=True,
)
def publish_content_v1_pack(
    pack_id: str,
    request: Optional[ContentPackPublishRequest] = None,
    version: Optional[str] = Query(None),
    dry_run: Optional[bool] = Query(None),
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    """Publish a strict content_v1 pack, or return read-only diagnostics."""
    require_admin_role(current_user)
    pack_path = validate_content_pack_path(f"content_packs/{pack_id}")
    selected_version = (request.version if request and request.version is not None else version)
    selected_dry_run = request.dry_run if request and request.dry_run is not None else bool(dry_run)

    from ..core.content_publish_service import (
        ContentPublishError,
        dry_run_content_pack,
        publish_content_pack_version,
    )

    try:
        if selected_dry_run:
            diagnostic = dry_run_content_pack(pack_path)
            return {
                "dry_run": True,
                "package_id": diagnostic.package_id,
                "pack_version": diagnostic.pack_version,
                "source_hash": diagnostic.source_hash,
                "runtime_hash": diagnostic.runtime_hash,
                "bundle_schema_version": diagnostic.bundle_schema_version,
                "engine_rules_version": diagnostic.engine_rules_version,
                "counts": dict(diagnostic.counts),
                "ref_map": dict(diagnostic.ref_map),
            }
        result = publish_content_pack_version(
            db,
            pack_dir=pack_path,
            version=selected_version,
        )
        return {
            "dry_run": False,
            "version_id": result.version_id,
            "world_id": result.world_id,
            "runtime_hash": result.runtime_hash,
            "source_hash": result.source_hash,
            "created": result.created,
        }
    except ContentPublishError as error:
        _raise_content_publish_http(error)


# =============================================================================
# Story Package Version Pydantic Models
# =============================================================================

class StoryPackageVersionCreateRequest(BaseModel):
    story_package_id: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    world_id: Optional[str] = None
    manifest_json: Optional[Dict[str, Any]] = None
    editor_schema_version: Optional[str] = None
    source_hash: Optional[str] = None


class StoryPackageVersionResponse(BaseModel):
    id: str
    story_package_id: str
    version: str
    status: str
    world_id: Optional[str] = None
    manifest_json: Dict[str, Any] = {}
    editor_schema_version: Optional[str] = None
    source_hash: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InstantiateRequest(BaseModel):
    user_id: Optional[str] = None
    config_json: Optional[Dict[str, Any]] = None


class InstantiateResponse(BaseModel):
    playthrough_instance_id: str
    session_id: str
    baseline_snapshot_id: Optional[str] = None


# =============================================================================
# Story Package Version Routes
# =============================================================================

@router.post(
    "/story-package-versions",
    response_model=StoryPackageVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_story_package_version(
    request: StoryPackageVersionCreateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    require_admin_role(current_user)

    from ..core.story_package_service import (
        create_story_package_version as svc_create,
        StoryPackageVersionError,
    )

    try:
        spv = svc_create(
            db,
            story_package_id=request.story_package_id,
            version=request.version,
            world_id=request.world_id,
            manifest_json=request.manifest_json,
            editor_schema_version=request.editor_schema_version,
            source_hash=request.source_hash,
        )
    except StoryPackageVersionError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    return StoryPackageVersionResponse.model_validate(spv)


@router.get(
    "/story-package-versions/{version_id}",
    response_model=StoryPackageVersionResponse,
)
def get_story_package_version(
    version_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    require_admin_role(current_user)

    from ..core.story_package_service import get_story_package_version as svc_get

    spv = svc_get(db, version_id)
    if spv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story package version not found",
        )

    return StoryPackageVersionResponse.model_validate(spv)


@router.post(
    "/story-package-versions/{version_id}/publish",
    response_model=StoryPackageVersionResponse,
)
def publish_story_package_version(
    version_id: str,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    require_admin_role(current_user)

    from ..core.story_package_service import (
        publish_story_package_version as svc_publish,
        StoryPackageVersionError,
    )

    try:
        from ..core.content_publish_service import assert_version_content_mutable, ContentPublishError
        try:
            assert_version_content_mutable(db, version_id)
        except ContentPublishError as error:
            _raise_content_publish_http(error)
        spv = svc_publish(db, version_id)
    except StoryPackageVersionError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    return StoryPackageVersionResponse.model_validate(spv)


@router.post(
    "/story-package-versions/{version_id}/instantiate",
    response_model=InstantiateResponse,
    status_code=status.HTTP_201_CREATED,
)
def instantiate_story_package_version(
    version_id: str,
    request: InstantiateRequest,
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db),
):
    require_admin_role(current_user)

    from ..core.playthrough_instance_service import (
        create_playthrough_from_version,
        PlaythroughInstanceError,
    )

    try:
        result = create_playthrough_from_version(
            db,
            version_id=version_id,
            user_id=request.user_id,
            config_json=request.config_json,
        )
    except PlaythroughInstanceError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    return InstantiateResponse(
        playthrough_instance_id=result.playthrough_instance_id,
        session_id=result.session_id,
        baseline_snapshot_id=result.baseline_snapshot_id,
    )
