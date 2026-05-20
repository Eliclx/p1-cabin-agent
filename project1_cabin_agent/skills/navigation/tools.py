"""
project1_cabin_agent/skills/navigation/tools.py
Navigation Skill 工具层 — 高德 REST API 封装

设计原则：
- 每个函数对应一个 intent，参数从 Pydantic schema 过滤
- 纯 API 调用，不含校验逻辑（校验归 harness）
- 统一返回格式：{"success": bool, "data": ..., "error": ...}
- API key 从环境变量读取，不硬编码
"""
import os
import requests
from typing import Optional

from shared.utils.logger import logger

# ── 配置 ──────────────────────────────────────────────────────────

AMAP_KEY = os.getenv("AMAP_API_KEY", "")
AMAP_BASE = "https://restapi.amap.com/v3"


# ── 工具函数 ──────────────────────────────────────────────────────

def _is_coord(s: str) -> bool:
    """判断是否是坐标格式 'lng,lat'"""
    parts = s.split(",")
    if len(parts) != 2:
        return False
    try:
        float(parts[0])
        float(parts[1])
        return True
    except ValueError:
        return False


def geocode(address: str, city: str = "成都") -> Optional[str]:
    """
    地理编码：地名 → 坐标
    
    Args:
        address: 地名（春熙路、天府广场）
        city: 城市名（默认成都）
    
    Returns:
        "lng,lat" 坐标字符串，失败返回 None
    """
    try:
        r = requests.get(f"{AMAP_BASE}/geocode/geo", params={
            "key": AMAP_KEY,
            "address": address,
            "city": city,
            "output": "json",
        }, timeout=5)
        data = r.json()
        geocodes = data.get("geocodes", [])
        if geocodes:
            location = geocodes[0].get("location")
            logger.info(f"[高德] 地理编码 {address} → {location}")
            return location
        logger.warning(f"[高德] 地理编码无结果: {address}")
        return None
    except Exception as e:
        logger.warning(f"[高德] 地理编码失败: {e}")
        return None


# ── Intent 对应的工具函数 ────────────────────────────────────────

def start_navigation(
    destination: str,
    origin: Optional[str] = None,
    route_type: str = "fastest",
) -> dict:
    """
    对应 intent: start_navigation
    驾车路径规划。
    
    Args:
        destination: 目的地（地名或坐标）
        origin: 起点（坐标），默认由 harness 从 vehicle_state 补
        route_type: 路线偏好 fastest/shortest/avoid_highway/avoid_toll
    
    Returns:
        {"success": True, "data": {"distance": km, "duration": min, "route": str}}
        {"success": False, "error": str}
    """
    if not origin:
        return {"success": False, "error": "缺少起点坐标，harness 未补全 origin"}

    # 目的地：地名 → geocode 转坐标
    if not _is_coord(destination):
        dest_coord = geocode(destination)
        if not dest_coord:
            return {"success": False, "error": f"无法解析目的地: {destination}"}
        destination = dest_coord

    # 高德路线策略映射
    strategy_map = {
        "fastest": 2,        # 速度最快
        "shortest": 3,       # 距离最短
        "avoid_highway": 4,  # 不走高速
        "avoid_toll": 9,     # 不走收费
    }
    strategy = strategy_map.get(route_type, 2)

    try:
        r = requests.get(f"{AMAP_BASE}/direction/driving", params={
            "key": AMAP_KEY,
            "origin": origin,
            "destination": destination,
            "strategy": strategy,
            "output": "json",
        }, timeout=5)
        data = r.json()
        route = data.get("route", {})
        paths = route.get("paths", [])

        if not paths:
            return {"success": False, "error": "无可用路径"}

        p = paths[0]
        distance_km = round(float(p.get("distance", 0)) / 1000, 1)
        duration_min = int(round(float(p.get("duration", 0)) / 60, 0))

        result = {
            "distance": distance_km,
            "duration": duration_min,
            "tolls": float(p.get("tolls", 0)),
            "route_text": f"全程{distance_km}公里，预计{duration_min}分钟",
        }
        logger.info(f"[高德] 路线规划: {result['route_text']}")
        return {"success": True, "data": result}

    except Exception as e:
        logger.warning(f"[高德] 路径规划失败: {e}")
        return {"success": False, "error": str(e)}


def search_poi(
    keyword: str,
    location: Optional[str] = None,
    radius: int = 3000,
    limit: int = 5,
) -> dict:
    """
    对应 intent: search_poi
    周边搜索。
    
    Args:
        keyword: 搜索关键词（加油站、餐厅、停车场）
        location: 搜索中心坐标，默认由 harness 从 vehicle_state 补
        radius: 搜索半径(米)
        limit: 返回数量
    
    Returns:
        {"success": True, "data": {"results": [...], "count": N}}
        {"success": False, "error": str}
    """
    if not location:
        return {"success": False, "error": "缺少位置坐标，harness 未补全 location"}

    try:
        r = requests.get(f"{AMAP_BASE}/place/around", params={
            "key": AMAP_KEY,
            "keywords": keyword,
            "location": location,
            "radius": radius,
            "offset": limit,
            "output": "json",
        }, timeout=5)
        data = r.json()
        pois = data.get("pois", [])

        results = []
        for p in pois:
            loc = p["location"].split(",")
            results.append({
                "name": p["name"],
                "lng": float(loc[0]),
                "lat": float(loc[1]),
                "dist_km": round(float(p.get("distance", 0)) / 1000, 1),
                "address": p.get("address", ""),
                "rating": float(p.get("biz_ext", {}).get("rating", 0) or 0),
            })

        logger.info(f"[高德] 周边搜索 {keyword}: {len(results)}个结果")
        return {"success": True, "data": {"results": results, "count": len(results)}}

    except Exception as e:
        logger.warning(f"[高德] 搜索失败: {e}")
        return {"success": False, "error": str(e)}
