# LLM-as-Judge 使用文档

## 概述

`judge.py` 是 project1 数据飞轮的**训练数据质量门禁**，用强模型（配置为 `judge` 类型）评估扩写后的训练数据是否自然。

## 企业级设计

### 1. 校准集 (Calibration)

5 条手写样本（2好/2坏/1边界），Judge 先跑校准验证与人类判断的一致性。

| 校准通过 | 校准失败 |
|---------|---------|
| → 继续批量评估 | → 告警退出，全部入库（降级策略，宁可数据多也不能丢） |

**手写样本设计原则：**
- 覆盖好/坏/边界三类
- 覆盖不同表达风格（极简/口语化/书面化）
- 每类至少 1 条

### 2. 思考链 (Chain of Thought)

Judge 先输出 `thinking` 再给分，可审计：

```json
{
  "thinking": "表达很自然，'太冷了给我调热点'符合真实车主口语习惯",
  "score": 5,
  "pass": true
}
```

vs 直接出分：出问题不知道 Judge 为什么判错。

### 3. 三级分流

| 分数 | 处理 | 说明 |
|------|------|------|
| ≥4 | accepted | 高质量，直接入库 |
| =3 | low_confidence | 入库但标记降级，训练时可能降权 |
| <3 | rejected | 丢弃，不污染训练集 |

### 4. 规则预筛 (Judge 之前)

以下检查是确定性的，不用 LLM：

```python
# 0ms，规则层
if variant.intent != seed.intent:      → 丢弃（意图漂移）
if variant.slots != seed.slots:        → 丢弃（槽位篡改）
if variant.slot_keys != seed.slot_keys: → 丢弃（槽位幻觉）
```

Judge 只判规则做不到的事：**这是真人会说的话吗？**

## 使用方式

```python
from project1_cabin_agent.tests.judge import Judge

judge = Judge()
judge.calibrate()     # 先校准

variants = [...]      # expander 产出的变体列表
result = judge.evaluate(variants)

# result = {"accepted": [...], "low_confidence": [...], "rejected": [...]}
```

## Judge Prompt

```
你是车载语音交互专家。

判断训练数据是否像真实车主会说的自然口语。

【正确答案（已校验）】意图: ac_control  槽位: {"temperature": 26}
【待评估变体】把空调温度设置成二十六度

评分 1-5:
5: 真人高概率就这么说
4: 自然，真实场景可能出现
3: 基本接受，略微生硬
2: 书面语/翻译腔，不像口语
1: 完全不像人话

输出: {"thinking": "...", "score": 1-5, "pass": true/false}
pass=true 当 score>=3
```

## 校准样本

| 样本 | 类型 | 期望 score | 期望 pass |
|------|------|-----------|----------|
| "调到26度" | 典型 | 4-5 | true |
| "把空调温度设置成二十六度" | 边界 | 3-4 | true |
| "请将车内环境温度调节至26摄氏度" | 坏 | 1-2 | false |
| "太冷了给我调热点" | 口语 | 4-5 | true |
| "温度26" | 极简 | 4-5 | true |

## 与 project2 judge 的对比

| | project1 Judge | project2 Judge |
|------|---------------|---------------|
| 判什么 | 训练数据自然度 | 对话回复质量 |
| 维度 | 1 维 (naturalness) | 5 维 (instruction/accuracy/dialect/safety/conciseness) |
| 校准 | 5 条手写样本 | 无（依赖 prompt 工程） |
| 思考链 | ✅ | ❌ |
| 安全红线 | 意图一致性（规则层做） | safety < 4 直接拒绝 |

## 限制

1. **Judge 不是完美的。** 校准能保证 80% 一致性，但边界 case 仍需人工判断
2. **成本。** ~0.3s/条，120 条约 40s。每次飞轮扩写跑一次。
3. **校准集需要维护。** 发现 Judge 误判后更新校准集
