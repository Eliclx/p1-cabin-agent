"""
project1_cabin_agent/skills/registry.py
Skill 注册中心 — domain/intent → skill 模块映射

设计原则：
- 替代旧的 INTENT_TO_TOOL 扁平查表
- 按 domain 找到对应的 skill 包，从包内取 harness/tools/schema
- 新旧并存：未迁移的 domain 返回 None，走旧路径

现有 domain → intent 映射（来自 edge_model.py DOMAIN_INTENTS）：
  climate:    ac_control, window_control, light_control, seat_control
  navigation: start_navigation（新: navigate_to, search_nearby）
  media:      media_control
  search:     search_poi
  vehicle:    query_vehicle_status, activate_scene
  chitchat:   chitchat
  unknown:    unknown
"""
import importlib
from types import ModuleType
from typing import Optional

from project1_cabin_agent.harness.base import BaseHarness
from shared.utils.logger import logger


# ── 辅助函数 ──────────────────────────────────────────────────────

def _domain_to_class_name(domain: str) -> str:
    """将 domain 名转为 PascalCase 类名前缀

    navigation → Navigation, vehicle_control → VehicleControl
    """
    return "".join(part.capitalize() for part in domain.split("_"))


# ── 已迁移到新架构的 domain ──────────────────────────────────────
# 每个 domain 对应 skills/{domain}/ 包
# 只有在这里注册的 domain 才走新路径（harness → tools → schema）
# 未注册的走旧路径（INTENT_TO_TOOL → TOOL_REGISTRY）
_MIGRATED_DOMAINS: set[str] = {
    "navigation",
    "media",
    "vehicle",
    "search",
    "climate",
}

# domain → intent 别名映射（新架构的 intent 名可能和旧的不一样）
# 旧 intent → 新 intent 的映射，让新旧路径能互相识别
_INTENT_MIGRATION_MAP: dict[str, str] = {
    "start_navigation": "navigate_to",
}

# 模块级缓存：避免每次查询都 importlib
_schema_cache: dict[str, ModuleType] = {}


def is_domain_migrated(domain: str) -> bool:
    """检查 domain 是否已迁移到新架构"""
    return domain in _MIGRATED_DOMAINS


def is_intent_migrated(intent: str) -> bool:
    """检查 intent 是否属于已迁移的 domain"""
    # 先看是不是新 intent（直接在已迁移域的 schema 中定义）
    domain = get_domain_for_intent(intent)
    return domain is not None and is_domain_migrated(domain)


def get_domain_for_intent(intent: str) -> Optional[str]:
    """根据 intent 名反查 domain

    查找顺序：
    1. 遍历已迁移 domain 的 schema，看 intent 是否在其中定义
    2. 未找到 → 返回 None（走旧路径）
    """
    for domain in _MIGRATED_DOMAINS:
        intents_attr = _get_intents_attr(domain)
        if intents_attr and intent in intents_attr:
            return domain
    return None


def _get_intents_attr(domain: str) -> Optional[dict]:
    """获取 domain schema 模块中的 intent 映射

    约定：每个 domain 的 schema.py 都导出一个 {DOMAIN}_INTENTS 字典
    如 navigation → NAVIGATION_INTENTS
    """
    if domain in _schema_cache:
        schema_mod = _schema_cache[domain]
    else:
        try:
            schema_mod = importlib.import_module(
                f"project1_cabin_agent.skills.{domain}.schema"
            )
            _schema_cache[domain] = schema_mod
        except ImportError:
            return None

    attr_name = f"{domain.upper()}_INTENTS"
    return getattr(schema_mod, attr_name, None)


def get_harness(domain: str) -> Optional[BaseHarness]:
    """获取 domain 对应的 harness 实例

    约定：skills/{domain}/harness.py 导出 {Domain}Harness 类
    如 navigation → NavigationHarness
    """
    if not is_domain_migrated(domain):
        return None

    try:
        harness_mod = importlib.import_module(
            f"project1_cabin_agent.skills.{domain}.harness"
        )
        # 约定类名：{Domain}Harness
        class_name = f"{_domain_to_class_name(domain)}Harness"
        harness_cls = getattr(harness_mod, class_name)
        return harness_cls()
    except (ImportError, AttributeError) as e:
        logger.error(f"[SkillRegistry] 无法加载 {domain} harness: {e}")
        return None


def get_tools_module(domain: str) -> Optional[ModuleType]:
    """获取 domain 对应的 tools 模块

    约定：skills/{domain}/tools.py 导出和 intent 同名的函数
    如 navigation → navigate_to(), search_nearby()
    """
    if not is_domain_migrated(domain):
        return None

    try:
        return importlib.import_module(
            f"project1_cabin_agent.skills.{domain}.tools"
        )
    except ImportError as e:
        logger.error(f"[SkillRegistry] 无法加载 {domain} tools: {e}")
        return None


def get_tool_function(domain: str, intent: str):
    """获取 domain + intent 对应的工具函数

    约定：tools.py 中的函数名和 intent 名一致
    如 navigation + navigate_to → tools.navigate_to()
    """
    tools_mod = get_tools_module(domain)
    if tools_mod is None:
        return None

    # 如果是新 intent 名，直接用；如果是旧 intent 名，先转换
    actual_intent = _INTENT_MIGRATION_MAP.get(intent, intent)
    fn = getattr(tools_mod, actual_intent, None)
    if fn is None:
        logger.warning(f"[SkillRegistry] {domain}.tools 没有 {actual_intent} 函数")
    return fn


def get_skill_knowledge_path(domain: str) -> Optional[str]:
    """获取 domain SKILL.md 的文件路径（给云端 LLM 读）"""
    if not is_domain_migrated(domain):
        return None
    from pathlib import Path
    skill_path = Path(__file__).parent / domain / "SKILL.md"
    return str(skill_path) if skill_path.exists() else None


# ── 辅助：列出所有已注册信息（调试用） ─────────────────────────

def list_registry() -> dict:
    """返回当前注册中心状态（调试用）"""
    result = {}
    for domain in _MIGRATED_DOMAINS:
        harness = get_harness(domain)
        tools = get_tools_module(domain)
        intents = _get_intents_attr(domain)
        result[domain] = {
            "harness": type(harness).__name__ if harness else None,
            "tools": bool(tools),
            "intents": list(intents.keys()) if intents else [],
            "skill_md": bool(get_skill_knowledge_path(domain)),
        }
    return result
