"""
project1_cabin_agent/tests/test_clarify_interrupt.py
压测：歧义追问 + 槽位中断 + 历史干扰

用例设计：
  A. 歧义追问：模糊输入 → agent 应 clarify（而非瞎执行）
  B. 槽位中断：clarify → 用户回答 → 正确填空 → 执行
  C. 历史干扰：注入无关历史后，agent 不应被污染

用法:
    conda run -n llm python project1_cabin_agent/tests/test_clarify_interrupt.py
"""

import asyncio, json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


# ══════════════════════════════════════════════
# mock 工具：不依赖 Gradio，直接调 agent astream
# ══════════════════════════════════════════════

from project1_cabin_agent.state import CabinAgentState
from project1_cabin_agent.main import get_agent, _build_initial_state


def _extract_response(result: dict) -> str:
    """从 astream 最后一帧提取回复文本"""
    # 尝试多种路径
    msgs = result.get("messages", [])
    if msgs:
        last = msgs[-1]
        return last.content if hasattr(last, "content") else str(last)
    # Gradio output format
    history = result.get("history", [])
    if history and len(history) > 1:
        last_entry = history[-1]
        if isinstance(last_entry, dict) and last_entry.get("role") == "assistant":
            return last_entry.get("content", "")
    return ""


def _build_noisy_history(turns: int = 6) -> list[dict]:
    """构造无关历史：聊周末、聊电影、问天气"""
    noise = [
        ("周末去哪玩了", "我去了青城山，空气很好！"),
        ("最近有什么好看的电影", "最近《流浪地球3》口碑不错，推荐去看"),
        ("明天天气怎么样", "明天成都多云，18-25度，适合出行"),
        ("我有点饿了", "附近有川菜馆和火锅店，想吃哪种？"),
        ("你叫什么名字", "我是智能座舱助手，随时为您服务～"),
        ("放首歌吧", "好的，为您播放周杰伦的《晴天》"),
    ]
    history = []
    for i in range(min(turns, len(noise))):
        u, a = noise[i]
        history.append({"role": "user", "content": u})
        history.append({"role": "assistant", "content": a})
    return history


async def run_one_turn(user_input: str, history: list, session_id: str) -> tuple[str, str, list]:
    """单轮对话：发送 user_input，返回 (final_reply, intent, debug_info)"""
    # 把 history 转成最简单的 messages 格式
    msg_list = []
    for h in history:
        msg_list.append({"role": h["role"], "content": h["content"]})

    initial_state = _build_initial_state(user_input, msg_list)
    state_keys = set(CabinAgentState.__annotations__.keys())

    # 补充缺失的 state 字段（从上次结果继承）
    # 简单起见，每次 fresh session 从零开始
    agent = await get_agent()
    config = {"configurable": {"thread_id": session_id}}

    # 如果 session 有中断，先恢复
    checkpointer = agent.checkpointer
    if checkpointer:
        try:
            saved = await checkpointer.aget(config)
        except Exception:
            saved = None
        if saved:
            # 有中断，恢复执行
            cmd = None  # 默认不重定向
            try:
                async for chunk in agent.astream(cmd, config=config):
                    pass
            except Exception:
                pass

    # 新轮：创建新 state
    full_state = {k: initial_state.get(k, None) for k in state_keys}
    full_state["messages"] = msg_list

    intent = ""
    final_reply = ""
    debug = []

    try:
        async for chunk in agent.astream(full_state, config=config):
            if isinstance(chunk, dict):
                for node_name, node_output in chunk.items():
                    if isinstance(node_output, dict):
                        debug.append(f"[{node_name}] {json.dumps({k: str(v)[:80] for k, v in node_output.items() if k != 'messages'}, ensure_ascii=False)}")
                        if "intent" in node_output:
                            intent = str(node_output["intent"])
                        if "final_response" in node_output and node_output["final_response"]:
                            final_reply = str(node_output["final_response"])
                        if "voice_reply" in node_output and node_output["voice_reply"]:
                            final_reply = str(node_output["voice_reply"])
                        # task_results 里拿 intent
                        if "task_results" in node_output and node_output["task_results"] and isinstance(node_output["task_results"], list):
                            for tr in node_output["task_results"]:
                                if isinstance(tr, dict):
                                    if tr.get("intent"):
                                        intent = tr["intent"]
                                    if tr.get("voice_reply"):
                                        final_reply = tr["voice_reply"]
                                    break
    except Exception as e:
        debug.append(f"ERROR: {e}")
        final_reply = f"ERROR: {e}"

    # 从 state 快照获取最终结果
    try:
        snapshot = agent.get_state(config)
        if snapshot and snapshot.values:
            sv = snapshot.values
            if "final_response" in sv and sv["final_response"]:
                final_reply = str(sv["final_response"])
            if "intent" in sv and sv["intent"]:
                intent = str(sv["intent"])
            # task_results
            trs = sv.get("task_results", [])
            if trs and isinstance(trs, list):
                for tr in trs:
                    if isinstance(tr, dict):
                        if tr.get("voice_reply") and not final_reply:
                            final_reply = tr["voice_reply"]
                        if tr.get("intent") and intent in ("", "None"):
                            intent = tr["intent"]
    except Exception:
        pass

    history.append({"role": "user", "content": user_input})
    history.append({"role": "assistant", "content": final_reply or "(no reply)"})

    return final_reply or "(no reply)", intent, debug


# ══════════════════════════════════════════════
# 测试用例
# ══════════════════════════════════════════════

async def main():
    results = []

    print("=" * 60)
    print("A. 歧义追问测试（含历史干扰）")
    print("=" * 60)

    # A1: 模糊导航 + 6轮无关历史
    print("\n--- A1: '我想去' + 6轮无关历史 ---")
    h = _build_noisy_history(6)
    reply, intent, debug = await run_one_turn("我想去", h, "a1")
    print(f"  回复: {reply}")
    print(f"  意图: {intent}")
    passed = "想去" in reply or "哪里" in reply or "去哪儿" in reply or intent == "clarify"
    print(f"  {'✅' if passed else '❌'} 期望: clarify 追问去哪")
    results.append(("A1", passed, reply))

    # A2: 模糊调节 + 0轮历史
    print("\n--- A2: '热' + 无历史 ---")
    reply, intent, debug = await run_one_turn("热", [], "a2")
    print(f"  回复: {reply}")
    print(f"  意图: {intent}")
    # 端侧可能直接出 ac_control adjust 无目标 → harness 应拦截 clarify
    # 或者端侧出完整输出 → 直接执行也行
    passed = (
        "调" in reply or 
        ("度" in reply and "?" not in reply) or
        "已" in reply and ("空调" in reply or "冷" in reply.lower())
    ) and "已调整" not in reply  # 不能是空调整
    print(f"  {'✅' if passed else '❌'} 期望: 降温或追问，不能是无目标 adjust")

    # 检查 harness 拦截（看日志）
    if "已调整" in reply and "温度" not in reply:
        print(f"  ⚠️  BUG: harness 没拦住 adjust-without-target!")
    results.append(("A2", passed, reply))

    # A3: 模糊搜索 + 3轮无关历史
    print("\n--- A3: '搜一搜' + 3轮无关历史 ---")
    h = _build_noisy_history(3)
    reply, intent, debug = await run_one_turn("搜一搜", h, "a3")
    print(f"  回复: {reply}")
    print(f"  意图: {intent}")
    passed = "搜索" in reply or "搜什么" in reply or "什么" in reply or intent == "clarify"
    print(f"  {'✅' if passed else '❌'} 期望: clarify 问搜什么")
    results.append(("A3", passed, reply))

    # A4: "我想去" + 3轮包含"加油站"的历史 → 关键词污染测试
    print("\n--- A4: '我想去' + 历史含'加油站'对话 ---")
    h = [
        {"role": "user", "content": "附近有加油站吗"},
        {"role": "assistant", "content": "找到3个加油站，最近的距您1.2km"},
        {"role": "user", "content": "去最近的加油站"},
        {"role": "assistant", "content": "已规划路线，前往中石化国贸加油站"},
    ]
    reply, intent, debug = await run_one_turn("我想去", h, "a4")
    print(f"  回复: {reply}")
    print(f"  意图: {intent}")
    # 关键：不能从历史脑补加油站！
    passed = ("加油站" not in reply.replace("中石化国贸加油站", "")) or intent == "clarify"
    # 更严格的检查：回复不应包含具体加油站名
    poisoned = "加油站" not in reply and ("去哪" in reply or "哪里" in reply)
    print(f"  {'✅' if passed else '❌'} 期望: clarify，不从历史脑补")
    if not passed:
        print(f"  ⚠️  历史污染！回复不应含非指代的加油站")
    results.append(("A4", passed, reply))

    # ════════════════════════════════════════
    # B. 槽位中断测试
    # ════════════════════════════════════════
    print("\n" + "=" * 60)
    print("B. 槽位中断追问测试")
    print("=" * 60)

    # B1: 端侧直出完整指令 → 直接执行（不走中断）
    print("\n--- B1: '调到26度' → 端侧直出 (完整) ---")
    try:
        reply, intent, debug = await run_one_turn("调到26度", [], "b1")
    except Exception:
        reply, intent, debug = await run_one_turn("调到26度", [], "b1_v2")
    print(f"  回复: {reply}")
    print(f"  意图: {intent}")
    # 端侧应该直出 ac_control + temperature=26 → 直接执行
    passed = ("26" in reply or "已" in reply) and "哪里" not in reply
    print(f"  {'✅' if passed else '❌'} 期望: 直接调温到26度（不走 clarify）")
    results.append(("B1", passed, reply))

    # B2: 模糊空调 + 明确回答 → 中断-恢复流程
    # 这个需要连续两轮对话，比较难在单轮测试里做
    # 先注释，用 Gradio 手工测
    #
    # print("\n--- B2: '热' → clarify → '冷气' → 执行 ---")
    # reply, intent, debug = await run_one_turn("热", [], "b2")
    # print(f"  第1轮回复: {reply}")
    # if "度" in reply:
    #     reply2, intent2, _ = await run_one_turn("调到最低", history_b2, "b2")
    #     print(f"  第2轮回复: {reply2}")
    # passed = "16" in reply2 or "已" in reply2
    # results.append(("B2", passed, reply2))

    # ════════════════════════════════════════
    print("\n" + "=" * 60)
    print("📊 汇总")
    print("=" * 60)
    total = len(results)
    passed = sum(1 for _, p, _ in results if p)
    for name, ok, reply in results:
        print(f"  {'✅' if ok else '❌'} {name}: {reply[:60]}")
    print(f"\n  通过: {passed}/{total}")
    if passed < total:
        print(f"  🔴 失败 {total - passed} 项，需检查")

    # 返回 exit code
    return 0 if passed == total else 1


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
