"""
project1_cabin_agent/nodes/response.py
节点 3（session_update）、节点 4（wave_aggregator）、
节点 5（response_gen）、节点 6（chitchat_handler）。
"""
from langchain_core.messages import HumanMessage

from project1_cabin_agent.state import CabinAgentState
from project1_cabin_agent.tools.cabin_tools import TOOL_REGISTRY
from shared.utils.llm_factory import get_llm
from shared.utils.logger import logger
from shared.utils.metrics import track_node

from project1_cabin_agent.nodes.message_utils import _ensure_str
from project1_cabin_agent.nodes.pipeline import _chitchat_reply


# ── 节点 3：L1 记忆写入 ──

@track_node("session_update")
def session_update(state: CabinAgentState | dict) -> dict:
    """从 task_results 中提取产出的实体，按黑板标签写入 dialogue_context。"""
    task_results = state.get("task_results", [])
    dialogue_ctx = state.get("dialogue_context", {})
    context_update = {}

    # 计算当前轮次：取所有实体栈中最大 round + 1，默认从 1 开始
    max_round = 0
    for entries in dialogue_ctx.values():
        if isinstance(entries, list):
            for entry in entries:
                max_round = max(max_round, entry.get("round", 0))
    current_round = max_round + 1

    for r in task_results:
        intent = r.get("intent")
        tool_result = r.get("tool_result", {})

        if not intent or not tool_result:
            continue

        reg = TOOL_REGISTRY.get(intent, {})
        bb = reg.get("blackboard")
        # 只有声明了 blackboard 标签的工具产出才写入 L1 结构化记忆，供后续轮次查询使用
        if not bb or "produces" not in bb:
            continue

        entity_tag = bb["produces"]

        # 存储结构化数据（过滤掉 status/voice_reply 等内部字段）
        data = {k: v for k, v in tool_result.items()
                if k not in ("status", "voice_reply")}

        context_update[entity_tag] = {
            "round": current_round,
            "task_id": r.get("task_id", ""),
            "data": data,
        }
        logger.info(
            f"[session_update] <- L1 entity={entity_tag} "
            f"round={current_round} task_id={r.get('task_id')}"
        )

    if not context_update:
        logger.debug("[session_update] 无需写入（本轮无产出实体）")
    return {"dialogue_context": context_update}


# ── 节点 4：并发结果汇聚 ──

@track_node("wave_aggregator")
def wave_aggregator(state: CabinAgentState | dict) -> dict:
    """并发结果汇聚：紧急任务立即返回，依赖链等聚合。"""
    results = state.get("task_results", [])
    completed = set(state.get("completed_task_ids", []))
    sub_tasks = state.get("sub_tasks", [])

    if not results:
        return {
            "final_response": "好的，已为您处理",
            "messages": [{"role": "assistant", "content": "好的，已为您处理"}],
        }
    depended_ids = set(depend_task_id for task in sub_tasks for depend_task_id in task.get("depends_on", []))

    # ── 紧急任务立即返回 ──
    urgent = [r for r in results if r.get("urgency") == "immediate"]
    if urgent:
        reply = urgent[0].get("voice_reply", "检测到紧急情况")
        logger.warning(f"[wave_aggregator] 紧急任务{urgent[0].get('task_id')} | 意图{urgent[0].get('intent')} | 紧急回复: {reply}")
        return {
            "final_response": reply,
            "messages": [{"role": "assistant", "content": reply}],
        }

    reply_parts = []

    blocked = [r for r in results if r.get("status") == "blocked" and r.get("task_id") not in depended_ids and not r.get("depends_on")]
    for r in blocked:
        reply = r.get("voice_reply", "操作被阻止")
        logger.info(f"[wave_aggregator] 任务{r.get('task_id')} | 意图{r.get('intent')} | 被阻止: {reply}")
        reply_parts.append(reply)

    done = [r for r in results if r.get("status") == "done" and r.get("task_id") not in depended_ids and not r.get("depends_on")]
    for r in done:
        reply = r.get("voice_reply", "操作成功")
        logger.info(f"[wave_aggregator] 任务{r.get('task_id')} | 意图{r.get('intent')} | 成功: {reply}")
        reply_parts.append(reply)

    errors = [r for r in results if r.get("status") == "error" and r.get("task_id") not in depended_ids and not r.get("depends_on")]
    for r in errors:
        err_detail = r.get("error", "未知错误")
        logger.error(f"[wave_aggregator] 任务{r.get('task_id')} | 意图{r.get('intent')} | 失败: {err_detail}")
        reply = r.get("voice_reply", "操作失败, 请稍后重试")
        reply_parts.append(reply)

    clarify = [r for r in results if r.get("status") == "need_clarify"]
    for r in clarify:
        missing_detail = r.get("missing_slots", [])
        logger.info(f"[wave_aggregator] 任务{r.get('task_id')} | 意图{r.get('intent')} | 需要追问: 缺失槽位 {missing_detail}")
        reply = r.get("voice_reply", "请补充信息")
        reply_parts.append(reply)

    # TODO: ★ 方案5插入点 — suspended 任务恢复
    if len(reply_parts):
        response = "；".join(reply_parts)
        return {
            "final_response": response,
            "messages": [{"role": "assistant", "content": response}],
        }
    else:
        return {}


# ── 节点 5：聚合回复（依赖链） ──

CHAIN_RESPONSE_PROMPT = """你是车载语音助手。多个关联任务已执行完成，请将结果合并为一条简洁的语音播报。

要求：
1. 不超过30字
2. 自然口语化
3. 按执行顺序串联结果

各任务结果：
{task_summaries}

直接输出合并后的回复："""


@track_node("response_gen")
def response_gen(state: CabinAgentState | dict) -> dict:
    results = state.get("task_results", [])
    if not results:
        return {"final_response": ""}

    summaries = []
    for r in results:
        if r.get("status") != "done":
            continue
        voice = r.get("voice_reply", "")
        if voice:
            summaries.append(f"[{r.get('intent', '')}] {voice}")

    if len(summaries) <= 1:
        response = summaries[0].split("] ", 1)[-1] if summaries else ""
    else:
        task_summaries = "\n".join(summaries)
        try:
            llm = get_llm("fast", temperature=0.3)
            prompt = CHAIN_RESPONSE_PROMPT.format(task_summaries=task_summaries)
            resp = llm.invoke([HumanMessage(content=prompt)])
            response = _ensure_str(resp.content).strip()
        except Exception as e:
            logger.error(f"[聚合回复] LLM 失败: {e}")
            response = "；".join(s.split("] ", 1)[-1] for s in summaries if "] " in s)

    logger.info(f"[聚合回复] {response}")
    return {
        "final_response": response,
        "messages": [{"role": "assistant", "content": response}],
    }


# ── 节点 6：闲聊处理 ──

@track_node("chitchat_handler")
def chitchat_handler(state: CabinAgentState | dict) -> dict:
    response = _chitchat_reply(state["user_input"], state.get("messages", []))
    return {
        "final_response": response,
        "messages": [
            # main.py 已经把用户输入追加到 messages 里了，这里不重复添加了
            # {"role": "user", "content": state["user_input"]},
            {"role": "assistant", "content": response},
        ],
    }
