"""
project1_cabin_agent/tests/test_retry.py — Error Recovery 测试

测试 retry 引擎的分类、策略和友好错误信息。
纯函数测试，零外部依赖。

解耦验证：
  - 通用引擎在 nodes/retry.py（分类 + fallback）
  - 域策略在 skills/{domain}/retry_rules.py
  - 引擎从 registry 加载域策略
"""

import pytest

from project1_cabin_agent.nodes.retry import (
    ErrorKind,
    RetryAction,
    classify_error,
    decide_retry,
)


# ═══════════════════════════════════════════════════
# 错误分类
# ═══════════════════════════════════════════════════


class TestClassifyError:
    def test_timeout(self):
        assert classify_error("timeout", {}) == ErrorKind.TIMEOUT
        assert classify_error("asyncio.TimeoutError", {}) == ErrorKind.TIMEOUT

    def test_network(self):
        assert classify_error("ConnectionError", {}) == ErrorKind.NETWORK
        assert classify_error("network unreachable", {}) == ErrorKind.NETWORK

    def test_api_error_from_tool_result(self):
        assert (
            classify_error("", {"success": False, "error": "API失败"})
            == ErrorKind.API_ERROR
        )

    def test_empty_result_from_tool_result(self):
        result = {"success": True, "data": {"results": [], "count": 0}}
        assert classify_error("", result) == ErrorKind.EMPTY_RESULT

    def test_empty_result_with_data(self):
        result = {"success": True, "data": {"results": [], "count": 0}}
        assert classify_error("", result) == ErrorKind.EMPTY_RESULT

    def test_invalid_input(self):
        assert (
            classify_error("", {"status": "error", "error": "无法解析目的地"})
            == ErrorKind.INVALID_INPUT
        )
        assert (
            classify_error("", {"status": "error", "error": "缺少位置坐标"})
            == ErrorKind.INVALID_INPUT
        )

    def test_unknown(self):
        assert classify_error("", {}) == ErrorKind.UNKNOWN
        assert classify_error("something odd", {}) == ErrorKind.UNKNOWN


# ═══════════════════════════════════════════════════
# Map 域重试策略
# ═══════════════════════════════════════════════════


class TestMapRetry:
    def test_search_poi_empty_expand_radius(self):
        result = decide_retry(
            "map",
            "search_poi",
            "",
            {"success": True, "data": {"results": [], "count": 0}},
            {"radius": 3000},
        )
        assert result.action == "retry"
        assert result.modified_slots["radius"] == 9000
        assert result.error_kind == ErrorKind.EMPTY_RESULT

    def test_search_poi_empty_large_radius_no_double(self):
        """已经扩大过就不再扩大"""
        result = decide_retry(
            "map",
            "search_poi",
            "",
            {"success": True, "data": {"results": [], "count": 0}},
            {"radius": 30000},
        )
        assert result.action == "retry"
        assert result.modified_slots["radius"] == 90000

    def test_timeout_retry(self):
        result = decide_retry(
            "map",
            "navigate",
            "timeout",
            {},
            {"destination": "重庆"},
        )
        assert result.action == "retry"
        assert result.error_kind == ErrorKind.TIMEOUT

    def test_network_retry(self):
        result = decide_retry(
            "map",
            "navigate",
            "ConnectionError",
            {},
            {"destination": "重庆"},
        )
        assert result.action == "retry"
        assert result.error_kind == ErrorKind.NETWORK

    def test_geocode_invalid_no_retry(self):
        result = decide_retry(
            "map",
            "navigate",
            "",
            {"status": "error", "error": "无法解析目的地: xyz"},
            {"destination": "xyz"},
        )
        assert result.action == "friendly_error"
        assert "无法识别" in result.friendly_message

    def test_api_error_friendly(self):
        result = decide_retry(
            "map",
            "weather",
            "",
            {"success": False, "error": "API请求失败"},
            {"city": "成都"},
        )
        assert result.action == "friendly_error"
        assert result.friendly_message  # 不为空

    def test_attempt_2_no_retry(self):
        """第二次不再重试"""
        result = decide_retry(
            "map",
            "navigate",
            "timeout",
            {},
            {"destination": "重庆"},
            attempt=2,
        )
        assert result.action == "friendly_error"
        assert "已重试" in result.reason


# ═══════════════════════════════════════════════════
# Climate 域重试策略
# ═══════════════════════════════════════════════════


class TestClimateRetry:
    def test_ac_error_friendly(self):
        result = decide_retry(
            "climate",
            "ac_control",
            "hardware error",
            {"status": "error", "error": "硬件无响应"},
            {"action": "on", "temperature": 24},
        )
        assert result.action == "friendly_error"
        assert "空调" in result.friendly_message

    def test_window_error_friendly(self):
        result = decide_retry(
            "climate",
            "window_control",
            "error",
            {"status": "error"},
            {"action": "open"},
        )
        assert result.action == "friendly_error"
        assert "车窗" in result.friendly_message

    def test_light_error_friendly(self):
        result = decide_retry(
            "climate",
            "light_control",
            "error",
            {"status": "error"},
            {},
        )
        assert result.action == "friendly_error"
        assert "灯光" in result.friendly_message

    def test_seat_error_friendly(self):
        result = decide_retry(
            "climate",
            "seat_control",
            "error",
            {"status": "error"},
            {},
        )
        assert result.action == "friendly_error"
        assert "座椅" in result.friendly_message


# ═══════════════════════════════════════════════════
# 未知域
# ═══════════════════════════════════════════════════


class TestUnknownDomain:
    def test_unknown_domain_friendly_error(self):
        result = decide_retry(
            "unknown",
            "test_intent",
            "some error",
            {},
            {},
        )
        assert result.action == "friendly_error"
        assert result.friendly_message  # 通用友好信息


# ═══════════════════════════════════════════════════
# 友好错误信息完整性
# ═══════════════════════════════════════════════════


class TestFriendlyErrors:
    @pytest.mark.parametrize("kind", list(ErrorKind))
    def test_all_error_kinds_have_message(self, kind):
        """每种错误类型都有对应的友好提示"""
        from project1_cabin_agent.nodes.retry import _FRIENDLY_ERRORS

        assert kind in _FRIENDLY_ERRORS
        assert len(_FRIENDLY_ERRORS[kind]) > 0


# ═══════════════════════════════════════════════════
# RetryAction 序列化
# ═══════════════════════════════════════════════════


class TestRetryActionSerialization:
    def test_to_dict(self):
        a = RetryAction(
            action="retry",
            modified_slots={"radius": 9000},
            error_kind=ErrorKind.EMPTY_RESULT,
            reason="扩大半径",
        )
        d = a.to_dict()
        assert d["action"] == "retry"
        assert d["modified_slots"]["radius"] == 9000
        assert d["error_kind"] == "empty_result"
