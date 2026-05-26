"""
project1_cabin_agent/tests/test_multi_turn.py
多轮对话端到端测试 — 验证黑板传递、infer_slots 三级优先级、POI→导航坐标传递

使用场景:
  - 天气跨轮城市记忆（黑板优先级2复用）
  - 城市切换后的黑板更新
  - POI 搜索后导航（精确坐标 vs 地名地理编码）
  - 多轮追问的上下文继承

运行: EDGE_ENABLED=true EDGE_BASE_URL=http://localhost:8001/v1 conda run -n llm python -m pytest \
      project1_cabin_agent/tests/test_multi_turn.py -v --tb=short -s

注意:
  - 需要端侧模型运行在 localhost:8001
  - 需要高德 API key 配置正确
  - 每个测试函数内部按顺序执行多轮对话（共享 session）
"""

import os
import pytest

# 确保环境变量
os.environ.setdefault("EDGE_ENABLED", "true")
os.environ.setdefault("EDGE_BASE_URL", "http://localhost:8001/v1")


async def _run_conversation(rounds: list[dict[str, str]]) -> list[dict]:
    """执行多轮对话并返回每轮结果

    使用 SQLite 持久化 checkpoint，确保跨轮状态正确传递。
    MemorySaver 在同一 thread_id 上第二次 ainvoke 时有缓存 bug，
    会导致第二轮直接返回第一轮的结果，不重新执行 graph。
    """
    import os
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from project1_cabin_agent.graph import build_graph_with_checkpointer

    # 清理旧 db，避免残留 checkpoint 影响测试
    db_path = "./data/test_multi_turn.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = await aiosqlite.connect(db_path)
    checkpointer = AsyncSqliteSaver(conn=conn)
    await checkpointer.setup()
    graph = build_graph_with_checkpointer(checkpointer)
    config = {"configurable": {"thread_id": "test_multi_turn"}}
    results = []

    for r in rounds:
        user_input = r["input"]
        state = {
            "messages": [],
            "user_input": user_input,
            "asr_confidence": 1.0,
            "sub_tasks": [],
            "is_complex": False,
            "task_results": [],
            "completed_task_ids": [],
            "current_task": None,
            "intent": "",
            "final_response": "",  # 关键: 清空上轮回复，强制 graph 重新执行
            "error": None,
            "clarify_count": 0,
            "active_frames": [],
            "dialogue_context": {},  # merge_dict reducer 会保留 checkpoint 里的黑板数据
        }
        result = await graph.ainvoke(state, config)  # type: ignore[arg-type]

        # 提取关键信息
        final = result.get("final_response", "")
        sub_tasks = result.get("sub_tasks", [])
        intent = sub_tasks[0].get("intent", "") if sub_tasks else ""
        slots = sub_tasks[0].get("extracted_slots", {}) if sub_tasks else {}

        entry = {
            "input": user_input,
            "response": final,
            "intent": intent,
            "slots": slots,
        }
        results.append(entry)

    await conn.close()
    return results


# ═══════════════════════════════════════════════════════════════
# 测试 1: 天气跨轮城市记忆
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_weather_cross_round_city_memory():
    """第1轮查成都天气 → 第2轮"明天呢"应继承成都 → 第3轮切换天津 → 第4轮"后天呢"应继承天津"""
    rounds = [
        {"input": "今天天气怎么样"},
        {"input": "明天呢"},
        {"input": "天津天气怎么样"},
        {"input": "后天呢"},
    ]

    results = await _run_conversation(rounds)

    # 第1轮: 应该查到天气（城市可能是成都或其他当前坐标对应城市）
    assert "天气" in results[0]["response"] or "度" in results[0]["response"], (
        f"第1轮应返回天气信息，实际: {results[0]['response']}"
    )

    # 第2轮: 应该查到"明天"的天气（date 应该是明天而非今天）
    r1_city = _extract_city(results[0]["response"])
    r2_city = _extract_city(results[1]["response"])
    assert r2_city == r1_city, f"第2轮城市应继承第1轮: 第1轮={r1_city}, 第2轮={r2_city}"
    assert "明天" in results[1]["response"] or "度" in results[1]["response"], (
        f"第2轮应返回明天天气，实际: {results[1]['response']}"
    )

    # 第3轮: 应该查天津天气
    assert "天津" in results[2]["response"], (
        f"第3轮应查天津天气，实际: {results[2]['response']}"
    )

    # 第4轮: 应该继承天津（而非成都）
    assert "天津" in results[3]["response"], (
        f"第4轮应继承天津，实际: {results[3]['response']}"
    )


# ═══════════════════════════════════════════════════════════════
# 测试 2: POI→导航精确坐标传递
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_poi_to_navigate_coordinates():
    """先搜餐厅 → "去第一个" → 导航距离应与 POI 距离相近（<5km），而非58km"""
    rounds = [
        {"input": "附近有没有加油站"},
        {"input": "去第一个"},
    ]

    results = await _run_conversation(rounds)

    # 第1轮: 应该搜到加油站
    assert "加油站" in results[0]["response"] or "结果" in results[0]["response"], (
        f"第1轮应搜到加油站，实际: {results[0]['response']}"
    )

    # 第2轮: 应该导航，且距离合理（POI 在 3km 范围内，导航不应超过 10km）
    r2 = results[1]["response"]
    distance = _extract_distance(r2)
    assert distance is not None, f"第2轮应返回导航距离，实际: {r2}"
    assert distance < 10.0, (
        f"第2轮导航距离应 <10km（POI 在 3km 范围内），实际: {distance}km\n完整回复: {r2}"
    )


# ═══════════════════════════════════════════════════════════════
# 测试 3: 天气城市切换后黑板更新
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_weather_city_switch():
    """连查多个城市，每次切换后黑板应更新为最新城市"""
    rounds = [
        {"input": "北京天气怎么样"},
        {"input": "明天呢"},  # 应继承北京
        {"input": "上海天气"},  # 切换上海
        {"input": "后天呢"},  # 应继承上海
    ]

    results = await _run_conversation(rounds)

    # 第1轮: 北京
    assert "北京" in results[0]["response"], (
        f"第1轮应查北京天气，实际: {results[0]['response']}"
    )

    # 第2轮: 继承北京
    assert "北京" in results[1]["response"], (
        f"第2轮应继承北京，实际: {results[1]['response']}"
    )

    # 第3轮: 切换上海
    assert "上海" in results[2]["response"], (
        f"第3轮应查上海天气，实际: {results[2]['response']}"
    )

    # 第4轮: 继承上海（不是北京）
    assert "上海" in results[3]["response"], (
        f"第4轮应继承上海，实际: {results[3]['response']}"
    )


# ═══════════════════════════════════════════════════════════════
# 测试 4: POI 搜索→导航→再搜→再导航
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_poi_navigate_chain():
    """搜餐厅 → 去第一个 → 搜停车场 → 去第一个 → 两次导航都应距离合理"""
    rounds = [
        {"input": "附近有什么好吃的"},
        {"input": "去第一个"},
        {"input": "附近有没有停车场"},
        {"input": "去第一个"},
    ]

    results = await _run_conversation(rounds)

    # 第1轮: 搜到餐厅
    assert "结果" in results[0]["response"] or "餐厅" in results[0]["response"], (
        f"第1轮应搜到餐厅，实际: {results[0]['response']}"
    )

    # 第2轮: 导航到第一个餐厅，距离合理
    d1 = _extract_distance(results[1]["response"])
    assert d1 is not None, f"第2轮应返回导航距离，实际: {results[1]['response']}"
    assert d1 < 10.0, (
        f"第2轮导航距离应 <10km，实际: {d1}km\n完整回复: {results[1]['response']}"
    )

    # 第3轮: 搜到停车场
    assert "停车场" in results[2]["response"] or "结果" in results[2]["response"], (
        f"第3轮应搜到停车场，实际: {results[2]['response']}"
    )

    # 第4轮: 导航到第一个停车场，距离合理
    d2 = _extract_distance(results[3]["response"])
    assert d2 is not None, f"第4轮应返回导航距离，实际: {results[3]['response']}"
    assert d2 < 10.0, (
        f"第4轮导航距离应 <10km，实际: {d2}km\n完整回复: {results[3]['response']}"
    )


# ═══════════════════════════════════════════════════════════════
# 测试 5: 用户明确指定城市 → 幻觉检测不应误杀
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_weather_explicit_city_not_hallucination():
    """用户明确说了城市名，幻觉检测不应误杀"""
    rounds = [
        {"input": "今天天气怎么样"},  # 先查默认城市
        {"input": "乌鲁木齐天气怎么样"},  # 明确指定乌鲁木齐
    ]

    results = await _run_conversation(rounds)

    # 第2轮: 应查乌鲁木齐（不会被误杀为幻觉）
    assert "乌鲁木齐" in results[1]["response"], (
        f"第2轮应查乌鲁木齐天气（不被误杀），实际: {results[1]['response']}"
    )


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════


def _extract_city(response: str) -> str | None:
    """从回复中提取城市名"""
    import re

    # 匹配 "成都市" / "北京市" 等，必须有 市/省/自治区 后缀才算城市名
    m = re.search(r"([\u4e00-\u9fff]+(?:市|省|自治区))", response)
    return m.group(1) if m else None


def _extract_distance(response: str) -> float | None:
    """从导航回复中提取距离(km)

    匹配: "全程3.0公里" / "全程58.3公里" / "3.2km"
    """
    import re

    m = re.search(r"(?:全程|距离)\s*([\d.]+)\s*(?:公里|km|千米)", response)
    if m:
        return float(m.group(1))
    return None
