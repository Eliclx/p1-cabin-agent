"""
project1_cabin_agent/tests/test_da.py — DA（Dialogue Act）识别测试

测试 DA 分类的正确性：confirm/deny/correction/select/new_intent。
纯函数测试，零外部依赖。

解耦验证：
  - 通用规则在 nodes/da.py（confirm/deny/select_index）
  - 域规则在 skills/{domain}/da_rules.py
  - 引擎从 registry 加载域规则
"""

import pytest

from project1_cabin_agent.nodes.da import (
    DAResult,
    DialogueAct,
    _rule_confirm,
    _rule_deny,
    _rule_select_index,
    classify_dialogue_act,
)


# ═══════════════════════════════════════════════════
# 通用规则：CONFIRM
# ═══════════════════════════════════════════════════


class TestConfirm:
    @pytest.mark.parametrize(
        "text",
        [
            "好",
            "好的",
            "确认",
            "确定",
            "可以",
            "行",
            "嗯",
            "对",
            "是的",
            "是",
            "要",
            "执行",
            "没问题",
            "OK",
            "ok",
        ],
    )
    def test_confirm_words(self, text):
        result = _rule_confirm(text, {})
        assert result is not None
        assert result.act == DialogueAct.CONFIRM

    @pytest.mark.parametrize(
        "text",
        [
            "不好",
            "不要",
            "不对",
            "算了",
            "取消",
        ],
    )
    def test_not_confirm(self, text):
        result = _rule_confirm(text, {})
        assert result is None

    def test_long_text_not_confirm(self):
        result = _rule_confirm("好的，请帮我开空调", {})
        assert result is None  # 长文本不匹配精确模式


# ═══════════════════════════════════════════════════
# 通用规则：DENY
# ═══════════════════════════════════════════════════


class TestDeny:
    @pytest.mark.parametrize(
        "text",
        [
            "不",
            "不要",
            "不用",
            "不用了",
            "算了",
            "取消",
            "别",
            "不行",
            "否",
            "不要了",
            "取消吧",
            "算了",
        ],
    )
    def test_deny_words(self, text):
        result = _rule_deny(text, {})
        assert result is not None
        assert result.act == DialogueAct.DENY

    @pytest.mark.parametrize(
        "text",
        [
            "好的",
            "确认",
            "要",
            "是",
        ],
    )
    def test_not_deny(self, text):
        result = _rule_deny(text, {})
        assert result is None


# ═══════════════════════════════════════════════════
# 通用规则：SELECT (序号)
# ═══════════════════════════════════════════════════


class TestSelectIndex:
    @pytest.mark.parametrize(
        "text,expected_idx",
        [
            ("第一个", 0),
            ("第二个", 1),
            ("第三个", 2),
            ("第1个", 0),
            ("第2个", 1),
            ("1号", 0),
            ("2号", 1),
        ],
    )
    def test_select_index(self, text, expected_idx):
        result = _rule_select_index(text, {})
        assert result is not None
        assert result.act == DialogueAct.SELECT
        assert result.selection["index"] == expected_idx

    @pytest.mark.parametrize(
        "text",
        [
            "第一",  # 不完整
            "个",  # 无序号
            "导航去重庆",  # 新意图
        ],
    )
    def test_not_select(self, text):
        result = _rule_select_index(text, {})
        assert result is None


# ═══════════════════════════════════════════════════
# 引擎集成
# ═══════════════════════════════════════════════════


class TestClassify:
    def test_confirm_via_engine(self):
        result = classify_dialogue_act("好的", {})
        assert result is not None
        assert result.act == DialogueAct.CONFIRM

    def test_deny_via_engine(self):
        result = classify_dialogue_act("不要", {})
        assert result is not None
        assert result.act == DialogueAct.DENY

    def test_select_via_engine(self):
        result = classify_dialogue_act("第一个", {})
        assert result is not None
        assert result.act == DialogueAct.SELECT
        assert result.selection["index"] == 0

    def test_new_intent_returns_none(self):
        result = classify_dialogue_act("空调开到24度", {})
        assert result is None  # 无法分类 → NEW_INTENT

    def test_deny_priority_over_confirm(self):
        # "不" 在 deny 和 confirm 之间，deny 优先
        result = classify_dialogue_act("不", {})
        assert result.act == DialogueAct.DENY


# ═══════════════════════════════════════════════════
# Climate 域规则：CORRECTION
# ═══════════════════════════════════════════════════


class TestClimateCorrection:
    def test_change_to_heat(self):
        from project1_cabin_agent.skills.climate.da_rules import rule_climate_correction

        result = rule_climate_correction("不要制冷", {"last_intent": "ac_control"})
        assert result is not None
        assert result.act == DialogueAct.CORRECTION
        assert result.corrections["mode"] == "heat"

    def test_change_to_cool(self):
        from project1_cabin_agent.skills.climate.da_rules import rule_climate_correction

        result = rule_climate_correction("不要制热", {"last_intent": "ac_control"})
        assert result is not None
        assert result.corrections["mode"] == "cool"

    def test_change_to_auto(self):
        from project1_cabin_agent.skills.climate.da_rules import rule_climate_correction

        result = rule_climate_correction("改成自动", {"last_intent": "ac_control"})
        assert result is not None
        assert result.corrections["mode"] == "auto"

    def test_change_temperature(self):
        from project1_cabin_agent.skills.climate.da_rules import rule_climate_correction

        result = rule_climate_correction(
            "太冷了调到26度", {"last_intent": "ac_control"}
        )
        assert result is not None
        assert result.corrections["temperature"] == 26

    def test_wrong_intent_no_correction(self):
        from project1_cabin_agent.skills.climate.da_rules import rule_climate_correction

        result = rule_climate_correction("不要制冷", {"last_intent": "navigate"})
        assert result is None

    def test_via_engine(self):
        result = classify_dialogue_act(
            "不要制冷",
            {
                "last_domain": "climate",
                "last_intent": "ac_control",
            },
        )
        assert result is not None
        assert result.act == DialogueAct.CORRECTION
        assert result.corrections["mode"] == "heat"


# ═══════════════════════════════════════════════════
# Map 域规则：SELECT + CORRECTION
# ═══════════════════════════════════════════════════


class TestMapDA:
    def test_select_by_name(self):
        from project1_cabin_agent.skills.map.da_rules import rule_map_select_by_name

        candidates = [
            {"name": "海底捞火锅(春熙路店)"},
            {"name": "小龙坎(科华北路店)"},
        ]
        result = rule_map_select_by_name(
            "小龙坎",
            {
                "last_intent": "search_poi",
                "candidates": candidates,
            },
        )
        assert result is not None
        assert result.act == DialogueAct.SELECT
        assert result.selection["index"] == 1
        assert result.selection["name"] == "小龙坎(科华北路店)"

    def test_select_name_not_found(self):
        from project1_cabin_agent.skills.map.da_rules import rule_map_select_by_name

        result = rule_map_select_by_name(
            "不存在的店",
            {
                "last_intent": "search_poi",
                "candidates": [{"name": "海底捞"}],
            },
        )
        assert result is None

    def test_avoid_toll(self):
        from project1_cabin_agent.skills.map.da_rules import rule_map_correction

        result = rule_map_correction("不要收费的", {"last_intent": "navigate"})
        assert result is not None
        assert result.act == DialogueAct.CORRECTION
        assert result.corrections["avoid_toll"] is True

    def test_avoid_highway(self):
        from project1_cabin_agent.skills.map.da_rules import rule_map_correction

        result = rule_map_correction("不走高速", {"last_intent": "navigate"})
        assert result is not None
        assert result.corrections["avoid_highway"] is True

    def test_route_shortest(self):
        from project1_cabin_agent.skills.map.da_rules import rule_map_correction

        result = rule_map_correction("走近路", {"last_intent": "navigate"})
        assert result is not None
        assert result.corrections["route_type"] == "shortest"

    def test_route_fastest(self):
        from project1_cabin_agent.skills.map.da_rules import rule_map_correction

        result = rule_map_correction("赶时间走最快的", {"last_intent": "navigate"})
        assert result is not None
        assert result.corrections["route_type"] == "fastest"

    def test_correction_via_engine(self):
        result = classify_dialogue_act(
            "不要收费的",
            {
                "last_domain": "map",
                "last_intent": "navigate",
            },
        )
        assert result is not None
        assert result.act == DialogueAct.CORRECTION


# ═══════════════════════════════════════════════════
# DAResult 序列化
# ═══════════════════════════════════════════════════


class TestDAResultSerialization:
    def test_to_dict(self):
        r = DAResult(
            act=DialogueAct.CORRECTION,
            corrections={"mode": "heat"},
            raw_input="不要制冷",
        )
        d = r.to_dict()
        assert d["act"] == "correction"
        assert d["corrections"]["mode"] == "heat"
        assert d["raw_input"] == "不要制冷"

    def test_from_dict(self):
        d = {"act": "select", "selection": {"index": 0}, "raw_input": "第一个"}
        r = DAResult.from_dict(d)
        assert r.act == DialogueAct.SELECT
        assert r.selection["index"] == 0

    def test_roundtrip(self):
        original = DAResult(
            act=DialogueAct.DENY,
            confidence=1.0,
            raw_input="不要",
        )
        restored = DAResult.from_dict(original.to_dict())
        assert restored.act == original.act
        assert restored.raw_input == original.raw_input


# ═══════════════════════════════════════════════════
# 端到端场景
# ═══════════════════════════════════════════════════


class TestE2EScenarios:
    """模拟真实对话流程中的 DA 分类"""

    def test_confirm_after_ask(self):
        """Agent: 确认打开所有车窗吗？ 用户: 好的"""
        result = classify_dialogue_act("好的", {"last_intent": "window_control"})
        assert result.act == DialogueAct.CONFIRM

    def test_deny_after_ask(self):
        """Agent: 确认打开所有车窗吗？ 用户: 算了"""
        result = classify_dialogue_act("算了", {"last_intent": "window_control"})
        assert result.act == DialogueAct.DENY

    def test_select_poi(self):
        """Agent: 找到3个火锅店 用户: 第一个"""
        result = classify_dialogue_act("第一个", {})
        assert result.act == DialogueAct.SELECT
        assert result.selection["index"] == 0

    def test_correction_mode(self):
        """Agent: 空调24度制冷 用户: 不要制冷"""
        result = classify_dialogue_act(
            "不要制冷",
            {
                "last_domain": "climate",
                "last_intent": "ac_control",
            },
        )
        assert result.act == DialogueAct.CORRECTION
        assert result.corrections["mode"] == "heat"

    def test_correction_route(self):
        """Agent: 导航路线规划好了 用户: 不要收费的"""
        result = classify_dialogue_act(
            "不要收费的",
            {
                "last_domain": "map",
                "last_intent": "navigate",
            },
        )
        assert result.act == DialogueAct.CORRECTION
        assert result.corrections["avoid_toll"] is True

    def test_normal_intent_passes_through(self):
        """正常新意图不被 DA 拦截"""
        result = classify_dialogue_act("空调开到24度", {})
        assert result is None

        result = classify_dialogue_act("导航去重庆", {})
        assert result is None
