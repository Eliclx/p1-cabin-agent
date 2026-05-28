"""
project1_cabin_agent/tests/test_condition_20.py
20 个条件分支专项测试 — 覆盖所有 op、边界值、AND/OR 组合、数据层差异

每个用例 print 实际输出，人工确认正确性。
"""

import json
from project1_cabin_agent.nodes.condition import evaluate_condition


def _run(idx: str, desc: str, condition: dict, task_results: list):
    """统一执行 + print"""
    print(f"\n[{idx}] {desc}")
    print(
        f"  condition: logic={condition['logic']}, rules={json.dumps(condition['rules'], ensure_ascii=False)}"
    )
    print(
        f"  task_results data: {json.dumps([{'task_id': r['task_id'], 'data': r.get('tool_result', {}).get('data', r.get('tool_result', {}))} for r in task_results], ensure_ascii=False)}"
    )
    passed, msg = evaluate_condition(condition, task_results)
    print(f"  → passed={passed}, msg='{msg}'")
    return passed, msg


# ═══════════════════════════════════════════════════
# 基础 op 测试（10个）
# ═══════════════════════════════════════════════════


def test_01_eq_pass():
    p, m = _run(
        "01",
        "eq: weather_main=='晴', 实际='晴' → 通过",
        {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "weather_main", "op": "eq", "value": "晴"}
            ],
            "fail_msg": "天气不晴",
        },
        [{"task_id": "t0", "tool_result": {"data": {"weather_main": "晴"}}}],
    )
    assert p is True


def test_02_eq_fail():
    p, m = _run(
        "02",
        "eq: weather_main=='晴', 实际='多云' → 不通过",
        {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "weather_main", "op": "eq", "value": "晴"}
            ],
            "fail_msg": "天气不晴",
        },
        [{"task_id": "t0", "tool_result": {"data": {"weather_main": "多云"}}}],
    )
    assert p is False
    assert "不晴" in m


def test_03_neq_pass():
    p, m = _run(
        "03",
        "neq: status!='error', 实际='success' → 通过",
        {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "status", "op": "neq", "value": "error"}
            ],
            "fail_msg": "上游出错",
        },
        [{"task_id": "t0", "tool_result": {"data": {"status": "success"}}}],
    )
    assert p is True


def test_04_neq_fail():
    p, m = _run(
        "04",
        "neq: status!='error', 实际='error' → 不通过",
        {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "status", "op": "neq", "value": "error"}
            ],
            "fail_msg": "上游出错",
        },
        [{"task_id": "t0", "tool_result": {"data": {"status": "error"}}}],
    )
    assert p is False


def test_05_gt_pass():
    p, m = _run(
        "05",
        "gt: count>0, 实际=5 → 通过",
        {
            "logic": "AND",
            "rules": [{"source": "t0", "field": "count", "op": "gt", "value": 0}],
            "fail_msg": "没有结果",
        },
        [{"task_id": "t0", "tool_result": {"data": {"count": 5}}}],
    )
    assert p is True


def test_06_gt_boundary():
    p, m = _run(
        "06",
        "gt: count>0, 实际=0 → 不通过（边界值）",
        {
            "logic": "AND",
            "rules": [{"source": "t0", "field": "count", "op": "gt", "value": 0}],
            "fail_msg": "没有结果",
        },
        [{"task_id": "t0", "tool_result": {"data": {"count": 0}}}],
    )
    assert p is False


def test_07_gte_pass():
    p, m = _run(
        "07",
        "gte: count>=0, 实际=0 → 通过（含等号）",
        {
            "logic": "AND",
            "rules": [{"source": "t0", "field": "count", "op": "gte", "value": 0}],
            "fail_msg": "没有结果",
        },
        [{"task_id": "t0", "tool_result": {"data": {"count": 0}}}],
    )
    assert p is True


def test_08_lt_pass():
    p, m = _run(
        "08",
        "lt: distance<10.0, 实际=3.5 → 通过",
        {
            "logic": "AND",
            "rules": [{"source": "t0", "field": "distance", "op": "lt", "value": 10.0}],
            "fail_msg": "太远了",
        },
        [{"task_id": "t0", "tool_result": {"data": {"distance": 3.5}}}],
    )
    assert p is True


def test_09_lte_boundary():
    p, m = _run(
        "09",
        "lte: distance<=10.0, 实际=10.0 → 通过（含等号）",
        {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "distance", "op": "lte", "value": 10.0}
            ],
            "fail_msg": "太远了",
        },
        [{"task_id": "t0", "tool_result": {"data": {"distance": 10.0}}}],
    )
    assert p is True


def test_10_lte_fail():
    p, m = _run(
        "10",
        "lte: distance<=10.0, 实际=10.1 → 不通过",
        {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "distance", "op": "lte", "value": 10.0}
            ],
            "fail_msg": "太远了",
        },
        [{"task_id": "t0", "tool_result": {"data": {"distance": 10.1}}}],
    )
    assert p is False


# ═══════════════════════════════════════════════════
# in / not_in / is_empty / is_not_empty（6个）
# ═══════════════════════════════════════════════════


def test_11_in_pass():
    p, m = _run(
        "11",
        "in: weather_main in [晴,多云], 实际='晴' → 通过",
        {
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
        [{"task_id": "t0", "tool_result": {"data": {"weather_main": "晴"}}}],
    )
    assert p is True


def test_12_in_fail():
    p, m = _run(
        "12",
        "in: weather_main in [晴,多云], 实际='暴雨' → 不通过",
        {
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
        [{"task_id": "t0", "tool_result": {"data": {"weather_main": "暴雨"}}}],
    )
    assert p is False


def test_13_not_in_pass():
    p, m = _run(
        "13",
        "not_in: weather_main not_in [雨,雪,冰雹], 实际='阴' → 通过",
        {
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
        [{"task_id": "t0", "tool_result": {"data": {"weather_main": "阴"}}}],
    )
    assert p is True


def test_14_not_in_fail():
    p, m = _run(
        "14",
        "not_in: weather_main not_in [雨,雪,冰雹], 实际='冰雹' → 不通过",
        {
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
        [{"task_id": "t0", "tool_result": {"data": {"weather_main": "冰雹"}}}],
    )
    assert p is False


def test_15_is_empty_pass():
    p, m = _run(
        "15",
        "is_empty: results=[], 实际=[] → True（空）",
        {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "results", "op": "is_empty", "value": None}
            ],
            "fail_msg": "有结果",
        },
        [{"task_id": "t0", "tool_result": {"data": {"results": []}}}],
    )
    assert p is True


def test_16_is_not_empty_pass():
    p, m = _run(
        "16",
        "is_not_empty: results=[a,b], 实际=[a,b] → True（非空）",
        {
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
        [{"task_id": "t0", "tool_result": {"data": {"results": ["a", "b"]}}}],
    )
    assert p is True


# ═══════════════════════════════════════════════════
# AND / OR 多规则组合（4个）
# ═══════════════════════════════════════════════════


def test_17_and_both_pass():
    p, m = _run(
        "17",
        "AND: count>0 [✓] AND distance<5.0 [✓] → 通过",
        {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "count", "op": "gt", "value": 0},
                {"source": "t0", "field": "distance", "op": "lt", "value": 5.0},
            ],
            "fail_msg": "没有附近的结果",
        },
        [{"task_id": "t0", "tool_result": {"data": {"count": 3, "distance": 1.2}}}],
    )
    assert p is True


def test_18_and_one_fail():
    p, m = _run(
        "18",
        "AND: count>0 [✓] AND distance<5.0 [✗, 实际=8.0] → 不通过",
        {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "count", "op": "gt", "value": 0},
                {"source": "t0", "field": "distance", "op": "lt", "value": 5.0},
            ],
            "fail_msg": "没有附近的结果",
        },
        [{"task_id": "t0", "tool_result": {"data": {"count": 3, "distance": 8.0}}}],
    )
    assert p is False


def test_19_or_one_pass():
    p, m = _run(
        "19",
        "OR: count>10 [✗, 实际=2] OR has_parking=true [✓] → 通过",
        {
            "logic": "OR",
            "rules": [
                {"source": "t0", "field": "count", "op": "gt", "value": 10},
                {"source": "t0", "field": "has_parking", "op": "eq", "value": True},
            ],
            "fail_msg": "没有停车场",
        },
        [{"task_id": "t0", "tool_result": {"data": {"count": 2, "has_parking": True}}}],
    )
    assert p is True


def test_20_or_both_fail():
    p, m = _run(
        "20",
        "OR: count>10 [✗] OR rating>=4.5 [✗, 实际=3.8] → 不通过",
        {
            "logic": "OR",
            "rules": [
                {"source": "t0", "field": "count", "op": "gt", "value": 10},
                {"source": "t0", "field": "rating", "op": "gte", "value": 4.5},
            ],
            "fail_msg": "不满足条件",
        },
        [{"task_id": "t0", "tool_result": {"data": {"count": 2, "rating": 3.8}}}],
    )
    assert p is False


# ═══════════════════════════════════════════════════
# 边界 + 异常场景（追加4个，共24个，取前20个序号即可）
# ═══════════════════════════════════════════════════


def test_B1_source_missing():
    """source task_id 不在 task_results 中 → 保守策略不通过"""
    p, m = _run(
        "B1",
        "source='t99' 不存在 → 保守不通过",
        {
            "logic": "AND",
            "rules": [{"source": "t99", "field": "count", "op": "gt", "value": 0}],
            "fail_msg": "找不到上游",
        },
        [{"task_id": "t0", "tool_result": {"data": {"count": 5}}}],
    )
    assert p is False


def test_B2_field_missing():
    """field 不存在 → 保守策略不通过"""
    p, m = _run(
        "B2",
        "field='nonexistent' 不存在 → 保守不通过",
        {
            "logic": "AND",
            "rules": [{"source": "t0", "field": "nonexistent", "op": "gt", "value": 0}],
            "fail_msg": "字段缺失",
        },
        [{"task_id": "t0", "tool_result": {"data": {"count": 5}}}],
    )
    assert p is False


def test_B3_no_data_wrapper():
    """tool_result 没有 data 包装层（扁平结构）→ 应从外层取字段"""
    p, m = _run(
        "B3",
        "tool_result 无 data 包装, 直接有 count 字段",
        {
            "logic": "AND",
            "rules": [{"source": "t0", "field": "count", "op": "gt", "value": 0}],
            "fail_msg": "没结果",
        },
        [{"task_id": "t0", "tool_result": {"count": 3, "status": "done"}}],
    )
    assert p is True


def test_B4_empty_rules():
    """rules 为空列表 → 默认通过（没有条件需要检查）"""
    p, m = _run(
        "B4",
        "rules=[] → 默认通过",
        {"logic": "AND", "rules": [], "fail_msg": "不应该触发"},
        [{"task_id": "t0", "tool_result": {"data": {}}}],
    )
    assert p is True


def test_B5_negative_value():
    """负数比较"""
    p, m = _run(
        "B5",
        "gt: temperature>-10, 实际=-5 → 通过",
        {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "temperature", "op": "gt", "value": -10}
            ],
            "fail_msg": "太冷",
        },
        [{"task_id": "t0", "tool_result": {"data": {"temperature": -5}}}],
    )
    assert p is True


def test_B6_zero_is_falsy():
    """is_empty: count=0 → 数字 0 算 falsy → is_empty=True"""
    p, m = _run(
        "B6",
        "is_empty: count=0 → 数字0算falsy",
        {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "count", "op": "is_empty", "value": None}
            ],
            "fail_msg": "有结果",
        },
        [{"task_id": "t0", "tool_result": {"data": {"count": 0}}}],
    )
    assert p is True


def test_B7_string_value_gt():
    """gt: 字符串 'abc' > 0 → 应失败（非数字）"""
    p, m = _run(
        "B7",
        "gt: name>0, 实际='abc' → 非数字，异常降级不通过",
        {
            "logic": "AND",
            "rules": [{"source": "t0", "field": "name", "op": "gt", "value": 0}],
            "fail_msg": "类型错误",
        },
        [{"task_id": "t0", "tool_result": {"data": {"name": "abc"}}}],
    )
    assert p is False


def test_B8_cross_source_and():
    """AND 跨 source: t0.count>0 AND t1.status=='success'"""
    p, m = _run(
        "B8",
        "AND 跨 source: t0.count>0 [✓] AND t1.status==success [✓]",
        {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "count", "op": "gt", "value": 0},
                {"source": "t1", "field": "status", "op": "eq", "value": "success"},
            ],
            "fail_msg": "条件不满足",
        },
        [
            {"task_id": "t0", "tool_result": {"data": {"count": 3}}},
            {"task_id": "t1", "tool_result": {"data": {"status": "success"}}},
        ],
    )
    assert p is True


def test_B9_cross_source_one_missing():
    """AND 跨 source: t1 不存在 → 不通过"""
    p, m = _run(
        "B9",
        "AND 跨 source: t0.count>0 [✓] 但 t1 不存在 → 不通过",
        {
            "logic": "AND",
            "rules": [
                {"source": "t0", "field": "count", "op": "gt", "value": 0},
                {"source": "t1", "field": "status", "op": "eq", "value": "success"},
            ],
            "fail_msg": "条件不满足",
        },
        [{"task_id": "t0", "tool_result": {"data": {"count": 3}}}],
    )
    assert p is False


def test_B10_is_not_empty_string():
    """is_not_empty: 空字符串 → falsy"""
    p, m = _run(
        "B10",
        "is_not_empty: destination='', 实际='' → 不通过",
        {
            "logic": "AND",
            "rules": [
                {
                    "source": "t0",
                    "field": "destination",
                    "op": "is_not_empty",
                    "value": None,
                }
            ],
            "fail_msg": "没目的地",
        },
        [{"task_id": "t0", "tool_result": {"data": {"destination": ""}}}],
    )
    assert p is False
