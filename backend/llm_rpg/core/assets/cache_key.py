"""Cache key resolver for asset generation.

Builds deterministic cache keys from asset generation requests
to enable result caching and deduplication.
"""

import hashlib
import json
from typing import Any, Dict

from llm_rpg.models.assets import AssetGenerationRequest


def _canonical_json(obj: Any) -> str:
    """Serialize object to canonical JSON (sorted keys, no whitespace).
    
    Ensures the same semantic content always produces the same string.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def build_asset_cache_key(
    request: AssetGenerationRequest,
    *,
    session_scoped: bool = False,
) -> str:
    """Build a deterministic cache key for an asset generation request.
    
    The key is based on the semantic content of the request:
    - asset_type, prompt, style, provider
    - Optionally session_id (for session-scoped caching)
    
    Args:
        request: The asset generation request
        session_scoped: If True, include session_id in the key
        
    Returns:
        A SHA-256 hex digest string that uniquely identifies this request.
    """
    key_parts: Dict[str, Any] = {
        "asset_type": request.asset_type.value,
        "prompt": request.prompt,
    }
    
    if request.style:
        key_parts["style"] = request.style
    
    if request.provider:
        key_parts["provider"] = request.provider
    
    if request.metadata:
        key_parts["metadata"] = request.metadata
    
    if session_scoped and request.session_id:
        key_parts["session_id"] = request.session_id
    
    canonical = _canonical_json(key_parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
