"""
project1_cabin_agent/skills/map/schema.py
Map Skill Schema — Pydantic SSOT（单一真相源）

合并原 navigation + search 域 → map 域，包含 4 个 intent：
1. search_poi — 搜索周边设施（加油站、餐厅、停车场等）
2. navigate   — 导航到目的地（rename from start_navigation）
3. map_query  — 地图信息查询（现在在哪儿/多远/堵不堵/还有多久）
4. weather    — 天气查询

派生关系：
  schema.py（唯一真相源）
    ├→ Stage2 prompt 字段定义
    ├→ examples.yaml 校验
    ├→ harness 校验规则
    └→ tools.py 参数过滤
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, Literal


# ═══════════════════════════════════════════════════════════════
# Intent 1: search_poi — 搜索周边设施
# ═══════════════════════════════════════════════════════════════

class SearchPoiSlots(BaseModel):
    """
    搜索周边设施（加油站、餐厅、停车场等）。
    合并自原 navigation/search_poi + search/search_poi。
    统一使用米作为距离单位。
    """
    keyword: str = Field(
        description="搜索关键词。如：加油站、餐厅、停车场、厕所、银行"
    )
    category: Optional[str] = Field(
        default=None,
        description="类别过滤: 餐饮/酒店/景点/加油站"
    )
    location: Optional[str] = Field(
        default=None,
        description="搜索中心位置坐标(lng,lat)。默认从 vehicle_state 取当前位置"
    )
    radius: Optional[int] = Field(
        default=3000,
        description="搜索半径(米)。默认3000米",
        ge=100,
        le=50000,
    )


# ═══════════════════════════════════════════════════════════════
# Intent 2: navigate — 导航到目的地（rename from start_navigation）
# ═══════════════════════════════════════════════════════════════

class NavigateSlots(BaseModel):
    """
    导航到目的地。
    对应原 navigation/start_navigation，重命名为 navigate。
    """
    destination: str = Field(
        description="目的地名称或坐标。用户可能说地名（春熙路）、别名（家/公司）、坐标（104.08,30.66）"
    )
    origin: Optional[str] = Field(
        default=None,
        description="起点坐标(lng,lat)。默认从 vehicle_state 取当前位置，一般不需要用户指定"
    )
    route_type: Optional[Literal["fastest", "shortest", "avoid_highway", "avoid_toll"]] = Field(
        default="fastest",
        description="路线偏好。默认最快路线"
    )


# ═══════════════════════════════════════════════════════════════
# Intent 3: map_query — 地图信息查询
# ═══════════════════════════════════════════════════════════════

class MapQuerySlots(BaseModel):
    """
    地图信息查询。
    支持查询当前位置、距离、路况、预计到达时间。
    """
    query_type: Optional[Literal["location", "distance", "traffic", "eta"]] = Field(
        default="location",
        description="查询类型：location=位置, distance=距离, traffic=路况, eta=预计到达时间"
    )
    target: Optional[str] = Field(
        default=None,
        description="查询目标。如距离查询的目标地点、路况查询的路段名称"
    )


# ═══════════════════════════════════════════════════════════════
# Intent 4: weather — 天气查询
# ═══════════════════════════════════════════════════════════════

class WeatherSlots(BaseModel):
    """
    天气查询。
    查询指定城市和日期的天气信息。
    """
    city: Optional[str] = Field(
        default=None,
        description="查询城市。默认从当前位置所在城市获取"
    )
    date: Optional[str] = Field(
        default="今天",
        description="查询日期。如：今天、明天、后天"
    )


# ═══════════════════════════════════════════════════════════════
# 域注册表 — domain "map" 下的所有 intent
# ═══════════════════════════════════════════════════════════════

MAP_INTENTS: dict[str, type[BaseModel]] = {
    "search_poi": SearchPoiSlots,
    "navigate": NavigateSlots,
    "map_query": MapQuerySlots,
    "weather": WeatherSlots,
}


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def get_intent_schema(intent: str) -> type[BaseModel] | None:
    """根据 intent 名获取对应的 Pydantic model"""
    return MAP_INTENTS.get(intent)


def get_all_intent_names() -> list[str]:
    """返回该域所有 intent 名（用于 Stage2 prompt 的 intent 列表）"""
    return list(MAP_INTENTS.keys())


def build_stage2_intent_list() -> str:
    """
    生成 Stage2 prompt 的 intent 列表文本。

    输出示例：
      search_poi: 搜索周边设施 → 槽位: keyword(string), category(string), location(string), radius(integer)
      navigate: 导航到目的地 → 槽位: destination(string), origin(string), route_type(enum)
    """
    lines = []
    for intent_name, model_cls in MAP_INTENTS.items():
        desc = model_cls.__doc__ or ""
        # 取第一行作为简短描述
        short_desc = desc.strip().split("\n")[0]

        schema = model_cls.model_json_schema()
        props = schema.get("properties", {})
        slot_parts = []
        for slot_name, slot_def in props.items():
            slot_type = slot_def.get("type", "string")
            if "enum" in slot_def:
                slot_type = f"enum({','.join(slot_def['enum'])})"
            slot_parts.append(f"{slot_name}({slot_type})")

        slots_str = ", ".join(slot_parts)
        lines.append(f"  - {intent_name}: {short_desc} → 槽位: {slots_str}")

    return "\n".join(lines)
