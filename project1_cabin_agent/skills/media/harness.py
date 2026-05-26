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

    _VALID_ACTIONS = {
        "play",
        "pause",
        "next",
        "previous",
        "search",
        "volume_up",
        "volume_down",
        "set_volume",
    }
    _VOLUME_LO, _VOLUME_HI = 0, 100
    _VOLUME_STEP = 10

    # ── infer_slots: 基于上下文的语义槽位推断 ──────────────────────

    def infer_slots(self, slots: dict, ctx: AgentContext, user_input: str) -> dict:
        """媒体域语义推断：基于 vehicle_state 和用户语义词补全音量。

        职责（只补缺，不校验，不覆盖已有值）：
        - "大声"/"响" → volume = 当前 + 10
        - "小声"/"安静" → volume = 当前 - 10
        """
        result = {**slots}
        current_vol = ctx.vehicle.volume

        if not result.get("volume"):
            if any(w in user_input for w in ("大声", "声音大", "响")):
                result["action"] = result.get("action", "set_volume")
                result["volume"] = min(100, current_vol + 10)
                logger.info(f"[slot_infer] media: '大声' → volume={result['volume']}")
            elif any(w in user_input for w in ("小声", "声音小", "安静")):
                result["action"] = result.get("action", "set_volume")
                result["volume"] = max(0, current_vol - 10)
                logger.info(f"[slot_infer] media: '小声' → volume={result['volume']}")

        return result

    # ── pre_validate: LLM 输出后、调工具前 ─────────────────────────

    def pre_validate(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        action = slots.get("action", "")

        # 1. action 必填
        if not action:
            logger.info("[media-harness] pre_validate: missing action → clarify")
            return HarnessResult(
                valid=False,
                slots=slots,
                need_clarify=True,
                clarify_message="请问您想怎么操作音乐？",
                block_reason="missing action",
            )

        # 2. action 合法性
        if action not in self._VALID_ACTIONS:
            logger.warning(
                f"[media-harness] pre_validate: illegal action={action} → fallback"
            )
            return HarnessResult(
                valid=False,
                slots=slots,
                fallback=True,
                block_reason=f"illegal action: {action}",
            )

        # 3. search 需要 query
        if action == "search" and not slots.get("query"):
            logger.info("[media-harness] pre_validate: search missing query → clarify")
            return HarnessResult(
                valid=False,
                slots=slots,
                need_clarify=True,
                clarify_message="请问您想听什么？",
                block_reason="search 缺 query",
            )

        # 4. set_volume 需要 volume 且在范围内
        if action == "set_volume":
            vol = slots.get("volume")
            if vol is None:
                return HarnessResult(
                    valid=False,
                    slots=slots,
                    need_clarify=True,
                    clarify_message="请问音量调到多少？",
                    block_reason="set_volume 缺 volume",
                )
            if vol < self._VOLUME_LO or vol > self._VOLUME_HI:
                clamped = max(self._VOLUME_LO, min(self._VOLUME_HI, vol))
                logger.info(
                    f"[media-harness] pre_validate: volume {vol} clamped → {clamped}"
                )
                slots = {**slots, "volume": clamped}

        return HarnessResult(valid=True, slots=slots)

    # ── post_validate: 工具返回后校验 ───────────────────────────────

    def post_validate(self, tool_result: dict, ctx: AgentContext) -> HarnessResult:
        if not tool_result.get("status") == "success":
            logger.warning("[media-harness] post_validate: tool failed → fallback")
            return HarnessResult(
                valid=False,
                fallback=True,
                block_reason=f"tool returned {tool_result.get('status')}",
            )

        # 校验返回的 volume 在合法范围
        result_volume = tool_result.get("volume")
        if result_volume is not None and result_volume is not Ellipsis:
            lo, hi = self._VOLUME_LO, self._VOLUME_HI
            if result_volume < lo or result_volume > hi:
                logger.warning(
                    f"[media-harness] post_validate: volume {result_volume} OOB → clamp"
                )
                tool_result["volume"] = max(lo, min(hi, result_volume))

        return HarnessResult(valid=True)

    # ── format_response: 确定性格式化，不信任工具的 voice_reply ─────

    def format_response(self, tool_result: dict) -> str:
        action = tool_result.get("action", "")
        volume = tool_result.get("volume")
        query = tool_result.get("query", "")

        return {
            "play": "好的，开始播放音乐",
            "pause": "好的，已暂停音乐",
            "next": "好的，已切换到下一首",
            "previous": "好的，已切换到上一首",
            "search": f"好的，正在播放{query}" if query else "好的，开始播放",
            "volume_up": "好的，音量已调高",
            "volume_down": "好的，音量已调低",
            "set_volume": f"好的，音量调到{volume}"
            if volume is not None
            else "好的，已调节音量",
        }.get(action, "好的")
