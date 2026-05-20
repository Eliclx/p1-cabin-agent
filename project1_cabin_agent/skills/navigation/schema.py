"""
project1_cabin_agent/skills/navigation/schema.py
Navigation Skill Schema — Pydantic SSOT（单一真相源）

同时用于：
1. 生成 Stage2 prompt 的字段列表（model_json_schema()）
2. 校验 few-shot 示例的合法性（model_validate()）
3. harness 校验规则的数据来源（required/enum/default）
4. tools.py 参数签名（只接受 schema 声明的字段）

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
# Intent 1: start_navigation — 导航到目的地
# ═══════════════════════════════════════════════════════════════

class NavigateToSlots(BaseModel):
    """
    导航到目的地。
    
    端侧 Stage2 prompt 生成：
      schema = NavigateToSlots.model_json_schema()
      → {"properties": {"destination": {"type": "string", "description": "目的地名称或坐标"}, ...}}
      → 注入 system prompt
    """
    destination: str = Field(
        description="目的地名称或坐标。用户可能说地名（春熙路）、别名（家/公司）、坐标（104.08,30.66）"
    )
    origin: Optional[str] = Field(
        default=None,
        description="起点。默认从 vehicle_state 取当前位置，一般不需要用户指定"
    )
    route_type: Optional[Literal["fastest", "shortest", "avoid_highway", "avoid_toll"]] = Field(
        default="fastest",
        description="路线偏好。默认最快路线"
    )


# ═══════════════════════════════════════════════════════════════
# Intent 2: search_poi — 搜索周边
# ═══════════════════════════════════════════════════════════════

class SearchNearbySlots(BaseModel):
    """搜索周边设施（加油站、餐厅、停车场等）"""
    keyword: str = Field(
        description="搜索关键词。如：加油站、餐厅、停车场、厕所、银行"
    )
    location: Optional[str] = Field(
        default=None,
        description="搜索中心位置。默认从 vehicle_state 取当前位置"
    )
    radius: Optional[int] = Field(
        default=3000,
        description="搜索半径(米)。默认3公里",
        ge=100,
        le=50000,
    )


# ═══════════════════════════════════════════════════════════════
# 域注册表 — domain "navigation" 下的所有 intent
# ═══════════════════════════════════════════════════════════════

NAVIGATION_INTENTS: dict[str, type[BaseModel]] = {
    "start_navigation": NavigateToSlots,
    "search_poi": SearchNearbySlots,
}


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def get_intent_schema(intent: str) -> type[BaseModel] | None:
    """根据 intent 名获取对应的 Pydantic model"""
    return NAVIGATION_INTENTS.get(intent)


def get_all_intent_names() -> list[str]:
    """返回该域所有 intent 名（用于 Stage2 prompt 的 intent 列表）"""
    return list(NAVIGATION_INTENTS.keys())


def build_stage2_intent_list() -> str:
    """
    生成 Stage2 prompt 的 intent 列表文本。
    
    输出示例：
      start_navigation: 导航到目的地 → 槽位: destination(string), origin(string), route_type(enum)
      search_poi: 搜索周边设施 → 槽位: keyword(string), location(string), radius(integer)
    """
    lines = []
    for intent_name, model_cls in NAVIGATION_INTENTS.items():
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
