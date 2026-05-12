# Makefile — Unified test and run commands for llm_rpg_engine
# Aligned with AGENTS.md canonical commands. Used by CI and local development.

.PHONY: help \
        test-backend test-scenario-smoke test-pgvector test-p3 \
        test-backend-unit test-backend-integration \
        test-frontend-static test-frontend-unit test-frontend-combat \
        run-backend run-frontend \
        docker-up docker-down

help: ## Show all available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}'

# ── Test targets ──────────────────────────────────────────────

test-backend: ## Run all backend tests (pytest)
	@cd backend && python3 -m pytest -q --tb=short

test-backend-unit: ## Run backend unit tests only
	@cd backend && python3 -m pytest tests/unit/ -q --tb=short

test-backend-integration: ## Run backend integration tests only
	@cd backend && python3 -m pytest tests/integration/ -q --tb=short

test-scenario-smoke: ## Run scenario smoke tests
	@cd backend && python3 -m pytest tests/scenario -q -m smoke --tb=short

test-pgvector: ## Run pgvector-marked backend tests
	@cd backend && python3 -m pytest -q -m pgvector --tb=short -v

test-frontend-static: ## Run frontend lint and typecheck (blocking gate)
	@cd frontend && npm run lint
	@cd frontend && npx tsc --noEmit

test-frontend-unit: ## Run frontend unit tests (deferred - known failures)
	@cd frontend && npm test

test-frontend-combat: ## Run stable combat frontend tests only
	@cd frontend && npm test -- __tests__/combat/CombatPanel.test.tsx

test-p3: ## Quality gate: backend + scenario smoke + pgvector + frontend static + combat
	@cd backend && python3 -m pytest -q --tb=short
	@cd backend && python3 -m pytest tests/scenario -q -m smoke --tb=short
	@cd backend && python3 -m pytest -q -m pgvector --tb=short
	@cd frontend && npm run lint
	@cd frontend && npx tsc --noEmit
	@cd frontend && npm test -- __tests__/combat/CombatPanel.test.tsx

# ── Run targets ───────────────────────────────────────────────

run-backend: ## Start backend dev server (port 8000)
	@cd backend && uvicorn llm_rpg.main:app --reload --port 8000

run-frontend: ## Start frontend dev server (port 3005)
	@cd frontend && npm run dev

# ── Docker targets ────────────────────────────────────────────

docker-up: ## Start PostgreSQL + Redis via docker-compose
	@docker-compose up -d

docker-down: ## Stop and remove docker-compose containers
	@docker-compose down
