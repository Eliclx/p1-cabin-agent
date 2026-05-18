"""
project1_cabin_agent/tests/test_search_harness.py
Search Harness 单测
"""
import pytest
from project1_cabin_agent.skills.search.harness import SearchHarness
from project1_cabin_agent.harness.context import AgentContext, VehicleSnapshot


@pytest.fixture
def harness():
    return SearchHarness()


@pytest.fixture
def ctx():
    return AgentContext(vehicle=VehicleSnapshot(location="104.06,30.67"))


# ── pre_validate ─────────────────────────────────────────────────

class TestPreValidate:
    def test_valid(self, harness, ctx):
        r = harness.pre_validate({"keyword": "加油站"}, ctx)
        assert r.valid

    def test_missing_keyword_clarify(self, harness, ctx):
        r = harness.pre_validate({}, ctx)
        assert not r.valid
        assert r.need_clarify

    def test_radius_clamped_high(self, harness, ctx):
        r = harness.pre_validate({"keyword": "餐厅", "radius": 100}, ctx)
        assert r.valid
        assert r.slots["radius"] == 50

    def test_radius_clamped_low(self, harness, ctx):
        r = harness.pre_validate({"keyword": "餐厅", "radius": 0.5}, ctx)
        assert r.valid
        assert r.slots["radius"] == 1.0


# ── post_validate ────────────────────────────────────────────────

class TestPostValidate:
    def test_success(self, harness, ctx):
        r = harness.post_validate({"status": "success", "results": []}, ctx)
        assert r.valid

    def test_failure(self, harness, ctx):
        r = harness.post_validate({"status": "error"}, ctx)
        assert not r.valid
        assert r.fallback


# ── format_response ──────────────────────────────────────────────

class TestFormatResponse:
    def test_with_results(self, harness):
        r = harness.format_response({
            "status": "success", "keyword": "加油站",
            "results": [{"name": "中石化", "distance": "1.2km", "rating": 4.1}],
        })
        assert "中石化" in r
        assert "1.2km" in r

    def test_empty_results(self, harness):
        r = harness.format_response({
            "status": "success", "keyword": "加油站", "results": [],
        })
        assert "没有找到" in r

    def test_multiple_results(self, harness):
        r = harness.format_response({
            "status": "success", "keyword": "餐厅",
            "results": [
                {"name": "A餐厅", "distance": "1km"},
                {"name": "B餐厅", "distance": "2km"},
                {"name": "C餐厅", "distance": "3km"},
            ],
        })
        assert "3个结果" in r
