"""
project1_cabin_agent/tests/test_proactive.py — Proactive Engine 测试

测试分层：
  - TestCooldownStore: 节流存储
  - TestProactiveEngine: 通用引擎（调度/节流/优先级/对话中降级）
  - TestMapProactiveRules: map 域规则
  - TestClimateProactiveRules: climate 域规则
"""

import time
from datetime import datetime
from unittest.mock import MagicMock, patch


from project1_cabin_agent.nodes.dialogue_state import (
    ActiveGoal,
    DialogueState,
)
from project1_cabin_agent.nodes.proactive import (
    CooldownStore,
    ProactiveContext,
    ProactiveEngine,
    ProactiveSuggestion,
)


# ═══════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════


def _snap(**overrides) -> dict:
    """构造车辆快照"""
    base = {
        "fuel": 68,
        "battery": 82,
        "speed": 60,
        "temperature": 32.0,
        "ac_on": False,
        "ac_temp": 24.0,
        "ac_mode": "auto",
        "seat_heat_level": 0,
    }
    base.update(overrides)
    return base


def _ctx(
    vehicle: dict | None = None,
    goals: list[ActiveGoal] | None = None,
    ds_overrides: dict | None = None,
) -> ProactiveContext:
    """构造 ProactiveContext"""
    ds_kwargs = {"active_goals": goals or []}
    if ds_overrides:
        ds_kwargs.update(ds_overrides)
    ds = DialogueState(**ds_kwargs)
    return ProactiveContext(
        dialogue_state=ds,
        vehicle_snapshot=vehicle or _snap(),
    )


# ═══════════════════════════════════════════════════
# CooldownStore
# ═══════════════════════════════════════════════════


class TestCooldownStore:
    def test_fresh_rule_not_cooled(self):
        store = CooldownStore()
        assert not store.is_cooled("rule_a", 60)

    def test_after_fired_is_cooled(self):
        store = CooldownStore()
        store.mark_fired("rule_a")
        assert store.is_cooled("rule_a", 60)

    def test_expired_cooldown(self):
        store = CooldownStore()
        store._store["rule_a"] = time.monotonic() - 100  # 100 秒前
        assert not store.is_cooled("rule_a", 60)

    def test_different_rules_independent(self):
        store = CooldownStore()
        store.mark_fired("rule_a")
        assert store.is_cooled("rule_a", 60)
        assert not store.is_cooled("rule_b", 60)


# ═══════════════════════════════════════════════════
# ProactiveEngine 调度逻辑
# ═══════════════════════════════════════════════════


def _make_rule(name: str, priority: int, should_fire: bool = True):
    """构造测试用规则"""
    def rule(ctx: ProactiveContext) -> ProactiveSuggestion | None:
        if not should_fire:
            return None
        return ProactiveSuggestion(
            rule_name=name,
            domain="test",
            priority=priority,
            message=f"suggestion from {name}",
        )
    rule.__name__ = name
    return rule


class TestProactiveEngine:
    def test_no_rules_no_suggestion(self):
        engine = ProactiveEngine()
        engine._rules = []
        ctx = _ctx()
        assert engine.check(ctx) is None

    def test_fire_one_rule(self):
        engine = ProactiveEngine()
        engine._rules = [_make_rule("r1", 3)]
        ctx = _ctx()
        result = engine.check(ctx)
        assert result is not None
        assert result.rule_name == "r1"

    def test_priority_ordering(self):
        """优先级数字小的胜出"""
        engine = ProactiveEngine()
        engine._rules = [
            _make_rule("r_low", 5),
            _make_rule("r_high", 1),
            _make_rule("r_mid", 3),
        ]
        ctx = _ctx()
        result = engine.check(ctx)
        assert result.rule_name == "r_high"

    def test_cooldown_blocks(self):
        """冷却中的规则被跳过"""
        engine = ProactiveEngine()
        engine._rules = [_make_rule("r1", 1)]
        ctx = _ctx()

        # 第一次触发
        engine.check(ctx)
        # 第二次被冷却拦住
        result = engine.check(ctx)
        assert result is None

    def test_pending_goal_blocks_low_priority(self):
        """有 pending goal 时只允许 priority=1"""
        engine = ProactiveEngine()
        engine._rules = [
            _make_rule("safety", 1),
            _make_rule("suggestion", 3),
        ]
        ctx = _ctx(goals=[ActiveGoal(goal_type="map", status="pending")])

        result = engine.check(ctx)
        assert result.rule_name == "safety"

    def test_pending_goal_blocks_all_non_safety(self):
        """有 pending goal 时 priority=3 也被拦"""
        engine = ProactiveEngine()
        engine._rules = [_make_rule("suggest", 3)]
        ctx = _ctx(goals=[ActiveGoal(goal_type="map", status="pending")])

        result = engine.check(ctx)
        assert result is None

    def test_active_goal_allows_suggestion(self):
        """active（非 pending）goal 不拦建议"""
        engine = ProactiveEngine()
        engine._rules = [_make_rule("suggest", 3)]
        ctx = _ctx(goals=[ActiveGoal(goal_type="map", status="active")])

        result = engine.check(ctx)
        assert result is not None

    def test_max_one_per_round(self):
        """每轮最多 1 条"""
        engine = ProactiveEngine()
        engine._rules = [_make_rule("r1", 1), _make_rule("r2", 1)]
        ctx = _ctx()

        result = engine.check(ctx)
        # 只返回 1 条（排序后第一条）
        assert result is not None
        # 第二条虽然也命中，但不返回
        assert result.rule_name in ("r1", "r2")


# ═══════════════════════════════════════════════════
# Map 域规则
# ═══════════════════════════════════════════════════


class TestFuelWarning:
    def test_fuel_low_navigating(self):
        from project1_cabin_agent.skills.map.proactive_rules import (
            rule_fuel_warning,
        )

        ctx = _ctx(
            vehicle=_snap(fuel=12),
            goals=[ActiveGoal(goal_type="map", status="active")],
        )
        result = rule_fuel_warning(ctx)
        assert result is not None
        assert "12%" in result.message
        assert result.priority == 1
        assert result.domain == "map"

    def test_fuel_ok_no_warning(self):
        from project1_cabin_agent.skills.map.proactive_rules import (
            rule_fuel_warning,
        )

        ctx = _ctx(
            vehicle=_snap(fuel=50),
            goals=[ActiveGoal(goal_type="map", status="active")],
        )
        assert rule_fuel_warning(ctx) is None

    def test_fuel_low_not_navigating(self):
        from project1_cabin_agent.skills.map.proactive_rules import (
            rule_fuel_warning,
        )

        ctx = _ctx(vehicle=_snap(fuel=12))
        assert rule_fuel_warning(ctx) is None

    def test_fuel_low_pending_goal(self):
        """pending 也算导航中（等用户补充槽位）"""
        from project1_cabin_agent.skills.map.proactive_rules import (
            rule_fuel_warning,
        )

        ctx = _ctx(
            vehicle=_snap(fuel=15),
            goals=[ActiveGoal(goal_type="map", status="pending")],
        )
        assert rule_fuel_warning(ctx) is None  # pending 不算 navigating


class TestFrequentDestination:
    def test_friday_evening_suggests(self):
        from project1_cabin_agent.skills.map.proactive_rules import (
            rule_frequent_destination,
        )

        mock_memory = MagicMock()
        mock_memory.get_frequent_destinations.return_value = [
            MagicMock(name="公司", count=5)
        ]

        # 周五 19:00
        mock_now = datetime(2026, 6, 5, 19, 0)  # 周五

        with patch(
            "project1_cabin_agent.skills.map.proactive_rules._get_now",
            return_value=mock_now,
        ):
            ctx = _ctx()
            ctx.get_memory = lambda: mock_memory

            result = rule_frequent_destination(ctx)
            assert result is not None
            assert "公司" in result.message
            assert result.priority == 3

    def test_monday_no_suggest(self):
        from project1_cabin_agent.skills.map.proactive_rules import (
            rule_frequent_destination,
        )

        mock_now = datetime(2026, 6, 1, 19, 0)  # 周一

        with patch(
            "project1_cabin_agent.skills.map.proactive_rules._get_now",
            return_value=mock_now,
        ):
            ctx = _ctx()
            result = rule_frequent_destination(ctx)
            assert result is None

    def test_has_active_goal_no_suggest(self):
        from project1_cabin_agent.skills.map.proactive_rules import (
            rule_frequent_destination,
        )

        mock_now = datetime(2026, 6, 5, 19, 0)  # 周五

        with patch(
            "project1_cabin_agent.skills.map.proactive_rules._get_now",
            return_value=mock_now,
        ):
            ctx = _ctx(goals=[ActiveGoal(goal_type="map", status="active")])
            result = rule_frequent_destination(ctx)
            assert result is None

    def test_few_visits_no_suggest(self):
        from project1_cabin_agent.skills.map.proactive_rules import (
            rule_frequent_destination,
        )

        mock_memory = MagicMock()
        mock_memory.get_frequent_destinations.return_value = [
            MagicMock(name="超市", count=1)
        ]

        mock_now = datetime(2026, 6, 5, 19, 0)  # 周五

        with patch(
            "project1_cabin_agent.skills.map.proactive_rules._get_now",
            return_value=mock_now,
        ):
            ctx = _ctx()
            ctx.get_memory = lambda: mock_memory
            result = rule_frequent_destination(ctx)
            assert result is None

    def test_saturday_morning_no_suggest(self):
        """周六上午 10 点不触发"""
        from project1_cabin_agent.skills.map.proactive_rules import (
            rule_frequent_destination,
        )

        mock_now = datetime(2026, 6, 6, 10, 0)  # 周六上午

        with patch(
            "project1_cabin_agent.skills.map.proactive_rules._get_now",
            return_value=mock_now,
        ):
            ctx = _ctx()
            result = rule_frequent_destination(ctx)
            assert result is None


# ═══════════════════════════════════════════════════
# Climate 域规则
# ═══════════════════════════════════════════════════


class TestHotNoAc:
    def test_hot_driving_no_ac(self):
        from project1_cabin_agent.skills.climate.proactive_rules import (
            rule_hot_no_ac,
        )

        ctx = _ctx(vehicle=_snap(temperature=38.0, ac_on=False, speed=80))
        result = rule_hot_no_ac(ctx)
        assert result is not None
        assert "38" in result.message
        assert result.priority == 1

    def test_ac_already_on(self):
        from project1_cabin_agent.skills.climate.proactive_rules import (
            rule_hot_no_ac,
        )

        ctx = _ctx(vehicle=_snap(temperature=38.0, ac_on=True, speed=80))
        assert rule_hot_no_ac(ctx) is None

    def test_not_hot(self):
        from project1_cabin_agent.skills.climate.proactive_rules import (
            rule_hot_no_ac,
        )

        ctx = _ctx(vehicle=_snap(temperature=25.0, ac_on=False, speed=80))
        assert rule_hot_no_ac(ctx) is None

    def test_parked_no_suggest(self):
        """停车时不打扰"""
        from project1_cabin_agent.skills.climate.proactive_rules import (
            rule_hot_no_ac,
        )

        ctx = _ctx(vehicle=_snap(temperature=38.0, ac_on=False, speed=0))
        assert rule_hot_no_ac(ctx) is None


class TestColdNoHeat:
    def test_cold_driving(self):
        from project1_cabin_agent.skills.climate.proactive_rules import (
            rule_cold_no_heat,
        )

        ctx = _ctx(vehicle=_snap(temperature=5.0, ac_on=False, speed=60, seat_heat_level=0))
        result = rule_cold_no_heat(ctx)
        assert result is not None
        assert "5" in result.message
        assert result.priority == 3

    def test_seat_heat_already_on(self):
        from project1_cabin_agent.skills.climate.proactive_rules import (
            rule_cold_no_heat,
        )

        ctx = _ctx(vehicle=_snap(temperature=5.0, ac_on=False, speed=60, seat_heat_level=2))
        assert rule_cold_no_heat(ctx) is None

    def test_not_cold(self):
        from project1_cabin_agent.skills.climate.proactive_rules import (
            rule_cold_no_heat,
        )

        ctx = _ctx(vehicle=_snap(temperature=15.0, ac_on=False, speed=60, seat_heat_level=0))
        assert rule_cold_no_heat(ctx) is None


# ═══════════════════════════════════════════════════
# Registry 发现
# ═══════════════════════════════════════════════════


class TestRegistryDiscovery:
    def test_map_rules_discovered(self):
        from project1_cabin_agent.skills.registry import registry
        rules = registry.get_proactive_rules("map")
        assert len(rules) == 2  # fuel_warning + frequent_destination

    def test_climate_rules_discovered(self):
        from project1_cabin_agent.skills.registry import registry
        rules = registry.get_proactive_rules("climate")
        assert len(rules) == 2  # hot_no_ac + cold_no_heat

    def test_vehicle_no_rules(self):
        from project1_cabin_agent.skills.registry import registry
        rules = registry.get_proactive_rules("vehicle")
        assert len(rules) == 0

    def test_all_rules_collected(self):
        from project1_cabin_agent.skills.registry import registry
        rules = registry.get_all_proactive_rules()
        assert len(rules) >= 4  # 2 map + 2 climate


# ═══════════════════════════════════════════════════
# 序列化
# ═══════════════════════════════════════════════════


class TestSerialization:
    def test_suggestion_to_dict(self):
        s = ProactiveSuggestion(
            rule_name="test",
            domain="map",
            priority=1,
            message="hello",
        )
        d = s.to_dict()
        assert d["rule_name"] == "test"
        assert d["priority"] == 1
