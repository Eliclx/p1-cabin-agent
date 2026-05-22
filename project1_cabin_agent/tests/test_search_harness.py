"""
project1_cabin_agent/tests/test_search_harness.py
Search Harness 单测 — 已合并到 MapHarness，通过 _intent="search_poi" 分发
"""
import pytest
from project1_cabin_agent.skills.map.harness import MapHarness
from project1_cabin_agent.harness.context import AgentContext, VehicleSnapshot


@pytest.fixture
def harness():
    return MapHarness()


@pytest.fixture
def ctx():
    return AgentContext(vehicle=VehicleSnapshot(location="104.06,30.67"))


# ── pre_validate ─────────────────────────────────────────────────

class TestPreValidate:
    def test_valid(self, harness, ctx):
        r = harness.pre_validate({"_intent": "search_poi", "keyword": "加油站"}, ctx)
        assert r.valid

    def test_missing_keyword_clarify(self, harness, ctx):
        r = harness.pre_validate({"_intent": "search_poi"}, ctx)
        assert not r.valid
        assert r.need_clarify

    def test_radius_clamped_high(self, harness, ctx):
        """radius > 50000 → clamp 到 50000"""
        r = harness.pre_validate({"_intent": "search_poi", "keyword": "餐厅", "radius": 60000}, ctx)
        assert r.valid
        assert r.slots["radius"] == 50000

    def test_radius_clamped_low(self, harness, ctx):
        """radius < 100 → clamp 到 100"""
        r = harness.pre_validate({"_intent": "search_poi", "keyword": "餐厅", "radius": 5}, ctx)
        assert r.valid
        assert r.slots["radius"] == 100


# ── post_validate ────────────────────────────────────────────────

class TestPostValidate:
    def test_success(self, harness, ctx):
        r = harness.post_validate({"success": True, "data": {"results": [], "count": 0}}, ctx)
        assert r.valid

    def test_failure(self, harness, ctx):
        r = harness.post_validate({"success": False, "error": "timeout"}, ctx)
        assert not r.valid
        assert r.fallback


# ── format_response ──────────────────────────────────────────────

class TestFormatResponse:
    def test_with_results(self, harness):
        r = harness.format_response({
            "success": True,
            "data": {"results": [{"name": "中石化", "distance": 1200, "rating": 4.1}], "count": 1},
        })
        assert "中石化" in r

    def test_empty_results(self, harness):
        r = harness.format_response({
            "success": True,
            "data": {"results": [], "count": 0},
        })
        assert "没有找到" in r

    def test_multiple_results(self, harness):
        r = harness.format_response({
            "success": True,
            "data": {
                "results": [
                    {"name": "A餐厅", "distance": 300},
                    {"name": "B餐厅", "distance": 500},
                    {"name": "C餐厅", "distance": 800},
                ],
                "count": 3,
            },
        })
        assert "3个结果" in r
