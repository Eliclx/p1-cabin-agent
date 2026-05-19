"""
project1_cabin_agent/skills/media/schema.py
Media Skill Schema — Pydantic SSOT
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal


class MediaControlSlots(BaseModel):
    """媒体与音量控制"""
    action: Literal["play", "pause", "next", "previous", "search",
                    "volume_up", "volume_down", "set_volume"] = Field(
        description="操作类型: play(播放)/pause(暂停)/next(下一首)/previous(上一首)/search(搜索)/volume_up(音量+)/volume_down(音量-)/set_volume(指定音量)"
    )
    query: Optional[str] = Field(
        default=None,
        description="搜索关键词（action=search 时，如歌名/歌手）"
    )
    volume: Optional[int] = Field(
        default=None, ge=0, le=100,
        description="目标音量（action=set_volume 时）"
    )


MEDIA_INTENTS: dict[str, type[BaseModel]] = {
    "media_control": MediaControlSlots,
}


def get_intent_schema(intent: str) -> type[BaseModel] | None:
    """
    Retrieve the Pydantic model class registered for a given intent name.
    
    Parameters:
        intent (str): The intent name to look up.
    
    Returns:
        type[BaseModel] | None: The Pydantic `BaseModel` subclass associated with `intent`, or `None` if no schema is registered for that intent.
    """
    return MEDIA_INTENTS.get(intent)


def get_all_intent_names() -> list[str]:
    """
    List all registered intent names for the media skill.
    
    Returns:
        intent_names (list[str]): A list of registered intent name strings from MEDIA_INTENTS.
    """
    return list(MEDIA_INTENTS.keys())
