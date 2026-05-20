"""
project1_cabin_agent/skills/registry.py
Skill 注册中心 — 自动扫描 skills/ 目录，按需加载

设计原则：
- 替代旧的 _MIGRATED_DOMAINS 手动注册 + importlib 逐个加载
- SkillRegistry 类在 __init__ 时自动扫描 skills/ 下所有含 schema.py 的子目录
- 每个 skill 目录约定 4 个文件：schema.py, tools.py, harness.py, examples.yaml
- 从 schema.py 加载 {DOMAIN}_INTENTS 字典（如 CLIMATE_INTENTS, MAP_INTENTS 等）
- 从 examples.yaml 加载 few-shot 示例
- 从 tools.py 加载工具函数（按 intent 名映射）
- 从 harness.py 加载校验函数（get_validator / get_formatter）
- 缺文件时 log warning 但不 crash，该 skill 跳过

全局单例：registry = SkillRegistry(Path(__file__).parent)
"""
from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

import yaml
from pydantic import BaseModel
from shared.utils.logger import logger


# ── Intent 别名映射（旧名 → 新名）────────────────────────────────
_INTENT_ALIASES: dict[str, str] = {
    "start_navigation": "navigate",
    "search_nearby": "search_poi",
}

# 兜底 domain：chitchat / unknown 不在 skills 目录，需要硬编码兜底
_FALLBACK_DOMAINS = {"chitchat", "unknown"}

# 每个 skill 目录必须包含的文件
_REQUIRED_FILES = ("schema.py", "tools.py", "harness.py", "examples.yaml")


# ── 数据结构 ───────────────────────────────────────────────────────

@dataclass
class IntentSpec:
    """单个 intent 的描述信息"""
    name: str
    domain: str
    description: str
    slots: dict[str, Any]  # model_json_schema()["properties"]
    slot_model: type[BaseModel]  # Pydantic model 类


@dataclass
class _SkillEntry:
    """单个 skill 目录的注册信息（内部使用）"""
    domain: str
    path: Path
    intents: dict[str, IntentSpec] = field(default_factory=dict)
    tools: dict[str, Callable] = field(default_factory=dict)
    validators: dict[str, Callable] = field(default_factory=dict)
    formatters: dict[str, Callable] = field(default_factory=dict)
    examples: dict[str, list[dict]] = field(default_factory=dict)
    tools_loaded: bool = False
    harness_loaded: bool = False
    examples_loaded: bool = False


# ── SkillRegistry ─────────────────────────────────────────────────

class SkillRegistry:
    """
    自动扫描 skills/ 目录，按需加载 schema / tools / harness / examples。

    用法：
        from project1_cabin_agent.skills.registry import registry
        spec = registry.get_intent_spec("ac_control")
        tool_fn = registry.get_tool("ac_control")
    """

    def __init__(self, skills_dir: Path) -> None:
        self._skills_dir = skills_dir
        # domain → _SkillEntry
        self._skills: dict[str, _SkillEntry] = {}
        # intent_name → domain（快速反查）
        self._intent_to_domain: dict[str, str] = {}
        # 加载状态标记
        self._scanned = False

        self._scan_skills_dir()

    # ── 扫描 ──────────────────────────────────────────────────────

    def _scan_skills_dir(self) -> None:
        """扫描 skills/ 目录下所有含 schema.py 的子目录"""
        if not self._skills_dir.is_dir():
            logger.warning(f"[SkillRegistry] skills 目录不存在: {self._skills_dir}")
            return

        for child in sorted(self._skills_dir.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith("_") or child.name.startswith("."):
                continue
            # 必须有 schema.py
            schema_file = child / "schema.py"
            if not schema_file.exists():
                continue

            # 检查 4 个必需文件
            missing = [f for f in _REQUIRED_FILES if not (child / f).exists()]
            if missing:
                logger.warning(
                    f"[SkillRegistry] skill '{child.name}' 缺少文件 {missing}，跳过"
                )
                continue

            domain = child.name
            entry = _SkillEntry(domain=domain, path=child)
            self._skills[domain] = entry

            # 立即加载 schema（轻量），tools/harness/examples 延迟到首次访问
            self._load_schema(entry)

        self._scanned = True
        logger.info(
            f"[SkillRegistry] 扫描完成: {len(self._skills)} 个 skill "
            f"({list(self._skills.keys())})"
        )

    # ── Schema 加载 ───────────────────────────────────────────────

    def _load_schema(self, entry: _SkillEntry) -> bool:
        """从 schema.py 加载 {DOMAIN}_INTENTS 字典"""
        domain = entry.domain
        module_name = f"project1_cabin_agent.skills.{domain}.schema"

        try:
            schema_mod = importlib.import_module(module_name)
        except Exception as e:
            logger.warning(f"[SkillRegistry] 加载 {domain} schema 失败: {e}")
            return False

        # 查找 {DOMAIN}_INTENTS 字典
        attr_name = f"{domain.upper()}_INTENTS"
        intents_dict: dict[str, type[BaseModel]] | None = getattr(schema_mod, attr_name, None)
        if intents_dict is None:
            # 尝试遍历模块属性找 *_INTENTS
            for attr in dir(schema_mod):
                if attr.upper().endswith("_INTENTS") and not attr.startswith("_"):
                    val = getattr(schema_mod, attr)
                    if isinstance(val, dict):
                        intents_dict = val
                        break

        if intents_dict is None:
            logger.warning(
                f"[SkillRegistry] {domain} schema.py 未导出 {attr_name}，跳过"
            )
            return False

        # 构建 IntentSpec
        for intent_name, model_cls in intents_dict.items():
            if not (isinstance(model_cls, type) and issubclass(model_cls, BaseModel)):
                logger.warning(
                    f"[SkillRegistry] {domain}.{intent_name} 不是 BaseModel 子类，跳过"
                )
                continue

            doc = model_cls.__doc__ or ""
            description = doc.strip().split("\n")[0]

            # 从 Pydantic model 获取 slot 定义
            schema_dict = model_cls.model_json_schema()
            slots = schema_dict.get("properties", {})

            spec = IntentSpec(
                name=intent_name,
                domain=domain,
                description=description,
                slots=slots,
                slot_model=model_cls,
            )
            entry.intents[intent_name] = spec
            self._intent_to_domain[intent_name] = domain

        return True

    # ── 延迟加载 helpers ──────────────────────────────────────────

    def _ensure_tools_loaded(self, domain: str) -> None:
        """延迟加载 tools.py"""
        entry = self._skills.get(domain)
        if entry is None or entry.tools_loaded:
            return

        module_name = f"project1_cabin_agent.skills.{domain}.tools"
        try:
            tools_mod = importlib.import_module(module_name)
        except Exception as e:
            logger.warning(f"[SkillRegistry] 加载 {domain} tools 失败: {e}")
            entry.tools_loaded = True  # 标记已尝试，避免重复
            return

        for intent_name in entry.intents:
            fn = getattr(tools_mod, intent_name, None)
            if fn is not None and callable(fn):
                entry.tools[intent_name] = fn
            else:
                logger.debug(
                    f"[SkillRegistry] {domain}.tools 中未找到函数 '{intent_name}'"
                )
        entry.tools_loaded = True

    def _ensure_harness_loaded(self, domain: str) -> None:
        """延迟加载 harness.py 中的 get_validator / get_formatter"""
        entry = self._skills.get(domain)
        if entry is None or entry.harness_loaded:
            return

        module_name = f"project1_cabin_agent.skills.{domain}.harness"
        try:
            harness_mod = importlib.import_module(module_name)
        except Exception as e:
            logger.warning(f"[SkillRegistry] 加载 {domain} harness 失败: {e}")
            entry.harness_loaded = True
            return

        # 约定：harness.py 导出 get_validator(intent) 和 get_formatter(intent)
        get_validator = getattr(harness_mod, "get_validator", None)
        get_formatter = getattr(harness_mod, "get_formatter", None)

        if get_validator is not None:
            for intent_name in entry.intents:
                try:
                    v = get_validator(intent_name)
                    if callable(v):
                        entry.validators[intent_name] = v
                except Exception:
                    pass

        if get_formatter is not None:
            for intent_name in entry.intents:
                try:
                    f = get_formatter(intent_name)
                    if callable(f):
                        entry.formatters[intent_name] = f
                except Exception:
                    pass

        # 如果 harness.py 使用旧的类式 harness（如 ClimateHarness），
        # 也支持通过 BaseHarness 子类获取 pre_validate / format_response
        self._try_load_class_harness(entry, harness_mod)
        entry.harness_loaded = True

    def _try_load_class_harness(self, entry: _SkillEntry, harness_mod: ModuleType) -> None:
        """兼容旧的 BaseHarness 子类模式（如 ClimateHarness）"""
        try:
            from project1_cabin_agent.harness.base import BaseHarness
        except ImportError:
            return

        for attr_name in dir(harness_mod):
            obj = getattr(harness_mod, attr_name, None)
            if (
                obj is not None
                and isinstance(obj, type)
                and issubclass(obj, BaseHarness)
                and obj is not BaseHarness
            ):
                try:
                    instance = obj()
                except Exception:
                    continue

                for intent_name in entry.intents:
                    # 如果已有新式 validator/formatter，跳过
                    if intent_name not in entry.validators:
                        pre_v = getattr(instance, "pre_validate", None)
                        if callable(pre_v):
                            entry.validators[intent_name] = pre_v
                    if intent_name not in entry.formatters:
                        fmt = getattr(instance, "format_response", None)
                        if callable(fmt):
                            entry.formatters[intent_name] = fmt
                break  # 只取第一个 BaseHarness 子类

    def _ensure_examples_loaded(self, domain: str) -> None:
        """延迟加载 examples.yaml"""
        entry = self._skills.get(domain)
        if entry is None or entry.examples_loaded:
            return

        yaml_path = entry.path / "examples.yaml"
        if not yaml_path.exists():
            return

        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"[SkillRegistry] 加载 {domain} examples.yaml 失败: {e}")
            return

        if not isinstance(data, dict):
            return

        for intent_name, examples in data.items():
            if isinstance(examples, list):
                entry.examples[intent_name] = examples
        entry.examples_loaded = True

    # ── 解析别名 ──────────────────────────────────────────────────

    def _resolve_alias(self, intent: str) -> str:
        """解析旧名别名映射"""
        return _INTENT_ALIASES.get(intent, intent)

    def _find_domain_for_intent(self, intent: str) -> str | None:
        """根据 intent 反查 domain"""
        # 先查别名
        resolved = self._resolve_alias(intent)
        domain = self._intent_to_domain.get(resolved)
        if domain is not None:
            return domain
        # 再查原名
        return self._intent_to_domain.get(intent)

    # ── 公共查询接口 ──────────────────────────────────────────────

    def get_all_intents(self) -> dict[str, list[str]]:
        """
        返回所有已注册 intent: {domain → [intent_name]}

        示例: {"climate": ["ac_control", "window_control", ...], ...}
        """
        result: dict[str, list[str]] = {}
        for domain, entry in self._skills.items():
            if entry.intents:
                result[domain] = list(entry.intents.keys())
        return result

    def get_intent_spec(self, intent: str) -> IntentSpec | None:
        """
        获取单个 intent 的 slot 定义（IntentSpec）。

        支持别名：start_navigation → navigate, search_nearby → search_poi
        """
        domain = self._find_domain_for_intent(intent)
        if domain is None:
            return None
        entry = self._skills.get(domain)
        if entry is None:
            return None
        # 先用原名查，再用别名查
        return entry.intents.get(intent) or entry.intents.get(self._resolve_alias(intent))

    def get_skill_for_intent(self, intent: str) -> str | None:
        """
        查询 intent 属于哪个 skill（返回 domain 名）。

        chitchat/unknown 返回自身名。
        """
        if intent in _FALLBACK_DOMAINS:
            return intent
        return self._find_domain_for_intent(intent)

    def get_examples(
        self, domain: str = None, max_per_intent: int = 2
    ) -> dict[str, str]:
        """
        获取 few-shot 示例文本。

        参数:
            domain: 指定 domain，None 则返回所有
            max_per_intent: 每个 intent 最多返回几条

        返回:
            {intent_name → 格式化的 few-shot 文本}
        """
        result: dict[str, str] = {}

        domains = [domain] if domain else list(self._skills.keys())
        for d in domains:
            self._ensure_examples_loaded(d)
            entry = self._skills.get(d)
            if entry is None:
                continue
            for intent_name, examples in entry.examples.items():
                selected = examples[:max_per_intent]
                parts: list[str] = []
                for ex in selected:
                    inp = ex.get("input", "")
                    out = ex.get("output", {})
                    parts.append(f"输入: {inp}\n输出: {out}")
                if parts:
                    result[intent_name] = "\n\n".join(parts)

        return result

    def get_tool(self, intent: str) -> Callable | None:
        """
        获取 intent 对应的可执行工具函数。

        约定：tools.py 中函数名 = intent 名。
        """
        domain = self._find_domain_for_intent(intent)
        if domain is None:
            return None
        self._ensure_tools_loaded(domain)
        entry = self._skills.get(domain)
        if entry is None:
            return None
        # 先用原名查，再用别名查
        return entry.tools.get(intent) or entry.tools.get(self._resolve_alias(intent))

    def get_validator(self, intent: str) -> Callable | None:
        """
        获取 intent 对应的校验函数。

        返回一个 Callable，约定签名：
            validate_fn(slots: dict, ctx) → HarnessResult
        对于旧式 BaseHarness 类，返回 pre_validate 方法。
        """
        domain = self._find_domain_for_intent(intent)
        if domain is None:
            return None
        self._ensure_harness_loaded(domain)
        entry = self._skills.get(domain)
        if entry is None:
            return None
        resolved = self._resolve_alias(intent)
        return entry.validators.get(intent) or entry.validators.get(resolved)

    def get_schema_block(self, domain: str) -> str:
        """
        生成 Stage2 prompt 里的 schema 描述文本。

        输出示例：
          - ac_control: 空调控制 — 开关/调温/调风 → 槽位: action(enum), temperature(number)
          - window_control: 车窗/天窗/车门控制 → 槽位: target(enum), action(enum)
        """
        entry = self._skills.get(domain)
        if entry is None:
            return ""

        lines: list[str] = []
        for intent_name, spec in entry.intents.items():
            slot_parts: list[str] = []
            for slot_name, slot_def in spec.slots.items():
                slot_type = slot_def.get("type", "string")
                if "enum" in slot_def:
                    slot_type = f"enum({','.join(slot_def['enum'])})"
                elif "anyOf" in slot_def:
                    # Optional 字段，anyOf 中找非 null 的类型
                    for item in slot_def["anyOf"]:
                        if item.get("type") != "null":
                            slot_type = item.get("type", "string")
                            if "enum" in item:
                                slot_type = f"enum({','.join(item['enum'])})"
                            break
                slot_parts.append(f"{slot_name}({slot_type})")

            slots_str = ", ".join(slot_parts)
            lines.append(f"  - {intent_name}: {spec.description} → 槽位: {slots_str}")

        return "\n".join(lines)

    def is_domain_migrated(self, domain: str) -> bool:
        """检查 domain 是否已迁移到新架构（兼容旧接口）"""
        if domain in _FALLBACK_DOMAINS:
            return True
        return domain in self._skills

    def is_intent_migrated(self, intent: str) -> bool:
        """检查 intent 是否属于已迁移的 domain（兼容旧接口）"""
        if intent in _FALLBACK_DOMAINS:
            return True
        return self._find_domain_for_intent(intent) is not None

    # ── 旧接口兼容（函数签名不变）───────────────────────────────────

    def get_domain_for_intent(self, intent: str) -> str | None:
        """根据 intent 反查 domain（兼容旧接口，同 get_skill_for_intent）"""
        return self.get_skill_for_intent(intent)

    def get_tool_function(self, domain: str, intent: str) -> Callable | None:
        """旧接口兼容：通过 domain + intent 获取工具函数"""
        self._ensure_tools_loaded(domain)
        entry = self._skills.get(domain)
        if entry is None:
            return None
        return entry.tools.get(intent)

    def get_tools_module(self, domain: str) -> ModuleType | None:
        """旧接口兼容：获取 tools 模块"""
        if domain not in self._skills:
            return None
        module_name = f"project1_cabin_agent.skills.{domain}.tools"
        try:
            return importlib.import_module(module_name)
        except ImportError:
            return None

    def get_harness_instance(self, domain: str):
        """旧接口兼容：获取 BaseHarness 子类实例"""
        if domain not in self._skills:
            return None

        module_name = f"project1_cabin_agent.skills.{domain}.harness"
        try:
            harness_mod = importlib.import_module(module_name)
        except ImportError:
            return None

        # 查找 {Domain}Harness 类
        class_name = "".join(part.capitalize() for part in domain.split("_")) + "Harness"
        harness_cls = getattr(harness_mod, class_name, None)
        if harness_cls is not None:
            try:
                return harness_cls()
            except Exception:
                pass

        # 兜底：遍历找 BaseHarness 子类
        try:
            from project1_cabin_agent.harness.base import BaseHarness
        except ImportError:
            return None

        for attr_name in dir(harness_mod):
            obj = getattr(harness_mod, attr_name, None)
            if (
                obj is not None
                and isinstance(obj, type)
                and issubclass(obj, BaseHarness)
                and obj is not BaseHarness
            ):
                try:
                    return obj()
                except Exception:
                    continue
        return None

    def get_skill_knowledge_path(self, domain: str) -> str | None:
        """旧接口兼容：获取 domain SKILL.md 的文件路径"""
        if domain not in self._skills:
            return None
        skill_path = self._skills_dir / domain / "SKILL.md"
        return str(skill_path) if skill_path.exists() else None

    def list_registry(self) -> dict:
        """返回当前注册中心状态（调试用）"""
        result = {}
        for domain, entry in self._skills.items():
            self._ensure_tools_loaded(domain)
            self._ensure_harness_loaded(domain)
            harness_inst = self.get_harness_instance(domain)
            result[domain] = {
                "harness": type(harness_inst).__name__ if harness_inst else None,
                "tools": list(entry.tools.keys()),
                "intents": list(entry.intents.keys()),
                "examples": list(entry.examples.keys()),
                "skill_md": bool(self.get_skill_knowledge_path(domain)),
            }
        return result

    def __repr__(self) -> str:
        domains = list(self._skills.keys())
        intents_count = sum(len(e.intents) for e in self._skills.values())
        return f"SkillRegistry(domains={domains}, total_intents={intents_count})"


# ── 全局单例 ──────────────────────────────────────────────────────
registry = SkillRegistry(Path(__file__).parent)


# ── 模块级函数（兼容旧调用方直接 import）───────────────────────────
# 旧代码: from project1_cabin_agent.skills.registry import is_domain_migrated, get_harness, ...

def is_domain_migrated(domain: str) -> bool:
    """兼容旧接口"""
    return registry.is_domain_migrated(domain)


def is_intent_migrated(intent: str) -> bool:
    """兼容旧接口"""
    return registry.is_intent_migrated(intent)


def get_domain_for_intent(intent: str) -> str | None:
    """兼容旧接口"""
    return registry.get_domain_for_intent(intent)


def get_harness(domain: str):
    """兼容旧接口：获取 domain 对应的 BaseHarness 实例"""
    return registry.get_harness_instance(domain)


def get_tools_module(domain: str) -> ModuleType | None:
    """兼容旧接口"""
    return registry.get_tools_module(domain)


def get_tool_function(domain: str, intent: str) -> Callable | None:
    """兼容旧接口"""
    return registry.get_tool_function(domain, intent)


def get_skill_knowledge_path(domain: str) -> str | None:
    """兼容旧接口"""
    return registry.get_skill_knowledge_path(domain)


def list_registry() -> dict:
    """兼容旧接口"""
    return registry.list_registry()
