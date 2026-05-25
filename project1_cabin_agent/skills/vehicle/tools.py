"""
project1_cabin_agent/skills/vehicle/tools.py
Vehicle Skill 工具层 — 纯 mock（无外部 API 依赖）
"""
from project1_cabin_agent.vehicle_state import vehicle_state


def query_vehicle_status(items: str = None) -> dict:
    """查询车辆状态 — 油量/胎压/电量/里程等硬车况"""
    status = vehicle_state.to_mock_status()
    if items and items in status:
        info = status[items]
        return {"status": "success", "items": items,
                "value": info["value"], "voice_reply": info["voice"]}
    # 返回全部状态
    return {"status": "success", "items": items or "all",
            "voice_reply": "好的，车辆状态正常"}
