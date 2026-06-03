"""
tests/test_policy.py — PolicyEngine Phase 4C 测试

覆盖：每条规则的命中/未命中 + 边界条件 + 优先级
"""

import pytest

from project1_cabin_agent.nodes.dialogue_state import (
    ActiveGoal,
    DialogueState,
    UserAttitude,
)
from project1_cabin_agent.nodes.policy import (
    PolicyAction,
    PolicyActionType,
    PolicyEngine,
)


@pytest.fixture
def engine():
    return PolicyEngine()


# ── 辅助 ──


def _make_ds(
    attitude=UserAttitude.NEUTRAL,
    entities=None,
    goals=None,
):
    return DialogueState(
        user_attitude=attitude,
        key_entities=entities or {},
        active_goals=goals or [],
    )


def _nav_goal(attempt=1, slots=None, last_result=None):
    return ActiveGoal(
        goal_type="map",
        attempt_count=attempt,
        slots=slots or {"destination": "重庆"},
        last_result=last_result,
    )


# ═══════════════════════════════════════════════════
# 0. 默认 EXECUTE
# ═══════════════════════════════════════════════════


class TestDefaultExecute:
    def test_normal_input(self, engine):
        ds = _make_ds(goals=[_nav_goal()])
        action = engine.decide(ds, "导航去成都")
        assert action.action == PolicyActionType.EXECUTE

    def test_empty_state(self, engine):
        ds = DialogueState()
        action = engine.decide(ds, "你好")
        assert action.action == PolicyActionType.EXECUTE

    def test_no_keywords_match(self, engine):
        ds = _make_ds(goals=[_nav_goal(last_result={"toll": "165元"})])
        action = engine.decide(ds, "谢谢")
        assert action.action == PolicyActionType.EXECUTE


# ═══════════════════════════════════════════════════
# 1. ABANDON
# ═══════════════════════════════════════════════════


class TestAbandon:
    def test_explicit_cancel(self, engine):
        ds = _make_ds(goals=[_nav_goal()])
        action = engine.decide(ds, "算了不去了")
        assert action.action == PolicyActionType.ABANDON
        assert "取消" in action.reply_template

    def test_cancel_with_destination(self, engine):
        ds = _make_ds(goals=[_nav_goal(slots={"destination": "天府广场"})])
        action = engine.decide(ds, "取消")
        assert action.action == PolicyActionType.ABANDON
        assert "天府广场" in action.reply_template

    def test_cancel_no_goal(self, engine):
        ds = DialogueState()
        action = engine.decide(ds, "算了")
        assert action.action == PolicyActionType.ABANDON
        assert "取消" in action.reply_template

    def test_not_cancel(self, engine):
        ds = _make_ds(goals=[_nav_goal()])
        action = engine.decide(ds, "导航去天府广场")
        assert action.action != PolicyActionType.ABANDON


# ═══════════════════════════════════════════════════
# 2a. REROUTE — 嫌贵
# ═══════════════════════════════════════════════════


class TestRerouteCost:
    def test_too_expensive(self, engine):
        ds = _make_ds(
            attitude=UserAttitude.UNSATISFIED,
            goals=[_nav_goal(last_result={"toll": "165元", "distance": "300km"})],
        )
        action = engine.decide(ds, "太贵了")
        assert action.action == PolicyActionType.REROUTE
        assert action.slot_overrides["route_type"] == "avoid_toll"
        assert action.slot_overrides["destination"] == "重庆"

    def test_explicit_cost_complaint(self, engine):
        ds = _make_ds(
            goals=[_nav_goal(last_result={"toll": "200元"})],
        )
        action = engine.decide(ds, "过路费太高了")
        assert action.action == PolicyActionType.REROUTE
        assert action.slot_overrides["route_type"] == "avoid_toll"

    def test_wants_alternative_with_toll(self, engine):
        ds = _make_ds(
            attitude=UserAttitude.WANTS_ALTERNATIVE,
            goals=[_nav_goal(last_result={"toll": "80元"})],
        )
        action = engine.decide(ds, "换一条")
        assert action.action == PolicyActionType.REROUTE
        assert action.slot_overrides["route_type"] == "avoid_toll"

    def test_no_toll_no_reroute_cost(self, engine):
        ds = _make_ds(
            attitude=UserAttitude.UNSATISFIED,
            goals=[_nav_goal(last_result={"distance": "300km"})],
        )
        action = engine.decide(ds, "太贵了")
        # 没有 toll，不应触发 cost reroute
        assert action.action != PolicyActionType.REROUTE or \
               action.slot_overrides.get("route_type") != "avoid_toll"

    def test_no_last_result(self, engine):
        ds = _make_ds(
            attitude=UserAttitude.UNSATISFIED,
            goals=[_nav_goal(last_result=None)],
        )
        action = engine.decide(ds, "太贵了")
        assert action.action == PolicyActionType.EXECUTE


# ═══════════════════════════════════════════════════
# 2b. REROUTE — 嫌远
# ═══════════════════════════════════════════════════


class TestRerouteDistance:
    def test_too_far(self, engine):
        ds = _make_ds(
            goals=[_nav_goal(last_result={"distance": "500km"})],
        )
        action = engine.decide(ds, "太远了")
        assert action.action == PolicyActionType.REROUTE
        assert action.slot_overrides["route_type"] == "shortest"
        assert action.slot_overrides["destination"] == "重庆"

    def test_too_detour(self, engine):
        ds = _make_ds(
            goals=[_nav_goal(last_result={"distance": "400km"})],
        )
        action = engine.decide(ds, "太绕了")
        assert action.action == PolicyActionType.REROUTE
        assert action.slot_overrides["route_type"] == "shortest"


# ═══════════════════════════════════════════════════
# 2c. REROUTE — 嫌慢
# ═══════════════════════════════════════════════════


class TestRerouteTime:
    def test_too_slow(self, engine):
        ds = _make_ds(
            goals=[_nav_goal(last_result={"duration": "6h"})],
        )
        action = engine.decide(ds, "太慢了")
        assert action.action == PolicyActionType.REROUTE
        assert action.slot_overrides["route_type"] == "fastest"
        assert action.slot_overrides["destination"] == "重庆"


# ═══════════════════════════════════════════════════
# 3. REROUTE — 通用换方案
# ═══════════════════════════════════════════════════


class TestRerouteGeneral:
    def test_change_route(self, engine):
        ds = _make_ds(
            goals=[_nav_goal(last_result={"distance": "300km"})],
        )
        action = engine.decide(ds, "换一条路")
        assert action.action == PolicyActionType.REROUTE
        assert action.slot_overrides["destination"] == "重庆"

    def test_change_one(self, engine):
        ds = _make_ds(
            goals=[_nav_goal(last_result={"distance": "300km"})],
        )
        action = engine.decide(ds, "换一个")
        assert action.action == PolicyActionType.REROUTE

    def test_no_goal_no_reroute(self, engine):
        ds = DialogueState()
        action = engine.decide(ds, "换一个")
        assert action.action == PolicyActionType.EXECUTE


# ═══════════════════════════════════════════════════
# 4. FILL_FROM_DST — 指代补槽
# ═══════════════════════════════════════════════════


class TestFillFromDST:
    def test_coreference_destination(self, engine):
        ds = _make_ds(
            entities={"destination": "天府广场"},
        )
        action = engine.decide(ds, "去那里")
        assert action.action == PolicyActionType.FILL_FROM_DST
        assert action.entities["destination"] == "天府广场"

    def test_coreference_poi(self, engine):
        ds = _make_ds(
            entities={"poi": "海底捞火锅(春熙路店)"},
        )
        action = engine.decide(ds, "去那儿")
        assert action.action == PolicyActionType.FILL_FROM_DST
        assert action.entities["poi"] == "海底捞火锅(春熙路店)"

    def test_coreference_from_goal_slot(self, engine):
        ds = _make_ds(
            goals=[_nav_goal(slots={"destination": "重庆"})],
        )
        action = engine.decide(ds, "去那个")
        assert action.action == PolicyActionType.FILL_FROM_DST
        assert action.entities["destination"] == "重庆"

    def test_no_entity_no_fill(self, engine):
        ds = DialogueState()
        action = engine.decide(ds, "去那里")
        assert action.action == PolicyActionType.EXECUTE

    def test_explicit_destination_not_fill(self, engine):
        ds = _make_ds(
            entities={"destination": "天府广场"},
        )
        action = engine.decide(ds, "去天府广场")
        assert action.action == PolicyActionType.EXECUTE


# ═══════════════════════════════════════════════════
# 5. EXPLAIN
# ═══════════════════════════════════════════════════


class TestExplain:
    def test_why_route(self, engine):
        ds = _make_ds(
            goals=[_nav_goal(last_result={"distance": "300km", "toll": "165元"})],
        )
        action = engine.decide(ds, "为什么走这条")
        assert action.action == PolicyActionType.EXPLAIN
        assert "toll" in action.entities

    def test_how_to_go(self, engine):
        ds = _make_ds(
            goals=[_nav_goal(last_result={"distance": "300km"})],
        )
        action = engine.decide(ds, "怎么回事")
        assert action.action == PolicyActionType.EXPLAIN

    def test_no_result_no_explain(self, engine):
        ds = _make_ds(
            goals=[_nav_goal(last_result=None)],
        )
        action = engine.decide(ds, "为什么")
        assert action.action == PolicyActionType.EXECUTE


# ═══════════════════════════════════════════════════
# 0. RETRY_LIMIT
# ═══════════════════════════════════════════════════


class TestRetryLimit:
    def test_three_attempts(self, engine):
        ds = _make_ds(goals=[_nav_goal(attempt=3)])
        action = engine.decide(ds, "再试一次")
        assert action.action == PolicyActionType.ABANDON
        assert "重试" in action.reason

    def test_two_attempts_ok(self, engine):
        ds = _make_ds(goals=[_nav_goal(attempt=2)])
        action = engine.decide(ds, "再试一次")
        assert action.action == PolicyActionType.EXECUTE

    def test_retry_limit_highest_priority(self, engine):
        """retry_limit 比 abandon 关键词优先级更高"""
        ds = _make_ds(goals=[_nav_goal(attempt=3, last_result={"toll": "100元"})])
        action = engine.decide(ds, "太贵了")
        # attempt=3 触发 retry_limit ABANDON，不触发 reroute
        assert action.action == PolicyActionType.ABANDON


# ═══════════════════════════════════════════════════
# 优先级验证
# ═══════════════════════════════════════════════════


class TestPriority:
    def test_abandon_beats_reroute(self, engine):
        """用户说'算了太贵了' → ABANDON 优先"""
        ds = _make_ds(
            goals=[_nav_goal(last_result={"toll": "165元"})],
        )
        action = engine.decide(ds, "算了太贵了不去了")
        assert action.action == PolicyActionType.ABANDON

    def test_reroute_beats_fill(self, engine):
        """嫌贵 + 指代词 → REROUTE 优先（因为 REROUTE 保留 destination）"""
        ds = _make_ds(
            attitude=UserAttitude.UNSATISFIED,
            entities={"destination": "重庆"},
            goals=[_nav_goal(last_result={"toll": "165元"})],
        )
        action = engine.decide(ds, "太贵了换那条")
        assert action.action == PolicyActionType.REROUTE

    def test_fill_beats_explain(self, engine):
        """指代词 + 为什么 → FILL 优先"""
        ds = _make_ds(
            entities={"destination": "天府广场"},
            goals=[_nav_goal(last_result={"distance": "10km"})],
        )
        action = engine.decide(ds, "去那里为什么")
        assert action.action == PolicyActionType.FILL_FROM_DST


# ═══════════════════════════════════════════════════
# 序列化
# ═══════════════════════════════════════════════════


class TestSerialization:
    def test_roundtrip(self):
        original = PolicyAction(
            action=PolicyActionType.REROUTE,
            reason="嫌贵",
            slot_overrides={"route_type": "avoid_toll"},
            entities={"destination": "重庆"},
            reply_template="",
        )
        d = original.to_dict()
        restored = PolicyAction.from_dict(d)
        assert restored.action == PolicyActionType.REROUTE
        assert restored.reason == "嫌贵"
        assert restored.slot_overrides == {"route_type": "avoid_toll"}
        assert restored.entities == {"destination": "重庆"}

    def test_to_dict_values(self):
        action = PolicyAction(action=PolicyActionType.ABANDON, reply_template="已取消")
        d = action.to_dict()
        assert d["action"] == "abandon"
        assert d["reply_template"] == "已取消"
