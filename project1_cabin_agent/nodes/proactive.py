"""
project1_cabin_agent/nodes/proactive.py — 主动引擎

职责：
  - 通用调度：收集所有域的 proactive rule，按优先级排序
  - 节流防骚扰：cooldown / 对话中降级 / 每轮上限
  - 不包含任何 skill 域的业务知识

解耦原则：
  1. 变更频率：安全规则天天变，引擎不动 → 隔离
  2. 替换可能：cooldown 存储将来可换 Redis → 抽接口
  3. 测试独立：引擎测调度/节流，域规则在 skill 测
  5. 影响范围：加 parking 主动规则只改 skills/parking/
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from project1_cabin_agent.nodes.dialogue_state import DialogueState


# ═══════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════


@dataclass
class ProactiveSuggestion:
    """主动建议"""

    rule_name: str           # 规则名（用于 cooldown 去重）
    domain: str              # "map" / "climate"
    priority: int            # 1=安全(油量低) 3=建议(常去地点) 5=闲聊
    message: str             # "油量仅剩12%，需要导航去加油站吗？"

    def to_dict(self) -> dict:
        return {
            "rule_name": self.rule_name,
            "domain": self.domain,
            "priority": self.priority,
            "message": self.message,
        }


@dataclass
class ProactiveContext:
    """
    喂给规则的上下文。

    由引擎组装，规则只读不写。
    车辆状态用 dict 而不是 VehicleState 类型，
    是为了不让 nodes/ 依赖 vehicle_state（解耦原则 3）。
    """
    dialogue_state: DialogueState
    vehicle_snapshot: dict = field(default_factory=dict)
    memory_meta: dict = field(default_factory=dict)  # {intent: memory_meta}

    def get_memory(self) -> object | None:
        """延迟获取 MemoryManager 单例（避免顶层 import）"""
        from project1_cabin_agent.memory._instance import get_memory
        return get_memory()


# ═══════════════════════════════════════════════════
# Cooldown 存储接口
# ═══════════════════════════════════════════════════


class CooldownStore:
    """
    节流存储。

    默认用内存 dict，将来可换 Redis / SQLite —— 替换可能（原则 2）。
    """

    def __init__(self) -> None:
        self._store: dict[str, float] = {}

    def is_cooled(self, rule_name: str, cooldown_sec: float) -> bool:
        """规则是否在冷却中（True=还在冷却，不触发）"""
        last = self._store.get(rule_name, 0)
        return (time.monotonic() - last) < cooldown_sec

    def mark_fired(self, rule_name: str) -> None:
        """记录触发时间"""
        self._store[rule_name] = time.monotonic()


# ═══════════════════════════════════════════════════
# ProactiveEngine
# ═══════════════════════════════════════════════════


# 优先级 → 冷却时间映射（安全类冷却短，建议类冷却长）
_PRIORITY_COOLDOWN: dict[int, float] = {
    1: 300,   # 安全类（油量低）：5 分钟
    3: 1800,  # 建议类（常去地点）：30 分钟
    5: 3600,  # 闲聊类：1 小时
}


class ProactiveEngine:
    """
    主动引擎。

    规则链从 registry 收集（跟 Policy 同模式）。
    通用调度逻辑在这里，域规则在 skills/{domain}/proactive_rules.py。
    """

    def __init__(self, cooldown_store: CooldownStore | None = None) -> None:
        self.cooldown = cooldown_store or CooldownStore()
        self._rules: list | None = None

    def _get_rules(self) -> list:
        """延迟加载域规则（从 registry）"""
        if self._rules is None:
            from project1_cabin_agent.skills.registry import registry
            self._rules = registry.get_all_proactive_rules()
        return self._rules

    def check(self, ctx: ProactiveContext) -> ProactiveSuggestion | None:
        """
        检查是否需要主动建议。

        返回优先级最高的一条（每轮最多 1 条，防骚扰）。
        对话中有 pending goal 时只允许 priority=1（安全类）。
        """
        candidates: list[ProactiveSuggestion] = []

        for rule in self._get_rules():
            suggestion = rule(ctx)
            if suggestion is None:
                continue

            # 对话中降级：有 pending goal → 只允许安全类
            has_pending = any(
                g.status == "pending"
                for g in ctx.dialogue_state.active_goals
            )
            if has_pending and suggestion.priority > 1:
                continue

            # 节流检查
            cooldown_sec = _PRIORITY_COOLDOWN.get(suggestion.priority, 1800)
            if self.cooldown.is_cooled(suggestion.rule_name, cooldown_sec):
                continue

            candidates.append(suggestion)

        if not candidates:
            return None

        # 按优先级排序（数字小 = 优先级高）
        candidates.sort(key=lambda s: s.priority)
        winner = candidates[0]

        # 标记触发
        self.cooldown.mark_fired(winner.rule_name)

        return winner
