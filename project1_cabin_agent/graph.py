"""
project1_cabin_agent/graph.py
LangGraph 状态图构建（Send fan-out 并发版）

图结构：
  intent_classifier
       ↓
  route_after_intent (条件边)
       ├── 全闲聊 → chitchat_handler → END
       └── 非闲聊 → wave_planner (Send fan-out)
                        ↓
                  [Send("task_pipeline") × N]  ← 本轮就绪任务并发执行
                        ↓ (reducer 自动合并)
                  wave_aggregator
                        ↓
                  route_after_aggregate (条件边)
                       ├── 还有未完成任务 → wave_planner (下一波)
                       ├── 依赖链需聚合   → response_gen → END
                       └── 全部完成/已回复 → END
"""
from langgraph.graph import StateGraph, END
from langgraph.types import Send
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import os
import aiosqlite

from project1_cabin_agent.state import CabinAgentState
from project1_cabin_agent.nodes.agent_nodes import (
    message_compressor,
    fast_rules_node,
    intent_classifier,
    task_pipeline,
    session_update,
    wave_aggregator,
    response_gen,
    chitchat_handler,
)
from project1_cabin_agent.nodes.slot_transfer import fill_slots_from_blackboard
from project1_cabin_agent.tools.cabin_tools import BLACKBOARD_DECLS

import logging
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 条件路由函数
# ─────────────────────────────────────────────────────────────

def route_after_fast_rules(state: CabinAgentState) -> str:
    """FastRules 短路判断：
    - sub_tasks 非空 → FastRules 命中，跳过 intent_classifier，直接路由
    - sub_tasks 为空/不存在 → 未命中，放行给 intent_classifier
    """
    sub_tasks = state.get("sub_tasks", [])
    if sub_tasks:
        # FastRules 已生成 sub_tasks，复用 intent 之后的路由逻辑
        if all(t.get("intent") == "chitchat" for t in sub_tasks):
            return "chitchat_handler"
        # no_support / 任务意图 → 走 wave_planner 路径
        # task_pipeline 会识别 intent=no_support 直接返回，wave_aggregator 输出 voice_reply
        return "wave_planner"
    return "intent_classifier"


def route_after_intent(state: CabinAgentState) -> str:
    sub_tasks = state.get("sub_tasks", [])
    if sub_tasks and all(t.get("intent") == "chitchat" for t in sub_tasks):
        return "chitchat_handler"
    return "wave_planner"


def route_wave(state: CabinAgentState | dict):
    """
    波次调度器 —— 决定「这一波该执行哪些任务」
    
    核心逻辑：只有「前置依赖全部完成」的任务才会被选中执行。
    被选中的任务通过 Send 并发投递给 task_pipeline，互不阻塞。
    
    例：用户说 "查天气然后推荐活动，顺便开空调"
        sub_tasks = [t1(查天气, depends=[]), t2(推荐活动, depends=[t1]), t3(开空调, depends=[])]
        第1波 ready = [t1, t3]  → 并发执行
        第2波 ready = [t2]      → t1完成后才就绪
    """
    sub_tasks = state.get("sub_tasks", [])
    completed = set(state.get("completed_task_ids", []))

    # 筛选本轮就绪任务：
    #   条件1: task_id 不在 completed 中 → 避免重复执行
    #   条件2: depends_on 列表中所有依赖都在 completed 中 → 前置任务全部完成
    #   注: depends_on=[] 的任务，all() 返回 True，天然就绪（独立任务）
    # 获取前置任务已完成，但还没执行的任务，后续给到task_pipeline执行，执行结果会更新completed_task_ids，触发下一波就绪任务的产生
    ready = [
        t for t in sub_tasks
        if t.get("task_id") not in completed
        and all(dep in completed for dep in t.get("depends_on", []))
    ]

    # 没有就绪任务 → 两种情况：
    #   1) 所有任务都已完成（completed 覆盖全部 sub_tasks）
    #   2) 存在循环依赖（A依赖B，B依赖A，永远没有就绪的）
    # 无论哪种，都直接跳到 wave_aggregator 做收尾聚合
    if not ready:
        return ["wave_aggregator"]

    # 紧急任务排前面（urgency="immediate" → sort key=0，优先投递）
    # 注: Send 是并发的，排序只影响投递顺序，不保证执行顺序
    # 真正保证紧急优先的是 wave_aggregator 里 urgent 立即 return
    ready.sort(key=lambda t: 0 if t.get("urgency") == "immediate" else 1)

    # ── 黑板回填：消费者任务的空槽从黑板取值 ──
    dialogue_context = state.get("dialogue_context", {})
    for task in ready:
        intent = task.get("intent", "")
        bb_decl = BLACKBOARD_DECLS.get(intent)
        if bb_decl and "consumes" in bb_decl:
            task["extracted_slots"] = fill_slots_from_blackboard(
                task["extracted_slots"],
                bb_decl,
                dialogue_context,
            )

    # 为每个就绪任务创建一个 Send → 触发 task_pipeline 并发执行
    # Send 是 LangGraph 的并发原语：多个 Send 同时投递，task_pipeline 会并行处理
    # 每个 task_pipeline 实例只接收自己的 current_task + 共享的 user_input/messages
    return [
        Send("task_pipeline", {
            "current_task": task,
            "user_input": state["user_input"],
            "messages": state.get("messages", []),
        })
        for task in ready
    ]


def route_after_aggregate(state: CabinAgentState) -> str:
    sub_tasks = state.get("sub_tasks", [])
    completed = set(state.get("completed_task_ids", []))
    results = state.get("task_results", [])

    # 如果还有未完成的任务，继续下一波调度
    if len(completed) < len(sub_tasks):
        # ── 死锁保护：检测是否有任务能被执行 ──
        # 场景：depends_on 填了 intent 名（如 'search_poi'）而非 task_id，
        #   导致 route_wave 永远找不到就绪任务 → aggregator 空结果 →
        #   又回 wave_planner → 死循环
        # 修复：如果所有未完成的任务的 depends_on 都无法被满足，强制终止
        incomplete = [t for t in sub_tasks if t.get("task_id") not in completed]
        can_progress = any(
            all(dep in completed for dep in t.get("depends_on", []))
            for t in incomplete
        )
        if not can_progress:
            # 无进展：存在无法满足的依赖，强制终止避免死循环
            logger.warning(
                f"[deadlock] {len(incomplete)} 个任务无法执行 "
                f"(depends_on 无法满足)，强制终止"
            )
            # 给用户一个兜底回复
            return END

        return "wave_planner"

    # 聚合回复
    chain_results = [r for r in results if r.get("depends_on")]
    if chain_results and not state.get("final_response"):
        return "response_gen"

    return END


# ─────────────────────────────────────────────────────────────
# 构建图
# ─────────────────────────────────────────────────────────────

def _build_graph():
    """构建 StateGraph（不绑定 checkpointer），供不同场景复用"""
    graph = StateGraph(CabinAgentState)

    graph.add_node("message_compressor", message_compressor)
    graph.add_node("fast_rules",         fast_rules_node)
    graph.add_node("intent_classifier", intent_classifier)
    graph.add_node("wave_planner",      _empty_planner)
    graph.add_node("task_pipeline",     task_pipeline)
    graph.add_node("session_update",    session_update)
    graph.add_node("wave_aggregator",   wave_aggregator)
    graph.add_node("response_gen",      response_gen)
    graph.add_node("chitchat_handler",  chitchat_handler)

    # 入口：先压缩历史消息，再 FastRules 前置检查，最后意图识别
    graph.set_entry_point("message_compressor")
    graph.add_edge("message_compressor", "fast_rules")

    # FastRules 条件路由：命中短路 → 直接走任务/闲聊，未命中 → LLM
    graph.add_conditional_edges(
        "fast_rules",
        route_after_fast_rules,
        {
            "intent_classifier": "intent_classifier",
            "chitchat_handler": "chitchat_handler",
            "wave_planner": "wave_planner",
        },
    )

    graph.add_conditional_edges(
        "intent_classifier",
        route_after_intent,
        {"chitchat_handler": "chitchat_handler", "wave_planner": "wave_planner"},
    )

    graph.add_conditional_edges("wave_planner", route_wave, ["task_pipeline", "wave_aggregator"])

    graph.add_edge("task_pipeline", "session_update")
    graph.add_edge("session_update", "wave_aggregator")

    graph.add_conditional_edges(
        "wave_aggregator",
        route_after_aggregate,
        {"wave_planner": "wave_planner", "response_gen": "response_gen", END: END},
    )

    graph.add_edge("response_gen", END)
    graph.add_edge("chitchat_handler", END)

    return graph


def build_graph_with_checkpointer(checkpointer):
    """用给定的 checkpointer 编译图（测试用 MemorySaver，生产用 SqliteSaver）"""
    return _build_graph().compile(checkpointer=checkpointer)


async def build_cabin_agent_graph():
    """生产环境入口：SQLite 持久化 checkpoint"""
    os.makedirs("./data", exist_ok=True)
    conn = await aiosqlite.connect("./data/checkpoints.db")
    memory = AsyncSqliteSaver(conn=conn)
    await memory.setup()
    return build_graph_with_checkpointer(memory)


def _empty_planner(state: CabinAgentState) -> dict:
    # 空节点，不做任何处理，仅作为 conditional_edges 的挂载点
    # 设计原因：解耦路由逻辑
    #   - route_after_intent 只管"闲聊 vs 任务"
    #   - route_wave 只管"哪些任务就绪可以并发执行"
    # 如果合并成一个路由函数，职责混杂，违反单一职责原则
    return {}


cabin_agent = None  # lazy init，由 init_agent() 异步创建
