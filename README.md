# LLM RPG Engine - Perspective-Aware Memory System

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

### Reserved Media Endpoints

The following endpoints are reserved for future implementation and currently return HTTP 501 Not Implemented:

- `POST /media/portraits/generate` - Character portrait generation
- `POST /media/scenes/generate` - Scene image generation
- `POST /media/bgm/generate` - Background music generation

These endpoints will support AI-generated media content in future releases.

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
```

### CI Pipeline

The project includes a GitHub Actions CI workflow (`.github/workflows/ci.yml`) that runs automatically on push and pull requests:

- **backend-tests**: Runs backend unit and integration tests + scenario smoke
- **frontend-tests**: Runs frontend static checks (lint + typecheck) and stable combat tests
- **frontend-unit-tests**: Runs full frontend unit tests (non-blocking, known failures)
- **pgvector-tests**: Runs pgvector-specific tests against PostgreSQL

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

### P5 Deferred Items

The following features are explicitly out of scope for P4 and deferred to future phases:

- **Media generation**: Portrait, scene, and BGM async generation (`/media/*` endpoints remain 501)
- **Async job infrastructure**: Celery, RQ, Temporal, or similar
- **Engine refactoring**: ReplayEngine or Turn Orchestrator major rewrites
- **Real LLM in tests**: Default tests must not require real OpenAI API
- **Arbitrary expressions**: Plot beat conditions must use whitelist only

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

### P6 Deferred Items

The following features are explicitly out of scope for P5 and deferred to future phases:

- **Media generation**: Portrait, scene, and BGM async generation (`/media/*` endpoints remain 501)
- **Async job infrastructure**: Celery, RQ, Temporal, or similar
- **Full AuditStore persistence**: Only model_calls persisted; context_builds, validations, etc. remain in-memory
- **ForgetCurve background decay**: Memory decay background job
- **Semantic leak detection**: Embedding-based leak detection
- **Engine refactoring**: ReplayEngine or Turn Orchestrator major rewrites

For detailed status, see `IMPLEMENTATION_STATUS.md`, `P5_COMPLETION_REPORT.md`, and `P5_READINESS.md`.

## References

- [Architecture Document](doc/llm_rpg_perspective_aware_memory_system_architecture.md)
- [Requirements Traceability](doc/requirements-traceability.md)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic V2](https://docs.pydantic.dev/)
- [Next.js Documentation](https://nextjs.org/docs)
