"""
project1_cabin_agent/skills/search/schema.py
Search Skill Schema — Pydantic SSOT
"""
from pydantic import BaseModel, Field
from typing import Optional


class SearchPoiSlots(BaseModel):
    """搜索周边兴趣点"""
    keyword: str = Field(
        description="搜索关键词: 加油站/餐厅/停车场/医院/便利店"
    )
    category: Optional[str] = Field(
        default=None,
        description="类别过滤: 餐饮/酒店/景点/加油站"
    )
    radius: float = Field(
        default=5.0, ge=1.0, le=50.0,
        description="搜索半径(公里)"
    )


SEARCH_INTENTS: dict[str, type[BaseModel]] = {
    "search_poi": SearchPoiSlots,
}


def get_intent_schema(intent: str) -> type[BaseModel] | None:
    return SEARCH_INTENTS.get(intent)


def get_all_intent_names() -> list[str]:
    return list(SEARCH_INTENTS.keys())
