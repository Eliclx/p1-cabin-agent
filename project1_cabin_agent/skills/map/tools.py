"""
project1_cabin_agent/skills/map/tools.py
Map Skill 工具层 — 高德 REST API 封装

设计原则：
- 每个函数对应一个 intent，函数名 = intent 名
- 纯 API 调用，不含校验逻辑（校验归 harness）
- 统一返回格式：{"success": bool, "data": ..., "error": ...}
- API key 从环境变量读取，不硬编码
- 不使用 mock 数据

合并自：
- navigation/tools.py → search_poi, navigate, geocode
- 新增 → map_query, weather
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


def _amap_get(endpoint: str, params: dict, timeout: int = 5) -> Optional[dict]:
    """
    高德 API 统一 GET 请求入口。

    Args:
        endpoint: API 路径，如 "/geocode/geo"
        params: 请求参数（不含 key）
        timeout: 超时秒数

    Returns:
        JSON dict，失败返回 None
    """
    try:
        full_params = {"key": AMAP_KEY, "output": "json", **params}
        r = requests.get(f"{AMAP_BASE}{endpoint}", params=full_params, timeout=timeout)
        return r.json()
    except Exception as e:
        logger.warning(f"[高德] API 请求失败 {endpoint}: {e}")
        return None


def geocode(address: str, city: str = "成都") -> Optional[str]:
    """
    地理编码：地名 → 坐标

    Args:
        address: 地名（春熙路、天府广场）
        city: 城市名（默认成都）

    Returns:
        "lng,lat" 坐标字符串，失败返回 None
    """
    data = _amap_get("/geocode/geo", {
        "address": address,
        "city": city,
    })
    if not data:
        return None

    geocodes = data.get("geocodes", [])
    if geocodes:
        location = geocodes[0].get("location")
        logger.info(f"[高德] 地理编码 {address} → {location}")
        return location
    logger.warning(f"[高德] 地理编码无结果: {address}")
    return None


def _reverse_geocode(location: str) -> Optional[dict]:
    """
    逆地理编码：坐标 → 地址信息

    Args:
        location: "lng,lat" 坐标

    Returns:
        {"province": ..., "city": ..., "district": ..., "address": ...}
    """
    data = _amap_get("/geocode/regeo", {
        "location": location,
        "extensions": "base",
    })
    if not data:
        return None

    regeocode = data.get("regeocode", {})
    addr_component = regeocode.get("addressComponent", {})
    return {
        "province": addr_component.get("province", ""),
        "city": addr_component.get("city", ""),
        "district": addr_component.get("district", ""),
        "address": regeocode.get("formatted_address", ""),
    }


# ═══════════════════════════════════════════════════════════════
# Intent 1: search_poi — 搜索周边设施
# ═══════════════════════════════════════════════════════════════

def search_poi(
    keyword: str,
    category: Optional[str] = None,
    location: Optional[str] = None,
    radius: int = 3000,
    limit: int = 5,
) -> dict:
    """
    对应 intent: search_poi
    周边搜索（高德 /place/around API）。

    Args:
        keyword: 搜索关键词（加油站、餐厅、停车场）
        category: 类别过滤（可选）
        location: 搜索中心坐标(lng,lat)，默认由 harness 从 vehicle_state 补
        radius: 搜索半径(米)
        limit: 返回数量

    Returns:
        {"success": True, "data": {"results": [...], "count": N}}
        {"success": False, "error": str}
    """
    if not location:
        return {"success": False, "error": "缺少位置坐标，harness 未补全 location"}

    params = {
        "keywords": keyword,
        "location": location,
        "radius": radius,
        "offset": limit,
    }
    if category:
        params["types"] = category

    data = _amap_get("/place/around", params)
    if data is None:
        return {"success": False, "error": "高德 API 请求失败"}

    pois = data.get("pois", [])
    results = []
    for p in pois:
        loc = p.get("location", "0,0").split(",")
        results.append({
            "name": p["name"],
            "lng": float(loc[0]),
            "lat": float(loc[1]),
            "distance": int(float(p.get("distance", 0))),
            "address": p.get("address", ""),
            "rating": float(p.get("biz_ext", {}).get("rating", 0) or 0),
        })

    logger.info(f"[高德] 周边搜索 {keyword}: {len(results)}个结果")
    return {"success": True, "data": {"results": results, "count": len(results)}}


# ═══════════════════════════════════════════════════════════════
# Intent 2: navigate — 导航到目的地
# ═══════════════════════════════════════════════════════════════

def navigate(
    destination: str,
    origin: Optional[str] = None,
    route_type: str = "fastest",
) -> dict:
    """
    对应 intent: navigate（原 start_navigation）
    驾车路径规划。

    Args:
        destination: 目的地（地名或坐标）
        origin: 起点坐标(lng,lat)，默认由 harness 从 vehicle_state 补
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

    data = _amap_get("/direction/driving", {
        "origin": origin,
        "destination": destination,
        "strategy": strategy,
    })
    if data is None:
        return {"success": False, "error": "高德 API 请求失败"}

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


# ═══════════════════════════════════════════════════════════════
# Intent 3: map_query — 地图信息查询
# ═══════════════════════════════════════════════════════════════

def map_query(
    query_type: str = "location",
    target: Optional[str] = None,
    location: Optional[str] = None,
    destination: Optional[str] = None,
) -> dict:
    """
    对应 intent: map_query
    地图信息查询（位置、距离、路况、预计到达时间）。

    Args:
        query_type: 查询类型 location/distance/traffic/eta
        target: 查询目标（如目标地点名）
        location: 当前位置坐标(lng,lat)，默认由 harness 补
        destination: 目的地坐标(lng,lat)，distance/eta 时需要

    Returns:
        {"success": True, "data": {...}}
        {"success": False, "error": str}
    """
    if not location:
        return {"success": False, "error": "缺少位置坐标，harness 未补全 location"}

    # ── 位置查询 ──
    if query_type == "location":
        addr_info = _reverse_geocode(location)
        if not addr_info:
            return {"success": False, "error": "逆地理编码失败"}
        return {"success": True, "data": {
            "query_type": "location",
            "location": location,
            **addr_info,
        }}

    # ── 距离查询 ──
    if query_type == "distance":
        if not target and not destination:
            return {"success": False, "error": "距离查询需要指定目标地点"}
        # 目标地名 → 坐标
        if not destination:
            dest_coord = geocode(target or "")
            if not dest_coord:
                return {"success": False, "error": f"无法解析目标地点: {target}"}
            destination = dest_coord

        data = _amap_get("/distance", {
            "origins": location,
            "destination": destination,
            "type": "1",  # 驾车距离
        })
        if data is None:
            return {"success": False, "error": "高德距离查询失败"}

        results = data.get("results", [])
        if not results:
            return {"success": False, "error": "距离查询无结果"}

        dist_m = int(float(results[0].get("distance", 0)))
        dist_km = round(dist_m / 1000, 1)
        return {"success": True, "data": {
            "query_type": "distance",
            "target": target or destination,
            "distance_m": dist_m,
            "distance_km": dist_km,
        }}

    # ── 路况查询 ──
    if query_type == "traffic":
        if not target and not destination:
            return {"success": False, "error": "路况查询需要指定目标路段或目的地"}
        if not destination:
            dest_coord = geocode(target or "")
            if not dest_coord:
                return {"success": False, "error": f"无法解析目标地点: {target}"}
            destination = dest_coord

        data = _amap_get("/direction/driving", {
            "origin": location,
            "destination": destination,
            "strategy": 2,
            "extensions": "all",
        })
        if data is None:
            return {"success": False, "error": "高德路况查询失败"}

        route = data.get("route", {})
        paths = route.get("paths", [])
        if not paths:
            return {"success": False, "error": "无可用路径信息"}

        p = paths[0]
        # 解析 TMC 路况信息
        traffic_desc = []
        steps = p.get("steps", [])
        for step in steps:
            for tmc in step.get("tmcs", []):
                status = tmc.get("status", "未知")
                name = tmc.get("name", "")
                if name:
                    traffic_desc.append({"road": name, "status": status})

        duration_min = int(round(float(p.get("duration", 0)) / 60, 0))
        distance_km = round(float(p.get("distance", 0)) / 1000, 1)

        return {"success": True, "data": {
            "query_type": "traffic",
            "target": target or destination,
            "distance_km": distance_km,
            "duration_min": duration_min,
            "traffic": traffic_desc,
        }}

    # ── 预计到达时间 ──
    if query_type == "eta":
        if not target and not destination:
            return {"success": False, "error": "预计到达时间需要指定目的地"}
        if not destination:
            dest_coord = geocode(target or "")
            if not dest_coord:
                return {"success": False, "error": f"无法解析目标地点: {target}"}
            destination = dest_coord

        data = _amap_get("/direction/driving", {
            "origin": location,
            "destination": destination,
            "strategy": 2,
        })
        if data is None:
            return {"success": False, "error": "高德路径规划失败"}

        route = data.get("route", {})
        paths = route.get("paths", [])
        if not paths:
            return {"success": False, "error": "无可用路径"}

        p = paths[0]
        duration_min = int(round(float(p.get("duration", 0)) / 60, 0))
        distance_km = round(float(p.get("distance", 0)) / 1000, 1)

        return {"success": True, "data": {
            "query_type": "eta",
            "target": target or destination,
            "eta_min": duration_min,
            "distance_km": distance_km,
        }}

    return {"success": False, "error": f"不支持的 query_type: {query_type}"}


# ═══════════════════════════════════════════════════════════════
# Intent 4: weather — 天气查询
# ═══════════════════════════════════════════════════════════════

def weather(
    city: Optional[str] = None,
    date: str = "今天",
    location: Optional[str] = None,
) -> dict:
    """
    对应 intent: weather
    天气查询（高德 /weather/weatherInfo API）。

    Args:
        city: 城市名或 adcode。默认由 harness 从当前位置推断
        date: 查询日期（今天/明天/后天）
        location: 当前位置坐标(lng,lat)，用于推断城市

    Returns:
        {"success": True, "data": {...}}
        {"success": False, "error": str}
    """
    # 城市推断：没有 city 时，从当前位置逆地理编码获取
    if not city:
        if location:
            addr_info = _reverse_geocode(location)
            if addr_info:
                # 高德天气 API 接受城市名或 adcode
                city = addr_info.get("city") or addr_info.get("province", "")
        if not city:
            return {"success": False, "error": "缺少城市信息，请告诉我您想查询哪个城市的天气"}

    # 高德 extensions: base=实况天气, all=预报天气
    extensions = "base" if date in ("今天",) else "all"

    data = _amap_get("/weather/weatherInfo", {
        "city": city,
        "extensions": extensions,
    })
    if data is None:
        return {"success": False, "error": "高德天气 API 请求失败"}

    lives = data.get("lives", [])
    forecasts = data.get("forecasts", [])

    if extensions == "base" and lives:
        w = lives[0]
        result = {
            "city": w.get("city", city),
            "weather": w.get("weather", ""),
            "temperature": w.get("temperature", ""),
            "wind_direction": w.get("winddirection", ""),
            "wind_power": w.get("windpower", ""),
            "humidity": w.get("humidity", ""),
            "date": "今天",
        }
        logger.info(f"[高德] 天气查询 {city}: {result['weather']} {result['temperature']}°C")
        return {"success": True, "data": result}

    if extensions == "all" and forecasts:
        fc = forecasts[0]
        casts = fc.get("casts", [])
        # 根据 date 找对应的预报
        target_date = date
        for c in casts:
            # 高德返回 date 字段，可匹配
            if target_date in ("明天",) and casts:
                c = casts[1] if len(casts) > 1 else casts[0]
            elif target_date in ("后天",) and casts:
                c = casts[2] if len(casts) > 2 else casts[-1]
            else:
                c = casts[0]

            result = {
                "city": fc.get("city", city),
                "weather": c.get("dayweather", ""),
                "temperature_lo": c.get("nighttemp", ""),
                "temperature_hi": c.get("daytemp", ""),
                "wind_direction": c.get("daywind", ""),
                "wind_power": c.get("daypower", ""),
                "date": target_date,
            }
            logger.info(f"[高德] 天气预报 {city}: {result['weather']} {result['temperature_lo']}~{result['temperature_hi']}°C")
            return {"success": True, "data": result}

    return {"success": False, "error": f"未找到{city}的天气信息"}
