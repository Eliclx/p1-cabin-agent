"""
memory/manager.py — 统一记忆管理器

所有记忆读写的唯一入口。
上层（DST / Policy / context_enrich）只跟 MemoryManager 交互，
不直接操作 SQLite / 黑板。

后端可替换：SqliteBackend → 向量数据库，上层零改动。
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime

from project1_cabin_agent.memory.backends.sqlite_backend import SqliteBackend
from project1_cabin_agent.memory.decay import score_with_decay, time_decay
from project1_cabin_agent.memory.models import (
    Event,
    FrequentPlace,
    MemoryConfig,
    MemoryHit,
    Preference,
)

# ── 默认数据库路径 ──

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_MODULE_DIR)
_DEFAULT_EPISODIC = os.path.join(_PROJECT_DIR, "data", "events.db")
_DEFAULT_LONGTERM = os.path.join(_PROJECT_DIR, "data", "preferences.db")

# ── 允许记录的事件类型白名单 ──
# 由 MemoryConfig.memory_meta 注入（SSOT = skill schema 声明）


def _template_values(tool_result: dict) -> defaultdict:
    """从 tool_result 构建模板变量（列表取 count，字符串/数字取原值）"""
    values = defaultdict(str)
    for k, v in tool_result.items():
        if isinstance(v, (str, int, float)):
            values[k] = v
        elif isinstance(v, list):
            values[k] = len(v)
    return values


class MemoryManager:
    """
    统一记忆管理器。

    用法：
        memory = MemoryManager(MemoryConfig())
        memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        events = memory.query_events(query="天府广场")
        prefs = memory.get_active_preferences()
    """

    def __init__(self, config: MemoryConfig | None = None):
        self.config = config or MemoryConfig()
        episodic_path = self.config.episodic_db_path or _DEFAULT_EPISODIC
        longterm_path = self.config.longterm_db_path or _DEFAULT_LONGTERM

        self.backend = SqliteBackend(episodic_path, longterm_path)

    # ═══════════════════════════════════════════════
    # L2 行程记忆 — 写入
    # ═══════════════════════════════════════════════

    def log_event(
        self,
        event_type: str,
        summary: str,
        details: dict | None = None,
        timestamp: str | None = None,
    ) -> str:
        """
        写入行程事件。

        内置逻辑：
        1. 白名单过滤（非白名单静默跳过）
        2. 去重：相同 dedup_hash → heat+1 而非新建
        3. 自动链接：同目的地 → 同一 link_group

        Args:
            event_type: 事件类型 (navigate/search_poi/media_control/weather)
            summary: 摘要文本 ("导航去天府广场")
            details: 结构化详情 ({"destination": "天府广场"})
            timestamp: ISO 时间（空则用当前时间）

        Returns:
            "dedup" 如果去重合并，"new" 如果新建
        """
        # 白名单 — 从注入的 memory_meta 读取（SSOT）
        meta = self.config.memory_meta.get(event_type, {})
        if not meta.get("log", False):
            return "skipped"

        now = timestamp or datetime.now().isoformat()
        details = details or {}

        # ① 去重检查
        dedup_hash = self._compute_dedup_hash(event_type, details, summary)
        existing = self.backend.find_event_by_hash(dedup_hash)

        if existing:
            # 去重合并：heat+1, dedup_count+1, 更新 last_accessed
            self.backend.update_event(
                existing.id,
                {
                    "heat": existing.heat + 1.0,
                    "dedup_count": existing.dedup_count + 1,
                    "last_accessed": now,
                    "summary": summary,  # 更新为最新摘要
                    "details": details,  # 更新为最新详情（保持 JSON）
                },
            )
            return "dedup"

        # ② 自动链接
        link_group = self._compute_link_group(event_type, details)

        # ③ 写入新事件
        event = Event(
            timestamp=now,
            event_type=event_type,
            summary=summary,
            details=details,
            dedup_hash=dedup_hash,
            heat=1.0,
            link_group=link_group,
            last_accessed=now,
        )
        self.backend.insert_event(event)
        return "new"

    # ═══════════════════════════════════════════════
    # L2 行程记忆 — 检索
    # ═══════════════════════════════════════════════

    def query_events(
        self,
        query: str | None = None,
        event_type: str | None = None,
        time_range: tuple[str, str] | None = None,
        limit: int = 10,
    ) -> list[Event]:
        """
        检索行程事件。

        排序：heat × time_decay，热门且近期的排前面。
        """
        events = self.backend.search_events(query, event_type, time_range, limit * 3)

        # 计算衰减分并排序（不修改原始 heat）
        scored = []
        for e in events:
            score = score_with_decay(
                e.heat,
                e.last_accessed or e.timestamp,
                half_life_days=self.config.decay_half_life_days,
                alpha=self.config.decay_alpha,
            )
            scored.append((score, e))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    def get_frequent_destinations(self, top_k: int = 5) -> list[FrequentPlace]:
        """获取高频目的地（按总访问次数排序）"""
        return self.backend.get_frequent_destinations(top_k)

    def get_linked_events(self, link_group: str) -> list[Event]:
        """获取同一关联组的所有事件"""
        return self.backend.get_events_by_group(link_group)

    # ═══════════════════════════════════════════════
    # L3 长期偏好 — 读写
    # ═══════════════════════════════════════════════

    def save_preference(
        self,
        key: str,
        value: str,
        source: str = "slot_extraction",
        confidence: float = 1.0,
    ) -> None:
        """写入偏好。已存在则 heat+1（合并策略在 backend 层）"""
        pref = Preference(
            key=key,
            value=value,
            source=source,
            confidence=confidence,
        )
        self.backend.upsert_preference(pref)

    def get_preference(self, key: str) -> str | None:
        """读取偏好值（同时 heat+1）"""
        pref = self.backend.get_preference(key)
        return pref.value if pref else None

    def get_preference_obj(self, key: str) -> Preference | None:
        """读取完整偏好对象"""
        return self.backend.get_preference(key)

    def get_active_preferences(self, top_k: int = 10) -> list[Preference]:
        """
        获取活跃偏好（带时间衰减排序）。
        用于注入 LLM prompt / DST 构建。
        """
        prefs = self.backend.get_all_preferences()

        now = datetime.now()
        for p in prefs:
            ts = p.last_used_at or p.updated_at or p.created_at
            decay = time_decay(
                ts,
                half_life_days=self.config.decay_half_life_days,
                alpha=self.config.decay_alpha,
                now=now,
            )
            p.heat = p.heat * decay  # heat 本身是访问次数，乘以衰减

        prefs.sort(key=lambda p: p.heat, reverse=True)
        return prefs[:top_k]

    # ═══════════════════════════════════════════════
    # 统一检索（跨 L2 + L3）
    # ═══════════════════════════════════════════════

    def recall(self, query: str, top_k: int = 10) -> list[MemoryHit]:
        """
        统一检索：同时查 L2 行程 + L3 偏好 + 高频地点，合并排序。
        这是 DST / context_builder 最常用的接口。
        """
        hits: list[MemoryHit] = []

        # L2: 行程事件
        events = self.query_events(query=query, limit=top_k)
        for e in events:
            hits.append(
                MemoryHit(
                    source="episodic",
                    content=e.summary,
                    score=e.heat,
                    data={
                        "event_type": e.event_type,
                        "timestamp": e.timestamp,
                        "details": e.details,
                        "dedup_count": e.dedup_count,
                    },
                    timestamp=e.timestamp,
                )
            )

        # L3: 偏好
        prefs = self.get_active_preferences(top_k=top_k)
        query_lower = query.lower()
        for p in prefs:
            # 简单相关性：key 或 value 包含查询词
            if query_lower in p.key.lower() or query_lower in p.value.lower():
                hits.append(
                    MemoryHit(
                        source="preference",
                        content=f"{p.key} = {p.value}",
                        score=p.heat,
                        data={"key": p.key, "value": p.value, "source": p.source},
                        timestamp=p.updated_at,
                    )
                )

        # 高频地点
        freq = self.get_frequent_destinations(top_k=3)
        for f in freq:
            if query_lower in f.name.lower():
                hits.append(
                    MemoryHit(
                        source="frequent_place",
                        content=f"{f.name}（去过{f.visit_count}次）",
                        score=float(f.visit_count),
                        data={"name": f.name, "visit_count": f.visit_count},
                        timestamp=f.last_visit,
                    )
                )

        # 合并排序
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    # ═══════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════

    def decay_all(self) -> int:
        """
        批量衰减：删除热度极低的已分析事件。
        建议每次 session 开始时调用。
        """
        return self.backend.cleanup_events(min_heat=0.05)

    def should_evolve(self) -> bool:
        """检查未分析事件总热度是否超过阈值"""
        total = self.backend.get_unanalyzed_heat()
        return total >= self.config.heat_threshold_for_evolution

    def get_unanalyzed_events(self) -> list[Event]:
        """获取未分析事件（供 evolve_preferences 使用）"""
        return self.backend.get_unanalyzed_events()

    def mark_events_analyzed(self, event_ids: list[int]) -> None:
        """标记事件为已分析"""
        self.backend.mark_events_analyzed(event_ids)

    # ═══════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════

    def _get_meta(self, event_type: str) -> dict:
        """获取 event_type 的记忆元数据（从注入的 config 读）"""
        return self.config.memory_meta.get(event_type, {})

    def _compute_dedup_hash(
        self, event_type: str, details: dict, summary: str = ""
    ) -> str:
        """
        计算去重指纹。

        策略：event_type + details 中 dedup_key 声明的字段值。
        dedup_key 由 skill schema 的 memory_meta 声明（SSOT），通过 config 注入。
        """
        meta = self._get_meta(event_type)
        dedup_key = meta.get("dedup_key", "")

        key = details.get(dedup_key, "") if dedup_key else ""

        # 兜底：从 summary 提取（去停用词）
        if not key and summary:
            key = re.sub(r"[的了去到过在]", "", summary).strip()

        return f"{event_type}:{key.strip().lower()}"

    def _compute_link_group(self, event_type: str, details: dict) -> str:
        """
        计算关联分组。

        link_key 由 skill schema 的 memory_meta 声明（SSOT），通过 config 注入。
        """
        meta = self._get_meta(event_type)
        link_key = meta.get("link_key", "")
        if link_key:
            val = details.get(link_key, "")
            return val.strip().lower() if val else ""
        return ""

    def log_event_from_results(self, task_results: list[dict]) -> None:
        """
        从 task_results 自动提取并记录事件。
        兼容旧 auto_log_from_task_results 的调用方式。
        """
        for r in task_results:
            intent = r.get("intent", "")
            meta = self._get_meta(intent)
            if not meta.get("log", False):
                continue

            tool_result = r.get("tool_result", {})
            summary = self._extract_summary(intent, tool_result)
            if summary:
                details = self._extract_details(intent, tool_result)
                self.log_event(intent, summary, details)

    def _extract_summary(self, intent: str, tool_result: dict) -> str | None:
        """从工具结果提取摘要。使用 config.memory_meta 的 summary_template（SSOT）。"""
        if not tool_result:
            return None

        meta = self._get_meta(intent)
        if not meta:
            return None

        # 优先用 summary_template
        template = meta.get("summary_template", "")
        if template:
            values = _template_values(tool_result)
            try:
                return template.format_map(defaultdict(str, values))
            except (KeyError, IndexError):
                pass

        # 兜底：用 summary_templates 字典按场景匹配
        templates = meta.get("summary_templates", {})
        if templates:
            for key, tmpl in templates.items():
                if key == "default":
                    continue
                if tool_result.get(key):
                    values = _template_values(tool_result)
                    try:
                        return tmpl.format_map(values)
                    except (KeyError, IndexError):
                        continue
            # default 模板
            default_tmpl = templates.get("default", "")
            if default_tmpl:
                try:
                    return default_tmpl.format_map(_template_values(tool_result))
                except (KeyError, IndexError):
                    pass

        return None

    def _extract_details(self, intent: str, tool_result: dict) -> dict:
        """从工具结果提取结构化详情。使用 config.memory_meta 的 detail_fields（SSOT）。"""
        meta = self._get_meta(intent)
        if not meta:
            return {}
        fields = meta.get("detail_fields", [])
        if not fields:
            return {}
        return {k: v for k, v in tool_result.items() if k in fields}
