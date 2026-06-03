"""
project1_cabin_agent/skills/climate/proactive_rules.py — Climate 域主动规则
"""

from __future__ import annotations

from project1_cabin_agent.nodes.proactive import ProactiveContext, ProactiveSuggestion


def rule_hot_no_ac(ctx: ProactiveContext) -> ProactiveSuggestion | None:
    """
    车外温度 > 35° + 空调关 + 车速 > 0（在行驶）→ 建议开空调（priority=1）
    """
    snap = ctx.vehicle_snapshot
    if not snap:
        return None

    cabin_temp = snap.get("temperature", 20)
    ac_on = snap.get("ac_on", True)
    speed = snap.get("speed", 0)

    # 车内温度高 + 空调关 + 在行驶
    if cabin_temp <= 35 or ac_on or speed <= 0:
        return None

    return ProactiveSuggestion(
        rule_name="climate_hot_no_ac",
        domain="climate",
        priority=1,
        message=f"车内温度{cabin_temp:.0f}度有点高，要开空调吗？",
    )


def rule_cold_no_heat(ctx: ProactiveContext) -> ProactiveSuggestion | None:
    """
    车内温度 < 10° + 座椅加热关 + 在行驶 → 建议开暖风（priority=3）
    """
    snap = ctx.vehicle_snapshot
    if not snap:
        return None

    cabin_temp = snap.get("temperature", 20)
    seat_heat = snap.get("seat_heat_level", 0)
    ac_on = snap.get("ac_on", False)
    speed = snap.get("speed", 0)

    if cabin_temp >= 10 or seat_heat > 0 or ac_on or speed <= 0:
        return None

    return ProactiveSuggestion(
        rule_name="climate_cold_no_heat",
        domain="climate",
        priority=3,
        message=f"车内只有{cabin_temp:.0f}度，要开暖风或座椅加热吗？",
    )


# ═══════════════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════════════

CLIMATE_PROACTIVE_RULES = [
    rule_hot_no_ac,
    rule_cold_no_heat,
]
