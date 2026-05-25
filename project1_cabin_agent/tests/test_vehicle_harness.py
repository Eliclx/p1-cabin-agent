"""
project1_cabin_agent/tests/test_vehicle_harness.py
Vehicle Harness 单测 — query_vehicle_status only
"""
import pytest
from project1_cabin_agent.skills.vehicle.harness import VehicleHarness
from project1_cabin_agent.harness.context import AgentContext, VehicleSnapshot


@pytest.fixture
def harness():
    return VehicleHarness()


@pytest.fixture
def ctx():
    return AgentContext(vehicle=VehicleSnapshot())


# ── pre_validate: query_vehicle_status ───────────────────────────

class TestPreValidateQuery:
    def test_valid_items_fuel(self, harness, ctx):
        r = harness.pre_validate(
            {"_intent": "query_vehicle_status", "items": "fuel"}, ctx)
        assert r.valid

    def test_valid_items_battery(self, harness, ctx):
        r = harness.pre_validate(
            {"_intent": "query_vehicle_status", "items": "battery"}, ctx)
        assert r.valid

    def test_valid_items_tire(self, harness, ctx):
        r = harness.pre_validate(
            {"_intent": "query_vehicle_status", "items": "tire"}, ctx)
        assert r.valid

    def test_valid_items_mileage(self, harness, ctx):
        r = harness.pre_validate(
            {"_intent": "query_vehicle_status", "items": "mileage"}, ctx)
        assert r.valid

    def test_valid_items_speed(self, harness, ctx):
        r = harness.pre_validate(
            {"_intent": "query_vehicle_status", "items": "speed"}, ctx)
        assert r.valid

    def test_empty_items_passes(self, harness, ctx):
        """items 为空也通过（返回全部状态）"""
        r = harness.pre_validate(
            {"_intent": "query_vehicle_status"}, ctx)
        assert r.valid

    def test_illegal_items_fallback(self, harness, ctx):
        r = harness.pre_validate(
            {"_intent": "query_vehicle_status", "items": "engine"}, ctx)
        assert not r.valid
        assert r.fallback

    def test_ac_temp_not_in_vehicle(self, harness, ctx):
        """ac_temp 已归 climate/cabin_query，vehicle 不再接受"""
        r = harness.pre_validate(
            {"_intent": "query_vehicle_status", "items": "ac_temp"}, ctx)
        assert not r.valid
        assert r.fallback

    def test_temperature_not_in_vehicle(self, harness, ctx):
        """temperature 已归 climate/cabin_query，vehicle 不再接受"""
        r = harness.pre_validate(
            {"_intent": "query_vehicle_status", "items": "temperature"}, ctx)
        assert not r.valid
        assert r.fallback


# ── unknown intent ───────────────────────────────────────────────

class TestUnknownIntent:
    def test_activate_scene_unknown(self, harness, ctx):
        """activate_scene 已移除，应返回 fallback"""
        r = harness.pre_validate(
            {"_intent": "activate_scene", "scene_name": "comfortable_driving"}, ctx)
        assert not r.valid
        assert r.fallback


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
    def test_voice_reply(self, harness):
        r = harness.format_response({"status": "success", "voice_reply": "当前油量68%"})
        assert "油量" in r
