"""
Portrait Generation Interface

Interface for character portrait generation.
"""

from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .interfaces import AssetGenerationRequest, AssetGenerationResult, AssetProvider, AssetType


class PortraitStyle(Enum):
    """Art styles for character portraits."""
    ANIME = "anime"
    REALISTIC = "realistic"
    PAINTING = "painting"
    SKETCH = "sketch"
    PIXEL_ART = "pixel_art"
    CEL_SHADED = "cel_shaded"
    WATERCOLOR = "watercolor"


class PortraitExpression(Enum):
    """Character expressions for portraits."""
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    THOUGHTFUL = "thoughtful"
    DETERMINED = "determined"
    SCARED = "scared"


@dataclass
class PortraitRequest(AssetGenerationRequest):
    """Request for character portrait generation."""
    npc_id: str = ""
    npc_name: str = ""
    npc_description: str = ""
    npc_personality: List[str] = field(default_factory=list)
    style: PortraitStyle = PortraitStyle.ANIME
    expression: PortraitExpression = PortraitExpression.NEUTRAL
    outfit_description: Optional[str] = None
    age_category: Optional[str] = None
    gender: Optional[str] = None
    
    def __post_init__(self):
        if not self.asset_type:
            self.asset_type = AssetType.PORTRAIT


@dataclass
class PortraitResult(AssetGenerationResult):
    """Result of portrait generation."""
    npc_id: str = ""
    style: PortraitStyle = PortraitStyle.ANIME
    expression: PortraitExpression = PortraitExpression.NEUTRAL
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None


class PortraitGenerator(AssetProvider):
    """
    Abstract portrait generator.
    
    Implementations generate character portraits based on NPC descriptions.
    """
    
    provider_name = "portrait"
    supported_asset_types = [AssetType.PORTRAIT]
    
    @abstractmethod
    async def generate_portrait(
        self,
        request: PortraitRequest,
    ) -> PortraitResult:
        """
        Generate a character portrait.
        
        Args:
            request: Portrait generation request
            
        Returns:
            PortraitResult with generated image URL
        """
        pass
    
    @abstractmethod
    async def generate_variations(
        self,
        request: PortraitRequest,
        num_variations: int = 4,
    ) -> List[PortraitResult]:
        """
        Generate multiple portrait variations.
        
        Args:
            request: Portrait generation request
            num_variations: Number of variations to generate
            
        Returns:
            List of PortraitResults
        """
        pass
    
    @abstractmethod
    async def modify_expression(
        self,
        base_portrait_id: str,
        new_expression: PortraitExpression,
    ) -> PortraitResult:
        """
        Modify an existing portrait's expression.
        
        Args:
            base_portrait_id: ID of the base portrait
            new_expression: New expression to apply
            
        Returns:
            Modified PortraitResult
        """
        pass
    
    async def generate(
        self,
        request: AssetGenerationRequest,
    ) -> AssetGenerationResult:
        """Implement base generate method."""
        if isinstance(request, PortraitRequest):
            return await self.generate_portrait(request)
        raise ValueError(f"Expected PortraitRequest, got {type(request)}")


class MockPortraitGenerator(PortraitGenerator):
    """
    Mock portrait generator for testing.
    
    Returns predetermined portrait URLs without external API calls.
    """
    
    provider_name = "mock_portrait"
    
    def __init__(self):
        self._portraits: Dict[str, PortraitResult] = {}
    
    async def generate_portrait(
        self,
        request: PortraitRequest,
    ) -> PortraitResult:
        """Generate a mock portrait."""
        import time
        import uuid
        
        start = time.time()
        portrait_id = str(uuid.uuid4())
        
        result = PortraitResult(
            request_id=request.request_id,
            status=AssetGenerationResult.__dataclass_fields__["status"].type,
            asset_id=portrait_id,
            npc_id=request.npc_id,
            style=request.style,
            expression=request.expression,
            image_url=f"https://example.com/mock/portraits/{portrait_id}.png",
            thumbnail_url=f"https://example.com/mock/portraits/{portrait_id}_thumb.png",
            metadata={
                "mock": True,
                "npc_name": request.npc_name,
                "style": request.style.value,
                "expression": request.expression.value,
            },
            processing_time_ms=int((time.time() - start) * 1000),
        )
        result.status = "completed"
        
        self._portraits[request.request_id] = result
        return result
    
    async def generate_variations(
        self,
        request: PortraitRequest,
        num_variations: int = 4,
    ) -> List[PortraitResult]:
        """Generate mock portrait variations."""
        variations = []
        for i in range(num_variations):
            variation_request = PortraitRequest(
                asset_type=request.asset_type,
                request_id=f"{request.request_id}_var{i}",
                npc_id=request.npc_id,
                npc_name=request.npc_name,
                npc_description=request.npc_description,
                style=request.style,
                expression=request.expression,
            )
            result = await self.generate_portrait(variation_request)
            variations.append(result)
        return variations
    
    async def modify_expression(
        self,
        base_portrait_id: str,
        new_expression: PortraitExpression,
    ) -> PortraitResult:
        """Mock modify expression."""
        import time
        import uuid
        
        start = time.time()
        portrait_id = str(uuid.uuid4())
        
        result = PortraitResult(
            request_id=str(uuid.uuid4()),
            status=AssetGenerationResult.__dataclass_fields__["status"].type,
            asset_id=portrait_id,
            npc_id=base_portrait_id,
            style=PortraitStyle.ANIME,
            expression=new_expression,
            image_url=f"https://example.com/mock/portraits/{portrait_id}_{new_expression.value}.png",
            thumbnail_url=f"https://example.com/mock/portraits/{portrait_id}_{new_expression.value}_thumb.png",
            metadata={
                "mock": True,
                "modified_from": base_portrait_id,
                "new_expression": new_expression.value,
            },
            processing_time_ms=int((time.time() - start) * 1000),
        )
        result.status = "completed"
        return result
    
    async def check_status(self, request_id: str):
        from .interfaces import AssetStatus
        if request_id in self._portraits:
            return AssetStatus.COMPLETED
        return AssetStatus.FAILED
    
    async def cancel(self, request_id: str) -> bool:
        return False
