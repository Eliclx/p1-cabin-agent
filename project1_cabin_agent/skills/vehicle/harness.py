"""
project1_cabin_agent/skills/vehicle/harness.py
Vehicle Skill Harness — 确定性校验+格式化
"""
from project1_cabin_agent.harness.base import BaseHarness, ContextDep, HarnessResult
from project1_cabin_agent.harness.context import AgentContext
from shared.utils.logger import logger


class VehicleHarness(BaseHarness):
    """车况域 harness。依赖 VEHICLE（车辆状态）。"""

    CONTEXT_DEPS = ContextDep.VEHICLE

    _VALID_ITEMS = {"fuel", "battery", "tire", "mileage", "temperature", "ac_temp", "speed"}
    _VALID_SCENES = {"comfortable_driving", "sleep_mode", "departure_check"}

    # ── pre_validate ───────────────────────────────────────────────

    def pre_validate(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        intent = slots.get("_intent", "")

        if intent == "query_vehicle_status":
            return self._validate_query(slots)
        elif intent == "activate_scene":
            return self._validate_scene(slots)

        # 通用：至少要知道 intent
        return HarnessResult(
            valid=False, fallback=True,
            block_reason="unknown intent in vehicle domain",
        )

    def _validate_query(self, slots: dict) -> HarnessResult:
        items = slots.get("items", "")
        if not items:
            # items 缺了也可以查（返回全部状态）
            return HarnessResult(valid=True, slots=slots)
        if items not in self._VALID_ITEMS:
            logger.warning(f"[vehicle-harness] pre_validate: illegal items={items} → fallback")
            return HarnessResult(valid=False, fallback=True,
                                 block_reason=f"illegal items: {items}")
        return HarnessResult(valid=True, slots=slots)

    def _validate_scene(self, slots: dict) -> HarnessResult:
        scene = slots.get("scene_name", "")
        if not scene:
            logger.info("[vehicle-harness] pre_validate: missing scene_name → clarify")
            return HarnessResult(
                valid=False, slots=slots,
                need_clarify=True,
                clarify_message="请问您想切换到哪个模式？舒适驾驶、休息还是出发前检查？",
                block_reason="missing scene_name",
            )
        if scene not in self._VALID_SCENES:
            logger.warning(f"[vehicle-harness] pre_validate: illegal scene={scene} → fallback")
            return HarnessResult(valid=False, fallback=True,
                                 block_reason=f"illegal scene: {scene}")
        return HarnessResult(valid=True, slots=slots)

    # ── post_validate ──────────────────────────────────────────────

    def post_validate(self, tool_result: dict, ctx: AgentContext) -> HarnessResult:
        if not tool_result.get("status") == "success":
            logger.warning(f"[vehicle-harness] post_validate: tool failed → fallback")
            return HarnessResult(valid=False, fallback=True,
                                 block_reason=f"tool status: {tool_result.get('status')}")
        return HarnessResult(valid=True)

    # ── format_response ────────────────────────────────────────────

    def format_response(self, tool_result: dict) -> str:
        scene = tool_result.get("scene", "")
        if scene:
            return f"好的，已激活{scene}模式"
        return tool_result.get("voice_reply", "好的")
