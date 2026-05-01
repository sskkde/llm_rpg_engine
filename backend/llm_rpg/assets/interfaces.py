"""
Base Asset Generation Interfaces

Defines the core abstractions for all asset generation providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class AssetType(Enum):
    """Types of game assets that can be generated."""
    PORTRAIT = "portrait"
    SCENE = "scene"
    BGM = "bgm"
    SFX = "sfx"


class AssetStatus(Enum):
    """Status of an asset generation request."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AssetGenerationRequest:
    """Base request for asset generation."""
    asset_type: AssetType
    request_id: str
    session_id: Optional[str] = None
    game_context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AssetGenerationResult:
    """Base result of asset generation."""
    request_id: str
    status: AssetStatus
    asset_url: Optional[str] = None
    asset_id: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    processing_time_ms: int = 0
    generated_at: datetime = field(default_factory=datetime.utcnow)


class AssetProvider(ABC):
    """
    Abstract base class for asset generation providers.
    
    All asset generation implementations must inherit from this class
    and implement the required methods.
    """
    
    provider_name: str = ""
    supported_asset_types: List[AssetType] = []
    
    @abstractmethod
    async def generate(
        self,
        request: AssetGenerationRequest,
    ) -> AssetGenerationResult:
        """
        Generate an asset.
        
        Args:
            request: The generation request
            
        Returns:
            AssetGenerationResult with status and asset information
        """
        pass
    
    @abstractmethod
    async def check_status(
        self,
        request_id: str,
    ) -> AssetStatus:
        """
        Check the status of a generation request.
        
        Args:
            request_id: The ID of the request to check
            
        Returns:
            Current status of the request
        """
        pass
    
    @abstractmethod
    async def cancel(
        self,
        request_id: str,
    ) -> bool:
        """
        Cancel a pending generation request.
        
        Args:
            request_id: The ID of the request to cancel
            
        Returns:
            True if cancelled, False otherwise
        """
        pass
    
    def supports(self, asset_type: AssetType) -> bool:
        """Check if this provider supports the given asset type."""
        return asset_type in self.supported_asset_types
    
    def get_provider_info(self) -> Dict[str, Any]:
        """Get information about this provider."""
        return {
            "provider_name": self.provider_name,
            "supported_types": [t.value for t in self.supported_asset_types],
        }


class MockAssetProvider(AssetProvider):
    """
    Mock asset provider for testing.
    
    Returns predetermined responses without making external API calls.
    """
    
    provider_name = "mock"
    supported_asset_types = [
        AssetType.PORTRAIT,
        AssetType.SCENE,
        AssetType.BGM,
        AssetType.SFX,
    ]
    
    def __init__(self):
        self._requests: Dict[str, AssetGenerationResult] = {}
        self._mock_urls: Dict[AssetType, str] = {
            AssetType.PORTRAIT: "https://example.com/mock/portrait.png",
            AssetType.SCENE: "https://example.com/mock/scene.png",
            AssetType.BGM: "https://example.com/mock/bgm.mp3",
            AssetType.SFX: "https://example.com/mock/sfx.mp3",
        }
    
    async def generate(
        self,
        request: AssetGenerationRequest,
    ) -> AssetGenerationResult:
        """Generate a mock asset."""
        import time
        start = time.time()
        
        mock_url = self._mock_urls.get(
            request.asset_type,
            "https://example.com/mock/asset.bin"
        )
        
        result = AssetGenerationResult(
            request_id=request.request_id,
            status=AssetStatus.COMPLETED,
            asset_url=mock_url,
            asset_id=f"mock_{request.request_id}",
            metadata={"mock": True, "asset_type": request.asset_type.value},
            processing_time_ms=int((time.time() - start) * 1000),
        )
        
        self._requests[request.request_id] = result
        return result
    
    async def check_status(self, request_id: str) -> AssetStatus:
        """Check mock status."""
        if request_id in self._requests:
            return self._requests[request_id].status
        return AssetStatus.FAILED
    
    async def cancel(self, request_id: str) -> bool:
        """Cancel mock request."""
        if request_id in self._requests:
            result = self._requests[request_id]
            if result.status == AssetStatus.PENDING:
                result.status = AssetStatus.CANCELLED
                return True
        return False
