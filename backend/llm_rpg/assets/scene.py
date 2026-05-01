"""
Scene Image Generation Interface

Interface for scene/location image generation.
"""

from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .interfaces import AssetGenerationRequest, AssetGenerationResult, AssetProvider, AssetType


class TimeOfDay(Enum):
    """Time of day for scene rendering."""
    DAWN = "dawn"
    DAY = "day"
    DUSK = "dusk"
    NIGHT = "night"
    MIDNIGHT = "midnight"


class WeatherCondition(Enum):
    """Weather conditions for scene rendering."""
    CLEAR = "clear"
    CLOUDY = "cloudy"
    RAINY = "rainy"
    STORMY = "stormy"
    FOGGY = "foggy"
    SNOWY = "snowy"


class ArtStyle(Enum):
    """Art styles for scene images."""
    REALISTIC = "realistic"
    PAINTED = "painted"
    ANIME = "anime"
    PIXEL_ART = "pixel_art"
    WATERCOLOR = "watercolor"
    CONCEPT_ART = "concept_art"


@dataclass
class SceneRequest(AssetGenerationRequest):
    """Request for scene image generation."""
    location_id: str = ""
    location_name: str = ""
    location_description: str = ""
    time_of_day: TimeOfDay = TimeOfDay.DAY
    weather: WeatherCondition = WeatherCondition.CLEAR
    art_style: ArtStyle = ArtStyle.PAINTED
    mood: Optional[str] = None
    focal_point: Optional[str] = None
    include_npcs: bool = False
    npc_ids: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.asset_type:
            self.asset_type = AssetType.SCENE


@dataclass
class SceneResult(AssetGenerationResult):
    """Result of scene generation."""
    location_id: str = ""
    time_of_day: TimeOfDay = TimeOfDay.DAY
    weather: WeatherCondition = WeatherCondition.CLEAR
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    width: int = 1024
    height: int = 768


class SceneGenerator(AssetProvider):
    """
    Abstract scene generator.
    
    Implementations generate location/scene images.
    """
    
    provider_name = "scene"
    supported_asset_types = [AssetType.SCENE]
    
    @abstractmethod
    async def generate_scene(
        self,
        request: SceneRequest,
    ) -> SceneResult:
        """
        Generate a scene image.
        
        Args:
            request: Scene generation request
            
        Returns:
            SceneResult with generated image URL
        """
        pass
    
    @abstractmethod
    async def generate_time_variations(
        self,
        request: SceneRequest,
        times: Optional[List[TimeOfDay]] = None,
    ) -> List[SceneResult]:
        """
        Generate the same scene at different times of day.
        
        Args:
            request: Base scene request
            times: List of times to generate (defaults to all)
            
        Returns:
            List of SceneResults
        """
        pass
    
    @abstractmethod
    async def generate_weather_variations(
        self,
        request: SceneRequest,
        weather_conditions: Optional[List[WeatherCondition]] = None,
    ) -> List[SceneResult]:
        """
        Generate the same scene in different weather conditions.
        
        Args:
            request: Base scene request
            weather_conditions: List of weather to generate (defaults to all)
            
        Returns:
            List of SceneResults
        """
        pass
    
    async def generate(
        self,
        request: AssetGenerationRequest,
    ) -> AssetGenerationResult:
        """Implement base generate method."""
        if isinstance(request, SceneRequest):
            return await self.generate_scene(request)
        raise ValueError(f"Expected SceneRequest, got {type(request)}")


class MockSceneGenerator(SceneGenerator):
    """
    Mock scene generator for testing.
    
    Returns predetermined scene URLs without external API calls.
    """
    
    provider_name = "mock_scene"
    
    def __init__(self):
        self._scenes: Dict[str, SceneResult] = {}
    
    async def generate_scene(
        self,
        request: SceneRequest,
    ) -> SceneResult:
        """Generate a mock scene."""
        import time
        import uuid
        
        start = time.time()
        scene_id = str(uuid.uuid4())
        
        result = SceneResult(
            request_id=request.request_id,
            status=AssetGenerationResult.__dataclass_fields__["status"].type,
            asset_id=scene_id,
            location_id=request.location_id,
            time_of_day=request.time_of_day,
            weather=request.weather,
            image_url=f"https://example.com/mock/scenes/{scene_id}.png",
            thumbnail_url=f"https://example.com/mock/scenes/{scene_id}_thumb.png",
            width=1024,
            height=768,
            metadata={
                "mock": True,
                "location_name": request.location_name,
                "time": request.time_of_day.value,
                "weather": request.weather.value,
            },
            processing_time_ms=int((time.time() - start) * 1000),
        )
        result.status = "completed"
        
        self._scenes[request.request_id] = result
        return result
    
    async def generate_time_variations(
        self,
        request: SceneRequest,
        times: Optional[List[TimeOfDay]] = None,
    ) -> List[SceneResult]:
        """Generate mock time variations."""
        if times is None:
            times = list(TimeOfDay)
        
        variations = []
        for time_of_day in times:
            variation_request = SceneRequest(
                asset_type=request.asset_type,
                request_id=f"{request.request_id}_{time_of_day.value}",
                location_id=request.location_id,
                location_name=request.location_name,
                location_description=request.location_description,
                time_of_day=time_of_day,
                weather=request.weather,
                art_style=request.art_style,
            )
            result = await self.generate_scene(variation_request)
            variations.append(result)
        return variations
    
    async def generate_weather_variations(
        self,
        request: SceneRequest,
        weather_conditions: Optional[List[WeatherCondition]] = None,
    ) -> List[SceneResult]:
        """Generate mock weather variations."""
        if weather_conditions is None:
            weather_conditions = list(WeatherCondition)
        
        variations = []
        for weather in weather_conditions:
            variation_request = SceneRequest(
                asset_type=request.asset_type,
                request_id=f"{request.request_id}_{weather.value}",
                location_id=request.location_id,
                location_name=request.location_name,
                location_description=request.location_description,
                time_of_day=request.time_of_day,
                weather=weather,
                art_style=request.art_style,
            )
            result = await self.generate_scene(variation_request)
            variations.append(result)
        return variations
    
    async def check_status(self, request_id: str):
        from .interfaces import AssetStatus
        if request_id in self._scenes:
            return AssetStatus.COMPLETED
        return AssetStatus.FAILED
    
    async def cancel(self, request_id: str) -> bool:
        return False
