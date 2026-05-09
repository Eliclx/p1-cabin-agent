#!/usr/bin/env python3
"""
project1_cabin_agent/tests/error_collector.py
错误收集器 — 数据飞轮入口。

每次运行测试时，将错误 case 写入 JSONL 日志。
后续用云端大模型对错误 case 做变体扩写 → 训练数据 → QLoRA 微调 3B。

用法:
    python -m project1_cabin_agent.tests.error_collector

环境变量:
    EDGE_ENABLED=true 必须（端侧模型需在线）
    LOG_FILE=errors.jsonl（默认在 tests/ 目录下）
"""

import json
import uuid
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from project1_cabin_agent.edge_model import edge_model_infer
from project1_cabin_agent.nodes.fast_rules import fast_rules_check
from project1_cabin_agent.nodes.intent import _can_use_edge


# ── 错误记录格式 ──

@dataclass
class ErrorRecord:
    """单条错误记录 — 企业三层格式（Layer1）"""
    error_id: str = ""       # uuid, 串联 seeds/training
    input: str = ""
    
    # 正确答案（= expected）
    domain: str = ""
    intent: Optional[str] = None
    slots: dict = field(default_factory=dict)
    
    # 实际输出
    actual_domain: str = ""
    actual_intent: str = ""
    actual_slots: dict = field(default_factory=dict)
    
    # 路由信息
    layer: str = ""          # fast_rule / edge / cloud
    gate_passed: bool = True
    latency_ms: float = 0.0
    
    # 错误分类
    error_stage: str = ""    # stage1(domain错) / stage2(intent+slot错)
    error_type: str = ""     # domain_miss / intent_confusion / slot_hallucination / multi_missed / gate_leak
    error_detail: str = ""
    
    # 元信息
    timestamp: str = ""
    model_name: str = "qwen2.5-3b-awq"


class ErrorLogger:
    """JSONL 错误日志"""
    
    def __init__(self, path: str = None):
        if path is None:
            path = Path(__file__).parent / "errors.jsonl"
        self.path = Path(path)
    
    def log(self, record: ErrorRecord):
        record.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        if not record.error_id:
            record.error_id = str(uuid.uuid4())[:8]
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.__dict__, ensure_ascii=False) + "\n")
    
    def stats(self) -> dict:
        """统计错误分布"""
        if not self.path.exists():
            return {"total": 0}
        
        records = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        
        by_type = {}
        by_layer = {}
        for r in records:
            et = r.get("error_type", "unknown")
            by_type[et] = by_type.get(et, 0) + 1
            layer = r.get("layer", "unknown")
            by_layer[layer] = by_layer.get(layer, 0) + 1
        
        return {
            "total": len(records),
            "by_error_type": by_type,
            "by_layer": by_layer,
        }
    
    def export_seeds(self) -> list[dict]:
        """导出种子数据（正确答案，用于 project2 数据飞轮）"""
        if not self.path.exists():
            return []
        seeds = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                seeds.append({
                    "error_id": r.get("error_id", ""),
                    "input": r["input"],
                    "domain": r["domain"],
                    "intent": r.get("intent"),
                    "slots": r.get("slots", {}),
                    "error_stage": r.get("error_stage", "stage2"),
                    "error_type": r.get("error_type", ""),
                })
        return seeds


# ── 测试用例 ──

# 预定义错误 case（来自之前的测试发现）
SEED_ERROR_CASES = [
    # (input, domain, intent, slots, error_type, error_detail, error_stage)
    ("空调多少度", "vehicle", "query_vehicle_status", {"items": "ac_temp"},
     "intent_confusion", "判为climate/ac_control, 该是vehicle/query", "stage2"),
    ("出发前检查", "vehicle", "activate_scene", {"scene_name": "departure_check"},
     "intent_confusion", "判为query_vehicle_status, 该是activate_scene", "stage2"),
    ("打开音乐关闭空调", "multi", None, {},
     "multi_missed", "无逗号/连接词, fast_rule和门控都漏", "stage1"),
    ("导航去最近的加油站", "navigation", "start_navigation", {"destination": "最近的加油站"},
     "intent_confusion", "判为search/search_poi, 该是navigation/start_navigation", "stage2"),
    ("先开空调再导航", "multi", None, {},
     "multi_missed", "先X再Y模式, fast_rule拦截", "stage1"),
]

def run_check(text: str, domain: str, intent: Optional[str], slots: dict,
              error_type: str, error_detail: str, logger: ErrorLogger,
              error_stage: str = "stage2") -> bool:
    """运行单条检测，记录错误"""
    
    record = ErrorRecord(
        input=text,
        domain=domain,
        intent=intent,
        slots=slots,
        error_type=error_type,
        error_detail=error_detail,
        error_stage=error_stage,
    )
    
    gate_ok = _can_use_edge(text, [])
    record.gate_passed = gate_ok
    
    fr = fast_rules_check(text, [])
    if fr:
        record.layer = "fast_rule"
        record.actual_intent = fr.get("intent", "?")
        record.actual_slots = fr.get("extracted_slots", {})
    else:
        result = edge_model_infer(text)
        record.latency_ms = result.latency_ms
        
        if result.is_acceptable:
            record.layer = "edge"
            record.actual_domain = result.domain
            record.actual_intent = result.intent
            record.actual_slots = result.slots
        else:
            record.layer = "cloud"
            record.actual_domain = result.domain
    
    is_error = False
    if domain == "multi":
        is_error = fr is not None
    elif result.is_acceptable if fr is None else True:
        if intent is None:
            is_error = True
        else:
            domain_ok = record.actual_domain == domain
            intent_ok = record.actual_intent == intent
            is_error = not (domain_ok and intent_ok)
    
    if is_error:
        logger.log(record)
        return False
    return True


if __name__ == "__main__":
    logger = ErrorLogger()
    
    # 清空旧日志
    if logger.path.exists():
        logger.path.unlink()
    
    ok = 0
    for case in SEED_ERROR_CASES:
        text, domain, intent, slots, etype, edetail, estage = case
        passed = run_check(text, domain, intent, slots, etype, edetail, logger, estage)
        ok += 1 if passed else 0
        status = "✅" if passed else "❌"
        print(f"{status} \"{case[0]}\" → {case[3]}")
    
    stats = logger.stats()
    print(f"\n{'='*50}")
    print(f"总计: {ok}/{len(SEED_ERROR_CASES)} 通过")
    print(f"错误记录: {stats['total']} 条")
    if stats["by_error_type"]:
        print(f"按类型: {stats['by_error_type']}")
    if stats["by_layer"]:
        print(f"按层: {stats['by_layer']}")
    print(f"\n日志文件: {logger.path}")
    
    if stats["total"] > 0:
        seeds = logger.export_seeds()
        print(f"种子数据: {len(seeds)} 条可扩写")
