# Repository Instructions

## Project shape
- Backend is FastAPI in `backend/`; the supported server entrypoint is `llm_rpg.main:app`.
- Frontend is Next.js 16/React 19 in `frontend/`; routes are always locale-prefixed (`/zh`, `/en`) with `zh` defaulted in `frontend/i18n/routing.ts`.
- Runtime infra is root `docker-compose.yml`: PostgreSQL + pgvector on 5432 and Redis on 6379.
- Before frontend changes, read `frontend/AGENTS.md` and the relevant Next 16 docs under `frontend/node_modules/next/dist/docs/`.

## Communication
- 回复用户时使用中文。

## Commands agents usually guess wrong
- Backend setup: `cd backend && pip install -r requirements.txt`.
- Backend dev server: `cd backend && uvicorn llm_rpg.main:app --reload --port 8000`; do not use legacy `backend/app_legacy.py` or `uvicorn app:app`.
- Frontend setup: `cd frontend && npm install`; use `frontend/package-lock.json`, not a root lockfile.
- Frontend dev server: `cd frontend && npm run dev` (port 3005). Playwright starts its own frontend server on port 3000.
- Frontend checks: `cd frontend && npm run build`, `npm run lint`, `npx tsc --noEmit`, `npm test`.

## Tests and focused verification
- Backend tests: `cd backend && pytest -q`; focus with `pytest tests/unit/ -q`, `pytest tests/integration/ -q`, or `pytest path/to/test_file.py -q`.
- Backend pytest config sets `pythonpath = .` and `testpaths = tests`; tests are intended to use SQLite/mocks and should not require PostgreSQL, Redis, or an OpenAI key.
- Frontend unit tests: `cd frontend && npm test`; focus with `npm test -- path/to/test.tsx`.
- Frontend E2E: `cd frontend && npm run test:e2e`; requires backend on `127.0.0.1:8000` plus DB migrations and seed content. Playwright projects: `chromium`, `Mobile Chrome`, `Mobile Safari`, `Tablet`.
- E2E preflight: `docker-compose up -d`, `cd backend && alembic upgrade head`, `python -m llm_rpg.scripts.seed_content`, then `cd backend && OPENAI_API_KEY= APP_ENV=development uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000`.

## Database and seed workflow
- Start services from repo root: `docker-compose up -d`; `docker-compose down -v` deletes local DB/Redis volumes.
- Migrations run from `backend/`: `alembic upgrade head`. `backend/alembic/env.py` reads `DATABASE_URL`, defaults to local PostgreSQL, and creates the `vector` extension.
- Seed world content after migrations: `cd backend && python -m llm_rpg.scripts.seed_content`.

## Frontend/API deployment gotchas
- Browser API calls should stay same-origin: `frontend/lib/api.ts` defaults to `process.env.NEXT_PUBLIC_API_URL ?? ''`; do not hardcode browser calls to `http://localhost:8000`.
- Keep backend API prefixes synchronized between `frontend/next.config.ts` rewrites and `frontend/proxy.ts` matcher exclusions, or `next-intl` will intercept API requests.
- `BACKEND_API_URL` is server-side rewrite config and must be reachable by the Next server (`127.0.0.1:8000` same-host, service DNS/container name in networks).
- Public frontend deploys must use `cd frontend && npm run build && npm run start`; never expose `next dev` publicly.
- Auth forms must keep `method="post"` and controls disabled before hydration so slow/unhydrated pages cannot native-GET credentials into the URL.
- If adding a public frontend origin, add it to backend CORS (`backend/llm_rpg/main.py` / `CORS_ORIGINS`) separately.

## Tooling caveats
- After each completed modification round, verify and create an atomic git commit for that round.
- There is no `.github/` CI directory and no pre-commit config; do not assume hidden checks.
- No backend formatter/linter/typechecker config was found; do not invent `ruff`, `black`, or `mypy` commands.
- Tailwind is v4 via `@tailwindcss/postcss`; there is no `tailwind.config.ts` to edit.
