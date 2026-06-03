"""
project1_cabin_agent/tests/test_action.py — Action 信号层测试

测试 tool_result → CabinAction 转换的正确性。
纯函数测试，零外部依赖。

这个模块也是 eval sandbox 的验证维度：
  action 输出对不对，可以跟 voice_reply 分开独立校验。
"""

from project1_cabin_agent.actions.engine import format_action
from project1_cabin_agent.actions.models import CabinAction


# ═══════════════════════════════════════════════════
# Climate 域
# ═══════════════════════════════════════════════════


class TestClimateAction:
    def test_ac_on(self):
        result = {
            "status": "success",
            "intent": "ac_control",
            "action": "on",
            "temperature": 24,
        }
        action = format_action("climate", "ac_control", result)
        assert action is not None
        assert action.command == "ac_on"
        assert action.params["temperature"] == 24

    def test_ac_off(self):
        result = {"status": "success", "intent": "ac_control", "action": "off"}
        action = format_action("climate", "ac_control", result)
        assert action.command == "ac_off"

    def test_ac_set(self):
        result = {
            "status": "success",
            "intent": "ac_control",
            "action": "adjust",
            "temperature": 22,
            "mode": "cool",
            "fan_level": 3,
        }
        action = format_action("climate", "ac_control", result)
        assert action.command == "ac_set"
        assert action.params == {"temperature": 22, "mode": "cool", "fan_level": 3}

    def test_window_open(self):
        result = {
            "status": "success",
            "intent": "window_control",
            "action": "open",
            "target": "driver",
        }
        action = format_action("climate", "window_control", result)
        assert action.command == "window_open"
        assert action.params["target"] == "driver"

    def test_window_close(self):
        result = {
            "status": "success",
            "intent": "window_control",
            "action": "close",
            "target": "all",
        }
        action = format_action("climate", "window_control", result)
        assert action.command == "window_close"

    def test_window_adjust(self):
        result = {
            "status": "success",
            "intent": "window_control",
            "action": "adjust",
            "target": "passenger",
            "percent": 50,
        }
        action = format_action("climate", "window_control", result)
        assert action.command == "window_set"
        assert action.params["percent"] == 50

    def test_light_on(self):
        result = {"status": "success", "intent": "light_control", "action": "on"}
        action = format_action("climate", "light_control", result)
        assert action.command == "light_on"

    def test_seat_heat(self):
        result = {
            "status": "success",
            "intent": "seat_control",
            "action": "heat_on",
            "heat_level": 3,
        }
        action = format_action("climate", "seat_control", result)
        assert action.command == "seat_heat_on"
        assert action.params["heat_level"] == 3

    def test_no_action_field(self):
        result = {"status": "success", "intent": "ac_control"}
        action = format_action("climate", "ac_control", result)
        assert action is None


# ═══════════════════════════════════════════════════
# Map 域
# ═══════════════════════════════════════════════════


class TestMapAction:
    def test_navigate(self):
        result = {
            "success": True,
            "data": {
                "distance": 300,
                "duration": 210,
                "tolls": 165,
                "route_text": "全程300公里，预计3.5小时",
            },
        }
        action = format_action("map", "navigate", result)
        assert action is not None
        assert action.command == "start_nav"
        assert action.params["distance_km"] == 300
        assert action.params["duration_min"] == 210
        assert action.params["tolls"] == 165

    def test_search_poi(self):
        result = {
            "success": True,
            "data": {
                "results": [
                    {"name": "海底捞火锅", "distance": 1500},
                    {"name": "小龙坎", "distance": 2300},
                ],
                "count": 2,
            },
        }
        action = format_action("map", "search_poi", result)
        assert action.command == "search_poi"
        assert action.params["count"] == 2
        assert action.params["top_result"]["name"] == "海底捞火锅"

    def test_search_poi_empty(self):
        result = {"success": True, "data": {"results": [], "count": 0}}
        action = format_action("map", "search_poi", result)
        assert action.params["count"] == 0
        assert action.params["top_result"] is None

    def test_weather(self):
        result = {
            "success": True,
            "data": {
                "city": "成都",
                "weather": "晴",
                "temperature": "28",
                "date": "今天",
            },
        }
        action = format_action("map", "weather", result)
        assert action.command == "weather_query"
        assert action.params["city"] == "成都"
        assert action.params["temperature"] == "28"

    def test_navigate_failed(self):
        result = {"success": False, "error": "无法解析目的地"}
        action = format_action("map", "navigate", result)
        assert action is None


# ═══════════════════════════════════════════════════
# Media 域
# ═══════════════════════════════════════════════════


class TestMediaAction:
    def test_play(self):
        result = {
            "status": "success",
            "intent": "media_control",
            "action": "play",
            "query": "周杰伦",
            "artist": "周杰伦",
        }
        action = format_action("media", "media_control", result)
        assert action.command == "media_play"
        assert action.params["query"] == "周杰伦"

    def test_pause(self):
        result = {"status": "success", "intent": "media_control", "action": "pause"}
        action = format_action("media", "media_control", result)
        assert action.command == "media_pause"

    def test_volume(self):
        result = {
            "status": "success",
            "intent": "media_control",
            "action": "set_volume",
            "volume": 80,
        }
        action = format_action("media", "media_control", result)
        assert action.command == "media_volume"
        assert action.params["volume"] == 80

    def test_next(self):
        result = {"status": "success", "intent": "media_control", "action": "next"}
        action = format_action("media", "media_control", result)
        assert action.command == "media_next"


# ═══════════════════════════════════════════════════
# Vehicle 域（查询类，无硬件动作）
# ═══════════════════════════════════════════════════


class TestVehicleAction:
    def test_vehicle_status_no_action(self):
        result = {"status": "success", "intent": "vehicle_status", "items": "fuel"}
        action = format_action("vehicle", "vehicle_status", result)
        assert action is None  # 查询类无硬件动作


# ═══════════════════════════════════════════════════
# 未知域
# ═══════════════════════════════════════════════════


class TestUnknownDomain:
    def test_unknown_domain(self):
        action = format_action("unknown", "test", {})
        assert action is None


# ═══════════════════════════════════════════════════
# CabinAction 序列化
# ═══════════════════════════════════════════════════


class TestCabinActionSerialization:
    def test_to_dict(self):
        a = CabinAction(
            domain="climate",
            intent="ac_control",
            command="ac_on",
            params={"temperature": 24},
        )
        d = a.to_dict()
        assert d == {
            "domain": "climate",
            "intent": "ac_control",
            "command": "ac_on",
            "params": {"temperature": 24},
        }

    def test_from_dict(self):
        d = {
            "domain": "map",
            "intent": "navigate",
            "command": "start_nav",
            "params": {"distance_km": 300},
        }
        a = CabinAction.from_dict(d)
        assert a.domain == "map"
        assert a.command == "start_nav"

    def test_roundtrip(self):
        original = CabinAction(
            domain="media",
            intent="media_control",
            command="media_play",
            params={"query": "周杰伦"},
        )
        restored = CabinAction.from_dict(original.to_dict())
        assert restored.domain == original.domain
        assert restored.command == original.command
        assert restored.params == original.params
