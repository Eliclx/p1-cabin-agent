"""
project1_cabin_agent/skills/media/tools.py
Media Skill 工具层 — 纯 mock（无外部 API 依赖）
"""
from project1_cabin_agent.vehicle_state import vehicle_state


def _set_media_state(playing=None, track=None, source=None):
    if playing is not None:
        vehicle_state.media_playing = playing
    if track:
        vehicle_state.current_track = track
    if source:
        vehicle_state.media_source = source


def _set_volume(v: int):
    vehicle_state.volume = max(0, min(100, v))


def media_control(action: str, query: str = None, volume: int = None) -> dict:
    """媒体与音量控制。

    action: play|pause|next|previous|search|volume_up|volume_down|set_volume
    """
    if action == "play":
        _set_media_state(playing=True)
        return {"status": "success", "action": "play"}
    elif action == "pause":
        _set_media_state(playing=False)
        return {"status": "success", "action": "pause"}
    elif action == "next":
        return {"status": "success", "action": "next"}
    elif action == "previous":
        return {"status": "success", "action": "previous"}
    elif action == "search":
        _set_media_state(playing=True, track=query)
        return {"status": "success", "action": "search", "query": query}
    elif action == "volume_up":
        new_vol = min(100, vehicle_state.volume + 10)
        _set_volume(new_vol)
        return {"status": "success", "action": "volume_up", "volume": new_vol}
    elif action == "volume_down":
        new_vol = max(0, vehicle_state.volume - 10)
        _set_volume(new_vol)
        return {"status": "success", "action": "volume_down", "volume": new_vol}
    elif action == "set_volume":
        v = volume if volume is not None else 50
        _set_volume(v)
        return {"status": "success", "action": "set_volume", "volume": v}
    return {"status": "success", "action": action}
