"""
project1_cabin_agent/nodes/policy.py — 通用对话策略引擎

职责：
  - 通用规则（ABANDON、retry_limit）— 所有域共享
  - 从 registry 收集 per-domain 规则 — 按优先级拼接执行
  - 不包含任何 skill 域的业务知识

解耦原则：
  1. 变更频率：通用规则 vs 域规则变更节奏不同 → 隔离
  2. 替换可能：将来换 LLM policy 时只换规则来源
  3. 测试独立：通用引擎测通用逻辑，域规则在 skill 测
  5. 影响范围：加 parking 策略只改 skills/parking/，不动本文件
"""

from __future__ import annotations

from enum import Enum

from project1_cabin_agent.nodes.dialogue_state import (
    DialogueState,
)


# ═══════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════


class PolicyActionType(str, Enum):
    EXECUTE = "execute"
    REROUTE = "reroute"
    FILL_FROM_DST = "fill_from_dst"
    ABANDON = "abandon"
    EXPLAIN = "explain"


class PolicyAction:
    """策略动作"""

    __slots__ = ("action", "reason", "slot_overrides", "entities", "reply_template")

    def __init__(
        self,
        action: PolicyActionType,
        reason: str = "",
        slot_overrides: dict | None = None,
        entities: dict | None = None,
        reply_template: str = "",
    ):
        self.action = action
        self.reason = reason
        self.slot_overrides = slot_overrides or {}
        self.entities = entities or {}
        self.reply_template = reply_template

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "slot_overrides": self.slot_overrides,
            "entities": self.entities,
            "reply_template": self.reply_template,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PolicyAction:
        return cls(
            action=PolicyActionType(d["action"]),
            reason=d.get("reason", ""),
            slot_overrides=d.get("slot_overrides", {}),
            entities=d.get("entities", {}),
            reply_template=d.get("reply_template", ""),
        )


# ═══════════════════════════════════════════════════
# 通用关键词（所有域共享的放弃/追问词）
# ═══════════════════════════════════════════════════

_ABANDON_WORDS = {"算了", "不去了", "取消", "不要了", "别去了", "取消导航"}


def _has_any(user_input: str, words: set[str]) -> bool:
    return any(w in user_input for w in words)


# ═══════════════════════════════════════════════════
# 通用规则（不依赖任何 skill 域）
# ═══════════════════════════════════════════════════


def _rule_retry_limit(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """连续失败 ≥ 3 → 放弃"""
    if ds.consecutive_failures < 3:
        return None
    return PolicyAction(
        action=PolicyActionType.ABANDON,
        reason=f"连续失败 {ds.consecutive_failures} 次，自动放弃",
        reply_template="抱歉，多次尝试未成功，已取消",
    )


def _rule_abandon(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """用户明确放弃"""
    if not _has_any(user_input, _ABANDON_WORDS):
        return None

    goal = ds.get_primary_goal()
    goal_name = ""
    if goal and goal.slots:
        # 不硬编码字段名，取 slots 的第一个值作为描述
        goal_name = next(iter(goal.slots.values()), "")

    reply = f"好的，已取消{goal_name}" if goal_name else "好的，已取消"
    return PolicyAction(
        action=PolicyActionType.ABANDON,
        reason="用户明确放弃",
        reply_template=reply,
    )


# ═══════════════════════════════════════════════════
# PolicyEngine
# ═══════════════════════════════════════════════════


class PolicyEngine:
    """
    通用策略引擎。

    规则链 = 通用规则（retry_limit, abandon）
           + per-domain 规则（从 registry 收集）

    域规则在 skills/{domain}/policy_rules.py 声明，
    registry 自动发现并拼接。
    """

    def __init__(self) -> None:
        self._rules: list | None = None

    def _get_rules(self) -> list:
        """延迟加载规则链（通用 + 域规则）"""
        if self._rules is None:
            from project1_cabin_agent.skills.registry import registry

            self._rules = [
                _rule_retry_limit,  # 通用：连续失败
                _rule_abandon,  # 通用：明确放弃
            ] + registry.get_all_policy_rules()  # per-domain
        return self._rules

    def decide(self, ds: DialogueState, user_input: str) -> PolicyAction:
        """
        执行规则链，返回第一个命中的 PolicyAction。
        无命中则返回 EXECUTE。
        """
        for rule in self._get_rules():
            action = rule(ds, user_input)
            if action is not None:
                return action
        return PolicyAction(action=PolicyActionType.EXECUTE)
