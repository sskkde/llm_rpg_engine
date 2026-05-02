# Repository Instructions

## Project shape
- Backend is a Python/FastAPI app in `backend/`; the supported server entrypoint is `llm_rpg.main:app`.
- Frontend is a Next.js 16/React app in `frontend/`; it uses locale-prefixed routes with default locale `zh` and `en` also supported.
- Runtime infrastructure is root `docker-compose.yml`: PostgreSQL with pgvector on 5432 and Redis on 6379.
- Also read `frontend/AGENTS.md` before frontend route work; it documents the Next.js 16 async dynamic route props requirement.

## Commands agents usually guess wrong
- Backend setup: `cd backend && pip install -r requirements.txt`
- Backend dev server: `cd backend && uvicorn llm_rpg.main:app --reload --port 8000`
- Do not run `uvicorn app:app` or import legacy `app.py`/`app_legacy.py` entrypoints.
- Frontend setup: `cd frontend && npm install`
- Frontend dev server: `cd frontend && npm run dev` (port 3005, not 3000)
- Frontend build/lint/typecheck: `cd frontend && npm run build`, `npm run lint`, `npx tsc --noEmit`

## Tests and focused verification
- Backend tests: `cd backend && pytest -q`
- Focus backend tests with `pytest tests/unit/ -q`, `pytest tests/integration/ -q`, or `pytest path/to/test_file.py -q`.
- Backend tests use SQLite/mocks; they should not need PostgreSQL, Redis, or an OpenAI key.
- Frontend unit tests: `cd frontend && npm test`; focused file: `npm test -- path/to/test.tsx`.
- Frontend E2E: `cd frontend && npm run test:e2e`; requires backend on `localhost:8000` and database services/migrations ready. Playwright starts the frontend server.

## Database and seed workflow
- Start services from repo root: `docker-compose up -d`; stop with `docker-compose down`.
- `docker-compose down -v` deletes local database/Redis volumes.
- Apply migrations: `cd backend && alembic upgrade head`.
- Seed world content after migrations: `cd backend && python -m llm_rpg.scripts.seed_content`.

## Public frontend deployment key points
- In public deployments, start the frontend with a production build (`cd frontend && npm run build && npm run start`), not `npm run dev`.
- If the public frontend runs `next dev`, slow hydration can degrade interactive forms to native `GET` submits before React attaches `onSubmit`, which breaks login/register navigation.
- Keep browser API calls same-origin. In `frontend/lib/api.ts`, use a relative default (`const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? ''`) and do not point the browser at `http://localhost:8000`.
- In `frontend/next.config.ts`, use server-side `rewrites` to forward `/auth`, `/saves`, `/sessions`, `/world`, `/game`, `/streaming`, `/combat`, `/admin`, `/debug`, `/media`, and `/dev` to the backend. Default backend URL: `process.env.BACKEND_API_URL || 'http://127.0.0.1:8000'`.
- In `frontend/proxy.ts`, exclude the backend API prefixes from the `next-intl` matcher so the proxy does not intercept API requests before `next.config.ts` rewrites run.
- Add the public frontend origin to backend CORS when needed, e.g. `https://llm.nas-1.club:18080`.
- `BACKEND_API_URL` is server-side routing config. It must be reachable by the Next server (`127.0.0.1:8000` for same-host, or the service DNS/container name in networked deployments).

## Tooling caveats
- No CI workflows or pre-commit config are present; do not assume hidden checks.
- No backend formatter/linter/typechecker config was found; do not invent `ruff`, `black`, or `mypy` commands.
- Keep repo instructions compact and verified; prefer executable config over README prose if they disagree.
