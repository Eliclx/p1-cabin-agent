"""Phase F: Logprob 验证脚本

对比短prompt（有区分度）跑30条case，收集intent token的logprob。
"""

import json
import os
import urllib

os.environ["EDGE_ENABLED"] = "true"

from project1_cabin_agent.edge_model import EDGE_MODEL, EDGE_BASE_URL  # noqa: E402

DOMAINS = {
    "climate": [
        "ac_control",
        "window_control",
        "light_control",
        "seat_control",
        "cabin_query",
    ],
    "map": ["navigate", "search_poi", "map_query", "weather"],
    "media": ["media_control"],
    "vehicle": ["query_vehicle_status"],
}

# 单 token intent 名（不需要 _suffix 拼接）
SINGLE_TOKEN_INTENTS = {"navigate", "chitchat", "unknown"}


def build_short_stage2(domain: str) -> str:
    intents = ", ".join(DOMAINS[domain])
    return (
        f'你是车载语义解析器。输出JSON格式：{{"intent": "意图名", "slots": {{"槽位名": 值}}}}\n'
        f"{domain}领域的意图：{intents}\n"
        "规则：只输出JSON，不要其他文字。"
    )


def call(text: str, domain: str) -> dict:
    system_prompt = build_short_stage2(domain)
    payload = json.dumps(
        {
            "model": EDGE_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.01,
            "max_tokens": 50,
            "logprobs": True,
            "top_logprobs": 5,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{EDGE_BASE_URL}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    content = data["choices"][0]["message"]["content"]
    lp_data = data["choices"][0].get("logprobs", {}).get("content", [])

    # 找 intent 名 token
    intent_lp = None
    intent_top = ""
    all_intents = set()
    for v in DOMAINS.values():
        all_intents.update(v)

    for i, lp in enumerate(lp_data):
        tok = lp["token"]
        prev_tok = lp_data[i - 1]["token"] if i > 0 else ""
        nxt_tok = lp_data[i + 1]["token"] if i + 1 < len(lp_data) else ""

        # 模式1: prefix + _suffix (如 ac + _control)
        if prev_tok in ('"', 'Ġ"') and nxt_tok.startswith("_"):
            intent_lp = lp["logprob"]
            top3 = lp.get("top_logprobs", [])[:3]
            intent_top = " ".join(f"{t['token']}({t['logprob']:.2f})" for t in top3)
            break

        # 模式2: 单 token intent (如 navigate)
        if prev_tok in ('"', 'Ġ"') and tok in SINGLE_TOKEN_INTENTS:
            intent_lp = lp["logprob"]
            top3 = lp.get("top_logprobs", [])[:3]
            intent_top = " ".join(f"{t['token']}({t['logprob']:.2f})" for t in top3)
            break

        # 模式3: search + _poi, map + _query
        if prev_tok in ('"', 'Ġ"') and nxt_tok.startswith("_"):
            intent_lp = lp["logprob"]
            top3 = lp.get("top_logprobs", [])[:3]
            intent_top = " ".join(f"{t['token']}({t['logprob']:.2f})" for t in top3)
            break

    # parse actual intent
    actual = "?"
    try:
        clean = content.replace("{{", "{").replace("}}", "}")
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
        parsed = json.loads(clean)
        actual = parsed.get("intent", "?")
    except Exception:
        if content.strip() == "{}":
            actual = "(空)"

    return {
        "content": content[:60],
        "intent_lp": round(intent_lp, 4) if intent_lp is not None else None,
        "intent_top": intent_top,
        "actual": actual,
    }


CASES = [
    # 标准
    ("调到26度", "climate", "ac_control", "✅标准"),
    ("关空调", "climate", "ac_control", "✅标准"),
    ("打开空调", "climate", "ac_control", "✅标准"),
    ("空调开到18度", "climate", "ac_control", "✅标准"),
    # 短词
    ("开窗", "climate", "window_control", "✅短词"),
    ("关灯", "climate", "light_control", "✅短词"),
    ("暂停", "media", "media_control", "✅短词"),
    ("下一首", "media", "media_control", "✅短词"),
    ("切歌", "media", "media_control", "✅短词"),
    # map/vehicle
    ("导航到天府广场", "map", "navigate", "✅标准"),
    ("去春熙路", "map", "navigate", "✅标准"),
    ("附近有没有川菜馆", "map", "search_poi", "✅标准"),
    ("还有多少油", "vehicle", "query_vehicle_status", "✅标准"),
    ("胎压怎么样", "vehicle", "query_vehicle_status", "✅标准"),
    # 极口语
    ("热成狗了", "climate", "ac_control", "⚠️极口语"),
    ("冻死我了", "climate", "ac_control", "⚠️极口语"),
    ("亮瞎了", "climate", "light_control", "⚠️极口语"),
    ("耳朵要聋了", "media", "media_control", "⚠️极口语"),
    ("吵死啦", "media", "media_control", "⚠️极口语"),
    ("饿得不行了", "map", "search_poi", "⚠️极口语"),
    ("想喝奶茶", "map", "search_poi", "⚠️极口语"),
    # ASR/口误
    ("帮我把空挑关掉", "climate", "ac_control", "⚠️ASR"),
    ("去到春熙路吧", "map", "navigate", "⚠️口语"),
    # 域边界/隐含
    ("挡风玻璃起雾了", "climate", "ac_control", "⚠️域边界"),
    ("打开暖风", "climate", "ac_control", "⚠️域边界"),
    ("后背好热", "climate", "seat_control", "⚠️隐含"),
    ("前面堵不堵", "map", "navigate", "⚠️隐含"),
    ("还剩多少公里", "map", "map_query", "⚠️边界"),
    ("打开座椅加热", "climate", "seat_control", "✅标准"),
    ("声音大一点", "media", "media_control", "✅标准"),
]

if __name__ == "__main__":
    header = f"{'输入':14s} | {'域':7s} | {'期望':18s} | {'int_lp':>7s} | {'实际':18s} | 对 | 备注"
    print(header)
    print("-" * len(header))

    for text, domain, exp, note in CASES:
        r = call(text, domain)
        ok = "✓" if r["actual"] == exp else "✗"
        ilp = f"{r['intent_lp']:.4f}" if r["intent_lp"] is not None else "N/A"
        print(
            f"{text:14s} | {domain:7s} | {exp:18s} | {ilp:>7s} | {r['actual']:18s} | {ok} | {note}"
        )
        if r["intent_top"]:
            print(f"{'':14s}   candidates: {r['intent_top']}")
