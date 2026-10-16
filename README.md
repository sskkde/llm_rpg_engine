# LLM RPG Engine - Perspective-Aware Memory System

> **版本与路线说明**：本仓库当前源码与下方运行说明描述的是 **V1 当前实现**，不代表新目标已实现。当前选定的演进目标是 **Python（FastAPI）游戏后端 + Next.js Web 前端**，按四阶段路线推进；设计基线与阶段路线见 [RFC（LLM RPG Engine 设计总结）](docs/design/llm_rpg_engine_design_summary_2026-10-08.md) 和[路线图草案](docs/design/roadmap-draft.md)。[旧 DSH V2 文档](docs/v2_dsh_rpg_engine.md)仅作已被替代的历史记录，不是当前目标或唯一权威入口。阶段实测不变量及未完成项见[回合恢复与不变量](backend/docs/RECOVERY_AND_INVARIANTS.md)。

A narrative RPG engine powered by LLMs with a perspective-aware memory system. This system maintains world consistency, prevents NPC omniscience, and supports long-term narrative generation through a sophisticated event sourcing architecture.

## Architecture Overview

The system follows a modular architecture designed for narrative coherence:

```
Perspective-Aware Memory System
├── Event Log          # Historical fact source (append-only)
├── Canonical State    # Current fact source (structured state)
├── Perspective Layer  # Information filtering by viewpoint
├── NPC Memory Scope   # Per-NPC memory and beliefs
├── Lore Store         # World-building and settings
├── Summary System     # Context compression
├── Retrieval System   # Hybrid search and filtering
├── Context Builder    # LLM context assembly
├── Action Scheduler   # Turn processing and conflict resolution
├── Validator          # Output validation before commit
└── Memory Writer      # Post-commit memory persistence
```

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15+ with pgvector extension (or use SQLite for testing)
- Redis 7+ (optional, for caching)
- Node.js 20+ (for frontend)

### 1. Clone and Setup

```bash
cd llm_rpg_engine

# Backend setup
cd backend
pip install -r requirements.txt

# Frontend setup
cd ../frontend
npm install
```

### 2. Environment Configuration

Copy the example environment file and configure:

```bash
cd backend
cp .env.example .env
```

Edit `.env` with your settings (see Environment Variables section below).

### 3. Start Infrastructure (Docker Compose)

```bash
# From project root
docker-compose up -d

# This starts:
# - PostgreSQL with pgvector on port 5432
# - Redis on port 6379
```

### 4. Run Database Migrations

```bash
cd backend
alembic upgrade head

# Seed world content
python -m llm_rpg.scripts.seed_content
```

### 5. Start the Backend

```bash
cd backend
uvicorn llm_rpg.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

Interactive documentation (Swagger UI) is at `http://localhost:8000/docs`

### 6. Start the Frontend

```bash
cd frontend
npm run dev
```

The frontend will be available at `http://localhost:3000`

## Project Structure

```
llm_rpg_engine/
├── backend/
│   ├── llm_rpg/
│   │   ├── main.py              # FastAPI application entrypoint
│   │   ├── config/seeds/        # World content seeds
│   │   ├── models/              # Pydantic data models
│   │   ├── core/                # Core systems (state, memory, retrieval)
│   │   ├── engines/             # Game engines (world, NPC, narration)
│   │   ├── storage/             # Database layer (SQLAlchemy, Redis)
│   │   ├── llm/                 # LLM integration (OpenAI, mock provider)
│   │   ├── api/                 # API routes (auth, game, admin, debug)
│   │   └── scripts/             # Utility scripts (seed_content)
│   ├── tests/                   # Test suite (pytest)
│   ├── alembic/                 # Database migrations
│   ├── requirements.txt
│   └── .env.example
├── frontend/                    # Next.js frontend application
├── docker-compose.yml           # Infrastructure services
└── doc/                         # Documentation
```

## Runtime Entrypoint

**The only supported runtime entrypoint is `llm_rpg.main:app`.**

```bash
# Correct way to run the server
uvicorn llm_rpg.main:app --reload --port 8000
```

### Legacy File Status

The file `backend/app.py` has been renamed to `backend/app_legacy.py` and is **deprecated**. It contains:
- A deprecation notice at the top
- Legacy demo code for reference only
- No active API routes

Do not use `uvicorn app:app` or any imports from `app.py`. All functionality has been migrated to the modular architecture under `llm_rpg/`.

## Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Database Configuration
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/llm_rpg

# For testing (uses SQLite instead of PostgreSQL)
TEST_DATABASE_URL=sqlite:///./test.db

# Redis Configuration (optional, for caching)
REDIS_URL=redis://localhost:6379/0

# OpenAI Configuration (required for production LLM calls)
OPENAI_API_KEY=your-openai-api-key-here

# Application Settings
APP_ENV=development          # development, testing, production
LOG_LEVEL=INFO               # DEBUG, INFO, WARNING, ERROR

# JWT Secret (generate a secure random string for production)
SECRET_KEY=your-secret-key-here

# CORS Origins (comma-separated for production)
CORS_ORIGINS=http://localhost:3000,http://localhost:8000
```

## Docker Compose Services

The `docker-compose.yml` file provides:

### PostgreSQL with pgvector
- **Image**: `ankane/pgvector:latest`
- **Port**: 5432
- **Database**: `llm_rpg`
- **User**: `postgres` / `postgres`
- **Features**: Full pgvector extension for vector embeddings
- **Volume**: `postgres_data` (persistent storage)
- **Healthcheck**: Automatic health monitoring

### Redis
- **Image**: `redis:7-alpine`
- **Port**: 6379
- **Persistence**: Append-only file (AOF) enabled
- **Volume**: `redis_data` (persistent storage)
- **Healthcheck**: Automatic health monitoring

### Starting Services

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Stop and remove volumes (WARNING: deletes data)
docker-compose down -v
```

## API Overview

### Production vs Legacy Endpoints

**IMPORTANT**: The API has two categories of endpoints:

1. **Production Endpoints** (database-backed, persisted): Use these for all production workloads
2. **Legacy Dev Endpoints** (in-memory, `/dev/*` prefix): Only for development/testing, NOT persisted

The legacy `/dev/*` endpoints are marked as DEPRECATED and use in-memory state that is lost on server restart. They are kept for backward compatibility with legacy tests only.

### Authentication
- `POST /auth/register` - Register new user
- `POST /auth/login` - Login and receive JWT token
- `GET /auth/me` - Get current user info

### Save Management
- `POST /saves` - Create new save slot
- `GET /saves` - List user's save slots
- `GET /saves/{id}` - Get save slot details
- `PUT /saves/{id}` - Update save slot
- `DELETE /saves/{id}` - Delete save slot
- `POST /saves/manual-save` - Create manual save

### Game Sessions
- `GET /sessions` - List user's sessions
- `GET /sessions/{id}/snapshot` - Get session state
- `POST /sessions/{id}/load` - Load session

### Gameplay
- `POST /game/sessions/{session_id}/turn` - Execute turn
- `POST /game/sessions/{session_id}/replay` - Replay turns
- `GET /game/sessions/{session_id}/audit-log` - Get audit log

### Streaming
- `POST /streaming/sessions/{id}/turn` - Stream turn execution (SSE)
- `POST /streaming/sessions/{id}/turn/mock` - Mock provider streaming

### Combat
- `POST /combat/start` - Start combat session
- `GET /combat/{id}` - Get combat state
- `POST /combat/{id}/turn` - Submit combat action
- `POST /combat/{id}/end` - End combat

### World
- `GET /world/state` - Get complete world state
- `GET /world/summary` - Get content counts
- `GET /world/chapters/{id}` - Get chapter details
- `GET /world/locations/{id}` - Get location details

### Admin (requires admin role)
- `GET /admin/worlds`, `PATCH /admin/worlds/{id}`
- `GET /admin/chapters`, `PATCH /admin/chapters/{id}`
- `GET /admin/locations`, `PATCH /admin/locations/{id}`
- `GET /admin/npc-templates`, `PATCH /admin/npc-templates/{id}`
- `GET /admin/item-templates`, `PATCH /admin/item-templates/{id}`
- `GET /admin/quest-templates`, `PATCH /admin/quest-templates/{id}`
- `GET /admin/event-templates`, `PATCH /admin/event-templates/{id}`
- `GET /admin/prompt-templates`, `PATCH /admin/prompt-templates/{id}`

### Debug (requires admin role)
- `GET /debug/sessions/{id}/logs` - Session event logs
- `GET /debug/sessions/{id}/state` - Complete state snapshot
- `GET /debug/model-calls` - LLM audit logs
- `GET /debug/errors` - Recent errors
- `POST /debug/sessions/{id}/replay` - Replay with perspective filtering
- `POST /debug/sessions/{id}/snapshots` - Create state snapshots

### Media API v1 (P6)

The Media API provides asset generation, caching, and retrieval for game content:

- `POST /media/portraits/generate` - Generate NPC portrait (returns AssetResponse)
- `POST /media/scenes/generate` - Generate scene background image (returns AssetResponse)
- `POST /media/bgm/generate` - Generate background music (returns AssetResponse)
- `GET /media/assets/{asset_id}` - Retrieve generated asset by ID
- `GET /media/sessions/{session_id}/assets` - List all assets for a session

**Asset Types**: `portrait`, `scene`, `bgm`

**Generation Status**: `pending`, `processing`, `completed`, `failed`

**Mock Provider**: Development and testing use `MockAssetProvider` which returns deterministic placeholder URLs. Set `ASSET_PROVIDER=mock` explicitly, or leave unset for automatic mock selection. Real external providers (DALL-E, Stable Diffusion) are deferred to P7.

**Caching**: Assets are deduplicated by cache key (SHA-256 hash of type + prompt + optional metadata). Identical requests return cached results.

## LLM Provider Configuration

The system supports multiple LLM providers with automatic fallback:

### OpenAI Provider (Production)

Requires `OPENAI_API_KEY` environment variable:

```bash
export OPENAI_API_KEY=sk-...
```

The OpenAI provider is used when:
- `OPENAI_API_KEY` is set and valid
- `APP_ENV` is `production` or `development`

### Mock Provider (Testing)

The MockLLMProvider is automatically used when:
- `OPENAI_API_KEY` is not set
- `APP_ENV` is `testing`
- Tests explicitly request mock provider

The mock provider returns predictable responses based on prompt content patterns:
- "narration" or "describe" -> narrative text
- "npc" or "decision" -> JSON action
- "intent" or "parse" -> JSON intent

### Provider Selection

```python
from llm_rpg.llm import LLMService

# Automatic selection based on environment
service = LLMService()

# Explicit mock provider
service = LLMService(use_mock=True)
```

## Testing

### Run All Tests

```bash
cd backend
pytest -q
```

### V1 Release Gate

The V1.0 release gate is the blocking quality gate for production:

```bash
make test-v1-release
```

This runs all V1 component tests, previous phase gates, and frontend static checks. See `doc/testing_strategy.md` for the full test pyramid and gate definitions.

### Run Specific Test Suites

```bash
# Integration tests
pytest tests/integration/ -q

# Unit tests
pytest tests/unit/ -q

# Specific test file
pytest tests/integration/test_auth_saves.py -q
```

### Test Environment

Tests use SQLite in-memory database for fast execution. No PostgreSQL or Redis required for testing.

```bash
# Tests automatically use APP_ENV=testing
APP_ENV=testing pytest -q
```

## Key Features

### 1. Event Sourcing
All game actions are recorded as immutable events. This enables complete history replay, state reconstruction, and debugging.

### 2. Perspective-Aware Information
Each entity has an independent perspective:
- **World Perspective**: Sees everything (world engine)
- **Player Perspective**: Only sees what the player experienced
- **NPC Perspective**: Based on individual knowledge and beliefs
- **Narrator Perspective**: Filters hidden information from output

### 3. NPC Memory System
NPCs maintain:
- **Episodic Memory**: Personal experiences
- **Semantic Memory**: Known facts
- **Belief State**: Subjective understanding
- **Secrets**: Hidden information
- **Forget Curve**: Memory decay over time

### 4. Lore Management
World content filtered by perspective:
- **Canonical Lore**: True version
- **Public Lore**: Common knowledge
- **Rumor Lore**: Unverified information
- **Hidden Lore**: Secret information

## Development Workflow

### Adding New Features

1. Write tests first (TDD)
2. Implement in appropriate module (`core/`, `api/`, etc.)
3. Update API routes if needed
4. Run full test suite
5. Update documentation

### Database Migrations

```bash
# Create new migration
cd backend
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one version
alembic downgrade -1
```

### Seeding Content

```bash
# Seed world content (idempotent)
cd backend
python -m llm_rpg.scripts.seed_content
```

This creates:
- 1 world (修仙试炼世界)
- 3 chapters
- 10 locations
- 6 NPCs with hidden identities
- 7 items
- 4 quests with 11 steps
- 6 event templates
- 5 prompt templates
- 3 endings

## Design Principles

1. **Event Sourcing**: History is immutable and append-only
2. **CQRS**: Separate read and write models
3. **Perspective Isolation**: NPCs cannot know what they should not
4. **Validation Before Commit**: LLM output verified before affecting state
5. **Memory Decay**: NPCs forget less important details over time

## Troubleshooting

### Database Connection Issues

```bash
# Verify PostgreSQL is running
docker-compose ps

# Check logs
docker-compose logs postgres

# Reset database (WARNING: destroys data)
docker-compose down -v
docker-compose up -d
alembic upgrade head
```

### Import Errors

```bash
# Ensure PYTHONPATH includes backend
cd backend
export PYTHONPATH=/path/to/backend:$PYTHONPATH
pytest -q
```

### LLM API Issues

The system will automatically fall back to the mock provider if:
- `OPENAI_API_KEY` is not set
- The API key is invalid
- Rate limits are exceeded

Check the logs for provider selection messages.

## P3 Quality Gate

This project has completed the P3 Engineering Quality Gate with deferred frontend unit test gate, establishing automated testing infrastructure and documentation.

### Quick Test Commands

The `Makefile` in the repository root provides unified test commands:

```bash
# Show all available targets
make help

# Run full P3 quality gate (backend + frontend static + combat)
make test-p3

# Run backend tests only
make test-backend

# Run frontend static checks (lint + typecheck)
make test-frontend-static

# Run frontend combat tests (stable subset)
make test-frontend-combat

# Run full frontend unit tests (deferred - known failures)
make test-frontend-unit

# Run scenario smoke tests (8 core tests)
make test-scenario-smoke

# Run pgvector tests (requires PostgreSQL with pgvector extension)
make test-pgvector

# Run V1 release gate (complete V1.0 quality gate)
make test-v1-release
```

### CI Pipeline

The project includes a GitHub Actions CI workflow (`.github/workflows/ci.yml`) that runs automatically on push and pull requests:

- **backend-tests**: Runs backend unit and integration tests + scenario smoke
- **frontend-tests**: Runs frontend static checks (lint + typecheck) and stable combat tests
- **frontend-unit-tests**: Runs full frontend unit tests (non-blocking, known failures)
- **pgvector-tests**: Runs pgvector-specific tests against PostgreSQL
- **v1-release-tests**: Runs V1 release gate + P8 regression + frontend build/lint/tsc (blocking)

The CI workflow calls Makefile targets for consistency with local development.

### Known Test Issues

| Area | Status | Notes |
|------|--------|-------|
| Backend tests | 1664 passed, 8 skipped | pgvector tests skipped in default SQLite path |
| Frontend static (lint + tsc) | All pass | Clean compilation - blocking gate |
| Frontend combat tests | 21 passed | CombatPanel.test.tsx - blocking gate |
| Frontend unit tests (full) | 89/113 pre-existing failures | Deferred to P4+ - test environment issues, not application bugs |
| pgvector tests | 8/8 pass | Requires PostgreSQL with pgvector extension |

### P4+ Deferred Items

The following features are explicitly out of scope for P3-QG and deferred to future phases:

- Frontend unit test environment fixes (89 failing tests)
- Factions/plot_beats schema extensions
- Media generation (portraits, scenes, BGM)
- ReplayEngine rewrite or turn service major refactoring
- Real OpenAI/LLM integration for tests
- New API routes or frontend routing changes

For detailed status, see `IMPLEMENTATION_STATUS.md` and `P3_COMPLETION_REPORT.md`.

## P4 Content Productization

This phase adds content productization infrastructure: structured content packs, Faction/PlotBeat persistence, Admin content editing, scenario regression testing, and replay reports.

### Quick Test Commands

```bash
# Show all available targets
make help

# Run full P4 quality gate
make test-p4

# Run content pack validation
make test-content

# Run admin content API tests
make test-admin-content

# Run scenario regression tests
make test-scenario-regression

# Run replay report tests
make test-replay-report

# Run admin UI tests
make test-frontend-admin
```

### Content Pack Commands

Content packs are structured YAML directories for game content:

```bash
# Validate a content pack
cd backend
python -m llm_rpg.scripts.validate_content_pack ../content_packs/qinglan_xianxia

# Validate with JSON output
python -m llm_rpg.scripts.validate_content_pack ../content_packs/qinglan_xianxia --format json

# Import a content pack (dry-run preview)
python -m llm_rpg.scripts.import_content_pack ../content_packs/qinglan_xianxia --dry-run

# Import a content pack
python -m llm_rpg.scripts.import_content_pack ../content_packs/qinglan_xianxia
```

### Admin Content API Endpoints

New Admin API endpoints require admin role authentication:

#### Factions
- `GET /admin/factions` - List all factions
- `GET /admin/factions/{id}` - Get faction details
- `PATCH /admin/factions/{id}` - Update faction

#### Plot Beats
- `GET /admin/plot-beats` - List all plot beats
- `GET /admin/plot-beats/{id}` - Get plot beat details
- `PATCH /admin/plot-beats/{id}` - Update plot beat

#### Content Packs
- `POST /admin/content-packs/validate` - Validate content pack at path
- `POST /admin/content-packs/import` - Import content pack (supports `?dry_run=true`)

### Admin UI

New admin pages are available at:
- `/admin` → Factions tab
- `/admin` → Plot Beats tab
- `/admin` → Content Packs tab

The Content Packs panel provides a workflow: enter path → validate → dry-run preview → import with confirmation.

### Content Pack Structure

Content packs are YAML directories with the following structure:

```
content_packs/qinglan_xianxia/
├── pack.yaml           # Manifest (id, name, version, dependencies)
├── worlds.yaml         # World definitions
├── locations.yaml      # Location definitions
├── npcs.yaml           # NPC templates
├── quests.yaml         # Quest definitions
├── items.yaml          # Item templates
├── factions.yaml       # Faction definitions
├── plot_beats.yaml     # Plot beat triggers
├── prompts.yaml        # LLM prompt templates
├── rules.yaml          # Game rule configurations
└── README.md           # Pack documentation
```

### Condition and Effect Whitelists

Plot beat conditions and effects use a whitelist approach (no arbitrary code execution):

**Conditions**: `fact_known`, `state_equals`, `state_in`, `quest_stage`, `npc_present`, `location_is`

**Effects**: `add_known_fact`, `advance_quest`, `set_state`, `emit_event`, `change_relationship`, `add_memory`

### P4 Deferred Items

The following features were explicitly out of scope for P4:

- **Media generation**: ~~Portrait, scene, and BGM async generation~~ → **Implemented in P6** (Media API v1)
- **Async job infrastructure**: Celery, RQ, Temporal, or similar → Deferred to P7
- **Engine refactoring**: ReplayEngine or Turn Orchestrator major rewrites → Deferred to P7+
- **Real LLM in tests**: Default tests must not require real OpenAI API → Deferred to P7+
- **Arbitrary expressions**: Plot beat conditions must use whitelist only → Completed

For detailed status, see `IMPLEMENTATION_STATUS.md`, `P4_EXECUTION_STATUS.md`, and `P4_COMPLETION_REPORT.md`.

## P5 Debug/Test/Replay Productization

This phase adds complete frontend UIs for all 14 debug endpoints, P2 memory and perspective module strengthening, and expanded scenario testing with 12 scenario types.

### Quick Test Commands

```bash
# Show all available targets
make help

# Run P5 quality gate components
make test-scenario-p5
make test-prompt-inspector

# Run P2 strengthening tests
cd backend
python3 -m pytest tests/unit/test_audit_db_persistence.py tests/unit/test_context_builder_p2.py tests/unit/test_narration_leak_hardening.py -q
```

### Debug Panel UI

The debug panel provides a comprehensive view of game session internals:

**Location**: `/zh/debug` or `/en/debug`

**Tabs**:
- **Logs**: Session event logs with filtering
- **State**: Complete session state snapshot
- **Timeline**: Turn-by-turn event timeline
- **NPC Mind**: NPC beliefs, memories, secrets, and goals
- **Turn Debug**: Per-turn debug information
- **Prompt Inspector**: LLM request/response details with tokens, cost, latency

### Replay Tool UI

The replay tool enables session replay with perspective filtering:

**Location**: `/zh/replay` or `/en/replay`

**Features**:
- Session ID input with load
- Turn range selection (start turn, end turn)
- Perspective selector (admin / player / auditor)
- State diff viewer (before/after comparison)
- Replay report generation

### Prompt Inspector API

New debug endpoints for LLM call inspection:

- `GET /debug/sessions/{id}/prompt-inspector` - Aggregated prompt data for a session
- `GET /debug/sessions/{id}/turns/{turn_no}` - Enhanced with prompt template info

**Query Parameters**:
- `start_turn`, `end_turn` - Turn range filter
- `prompt_type` - Filter by prompt type (narration, npc_decision, etc.)

### Scenario Types

12 scenario types for comprehensive testing:

**Existing (P4)**:
- `SECRET_LEAK_PREVENTION` - NPC secret leak verification
- `IMPORTANT_NPC_ATTACK` - Important NPC attack handling
- `SEAL_COUNTDOWN` - Seal countdown mechanics
- `FORBIDDEN_KNOWLEDGE` - Forbidden knowledge access

**New (P5)**:
- `COMBAT_RULE_ENFORCEMENT` - Combat rule verification
- `QUEST_FLOW_VALIDATION` - Quest stage transition validation
- `SAVE_CONSISTENCY` - Save/load state consistency
- `REPRODUCIBILITY` - Same seed same result
- `WORLD_TIME_PROGRESSION` - World time advancement
- `AREA_SUMMARY_GENERATION` - Area summary updates
- `NPC_RELATIONSHIP_CHANGE` - Relationship tracking
- `INTEGRATION_FULL_TURN` - Full turn pipeline

### P2 Strengthening

P5 strengthens existing P2 modules:

**AuditStore DB Persistence**:
- LLM model calls now persist to PostgreSQL
- Survives backend restart
- Migration: `011_add_model_call_audit_logs.py`

**NPCContextBuilder**:
- `build_npc_decision_context()` - Complete NPC decision context
- `get_npc_perspective_facts()` - Perspective-filtered facts
- `get_npc_available_actions()` - NPC action availability

**NarrationLeakValidator**:
- Edge case handling (empty, None, long strings, special characters)
- Severity levels (EXACT_MATCH, PARTIAL_MATCH, SUSPICIOUS)
- Forbidden pattern support

### P5 Deferred Items

The following features were explicitly out of scope for P5:

- **Media generation**: ~~Portrait, scene, and BGM async generation~~ → **Implemented in P6** (Media API v1)
- **Async job infrastructure**: Celery, RQ, Temporal, or similar → Deferred to P7
- **Full AuditStore persistence**: Only model_calls persisted; context_builds, validations, etc. remain in-memory → Phase 1 completed in P5
- **ForgetCurve background decay**: Memory decay background job → Deferred to P7+
- **Semantic leak detection**: Embedding-based leak detection → Deferred to P7+
- **Engine refactoring**: ReplayEngine or Turn Orchestrator major rewrites → Deferred to P7+

For detailed status, see `IMPLEMENTATION_STATUS.md`, `P5_COMPLETION_REPORT.md`, and `P5_READINESS.md`.

## P6 Media Asset Infrastructure

This phase adds the Media API v1 infrastructure for asset generation, caching, and retrieval, replacing the 501 placeholder endpoints.

### Quick Test Commands

```bash
# Show all available targets
make help

# Run P6 quality gate (fast)
make test-p6-fast

# Run P6 quality gate (full)
make test-p6

# Run frontend asset component tests
cd frontend
npm test -- __tests__/assets
```

### Media API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/media/portraits/generate` | POST | Generate NPC portrait |
| `/media/scenes/generate` | POST | Generate scene background |
| `/media/bgm/generate` | POST | Generate background music |
| `/media/assets/{asset_id}` | GET | Retrieve asset by ID |
| `/media/sessions/{session_id}/assets` | GET | List session assets |

### Mock Asset Provider

Development and testing use `MockAssetProvider` which returns deterministic placeholder URLs. The mock provider:

- Returns consistent results for identical inputs
- Does not require external API keys
- Enables fast test execution
- Can be swapped for real providers (DALL-E, Stable Diffusion) in P7

Set `ASSET_PROVIDER=mock` explicitly, or leave unset for automatic mock selection.

### Asset Components

Frontend components for displaying generated assets:

- `NPCPortrait` - Displays NPC portrait with emoji placeholder
- `SceneBackground` - Displays scene background with gradient placeholder
- `BGMControl` - BGM play/pause control
- `AssetFallback` - Unified loading/error/empty state

### P7 Deferred Items

The following features are explicitly out of scope for P6 and deferred to future phases:

- **Real external providers**: DALL-E, Stable Diffusion, audio synthesis
- **Async job infrastructure**: Celery, RQ, Temporal, or similar
- **Real rendering**: Currently placeholder URLs only
- **Game page integration**: Asset components not yet wired to game session
- **ForgetCurve background decay**: Memory decay background job

For detailed status, see `IMPLEMENTATION_STATUS.md`, `P6_COMPLETION_REPORT.md`, and `P6_READINESS.md`.

## P7 Media Productization + Async Runtime

This phase extends P6 infrastructure to production-ready async runtime with job tracking, polling hooks, and game page integration.

### Quick Test Commands

```bash
# Show all available targets
make help

# Run P7 quality gate (fast)
make test-p7-fast

# Run P7 quality gate (full)
make test-p7

# Run P7 scenario tests
make test-scenario-p7

# Run frontend asset job tests
cd frontend
npm test -- __tests__/assets/useAssetJob.test.tsx
```

### Async Job Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/media/jobs/portraits` | POST | Create portrait generation job |
| `/media/jobs/scenes` | POST | Create scene generation job |
| `/media/jobs/bgm` | POST | Create BGM generation job |
| `/media/jobs/{job_id}` | GET | Get job status |
| `/media/sessions/{session_id}/jobs` | GET | List session jobs |
| `/media/jobs/{job_id}/retry` | POST | Retry failed job |
| `/media/jobs/{job_id}/cancel` | POST | Cancel pending job |

### P6 Compat Mode

Existing P6 endpoints now support `?mode=sync|async`:
- `POST /media/portraits/generate?mode=async` → Returns `AssetJobResponse` for polling
- `POST /media/portraits/generate?mode=sync` → Returns `AssetResponse` immediately (default)

### useAssetJob Hook

Frontend polling hook for async job tracking:

```typescript
const { job, isLoading, error, isPolling, retry, cancel, refetch } = useAssetJob({
  jobId: "job-123",
  pollInterval: 2000,
  onCompleted: (job) => console.log("Done:", job),
  onFailed: (job) => console.log("Failed:", job),
});
```

### Game Page Integration

Asset components are now integrated into the game session page:
- **SceneBackground**: Displays scene background based on current location
- **BGMControl**: BGM control in game header

### Debug Asset Job Endpoints

Admin-only endpoints for job management:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/debug/assets/jobs` | GET | List all jobs (paginated) |
| `/debug/assets/jobs/{job_id}` | GET | Get job debug info |
| `/debug/sessions/{session_id}/asset-jobs` | GET | List session jobs |
| `/debug/assets/jobs/{job_id}/retry` | POST | Retry failed job |
| `/debug/assets/jobs/{job_id}/cancel` | POST | Cancel pending job |

### P8 Deferred Items

The following features are explicitly out of scope for P7 and deferred to future phases:

- **Real external providers**: DALL-E/Stable Diffusion with real API calls
- **Production queue**: Celery/RQ/Temporal with worker processes
- **NPCPortrait integration**: Game page NPC portrait display
- **Cost tracking**: Per-session and per-user cost metrics
- **Rate limiting**: API rate limits for generation endpoints

For detailed status, see `IMPLEMENTATION_STATUS.md`, `P7_COMPLETION_REPORT.md`, and `P7_READINESS.md`.

## P8 Production Asset Runtime + Provider Integration

This phase upgrades P7 infrastructure to production-grade with provider registry, real OpenAI DALL-E adapter, queue abstraction, cost tracking, rate limiting, and richer NPC portrait integration.

### Quick Test Commands

```bash
# Show all available targets
make help

# Run P8 quality gate (fast)
make test-p8-fast

# Run P8 quality gate (full)
make test-p8

# Run P8 scenario tests
make test-scenario-p8

# Run frontend P8 asset tests
cd frontend
npm test -- __tests__/assets/NPCPortrait.p8.test.tsx
```

### Key Features

- **Provider Registry**: Capability metadata for all providers, health checks without real API calls
- **OpenAI DALL-E Adapter**: Real client abstraction with Fake/Real client injection, no secrets in logs
- **Queue Backend**: Protocol + in-process implementation, RQ/Celery shells for P9
- **Lease/Heartbeat**: Job lease with heartbeat, stale recovery, dead-letter handling
- **Worker CLI**: `python -m llm_rpg.scripts.asset_worker --once/--loop/--batch-size`
- **Cost Tracking**: Per-job usage recording, cost summary API, session/user/provider queries
- **Rate Limiting**: Per-user/per-session/per-provider limits, 429 with Retry-After header
- **NPC Portrait Context**: Prompt includes NPC name, mood, personality, location, narration
- **Portrait Pre-generation**: Cache-first prewarm for current location NPCs
- **Admin Audit APIs**: Phase 2 read endpoints with pagination and filtering

### Provider Registry Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/debug/assets/providers` | GET | List provider capabilities |
| `/debug/assets/providers/{name}/health` | GET | Individual provider health |
| `/debug/assets/usage` | GET | List usage logs (paginated) |
| `/debug/assets/usage/summary` | GET | Aggregated cost summary |
| `/debug/assets/rate-limit-events` | GET | List rate limit events |

### Portrait Prewarm Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/media/sessions/{id}/prewarm-portraits` | POST | Trigger pre-generation for location NPCs |
| `/media/sessions/{id}/prewarm-status` | GET | Get pre-generation status |

### Admin Audit Endpoints (Phase 2)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/audit/sessions/{id}/logs` | GET | Session event logs (paginated) |
| `/admin/audit/sessions/{id}/model-calls` | GET | LLM call history |
| `/admin/audit/sessions/{id}/errors` | GET | Error log |
| `/admin/audit/export` | GET | Export session audit (JSONL) |

### Debug UI Components

New debug components available in the debug page:
- **AssetQueueViewer**: Job queue with lease/dead-letter status, retry/cancel actions
- **AssetUsageViewer**: Usage logs with cost summary, provider/session filters
- **ProviderHealthViewer**: Provider cards with enabled/configured status
- **RateLimitViewer**: Rate limit events with allowed/denied badges

### P9 Deferred Items

The following features are explicitly out of scope for P8 and deferred to future phases:

- **Celery/RQ production queue**: Distributed workers with real task queue
- **Real audio generation**: Music synthesis API for BGM and SFX
- **SFX asset type support**: Sound effects beyond BGM
- **CDN/S3 deployment**: Production asset storage and delivery
- **Real DALL-E integration tests**: End-to-end with recorded responses
- **Redis-based rate limiting**: Multi-process shared state
- **ForgetCurve background decay**: Automatic memory decay job

For detailed status, see `IMPLEMENTATION_STATUS.md`, `P8_COMPLETION_REPORT.md`, and `P8_READINESS.md`.

## P9 V1.0 Release Readiness

This phase delivers the V1.0 release with a complete rule engine, playable UX, production operations infrastructure, and comprehensive release test gate.

### Quick Test Commands

```bash
# Show all available targets
make help

# Run V1 release gate (blocking)
make test-v1-release

# Run V1 component gates
make test-v1-rule-engine
make test-v1-game-ui
make test-v1-ops
make test-v1-playthrough

# Run previous phase gates (no regression)
make test-p8-fast
make test-p8
```

### Key Features

- **Rule Engine Formalization**: MovementValidator, QuestValidator, ItemRules, SkillRules, ActionSchema (16 action types), StateDeltaResolver, ConflictResolver (5 scenarios)
- **Playable UX**: 4 Player APIs (Quests/Inventory/Relationships/Locations), 4 Frontend panels, Settings Panel, Streaming Turn UI with 9 event types
- **Production Operations**: Dockerfiles, nginx SSL, docker-compose.prod.yml, Admin Health/Metrics/Release-Readiness APIs
- **Release Test Gate**: CI V1 release gate, Frontend test debt audit, 30-60 min playthrough scenario

### Player API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/player/sessions/{id}/quests` | GET | Player-visible quest list |
| `/player/sessions/{id}/inventory` | GET | Player inventory |
| `/player/sessions/{id}/relationships` | GET | Player-known NPC relationships |
| `/player/sessions/{id}/locations` | GET | Player-discovered locations |

All endpoints apply PerspectiveService filtering to exclude hidden information.

### Frontend Panels

- **QuestJournalPanel**: Quest tracking with stage progress
- **InventoryPanel**: Item management with category filter
- **LocationMapPanel**: Discovered locations with movement paths
- **RelationshipPanel**: NPC relationship scores with progress bars
- **SettingsPanel**: BGM volume, text speed, auto-save toggle

### Rule Engine Components

| Component | File | Purpose |
|-----------|------|---------|
| MovementValidator | `core/validation/movement_validator.py` | Path blocking, access rules, stamina |
| QuestValidator | `core/validation/quest_validator.py` | Stage transitions, prerequisites |
| ItemRules | `rules/item_rules.py` | Use/give/take validation, effects |
| SkillRules | `rules/skill_rules.py` | Cast validation, effect resolution |
| ActionSchema | `rules/action_schema.py` | 16 action type definitions |
| StateDeltaResolver | `core/state_delta_resolver.py` | Delta generation for 7 action types |
| ConflictResolver | `core/conflict_resolver.py` | 5 conflict resolution scenarios |

### Admin Operations Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/health` | GET | DB, Redis, Provider health status |
| `/admin/metrics` | GET | API latency, LLM calls, turn stats |
| `/admin/release-readiness` | GET | Migration, content, env var status |

### Documentation

| Doc | Content |
|-----|---------|
| `docs/deployment.md` | Docker Compose, VPS, cloud deployment |
| `docs/operations.md` | Health checks, troubleshooting, migrations |
| `docs/security.md` | Auth mechanism, API key safety, CORS |
| `docs/backup.md` | PostgreSQL backup, content pack backup |
| `docs/release_checklist.md` | Pre-release checklist (15+ items) |
| `docs/rule_engine_spec.md` | Rule engine specification |
| `docs/v1_playthrough_script.md` | 8-phase playthrough script |

### V1.0 Release Status: COMPLETE

All Must Have items complete. All test gates pass. Ready for production deployment.

For detailed status, see `V1_COMPLETION_REPORT.md` and `V1_READINESS.md`.

## P10-A: Immersion & Provider Routing

This phase adds four experience/architecture modules: SSE stage progress events, minute-precision dynamic world time, quest anti-spoiler gating, and per-asset-type provider routing.

### Quick Test Commands

```bash
# Show all available targets
make help

# Run P10-A quality gate (fast)
make test-p10a-fast

# Run P10-A quality gate (full)
make test-p10a

# Verify no regression
make test-v1-release
```

### Key Features

- **SSE Stage Progress Events**: Real-time stage updates during turn execution via `stage_started` and `stage_completed` events
- **TurnStageStatus Component**: Frontend component replacing static "故事展开中" with dynamic stage labels
- **Dynamic World Time**: Minute-precision time with hour/minute fields (辰时 → 08:35)
- **TimeAdvanceValidator**: Enforces per-action time ranges (inspect: 1-5 min, dialogue: 3-15 min, movement: 5-180 min)
- **Quest Anti-Spoiler Gating**: Hidden quests excluded from Player API until discovered
- **Per-Asset-Type Provider Routing**: PORTRAIT → IMAGE → DEFAULT → mock fallback chain
- **Debug Endpoint**: `GET /debug/assets/providers/resolved` for provider inspection

### New SSE Events

| Event | Description |
|-------|-------------|
| `stage_started` | Turn stage begins (e.g., NPC 思考中……) |
| `stage_completed` | Turn stage finishes |

### New Environment Variables

```bash
# Asset Provider Configuration
ASSET_PROVIDER_DEFAULT=mock          # Global fallback
ASSET_PROVIDER_IMAGE=mock            # Image category (portrait, scene)
ASSET_PROVIDER_PORTRAIT=mock         # Portrait-specific override
ASSET_PROVIDER_SCENE=mock            # Scene-specific override
ASSET_PROVIDER_AUDIO=audio_placeholder  # Audio category (bgm, sfx)
ASSET_PROVIDER_BGM=audio_placeholder    # BGM-specific override
ASSET_PROVIDER_SFX=audio_placeholder    # SFX-specific override

# Time Advance Configuration
TIME_ADVANCE_LLM_MODE=reuse          # "reuse" (P10-A default); "explicit" not yet implemented (P10-B scope)
```

### Quest Visibility

Quests now have `player_visibility` field:
- `hidden`: Not returned by Player API (spoiler protection)
- `discovered`: Visible to player
- Completed quests auto-promoted to `discovered`

### Time Categories

| Category | Minutes | Example Actions |
|----------|---------|-----------------|
| inspect | 1-5 | Look around, examine item |
| short_dialogue | 3-15 | Talk, ask question |
| long_dialogue | 10-45 | Persuade, negotiate |
| nearby_movement | 5-30 | Move within area |
| far_movement | 30-180 | Travel to distant location |
| combat | 1-10 | Attack, defend, cast skill |
| rest | 30-480 | Rest, recover |
| wait | 1-1440 | Explicit wait action |

### P10-B Deferred Items

The following features are explicitly out of scope for P10-A:

- **TIME_ADVANCE_LLM_MODE=explicit**: Separate LLM call for time advancement
- **Real external providers**: DALL-E/Stable Diffusion with real API calls
- **SFX asset generation**: Sound effects beyond placeholder
- **Real audio synthesis**: Music generation API

For detailed status, see `P10A_EXECUTION_REPORT.md` and `P10A_READINESS.md`.

## P10-B: Stage-Level LLM Routing

This phase implements per-stage LLM configuration with environment variable fallback chain for all 5 LLM stages.

### Quick Test Commands

```bash
# Show all available targets
make help

# Run P10-B resolver unit tests
make test-p10b-resolver

# Run P10-B integration tests
make test-p10b-routing

# Run P10-B quality gate (fast)
make test-p10b-fast

# Run P10-B quality gate (full)
make test-p10b

# Verify no regression
make test-v1-release
```

### Key Features

- **5 LLM Stages**: input_intent, world, scene, npc, narration — each independently configurable
- **Fallback Chain**: stage env var → global env var → global settings → stage default
- **input_intent Defaults**: 15s timeout, 200 max_tokens, 0.3 temperature (optimized for quick intent parsing)
- **Other Stage Defaults**: 30s timeout, 500 max_tokens, 0.8 temperature
- **Debug Endpoint**: `GET /debug/llm/stage-routing/resolved` exposes resolved config without API key leakage
- **Mock Mode**: `use_mock=True` forces mock provider for all stages

### LLM Stages

| Stage | Purpose | Default Timeout | Default Max Tokens | Default Temperature |
|-------|---------|-----------------|-------------------|---------------------|
| input_intent | Parse player input into structured intent | 15s | 200 | 0.3 |
| world | World state evolution | 30s | 500 | 0.8 |
| scene | Scene/location changes | 30s | 500 | 0.8 |
| npc | NPC decision making | 30s | 500 | 0.8 |
| narration | Narrative text generation | 30s | 500 | 0.8 |

### New Environment Variables

```bash
# Per-Stage LLM Configuration
# Each stage supports: PROVIDER_MODE, DEFAULT_MODEL, TEMPERATURE, MAX_TOKENS, TIMEOUT

# input_intent stage (quick parsing)
LLM_INPUT_INTENT_PROVIDER_MODE=openai
LLM_INPUT_INTENT_DEFAULT_MODEL=gpt-4o-mini
LLM_INPUT_INTENT_TEMPERATURE=0.3
LLM_INPUT_INTENT_MAX_TOKENS=200
LLM_INPUT_INTENT_TIMEOUT=15

# world stage
LLM_WORLD_PROVIDER_MODE=openai
LLM_WORLD_DEFAULT_MODEL=gpt-4o
LLM_WORLD_TEMPERATURE=0.8
LLM_WORLD_MAX_TOKENS=500
LLM_WORLD_TIMEOUT=30

# scene stage
LLM_SCENE_PROVIDER_MODE=openai
LLM_SCENE_DEFAULT_MODEL=gpt-4o
LLM_SCENE_TEMPERATURE=0.8
LLM_SCENE_MAX_TOKENS=500
LLM_SCENE_TIMEOUT=30

# npc stage
LLM_NPC_PROVIDER_MODE=openai
LLM_NPC_DEFAULT_MODEL=gpt-4o
LLM_NPC_TEMPERATURE=0.8
LLM_NPC_MAX_TOKENS=500
LLM_NPC_TIMEOUT=30

# narration stage
LLM_NARRATION_PROVIDER_MODE=openai
LLM_NARRATION_DEFAULT_MODEL=gpt-4o
LLM_NARRATION_TEMPERATURE=0.8
LLM_NARRATION_MAX_TOKENS=500
LLM_NARRATION_TIMEOUT=30

# Global LLM fallback (used when stage-specific not set)
LLM_PROVIDER_MODE=openai
LLM_DEFAULT_MODEL=gpt-4o
LLM_TEMPERATURE=0.8
LLM_MAX_TOKENS=500
LLM_TIMEOUT=30
```

### Debug Endpoint Response

`GET /debug/llm/stage-routing/resolved` returns:

```json
{
  "stages": {
    "input_intent": {
      "provider_mode": "openai",
      "default_model": "gpt-4o-mini",
      "temperature": 0.3,
      "max_tokens": 200,
      "timeout_seconds": 15,
      "config_source": "stage_env_var",
      "fallback_used": false,
      "overrides": { "stage_env_vars": { "LLM_INPUT_INTENT_DEFAULT_MODEL": "set" } }
    },
    "world": { ... },
    "scene": { ... },
    "npc": { ... },
    "narration": { ... }
  },
  "global_env_vars": { "LLM_PROVIDER_MODE": "set", "LLM_DEFAULT_MODEL": null },
  "global_settings": { "provider_mode": "openai", "api_key": "***masked***" }
}
```

### P10-B Deferred Items

The following features are explicitly out of scope for P10-B:

- **DB provider profiles**: Admin UI for managing provider configurations
- **Cost-aware routing**: Route to cheaper/faster models based on cost constraints
- **Per-stage API keys**: Different API keys for different stages

For detailed status, see `P10B_EXECUTION_REPORT.md`.

## P10-C: Story Editor & NPC Memory-First

This phase delivers two major modules: Story Editor infrastructure with content pack versioning and NPC memory-first architecture with private memory storage and retrieval.

### Quick Test Commands

```bash
# Show all available targets
make help

# Run P10-C NPC memory unit tests
make test-p10c-npc-memory-unit

# Run P10-C story editor unit tests
make test-p10c-story-editor-unit

# Run P10-C content pack unit tests
make test-p10c-content-pack-unit

# Run P10-C integration tests
make test-p10c-integration

# Run P10-C quality gate (fast)
make test-p10c-fast

# Run P10-C quality gate (full)
make test-p10c

# Run P10-C quality gate (alias)
make test-p10c-gate
```

### Key Features

- **NPC Memory-First**: Private memory storage per major NPC with retrieval and turn service integration
- **Story Editor Fields**: ORM editor fields for story package versioning (World, Location, NPC, Event, Prompt)
- **Content Pack Versioning**: StoryPackageVersion with manifest snapshots and publish bridge
- **Hallucination Leak Hardening**: Stricter validation for LLM outputs

### P10-C Deferred Items

The following features are explicitly out of scope for P10-C:

- **Story Editor UI**: Admin UI for story package versioning
- **NPC Memory UI**: Debug UI for viewing NPC private memories
- **Memory Decay Integration**: ForgetCurve integration with private memories
- **Cross-Session Memory**: Memory sharing across sessions for same NPC

For detailed status, see `P10C_EXECUTION_REPORT.md`.

## References

- [Architecture Document](doc/core-game-loop-architecture.md)
- [Requirements Traceability](doc/requirements-traceability.md)
- [Testing Strategy](doc/testing_strategy.md) — Test pyramid, gates, and coverage requirements
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic V2](https://docs.pydantic.dev/)
- [Next.js Documentation](https://nextjs.org/docs)
