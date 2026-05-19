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
- navigation: 导航（路线、地点、路况等）
- media: 媒体（音乐、电台、视频等）
- search: 搜索（周边设施、新闻、知识问答等）
- vehicle: 车况（油量、胎压、车速、里程、保养等）
- chitchat: 闲聊（打招呼、情感、日常对话、笑话、天气/时间/日期等）
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
2. "去XX"/"导航到XX"是导航(navigation)，不是搜索(search)
3. 天气、时间、日期类问题属于闲聊(chitchat)，不是搜索
4. 单字"暂停"是媒体操作(media)
5. 音量调节属于媒体(media)
6. 保养/维修/询问空调参数(温度、风速)属于车况(vehicle)

只输出领域名称（一个英文单词），不要其他文字。"""

# Stage1 不再需要单独的 user 模板，直接用裸输入


_STAGE1_CACHED_PROMPT: str | None = None


def _build_stage1_system() -> str:
    """
    Builds the Stage 1 system prompt and injects few-shot examples discovered in skills' examples.yaml.
    
    Constructs a prompt used for domain classification by combining the base STAGE1_SYSTEM with example lines loaded from skill example files. If no examples are found, falls back to STAGE1_SYSTEM. The composed prompt is cached at module level and only generated on first call (skill YAML files are not expected to hot-update).
    Returns:
        stage1_prompt (str): The complete system prompt to use for Stage 1 domain classification.
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
    """
    Load Stage1 few-shot examples from skills/*/examples.yaml for use as single-source examples.
    
    Scans each skill directory's examples.yaml (if present), collects up to two examples per intent, maps specific intent names to edge domains (`navigate_to` -> `navigation`, `search_nearby` -> `search`), and returns at most 15 examples. Files that are missing or produce parsing errors are skipped silently.
    
    Returns:
        list[dict]: A list of example objects each containing:
            - "input" (str): the example user utterance
            - "domain" (str): the mapped edge domain name
    """
    import yaml, os
    
    examples = []
    
    # intent → domain 映射（边缘模型 domain 比 skill 细粒度）
    intent_domain_map = {
        "navigate_to": "navigation",
        "search_nearby": "search",
    }
    
    skills_dir = os.path.join(os.path.dirname(__file__), "skills")
    for skill_name in os.listdir(skills_dir):
        yaml_path = os.path.join(skills_dir, skill_name, "examples.yaml")
        if not os.path.exists(yaml_path):
            continue
        try:
            with open(yaml_path) as f:
                data = yaml.safe_load(f) or {}
            for intent_name, intent_examples in data.items():
                if not isinstance(intent_examples, list):
                    continue
                domain = intent_domain_map.get(intent_name, skill_name)
                for ex in intent_examples[:2]:
                    inp = ex.get("input", "")
                    if inp:
                        examples.append({"input": inp, "domain": domain})
        except Exception:
            pass
    
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

# 按 domain 提供对应的 few-shot 示例
_DOMAIN_EXAMPLES = {
    "climate": (
        "输入：打开空调\n输出：{{\"intent\": \"ac_control\", \"slots\": {{\"action\": \"on\"}}}}\n"
        "输入：空调调到22度\n输出：{{\"intent\": \"ac_control\", \"slots\": {{\"action\": \"adjust\", \"temperature\": 22}}}}\n"
        "输入：关车窗\n输出：{{\"intent\": \"window_control\", \"slots\": {{\"target\": \"window\", \"action\": \"close\"}}}}\n"
        "输入：调小点\n输出：{{\"intent\": \"ac_control\", \"slots\": {{}}}}"
    ),
    "navigation": (
        "输入：导航去天府广场\n输出：{{\"intent\": \"start_navigation\", \"slots\": {{\"destination\": \"天府广场\"}}}}\n"
        "输入：我想去\n输出：{{\"intent\": \"start_navigation\", \"slots\": {{}}}}"
    ),
    "media": (
        "输入：播放周杰伦的歌\n输出：{{\"intent\": \"media_control\", \"slots\": {{\"action\": \"play\", \"query\": \"周杰伦\"}}}}\n"
        "输入：调小点\n输出：{{\"intent\": \"media_control\", \"slots\": {{\"action\": \"volume_down\"}}}}\n"
        "输入：打开\n输出：{{\"intent\": \"media_control\", \"slots\": {{\"action\": \"play\"}}}}"
    ),
    "search": (
        "输入：附近有没有加油站\n输出：{{\"intent\": \"search_poi\", \"slots\": {{\"keyword\": \"加油站\"}}}}"
    ),
    "vehicle": (
        "输入：还有多少油\n输出：{{\"intent\": \"query_vehicle_status\", \"slots\": {{}}}}\n"
        "输入：舒适模式\n输出：{{\"intent\": \"activate_scene\", \"slots\": {{\"scene_name\": \"comfortable_driving\"}}}}"
    ),
    "chitchat": (
        "输入：你好啊\n输出：{{\"intent\": \"chitchat\", \"slots\": {{}}}}"
    ),
    "unknown": (
        "输入：随便说点什么\n输出：{{\"intent\": \"unknown\", \"slots\": {{}}}}"
    ),
}

# 领域→意图映射（与 eval_harness / fast_rules 对齐）
DOMAIN_INTENTS = {
    "climate": [
        "ac_control", "window_control", "light_control", "seat_control",
    ],
    "navigation": [
        "start_navigation",
    ],
    "media": [
        "media_control",
    ],
    "search": [
        "search_poi",
    ],
    "vehicle": [
        "query_vehicle_status", "activate_scene",
    ],
    "chitchat": ["chitchat"],
    "unknown": ["unknown"],
}


def _build_schema_block(domain: str) -> str:
    """从 INTENT_SCHEMAS 生成精简的 schema 描述，注入 Stage2 prompt"""
    from project1_cabin_agent.edge_schemas import INTENT_SCHEMAS
    domain_schemas = INTENT_SCHEMAS.get(domain, {})
    if not domain_schemas:
        return "无"
    lines = []
    for intent_name, schema in domain_schemas.items():
        desc = schema.get("desc", "")
        slot_parts = []
        for key, spec in schema.get("slots", {}).items():
            stype = spec["type"]
            sdesc = spec.get("desc", "")
            if stype == "enum":
                vals = "|".join(spec["values"])
                slot_parts.append(f"{key}({sdesc}, 可选值:{vals})")
            elif stype == "number":
                lo, hi = spec.get("range", [0, 9999])
                slot_parts.append(f"{key}({sdesc}, 数字{lo}~{hi})")
            else:
                slot_parts.append(f"{key}({sdesc}, 文本)")
        slots_str = ", ".join(slot_parts) if slot_parts else "无槽位"
        lines.append(f"- {intent_name}({desc}): {slots_str}")
    return "\n".join(lines)


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
        """
        Determine whether the edge inference result is acceptable for direct use.
        
        Performs the acceptance checks used by callers to decide whether to use the edge result or fall back to cloud handling: no recorded error, confidence meets the configured threshold, intent is not in the skip list, not all model-provided slots were removed by whitelist filtering, and at least one required slot (if any are defined for the intent) is present and non-empty.
        
        Returns:
            true if the result passes all acceptance checks, false otherwise.
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
    """
    Send messages to the configured edge LLM endpoint and return the model text and round-trip latency.
    
    Parameters:
        messages (list): Conversation messages following the chat-completion schema sent to the edge model.
        max_tokens (int): Maximum number of tokens the model is allowed to generate.
        response_format (dict | None): Optional schema guiding model output formatting (passed through to the endpoint).
    
    Returns:
        dict: Dictionary with keys:
            - raw_text (str): The trimmed content generated by the model.
            - latency_ms (float): End-to-end request latency in milliseconds.
    """
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
    """
    Classify the user's input into a single domain for stage‑1 inference.
    
    Builds the stage1 system prompt (including few‑shot examples), sends the prompt and user input to the edge LLM, and interprets the model output. If an LLM error occurs the function returns ("unknown", 0). If the model output contains "multi" the function returns ("unknown", latency) to indicate a detected multi‑intent case that should bypass stage2. Otherwise the function returns the first domain (from DOMAIN_INTENTS keys) found as a substring in the model output; if no match is found it returns "unknown".
    
    Returns:
        (domain, latency_ms): `domain` is a one-word domain name or `"unknown"`; `latency_ms` is the LLM call latency in milliseconds (0 if an error occurred).
    """
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
    """
    Extract intent and slots from a user's input constrained by the specified domain.
    
    If `domain` is "unknown" this function returns immediately with intent "unknown", an empty slots dict, and 0 latency. The function returns the parsed intent name (or "unknown" on error/parse failure), a dict of extracted slots (empty on failure or when not a mapping), and the LLM response latency in milliseconds.
    
    Parameters:
        user_input (str): The user's raw input text to be parsed.
        domain (str): The domain context used to constrain extraction; if "unknown", extraction is skipped.
    
    Returns:
        tuple[str, dict, float]: A tuple of `(intent, slots, latency_ms)` where `intent` is the extracted intent name or `"unknown"`, `slots` is a mapping of extracted slot names to values (empty on failure), and `latency_ms` is the LLM call latency in milliseconds (0 for immediate short-circuits or errors).
    """
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
    Perform two-stage edge inference to determine domain, intent, and slots from a user input.
    
    Stage 1 performs domain classification; if the domain is "unknown" the function returns an EdgeResult indicating a fallback chitchat intent with `error="domain_unknown"`. Stage 2 performs intent and slot extraction for known domains; if intent extraction fails the function returns an EdgeResult indicating a fallback chitchat intent with `error="intent_unknown"`. Extracted slots are passed through `validate_slots(...)` and the result is returned. The returned EdgeResult.lantency_ms is the total elapsed inference time in milliseconds.
    
    Parameters:
        user_input (str): The raw user utterance to analyze.
    
    Returns:
        EdgeResult: Result populated with:
          - intent: detected intent or "chitchat" for fallback cases.
          - confidence: fixed score used for edge results (0.85).
          - slots: validated/cleaned slots (empty on fallback or when none remain).
          - domain: detected domain or "unknown".
          - latency_ms: total inference latency in milliseconds.
          - error: "domain_unknown" or "intent_unknown" for fallback cases, otherwise None.
          - all_slots_filtered: True when model-provided slots existed but were all removed by whitelist validation, False otherwise.
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
    """
    Extracts an intent-and-slots structure from noisy model output text.
    
    Attempts a three-stage recovery: (1) strict JSON parse, (2) normalization to repair minor JSON noise then parse, and (3) regex-based extraction when JSON recovery fails. Preserves JSON `null` semantics for slot values and only returns results whose intent is recognized by the schema validator.
    
    Parameters:
        text (str): Raw text output from the model.
    
    Returns:
        dict | None: A mapping that typically contains at least `"intent"` (str) and `"slots"` (dict) when extraction succeeds; `None` if no valid intent/slots could be recovered.
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
    """
    Normalize lightly corrupted JSON-like text by trimming extra braces and removing trailing commas.
    
    Performs non-destructive repairs commonly seen in model outputs: collapses repeated leading or trailing braces (e.g., "{{{...}}}" -> "{...}"), removes trailing commas before `}` or `]`, and returns None when the text is missing closing braces (unrecoverable). Explicit `null` values are preserved.
    
    Parameters:
        text (str): The raw model output to normalize.
    
    Returns:
        str | None: The normalized text suitable for JSON parsing, or `None` if the structure is missing required closing braces.
    """
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
    """
    Extract an `intent` and its `slots` from a non-JSON text blob using regular expressions.
    
    This function searches the input for an `"intent"` field matching `[a-z_]+` and then scans for key/value pairs of the forms `"key": "string"`, `"key": number`, or `"key": null`. String values are JSON-decoded, numeric values are returned as `int` or `float`, and `null` is returned as `None`. The function does not require the input to be valid JSON and returns `None` if no valid intent is found.
    
    Returns:
        dict | None: A mapping `{"intent": <str>, "slots": {<key>: <value>, ...}}` when an intent is found (slots may be empty), or `None` if no valid intent is detected.
    """
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
    """
    Check whether an intent name is defined in the configured intent schemas.
    
    Parameters:
        intent (str): The intent name to validate.
    
    Returns:
        bool: `True` if the intent appears in any domain's intent schema, `False` otherwise.
    """
    for domain_schemas in __import__("project1_cabin_agent.edge_schemas", fromlist=["INTENT_SCHEMAS"]).INTENT_SCHEMAS.values():
        if intent in domain_schemas:
            return True
    return False


def edge_result_to_subtask(result: EdgeResult) -> dict:
    """
    Map an EdgeResult into the downstream `sub_task` dictionary schema expected by cloud/downstream services.
    
    Parameters:
        result (EdgeResult): The edge inference result to convert.
    
    Returns:
        dict: A dictionary with the following keys:
            - task_id: fixed string "task_0".
            - intent: intent name from `result`.
            - intent_confidence: intent confidence from `result`.
            - ambiguity_score: numeric ambiguity score (fixed to 0.0).
            - ambiguity_reason: explanation for ambiguity (empty string when none).
            - required_slots: list of required slots (empty list when not provided).
            - extracted_slots: validated slot mapping from `result.slots`.
            - depends_on: dependency list for the task (empty list when none).
            - urgency: urgency level for the task (fixed to "normal").
    """
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
