"""
project1_cabin_agent/harness/__init__.py
Harness 框架 — 确定性校验层

设计原则：
- BaseHarness 是所有域 harness 的基类
- CONTEXT_DEPS 声明式依赖：每个 harness 声明自己需要哪些上下文层
- HarnessResult 标准化输出：valid/slots/block_reason/need_clarify/fallback
- harness 是纯函数：给定 (slots, ctx) → HarnessResult，不做任何 I/O
"""
from project1_cabin_agent.harness.base import (
    ContextDep,
    HarnessResult,
    BaseHarness,
)

__all__ = ["ContextDep", "HarnessResult", "BaseHarness"]
