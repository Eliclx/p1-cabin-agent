"""
project1_cabin_agent/nodes/pipeline.py
节点 2：单任务流水线（槽位校验 → 安全校验 → 工具直调）。
由 Send 并发注入 current_task。
"""
from __future__ import annotations

import asyncio
import json

from langchain_core.messages import HumanMessage
from langgraph.types import Command, interrupt

from project1_cabin_agent.state import CabinAgentState
from project1_cabin_agent.tools.cabin_tools import (
    TOOL_REGISTRY, INTENT_TO_TOOL,
)
from shared.utils.llm_factory import get_llm
from shared.utils.logger import logger
from shared.utils.metrics import track_node

from project1_cabin_agent.nodes import user_profile

from project1_cabin_agent.nodes.schema import DYNAMIC_SCHEMA
from project1_cabin_agent.nodes.intent import _validate_slots
from project1_cabin_agent.nodes.message_utils import _ensure_str, _parse_json

# v3 新路径
from project1_cabin_agent.skills.registry import (
    is_intent_migrated,
    get_domain_for_intent,
    get_harness,
    get_tool_function,
)
from project1_cabin_agent.nodes.context_enrich import enrich_context_for_task


# ═══════════════════════════════════════════════
# 辅助函数（Prompt、规则判断、模板）
# ═══════════════════════════════════════════════

# ── 槽位提取 Prompt ──

SLOT_EXTRACT_PROMPT = """从用户回答中提取缺失槽位的值。只返回纯 JSON，不要加任何额外文字。

缺少的槽位：{missing_slots}
当前意图：{intent}
已知道的信息：{known_slots}
用户回答：{user_reply}

规则：
1. 每个缺失槽位必须出现在 JSON 中（值是提取到的内容，提取不到则为空字符串 ""）
2. 槽位值只能是简单字符串/数字，不要嵌套对象
3. 只输出一行纯 JSON，不要换行，不要 markdown 代码块，不要解释

示例输出：{{"action": "adjust_volume"}}"""


def _extract_slots_from_reply(missing_slots: list, user_reply: str, intent: str) -> dict:
    """用 LLM 从用户回答中提取缺失的槽位值。解析失败时重试一次。"""
    llm = get_llm("fast", temperature=0)
    prompt = SLOT_EXTRACT_PROMPT.format(
        missing_slots=missing_slots,
        intent=intent,
        known_slots="{}",
        user_reply=user_reply,
    )
    for attempt in range(2):
        try:
            resp = llm.invoke([HumanMessage(content=prompt)])
            raw = _ensure_str(resp.content).strip()
            extracted = _parse_json(raw)
            if not isinstance(extracted, dict):
                raise ValueError(f"非 dict: {type(extracted)}")
            return {k: v for k, v in extracted.items() if v and k in missing_slots}
        except Exception as e:
            if attempt == 0:
                logger.warning(f"[槽位提取] 第1次失败: {e}，重试...")
            else:
                logger.error(f"[槽位提取] 重试仍失败: {e}，raw={raw[:200]}")
                return {}


# ── 确认相关 ──

def _is_confirm_positive(answer: str) -> bool:
    a = answer.strip().lower()
    return any(w in a for w in ("确认", "是的", "好", "可以", "确定", "打开", "开", "执行", "要", "是"))


# 取消关键词：短输入快速路径
_CANCEL_KEYWORDS = (
    "算了", "不用了", "取消", "不要了", "不开了", "别开", "别了",
    "算了算了", "不用", "不要", "不了", "放弃", "停下", "算了吧",
)


def _is_cancel_answer(answer: str) -> bool:
    """
    判断用户回答是否表示取消（两层漏斗）。
    第一层：规则匹配（0ms）
    第二层：LLM 语义判断（~200ms）
    """
    a = answer.strip().lower()
    # ── 第一层：规则快速路径 ──
    if any(kw in a for kw in _CANCEL_KEYWORDS):
        return True

    # ── 第二层：LLM 兜底 ──
    try:
        llm = get_llm("fast", temperature=0)
        prompt = (
            f"用户被系统追问确认，用户回答：\"{answer}\"\n"
            f"用户是想取消操作，还是想继续？只回答一个字：\"取\"或\"续\""
        )
        resp = llm.invoke([HumanMessage(content=prompt)])
        result = _ensure_str(resp.content).strip()
        return result.startswith("取")
    except Exception as e:
        logger.warning(f"[取消判断] LLM 失败，默认不取消: {e}")
        return False


# ── 新意图检测（追问恢复后用户改主意） ──

# 规则层：包含这些关键词的输入大概率是新意图，不是在回答追问
_NEW_INTENT_KEYWORDS = (
    "导航去", "导航到", "搜索", "附近有", "找一", "帮我查",
    "播放", "开启", "关闭", "打开", "帮我开", "帮我关",
    "关灯", "开灯", "关窗", "开窗", "调到",
    "查一下", "多少油", "多少电", "胎压",
)


def _detect_redirect(user_input: str, current_intent: str) -> dict | None:
    """
    检测用户回答是否包含新意图（两层漏斗）。
    返回新意图的 sub_task dict，或 None（表示没有新意图）。
    
    场景：系统问"确认要打开车窗吗？"，用户回答"算了帮我开灯"
    → 取消开窗 + 新意图"开灯"
    """
    a = user_input.strip()
    if not a:
        return None

    # ── 第一层：规则快速路径 ──
    for kw in _NEW_INTENT_KEYWORDS:
        if kw in a:
            # 找到匹配的 intent（简单映射，不需要 LLM）
            redirect = _quick_intent_map(a)
            if redirect and redirect.get("intent") != current_intent:
                logger.info(f"[新意图检测] 规则命中 '{kw}'，重定向到 {redirect['intent']}")
                return redirect

    # ── 第二层：LLM 兜底 ──
    try:
        llm = get_llm("fast", temperature=0)
        prompt = (
            f"系统在追问用户关于「{current_intent}」的信息，用户回答：\"{a}\"\n"
            f"用户是在回答追问，还是提出了一个全新的请求？\n"
            f"如果是全新请求，识别意图和参数，返回JSON：{{\"intent\": \"xxx\", \"extracted_slots\": {{...}}}}\n"
            f"如果是在回答追问，返回：{{\"intent\": null}}\n"
            f"只返回JSON，不要解释。"
        )
        resp = llm.invoke([HumanMessage(content=prompt)])
        result_text = _ensure_str(resp.content).strip()
        parsed = _parse_json(result_text)
        new_intent = parsed.get("intent")
        if new_intent and new_intent != current_intent and new_intent != "null":
            slots = parsed.get("extracted_slots", {})
            logger.info(f"[新意图检测] LLM 检测到新意图: {new_intent}, slots={slots}")
            return {
                "task_id": "task_redirect_0",
                "intent": new_intent,
                "extracted_slots": slots,
                "depends_on": [],
                "urgency": "normal",
            }
    except Exception as e:
        logger.debug(f"[新意图检测] LLM 失败，忽略: {e}")

    return None


def _quick_intent_map(text: str) -> dict | None:
    """规则层：从用户输入快速映射到意图。"""
    mappings = [
        (["导航去", "导航到", "去"], "start_navigation"),
        (["搜索", "附近有", "找"], "search_poi"),
        (["空调", "调到", "有点冷", "太热"], "ac_control"),
        (["播放", "放音乐", "听"], "media_control"),
        (["开灯", "关灯", "灯光"], "light_control"),
        (["开窗", "关窗", "天窗"], "window_control"),
        (["座椅"], "seat_control"),
        (["油", "电量", "胎压", "里程"], "query_vehicle_status"),
    ]
    for keywords, intent in mappings:
        for kw in keywords:
            if kw in text:
                return {
                    "task_id": "task_redirect_0",
                    "intent": intent,
                    "extracted_slots": {},
                    "depends_on": [],
                    "urgency": "normal",
                }
    return None


def _execute_confirmed(intent: str, slots: dict, tool_result: dict = None) -> dict:
    """确认后执行高风险工具：从 TOOL_REGISTRY 查表调用 confirmed_execute。"""
    tool_name = INTENT_TO_TOOL.get(intent, "")
    executor = TOOL_REGISTRY.get(tool_name, {}).get("confirmed_execute")
    if executor:
        return executor(slots, tool_result or {})
    return {"status": "success", "voice_reply": "好的，已执行"}


# ── 闲聊回复（pipeline 内 chitchat 分支复用） ──

def _chitchat_reply(user_input: str, messages: list) -> str:
    """统一的闲聊回复逻辑。"""
    from project1_cabin_agent.nodes.message_utils import _format_history
    try:
        llm = get_llm("fast", temperature=0.7)
        history = _format_history(messages)
        prompt = f"你是车载助手，简短回复（不超过20字）。\n对话历史：{history}\n用户：{user_input}"
        resp = llm.invoke([HumanMessage(content=prompt)])
        return _ensure_str(resp.content).strip()
    except Exception:
        return "好的"


# ── 歧义追问模板 ──

# intent 名 → 中文标签（面试可讲：来自工具定义，LLM 不编造）
INTENT_LABELS = {
    "open_window": "车窗", "ac_control": "空调", "media_control": "音乐/电台",
    "light_control": "灯光", "seat_control": "座椅", "window_control": "车窗/车门",
    "search_poi": "搜索附近", "start_navigation": "导航", "query_vehicle_status": "车辆状态",
    "parking": "停车", "activate_scene": "场景模式",
}

def _build_clarify_reply(candidates: list) -> str:
    """根据候选意图列表，模板拼装追问文本（0ms，不调 LLM）。"""
    if not candidates:
        return "请问您具体想做什么？"
    labels = [INTENT_LABELS.get(c, c) for c in candidates]
    options = "、".join(labels)
    return f"请问您具体是指哪个操作？({options})"


# ═══════════════════════════════════════════════
# result 工厂函数
# ═══════════════════════════════════════════════

def _make_result(task_id: str, intent: str, voice_reply: str,
                 task: dict, msgs: list = None, **extra) -> dict:
    """统一拼装 task_pipeline 的返回 dict。"""
    result_item = {
        "task_id": task_id,
        "status": extra.pop("status", "done"),
        "intent": intent,
        "voice_reply": voice_reply,
        "urgency": task.get("urgency", "normal"),
        "depends_on": task.get("depends_on", []),
    }
    # 可选字段
    for key in ("tool_result", "error", "missing_slots"):
        if key in extra:
            result_item[key] = extra.pop(key)
    ret = {
        "task_results": [result_item],
        "completed_task_ids": extra.pop("completed_ids", [task_id]),
    }
    if msgs:
        ret["messages"] = msgs
    # 兜底：其他额外字段直接透传（如 clarify_count）
    ret.update(extra)
    return ret


# ═══════════════════════════════════════════════
# interrupt 恢复处理（两个 interrupt 点共用）
# ═══════════════════════════════════════════════

def _handle_resume(question: str, user_answer: str, intent: str,
                   task: dict, task_id: str, msgs: list) -> dict | Command | None:
    """
    interrupt 恢复后的统一分支处理：取消→重定向 / 取消 / 继续放行。
    返回 dict/Command 表示终结，返回 None 表示继续往下执行工具。
    """
    # ── 取消分支 ──
    if _is_cancel_answer(user_answer):
        logger.info(f"[interrupt恢复] 用户取消，意图={intent}")
        redirect = _detect_redirect(user_answer, intent)
        if redirect:
            logger.info(f"[interrupt恢复] 取消 + 重定向到 {redirect['intent']}")
            return Command(
                update={
                    **_make_result(task_id, intent, "好的，已取消操作", task, msgs,
                                   tool_result={}),
                    "sub_tasks": [redirect],
                    "is_complex": False,
                    "intent": redirect["intent"],
                },
                goto="wave_planner",
            )
        # 纯取消
        return _make_result(task_id, intent, "好的，已取消操作", task, msgs,
                            tool_result={})

    return None  # 非取消，交由调用方继续处理


# ═══════════════════════════════════════════════
# v3 新路径：skill-based task handler
# ═══════════════════════════════════════════════

async def _handle_skill_task(state: CabinAgentState, task_id: str, task: dict,
                              intent: str, slots: dict) -> dict | Command:
    """
    v3 新路径：harness → context_enrich → tool → format_response。
    已迁移的 domain（目前只有 navigation）走这条路径。
    未迁移的 domain 走旧路径 _handle_tool_task。

    流程：
      1. registry 路由（domain → harness + tool_fn）
      2. context_enrich（按 CONTEXT_DEPS 组装 AgentContext）
      3. harness.pre_validate（必填检查 + 别名解析 + 默认值补全）
      4. 工具执行
      5. harness.post_validate（API 失败兜底 + 异常值拦截）
      6. 高风险确认（复用 interrupt）
      7. harness.format_response（确定性格式化）
    """
    msgs: list = []

    # ── 1. registry 路由 ──
    domain = get_domain_for_intent(intent)
    if not domain:
        # 不应该走到这里（task_pipeline 已经过滤），安全兜底
        logger.error(f"[skill_task] intent={intent} 不在已迁移 domain 中，回退旧路径")
        return await _handle_tool_task(state, task_id, task, intent, slots)

    harness = get_harness(domain)
    tool_fn = get_tool_function(domain, intent)

    if not harness:
        logger.error(f"[skill_task] {domain} harness 加载失败，回退旧路径")
        return await _handle_tool_task(state, task_id, task, intent, slots)

    if not tool_fn:
        return _make_result(task_id, intent, "抱歉，该功能暂时不可用", task,
                            status="error", error=f"tool_fn not found: {domain}.{intent}")

    # ── 2. context_enrich ──
    ctx = enrich_context_for_task(state, task)
    if ctx is None:
        logger.warning(f"[skill_task] context_enrich 返回 None，使用空 AgentContext")
        from project1_cabin_agent.harness.context import AgentContext
        ctx = AgentContext()

    # ── 3. harness.pre_validate ──
    # 注入 _intent，供 harness 按意图分发子校验器（climate 域需要区分 ac/window/light/seat）
    slots = {**slots, "_intent": intent}
    pre_result = harness.pre_validate(slots, ctx)

    # 3a. 追问（缺必填槽位）
    if not pre_result.valid and pre_result.need_clarify:
        clarify_msg = pre_result.clarify_message or "请提供更多信息"
        clarify_count = state.get("clarify_count", 0)

        if clarify_count < 3:
            user_answer = interrupt({
                "question": clarify_msg,
                "missing_slots": [k for k in pre_result.slots if not pre_result.slots.get(k)],
                "task_id": task_id,
                "intent": intent,
            })
            msgs = [
                {"role": "assistant", "content": clarify_msg},
                {"role": "user", "content": user_answer},
            ]
            logger.info(f"[skill追问] 用户回答: {user_answer}")

            # 取消/重定向
            cancelled = _handle_resume(clarify_msg, user_answer, intent, task, task_id, msgs)
            if cancelled:
                return cancelled

            # 从回答中提取 slot 并重新校验
            missing = [k for k in pre_result.slots if not pre_result.slots.get(k)]
            if missing:
                new_slots = _extract_slots_from_reply(missing, user_answer, intent)
                slots.update(new_slots)

            # 二次 pre_validate
            pre_result = harness.pre_validate(slots, ctx)

            if not pre_result.valid and pre_result.need_clarify:
                # 仍然缺槽位
                still_missing_msg = pre_result.clarify_message or "还需要更多信息"
                return {
                    **_make_result(task_id, intent, still_missing_msg, task, msgs,
                                   status="need_clarify",
                                   missing_slots=list(pre_result.slots.keys()),
                                   completed_ids=[]),
                    "clarify_count": clarify_count + 1,
                }
        else:
            logger.warning(f"[skill追问] 超过上限({clarify_count})，用现有 slots 强制执行")

    # 3b. pre_validate 失败（非追问，如 fallback）
    if not pre_result.valid and not pre_result.need_clarify:
        fallback_msg = pre_result.block_reason or "输入校验失败"
        logger.warning(f"[skill_task] pre_validate 失败: {fallback_msg}")
        return _make_result(task_id, intent, "抱歉，无法处理您的请求，请换个方式说试试",
                            task, status="error", error=fallback_msg)

    # pre_validate 通过，使用修正后的 slots
    slots = pre_result.slots
    logger.info(f"[skill_task] pre_validate 通过, slots={slots}")

    # ── 4. 工具执行 ──
    # skill 纯函数：过滤内部字段，**kwargs 展开；LangChain @tool：走 .ainvoke()
    exec_slots = {k: v for k, v in slots.items() if not k.startswith("_")}
    try:
        if hasattr(tool_fn, "ainvoke"):
            result = await asyncio.wait_for(tool_fn.ainvoke(exec_slots), timeout=8)
        else:
            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, lambda: tool_fn(**exec_slots)),
                timeout=8,
            )
    except asyncio.TimeoutError:
        logger.error(f"[skill_task] 工具超时: {domain}.{intent}")
        return _make_result(task_id, intent, "操作超时，请稍后再试", task, msgs,
                            status="error", error="timeout")
    except Exception as e:
        logger.error(f"[skill_task] 工具执行失败: {e}")
        # 走 harness.post_validate 的失败兜底
        post_result = harness.post_validate({"status": "error", "error": str(e)}, ctx)
        if not post_result.valid:
            fallback_reply = harness.format_response({"status": "error"})
            return _make_result(task_id, intent, fallback_reply, task, msgs,
                                status="error", error=str(e))
        return _make_result(task_id, intent, "操作过程中发生错误", task, msgs,
                            status="error", error=str(e))

    # ── 5. harness.post_validate ──
    tool_result = result if isinstance(result, dict) else {"raw": result}
    post_result = harness.post_validate(tool_result, ctx)

    if not post_result.valid:
        # API 失败兜底 / 异常值拦截
        if post_result.need_confirm:
            # 异常值需要确认（如距离太远）
            confirm_question = post_result.confirm_message or "请确认"
            user_answer = interrupt({
                "question": confirm_question,
                "task_id": task_id,
                "intent": intent,
                "is_confirm": True,
            })
            msgs += [
                {"role": "assistant", "content": confirm_question},
                {"role": "user", "content": user_answer},
            ]
            cancelled = _handle_resume(confirm_question, user_answer, intent, task, task_id, msgs)
            if cancelled:
                return cancelled
            if not _is_confirm_positive(user_answer):
                return _make_result(task_id, intent, "好的，已取消", task, msgs, tool_result={})

        elif post_result.need_clarify:
            # post_validate 发现问题需要追问
            clarify_msg = post_result.clarify_message or "请提供更多信息"
            return _make_result(task_id, intent, clarify_msg, task, msgs,
                                status="need_clarify")
        else:
            # 直接兜底回复
            fallback_reply = harness.format_response(tool_result)
            return _make_result(task_id, intent, fallback_reply, task, msgs,
                                tool_result=tool_result)

    # ── 6. 高风险确认（tool 返回 need_confirm） ──
    if isinstance(tool_result, dict) and tool_result.get("status") == "need_confirm":
        confirm_question = tool_result.get("voice_reply", "请确认")
        user_answer = interrupt({
            "question": confirm_question,
            "task_id": task_id,
            "intent": intent,
            "is_confirm": True,
        })
        msgs += [
            {"role": "assistant", "content": confirm_question},
            {"role": "user", "content": user_answer},
        ]
        logger.info(f"[skill确认] 用户回答: {user_answer}")

        cancelled = _handle_resume(confirm_question, user_answer, intent, task, task_id, msgs)
        if cancelled:
            return cancelled

        if not _is_confirm_positive(user_answer):
            return _make_result(task_id, intent, "好的，已取消", task, msgs, tool_result={})

    # ── 7. harness.format_response ──
    voice_reply = harness.format_response(tool_result)

    # L2 记忆写入
    user_profile.save_from_tool_result(intent, slots)

    logger.info(f"[skill_task] {domain}.{intent} 完成, reply={voice_reply}")
    return _make_result(task_id, intent, voice_reply, task, msgs,
                        tool_result=tool_result)


# ═══════════════════════════════════════════════
# task_pipeline 子处理器（旧路径）
# ═══════════════════════════════════════════════

def _handle_chitchat(state: CabinAgentState, task_id: str, task: dict) -> dict:
    """闲聊分支：调 LLM 生成简短回复。"""
    reply = _chitchat_reply(state["user_input"], state.get("messages", []))
    return _make_result(task_id, "chitchat", reply, task)


def _handle_clarify(state: CabinAgentState, task_id: str, task: dict,
                     slots: dict) -> dict:
    """歧义追问分支：模板拼装，0ms，不调 LLM。"""
    clarify_count = state.get("clarify_count", 0) + 1
    if clarify_count > 2:
        logger.warning(f"[歧义追问] 连续追问 {clarify_count} 次，降级 chitchat")
        return _make_result(task_id, "chitchat", "抱歉没太明白，您可以换个方式说试试",
                            task, clarify_count=0)
    candidates = slots.get("candidates", [])
    reply = _build_clarify_reply(candidates)
    logger.info(f"[歧义追问] candidates={candidates}, reply={reply}, count={clarify_count}")
    return _make_result(task_id, "clarify", reply, task, clarify_count=clarify_count)


def _handle_direct_answer(state: CabinAgentState, task_id: str, task: dict,
                           slots: dict) -> dict:
    """直接回答分支：调 LLM 根据 dialogue_context + user_input 生成回复。"""
    ctx = state.get("dialogue_context", {})
    ctx_text = json.dumps(ctx, ensure_ascii=False, indent=2) if ctx else "（无）"
    direct_prompt = (
        f"根据以下上下文数据，简短回答用户的问题。\n"
        f"只使用数据中有的信息，不要编造。如果是常识问题上下文无数据，用自身知识回答。\n\n"
        f"上下文数据：\n{ctx_text}\n\n"
        f"用户问题：{state['user_input']}\n"
        f"回答："
    )
    try:
        llm = get_llm("fast", temperature=0.1)
        resp = llm.invoke(direct_prompt)
        reply = resp.content.strip() if hasattr(resp, "content") else str(resp).strip()
        logger.info(f"[直接回答] 生成回答: {reply}")
    except Exception as e:
        logger.error(f"[直接回答] LLM 调用失败: {e}")
        reply = "抱歉，我无法获取相关信息。"
    return _make_result(task_id, "direct_answer", reply, task)


def _resolve_ref(value: str, upstream_result: dict) -> str:
    """解析 LLM 引用表达式如 results[0].name → 实际值"""
    import re
    m = re.match(r"results\[(\d+)\]\.(\w+)", value)
    if not m:
        return value
    idx, field = int(m.group(1)), m.group(2)
    results = upstream_result.get("results", [])
    if idx < len(results) and field in results[idx]:
        return str(results[idx][field])
    return value


async def _handle_tool_task(state: CabinAgentState, task_id: str, task: dict,
                             intent: str, slots: dict) -> dict | Command:
    """
    工具任务分支：槽位检查 → interrupt → 工具执行 → 高风险确认 → interrupt。
    包含两个 interrupt 点，恢复后统一走 _handle_resume。
    """
    msgs: list = []

    # ── 1. 槽位缺失检查 → interrupt ──
    tool_name = INTENT_TO_TOOL.get(intent, "")
    schema = DYNAMIC_SCHEMA.get(tool_name, {})
    required = schema.get("required", [])
    missing = [s for s in required if s not in slots or not slots[s]]

    # L2 长期记忆填充：泛化指令用 slot→L2 映射补全偏好
    l2_mapping = user_profile.INTENT_TO_L2_KEY.get(intent, {})
    for slot_key, l2_key in l2_mapping.items():
        if slot_key in slots and not slots.get(slot_key):
            pref = user_profile.get_preference(l2_key)
            if pref:
                slots[slot_key] = pref
                logger.info(f"[L2记忆] -> {slot_key} ← {l2_key} = {pref}")

    # depends_on 参数提取：从上游已完成任务/黑板中解析引用表达式
    depends_on = task.get("depends_on", [])
    if depends_on:
        logger.info(f"[依赖提取] task={task_id} depends_on={depends_on}, slots={slots}")
        ctx = state.get("dialogue_context", {})
        for dep_id in depends_on:
            upstream_result = {}
            # 1) 从 task_results 找
            task_results = state.get("task_results", [])
            upstream = next((r for r in task_results if r.get("task_id") == dep_id and r.get("status") == "done"), None)
            if upstream:
                upstream_result = upstream.get("tool_result", {})
                logger.info(f"[依赖提取] 从 task_results 找到 {dep_id}")
            # 2) 从 dialogue_context 找
            if not upstream_result:
                for entity_tag, entity_data in ctx.items():
                    if isinstance(entity_data, dict) and entity_data.get("task_id") == dep_id:
                        upstream_result = entity_data.get("data", {})
                        logger.info(f"[依赖提取] 从 dialogue_context.{entity_tag} 找到 {dep_id}")
                        break
            # 3) 还没找到
            if not upstream_result:
                logger.warning(f"[依赖提取] 未找到上游 {dep_id}, ctx keys={list(ctx.keys())}")
                continue
            # 解析引用表达式如 results[0].name
            for k, v in list(slots.items()):
                if isinstance(v, str) and "results[" in v:
                    resolved = _resolve_ref(v, upstream_result)
                    if resolved != v:
                        slots[k] = resolved
                        logger.info(f"[依赖提取] {k}: '{v}' → '{resolved}'")
                    else:
                        logger.warning(f"[依赖提取] _resolve_ref 未解析: {v}")
            # 补全缺失的 required slot：从上游 results[0] 取第一个结果
            upstream_results = upstream_result.get("results", [])
            if upstream_results:
                for req in required:
                    if req not in slots or not slots[req]:
                        # 尝试 results[0].<req>，如 destination → results[0].name
                        candidate_fields = {
                            "destination": "name",
                            "location": "address",
                        }
                        field = candidate_fields.get(req, req)
                        if field in upstream_results[0]:
                            slots[req] = str(upstream_results[0][field])
                            logger.info(f"[依赖提取] 自动补全: {req} = {slots[req]} (from results[0].{field})")

    if missing and state.get("clarify_count", 0) < 3:
        slot_names = "、".join(missing)
        question = f"请告诉我您想{slot_names}是？"

        user_answer = interrupt({
            "question": question,
            "missing_slots": missing,
            "task_id": task_id,
            "intent": intent,
        })
        msgs = [
            {"role": "assistant", "content": question},
            {"role": "user", "content": user_answer},
        ]
        logger.info(f"[追问恢复] 用户回答: {user_answer}，尝试提取 {missing}")

        # 取消/重定向
        cancelled = _handle_resume(question, user_answer, intent, task, task_id, msgs)
        if cancelled:
            return cancelled

        # 提取 slot 并更新
        new_slots = _extract_slots_from_reply(missing, user_answer, intent)
        slots.update(new_slots)
        task["extracted_slots"] = slots

        still_missing = [s for s in required if s not in slots or not slots[s]]
        if still_missing and state.get("clarify_count", 0) < 2:
            slot_names2 = "、".join(still_missing)
            clarify2 = f"还需要您告诉我{slot_names2}"
            return {
                **_make_result(task_id, intent, clarify2, task,
                               msgs + [{"role": "assistant", "content": clarify2}],
                               status="need_clarify", missing_slots=still_missing,
                               completed_ids=[]),
                "clarify_count": state.get("clarify_count", 0) + 1,
            }
        elif still_missing:
            logger.warning(f"[追问] 超过上限，强制执行，缺失={still_missing}")

    elif missing:
        logger.warning(f"[追问] 超过上限，强制执行，缺失={missing}")

    # ── 2. 工具路由 ──
    tool_name = INTENT_TO_TOOL.get(intent)
    if not tool_name:
        return _make_result(task_id, intent, f"抱歉，未知意图{intent}", task, msgs,
                            status="error", error=f"未知意图: {intent}")
    tool_fn = TOOL_REGISTRY.get(tool_name)
    tool_fn = tool_fn.get("function") if tool_fn else None
    if not tool_fn:
        return _make_result(task_id, intent, f"抱歉，未知工具{tool_name}", task, msgs,
                            status="error", error=f"未知工具: {tool_name}")

    # ── 3. 工具执行 ──
    try:
        result = await asyncio.wait_for(tool_fn.ainvoke(slots), timeout=8)
    except asyncio.TimeoutError:
        logger.error(f"[工具执行] 超时: {tool_name} 超过 8s")
        decs = DYNAMIC_SCHEMA.get(tool_name, {}).get("description", "")
        return _make_result(task_id, intent, f"{decs}操作超时，请稍后再试", task, msgs,
                            status="error", error="timeout")
    except Exception as e:
        logger.error(f"[工具执行] 失败: {e}")
        decs = DYNAMIC_SCHEMA.get(tool_name, {}).get("description", "")
        return _make_result(task_id, intent, f"执行{decs}过程中发生错误", task, msgs,
                            status="error", error=str(e))

    # ── 4. 高风险确认 → interrupt ──
    if isinstance(result, dict) and result.get("status") == "need_confirm":
        confirm_question = result.get("voice_reply", "请确认")
        user_answer = interrupt({
            "question": confirm_question,
            "task_id": task_id,
            "intent": intent,
            "is_confirm": True,
        })
        msgs += [
            {"role": "assistant", "content": confirm_question},
            {"role": "user", "content": user_answer},
        ]
        logger.info(f"[确认恢复] 用户回答: {user_answer}")

        # 取消/重定向
        cancelled = _handle_resume(confirm_question, user_answer, intent, task, task_id, msgs)
        if cancelled:
            return cancelled

        # 确认执行
        if _is_confirm_positive(user_answer):
            confirmed_result = _execute_confirmed(intent, slots, result)
            voice_reply = confirmed_result.get("voice_reply", "好的，已执行")
            logger.info(f"[确认执行] {tool_name} 结果: {voice_reply}")
            return _make_result(task_id, intent, voice_reply, task, msgs,
                                tool_result=confirmed_result)

        # 模糊回答 → 默认取消
        logger.info(f"[确认恢复] 用户回答模糊，默认取消: {user_answer}")
        return _make_result(task_id, intent, "好的，已取消。如需操作请重新告诉我",
                            task, msgs, tool_result={})

    # ── 5. 正常返回 ──
    voice_reply = result.get("voice_reply", "") if isinstance(result, dict) else ""

    # L2 长期记忆：从工具结果自动写入用户画像
    user_profile.save_from_tool_result(intent, slots)

    logger.info(f"[子任务{task_id}] [工具调用]-[{tool_name}] [处理结果]-[{result}] [回复]-[{voice_reply}]")
    return _make_result(task_id, intent, voice_reply, task, msgs,
                        tool_result=result)


# ═══════════════════════════════════════════════
# 主入口：task_pipeline 节点
# ═══════════════════════════════════════════════

@track_node("task_pipeline")
async def task_pipeline(state: CabinAgentState) -> dict | Command:
    """单任务完整流水线：按意图路由到对应子处理器。"""
    task = state.get("current_task")
    if not task:
        return {"task_results": [], "completed_task_ids": []}

    intent = task.get("intent", "chitchat")
    slots = task.get("extracted_slots", {})
    task_id = task.get("task_id", "task_0")

    # ── 路由 ──
    if intent == "chitchat":
        return _handle_chitchat(state, task_id, task)

    if intent == "clarify":
        return _handle_clarify(state, task_id, task, slots)

    if intent == "direct_answer":
        return _handle_direct_answer(state, task_id, task, slots)

    if intent == "no_support":
        reply = slots.get("answer", "抱歉，目前不支持此功能")
        return _make_result(task_id, intent, reply, task)

    # 自动 OOS 兜底：意图不在已知列表中 → chitchat 降级（而非直接拒绝）
    KNOWN_INTENTS = {"chitchat", "clarify", "direct_answer", "no_support"} | set(DYNAMIC_SCHEMA.keys())
    if intent not in KNOWN_INTENTS:
        logger.warning(f"[OOS兜底] 未知意图: {intent}，降级 chitchat")
        return _handle_chitchat(state, task_id, task)

    # 所有工具意图
    # v3 新路径：已迁移的 domain 走 skill-based handler
    if is_intent_migrated(intent):
        return await _handle_skill_task(state, task_id, task, intent, slots)

    # 旧路径：未迁移的 intent 走 INTENT_TO_TOOL 查表
    return await _handle_tool_task(state, task_id, task, intent, slots)
