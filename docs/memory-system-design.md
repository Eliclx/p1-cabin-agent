# P1 记忆系统 + DST + 对话策略 — 系统化设计方案

> 设计时间：2026-06-02
> 设计目标：可插拔记忆模块 + DST + 对话策略 + 主动策略

---

## 一、设计原则

1. **Memory 是一个独立模块** — 不散落在 episodic_memory.py / user_profile.py / state.py 里，
   而是一个统一的 `memory/` 包，提供 `MemoryManager` 统一 API
2. **Memory 只做存储和检索** — 不关心谁调它。DST 读 Memory，Policy 读 DST，pipeline 执行 Policy。
   职责清晰，不耦合
3. **Memory 是可插拔的** — 面试时可以说"底层存储可以换成向量数据库，
   上层逻辑（DST/Policy）零改动"
4. **车机友好** — 不依赖外部服务（向量库/embedding API），只用 SQLite + 规则 + 少量云端 LLM
5. **现有代码最小侵入** — 不改 graph.py 节点拓扑，不改 harness 接口，
   不改 Skill 4文件约定

---

## 二、架构全景

```
                          用户输入
                             │
                             ▼
                    ┌─────────────────┐
                    │   fast_rules     │  (不变)
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ intent_classifier│  (增强：注入 DST 摘要)
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   wave_planner   │  (不变)
                    └────────┬────────┘
                             │ Send × N
                    ┌────────▼────────┐
                    │  context_enrich  │──→ 读 MemoryManager
                    └────────┬────────┘
                             │
               ┌─────────────▼──────────────┐
               │        Policy Layer         │  (新增)
               │  DST state → 策略决策       │
               │  EXECUTE / REROUTE /        │
               │  PROPOSE / EXPLAIN          │
               └─────────────┬──────────────┘
                             │
                    ┌────────▼────────┐
                    │   task_pipeline  │  (增强：执行 Policy 决策)
                    └────────┬────────┘
                             │
               ┌─────────────▼──────────────┐
               │      MemoryManager          │  (新增：统一记忆 API)
               │  write() / query() /        │
               │  evolve() / decay()         │
               ├──────────────────────────────┤
               │  L1 Working Memory (黑板)    │  → state.dialogue_context (不变)
               │  L2 Episodic Memory (行程)   │  → SQLite events.db (增强)
               │  L3 Long-term Memory (偏好)  │  → SQLite preferences.db (增强)
               └─────────────┬──────────────┘
                             │
               ┌─────────────▼──────────────┐
               │     Proactive Engine        │  (新增：异步)
               │  条件检测 → 主动提议         │
               └──────────────────────────────┘
```

---

## 三、MemoryManager — 可插拔记忆模块

### 3.1 目录结构

```
project1_cabin_agent/
├── memory/                          # ← 新增
│   ├── __init__.py                  # 导出 MemoryManager
│   ├── manager.py                   # 统一 API
│   ├── working.py                   # L1 工作记忆（封装黑板，可选）
│   ├── episodic.py                  # L2 行程记忆（改造自 episodic_memory.py）
│   ├── longterm.py                  # L3 长期偏好（改造自 user_profile.py）
│   ├── models.py                    # 数据模型（Event, Preference, MemoryQuery, MemoryHit）
│   ├── decay.py                     # 时间衰减函数
│   └── backends/                    # 可插拔存储后端
│       ├── __init__.py
│       ├── sqlite_backend.py        # 默认：SQLite（车机）
│       └── base.py                  # Backend 抽象接口
├── nodes/
│   ├── dialogue_state.py            # ← 新增：DST
│   ├── context_builder.py           # ← 新增：Context Builder（增强版）
│   ├── policy.py                    # ← 新增：对话策略
│   ├── proactive.py                 # ← 新增：主动策略引擎
│   ├── episodic_memory.py           # → 废弃，迁移到 memory/episodic.py
│   ├── user_profile.py              # → 废弃，迁移到 memory/longterm.py
│   └── ...
```

### 3.2 MemoryManager 统一 API

```python
# memory/manager.py

class MemoryManager:
    """
    统一记忆管理器 — 所有记忆读写的唯一入口。
    
    设计理念：
    - 上层（DST / Policy / context_enrich）只跟 MemoryManager 交互
    - 不直接操作 SQLite / 黑板
    - 后端可替换：SQLite → 向量数据库，上层零改动
    """
    
    def __init__(self, config: MemoryConfig):
        self.episodic = EpisodicStore(config.episodic_db_path)
        self.longterm = LongtermStore(config.longterm_db_path)
        # self.working 直接操作 state.dialogue_context，不需要独立存储
    
    # ── L2 行程记忆 ──
    
    def log_event(self, event_type: str, summary: str, 
                  details: dict = None) -> str:
        """
        写入行程事件。
        内置去重：相似事件 heat+1 而非新建记录。
        内置链接：同目的地自动归入同一 link_group。
        """
        ...
    
    def query_events(self, query: str = None, 
                     event_type: str = None,
                     time_range: tuple[str,str] = None,
                     limit: int = 10) -> list[Event]:
        """
        检索行程事件。
        优先级：关键词匹配(FTS5) > 时间范围 > 全量
        排序：heat × time_decay，热门且近期的排前面
        """
        ...
    
    def get_frequent_destinations(self, top_k: int = 5) -> list[FrequentPlace]:
        """获取高频目的地（dedup_count 排序）"""
        ...
    
    def get_linked_events(self, link_group: str) -> list[Event]:
        """获取同一关联组的所有事件"""
        ...
    
    # ── L3 长期偏好 ──
    
    def save_preference(self, key: str, value: str,
                       source: str = "slot_extraction",
                       confidence: float = 1.0) -> None:
        """写入偏好。支持置信度和来源追踪。"""
        ...
    
    def get_preference(self, key: str) -> str | None:
        """读取偏好（同时 heat+1）"""
        ...
    
    def get_active_preferences(self, top_k: int = 10) -> list[Preference]:
        """
        获取活跃偏好（带时间衰减排序）。
        用于注入 LLM prompt / DST 构建。
        """
        ...
    
    def evolve_preferences(self, events: list[Event]) -> None:
        """
        从行程事件进化偏好（异步，云端 LLM）。
        触发条件：未分析事件 total_heat >= 阈值。
        
        对标：MemoryOS 的 _trigger_profile_and_knowledge_update
        """
        ...
    
    # ── 生命周期 ──
    
    def decay_all(self) -> int:
        """
        批量衰减：删除低于地板价的偏好/事件。
        建议每次 session 开始时调用一次。
        """
        ...
    
    # ── 统一查询（跨层） ──
    
    def recall(self, query: str, top_k: int = 10) -> list[MemoryHit]:
        """
        统一检索：同时查 L2 行程 + L3 偏好，合并排序。
        返回 MemoryHit 列表，每条带 source 标记和 score。
        
        这是 DST / context_builder 最常用的接口。
        """
        ...
```

### 3.3 数据模型

```python
# memory/models.py

@dataclass
class Event:
    """行程事件"""
    id: int
    timestamp: str
    event_type: str          # navigate / search_poi / media_control / weather
    summary: str             # "导航去天府广场"
    details: dict            # {"destination": "天府广场", "distance": "5km"}
    
    # ← 以下为新增字段
    session_id: str = ""     # 驾车行程分组
    dedup_hash: str = ""     # 去重指纹（event_type + 标准化 summary）
    dedup_count: int = 1     # 被合并次数（= 热度信号）
    heat: float = 1.0        # 热度分
    link_group: str = ""     # 关联分组
    last_accessed: str = ""  # 最后访问时间
    analyzed: bool = False   # 是否已被 LLM 分析过

@dataclass
class Preference:
    """用户偏好"""
    key: str
    value: str
    confidence: float = 1.0  # 置信度
    source: str = "slot_extraction"  # slot_extraction / llm_analysis
    heat: float = 1.0        # 被使用次数
    created_at: str = ""
    updated_at: str = ""
    last_used_at: str = ""

@dataclass
class FrequentPlace:
    """高频地点"""
    name: str                # "天府广场"
    visit_count: int         # 30
    last_visit: str          # 上次去的时间
    event_types: list[str]   # ["navigate", "search_poi"]
    is_home: bool = False    # LLM 推断
    is_work: bool = False    # LLM 推断

@dataclass
class MemoryHit:
    """统一检索结果"""
    source: str              # "episodic" / "preference" / "frequent_place"
    content: str             # 人类可读文本
    score: float             # 排序分
    data: dict               # 原始数据
    timestamp: str = ""

@dataclass
class MemoryQuery:
    """检索请求"""
    text: str = ""           # 查询文本（FTS5 关键词）
    event_type: str = None   # 过滤事件类型
    time_range: tuple = None # (start, end)
    top_k: int = 10
    min_score: float = 0.0   # 最低分过滤
```

### 3.4 时间衰减

```python
# memory/decay.py

def time_decay(created_at: str, half_life_days: float = 14.0, 
               alpha: float = 0.3, now: datetime = None) -> float:
    """
    指数时间衰减。
    
    对标：MemOS recency.ts — applyRecencyDecay
    
    公式：score × (alpha + (1 - alpha) × 0.5^(age_days / half_life))
    
    - half_life_days=14: 14天半衰期（两周前的记忆权重减半）
    - alpha=0.3: 旧但相关的记忆不会清零，最低保留 30% 权重
    
    Args:
        created_at: ISO 格式时间字符串
        half_life_days: 半衰期天数
        alpha: 保留系数（越高旧记忆权重越大）
        now: 当前时间（可注入，测试用）
    
    Returns:
        0.0 ~ 1.0 之间的衰减系数
    """
    if now is None:
        now = datetime.now()
    created = datetime.fromisoformat(created_at)
    age_days = max(0, (now - created).total_seconds() / 86400)
    decay = 0.5 ** (age_days / half_life_days)
    return alpha + (1 - alpha) * decay


def score_with_decay(heat: float, created_at: str, **kwargs) -> float:
    """热度 × 时间衰减 = 最终得分"""
    return heat * time_decay(created_at, **kwargs)
```

### 3.5 存储后端接口

```python
# memory/backends/base.py

class MemoryBackend(ABC):
    """可插拔存储后端抽象"""
    
    @abstractmethod
    def store_event(self, event: Event) -> int: ...
    
    @abstractmethod
    def find_similar_event(self, event_type: str, 
                           dedup_hash: str) -> Event | None: ...
    
    @abstractmethod
    def search_events(self, query: str, **kwargs) -> list[Event]: ...
    
    @abstractmethod
    def store_preference(self, pref: Preference) -> None: ...
    
    @abstractmethod
    def load_preference(self, key: str) -> Preference | None: ...
    
    @abstractmethod
    def load_all_preferences(self) -> list[Preference]: ...


# memory/backends/sqlite_backend.py

class SqliteBackend(MemoryBackend):
    """
    默认后端：SQLite。
    
    适合：嵌入式车机，零外部依赖。
    特性：FTS5 全文检索 + WAL 并发 + 时间衰减纯计算。
    """
    ...
```

---

## 四、DST — 对话状态追踪

### 4.1 核心数据结构

```python
# nodes/dialogue_state.py

class UserAttitude(str, Enum):
    """用户态度 — 影响 Policy 决策"""
    NEUTRAL = "neutral"
    SATISFIED = "satisfied"                  # "好的""谢谢"
    UNSATISFIED = "unsatisfied"              # "太贵了""不好用""太远了"
    WANTS_ALTERNATIVE = "wants_alternative"  # "有别的方案吗""换个""其他路线"
    CONFUSED = "confused"                    # "什么意思""你说啥"
    CORRECTING = "correcting"                # "不是，我是说..."

class ActiveGoal(BaseModel):
    """当前活跃目标 — 对话在做什么"""
    goal_type: str                    # "navigate" / "search" / "climate" / ...
    slots: dict = {}                  # 当前轮已收集的槽位
    attempt_count: int = 0            # 尝试次数（重复执行同一目标）
    last_result: dict | None = None   # 上次工具返回的结果
    status: str = "active"            # active / completed / abandoned

class DialogueState(BaseModel):
    """
    对话状态 — 每轮更新，checkpoint 持久化。
    
    存储在 state.dialogue_state，跨轮保留。
    由 ContextBuilder 每轮重建。
    """
    # ── 当前对话 ──
    active_goals: list[ActiveGoal] = []    # 可以有多个并行目标
    user_attitude: UserAttitude = UserAttitude.NEUTRAL
    turn_count: int = 0
    last_system_action: str = ""           # "navigated" / "searched" / "ac_adjusted" / ...
    
    # ── 历史摘要 ──
    intent_history: list[str] = []         # 最近10轮意图
    key_entities: dict = {}                # 当前对话关键实体 {"destination": "重庆", "route_type": "avoid_toll"}
    
    # ── 策略信号 ──
    consecutive_failures: int = 0          # 连续失败次数
    needs_reroute: bool = False            # 需要换方案
    pending_proposal: str | None = None    # 待提出的主动建议
    
    # ── 记忆摘要（从 MemoryManager 加载）──
    active_preferences: list[dict] = []    # [{"key": "route_type", "value": "avoid_toll", "score": 0.8}]
    frequent_destinations: list[dict] = [] # [{"name": "天府广场", "count": 30}]
    
    # ── 便捷方法 ──
    
    def get_primary_goal(self) -> ActiveGoal | None:
        """获取主要活跃目标"""
        active = [g for g in self.active_goals if g.status == "active"]
        return active[0] if active else None
    
    def get_goal_by_type(self, goal_type: str) -> ActiveGoal | None:
        for g in self.active_goals:
            if g.goal_type == goal_type and g.status == "active":
                return g
        return None
    
    def is_repeating(self, window: int = 3) -> bool:
        """最近 N 轮是否同一意图"""
        if len(self.intent_history) < window:
            return False
        return len(set(self.intent_history[-window:])) == 1
    
    def get_entity(self, key: str) -> str | None:
        """获取关键实体（优先级：本轮key_entities > active_goal.slots > Memory偏好）"""
        if key in self.key_entities:
            return self.key_entities[key]
        goal = self.get_primary_goal()
        if goal and key in goal.slots:
            return goal.slots[key]
        return None
```

### 4.2 Context Builder — 每轮构建 DST

Context Builder 是 DST 的"大脑"，每轮在 `intent_classifier` 之前运行。

**职责：**
1. 从 `state` + `MemoryManager` 构建 `DialogueState`
2. 生成结构化摘要注入 LLM prompt
3. 替代"让 LLM 从 30 条历史推理上下文"的低效做法

```python
# nodes/context_builder.py

class ContextBuilder:
    """
    对话状态构建器。
    
    数据流：
      state + MemoryManager → DialogueState → 摘要文本 → 注入 LLM
    
    对标：
    - Rasa CALM Dialogue Understanding
    - MemoryOS 的 get_response() 中的 context 组装
    """
    
    def __init__(self, memory: MemoryManager):
        self.memory = memory
    
    def build_state(self, state: CabinAgentState) -> DialogueState:
        """
        从 CabinAgentState 构建 DialogueState。
        
        步骤：
        1. 读取上一轮 dialogue_state（checkpoint 持久化）
        2. 更新 turn_count
        3. 从 user_input 推断 user_attitude
        4. 从 task_results 更新 active_goals
        5. 从 MemoryManager 加载活跃偏好和高频地点
        6. 检测策略信号（needs_reroute / is_repeating）
        """
        ...
    
    def generate_summary(self, ds: DialogueState) -> str:
        """
        生成注入 LLM prompt 的结构化摘要。
        
        关键：不是把所有数据都塞给 LLM，而是精选"当前对话需要知道的"。
        
        示例输出：
        ```
        [对话状态]
        - 当前目标: 导航 → 重庆
        - 用户态度: 不满意(太贵了过路费)
        - 上次路线: 距离300km, 收费165元, 避高速
        - 已尝试: 2次
        - 🔄 用户需要换方案，建议设置 route_type=avoid_toll
        
        [用户偏好]
        - 导航偏好: 避收费(热度8)
        - 常去地点: 天府广场(30次), 万达广场(12次)
        ```
        """
        ...
```

### 4.3 state.py 新增字段

```python
# state.py 新增

dialogue_state: Optional[dict]
    # DialogueState 的 dict 序列化
    # 跨轮保留（不重置）
    # 由 ContextBuilder 每轮重建
    # LangGraph checkpoint 自动持久化
```

---

## 五、Policy — 对话策略

### 5.1 策略动作

```python
# nodes/policy.py

class PolicyAction(str, Enum):
    EXECUTE = "execute"       # 正常执行工具（默认）
    REROUTE = "reroute"       # 自动换方案（覆盖 slots，如 avoid_toll）
    PROPOSE = "propose"       # 主动提议（跳过工具，直接生成建议回复）
    EXPLAIN = "explain"       # 解释当前状态（"当前路线是走高速..."）
    FILL_FROM_DST = "fill"    # 从 DST 回填缺失槽位
    ABANDON = "abandon"       # 放弃当前目标
```

### 5.2 策略决策

```python
@dataclass
class PolicyDecision:
    action: PolicyAction
    slot_overrides: dict = {}     # 需要覆盖的槽位
    hint: str = ""                # 决策原因（日志/调试）
    proposal_text: str = ""       # PROPOSE 动作的回复文本
    inject_prompt: str = ""       # 注入 LLM 的额外指令

class DialogPolicy:
    """
    对话策略 — 根据 DST 决定下一步动作。
    
    核心原则：
    - 不替代 intent_classifier（意图识别仍走三层漏斗）
    - 在 pipeline 执行前做策略性干预
    - 只在明确条件时覆盖，默认不干预
    
    策略优先级：
    1. REROUTE（用户不满，强制换方案）
    2. FILL_FROM_DST（槽位缺失，从 DST 回填）
    3. PROPOSE（重复尝试，主动提议替代）
    4. EXPLAIN（用户困惑，解释当前状态）
    5. ABANDON（放弃当前目标）
    6. EXECUTE（默认：正常执行）
    """
    
    def __init__(self, memory: MemoryManager):
        self.memory = memory
    
    def decide(self, ds: DialogueState, intent: str, 
               slots: dict) -> PolicyDecision:
        
        goal = ds.get_primary_goal()
        
        # ── 策略1: REROUTE ──
        # 条件：用户不满 + 有活跃导航目标 + 目的地还在
        # 对标：你 Phase 4 计划里的核心场景
        if self._should_reroute(ds, intent):
            return PolicyDecision(
                action=PolicyAction.REROUTE,
                slot_overrides=self._build_reroute_overrides(ds),
                hint=f"用户不满({ds.user_attitude.value})，自动换方案",
            )
        
        # ── 策略2: FILL_FROM_DST ──
        # 条件：关键槽位缺失 + DST 有值
        # 对标：MemoryOS 的 retrieve_context 回填
        fill = self._try_fill_from_dst(ds, intent, slots)
        if fill:
            return fill
        
        # ── 策略3: PROPOSE ──
        # 条件：重复3次 + 有活跃目标
        # 对标：Proactive Agent 主动提议
        if ds.is_repeating() and goal and goal.attempt_count >= 3:
            return self._build_proposal(ds, goal)
        
        # ── 策略4: EXPLAIN ──
        # 条件：用户困惑 + 有上次结果
        if ds.user_attitude == UserAttitude.CONFUSED and goal and goal.last_result:
            return PolicyDecision(
                action=PolicyAction.EXPLAIN,
                inject_prompt=self._build_explain_prompt(ds, goal),
                hint="用户困惑，解释当前状态",
            )
        
        # ── 策略5: ABANDON ──
        # 条件：连续失败 >= 3
        if ds.consecutive_failures >= 3:
            return PolicyDecision(
                action=PolicyAction.ABANDON,
                hint="连续失败3次，放弃当前目标",
            )
        
        # ── 默认: EXECUTE ──
        return PolicyDecision(action=PolicyAction.EXECUTE)
```

### 5.3 策略规则详解

```python
    def _should_reroute(self, ds: DialogueState, intent: str) -> bool:
        """是否需要换方案"""
        if ds.user_attitude not in (UserAttitude.UNSATISFIED, 
                                      UserAttitude.WANTS_ALTERNATIVE):
            return False
        goal = ds.get_goal_by_type("navigate")
        if not goal or not goal.last_result:
            return False
        # 有上次结果且用户不满 → 换方案
        return True
    
    def _build_reroute_overrides(self, ds: DialogueState) -> dict:
        """构建换方案的槽位覆盖"""
        goal = ds.get_goal_by_type("navigate")
        overrides = {
            "destination": goal.slots.get("destination"),  # 保留目的地
        }
        
        last_result = goal.last_result or {}
        
        # 根据用户态度推断应该换什么
        # "太贵了" → avoid_toll
        # "太远了" → 可能是目的地问题，不换 route_type
        # "太慢了" → fastest
        
        # 更智能的方式：查 MemoryManager 的偏好
        route_pref = self.memory.get_preference("route_type")
        if route_pref:
            overrides["route_type"] = route_pref
        else:
            # 默认：用户说贵→avoid_toll
            overrides["route_type"] = "avoid_toll"
        
        return overrides
    
    def _try_fill_from_dst(self, ds: DialogueState, 
                           intent: str, slots: dict) -> PolicyDecision | None:
        """从 DST 回填缺失槽位"""
        fills = {}
        
        # 导航缺目的地 → 从 DST 取
        if intent == "navigate" and not slots.get("destination"):
            dest = ds.get_entity("destination")
            if dest:
                fills["destination"] = dest
        
        # 音乐缺歌名 → 从 L3 偏好取
        if intent == "media_control" and not slots.get("query"):
            music = self.memory.get_preference("music_query")
            if music:
                fills["query"] = music
        
        # 空调缺温度 → 从 L3 偏好取
        if intent == "ac_control" and not slots.get("temperature"):
            temp = self.memory.get_preference("ac_temperature")
            if temp:
                fills["temperature"] = temp
        
        if not fills:
            return None
        
        return PolicyDecision(
            action=PolicyAction.FILL_FROM_DST,
            slot_overrides=fills,
            hint=f"从 DST/L3 回填: {fills}",
        )
```

---

## 六、Proactive Engine — 主动策略

### 6.1 设计理念

主动策略和被动策略（Policy）不同：
- **Policy**：在 pipeline 内执行，每轮都会触发，**同步**
- **Proactive**：在特定条件下才触发，**异步**，不阻塞主流程

对标：
- ProAgent (arxiv 2512.06721) — Agent 主动推断用户需求
- PROGRESS.md 痛点："对话整体机械，没有记忆和主动性"

### 6.2 主动策略触发器

```python
# nodes/proactive.py

@dataclass
class ProactiveTrigger:
    """主动提议触发条件"""
    name: str                        # 触发器名称
    condition: Callable              # 判断是否触发
    proposal: Callable               # 生成提议文本
    priority: int = 0                # 优先级（越高越优先）
    cooldown_turns: int = 5          # 冷却轮数（避免反复提议）

class ProactiveEngine:
    """
    主动策略引擎。
    
    位置：session_update 之后异步检查。
    不阻塞主流程，只返回建议文本追加到 final_response。
    
    设计原则：
    - 只建议，不强制（用户可以忽略）
    - 有冷却期（同一建议5轮内不重复）
    - 有优先级（安全提醒 > 路线建议 > 音乐推荐）
    """
    
    def __init__(self, memory: MemoryManager):
        self.memory = memory
        self.triggers = self._register_triggers()
        self.last_trigger_turn: dict[str, int] = {}  # trigger_name → turn_count
    
    def check(self, ds: DialogueState, state: CabinAgentState) -> str | None:
        """
        检查所有触发器，返回最高优先级的主动提议。
        没有触发则返回 None。
        """
        proposals = []
        
        for trigger in self.triggers:
            # 冷却检查
            last = self.last_trigger_turn.get(trigger.name, -999)
            if ds.turn_count - last < trigger.cooldown_turns:
                continue
            
            if trigger.condition(ds, state, self.memory):
                text = trigger.proposal(ds, state, self.memory)
                if text:
                    proposals.append((trigger.priority, trigger.name, text))
        
        if not proposals:
            return None
        
        # 取优先级最高的
        proposals.sort(key=lambda x: x[0], reverse=True)
        _, name, text = proposals[0]
        self.last_trigger_turn[name] = ds.turn_count
        return text
    
    def _register_triggers(self) -> list[ProactiveTrigger]:
        return [
            # ── 1. 低油量提醒 ──
            ProactiveTrigger(
                name="low_fuel",
                condition=self._low_fuel_condition,
                proposal=self._low_fuel_proposal,
                priority=100,  # 安全提醒优先级最高
                cooldown_turns=10,
            ),
            # ── 2. 高频目的地建议 ──
            ProactiveTrigger(
                name="frequent_dest",
                condition=self._frequent_dest_condition,
                proposal=self._frequent_dest_proposal,
                priority=20,
                cooldown_turns=5,
            ),
            # ── 3. 路线偏好建议 ──
            ProactiveTrigger(
                name="route_suggestion",
                condition=self._route_suggestion_condition,
                proposal=self._route_suggestion_proposal,
                priority=30,
                cooldown_turns=3,
            ),
            # ── 4. 天气出行提醒 ──
            ProactiveTrigger(
                name="weather_reminder",
                condition=self._weather_condition,
                proposal=self._weather_proposal,
                priority=50,
                cooldown_turns=20,
            ),
            # ── 5. 音乐偏好建议 ──
            ProactiveTrigger(
                name="music_suggestion",
                condition=self._music_condition,
                proposal=self._music_proposal,
                priority=10,
                cooldown_turns=10,
            ),
        ]
```

### 6.3 触发器实现示例

```python
    # ── 低油量 ──
    
    def _low_fuel_condition(self, ds, state, memory) -> bool:
        """油量 < 20%"""
        ctx = state.get("dialogue_context", {})
        fuel = ctx.get("entity.vehicle", [{}])
        if isinstance(fuel, list) and fuel:
            fuel_val = fuel[0].get("data", {}).get("fuel", 100)
            return fuel_val < 20
        return False
    
    def _low_fuel_proposal(self, ds, state, memory) -> str:
        return "油量有点低了，需要帮您搜索附近加油站吗？"
    
    # ── 高频目的地 ──
    
    def _frequent_dest_condition(self, ds, state, memory) -> bool:
        """用户刚上车（turn_count=1）且有高频目的地"""
        if ds.turn_count > 1:
            return False
        freq = memory.get_frequent_destinations(top_k=1)
        return len(freq) > 0 and freq[0].visit_count >= 5
    
    def _frequent_dest_proposal(self, ds, state, memory) -> str:
        freq = memory.get_frequent_destinations(top_k=3)
        if len(freq) >= 2:
            names = "、".join(f.name for f in freq[:2])
            return f"今天要去{names}吗？"
        elif freq:
            return f"需要导航去{freq[0].name}吗？"
        return None
    
    # ── 路线偏好 ──
    
    def _route_suggestion_condition(self, ds, state, memory) -> bool:
        """导航完成 + 用户偏好不同路线类型"""
        goal = ds.get_goal_by_type("navigate")
        if not goal or not goal.last_result:
            return False
        # 路线有收费 + 用户之前偏好避收费
        toll = goal.last_result.get("toll", "")
        route_pref = memory.get_preference("route_type")
        return "元" in str(toll) and route_pref == "avoid_toll"
    
    def _route_suggestion_proposal(self, ds, state, memory) -> str:
        return "这条路线有收费，要不要帮您换个免费的？"
```

---

## 七、集成到现有架构

### 7.1 graph.py — 不改节点拓扑

```
现有拓扑（不变）：
  message_compressor → fast_rules → intent_classifier → wave_planner → task_pipeline → session_update → wave_aggregator

只做这些增强：
1. intent_classifier 内调用 ContextBuilder.build_state()
2. task_pipeline 内调用 Policy.decide()
3. session_update / wave_aggregator 后调用 ProactiveEngine.check()
4. 全局初始化 MemoryManager 单例
```

### 7.2 初始化

```python
# main.py 或 graph.py 顶部

from memory import MemoryManager
from nodes.context_builder import ContextBuilder
from nodes.policy import DialogPolicy
from nodes.proactive import ProactiveEngine

# 全局单例
memory = MemoryManager(MemoryConfig(
    episodic_db_path="data/events.db",
    longterm_db_path="data/preferences.db",
))

context_builder = ContextBuilder(memory)
policy = DialogPolicy(memory)
proactive = ProactiveEngine(memory)
```

### 7.3 intent_classifier 增强

```python
# nodes/intent.py — intent_classifier 函数内

def intent_classifier(state: CabinAgentState) -> dict:
    # ... 现有逻辑 ...
    
    # ← 新增：构建 DST
    ds = context_builder.build_state(state)
    summary = context_builder.generate_summary(ds)
    
    # ← 增强：注入 DST 摘要到 LLM prompt
    enhanced_prompt = original_prompt + "\n\n" + summary
    
    # ... LLM 调用 ...
    
    return {
        **result,
        "dialogue_state": ds.model_dump(),  # ← 持久化 DST
    }
```

### 7.4 task_pipeline 增强

```python
# nodes/pipeline.py — _handle_skill_task 函数内

async def _handle_skill_task(state, task_id, task, intent, slots):
    # ... 现有 registry/context_enrich 逻辑 ...
    
    # ← 新增：Policy 决策
    ds_dict = state.get("dialogue_state", {})
    ds = DialogueState(**ds_dict) if ds_dict else DialogueState()
    decision = policy.decide(ds, intent, slots)
    
    # 应用策略
    if decision.slot_overrides:
        slots.update(decision.slot_overrides)
        logger.info(f"[policy] {decision.action.value}: {decision.hint}")
    
    if decision.action == PolicyAction.PROPOSE:
        return _make_result(task_id, intent, decision.proposal_text, 
                           task, tool_result={})
    
    if decision.action == PolicyAction.ABANDON:
        return _make_result(task_id, intent, "好的，我们换个话题吧", 
                           task, tool_result={})
    
    # ... 继续原有 pre_validate → tool → post_validate 流程 ...
```

### 7.5 session_update 增强

```python
# nodes/response.py — session_update 函数内

@track_node("session_update")
def session_update(state: CabinAgentState | dict) -> dict:
    # ... 现有黑板写入逻辑 ...
    
    # ← 增强：通过 MemoryManager 写入
    memory.log_event_from_results(task_results)  # 去重+热度+链接
    
    # ← 增强：检查主动策略
    ds_dict = state.get("dialogue_state", {})
    ds = DialogueState(**ds_dict) if ds_dict else DialogueState()
    proactive_text = proactive.check(ds, state)
    
    # 如果有主动提议，追加到回复
    if proactive_text:
        # 不覆盖原有回复，追加
        ...
    
    return {"dialogue_context": context_update}
```

---

## 八、数据流全景（完整示例）

```
═══ 第一轮：用户 "导航去重庆" ═══

1. ContextBuilder:
   - 首轮，无历史 DST
   - 从 MemoryManager 加载偏好: route_type=avoid_toll(热度8)
   - 生成摘要: "[用户偏好] 导航偏好: 避收费"

2. intent_classifier:
   - 注入 DST 摘要，LLM 识别 navigate + destination=重庆

3. Policy:
   - 无活跃目标，无态度信号 → EXECUTE（不干预）

4. task_pipeline:
   - harness.pre_validate → 通过
   - 工具执行: 导航去重庆，距离300km，收费165元
   - harness.post_validate → 通过
   - harness.format_response → "导航去重庆，全程300公里，预计收费165元"

5. session_update:
   - MemoryManager.log_event: "导航去重庆"
     → 去重: 无重复，新建记录，heat=1
     → 链接: "重庆"首次出现，新建 link_group
   - DST 更新: active_goal={type:navigate, dest:重庆, result:{toll:165元}}

6. ProactiveEngine:
   - route_suggestion: 路线有收费+偏好避收费 → "这条路线有收费，要不要换个免费的？"
   - 追加到回复: "导航去重庆...。这条路线有收费，要不要换个免费的？"

═══ 第二轮：用户 "太贵了，有其他方案吗" ═══

1. ContextBuilder:
   - 读取上轮 DST: active_goal={navigate, 重庆, toll:165元}
   - 推断态度: WANTS_ALTERNATIVE（"太贵了"+"有其他方案"）
   - 生成摘要: "[对话状态] 用户不满(太贵了), 上次路线收费165元, 🔄 建议换方案"

2. intent_classifier:
   - 注入 DST 摘要，LLM 理解用户是要换导航方案
   - 输出: intent=navigate, slots={}

3. Policy:
   - should_reroute: WANTS_ALTERNATIVE + 有导航目标 + 有上次结果 → True
   - 返回: REROUTE, overrides={destination:"重庆", route_type:"avoid_toll"}

4. task_pipeline:
   - Policy 覆盖: slots = {destination:"重庆", route_type:"avoid_toll"}
   - 工具执行: 导航去重庆(避收费)，距离320km，收费0元
   - 回复: "已为您重新规划路线，走免费道路，全程320公里，不收费"

5. session_update:
   - MemoryManager.log_event: "导航去重庆(避收费)"
     → 去重: 和上条"导航去重庆"相似度 0.7 < 0.85，新建记录
     → 但 route_type 不同，记为新事件
   - DST 更新: active_goal.attempt_count = 2, last_result 更新

═══ 第三轮：用户 "那就走国道" ═══

1. ContextBuilder:
   - 读取上轮 DST: active_goal={navigate, 重庆, attempt=2, last_result:320km/0元}
   - 态度: NEUTRAL（"那就"表示接受）
   - 生成摘要: "[对话状态] 用户目标: 导航→重庆, 上次已换方案(320km, 0元)"

2. intent_classifier:
   - DST 摘要告知 LLM: 用户在说路线类型
   - 输出: intent=navigate, slots={route_type:"avoid_highway"}（"国道"→avoid_highway）

3. Policy:
   - destination 缺失 + DST 有值 → FILL_FROM_DST
   - overrides={destination: "重庆"}
   - hint="从 DST 回填 destination=重庆"

4. task_pipeline:
   - slots = {route_type:"avoid_highway", destination:"重庆"}（自动回填！）
   - 工具执行: 国道去重庆
   - 回复: "好的，走国道去重庆，全程310公里"

═══ 第四轮：用户 "今天去了哪些地方" ═══

1. ContextBuilder:
   - MemoryManager.query_events("今天", time_range=today)
   - 返回: [导航去重庆(2次), ...]
   - 生成摘要: "[行程记忆] 今天: 09:00 导航去重庆, 09:15 重新规划(避收费), 09:20 走国道去重庆"

2. intent_classifier:
   - 时间回溯词触发 → direct_answer

3. task_pipeline:
   - direct_answer 分支，带行程数据
   - 回复: "今天您导航去了重庆，换了三次路线，最后走了国道"
```

---

## 九、实施路径

### Phase 4A: MemoryManager 基础设施 (~4h)

| 步骤 | 文件 | 内容 |
|------|------|------|
| 4A.1 | memory/ 目录 | 创建 MemoryManager + 数据模型 |
| 4A.2 | memory/episodic.py | 改造 episodic_memory.py（去重+热度+链接） |
| 4A.3 | memory/longterm.py | 改造 user_profile.py（置信度+热度+来源） |
| 4A.4 | memory/decay.py | 时间衰减函数 |
| 4A.5 | 迁移 | 旧文件改为调用 MemoryManager，确保零退化 |

### Phase 4B: DST + ContextBuilder (~3h)

| 步骤 | 文件 | 内容 |
|------|------|------|
| 4B.1 | nodes/dialogue_state.py | DST 数据结构 |
| 4B.2 | nodes/context_builder.py | 状态构建 + 摘要生成 |
| 4B.3 | state.py | 新增 dialogue_state 字段 |
| 4B.4 | nodes/intent.py | 集成 ContextBuilder |

### Phase 4C: Policy (~3h)

| 步骤 | 文件 | 内容 |
|------|------|------|
| 4C.1 | nodes/policy.py | 策略决策器 |
| 4C.2 | nodes/pipeline.py | 集成 Policy（策略覆盖 + PROPOSE/EXPLAIN） |
| 4C.3 | 测试 | 15-20 条策略单测 |

### Phase 4D: Proactive Engine (~2h)

| 步骤 | 文件 | 内容 |
|------|------|------|
| 4D.1 | nodes/proactive.py | 主动策略引擎 |
| 4D.2 | nodes/response.py | 集成 Proactive（追加到回复） |
| 4D.3 | 测试 | 主动策略单测 |

### Phase 4E: Memory 进化 (异步) (~2h)

| 步骤 | 文件 | 内容 |
|------|------|------|
| 4E.1 | memory/manager.py | evolve_preferences (Heat 触发 LLM) |
| 4E.2 | session_update | 检查 Heat 阈值，触发进化 |
| 4E.3 | 测试 | 进化流程单测 |

---

## 十、面试讲述框架

> **S**: 第一版是纯 intent→tool 映射。三大问题：① 用户说"太贵了"系统重新给同样路线；② "那就走国道"系统追问"您去哪"丢目的地；③ 对话机械没有主动性，用户偏好写入了但回复时不用。
>
> **T**: 对标 Rasa CALM 架构，设计可插拔的记忆系统 + DST + 对话策略 + 主动策略。目标：系统理解对话进展、自动补全信息、主动提议、记忆进化。
>
> **A**:
> 1. **可插拔记忆模块**：设计 MemoryManager 统一 API，底层 SQLite 可替换为向量数据库。集成去重（dedup）、热度（heat）、时间衰减（半衰期14天）、自动链接（同目的地）
> 2. **DST**：设计 DialogueState 结构，由 ContextBuilder 每轮从 state + MemoryManager 构建。结构化摘要替代"让 LLM 从 30 条历史推理上下文"
> 3. **对话策略**：Policy 根据 DST 决定 EXECUTE/REROUTE/PROPOSE/EXPLAIN。用户不满自动换方案，槽位缺失从 DST 回填
> 4. **主动策略**：ProactiveEngine 异步检查条件（低油量/高频目的地/路线偏好），有冷却期和优先级
> 5. **记忆进化**：借鉴 MemoryOS 的 Heat 机制，未分析事件热度超阈值才触发云端 LLM 分析，提取 pattern + 更新偏好
> 6. **最小侵入**：不改 LangGraph 图结构，不改 harness 接口，不改 Skill 4 文件约定
>
> **R**: "太贵了"自动切换 avoid_toll；"那就走国道"自动从 DST 回填目的地不追问；高频目的地主动推荐；336 条 eval 零退化。记忆从纯写入变成"写入→检索→影响回复"的闭环。

---

## 十一、三个开源项目的借鉴点对照

| 设计点 | 来源 | P1 实现 |
|--------|------|---------|
| Heat 热度驱动升级 | MemoryOS | dedup_count + heat → 超阈值触发 LLM 分析 |
| 短→中→长分层迁移 | MemoryOS | L1黑板 → L2行程 → L3偏好（已有框架，补流通机制） |
| 用户画像 LLM 分析 | MemoryOS | evolve_preferences() |
| 时间衰减（半衰期14天）| MemOS | decay.py: 0.5^(age/14) × (0.3 + 0.7×decay) |
| 去重 (dedup) | MemOS | dedup_hash 相似度检查，相同则 heat+1 |
| CJK bigram 检索 | MemOS | SQLite FTS5 + CJK tokenizer（Phase 4E 可选） |
| 记忆链接 (links) | A-MEM | link_group（同目的地自动关联，规则驱动而非 LLM） |
| 新记忆更新旧记忆 | A-MEM | evolve_preferences + confidence 加权合并 |
| 可插拔后端 | MemOS | MemoryBackend 抽象接口，默认 SQLite |
| Skill Evolution | MemOS | 暂不实现（P1 的 Skill 是领域内固定的） |
| 每次调 LLM 做进化 | A-MEM | ❌ 不采用（车机延迟受不了） |
| RRF + MMR 四层检索 | MemOS | ❌ 不采用（需要向量数据库） |
| JSON 文件存储 | MemoryOS | ❌ 不采用（已有 SQLite） |
