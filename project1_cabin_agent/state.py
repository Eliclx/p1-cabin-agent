"""
project1_cabin_agent/state.py
LangGraph 状态定义（Send fan-out 并发版）

设计原则：
- 全局 state 只保留跨任务需要的信息
- 单任务级别的字段通过 Send 注入 current_task，在 task_pipeline 内部局部处理
- task_results / completed_task_ids 使用 reducer 自动合并并发结果
"""
from typing import TypedDict, Annotated, List, Dict, Any, Optional
import operator
from typing import Optional as _Opt
from langgraph.graph import add_messages


def merge_dict(old: dict, new: _Opt[dict]) -> dict:
    """
    reducer: 栈式合并字典。新值压栈顶，同 key 不覆盖而是追加。
    
    用途：dialogue_context 的黑板栈式存储。
    例：search_poi 第1轮写入 entity.poi，第2轮再写入 → 栈里有两层，不覆盖。
    栈顶 = 最新值，栈底 = 最旧值。
    
    数据格式要求：new 的每个 value 必须是 dict（含 round/task_id/data 等元信息），
    由 session_update 负责打包，reducer 只做压栈。
    """
    if new is None:
        return old
    result = {**old}
    for key, value in new.items():
        if key in result and isinstance(result[key], list):
            # 已有栈 → 压栈顶
            result[key] = [value] + result[key]
        else:
            # 新 key → 初始化栈
            result[key] = [value]
    return result


def add_list_with_reset(old: list, new: _Opt[list]) -> list:
    """
    reducer: None 表示重置为空列表，否则累加。用于跨轮清空旧状态。
    
    工作原理：
        intent_classifier 返回 task_results=None → 触发重置 → 返回 []
        task_pipeline 返回 task_results=[{...}] → 累加到列表
    """
    if new is None:
        return []
    return old + new


class CabinAgentState(TypedDict):
    """
    全局状态 — 贯穿整个对话流程，由 LangGraph MemorySaver 做 checkpoint 持久化
    """

    # ── 对话 ──────────────────────────────────────
    messages: Annotated[list, add_messages]
        # 所有对话历史，add_messages reducer 支持：累加 + RemoveMessage 删除（压缩场景）
        # add_messages 自动将 dict 转为 LangChain Message 对象并分配唯一 id
        # RemoveMessage 删除见 intent.py message_compressor（滑动窗口 >30 条触发压缩）
        # 跨轮保留（checkpoint 持久化）；工具产出的结构化数据走 dialogue_context，不依赖此字段

    user_input: str
        # 当前用户的原始输入文本
        # 每轮由 main.py 注入，直接覆盖上一轮

    asr_confidence: float
        # 语音识别置信度（ASR = Automatic Speech Recognition）
        # 车载场景：语音输入时才有值，文本输入时为 0
        # 用途：低置信度时可以触发确认（"您是说XXX吗？"）
        # 当前项目未深度使用

    # ── 多意图调度 ────────────────────────────────
    sub_tasks: List[dict]
        # 当前轮拆解出的子任务列表
        # 由 intent_classifier 调 LLM 生成，每轮重建
        # 格式: [
        #   {"task_id": "task_0", "intent": "search_poi", "extracted_slots": {...}, "depends_on": []},
        #   {"task_id": "task_1", "intent": "ac_control", "extracted_slots": {...}, "depends_on": []},
        # ]
        # 生命周期：仅限本轮，intent_classifier 每轮重新生成

    is_complex: bool
        # 是否是多意图（sub_tasks 长度 > 1）
        # 供路由使用：单意图走 task_pipeline，多意图走 wave 并发调度
        # 生命周期：仅限本轮

    # ── Send 并发结果汇聚（reducer 自动追加）──
    task_results: Annotated[List[dict], add_list_with_reset]
        # 本轮所有已执行的工具返回结果
        # 由 task_pipeline 执行工具后写入，add_list_with_reset 做累加
        # intent_classifier 返回 None → reducer 重置为 []（每轮清空）
        # 格式: [{"task_id": "task_0", "intent": "search_poi", "data": {...}, "voice_reply": "找到2个加油站"}]
        # 生命周期：仅限本轮（intent_classifier 每轮 reset 为 []）
        # 注意：本字段跨轮丢失，但工具结果通过 session_update 写入 dialogue_context（黑板）
        # 所以"就去第二个"这类跨轮指代走黑板，不依赖此字段

    completed_task_ids: Annotated[List[str], add_list_with_reset]
        # 本轮已完成（成功或失败都算）的任务 ID 列表
        # 用途：route_wave 判断"这个任务的 depends_on 都完成了没"
        # 槽缺失的任务不算完成（task_pipeline 会跳过）
        # 生命周期：仅限本轮（intent_classifier 返回 None 重置）

    # ── 单任务上下文（Send 注入）───────────────
    current_task: Optional[dict]
        # 当前正在执行的子任务（由 Send fan-out 注入）
        # 用途：task_pipeline 拿到自己的任务，不跟其他并发任务混淆
        # 不是全局状态，是每个 task_pipeline 实例的局部变量
        # 写入时机：wave_planner 用 Send(task_pipeline, {"current_task": sub_task})

    # ── 意图（供闲聊路由使用）──────────────────
    intent: str
        # 当前轮的主意图名称
        # 用于 graph.py 的闲聊路由判断：chitchat → chitchat_handler
        # 取 sub_tasks[0].intent 或 carry-over 的 intent

    # ── 最终输出 ──────────────────────────────────
    final_response: str
        # 最终回复给用户的自然语言文本
        # 由 wave_aggregator（单意图）或 response_gen（依赖链）生成

    error: Optional[str]
        # 异常信息（如有），用于调试和兜底回复

    # ── 多轮追问 ──────────────────────────────────
    clarify_count: int
        # 当前轮连续追问次数（跨轮不重置，由 _handle_clarify 和 _handle_resume 维护）
        # 用途：防止无限追问 —— 连续 >2 次追问降级为 chitchat，>3 次缺槽直接强制执行
        # 重置时机：用户输入完整新指令时，intent_classifier 返回 clarify_count=0

    # ── OOS 标记（fast_rules → intent_classifier）──
    _oos_flag: Optional[str]
        # FastRules OOS 疑似命中时写入（值为 OOS reason，如 "点单""打电话"）
        # intent_classifier 检测到此 flag → 跳过端侧，强制走云端 LLM 二次判断
        # 云端判断 true OOS → no_support；误杀 → 正常流程
        # 生命周期：仅限本轮，intent_classifier 读取后重置为 None

    # ── 跨域多意图标记（fast_rules → intent_classifier）──
    _cross_domain_flag: Optional[bool]
        # FastRules 检测到跨域多意图时写入（True）
        # intent_classifier 检测到此 flag → 跳过端侧，强制走云端 LLM 拆子任务
        # 生命周期：仅限本轮，intent_classifier 读取后重置为 None

    # ── 对话帧追踪（Slot Carry-Over）────────────
    active_frames: List[dict]
        # 存"没完成的意图"——上一轮识别了意图但缺槽位，等用户下一轮补充
        # 格式: [
        #   {"task_id": "task_0", "intent": "start_navigation", "status": "pending",
        #    "required_slots": ["destination"], "extracted_slots": {}},
        # ]
        # 两个使用入口（均在 intent_classifier 内）：
        #   1) Stage 0 Slot Carry-Over：用户简短输入命中 pending 帧 → 直接填槽，0ms 跳过 LLM
        #   2) Stage 1 _needs_context：有 pending 帧 → 强制注入对话历史给 LLM
        # 上限：5 个 pending 帧，超出丢弃最旧的
        # 生命周期：跨轮保留（intent_classifier 每轮更新，不重置）
        # 注意：管的是"没做完的意图"，和 task_results（已做完）+ dialogue_context（已持久化）互补

    # ── L1 黑板栈式记忆 ─────────────────────────
    dialogue_context: Annotated[Dict[str, Any], merge_dict]
        # 黑板机制：工具产出实体按标签栈式存储，消费者按标签取值。
        # key = 实体标签（如 "entity.poi", "entity.route"）
        # value = 栈（list），每层含 {round, task_id, data}
        # 栈顶 = 最新，栈底 = 最旧，默认取栈顶
        # reducer: merge_dict（栈式压入，不覆盖）
        # 生命周期：跨轮保留，不每轮重置
        # 写入时机：session_update 节点从 task_results 提取并打包写入

    # ── L1.5 行程记忆（当前轮）──────────────────
    episodic_context: Optional[dict]
        # 本轮检索到的行程事件上下文（由 intent_classifier 的 Stage 1.5 写入）
        # 格式: {"text": "...", "raw": [...]} 或 None
        # 用途：chitchat_handler 等回复节点读取，生成自然语言回复
        # 生命周期：仅限本轮（intent_classifier 每轮重新设置）
