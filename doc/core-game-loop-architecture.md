# Core Game Loop Architecture

## Document Information
- **Created**: 2026-05-05
- **Purpose**: Define the LLM-vs-rule authority boundary for the core RPG turn loop
- **Scope**: Backend turn orchestration, proposal pipeline, state management

---

## Authority Boundary Overview

The core game loop follows a strict separation between LLM-driven creative operations and Rule/script-driven deterministic operations. This boundary ensures narrative coherence while maintaining game state integrity.

**LLM-driven operations**: input understanding, world state advancement, current scene operation, NPC independent decisions, player-visible narration.

**Rule/script-driven operations**: action scheduling, conflict resolution, validation, canonical fact commit.

### LLM-Driven Operations

LLM components are responsible for creative interpretation and narrative generation. They propose content but never directly mutate canonical state.

| Operation | Description | Current Implementation |
|-----------|-------------|------------------------|
| Input understanding | Parse player natural language into structured intent | Rule-based keyword matching (fallback) |
| World state advancement | Propose time-based world changes, offscreen events | Deterministic tick (fallback) |
| Current scene operation | Generate scene-specific content and interactions | Template-based (fallback) |
| NPC independent decisions | Generate NPC actions based on goals, personality, memory | Goal/idle-based logic (fallback) |
| Player-visible narration | Transform committed facts into narrative prose | Template-based generation (fallback) |

### Rule/Script-Driven Operations

Rule-based components handle deterministic game logic. They validate, schedule, and commit all state changes.

| Operation | Description | Implementation |
|-----------|-------------|----------------|
| Action scheduling | Order and prioritize proposed actions by rules | `ActionScheduler` in `core/action_scheduler.py` |
| Conflict resolution | Resolve competing actions deterministically | Priority-based resolution in scheduler |
| Validation | Verify action legality and state delta validity | `Validator` in `core/validator.py` |
| Canonical fact commit | Atomically persist validated state changes | `TurnOrchestrator._atomic_commit()` |

---

## Turn Loop Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     CORE TURN LOOP                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. INPUT PHASE (LLM-driven)                                    │
│     ┌──────────────────┐                                        │
│     │ Player Input     │                                        │
│     │ (natural lang)   │                                        │
│     └────────┬─────────┘                                        │
│              ▼                                                   │
│     ┌──────────────────┐     ┌─────────────────┐                │
│     │ Intent Parser    │────▶│ Parsed Intent   │                │
│     │ (LLM proposal)   │     │ (structured)    │                │
│     └──────────────────┘     └─────────────────┘                │
│                                                                  │
│  2. WORLD PHASE (LLM-driven + Rule-driven)                      │
│     ┌──────────────────┐                                        │
│     │ World Tick       │──▶ Time advancement (deterministic)    │
│     │ Scene Triggers   │──▶ Event evaluation (deterministic)    │
│     └──────────────────┘                                        │
│                                                                  │
│  3. ACTOR PHASE (LLM-driven)                                    │
│     ┌──────────────────┐                                        │
│     │ Collect Actors   │                                        │
│     └────────┬─────────┘                                        │
│              ▼                                                   │
│     ┌──────────────────┐     ┌─────────────────┐                │
│     │ NPC Decision     │────▶│ NPC Actions     │                │
│     │ (LLM proposal)   │     │ (proposed)      │                │
│     └──────────────────┘     └─────────────────┘                │
│                                                                  │
│  4. SCHEDULING PHASE (Rule-driven)                              │
│     ┌──────────────────┐     ┌─────────────────┐                │
│     │ Proposed Actions │────▶│ Conflict        │                │
│     │ (player + NPCs)  │     │ Resolution      │                │
│     └──────────────────┘     └────────┬────────┘                │
│                                       ▼                          │
│                              ┌─────────────────┐                │
│                              │ Resolved Actions│                │
│                              └─────────────────┘                │
│                                                                  │
│  5. VALIDATION PHASE (Rule-driven)                              │
│     ┌──────────────────┐                                        │
│     │ Action Validator │──▶ Legal/illegal check                 │
│     │ State Validator  │──▶ Delta validity check                │
│     └────────┬─────────┘                                        │
│              ▼                                                   │
│     ┌──────────────────┐                                        │
│     │ Validation Audit │──▶ Record failures                    │
│     └──────────────────┘                                        │
│                                                                  │
│  6. COMMIT PHASE (Rule-driven)                                  │
│     ┌──────────────────┐                                        │
│     │ ATOMIC COMMIT    │──▶ Events + Deltas + Audit             │
│     └────────┬─────────┘                                        │
│              ▼                                                   │
│     ┌──────────────────┐                                        │
│     │ Canonical State  │──▶ Immutable fact store                │
│     └──────────────────┘                                        │
│                                                                  │
│  7. NARRATION PHASE (LLM-driven)                                │
│     ┌──────────────────┐                                        │
│     │ Build Player     │──▶ Perspective filter                  │
│     │ Perspective      │                                        │
│     └────────┬─────────┘                                        │
│              ▼                                                   │
│     ┌──────────────────┐     ┌─────────────────┐                │
│     │ Narration Engine │────▶│ Player-visible  │                │
│     │ (LLM proposal)   │     │ Narration       │                │
│     └──────────────────┘     └─────────────────┘                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Current Implementation State

### Implemented (Rule-based Fallbacks)

| Component | Location | Status |
|-----------|----------|--------|
| Intent Parser | `turn_orchestrator.py:147` | Rule-based keyword matching |
| World Tick | `world_engine.advance_time()` | Deterministic time increment |
| Scene Triggers | `action_scheduler.collect_scene_triggers()` | Rule-based evaluation |
| NPC Decisions | `turn_orchestrator._process_npc_decisions()` | Goal/idle-based logic |
| Action Scheduler | `action_scheduler.resolve_conflicts()` | Priority-based resolution |
| Validator | `validator.validate_action()` | Rule-based validation |
| Atomic Commit | `turn_orchestrator._atomic_commit()` | Transactional commit |
| Narration Engine | `narration_engine.generate_narration()` | Template-based generation |

### Pending LLM Integration

The following components have deterministic fallbacks and will be enhanced with LLM proposals:

1. **Input Understanding** - Natural language intent parsing
2. **NPC Independent Decisions** - Context-aware NPC behavior
3. **Player-visible Narration** - Dynamic narrative generation
4. **World State Advancement** - Offscreen event generation
5. **Current Scene Operation** - Scene-specific content

---

## Key Constraints

### LLM Output Handling

```
LLM Output ──▶ Structured Proposal ──▶ Parse ──▶ Repair ──▶ Audit ──▶ Accept/Reject
                                                                  │
                                                                  ▼
                                                          Rule/Validator Layer
```

- LLM outputs are **proposals only**
- Never mutate `CanonicalState` directly
- All outputs are structured, parsed, repaired, audited
- Rule/validator layers have final authority

### Deterministic Fallbacks

Every LLM-driven operation has a deterministic fallback:

| LLM Operation | Fallback Mechanism |
|---------------|-------------------|
| Intent parsing | Keyword-based matching |
| NPC decisions | Goal/idle-based logic |
| Narration | Template-based generation |
| World advancement | Fixed time increment |

### Narration Constraints

- Narration consumes **committed/player-visible facts only**
- Cannot invent uncommitted facts
- Cannot reveal hidden information
- Must respect perspective filtering

### Sequential NPC Decisions

- NPC decisions use working/temporary state
- State is not canonical until commit
- Later NPCs can see earlier NPC proposals within same turn

---

## MVP excludes

The following are explicitly out of scope for MVP:

1. **No UI/media expansion** - Media endpoints return 501 Not Implemented
2. **No broad RAG rewrite** - Existing retrieval system remains
3. **No replacing scheduler/validator/commit authority with LLM** - Rule-based components retain final authority
4. **No direct LLM state mutation** - All changes go through proposal pipeline
5. **No bypassing validation** - Every proposal must pass rule-based validation

---

## Integration Order

Based on risk assessment, LLM integration follows this order:

1. **Narration** (lowest risk) - Read-only, consumes committed facts
2. **Input Intent** - Structured output, validation available
3. **NPC Decisions** - Working state, validation available
4. **Scene Candidates** - Proposal-based, validation available
5. **World Tick** (highest risk) - Global state impact

---

## References

- Implementation: `backend/llm_rpg/core/turn_orchestrator.py`
- Scheduler: `backend/llm_rpg/core/action_scheduler.py`
- Validator: `backend/llm_rpg/core/validator.py`
- World Engine: `backend/llm_rpg/engines/world_engine.py`
- Narration Engine: `backend/llm_rpg/engines/narration_engine.py`
