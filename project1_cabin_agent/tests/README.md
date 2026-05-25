# Project1 测试与数据飞轮

> 车载语音助手端侧 3B 模型的评估、训练数据生成、持续迭代闭环。

## 目录结构

```
tests/
├── README.md
│
│  训练数据生成（Schema 驱动）
├── synth_data.py              # 主生成器：模板×实体 → 全量训练数据
├── synth_stage1.jsonl         # 产物：domain 分类训练数据
├── synth_stage2.jsonl         # 产物：intent+slot 联合提取训练数据
│
│  数据飞轮（Error 驱动）
├── error_collector.py         # Step 1: 收集端侧错误 → errors.jsonl
├── data_pipeline.py           # Step 2: errors → seeds → training（3层管道）
├── expander.py                # Step 3: seeds → LLM扩写 + Judge过滤
├── judge.py                   # LLM-as-Judge 质量门禁
├── JUDGE.md                   # Judge 设计文档
├── errors.jsonl               # 错误记录（飞轮入口）
├── seeds.jsonl                # 种子数据（飞轮中间产物）
│
│  评估系统
├── eval_harness.py            # 跑测试套件 + 基线对比 + 退化告警
├── eval_baseline.json         # 上次评估基线
├── bench_stage2.py            # 端侧 Stage2 三组对比 benchmark
│
│  单元测试
├── test_corner_cases.py       # 边界用例（模糊输入、歧义、指代等）
├── test_b1_direct_answer.py   # B1 直接回答测试
├── test_clarify_interrupt.py  # 歧义追问 + 槽位中断 + 历史干扰压测
├── test_episodic_memory.py    # 行程记忆 CRUD + 时间检索
├── test_climate_harness.py    # climate harness 单测
├── test_media_harness.py      # media harness 单测
├── test_navigation_harness.py # navigation harness 单测
├── test_search_harness.py     # search harness 单测 (已合并到 map)
└── test_vehicle_harness.py    # vehicle harness 单测
```

---

## 快速开始

### 1. 生成训练数据（Schema 驱动，推荐）

零 LLM 成本，从 intent schema + 口语模板批量合成：

```bash
cd ~/llm/projects/p1-cabin-agent
conda activate llm

# 生成基础数据（~500条，含 hard negative）
python -m project1_cabin_agent.tests.synth_data

# LLM 口语化增强（每条基础数据扩写成 5 条口语变体）
python -m project1_cabin_agent.tests.synth_data --llm-enhance 5

# 不要 hard negative
python -m project1_cabin_agent.tests.synth_data --no-negatives
```

产物：`synth_stage1.jsonl` + `synth_stage2.jsonl`，Axolotl/TRL 兼容的 chat 格式，可直接拿去 QLoRA 微调。

数据分布：

| 领域 | 覆盖的 intent | 基础条数 |
|------|-------------|---------|
| climate | ac/window/seat/light | ~208 |
| map | navigate/search_poi/map_query/weather | ~108 |
| media | media_control | ~68 |
| vehicle | query_status/activate_scene | ~69 |
| chitchat | — | ~12 |
| hard_negatives | unknown/multi | ~13 |

---

### 2. 跑数据飞轮（Error 驱动）

从端侧模型的真实错误出发，针对性生成训练数据：

```bash
cd ~/llm/projects/p1-cabin-agent

# 确保端侧模型在线
curl -s http://localhost:8001/v1/models | head -c 100

# Step 1: 收集错误（端侧必须在线）
EDGE_ENABLED=true python -m project1_cabin_agent.tests.error_collector

# Step 2: 评估 + 收集错误 + 自动跑管道
python project1_cabin_agent/tests/eval_harness.py

# Step 3: LLM 扩写 + Judge 过滤（需要手动触发，消耗 token）
python -m project1_cabin_agent.tests.expander --count 20
```

飞轮链路：

```
eval_harness → errors.jsonl → data_pipeline → seeds.jsonl → expander → training_stage1/2.jsonl
                                                                       ↓ Judge 过滤
                                                                       ↓ QLoRA 微调 3B
```

---

### 3. 跑评估

```bash
# 完整评估（132 条，含 GOLDEN + EXTENDED + BOUNDARY）
python project1_cabin_agent/tests/eval_harness.py

# 快速评估（14 条，只跑核心用例）
python project1_cabin_agent/tests/eval_harness.py --quick

# 只看上次基线
python project1_cabin_agent/tests/eval_harness.py --compare
```

评估指标：准确率、fast_rule/edge/cloud 命中率、平均延迟、各领域分布、退化告警。

---

### 4. 跑单元测试

```bash
pytest project1_cabin_agent/tests/ -v
```

---

## 两条路径怎么选

| | Schema 驱动 | Error 驱动飞轮 |
|------|-----------|-------------|
| **目的** | 全量覆盖，训练基础能力 | 修补弱点，针对性提升 |
| **数据量** | ~500~2500 条 | ~50~200 条 |
| **LLM 成本** | 基础生成 0 成本 | expander + judge 消耗 token |
| **何时用** | 首次训练、大改 schema 后 | 每次评估发现新错误后 |
| **命令** | `synth_data.py` | `eval_harness.py` + `expander.py` |

**推荐策略**：Schema 驱动打底（首次训练） → Error 驱动补强（持续迭代）。两条路不冲突，训练数据可以合并。

---

## 输出格式

所有训练数据使用 Axolotl/TRL 兼容的 chat 格式：

```json
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

### Stage1: domain 分类

```
System: 你是车载语音助手领域分类模块。只输出一个领域名：climate, map, media, vehicle, chitchat, unknown。
User: 空调调到26度
Assistant: climate
```

### Stage2: intent + slot 联合提取

```
System: 你是车载语音助手意图+槽位提取模块。当前领域: climate。输出纯 JSON: {"intent": "意图名", "slots": {"槽位": 值}}
User: 空调调到26度
Assistant: {"intent": "ac_control", "slots": {"temperature": 26}}
```

**注意**：Stage2 的 system prompt 包含了 domain，训练和推理格式保持一致。

---

## LLM-as-Judge

用于训练数据质量过滤。Judge 先跑 5 条校准样本验证一致性，再对扩写后的变体做三级分流：

| 分数 | 处理 |
|------|------|
| ≥4 | 接受，直接入库 |
| =3 | 降级，入库但标记低置信 |
| <3 | 丢弃 |

详见 `JUDGE.md`。
