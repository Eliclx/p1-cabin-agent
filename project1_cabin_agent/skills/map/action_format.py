"""
project1_cabin_agent/skills/map/action_format.py — Map 域 action 转换
"""

from __future__ import annotations

from project1_cabin_agent.actions.models import CabinAction


def format_navigate(tool_result: dict) -> CabinAction | None:
    if not tool_result.get("success"):
        return None
    data = tool_result.get("data", {})
    return CabinAction(domain="map", intent="navigate", command="start_nav", params={
        "distance_km": data.get("distance"),
        "duration_min": data.get("duration"),
        "tolls": data.get("tolls"),
        "route_text": data.get("route_text"),
    })


def format_search_poi(tool_result: dict) -> CabinAction | None:
    if not tool_result.get("success"):
        return None
    data = tool_result.get("data", {})
    results = data.get("results", [])
    return CabinAction(domain="map", intent="search_poi", command="search_poi", params={
        "count": data.get("count", 0),
        "top_result": results[0] if results else None,
    })


def format_weather(tool_result: dict) -> CabinAction | None:
    if not tool_result.get("success"):
        return None
    data = tool_result.get("data", {})
    return CabinAction(domain="map", intent="weather", command="weather_query", params={
        "city": data.get("city", ""),
        "weather": data.get("weather", ""),
        "temperature": data.get("temperature", ""),
        "date": data.get("date", "今天"),
    })


def format_map_query(tool_result: dict) -> CabinAction | None:
    if not tool_result.get("success"):
        return None
    return CabinAction(domain="map", intent="map_query", command="map_query",
                       params=tool_result.get("data", {}))


# ── 导出 ──

MAP_ACTION_FORMATTERS = {
    "navigate": format_navigate,
    "search_poi": format_search_poi,
    "weather": format_weather,
    "map_query": format_map_query,
}
