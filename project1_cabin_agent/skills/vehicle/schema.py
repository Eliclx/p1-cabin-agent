"""
project1_cabin_agent/skills/vehicle/schema.py
Vehicle Skill Schema — Pydantic SSOT
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal


class QueryVehicleStatusSlots(BaseModel):
    """查询车辆状态 — 油量/胎压/电量/温度等"""
    items: Optional[str] = Field(
        default=None,
        description="查询项目: fuel(油量)/battery(电量)/tire(胎压)/mileage(里程)/temperature(车内温度)/ac_temp(空调设定温度)/speed(车速)"
    )


class ActivateSceneSlots(BaseModel):
    """场景联动"""
    scene_name: Literal["comfortable_driving", "sleep_mode", "departure_check"] = Field(
        description="场景名: comfortable_driving(舒适驾驶)/sleep_mode(休息)/departure_check(出发检查)"
    )


VEHICLE_INTENTS: dict[str, type[BaseModel]] = {
    "query_vehicle_status": QueryVehicleStatusSlots,
    "activate_scene": ActivateSceneSlots,
}


def get_intent_schema(intent: str) -> type[BaseModel] | None:
    return VEHICLE_INTENTS.get(intent)


def get_all_intent_names() -> list[str]:
    return list(VEHICLE_INTENTS.keys())
