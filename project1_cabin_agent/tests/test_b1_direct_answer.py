"""临时测试：验证 B1 direct_answer 短正向反馈不被误判"""
import pytest
from project1_cabin_agent.tests.test_corner_cases import make_state, _new_thread, cabin_agent

POSITIVE_FEEDBACK = [
    ("完美", "正向反馈应走 chitchat 或 direct_answer，不应追问"),
    ("不错", "正向反馈应走 chitchat 或 direct_answer，不应追问"),
    ("很好", "正向反馈应走 chitchat 或 direct_answer，不应追问"),
    ("太棒了", "正向反馈应走 chitchat 或 direct_answer，不应追问"),
    ("厉害", "正向反馈应走 chitchat 或 direct_answer，不应追问"),
]


@pytest.mark.parametrize("text,reason", POSITIVE_FEEDBACK)
@pytest.mark.asyncio
async def test_positive_feedback(text, reason):
    """B1: 短正向反馈不应触发歧义追问。"""
    state = make_state(text)
    result = await cabin_agent.ainvoke(state, config=_new_thread())
    tasks = result.get("task_results", [])
    intent = tasks[0].get("intent", "?") if tasks else result.get("intent", "?")
    resp = result.get("final_response", "")
    # intent 应该是 chitchat 或 direct_answer，绝不能是 clarify
    assert intent != "clarify", f"[{reason}] '{text}' 被误判为 clarify，回复: {resp}"
    assert resp, f"[{reason}] '{text}' 应有回复"
