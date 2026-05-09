"""
project1_cabin_agent/nodes/message_utils.py
消息角色映射、内容提取、历史格式化、JSON 解析等纯工具函数。
"""
import json
import re


# LangChain Message role 映射：type 属性 → 标准角色名
_MSG_ROLE_MAP = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}


def _get_msg_role(m) -> str:
    """统一获取消息角色名，兼容 LangChain Message 对象和原生 dict。"""
    if isinstance(m, dict):
        return m.get("role", "")
    # 对于 LangChain Message 对象，尝试通过 type 属性映射到标准角色名
    return _MSG_ROLE_MAP.get(getattr(m, "type", ""), "")


def _get_msg_content(m):
    """统一获取消息内容，兼容 LangChain Message 对象和原生 dict。"""
    if isinstance(m, dict):
        return m.get("content", "")
    return getattr(m, "content", "")


def _ensure_str(content) -> str:
    """确保 content 为 str，兼容 list[dict] 格式的 content blocks。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(content)


def _format_history(messages: list, needs_context: bool = True, max_turns: int = 5) -> str:
    """格式化消息历史为自然语言文本。"""
    if not messages:
        return ""
    if not needs_context:
        return ""
    lines = []
    for m in messages[-max_turns:]:
        role_str = _get_msg_role(m)
        content_str = _get_msg_content(m)
        role = "用户" if role_str == "user" else "助手"
        lines.append(f"{role}：{content_str}")
    return "\n".join(lines)


def _parse_json(text) -> dict:
    """从 LLM 输出中解析 JSON，兼容 markdown 包裹。"""
    text = _ensure_str(text)
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()
    # 清理 trailing comma（LLM 常见毛病，JSON 标准不允许尾逗号）
    text = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise
