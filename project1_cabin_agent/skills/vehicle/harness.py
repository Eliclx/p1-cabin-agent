"""
project1_cabin_agent/skills/vehicle/harness.py
Vehicle Skill Harness — 确定性校验+格式化
"""
from project1_cabin_agent.harness.base import BaseHarness, ContextDep, HarnessResult
from project1_cabin_agent.harness.context import AgentContext
from shared.utils.logger import logger


class VehicleHarness(BaseHarness):
    """车况域 harness。依赖 VEHICLE（车辆状态）。只负责硬车况查询。"""

    CONTEXT_DEPS = ContextDep.VEHICLE

    _VALID_ITEMS = {"fuel", "battery", "tire", "mileage", "speed"}

    # ── pre_validate ───────────────────────────────────────────────

    def pre_validate(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        intent = slots.get("_intent", "")

        if intent == "query_vehicle_status":
            return self._validate_query(slots)

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

    # ── post_validate ──────────────────────────────────────────────

    def post_validate(self, tool_result: dict, ctx: AgentContext) -> HarnessResult:
        if not tool_result.get("status") == "success":
            logger.warning(f"[vehicle-harness] post_validate: tool failed → fallback")
            return HarnessResult(valid=False, fallback=True,
                                 block_reason=f"tool status: {tool_result.get('status')}")
        return HarnessResult(valid=True)

    # ── format_response ────────────────────────────────────────────

    def format_response(self, tool_result: dict) -> str:
        return tool_result.get("voice_reply", "好的")
