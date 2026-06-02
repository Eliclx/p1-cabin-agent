"""
project1_cabin_agent/nodes/episodic_memory.py
L1.5 行程记忆 — 跨 session 事件日志 + 时间检索 + 上下文注入。

迁移说明（Phase 4E）：
  所有读写操作已委托给 memory.MemoryManager。
  本文件保留为薄代理层，维持旧接口兼容。

  - log_event / auto_log_from_task_results → MemoryManager.log_event / log_event_from_results
  - retrieve_episodic_context → MemoryManager.query_events（时间范围过滤）
  - seed_event / clear_events → MemoryManager（测试用）

  时间源 mock 功能保留在此文件（MemoryManager 不依赖自定义时间源）。
"""

import re
from datetime import datetime, timedelta

from shared.utils.logger import logger

# ── 时间源（可 mock）──
# MemoryManager 不使用自定义时间源，但旧测试依赖 mock 能力
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


# ── 时间回溯词 ──

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
    (r"之前", "last_time"),
]


def has_temporal_keywords(user_input: str) -> bool:
    """检测用户输入是否含时间回溯词。"""
    for pattern, _ in _TEMPORAL_PATTERNS:
        if re.search(pattern, user_input):
            return True
    return False


def _parse_time_range(user_input: str) -> tuple[str | None, str | None]:
    """根据时间词计算时间范围 (start_ts, end_ts)。"""
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


# ═══════════════════════════════════════════════════
# 代理函数 — 全部委托给 MemoryManager
# ═══════════════════════════════════════════════════


def _get_memory():
    """获取 MemoryManager 单例"""
    from project1_cabin_agent.memory._instance import get_memory

    return get_memory()


def log_event(
    event_type: str,
    summary: str,
    details: dict | None = None,
    timestamp: str | None = None,
) -> None:
    """写入一条事件日志。委托给 MemoryManager.log_event。"""
    result = _get_memory().log_event(event_type, summary, details, timestamp)
    if result != "skipped":
        logger.info(f"[L1.5行程记忆] <- {event_type}: {summary}")


def auto_log_from_task_results(task_results: list) -> None:
    """从 task_results 自动提取事件并归档。委托给 MemoryManager。"""
    _get_memory().log_event_from_results(task_results)


def retrieve_episodic_context(user_input: str, limit: int = 10) -> dict | None:
    """
    检索 + 格式化，同时返回 LLM 文本和 harness 原始数据。

    委托给 MemoryManager.query_events，用时间范围过滤。
    """
    if not has_temporal_keywords(user_input):
        return None

    start_ts, end_ts = _parse_time_range(user_input)
    if not start_ts:
        return None

    memory = _get_memory()
    events = memory.query_events(
        query="",
        limit=limit,
    )

    # 时间范围过滤（MemoryManager 的 query_events 没有 start/end 参数，这里过滤）
    import json as _json

    filtered = []
    for ev in events:
        ts = ev.timestamp
        if start_ts <= ts <= end_ts:
            filtered.append(ev)

    if not filtered:
        logger.info(f"[L1.5行程记忆] 未检索到匹配事件: {user_input}")
        return None

    text_lines = ["[可用行程数据 - 以下为可提取的真实数据]"]
    raw_data = []

    for ev in filtered:
        try:
            dt = datetime.fromisoformat(ev.timestamp)
            time_str = dt.strftime("%m-%d %H:%M")
        except (ValueError, OSError):
            time_str = ev.timestamp[:16]

        text_lines.append(f"- {time_str} | {ev.event_type} | {ev.summary}")

        details = ev.details or {}
        full_text = (
            f"{time_str} {ev.event_type} {ev.summary} "
            f"{_json.dumps(details, ensure_ascii=False)}"
        )
        raw_data.append(
            {
                "timestamp": ev.timestamp,
                "event_type": ev.event_type,
                "summary": ev.summary,
                "details": details,
                "full_text": full_text,
            }
        )

    context_text = "\n".join(text_lines)
    logger.info(
        f"[L1.5行程记忆] 检索到 {len(filtered)} 条事件，注入 LLM context"
    )
    return {"text": context_text, "raw": raw_data}


def seed_event(
    timestamp: str, event_type: str, summary: str, details: dict | None = None
) -> None:
    """手动写入事件（测试用）。绕过白名单和 dedup。"""
    memory = _get_memory()
    conn = memory.backend._episodic_conn()
    import json as _json
    details_json = _json.dumps(details or {}, ensure_ascii=False)
    conn.execute(
        "INSERT INTO events (timestamp, event_type, summary, details, dedup_hash, heat, dedup_count) "
        "VALUES (?, ?, ?, ?, '', 1.0, 1)",
        (timestamp, event_type, summary, details_json),
    )
    conn.commit()


def clear_events() -> None:
    """清空事件表（测试用）。"""
    memory = _get_memory()
    conn = memory.backend._episodic_conn()
    conn.execute("DELETE FROM events")
    conn.commit()
    logger.info("[L1.5行程记忆] 事件表已清空")
