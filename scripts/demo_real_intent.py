"""真实 intent_classifier 端到端测试 — 不用任何简化"""
import sys
sys.path.insert(0, '.')
from datetime import datetime
from project1_cabin_agent.nodes.episodic_memory import *

# 设置时间 + seed
FAKE_NOW = datetime(2026, 5, 15, 10, 30, 0)
set_current_time_fn(lambda: FAKE_NOW)
clear_events()
seed_event('2026-05-14T19:30:00', 'start_navigation', '导航去海底捞火锅(春熙路店)')
seed_event('2026-05-14T08:10:00', 'media_control', '播放了周杰伦的晴天')

from project1_cabin_agent.nodes.intent import intent_classifier

print('=' * 60)
print('  真实 intent_classifier 端到端')
print('  当前: 2026-05-15 10:30')
print('  事件: 昨晚19:30海底捞 | 昨天08:10周杰伦')
print('=' * 60)

queries = [
    '去昨天那个餐厅',
    '导航去昨晚吃饭的地方',
    '昨晚去的饭店是哪家',
    '昨天早上放的什么歌',
]

for q in queries:
    state = {
        'user_input': q,
        'active_frames': [],
        'messages': [],
        'dialogue_context': {},
        'asr_confidence': 1.0,
    }
    print(f'\n{"─" * 50}')
    print(f'用户: "{q}"')
    try:
        result = intent_classifier(state)
        sub = result.get('sub_tasks', [])
        if sub:
            st = sub[0]
            print(f'intent: {st.get("intent")}')
            print(f'slots:  {st.get("extracted_slots")}')
            print(f'reply:  "{st.get("voice_reply","")}"')
            print(f'is_complex: {result.get("is_complex")}')
        else:
            print(f'sub_tasks: 空')
            print(f'完整返回: {result}')
    except Exception as e:
        import traceback
        print(f'ERROR: {e}')
        traceback.print_exc()

reset_current_time_fn()
clear_events()
print()
print('完成')
