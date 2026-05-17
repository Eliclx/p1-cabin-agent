"""
project1_cabin_agent/nodes/constants.py
Pydantic 模型 + 关键词常量集合。

合并自原 models.py，职责：数据结构定义。
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any


# ── 指代 / 上下文关键词 ──

STRONG_COREFERENCE = {
    "最近的那个", "刚才的", "上一个", "另一个", "刚才说的",
    "那个", "它", "那边", "那里", "这", "那",
}

IMPLIES_CONTEXT = {
    "现在", "目前", "当前", "刚才", "之后", "然后",
    "怎么样", "呢", "这个", "那个", "后来", "结果",
    "可以吗", "好吗", "行吗", "对吧", "是不是",
}

INDEPENDENT_KEYWORDS = {
    "导航去", "导航到", "搜索", "附近有", "找一", "帮我查",
    "播放", "开启", "关闭", "打开", "帮我开", "帮我关",
    "查一下", "多少油", "多少电", "胎压",
}

# ── 歧义检测常量（原 intent_ambiguity.py） ──

# 不含明确操作对象的极短输入，且 LLM 分配了具体工具意图 → 歧义
AMBIGUOUS_SHORT_INTENTS = {
    "ac_control", "media_control", "light_control", "window_control",
    "seat_control", "search_poi", "start_navigation", "parking",
    "query_vehicle_status", "activate_scene", "comfort_driving",
}

# 明确的操作对象关键词 → 即使短输入也不拦截
CLEAR_OBJECT_WORDS = {
    # 空调
    "空调", "冷气", "暖气", "温度", "风量", "除雾",
    # 车窗/门
    "车窗", "窗户", "天窗", "车门", "后备箱",
    # 灯光
    "灯", "大灯", "雾灯", "氛围灯", "阅读灯",
    # 座椅
    "座椅", "座位", "靠背", "加热", "通风", "按摩",
    # 媒体
    "音乐", "歌", "电台", "广播", "收音机", "播放",
    # 导航
    "导航", "地图",
    # 车辆状态
    "油量", "电量", "续航", "胎压", "油耗",
    # 停车
    "停车", "车位",
}

# 模糊代词 / 指代不明词汇（出现在 slot 值里 → 幻觉填充）
VAGUE_SLOT_VALUES = {
    "那边", "这边", "最近的", "那个", "这个", "那里", "这里",
    "那个地方", "上面", "下面", "旁边", "对面",
}

# ── 漂移检测常量（原 intent_drift.py） ──

# 用户含这些词时，slot 值来自上轮回复是正常的指代消解，不算漂移
COREFERENCE_INDICATORS = {
    "就去", "去这个", "去那个", "选这个", "选那个", "就这个", "就那个",
    "第一个", "第二个", "第三个", "第一个吧", "第二个吧",
    "这个吧", "那个吧", "要这个", "要那个", "用它", "就它",
    # 指代导航: "去最近的""去最远的""去第一个" 等
    "去最近的", "去最远的", "去第一个", "去第二个",
    "导航去最近的", "导航去最远的",
}


# ── Pydantic 模型 ──

class SubTask(BaseModel):
    task_id: str = Field(default="", description="子任务唯一ID")
    intent: str = Field(description="意图类型")
    intent_confidence: float = Field(ge=0.0, le=1.0, description="意图置信度")
    ambiguity_score: float = Field(ge=0.0, le=1.0, description="歧义程度")
    ambiguity_reason: str = Field(default="", description="歧义原因")
    required_slots: List[str] = Field(default_factory=list, description="需要的槽位列表")
    extracted_slots: Dict[str, Any] = Field(default_factory=dict, description="已提取的槽位")
    depends_on: List[str] = Field(default_factory=list, description="依赖的子任务ID列表")
    urgency: str = Field(default="normal", description="immediate/normal/low")
    voice_reply: str = Field(default="", description="语音播报文本。由下游回复节点生成，意图分类时留空。direct_answer 意图不填此字段")


class IntentOutput(BaseModel):
    sub_tasks: List[SubTask] = Field(description="拆解后的子任务列表")
    is_complex: bool = Field(description="是否为多意图")
    model_thinking: str = Field(default="", description="模型思考过程的文本描述")
