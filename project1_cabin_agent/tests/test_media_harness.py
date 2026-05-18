"""
project1_cabin_agent/tests/test_media_harness.py
Media Harness 单测 — 纯函数，零 I/O
"""
import pytest
from project1_cabin_agent.skills.media.harness import MediaHarness
from project1_cabin_agent.harness.context import AgentContext, VehicleSnapshot


@pytest.fixture
def harness():
    return MediaHarness()


@pytest.fixture
def ctx():
    return AgentContext(vehicle=VehicleSnapshot())


# ── pre_validate ─────────────────────────────────────────────────

class TestPreValidate:
    def test_missing_action(self, harness, ctx):
        r = harness.pre_validate({}, ctx)
        assert not r.valid
        assert r.need_clarify
        assert "操作" in r.clarify_message

    def test_valid_play(self, harness, ctx):
        r = harness.pre_validate({"action": "play"}, ctx)
        assert r.valid

    def test_valid_pause(self, harness, ctx):
        r = harness.pre_validate({"action": "pause"}, ctx)
        assert r.valid

    def test_valid_next(self, harness, ctx):
        r = harness.pre_validate({"action": "next"}, ctx)
        assert r.valid

    def test_valid_volume_up(self, harness, ctx):
        r = harness.pre_validate({"action": "volume_up"}, ctx)
        assert r.valid

    def test_illegal_action(self, harness, ctx):
        r = harness.pre_validate({"action": "rewind"}, ctx)
        assert not r.valid
        assert r.fallback

    def test_search_missing_query(self, harness, ctx):
        r = harness.pre_validate({"action": "search"}, ctx)
        assert not r.valid
        assert r.need_clarify
        assert "听什么" in r.clarify_message

    def test_search_with_query(self, harness, ctx):
        r = harness.pre_validate({"action": "search", "query": "周杰伦"}, ctx)
        assert r.valid

    def test_set_volume_missing_volume(self, harness, ctx):
        r = harness.pre_validate({"action": "set_volume"}, ctx)
        assert not r.valid
        assert r.need_clarify

    def test_set_volume_oob_clamped(self, harness, ctx):
        r = harness.pre_validate({"action": "set_volume", "volume": 150}, ctx)
        assert r.valid
        assert r.slots["volume"] == 100  # clamped

    def test_set_volume_negative_clamped(self, harness, ctx):
        r = harness.pre_validate({"action": "set_volume", "volume": -10}, ctx)
        assert r.valid
        assert r.slots["volume"] == 0  # clamped


# ── post_validate ────────────────────────────────────────────────

class TestPostValidate:
    def test_success(self, harness, ctx):
        r = harness.post_validate({"status": "success", "action": "play"}, ctx)
        assert r.valid

    def test_failure(self, harness, ctx):
        r = harness.post_validate({"status": "error"}, ctx)
        assert not r.valid
        assert r.fallback

    def test_volume_oob_clamped(self, harness, ctx):
        tool_result = {"status": "success", "action": "set_volume", "volume": 200}
        r = harness.post_validate(tool_result, ctx)
        assert r.valid
        assert tool_result["volume"] == 100


# ── format_response ──────────────────────────────────────────────

class TestFormatResponse:
    def test_play(self, harness):
        assert "播放" in harness.format_response({"action": "play"})

    def test_pause(self, harness):
        assert "暂停" in harness.format_response({"action": "pause"})

    def test_next(self, harness):
        assert "下一首" in harness.format_response({"action": "next"})

    def test_search_with_query(self, harness):
        r = harness.format_response({"action": "search", "query": "周杰伦"})
        assert "周杰伦" in r

    def test_set_volume(self, harness):
        r = harness.format_response({"action": "set_volume", "volume": 50})
        assert "50" in r

    def test_unknown_action(self, harness):
        r = harness.format_response({"action": "unknown"})
        assert "好的" == r
