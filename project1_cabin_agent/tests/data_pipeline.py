"""
project1_cabin_agent/tests/data_pipeline.py
三层数据管道: errors → seeds → training_data

Layer 1: errors.jsonl    — 错误记录（含 actual_*，用于分析）+ error_id 可追溯
Layer 2: seeds.jsonl     — 种子数据（仅正确答案，可喂 project2）
Layer 3: training_*.jsonl — 标准 chat 格式训练数据（Axolotl/TRL 兼容）
"""

import json
import uuid
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parents[1]))

from project1_cabin_agent.edge_schemas import INTENT_SCHEMAS, get_allowed_slot_keys

# ── 路径 ──
ERRORS_PATH = ROOT / "errors.jsonl"
SEEDS_PATH = ROOT / "seeds.jsonl"
TRAIN_S1_PATH = ROOT / "training_stage1.jsonl"
TRAIN_S2_PATH = ROOT / "training_stage2.jsonl"

# ── Layer 1: 错误格式 ──

ERROR_SCHEMA = {
    "error_id":     "uuid",        # 唯一 ID，串联三层
    "input":        "空调多少度",
    "domain":       "vehicle",     # 正确答案（即 expected）
    "intent":       "query_vehicle_status",
    "slots":        {"items": "ac_temp"},
    "actual_domain": "climate",    # 实际输出
    "actual_intent": "ac_control",
    "actual_slots": {"temperature": 20},
    "error_stage":  "stage2",      # stage1: domain错 / stage2: intent/slot错
    "error_type":   "intent_confusion",
    "layer":        "edge",        # fast_rule / edge / cloud
    "latency_ms":   200.0,
}


# ── Layer 2: seeds.jsonl — 正确答案，可追溯 ──

def errors_to_seeds() -> list[dict]:
    """errors.jsonl → seeds.jsonl，只保留正确答案 + schema 校验"""
    if not ERRORS_PATH.exists():
        print(f"⚠️ {ERRORS_PATH} 不存在")
        return []

    seeds = []
    warnings = 0
    with open(ERRORS_PATH, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            err = json.loads(line)
            domain = err["domain"]
            intent = err.get("intent")
            slots = err.get("slots", {})

            # ── Schema 校验：slot key 是否在当前 schema 中 ──
            allowed = get_allowed_slot_keys(domain, intent) if intent else set()
            unknown_keys = set(slots.keys()) - allowed
            if unknown_keys:
                print(f"⚠️ [{err.get('error_id','?')[:8]}] slot key 不在 schema 中: {unknown_keys}")
                print(f"   domain={domain} intent={intent} allowed={allowed}")
                print(f"   可能工具已变更，需更新种子。当前跳过未知 key。")
                slots = {k: v for k, v in slots.items() if k in allowed}
                warnings += 1

            seed = {
                "seed_id":  err.get("error_id", str(uuid.uuid4())),
                "input":    err["input"],
                "domain":   domain,
                "intent":   intent,
                "slots":    slots,
                "error_stage": err.get("error_stage", "stage2"),
                "error_type":  err.get("error_type", ""),
            }
            seeds.append(seed)

    with open(SEEDS_PATH, "w", encoding="utf-8") as f:
        for s in seeds:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"Layer2: {len(seeds)} 条种子 → {SEEDS_PATH}")
    if warnings:
        print(f"  ⚠️ {warnings} 条有 schema 不匹配（已自动跳过未知 key）")
    return seeds


# ── Layer 3: 标准 chat 格式训练数据 ──

STAGE1_PROMPT = """你是车载语音助手领域分类模块。

领域列表: climate(车内环境), navigation(导航), media(媒体), search(周边搜索), vehicle(车辆状态), chitchat(闲聊), multi(多意图), unknown(未知)

用户输入: {input}

只输出一个领域名:"""

STAGE2_PROMPT = """你是车载语音助手意图+槽位提取模块。

当前领域: {domain}

用户输入: {input}

输出纯 JSON（无 markdown 包裹），包含 intent 和 slots:
{{"intent": "意图名", "slots": {{"槽位": 值}}}}"""


def seeds_to_training(seeds: list[dict] = None) -> tuple[int, int]:
    """seeds.jsonl → training_stage1.jsonl + training_stage2.jsonl"""
    if seeds is None:
        if not SEEDS_PATH.exists():
            print("先跑 errors_to_seeds()")
            return 0, 0
        seeds = []
        with open(SEEDS_PATH, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    seeds.append(json.loads(line))

    s1_data = []
    s2_data = []

    for seed in seeds:
        # Stage1: input → domain
        s1_data.append({
            "messages": [
                {"role": "system", "content": "你是车载语音助手领域分类模块。"},
                {"role": "user", "content": STAGE1_PROMPT.format(input=seed["input"])},
                {"role": "assistant", "content": seed["domain"]},
            ]
        })

        # Stage2: input + domain → intent + slots（仅当有 intent 时）
        if seed.get("intent"):
            output = json.dumps({
                "intent": seed["intent"],
                "slots": seed["slots"],
            }, ensure_ascii=False)

            s2_data.append({
                "messages": [
                    {"role": "system", "content": "你是车载语音助手意图+槽位提取模块。"},
                    {"role": "user", "content": STAGE2_PROMPT.format(
                        domain=seed["domain"], input=seed["input"])},
                    {"role": "assistant", "content": output},
                ]
            })

    with open(TRAIN_S1_PATH, "w", encoding="utf-8") as f:
        for d in s1_data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    with open(TRAIN_S2_PATH, "w", encoding="utf-8") as f:
        for d in s2_data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"Layer3: Stage1={len(s1_data)} 条 → {TRAIN_S1_PATH}")
    print(f"Layer3: Stage2={len(s2_data)} 条 → {TRAIN_S2_PATH}")
    return len(s1_data), len(s2_data)


# ── 一键 Pipeline ──

def run_pipeline(expand: bool = False, expand_count: int = 20):
    """errors → seeds → training（一键）"""
    print("═" * 50)
    print("数据管道: errors → seeds → training")
    print("═" * 50)

    seeds = errors_to_seeds()
    if not seeds:
        return

    if expand:
        from project1_cabin_agent.tests.expander import expand_all
        expand_all(expand_count)
    else:
        seeds_to_training(seeds)
        print(f"\n种子: {len(seeds)} 条")
        print("下一步: python -m project1_cabin_agent.tests.expander 扩写训练数据")


if __name__ == "__main__":
    run_pipeline()
