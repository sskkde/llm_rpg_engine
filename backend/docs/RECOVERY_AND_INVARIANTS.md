# Backend Architecture: Recovery Workflow and Progression Invariants

This document explains the core invariants governing turn execution, state management, and recovery workflows in the LLM RPG Engine backend.

## Core Invariants

### 1. Database is Authoritative

**The database is the single source of truth for all game state.**

- Turn numbering comes from `SELECT MAX(turn_no) FROM event_logs WHERE session_id = ?`
- Session state is reconstructed from persisted DB rows, not in-memory caches
- The in-memory `CanonicalStateManager` is treated as a **cache only**
- After any orchestrator cache reset, state is fully recoverable from DB

**Why this matters:**
- Server restarts do not lose game state
- Multiple backend instances can share the same DB
- Debugging is simpler: query the DB to see the true state

### 2. Idempotent Initialization

**Session initialization is idempotent.**

Running `initialize_session_story_state()` multiple times produces the same result as running it once:

```python
from llm_rpg.core.session_initialization import initialize_session_story_state

# Safe to call multiple times
initialize_session_story_state(db, session_id)
initialize_session_story_state(db, session_id)  # No-op, no duplicates created
```

This creates baseline rows if missing:
- `session_states` (current location, world time, global flags)
- `session_player_states` (realm, HP, stamina, spirit power)
- `session_npc_states` (one row per NPC template in the world)
- `session_quest_states` (one row per visible quest template)

**Backfill for historical sessions:**

```python
from llm_rpg.core.session_initialization import backfill_historical_sessions

# Backfill all active sessions missing baseline rows
count = backfill_historical_sessions(db)
print(f"Backfilled {count} sessions")
```

### 3. Turn Numbering is DB-Authoritative

**Turn numbers are allocated from the database, not in-memory counters.**

```python
from llm_rpg.core.turn_allocation import allocate_turn, get_current_turn_number

# Allocate next turn (DB query: SELECT MAX(turn_no))
turn_no, is_new = allocate_turn(db, session_id)

# Get current turn without allocating
current = get_current_turn_number(db, session_id)
```

**Idempotency key support:**

For retry scenarios (network failures, client retries), provide an idempotency key:

```python
turn_no, is_new = allocate_turn(
    db, 
    session_id, 
    idempotency_key="req_abc123"
)

# If called again with same key, returns same turn_no
# is_new will be False on retry
```

### 4. No State Mutation Without DB Record

**Canonical state is never mutated before validation passes and DB commit succeeds.**

The turn orchestrator follows this order:

1. **START TRANSACTION** - Create `TurnTransaction` record
2. **PARSE INTENT** - LLM or keyword-based parsing
3. **GENERATE PROPOSALS** - LLM outputs are proposals only (no state mutation)
4. **VALIDATE** - All proposals must pass validation
5. **ATOMIC COMMIT** - All events and state deltas committed together
6. **MEMORY WRITES** - Post-commit operations (chronicle, summaries)
7. **NARRATION** - Generated from committed facts only

If validation fails at any point, the transaction is rolled back and no state changes persist.

### 5. Streaming Commits Before Narration

**In streaming endpoints, state is committed to DB before narration begins.**

SSE event order:

```
1. turn_started      - Turn execution begins
2. event_committed   - State/events committed to DB (durable)
3. narration_delta   - Streaming narration text chunks
4. turn_completed    - Turn execution complete
```

This ensures:
- Client sees narration only after state is persisted
- If streaming fails mid-narration, the turn is still recorded
- Retry logic can safely re-request the turn

## Movement and Access Rules

### Deterministic Movement Resolution

Movement is resolved deterministically via `movement_handler.handle_movement()`:

```python
from llm_rpg.core.movement_handler import handle_movement

result = handle_movement(db, session_id, target_location_code)

if result.success:
    print(f"Moved to: {result.new_location_name}")
    # session_states.current_location_id is updated
else:
    print(f"Blocked: {result.blocked_reason}")
    # No state mutation occurred
```

### Access Rule Evaluation

Location access is controlled by `access_rules` JSON in `locations` table:

```json
{
  "always_accessible": false,
  "player_level": "inner_disciple",
  "time_restrictions": "daytime_only",
  "chapter": 2,
  "quest_trigger": "secret_revealed",
  "item_required": "ancient_key",
  "quest_completed": "main_quest_1",
  "boss_unlocked": true,
  "combat_level": "apprentice"
}
```

Rules are evaluated in order:
1. `always_accessible` - Short-circuits all other checks
2. `player_level` - Compares against `session_player_states.realm_stage`
3. `time_restrictions` - Checks `session_states.time_phase`
4. `chapter` - Checks `sessions.current_chapter_id`
5. `quest_trigger` - Checks `session_states.global_flags_json`
6. `item_required` - Checks global flags
7. `quest_completed` - Checks global flags
8. `boss_unlocked` - Checks global flags
9. `combat_level` - Checks global flags

### Recommended Action Generation

Recommended actions are generated deterministically from:

1. **Legal movement actions** - All locations with passing access rules
2. **NPC interactions** - NPCs at current location
3. **Quest actions** - Active quests

```python
from llm_rpg.core.scene_action_generator import generate_recommended_actions

actions = generate_recommended_actions(db, session_id, location_id)
# Returns up to 4 recommended action strings
```

## State Reconstruction

### Rebuilding CanonicalState from DB

When the in-memory cache is missing or stale, reconstruct from persisted rows:

```python
from llm_rpg.core.state_reconstruction import reconstruct_canonical_state

canonical_state = reconstruct_canonical_state(db, session_id)

if canonical_state is None:
    # Session does not exist
    pass
```

This reads from:
- `sessions` - World ID, chapter, status
- `session_states` - Location, time, flags
- `session_player_states` - Realm, HP, stats
- `session_npc_states` - NPC locations, trust, suspicion
- `session_quest_states` - Quest progress
- `locations`, `npc_templates`, `quest_templates` - Reference data

### Getting Latest Turn Number

```python
from llm_rpg.core.state_reconstruction import get_latest_turn_number

turn_no = get_latest_turn_number(db, session_id)
# Returns 0 if no events exist
```

## Diagnosing Stuck Sessions

### SQL Queries

**Check session state:**

```sql
SELECT 
    s.id,
    s.status,
    s.last_played_at,
    ss.current_location_id,
    ss.current_time,
    ss.time_phase
FROM sessions s
LEFT JOIN session_states ss ON ss.session_id = s.id
WHERE s.id = 'session_123';
```

**Check latest turn:**

```sql
SELECT 
    turn_no,
    event_type,
    input_text,
    narrative_text,
    occurred_at
FROM event_logs
WHERE session_id = 'session_123'
ORDER BY turn_no DESC
LIMIT 5;
```

**Check for missing baseline rows:**

```sql
-- Sessions without session_states
SELECT s.id
FROM sessions s
LEFT JOIN session_states ss ON ss.session_id = s.id
WHERE s.status = 'active' AND ss.id IS NULL;

-- Sessions without player_states
SELECT s.id
FROM sessions s
LEFT JOIN session_player_states sps ON sps.session_id = s.id
WHERE s.status = 'active' AND sps.id IS NULL;
```

**Check NPC states:**

```sql
SELECT 
    nt.name as npc_name,
    sns.current_location_id,
    sns.trust_score,
    sns.suspicion_score
FROM session_npc_states sns
JOIN npc_templates nt ON nt.id = sns.npc_template_id
WHERE sns.session_id = 'session_123';
```

### Debug Endpoints

**Get session state snapshot:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/debug/sessions/$SESSION_ID/state
```

**Get session event logs:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/debug/sessions/$SESSION_ID/logs?limit=10
```

**Get turn timeline:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/debug/sessions/$SESSION_ID/timeline
```

**Get specific turn debug info:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/debug/sessions/$SESSION_ID/turns/5
```

### Recovery Steps

**1. Backfill missing baseline rows:**

```python
from llm_rpg.core.session_initialization import initialize_session_story_state

# For a specific session
initialize_session_story_state(db, session_id)

# Or backfill all active sessions
from llm_rpg.core.session_initialization import backfill_historical_sessions
backfill_historical_sessions(db)
```

**2. Reconstruct state from DB:**

```python
from llm_rpg.core.state_reconstruction import reconstruct_canonical_state

state = reconstruct_canonical_state(db, session_id)
```

**3. Verify turn numbering:**

```python
from llm_rpg.core.turn_allocation import get_current_turn_number

current_turn = get_current_turn_number(db, session_id)
print(f"Current turn: {current_turn}")
```

## Testing Commands

### Run All Tests

```bash
cd backend
pytest -q
```

### Run Specific Test Suites

```bash
# Unit tests only
pytest tests/unit/ -q

# Integration tests only
pytest tests/integration/ -q

# Specific test file
pytest tests/integration/test_turn_service.py -q

# Specific test
pytest tests/unit/test_session_initialization.py::test_idempotent_initialization -q
```

### Test Coverage for Recovery Workflow

```bash
# Session initialization tests
pytest tests/unit/test_session_initialization.py -q

# State reconstruction tests
pytest tests/unit/test_state_reconstruction.py -q

# Turn allocation tests
pytest tests/unit/test_turn_allocation.py -q

# Movement handler tests
pytest tests/unit/test_movement_handler.py -q

# Turn service integration tests
pytest tests/integration/test_turn_service.py -q
```

## Key Files Reference

| Component | File | Purpose |
|-----------|------|---------|
| Session Initialization | `core/session_initialization.py` | Idempotent baseline row creation |
| State Reconstruction | `core/state_reconstruction.py` | Rebuild CanonicalState from DB |
| Turn Allocation | `core/turn_allocation.py` | DB-authoritative turn numbering |
| Turn Service | `core/turn_service.py` | Unified turn execution entry point |
| Turn Orchestrator | `core/turn_orchestrator.py` | Transaction pipeline with atomic commit |
| Movement Handler | `core/movement_handler.py` | Deterministic movement resolution |
| Scene Action Generator | `core/scene_action_generator.py` | Recommended action generation |
| Streaming API | `api/streaming.py` | SSE endpoint with commit-before-narration |
| Debug API | `api/debug.py` | Admin endpoints for diagnostics |

## Summary of Invariants

1. **DB is authoritative** - All state comes from persisted rows
2. **Idempotent init** - Running initialization twice is safe
3. **DB-authoritative turns** - Turn numbers from `SELECT MAX(turn_no)`
4. **No mutation before commit** - Validation must pass first
5. **Commit before narration** - Streaming commits state first
6. **Deterministic access** - Movement rules evaluated consistently
7. **Recoverable state** - Any session can be reconstructed from DB
