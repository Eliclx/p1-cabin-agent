"""
project1_cabin_agent/nodes/user_profile.py
L2 长期记忆 — 用户画像存储（跨 session 持久化）
存用户偏好：音乐、空调、常去地点、搜索偏好等
"""
import json
import sqlite3
import os
from datetime import datetime

from shared.utils.logger import logger

# 数据库文件路径
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "user_profile.db"
)

# ── Intent → L2 key 映射（slot名 → L2 key）──
INTENT_TO_L2_KEY = {
    "media_control": {
        "query": "music_query",
    },
    "ac_control": {
        "temperature": "ac_temperature",
    },
    "start_navigation": {
        "destination": "last_destination",
    },
    "search_poi": {
        "category": "poi_category",
    },
}

# ═══════════════════════════════════════════════════
# SQLite
# ═══════════════════════════════════════════════════

_WAL_ENABLED_UP = False


def _get_db() -> sqlite3.Connection:
    """获取数据库连接，自动创建目录和表"""
    global _WAL_ENABLED_UP
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    if not _WAL_ENABLED_UP:
        conn.execute("PRAGMA journal_mode=WAL")
        _WAL_ENABLED_UP = True
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _retry_on_lock(fn):
    """SQLite 写冲突重试"""
    import time as _time
    def wrapper(*args, **kwargs):
        for i in range(3):
            try:
                return fn(*args, **kwargs)
            except sqlite3.OperationalError as e:
                if "locked" in str(e) and i < 2:
                    _time.sleep(0.05 * (2 ** i))
                    continue
                raise
    return wrapper


@_retry_on_lock
def save_preference(key: str, value: str) -> None:
    """保存用户偏好"""
    conn = _get_db()
    conn.execute(
        "INSERT OR REPLACE INTO user_profile (key, value, updated_at) VALUES (?, ?, ?)",
        (key, str(value), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    logger.info(f"[L2记忆] <- {key} = {value}")


def get_preference(key: str) -> str | None:
    """读取单个偏好"""
    conn = _get_db()
    row = conn.execute(
        "SELECT value FROM user_profile WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def get_all_preferences() -> dict:
    """读取所有偏好"""
    conn = _get_db()
    rows = conn.execute("SELECT key, value FROM user_profile").fetchall()
    conn.close()
    return {k: v for k, v in rows}


def _is_valid_preference(value) -> bool:
    """过滤未解析的引用表达式，避免把 LLM 的占位符写进 L2。"""
    invalid_patterns = [
        "results[", "task_", "[0]", "[1]", "[2]",
        "resolver_", "unknown", "未知", "待定",
    ]
    v = str(value).lower()
    return not any(p in v for p in invalid_patterns)


def save_from_tool_result(intent: str, slots: dict) -> None:
    """
    工具执行后，根据 intent 自动提取 slot 写入 L2。
    过滤掉 LLM 未解析的引用表达式（如 results[0].name）。
    """
    mapping = INTENT_TO_L2_KEY.get(intent, {})
    for slot_key, l2_key in mapping.items():
        value = slots.get(slot_key)
        if value and _is_valid_preference(value):
            save_preference(l2_key, value)
