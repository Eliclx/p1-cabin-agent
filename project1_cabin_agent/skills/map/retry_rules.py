"""
project1_cabin_agent/skills/map/retry_rules.py — Map 域重试策略

地图工具依赖外部 API，最容易失败：
  - search_poi 空结果 → 扩大搜索半径
  - navigate/geocode 超时 → 延长超时
  - API 网络错误 → 同参数重试
"""

from __future__ import annotations

from project1_cabin_agent.nodes.retry import ErrorKind, RetryAction


def rule_search_poi_expand_radius(
    intent: str,
    error_kind: ErrorKind,
    error: str,
    tool_result: dict,
    slots: dict,
) -> RetryAction | None:
    """search_poi 空结果 → 扩大半径 3 倍重试"""
    if intent != "search_poi":
        return None
    if error_kind != ErrorKind.EMPTY_RESULT:
        return None

    old_radius = slots.get("radius", 3000)
    new_radius = old_radius * 3

    return RetryAction(
        action="retry",
        modified_slots={"radius": new_radius},
        error_kind=error_kind,
        reason=f"空结果，扩大搜索半径 {old_radius}→{new_radius}",
    )


def rule_api_timeout_retry(
    intent: str,
    error_kind: ErrorKind,
    error: str,
    tool_result: dict,
    slots: dict,
) -> RetryAction | None:
    """超时 → 同参数重试 1 次"""
    if error_kind != ErrorKind.TIMEOUT:
        return None

    # 只有 map 域的规则才会被加载，但防御性检查
    if intent not in ("navigate", "search_poi", "weather", "map_query", "geocode"):
        return None

    return RetryAction(
        action="retry",
        modified_slots={},
        error_kind=error_kind,
        reason=f"{intent} 超时，同参数重试",
    )


def rule_network_retry(
    intent: str,
    error_kind: ErrorKind,
    error: str,
    tool_result: dict,
    slots: dict,
) -> RetryAction | None:
    """网络错误 → 同参数重试 1 次"""
    if error_kind != ErrorKind.NETWORK:
        return None

    return RetryAction(
        action="retry",
        modified_slots={},
        error_kind=error_kind,
        reason=f"{intent} 网络错误，重试",
    )


def rule_geocode_invalid_input(
    intent: str,
    error_kind: ErrorKind,
    error: str,
    tool_result: dict,
    slots: dict,
) -> RetryAction | None:
    """geocode 无法解析地名 → 友好提示（不重试）"""
    if error_kind != ErrorKind.INVALID_INPUT:
        return None
    # error 可能在异常信息或 tool_result.error 里
    combined = (error or "") + (
        tool_result.get("error", "") if isinstance(tool_result, dict) else ""
    )
    if "无法解析" not in combined and "缺少" not in combined:
        return None

    return RetryAction(
        action="friendly_error",
        friendly_message="抱歉，无法识别这个地名，请换个说法",
        error_kind=error_kind,
        reason="地名无法解析，不重试",
    )


# ── 导出 ──

MAP_RETRY_RULES = [
    rule_search_poi_expand_radius,
    rule_api_timeout_retry,
    rule_network_retry,
    rule_geocode_invalid_input,
]
