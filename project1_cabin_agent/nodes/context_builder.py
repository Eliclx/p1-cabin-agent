"""
nodes/context_builder.py — 对话状态构建器

数据流：
  state + MemoryManager → DialogueState → 摘要文本 → 注入 LLM

对标：
- Rasa CALM Dialogue Understanding
- MemoryOS 的 get_response() 上下文组装

职责：
1. 从 CabinAgentState + MemoryManager 构建 DialogueState
2. 生成结构化摘要注入 LLM prompt（替代"让 LLM 从 30 条历史推理上下文"）
3. 推断用户态度（不满/想换方案/困惑）
"""

from __future__ import annotations


from project1_cabin_agent.memory.manager import MemoryManager
from project1_cabin_agent.nodes.dialogue_state import (
    ActiveGoal,
    DialogueState,
    UserAttitude,
)
from project1_cabin_agent.skills.registry import get_domain_for_intent


# ── 态度推断词表（按优先级，长匹配优先）──

_ATTITUDE_RULES: list[tuple[list[str], UserAttitude]] = [
    # WANTS_ALTERNATIVE（最优先，因为通常包含不满信号 + 换方案请求）
    (
        [
            "有其他方案",
            "有没有别的",
            "换个",
            "换条",
            "换种",
            "其他路线",
            "免费的路线",
            "别走高速",
            "别走收费",
            "别的方案",
        ],
        UserAttitude.WANTS_ALTERNATIVE,
    ),
    # UNSATISFIED
    (
        [
            "太贵",
            "太远",
            "太慢",
            "不好",
            "不行",
            "不好用",
            "不满意",
            "好贵",
            "收费太高",
            "太长了",
            "不合适",
        ],
        UserAttitude.UNSATISFIED,
    ),
    # CONFUSED
    (
        ["什么意思", "你说啥", "不明白", "啥意思", "啥玩意"],
        UserAttitude.CONFUSED,
    ),
    # CORRECTING
    (
        ["不是，我是说", "我说的是", "不对，我要", "不是这个"],
        UserAttitude.CORRECTING,
    ),
    # SATISFIED
    (
        ["好的", "谢谢", "不错", "可以", "行吧", "就这样"],
        UserAttitude.SATISFIED,
    ),
]

# ── task_results intent → goal_type 映射 ──

# intent → goal_type 由 SkillRegistry 的 get_domain_for_intent() 统一提供（SSOT）


class ContextBuilder:
    """
    对话状态构建器。

    用法：
        builder = ContextBuilder(memory)
        ds = builder.build_state(state)
        summary = builder.generate_summary(ds)
        # summary 注入 LLM prompt
    """

    def __init__(self, memory: MemoryManager):
        self.memory = memory

    def build_state(self, state: dict) -> DialogueState:
        """
        从 CabinAgentState 构建 DialogueState。

        步骤：
        1. 读取上一轮 dialogue_state（checkpoint 持久化）
        2. 更新 turn_count
        3. 从 user_input 推断 user_attitude
        4. 从 task_results 更新 active_goals
        5. 从 MemoryManager 加载活跃偏好和高频地点
        6. 检测策略信号
        """
        # 1. 读取上一轮
        prev = state.get("dialogue_state")
        ds = (
            DialogueState(**prev)
            if isinstance(prev, dict) and prev
            else DialogueState()
        )

        user_input = state.get("user_input", "")

        # 2. turn_count
        ds.turn_count += 1

        # 3. 态度推断
        ds.user_attitude = _infer_attitude(user_input)

        # 4. 从 task_results 更新 active_goals
        task_results = state.get("task_results", [])
        ds = self._update_goals(ds, task_results)

        # 5. 更新意图历史
        sub_tasks = state.get("sub_tasks", [])
        for t in sub_tasks:
            intent = t.get("intent", "")
            if intent and intent not in ("chitchat", "clarify", "direct_answer"):
                ds.intent_history.append(intent)
        ds.intent_history = ds.intent_history[-10:]  # 保留最近 10 轮

        # 6. 从 MemoryManager 加载记忆摘要
        try:
            prefs = self.memory.get_active_preferences(top_k=5)
            ds.active_preferences = [
                {"key": p.key, "value": p.value, "score": round(p.heat, 2)}
                for p in prefs
                if p.heat > 0.5  # 过滤几乎无用的偏好
            ]
        except Exception:
            ds.active_preferences = []

        try:
            freq = self.memory.get_frequent_destinations(top_k=3)
            ds.frequent_destinations = [
                {"name": f.name, "count": f.visit_count}
                for f in freq
                if f.visit_count >= 3  # 至少去过 3 次
            ]
        except Exception:
            ds.frequent_destinations = []

        return ds

    def generate_summary(self, ds: DialogueState) -> str:
        """
        生成注入 LLM prompt 的结构化摘要。

        关键：不是把所有数据都塞给 LLM，而是精选"当前对话需要知道的"。
        """
        lines: list[str] = []

        # ── 对话状态 ──
        goal = ds.get_primary_goal()
        has_state = goal or ds.user_attitude != UserAttitude.NEUTRAL

        if has_state:
            lines.append("[对话状态]")

            if goal:
                dest = goal.slots.get("destination", "")
                lines.append(
                    f"- 当前目标: {goal.goal_type}" + (f" → {dest}" if dest else "")
                )
                if goal.attempt_count > 1:
                    lines.append(f"- 已尝试 {goal.attempt_count} 次")

                if goal.last_result:
                    info_parts = []
                    for k in ("distance", "toll", "duration"):
                        v = goal.last_result.get(k)
                        if v:
                            info_parts.append(f"{k}={v}")
                    if info_parts:
                        lines.append(f"- 上次结果: {', '.join(info_parts)}")

            if ds.user_attitude != UserAttitude.NEUTRAL:
                lines.append(f"- 用户态度: {ds.user_attitude.value}")

            # 策略提示
            if (
                ds.user_attitude
                in (
                    UserAttitude.UNSATISFIED,
                    UserAttitude.WANTS_ALTERNATIVE,
                )
                and goal
                and goal.goal_type
                in ("map", "navigate")  # registry 返回 map，兜底 navigate
            ):
                lines.append(
                    "- 🔄 用户需要换方案，请考虑设置 route_type=avoid_toll/avoid_highway"
                )

            if ds.is_repeating():
                lines.append("- ⚠️ 用户可能在重复同一意图")

        # ── 用户偏好 ──
        if ds.active_preferences:
            if not has_state:
                lines.append("[对话状态]")
            pref_parts = [
                f"{p['key']}={p['value']}(热度{p['score']:.0f})"
                for p in ds.active_preferences[:5]
            ]
            lines.append(f"- 用户偏好: {', '.join(pref_parts)}")

        # ── 高频地点 ──
        if ds.frequent_destinations:
            if not has_state and not ds.active_preferences:
                lines.append("[对话状态]")
            dest_parts = [
                f"{d['name']}({d['count']}次)" for d in ds.frequent_destinations[:3]
            ]
            lines.append(f"- 常去地点: {', '.join(dest_parts)}")

        if not lines:
            return ""

        return "\n".join(lines)

    def _update_goals(
        self, ds: DialogueState, task_results: list[dict]
    ) -> DialogueState:
        """从 task_results 更新 active_goals"""
        if not task_results:
            return ds

        for r in task_results[-5:]:  # 只看最近 5 条
            intent = r.get("intent", "")
            goal_type = get_domain_for_intent(intent)
            if not goal_type:
                continue

            tool_result = r.get("tool_result", {})
            status = r.get("status", "done")

            # 查找已有 goal
            existing = ds.get_goal_by_type(goal_type)

            if existing:
                # 更新已有 goal
                existing.attempt_count += 1
                if status == "done" and tool_result:
                    existing.last_result = _extract_result_data(tool_result)
                    existing.slots.update(_extract_slots_from_result(tool_result))
                    ds.last_system_action = f"{goal_type}_executed"

                if status == "error":
                    ds.consecutive_failures += 1
                else:
                    ds.consecutive_failures = 0

                # 更新 key_entities
                for k in ("destination", "keyword", "city", "route_type"):
                    if k in existing.slots and existing.slots[k]:
                        ds.key_entities[k] = existing.slots[k]
            else:
                # 新建 goal
                new_goal = ActiveGoal(
                    goal_type=goal_type,
                    attempt_count=1,
                    status="active",
                )
                if status == "done" and tool_result:
                    new_goal.last_result = _extract_result_data(tool_result)
                    new_goal.slots = _extract_slots_from_result(tool_result)
                    ds.last_system_action = f"{goal_type}_executed"

                    # 更新 key_entities
                    for k in ("destination", "keyword", "city", "route_type"):
                        if k in new_goal.slots and new_goal.slots[k]:
                            ds.key_entities[k] = new_goal.slots[k]

                ds.active_goals.append(new_goal)

                # 只保留最近 3 个活跃 goal
                active = [g for g in ds.active_goals if g.status == "active"]
                if len(active) > 3:
                    for old in active[:-3]:
                        old.status = "completed"

        # 清理 key_entities（只保留最近 10 个）
        if len(ds.key_entities) > 10:
            ds.key_entities = dict(list(ds.key_entities.items())[-10:])

        return ds


# ═══════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════


def _infer_attitude(user_input: str) -> UserAttitude:
    """从用户输入推断态度（规则驱动，0ms）"""
    text = user_input.strip()
    if not text:
        return UserAttitude.NEUTRAL

    for keywords, attitude in _ATTITUDE_RULES:
        for kw in keywords:
            if kw in text:
                return attitude

    return UserAttitude.NEUTRAL


def _extract_result_data(tool_result: dict) -> dict:
    """从 tool_result 提取关键数据"""
    if not tool_result:
        return {}

    # 优先取 data 字段（结构化数据）
    data = tool_result.get("data")
    if isinstance(data, dict):
        return {
            k: v
            for k, v in data.items()
            if k
            in (
                "destination",
                "distance",
                "toll",
                "duration",
                "route_type",
                "keyword",
                "results",
                "count",
                "city",
                "weather",
                "temperature",
            )
        }

    # 兜底：直接从 tool_result 提取
    return {
        k: v
        for k, v in tool_result.items()
        if k
        in (
            "destination",
            "distance",
            "toll",
            "duration",
            "route_type",
            "keyword",
            "results",
            "count",
            "city",
            "weather",
            "temperature",
        )
    }


def _extract_slots_from_result(tool_result: dict) -> dict:
    """从 tool_result 提取可用于回填的槽位"""
    result = _extract_result_data(tool_result)
    slots = {}
    # 目的地的回填
    if "destination" in result:
        slots["destination"] = result["destination"]
    return slots
