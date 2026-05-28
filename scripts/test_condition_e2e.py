"""
条件分支端到端测试 — 真实用户输入 → LLM 生成 condition → 评估结果
每个 case 调 LLM（~5s），共 8 个核心场景。
"""

import json
import sys
import os

sys.path.insert(0, ".")
os.environ["EDGE_ENABLED"] = "false"

from project1_cabin_agent.nodes.intent import intent_classifier
from project1_cabin_agent.nodes.condition import evaluate_condition


def make_state(user_input: str) -> dict:
    return {
        "user_input": user_input,
        "messages": [],
        "active_frames": [],
        "dialogue_context": {},
        "asr_confidence": 1.0,
        "clarify_count": 0,
        "sub_tasks": [],
        "is_complex": False,
        "task_results": [],
        "completed_task_ids": [],
        "current_task": None,
        "intent": "",
        "final_response": "",
        "error": None,
        "episodic_context": None,
        "_oos_flag": None,
        "_cross_domain_flag": None,
    }


# 8 个用户场景
cases = [
    {
        "input": "查下附近有没有充电站，有的话就导航过去",
        "desc": "有充电站才导航",
        "mock_upstream": {"task_0": {"count": 3, "results": [{"name": "壳牌"}]}},
    },
    {
        "input": "看看天气怎么样，天气好的话导航去天府广场",
        "desc": "天气好才导航",
        "mock_upstream": {"task_0": {"weather_main": "雨"}},
    },
    {
        "input": "附近有停车场吗？有的话导航过去",
        "desc": "有停车场才导航",
        "mock_upstream": {"task_0": {"count": 0, "results": []}},
    },
    {
        "input": "如果油量低于30%就导航去加油站",
        "desc": "油量低才导航",
        "mock_upstream": {"task_0": {"fuel": 15}},
    },
    {
        "input": "开空调，顺便导航去春熙路",
        "desc": "普通多意图（不应有 condition）",
    },
    {
        "input": "前面堵不堵车，不堵的话走高速",
        "desc": "不堵车才导航走高速",
        "mock_upstream": {"task_0": {"traffic": "畅通"}},
    },
    {
        "input": "有便宜的就推荐个餐厅",
        "desc": "条件模糊场景",
    },
    {
        "input": "找下有没有露营地，有的话导航过去",
        "desc": "有露营地才导航",
        "mock_upstream": {"task_0": {"count": 2, "results": [{"name": "阳光营地"}]}},
    },
]


for i, c in enumerate(cases, 1):
    print(f"\n{'=' * 70}")
    print(f'[{i}/8] 用户说: "{c["input"]}"')
    print(f"场景: {c['desc']}")
    print("-" * 70)

    state = make_state(c["input"])
    result = intent_classifier(state)
    sub_tasks = result.get("sub_tasks", [])

    print(f"LLM 返回 {len(sub_tasks)} 个 sub_task:")

    for j, task in enumerate(sub_tasks):
        intent = task.get("intent", "")
        slots = task.get("extracted_slots", {})
        depends = task.get("depends_on", [])
        condition = task.get("condition")

        print(f"  [{j}] intent={intent}, depends_on={depends}")
        print(f"      slots={json.dumps(slots, ensure_ascii=False)}")

        if condition:
            print(f"      condition: logic={condition.get('logic')}")
            for r in condition.get("rules", []):
                print(
                    f"        → {r['source']}.{r['field']} {r['op']} {r.get('value')}"
                )
            print(f'        fail_msg="{condition.get("fail_msg")}"')

            # 模拟上游结果，评估 condition
            mock = c.get("mock_upstream")
            if mock:
                task_results = []
                for tid, data in mock.items():
                    task_results.append({"task_id": tid, "tool_result": {"data": data}})
                passed, msg = evaluate_condition(condition, task_results)
                print(f"      模拟上游数据: {json.dumps(mock, ensure_ascii=False)}")
                print(f'      condition 评估结果: passed={passed}, msg="{msg}"')
                if not passed:
                    print(f'      → task 将被替换为 direct_answer: "{msg}"')
            else:
                print(f"      （无模拟数据，仅展示 LLM 生成的 condition）")
        else:
            print(f"      condition=无")

print(f"\n{'=' * 70}")
print("完成")
