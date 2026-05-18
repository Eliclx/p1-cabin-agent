"""
project1_cabin_agent/skills/search/harness.py
Search Skill Harness — 确定性校验+格式化
"""
from project1_cabin_agent.harness.base import BaseHarness, ContextDep, HarnessResult
from project1_cabin_agent.harness.context import AgentContext
from shared.utils.logger import logger


class SearchHarness(BaseHarness):
    """搜索域 harness。依赖 VEHICLE（当前位置）。"""

    CONTEXT_DEPS = ContextDep.VEHICLE

    _RADIUS_LO, _RADIUS_HI = 1.0, 50.0

    def pre_validate(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        keyword = slots.get("keyword", "")

        # 1. keyword 必填
        if not keyword:
            logger.info("[search-harness] pre_validate: missing keyword → clarify")
            return HarnessResult(
                valid=False, slots=slots,
                need_clarify=True,
                clarify_message="请问您想搜索什么？",
                block_reason="missing keyword",
            )

        # 2. radius 范围约束
        radius = slots.get("radius")
        if radius is not None:
            if radius < self._RADIUS_LO or radius > self._RADIUS_HI:
                clamped = max(self._RADIUS_LO, min(self._RADIUS_HI, radius))
                logger.info(f"[search-harness] pre_validate: radius {radius} clamped → {clamped}")
                slots = {**slots, "radius": clamped}

        return HarnessResult(valid=True, slots=slots)

    def post_validate(self, tool_result: dict, ctx: AgentContext) -> HarnessResult:
        if not tool_result.get("status") == "success":
            logger.warning(f"[search-harness] post_validate: tool failed → fallback")
            return HarnessResult(valid=False, fallback=True,
                                 block_reason=f"tool status: {tool_result.get('status')}")

        # 空结果不报错，正常返回
        return HarnessResult(valid=True)

    def format_response(self, tool_result: dict) -> str:
        results = tool_result.get("results", [])
        if not results:
            keyword = tool_result.get("keyword", "")
            return f"附近没有找到{keyword}，试试扩大搜索范围？"

        count = len(results)
        first = results[0]
        dist = first.get("distance", "?")
        name = first.get("name", "?")
        reply = f"找到{count}个结果，最近的是{name}，距您{dist}"

        rating = first.get("rating")
        if rating:
            reply += f"，评分{rating}"
        return reply
