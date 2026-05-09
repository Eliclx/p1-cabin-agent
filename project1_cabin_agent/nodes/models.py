"""
project1_cabin_agent/nodes/models.py
Pydantic 模型 + 关键词常量集合。
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
