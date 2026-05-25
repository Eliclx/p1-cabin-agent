# AGENTS.md — Project1: 智能座舱 Agent

> AI agent（小洁宝 / Claude Code 等）读写本项目时，以此文件为入口。

## 项目概述

车载智能座舱 Agent，基于 LangGraph StateGraph 构建。支持多意图并发调度（Send fan-out）、黑板栈式记忆、Slot Carry-Over、端侧 3B 模型快路径、行程记忆等特性。

**一句话总结：** 用户语音输入 → FastRules 短路/端侧快路径/云端 LLM 意图识别 → Send 并发执行工具 → 聚合回复。

## 环境与运行

```bash
conda activate llm          # Python 3.12
python -m project1_cabin_agent.main   # 启动 Gradio Demo (端口 7860)
```

关键环境变量（`.env`）：
- `EDGE_ENABLED=true/false` — 端侧模型开关（默认 false）
- `EDGE_BASE_URL` — LMDeploy 端侧推理地址（默认 localhost:8001）
- LLM API key — 云端模型凭证

测试：
```bash
conda run -n llm python -m pytest project1_cabin_agent/tests/ -v
```

## 架构总览

```
message_compressor → fast_rules → [条件路由]
                                      │
                    ┌─────────────────┼──────────────────┐
                    │                 │                   │
              [命中短路]        intent_classifier    [命中短路]
              chitchat_handler        │             wave_planner
                    │          ┌──────┴──────┐           │
                   END    [全闲聊]      [非闲聊]    Send × N 并发
                    │     chitchat_handler  wave_planner   │
                    │          │               │     context_enrich
                    │         END       context_enrich     │
                    │                      │        task_pipeline
                    │               task_pipeline          │
                    │                      │        session_update
                    │               session_update          │
                    │                      │        wave_aggregator
                    │              wave_aggregator          │
                    │                      │        route_after_aggregate
                    │          route_after_aggregate       │
                    │           ↙      ↓      ↘    wave_planner / response_gen / END
                    │    wave_planner response_gen END
                    │                    │
                    │                   END
```

**图定义：** `project1_cabin_agent/graph.py` — `_build_graph()` + 条件路由函数。

## 意图识别五阶段流水线

在 `nodes/intent.py` 的 `intent_classifier` 节点内：

| Stage | 名称 | 耗时 | 位置 | 说明 |
|-------|------|------|------|------|
| 0 | Slot Carry-Over | 0ms | `post_rules._try_carry_over` | pending 帧+短输入命中 → 直接填槽，跳过 LLM |
| 1 | 历史注入判断 | 0ms | `post_rules._needs_context` | 判断是否需要注入对话历史 |
| 1.5 | 行程记忆检索 | 0ms | `episodic_memory` | 时间回溯词 → SQLite 检索历史事件 |
| 2a | 端侧快路径 | ~1s | `edge_model` | 3B AWQ 两阶段推理，conf ≥ 0.85 直出 |
| 2b | 云端 LLM | ~5s | `intent.py` 调 `get_llm("fast")` | 兜底，含漂移+歧义检测 |
| 3 | 后置漂移检测 | 0ms | `post_rules._detect_context_bleeding` | 防止无上下文时 LLM 被历史污染 |
| 4 | 歧义检测 | 0ms | `post_rules._detect_ambiguity` | 极短输入+工具意图 → 追问候选 |
| 4b | 行程提取校验 | 0ms | `post_rules.guard_episodic_extraction` | 验证 LLM 从行程数据提取的值是否真实存在 |

**前置层（fast_rules 节点）：** OOS 拒绝 → 多意图放行 → 高频意图短路（开空调/关窗等 ~40% 请求 0ms 处理）

## State 设计

**文件：** `project1_cabin_agent/state.py`

核心字段：

| 字段 | Reducer | 生命周期 | 说明 |
|------|---------|---------|------|
| `messages` | `add_messages` | 跨轮 | 对话历史，支持滑动窗口压缩 |
| `user_input` | 覆盖 | 仅本轮 | 用户原始输入 |
| `sub_tasks` | 覆盖 | 仅本轮 | intent_classifier 拆解的子任务列表 |
| `task_results` | `add_list_with_reset` | 仅本轮 | 工具执行结果，intent_classifier 返回 None 重置 |
| `completed_task_ids` | `add_list_with_reset` | 仅本轮 | 已完成任务 ID |
| `dialogue_context` | `merge_dict`（栈式） | 跨轮 | 黑板记忆，工具产出实体按标签栈式存储 |
| `active_frames` | 覆盖 | 跨轮 | 未完成的意图帧，用于 Slot Carry-Over |
| `episodic_context` | 覆盖 | 仅本轮 | 行程记忆检索结果 |
| `clarify_count` | 覆盖 | 跨轮 | 连续追问次数，>2 降级 chitchat，>3 强制执行 |

**Reducer 注意事项：**
- `add_list_with_reset`：None 重置为 []，非 None 累加
- `merge_dict`：同 key 追加成栈（新值在栈顶），不覆盖

## 文件职责速查

### 核心模块

| 文件 | 职责 |
|------|------|
| `graph.py` | StateGraph 构建、条件路由（route_after_fast_rules / route_after_intent / route_wave / route_after_aggregate） |
| `state.py` | CabinAgentState TypedDict + reducer（merge_dict / add_list_with_reset） |
| `main.py` | Gradio Demo 入口（流式 + 会话隔离 + interrupt 恢复 + 车辆面板） |

### nodes/ 目录

| 文件 | 职责 |
|------|------|
| `agent_nodes.py` | 向后兼容 re-export 层，graph.py 从这里 import 8 个节点函数 |
| `constants.py` | Pydantic 模型（SubTask / IntentOutput）+ 关键词常量（指代/歧义/漂移） |
| `pre_rules.py` | FastRules 前置规则层（OOS 拒绝 + 高频短路 + 多意图放行 + 追问防误杀） |
| `intent.py` | 意图识别调度入口，串联 Stage 0~4，含端侧门控 `_can_use_edge` |
| `post_rules.py` | 后置守卫（漂移检测 + 歧义检测 + Carry-Over + 历史注入判断 + 行程提取校验） |
| `pipeline.py` | task_pipeline 节点（槽位校验 → interrupt 追问 → 工具执行 → 高风险确认） |
| `context_enrich.py` | ContextEnrichmentNode — 按 CONTEXT_DEPS 声明组装 AgentContext，在 task_pipeline 之前运行，为 harness 准备上下文数据 |
| `response.py` | session_update（黑板写入）+ wave_aggregator（并发结果汇聚）+ response_gen（依赖链聚合）+ chitchat_handler |
| `episodic_memory.py` | L1.5 行程记忆（SQLite 事件日志 + 时间回溯检索 + 上下文注入） |
| `user_profile.py` | L2 用户偏好（SQLite kv 存储） |
| `slot_transfer.py` | 黑板槽位回填（消费者任务从黑板取值） |
| `schema.py` | 技能发现 + 动态 Schema 生成（DYNAMIC_SCHEMA / PROMPT_TOOLS_TEXT） |
| `intent_slots.py` | 槽位校验 + 降级结果工厂 |
| `intent_compress.py` | 消息压缩（滑动窗口 >30 条触发） |
| `message_utils.py` | 消息/历史/JSON 工具函数 |

### tools/

| 文件 | 职责 |
|------|------|
| `cabin_tools.py` | 三层架构工具集：原子函数 → @tool 领域工具 → 场景联动。含 TOOL_REGISTRY / INTENT_TO_TOOL 映射（未迁移到 Skill 的旧工具）+ 黑板声明（produces/consumes）+ mock 数据 |

### skills/ 目录

| 文件 | 职责 |
|------|------|
| `registry.py` | SkillRegistry 类 — 启动时扫描 skills/ 目录自动注册，提供 get_all_intents / get_intent_spec / get_skill_for_intent / get_tool / get_validator / get_schema_block 接口 |
| `climate/schema.py` | climate 技能 Schema 定义（intent + slots + 工具声明） |
| `climate/tools.py` | climate 领域 @tool 函数 |
| `climate/harness.py` | climate harness — 槽位填充 → 工具编排 → 结果格式化 |
| `climate/examples.yaml` | climate few-shot 示例 |
| `climate/SKILL.md` | climate 技能说明文档 |
| `map/schema.py` | map 技能 Schema 定义 |
| `map/tools.py` | map 领域 @tool 函数 |
| `map/harness.py` | map harness — 导航/搜索工具编排 |
| `map/examples.yaml` | map few-shot 示例 |
| `media/schema.py` | media 技能 Schema 定义 |
| `media/tools.py` | media 领域 @tool 函数 |
| `media/harness.py` | media harness — 音乐/视频工具编排 |
| `media/examples.yaml` | media few-shot 示例 |
| `media/SKILL.md` | media 技能说明文档 |
| `vehicle/schema.py` | vehicle 技能 Schema 定义 |
| `vehicle/tools.py` | vehicle 领域 @tool 函数 |
| `vehicle/harness.py` | vehicle harness — 车辆控制工具编排 |
| `vehicle/examples.yaml` | vehicle few-shot 示例 |
| `vehicle/SKILL.md` | vehicle 技能说明文档 |

### 端侧模型

| 文件 | 职责 |
|------|------|
| `edge_model.py` | 端侧两阶段推理（Stage1 domain 分类 → Stage2 intent+slot 提取），调 LMDeploy API |
| `edge_schemas.py` | 端侧输出白名单校验 |

### shared/

| 文件 | 职责 |
|------|------|
| `config/settings.py` | 全局配置 |
| `utils/llm_factory.py` | LLM 工厂（get_llm("fast"/"smart")） |
| `utils/logger.py` | 日志 |
| `utils/metrics.py` | 节点耗时追踪（@track_node） |

### tests/

| 文件 | 职责 |
|------|------|
| `test_corner_cases.py` | 边界用例（模糊输入、歧义、指代等） |
| `test_b1_direct_answer.py` | 直接回复场景（正向反馈不追问） |
| `test_episodic_memory.py` | 行程记忆 CRUD + 时间检索 |
| `test_clarify_interrupt.py` | 歧义追问 + 槽位中断 + 历史干扰压测 |
| `test_climate_harness.py` | climate harness 单测 |
| `test_media_harness.py` | media harness 单测 |
| `test_navigation_harness.py` | navigation harness 单测 |
| `test_search_harness.py` | search harness 单测（已合并到 map 但测试文件名保留） |
| `test_vehicle_harness.py` | vehicle harness 单测 |
| `bench_stage2.py` | 端侧 Stage2 三组对比 benchmark |
| `eval_harness.py` | 评估框架 |
| `error_collector.py` | 错误收集器 |
| `data_pipeline.py` / `synth_data.py` / `expander.py` / `judge.py` | 合成数据+评估流水线 |

## 开发约定

### 代码风格
- 中文注释为主，docstring 说明设计意图
- 节点函数用 `@track_node("name")` 装饰器追踪耗时
- 日志格式：`[节点名] 动作`，如 `[意图识别] ✅ 子任务数: 2`
- 数据写入用 `<-`，读出用 `->`，如 `[L2记忆] <- music_query`、`[slot_transfer] -> destination`

### 状态操作
- 节点返回 dict，只包含需要更新/重置的字段，不要返回不需要修改的字段
- `task_results` 和 `completed_task_ids` 在 intent_classifier 中必须返回 None 重置（每轮清空）
- 新增 state 字段必须在 `CabinAgentState` TypedDict 中声明，否则静默丢弃

### 工具注册
- 已迁移到 Skill 架构的 intent 走 `skills/registry.py` 自动发现，无需手动注册
- 未迁移的旧工具仍在 `cabin_tools.py` 中注册到 `TOOL_REGISTRY` 和 `INTENT_TO_TOOL`
- 需要黑板交互的工具声明 `blackboard: {produces: "entity.xxx", consumes: [...]}`
- 端侧意图映射在 `edge_model.py` 的 `DOMAIN_INTENTS` 中同步

### 测试
- 跑完测试必须展示终端原始输出，不替人总结"通过"
- 行程记忆测试可用 `seed_event()` 注入数据，`clear_events()` 清理，`set_current_time_fn()` mock 时间

### 路由规则
- 新增意图只需在 `skills/xxx/schema.py` 中定义，registry 自动发现
- 仍需同步的位置：`pre_rules.py`（短路规则，可选）→ `edge_model.py`（DOMAIN_INTENTS）
- `constants.py` 和顶层 `schema.py` 已被 Skill 架构取代，无需手动同步
- 条件路由函数在 `graph.py` 中定义，返回字符串节点名

### 关键陷阱
1. **TypedDict 未声明字段 → 静默丢弃** — 这是 LangGraph 的硬限制
2. **MemorySaver 用 msgpack 序列化** — 自定义类放不进去，用 dict
3. **add_messages reducer** — dict 自动转 Message 对象，用 `.type` 不用 `.role`
4. **端侧模型无上下文** — 始终做漂移检测（needs_ctx=False）
5. **depends_on 填 intent 名而非 task_id → 死锁** — graph.py 有 deadlock 保护

## 端侧模型版本历史

- v6: 两阶段 System+User + 动态 few-shot + chitchat 单一 intent
- v7: Stage1 domain 分类加入区分规则（车窗→climate 不是 vehicle 等）
- P0: is_acceptable + required_slots 检查，修了 8/13 个 flaky edge test
- P1: Stage2 prompt schema 注入 + few-shot 动态加载
- P2: 白名单全空时统一降级云端
- guided generation (json_schema) → 去掉（延迟降 57%）
- 端侧门控 `_can_use_edge`：多意图/指代/追问/极短模糊 → 放行云端
- 安全网：conf < 0.85 自动 fallback 云端

## 面试亮点

1. **Send fan-out 多意图并发** — 波次调度器，支持依赖链（查天气→推荐活动），deadlock 保护
2. **三层推理漏斗** — FastRules(0ms, ~40%) → 端侧 3B(~1s) → 云端 LLM(~5s)
3. **黑板栈式记忆** — 工具产出实体按标签栈式存储，消费者按标签取值，支持跨轮
4. **Slot Carry-Over** — 缺槽位挂起 pending 帧，下轮短输入直接填槽，0ms 跳过 LLM
5. **Post-hoc 守卫** — 漂移检测 + 歧义检测 + 行程提取校验，不信任 LLM 自觉性
6. **端云双模型** — 3B INT4 本地 + 云端大模型，置信度 fallback 安全网
7. **Interrupt 机制** — LangGraph interrupt 做追问，Command(resume) 恢复，支持取消+重定向
8. **行程记忆 L1.5** — 工具执行自动归档，时间回溯词触发检索，上下文注入
