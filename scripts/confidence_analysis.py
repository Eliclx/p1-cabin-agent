"""
Phase F: 端侧 Confidence 分布分析

跑全量 132 条 eval cases，收集每条 confidence 分值，
按 domain/intent 分组，输出分布报告。

用法:
    cd ~/llm/projects/p1-cabin-agent
    conda activate llm
    EDGE_ENABLED=true python scripts/confidence_analysis.py
"""

import os
import sys
import json
import time
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["EDGE_ENABLED"] = "true"

from project1_cabin_agent.edge_model import edge_model_infer, EDGE_CONFIDENCE_THRESHOLD
from project1_cabin_agent.nodes.intent import _can_use_edge

# ── 从 eval_harness 导入全量用例 ──
from project1_cabin_agent.tests.eval_harness import (
    GOLDEN_SET,
    EXTENDED_SET,
    BOUNDARY_SET,
)

ALL_CASES = GOLDEN_SET + EXTENDED_SET + BOUNDARY_SET


def main():
    print("全量 Confidence 分布分析")
    print(f"总用例: {len(ALL_CASES)}")
    print(f"阈值: {EDGE_CONFIDENCE_THRESHOLD}")
    print("=" * 70)

    results = []
    by_domain = defaultdict(list)
    by_intent = defaultdict(list)

    for text, exp_domain, exp_intent in ALL_CASES:
        # needs_context / unknown: 端侧本就不该接，记录门控结果
        if exp_domain in ("needs_context", "unknown"):
            can_edge = _can_use_edge(text, [])
            results.append(
                {
                    "input": text,
                    "exp_domain": exp_domain,
                    "exp_intent": exp_intent,
                    "gate_pass": can_edge,
                    "edge_ran": False,
                    "note": f"期望不走端侧, 门控={'通过(误放)' if can_edge else '拦截(正确)'}",
                }
            )
            by_domain[exp_domain].append(
                {
                    "input": text,
                    "gate_pass": can_edge,
                    "confidence": None,
                }
            )
            continue

        # multi: 端侧不接多意图，记录门控结果
        if exp_domain == "multi":
            can_edge = _can_use_edge(text, [])
            results.append(
                {
                    "input": text,
                    "exp_domain": exp_domain,
                    "exp_intent": exp_intent,
                    "gate_pass": can_edge,
                    "edge_ran": False,
                    "note": f"多意图, 门控={'通过(误放)' if can_edge else '拦截(正确)'}",
                }
            )
            by_domain[exp_domain].append(
                {
                    "input": text,
                    "gate_pass": can_edge,
                    "confidence": None,
                }
            )
            continue

        # chitchat: 没有具体 intent 要求，记录端侧结果
        if exp_domain == "chitchat":
            can_edge = _can_use_edge(text, [])
            if not can_edge:
                results.append(
                    {
                        "input": text,
                        "exp_domain": exp_domain,
                        "exp_intent": None,
                        "gate_pass": False,
                        "edge_ran": False,
                        "note": "门控拦截",
                    }
                )
                by_domain[exp_domain].append(
                    {
                        "input": text,
                        "gate_pass": False,
                        "confidence": None,
                    }
                )
                continue

        # 走端侧推理
        can_edge = _can_use_edge(text, [])
        if not can_edge:
            results.append(
                {
                    "input": text,
                    "exp_domain": exp_domain,
                    "exp_intent": exp_intent,
                    "gate_pass": False,
                    "edge_ran": False,
                    "note": "门控拦截(误拦)",
                }
            )
            by_domain[exp_domain].append(
                {
                    "input": text,
                    "gate_pass": False,
                    "confidence": None,
                }
            )
            continue

        r = edge_model_infer(text)

        domain_ok = r.domain == exp_domain
        intent_ok = (exp_intent is None) or (r.intent == exp_intent)

        entry = {
            "input": text,
            "exp_domain": exp_domain,
            "exp_intent": exp_intent,
            "gate_pass": True,
            "edge_ran": True,
            "actual_domain": r.domain,
            "actual_intent": r.intent,
            "confidence": r.confidence,
            "is_acceptable": r.is_acceptable,
            "domain_ok": domain_ok,
            "intent_ok": intent_ok,
            "latency_ms": round(r.latency_ms, 0),
            "slots": r.slots,
            "all_slots_filtered": r.all_slots_filtered,
            "error": r.error,
        }
        results.append(entry)

        by_domain[r.domain].append(
            {
                "input": text,
                "gate_pass": True,
                "confidence": r.confidence,
                "intent": r.intent,
                "intent_ok": intent_ok,
                "is_acceptable": r.is_acceptable,
            }
        )
        by_intent[r.intent].append(
            {
                "input": text,
                "confidence": r.confidence,
                "is_acceptable": r.is_acceptable,
                "intent_ok": intent_ok,
            }
        )

        tag = "✅" if intent_ok and r.is_acceptable else "❌"
        print(
            f"  {tag} [{r.confidence:.2f}] '{text}' → {r.domain}/{r.intent} (期望 {exp_domain}/{exp_intent or '-'}) acc={r.is_acceptable} lat={r.latency_ms:.0f}ms"
        )

    # ── 输出统计报告 ──
    print("\n" + "=" * 70)
    print("按 DOMAIN 分组统计")
    print("=" * 70)

    for domain in [
        "climate",
        "map",
        "media",
        "vehicle",
        "chitchat",
        "needs_context",
        "unknown",
        "multi",
    ]:
        items = by_domain.get(domain, [])
        if not items:
            continue

        gate_blocked = [i for i in items if not i["gate_pass"]]
        edge_items = [
            i for i in items if i["gate_pass"] and i.get("confidence") is not None
        ]
        confidences = [i["confidence"] for i in edge_items]

        print(f"\n--- {domain} (总 {len(items)} 条) ---")
        print(f"  门控拦截: {len(gate_blocked)} 条")
        if not confidences:
            print("  无端侧数据")
            continue

        print(f"  端侧推理: {len(edge_items)} 条")
        print(
            f"  Confidence: min={min(confidences):.2f}  max={max(confidences):.2f}  avg={sum(confidences) / len(confidences):.2f}"
        )
        acceptable_count = sum(1 for i in edge_items if i.get("is_acceptable"))
        print(
            f"  is_acceptable: {acceptable_count}/{len(edge_items)} ({acceptable_count / len(edge_items):.0%})"
        )
        intent_ok_count = sum(1 for i in edge_items if i.get("intent_ok", True))
        print(
            f"  intent准确: {intent_ok_count}/{len(edge_items)} ({intent_ok_count / len(edge_items):.0%})"
        )

        # confidence 分布桶
        bins = [(0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 0.95), (0.95, 1.01)]
        print("  分布:", end="")
        for lo, hi in bins:
            count = sum(1 for c in confidences if lo <= c < hi)
            label = f"[{lo:.1f},{hi:.2f})" if hi <= 1.0 else f"[{lo:.1f},1.0]"
            print(f" {label}={count}", end="")
        print()

    print("\n" + "=" * 70)
    print("按 INTENT 分组统计")
    print("=" * 70)

    for intent in sorted(by_intent.keys()):
        items = by_intent[intent]
        confidences = [i["confidence"] for i in items]
        acceptable = sum(1 for i in items if i.get("is_acceptable"))
        intent_ok = sum(1 for i in items if i.get("intent_ok", True))

        print(
            f"  {intent:25s} n={len(items):2d}  conf_avg={sum(confidences) / len(confidences):.2f}  "
            f"acceptable={acceptable}/{len(items)}  intent_ok={intent_ok}/{len(items)}  "
            f"conf_range=[{min(confidences):.2f},{max(confidences):.2f}]"
        )

    # ── 关键指标 ──
    print("\n" + "=" * 70)
    print("关键发现")
    print("=" * 70)

    edge_results = [r for r in results if r.get("edge_ran")]
    all_confs = [r["confidence"] for r in edge_results]
    acceptables = [r for r in edge_results if r["is_acceptable"]]
    rejected = [r for r in edge_results if not r["is_acceptable"]]

    print(f"\n端侧实际推理: {len(edge_results)} 条")
    print(
        f"  confidence avg={sum(all_confs) / len(all_confs):.2f}  min={min(all_confs):.2f}  max={max(all_confs):.2f}"
    )
    print(
        f"  is_acceptable=True:  {len(acceptables)}/{len(edge_results)} ({len(acceptables) / len(edge_results):.0%})"
    )
    print(
        f"  is_acceptable=False: {len(rejected)}/{len(edge_results)} ({len(rejected) / len(edge_results):.0%})"
    )

    # 低 confidence 但 intent 正确的 case（被误拒）
    false_reject = [r for r in rejected if r.get("intent_ok")]
    if false_reject:
        print(f"\n⚠️  intent正确但被confidence拒绝 ({len(false_reject)} 条):")
        for r in false_reject:
            print(
                f"    conf={r['confidence']:.2f} '{r['input']}' → {r['actual_domain']}/{r['actual_intent']}"
            )

    # 高 confidence 但 intent 错误的 case（被误放）
    false_accept = [r for r in acceptables if not r.get("intent_ok")]
    if false_accept:
        print(f"\n⚠️  intent错误但被confidence放过 ({len(false_accept)} 条):")
        for r in false_accept:
            print(
                f"    conf={r['confidence']:.2f} '{r['input']}' → {r['actual_domain']}/{r['actual_intent']} (期望 {r['exp_domain']}/{r['exp_intent'] or '-'})"
            )

    # 保存 JSON
    out_path = (
        Path(__file__).parent.parent
        / "project1_cabin_agent"
        / "tests"
        / "confidence_report.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "threshold": EDGE_CONFIDENCE_THRESHOLD,
                "total_cases": len(ALL_CASES),
                "edge_ran": len(edge_results),
                "avg_confidence": round(sum(all_confs) / len(all_confs), 3),
                "accept_rate": round(len(acceptables) / len(edge_results), 3),
                "by_domain": {
                    k: {
                        "count": len(v),
                        "confidences": [
                            i["confidence"]
                            for i in v
                            if i.get("confidence") is not None
                        ],
                    }
                    for k, v in by_domain.items()
                },
                "by_intent": {
                    k: {
                        "count": len(v),
                        "confidences": [i["confidence"] for i in v],
                    }
                    for k, v in by_intent.items()
                },
                "details": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n报告已保存: {out_path}")


if __name__ == "__main__":
    main()
