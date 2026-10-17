# 阶段四内容能力规范 v1（`content_v1`）

> **状态：W1 冻结契约。** 本文件是阶段四实施与验收的规范来源。实现、JSON Schema、golden trace 与测试断言都必须与本文件一致；不一致时以本文件为准，除非先修订本文件。
>
> 基线：`31abb0df6bea166baa6190396d4a6e556e282f40`。范围依据：[四阶段路线图](roadmap-draft.md#L38-L49)；设计依据：[设计摘要](llm_rpg_engine_design_summary_2026-10-08.md#L93-L112)。

---

## 0. 版本标识（互不混用）

| 标识 | 常量 | 值 | 载体 |
|---|---|---|---|
| 包 schema 版本 | `PACK_SCHEMA_VERSION` | `2` | `pack.yaml: schema_version` |
| bundle schema 版本 | `BUNDLE_SCHEMA_VERSION` | `1` | `RuntimeBundle.schema_version` |
| 引擎规则版本 | `ENGINE_RULES_VERSION` | `1` | 参与 runtime hash；存于 SPV.runtime_schema_version 的伴生字段 |
| 解释器 profile id | `CONTENT_PROFILE_ID` | `"content_v1"` | `World.ruleset_json.content_profile` |
| 会话运行态命名空间 | `CONTENT_NAMESPACE` | `"__content_simulation"` | `session_states.global_flags_json`、`session_npc_states.hidden_plan_state`、`scheduled_events.trigger_conditions_json` |
| 旧阶段三 profile id | `PROFILE_ID` | `"trial_micro_v1"`（既有，不改） | `World.ruleset_json.phase3_profile` |

**分派规则（不得隐式 default）**

- `pack.yaml` 无 `schema_version` 键 → 走既有 `load_content_pack` / `ContentValidator` 旧路径，**不**进入 v2。
- `schema_version == 2` → 走 v2 严格路径。
- `schema_version` 为其他任何值（含 `1`、`"2"`、`2.0`、`null`）→ **明确拒绝**，报 `CONTENT_PACK_SCHEMA_UNSUPPORTED`。
- 世界 `ruleset_json` 含 `content_profile.id == "content_v1"` → 走 content_v1 运行路径；含 `phase3_profile` → 走既有阶段三路径；两者皆无 → legacy 路径。同时含两者 → 拒绝（`CONTENT_BINDING_CONFLICT`）。

---

## 1. 包格式（`schema_version: 2`）

### 1.1 目录与文件

包根目录下的文件按固定名字识别；未列出的文件被忽略（不报错），但**列出的文件若存在则必须严格解析**。

| 文件 | 必需 | 内容 |
|---|---|---|
| `pack.yaml` | 是 | manifest（含 `schema_version: 2`） |
| `world.yaml` | 是 | 唯一 `World` 对象 |
| `locations.yaml` | 是 | `Location[]` + `Route[]` |
| `characters.yaml` | 否 | `Character[]` |
| `items.yaml` | 否 | `Item[]` |
| `initial_state.yaml` | 是 | `InitialState` |
| `rules.yaml` | 否 | `Rule[]`（Trigger/Condition/Effect） |
| `schedules.yaml` | 否 | `Schedule[]` |
| `goals.yaml` | 否 | `Goal[]` + `PlanRecipe[]` |
| `knowledge.yaml` | 否 | `KnowledgeRule[]` |
| `factions.yaml` | 否 | 既有 faction 静态字段 |
| `plot_beats.yaml` | 否 | 受限 PlotBeat |
| `quests.yaml` | 否 | 受限 Quest |
| `prompts.yaml` | 否 | 呈现层，**不进** RuntimeBundle |

### 1.2 严格解析规则

1. 顶层与所有嵌套模型递归 `extra="forbid"`：未知键 → `CONTENT_UNKNOWN_FIELD`。
2. 同一 YAML 映射内重复键 → `CONTENT_DUPLICATE_KEY`（用自定义 loader 检测，`yaml.safe_load` 默认静默覆盖）。
3. 拒绝 YAML 代码标签（`!!python/...`）、递归 alias、任意模块名、动态 import：只使用 `yaml.SafeLoader` 并显式移除 `python/*` 构造器。
4. 浮点必须有限（拒绝 `NaN`/`Infinity`/`-Infinity`）→ `CONTENT_NON_FINITE_NUMBER`。
5. 类型错误 → `CONTENT_TYPE_ERROR`；值域错误 → `CONTENT_VALUE_RANGE`。
6. 未知 operator / enum / params 一律**拒绝**，不修复、不猜测、不交给 LLM 补全。
7. 未支持的高级条件、奖励与对象在导入时报错（`CONTENT_UNSUPPORTED_FEATURE`），不允许只记录文件名却声称已加载执行。

### 1.3 路径安全

- 所有引用文件路径必须解析后仍位于包根目录内（`Path.resolve()` 后 `is_relative_to(pack_root.resolve())`），否则 `CONTENT_PATH_ESCAPE`。
- 不跟随指向包根外的 symlink。
- 不远程下载依赖。
- **一次捕获**：加载时先把每个文件的字节读入内存并计算 hash，之后所有校验、canonical 化与发布都使用同一份字节；不允许校验后再读第二遍。

### 1.4 对象通用字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 包内**跨类型唯一**的稳定 ID；`^[a-z][a-z0-9_]{0,63}$` |
| `name` | string | 是 | 人类可读名称 |
| `description` | string | 否 | 默认 `""` |
| `tags` | string[] | 否 | 默认 `[]`；元素去重、canonical 时排序 |
| `enabled` | bool | 否 | 默认 `true` |

`id` 不得为 `"player"`、`"world"`（保留字）→ `CONTENT_RESERVED_ID`。

### 1.5 各对象字段

#### `World`（`world.yaml: world`）

`id, name, genre, theme, lore_summary, status, start_hour(0-23,默认8), start_minute(0-59,默认0), start_tick(int>=0,默认0)`

#### `Location`（`locations.yaml: locations[]`）

`id, name, description, tags, parent_id(可空，必须是本包 location), access_rules.always_accessible(bool,默认true)`

#### `Route`（`locations.yaml: routes[]`）

`from, to, open(bool,默认true), travel_ticks(int>=1,默认1), bidirectional(bool,默认false)`

- `from`/`to` 必须是本包 location → `CONTENT_DANGLING_REF`。
- 重复有向边 → `CONTENT_DUPLICATE_ROUTE`。
- `bidirectional: true` 在 canonical 化时展开为两条有向边。

#### `Character`（`characters.yaml: characters[]`）

`id, name, description, tags, public_identity, personality, initial_location_id, alive(bool,默认true)`

#### `Item`（`items.yaml: items[]`）

`id, name, description, tags, item_type(string), quantity(必须为 1)`

> v1 只支持具名、`quantity == 1` 的实例，不开放堆叠/拆分/增发。`quantity != 1` → `CONTENT_UNSUPPORTED_FEATURE`。

#### `InitialState`（`initial_state.yaml`）

```yaml
player:
  location_id: east_bank
  alive: true
characters:
  - id: guard
    location_id: watch_house
    alive: true
items:
  - id: lantern
    owner: location:watch_house
routes:
  - from: east_bank
    to: bridge
    open: true
flags:
  bridge_open: true
schedules:            # 可选：初始日程的显式起点
  - character_id: guard
    activity: patrol
    location_id: watch_house
    start_tick: 0
```

- `owner` 语法：`player` | `location:<location_id>` | `character:<character_id>`；非法 → `CONTENT_INVALID_OWNER`。
- `flags` 值类型限定 `bool|int|string`；未在 `flags` 声明的 key 不得被 Condition 读取（编译期检查）→ `CONTENT_UNDECLARED_FLAG`。

#### `Rule`（`rules.yaml: rules[]`）

`id, description, trigger, condition(可空=恒真), effects[], fire_policy, priority(0-100,默认0), enabled`

#### `Schedule`（`schedules.yaml: schedules[]`）

`id, character_id, activity, location_id, at_tick(int>=0), window_ticks(int>=1,默认1), default_activity(bool,默认false)`

- 语义：提供**候选目标/行动**，不是按表传送。首版不做无限每日循环。
- 同一 character 的 `at_tick` 区间不得重叠 → `CONTENT_SCHEDULE_OVERLAP`。

#### `Goal`（`goals.yaml: goals[]`）

`id, character_id(可空=任意), priority(0-100), description, preconditions(Condition,可空), completion(Condition,可空), recipe(PlanRecipe.id), initial_status(inactive|active,默认 inactive)`

- 同优先级按稳定 `id` 字典序决定 → 冻结的 tie-break。

#### `PlanRecipe`（`goals.yaml: recipes[]`）

`id, steps[]`，每步：`action ∈ {move, wait, take, use, transfer}`, `target`(move: location_id；take/use/transfer: item_id), `ticks`(int>=1，wait 必需，move 可空=用 Route.travel_ticks)。

- 每 recipe 最多 16 步 → `CONTENT_RECIPE_TOO_LONG`。

#### `KnowledgeRule`（`knowledge.yaml: knowledge_rules[]`）

`id, source_event_types[]`, `observers ∈ {actor, at_location, all_alive}`, `memory_kind ∈ {action, observation}`, `visibility ∈ {npc_private, npc_shared}`, `template`(带 `{actor}`/`{target}`/`{item}` 占位)

- 模板占位符集合封闭，未知占位符 → `CONTENT_UNKNOWN_PLACEHOLDER`。

#### `Quest`（`quests.yaml: quests[]`，受限）

`id, name, description, steps[]`，每步 `{id, location_id}`。完成条件：玩家到达指定 Location。**不含奖励**。

#### `PlotBeat`（`plot_beats.yaml: plot_beats[]`，受限）

`id, name, description, trigger`（同 DSL Trigger 子集：`on_action_completed` 或 `on_time_crossed`）, `effects`（仅 `flag_set`）, `visibility`

- 原任意 `params` 的执行权限**不开放**；出现未支持 effect → `CONTENT_UNSUPPORTED_FEATURE`。

---

## 2. 稳定 ID 与引用

1. 对象 `id` 在包内跨类型唯一 → 冲突报 `CONTENT_DUPLICATE_ID`。
2. 完整逻辑身份 = `package_id/object_id`（记作 `stable_ref`）。
3. 引用必须同时声明期望 kind；kind 不符 → `CONTENT_KIND_MISMATCH`。
4. **仅允许包内引用**；跨包引用明确不支持 → `CONTENT_CROSS_PACK_REF`。
5. 不同包可使用相同局部 ID；运行映射以 `(version_id, stable_ref)` 为键，绝不能串包/串版本。
6. UUID 是物化与会话实例身份，不替代作者稳定 ID。编译器构造显式映射：
   `stable_ref → version-scoped template UUID → session instance UUID`。
7. 发布前必须拒绝：同包同版本同 ID 重复、悬空引用、跨 kind 引用、非法 owner、路线两端不存在、重复有向边、不可识别计划目标。
8. 地点 code/name/alias 解析以本包为范围；会产生歧义的别名 → `CONTENT_AMBIGUOUS_ALIAS`。默认世界的既有中文 alias 行为不重写。

---

## 3. 规范化工件 `RuntimeBundle` 与 hash

### 3.1 内容

`RuntimeBundle` 保存所有执行与呈现所需的配置对象，**不只是**源文件名、实体数量或 hash：

```
world, locations[], routes[], characters[], items[],
initial_state, rules[], schedules[], goals[], recipes[], knowledge_rules[],
quests[], plot_beats[], factions[]
```

### 3.2 规范化规则

- 排序**无语义顺序**的集合：`locations/routes/characters/items/rules/schedules/goals/recipes/knowledge_rules/quests/plot_beats/factions` 按 `id`（或 `(from,to)`）字典序；所有 `tags` 排序去重；所有对象键排序。
- **保留**有语义顺序的 `PlanRecipe.steps`（顺序即执行顺序）。
- 补齐正式默认值（使“显式写默认值”与“省略”产生同一 bundle）。
- 不包含：墙钟时间、绝对路径、随机 UUID、`prompts.yaml` 内容。

### 3.3 hash

```
runtime_hash = sha256(canonical_json({
  "bundle": <canonical RuntimeBundle>,
  "bundle_schema_version": 1,
  "engine_rules_version": 1
}))
```

- 原 `source_hash` 保留既有来源指纹语义（排序拼接 `*.yaml` 内容），**不冒充** runtime hash。
- 缓存键为 `(version_id, runtime_hash, engine_rules_version)`；不得只按 package id 缓存。

---

## 4. 发布、物化与绑定

### 4.1 原子发布

1. **dry-run**：只加载、校验、编译并返回诊断，**零 DB 写入**。
2. **draft 发布**：在**一个内容管理事务**内：校验完整 bundle → 物化独立 `World` 与全部必要模板（Location/NPCTemplate/ItemTemplate/QuestTemplate）→ 保存 `runtime_bundle_json`/`runtime_hash`/`runtime_schema_version` 与引用映射 → 置 `published`。
3. 用既有 `(story_package_id, version)` 唯一约束处理竞争；同一版本内容冲突明确报错（`CONTENT_VERSION_CONFLICT`），**不 upsert 覆盖**。
4. 新 `World` 写入既有 `story_package_version_id`；其 `ruleset_json` 仅保存服务器生成的 `content_profile` 绑定。`SPV.world_id`、`World.story_package_version_id` 与 bundle/hash 必须一致，否则 `CONTENT_BINDING_MISMATCH`。
5. 每个新发布版本使用**独立** World/templates；在版本行锁内检查并完成双向关联；同一新版本只能有一个物化 World（`CONTENT_WORLD_ALREADY_BOUND`）。所有受管创建/更新入口禁止绕过 publisher 设置该绑定；运行读取也验证唯一归属。不对旧非空关联盲加会破坏历史行的全局约束。
6. 发布后的受管 API、importer、通用 update/delete 入口**禁止**修改/删除被版本冻结的语义内容；需要变化就发布新版本。审计/状态元数据也不能绕过该守卫改 bundle/hash/world（`CONTENT_FROZEN_VERSION`）。
7. 必要写入失败**全部回滚**。当前仓储在非 managed Session 下会自行 commit，因此新 publisher/实例工厂必须使用**明确的受管 UoW**（`TurnUnitOfWork` 或等价 `db.info["turn_uow"]` 标记），不能只在外层写 begin 却继续让内部仓储提交。内容管理事务与游戏回合事务职责分开，但各自只能有一个服务级提交点。

保证范围是受管写入口；不宣称能阻止任意越权直接 SQL。发现工件/物化定义损坏时**拒绝推进**，不自动修复用户状态。

### 4.2 创建、继续与普通 save 路径

- 复用既有 Session 与 PlaythroughInstance 的 version FK；Instance 的 `config_json` 保存绑定 hash/规则版本于服务器保留键 `__content_binding`，客户端不能覆盖保留键。
- 扩展用户实例入口为可选明确 `version_id` 及 opt-in `runtime_mode=content_v1`：
  - 指定版本必须属于所请求 package 且 `published`，否则 `CONTENT_VERSION_NOT_PUBLISHED` / `CONTENT_VERSION_PACKAGE_MISMATCH`。
  - 新模式只选择具有合法完整 bundle 的兼容版本；缺少工件**不能降格**为 legacy（`CONTENT_BUNDLE_MISSING`）。
  - 旧客户端未声明模式时保留原创建选择，再按所选版本类型分派。
  - 未指定 `version_id` 时仅在创建这一刻按 `(published_at DESC, version_row_id DESC)` 选择，随后永久使用保存的 ID；响应/审计记录最终选中的版本。
- 实例创建校验 user/world/version/instance 归属，在同一个创建事务写元数据、按固定 bundle 的 `InitialState` 初始化，并按现有开关处理 baseline snapshot；失败不能留下半个实例或部分基线。
- **保留现有显式 instantiate 的生命周期语义**：创建 API 可以在回合外建立初始状态；这不是模型准备期写入。后续澄清回合不能新增初始化、推进时间或修改业务状态。
- 普通 manual-save 及其他新会话创建入口若指向新版本世界，必须调用**同一绑定工厂**；不能生成指向该 world 却没有 binding 的可运行会话。该 API 对新版本世界同样创建一个新的 PI + root Session，按 `InitialState` 开局，可挂到所选 SaveSlot，不复用另一 PI、不隐式分叉。普通旧世界路径不变。
- 每回合按保存的 version 加载与验证；**不从可编辑工作树或当前 latest 补内容**。运行态头保存对应 schema/hash，Session、Instance、World、SPV 不一致即拒绝。
- 将 Session 的 version/instance 引用、Instance 的绑定、SPV 工件指纹及物化定义决策指纹加入准备期与锁内重验；相关非回合写者沿用会话锁协议。

---

## 5. 兼容矩阵（冻结）

| 数据 | 处理 |
|---|---|
| 旧 Session/SaveSlot 的 NULL version | 原路读取和继续，**不回填** latest |
| 旧 metadata-only SPV | 保留 legacy 行为/标识，不从当前目录伪造历史工件 |
| 已运行的 phase3 存档 | 原 codec、原固定规则、原 tick/owner/事件语义，**不自动转换** |
| 新 bundle 绑定实例 | 固定版本继续；发布同包新版本不影响已有游戏 |
| 新绑定缺失/损坏/未来 schema | 明确安全拒绝（`CONTENT_BUNDLE_MISSING` / `CONTENT_HASH_MISMATCH` / `CONTENT_SCHEMA_UNSUPPORTED`），不丢弃、不清理、不重放 |
| 已提交同键请求 | 只读返回保存结果，不重新解释内容或生成事实 |
| 模拟实例历史快照 apply/restore | 继续拒绝 rewind；guard 扩至新运行态和 payload，且必须早于 checkpoint/任何写入 |
| 无 `schema_version` 的包 | 旧 loader/validator 原样 |
| `schema_version: 2` 的包但引擎不认识某 effect | 导入期拒绝，不记录“已加载” |
| World 同时含 `content_profile` 与 `phase3_profile` | 拒绝 `CONTENT_BINDING_CONFLICT` |

保存 bundle/绑定**不等于**支持 rewind/branch；本阶段不放宽既有快照安全边界。

---

## 6. 最小 Typed DSL

### 6.1 Trigger（封闭）

| type | 字段 | 语义 |
|---|---|---|
| `on_time_crossed` | `due_tick: int >= 1`，`phase ∈ {environment, npc_move, item, player_continuous}`（默认 `environment`） | 处理 `(start, end]` 区间内的有限正整数 tick；`phase` 决定该规则在此 tick 的哪个结算阶段求值 |
| `on_action_completed` | `action ∈ {move, idle}`，`actor: player\|<character_id>`，`location: <location_id>`（可选） | 只消费引擎确认成功完成的受管动作；不读原始文本、未授权提案或失败动作 |

- `on_action_completed` 首版只支持引擎有明确完成事件的 move/idle 与 NPC 受管原语；不将 talk/inspect 的起点瞬时行为偷换为持续生命周期。
- `on_action_completed` 固定落在 `player_continuous` 阶段（玩家动作）或 `npc_move` 阶段（NPC 受管原语完成）。

### 6.2 Condition（只读表达式树）

组合：`all: [Condition]`、`any: [Condition]`、`not: Condition`；三者互斥，一次只能出现一个键。

原子（只能读取**已声明**的类型与字段）：

| type | 字段 | 语义 |
|---|---|---|
| `flag_equals` | `key`, `value: bool\|int\|string` | `flags[key] == value`；key 未声明 → 编译期 `CONTENT_UNDECLARED_FLAG` |
| `actor_alive` | `actor: player\|<character_id>` | |
| `actor_at_location` | `actor`, `location` | |
| `route_open` | `from`, `to` | |
| `item_owner_is` | `item`, `owner: player\|location:<id>\|character:<id>` | |
| `item_has` | `item`, `actor: player\|<character_id>` | actor 当前持有该实例 |

- 求值返回 `TRUE / FALSE / UNKNOWN`；数据缺失 = `UNKNOWN`，`not UNKNOWN = UNKNOWN`。
- **只有 TRUE 才触发 Effect**；`UNKNOWN` 视为未满足（安全默认）。
- 编译期检查：depth ≤ 8，节点数 ≤ 128 → `CONTENT_CONDITION_TOO_DEEP` / `CONTENT_CONDITION_TOO_LARGE`。

### 6.3 Effect（受限领域操作，非 teleport、非 SQL、非 callable）

| type | 字段 | 语义 |
|---|---|---|
| `flag_set` | `key`, `value` | key 必须已声明 |
| `route_set_open` | `from`, `to`, `open` | 写**会话覆盖**，不改共享 Location.access_rules |
| `npc_action_start` | `actor`, `action ∈ {move, wait}`, `target`, `ticks` | 请求领域动作；move 是请求不是传送 |
| `plan_start` | `actor`, `goal` | 启动有限计划 |
| `item_transfer` | `item`, `to: player\|location:<id>\|character:<id>` | 必须经过当前 owner、位置与唯一实例检查 |
| `item_use` | `item`, `actor` | 同上 |
| `interrupt` | `kind`, `message` | 可感知中断，产生引擎事件/Delta |
| `emit_event` | `event_type`, `payload` | 受限事件生成 |
| `event_schedule` | `rule`, `tick` | 受限调度；`tick` 必须 > 当前 tick |

- 所有变更都产出引擎事件/Delta。
- 同一规则的 Effect 组先在**临时副本**上整体校验，再一次应用至主 `WorkingState`；前置条件失败留下明确无效果结果，内部错误使整回合失败，**不应用半组**。
- 规则触发的视角明确区分 world 权威前置条件与 NPC 可知条件；NPC 目标选择不能读全局隐藏 owner/秘密 flags 来获得全知。

### 6.4 Fire policy（封闭）

| mode | 语义 |
|---|---|
| `once_per_instance` | 每实例最多触发一次 |
| `once_per_source_event` | 每来源事件最多触发一次 |

- 不做任意重试、每日无限重复或通用 `on_state_changed` 级联。
- 去重键 = `(rule_id, occurrence_key)`，其中 `occurrence_key` 对 `on_time_crossed` 为 `tick`，对 `on_action_completed` 为 `(actor, action, tick, location)`。
- 已消费终态跨回合持久化于运行态 `rules_fired`。

### 6.5 顺序、派生与预算

- 核心顺序：`(tick, phase, stable_actor, stable_step_key)`。作者 Goal priority 只用于选计划，**不隐式改变物理结算顺序**。
- 阶段顺序：ENV(1) → NPC_MOVE(2) → ITEM(3) → PLAYER_CONTINUOUS(4)。ENV 变化先于 NPC move/wait 完成，再物品操作，再玩家持续动作完成。旧 phase3 的 phase 编码与顺序不变。
- Effect 继承因果步骤的结算阶段；新派生步骤**不能**倒退时间或 phase。若目标 phase 已经过，必须显式调度至未来 tick → `CONTENT_BACKWARD_DERIVATION`。
- step key 包含绑定内容身份、rule/schedule、actor 与 occurrence。
- 预算（超限**整回合失败**，不截取可提交前缀）：

| 预算 | 值 | 错误码 |
|---|---|---|
| 每 advance 步数 | 256（既有 `MAX_STEPS_PER_ADVANCE`） | `SIMULATION_STEP_BUDGET_EXCEEDED` |
| Condition 深度 | 8 | `CONTENT_CONDITION_TOO_DEEP` |
| Condition 节点数 | 128 | `CONTENT_CONDITION_TOO_LARGE` |
| 每 recipe 步数 | 16 | `CONTENT_RECIPE_TOO_LONG` |
| 每 advance 计划重评估 | 64 | `CONTENT_PLAN_REEVAL_BUDGET` |

- 候选规则与派生步骤**均计入**预算，不只统计成功 Effect。
- one-shot 与运行进度按定义/实体存**有限**状态，不往 flags 塞无界事件日志。

### 6.6 规则执行的确定性模型（冻结）

**规则步身份**

- 一条规则在 tick `t` 命中时产生一个 `content_rule_fire` 步：
  - `actor_code = "world"`
  - `phase` = 该 trigger 决定的阶段（`on_time_crossed.phase`；`on_action_completed` 见 §6.1）
  - `step_key = f"rule:{rule_id}@{t}"`，`payload = {"rule": rule_id, "occurrence": <occurrence_key>}`
- 因此同 tick 同 phase 的多条规则按 `step_key` 的字典序结算（`rule:<id>@<t>`），这是**唯一**的规则间定序来源；作者不得依赖 YAML 书写顺序。

**Effect 的应用时机**

- Effect 在**命中该规则的那一步内立即应用**，产出引擎事件/Delta；不推迟到未来 tick 再“生效”。
- 领域动作类 Effect（`npc_action_start`、`item_transfer`、`item_use`）产生一个**派生完成步**，调度到未来 tick：
  - `npc_action_start(action=move)` → 派生 `npc_travel_arrive`，`tick = t + ticks`，phase = `npc_move`
  - `npc_action_start(action=wait)` → 派生 `npc_wait_complete`，`tick = t + ticks`，phase = `npc_move`
  - `item_transfer` / `item_use` 无派生步：立即结算，成功或产生无效果的明确失败事件
- 派生步必须满足 `derived.tick > 源步.tick`，或在同 tick 时 `derived.phase > 源步.phase`；否则 `CONTENT_BACKWARD_DERIVATION`。

**Condition 求值时机**

- Condition 在规则步**结算时**对当前 `WorkingState` 求值（因此同 tick 更早的 phase 与更早的 step_key 的结果可见）。
- 只有 `TRUE` 才应用 Effect；`FALSE`/`UNKNOWN` 都不应用，并留下明确的无效果记录（事件或 Delta 语义由实现定义，但必须可审计）。

**Fire policy 与去重**

- `occurrence_key`：`on_time_crossed` → `str(tick)`；`on_action_completed` → `f"{actor}:{action}@{tick}:{location or '-'}"`。
- `once_per_instance`：同一 `rule_id` 在实例内只允许命中一次；后续命中记为已消费，不重放。
- `once_per_source_event`：同一 `(rule_id, occurrence_key)` 只允许命中一次。
- 已消费终态持久化于运行态 `rules_fired`，跨回合不重放。

**NPC 计划决策边界（冻结）**

计划重评估**只**发生在以下边界，其他时刻不得重规划：

1. Schedule 到点（该 NPC 的 `at_tick` 进入当前 tick）。
2. 当前计划步骤**完成**（`npc_travel_arrive` / `npc_wait_complete` 成功）。
3. 当前计划步骤**失败**（到达重检失败、owner 变化、路线关闭等）。
4. 计划被显式取消。

在边界处按以下顺序选择计划（**冻结的 tie-break**）：

1. 过滤出 `character_id` 为空或等于本 NPC 的 Goal；
2. 丢弃 `preconditions` 求值不为 `TRUE` 的 Goal；
3. 丢弃 `completion` 已为 `TRUE` 的 Goal（标记 `achieved`）；
4. 按 `priority` 降序、`id` 字典序升序取第一个；
5. 无候选 → 进入稳定 `idle`（若有 `default_activity` 的 Schedule 则按其 `activity`/`location_id` 生成 `wait`，否则不产生任何步）；
6. 每次边界选择计入 `CONTENT_PLAN_REEVAL_BUDGET`（每 advance 64 次）。

**Schedule 到点步**：Schedule 的 `at_tick` 到点同样产生一个 `content_rule_fire` 步（不新增 step kind），身份为 `actor_code="world"`、`phase = environment`、`step_key = f"schedule:{schedule_id}@{tick}"`。因此它与同 tick 的规则步共用同一个定序键空间，`rule:` 与 `schedule:` 前缀的字典序即为跨类别定序。

**失败语义**

- 计划步骤失败时：**无任何状态变更**，写 `failure_code`，`status = failed`，并按上面的边界立即重新选择（同一次 advance 内）。
- 成功**只在完成时**更改位置或物品。
- 行动期间死亡、路线变化、owner 变化都在执行/完成时**重新验证**。
- 非预期状态（例如 plan 指向已不存在的 recipe step）→ 明确拒绝并失败整回合，不吞错后继续。

---

## 7. 模拟内核 `content_v1`

### 7.1 复用与状态推广

- `WorldAdvancer` 继续纯内存、无 DB/模型/墙钟/随机数；把对 `TrialRules` 的具体依赖收敛为小型规则协议（`player_completion_step` + `apply_step`），由旧 `TrialRules` 与新 `CompiledContentRules` 实现。
- `WorkingState` 增加：`item_instances: Dict[str, ItemInstanceState]`、`flags: Dict[str, Any]`、`npc_goals: Dict[str, str]`、`npc_current_plans: Dict[str, CurrentPlanState]`、`route_overrides: Dict[str, bool]`。
  - 新内容路径**只用** `item_instances`；旧单物品标量只用于旧 phase3；禁止同一运行态维护两份 owner 真相。
- 新增嵌套状态必须**深拷贝**或使用不可变值；编译后的定义不可变；测试必须验证 advance 不修改输入、不同会话不共享引用。

### 7.2 step kind（content_v1 封闭集）

复用：`npc_travel_start`、`npc_travel_arrive`、`npc_take_item`、`npc_use_item`、`player_continuous_complete`。

新增：`content_rule_fire`、`npc_wait_complete`。

- 新规则需要有限 rule-fire 与 NPC wait-complete 等 step，**不能**借用固定 `environment_interrupt` 来伪装普通路线变化。

### 7.3 会话运行态 schema

`session_states.global_flags_json[CONTENT_NAMESPACE]`：

```json
{
  "schema_version": 1,
  "profile_id": "content_v1",
  "binding_hash": "<runtime_hash>",
  "engine_rules_version": 1,
  "logical_tick": 12,
  "next_event_seq": 5,
  "rules_fired": {"<rule_id>|<occurrence_key>": "<tick>"},
  "flags": {"bridge_open": false},
  "route_overrides": {"east_bank->bridge": false},
  "pending_steps": ["<step_key>", "..."]
}
```

- 严格解码：未知键 / 缺键 / schema_version 不符 / profile_id 不符 / binding_hash 不符 → 拒绝（`CONTENT_RUN_STATE_CORRUPT` / `CONTENT_HASH_MISMATCH`）。
- 旧 phase3 codec **不解释**这一结构，反之亦然。

### 7.4 路线会话覆盖

- 路线基础定义来自不可变 bundle；动态开闭**仅写会话覆盖** `route_overrides`。
- load 顺序：`defaults → session overrides`。
- **禁止**修改共享 `Location.access_rules`。
- 玩家移动准入、完成重检、NPC 行程及可见推荐动作都必须读取**同一**会话路线视图。

### 7.5 事件与 Delta 词汇（冻结）

content_v1 只产出以下 `event_type`（引擎事实）。名称一旦冻结，`knowledge.yaml` 的 `source_event_types` 与测试断言都以此为唯一口径。

| event_type | 触发时机 | 关键 payload |
|---|---|---|
| `content_rule_fired` | 规则 Condition 为 TRUE 且 Effect 已应用 | `rule`, `occurrence`, `tick`, `effects_applied` |
| `route_changed` | `route_set_open` 生效 | `from`, `to`, `open`, `tick` |
| `flag_changed` | `flag_set` 生效 | `key`, `old_value`, `new_value`, `tick` |
| `npc_travel_started` | `npc_action_start(move)` 生效 | `npc_id`, `from`, `to`, `expected_end_tick` |
| `npc_arrived` | `npc_travel_arrive` 成功 | `npc_id`, `from`, `to` |
| `npc_wait_started` | `npc_action_start(wait)` 生效 | `npc_id`, `location`, `expected_end_tick` |
| `npc_wait_completed` | `npc_wait_complete` 成功 | `npc_id`, `location` |
| `npc_travel_failed` | 到达重检失败 | `npc_id`, `from`, `to`, `reason` |
| `item_acquired` | `item_transfer` 成功 | `item`, `from`, `to` |
| `item_take_failed` | `item_transfer` 失败 | `item`, `actor`, `reason` ∈ {`already_taken`, `actor_not_at_item`, `item_unknown`, `actor_not_alive`} |
| `item_used` | `item_use` 成功 | `item`, `actor`, `effect` |
| `item_use_failed` | `item_use` 失败 | `item`, `actor`, `reason` ∈ {`not_owner`, `already_used`, `item_unknown`, `actor_not_alive`} |
| `world_interrupt` | `interrupt` 生效 | `kind`, `message`, `tick` |
| `plan_selected` | 决策边界选中新计划 | `npc_id`, `goal_id`, `priority`, `source`, `generation`, `recipe_step`, `action`, `target`, `expected_end_tick` |
| `plan_failed` | 计划步骤失败 | `npc_id`, `goal_id`, `generation`, `recipe_step`, `failure_code` |
| `plan_achieved` | `completion` 求值为 TRUE | `npc_id`, `goal_id`, `generation` |
| `plan_blocked` | 无候选计划 | `npc_id`, `reason` |
| `player_move_completed` | 玩家移动完成 | `from`, `to`, `arrival_task`, `tick` |
| `player_action_completed` | 玩家 idle 完成 | `action_type`, `action_kind`, `tick` |

Delta 的 `path` 使用既有 `CanonicalState` 路径风格（`npcs.<id>.location`、`inventory.<item>.owner`、`world.flags.<key>`、`routes.<from>-><to>`），`operation` 为 `set`。私有/隐藏状态的 Delta `visibility_scope = "hidden"`，玩家可感知的为 `player_visible`。

**视角冻结**：`npc_arrived` / `npc_travel_started` 的观察者按事件**发生当时**的行动者位置求；`route_changed` 按事件 `from` 地点求；`world_interrupt` 由配置的 `observers` 决定（`all_alive` 表示全部存活 NPC）。不得使用推进终点位置回溯发知识。

---

## 8. Schedule / Goal / CurrentPlan

### 8.1 语义

- **Schedule**：有限 `at_tick`/有效窗口与默认活动；提供候选目标/行动，**不是**按表传送。首版不做无限每日循环。
- **Goal**：稳定 ID、`priority 0–100`、前置/完成条件、固定 recipe 与有限 `inactive/active/blocked/achieved/failed` 状态；同优先级按稳定 ID 决定。
- **CurrentPlan**：保存来源 goal/schedule、`generation`、`recipe_step`、动作 `kind`/`target`、`start_tick`/`expected_end_tick`、`status` 与失败原因；可含当前 travel span，但**不再另存一份可独立变更的位置**。

### 8.2 CurrentPlan 持久化

`session_npc_states.hidden_plan_state`（`CONTENT_NAMESPACE`）：

```json
{"__content_simulation": {
  "schema_version": 1, "profile_id": "content_v1", "binding_hash": "<runtime_hash>",
  "goal_id": "guard_cross", "source": "goal", "generation": 2,
  "recipe_step": 0, "action": "move", "target": "bridge",
  "start_tick": 9, "expected_end_tick": 12,
  "status": "traveling", "failure_code": null
}}
```

### 8.3 决策边界与失败语义

- 决策边界：schedule 到点、当前步骤完成/失败、计划明确取消。
- 普通行程**不**中途被目标优先级瞬时传送或无界重规划。
- 无合法计划 → 稳定 `idle`/`blocked`，等待下一已知边界；**不**每回合调用 LLM 修复计划。
- 非预期状态明确拒绝，不吞错后继续。
- 行动期间死亡、路线变化、owner 变化都在执行/完成时**重新验证**。失败无效果并进入定义好的 fallback；成功仅在完成时更改位置或物品。
- 受管原语限 `move`、`wait`、`take`/`use`/`transfer`；**不扩大**生产 LLM 可提议动作权限。

---

## 9. 认知与记忆

### 9.1 来源、观察者与原子性

- 从**已裁定**的引擎事件生成认知计划；准备期可以生成只读草稿，但事实事件与必要认知必须同一权威事务提交。
- 每个事件**冻结发生当时**的位置、行动者和授权感知范围；按当时视角求观察者，**不能**使用推进终点位置回溯发知识。
- NPC 计划选择仅消费自己的可知视图。世界真相、玩家知识、NPC 私有记忆和 speech belief 分离；听见说法不能升级为事实。
- 为事件与 Delta/认知**预分配**明确的因果身份；不得用两个独立 seq 计数器相等来猜关联。多 Effect/多事件时必须有显式 causal mapping。
- content_v1 的 NPC 新记忆：
  - `source_event_ids_json` 保存实际 `GameEvent.id`；
  - `memory_type = "episodic"`；
  - `memory_kind ∈ {"action", "observation"}`；
  - `visibility ∈ {"npc_private", "npc_shared"}`。
- 旧 phase3 **不因本规范被批量改写或自动换 codec**，其既有表示通过**窄读适配**兼容。
- 玩家观察所得知识沿 `MemoryFact` 扩展保存，使用明确的 `player_knowledge` 类型与玩家主体；新增独立 `source_game_event_id` 字段（FK → `game_events.id`），**不**把 GameEvent ID 填进既有 FK 指向 `event_logs` 的 `source_event_id`。
- 新知识读取必须先按主体/可见性过滤**再**检索；通用 fact 查询不能将新增的玩家私有知识无差别放进 NPC/world 上下文。
- 派生去重键 = `(version_id, source_event_id, subject_ref, rule_id)`，存于 `derivation_key`；失败传播，重试不重复认知。按真实 FK 拓扑 flush，**不**为便利增加第二个 commit。

### 9.2 兼容与可检索性

- 既有默认记忆开关（`NPC_MEMORY_FIRST_ENABLED`）和 major-NPC 边界**不**全局放开；记忆闭环验收显式开启开关并使用 major NPC，同时测试关闭时不授权引用不存在的记忆。
- 对已证明属于旧 phase3 的同会话/同 owner、engine 来源行，读取投影可将 `private` 窄映射为 `npc_private`、旧 `action`/`observation` 类型映射为 `episodic`；**不原位改数据**，不把未知 `private` 变 shared，不伪造缺失的 durable 来源 ID。
- 旧 enum 解码路径（`NPCMemoryManager._load_scope_from_db` 的 `MemoryType(mm.memory_type)`）存在兼容风险；窄读适配必须覆盖它，但不把它写成当前所有回合必现故障。
- 必须加入**正式回合闭环**：上一回合生成事件并写记忆 → 下一回合同一 NPC context 能检索该记忆且来源 ID 合法 → 另一 NPC/玩家不可见。不能仅断言“表里有一行”。

### 9.3 对外投影

- 所有依赖旧 phase3 判定的地点、库存、快照等守卫**推广**到规则运行态；不能新 DSL 接通而安全守卫仍只认 `trial_micro_v1`。
- 对玩家开放的版本接口只返回**可公开元数据**；完整 bundle/隐藏 recipe/初始秘密仅限授权作者/管理员读取。
- world/scene/NPC/旁白/REST/SSE/replay 使用同一白名单投影；私有命名空间、未感知 NPC/owner、未来步骤和计划不出现在模型上下文或客户端。
- 当前地点 API 不得把 `short_memory_summary` 当公开 mood；公开状态字段限定白名单。
- 新内容 replay 的 `npc_count` 按**公开投影**计数，不用原始行数泄露新场景隐藏实体；legacy 的历史总数口径不悄悄改写。
- 保持 `action_resolution v1` 词汇、实际耗时、中断失败计数、提交后旁白、同键只读恢复等既有外部契约，不公开离场步骤数量。

---

## 10. 错误码（冻结）

### 10.1 内容/契约（发布前拒绝）

`CONTENT_PACK_SCHEMA_UNSUPPORTED`, `CONTENT_UNKNOWN_FIELD`, `CONTENT_DUPLICATE_KEY`, `CONTENT_DUPLICATE_ID`, `CONTENT_RESERVED_ID`, `CONTENT_TYPE_ERROR`, `CONTENT_VALUE_RANGE`, `CONTENT_NON_FINITE_NUMBER`, `CONTENT_DANGLING_REF`, `CONTENT_KIND_MISMATCH`, `CONTENT_CROSS_PACK_REF`, `CONTENT_INVALID_OWNER`, `CONTENT_DUPLICATE_ROUTE`, `CONTENT_PATH_ESCAPE`, `CONTENT_UNKNOWN_PLACEHOLDER`, `CONTENT_UNDECLARED_FLAG`, `CONTENT_CONDITION_TOO_DEEP`, `CONTENT_CONDITION_TOO_LARGE`, `CONTENT_RECIPE_TOO_LONG`, `CONTENT_SCHEDULE_OVERLAP`, `CONTENT_AMBIGUOUS_ALIAS`, `CONTENT_UNSUPPORTED_FEATURE`

### 10.2 绑定/发布/运行

`CONTENT_BINDING_CONFLICT`, `CONTENT_BINDING_MISMATCH`, `CONTENT_VERSION_CONFLICT`, `CONTENT_VERSION_NOT_PUBLISHED`, `CONTENT_VERSION_PACKAGE_MISMATCH`, `CONTENT_BUNDLE_MISSING`, `CONTENT_HASH_MISMATCH`, `CONTENT_SCHEMA_UNSUPPORTED`, `CONTENT_WORLD_ALREADY_BOUND`, `CONTENT_FROZEN_VERSION`, `CONTENT_RUN_STATE_CORRUPT`, `CONTENT_BACKWARD_DERIVATION`, `CONTENT_PLAN_REEVAL_BUDGET`, `SIMULATION_STEP_BUDGET_EXCEEDED`

> `CONTENT_FROZEN_VERSION`、`CONTENT_BINDING_MISMATCH`、`CONTENT_BUNDLE_MISSING`、`CONTENT_HASH_MISMATCH`、`CONTENT_SCHEMA_UNSUPPORTED`、`CONTENT_RUN_STATE_CORRUPT` 是**运行时拒绝新回合**的错误，不静默回落 legacy、不自动改绑 latest。

---

## 11. 验收轨迹（golden traces）

> 规范化对齐口径：比较**事件类型序列、实际 tick/时间、位置、owner、失败结果与必要认知语义**；忽略 UUID、墙钟与旁白文本差异。

### A：配置化试炼样例 `content_packs/trial_micro_config/`

以配置复刻阶段三 `+2/+5/+6/+7/+8/+9` 的轨迹，走 `content_v1`，而非继续调用固定 `TrialRules`。

| Tick | 期望事实 |
|---|---|
| 0 | 玩家在 `mountain_gate`；`npc_a` 在 `plaza`；`npc_b` 在 `trial_peak`；`trial_token` owner = `location:trial_peak` |
| +2 | `npc_travel_started`(npc_a, plaza→trial_peak, expected_end=5) |
| +5 | 先 `npc_arrived`(npc_a, trial_peak)，再 `item_acquired`(npc_a, trial_token)，再 `item_take_failed`(npc_b, reason=already_taken) |
| +6 | `item_use_failed`(npc_b, reason=not_owner) |
| +7 | `world_interrupt`(kind=trial_bell)，玩家持续动作被**实际截断**（`planned=10/15 → actual=7`） |
| +8 | `npc_travel_started`(npc_b, trial_peak→plaza, expected_end=9) |
| +9 | `npc_arrived`(npc_b, plaza) |

- 旧 phase3 fixture 同时回归，**不能**为了复刻修改旧档解释。
- 事件类型名对齐旧样例的规范化语义（`npc_travel_started`/`npc_arrived`/`item_acquired`/`item_take_failed`/`item_use_failed`/`world_interrupt`），但实现必须来自 DSL 配置，而非硬编码 handler。

**回合切分（冻结，修正先前草案）**：`+7` 的中断会**实际截断**玩家当次持续动作，因此推进端点不是整齐的 3-tick 步进。A 的正式回合作如下切分，第四回合必须从**实际截断终点 7** 续跑：

| 回合 | 推进区间 | 说明 |
|---|---|---|
| 1 | `(0, 3]` | `inspect` 3 tick |
| 2 | `(3, 6]` | `inspect` 3 tick；覆盖 `+5` 争用与 `+6` 试用失败 |
| 3 | `(6, 9]` → 实际 `(6, 7]` | `inspect` 3 tick 被 `+7` 钟声中断，实际终点 **7**，`planned=3 → actual=1` |
| 4 | `(7, 12]` | 自 7 续跑 5 tick；覆盖 `+8` 出发与 `+9` 抵达 |

把第三段当作终点 9、或让第四段从 9 起跑，都是错的：那会跳过被截断的 1 tick 并掩盖中断语义。

**断言口径（冻结）**：A/B 两张表列的是**必须出现的引擎事实及其相对先后**，不是该 tick 的完整事件列表。除表中所列事实外，同一 tick 还可能合法出现其它事件——特别是 **`plan_blocked`**：按 §6.6，任何一个计划步骤完成/失败都会触发决策边界，而 pack A 的 `npc_a` 没有任何 Goal，因此它抵达 `trial_peak` 时**必然**产生一次 `plan_blocked`。因此验收断言应写成「表中所列事件按给定相对顺序出现」（子序列断言），**不要**写成「该 tick 的事件前缀恰好等于表中三项」。把 `plan_blocked` 当作失败信号是错的；反过来，如果它**没有**出现，那才说明决策边界没有执行。

### B：雾渡封桥 `content_packs/misty_ford/`

4 个地点（`east_bank` 东岸、`watch_house` 守望屋、`bridge` 石桥、`west_bank` 西岸）、2 名 NPC（`ferryman` 渡守、`herbalist` 采药人）。

| Tick | 配置行为 | 期望 |
|---|---|---|
| +2 | `ferryman` 按渡桥目标出发，预计 +5 抵达 | CurrentPlan 进入 `move`，**尚未传送**（位置仍 `east_bank`） |
| +4 | `on_time_crossed(4)` 关闭该会话桥路 | `route_set_open(east_bank→west_bank, false)` → route Delta 生效；**其他会话不受影响** |
| +5 | 到达步骤重检；主目标不可执行，选择守桥 `wait` 4 | **不抵达**；原计划终止（`failure_code=route_closed`），保存 fallback 来源与终点 +9 |
| +9 | ENV 重开桥；wait 完成后重选高优先渡桥目标 | 先 `reopen`，再完成/选择；新行程预计 +12 |
| +12 | 到达 `west_bank` | 目标 `achieved`；事件/认知准确；旧失败**不重放** |

- 至少用 `inspect3 → inspect3 → inspect3 → inspect3` 四个正式回合覆盖上述轨迹；+4/+5 在第二回合、+9 在第三回合。
- 在纯推进器测试中用**同起止 tick 的单区间 vs 不同分段**比较 NPC、路线、物品事实与终态；不把不同玩家动作数量的完整事件日志要求为相同。
- 正式 API 仅使用**既有**时长，不新增用户 duration 参数。
- 在 +6 或 +9 后重新建立服务/DB Session 继续，不能靠内存状态过关。
- 第二 NPC 作为**非观察者对照**，验证事件当时视角、下一回合私有记忆检索；玩家感知范围由配置声明，不因全局规则执行而自动全知。
- 增加两个不同具名物品实例的通用 fixture，验证 map、owner 与唯一约束，不宣称通用堆叠系统已实现。

### 不改核心的证明

先冻结支持操作集与引擎，随后**仅**增加/修改第二包配置、对应测试与文档；核心源码 hash 不变。第二包不得需要新增 `if pack_id == ...`、Python handler、seed 工厂或专用迁移。B 的真实路线 Effect、失败/fallback/重选与跨回合存储必须由配置驱动，**单纯换 ID 不能通过验收**。

---

## 12. 数据库增量（nullable，无数据清洗）

| 对象 | 增量 |
|---|---|
| `StoryPackageVersion` | `runtime_bundle_json`(JSON, null)、`runtime_hash`(String(64), null)、`runtime_schema_version`(Integer, null)；保留 manifest/source_hash 旧语义 |
| `Session` / `PlaythroughInstance` / `World` | 复用既有 version/world/instance FK；服务器保留绑定信息（`Instance.config_json.__content_binding`），补必要索引与写保护，**不批量回填** |
| `SessionInventoryItem` | nullable `instance_key`，新增 `UNIQUE(session_id, instance_key)`；旧 NULL 行可保留，新内容实例**必须**有 key |
| `NPCPrivateMemory` | nullable `derivation_key` 及 `UNIQUE(session_id, npc_id, derivation_key)`；使用既有 `source_event_ids_json` |
| `MemoryFact` | nullable `source_game_event_id`(FK → `game_events.id`)、`derivation_key` 及 `UNIQUE(session_id, subject_ref, derivation_key)`；既有 EventLog FK 口径**不改** |

- 约束的 NULL 兼容语义必须在 SQLite 与 PG **分别**验证（两库都允许唯一索引中多行 NULL）。
- 升级测试保留旧行内容/数量与 NULL 引用；迁移**不得**清洗重复数据、猜测版本或重写模糊 owner。
- `downgrade` 只在专用测试库验证；已有新版本实例时的生产回退须明确拒绝危险丢字段操作，**不承诺无损降级**。
- 迁移 revision 链当前 tip 为 `025`；新增迁移命名 `026_<snake_case>.py`，`revision="026"`、`down_revision="025"`。
