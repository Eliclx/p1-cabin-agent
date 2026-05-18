"""
project1_cabin_agent/harness/context.py
AgentContext — 跨所有 harness 的统一上下文对象

设计原则：
- AgentContext 是 harness 的唯一外部数据来源（除了 slots）
- frozen 的部分（vehicle）防止 harness 意外修改
- L3 用户偏好支持延迟加载：天气 harness 不碰 L3，就不会触发 DB 查询
- 可测试：mock 一个 AgentContext 就能单测任何 harness
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# ── 车机实时状态快照 ────────────────────────────────────────────────

@dataclass(frozen=True)
class VehicleSnapshot:
    """
    车机实时状态快照（每轮注入，不入 State）。
    frozen=True：harness 只读，不能修改。
    
    注意：这里的字段是 harness 关心的子集，不是 vehicle_state.py 的完整字段。
    后续 context_enrich 节点负责从 VehicleState 转换。
    """
    location: str = ""          # "104.06,30.67"（经度,纬度）
    speed: float = 0.0          # km/h
    ac_on: bool = False
    ac_temp: float = 24.0
    ac_mode: str = "auto"
    ac_fan_level: int = 3
    window_percent: int = 0
    sunroof_percent: int = 0
    fuel: int = 68
    battery: int = 82
    temperature: float = 32.0
    light_on: bool = False
    light_brightness: int = 80
    volume: int = 50


# ── AgentContext ────────────────────────────────────────────────────

@dataclass
class AgentContext:
    """
    harness 的统一上下文对象。
    
    四层数据来源：
    - vehicle: 车机实时状态（每轮注入快照）
    - dialogue: L1 对话记忆（从 State 取）
    - session: L2 行程记忆（从 State 取）
    - user: L3 用户偏好（按需查 DB，延迟加载）
    
    使用方式：
        ctx = AgentContext(vehicle=snapshot, dialogue={...}, session={...}, ...)
        result = harness.pre_validate(slots, ctx)
    """
    vehicle: VehicleSnapshot = field(default_factory=VehicleSnapshot)
    dialogue: dict[str, Any] = field(default_factory=dict)   # L1: 实体黑板、对话历史
    session: dict[str, Any] = field(default_factory=dict)    # L2: 行程摘要、上次目的地
    user: dict[str, Any] = field(default_factory=dict)       # L3: 用户偏好（预加载或延迟加载）

    # L3 延迟加载回调（可选）
    _user_loader: Callable[[], dict[str, Any]] | None = field(default=None, repr=False)

    def get_user(self) -> dict[str, Any]:
        """
        获取 L3 用户偏好。
        如果设置了 _user_loader 且 user 为空，触发延迟加载。
        harness 不碰 L3 就不会触发 DB 查询。
        """
        if not self.user and self._user_loader is not None:
            self.user = self._user_loader()
        return self.user
