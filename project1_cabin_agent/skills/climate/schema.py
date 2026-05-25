"""
project1_cabin_agent/skills/climate/schema.py
Climate Skill Schema — Pydantic SSOT
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal


class AcControlSlots(BaseModel):
    """空调控制 — 开关/调温/调风"""
    action: Literal["on", "off", "adjust"] = Field(
        description="操作: on(开启)/off(关闭)/adjust(调节)"
    )
    temperature: Optional[float] = Field(
        default=None, ge=16, le=32,
        description="目标温度(℃)，范围16-32"
    )
    mode: Optional[Literal["cool", "heat", "auto"]] = Field(
        default=None,
        description="模式: cool(制冷)/heat(制热)/auto(自动)"
    )
    fan_level: Optional[int] = Field(
        default=None, ge=1, le=5,
        description="风速档位1-5"
    )


class WindowControlSlots(BaseModel):
    """车窗/天窗/车门控制 — 高风险"""
    target: Literal["window", "sunroof", "door"] = Field(
        description="控制对象: window(车窗)/sunroof(天窗)/door(车门)"
    )
    action: Literal["open", "close", "adjust"] = Field(
        description="操作: open/close/adjust"
    )
    percent: Optional[int] = Field(
        default=None, ge=0, le=100,
        description="开合百分比(0-100)"
    )


class LightControlSlots(BaseModel):
    """车内灯光控制"""
    action: Literal["on", "off", "adjust"] = Field(
        description="操作: on/off/adjust"
    )
    target: Optional[Literal["cabin", "reading", "ambient"]] = Field(
        default=None,
        description="灯光类型: cabin(车内)/reading(阅读)/ambient(氛围)"
    )
    brightness: Optional[int] = Field(
        default=None, ge=0, le=100,
        description="亮度0-100"
    )


class SeatControlSlots(BaseModel):
    """座椅加热/通风控制"""
    action: Literal["heat_on", "heat_off", "ventilate_on", "ventilate_off"] = Field(
        description="操作: heat_on(加热开)/heat_off(加热关)/ventilate_on(通风开)/ventilate_off(通风关)"
    )
    heat_level: Optional[int] = Field(
        default=None, ge=1, le=3,
        description="加热档位1-3"
    )


class CabinQuerySlots(BaseModel):
    """座舱状态查询 — 空调温度/车内温度/湿度等"""
    items: Optional[str] = Field(
        default=None,
        description="查询项目: ac_temp(空调温度)/cabin_temp(车内温度)/humidity(湿度)"
    )


CLIMATE_INTENTS: dict[str, type[BaseModel]] = {
    "ac_control": AcControlSlots,
    "window_control": WindowControlSlots,
    "light_control": LightControlSlots,
    "seat_control": SeatControlSlots,
    "cabin_query": CabinQuerySlots,
}


def get_intent_schema(intent: str) -> type[BaseModel] | None:
    return CLIMATE_INTENTS.get(intent)


def get_all_intent_names() -> list[str]:
    return list(CLIMATE_INTENTS.keys())
