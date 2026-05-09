# Project1 智能座舱 Agent 学习指南

> 一份快速上手文档，帮你10分钟内理解整个项目的架构、数据流和核心设计。

---

## 一、项目是什么

一个**车载语音助手**，基于 LangGraph 状态机编排。用户说"导航去天府广场"、"开空调"、"附近有加油站吗"，系统识别意图、调用工具、返回语音回复。

核心能力：多意图并发处理、槽位缺失追问、跨轮指代消解、高风险操作确认、闲聊兜底。

---

## 二、一张图看懂数据流

```
用户输入 "查附近加油站，顺便开空调"
         │
         ▼
  ┌─────────────────┐
  │ message_compressor│  ← 消息>30条时压缩旧消息为摘要
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │   fast_rules     │  ← 纯规则层(0ms)，~40%请求直接短路
  │   ┌ OOS拒绝      │     "点外卖"→no_support
  │   ├ 高频意图短路   │     "开空调"→直接生成sub_task，跳过LLM
  │   └ 追问防误杀    │     "还有多久"→放行不短路
  └────────┬────────┘
     命中?─┼─未命中→intent_classifier(LLM ~300ms)
           │
           ▼
  ┌─────────────────┐
  │ intent_classifier │  ← LLM意图识别，4个Stage：
  │   Stage0: Carry-Over│   "天府广场"→填入上轮pending的导航帧(0ms)
  │   Stage1: 历史注入  │   有指代词/短输入→注入对话历史
  │   Stage2: LLM识别   │   调LLM生成sub_tasks JSON
  │   Stage3: 后置检测  │   漂移检测+歧义拦截(纯规则0ms)
  └────────┬────────┘
           ▼
     ┌─────┴─────┐
     │闲聊?→chitchat_handler→END
     │非闲聊↓
     ▼
  ┌─────────────────┐
  │  wave_planner    │  ← 空节点(仅作路由挂载点)
  └────────┬────────┘
           ▼ route_wave()
  ┌─────────────────────────────────────┐
  │  Send fan-out 并发执行               │
  │  task_0(search_poi) ─┐              │
  │  task_1(ac_control) ─┤ 并发投递       │
  │                      ▼              │
  │              ┌──────────────┐       │
  │              │ task_pipeline │×N     │
  │              │  槽位校验→interrupt  │
  │              │  →工具执行→确认     │
  │              └──────┬───────┘       │
  │                     ▼              │
  │              ┌──────────────┐       │
  │              │session_update│       │
  │              │ 写入黑板(L1) │       │
  │              └──────┬───────┘       │
  │                     ▼              │
  │              ┌──────────────┐       │
  │              │wave_aggregator│      │
  │              │ 汇聚并发结果   │      │
  │              └──────┬───────┘       │
  └─────────────────────┼──────────────┘
                        ▼ route_after_aggregate()
              ┌─────────┴─────────┐
              │还有未完成?→wave_planner(下一波)
              │依赖链?→response_gen→END
              │全部完成→END
```

---

## 三、核心概念详解

### 3.1 State — 全局状态 (`state.py`)

`CabinAgentState` 是 TypedDict，贯穿整个图。关键字段：

| 字段 | 类型 | 作用 | 生命周期 |
|------|------|------|---------|
| `messages` | `Annotated[list, add_messages]` | 对话历史，reducer自动累加 | 跨轮保留(checkpoint) |
| `sub_tasks` | `List[dict]` | 本轮拆解的子任务 | 仅本轮(每轮重建) |
| `task_results` | `Annotated[List[dict], add_list_with_reset]` | 工具执行结果 | 仅本轮(intent_classifier返回None重置) |
| `completed_task_ids` | `Annotated[List[str], add_list_with_reset]` | 已完成的任务ID | 仅本轮 |
| `dialogue_context` | `Annotated[Dict, merge_dict]` | L1黑板(栈式存储) | 跨轮保留(不重置) |
| `active_frames` | `List[dict]` | 未完成的意图帧(Carry-Over) | 跨轮保留 |
| `current_task` | `Optional[dict]` | Send注入的单任务 | 局部(Send注入) |

**关键 reducer 设计：**

- `add_messages`: LangGraph内置，累加消息 + 支持 RemoveMessage 删除
- `add_list_with_reset`: intent_classifier 返回 None → 重置为[]；task_pipeline 返回 [{...}] → 累加
- `merge_dict`: 栈式合并，同key不覆盖而是压栈。黑板实体按标签栈式存储

### 3.2 波次调度 (Wave Scheduling) (`graph.py`)

核心设计：**多意图按依赖拓扑分波并发执行**。

```
用户: "查天气然后推荐活动，顺便开空调"
sub_tasks = [
  t1(查天气, depends=[]),
  t2(推荐活动, depends=[t1]),
  t3(开空调, depends=[])
]
第1波 ready = [t1, t3] → Send并发
第2波 ready = [t2]     → t1完成后才就绪
```

`route_wave()` 筛选逻辑：
1. task_id 不在 completed 中（避免重复执行）
2. depends_on 列表中所有依赖都在 completed 中（前置全部完成）
3. depends_on=[] 的任务天然就绪

`route_after_aggregate()` 判断：
- 还有未完成 → 回到 wave_planner
- 全部完成 → END 或 response_gen(依赖链聚合)
- 死锁保护：检测是否有任务能被执行，不能则强制终止

### 3.3 三层漏斗意图识别

```
L0  FastRules    (0ms, ~40% 短路)    ← fast_rules.py
L1  云端 LLM     (~300ms, ~60%)      ← intent.py Stage2
L2  端侧模型     (可选, 省token)      ← 未集成，project4在用
```

**FastRules (`fast_rules.py`)**:
- 18条短路规则，纯模式匹配/正则提取
- 覆盖：空调开关/调温、车窗开关、媒体播放/暂停/切歌/音量、座椅加热、灯光开关、车辆状态查询、场景联动、OOS拒绝
- 命中后直接生成 sub_task，跳过 LLM，0ms
- 有 pending 帧时不短路（让 Carry-Over 先处理）

**intent_classifier (`intent.py`)**:
- Stage 0: Slot Carry-Over（0ms）— 短输入填入上轮 pending 帧
- Stage 1: 历史注入判断（0ms）— 三层漏斗决定是否注入历史
- Stage 2: LLM 识别（~300ms）— 调 LLM 生成 sub_tasks JSON
- Stage 3: 后置漂移检测（0ms）— 纯规则，检查 slot 值是否从历史"偷"来的
- Stage 4: 歧义检测（0ms）— 三条硬规则拦截 LLM 瞎猜

### 3.4 task_pipeline — 单任务处理 (`pipeline.py`)

每个 Send 投递的并发任务走这里：

```
槽位缺失? → interrupt(追问用户) → 恢复后提取slot → 再缺则追问 → 超限强制执行
    ↓ 槽位齐了
工具路由 → TOOL_REGISTRY查表
    ↓
工具执行 → asyncio.wait_for(timeout=8s)
    ↓
高风险? → interrupt(确认) → 恢复后 _is_cancel_answer / _detect_redirect
    ↓ 确认执行
_execute_confirmed → TOOL_REGISTRY[confirmed_execute]
    ↓
返回 result → session_update → wave_aggregator
```

两个 interrupt 点：
1. **槽位缺失追问**：缺失 required_slots → interrupt 等用户补充
2. **高风险确认**：window_control 的 risk_level=high → interrupt 等用户确认

恢复后检测（两个 interrupt 点共用 `_handle_resume`）：
- 取消？→ 两层漏斗（规则关键词 + LLM语义判断）
- 新意图？→ `_detect_redirect`（规则映射 + LLM兜底）→ Command(goto="wave_planner")

### 3.5 黑板机制 (`slot_transfer.py` + `response.py`)

**黑板 = 跨轮结构化记忆**，存在 `dialogue_context` 字段，栈式存储。

```
search_poi 产出 → 写入黑板 entity.poi 栈
start_navigation 消费 → 从 entity.poi 栈顶取值 → 回填 destination slot

例：
第1轮: "附近加油站" → search_poi → entity.poi: [{round:1, data:{results:[壳牌(0.8km),中石化(1.5km)]}}]
第2轮: "就去第二个" → start_navigation → slot_transfer 从 entity.poi 取 results[1].name = "中石化"
```

`BLACKBOARD_DECLS` 声明：
- `produces`: 产出什么实体标签（写入）
- `consumes`: 消费什么实体标签（读取）
- `slots`: 参数名到字段名的映射（如 destination ← name）

`session_update` 节点负责写入，`route_wave` 在投递前负责回填。

### 3.6 工具三层架构 (`cabin_tools.py`)

```
Layer 1: 原子函数 (_set_ac_state, _set_window_state...)
         不暴露给LLM，直接操作 vehicle_state

Layer 2: 领域工具 (@tool ac_control, window_control...)
         暴露给LLM，docstring含参数说明/示例/反例/隐式映射/风险等级
         9个工具：ac_control, window_control, seat_control, media_control,
                  light_control, search_poi, start_navigation,
                  query_vehicle_status, activate_scene

Layer 3: 场景联动 (activate_scene)
         编排多个Layer1原子函数，一键触发
```

`TOOL_REGISTRY`: 注册表，每个工具的 function + description + blackboard 声明
`INTENT_TO_TOOL`: 意图名到工具名的映射（当前 intent名=工具名）

### 3.7 Schema 自动发现 (`schema.py`)

从工具的 docstring 自动解析出：
- 参数列表（required/optional）
- 示例、反例、隐式映射
- 风险等级

生成 `DYNAMIC_SCHEMA` 供 intent_classifier 使用，`PROMPT_TOOLS_TEXT` 注入到 LLM prompt。

**新增工具时**：只需要在 cabin_tools.py 写好 @tool 和 docstring，schema.py 自动发现，不用改其他地方。

---

## 四、文件索引

```
project1_cabin_agent/
├── main.py              # 入口 + Gradio Demo（流式 + 会话隔离）
├── graph.py             # LangGraph 状态图构建 + 条件路由
├── state.py             # 全局状态定义 + reducer
├── vehicle_state.py     # 车辆状态模拟器
├── nodes/
│   ├── intent.py        # 消息压缩 + 意图识别 + Carry-Over + 漂移检测
│   ├── pipeline.py      # 单任务流水线（槽位追问 + 工具执行 + interrupt）
│   ├── response.py      # session_update + wave_aggregator + response_gen + chitchat
│   ├── fast_rules.py    # FastRules 规则层（18条短路规则）
│   ├── slot_transfer.py # 黑板槽位回填
│   ├── schema.py        # Schema 自动发现引擎
│   ├── models.py        # Pydantic 数据模型
│   ├── user_profile.py  # L2 长期记忆（用户画像，SQLite持久化）
│   └── message_utils.py # 消息处理工具函数
├── tools/
│   └── cabin_tools.py   # 9个工具 + 注册表 + 黑板声明
├── tests/
│   ├── test_corner_cases.py  # 45个测试
│   └── test_b1_direct_answer.py
└── data/
    ├── checkpoints.db        # SQLite checkpoint持久化
    └── user_profile.db       # L2用户画像
```

---

## 五、面试高频问题 & 回答要点

### Q1: 为什么用 LangGraph 而不是纯 LangChain Agent？

> 纯 LangChain Agent 是单链式 ReAct 循环，一次只能处理一个工具调用。车载场景用户经常说"查附近加油站顺便开空调"这种多意图，LangGraph 的 Send fan-out 可以并发执行多个独立任务，波次调度处理依赖链。另外 LangGraph 的 interrupt 机制原生支持槽位追问和高风险确认，不需要自己维护状态机。

### Q2: FastRules 的设计原则是什么？

> 输出是否完全由输入唯一确定，不需语义理解？是→规则层，否→模型层。"开空调"→开空调，纯模式匹配。"有点冷"→需要理解"冷→制热+升温"，交给LLM。这样可以省掉约40%的LLM调用，延迟从300ms降到0ms。

### Q3: 黑板机制解决了什么问题？

> 跨轮指代消解。"就去第二个"这种输入，需要知道"第二个"是谁。黑板栈式存储工具产出的结构化实体，消费者工具按标签取值。关键是分离了"存"和"用"——search_poi 只管存 entity.poi，start_navigation 从 entity.poi 取值时还支持 sort_by/pick 排序选取。

### Q4: interrupt 恢复后怎么处理用户改主意？

> 两层检测：_handle_resume 先判取消（规则关键词+LLM），再判新意图（_detect_redirect，规则映射+LLM）。如果检测到新意图，返回 Command(goto="wave_planner") 直接重定向，不走原流程。这样"算了帮我开灯"不会走到开窗确认。

### Q5: 歧义检测为什么用 post-hoc 而不是让 LLM 自己判断？

> LLM 对短输入的意图分配不可信。用户说"打开"，LLM 可能猜 ac_control 或 window_control，都会带一个置信度但都不高。post-hoc 硬规则（短输入+无对象词+required缺失→强制 clarify）不信任 LLM 的自觉性，0ms 成本兜底。这是"规则层不信任模型层"的设计哲学。

---

## 六、如何运行

```bash
# 1. 进入项目目录
cd ~/llm/projects/cabin-ai-agent

# 2. 激活环境（Python 3.12）
conda activate llm

# 3. 配置 .env
cp .env.example .env
# 填入 DASHSCOPE_API_KEY（通义千问）或 OPENAI_API_KEY

# 4. 启动 Gradio Demo
python project1_cabin_agent/main.py
# 访问 http://localhost:7860

# 5. 跑测试
pytest project1_cabin_agent/tests/ -v
```

---

## 七、扩展方向（Phase 4）

| 方向 | 说明 |
|------|------|
| pending_selection 三层漏斗 | 引擎匹配→LLM兜底→澄清反问 |
| L2 用户画像完善 | 偏好+实体库，跨session持久化 |
| 条件执行 | "如果油量不足才去加油站" |
| 事件驱动 | 天气变化→自动开窗 |
| Carry-Over 降级 | 从主力降为兜底，LLM为主 |

---

*生成时间: 2026-05-05 | 基于 project1 完整源码（Phase 3 完成，73个测试全绿）*
