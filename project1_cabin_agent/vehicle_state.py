"""
project1_cabin_agent/vehicle_state.py
车内状态模型（全局单例）

车载场景天然是单车单用户，不存在多会话并发隔离需求。
"""
from dataclasses import dataclass, asdict, field


@dataclass
class VehicleState:
    fuel: int = 68
    battery: int = 82
    speed: int = 60
    mileage: int = 12456
    temperature: float = 32.0
    tire_status: str = "正常"
    location: str = "104.06,30.67"  # 当前位置（经度,纬度 GCJ-02），mock 默认成都

    ac_on: bool = False
    ac_temp: float = 24.0
    ac_mode: str = "auto"
    ac_fan_level: int = 3
    window_percent: int = 0
    sunroof_percent: int = 0
    door_open: bool = False
    music_playing: bool = False
    music_source: str = ""
    music_track: str = ""
    volume: int = 50
    seat_heat_level: int = 0
    seat_ventilate: bool = False
    light_on: bool = False
    light_brightness: int = 80

    def to_mock_status(self) -> dict:
        return {
            "fuel": {"value": f"{self.fuel}%", "voice": f"当前油量{self.fuel}%，续航约{int(self.fuel * 4.1)}公里"},
            "battery": {"value": f"{self.battery}%", "voice": f"电池电量{self.battery}%，续航约{int(self.battery * 3.9)}公里"},
            "tire": {"value": self.tire_status, "voice": f"四轮胎压{self.tire_status}" + ("，无需充气" if self.tire_status == "正常" else "")},
            "mileage": {"value": f"{self.mileage:,}km", "voice": f"当前里程{self.mileage}公里"},
            "temperature": {"value": f"{self.temperature}°C", "voice": f"车内温度{self.temperature}摄氏度"},
            "ac_temp": {"value": f"{self.ac_temp}°C", "voice": f"空调设定温度{self.ac_temp}摄氏度"},
            "speed": {"value": f"{self.speed}km/h", "voice": f"当前车速{self.speed}公里每小时"},
        }

    def update(self, updates: dict) -> None:
        for k, v in updates.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def snapshot(self) -> dict:
        return asdict(self)

    def to_prompt_text(self) -> str:
        return (
            f"油量={self.fuel}%, 电量={self.battery}%, 车速={self.speed}km/h, "
            f"车内温度={self.temperature}°C, 里程={self.mileage}km, "
            f"空调={'开' if self.ac_on else '关'}({self.ac_temp}°C/{self.ac_mode}/风挡{self.ac_fan_level}), "
            f"车窗={'开' if self.window_percent > 0 else '关'}({self.window_percent}%), "
            f"音乐={'播放中' if self.music_playing else '停止'}, 音量={self.volume}, "
            f"座椅加热={'L'+str(self.seat_heat_level) if self.seat_heat_level > 0 else '关'}, "
            f"车灯={'开' if self.light_on else '关'}(亮度{self.light_brightness}%)"
        )


vehicle_state = VehicleState()
