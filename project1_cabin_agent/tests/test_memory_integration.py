"""
tests/test_memory_integration.py — 记忆模块集成测试

验证：
1. skill schema 声明 → registry 发现 → memory_meta 注入 → MemoryManager 全链路
2. 新增 skill 只需声明，memory 代码零改动
3. memory/ 模块独立运行（不依赖 registry）
"""

import os
import tempfile

import pytest

from project1_cabin_agent.memory import (
    MemoryManager,
    MemoryConfig,
    create_memory_manager,
)
from project1_cabin_agent.skills.registry import registry


# ═══════════════════════════════════════════════════════════════
# 1. Registry → Memory 全链路
# ═══════════════════════════════════════════════════════════════


class TestRegistryMetaDiscovery:
    """验证 registry 能正确发现所有 skill schema 的 memory_meta"""

    def test_all_skills_have_memory_meta(self):
        """4 个 skill 域都声明了 _MEMORY"""
        all_meta = registry.get_all_memory_meta()
        # 11 个 intent（map 4 + climate 5 + media 1 + vehicle 1）
        assert len(all_meta) >= 10

    def test_navigate_meta_complete(self):
        """navigate intent 的 meta 包含所有必要字段"""
        meta = registry.get_memory_meta("navigate")
        assert meta is not None
        assert meta.get("log") is True
        assert meta.get("dedup_key") == "destination"
        assert meta.get("link_key") == "destination"
        assert "summary_template" in meta
        assert "detail_fields" in meta

    def test_control_intent_not_logged(self):
        """控制类 intent（ac_control）不记录"""
        meta = registry.get_memory_meta("ac_control")
        assert meta is not None
        assert meta.get("log") is False

    def test_unknown_intent_returns_none(self):
        """未知 intent 返回 None"""
        assert registry.get_memory_meta("nonexistent") is None


class TestRegistryInjectMemory:
    """验证 registry 注入的 meta 能驱动 MemoryManager"""

    @pytest.fixture
    def memory(self):
        tmpdir = tempfile.mkdtemp()
        meta = registry.get_all_memory_meta()
        cfg = MemoryConfig(
            episodic_db_path=os.path.join(tmpdir, "events.db"),
            longterm_db_path=os.path.join(tmpdir, "prefs.db"),
            memory_meta=meta,
        )
        m = MemoryManager(cfg)
        yield m
        for f in os.listdir(tmpdir):
            os.remove(os.path.join(tmpdir, f))
        os.rmdir(tmpdir)

    def test_loggable_intent_accepted(self, memory):
        """log=True 的 intent 能写入"""
        result = memory.log_event("navigate", "导航去重庆", {"destination": "重庆"})
        assert result == "new"

    def test_non_loggable_intent_skipped(self, memory):
        """log=False 的 intent 被跳过"""
        result = memory.log_event("ac_control", "开空调", {"action": "on"})
        assert result == "skipped"

    def test_dedup_from_meta_dedup_key(self, memory):
        """dedup_key=destination 驱动去重"""
        memory.log_event("navigate", "导航去重庆", {"destination": "重庆"})
        result = memory.log_event("navigate", "再次导航去重庆", {"destination": "重庆"})
        assert result == "dedup"

    def test_different_dest_not_dedup(self, memory):
        """不同 destination 不去重"""
        memory.log_event("navigate", "导航去重庆", {"destination": "重庆"})
        result = memory.log_event("navigate", "导航去成都", {"destination": "成都"})
        assert result == "new"

    def test_summary_from_template(self, memory):
        """summary_template 驱动摘要生成"""
        s = memory._extract_summary("navigate", {"destination": "天府广场"})
        assert "天府广场" in s

    def test_summary_weather_template(self, memory):
        """weather 的 summary_template 包含城市和天气"""
        s = memory._extract_summary("weather", {"city": "成都", "weather": "晴"})
        assert "成都" in s
        assert "晴" in s

    def test_summary_media_templates(self, memory):
        """media_control 用 summary_templates 字典匹配"""
        s = memory._extract_summary("media_control", {"query": "七里香"})
        assert "七里香" in s

    def test_details_filter_by_detail_fields(self, memory):
        """detail_fields 驱动详情过滤"""
        d = memory._extract_details(
            "navigate",
            {"destination": "重庆", "distance": "300km", "extra": "ignored"},
        )
        assert "destination" in d
        assert "distance" in d
        assert "extra" not in d

    def test_log_event_from_results_integration(self, memory):
        """log_event_from_results 完整链路"""
        results = [
            {
                "intent": "navigate",
                "tool_result": {"destination": "重庆", "distance": "300km"},
            },
            {
                "intent": "ac_control",  # log=False，跳过
                "tool_result": {"action": "on"},
            },
        ]
        memory.log_event_from_results(results)
        events = memory.query_events(query="重庆")
        assert len(events) == 1

    def test_link_group_from_meta(self, memory):
        """link_key=destination 驱动链接分组"""
        memory.log_event("navigate", "导航去重庆", {"destination": "重庆"})
        memory.log_event(
            "search_poi", "搜索加油站", {"keyword": "加油站", "destination": "重庆"}
        )
        places = memory.get_frequent_destinations()
        assert len(places) >= 1


# ═══════════════════════════════════════════════════════════════
# 2. 新增 Skill 场景模拟
# ═══════════════════════════════════════════════════════════════


class TestNewSkillScenario:
    """模拟新增一个 parking skill，memory 代码零改动"""

    @pytest.fixture
    def memory(self):
        tmpdir = tempfile.mkdtemp()
        # 模拟：新增 parking skill 后，只需在 schema 里声明
        meta = registry.get_all_memory_meta()
        meta["parking"] = {
            "log": True,
            "dedup_key": "location",
            "link_key": "location",
            "summary_template": "停在了{location}",
            "detail_fields": ["location", "duration", "fee"],
        }
        cfg = MemoryConfig(
            episodic_db_path=os.path.join(tmpdir, "events.db"),
            longterm_db_path=os.path.join(tmpdir, "prefs.db"),
            memory_meta=meta,
        )
        m = MemoryManager(cfg)
        yield m
        for f in os.listdir(tmpdir):
            os.remove(os.path.join(tmpdir, f))
        os.rmdir(tmpdir)

    def test_new_skill_loggable(self, memory):
        """新 skill 的 intent 能写入"""
        result = memory.log_event("parking", "停在了万象城", {"location": "万象城"})
        assert result == "new"

    def test_new_skill_dedup(self, memory):
        """新 skill 的 dedup_key 驱动去重"""
        memory.log_event("parking", "停在了万象城", {"location": "万象城"})
        result = memory.log_event("parking", "又停万象城", {"location": "万象城"})
        assert result == "dedup"

    def test_new_skill_summary(self, memory):
        """新 skill 的 summary_template 驱动摘要"""
        s = memory._extract_summary("parking", {"location": "万象城"})
        assert s == "停在了万象城"

    def test_new_skill_details(self, memory):
        """新 skill 的 detail_fields 驱动过滤"""
        d = memory._extract_details(
            "parking",
            {"location": "万象城", "duration": "2h", "fee": "20元", "extra": "ignore"},
        )
        assert set(d.keys()) == {"location", "duration", "fee"}

    def test_new_skill_link_group(self, memory):
        """新 skill 的 link_key 驱动分组"""
        memory.log_event("parking", "停在了万象城", {"location": "万象城"})
        memory.log_event("parking", "又停万象城", {"location": "万象城"})
        places = memory.get_frequent_destinations()
        assert len(places) >= 1


# ═══════════════════════════════════════════════════════════════
# 3. Memory 模块独立性
# ═══════════════════════════════════════════════════════════════


class TestMemoryIndependence:
    """验证 memory/ 不依赖 skills/nodes 等上层模块"""

    def test_memory_no_skills_import(self):
        """memory 包的 import 树不包含 skills"""
        import project1_cabin_agent.memory.manager as mgr
        import inspect

        source = inspect.getsource(mgr)
        assert "skills" not in source
        assert "registry" not in source

    def test_memory_works_with_custom_meta(self):
        """用完全自定义的 meta 创建 MemoryManager"""
        tmpdir = tempfile.mkdtemp()
        cfg = MemoryConfig(
            episodic_db_path=os.path.join(tmpdir, "e.db"),
            longterm_db_path=os.path.join(tmpdir, "p.db"),
            memory_meta={
                "fly_plane": {
                    "log": True,
                    "dedup_key": "airport",
                    "link_key": "airport",
                    "summary_template": "飞去了{airport}",
                    "detail_fields": ["airport", "airline"],
                },
            },
        )
        m = MemoryManager(cfg)
        result = m.log_event("fly_plane", "飞去了浦东", {"airport": "浦东"})
        assert result == "new"

        s = m._extract_summary("fly_plane", {"airport": "浦东"})
        assert s == "飞去了浦东"

        d = m._extract_details(
            "fly_plane", {"airport": "浦东", "airline": "东航", "extra": "no"}
        )
        assert set(d.keys()) == {"airport", "airline"}

    def test_create_memory_manager_factory(self):
        """create_memory_manager 工厂函数"""
        tmpdir = tempfile.mkdtemp()
        m = create_memory_manager(
            episodic_db_path=os.path.join(tmpdir, "e.db"),
            longterm_db_path=os.path.join(tmpdir, "p.db"),
            memory_meta={"test": {"log": True}},
        )
        assert isinstance(m, MemoryManager)
        assert m.config.memory_meta["test"]["log"] is True
