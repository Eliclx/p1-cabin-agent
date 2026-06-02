"""
project1_cabin_agent/skills/vehicle/schema.py
Vehicle Skill Schema — Pydantic SSOT
"""

from pydantic import BaseModel, Field
from typing import Optional


class QueryVehicleStatusSlots(BaseModel):
    """查询车辆状态 — 油量/胎压/电量/里程等硬车况"""

    items: Optional[str] = Field(
        default=None,
        description="查询项目: fuel(油量)/battery(电量)/tire(胎压)/mileage(里程)/speed(车速)",
    )


VEHICLE_INTENTS: dict[str, type[BaseModel]] = {
    "query_vehicle_status": QueryVehicleStatusSlots,
}

# 记忆元数据
VEHICLE_MEMORY: dict[str, dict] = {
    "query_vehicle_status": {
        "log": False,  # 查询类不记
    },
}


def get_intent_schema(intent: str) -> type[BaseModel] | None:
    return VEHICLE_INTENTS.get(intent)


def get_all_intent_names() -> list[str]:
    return list(VEHICLE_INTENTS.keys())
