"""
memory/decay.py — 时间衰减函数

核心公式：score × (α + (1 - α) × 0.5^(age_days / half_life))

- half_life_days=14: 14天前的记忆权重减半
- α=0.3: 旧记忆最低保留 30% 权重，不会清零

对标：MemOS recency.ts
"""

from __future__ import annotations

from datetime import datetime


def time_decay(
    timestamp: str,
    half_life_days: float = 14.0,
    alpha: float = 0.3,
    now: datetime | None = None,
) -> float:
    """
    计算时间衰减系数。

    Args:
        timestamp: ISO 格式时间字符串
        half_life_days: 半衰期天数
        alpha: 保留系数
        now: 当前时间（可注入，测试用）

    Returns:
        0.0 ~ 1.0 之间的衰减系数
    """
    if not timestamp:
        return alpha
    if now is None:
        now = datetime.now()
    try:
        created = datetime.fromisoformat(timestamp)
    except (ValueError, TypeError):
        return alpha

    age_days = max(0, (now - created).total_seconds() / 86400)
    decay = 0.5 ** (age_days / half_life_days)
    return alpha + (1 - alpha) * decay


def score_with_decay(
    heat: float,
    timestamp: str,
    half_life_days: float = 14.0,
    alpha: float = 0.3,
    now: datetime | None = None,
) -> float:
    """热度 × 时间衰减 = 最终得分"""
    return heat * time_decay(timestamp, half_life_days, alpha, now)
