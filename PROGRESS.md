# P1 智能座舱 Agent — 项目进度

## Phase 1: Registry 自动发现 ✅

> 提交: d27d6c7 → f73d456 → e18b372
> eval 基线: 91.7%

- SkillRegistry 类自动发现 skills/ 下所有域
- edge_model 从 registry 动态加载 DOMAIN_INTENTS + examples
- pipeline/schema/post_rules/constants/edge_schemas 全部从 registry 动态生成
- SSOT 解决 10/16 处违规
- 4 skill: climate, media, vehicle, navigation（Phase2 前状态）

## Phase 2: 地图域重构 ✅

> 提交: 8595226 → 2757de4 → bd45856 → 62d8173

| 步骤 | 内容 | 提交 |
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

| 步骤 | 内容 | 改动文件 |
|------|------|---------|
| 3.1 | orchestrator/planner.py 执行计划数据结构 | 新建 |
| 3.2 | orchestrator/executor.py 逐步执行+条件判断 | 新建 |
| 3.3 | pipeline.py 加入 Layer 3 路由 | 1 文件 |
| 3.4 | eval 加条件编排测试用例 | 1 文件 |

## SSOT 审计进度 (16处违规)

| 状态 | 数量 | 说明 |
|------|------|------|
| ✅ 已解决 | 12 | Phase1 解决 10 处 + Phase2 解决 V16 |
| ⏳ 剩余 | 4 | V3(unknown域), V11(pre_rules硬编码), V14(_DOMAIN_SIGNALS), V17(mode→route_type) |
