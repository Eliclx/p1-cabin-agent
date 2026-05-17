"""检查 LLM 实际收到的 prompt"""
import sys
sys.path.insert(0, '.')
from datetime import datetime
from project1_cabin_agent.nodes.episodic_memory import *
from project1_cabin_agent.nodes.intent import INTENT_PROMPT
from project1_cabin_agent.nodes.post_rules import _needs_context
from project1_cabin_agent.vehicle_state import vehicle_state
from project1_cabin_agent.nodes.message_utils import _format_history

FAKE_NOW = datetime(2026, 5, 15, 10, 30, 0)
set_current_time_fn(lambda: FAKE_NOW)
clear_events()
seed_event('2026-05-14T19:30:00', 'start_navigation', '导航去海底捞火锅(春熙路店)')

q = '昨晚去的饭店是哪家'
epi = retrieve_episodic_context(q)

prompt = INTENT_PROMPT.format(
    history='（无）',
    user_input=q,
    asr_confidence=1.0,
    vehicle_state_text=vehicle_state.to_prompt_text(),
    dialogue_context='（无）',
)
if epi:
    prompt = epi['text'] + '\n\n' + prompt

print('=== LLM 收到的完整 prompt ===')
print()
print(prompt)

reset_current_time_fn()
clear_events()
