"""
project1_cabin_agent/skills/map/proactive_rules.py — Map 域主动规则

触发条件只读 ProactiveContext，不写。
业务逻辑跟着 skill 走，不污染通用 ProactiveEngine。
"""

from __future__ import annotations

from project1_cabin_agent.nodes.proactive import ProactiveContext, ProactiveSuggestion


def rule_fuel_warning(ctx: ProactiveContext) -> ProactiveSuggestion | None:
    """
    油量 < 20% + 正在导航 → 建议加油站（priority=1 安全类）
    """
    snap = ctx.vehicle_snapshot
    if not snap:
        return None

    fuel = snap.get("fuel", 100)
    if fuel >= 20:
        return None

    # 只在导航中提醒（避免用户只是听歌时骚扰）
    ds = ctx.dialogue_state
    navigating = any(
        g.goal_type == "map" and g.status == "active"
        for g in ds.active_goals
    )
    if not navigating:
        return None

    return ProactiveSuggestion(
        rule_name="map_fuel_warning",
        domain="map",
        priority=1,
        message=f"油量仅剩{fuel}%，需要在途中找个加油站吗？",
    )


def rule_frequent_destination(ctx: ProactiveContext) -> ProactiveSuggestion | None:
    """
    常去地点 ≥ 3 次 + 无活跃目标 + 周五/六晚 18-21 点 → 建议常去地（priority=3）
    """
    ds = ctx.dialogue_state
    if ds.active_goals:
        return None  # 有目标不打扰

    # 时间判断（用函数注入方便测试）
    now = _get_now()
    if now.weekday() not in (4, 5):  # 4=周五, 5=周六
        return None
    if not (18 <= now.hour < 21):
        return None

    memory = ctx.get_memory()
    if not memory:
        return None

    freq = memory.get_frequent_destinations(top_k=1)
    if not freq or freq[0].count < 3:
        return None

    place = freq[0]
    return ProactiveSuggestion(
        rule_name="map_frequent_destination",
        domain="map",
        priority=3,
        message=f"这个时间您经常去{place.name}，要去吗？",
    )


def _get_now():
    """时间获取函数，方便测试 mock"""
    from datetime import datetime
    return datetime.now()


# ═══════════════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════════════

MAP_PROACTIVE_RULES = [
    rule_fuel_warning,
    rule_frequent_destination,
]
