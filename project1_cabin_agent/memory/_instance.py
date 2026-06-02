"""
project1_cabin_agent/memory/_instance.py — MemoryManager 全局单例

为什么需要单例：
  1. 避免每次 intent_classifier 调用都 MemoryManager() 创建新实例
  2. 单例持有同一个 SQLite 连接池，避免并发冲突
  3. memory_meta 只注入一次（从 registry）

使用方式：
  from memory._instance import get_memory
  memory = get_memory()  # 返回全局单例
"""

from project1_cabin_agent.memory.manager import MemoryManager
from project1_cabin_agent.memory.models import MemoryConfig

_instance: MemoryManager | None = None


def get_memory() -> MemoryManager:
    """获取全局 MemoryManager 单例（首次调用时初始化）"""
    global _instance
    if _instance is None:
        from project1_cabin_agent.skills.registry import registry

        meta = registry.get_all_memory_meta()
        cfg = MemoryConfig(memory_meta=meta)
        _instance = MemoryManager(cfg)
    return _instance


def reset_memory(memory: MemoryManager | None = None) -> MemoryManager | None:
    """
      重置单例（测试用）。
    无参调用 → 置 None，下次 get_memory() 会重建。
      传入 MemoryManager → 替换为给定实例。
    """
    global _instance
    old = _instance
    _instance = memory
    return old
