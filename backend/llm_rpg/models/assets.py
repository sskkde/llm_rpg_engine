"""Pydantic schemas for asset generation requests and responses."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AssetType(str, Enum):
    """Types of game assets that can be generated."""
    PORTRAIT = "portrait"
    SCENE = "scene"
    BGM = "bgm"
    # SFX is deferred to P7


class AssetGenerationStatus(str, Enum):
    """Status of an asset generation request (API-facing)."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AssetGenerationRequest(BaseModel):
    """Request schema for generating a game asset."""
    asset_type: AssetType = Field(..., description="Type of asset to generate")
    prompt: str = Field(..., min_length=1, max_length=2000, description="Generation prompt")
    style: Optional[str] = Field(None, description="Art style override")
    session_id: Optional[str] = Field(None, description="Session ID for scoping")
    world_id: Optional[str] = Field(None, description="World ID for context")
    owner_entity_id: Optional[str] = Field(None, description="Entity that owns this asset")
    owner_entity_type: Optional[str] = Field(None, description="Entity type (npc, location, etc.)")
    provider: Optional[str] = Field(None, description="Provider override (default: mock)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class AssetResponse(BaseModel):
    """Response schema for asset generation result."""
    asset_id: str = Field(..., description="Public asset identifier")
    asset_type: AssetType = Field(..., description="Type of asset")
    generation_status: AssetGenerationStatus = Field(..., description="Generation status")
    result_url: Optional[str] = Field(None, description="URL to the generated asset (None if not ready/failed)")
    error_message: Optional[str] = Field(None, description="Error message if generation failed")
    provider: Optional[str] = Field(None, description="Provider used for generation")
    cache_hit: bool = Field(default=False, description="Whether this was served from cache")
    created_at: datetime = Field(default_factory=datetime.now, description="When the asset was created")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class AssetReference(BaseModel):
    """Minimal asset reference for embedding in game state."""
    asset_id: str
    asset_type: AssetType
    generation_status: AssetGenerationStatus
    result_url: Optional[str] = None
