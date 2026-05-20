"""
Audio Asset Provider - Placeholder Implementation

Provides placeholder URLs for BGM and SFX asset types.
Disabled by default; enable via ASSET_AUDIO_PROVIDER_ENABLED=true.
"""

import os
import time
import uuid
from typing import Dict

from .interfaces import (
    AssetGenerationRequest,
    AssetGenerationResult,
    AssetProvider,
    AssetStatus,
    AssetType,
)


class AudioAssetProvider(AssetProvider):
    """
    Placeholder audio asset provider.

    Returns placeholder URLs for BGM and SFX without actual generation.
    Disabled by default; set ASSET_AUDIO_PROVIDER_ENABLED=true to enable.
    """

    provider_name = "audio_placeholder"
    supported_asset_types = [AssetType.BGM, AssetType.SFX]

    def __init__(self):
        self._enabled = os.environ.get("ASSET_AUDIO_PROVIDER_ENABLED", "false").lower() == "true"
        self._requests: Dict[str, AssetGenerationResult] = {}

    @property
    def enabled(self) -> bool:
        """Whether this provider is enabled."""
        return self._enabled

    async def generate(
        self,
        request: AssetGenerationRequest,
    ) -> AssetGenerationResult:
        """
        Generate a placeholder audio asset.

        Returns COMPLETED status with a placeholder URL.
        """
        start = time.time()
        asset_id = str(uuid.uuid4())

        # Build placeholder URL based on asset type
        if request.asset_type == AssetType.BGM:
            placeholder_url = "https://placeholder.audio/bgm/default.mp3"
        elif request.asset_type == AssetType.SFX:
            placeholder_url = "https://placeholder.audio/sfx/default.mp3"
        else:
            placeholder_url = "https://placeholder.audio/unknown.bin"

        result = AssetGenerationResult(
            request_id=request.request_id,
            status=AssetStatus.COMPLETED,
            asset_url=placeholder_url,
            asset_id=asset_id,
            metadata={
                "placeholder": True,
                "asset_type": request.asset_type.value,
                "provider": self.provider_name,
            },
            processing_time_ms=int((time.time() - start) * 1000),
        )

        self._requests[request.request_id] = result
        return result

    async def check_status(self, request_id: str) -> AssetStatus:
        """Check the status of a generation request."""
        if request_id in self._requests:
            return self._requests[request_id].status
        return AssetStatus.FAILED

    async def cancel(self, request_id: str) -> bool:
        """Cancel a pending generation request."""
        if request_id in self._requests:
            result = self._requests[request_id]
            if result.status == AssetStatus.PENDING:
                result.status = AssetStatus.CANCELLED
                return True
        return False
