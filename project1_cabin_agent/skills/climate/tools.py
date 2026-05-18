"""
project1_cabin_agent/skills/climate/tools.py
Climate Skill 工具层 — 纯 mock（无外部 API）
"""
from project1_cabin_agent.vehicle_state import vehicle_state


def _set_ac_state(on=None, temp=None, mode=None, fan_level=None):
    if on is not None:
        vehicle_state.ac_on = on
    if temp is not None:
        vehicle_state.ac_temp = temp
    if mode is not None:
        vehicle_state.ac_mode = mode
    if fan_level is not None:
        vehicle_state.ac_fan_level = fan_level


def _set_window_state(target, percent):
    if target == "window":
        vehicle_state.window_percent = percent
    elif target == "sunroof":
        vehicle_state.sunroof_percent = percent


def _set_seat_state(heat_level=None, ventilate=None):
    if heat_level is not None:
        vehicle_state.seat_heat_level = heat_level
    if ventilate is not None:
        vehicle_state.seat_ventilate = ventilate


def _set_light_state(on=None, brightness=None):
    if on is not None:
        vehicle_state.light_on = on
    if brightness is not None:
        vehicle_state.light_brightness = brightness


def ac_control(action: str, temperature: float = None, mode: str = None, fan_level: int = None) -> dict:
    """空调控制。action: on|off|adjust"""
    if action == "on":
        _set_ac_state(on=True, temp=temperature, mode=mode, fan_level=fan_level)
        t = temperature or vehicle_state.ac_temp
        return {"status": "success", "intent": "ac_control", "action": "on",
                "temperature": t}
    elif action == "off":
        _set_ac_state(on=False)
        return {"status": "success", "intent": "ac_control", "action": "off"}
    elif action == "adjust":
        _set_ac_state(temp=temperature, mode=mode, fan_level=fan_level)
        return {"status": "success", "intent": "ac_control", "action": "adjust",
                "temperature": temperature, "mode": mode, "fan_level": fan_level}
    return {"status": "success", "intent": "ac_control"}


def window_control(target: str, action: str, percent: int = None) -> dict:
    """车窗/天窗/车门控制。高风险。"""
    names = {"window": "车窗", "sunroof": "天窗", "door": "车门"}
    name = names.get(target, target)

    if target == "door":
        if action == "open":
            return {"status": "need_confirm", "intent": "window_control",
                    "target": target, "action": action}
        return {"status": "success", "intent": "window_control",
                "target": target, "action": action, "voice_reply": f"好的，已关闭{name}"}

    if action == "open":
        p = percent if percent is not None else 100
        return {"status": "need_confirm", "intent": "window_control",
                "target": target, "action": "open", "percent": p}
    elif action == "close":
        _set_window_state(target, 0)
        return {"status": "success", "intent": "window_control",
                "target": target, "action": "close"}
    elif action == "adjust":
        p = percent if percent is not None else 50
        _set_window_state(target, p)
        return {"status": "success", "intent": "window_control",
                "target": target, "action": "adjust", "percent": p}
    return {"status": "success", "intent": "window_control"}


def light_control(action: str, target: str = None, brightness: int = None) -> dict:
    """车内灯光控制。"""
    if action == "on":
        _set_light_state(on=True, brightness=brightness)
        return {"status": "success", "intent": "light_control", "action": "on"}
    elif action == "off":
        _set_light_state(on=False)
        return {"status": "success", "intent": "light_control", "action": "off"}
    elif action == "adjust":
        b = brightness if brightness is not None else 50
        _set_light_state(brightness=b)
        return {"status": "success", "intent": "light_control", "action": "adjust",
                "brightness": b}
    return {"status": "success", "intent": "light_control"}


def seat_control(action: str, heat_level: int = None) -> dict:
    """座椅加热/通风控制。"""
    if action == "heat_on":
        lv = heat_level or 2
        _set_seat_state(heat_level=lv)
        return {"status": "success", "intent": "seat_control", "action": "heat_on",
                "heat_level": lv}
    elif action == "heat_off":
        _set_seat_state(heat_level=0)
        return {"status": "success", "intent": "seat_control", "action": "heat_off"}
    elif action == "ventilate_on":
        _set_seat_state(ventilate=True)
        return {"status": "success", "intent": "seat_control", "action": "ventilate_on"}
    elif action == "ventilate_off":
        _set_seat_state(ventilate=False)
        return {"status": "success", "intent": "seat_control", "action": "ventilate_off"}
    return {"status": "success", "intent": "seat_control"}
