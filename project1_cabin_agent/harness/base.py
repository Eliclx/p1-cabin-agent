"""
project1_cabin_agent/harness/base.py
Harness 基类 — 确定性校验层核心定义

四大核心理念之"确定性兜底"：
- harness 是纯 Python 规则，不信任 LLM，100% 确定
- 不调 LLM，不做 I/O，给定 (slots, ctx) 确定性返回 HarnessResult
- CONTEXT_DEPS 声明式依赖，让 orchestrator/context_enrich 按需准备数据
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Flag, auto
from typing import Any


# ── 上下文依赖声明（Flag 支持组合：VEHICLE | L2 | L3） ──────────────

class ContextDep(Flag):
    """
    harness 显式声明自己需要哪些上下文层。
    orchestrator / context_enrich 节点根据声明按需准备数据。
    
    用法：
        class NavigationHarness(BaseHarness):
            CONTEXT_DEPS = ContextDep.VEHICLE | ContextDep.L2 | ContextDep.L3
    """
    NONE    = 0
    VEHICLE = auto()   # 需要车机实时状态（位置、车速、空调状态等）
    L1      = auto()   # 需要当前对话记忆（指代消解、实体黑板）
    L2      = auto()   # 需要行程记忆（上次目的地、行程摘要）
    L3      = auto()   # 需要用户偏好（家/公司地址、常用设置）


# ── Harness 标准化输出 ──────────────────────────────────────────────

@dataclass
class HarnessResult:
    """
    harness 校验结果 — 所有 harness.pre_validate / post_validate 统一返回这个。
    
    设计原则：
    - valid=True 表示校验通过，可以继续执行
    - valid=False 表示校验失败，根据 need_clarify / fallback / block_reason 决定后续
    - slots 是修正后的槽位（harness 可能补全了默认值或解析了别名）
    """
    valid: bool
    slots: dict[str, Any] = field(default_factory=dict)

    # 校验失败时的处理方式（三选一）
    need_clarify: bool = False       # 需要追问用户（缺少必填槽位）
    clarify_message: str | None = None  # 追问文本
    need_confirm: bool = False       # 需要二次确认（安全检查）
    confirm_message: str | None = None
    fallback: bool = False           # 直接走云端兜底
    block_reason: str | None = None  # 校验失败原因（日志/调试用）


# ── Harness 基类 ────────────────────────────────────────────────────

class BaseHarness:
    """
    所有域 harness 的基类。
    
    子类必须实现：
    - pre_validate: LLM 输出后、调 tool 前的校验+补全
    - post_validate: tool 返回后、给用户前的校验
    - format_response: 确定性格式化输出（不经过 LLM）
    
    子类必须声明：
    - CONTEXT_DEPS: 告诉 context_enrich 需要准备哪些数据
    """
    CONTEXT_DEPS: ContextDep = ContextDep.NONE

    def pre_validate(self, slots: dict[str, Any], ctx: Any) -> HarnessResult:
        """
        LLM 输出后、调 tool 前。
        
        职责：
        1. 必填检查 — 缺了必填槽位 → need_clarify
        2. 默认值补全 — origin 缺失 → 从 vehicle_state 补
        3. 语义别名解析 — "家" → L3 用户地址
        4. 格式校验 — 坐标格式、枚举值
        5. 安全检查 — 高速行驶中改目的地 → need_confirm
        """
        raise NotImplementedError

    def post_validate(self, tool_result: dict[str, Any], ctx: Any) -> HarnessResult:
        """
        tool 返回后、给用户前。
        
        职责：
        1. API 返回失败 → 兜底提示
        2. 结果异常检查 — 距离 > 5000km → 追问确认
        3. 空结果处理 — "附近没有XX" → 提示用户
        """
        raise NotImplementedError

    def format_response(self, tool_result: dict[str, Any]) -> str:
        """
        确定性格式化输出，不经过 LLM。
        
        职责：
        - 把 tool 返回的原始数据格式化成用户可读的语音文本
        - 纯字符串拼接/模板，确定性 100%
        """
        raise NotImplementedError
