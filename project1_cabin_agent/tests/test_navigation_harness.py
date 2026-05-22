"""
project1_cabin_agent/tests/test_navigation_harness.py
Navigation Harness 单测 — 已合并到 MapHarness，通过 _intent="navigate" 分发

测试覆盖：
- pre_validate: 必填检查、别名解析、origin 补全、安全检查
- post_validate: API 失败、空结果、距离异常
- format_response: navigate 格式化、search 格式化、失败格式化
"""
import pytest

from project1_cabin_agent.skills.map.harness import MapHarness
from project1_cabin_agent.harness.context import AgentContext, VehicleSnapshot
from project1_cabin_agent.harness.base import ContextDep


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def harness():
    return MapHarness()


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


@pytest.fixture
def ctx_with_l1_poi():
    """有 L1 黑板 POI 搜索结果的上下文"""
    return AgentContext(
        vehicle=VehicleSnapshot(location="104.06,30.67", speed=60),
        dialogue={
            "entity.poi": {
                "results": [
                    {"name": "川菜馆", "dist_km": 0.3, "address": "天府大道100号"},
                    {"name": "火锅店", "dist_km": 0.5, "address": "天府大道200号"},
                    {"name": "面馆", "dist_km": 1.0, "address": "天府大道300号"},
                ],
                "count": 3,
            },
        },
        session={},
        user={"home_address": "天府大道388号"},
    )


# ══════════════════════════════════════════════════════════════════
# CONTEXT_DEPS 声明
# ══════════════════════════════════════════════════════════════════

class TestContextDeps:
    def test_deps_includes_vehicle(self):
        assert ContextDep.VEHICLE in MapHarness.CONTEXT_DEPS

    def test_deps_includes_l1(self):
        assert ContextDep.L1 in MapHarness.CONTEXT_DEPS

    def test_deps_includes_l2(self):
        assert ContextDep.L2 in MapHarness.CONTEXT_DEPS

    def test_deps_includes_l3(self):
        assert ContextDep.L3 in MapHarness.CONTEXT_DEPS


# ══════════════════════════════════════════════════════════════════
# pre_validate
# ══════════════════════════════════════════════════════════════════

class TestPreValidate:
    """LLM 输出后、调 tool 前的校验+补全"""

    # ── 正常 case ──

    def test_normal_navigation(self, harness, ctx_with_vehicle):
        """正常导航：有 destination，自动补 origin"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "天府广场"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.slots["destination"] == "天府广场"
        assert result.slots["origin"] == "104.06,30.67"
        assert result.slots.get("route_type", "fastest") == "fastest"

    def test_with_route_type(self, harness, ctx_with_vehicle):
        """指定路线偏好"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "天府广场", "route_type": "avoid_highway"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.slots["route_type"] == "avoid_highway"

    def test_origin_already_filled(self, harness, ctx_with_vehicle):
        """origin 已有值，不覆盖"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "天府广场", "origin": "104.08,30.68"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.slots["origin"] == "104.08,30.68"

    # ── 别名解析：家 → L3 ──

    def test_alias_home(self, harness, ctx_with_vehicle):
        """回家 → L3 地址"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "家"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.slots["destination"] == "成都市高新区天府大道388号"

    def test_alias_home_variants(self, harness, ctx_with_vehicle):
        """回家的多种说法"""
        for alias in ["回家"]:
            result = harness.pre_validate(
                slots={"_intent": "navigate", "destination": alias},
                ctx=ctx_with_vehicle,
            )
            assert result.valid is True
            assert "天府大道" in result.slots["destination"]

    # ── 别名解析：公司 → L3 ──

    def test_alias_company(self, harness, ctx_with_vehicle):
        """去公司 → L3 地址"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "公司"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.slots["destination"] == "成都市锦江区红星路三段1号"

    # ── 别名解析：上次去的 → L2 ──

    def test_alias_last_destination(self, harness, ctx_with_vehicle):
        """上次去的 → L2 行程记忆"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "上次去的"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.slots["destination"] == "春熙路"

    # ── 失败 case：缺必填 ──

    def test_missing_destination(self, harness, ctx_with_vehicle):
        """缺少 destination → 追问"""
        result = harness.pre_validate(
            slots={"_intent": "navigate"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is False
        assert result.need_clarify is True
        assert "哪里" in result.clarify_message

    # ── 失败 case：别名解析失败 ──

    def test_alias_home_no_l3(self, harness, ctx_no_l3):
        """回家但 L3 没配置 → 追问"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "家"},
            ctx=ctx_no_l3,
        )
        assert result.valid is False
        assert result.need_clarify is True
        assert "设置" in result.clarify_message

    def test_alias_company_no_l3(self, harness, ctx_no_l3):
        """去公司但 L3 没配置 → 追问"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "公司"},
            ctx=ctx_no_l3,
        )
        assert result.valid is False
        assert result.need_clarify is True

    def test_alias_last_no_l2(self, harness, ctx_no_l2):
        """上次去的但 L2 没记录 → 追问"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "上次去的"},
            ctx=ctx_no_l2,
        )
        assert result.valid is False
        assert result.need_clarify is True
        assert "没有" in result.clarify_message

    # ── 失败 case：无位置 ──

    def test_no_vehicle_location(self, harness, ctx_no_location):
        """vehicle_state 无 location → 走云端兜底"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "天府广场"},
            ctx=ctx_no_location,
        )
        assert result.valid is False
        assert result.fallback is True

    # ── 安全检查 ──

    def test_high_speed_confirm(self, harness, ctx_high_speed):
        """高速行驶中改目的地 → 二次确认"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "天府广场"},
            ctx=ctx_high_speed,
        )
        assert result.valid is True
        assert result.need_confirm is True
        assert "120" in result.confirm_message

    def test_normal_speed_no_confirm(self, harness, ctx_with_vehicle):
        """正常速度不需要确认"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "天府广场"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is True
        assert result.need_confirm is False

    # ── 序号指代消解：从 L1 黑板取 POI ──

    def test_ordinal_first(self, harness, ctx_with_l1_poi):
        """去第一个 → L1 黑板第 0 个 POI"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "第一个"},
            ctx=ctx_with_l1_poi,
        )
        assert result.valid is True
        assert result.slots["destination"] == "川菜馆"

    def test_ordinal_second(self, harness, ctx_with_l1_poi):
        """去第二个 → L1 黑板第 1 个 POI"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "第二个"},
            ctx=ctx_with_l1_poi,
        )
        assert result.valid is True
        assert result.slots["destination"] == "火锅店"

    def test_ordinal_nearest(self, harness, ctx_with_l1_poi):
        """去最近那个 → L1 黑板第 0 个 POI"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "最近那个"},
            ctx=ctx_with_l1_poi,
        )
        assert result.valid is True
        assert result.slots["destination"] == "川菜馆"

    def test_ordinal_no_l1(self, harness, ctx_with_vehicle):
        """去第一个但 L1 黑板没有搜索结果 → 追问"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "第一个"},
            ctx=ctx_with_vehicle,
        )
        assert result.valid is False
        assert result.need_clarify is True
        assert "搜索结果" in result.clarify_message

    def test_ordinal_out_of_range(self, harness, ctx_with_l1_poi):
        """去第五个但只有 3 个结果 → 追问"""
        result = harness.pre_validate(
            slots={"_intent": "navigate", "destination": "第五个"},
            ctx=ctx_with_l1_poi,
        )
        assert result.valid is False
        assert result.need_clarify is True


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
        """搜索只有 1 个结果（distance 单位：米）"""
        text = harness.format_response({
            "success": True,
            "data": {
                "results": [{"name": "中石化加油站", "distance": 300, "address": "天府大道100号"}],
                "count": 1,
            },
        })
        assert "中石化加油站" in text
        assert "300米" in text

    def test_search_multiple_results(self, harness):
        """搜索多个结果，只播报前 3（distance 单位：米）"""
        text = harness.format_response({
            "success": True,
            "data": {
                "results": [
                    {"name": "中石化", "distance": 300},
                    {"name": "中石油", "distance": 500},
                    {"name": "壳牌", "distance": 1000},
                    {"name": "BP", "distance": 1500},
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
