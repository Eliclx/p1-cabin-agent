"""
memory — 可插拔记忆模块

统一管理 L2 行程记忆 + L3 长期偏好。
底层存储可替换（SQLite / 向量数据库），上层零改动。

使用方式：
    from memory import MemoryManager, MemoryConfig

    memory = MemoryManager(MemoryConfig(
        episodic_db_path="data/events.db",
        longterm_db_path="data/preferences.db",
    ))
    memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
    events = memory.query_events(query="天府广场")
"""

from project1_cabin_agent.memory.manager import MemoryManager
from project1_cabin_agent.memory.models import MemoryConfig

__all__ = ["MemoryManager", "MemoryConfig"]


def create_memory_manager(
    episodic_db_path: str = "",
    longterm_db_path: str = "",
    memory_meta: dict | None = None,
) -> MemoryManager:
    """
    工厂函数：创建注入了 memory_meta 的 MemoryManager。

    memory_meta 通常从 skills.registry 获取：
        from skills.registry import registry
        meta = registry.get_all_memory_meta()
        memory = create_memory_manager(memory_meta=meta)

    也可以手动传入自定义 meta（测试/迁移用）。
    """
    cfg = MemoryConfig(
        episodic_db_path=episodic_db_path,
        longterm_db_path=longterm_db_path,
        memory_meta=memory_meta or {},
    )
    return MemoryManager(cfg)
