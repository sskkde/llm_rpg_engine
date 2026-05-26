# Makefile — Unified test and run commands for llm_rpg_engine
# Aligned with AGENTS.md canonical commands. Used by CI and local development.

.PHONY: help \
        test-backend test-scenario-smoke test-scenario-regression test-scenario-full test-scenario-p5 test-pgvector test-p3 test-p4 test-p5 test-p5-fast test-debug-contract test-content \
        test-backend-unit test-backend-integration \
        test-frontend-static test-frontend-unit test-frontend-combat test-frontend-admin \
        test-prompt-inspector test-replay-report \
        test-assets-unit test-media-api test-asset-debug-api test-frontend-assets test-p6-fast test-p6 \
        test-asset-job-model-unit test-asset-jobs-api test-frontend-asset-jobs test-scenario-p7 test-p7-fast test-p7 \
        test-asset-provider-p8 test-asset-queue-p8 test-asset-cost-rate-p8 test-admin-audit-p8 test-frontend-p8-assets test-scenario-p8 test-p8-fast test-p8 \
        test-v1-rule-engine test-v1-game-ui test-v1-ops test-v1-playthrough test-v1-release \
        test-p10a-quests test-p10a-providers test-p10a-streaming test-p10a-time test-p10a-fast test-p10a \
        test-p10b-resolver test-p10b-routing test-p10b-debug test-p10b-fast test-p10b \
        test-p10c-npc-memory-unit test-p10c-story-editor-unit test-p10c-content-pack-unit test-p10c-integration test-p10c-fast test-p10c test-p10c-gate \
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

test-scenario-regression: ## Run scenario regression tests
	@cd backend && python3 -m pytest tests/scenario -q -m regression --tb=short

test-scenario-full: ## Run all scenario tests including full suite
	@cd backend && python3 -m pytest tests/scenario -q -m "smoke or regression or full" --tb=short

test-pgvector: ## Run pgvector-marked backend tests
	@cd backend && python3 -m pytest -q -m pgvector --tb=short -v

test-frontend-static: ## Run frontend lint and typecheck (blocking gate)
	@cd frontend && npm run lint
	@cd frontend && npx tsc --noEmit

test-frontend-unit: ## Run frontend unit tests (deferred - known failures)
	@cd frontend && npm test

test-frontend-combat: ## Run stable combat frontend tests only
	@cd frontend && npm test -- __tests__/combat/CombatPanel.test.tsx

test-content: ## Validate the qinglan_xianxia content pack
	@cd backend && python3 -m llm_rpg.scripts.validate_content_pack ../content_packs/qinglan_xianxia

test-admin-content: ## Run admin content API integration tests
	@cd backend && python3 -m pytest tests/integration/ -q -k "admin" --tb=short

test-replay-report: ## Run replay report unit + integration tests
	@cd backend && python3 -m pytest tests/ -q -k "replay" --tb=short

test-frontend-admin: ## Run admin UI tests
	@cd frontend && npm test -- __tests__/admin

test-p4: ## P4 quality gate: test-p3 + content + admin-content + scenario-regression + replay-report + frontend-admin
	@$(MAKE) test-p3
	@$(MAKE) test-content
	@$(MAKE) test-admin-content
	@$(MAKE) test-scenario-regression
	@$(MAKE) test-replay-report
	@$(MAKE) test-frontend-static
	@$(MAKE) test-frontend-combat
	@$(MAKE) test-frontend-admin

test-assets-unit: ## Run P6 asset unit tests (cache key, repository, service, provider factory)
	@cd backend && python3 -m pytest tests/unit/test_asset_cache_key.py tests/unit/test_asset_repository.py tests/unit/test_asset_generation_service.py tests/unit/test_asset_provider_factory.py -q --tb=short

test-media-api: ## Run P6 media API integration tests
	@cd backend && python3 -m pytest tests/integration/test_media_api.py -q --tb=short

test-frontend-assets: ## Run frontend asset component tests
	@cd frontend && npm test -- __tests__/assets --runInBand

test-asset-debug-api: ## Run P6 asset debug API integration tests
	@cd backend && python3 -m pytest tests/integration/test_asset_debug_api.py -q --tb=short

test-p6-fast: ## P6 fast gate: p5-fast + asset unit + media API + asset debug API + frontend assets
	@$(MAKE) test-p5-fast
	@$(MAKE) test-assets-unit
	@$(MAKE) test-media-api
	@$(MAKE) test-asset-debug-api
	@$(MAKE) test-frontend-assets

test-p6: ## P6 quality gate: p6-fast + p4 (full regression)
	@$(MAKE) test-p6-fast
	@$(MAKE) test-p4

# === P7: Asset Job Infrastructure ===

test-asset-job-model-unit: ## Run P7 unit tests
	cd backend && APP_ENV=testing python3 -m pytest tests/unit/test_asset_job_service.py tests/unit/test_asset_job_repository.py tests/unit/test_asset_job_runner.py tests/unit/test_asset_retry_policy.py tests/unit/test_asset_provider_registry.py -q --tb=short

test-asset-jobs-api: ## Run P7 integration tests
	cd backend && APP_ENV=testing python3 -m pytest tests/integration/test_asset_jobs_api.py tests/integration/test_asset_debug_jobs_api.py tests/integration/test_game_asset_integration_api.py -q --tb=short

test-frontend-asset-jobs: ## Run P7 frontend tests
	cd frontend && npm test -- __tests__/assets/useAssetJob.test.tsx __tests__/assets/SceneBackground.p7.test.tsx __tests__/assets/GameAssetIntegration.test.tsx --runInBand

test-scenario-p7: ## Run P7 scenario tests
	cd backend && APP_ENV=testing python3 -m pytest tests/scenario/test_asset_generation_workflow.py -q --tb=short

test-p7-fast: test-p6-fast test-asset-job-model-unit test-asset-jobs-api test-frontend-asset-jobs ## Run P7 fast gate

test-p7: test-p7-fast test-scenario-p7 ## Run P7 full gate

# === P8: Production Asset Runtime ===

test-asset-provider-p8:
	cd backend && APP_ENV=testing python3 -m pytest \
		tests/unit/test_asset_provider_registry_p8.py \
		tests/unit/test_openai_image_provider_p8.py \
		tests/unit/test_audio_provider_p8.py \
		tests/unit/test_provider_errors.py \
		-q --tb=short

test-asset-queue-p8:
	cd backend && APP_ENV=testing python3 -m pytest \
		tests/unit/test_asset_queue_backend.py \
		tests/unit/test_asset_job_lease.py \
		tests/unit/test_asset_worker_cli.py \
		-q --tb=short

test-asset-cost-rate-p8:
	cd backend && APP_ENV=testing python3 -m pytest \
		tests/unit/test_asset_usage_service.py \
		tests/unit/test_asset_rate_limit.py \
		tests/integration/test_asset_rate_limit_api.py \
		tests/integration/test_asset_usage_api.py \
		-q --tb=short

test-admin-audit-p8:
	cd backend && APP_ENV=testing python3 -m pytest \
		tests/integration/test_admin_audit_api.py \
		-q --tb=short

test-frontend-p8-assets:
	cd frontend && npm test -- \
		__tests__/assets/NPCPortrait.p8.test.tsx \
		__tests__/debug/AssetQueueViewer.test.tsx \
		__tests__/debug/AssetUsageViewer.test.tsx \
		__tests__/debug/ProviderHealthViewer.test.tsx \
		__tests__/debug/RateLimitViewer.test.tsx \
		--runInBand

test-scenario-p8:
	cd backend && APP_ENV=testing python3 -m pytest \
		tests/scenario/test_p8_asset_runtime.py \
		-q --tb=short

test-p8-fast: test-p7-fast test-asset-provider-p8 test-asset-queue-p8 test-asset-cost-rate-p8 test-admin-audit-p8 test-frontend-p8-assets ## Run P8 fast gate

test-p8: test-p8-fast test-scenario-p8 ## Run P8 full gate

test-scenario-p5: ## Run P5 scenario tests (new scenario types)
	@cd backend && python3 -m pytest tests/scenario/ -q -m "p5_scenario" --tb=short

test-prompt-inspector: ## Run prompt inspector API tests
	@cd backend && python3 -m pytest tests/integration/test_prompt_inspector_api.py -q --tb=short

test-debug-contract: ## Run debug contract tests (backend debug + frontend debug + tsc)
	@cd backend && python3 -m pytest tests/ -q -k "debug" --tb=short
	@cd frontend && npx tsc --noEmit
	@cd frontend && npm test -- --testPathPatterns="debug" --runInBand

test-p5-fast: ## P5 fast gate: debug contract + scenario-p5 + prompt-inspector (< 60s)
	@$(MAKE) test-debug-contract
	@$(MAKE) test-scenario-p5
	@$(MAKE) test-prompt-inspector

test-p5: ## P5 quality gate: test-p4 + scenario-p5 + replay-report + prompt-inspector
	@$(MAKE) test-p4
	@$(MAKE) test-scenario-p5
	@$(MAKE) test-replay-report
	@$(MAKE) test-prompt-inspector

test-p3: ## Quality gate: backend + scenario smoke + pgvector + frontend static + combat
	@cd backend && python3 -m pytest -q --tb=short
	@cd backend && python3 -m pytest tests/scenario -q -m smoke --tb=short
	@cd backend && python3 -m pytest -q -m pgvector --tb=short
	@cd frontend && npm run lint
	@cd frontend && npx tsc --noEmit
	@cd frontend && npm test -- __tests__/combat/CombatPanel.test.tsx

# === V1.0 Release Targets ===

test-v1-rule-engine: ## Run WP1 rule engine tests (MovementValidator, QuestValidator, ItemRules, SkillRules, ActionSchema, StateDeltaResolver, ConflictResolver)
	cd backend && APP_ENV=testing python3 -m pytest \
		tests/unit/test_movement_validator.py \
		tests/unit/test_quest_validator.py \
		tests/unit/test_item_rules.py \
		tests/unit/test_skill_rules.py \
		tests/unit/test_action_schema.py \
		tests/unit/test_state_delta_resolver.py \
		tests/unit/test_conflict_resolver.py \
		tests/scenario/test_rule_engine_v1.py \
		-q --tb=short

test-v1-game-ui: ## Run WP2 game panel test suite
	cd frontend && npm test -- \
		__tests__/game/QuestJournalPanel.test.tsx \
		__tests__/game/InventoryPanel.test.tsx \
		__tests__/game/LocationMapPanel.test.tsx \
		__tests__/game/RelationshipPanel.test.tsx \
		__tests__/game/V1PlayableFlow.test.tsx \
		--runInBand

test-v1-ops: ## Run WP3 operations API tests (admin ops + release readiness + player API)
	cd backend && APP_ENV=testing python3 -m pytest \
		tests/integration/test_admin_ops_api.py \
		tests/integration/test_release_readiness_api.py \
		tests/integration/test_player_api.py \
		-q --tb=short

test-v1-playthrough: ## Run V1.0 playthrough scenario tests
	@cd backend && APP_ENV=testing python3 -m pytest tests/scenario/test_v1_playthrough.py -q --tb=short

test-v1-release: ## V1.0 release gate: all V1 tests + test-p8-fast + frontend build/lint/tsc
	@$(MAKE) test-v1-rule-engine
	@$(MAKE) test-v1-game-ui
	@$(MAKE) test-v1-ops
	@$(MAKE) test-v1-playthrough
	@$(MAKE) test-p8-fast
	@cd frontend && npm run build
	@cd frontend && npm run lint
	@cd frontend && npx tsc --noEmit

# === P10-A: Immersion Provider Routing ===

test-p10a-quests:
	cd backend && APP_ENV=testing python3 -m pytest tests/unit/test_quest_journal_service.py tests/integration/test_quest_visibility_api.py -q --tb=short

test-p10a-providers:
	cd backend && APP_ENV=testing python3 -m pytest tests/unit/test_asset_provider_resolver.py tests/integration/test_media_provider_routing.py -q --tb=short

test-p10a-streaming:
	cd backend && APP_ENV=testing python3 -m pytest tests/integration/test_streaming_stage_events.py -q --tb=short

test-p10a-time:
	cd backend && APP_ENV=testing python3 -m pytest tests/unit/test_time_advance_validator.py tests/integration/test_dynamic_world_time.py -q --tb=short

test-p10a-fast: test-v1-release test-p10a-streaming test-p10a-time test-p10a-quests test-p10a-providers

test-p10a:
	$(MAKE) test-p10a-fast
	cd frontend && npm run build
	cd frontend && npm run lint
	cd frontend && npx tsc --noEmit

# === P10-B: Stage-Level LLM Routing ===

test-p10b-resolver:
	cd backend && APP_ENV=testing python3 -m pytest tests/unit/test_llm_stage_provider_resolver.py -q --tb=short

test-p10b-routing:
	cd backend && APP_ENV=testing python3 -m pytest tests/integration/test_llm_stage_routing_turn.py -q --tb=short

test-p10b-debug:
	cd backend && APP_ENV=testing python3 -m pytest tests/integration/test_llm_stage_routing_turn.py -q -k "debug" --tb=short

test-p10b-fast: test-p10b-resolver test-p10b-routing

test-p10b:
	$(MAKE) test-p10b-fast
	cd frontend && npm run build
	cd frontend && npm run lint
	cd frontend && npx tsc --noEmit

# === P10-C: Story Editor & NPC Memory-First ===

# Feature flags required for P10-C Memory-first & Story Instance behavior.
# Each test target activates the relevant flags explicitly so that
# the P10-C gate passes even with the flags defaulting to false in production.
P10C_PACKAGE_FLAGS = STORY_PACKAGE_INSTANCE_ENABLED=true STORY_EDITOR_ENABLED=true
P10C_MEMORY_FLAGS  = NPC_MEMORY_FIRST_ENABLED=true INSTANCE_SNAPSHOT_ENABLED=true
P10C_FLAGS         = $(P10C_PACKAGE_FLAGS) $(P10C_MEMORY_FLAGS)

test-p10c-npc-memory-unit:
	cd backend && APP_ENV=testing $(P10C_MEMORY_FLAGS) python3 -m pytest \
		tests/unit/test_p10c_npc_memory_schema.py \
		tests/unit/test_p10c_npc_memory_retrieval.py \
		tests/unit/test_p10c_npc_decision_adapter.py \
		-q --tb=short

test-p10c-story-editor-unit:
	cd backend && APP_ENV=testing $(P10C_FLAGS) python3 -m pytest \
		tests/unit/test_p10c_story_editor_fields.py \
		tests/unit/test_p10c_story_editor_gaps.py \
		tests/unit/test_p10c_schema_foundation.py \
		-q --tb=short

test-p10c-content-pack-unit:
	cd backend && APP_ENV=testing $(P10C_PACKAGE_FLAGS) python3 -m pytest \
		tests/unit/test_p10c_content_pack_version_manifest.py \
		tests/unit/test_p10c_hallucination_leak_hardening.py \
		-q --tb=short

test-p10c-integration:
	cd backend && APP_ENV=testing $(P10C_FLAGS) python3 -m pytest \
		tests/integration/test_p10c_npc_memory_integration.py \
		tests/integration/test_p10c_content_pack_publish_bridge.py \
		tests/integration/test_p10c_story_package_instance_api.py \
		-q --tb=short

test-p10c-fast: test-p10b-fast test-p10c-npc-memory-unit test-p10c-story-editor-unit test-p10c-content-pack-unit test-p10c-integration

test-p10c:
	$(MAKE) test-p10c-fast
	cd frontend && npm run build
	cd frontend && npm run lint
	cd frontend && npx tsc --noEmit

test-p10c-gate: test-p10c
	@echo "P10-C quality gate passed"

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
