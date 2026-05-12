# P5 Readiness

**Status**: Ready for P5 planning and pre-research, not a release candidate.

## What Is Complete

- P4 content productization features are complete.
- P4 content pack validation/import paths pass.
- P4 Admin API and Admin UI features are in place.
- P4 scenario regression and replay report gates pass.
- P4 Makefile and CI targets are in place.

## Accepted Debt

- Admin UI tests are accepted debt: 36 tests remain skipped under the current React 19 / @testing-library setup.
- CI keeps `frontend-admin-tests` as a soft gate with `continue-on-error: true`.
- This is acceptable for P5 planning, but should be revisited before any release-candidate claim.

## P5 Entry Checklist

- `make test-p4` passes.
- `make test-content` passes.
- `make test-admin-content` passes.
- `make test-scenario-regression` passes.
- `make test-replay-report` passes.
- `make test-frontend-static` passes.
- `make test-frontend-combat` passes.

## Not Yet Ready For

- P5 release candidate / production readiness.
- Media generation work.
- Engine rewrite work.

## Recommendation

Proceed with P5 planning and pre-research now. Revisit the admin UI test debt only if a later P5 milestone needs it as a hard gate.
