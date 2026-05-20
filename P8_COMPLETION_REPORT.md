# P8 Completion Report

**Date**: 2026-05-20
**Phase**: P8 Production Asset Runtime + Provider Integration

---

## Summary

P8 upgrades the P7 in-process async job runtime to a production-grade media asset system. It introduces a provider capability registry, real OpenAI DALL-E adapter with client abstraction, queue backend abstraction with lease/heartbeat/stale recovery, cost/usage tracking with DB persistence, per-user/per-session rate limiting, NPCPortrait richer integration with mood/context prompts, portrait pre-generation, admin audit read APIs phase 2, and debug/admin observability viewers for queue, cost, provider health, and rate limiting.

---

## Deliverables Table

| Task | Description | Status | Key Files | Test Count |
|------|-------------|--------|-----------|------------|
| T1 | Migration 015: asset_usage_logs, rate_limit_events, npc appearance | Complete | `alembic/versions/015_asset_runtime_production.py`, `storage/models.py`, `scripts/seed_content.py` | 0 (schema) |
| T2 | Provider capability registry | Complete | `assets/provider_registry.py` | ~15 |
| T3 | Provider error taxonomy | Complete | `assets/provider_errors.py` | 30 |
| T4 | AssetQueueBackend interface + in-process impl | Complete | `assets/queue.py` | 26 |
| T5 | Cost/usage model + repository | Complete | `storage/repositories.py` | 15 |
| T6 | Rate limit model + repository | Complete | `storage/repositories.py` | 11 |
| T7 | Mood/expression mapping + portrait context skeleton | Complete | `services/npc_portrait_prompt.py` | 20 |
| T8 | OpenAI DALL-E real adapter with client abstraction | Complete | `assets/openai_image.py` | ~20 |
| T9 | Audio provider shell | Complete | `assets/audio_provider.py` | ~10 |
| T10 | Lease/heartbeat/stale recovery/dead-letter | Complete | `storage/repositories.py`, `assets/jobs.py` | ~25 |
| T11 | Worker CLI | Complete | `scripts/asset_worker.py` | ~10 |
| T12 | Cost/usage service + API | Complete | `services/asset_usage_service.py`, `api/debug.py` | ~20 |
| T13 | Rate limit service + API | Complete | `services/asset_rate_limit.py` | ~15 |
| T14 | NPC portrait context builder (full) | Complete | `services/npc_portrait_prompt.py`, `api/media.py` | ~15 |
| T15 | Portrait pre-generation API | Complete | `api/media.py` | 8 |
| T16 | NPCPortrait frontend richer integration | Complete | `components/assets/NPCPortrait.tsx`, `game page` | 10 |
| T17 | AuditStore read APIs phase 2 | Complete | `api/admin_audit.py` | 21 |
| T18 | AssetQueueViewer debug component | Complete | `components/debug/AssetQueueViewer.tsx` | 14 |
| T19 | Usage/Provider/RateLimit viewers | Complete | `components/debug/AssetUsageViewer.tsx`, `ProviderHealthViewer.tsx`, `RateLimitViewer.tsx` | 28 |
| T20 | AssetJobService rate-limit integration | Complete | `services/asset_job_service.py`, `api/media.py` | 6 |
| T21 | P8 scenario tests | Complete | `tests/scenario/test_p8_asset_runtime.py` | 12 |
| T22 | Makefile + CI targets | Complete | `Makefile`, `.github/workflows/ci.yml` | 0 (infra) |
| T23 | P8 completion docs | Complete | This file + 4 others | 0 (docs) |

---

## Architecture Overview

### Provider Registry

**File**: `backend/llm_rpg/assets/provider_registry.py`

The `ProviderRegistry` wraps `provider_factory` (does not replace it). It provides:

- `list_providers()` returns capability metadata for each registered provider
- `get_available_provider(asset_type)` returns the first enabled and configured provider
- `check_provider_health(provider_name)` checks env var configuration (never calls real APIs)
- Auto-registers `mock` and `openai_image` on initialization

`ProviderCapability` is a Pydantic model with: provider_name, supported_asset_types, enabled, requires_api_key, configured, supports_async, supports_cancel, supports_cost_estimate.

### Queue Backend

**File**: `backend/llm_rpg/assets/queue.py`

`AssetQueueBackend` is a Protocol with: enqueue, dequeue, ack, nack, size, pending_count. Implementations:

- `InProcessAssetQueueBackend`: wraps AssetJobRepository for direct DB operations, includes SQLite-compatible claim (no FOR UPDATE SKIP LOCKED)
- `RQAssetQueueBackend`: NotImplementedError shell
- `CeleryAssetQueueBackend`: NotImplementedError shell

Factory `get_queue_backend()` reads `ASSET_QUEUE_BACKEND` env var (default "in_process").

### Cost Tracking

**File**: `backend/llm_rpg/services/asset_usage_service.py`

Records usage events on job creation (estimated cost) and completion (actual cost). Uses `AssetUsageLogRepository` with `AssetUsageLogModel` from migration 015. Supports:

- Per-session, per-user, per-provider cost queries
- `get_cost_summary()` returns aggregated totals (total_estimated, total_actual, count)
- Handles null cost values gracefully (treats as 0)

### Rate Limiting

**File**: `backend/llm_rpg/services/asset_rate_limit.py`

In-memory sliding window + DB event recording (no Redis dependency). Configuration via env vars:

- `ASSET_RATE_LIMIT_USER_PER_MINUTE` (default 10)
- `ASSET_RATE_LIMIT_SESSION_PER_MINUTE` (default 20)
- `ASSET_PROVIDER_CONCURRENCY_LIMIT` (default 3)

Integrated into `AssetJobService.submit()` before provider call. Returns 429 with structured error including limit_type, limit_value, and Retry-After header.

### NPC Portrait Context

**File**: `backend/llm_rpg/services/npc_portrait_prompt.py`

Rich portrait context builder that:

1. Fetches `SessionNPCStateModel` and derives mood via `_derive_mood()`
2. Fetches `NPCTemplateModel` for name, personality, appearance, role_type
3. Fetches `LocationModel` for location name and tags
4. Fetches recent `EventLogModel` entries for narration summary
5. Maps mood to `PortraitExpression` via explicit mapping
6. Builds DALL-E prompt with NPC name, mood, personality excerpt, location, narration

Handles missing data gracefully with defaults, never crashes.

### Worker CLI

**File**: `backend/llm_rpg/scripts/asset_worker.py`

In-process worker with CLI arguments: `--once`, `--loop`, `--batch-size`, `--poll-interval`, `--provider`, `--worker-id`, `--lease-seconds`. Supports graceful shutdown on SIGINT/SIGTERM, stale recovery before each claim, and structured JSON logging with no secrets.

---

## Test Results

### Wave 3 Verification (T15-T20)

| Suite | Tests | Status |
|-------|-------|--------|
| T15: Portrait prewarm API | 8 | PASS |
| T16: NPCPortrait frontend | 10 | PASS |
| T17: Admin audit API | 21 | PASS |
| T18: AssetQueueViewer | 14 | PASS |
| T19: Usage/Provider/RateLimit viewers | 28 | PASS |
| T20: Job rate limit integration | 6 | PASS |
| P7 regression | 44 | PASS |

### Wave 4 Verification (T21-T22)

| Suite | Tests | Status |
|-------|-------|--------|
| T21: P8 scenario tests | 12 | PASS |
| T22: Makefile targets | 0 (infra) | PASS |

### Wave 1-2 Unit/Integration Summary

| Suite | Tests | Status |
|-------|-------|--------|
| Provider errors (T3) | 30 | PASS |
| Queue backend (T4) | 26 | PASS |
| Usage repository (T5) | 15 | PASS |
| Rate limit repository (T6) | 11 | PASS |
| Portrait prompt (T7) | 20 | PASS |

### Scenario Tests (12 total)

1. `test_real_provider_disabled_falls_back_safely` - no key, no crash
2. `test_openai_provider_missing_key_fails_safely` - ProviderAuthError returned
3. `test_queue_lease_recovery` - expired lease recovers stale job
4. `test_dead_letter_after_max_retries` - exceeded attempts enter dead-letter
5. `test_rate_limit_blocks_excessive_requests` - 11th request returns 429
6. `test_cost_usage_recorded_for_completed_job` - actual_cost tracked
7. `test_cost_usage_recorded_for_failed_job` - failed jobs have usage events
8. `test_npc_portrait_uses_mood_context` - prompt contains NPC name/mood
9. `test_portrait_prewarm_is_cache_first` - cached NPC skipped
10. `test_audit_read_api_returns_session_logs` - paginated logs
11. `test_debug_usage_summary_aggregates_costs` - cost summary endpoint
12. `test_worker_does_not_leak_secrets` - no sk- patterns in output

### Frontend Tests

| Suite | Tests | Status |
|-------|-------|--------|
| NPCPortrait.p8.test.tsx | 10 | PASS |
| AssetQueueViewer.test.tsx | 14 | PASS |
| AssetUsageViewer.test.tsx | part of 28 | PASS |
| ProviderHealthViewer.test.tsx | part of 28 | PASS |
| RateLimitViewer.test.tsx | part of 28 | PASS |

---

## Known Limitations

### 1. Audio Provider is Shell Only

**Status**: `AudioAssetProvider` returns placeholder URLs, no real audio generation

**Impact**: BGM and SFX generation return stub data, not synthesized audio

**Mitigation**: Interface is complete and registered; real audio synthesis can be swapped in without API changes

**P9 Scope**: Real audio generation with music synthesis API

### 2. In-Process Queue Only

**Status**: `RQAssetQueueBackend` and `CeleryAssetQueueBackend` raise NotImplementedError

**Impact**: No horizontal scaling of workers; single-process only

**Mitigation**: Queue abstraction is complete; RQ/Celery adapters can be implemented without changing the interface

**P9 Scope**: Celery/RQ production queue with distributed workers

### 3. No Redis Rate Limiting

**Status**: Rate limiting uses in-memory sliding window + DB event recording

**Impact**: Rate limit state does not survive process restarts; not shared across processes

**Mitigation**: DB event recording provides audit trail; in-memory is sufficient for single-process deployments

**P9 Scope**: Redis-based rate limiting for multi-process deployments

### 4. OpenAI DALL-E Not Integration-Tested

**Status**: RealOpenAIClient exists but is never called in tests (FakeOpenAIClient used)

**Impact**: No proof that real DALL-E API integration works end-to-end

**Mitigation**: Client abstraction allows local testing with real key; CI uses FakeOpenAIClient

**P9 Scope**: Real DALL-E integration tests with recorded responses

### 5. Non-Debug Frontend Unit Tests Have Pre-existing Failures

**Status**: ~118 tests skipped (89/113 pre-existing failures)

**Cause**: React 19 production build + jsdom incompatibility

**Impact**: Debug and P8 asset tests pass; non-debug tests remain skipped

**Mitigation**: Tests explicitly marked with `it.skip()`; does not block P8

---

## Files Created/Modified

### Backend (New)

- `backend/alembic/versions/015_asset_runtime_production.py`
- `backend/llm_rpg/assets/provider_registry.py`
- `backend/llm_rpg/assets/provider_errors.py`
- `backend/llm_rpg/assets/queue.py`
- `backend/llm_rpg/assets/audio_provider.py`
- `backend/llm_rpg/services/asset_usage_service.py`
- `backend/llm_rpg/services/asset_rate_limit.py`
- `backend/llm_rpg/services/npc_portrait_prompt.py`
- `backend/llm_rpg/scripts/asset_worker.py`
- `backend/llm_rpg/api/admin_audit.py`
- `backend/tests/unit/test_asset_provider_registry_p8.py`
- `backend/tests/unit/test_openai_image_provider_p8.py`
- `backend/tests/unit/test_audio_provider_p8.py`
- `backend/tests/unit/test_provider_errors.py`
- `backend/tests/unit/test_asset_queue_backend.py`
- `backend/tests/unit/test_asset_usage_repository.py`
- `backend/tests/unit/test_asset_rate_limit_repository.py`
- `backend/tests/unit/test_asset_usage_service.py`
- `backend/tests/unit/test_asset_rate_limit.py`
- `backend/tests/unit/test_asset_job_lease.py`
- `backend/tests/unit/test_asset_worker_cli.py`
- `backend/tests/unit/test_npc_portrait_prompt.py`
- `backend/tests/unit/test_npc_portrait_prompt_p8.py`
- `backend/tests/integration/test_asset_usage_api.py`
- `backend/tests/integration/test_asset_rate_limit_api.py`
- `backend/tests/integration/test_admin_audit_api.py`
- `backend/tests/integration/test_portrait_prewarm_api.py`
- `backend/tests/integration/test_asset_job_rate_limit.py`
- `backend/tests/scenario/test_p8_asset_runtime.py`

### Backend (Modified)

- `backend/llm_rpg/storage/models.py` (AssetUsageLogModel, AssetRateLimitEventModel, NPCTemplateModel.appearance, AssetGenerationJobModel new columns)
- `backend/llm_rpg/storage/repositories.py` (AssetUsageLogRepository, AssetRateLimitEventRepository, claim_with_lease, heartbeat, recover_stale_jobs, mark_dead_letter, list_dead_lettered)
- `backend/llm_rpg/assets/openai_image.py` (RealOpenAIClient, FakeOpenAIClient, client abstraction)
- `backend/llm_rpg/assets/jobs.py` (lease/heartbeat integration, dead-letter handling)
- `backend/llm_rpg/services/asset_job_service.py` (rate limit integration)
- `backend/llm_rpg/api/media.py` (prewarm endpoints, portrait context integration, rate limit check)
- `backend/llm_rpg/api/debug.py` (usage/summary/providers/health/rate-limit-events endpoints, dead-lettered endpoint)
- `backend/llm_rpg/main.py` (admin_audit router mounting)
- `backend/llm_rpg/scripts/seed_content.py` (NPC appearance descriptions)

### Frontend (New)

- `frontend/components/debug/AssetQueueViewer.tsx`
- `frontend/components/debug/AssetUsageViewer.tsx`
- `frontend/components/debug/ProviderHealthViewer.tsx`
- `frontend/components/debug/RateLimitViewer.tsx`
- `frontend/__tests__/assets/NPCPortrait.p8.test.tsx`
- `frontend/__tests__/debug/AssetQueueViewer.test.tsx`
- `frontend/__tests__/debug/AssetUsageViewer.test.tsx`
- `frontend/__tests__/debug/ProviderHealthViewer.test.tsx`
- `frontend/__tests__/debug/RateLimitViewer.test.tsx`

### Frontend (Modified)

- `frontend/components/assets/NPCPortrait.tsx` (async job integration, image rendering, retry)
- `frontend/app/[locale]/game/[sessionId]/page.tsx` (sessionId prop for NPCPortrait)
- `frontend/app/[locale]/debug/page.tsx` (new viewer tabs)
- `frontend/lib/api.ts` (prewarm, provider capabilities, health functions)
- `frontend/types/api.ts` (usage, provider, rate limit types)

### Infrastructure

- `Makefile` (test-p8-fast, test-p8, sub-targets)
- `.github/workflows/ci.yml` (p8-tests job)

---

## Verification

```bash
# P8 fast gate
make test-p8-fast

# P8 full gate
make test-p8

# P7 regression check
make test-p7-fast

# Frontend static checks
cd frontend && npm run build && npm run lint && npx tsc --noEmit

# Frontend P8 asset tests
cd frontend && npm test -- __tests__/assets/NPCPortrait.p8.test.tsx

# P8 scenario tests
make test-scenario-p8
```

### P8 Closeout Fixes

Three closeout fixes applied after initial implementation review:

| Fix | Status | Description |
|-----|--------|-------------|
| F1: OpenAI provider env-safe behavior | ✅ | Production without OPENAI_API_KEY now returns structured FAILED result (no silent FakeOpenAIClient). Fake fallback only in testing or with `ASSET_OPENAI_FAKE_FALLBACK=true`. |
| F2: user_per_day rate limit | ✅ | `AssetRateLimiter` now enforces `user_per_day` (was defined but never checked). Blocked requests do not increment allowed quota. |
| F3: dynamic provider name resolution | ✅ | `_resolve_provider_name()` checks `ASSET_PROVIDER` env var + `ProviderRegistry` before falling back to "mock". 6 hardcoded `provider_name="mock"` replaced. |

### Final Verification Results

| Command | Result |
|---------|--------|
| `make test-p8-fast` | PASS |
| `make test-p8` | PASS (all P8 + scenario tests) |
| `make test-p7-fast` | PASS (no regression) |
| `cd frontend && npm run build` | PASS |
| `cd frontend && npm run lint` | PASS |
| `cd frontend && npx tsc --noEmit` | PASS |
| `make test-scenario-p8` | PASS (12/12) |
| CI (all 12 jobs) | PASS ✅ |
| P8 unit tests (`test_openai_image_provider_p8` + `test_asset_rate_limit` + etc.) | 144 passed |
| P8 frontend tests (`NPCPortrait.p8` + debug viewers) | 52 passed |

---

## P9 Candidates

The following items are deferred from P8 to future phases:

- **Celery/RQ production queue**: Distributed workers with RQ or Celery adapter implementation
- **Real audio generation**: Music synthesis API integration for BGM and SFX
- **SFX asset type support**: Sound effects beyond BGM
- **CDN/S3 asset deployment**: Production asset storage and delivery
- **Real DALL-E integration tests**: End-to-end testing with recorded OpenAI responses
- **Redis-based rate limiting**: Multi-process shared rate limit state
- **ForgetCurve background decay**: Automatic memory decay job (requires production queue)
- **Semantic leak detection**: Embedding-based leak detection
- **Full AuditStore persistence**: Context builds, validations beyond model_calls
- **Non-debug frontend unit test fixes**: React 19 + jsdom compatibility resolution
- **Engine refactoring**: ReplayEngine or Turn Orchestrator major rewrites

---

## References

- Learnings: `.sisyphus/notepads/p8-production-asset-runtime/learnings.md`
- Testing Strategy: `doc/testing_strategy.md`
- Plan: `.sisyphus/plans/p8-production-asset-runtime.md`
- P7 Completion: `P7_COMPLETION_REPORT.md`
- P7 Readiness: `P7_READINESS.md`
