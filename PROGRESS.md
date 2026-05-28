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
| intent 总数 | 14 |
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
| 3.1 | 条件分支（condition 评估机制） | 🔧 进行中 |
| 3.2 | Recovery 容错 | 待做 |
| 3.3 | eval 加条件编排测试用例 | 待做 |

### Phase 3.1 条件分支设计

**核心问题：** "天气好就导航"、"有充电站才去" — 任务 B 是否执行取决于任务 A 的结果。

**三种校验方案：**

| 方案 | 做法 | 优缺点 |
|------|------|--------|
| A: harness 约束 | source task 的 harness 声明 condition_fields | SSOT 但校验需反向查找 source harness |
| B: 集中注册表 | registry.py 一份 CONDITION_FIELDS | 和 blackboard_decl 信息重复 |
| C: 运行时校验 | evaluate 时直接从 task_results 取实际数据 | 最简单，字段不存在则降级 |

**当前选择：方案 C 先实现看效果。**

**数据结构：**
```python
task = {
    "task_id": "task_1",
    "intent": "navigate",
    "depends_on": ["task_0"],
    "condition": {                    # 可选
        "logic": "AND",              # AND | OR
        "rules": [
            {"source": "task_0", "field": "count", "op": "gt", "value": 0}
        ],
        "fail_msg": "附近没有充电站"
    }
}
```

**支持的 op:** eq/neq/gt/gte/lt/lte/in/not_in/is_empty/is_not_empty

**执行流程：** route_wave 中 depends_on 满足后、调度前评估 condition → 通过加入 ready / 不通过标记 skipped

**改动文件：** intent.py（LLM 生成 condition）、graph.py（评估逻辑）、response.py（处理 skipped）、state.py（skipped_task_ids）

**测试样例：**
| 用户说法 | condition | 预期 |
|---------|-----------|------|
| 有充电站就导航 | count gt 0 | 有→导航 / 没→"附近没找到" |
| 天气好就导航 | weather_main not_in ["雨","雪"] | 晴→导航 / 雨→"天气不好" |
| 找附近有没有露营地 | 无 condition | 正常执行 |

## 当前状态总览

| 指标 | 数值 |
|------|------|
| skill 域 | 4 (climate, map, media, vehicle) |
| intent 总数 | 14 |
| harness 单测 | 104/104 全绿 |
| 多轮端到端 | 5/5 全绿（新增） |
| 全量测试 | 192/197 (97.5%)，5个预先存在失败 |
| eval 132条 | 91.7% 零退化 |
| SSOT 已解决 | 16/16 全部闭合 |
| pipeline.py | ~770行（从 ~1040行缩减） |
| cabin_tools.py | 已删除（-584行） |

## SSOT 审计进度 (16处违规) — 全部闭合 ✅

|| 状态 | 数量 | 说明 |
|------|------|------|
| ✅ 代码修复 | 12 | Phase1(10) + Phase2(V16) + PhaseE(V14) |
| ✅ won't-fix | 2 | V3(unknown域硬编码合理) + V11(短路规则有 _validate_rules 校验) |
| ✅ 间接解决 | 2 | V14(DOMAIN_SIGNALS→schema) + V17(mode→route_type 映射统一) |
