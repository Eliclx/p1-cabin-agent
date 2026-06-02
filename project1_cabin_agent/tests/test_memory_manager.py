"""
tests/test_memory_manager.py — MemoryManager Phase 4A 测试

覆盖：去重 / 热度 / 链接 / 衰减 / 偏好 / 高频地点 / recall
"""

import os
import tempfile
from datetime import datetime, timedelta

import pytest

from project1_cabin_agent.memory.decay import score_with_decay, time_decay
from project1_cabin_agent.memory.manager import MemoryManager
from project1_cabin_agent.memory.models import MemoryConfig

# 测试用的 memory_meta（和 skill schema 声明一致）
_TEST_MEMORY_META = {
    "navigate": {
        "log": True,
        "dedup_key": "destination",
        "link_key": "destination",
        "summary_template": "导航去{destination}",
        "detail_fields": ["destination", "route_type", "distance", "toll", "duration"],
    },
    "search_poi": {
        "log": True,
        "dedup_key": "keyword",
        "link_key": "keyword",
        "summary_template": "搜索了{keyword}({count}个结果)",
        "detail_fields": ["keyword", "category"],
    },
    "media_control": {
        "log": True,
        "dedup_key": "query",
        "link_key": "",
        "summary_templates": {
            "query": "播放了{query}",
            "artist": "播放了{artist}的歌",
            "default": "媒体操作: {action}",
        },
        "detail_fields": ["query", "artist", "action"],
    },
    "weather": {
        "log": True,
        "dedup_key": "city",
        "link_key": "",
        "summary_template": "查询了{city}天气: {weather}",
        "detail_fields": ["city", "weather", "temperature"],
    },
}


@pytest.fixture
def memory():
    """每个测试用独立的 MemoryManager + 临时数据库"""
    tmpdir = tempfile.mkdtemp()
    cfg = MemoryConfig(
        episodic_db_path=os.path.join(tmpdir, "events.db"),
        longterm_db_path=os.path.join(tmpdir, "prefs.db"),
        decay_half_life_days=14.0,
        decay_alpha=0.3,
        heat_threshold_for_evolution=10.0,
        memory_meta=_TEST_MEMORY_META,
    )
    m = MemoryManager(cfg)
    yield m
    # 清理
    for f in os.listdir(tmpdir):
        os.remove(os.path.join(tmpdir, f))
    os.rmdir(tmpdir)


# ═══════════════════════════════════════════════
# 时间衰减
# ═══════════════════════════════════════════════


class TestDecay:
    def test_fresh_event_high_score(self):
        """新事件的衰减系数接近 1.0"""
        now = datetime.now().isoformat()
        score = time_decay(now)
        assert score > 0.95

    def test_old_event_decayed(self):
        """14天前的事件衰减到约 0.8"""
        old = (datetime.now() - timedelta(days=14)).isoformat()
        score = time_decay(old)
        # 0.3 + 0.7 * 0.5^1 = 0.65
        assert 0.6 < score < 0.7

    def test_very_old_event_alpha_floor(self):
        """很久以前的事件不低于 alpha=0.3"""
        very_old = (datetime.now() - timedelta(days=365)).isoformat()
        score = time_decay(very_old)
        assert score >= 0.3

    def test_score_with_decay(self):
        """heat=5 + 新事件 → 接近 5.0"""
        now = datetime.now().isoformat()
        score = score_with_decay(5.0, now)
        assert score > 4.5

    def test_score_with_decay_old(self):
        """heat=5 + 14天前 → 约 3.25"""
        old = (datetime.now() - timedelta(days=14)).isoformat()
        score = score_with_decay(5.0, old)
        assert 3.0 < score < 3.5


# ═══════════════════════════════════════════════
# 事件写入 + 去重
# ═══════════════════════════════════════════════


class TestEventWrite:
    def test_log_new_event(self, memory):
        """新事件正常写入"""
        result = memory.log_event(
            "navigate", "导航去天府广场", {"destination": "天府广场"}
        )
        assert result == "new"

    def test_log_dedup_same_destination(self, memory):
        """相同目的地 → 去重，heat+1"""
        memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        result = memory.log_event(
            "navigate", "导航去天府广场", {"destination": "天府广场"}
        )
        assert result == "dedup"

        # 应该只有一条记录
        events = memory.query_events()
        assert len(events) == 1
        assert events[0].dedup_count == 2
        assert events[0].heat == 2.0

    def test_log_different_destination_not_dedup(self, memory):
        """不同目的地 → 新建"""
        memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        result = memory.log_event("navigate", "导航去春熙路", {"destination": "春熙路"})
        assert result == "new"

        events = memory.query_events()
        assert len(events) == 2

    def test_log_skips_non_whitelist(self, memory):
        """非白名单事件类型静默跳过"""
        result = memory.log_event("chitchat", "你好")
        assert result == "skipped"

    def test_log_multiple_types(self, memory):
        """多种事件类型共存"""
        memory.log_event("navigate", "导航去重庆", {"destination": "重庆"})
        memory.log_event("weather", "查询了成都天气: 晴", {"city": "成都"})
        memory.log_event("search_poi", "搜索了加油站", {"keyword": "加油站"})

        events = memory.query_events()
        assert len(events) == 3


# ═══════════════════════════════════════════════
# 事件检索 + 衰减排序
# ═══════════════════════════════════════════════


class TestEventQuery:
    def test_query_by_keyword(self, memory):
        """关键词检索"""
        memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        memory.log_event("navigate", "导航去重庆", {"destination": "重庆"})

        events = memory.query_events(query="天府")
        assert len(events) == 1
        assert "天府广场" in events[0].summary

    def test_query_by_event_type(self, memory):
        """按类型过滤"""
        memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        memory.log_event("weather", "查询了成都天气", {"city": "成都"})

        events = memory.query_events(event_type="weather")
        assert len(events) == 1
        assert events[0].event_type == "weather"

    def test_query_hot_first(self, memory):
        """热门事件排前面"""
        # 天府广场去了 5 次
        for _ in range(5):
            memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        # 重庆去了 1 次
        memory.log_event("navigate", "导航去重庆", {"destination": "重庆"})

        events = memory.query_events()
        assert len(events) == 2
        # 天府广场 heat=5 > 重庆 heat=1
        assert "天府广场" in events[0].summary


# ═══════════════════════════════════════════════
# 关联分组 + 高频目的地
# ═══════════════════════════════════════════════


class TestLinkGroup:
    def test_same_destination_linked(self, memory):
        """同目的地的导航自动链接"""
        memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        memory.log_event("search_poi", "搜索了天府广场附近", {"keyword": "天府广场"})

        linked = memory.get_linked_events("天府广场")
        assert len(linked) == 2

    def test_frequent_destinations(self, memory):
        """高频目的地聚合"""
        for _ in range(5):
            memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        memory.log_event("navigate", "导航去重庆", {"destination": "重庆"})

        freq = memory.get_frequent_destinations(top_k=5)
        assert len(freq) >= 1
        # 天府广场访问最多
        assert freq[0].name == "天府广场"
        assert freq[0].visit_count >= 5


# ═══════════════════════════════════════════════
# 偏好读写
# ═══════════════════════════════════════════════


class TestPreference:
    def test_save_and_get(self, memory):
        """写入 + 读取"""
        memory.save_preference("ac_temperature", "24")
        val = memory.get_preference("ac_temperature")
        assert val == "24"

    def test_get_nonexistent(self, memory):
        """读取不存在的偏好返回 None"""
        assert memory.get_preference("nonexistent") is None

    def test_heat_on_read(self, memory):
        """读取时 heat 增加"""
        memory.save_preference("ac_temperature", "24")
        _ = memory.get_preference("ac_temperature")
        _ = memory.get_preference("ac_temperature")

        pref = memory.get_preference_obj("ac_temperature")
        # save heat=1, read×2 heat=3+1=4 (backend upsert heat+1 + read heat+1)
        assert pref.heat >= 3

    def test_update_preference(self, memory):
        """更新偏好值"""
        memory.save_preference("route_type", "fastest")
        memory.save_preference("route_type", "avoid_toll")

        val = memory.get_preference("route_type")
        assert val == "avoid_toll"

    def test_active_preferences_sorted(self, memory):
        """活跃偏好按 heat 排序"""
        memory.save_preference("pref_a", "a")
        memory.save_preference("pref_b", "b")
        # 让 pref_b 热度更高
        _ = memory.get_preference("pref_b")
        _ = memory.get_preference("pref_b")

        prefs = memory.get_active_preferences()
        assert prefs[0].key == "pref_b"  # heat 更高排前面


# ═══════════════════════════════════════════════
# 统一检索 recall
# ═══════════════════════════════════════════════


class TestRecall:
    def test_recall_cross_layer(self, memory):
        """recall 同时查 L2 + L3"""
        memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        memory.save_preference("route_type", "avoid_toll")

        hits = memory.recall("天府")
        # 至少有行程事件
        assert len(hits) >= 1
        assert any(h.source == "episodic" for h in hits)

    def test_recall_sorted_by_score(self, memory):
        """recall 结果按 score 降序"""
        for _ in range(5):
            memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        memory.log_event("navigate", "导航去春熙路", {"destination": "春熙路"})

        hits = memory.recall("导航")
        if len(hits) >= 2:
            assert hits[0].score >= hits[1].score


# ═══════════════════════════════════════════════
# 生命周期
# ═══════════════════════════════════════════════


class TestLifecycle:
    def test_should_evolve_below_threshold(self, memory):
        """热度不够 → 不触发进化"""
        memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        assert memory.should_evolve() is False

    def test_should_evolve_above_threshold(self, memory):
        """热度超过阈值 → 触发进化"""
        for _ in range(12):
            memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        assert memory.should_evolve() is True

    def test_mark_analyzed(self, memory):
        """标记已分析"""
        memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        events = memory.get_unanalyzed_events()
        assert len(events) >= 1

        memory.mark_events_analyzed([e.id for e in events])
        events2 = memory.get_unanalyzed_events()
        assert len(events2) == 0

    def test_log_event_from_results(self, memory):
        """从 task_results 自动提取事件"""
        task_results = [
            {
                "intent": "navigate",
                "tool_result": {"destination": "天府广场", "distance": "5km"},
            },
            {"intent": "chitchat", "tool_result": {}},
        ]
        memory.log_event_from_results(task_results)

        events = memory.query_events()
        assert len(events) == 1
        assert "天府广场" in events[0].summary


# ═══════════════════════════════════════════════
# 旧表兼容
# ═══════════════════════════════════════════════


class TestBackwardCompat:
    def test_old_events_table_migration(self, memory):
        """旧 events 表（无新字段）自动迁移"""
        # 直接往 SQLite 插入旧格式数据（模拟旧表）
        import sqlite3

        conn = sqlite3.connect(memory.backend._episodic_path)
        # 手动插入一条旧格式数据（不带新字段）
        conn.execute(
            "INSERT INTO events (timestamp, event_type, summary, details) "
            "VALUES (?, ?, ?, ?)",
            (
                "2026-01-01T10:00:00",
                "navigate",
                "导航去公司",
                '{"destination": "公司"}',
            ),
        )
        conn.commit()
        conn.close()

        # 新 MemoryManager 应该能读取
        events = memory.query_events(event_type="navigate")
        assert len(events) >= 1
        # 旧数据的新字段应该是默认值
        old_event = [e for e in events if "公司" in e.summary][0]
        assert old_event.dedup_hash == ""  # 旧数据没有 dedup_hash
        assert old_event.heat == 1.0  # 默认值
