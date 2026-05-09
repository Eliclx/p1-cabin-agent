"""
project1_cabin_agent/nodes/intent_compress.py
消息压缩节点 — 检查 messages 是否超限，超限则压缩旧消息为摘要。
"""
from langchain_core.messages import HumanMessage, RemoveMessage

from project1_cabin_agent.state import CabinAgentState
from shared.utils.llm_factory import get_llm
from shared.utils.logger import logger
from shared.utils.metrics import track_node
from project1_cabin_agent.nodes.message_utils import (
    _get_msg_role, _get_msg_content, _ensure_str,
)

# ── 常量 ──

MAX_MESSAGES = 30  # 上限设为30条，超过则触发压缩。车载场景对话通常很短，30条已是极限了。
COMPRESS_CHUNK = 24  # 每次压缩保留最近20条消息，其他的压缩成摘要。保留最近消息有助于保持上下文连贯，避免过度压缩导致信息丢失。

SUMMARY_PROMPT = """你是对话摘要助手。将以下车载对话历史压缩为一条简短摘要，保留关键信息：
- 用户做过什么操作（开空调、导航去哪、搜了什么）
- 工具执行的关键结果（搜索结果、导航路线等）
- 用户偏好（喜欢什么温度、常去什么地方）

现有摘要：
{existing_summary}

新的对话：
{new_messages}

输出一条摘要（不超过100字）："""


# ── 节点 0：消息压缩 ──

@track_node("message_compressor")
def message_compressor(state: CabinAgentState) -> dict:
    """新一轮开始前执行。检查 messages 是否超限，超限则压缩旧消息为摘要。"""
    # 获取历史消息
    messages = state.get("messages", [])

    if len(messages) <= MAX_MESSAGES:
        return {}

    logger.info(f"[消息压缩] 当前 {len(messages)} 条，上限 {MAX_MESSAGES}，开始压缩")
    # 保留最近 COMPRESS_CHUNK 条消息，其他的压缩成摘要。保留最近消息有助于保持上下文连贯，避免过度压缩导致信息丢失。
    old_messages = messages[:-COMPRESS_CHUNK]
    recent_messages = messages[-COMPRESS_CHUNK:]
    # 已经总结的摘要
    existing_summary = ""
    # 旧消息，没有被总结
    non_summary_old = []
    for m in old_messages:
        role = _get_msg_role(m)
        content = _get_msg_content(m)
        if role == "system" and "[对话摘要]" in content:
            existing_summary = content.replace("[对话摘要] ", "")
        else:
            non_summary_old.append(m)
    
    dialog_text = "\n".join(
        f"{'用户' if _get_msg_role(m) == 'user' else '助手'}："
        f"{_get_msg_content(m)}"
        for m in non_summary_old
    )

    try:
        llm = get_llm("fast", temperature=0)
        prompt = SUMMARY_PROMPT.format(
            existing_summary=existing_summary or "（无）",
            new_messages=dialog_text,
        )
        resp = llm.invoke([HumanMessage(content=prompt)])
        summary_text = _ensure_str(resp.content).strip()
        logger.info(f"[消息压缩] ✅ 摘要: {summary_text}")
    except Exception as e:
        logger.error(f"[消息压缩] LLM 调用失败: {e}，降级直接截断")
        summary_text = existing_summary or "早期对话已省略"
    # 生成 RemoveMessage 操作删除旧消息，添加新摘要消息
    # messages: Annotated[list, add_messages]
    # state.py 里 messages 字段用了 Annotated[list, add_messages]，reducer 的行为是追加合并——你 return {"messages": [new_msg]}，它会加到列表末尾，不会覆盖。                                                                                           
    # 所以不能直接删消息。删除必须用 RemoveMessage 信号
    remove_ops = [RemoveMessage(id=m.id) for m in old_messages if hasattr(m, "id")]
    summary_msg = {"role": "system", "content": f"[对话摘要] {summary_text}"}

    new_len = len(messages) - len(remove_ops) + 1
    logger.info(f"[消息压缩] {len(messages)} → {new_len} 条")

    return {"messages": remove_ops + [summary_msg]}
