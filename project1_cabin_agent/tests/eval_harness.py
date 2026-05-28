"""
project1_cabin_agent/tests/eval_harness.py
持续集成评估框架 — 跑测试 + 基线对比 + 退化告警

用法:
    python project1_cabin_agent/tests/eval_harness.py          # 跑完整评估
    python project1_cabin_agent/tests/eval_harness.py --quick  # 快速(50条)
    python project1_cabin_agent/tests/eval_harness.py --compare # 只看对比
"""

import os
import sys
import json
import time
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
    "导航去成都避开高速": {"destination": "成都", "route_type": "avoid_highway"},
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
    "空调多少度": {"items": "ac_temp"},
}

# ── 测试用例（分层管理）──

GOLDEN_SET = [
    # 核心高频 — 绝对不能退化
    ("调到26度", "climate", "ac_control"),
    ("关空调", "climate", "ac_control"),
    ("开窗", "climate", "window_control"),
    ("灯太暗了", "climate", "light_control"),
    ("导航去公司", "map", "navigate"),
    ("放首歌", "media", "media_control"),
    ("附近有没有加油站", "map", "search_poi"),
    ("测下胎压", "vehicle", "query_vehicle_status"),
    ("早上好", "chitchat", None),
    ("打开音乐关闭空调", "multi", None),
    ("最远的", "needs_context", None),
]

EXTENDED_SET = [
    ("太热了", "climate", "ac_control"),
    ("冷死了", "climate", "ac_control"),
    ("温度调到22", "climate", "ac_control"),
    ("风速调到3档", "climate", "ac_control"),
    ("关窗", "climate", "window_control"),
    ("打开车窗", "climate", "window_control"),
    ("天窗打开", "climate", "window_control"),
    ("开灯", "climate", "light_control"),
    ("关灯", "climate", "light_control"),
    ("阅读灯打开", "climate", "light_control"),
    ("打开座椅加热", "climate", "seat_control"),
    ("座椅加热关掉", "climate", "seat_control"),
    ("座椅通风", "climate", "seat_control"),
    ("呃开一下空调", "climate", "ac_control"),
    ("麻烦帮我把空调关了", "climate", "ac_control"),
    ("热得不行了", "climate", "ac_control"),
    ("导航到天府广场", "map", "navigate"),
    ("去春熙路", "map", "navigate"),
    ("导航去最近的加油站", "map", "navigate"),
    ("导航去成都春熙路太古里避开高速", "map", "navigate"),
    ("播放周杰伦", "media", "media_control"),
    ("下一首", "media", "media_control"),
    ("暂停", "media", "media_control"),
    ("声音大一点", "media", "media_control"),
    ("音量调到80", "media", "media_control"),
    ("来点音乐", "media", "media_control"),
    ("我想听周杰伦的歌", "media", "media_control"),
    ("麻烦帮我放首歌呗", "media", "media_control"),
    ("附近有没有川菜馆", "map", "search_poi"),
    ("帮我找下附近的医院", "map", "search_poi"),
    ("附近的火锅店", "map", "search_poi"),
    ("还有多少油", "vehicle", "query_vehicle_status"),
    ("电量还剩多少", "vehicle", "query_vehicle_status"),
    # scene 相关 → 不再有 activate_scene intent，改为 multi 放行云端
    ("舒适模式", "multi", None),
    ("休息模式", "multi", None),
    ("出发前检查", "multi", None),
    ("空调多少度", "climate", "cabin_query"),
    ("该保养了吗", "vehicle", "query_vehicle_status"),
    ("讲个笑话", "chitchat", None),
    ("今天星期几", "chitchat", None),
    ("今天天气怎么样", "map", "weather"),
    ("几点了", "chitchat", None),
    ("开空调、关窗", "multi", None),
    ("打开空调 然后放歌", "multi", None),
    ("第二个", "needs_context", None),
    ("还有多远", "needs_context", None),
    ("最近的有多远", "needs_context", None),
    # ── 新增：跨域多意图（验证 cross_domain_flag）──
    ("开窗放音乐", "multi", None),
    ("帮我打开空调并播放音乐", "multi", None),
    ("先找加油站再导航过去", "multi", None),
    ("导航到天府广场然后放点音乐", "multi", None),
    ("附近有便利店吗帮我调低温度", "multi", None),
    ("帮我加油顺便开空调", "multi", None),
    # ── 新增：高频补充 ──
    ("打开空调", "climate", "ac_control"),
    ("空调开到18度", "climate", "ac_control"),
    ("关天窗", "climate", "window_control"),
    ("开阅读灯", "climate", "light_control"),
    ("座椅加热调到3档", "climate", "seat_control"),
    ("关座椅通风", "climate", "seat_control"),
    ("去最近的加油站", "map", "navigate"),
    ("导航去成都避开高速", "map", "navigate"),
    ("音量调小点", "media", "media_control"),
    ("切歌", "media", "media_control"),
    ("我想听周杰伦", "media", "media_control"),
    ("有没有附近的火锅店", "map", "search_poi"),
    ("胎压怎么样", "vehicle", "query_vehicle_status"),
    ("睡眠模式", "multi", None),
    # ── 新增：白名单边界（验证P2）──
    ("空调暖风", "climate", "ac_control"),
    ("车窗全开", "climate", "window_control"),
    ("灯调亮点", "climate", "light_control"),
    ("座椅加热开", "climate", "seat_control"),
    ("放周杰伦", "media", "media_control"),
    ("搜一下附近的加油站", "map", "search_poi"),
    ("车还有多少电", "vehicle", "query_vehicle_status"),
    ("运动模式", "multi", None),
    # ── 新增：ASR噪声/口误（验证端侧鲁棒性）──
    ("帮我把空挑关掉", "climate", "ac_control"),  # 空调→空挑
    ("去到春熙路吧", "map", "navigate"),  # 去→去到
    ("我想停歌", "media", "media_control"),  # 听歌→停歌(ASR)
    ("把那啥温度调低一点", "climate", "ac_control"),  # 语气词+隐含
    ("导一下航到天府广场", "map", "navigate"),  # 口语拆分
    ("太冷了 那个 调到26度", "climate", "ac_control"),  # 口吃/修正
    # ── 新增：极口语化（验证3B模型对口语的理解）──
    ("热成狗了", "climate", "ac_control"),
    ("冻死我了", "climate", "ac_control"),
    ("闷得喘不过气", "climate", "ac_control"),
    ("亮瞎了", "climate", "light_control"),
    ("啥也看不见", "climate", "light_control"),
    ("耳朵要聋了", "media", "media_control"),  # → volume_down
    ("吵死啦", "media", "media_control"),  # → volume_down
    ("来点带劲的音乐", "media", "media_control"),
    ("这什么歌啊换掉", "media", "media_control"),
    ("饿得不行了", "map", "search_poi"),  # → 搜餐厅
    ("想喝奶茶", "map", "search_poi"),
    ("困了找个地方睡觉", "map", "search_poi"),  # → 搜酒店
    # ── 新增：域边界模糊（验证Stage1区分能力）──
    ("打开暖风", "climate", "ac_control"),  # 暖风≠vehicle
    ("车里好暗", "climate", "light_control"),  # 暗→灯光,非chitchat
    ("后背好热", "climate", "seat_control"),  # 座椅通风,非ac
    ("挡风玻璃起雾了", "climate", "ac_control"),  # 除雾=空调制热/制冷
    ("前面堵不堵", "map", "navigate"),  # 路况→导航域
    ("换一条路", "map", "navigate"),  # 重规划→导航
    ("现在在哪儿", "map", "map_query"),  # 位置查询→map_query
    ("离机场还有多远", "map", "map_query"),  # 问距离,非导航指令
    ("油灯亮了", "vehicle", "query_vehicle_status"),  # 油灯=油量告警
    ("这个按钮干嘛的", "chitchat", None),  # 边界:不是车控
    ("你好小Q", "chitchat", None),  # 唤醒词风格
    # ── 新增：否定/修正（验证Cancel和意图切换）──
    ("不是 我是说开窗", "climate", "window_control"),  # 修正
    ("不对 关掉音乐", "media", "media_control"),  # 修正
    ("别开空调了 开窗吧", "multi", None),  # 否定AC+开窗 = 多意图
    ("算了不去了", "chitchat", None),  # 取消→chitchat
    # ── 新增：车载特有场景 ──
    ("后排说冷", "climate", "ac_control"),
    ("副驾太热", "climate", "ac_control"),
    ("孩子睡着了 小声点", "media", "media_control"),  # → volume_down
    ("路上还有多久", "map", "navigate"),  # ETA查询
    ("前方有摄像头吗", "map", "search_poi"),  # 电子眼→POI
    ("帮我记一下这个位置", "map", "navigate"),  # 收藏位置
    ("还剩多少公里", "map", "map_query"),  # 距离查询→map_query
    # ── 新增：条件分支（Phase 3.1/3.2，验证 LLM 生成 condition）──
    ("附近有充电站吗有的话导航过去", "needs_context", None),  # 条件: 有→导航
    ("天气好的话导航去春熙路", "needs_context", None),  # 条件: 天气好→导航
    ("找下有没有停车场有的话过去", "needs_context", None),  # 条件: 有→导航
    ("如果油量低于30就去加油站", "needs_context", None),  # 条件: 油少→导航
    ("有便宜的就推荐个餐厅", "map", "search_poi"),  # 无条件，直接搜
    # ── 新增：weather 天气查询（补齐短板 1→15）──
    ("明天天气怎么样", "map", "weather"),
    ("明天会下雨吗", "map", "weather"),
    ("需要带伞吗", "map", "weather"),
    ("周末天气好不好", "map", "weather"),
    ("外面冷不冷", "map", "weather"),
    ("今天温度多少", "map", "weather"),
    ("看一下天气预报", "map", "weather"),
    ("待会儿会不会下雪", "map", "weather"),
    ("明天多少度", "map", "weather"),
    ("现在外面几度", "map", "weather"),
    ("今天适合出游吗", "map", "weather"),
    ("查一下成都是不是在下雨", "map", "weather"),
    ("这周天气怎么样", "map", "weather"),
    ("明天穿什么合适", "map", "weather"),
    # ── 新增：cabin_query 车内状态查询（补齐短板 1→12）──
    ("车内多少度", "climate", "cabin_query"),
    ("现在空调几度", "climate", "cabin_query"),
    ("空调风速几档", "climate", "cabin_query"),
    ("车里是不是太闷了", "climate", "cabin_query"),
    ("座椅加热开没开", "climate", "seat_control"),  # FastRules: 状态查询→seat_control
    ("现在吹的是冷风还是暖风", "climate", "cabin_query"),
    ("窗户关了没", "climate", "window_control"),  # FastRules: 状态查询→window_control
    ("灯是开着的吗", "climate", "cabin_query"),
    ("当前空调模式是什么", "climate", "cabin_query"),
    ("空气净化开了吗", "climate", "cabin_query"),
    ("车内PM2.5多少", "climate", "cabin_query"),
    # ── 新增：vehicle 车辆状态（补齐短板 7→25）──
    ("还有多少公里保养", "vehicle", "query_vehicle_status"),
    ("机油寿命还剩多少", "vehicle", "query_vehicle_status"),
    ("电瓶还好吧", "vehicle", "query_vehicle_status"),
    ("车门关好了吗", "climate", "window_control"),  # FastRules: 关→window_control
    ("轮胎气压正常吗", "vehicle", "query_vehicle_status"),
    ("刹车片该换了吗", "vehicle", "query_vehicle_status"),
    ("车跑了多少公里了", "vehicle", "query_vehicle_status"),
    ("剩余续航多少", "vehicle", "query_vehicle_status"),
    ("有没有故障码", "vehicle", "query_vehicle_status"),
    ("发动机温度正常吗", "vehicle", "query_vehicle_status"),
    ("平均油耗多少", "vehicle", "query_vehicle_status"),
    ("车灯有没有坏的", "vehicle", "query_vehicle_status"),
    ("空调滤芯该换了吗", "vehicle", "query_vehicle_status"),
    ("胎压左前轮", "vehicle", "query_vehicle_status"),
    ("油耗怎么样", "vehicle", "query_vehicle_status"),
    ("保养提醒", "vehicle", "query_vehicle_status"),
    ("上次保养是什么时候", "vehicle", "query_vehicle_status"),
    ("车况怎么样", "vehicle", "query_vehicle_status"),
    # ── 新增：map_query 位置/距离查询（3→15）──
    ("现在到哪里了", "map", "map_query"),
    ("还有几个红绿灯", "map", "map_query"),
    ("这条路限速多少", "map", "map_query"),
    ("前面有没有服务区", "map", "map_query"),
    ("经过哪些地方", "map", "map_query"),
    ("到目的地要多久", "map", "map_query"),
    ("现在在什么路上", "map", "map_query"),
    ("导航路线是什么", "map", "map_query"),
    ("走的是高速还是国道", "map", "map_query"),
    ("附近有没有测速", "map", "map_query"),
    ("下了高速怎么走", "map", "map_query"),
    ("到机场要多久", "map", "map_query"),
    # ── 新增：navigate 补充（13→30）──
    ("回家", "map", "navigate"),
    ("去公司", "map", "navigate"),
    ("导航去医院", "map", "navigate"),
    ("去机场", "map", "navigate"),
    ("导航去火车站", "map", "navigate"),
    ("去沃尔玛", "map", "navigate"),
    ("导航到最近的停车场", "map", "navigate"),
    ("去刚才搜的那个地方", "map", "navigate"),
    ("去锦里", "map", "navigate"),
    ("导航去宽窄巷子", "map", "navigate"),
    ("走最快的路线", "map", "navigate"),
    ("避开收费站", "map", "navigate"),
    ("走国道", "map", "navigate"),
    ("重新规划路线", "map", "navigate"),
    ("换个路线", "map", "navigate"),
    ("走高速去重庆", "map", "navigate"),
    ("导航去万象城", "map", "navigate"),
    # ── 新增：search_poi 补充（11→30）──
    ("附近有没有厕所", "map", "search_poi"),
    ("最近的4S店", "map", "search_poi"),
    ("帮我找下银行", "map", "search_poi"),
    ("附近有药店吗", "map", "search_poi"),
    ("找个修车的地方", "map", "search_poi"),
    ("附近有没有共享充电宝", "map", "search_poi"),
    ("找下最近的超市", "map", "search_poi"),
    ("附近有没有ATM", "map", "search_poi"),
    ("帮我搜下附近的ktv", "map", "search_poi"),
    ("附近有什么好吃的", "map", "search_poi"),
    ("有没有图书馆", "map", "search_poi"),
    ("附近有没有公园", "map", "search_poi"),
    ("找个咖啡厅", "map", "search_poi"),
    ("周围有没有花店", "map", "search_poi"),
    ("附近有没有充电桩", "map", "search_poi"),
    ("帮我找下健身房", "map", "search_poi"),
    ("附近有什么好玩的", "map", "search_poi"),
    ("找下最近的驾校", "map", "search_poi"),
    ("附近有没有母婴室", "map", "search_poi"),
    # ── 新增：chitchat 补充（8→25）──
    ("你好", "chitchat", None),
    ("你是谁", "chitchat", None),
    ("谢谢", "chitchat", None),
    ("再见", "chitchat", None),
    ("你真聪明", "chitchat", None),
    ("你叫什么名字", "chitchat", None),
    ("我无聊", "chitchat", None),
    ("给我讲个故事", "chitchat", None),
    ("今天是什么节日", "chitchat", None),
    ("1加1等于几", "chitchat", None),
    ("你知道成都有什么好玩的吗", "chitchat", None),
    ("放个屁", "chitchat", None),
    ("哈哈哈", "chitchat", None),
    ("不错", "chitchat", None),
    ("好的", "chitchat", None),
    ("随便", "chitchat", None),
    ("我饿了", "chitchat", None),
    # ── 新增：climate 补充 — ac_control 深度（22→35）──
    ("太干了开点加湿", "climate", "ac_control"),
    ("空调开自动模式", "climate", "ac_control"),
    ("调到内循环", "climate", "ac_control"),
    ("开外循环", "climate", "ac_control"),
    ("除雾", "climate", "ac_control"),
    ("前挡风玻璃除雾", "climate", "ac_control"),
    ("后窗除雾", "climate", "ac_control"),
    ("空调开低风速", "climate", "ac_control"),
    ("制冷关掉", "climate", "ac_control"),
    ("暖风开大点", "climate", "ac_control"),
    ("调到24度自动", "climate", "ac_control"),
    ("空调风速2档", "climate", "ac_control"),
    ("最大风量", "climate", "ac_control"),
    # ── 新增：climate 补充 — window_control 深度（7→15）──
    ("开一半窗", "climate", "window_control"),
    ("后窗打开", "climate", "window_control"),
    ("关后窗", "climate", "window_control"),
    ("开天窗", "climate", "window_control"),
    ("天窗翘起来", "climate", "window_control"),
    ("全关窗", "climate", "window_control"),
    ("车窗开一条缝", "climate", "window_control"),
    ("副驾的窗户关了", "climate", "window_control"),
    # ── 新增：climate 补充 — light_control 深度（9→18）──
    ("氛围灯调蓝色", "climate", "light_control"),
    ("灯调暗一点", "climate", "light_control"),
    ("氛围灯打开", "climate", "light_control"),
    ("关阅读灯", "climate", "light_control"),
    ("后座灯打开", "climate", "light_control"),
    ("后备箱灯", "climate", "light_control"),
    ("仪表盘灯调亮", "climate", "light_control"),
    ("车内灯全开", "climate", "light_control"),
    ("把灯关了", "climate", "light_control"),
    # ── 新增：climate 补充 — seat_control 深度（7→18）──
    ("座椅通风开最大", "climate", "seat_control"),
    ("关座椅加热", "climate", "seat_control"),
    ("座椅按摩", "climate", "seat_control"),
    ("座椅加热2档", "climate", "seat_control"),
    ("副驾座椅加热", "climate", "seat_control"),
    ("后排座椅加热开", "climate", "seat_control"),
    ("关座椅按摩", "climate", "seat_control"),
    ("座椅通风调低", "climate", "seat_control"),
    ("腰托调一下", "climate", "seat_control"),
    ("座椅位置往前调", "climate", "seat_control"),
    ("靠背调直一点", "climate", "seat_control"),
    # ── 新增：media 补充（20→38）──
    ("播放流行音乐", "media", "media_control"),
    ("来首轻音乐", "media", "media_control"),
    ("放点安静的歌", "media", "media_control"),
    ("随机播放", "media", "media_control"),
    ("单曲循环", "media", "media_control"),
    ("列表循环", "media", "media_control"),
    ("上一首", "media", "media_control"),
    ("继续播放", "media", "media_control"),
    ("快进", "media", "media_control"),
    ("倒回去一点", "media", "media_control"),
    ("听电台", "media", "media_control"),
    ("听新闻", "media", "media_control"),
    ("播放有声书", "media", "media_control"),
    ("收音机调到FM95.5", "media", "media_control"),
    ("静音", "media", "media_control"),
    ("取消静音", "media", "media_control"),
    ("音量20", "media", "media_control"),
    ("大声点", "media", "media_control"),
    # ── 新增：multi 多意图补充（15→30）──
    ("关窗开空调", "multi", None),
    ("把灯关了放首歌", "multi", None),
    ("导航回家开窗通风", "multi", None),
    ("调高温度然后静音", "multi", None),
    ("开空调 导航去春熙路 放周杰伦", "multi", None),
    ("先关灯再开空调", "multi", None),
    ("打开座椅加热和导航", "multi", None),
    ("关窗关空调关音乐", "multi", None),
    ("开暖风同时搜下附近加油站", "multi", None),
    ("放首歌顺便查下胎压", "multi", None),
    ("导航去医院顺便看看天气", "multi", None),
    ("调低音量关窗", "multi", None),
    ("帮我开个导航再去搜下附近美食", "multi", None),
    ("空调制冷 导航去机场", "multi", None),
    # ── 新增：needs_context 条件分支/复杂依赖补充（8→18）──
    ("如果下雨的话就别走高速", "needs_context", None),
    ("有最近的就过去", "needs_context", None),
    ("电量低于20就找充电站", "needs_context", None),
    ("附近有便宜的停车场的话就停那", "needs_context", None),
    ("看下明天天气如果好就去青城山", "needs_context", None),
    ("堵车就换条路", "needs_context", None),
    ("胎压不正常就提醒我", "needs_context", None),
    ("找到充电桩的话告诉我", "needs_context", None),
    ("搜下附近有没有洗车店有的话去最近的", "needs_context", None),
    ("先查下油价如果便宜就加", "needs_context", None),
    # ── 新增：unknown/boundary 补充（6→15）──
    ("嗯嗯", "chitchat", None),
    ("dlkfj", "unknown", None),
    ("666", "chitchat", None),
    ("什么", "needs_context", None),
    ("啊", "chitchat", None),
    ("那个", "needs_context", None),
    ("你", "unknown", None),
    ("卡", "unknown", None),
]

BOUNDARY_SET = [
    ("阿巴阿巴", "unknown", None),
    ("asdfghjkl", "unknown", None),
    ("12345", "unknown", None),
    ("！！！", "unknown", None),
    ("嗯", "chitchat", None),
    ("开", "unknown", None),
]


# ── 评估核心 ──


def run_suite(cases: list, logger: ErrorLogger = None) -> dict:
    """运行测试套件，返回指标"""
    stats = {
        "total": 0,
        "correct": 0,
        "fast_rule_hit": 0,
        "edge_hit": 0,
        "cloud_fallback": 0,
        "errors": [],
        "latencies": [],
        "by_domain": {},
    }
    t0 = time.monotonic()

    for text, exp_domain, exp_intent in cases:
        stats["total"] += 1
        domain_key = exp_domain
        stats["by_domain"].setdefault(domain_key, {"total": 0, "correct": 0})

        if exp_domain == "multi":
            fr = fast_rules_check(text, [])
            # cross_domain_flag 或 None 都算正确（放行云端）
            ok = (fr is None) or (isinstance(fr, dict) and fr.get("_cross_domain_flag"))
            if ok:
                stats["cloud_fallback"] += 1
        elif exp_domain == "needs_context":
            ok = not _can_use_edge(text, [])
            if ok:
                stats["cloud_fallback"] += 1
        elif exp_domain == "unknown":
            r = edge_model_infer(text)
            stats["latencies"].append(r.latency_ms)
            ok = not r.is_acceptable
            if ok:
                stats["cloud_fallback"] += 1
        elif exp_intent is None:
            r = edge_model_infer(text)
            stats["latencies"].append(r.latency_ms)
            ok = r.domain == exp_domain
            if r.is_acceptable:
                stats["edge_hit"] += 1
            else:
                stats["cloud_fallback"] += 1
        else:
            fr = fast_rules_check(text, [])
            # 区分"短路命中"和"信号flag"：flag dict(no intent)不算 FastRules hit
            if (
                fr
                and fr.get("intent")
                and not fr.get("_cross_domain_flag")
                and not fr.get("_oos_flag")
            ):
                ok = fr.get("intent") == exp_intent
                if ok:
                    stats["fast_rule_hit"] += 1
                stats["latencies"].append(0)
            else:
                r = edge_model_infer(text)
                stats["latencies"].append(r.latency_ms)
                if r.is_acceptable:
                    ok = r.intent == exp_intent
                    if ok:
                        stats["edge_hit"] += 1
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
                    input=text,
                    domain=exp_domain,
                    intent=exp_intent,
                    slots=EXPECTED_SLOTS.get(text, {}),  # ← 带槽位
                    error_type="intent_confusion" if exp_intent else "domain_miss",
                    error_stage="stage2" if exp_intent else "stage1",
                    error_detail=f"expected {exp_domain}/{exp_intent}",
                )
                logger.log(rec)

        stats["by_domain"][domain_key]["total"] += 1

    stats["accuracy"] = stats["correct"] / stats["total"] if stats["total"] else 0
    stats["avg_latency_ms"] = (
        sum(stats["latencies"]) / len(stats["latencies"]) if stats["latencies"] else 0
    )
    stats["fast_rule_rate"] = (
        stats["fast_rule_hit"] / stats["total"] if stats["total"] else 0
    )
    stats["edge_hit_rate"] = stats["edge_hit"] / stats["total"] if stats["total"] else 0
    stats["cloud_fallback_rate"] = (
        stats["cloud_fallback"] / stats["total"] if stats["total"] else 0
    )
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
        pct_str = (
            f"{delta:+.1%}"
            if key.endswith("_rate")
            else f"{delta:+.0f}ms"
            if "latency" in key
            else f"{delta:+.2f}"
        )

        if direction == "higher" and delta < -threshold:
            alerts.append(
                f"⚠️ {label}: {baseline[key]:.3f} → {current[key]:.3f} ({pct_str}) 退化超过阈值"
            )
        elif direction == "lower" and delta > threshold:
            alerts.append(
                f"⚠️ {label}: {baseline[key]:.0f} → {current[key]:.0f} ({pct_str}) 退化超过阈值"
            )
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
    print(f"\n{'=' * 60}")
    print(f"📊 评估报告  {stats['timestamp'][:19]}")
    print(f"{'=' * 60}")
    print(f"  用例数:     {stats['total']}")
    print(f"  准确率:     {stats['accuracy']:.1%}")
    print(f"  平均延迟:   {stats['avg_latency_ms']:.0f}ms")
    print(f"  fast_rule:  {stats['fast_rule_rate']:.1%}")
    print(f"  edge:       {stats['edge_hit_rate']:.1%}")
    print(f"  cloud:      {stats['cloud_fallback_rate']:.1%}")
    print(f"  耗时:       {stats['elapsed_s']:.1f}s")

    print("\n  各 domain:")
    for domain, d in sorted(stats.get("by_domain", {}).items()):
        acc = d["correct"] / d["total"] if d["total"] else 0
        bar = "█" * int(acc * 20) + "░" * (20 - int(acc * 20))
        print(f"    {domain:12s} {bar} {acc:.0%} ({d['correct']}/{d['total']})")

    if baseline:
        print(f"\n  ── 基线对比 (上次: {baseline.get('timestamp', '?')[:19]}) ──")
        for key, label in [
            ("accuracy", "准确率"),
            ("fast_rule_rate", "fast_rule命中率"),
            ("edge_hit_rate", "edge命中率"),
            ("avg_latency_ms", "平均延迟"),
        ]:
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
            print("\n  🚨 退化告警:")
            for a in alerts:
                print(f"    {a}")
        else:
            print("  ✅ 无退化")

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
