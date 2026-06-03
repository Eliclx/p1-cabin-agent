"""
project1_cabin_agent/memory/evolution_runner.py — 进化编排器

职责：
  - 读 MemoryManager 未分析事件
  - 调 EvolutionEngine 分析
  - 写偏好回 MemoryManager
  - 标记事件已分析

依赖方向：
  evolution_runner → memory/manager.py (读/写数据)
  evolution_runner → memory/evolution.py (纯逻辑)
  evolution_runner → shared/utils/llm_factory.py (拿 LLM)

evolution.py 本身零外部依赖。Runner 是胶水层。

触发方式可换（原则 2）：
  - 当前：response_gen 末尾同步调
  - 将来：异步任务 / 定时任务 / 手动触发
"""

from __future__ import annotations

import logging

from project1_cabin_agent.memory.evolution import EvolutionEngine

logger = logging.getLogger(__name__)


def run_evolution(memory_manager, max_events: int = 50) -> int:
    """
    执行一次记忆进化。

    Args:
        memory_manager: MemoryManager 实例（由调用方传入，不在此 import）
        max_events: 单次分析的最大事件数

    Returns:
        提取到的偏好数量
    """
    # 1. 检查是否需要进化
    if not memory_manager.should_evolve():
        return 0

    # 2. 取未分析事件
    events = memory_manager.get_unanalyzed_events()
    if not events:
        return 0

    # 截断（防止单次给 LLM 太多）
    events = events[:max_events]

    # 3. 序列化为 dict 列表（evolution.py 只收 dict，不收 Event 对象）
    events_data = [
        {
            "event_type": e.event_type,
            "summary": e.summary,
            "heat": e.heat,
            "dedup_count": e.dedup_count,
            "details": e.details,
            "timestamp": e.timestamp,
        }
        for e in events
    ]

    # 4. 构建 LLM callable（延迟 import，runner 不强制依赖 llm_factory）
    try:
        from langchain_core.messages import HumanMessage
        from shared.utils.llm_factory import get_llm
    except ImportError:
        logger.debug("[Evolution] LLM 依赖不可用，跳过")
        return 0

    def llm_fn(prompt: str) -> str:
        llm = get_llm("fast", temperature=0.1)
        from project1_cabin_agent.memory.evolution import _EVOLUTION_SYSTEM_PROMPT

        messages = [
            {"role": "system", "content": _EVOLUTION_SYSTEM_PROMPT},
            HumanMessage(content=prompt),
        ]
        resp = llm.invoke(messages)
        return resp.content if hasattr(resp, "content") else str(resp)

    # 5. 执行进化
    engine = EvolutionEngine(llm_fn)
    preferences = engine.evolve(events_data)

    if not preferences:
        # 没提取到偏好，仍然标记已分析（避免反复送同样的数据给 LLM）
        event_ids = [e.id for e in events]
        memory_manager.mark_events_analyzed(event_ids)
        logger.info(f"[Evolution] 分析 {len(events)} 条事件，未提取到偏好")
        return 0

    # 6. 写回偏好
    for pref in preferences:
        memory_manager.save_preference(
            key=pref.key,
            value=pref.value,
            source="llm_evolution",
            confidence=pref.confidence,
        )

    # 7. 标记事件已分析
    event_ids = [e.id for e in events]
    memory_manager.mark_events_analyzed(event_ids)

    logger.info(
        f"[Evolution] 分析 {len(events)} 条事件 → 提取 {len(preferences)} 条偏好"
    )
    for pref in preferences:
        logger.debug(
            f"  {pref.key}={pref.value} (conf={pref.confidence:.2f}, {pref.reason})"
        )

    return len(preferences)
