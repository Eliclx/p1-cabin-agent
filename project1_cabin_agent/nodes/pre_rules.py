"""
project1_cabin_agent/nodes/pre_rules.py
前置规则层 — "这个请求要不要/怎么进模型？"

插入位置：intent_classifier 之前（图节点 fast_rules）
三层漏斗的 L0 层：
  L0  FastRules    (0ms, ~40% 请求短路)
  L1  云端 LLM     (~300ms, ~60%)
  L2  端侧模型     (可选, prompt 裁剪省 token)

功能：
  1. OOS 拒绝     — 超出车载能力范围的请求，直接返回 no_support
  2. 高频意图短路 — 明确的空调/车窗/导航/媒体/座椅/灯光指令，直接生成 sub_task
  3. 多意图检测   — 连接词/逗号/冲突动词 → 放行云端
  4. 追问防误杀   — "还有多久"不是多意图，标记 is_followup 放行
"""

import re
from shared.utils.logger import logger



# ── OOS（Out-Of-Scope）关键词 ──────────────────────────────────
# 用户想做但我们不支持的

OOS_KEYWORDS = [
    ("点杯", "点单"), ("点单", "点单"), ("点菜", "点单"), ("点外卖", "点单"),   # 点单
    ("订票", "订票"), ("订一张", "订票"), ("买票", "订票"),                    # 订票
    ("买一个", "购买"), ("买点", "购买"), ("下单", "购买"),                 # 购买
    ("发微信", "发消息"), ("发消息给", "发消息"), ("发短信", "发消息"),         # 发消息
    ("打电话", "打电话"), ("拨号", "打电话"),                                  # 打电话
    ("外卖", "外卖"), ("快递", "快递"),
    ("转账", "转账"), ("付款", "转账"),
]

# ── 追问防误杀 ──────────────────────────────────────────────
# 包含"还有""再"但实际是追问，不是多意图

FOLLOWUP_PATTERNS = [
    "还有多久", "还有多远", "还有几个", "还要多久",
    "再往前", "再开一会", "再来一首", "再播一首",
    "再大一点", "再小一点", "再亮一点", "再暗一点",
    "再高点", "再低点", "再热点", "再冷点",
]


# ═══════════════════════════════════════════════════════════════
# 槽位提取函数
# ═══════════════════════════════════════════════════════════════

def _extract_temp(user_input: str) -> dict:
    """提取温度值：'22度' '调到24度'"""
    m = re.search(r'(\d{1,2})\s*度', user_input)
    if m:
        temp = int(m.group(1))
        if 16 <= temp <= 32:
            return {"action": "adjust", "temperature": float(temp)}
        # 超出范围也走 LLM，让 LLM 来处理
        return {}
    return {"action": "adjust"}


def _extract_fan(user_input: str) -> dict | None:
    """提取风速档位：'风速3档' '风力调到2'
    匹配不到具体档位时返回 None（放行给 LLM），不猜测默认值。
    """
    m = re.search(r'[风速风力]*\s*[调到设]*\s*(\d)\s*[档级]', user_input)
    if m:
        fan = int(m.group(1))
        if 1 <= fan <= 5:
            return {"action": "adjust", "fan_level": fan}
    return None


def _extract_volume_direction(user_input: str) -> dict:
    """判断音量方向：大/小/高/低"""
    if any(w in user_input for w in ("大", "高", "响")):
        return {"action": "volume_up"}
    if any(w in user_input for w in ("小", "低", "轻")):
        return {"action": "volume_down"}
    return {"action": "volume_up"}


def _extract_window_target(user_input: str) -> dict:
    """提取车窗控制参数"""
    target = "window"
    if "天窗" in user_input:
        target = "sunroof"
    elif "车门" in user_input or "后备箱" in user_input:
        target = "door"

    if any(w in user_input for w in ("关", "闭")):
        return {"target": target, "action": "close"}
    return {"target": target, "action": "open"}


def _extract_scene(user_input: str) -> dict:
    """提取场景名"""
    if any(w in user_input for w in ("舒适", "开车模式", "驾驶模式")):
        return {"scene_name": "comfortable_driving"}
    if any(w in user_input for w in ("休息", "睡眠", "睡觉")):
        return {"scene_name": "sleep_mode"}
    if any(w in user_input for w in ("出发检查", "出发前", "检查车辆")):
        return {"scene_name": "departure_check"}
    return {}


def _extract_seat_action(user_input: str) -> dict:
    """提取座椅控制参数"""
    if any(w in user_input for w in ("加热", "暖")):
        if any(w in user_input for w in ("关", "停", "取消")):
            return {"action": "heat_off"}
        # 提取档位
        m = re.search(r'(\d)\s*[档级]', user_input)
        if m and 1 <= int(m.group(1)) <= 3:
            return {"action": "heat_on", "heat_level": int(m.group(1))}
        return {"action": "heat_on", "heat_level": 2}
    if any(w in user_input for w in ("通风", "透气")):
        if any(w in user_input for w in ("关", "停", "取消")):
            return {"action": "ventilate_off"}
        return {"action": "ventilate_on"}
    return {}


def _extract_light_action(user_input: str) -> dict:
    """提取灯光控制参数"""
    target = None
    if "阅读灯" in user_input:
        target = "reading"
    elif "氛围灯" in user_input:
        target = "ambient"

    if any(w in user_input for w in ("关", "灭")):
        result = {"action": "off"}
        if target:
            result["target"] = target
        return result
    # 开/调
    result = {"action": "on"}
    if target:
        result["target"] = target
    # 亮度提取
    m = re.search(r'(\d{1,3})\s*%', user_input)
    if m:
        result = {"action": "adjust", "brightness": int(m.group(1))}
        if target:
            result["target"] = target
    return result


# ═══════════════════════════════════════════════════════════════
# 短路规则表（优先级从高到低）
# ═══════════════════════════════════════════════════════════════
# 格式：(match_func, intent, slots_extractor, rule_name)
# match_func: (user_input: str) -> bool

SHORT_CIRCUIT_RULES = [
    # ── 空调控制（短语精确匹配，不跨距离松散匹配）──
    (
        lambda s: any(p in s for p in ("打开空调", "开启空调", "开空调", "空调打开", "开下空调", "开冷气")),
        "ac_control",
        lambda s: {"action": "on"},
        "ac_on",
    ),
    (
        lambda s: any(p in s for p in ("关空调", "关闭空调", "关掉空调", "空调关掉", "把空调关了", "关上空调")),
        "ac_control",
        lambda s: {"action": "off"},
        "ac_off",
    ),
    (
        lambda s: bool(re.search(r'\d{1,2}\s*度', s))
        and 16 <= int(re.search(r'(\d{1,2})\s*度', s).group(1)) <= 32
        and not any(w in s for w in ("导航去", "导航到", "去", "前往")),
        "ac_control",
        _extract_temp,
        "ac_temp",
    ),
    # ── 隐式意图（太热/太冷→需要理解"热→制冷"，交给 LLM）──
    (
        lambda s: any(w in s for w in ("风速", "风力", "风量")) and any(
            w in s for w in ("大", "高", "调", "档", "级")
        ),
        "ac_control",
        _extract_fan,
        "ac_fan",
    ),
    # ── 模糊调温（热一点/冷一点→需要理解+依赖 vehicle_state，交给 LLM）──
    # ── 车窗/车门控制（开口语表达增强）──
    (
        lambda s: any(w in s for w in (
            "开窗", "车窗打开", "开个窗", "窗户打开", "天窗打开",
            "开门", "打开车门", "把窗", "把车窗", "帮我开窗",
            "天窗打开", "打开天窗", "打开车窗",
        )),
        "window_control",
        _extract_window_target,
        "window_open",
    ),
    (
        lambda s: any(w in s for w in (
            "关窗", "车窗关", "关上窗", "窗户关", "天窗关",
            "关车门", "车门关", "关上车窗", "关上车门", "把窗关",
            "把车窗关", "关上窗户", "关上天窗", "帮我关窗",
        )),
        "window_control",
        _extract_window_target,
        "window_close",
    ),
    # ── 媒体/音量控制 ──
    (
        lambda s: any(w in s for w in ("放音乐", "播放音乐", "播音乐", "来点音乐", "听音乐", "放首歌")),
        "media_control",
        lambda s: {"action": "play"},
        "media_play",
    ),
    (
        lambda s: any(w in s for w in ("暂停", "停一下", "暂停音乐", "别放了", "停止播放")),
        "media_control",
        lambda s: {"action": "pause"},
        "media_pause",
    ),
    (
        lambda s: any(w in s for w in ("下一首", "切歌", "换一首", "切到下一首", "换歌")),
        "media_control",
        lambda s: {"action": "next"},
        "media_next",
    ),
    (
        lambda s: any(w in s for w in ("上一首", "前一首", "上一曲")),
        "media_control",
        lambda s: {"action": "previous"},
        "media_prev",
    ),
    # 音量：同时匹配"声音"和"音量"
    (
        lambda s: any(w in s for w in ("声音", "音量")) and any(
            w in s for w in ("大", "高", "响")
        ),
        "media_control",
        _extract_volume_direction,
        "volume_up",
    ),
    (
        lambda s: any(w in s for w in ("声音", "音量")) and any(
            w in s for w in ("小", "低", "轻")
        ),
        "media_control",
        _extract_volume_direction,
        "volume_down",
    ),
    # ── 导航/POI 搜索：确定性不高，交给 LLM + pipeline depends_on 处理 ──
    # ── 场景联动 ──
    (
        lambda s: any(w in s for w in ("舒适驾驶", "舒适模式", "开车模式")),
        "activate_scene",
        _extract_scene,
        "scene_comfort",
    ),
    (
        lambda s: any(w in s for w in ("休息模式", "睡眠模式")),
        "activate_scene",
        _extract_scene,
        "scene_sleep",
    ),
    # ── 座椅控制（短语精确匹配）──
    (
        lambda s: any(p in s for p in ("座椅加热", "座椅暖", "座位加热", "加热座椅"))
        and not any(w in s for w in ("关", "停", "取消")),
        "seat_control",
        _extract_seat_action,
        "seat_heat_on",
    ),
    (
        lambda s: any(p in s for p in ("关座椅加热", "座椅加热关", "关掉座椅加热", "停止加热")),
        "seat_control",
        _extract_seat_action,
        "seat_heat_off",
    ),
    (
        lambda s: any(p in s for p in ("座椅通风", "座位通风")),
        "seat_control",
        _extract_seat_action,
        "seat_ventilate",
    ),
    # ── 灯光控制（短语精确匹配）──
    (
        lambda s: any(p in s for p in ("开灯", "打开灯", "开阅读灯", "开氛围灯"))
        and not any(w in s for w in ("关", "灭")),
        "light_control",
        _extract_light_action,
        "light_on",
    ),
    (
        lambda s: any(p in s for p in ("关灯", "关闭灯", "灯关", "关阅读灯", "关氛围灯", "灯灭")),
        "light_control",
        _extract_light_action,
        "light_off",
    ),
    # ── 车辆状态查询 ──
    (
        lambda s: any(w in s for w in ("多少油", "油量", "还剩多少油")),
        "query_vehicle_status",
        lambda s: {"items": "fuel"},
        "query_fuel",
    ),
    (
        lambda s: any(w in s for w in ("电量", "多少电", "电池", "续航")),
        "query_vehicle_status",
        lambda s: {"items": "battery"},
        "query_battery",
    ),
    (
        lambda s: "胎压" in s,
        "query_vehicle_status",
        lambda s: {"items": "tire"},
        "query_tire",
    ),
]


# ═══════════════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════════════

def fast_rules_check(user_input: str, active_frames: list) -> dict | None:
    """
    Apply front-door fast rules to determine whether the user input should be short-circuited before intent classification.
    
    Parameters:
        user_input (str): Raw user utterance to evaluate.
        active_frames (list): Active conversation frames; used to detect pending carry-over state which prevents short-circuiting.
    
    Returns:
        dict | None: If a rule or special condition is triggered, returns a dict intended to match the intent_classifier's sub_tasks result or a control-flag object; otherwise returns `None` to allow normal intent classification. Possible observable return forms include:
          - {"_oos_flag": "<reason>"} when the input appears out-of-scope.
          - {"_cross_domain_flag": True} when the input matches keywords from multiple domains.
          - A short-circuit sub_tasks result dict (intent, extracted_slots, etc.) when a single-domain rule matches.
          - For exact pure cancellation tokens (e.g., "算了", "取消"), a short-circuit chitchat result with a `voice_reply` of "好的".
    """
    text = user_input.strip()
    if not text:
        return None

    # ===== 1. OOS 检测 ===== 疑似超出能力范围，标记后放行给云端 LLM 二次判断
    oos = _detect_oos(text)
    if oos:
        logger.info(f"[FastRules] OOS 疑似命中: '{text}' → {oos}，放行云端二次判断")
        # 不短路，返回带 flag 的空结果，让 intent_classifier 跳过端侧走云端
        return {"_oos_flag": oos}

    # ===== 1b. 纯取消词检测 ===== "算了/不用了/取消" → 0ms 短路，清 pending frame
    # 仅拦截无操作对象的纯取消词（≤3字）。带操作对象的取消（"不开空调了"）走完整链路。
    PURE_ABANDON = {"算了", "不用了", "取消", "不了", "别了", "不要了"}
    if text in PURE_ABANDON:
        logger.info(f"[FastRules] 纯取消词短路: '{text}' → chitchat")
        return _build_short_circuit_result("chitchat", {"voice_reply": "好的"}, "abandon")

    # ===== 2. 追问防误杀 ===== 追问模式：包含"还有""再"但实际是追问，不是多意图
    # 只标记，不短路（追问仍需 LLM 处理，但标记 is_followup 供下游参考）
    # 放在短路规则之前，避免 "还有多久" 被误匹配到其他规则
    if _is_followup(text):
        logger.info(f"[FastRules] 追问模式放行: '{text}'")
        return None

    # ===== 2b. 多意图检测 =====
    # 1) 连接词 → 多意图
    _MULTI_INTENT_MARKERS = {"然后", "顺便", "同时", "并且", "另外", "和", "接着"}
    if any(w in text for w in _MULTI_INTENT_MARKERS):
        logger.info(f"[FastRules] 多意图放行云端: '{text}'")
        return None
    # 1b) "先X再Y" 模式
    if "先" in text and "再" in text:
        logger.info(f"[FastRules] 多意图(先X再Y)放行云端: '{text}'")
        return None
    # 2) 逗号/顿号分割 → 如果两边都有可执行关键词 → 多意图
    _ACTION_KEYWORDS = {"开", "关", "调", "放", "播", "导", "去", "搜", "查", "看", "听",
                        "切换", "换", "暂停", "继续", "停止", "切歌", "下一首", "上一首"}
    for sep in ("，", "、"):
        if sep in text:
            parts = [p.strip() for p in text.split(sep) if p.strip()]
            actionable = sum(1 for p in parts if any(p.startswith(k) or k in p for k in _ACTION_KEYWORDS))
            if actionable >= 2:
                logger.info(f"[FastRules] 逗号多意图放行云端: '{text}'")
                return None

    # ===== 2c. 冲突动词检测 =====
    # 同时包含"开"类+"关"类动作词 → 多子句，fast_rule 不该管
    _OPEN_WORDS = {"打开", "开启", "开开", "开一下", "开窗", "开灯", "开空调", "开音乐", "开座椅"}
    _CLOSE_WORDS = {"关闭", "关掉", "关了", "关上", "关窗", "关灯", "关空调", "关音乐", "关座椅"}
    has_open = any(w in text for w in _OPEN_WORDS)
    has_close = any(w in text for w in _CLOSE_WORDS)
    if has_open and has_close:
        logger.info(f"[FastRules] 冲突动词(开+关)放行云端: '{text}'")
        return None
    _CONFLICT_PAIRS = [("关闭打开", "ac"), ("打开关闭", "ac"), ("开开关关", "ac"),
                       ("关掉打开", "ac"), ("升高降低", "ac"), ("降低升高", "ac")]
    if any(p[0] in text for p in _CONFLICT_PAIRS):
        logger.info(f"[FastRules] 矛盾动词放行云端: '{text}'")
        return None

    # ===== 2d. 跨域多意图检测 =====
    # 如果同时命中 >=2 个 domain 的关键词 → 可能是多意图，放行云端
    # 必须在短路规则之前检测，避免被单意图规则误判
    if _detect_cross_domain(text):
        logger.info(f"[FastRules] 跨域多意图放行云端: '{text}'")
        return {"_cross_domain_flag": True}

    # ===== 2e. 极短输入保护 =====
    # 单字/两字且不含明确指令词 → 放行云端（避免"调""嗯"误匹配）
    if len(text) <= 2:
        _SAFE_SHORT = {"26", "28", "30", "开空调", "关空调", "开灯", "关灯", "放歌"}
        if not any(k in text for k in _SAFE_SHORT) and len(text) < 3:
            logger.info(f"[FastRules] 极短输入放行: '{text}'")
            return None

    # ===== 3. Carry-Over 优先：有 pending 帧时不短路，让 Carry-Over 处理 =====
    has_pending = any(f.get("status") == "pending" for f in active_frames)
    if has_pending:
        return None

    # ===== 4. 高频意图短路 =====
    for match_func, intent, slots_extractor, rule_name in SHORT_CIRCUIT_RULES:
        try:
            if match_func(text):
                slots = slots_extractor(text)
                if slots is None:
                    continue
                logger.info(f"[FastRules] ✅ 短路命中: rule={rule_name}, intent={intent}, slots={slots}")
                return _build_short_circuit_result(intent, slots, rule_name)
        except Exception as e:
            logger.warning(f"[FastRules] 规则 {rule_name} 执行异常: {e}")
            continue

    # ===== 未命中，放行给 LLM =====
    return None


def fast_rules_node(state) -> dict:
    """
    LangGraph 节点函数 — FastRules 前置规则层。

    插入位置：message_compressor → fast_rules → intent_classifier
    命中规则时直接返回 sub_tasks（跳过 LLM），未命中时返回空 dict 放行。
    """
    from shared.utils.logger import logger as _logger

    user_input = state.get("user_input", "")
    active_frames = state.get("active_frames", [])

    result = fast_rules_check(user_input, active_frames)
    if result is not None:
        _logger.info(f"[FastRules] ✅ 命中短路，跳过 LLM，intent={result.get('intent')}")
        return result

    # 未命中，返回空 dict（不修改 state，放行给 intent_classifier）
    return {}


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def _detect_oos(text: str) -> str:
    """检测超出能力范围的请求，返回 OOS 原因或空字符串"""
    for kw, reason in OOS_KEYWORDS:
        if kw in text:
            return reason
    return ""


def _is_followup(text: str) -> bool:
    """
    Detects whether the input is a follow-up question phrase.
    
    Returns:
        `True` if the input contains any substring from `FOLLOWUP_PATTERNS`, `False` otherwise.
    """
    for pattern in FOLLOWUP_PATTERNS:
        if pattern in text:
            return True
    return False


def _detect_cross_domain(text: str) -> bool:
    """
    Detect whether the input text matches keywords from two or more different domains.
    
    Uses the edge schema domain keyword lists to perform lightweight substring matching. This check excludes the "chitchat" and "unknown" domains and ignores single-character keywords to reduce false positives.
    
    Parameters:
        text (str): The user input to check.
    
    Returns:
        bool: `True` if keywords from at least two distinct domains are found in `text`, `False` otherwise.
    """
    from project1_cabin_agent.edge_schemas import DOMAINS as _DOMAINS
    matched = set()
    for domain_name, domain_info in _DOMAINS.items():
        if domain_name in ("chitchat", "unknown"):
            continue
        for kw in domain_info.get("keywords", "").split():
            if len(kw) <= 1:  # 单字太泛，跳过防误伤
                continue
            if kw in text:
                matched.add(domain_name)
                break
        if len(matched) >= 2:
            return True
    return False


def _build_short_circuit_result(intent: str, slots: dict, rule_name: str) -> dict:
    """
    Builds a short-circuit result matching the intent classifier output format.
    
    Parameters:
        intent (str): The intent name to set on the generated task.
        slots (dict): Extracted slot values to populate `extracted_slots` for the task.
        rule_name (str): Identifier of the rule that produced this short-circuit (kept for traceability).
    
    Returns:
        dict: A result object containing a single `task_0` in `sub_tasks` with the provided `intent` and `extracted_slots`, fixed metadata (e.g. `intent_confidence=0.95`, empty `required_slots`), `is_complex=False`, and `active_frames` set to an empty list to prevent carry-over.
    """
    return {
        "sub_tasks": [{
            "task_id": "task_0",
            "intent": intent,
            "intent_confidence": 0.95,
            "ambiguity_score": 0.0,
            "ambiguity_reason": "",
            "required_slots": [],
            "extracted_slots": slots,
            "depends_on": [],
            "urgency": "normal",
            "voice_reply": "",
        }],
        "is_complex": False,
        "task_results": None,
        "completed_task_ids": None,
        "intent": intent,
        "active_frames": [],  # 短路时清空，不走 Carry-Over
    }


def _build_no_support_result(reply: str) -> dict:
    """构建 OOS/不支持 结果"""
    return {
        "sub_tasks": [{
            "task_id": "task_0",
            "intent": "no_support",
            "intent_confidence": 1.0,
            "ambiguity_score": 0.0,
            "ambiguity_reason": "",
            "required_slots": [],
            "extracted_slots": {"answer": reply},
            "depends_on": [],
            "urgency": "normal",
            "voice_reply": reply,
        }],
        "is_complex": False,
        "task_results": None,
        "completed_task_ids": None,
        "intent": "no_support",
        "active_frames": [],
    }
