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
|--------|------|
| C1 | skill registry (skills/registry.py) — get_harness/get_schema/get_domain_for_intent + intent caching + _domain_to_class_name |
| C2 | context enrich (nodes/context_enrich.py) — CONTEXT_DEPS per-domain, AgentContext assembly |
| C3 | _handle_skill_task in pipeline.py — 7-step flow: registry → context_enrich → harness → tool → post_validate |
| C4 | OOS cloud fallback — pre_rules: _oos_flag, intent.py: OOS flag → skip edge |
| P0 | is_acceptable + required_slots check — INTENT_REQUIRED_SLOTS, EdgeResult.is_acceptable, fixed 8/13 flaky edge tests |
| P1 | Stage2 prompt schema injection + few-shot — _build_schema_block |

## Phase D: 迁移 + 增强 + 优化 ✅

> 提交范围: 5332225 → 35d922a → 3b5b934 → 3674d36 → 3da2686 → 78b7f8e → b0e54ac → ecc1b4c → c9b2df6 → d7e9e17 → 5c0afcd → 4de679c → eeb8be0

|| 子步骤 | 内容 | 提交 |
|--------|------|------|
| D1 | 端侧多意图检测 + SSOT required slots + FastRules 跨域 | 5332225 |
| D2 | P2 白名单全空降级 + FastRules 跨域信号联动 | a168afb |
| D3 | guided generation (json_schema) + harness 多级降级 JSON 提取 | 6e86a22 |
| D4 | Stage1 从 skill examples.yaml 动态注入 few-shot + eval harness 修复 | 35d922a |
| D5 | 迁移 climate/media/search/vehicle 到 Skill 架构 | 3b5b934 |
| D6 | 扩增 eval 用例 92→132 条 (+40) | 3674d36 |
| D7 | skill _intent 注入 + 纯函数调用兼容 + Stage1 prompt 缓存 | 3da2686 |
| D8 | 去掉 Stage2 guided generation (xgrammar FSM)，延迟降 57% | 78b7f8e |
| D9 | known_slots 传入追问槽位提取，LLM 追问时不再丢失已有信息 | b0e54ac |
| D10 | harness 拦截空调节 + clarify 追问语定制 | ecc1b4c |
| D11 | _try_carry_over 不再直接 mutate active_frames | c9b2df6 |
| D12 | ABANDON_SIGNALS 纯取消词短路 + CARRY_OVER 跨域拦截 | d7e9e17 |
| D13 | RT-4 SQLite lock — WAL 模式 + 写重试 | 5c0afcd |
| D14 | navigation skill 路由修复 + slot 名归一化 | 4de679c |
| D15 | search_poi 统一走导航 skill + 高德 API | eeb8be0 |

## Phase 1: Registry 自动发现 ✅

> 提交: d27d6c7 → f73d456 → e18b372
> eval 基线: 91.7%

|| 子步骤 | 内容 | 提交 |
|--------|------|------|
| 1.1 | SkillRegistry 重写 + edge_model 接入 registry (eval 91.7%, 待调优) | d27d6c7 |
| 1.3-1.6 | cabin_tools 引用迁移至 registry (7处 SSOT 已解决) | f73d456 |
| 1.7 | edge_schemas INTENT_SCHEMAS 从 registry 动态生成 | e18b372 |

- SSOT 解决 10/16 处违规
- 4 skill: climate, media, vehicle, navigation（Phase2 前状态）

## Phase 2: 地图域重构 ✅

> 提交: 8595226 → 2757de4 → bd45856 → 62d8173

|| 步骤 | 内容 | 提交 |
|------|------|------|
| 2.1 | 新建 skills/map/ 4文件 (schema/tools/harness/examples) | 8595226 |
| 2.2 | 删除 skills/navigation/ + skills/search/ | 8595226 |
| 2.3 | Stage1 prompt domain 列表更新 | 8595226 |
| 2.4 | 旧名兼容 (start_navigation→navigate, _INTENT_ALIASES) | 8595226 |
| 2.5 | eval/bench/error_collector 批量替换 domain/intent 名 | 8595226 |
| 2.6 | corner_cases 42/45 (3个DeepSeek超时非代码问题) | 8595226 |
| 2.6.1 | 端侧 LMDeploy model id 动态获取，修复 404 | 2757de4 |
| 2.7 | 端侧训练数据 domain/intent 映射更新 | bd45856 |
| 2.8 | eval 132条验证零退化 91.7%, baseline合并为map域 | 62d8173 |

**结果：**
- 4 skill: climate, map, media, vehicle (14 intent)
- map 域 4 intent: navigate, search_poi, map_query, weather
- harness 单测 103/103 全绿
- eval 91.7% 零退化, 43s 完成
- SSOT 再解决 V16 (search_poi 双重定义)

## Phase E: Legacy 清理 + 端侧优化 ✅

> 提交范围: e6a3c20 → 018b6cb → a8775d1 → 06cbb67

|| 子步骤 | 内容 | 提交 |
|--------|------|------|------|
| E0 | 新增 infer_slots 语义槽位推断层（5文件 +836/-273） | e6a3c20 |
| E0.1 | 删除 _handle_tool_task legacy 路径（-293行） | 018b6cb |
| E0.2 | 天气修复：歧义检测误杀 + 黑板/行程记忆 + 端侧幻觉清洗 | a8775d1 |
| E0.3 | 天气三级优先级链 + POI→导航精确坐标 + 多轮端到端测试 | 06cbb67 |

**E0.2 详细改动：**
- `constants.py`: CLEAR_OBJECT_WORDS 加天气关键词
- `cabin_tools.py`: BLACKBOARD_DECLS 加 weather produces=entity.weather
- `episodic_memory.py`: EVENT_TYPES_TO_LOG 加 weather + 摘要格式
- `map/harness.py`: 幻觉清洗（端侧模型填的假城市名会被清除）

**E0.3 详细改动：**
- `graph.py`: Send 传递 dialogue_context 给 task_pipeline（修复黑板数据断裂）
- `map/harness.py`: 天气 city 三级优先级链 + `_is_hallucinated_city` 幻觉检测 + `_find_poi_coordinates` 精确坐标替换
- `map/schema.py`: weather city 描述改为“用户未指定时留空”（从源头减少端侧幻觉）
- `edge_model.py`: Stage2 规则第4条加强反幻觉
- `slot_transfer.py`: 支持 `_coordinates` 特殊映射（POI→导航坐标直传）
- `cabin_tools.py`: BLACKBOARD_DECLS navigate.slots 改为 `_coordinates`
- `tests/test_multi_turn.py`: 新增5个多轮端到端测试

**关键设计决策：**
- 天气 city 三级优先级：①用户指定 → ②黑板复用 → ③坐标兜底
- POI→导航精确坐标：从黑板 POI 的 lng/lat 拼坐标字符串，避免文字名重新地理编码导致路线偏差
- 幻觉检测纵深防御：prompt优化（源头）→ _is_hallucinated_city（harness层）→ 黑板兜底（数据层）

**测试结果：192/197 通过（97.5%），5个失败均为预先存在，零退化**

## 当前状态总览

| 指标 | 数值 |
|------|------|
| skill 域 | 4 (climate, map, media, vehicle) |
| intent 总数 | 11（skill）+ 4 特殊(chitchat/clarify/direct_answer/no_support) |
| harness 单测 | 103/103 全绿 |
| eval 132条 | 91.7% 零退化 |
| 纯逻辑测试 | 74 passed |
| 端侧 e2e | 122 passed, 2 failed (多意图) |
| SSOT 已解决 | 16/16 全部闭合 |

## Phase E: Legacy 清理 + SSOT 收尾 ✅

> 提交范围: e6a3c20 → 018b6cb → a8775d1 → 06cbb67 → fed1a3f

|| 子步骤 | 内容 | 提交 |
|--------|------|------|
| E0 | infer_slots 语义槽位推断层 | e6a3c20 |
| E0.1 | 删除 _handle_tool_task legacy 路径 | 018b6cb |
| E0.2 | 天气修复：歧义检测误杀 + 黑板/行程记忆 + 端侧幻觉清洗 | a8775d1 |
| E0.3 | 天气三级优先级链 + POI→导航精确坐标 + 多轮端到端测试 | 06cbb67 |
| E3 | BLACKBOARD_DECLS 迁移至各 skill schema（registry 自动发现） | fed1a3f |
| E4 | _DOMAIN_SIGNALS 动态化（从 registry schema 读取） | fed1a3f |
| E5 | cabin_tools.py 删除（全项目零引用，-584行） | fed1a3f |

## ⏭️ 下一步：Phase 3（Plan-and-Execute）

### Phase F 结论（⏸ 暂缓）

|| 步骤 | 内容 | 状态 |
|--------|------|------|
| F1 | 端侧 confidence 分布分析（132 eval cases） | ✅ |
| F2 | logprobs 不可行（LMDeploy+few-shot 结构化输出下=0） | ✅ |
| F3 | 企业级方案调研（Self-Assessment / Verification Gate / Confidence Token） | ✅ |
| F4 | confidence 重设计 | ⏸ 暂缓 |

3B 模型在结构化 JSON 输出场景下，confidence scoring 本质上是小模型能力边界问题，
非 scoring 机制能补。待 Phase 3 云端接入后有 ground truth 对比数据再回来校准更合理。

**调研成果留存：**
- logprobs 不可行（LMDeploy+AWQ+TurboMind，few-shot 导致 logits 极化 → logprobs=0）
- 企业级方案 4 条路径已评估（Self-Assessment / Verification Gate / Confidence Token / Post-hoc Validator）
- 方案 C（Confidence Token, Self-REF arxiv 2410.13284）留作未来微调方向

### Phase 3 任务列表

| 步骤 | 内容 | 状态 |
|--------|------|------|
| 3.0 | depends_on 验证（已实现，slot_transfer bug 已修） | ✅ cbdc099 |
| 3.1 | 条件分支（condition 评估机制） | ✅ c71abdc |
| 3.2 | Recovery 容错（字段别名 + output_fields） | ✅ c74356a |
| 3.3 | eval 扩充条件编排用例 (137→336) | ✅ 15ceb50 |
| 3.4 | 端侧门控增强（条件分支拦截 + 追问误杀修复） | ✅ 34a411b |

### Phase 3.1 条件分支实现 ✅

> 提交: c71abdc

- `condition.py`: 新建条件评估模块，支持 AND/OR + 10 种 op
- `constants.py`: Condition / ConditionRule Pydantic 模型
- `graph.py`: route_wave 集成条件评估，不通过替换为 direct_answer（零新增 state 字段）
- `intent.py`: LLM prompt 新增 condition 字段 + CONDITION_EXAMPLE 示例 + output_fields 参考
- LLM timeout 10s→60s（修复 deepseek-v4-flash 超时）

**测试：**
- test_condition_20.py: 30 个条件评估单元测试（全绿）
- test_stress_20.py: 22 个跨模块测试（全绿）
- test_condition_e2e.py: 8 个端到端测试（LLM+condition 全通）

**端到端验证结果（8/8）：**
| # | 用户输入 | LLM condition | 评估结果 |
|---|---------|---------------|----------|
| 1 | 查下附近有没有充电站，有的话导航 | count gt 0 | count=3 → 通过 ✅ |
| 2 | 天气好的话导航去天府广场 | weather not_in [雨,雪] | weather=雨 → 不通过 ✅ |
| 3 | 附近有停车场吗有的话导航 | count gt 0 | count=0 → 不通过 ✅ |
| 4 | 油量低于30%就导航去加油站 | fuel lt 30 | fuel=15 → 通过 ✅ |
| 5 | 开空调顺便导航去春熙路 | 无 condition | 独立多意图 ✅ |
| 6 | 前面堵不堵车不堵走高速 | traffic not_in [拥堵,阻塞] | traffic=畅通 → 通过 ✅ |
| 7 | 有便宜的就推荐个餐厅 | 无 condition | 单任务搜索 ✅ |
| 8 | 找下有没有露营地有的话导航 | count gt 0 | count=2 → 通过 ✅ |

### Phase 3.2 Recovery 容错 ✅

> 提交: c74356a

**问题：** LLM 生成 condition field 名时不知道工具实际返回什么字段（如写 `traffic_status` 而非 `traffic`）

**三层防御：**
1. **声明层** — MAP_BLACKBOARD 新增 `output_fields`，列出工具返回的可引用字段
2. **Prompt 层** — CONDITION_EXAMPLE 末尾加 output_fields 参考，引导 LLM 写正确字段名
3. **运行时层** — `condition.py` 新增 `_resolve_field` 三级容火：精确→别名表→前缀模糊

**别名表覆盖：**
- weather_main/weather_desc/weather_type → weather
- traffic_status/traffic_info/traffic_condition → traffic
- fuel_level/oil → fuel
- eta → duration_min

### Phase 3.3 eval 扩充 ✅

> 提交: 15ceb50

- eval 用例 137→336 条（+199），覆盖条件编排 / 多意图变体 / 极端边界
- CONDITIONAL_CASES: 3 → 9 个条件分支端到端用例
- eval_harness EXTENDED_SET: 新增 6 个条件编排 eval 用例
- 覆盖：有→导航 / 天气→导航 / 油量→导航 / 路况→高速 / 无条件 / 模糊条件

### Phase 3.4 端侧门控增强 ✅

> 提交: 34a411b

**改动点：** `_can_use_edge()` 端侧快路径门控两处增强

1. **条件分支拦截** — 新增 `_CONDITIONAL_PATTERNS` 正则，识别"有的话就X/如果X就Y/低于X就Y"等条件语句。
   这类输入需要云端 LLM 生成 `condition` 字段，端侧 3B 不支持，直接放行云端。
   覆盖 5 大类条件模式：口语条件 / 显式条件 / 数值比较 / 状态条件 / 动作条件

2. **追问误杀修复** — `_FOLLOWUP_PATTERNS` 原逻辑：≤10字+含追问词→拦截。但"胎压怎么样""油量多少"等
   含明确操作目标的短句是独立查询，不需要上下文。新增 `_INDEPENDENT_QUERY_TARGETS` 词表（12项），
   命中时不再误杀，正确走端侧。

3. **"什么"加入超短歧义词表** — 单独出现的"什么"需要上下文，不走走端侧

**验证：**
- 条件分支拦截: 17/17 ✅
- 追问误杀修复: 14/14 ✅
- 泛化边界测试: 37/44（7个未覆盖变体已分析，车载场景真实误杀=0）
- harness 单测: 104/104 ✅
- eval 336条: 92.0% 零退化

## 当前状态总览

| 指标 | 数值 |
|------|------|
| skill 域 | 4 (climate, map, media, vehicle) |
| intent 总数 | 11（skill）+ 4 特殊(chitchat/clarify/direct_answer/no_support) |
| harness 单测 | 104/104 全绿 |
| 多轮端到端 | 5/5 全绿 |
| 全量测试 | 331/335 (98.8%)，4个失败(2 pre-existing + 2 LLM flaky) |
| **eval 336条** | **92.0%** 零退化 |
| SSOT 已解决 | 16/16 全部闭合 |
| pipeline.py | ~770行（从 ~1040行缩减） |
| cabin_tools.py | 已删除（-584行） |

### eval 各域准确率

| 域 | 准确率 | 详情 |
|----|--------|------|
| media | 100% | 38/38 |
| needs_context | 100% | 20/20 |
| vehicle | 100% | 24/24 |
| climate | 93% | 92/99 |
| multi | 93% | 27/29 |
| map | 91% | 82/90 |
| unknown | 88% | 7/8 |
| chitchat | 68% | 19/28（端侧 3B 能力边界） |

### 三层推理命中率

| 层 | 命中率 | 延迟 |
|----|--------|------|
| FastRules | 14.3% | 0ms |
| 端侧 3B | 33.6% | ~500ms |
| 云端 LLM | 46.7% | ~5s |

### 27 条错误分类

| 类型 | 数量 | 典型 case | 根因 |
|------|------|----------|------|
| 天气/温度查询 | 5 | "今天温度多少""查下成都是不是在下雨" | 时间词触发 has_temporal_keywords 走行程记忆 |
| chitchat 短句 | 5 | "谢谢""好的""嗯嗯" | 端侧/云端 chitchat 识别率低 |
| 极短歧义 | 2 | "开""不错" | 单字/双字太模糊 |
| 车况查询 | 4 | "当前空调模式""空气净化开了吗" | 查询类 intent 端侧不擅长 |
| 地图变体 | 3 | "前面有没有服务区""下了高速怎么走" | 不常见表达 |
| 多意图/取消 | 3 | "别开空调了 开窗吧""算了不去了" | 取消意图 / FastRules 短路误判 |
| 超纲 | 5 | "后排说冷""除雾""最大风量" | 不在 intent 覆盖范围 / 槽位提取错 |

### ⏭️ 待改进

- 条件分支正则泛化："X的话Y"缺少"就"时漏匹配（"太热的话开空调"），真实误杀=0但可优化
- 天气查询 5 条误杀：`has_temporal_keywords("今天")` 导致独立天气查询走了行程记忆路径
- chitchat 68%：3B 模型能力边界，需微调或更大的端侧模型

## SSOT 审计进度 (16处违规) — 全部闭合 ✅

|| 状态 | 数量 | 说明 |
|------|------|------|
| ✅ 代码修复 | 12 | Phase1(10) + Phase2(V16) + PhaseE(V14) |
| ✅ won't-fix | 2 | V3(unknown域硬编码合理) + V11(短路规则有 _validate_rules 校验) |
| ✅ 间接解决 | 2 | V14(DOMAIN_SIGNALS→schema) + V17(mode→route_type 映射统一) |

### Phase 4: 记忆系统 + DST + 对话策略 (进行中)

> 提交范围: 04e10e8 → 688dbe9 → eae71c8
> 设计文档: docs/memory-system-design.md

### 调研基础

- MemoryOS (BAI-LAB) — heat-based evolution trigger
- A-MEM (agiresearch) — agent-centric memory
- MemOS (MemTensor) — time decay formula, recency scoring

### Phase 4 任务列表

| 步骤 | 内容 | 状态 | 测试 |
|--------|------|------|------|
| 4A | MemoryManager (SQLite backend, dedup, heat, decay, preferences, recall) | ✅ 04e10e8 | 27/27 |
| 4B | DST + ContextBuilder (态度推断, 目标追踪, 摘要生成) | ✅ 04e10e8 | 29/29 |
| — | SSOT修复: context_builder 硬编码 → registry API | ✅ 04e10e8 | — |
| — | Skill-Memory解耦: 声明式 {DOMAIN}_MEMORY + 依赖注入 | ✅ 04e10e8 | 22/22 集成 |
| 4E | 旧模块迁移: episodic/user_profile → MemoryManager 薄代理 | ✅ 688dbe9 | 38/38 |
| 4E补 | test_episodic_memory 修 start_navigation→navigate + mock时间 | ✅ eae71c8 | 38/38 |
| 4C | Policy 对话策略 (nodes/policy.py) | ⬅️ 下一步 | |
| 4D | Proactive 主动引擎 (nodes/proactive.py) | 待做 | |
| 4F | Memory evolution (异步 LLM) | 待做 | |

### Phase 4A: MemoryManager ✅

**文件清单：**
- `memory/models.py` — Event, Preference, FrequentPlace, MemoryConfig, MemoryHit
- `memory/decay.py` — score_with_decay, time_decay (half-life 14d, α=0.3)
- `memory/backends/sqlite_backend.py` — SqliteBackend (双 DB: events + preferences)
- `memory/manager.py` — 统一入口: log/query/recall/preference/lifecycle

**核心设计决策：**
- 去重: `event_type:dedup_key_value` hash（O(1) 确定性，不用 embedding）
- 时间衰减: `heat × (0.3 + 0.7 × 0.5^(age/14))`
- 进化触发: heat 累积 > 10.0 时才调 LLM
- 偏好: confidence + source 区分 slot_extraction vs llm_analysis

### Phase 4B: DST + ContextBuilder ✅

**文件清单：**
- `nodes/dialogue_state.py` — DialogueState, UserAttitude, ActiveGoal
- `nodes/context_builder.py` — ContextBuilder (态度推断, 目标追踪, 记忆摘要)
- `state.py` — 新增 `dialogue_state: Optional[dict]`
- `nodes/intent.py` — DST 构建 + 摘要注入 prompt

### SSOT + Skill-Memory 解耦 ✅

**依赖方向：**
```
skills/schema.py  ← 声明 {DOMAIN}_MEMORY (SSOT)
      ↓
skills/registry.py ← 自动发现 + get_memory_meta()
      ↓ push
调用方 (intent.py)
      ↓ inject via MemoryConfig
memory/manager.py  ← 零外部 import, 完全独立
```

**memory/ 模块独立性验证：**
- 对外 import: 零（不 import skills/nodes/任何上层模块）
- 新增 skill: 只需在 schema.py 加 `{DOMAIN}_MEMORY` 声明，memory 代码零改动

### Phase 4E: 旧模块迁移 ✅

**改动：**
- `episodic_memory.py` → 薄代理（log/query/seed/clear 委托 MemoryManager）
- `user_profile.py` → 薄代理（save/get preference 委托 MemoryManager）
- `memory/_instance.py` → 全局单例 + reset_memory()（测试注入点）
- `intent.py` → `_get_memory_instance()` 取单例，不再每次 MemoryManager()
- 上层调用方（response.py / pipeline.py / context_enrich.py）零改动

### 架构差距分析

| 层 | 模块 | 现状 | 差距 |
|----|------|------|------|
| NLU | 意图识别 | ✅ 三层漏斗 | — |
| NLU | 槽位抽取 | ✅ LLM+harness | — |
| NLU | 对话行为(DA) | ❌ 缺 confirm/deny/correction | 🔴 Phase 5 |
| DST | Belief State | ✅ DialogueState (Phase 4B) | — |
| DST | Slot Carry-Over | ✅ active_frames | — |
| DST | Confirmed Facts | ✅ 黑板栈 | — |
| DPL | Action 选择 | ⚠️ 缺 propose/explain/reroute | 🔴 Phase 4C |
| DPL | 主动策略 | ❌ 无 Proactive | 🔴 Phase 4D |
| DPL | Safety Guard | ✅ harness | — |
| NLG | 回复生成 | ⚠️ 纯拼接 | 🟡 Phase 6 |
| 记忆 | L1-L3 | ✅ MemoryManager (Phase 4A/4E) | — |
| 记忆 | 进化 | ❌ 无 async LLM | 🔴 Phase 4F |

### Phase 5: 对话行为识别 DA (~3h)

- DA 分类器: confirm/deny/correction/select
- 跟 Carry-Over 和歧义检测整合

### Phase 6: NLG + Error Recovery (~3h)

- NLG 润色层（基于 dialogue_state）
- 工具失败重试 + 槽位修复

### Demo 测试发现的 4 个问题

1. "太贵了" → LLM 没设 route_type=avoid_toll
2. "那就走国道" → LLM 丢 destination（黑板有但不利用）
3. avoid_highway 跟 fastest 差不多（300.9km/157元 vs 300.3km/165元）
4. 对话整体机械，没有记忆和主动性
