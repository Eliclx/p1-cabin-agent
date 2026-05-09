"""端侧模型专项评估：门控命中率 + 意图准确率 + 槽位准确率"""
import os, sys, json, time, logging
from pathlib import Path

logging.disable(logging.CRITICAL)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ["EDGE_ENABLED"] = "true"

from project1_cabin_agent.edge_model import edge_model_infer
from project1_cabin_agent.nodes.intent import _can_use_edge

# (输入, 期望domain, 期望intent, 期望slots)
CASES = [
    # climate / ac_control
    ("调到26度", "climate", "ac_control", {"temperature": 26}),
    ("空调开到18度", "climate", "ac_control", {"temperature": 18}),
    ("温度调到22", "climate", "ac_control", {"temperature": 22}),
    ("关空调", "climate", "ac_control", {"action": "off"}),
    # climate / window
    ("开窗", "climate", "window_control", {"target": "window", "action": "open"}),
    ("关窗", "climate", "window_control", {"target": "window", "action": "close"}),
    ("天窗打开", "climate", "window_control", {"target": "sunroof", "action": "open"}),
    # climate / light
    ("开灯", "climate", "light_control", {"action": "on"}),
    ("关灯", "climate", "light_control", {"action": "off"}),
    ("阅读灯打开", "climate", "light_control", {"target": "reading", "action": "on"}),
    # climate / seat
    ("打开座椅加热", "climate", "seat_control", {"action": "heat_on"}),
    # navigation
    ("导航到天府广场", "navigation", "start_navigation", {"destination": "天府广场"}),
    ("导航去最近的加油站", "navigation", "start_navigation", {"destination": "最近的加油站"}),
    # media
    ("播放周杰伦", "media", "media_control", {"action": "play", "query": "周杰伦"}),
    ("声音大一点", "media", "media_control", {"action": "volume_up"}),
    ("音量调到80", "media", "media_control", {"action": "set_volume", "volume": 80}),
    ("下一首", "media", "media_control", {"action": "next"}),
    ("暂停", "media", "media_control", {"action": "pause"}),
    # search
    ("附近有没有加油站", "search", "search_poi", {"keyword": "加油站"}),
    ("帮我找下附近的医院", "search", "search_poi", {"keyword": "医院"}),
    # vehicle
    ("还有多少油", "vehicle", "query_vehicle_status", {"items": "fuel"}),
    ("胎压怎么样", "vehicle", "query_vehicle_status", {"items": "tire"}),
    # chitchat
    ("早上好", "chitchat", "chitchat", {}),
    ("讲个笑话", "chitchat", "chitchat", {}),
    ("今天天气怎么样", "chitchat", "chitchat", {}),
    ("几点了", "chitchat", "chitchat", {}),
    # boundary
    ("阿巴阿巴", "unknown", None, {}),
    ("嗯", "chitchat", "chitchat", {}),
    # needs_context (应被门控拦截)
    ("第二个", "needs_context", None, {}),
    ("还有多远", "needs_context", None, {}),
]

total = len(CASES)
gate_pass = 0
gate_block_correct = 0  # 正确拦截
gate_block_wrong = 0    # 错误拦截（应走端侧但被拦了）
intent_correct = 0
intent_total = 0
slot_correct = 0
slot_total = 0
slot_key_correct = 0
slot_key_total = 0
errors = []
latencies = []

for text, exp_domain, exp_intent, exp_slots in CASES:
    can_edge = _can_use_edge(text, [])
    
    # needs_context: 期望被拦截
    if exp_domain == "needs_context":
        if not can_edge:
            gate_block_correct += 1
        else:
            gate_block_wrong += 1
            errors.append(f"[门控漏放] '{text}' 应拦截但放了")
        continue
    
    # unknown: 期望不可接受
    if exp_domain == "unknown":
        r = edge_model_infer(text)
        latencies.append(r.latency_ms)
        if not r.is_acceptable:
            gate_block_correct += 1
        else:
            errors.append(f"[unknown误放] '{text}' domain={r.domain} intent={r.intent}")
        continue
    
    if not can_edge:
        gate_block_wrong += 1
        errors.append(f"[门控误拦] '{text}' 期望走端侧但被拦")
        continue
    
    gate_pass += 1
    r = edge_model_infer(text)
    latencies.append(r.latency_ms)
    
    # domain check
    if r.domain != exp_domain:
        errors.append(f"[domain错] '{text}' 期望={exp_domain} 实际={r.domain}")
    
    # intent check
    if exp_intent is not None:
        intent_total += 1
        if r.intent == exp_intent:
            intent_correct += 1
        else:
            errors.append(f"[意图错] '{text}' 期望={exp_intent} 实际={r.intent}")
    
    # slot check
    if exp_slots:
        slot_total += 1
        actual = r.slots or {}
        all_ok = True
        for k, v in exp_slots.items():
            slot_key_total += 1
            if k in actual:
                if str(actual[k]) == str(v):
                    slot_key_correct += 1
                else:
                    all_ok = False
                    errors.append(f"[槽位值错] '{text}' key={k} 期望={v} 实际={actual[k]}")
            else:
                all_ok = False
                errors.append(f"[槽位缺失] '{text}' key={k} 期望={v} slots={actual}")
        if all_ok:
            slot_correct += 1

edge_cases = gate_pass  # 实际走端侧的case数

print("=" * 60)
print("端侧模型专项评估")
print("=" * 60)
print(f"总用例: {total}")
print()
print(f"【门控命中率】")
print(f"  通过(走端侧): {gate_pass}/{total} = {gate_pass/total:.1%}")
print(f"  正确拦截:     {gate_block_correct}/{total} = {gate_block_correct/total:.1%}")
print(f"  误拦截:       {gate_block_wrong}")
print()
if intent_total:
    print(f"【意图准确率】 {intent_correct}/{intent_total} = {intent_correct/intent_total:.1%}")
if slot_total:
    print(f"【槽位完全准确】 {slot_correct}/{slot_total} = {slot_correct/slot_total:.1%}")
if slot_key_total:
    print(f"【槽位key准确】  {slot_key_correct}/{slot_key_total} = {slot_key_correct/slot_key_total:.1%}")
if latencies:
    print(f"【平均延迟】     {sum(latencies)/len(latencies):.0f}ms")
print()
print(f"错误明细 ({len(errors)}):")
for e in errors:
    print(f"  {e}")
