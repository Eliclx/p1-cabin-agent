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
from project1_cabin_agent.edge_schemas import validate_slots

# ── 配置 ──

EDGE_ENABLED = os.getenv("EDGE_ENABLED", "false").lower() == "true"
EDGE_BASE_URL = os.getenv("EDGE_BASE_URL", "http://localhost:8001/v1")
EDGE_MODEL = os.getenv("EDGE_MODEL", "Qwen/Qwen2.5-3B-Instruct-AWQ")
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
- unknown: 无法判断

重要区分规则：
1. 车窗、灯光、座椅加热都属于车内环境(climate)，不是车况(vehicle)
2. "去XX"/"导航到XX"是导航(navigation)，不是搜索(search)
3. 天气、时间、日期类问题属于闲聊(chitchat)，不是搜索
4. 单字"暂停"是媒体操作(media)
5. 音量调节属于媒体(media)
6. 保养/维修/询问空调参数(温度、风速)属于车况(vehicle)

只输出领域名称（一个英文单词），不要其他文字。"""

# Stage1 不再需要单独的 user 模板，直接用裸输入


# ═══════════════════════════════════════════════════
# Stage2: Intent + Slot 提取 Prompt（按 domain 分）
# ═══════════════════════════════════════════════════

STAGE2_SYSTEM_TEMPLATE = """你是车载语音助手的语义解析器。
用户输入属于 {domain} 领域。请提取意图和槽位。

输出JSON格式：{{"intent": "意图名", "slots": {{"槽位名": 值}}}}

{domain} 领域的意图列表（必须从中选择）：
{intents}

规则：
1. intent 必须从上面的列表中选
2. slots 提取关键参数
3. 只输出JSON，不要其他文字

示例：
{examples}"""

# 按 domain 提供对应的 few-shot 示例
_DOMAIN_EXAMPLES = {
    "climate": "输入：打开空调\n输出：{{\"intent\": \"ac_control\", \"slots\": {{}}}}",
    "navigation": "输入：导航去天府广场\n输出：{{\"intent\": \"start_navigation\", \"slots\": {{\"destination\": \"天府广场\"}}}}",
    "media": "输入：播放周杰伦的歌\n输出：{{\"intent\": \"media_control\", \"slots\": {{\"artist\": \"周杰伦\"}}}}",
    "search": "输入：附近有没有加油站\n输出：{{\"intent\": \"search_poi\", \"slots\": {{\"keyword\": \"加油站\"}}}}",
    "vehicle": "输入：还有多少油\n输出：{{\"intent\": \"query_vehicle_status\", \"slots\": {{}}}}",
    "chitchat": "输入：你好啊\n输出：{{\"intent\": \"chitchat\", \"slots\": {{}}}}",
    "unknown": "输入：随便说点什么\n输出：{{\"intent\": \"unknown\", \"slots\": {{}}}}",
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


def _build_stage2_system(domain: str) -> str:
    intents = DOMAIN_INTENTS.get(domain, ["unknown"])
    intent_str = ", ".join(intents)
    examples = _DOMAIN_EXAMPLES.get(domain, _DOMAIN_EXAMPLES["unknown"])
    return STAGE2_SYSTEM_TEMPLATE.format(domain=domain, intents=intent_str, examples=examples)


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

    @property
    def is_acceptable(self) -> bool:
        return (
            self.error is None
            and self.confidence >= EDGE_CONFIDENCE_THRESHOLD
            and self.intent not in _SKIP_INTENTS
        )


# ═══════════════════════════════════════════════════
# HTTP 调用
# ═══════════════════════════════════════════════════

def _call_llm(messages: list, max_tokens: int = 40) -> dict:
    """调用 LMDeploy API，返回 {raw_text, latency_ms}"""
    import time
    start = time.monotonic()

    payload_dict = {
        "model": EDGE_MODEL,
        "messages": messages,
        "temperature": 0.01,
        "max_tokens": max_tokens,
    }

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
    """Stage1: domain 分类，返回 (domain, latency_ms)"""
    messages = [
        {"role": "system", "content": STAGE1_SYSTEM},
        {"role": "user", "content": user_input},
    ]
    try:
        result = _call_llm(messages, max_tokens=10)
    except Exception as e:
        logger.warning(f"[edge stage1] LLM error: {e}")
        return "unknown", 0

    raw = result["raw_text"].strip().lower()
    latency = result["latency_ms"]

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
    """Stage2: 提取 intent + slots，返回 (intent, slots, latency_ms)"""
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
        )

    # Stage2: intent + slots
    intent, raw_slots, lat2 = _extract_intent_and_slots(user_input, domain)
    total_lat = (time.monotonic() - total_start) * 1000

    if intent == "unknown":
        return EdgeResult(
            intent="chitchat", confidence=0.85, slots={},
            domain=domain, latency_ms=total_lat, error="intent_unknown",
        )

    # 白名单校验
    clean_slots = validate_slots(domain, intent, raw_slots)

    if raw_slots and not clean_slots:
        logger.info(f"[edge 白名单] 全部过滤: {raw_slots} → {{}} (domain={domain}, intent={intent})")
    elif clean_slots != raw_slots:
        logger.info(f"[edge 白名单] 部分过滤: {raw_slots} → {clean_slots}")

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
    )


# ═══════════════════════════════════════════════════
# 兼容层
# ═══════════════════════════════════════════════════

def _parse_edge_json(text: str) -> dict | None:
    """解析端侧模型输出的 JSON，兼容 markdown 包裹"""
    if "```" in text:
        lines = text.split("\n")
        text = "\n".join(l for l in lines if not l.strip().startswith("```"))

    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass

    return None


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
