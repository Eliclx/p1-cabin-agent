"""
project1_cabin_agent/nodes/episodic_memory.py
L1.5 行程记忆 — 跨 session 事件日志 + 时间检索 + 上下文注入。

设计原则：
# - 工具执行后自动归档（白名单控制：navigate/search_poi/media_control）
- 含时间回溯词时触发检索，结果注入 LLM context
- 时间源可 mock（测试时注入固定时间，生产用系统时钟）
- 守卫层零改动：走 needs_ctx=True 路径，漂移/歧义自动豁免
"""

import os
import re
import sqlite3
from datetime import datetime, timedelta

from shared.utils.logger import logger

# ── 数据库路径（和 user_profile.db 同目录） ──

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "events.db"
)

# ── 白名单：哪些 intent 的执行结果值得记 ──

EVENT_TYPES_TO_LOG = {"navigate", "search_poi", "media_control", "weather"}


# ═══════════════════════════════════════════════════════════════
# 时间源（可 mock）
# ═══════════════════════════════════════════════════════════════

_current_time_fn = datetime.now


def set_current_time_fn(fn):
    """注入自定义时间函数，用于测试。fn() 返回 datetime 对象。"""
    global _current_time_fn
    _current_time_fn = fn


def reset_current_time_fn():
    """恢复系统时钟。"""
    global _current_time_fn
    _current_time_fn = datetime.now


def _get_current_time() -> datetime:
    return _current_time_fn()


# ═══════════════════════════════════════════════════════════════
# SQLite
# ═══════════════════════════════════════════════════════════════

_WAL_ENABLED = False  # 模块级 flag，首次连接时开启


def _get_db() -> sqlite3.Connection:
    global _WAL_ENABLED
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    if not _WAL_ENABLED:
        conn.execute("PRAGMA journal_mode=WAL")  # 允许读写并发，减少 lock
        _WAL_ENABLED = True
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            details TEXT DEFAULT '{}'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_timestamp
        ON events(timestamp)
    """)
    conn.commit()
    return conn


def _retry_on_lock(fn):
    """SQLite 写冲突重试：WAL 模式下偶尔仍有 transient lock"""
    import time as _time

    def wrapper(*args, **kwargs):
        for i in range(3):
            try:
                return fn(*args, **kwargs)
            except sqlite3.OperationalError as e:
                if "locked" in str(e) and i < 2:
                    _time.sleep(0.05 * (2**i))
                    continue
                raise

    return wrapper


# ═══════════════════════════════════════════════════════════════
# 写入
# ═══════════════════════════════════════════════════════════════


@_retry_on_lock
def log_event(
    event_type: str,
    summary: str,
    details: dict | None = None,
    timestamp: str | None = None,
) -> None:
    """写入一条事件日志。非白名单类型静默跳过。"""
    if event_type not in EVENT_TYPES_TO_LOG:
        return

    import json

    ts = timestamp or _get_current_time().isoformat()
    details_json = json.dumps(details or {}, ensure_ascii=False)

    conn = _get_db()
    conn.execute(
        "INSERT INTO events (timestamp, event_type, summary, details) VALUES (?, ?, ?, ?)",
        (ts, event_type, summary, details_json),
    )
    conn.commit()
    conn.close()
    logger.info(f"[L1.5行程记忆] <- {event_type}: {summary}")


def auto_log_from_task_results(task_results: list) -> None:
    """从 task_results 自动提取事件并归档。放在 session_update 之后调用。"""
    for r in task_results:
        intent = r.get("intent", "")
        if intent not in EVENT_TYPES_TO_LOG:
            continue

        tool_result = r.get("tool_result", {})
        summary = _extract_summary(intent, tool_result)
        if summary:
            log_event(intent, summary)
            logger.info(f"[L1.5行程记忆] <- {intent}: {summary}")


def _extract_summary(intent: str, tool_result: dict) -> str | None:
    """从工具结果提取人类可读摘要。"""
    if not tool_result:
        return None

    if intent == "navigate":
        dest = tool_result.get("destination", "")
        return f"导航去{dest}" if dest else None

    if intent == "search_poi":
        keyword = tool_result.get("keyword", "")
        if keyword:
            # 如果有搜索结果，附加数量
            count = len(tool_result.get("results", []))
            if count:
                return f"搜索了{keyword}({count}个结果)"
            return f"搜索了{keyword}"
        return None

    if intent == "media_control":
        action = tool_result.get("action", "")
        query = tool_result.get("query", "")
        artist = tool_result.get("artist", "")
        if query:
            return f"播放了{query}"
        if artist:
            return f"播放了{artist}的歌"
        if action in ("play", "pause", "next", "previous"):
            return f"媒体操作: {action}"
        return None

    if intent == "weather":
        city = tool_result.get("city", "")
        weather_desc = tool_result.get("weather", "")
        if city and weather_desc:
            return f"查询了{city}天气: {weather_desc}"
        if city:
            return f"查询了{city}天气"
        return None

    return None


# ═══════════════════════════════════════════════════════════════
# 检索
# ═══════════════════════════════════════════════════════════════

# 时间回溯词 → (标签, 时间范围计算规则)
# ⚠️ 顺序重要：长匹配优先，避免 "昨天早上" 被 "昨天" 吞掉
_TEMPORAL_PATTERNS = [
    (r"昨天晚上", "last_night"),
    (r"昨晚", "last_night"),
    (r"昨天早上", "yesterday_morning"),
    (r"昨天上午", "yesterday_morning"),
    (r"昨天", "yesterday"),
    (r"前天晚上", "day_before_yesterday_night"),
    (r"前天", "day_before_yesterday"),
    (r"今天早上", "this_morning"),
    (r"今天上午", "this_morning"),
    (r"今天", "today"),
    (r"刚才", "just_now"),
    (r"早上", "this_morning"),
    (r"上午", "this_morning"),
    (r"上次", "last_time"),
    (r"前几天", "few_days_ago"),
    (r"上周", "last_week"),
    (r"上星期", "last_week"),
    (r"之前", "last_time"),  # 模糊，兜底
]


def has_temporal_keywords(user_input: str) -> bool:
    """检测用户输入是否含时间回溯词。"""
    for pattern, _ in _TEMPORAL_PATTERNS:
        if re.search(pattern, user_input):
            return True
    return False


def _parse_time_range(user_input: str) -> tuple[str | None, str | None]:
    """根据时间词计算 SQL 查询的时间范围 (start_ts, end_ts)。"""
    now = _get_current_time()

    for pattern, label in _TEMPORAL_PATTERNS:
        if not re.search(pattern, user_input):
            continue

        if label == "last_night":
            yesterday = now - timedelta(days=1)
            start = yesterday.replace(hour=18, minute=0, second=0)
            end = yesterday.replace(hour=23, minute=59, second=59)
        elif label == "yesterday_morning":
            yesterday = now - timedelta(days=1)
            start = yesterday.replace(hour=6, minute=0, second=0)
            end = yesterday.replace(hour=12, minute=0, second=0)
        elif label == "yesterday":
            yesterday = now - timedelta(days=1)
            start = yesterday.replace(hour=0, minute=0, second=0)
            end = yesterday.replace(hour=23, minute=59, second=59)
        elif label == "day_before_yesterday_night":
            dby = now - timedelta(days=2)
            start = dby.replace(hour=18, minute=0, second=0)
            end = dby.replace(hour=23, minute=59, second=59)
        elif label == "day_before_yesterday":
            dby = now - timedelta(days=2)
            start = dby.replace(hour=0, minute=0, second=0)
            end = dby.replace(hour=23, minute=59, second=59)
        elif label == "today":
            start = now.replace(hour=0, minute=0, second=0)
            end = now
        elif label == "just_now":
            start = now - timedelta(minutes=30)
            end = now
        elif label == "this_morning":
            start = now.replace(hour=6, minute=0, second=0)
            end = now.replace(hour=12, minute=0, second=0)
        elif label == "last_time":
            start = now - timedelta(days=7)
            end = now
        elif label == "few_days_ago":
            start = now - timedelta(days=7)
            end = now - timedelta(days=1)
        elif label == "last_week":
            start = now - timedelta(days=14)
            end = now - timedelta(days=7)
        else:
            start = now - timedelta(days=7)
            end = now

        return start.isoformat(), end.isoformat()

    return None, None


def retrieve_episodic_context(user_input: str, limit: int = 10) -> dict | None:
    """检索 + 格式化，同时返回 LLM 文本和 harness 原始数据。

    返回 None 表示无需注入（无时间词 / 无匹配事件）。
    返回 dict:
      - text: 注入 LLM prompt 的格式化文本
      - raw:  list[dict]，每条事件的原始数据，供 harness 校验
    """
    if not has_temporal_keywords(user_input):
        return None

    start_ts, end_ts = _parse_time_range(user_input)
    if not start_ts:
        return None

    conn = _get_db()
    rows = conn.execute(
        "SELECT timestamp, event_type, summary, details FROM events "
        "WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp DESC LIMIT ?",
        (start_ts, end_ts, limit),
    ).fetchall()
    conn.close()

    if not rows:
        logger.info(f"[L1.5行程记忆] 未检索到匹配事件: {user_input}")
        return None

    import json

    text_lines = ["[可用行程数据 - 以下为可提取的真实数据]"]
    raw_data = []

    for ts, etype, summary, details_json in rows:
        try:
            dt = datetime.fromisoformat(ts)
            time_str = dt.strftime("%m-%d %H:%M")
        except (ValueError, OSError):
            time_str = ts[:16]

        # LLM 用的格式化行：时间 | 类型 | 摘要
        text_lines.append(f"- {time_str} | {etype} | {summary}")

        # harness 用的原始数据：把所有文本字段展开，方便校验时匹配
        details = {}
        try:
            details = json.loads(details_json) if details_json else {}
        except (json.JSONDecodeError, TypeError):
            pass
        full_text = (
            f"{time_str} {etype} {summary} {json.dumps(details, ensure_ascii=False)}"
        )
        raw_data.append(
            {
                "timestamp": ts,
                "event_type": etype,
                "summary": summary,
                "details": details,
                "full_text": full_text,
            }
        )

    context_text = "\n".join(text_lines)
    logger.info(f"[L1.5行程记忆] 检索到 {len(rows)} 条事件，注入 LLM context")
    return {"text": context_text, "raw": raw_data}


def seed_event(
    timestamp: str, event_type: str, summary: str, details: dict | None = None
) -> None:
    """手动写入事件（测试用）。绕过白名单限制。"""
    import json

    details_json = json.dumps(details or {}, ensure_ascii=False)
    conn = _get_db()
    conn.execute(
        "INSERT INTO events (timestamp, event_type, summary, details) VALUES (?, ?, ?, ?)",
        (timestamp, event_type, summary, details_json),
    )
    conn.commit()
    conn.close()


def clear_events() -> None:
    """清空事件表（测试用）。"""
    conn = _get_db()
    conn.execute("DELETE FROM events")
    conn.commit()
    conn.close()
    logger.info("[L1.5行程记忆] 事件表已清空")
