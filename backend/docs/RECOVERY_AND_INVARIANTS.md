# Backend Architecture: Recovery Workflow and Progression Invariants

> **当前阶段实测基线（不是对所有运行配置的普遍保证）**：本节记录回合原子性与认领/恢复链路的阶段验证结论；后续通用说明中未列出的旧路径不应推断为同样满足这些不变量。当前选定的产品演进目标与路线入口见根目录 README、[RFC](../../docs/design/llm_rpg_engine_design_summary_2026-10-08.md) 和[四阶段路线图](../../docs/design/roadmap-draft.md)。

## Current Turn Commit and Recovery Invariants

> **勘误（2026-10-15，阶段一补齐）**：本文件此前记录的「旧 worker 不得提交」在**提交路径上并未接线**——租约/generation 只在失败路径（`abort_claim`）生效，最终事实提交按事务 ID 直接更新状态，且认领心跳在生产零调用。**helper 级 fencing 不等于生产提交保证。** 该缺口已由阶段一补齐计划修复，证据见 [`../../.omo/evidence/phase1/20261015-p1-completion/`](../../.omo/evidence/phase1/20261015-p1-completion/)（W1a/W1b/Fix-1 复核记录）。旧验收记录保留原文，不作为当前保证的依据。

- **数据库是权威真相**。回合必要效果经 Unit of Work 原子提交，并由单一权威提交点持久化；该提交失败时不得留下半回合持久化残留。回合生产入口为 `execute_turn_service`。
- **认领与幂等按会话隔离**：`(session_id, idempotency_key)` 唯一；同键输入指纹不同返回 409；活跃认领快速返回 `turn_in_progress`；已提交的同键请求只恢复既有结果，不重放回合。请求指纹**由服务端始终重算**，客户端传入值不参与裁决。
- **回合编号在会话锁内判定**：编号只在取得会话级 advisory 锁之后计算，并以认领 token 为准；后续步骤不得另算编号覆盖 token。这消除了「陈旧编号撞上竞争者已提交回合」的路径。
- **租约与 fencing generation**：认领使用租约及 generation fencing。最终提交以**完整 token**（transaction_id、session、key、fingerprint、turn_no、generation）+ `status='pending'` + **SQL 内 `clock_timestamp()` 租约比较**做 CAS，失败整体回滚；旧 worker 不得提交。模型等待期间不持有业务事务或写锁（读事务在每次模型调用前显式结束）。
- **心跳与预算**：认领后由**独立 Session** 周期续租（默认 15s / 90s 租约）；进入最终写事务前停止并有界 join 心跳，停止失败或已失认领则拒绝提交。服务级总预算默认 600s，到期停止续租并在提交前复检。
- **提交回执不确定**：`db.commit()` 抛错时按**完整 token** 重读认领行确认归属；只有确认属本 worker 且已提交才走只读恢复，否则走 abort（abort 自身亦为完整 token CAS，不会覆盖接替者）。
- **历史认领裁决**：存在 `player_turn` 时只恢复，不重放；无事件且无残留时裁为 `expired`；发现残留或未知指纹时裁为 `legacy_inconsistent`，不重放也不清理。
- **准备期零业务写**：模型等待期间的初始化、移动、任务推进、事件与校验报告、模型审计均以「计划/缓冲」形式存在，随最终权威事务一次性落库；准备段不再对游戏状态产生可见写入。
- **澄清语义**：明确需澄清的输入（含确定性解析得到 `move` 但缺目标）记为零耗时回合——回合号增加、`actions_committed=0`、世界时间不变，且不产生移动/任务/NPC/调度/认知写入；首回合澄清不提前初始化运行状态。澄清文案与旁白一样经过泄漏校验，不通过则使用确定性模板。
- **提交后旁白**：旁白模型调用发生在权威提交**之后**，只消费本回合冻结、白名单可见的上下文（含最终裁决后的时间与仍被接受的反应）；表现采用 `template → finalized` CAS，并同时定稿该回合 narration `game_event` 的表现文本。旁白生成/定稿失败保留模板，不回滚已提交事实。同键恢复为只读；历史部分状态标为 `legacy_partial`。
- **非回合写者的锁协议**：可修改状态指纹集合的非回合写者（当前为放弃任务）在读取之前取得同一会话级 advisory 锁，顺序为「会话锁 → 读取 → 校验 → 写入 → 单次提交」，因此不能落入回合的「重验 → 提交」窗口。
- **流式语义边界**：当前不提供逐片 SSE 续传；断开后可恢复已提交结果，但不保证从断点续发先前片段。外部 LLM 调用不承诺 exactly-once；数据库事务不能撤销已发生的外部调用。
- **生产 LLM 权限边界（阶段二，2026-10-16）**：生产模型输出只以 `contract_version=2` 严格契约进入回合路径（递归 `extra=forbid`，仅允许去首尾空白与剥离整串代码围栏；拒绝重复键、非有限常量、尾随内容与未知字段），且**不经过宽松修复器**。模型只能引用本次上下文给出的稳定 ID；actor、session、transaction、turn、source、可见性上限与审计元数据由服务端生成。动作合法性、目标权限、实际结果与耗时由引擎裁决：`attack`/`interact`/`action`/`unknown` 及其余未授权动作明确返回 `unsupported`/无效果，不假装成功。world/scene 阶段为**引用型**（只引用本回合引擎事件、从引擎合法推荐动作中选择，不创建事实、effects 或时间变化）。模型自由文本不得成为 `memory_facts`、`npc_beliefs`（断言真相的类型）、`memory_summaries` 或事件公开载荷；话语只形成「听见某人如此声称」的 `belief_type="speech"` 记忆，不升级为世界真相。`used_memory_ids` 的权限检查不随 `NPC_MEMORY_FIRST_ENABLED` 关闭，空可用集合不允许引用任何记忆。受管事务下 `game_events`/`state_deltas`/校验报告/认知写入失败必须传播并整体回滚。`state_deltas.source_event_id` 指向引擎动作事实事件，**不指向 narration 表现事件**。公开 `action_resolution` 摘要只含四个粗粒度原因码（不泄露隐藏实体是否存在），同键恢复只读保存值，表现 CAS 不得修改它。证据见 [`../../.omo/evidence/phase2/20261016-p2-authority/`](../../.omo/evidence/phase2/20261016-p2-authority/)。
- **时间模拟纵切片边界（阶段三，2026-10-17）**：该能力**按世界 opt-in**（`World.ruleset_json.phase3_profile`）；无标记的世界继续走旧路径，标记未知/结构损坏/运行标记缺失而会话已有业务状态时**明确拒绝**该回合，绝不静默回落到旧调度器。权威游标是会话内单调 `logical_tick`；日历（`session_states.current_time`）只是投影，由回合起始显示时间加**实际**经过分钟一次算出，**不得**用跨季会重置的 `WorldTime.total_minutes` 反算游标。一次玩家动作只推进一次世界：准入（既有移动/授权校验）与完成效果分离，完成、同刻竞争、资源冲突与中断全部在同一个 `WorkingState` 上按 `(tick, phase, stable actor, step)` 排序判定，同刻步骤即时读取前一步结果。中断在 t 发生即取消玩家未发生的完成效果、排空同刻独立步骤并停在 t，t 之后步骤保留给下一回合且不得重放；**被截短的实际时长不再经过 `TimeAdvanceValidator`**（二次 clamp 会被类别下限推过中断时刻）。被中断/到达被拒的移动不得写目标位置、到达任务、成功旁白或成功计数。唯一物品是**一行**库存记录，只更新其 owner（不删除重建、不为败者复制）；重复行、丢失实例、非法 quantity/owner 明确拒绝且不自动修复。游标、NPC 位置与行程、owner、调度状态、引擎事件、Delta 与已启用的必要认知在**同一权威事务**内提交，任一必要写失败整体回滚。公开出口（REST/SSE 响应、旁白、模型上下文、推荐动作、玩家 replay、地点详情、库存详情、公开计数）只使用显式白名单投影：`__` 前缀的内部命名空间键不进入 canonical state、模型上下文或 replay；离场事实按其**当时**的感知主体裁定可见性。模拟会话的历史快照回退**明确拒绝**（`SnapshotRewindRefusedError`），普通会话快照行为不变。证据见 [`../../.omo/evidence/phase3/20261017-p3-timesim/`](../../.omo/evidence/phase3/20261017-p3-timesim/)。

- **配置化内容能力边界（阶段四，2026-10-17）**：新能力由**包 schema 版本**分派——`pack.yaml` 无 `schema_version` 走旧 loader/validator，`schema_version: 2` 走 `content_v1` 严格路径，其余值明确拒绝（不隐式 default）；世界侧由 `World.ruleset_json.content_profile.id == "content_v1"` 分派，同时携带 `phase3_profile` 即拒绝（`CONTENT_BINDING_CONFLICT`）。**不可变发布**：dry-run 零 DB 写入；draft 发布在一个受管 UoW 内完成「校验 → 物化独立 World 与全部模板 → 保存 canonical `runtime_bundle_json`/`runtime_hash` → 置 published」，只有一个服务级提交点；`(story_package_id, version)` 冲突明确报错、**不 upsert 覆盖**；每个发布版本使用独立 World/templates，`SPV.world_id` 与 `World.story_package_version_id` 双向一致。已发布版本的语义字段（`runtime_bundle_json`/`runtime_hash`/`runtime_schema_version`/`source_hash`/`world_id`/`story_package_id`/`version`）在仓储层、importer、CLI 与 admin 入口一律冻结（`CONTENT_FROZEN_VERSION`），metadata/status 转换仍可用。**运行绑定**：会话/实例固定保存的 `version_id`，服务器保留键 `__content_binding` 的四个字段（version_id、runtime_hash、bundle_schema_version、engine_rules_version）逐项重验，任一处漂移或缺失/损坏/未来 schema 一律**明确拒绝**该回合，不静默回落 legacy、不自动改绑 latest；每回合从 DB bundle 重新编译，源目录变化不影响已发布游戏。**运行态**：`content_v1` 使用独立命名空间 `__content_simulation`，与 `__phase3_simulation` 双向互不解释；会话路线覆盖、声明 flags、有限规则进度、待执行步骤与 CurrentPlan 只写会话载体，**绝不回写共享 `Location.access_rules` 或任何版本模板**；恢复顺序为「bundle 默认值 → 会话覆盖」。规则结算沿用既有 `(tick, phase, stable actor, step_key)` 与 256 步预算，另加 Condition 深度 8、节点 128、recipe 16 步、每 advance 计划重评估 64 的预算，超限**整回合失败**、不截取可提交前缀；Effect 组先在临时副本整体校验再应用，前置条件失败留下明确无效果结果。NPC 计划只在四个决策边界重选，按 priority 降序 + 稳定 id 字典序冻结 tie-break，失败无状态变更并立即 fallback，**不逐回合调用 LLM 托管离场 NPC**。**认知**：从已裁定的引擎事件生成，观察者按事件**发生当时**的位置求（不得用推进终点回溯），`memory_type=episodic`、`memory_kind ∈ {action, observation}`、`visibility ∈ {npc_private, npc_shared}`、`source_event_ids_json` 保存真实 `game_events.id`；玩家知识用独立 `MemoryFact.source_game_event_id` FK，不占用既有指向 `event_logs` 的 `source_event_id`；派生以 `derivation_key` 去重，重试不重复认知。旧 phase3 的 `visibility="private"` 与 `action`/`observation` 类型只做**读取期窄映射**，不原位改数据、不把未知 private 变 shared。**玩家投影**：地点/关系/库存/replay 与模型上下文共用同一可见性白名单，私有命名空间、未感知 NPC 与 owner、未来步骤与隐藏计划不出现在任何玩家或模型出口；`short_memory_summary` 不再当作公开 mood。**快照**：`content_v1` 允许创建期只读 baseline 捕获，但 apply/restore/rewind 继续明确拒绝，且守卫早于任何写入。证据见 [`../../.omo/evidence/phase4/20261017-p4-content/`](../../.omo/evidence/phase4/20261017-p4-content/)；规范正文见 [`../../docs/design/phase4-content-v1-spec.md`](../../docs/design/phase4-content-v1-spec.md)。

### Measured gaps and limitations

阶段一补齐计划（[`.omo/plans/phase1-turn-foundation-completion.md`](../../.omo/plans/phase1-turn-foundation-completion.md)）已完成 W0–W4 与收口修复；**全量测试在基线条件（不导出 PG 变量）下只剩 4 项既有失败**（`test_runtime_entrypoint::test_required_endpoints_exist`、`test_llm_npc_engine::TestExecuteNPCStage::test_build_npc_context_excludes_hidden_identity`、`test_p10c_npc_decision_adapter::TestPromptMemoryFirstRules` ×2），无设计内红灯。仍存在的边界如下（不得据此推断更强的保证）：

- **SQLite 下独立连接重验不可测**；并发/锁/租约语义以 PostgreSQL 为准，不能用 SQLite 结果替代。
- **模型调用不被预算抢占**：预算到期只停止续租并在提交前复检（拒绝落库未提交结果），不会中断进行中的模型调用。
- **参数化事务测试观测各阶段入口**；「阶段内模型调用前关闭读事务」由代码检视（`_end_read_transaction` 调用点）覆盖，尚无独立的运行时断言。
- **旧客户端指纹兼容（已接受为偏差，2026-10-15 决定）**：历史中由客户端传入并落库的 `request_fingerprint` 记录，同键重试会得到 `fingerprint_conflict`（明确拒绝、不重放、不重写），而非计划措辞中的 `legacy_inconsistent` 分类。该行为安全，但不满足计划退出门第 8 条的措辞；彻底对齐需要额外的持久标记来区分「客户端值」与「服务端值」，会改动最敏感的认领裁决代码，故按已记录偏差接受。
- **首回合种子记忆（`NPC_MEMORY_FIRST_ENABLED`）** 未纳入 overlay：该开关开启且首回合存在 major NPC seed bundle 时，第一回合上下文看不到本应初始化的种子记忆；既有会话不受影响。
- **测试隔离缺陷（已定位并修复）**：`alembic/env.py` 曾以默认参数调用 `fileConfig(config.config_file_name)`，而 `fileConfig` 默认 `disable_existing_loggers=True`，会把调用前已存在的 logger 全部禁用。`tests/integration/test_turn_postgres_foundation.py` 会真实执行 `alembic upgrade`，因此同一进程内**之后**的测试 `caplog` 收不到任何记录——表现为全量在导出 PG 变量（迁移真的执行）时出现 3 例 `test_asset_provider_resolver` 失败（`assert len(caplog.records) == 3` 得到 `0`）；不导出 PG 变量的基线全量无此失败。实测 `llm_rpg.assets.provider_resolver` 的 `disabled` 由 `False` 变为 `True`。**这同时是运维隐患**：任何在进程内跑迁移的代码都会静默关掉应用日志。已改为 `fileConfig(config.config_file_name, disable_existing_loggers=False)`（只让 ini 配置它自己声明的 logger）。修复后：最小复现对 36 passed；导出 PG 变量的全量由 7 failed 降为 4 项既有失败（3804 passed / 10 skipped），基线全量不变（3782 passed / 32 skipped）。
- **心跳 Session 未设数据库/连接池超时**：`stop()` 有界 join 但不能中断阻塞中的数据库操作；连接中断、池耗尽等场景需故障注入验证（未做）。


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
