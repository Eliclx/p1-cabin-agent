"""
project1_cabin_agent/nodes/context_enrich.py
ContextEnrichmentNode — 按 CONTEXT_DEPS 声明组装 AgentContext

设计原则：
- 在 task_pipeline 之前运行，为 harness 准备好所有上下文数据
- 只拉 harness 声明需要的数据层，不浪费
- 纯数据搬运，不做校验（校验归 harness）

数据流位置：
  intent_classifier → wave_planner → [context_enrich → task_pipeline] × N
                                        ↑
                                    这个节点

数据源：
  VEHICLE: vehicle_state 全局单例（车载场景天然单车单用户）
  L1:      State.dialogue_context（黑板栈式记忆，跨轮保留）
  L2:      State.active_frames（行程记忆/对话帧）
  L3:      user_profile 模块（用户偏好，跨设备持久化）

注意：
  context_enrich 只在新路径（已迁移的 domain）触发
  旧路径（climate/media 等）不走这个节点，黑板回填仍在 route_wave 里
"""
from project1_cabin_agent.state import CabinAgentState
from project1_cabin_agent.harness.context import AgentContext, VehicleSnapshot
from project1_cabin_agent.harness.base import ContextDep
from project1_cabin_agent.skills.registry import (
    is_domain_migrated, get_harness, get_domain_for_intent,
)
from project1_cabin_agent.vehicle_state import vehicle_state
from shared.utils.logger import logger


def _build_vehicle_snapshot() -> VehicleSnapshot:
    """从 vehicle_state 全局单例构建快照

    vehicle_state 是实时更新的（模拟车机信号），
    每次调 context_enrich 取最新值，不缓存。
    """
    return VehicleSnapshot(
        location=vehicle_state.location,
        speed=vehicle_state.speed,
        ac_on=vehicle_state.ac_on,
        ac_temp=vehicle_state.ac_temp,
        ac_mode=vehicle_state.ac_mode,
        ac_fan_level=vehicle_state.ac_fan_level,
        window_percent=vehicle_state.window_percent,
        sunroof_percent=vehicle_state.sunroof_percent,
        fuel=vehicle_state.fuel,
        battery=vehicle_state.battery,
        temperature=vehicle_state.temperature,
    )


def _extract_l1_dialogue(state: CabinAgentState) -> dict:
    """从 State.dialogue_context 黑板提取 L1 对话记忆

    黑板是栈式存储，每个 key 对应一个栈，取栈顶（最新值）
    """
    dialogue_context = state.get("dialogue_context", {})
    if not dialogue_context:
        return {}

    # 展开黑板：每个 key 取栈顶
    flat = {}
    for tag, stack in dialogue_context.items():
        if isinstance(stack, list) and stack:
            flat[tag] = stack[0].get("data", {}) if isinstance(stack[0], dict) else stack[0]
        else:
            flat[tag] = stack
    return flat


def _extract_l2_session(state: CabinAgentState) -> dict:
    """从 State.active_frames 提取 L2 会话记忆

    active_frames 存的是"没完成的意图"，包含：
    - 上次的 intent + slots（供 carry-over）
    - pending 状态的帧
    """
    frames = state.get("active_frames", [])
    if not frames:
        return {}

    session = {}
    # 提取最近的行程信息
    for frame in frames:
        intent = frame.get("intent", "")
        slots = frame.get("extracted_slots", {})
        if intent in ("navigate_to", "start_navigation") and "destination" in slots:
            session["last_destination"] = slots["destination"]
            break

    return session


def _extract_l3_user_prefs() -> dict:
    """从 user_profile 模块提取 L3 用户偏好

    当前使用 mock 数据，未来对接真实用户画像系统
    """
    try:
        from project1_cabin_agent.nodes import user_profile
        prefs = {}
        # 尝试获取常用地址
        home = user_profile.get_preference("home_address")
        if home:
            prefs["home_address"] = home
        company = user_profile.get_preference("company_address")
        if company:
            prefs["company_address"] = company
        return prefs
    except (ImportError, AttributeError):
        # user_profile 模块不可用或没有对应方法
        return {}


def enrich_context_for_task(state: CabinAgentState, task: dict) -> AgentContext | None:
    """为单个任务组装 AgentContext

    根据 task 的 domain 找到对应 harness 的 CONTEXT_DEPS，
    只拉需要的数据层。

    Args:
        state: LangGraph 全局状态
        task: 当前子任务（current_task）

    Returns:
        AgentContext 对象（直接传给 harness，不入 State），或 None（非迁移域）
    """
    intent = task.get("intent", "")

    # 1. 判断是否走新路径
    domain = get_domain_for_intent(intent)
    if domain is None:
        # 非迁移域，不走 context_enrich
        return None

    # 2. 获取 harness 的 CONTEXT_DEPS
    harness = get_harness(domain)
    if harness is None:
        return None

    deps = harness.CONTEXT_DEPS

    # 3. 按需组装
    vehicle = None
    dialogue = None
    session = None
    user = None

    if ContextDep.VEHICLE in deps:
        vehicle = _build_vehicle_snapshot()
        logger.info(f"[context_enrich] <- VEHICLE: location={vehicle.location}, speed={vehicle.speed}")

    if ContextDep.L1 in deps:
        dialogue = _extract_l1_dialogue(state)
        logger.info(f"[context_enrich] <- L1 dialogue: {list(dialogue.keys())}")

    if ContextDep.L2 in deps:
        session = _extract_l2_session(state)
        logger.info(f"[context_enrich] <- L2 session: {list(session.keys())}")

    if ContextDep.L3 in deps:
        user = _extract_l3_user_prefs()
        logger.info(f"[context_enrich] <- L3 user: {list(user.keys())}")

    ctx = AgentContext(
        vehicle=vehicle or VehicleSnapshot(),
        dialogue=dialogue or {},
        session=session or {},
        user=user or {},
    )

    return ctx
