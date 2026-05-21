# Rule Engine Specification (WP1)

This document specifies the rule engine architecture for the LLM RPG Engine, covering all six WP1 modules: RuleEngine, ActionSchema, StateDeltaResolver, StateDeltaValidator, ConflictResolver, and the validation pipeline.

## 1. Architecture Overview

### 1.1 RuleEngine

**Location**: `backend/llm_rpg/rules/rule_engine.py`

The RuleEngine is the main rule evaluation and validation system. It coordinates between different rule types and provides unified validation.

```python
class RuleEngine:
    def __init__(self):
        self._rules: Dict[str, Dict[str, Any]] = {}
        self._rule_handlers: Dict[RuleType, List[Callable]] = {...}
        self._validation_history: List[RuleResult] = []
```

**Key Responsibilities**:
- Rule registration with priority and type
- Rule evaluation and validation
- Validation history tracking
- Bulk validation with stop-on-error support

### 1.2 RuleType Enum

The system defines six rule types:

| RuleType | Value | Description |
|----------|-------|-------------|
| `MOVEMENT` | `"movement"` | Movement rules (location access, path blocking) |
| `QUEST` | `"quest"` | Quest progression rules (stage transitions) |
| `COMBAT` | `"combat"` | Combat rules (attack validity, damage calculation) |
| `DIALOGUE` | `"dialogue"` | Dialogue rules (NPC availability, topic access) |
| `WORLD_TIME` | `"world_time"` | World time rules (time progression, event triggers) |
| `CUSTOM` | `"custom"` | Custom game-specific rules |

### 1.3 RulePriority Enum

Rules are evaluated in priority order:

| Priority | Value | Use Case |
|----------|-------|----------|
| `CRITICAL` | 0 | Integrity-critical checks |
| `HIGH` | 1 | Game-breaking prevention |
| `NORMAL` | 2 | Standard game rules |
| `LOW` | 3 | Non-essential checks |
| `INFO` | 4 | Logging and metrics |

### 1.4 RuleResult Dataclass

```python
@dataclass
class RuleResult:
    rule_id: str
    rule_type: RuleType
    passed: bool
    errors: List[str]
    warnings: List[str]
    modifications: Dict[str, Any]
    priority: RulePriority
    timestamp: datetime
```

### 1.5 Registration Pattern

Rules are registered with the engine:

```python
rule_id = engine.register_rule(
    rule_type=RuleType.MOVEMENT,
    handler=validate_movement,
    priority=RulePriority.HIGH,
    description="Block movement to undiscovered locations"
)
```

The engine maintains per-type handler lists and enables/disables rules dynamically.

---

## 2. ActionSchema System

**Location**: `backend/llm_rpg/rules/action_schema.py`

### 2.1 ActionType Enum (16 Types)

| ActionType | Required Fields | Valid Targets | Description |
|------------|-----------------|---------------|-------------|
| `move` | `target_ids` | `location` | Move to a location |
| `inspect` | `target_ids` | `location`, `npc`, `item` | Inspect a location, NPC, or item |
| `talk` | `target_ids` | `npc` | Talk to an NPC |
| `ask` | `target_ids` | `npc` | Ask an NPC a question |
| `use_item` | `item_id` | `self`, `npc` | Use an item on self or an NPC |
| `take_item` | `item_id` | `item` | Take an item from a location |
| `give_item` | `item_id`, `target_ids` | `npc`, `item` | Give an item to an NPC |
| `attack` | `target_ids` | `npc` | Attack an NPC |
| `defend` | (none) | `none` | Defend against attacks |
| `cast_skill` | `skill_name` | `npc`, `self` | Cast a skill on self or an NPC |
| `persuade` | `target_ids` | `npc` | Persuade an NPC |
| `hide` | (none) | `none` | Hide from enemies |
| `follow` | `target_ids` | `npc` | Follow an NPC |
| `wait` | (none) | `none` | Wait for some time |
| `trigger_object` | `item_id` | `item` | Trigger or interact with an object |
| `quest_progress` | `quest_id` | `none` | Progress a quest |

### 2.2 TargetType Enum (5 Types)

| TargetType | Value | Description |
|------------|-------|-------------|
| `location` | `"location"` | A game location |
| `npc` | `"npc"` | A non-player character |
| `item` | `"item"` | An item object |
| `self_type` | `"self"` | The acting entity itself |
| `none` | `"none"` | No target required |

### 2.3 ActionSchema Dataclass

```python
@dataclass
class ActionSchema:
    action_type: ActionType
    required_fields: list[str]
    optional_fields: list[str]
    valid_targets: list[TargetType]
    description: str
```

### 2.4 ACTION_SCHEMAS Registry

The global `ACTION_SCHEMAS` dictionary maps each ActionType to its schema:

```python
ACTION_SCHEMAS: dict[ActionType, ActionSchema] = {
    ActionType.move: ActionSchema(
        action_type=ActionType.move,
        required_fields=["target_ids"],
        optional_fields=[],
        valid_targets=[TargetType.location],
        description="Move to a location",
    ),
    # ... 15 more schemas
}
```

### 2.5 validate_action_schema Function

```python
def validate_action_schema(action: dict[str, Any]) -> ValidationResult:
```

**Validation Steps**:
1. Check `action_type` field exists
2. Validate `action_type` is a known ActionType
3. Retrieve schema from registry
4. Check all required fields are present

**Return**: `ValidationResult` with `is_valid` boolean and detailed checks.

---

## 3. StateDeltaResolver

**Location**: `backend/llm_rpg/core/state_delta_resolver.py`

The StateDeltaResolver generates `StateDeltaCandidate` objects for various resolution scenarios. It does NOT commit deltas, it only produces candidates for downstream validation.

### 3.1 StateDeltaCandidate Model

```python
@dataclass
class StateDeltaCandidate:
    path: str                    # Dot-notation state path
    operation: str               # One of: set, increment, decrement, append, remove, merge
    old_value: Any               # Previous value at the path
    new_value: Any               # Proposed new value
    source_action_id: str = ""   # ID of the triggering action
    source_event_id: str = ""    # ID of the triggering event
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### 3.2 Resolution Methods (7 Types)

| Method | Scenario | Delta Paths Generated |
|--------|----------|----------------------|
| `resolve_player_action()` | Player move, attack, use_item, cast_skill, take_item, give_item, defend | `session_state.current_location_id`, `npc_state.*.hp`, `player_state.*` |
| `resolve_npc_action()` | NPC move, attack, talk | `npc_state.*.current_location_id`, `npc_state.*.dialogue_state`, `player_state.hp` |
| `resolve_item_effect()` | Item hp_heal, mp_heal, buff | `player_state.hp`, `player_state.spirit_power`, `player_state.*` |
| `resolve_quest_progress()` | Quest stage advancement, completion | `quest_state.*.current_step`, `quest_state.*.status` |
| `resolve_relationship_change()` | Trust, respect, affinity changes | `npc_state.*.trust_score`, `npc_state.*.affinity` |
| `resolve_combat_result()` | HP changes, status effects from combat | `player_state.hp`, `npc_state.*.hp`, `world_state.global_flags.status_*` |
| `resolve_world_time_change()` | World time advancement | `session_state.world_time` |

### 3.3 Player Action Resolution Details

The `resolve_player_action()` method dispatches to specialized handlers:

```python
handler = {
    "move": self._resolve_player_move,
    "attack": self._resolve_player_attack,
    "use_item": self._resolve_player_use_item,
    "cast_skill": self._resolve_player_cast_skill,
    "take_item": self._resolve_player_take_item,
    "give_item": self._resolve_player_give_item,
    "defend": self._resolve_player_defend,
}.get(action_type)
```

**Move Resolution**: Generates a single delta for `session_state.current_location_id`.

**Attack Resolution**: Generates decrement deltas for each target's HP.

**Use Item Resolution**: Generates inventory removal delta plus effect deltas (hp_heal, mp_heal).

**Cast Skill Resolution**: Generates spirit_power decrement for caster plus HP decrement for targets.

### 3.4 Source Tracking

Every `StateDeltaCandidate` includes source tracking:

```python
for c in candidates:
    if not c.source_action_id:
        c.source_action_id = action_id
```

This enables complete traceability from any state change back to its originating action or event.

---

## 4. StateDeltaValidator

**Location**: `backend/llm_rpg/core/validation/state_delta_validator.py`

The StateDeltaValidator ensures all state changes conform to the contract defined in `state_delta_contract.py`.

### 4.1 Contract Constants

**Location**: `backend/llm_rpg/core/validation/state_delta_contract.py`

#### ALLOWED_DELTA_PATHS (57 paths)

The contract defines allowed state modification paths with wildcard support:

```
# Session state (4 paths)
session_state.current_location_id
session_state.world_time
session_state.current_chapter_id
session_state.flags.*

# Player state (10 paths)
player_state.hp
player_state.stamina
player_state.spirit_power
player_state.realm
player_state.experience
player_state.gold
player_state.inventory.*
player_state.learned_techniques.*
player_state.completed_quests.*
player_state.reputation.*

# NPC state (6 paths with wildcards)
npc_state.*.trust_score
npc_state.*.suspicion_score
npc_state.*.current_location_id
npc_state.*.affinity
npc_state.*.dialogue_state
npc_state.*.quest_progress.*

# World state (3 paths)
world_state.weather
world_state.time_of_day
world_state.global_flags.*

# Quest state (3 paths with wildcards)
quest_state.*.status
quest_state.*.current_step
quest_state.*.objectives.*
```

**Note**: Wildcard patterns (`*`) allow dynamic entity IDs.

#### BLOCKED_DELTA_PATHS (18 paths)

Critical paths that cannot be modified via state deltas:

```
# Session integrity (5 paths)
session.id, session.status, session.user_id, session.created_at, session.updated_at

# NPC hidden states (5 paths)
npc_state.*.hidden_plan_state
npc_state.*.secret_knowledge
npc_state.*.true_identity
npc_state.*.hidden_identity
npc_state.*.memory.*

# Player immutable (3 paths)
player_state.id, player_state.user_id, player_state.created_at

# World immutable (2 paths)
world_state.id, world_state.seed

# Quest bypass (1 path)
quest_state.*.skip

# Audit integrity (3 paths)
audit_log.*, game_events.*, state_deltas.*
```

### 4.2 ALLOWED_OPERATIONS (6 Types)

| Operation | Description |
|-----------|-------------|
| `set` | Replace old value with new value |
| `increment` | Add numeric delta to current value |
| `decrement` | Subtract numeric delta from current value |
| `append` | Add item to list/array |
| `remove` | Remove item from list/array |
| `merge` | Merge dict fields (partial update) |

### 4.3 NUMERIC_BOUNDS

Value constraints for numeric fields:

| Path | Min | Max | Note |
|------|-----|-----|------|
| `player_state.hp` | 0 | None | HP cannot go below 0 |
| `player_state.stamina` | 0 | 100 | Stamina 0-100 |
| `player_state.spirit_power` | 0 | None | Spirit power >= 0 |
| `player_state.realm` | 0 | 10 | Cultivation realm 0-10 |
| `player_state.experience` | 0 | None | Experience >= 0 |
| `player_state.gold` | 0 | None | Gold >= 0 |
| `npc_state.*.trust_score` | 0 | 100 | Trust 0-100 |
| `npc_state.*.suspicion_score` | 0 | 100 | Suspicion 0-100 |
| `npc_state.*.affinity` | -100 | 100 | Affinity -100 to 100 |
| `session_state.world_time` | 0 | None | Time >= 0 |

### 4.4 SOURCE_EVENT_ID_EXCEPTIONS

Special source_event_id values that bypass validation:

| Exception | Use Case |
|-----------|----------|
| `bootstrap` | Initial state setup |
| `system` | System-initiated changes |
| `migration` | Database migration scripts |
| `admin` | Admin override operations |
| `debug` | Debug/test operations |

### 4.5 Validation Checks

The `validate()` method performs five checks in order:

1. **source_event_id check**: Must be non-empty (unless exception)
2. **path check**: Must be in allowed list and not blocked
3. **operation check**: Must be in allowed operations list
4. **old_value check**: Must match current state (if state provided)
5. **numeric_bounds check**: Must be within defined constraints

```python
def validate(
    self,
    path: str,
    operation: str,
    old_value: Any,
    new_value: Any,
    current_state: CanonicalState | None = None,
    source_event_id: str | None = None,
) -> ValidationResult:
```

---

## 5. ConflictResolver

**Location**: `backend/llm_rpg/core/conflict_resolver.py`

The ConflictResolver resolves action conflicts using scenario-specific rules. It is called from `ActionScheduler._resolve_conflict_group()`.

### 5.1 ConflictResult Dataclass

```python
@dataclass
class ConflictResult:
    should_block: bool
    blocked_actions: List[str]
    resolved_actions: List[CommittedAction]
    narration: str
```

### 5.2 Resolution Scenarios (5 Types)

#### Scenario 1: NPC Block

**Method**: `resolve_npc_block()`

**Condition**: NPC with higher priority blocks player action.

**Rules**:
- NPC priority must be higher than player priority
- NPC action type must be in blocking types: `move`, `attack`, `defend`, `cast_skill`, `wait`
- Player action type must be in blockable types: `move`, `take_item`, `attack`, `cast_skill`, `trigger_object`
- NPC and player must be at the same location

**Narration**: "{NPC名}以更高优先级行动，阻挡了你的{玩家行动摘要}"

#### Scenario 2: Item Competition

**Method**: `resolve_item_competition()`

**Condition**: Multiple characters compete for the same item.

**Rules**:
- Score = priority + dexterity * 0.1
- Dexterity: Player=0.5, NPC=1.0-fatigue, Unknown=0.3
- Winner has highest score

**Narration**: "{赢家名}抢先获得了{物品名}"

#### Scenario 3: Target Fled

**Method**: `resolve_target_fled()`

**Condition**: Target is no longer at the same location as the actor.

**Rules**:
- Action type must require a target: `attack`, `talk`, `ask`, `follow`, `give_item`, `persuade`, `cast_skill`
- Target location must differ from actor location

**Narration**: "{目标名}已经离开，你的行动落空了"

#### Scenario 4: Dialog Interrupt

**Method**: `resolve_dialog_interrupt()`

**Condition**: High-priority event interrupts current dialog.

**Rules**:
- Dialog action types: `talk`, `ask`, `persuade`
- Interrupting action must have higher priority
- Combat types (`attack`, `cast_skill`, `defend`) trigger special narration

**Narration**: 
- Combat interrupt: "战斗突然爆发，你的对话被打断了！"
- Other interrupt: "突发事件打断了你的对话"

#### Scenario 5: Quest Conflict

**Method**: `resolve_quest_conflict()`

**Condition**: Invalid quest stage transition.

**Rules**:
- Action type must be `quest_progress`
- Quest template must have `legal_transitions` list
- Current stage to target stage must be in transitions list

**Narration**: "任务阶段从'{当前阶段}'到'{目标阶段}'的跳转不被允许"

---

## 6. Validation Flow

### 6.1 Turn Orchestrator Pipeline

**Location**: `backend/llm_rpg/core/turn_orchestrator.py`

The turn orchestrator executes a 12-step pipeline with atomic commit/rollback semantics.

### 6.2 Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          TURN TRANSACTION PIPELINE                          │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────┐
    │ 1. START     │ Create TurnTransaction record
    │ TRANSACTION  │ Record world_time_before
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ 2. PARSE     │ LLM/Rule Input Intent
    │    INTENT    │ Fallback: keyword parser
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ 3. TIME TICK │ Deterministic time advancement
    │    + WORLD   │ LLM world candidates (proposals only)
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ 4. SCENE     │ LLM scene candidates
    │    CANDIDATES│ Fallback: ActionScheduler triggers
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ 5. COLLECT   │ ActionScheduler.collect_actors()
    │    ACTORS    │ Player + NPCs in scene
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ 6. NPC       │ Sequential NPC decisions
    │    DECISIONS │ Each NPC sees working state
    └──────┬───────┘
           │
           ▼
    ┌──────────────────────────────────────────────────────────────┐
    │                    7. ACTION SCHEDULER                        │
    │  ┌─────────────────────────────────────────────────────────┐  │
    │  │ resolve_conflicts()                                      │  │
    │  │   ├── detect_conflicts()                                │  │
    │  │   │       Group actions with common targets              │  │
    │  │   └── _resolve_conflict_group()                          │  │
    │  │           ├── resolve_npc_block()                        │  │
    │  │           ├── resolve_item_competition()                 │  │
    │  │           ├── resolve_target_fled()                      │  │
    │  │           ├── resolve_dialog_interrupt()                 │  │
    │  │           └── resolve_quest_conflict()                   │  │
    │  └─────────────────────────────────────────────────────────┘  │
    └────────────────────────────┬─────────────────────────────────┘
                                 │
                                 ▼
    ┌──────────────────────────────────────────────────────────────┐
    │                      8. VALIDATOR                             │
    │  ┌─────────────────────────────────────────────────────────┐  │
    │  │ validate_action(action, state)                           │  │
    │  │   └── Action schema validation                           │  │
    │  │                                                          │  │
    │  │ validate_state_delta(path, old, new, state)              │  │
    │  │   ├── Path whitelist check                               │  │
    │  │   ├── Path blacklist check                               │  │
    │  │   ├── Operation check                                    │  │
    │  │   ├── Old value verification                             │  │
    │  │   └── Numeric bounds check                               │  │
    │  └─────────────────────────────────────────────────────────┘  │
    │                                                                │
    │  FAILURE → Rollback transaction, no state change              │
    └────────────────────────────┬─────────────────────────────────┘
                                 │
                                 ▼
    ┌──────────────┐
    │ 9. ATOMIC    │ All events recorded to EventLog
    │    COMMIT    │ All state deltas applied to CanonicalState
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ 10. MEMORY   │ World Chronicle
    │    WRITES    │ Scene Summary
    │              │ NPC Subjective Summary
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ 11. AUDIT    │ Complete audit trail for replay
    │              │ Prompt/template ID, proposal type, raw output
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ 12. NARRATION│ Generated from committed state only
    │              │ Fallback: template-based narration
    └──────────────┘
```

### 6.3 Key Invariants

1. **Canonical state is NEVER mutated before validation passes**
2. **LLM outputs are PROPOSALS only - never direct state mutation**
3. **All proposals have deterministic fallback**
4. **Validation failures result in NO committed state delta**
5. **Commit is ATOMIC - all or nothing**
6. **Narration consumes COMMITTED facts only**
7. **NPC prompts are perspective-filtered (no hidden info leak)**

---

## 7. Traceability

### 7.1 Source Tracking Fields

Every state change is traceable to its source:

| Field | Type | Description |
|-------|------|-------------|
| `source_action_id` | `str` | ID of the action that triggered this delta |
| `source_event_id` | `str` | ID of the event that triggered this delta |

### 7.2 Traceability Chain

```
Player Input
    │
    ▼
PlayerInputEvent (event_id)
    │
    ▼
ParsedIntent
    │
    ▼
ProposedAction (action_id)
    │
    ▼
StateDeltaCandidate (source_action_id, source_event_id)
    │
    ▼
StateDeltaEvent (deltas[].source_action_id)
    │
    ▼
CanonicalState (state change applied)
```

### 7.3 Replay Capability

The system supports state reconstruction via replay:

```python
def replay_turns(
    self,
    game_id: str,
    start_turn: int,
    end_turn: int,
) -> CanonicalState:
```

1. Load initial state snapshot
2. Get events in turn range
3. Sort by timestamp
4. Apply state deltas in order
5. Return reconstructed state

### 7.4 Audit Trail

Every proposal records:

- `prompt_template_id`: Template used for LLM call
- `raw_output_preview`: First 200 chars of LLM response
- `parsed_proposal`: Structured proposal data
- `repair_trace`: JSON repair strategies attempted
- `rejection_reason`: Why proposal was rejected (if applicable)
- `fallback_reason`: Why fallback was used (if applicable)
- `committed_event_ids`: Events that resulted from this proposal

---

## 8. Test Coverage

### 8.1 Unit Tests

| Module | Test File | Coverage |
|--------|-----------|----------|
| MovementValidator | `tests/unit/test_movement_validator.py` | Location access, path blocking |
| QuestValidator | `tests/unit/test_quest_validator.py` | Stage transitions |
| ItemRules | `tests/unit/test_item_rules.py` | Item usage rules |
| SkillRules | `tests/unit/test_skill_rules.py` | Skill casting rules |
| ActionSchema | `tests/unit/test_action_schema.py` | Schema validation |
| StateDeltaResolver | `tests/unit/test_state_delta_resolver.py` | Delta generation |
| ConflictResolver | `tests/unit/test_conflict_resolver.py` | Conflict resolution |

### 8.2 Scenario Tests

**Location**: `backend/tests/scenario/test_rule_engine_v1.py`

**Test Classes (12 scenarios)**:

1. `TestIllegalActionStatePreservation` - Illegal moves don't affect canonical state
2. `TestQuestStageProgression` - Quest stage skip prevention
3. `TestDeadNPCActionRejection` - Dead NPCs cannot act
4. `TestUndiscoveredLocationMove` - Cannot move to undiscovered locations
5. `TestStateDeltaTraceability` - All deltas have source tracking
6. `TestCombinedRuleValidation` - Multiple violations reported

**Test Count**: 12 scenario tests, all passing

### 8.3 Makefile Target

```bash
make test-v1-rule-engine
```

Runs:
- MovementValidator unit tests
- QuestValidator unit tests
- ItemRules unit tests
- SkillRules unit tests
- ActionSchema unit tests
- StateDeltaResolver unit tests
- ConflictResolver unit tests
- Rule engine V1 scenario tests

---

## 9. Fallback Matrix

| Failure Point | Fallback Strategy | Audit Record |
|---------------|-------------------|--------------|
| Input Intent LLM | Keyword-based parser | `fallback_reason` |
| World Tick LLM | WorldEngine.check_world_events() | `fallback_reason` |
| Scene Candidates LLM | ActionScheduler.collect_scene_triggers() | `fallback_reason` |
| NPC Action LLM | Goal/idle behavior from NPCEngine | `fallback_reason` |
| Narration LLM | Template-based _generate_text() | `fallback_reason` |
| Parse Failure | JSON repair → fallback if repair fails | `repair_trace` |
| Schema Validation | Reject proposal, use fallback | `validation_errors` |
| Validator Rejection | Rollback transaction, no state change | `rejection_reason` |
| Timeout | Use deterministic fallback | `fallback_reason` |
| Perspective Leak | Sanitize or reject proposal | `validation_errors` |

---

## 10. References

### Source Files

| Component | Path |
|-----------|------|
| RuleEngine | `backend/llm_rpg/rules/rule_engine.py` |
| ActionSchema | `backend/llm_rpg/rules/action_schema.py` |
| StateDeltaResolver | `backend/llm_rpg/core/state_delta_resolver.py` |
| StateDeltaContract | `backend/llm_rpg/core/validation/state_delta_contract.py` |
| StateDeltaValidator | `backend/llm_rpg/core/validation/state_delta_validator.py` |
| ConflictResolver | `backend/llm_rpg/core/conflict_resolver.py` |
| TurnOrchestrator | `backend/llm_rpg/core/turn_orchestrator.py` |
| ActionScheduler | `backend/llm_rpg/core/action_scheduler.py` |

### Test Files

| Test Type | Path |
|-----------|------|
| MovementValidator | `backend/tests/unit/test_movement_validator.py` |
| QuestValidator | `backend/tests/unit/test_quest_validator.py` |
| ItemRules | `backend/tests/unit/test_item_rules.py` |
| SkillRules | `backend/tests/unit/test_skill_rules.py` |
| Scenario Tests | `backend/tests/scenario/test_rule_engine_v1.py` |

### Build Target

| Target | Makefile Location |
|--------|-------------------|
| test-v1-rule-engine | `Makefile:196-199` |

---

*Document Version: 1.0*
*Last Updated: 2026-05-21*
*WP1 Rule Engine Specification*
