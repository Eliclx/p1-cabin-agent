"""L1.5 行程记忆 — LLM 端到端测试 (使用真实 INTENT_PROMPT)"""
import sys
sys.path.insert(0, '.')
from datetime import datetime
from langchain_core.messages import HumanMessage
from project1_cabin_agent.nodes.episodic_memory import *
from project1_cabin_agent.nodes.message_utils import _ensure_str, _parse_json
from project1_cabin_agent.vehicle_state import vehicle_state
from project1_cabin_agent.nodes.intent import INTENT_PROMPT
from project1_cabin_agent.nodes.constants import IntentOutput
from project1_cabin_agent.nodes.post_rules import guard_episodic_extraction
from shared.utils.llm_factory import get_llm

FAKE_NOW = datetime(2026, 5, 15, 10, 30, 0)
set_current_time_fn(lambda: FAKE_NOW)
clear_events()
seed_event('2026-05-14T19:30:00', 'start_navigation', '导航去海底捞火锅(春熙路店)')
seed_event('2026-05-14T08:10:00', 'media_control', '播放了周杰伦的晴天')

print('=' * 60)
print('  LLM 端到端 (真实 INTENT_PROMPT)')
print('  当前: 2026-05-15 10:30 | 事件: 海底捞(昨晚19:30), 周杰伦(昨天08:10)')
print('=' * 60)

llm = get_llm('fast', temperature=0.1)

queries = [
    '去昨天那个餐厅',
    '导航去昨晚吃饭的地方',
    '昨天早上放的什么歌',
    '昨晚去的饭店是哪家',
]

for q in queries:
    print(f'\n{"─" * 50}')
    print(f'用户: "{q}"')

    # 检索
    epi = retrieve_episodic_context(q)
    if epi:
        print(f'检索: {len(epi["raw"])}条 → 注入 LLM context')

    # 真实 INTENT_PROMPT + 行程数据
    prompt = INTENT_PROMPT.format(
        history='（无）',
        user_input=q,
        asr_confidence=1.0,
        vehicle_state_text=vehicle_state.to_prompt_text(),
        dialogue_context='（无）',
    )
    if epi:
        prompt = epi['text'] + '\n\n' + prompt

    # LLM
    try:
        raw = llm.invoke([HumanMessage(content=prompt)])
        text = _ensure_str(raw.content).strip()
        print(f'LLM原始: {text[:250]}')

        parsed = _parse_json(text)
        if not parsed:
            print(f'  解析失败')
            continue

        result = IntentOutput(**parsed)
        st = result.sub_tasks[0]
        print(f'intent: {st.intent}')
        print(f'slots:  {st.extracted_slots}')
        print(f'reply:  "{st.voice_reply}"')

        # Guard
        if epi:
            sub = [{
                'task_id': 't0',
                'intent': st.intent,
                'extracted_slots': st.extracted_slots,
                'required_slots': st.required_slots,
                'voice_reply': st.voice_reply or '',
            }]
            guard_episodic_extraction(sub, epi['raw'])
            if sub[0]['intent'] != st.intent:
                print(f'Guard: 拦截 → {sub[0]["intent"]}')
            else:
                print(f'Guard: 放行')

    except Exception as e:
        print(f'ERROR: {e}')

reset_current_time_fn()
clear_events()
print()
print('完成')
