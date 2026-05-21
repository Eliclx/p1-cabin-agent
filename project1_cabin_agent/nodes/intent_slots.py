"""
project1_cabin_agent/nodes/intent_slots.py
槽位校验 + 降级结果生成。
"""
from project1_cabin_agent.nodes.constants import SubTask
from project1_cabin_agent.nodes.schema import DYNAMIC_SCHEMA
# INTENT_TO_TOOL 已移除 — intent 名即 tool 名，直接用 intent 作 DYNAMIC_SCHEMA 的 key
from project1_cabin_agent.vehicle_state import vehicle_state
from shared.utils.logger import logger


# ── 降级结果 ──

_FALLBACK_MESSAGES = {
    "json_error": "抱歉没听懂，请再说一次",
    "unknown_error": "系统开小差了，请稍后再试",
    "empty_result": "没理解您的意思，换个说法试试",
}


def _create_fallback_result(error_type: str) -> dict:
    voice_reply = _FALLBACK_MESSAGES.get(error_type, "抱歉，出了点问题")
    logger.warning(f"[降级] 意图识别失败，错误类型={error_type}，回复: {voice_reply}")
    return {
        "sub_tasks": [{
            "task_id": "task_0", "intent": "direct_answer",
            "intent_confidence": 0.0, "ambiguity_score": 1.0,
            "ambiguity_reason": f"意图识别失败: {error_type}",
            "required_slots": [], "extracted_slots": {"answer": voice_reply},
            "depends_on": [], "urgency": "normal", "voice_reply": voice_reply,
        }],
        "is_complex": False,
        "task_results": None,
        "completed_task_ids": None,
        "intent": "direct_answer",
        "error": f"意图识别异常: {error_type}",
    }


def _create_default_subtask() -> SubTask:
    return SubTask(
        task_id="task_0", intent="chitchat", intent_confidence=0.3,
        ambiguity_score=0.8, ambiguity_reason="无法正确解析模型输出",
        required_slots=[], extracted_slots={}, depends_on=[], urgency="normal",
    )


# ── 槽位校验（intent_classifier 和 task_pipeline 都用） ──

def _validate_slots(task: dict):
    """过滤非法槽位 key 和空字符串。"""
    intent = task.get("intent", "")
    extracted = task.get("extracted_slots", {})
    if not extracted:
        return

    schema = DYNAMIC_SCHEMA.get(intent, {})
    valid_keys = set(schema.get("required", []) + schema.get("optional", []))

    if valid_keys:
        invalid = [k for k in extracted if k not in valid_keys]
        for k in invalid:
            logger.warning(f"[槽位校验] 移除非法 key '{k}' (intent={intent})")
            del extracted[k]

    empty_keys = [k for k, v in extracted.items() if isinstance(v, str) and v.strip() == ""]
    for k in empty_keys:
        logger.warning(f"[槽位校验] 移除空字符串参数 '{k}' (intent={intent})")
        del extracted[k]

    # ── 类型修复：模糊值 → 从 vehicle_state 推算绝对值 ──
    _TYPE_FIX_MAP = {
        "temperature": float,
        "fan_level": int,
    }
    _FUZZY_FIX = {
        "temperature": {
            "lower": -2, "decrease": -2, "down": -2, " colder": -2, "冷": -2,
            "higher": 2, "increase": 2, "up": 2, "warmer": 2, "热": 2,
        },
        "fan_level": {
            "lower": -1, "decrease": -1, "down": -1,
            "higher": 1, "increase": 1, "up": 1,
        },
    }
    _STATE_GETTER = {
        "temperature": lambda: vehicle_state.ac_temp,
        "fan_level": lambda: vehicle_state.ac_fan_level,
    }
    for key, expected_type in _TYPE_FIX_MAP.items():
        val = extracted.get(key)
        if val is None:
            continue
        if isinstance(val, expected_type):
            continue  # 已经是正确类型，跳过
        # 是字符串但不是合法数字
        if isinstance(val, str):
            try:
                extracted[key] = expected_type(float(val))
                logger.info(f"[槽位校验] 类型修复 '{key}': '{val}' → {extracted[key]}")
                continue
            except (ValueError, TypeError):
                pass
            # 模糊词 → 从 vehicle_state 推算
            fuzzy_map = _FUZZY_FIX.get(key, {})
            val_lower = val.lower().strip()
            delta = fuzzy_map.get(val_lower)
            if delta is not None:
                current = _STATE_GETTER[key]()
                new_val = current + delta
                # clamp 到合法范围
                if key == "temperature":
                    new_val = max(16.0, min(32.0, new_val))
                elif key == "fan_level":
                    new_val = max(1, min(5, new_val))
                extracted[key] = expected_type(new_val)
                logger.info(f"[槽位校验] 模糊→绝对值 '{key}': '{val}' → {new_val} (当前={current}, delta={delta})")
            else:
                # 无法修复，删掉让工具用默认值
                logger.warning(f"[槽位校验] 无法修复 '{key}'='{val}'，移除")
                del extracted[key]
