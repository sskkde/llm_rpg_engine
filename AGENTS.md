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

## Tooling caveats
- No CI workflows or pre-commit config are present; do not assume hidden checks.
- No backend formatter/linter/typechecker config was found; do not invent `ruff`, `black`, or `mypy` commands.
- Keep repo instructions compact and verified; prefer executable config over README prose if they disagree.
