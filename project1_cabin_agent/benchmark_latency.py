"""
project1_cabin_agent/benchmark_latency.py
延迟 Benchmark 脚本

跑 20+ 条请求，统计各节点 P50/P95 延迟，
用于面试时准确回答性能数据。

用法：
    cd cabin-ai-agent
    python project1_cabin_agent/benchmark_latency.py

注意：依赖 LLM API，仅在网络通畅时运行。
"""

import asyncio
import sys
import time
import uuid
from pathlib import Path

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.checkpoint.memory import MemorySaver
from project1_cabin_agent.graph import build_graph_with_checkpointer
from project1_cabin_agent.state import CabinAgentState
from shared.utils.metrics import reset_metrics, get_session_summary


# ── Test Cases ──────────────────────────────────────────────────────────
# 覆盖：单意图 / 多意图独立 / 多意图依赖链 / 闲聊 / 隐含意图 / 场景联动

BENCHMARK_CASES = [
    # 单意图 — 导航
    ("导航去天府广场", "navigate", 1),
    ("去机场", "navigate", 1),

    # 单意图 — 搜索
    ("附近有加油站吗", "search_poi", 1),
    ("附近有什么好吃的", "search_poi", 1),
    ("找附近的停车场", "search_poi", 1),

    # 单意图 — 空调控制
    ("开空调", "ac_control", 1),
    ("把空调调到22度", "ac_control", 1),
    ("关空调", "ac_control", 1),

    # 单意图 — 车窗控制
    ("关车窗", "window_control", 1),

    # 单意图 — 媒体控制
    ("放音乐", "media_control", 1),
    ("声音大一点", "media_control", 1),
    ("暂停音乐", "media_control", 1),

    # 单意图 — 灯光
    ("开灯", "light_control", 1),

    # 单意图 — 查询
    ("还有多少油", "query_vehicle_status", 1),
    ("电池电量怎么样", "query_vehicle_status", 1),

    # 闲聊
    ("你好", "chitchat", 1),
    ("谢谢", "chitchat", 1),

    # 隐含意图（"有点冷" → 调空调，需要 LLM 推断）
    ("有点冷", "implicit", 1),
    ("太热了开一下", "implicit", 1),

    # 场景联动
    ("舒适驾驶模式", "activate_scene", 1),

    # 多意图 — 独立（并发执行）
    ("帮我加油顺便开空调", "multi_independent", 1),
    ("开窗放音乐", "multi_independent", 1),

    # 多意图 — 依赖链（串行执行，含 response_gen 聚合）
    ("先找加油站再导航过去", "multi_dependent", 3),  # 多跑几轮，这是重路径
    ("帮我找最近的停车场然后导航", "multi_dependent", 2),

    # 座椅控制
    ("开座椅加热", "seat_control", 1),
]

TOTAL_RUNS = sum(run_times for _, _, run_times in BENCHMARK_CASES)


def make_state(user_input: str) -> CabinAgentState:
    return {
        "messages": [],
        "user_input": user_input,
        "asr_confidence": 1.0,
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
    return {"configurable": {"thread_id": f"bench_{uuid.uuid4().hex[:8]}"}}


def percentile(sorted_vals: list[float], p: float) -> float:
    """计算百分位数（nearest-rank 方法）"""
    if not sorted_vals:
        return 0.0
    idx = max(0, min(len(sorted_vals) - 1, int(p / 100.0 * len(sorted_vals))))
    return sorted(sorted_vals)[idx]


async def main():
    # ── 构建 agent（MemorySaver，无 SQLite 开销）──
    print(f"🔧 构建 agent（MemorySaver）...")
    agent = build_graph_with_checkpointer(MemorySaver())

    # ── 预热：跑一条简单请求，消化 LLM client 初始化开销 ──
    print(f"🔥 预热中（消化 LLM client 初始化）...")
    reset_metrics()
    warmup_state = make_state("你好")
    await agent.ainvoke(warmup_state, config=_new_thread())
    print(f"   预热完成\n")

    # ── 收集数据 ──
    all_e2e_ms: list[float] = []                      # 端到端延迟
    node_latencies: dict[str, list[float]] = {}        # node_name → [latency_ms, ...]

    run_idx = 0
    for text, tag, run_times in BENCHMARK_CASES:
        for _ in range(run_times):
            run_idx += 1
            state = make_state(text)
            config = _new_thread()

            reset_metrics()
            t0 = time.perf_counter()

            try:
                result = await agent.ainvoke(state, config=config)
                e2e_ms = (time.perf_counter() - t0) * 1000
            except Exception as e:
                print(f"  ⚠️  [{run_idx}/{TOTAL_RUNS}] {text} → 异常: {e}")
                continue

            all_e2e_ms.append(e2e_ms)

            # 收集各节点延迟
            summary = get_session_summary()
            for node_entry in summary.get("nodes", []):
                node_name = node_entry["node"]
                latency = node_entry["latency_ms"]
                if node_name not in node_latencies:
                    node_latencies[node_name] = []
                node_latencies[node_name].append(latency)

            reply = result.get("final_response", "")[:50]
            print(f"  [{run_idx:2d}/{TOTAL_RUNS}] e2e={e2e_ms:7.1f}ms  [{tag}] {text} → {reply}")

    # ── 输出结果 ──
    if not all_e2e_ms:
        print("\n⚠️  所有请求都失败了，无法生成报告。请检查 LLM API 连接。")
        return

    print(f"\n{'='*70}")
    print(f"📊 Benchmark 结果（{len(all_e2e_ms)} 条有效请求）")
    print(f"{'='*70}")

    print(f"\n{'节点':<25} {'P50':>8} {'P95':>8} {'Avg':>8} {'样本数':>6}")
    print(f"{'-'*57}")

    # 端到端
    print(f"{'[端到端]':<25} {percentile(all_e2e_ms, 50):8.0f}ms {percentile(all_e2e_ms, 95):8.0f}ms {sum(all_e2e_ms)/len(all_e2e_ms):8.0f}ms {len(all_e2e_ms):6d}")

    # 各节点（按 P50 降序排列）
    sorted_nodes = sorted(node_latencies.items(), key=lambda x: percentile(x[1], 50), reverse=True)
    for node_name, lats in sorted_nodes:
        p50 = percentile(lats, 50)
        p95 = percentile(lats, 95)
        avg = sum(lats) / len(lats)
        print(f"{node_name:<25} {p50:8.0f}ms {p95:8.0f}ms {avg:8.0f}ms {len(lats):6d}")

    # ── 诊断信息 ──
    print(f"\n{'='*70}")
    print("💡 诊断提示")
    print(f"{'='*70}")
    
    intent_lats = node_latencies.get("intent_classifier", [])
    if intent_lats:
        p50_intent = percentile(intent_lats, 50)
        p50_e2e = percentile(all_e2e_ms, 50)
        intent_ratio = p50_intent / p50_e2e * 100 if p50_e2e else 0
        print(f"  intent_classifier 占端到端延迟: {intent_ratio:.0f}% (P50 {p50_intent:.0f}ms / {p50_e2e:.0f}ms)")
        print(f"  优化方向: 小模型蒸馏 → 减少 LLM 调用开销")
    
    compressor_lats = node_latencies.get("message_compressor", [])
    if compressor_lats:
        p50_comp = percentile(compressor_lats, 50)
        print(f"  message_compressor P50: {p50_comp:.0f}ms（无历史时几乎为 0）")

    print(f"\n  面试话术提示:")
    print(f"  - 瓶颈在 intent_classifier 的 LLM 调用")
    print(f"  - 高频意图可用 Carry-Over 规则路径（0ms 绕过 LLM）")
    print(f"  - 生产环境可用小模型蒸馏 / prefix caching 优化")


if __name__ == "__main__":
    asyncio.run(main())
