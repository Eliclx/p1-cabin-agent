"""
project1_cabin_agent/skills/climate/action_format.py — Climate 域 action 转换

tool_result → CabinAction，跟着 skill 走。
加新 intent（如 seat_massage）只改这个文件，不动引擎。
"""

from __future__ import annotations

from project1_cabin_agent.actions.models import CabinAction


def format_ac_control(tool_result: dict) -> CabinAction | None:
    action = tool_result.get("action", "")
    if action == "on":
        return CabinAction(
            domain="climate",
            intent="ac_control",
            command="ac_on",
            params={"temperature": tool_result.get("temperature", 24)},
        )
    elif action == "off":
        return CabinAction(domain="climate", intent="ac_control", command="ac_off")
    elif action == "adjust":
        params = {
            k: tool_result[k]
            for k in ("temperature", "mode", "fan_level")
            if k in tool_result
        }
        return CabinAction(
            domain="climate", intent="ac_control", command="ac_set", params=params
        )
    return None


def format_window_control(tool_result: dict) -> CabinAction | None:
    action = tool_result.get("action", "")
    target = tool_result.get("target", "all")
    if action == "open":
        return CabinAction(
            domain="climate",
            intent="window_control",
            command="window_open",
            params={"target": target},
        )
    elif action == "close":
        return CabinAction(
            domain="climate",
            intent="window_control",
            command="window_close",
            params={"target": target},
        )
    elif action == "adjust":
        return CabinAction(
            domain="climate",
            intent="window_control",
            command="window_set",
            params={"target": target, "percent": tool_result.get("percent", 100)},
        )
    return None


def format_light_control(tool_result: dict) -> CabinAction | None:
    action = tool_result.get("action", "")
    if action == "on":
        return CabinAction(domain="climate", intent="light_control", command="light_on")
    elif action == "off":
        return CabinAction(
            domain="climate", intent="light_control", command="light_off"
        )
    elif action == "adjust":
        params = {
            k: tool_result[k] for k in ("target", "brightness") if k in tool_result
        }
        return CabinAction(
            domain="climate", intent="light_control", command="light_set", params=params
        )
    return None


def format_seat_control(tool_result: dict) -> CabinAction | None:
    action = tool_result.get("action", "")
    if action == "heat_on":
        return CabinAction(
            domain="climate",
            intent="seat_control",
            command="seat_heat_on",
            params={"heat_level": tool_result.get("heat_level", 1)},
        )
    elif action == "heat_off":
        return CabinAction(
            domain="climate", intent="seat_control", command="seat_heat_off"
        )
    elif action == "ventilate_on":
        return CabinAction(
            domain="climate", intent="seat_control", command="seat_vent_on"
        )
    elif action == "ventilate_off":
        return CabinAction(
            domain="climate", intent="seat_control", command="seat_vent_off"
        )
    return None


# ── 导出：intent → formatter 映射 ──

CLIMATE_ACTION_FORMATTERS = {
    "ac_control": format_ac_control,
    "window_control": format_window_control,
    "light_control": format_light_control,
    "seat_control": format_seat_control,
}
