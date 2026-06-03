"""
project1_cabin_agent/skills/media/action_format.py — Media 域 action 转换
"""

from __future__ import annotations

from project1_cabin_agent.actions.models import CabinAction


def format_media_control(tool_result: dict) -> CabinAction | None:
    action = tool_result.get("action", "")
    if action == "play":
        params = {
            k: tool_result[k]
            for k in ("query", "artist", "source", "track")
            if k in tool_result
        }
        return CabinAction(
            domain="media", intent="media_control", command="media_play", params=params
        )
    elif action == "pause":
        return CabinAction(
            domain="media", intent="media_control", command="media_pause"
        )
    elif action == "next":
        return CabinAction(domain="media", intent="media_control", command="media_next")
    elif action == "previous":
        return CabinAction(
            domain="media", intent="media_control", command="media_previous"
        )
    elif action in ("set_volume", "volume_set"):
        return CabinAction(
            domain="media",
            intent="media_control",
            command="media_volume",
            params={"volume": tool_result.get("volume")},
        )
    elif action == "volume_up":
        return CabinAction(
            domain="media", intent="media_control", command="media_volume_up"
        )
    elif action == "volume_down":
        return CabinAction(
            domain="media", intent="media_control", command="media_volume_down"
        )
    return None


# ── 导出 ──

MEDIA_ACTION_FORMATTERS = {
    "media_control": format_media_control,
}
