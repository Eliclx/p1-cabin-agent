"""
project1_cabin_agent/tests/test_evolution.py — 记忆进化测试

测试分层：
  TestBuildPrompt: prompt 构建（纯函数）
  TestParseResponse: LLM 响应解析（纯函数，容错）
  TestEvolutionEngine: 引擎编排（mock LLM）
  TestEvolutionRunner: 端到端编排（mock MemoryManager + LLM）
"""

import json
from unittest.mock import MagicMock, patch

from project1_cabin_agent.memory.evolution import (
    ExtractedPreference,
    EvolutionEngine,
    build_evolution_prompt,
    parse_evolution_response,
)


# ═══════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════


def _make_event(**overrides) -> dict:
    """构造测试用事件 dict"""
    base = {
        "event_type": "navigate",
        "summary": "导航去天府广场",
        "heat": 1.0,
        "dedup_count": 1,
        "details": {"destination": "天府广场"},
        "timestamp": "2026-06-01T10:00:00",
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════
# Prompt 构建
# ═══════════════════════════════════════════════════


class TestBuildPrompt:
    def test_empty_events(self):
        assert build_evolution_prompt([]) == ""

    def test_single_event(self):
        events = [_make_event()]
        prompt = build_evolution_prompt(events)
        assert "[navigate]" in prompt
        assert "天府广场" in prompt
        assert "操作记录" in prompt

    def test_dedup_count_shown(self):
        events = [_make_event(dedup_count=5)]
        prompt = build_evolution_prompt(events)
        assert "重复5次" in prompt

    def test_dedup_count_1_hidden(self):
        events = [_make_event(dedup_count=1)]
        prompt = build_evolution_prompt(events)
        assert "重复" not in prompt

    def test_details_included(self):
        events = [_make_event(details={"destination": "重庆", "toll": "165元"})]
        prompt = build_evolution_prompt(events)
        assert "destination=重庆" in prompt
        assert "toll=165元" in prompt

    def test_empty_details_filtered(self):
        events = [_make_event(details={"destination": "天府广场", "note": ""})]
        prompt = build_evolution_prompt(events)
        assert "destination=天府广场" in prompt
        assert "note=" not in prompt

    def test_multiple_events_numbered(self):
        events = [
            _make_event(summary="导航去A"),
            _make_event(summary="导航去B"),
            _make_event(summary="导航去C"),
        ]
        prompt = build_evolution_prompt(events)
        assert "1." in prompt
        assert "2." in prompt
        assert "3." in prompt

    def test_different_event_types(self):
        events = [
            _make_event(event_type="navigate", summary="去重庆"),
            _make_event(event_type="media_control", summary="播放周杰伦"),
            _make_event(event_type="weather", summary="查成都天气"),
        ]
        prompt = build_evolution_prompt(events)
        assert "[navigate]" in prompt
        assert "[media_control]" in prompt
        assert "[weather]" in prompt


# ═══════════════════════════════════════════════════
# 响应解析
# ═══════════════════════════════════════════════════


class TestParseResponse:
    def test_valid_response(self):
        raw = json.dumps({
            "preferences": [
                {
                    "key": "frequent_destination_tianfu",
                    "value": "天府广场",
                    "reason": "用户3次导航去天府广场",
                    "confidence": 0.85,
                },
                {
                    "key": "preferred_route_type",
                    "value": "avoid_toll",
                    "reason": "用户多次抱怨过路费",
                    "confidence": 0.7,
                },
            ]
        })
        prefs = parse_evolution_response(raw)
        assert len(prefs) == 2
        assert prefs[0].key == "frequent_destination_tianfu"
        assert prefs[0].confidence == 0.85
        assert prefs[1].value == "avoid_toll"

    def test_empty_preferences(self):
        raw = json.dumps({"preferences": []})
        prefs = parse_evolution_response(raw)
        assert prefs == []

    def test_no_preferences_key(self):
        raw = json.dumps({"other_key": "value"})
        prefs = parse_evolution_response(raw)
        assert prefs == []

    def test_invalid_json(self):
        prefs = parse_evolution_response("not json at all")
        assert prefs == []

    def test_partial_json(self):
        """LLM 在 JSON 前后加了文字"""
        raw = '好的，分析结果如下：\n{"preferences": [{"key": "test", "value": "v", "reason": "r", "confidence": 0.5}]}'
        prefs = parse_evolution_response(raw)
        assert len(prefs) == 1
        assert prefs[0].key == "test"

    def test_missing_key_skipped(self):
        """缺少 key 或 value 的条目被跳过"""
        raw = json.dumps({
            "preferences": [
                {"value": "v", "reason": "r", "confidence": 0.5},
                {"key": "k", "reason": "r", "confidence": 0.5},
                {"key": "valid", "value": "yes", "reason": "r", "confidence": 0.8},
            ]
        })
        prefs = parse_evolution_response(raw)
        assert len(prefs) == 1
        assert prefs[0].key == "valid"

    def test_confidence_bounded(self):
        """confidence 超出 0-1 范围被裁剪"""
        raw = json.dumps({
            "preferences": [
                {"key": "a", "value": "v", "reason": "r", "confidence": 1.5},
                {"key": "b", "value": "v", "reason": "r", "confidence": -0.3},
                {"key": "c", "value": "v", "reason": "r", "confidence": 0.7},
            ]
        })
        prefs = parse_evolution_response(raw)
        assert prefs[0].confidence == 1.0
        assert prefs[1].confidence == 0.0
        assert prefs[2].confidence == 0.7

    def test_confidence_missing_defaults(self):
        """confidence 缺失默认 0.5"""
        raw = json.dumps({
            "preferences": [
                {"key": "a", "value": "v", "reason": "r"},
            ]
        })
        prefs = parse_evolution_response(raw)
        assert prefs[0].confidence == 0.5

    def test_confidence_non_numeric(self):
        """confidence 非数字默认 0.5"""
        raw = json.dumps({
            "preferences": [
                {"key": "a", "value": "v", "reason": "r", "confidence": "high"},
            ]
        })
        prefs = parse_evolution_response(raw)
        assert prefs[0].confidence == 0.5

    def test_non_dict_item_skipped(self):
        raw = json.dumps({"preferences": ["not a dict", 42, None]})
        prefs = parse_evolution_response(raw)
        assert prefs == []

    def test_preferences_not_list(self):
        raw = json.dumps({"preferences": "not a list"})
        prefs = parse_evolution_response(raw)
        assert prefs == []

    def test_empty_string(self):
        prefs = parse_evolution_response("")
        assert prefs == []

    def test_no_json_at_all(self):
        prefs = parse_evolution_response("plain text without braces")
        assert prefs == []


# ═══════════════════════════════════════════════════
# EvolutionEngine（mock LLM）
# ═══════════════════════════════════════════════════


class TestEvolutionEngine:
    def test_empty_events_returns_empty(self):
        engine = EvolutionEngine(llm_fn=lambda p: "")
        assert engine.evolve([]) == []

    def test_llm_returns_preferences(self):
        def mock_llm(prompt: str) -> str:
            return json.dumps({
                "preferences": [
                    {
                        "key": "frequent_destination_chongqing",
                        "value": "重庆",
                        "reason": "3次导航",
                        "confidence": 0.8,
                    }
                ]
            })

        engine = EvolutionEngine(llm_fn=mock_llm)
        events = [
            _make_event(summary="导航去重庆", details={"destination": "重庆"}),
            _make_event(summary="导航去重庆", details={"destination": "重庆"}),
            _make_event(summary="导航去重庆", details={"destination": "重庆"}),
        ]
        prefs = engine.evolve(events)
        assert len(prefs) == 1
        assert prefs[0].value == "重庆"

    def test_llm_returns_nothing(self):
        engine = EvolutionEngine(llm_fn=lambda p: '{"preferences": []}')
        events = [_make_event()]
        prefs = engine.evolve(events)
        assert prefs == []

    def test_llm_exception_handled(self):
        """LLM 调用失败不崩溃"""
        def broken_llm(prompt: str) -> str:
            raise RuntimeError("LLM down")

        engine = EvolutionEngine(llm_fn=broken_llm)
        events = [_make_event()]
        prefs = engine.evolve(events)
        assert prefs == []

    def test_prompt_passed_to_llm(self):
        """验证 prompt 正确传入 LLM"""
        captured = {}

        def capturing_llm(prompt: str) -> str:
            captured["prompt"] = prompt
            return '{"preferences": []}'

        engine = EvolutionEngine(llm_fn=capturing_llm)
        events = [_make_event(summary="导航去重庆")]
        engine.evolve(events)
        assert "导航去重庆" in captured["prompt"]

    def test_multiple_preferences(self):
        def mock_llm(prompt: str) -> str:
            return json.dumps({
                "preferences": [
                    {"key": "frequent_dest", "value": "重庆", "reason": "3次", "confidence": 0.8},
                    {"key": "preferred_route", "value": "avoid_toll", "reason": "抱怨过路费", "confidence": 0.7},
                    {"key": "preferred_temp", "value": "24", "reason": "多次设24度", "confidence": 0.6},
                ]
            })

        engine = EvolutionEngine(llm_fn=mock_llm)
        events = [_make_event()]
        prefs = engine.evolve(events)
        assert len(prefs) == 3


# ═══════════════════════════════════════════════════
# ExtractedPreference
# ═══════════════════════════════════════════════════


class TestExtractedPreference:
    def test_to_dict(self):
        p = ExtractedPreference(
            key="test_key",
            value="test_value",
            reason="test reason",
            confidence=0.9,
        )
        d = p.to_dict()
        assert d["key"] == "test_key"
        assert d["value"] == "test_value"
        assert d["confidence"] == 0.9


# ═══════════════════════════════════════════════════
# EvolutionRunner（mock MemoryManager + LLM）
# ═══════════════════════════════════════════════════


class TestEvolutionRunner:
    def test_should_not_evolve(self):
        """不需要进化时直接返回 0"""
        from project1_cabin_agent.memory.evolution_runner import run_evolution

        memory = MagicMock()
        memory.should_evolve.return_value = False

        result = run_evolution(memory)
        assert result == 0
        memory.get_unanalyzed_events.assert_not_called()

    def test_no_unanalyzed_events(self):
        """需要进化但没事件"""
        from project1_cabin_agent.memory.evolution_runner import run_evolution

        memory = MagicMock()
        memory.should_evolve.return_value = True
        memory.get_unanalyzed_events.return_value = []

        result = run_evolution(memory)
        assert result == 0

    def test_full_flow_with_mock_llm(self):
        """完整流程：events → LLM → 偏好写回"""
        from project1_cabin_agent.memory.evolution_runner import run_evolution
        

        # 准备 mock events
        mock_event = MagicMock()
        mock_event.id = 1
        mock_event.event_type = "navigate"
        mock_event.summary = "导航去重庆"
        mock_event.heat = 5.0
        mock_event.dedup_count = 3
        mock_event.details = {"destination": "重庆"}
        mock_event.timestamp = "2026-06-01T10:00:00"

        memory = MagicMock()
        memory.should_evolve.return_value = True
        memory.get_unanalyzed_events.return_value = [mock_event]

        # Mock LLM
        mock_llm_resp = MagicMock()
        mock_llm_resp.content = json.dumps({
            "preferences": [
                {
                    "key": "frequent_destination_chongqing",
                    "value": "重庆",
                    "reason": "3次导航去重庆",
                    "confidence": 0.85,
                }
            ]
        })
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_llm_resp

        with patch(
            "shared.utils.llm_factory.get_llm",
            return_value=mock_llm,
        ):
            result = run_evolution(memory)

        assert result == 1
        memory.save_preference.assert_called_once_with(
            key="frequent_destination_chongqing",
            value="重庆",
            source="llm_evolution",
            confidence=0.85,
        )
        memory.mark_events_analyzed.assert_called_once_with([1])

    def test_no_preferences_still_marks_analyzed(self):
        """LLM 没提取到偏好，仍标记事件已分析"""
        from project1_cabin_agent.memory.evolution_runner import run_evolution
        

        mock_event = MagicMock()
        mock_event.id = 42
        mock_event.event_type = "navigate"
        mock_event.summary = "导航去A"
        mock_event.heat = 2.0
        mock_event.dedup_count = 1
        mock_event.details = {}
        mock_event.timestamp = "2026-06-01T10:00:00"

        memory = MagicMock()
        memory.should_evolve.return_value = True
        memory.get_unanalyzed_events.return_value = [mock_event]

        mock_llm_resp = MagicMock()
        mock_llm_resp.content = '{"preferences": []}'
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_llm_resp

        with patch(
            "shared.utils.llm_factory.get_llm",
            return_value=mock_llm,
        ):
            result = run_evolution(memory)

        assert result == 0
        # 仍然标记已分析
        memory.mark_events_analyzed.assert_called_once_with([42])

    def test_max_events_truncation(self):
        """事件超过 max_events 时截断"""
        from project1_cabin_agent.memory.evolution_runner import run_evolution
        

        events = []
        for i in range(10):
            e = MagicMock()
            e.id = i
            e.event_type = "navigate"
            e.summary = f"导航{i}"
            e.heat = 1.0
            e.dedup_count = 1
            e.details = {}
            e.timestamp = "2026-06-01T10:00:00"
            events.append(e)

        memory = MagicMock()
        memory.should_evolve.return_value = True
        memory.get_unanalyzed_events.return_value = events

        captured_prompt = {}

        def capture_llm(prompt: str) -> str:
            captured_prompt["text"] = prompt
            return '{"preferences": []}'

        mock_llm_resp = MagicMock()
        mock_llm_resp.content = '{"preferences": []}'
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_llm_resp

        with patch(
            "shared.utils.llm_factory.get_llm",
            return_value=mock_llm,
        ):
            run_evolution(memory, max_events=3)

        # 只标记前 3 个事件
        ids = memory.mark_events_analyzed.call_args[0][0]
        assert len(ids) == 3
