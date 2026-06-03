"""
project1_cabin_agent/skills/climate/retry_rules.py — Climate 域重试策略

Climate 工具是纯函数/硬件指令，几乎不会失败。
唯一场景：硬件指令失败时给更友好的提示。
"""

from __future__ import annotations

from project1_cabin_agent.nodes.retry import ErrorKind, RetryAction


def rule_climate_friendly_error(
    intent: str,
    error_kind: ErrorKind,
    error: str,
    tool_result: dict,
    slots: dict,
) -> RetryAction | None:
    """climate 失败 → 友好提示（不重试，硬件指令重试无意义）"""
    if intent not in ("ac_control", "window_control", "light_control", "seat_control"):
        return None

    messages = {
        "ac_control": "空调控制遇到问题，请稍后再试",
        "window_control": "车窗控制遇到问题，请稍后再试",
        "light_control": "灯光控制遇到问题，请稍后再试",
        "seat_control": "座椅控制遇到问题，请稍后再试",
    }

    return RetryAction(
        action="friendly_error",
        friendly_message=messages.get(intent, "操作遇到问题，请稍后再试"),
        error_kind=error_kind,
        reason=f"climate {intent} 失败，不重试",
    )


# ── 导出 ──

CLIMATE_RETRY_RULES = [
    rule_climate_friendly_error,
]
