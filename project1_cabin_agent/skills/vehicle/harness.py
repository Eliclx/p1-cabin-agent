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
        """
        Route and perform intent-specific pre-validation for vehicle-related requests.
        
        Parameters:
            slots (dict): Extracted intent/slot mapping; expects '_intent' to determine validation route.
            ctx (AgentContext): Execution context for the agent (not used for routing).
        
        Returns:
            HarnessResult: Validation result for the detected intent. If `_intent` is missing or unrecognized, returns a result with `valid=False`, `fallback=True`, and `block_reason='unknown intent in vehicle domain'`.
        """
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
        """
        Validate the `items` slot for a vehicle status query.
        
        Checks the optional `items` key in `slots`. If `items` is missing or empty, the function treats this as a request for all status and returns a valid result. If `items` is not one of the allowed query items, returns an invalid result with `fallback=True` and a `block_reason` describing the illegal item; otherwise returns a valid result preserving `slots`.
        
        Parameters:
            slots (dict): Extracted intent slots; may contain the optional `"items"` key.
        
        Returns:
            HarnessResult: `valid` when `items` is missing or allowed; `valid=False` with `fallback=True` and `block_reason` when `items` is not allowed.
        """
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
        """
        Validate the requested scene name in `slots` for activating a vehicle scene.
        
        Parameters:
            slots (dict): Slot dictionary expected to contain the key `"scene_name"` with the desired scene.
        
        Returns:
            HarnessResult: If `scene_name` is missing, returns a result with `valid=False`, `need_clarify=True`, a `clarify_message` asking which mode to switch to, `block_reason="missing scene_name"`, and the original `slots`. If `scene_name` is present but not one of the allowed scenes, returns `valid=False`, `fallback=True`, and `block_reason="illegal scene: <scene>"`. If `scene_name` is valid, returns `valid=True` and includes the original `slots`.
        """
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
        """
        Validate a tool's execution result and produce a corresponding HarnessResult.
        
        Parameters:
            tool_result (dict): Tool execution output; expected to contain a "status" key (e.g., "success").
            ctx (AgentContext): Agent context (unused by this method).
        
        Returns:
            HarnessResult: `true` if `tool_result["status"]` equals `"success"`, `false` otherwise. If not successful, the returned result has `fallback=True` and `block_reason` set to the tool's status.
        """
        if not tool_result.get("status") == "success":
            logger.warning(f"[vehicle-harness] post_validate: tool failed → fallback")
            return HarnessResult(valid=False, fallback=True,
                                 block_reason=f"tool status: {tool_result.get('status')}")
        return HarnessResult(valid=True)

    # ── format_response ────────────────────────────────────────────

    def format_response(self, tool_result: dict) -> str:
        """
        Format a spoken response based on the tool result.
        
        Parameters:
            tool_result (dict): Tool execution result; expected keys:
                - "scene": optional scene name to confirm activation.
                - "voice_reply": optional fallback reply text.
        
        Returns:
            str: If "scene" is present, a confirmation string "好的，已激活{scene}模式"; otherwise the value of "voice_reply" or "好的" if absent.
        """
        scene = tool_result.get("scene", "")
        if scene:
            return f"好的，已激活{scene}模式"
        return tool_result.get("voice_reply", "好的")
