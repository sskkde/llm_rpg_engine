# P6 Completion Report

**Date**: 2026-05-15
**Phase**: P6 Media Asset Infrastructure

---

## Summary

P6 delivers the Media API v1 infrastructure, replacing the 501 placeholder endpoints with functional asset generation, caching, and retrieval. This phase establishes the foundation for AI-generated game content while using mock providers for testing and development.

---

## Asset Model & Migration & Repository

### AssetModel

**File**: `backend/llm_rpg/models/assets.py`

**Key Design Decisions**:
- String IDs (UUID format), no foreign key constraints
- `cache_key` column with unique constraint for deduplication
- `index=True` on searchable columns (`session_id`, `asset_type`, `status`)

```python
class AssetModel(Base):
    __tablename__ = "assets"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    asset_type = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    session_id = Column(String, nullable=True, index=True)
    cache_key = Column(String, unique=True, nullable=True, index=True)
    prompt_text = Column(Text, nullable=True)
    result_url = Column(Text, nullable=True)
    result_metadata = Column(JSON, default=dict)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### Migration

**File**: `alembic/versions/013_add_assets.py`

- Creates `assets` table
- Adds indexes on `id`, `session_id`, `asset_type`, `status`, `cache_key`
- Unique constraint on `cache_key`

### Repository

**File**: `backend/llm_rpg/storage/repositories.py` (AssetRepository class)

**Methods**:
- `create(asset: AssetModel) -> AssetModel`
- `get_by_id(asset_id: str) -> AssetModel | None`
- `get_ready_by_cache_key(cache_key: str | None) -> AssetModel | None`
- `list_by_session(session_id: str) -> list[AssetModel]`
- `update_status(asset_id: str, status: str, **kwargs) -> AssetModel | None`

**Edge Case**: `get_ready_by_cache_key(None)` returns `None` early to avoid matching rows where `cache_key IS NULL`.

---

## Asset Schemas & Cache Key

### Pydantic Schemas

**File**: `backend/llm_rpg/models/assets.py`

- `AssetType` enum: `PORTRAIT`, `SCENE`, `BGM`
- `AssetGenerationStatus` enum: `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`
- `AssetGenerationRequest` - API request schema
- `AssetResponse` - API response schema
- `AssetReference` - Reference for caching

### Cache Key Resolver

**File**: `backend/llm_rpg/core/assets/cache_key.py`

```python
def build_asset_cache_key(
    asset_type: str,
    prompt_text: str,
    session_id: str | None = None,
    metadata: dict | None = None,
    session_scoped: bool = False
) -> str:
```

- Uses SHA-256 hex digest (64 chars)
- Canonical JSON serialization
- Excludes `session_id` by default; includes when `session_scoped=True`
- Empty metadata `{}` and missing metadata produce same key

---

## Provider Factory & Mock Providers

### Provider Factory

**File**: `backend/llm_rpg/assets/provider_factory.py`

```python
def get_asset_provider(provider_name: str | None = None) -> AssetProvider:
```

- Reads `ASSET_PROVIDER` environment variable
- Returns new instance per call (not singleton)
- Clear error message listing available providers

### Mock Providers

**Locations**:
- `MockAssetProvider`: `interfaces.py` (lines 126-188)
- `MockPortraitGenerator`: `portrait.py` (lines 138-242)
- `MockSceneGenerator`: `scene.py` (lines 147-251)
- `MockAudioGenerator`: `audio.py` (lines 195-320)

**Behavior**: Returns deterministic placeholder URLs and metadata based on input parameters.

---

## AssetGenerationService

**File**: `backend/llm_rpg/services/asset_generation_service.py` (235 lines)

### Methods

- `async generate_asset(request: AssetGenerationRequest) -> AssetResponse`
- `get_asset(asset_id: str) -> AssetResponse | None`
- `list_session_assets(session_id: str) -> list[AssetResponse]`

### Error Isolation Pattern

All provider failures return `AssetResponse(generation_status=FAILED)`:
- Never raises to caller
- Best-effort `update_status` in catch block
- Concurrent creation conflict handled via `IntegrityError`

### Cache Hit Logic

```python
try:
    asset = self.repo.create(new_asset)
except IntegrityError:
    # Cache key collision - return existing
    existing = self.repo.get_ready_by_cache_key(cache_key)
    if existing:
        return AssetResponse.from_orm(existing, cache_hit=True)
    return AssetResponse(generation_status=FAILED, error_message="Concurrent creation conflict")
```

### Test Coverage

13 unit tests covering:
- Happy path generation
- Cache hit scenario
- Provider failure handling
- IntegrityError recovery
- Status updates

---

## Media API v1

**File**: `backend/llm_rpg/api/media.py`

### Endpoints (No More 501s)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/media/portraits/generate` | POST | Generate NPC portrait |
| `/media/scenes/generate` | POST | Generate scene background |
| `/media/bgm/generate` | POST | Generate background music |
| `/media/assets/{asset_id}` | GET | Retrieve asset by ID |
| `/media/sessions/{session_id}/assets` | GET | List session assets |

### Auth

All endpoints require authentication via `Depends(get_current_active_user)`.

### Integration Tests

9 tests covering:
- Generation endpoints return 200 (not 501)
- Cache hit works
- Auth required (401 without token)
- Asset retrieval
- Session asset listing

---

## Frontend Asset Types & API Client

### Types

**File**: `frontend/types/api.ts`

- `AssetType` enum
- `AssetGenerationStatus` enum
- `AssetGenerationRequest` interface
- `AssetResponse` interface

### API Client

**File**: `frontend/lib/api.ts`

**Functions**:
- `generatePortrait(request: AssetGenerationRequest): Promise<AssetResponse>`
- `generateScene(request: AssetGenerationRequest): Promise<AssetResponse>`
- `generateBGM(request: AssetGenerationRequest): Promise<AssetResponse>`
- `getAsset(assetId: string): Promise<AssetResponse | null>`
- `listSessionAssets(sessionId: string): Promise<AssetResponse[]>`

**Test Coverage**: 6 unit tests

---

## Frontend Asset Display Components

### Components Created

| Component | File | Purpose |
|-----------|------|---------|
| `NPCPortrait` | `components/assets/NPCPortrait.tsx` | Display NPC portrait with emoji placeholder |
| `SceneBackground` | `components/assets/SceneBackground.tsx` | Display scene background with gradient placeholder |
| `BGMControl` | `components/assets/BGMControl.tsx` | BGM play/pause control |
| `AssetFallback` | `components/assets/AssetFallback.tsx` | Unified loading/error/empty state |

### i18n Keys

Added to `messages/en.json` and `messages/zh.json`:
- `assets.portrait.title`, `assets.portrait.loading`, `assets.portrait.error`
- `assets.scene.title`, `assets.scene.loading`, `assets.scene.error`
- `assets.bgm.title`, `assets.bgm.play`, `assets.bgm.pause`, `assets.bgm.error`

### Test Coverage

28 component tests covering:
- Loading, success, error states
- Placeholder rendering
- User interactions (play/pause)
- Accessibility

---

## Asset Debug/Admin Observability

### Debug Endpoints

**File**: `backend/llm_rpg/api/debug_assets.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/debug/assets/session/{session_id}` | GET | List assets for debug |
| `/debug/assets/{asset_id}` | GET | Get asset debug info |

### Frontend Debug Viewer

**Component**: `AssetDebugViewer`

**Features**:
- Asset list by session
- Status filtering
- Cache key inspection
- Error message display
- Debug tab in admin panel

**Test Coverage**: 10 tests

---

## P6 Makefile Targets & CI

### Makefile Targets

```makefile
test-p6-fast:
	cd backend && python3 -m pytest tests/unit/test_asset_*.py tests/unit/test_cache_key.py -q

test-p6:
	cd backend && python3 -m pytest tests/unit/test_asset_*.py tests/unit/test_cache_key.py tests/integration/test_media_api.py -q
```

### CI Job

Added `p6-tests` job to `.github/workflows/ci.yml`:
- Runs `make test-p6-fast`
- Depends on backend-tests job
- Non-blocking for P6 (will become blocking in P7)

---

## Test Results Summary

| Category | Count |
|----------|-------|
| Backend unit (cache_key) | 8 |
| Backend unit (repository) | 14 |
| Backend unit (service) | 13 |
| Backend unit (factory) | 6 |
| Backend integration (media API) | 9 |
| Backend integration (asset debug) | 12 |
| Frontend (api client) | 6 |
| Frontend (components) | 28 |
| Frontend (debug viewer) | 10 |
| **Total** | **106** |

---

## Deferred P7 Items

### Real External Provider Integration

**Scope**: DALL-E, Stable Diffusion, or similar for images; audio synthesis for BGM

**Blockers**: 
- API keys and cost management
- Rate limiting and queuing
- Async job infrastructure

---

### Async Job Infrastructure

**Scope**: Celery, RQ, or Temporal integration

**Requirements**:
- Background task queue
- Job status tracking
- Retry logic
- Dead letter queue

---

### Real Image/Audio Rendering

**Current State**: Mock providers return placeholder URLs

**Needed**:
- Image generation API integration
- Audio synthesis integration
- Storage (S3, CDN)
- CDN caching

---

### Full Game Page Integration

**Scope**: Integrate asset components into game session page

**Needed**:
- Wire NPCPortrait to NPC mentions
- Wire SceneBackground to location changes
- Wire BGMControl to scene transitions

---

### ForgetCurve Background Decay

**Scope**: Background job for NPC memory decay

**Deferred**: Requires async job infrastructure first

---

## Files Created/Modified

### Backend (New)
- `llm_rpg/models/assets.py`
- `llm_rpg/core/assets/cache_key.py`
- `llm_rpg/assets/provider_factory.py`
- `llm_rpg/services/asset_generation_service.py`
- `llm_rpg/api/debug_assets.py`
- `alembic/versions/013_add_assets.py`

### Backend (Modified)
- `llm_rpg/storage/repositories.py` (AssetRepository)
- `llm_rpg/api/media.py` (real implementations)
- `llm_rpg/assets/__init__.py` (exports)

### Frontend (New)
- `components/assets/NPCPortrait.tsx`
- `components/assets/SceneBackground.tsx`
- `components/assets/BGMControl.tsx`
- `components/assets/AssetFallback.tsx`
- `__tests__/assets/*.test.tsx`

### Frontend (Modified)
- `types/api.ts` (asset types)
- `lib/api.ts` (asset functions)
- `messages/en.json`, `messages/zh.json` (i18n)

### Infrastructure
- `Makefile` (p6 targets)
- `.github/workflows/ci.yml` (p6 job)

---

## Verification

```bash
# P6 fast gate
make test-p6-fast

# P6 full gate
make test-p6

# Frontend static checks
cd frontend && npm run build && npm run lint && npx tsc --noEmit

# Frontend asset tests
cd frontend && npm test -- __tests__/assets
```

---

## References

- Learnings: `.sisyphus/notepads/p5-closeout-p6-assets/learnings.md`
- Testing Strategy: `doc/testing_strategy.md`
- README.md: Media API v1 section
