"""
project1_cabin_agent/skills/climate/harness.py
Climate Skill Harness — 确定性校验+高风控+格式化
"""
from project1_cabin_agent.harness.base import BaseHarness, ContextDep, HarnessResult
from project1_cabin_agent.harness.context import AgentContext
from shared.utils.logger import logger


class ClimateHarness(BaseHarness):
    """气候域 harness。依赖 VEHICLE（温度/车窗/车速）。"""

    CONTEXT_DEPS = ContextDep.VEHICLE

    # ── 常量 ──
    _TEMP_LO, _TEMP_HI = 16, 32
    _FAN_LO, _FAN_HI = 1, 5

    def pre_validate(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """
        Dispatches the climate `_intent` in `slots` to the appropriate validator and returns its validation result.
        
        If `slots` does not contain `_intent`, returns a `HarnessResult` with `valid=False`, `fallback=True`, and `block_reason="no _intent in climate"`. If `_intent` is not one of the supported intents (`"ac_control"`, `"window_control"`, `"light_control"`, `"seat_control"`), returns a `HarnessResult` with `valid=False`, `fallback=True`, and `block_reason` indicating the unknown intent.
        
        Parameters:
            slots (dict): Parsed slot values for the climate domain. Must contain `_intent` to select a validator.
            ctx (AgentContext): Execution context (provides vehicle state and other dependencies used by validators).
        
        Returns:
            HarnessResult: The validation result produced by the selected intent validator, or a failure `HarnessResult` for missing/unknown intents.
        """
        intent = slots.get("_intent", "")
        if not intent:
            return HarnessResult(valid=False, fallback=True,
                                 block_reason="no _intent in climate")

        handlers = {
            "ac_control": self._validate_ac,
            "window_control": self._validate_window,
            "light_control": self._validate_light,
            "seat_control": self._validate_seat,
        }
        handler = handlers.get(intent)
        if handler:
            return handler(slots, ctx)
        return HarnessResult(valid=False, fallback=True,
                             block_reason=f"unknown climate intent: {intent}")

    # ── ac_control ────────────────────────────────────────────────

    def _validate_ac(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """
        Validate and normalize slots for air-conditioning (AC) control intents.
        
        Checks that an `action` is present and one of "on", "off", or "adjust"; if `action` is "adjust", requires at least one target among `temperature`, `mode`, or `fan_level`. If `temperature` is provided, it is clamped to the harness temperature bounds (16–32) and the returned `slots` reflect the clamped value. If `fan_level` is provided, it is clamped to the harness fan bounds (1–5) and the returned `slots` reflect the clamped value. Produces `HarnessResult` that indicates whether clarification, fallback, or a valid normalized slot set is required.
        
        Parameters:
        	slots (dict): Incoming intent slots; may contain keys like `action`, `temperature`, `mode`, and `fan_level`. The returned `HarnessResult.slots` may contain clamped `temperature` or `fan_level`.
        	ctx (AgentContext): Execution context (vehicle and environment information); not used for AC-specific safety checks but provided for consistency with harness signature.
        
        Returns:
        	HarnessResult: A result describing validation outcome. Possible outcomes:
        	- Clarification required when `action` is missing or `adjust` has no targets.
        	- Fallback when `action` is not one of the allowed values.
        	- Valid with `slots` (possibly updated with clamped `temperature`/`fan_level`) when inputs pass validation.
        """
        action = slots.get("action", "")
        if not action:
            logger.info("[climate-harness] ac: missing action → clarify")
            return HarnessResult(valid=False, slots=slots, need_clarify=True,
                clarify_message="请问您要怎么调节空调？", block_reason="missing action")
        if action not in ("on", "off", "adjust"):
            logger.warning(f"[climate-harness] ac: illegal action={action} → fallback")
            return HarnessResult(valid=False, slots=slots, fallback=True,
                block_reason=f"illegal action: {action}")

        # adjust 必须有调节目标（温度/模式/风速至少一个）
        if action == "adjust":
            has_target = any(slots.get(k) is not None for k in ("temperature", "mode", "fan_level"))
            if not has_target:
                logger.info("[climate-harness] ac: adjust without target → clarify")
                return HarnessResult(valid=False, slots=slots, need_clarify=True,
                    clarify_message="请问要调到多少度？", block_reason="adjust without target")

        # 温度范围 clamp
        temp = slots.get("temperature")
        if temp is not None:
            lo, hi = self._TEMP_LO, self._TEMP_HI
            if temp < lo or temp > hi:
                clamped = max(lo, min(hi, temp))
                logger.info(f"[climate-harness] ac: temp {temp} clamped → {clamped}")
                slots = {**slots, "temperature": clamped}

        # 风速范围 clamp
        fan = slots.get("fan_level")
        if fan is not None:
            lo, hi = self._FAN_LO, self._FAN_HI
            if fan < lo or fan > hi:
                clamped = max(lo, min(hi, fan))
                logger.info(f"[climate-harness] ac: fan {fan} clamped → {clamped}")
                slots = {**slots, "fan_level": clamped}

        return HarnessResult(valid=True, slots=slots)

    # ── window_control ────────────────────────────────────────────

    def _validate_window(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """
        Validate window/sunroof/door control slots and enforce safety and confirmation rules.
        
        Parameters:
        	slots (dict): Parsed intent slots expected to contain at least `action` and `target`. May include `percent`.
        	ctx (AgentContext): Execution context used to inspect vehicle state (e.g., `ctx.vehicle.speed`) for safety checks.
        
        Returns:
        	HarnessResult: Validation outcome:
        	- `valid=False, need_clarify=True` with `clarify_message` when `action` or `target` is missing.
        	- `valid=False, fallback=True` with `block_reason` when attempting to open a door while the vehicle is moving (blocks unsafe action).
        	- `valid=True, need_confirm=True` with `confirm_message` when opening or adjusting a window/sunroof (uses `percent` default 100 for open).
        	- `valid=True` for other allowed actions.
        """
        action = slots.get("action", "")
        target = slots.get("target", "")

        if not action or not target:
            logger.info("[climate-harness] window: missing action/target → clarify")
            return HarnessResult(valid=False, slots=slots, need_clarify=True,
                clarify_message="请问您要操作车窗、天窗还是车门？",
                block_reason="missing target/action")

        # 行车中开门 → 拦截
        if target == "door" and action == "open" and ctx.vehicle.speed > 0:
            logger.warning(f"[climate-harness] window: door open at {ctx.vehicle.speed}km/h → blocked")
            return HarnessResult(valid=False, slots=slots, fallback=True,
                block_reason=f"行驶中({ctx.vehicle.speed}km/h)禁止开门")

        # open 动作需要确认（除关窗外）
        if action in ("open", "adjust") and target in ("window", "sunroof"):
            pct = slots.get("percent", 100 if action == "open" else None)
            target_name = {"window": "车窗", "sunroof": "天窗"}.get(target, target)
            return HarnessResult(valid=True, slots=slots, need_confirm=True,
                confirm_message=f"确认要打开{target_name}吗？")

        return HarnessResult(valid=True, slots=slots)

    # ── light_control ─────────────────────────────────────────────

    def _validate_light(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """
        Validate slots for light control actions and produce a HarnessResult describing required clarification, fallback, or success.
        
        Parameters:
            slots (dict): Slot dictionary expected to contain an "action" key with one of "on", "off", or "adjust".
            ctx (AgentContext): Agent context (not used by this validator but provided for consistency).
        
        Returns:
            HarnessResult: 
                - If "action" is missing: `valid=False`, `need_clarify=True`, `clarify_message="请问您要怎么调节灯光？"`, and `block_reason="missing action"`.
                - If "action" is not one of "on", "off", "adjust": `valid=False`, `fallback=True`, and `block_reason="illegal light action: {action}"`.
                - Otherwise: `valid=True` with the (possibly normalized) `slots`.
        """
        action = slots.get("action", "")
        if not action:
            return HarnessResult(valid=False, slots=slots, need_clarify=True,
                clarify_message="请问您要怎么调节灯光？", block_reason="missing action")
        if action not in ("on", "off", "adjust"):
            return HarnessResult(valid=False, slots=slots, fallback=True,
                block_reason=f"illegal light action: {action}")
        return HarnessResult(valid=True, slots=slots)

    # ── seat_control ──────────────────────────────────────────────

    def _validate_seat(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        """
        Validate and normalize seat-control slots for seat heating and ventilation actions.
        
        Parameters:
            slots (dict): Incoming slot values; expected keys include "action" and optional "heat_level".
            ctx (AgentContext): Agent context (used for contextual checks; not read by this validator).
        
        Returns:
            HarnessResult: Validation result. On success (`valid=True`) returns possibly updated `slots` with `heat_level` clamped to the range 1–3. On failure returns `valid=False` and either `need_clarify=True` when action is missing (with `clarify_message`) or `fallback=True` when the action is not one of "heat_on", "heat_off", "ventilate_on", "ventilate_off".
        """
        action = slots.get("action", "")
        if not action:
            return HarnessResult(valid=False, slots=slots, need_clarify=True,
                clarify_message="请问您要怎么调节座椅？", block_reason="missing action")
        if action not in ("heat_on", "heat_off", "ventilate_on", "ventilate_off"):
            return HarnessResult(valid=False, slots=slots, fallback=True,
                block_reason=f"illegal seat action: {action}")

        # heat_level 范围 clamp
        level = slots.get("heat_level")
        if level is not None and (level < 1 or level > 3):
            clamped = max(1, min(3, level))
            logger.info(f"[climate-harness] seat: heat_level {level} clamped → {clamped}")
            slots = {**slots, "heat_level": clamped}

        return HarnessResult(valid=True, slots=slots)

    # ── post_validate ─────────────────────────────────────────────

    def post_validate(self, tool_result: dict, ctx: AgentContext) -> HarnessResult:
        """
        Validate the tool execution result and convert it into a HarnessResult indicating success or fallback.
        
        Parameters:
            tool_result (dict): Result returned by the tool; expected to include a `"status"` key.
            ctx (AgentContext): Agent context (unused by this validator).
        
        Returns:
            HarnessResult: `valid=True` when `tool_result["status"]` equals `"success"`. Otherwise
            returns `valid=False` and `fallback=True` with `block_reason` set to `tool status: {status}`.
        """
        if not tool_result.get("status") == "success":
            logger.warning(f"[climate-harness] post_validate: tool failed → fallback")
            return HarnessResult(valid=False, fallback=True,
                block_reason=f"tool status: {tool_result.get('status')}")
        return HarnessResult(valid=True)

    # ── format_response ───────────────────────────────────────────

    def format_response(self, tool_result: dict) -> str:
        """
        Format a user-facing Chinese acknowledgement or confirmation based on the tool_result's intent and related fields.
        
        The function selects an intent-specific formatter to produce a natural-language response for climate-related actions. Expected keys in `tool_result` include:
        - `intent` (str): one of "ac_control", "window_control", "light_control", "seat_control".
        - `action` (str): the action performed (used by formatters).
        - Other intent-specific fields that formatters may read, for example:
          - AC: `temperature`, `mode`, `fan_level`
          - Window: `target`, `percent`
          - Light: `brightness`
          - Seat: `heat_level`
        
        Parameters:
            tool_result (dict): Result dictionary produced by the tool containing intent and related fields.
        
        Returns:
            str: A Chinese acknowledgement or confirmation message (e.g., "好的，已打开空调"), or "好的" for unknown intents.
        """
        intent = tool_result.get("intent", "")
        action = tool_result.get("action", "")

        if intent == "ac_control":
            return self._format_ac(tool_result)
        elif intent == "window_control":
            return self._format_window(tool_result)
        elif intent == "light_control":
            return self._format_light(tool_result)
        elif intent == "seat_control":
            return self._format_seat(tool_result)
        return "好的"

    def _format_ac(self, r: dict) -> str:
        """
        Generate a user-facing Chinese acknowledgement for air-conditioning actions based on the tool result.
        
        Parameters:
            r (dict): Tool result containing at least an "action" key and optional fields:
                - "temperature": numeric temperature to report.
                - "mode": mode name to report.
                - "fan_level": fan level to report.
        
        Returns:
            str: A Chinese response:
                - For action "on": "好的，已打开空调" and append "，{temperature}度" if "temperature" is present.
                - For action "off": "好的，已关闭空调".
                - For action "adjust": combine present segments among "温度调到{temperature}度", "模式调为{mode}", "风速调到{fan_level}档" joined by Chinese commas; if none present return "好的，已调整".
                - For other actions: "好的".
        """
        action = r.get("action", "")
        temp = r.get("temperature")
        if action == "on":
            return f"好的，已打开空调" + (f"，{temp}度" if temp else "")
        elif action == "off":
            return "好的，已关闭空调"
        elif action == "adjust":
            parts = []
            if r.get("temperature"): parts.append(f"温度调到{temp}度")
            if r.get("mode"): parts.append(f"模式调为{r['mode']}")
            if r.get("fan_level"): parts.append(f"风速调到{r['fan_level']}档")
            return f"好的，{'，'.join(parts) if parts else '已调整'}"
        return "好的"

    def _format_window(self, r: dict) -> str:
        """
        Format a user-facing acknowledgement message for window, sunroof, or door actions.
        
        Parameters:
            r (dict): Tool result containing action details. Expected keys:
                - "target" (str): one of "window", "sunroof", "door" (used to choose the displayed name; other values are used as-is).
                - "action" (str): action performed; if "close", the message indicates closure.
                - "percent" (int, optional): percentage to set (used when action is not "close"); defaults to 100 when absent.
        
        Returns:
            str: A Chinese acknowledgement message such as "好的，已关闭车门" or "好的，车窗已调到50%".
        """
        target = r.get("target", "")
        action = r.get("action", "")
        names = {"window": "车窗", "sunroof": "天窗", "door": "车门"}
        name = names.get(target, target)
        if action == "close":
            return f"好的，已关闭{name}"
        pct = r.get("percent", 100)
        return f"好的，{name}已调到{pct}%"

    def _format_light(self, r: dict) -> str:
        """
        Format a user-facing acknowledgement message for light control results.
        
        Parameters:
            r (dict): Tool result for light control. Expected keys:
                - "action": one of "on", "off", or "adjust".
                - "brightness" (optional): integer 0–100 used when action is "adjust".
        
        Returns:
            str: A Chinese acknowledgement message reflecting the performed light action (e.g., "好的，已打开车灯", "好的，已关闭车灯", or "好的，灯光亮度调到{b}%"). 
        """
        action = r.get("action", "")
        if action == "on":
            return "好的，已打开车灯"
        elif action == "off":
            return "好的，已关闭车灯"
        elif action == "adjust":
            b = r.get("brightness", 50)
            return f"好的，灯光亮度调到{b}%"
        return "好的"

    def _format_seat(self, r: dict) -> str:
        """
        Format an acknowledgment message for seat control results.
        
        Parameters:
            r (dict): Tool result containing at least an "action" key with values like
                "heat_on", "heat_off", "ventilate_on", or "ventilate_off". May include
                "heat_level" (int) when action is "heat_on".
        
        Returns:
            str: A Chinese acknowledgement string describing the completed seat action;
                 for "heat_on" includes the heat level (default 2), for other known
                 actions returns a corresponding confirmation, otherwise returns "好的".
        """
        action = r.get("action", "")
        if action == "heat_on":
            lv = r.get("heat_level", 2)
            return f"好的，已开启座椅加热{lv}档"
        elif action == "heat_off":
            return "好的，已关闭座椅加热"
        elif action == "ventilate_on":
            return "好的，已开启座椅通风"
        elif action == "ventilate_off":
            return "好的，已关闭座椅通风"
        return "好的"
