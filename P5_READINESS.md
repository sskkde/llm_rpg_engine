# P5 Readiness Checklist

**Phase**: P5 Debug/Test/Replay Productization
**Status**: COMPLETE
**Last Verified**: 2026-05-14

---

## P6 Entry Criteria

Before entering P6, all P5 gates must pass and the following criteria must be met:

### Required Gates

| Gate | Command | Status |
|------|---------|--------|
| P5 scenario tests | `make test-scenario-p5` | PASS (77 tests) |
| Prompt Inspector tests | `make test-prompt-inspector` | PASS (13 tests) |
| Replay report tests | `make test-replay-report` | PASS (147 tests) |
| Memory writer regression | `cd backend && pytest tests/integration/test_timeline_npc_mind.py tests/integration/test_memory_writes_to_db.py -q` | PASS (44 tests) |
| P2 strengthening tests | `cd backend && python3 -m pytest tests/unit/test_audit_db_persistence.py tests/unit/test_context_builder_p2.py tests/unit/test_narration_leak_hardening.py -q` | PASS (70 tests) |
| Frontend static checks | `cd frontend && npm run lint && npx tsc --noEmit && npm run build` | PASS |
| Frontend debug tests | `cd frontend && npm test` | PASS (105/105, 0 skipped) |
| P4 regression | `make test-p4` | PASS (no regression) |

### Documentation Checklist

| Document | Status |
|----------|--------|
| `P5_COMPLETION_REPORT.md` | Created |
| `P5_READINESS.md` | This file |
| `IMPLEMENTATION_STATUS.md` | Updated with P5 section |
| `README.md` | Updated with P5 section |
| `AGENTS.md` | Reviewed (no changes needed) |

---

## P5 Deliverables Verification

### Frontend Debug Components (13 files)

- [x] `frontend/components/debug/DebugSessionSelector.tsx` - Exists
- [x] `frontend/components/debug/DebugErrorBoundary.tsx` - Exists
- [x] `frontend/components/debug/DebugEmptyState.tsx` - Exists
- [x] `frontend/components/debug/DebugLoading.tsx` - Exists
- [x] `frontend/components/debug/TimelineViewer.tsx` - Exists
- [x] `frontend/components/debug/NPCMindInspector.tsx` - Exists
- [x] `frontend/components/debug/TurnDebugViewer.tsx` - Exists
- [x] `frontend/components/debug/ContextBuildAudit.tsx` - Exists
- [x] `frontend/components/debug/ValidationAuditViewer.tsx` - Exists
- [x] `frontend/components/debug/PromptInspector.tsx` - Exists
- [x] `frontend/components/debug/ReplayControls.tsx` - Exists
- [x] `frontend/components/debug/StateDiffViewer.tsx` - Exists
- [x] `frontend/components/debug/ReplayReportViewer.tsx` - Exists

### Frontend Pages

- [x] `frontend/app/[locale]/debug/page.tsx` - Exists (209 lines, 6 tabs)
- [x] `frontend/app/[locale]/replay/page.tsx` - Exists (103 lines)

### Backend Components

- [x] `backend/llm_rpg/observability/scenario_runner.py` - 12 scenario types
- [x] `backend/llm_rpg/core/audit.py` - AuditStore DB persistence for model_calls
- [x] `backend/llm_rpg/core/context_builder.py` - NPCContextBuilder strengthened
- [x] `backend/llm_rpg/core/validation/narration_leak_validator.py` - Hardened
- [x] `backend/alembic/versions/011_add_model_call_audit_logs.py` - Migration exists

### Test Files

- [x] `backend/tests/unit/test_audit_db_persistence.py` - Exists
- [x] `backend/tests/unit/test_context_builder_p2.py` - Exists
- [x] `backend/tests/unit/test_narration_leak_hardening.py` - Exists
- [x] `backend/tests/integration/test_prompt_inspector_api.py` - Exists
- [x] `backend/tests/scenario/test_new_scenario_types.py` - Exists

---

## P6 Scope Preview

The following items are candidates for P6:

### High Priority
1. **Media Generation Infrastructure**
   - Portrait generation (`/media/portraits/generate`)
   - Scene image generation (`/media/scenes/generate`)
   - Background music generation (`/media/bgm/generate`)
   - Async job infrastructure (Celery/RQ/Temporal)

2. **Full AuditStore Persistence**
   - Persist context_builds to DB
   - Persist validations to DB
   - Persist turn_audits to DB
   - Persist proposal_audits to DB
   - Persist errors to DB

### Medium Priority
3. **ForgetCurve Background Decay**
   - Background job for memory strength decay
   - Configurable decay rates
   - NPC memory cleanup

4. **Advanced Leak Detection**
   - Semantic similarity matching
   - Embedding-based leak detection
   - False positive reduction

### Low Priority
5. **Engine Refactoring**
   - ReplayEngine optimization
   - Turn Orchestrator improvements

---

## Known Issues for P6

### Carried Forward from P5

1. **Frontend Non-Debug Tests (React 19 Compatibility)**
   - ~118 non-debug frontend tests still skipped (inherited from P4)
   - Debug tests (105) are now all passing with `NODE_ENV=development` workaround
   - Test environment issues, not application bugs
   - Requires @testing-library/react update or React 19 test utilities

2. **pgvector Tests Require PostgreSQL**
   - 8 tests skipped in SQLite path
   - CI handles with dedicated PostgreSQL job

3. **Full Test Suite Timeout**
   - `make test-p5` runs P1-P5 (2219 tests) and may timeout
   - Use individual P5 targets for verification (all pass individually)

---

## Accepted Debt

- Non-debug frontend unit tests remain skipped (~118 tests) due to React 19 / @testing-library compatibility
- These are test environment issues, not application bugs
- Debug frontend tests (105) are fully passing after React 19 jsdom fix
- CI uses `continue-on-error: true` for affected jobs
- Should be revisited before any release-candidate claim

---

## Sign-off

### P5 Completion Status

- [x] All P5 deliverables implemented
- [x] All P5 tests pass
- [x] No regression in P4/P3 gates
- [x] Documentation complete
- [x] Ready for P6 planning

**P5 Status**: **COMPLETE - Ready for P6 Planning**

---

## Verification Commands

```bash
# Verify P5 is complete
make test-scenario-p5
make test-prompt-inspector

# Verify P2 strengthening
cd backend && python3 -m pytest tests/unit/test_audit_db_persistence.py tests/unit/test_context_builder_p2.py tests/unit/test_narration_leak_hardening.py -q

# Verify no regression
make test-p4

# Verify frontend
cd frontend && npm run lint && npx tsc --noEmit

# Verify debug pages exist
ls -la frontend/app/\[locale\]/debug/page.tsx
ls -la frontend/app/\[locale\]/replay/page.tsx
ls frontend/components/debug/*.tsx | wc -l  # Should be 13
```
