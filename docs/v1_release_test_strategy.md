# V1 Release Test Strategy

**Date**: 2026-05-21
**Version**: V1.0

---

## Overview

This document defines the V1.0 release test strategy, including the test pyramid, release gate, frontend test debt strategy, and mock provider approach.

---

## V1 Test Pyramid

```
                    ┌──────────┐
                    │  E2E     │   Playwright (deferred to P10)
                    │  Tests   │   Requires full stack running
                    ├──────────┤
                    │ Scenario │   12 scenario types
                    │  Tests   │   Backend scenario tests
                    ├──────────┤
                    │Integration│  API + DB integration
                    │  Tests   │   FastAPI test client + SQLite
                    ├──────────┤
                    │  Unit    │   Pure function tests
                    │  Tests   │   No DB, no external deps
                    └──────────┘
```

### Layer Details

| Layer | Count | Environment | Speed |
|-------|-------|-------------|-------|
| Unit | ~1000+ | SQLite in-memory | <5 min |
| Integration | ~200+ | FastAPI + SQLite | <3 min |
| Scenario | ~50+ | FastAPI + SQLite | <2 min |
| E2E | Deferred | Full stack (PostgreSQL + Redis + Backend + Frontend) | N/A |

---

## Release Gate

### Command

```bash
make test-v1-release
```

### What It Runs

1. **Backend V1 tests** — Rule engine + Player APIs + Operations + Playthrough
2. **P8 regression gate** — No regression from previous phases
3. **Frontend static checks** — Build + Lint + TypeScript
4. **Frontend V1 game UI tests** — V1PlayableFlow.test.tsx

### Blocking Criteria

All of the following must pass:

| Gate | Command | Blocking |
|------|---------|----------|
| V1 Release | `make test-v1-release` | Yes |
| P8 Fast | `make test-p8-fast` | Yes |
| Frontend Build | `cd frontend && npm run build` | Yes |
| Frontend Lint | `cd frontend && npm run lint` | Yes |
| Frontend TypeScript | `cd frontend && npx tsc --noEmit` | Yes |

### Non-Blocking

| Gate | Command | Blocking |
|------|---------|----------|
| Full frontend unit tests | `cd frontend && npm test` | No (known skips) |
| E2E tests | `cd frontend && npm run test:e2e` | No (requires full stack) |

---

## V1 Component Gates

| Component | Makefile Target | Description |
|-----------|----------------|-------------|
| Rule Engine | `make test-v1-rule-engine` | MovementValidator, QuestValidator, ItemRules, SkillRules, ActionSchema, StateDeltaResolver, ConflictResolver |
| Game UI | `make test-v1-game-ui` | Frontend game panel tests |
| Operations | `make test-v1-ops` | Admin health/metrics/release-readiness |
| Playthrough | `make test-v1-playthrough` | 8-phase automated playthrough |

---

## Frontend Test Debt Strategy

### Current State

- **~48 test files** in the frontend test suite
- **~9 test files** skipped via `describe.skip()` due to React 19 + jsdom incompatibility
- **~39 test files** passing (debug, combat, asset, save tests)

### Strategy

1. **V1 Gate excludes skipped tests** — Only passing tests are blocking
2. **Skipped tests documented** — `docs/frontend_test_debt_audit.md` categorizes all debt
3. **Static checks are blocking** — Build, lint, and TypeScript must pass
4. **P10 resolution** — React 19 + jsdom compatibility to be resolved in P10+

### Classification

| Category | Count | Action |
|----------|-------|--------|
| A. Obsolete | 0 | Delete (none identified) |
| B. React 19/jsdom | ~9 | Keep skipped, document reason |
| C. V1 Critical (fixed) | ~14 | Unskipped and passing |
| D. Non-critical legacy | 0 | Keep skipped (none identified) |

---

## Mock Provider Approach

### Backend Mock Provider

The backend uses `MockLLMProvider` that returns predictable responses based on prompt content patterns:

- "narration" or "describe" → narrative text
- "npc" or "decision" → JSON action
- "intent" or "parse" → JSON intent

**Activation**: Automatically used when `OPENAI_API_KEY` is not set or `APP_ENV=testing`.

**Coverage**: All backend tests use mock provider. No real OpenAI API calls in CI.

### Asset Mock Provider

The backend uses `MockAssetProvider` that returns deterministic placeholder URLs:

- Portraits: `https://mock-assets.local/portrait/{hash}.png`
- Scenes: `https://mock-assets.local/scene/{hash}.png`
- BGM: `https://mock-assets.local/bgm/{hash}.mp3`

**Activation**: Automatically used when `ASSET_PROVIDER=mock` or unset.

**Coverage**: All CI tests use mock provider. DALL-E integration deferred to P10.

### Frontend Test Environment

Frontend tests use:
- `@testing-library/react` for component testing
- `jest` with `jsdom` environment
- MSW (Mock Service Worker) for API mocking in some tests
- Direct fetch mocking in others

**Workaround**: Debug tests use `NODE_ENV=development` to avoid React 17/19 production build issues with jsdom.

---

## CI Integration

### V1 Release Gate in CI

The `.github/workflows/ci.yml` includes a `v1-release-tests` job that:

1. Installs Python + Node dependencies
2. Runs `make test-v1-release`
3. Runs `make test-p8-fast`
4. Runs `cd frontend && npm run build && npm run lint && npx tsc --noEmit`

**Environment**: `APP_ENV=testing`, `ASSET_PROVIDER=mock`

**Blocking**: The job is NOT `continue-on-error` — failures block the pipeline.

---

## Verification Commands

```bash
# Full V1 release gate
make test-v1-release

# Individual component gates
make test-v1-rule-engine
make test-v1-game-ui
make test-v1-ops
make test-v1-playthrough

# P8 regression
make test-p8-fast

# Frontend static
cd frontend && npm run build && npm run lint && npx tsc --noEmit

# Frontend passing tests
cd frontend && npm test -- __tests__/debug/
cd frontend && npm test -- __tests__/combat/CombatPanel.test.tsx

# Full backend regression
cd backend && pytest -q
```

---

## References

- Frontend Test Debt Audit: `docs/frontend_test_debt_audit.md`
- Testing Strategy (general): `doc/testing_strategy.md`
- CI Workflow: `.github/workflows/ci.yml`
- Makefile: `Makefile`
- V1 Readiness: `V1_READINESS.md`
- V1 Completion: `V1_COMPLETION_REPORT.md`

---

*End of V1 Release Test Strategy*
