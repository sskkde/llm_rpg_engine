# LLM RPG Engine 设计讨论汇总与架构基线

> **版本**：讨论整合稿 v0.1  
> **整理日期**：2026-10-08  
> **项目**：[sskkde/llm_rpg_engine](https://github.com/sskkde/llm_rpg_engine)  
> **文档性质**：架构与产品设计基线（Discussion RFC）；不是已经完成的实现规范  
> **适用范围**：当前讨论的单人 Web 文字冒险 RPG、剧本内容模型、时间驱动世界模拟、NPC 认知、LLM 接口和底座选型。

## 0. 阅读指南与决策状态

本文按照**最新共识优先**整理此前全部相关讨论，并区分：

- **【已确定】**：现阶段采用的产品或架构原则。
- **【建议基线】**：方向已获得认可，但字段或技术细节仍需要 Schema/PoC 验证。
- **【待定】**：尚未正式冻结，需要实施验证或进一步设计。
- **【已放弃】**：曾讨论但已被后续决策替代。

**特别声明**：此前曾提出“玩家不动时世界也按现实时间持续演进”的 Persistent Living World 方案，随后已明确调整为**玩家行动推动游戏逻辑时间，NPC 和不可见世界在这一段经过的游戏时间内同步演进**。全文以后一方案为准，前一方案只作为历史备选记录。

### 0.1 一页结论

1. **【已确定】游戏类型**：单人、Web、文字为核心、半开放探索、世界与剧本解耦；演示题材暂定中国风修仙《青云试炼》。
2. **【已确定】世界推进**：玩家驱动的**可变时间跨度回合制世界模拟**。玩家的一次操作耗费符合设定的游戏时间；不可见 NPC 和世界同期演进；等待用户输入、LLM 响应以及真实世界经过的时间不会自动推动世界时钟。
3. **【建议基线】内容形式**：`Story Package` = **结构化规则/对象 + 自然语言设定 + 关键剧情约束 + 初始状态**。用稳定对象 ID 引用，不能仅靠超长 Prompt 定义世界。
4. **【建议基线】核心内容对象**：14 类——`StoryPackage`、`World`、`RuleSet`、`Location`、`Route`、`Faction`、`Character`、`Ability`、`Item`、`Lore`、`Quest`、`PlotBeat`、`Event`、`InitialState`。
5. **【建议基线】规则表达**：共享 `Condition`、`Trigger`、`Effect` DSL；分别用于**判断、识别检查时机、表达可验证的变化**。
6. **【已确定】LLM 边界**：模型只提议意图、动作、叙事；**不直接修改 Canonical State、数据库或 NPC 知识**。由引擎校验 Action、计算耗时与效果、产生 StateDelta、原子提交；之后才生成旁白。
7. **【已确定】知识隔离**：世界客观事实、NPC 已知知识、NPC 主观信念、玩家已知知识、叙事表现必须区分。
8. **【建议基线】技术方向**：保留 Python 游戏核心与现有状态/记忆实现；**不因更换 LLM 底座而重写完整引擎**。
9. **【待定】LLM 基础设施**：优先 PoC 比较 **LiteLLM SDK**（多提供方底座）与 **PydanticAI**（结构化 Proposal），可测试 `LiteLLM + Instructor`；`pi-ai`/DSH 作为 TypeScript 或跨进程备选，而非已确定的迁移目标。

---

## 1. 游戏愿景与玩法边界

### 1.1 产品目标

构建一个**LLM 驱动、规则约束、可持续演化的回合制模拟文字 RPG**：

- 玩家以自由文本、选择或 UI 操作参与世界，而不只是沿固定剧本文本翻页。
- 世界存在稳定的地点、路线、人物、道具、能力、势力、任务、知识和事件定义。
- 关键剧情保有作者可控的边界；具体对话、过渡行为、环境文本由 LLM 灵活生成。
- NPC 拥有自己的目标、行程、私人记忆、已知事实及可能错误的信念。
- 只要玩家行动令世界时间经过，NPC 即使不在玩家视野中也会继续其生活和计划。
- 游戏引擎决定客观事实；模型生成的文本不能成为未经确认的世界状态变更。

### 1.2 近期不做的事情

- **【已放弃】真正的现实时间常驻世界**：不要求玩家离线、发呆时世界自动推进；不需要持续运转的后台时钟、实时 Tick 和每 NPC 常驻 Agent。
- **【不做】通用 2D/3D 游戏引擎**：图形表现是前端/资产接口，不是首版模拟内核的职责。
- **【不做】完全自由的可执行剧情脚本**：不允许 Story Package 提供可直接执行的任意 Python/SQL 或任意状态路径写入。
- **【不做】把一切交给单一全知 LLM**：避免 NPC 知识越权、设定漂移和不可回放的状态变更。

### 1.3 《青云试炼》样例世界

**明线**：前往青云宗、参加弟子试炼、通过入门考核。  
**暗线**：调查试炼异常、发现幕后操纵、发展竞争者合作关系、最终面对长老与师傅介入。

主要 NPC：

| 角色 | 主要功能 | 叙事原则 |
|---|---|---|
| 师姐 | 引导玩家、熟悉宗门、暗中调查 | 表面温和可靠，有独立目标和秘密 |
| 男竞争者 | 竞争与后续潜在合作 | 不始终围绕玩家行动 |
| 女竞争者 | 竞争与潜在联盟 | 有独立身份、目标和知识 |
| 谜语人 | 透露部分线索 | 知道部分真相，但并非全知 |
| 长老 | 宗门权威、幕后反派 | 公开身份与秘密行为相容 |
| 师傅 | 关键人物、后期介入 | 出场时机与剧情条件受作者约束 |

---

## 2. 五个逻辑边界：Definition、State、Cognition、Runtime、Presentation

建议在架构上明确区分以下层次，而不是将所有信息都放在 NPC Prompt 或数据库大字段里。

| 层 | 核心内容 | 典型责任 |
|---|---|---|
| **Story Definition** | `StoryPackage`、对象模板、Lore 真相、条件/触发器/效果 | 作者声明世界规则与内容 |
| **Canonical State** | 当前时间、位置、人物状态、物品实例、任务阶段、标志位 | 权威世界事实 |
| **Cognition** | NPC 视角、Knowledge、Belief、Memory、Goals | 各角色允许知道和相信什么 |
| **Runtime** | 行动验证、耗时、时间推进、NPC 计划、事件结算 | 决定世界实际发生什么 |
| **Presentation** | 玩家可见投影、叙事、UI、立绘、BGM | 让玩家感知已确定事实 |

至少保留四个不同概念：

```text
CharacterTemplate      ≠ CharacterRuntimeState
ItemTemplate           ≠ ItemInstance
WorldTruth             ≠ CharacterKnowledge/Belief
GeneratedNarration     ≠ CommittedGameEvent
```

### 2.1 内容包、游戏实例与时间线

```text
StoryPackageVersion（作者发布，版本固定）
           │
           ▼
InitialState + Player Configuration
           │
           ▼
PlaythroughInstance（本局游戏）
           │
           ├─ Canonical State
           ├─ World Time
           ├─ Game Events / State Deltas
           ├─ NPC Cognitive State
           ├─ Current Plans / Schedules
           └─ Player Knowledge / Quest Progress
```

发布后的剧本版本应不可变；存档固定所用版本。如需升级，应有显式的内容迁移，而不是静默替换世界定义。【建议基线】

---

## 3. Story Package Schema v1：14 类顶层对象

### 3.1 完整分类

| 分组 | 对象 | 定义什么 | 主要引用关系 |
|---|---|---|---|
| 包级 | `StoryPackage` | 剧本入口、版本、内容索引 | World / RuleSet / InitialState |
| 世界 | `World` | 世界背景、基调、宏观设定 | RuleSet / Faction / Lore |
| 世界 | `RuleSet` | 时间、移动、战斗、属性、经济等规则 | State Schema / Action Rules |
| 空间 | `Location` | 地点实体、层级、环境、可交互内容 | Location / Character / Item / Lore |
| 空间 | `Route` | 有向/双向位置连接、距离、时间、通行要求 | Location / Condition |
| 社会 | `Faction` | 阵营组织、等级、势力目标、关系 | Character / Location / Lore |
| 角色 | `Character` | 人物模板、背景、目标、性格、能力、认知初值 | Ability / Item / Lore / Faction |
| 能力 | `Ability` | 技能、法术、主动/被动能力 | Condition / Effect / RuleSet |
| 物品 | `Item` | 物品模板、属性、能力、隐藏特性 | Ability / Lore |
| 知识 | `Lore` | 可发现的知识单元、史实、线索、传闻 | Character / Location / PlotBeat |
| 目标 | `Quest` | 面向玩家的任务目标与进度 | Condition / Effect / PlotBeat |
| 剧情 | `PlotBeat` | 作者控制的重要剧情约束和结果 | Event / Quest / Condition |
| 事件 | `Event` | 可触发的具体世界变化模板 | Trigger / Condition / Effect |
| 开局 | `InitialState` | 新一局的初始权威状态蓝图 | 全部实例化对象 |

`Scene` 暂**不列为第 15 类顶层对象**：通常由 `Location + 当前参与者 + 事件 + RuntimeState` 动态形成；必要的预制剧情场景可在后续添加 `SceneTemplate`。

### 3.2 通用字段

适合继承 `ContentObject`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 包内稳定、全局不冲突的引用标识 |
| `name` | string | 是 | 面向人类的名称 |
| `description` | string | 否 | 自然语言背景/外观/功能描述 |
| `tags` | string[] | 否 | 分类、检索、规则筛选 |
| `enabled` | boolean | 否 | 内容启用状态 |
| `metadata` | object | 否 | 非运行逻辑的编辑器/作者信息 |
| `schema_version` | string | 否 | 对象 Schema 版本 |

建议把**字段可见范围**、**模板/运行时可变性**、**事实权威性**视作 Schema 或字段级元数据，而不是让任何模型直接看到全部内容。

### 3.3 各对象的字段清单

以下为 **v1 候选字段**，具体类型和必填性需要在 Pydantic 模型定稿时统一收敛；避免为了“完整”一次引入过多可执行子模型。

#### 3.3.1 `StoryPackage`

`id`、`name`、`version`、`schema_version`、`description`、`author`、`language`、`genre`、`world_id`、`ruleset_id`、`initial_state_id`、`entry_plot`、`content_paths`、`assets`、`dependencies`、`config`。

职责：发布单位、版本锁定、内容索引和加载入口。

#### 3.3.2 `World`

`id`、`name`、`premise`、`genre`、`tone`、`themes`、`era`、`technology_level`、`magic_system`、`calendar`、`currency`、`languages`、`regions`、`major_factions`、`global_lore`、`world_constraints`、`narrative_style`。

`premise` 用自然语言写世界文化和冲突；修为顺序、禁用武器、死亡机制等**硬规则**不应只放在 `premise`。

#### 3.3.3 `RuleSet`

建议的命名空间：`time`、`movement`、`combat`、`character`、`inventory`、`ability`、`social`、`death`、`discovery`、`economy`、`state_schema`。  

其中 `time` 至少包括单位、动作基础耗时、修正器；`movement` 包括通路要求、速度、地形修正；`state_schema` 声明允许出现的 flag、角色属性、关系和地点状态字段及其数据类型、默认值和边界。

#### 3.3.4 `Location`

`id`、`name`、`type`、`parent_id`、`region_id`、`short_description`、`description`、`tags`、`coordinates`、`environment`、`access`、`interactive_objects`、`default_characters`、`default_items`、`lore_refs`、`hidden_features`、`local_rules`、`event_refs`、`assets`、`narrative_guidance`。

地点为图节点，支持层级：`World → Region → Location/Room`。当前谁在此地、门是否打开等属于运行状态；模板中的 `default_characters` 只用于初始化，不是永远常驻约束。

#### 3.3.5 `Route`

`id`、`from`、`to`、`bidirectional`、`movement_type`、`distance_m`、`travel_time`、`terrain`、`cost`、`visibility`、`discoverable`、`access_conditions`、`blocked_conditions`、`risk`、`encounters`、`requirements`、`description`。

路线单独维护，而不是把可达地点列表和全部路线规则混在 `Location.description` 里；NPC 和玩家共用路线图与移动合法性规则。

#### 3.3.6 `Faction`

`id`、`name`、`type`、`description`、`ideology`、`values`、`goals`、`territories`、`leaders`、`members`、`ranks`、`relations`、`resources`、`knowledge`、`secrets`、`reputation_rules`、`hostility_rules`。

势力关系可为模板初值；实际玩家声望、势力占领等进入 RuntimeState。

#### 3.3.7 `Character`

建议按结构分组：

| 组 | 字段 |
|---|---|
| Identity | `id`、`name`、`character_type`、`role`、`age`、`gender`、`faction_ids` |
| Appearance | `appearance.summary/details/distinctive_features` |
| Personality | `personality.traits/values/dislikes/fears/flaws` |
| Background | `background.public/private/origin/important_events` |
| Motivation | `goals.immediate/short_term/long_term/hidden` |
| Social | `relationships`（信任、怀疑、地位等初值） |
| Capability | `stats`、`abilities`、`inventory` |
| Knowledge | `known_lore`、`suspected_lore`、`secrets`、`initial_beliefs` |
| Autonomy | `autonomy`、`schedule`、`decision_policy`、`fallback_behavior` |
| Presentation | `speech`、`ai_guidance`、`narrative_guidance`、`assets` |

**背景不等于实时记忆**：人物过去的固定经历可放 `background`；这一局刚发生的事进入 Episode/Memory。NPC 并不自动知道 Story Package 内所有 `private` 字段和世界真相。

#### 3.3.8 `Ability`

`id`、`name`、`type`（active/passive）、`category`、`description`、`requirements`、`cost`、`cooldown`、`targeting`、`conditions`、`effects`、`scaling`、`failure`、`ai_usage`、`cast_time`、`execution_time`。

`Ability` 可由人物、装备、场景机关引用。伤害、命中与状态应由领域规则计算，不能只通过模型描述决定。

#### 3.3.9 `Item`

`id`、`name`、`type`、`subtype`、`rarity`、`description`、`stackable`、`unique`、`properties`、`requirements`、`abilities`、`passive_effects`、`usage`、`durability`、`value`、`lore_refs`、`hidden_properties`、`use_time`、`assets`。

Story Package 定义 **ItemTemplate**，背包里的物品是 **ItemInstance**（`instance_id`、owner、location、quantity、durability 等）。

#### 3.3.10 `Lore`

`id`、`title`、`content`、`category`、`truth_status`、`importance`、`visibility`、`known_by`、`sources`、`related_entities`、`discovery`、`prerequisites`、`reveals`、`contradicts`、`tags`。

建议支持 `true / false / partial / rumor / disputed` 的叙事含义，但注意**世界真实事实**、**一条可被学到的知识主张**和**具体 NPC 对该主张的信任程度**应分层维护。NPC 的错误信念不能改写世界真相。

#### 3.3.11 `Quest`

`id`、`name`、`description`、`category`、`visibility`、`availability`、`activation`、`objectives`、`optional_objectives`、`failure_conditions`、`completion_conditions`、`rewards`、`on_start`、`on_progress`、`on_complete`、`on_fail`、`next_quests`、`related_plot_beats`、`journal`。

`Quest` 主要解决玩家可见目标、任务日志、阶段和奖励；不要把全部剧情推进逻辑藏到 Quest 里。

#### 3.3.12 `PlotBeat`

`id`、`name`、`type`、`chapter`、`priority`、`description`、`prerequisites`、`activation_conditions`、`trigger_conditions`、`required_outcomes`、`allowed_variations`、`blocked_until`、`involved_characters`、`preferred_locations`、`related_lore`、`related_quests`、`followups`、`fallback`、`timing`、`narrative_guidance`、`progression_policy`。

`PlotBeat` 控制关键剧情的约束和变化方向，**不等于固定对白或玩家必须按唯一顺序行动**。对关键剧情还需定义错过/失败/替代分支，避免作者以“必须发生”为名强制抹除玩家选择。

#### 3.3.13 `Event`（内容定义）

`id`、`name`、`type`、`priority`、`scope`、`conditions`、`trigger`、`participants`、`effects`、`visibility`、`duration`、`repeat`、`followups`、`narrative`、`memory_policy`。

它是**可能发生的世界变化模板**。运行时实际发生的一次事件应记作 `GameEvent`，包含事件实例 ID、逻辑时间、因果关系、观察者、执行结果等。两者不得混淆。

#### 3.3.14 `InitialState`

`id`、`world_time`、`player`、`characters`、`items`、`locations`、`factions`、`quests`、`plot`、`flags`、`events`、`relationships`、`knowledge`、`randomization`。

作用是实例化存档蓝图，只描述初始位置、NPC 状态、物品归属、任务状态和变量等，不应复制整个 Character/Item 模板。

### 3.4 不单列为顶层实体的共享结构

`Condition`、`Trigger`、`Effect`、`Requirement`、`Reference`、`Visibility`、`Discovery`、`Reward`、`Schedule`、`NarrativeGuidance`、`ActionDefinition`、`Goal`。  

`ActionPlan` 通常属于 **Runtime State**；`Scene` 通常由当前状态动态派生。【建议基线】

---

## 4. 规则 DSL：Condition / Trigger / Effect

### 4.1 定义与约束

```text
Trigger   = 什么时候检查某条规则？
Condition = 在当前状态下，是否满足该规则？
Effect    = 如果成立，意图修改哪些权威状态？
```

共同约束：**类型化、可校验、不可执行任意代码、支持稳定引用、引擎独占最终裁决权**。

#### Condition：只读表达式树

支持 `all`、`any`、`not` 逻辑组合，以及 v1 候选原子条件：

`flag.equals`、`character.at_location`、`character.stat_compare`、`character.status_is`、`inventory.has`、`knowledge.has`、`relationship.compare`、`quest.state_is`、`plot.state_is`、`route.discovered`、`world_time.compare`。

数值操作符：`eq / ne / gt / gte / lt / lte`。支持 `$actor`、`$target`、`player` 等绑定对象引用。内部建议返回 `TRUE / FALSE / UNKNOWN`：数据缺失不应当误判为真，`not UNKNOWN` 仍是 `UNKNOWN`；权限或关键推进仅接受 TRUE。

#### Trigger：触发检查时机

基于目前**玩家驱动的时间推进模式**，v1 应优先支持：

| Trigger | 触发来源 | 示例 |
|---|---|---|
| `on_action` | 已验证的玩家/NPC 行为 | 玩家尝试开门、NPC 抵达地点 |
| `on_time_crossed` | 本次时间区间跨越指定时间点 | 09:55 → 10:10 跨过 10:00 |
| `on_state_changed` | WorkingState 中某字段变化 | `trial_started: false → true` |

可以扩展重复频率、`once_per_playthrough`、`once_per_actor`、`cooldown` 等 `fire_policy`。**不需要独立的实时事件总线或每秒 Tick**。同一回合依逻辑时间结算时，检查到期 Trigger 即可。

#### Effect：受限领域操作

建议 v1 操作白名单：

- `flag.set`、`character.stat_modify`、`character.status_apply`
- `character.move`、`inventory.grant`、`inventory.remove`
- `relationship.adjust`、`knowledge.reveal`、`route.discover`
- `location.property_set`、`quest.start`、`quest.complete`
- `plot.activate`、`plot.complete`、`event.schedule`

这些是**变更意图**，不是数据库写入语句。实际执行仍需通过领域处理器：移动遵守 Route、阻断和耗时；物品遵守背包与唯一性；数值遵守 `RuleSet.state_schema` 上下限。

### 4.2 完整事件示例

```yaml
id: trial_anomaly_event
name: 试炼异变
trigger:
  any:
    - type: on_action
      action: enter_location
      actor: player
      location_id: trial_peak
    - type: on_time_crossed
      at:
        day: 1
        time: '10:00'
conditions:
  all:
    - type: flag.equals
      key: trial_started
      value: true
    - type: flag.equals
      key: trial_anomaly_started
      value: false
effects:
  - type: flag.set
    key: trial_anomaly_started
    value: true
  - type: location.property_set
    location_id: trial_peak
    property: danger_level
    value: 4
  - type: plot.activate
    beat_id: investigate_anomaly
  - type: event.schedule
    event_id: elder_arrival
    delay_seconds: 900
fire_policy:
  mode: once_per_playthrough
priority: 100
narrative_guidance:
  tone: tense
  do_not_reveal: [elder_is_mastermind]
```

上述 DSL 为**建议性 v1 格式**；实际发布时必须确定 `Trigger` 字段命名规范、Action 事件类型枚举与逻辑时间类型，不应混用此前讨论中的 `domain_event / time_crossed` 等不同示例拼写。

### 4.3 规则执行不变式

1. Trigger 找到检查时机；Condition 只读；Effect 转成领域命令/`StateDeltaCandidate`。
2. 同一事件的一组 Effect 默认按原子单元验证；失败不可部分提交。
3. 同回合内，前一合法变更可影响后续事件条件。
4. 事件重复触发需有幂等标识，限制级联深度、事件数、预算，防止循环。
5. 发布时验证全部 ID、字段类型、值域、引用与可达性。
6. 不允许 Story Package 随意写 `characters.anything` 等任意状态路径。

---

## 5. 世界时间与玩家驱动的回合制模拟

### 5.1 最新确定的时间语义

**【已确定】**：游戏世界逻辑时间只由已接受的玩家行为或明确的游戏内“等待/休息”行为推进：

- 玩家在网页上思考、离线、阅读文本或等待 LLM 响应时，世界时间不动。
- 行动时长由引擎依据行为类型、场景、装备和能力计算，力求符合常识。
- 一次动作可消耗秒、分钟乃至数小时，**回合不等于固定长度的一分钟或一步**。
- 玩家不可见的世界同样推进这个时间区间，且结果永久纳入本局权威状态。

可用简单耗时模型起步：

```text
ActionDuration = BaseDuration × CharacterModifier × EnvironmentModifier
```

移动更适合 `距离 ÷ 有效速度`；技能/炼制/修炼可有领域专用的时间规则。

### 5.2 起始耗时建议（可配置，不是物理常数）

| 行动 | 基础时间量级 | 修正要素 |
|---|---|---|
| 简单观察 | 10–30 秒 | 环境、感知 |
| 检查物品 | 1–5 分钟 | 目标复杂度 |
| 简短交谈 | 30 秒–2 分钟 | 交流内容 |
| 深入交谈 | 3–15 分钟 | 信息量 |
| 行走 | 距离 ÷ 速度 | 地形、负重、状态 |
| 搜索房间 | 5–20 分钟 | 房间大小 |
| 修炼/休息 | 玩家选择，规则限制 | 功法、身体状态 |
| 战斗动作 | 秒级或战斗规则内部单位 | 能力、冷却 |

`ActionDurationResolver` 是独立组件。LLM 可以帮助理解动作意图和规模，但最终时长必须由引擎校验并确定。非法输入是否耗时须按失败类型分别定义，不应一概零耗时；**只有无法识别而需澄清的输入通常不推进时间**。

### 5.3 时间推进核心 LOOP

```text
Player Input
   ↓
Intent Interpreter（可选 LLM）
   ↓
Action Resolver / Validator
   ↓
ActionDurationResolver → [start_time, end_time]
   ↓
WorldAdvancer(start, end, WorkingState)
   ├─ 定时世界事件
   ├─ 当前区域 NPC
   ├─ 其他区域重要 NPC
   ├─ NPC 日程与当前计划
   ├─ Quest / PlotBeat
   └─ Condition / Trigger / Effect
   ↓
StateDelta / Domain Validation / Conflict Resolution
   ↓
Atomic Commit（事件、状态、认知必要更新）
   ↓
PlayerVisibleProjection
   ↓
LLM Narration（失败可兜底）
   ↓
等待玩家下一次输入
```

**时间因果顺序**必须确定：如果玩家行为为 08:00→08:20，而 NPC 在 08:05 拿走道具、08:10 另一个 NPC 尝试使用该物品，后者应看到 08:05 产生的临时状态。不能简单把每个 NPC 的 20 分钟行为分别跑完再合并。

### 5.4 玩家行动与世界事件的交错

建议行为模型支持**开始 → 进行中 → 完成/中断**：

```text
08:00 玩家开始调查石碑，预计 08:06 完成
08:02 师姐决定去藏书阁
08:05 师姐抵达藏书阁
08:06 玩家调查完成
→ 统一审核并提交
```

如果玩家选择睡 8 小时，而夜里 02:00 被袭击，必须在袭击发生时中断睡眠动作，不能直接把完整 8 小时结算完毕。

### 5.5 建议的 WorldAdvancer 契约

```python
class WorldAdvancer:
    async def advance(
        self,
        working_state: "WorkingState",
        start_time: int,
        target_time: int,
        player_action: "ResolvedAction",
    ) -> "AdvanceResult":
        ...
```

`AdvanceResult` 建议包含 `actual_end_time`、`interrupted`、`validated_deltas`、`game_events`、`scheduled_steps`、`required_memory_updates` 等。实际 API 需进一步定稿。

**关键**：WorldAdvancer 的工作是**推进模拟**，不是管理 LLM Provider、拼叙事 Prompt 或直接 `db.commit()`。

---

## 6. NPC 自主性、日程与不可见世界推进

### 6.1 三组核心信息

| 信息 | 所在层 | 作用 |
|---|---|---|
| `Schedule` | Story Definition（默认） | NPC 正常情况下什么时候在哪里做什么 |
| `Goal` | Definition + Runtime | NPC 长/短期想达成什么、优先级多少 |
| `CurrentPlan` | Runtime | 已选具体动作、起止时间、目标、前置条件、中断策略 |

`CurrentPlan` 必须根据情况修改，不可把 Schedule 理解为强制传送或无法打断的剧本指令。

```yaml
npc_id: senior_sister
location_id: sect_gate
current_activity: guiding_students
current_goals:
  - goal_id: investigate_trial
    priority: 80
    status: active
current_plan:
  action: move
  target: archive
  planned_start: '08:10'
  expected_end: '08:15'
last_simulated_time: '08:00'
```

### 6.2 分层模拟精度

| 层级 | 对象 | 运行策略 | LLM 时机 |
|---|---|---|---|
| 精细 | 与玩家共场景或紧密互动的 NPC | 连续的离散动作与交互 | 对话、冲突、关键决策 |
| 重点 | 主要 NPC、剧情核心人物 | 按日程、目标、计划推进 | 计划失败、发现线索、目标变更 |
| 粗粒度 | 普通弟子、商人、路人 | 日程、规则、摘要结算 | 默认不调用 |

层级可动态提升：普通 NPC 若见证重大事件，可以变为需要独立记忆的关键人物。

### 6.3 NPC 决策触发条件

可按规则完成的动作（移动、例行休息、已有计划）尽量**零 LLM 调用**。在计划失效、面临重要选择、遇到玩家、角色目标冲突时，构造专门的 `NPC ContextPack` 调用 LLM。产生的是**Action Proposal**，不能让 NPC 声称“我已找到真相”就自动获得世界真实知识。

### 6.4 不可见区域模拟原则

- 主要 NPC、关键物品、剧情事件：保留足够精确的时间顺序和因果记录。
- 普通人群和环境变化：允许粗粒度规则、区间摘要、延迟物化。
- 简化计算不能推翻已有 GameEvent 或把已死亡/不在场 NPC 送回日程。
- 玩家返场看到的是已推进的实际状态，不是无依据的临时编造。

---

## 7. NPC 认知与记忆模型

### 7.1 四类信息必须分开

| 类型 | 示例 | 谁维护 |
|---|---|---|
| `WorldTruth` | 长老实际策划了试炼异变 | 权威世界状态 / Story Definition |
| `Knowledge` | 师姐知道上届有三名弟子失踪 | 认知系统，依据感知/获知事件更新 |
| `Belief` | 师姐认为失踪可能由长老所为，置信 0.6 | NPC 私人认知 |
| `Memory` | 师姐回忆昨日玩家帮她翻查记录 | 事件派生的私人/阶段记忆 |

叙事时 NPC **说出了一个命题**，只证明她说了这句话，不证明该命题是真的。可记录 `CharacterSpoke` 和 `PlayerHeard`，由知识传播机制更新玩家的信念或线索，不自动更新 WorldTruth。

### 7.2 事件与认知更新

```text
Committed GameEvent
       ↓
Perception / Witness Rules
       ↓
按视角生成观察记录
       ├─ Player Knowledge
       ├─ NPC A Memory / Belief
       └─ NPC B Memory / Belief
       ↓
检索与摘要（可异步派生）
```

NPC 决策上下文必须先做**权限/视角过滤**，再做**相关性检索**。只靠 Prompt 写“你不知道长老秘密”不够安全。

### 7.3 记忆与持久化分层

此前讨论的存储原则仍然适用：

- `Event Store`：可审计的实际发生记录。
- `Turn Transcript`：玩家/模型交互与轮次执行记录。
- `Canonical State / Snapshot`：权威状态和重建入口。
- `NPC Cognitive State`：各 NPC 的知识、信念、关系、目标和必要记忆。
- `Rolling / Episodic / Long-term Memory`：相关上下文的摘要与长期检索，可从已确认事件派生。

**事实和必须生效的认知状态**应与本回合事务保持一致或具有可靠的派生任务机制；较大规模的自然语言摘要、索引与长期检索可在提交之后生成。

---

## 8. Engine ↔ LLM 的双向协议

### 8.1 根原则

```text
Engine → LLM: ContextPack（局部、过滤后的任务上下文）
LLM → Engine: Proposal（尚未批准的结构化提案）
Engine → World: Validated Action / Effects → StateDelta → Commit
Engine → LLM: NarrationContext（提交后、玩家可感知）
LLM → Player: Narration（表现，不是新事实）
```

**禁止** LLM 直接写 StateDelta、数据库或世界真相。即使 JSON Schema 格式正确，也仍可能引用不存在的物品、越权知识或非法目标，必须由领域规则再次校验。

### 8.2 四类逻辑调用

| Stage | 目标 | 输入视角 | 输出 |
|---|---|---|---|
| `intent_interpreter` | 解释自由文本 | 玩家可见状态、目标、可尝试动作 | `InputIntentProposal` |
| `npc_decision` | 决定 NPC 下一行动/言语行为 | 该 NPC 的 Profile + State + Knowledge + Belief + Memory + Goal | `NPCActionProposal` |
| `story_director`（可选） | 在作者允许边界内提出剧情候选 | 受授权的导演视角、PlotBeat 约束、世界状态 | `StoryEventProposal` |
| `narration` | 描述已确认的可见结果 | 玩家可见投影、已提交事件、风格要求 | `NarrationProposal` |

这些不需要四个常驻 Agent，可以是同一模型服务上不同的 Prompt / Schema / Stage。**不存在每回合必须调用所有 Stage 的要求**。

### 8.3 ContextPack v1 建议结构

```json
{
  "request_id": "req_001",
  "stage": "npc_decision",
  "story_package_id": "qingyun_trial",
  "story_package_version": "1.0.0",
  "world_time_seconds": 29400,
  "base_state_version": 42,
  "actor_id": "senior_sister",
  "context": {
    "identity": {"name": "李清瑶", "role": "内门师姐"},
    "current_state": {"location_id": "sect_gate", "activity": "guiding_students"},
    "goals": [{"id": "investigate_trial", "priority": 80}],
    "known_facts": [{"lore_id": "previous_trial_accident"}],
    "beliefs": [{"claim": "事故并非意外", "confidence": 0.7}],
    "relevant_memories": [{"content": "昨日看到旧档案缺页"}],
    "perception": {"visible_characters": ["player"]},
    "available_actions": [
      {"id": "move_to_archive", "type": "move", "target_id": "archive", "estimated_seconds": 300},
      {"id": "talk_to_player", "type": "talk", "target_id": "player"}
    ]
  },
  "output_schema": "NPCActionProposal.v1"
}
```

`ContextPack` 为模型输入，不必与 Story Package 原对象一一同形。由 `PerspectiveFilter` 先剔除不应知道的内容，再由 `RelevanceRetriever` 提取和压缩必要片段。对 Narrator，不传任何超出玩家可感知范围的隐藏真相。

### 8.4 Proposal v1 建议结构

```json
{
  "proposal_type": "npc_action",
  "actor_id": "senior_sister",
  "base_state_version": 42,
  "selected_action_id": "move_to_archive",
  "action": {"type": "move", "target_id": "archive"},
  "goal_id": "investigate_trial",
  "speech": null
}
```

模型**选择**行动；引擎决定 Route、Condition、预计耗时、开始/完成、冲突和结果。LLM 不返回“已经成功到达”“玩家得到隐藏 Lore”之类的权威结果。

### 8.5 共享 `ActionDefinition`

允许内容作者配置受限领域动作，例如：

```yaml
id: accept_assistance
actor_type: character
conditions:
  all:
    - type: relationship.compare
      from: senior_sister
      to: player
      field: trust
      op: gte
      value: 40
effects:
  - type: relationship.adjust
    from: senior_sister
    to: player
    field: trust
    amount: 5
  - type: quest.start
    quest_id: investigate_trial
duration:
  base_seconds: 60
```

除预定义动作外，允许受限的通用动作：`talk`、`observe`、`inspect`、`attempt_manipulation` 等。开放式输入先解析为可审核的对象引用与参数，未知目标或不支持的效果不得任意落库。

### 8.6 验证与回填链

```text
LLM Response
   ↓
1. Schema / JSON / Pydantic Validation
   ↓
2. Reference / ID Validation
   ↓
3. Perspective / Knowledge Permission Validation
   ↓
4. Domain / Condition / Resource / Distance Validation
   ↓
5. State Version / Conflict Revalidation
   ↓
ActionResolver + DurationResolver
   ↓
EffectExecutor → StateDeltaCandidate
   ↓
WorkingState
   ↓
Atomic Commit → Event Log / State / Necessary Cognition
```

修复与失败策略：格式错误限次重试；NPC 行动超时或非法时采用不造成重大状态变化的规则回退；解析不了的玩家输入请求澄清；Narrator 出错不回滚已成功提交的世界事实。

### 8.7 对话与叙事

- NPC 可输出 `speech_act`、`speech.text`、`disclosed_lore_ids`，但知识披露先经权限验证。
- NPC 的句子是**对话事件**，不自动证明句中命题为真。
- Narrator 应读取 **已提交的玩家可见 GameEvent**，可以补充修辞和感官描写，不应新增重要地点、物品、角色、事实或隐藏线索。
- 最好记录 `request_id`、`proposal_id`、Stage、模型、上下文版本、Token、校验结果、执行结果和对应 GameEvent ID 以支持排错。

### 8.8 减少 LLM 调用

| 场景 | 建议调用 |
|---|---|
| 标准移动 / 已知物品使用 | 可能无需 Intent LLM，只需模板或 Narration |
| 自由文本探索 | 必要时调用 Intent + Narration |
| 与重要 NPC 对话 | NPC Decision + Narration |
| NPC 按既定路线走路 | 零 LLM |
| NPC 计划受阻或出现重要线索 | 按需 NPC Decision |
| 作者允许的动态剧情支线 | 按需 Story Director |

---

## 9. 游戏核心 Runtime 与数据一致性

### 9.1 推荐核心组件

| 组件 | 职责 |
|---|---|
| `TurnCoordinator` | 一次玩家动作的生命周期、错误与提交协调 |
| `IntentInterpreter` | 解析自由输入为受限行动 |
| `ActionResolver` | 调用领域规则，解析行动开始与结果 |
| `ActionDurationResolver` | 计算动作消耗的逻辑时间 |
| `WorldAdvancer` | 以时间顺序推进 NPC、世界与剧情 |
| `NPCTimeSimulator` | 日程、目标、当前计划、必要 LLM 决策 |
| `ConditionEvaluator` | 只读条件判定 |
| `TriggerDispatcher` | 在推进区间匹配行为/时间/状态触发 |
| `EffectExecutor` / `StateDeltaResolver` | 将合法动作转为权威变更候选 |
| `ConflictResolver` | 行动/效果资源冲突裁决 |
| `PerspectiveService` | 按角色感知和知识过滤上下文 |
| `MemoryWriter` | 依据已确认事件维护认知 |
| `UnitOfWork` | 原子持久化事件、状态、必要认知 |
| `NarrationService` | 根据已提交事实生成玩家文字 |

### 9.2 持久化设计不变式

- **一个 Game Runtime 写入入口**：避免并存多个生产用 Orchestrator。
- **一个权威事务边界**：领域方法和 Repository 不应在协调器外部任意 `commit()`。
- **LLM 调用不能持有长数据库事务**：基于版本快照决策，在写入前重验/冲突处理。
- **权威状态与 GameEvent / Delta 因果一致**：失败不得出现半次回合已落库。
- **支持重放/检查点/幂等**：玩家提交重试不能重复获得道具或奖励。
- **事件时间顺序确定**：同时间动作需要稳定排序和冲突规则。
- **图片/BGM 等昂贵派生工作**：放在核心游戏提交之外，避免阻塞状态事务。

### 9.3 现有仓库实施观察（此前代码审阅的快照）

此前对 `master` 的审阅发现：

| 模块 | 现状与方向 |
|---|---|
| `core/turn_service.py` | 核心生产入口规模较大，建议逐步拆为 TurnCoordinator 和领域执行器 |
| `core/turn_orchestrator.py`、`runtime/turn_orchestrator.py` | 存在参考/旧版路径，需避免继续形成多套生产入口 |
| `llm/proposal_pipeline.py` | 已有统一 Proposal、JSON 解析/修复、回退、审计基础，应复用 |
| `models/proposals.py` | 已有 InputIntent / WorldTick / SceneEvent / NPCAction / Narration Proposal；应收紧 LLM 直接提供 `state_deltas` 的权限 |
| `core/context_builder.py`、`core/projections.py` | 继续强化按 Stage、按角色视角的 ContextPack 组装 |
| `core/state_delta_resolver.py` | 应成为领域 Effect → StateDeltaCandidate 的统一执行链 |
| `storage/repositories.py`、`movement_handler.py`、`quest_progression.py` | 需重点检查方法内部 `commit()` 与提前写库，收束到 UnitOfWork |
| NPC Memory 相关模块 | 保留独立知识与记忆逻辑，改为从已确认事件/权威状态注入 |

**审阅结论的局限**：上述为此前仓库代码审阅的设计观察，不代表已在本次文档整理时重新完成测试或改动代码；实施前需以最新分支逐项复核。

---

## 10. 开源游戏引擎调研结论

此前讨论了直接用开源游戏引擎承载 Story Package 的可能性：

| 项目 | 可参考能力 | 适用边界 | 结论 |
|---|---|---|---|
| [Evennia](https://github.com/evennia/evennia) | Room、Exit、角色、物品、持久化世界、Script、Lock | 偏 Python MUD / 持久文字世界 | **值得参考，但不建议现在迁移** |
| [Narrat](https://github.com/liana-p/narrat-engine) | RPG 对话、任务、背包、网页 UI、内容配置 | 偏作者编排的叙事体验 | 适合 Story Editor / 表现层参考 |
| [QuestJS](https://github.com/ThePix/QuestJS) | 地点图、出口、物品、文字互动 | JS 浏览器文字冒险 | 适合 Location/Route/Item 规则参考 |
| [ink](https://github.com/inkle/ink) | 分支剧情、固定对话、剧情编排 | 不是完整世界模拟器 | 可选预制剧情子系统 |
| [GDevelop](https://github.com/4ian/GDevelop) | 可视化条件与动作编辑 | 通用游戏事件环境 | 适合 DSL 可视化 Story Editor 参考 |
| [Godot](https://github.com/godotengine/godot) | 2D/3D 游戏客户端和 UI | 对后端 LLM 认知与权威状态无直接替代 | 后续可选前端，不是当前核心 |

**【建议基线】保留现有 Python Game Runtime，自研小而专的 `Narrative World Simulation Kernel`**，复用成熟库与 UI 设计，不重做 Unity/Godot 式通用游戏引擎，也不进行一次性 Evennia 迁移。

---

## 11. LLM 底座调研：DSH、Pi、LiteLLM、PydanticAI、Instructor

### 11.1 评估目标

不是寻找一个通用 Agent 替代整个游戏，而是尽可能降低以下维护成本：

- Provider 协议、模型目录、模型参数兼容性。
- 流式输出、取消、超时、调用失败与重试。
- 模型选型/分阶段路由、使用量和成本。
- Pydantic 结构化输出与错误修复。

与此同时**保留**游戏专有：ContextPack、知识过滤、NPC Proposal、Condition/Effect、WorldAdvancer、Memory、Canonical State、StateDelta。

### 11.2 DeepSeek Harness（DSH）

项目：[deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)

- TypeScript/Cordis 插件架构；提供 `dsh-llm`、`dsh-llm-pi-ai`、Provider 适配器、Agent Loop、Session、Tools 等。
- `dsh-llm` 可独立供插件做统一流式模型请求；Agent Loop 是另一个层次。
- 官方存在 [Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)，通过子进程 JSON-RPC 驱动 DSH Agent；**不意味着已原样暴露通用 Python `ctx.llm.stream()` API**。
- `dsh-llm-retry` 的 Agent 步骤重试**不自动适用于直接 `ctx.llm.stream()`**；调用级重试和 JSON/Pydantic 修复仍要单独规划。
- 优点：提供方抽象、多模型、会话与插件扩展较完整。
- 缺点：与现有 Python 后端跨语言；若“整套 RPG 变插件”则可能重写或维护 RPC 边界。

**【结论】不把完整 RPG 重构成 DSH 插件。** 若想复用，仅做 Python `LLMProvider` ↔ DSH Bridge 的可替换 PoC；而 **Story Authoring Agent**（通过工具自动编辑 Story Package）更适合将来作为 DSH 插件。

### 11.3 Pi / pi-ai

项目：[earendil-works/pi](https://github.com/earendil-works/pi)（注意旧资料可能仍指向 `badlogic/pi-mono` 或旧包名）。

- **`pi-ai`**：独立的 TypeScript 多模型库，模型目录、streaming、工具调用、使用量等；不要求使用 Agent Loop。
- **`pi-agent-core`**：通用 Agent Loop、工具执行和会话语义。
- **完整 Pi Coding Agent**：面向编程任务，不适合作为游戏核心世界模拟器。

**【结论】Pi-ai 在纯 TypeScript 项目中是很好的模型底座候选；当前 Python 项目若接入，则需要 Node/TS 服务桥接。** 没有必要为模型调用引入完整 Pi Agent Loop。

### 11.4 Python 原生候选

| 方案 | 最值得复用的部分 | 保留的游戏工作 | 当前评估 |
|---|---|---|---|
| [LiteLLM](https://github.com/BerriAI/litellm) | 多提供方 SDK、路由、模型接入、stream、监控 | Proposal/认知/世界状态 | **优先 PoC** |
| [PydanticAI](https://github.com/pydantic/pydantic-ai) | Pydantic 结构化输出、模型调用与重试 | 领域合法性/时间推进 | **优先 PoC** |
| [Instructor](https://github.com/567-labs/instructor) | 从 LLM 响应得到强类型 Pydantic 对象、修复 | 游戏权限校验 | 可与 LiteLLM 测试组合 |
| [aisuite](https://github.com/andrewyng/aisuite) | 轻量 Python 多模型统一 API | 几乎全部业务层 | 轻量备选 |
| [Vercel AI SDK](https://github.com/vercel/ai) | TS 多模型与 UI/流式 | Python 需要跨语言 | 不优先 |

### 11.5 目前建议与未决事项

- **【建议基线】** 首先在现有 `LLMProvider` 抽象后接入 LiteLLM SDK，或以 PydanticAI 实现受控 Stage 调用；不立即重写 ProposalPipeline。
- **【待定】** `LiteLLM` 与 `PydanticAI` 哪个做唯一主干，要用同一 ContextPack、同一模型、同一 Schema 做实测；它们也可以职责互补，但不应无理由双层包裹。
- **【待定】** 是否引入 Instructor 以替代 `OutputParser / RepairHandler` 的一部分实现。
- **【暂缓】** 以 DSH 或 pi-ai 为跨进程网关；只有需要其独有多提供方能力/鉴权时再评估。

不要把“统一模型流式 API”与“RPG Proposal 有效性”混同。任何 LLM 框架都不能替代 `PerspectiveValidator + ActionResolver + StateDeltaResolver`。

---

## 12. 推荐目录与模块边界

这是目标结构，而不是断言仓库当前已经按此实现：

```text
backend/llm_rpg/
├── api/
│   ├── game.py
│   └── streaming.py
├── application/
│   ├── turn_coordinator.py
│   ├── story_instance_service.py
│   └── save_service.py
├── content/
│   ├── story_package_models.py
│   ├── importer.py
│   ├── validator.py
│   └── schemas/
├── domain/
│   ├── action/
│   │   ├── resolver.py
│   │   └── duration_resolver.py
│   ├── world/
│   │   ├── advancer.py
│   │   ├── time.py
│   │   └── schedule.py
│   ├── npc/
│   │   ├── simulator.py
│   │   └── planner.py
│   ├── rules/
│   │   ├── conditions.py
│   │   ├── triggers.py
│   │   └── effects.py
│   ├── state/
│   │   ├── canonical.py
│   │   └── delta_resolver.py
│   └── quest/
├── cognition/
│   ├── projections.py
│   ├── context_assembler.py
│   └── perception.py
├── memory/
│   ├── npc_memory.py
│   ├── retrieval.py
│   └── post_commit_writer.py
├── llm/
│   ├── provider.py
│   ├── provider_litellm.py   # PoC 候选
│   ├── proposal_pipeline.py
│   ├── stage_router.py
│   └── prompts/
├── infrastructure/
│   ├── database/
│   │   ├── uow.py
│   │   └── repositories/
│   └── assets/
└── observability/
    ├── audit/
    └── replay/
```

重点不是文件夹多少，而是保证三个**不可混淆的权力边界**：

1. Story Package 的定义权属于作者；Runtime 可以变化的是实例状态，而不是无意间篡改已发布剧本。
2. LLM 有**提议权/表现权**，但没有事实提交权。
3. 领域执行器有规则裁决权；只有统一 UnitOfWork 可以完成权威状态提交。

---

## 13. 最小纵向 Demo 与实施顺序

### 13.1 首个可运行 Demo

使用《青云试炼》的一段场景：

| 类别 | 范围 |
|---|---|
| 地点 | 山门、外门广场、试炼峰（3 个） |
| 路线 | 2 条，至少 1 条受 Condition 限制 |
| NPC | 师姐与竞争者（2 名） |
| 物品 | 试炼令牌（1 种） |
| Lore | 一条公开规则、一条可发现隐藏线索 |
| 关键事件 | 试炼峰阵法异常（时间/进入地点触发） |
| NPC 行为 | 师姐按 Schedule 从山门去藏书阁（需增加必要地点或将路线简化） |
| 机制 | 玩家观察/调查/交谈/移动/等待、可变耗时、离场 NPC 推进、事件顺序、NPC 私人记忆 |

### 13.2 建议交付步骤

| 阶段 | 交付物 | 验收标准 |
|---|---|---|
| P0 | `StoryPackage Schema v1` 骨架与引用验证 | 能加载 14 类对象的最小样例并报出非法引用 |
| P1 | `Condition / Trigger / Effect` Typed DSL | 复合条件、时间跨越触发、幂等与效果验证通过测试 |
| P2 | `ActionDurationResolver + WorldAdvancer` | 玩家动作 6 分钟可推进区间内 NPC 与事件，顺序可复现 |
| P3 | NPC `Schedule + Goal + CurrentPlan` | 玩家不在场时 NPC 按时间移动，途中状态改变会打断/改计划 |
| P4 | `ContextPack + NPCActionProposal` | 无越权上下文，模型输出只能变成受限动作，不能直接改 StateDelta |
| P5 | UnitOfWork 收束与回放 | 异常回滚、重试不重复发奖、重建状态一致 |
| P6 | Narration / NPC Memory 闭环 | 玩家只获知可见事件，NPC 知识来自感知、不会全知 |
| P7 | LiteLLM vs PydanticAI PoC | 统一样例下比较正确率、延迟、成本、错误处理和维护量 |
| P8 | Web UI / Story Editor MVP | 可以编辑地点、路线、NPC、事件和条件并运行 Demo |

> **执行建议**：`P0–P5` 应以核心逻辑可运行与可测试为目标；不必等所有 14 类对象的高级字段实现完毕才开始纵向验证。可以先支持必要字段、稳定引用和规则闭环。

### 13.3 回归测试清单

- 玩家不操作时逻辑时间不变；玩家“等待/打坐”推进指定时间。
- 玩家某动作耗时从 08:00 到 08:06，08:02 与 08:05 的 NPC 动作被正确插入。
- 同一唯一物品不能被两个角色同时取得。
- 已死 NPC 不会被日程系统继续移动。
- 玩家开始休息后若在中途被袭击，动作正确中断且时间停在事件时刻。
- 隐藏 NPC 行动影响权威状态，但不会未经发现出现在玩家旁白中。
- NPC 能依据错误信念做决策，但其信念不改变世界客观真相。
- LLM 提出不存在的物品、越权知识或非法移动时被拒绝。
- JSON 输出不合法或模型超时时采用有限重试/安全回退。
- 事务提交失败后 State 和 Event 不出现部分成功；请求重试不重复发放奖励。
- 已提交事实的 Narration 失败不会回滚游戏回合。

---

## 14. 尚未冻结的关键设计问题

以下问题**没有在此前对话中完全定稿**，后续需要形成各自的 v1 规范：

1. **Story Package 精确定义**：字段必填、枚举、稳定 ID 命名空间、Schema 版本、条件语法终稿。
2. **世界时间单位与计量**：全局以整数秒或逻辑 Tick 为权威；日历、时区、技能时间是否允许小数与如何取整。
3. **行为起止边界**：玩家动作的实际效果在开始、过程中还是完成时发生；不同动作能否被打断。
4. **NPC 决策时机和预算**：何种事件导致重新计划、每回合最多调用多少次模型，长动作如何压缩。
5. **同一时刻的事件排序**：优先级、先后依赖、冲突资源、同刻并发定义。
6. **Story Director 权限**：是否引入动态剧情提案、哪些对象允许模型新增以及新增的审计/版本边界。
7. **Quest / PlotBeat 时间错过后的分支**：如何避免玩家自由探索时主线死锁。
8. **LLM Provider 最终选型**：LiteLLM、PydanticAI、Instructor、Pi-ai、DSH 的范围以 PoC 为准，不因流行度提前绑定。
9. **Agent Session 的使用**：NPC 只使用有状态游戏记忆+一次模型调用，还是需要独立长期模型会话；建议先前者。
10. **Story Editor 方案**：从 JSON/YAML 表单到可视化地图和条件编辑器分阶段实现。

---

## 15. 决策记录（ADR 摘要）

| 编号 | 决策 | 状态 | 原因 |
|---|---|---|---|
| ADR-001 | Story Package 以结构化对象 + 自然语言混合表示 | 已确定方向 | 机器可验证与叙事表现并重 |
| ADR-002 | 保留 14 类顶层对象，Scene 暂不单列 | 建议基线 | 降低模型复杂度 |
| ADR-003 | Condition/Trigger/Effect 统一 Typed DSL | 建议基线 | 统一 Route/Quest/Ability/Event 的规则 |
| ADR-004 | 不做现实时间常驻世界，改为玩家行动推进逻辑时间 | **已确定；替代旧方案** | 复杂度与 LLM 成本可控 |
| ADR-005 | 不可见 NPC 也随玩家动作消耗的时间演进 | **已确定** | 保留世界真实生活感 |
| ADR-006 | NPC 使用 Schedule + Goal + Runtime CurrentPlan | 建议基线 | 规则驱动日常、LLM 决策重要节点 |
| ADR-007 | 世界真相与角色 Knowledge/Belief/Memory 分离 | **已确定** | 防止全知与记忆污染 |
| ADR-008 | LLM 只产出 Proposal，不能直接提交 StateDelta | **已确定** | 可验证、可回放、可测试 |
| ADR-009 | 单一权威 UnitOfWork 提交所有关键世界变更 | 建议基线 | 防止部分提交和并发异常 |
| ADR-010 | 不把整个 RPG 迁移到 Evennia/DSH/Pi Agent | 现阶段建议 | 避免改造底座反而增加复杂度 |
| ADR-011 | 优先 PoC Python 原生的 LiteLLM/PydanticAI | **待最终选型** | 与现有 Python/Pydantic 代码契合 |

---

## 16. 参考项目与后续文档拆分

### 16.1 参考项目

- 游戏引擎：[Evennia](https://github.com/evennia/evennia)、[Narrat](https://github.com/liana-p/narrat-engine)、[QuestJS](https://github.com/ThePix/QuestJS)、[ink](https://github.com/inkle/ink)、[GDevelop](https://github.com/4ian/GDevelop)。
- 通用/插件化 LLM：[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)、[Pi](https://github.com/earendil-works/pi)、[LiteLLM](https://github.com/BerriAI/litellm)、[PydanticAI](https://github.com/pydantic/pydantic-ai)、[Instructor](https://github.com/567-labs/instructor)。
- 项目仓库：[llm_rpg_engine](https://github.com/sskkde/llm_rpg_engine)。

### 16.2 后续拆分建议

当前单篇文件是讨论汇总，可在方案收敛后拆成可实现的规范：

```text
docs/design/
  00-overview-and-decisions.md
  01-story-package-schema-v1.md
  02-rule-dsl-condition-trigger-effect.md
  03-action-duration-and-world-advancer.md
  04-npc-autonomy-schedule-goal-plan.md
  05-cognition-and-memory.md
  06-engine-llm-context-proposal-protocol.md
  07-state-delta-uow-and-replay.md
  08-llm-provider-evaluation.md
  09-mvp-acceptance-tests.md
```

---

## 17. 最终架构定义

> **LLM RPG Engine 是一个由玩家行动推动逻辑时间、使用确定性规则维护权威世界状态、使用独立 NPC 认知模型产生自主行为、并由 LLM 负责受限决策提案与叙事表现的半开放式文字 RPG Runtime。**
>
> **Story Package 定义世界和剧情约束；WorldAdvancer 让世界在每次经过的游戏时间区间内同步演进；Condition/Trigger/Effect 约束合法变化；StateDelta 与 UnitOfWork 决定事实何时成立；NPC Memory 与 Perspective 保证角色认知有边界；LLM 是受约束的创作与决策能力，而不是世界状态的最高权威。**

**当前下一步最值得落地的三项正式规范**：

1. `Story Package Schema v1` 的可执行 Pydantic/JSON Schema（先实现最小字段）。
2. `ActionDuration + WorldAdvancer + NPC Schedule v1` 的因果顺序与中断规则。
3. `ContextPack v1 + NPCActionProposal v1` 的端到端运行闭环。

LLM 底座选型可以与上述规范并行 PoC，但不应反向改变游戏世界的权威执行边界。
