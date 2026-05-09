"""
project1_cabin_agent/nodes/schema.py
技能自动发现引擎 — 解析工具 docstring，生成动态意图-槽位 schema。
"""
from project1_cabin_agent.tools.cabin_tools import ALL_TOOLS


def _parse_docstring(docstring: str) -> dict:
    lines = docstring.strip().split("\n")
    result = {
        "description": lines[0].strip() if lines else "",
        "param_descriptions": {},
        "examples": [],
        "anti_examples": [],
        "implicit_maps": [],
        "risk_level": "normal",
    }
    for line in lines[1:]:
        line = line.strip()
        if line.startswith(":param "):
            _, rest = line.split(":param ", 1)
            if ":" in rest:
                pname, desc = rest.split(":", 1)
                result["param_descriptions"][pname.strip()] = desc.strip()
        elif line.startswith(":example: "):
            result["examples"].append(line[len(":example: "):])
        elif line.startswith(":anti_example: "):
            result["anti_examples"].append(line[len(":anti_example: "):])
        elif line.startswith(":implicit_map: "):
            result["implicit_maps"].append(line[len(":implicit_map: "):])
        elif line.startswith(":risk_level: "):
            result["risk_level"] = line[len(":risk_level: "):].strip()
    return result


def generate_dynamic_schema(tools: list) -> dict:
    """解析工具列表，生成动态意图-槽位 schema，供 intent_classifier 使用。"""
    schema = {}
    for t in tools:
        args_info = t.args
        required_slots = []
        optional_slots = []
        for arg_name, arg_meta in args_info.items():
            if 'default' in arg_meta or 'anyOf' in arg_meta:
                optional_slots.append(arg_name)
            else:
                required_slots.append(arg_name)
        doc_meta = _parse_docstring(t.description or "")
        schema[t.name] = {
            "description": doc_meta["description"],
            "required": required_slots,
            "optional": optional_slots,
            "param_descriptions": doc_meta["param_descriptions"],
            "examples": doc_meta["examples"],
            "anti_examples": doc_meta["anti_examples"],
            "implicit_maps": doc_meta["implicit_maps"],
            "risk_level": doc_meta["risk_level"],
        }
    schema["chitchat"] = {"description": "日常闲聊或无关对话", "required": [], "optional": [],
                           "param_descriptions": {}, "examples": [], "anti_examples": [],
                           "implicit_maps": [], "risk_level": "normal"}
    schema["direct_answer"] = {"description": "直接回答用户的信息查询（数据已在dialogue_context中，无需调工具）。当用户询问上轮搜索结果的细节时使用，如'第2个是什么'、'最远的是哪个'。不要对需要执行操作的使用此意图。",
                               "required": [], "optional": [],
                               "param_descriptions": {},
                               "examples": ["第2个加油站是什么", "最远的是哪个", "第一个的评分多少"],
                               "anti_examples": ["帮我导航去第二个（这是操作指令，应识别为start_navigation）"],
                               "implicit_maps": [], "risk_level": "normal"}
    schema["no_support"] = {"description": "用户请求超出系统能力范围（外卖、购物、电话、订票等），礼貌告知暂不支持",
                             "required": [], "optional": [],
                             "param_descriptions": {},
                             "examples": ["帮我点个外卖", "打电话给张三", "买张机票"],
                             "anti_examples": ["帮我导航（这是支持的start_navigation）"],
                             "implicit_maps": [], "risk_level": "normal"}
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
DYNAMIC_SCHEMA = generate_dynamic_schema(ALL_TOOLS)
PROMPT_TOOLS_TEXT = generate_prompt_text(DYNAMIC_SCHEMA)
