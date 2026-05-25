"""
project1_cabin_agent/tests/eval_harness.py
持续集成评估框架 — 跑测试 + 基线对比 + 退化告警

用法:
    python project1_cabin_agent/tests/eval_harness.py          # 跑完整评估
    python project1_cabin_agent/tests/eval_harness.py --quick  # 快速(50条)
    python project1_cabin_agent/tests/eval_harness.py --compare # 只看对比
"""

import os, sys, json, time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("EDGE_ENABLED", "true")

from project1_cabin_agent.edge_model import edge_model_infer
from project1_cabin_agent.nodes.pre_rules import fast_rules_check
from project1_cabin_agent.nodes.intent import _can_use_edge
from project1_cabin_agent.tests.error_collector import ErrorLogger, ErrorRecord
from project1_cabin_agent.tests.data_pipeline import run_pipeline

# ── 期望槽位映射（输入文本 → 正确槽位）──
EXPECTED_SLOTS = {
    "调到26度": {"temperature": 26},
    "空调开到18度": {"temperature": 18},
    "温度调到22": {"temperature": 22},
    "开窗": {"target": "window", "action": "open"},
    "关窗": {"target": "window", "action": "close"},
    "关天窗": {"target": "sunroof", "action": "close"},
    "灯太暗了": {"action": "adjust"},
    "开灯": {"action": "on"},
    "关灯": {"action": "off"},
    "开阅读灯": {"target": "reading", "action": "on"},
    "阅读灯打开": {"target": "reading", "action": "on"},
    "打开座椅加热": {"action": "heat_on"},
    "座椅加热调到3档": {"action": "heat_on", "heat_level": 3},
    "关座椅通风": {"action": "ventilate_off"},
    "导航到天府广场": {"destination": "天府广场"},
    "导航去成都避开高速": {"destination": "成都", "mode": "avoid_highway"},
    "导航去最近的加油站": {"destination": "最近的加油站"},
    "去最近的加油站": {"destination": "最近的加油站"},
    "播放周杰伦": {"action": "play", "query": "周杰伦"},
    "声音大一点": {"action": "volume_up"},
    "音量调到80": {"action": "set_volume", "volume": 80},
    "下一首": {"action": "next"},
    "附近有没有加油站": {"keyword": "加油站"},
    "帮我找下附近的医院": {"keyword": "医院"},
    "还有多少油": {"items": "fuel"},
    "胎压怎么样": {"items": "tire"},
    "舒适模式": {"scene_name": "comfortable_driving"},
    "睡眠模式": {"scene_name": "sleep_mode"},
    "空调多少度": {"items": "ac_temp"},
    "出发前检查": {"scene_name": "departure_check"},
}

# ── 测试用例（分层管理）──

GOLDEN_SET = [
    # 核心高频 — 绝对不能退化
    ("调到26度","climate","ac_control"),("关空调","climate","ac_control"),
    ("开窗","climate","window_control"),("灯太暗了","climate","light_control"),
    ("导航去公司","map","navigate"),("放首歌","media","media_control"),
    ("附近有没有加油站","map","search_poi"),("测下胎压","vehicle","query_vehicle_status"),
    ("早上好","chitchat",None),("打开音乐关闭空调","multi",None),
    ("最远的","needs_context",None),
]

EXTENDED_SET = [
    ("太热了","climate","ac_control"),("冷死了","climate","ac_control"),
    ("温度调到22","climate","ac_control"),("风速调到3档","climate","ac_control"),
    ("关窗","climate","window_control"),("打开车窗","climate","window_control"),
    ("天窗打开","climate","window_control"),("开灯","climate","light_control"),
    ("关灯","climate","light_control"),("阅读灯打开","climate","light_control"),
    ("打开座椅加热","climate","seat_control"),("座椅加热关掉","climate","seat_control"),
    ("座椅通风","climate","seat_control"),("呃开一下空调","climate","ac_control"),
    ("麻烦帮我把空调关了","climate","ac_control"),("热得不行了","climate","ac_control"),
    ("导航到天府广场","map","navigate"),("去春熙路","map","navigate"),
    ("导航去最近的加油站","map","navigate"),
    ("导航去成都春熙路太古里避开高速","map","navigate"),
    ("播放周杰伦","media","media_control"),("下一首","media","media_control"),
    ("暂停","media","media_control"),("声音大一点","media","media_control"),
    ("音量调到80","media","media_control"),("来点音乐","media","media_control"),
    ("我想听周杰伦的歌","media","media_control"),("麻烦帮我放首歌呗","media","media_control"),
    ("附近有没有川菜馆","map","search_poi"),("帮我找下附近的医院","map","search_poi"),
    ("附近的火锅店","map","search_poi"),("还有多少油","vehicle","query_vehicle_status"),
    ("电量还剩多少","vehicle","query_vehicle_status"),("舒适模式","vehicle","activate_scene"),
    ("休息模式","vehicle","activate_scene"),("出发前检查","vehicle","activate_scene"),
    ("空调多少度","vehicle","query_vehicle_status"),("该保养了吗","vehicle","query_vehicle_status"),
    ("讲个笑话","chitchat",None),("今天星期几","chitchat",None),
    ("今天天气怎么样","map","weather"),("几点了","chitchat",None),
    ("开空调、关窗","multi",None),("打开空调 然后放歌","multi",None),
    ("第二个","needs_context",None),("还有多远","needs_context",None),
    ("最近的有多远","needs_context",None),
    # ── 新增：跨域多意图（验证 cross_domain_flag）──
    ("开窗放音乐","multi",None),
    ("帮我打开空调并播放音乐","multi",None),
    ("先找加油站再导航过去","multi",None),
    ("导航到天府广场然后放点音乐","multi",None),
    ("附近有便利店吗帮我调低温度","multi",None),
    ("帮我加油顺便开空调","multi",None),
    # ── 新增：高频补充 ──
    ("打开空调","climate","ac_control"),
    ("空调开到18度","climate","ac_control"),
    ("关天窗","climate","window_control"),
    ("开阅读灯","climate","light_control"),
    ("座椅加热调到3档","climate","seat_control"),
    ("关座椅通风","climate","seat_control"),
    ("去最近的加油站","map","navigate"),
    ("导航去成都避开高速","map","navigate"),
    ("音量调小点","media","media_control"),
    ("切歌","media","media_control"),
    ("我想听周杰伦","media","media_control"),
    ("有没有附近的火锅店","map","search_poi"),
    ("胎压怎么样","vehicle","query_vehicle_status"),
    ("睡眠模式","vehicle","activate_scene"),
    # ── 新增：白名单边界（验证P2）──
    ("空调暖风","climate","ac_control"),
    ("车窗全开","climate","window_control"),
    ("灯调亮点","climate","light_control"),
    ("座椅加热开","climate","seat_control"),
    ("放周杰伦","media","media_control"),
    ("搜一下附近的加油站","map","search_poi"),
    ("车还有多少电","vehicle","query_vehicle_status"),
    ("运动模式","vehicle","activate_scene"),
    # ── 新增：ASR噪声/口误（验证端侧鲁棒性）──
    ("帮我把空挑关掉","climate","ac_control"),          # 空调→空挑
    ("去到春熙路吧","map","navigate"),    # 去→去到
    ("我想停歌","media","media_control"),               # 听歌→停歌(ASR)
    ("把那啥温度调低一点","climate","ac_control"),      # 语气词+隐含
    ("导一下航到天府广场","map","navigate"), # 口语拆分
    ("太冷了 那个 调到26度","climate","ac_control"),     # 口吃/修正
    # ── 新增：极口语化（验证3B模型对口语的理解）──
    ("热成狗了","climate","ac_control"),
    ("冻死我了","climate","ac_control"),
    ("闷得喘不过气","climate","ac_control"),
    ("亮瞎了","climate","light_control"),
    ("啥也看不见","climate","light_control"),
    ("耳朵要聋了","media","media_control"),              # → volume_down
    ("吵死啦","media","media_control"),                  # → volume_down
    ("来点带劲的音乐","media","media_control"),
    ("这什么歌啊换掉","media","media_control"),
    ("饿得不行了","map","search_poi"),               # → 搜餐厅
    ("想喝奶茶","map","search_poi"),
    ("困了找个地方睡觉","map","search_poi"),         # → 搜酒店
    # ── 新增：域边界模糊（验证Stage1区分能力）──
    ("打开暖风","climate","ac_control"),                # 暖风≠vehicle
    ("车里好暗","climate","light_control"),              # 暗→灯光,非chitchat
    ("后背好热","climate","seat_control"),              # 座椅通风,非ac
    ("挡风玻璃起雾了","climate","ac_control"),      # 除雾=空调制热/制冷
    ("前面堵不堵","map","navigate"),     # 路况→导航域
    ("换一条路","map","navigate"),       # 重规划→导航
    ("现在在哪儿","map","map_query"),     # 位置查询→map_query
    ("离机场还有多远","map","navigate"), # 导航进度
    ("油灯亮了","vehicle","query_vehicle_status"),      # 油灯=油量告警
    ("这个按钮干嘛的","chitchat",None),                 # 边界:不是车控
    ("你好小Q","chitchat",None),                        # 唤醒词风格
    # ── 新增：否定/修正（验证Cancel和意图切换）──
    ("不是 我是说开窗","climate","window_control"),     # 修正
    ("不对 关掉音乐","media","media_control"),           # 修正
    ("别开空调了 开窗吧","multi",None),    # 否定AC+开窗 = 多意图
    ("算了不去了","chitchat",None),                     # 取消→chitchat
    # ── 新增：车载特有场景 ──
    ("后排说冷","climate","ac_control"),
    ("副驾太热","climate","ac_control"),
    ("孩子睡着了 小声点","media","media_control"),      # → volume_down
    ("路上还有多久","map","navigate"),   # ETA查询
    ("前方有摄像头吗","map","search_poi"),           # 电子眼→POI
    ("帮我记一下这个位置","map","navigate"), # 收藏位置
    ("还剩多少公里","map","map_query"),   # 距离查询→map_query
]

BOUNDARY_SET = [
    ("阿巴阿巴","unknown",None),("asdfghjkl","unknown",None),
    ("12345","unknown",None),("！！！","unknown",None),
    ("嗯","chitchat",None),("开","unknown",None),
]


# ── 评估核心 ──

def run_suite(cases: list, logger: ErrorLogger = None) -> dict:
    """运行测试套件，返回指标"""
    stats = {"total": 0, "correct": 0, "fast_rule_hit": 0, "edge_hit": 0, "cloud_fallback": 0,
             "errors": [], "latencies": [], "by_domain": {}}
    t0 = time.monotonic()

    for text, exp_domain, exp_intent in cases:
        stats["total"] += 1
        domain_key = exp_domain
        stats["by_domain"].setdefault(domain_key, {"total": 0, "correct": 0})

        if exp_domain == "multi":
            fr = fast_rules_check(text, [])
            # cross_domain_flag 或 None 都算正确（放行云端）
            ok = (fr is None) or (isinstance(fr, dict) and fr.get("_cross_domain_flag"))
            if ok: stats["cloud_fallback"] += 1
        elif exp_domain == "needs_context":
            ok = not _can_use_edge(text, [])
            if ok: stats["cloud_fallback"] += 1
        elif exp_domain == "unknown":
            r = edge_model_infer(text)
            stats["latencies"].append(r.latency_ms)
            ok = not r.is_acceptable
            if ok: stats["cloud_fallback"] += 1
        elif exp_intent is None:
            r = edge_model_infer(text)
            stats["latencies"].append(r.latency_ms)
            ok = r.domain == exp_domain
            if r.is_acceptable: stats["edge_hit"] += 1
            else: stats["cloud_fallback"] += 1
        else:
            fr = fast_rules_check(text, [])
            # 区分"短路命中"和"信号flag"：flag dict(no intent)不算 FastRules hit
            if fr and fr.get("intent") and not fr.get("_cross_domain_flag") and not fr.get("_oos_flag"):
                ok = fr.get("intent") == exp_intent
                if ok: stats["fast_rule_hit"] += 1
                stats["latencies"].append(0)
            else:
                r = edge_model_infer(text)
                stats["latencies"].append(r.latency_ms)
                if r.is_acceptable:
                    ok = r.intent == exp_intent
                    if ok: stats["edge_hit"] += 1
                else:
                    ok = True  # 放行云端不算错
                    stats["cloud_fallback"] += 1

        if ok:
            stats["correct"] += 1
            stats["by_domain"][domain_key]["correct"] += 1
        else:
            stats["errors"].append(text)
            if logger:
                rec = ErrorRecord(
                    input=text, domain=exp_domain, intent=exp_intent,
                    slots=EXPECTED_SLOTS.get(text, {}),  # ← 带槽位
                    error_type="intent_confusion" if exp_intent else "domain_miss",
                    error_stage="stage2" if exp_intent else "stage1",
                    error_detail=f"expected {exp_domain}/{exp_intent}")
                logger.log(rec)

        stats["by_domain"][domain_key]["total"] += 1

    stats["accuracy"] = stats["correct"] / stats["total"] if stats["total"] else 0
    stats["avg_latency_ms"] = sum(stats["latencies"]) / len(stats["latencies"]) if stats["latencies"] else 0
    stats["fast_rule_rate"] = stats["fast_rule_hit"] / stats["total"] if stats["total"] else 0
    stats["edge_hit_rate"] = stats["edge_hit"] / stats["total"] if stats["total"] else 0
    stats["cloud_fallback_rate"] = stats["cloud_fallback"] / stats["total"] if stats["total"] else 0
    stats["elapsed_s"] = time.monotonic() - t0
    stats["timestamp"] = datetime.now().isoformat()

    return stats


# ── 基线管理 ──

BASELINE_PATH = ROOT / "project1_cabin_agent" / "tests" / "eval_baseline.json"


def load_baseline() -> dict | None:
    """加载上次基线"""
    if BASELINE_PATH.exists():
        with open(BASELINE_PATH) as f:
            return json.load(f)
    return None


def save_baseline(stats: dict):
    """保存当前结果为基线"""
    baseline = {
        "accuracy": stats["accuracy"],
        "fast_rule_rate": stats["fast_rule_rate"],
        "edge_hit_rate": stats["edge_hit_rate"],
        "cloud_fallback_rate": stats["cloud_fallback_rate"],
        "avg_latency_ms": stats["avg_latency_ms"],
        "total_cases": stats["total"],
        "errors": stats.get("errors", []),
        "by_domain": stats.get("by_domain", {}),
        "timestamp": stats["timestamp"],
    }
    with open(BASELINE_PATH, "w") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2)


def compare_baseline(current: dict, baseline: dict) -> list[str]:
    """对比当前和基线，返回退化告警"""
    alerts = []
    metrics = [
        ("accuracy", "准确率", 0.02, "higher"),
        ("fast_rule_rate", "fast_rule命中率", 0.05, "higher"),
        ("edge_hit_rate", "edge命中率", 0.05, "higher"),
        ("avg_latency_ms", "平均延迟", 50, "lower"),
    ]
    for key, label, threshold, direction in metrics:
        delta = current[key] - baseline[key]
        pct_str = f"{delta:+.1%}" if key.endswith("_rate") else f"{delta:+.0f}ms" if "latency" in key else f"{delta:+.2f}"
        
        if direction == "higher" and delta < -threshold:
            alerts.append(f"⚠️ {label}: {baseline[key]:.3f} → {current[key]:.3f} ({pct_str}) 退化超过阈值")
        elif direction == "lower" and delta > threshold:
            alerts.append(f"⚠️ {label}: {baseline[key]:.0f} → {current[key]:.0f} ({pct_str}) 退化超过阈值")
        elif delta < 0 and direction == "lower":
            pass  # 降延迟是好事
        elif delta >= 0:
            pass  # 提升是好事
    
    # 检查是否有新的错误 case（上次没错这次错了）
    new_errors = set(current.get("errors", [])) - set(baseline.get("errors", []))
    if new_errors:
        alerts.append(f"🔴 新增错误 {len(new_errors)} 条: {list(new_errors)[:5]}")
    
    return alerts


# ── 打印报告 ──

def print_report(stats: dict, baseline: dict = None):
    """打印格式化报告"""
    print(f"\n{'='*60}")
    print(f"📊 评估报告  {stats['timestamp'][:19]}")
    print(f"{'='*60}")
    print(f"  用例数:     {stats['total']}")
    print(f"  准确率:     {stats['accuracy']:.1%}")
    print(f"  平均延迟:   {stats['avg_latency_ms']:.0f}ms")
    print(f"  fast_rule:  {stats['fast_rule_rate']:.1%}")
    print(f"  edge:       {stats['edge_hit_rate']:.1%}")
    print(f"  cloud:      {stats['cloud_fallback_rate']:.1%}")
    print(f"  耗时:       {stats['elapsed_s']:.1f}s")
    
    print(f"\n  各 domain:")
    for domain, d in sorted(stats.get("by_domain", {}).items()):
        acc = d["correct"] / d["total"] if d["total"] else 0
        bar = "█" * int(acc * 20) + "░" * (20 - int(acc * 20))
        print(f"    {domain:12s} {bar} {acc:.0%} ({d['correct']}/{d['total']})")
    
    if baseline:
        print(f"\n  ── 基线对比 (上次: {baseline.get('timestamp','?')[:19]}) ──")
        for key, label in [("accuracy","准确率"),("fast_rule_rate","fast_rule命中率"),
                           ("edge_hit_rate","edge命中率"),("avg_latency_ms","平均延迟")]:
            curr = stats[key]
            prev = baseline.get(key, curr)
            if "rate" in key:
                delta = curr - prev
                print(f"    {label:14s} {prev:.1%} → {curr:.1%}  ({delta:+.1%})")
            elif "latency" in key:
                delta = curr - prev
                print(f"    {label:14s} {prev:.0f}ms → {curr:.0f}ms  ({delta:+.0f}ms)")
        
        alerts = compare_baseline(stats, baseline)
        if alerts:
            print(f"\n  🚨 退化告警:")
            for a in alerts:
                print(f"    {a}")
        else:
            print(f"  ✅ 无退化")
    
    errors = stats.get("errors", [])
    if errors:
        print(f"\n  错误 case ({len(errors)}):")
        for e in errors[:10]:
            print(f"    ❌ {e}")
        if len(errors) > 10:
            print(f"    ... 共 {len(errors)} 条")


# ── 入口 ──

def main(quick: bool = False, compare_only: bool = False):
    if compare_only:
        current = load_baseline()
        if current is None:
            print("⚠️ 无基线数据，先跑一次评估")
            return
        print_report(current, None)
        return
    
    # 选择用例
    if quick:
        cases = GOLDEN_SET + BOUNDARY_SET[:3]
    else:
        cases = GOLDEN_SET + EXTENDED_SET + BOUNDARY_SET
    
    logger = ErrorLogger()
    if logger.path.exists():
        logger.path.unlink()
    
    stats = run_suite(cases, logger)
    baseline = load_baseline()
    
    print_report(stats, baseline)
    
    # 保存基线
    save_baseline(stats)
    print(f"\n基线已保存: {BASELINE_PATH}")
    
    # 如果有错误，跑数据管道
    err_count = logger.stats().get("total", 0)
    if err_count > 0:
        print(f"\n发现 {err_count} 条错误，跑数据管道...")
        run_pipeline()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--quick", action="store_true")
    p.add_argument("--compare", action="store_true")
    args = p.parse_args()
    main(quick=args.quick, compare_only=args.compare)
