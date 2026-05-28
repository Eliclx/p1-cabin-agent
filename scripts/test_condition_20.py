"""
手工跑 20 个条件分支测试，print 每个样例的输入和输出。
不依赖 pytest，直接 python 运行。
"""

import json
import sys

sys.path.insert(0, ".")

from project1_cabin_agent.nodes.condition import evaluate_condition


cases = [
    # ── 基础 op ──
    {
        "desc": "eq: weather_main=='晴', 实际='晴'",
        "condition": {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "weather_main", "op": "eq", "value": "晴"}
            ],
            "fail_msg": "天气不晴",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"weather_main": "晴"}}}],
        "expect": True,
    },
    {
        "desc": "eq: weather_main=='晴', 实际='多云'",
        "condition": {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "weather_main", "op": "eq", "value": "晴"}
            ],
            "fail_msg": "天气不晴",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"weather_main": "多云"}}}],
        "expect": False,
    },
    {
        "desc": "neq: status!='error', 实际='success'",
        "condition": {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "status", "op": "neq", "value": "error"}
            ],
            "fail_msg": "上游出错",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"status": "success"}}}],
        "expect": True,
    },
    {
        "desc": "neq: status!='error', 实际='error'",
        "condition": {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "status", "op": "neq", "value": "error"}
            ],
            "fail_msg": "上游出错",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"status": "error"}}}],
        "expect": False,
    },
    {
        "desc": "gt: count>0, 实际=5",
        "condition": {
            "logic": "AND",
            "rules": [{"source": "t0", "field": "count", "op": "gt", "value": 0}],
            "fail_msg": "没有结果",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"count": 5}}}],
        "expect": True,
    },
    {
        "desc": "gt: count>0, 实际=0 (边界)",
        "condition": {
            "logic": "AND",
            "rules": [{"source": "t0", "field": "count", "op": "gt", "value": 0}],
            "fail_msg": "没有结果",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"count": 0}}}],
        "expect": False,
    },
    {
        "desc": "gte: count>=0, 实际=0 (含等号)",
        "condition": {
            "logic": "AND",
            "rules": [{"source": "t0", "field": "count", "op": "gte", "value": 0}],
            "fail_msg": "没有结果",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"count": 0}}}],
        "expect": True,
    },
    {
        "desc": "lt: distance<10.0, 实际=3.5",
        "condition": {
            "logic": "AND",
            "rules": [{"source": "t0", "field": "distance", "op": "lt", "value": 10.0}],
            "fail_msg": "太远了",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"distance": 3.5}}}],
        "expect": True,
    },
    {
        "desc": "lte: distance<=10.0, 实际=10.0 (含等号)",
        "condition": {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "distance", "op": "lte", "value": 10.0}
            ],
            "fail_msg": "太远了",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"distance": 10.0}}}],
        "expect": True,
    },
    {
        "desc": "lte: distance<=10.0, 实际=10.1",
        "condition": {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "distance", "op": "lte", "value": 10.0}
            ],
            "fail_msg": "太远了",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"distance": 10.1}}}],
        "expect": False,
    },
    # ── in / not_in / is_empty / is_not_empty ──
    {
        "desc": "in: weather in [晴,多云], 实际='晴'",
        "condition": {
            "logic": "AND",
            "rules": [
                {
                    "source": "t0",
                    "field": "weather_main",
                    "op": "in",
                    "value": ["晴", "多云"],
                }
            ],
            "fail_msg": "天气不好",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"weather_main": "晴"}}}],
        "expect": True,
    },
    {
        "desc": "in: weather in [晴,多云], 实际='暴雨'",
        "condition": {
            "logic": "AND",
            "rules": [
                {
                    "source": "t0",
                    "field": "weather_main",
                    "op": "in",
                    "value": ["晴", "多云"],
                }
            ],
            "fail_msg": "天气不好",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"weather_main": "暴雨"}}}],
        "expect": False,
    },
    {
        "desc": "not_in: weather not_in [雨,雪,冰雹], 实际='阴'",
        "condition": {
            "logic": "AND",
            "rules": [
                {
                    "source": "t0",
                    "field": "weather_main",
                    "op": "not_in",
                    "value": ["雨", "雪", "冰雹"],
                }
            ],
            "fail_msg": "恶劣天气",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"weather_main": "阴"}}}],
        "expect": True,
    },
    {
        "desc": "not_in: weather not_in [雨,雪,冰雹], 实际='冰雹'",
        "condition": {
            "logic": "AND",
            "rules": [
                {
                    "source": "t0",
                    "field": "weather_main",
                    "op": "not_in",
                    "value": ["雨", "雪", "冰雹"],
                }
            ],
            "fail_msg": "恶劣天气",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"weather_main": "冰雹"}}}],
        "expect": False,
    },
    {
        "desc": "is_empty: results=[], 实际=[]",
        "condition": {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "results", "op": "is_empty", "value": None}
            ],
            "fail_msg": "有结果",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"results": []}}}],
        "expect": True,
    },
    {
        "desc": "is_not_empty: results非空, 实际=[a,b]",
        "condition": {
            "logic": "AND",
            "rules": [
                {
                    "source": "t0",
                    "field": "results",
                    "op": "is_not_empty",
                    "value": None,
                }
            ],
            "fail_msg": "没找到",
        },
        "data": [{"task_id": "t0", "tool_result": {"data": {"results": ["a", "b"]}}}],
        "expect": True,
    },
    # ── AND / OR 组合 ──
    {
        "desc": "AND: count>0 ✓ AND distance<5 ✓ → 全过",
        "condition": {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "count", "op": "gt", "value": 0},
                {"source": "t0", "field": "distance", "op": "lt", "value": 5.0},
            ],
            "fail_msg": "没有附近的结果",
        },
        "data": [
            {"task_id": "t0", "tool_result": {"data": {"count": 3, "distance": 1.2}}}
        ],
        "expect": True,
    },
    {
        "desc": "AND: count>0 ✓ AND distance<5 ✗(8.0) → 不通过",
        "condition": {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "count", "op": "gt", "value": 0},
                {"source": "t0", "field": "distance", "op": "lt", "value": 5.0},
            ],
            "fail_msg": "没有附近的结果",
        },
        "data": [
            {"task_id": "t0", "tool_result": {"data": {"count": 3, "distance": 8.0}}}
        ],
        "expect": False,
    },
    {
        "desc": "OR: count>10 ✗ OR has_parking=true ✓ → 通过",
        "condition": {
            "logic": "OR",
            "rules": [
                {"source": "t0", "field": "count", "op": "gt", "value": 10},
                {"source": "t0", "field": "has_parking", "op": "eq", "value": True},
            ],
            "fail_msg": "没有停车场",
        },
        "data": [
            {
                "task_id": "t0",
                "tool_result": {"data": {"count": 2, "has_parking": True}},
            }
        ],
        "expect": True,
    },
    {
        "desc": "OR: count>10 ✗ OR rating>=4.5 ✗(3.8) → 不通过",
        "condition": {
            "logic": "OR",
            "rules": [
                {"source": "t0", "field": "count", "op": "gt", "value": 10},
                {"source": "t0", "field": "rating", "op": "gte", "value": 4.5},
            ],
            "fail_msg": "不满足条件",
        },
        "data": [
            {"task_id": "t0", "tool_result": {"data": {"count": 2, "rating": 3.8}}}
        ],
        "expect": False,
    },
]

pass_count = 0
fail_count = 0

for i, c in enumerate(cases, 1):
    print(f"\n{'=' * 60}")
    print(f"测试样例 {i:02d}: {c['desc']}")
    print(f"  期望: passed={c['expect']}")
    print(f"  输入 condition: {json.dumps(c['condition'], ensure_ascii=False)}")
    print(f"  输入 task_results: {json.dumps(c['data'], ensure_ascii=False)}")

    passed, msg = evaluate_condition(c["condition"], c["data"])

    print(f"  实际输出: passed={passed}, msg='{msg}'")

    ok = passed == c["expect"]
    if ok:
        pass_count += 1
        print("  结果: ✅ 符合预期")
    else:
        fail_count += 1
        print(f"  结果: ❌ 不符合预期! 期望={c['expect']}, 实际={passed}")

print(f"\n{'=' * 60}")
print(f"总计: {pass_count + fail_count} 个, 通过 {pass_count}, 失败 {fail_count}")
