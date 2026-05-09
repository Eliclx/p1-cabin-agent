"""
project1_cabin_agent/nodes/intent_carry.py
Slot Carry-Over + 历史注入判断。
"""
from project1_cabin_agent.nodes.models import (
    STRONG_COREFERENCE, IMPLIES_CONTEXT, INDEPENDENT_KEYWORDS,
)
from shared.utils.logger import logger


# ── Carry-Over ──

def _try_carry_over(user_input: str, active_frames: list) -> dict | None:
    """纯规则 Slot Carry-Over：检查新输入能否填充某个活跃帧的缺失槽位（0ms）。"""
    for frame in active_frames:
        if frame.get("status") != "pending":
            continue
        extracted = frame.get("extracted_slots", {})
        required = frame.get("required_slots", [])
        missing = [s for s in required if s not in extracted or not extracted[s]]
        if not missing:
            continue
        if len(user_input.strip()) <= 10 and len(missing) == 1:
            if any(w in user_input for w in INDEPENDENT_KEYWORDS):
                return None
            frame["extracted_slots"][missing[0]] = user_input.strip()
            new_missing = [s for s in required if s not in frame["extracted_slots"] or not frame["extracted_slots"][s]]
            frame["status"] = "completed" if not new_missing else "pending"
            logger.info(f"[Carry-Over] 匹配帧 {frame.get('task_id')}, 填充 {missing[0]}={user_input.strip()}")
            return frame
    return None


# ── 历史注入判断 ──

def _needs_context(user_input: str, active_frames: list) -> bool:
    """历史注入策略（三层漏斗）。"""
    input_clean = user_input.strip()

    has_pending = any(f.get("status") == "pending" for f in active_frames)
    if has_pending:
        return True
    if any(w in input_clean for w in STRONG_COREFERENCE):
        return True
    if len(input_clean) <= 6 and any(w in input_clean for w in IMPLIES_CONTEXT):
        return True

    if len(input_clean) >= 8:
        for kw in INDEPENDENT_KEYWORDS:
            if kw in input_clean:
                return False

    return True
