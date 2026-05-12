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
from ..storage.repositories import FactionRepository, PlotBeatRepository
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
    if "../" in path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Path traversal not allowed"
        )
    
    if not path.startswith("content_packs/"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Path must start with 'content_packs/'"
        )
    
    return Path(path)


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
    except Exception as e:
        return ContentPackImportResponse(
            success=False,
            errors=[f"Import failed: {e}"],
            dry_run=dry_run,
        )
