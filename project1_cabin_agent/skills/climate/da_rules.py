"""
project1_cabin_agent/skills/climate/da_rules.py — Climate 域 DA 规则

处理空调/车窗/灯光/座椅的纠正场景。
例如："不要制冷" → CORRECTION(mode=heat)
"""

from __future__ import annotations

import re

from project1_cabin_agent.nodes.da import DAResult, DialogueAct


def rule_climate_correction(user_input: str, context: dict) -> DAResult | None:
    """纠正空调/车窗/灯光参数"""
    text = user_input.strip()

    last_intent = context.get("last_intent", "")
    if last_intent not in (
        "ac_control",
        "window_control",
        "light_control",
        "seat_control",
    ):
        return None

    # 空调模式纠正
    if last_intent == "ac_control":
        if re.search(r"不要?制冷|别制冷|改成?制热|换制热|不要?冷风", text):
            return DAResult(
                act=DialogueAct.CORRECTION,
                corrections={"mode": "heat"},
                raw_input=text,
            )
        if re.search(r"不要?制热|别制热|改成?制冷|换制冷|不要?暖风", text):
            return DAResult(
                act=DialogueAct.CORRECTION,
                corrections={"mode": "cool"},
                raw_input=text,
            )
        if re.search(r"改成?自动|换自动|自动模式", text):
            return DAResult(
                act=DialogueAct.CORRECTION,
                corrections={"mode": "auto"},
                raw_input=text,
            )
        # 温度纠正
        m = re.search(r"(\d+)[度°]", text)
        if m and re.search(r"改|调|换|不要?|太|不够", text):
            return DAResult(
                act=DialogueAct.CORRECTION,
                corrections={"temperature": int(m.group(1))},
                raw_input=text,
            )

    # 车窗纠正（开一半/关一半）
    if last_intent == "window_control":
        m = re.search(r"(\d+)%?|一半|半", text)
        if m and re.search(r"改|调|只要|开到|关到", text):
            if m.group(1):
                percent = int(m.group(1))
            else:
                percent = 50
            return DAResult(
                act=DialogueAct.CORRECTION,
                corrections={"percent": percent},
                raw_input=text,
            )

    return None


# ── 导出 ──

CLIMATE_DA_RULES = [
    rule_climate_correction,
]
