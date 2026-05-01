"""
Media API routes for LLM RPG Engine.

These endpoints are RESERVED for future media generation features.
They return HTTP 501 Not Implemented responses to document the API contract
while indicating these features are not in the current runtime scope.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/media", tags=["media"])


class PortraitGenerateRequest(BaseModel):
    npc_id: str = Field(..., description="NPC template ID")
    style: Optional[str] = Field("anime", description="Art style for the portrait")
    expression: Optional[str] = Field("neutral", description="NPC expression")


class PortraitGenerateResponse(BaseModel):
    portrait_id: str
    npc_id: str
    image_url: str
    style: str
    status: str


class SceneGenerateRequest(BaseModel):
    location_id: str = Field(..., description="Location ID")
    time_of_day: Optional[str] = Field("day", description="Time of day for scene")
    weather: Optional[str] = Field(None, description="Weather condition")


class SceneGenerateResponse(BaseModel):
    scene_id: str
    location_id: str
    image_url: str
    time_of_day: str
    status: str


class BGMGenerateRequest(BaseModel):
    location_id: Optional[str] = Field(None, description="Location ID for ambient music")
    mood: str = Field(..., description="Mood/theme for the music")
    duration_seconds: Optional[int] = Field(60, ge=10, le=300)


class BGMGenerateResponse(BaseModel):
    track_id: str
    audio_url: str
    mood: str
    duration_seconds: int
    status: str


RESERVED_DETAIL = "Media generation is reserved for future implementation and not available in the current runtime scope."


@router.post(
    "/portraits/generate",
    response_model=PortraitGenerateResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="Generate character portrait",
    description="Generate an AI portrait for an NPC character. RESERVED - returns 501."
)
def generate_portrait(request: PortraitGenerateRequest):
    """
    Generate a character portrait.

    This endpoint is RESERVED for future implementation.
    It will generate AI portraits for NPC characters based on their template.

    Returns HTTP 501 Not Implemented.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=RESERVED_DETAIL
    )


@router.post(
    "/scenes/generate",
    response_model=SceneGenerateResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="Generate scene image",
    description="Generate an AI scene image for a location. RESERVED - returns 501."
)
def generate_scene(request: SceneGenerateRequest):
    """
    Generate a scene image.

    This endpoint is RESERVED for future implementation.
    It will generate AI scene images for game locations.

    Returns HTTP 501 Not Implemented.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=RESERVED_DETAIL
    )


@router.post(
    "/bgm/generate",
    response_model=BGMGenerateResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="Generate background music",
    description="Generate AI background music for a mood/location. RESERVED - returns 501."
)
def generate_bgm(request: BGMGenerateRequest):
    """
    Generate background music.

    This endpoint is RESERVED for future implementation.
    It will generate AI background music based on mood and location.

    Returns HTTP 501 Not Implemented.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=RESERVED_DETAIL
    )
