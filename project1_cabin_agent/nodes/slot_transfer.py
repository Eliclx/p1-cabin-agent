"""
project1_cabin_agent/nodes/slot_transfer.py
黑板槽位回填：消费者空槽 → 从黑板按实体标签取值 → 排序选取 → 填入。

设计原则：
- 工具只管执行，黑板只管存，回填只管取
- sort_by/pick 是 extracted_slots 里的元数据，不传给工具函数
- 每步可选：无 sort_by 跳过排序，无 pick 跳过选取
"""
from shared.utils.logger import logger


def fill_slots_from_blackboard(
    extracted_slots: dict,
    blackboard_decl: dict | None,
    dialogue_context: dict,
) -> dict:
    """
    从黑板回填消费者的空槽位。

    Args:
        extracted_slots: 消费者的原始 extracted_slots（含 sort_by/pick 元数据）
            例: {"destination": null, "sort_by": "distance", "pick": 0}
        blackboard_decl: 消费者的黑板声明（consumes + slots）
            例: {"consumes": "entity.poi", "slots": {"destination": "name"}}
        dialogue_context: 黑板数据（栈式），key=实体标签，value=栈（栈顶=最新）
            例: {
                "entity.poi": [
                    {"round": 2, "task_id": "task_2", "data": {"keyword": "加油站",
                     "results": [{"name": "壳牌", "distance": "0.8km", "rating": 4.0}]}},
                    {"round": 1, "task_id": "task_0", "data": {"keyword": "牛排馆",
                     "results": [{"name": "王品牛排", "distance": "1.2km", "rating": 4.5},
                                 {"name": "莫尔顿", "distance": "2.5km", "rating": 4.8}]}},
                ],
                "entity.route": [
                    {"round": 1, "task_id": "task_1", "data": {"destination": "王品牛排",
                     "route": {"eta": "15分钟", "distance": "3.2km", "traffic": "畅通"}}},
                ],
            }

    Returns:
        更新后的 extracted_slots（空槽已填充，sort_by/pick 已移除）
            例: {"destination": "王品牛排"}
    """
    if not blackboard_decl or "consumes" not in blackboard_decl:
        return extracted_slots

    entity_tag = blackboard_decl["consumes"]
    slot_mapping = blackboard_decl.get("slots", {})   # {"destination": "name"}

    # ── ① 检查是否有空槽需要回填 ──
    empty_slots = [s for s in slot_mapping if not extracted_slots.get(s)]
    if not empty_slots:
        return extracted_slots

    # ── ② 从黑板取数据（默认栈顶） ──
    stack = dialogue_context.get(entity_tag, [])
    if not stack:
        logger.debug(f"[slot_transfer] 黑板无 {entity_tag} 数据")
        return extracted_slots

    entry = _resolve_layer(stack, extracted_slots)
    if not entry:
        return extracted_slots

    data = entry.get("data", {})

    # ── ③ 排序（可选） ──
    sort_by = extracted_slots.get("sort_by")
    items = _get_items(data)   # 可能是列表或单个对象
    if sort_by and isinstance(items, list) and len(items) > 1:
        items = _sort_items(items, sort_by, extracted_slots.get("sort_order", "asc"))

    # ── ④ 选取（可选） ──
    pick = extracted_slots.get("pick")
    if pick is not None and isinstance(items, list) and len(items) > 0:
        idx = min(pick, len(items) - 1)
        items = [items[idx]]
    elif isinstance(items, list) and len(items) == 1:
        pass  # 只有一个，直接用
    elif isinstance(items, list) and len(items) > 1:
        items = [items[0]]  # 默认取第一个

    # ── ⑤ 提取字段，填入空槽 ──
    result = {**extracted_slots}
    target = items[0] if isinstance(items, list) and items else items

    for slot_name, field_name in slot_mapping.items():
        if not result.get(slot_name) and isinstance(target, dict):
            value = target.get(field_name, "")
            if value:
                result[slot_name] = str(value)
                logger.info(
                    f"[slot_transfer] -> {slot_name} ← {entity_tag}.{field_name} = {value}"
                )

    # ── ⑥ 清理元数据（sort_by/pick 不传给工具） ──
    result.pop("sort_by", None)
    result.pop("sort_order", None)
    result.pop("pick", None)

    return result


def _resolve_layer(stack: list, extracted_slots: dict) -> dict | None:
    """决定取栈的哪一层。默认取栈顶（最新的）。"""
    # TODO: 支持 round 指定（"第一次搜的那个"）和序数词（"最后一个"）
    return stack[0] if stack else None


def _get_items(data: dict) -> list | dict:
    """从黑板条目的 data 中提取可操作的列表。"""
    # search_poi 返回 {"keyword": ..., "results": [...]}
    # 优先取 results 字段
    if "results" in data and isinstance(data["results"], list):
        return data["results"]
    # 如果本身就是列表
    if isinstance(data, list):
        return data
    # 单个对象（如 route）
    return data


def _sort_items(items: list, field: str, order: str = "asc") -> list:
    """按字段排序，支持数值和字符串。"""
    reverse = order == "desc"

    def sort_key(item):
        val = item.get(field, "")
        # 尝试提取数值（如 "1.2km" → 1.2）
        if isinstance(val, str):
            import re
            m = re.match(r"([\d.]+)", val)
            return float(m.group(1)) if m else 0
        return val if isinstance(val, (int, float)) else 0

    return sorted(items, key=sort_key, reverse=reverse)
