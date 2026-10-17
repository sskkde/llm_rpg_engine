# 路线图草案：从回合生成到规则驱动世界

> **当前选定目标**：Python（FastAPI）游戏后端 + Next.js Web 前端，按本文四阶段推进。设计基线见 [RFC（LLM RPG Engine 设计总结，2026-10-08）](./llm_rpg_engine_design_summary_2026-10-08.md)。旧 [DSH 原生迁移目标](../v2_dsh_rpg_engine.md)已被替代，仅保留历史正文。
>
> **进度（2026-10-17）**：**阶段三已完成**（最小时间模拟纵切片：固定微型世界、共享 `WorkingState` 的按时间排序推进、离场 NPC 与唯一物品竞争、可感知中断与实际时间截断、单次权威提交与投影边界）。证据见 [`.omo/evidence/phase3/20261017-p3-timesim/`](../../.omo/evidence/phase3/20261017-p3-timesim/)；计划见 [阶段三实施计划](../../.omo/plans/phase3-time-simulation.md)。阶段四未实施。
>
> **进度（2026-10-16）**：**阶段二已完成**（契约收紧、实体授权、领域裁决、事件与认知事实边界、安全回退、恢复兼容；远端全量验收两套配置均 0 失败，独立复核缺陷全部修复）。证据见 [`.omo/evidence/phase2/20261016-p2-authority/`](../../.omo/evidence/phase2/20261016-p2-authority/)；计划见 [阶段二实施计划](../../.omo/plans/phase2-llm-authority.md)。
>
> **进度（2026-10-15）**：**阶段一已完成**（原阶段一计划 + [阶段一补齐计划](../../.omo/plans/phase1-turn-foundation-completion.md) 的 W0–W4 与收口修复）。证据见 [`.omo/evidence/phase1/20261015-p1-completion/`](../../.omo/evidence/phase1/20261015-p1-completion/)；当前保证与残留边界见 [`backend/docs/RECOVERY_AND_INVARIANTS.md`](../../backend/docs/RECOVERY_AND_INVARIANTS.md)。
>
> RFC 的 P0–P8 是建议交付步骤，本草案把演进组织为四个阶段；两者层次不同，细节仍需后续审议。

## 总体目标

从“LLM 生成回合内容”逐步演进为规则驱动的世界：规则负责状态与模拟，LLM 在受限边界内提出行动建议，并负责叙事表现。

## 阶段一：稳固回合底座

- **目标：** 建立可信、可恢复、可审计的回合提交路径。
- **范围：** 写入审计；关键状态、事件、时间与必要认知的原子提交；幂等与并发控制；提交后旁白；统一耗时语义；失败场景回归验证。
- **退出标准：** 关键状态与事件原子落库，提交失败不留下部分游戏副作用；重试和并发不会重复执行；提交后断线可幂等取回完整结果；事实性旁白只在提交成功后发送，叙事失败不回滚已提交事实。
- **边界：** 不包含 LLM 权限改造或 WorldAdvancer。恢复先幂等取回完整结果，不做逐片 SSE 续传。非必要摘要、索引与图片/BGM 等资产在提交后派生。

## 阶段二：收紧 LLM 权限

- **目标：** 将 LLM 的输出从状态变更候选收紧为受限动作提案与叙事表现；权威状态变化由引擎裁决。
- **范围：** 复用现有 ProposalPipeline；限定可提议的动作与参数；由领域逻辑生成 Delta；验证实体权限；提供安全回退。
- **退出标准：** 提议经过确定性验证后才影响状态；非法、越权或不可用的提议有可预测的安全处理；旁白与规则提交边界清晰。
- **实施结果（2026-10-16）：** 已建立唯一可信链路 `LLM 受限提案 → 严格契约检查 → 引用与角色权限检查 → 领域规则裁决 → 引擎生成事件/Delta/必要认知 → 原子提交 → 提交后表现`。生产 wire 契约收紧为 `contract_version=2`（递归 `extra=forbid`，不含任何可执行字段）；授权表与提示词读同一份 `PRODUCTION_ACTION_PERMISSIONS`；world/scene 收敛为引用型；模型文本不再进入 `memory_facts`/`npc_beliefs(fact)`/`memory_summaries`/事件公开载荷；公开 `action_resolution` 摘要贯通 REST 与 SSE 且同键恢复只读。证据与残留见 [`.omo/evidence/phase2/20261016-p2-authority/`](../../.omo/evidence/phase2/20261016-p2-authority/)。

## 阶段三：最小时间模拟纵切片

- **目标：** 用小规模可验证样例证明规则能够驱动世界随时间演进。
- **范围：** 少量地点、2 名 NPC、唯一物品与定时事件；按时间排序并共享 WorkingState；支持离场推进；覆盖资源冲突与中断；规则优先。
- **退出标准：** 同一输入按确定规则推进并得到一致结果；事件顺序、共享状态、冲突和中断可验证；离场推进不依赖逐回合 LLM 托管。
- **实施结果（2026-10-17）：** 已交付 opt-in 专用世界 `phase3_trial_micro`（`World.ruleset_json.phase3_profile = {id: trial_micro_v1, schema_version: 1}`）与封闭规则集：3 个地点（山门 / 广场 / 试炼峰）、2 名 NPC（甲 / 乙）、1 枚唯一令牌与固定 tick 表（+2 出发、+5 抵达与同刻争用、+6 试用、+7 可感知中断、+8/+9 后续行程）。正式回合入口内复用既有准入链，另由纯内存 `WorldAdvancer` 在**同一个 `WorkingState`** 上按 `(logical_tick, phase, actor, step)` 排序推进：同刻竞争即时读取前一步结果（甲取得、乙明确失败且不复制实例）、离场 NPC 与物品操作不依赖逐回合 LLM、玩家持续动作在 +7 被中断并**实际截断**（`planned=10/15 → actual=7`，截短时长不再过 validator）。运行态不新增表：游标与一次性状态在 `session_states.global_flags_json` 的命名空间内，NPC 行程在 `session_npc_states.hidden_plan_state`，定时步骤在 `scheduled_events.trigger_conditions_json`，唯一物品只更新同一库存行的 owner；首回合库存/调度/游标经既有初始化计划延迟落库，澄清回合不落任何初始化行。旧 `ScheduledEventProcessor` 拒绝阶段三命名空间行，普通世界行为不变。**未提前实施阶段四**：无通用 Condition/Trigger/Effect DSL、无完整 Schedule/Goal/CurrentPlan、无内容编辑器、无第二场景纯配置能力、无存档内容版本绑定、无战斗伤害系统、无后台世界循环。证据与残留见 [`.omo/evidence/phase3/20261017-p3-timesim/`](../../.omo/evidence/phase3/20261017-p3-timesim/)。

## 阶段四：沉淀内容能力

- **目标：** 让新增场景主要由内容配置表达，而非修改核心逻辑。
- **范围：** 沿现有 ContentPack 渐进扩展；稳定 ID 引用；存档绑定内容版本；最小 Typed DSL；Schedule、Goal、CurrentPlan；由事件派生知识与记忆；保持旧内容存档兼容。
- **退出标准：** 能以配置建立第二个场景而不改核心代码；引用与版本绑定可验证；旧内容存档可兼容读取或有明确安全处理。
- **实施结果（2026-10-17）：** 已交付 `content_v1` 解释器与包 schema `schema_version: 2`（严格 `extra=forbid`、单次字节捕获、路径逃逸拒绝、22 个内容错误码），canonical `RuntimeBundle` + `runtime_hash`（覆盖 bundle schema 与引擎规则版本）与版本作用域 `ref_map`；受管 UoW 内**原子发布**（dry-run 零写、独立物化 World/templates、`(package_id, version)` 冲突不覆盖、发布后语义字段冻结）；`PlaythroughInstance`/`Session` 固定版本绑定与服务器保留键 `__content_binding`，每回合按保存版本加载并在锁内重验；最小 Typed DSL（2 类 Trigger、6 种原子 Condition、9 种 Effect、2 种 fire policy，深度 8/节点 128/recipe 16/重评估 64 预算）；有限 Schedule/Goal/CurrentPlan（冻结 tie-break，失败即 fallback 重选，不逐回合调用 LLM）；事件派生认知（事件当时视角求观察者、`memory_type=episodic`、`derivation_key` 去重、`player_knowledge` 独立 `source_game_event_id` FK）与旧 phase3 行的**只读窄映射**。新增 `content_packs/trial_micro_config`（复刻阶段三 +2/+5/+6/+7/+8/+9）与 `content_packs/misty_ford`（4 地点/2 NPC，封桥→到达失败→守桥 fallback→重开→重选→抵达）；**第二场景纯配置，核心源码未因加入 B 而改动**（AST 搜索确认生产代码无 pack 字面量）。迁移 `026` 为纯增量 nullable，未回填/清洗。验收：新增 109 项测试；SQLite 全量 4137 passed/44 skipped、PG 全量 4171 passed/10 skipped、PG 必需项 0 skip。规范正文见 [`phase4-content-v1-spec.md`](phase4-content-v1-spec.md)，证据见 [`.omo/evidence/phase4/20261017-p4-content/`](../../.omo/evidence/phase4/20261017-p4-content/)。**未提前实施阶段五/六**：无完整编辑器、无 14 类对象全量字段、无通用行为树、无任意脚本/表达式、无跨包依赖、无存档自动升级、无 rewind/branch、无后台实时世界。

## 推进原则与暂缓项

- 复用现有单入口；先验证静态风险，再扩展运行行为。
- 后续阶段不得破坏前一阶段已建立的不变量；每阶段退出标准应先验证，再进入下一阶段。
- 本文只给出目标、范围和退出标准；文件级任务、排期与人日等详细方案另行编制并审批。
- 暂缓：完整编辑器、14 类高级字段、实时后台世界、整体迁移到 DSH/Pi/Evennia，以及目录大重构。
- Provider 工作仅可作为独立小型 PoC，不得阻塞主线。
