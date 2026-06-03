"""
project1_cabin_agent/skills/map/da_rules.py — Map 域 DA 规则

处理导航/搜索的选择和纠正场景。
例如："第一个" → SELECT(index=0)
     "不要收费的" → CORRECTION(avoid_toll=True)
"""

from __future__ import annotations

import re

from project1_cabin_agent.nodes.da import DAResult, DialogueAct


def rule_map_select_by_name(user_input: str, context: dict) -> DAResult | None:
    """从候选项中按名字选择"""
    text = user_input.strip()
    last_intent = context.get("last_intent", "")
    if last_intent not in ("search_poi", "navigate"):
        return None

    candidates = context.get("candidates", [])
    if not candidates:
        return None

    # 短输入且能匹配候选项名字
    if len(text) > 8:
        return None

    for i, c in enumerate(candidates):
        name = c.get("name", "")
        if name and (text in name or name.startswith(text)):
            return DAResult(
                act=DialogueAct.SELECT,
                selection={"index": i, "name": name},
                raw_input=text,
            )

    return None


def rule_map_correction(user_input: str, context: dict) -> DAResult | None:
    """导航路线纠正"""
    text = user_input.strip()
    last_intent = context.get("last_intent", "")
    if last_intent != "navigate":
        return None

    if re.search(r"不要?收费|避开?收费|免费|不走收费", text):
        return DAResult(
            act=DialogueAct.CORRECTION,
            corrections={"avoid_toll": True},
            raw_input=text,
        )
    if re.search(r"不走高速|避开?高速|不要?高速", text):
        return DAResult(
            act=DialogueAct.CORRECTION,
            corrections={"avoid_highway": True},
            raw_input=text,
        )
    if re.search(r"最短|距离短|走近路", text):
        return DAResult(
            act=DialogueAct.CORRECTION,
            corrections={"route_type": "shortest"},
            raw_input=text,
        )
    if re.search(r"最快|时间短|赶时间", text):
        return DAResult(
            act=DialogueAct.CORRECTION,
            corrections={"route_type": "fastest"},
            raw_input=text,
        )

    return None


# ── 导出 ──

MAP_DA_RULES = [
    rule_map_select_by_name,
    rule_map_correction,
]
