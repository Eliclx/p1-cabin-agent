"""
project1_cabin_agent/tests/test_climate_harness.py
Climate Harness 单测 — 4 intents + 高风控
"""
import pytest
from project1_cabin_agent.skills.climate.harness import ClimateHarness
from project1_cabin_agent.harness.context import AgentContext, VehicleSnapshot


@pytest.fixture
def harness():
    return ClimateHarness()


@pytest.fixture
def ctx():
    return AgentContext(vehicle=VehicleSnapshot(location="104.06,30.67", speed=60))


@pytest.fixture
def ctx_stopped():
    return AgentContext(vehicle=VehicleSnapshot(speed=0))


@pytest.fixture
def ctx_highway():
    return AgentContext(vehicle=VehicleSnapshot(speed=120))


# ── ac_control ───────────────────────────────────────────────────

class TestAcControl:
    def test_on(self, harness, ctx):
        r = harness.pre_validate({"_intent": "ac_control", "action": "on"}, ctx)
        assert r.valid

    def test_off(self, harness, ctx):
        r = harness.pre_validate({"_intent": "ac_control", "action": "off"}, ctx)
        assert r.valid

    def test_adjust_with_temp(self, harness, ctx):
        r = harness.pre_validate({"_intent": "ac_control", "action": "adjust", "temperature": 22}, ctx)
        assert r.valid

    def test_missing_action(self, harness, ctx):
        r = harness.pre_validate({"_intent": "ac_control"}, ctx)
        assert not r.valid
        assert r.need_clarify

    def test_illegal_action(self, harness, ctx):
        r = harness.pre_validate({"_intent": "ac_control", "action": "heat"}, ctx)
        assert not r.valid
        assert r.fallback

    def test_temp_oob_high(self, harness, ctx):
        r = harness.pre_validate({"_intent": "ac_control", "action": "adjust", "temperature": 40}, ctx)
        assert r.valid
        assert r.slots["temperature"] == 32

    def test_temp_oob_low(self, harness, ctx):
        r = harness.pre_validate({"_intent": "ac_control", "action": "adjust", "temperature": 5}, ctx)
        assert r.valid
        assert r.slots["temperature"] == 16

    def test_fan_oob(self, harness, ctx):
        r = harness.pre_validate({"_intent": "ac_control", "action": "adjust", "fan_level": 10}, ctx)
        assert r.valid
        assert r.slots["fan_level"] == 5


# ── window_control ───────────────────────────────────────────────

class TestWindowControl:
    def test_close(self, harness, ctx):
        r = harness.pre_validate({"_intent": "window_control", "target": "window", "action": "close"}, ctx)
        assert r.valid
        assert not r.need_confirm  # 关窗不需要确认

    def test_open_window_needs_confirm(self, harness, ctx):
        r = harness.pre_validate({"_intent": "window_control", "target": "window", "action": "open"}, ctx)
        assert r.valid
        assert r.need_confirm

    def test_door_open_driving_blocked(self, harness, ctx_highway):
        r = harness.pre_validate({"_intent": "window_control", "target": "door", "action": "open"}, ctx_highway)
        assert not r.valid
        assert r.fallback

    def test_door_open_stopped(self, harness, ctx_stopped):
        """停车时开门不需要阻挡（但工具层会 need_confirm）"""
        r = harness.pre_validate({"_intent": "window_control", "target": "door", "action": "open"}, ctx_stopped)
        assert r.valid

    def test_missing_target(self, harness, ctx):
        r = harness.pre_validate({"_intent": "window_control", "action": "open"}, ctx)
        assert not r.valid
        assert r.need_clarify


# ── light_control ────────────────────────────────────────────────

class TestLightControl:
    def test_on(self, harness, ctx):
        r = harness.pre_validate({"_intent": "light_control", "action": "on"}, ctx)
        assert r.valid

    def test_off(self, harness, ctx):
        r = harness.pre_validate({"_intent": "light_control", "action": "off"}, ctx)
        assert r.valid

    def test_illegal_action(self, harness, ctx):
        r = harness.pre_validate({"_intent": "light_control", "action": "blink"}, ctx)
        assert not r.valid
        assert r.fallback


# ── seat_control ─────────────────────────────────────────────────

class TestSeatControl:
    def test_heat_on(self, harness, ctx):
        r = harness.pre_validate({"_intent": "seat_control", "action": "heat_on"}, ctx)
        assert r.valid

    def test_ventilate_off(self, harness, ctx):
        r = harness.pre_validate({"_intent": "seat_control", "action": "ventilate_off"}, ctx)
        assert r.valid

    def test_heat_level_oob(self, harness, ctx):
        r = harness.pre_validate({"_intent": "seat_control", "action": "heat_on", "heat_level": 5}, ctx)
        assert r.valid
        assert r.slots["heat_level"] == 3


# ── post_validate ────────────────────────────────────────────────

class TestPostValidate:
    def test_success(self, harness, ctx):
        r = harness.post_validate({"status": "success"}, ctx)
        assert r.valid

    def test_failure(self, harness, ctx):
        r = harness.post_validate({"status": "error"}, ctx)
        assert not r.valid
        assert r.fallback


# ── format_response ──────────────────────────────────────────────

class TestFormatResponse:
    def test_ac_on(self, harness):
        r = harness.format_response({"intent": "ac_control", "action": "on", "temperature": 22})
        assert "空调" in r and "22" in r

    def test_ac_off(self, harness):
        r = harness.format_response({"intent": "ac_control", "action": "off"})
        assert "关闭" in r

    def test_window_close(self, harness):
        r = harness.format_response({"intent": "window_control", "target": "window", "action": "close"})
        assert "关闭" in r

    def test_light_on(self, harness):
        r = harness.format_response({"intent": "light_control", "action": "on"})
        assert "车灯" in r

    def test_seat_heat(self, harness):
        r = harness.format_response({"intent": "seat_control", "action": "heat_on", "heat_level": 2})
        assert "加热" in r and "2" in r
