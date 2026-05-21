"""
project1_cabin_agent/nodes/schema.py
技能自动发现引擎 — 从 Skill Registry 生成动态意图-槽位 schema。
"""
from project1_cabin_agent.skills.registry import registry


def _slot_is_required(slot_def: dict) -> bool:
    """判断 slot 是否必填（无 default 且无 anyOf 含 null）"""
    if "default" in slot_def:
        return False
    if "anyOf" in slot_def:
        # anyOf 含 null 类型 = optional
        return not any(t.get("type") == "null" for t in slot_def["anyOf"] if isinstance(t, dict))
    return True


def _extract_param_description(slot_def: dict) -> str:
    """从 slot dict 提取描述文本"""
    return slot_def.get("description", "")


def generate_dynamic_schema() -> dict:
    """从 Registry 生成动态意图-槽位 schema，供 intent_classifier 使用。"""
    schema = {}

    for domain, intent_list in registry.get_all_intents().items():
        for intent_name in intent_list:
            spec = registry.get_intent_spec(intent_name)
            if spec is None:
                continue

            required = []
            optional = []
            param_descriptions = {}

            for slot_name, slot_def in spec.slots.items():
                if _slot_is_required(slot_def):
                    required.append(slot_name)
                else:
                    optional.append(slot_name)
                param_descriptions[slot_name] = _extract_param_description(slot_def)

            # 从 examples.yaml 提取 literal 示例
            examples = []
            registry._ensure_examples_loaded(domain)
            entry = registry._skills.get(domain)
            if entry and intent_name in entry.examples:
                for ex in entry.examples[intent_name]:
                    if isinstance(ex, dict) and "input" in ex:
                        examples.append(ex["input"])

            schema[intent_name] = {
                "description": spec.description,
                "required": required,
                "optional": optional,
                "param_descriptions": param_descriptions,
                "examples": examples[:5],
                "anti_examples": [],
                "implicit_maps": [],
                "risk_level": "normal",
            }

    # 非 skill 兜底 intent
    schema["chitchat"] = {
        "description": "日常闲聊或无关对话",
        "required": [], "optional": [],
        "param_descriptions": {}, "examples": [],
        "anti_examples": [], "implicit_maps": [],
        "risk_level": "normal",
    }
    schema["direct_answer"] = {
        "description": "直接回答用户的信息查询（数据已在dialogue_context中，无需调工具）。当用户询问上轮搜索结果的细节时使用，如'第2个是什么'、'最远的是哪个'。不要对需要执行操作的使用此意图。",
        "required": [], "optional": [],
        "param_descriptions": {},
        "examples": ["第2个加油站是什么", "最远的是哪个", "第一个的评分多少"],
        "anti_examples": ["帮我导航去第二个（这是操作指令，应识别为start_navigation）"],
        "implicit_maps": [], "risk_level": "normal",
    }
    schema["no_support"] = {
        "description": "用户请求超出系统能力范围（外卖、购物、电话、订票等），礼貌告知暂不支持",
        "required": [], "optional": [],
        "param_descriptions": {},
        "examples": ["帮我点个外卖", "打电话给张三", "买张机票"],
        "anti_examples": ["帮我导航（这是支持的start_navigation）"],
        "implicit_maps": [], "risk_level": "normal",
    }

    return schema


def generate_prompt_text(schema: dict) -> str:
    """生成工具列表文本，注入 INTENT_PROMPT。
    
    注意：anti_examples 和 implicit_maps 不再输出到 prompt。
    原因：这两个段落（共 ~525 字）已被 FastRules 规则层覆盖：
      - anti_examples（"声音大一点不是空调"）→ FastRules 短路命中 volume_up
      - implicit_maps（"有点冷→空调制热"）→ FastRules 短路命中 ac_cold
    删掉后 prompt 减少 ~525 字，且不会到达 LLM（被 FastRules 拦截）。
    """
    tool_lines = ["【支持的意图类型（严格限定，绝不能自己捏造）】："]
    for name, info in schema.items():
        params = [f"{pn}({pd})" for pn, pd in info.get("param_descriptions", {}).items()]
        line = f"- {name}: {info['description']}。参数: {', '.join(params) if params else '无参数'}"
        examples = info.get("examples", [])
        if examples:
            line += f"\n  示例: {' | '.join(examples[:2])}"
        tool_lines.append(line)
    return "\n".join(tool_lines)


# 模块级缓存 — 只算一次
DYNAMIC_SCHEMA = generate_dynamic_schema()
PROMPT_TOOLS_TEXT = generate_prompt_text(DYNAMIC_SCHEMA)
