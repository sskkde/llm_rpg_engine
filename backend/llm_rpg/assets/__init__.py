"""
Asset Generation Interfaces

This package provides abstract interfaces for AI-generated game assets:
- Portraits: Character portrait generation
- Scenes: Scene image generation
- Audio: Background music and sound effects

All interfaces are provider-agnostic and can be implemented by various
backend providers (OpenAI DALL-E, Stable Diffusion, etc.)
"""

from .interfaces import (
    AssetProvider,
    AssetGenerationRequest,
    AssetGenerationResult,
    AssetType,
    AssetStatus,
)
from .portrait import (
    PortraitGenerator,
    PortraitRequest,
    PortraitResult,
    PortraitStyle,
    PortraitExpression,
)
from .scene import (
    SceneGenerator,
    SceneRequest,
    SceneResult,
    TimeOfDay,
    WeatherCondition,
)
from .audio import (
    AudioGenerator,
    BGMRequest,
    BGMResult,
    SFXRequest,
    SFXResult,
    MusicMood,
    SFXType,
)

__all__ = [
    # Base interfaces
    "AssetProvider",
    "AssetGenerationRequest",
    "AssetGenerationResult",
    "AssetType",
    "AssetStatus",
    # Portrait
    "PortraitGenerator",
    "PortraitRequest",
    "PortraitResult",
    "PortraitStyle",
    "PortraitExpression",
    # Scene
    "SceneGenerator",
    "SceneRequest",
    "SceneResult",
    "TimeOfDay",
    "WeatherCondition",
    # Audio
    "AudioGenerator",
    "BGMRequest",
    "BGMResult",
    "SFXRequest",
    "SFXResult",
    "MusicMood",
    "SFXType",
]
