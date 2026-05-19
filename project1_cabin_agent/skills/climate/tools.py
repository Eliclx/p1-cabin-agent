"""
project1_cabin_agent/skills/climate/tools.py
Climate Skill 工具层 — 纯 mock（无外部 API）
"""
from project1_cabin_agent.vehicle_state import vehicle_state


def _set_ac_state(on=None, temp=None, mode=None, fan_level=None):
    """
    Conditionally update the vehicle's AC-related state fields when corresponding arguments are provided.
    
    Parameters:
        on (bool | None): If not None, sets vehicle_state.ac_on to this value.
        temp (float | None): If not None, sets vehicle_state.ac_temp to this temperature.
        mode (str | None): If not None, sets vehicle_state.ac_mode to this mode string.
        fan_level (int | None): If not None, sets vehicle_state.ac_fan_level to this level.
    """
    if on is not None:
        vehicle_state.ac_on = on
    if temp is not None:
        vehicle_state.ac_temp = temp
    if mode is not None:
        vehicle_state.ac_mode = mode
    if fan_level is not None:
        vehicle_state.ac_fan_level = fan_level


def _set_window_state(target, percent):
    """
    Set the open percentage for a window-like vehicle component.
    
    Sets vehicle_state.window_percent when target is "window" and vehicle_state.sunroof_percent when target is "sunroof". Other target values are ignored.
    
    Parameters:
        target (str): One of "window" or "sunroof" indicating which component to update.
        percent (int): The open percentage to apply to the specified component.
    """
    if target == "window":
        vehicle_state.window_percent = percent
    elif target == "sunroof":
        vehicle_state.sunroof_percent = percent


def _set_seat_state(heat_level=None, ventilate=None):
    """
    Set seat heating level and ventilation state in the shared vehicle_state.
    
    Parameters:
        heat_level (int | None): Desired seat heating level; if None, the current value is left unchanged.
        ventilate (bool | None): Whether seat ventilation should be enabled (`True`) or disabled (`False`); if None, the current value is left unchanged.
    """
    if heat_level is not None:
        vehicle_state.seat_heat_level = heat_level
    if ventilate is not None:
        vehicle_state.seat_ventilate = ventilate


def _set_light_state(on=None, brightness=None):
    """
    Update the vehicle_state lighting fields when values are provided.
    
    Parameters:
        on (bool | None): If not None, set vehicle_state.light_on to this value.
        brightness (int | None): If not None, set vehicle_state.light_brightness to this value.
    """
    if on is not None:
        vehicle_state.light_on = on
    if brightness is not None:
        vehicle_state.light_brightness = brightness


def ac_control(action: str, temperature: float = None, mode: str = None, fan_level: int = None) -> dict:
    """
    Control the vehicle's air conditioning state according to the specified action.
    
    Parameters:
        action (str): One of "on", "off", or "adjust" determining the AC operation.
        temperature (float, optional): Target temperature to set when provided.
        mode (str, optional): AC mode to set (e.g., "auto", "cool") when provided.
        fan_level (int, optional): Fan level to set when provided.
    
    Returns:
        dict: A status dictionary with "status":"success" and "intent":"ac_control".
            - When action == "on": includes "action":"on" and "temperature" (the provided temperature or the current vehicle AC temperature).
            - When action == "off": includes "action":"off".
            - When action == "adjust": includes "action":"adjust" and the provided "temperature", "mode", and "fan_level" values (may be None).
    """
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
    """
    Control the window, sunroof, or door positions and return a status dictionary describing the outcome.
    
    Parameters:
        target (str): One of "window", "sunroof", or "door" identifying the target to control.
        action (str): Operation to perform: "open", "close", "adjust", or other intent names.
        percent (int, optional): Target openness percentage for "open" or "adjust". If omitted, defaults are used:
            - "open": 100
            - "adjust": 50
    
    Returns:
        dict: A status dictionary containing at least "status" and "intent". Possible additional keys:
            - "target": the provided target
            - "action": the performed action
            - "percent": applied openness percentage (when relevant)
            - "voice_reply": confirmation text for closing a door
          Behavior summary:
            - Opening a door returns a "need_confirm" status requiring confirmation.
            - Closing a door returns "success" with a "voice_reply".
            - Opening a non-door returns "need_confirm" with an applied or default percent (100).
            - Closing a non-door returns "success" and sets percent to 0.
            - Adjusting a non-door applies the given or default percent (50) and returns "success".
            - Unrecognized actions return a minimal success intent dictionary.
    """
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
    """
    Control the vehicle's interior lights.
    
    Parameters:
        action (str): One of "on", "off", or "adjust". "on" turns lights on, "off" turns lights off, and "adjust" sets brightness.
        target (str, optional): Ignored by this function; kept for compatibility.
        brightness (int, optional): Desired brightness level for "on" or "adjust". If omitted for "adjust", defaults to 50. If omitted for "on", the provided value (or vehicle state) is applied when available.
    
    Returns:
        dict: A result dictionary containing at least `"status": "success"` and `"intent": "light_control"`. When applicable includes `"action"` set to the performed action and `"brightness"` for brightness-adjusting actions.
    """
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
    """
    Control seat heating and ventilation.
    
    Parameters:
        action (str): One of "heat_on", "heat_off", "ventilate_on", "ventilate_off"; selects the seat control action.
        heat_level (int, optional): Heating level to set when `action` is "heat_on". If omitted or falsy, defaults to 2.
    
    Returns:
        dict: A result dictionary with keys:
            - "status": always "success".
            - "intent": always "seat_control".
            - "action": included for handled actions ("heat_on", "heat_off", "ventilate_on", "ventilate_off").
            - "heat_level": included when `action` is "heat_on", indicating the applied level.
    """
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
