"""
project1_cabin_agent/nodes/policy.py — 对话策略引擎

基于 DST 信号做确定性决策，减少对 LLM 的依赖。
规则链按优先级执行，第一条命中即返回。

设计原则：
  - 规则优先：能用规则解决的绝不等 LLM
  - 不改 graph.py 拓扑：在 intent_classifier 内部调用
  - 和 carry-over 配合：carry-over 处理明确值，Policy 处理指代/兜底
"""

from __future__ import annotations

from enum import Enum

from project1_cabin_agent.nodes.dialogue_state import (
    DialogueState,
    UserAttitude,
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
    """策略动作 — 不用 dataclass 保持和项目风格一致"""

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
# 指代词检测
# ═══════════════════════════════════════════════════

_COREFERENCE_WORDS = {"那里", "那儿", "那边", "那个", "那里", "那家", "第二", "第三个"}

_CHANGE_WORDS = {"换一个", "换一条", "换条", "换条路", "换一条路", "换个"}

_EXPLAIN_WORDS = {"为什么", "怎么回事", "为啥", "怎么走"}

_ABANDON_WORDS = {"算了", "不去了", "取消", "不要了", "别去了", "取消导航"}

_COST_WORDS = {"太贵了", "太贵", "贵了", "过路费太高", "费太高", "不想交"}

_DISTANCE_WORDS = {"太远了", "太远", "远了一", "太绕", "绕路"}

_TIME_WORDS = {"太慢了", "太慢", "太久", "太长了", "时间太长"}


def _has_any(user_input: str, words: set[str]) -> bool:
    return any(w in user_input for w in words)


# ═══════════════════════════════════════════════════
# 规则实现
# ═══════════════════════════════════════════════════


def _rule_abandon(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """优先级 1: 用户明确放弃"""
    if not _has_any(user_input, _ABANDON_WORDS):
        return None

    goal = ds.get_primary_goal()
    goal_name = ""
    if goal and goal.slots:
        goal_name = goal.slots.get("destination", "") or goal.slots.get("keyword", "")

    reply = f"好的，已取消{goal_name}" if goal_name else "好的，已取消"
    return PolicyAction(
        action=PolicyActionType.ABANDON,
        reason="用户明确放弃",
        reply_template=reply,
    )


def _rule_reroute_cost(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """优先级 2: 用户嫌贵 + 有过路费 → 避高速"""
    goal = ds.get_primary_goal()
    if not goal or not goal.last_result:
        return None

    # 检查态度或关键词
    is_unhappy = ds.user_attitude in (
        UserAttitude.UNSATISFIED,
        UserAttitude.WANTS_ALTERNATIVE,
    )
    has_cost_complaint = _has_any(user_input, _COST_WORDS)

    if not (is_unhappy or has_cost_complaint):
        return None

    last = goal.last_result
    toll_val = last.get("toll", "")
    has_toll = bool(toll_val and toll_val not in ("0", "0元", "免费"))
    if not has_toll:
        return None

    # 保留 destination（从 goal slots 或 key_entities 取）
    dest = goal.slots.get("destination", "") or ds.get_entity("destination") or ""
    overrides = {"route_type": "avoid_toll"}
    if dest:
        overrides["destination"] = dest

    return PolicyAction(
        action=PolicyActionType.REROUTE,
        reason=f"用户不满意过路费({last.get('toll', '')})，改走免费路线",
        slot_overrides=overrides,
    )


def _rule_reroute_distance(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """优先级 2b: 用户嫌远 → 最短路线"""
    goal = ds.get_primary_goal()
    if not goal or not goal.last_result:
        return None

    has_dist_complaint = _has_any(user_input, _DISTANCE_WORDS)
    if not has_dist_complaint:
        return None

    dest = goal.slots.get("destination", "") or ds.get_entity("destination") or ""
    overrides = {"route_type": "shortest"}
    if dest:
        overrides["destination"] = dest

    return PolicyAction(
        action=PolicyActionType.REROUTE,
        reason="用户嫌远，改走最短路线",
        slot_overrides=overrides,
    )


def _rule_reroute_time(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """优先级 2c: 用户嫌慢 → 最快路线"""
    goal = ds.get_primary_goal()
    if not goal or not goal.last_result:
        return None

    has_time_complaint = _has_any(user_input, _TIME_WORDS)
    if not has_time_complaint:
        return None

    dest = goal.slots.get("destination", "") or ds.get_entity("destination") or ""
    overrides = {"route_type": "fastest"}
    if dest:
        overrides["destination"] = dest

    return PolicyAction(
        action=PolicyActionType.REROUTE,
        reason="用户嫌慢，改走最快路线",
        slot_overrides=overrides,
    )


def _rule_reroute_general(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """优先级 3: 用户不满 + 换一条（通用）"""
    if not _has_any(user_input, _CHANGE_WORDS):
        return None

    goal = ds.get_primary_goal()
    if not goal:
        return None

    dest = goal.slots.get("destination", "") or ds.get_entity("destination") or ""
    overrides = {}
    if dest:
        overrides["destination"] = dest

    return PolicyAction(
        action=PolicyActionType.REROUTE,
        reason="用户要求换方案",
        slot_overrides=overrides,
    )


def _rule_fill_from_dst(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """优先级 4: 指代词 + DST 有实体 → 从 DST 补槽"""
    if not _has_any(user_input, _COREFERENCE_WORDS):
        return None

    # 从 DST 取实体
    entities = {}
    for key in ("destination", "poi", "city", "location", "keyword"):
        val = ds.get_entity(key)
        if val:
            entities[key] = val

    if not entities:
        return None

    return PolicyAction(
        action=PolicyActionType.FILL_FROM_DST,
        reason=f"指代词匹配，从 DST 填充: {entities}",
        entities=entities,
    )


def _rule_explain(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """优先级 5: 追问为什么 + 有结果 → 解释"""
    if not _has_any(user_input, _EXPLAIN_WORDS):
        return None

    goal = ds.get_primary_goal()
    if not goal or not goal.last_result:
        return None

    return PolicyAction(
        action=PolicyActionType.EXPLAIN,
        reason="用户追问原因",
        entities=goal.last_result,
    )


def _rule_retry_limit(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """优先级 0: 连续失败 ≥ 3 → 放弃（只计 error，不计成功）"""
    if ds.consecutive_failures < 3:
        return None

    return PolicyAction(
        action=PolicyActionType.ABANDON,
        reason=f"连续失败 {ds.consecutive_failures} 次，自动放弃",
        reply_template="抱歉，多次尝试未成功，已取消",
    )


# ═══════════════════════════════════════════════════
# PolicyEngine
# ═══════════════════════════════════════════════════


class PolicyEngine:
    """
    规则链对话策略引擎。

    用法：
        engine = PolicyEngine()
        action = engine.decide(ds, user_input)
        if action.action != PolicyActionType.EXECUTE:
            # 按 action 调整后续流程
    """

    def __init__(self) -> None:
        # 优先级从高到低
        self._rules = [
            _rule_retry_limit,  # 0: 连续失败放弃
            _rule_abandon,  # 1: 用户明确放弃
            _rule_reroute_cost,  # 2: 嫌贵 → 避高速
            _rule_reroute_distance,  # 2b: 嫌远 → 最短
            _rule_reroute_time,  # 2c: 嫌慢 → 最快
            _rule_reroute_general,  # 3: 换一条
            _rule_fill_from_dst,  # 4: 指代补槽
            _rule_explain,  # 5: 追问解释
        ]

    def decide(self, ds: DialogueState, user_input: str) -> PolicyAction:
        """
        执行规则链，返回第一个命中的 PolicyAction。
        无命中则返回 EXECUTE（正常执行）。
        """
        for rule in self._rules:
            action = rule(ds, user_input)
            if action is not None:
                return action
        return PolicyAction(action=PolicyActionType.EXECUTE)
