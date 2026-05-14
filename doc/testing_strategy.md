# Testing Strategy

This document describes the comprehensive test pyramid, quality gates, and coverage requirements for the LLM RPG Engine.

---

## Test Pyramid Overview

The project follows a layered test pyramid with increasing scope and decreasing speed at each tier:

```
                    ┌─────────────┐
                    │   CI/CD     │  ← Pipeline orchestration
                    │  Pipeline   │
                    └─────────────┘
                          │
            ┌─────────────┼─────────────┐
            │   Smoke     │  pgvector   │  ← Specialized tiers
            │   Tests     │   Tests     │
            └─────────────┴─────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │   Scenario      │   Frontend      │  ← Integration tier
        │   Tests         │   Tests         │
        └─────────────────┴─────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │   Integration   │   Frontend      │  ← API/UI tier
        │   Tests         │   Unit Tests    │
        └─────────────────┴─────────────────┘
                          │
              ┌───────────┴───────────┐
              │      Unit Tests       │  ← Foundation
              └───────────────────────┘
```

**Principles**:
- Fast tests at the bottom, slow tests at the top
- Higher coverage at lower tiers
- Each tier has a specific purpose and CI behavior
- Quality gates combine multiple tiers

---

## Test Tiers Table

| Tier | Location | Command | CI Behavior | Description |
|------|----------|---------|-------------|-------------|
| **Unit** | `backend/tests/unit/` | `pytest tests/unit/ -q` | Blocking | Isolated component tests with mocks |
| **Integration** | `backend/tests/integration/` | `pytest tests/integration/ -q` | Blocking | API and database integration tests |
| **Scenario** | `backend/tests/scenario/` | See below | See below | End-to-end game scenarios |
| **Frontend Unit** | `frontend/__tests__/` | `npm test` | Partial blocking | React component tests |
| **Smoke** | `pytest -m smoke` | `make test-scenario-smoke` | Blocking | Fast core scenario validation |
| **pgvector** | `pytest -m pgvector` | `make test-pgvector` | Non-blocking | PostgreSQL vector search tests |
| **CI Pipeline** | `.github/workflows/` | `make test-p3/p4/p5` | Blocking | Quality gate orchestration |

### Scenario Test Strengths

Scenario tests run at three strength levels:

| Strength | Command | Description | DB Required |
|----------|---------|-------------|-------------|
| **Smoke** | `make test-scenario-smoke` | 8 core tests, fast validation | No (SQLite) |
| **Integration** | `pytest tests/scenario/ -m integration` | Full pipeline tests | Optional |
| **Full** | `pytest tests/scenario/` | All scenarios, most comprehensive | Optional |

---

## P5 Gate Commands

### Fast Gate (Development)

```bash
make test-p5-fast
```

Runs the debug contract verification:
- Backend debug endpoint tests
- Frontend debug component tests
- TypeScript compilation (`tsc --noEmit`)
- P5 scenario tests
- Prompt Inspector tests

### Full Gate (Pre-merge)

```bash
make test-p5
```

Runs the complete P5 quality gate:
- All P4 tests (`make test-p4`)
- P5 scenario tests (`make test-scenario-p5`)
- Replay report tests (`make test-replay-report`)
- Prompt Inspector tests (`make test-prompt-inspector`)

---

## P6 Gate Commands (Future)

P6 will introduce asset generation infrastructure. The following targets are planned:

| Target | Description |
|--------|-------------|
| `test-p6-fast` | Debug contract + scenario-p6 + asset-pipeline |
| `test-p6` | Full P6 gate (p5 + scenario-p6 + asset tests) |

These targets will be added in P6 when media generation endpoints are implemented.

---

## Mock Provider Principles

### MockLLMProvider

The `MockLLMProvider` is used when `OPENAI_API_KEY` is not set or `APP_ENV=testing`:

```python
from llm_rpg.llm import LLMService

# Automatic mock selection in testing
service = LLMService()  # Uses mock when OPENAI_API_KEY not set

# Explicit mock for specific tests
service = LLMService(use_mock=True)
```

**Behavior**:
- Returns predictable responses based on prompt content patterns
- "narration" or "describe" → narrative text
- "npc" or "decision" → JSON action
- "intent" or "parse" → JSON intent

### MockAssetProvider (P6)

Will be used for P6 asset generation tests:
- Portrait generation → placeholder image
- Scene generation → placeholder scene
- BGM generation → placeholder audio

### Core Principles

1. **No real external API calls in tests** — All tests must pass without OpenAI API key
2. **Tests must pass without PostgreSQL** — Default path uses SQLite in-memory
3. **Tests must pass without Redis** — Redis is optional for caching
4. **Deterministic by default** — Same seed produces same results

---

## External Service Unavailable Handling

### Backend Fallback

The backend gracefully handles missing external services:

| Service | Missing Behavior |
|---------|------------------|
| OpenAI API | Falls back to `MockLLMProvider` |
| PostgreSQL | Tests use SQLite in-memory |
| Redis | Caching disabled, no error |

### Test Environment

```bash
# Tests automatically set APP_ENV=testing
APP_ENV=testing pytest -q

# Or rely on pytest.ini configuration
pytest -q  # Uses testing environment by default
```

### CI Environment

CI sets `APP_ENV=testing` and `OPENAI_API_KEY=""` to ensure mock providers are used.

---

## Coverage Requirements

### Debug Endpoints (P5)

All 14+ debug endpoints must have test coverage:

| Endpoint | Test File | Coverage |
|----------|-----------|----------|
| `GET /debug/sessions/{id}/logs` | `test_debug_observability.py` | Session logs |
| `GET /debug/sessions/{id}/state` | `test_debug_observability.py` | State snapshot |
| `GET /debug/model-calls` | `test_debug_observability.py` | LLM audit |
| `GET /debug/errors` | `test_debug_observability.py` | Error log |
| `POST /debug/sessions/{id}/replay` | `test_audit_replay.py` | Replay |
| `POST /debug/sessions/{id}/snapshots` | `test_replay_snapshot_invariants.py` | Snapshots |
| `GET /debug/sessions/{id}/prompt-inspector` | `test_prompt_inspector_api.py` | Aggregation |
| `GET /debug/sessions/{id}/turns/{turn_no}` | `test_prompt_inspector_api.py` | Turn details |

### Replay System

| Requirement | Test |
|-------------|------|
| Consistency | `test_replay_snapshot_invariants.py` |
| Determinism | `test_audit_replay.py` |
| Perspective filtering | Scenario `REPRODUCIBILITY` |

### Prompt Inspector

| Requirement | Test |
|-------------|------|
| Aggregation | `test_prompt_inspector_api.py` |
| All sub-sections | Token count, cost, latency, template info |
| Turn range filtering | Query parameter tests |

### P6 Asset Pipeline (Future)

| Component | Required Tests |
|-----------|----------------|
| Model | Asset model tests |
| Cache | Cache hit/miss tests |
| Service | Generation service tests |
| API | Endpoint tests |

---

## Scenario Runner Strength Grading

### Smoke (8 tests)

Fast, no database required:

| Scenario Type | Purpose |
|---------------|---------|
| `SECRET_LEAK_PREVENTION` | NPC secret leak verification |
| `IMPORTANT_NPC_ATTACK` | Important NPC attack handling |
| `SEAL_COUNTDOWN` | Seal countdown mechanics |
| `FORBIDDEN_KNOWLEDGE` | Forbidden knowledge access |
| Core loop tests | Basic turn execution |
| Fallback tests | Mock provider fallback |
| Audit replay tests | Basic replay functionality |

**Command**: `make test-scenario-smoke`

### Integration

Full pipeline tests, may need database:

| Scenario Type | Purpose |
|---------------|---------|
| `INTEGRATION_FULL_TURN` | Full turn pipeline |
| `SAVE_CONSISTENCY` | Save/load state consistency |
| `QUEST_FLOW_VALIDATION` | Quest stage transitions |

**Command**: `pytest tests/scenario/ -m integration`

### Full

All scenarios, slowest but most comprehensive:

| Scenario Type | Purpose |
|---------------|---------|
| All smoke tests | Fast validation |
| All integration tests | Pipeline validation |
| `COMBAT_RULE_ENFORCEMENT` | Combat rules |
| `WORLD_TIME_PROGRESSION` | Time advancement |
| `AREA_SUMMARY_GENERATION` | Summary updates |
| `NPC_RELATIONSHIP_CHANGE` | Relationship tracking |
| `REPRODUCIBILITY` | Determinism check |

**Command**: `pytest tests/scenario/`

---

## Accepted Debts

These debts are documented but not resolved:

### 1. Non-debug Frontend Unit Tests

- **Status**: ~118 tests skipped (89/113 pre-existing failures)
- **Cause**: React 19 production build + jsdom incompatibility (error #299)
- **Mitigation**: Debug tests (105) pass with `NODE_ENV=development` workaround
- **Deferred to**: P6+

### 2. pgvector Tests

- **Status**: 8 tests skipped in default SQLite path
- **Cause**: pgvector extension only available in PostgreSQL
- **Mitigation**: CI has dedicated pgvector job; pass with PostgreSQL
- **Not blocking**: Default test path unaffected

### 3. Full Suite Timeout

- **Status**: `pytest tests/` takes > 5 minutes
- **Mitigation**: Use tiered gates (`test-p3`, `test-p4`, `test-p5`)
- **Not blocking**: CI uses quality gates, not full suite

---

## RC Prerequisites

Before a release candidate, all of the following must pass:

### 1. P5 Fast Gate

```bash
make test-p5-fast
```

Must pass with zero failures.

### 2. Frontend Quality

```bash
cd frontend
npm run build      # Production build
npx tsc --noEmit   # Type checking
npm run lint       # Linting
```

All must pass with zero errors.

### 3. No Unresolved P5 Blockers

Check `P5_READINESS.md` for any open blockers. All must be resolved or explicitly deferred with documentation.

### RC Checklist

- [ ] `make test-p5-fast` passes
- [ ] `npm run build` passes
- [ ] `npx tsc --noEmit` passes
- [ ] `npm run lint` passes
- [ ] No unresolved P5 blockers in `P5_READINESS.md`
- [ ] `IMPLEMENTATION_STATUS.md` updated
- [ ] `P5_COMPLETION_REPORT.md` updated

---

## Quick Reference

### Common Commands

```bash
# Show all targets
make help

# Backend only
make test-backend

# Frontend static checks
make test-frontend-static

# P3 gate
make test-p3

# P4 gate
make test-p4

# P5 gate
make test-p5

# Scenario smoke (fast)
make test-scenario-smoke

# pgvector tests (requires PostgreSQL)
make test-pgvector
```

### Test Markers

```bash
# Run by marker
pytest -m smoke       # Smoke tests
pytest -m pgvector    # pgvector tests
pytest -m scenario    # Scenario tests
pytest -m p5_scenario # P5 scenario tests
```

### Debug Specific Tests

```bash
# Single file
pytest tests/unit/test_specific.py -v

# Single test
pytest tests/unit/test_specific.py::test_function -v

# With print output
pytest tests/unit/test_specific.py -v -s
```
