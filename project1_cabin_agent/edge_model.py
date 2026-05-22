"""
project1_cabin_agent/edge_model.py
端侧模型推理 — 本地 3B INT4 (LMDeploy OpenAI 兼容接口)。

设计原则（v7 两阶段 System+User + 区分规则）：
- Stage1: domain 分类（system=领域列表+区分规则, user=裸输入）
- Stage2: intent + slot 提取（system=intent列表+few-shot, user=裸输入）
- 白名单校验 → 过滤幻觉 key + 类型/范围校验
- JSON parse 失败 → 兜底为 chitchat，放行云端
- EDGE_ENABLED 开关控制，关闭时完全跳过

与 v5 差异:
- 恢复两阶段架构（Stage1 domain → Stage2 intent/slot）
- 每个 stage 都用 System+User 分离格式（替代 v4 的纯 user 一坨）
"""
import os
import json
import urllib.request
import urllib.error
from dataclasses import dataclass

from shared.utils.logger import logger
from project1_cabin_agent.edge_schemas import validate_slots, get_required_slots
from project1_cabin_agent.skills.registry import registry

# ── 配置 ──

EDGE_ENABLED = os.getenv("EDGE_ENABLED", "false").lower() == "true"
EDGE_BASE_URL = os.getenv("EDGE_BASE_URL", "http://localhost:8001/v1")
EDGE_MODEL = os.getenv("EDGE_MODEL", "Qwen2.5-3B-Instruct-AWQ")
EDGE_TIMEOUT = int(os.getenv("EDGE_TIMEOUT", "5"))
EDGE_CONFIDENCE_THRESHOLD = float(os.getenv("EDGE_CONFIDENCE_THRESHOLD", "0.85"))

# 端侧不处理的意图（交给云端）
_SKIP_INTENTS = {"clarify", "direct_answer", "multi_intent"}

# 置信度标签 → 数值映射（logprobs 不可用时兜底）
_CONFIDENCE_MAP = {
    "high": 0.95, "高": 0.95,
    "medium": 0.70, "中": 0.70,
    "low": 0.40, "低": 0.40,
}


# ═══════════════════════════════════════════════════
# Stage1: Domain 分类 Prompt（v7: system=区分规则, user=领域列表）
# ═══════════════════════════════════════════════════

STAGE1_SYSTEM = """你是车载语音助手的领域分类器。

领域列表：
- climate: 车内环境（空调、温度、车窗、灯光、座椅加热等）
- map: 地图与位置（导航、路线、周边搜索、地点查询、天气等）
- media: 媒体（音乐、电台、视频等）
- vehicle: 车况（油量、胎压、车速、里程、保养等）
- chitchat: 闲聊（打招呼、情感、日常对话、笑话、时间/日期等）
- multi: 多意图（用户一句话包含多个不相关的动作，如"开窗放音乐"）
- unknown: 无法判断

多意图识别规则（优先判断）：
1. 如果输入包含来自不同领域的动作词，输出 multi
   - 例："开窗放音乐" → 开窗(climate) + 放音乐(media) → multi
   - 例："帮我打开空调并播放音乐" → 开空调(climate) + 放音乐(media) → multi
2. 连接词提示多意图："并" "然后" "顺便" "同时" "再" "也" "接着"
   - 例："先找加油站再导航过去" → multi
3. 同一个领域的多个操作不算是 multi
   - 例："打开空调调到22度" → climate（空调控制+调温是同一个领域）
   - 例："关窗关灯" → climate（车窗和灯光都是车内环境）

重要区分规则：
1. 车窗、灯光、座椅加热都属于车内环境(climate)，不是车况(vehicle)
2. "去XX"/"导航到XX"/"附近有没有XX"都属于地图(map)
3. 时间、日期类问题属于闲聊(chitchat)
4. 单字"暂停"是媒体操作(media)
5. 音量调节属于媒体(media)
6. 保养/维修/询问空调参数(温度、风速)属于车况(vehicle)

只输出领域名称（一个英文单词），不要其他文字。"""

# Stage1 不再需要单独的 user 模板，直接用裸输入


_STAGE1_CACHED_PROMPT: str | None = None


def _build_stage1_system() -> str:
    """构建 Stage1 系统 prompt，从 skill examples.yaml 动态注入 few-shot。
    
    单一真相源：skill 的 examples.yaml 定义 domain→example 映射，
    未迁移的域用训练数据 training_stage1.jsonl 兜底。
    
    结果缓存到模块级变量，只在首次调用时读文件（yaml 不会热更新）。
    """
    global _STAGE1_CACHED_PROMPT
    if _STAGE1_CACHED_PROMPT is not None:
        return _STAGE1_CACHED_PROMPT

    examples = _load_stage1_examples()
    if not examples:
        _STAGE1_CACHED_PROMPT = STAGE1_SYSTEM
        return _STAGE1_CACHED_PROMPT

    lines = [STAGE1_SYSTEM, "", "示例（从 skill examples.yaml 自动注入）："]
    for ex in examples:
        lines.append(f"输入：{ex['input']} → {ex['domain']}")
    _STAGE1_CACHED_PROMPT = "\n".join(lines)
    return _STAGE1_CACHED_PROMPT


def _load_stage1_examples() -> list[dict]:
    """从 registry 加载 Stage1 few-shot 示例"""
    examples = []
    for domain in registry.get_all_intents():
        registry._ensure_examples_loaded(domain)
        entry = registry._skills.get(domain)
        if entry is None:
            continue
        for intent_name, cases in entry.examples.items():
            if not isinstance(cases, list):
                continue
            for ex in cases[:2]:
                inp = ex.get("input", "")
                if inp:
                    examples.append({"input": inp, "domain": domain})
    return examples[:15]


# ═══════════════════════════════════════════════════
# Stage2: Intent + Slot 提取 Prompt（按 domain 分）
# ═══════════════════════════════════════════════════

STAGE2_SYSTEM_TEMPLATE = """你是车载语音助手的语义解析器。
用户输入属于 {domain} 领域。请提取意图和槽位。

输出JSON格式：{{"intent": "意图名", "slots": {{"槽位名": 值}}}}

{domain} 领域的意图和槽位定义：
{schema_block}

规则：
1. intent 必须从上面的列表中选
2. slot key 必须用上面定义的英文名，不能自己造key
3. slot value 必须符合类型要求（enum从可选值中选，数字在范围内）
4. 无法确定的槽位不要填，留空即可（不要猜测）
5. 只输出严格JSON，花括号必须配对，末尾不能有多余的}}或{{
6. 只输出JSON，不要其他文字

示例：
{examples}"""

# ── SSOT: 从 registry 构建 few-shot / intents / schema ──


def _build_domain_examples(max_per_intent: int = 2) -> dict:
    """从 registry 构建 domain examples，保留双花括号转义格式用于 STAGE2_SYSTEM_TEMPLATE.format()"""
    result = {}
    for domain in registry.get_all_intents():
        registry._ensure_examples_loaded(domain)
        entry = registry._skills.get(domain)
        if entry is None:
            continue
        lines = []
        for intent_name, cases in entry.examples.items():
            if not isinstance(cases, list):
                continue
            # 优先 literal，再补其他
            selected = [c for c in cases if "literal" in c.get("tags", [])]
            fallback = [c for c in cases if "literal" not in c.get("tags", [])]
            picked = (selected + fallback)[:max_per_intent]

            for c in picked:
                raw_output = json.dumps(
                    {"intent": c["output"]["intent"], "slots": c["output"]["slots"]},
                    ensure_ascii=False,
                )
                # 双花括号转义：虽然 .format() 不二次处理替换值中的花括号，
                # 但模板 STAGE2_SYSTEM_TEMPLATE 内部用 {{ }} 表示示例格式，
                # 保持 examples 和模板风格一致，模型已适配此格式
                escaped = raw_output.replace("{", "{{").replace("}", "}}")
                lines.append(f"输入：{c['input']}\n输出：{escaped}")

        if lines:
            result[domain] = "\n".join(lines) + "\n"
    return result


DOMAIN_INTENTS = registry.get_all_intents()

# chitchat/unknown 不在 skills 目录，兜底补上
for _d in ("chitchat", "unknown"):
    if _d not in DOMAIN_INTENTS:
        DOMAIN_INTENTS[_d] = [_d]

_DOMAIN_EXAMPLES = _build_domain_examples()
# chitchat/unknown 兜底 examples（双花括号转义保持一致）
for _d in ("chitchat", "unknown"):
    if _d not in _DOMAIN_EXAMPLES:
        _DOMAIN_EXAMPLES[_d] = (
            f'输入：你好啊\n输出：{{{{"intent": "{_d}", "slots": {{}}}}}}\n'
            f'输入：随便说点什么\n输出：{{{{"intent": "{_d}", "slots": {{}}}}}}'
        )


def _build_schema_block(domain: str) -> str:
    """从 registry 构建 schema block，格式和旧版 edge_schemas 一致"""
    all_intents = registry.get_all_intents()
    intent_names = all_intents.get(domain, [])
    if not intent_names:
        return "无"
    lines = []
    for intent_name in intent_names:
        spec = registry.get_intent_spec(intent_name)
        if spec is None:
            continue
        desc = spec.description
        slot_parts = []
        for key, slot_def in spec.slots.items():
            # Handle anyOf (Optional fields)
            effective = slot_def
            if "anyOf" in slot_def:
                for item in slot_def["anyOf"]:
                    if item.get("type") != "null":
                        effective = item
                        break
            # description 可能在 anyOf 父级，优先取父级
            sdesc = slot_def.get("description", slot_def.get("desc", "")) or effective.get("description", effective.get("desc", ""))
            if "enum" in effective:
                vals = "|".join(effective["enum"])
                slot_parts.append(f"{key}({sdesc}, 可选值:{vals})")
            elif effective.get("type") in ("integer", "number"):
                lo = effective.get("minimum", 0)
                hi = effective.get("maximum", 9999)
                slot_parts.append(f"{key}({sdesc}, 数字{lo}~{hi})")
            else:
                slot_parts.append(f"{key}({sdesc}, 文本)")
        slots_str = ", ".join(slot_parts) if slot_parts else "无槽位"
        lines.append(f"- {intent_name}({desc}): {slots_str}")
    return "\n".join(lines) if lines else "无"


def _build_stage2_system(domain: str) -> str:
    schema_block = _build_schema_block(domain)
    examples = _DOMAIN_EXAMPLES.get(domain, _DOMAIN_EXAMPLES["unknown"])
    return STAGE2_SYSTEM_TEMPLATE.format(domain=domain, schema_block=schema_block, examples=examples)


# ═══════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════

@dataclass
class EdgeResult:
    """端侧推理结果（接口不变，兼容 intent.py）"""
    intent: str
    confidence: float
    slots: dict
    domain: str = ""
    raw_text: str = ""
    latency_ms: float = 0.0
    error: str | None = None
    all_slots_filtered: bool = False  # P2: 模型输出了 slot 但全部被白名单拒绝

    @property
    def is_acceptable(self) -> bool:
        """端侧结果是否可接受，直出给用户

        检查链：
        1. 无 error（domain/intent 都识别出来了）
        2. confidence 达标
        3. intent 不是跳过类（chitchat/unknown）
        4. 白名单全空 → 降级（P2：模型输出 slot 但全部被拒绝=幻觉）
        5. 必填 slots 至少有一个非空（P0：堵住"自信直出空 slots"的漏洞）
        """
        if self.error is not None:
            return False
        if self.confidence < EDGE_CONFIDENCE_THRESHOLD:
            return False
        if self.intent in _SKIP_INTENTS:
            return False

        # P2: 白名单全空 → 模型在猜测，降级云端
        if self.all_slots_filtered:
            return False

        # P0: 必填 slots 检查
        required = get_required_slots(self.intent)
        if required:
            filled = any(self.slots.get(k) for k in required)
            if not filled:
                return False

        return True


# ═══════════════════════════════════════════════════
# HTTP 调用
# ═══════════════════════════════════════════════════

def _call_llm(messages: list, max_tokens: int = 40, response_format: dict | None = None) -> dict:
    """调用 LMDeploy API，返回 {raw_text, latency_ms}。可选 response_format 用于 guided generation。"""
    import time
    start = time.monotonic()

    payload_dict = {
        "model": EDGE_MODEL,
        "messages": messages,
        "temperature": 0.01,
        "max_tokens": max_tokens,
    }
    if response_format:
        payload_dict["response_format"] = response_format

    payload = json.dumps(payload_dict).encode("utf-8")
    url = f"{EDGE_BASE_URL}/chat/completions"

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=EDGE_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    raw_text = data["choices"][0]["message"]["content"].strip()
    latency_ms = (time.monotonic() - start) * 1000

    return {"raw_text": raw_text, "latency_ms": latency_ms}


# ═══════════════════════════════════════════════════
# 两阶段推理
# ═══════════════════════════════════════════════════

def _classify_domain(user_input: str) -> tuple[str, float]:
    """Stage1: domain 分类，返回 (domain, latency_ms)。prompt 从 skill examples.yaml 动态构建。"""
    system_prompt = _build_stage1_system()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    try:
        result = _call_llm(messages, max_tokens=10)
    except Exception as e:
        logger.warning(f"[edge stage1] LLM error: {e}")
        return "unknown", 0

    raw = result["raw_text"].strip().lower()
    latency = result["latency_ms"]

    # 显式处理 multi → 多意图，跳过 Stage2 直接降级云端
    if "multi" in raw:
        logger.info(f"[edge stage1] → multi-intent detected, bypass edge")
        return "unknown", latency

    # 匹配合法 domain
    valid_domains = list(DOMAIN_INTENTS.keys())
    domain = "unknown"
    for d in valid_domains:
        if d in raw:
            domain = d
            break

    logger.info(f"[edge stage1] → domain={domain} raw={raw[:30]} latency={latency:.0f}ms")
    return domain, latency


def _extract_intent_and_slots(user_input: str, domain: str) -> tuple[str, dict, float]:
    """Stage2: 提取 intent + slots，返回 (intent, slots, latency_ms)。
    
    Q2 优化：去掉 guided generation (xgrammar FSM)，改用纯 prompt 约束 + harness 兜底。
    原因：LMDeploy xgrammar FSM 导致 decode 每token从8ms涨到33ms（+300%），
    但 benchmark 132 case 对比显示准确率只差 0.9%（76.0% vs 76.9%），格式失败率不变。
    延迟从 534ms → 192ms（-64%）。"""
    if domain == "unknown":
        return "unknown", {}, 0

    system_prompt = _build_stage2_system(domain)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    
    try:
        result = _call_llm(messages, max_tokens=60)
    except Exception as e:
        logger.warning(f"[edge stage2] LLM error: {e}")
        return "unknown", {}, 0

    raw = result["raw_text"]
    latency = result["latency_ms"]

    parsed = _parse_edge_json(raw)
    if parsed is None:
        logger.info(f"[edge stage2] JSON parse failed: {raw[:80]}")
        return "unknown", {}, latency

    intent = parsed.get("intent", "unknown")
    raw_slots = parsed.get("slots", {})
    if not isinstance(raw_slots, dict):
        raw_slots = {}

    logger.info(f"[edge stage2] → intent={intent} slots={raw_slots} latency={latency:.0f}ms")
    return intent, raw_slots, latency


# ═══════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════

def edge_model_infer(user_input: str) -> EdgeResult:
    """
    端侧两阶段推理（v6）：
      Stage1: domain 分类 (System+User)
      Stage2: intent + slot 提取 (System+User)
    """
    import time
    total_start = time.monotonic()

    # Stage1: domain
    domain, lat1 = _classify_domain(user_input)

    if domain == "unknown":
        total_lat = (time.monotonic() - total_start) * 1000
        return EdgeResult(
            intent="chitchat", confidence=0.85, slots={},
            domain=domain, latency_ms=total_lat, error="domain_unknown",
            all_slots_filtered=False,
        )

    # Stage2: intent + slots
    intent, raw_slots, lat2 = _extract_intent_and_slots(user_input, domain)
    total_lat = (time.monotonic() - total_start) * 1000

    if intent == "unknown":
        return EdgeResult(
            intent="chitchat", confidence=0.85, slots={},
            domain=domain, latency_ms=total_lat, error="intent_unknown",
            all_slots_filtered=False,
        )

    # 白名单校验
    clean_slots = validate_slots(domain, intent, raw_slots)

    if raw_slots and not clean_slots:
        logger.info(f"[edge 白名单] 全部过滤: {raw_slots} → {{}} (domain={domain}, intent={intent})")
        all_slots_filtered = True
    elif clean_slots != raw_slots:
        logger.info(f"[edge 白名单] 部分过滤: {raw_slots} → {clean_slots}")
        all_slots_filtered = False
    else:
        all_slots_filtered = False

    logger.info(
        f"[edge result] domain={domain} intent={intent} "
        f"slots={clean_slots} total_latency={total_lat:.0f}ms"
    )

    return EdgeResult(
        intent=intent,
        confidence=0.85,
        slots=clean_slots,
        domain=domain,
        latency_ms=total_lat,
        all_slots_filtered=all_slots_filtered,
    )


# ═══════════════════════════════════════════════════
# 兼容层
# ═══════════════════════════════════════════════════

def _parse_edge_json(text: str) -> dict | None:
    """Harness 约束提取器：不信任 JSON 格式，多级降级从噪声中提取信号。

    L1: json.loads 严格解析 → confidence × 1.0
    L2: 去噪声 + json.loads（剥多余花括号、去尾部逗号、null 保留）
    L3: 正则硬提取（intent + slot 逐个匹配，不依赖 JSON 结构）
    
    每一级提取的 {intent, slots} 仍会过 validate_slots 白名单校验。
    """
    import re

    # ── 清理 ──
    if "```" in text:
        lines = text.split("\n")
        text = "\n".join(l for l in lines if not l.strip().startswith("```"))
    text = text.strip()

    # ── L1: 严格解析 ──
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ── L2: 去噪声后解析 ──
    cleaned = _level2_normalize(text)
    if cleaned:
        try:
            parsed = json.loads(cleaned)
            # null 保留语义（"用户没提到"），不转空串
            if isinstance(parsed, dict) and "intent" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass

    # ── L3: 正则硬提取（不依赖 JSON 结构）──
    parsed = _level3_regex_extract(text)
    if parsed and _validate_intent(parsed.get("intent", "")):
        return parsed

    return None


def _level2_normalize(text: str) -> str | None:
    """L2 去噪声：剥多余花括号、去尾部逗号。保留 null 语义。"""
    import re

    # 剥首尾多余花括号（端侧 3B 常见：{{...}}）
    text = re.sub(r'^\{\{+', '{', text)  # {{{...→ {
    text = re.sub(r'\}\}+$', '}', text)  # ...}}} → }

    # 数花括号，平衡配对
    opens = text.count("{")
    closes = text.count("}")
    if closes > opens:
        # 从尾部切除多余 }
        idx = text.rfind("}")
        text = text[:idx + 1]
        opens = text.count("{")
        closes = text.count("}")

    if opens > closes:
        return None  # 少 }，结构破损太严重

    # 去尾部逗号: , }
    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r",\s*\]", "]", text)

    return text


def _level3_regex_extract(text: str) -> dict | None:
    """L3 正则硬提取：不依赖 JSON 结构，逐个匹配 intent + slot。"""
    import re

    # 提取 intent
    intent_m = re.search(r'"intent"\s*:\s*"([a-z_]+)"', text)
    if not intent_m:
        return None

    intent = intent_m.group(1)
    slots = {}

    # 提取 slot key-value 对: "key": "val" 或 "key": 数字 或 "key": null
    for m in re.finditer(r'"(\w+)"\s*:\s*("([^"\\]*(\\.[^"\\]*)*)"|(\d+\.?\d*)|null)', text):
        key = m.group(1)
        if key == "intent":
            continue
        val_str = m.group(2)
        if val_str == "null":
            slots[key] = None  # 保留 null 语义
        elif val_str.startswith('"'):
            slots[key] = json.loads(val_str)  # 安全 parse 单个字符串值
        else:
            slots[key] = float(val_str) if "." in val_str else int(val_str)

    return {"intent": intent, "slots": slots} if slots or intent else None


def _validate_intent(intent: str) -> bool:
    """校验 intent 是否在已知列表中（防正则误提取）"""
    for domain_schemas in __import__("project1_cabin_agent.edge_schemas", fromlist=["INTENT_SCHEMAS"]).INTENT_SCHEMAS.values():
        if intent in domain_schemas:
            return True
    return False


def edge_result_to_subtask(result: EdgeResult) -> dict:
    """把端侧结果转换为 sub_task dict（和云端输出格式一致）"""
    return {
        "task_id": "task_0",
        "intent": result.intent,
        "intent_confidence": result.confidence,
        "ambiguity_score": 0.0,
        "ambiguity_reason": "",
        "required_slots": [],
        "extracted_slots": result.slots,
        "depends_on": [],
        "urgency": "normal",
    }
