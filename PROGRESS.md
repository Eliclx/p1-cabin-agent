# P1 智能座舱 Agent — 项目进度

## Phase A: Harness 框架 + Navigation Schema SSOT ✅

> 提交: 540e54f

- eval harness 框架搭建 (eval_harness / error_collector)
- navigation schema 作为 SSOT 定义意图+槽位

## Phase B: Navigation Skill 完整实现 ✅

> 提交: 3dc6212

- navigation skill 完整实现 (schema / tools / harness / examples)
- 端侧模型 domain/intent 映射

## Phase C: Skill Registry + Context Enrich + 多层增强 ✅

> 提交: 99f4f28

|| 子步骤 | 内容 |
|--------|------|------|
| C1 | skill registry (skills/registry.py) — get_harness/get_schema/get_domain_for_intent + intent caching + _domain_to_class_name |
| C2 | context enrich (nodes/context_enrich.py) — CONTEXT_DEPS per-domain, AgentContext assembly |
| C3 | _handle_skill_task in pipeline.py — 7-step flow: registry → context_enrich → harness → tool → post_validate |
| C4 | OOS cloud fallback — pre_rules: _oos_flag, intent.py: OOS flag → skip edge |
| P0 | is_acceptable + required_slots check — INTENT_REQUIRED_SLOTS, EdgeResult.is_acceptable, fixed 8/13 flaky edge tests |
| P1 | Stage2 prompt schema injection + few-shot — _build_schema_block |

## Phase D: 迁移 + 增强 + 优化 ✅

> 提交范围: 5332225 → eeb8be0（15 个子步骤）

## Phase 1: Registry 自动发现 ✅

> 提交: d27d6c7 → f73d456 → e18b372
> eval 基线: 91.7%

## Phase 2: 地图域重构 ✅

> 提交: 8595226 → 62d8173

- 4 skill: climate, map, media, vehicle (14 intent)
- eval 91.7% 零退化

## Phase E: Legacy 清理 + 端侧优化 ✅

> 提交范围: e6a3c20 → fed1a3f

## Phase 3: Plan-and-Execute ✅

> 提交范围: cbdc099 → 34a411b
> eval: 336 条, 92.0%

## Phase 4: 记忆系统 + DST + 对话策略 ✅

> 提交范围: 04e10e8 → 90bb211
> 设计文档: docs/memory-system-design.md

| 步骤 | 内容 | 提交 | 测试 |
|------|------|------|------|
| 4A | MemoryManager (SQLite backend, dedup, heat, decay, preferences, recall) | 04e10e8 | 27/27 |
| 4B | DST + ContextBuilder (态度推断, 目标追踪, 摘要生成) | 04e10e8 | 29/29 |
| — | SSOT修复: context_builder 硬编码 → registry API | 04e10e8 | — |
| — | Skill-Memory解耦: 声明式 {DOMAIN}_MEMORY + 依赖注入 | 04e10e8 | 22/22 |
| 4E | 旧模块迁移: episodic/user_profile → MemoryManager 薄代理 | 688dbe9 | 38/38 |
| 4C | Policy 对话策略 + 域规则解耦 | a472655 | 34/34 |
| 4D | Proactive 主动引擎 + 域规则解耦 | 5252639 | 33/33 |
| 4F | Memory evolution (异步 LLM, 三层分离) | 90bb211 | 33/33 |

## Phase 5: DA 对话行为识别 ✅

> 提交范围: b24abb0 → a4a5379

| 步骤 | 内容 | 提交 |
|------|------|------|
| 5.0 | DA 引擎 + 通用规则 (confirm/deny/select) | b24abb0 |
| 5.0 | Climate 域规则 (模式/温度/车窗纠正) | b24abb0 |
| 5.0 | Map 域规则 (POI选择/路线纠正) | b24abb0 |
| 5.1 | intent_classifier 集成 (DENY短路/SELECT构造/CORRECTION合并) | b24abb0 |
| fix | CORRECTION 从 tool_result 提取业务参数，过滤元数据 | 0c1bdc5 |
| fix | 删全局变量，_is_confirm_positive 直接调 DA 分类 | a4a5379 |

**DA 类型：** CONFIRM / DENY / CORRECTION / SELECT / SLOT_FILL / NEW_INTENT

**解耦：** nodes/da.py（通用引擎）+ skills/{domain}/da_rules.py（per-domain）+ registry 自动发现

## Phase 6A: Error Recovery ✅

> 提交: 59b6bcd

| 内容 | 说明 |
|------|------|
| 错误分类 | TIMEOUT / NETWORK / API_ERROR / EMPTY_RESULT / INVALID_INPUT / UNKNOWN |
| Map 重试 | search_poi 空结果→扩大半径×3, 超时→重试, 网络→重试, 地名无效→友好提示 |
| Climate | 硬件失败→友好错误（不重试） |
| Pipeline 集成 | 工具执行包裹 retry 循环，最多重试 1 次 |
| 友好错误 | 6 种错误类型对应友好模板 |

**解耦：** nodes/retry.py（通用引擎）+ skills/{domain}/retry_rules.py（per-domain）+ registry 自动发现

## Phase 6B: NLG 润色 — 不需要

现有模板已覆盖所有场景（单任务 harness.format_response + 多任务 LLM 聚合）。CORRECTION 重执行走同一个 tool + harness，回复自然包含新参数。车载场景简洁确定性 > 花哨。

## Action 信号层 ✅

> 提交范围: 871313c → 10f3770

| 内容 | 说明 |
|------|------|
| CabinAction 数据模型 | domain + intent + command + params |
| Per-domain 转换 | skills/{domain}/action_format.py |
| 通用引擎 | actions/engine.py（从 registry 调度，零域硬编码）|
| Pipeline 集成 | task_result 新增 action 字段，双通道输出 |

**输出示例：**
- 空调开24度 → action: `{domain: climate, command: ac_on, params: {temperature: 24}}`
- 导航去重庆 → action: `{domain: map, command: start_nav, params: {distance_km: 300}}`
- 查油量 → action: null（查询类无硬件动作）

## 代码审查 ✅

> 提交: f2e72f0

| 维度 | 结果 |
|------|------|
| 循环依赖 | 零 |
| 死代码 | 无未使用模块 |
| 引擎硬编码 | 6 个通用引擎全部零域硬编码 |
| 依赖方向 | 单向：nodes → registry ← skills |
| memory 独立性 | memory/ 零外部依赖（除 _instance.py 启动时一次性） |
| 旧模块代理 | episodic_memory.py / user_profile.py 薄代理 |
| registry 一致性 | 6 个 per-domain 字段全部一致 |
| 冗余文件 | 已清理（tools/ 目录 + 产物文件从 git 移除） |

---

## 当前状态总览

| 指标 | 数值 |
|------|------|
| skill 域 | 4 (climate, map, media, vehicle) |
| intent 总数 | 11（skill）+ 4 特殊 |
| 通用引擎 | 6 个（policy / proactive / action / da / retry + registry） |
| 解耦模式 | per-domain 声明 + registry 发现 + 通用引擎调度 |
| 纯逻辑测试 | **339 passed, 0 failed** |
| 全量测试 | 573 passed + 5 LLM flaky + 19 skip |
| eval 336 条 | 92.0% |
| 代码量 | ~24K lines (Python) |

### Per-Domain 规则完整性

```
skills/{domain}/
  ├── schema.py           → registry: blackboard, memory_meta, domain_signals
  ├── harness.py          → registry: harness
  ├── tools.py            → registry: tools
  ├── policy_rules.py     → registry: policy_rules       (climate/map)
  ├── proactive_rules.py  → registry: proactive_rules    (climate/map)
  ├── action_format.py    → registry: action_formatters  (climate/map/media)
  ├── da_rules.py         → registry: da_rules           (climate/map)
  └── retry_rules.py      → registry: retry_rules        (climate/map)
```

加新 skill 只需建目录 + 按需写文件，引擎和 registry 零改动。

### 解耦 6 原则落地记录

| 原则 | 落地案例 |
|------|---------|
| 1. 变更频率不同 → 隔离 | Eval-Sandbox 独立项目；per-domain 规则 vs 通用引擎 |
| 2. 替换可能性 → 抽接口 | MemoryBackend duck typing；LLM callable 注入 |
| 3. 测试需要独立 → 注入依赖 | MemoryManager 通过 MemoryConfig 注入；_instance.py 单例可替换 |
| 4. 多人并行开发 → 划边界 | 每个 skill 目录独立；memory/ 零外部 import |
| 5. 影响范围过大 → 单一职责 | Policy 不做 DA；Action 不做 voice_reply |
| 6. 逻辑方向相反 → 打破循环 | nodes → registry ← skills（单向依赖） |

### 遗留项（不急）

| # | 内容 | 优先级 |
|---|------|--------|
| 1 | Event.key_entity 有 intent→field 硬编码（navigate→destination），应从 memory_meta 驱动 | 低 |
| 2 | slot_transfer.py TODO: 支持 round 指定和序数词 | 低 |
| 3 | response.py TODO: suspended 任务恢复 | 低 |
| 4 | shared/ 在项目根目录外，部署时需处理 | 低 |

---

## ⏭️ 下一步：P1-Eval-Sandbox（独立项目）

> 多 Agent 自动化评估沙盒。以 action 为第一校验维度 + DA 分类准确性 + Policy 决策合理性。

### 架构

```
User Agent（模拟司机）
  → 发送多轮中文对话
  → Cabin Agent（P1 座舱系统，被测）
  → Judge Agent（评判对错）
      → action 输出 vs 期望 action（客观校验）
      → DA 分类准确性
      → Policy 决策合理性
  → 错误报告
```

### 行业参考

- **CarMem**（宝马，COLING 2025）— 100 用户×10 偏好×50 对话
- **VehicleMemBench**（中科大，2026）— 多用户长程记忆基准，可执行沙盒
- **In-Car Agent V1** (goreasoning) — 200K 中文意图 + 100K 多轮

### 与 P1 的边界

- P1 是被测系统（不动）
- Sandbox 是测试工具（独立项目）
- 解耦理由: 变更频率不同（原则 1）+ 测试需要独立（原则 3）

### 优先级

⏸ 待启动。

---

## KVRet 中文 Eval ✅

> 提交: 6bcbbca

- 22 个中文场景（基于 KVRet 多轮模式重写）
- 9 种模式：search→navigate, reroute, explain, abandon, retry_limit, correction, conditional, proactive, normal
- 20 passed, 0 failed

## 车载对话数据集调研 ✅

| 数据集 | 规模 | 适配性 |
|--------|------|--------|
| KVRet | 3,031 多轮 | ⭐⭐⭐ 域直接对应 |
| In-Car Agent V1 | 200K 中文 | ⭐⭐⭐ 最全，需邮件申请 |
| Magic Data | 90K+ 条 | ⭐⭐ 中文，单轮为主 |
