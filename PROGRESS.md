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

## ⏭️ 下一步：Phase 3 编排层 (Layer 3 Plan-and-Execute)

> 覆盖复杂条件编排 ~5% 请求（如"先找加油站再导航过去"、"附近有便利店吗帮我调低温度"）

设计文档: /mnt/e/wiki/p1_skill_registry_地图域重构.md (第五节 Phase3)

|| 步骤 | 内容 | 改动文件 |
|------|------|---------|
| 3.1 | orchestrator/planner.py 执行计划数据结构 | 新建 |
| 3.2 | orchestrator/executor.py 逐步执行+条件判断 | 新建 |
| 3.3 | pipeline.py 加入 Layer 3 路由 | 1 文件 |
| 3.4 | eval 加条件编排测试用例 | 1 文件 |

## 当前状态总览

| 指标 | 数值 |
|------|------|
| skill 域 | 4 (climate, map, media, vehicle) |
| intent 总数 | 14 |
| harness 单测 | 103/103 全绿 |
| eval 132条 | 91.7% 零退化 |
| 纯逻辑测试 | 74 passed |
| 端侧 e2e | 122 passed, 2 failed (多意图) |
| SSOT 已解决 | 12/16，剩余 4 处 |

## SSOT 审计进度 (16处违规)

|| 状态 | 数量 | 说明 ||
|------|------|------|
| ✅ 已解决 | 12 | Phase1 解决 10 处 + Phase2 解决 V16 |
| ⏳ 剩余 | 4 | V3(unknown域), V11(pre_rules硬编码), V14(_DOMAIN_SIGNALS), V17(mode→route_type) |
