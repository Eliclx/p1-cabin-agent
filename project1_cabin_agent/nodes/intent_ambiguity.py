"""
project1_cabin_agent/nodes/intent_ambiguity.py
post-hoc 歧义硬拦截 — 纯规则校验 LLM 输出。
"""
from shared.utils.logger import logger


# ── 常量 ──

# 不含明确操作对象的极短输入，且 LLM 分配了具体工具意图 → 歧义
_AMBIGUOUS_SHORT_INTENTS = {
    "ac_control", "media_control", "light_control", "window_control",
    "seat_control", "search_poi", "start_navigation", "parking",
    "query_vehicle_status", "activate_scene", "comfort_driving",
}

# 明确的操作对象关键词 → 即使短输入也不拦截
_CLEAR_OBJECT_WORDS = {
    # 空调
    "空调", "冷气", "暖气", "温度", "风量", "除雾",
    # 车窗/门
    "车窗", "窗户", "天窗", "车门", "后备箱",
    # 灯光
    "灯", "大灯", "雾灯", "氛围灯", "阅读灯",
    # 座椅
    "座椅", "座位", "靠背", "加热", "通风", "按摩",
    # 媒体
    "音乐", "歌", "电台", "广播", "收音机", "播放",
    # 导航
    "导航", "地图",
    # 车辆状态
    "油量", "电量", "续航", "胎压", "油耗",
    # 停车
    "停车", "车位",
}

# 模糊代词 / 指代不明词汇（出现在 slot 值里 → 幻觉填充）
_VAGUE_SLOT_VALUES = {
    "那边", "这边", "最近的", "那个", "这个", "那里", "这里",
    "那个地方", "上面", "下面", "旁边", "对面",
}


def _detect_ambiguity(user_input: str, sub_tasks: list) -> list:
    """post-hoc 歧义硬拦截：纯规则校验 LLM 输出，0ms。

    三条规则：
    1. 短输入(≤4字) + 非chitchat/direct_answer/clarify + 输入无明确对象词 → 强制 clarify
    2. slot 值含模糊代词 → 清空该 slot，若 required_slots 非空则强制 clarify
    3. 输入无操作对象词 + LLM 给了具体意图 + 有 required slot 但没填 → 强制 clarify
    """
    if not sub_tasks:
        return sub_tasks

    cleaned = []
    for task in sub_tasks:
        intent = task.get("intent", "")
        slots = task.get("extracted_slots", {})
        required = task.get("required_slots", [])

        # 已是 clarify/chitchat/direct_answer/no_support → 不拦截
        if intent in ("clarify", "chitchat", "direct_answer", "no_support"):
            cleaned.append(task)
            continue

        # 有 depends_on 的任务 → 不拦截（缺失字段由上游填充）
        if task.get("depends_on"):
            cleaned.append(task)
            continue

        forced_clarify = False
        clarify_reason = ""

        # --- 规则 1: 极短输入 + 无明确对象词 ---
        # 例外：required slots 已全部填满 → LLM 已正确提取信息，不拦截
        if len(user_input.strip()) <= 4 and intent in _AMBIGUOUS_SHORT_INTENTS:
            if not any(w in user_input for w in _CLEAR_OBJECT_WORDS):
                missing = [s for s in required if s not in slots or not slots[s]]
                if missing:
                    forced_clarify = True
                    clarify_reason = f"短输入('{user_input}')无明确对象词，LLM分配了{intent}"

        # --- 规则 2: slot 值含模糊代词（幻觉填充） ---
        if not forced_clarify:
            vague_keys = []
            for key, value in slots.items():
                if isinstance(value, str) and any(v in value for v in _VAGUE_SLOT_VALUES):
                    vague_keys.append(key)
            if vague_keys:
                logger.warning(f"[歧义检测] 移除模糊slot值: {vague_keys}")
                for k in vague_keys:
                    del slots[k]
                task["extracted_slots"] = slots
                # 如果有 required slot 未填 → 强制 clarify
                missing = [s for s in required if s not in slots]
                if missing:
                    forced_clarify = True
                    clarify_reason = f"slot含模糊代词被移除，required缺失: {missing}"

        # --- 规则 3: 输入无操作对象 + intent 有 required slot 但未填 ---
        if not forced_clarify:
            if intent in _AMBIGUOUS_SHORT_INTENTS and not any(w in user_input for w in _CLEAR_OBJECT_WORDS):
                missing = [s for s in required if s not in slots]
                if missing:
                    forced_clarify = True
                    clarify_reason = f"输入无对象词 + required slot缺失: {missing}"

        if forced_clarify:
            # 规则1拦截：LLM 连意图都在瞎猜，candidates 不可信，走通用追问
            # 规则2/3拦截：意图可能对（只是 slot 不完整），保留 candidates
            if clarify_reason.startswith("短输入"):
                candidates = []
            else:
                candidates = [intent]
            logger.warning(
                f"[歧义检测] 强制澄清: intent={intent} → clarify, "
                f"reason={clarify_reason}, candidates={candidates}"
            )
            task["intent"] = "clarify"
            task["extracted_slots"] = {"candidates": candidates}
            task["required_slots"] = []
            task["voice_reply"] = ""

        cleaned.append(task)

    return cleaned
