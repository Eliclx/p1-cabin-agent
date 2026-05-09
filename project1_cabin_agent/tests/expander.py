"""
project1_cabin_agent/tests/expander.py
训练数据扩写器 — 数据飞轮 Layer 3

从 seeds.jsonl 读取正确答案，用云端大模型生成口语变体，
输出标准 chat 格式训练数据 (Axolotl/TRL 直接可训)。

每条种子 → 20 条变体，保持 intent + slot 不变。

用法:
    python -m project1_cabin_agent.tests.expander
    python -m project1_cabin_agent.tests.expander --count 30  # 每条扩30条
"""

import json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.utils.llm_factory import get_llm
from langchain_core.messages import HumanMessage

SEEDS_PATH = Path(__file__).parent / "seeds.jsonl"
TRAIN_S1_PATH = Path(__file__).parent / "training_stage1.jsonl"
TRAIN_S2_PATH = Path(__file__).parent / "training_stage2.jsonl"

# ── Prompt 模板 ──

EXPAND_TEMPLATE = """你是车载语音助手训练数据生成器。

将下面这条用户输入扩写成 {count} 条**自然口语变体**，每条保持相同的意图和槽位值。

【原始输入】
{input}

【正确答案 - 必须保持不变】
领域: {domain}
意图: {intent}
槽位: {slots}

【要求】
1. 生成恰好 {count} 条变体
2. 改变表达方式：短/长/口语填充/客套/方言化
3. **槽位值严格不变**（如 temperature=26 始终是 26）
4. 输出纯 JSON 数组

【输出格式】
[
  {{"input": "调到26度", "domain": "{domain}", "intent": "{intent}", "slots": {slots_json}}},
  ...
]"""


def expand_single(seed: dict, count: int = 20) -> list[dict]:
    """用云端 LLM 扩写单条种子"""
    slots_json = json.dumps(seed.get("slots", {}), ensure_ascii=False)

    prompt = EXPAND_TEMPLATE.format(
        count=count,
        input=seed["input"],
        domain=seed["domain"],
        intent=seed.get("intent", "N/A"),
        slots=seed.get("slots", {}),
        slots_json=slots_json,
    )

    llm = get_llm("fast", temperature=0.8)
    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        text = resp.content.strip()

        # 提取 JSON 数组
        if "```" in text:
            text = text.split("```")[1]
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            data = json.loads(text[start:end + 1])
            # 过滤：只保留 slot 值未变且 intent 未变的
            valid = []
            for v in data:
                if v.get("intent") != seed.get("intent"):
                    continue  # intent 漂移了，丢弃
                # slot 值校验
                s = v.get("slots", {})
                ok = True
                for k, expected_val in seed.get("slots", {}).items():
                    if str(s.get(k, "")) != str(expected_val):
                        ok = False
                        break
                if ok:
                    valid.append(v)
            return valid[:count]
    except Exception as e:
        print(f"  ⚠️ 扩写失败: {e}")

    return []


def expand_all(count: int = 20) -> tuple[int, int]:
    """扩写所有种子 → 规则预筛 → Judge 评估 → 训练数据"""
    if not SEEDS_PATH.exists():
        print("❌ 无种子数据，先跑 error_collector + data_pipeline")
        return 0, 0

    seeds = []
    with open(SEEDS_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                seeds.append(json.loads(line))

    print(f"📋 {len(seeds)} 条种子，每条→{count}条变体\n")

    # ── Judge 初始化 + 校准 ──
    from project1_cabin_agent.tests.judge import Judge
    judge = Judge()
    use_judge = judge.calibrate()
    if not use_judge:
        print("⚠️ Judge 校准失败，降级：所有规则预筛通过的数据直接入库\n")

    s1_data = []
    s2_data = []
    total_judge_accepted = 0
    total_judge_low = 0
    total_judge_rejected = 0

    for i, seed in enumerate(seeds):
        inp = seed["input"]
        domain = seed["domain"]
        intent = seed.get("intent")
        slots = seed.get("slots", {})

        if not intent:
            continue

        print(f"[{i+1}/{len(seeds)}] \"{inp}\" → {domain}/{intent}")

        variants = expand_single(seed, count)
        if not variants:
            print(f"  ⚠️ 扩写为空，种子自身作为训练数据")
            variants = [{"input": inp, "domain": domain, "intent": intent, "slots": slots}]

        print(f"  → 规则预筛后 {len(variants)} 条")

        # ── Judge 评估 ──
        if use_judge and len(variants) > 1:
            eval_result = judge.evaluate(variants)
            final = eval_result["accepted"] + eval_result["low_confidence"]
            total_judge_accepted += len(eval_result["accepted"])
            total_judge_low += len(eval_result["low_confidence"])
            total_judge_rejected += len(eval_result["rejected"])
        else:
            final = variants

        for v in final:
            d = v.get("domain", domain)
            i_intent = v.get("intent", intent)
            i_slots = v.get("slots", slots)
            i_input = v["input"]

            s1_data.append({
                "messages": [
                    {"role": "system", "content": "你是车载语音助手领域分类模块。"},
                    {"role": "user",
                     "content": f"领域列表: climate(车内环境), navigation(导航), media(媒体), search(周边搜索), vehicle(车辆状态), chitchat(闲聊)。\n\n用户输入: {i_input}\n\n只输出一个领域名:"},
                    {"role": "assistant", "content": d},
                ]
            })

            s2_data.append({
                "messages": [
                    {"role": "system", "content": "你是车载语音助手意图+槽位提取模块。"},
                    {"role": "user",
                     "content": f"当前领域: {d}\n\n用户输入: {i_input}\n\n输出纯 JSON（无 markdown 包裹），包含 intent 和 slots:\n{{\"intent\": \"意图名\", \"slots\": {{\"槽位\": 值}}}}"},
                    {"role": "assistant",
                     "content": json.dumps({"intent": i_intent, "slots": i_slots}, ensure_ascii=False)},
                ]
            })

        time.sleep(0.5)

    with open(TRAIN_S1_PATH, "w", encoding="utf-8") as f:
        for d in s1_data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    with open(TRAIN_S2_PATH, "w", encoding="utf-8") as f:
        for d in s2_data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"\n{'='*50}")
    print(f"✅ 训练数据生成完成")
    if use_judge:
        print(f"  Judge: 接受={total_judge_accepted} 降级={total_judge_low} 丢弃={total_judge_rejected}")
    print(f"  Stage1: {len(s1_data)} 条 → {TRAIN_S1_PATH}")
    print(f"  Stage2: {len(s2_data)} 条 → {TRAIN_S2_PATH}")
    print(f"\n下一步: QLoRA 微调")
    return len(s1_data), len(s2_data)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=20)
    args = p.parse_args()
    expand_all(args.count)
