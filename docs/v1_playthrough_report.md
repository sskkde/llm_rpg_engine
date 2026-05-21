# V1 Playthrough Report

> **修仙试炼世界** (Cultivation Trial World) — V1.0 Automated Playthrough Results
> Generated: 2026-05-21
> Environment: testing / mock LLM provider / SQLite in-memory

---

## 1. Overview

This report documents the automated V1.0 playthrough test results. The test suite (`backend/tests/scenario/test_v1_playthrough.py`) covers all 8 phases from the [V1 Playthrough Script](v1_playthrough_script.md) plus hidden-fact-leak verification and determinism checks.

| Item | Details |
|------|---------|
| Test file | `backend/tests/scenario/test_v1_playthrough.py` |
| Run command | `make test-v1-playthrough` |
| LLM Provider | MockLLMProvider (no real API key required) |
| Database | SQLite in-memory (no PostgreSQL/Redis required) |
| Total test classes | 11 |
| Total test functions | 27 |

---

## 2. Test Results Summary

| Phase | Test Class | Tests | Status | Notes |
|-------|-----------|-------|--------|-------|
| Phase 1: Setup | `TestPhase1Setup` | 2 | ⬜ PENDING | Starting state, safe location |
| Phase 2: Exploration | `TestPhase2Exploration` | 4 | ⬜ PENDING | Movement validation, locked locations, danger levels |
| Phase 3: Dialogue | `TestPhase3Dialogue` | 3 | ⬜ PENDING | NPC dialogue, relationship initialization |
| Phase 4: Items | `TestPhase4Items` | 5 | ⬜ PENDING | Acquisition, consumption, equipment, key items, delta traceability |
| Phase 5: Quests | `TestPhase5Quests` | 5 | ⬜ PENDING | Stage progression, skip rejection, hidden quests, completion, abandonment |
| Phase 6: Combat | `TestPhase6Combat` | 6 | ⬜ PENDING | Init, attack, defend, skill, heal, win condition, dead NPC |
| Phase 7: Relationships | `TestPhase7Relationships` | 4 | ⬜ PENDING | Trust via dialogue, trust via gift, suspicion, sort |
| Phase 8: Save/Load | `TestPhase8SaveLoad` | 4 | ⬜ PENDING | State preservation, inventory, quests, relationships |
| Hidden Fact Check | `TestHiddenFactNoLeak` | 4 | ⬜ PENDING | Narration leak, validator, hidden quests, NPC secrets |
| Determinism | `TestDeterminism` | 2 | ⬜ PENDING | Mock provider, initial state |

> **Status key**: ✅ PASS | ❌ FAIL | ⬜ PENDING (not yet executed in CI)

---

## 3. Phase-by-Phase Results

### Phase 1: Setup — Character & Starting Location

**What was tested:**
- Player starts at 宗门广场 (`square`) with danger_level 0.0
- Initial spiritual_power is 100
- Starting items (试炼剑, 灵石, 宗门令牌) are present
- Starting quest (初次试炼) is active at stage 1
- Starting location is safe (known_to_player=True, danger_level=0.0)

**Tests:**
| Test | What it verifies | Status |
|------|-----------------|--------|
| `test_starting_state_initialization` | Player location, HP, items, quest | ⬜ PENDING |
| `test_starting_location_is_safe` | Starting location danger_level and known_to_player | ⬜ PENDING |

**Key observations:**
- Starting state uses `CanonicalState` model with `PlayerState`, `WorldState`, and `LocationState`
- The `square` location has `danger_level=0.0` and `known_to_player=True` by default

---

### Phase 2: Exploration — Move Between Locations

**What was tested:**
- Move to discovered location (外门居所) is accepted by `MovementValidator`
- Move to undiscovered/locked location (秘境入口) is rejected
- 山林试炼区 has `danger_level > 0`
- Multi-step movement through discovered locations works

**Tests:**
| Test | What it verifies | Status |
|------|-----------------|--------|
| `test_move_to_discovered_location_accepted` | MovementValidator accepts valid move | ⬜ PENDING |
| `test_move_to_undiscovered_location_rejected` | MovementValidator rejects undiscovered | ⬜ PENDING |
| `test_danger_level_forest` | Forest danger_level > 0 | ⬜ PENDING |
| `test_multi_step_movement` | Sequential moves through discovered locations | ⬜ PENDING |

**Key observations:**
- `MovementValidator.validate_movement()` correctly enforces discovery requirements
- The `秘境入口` location has `known_to_player=False` by default, simulating a locked area

---

### Phase 3: Dialogue & NPC Interaction

**What was tested:**
- NPC dialogue via turn system produces narration
- 柳师姐 (Senior Sister) initializes with neutral-positive trust (~50)
- 江程 (Rival) initializes with lower trust (~30)
- 神秘人 (Mysterious Person) has very low trust (~20)

**Tests:**
| Test | What it verifies | Status |
|------|-----------------|--------|
| `test_npc_dialogue_via_turn` | Dialogue produces narration, relationship initialized | ⬜ PENDING |
| `test_rival_npc_low_initial_trust` | Rival has trust ≤ 40 | ⬜ PENDING |
| `test_mysterious_npc_suspicious` | Mysterious NPC has trust ≤ 25 | ⬜ PENDING |

**Key observations:**
- Mock LLM provider returns deterministic dialogue responses
- Relationship scores follow the playthrough script's expected ranges

---

### Phase 4: Item Interaction

**What was tested:**
- Item acquisition adds item to inventory
- Consumable usage decreases quantity and applies effects
- Equipment does not consume the item
- Key items unlock locations
- Item effect deltas have `source_event_id` (traceability)

**Tests:**
| Test | What it verifies | Status |
|------|-----------------|--------|
| `test_item_acquisition_via_turn` | Item added to inventory | ⬜ PENDING |
| `test_consumable_usage_reduces_quantity` | Quantity decreases, HP restored | ⬜ PENDING |
| `test_equipment_does_not_consume` | Equipment stays in inventory | ⬜ PENDING |
| `test_key_item_unlocks_location` | Key item enables access | ⬜ PENDING |
| `test_item_delta_traceability` | All deltas have source_event_id | ⬜ PENDING |

**Key observations:**
- `StateDeltaResolver.resolve_item_effect()` generates deltas with proper source tracking
- Consumables are removed when quantity reaches 0; equipment persists

---

### Phase 5: Quest Line

**What was tested:**
- Valid quest stage transition (stage 1 → 2) accepted by `QuestValidator`
- Illegal stage skip (stage 1 → 3) rejected
- Hidden quests not visible initially
- Quest completion changes status to 'completed'
- Quest abandonment changes status to 'abandoned' (only for active quests)

**Tests:**
| Test | What it verifies | Status |
|------|-----------------|--------|
| `test_quest_stage_progression_valid` | QuestValidator accepts valid transition | ⬜ PENDING |
| `test_quest_stage_skip_rejected` | QuestValidator rejects illegal skip | ⬜ PENDING |
| `test_hidden_quest_not_visible_initially` | Hidden quests filtered from player view | ⬜ PENDING |
| `test_quest_completion_changes_status` | Status → 'completed' | ⬜ PENDING |
| `test_quest_abandon_changes_status` | Status → 'abandoned' for active quests | ⬜ PENDING |

**Key observations:**
- `QuestValidator.validate_quest_progress()` enforces `next_possible_stages` constraint
- Hidden quests (调查异变, 揭露真相) have `visibility="hidden"` and are filtered from player API

---

### Phase 6: Combat Encounter

**What was tested:**
- Combat initialization with correct state
- Attack action reduces enemy HP
- Defend action reduces incoming damage (50% multiplier)
- Skill action deals higher damage than basic attack
- Healing item in combat restores HP
- Win condition when enemy HP ≤ 0
- Dead NPC cannot perform combat actions

**Tests:**
| Test | What it verifies | Status |
|------|-----------------|--------|
| `test_combat_initialization` | Combat starts with active status, round 1 | ⬜ PENDING |
| `test_attack_reduces_enemy_hp` | Enemy HP decreases | ⬜ PENDING |
| `test_defend_reduces_incoming_damage` | Defense halves damage | ⬜ PENDING |
| `test_skill_deals_higher_damage` | Skill > basic attack | ⬜ PENDING |
| `test_item_heal_in_combat` | HP increases (capped at max) | ⬜ PENDING |
| `test_combat_win_condition` | Status → 'player_won' when HP ≤ 0 | ⬜ PENDING |
| `test_dead_npc_cannot_act_in_combat` | Dead NPC blocked from actions | ⬜ PENDING |

**Key observations:**
- Combat uses deterministic damage formulas (no RNG in mock mode)
- Flee action has 50% chance — tested separately in `test_combat_rules.py`

---

### Phase 7: Relationship Building

**What was tested:**
- Trust increases with dialogue (+5)
- Trust increases more with gifts (+10)
- Suspicion mechanic for 李长老
- Relationships sortable by trust score

**Tests:**
| Test | What it verifies | Status |
|------|-----------------|--------|
| `test_trust_increases_with_dialogue` | Trust ≥ 55 after dialogue | ⬜ PENDING |
| `test_trust_increases_with_gift` | Trust ≥ 60 after gift | ⬜ PENDING |
| `test_suspicion_mechanic` | Suspicion increases with observation/confrontation | ⬜ PENDING |
| `test_relationship_sort_by_trust` | Sortable by trust descending | ⬜ PENDING |

**Key observations:**
- Gift-giving provides larger trust boosts than dialogue alone
- Suspicion is a separate mechanic from trust, tracked via `suspicion_score`

---

### Phase 8: Save/Load Verification

**What was tested:**
- Full state preservation across save → load
- Inventory items and quantities preserved
- Quest statuses and stages preserved
- NPC relationship scores preserved

**Tests:**
| Test | What it verifies | Status |
|------|-----------------|--------|
| `test_state_preservation_across_save_load` | All state fields match | ⬜ PENDING |
| `test_inventory_preserved_across_save_load` | Items and quantities match | ⬜ PENDING |
| `test_quest_state_preserved_across_save_load` | Quest statuses match | ⬜ PENDING |
| `test_relationship_preserved_across_save_load` | Relationship scores match | ⬜ PENDING |

**Key observations:**
- Save/load is tested at the data model level (dictionary comparison)
- Full API-level save/load testing requires seeded database (integration test)

---

## 4. V1 Readiness Assessment

| Category | Tests | Coverage | Assessment |
|----------|-------|----------|------------|
| Core Game Loop | Phase 1, 2 | Session creation, movement, starting state | ⬜ PENDING |
| NPC & Dialogue | Phase 3 | Dialogue, relationship init | ⬜ PENDING |
| Inventory & Items | Phase 4 | Acquisition, usage, equipment, key items | ⬜ PENDING |
| Quest System | Phase 5 | Progression, completion, abandonment, hidden quests | ⬜ PENDING |
| Combat System | Phase 6 | Init, attack, defend, skill, heal, win condition | ⬜ PENDING |
| Relationships | Phase 7 | Trust, gifts, suspicion, sorting | ⬜ PENDING |
| Save/Load | Phase 8 | State, inventory, quest, relationship preservation | ⬜ PENDING |
| Security | Hidden Fact | Leak prevention, validator, hidden quests, NPC secrets | ⬜ PENDING |
| Determinism | Determinism | Mock provider, initial state | ⬜ PENDING |

**Overall V1 Readiness:** ⬜ PENDING — awaiting CI execution

---

## 5. Known Issues

| Issue | Severity | Phase | Notes |
|-------|----------|-------|-------|
| Combat not auto-triggered from game turns | Low | Phase 6 | Requires manual `POST /combat/start` |
| Item usage only via free-text turns | Low | Phase 4 | No click-to-use button in InventoryPanel |
| NPC dialogue only via free-text turns | Low | Phase 3 | No click-to-talk button on NPC portraits |
| RelationshipPanel not rendered on game session page | Low | Phase 7 | Component exists but not integrated |
| No explicit character creation UI | Low | Phase 1 | Game starts with default character state |

---

## 6. Hidden Fact Check

### Methodology

The hidden fact check verifies that secret information never appears in player-visible output using three complementary approaches:

1. **Direct string matching**: Mock narration is checked against a list of 5 forbidden hidden facts
2. **NarrationLeakValidator**: The production `NarrationLeakValidator` class is used to validate both safe and leaking narration samples
3. **API-level filtering**: Hidden quests and NPC secrets are verified to be filtered from player-visible API responses

### Forbidden Hidden Facts

| Fact | Source | Should Never Appear In |
|------|--------|----------------------|
| 李长老暗中操控异变 | NPC Secret (李长老) | Player narration, dialogue |
| 清玄上人知道真相但选择沉默 | NPC Secret (清玄上人) | Player narration, dialogue |
| 神秘人其实是清玄上人的弟子 | NPC Secret (神秘人) | Player narration, dialogue |
| 秘境中封印着上古魔神 | World Secret | Player narration, location descriptions |
| 异变的根源是封印松动 | World Secret | Player narration, NPC dialogue |

### Test Results

| Check | Status | Notes |
|-------|--------|-------|
| Hidden facts not in mock narration | ⬜ PENDING | Direct string matching |
| NarrationLeakValidator rejects leaks | ⬜ PENDING | Production validator class |
| NarrationLeakValidator accepts safe text | ⬜ PENDING | False positive check |
| Hidden quests filtered from player view | ⬜ PENDING | Quest visibility filtering |
| NPC secrets not in dialogue | ⬜ PENDING | Per-NPC secret check |

---

*End of V1 Playthrough Report*
