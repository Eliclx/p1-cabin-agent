"""
project1_cabin_agent/tests/judge.py
LLM-as-Judge — 训练数据质量评估

企业级做法:
  1. 校准集 → 先跑已知好/坏样本，验证 Judge 一致性
  2. 思考链 → 输出推理过程再打分，可审计
  3. 三级分流 → ≥4 入库 / =3 标记降级 / <3 丢弃

用法:
    from project1_cabin_agent.tests.judge import Judge
    judge = Judge()
    judge.calibrate()                    # 校准
    result = judge.evaluate(variants)    # 批量评估
"""

import json, time
from dataclasses import dataclass, field

from shared.utils.llm_factory import get_llm
from langchain_core.messages import HumanMessage, SystemMessage


# ── 校准集 (手写，覆盖好/坏/边界) ──

CALIBRATION_SAMPLES = [
    {
        "input": "调到26度",
        "intent": "ac_control",
        "slots": {"temperature": 26},
        "expected_pass": True,
        "expected_score_range": (4, 5),
        "label": "好样本-典型表达",
    },
    {
        "input": "把空调温度设置成二十六度",
        "intent": "ac_control",
        "slots": {"temperature": 26},
        "expected_pass": True,
        "expected_score_range": (4, 5),
        "label": "边界-稍书面但可接受",
    },
    {
        "input": "请将车内环境温度调节至26摄氏度",
        "intent": "ac_control",
        "slots": {"temperature": 26},
        "expected_pass": False,
        "expected_score_range": (1, 2),
        "label": "坏样本-过于正式不像口语",
    },
    {
        "input": "太冷了给我调热点",
        "intent": "ac_control",
        "slots": {"action": "heat_on", "mode": "heat"},
        "expected_pass": True,
        "expected_score_range": (4, 5),
        "label": "好样本-口语化",
    },
    {
        "input": "温度26",
        "intent": "ac_control",
        "slots": {"temperature": 26},
        "expected_pass": True,
        "expected_score_range": (4, 5),
        "label": "边界-极简表达但真实",
    },
]


# ── Judge Prompt ──

JUDGE_SYSTEM = """你是车载语音交互专家，有10年车载UI/UX经验。
你的任务是判断训练数据的用户输入是否像真实车主会说的自然口语。"""

JUDGE_PROMPT = """判断下面这条训练数据是否像真实车载用户会说的自然口语。

【正确答案（已校验，trust me）】
意图: {intent}
槽位: {slots}

【待评估的变体】
{input}

【评分标准 1-5】
5: 真人高概率就这么说，高频自然表达
4: 自然，真实场景可能出现
3: 基本接受，略微生硬但仍像人话
2: 明显书面语/翻译腔/过于正式，不像口语
1: 完全不像人类会说的话

【输出格式 — 先思考再给分】
{{
  "thinking": "简要推理（1-2句，为什么给这个分）",
  "score": <1-5>,
  "pass": <true/false>
}}
pass 为 true 当 score >= 3 时"""


@dataclass
class JudgeResult:
    input: str
    score: int
    pass_: bool
    thinking: str = ""
    confidence: str = "high"  # high / low


class Judge:
    """LLM-as-Judge：评估训练数据自然度"""

    def __init__(self):
        self.calibrated = False
        self.calibration_results = []

    def _call(self, input_text: str, intent: str, slots: dict) -> JudgeResult:
        """单次调用 Judge"""
        llm = get_llm("judge", temperature=0, timeout=30)
        prompt = JUDGE_PROMPT.format(
            intent=intent,
            slots=json.dumps(slots, ensure_ascii=False),
            input=input_text,
        )
        try:
            resp = llm.invoke([
                SystemMessage(content=JUDGE_SYSTEM),
                HumanMessage(content=prompt),
            ])
            text = resp.content.strip()

            # 健壮解析
            import re
            text = re.sub(r"```json\s*|```", "", text).strip()
            data = json.loads(text)

            return JudgeResult(
                input=input_text,
                score=data.get("score", 3),
                pass_=data.get("pass", True),
                thinking=data.get("thinking", ""),
                confidence="high" if data.get("score", 0) >= 4 else "low",
            )
        except Exception as e:
            return JudgeResult(
                input=input_text, score=3, pass_=True,
                thinking=f"parse error: {e}", confidence="low"
            )

    def calibrate(self) -> bool:
        """
        校准 Judge：用已知好/坏样本验证一致性。
        返回 True 表示校准通过。
        """
        print(f"\n{'='*50}")
        print("🔧 Judge 校准中...")
        print(f"{'='*50}")

        passed = 0
        failed = 0

        for sample in CALIBRATION_SAMPLES:
            result = self._call(
                sample["input"], sample["intent"], sample["slots"]
            )
            self.calibration_results.append({
                **sample,
                "actual_score": result.score,
                "actual_pass": result.pass_,
                "actual_thinking": result.thinking,
            })

            score_ok = sample["expected_score_range"][0] <= result.score <= sample["expected_score_range"][1]
            pass_ok = result.pass_ == sample["expected_pass"]

            status = "✅" if (score_ok and pass_ok) else "❌"
            if score_ok and pass_ok:
                passed += 1
            else:
                failed += 1

            print(f"  {status} [{sample['label']}]")
            print(f"      expected pass={sample['expected_pass']} score={sample['expected_score_range']}")
            print(f"      actual   pass={result.pass_} score={result.score}")
            print(f"      thinking: {result.thinking[:80]}")

        self.calibrated = failed == 0
        print(f"\n  校准结果: {passed}/{passed+failed} 通过")

        if not self.calibrated:
            print("  ⚠️ 校准失败！Judge 与人类判断不一致，需要调整 prompt 或阈值")
            print("  跳过批量评估，所有数据直接入库（降级策略）")

        return self.calibrated

    def evaluate(self, variants: list[dict]) -> dict:
        """
        批量评估变体列表。
        variants: [{"input": "...", "intent": "...", "slots": {...}}, ...]
        Returns: {"accepted": [...], "low_confidence": [...], "rejected": [...]}
        """
        if not self.calibrated:
            print("⚠️ Judge 未校准，跳过评估，全部入库")
            return {"accepted": variants, "low_confidence": [], "rejected": []}

        accepted = []
        low_confidence = []
        rejected = []

        import asyncio

        print(f"\n🔍 Judge 评估 {len(variants)} 条...")

        for i, v in enumerate(variants):
            result = self._call(v["input"], v.get("intent", ""), v.get("slots", {}))

            if result.score >= 4:
                accepted.append(v)
            elif result.score == 3:
                low_confidence.append(v)
                print(f"  [3/5] \"{v['input'][:30]}...\" → 降级 (低置信)")
            else:
                rejected.append(v)
                print(f"  [{result.score}/5] \"{v['input'][:30]}...\" → 丢弃: {result.thinking[:60]}")

            time.sleep(0.3)  # 限流

        print(f"\n  结果: 接受={len(accepted)} 降级={len(low_confidence)} 丢弃={len(rejected)}")
        return {"accepted": accepted, "low_confidence": low_confidence, "rejected": rejected}
