# E2E Test Setup

## Backend Preflight Commands

Before running E2E tests, ensure the backend is running:

```bash
# From repo root - start infrastructure
docker-compose up -d

# Run database migrations
cd backend && alembic upgrade head

# Seed world content
python -m llm_rpg.scripts.seed_content

# Start backend (no OpenAI key needed for mock provider)
cd backend && OPENAI_API_KEY= APP_ENV=development uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000
```

## Frontend Setup

```bash
cd frontend
npm install
```

## Running Tests

```bash
# Run all E2E tests
npx playwright test

# Run specific test file
npx playwright test e2e/auth-saves-game.spec.ts

# Run with UI
npx playwright test --ui

# Run in headed mode
npx playwright test --headed
```

## Health Check

Tests will fail fast if backend is unavailable. Verify backend is running:

```bash
curl http://127.0.0.1:8000/health
```

## Environment Variables

- `NEXT_PUBLIC_API_URL` - Backend API URL (default: http://localhost:8000)
- `CI` - Set to enable retries and single worker
