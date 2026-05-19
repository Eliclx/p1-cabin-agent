"""
project1_cabin_agent/tests/bench_stage2.py
三组对比 benchmark：评估精确率、JSON格式失败率、token数、延迟

用法:
    conda run -n llm python project1_cabin_agent/tests/bench_stage2.py
"""

import os, sys, json, time, re, urllib.request
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("EDGE_ENABLED", "true")
os.environ.setdefault("LANGSMITH_TRACING", "false")

from project1_cabin_agent.edge_model import (
    _build_stage1_system, _build_stage2_system, _call_llm,
    EDGE_BASE_URL, EDGE_MODEL, _classify_domain, _parse_edge_json,
    STAGE2_SYSTEM_TEMPLATE, _DOMAIN_EXAMPLES,
)
from project1_cabin_agent.edge_schemas import build_json_schema
from project1_cabin_agent.nodes.pre_rules import fast_rules_check

# ── 从 eval_harness 导入测试集 ──
from project1_cabin_agent.tests.eval_harness import GOLDEN_SET, EXTENDED_SET, BOUNDARY_SET

ALL_CASES = GOLDEN_SET + EXTENDED_SET + BOUNDARY_SET


# ═══════════════════════════════════════════════════
# 三种 Stage2 实现方式
# ═══════════════════════════════════════════════════

def stage2_current(user_input: str, domain: str) -> dict:
    """当前方式：带 guided generation (json_schema FSM)"""
    system_prompt = _build_stage2_system(domain)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    json_schema = build_json_schema(domain)
    result = _call_llm(messages, max_tokens=60, response_format=json_schema)
    raw = result["raw_text"]
    latency = result["latency_ms"]
    parsed = _parse_edge_json(raw)
    return {
        "raw": raw,
        "parsed": parsed,
        "latency_ms": latency,
        "parse_ok": parsed is not None,
        "method": "guided_gen",
    }


def stage2_no_fsm(user_input: str, domain: str) -> dict:
    """Q2：去掉 guided generation，纯 prompt 约束"""
    system_prompt = _build_stage2_system(domain)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    result = _call_llm(messages, max_tokens=60)
    raw = result["raw_text"]
    latency = result["latency_ms"]
    parsed = _parse_edge_json(raw)
    return {
        "raw": raw,
        "parsed": parsed,
        "latency_ms": latency,
        "parse_ok": parsed is not None,
        "method": "no_fsm",
    }


# ── Q3：紧凑格式 ──

COMPACT_SYSTEM_TEMPLATE = """你是车载语音助手的语义解析器。
用户输入属于 {domain} 领域。请提取意图和槽位。

输出格式：intent|k1=v1|k2=v2
如果没有槽位，只输出 intent

{domain} 领域的意图和槽位定义：
{schema_block}

规则：
1. intent 必须从上面的列表中选
2. slot key 必须用上面定义的英文名
3. slot value 必须符合类型要求
4. 无法确定的槽位不要填
5. 只输出 intent|k1=v1 格式，不要其他文字

示例：
{compact_examples}"""


def _build_compact_system(domain: str) -> str:
    """构建紧凑格式的 system prompt"""
    # 复用原有的 schema block
    from project1_cabin_agent.edge_model import _build_schema_block
    schema_block = _build_schema_block(domain)

    # 把原有 JSON 示例转成紧凑格式
    examples_raw = _DOMAIN_EXAMPLES.get(domain, _DOMAIN_EXAMPLES["unknown"])
    compact_lines = []
    for line in examples_raw.strip().split("\n"):
        if not line.strip():
            continue
        # 原始格式: 输入：XXX\n输出：{"intent": "...", "slots": {...}}
        # 提取输入和输出部分
        m = re.match(r'输入[：:](.+?)输出[：:](.+)', line.strip())
        if m:
            inp = m.group(1).strip()
            json_str = m.group(2).strip()
            try:
                # 清理 {{ }} 转义
                clean = json_str.replace("{{", "{").replace("}}", "}")
                obj = json.loads(clean)
                intent = obj.get("intent", "")
                slots = obj.get("slots", {})
                if slots:
                    slot_parts = "|".join(f"{k}={v}" for k, v in slots.items())
                    compact_lines.append(f"输入：{inp}\n输出：{intent}|{slot_parts}")
                else:
                    compact_lines.append(f"输入：{inp}\n输出：{intent}")
            except json.JSONDecodeError:
                compact_lines.append(f"输入：{inp}\n输出：unknown")

    compact_examples = "\n".join(compact_lines) if compact_lines else "无示例"
    return COMPACT_SYSTEM_TEMPLATE.format(
        domain=domain,
        schema_block=schema_block,
        compact_examples=compact_examples,
    )


def parse_compact(raw: str) -> dict | None:
    """解析紧凑格式 intent|k1=v1|k2=v2"""
    raw = raw.strip()
    # 去掉可能的前缀文字
    m = re.search(r'(?:输出[：:]?\s*)?(\w+(?:_\w+)*)(?:\|(.*))?', raw)
    if not m:
        return None
    intent = m.group(1)
    slots_str = m.group(2) or ""
    slots = {}
    if slots_str:
        for part in slots_str.split("|"):
            if "=" in part:
                k, v = part.split("=", 1)
                # 尝试转数字
                v = v.strip()
                try:
                    v = int(v)
                except ValueError:
                    try:
                        v = float(v)
                    except ValueError:
                        pass
                slots[k.strip()] = v
    return {"intent": intent, "slots": slots}


def stage2_compact(user_input: str, domain: str) -> dict:
    """Q2+Q3：去掉 FSM + 紧凑输出格式"""
    system_prompt = _build_compact_system(domain)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    result = _call_llm(messages, max_tokens=30)  # 紧凑格式不需要 60 tokens
    raw = result["raw_text"]
    latency = result["latency_ms"]
    parsed = parse_compact(raw)
    return {
        "raw": raw,
        "parsed": parsed,
        "latency_ms": latency,
        "parse_ok": parsed is not None,
        "method": "compact",
    }


# ═══════════════════════════════════════════════════
# 跑 benchmark
# ═══════════════════════════════════════════════════

def run_benchmark(stage2_fn, label: str) -> dict:
    """跑完整测试集，只测端侧路径（跳过 fast_rule 命中的）"""
    total = 0
    correct = 0
    parse_fail = 0
    latencies = []
    errors = []

    for text, exp_domain, exp_intent in ALL_CASES:
        # 跳过非标准测试（multi/needs_context/unknown）
        if exp_domain in ("multi", "needs_context", "unknown"):
            continue
        if exp_intent is None:
            continue

        total += 1

        # 先走 Stage1 拿 domain
        domain, _ = _classify_domain(text)

        # Stage2
        result = stage2_fn(text, domain)
        latencies.append(result["latency_ms"])

        if not result["parse_ok"]:
            parse_fail += 1
            errors.append({
                "input": text,
                "exp": f"{exp_domain}/{exp_intent}",
                "domain": domain,
                "raw": result["raw"][:80],
                "error": "parse_fail",
            })
            continue

        parsed = result["parsed"]
        got_intent = parsed.get("intent", "") if parsed else ""

        if got_intent == exp_intent:
            correct += 1
        else:
            errors.append({
                "input": text,
                "exp": f"{exp_domain}/{exp_intent}",
                "domain": domain,
                "got_intent": got_intent,
                "raw": result["raw"][:80],
                "error": "intent_wrong",
            })

    return {
        "label": label,
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0,
        "parse_fail": parse_fail,
        "parse_fail_rate": parse_fail / total if total else 0,
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
        "p50_latency_ms": sorted(latencies)[len(latencies)//2] if latencies else 0,
        "errors": errors,
        "timestamp": datetime.now().isoformat(),
    }


def measure_tokens(stage2_fn, domain: str, user_input: str) -> dict:
    """测单次请求的 token 数和延迟分解"""
    if stage2_fn == stage2_current:
        system_prompt = _build_stage2_system(domain)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]
        schema = build_json_schema(domain)
        payload = json.dumps({
            "model": EDGE_MODEL,
            "messages": messages,
            "max_tokens": 60,
            "temperature": 0.01,
            "response_format": schema,
        }).encode()
    elif stage2_fn == stage2_no_fsm:
        system_prompt = _build_stage2_system(domain)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]
        payload = json.dumps({
            "model": EDGE_MODEL,
            "messages": messages,
            "max_tokens": 60,
            "temperature": 0.01,
        }).encode()
    else:  # compact
        system_prompt = _build_compact_system(domain)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]
        payload = json.dumps({
            "model": EDGE_MODEL,
            "messages": messages,
            "max_tokens": 30,
            "temperature": 0.01,
        }).encode()

    url = f"{EDGE_BASE_URL}/chat/completions"
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=payload, headers=headers)
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    lat = (time.monotonic() - t0) * 1000

    usage = data.get("usage", {})
    return {
        "prompt_tokens": usage.get("prompt_tokens", "?"),
        "completion_tokens": usage.get("completion_tokens", "?"),
        "latency_ms": lat,
        "output": data["choices"][0]["message"]["content"][:60],
    }


if __name__ == "__main__":
    print("=" * 60)
    print("Stage2 三组对比 Benchmark")
    print(f"测试集: {len(ALL_CASES)} 条 (跳过 multi/needs_context/unknown/None intent)")
    print("=" * 60)

    # 预热
    print("\n预热中...")
    for _ in range(3):
        _classify_domain("预热测试")
        stage2_current("开空调", "climate")
        stage2_no_fsm("开空调", "climate")
        stage2_compact("开空调", "climate")

    # ── Token 数对比 ──
    print("\n" + "=" * 60)
    print("1. Token 数对比（climate 域 '开空调'）")
    print("=" * 60)

    for fn, label in [
        (stage2_current, "当前 (guided gen)"),
        (stage2_no_fsm, "Q2 (无 FSM)"),
        (stage2_compact, "Q2+Q3 (紧凑格式)"),
    ]:
        r = measure_tokens(fn, "climate", "开空调")
        print(f"\n  [{label}]")
        print(f"    prompt_tokens:    {r['prompt_tokens']}")
        print(f"    completion_tokens: {r['completion_tokens']}")
        print(f"    latency:           {r['latency_ms']:.0f}ms")
        print(f"    output:            {r['output']}")

    # 多测几个 domain
    print("\n  --- 各 domain 对比 ---")
    test_inputs = [
        ("climate", "关窗"),
        ("search", "附近有没有加油站"),
        ("navigation", "导航去天府广场"),
        ("media", "播放周杰伦"),
        ("vehicle", "还有多少油"),
    ]
    for domain, text in test_inputs:
        print(f"\n  [{domain}] '{text}'")
        for fn, label in [
            (stage2_current, "guided"),
            (stage2_no_fsm, "no_fsm"),
            (stage2_compact, "compact"),
        ]:
            r = measure_tokens(fn, domain, text)
            print(f"    {label:10s}: completion={r['completion_tokens']:>2}  latency={r['latency_ms']:>5.0f}ms  output={r['output'][:40]}")

    # ── 准确率对比 ──
    print("\n" + "=" * 60)
    print("2. 准确率 + 格式失败率对比（完整测试集）")
    print("=" * 60)

    results = {}
    for fn, label in [
        (stage2_current, "当前 (guided gen)"),
        (stage2_no_fsm, "Q2 (无 FSM)"),
        (stage2_compact, "Q2+Q3 (紧凑格式)"),
    ]:
        print(f"\n  跑 {label} ...")
        r = run_benchmark(fn, label)
        results[label] = r
        print(f"    准确率:     {r['accuracy']:.1%} ({r['correct']}/{r['total']})")
        print(f"    格式失败:   {r['parse_fail']} ({r['parse_fail_rate']:.1%})")
        print(f"    平均延迟:   {r['avg_latency_ms']:.0f}ms")
        print(f"    P50延迟:    {r['p50_latency_ms']:.0f}ms")

    # ── 汇总 ──
    print("\n" + "=" * 60)
    print("3. 汇总")
    print("=" * 60)
    print(f"{'方法':<22s} {'准确率':>8s} {'格式失败':>8s} {'平均延迟':>10s} {'P50延迟':>10s}")
    print("-" * 60)
    for label, r in results.items():
        print(f"{label:<22s} {r['accuracy']:>7.1%} {r['parse_fail_rate']:>7.1%} {r['avg_latency_ms']:>8.0f}ms {r['p50_latency_ms']:>8.0f}ms")

    # ── 错误详情 ──
    print("\n" + "=" * 60)
    print("4. 错误详情")
    print("=" * 60)
    for label, r in results.items():
        if r["errors"]:
            print(f"\n  [{label}] 错误 ({len(r['errors'])} 条):")
            for e in r["errors"][:10]:
                if e["error"] == "parse_fail":
                    print(f"    [格式失败] {e['input']:20s} domain={e['domain']}  raw={e['raw']}")
                else:
                    print(f"    [意图错误] {e['input']:20s} exp={e['exp']}  got={e.get('got_intent','?')}")
        else:
            print(f"\n  [{label}] 无错误 ✅")

    # ── 保存结果 ──
    out_path = ROOT / "project1_cabin_agent" / "tests" / "bench_stage2_results.json"
    with open(out_path, "w") as f:
        # 不保存 errors 完整内容，只保存摘要
        summary = {}
        for label, r in results.items():
            summary[label] = {k: v for k, v in r.items() if k != "errors"}
            summary[label]["error_count"] = len(r["errors"])
            summary[label]["error_inputs"] = [e["input"] for e in r["errors"]]
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_path}")
