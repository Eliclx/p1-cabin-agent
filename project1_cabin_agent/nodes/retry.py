"""
project1_cabin_agent/nodes/retry.py — Error Recovery 引擎

同一轮内的工具失败恢复。跟 Policy 的 retry_limit 互补：
  Policy retry_limit — 跨轮保护（consecutive_failures ≥ 3 → ABANDON）
  retry — 同轮恢复（失败后改参数重试 1 次，或返回友好错误信息）

架构（跟 Policy/DA/Action 同模式）：
  nodes/retry.py              — 通用引擎（规则链 + friendly error）
  skills/{domain}/retry_rules.py — per-domain 重试策略
  registry 自动发现            — {DOMAIN}_RETRY_RULES

解耦：
  引擎不知道 climate/map 的存在
  每个 skill 只处理自己的重试策略
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════


class ErrorKind(str, Enum):
    TIMEOUT = "timeout"
    NETWORK = "network"
    EMPTY_RESULT = "empty_result"
    INVALID_INPUT = "invalid_input"
    API_ERROR = "api_error"
    UNKNOWN = "unknown"


@dataclass
class RetryAction:
    """重试引擎的决策结果"""

    action: str  # "retry" | "friendly_error" | "raw_error"
    # retry: 改了什么参数
    modified_slots: dict = field(default_factory=dict)
    # friendly_error: 给用户听的友好提示
    friendly_message: str = ""
    # 元信息
    error_kind: ErrorKind = ErrorKind.UNKNOWN
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "modified_slots": self.modified_slots,
            "friendly_message": self.friendly_message,
            "error_kind": self.error_kind.value,
            "reason": self.reason,
        }


# ═══════════════════════════════════════════════════
# 错误分类
# ═══════════════════════════════════════════════════


def classify_error(error: str, tool_result: dict) -> ErrorKind:
    """从 error 和 tool_result 推断错误类型"""
    if not error and not tool_result:
        return ErrorKind.UNKNOWN

    error_lower = (error or "").lower()

    if "timeout" in error_lower:
        return ErrorKind.TIMEOUT
    if (
        "connection" in error_lower
        or "network" in error_lower
        or "connect" in error_lower
    ):
        return ErrorKind.NETWORK
    if "json" in error_lower or "parse" in error_lower:
        return ErrorKind.API_ERROR

    # 从 tool_result 判断
    if isinstance(tool_result, dict):
        if tool_result.get("status") == "error":
            err = tool_result.get("error", "").lower()
            if "timeout" in err:
                return ErrorKind.TIMEOUT
            if "无法解析" in err or "缺少" in err:
                return ErrorKind.INVALID_INPUT

        if tool_result.get("success") is True:
            data = tool_result.get("data", {})
            if isinstance(data, dict):
                results = data.get("results", [])
                count = data.get("count", 0)
                if (results is not None and len(results) == 0) or count == 0:
                    return ErrorKind.EMPTY_RESULT

        if tool_result.get("success") is False:
            return ErrorKind.API_ERROR

    return ErrorKind.UNKNOWN


# ═══════════════════════════════════════════════════
# 友好错误信息模板
# ═══════════════════════════════════════════════════

_FRIENDLY_ERRORS: dict[ErrorKind, str] = {
    ErrorKind.TIMEOUT: "服务响应有点慢，请稍后再试",
    ErrorKind.NETWORK: "网络似乎不太稳定，请稍后再试",
    ErrorKind.API_ERROR: "服务暂时不可用，请稍后再试",
    ErrorKind.EMPTY_RESULT: "没有找到相关结果",
    ErrorKind.INVALID_INPUT: "无法理解您的请求，请换个方式说",
    ErrorKind.UNKNOWN: "操作遇到了问题，请稍后再试",
}


# ═══════════════════════════════════════════════════
# Retry 引擎
# ═══════════════════════════════════════════════════


def decide_retry(
    domain: str,
    intent: str,
    error: str,
    tool_result: dict,
    slots: dict,
    attempt: int = 1,
) -> RetryAction:
    """
    根据错误信息决定是否重试。

    Args:
        domain: skill 域
        intent: 意图名
        error: 异常信息
        tool_result: 工具返回（可能包含空结果等）
        slots: 当前执行参数
        attempt: 当前是第几次执行（1=首次，2=重试）

    Returns:
        RetryAction: retry / friendly_error / raw_error
    """
    error_kind = classify_error(error, tool_result)

    # 只重试 1 次
    if attempt >= 2:
        friendly = _FRIENDLY_ERRORS.get(error_kind, _FRIENDLY_ERRORS[ErrorKind.UNKNOWN])
        return RetryAction(
            action="friendly_error",
            friendly_message=friendly,
            error_kind=error_kind,
            reason=f"已重试{attempt - 1}次，不再重试",
        )

    # ── 1. Per-domain 重试规则（从 registry 加载）──
    try:
        from project1_cabin_agent.skills.registry import registry

        domain_rules = registry.get_retry_rules(domain)
        for rule_fn in domain_rules:
            result = rule_fn(intent, error_kind, error, tool_result, slots)
            if result is not None:
                logger.info(
                    f"[Retry] {domain}.{intent} {rule_fn.__name__} → {result.action}, "
                    f"reason={result.reason}"
                )
                return result
    except Exception:
        pass

    # ── 2. 通用 fallback：友好错误信息 ──
    friendly = _FRIENDLY_ERRORS.get(error_kind, _FRIENDLY_ERRORS[ErrorKind.UNKNOWN])
    return RetryAction(
        action="friendly_error",
        friendly_message=friendly,
        error_kind=error_kind,
        reason="无重试策略，返回友好错误",
    )
