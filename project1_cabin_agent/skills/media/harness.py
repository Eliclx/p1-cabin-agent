"""
project1_cabin_agent/skills/media/harness.py
Media Skill Harness — 确定性校验+补全+格式化

原则：不信任 LLM 的 action 判断，不信任工具的 voice_reply。
"""
from project1_cabin_agent.harness.base import BaseHarness, ContextDep, HarnessResult
from project1_cabin_agent.harness.context import AgentContext
from shared.utils.logger import logger


class MediaHarness(BaseHarness):
    """媒体域 harness。依赖 VEHICLE（当前音量状态）。"""

    CONTEXT_DEPS = ContextDep.VEHICLE

    _VALID_ACTIONS = {"play", "pause", "next", "previous", "search",
                      "volume_up", "volume_down", "set_volume"}
    _VOLUME_LO, _VOLUME_HI = 0, 100
    _VOLUME_STEP = 10

    # ── pre_validate: LLM 输出后、调工具前 ─────────────────────────

    def pre_validate(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """
        Validate and normalize the incoming media action slots before tool invocation.
        
        Parameters:
            slots (dict): Extracted action slots; may be mutated and returned with normalized values (e.g., clamped volume).
            ctx (AgentContext): Agent context (unused for validation but provided for consistency).
        
        Returns:
            HarnessResult: Validation outcome. If valid, returns with possibly-updated `slots`.
                - If `action` is missing: `valid=False`, `need_clarify=True`, `clarify_message="请问您想怎么操作音乐？"`, `block_reason="missing action"`.
                - If `action` is not one of the allowed media actions: `valid=False`, `fallback=True`, `block_reason="illegal action: {action}"`.
                - If `action == "search"` and `query` is missing: `valid=False`, `need_clarify=True`, `clarify_message="请问您想听什么？"`, `block_reason="search 缺 query"`.
                - If `action == "set_volume"` and `volume` is missing: `valid=False`, `need_clarify=True`, `clarify_message="请问音量调到多少？"`, `block_reason="set_volume 缺 volume"`.
                - If `action == "set_volume"` and `volume` is outside [0, 100]: volume is clamped into the range and returned in `slots`.
        """
        action = slots.get("action", "")

        # 1. action 必填
        if not action:
            logger.info("[media-harness] pre_validate: missing action → clarify")
            return HarnessResult(
                valid=False, slots=slots,
                need_clarify=True,
                clarify_message="请问您想怎么操作音乐？",
                block_reason="missing action",
            )

        # 2. action 合法性
        if action not in self._VALID_ACTIONS:
            logger.warning(f"[media-harness] pre_validate: illegal action={action} → fallback")
            return HarnessResult(
                valid=False, slots=slots,
                fallback=True,
                block_reason=f"illegal action: {action}",
            )

        # 3. search 需要 query
        if action == "search" and not slots.get("query"):
            logger.info("[media-harness] pre_validate: search missing query → clarify")
            return HarnessResult(
                valid=False, slots=slots,
                need_clarify=True,
                clarify_message="请问您想听什么？",
                block_reason="search 缺 query",
            )

        # 4. set_volume 需要 volume 且在范围内
        if action == "set_volume":
            vol = slots.get("volume")
            if vol is None:
                return HarnessResult(
                    valid=False, slots=slots,
                    need_clarify=True,
                    clarify_message="请问音量调到多少？",
                    block_reason="set_volume 缺 volume",
                )
            if vol < self._VOLUME_LO or vol > self._VOLUME_HI:
                clamped = max(self._VOLUME_LO, min(self._VOLUME_HI, vol))
                logger.info(f"[media-harness] pre_validate: volume {vol} clamped → {clamped}")
                slots = {**slots, "volume": clamped}

        return HarnessResult(valid=True, slots=slots)

    # ── post_validate: 工具返回后校验 ───────────────────────────────

    def post_validate(self, tool_result: dict, ctx: AgentContext) -> HarnessResult:
        """
        Validate a tool's execution result and normalize any returned volume.
        
        Parameters:
            tool_result (dict): Tool response expected to include a "status" key and optionally a "volume" key. If "status" is not "success", the function marks the result as failing. If "volume" is present and not `Ellipsis`, it will be clamped into the harness's valid range.
        
        Returns:
            HarnessResult: If the tool status is not "success", returns `valid=False`, `fallback=True`, and `block_reason` set to the tool's status. Otherwise returns `valid=True` after ensuring any returned volume is within the allowed range.
        """
        if not tool_result.get("status") == "success":
            logger.warning(f"[media-harness] post_validate: tool failed → fallback")
            return HarnessResult(
                valid=False, fallback=True,
                block_reason=f"tool returned {tool_result.get('status')}",
            )

        # 校验返回的 volume 在合法范围
        result_volume = tool_result.get("volume")
        if result_volume is not None and result_volume is not Ellipsis:
            lo, hi = self._VOLUME_LO, self._VOLUME_HI
            if result_volume < lo or result_volume > hi:
                logger.warning(f"[media-harness] post_validate: volume {result_volume} OOB → clamp")
                tool_result["volume"] = max(lo, min(hi, result_volume))

        return HarnessResult(valid=True)

    # ── format_response: 确定性格式化，不信任工具的 voice_reply ─────

    def format_response(self, tool_result: dict) -> str:
        """
        Produce a deterministic user-facing message describing the media action result.
        
        This uses the `action` key of `tool_result` to select a fixed, localized response and inserts `query` or `volume` when applicable. Supported actions: "play", "pause", "next", "previous", "search", "volume_up", "volume_down", "set_volume". Unknown actions produce a generic acknowledgement.
        
        Parameters:
            tool_result (dict): Tool output expected to contain:
                - action (str): the media action performed.
                - volume (int | None): current or set volume, used for "set_volume" responses.
                - query (str): search query or track name, used for "search" responses.
        
        Returns:
            str: A localized confirmation message appropriate for the action (e.g., "好的，开始播放音乐", "好的，音量调到{volume}").
        """
        action = tool_result.get("action", "")
        volume = tool_result.get("volume")
        query = tool_result.get("query", "")

        return {
            "play": "好的，开始播放音乐",
            "pause": "好的，已暂停音乐",
            "next": "好的，已切换到下一首",
            "previous": "好的，已切换到上一首",
            "search": f"好的，正在播放{query}" if query else "好的，开始播放",
            "volume_up": f"好的，音量已调高",
            "volume_down": f"好的，音量已调低",
            "set_volume": f"好的，音量调到{volume}" if volume is not None else "好的，已调节音量",
        }.get(action, "好的")
