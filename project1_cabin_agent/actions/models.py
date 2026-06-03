"""
project1_cabin_agent/actions/models.py — Action 信号数据模型

每个 action 代表一个给硬件的结构化指令。
独立于 voice_reply，可以单独校验。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CabinAction:
    """
    座舱硬件动作信号。

    Examples:
        # 空调控制
        CabinAction(domain="climate", intent="ac_control",
                    command="ac_set", params={"temperature": 24, "mode": "auto"})

        # 导航启动
        CabinAction(domain="map", intent="navigate",
                    command="start_nav", params={"destination": {"lng": 106.5, "lat": 29.5},
                                                  "route_type": "fastest"})

        # 车窗控制
        CabinAction(domain="climate", intent="window_control",
                    command="window_set", params={"target": "driver", "percent": 50})
    """

    domain: str          # "climate" / "map" / "media" / "vehicle"
    intent: str          # "ac_control" / "navigate" / "media_control" / ...
    command: str         # "ac_set" / "start_nav" / "play" / "window_set" / ...
    params: dict = field(default_factory=dict)  # 动作参数

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "intent": self.intent,
            "command": self.command,
            "params": self.params,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CabinAction:
        return cls(
            domain=d["domain"],
            intent=d["intent"],
            command=d["command"],
            params=d.get("params", {}),
        )


# ═══════════════════════════════════════════════════
# Per-domain action command 定义（声明式）
# ═══════════════════════════════════════════════════

CLIMATE_ACTIONS = {
    "ac_control": {
        "on":       {"command": "ac_on"},
        "off":      {"command": "ac_off"},
        "adjust":   {"command": "ac_set", "params": ["temperature", "mode", "fan_level"]},
    },
    "window_control": {
        "open":     {"command": "window_open", "params": ["target"]},
        "close":    {"command": "window_close", "params": ["target"]},
        "adjust":   {"command": "window_set", "params": ["target", "percent"]},
    },
    "light_control": {
        "on":       {"command": "light_on"},
        "off":      {"command": "light_off"},
        "adjust":   {"command": "light_set", "params": ["target", "brightness"]},
    },
    "seat_control": {
        "heat_on":      {"command": "seat_heat_on", "params": ["heat_level"]},
        "heat_off":     {"command": "seat_heat_off"},
        "ventilate_on": {"command": "seat_vent_on"},
        "ventilate_off":{"command": "seat_vent_off"},
    },
}

MAP_ACTIONS = {
    "navigate": {
        "command": "start_nav",
        "params": ["destination", "origin", "route_type"],
    },
    "search_poi": {
        "command": "search_poi",
        "params": ["keyword", "location", "radius"],
    },
    "map_query": {
        "command": "map_query",
        "params": ["query_type", "target", "location"],
    },
    "weather": {
        "command": "weather_query",
        "params": ["city", "date"],
    },
}

MEDIA_ACTIONS = {
    "media_control": {
        "play":         {"command": "media_play", "params": ["query", "artist", "source"]},
        "pause":        {"command": "media_pause"},
        "next":         {"command": "media_next"},
        "previous":     {"command": "media_previous"},
        "set_volume":   {"command": "media_volume", "params": ["volume"]},
        "volume_up":    {"command": "media_volume_up"},
        "volume_down":  {"command": "media_volume_down"},
    },
}

VEHICLE_ACTIONS = {
    "vehicle_status": {
        "command": "vehicle_query",
        "params": ["items"],
    },
}
