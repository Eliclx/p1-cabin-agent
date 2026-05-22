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
    "map": {
        "label": "地图与位置",
        "keywords": "导航 去 怎么走 路线 出发 回家 公司 到 开往 附近 有没有 哪里 搜 找 加油站 餐厅 厕所 停车场 洗车 地图 天气 下雨 晴 多云 温度 多少度",
    },
    "media": {
        "label": "媒体",
        "keywords": "播放 放歌 来首 音乐 音量 下一首 切歌 暂停 继续 听歌 歌 声音",
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
#
# 每个 slot spec 含 required 标记（单一真相源，不再维护独立 INTENT_REQUIRED_SLOTS 表）
# required=True 的 slot 全空 → is_acceptable=False → 降级云端
#
# 由 _build_intent_schemas() 从 SkillRegistry 动态生成


def _build_intent_schemas() -> dict:
    """从 SkillRegistry 动态构建 INTENT_SCHEMAS。

    转换规则:
    1. type="string" + enum → {"type": "enum", "values": [...]}
    2. type="number"/"integer" + minimum/maximum → {"type": "number", "range": [min, max]}
    3. type="string" 无 enum → {"type": "string"}
    4. anyOf 结构: 从 anyOf[0]（非null分支）提取实际类型
    5. required 判断: 无 default 且 anyOf 中无 null → True
    """
    from project1_cabin_agent.skills.registry import registry

    # 需要 skip 的 (domain, intent) 组合：
    # （原 navigation/search_poi 与 search/search_poi 重复已合并到 map，无需 skip）
    _SKIP_INTENTS: set[tuple[str, str]] = set()

    # slot 名映射：registry 名 → edge_schemas 名（兼容旧格式）
    # map 域的 navigate intent，旧 prompt 用 mode → 新 schema 用 route_type
    _SLOT_NAME_MAP = {
        ("map", "navigate", "route_type"): "mode",
    }

    # intent 名映射：registry 名 → edge_schemas 名
    _INTENT_NAME_MAP = {
        # 旧名 start_navigation → navigate（registry _INTENT_ALIASES 兼容）
    }

    # 额外 slot 需要 skip 的（不导出到 edge schema）
    # map 域 navigate 的 origin 自动补全，不需要 LLM 填
    _SKIP_SLOTS = {
        ("map", "navigate", "origin"),
    }

    schemas: dict[str, dict] = {}

    for domain, intent_list in registry.get_all_intents().items():
        for intent_name in intent_list:
            # skip 重复
            if (domain, intent_name) in _SKIP_INTENTS:
                continue

            spec = registry.get_intent_spec(intent_name)
            if spec is None:
                continue

            # 最终 intent 名
            final_intent = _INTENT_NAME_MAP.get((domain, intent_name), intent_name)

            # 构建 slots
            slots: dict[str, dict] = {}
            for slot_name, slot_def in spec.slots.items():
                # skip 不需要的 slot
                if (domain, intent_name, slot_name) in _SKIP_SLOTS:
                    continue

                # 最终 slot 名
                final_slot = _SLOT_NAME_MAP.get(
                    (domain, intent_name, slot_name), slot_name
                )

                slots[final_slot] = _convert_slot(slot_def)

            # 写入 schemas
            if domain not in schemas:
                schemas[domain] = {}
            schemas[domain][final_intent] = {
                "desc": spec.description,
                "slots": slots,
            }

    return schemas


def _convert_slot(slot_def: dict) -> dict:
    """将 registry 的 JSON Schema slot 转换为 edge_schemas 格式。"""
    # 1) 判断 required
    required = _slot_is_required(slot_def)

    # 2) 规范化：如果是 anyOf，取非 null 分支
    normalized = _normalize_slot(slot_def)

    # 3) 提取 desc
    desc = _extract_short_desc(normalized.get("description", ""))

    # 4) 判断类型并构建结果
    result = {"desc": desc, "required": required}

    stype = normalized.get("type", "string")
    enum_vals = normalized.get("enum")

    if enum_vals is not None:
        # string + enum → enum
        result["type"] = "enum"
        result["values"] = enum_vals
    elif stype in ("number", "integer"):
        lo = normalized.get("minimum")
        hi = normalized.get("maximum")
        result["type"] = "number"
        if lo is not None and hi is not None:
            result["range"] = [lo, hi]
    else:
        # 纯 string
        result["type"] = "string"

    return result


def _slot_is_required(slot_def: dict) -> bool:
    """判断 slot 是否必填（无 default 且无 anyOf 含 null）"""
    if "default" in slot_def:
        return False
    if "anyOf" in slot_def:
        return not any(
            t.get("type") == "null"
            for t in slot_def["anyOf"]
            if isinstance(t, dict)
        )
    return True


def _normalize_slot(slot_def: dict) -> dict:
    """如果是 anyOf 结构，取非 null 分支的实际定义。"""
    if "anyOf" not in slot_def:
        return slot_def

    for item in slot_def["anyOf"]:
        if isinstance(item, dict) and item.get("type") != "null":
            # 合并外层 description（anyOf 分支可能没有）
            merged = dict(item)
            if "description" not in merged and "description" in slot_def:
                merged["description"] = slot_def["description"]
            return merged

    # fallback: 返回原始
    return slot_def


def _extract_short_desc(description: str) -> str:
    """从 description 提取简短中文描述（取冒号前的部分或整句）。"""
    if not description:
        return ""
    # 取第一行
    first_line = description.strip().split("\n")[0]
    # 如果有冒号，取冒号前
    if ":" in first_line or "：" in first_line:
        sep = ":" if ":" in first_line else "："
        return first_line.split(sep)[0].strip()
    # 如果有括号，取括号前
    if "(" in first_line:
        return first_line.split("(")[0].strip()
    return first_line


INTENT_SCHEMAS = _build_intent_schemas()


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


def build_json_schema(domain: str) -> dict:
    """为 LMDeploy guided generation 构建 JSON Schema（治本层）
    
    约束模型输出合法 JSON，从生成层杜绝 46.8% 的格式错误。
    
    Returns:
        {"type": "json_schema", "json_schema": {"name": "...", "schema": {...}}}
        可直接传给 OpenAI API 的 response_format 参数。
    """
    intent_names = [name for name in INTENT_SCHEMAS.get(domain, {}).keys()]
    if not intent_names:
        return None
    
    return {
        "type": "json_schema",
        "json_schema": {
            "name": f"edge_stage2_{domain}",
            "schema": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": intent_names,
                        "description": f"{domain} 领域下的意图"
                    },
                    "slots": {
                        "type": "object",
                        "description": "槽位键值对"
                    }
                },
                "required": ["intent", "slots"],
                "additionalProperties": False
            }
        }
    }
