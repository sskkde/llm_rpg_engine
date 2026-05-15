"""OpenAI Image provider — env-gated stub for DALL-E integration."""

import os
import time
from .interfaces import (
    AssetProvider,
    AssetGenerationRequest,
    AssetGenerationResult,
    AssetType,
    AssetStatus,
)


class OpenAIImageProvider(AssetProvider):
    """OpenAI DALL-E image provider.
    
    Requires OPENAI_API_KEY environment variable.
    If key is unset, generate() returns an error result (safe failure).
    If key is set, generates mock URLs (stub — real API call deferred).
    """
    
    provider_name = "openai_image"
    supported_asset_types = [AssetType.PORTRAIT, AssetType.SCENE]
    
    def __init__(self):
        self._api_key = os.environ.get("OPENAI_API_KEY")
    
    async def generate(self, request: AssetGenerationRequest) -> AssetGenerationResult:
        """Generate an asset using OpenAI DALL-E (stub).
        
        Returns FAILED if API key not configured.
        Returns mock URL if API key is set (real implementation deferred).
        """
        if not self._api_key:
            return AssetGenerationResult(
                request_id=request.request_id,
                status=AssetStatus.FAILED,
                error_message="OPENAI_API_KEY not configured. Set the environment variable to enable DALL-E image generation.",
                processing_time_ms=0,
            )
        
        # Stub: return mock URL (real implementation deferred to production deployment)
        start = time.time()
        asset_id = f"openai_{request.request_id}"
        return AssetGenerationResult(
            request_id=request.request_id,
            status=AssetStatus.COMPLETED,
            asset_url=f"https://api.openai.com/v1/images/generations/stub/{asset_id}",
            asset_id=asset_id,
            metadata={
                "provider": "openai_image",
                "api_key_configured": True,
                "asset_type": request.asset_type.value,
            },
            processing_time_ms=int((time.time() - start) * 1000),
        )
    
    async def check_status(self, request_id: str) -> AssetStatus:
        return AssetStatus.COMPLETED if self._api_key else AssetStatus.FAILED
    
    async def cancel(self, request_id: str) -> bool:
        return False
    
    def get_provider_info(self) -> dict:
        """Return provider info WITHOUT exposing the API key."""
        return {
            "provider_name": self.provider_name,
            "supported_types": [t.value for t in self.supported_asset_types],
            "api_key_configured": bool(self._api_key),
        }
