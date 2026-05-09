"""
project1_cabin_agent/tests/synth_data.py
Schema-Driven 训练数据合成器

设计原则：
  1. 从 edge_schemas.py 的 intent schema 出发，不依赖错误收集
  2. 模板 × 实体组合 → 程序化批量生成（零 LLM 成本）
  3. Stage1 (input→domain) + Stage2 (input+domain→intent+slots) 分阶段输出
  4. Axolotl/TRL 兼容的 chat 格式
  5. 加 hard negative 防止过拟合

用法:
    python -m project1_cabin_agent.tests.synth_data
    python -m project1_cabin_agent.tests.synth_data --no-negatives  # 不加反例
    python -m project1_cabin_agent.tests.synth_data --llm-enhance 5  # LLM口语化增强(每条→5条)

输出:
    tests/synth_stage1.jsonl  — domain 分类训练数据
    tests/synth_stage2.jsonl  — intent+slot 联合提取训练数据
"""

import json, sys, time, random
from pathlib import Path
from itertools import product

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from project1_cabin_agent.edge_schemas import INTENT_SCHEMAS, DOMAINS, DOMAIN_NAMES

OUT_DIR = Path(__file__).parent
S1_PATH = OUT_DIR / "synth_stage1.jsonl"
S2_PATH = OUT_DIR / "synth_stage2.jsonl"

# ═══════════════════════════════════════════════════
# 口语模板 — 每个 intent 的自然表达模式
# {slot_name} 会被实体值替换
# ═══════════════════════════════════════════════════

TEMPLATES = {

    # ── climate ──
    "ac_control": [
        # 温度
        "调到{temperature}度",
        "温度{temperature}",
        "把空调调到{temperature}度",
        "空调{temperature}度",
        "{temperature}度",
        "调到{temperature}",
        "太热了调到{temperature}",
        "太冷了调到{temperature}",
        "空调打到{temperature}度",
        "帮我调到{temperature}",
        # 模式
        "开{mode}",
        "{mode}模式",
        "切换{mode}",
        "打开{mode}",
        "把空调调成{mode}",
        # 操作
        "空调{action}",
        "把空调{action}",
        "{action}空调",
        "{action}一下空调",
    ],
    "window_control": [
        "{action}{target}",
        "把{target}{action}",
        "{target}{action}一下",
        "{action}一下{target}",
        "帮我把{target}{action}",
        "{target}开到{percent}",
        "{target}关到{percent}",
        "{target}{action}到{percent}",
    ],
    "seat_control": [
        "座椅加热{action}",
        "把座椅加热{action}",
        "座椅通风{action}",
        "座椅加热{heat_level}档",
        "加热调到{heat_level}档",
        "座椅{action}",
        "{action}座椅加热",
    ],
    "light_control": [
        "{action}{target}",
        "把{target}{action}",
        "{action}一下{target}",
        "{target}太{state}了",
        "{target}{action}点",
        "帮我把{target}{action}",
        "{target}调{brightness}",
        "{target}亮度{brightness}",
    ],

    # ── navigation ──
    "start_navigation": [
        "导航到{destination}",
        "去{destination}",
        "导航去{destination}",
        "带我去{destination}",
        "帮我导航到{destination}",
        "到{destination}怎么走",
        "去{destination}的路线",
        "{mode}去{destination}",
        "导航去{destination}走{mode}",
    ],

    # ── media ──
    "media_control": [
        "{action}",
        "音乐{action}",
        "{action}音乐",
        "{action}一下",
        "把音乐{action}",
        "播放{query}",
        "来首{query}",
        "听{query}",
        "放{query}",
        "放一首{query}",
        "我想听{query}",
        "音量调到{volume}",
        "声音{volume}",
        "音量{action_vol}",
        "{action_vol}音量",
    ],

    # ── search ──
    "search_poi": [
        "附近有没有{keyword}",
        "附近有{keyword}吗",
        "帮我找附近的{keyword}",
        "最近的{keyword}",
        "找一下附近的{keyword}",
        "周围的{keyword}",
        "搜一下{keyword}",
        "哪里有{keyword}",
        "查一下{keyword}",
    ],

    # ── vehicle ──
    "query_vehicle_status": [
        "查询{items}",
        "{items}多少",
        "还剩多少{items}",
        "看一下{items}",
        "看看{items}",
        "{items}怎么样",
        "测一下{items}",
        "还有{items}吗",
    ],
    "activate_scene": [
        "{scene_name}",
        "打开{scene_name}",
        "开启{scene_name}",
        "进入{scene_name}",
        "切换到{scene_name}",
        "帮我调到{scene_name}",
        "开启{scene_name}模式",
    ],

    # ── chitchat ──
    "chitchat": [
        "你好",
        "在吗",
        "早上好",
        "晚上好",
        "讲个笑话",
        "今天天气怎么样",
        "现在几点了",
        "今天星期几",
        "你是谁",
        "谢谢",
        "辛苦了",
        "有点无聊",
    ],
}

# ═══════════════════════════════════════════════════
# 实体值 — 槽位可取值
# ═══════════════════════════════════════════════════

ENTITIES = {
    # ac_control
    "temperature": [16, 18, 20, 22, 24, 26, 28, 30],
    "mode":        ["制冷", "制热", "自动", "除湿"],
    "action_ac":   ["打开", "关闭", "调高", "调低"],

    # window_control
    "target_win":  ["车窗", "天窗", "车门"],
    "action_win":  ["打开", "关闭"],
    "percent":     [30, 50, 80, 100],

    # seat_control
    "action_seat": ["打开", "关闭"],
    "heat_level":  [1, 2, 3],

    # light_control
    "target_light": ["灯", "阅读灯", "氛围灯", "车内灯"],
    "action_light": ["开", "关"],
    "state_light":  ["暗", "亮", "太暗", "太亮"],
    "brightness":   [20, 50, 80, 100],

    # navigation
    "destinations": ["天府广场", "春熙路", "太古里", "公司", "家", "成都东站",
                     "双流机场", "宽窄巷子", "锦里", "武侯祠"],
    "nav_modes":    ["最快", "最短", "不走高速", "避开收费"],

    # media
    "action_media": ["播放", "暂停", "下一首", "上一首"],
    "queries":      ["周杰伦", "晴天", "稻香", "七里香", "夜曲", "好久不见",
                     "起风了", "孤勇者", "小苹果", "平凡之路"],
    "action_vol":   ["大一点", "小一点"],
    "volume":       [20, 40, 60, 80],

    # search
    "keywords":     ["加油站", "餐厅", "火锅店", "厕所", "停车场", "川菜馆",
                     "医院", "超市", "加油站", "洗车店", "咖啡店"],

    # vehicle
    "items":        ["油量", "胎压", "电量", "续航", "空调温度", "车速",
                     "总里程", "发动机", "保养时间"],
    "scenes":       ["舒适模式", "休息模式", "出发前检查"],

    # chitchat — 直接就是完整句子，不用替换
}


# ═══════════════════════════════════════════════════
# 实体映射 — 模板里的 {slot} → 实际取值
# ═══════════════════════════════════════════════════

def _get_entities(intent: str) -> dict:
    """返回 {slot_name: [values], ...}"""
    if intent == "ac_control":
        return {"temperature": ENTITIES["temperature"],
                "mode": ENTITIES["mode"],
                "action": ENTITIES["action_ac"]}
    elif intent == "window_control":
        return {"target": ENTITIES["target_win"],
                "action": ENTITIES["action_win"],
                "percent": ENTITIES["percent"]}
    elif intent == "seat_control":
        return {"action": ENTITIES["action_seat"],
                "heat_level": ENTITIES["heat_level"]}
    elif intent == "light_control":
        return {"target": ENTITIES["target_light"],
                "action": ENTITIES["action_light"],
                "state": ENTITIES["state_light"],
                "brightness": ENTITIES["brightness"]}
    elif intent == "start_navigation":
        return {"destination": ENTITIES["destinations"],
                "mode": ENTITIES["nav_modes"]}
    elif intent == "media_control":
        return {"action": ENTITIES["action_media"],
                "query": ENTITIES["queries"],
                "action_vol": ENTITIES["action_vol"],
                "volume": ENTITIES["volume"]}
    elif intent == "search_poi":
        return {"keyword": ENTITIES["keywords"]}
    elif intent == "query_vehicle_status":
        return {"items": ENTITIES["items"]}
    elif intent == "activate_scene":
        return {"scene_name": ENTITIES["scenes"]}
    return {}


def _fill_template(template: str, slots: dict) -> str:
    """用槽位值填充模板，返回自然语句"""
    result = template
    for k, v in slots.items():
        result = result.replace(f"{{{k}}}", str(v))
    return result


def _slots_for_template(template: str, entity_map: dict) -> list[dict]:
    """返回模板所需槽位的所有可能值组合（笛卡尔积）"""
    import re
    needed = re.findall(r"\{(\w+)\}", template)
    if not needed:
        return [{}]

    # 去重 + 按模板出现顺序
    seen = set()
    ordered = []
    for n in needed:
        if n not in seen and n in entity_map:
            ordered.append(n)
            seen.add(n)

    values = [entity_map[n] for n in ordered]
    combos = []
    for combo in product(*values):
        combos.append(dict(zip(ordered, combo)))
    return combos


def _extract_slots(template: str, filled_slots: dict, intent: str) -> dict:
    """从填充后的槽位中提取最终 slots（只保留 schema 定义的）"""
    schemas = INTENT_SCHEMAS
    for domain, intents in schemas.items():
        if intent in intents:
            allowed = set(intents[intent]["slots"].keys())
            return {k: v for k, v in filled_slots.items() if k in allowed}
    return {}


# ═══════════════════════════════════════════════════
# 主生成逻辑
# ═══════════════════════════════════════════════════

def generate(include_negatives: bool = True, seed: int = 42):
    """从 schema + 模板驱动，生成 Stage1 + Stage2 训练数据"""
    random.seed(seed)
    stage1_data = []
    stage2_data = []

    total = 0

    for domain, intents in INTENT_SCHEMAS.items():
        for intent, cfg in intents.items():
            templates = TEMPLATES.get(intent, [])
            entity_map = _get_entities(intent)

            count = 0
            for tpl in templates:
                slot_combos = _slots_for_template(tpl, entity_map)
                # 每个模板最多取 6 个组合，避免爆炸
                if len(slot_combos) > 6:
                    slot_combos = random.sample(slot_combos, 6)

                for slots in slot_combos:
                    text = _fill_template(tpl, slots)
                    final_slots = _extract_slots(tpl, slots, intent)

                    # Stage1: 领域分类
                    stage1_data.append({
                        "messages": [
                            {"role": "system", "content": "你是车载语音助手领域分类模块。只输出一个领域名：climate, navigation, media, search, vehicle, chitchat, unknown。"},
                            {"role": "user", "content": text},
                            {"role": "assistant", "content": domain},
                        ]
                    })

                    # Stage2: intent + slot 联合提取
                    output = json.dumps({"intent": intent, "slots": final_slots}, ensure_ascii=False)
                    stage2_data.append({
                        "messages": [
                            {"role": "system", "content": f"你是车载语音助手意图+槽位提取模块。当前领域: {domain}。输出纯 JSON: {{\"intent\": \"意图名\", \"slots\": {{\"槽位\": 值}}}}"},
                            {"role": "user", "content": text},
                            {"role": "assistant", "content": output},
                        ]
                    })

                    count += 1
                    total += 1

            print(f"  {domain}/{intent}: {count} 条")

    # chitchat
    for text in TEMPLATES["chitchat"]:
        stage1_data.append({
            "messages": [
                {"role": "system", "content": "你是车载语音助手领域分类模块。只输出一个领域名：climate, navigation, media, search, vehicle, chitchat, unknown。"},
                {"role": "user", "content": text},
                {"role": "assistant", "content": "chitchat"},
            ]
        })
        # chitchat 不需要 stage2，不生成
        total += 1

    print(f"  chitchat: {len(TEMPLATES['chitchat'])} 条")

    # ── hard negatives ──
    if include_negatives:
        negatives_added = 0
        negatives = [
            # 不属于任何领域
            ("点个外卖", "unknown"),
            ("给我老婆打电话", "unknown"),
            ("帮我发个微信", "unknown"),
            ("设置提醒", "unknown"),
            ("打开后备箱", "unknown"),  # 当前不支持
            # 模糊/噪声
            ("啊", "unknown"),
            ("哦", "unknown"),
            ("嗯嗯好的", "chitchat"),
            ("12345", "unknown"),
            ("asdfgh", "unknown"),
            # 跨域混淆 — 容易误判的
            ("导航到家顺便开空调", "multi"),
            ("打开音乐关闭车窗", "multi"),
            ("太闷了开窗放首歌", "multi"),
        ]
        for text, domain in negatives:
            stage1_data.append({
                "messages": [
                    {"role": "system", "content": "你是车载语音助手领域分类模块。只输出一个领域名：climate, navigation, media, search, vehicle, chitchat, unknown。"},
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": domain},
                ]
            })
            negatives_added += 1
        print(f"  hard_negatives: {negatives_added} 条")
        total += negatives_added

    # 打乱
    random.shuffle(stage1_data)
    random.shuffle(stage2_data)

    # 写入
    with open(S1_PATH, "w", encoding="utf-8") as f:
        for d in stage1_data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    with open(S2_PATH, "w", encoding="utf-8") as f:
        for d in stage2_data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"\n{'='*50}")
    print(f"✅ 生成完成")
    print(f"  Stage1 (domain分类): {len(stage1_data)} 条 → {S1_PATH}")
    print(f"  Stage2 (intent+slot): {len(stage2_data)} 条 → {S2_PATH}")
    print(f"\n下一步: python -m project1_cabin_agent.tests.synth_data --llm-enhance 5   # LLM口语化增强")
    return len(stage1_data), len(stage2_data)


# ═══════════════════════════════════════════════════
# LLM 口语化增强（可选）
# ═══════════════════════════════════════════════════

ENHANCE_PROMPT = """将下面这条车载语音助手的训练数据扩写成 {n} 条自然口语变体。
每条变体保持领域、意图和槽位值完全不变，只改变表达方式。

【原始输入】: {input}
【领域】: {domain}
【意图】: {intent}
【槽位值（严格不变）】: {slots}

【要求】
1. 生成 {n} 条变体
2. 风格多样: 短/长/口语填充/客套/方言
3. 槽位值一字不改
4. 输出纯 JSON 字符串数组: ["变体1", "变体2", ...]

只输出 JSON 数组，不要任何其他文字。"""


def llm_enhance(n: int = 5):
    """用 LLM 对已生成的训练数据做口语化增强"""
    from shared.utils.llm_factory import get_llm
    from langchain_core.messages import HumanMessage

    if not S1_PATH.exists():
        print("❌ 先运行 python -m project1_cabin_agent.tests.synth_data 生成基础数据")
        return

    # 读入已有数据，提取 (input, domain, intent, slots)
    stage2_raw = []
    with open(S2_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            msgs = d["messages"]
            user = msgs[1]["content"]
            system = msgs[0]["content"]
            assistant = json.loads(msgs[2]["content"])
            # 从 system prompt 提取 domain
            domain = system.split("当前领域: ")[1].split("。")[0] if "当前领域:" in system else "unknown"
            stage2_raw.append({
                "input": user,
                "domain": domain,
                "intent": assistant["intent"],
                "slots": assistant["slots"],
                "original_system": system,
            })

    # 去重 + 采样
    seen = set()
    unique = []
    for r in stage2_raw:
        key = (r["input"], r["intent"])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    # 每条扩写 n 条变体
    llm = get_llm("fast", temperature=0.8, timeout=30)
    new_s1 = []
    new_s2 = []

    # 先读已有
    with open(S1_PATH, encoding="utf-8") as f:
        for line in f:
            new_s1.append(json.loads(line.strip()))

    total = 0
    for i, r in enumerate(unique):
        prompt = ENHANCE_PROMPT.format(
            n=n, input=r["input"], domain=r["domain"],
            intent=r["intent"], slots=json.dumps(r["slots"], ensure_ascii=False),
        )
        try:
            resp = llm.invoke([HumanMessage(content=prompt)])
            text = resp.content.strip()
            # 提取 JSON 数组
            if "```" in text:
                text = text.split("```")[1]
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1:
                variants = json.loads(text[start:end+1])
                for v in variants:
                    if not isinstance(v, str) or len(v) < 2:
                        continue
                    # Stage1
                    new_s1.append({
                        "messages": [
                            {"role": "system", "content": "你是车载语音助手领域分类模块。只输出一个领域名：climate, navigation, media, search, vehicle, chitchat, unknown。"},
                            {"role": "user", "content": v},
                            {"role": "assistant", "content": r["domain"]},
                        ]
                    })
                    # Stage2
                    new_s2.append({
                        "messages": [
                            {"role": "system", "content": r["original_system"]},
                            {"role": "user", "content": v},
                            {"role": "assistant", "content": json.dumps({"intent": r["intent"], "slots": r["slots"]}, ensure_ascii=False)},
                        ]
                    })
                    total += 1
            print(f"  [{i+1}/{len(unique)}] \"{r['input'][:20]}\" → +{len(variants) if 'variants' in dir() else 0} 条")
        except Exception as e:
            print(f"  [{i+1}/{len(unique)}] \"{r['input'][:20]}\" ❌ {e}")

        time.sleep(0.5)

    # 打乱 + 覆写
    random.shuffle(new_s1)
    random.shuffle(new_s2)

    with open(S1_PATH, "w", encoding="utf-8") as f:
        for d in new_s1:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    with open(S2_PATH, "w", encoding="utf-8") as f:
        for d in new_s2:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"\n✅ LLM增强完成: Stage1={len(new_s1)}, Stage2={len(new_s2)} (+{total} 条)")


# ═══════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--no-negatives", action="store_true", help="不生成 hard negative 反例")
    p.add_argument("--llm-enhance", type=int, default=0, help="LLM口语化增强, 每条→N条变体")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    if args.llm_enhance > 0:
        llm_enhance(args.llm_enhance)
    else:
        generate(include_negatives=not args.no_negatives, seed=args.seed)
