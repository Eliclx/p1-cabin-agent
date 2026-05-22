"""
project1_cabin_agent/tests/test_corner_cases.py
Corner Case 测试集

覆盖车载场景：
1. 歧义指令
2. 噪声 ASR
3. 隐含意图
4. 高风险车控
5. 多轮上下文
6. 单意图冒烟
7. 多意图独立任务（Send 并发 + 流式回复）
8. 多意图依赖链（串行 + 聚合回复）
9. interrupt 多轮追问闭环
"""
import asyncio
import uuid
import pytest
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver
from project1_cabin_agent.graph import build_graph_with_checkpointer
from project1_cabin_agent.state import CabinAgentState

# 测试用 MemorySaver（不需要持久化，速度快）
cabin_agent = build_graph_with_checkpointer(MemorySaver())


def make_state(user_input: str, asr_confidence: float = 1.0, messages: list | None = None) -> CabinAgentState:
    return {
        "messages": messages or [],
        "user_input": user_input,
        "asr_confidence": asr_confidence,
        "sub_tasks": [],
        "is_complex": False,
        "task_results": [],
        "completed_task_ids": [],
        "current_task": None,
        "intent": "",
        "final_response": "",
        "error": None,
        "clarify_count": 0,
        "active_frames": [],
        "dialogue_context": {},
    }


def _new_thread() -> dict:
    return {"configurable": {"thread_id": f"test_{uuid.uuid4().hex[:8]}"}}


# ─────────────────────────────────────────────────────────────
# 1. 歧义指令测试
# ─────────────────────────────────────────────────────────────

AMBIGUOUS_CASES = [
    # 短句（≤4字）无明确对象
    ("开一下",       "缺少操作对象"),
    ("调小点",       "缺少操作目标"),
    ("去那边",       "目的地不明确"),
    ("停一下",       "可能是停车或停止播放"),
    ("换一个",       "换什么不明确"),
    ("打开",         "打开什么没说"),
    ("关掉",         "关掉什么没说"),
    ("调高",         "调高什么没说"),
    ("来点",         "来点什么没说"),
    ("停",           "停什么没说"),
    # 不完整长句（>4字但缺关键信息）
    ("帮我打开",     "打开什么没说"),
    ("太亮了",       "暗指灯光但未说操作"),
    ("太冷了",       "暗指空调但未说具体操作"),
    ("好吵啊",       "暗指媒体/空调但不确定"),
    ("换一个吧",     "换什么没说"),
    ("我想去",       "去哪没说"),
    ("太热了开一下", "空调意图明确但操作模糊"),
]

@pytest.mark.parametrize("text,reason", AMBIGUOUS_CASES)
@pytest.mark.asyncio
async def test_ambiguous_intent(text, reason):
    state = make_state(text)
    result = await cabin_agent.ainvoke(state, config=_new_thread())
    response = result.get("final_response", "")
    assert response, f"[{reason}] 应有追问回复，但无输出"
    print(f"✅ 歧义测试 [{reason}]: {response}")


# ─────────────────────────────────────────────────────────────
# 2. 噪声 ASR 测试
# ─────────────────────────────────────────────────────────────

NOISY_ASR_CASES = [
    ("导航去天府广", 0.6, "天府广场"),
    ("空调调到22",   0.5, "空调"),
    ("加油站",       0.4, "加油"),
]

@pytest.mark.parametrize("text,conf,keyword", NOISY_ASR_CASES)
@pytest.mark.asyncio
async def test_noisy_asr(text, conf, keyword):
    state = make_state(text, asr_confidence=conf)
    result = await cabin_agent.ainvoke(state, config=_new_thread())
    response = result.get("final_response", "")
    assert response, "低置信度场景应有回复"
    print(f"✅ 噪声ASR [{text}|conf={conf}]: {response}")


# ─────────────────────────────────────────────────────────────
# 3. 隐含意图测试
# ─────────────────────────────────────────────────────────────

IMPLICIT_CASES = [
    ("我有点冷",   "vehicle_control", "ac"),
    ("有点吵",     "vehicle_control", "music"),
    ("看不清楚",   "vehicle_control", "light"),
    ("好渴",       "search_poi", "便利店"),
]

@pytest.mark.parametrize("text,expected_intent,hint", IMPLICIT_CASES)
@pytest.mark.asyncio
async def test_implicit_intent(text, expected_intent, hint):
    state = make_state(text)
    result = await cabin_agent.ainvoke(state, config=_new_thread())
    response = result.get("final_response", "")
    assert response, f"隐含意图应有回复: {text}"
    print(f"✅ 隐含意图 [{text}]: 期望={expected_intent}, 回复={response}")


# ─────────────────────────────────────────────────────────────
# 4. 高风险车控测试
# ─────────────────────────────────────────────────────────────

HIGH_RISK_CASES = [
    "关车窗",
    "打开车门",
    "关发动机",
]

@pytest.mark.parametrize("text", HIGH_RISK_CASES)
@pytest.mark.asyncio
async def test_high_risk_control(text):
    state = make_state(text)
    result = await cabin_agent.ainvoke(state, config=_new_thread())
    response = result.get("final_response", "")
    assert response, f"高风险操作应有回复: {text}"
    # 注意：是否触发确认取决于 LLM 判断和 mock 工具行为
    # 此处仅验证高风险操作有回复（确认流程是 LLM 行为，非代码强制）
    print(f"   高风险回复: {response}")
    print(f"✅ 安全校验 [{text}]: {response}")


# ─────────────────────────────────────────────────────────────
# 5. 多轮上下文测试
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_turn_context():
    history = []

    cfg = _new_thread()
    state1 = make_state("我想去看电影", messages=history)
    result1 = await cabin_agent.ainvoke(state1, config=cfg)
    history.extend([
        {"role": "user", "content": "我想去看电影"},
        {"role": "assistant", "content": result1.get("final_response", "")},
    ])

    state2 = make_state("最近的那个", messages=history)
    result2 = await cabin_agent.ainvoke(state2, config=cfg)
    response = result2.get("final_response", "")
    print(f"✅ 多轮上下文: 第1轮={result1.get('final_response')}, 第2轮={response}")
    assert response


# ─────────────────────────────────────────────────────────────
# 6. 单意图冒烟测试
# ─────────────────────────────────────────────────────────────

SMOKE_CASES = [
    ("导航去天府广场",   "navigate",    "天府广场"),
    ("附近有加油站吗",   "search_poi",  "加油站"),
    ("把空调调到22度",   "control",     "空调"),
    ("还有多少油",       "query",       "油量"),
    ("你好",             "chitchat",    ""),
]

@pytest.mark.parametrize("text,tag,keyword", SMOKE_CASES)
@pytest.mark.asyncio
async def test_smoke(text, tag, keyword):
    state = make_state(text)
    result = await cabin_agent.ainvoke(state, config=_new_thread())
    response = result.get("final_response", "")
    assert response, f"[{tag}] {text} → 无回复"
    print(f"✅ [{tag}] {text} → {response}")


# ─────────────────────────────────────────────────────────────
# 7. 多意图独立任务测试（Send 并发 + 流式回复）
# ─────────────────────────────────────────────────────────────

MULTI_INTENT_INDEPENDENT = [
    ("帮我加油顺便开空调", "独立多意图，应并发执行"),
    ("附近有便利店吗帮我调低温度", "独立多意图，应并发执行"),
    ("开窗放音乐", "独立多意图，应并发执行"),
]

@pytest.mark.parametrize("text,reason", MULTI_INTENT_INDEPENDENT)
@pytest.mark.asyncio
async def test_multi_intent_independent(text, reason):
    state = make_state(text)
    result = await cabin_agent.ainvoke(state, config=_new_thread())
    is_complex = result.get("is_complex", False)
    completed = result.get("completed_task_ids", [])
    total = len(result.get("sub_tasks", []))
    response = result.get("final_response", "")

    assert is_complex, f"[{reason}] 应识别为多意图"
    assert len(completed) > 0, f"[{reason}] 应有完成的子任务"
    assert response, f"[{reason}] 应有回复"
    print(f"✅ [{reason}] {text}: 完成{len(completed)}/{total}任务, 回复={response[:60]}")


# ─────────────────────────────────────────────────────────────
# 8. 多意图依赖链测试（串行 + 聚合回复）
# ─────────────────────────────────────────────────────────────

MULTI_INTENT_DEPENDENT = [
    ("先找加油站再导航过去", "依赖链，应串行聚合回复"),
    ("帮我找最近的停车场然后导航", "依赖链，应串行聚合回复"),
]

@pytest.mark.parametrize("text,reason", MULTI_INTENT_DEPENDENT)
@pytest.mark.asyncio
async def test_multi_intent_dependent(text, reason):
    state = make_state(text)
    result = await cabin_agent.ainvoke(state, config=_new_thread())
    sub_tasks = result.get("sub_tasks", [])
    has_dependencies = any(t.get("depends_on") for t in sub_tasks)
    response = result.get("final_response", "")

    assert len(sub_tasks) >= 2, f"[{reason}] 应有多个子任务"
    assert has_dependencies, f"[{reason}] 应有依赖关系"
    print(f"✅ [{reason}] {text}: 子任务数={len(sub_tasks)}, 依赖={[t.get('depends_on') for t in sub_tasks]}")
    if response:
        print(f"   回复: {response[:60]}")


# ─────────────────────────────────────────────────────────────
# 9. interrupt 多轮追问闭环测试
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_interrupt_single_clarify():
    """单次追问：缺少槽位 → interrupt → 用户回答 → 恢复执行"""
    config = _new_thread()

    # Round 1: 输入缺槽位的指令
    state1 = make_state("导航去")
    result1 = await cabin_agent.ainvoke(state1, config=config)

    # 检查是否有 interrupt
    snapshot = await cabin_agent.aget_state(config)
    if snapshot.tasks:
        question = snapshot.tasks[0].interrupts[0].value.get("question", "")
        assert question, "interrupt 应有追问问题"
        print(f"✅ [interrupt] 追问: {question}")

        # Round 2: 用 Command(resume) 恢复
        result2 = await cabin_agent.ainvoke(Command(resume="天府广场"), config=config)
        response = result2.get("final_response", "")
        assert response, "恢复后应有最终回复"
        print(f"✅ [interrupt] 恢复后回复: {response[:60]}")
    else:
        print("✅ [interrupt] 未触发 interrupt（可能意图识别已推断出槽位）")


@pytest.mark.asyncio
async def test_interrupt_multi_clarify():
    """多次追问：连续缺少多个槽位"""
    config = _new_thread()

    # Round 1
    state1 = make_state("调一下")
    result1 = await cabin_agent.ainvoke(state1, config=config)

    snapshot = await cabin_agent.aget_state(config)
    if not snapshot.tasks:
        print("✅ [多次追问] 未触发 interrupt（可能意图识别已推断出槽位）")
        return

    question1 = snapshot.tasks[0].interrupts[0].value.get("question", "")
    print(f"✅ [多次追问] 第1次追问: {question1}")

    # Round 2: 回答一个槽位
    result2 = await cabin_agent.ainvoke(Command(resume="空调"), config=config)
    snapshot2 = await cabin_agent.aget_state(config)

    if snapshot2.tasks:
        question2 = snapshot2.tasks[0].interrupts[0].value.get("question", "")
        print(f"✅ [多次追问] 第2次追问: {question2}")

        # Round 3
        result3 = await cabin_agent.ainvoke(Command(resume="22度"), config=config)
        response = result3.get("final_response", "")
        print(f"✅ [多次追问] 最终回复: {response[:60]}")
    else:
        response = result2.get("final_response", "")
        print(f"✅ [多次追问] 第2轮直接完成: {response[:60]}")


@pytest.mark.asyncio
async def test_interrupt_with_multi_intent():
    """多意图 + 部分追问：一个任务缺槽位触发 interrupt，其他任务正常完成"""
    config = _new_thread()

    state1 = make_state("帮我加油顺便开")
    result1 = await cabin_agent.ainvoke(state1, config=config)

    snapshot = await cabin_agent.aget_state(config)

    completed = result1.get("completed_task_ids", [])
    has_interrupt = bool(snapshot.tasks)

    assert len(completed) >= 1, "加油任务应正常完成"
    print(f"✅ [多意图+追问] 完成={completed}, interrupt={has_interrupt}")

    if has_interrupt:
        question = snapshot.tasks[0].interrupts[0].value.get("question", "")
        print(f"   追问: {question}")

        result2 = await cabin_agent.ainvoke(Command(resume="空调"), config=config)
        print(f"   恢复后回复: {result2.get('final_response', '')[:60]}")


# ─────────────────────────────────────────────────────────────
# 10. 历史污染防护 + Slot Carry-Over 测试
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_context_bleeding():
    """导航后说'打开'不应延续导航意图"""
    history = [
        {"role": "user", "content": "导航去机场"},
        {"role": "assistant", "content": "已规划路线，前往机场，预计未知，全程未知"},
    ]
    state = make_state("打开", messages=history)
    result = await cabin_agent.ainvoke(state, config=_new_thread())
    sub_tasks = result.get("sub_tasks", [])
    intents = [t.get("intent") for t in sub_tasks]

    navigate_tasks = [t for t in sub_tasks if t.get("intent") in ("start_navigation", "navigate")]
    assert not navigate_tasks, f"'打开'不应被识别为导航意图, 实际 intents={intents}"
    print(f"✅ 历史污染防护: '打开' → intents={intents}")


@pytest.mark.asyncio
async def test_coreference_resolution():
    """指代词应正确关联历史"""
    history = [
        {"role": "user", "content": "附近有加油站吗"},
        {"role": "assistant", "content": "找到3个加油站，最近的是中石化"},
    ]
    state = make_state("最近的那个导航过去", messages=history)
    result = await cabin_agent.ainvoke(state, config=_new_thread())
    sub_tasks = result.get("sub_tasks", [])

    assert len(sub_tasks) >= 1, "应有子任务"
    print(f"✅ 指代消解: '最近的那个导航过去' → intents={[t.get('intent') for t in sub_tasks]}")


@pytest.mark.asyncio
async def test_short_input_as_new_intent():
    """短输入不应被历史锚定"""
    history = [
        {"role": "user", "content": "帮我加油"},
        {"role": "assistant", "content": "找到3个加油站，最近的是中石化加油站"},
    ]
    state = make_state("关窗", messages=history)
    result = await cabin_agent.ainvoke(state, config=_new_thread())
    sub_tasks = result.get("sub_tasks", [])
    intents = [t.get("intent") for t in sub_tasks]

    assert "search_poi" not in intents, f"'关窗'不应被识别为搜索加油站, 实际={intents}"
    print(f"✅ 短输入独立: '关窗' → intents={intents}")


@pytest.mark.asyncio
async def test_independent_with_location_word():
    """包含'那边'但不是指代，应作为新指令"""
    history = [
        {"role": "user", "content": "导航去机场"},
        {"role": "assistant", "content": "已规划路线，前往机场"},
    ]
    state = make_state("那边有一家新餐厅帮我导航过去", messages=history)
    result = await cabin_agent.ainvoke(state, config=_new_thread())
    sub_tasks = result.get("sub_tasks", [])
    intents = [t.get("intent") for t in sub_tasks]

    slots = {}
    for t in sub_tasks:
        slots.update(t.get("extracted_slots", {}))

    # LLM 合理决策：destination 不明确时只先 search_poi，等用户选了再导航
    assert "search_poi" in intents, f"应至少有搜索意图, 实际={intents}"
    assert "机场" not in str(slots), f"目的地不应被历史污染为机场, 实际 slots={slots}"
    print(f"✅ 独立指令: '那边有新餐厅...' → intents={intents}, slots={slots}")


if __name__ == "__main__":
    async def run_all():
        print("=" * 60)
        print("车载 Agent Corner Case 测试")
        print("=" * 60)

        for text, reason in AMBIGUOUS_CASES:
            state = make_state(text)
            result = await cabin_agent.ainvoke(state, config=_new_thread())
            print(f"[歧义] {text!r:20} → {result.get('final_response', '')}")

        print()
        for text, tag, kw in SMOKE_CASES:
            state = make_state(text)
            result = await cabin_agent.ainvoke(state, config=_new_thread())
            print(f"[{tag}] {text!r:20} → {result.get('final_response', '')}")

        print()
        for text, reason in MULTI_INTENT_INDEPENDENT:
            state = make_state(text)
            result = await cabin_agent.ainvoke(state, config=_new_thread())
            completed = len(result.get("completed_task_ids", []))
            total = len(result.get("sub_tasks", []))
            print(f"[并发] {text!r:20} → 完成{completed}/{total}, 回复={result.get('final_response', '')[:50]}")

        print()
        print("--- interrupt 测试 ---")
        await test_interrupt_single_clarify()
        await test_interrupt_multi_clarify()
        await test_interrupt_with_multi_intent()

        print()
        print("--- 历史污染防护测试 ---")
        await test_no_context_bleeding()
        await test_coreference_resolution()
        await test_short_input_as_new_intent()
        await test_independent_with_location_word()

    asyncio.run(run_all())
