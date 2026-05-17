"""
project1_cabin_agent/skills/navigation/harness.py
Navigation Skill Harness — 确定性校验+补全+兜底

设计原则（Skill 四大理念之"确定性兜底"）：
- harness 是纯函数：给定 (slots, ctx) → HarnessResult，不做任何 I/O
- 不调 LLM，不查 DB，不调 API
- CONTEXT_DEPS 声明需要哪些上下文层
- 三阶段：pre_validate → tools → post_validate → format_response
"""
from __future__ import annotations

from project1_cabin_agent.harness.base import BaseHarness, ContextDep, HarnessResult
from project1_cabin_agent.harness.context import AgentContext


class NavigationHarness(BaseHarness):
    """
    导航域 harness。
    
    CONTEXT_DEPS = VEHICLE | L2 | L3
    - VEHICLE: 需要当前位置（补 origin）、车速（安全检查）
    - L2: 需要行程记忆（"上次去的"指代消解）
    - L3: 需要用户偏好（"家"/"公司"地址解析）
    """

    CONTEXT_DEPS = ContextDep.VEHICLE | ContextDep.L2 | ContextDep.L3

    # ── 语义别名映射（L3 级别的常用别名） ──
    _ALIAS_HOME = {"家", "回家", "回家"}
    _ALIAS_COMPANY = {"公司", "单位", "上班"}
    _ALIAS_LAST = {"上次去的", "上次那里", "刚才那里", "上次去的那个地方"}

    def pre_validate(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """
        LLM 输出后、调 tool 前的校验+补全。
        
        职责：
        1. destination 必填检查
        2. 语义别名解析（家→L3地址，公司→L3地址，上次去的→L2记录）
        3. origin 补全（从 vehicle_state 取当前位置）
        4. 安全检查（高速行驶中改目的地）
        """
        destination = slots.get("destination", "")

        # ── 1. 必填检查 ──
        if not destination:
            return HarnessResult(
                valid=False,
                slots=slots,
                need_clarify=True,
                clarify_message="请问您要导航到哪里？",
                block_reason="缺少 destination",
            )

        # ── 2. 语义别名解析：家 → L3 ──
        if destination in self._ALIAS_HOME:
            user = ctx.get_user()
            home = user.get("home_address", "")
            if not home:
                return HarnessResult(
                    valid=False,
                    slots=slots,
                    need_clarify=True,
                    clarify_message="您还没有设置家的地址，请先在设置中添加",
                    block_reason=f"别名'{destination}'解析失败：L3 无 home_address",
                )
            slots = {**slots, "destination": home}

        # ── 3. 语义别名解析：公司 → L3 ──
        elif destination in self._ALIAS_COMPANY:
            user = ctx.get_user()
            company = user.get("company_address", "")
            if not company:
                return HarnessResult(
                    valid=False,
                    slots=slots,
                    need_clarify=True,
                    clarify_message="您还没有设置公司地址，请先在设置中添加",
                    block_reason=f"别名'{destination}'解析失败：L3 无 company_address",
                )
            slots = {**slots, "destination": company}

        # ── 4. 语义别名解析：上次去的 → L2 ──
        elif destination in self._ALIAS_LAST:
            last_dest = ctx.session.get("last_destination", "")
            if not last_dest:
                return HarnessResult(
                    valid=False,
                    slots=slots,
                    need_clarify=True,
                    clarify_message="本次行程没有导航记录",
                    block_reason=f"别名'{destination}'解析失败：L2 无 last_destination",
                )
            slots = {**slots, "destination": last_dest}

        # ── 5. origin 补全：从 vehicle_state 取当前位置 ──
        if not slots.get("origin"):
            current_location = ctx.vehicle.location
            if not current_location:
                return HarnessResult(
                    valid=False,
                    slots=slots,
                    fallback=True,
                    block_reason="vehicle_state 无 location，无法补全 origin",
                )
            slots = {**slots, "origin": current_location}

        # ── 6. 安全检查：高速行驶中改目的地 ──
        if ctx.vehicle.speed > 100 and slots.get("origin"):
            return HarnessResult(
                valid=True,
                slots=slots,
                need_confirm=True,
                confirm_message=f"当前车速{int(ctx.vehicle.speed)}km/h，确定要导航到{slots['destination']}吗？",
            )

        return HarnessResult(valid=True, slots=slots)

    def post_validate(self, tool_result: dict, ctx: AgentContext) -> HarnessResult:
        """
        tool 返回后、给用户前的校验。
        
        职责：
        1. API 调用失败 → 兜底提示
        2. 距离异常检查（>5000km 追问）
        3. 空结果处理
        """
        # ── 1. API 失败 ──
        if not tool_result.get("success"):
            error = tool_result.get("error", "未知错误")
            return HarnessResult(
                valid=False,
                slots={},
                fallback=True,
                block_reason=f"API 失败: {error}",
            )

        data = tool_result.get("data", {})

        # ── 2. search_nearby 空结果 ──
        if "results" in data:
            count = data.get("count", 0)
            if count == 0:
                return HarnessResult(
                    valid=True,
                    slots={},
                    block_reason="搜索无结果",
                )

        # ── 3. navigate_to 距离异常 ──
        distance = data.get("distance")
        if distance is not None and distance > 5000:
            return HarnessResult(
                valid=True,
                slots={},
                need_confirm=True,
                confirm_message=f"目的地距离{distance}公里，确定要导航吗？",
            )

        return HarnessResult(valid=True, slots={})

    def format_response(self, tool_result: dict) -> str:
        """
        确定性格式化输出，不经过 LLM。
        
        把 API 返回的原始数据格式化成用户可读的语音文本。
        """
        if not tool_result.get("success"):
            error = tool_result.get("error", "服务暂时不可用")
            return f"导航失败：{error}，请稍后再试"

        data = tool_result.get("data", {})

        # ── navigate_to 结果格式化 ──
        if "route_text" in data:
            distance = data.get("distance", 0)
            duration = data.get("duration", 0)
            tolls = data.get("tolls", 0)

            parts = [f"已为您规划路线，全程{distance}公里，预计{duration}分钟"]
            if tolls > 0:
                parts.append(f"过路费约{int(tolls)}元")
            return "，".join(parts) + "。"

        # ── search_nearby 结果格式化 ──
        if "results" in data:
            results = data.get("results", [])
            count = data.get("count", 0)

            if count == 0:
                return "附近没有找到相关地点。"

            # 只播报前 3 个
            top = results[:3]
            if count == 1:
                r = top[0]
                return f"找到一家{r['name']}，距离{r['dist_km']}公里，地址是{r['address']}。"
            else:
                items = []
                for i, r in enumerate(top, 1):
                    items.append(f"第{i}，{r['name']}，{r['dist_km']}公里")
                return f"为您找到{count}个结果：{'；'.join(items)}。"

        return "操作完成。"
