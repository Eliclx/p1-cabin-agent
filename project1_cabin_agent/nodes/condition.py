"""
project1_cabin_agent/nodes/condition.py
条件评估模块 —— 根据上游 task 的 tool_result 判断是否执行当前 task。

设计原则（方案 C：运行时校验）：
  - 不做预声明，直接从 task_results 取实际数据评估
  - 字段不存在 → 条件视为不通过（保守策略：宁可多问，不要错误执行）
  - 被 route_wave 调用，评估通过 → 正常调度；不通过 → 替换为 direct_answer

支持的比较操作（企业标准 IF/ELSE 节点）：
  eq / neq / gt / gte / lt / lte / in / not_in / is_empty / is_not_empty
"""

from __future__ import annotations

from typing import Any

from shared.utils.logger import logger


def evaluate_condition(
    condition: dict,
    task_results: list[dict],
) -> tuple[bool, str]:
    """评估条件是否满足。

    Args:
        condition: {
            "logic": "AND" | "OR",
            "rules": [{"source": "task_0", "field": "count", "op": "gt", "value": 0}],
            "fail_msg": "附近没有充电站"
        }
        task_results: 已完成的 task 结果列表

    Returns:
        (passed, fail_msg) — passed=True 表示条件满足，fail_msg 仅在不通过时有意义
    """
    logic = condition.get("logic", "AND").upper()
    rules = condition.get("rules", [])
    fail_msg = condition.get("fail_msg", "条件不满足，已跳过该任务")

    if not rules:
        return True, ""

    # 构建 source → tool_result.data 的查找表
    result_map: dict[str, dict] = {}
    for r in task_results:
        tid = r.get("task_id", "")
        tr = r.get("tool_result", {})
        # 取 data 层（和 session_update 同逻辑）
        inner = tr.get("data")
        if isinstance(inner, dict):
            result_map[tid] = inner
        else:
            result_map[tid] = {
                k: v
                for k, v in tr.items()
                if k not in ("status", "voice_reply", "success")
            }

    results: list[bool] = []
    for rule in rules:
        passed = _evaluate_rule(rule, result_map)
        results.append(passed)

    # AND: 全部 True → True；OR: 任一 True → True
    if logic == "OR":
        final = any(results)
    else:
        final = all(results)

    if not final:
        logger.info(f"[condition] ❌ 不通过: {fail_msg}")
    else:
        logger.info("[condition] ✅ 通过")

    return final, fail_msg if not final else ""


# LLM 常见 field 名别夗 → 工具实际返回的字段名
# 解决 LLM 猜测 field 名不精确的问题
_FIELD_ALIASES: dict[str, list[str]] = {
    "weather_main": ["weather"],
    "weather_desc": ["weather"],
    "weather_type": ["weather"],
    "traffic_status": ["traffic"],
    "traffic_info": ["traffic"],
    "traffic_condition": ["traffic"],
    "result_count": ["count"],
    "num_results": ["count"],
    "total": ["count"],
    "eta": ["duration", "duration_min"],
    "eta_min": ["duration_min", "duration"],
    "distance": ["distance_km"],
    "fuel_level": ["fuel"],
    "battery_level": ["battery"],
    "oil": ["fuel"],
}


def _resolve_field(field: str, data: dict) -> tuple[str, Any | None]:
    """解析字段名：先精确匹配，再别名匹配，再后缀模糊匹配。

    返回 (resolved_field, value)，未找到返回 (field, None)。
    """
    # 1. 精确匹配
    if field in data:
        return field, data[field]

    # 2. 别名匹配
    aliases = _FIELD_ALIASES.get(field, [])
    for alias in aliases:
        if alias in data:
            return alias, data[alias]

    # 3. 后缀模糊匹配：LLM 写 traffic_status，数据有 traffic → 前缀匹配
    for key in data:
        if key.startswith(field.split("_")[0]) or field.startswith(key.split("_")[0]):
            return key, data[key]

    return field, None


def _evaluate_rule(rule: dict, result_map: dict[str, dict]) -> bool:
    """评估单条规则。字段不存在时尝试别名容错，仍找不到 → 保守策略不通过。"""
    source = rule.get("source", "")
    field = rule.get("field", "")
    op = rule.get("op", "")
    value = rule.get("value")

    data = result_map.get(source)
    if data is None:
        logger.warning(
            f"[condition] source '{source}' 不在 task_results 中 → 降级不通过"
        )
        return False

    resolved_field, actual = _resolve_field(field, data)
    if actual is None:
        logger.warning(
            f"[condition] field '{field}' 不在 {source} 的结果中 "
            f"(可用字段: {list(data.keys())}) → 降级不通过"
        )
        return False

    if resolved_field != field:
        logger.info(f"[condition] 字段别名: {field} → {resolved_field}")

    try:
        return _compare(actual, op, value)
    except Exception as e:
        logger.warning(
            f"[condition] 比较异常 actual={actual} op={op} value={value}: {e}"
        )
        return False


def _compare(actual: Any, op: str, value: Any) -> bool:
    """执行比较操作。"""
    if op == "eq":
        return actual == value
    elif op == "neq":
        return actual != value
    elif op == "gt":
        return float(actual) > float(value)
    elif op == "gte":
        return float(actual) >= float(value)
    elif op == "lt":
        return float(actual) < float(value)
    elif op == "lte":
        return float(actual) <= float(value)
    elif op == "in":
        return actual in value
    elif op == "not_in":
        return actual not in value
    elif op == "is_empty":
        if isinstance(actual, list):
            return len(actual) == 0
        return not actual
    elif op == "is_not_empty":
        if isinstance(actual, list):
            return len(actual) > 0
        return bool(actual)
    else:
        logger.warning(f"[condition] 未知 op: {op}")
        return False
