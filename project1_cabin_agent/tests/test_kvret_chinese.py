"""
project1_cabin_agent/tests/test_kvret_chinese.py — 中文多轮 eval

基于 KVRet 对话模式，用中国司机的口语重写。
测试 Phase 4 的 DST/Policy/Memory/Proactive 能力。

设计原则（解耦）：
  - 每个场景是独立的数据声明（scenario dict）
  - 跑测试的逻辑在 TestKVRretChinese 里（引擎）
  - 新增场景只加数据，不改引擎

模式来源（KVRet 3030 条英文对话）：
  1. 搜索 → 导航（POI 搜索后导航去那里）
  2. 换方案（太贵/太远/太慢 → reroute）
  3. 追问详情（为什么走这条 → explain）
  4. 放弃（算了不去了 → abandon）
  5. 条件分支（如果不堵就走高速）
  6. 纠正（不是春熙路 是天府广场 → correction）
  7. 天气多轮（查天气 → 换城市）
  8. Proactive 触发（油量低/高温）
"""

from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════
# 场景定义（数据层，只加数据不改引擎）
# ═══════════════════════════════════════════════════

SCENARIOS = [
    # ─────────────────────────────────────────────
    # 模式 1: 搜索 → 导航（指代消解 + DST 填充）
    # KVRet: "where's the nearest parking garage" → "Yes, directions there"
    # ─────────────────────────────────────────────
    {
        "id": "poi_then_navigate",
        "desc": "搜索火锅店后导航去那里",
        "rounds": [
            {
                "user": "附近有没有火锅店",
                "expected_intent": "search_poi",
                "expected_slots": {"keyword": "火锅"},
                "expected_dst": {"goal_type": "map"},
            },
            {
                "user": "去那里",
                "expected_policy": "fill_from_dst",
                "expected_dst_filled": True,
                # 模拟第一轮搜索后 DST 累积的实体
                "dst_entities": {"poi": "海底捞火锅(春熙路店)", "destination": "海底捞火锅(春熙路店)"},
            },
        ],
    },
    {
        "id": "poi_select_second",
        "desc": "搜索加油站后选第二个",
        "rounds": [
            {
                "user": "附近哪里有加油站",
                "expected_intent": "search_poi",
                "expected_slots": {"keyword": "加油站"},
            },
            {
                "user": "去第二个",
                "expected_policy": "fill_from_dst",
                "expected_dst_filled": True,
                "dst_entities": {"poi": "中石化(科华北路店)"},
            },
        ],
    },

    # ─────────────────────────────────────────────
    # 模式 2: 换方案（Policy reroute）
    # KVRet: "route that avoids all heavy traffic"
    # ─────────────────────────────────────────────
    {
        "id": "reroute_avoid_toll",
        "desc": "导航结果有过路费，嫌贵换路线",
        "context": {
            "vehicle": {"fuel": 68, "speed": 80, "temperature": 25.0, "ac_on": True},
            "active_goal": {"goal_type": "map", "slots": {"destination": "重庆"},
                           "last_result": {"toll": "165元", "distance": "300km"}},
        },
        "rounds": [
            {
                "user": "太贵了",
                "expected_policy": "reroute",
                "expected_slot_overrides": {"route_type": "avoid_toll"},
            },
        ],
    },
    {
        "id": "reroute_shortest",
        "desc": "嫌远要换最短路线",
        "context": {
            "active_goal": {"goal_type": "map", "slots": {"destination": "天府广场"},
                           "last_result": {"distance": "25km"}},
        },
        "rounds": [
            {
                "user": "太远了换条短的",
                "expected_policy": "reroute",
                "expected_slot_overrides": {"route_type": "shortest"},
            },
        ],
    },
    {
        "id": "reroute_fastest",
        "desc": "嫌慢要换最快路线",
        "context": {
            "active_goal": {"goal_type": "map", "slots": {"destination": "重庆"},
                           "last_result": {"duration": "6小时"}},
        },
        "rounds": [
            {
                "user": "太慢了",
                "expected_policy": "reroute",
                "expected_slot_overrides": {"route_type": "fastest"},
            },
        ],
    },
    {
        "id": "reroute_general",
        "desc": "换一条路（通用不满）",
        "context": {
            "active_goal": {"goal_type": "map", "slots": {"destination": "天府广场"},
                           "last_result": {"toll": "0元"}},
        },
        "rounds": [
            {
                "user": "换一条",
                "expected_policy": "reroute",
            },
        ],
    },

    # ─────────────────────────────────────────────
    # 模式 3: 追问详情（Policy explain）
    # KVRet: "What is the address?" + 多轮追问
    # ─────────────────────────────────────────────
    {
        "id": "explain_route",
        "desc": "追问为什么走这条路线",
        "context": {
            "active_goal": {"goal_type": "map", "slots": {"destination": "重庆"},
                           "last_result": {"distance": "300km", "toll": "165元", "route": "G75兰海高速"}},
        },
        "rounds": [
            {
                "user": "为什么走这条",
                "expected_policy": "explain",
            },
        ],
    },

    # ─────────────────────────────────────────────
    # 模式 4: 放弃（Policy abandon）
    # KVRet: "Thanks for all the help"（结束语）
    # ─────────────────────────────────────────────
    {
        "id": "abandon_explicit",
        "desc": "明确说算了不去了",
        "context": {
            "active_goal": {"goal_type": "map", "slots": {"destination": "天府广场"}},
        },
        "rounds": [
            {
                "user": "算了不去了",
                "expected_policy": "abandon",
            },
        ],
    },
    {
        "id": "abandon_cancel",
        "desc": "说取消",
        "context": {
            "active_goal": {"goal_type": "map", "slots": {"destination": "重庆"}},
        },
        "rounds": [
            {
                "user": "取消导航",
                "expected_policy": "abandon",
            },
        ],
    },

    # ─────────────────────────────────────────────
    # 模式 5: 连续失败放弃
    # ─────────────────────────────────────────────
    {
        "id": "retry_limit",
        "desc": "连续失败3次自动放弃",
        "context": {
            "consecutive_failures": 3,
            "active_goal": {"goal_type": "map", "slots": {"destination": "某地"}},
        },
        "rounds": [
            {
                "user": "再试一次吧",
                "expected_policy": "abandon",
            },
        ],
    },

    # ─────────────────────────────────────────────
    # 模式 6: 纠正（不是A是B）
    # KVRet 里常见: 用户更正之前的信息
    # ─────────────────────────────────────────────
    {
        "id": "correction_destination",
        "desc": "纠正目的地（不是春熙路 是天府广场）",
        "rounds": [
            {
                "user": "不是春熙路 是天府广场",
                "expected_intent": "navigate",
                "expected_slots": {"destination": "天府广场"},
            },
        ],
    },
    {
        "id": "correction_temperature",
        "desc": "纠正温度（不是26度 是22度）",
        "rounds": [
            {
                "user": "不是26度 是22度",
                "expected_intent": "ac_control",
                "expected_slots": {"temperature": 22},
            },
        ],
    },

    # ─────────────────────────────────────────────
    # 模式 7: 条件分支
    # KVRet: "avoid heavy traffic if possible"
    # ─────────────────────────────────────────────
    {
        "id": "conditional_traffic",
        "desc": "不堵走高速",
        "rounds": [
            {
                "user": "查下前面堵不堵车 不堵的话走高速",
                "expected_intent": "navigate",
                "expected_has_condition": True,
            },
        ],
    },

    # ─────────────────────────────────────────────
    # 模式 8: Proactive 触发
    # ─────────────────────────────────────────────
    {
        "id": "proactive_fuel_low",
        "desc": "导航中油量低于20%",
        "proactive_test": True,
        "vehicle": {"fuel": 12, "speed": 80, "temperature": 25.0, "ac_on": True,
                    "battery": 82, "seat_heat_level": 0, "ac_temp": 24.0, "ac_mode": "auto"},
        "goals": [{"goal_type": "map", "status": "active"}],
        "expected_proactive": "map_fuel_warning",
    },
    {
        "id": "proactive_hot_no_ac",
        "desc": "高温+空调关+行驶中",
        "proactive_test": True,
        "vehicle": {"fuel": 68, "speed": 60, "temperature": 38.0, "ac_on": False,
                    "battery": 82, "seat_heat_level": 0, "ac_temp": 24.0, "ac_mode": "auto"},
        "goals": [],
        "expected_proactive": "climate_hot_no_ac",
    },
    {
        "id": "proactive_normal_no_trigger",
        "desc": "一切正常不触发",
        "proactive_test": True,
        "vehicle": {"fuel": 68, "speed": 60, "temperature": 25.0, "ac_on": True,
                    "battery": 82, "seat_heat_level": 0, "ac_temp": 24.0, "ac_mode": "auto"},
        "goals": [],
        "expected_proactive": None,
    },
    {
        "id": "proactive_pending_blocks_suggest",
        "desc": "有pending goal时建议类不触发",
        "proactive_test": True,
        "vehicle": {"fuel": 68, "speed": 0, "temperature": 5.0, "ac_on": False,
                    "battery": 82, "seat_heat_level": 0, "ac_temp": 24.0, "ac_mode": "auto"},
        "goals": [{"goal_type": "map", "status": "pending"}],
        "expected_proactive": None,
    },

    # ─────────────────────────────────────────────
    # 模式 9: 正常导航不触发任何规则
    # ─────────────────────────────────────────────
    {
        "id": "normal_navigate",
        "desc": "正常导航请求",
        "rounds": [
            {
                "user": "导航去春熙路",
                "expected_intent": "navigate",
                "expected_slots": {"destination": "春熙路"},
                "expected_policy": "execute",
            },
        ],
    },
    {
        "id": "normal_ac",
        "desc": "正常空调请求",
        "rounds": [
            {
                "user": "空调开到24度",
                "expected_intent": "ac_control",
                "expected_slots": {"temperature": 24},
                "expected_policy": "execute",
            },
        ],
    },
]


# ═══════════════════════════════════════════════════
# 测试引擎
# ═══════════════════════════════════════════════════


def _build_dst(context: dict) -> "DialogueState":
    """从 context 构造 DialogueState"""
    from project1_cabin_agent.nodes.dialogue_state import (
        ActiveGoal,
        DialogueState,
    )

    goals = []
    goal_cfg = context.get("active_goal", {})
    if goal_cfg:
        goals.append(ActiveGoal(
            goal_type=goal_cfg.get("goal_type", "map"),
            slots=goal_cfg.get("slots", {}),
            status="active",
            last_result=goal_cfg.get("last_result"),
        ))

    return DialogueState(
        consecutive_failures=context.get("consecutive_failures", 0),
        active_goals=goals,
    )


class TestPolicyScenarios:
    """测试 Policy 对话策略"""

    @pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["id"])
    def test_policy(self, scenario):
        """测试每个场景的 Policy 决策"""
        if scenario.get("proactive_test"):
            pytest.skip("Proactive 场景在 TestProactiveScenarios 测")

        rounds = scenario.get("rounds", [])
        if not rounds:
            pytest.skip("无 rounds")

        context = scenario.get("context", {})
        ds = _build_dst(context)

        from project1_cabin_agent.nodes.policy import PolicyEngine
        engine = PolicyEngine()

        for i, turn in enumerate(rounds):
            user_input = turn["user"]

            # 如果本轮有 dst_entities，模拟上一轮 DST 累积
            dst_entities = turn.get("dst_entities")
            if dst_entities:
                ds.key_entities = dst_entities

            action = engine.decide(ds, user_input)

            # 检查 Policy
            expected_policy = turn.get("expected_policy")
            if expected_policy:
                assert action.action.value == expected_policy, (
                    f"Round {i}: expected policy={expected_policy}, got {action.action.value}"
                )

            # 检查 slot_overrides
            expected_overrides = turn.get("expected_slot_overrides")
            if expected_overrides:
                for k, v in expected_overrides.items():
                    assert action.slot_overrides.get(k) == v, (
                        f"Round {i}: expected slot_overrides[{k}]={v}, got {action.slot_overrides}"
                    )


class TestProactiveScenarios:
    """测试 Proactive 主动引擎"""

    @pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["id"])
    def test_proactive(self, scenario):
        """测试 Proactive 触发"""
        if not scenario.get("proactive_test"):
            pytest.skip("非 Proactive 场景")

        from project1_cabin_agent.nodes.proactive import ProactiveContext, ProactiveEngine
        from project1_cabin_agent.nodes.dialogue_state import ActiveGoal, DialogueState

        goals = [
            ActiveGoal(goal_type=g["goal_type"], status=g.get("status", "active"))
            for g in scenario.get("goals", [])
        ]
        ds = DialogueState(active_goals=goals)
        ctx = ProactiveContext(
            dialogue_state=ds,
            vehicle_snapshot=scenario["vehicle"],
        )

        engine = ProactiveEngine()
        result = engine.check(ctx)

        expected = scenario["expected_proactive"]
        if expected is None:
            assert result is None, f"不应该触发，但触发了 {result.rule_name}"
        else:
            assert result is not None, f"应该触发 {expected}，但没触发"
            assert result.rule_name == expected, (
                f"期望触发 {expected}，实际触发 {result.rule_name}"
            )


class TestScenarioSummary:
    """汇总统计"""

    def test_scenario_count(self):
        """确保场景覆盖足够全面"""
        policy_count = sum(
            1 for s in SCENARIOS
            if not s.get("proactive_test") and s.get("rounds")
        )
        proactive_count = sum(
            1 for s in SCENARIOS if s.get("proactive_test")
        )
        total_rounds = sum(
            len(s.get("rounds", []))
            for s in SCENARIOS
            if not s.get("proactive_test")
        )

        print(f"\n  Policy 场景: {policy_count}")
        print(f"  Proactive 场景: {proactive_count}")
        print(f"  总对话轮次: {total_rounds}")
        print(f"  总场景数: {len(SCENARIOS)}")

        assert policy_count >= 10, "Policy 场景应 ≥ 10"
        assert proactive_count >= 3, "Proactive 场景应 ≥ 3"
