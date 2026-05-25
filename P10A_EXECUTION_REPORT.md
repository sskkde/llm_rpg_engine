# P10-A Immersion & Provider Routing — Execution Report

**Date**: 2026-05-23
**Phase**: P10-A Immersion & Provider Routing
**Predecessor**: V1.0 Release Readiness (P9)

---

## Summary

P10-A delivers four experience/architecture modules: SSE stage progress events during turn execution, minute-precision dynamic world time, quest journal anti-spoiler gating, and per-asset-type provider routing. All implemented without breaking V1.0 release gate.

---

## Scope & Deliverables

| Module | Deliverables | Tasks | Status |
|--------|--------------|-------|--------|
| Turn Stage Feedback | TurnProgressEvent model + emit_stage helper, SSE Queue+Thread bridge, stage_started/stage_completed events, TurnStageStatus frontend component | T2, T8, T13 | Complete |
| Dynamic World Time | WorldTime hour/minute extension, TimeAdvanceProposal + Validator, _advance_world_time rewrite, intent-to-time_category mapping, WorldTickProposal elapsed_minutes extension | T3, T9, T11, T14, T15 | Complete |
| Quest Anti-Spoiler Gating | Migration 016 (visibility columns), QuestJournalService, Player API visibility filtering, frontend toast notification | T1, T4, T7, T10 | Complete |
| Per-Asset-Type Provider Routing | Provider resolver with env var fallback chain, media.py integration, debug endpoint, env var documentation | T5, T12, T16 | Complete |

**Total Tasks**: 18 (T1-T16 + T17-T18)
**Completed**: 18/18

---

## Module 1: Turn Stage Feedback

### Overview

Implements SSE progress events during turn execution, replacing static "故事展开中" loading state with dynamic stage updates.

### Deliverables

| Task | Description | Status | Key Files |
|------|-------------|--------|-----------|
| T2 | TurnProgressEvent model + emit_stage helper | Complete | `backend/llm_rpg/core/turn_progress.py` |
| T8 | SSE Queue+Thread bridge + stage events | Complete | `backend/llm_rpg/api/streaming.py`, `backend/llm_rpg/core/turn_service.py` |
| T13 | TurnStageStatus frontend component | Complete | `frontend/components/game/TurnStageStatus.tsx`, `frontend/hooks/useTurnStream.tsx` |

### Architecture Details

#### TurnProgressEvent

**File**: `backend/llm_rpg/core/turn_progress.py`

Defines 8 stages with Chinese labels:

| Stage | Label |
|-------|-------|
| input_intent | 解析玩家意图…… |
| action_resolving | 执行玩家行动…… |
| world_stage | 世界演进中…… |
| scene_stage | 场景变化中…… |
| npc_stage | NPC 思考中…… |
| validation | 规则校验中…… |
| committing | 提交状态变更…… |
| narration | 生成叙事文本…… |

#### SSE Bridge Pattern

**Queue + Thread pattern** (not async refactor):
- `asyncio.Queue[TurnProgressEvent | object]` with sentinel termination
- Thread runs `execute_turn_service()`, puts progress events to queue
- Async generator yields `format_sse("stage_started"/"stage_completed")` events
- Backward compatible: `progress_callback=None` (REST endpoint) produces identical behavior

#### Frontend Integration

- `TurnStageStatus.tsx` displays current stage label
- `useTurnStream.tsx` handles `stage_started`/`stage_completed` events
- Actor names displayed when available (e.g., "凌月正在思考……")

---

## Module 2: Dynamic World Time

### Overview

Extends WorldTime model with minute precision, implements time advance validation, and rewrites `_advance_world_time()` for variable minute advancement based on action type.

### Deliverables

| Task | Description | Status | Key Files |
|------|-------------|--------|-----------|
| T3 | WorldTime hour/minute/total_minutes/display_text extension | Complete | `backend/llm_rpg/models/events.py` |
| T9 | TimeAdvanceProposal + TimeAdvanceValidator | Complete | `backend/llm_rpg/core/time_advance.py`, `backend/llm_rpg/core/time_advance_validator.py` |
| T11 | _advance_world_time rewrite + intent→time_category mapping | Complete | `backend/llm_rpg/core/turn_service.py` |
| T14 | WorldTickProposal elapsed_minutes extension | Complete | `backend/llm_rpg/models/proposals.py` |
| T15 | Turn service integration — progress_callback + time advance | Complete | `backend/llm_rpg/core/turn_service.py` |

### Architecture Details

#### WorldTime Extension

**File**: `backend/llm_rpg/models/events.py`

New fields:
- `hour: int` (0-23)
- `minute: int` (0-59)
- `total_minutes: int` — from day 0:00
- `display_text: str | None` — formatted display

Methods:
- `derive_period(hour)` → period name (hour=8 → "辰时")
- `from_period(period)` → hour (period="辰时" → 8)

Dual-track: hour/minute are internal, period is derived automatically.

#### TimeAdvanceValidator

**File**: `backend/llm_rpg/core/time_advance_validator.py`

Per-category minute ranges:

| Category | Min | Max | Default |
|----------|-----|-----|---------|
| inspect | 1 | 5 | 3 |
| short_dialogue | 3 | 15 | 8 |
| long_dialogue | 10 | 45 | 25 |
| nearby_movement | 5 | 30 | 15 |
| far_movement | 30 | 180 | 90 |
| combat | 1 | 10 | 5 |
| rest | 30 | 480 | 120 |
| wait | 1 | 1440 | 60 |
| unknown | 5 | 15 | 10 |

#### Intent to Time Category Mapping

16 intent types mapped to 9 time categories:

| Intent | Category |
|--------|----------|
| move | nearby_movement |
| inspect | inspect |
| talk | short_dialogue |
| ask | short_dialogue |
| attack | combat |
| defend | combat |
| cast_skill | combat |
| use_item | inspect |
| take_item | inspect |
| give_item | short_dialogue |
| persuade | long_dialogue |
| hide | inspect |
| follow | nearby_movement |
| wait | wait |
| trigger_object | inspect |
| quest_progress | short_dialogue |

#### Time Resolution Flow

1. **Step 11**: Resolve elapsed_minutes from action_type + input_intent
2. **Step 15b**: After LLM stages, re-resolve with world_stage_result if available
3. Validate with TimeAdvanceValidator (clamp out-of-range)
4. Apply via `_advance_world_time(world_time, elapsed_minutes=...)`

---

## Module 3: Quest Anti-Spoiler Gating

### Overview

Implements quest visibility gating to prevent spoilers. Hidden quests are not returned by Player API until discovered through gameplay.

### Deliverables

| Task | Description | Status | Key Files |
|------|-------------|--------|-----------|
| T1 | Migration 016 quest journal visibility | Complete | `backend/alembic/versions/016_quest_journal_visibility.py` |
| T4 | QuestJournalService core | Complete | `backend/llm_rpg/services/quest_journal_service.py` |
| T7 | Player quest API visibility filtering | Complete | `backend/llm_rpg/api/player_quests.py` |
| T10 | Quest journal frontend toast notification | Complete | `frontend/components/game/QuestJournalPanel.tsx` |

### Architecture Details

#### Migration 016

**File**: `backend/alembic/versions/016_quest_journal_visibility.py`

Added columns to `session_quest_states`:
- `player_visibility` (String(20), default "hidden")
- `revealed_at` (DateTime, nullable)
- `reveal_source_event_id` (String, nullable)
- `last_revealed_step_no` (Integer, nullable)

Data migration: existing active/completed quests auto-promoted to `player_visibility='discovered'`

#### QuestJournalService

**File**: `backend/llm_rpg/services/quest_journal_service.py`

Methods:
- `reveal_quest()` — Set visibility to "discovered"
- `reveal_objective()` — Update last_revealed_step_no
- `list_visible_quests()` — Filter by visibility != "hidden"
- `get_visible_quest_detail()` — Return quest if visible
- `hide_quest()` — Admin/debug only

Key behaviors:
- Idempotent: reveal_quest returns existing state if already discovered
- Auto-promote: Completed/failed quests auto-promote to discovered
- Deterministic: No LLM calls

#### Player API Filtering

**File**: `backend/llm_rpg/api/player_quests.py`

- `list_quests()`: Filters out `player_visibility='hidden'`
- `get_quest_detail()`: Returns 404 for hidden quests (not 403 — prevents info leak)

---

## Module 4: Per-Asset-Type Provider Routing

### Overview

Implements per-asset-type provider resolution with env var fallback chain, replacing simplistic single-provider routing.

### Deliverables

| Task | Description | Status | Key Files |
|------|-------------|--------|-----------|
| T5 | Provider resolver with env var fallback chain | Complete | `backend/llm_rpg/assets/provider_resolver.py` |
| T12 | Media API + debug endpoint integration | Complete | `backend/llm_rpg/api/media.py`, `backend/llm_rpg/api/debug.py` |
| T16 | Provider resolver env var documentation | Complete | `backend/.env.example`, `backend/.env.production.example` |

### Architecture Details

#### Provider Resolver

**File**: `backend/llm_rpg/assets/provider_resolver.py`

`resolve_asset_provider_name(asset_type: AssetType) -> str`

Fallback chain for PORTRAIT:
```
ASSET_PROVIDER_PORTRAIT → ASSET_PROVIDER_IMAGE → ASSET_PROVIDER_DEFAULT → "mock"
```

Fallback chain for BGM:
```
ASSET_PROVIDER_BGM → ASSET_PROVIDER_AUDIO → ASSET_PROVIDER_DEFAULT → "mock"
```

Same pattern for SCENE and SFX.

#### Debug Endpoint

**File**: `backend/llm_rpg/api/debug.py`

`GET /debug/assets/providers/resolved` — Admin-only endpoint returning:
- Resolved provider for each asset type
- All relevant env var values
- Default provider

#### New Environment Variables

| Variable | Purpose |
|----------|---------|
| ASSET_PROVIDER_DEFAULT | Global fallback |
| ASSET_PROVIDER_IMAGE | Image category (portrait, scene) |
| ASSET_PROVIDER_PORTRAIT | Portrait-specific override |
| ASSET_PROVIDER_SCENE | Scene-specific override |
| ASSET_PROVIDER_AUDIO | Audio category (bgm, sfx) |
| ASSET_PROVIDER_BGM | BGM-specific override |
| ASSET_PROVIDER_SFX | SFX-specific override |
| TIME_ADVANCE_LLM_MODE | "reuse" (P10-A default); "explicit" not yet implemented (P10-B) |

---

## Test Results

### Backend Tests

| Suite | Tests | Status |
|-------|-------|--------|
| Full backend | 3177 collected | All pass |
| V1 Release Gate | — | PASS |
| P10-A Integration | — | PASS |

### P10-A Integration Test Files

| File | Tests |
|------|-------|
| `tests/integration/test_streaming_stage_events.py` | Stage event emission |
| `tests/integration/test_dynamic_world_time.py` | Minute-precision time |
| `tests/integration/test_quest_visibility_api.py` | Quest gating |
| `tests/integration/test_media_provider_routing.py` | Provider resolution |

### Frontend Tests

| Suite | Command | Status |
|-------|---------|--------|
| Build | `npm run build` | PASS |
| Lint | `npm run lint` | PASS |
| TypeScript | `npx tsc --noEmit` | PASS |

---

## Key Metrics

- **8 SSE stage events**: stage_started + stage_completed for 4 core stages
- **16 intent-to-time_category mappings**: Complete coverage of all action types
- **4 new DB columns**: player_visibility, revealed_at, reveal_source_event_id, last_revealed_step_no
- **7 new env vars**: ASSET_PROVIDER_* per-type vars + TIME_ADVANCE_LLM_MODE
- **3177 backend tests**: All pass

---

## Known Limitations

### 1. No Real External Providers

**Status**: All asset generation uses mock/placeholder providers

**Impact**: Portrait and scene generation return placeholder URLs, no real DALL-E/Stable Diffusion integration

**Mitigation**: Provider interface complete; real providers can be swapped in without API changes

### 2. TIME_ADVANCE_LLM_MODE=explicit Not Implemented

**Status**: Config defined but LLM call not implemented; P10-A uses deterministic action-category defaults plus optional world-stage LLM reuse only

**Impact**: Time advance always uses "reuse" mode (extracts from world stage output); explicit dedicated LLM time-advance calls are deferred to P10-B

**Mitigation**: Deterministic fallbacks provide reasonable defaults; explicit mode can be added later

### 3. SFX Provider Deferred

**Status**: `ASSET_PROVIDER_SFX` env var defined but no SFX asset type in production

**Impact**: Sound effects generation returns placeholder

**Mitigation**: Interface ready for future implementation

---

## Files Modified/Created

### Backend (New Files)

- `backend/llm_rpg/core/turn_progress.py`
- `backend/llm_rpg/core/time_advance.py`
- `backend/llm_rpg/core/time_advance_validator.py`
- `backend/llm_rpg/services/quest_journal_service.py`
- `backend/llm_rpg/assets/provider_resolver.py`
- `backend/alembic/versions/016_quest_journal_visibility.py`
- `backend/tests/unit/test_quest_journal_service.py`
- `backend/tests/unit/test_time_advance_validator.py`
- `backend/tests/unit/test_asset_provider_resolver.py`
- `backend/tests/integration/test_streaming_stage_events.py`
- `backend/tests/integration/test_dynamic_world_time.py`
- `backend/tests/integration/test_quest_visibility_api.py`
- `backend/tests/integration/test_media_provider_routing.py`

### Backend (Modified Files)

- `backend/llm_rpg/models/events.py` — WorldTime extension
- `backend/llm_rpg/models/proposals.py` — WorldTickProposal extension
- `backend/llm_rpg/storage/models.py` — SessionQuestStateModel columns
- `backend/llm_rpg/core/turn_service.py` — progress_callback, time advance integration
- `backend/llm_rpg/api/streaming.py` — SSE bridge, stage events
- `backend/llm_rpg/api/game.py` — time_advance_result in response
- `backend/llm_rpg/api/player_quests.py` — visibility filtering
- `backend/llm_rpg/api/media.py` — provider resolver integration
- `backend/llm_rpg/api/debug.py` — resolved providers endpoint
- `backend/.env.example` — provider env vars
- `backend/.env.production.example` — provider env vars
- `Makefile` — test-p10a-fast, test-p10a targets
- `.github/workflows/ci.yml` — p10a-tests job

### Frontend (New Files)

- `frontend/components/game/TurnStageStatus.tsx`

### Frontend (Modified Files)

- `frontend/types/api.ts` — TurnStageState, stage event types
- `frontend/hooks/useTurnStream.tsx` — stage event handling
- `frontend/components/game/QuestJournalPanel.tsx` — toast notification
- `frontend/app/[locale]/game/[sessionId]/page.tsx` — TurnStageStatus integration

---

## References

- Plan: `.sisyphus/plans/p10a-immersion-provider-routing.md`
- Learnings: `.sisyphus/notepads/p10a-immersion-provider-routing/learnings.md`
- V1 Completion: `V1_COMPLETION_REPORT.md`
- V1 Readiness: `V1_READINESS.md`
- CI Workflow: `.github/workflows/ci.yml`

---

*End of P10-A Execution Report*
