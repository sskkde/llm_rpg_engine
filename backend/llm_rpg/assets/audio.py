"""
Audio Generation Interface

Interface for background music and sound effect generation.
"""

from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .interfaces import AssetGenerationRequest, AssetGenerationResult, AssetProvider, AssetType


class MusicMood(Enum):
    """Moods for background music."""
    CALM = "calm"
    TENSE = "tense"
    EPIC = "epic"
    MYSTERIOUS = "mysterious"
    SAD = "sad"
    JOYFUL = "joyful"
    DARK = "dark"
    PEACEFUL = "peaceful"
    DRAMATIC = "dramatic"
    ROMANTIC = "romantic"


class SFXType(Enum):
    """Types of sound effects."""
    UI_CLICK = "ui_click"
    UI_HOVER = "ui_hover"
    STEP = "step"
    DOOR_OPEN = "door_open"
    DOOR_CLOSE = "door_close"
    COMBAT_HIT = "combat_hit"
    COMBAT_MISS = "combat_miss"
    SPELL_CAST = "spell_cast"
    ITEM_PICKUP = "item_pickup"
    AMBIENT_WIND = "ambient_wind"
    AMBIENT_RAIN = "ambient_rain"
    AMBIENT_FIRE = "ambient_fire"
    AMBIENT_WATER = "ambient_water"


class MusicGenre(Enum):
    """Genres for background music."""
    ORCHESTRAL = "orchestral"
    FOLK = "folk"
    ELECTRONIC = "electronic"
    AMBIENT = "ambient"
    CLASSICAL = "classical"
    FANTASY = "fantasy"
    ASIAN = "asian"


@dataclass
class BGMRequest(AssetGenerationRequest):
    """Request for background music generation."""
    location_id: Optional[str] = None
    location_name: Optional[str] = None
    mood: MusicMood = MusicMood.CALM
    genre: MusicGenre = MusicGenre.FANTASY
    duration_seconds: int = 60
    loopable: bool = True
    intensity: int = 50
    tempo_bpm: Optional[int] = None
    
    def __post_init__(self):
        if not self.asset_type:
            self.asset_type = AssetType.BGM


@dataclass
class BGMResult(AssetGenerationResult):
    """Result of BGM generation."""
    mood: MusicMood = MusicMood.CALM
    genre: MusicGenre = MusicGenre.FANTASY
    duration_seconds: int = 60
    audio_url: Optional[str] = None
    loop_start_seconds: Optional[float] = None
    loop_end_seconds: Optional[float] = None


@dataclass
class SFXRequest(AssetGenerationRequest):
    """Request for sound effect generation."""
    sfx_type: SFXType = SFXType.UI_CLICK
    description: Optional[str] = None
    duration_seconds: int = 1
    volume_db: float = 0.0
    pitch_variation: float = 0.0
    
    def __post_init__(self):
        if not self.asset_type:
            self.asset_type = AssetType.SFX


@dataclass
class SFXResult(AssetGenerationResult):
    """Result of SFX generation."""
    sfx_type: SFXType = SFXType.UI_CLICK
    duration_seconds: int = 1
    audio_url: Optional[str] = None


class AudioGenerator(AssetProvider):
    """
    Abstract audio generator.
    
    Implementations generate background music and sound effects.
    """
    
    provider_name = "audio"
    supported_asset_types = [AssetType.BGM, AssetType.SFX]
    
    @abstractmethod
    async def generate_bgm(
        self,
        request: BGMRequest,
    ) -> BGMResult:
        """
        Generate background music.
        
        Args:
            request: BGM generation request
            
        Returns:
            BGMResult with generated audio URL
        """
        pass
    
    @abstractmethod
    async def generate_sfx(
        self,
        request: SFXRequest,
    ) -> SFXResult:
        """
        Generate a sound effect.
        
        Args:
            request: SFX generation request
            
        Returns:
            SFXResult with generated audio URL
        """
        pass
    
    @abstractmethod
    async def generate_sfx_batch(
        self,
        requests: List[SFXRequest],
    ) -> List[SFXResult]:
        """
        Generate multiple sound effects in batch.
        
        Args:
            requests: List of SFX requests
            
        Returns:
            List of SFXResults
        """
        pass
    
    @abstractmethod
    async def extend_bgm(
        self,
        existing_bgm_id: str,
        additional_duration_seconds: int,
    ) -> BGMResult:
        """
        Extend an existing background music track.
        
        Args:
            existing_bgm_id: ID of the existing track
            additional_duration_seconds: Seconds to add
            
        Returns:
            Extended BGMResult
        """
        pass
    
    async def generate(
        self,
        request: AssetGenerationRequest,
    ) -> AssetGenerationResult:
        """Implement base generate method."""
        if isinstance(request, BGMRequest):
            return await self.generate_bgm(request)
        elif isinstance(request, SFXRequest):
            return await self.generate_sfx(request)
        raise ValueError(f"Unknown request type: {type(request)}")


class MockAudioGenerator(AudioGenerator):
    """
    Mock audio generator for testing.
    
    Returns predetermined audio URLs without external API calls.
    """
    
    provider_name = "mock_audio"
    
    def __init__(self):
        self._audio: Dict[str, AssetGenerationResult] = {}
    
    async def generate_bgm(
        self,
        request: BGMRequest,
    ) -> BGMResult:
        """Generate mock BGM."""
        import time
        import uuid
        
        start = time.time()
        audio_id = str(uuid.uuid4())
        
        result = BGMResult(
            request_id=request.request_id,
            status=AssetGenerationResult.__dataclass_fields__["status"].type,
            asset_id=audio_id,
            mood=request.mood,
            genre=request.genre,
            duration_seconds=request.duration_seconds,
            audio_url=f"https://example.com/mock/audio/bgm_{audio_id}.mp3",
            loop_start_seconds=0.0,
            loop_end_seconds=request.duration_seconds,
            metadata={
                "mock": True,
                "location": request.location_name,
                "mood": request.mood.value,
                "genre": request.genre.value,
                "loopable": request.loopable,
            },
            processing_time_ms=int((time.time() - start) * 1000),
        )
        result.status = "completed"
        
        self._audio[request.request_id] = result
        return result
    
    async def generate_sfx(
        self,
        request: SFXRequest,
    ) -> SFXResult:
        """Generate mock SFX."""
        import time
        import uuid
        
        start = time.time()
        audio_id = str(uuid.uuid4())
        
        result = SFXResult(
            request_id=request.request_id,
            status=AssetGenerationResult.__dataclass_fields__["status"].type,
            asset_id=audio_id,
            sfx_type=request.sfx_type,
            duration_seconds=request.duration_seconds,
            audio_url=f"https://example.com/mock/audio/sfx_{request.sfx_type.value}_{audio_id}.mp3",
            metadata={
                "mock": True,
                "sfx_type": request.sfx_type.value,
                "volume_db": request.volume_db,
            },
            processing_time_ms=int((time.time() - start) * 1000),
        )
        result.status = "completed"
        
        self._audio[request.request_id] = result
        return result
    
    async def generate_sfx_batch(
        self,
        requests: List[SFXRequest],
    ) -> List[SFXResult]:
        """Generate mock SFX batch."""
        results = []
        for req in requests:
            result = await self.generate_sfx(req)
            results.append(result)
        return results
    
    async def extend_bgm(
        self,
        existing_bgm_id: str,
        additional_duration_seconds: int,
    ) -> BGMResult:
        """Mock extend BGM."""
        import time
        import uuid
        
        start = time.time()
        new_audio_id = str(uuid.uuid4())
        
        result = BGMResult(
            request_id=str(uuid.uuid4()),
            status=AssetGenerationResult.__dataclass_fields__["status"].type,
            asset_id=new_audio_id,
            mood=MusicMood.CALM,
            genre=MusicGenre.FANTASY,
            duration_seconds=additional_duration_seconds,
            audio_url=f"https://example.com/mock/audio/bgm_extended_{new_audio_id}.mp3",
            metadata={
                "mock": True,
                "extended_from": existing_bgm_id,
                "additional_duration": additional_duration_seconds,
            },
            processing_time_ms=int((time.time() - start) * 1000),
        )
        result.status = "completed"
        return result
    
    async def check_status(self, request_id: str):
        from .interfaces import AssetStatus
        if request_id in self._audio:
            return AssetStatus.COMPLETED
        return AssetStatus.FAILED
    
    async def cancel(self, request_id: str) -> bool:
        return False
