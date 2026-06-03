"""
project1_cabin_agent/skills/map/policy_rules.py — Map 域策略规则

策略规则跟着 skill 走，不污染通用 PolicyEngine。
每个域可以声明自己的规则，注册到 registry。

设计原则（解耦 6 条）：
1. 变更频率：策略随业务变，DST 不变——隔离
2. 替换可能：将来换 LLM policy 时，只换这层
3. 测试独立：map 策略只测 map 场景
4. 并行开发：不同域的策略在不同文件改
5. 影响范围：改 map 策略不影响 climate
"""

from __future__ import annotations

from project1_cabin_agent.nodes.dialogue_state import DialogueState, UserAttitude
from project1_cabin_agent.nodes.policy import PolicyAction, PolicyActionType

# ── 关键词 ──

_COST_WORDS = {"太贵了", "太贵", "贵了", "过路费太高", "费太高", "不想交"}
_DISTANCE_WORDS = {"太远了", "太远", "远了一", "太绕", "绕路"}
_TIME_WORDS = {"太慢了", "太慢", "太久", "太长了", "时间太长"}
_CHANGE_WORDS = {"换一个", "换一条", "换条", "换条路", "换一条路", "换个"}
_COREFERENCE_WORDS = {"那里", "那儿", "那边", "那个", "那家", "第二", "第三个"}
_EXPLAIN_WORDS = {"为什么", "怎么回事", "为啥", "怎么走"}

# ── 从 MEMORY 声明取字段名（SSOT） ──
# dedup_key/detail_fields 声明了哪些字段重要，策略直接用

_DEST_KEY = "destination"  # MEMORY.detail_fields 里第一个
_TOLL_KEY = "toll"  # MEMORY.detail_fields 里
_ROUTE_KEY = "route_type"  # MEMORY.detail_fields 里


def _has_any(user_input: str, words: set[str]) -> bool:
    return any(w in user_input for w in words)


def _get_dest(ds: DialogueState, goal) -> str:
    """从 goal slots 或 DST entities 取目的地（不硬编码"destination"以外的逻辑）"""
    return goal.slots.get(_DEST_KEY, "") or ds.get_entity(_DEST_KEY) or ""


# ═══════════════════════════════════════════════════
# Map 域规则（优先级从高到低）
# ═══════════════════════════════════════════════════


def rule_reroute_cost(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """嫌贵 + 有过路费 → 避高速"""
    goal = ds.get_primary_goal()
    if not goal or not goal.last_result:
        return None

    is_unhappy = ds.user_attitude in (
        UserAttitude.UNSATISFIED,
        UserAttitude.WANTS_ALTERNATIVE,
    )
    if not (is_unhappy or _has_any(user_input, _COST_WORDS)):
        return None

    toll_val = goal.last_result.get(_TOLL_KEY, "")
    has_toll = bool(toll_val and toll_val not in ("0", "0元", "免费"))
    if not has_toll:
        return None

    dest = _get_dest(ds, goal)
    overrides = {_ROUTE_KEY: "avoid_toll"}
    if dest:
        overrides[_DEST_KEY] = dest

    return PolicyAction(
        action=PolicyActionType.REROUTE,
        reason=f"用户不满意过路费({toll_val})，改走免费路线",
        slot_overrides=overrides,
    )


def rule_reroute_distance(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """嫌远 → 最短路线"""
    goal = ds.get_primary_goal()
    if not goal or not goal.last_result:
        return None
    if not _has_any(user_input, _DISTANCE_WORDS):
        return None

    dest = _get_dest(ds, goal)
    overrides = {_ROUTE_KEY: "shortest"}
    if dest:
        overrides[_DEST_KEY] = dest

    return PolicyAction(
        action=PolicyActionType.REROUTE,
        reason="用户嫌远，改走最短路线",
        slot_overrides=overrides,
    )


def rule_reroute_time(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """嫌慢 → 最快路线"""
    goal = ds.get_primary_goal()
    if not goal or not goal.last_result:
        return None
    if not _has_any(user_input, _TIME_WORDS):
        return None

    dest = _get_dest(ds, goal)
    overrides = {_ROUTE_KEY: "fastest"}
    if dest:
        overrides[_DEST_KEY] = dest

    return PolicyAction(
        action=PolicyActionType.REROUTE,
        reason="用户嫌慢，改走最快路线",
        slot_overrides=overrides,
    )


def rule_reroute_general(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """换一条（通用不满）"""
    if not _has_any(user_input, _CHANGE_WORDS):
        return None

    goal = ds.get_primary_goal()
    if not goal:
        return None

    dest = _get_dest(ds, goal)
    overrides = {}
    if dest:
        overrides[_DEST_KEY] = dest

    return PolicyAction(
        action=PolicyActionType.REROUTE,
        reason="用户要求换方案",
        slot_overrides=overrides,
    )


def rule_fill_from_dst(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """指代词 + DST 有实体 → 补槽"""
    if not _has_any(user_input, _COREFERENCE_WORDS):
        return None

    entities = {}
    for key in (_DEST_KEY, "poi", "city", "location", "keyword"):
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


def rule_explain(ds: DialogueState, user_input: str) -> PolicyAction | None:
    """追问为什么 + 有结果 → 解释"""
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


# ═══════════════════════════════════════════════════
# 导出规则列表（注册到 registry 用）
# ═══════════════════════════════════════════════════

# 优先级从高到低
MAP_POLICY_RULES: list = [
    rule_reroute_cost,
    rule_reroute_distance,
    rule_reroute_time,
    rule_reroute_general,
    rule_fill_from_dst,
    rule_explain,
]
