# Project1: 智能座舱 Agent (Cabin Agent)

基于 LangGraph 构建的车载语音助手 Agent，支持多意图并发调度、Skill 自动发现、黑板记忆、端侧快路径、行程记忆等特性。

## 功能

- **多意图识别与并发执行** — "开空调，顺便导航去天府广场" 自动拆解为两个子任务并发执行
- **三层推理漏斗** — FastRules(0ms) → 端侧 3B 模型(~1s) → 云端 LLM(~5s)，按需升级
- **Skill Registry 自动发现** — 新增 skill = 建目录写 4 文件，改 0 个已有文件
- **黑板栈式记忆** — 工具产出跨轮持久化，支持 "就去第二个" 等跨轮指代消解
- **Slot Carry-Over** — 缺槽位自动挂起，下轮补充后无缝恢复
- **行程记忆** — 自动归档导航/搜索/媒体事件，支持 "昨天去了哪里" 等时间回溯查询
- **端侧快路径** — 本地 3B INT4 模型 (LMDeploy)，简单意图 ~1s 直出
- **安全守卫** — 漂移检测 + 歧义检测 + 行程提取校验，不信任 LLM 自觉性
- **Gradio Demo** — 流式回复 + 会话隔离 + 车辆状态面板 + 快速测试按钮

## 支持的意图

| 域 | 意图 | 说明 | 示例 |
|----|------|------|------|
| climate | `ac_control` | 空调控制 | "开空调"、"调到22度" |
| climate | `window_control` | 车窗/天窗/车门 | "关车窗"、"打开天窗" |
| climate | `light_control` | 灯光控制 | "开灯"、"关氛围灯" |
| climate | `seat_control` | 座椅加热/通风 | "座椅加热2档" |
| map | `navigate` | 导航 | "导航去天府广场" |
| map | `search_poi` | 搜索周边 | "附近加油站"、"找火锅店" |
| map | `map_query` | 地图信息查询 | "现在在哪儿"、"前面堵不堵" |
| map | `weather` | 天气查询 | "今天天气怎么样" |
| media | `media_control` | 音乐/音量 | "放音乐"、"声音大一点" |
| vehicle | `query_vehicle_status` | 车况查询 | "还有多少油"、"胎压" |
| vehicle | `activate_scene` | 场景模式 | "舒适驾驶模式"、"休息模式" |
| — | `chitchat` | 闲聊 | "你好"、"讲个笑话" |

## 架构

```
用户输入
    ↓
message_compressor (滑动窗口压缩 >30 条历史)
    ↓
fast_rules (0ms 前置规则: OOS拒绝 / 高频短路 / 多意图放行)
    ↓ [未命中短路]
intent_classifier (五阶段流水线)
    ├── Stage 0: Slot Carry-Over (0ms)
    ├── Stage 1: 历史注入判断 (0ms)
    ├── Stage 1.5: 行程记忆检索 (0ms)
    ├── Stage 2a: 端侧快路径 (~1s, 可选)
    ├── Stage 2b: 云端 LLM (~5s)
    ├── Stage 3: 漂移检测 (0ms)
    └── Stage 4: 歧义检测 (0ms)
    ↓
wave_planner → Send fan-out 并发调度
    ↓
task_pipeline × N (context_enrich → harness校验 → 工具执行 → 高风险确认)
    ↓
session_update (黑板写入 + 行程归档)
    ↓
wave_aggregator (结果汇聚) → 最终回复
```

## 项目结构

```
p1-cabin-agent/
├── project1_cabin_agent/
│   ├── graph.py                  # LangGraph StateGraph 构建 + 条件路由
│   ├── state.py                  # CabinAgentState 定义 + reducer
│   ├── main.py                   # Gradio Demo 入口
│   ├── vehicle_state.py          # 车辆状态模拟
│   ├── edge_model.py             # 端侧 3B 两阶段推理
│   ├── edge_schemas.py           # 端侧输出白名单校验
│   ├── nodes/
│   │   ├── agent_nodes.py        # re-export 层
│   │   ├── constants.py          # Pydantic 模型 + 关键词常量
│   │   ├── pre_rules.py          # FastRules 前置规则
│   │   ├── intent.py             # 意图识别调度入口
│   │   ├── post_rules.py         # 后置守卫 (漂移/歧义/Carry-Over)
│   │   ├── context_enrich.py     # 上下文组装 (按 CONTEXT_DEPS 声明)
│   │   ├── pipeline.py           # 任务流水线 (skill path + legacy path)
│   │   ├── response.py           # 结果聚合 + 回复生成
│   │   ├── episodic_memory.py    # L1.5 行程记忆
│   │   ├── user_profile.py       # L2 用户偏好
│   │   ├── slot_transfer.py      # 黑板槽位回填
│   │   ├── schema.py             # 动态 Schema 生成
│   │   ├── intent_slots.py       # 槽位校验
│   │   ├── intent_compress.py    # 消息压缩
│   │   └── message_utils.py      # 消息工具函数
│   ├── skills/
│   │   ├── registry.py           # SkillRegistry 自动发现 + 统一接口
│   │   ├── climate/              # 气候域: ac/window/light/seat
│   │   │   ├── schema.py         # intent + slot 定义 (SSOT)
│   │   │   ├── tools.py          # 工具实现
│   │   │   ├── harness.py        # 校验 + 格式化
│   │   │   ├── examples.yaml     # few-shot 示例
│   │   │   └── SKILL.md          # 域知识文档
│   │   ├── map/                  # 地图域: navigate/search_poi/map_query/weather
│   │   │   ├── schema.py / tools.py / harness.py / examples.yaml
│   │   │   └── SKILL.md
│   │   ├── media/                # 媒体域: media_control
│   │   │   └── (同构 4 文件 + SKILL.md)
│   │   └── vehicle/              # 车辆域: query_status/activate_scene
│   │       └── (同构 4 文件 + SKILL.md)
│   ├── tools/
│   │   ├── cabin_tools.py        # 遗留工具集 (未迁移到 skill 的工具)
│   │   ├── mock_data.yaml
│   │   └── vehicle_mock_data.yaml
│   ├── data/                     # SQLite 数据 (events.db, user_profile.db)
│   └── tests/                    # 17 个测试文件 (132 eval 用例 + harness 单测)
├── shared/
│   ├── config/settings.py        # 全局配置
│   └── utils/                    # logger, llm_factory, metrics
├── scripts/                      # Demo 脚本
├── .env                          # 环境变量
├── AGENTS.md                     # AI agent 上下文
├── PROGRESS.md                   # 开发进度
└── README.md                     # 本文件
```

## 快速开始

```bash
# 1. 激活环境
conda activate llm

# 2. 配置 .env (LLM API key 等)

# 3. 启动 Demo
python -m project1_cabin_agent.main

# 4. (可选) 启用端侧模型
export EDGE_ENABLED=true
export EDGE_BASE_URL=http://localhost:8001/v1
```

## 运行测试

```bash
conda run -n llm python -m pytest project1_cabin_agent/tests/ -v
```

## 技术栈

- **框架:** LangGraph + LangChain
- **LLM:** 云端 (通过 llm_factory) + 端侧 Qwen2.5-3B-AWQ (LMDeploy)
- **UI:** Gradio (流式 + 车辆面板)
- **存储:** SQLite (checkpoint / 行程记忆 / 用户偏好)
- **状态管理:** LangGraph StateGraph + TypedDict + 自定义 reducer

## 许可

私有项目
