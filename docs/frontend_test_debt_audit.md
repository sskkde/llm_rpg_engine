# Frontend Test Debt Audit

**Date**: 2026-05-21
**Status**: V1.0 Release Ready with Known Test Debt

---

## Summary

The frontend test suite has 48 test files total. The majority of tests pass, but some tests are explicitly skipped due to React 19 + jsdom compatibility issues. This audit categorizes the skipped tests and documents the mitigation strategy.

---

## Test Categories

### A. Obsolete Tests (Delete)

None identified. All skipped tests have valid reasons for deferral.

---

### B. React 19/jsdom Compatibility (Keep Skipped)

These tests are skipped due to React 19 production build incompatibility with jsdom test environment. This is a known issue tracked as React error #299.

| Test File | Reason | Action |
|-----------|--------|--------|
| `__tests__/CollapsibleSection.test.tsx` | React 19 + jsdom incompatibility | Keep skipped, document reason |
| `__tests__/Tabs.test.tsx` | React 19 + jsdom incompatibility | Keep skipped, document reason |
| `__tests__/admin/AdminSection.test.tsx` | React 19 + jsdom incompatibility | Keep skipped, document reason |
| `__tests__/admin/FactionEditor.test.tsx` | React 19 + jsdom incompatibility | Keep skipped, document reason |
| `__tests__/admin/PlotBeatEditor.test.tsx` | React 19 + jsdom incompatibility | Keep skipped, document reason |
| `__tests__/admin/ContentPackValidationPanel.test.tsx` | React 19 + jsdom incompatibility | Keep skipped, document reason |
| `__tests__/admin/SystemSettingsPanel.test.tsx` | React 19 + jsdom incompatibility | Keep skipped, document reason |
| `__tests__/combat/CombatParticipantCard.test.tsx` | React 19 + jsdom incompatibility | Keep skipped, document reason |
| `__tests__/game/GameSessionPage.test.tsx` | React 19 + jsdom incompatibility | Keep skipped, document reason |

**Count**: 9 test files with `describe.skip`

**Root Cause**: React 19 changed internal behavior that jsdom cannot simulate. The `NODE_ENV=development` workaround was applied for debug tests but not for these components.

**Mitigation**: 
- Tests explicitly marked with `describe.skip()`
- Reason documented in each test file
- P10 scope: React 19 + jsdom compatibility resolution

---

### C. V1 Critical Tests (Fixed and Unskipped)

These tests were identified as V1 critical and have been fixed and unskipped.

| Test File | Status | Fix Applied |
|-----------|--------|-------------|
| `__tests__/saves/SaveSlotList.test.tsx` | PASSING | Unskipped, save system is V1 core |
| `__tests__/debug/*.test.tsx` (all 13 files) | PASSING | Unskipped with `NODE_ENV=development` workaround |

**Count**: 14 test files now passing

---

### D. Non-Critical Legacy Tests (Keep Skipped)

None identified. All non-critical tests fall into category B.

---

## Passing Test Suites

The following test suites pass and provide adequate coverage for V1:

| Suite | Files | Status |
|-------|-------|--------|
| Debug Tests | 13 files | All PASS |
| Combat Tests | 2 files | All PASS |
| Asset Tests | 8 files | All PASS |
| Save Tests | 1 file | PASS |
| Other Passing | ~15 files | PASS |

**Total Passing**: ~39 test files

---

## V1 Test Gate

The V1 test gate is defined as:

```bash
# Frontend static checks (blocking)
cd frontend && npm run build && npm run lint && npx tsc --noEmit

# Debug tests (blocking)
cd frontend && npm test -- __tests__/debug/

# Combat tests (blocking)
cd frontend && npm test -- __tests__/combat/CombatPanel.test.tsx
```

All V1 gate tests pass.

---

## P10 Scope

The following items are deferred to P10+:

1. **React 19 + jsdom compatibility resolution**
   - Investigate jsdom updates or alternative test environment
   - Consider switching to @testing-library/react-hooks for hook tests
   - May require React team to address jsdom compatibility

2. **Full frontend unit test coverage**
   - Unskip all tests once compatibility resolved
   - Add missing tests for new V1 components

---

## Recommendations

1. **Do NOT remove skipped tests** - They represent real test coverage that will be needed
2. **Document skip reason** - Each `describe.skip` should have a comment explaining why
3. **Monitor React 19 updates** - Watch for jsdom compatibility fixes
4. **P10 prioritization** - Frontend test debt should be addressed in P10

---

## Verification

```bash
# Verify static checks pass
cd frontend && npm run build && npm run lint && npx tsc --noEmit

# Verify debug tests pass
cd frontend && npm test -- __tests__/debug/

# Verify combat tests pass
cd frontend && npm test -- __tests__/combat/CombatPanel.test.tsx

# List all skipped tests
cd frontend && grep -r "describe.skip\|it.skip" __tests__/
```

---

*End of Frontend Test Debt Audit*
