# Repository Instructions

## Project shape
- Backend is a Python/FastAPI app in `backend/`; the supported server entrypoint is `llm_rpg.main:app`.
- Frontend is a Next.js 16/React 19 app in `frontend/`; routes are always locale-prefixed (`/zh`, `/en`) with `zh` as default (`frontend/i18n/routing.ts`).
- Runtime infra is root `docker-compose.yml`: PostgreSQL + pgvector on 5432 and Redis on 6379.
- Also read `frontend/AGENTS.md` before frontend work; Next.js 16 has repo-local rules and API/proxy constraints.

## Commands agents usually guess wrong
- Backend setup: `cd backend && pip install -r requirements.txt`
- Backend dev server: `cd backend && uvicorn llm_rpg.main:app --reload --port 8000`
- Do not run `uvicorn app:app`; `backend/app_legacy.py` is reference-only legacy code.
- Frontend setup: `cd frontend && npm install` (uses `frontend/package-lock.json`; ignore the tiny root `package-lock.json`).
- Frontend dev server: `cd frontend && npm run dev` (script uses port 3005; Playwright config starts its own server on 3000).
- Frontend build/lint/typecheck: `cd frontend && npm run build`, `npm run lint`, `npx tsc --noEmit`.

## Tests and focused verification
- Backend tests: `cd backend && pytest -q`; focus with `pytest tests/unit/ -q`, `pytest tests/integration/ -q`, or `pytest path/to/test_file.py -q`.
- Backend pytest config is `backend/pytest.ini`; tests default to `backend/tests` and use `pythonpath = .`.
- Backend tests are designed for SQLite/mocks; they should not require PostgreSQL, Redis, or an OpenAI key.
- Frontend unit tests: `cd frontend && npm test`; focused file: `npm test -- path/to/test.tsx`.
- Frontend E2E: `cd frontend && npm run test:e2e`; requires backend on `127.0.0.1:8000` plus DB migrations and seed content. Playwright starts the frontend server on `127.0.0.1:3000`.
- Run frontend E2E commands from `frontend/`; the tiny root `package-lock.json` can make Next choose the wrong workspace root and fail module resolution.
- Playwright projects are `chromium`, `Mobile Chrome`, `Mobile Safari`, and `Tablet`; WebKit/mobile Safari may need extra OS browser libraries in minimal containers.
- Frontend E2E preflight is documented in `frontend/e2e/README.md`: `docker-compose up -d`, `cd backend && alembic upgrade head`, `python -m llm_rpg.scripts.seed_content`, then backend uvicorn with `OPENAI_API_KEY=`.

## Database and seed workflow
- Start services from repo root: `docker-compose up -d`; stop with `docker-compose down`.
- `docker-compose down -v` deletes local database/Redis volumes.
- Apply migrations: `cd backend && alembic upgrade head` (`backend/alembic/env.py` reads `DATABASE_URL`, defaulting to local PostgreSQL, and creates the `vector` extension).
- Seed world content after migrations: `cd backend && python -m llm_rpg.scripts.seed_content`.

## Frontend/API deployment gotchas
- Browser API calls should stay same-origin. `frontend/lib/api.ts` defaults to `process.env.NEXT_PUBLIC_API_URL ?? ''`; do not point browser code at `http://localhost:8000` by default.
- Backend routing for the frontend is in `frontend/next.config.ts` rewrites; keep API prefixes in sync with `frontend/proxy.ts` so `next-intl` does not intercept API requests.
- Public deployments should run `cd frontend && npm run build && npm run start`, not `next dev`; dev mode can hydrate slowly and let forms fall back to native `GET` submits before React handlers attach.
- `BACKEND_API_URL` is server-side rewrite config and must be reachable by the Next server (`127.0.0.1:8000` same-host, service DNS/container name in networked deployments).
- If adding a public frontend origin, add it to backend CORS (`backend/llm_rpg/main.py` / `CORS_ORIGINS`) separately.

## Tooling caveats
- There is no `.github/` CI directory and no pre-commit config; do not assume hidden checks.
- No backend formatter/linter/typechecker config was found; do not invent `ruff`, `black`, or `mypy` commands.
- Tailwind is v4 via `@tailwindcss/postcss`; there is no `tailwind.config.ts` to edit.
