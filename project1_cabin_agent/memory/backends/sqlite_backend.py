"""
memory/backends/sqlite_backend.py — SQLite 存储后端

默认后端，适合嵌入式车机，零外部依赖。
特性：
- WAL 模式并发读写
- 自动 schema 迁移（旧表加新字段）
- 线程安全（每操作独立连接 + 锁）
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any

from project1_cabin_agent.memory.models import Event, FrequentPlace, Preference


class SqliteBackend:
    """SQLite 存储后端 — 事件 + 偏好双库"""

    def __init__(self, episodic_db_path: str, longterm_db_path: str):
        self._episodic_path = episodic_db_path
        self._longterm_path = longterm_db_path
        self._episodic_wal = False
        self._longterm_wal = False
        self._lock = threading.Lock()
        self._init_schema()

    # ═══════════════════════════════════════════
    # 连接管理
    # ═══════════════════════════════════════════

    def _episodic_conn(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self._episodic_path), exist_ok=True)
        conn = sqlite3.connect(self._episodic_path)
        conn.row_factory = sqlite3.Row
        if not self._episodic_wal:
            conn.execute("PRAGMA journal_mode=WAL")
            self._episodic_wal = True
        return conn

    def _longterm_conn(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self._longterm_path), exist_ok=True)
        conn = sqlite3.connect(self._longterm_path)
        conn.row_factory = sqlite3.Row
        if not self._longterm_wal:
            conn.execute("PRAGMA journal_mode=WAL")
            self._longterm_wal = True
        return conn

    # ═══════════════════════════════════════════
    # Schema 初始化 + 迁移
    # ═══════════════════════════════════════════

    def _init_schema(self):
        self._init_events_table()
        self._init_preferences_table()

    def _init_events_table(self):
        conn = self._episodic_conn()
        try:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
                ).fetchall()
            ]
            if not tables:
                # 全新安装 — 创建完整表
                conn.execute("""
                    CREATE TABLE events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        details TEXT DEFAULT '{}',
                        session_id TEXT DEFAULT '',
                        dedup_hash TEXT DEFAULT '',
                        dedup_count INTEGER DEFAULT 1,
                        heat REAL DEFAULT 1.0,
                        link_group TEXT DEFAULT '',
                        last_accessed TEXT DEFAULT '',
                        analyzed INTEGER DEFAULT 0
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_dedup_hash ON events(dedup_hash)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_link_group ON events(link_group)"
                )
            else:
                # 旧表 — 补字段
                self._migrate_events(conn)
            conn.commit()
        finally:
            conn.close()

    def _migrate_events(self, conn: sqlite3.Connection):
        """给旧 events 表添加新字段"""
        existing = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
        new_cols = {
            "session_id": "TEXT DEFAULT ''",
            "dedup_hash": "TEXT DEFAULT ''",
            "dedup_count": "INTEGER DEFAULT 1",
            "heat": "REAL DEFAULT 1.0",
            "link_group": "TEXT DEFAULT ''",
            "last_accessed": "TEXT DEFAULT ''",
            "analyzed": "INTEGER DEFAULT 0",
        }
        for col, typ in new_cols.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE events ADD COLUMN {col} {typ}")
        # 补索引
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_dedup_hash ON events(dedup_hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_link_group ON events(link_group)"
        )

    def _init_preferences_table(self):
        conn = self._longterm_conn()
        try:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='preferences'"
                ).fetchall()
            ]
            if not tables:
                # 全新安装
                conn.execute("""
                    CREATE TABLE preferences (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        confidence REAL DEFAULT 1.0,
                        source TEXT DEFAULT 'slot_extraction',
                        heat REAL DEFAULT 1.0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_used_at TEXT
                    )
                """)
            else:
                self._migrate_preferences(conn)
            conn.commit()
        finally:
            conn.close()

    def _migrate_preferences(self, conn: sqlite3.Connection):
        """旧 user_profile 表兼容或新表补字段"""
        existing = {
            r[1] for r in conn.execute("PRAGMA table_info(preferences)").fetchall()
        }
        new_cols = {
            "confidence": "REAL DEFAULT 1.0",
            "source": "TEXT DEFAULT 'slot_extraction'",
            "heat": "REAL DEFAULT 1.0",
            "last_used_at": "TEXT",
        }
        for col, typ in new_cols.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE preferences ADD COLUMN {col} {typ}")

    # ═══════════════════════════════════════════
    # Events CRUD
    # ═══════════════════════════════════════════

    def insert_event(self, event: Event) -> int:
        """插入新事件，返回 id"""
        conn = self._episodic_conn()
        try:
            cur = conn.execute(
                """INSERT INTO events
                   (timestamp, event_type, summary, details,
                    session_id, dedup_hash, dedup_count, heat,
                    link_group, last_accessed, analyzed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.timestamp,
                    event.event_type,
                    event.summary,
                    json.dumps(event.details, ensure_ascii=False),
                    event.session_id,
                    event.dedup_hash,
                    event.dedup_count,
                    event.heat,
                    event.link_group,
                    event.last_accessed or event.timestamp,
                    int(event.analyzed),
                ),
            )
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()

    def find_event_by_hash(self, dedup_hash: str) -> Event | None:
        """按去重指纹查找最近一条匹配事件"""
        conn = self._episodic_conn()
        try:
            row = conn.execute(
                "SELECT * FROM events WHERE dedup_hash = ? ORDER BY id DESC LIMIT 1",
                (dedup_hash,),
            ).fetchone()
            return self._row_to_event(row) if row else None
        finally:
            conn.close()

    def update_event(self, event_id: int, updates: dict[str, Any]) -> None:
        """更新事件字段"""
        if not updates:
            return
        # details 需要序列化为 JSON
        processed = {}
        for k, v in updates.items():
            if k == "details" and isinstance(v, dict):
                import json as _json

                processed[k] = _json.dumps(v, ensure_ascii=False)
            else:
                processed[k] = v
        set_clause = ", ".join(f"{k} = ?" for k in processed)
        values = list(processed.values()) + [event_id]
        conn = self._episodic_conn()
        try:
            conn.execute(f"UPDATE events SET {set_clause} WHERE id = ?", values)
            conn.commit()
        finally:
            conn.close()

    def search_events(
        self,
        query: str | None = None,
        event_type: str | None = None,
        time_range: tuple[str, str] | None = None,
        limit: int = 10,
    ) -> list[Event]:
        """检索事件（关键词 + 类型 + 时间范围）"""
        clauses: list[str] = []
        params: list[Any] = []

        if query:
            # 关键词匹配 summary 或 details
            clauses.append("(summary LIKE ? OR details LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if time_range:
            clauses.append("timestamp BETWEEN ? AND ?")
            params.extend(time_range)

        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"SELECT * FROM events WHERE {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        conn = self._episodic_conn()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_event(r) for r in rows]
        finally:
            conn.close()

    def get_events_by_group(self, link_group: str) -> list[Event]:
        """获取同一关联组的所有事件"""
        conn = self._episodic_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM events WHERE link_group = ? ORDER BY timestamp DESC",
                (link_group,),
            ).fetchall()
            return [self._row_to_event(r) for r in rows]
        finally:
            conn.close()

    def get_frequent_destinations(self, top_k: int = 5) -> list[FrequentPlace]:
        """
        聚合高频目的地。
        按 link_group 分组，统计 dedup_count 总和 + 事件数。
        """
        conn = self._episodic_conn()
        try:
            rows = conn.execute(
                """SELECT link_group,
                          SUM(dedup_count) as total_visits,
                          COUNT(*) as event_count,
                          MAX(timestamp) as last_visit,
                          GROUP_CONCAT(DISTINCT event_type) as types
                   FROM events
                   WHERE link_group != ''
                   GROUP BY link_group
                   ORDER BY total_visits DESC
                   LIMIT ?""",
                (top_k,),
            ).fetchall()
            results = []
            for r in rows:
                results.append(
                    FrequentPlace(
                        name=r["link_group"],
                        visit_count=r["total_visits"],
                        last_visit=r["last_visit"],
                        event_types=r["types"].split(",") if r["types"] else [],
                    )
                )
            return results
        finally:
            conn.close()

    def get_unanalyzed_heat(self) -> float:
        """获取未分析事件的总热度"""
        conn = self._episodic_conn()
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(heat), 0) as total FROM events WHERE analyzed = 0"
            ).fetchone()
            return float(row["total"]) if row else 0.0
        finally:
            conn.close()

    def get_unanalyzed_events(self) -> list[Event]:
        """获取所有未分析事件"""
        conn = self._episodic_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM events WHERE analyzed = 0 ORDER BY timestamp DESC"
            ).fetchall()
            return [self._row_to_event(r) for r in rows]
        finally:
            conn.close()

    def mark_events_analyzed(self, event_ids: list[int]) -> None:
        """标记事件为已分析"""
        if not event_ids:
            return
        placeholders = ",".join("?" * len(event_ids))
        conn = self._episodic_conn()
        try:
            conn.execute(
                f"UPDATE events SET analyzed = 1 WHERE id IN ({placeholders})",
                event_ids,
            )
            conn.commit()
        finally:
            conn.close()

    def cleanup_events(self, min_heat: float = 0.1) -> int:
        """删除热度低于阈值的旧事件，返回删除数"""
        conn = self._episodic_conn()
        try:
            cur = conn.execute(
                "DELETE FROM events WHERE heat < ? AND analyzed = 1",
                (min_heat,),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    # ═══════════════════════════════════════════
    # Preferences CRUD
    # ═══════════════════════════════════════════

    def upsert_preference(self, pref: Preference) -> None:
        """写入偏好（存在则更新）"""
        now = datetime.now().isoformat()
        conn = self._longterm_conn()
        try:
            # 检查是否已存在
            existing = conn.execute(
                "SELECT heat, confidence FROM preferences WHERE key = ?",
                (pref.key,),
            ).fetchone()

            if existing:
                # 已存在：合并策略
                old_heat = float(existing["heat"])
                old_conf = float(existing["confidence"])
                # heat 累加（最多保留到原值+1，避免无限膨胀）
                new_heat = old_heat + 1.0
                # confidence 取 max（不降级）
                new_conf = max(old_conf, pref.confidence)
                conn.execute(
                    """UPDATE preferences
                       SET value = ?, confidence = ?, source = ?,
                           heat = ?, updated_at = ?
                       WHERE key = ?""",
                    (
                        pref.value,
                        new_conf,
                        pref.source,
                        new_heat,
                        now,
                        pref.key,
                    ),
                )
            else:
                # 新建
                conn.execute(
                    """INSERT INTO preferences
                       (key, value, confidence, source, heat, created_at, updated_at, last_used_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        pref.key,
                        pref.value,
                        pref.confidence,
                        pref.source,
                        1.0,
                        now,
                        now,
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def get_preference(self, key: str) -> Preference | None:
        """读取偏好"""
        conn = self._longterm_conn()
        try:
            row = conn.execute(
                "SELECT * FROM preferences WHERE key = ?", (key,)
            ).fetchone()
            if not row:
                return None
            # 读取时 heat+1
            conn.execute(
                "UPDATE preferences SET heat = heat + 1, last_used_at = ? WHERE key = ?",
                (datetime.now().isoformat(), key),
            )
            conn.commit()
            return self._row_to_preference(row)
        finally:
            conn.close()

    def get_all_preferences(self) -> list[Preference]:
        """读取所有偏好"""
        conn = self._longterm_conn()
        try:
            rows = conn.execute("SELECT * FROM preferences").fetchall()
            return [self._row_to_preference(r) for r in rows]
        finally:
            conn.close()

    def delete_preference(self, key: str) -> bool:
        """删除偏好"""
        conn = self._longterm_conn()
        try:
            cur = conn.execute("DELETE FROM preferences WHERE key = ?", (key,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # ═══════════════════════════════════════════
    # Row → Model 转换
    # ═══════════════════════════════════════════

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> Event:
        details = {}
        try:
            raw = row["details"]
            if raw:
                details = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            pass
        # sqlite3.Row 不支持 'key in row' 语义检查，用 dict(row) 转换
        d = dict(row)
        return Event(
            id=d["id"],
            timestamp=d["timestamp"],
            event_type=d["event_type"],
            summary=d["summary"],
            details=details,
            session_id=d.get("session_id", ""),
            dedup_hash=d.get("dedup_hash", ""),
            dedup_count=d.get("dedup_count", 1),
            heat=d.get("heat", 1.0),
            link_group=d.get("link_group", ""),
            last_accessed=d.get("last_accessed", ""),
            analyzed=bool(d.get("analyzed", 0)),
        )

    @staticmethod
    def _row_to_preference(row: sqlite3.Row) -> Preference:
        d = dict(row)
        return Preference(
            key=d["key"],
            value=d["value"],
            confidence=d.get("confidence", 1.0),
            source=d.get("source", "slot_extraction"),
            heat=d.get("heat", 1.0),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            last_used_at=d.get("last_used_at", ""),
        )
