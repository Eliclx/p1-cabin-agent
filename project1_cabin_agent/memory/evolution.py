"""
project1_cabin_agent/memory/evolution.py — 记忆进化引擎（纯逻辑）

职责：
  - 把未分析的 events 编译成 LLM prompt
  - 解析 LLM 返回的偏好列表
  - 不依赖任何外部模块（MemoryManager / LLM provider 都不 import）

解耦原则：
  1. 变更频率：prompt 模板经常调优，不该耦合 MemoryManager
  2. 替换可能：LLM callable 由外部注入，引擎不知道用的是哪个模型
  3. 测试独立：build_prompt / parse_response 都可以纯函数测试
  5. 影响范围：调 prompt 模板不动引擎和存储

调用链：
  evolution_runner.py (编排)
    → evolution.py (纯逻辑)
      → MemoryManager (读写数据，由 runner 传入)
      → LLM callable (由 runner 注入)
"""

from __future__ import annotations

import json
from dataclasses import dataclass


# ═══════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════


@dataclass
class ExtractedPreference:
    """从 LLM 分析中提取的偏好"""

    key: str          # "preferred_route_type" / "frequent_destination_xxx"
    value: str        # "avoid_toll" / "天府广场"
    reason: str       # "用户3次导航去天府广场"
    confidence: float  # 0.0 ~ 1.0

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "reason": self.reason,
            "confidence": self.confidence,
        }


# ═══════════════════════════════════════════════════
# Prompt 构建
# ═══════════════════════════════════════════════════


_EVOLUTION_SYSTEM_PROMPT = """\
你是一个用户偏好分析助手。根据用户的操作记录，提取长期偏好。

输出 JSON 格式：
{
  "preferences": [
    {
      "key": "偏好名称（英文蛇形命名）",
      "value": "偏好值",
      "reason": "推断理由",
      "confidence": 0.8
    }
  ]
}

规则：
1. 只输出有明确证据的偏好（至少出现 2 次的模式）
2. confidence: 确定性高的 0.8-0.95，一般的 0.5-0.7
3. key 命名规范: {类型}_{实体}，如 frequent_destination_chongqing, preferred_route_type
4. 如果没有明确偏好，返回 {"preferences": []}
5. 只输出 JSON，不要其他文字"""


def build_evolution_prompt(events: list[dict]) -> str:
    """
    将 events 列表编译成 LLM prompt。

    events 是 dict 列表（不是 Event 对象），方便 runner 从 backend 取出后直接传入。
    只保留 LLM 需要看的字段，过滤掉内部实现细节。
    """
    if not events:
        return ""

    lines = ["以下是用户的操作记录：\n"]

    for i, evt in enumerate(events, 1):
        event_type = evt.get("event_type", "unknown")
        summary = evt.get("summary", "")
        heat = evt.get("heat", 1.0)
        dedup_count = evt.get("dedup_count", 1)
        details = evt.get("details", {})

        # 精简 details，只保留有意义的字段
        detail_parts = []
        for k, v in details.items():
            if v and str(v).strip():
                detail_parts.append(f"{k}={v}")

        detail_str = ", ".join(detail_parts) if detail_parts else ""
        count_str = f"(重复{dedup_count}次)" if dedup_count > 1 else ""

        line = f"{i}. [{event_type}] {summary}"
        if detail_str:
            line += f" | {detail_str}"
        if count_str:
            line += f" {count_str}"
        lines.append(line)

    return "\n".join(lines)


# ═══════════════════════════════════════════════════
# 响应解析
# ═══════════════════════════════════════════════════


def parse_evolution_response(llm_output: str) -> list[ExtractedPreference]:
    """
    解析 LLM 返回的偏好 JSON。

    容错：JSON 解析失败 / 字段缺失 / confidence 越界 都不会崩溃。
    """
    # 提取 JSON（LLM 可能在前后加文字）
    text = llm_output.strip()

    # 尝试找到 JSON 块
    json_start = text.find("{")
    json_end = text.rfind("}") + 1
    if json_start == -1 or json_end == 0:
        return []

    try:
        data = json.loads(text[json_start:json_end])
    except json.JSONDecodeError:
        return []

    raw_prefs = data.get("preferences", [])
    if not isinstance(raw_prefs, list):
        return []

    results: list[ExtractedPreference] = []
    for raw in raw_prefs:
        if not isinstance(raw, dict):
            continue

        key = raw.get("key", "").strip()
        value = raw.get("value", "").strip()
        if not key or not value:
            continue

        confidence = raw.get("confidence", 0.5)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        results.append(ExtractedPreference(
            key=key,
            value=value,
            reason=raw.get("reason", ""),
            confidence=confidence,
        ))

    return results


# ═══════════════════════════════════════════════════
# 进化引擎（纯逻辑编排）
# ═══════════════════════════════════════════════════


class EvolutionEngine:
    """
    纯逻辑引擎：events → prompt → LLM → preferences

    不 import MemoryManager / get_llm / 任何外部模块。
    LLM callable 由调用方注入（原则 2: 替换可能性）。
    """

    def __init__(self, llm_fn) -> None:
        """
        Args:
            llm_fn: callable，接收 str(prompt)，返回 str(response)
                    由 runner 注入，引擎不知道底层用什么模型
        """
        self._llm_fn = llm_fn

    def evolve(self, events: list[dict]) -> list[ExtractedPreference]:
        """
        执行一次进化分析。

        Args:
            events: 未分析的事件列表（dict 格式）

        Returns:
            提取到的偏好列表（可能为空）
        """
        if not events:
            return []

        # 1. 构建 prompt
        user_prompt = build_evolution_prompt(events)
        if not user_prompt:
            return []

        # 2. 调 LLM
        try:
            response = self._llm_fn(user_prompt)
        except Exception:
            return []

        # 3. 解析响应
        preferences = parse_evolution_response(response)

        return preferences
