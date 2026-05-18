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

# 每个 slot spec 含 required 标记（单一真相源，不再维护独立 INTENT_REQUIRED_SLOTS 表）
# required=True 的 slot 全空 → is_acceptable=False → 降级云端
INTENT_SCHEMAS = {
    "climate": {
        "ac_control": {
            "desc": "空调控制，开关/调温/调风",
            "slots": {
                "action":    {"type": "enum",   "values": ["on", "off", "adjust"], "desc": "操作", "required": False},
                "temperature": {"type": "number", "range": [16, 32], "desc": "目标温度", "required": False},
                "mode":      {"type": "enum",   "values": ["cool", "heat", "auto"], "desc": "模式", "required": False},
                "fan_level": {"type": "number", "range": [1, 5], "desc": "风速档位", "required": False},
            },
        },
        "window_control": {
            "desc": "车窗/天窗/车门控制",
            "slots": {
                "target": {"type": "enum", "values": ["window", "sunroof", "door"], "desc": "控制对象", "required": False},
                "action":   {"type": "enum",   "values": ["open", "close", "adjust"], "desc": "操作", "required": True},
                "percent": {"type": "number", "range": [0, 100], "desc": "开合百分比", "required": False},
            },
        },
        "seat_control": {
            "desc": "座椅加热/通风",
            "slots": {
                "action": {"type": "enum", "values": ["heat_on", "heat_off", "ventilate_on", "ventilate_off"], "desc": "操作", "required": True},
                "heat_level": {"type": "number", "range": [1, 3], "desc": "加热档位", "required": False},
            },
        },
        "light_control": {
            "desc": "灯光控制",
            "slots": {
                "action": {"type": "enum", "values": ["on", "off", "adjust"], "desc": "操作", "required": True},
                "target": {"type": "enum", "values": ["cabin", "reading", "ambient"], "desc": "灯光类型", "required": False},
                "brightness": {"type": "number", "range": [0, 100], "desc": "亮度", "required": False},
            },
        },
    },
    "navigation": {
        "start_navigation": {
            "desc": "导航到目的地",
            "slots": {
                "destination": {"type": "string", "desc": "目的地名称", "required": True},
                "mode": {"type": "enum", "values": ["fastest", "shortest", "avoid_highway", "avoid_toll"], "desc": "路线偏好", "required": False},
            },
        },
    },
    "media": {
        "media_control": {
            "desc": "音乐播放/暂停/切歌",
            "slots": {
                "action": {"type": "enum", "values": ["play", "pause", "next", "previous", "search", "volume_up", "volume_down", "set_volume"], "desc": "操作", "required": True},
                "query": {"type": "string", "desc": "搜索关键词(歌名/歌手)", "required": False},
                "volume": {"type": "number", "range": [0, 100], "desc": "音量", "required": False},
            },
        },
    },
    "search": {
        "search_poi": {
            "desc": "搜索附近POI",
            "slots": {
                "keyword": {"type": "string", "desc": "搜索关键词", "required": True},
            },
        },
    },
    "vehicle": {
        "query_vehicle_status": {
            "desc": "查询车况(油量/胎压/续航等)",
            "slots": {
                "items": {"type": "string", "desc": "查询项目(fuel/tire/ac_temp等)", "required": False},
            },
        },
        "activate_scene": {
            "desc": "场景模式(舒适/休息等)",
            "slots": {
                "scene_name": {"type": "enum", "values": ["comfortable_driving", "sleep_mode", "departure_check"], "desc": "场景名", "required": True},
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
            # 尝试转换字符串为数字（端侧LLM常输出 '26' 而非 26）
            if isinstance(value, str):
                try:
                    value = int(value)
                except ValueError:
                    try:
                        value = float(value)
                    except ValueError:
                        continue
            if not isinstance(value, (int, float)):
                continue
            lo, hi = s.get("range", [0, 9999])
            if not (lo <= value <= hi):
                continue
        elif stype == "enum":
            v = str(value)
            # 先尝试中文值映射（端侧LLM常输出中文如'开'→'on'）
            mapped = _CN_VALUE_MAP.get(v)
            if mapped is not None:
                v = mapped
            # 再尝试英文字段映射（如模型输出 "on" → 工具要 "open"）
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

# ═══════════════════════════════════════════════════
# Key 别名映射：端侧 3B 模型常见输出 → 白名单合法 key
# ═══════════════════════════════════════════════════

_KEY_ALIAS = {
    # climate
    "light": "action",        # 灯光控制时输出 {'light': '开'}
    "seat": "action",         # 座椅控制时输出 {'seat': '座椅加热'}
    "fan_level": "fan_level", # 一致
    "temp": "temperature",
    # media
    "artist": "query",        # {'artist': '周杰伦'} → {'query': '周杰伦'}
    "song": "query",
    "volume_level": "action", # {'volume_level': '大一点'} → {'action': 'volume_up'} 需值映射
    # vehicle
    "check_type": "items",
    "status": "items",
}

_CN_VALUE_MAP = {
    # 中文值 → 英文 enum 值（端侧 3B 模型常见输出）
    "开": "on", "打开": "on", "开启": "on",
    "关": "off", "关闭": "off", "关掉": "off",
    "调高": "adjust", "调低": "adjust", "调节": "adjust",
    "暂停": "pause", "停止": "pause",
    "下一首": "next", "切歌": "next",
    "上一首": "previous",
    "播放": "play", "放": "play",
    "加热": "heat_on",
    "通风": "ventilate_on",
    # P1: 音量调节中文值 → media_control action enum
    "调小": "volume_down", "调小点": "volume_down", "小一点": "volume_down",
    "调大": "volume_up", "调大点": "volume_up", "大一点": "volume_up",
}

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


def get_required_slots(intent: str) -> list[str]:
    """从 INTENT_SCHEMAS 自动提取 required=True 的 slot key（单一真相源）"""
    for domain_schemas in INTENT_SCHEMAS.values():
        intent_schema = domain_schemas.get(intent)
        if intent_schema:
            return [
                key for key, spec in intent_schema.get("slots", {}).items()
                if spec.get("required")
            ]
    return []
