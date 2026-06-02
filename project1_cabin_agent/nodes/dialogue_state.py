"""
nodes/dialogue_state.py — 对话状态追踪（DST）

维护结构化对话状态，替代"从历史消息推理上下文"。

对标：
- Rasa CALM Dialogue Understanding
- MemoryOS 的 get_response() 上下文组装

关键概念：
- ActiveGoal: 用户当前在做什么（导航/搜索/空调...）
- UserAttitude: 用户态度（影响 Policy 决策）
- DialogueState: 完整对话状态，每轮更新，checkpoint 持久化
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class UserAttitude(str, Enum):
    """用户态度 — 影响 Policy 决策"""

    NEUTRAL = "neutral"
    SATISFIED = "satisfied"  # "好的""谢谢""不错"
    UNSATISFIED = "unsatisfied"  # "太贵了""不好用""太远了"
    WANTS_ALTERNATIVE = "wants_alternative"  # "有别的方案吗""换个""其他路线"
    CONFUSED = "confused"  # "什么意思""你说啥"
    CORRECTING = "correcting"  # "不是，我是说..."


class ActiveGoal(BaseModel):
    """当前活跃目标 — 对话在做什么"""

    goal_type: str = ""  # "navigate" / "search" / "climate" / ...
    slots: dict[str, Any] = {}  # 当前轮已收集的槽位
    attempt_count: int = 0  # 尝试次数（重复执行同一目标）
    last_result: dict[str, Any] | None = None  # 上次工具返回的结果
    status: str = "active"  # active / completed / abandoned


class DialogueState(BaseModel):
    """
    对话状态 — 每轮更新，checkpoint 持久化。

    存储在 state.dialogue_state，跨轮保留。
    由 ContextBuilder 每轮重建。
    """

    # ── 当前对话 ──
    active_goals: list[ActiveGoal] = []
    user_attitude: UserAttitude = UserAttitude.NEUTRAL
    turn_count: int = 0
    last_system_action: str = ""  # "navigated" / "searched" / "ac_adjusted" / ...

    # ── 历史摘要 ──
    intent_history: list[str] = []
    key_entities: dict[str, str] = {}

    # ── 策略信号 ──
    consecutive_failures: int = 0
    pending_proposal: str | None = None

    # ── 记忆摘要（从 MemoryManager 加载）──
    active_preferences: list[dict[str, Any]] = []
    frequent_destinations: list[dict[str, Any]] = []

    # ── 便捷方法 ──

    def get_primary_goal(self) -> ActiveGoal | None:
        """获取主要活跃目标"""
        active = [g for g in self.active_goals if g.status == "active"]
        return active[0] if active else None

    def get_goal_by_type(self, goal_type: str) -> ActiveGoal | None:
        """按类型获取活跃目标"""
        for g in self.active_goals:
            if g.goal_type == goal_type and g.status == "active":
                return g
        return None

    def is_repeating(self, window: int = 3) -> bool:
        """最近 N 轮是否同一意图"""
        if len(self.intent_history) < window:
            return False
        return len(set(self.intent_history[-window:])) == 1

    def get_entity(self, key: str) -> str | None:
        """获取关键实体（优先级：本轮 key_entities > active_goal.slots）"""
        if key in self.key_entities:
            return self.key_entities[key]
        goal = self.get_primary_goal()
        if goal and key in goal.slots:
            return goal.slots[key]
        return None
