"""
project1_cabin_agent/nodes/agent_nodes.py
向后兼容入口 — 所有节点和公共函数从子模块 re-export。

拆分后的模块：
  schema.py            — 技能发现 + Schema 生成
  models.py            — Pydantic 模型 + 关键词常量
  message_utils.py     — 消息/历史/JSON 工具函数
  intent_compress.py   — 消息压缩
  intent_carry.py      — Carry-Over + 历史注入判断
  intent_drift.py      — 漂移检测
  intent_ambiguity.py  — 歧义检测
  intent_slots.py      — 槽位校验 + 降级结果
  intent.py            — 意图识别调度入口
  pipeline.py          — 任务流水线 + 槽位提取 + 确认执行
  response.py          — 结果聚合 + 回复生成 + 闲聊处理
"""

# ── 节点函数（graph.py import 的8个） ──
from project1_cabin_agent.nodes.fast_rules import (
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
from project1_cabin_agent.nodes.models import (
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
from project1_cabin_agent.nodes.intent_carry import (
    _try_carry_over,
    _needs_context,
)
from project1_cabin_agent.nodes.intent_drift import (
    _detect_context_bleeding,
)
from project1_cabin_agent.nodes.intent_slots import (
    _validate_slots,
    _create_fallback_result,
    _create_default_subtask,
)
from project1_cabin_agent.nodes.intent_ambiguity import (
    _detect_ambiguity,
)
