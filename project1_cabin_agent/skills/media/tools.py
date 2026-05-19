"""
project1_cabin_agent/skills/media/tools.py
Media Skill 工具层 — 纯 mock（无外部 API 依赖）
"""
from project1_cabin_agent.vehicle_state import vehicle_state


def _set_media_state(playing=None, track=None, source=None):
    """
    Update shared vehicle_state media fields.
    
    Parameters:
    	playing (bool | None): If not None, sets the playback state.
    	track (str | None): If truthy, updates the current track.
    	source (str | None): If truthy, updates the media source.
    """
    if playing is not None:
        vehicle_state.media_playing = playing
    if track:
        vehicle_state.current_track = track
    if source:
        vehicle_state.media_source = source


def _set_volume(v: int):
    """
    Set the shared vehicle volume to the given value, clamped to the 0–100 range.
    
    Parameters:
        v (int): Desired volume level; values below 0 are set to 0 and values above 100 are set to 100.
    """
    vehicle_state.volume = max(0, min(100, v))


def media_control(action: str, query: str = None, volume: int = None) -> dict:
    """
    Dispatches media and volume commands and updates the shared vehicle_state accordingly.
    
    Supported actions:
    - "play": sets playback to playing.
    - "pause": sets playback to paused.
    - "next", "previous": acknowledge track navigation (no state change here).
    - "search": sets playback to playing and updates the current track from `query`.
    - "volume_up": increases volume by 10, capped at 100.
    - "volume_down": decreases volume by 10, floored at 0.
    - "set_volume": sets volume to `volume` or 50 if `volume` is None.
    Any other action is returned unchanged without mutating media state.
    
    Parameters:
        action (str): The command to execute; one of the supported action names above.
        query (str | None): Track identifier or search query used by the "search" action.
        volume (int | None): Target volume for "set_volume"; if None, defaults to 50.
    
    Returns:
        dict: A status dictionary containing at minimum `"status": "success"` and `"action": <action>"`. Depending on the action, the response may include `"query"` and/or `"volume"` with the applied values.
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
