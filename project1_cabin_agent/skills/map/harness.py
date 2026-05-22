"""
project1_cabin_agent/skills/map/harness.py
Map Skill Harness — 确定性校验+补全+兜底

设计原则（Skill 四大理念之"确定性兜底"）：
- harness 是纯函数：给定 (slots, ctx) → HarnessResult，不做任何 I/O
- 不调 LLM，不查 DB，不调 API
- CONTEXT_DEPS 声明需要哪些上下文层
- 三阶段：pre_validate → tools → post_validate → format_response

合并自：
- navigation/harness.py → search_poi, navigate 的校验逻辑
- search/harness.py → search_poi 的部分逻辑
- 新增 → map_query, weather 的校验逻辑
"""
from __future__ import annotations

from project1_cabin_agent.harness.base import BaseHarness, ContextDep, HarnessResult
from project1_cabin_agent.harness.context import AgentContext
from shared.utils.logger import logger


class MapHarness(BaseHarness):
    """
    地图域 harness（合并 navigation + search → map）。

    CONTEXT_DEPS = VEHICLE | L1 | L2 | L3
    - VEHICLE: 需要当前位置（补 origin/location）、车速（安全检查）
    - L1: 需要黑板记忆（"去第一个"→从 entity.poi 取上次搜索结果）
    - L2: 需要行程记忆（"上次去的"指代消解）
    - L3: 需要用户偏好（"家"/"公司"地址解析）
    """

    CONTEXT_DEPS = ContextDep.VEHICLE | ContextDep.L1 | ContextDep.L2 | ContextDep.L3

    # ── 语义别名映射（L3 级别的常用别名） ──
    _ALIAS_HOME = {"家", "回家"}
    _ALIAS_COMPANY = {"公司", "单位", "上班"}
    _ALIAS_LAST = {"上次去的", "上次那里", "刚才那里", "上次去的那个地方"}

    # ── 序号指代消解 ──
    _ORDINALS = {
        "第一个": 0, "第二个": 1, "第三个": 2, "第四个": 3, "第五个": 4,
        "第1个": 0, "第2个": 1, "第3个": 2, "第4个": 3, "第5个": 4,
        "最近那个": 0, "最近的那家": 0, "最近的": 0,
    }

    # ═══════════════════════════════════════════════════════════
    # pre_validate — 按 intent 分发
    # ═══════════════════════════════════════════════════════════

    def pre_validate(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """
        LLM 输出后、调 tool 前的校验+补全。

        按 intent 分发到对应的校验方法：
        - search_poi: keyword 必填 + location 自动补全
        - navigate: destination 必填 + 别名解析 + origin 补全 + 安全检查
        - map_query: query_type 默认补 location
        - weather: 基本通过
        """
        intent = slots.get("_intent", "")

        if intent == "search_poi":
            return self._validate_search_poi(slots, ctx)
        elif intent == "navigate":
            return self._validate_navigate(slots, ctx)
        elif intent == "map_query":
            return self._validate_map_query(slots, ctx)
        elif intent == "weather":
            return self._validate_weather(slots, ctx)

        # 未知 intent 直接放行
        return HarnessResult(valid=True, slots=slots)

    # ── search_poi 校验 ──

    def _validate_search_poi(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """search_poi: keyword 必填 + location 自动补全"""
        keyword = slots.get("keyword", "")
        if not keyword:
            return HarnessResult(
                valid=False, slots=slots,
                need_clarify=True,
                clarify_message="请问您想搜索什么？",
                block_reason="缺少 keyword",
            )

        # location 自动补全
        if not slots.get("location"):
            loc = ctx.vehicle.location
            if not loc:
                return HarnessResult(
                    valid=False, slots=slots, fallback=True,
                    block_reason="vehicle_state 无 location",
                )
            slots = {**slots, "location": loc}

        # radius 范围约束（100~50000 米）
        radius = slots.get("radius")
        if radius is not None:
            if radius < 100:
                slots = {**slots, "radius": 100}
            elif radius > 50000:
                slots = {**slots, "radius": 50000}

        return HarnessResult(valid=True, slots=slots)

    # ── navigate 校验 ──

    def _validate_navigate(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """navigate: destination 必填 + 别名解析 + 序号指代消解 + origin 补全 + 安全检查"""
        destination = slots.get("destination", "")

        # ── 1. 必填检查 ──
        if not destination:
            return HarnessResult(
                valid=False, slots=slots,
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
                    valid=False, slots=slots,
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
                    valid=False, slots=slots,
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
                    valid=False, slots=slots,
                    need_clarify=True,
                    clarify_message="本次行程没有导航记录",
                    block_reason=f"别名'{destination}'解析失败：L2 无 last_destination",
                )
            slots = {**slots, "destination": last_dest}

        # ── 4.5 序号指代消解：\"第一个\"/\"最近那个\" → L1 黑板 ──
        elif destination in self._ORDINALS:
            resolved = self._resolve_ordinal(destination, ctx.dialogue)
            if not resolved:
                return HarnessResult(
                    valid=False, slots=slots,
                    need_clarify=True,
                    clarify_message="没有找到之前的搜索结果，请告诉我具体目的地",
                    block_reason=f"序号指代'{destination}'解析失败：L1 黑板无 entity.poi",
                )
            slots = {**slots, "destination": resolved}

        # ── 5. origin 补全：从 vehicle_state 取当前位置 ──
        if not slots.get("origin"):
            current_location = ctx.vehicle.location
            if not current_location:
                return HarnessResult(
                    valid=False, slots=slots, fallback=True,
                    block_reason="vehicle_state 无 location，无法补全 origin",
                )
            slots = {**slots, "origin": current_location}

        # ── 5.5 槽位名归一化：旧 prompt 用 mode，新 schema 用 route_type ──
        if "mode" in slots and "route_type" not in slots:
            slots = {**slots, "route_type": slots["mode"]}

        # ── 6. 安全检查：高速行驶中改目的地 ──
        if ctx.vehicle.speed > 100:
            return HarnessResult(
                valid=True, slots=slots,
                need_confirm=True,
                confirm_message=f"当前车速{int(ctx.vehicle.speed)}km/h，确定要导航到{slots['destination']}吗？",
            )

        return HarnessResult(valid=True, slots=slots)

    # ── map_query 校验 ──

    def _validate_map_query(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """map_query: query_type 默认补 location，location 自动补全"""
        # query_type 默认补 location
        if not slots.get("query_type"):
            slots = {**slots, "query_type": "location"}

        # location 自动补全（给 tools 传递当前位置）
        if not slots.get("location"):
            loc = ctx.vehicle.location
            if not loc:
                return HarnessResult(
                    valid=False, slots=slots, fallback=True,
                    block_reason="vehicle_state 无 location",
                )
            slots = {**slots, "location": loc}

        return HarnessResult(valid=True, slots=slots)

    # ── weather 校验 ──

    def _validate_weather(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """weather: 基本通过，缺 city 时从当前位置推断（传 location 给 tools）"""
        # date 默认补"今天"
        if not slots.get("date"):
            slots = {**slots, "date": "今天"}

        # 如果没有 city，补当前位置让 tools 推断
        if not slots.get("city"):
            loc = ctx.vehicle.location
            if loc:
                slots = {**slots, "location": loc}
            # 即使没 location 也放行，tools 会返回错误让用户补充

        return HarnessResult(valid=True, slots=slots)

    # ═══════════════════════════════════════════════════════════
    # post_validate — 工具返回后校验
    # ═══════════════════════════════════════════════════════════

    def post_validate(self, tool_result: dict, ctx: AgentContext) -> HarnessResult:
        """
        tool 返回后、给用户前的校验。

        职责：
        1. API 调用失败 → 兜底提示
        2. search_poi 空结果 → 正常返回
        3. navigate 距离异常（>5000km）→ 追问确认
        """
        # ── 1. API 失败 ──
        if not tool_result.get("success"):
            error = tool_result.get("error", "未知错误")
            return HarnessResult(
                valid=False, slots={},
                fallback=True,
                block_reason=f"API 失败: {error}",
            )

        data = tool_result.get("data", {})

        # ── 2. search_poi 空结果 ──
        if "results" in data:
            count = data.get("count", 0)
            if count == 0:
                return HarnessResult(
                    valid=True, slots={},
                    block_reason="搜索无结果",
                )

        # ── 3. navigate 距离异常 ──
        distance = data.get("distance")
        if distance is not None and distance > 5000:
            return HarnessResult(
                valid=True, slots={},
                need_confirm=True,
                confirm_message=f"目的地距离{distance}公里，确定要导航吗？",
            )

        return HarnessResult(valid=True, slots={})

    # ═══════════════════════════════════════════════════════════
    # format_response — 确定性格式化输出
    # ═══════════════════════════════════════════════════════════

    def format_response(self, tool_result: dict) -> str:
        """
        确定性格式化输出，不经过 LLM。

        按 intent 格式化：
        - search_poi: "找到N个结果，最近的是XXX"
        - navigate: "已规划路线，全程X公里，预计X分钟"
        - map_query: 按 query_type 格式化
        - weather: "XX天气：XX，温度XX度"
        """
        if not tool_result.get("success"):
            error = tool_result.get("error", "服务暂时不可用")
            return f"操作失败：{error}，请稍后再试"

        data = tool_result.get("data", {})

        # ── search_poi 结果格式化 ──
        if "results" in data:
            return self._format_search_poi(data)

        # ── navigate 结果格式化 ──
        if "route_text" in data:
            return self._format_navigate(data)

        # ── map_query 结果格式化 ──
        if "query_type" in data:
            return self._format_map_query(data)

        # ── weather 结果格式化 ──
        if "weather" in data:
            return self._format_weather(data)

        return "操作完成。"

    def _format_search_poi(self, data: dict) -> str:
        """格式化 search_poi 结果"""
        results = data.get("results", [])
        count = data.get("count", 0)

        if count == 0:
            return "附近没有找到相关地点。"

        # 播报前 3 个，超出部分提示
        top = results[:3]
        remaining = count - len(top)
        if count == 1:
            r = top[0]
            dist = r.get("distance", 0)
            # 距离格式化
            dist_str = f"{dist}米" if dist < 1000 else f"{round(dist / 1000, 1)}公里"
            return f"找到一家{r['name']}，距离{dist_str}，地址是{r.get('address', '')}。"
        else:
            items = []
            for i, r in enumerate(top, 1):
                dist = r.get("distance", 0)
                dist_str = f"{dist}米" if dist < 1000 else f"{round(dist / 1000, 1)}公里"
                items.append(f"第{i}，{r['name']}，{dist_str}")
            text = f"为您找到{count}个结果：{'；'.join(items)}"
            if remaining > 0:
                text += f"；还有{remaining}个，需要可以说第几个"
            return text + "。"

    def _format_navigate(self, data: dict) -> str:
        """格式化 navigate 结果"""
        distance = data.get("distance", 0)
        duration = data.get("duration", 0)
        tolls = data.get("tolls", 0)

        parts = [f"已为您规划路线，全程{distance}公里，预计{duration}分钟"]
        if tolls > 0:
            parts.append(f"过路费约{int(tolls)}元")
        return "，".join(parts) + "。"

    def _format_map_query(self, data: dict) -> str:
        """格式化 map_query 结果"""
        query_type = data.get("query_type", "")

        if query_type == "location":
            address = data.get("address", "")
            city = data.get("city", "")
            district = data.get("district", "")
            return f"您当前位置在{city}{district}，{address}。"

        if query_type == "distance":
            target = data.get("target", "")
            dist_km = data.get("distance_km", 0)
            return f"距离{target}大约{dist_km}公里。"

        if query_type == "traffic":
            target = data.get("target", "")
            duration_min = data.get("duration_min", 0)
            traffic_info = data.get("traffic", [])
            # 简化路况播报
            jammed = [t for t in traffic_info if t.get("status") in ("拥堵", "缓行")]
            if jammed:
                roads = "、".join(t["road"] for t in jammed[:3])
                return f"到{target}的路上，{roads}路段有拥堵，预计需要{duration_min}分钟。"
            return f"到{target}的路况比较畅通，预计需要{duration_min}分钟。"

        if query_type == "eta":
            target = data.get("target", "")
            eta_min = data.get("eta_min", 0)
            dist_km = data.get("distance_km", 0)
            return f"距离{target}还有{dist_km}公里，预计{eta_min}分钟到达。"

        return "查询完成。"

    def _format_weather(self, data: dict) -> str:
        """格式化 weather 结果"""
        city = data.get("city", "")
        weather_desc = data.get("weather", "")
        date = data.get("date", "")

        # 当天实况
        if "temperature" in data:
            temp = data["temperature"]
            return f"{city}{date}天气：{weather_desc}，温度{temp}度。"

        # 预报
        if "temperature_lo" in data and "temperature_hi" in data:
            lo = data["temperature_lo"]
            hi = data["temperature_hi"]
            return f"{city}{date}天气：{weather_desc}，温度{lo}到{hi}度。"

        return f"{city}{date}天气：{weather_desc}。"

    # ═══════════════════════════════════════════════════════════
    # 序号指代消解辅助方法
    # ═══════════════════════════════════════════════════════════

    def _is_ordinal(self, text: str) -> bool:
        """判断是否是序号指代（"第一个"/"最近那个"）"""
        return text in self._ORDINALS

    def _resolve_ordinal(self, ordinal: str, dialogue: dict) -> str:
        """
        从 L1 黑板 entity.poi 解析序号指代。

        dialogue 是黑板展开后的 flat dict，key 如 "entity.poi"
        每个值是上次 search_poi 的结果列表
        """
        idx = self._ORDINALS.get(ordinal, 0)

        # 从黑板取 entity.poi 的栈顶（最新搜索结果）
        poi_data = dialogue.get("entity.poi", {})
        results = poi_data.get("results", []) if isinstance(poi_data, dict) else []

        if idx < len(results):
            resolved = results[idx].get("name", "")
            if resolved:
                logger.info(f"[序号指代] '{ordinal}' → entity.poi[{idx}] = '{resolved}'")
            return resolved

        return ""
