"""
project1_cabin_agent/nodes/intent_drift.py
漂移检测 — 检查 slot 值是否从历史回复中'偷'来的。
"""
from project1_cabin_agent.nodes.message_utils import _get_msg_role, _get_msg_content
from shared.utils.logger import logger


# 用户含这些词时，slot 值来自上轮回复是正常的指代消解，不算漂移
_COREFERENCE_INDICATORS = {
    "就去", "去这个", "去那个", "选这个", "选那个", "就这个", "就那个",
    "第一个", "第二个", "第三个", "第一个吧", "第二个吧",
    "这个吧", "那个吧", "要这个", "要那个", "用它", "就它",
    # 指代导航: "去最近的""去最远的""去第一个" 等
    "去最近的", "去最远的", "去第一个", "去第二个",
    "导航去最近的", "导航去最远的",
}


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
    if any(w in user_input for w in _COREFERENCE_INDICATORS):
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
