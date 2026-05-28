"""
project1_cabin_agent/tests/test_stress_20.py
22 个压力测试用例 — 覆盖条件分支、多轮、跨域、边界场景
每个用例 print 实际输出，人工确认结果正确性。
"""

import json

from project1_cabin_agent.nodes.pre_rules import fast_rules_check
from project1_cabin_agent.skills.registry import registry
from project1_cabin_agent.nodes.constants import SubTask
from project1_cabin_agent.nodes.post_rules import (
    _detect_ambiguity,
    _detect_context_bleeding,
)
from project1_cabin_agent.nodes.condition import evaluate_condition


def _p(label: str, value):
    """统一 print 输出"""
    if isinstance(value, dict):
        # 精简输出
        if "sub_tasks" in value and value["sub_tasks"]:
            tasks = value["sub_tasks"]
            value = {
                k: v
                for k, v in value.items()
                if k in ("_oos_flag", "_cross_domain_flag", "intent")
            }
            value["sub_tasks"] = [
                {"intent": t.get("intent"), "slots": t.get("extracted_slots")}
                for t in tasks
            ]
        print(f"  {label} = {json.dumps(value, ensure_ascii=False, indent=2)}")
    elif isinstance(value, list) and value and isinstance(value[0], dict):
        print(f"  {label} = {json.dumps(value, ensure_ascii=False, indent=2)}")
    else:
        print(f"  {label} = {value}")


# ═══════════════════════════════════════════════════
# Group 1: FastRules 规则层
# ═══════════════════════════════════════════════════


def test_01_oos_order_food():
    """OOS: '帮我点杯奶茶' → 应命中 OOS flag"""
    print("\n[01] 输入: '帮我点杯奶茶'")
    result = fast_rules_check("帮我点杯奶茶", [])
    _p("result", result)
    assert result is not None
    assert result.get("_oos_flag") == "点单"
    print("  ✅ 命中 OOS='点单'")


def test_02_oos_phone_call():
    """OOS: '打电话给妈妈' → 应命中打电话"""
    print("\n[02] 输入: '打电话给妈妈'")
    result = fast_rules_check("打电话给妈妈", [])
    _p("result", result)
    assert result is not None
    assert result.get("_oos_flag") == "打电话"
    print("  ✅ 命中 OOS='打电话'")


def test_03_cross_domain_ac_navigate():
    """跨域多意图: '开空调，导航去春熙路' → 应放行云端"""
    print("\n[03] 输入: '开空调，导航去春熙路'")
    result = fast_rules_check("开空调，导航去春熙路", [])
    _p("result", result)
    assert result is None or result == {}
    print("  ✅ 放行云端 (result=None)")


def test_04_pure_abandon():
    """纯取消词: '算了' → 应短路 chitchat"""
    print("\n[04] 输入: '算了'")
    result = fast_rules_check("算了", [])
    _p("result", result)
    assert result is not None
    assert result.get("intent") == "chitchat"
    print("  ✅ 短路 chitchat")


def test_05_short_circuit_ac_off():
    """高频短路: '关空调' → 应直出 ac_control"""
    print("\n[05] 输入: '关空调'")
    result = fast_rules_check("关空调", [])
    _p("result", result)
    assert result is not None
    tasks = result.get("sub_tasks", [])
    assert len(tasks) == 1
    print(f"  intent={tasks[0]['intent']}, slots={tasks[0]['extracted_slots']}")
    assert tasks[0]["intent"] == "ac_control"
    assert tasks[0]["extracted_slots"]["action"] == "off"
    print("  ✅ ac_control, action=off")


# ═══════════════════════════════════════════════════
# Group 2: 条件分支（Phase 3.1）
# ═══════════════════════════════════════════════════


def test_06_condition_gt_pass():
    """条件: count > 0, count=3 → 应通过"""
    print("\n[06] 条件: count > 0, 实际 count=3")
    condition = {
        "logic": "AND",
        "rules": [{"source": "task_0", "field": "count", "op": "gt", "value": 0}],
        "fail_msg": "附近没有充电站",
    }
    task_results = [{"task_id": "task_0", "tool_result": {"data": {"count": 3}}}]
    passed, msg = evaluate_condition(condition, task_results)
    print(f"  passed={passed}, msg='{msg}'")
    assert passed is True
    print("  ✅ 通过")


def test_07_condition_gt_fail():
    """条件: count > 0, count=0 → 应不通过"""
    print("\n[07] 条件: count > 0, 实际 count=0")
    condition = {
        "logic": "AND",
        "rules": [{"source": "task_0", "field": "count", "op": "gt", "value": 0}],
        "fail_msg": "附近没有充电站",
    }
    task_results = [{"task_id": "task_0", "tool_result": {"data": {"count": 0}}}]
    passed, msg = evaluate_condition(condition, task_results)
    print(f"  passed={passed}, msg='{msg}'")
    assert passed is False
    assert "充电站" in msg
    print(f"  ✅ 不通过, fail_msg='{msg}'")


def test_08_condition_not_in_pass():
    """条件: weather_main not_in [雨,雪], weather_main=晴 → 应通过"""
    print("\n[08] 条件: weather_main not_in [雨,雪], 实际='晴'")
    condition = {
        "logic": "AND",
        "rules": [
            {
                "source": "task_0",
                "field": "weather_main",
                "op": "not_in",
                "value": ["雨", "雪"],
            }
        ],
        "fail_msg": "天气不好",
    }
    task_results = [
        {"task_id": "task_0", "tool_result": {"data": {"weather_main": "晴"}}}
    ]
    passed, msg = evaluate_condition(condition, task_results)
    print(f"  passed={passed}, msg='{msg}'")
    assert passed is True
    print("  ✅ 通过")


def test_09_condition_not_in_fail():
    """条件: weather_main not_in [雨,雪], weather_main=雨 → 应不通过"""
    print("\n[09] 条件: weather_main not_in [雨,雪], 实际='雨'")
    condition = {
        "logic": "AND",
        "rules": [
            {
                "source": "task_0",
                "field": "weather_main",
                "op": "not_in",
                "value": ["雨", "雪"],
            }
        ],
        "fail_msg": "天气不好",
    }
    task_results = [
        {"task_id": "task_0", "tool_result": {"data": {"weather_main": "雨"}}}
    ]
    passed, msg = evaluate_condition(condition, task_results)
    print(f"  passed={passed}, msg='{msg}'")
    assert passed is False
    assert "天气" in msg
    print(f"  ✅ 不通过, fail_msg='{msg}'")


def test_10_condition_is_not_empty_pass():
    """条件: results is_not_empty, results=[{...}] → 应通过"""
    print("\n[10] 条件: results is_not_empty, 实际 results=[{name:壳牌}]")
    condition = {
        "logic": "AND",
        "rules": [
            {
                "source": "task_0",
                "field": "results",
                "op": "is_not_empty",
                "value": None,
            }
        ],
        "fail_msg": "没找到",
    }
    task_results = [
        {"task_id": "task_0", "tool_result": {"data": {"results": [{"name": "壳牌"}]}}}
    ]
    passed, msg = evaluate_condition(condition, task_results)
    print(f"  passed={passed}, msg='{msg}'")
    assert passed is True
    print("  ✅ 通过")


def test_11_condition_missing_field_fails():
    """条件: 字段不存在 → 保守策略应不通过"""
    print("\n[11] 条件: nonexistent > 0, 数据只有 count=5 → 字段缺失")
    condition = {
        "logic": "AND",
        "rules": [{"source": "task_0", "field": "nonexistent", "op": "gt", "value": 0}],
        "fail_msg": "数据缺失",
    }
    task_results = [{"task_id": "task_0", "tool_result": {"data": {"count": 5}}}]
    passed, msg = evaluate_condition(condition, task_results)
    print(f"  passed={passed}, msg='{msg}'")
    assert passed is False
    print(f"  ✅ 保守策略: 不通过")


def test_12_condition_or_logic():
    """条件: OR(count>10, has_parking=true), count=2, has_parking=true → 应通过"""
    print("\n[12] 条件: OR(count>10 [✗], has_parking=true [✓])")
    condition = {
        "logic": "OR",
        "rules": [
            {"source": "task_0", "field": "count", "op": "gt", "value": 10},
            {"source": "task_0", "field": "has_parking", "op": "eq", "value": True},
        ],
        "fail_msg": "条件不满足",
    }
    task_results = [
        {
            "task_id": "task_0",
            "tool_result": {"data": {"count": 2, "has_parking": True}},
        }
    ]
    passed, msg = evaluate_condition(condition, task_results)
    print(f"  passed={passed}, msg='{msg}'")
    assert passed is True
    print("  ✅ OR: has_parking 满足 → 通过")


# ═══════════════════════════════════════════════════
# Group 3: 歧义 + 漂移检测
# ═══════════════════════════════════════════════════


def test_13_ambiguity_short_no_object():
    """歧义: '调' + navigate(缺 destination) → 应强制 clarify"""
    print("\n[13] 输入: '调', intent=navigate, slots={}, required=[destination]")
    sub_tasks = [
        {
            "task_id": "task_0",
            "intent": "navigate",
            "extracted_slots": {},
            "required_slots": ["destination"],
        }
    ]
    result = _detect_ambiguity("调", sub_tasks)
    print(f"  结果 intent={result[0]['intent']}")
    assert result[0]["intent"] == "clarify"
    print("  ✅ 强制 clarify")


def test_14_ambiguity_with_clear_object():
    """歧义: '调空调' → 有对象词'空调'，不应拦截"""
    print("\n[14] 输入: '调空调', intent=ac_control, slots={action:adjust}")
    sub_tasks = [
        {
            "task_id": "task_0",
            "intent": "ac_control",
            "extracted_slots": {"action": "adjust"},
            "required_slots": [],
        }
    ]
    result = _detect_ambiguity("调空调", sub_tasks)
    print(f"  结果 intent={result[0]['intent']}")
    assert result[0]["intent"] == "ac_control"
    print("  ✅ 有对象词，不拦截")


def test_15_drift_detection():
    """漂移: 用户说'好的'，LLM 填了 destination=天府广场（来自上轮回复）→ 应清除"""
    print("\n[15] 输入: '好的', slot={destination:'天府广场'}, 上轮回复含'天府广场'")
    messages = [{"role": "assistant", "content": "已找到附近的壳牌加油站和天府广场"}]
    sub_tasks = [
        {
            "task_id": "task_0",
            "intent": "navigate",
            "extracted_slots": {"destination": "天府广场"},
            "required_slots": [],
        }
    ]
    result = _detect_context_bleeding("好的", sub_tasks, messages, needs_ctx=False)
    print(f"  结果 slots={result[0]['extracted_slots']}")
    assert "destination" not in result[0]["extracted_slots"] or not result[0][
        "extracted_slots"
    ].get("destination")
    print("  ✅ 漂移 slot 已清除")


def test_16_drift_with_coreference():
    """漂移: '就去天府广场' → 含指代词'就去'，slot 保留"""
    print("\n[16] 输入: '就去天府广场', 含指代词'就去'")
    messages = [{"role": "assistant", "content": "已找到附近的壳牌加油站和天府广场"}]
    sub_tasks = [
        {
            "task_id": "task_0",
            "intent": "navigate",
            "extracted_slots": {"destination": "天府广场"},
            "required_slots": [],
        }
    ]
    result = _detect_context_bleeding(
        "就去天府广场", sub_tasks, messages, needs_ctx=False
    )
    print(f"  结果 slots={result[0]['extracted_slots']}")
    assert result[0]["extracted_slots"].get("destination") == "天府广场"
    print("  ✅ 指代消解，slot 保留")


# ═══════════════════════════════════════════════════
# Group 4: Registry
# ═══════════════════════════════════════════════════


def test_17_registry_intents():
    """Registry: 应有 11 个 skill intent"""
    print("\n[17] 检查 Registry intent 总数")
    all_intents = registry.get_all_intents()
    for domain, intents in all_intents.items():
        print(f"  {domain}: {intents}")
    total = sum(len(v) for v in all_intents.values())
    print(f"  总计: {total} 个")
    assert total == 11
    print("  ✅ 11 个 skill intent")


def test_18_registry_domains():
    """Registry: 应有 4 个 domain"""
    print("\n[18] 检查 Registry domain")
    all_intents = registry.get_all_intents()
    domains = set(all_intents.keys())
    print(f"  domains={domains}")
    assert domains == {"climate", "map", "media", "vehicle"}
    print("  ✅ 4 个 domain")


def test_19_registry_alias():
    """Registry: start_navigation 别名 → map 域 navigate"""
    print("\n[19] 别名: start_navigation → ?")
    domain = registry.get_domain_for_intent("start_navigation")
    spec = registry.get_intent_spec("start_navigation")
    print(f"  domain={domain}, spec.name={spec.name if spec else None}")
    assert domain == "map"
    print("  ✅ 解析到 map 域")


def test_20_registry_blackboard():
    """Registry: navigate 应有黑板声明"""
    print("\n[20] navigate 黑板声明")
    bb = registry.get_blackboard_decl("navigate")
    print(f"  blackboard={bb}")
    assert bb is not None
    assert "produces" in bb
    print(f"  ✅ produces={bb['produces']}")


# ═══════════════════════════════════════════════════
# Group 5: Pydantic 模型
# ═══════════════════════════════════════════════════


def test_21_condition_model():
    """Condition Pydantic 模型序列化"""
    print("\n[21] Condition 模型构建")
    from project1_cabin_agent.nodes.constants import Condition, ConditionRule

    c = Condition(
        logic="AND",
        rules=[ConditionRule(source="task_0", field="count", op="gt", value=0)],
        fail_msg="没有找到",
    )
    print(
        f"  logic={c.logic}, rules[0]={c.rules[0].model_dump()}, fail_msg='{c.fail_msg}'"
    )
    assert c.logic == "AND"
    assert len(c.rules) == 1
    print("  ✅ 模型正确")


def test_22_subtask_with_condition():
    """SubTask 含 condition 字段，整体序列化/反序列化"""
    print("\n[22] SubTask + Condition 组合")
    from project1_cabin_agent.nodes.constants import Condition, ConditionRule

    task = SubTask(
        task_id="task_1",
        intent="navigate",
        intent_confidence=0.9,
        ambiguity_score=0.0,
        depends_on=["task_0"],
        condition=Condition(
            logic="AND",
            rules=[ConditionRule(source="task_0", field="count", op="gt", value=0)],
            fail_msg="没找到",
        ),
    )
    d = task.model_dump()
    print(
        f"  task_id={d['task_id']}, intent={d['intent']}, depends_on={d['depends_on']}"
    )
    print(f"  condition={d['condition']}")
    assert task.condition is not None
    assert task.condition.fail_msg == "没找到"
    # 确认序列化后 condition 完整
    assert d["condition"]["logic"] == "AND"
    assert d["condition"]["rules"][0]["source"] == "task_0"
    print("  ✅ SubTask+Condition 序列化完整")
