"""打印 L1.5 行程记忆具体输出结果"""
import sys
sys.path.insert(0, '.')
from datetime import datetime
from project1_cabin_agent.nodes.episodic_memory import *
from project1_cabin_agent.nodes.post_rules import guard_episodic_extraction
from project1_cabin_agent.nodes.pre_rules import fast_rules_check

FAKE_NOW = datetime(2026, 5, 15, 10, 30, 0)
set_current_time_fn(lambda: FAKE_NOW); clear_events()
seed_event('2026-05-14T19:30:00', 'start_navigation', '导航去海底捞火锅(春熙路店)')
seed_event('2026-05-14T12:15:00', 'start_navigation', '导航去天府广场')
seed_event('2026-05-14T08:10:00', 'media_control', '播放了周杰伦的晴天')
seed_event('2026-05-13T20:00:00', 'start_navigation', '导航去锦里古街')

print('=' * 70)
print('  L1.5 行程记忆 — 具体输出结果')
print('  当前时间: 2026-05-15 10:30 | Seed: 4条')
print('=' * 70)

# ═══ 1. 检索文本输出 ═══
print()
print('--- 1. 查询: "昨晚去哪了" ---')
r = retrieve_episodic_context('昨晚去哪了')
print()
print('  retrieve_episodic_context 返回值:')
print(f'  type = {type(r).__name__}')
print(f'  keys = {list(r.keys())}')
print()
print('  text = """')
for line in r['text'].split('\n'):
    print('    ' + line)
print('  """')
print()
print(f'  raw = [  # {len(r["raw"])}条')
for entry in r['raw']:
    print(f'    {{')
    print(f'      "timestamp":  "{entry["timestamp"]}",')
    print(f'      "event_type": "{entry["event_type"]}",')
    print(f'      "summary":    "{entry["summary"]}",')
    print(f'      "full_text":  "{entry["full_text"]}"')
    print(f'    }},')
print('  ]')

# ═══ 2. 多种查询对比 ═══
print()
print('--- 2. 不同时间词的检索数量 ---')
for q in ['昨晚去哪了', '昨天去了哪些地方', '昨天早上放的什么歌',
           '前天晚上去哪了', '前天搜了什么']:
    r = retrieve_episodic_context(q)
    n = len(r['raw']) if r else 0
    items = ', '.join([e['summary'][:25] for e in (r['raw'] if r else [])])
    print(f'  "{q}"')
    print(f'    → {n}条: {items}')

# ═══ 3. fast_rules 短路检查 ═══
print()
print('--- 3. fast_rules 短路检查 ---')
for q in ['昨晚去哪了', '开空调', '导航去天府广场']:
    fr = fast_rules_check(q, [])
    if fr:
        print(f'  "{q}" → 短路: intent={fr["intent"]}')
    else:
        print(f'  "{q}" → None (放行给 LLM)')

# ═══ 4. Guard 校验 ═══
print()
print('--- 4. Guard 槽位校验 ---')
raw = retrieve_episodic_context('昨晚去哪了')['raw']
print(f'  raw数据 (full_text截取): "{raw[0]["full_text"][:75]}"')
print()

# 合法提取
sub1 = [{'task_id':'t0','intent':'start_navigation',
         'extracted_slots':{'destination':'海底捞火锅(春熙路店)'},
         'required_slots':['destination'],'voice_reply':''}]
check_str = '海底捞火锅(春熙路店)' in raw[0]['full_text']
print(f'  case1: destination="海底捞火锅(春熙路店)"')
print(f'    destination 在 raw 中? {check_str}')
guard_episodic_extraction(sub1, raw)
print(f'    → intent={sub1[0]["intent"]}')

# 幻觉
sub2 = [{'task_id':'t0','intent':'start_navigation',
         'extracted_slots':{'destination':'小龙坎老火锅'},
         'required_slots':['destination'],'voice_reply':''}]
check_str2 = '小龙坎老火锅' in raw[0]['full_text']
print(f'  case2: destination="小龙坎老火锅"')
print(f'    destination 在 raw 中? {check_str2}')
guard_episodic_extraction(sub2, raw)
print(f'    → intent={sub2[0]["intent"]}, slots={sub2[0]["extracted_slots"]}')

# 多slot (提取型+结构型)
sub3 = [{'task_id':'t0','intent':'start_navigation',
         'extracted_slots':{'destination':'海底捞火锅(春熙路店)','mode':'fastest'},
         'required_slots':['destination','mode'],'voice_reply':''}]
print(f'  case3: destination="海底捞火锅(春熙路店)", mode="fastest"')
print(f'    destination → 提取型slot → 校验 → 在raw中 ✅')
print(f'    mode        → 结构型slot → 跳过校验')
guard_episodic_extraction(sub3, raw)
print(f'    → intent={sub3[0]["intent"]}, slots={sub3[0]["extracted_slots"]}')

# ═══ 5. LLM端到端 ═══
print()
print('--- 5. LLM 端到端 ---')
from langchain_core.messages import HumanMessage
from project1_cabin_agent.nodes.message_utils import _ensure_str
from project1_cabin_agent.vehicle_state import vehicle_state
from project1_cabin_agent.nodes.schema import PROMPT_TOOLS_TEXT
from shared.utils.llm_factory import get_llm
import json

PROMPT = (
    '你是车载语音助手意图理解中枢。返回纯 JSON。\n\n'
    '【核心原则】：\n'
    '1. 每条输入优先作为独立新指令\n'
    '2. 槽位提取规则：\n'
    '   a) 优先从用户输入提取槽位值\n'
    '   b) 用户用时间词引用过去事件时，行程数据是权威来源，直接从中提取对应值填入槽位\n'
    '   c) 禁止从对话历史编造槽位值\n'
    '   d) 只有行程数据确实不包含用户引用的信息时才 clarify\n\n'
    + PROMPT_TOOLS_TEXT + '\n\n'
    '当前车辆状态：{vehicle_state_text}\n'
    '对话历史：{history}\n'
    '用户输入：{user_input}\n'
)

llm = get_llm('fast', temperature=0.1)

for q in ['去昨天那个餐厅', '导航去昨晚吃饭的地方', '昨天早上放的什么歌']:
    print(f'  用户: "{q}"')
    r = retrieve_episodic_context(q)
    if not r:
        print(f'    检索: 无匹配')
    else:
        print(f'    检索: {len(r["raw"])}条 注入 prompt')
        prompt = r['text'] + '\n\n' + PROMPT.format(
            vehicle_state_text='（当前无可上报状态）',
            history='（无）',
            user_input=q,
        )
    try:
        raw_resp = llm.invoke([HumanMessage(content=prompt)])
        text = _ensure_str(raw_resp.content).strip()
        print(f'    LLM原始输出: {text[:300]}')
        try:
            parsed = json.loads(text)
            st = parsed['sub_tasks'][0]
            print(f'    解析: intent={st["intent"]} slots={st["extracted_slots"]}')
        except (json.JSONDecodeError, KeyError):
            print(f'    解析失败 (非标准JSON)')
            # try to repair
            import re
            m = re.search(r'"intent"\s*:\s*"(\w+)"', text)
            if m: print(f'    从原文提取 intent={m.group(1)}')
            m2 = re.search(r'"destination"\s*:\s*"([^"]+)"', text)
            if m2: print(f'    从原文提取 destination={m2.group(1)}')
    except Exception as e:
        print(f'    ERROR: {e}')
    print()

reset_current_time_fn(); clear_events()
print('完成')
