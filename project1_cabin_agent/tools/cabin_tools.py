"""
project1_cabin_agent/tools/cabin_tools.py
车载工具集（三层架构版）

Layer 1: 原子函数（不暴露给 LLM，直接操作 vehicle_state）
Layer 2: 领域工具（暴露给 LLM，@tool 注册，带反射元信息 docstring）
Layer 3: 场景联动（内部编排 Layer 1 原子函数）
"""

from pathlib import Path
import yaml
from langchain_core.tools import tool
from project1_cabin_agent.vehicle_state import vehicle_state

# ── mock 数据加载 ──
_MOCK_DATA_PATH = Path(__file__).parent.parent / "vehicle_mock_data.yaml"
_mock_data: dict = {}
if _MOCK_DATA_PATH.exists():
    with open(_MOCK_DATA_PATH, "r", encoding="utf-8") as f:
        _mock_data = yaml.safe_load(f) or {}

# 类别 → YAML section 映射
_CATEGORY_MAP = {
    "餐饮": "restaurants",
    "餐厅": "restaurants",
    "小吃": "restaurants",
    "美食": "restaurants",
    "饭店": "restaurants",
    "火锅": "restaurants",
    "酒店": "hotels",
    "住宿": "hotels",
    "宾馆": "hotels",
    "旅馆": "hotels",
    "景点": "attractions",
    "旅游": "attractions",
    "公园": "attractions",
    "名胜": "attractions",
    "景区": "attractions",
    "加油站": "gas_stations",
    "加油": "gas_stations",
    "加油站的": "gas_stations",
    "医院": "hospitals",
    "诊所": "hospitals",
    "停车场": "parking",
    "停车": "parking",
    "车位": "parking",
}

# keyword → category 推断
_KEYWORD_CATEGORY = {
    "餐厅": "restaurants",
    "饭店": "restaurants",
    "美食": "restaurants",
    "小吃": "restaurants",
    "火锅": "restaurants",
    "烤鸭": "restaurants",
    "酒店": "hotels",
    "宾馆": "hotels",
    "住宿": "hotels",
    "景点": "attractions",
    "公园": "attractions",
    "景区": "attractions",
    "加油站": "gas_stations",
    "加油": "gas_stations",
    "医院": "hospitals",
    "急诊": "hospitals",
    "停车场": "parking",
    "停车": "parking",
}


def _search_mock_pois(keyword: str, category: str = None, limit: int = 3) -> list:
    """从 YAML mock 数据搜索 POI，按距离排序返回 top N"""
    results = []

    # 搜索范围：所有 POI 类别的 section
    _all_sections = [
        "restaurants",
        "hotels",
        "attractions",
        "gas_stations",
        "hospitals",
        "parking",
    ]

    # 1. keyword 直接匹配 name/address
    for section in _all_sections:
        for poi in _mock_data.get(section, []):
            if keyword in poi.get("name", "") or keyword in poi.get("address", ""):
                results.append(poi)

    # 2. 如果没匹配到，尝试按 category 映射
    if not results:
        sec = None
        if category:
            sec = _CATEGORY_MAP.get(category)
        elif keyword in _KEYWORD_CATEGORY:
            sec = _KEYWORD_CATEGORY[keyword]
        if sec:
            results = list(_mock_data.get(sec, []))

    # 按距离排序
    results.sort(key=lambda x: x.get("distance_km", 999))
    return results[:limit]


def _find_route(destination: str) -> dict | None:
    """从 YAML mock 数据匹配目的地，返回 route 信息"""
    _all_sections = [
        "restaurants",
        "hotels",
        "attractions",
        "gas_stations",
        "hospitals",
        "parking",
    ]
    for section in _all_sections:
        for poi in _mock_data.get(section, []):
            if destination in poi.get("name", "") or destination in poi.get(
                "address", ""
            ):
                return {
                    "name": poi["name"],
                    "eta": f"{poi.get('eta_minutes', '?')}分钟",
                    "distance": f"{poi.get('distance_km', '?')}km",
                    "traffic": poi.get("traffic", "未知"),
                    "address": poi.get("address", ""),
                }
    return None


# ═══════════════════════════════════════════════════════════════
# Layer 1: 原子函数
# ═══════════════════════════════════════════════════════════════


def _set_ac_state(on=None, temp=None, mode=None, fan_level=None):
    updates = {}
    if on is not None:
        updates["ac_on"] = on
    if temp is not None:
        updates["ac_temp"] = max(16, min(32, temp))
    if mode is not None:
        updates["ac_mode"] = mode
    if fan_level is not None:
        updates["ac_fan_level"] = max(1, min(5, fan_level))
    vehicle_state.update(updates)


def _set_window_state(target, percent):
    key = "sunroof_percent" if target == "sunroof" else "window_percent"
    vehicle_state.update({key: max(0, min(100, percent))})


def _set_door_state(open_):
    vehicle_state.update({"door_open": open_})


def _window_control_execute(slots: dict, tool_result: dict) -> dict:
    """确认后执行车窗/车门开启。由 TOOL_REGISTRY["window_control"]["confirmed_execute"] 引用。"""
    tool_result = tool_result or {}
    target = slots.get("target", "")
    names = {"window": "车窗", "sunroof": "天窗", "door": "车门"}
    name = names.get(target, target)
    if target == "door":
        _set_door_state(True)
    else:
        p = tool_result.get("percent", slots.get("percent", 100))
        _set_window_state(target, p)
    return {"status": "success", "voice_reply": f"好的，已打开{name}"}


def _set_seat_state(heat_level=None, ventilate=None):
    updates = {}
    if heat_level is not None:
        updates["seat_heat_level"] = max(0, min(3, heat_level))
    if ventilate is not None:
        updates["seat_ventilate"] = ventilate
    vehicle_state.update(updates)


def _set_media_state(playing=None, track=None, source=None):
    updates = {}
    if playing is not None:
        updates["music_playing"] = playing
    if track is not None:
        updates["music_track"] = track
    if source is not None:
        updates["music_source"] = source
    vehicle_state.update(updates)


def _set_volume(level):
    vehicle_state.update({"volume": max(0, min(100, level))})


def _set_light_state(on=None, brightness=None):
    updates = {}
    if on is not None:
        updates["light_on"] = on
    if brightness is not None:
        updates["light_brightness"] = max(0, min(100, brightness))
    vehicle_state.update(updates)


# ═══════════════════════════════════════════════════════════════
# Layer 2: 领域工具（9个）
# ═══════════════════════════════════════════════════════════════


@tool
async def ac_control(
    action: str, temperature: float = None, mode: str = None, fan_level: int = None
) -> dict:
    """
    空调控制，调节车内温度、模式和风速。
    :param action: on/off/adjust
    :param temperature: 目标温度 16-32，必须是具体数字(如22.0)，禁止填"lower""higher"等文字
    :param mode: cool/heat/auto
    :param fan_level: 风速档位 1-5
    :example: "打开空调" → action=on
    :example: "调到22度" → action=adjust, temperature=22
    :example: "我有点冷" → action=on, temperature=由当前车内温度推断, mode=heat
    :anti_example: "声音大一点" → 不是空调，是 media_control
    :anti_example: "开窗" → 不是空调，是 window_control
    :implicit_map: "有点冷"→action=on,temperature=由当前车内温度推断,mode=heat
    :implicit_map: "太热了"→action=on,temperature=由当前车内温度推断,mode=cool
    :risk_level: normal
    """
    if action == "on":
        _set_ac_state(on=True, temp=temperature, mode=mode, fan_level=fan_level)
        t = temperature or vehicle_state.ac_temp
        return {"status": "success", "voice_reply": f"好的，已打开空调，{t}度"}
    elif action == "off":
        _set_ac_state(on=False)
        return {"status": "success", "voice_reply": "好的，已关闭空调"}
    elif action == "adjust":
        _set_ac_state(temp=temperature, mode=mode, fan_level=fan_level)
        parts = []
        if temperature:
            parts.append(f"温度调到{temperature}度")
        if mode:
            parts.append(f"模式调为{mode}")
        if fan_level:
            parts.append(f"风速调到{fan_level}档")
        return {
            "status": "success",
            "voice_reply": f"好的，{'，'.join(parts) if parts else '已调整'}",
        }
    return {"status": "success", "voice_reply": "好的"}


@tool
async def window_control(target: str, action: str, percent: int = None) -> dict:
    """
    车窗/天窗/车门控制。
    :param target: window/sunroof/door
    :param action: open/close/adjust
    :param percent: 开合百分比 0-100（可选，不传时：open=100, close=0）
    :example: "开窗" → target=window, action=open
    :example: "开一半" → target=window, action=open, percent=50
    :example: "开一点" → target=window, action=open, percent=20
    :example: "关窗" → target=window, action=close
    :example: "开门" → target=door, action=open
    :example: "天窗开一半" → target=sunroof, action=open, percent=50
    :anti_example: "声音大一点" → 不是车窗，是 media_control
    :risk_level: high
    """
    names = {"window": "车窗", "sunroof": "天窗", "door": "车门"}
    name = names.get(target, target)

    if target == "door":
        if vehicle_state.speed > 0:
            return {
                "status": "blocked",
                "voice_reply": f"行驶中无法操作{name}，请停车后操作",
            }
        if action == "open":
            return {"status": "need_confirm", "voice_reply": f"确认要打开{name}吗？"}
        _set_door_state(False)
        return {"status": "success", "voice_reply": f"好的，已关闭{name}"}

    if action == "open":
        p = percent if percent is not None else 100
        return {
            "status": "need_confirm",
            "voice_reply": f"确认要打开{name}吗？",
            "percent": p,
        }
    elif action == "close":
        _set_window_state(target, 0)
        return {"status": "success", "voice_reply": f"好的，已关闭{name}"}
    elif action == "adjust":
        p = percent if percent is not None else 50
        _set_window_state(target, p)
        return {"status": "success", "voice_reply": f"好的，{name}已调到{p}%"}
    return {"status": "success", "voice_reply": "好的"}


@tool
async def seat_control(action: str, heat_level: int = None) -> dict:
    """
    座椅控制，加热或通风。
    :param action: heat_on/heat_off/ventilate_on/ventilate_off
    :param heat_level: 加热档位 1-3
    :example: "开座椅加热" → action=heat_on, heat_level=2
    :anti_example: "开空调" → 不是座椅，是 ac_control
    :risk_level: normal
    """
    if action == "heat_on":
        lv = heat_level or 2
        _set_seat_state(heat_level=lv)
        return {"status": "success", "voice_reply": f"好的，已开启座椅加热{lv}档"}
    elif action == "heat_off":
        _set_seat_state(heat_level=0)
        return {"status": "success", "voice_reply": "好的，已关闭座椅加热"}
    elif action == "ventilate_on":
        _set_seat_state(ventilate=True)
        return {"status": "success", "voice_reply": "好的，已开启座椅通风"}
    elif action == "ventilate_off":
        _set_seat_state(ventilate=False)
        return {"status": "success", "voice_reply": "好的，已关闭座椅通风"}
    return {"status": "success", "voice_reply": "好的"}


@tool
async def media_control(
    action: str, query: str = None, source: str = None, volume: int = None
) -> dict:
    """
    媒体与音量控制，播放/暂停/切歌/搜索/音量调节。
    :param action: play/pause/next/previous/search/volume_up/volume_down/set_volume
    :param query: 搜索关键词（action=search 时）
    :param source: 音乐来源
    :param volume: 音量值 0-100（action=set_volume 时）
    :example: "放音乐" → action=play
    :example: "声音大一点" → action=volume_up
    :example: "换一首" → action=next
    :example: "播放周杰伦" → action=search, query=周杰伦
    :anti_example: "调到22度" → 不是媒体，是 ac_control
    :implicit_map: "有点吵"→action=volume_down
    :risk_level: normal
    """
    if action == "play":
        _set_media_state(playing=True, source=source)
        return {"status": "success", "voice_reply": "好的，开始播放音乐"}
    elif action == "pause":
        _set_media_state(playing=False)
        return {"status": "success", "voice_reply": "好的，已暂停音乐"}
    elif action == "next":
        return {"status": "success", "voice_reply": "好的，已切换到下一首"}
    elif action == "previous":
        return {"status": "success", "voice_reply": "好的，已切换到上一首"}
    elif action == "search":
        _set_media_state(playing=True, track=query, source=source)
        return {"status": "success", "voice_reply": f"好的，正在播放{query}"}
    elif action == "volume_up":
        v = min(100, vehicle_state.volume + 10)
        _set_volume(v)
        return {"status": "success", "voice_reply": f"好的，音量调到{v}"}
    elif action == "volume_down":
        v = max(0, vehicle_state.volume - 10)
        _set_volume(v)
        return {"status": "success", "voice_reply": f"好的，音量调到{v}"}
    elif action == "set_volume":
        v = volume if volume is not None else 50
        _set_volume(v)
        return {"status": "success", "voice_reply": f"好的，音量调到{v}"}
    return {"status": "success", "voice_reply": "好的"}


@tool
async def light_control(
    action: str, target: str = None, brightness: int = None
) -> dict:
    """
    车内灯光控制。
    :param action: on/off/adjust
    :param target: cabin/reading/ambient
    :param brightness: 亮度 0-100
    :example: "开灯" → action=on
    :example: "关阅读灯" → action=off, target=reading
    :example: "调暗一点" → action=adjust, brightness=30
    :anti_example: "声音大一点" → 不是灯光，是 media_control
    :implicit_map: "看不清楚"→action=on
    :risk_level: normal
    """
    if action == "on":
        _set_light_state(on=True, brightness=brightness)
        return {"status": "success", "voice_reply": "好的，已打开车灯"}
    elif action == "off":
        _set_light_state(on=False)
        return {"status": "success", "voice_reply": "好的，已关闭车灯"}
    elif action == "adjust":
        b = brightness if brightness is not None else 50
        _set_light_state(brightness=b)
        return {"status": "success", "voice_reply": f"好的，灯光亮度调到{b}%"}
    return {"status": "success", "voice_reply": "好的"}


@tool
async def search_poi(
    keyword: str, category: str = None, radius: float = 5.0, limit: int = 3
) -> dict:
    """
    搜索周边兴趣点。
    :param keyword: 搜索关键词，如"餐厅"、"酒店"、"故宫"、"加油站"
    :param category: 类别过滤（餐饮/酒店/景点）
    :param radius: 搜索半径（公里）
    :param limit: 返回数量
    :example: "附近有餐厅吗" → keyword=餐厅
    :example: "好饿" → keyword=餐厅
    :example: "想去看故宫" → keyword=故宫
    :implicit_map: "好饿"→keyword=餐厅
    :implicit_map: "要加油"→keyword=加油站
    :implicit_map: "想住酒店"→keyword=酒店
    :risk_level: normal
    """
    pois = _search_mock_pois(keyword, category, limit)

    if pois:
        formatted = []
        for p in pois:
            info = {"name": p["name"], "distance": f"{p.get('distance_km', '?')}km"}
            if "rating" in p:
                info["rating"] = p["rating"]
            if "avg_price" in p:
                info["avg_price"] = f"¥{p['avg_price']}/人"
            if "price" in p:
                info["price"] = f"¥{p['price']}/晚"
            if "ticket" in p:
                info["ticket"] = p["ticket"]
            formatted.append(info)

        first = pois[0]
        dist = f"{first.get('distance_km', '?')}km"
        reply = f"找到{len(pois)}个结果，最近的是{first['name']}，距您{dist}"
        if "rating" in first:
            reply += f"，评分{first['rating']}"
        return {
            "status": "success",
            "keyword": keyword,
            "results": formatted,
            "voice_reply": reply,
        }

    # fallback：mock 数据中没有的
    fallback = [{"name": f"宏扬{keyword}（模拟数据）", "distance": "1.0km"}]
    return {
        "status": "success",
        "keyword": keyword,
        "results": fallback,
        "voice_reply": f"找到1个{keyword}，距您1.0km",
    }


@tool
async def navigate(destination: str, route_type: str = None) -> dict:
    """
    开启导航到目的地。
    :param destination: 目的地名称或地址，如"故宫"、"王府井"、"全聚德"
    :param route_type: 路线偏好 fastest/shortest/avoid_highway/avoid_toll
    :example: "导航去故宫" → destination=故宫
    :example: "去鸟巢" → destination=鸟巢
    :example: "去全聚德" → destination=全聚德
    :risk_level: normal
    """
    route = _find_route(destination)

    if route:
        return {
            "status": "success",
            "destination": route["name"],
            "route": {
                "eta": route["eta"],
                "distance": route["distance"],
                "traffic": route["traffic"],
                "address": route.get("address", ""),
            },
            "voice_reply": f"已规划路线，前往{route['name']}，预计{route['eta']}，全程{route['distance']}，路况{route['traffic']}",
        }

    # fallback
    default_route = {"eta": "未知", "distance": "未知", "traffic": "未知"}
    return {
        "status": "success",
        "destination": destination,
        "route": default_route,
        "voice_reply": f"已规划路线，前往{destination}，路线信息加载中",
    }


@tool
async def query_vehicle_status(items: str) -> dict:
    """
    查询车辆状态信息。
    :param items: 查询项目 fuel/battery/tire/mileage/temperature(车内温度)/ac_temp(空调设定温度)/speed
    :example: "还有多少油" → items=fuel
    :example: "电池电量" → items=battery
    :example: "空调多少度" → items=ac_temp
    :example: "车内温度" → items=temperature
    :risk_level: normal
    """
    status = vehicle_state.to_mock_status()
    info = status.get(items, {"value": "未知", "voice": f"暂时无法获取{items}信息"})
    return {
        "status": "success",
        "system": items,
        "value": info["value"],
        "voice_reply": info["voice"],
    }


@tool
async def activate_scene(scene_name: str) -> dict:
    """
    场景联动，一键触发多个设备操作。
    :param scene_name: 场景名称 comfortable_driving/sleep_mode/departure_check
    :example: "舒适驾驶模式" → scene_name=comfortable_driving
    :example: "休息模式" → scene_name=sleep_mode
    :implicit_map: "我有点冷"→scene_name=comfortable_driving
    :risk_level: normal
    """
    actions = []
    if scene_name == "comfortable_driving":
        _set_ac_state(on=True, temp=24, mode="auto", fan_level=2)
        _set_media_state(playing=True, source="轻音乐")
        _set_seat_state(heat_level=1)
        actions = ["空调24度自动模式", "播放轻音乐", "座椅加热1档"]
    elif scene_name == "sleep_mode":
        _set_ac_state(on=True, temp=25, mode="auto", fan_level=1)
        _set_light_state(on=False)
        _set_media_state(playing=False)
        actions = ["空调25度低风", "关闭车灯", "暂停音乐"]
    elif scene_name == "departure_check":
        status = vehicle_state.to_mock_status()
        actions = [
            status.get(i, {}).get("voice", i) for i in ["fuel", "battery", "tire"]
        ]
    else:
        return {"status": "success", "voice_reply": f"未知场景: {scene_name}"}
    return {
        "status": "success",
        "scene": scene_name,
        "voice_reply": f"已激活{scene_name}：{'；'.join(actions)}",
    }


# ═══════════════════════════════════════════════════════════════
# 注册表
# ═══════════════════════════════════════════════════════════════

ALL_TOOLS = [
    ac_control,
    window_control,
    seat_control,
    media_control,
    light_control,
    search_poi,
    navigate,
    query_vehicle_status,
    activate_scene,
]

# ── 黑板实体声明 ──
# produces: 工具产出什么实体标签（写入黑板）
# consumes: 工具消费什么实体标签（从黑板取值）
# fields:  产出实体包含哪些字段（消费者可按名取用）
# slots:   消费者的哪个参数 ← 取实体的哪个字段  {slot_name: field_name}
BLACKBOARD_DECLS = {
    "search_poi": {
        "produces": "entity.poi",  # 唯一标签，供后续工具查询使用
        "fields": ["name", "distance", "rating", "avg_price", "price", "ticket"],
    },
    "navigate": {
        "produces": "entity.route",
        "fields": ["destination", "eta", "distance", "traffic"],
        "consumes": "entity.poi",
        "slots": {"destination": "name"},
    },
    "weather": {
        "produces": "entity.weather",
        "fields": ["city", "weather", "temperature"],
    },
}

# @tool 让函数有 `.name` 属性，可以统一放到字典里管理。task_pipeline 通过 `TOOL_REGISTRY.get(tool_name)` 按名字查找
TOOL_REGISTRY = {
    t.name: {
        "function": t,
        "description": t.__doc__.strip() if t.__doc__ else "",
        "blackboard": BLACKBOARD_DECLS.get(t.name),
    }
    for t in ALL_TOOLS
}
# 高风险工具：注册确认后执行函数。新增高风险工具只加这一行。
TOOL_REGISTRY["window_control"]["confirmed_execute"] = _window_control_execute


INTENT_TO_TOOL = {t.name: t.name for t in ALL_TOOLS}
INTENT_TO_TOOL["chitchat"] = "chitchat"
INTENT_TO_TOOL["clarify"] = "clarify"
