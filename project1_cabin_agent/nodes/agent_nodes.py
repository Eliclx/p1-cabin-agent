"""
project1_cabin_agent/nodes/agent_nodes.py
向后兼容入口 — 所有节点和公共函数从子模块 re-export。

拆分后的模块：
  constants.py         — Pydantic 模型 + 关键词常量
  pre_rules.py         — 前置规则层（短路 + OOS + 多意图 + 防误杀 + 槽位提取）
  post_rules.py        — 后置守卫（歧义拦截 + 漂移检测 + Carry-Over + 历史注入）
  schema.py            — 技能发现 + Schema 生成
  message_utils.py     — 消息/历史/JSON 工具函数
  intent_compress.py   — 消息压缩
  intent_slots.py      — 槽位校验 + 降级结果
  intent.py            — 意图识别调度入口
  pipeline.py          — 任务流水线 + 槽位提取 + 确认执行
  response.py          — 结果聚合 + 回复生成 + 闲聊处理
"""

# ── 节点函数（graph.py import 的8个） ──
from project1_cabin_agent.nodes.pre_rules import (
    fast_rules_node,
)
from project1_cabin_agent.nodes.intent_compress import (
    message_compressor,
)
from project1_cabin_agent.nodes.intent import (
    intent_classifier,
)
from project1_cabin_agent.nodes.pipeline import (
    task_pipeline,
)
from project1_cabin_agent.nodes.response import (
    session_update,
    wave_aggregator,
    response_gen,
    chitchat_handler,
)

# ── 公共 API（其他模块可能引用的） ──
from project1_cabin_agent.nodes.schema import (
    DYNAMIC_SCHEMA,
    PROMPT_TOOLS_TEXT,
    generate_dynamic_schema,
    generate_prompt_text,
)
from project1_cabin_agent.nodes.constants import (
    SubTask,
    IntentOutput,
    STRONG_COREFERENCE,
    IMPLIES_CONTEXT,
    INDEPENDENT_KEYWORDS,
)
from project1_cabin_agent.nodes.message_utils import (
    _get_msg_role,
    _get_msg_content,
    _ensure_str,
    _format_history,
    _parse_json,
)
from project1_cabin_agent.nodes.post_rules import (
    _try_carry_over,
    _needs_context,
    _detect_context_bleeding,
    _detect_ambiguity,
)
from project1_cabin_agent.nodes.intent_slots import (
    _validate_slots,
    _create_fallback_result,
    _create_default_subtask,
)
