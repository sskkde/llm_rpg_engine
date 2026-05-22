# V1 Playthrough Script & Test Report

> **修仙试炼世界** (Cultivation Trial World) — 30-60 minute V1 release verification playthrough
> Last updated: 2026-05-21

---

## Table of Contents

1. [Overview](#overview)
2. [Pre-Flight Checklist](#pre-flight-checklist)
3. [Phase 1: Setup — Character & Starting Location (5 min)](#phase-1-setup--character--starting-location-5-min)
4. [Phase 2: Exploration — Move Between Locations (10 min)](#phase-2-exploration--move-between-locations-10-min)
5. [Phase 3: Dialogue & NPC Interaction (5 min)](#phase-3-dialogue--npc-interaction-5-min)
6. [Phase 4: Item Interaction (10 min)](#phase-4-item-interaction-10-min)
7. [Phase 5: Quest Line (15 min)](#phase-5-quest-line-15-min)
8. [Phase 6: Combat Encounter (10 min)](#phase-6-combat-encounter-10-min)
9. [Phase 7: Relationship Building (5 min)](#phase-7-relationship-building-5-min)
10. [Phase 8: Save/Load Verification (5 min)](#phase-8-saveload-verification-5-min)
11. [V1 Readiness Checklist](#v1-readiness-checklist)

---

## Overview

This document provides a step-by-step narrative playthrough for verifying all V1 release features of the LLM RPG Engine. Each step documents:

| Column | Meaning |
|--------|---------|
| **Player Input** | The action the tester performs (UI click, API call, or free-text turn) |
| **Expected System Response** | What the system should return/display |
| **Feature Verified** | Which V1 feature or panel is being tested |

### Game World Summary

| Element | Details |
|---------|---------|
| World | 修仙试炼世界 (`cultivation_trial_world`) |
| Genre | Xianxia (仙侠) |
| Starting Location | 宗门广场 (`square`) — danger 0.0, tags: public, safe, starting_point |
| Chapters | 3: 初入宗门 → 异变初现 → 真相揭露 |
| NPCs | 6: 柳师姐, 江程, 林菲, 神秘人, 李长老, 清玄上人 |
| Items | 7: 灵石, 回春草, 秘境钥匙, 宗门令牌, 上古残卷, 试炼剑, 聚灵丹 |
| Quests | 4: 初次试炼, 调查异变, 揭露真相, 师姐的请求 |
| Endings | 3: 宗门英雄, 牺牲与救赎, 真相之后 |

### Key API Prefixes

| Category | Base Path |
|----------|-----------|
| Game Turn | `POST /game/sessions/{session_id}/turn` |
| Streaming Turn | `POST /streaming/sessions/{session_id}/turn` (SSE) |
| Player Quests | `GET /player/sessions/{session_id}/quests` |
| Player Inventory | `GET /player/sessions/{session_id}/inventory` |
| Player Locations | `GET /player/sessions/{session_id}/locations` |
| Player Relationships | `GET /player/sessions/{session_id}/relationships` |
| Combat | `POST /combat/start`, `GET /combat/{combat_id}` |
| Admin Health | `GET /admin/health` |
| Admin Metrics | `GET /admin/metrics` |
| Admin Release Readiness | `GET /admin/release-readiness` |

---

## Pre-Flight Checklist

Before starting the playthrough, verify infrastructure is running:

| Step | Command / Action | Expected Result |
|------|-----------------|-----------------|
| 1 | `docker-compose up -d` | PostgreSQL (5432) and Redis (6379) containers running |
| 2 | `cd backend && alembic upgrade head` | Migrations applied, `current == head` |
| 3 | `cd backend && python -m llm_rpg.scripts.seed_content` | World seeded: 1 world, 6 NPCs, 10 locations, 4 quests, 7 items |
| 4 | `GET /admin/health` | `{ db: {status: "ok"}, redis: {status: "ok"}, provider: {status: "ok"} }` |
| 5 | `GET /admin/release-readiness` | All checks green: `migrations.up_to_date=true, content.seeded=true, env_vars.*=true` |
| 6 | `GET /admin/metrics` | Returns `api_latency`, `llm_calls`, `sessions` metrics |
| 7 | Frontend dev server running (`npm run dev` on port 3005) | Landing page loads at `http://127.0.0.1:3005/zh` |

---

## Phase 1: Setup — Character & Starting Location (5 min)

**Goal**: Register a test user, create a save slot, start a new game session, and verify the player arrives at the starting location with correct initial state.

### Step 1.1: Register Test Account

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Navigate to `/zh/auth/register` | Registration form renders with username/password fields, `method="post"` | Auth UI, form security |
| Fill username: `testplayer_v1`, password: `TestPass123!`, submit | Success redirect to `/zh/game`, JWT stored in localStorage | `POST /auth/register`, `POST /auth/login` |
| Verify auth state | `getCurrentUser()` returns `{ username: "testplayer_v1" }` | `GET /auth/me`, useAuth hook |

### Step 1.2: Create Save Slot

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Navigate to `/zh/saves` | Save list page renders, empty state shown | Saves page UI |
| Click "Create Save Slot", enter name: "修仙之旅", slot: 1 | `createSaveSlot({ name: "修仙之旅", slot_number: 1 })` returns save with `id` | `POST /saves` |
| Save slot appears in list | Shows name, slot number, session count (0) | `GET /saves` |

### Step 1.3: Start New Game

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Click on save slot "修仙之旅" | Navigates to `/zh/saves/{save_id}` | Save detail page |
| Click "Start New Game" | Backend calls: `getWorldState()` → `manualSave({ world_id, save_slot_id, current_chapter_id })` → `loadSession(session_id)` | `GET /world/state`, `POST /saves/manual-save`, `POST /sessions/{id}/load` |
| Redirect to `/zh/game/{session_id}` | Game session page loads with NarrationPanel, ActionInput, StatePanel | Game session page layout |

### Step 1.4: Verify Starting State

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Check StatePanel | Shows: HP, realm (初始境界), location: 宗门广场, time: 青岚历 春 Day 1 辰时 | StatePanel, `GET /sessions/{id}/snapshot` |
| Check LocationMapPanel | Current location: 宗门广场 (danger: safe, ◆), connections visible | LocationMapPanel, `GET /player/sessions/{id}/locations` |
| Check InventoryPanel | Starting items visible (e.g., 试炼剑, 灵石, 宗门令牌) | InventoryPanel, `GET /player/sessions/{id}/inventory` |
| Check QuestJournalPanel | Quest "初次试炼" visible with status: active, step 1 | QuestJournalPanel, `GET /player/sessions/{id}/quests` |
| `GET /player/sessions/{id}/locations/current` | Returns `{ location_id: "square", name: "宗门广场", npcs_present: [...], items_present: [...] }` | Current location API |

---

## Phase 2: Exploration — Move Between Locations (10 min)

**Goal**: Navigate between locations, discover new areas, verify the LocationMapPanel updates correctly.

### Step 2.1: Observe Starting Area

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "观察四周" (look around) | NarrationPanel streams description of 宗门广场, recommended actions appear | `POST /game/sessions/{id}/turn`, SSE streaming, NarrationPanel |
| Verify narration appears with typing cursor | Narration text accumulates via `narration_delta` SSE events, cursor shows during streaming | useTurnStream hook, SSE fallback |
| Click a recommended action (e.g., "与人交谈") | Action text fills ActionInput, submit triggers turn | RecommendedActions component |

### Step 2.2: Move to 外门居所 (Residence)

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "前往外门居所" | Narration describes arriving at 外门居所, StatePanel updates location | Turn-based navigation |
| Check LocationMapPanel | Current location changes to 外门居所 (◆), 宗门广场 shows as connected (◇) | LocationMapPanel refresh, `GET /player/sessions/{id}/locations` |
| Verify connection graph | ASCII tree shows: `◆ 外门居所 └── ◇ 宗门广场` | Connection graph rendering |

### Step 2.3: Move to 药园 (Herb Garden)

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "去药园看看" | Narration describes 药园, herbs visible, danger level: safe | Turn-based navigation |
| Check LocationMapPanel | Current: 药园 (safe, ◆), connections to 宗门广场 and 山林试炼区 shown | Location discovery, danger badges |
| `GET /player/sessions/{id}/locations` | Returns list with 药园 marked `is_current: true`, danger_level: 0.0 | Location list API |

### Step 2.4: Discover 山林试炼区 (Forest Trial Area)

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "向山林试炼区走去" | Narration warns of danger, describes the forest edge | Danger-aware narration |
| Check LocationMapPanel | 山林试炼区 shows danger badge: "危险" (amber), danger_level: 0.5 | Danger level display |
| Verify location detail | `GET /player/sessions/{id}/locations/forest` returns tags: combat, exploration, danger_medium | Location detail API |

### Step 2.5: Visit 藏经阁外区 (Library)

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "回到宗门广场，然后去藏经阁" | Narration describes the library exterior, knowledge/lore atmosphere | Multi-step movement |
| Check LocationMapPanel | Current: 藏经阁外区 (safe), connections updated | Location state tracking |
| Verify NPCs present | `GET /player/sessions/{id}/locations/current` shows `npcs_present` array | NPC presence at location |

### Step 2.6: Attempt to Access Locked Location

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "进入秘境入口" | Narration blocks entry — location is locked/inaccessible, requires key item | Access rules enforcement |
| Check LocationMapPanel | 秘境入口 shows 🔒 locked icon, not accessible | Accessible/locked indicators |
| `GET /player/sessions/{id}/locations?accessible=true` | 秘境入口 NOT in list (filtered out) | Accessible filter parameter |

---

## Phase 3: Dialogue & NPC Interaction (5 min)

**Goal**: Talk to NPCs at various locations, verify NPC portraits appear, dialogue flows through the turn system, and relationship scores initialize.

### Step 3.1: Talk to 柳师姐 (Senior Sister) at 宗门广场

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Navigate to 宗门广场 | NPC portrait row shows 柳师姐 avatar | NPC portrait display, `GET /sessions/{id}/npcs` |
| Type action: "向柳师姐打招呼" | Narration: 柳师姐 responds warmly, introduces herself as guide | NPC dialogue via turn system |
| Type action: "询问关于试炼的事情" | 柳师姐 explains trial rules, hints at quest "初次试炼" | Quest-gated dialogue, lore delivery |
| Check RelationshipPanel | 柳师姐 entry shows: trust ~50-60 (neutral-positive), respect ~40 | `GET /player/sessions/{id}/relationships` |

### Step 3.2: Talk to 江程 (Rival) at 试炼堂

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Move to 试炼堂, type: "和江程交谈" | 江程 responds competitively, shows rivalry | Rival NPC personality |
| Type action: "挑战江程" | 江程 dismisses or accepts challenge based on relationship | Relationship-gated dialogue |
| Check RelationshipPanel | 江程: trust ~30 (low), respect ~50 | Rival relationship initialization |

### Step 3.3: Encounter 神秘人 (Mysterious Person)

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| At 山林试炼区, type: "观察周围有没有其他人" | Narration hints at a shadowy figure | Hidden NPC discovery |
| Type action: "走向那个神秘的身影" | 神秘人 appears, speaks cryptically about "异变" | Mystery NPC dialogue, plot hook |
| Check RelationshipPanel | 神秘人: trust ~20 (low, suspicious), fear ~30 | Mystery NPC relationship |

### Step 3.4: Sort and Review Relationships

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Click "Sort by Trust" in RelationshipPanel | NPC list reorders by trust score descending | `GET /player/sessions/{id}/relationships?sort_by=trust` |
| Click "Sort by Respect" | NPC list reorders by respect score | Sort parameter |
| Click on 柳师姐 card to expand | Shows all scores: trust, respect, fear with progress bars, last interaction turn | `GET /player/sessions/{id}/relationships/senior_sister` |
| Check summary card | Shows: total NPCs, average trust, highest/lowest trust NPC | `GET /player/sessions/{id}/relationships/summary` |

---

## Phase 4: Item Interaction (10 min)

**Goal**: Pick up items, use consumables, equip gear, give items to NPCs, verify InventoryPanel updates.

### Step 4.1: View Starting Inventory

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Check InventoryPanel | Shows starting items with rarity badges: 试炼剑 (common/灰色), 灵石 (common/灰色), 宗门令牌 (uncommon/绿色) | InventoryPanel rendering, rarity colors |
| Click "Stats" in InventoryPanel | Shows: total_items, unique_items, category breakdown | `GET /player/sessions/{id}/inventory/stats` |
| Filter by "equipment" | Only 试炼剑 and 宗门令牌 shown | `GET /player/sessions/{id}/inventory?category=equipment` |

### Step 4.2: Pick Up Items from Location

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| At 药园, type: "采集回春草" | Narration: player gathers 回春草, item added to inventory | Item acquisition via turn |
| Check InventoryPanel | 回春草 appears: consumable, common rarity, quantity: 1, effects: {hp_restore: 20} | Inventory update, item detail expansion |
| At 山林试炼区, type: "搜索周围有没有有用的东西" | Narration: player finds 灵石 or other items | Exploration-based item discovery |

### Step 4.3: Use Consumable Item

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "使用回春草" | Narration: player consumes herb, HP restored by 20 | Item usage via turn, effect application |
| Check StatePanel | HP increases by ~20 points | State update after item use |
| Check InventoryPanel | 回春草 quantity decreases by 1 (or removed if quantity was 1) | Inventory quantity tracking |

### Step 4.4: Use 聚灵丹 (Spirit Pill)

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "服用聚灵丹" | Narration: spiritual energy surges, spirit_power +50, realm progress +5 | Uncommon consumable effects |
| Check StatePanel | Spirit power and realm progress updated | Multiple effect application |
| Check InventoryPanel | 聚灵丹 removed from inventory | Consumable consumption |

### Step 4.5: Equip Item

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "装备试炼剑" | Narration: player equips the trial sword, attack bonus +10 | Equipment via turn |
| Check InventoryPanel | 试炼剑 shows as equipment type, effects: {attack_bonus: 10, durability: 100} | Equipment item display |
| Filter by "equipment" category | 试炼剑 and 宗门令牌 shown | Category filter |

### Step 4.6: Give Item to NPC

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "把灵石送给柳师姐" | Narration: 柳师姐 accepts gift, thanks player | Gift-giving interaction |
| Check RelationshipPanel | 柳师姐 trust score increases (+5-10) | Relationship impact from gifts |
| Check InventoryPanel | 灵石 quantity decreased | Inventory deduction |

### Step 4.7: Obtain Key Item — 秘境钥匙

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Progress quest to appropriate stage, type: "向柳师姐询问秘境的事情" | 柳师姐 gives 秘境钥匙 (rare, blue badge) | Key item acquisition via quest |
| Check InventoryPanel | 秘境钥匙 appears: key type, rare rarity, effects: {unlock_location: "secret_gate"} | Key item display |
| Filter by "key_item" | Only 秘境钥匙 shown | Key item category filter |

### Step 4.8: View Item Detail

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Click on 上古残卷 in InventoryPanel | Expanded view shows: description, rarity (epic/purple), effects: {reveal_secret: "cliff_altar_truth"}, durability, bound_flag | `GET /player/sessions/{id}/inventory/{item_id}` |
| Verify rarity color | Epic items show purple badge | Rarity color coding |

---

## Phase 5: Quest Line (15 min)

**Goal**: Accept, progress, and complete the main quest "初次试炼" and side quest "师姐的请求", verify QuestJournalPanel tracks all stages.

### Step 5.1: View Initial Quest

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Check QuestJournalPanel | Quest "初次试炼" shown: status=active, stage=1, objectives listed | QuestJournalPanel, `GET /player/sessions/{id}/quests` |
| Click on "初次试炼" | Detail view: description, 3 objectives with checkboxes, step history | `GET /player/sessions/{id}/quests/first_trial` |
| Verify hidden quests not shown | "调查异变" and "揭露真相" NOT visible (visibility=hidden) | Quest visibility filtering |

### Step 5.2: Progress Quest — Stage 1

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "前往试炼堂报到" | Narration: player reports to trial hall, first objective checked off | Quest objective completion via turn |
| Check QuestJournalPanel | Objective 1 checkbox now checked, progress bar updates | Quest progress tracking |
| Type action: "接受试炼任务" | Narration: trial elder assigns first trial task | Quest stage advancement |

### Step 5.3: Progress Quest — Stage 2

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "进入山林试炼区完成试炼" | Narration: player enters forest, encounters challenges | Quest-gated area access |
| Complete trial combat (see Phase 6) | Quest objective "完成山林试炼" checked off | Combat-quest integration |
| Check QuestJournalPanel | Stage 2 objectives shown, progress bar at 2/3 | Multi-stage quest tracking |

### Step 5.4: Accept Side Quest — "师姐的请求"

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| At 宗门广场, type: "问柳师姐有没有需要帮忙的" | 柳师姐 gives side quest "师姐的请求" | Side quest acquisition |
| Check QuestJournalPanel | "师姐的请求" appears: type=side, status=active, 2 steps | Side quest display |
| `GET /player/sessions/{id}/quests?status=active` | Both "初次试炼" and "师姐的请求" returned | Quest status filter |

### Step 5.5: Complete Side Quest

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "去药园采集灵草给柳师姐" | Narration: player gathers herbs, returns to 柳师姐 | Side quest progression |
| Type action: "把灵草交给柳师姐" | Narration: 柳师姐 thanks player, quest complete | Side quest completion |
| Check QuestJournalPanel | "师姐的请求" status changes to "completed" (green badge) | Quest completion state |
| Check RelationshipPanel | 柳师姐 trust increases significantly (+10-15) | Quest completion relationship reward |

### Step 5.6: Complete Main Quest — Stage 3

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type action: "向试炼堂汇报试炼完成" | Narration: trial complete, player recognized | Main quest final stage |
| Check QuestJournalPanel | "初次试炼" status: completed, all objectives checked, progress bar 100% | Main quest completion |
| Verify hidden quest unlock | "调查异变" now visible (was hidden, now triggered by main quest completion) | Hidden quest visibility trigger |

### Step 5.7: Abandon a Quest (Negative Test)

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Accept a new quest, then: `DELETE /player/sessions/{id}/quests/{quest_id}` | Quest status changes to "abandoned" | Quest abandon API |
| Check QuestJournalPanel | Quest shows "abandoned" badge (gray) | Abandoned quest display |
| Filter: `GET /player/sessions/{id}/quests?status=abandoned` | Abandoned quest returned | Status filter for abandoned |

### Step 5.8: Quest Detail Verification

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| `GET /player/sessions/{id}/quests/first_trial` | Returns: `quest_id`, `title`, `description`, `quest_type: "main"`, `stage: 3`, `status: "completed"`, `step_history[]`, `progress`, `visibility: "visible"`, `last_updated_at` | Full quest detail API |

---

## Phase 6: Combat Encounter (10 min)

**Goal**: Engage in turn-based combat, use all action types, verify CombatPanel and combat API.

### Step 6.1: Trigger Combat

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| At 山林试炼区, type: "深入山林探索" | Narration: wild beast appears, combat initiated | Combat trigger via turn |
| Or manual: `POST /combat/start` with `{ session_id, enemy_ids: ["wild_beast"] }` | Returns `{ combat_id, status: "active", round_no: 1, participants[] }` | Combat start API |
| CombatPanel renders | Shows: round number, player card (HP bar), enemy card (HP bar), action form, event feed | CombatPanel component |

### Step 6.2: Attack Action

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Select "Attack" in CombatActionForm, choose target, submit | `POST /combat/{combat_id}/turn` with `{ action_type: "attack", target_id: "enemy_1" }` | Attack action API |
| CombatEventFeed updates | Shows: "你发动攻击，造成 10 点伤害" | Combat event logging |
| Enemy HP decreases by ~10 | Enemy card HP bar updates | Combat state refresh, `GET /combat/{combat_id}` |
| NPC counter-attack event | "敌人反击，造成 8 点伤害" | Automatic NPC counter-attack |
| Player HP decreases by ~8 | Player card HP bar updates | Damage application |

### Step 6.3: Defend Action

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Select "Defend", submit | `{ action_type: "defend" }` | Defend action API |
| CombatEventFeed | "你采取防御姿态，防御力提升" | Defense boost narration |
| Next enemy attack deals reduced damage | Player HP decreases by less than 8 | Defense effect |

### Step 6.4: Skill Action

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Select "Skill", enter skill name: "剑气斩", submit | `{ action_type: "skill", skill_name: "剑气斩" }` | Skill action API |
| CombatEventFeed | "你施展剑气斩，造成 15 点伤害" | Skill damage (base 15) |
| Enemy HP decreases by ~15 | Higher damage than basic attack | Skill effectiveness |

### Step 6.5: Item Action (Healing in Combat)

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Select "Item", choose 回春草, submit | `{ action_type: "item", item_id: "healing_herb" }` | Item use in combat API |
| CombatEventFeed | "你使用回春草，恢复 20 点生命" | Combat healing |
| Player HP increases by ~20 | HP bar updates upward | Healing effect in combat |

### Step 6.6: Flee Action

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Select "Flee", submit | `{ action_type: "flee" }` | Flee action API |
| Two possible outcomes: | | |
| — Success (50% chance) | Combat status: "escaped", "Return to Game" button appears | Flee success, `GET /combat/{combat_id}` shows `status: "escaped"` |
| — Failure | "逃跑失败！敌人趁机攻击", combat continues | Flee failure, combat remains active |

### Step 6.7: Win Combat

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Continue attacking until enemy HP ≤ 0 | Combat status: "player_won" | Win condition |
| CombatEventFeed | "战斗胜利！" | Victory narration |
| Click "Return to Game" | `POST /combat/{combat_id}/end`, returns to game session | Combat end API, `endCombat()` |
| Check InventoryPanel | Loot items may appear (灵石, etc.) | Combat rewards |
| Check StatePanel | HP may be reduced, spirit power may have changed | Post-combat state |

### Step 6.8: Combat Events History

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| `GET /combat/{combat_id}/events` | Returns array of all combat events with round numbers, actor IDs, action types, damage/heal amounts | Combat events API |

### Step 6.9: Combat Test Page (Standalone)

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Navigate to `/zh/combat-test` | Standalone combat UI loads for testing | Combat test page |
| Start test combat, try all actions | All action types work independently | CombatPanel isolation test |

---

## Phase 7: Relationship Building (5 min)

**Goal**: Build NPC relationships through dialogue and gifts, verify RelationshipPanel tracks all changes.

### Step 7.1: Build Trust with 柳师姐

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type: "和柳师姐深入交谈，询问她的修行经历" | Narration: 柳师姐 shares personal story, trust increases | Trust-building dialogue |
| Type: "表示愿意帮助师姐" | Narration: 柳师姐 appreciates offer, trust +5 | Proactive trust building |
| Give gift: "把聚灵丹送给柳师姐" | Narration: 柳师姐 surprised and grateful, trust +10-15 | Gift relationship boost |
| Check RelationshipPanel | 柳师姐 trust ≥ 70 (emerald/green progress bar) | High trust visualization |

### Step 7.2: Build Respect with 清玄上人

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| At 藏经阁外区, type: "向清玄上人请教修行之道" | Narration: 清玄上人 imparts wisdom, respect increases | Respect-building dialogue |
| Type: "认真领悟上人的教诲" | Narration: 清玄上人 nods approvingly | Respect through behavior |
| Check RelationshipPanel | 清玄上人 respect score increased, sort by respect shows him higher | Respect tracking |

### Step 7.3: Increase Suspicion with 李长老

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Type: "暗中观察李长老的举动" | Narration: 李长老 notices, becomes suspicious | Suspicion mechanic |
| Check relationship detail | `GET /player/sessions/{id}/relationships/elder` shows `suspicion_score` increased | Suspicion tracking |
| Type: "质问李长老关于异变的事" | Narration: 李长老 deflects, suspicion increases further | Confrontation mechanics |

### Step 7.4: Relationship Summary Review

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| `GET /player/sessions/{id}/relationships/summary` | Returns: `total_npcs: 6`, `highest_trust: {npc_name: "柳师姐", score: 75}`, `lowest_trust: {npc_name: "李长老", score: 25}`, `average_trust: 45`, `average_respect: 50` | Relationship summary API |
| Sort by fear | NPCs reorder, 李长老 may show higher fear score | Fear sort parameter |
| Expand each NPC card | All 6 NPCs show trust/respect/fear with color-coded bars | Full relationship display |

### Step 7.5: Interaction History

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| `GET /player/sessions/{id}/relationships/senior_sister` | Returns `interaction_history[]` with `turn`, `content`, `impact` entries | Interaction history tracking |
| Verify history entries match playthrough | Each dialogue/gift interaction recorded with impact values | History accuracy |

---

## Phase 8: Save/Load Verification (5 min)

**Goal**: Manually save game state, verify state preservation across load.

### Step 8.1: Record Current State (Pre-Save)

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| `GET /sessions/{session_id}/snapshot` | Record: location, HP, realm, inventory items, quest statuses, relationship scores | Snapshot API |
| `GET /player/sessions/{id}/inventory` | Record: item list with quantities | Pre-save inventory |
| `GET /player/sessions/{id}/quests?status=active` | Record: active quest list with stages | Pre-save quests |
| `GET /player/sessions/{id}/relationships` | Record: all NPC relationship scores | Pre-save relationships |
| `GET /player/sessions/{id}/locations` | Record: discovered locations list | Pre-save locations |

### Step 8.2: Manual Save

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| `POST /saves/manual-save` with `{ world_id, save_slot_id, current_chapter_id }` | Returns new session with snapshot of current state | Manual save API |
| Verify save appears in save slot | `GET /saves/{save_slot_id}` shows increased session count | Save slot update |

### Step 8.3: Load Saved State

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Navigate to `/zh/saves`, select save slot | Shows saved session | Save slot listing |
| Click saved session, "Load" | `POST /sessions/{session_id}/load` activates session | Load session API |
| Redirect to `/zh/game/{session_id}` | Game session page loads | Session restoration |

### Step 8.4: Verify State Preservation

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Check StatePanel | Location, HP, realm match pre-save values | State preservation |
| `GET /player/sessions/{id}/inventory` | Item list and quantities match pre-save | Inventory preservation |
| `GET /player/sessions/{id}/quests?status=all` | Quest statuses and stages match pre-save | Quest preservation |
| `GET /player/sessions/{id}/relationships` | All relationship scores match pre-save | Relationship preservation |
| `GET /player/sessions/{id}/locations` | Discovered locations match pre-save | Location discovery preservation |
| `GET /sessions/{id}/adventure-log` | All previous turn entries present | Adventure log preservation |

### Step 8.5: Adventure Log Review

| Player Input | Expected System Response | Feature Verified |
|-------------|-------------------------|------------------|
| Check LogPanel | All turns from playthrough listed chronologically | LogPanel, `GET /sessions/{id}/adventure-log` |
| Click on a log entry | Entry expands showing full narration and actions | Log entry detail |

---

## V1 Readiness Checklist

### Core Game Loop

| Feature | Status | Verified By |
|---------|--------|-------------|
| User registration & login | ☐ | Phase 1, Step 1.1 |
| Save slot creation | ☐ | Phase 1, Step 1.2 |
| New game start | ☐ | Phase 1, Step 1.3 |
| Turn-based action input | ☐ | Phase 2, Step 2.1 |
| SSE streaming narration | ☐ | Phase 2, Step 2.1 |
| Streaming fallback to POST | ☐ | Phase 2, Step 2.1 |
| Recommended actions | ☐ | Phase 2, Step 2.1 |
| World time advancement | ☐ | Phase 1, Step 1.4 |

### Location & Exploration

| Feature | Status | Verified By |
|---------|--------|-------------|
| LocationMapPanel rendering | ☐ | Phase 1, Step 1.4 |
| Current location highlight | ☐ | Phase 2, Step 2.2 |
| Connection graph display | ☐ | Phase 2, Step 2.2 |
| Danger level badges | ☐ | Phase 2, Step 2.4 |
| Accessible/locked indicators | ☐ | Phase 2, Step 2.6 |
| Location detail API | ☐ | Phase 2, Step 2.4 |
| Accessible filter parameter | ☐ | Phase 2, Step 2.6 |
| NPC presence at location | ☐ | Phase 2, Step 2.5 |

### NPC & Dialogue

| Feature | Status | Verified By |
|---------|--------|-------------|
| NPC portrait display | ☐ | Phase 3, Step 3.1 |
| NPC dialogue via turns | ☐ | Phase 3, Step 3.1 |
| Relationship-gated dialogue | ☐ | Phase 3, Step 3.2 |
| Hidden NPC discovery | ☐ | Phase 3, Step 3.3 |

### Inventory & Items

| Feature | Status | Verified By |
|---------|--------|-------------|
| InventoryPanel rendering | ☐ | Phase 1, Step 1.4 |
| Rarity color coding | ☐ | Phase 4, Step 4.1 |
| Category filtering | ☐ | Phase 4, Step 4.1 |
| Item detail expansion | ☐ | Phase 4, Step 4.8 |
| Inventory stats | ☐ | Phase 4, Step 4.1 |
| Item acquisition | ☐ | Phase 4, Step 4.2 |
| Consumable usage | ☐ | Phase 4, Step 4.3 |
| Equipment | ☐ | Phase 4, Step 4.5 |
| Gift to NPC | ☐ | Phase 4, Step 4.6 |
| Key item acquisition | ☐ | Phase 4, Step 4.7 |

### Quest System

| Feature | Status | Verified By |
|---------|--------|-------------|
| QuestJournalPanel rendering | ☐ | Phase 1, Step 1.4 |
| Quest list with status badges | ☐ | Phase 5, Step 5.1 |
| Quest detail view | ☐ | Phase 5, Step 5.1 |
| Objective checklist | ☐ | Phase 5, Step 5.2 |
| Progress bar | ☐ | Phase 5, Step 5.2 |
| Quest stage advancement | ☐ | Phase 5, Step 5.2 |
| Side quest support | ☐ | Phase 5, Step 5.4 |
| Quest completion | ☐ | Phase 5, Step 5.5 |
| Quest abandonment | ☐ | Phase 5, Step 5.7 |
| Hidden quest visibility trigger | ☐ | Phase 5, Step 5.6 |
| Quest status filter | ☐ | Phase 5, Step 5.4 |

### Combat System

| Feature | Status | Verified By |
|---------|--------|-------------|
| CombatPanel rendering | ☐ | Phase 6, Step 6.1 |
| Combat start API | ☐ | Phase 6, Step 6.1 |
| Attack action | ☐ | Phase 6, Step 6.2 |
| Defend action | ☐ | Phase 6, Step 6.3 |
| Skill action | ☐ | Phase 6, Step 6.4 |
| Item use in combat | ☐ | Phase 6, Step 6.5 |
| Flee action | ☐ | Phase 6, Step 6.6 |
| NPC counter-attack | ☐ | Phase 6, Step 6.2 |
| HP bar updates | ☐ | Phase 6, Step 6.2 |
| Combat event feed | ☐ | Phase 6, Step 6.2 |
| Win/lose/escape conditions | ☐ | Phase 6, Step 6.7 |
| Combat end & return to game | ☐ | Phase 6, Step 6.7 |
| Combat events history API | ☐ | Phase 6, Step 6.8 |
| Combat test page | ☐ | Phase 6, Step 6.9 |

### Relationship System

| Feature | Status | Verified By |
|---------|--------|-------------|
| RelationshipPanel rendering | ☐ | Phase 3, Step 3.1 |
| Trust/respect/fear scores | ☐ | Phase 3, Step 3.1 |
| Color-coded progress bars | ☐ | Phase 7, Step 7.1 |
| Sort by trust/respect/fear | ☐ | Phase 3, Step 3.4 |
| Relationship summary | ☐ | Phase 3, Step 3.4 |
| NPC detail expansion | ☐ | Phase 3, Step 3.4 |
| Trust building via dialogue | ☐ | Phase 7, Step 7.1 |
| Trust building via gifts | ☐ | Phase 7, Step 7.1 |
| Suspicion mechanic | ☐ | Phase 7, Step 7.3 |
| Interaction history | ☐ | Phase 7, Step 7.5 |

### Save/Load System

| Feature | Status | Verified By |
|---------|--------|-------------|
| Manual save | ☐ | Phase 8, Step 8.2 |
| Load session | ☐ | Phase 8, Step 8.3 |
| State preservation (location) | ☐ | Phase 8, Step 8.4 |
| State preservation (inventory) | ☐ | Phase 8, Step 8.4 |
| State preservation (quests) | ☐ | Phase 8, Step 8.4 |
| State preservation (relationships) | ☐ | Phase 8, Step 8.4 |
| State preservation (locations) | ☐ | Phase 8, Step 8.4 |
| Adventure log preservation | ☐ | Phase 8, Step 8.4 |
| LogPanel review | ☐ | Phase 8, Step 8.5 |

### Admin & Infrastructure

| Feature | Status | Verified By |
|---------|--------|-------------|
| `GET /admin/health` — DB status | ☐ | Pre-Flight |
| `GET /admin/health` — Redis status | ☐ | Pre-Flight |
| `GET /admin/health` — Provider status | ☐ | Pre-Flight |
| `GET /admin/metrics` — API latency | ☐ | Pre-Flight |
| `GET /admin/metrics` — LLM calls | ☐ | Pre-Flight |
| `GET /admin/metrics` — Session count | ☐ | Pre-Flight |
| `GET /admin/release-readiness` — Migrations | ☐ | Pre-Flight |
| `GET /admin/release-readiness` — Content seeded | ☐ | Pre-Flight |
| `GET /admin/release-readiness` — Env vars | ☐ | Pre-Flight |
| `GET /admin/release-readiness` — Test gate | ☐ | Pre-Flight |

### Frontend Panels

| Panel | Component | Status | Verified By |
|-------|-----------|--------|-------------|
| Quest Journal | `QuestJournalPanel.tsx` | ☐ | Phase 5 |
| Inventory | `InventoryPanel.tsx` | ☐ | Phase 4 |
| Location Map | `LocationMapPanel.tsx` | ☐ | Phase 2 |
| Relationship | `RelationshipPanel.tsx` | ☐ | Phase 3, 7 |
| Combat | `CombatPanel.tsx` | ☐ | Phase 6 |
| Narration | `NarrationPanel.tsx` | ☐ | Phase 2 |
| State | `StatePanel.tsx` | ☐ | Phase 1 |
| Log | `LogPanel.tsx` | ☐ | Phase 8 |
| Action Input | `ActionInput.tsx` | ☐ | Phase 2 |
| Recommended Actions | `RecommendedActions.tsx` | ☐ | Phase 2 |
| Settings | `SettingsPanel.tsx` | ☐ | Phase 1 |

### i18n

| Feature | Status | Verified By |
|---------|--------|-------------|
| Chinese (zh) locale — default | ☐ | All phases |
| English (en) locale | ☐ | Manual switch test |
| Game namespace translations | ☐ | Panel labels |
| Combat namespace translations | ☐ | Phase 6 |

### Known Gaps (Not V1 Blockers)

| Gap | Notes |
|-----|-------|
| RelationshipPanel basic integration done on game session page | Component rendered in `GameSessionContent` layout; richer interaction flows deferred to P10+ |
| No explicit character creation UI | Game starts with default character state |
| Item usage only via free-text turns | No click-to-use button in InventoryPanel |
| Combat not auto-triggered from game turns | Requires manual `POST /combat/start` or test page |
| NPC dialogue only via free-text turns | No click-to-talk button on NPC portraits |

---

*End of V1 Playthrough Script*
