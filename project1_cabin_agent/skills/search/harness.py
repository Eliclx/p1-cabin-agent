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
        """
        Validate and normalize `slots` for a search request.
        
        Checks that `slots` contains a non-empty `keyword`; if missing, returns an invalid HarnessResult that requests clarification. If `radius` is provided and falls outside the allowed range (1.0 to 50.0), clamps it into that range and returns the updated slots. Otherwise returns a valid HarnessResult with (possibly) normalized slots.
        
        Parameters:
            slots (dict): Input slot map; expected keys:
                - "keyword" (str): required search term.
                - "radius" (float, optional): search radius which will be clamped to [1.0, 50.0] if out of bounds.
            ctx (AgentContext): Agent context (unused by this validator).
        
        Returns:
            HarnessResult: One of:
                - invalid with need_clarify=True and clarify_message="请问您想搜索什么？" when "keyword" is missing.
                - valid with `slots` possibly updated to contain a clamped "radius".
                - valid with original `slots` when no modification is necessary.
        """
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
        """
        Validate the search tool's execution status and map it to a HarnessResult.
        
        Checks whether `tool_result["status"]` equals "success". If the status is not "success", returns a HarnessResult indicating validation failure and requesting a fallback, with the `block_reason` set to the tool's status. If the status is "success", returns a successful HarnessResult. Empty search results are treated as a successful outcome.
        
        Parameters:
            tool_result (dict): Result object produced by the search tool; expected to contain a `"status"` key.
            ctx (AgentContext): Agent context (not used by this validation).
        
        Returns:
            HarnessResult: `valid=False, fallback=True` and `block_reason` describing the tool status when the tool failed; `valid=True` otherwise.
        """
        if not tool_result.get("status") == "success":
            logger.warning(f"[search-harness] post_validate: tool failed → fallback")
            return HarnessResult(valid=False, fallback=True,
                                 block_reason=f"tool status: {tool_result.get('status')}")

        # 空结果不报错，正常返回
        return HarnessResult(valid=True)

    def format_response(self, tool_result: dict) -> str:
        """
        Format a search tool result into a human-readable Chinese response string.
        
        Parameters:
            tool_result (dict): Result returned by the search tool. Expected keys:
                - "results" (list): zero or more result dicts; each result may include "name", "distance", and "rating".
                - "keyword" (str, optional): the search keyword used, used when no results are found.
        
        Returns:
            str: A Chinese message. If no results are present, a prompt indicating nothing was found for the keyword and suggesting expanding the search range.
                 Otherwise, a summary that includes the number of results, the nearest result's name and distance, and the nearest result's rating if available.
        """
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
