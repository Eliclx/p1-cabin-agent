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
        """按 intent 分发校验"""
        intent = slots.get("_intent", "")
        if not intent:
            return HarnessResult(valid=False, fallback=True,
                                 block_reason="no _intent in climate")

        handlers = {
            "ac_control": self._validate_ac,
            "window_control": self._validate_window,
            "light_control": self._validate_light,
            "seat_control": self._validate_seat,
            "cabin_query": self._validate_cabin_query,
        }
        handler = handlers.get(intent)
        if handler:
            return handler(slots, ctx)
        return HarnessResult(valid=False, fallback=True,
                             block_reason=f"unknown climate intent: {intent}")

    # ── ac_control ────────────────────────────────────────────────

    def _validate_ac(self, slots: dict, ctx: AgentContext) -> HarnessResult:
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

    # ── cabin_query ──────────────────────────────────────────────

    _VALID_CABIN_ITEMS = {"ac_temp", "cabin_temp", "humidity"}

    def _validate_cabin_query(self, slots: dict, ctx: AgentContext) -> HarnessResult:
        items = slots.get("items", "")
        if not items:
            logger.info("[climate-harness] cabin_query: missing items → fallback")
            return HarnessResult(valid=False, fallback=True,
                                 block_reason="cabin_query missing items")
        if items not in self._VALID_CABIN_ITEMS:
            logger.warning(f"[climate-harness] cabin_query: illegal items={items} → fallback")
            return HarnessResult(valid=False, fallback=True,
                                 block_reason=f"illegal cabin items: {items}")
        return HarnessResult(valid=True, slots=slots)

    # ── post_validate ─────────────────────────────────────────────

    def post_validate(self, tool_result: dict, ctx: AgentContext) -> HarnessResult:
        if not tool_result.get("status") == "success":
            logger.warning(f"[climate-harness] post_validate: tool failed → fallback")
            return HarnessResult(valid=False, fallback=True,
                block_reason=f"tool status: {tool_result.get('status')}")
        return HarnessResult(valid=True)

    # ── format_response ───────────────────────────────────────────

    def format_response(self, tool_result: dict) -> str:
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
        elif intent == "cabin_query":
            return self._format_cabin_query(tool_result)
        return "好的"

    def _format_ac(self, r: dict) -> str:
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
        target = r.get("target", "")
        action = r.get("action", "")
        names = {"window": "车窗", "sunroof": "天窗", "door": "车门"}
        name = names.get(target, target)
        if action == "close":
            return f"好的，已关闭{name}"
        pct = r.get("percent", 100)
        return f"好的，{name}已调到{pct}%"

    def _format_light(self, r: dict) -> str:
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

    def _format_cabin_query(self, r: dict) -> str:
        """格式化座舱查询结果"""
        voice = r.get("voice_reply", "")
        if voice:
            return voice
        items = r.get("items", "")
        value = r.get("value", "")
        return f"好的，{items}当前为{value}"
