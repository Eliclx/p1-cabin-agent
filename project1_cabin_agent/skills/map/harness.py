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
        "第一个": 0,
        "第二个": 1,
        "第三个": 2,
        "第四个": 3,
        "第五个": 4,
        "第1个": 0,
        "第2个": 1,
        "第3个": 2,
        "第4个": 3,
        "第5个": 4,
        "最近那个": 0,
        "最近的那家": 0,
        "最近的": 0,
    }

    # ═══════════════════════════════════════════════════════════

    def _find_poi_coordinates(
        self, destination_name: str, dialogue: dict
    ) -> str | None:
        """从黑板 entity.poi 中查找与 destination_name 匹配的 POI 精确坐标

        用于解决"同名不同店"问题：POI 搜索返回精确坐标，
        但 LLM 填的 destination 是文字名，地理编码可能匹配到另一个分店。
        """
        poi_data = dialogue.get("entity.poi", {})
        if not poi_data:
            return None

        # context_enrich 展开后是嵌套结构: {"success": true, "data": {"results": [...]}}
        inner = poi_data.get("data", poi_data)
        results = inner.get("results", [])
        if not results:
            return None

        # 模糊匹配 POI 名称（destination 可能是 LLM 简化的版本）
        for poi in results:
            name = poi.get("name", "")
            if (
                name == destination_name
                or destination_name in name
                or name in destination_name
            ):
                lng = poi.get("lng")
                lat = poi.get("lat")
                if lng is not None and lat is not None:
                    return f"{lng},{lat}"

        return None

    # ═══════════════════════════════════════════════════════════
    # infer_slots — 基于上下文的语义槽位推断
    # ═══════════════════════════════════════════════════════════

    def infer_slots(self, slots: dict, ctx: AgentContext, user_input: str) -> dict:
        """地图域语义推断：别名解析、origin补全、默认值推断。

        职责（只补缺，不校验）：
        - destination 别名: "家"→L3, "公司"→L3, "上次去的"→L2, "第一个"→L1
        - origin 自动补全: 从 vehicle_state 取当前位置
        - location 自动补全: search_poi/weather/map_query 的位置
        - 默认值: weather.date→"今天", map_query.query_type→"location"
        - 归一化: mode→route_type
        """
        result = {**slots}
        intent = slots.get("_intent", "")

        if intent == "navigate":
            result = self._infer_navigate(result, ctx)
        elif intent == "search_poi":
            result = self._infer_search_poi(result, ctx)
        elif intent == "map_query":
            result = self._infer_map_query(result, ctx)
        elif intent == "weather":
            result = self._infer_weather(result, ctx, user_input)

        return result

    def _infer_navigate(self, slots: dict, ctx: AgentContext) -> dict:
        """navigate 推断: 别名解析 + origin补全 + mode归一化"""
        result = {**slots}
        destination = result.get("destination", "")

        # ── 1. 别名解析: 家 → L3 ──
        if destination in self._ALIAS_HOME:
            user = ctx.get_user()
            home = user.get("home_address", "")
            if home:
                result["destination"] = home
                logger.info(f"[slot_infer] navigate: '家' → '{home}'")

        # ── 2. 别名解析: 公司 → L3 ──
        elif destination in self._ALIAS_COMPANY:
            user = ctx.get_user()
            company = user.get("company_address", "")
            if company:
                result["destination"] = company
                logger.info(f"[slot_infer] navigate: '公司' → '{company}'")

        # ── 3. 别名解析: 上次去的 → L2 ──
        elif destination in self._ALIAS_LAST:
            last_dest = ctx.session.get("last_destination", "")
            if last_dest:
                result["destination"] = last_dest
                logger.info(f"[slot_infer] navigate: '上次去的' → '{last_dest}'")

        # ── 4. 序号指代消解: "第一个" → L1 黑板 ──
        elif destination in self._ORDINALS:
            resolved = self._resolve_ordinal(destination, ctx.dialogue)
            if resolved:
                result["destination"] = resolved
                logger.info(f"[slot_infer] navigate: '{destination}' → '{resolved}'")

        # ── 5. origin 自动补全 ──
        if not result.get("origin"):
            loc = ctx.vehicle.location
            if loc:
                result["origin"] = loc
                logger.info(f"[slot_infer] navigate: origin 补全 → '{loc}'")

        # ── 6. mode → route_type 归一化 ──
        if "mode" in result and "route_type" not in result:
            result["route_type"] = result["mode"]

        # ── 7. 精确坐标替换: 如果黑板有 POI 坐标，用坐标替换文字 destination ──
        # 避免地名重新地理编码导致路线偏差（同名不同店问题）
        dest = result.get("destination", "")
        if dest:
            coord = self._find_poi_coordinates(dest, ctx.dialogue)
            if coord:
                result["destination"] = coord
                logger.info(f"[slot_infer] navigate: 精确坐标替换 '{dest}' → '{coord}'")

        return result

    def _infer_search_poi(self, slots: dict, ctx: AgentContext) -> dict:
        """search_poi 推断: location 自动补全"""
        result = {**slots}
        if not result.get("location"):
            loc = ctx.vehicle.location
            if loc:
                result["location"] = loc
                logger.info(f"[slot_infer] search_poi: location 补全 → '{loc}'")
        return result

    def _infer_map_query(self, slots: dict, ctx: AgentContext) -> dict:
        """map_query 推断: query_type 默认 + location 补全"""
        result = {**slots}
        if not result.get("query_type"):
            result["query_type"] = "location"
            logger.info("[slot_infer] map_query: query_type 默认 → 'location'")
        if not result.get("location"):
            loc = ctx.vehicle.location
            if loc:
                result["location"] = loc
                logger.info(f"[slot_infer] map_query: location 补全 → '{loc}'")
        return result

    # 幻觉词黑名单 — 这些词永远不会出现在真实城市名里
    _HALLUCINATION_WORDS = frozenset(
        {
            "默认",
            "获取",
            "根据",
            "系统",
            "自动",
            "所在",
            "当前",
            "位置",
            "用户",
            "填充",
            "推断",
            "以下",
        }
    )

    def _is_hallucinated_city(self, city: str, user_input: str) -> bool:
        """判断端侧模型填的 city 是否是幻觉"""
        # 检查1: 包含指令性词汇 → 100% 幻觉
        if any(w in city for w in self._HALLUCINATION_WORDS):
            return True
        # 检查2: 城市名核心部分是否出现在用户输入里
        core = city.rstrip("市省区县特别行政区")
        if core and core in user_input:
            return False  # 用户提到了，真实值
        # 检查3: 用户没说城市 → 可能是幻觉，保守丢弃
        return True

    def _infer_weather(
        self, slots: dict, ctx: AgentContext, user_input: str = ""
    ) -> dict:
        """weather 推断: city 三级优先级 + date 默认

        优先级1: 用户明确说了城市 → LLM 提取的 city 通过幻觉检测 → 信任
        优先级2: 黑板上轮 entity.weather 的 city → 复用（"明天呢" 场景）
        优先级3: vehicle_state.location → 坐标兜底
        """
        result = {**slots}

        # ── date 默认 ──
        if not result.get("date"):
            result["date"] = "今天"
            logger.info("[slot_infer] weather: date 默认 → '今天'")

        # ── city 三级优先级 ──
        city = result.get("city", "")

        # 优先级1: LLM/端侧提取的 city → 幻觉检测
        if city and not self._is_hallucinated_city(city, user_input):
            pass  # 合法城市，保留
            logger.info(f"[slot_infer] weather: city 优先级1(用户指定) → '{city}'")
        else:
            if city:
                logger.warning(f"[slot_infer] weather: city='{city}' 疑似幻觉，清除")
                del result["city"]
                city = ""

        # 优先级2: 黑板上轮 entity.weather → 复用 city
        if not city:
            weather_entry = ctx.dialogue.get("entity.weather", {})
            if isinstance(weather_entry, dict):
                # data 嵌套结构: {"success": true, "data": {"city": "成都市", ...}}
                inner = weather_entry.get("data", weather_entry)
                prev_city = inner.get("city", "")
                if prev_city:
                    result["city"] = prev_city
                    logger.info(
                        f"[slot_infer] weather: city 优先级2(黑板复用) → '{prev_city}'"
                    )
                    city = prev_city

        # 优先级3: vehicle_state location 坐标兜底
        if not city and not result.get("location"):
            loc = ctx.vehicle.location
            if loc:
                result["location"] = loc
                logger.info(
                    f"[slot_infer] weather: city 优先级3(location兜底) → '{loc}'"
                )

        return result

    # ═══════════════════════════════════════════════════════════
    # pre_validate — 按 intent 分发（纯校验，不含推断）
    # ═══════════════════════════════════════════════════════════

    def pre_validate(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """
        LLM 输出后、调 tool 前的纯校验。

        注意：别名解析、origin补全、默认值等推断逻辑已迁至 infer_slots，
        pre_validate 只负责必填检查 + 格式校验 + 安全检查。
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
        """search_poi: keyword 必填 + location 兜底补全"""
        keyword = slots.get("keyword", "")
        if not keyword:
            return HarnessResult(
                valid=False,
                slots=slots,
                need_clarify=True,
                clarify_message="请问您想搜索什么？",
                block_reason="缺少 keyword",
            )

        # location 兜底补全（infer_slots 已尝试，这里做最后兜底）
        if not slots.get("location"):
            loc = ctx.vehicle.location
            if loc:
                slots = {**slots, "location": loc}
            else:
                return HarnessResult(
                    valid=False,
                    slots=slots,
                    fallback=True,
                    block_reason="vehicle_state 无 location",
                )

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
        """navigate: destination 必填 + 别名兜底解析 + origin 兜底补全 + 安全检查

        推断逻辑主要在 infer_slots，这里做兜底：
        - 别名如果还在（未经 infer_slots），尝试从 ctx 解析
        - origin 如果还缺，尝试从 ctx 补全
        - 解析/补全失败才报错
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

        # ── 2. 别名兜底解析（infer_slots 已尝试，这里做最后兜底）──
        if destination in self._ALIAS_HOME:
            user = ctx.get_user()
            home = user.get("home_address", "")
            if home:
                slots = {**slots, "destination": home}
            else:
                return HarnessResult(
                    valid=False,
                    slots=slots,
                    need_clarify=True,
                    clarify_message="您还没有设置家的地址，请先在设置中添加",
                    block_reason=f"别名'{destination}'解析失败：L3 无 home_address",
                )
        elif destination in self._ALIAS_COMPANY:
            user = ctx.get_user()
            company = user.get("company_address", "")
            if company:
                slots = {**slots, "destination": company}
            else:
                return HarnessResult(
                    valid=False,
                    slots=slots,
                    need_clarify=True,
                    clarify_message="您还没有设置公司地址，请先在设置中添加",
                    block_reason=f"别名'{destination}'解析失败：L3 无 company_address",
                )
        elif destination in self._ALIAS_LAST:
            last_dest = ctx.session.get("last_destination", "")
            if last_dest:
                slots = {**slots, "destination": last_dest}
            else:
                return HarnessResult(
                    valid=False,
                    slots=slots,
                    need_clarify=True,
                    clarify_message="本次行程没有导航记录",
                    block_reason=f"别名'{destination}'解析失败：L2 无 last_destination",
                )
        elif destination in self._ORDINALS:
            resolved = self._resolve_ordinal(destination, ctx.dialogue)
            if resolved:
                slots = {**slots, "destination": resolved}
            else:
                return HarnessResult(
                    valid=False,
                    slots=slots,
                    need_clarify=True,
                    clarify_message="没有找到之前的搜索结果，请告诉我具体目的地",
                    block_reason=f"序号指代'{destination}'解析失败：L1 黑板无 entity.poi",
                )

        # ── 3. origin 兜底补全 ──
        if not slots.get("origin"):
            loc = ctx.vehicle.location
            if loc:
                slots = {**slots, "origin": loc}
            else:
                return HarnessResult(
                    valid=False,
                    slots=slots,
                    fallback=True,
                    block_reason="vehicle_state 无 location，无法补全 origin",
                )

        # ── 4. 安全检查：高速行驶中改目的地 ──
        if ctx.vehicle.speed > 100:
            return HarnessResult(
                valid=True,
                slots=slots,
                need_confirm=True,
                confirm_message=f"当前车速{int(ctx.vehicle.speed)}km/h，确定要导航到{slots['destination']}吗？",
            )

        return HarnessResult(valid=True, slots=slots)

    # ── map_query 校验 ──

    def _validate_map_query(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """map_query: location 兜底补全"""
        # location 兜底补全（infer_slots 已尝试，这里做最后兜底）
        if not slots.get("location"):
            loc = ctx.vehicle.location
            if loc:
                slots = {**slots, "location": loc}
            else:
                return HarnessResult(
                    valid=False,
                    slots=slots,
                    fallback=True,
                    block_reason="vehicle_state 无 location",
                )

        return HarnessResult(valid=True, slots=slots)

    # ── weather 校验 ──

    def _validate_weather(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """weather: 基本通过（date/location 已在 infer_slots 补全）"""
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
                valid=False,
                slots={},
                fallback=True,
                block_reason=f"API 失败: {error}",
            )

        data = tool_result.get("data", {})

        # ── 2. search_poi 空结果 ──
        if "results" in data:
            count = data.get("count", 0)
            if count == 0:
                return HarnessResult(
                    valid=True,
                    slots={},
                    block_reason="搜索无结果",
                )

        # ── 3. navigate 距离异常 ──
        distance = data.get("distance")
        if distance is not None and distance > 5000:
            return HarnessResult(
                valid=True,
                slots={},
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
            return (
                f"找到一家{r['name']}，距离{dist_str}，地址是{r.get('address', '')}。"
            )
        else:
            items = []
            for i, r in enumerate(top, 1):
                dist = r.get("distance", 0)
                dist_str = (
                    f"{dist}米" if dist < 1000 else f"{round(dist / 1000, 1)}公里"
                )
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
                return (
                    f"到{target}的路上，{roads}路段有拥堵，预计需要{duration_min}分钟。"
                )
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
                logger.info(
                    f"[序号指代] '{ordinal}' → entity.poi[{idx}] = '{resolved}'"
                )
            return resolved

        return ""
