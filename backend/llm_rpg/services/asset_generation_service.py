"""Asset generation service — orchestrates asset creation with caching and error handling."""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy.exc import IntegrityError

from llm_rpg.models.assets import (
    AssetGenerationRequest,
    AssetGenerationStatus,
    AssetResponse,
    AssetType,
)
from llm_rpg.core.assets.cache_key import build_asset_cache_key
from llm_rpg.storage.repositories import AssetRepository
from llm_rpg.assets.provider_factory import get_asset_provider
from llm_rpg.assets.interfaces import (
    AssetGenerationRequest as InternalRequest,
    AssetGenerationResult,
    AssetStatus,
    AssetType as InternalAssetType,
)

logger = logging.getLogger(__name__)


class AssetGenerationService:
    """Service for generating game assets with caching and error isolation.

    Never propagates asset generation errors to game logic.
    All provider failures return AssetResponse with generation_status=failed.
    """

    def __init__(self, repository: AssetRepository):
        self._repository = repository

    async def generate_asset(self, request: AssetGenerationRequest) -> AssetResponse:
        """Generate an asset or return cached result.

        Args:
            request: The asset generation request.

        Returns:
            AssetResponse with generation status. Never raises for provider failures.
        """
        # 1. Compute cache key
        cache_key = build_asset_cache_key(request)

        # 2. Check cache for ready asset
        cached = self._repository.get_ready_by_cache_key(cache_key)
        if cached is not None:
            return AssetResponse(
                asset_id=cached.asset_id,
                asset_type=AssetType(cached.asset_type),
                generation_status=AssetGenerationStatus(cached.status),
                result_url=cached.result_url,
                error_message=cached.error_message,
                provider=cached.provider_name,
                cache_hit=True,
                created_at=cached.created_at,
                metadata=cached.metadata_json or {},
            )

        # 3. Create asset record
        asset_id = str(uuid.uuid4())
        now = datetime.now()

        try:
            self._repository.create({
                "id": str(uuid.uuid4()),
                "asset_id": asset_id,
                "asset_type": request.asset_type.value,
                "status": AssetGenerationStatus.PROCESSING.value,
                "session_id": request.session_id,
                "world_id": request.world_id,
                "owner_entity_id": request.owner_entity_id,
                "owner_entity_type": request.owner_entity_type,
                "provider_name": request.provider or "mock",
                "request_params": {
                    "prompt": request.prompt,
                    "style": request.style,
                    "asset_type": request.asset_type.value,
                    **(request.metadata or {}),
                },
                "cache_key": cache_key,
                "created_at": now,
                "updated_at": now,
            })
        except IntegrityError:
            # Cache key collision — another request created the same asset concurrently
            # Re-query and return the existing one
            cached = self._repository.get_ready_by_cache_key(cache_key)
            if cached is not None:
                return AssetResponse(
                    asset_id=cached.asset_id,
                    asset_type=AssetType(cached.asset_type),
                    generation_status=AssetGenerationStatus(cached.status),
                    result_url=cached.result_url,
                    error_message=cached.error_message,
                    provider=cached.provider_name,
                    cache_hit=True,
                    created_at=cached.created_at,
                    metadata=cached.metadata_json or {},
                )
            # If no ready result exists, return a generic failed response
            return AssetResponse(
                asset_id=asset_id,
                asset_type=request.asset_type,
                generation_status=AssetGenerationStatus.FAILED,
                error_message="Concurrent creation conflict",
                provider=request.provider or "mock",
                cache_hit=False,
                created_at=now,
            )

        # 4. Call provider
        try:
            provider = get_asset_provider(request.provider)
            internal_request = InternalRequest(
                asset_type=InternalAssetType(request.asset_type.value),
                request_id=asset_id,
                session_id=request.session_id,
                game_context={"prompt": request.prompt, "style": request.style or ""},
                metadata=request.metadata or {},
            )
            result: AssetGenerationResult = await provider.generate(internal_request)

            if result.status == AssetStatus.COMPLETED:
                self._repository.update_status(
                    asset_id=asset_id,
                    status=AssetGenerationStatus.COMPLETED.value,
                    result_url=result.asset_url,
                )
                return AssetResponse(
                    asset_id=asset_id,
                    asset_type=request.asset_type,
                    generation_status=AssetGenerationStatus.COMPLETED,
                    result_url=result.asset_url,
                    provider=provider.provider_name,
                    cache_hit=False,
                    created_at=now,
                )
            else:
                error_msg = result.error_message or f"Provider returned status: {result.status.value}"
                self._repository.update_status(
                    asset_id=asset_id,
                    status=AssetGenerationStatus.FAILED.value,
                    error_message=error_msg,
                )
                return AssetResponse(
                    asset_id=asset_id,
                    asset_type=request.asset_type,
                    generation_status=AssetGenerationStatus.FAILED,
                    error_message=error_msg,
                    provider=provider.provider_name,
                    cache_hit=False,
                    created_at=now,
                )
        except Exception as e:
            error_msg = str(e) or "Unknown provider error"
            logger.warning(f"Asset generation failed for {asset_id}: {error_msg}")
            try:
                self._repository.update_status(
                    asset_id=asset_id,
                    status=AssetGenerationStatus.FAILED.value,
                    error_message=error_msg,
                )
            except Exception:
                pass  # Best-effort status update
            return AssetResponse(
                asset_id=asset_id,
                asset_type=request.asset_type,
                generation_status=AssetGenerationStatus.FAILED,
                error_message=error_msg,
                provider=request.provider or "mock",
                cache_hit=False,
                created_at=now,
            )

    def get_asset(self, asset_id: str) -> Optional[AssetResponse]:
        """Get an asset by its public ID.

        Args:
            asset_id: Public asset identifier.

        Returns:
            AssetResponse if found, None otherwise.
        """
        asset = self._repository.get_by_asset_id(asset_id)
        if asset is None:
            return None
        return AssetResponse(
            asset_id=asset.asset_id,
            asset_type=AssetType(asset.asset_type),
            generation_status=AssetGenerationStatus(asset.status),
            result_url=asset.result_url,
            error_message=asset.error_message,
            provider=asset.provider_name,
            cache_hit=False,
            created_at=asset.created_at,
            metadata=asset.metadata_json or {},
        )

    def list_session_assets(
        self,
        session_id: str,
        asset_type: Optional[str] = None,
    ) -> List[AssetResponse]:
        """List assets for a session.

        Args:
            session_id: Session ID.
            asset_type: Optional type filter.

        Returns:
            List of AssetResponse objects.
        """
        assets = self._repository.list_by_session(session_id, asset_type=asset_type)
        return [
            AssetResponse(
                asset_id=a.asset_id,
                asset_type=AssetType(a.asset_type),
                generation_status=AssetGenerationStatus(a.status),
                result_url=a.result_url,
                error_message=a.error_message,
                provider=a.provider_name,
                cache_hit=False,
                created_at=a.created_at,
                metadata=a.metadata_json or {},
            )
            for a in assets
        ]
