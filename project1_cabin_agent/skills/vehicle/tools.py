"""
project1_cabin_agent/skills/vehicle/tools.py
Vehicle Skill 工具层 — 纯 mock（无外部 API 依赖）
"""
from project1_cabin_agent.vehicle_state import vehicle_state


def query_vehicle_status(items: str = None) -> dict:
    """
    Retrieve vehicle status or a specific status item.
    
    If `items` names a key present in the vehicle status, returns that item's `value` and `voice_reply`; otherwise returns a default overall status reply with `items` set to the provided name or `"all"`.
    
    Parameters:
        items (str, optional): The specific status key to query (e.g., "fuel", "tire", "battery", "temperature"). If omitted or not found, the function returns the overall/default status reply.
    
    Returns:
        dict: A result dictionary. When a specific item is found, includes `{"status": "success", "items": items, "value": <item value>, "voice_reply": <item voice>}`. Otherwise includes `{"status": "success", "items": items or "all", "voice_reply": "好的，车辆状态正常"}`.
    """
    status = vehicle_state.to_mock_status()
    if items and items in status:
        info = status[items]
        return {"status": "success", "items": items,
                "value": info["value"], "voice_reply": info["voice"]}
    # 返回全部状态
    return {"status": "success", "items": items or "all",
            "voice_reply": "好的，车辆状态正常"}


def activate_scene(scene_name: str) -> dict:
    """
    Activate a predefined in-vehicle scene by adjusting cabin systems and return a voice-ready response.
    
    This function triggers changes to cabin state (HVAC, media, lights, seats) for known scenes and returns a normalized result describing the activated scene and a voice reply. Recognized scenes:
    - "comfortable_driving": sets a comfort driving profile (AC, light music, seat heating).
    - "sleep_mode": sets a resting profile (mild AC, lights off, media paused).
    - "departure_check": gathers concise status phrases for fuel, battery, and tire and composes a check-list voice reply.
    For any other scene name, the function returns a generic success message acknowledging activation without performing predefined controls.
    
    Parameters:
        scene_name (str): The identifier of the scene to activate; known values are "comfortable_driving", "sleep_mode", and "departure_check".
    
    Returns:
        dict: A payload with keys:
            - "status": fixed string `"success"`.
            - "scene": human-readable scene name or the provided `scene_name`.
            - "voice_reply": a short string suitable for vocalization describing the result of the activation.
    """
    import project1_cabin_agent.tools.cabin_tools as ct

    if scene_name == "comfortable_driving":
        ct._set_ac_state(on=True, temp=24, mode="auto", fan_level=2)
        ct._set_media_state(playing=True, source="轻音乐")
        ct._set_seat_state(heat_level=1)
        return {"status": "success", "scene": "舒适驾驶",
                "voice_reply": "已激活舒适驾驶：空调24度、播放轻音乐、座椅加热1档"}
    elif scene_name == "sleep_mode":
        ct._set_ac_state(on=True, temp=25, mode="auto", fan_level=1)
        ct._set_light_state(on=False)
        ct._set_media_state(playing=False)
        return {"status": "success", "scene": "休息",
                "voice_reply": "已激活休息模式：空调25度低风、关闭车灯、暂停音乐"}
    elif scene_name == "departure_check":
        status = vehicle_state.to_mock_status()
        checks = [status.get(i, {}).get("voice", i) for i in ["fuel", "battery", "tire"]]
        return {"status": "success", "scene": "出发前检查",
                "voice_reply": "出发前检查：" + "；".join(checks)}
    return {"status": "success", "scene": scene_name,
            "voice_reply": f"好的，已激活{scene_name}"}
