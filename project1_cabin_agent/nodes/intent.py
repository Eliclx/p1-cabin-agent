"""
project1_cabin_agent/nodes/intent.py
意图识别调度入口 — 串联 Stage 0~4，具体逻辑拆到子模块。

子模块：
  intent_compress.py  — 消息压缩
  intent_carry.py     — Carry-Over + 历史注入判断
  intent_drift.py     — 漂移检测
  intent_ambiguity.py — 歧义检测
  intent_slots.py     — 槽位校验 + 降级结果
"""
import json

from langchain_core.messages import HumanMessage

from project1_cabin_agent.state import CabinAgentState
from project1_cabin_agent.vehicle_state import vehicle_state
from shared.utils.llm_factory import get_llm
from shared.utils.logger import logger
from shared.utils.metrics import track_node

from project1_cabin_agent.nodes.schema import DYNAMIC_SCHEMA, PROMPT_TOOLS_TEXT
from project1_cabin_agent.nodes.constants import IntentOutput
from project1_cabin_agent.nodes.constants import STRONG_COREFERENCE
from project1_cabin_agent.nodes.message_utils import _ensure_str, _format_history, _parse_json

# 从子模块 import
from project1_cabin_agent.nodes.intent_compress import message_compressor
from project1_cabin_agent.nodes.post_rules import _try_carry_over, _needs_context
from project1_cabin_agent.nodes.post_rules import _detect_context_bleeding
from project1_cabin_agent.nodes.post_rules import _detect_ambiguity
from project1_cabin_agent.nodes.intent_slots import _validate_slots, _create_fallback_result
from project1_cabin_agent.nodes.episodic_memory import retrieve_episodic_context, has_temporal_keywords


# ── 端侧门控（独立于 _needs_context）──

# 多意图连接词 → 可能多意图，端侧不处理
_MULTI_INTENT_MARKERS = {"然后", "顺便", "同时", "并且", "另外"}

# 极短模糊输入 → 太模糊，端侧可能误判
_ULTRA_SHORT_AMBIGUOUS = {"开", "关", "好", "行", "嗯", "哦", "啊", "停", "换", "来", "去"}

# 序数指代词模式 → "第二个"/"第3个" 等需要历史上下文
import re
_ORDINAL_COREFERENCE = re.compile(r"第[一二两三四五六七八九十\d]+")


def _can_use_edge(user_input: str, active_frames: list) -> bool:
    """端侧快路径门控：判断当前输入是否适合走端侧 3B。
    
    设计原则：
    - 端侧只做独立简单意图，不包揽复杂/多意图/指代消解
    - 门槛比 _needs_context 宽松——不需要≥8字，不需要独立关键词
    - 即使端侧 miss，conf < 0.85 会自动 fallback 到云端（安全网）
    """
    text = user_input.strip()
    
    # 0. 空输入 → 端侧不处理
    if not text:
        return False

    # 0b. 含时间回溯词 → 需要行程记忆，端侧不接
    if has_temporal_keywords(text):
        return False
    
    # 1. 有未完成任务 → 需要上下文，端侧不接
    if any(f.get("status") == "pending" for f in active_frames):
        return False
    
    # 2. 强烈指代词 → 指代消解，端侧不接
    # 注："最近的"已移除——"最近的加油站"是独立导航目标非指代
    # 但"最近的"+"追问词"（有多远/是哪个/在哪里）是追问，端侧不接
    if any(w in text for w in STRONG_COREFERENCE):
        return False

    # 2b. "最近的" + 追问模式 → 需要上下文
    _FOLLOWUP_AFTER_NEAREST = re.compile(r"最近的.{0,4}(有多远|多远|是哪个|哪个|在哪里|在哪|怎么样|多少钱|电话|评价)")
    if _FOLLOWUP_AFTER_NEAREST.search(text):
        return False

    # 2c. 最高级指代（"最远的""评分最高的""最近的一个"）→ 无具体名词时是上下文指代
    # "最X的" 后面如果没有真实目标名词 → 指代上轮结果，端侧不接
    _SUPERLATIVE_REF = re.compile(r"最[^的]{0,3}的")
    if _SUPERLATIVE_REF.search(text):
        m = _SUPERLATIVE_REF.search(text)
        after = text[m.end():].strip()
        # 量词/虚词不算真实目标：一个、那个、这家、那种...
        _NON_TARGETS = {"一个", "一家", "那个", "这家", "那种", "这个", "那种", "一间", "一座"}
        if not after or after in _NON_TARGETS or len(after) < 2:
            return False

    # 2d. 序数指代词
    if _ORDINAL_COREFERENCE.search(text):
        return False

    # 2e. 追问模式（有多远/多久/怎么样/多少钱）→ 需要上轮上下文
    _FOLLOWUP_PATTERNS = re.compile(r"(有多远|多远|还有多远|多久|还有多久|怎么样|好不好|多少钱|电话|评价|营业时间)")
    if _FOLLOWUP_PATTERNS.search(text) and len(text) <= 10:
        return False
    
    # 3. 多意图连接词 → 可能多意图，端侧不接
    if any(w in text for w in _MULTI_INTENT_MARKERS):
        return False

    # 3b. 逗号/顿号分割 → 两边都有可执行关键词 → 多意图
    _ACTION_KEYWORDS = {"开", "关", "调", "放", "播", "导", "去", "搜", "查", "看", "听",
                        "切换", "换", "暂停", "继续", "停止", "切歌", "下一首", "上一首"}
    for sep in ("，", "、"):
        if sep in text:
            parts = [p.strip() for p in text.split(sep) if p.strip()]
            actionable = sum(1 for p in parts if any(k in p for k in _ACTION_KEYWORDS))
            if actionable >= 2:
                return False

    # 4. 极短模糊输入
    if len(text) <= 2 and text in _ULTRA_SHORT_AMBIGUOUS:
        return False
    
    # 其余：端侧可尝试
    return True


# ── 意图识别 Prompt ──

INTENT_PROMPT = """你是车载语音助手意图理解中枢。分析用户输入，理解情绪需求并响应（如用户冷热感则考虑调空调），高情商处理。返回纯 JSON。

【核心原则】：
1. 每条输入优先作为独立新指令，短输入（≤4字）警惕历史污染
2. 仅含指代词（"这个/那个/最近的/第N个"）时参考历史
3. 槽位提取规则：
   a) 优先从用户输入提取槽位值
   b) 用户用时间词（昨天/上次/前天等）引用过去事件时，行程数据是权威来源，直接从中提取对应值填入槽位
      （例：用户说"去昨天那个餐厅"→行程有"海底捞火锅"→destination填"海底捞火锅"）
   c) 禁止从 [对话历史] 编造槽位值
   d) 只有行程数据确实不包含用户引用的信息时才 clarify

【上轮结果引用】：
dialogue_context 含上轮工具结果，仅含指代词时参考。指代时直接填 extracted_slots，不创建额外搜索任务，depends_on=[]。询问上轮结果细节（"第2个是什么""最远的是哪个"）用 direct_answer，slots留空。禁止用 direct_answer 编造需实时数据的答案。指令模糊/缺少操作对象时用 clarify，并在 extracted_slots 中填入 clarify_message（如"请问您想去哪里？""请问您想搜索什么？"）。超能力范围用 no_support。

""" + PROMPT_TOOLS_TEXT + """

【多意图】：绝大多数独立执行 depends_on=[]。仅B需A输出时才设依赖（如"找加油站再导航"）。"然后/顺便/再"≠依赖。depends_on 只填同轮 task_id，严禁虚构。严禁参数脑补。

【指代选取】：模糊指代上轮搜索结果时用 sort_by(distance/rating)、sort_order(asc/desc)、pick(0起索引)。"最近的"→sort_by=distance,pick=0；"第N个"→pick=N-1；"评分最高的"→sort_by=rating,sort_order=desc,pick=0。用户说具体名字时直接填slot，不用sort_by/pick。

当前车辆状态：{vehicle_state_text}
当前对话历史：{history}
上一轮工具调用结果：
{dialogue_context}
用户输入：{user_input}
ASR置信度：{asr_confidence}

返回纯 JSON（无 markdown）：
{{
  "is_complex": false,
  "sub_tasks": [
    {{
      "task_id": "task_0",
      "intent": "search_poi",
      "intent_confidence": 0.95,
      "ambiguity_score": 0.0,
      "ambiguity_reason": "",
      "required_slots": ["keyword"],
      "extracted_slots": {{"keyword": "加油站"}},
      "depends_on": [],
      "urgency": "normal"
    }}
  ],
  "model_thinking": "思考过程（可选）"
}}
"""


# ── 节点 1：意图识别 ──

@track_node("intent_classifier")
def intent_classifier(state: CabinAgentState) -> dict:
    """
    Dispatch the intent recognition pipeline (Stage 0–4) and return structured sub-tasks and updated frame state.
    
    Performs slot carry-over, decides whether to use edge fast-path or call the cloud LLM, applies post-processing (depends_on validation, context-bleeding detection, ambiguity detection, episodic extraction guard), and updates active_frames. Ensures OOS and cross-domain flags are cleared in all LLM and fallback returns.
    
    Parameters:
        state (CabinAgentState): Agent runtime state containing at least:
            - "user_input": the current user utterance
            - optional "active_frames": list of existing frames
            - optional "_oos_flag" and "_cross_domain_flag": routing hints
            - optional "messages", "dialogue_context", "asr_confidence", etc.
    
    Returns:
        dict: A result dictionary with keys including:
            - "sub_tasks": list of subtask dicts (each contains task_id, intent, required_slots, extracted_slots, depends_on, intent_confidence, voice_reply, etc.)
            - "is_complex": `True` if multiple sub_tasks were produced
            - "task_results": reserved (currently None)
            - "completed_task_ids": reserved (currently None)
            - "intent": the primary intent (from the first subtask or "chitchat")
            - "active_frames": updated list of frames (pending/completed)
            - "episodic_context": injected episodic context if any, otherwise None
            - "_oos_flag": cleared (`None`) on LLM and fallback returns
            - "_cross_domain_flag": cleared (`None`) on LLM and fallback returns
    
    """
    user_input = state["user_input"]
    active_frames = state.get("active_frames", [])
    episodic_context = None  # Stage 1.5 会设置

    # ===== Stage 0: Slot Carry-Over（0ms）=====
    carried = _try_carry_over(user_input, active_frames)
    if carried:
        logger.info(f"[意图识别] Carry-Over 命中，跳过 LLM")
        return {
            "sub_tasks": [carried],
            "is_complex": False,
            "task_results": None,
            "completed_task_ids": None,
            "intent": carried.get("intent", "chitchat"),
            "active_frames": active_frames,
            "episodic_context": episodic_context,
        }

    # ===== Stage 1: 历史注入判断（0ms）=====
    needs_ctx = _needs_context(user_input, active_frames)

    # ===== Stage 1.5: 行程记忆检索（0ms）=====
    episodic_context = retrieve_episodic_context(user_input)
    if episodic_context:
        needs_ctx = True  # 含行程记录 → 上下文模式 → 漂移检测自动豁免
        logger.info(f"[意图识别] L1.5 行程记忆命中，{len(episodic_context['raw'])}条，注入上下文")

    history_text = _format_history(state.get("messages", []), needs_ctx)

    # ===== OOS flag 检测：FastRules 疑似命中 OOS，跳过端侧，强制走云端 =====
    oos_flag = state.get("_oos_flag")
    if oos_flag:
        logger.info(f"[意图识别] OOS flag 检出: {oos_flag}，跳过端侧，强制云端判断")

    # ===== 跨域多意图 flag 检测：FastRules 检测到跨域，跳过端侧，强制云端拆子任务 =====
    cross_domain_flag = state.get("_cross_domain_flag")
    if cross_domain_flag:
        logger.info("[意图识别] 跨域多意图 flag 检出，跳过端侧，强制云端拆子任务")

    # ===== Stage 2a: 端侧快路径（~1s，可选）=====
    from project1_cabin_agent.edge_model import EDGE_ENABLED, edge_model_infer, edge_result_to_subtask

    if EDGE_ENABLED and _can_use_edge(user_input, active_frames) and not oos_flag and not cross_domain_flag:
        edge_result = edge_model_infer(user_input)
        if edge_result.is_acceptable:
            # 端侧直出，跳过云端 LLM
            logger.info(
                f"[意图识别] 端侧直出: intent={edge_result.intent} "
                f"conf={edge_result.confidence:.2f} latency={edge_result.latency_ms:.0f}ms"
            )
            sub_tasks_data = [edge_result_to_subtask(edge_result)]
            _validate_slots(sub_tasks_data[0])
            # 端侧直出也走漂移+歧义检测（安全网）
            # 端侧模型无上下文，始终做漂移检测
            sub_tasks_data = _detect_context_bleeding(
                user_input, sub_tasks_data, state.get("messages", []), needs_ctx=False
            )
            sub_tasks_data = _detect_ambiguity(user_input, sub_tasks_data)
            # 构建 active_frames
            new_frames = [f for f in active_frames if f.get("status") == "pending"]
            for task in sub_tasks_data:
                missing = [s for s in task.get("required_slots", [])
                           if s not in task.get("extracted_slots", {})]
                new_frames.append({
                    "task_id": task.get("task_id", ""),
                    "intent": task.get("intent", ""),
                    "required_slots": task.get("required_slots", []),
                    "extracted_slots": task.get("extracted_slots", {}),
                    "status": "completed" if not missing else "pending",
                })
            first = sub_tasks_data[0]
            return {
                "sub_tasks": sub_tasks_data,
                "is_complex": len(sub_tasks_data) > 1,
                "task_results": None,
                "completed_task_ids": None,
                "intent": first.get("intent", "chitchat"),
                "active_frames": new_frames,
                "episodic_context": episodic_context,
                "_oos_flag": None,
                "_cross_domain_flag": None,
            }
        else:
            logger.info(
                f"[意图识别] 端侧放行云端: intent={edge_result.intent} "
                f"conf={edge_result.confidence:.2f} error={edge_result.error}"
            )

    # ===== Stage 2b: 云端 LLM 意图识别（~5s）=====
    llm = get_llm("fast", temperature=0.1)
    dialogue_ctx = state.get("dialogue_context", {})
    ctx_text = json.dumps(dialogue_ctx, ensure_ascii=False, indent=2) if dialogue_ctx else "（无）"
    prompt = INTENT_PROMPT.format(
            history=history_text or "（无相关历史）",
            user_input=user_input,
            asr_confidence=state.get("asr_confidence", 1.0),
            vehicle_state_text=vehicle_state.to_prompt_text(),
            dialogue_context=ctx_text,
        )

    if episodic_context:
        prompt = episodic_context["text"] + "\n\n" + prompt

    try:
        logger.info(f"[意图识别] 调用 LLM，user_input={user_input}，needs_ctx={needs_ctx}")
        raw_response = llm.invoke([HumanMessage(content=prompt)])
        raw_text = _ensure_str(raw_response.content).strip()

        parsed_dict = _parse_json(raw_text)
        # 修复 LLM 格式漂移：required_slots/depends_on 必须是 list，LLM 偶尔输出 {}
        for st in parsed_dict.get("sub_tasks", []):
            if isinstance(st.get("required_slots"), dict):
                st["required_slots"] = []
            if isinstance(st.get("depends_on"), dict):
                st["depends_on"] = []
        results = IntentOutput(**parsed_dict)
        logger.info(f"[意图识别] 模型思考过程: {results.model_thinking}")
        logger.info(f"[意图识别] ✅ 子任务数: {len(results.sub_tasks)}")
        sub_tasks_data = []
        for i, st in enumerate(results.sub_tasks):
            task_dict = st.model_dump()
            _validate_slots(task_dict)
            logger.info(
                f"[子任务{i+1}] id={st.task_id} intent={st.intent} "
                f"conf={st.intent_confidence:.0%} dep={st.depends_on} urgency={st.urgency} "
                f"slots={task_dict['extracted_slots']}"
            )
            if st.voice_reply:
                logger.info(f"[子任务{i+1}] voice_reply={st.voice_reply}")
            sub_tasks_data.append(task_dict)

        if not sub_tasks_data:
            logger.warning("[意图识别] LLM 返回空 sub_tasks")
            return _create_fallback_result("empty_result")

        # ===== depends_on 合法性校验 =====
        valid_ids = {t.get("task_id") for t in sub_tasks_data}
        for t in sub_tasks_data:
            invalid = [d for d in t.get("depends_on", []) if d not in valid_ids]
            if invalid:
                logger.warning(f"[depends_on校验] {t.get('task_id')} 的依赖 {invalid} 不在当前 sub_tasks 中，已清空")
                t["depends_on"] = [d for d in t.get("depends_on", []) if d in valid_ids]

        # ===== Stage 3: 后置漂移检测（0ms）=====
        # needs_ctx=True → 云端有上下文，引用历史是正确行为，跳过漂移检测
        if not needs_ctx:
            sub_tasks_data = _detect_context_bleeding(
                user_input, sub_tasks_data, state.get("messages", []), needs_ctx=False
            )

        # ===== Stage 4: post-hoc 歧义检测（0ms，规则层不信任 LLM 自觉性）=====
        sub_tasks_data = _detect_ambiguity(user_input, sub_tasks_data)

        # ===== Stage 4b: 行程提取校验（0ms，harness——验 LLM 从行程数据提取的值是否真实存在）=====
        if episodic_context:
            from project1_cabin_agent.nodes.post_rules import guard_episodic_extraction
            sub_tasks_data = guard_episodic_extraction(sub_tasks_data, episodic_context["raw"])

        # 更新 active_frames（上限 5，超出丢弃最旧的）
        new_frames = [f for f in active_frames if f.get("status") == "pending"]
        MAX_PENDING_FRAMES = 5
        if len(new_frames) >= MAX_PENDING_FRAMES:
            new_frames = new_frames[-(MAX_PENDING_FRAMES - 1):]
            logger.warning(f"[active_frames] pending 帧超限，丢弃最旧的")
        for task in sub_tasks_data:
            missing = [s for s in task.get("required_slots", [])
                       if s not in task.get("extracted_slots", {})]
            new_frames.append({
                "task_id": task.get("task_id", ""),
                "intent": task.get("intent", ""),
                "required_slots": task.get("required_slots", []),
                "extracted_slots": task.get("extracted_slots", {}),
                "status": "completed" if not missing else "pending",
            })

        first = sub_tasks_data[0]

        return {
            "sub_tasks": sub_tasks_data,
            "is_complex": len(sub_tasks_data) > 1,
            "task_results": None,
            "completed_task_ids": None,
            "intent": first.get("intent", "chitchat"),
            "active_frames": new_frames,
            "episodic_context": episodic_context,
            "_oos_flag": None,  # 清空 OOS flag
            "_cross_domain_flag": None,  # 清空跨域 flag
        }
    except json.JSONDecodeError as je:
        logger.error(f"[意图识别] ❌ JSON 解析错误: {je}")
        logger.debug(f"[意图识别] LLM 原始输出: {raw_text[:500]}")
        result = _create_fallback_result("json_error")
        result["episodic_context"] = episodic_context
        result["_oos_flag"] = None
        result["_cross_domain_flag"] = None
        return result

    except Exception as e:
        logger.error(f"[意图识别] ❌ 异常: {e}")
        result = _create_fallback_result("unknown_error")
        result["episodic_context"] = episodic_context
        result["_oos_flag"] = None
        result["_cross_domain_flag"] = None
        return result
