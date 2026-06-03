"""
project1_cabin_agent/actions/engine.py — Action 通用引擎

职责：从 registry 收集 per-domain formatter，调度转换。
零域硬编码（不知道 climate/map/media 的存在）。

解耦：
  skills/{domain}/action_format.py 声明转换逻辑
  registry 自动发现
  engine 只做调度
"""

from __future__ import annotations

import logging

from project1_cabin_agent.actions.models import CabinAction

logger = logging.getLogger(__name__)


def format_action(domain: str, intent: str, tool_result: dict) -> CabinAction | None:
    """
    tool_result → CabinAction

    从 registry 找到对应 domain+intent 的 formatter 调用。
    找不到则返回 None（查询类 intent 或未实现的域）。
    """
    try:
        from project1_cabin_agent.skills.registry import registry
        formatter = registry.get_action_formatter(domain, intent)
    except Exception:
        return None

    if not formatter:
        return None

    try:
        return formatter(tool_result)
    except Exception as e:
        logger.debug(f"[action] {domain}.{intent} 转换失败: {e}")
        return None
