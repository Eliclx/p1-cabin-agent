"""
project1_cabin_agent/edge_schemas.py
端侧两阶段 Schema 定义 — 单一真相源

同时用于：
1. 生成 Stage 1 domain 分类 prompt
2. 生成 Stage 2 intent + slot 提取 prompt
3. Stage 3 白名单校验（后置过滤）
"""

# ── Domain 定义 ──

DOMAINS = {
    "climate": {
        "label": "车内环境",
        "keywords": "空调 温度 车窗 座椅 热 冷 闷 风速 开空调 关空调 开窗 关窗 座椅加热 调高 调低 暖 冷 灯 灯光 开灯 关灯 暗 亮 副驾 加热档",
    },
    "navigation": {
        "label": "导航",
        "keywords": "导航 去 怎么走 路线 出发 回家 公司 到 开往",
    },
    "media": {
        "label": "媒体",
        "keywords": "播放 放歌 来首 音乐 音量 下一首 切歌 暂停 继续 听歌 歌 声音",
    },
    "search": {
        "label": "搜索",
        "keywords": "附近 有没有 哪里 搜 找 加油站 餐厅 厕所 停车场 洗车",
    },
    "vehicle": {
        "label": "车况查询",
        "keywords": "多少油 胎压 保养 故障 续航 油箱 剩余 空调几度 车速 舒适 休息 模式 场景",
    },
    "chitchat": {
        "label": "闲聊",
        "keywords": "你好 嗨 笑话 聊天 谢谢 天气 无聊 几点 谁",
    },
}

DOMAIN_NAMES = list(DOMAINS.keys())

# ── Intent + Slot Schema ──
# 每个 domain 下可执行的 intent，含 slot 白名单

INTENT_SCHEMAS = {
    "climate": {
        "ac_control": {
            "desc": "空调控制，开关/调温/调风",
            "slots": {
                "action":    {"type": "enum",   "values": ["on", "off", "adjust"], "desc": "操作"},
                "temperature": {"type": "number", "range": [16, 32], "desc": "目标温度"},
                "mode":      {"type": "enum",   "values": ["cool", "heat", "auto"], "desc": "模式"},
                "fan_level": {"type": "number", "range": [1, 5], "desc": "风速档位"},
            },
        },
        "window_control": {
            "desc": "车窗/天窗/车门控制",
            "slots": {
                "target": {"type": "enum", "values": ["window", "sunroof", "door"], "desc": "控制对象"},
                "action":   {"type": "enum",   "values": ["open", "close", "adjust"], "desc": "操作"},
                "percent": {"type": "number", "range": [0, 100], "desc": "开合百分比"},
            },
        },
        "seat_control": {
            "desc": "座椅加热/通风",
            "slots": {
                "action": {"type": "enum", "values": ["heat_on", "heat_off", "ventilate_on", "ventilate_off"], "desc": "操作"},
                "heat_level": {"type": "number", "range": [1, 3], "desc": "加热档位"},
            },
        },
        "light_control": {
            "desc": "灯光控制",
            "slots": {
                "action": {"type": "enum", "values": ["on", "off", "adjust"], "desc": "操作"},
                "target": {"type": "enum", "values": ["cabin", "reading", "ambient"], "desc": "灯光类型"},
                "brightness": {"type": "number", "range": [0, 100], "desc": "亮度"},
            },
        },
    },
    "navigation": {
        "start_navigation": {
            "desc": "导航到目的地",
            "slots": {
                "destination": {"type": "string", "desc": "目的地名称"},
                "mode": {"type": "enum", "values": ["fastest", "shortest", "avoid_highway", "avoid_toll"], "desc": "路线偏好"},
            },
        },
    },
    "media": {
        "media_control": {
            "desc": "音乐播放/暂停/切歌",
            "slots": {
                "action": {"type": "enum", "values": ["play", "pause", "next", "previous", "search", "volume_up", "volume_down", "set_volume"], "desc": "操作"},
                "query": {"type": "string", "desc": "搜索关键词(歌名/歌手)"},
                "volume": {"type": "number", "range": [0, 100], "desc": "音量"},
            },
        },
    },
    "search": {
        "search_poi": {
            "desc": "搜索附近POI",
            "slots": {
                "keyword": {"type": "string", "desc": "搜索关键词"},
            },
        },
    },
    "vehicle": {
        "query_vehicle_status": {
            "desc": "查询车况(油量/胎压/续航等)",
            "slots": {
                "items": {"type": "string", "desc": "查询项目(fuel/tire/ac_temp等)"},
            },
        },
        "activate_scene": {
            "desc": "场景模式(舒适/休息等)",
            "slots": {
                "scene_name": {"type": "enum", "values": ["comfortable_driving", "sleep_mode", "departure_check"], "desc": "场景名"},
            },
        },
    },
}


def get_allowed_slot_keys(domain: str, intent: str) -> set:
    """获取某个 intent 允许的 slot key 集合（白名单）"""
    domain_schemas = INTENT_SCHEMAS.get(domain, {})
    intent_schema = domain_schemas.get(intent, {})
    return set(intent_schema.get("slots", {}).keys())


def validate_slots(domain: str, intent: str, slots: dict) -> dict:
    """白名单校验：过滤幻觉 key + 类型/范围校验 + 值映射"""
    domain_schemas = INTENT_SCHEMAS.get(domain, {})
    intent_schema = domain_schemas.get(intent, {})
    slot_schemas = intent_schema.get("slots", {})
    if not slot_schemas:
        return {}

    result = {}
    for key, value in slots.items():
        if key not in slot_schemas:
            continue
        s = slot_schemas[key]
        stype = s.get("type")

        if stype == "number":
            if not isinstance(value, (int, float)):
                continue
            lo, hi = s.get("range", [0, 9999])
            if not (lo <= value <= hi):
                continue
        elif stype == "enum":
            v = str(value)
            # 先尝试值映射（如模型输出 "on" → 工具要 "open"）
            mapped = _VALUE_MAP.get((domain, intent, key, v))
            if mapped is not None:
                v = mapped
            if v not in s.get("values", []):
                continue
            value = v
        elif stype == "string":
            if not isinstance(value, str):
                continue
        result[key] = value
    return result


# ═══════════════════════════════════════════════════
# 值映射表：模型常用术语 → 工具期望术语
# 格式: (domain, intent, slot_key, model_value) → tool_value
# ═══════════════════════════════════════════════════

_VALUE_MAP = {
    # window_control: 模型习惯输出 on/off，工具要 open/close
    ("climate", "window_control", "action", "on"): "open",
    ("climate", "window_control", "action", "off"): "close",
    # seat_control: 模型习惯输出 on/off，工具要 heat_on/heat_off
    ("climate", "seat_control", "action", "on"): "heat_on",
    ("climate", "seat_control", "action", "off"): "heat_off",
    # light_control: on/off 一致，不需要映射
    # ac_control: on/off 一致，不需要映射
}
