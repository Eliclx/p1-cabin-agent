"""
memory/models.py — 记忆数据模型

所有模型用 dataclass，轻量、可序列化。
MemoryManager 内部使用这些模型，外部通过 dict 交互也可以。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── 事件（L2 行程记忆）──


@dataclass
class Event:
    """行程事件 — 一次导航/搜索/播放等操作的记录"""

    id: int = 0
    timestamp: str = ""
    event_type: str = ""  # navigate / search_poi / media_control / weather
    summary: str = ""  # "导航去天府广场"
    details: dict = field(default_factory=dict)

    # 新增字段（Phase 4A）
    session_id: str = ""  # 驾车行程分组（预留）
    dedup_hash: str = ""  # 去重指纹 "navigate:天府广场"
    dedup_count: int = 1  # 被合并次数（= 热度信号）
    heat: float = 1.0  # 热度分
    link_group: str = ""  # 关联分组（同目的地）
    last_accessed: str = ""  # 最后访问时间
    analyzed: bool = False  # 是否已被 LLM 分析过

    @property
    def key_entity(self) -> str:
        """提取关键实体（用于 dedup/link）。由外部注入的 memory_meta 驱动。"""
        # 如果有 _meta 上下文，从 dedup_key 字段取
        # 否则走兼容逻辑
        if self.event_type == "navigate":
            return self.details.get("destination", "")
        elif self.event_type == "search_poi":
            return self.details.get("keyword", "")
        elif self.event_type == "weather":
            return self.details.get("city", "")
        elif self.event_type == "media_control":
            return self.details.get("query", "") or self.details.get("artist", "")
        return ""


# ── 偏好（L3 长期记忆）──


@dataclass
class Preference:
    """用户偏好 — 跨 session 持久化的个性化设置"""

    key: str = ""
    value: str = ""
    confidence: float = 1.0  # 置信度（1.0=用户明确说，<1.0=LLM 推断）
    source: str = "slot_extraction"  # slot_extraction / llm_analysis
    heat: float = 1.0  # 被使用次数
    created_at: str = ""
    updated_at: str = ""
    last_used_at: str = ""


# ── 高频地点 ──


@dataclass
class FrequentPlace:
    """高频地点 — 多次访问的目的地汇总"""

    name: str = ""  # "天府广场"
    visit_count: int = 0  # 30
    last_visit: str = ""  # 上次去的时间
    event_types: list[str] = field(default_factory=list)  # ["navigate", "search_poi"]
    is_home: bool = False  # LLM 推断（预留）
    is_work: bool = False  # LLM 推断（预留）


# ── 统一检索结果 ──


@dataclass
class MemoryHit:
    """统一检索结果 — recall() 返回，跨 L2/L3 合并排序"""

    source: str = ""  # "episodic" / "preference" / "frequent_place"
    content: str = ""  # 人类可读文本
    score: float = 0.0  # 排序分（heat × decay）
    data: dict = field(default_factory=dict)
    timestamp: str = ""


# ── 配置 ──


@dataclass
class MemoryConfig:
    """记忆模块配置"""

    episodic_db_path: str = ""  # events.db 路径（空则用默认）
    longterm_db_path: str = ""  # preferences.db 路径（空则用默认）
    heat_threshold_for_evolution: float = 10.0  # 触发 LLM 进化的热度阈值
    decay_half_life_days: float = 14.0  # 时间衰减半衰期（天）
    decay_alpha: float = 0.3  # 保留系数（越高旧记忆权重越大）
    memory_meta: dict[str, dict] = field(
        default_factory=dict
    )  # 从外部注入（SSOT = skill schema）
