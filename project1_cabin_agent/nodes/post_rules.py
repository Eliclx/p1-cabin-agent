"""
project1_cabin_agent/nodes/post_rules.py
后置守卫 — "模型的输出可不可信？"

合并自：
  intent_ambiguity.py  — 歧义硬拦截（3条规则）
  intent_drift.py      — 漂移检测（slot 值从历史回复"偷"来的）
  intent_carry.py      — Slot Carry-Over + 历史注入判断

职责：
  1. 歧义拦截 — 短输入无对象词 / 模糊slot值 / 缺失required slot → 强制 clarify
  2. 漂移检测 — 端侧模型无上下文时，slot 值不应来自上轮回复
  3. Carry-Over — 新输入填充活跃帧的缺失槽位
  4. 历史注入判断 — 三层漏斗决定是否注入对话历史给 LLM
"""

from project1_cabin_agent.nodes.constants import (
    STRONG_COREFERENCE,
    IMPLIES_CONTEXT,
    INDEPENDENT_KEYWORDS,
    AMBIGUOUS_SHORT_INTENTS,
    CLEAR_OBJECT_WORDS,
    VAGUE_SLOT_VALUES,
    COREFERENCE_INDICATORS,
)
from project1_cabin_agent.nodes.message_utils import _get_msg_role, _get_msg_content
from shared.utils.logger import logger


# ═══════════════════════════════════════════════════════════════
# 1. 歧义硬拦截（原 intent_ambiguity.py）
# ═══════════════════════════════════════════════════════════════

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
        if len(user_input.strip()) <= 4 and intent in AMBIGUOUS_SHORT_INTENTS:
            if not any(w in user_input for w in CLEAR_OBJECT_WORDS):
                missing = [s for s in required if s not in slots or not slots[s]]
                if missing:
                    forced_clarify = True
                    clarify_reason = f"短输入('{user_input}')无明确对象词，LLM分配了{intent}"

        # --- 规则 2: slot 值含模糊代词（幻觉填充） ---
        if not forced_clarify:
            vague_keys = []
            for key, value in slots.items():
                if isinstance(value, str) and any(v in value for v in VAGUE_SLOT_VALUES):
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
            if intent in AMBIGUOUS_SHORT_INTENTS and not any(w in user_input for w in CLEAR_OBJECT_WORDS):
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


# ═══════════════════════════════════════════════════════════════
# 2. 漂移检测（原 intent_drift.py）
# ═══════════════════════════════════════════════════════════════

def _detect_context_bleeding(user_input: str, sub_tasks: list, messages: list, needs_ctx: bool = False) -> list:
    """纯规则后置漂移检测：检查 slot 值是否从历史回复中'偷'来的（0ms）。

    当 needs_ctx=True 时跳过——云端 LLM 有完整上下文，引用历史是正确行为。
    含指代词的短输入例外——slot 值来自上轮回复是正常的指代消解。
    """
    # 云端有上下文时跳过：LLM 引用历史是正确行为，不是污染
    if needs_ctx:
        return sub_tasks

    if not messages or len(user_input.strip()) > 4:
        return sub_tasks

    # 指代消解场景：用户说"就去这个"，slot 值来自上轮回复是正确行为
    if any(w in user_input for w in COREFERENCE_INDICATORS):
        return sub_tasks

    last_assistant = ""
    for m in reversed(messages):
        role_str = _get_msg_role(m)
        content_str = _get_msg_content(m)
        if role_str == "assistant" and content_str:
            last_assistant = content_str
            break
    if not last_assistant:
        return sub_tasks

    cleaned = []
    for task in sub_tasks:
        slots = task.get("extracted_slots", {})
        polluted_keys = []
        for key, value in slots.items():
            if isinstance(value, str) and len(value) > 1 and value in last_assistant:
                if value not in user_input:
                    polluted_keys.append(key)

        if polluted_keys:
            logger.warning(f"[漂移检测] 移除污染槽位: {polluted_keys}")
            for k in polluted_keys:
                del slots[k]
            task["extracted_slots"] = slots

        cleaned.append(task)

    return cleaned


# ═══════════════════════════════════════════════════════════════
# 3. Slot Carry-Over（原 intent_carry.py）
# ═══════════════════════════════════════════════════════════════

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
            # 不 mutate 原 frame，返回新 dict
            new_extracted = {**extracted, missing[0]: user_input.strip()}
            new_missing = [s for s in required if s not in new_extracted or not new_extracted[s]]
            logger.info(f"[Carry-Over] 匹配帧 {frame.get('task_id')}, 填充 {missing[0]}={user_input.strip()}")
            return {
                **frame,
                "extracted_slots": new_extracted,
                "status": "completed" if not new_missing else "pending",
            }
    return None


# ═══════════════════════════════════════════════════════════════
# 4. 历史注入判断（原 intent_carry.py）
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# 5. 行程提取校验（harness — 验 LLM 从行程数据提取的值是否真实存在）
# ═══════════════════════════════════════════════════════════════

def guard_episodic_extraction(sub_tasks: list, episodic_raw: list) -> list:
    """后置校验：LLM 从行程记录提取的槽位值，是否在原始行程数据中出现过。

    episodic_raw: retrieve_episodic_context 返回的 raw 列表，
                  每条含 full_text（所有文本字段拼接）。

    校验逻辑：
    - 只校验「提取型」slot（destination/keyword/query/artist）
      这些值来自行程数据，LLM 可能幻觉
    - 「结构型」slot（action/mode/sort_by/fan_level 等）不校验
      这些来自标准枚举或用户指令，不是从行程数据提取的
    - 校验的值必须在 raw.full_text 中出现过，否则 → clarify
    """
    # 「提取型」slot — 值来自行程数据，需要校验
    _EXTRACTION_SLOTS = {"destination", "keyword", "query", "artist", "scene_name"}

    if not episodic_raw:
        return sub_tasks

    for task in sub_tasks:
        intent = task.get("intent", "")
        if intent in ("clarify", "chitchat", "direct_answer", "no_support"):
            continue

        slots = task.get("extracted_slots", {})
        if not slots:
            continue

        for key, value in slots.items():
            # 只校验「提取型」slot
            if key not in _EXTRACTION_SLOTS:
                continue
            if not isinstance(value, str) or not value.strip():
                continue
            # 在 raw 数据的 full_text 中搜索这个值
            found = any(value in entry.get("full_text", "") for entry in episodic_raw)
            if not found:
                logger.warning(
                    f"[episodic guard] {key}={value} 不在行程数据中，"
                    f"intent={intent} → clarify"
                )
                task["intent"] = "clarify"
                task["extracted_slots"] = {}
                task["required_slots"] = []
                task["voice_reply"] = ""
                break

    return sub_tasks
