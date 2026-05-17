"""
project1_cabin_agent/scripts/validate_schema_examples.py
Schema + Examples 一致性校验脚本

启动时运行，确保 Pydantic schema 和 YAML few-shot 示例保持一致。

双向校验：
  正向：examples 里的 slot key 必须在 schema 中存在
  反向：schema 里的 required slot 必须在 examples 中出现（覆盖度）

用法：
  python scripts/validate_schema_examples.py
  python scripts/validate_schema_examples.py --domain navigation
"""
import sys
import os
import json
import yaml
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from project1_cabin_agent.skills.navigation.schema import NAVIGATION_INTENTS


def validate_domain(domain_name: str, intent_schemas: dict[str, type], examples: dict) -> list[str]:
    """
    校验单个 domain 的 schema + examples 一致性。
    
    Args:
        domain_name: 域名（如 "navigation"）
        intent_schemas: {intent_name: Pydantic class}
        examples: 从 YAML 加载的 examples dict
        
    Returns:
        errors: 错误列表，空=全部通过
    """
    errors = []
    
    for intent_name, model_cls in intent_schemas.items():
        schema = model_cls.model_json_schema()
        props = schema.get("properties", {})
        required_fields = set(schema.get("required", []))
        
        # ── 检查 examples 中是否有该 intent ──
        intent_examples = examples.get(intent_name, [])
        if not intent_examples:
            errors.append(f"[{domain_name}/{intent_name}] ❌ 没有 few-shot 示例")
            continue
        
        # ── 正向校验：examples 里的 slot key 必须在 schema 中存在 ──
        for i, ex in enumerate(intent_examples):
            ex_id = ex.get("input", f"#{i}")[:20]
            output = ex.get("output", {})
            slots = output.get("slots", {})
            
            for slot_name in slots:
                if slot_name not in props:
                    errors.append(
                        f"[{domain_name}/{intent_name}] 示例 '{ex_id}' 有未知 slot '{slot_name}'，"
                        f"schema 中不存在"
                    )
            
            # 检查 intent 名是否匹配
            ex_intent = output.get("intent", "")
            if ex_intent and ex_intent != intent_name:
                errors.append(
                    f"[{domain_name}/{intent_name}] 示例 '{ex_id}' 的 intent='{ex_intent}' "
                    f"与当前 intent='{intent_name}' 不匹配"
                )
        
        # ── 反向校验：required slot 必须在 examples 中出现 ──
        for slot_name in required_fields:
            covered = [
                ex for ex in intent_examples
                if slot_name in ex.get("output", {}).get("slots", {})
            ]
            if not covered:
                errors.append(
                    f"[{domain_name}/{intent_name}] ❌ 必填 slot '{slot_name}' "
                    f"在 {len(intent_examples)} 条示例中从未出现"
                )
        
        # ── 覆盖度统计 ──
        all_slots = set(props.keys())
        covered_slots = set()
        for ex in intent_examples:
            covered_slots.update(ex.get("output", {}).get("slots", {}).keys())
        
        uncovered = all_slots - covered_slots
        if uncovered and not required_fields.issubset(covered_slots):
            # 只有 required 未覆盖才报错，optional 未覆盖只是警告
            pass
        
        tag_coverage = _check_tag_coverage(domain_name, intent_name, intent_examples)
        errors.extend(tag_coverage)
    
    # ── 检查 YAML 中是否有 schema 里没有的 intent ──
    for intent_name in examples:
        if intent_name not in intent_schemas:
            errors.append(
                f"[{domain_name}] ❌ examples.yaml 中有 intent '{intent_name}'，"
                f"但 schema.py 中没有定义"
            )
    
    return errors


def _check_tag_coverage(domain_name: str, intent_name: str, examples: list) -> list[str]:
    """检查 tag 覆盖度：每个 intent 至少有 literal 和 implicit 的示例"""
    warnings = []
    
    all_tags = set()
    for ex in examples:
        all_tags.update(ex.get("tags", []))
    
    # 建议覆盖的 tag 类型
    recommended_tags = {"literal", "implicit"}
    missing_tags = recommended_tags - all_tags
    
    if missing_tags:
        for tag in missing_tags:
            warnings.append(
                f"[{domain_name}/{intent_name}] ⚠️ 缺少 '{tag}' 类型的示例"
            )
    
    return warnings


def validate_navigation():
    """校验 navigation skill 的 schema + examples"""
    print("=" * 60)
    print("校验 Navigation Skill: schema.py ↔ examples.yaml")
    print("=" * 60)
    
    # 1. 加载 examples.yaml
    examples_path = PROJECT_ROOT / "project1_cabin_agent" / "skills" / "navigation" / "examples.yaml"
    if not examples_path.exists():
        print(f"❌ 文件不存在: {examples_path}")
        return False
    
    with open(examples_path, "r", encoding="utf-8") as f:
        examples = yaml.safe_load(f)
    
    print(f"\n✓ 加载 examples.yaml: {len(examples)} 个 intent")
    for intent_name, ex_list in examples.items():
        print(f"  - {intent_name}: {len(ex_list)} 条示例")
    
    # 2. 加载 schema
    print(f"\n✓ 加载 schema.py: {len(NAVIGATION_INTENTS)} 个 intent")
    for intent_name, model_cls in NAVIGATION_INTENTS.items():
        schema = model_cls.model_json_schema()
        required = schema.get("required", [])
        props = list(schema.get("properties", {}).keys())
        print(f"  - {intent_name}: 字段 {props}, 必填 {required}")
    
    # 3. 运行校验
    print(f"\n{'─' * 60}")
    errors = validate_domain("navigation", NAVIGATION_INTENTS, examples)
    
    if errors:
        print(f"\n❌ 校验失败，{len(errors)} 个问题：\n")
        for err in errors:
            print(f"  {err}")
        return False
    else:
        print("\n✅ 全部通过！schema 和 examples 完全一致。\n")
        
        # 4. 打印覆盖度统计
        print("覆盖度统计：")
        for intent_name, model_cls in NAVIGATION_INTENTS.items():
            schema = model_cls.model_json_schema()
            props = set(schema.get("properties", {}).keys())
            intent_exs = examples.get(intent_name, [])
            
            covered = set()
            for ex in intent_exs:
                covered.update(ex.get("output", {}).get("slots", {}).keys())
            
            uncovered = props - covered
            tags = set()
            for ex in intent_exs:
                tags.update(ex.get("tags", []))
            
            print(f"  {intent_name}:")
            print(f"    字段覆盖: {len(covered)}/{len(props)}" + 
                  (f"（未覆盖: {uncovered}）" if uncovered else " ✓"))
            print(f"    Tag 覆盖: {tags}")
            print(f"    示例数量: {len(intent_exs)}")
        
        return True


if __name__ == "__main__":
    success = validate_navigation()
    sys.exit(0 if success else 1)
