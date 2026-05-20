# P8 Readiness

**Date**: 2026-05-20
**Purpose**: P9 Entry Criteria and Known Issues

---

## P9 Entry Criteria

Before entering P9, the following must be complete:

### Required Gates

| Gate | Command | Expected Result |
|------|---------|-----------------|
| P8 Fast Gate | `make test-p8-fast` | All tests pass |
| P7 Fast Gate | `make test-p7-fast` | All tests pass (no regression) |
| Frontend Static | `cd frontend && npm run build && npm run lint && npx tsc --noEmit` | All pass |
| No Unresolved P8 Blockers | Review open issues | Zero blockers |

### Test Verification

```bash
# Verify P8 gate
make test-p8-fast

# Verify P7 gate (prerequisite, no regression)
make test-p7-fast

# Verify frontend
cd frontend
npm run build
npm run lint
npx tsc --noEmit
npm test -- __tests__/assets/NPCPortrait.p8.test.tsx
```

---

## Required Gates

### Backend Gates

1. **test-p8-fast**: Provider + queue + cost/rate + admin audit + frontend assets
   - Command: `make test-p8-fast`
   - Expected: All pass
   - Tests: ~200+ unit + integration + frontend tests

2. **test-p7-fast**: P7 asset job infrastructure tests
   - Command: `make test-p7-fast`
   - Expected: All pass (no regression)
   - Tests: Asset job model, service, API, debug, frontend

3. **test-p8** (optional for P9 entry, recommended):
   - Command: `make test-p8`
   - Includes scenario tests (12 tests)

### Frontend Gates

1. **Build**: `npm run build` - Production build succeeds
2. **Lint**: `npm run lint` - No errors
3. **TypeScript**: `npx tsc --noEmit` - No type errors
4. **P8 Asset Tests**: `npm test -- __tests__/assets/NPCPortrait.p8.test.tsx` - All pass

---

## Must Have Verification

All "Must Have" items from P8 plan verified:

| Must Have | Verification Command | Status |
|-----------|---------------------|--------|
| Real provider adapter architecture (OpenAI DALL-E) | `grep -l "OpenAIImageProvider" backend/llm_rpg/assets/*.py` | Verified |
| All real providers default disabled in testing/local | `grep "enabled.*False" backend/llm_rpg/assets/provider_registry.py` | Verified |
| Queue backend abstraction + in-process backend | `grep "AssetQueueBackend" backend/llm_rpg/assets/queue.py` | Verified |
| Job lease/heartbeat/stale recovery/dead-letter | `grep "claim_next_pending_with_lease" backend/llm_rpg/storage/repositories.py` | Verified |
| Cost/usage tracking (DB + service + API) | `grep "AssetUsageLogRepository" backend/llm_rpg/storage/repositories.py` | Verified |
| Rate limiting (per-user/per-session/per-provider) | `grep "AssetRateLimiter" backend/llm_rpg/services/asset_rate_limit.py` | Verified |
| NPCPortrait mood/state/context in portrait prompt | `grep "build_portrait_prompt" backend/llm_rpg/services/npc_portrait_prompt.py` | Verified |
| Portrait pre-generation (cache-first) | `grep "prewarm_portraits" backend/llm_rpg/api/media.py` | Verified |
| P8 Makefile gates + CI job | `grep "test-p8" Makefile` | Verified |

---

## Must NOT Have Verification

All "Must NOT Have" items from P8 plan verified absent:

| Must NOT Have | Verification Command | Status |
|---------------|---------------------|--------|
| Celery/RQ/Temporal production deployment | `grep -r "Celery\|RQ\|Temporal" backend/llm_rpg/assets/queue.py \| grep -v "NotImplementedError"` | Absent (only shells) |
| CDN/S3 formal deployment | `grep -r "s3\|cdn\|cloudfront" backend/llm_rpg/assets/` | Absent |
| Real audio generation | `grep -r "synthesis\|generate_audio" backend/llm_rpg/assets/audio_provider.py \| grep -v "placeholder"` | Absent |
| E2E browser tests as required CI | `grep "e2e.*required" .github/workflows/ci.yml` | Absent |
| Fixes for 89 pre-existing frontend test failures | `grep -r "it.skip.*// P8" frontend/__tests__/` | Absent (not addressed) |
| ReplayEngine or Turn Orchestrator rewrites | `git diff HEAD~50 -- backend/llm_rpg/core/replay_engine.py backend/llm_rpg/engines/turn_orchestrator.py` | Absent (no changes) |
| Semantic leak detection | `grep -r "embedding.*leak\|semantic.*leak" backend/llm_rpg/` | Absent |
| SFX asset type support | `grep -r "sfx.*generation" backend/llm_rpg/api/media.py` | Absent |
| Game page layout redesign | `grep "grid-cols" frontend/app/\[locale\]/game/\[sessionId\]/page.tsx` | Absent (no layout changes) |
| API key exposure in logs/API/debug UI | `grep -r "sk-" backend/tests/ \| grep -v "placeholder\|mock\|fake"` | Absent |
| Real external API calls in CI | `grep "openai.com" .github/workflows/ci.yml` | Absent |
| Breaking changes to AssetProvider interface | `grep "def generate" backend/llm_rpg/assets/interfaces.py` | No signature changes |
| NPCTemplateModel portrait_asset_id FK | `grep "portrait_asset_id" backend/llm_rpg/storage/models.py` | Absent |

---

## Known Issues

### 1. Audio Provider is Shell Only

**Status**: `AudioAssetProvider` returns placeholder URLs

**Impact**: No real audio generation; BGM/SFX endpoints return stub data

**Mitigation**: Interface complete; can swap real provider without API changes

**P9 Scope**: Real audio synthesis integration

---

### 2. In-Process Queue Only

**Status**: RQ and Celery backends raise NotImplementedError

**Impact**: No horizontal worker scaling; single-process deployment only

**Mitigation**: Queue abstraction complete; RQ/Celery adapters can be implemented

**P9 Scope**: Celery/RQ production deployment

---

### 3. No Redis Rate Limiting

**Status**: Rate limiting uses in-memory sliding window + DB events

**Impact**: Rate limit state lost on process restart; not shared across processes

**Mitigation**: DB events provide audit; in-memory sufficient for single-process

**P9 Scope**: Redis-based distributed rate limiting

---

### 4. Real DALL-E Not Integration-Tested

**Status**: All tests use FakeOpenAIClient; RealOpenAIClient never called in CI

**Impact**: No end-to-end proof of real DALL-E integration

**Mitigation**: Client abstraction allows manual testing with real key

**P9 Scope**: Real DALL-E integration tests with recorded responses

---

### 5. Non-Debug Frontend Unit Tests Have Pre-existing Failures

**Status**: ~118 tests skipped (89/113 pre-existing failures from P3-QG)

**Cause**: React 19 production build + jsdom incompatibility

**Impact**: Debug and P8 asset tests pass; non-debug tests remain skipped

**Mitigation**: Tests explicitly marked with `it.skip()`; does not block P8

**P9+ Scope**: Investigate React 19 + jsdom compatibility

---

### 6. ForgetCurve Background Decay Deferred

**Status**: NPC memory decay logic exists but no background job

**Impact**: Memory does not decay automatically

**Mitigation**: Decay can be triggered manually via admin API

**P9+ Scope**: Background decay job (requires production queue)

---

## P8 Deliverables Summary

| Deliverable | Status |
|-------------|--------|
| Migration 015 (asset_usage_logs, rate_limit_events, npc appearance) | Complete |
| ProviderCapability + ProviderRegistry | Complete |
| ProviderError taxonomy (5 error types) | Complete |
| AssetQueueBackend Protocol + InProcessAssetQueueBackend | Complete |
| AssetUsageLogRepository + AssetRateLimitEventRepository | Complete |
| AssetUsageService + AssetRateLimiter | Complete |
| NPC portrait prompt builder with mood/context | Complete |
| OpenAI DALL-E adapter with client abstraction | Complete |
| Audio provider shell | Complete |
| Lease/heartbeat/stale recovery/dead-letter | Complete |
| Worker CLI (--once/--loop/--batch-size) | Complete |
| Portrait pre-generation API | Complete |
| NPCPortrait frontend richer integration | Complete |
| AuditStore read APIs phase 2 | Complete |
| AssetQueueViewer debug component | Complete |
| AssetUsageViewer/ProviderHealthViewer/RateLimitViewer | Complete |
| P8 Makefile targets + CI p8-tests job | Complete |
| P8 scenario tests (12 tests) | Complete |
| P8_COMPLETION_REPORT.md | Complete |
| P8_READINESS.md | Complete |

---

## Deferred to P9+

- **Celery/RQ production queue**: Distributed workers with real task queue
- **Real audio generation**: Music synthesis API for BGM and SFX
- **SFX asset type support**: Sound effects beyond BGM
- **CDN/S3 asset deployment**: Production storage and delivery
- **Real DALL-E integration tests**: End-to-end with recorded responses
- **Redis-based rate limiting**: Multi-process shared state
- **ForgetCurve background decay**: Automatic memory decay job
- **Semantic leak detection**: Embedding-based leak detection
- **Full AuditStore persistence**: Context builds, validations
- **Non-debug frontend unit test fixes**: React 19 + jsdom compatibility
- **Engine refactoring**: ReplayEngine or Turn Orchestrator rewrites

---

## P9 Scope Preview

P9 will focus on:

1. **Production Queue Infrastructure**
   - Celery or RQ adapter implementation
   - Worker process deployment
   - Dead letter queue handling
   - Job monitoring dashboard

2. **Real Audio Generation**
   - Music synthesis API integration
   - BGM generation with mood/tempo
   - SFX asset type support

3. **CDN/S3 Deployment**
   - Asset upload to cloud storage
   - CDN delivery for images/audio
   - Signed URL generation

4. **Redis-Based Rate Limiting**
   - Distributed rate limit state
   - Multi-process support
   - Sliding window with Redis

---

## Verification Checklist

Before declaring P8 complete:

- [x] `make test-p8-fast` passes
- [x] `make test-p7-fast` passes (no regression)
- [x] `cd frontend && npm run build` passes
- [x] `cd frontend && npm run lint` passes
- [x] `cd frontend && npx tsc --noEmit` passes
- [x] `cd frontend && npm test -- __tests__/assets/NPCPortrait.p8.test.tsx` passes
- [x] `make test-scenario-p8` passes (12/12)
- [x] P8_COMPLETION_REPORT.md exists
- [x] P8_READINESS.md exists
- [x] README.md updated with P8 section
- [x] IMPLEMENTATION_STATUS.md updated with P8 deliverables
- [x] doc/testing_strategy.md updated with P8 gates
- [x] All "Must Have" items verified
- [x] All "Must NOT Have" items verified absent

---

## References

- P8 Completion Report: `P8_COMPLETION_REPORT.md`
- Testing Strategy: `doc/testing_strategy.md`
- Learnings: `.sisyphus/notepads/p8-production-asset-runtime/learnings.md`
- Plan: `.sisyphus/plans/p8-production-asset-runtime.md`
