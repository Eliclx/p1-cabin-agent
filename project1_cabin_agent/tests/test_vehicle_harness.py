"""
project1_cabin_agent/tests/test_vehicle_harness.py
Vehicle Harness 单测
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
    def test_valid_items(self, harness, ctx):
        r = harness.pre_validate(
            {"_intent": "query_vehicle_status", "items": "fuel"}, ctx)
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


# ── pre_validate: activate_scene ──────────────────────────────────

class TestPreValidateScene:
    def test_comfortable(self, harness, ctx):
        r = harness.pre_validate(
            {"_intent": "activate_scene", "scene_name": "comfortable_driving"}, ctx)
        assert r.valid

    def test_sleep(self, harness, ctx):
        r = harness.pre_validate(
            {"_intent": "activate_scene", "scene_name": "sleep_mode"}, ctx)
        assert r.valid

    def test_departure(self, harness, ctx):
        r = harness.pre_validate(
            {"_intent": "activate_scene", "scene_name": "departure_check"}, ctx)
        assert r.valid

    def test_illegal_scene(self, harness, ctx):
        r = harness.pre_validate(
            {"_intent": "activate_scene", "scene_name": "sport_mode"}, ctx)
        assert not r.valid
        assert r.fallback

    def test_missing_scene_clarify(self, harness, ctx):
        r = harness.pre_validate(
            {"_intent": "activate_scene"}, ctx)
        assert not r.valid
        assert r.need_clarify


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
    def test_scene(self, harness):
        r = harness.format_response({"status": "success", "scene": "舒适驾驶"})
        assert "舒适驾驶" in r

    def test_voice_reply_fallback(self, harness):
        r = harness.format_response({"status": "success", "voice_reply": "好的"})
        assert "好的" == r
