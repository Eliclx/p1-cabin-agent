"""
project1_cabin_agent/skills/media/schema.py
Media Skill Schema — Pydantic SSOT
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal


class MediaControlSlots(BaseModel):
    """媒体与音量控制"""

    action: Literal[
        "play",
        "pause",
        "next",
        "previous",
        "search",
        "volume_up",
        "volume_down",
        "set_volume",
    ] = Field(
        description="操作类型: play(播放)/pause(暂停)/next(下一首)/previous(上一首)/search(搜索)/volume_up(音量+)/volume_down(音量-)/set_volume(指定音量)"
    )
    query: Optional[str] = Field(
        default=None, description="搜索关键词（action=search 时，如歌名/歌手）"
    )
    volume: Optional[int] = Field(
        default=None, ge=0, le=100, description="目标音量（action=set_volume 时）"
    )


MEDIA_INTENTS: dict[str, type[BaseModel]] = {
    "media_control": MediaControlSlots,
}

# 记忆元数据
MEDIA_MEMORY: dict[str, dict] = {
    "media_control": {
        "log": True,
        "dedup_key": "query",  # 按歌名/艺术家去重
        "link_key": "",  # 不链接
        "summary_templates": {  # 按场景选模板
            "query": "播放了{query}",
            "artist": "播放了{artist}的歌",
            "default": "媒体操作: {action}",
        },
        "detail_fields": ["query", "artist", "action"],
        "l3_keys": {"query": "music_query"},  # 写入 L3 偏好
    },
}


def get_intent_schema(intent: str) -> type[BaseModel] | None:
    return MEDIA_INTENTS.get(intent)


def get_all_intent_names() -> list[str]:
    return list(MEDIA_INTENTS.keys())
