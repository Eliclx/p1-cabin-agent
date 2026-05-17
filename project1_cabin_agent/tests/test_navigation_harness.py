"""
project1_cabin_agent/tests/test_navigation_harness.py
Navigation Harness 单测 — 纯函数，零 I/O，三行就能跑

测试覆盖：
- pre_validate: 必填检查、别名解析、origin 补全、安全检查
- post_validate: API 失败、空结果、距离异常
- format_response: navigate_to 格式化、search_nearby 格式化、失败格式化
"""
import pytest

from project1_cabin_agent.skills.navigation.harness import NavigationHarness
from project1_cabin_agent.harness.context import AgentContext, VehicleSnapshot
from project1_cabin_agent.harness.base import ContextDep


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def harness():
    return NavigationHarness()


@pytest.fixture
def ctx_with_vehicle():
    """有位置和正常车速的上下文"""
    return AgentContext(
        vehicle=VehicleSnapshot(location="104.06,30.67", speed=60),
        dialogue={},
        session={"last_destination": "春熙路"},
        user={"home_address": "成都市高新区天府大道388号", "company_address": "成都市锦江区红星路三段1号"},
    )


@pytest.fixture
def ctx_no_location():
    """没有位置的上下文"""
    return AgentContext(
        vehicle=VehicleSnapshot(location="", speed=0),
    )


@pytest.fixture
def ctx_high_speed():
    """高速行驶的上下文"""
    return AgentContext(
        vehicle=VehicleSnapshot(location="104.06,30.67", speed=120),
        dialogue={},
        session={},
        user={"home_address": "天府大道388号"},
    )


@pytest.fixture
def ctx_no_l3():
    """没有 L3 用户偏好的上下文"""
    return AgentContext(
        vehicle=VehicleSnapshot(location="104.06,30.67", speed=60),
        dialogue={},
        session={},
        user={},
    )


@pytest.fixture
def ctx_no_l2():
    """没有 L2 行程记忆的上下文"""
    return AgentContext(
        vehicle=VehicleSnapshot(location="104.06,30.67", speed=60),
        dialogue={},
        session={},
        user={"home_address": "天府大道388号"},
    )


# ══════════════════════════════════════════════════════════════════
# CONTEXT_DEPS 声明
# ══════════════════════════════════════════════════════════════════

class TestContextDeps:
    def test_deps_includes_vehicle(self):
        assert ContextDep.VEHICLE in NavigationHarness.CONTEXT_DEPS

    def test_deps_includes_l2(self):
        assert ContextDep.L2 in NavigationHarness.CONTEXT_DEPS

    def test_deps_includes_l3(self):
        assert ContextDep.L3 in NavigationHarness.CONTEXT_DEPS


# ══════════════════════════════════════════════════════════════════
# pre_validate
# ══════════════════════════════════════════════════════════════════

class TestPreValidate:
    """LLM 输出后、调 tool 前的校验+补全"""

    # ── 正常 case ──

    def test_normal_navigation(self, harness, ctx_with_vehicle):
        """正常导航：有 destination，自动补 origin"""
        result = harness.pre_validate(
            slots={"destination": "天府广场"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.slots["destination"] == "天府广场"
        assert result.slots["origin"] == "104.06,30.67"
        assert result.slots.get("route_type", "fastest") == "fastest"

    def test_with_route_type(self, harness, ctx_with_vehicle):
        """指定路线偏好"""
        result = harness.pre_validate(
            slots={"destination": "天府广场", "route_type": "avoid_highway"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.slots["route_type"] == "avoid_highway"

    def test_origin_already_filled(self, harness, ctx_with_vehicle):
        """origin 已有值，不覆盖"""
        result = harness.pre_validate(
            slots={"destination": "天府广场", "origin": "104.08,30.68"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.slots["origin"] == "104.08,30.68"

    # ── 别名解析：家 → L3 ──

    def test_alias_home(self, harness, ctx_with_vehicle):
        """回家 → L3 地址"""
        result = harness.pre_validate(
            slots={"destination": "家"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.slots["destination"] == "成都市高新区天府大道388号"

    def test_alias_home_variants(self, harness, ctx_with_vehicle):
        """回家的多种说法"""
        for alias in ["回家", "回家"]:
            result = harness.pre_validate(
                slots={"destination": alias},
                ctx=ctx_with_vehicle,
            )
            assert result.valid is True
            assert "天府大道" in result.slots["destination"]

    # ── 别名解析：公司 → L3 ──

    def test_alias_company(self, harness, ctx_with_vehicle):
        """去公司 → L3 地址"""
        result = harness.pre_validate(
            slots={"destination": "公司"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.slots["destination"] == "成都市锦江区红星路三段1号"

    # ── 别名解析：上次去的 → L2 ──

    def test_alias_last_destination(self, harness, ctx_with_vehicle):
        """上次去的 → L2 行程记忆"""
        result = harness.pre_validate(
            slots={"destination": "上次去的"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.slots["destination"] == "春熙路"

    # ── 失败 case：缺必填 ──

    def test_missing_destination(self, harness, ctx_with_vehicle):
        """缺少 destination → 追问"""
        result = harness.pre_validate(
            slots={},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is False
        assert result.need_clarify is True
        assert "哪里" in result.clarify_message

    # ── 失败 case：别名解析失败 ──

    def test_alias_home_no_l3(self, harness, ctx_no_l3):
        """回家但 L3 没配置 → 追问"""
        result = harness.pre_validate(
            slots={"destination": "家"},
            ctx=ctx_no_l3,
        )
        assert result.valid is False
        assert result.need_clarify is True
        assert "设置" in result.clarify_message

    def test_alias_company_no_l3(self, harness, ctx_no_l3):
        """去公司但 L3 没配置 → 追问"""
        result = harness.pre_validate(
            slots={"destination": "公司"},
            ctx=ctx_no_l3,
        )
        assert result.valid is False
        assert result.need_clarify is True

    def test_alias_last_no_l2(self, harness, ctx_no_l2):
        """上次去的但 L2 没记录 → 追问"""
        result = harness.pre_validate(
            slots={"destination": "上次去的"},
            ctx=ctx_no_l2,
        )
        assert result.valid is False
        assert result.need_clarify is True
        assert "没有" in result.clarify_message

    # ── 失败 case：无位置 ──

    def test_no_vehicle_location(self, harness, ctx_no_location):
        """vehicle_state 无 location → 走云端兜底"""
        result = harness.pre_validate(
            slots={"destination": "天府广场"},
            ctx=ctx_no_location,
        )
        assert result.valid is False
        assert result.fallback is True

    # ── 安全检查 ──

    def test_high_speed_confirm(self, harness, ctx_high_speed):
        """高速行驶中改目的地 → 二次确认"""
        result = harness.pre_validate(
            slots={"destination": "天府广场"},
            ctx=ctx_high_speed,
        )
        assert result.valid is True
        assert result.need_confirm is True
        assert "120" in result.confirm_message

    def test_normal_speed_no_confirm(self, harness, ctx_with_vehicle):
        """正常速度不需要确认"""
        result = harness.pre_validate(
            slots={"destination": "天府广场"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.need_confirm is False


# ══════════════════════════════════════════════════════════════════
# post_validate
# ══════════════════════════════════════════════════════════════════

class TestPostValidate:
    """tool 返回后、给用户前的校验"""

    def test_api_success(self, harness, ctx_with_vehicle):
        """API 正常返回"""
        result = harness.post_validate(
            tool_result={"success": True, "data": {"distance": 15, "duration": 25, "route_text": "全程15公里"}},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True

    def test_api_failure(self, harness, ctx_with_vehicle):
        """API 失败 → 走云端兜底"""
        result = harness.post_validate(
            tool_result={"success": False, "error": "timeout"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is False
        assert result.fallback is True

    def test_search_no_results(self, harness, ctx_with_vehicle):
        """周边搜索无结果"""
        result = harness.post_validate(
            tool_result={"success": True, "data": {"results": [], "count": 0}},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.block_reason == "搜索无结果"

    def test_search_has_results(self, harness, ctx_with_vehicle):
        """周边搜索有结果"""
        result = harness.post_validate(
            tool_result={"success": True, "data": {"results": [{"name": "中石化"}], "count": 1}},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True

    def test_distance_too_long(self, harness, ctx_with_vehicle):
        """距离异常 > 5000km → 确认"""
        result = harness.post_validate(
            tool_result={"success": True, "data": {"distance": 6000, "duration": 5000, "route_text": "..."}},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.need_confirm is True
        assert "6000" in result.confirm_message

    def test_normal_distance(self, harness, ctx_with_vehicle):
        """正常距离不触发确认"""
        result = harness.post_validate(
            tool_result={"success": True, "data": {"distance": 100, "duration": 120, "route_text": "..."}},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.need_confirm is False


# ══════════════════════════════════════════════════════════════════
# format_response
# ══════════════════════════════════════════════════════════════════

class TestFormatResponse:
    """确定性格式化输出"""

    def test_navigate_success_with_tolls(self, harness):
        """导航成功（有过路费）"""
        text = harness.format_response({
            "success": True,
            "data": {"distance": 15.3, "duration": 25, "tolls": 10.0, "route_text": "全程15.3公里"},
        })
        assert "15.3公里" in text
        assert "25分钟" in text
        assert "10元" in text

    def test_navigate_success_no_tolls(self, harness):
        """导航成功（无过路费）"""
        text = harness.format_response({
            "success": True,
            "data": {"distance": 5.2, "duration": 10, "tolls": 0, "route_text": "全程5.2公里"},
        })
        assert "5.2公里" in text
        assert "过路费" not in text

    def test_navigate_failure(self, harness):
        """导航失败"""
        text = harness.format_response({
            "success": False,
            "error": "无法解析目的地",
        })
        assert "失败" in text
        assert "无法解析目的地" in text

    def test_search_single_result(self, harness):
        """搜索只有 1 个结果"""
        text = harness.format_response({
            "success": True,
            "data": {
                "results": [{"name": "中石化加油站", "dist_km": 0.3, "address": "天府大道100号"}],
                "count": 1,
            },
        })
        assert "中石化加油站" in text
        assert "0.3公里" in text

    def test_search_multiple_results(self, harness):
        """搜索多个结果，只播报前 3"""
        text = harness.format_response({
            "success": True,
            "data": {
                "results": [
                    {"name": "中石化", "dist_km": 0.3},
                    {"name": "中石油", "dist_km": 0.5},
                    {"name": "壳牌", "dist_km": 1.0},
                    {"name": "BP", "dist_km": 1.5},
                ],
                "count": 4,
            },
        })
        assert "4个结果" in text
        assert "中石化" in text
        assert "中石油" in text
        assert "壳牌" in text
        assert "BP" not in text  # 第 4 个不播报

    def test_search_no_results(self, harness):
        """搜索无结果"""
        text = harness.format_response({
            "success": True,
            "data": {"results": [], "count": 0},
        })
        assert "没有找到" in text

    def test_fallback_text(self, harness):
        """兜底文本"""
        text = harness.format_response({
            "success": True,
            "data": {},
        })
        assert "操作完成" in text
