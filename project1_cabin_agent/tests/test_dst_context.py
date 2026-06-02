"""
tests/test_dst_context.py — Phase 4B DST + ContextBuilder 测试

覆盖：DialogueState / 态度推断 / goal 更新 / 摘要生成
"""

import os
import tempfile

import pytest

from project1_cabin_agent.memory import MemoryManager, MemoryConfig

# 测试用的 memory_meta（与 skill schema 声明一致）
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
from project1_cabin_agent.nodes.context_builder import (
    ContextBuilder,
    _infer_attitude,
)
from project1_cabin_agent.nodes.dialogue_state import (
    ActiveGoal,
    DialogueState,
    UserAttitude,
)


@pytest.fixture
def memory():
    tmpdir = tempfile.mkdtemp()
    cfg = MemoryConfig(
        episodic_db_path=os.path.join(tmpdir, "events.db"),
        longterm_db_path=os.path.join(tmpdir, "prefs.db"),
        memory_meta=_TEST_MEMORY_META,
    )
    m = MemoryManager(cfg)
    yield m
    for f in os.listdir(tmpdir):
        os.remove(os.path.join(tmpdir, f))
    os.rmdir(tmpdir)


@pytest.fixture
def builder(memory):
    return ContextBuilder(memory)


# ═══════════════════════════════════════════════
# DialogueState 数据结构
# ═══════════════════════════════════════════════


class TestDialogueState:
    def test_empty_state(self):
        ds = DialogueState()
        assert ds.get_primary_goal() is None
        assert ds.is_repeating() is False
        assert ds.get_entity("destination") is None

    def test_get_primary_goal(self):
        ds = DialogueState(
            active_goals=[
                ActiveGoal(goal_type="map", status="completed"),
                ActiveGoal(goal_type="search", status="active"),
            ]
        )
        goal = ds.get_primary_goal()
        assert goal is not None
        assert goal.goal_type == "search"

    def test_get_goal_by_type(self):
        ds = DialogueState(
            active_goals=[
                ActiveGoal(goal_type="map", slots={"destination": "重庆"}),
                ActiveGoal(goal_type="search"),
            ]
        )
        goal = ds.get_goal_by_type("map")
        assert goal is not None
        assert goal.slots["destination"] == "重庆"

    def test_is_repeating(self):
        ds = DialogueState(intent_history=["navigate", "navigate", "navigate"])
        assert ds.is_repeating() is True

    def test_not_repeating(self):
        ds = DialogueState(intent_history=["navigate", "ac_control", "navigate"])
        assert ds.is_repeating() is False

    def test_get_entity_from_key_entities(self):
        ds = DialogueState(key_entities={"destination": "重庆"})
        assert ds.get_entity("destination") == "重庆"

    def test_get_entity_from_goal(self):
        ds = DialogueState(
            active_goals=[
                ActiveGoal(goal_type="map", slots={"destination": "天府广场"}),
            ]
        )
        assert ds.get_entity("destination") == "天府广场"

    def test_get_entity_priority(self):
        # key_entities 优先于 goal.slots
        ds = DialogueState(
            key_entities={"destination": "重庆"},
            active_goals=[ActiveGoal(goal_type="map", slots={"destination": "成都"})],
        )
        assert ds.get_entity("destination") == "重庆"

    def test_model_dump_roundtrip(self):
        ds = DialogueState(
            turn_count=3,
            user_attitude=UserAttitude.UNSATISFIED,
            active_goals=[ActiveGoal(goal_type="map", attempt_count=2)],
        )
        dumped = ds.model_dump()
        restored = DialogueState(**dumped)
        assert restored.turn_count == 3
        assert restored.user_attitude == UserAttitude.UNSATISFIED
        assert restored.active_goals[0].attempt_count == 2


# ═══════════════════════════════════════════════
# 态度推断
# ═══════════════════════════════════════════════


class TestAttitudeInfer:
    def test_neutral(self):
        assert _infer_attitude("开空调") == UserAttitude.NEUTRAL
        assert _infer_attitude("导航去重庆") == UserAttitude.NEUTRAL

    def test_unsatisfied(self):
        assert _infer_attitude("太贵了") == UserAttitude.UNSATISFIED
        assert _infer_attitude("这个路线不好") == UserAttitude.UNSATISFIED

    def test_wants_alternative(self):
        assert _infer_attitude("有其他方案吗") == UserAttitude.WANTS_ALTERNATIVE
        assert _infer_attitude("换个路线") == UserAttitude.WANTS_ALTERNATIVE

    def test_wants_alternative_over_unsatisfied(self):
        # "太贵了有其他方案" → WANTS_ALTERNATIVE 优先
        assert _infer_attitude("太贵了有其他方案") == UserAttitude.WANTS_ALTERNATIVE

    def test_confused(self):
        assert _infer_attitude("什么意思") == UserAttitude.CONFUSED

    def test_correcting(self):
        assert _infer_attitude("不是，我是说国道") == UserAttitude.CORRECTING

    def test_satisfied(self):
        assert _infer_attitude("好的") == UserAttitude.SATISFIED
        assert _infer_attitude("谢谢") == UserAttitude.SATISFIED

    def test_empty_input(self):
        assert _infer_attitude("") == UserAttitude.NEUTRAL


# ═══════════════════════════════════════════════
# ContextBuilder — build_state
# ═══════════════════════════════════════════════


class TestBuildState:
    def test_first_turn(self, builder):
        """首轮：无历史"""
        state = {"user_input": "开空调", "task_results": [], "sub_tasks": []}
        ds = builder.build_state(state)
        assert ds.turn_count == 1
        assert ds.user_attitude == UserAttitude.NEUTRAL
        assert ds.get_primary_goal() is None

    def test_attitude_from_input(self, builder):
        state = {"user_input": "太贵了", "task_results": [], "sub_tasks": []}
        ds = builder.build_state(state)
        assert ds.user_attitude == UserAttitude.UNSATISFIED

    def test_goal_from_task_results(self, builder):
        """task_results 更新 active_goals"""
        state = {
            "user_input": "好的",
            "dialogue_state": DialogueState().model_dump(),
            "task_results": [
                {
                    "intent": "navigate",
                    "status": "done",
                    "tool_result": {
                        "destination": "重庆",
                        "distance": "300km",
                        "toll": "165元",
                    },
                }
            ],
            "sub_tasks": [{"intent": "navigate"}],
        }
        ds = builder.build_state(state)
        goal = ds.get_goal_by_type("map")
        assert goal is not None
        assert goal.attempt_count == 1
        assert goal.last_result is not None
        assert goal.last_result["destination"] == "重庆"
        assert ds.key_entities.get("destination") == "重庆"

    def test_goal_attempt_count_accumulates(self, builder):
        """多次执行同一 goal → attempt_count 累加"""
        prev_ds = DialogueState(
            active_goals=[
                ActiveGoal(goal_type="map", attempt_count=1),
            ]
        )
        state = {
            "user_input": "那就走国道",
            "dialogue_state": prev_ds.model_dump(),
            "task_results": [
                {
                    "intent": "navigate",
                    "status": "done",
                    "tool_result": {
                        "destination": "重庆",
                        "route_type": "avoid_highway",
                    },
                }
            ],
            "sub_tasks": [{"intent": "navigate"}],
        }
        ds = builder.build_state(state)
        goal = ds.get_goal_by_type("map")
        assert goal is not None
        assert goal.attempt_count == 2

    def test_preferences_loaded(self, builder, memory):
        """从 MemoryManager 加载偏好"""
        memory.save_preference("route_type", "avoid_toll")
        state = {"user_input": "导航", "task_results": [], "sub_tasks": []}
        ds = builder.build_state(state)
        assert len(ds.active_preferences) >= 1
        assert ds.active_preferences[0]["key"] == "route_type"

    def test_frequent_destinations_loaded(self, builder, memory):
        """从 MemoryManager 加载高频地点"""
        for _ in range(5):
            memory.log_event("navigate", "导航去天府广场", {"destination": "天府广场"})
        state = {"user_input": "今天去哪", "task_results": [], "sub_tasks": []}
        ds = builder.build_state(state)
        assert len(ds.frequent_destinations) >= 1
        assert ds.frequent_destinations[0]["name"] == "天府广场"


# ═══════════════════════════════════════════════
# ContextBuilder — generate_summary
# ═══════════════════════════════════════════════


class TestGenerateSummary:
    def test_empty_state(self, builder):
        ds = DialogueState()
        summary = builder.generate_summary(ds)
        assert summary == ""

    def test_with_goal(self, builder):
        ds = DialogueState(
            active_goals=[
                ActiveGoal(
                    goal_type="map",
                    slots={"destination": "重庆"},
                    attempt_count=2,
                    last_result={"distance": "300km", "toll": "165元"},
                )
            ],
            user_attitude=UserAttitude.WANTS_ALTERNATIVE,
        )
        summary = builder.generate_summary(ds)
        assert "map" in summary  # goal_type 来自 registry
        assert "重庆" in summary
        assert "wants_alternative" in summary
        assert "🔄" in summary

    def test_with_preferences(self, builder):
        ds = DialogueState(
            active_preferences=[
                {"key": "route_type", "value": "avoid_toll", "score": 8.0}
            ]
        )
        summary = builder.generate_summary(ds)
        assert "route_type" in summary
        assert "avoid_toll" in summary

    def test_with_frequent_destinations(self, builder):
        ds = DialogueState(
            frequent_destinations=[
                {"name": "天府广场", "count": 30},
            ]
        )
        summary = builder.generate_summary(ds)
        assert "天府广场" in summary
        assert "30次" in summary

    def test_no_hint_for_normal_navigation(self, builder):
        """正常导航不带策略提示"""
        ds = DialogueState(
            active_goals=[
                ActiveGoal(goal_type="map", slots={"destination": "重庆"}),
            ],
        )
        summary = builder.generate_summary(ds)
        assert "🔄" not in summary  # 没有"换方案"提示

    def test_hint_for_unsatisfied_navigation(self, builder):
        """用户不满 + 导航 → 有策略提示"""
        ds = DialogueState(
            active_goals=[
                ActiveGoal(goal_type="map", slots={"destination": "重庆"}),
            ],
            user_attitude=UserAttitude.UNSATISFIED,
        )
        summary = builder.generate_summary(ds)
        assert "🔄" in summary
        assert "avoid_toll" in summary
