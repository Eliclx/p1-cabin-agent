"""
project1_cabin_agent/nodes/da.py — Dialogue Act 识别引擎

DA 分类器：判断用户输入是对上一轮的"反应"还是"新意图"。

DA 类型：
  CONFIRM    — 确认（"好"/"确认"/"嗯"）
  DENY       — 否定（"不要"/"算了"/"取消"）
  CORRECTION — 纠正（"不要制冷"→改mode）
  SELECT     — 选择（"第一个"/"小龙坎"）
  SLOT_FILL  — 补槽（"成都"→origin）
  NEW_INTENT — 全新意图，不走 carry-over

架构（跟 Policy/Action 同模式）：
  nodes/da.py              — 通用引擎（规则链，per-domain 规则从 registry 加载）
  skills/{domain}/da_rules.py — per-domain 规则
  registry 自动发现         — {DOMAIN}_DA_RULES

解耦：
  引擎不知道 climate/map 的存在
  每个 skill 只处理自己的 DA 规则
  加新域只建 skills/{domain}/da_rules.py
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════


class DialogueAct(str, Enum):
    CONFIRM = "confirm"
    DENY = "deny"
    CORRECTION = "correction"
    SELECT = "select"
    SLOT_FILL = "slot_fill"
    NEW_INTENT = "new_intent"


@dataclass
class DAResult:
    """DA 分类结果"""

    act: DialogueAct
    confidence: float = 1.0  # 0-1，规则=1.0，LLM 兜底<1.0
    # CORRECTION: 要改的参数
    corrections: dict[str, Any] = field(default_factory=dict)
    # SELECT: 选中的索引或名字
    selection: dict[str, Any] = field(default_factory=dict)
    # 原始输入
    raw_input: str = ""

    def to_dict(self) -> dict:
        d = {
            "act": self.act.value,
            "confidence": self.confidence,
        }
        if self.corrections:
            d["corrections"] = self.corrections
        if self.selection:
            d["selection"] = self.selection
        d["raw_input"] = self.raw_input
        return dict(d)

    @classmethod
    def from_dict(cls, d: dict) -> DAResult:
        return cls(
            act=DialogueAct(d["act"]),
            confidence=d.get("confidence", 1.0),
            corrections=d.get("corrections", {}),
            selection=d.get("selection", {}),
            raw_input=d.get("raw_input", ""),
        )


# ═══════════════════════════════════════════════════
# 通用规则（0ms，不依赖任何域）
# ═══════════════════════════════════════════════════

_CONFIRM_PATTERNS = re.compile(
    r"^(好|好的|确认|确定|可以|行|嗯|对|是的|是|要|执行|没问题|OK|ok|嗯嗯|对对)$"
)

_DENY_PATTERNS = re.compile(
    r"^(不|不要|不用|不用了|算了|取消|别|不行|否|不要了|取消吧|算了)$"
)

_SELECT_INDEX = re.compile(
    r"^(第([一二三四五六七八九十\d]+)[个条个项]|"
    r"([一二三四五六七八九十\d]+)[号个条])$"
)

# 中文数字 → 阿拉伯数字
_CN_NUM = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4,
    "六": 5, "七": 6, "八": 7, "九": 8, "十": 9,
}


def _cn_to_index(s: str) -> int | None:
    """中文数字/阿拉伯数字 → 0-based index"""
    if s.isdigit():
        return int(s) - 1
    if s in _CN_NUM:
        return _CN_NUM[s]
    # "十一" 等
    return None


def _rule_confirm(user_input: str, context: dict) -> DAResult | None:
    """短输入确认词匹配"""
    text = user_input.strip()
    if _CONFIRM_PATTERNS.match(text):
        return DAResult(act=DialogueAct.CONFIRM, raw_input=text)
    return None


def _rule_deny(user_input: str, context: dict) -> DAResult | None:
    """短输入否定词匹配"""
    text = user_input.strip()
    if _DENY_PATTERNS.match(text):
        return DAResult(act=DialogueAct.DENY, raw_input=text)
    return None


def _rule_select_index(user_input: str, context: dict) -> DAResult | None:
    """序号选择：'第一个'、'2号'"""
    text = user_input.strip()
    m = _SELECT_INDEX.match(text)
    if m:
        # group(2) = 第X个的X, group(3) = X号个条的X
        num_str = m.group(2) or m.group(3)
        idx = _cn_to_index(num_str)
        if idx is not None:
            return DAResult(
                act=DialogueAct.SELECT,
                selection={"index": idx},
                raw_input=text,
            )
    return None


# 通用规则链（优先级：deny > confirm > select）
_GENERIC_RULES = [
    _rule_deny,
    _rule_confirm,
    _rule_select_index,
]


# ═══════════════════════════════════════════════════
# DA 引擎
# ═══════════════════════════════════════════════════


def classify_dialogue_act(
    user_input: str,
    context: dict | None = None,
) -> DAResult | None:
    """
    对用户输入做 DA 分类。

    Args:
        user_input: 用户原始输入
        context: {
            "last_intent": "ac_control",
            "last_action": {...},
            "last_tool_result": {...},
            "active_frames": [...],
            "candidates": [...],  # SELECT 候选项
        }

    Returns:
        DAResult 或 None（无法分类 → NEW_INTENT）
    """
    if context is None:
        context = {}

    # ── 1. 通用规则链（0ms）──
    for rule in _GENERIC_RULES:
        result = rule(user_input, context)
        if result:
            logger.debug(f"[DA] 通用规则 {rule.__name__} → {result.act.value}")
            return result

    # ── 2. Per-domain 规则（从 registry 加载，0ms）──
    last_domain = context.get("last_domain", "")
    if last_domain:
        try:
            from project1_cabin_agent.skills.registry import registry

            domain_rules = registry.get_da_rules(last_domain)
            for rule_fn in domain_rules:
                result = rule_fn(user_input, context)
                if result:
                    logger.debug(
                        f"[DA] 域规则 {last_domain}.{rule_fn.__name__} → {result.act.value}"
                    )
                    return result
        except Exception:
            pass

    # ── 3. 无法分类 → None（调用方视为 NEW_INTENT）──
    return None
