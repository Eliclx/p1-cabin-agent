"""
project1_cabin_agent/nodes/user_profile.py
L2 长期记忆 — 用户画像存储（跨 session 持久化）

迁移说明（Phase 4E）：
  所有读写操作已委托给 memory.MemoryManager。
  本文件保留为薄代理层，维持旧接口兼容。

  - save_preference → MemoryManager.save_preference
  - get_preference → MemoryManager.get_preference
  - get_all_preferences → MemoryManager.get_active_preferences
  - save_from_tool_result → MemoryManager.save_from_tool_result（映射 + 过滤）
"""


from shared.utils.logger import logger

# ── Intent → L3 key 映射（SSOT 从 skill schema 的 l3_keys 注入，这里保留兼容）──

INTENT_TO_L2_KEY = {
    "media_control": {
        "query": "music_query",
    },
    "ac_control": {
        "temperature": "ac_temperature",
    },
    "navigate": {
        "destination": "last_destination",
    },
    "search_poi": {
        "category": "poi_category",
    },
}


def _get_memory():
    """获取 MemoryManager 单例"""
    from project1_cabin_agent.memory._instance import get_memory

    return get_memory()


# ═══════════════════════════════════════════════════
# 代理函数
# ═══════════════════════════════════════════════════


def save_preference(key: str, value: str) -> None:
    """保存用户偏好。委托给 MemoryManager.save_preference。"""
    _get_memory().save_preference(key, value)
    logger.info(f"[L2记忆] <- {key} = {value}")


def get_preference(key: str) -> str | None:
    """读取单个偏好。委托给 MemoryManager。"""
    pref = _get_memory().get_preference(key)
    if pref:
        return pref.value
    return None


def get_all_preferences() -> dict:
    """读取所有偏好。委托给 MemoryManager。"""
    prefs = _get_memory().get_active_preferences()
    return {p.key: p.value for p in prefs}


def _is_valid_preference(value) -> bool:
    """过滤未解析的引用表达式，避免把 LLM 的占位符写进 L2。"""
    invalid_patterns = [
        "results[",
        "task_",
        "[0]",
        "[1]",
        "[2]",
        "resolver_",
        "unknown",
        "未知",
        "待定",
    ]
    v = str(value).lower()
    return not any(p in v for p in invalid_patterns)


def save_from_tool_result(intent: str, slots: dict) -> None:
    """
    工具执行后，根据 intent 自动提取 slot 写入 L3。
    委托给 MemoryManager.save_preference。
    """
    mapping = INTENT_TO_L2_KEY.get(intent, {})
    for slot_key, l2_key in mapping.items():
        value = slots.get(slot_key)
        if value and _is_valid_preference(value):
            save_preference(l2_key, value)
