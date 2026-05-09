"""
project1_cabin_agent/main.py
车载 Agent 入口 + Gradio Demo（流式 + 会话隔离版）
"""
import sys
import os
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import gradio as gr
from gradio.themes import Soft
from typing import List, Tuple, Optional, Dict, Any, AsyncGenerator
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from project1_cabin_agent.graph import build_cabin_agent_graph
from project1_cabin_agent.state import CabinAgentState
from project1_cabin_agent.vehicle_state import vehicle_state
from shared.utils.logger import logger

# 全局 agent 实例（lazy init）
_agent = None

async def get_agent():
    """获取 agent 实例，首次调用时异步初始化（含 SQLite checkpoint）"""
    global _agent
    if _agent is None:
        _agent = await build_cabin_agent_graph()
        logger.info("[init] cabin_agent 已初始化（SQLite 持久化）")
    return _agent


def _build_initial_state(user_input: str, messages: list, asr_confidence: float = 1.0) -> CabinAgentState:
    return {
        "messages": messages,
        "user_input": user_input,
        "asr_confidence": asr_confidence,
        "sub_tasks": [],
        "is_complex": False,
        "task_results": [],
        "completed_task_ids": [],
        "current_task": None,
        "intent": "",
        "final_response": "",
        "error": None,
        "clarify_count": 0,
        "active_frames": [],
        "dialogue_context": {},  # 新增字段：上一轮工具调用结果
    }


async def run_agent(
    user_input: str,
    history: List[Dict[Optional[str], Optional[str]]],
    asr_confidence: float = 1.0,
    session_id: str = "",
) -> Tuple[List[Dict[Optional[str], Optional[str]]], str, tuple]:
    """
    运行一轮 Agent（支持流式 + 会话隔离）
    返回 (updated_history, debug_info)
    """
    messages = [{"role": "user", "content": user_input}]

    # thread_id 是 checkpointer(SqliteSaver) 的查找键
    # config 本身不变，只是"钥匙"；状态快照（含 interrupt 信息）由 SqliteSaver 按 thread_id 存储
    thread_id = session_id or str(uuid.uuid4())
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    try:
        agent = await get_agent()
        history.append({"role": "user", "content": user_input})

        # 检查是否有 pending interrupt 需要恢复
        # 工具槽位缺失，或者风险确认等场景都可能产生 interrupt，等待用户补充信息后再继续执行
        snapshot = await agent.aget_state(config)
        if snapshot.next:
            logger.info(f"[interrupt] 恢复暂停点，用户回答: {user_input}")
            final_state = await agent.ainvoke(
                Command(resume=user_input), config=config
            )
        else:
            # 正常执行入口
            initial_state = _build_initial_state(user_input, messages, asr_confidence)
            final_state = await agent.ainvoke(initial_state, config=config)

        # 检查是否又产生了新的 interrupt，如果有则先不更新历史，直接返回追问提示
        snapshot = await agent.aget_state(config)
        if snapshot.tasks:
            for task in snapshot.tasks:
                if task.interrupts:
                    interrupt_value = task.interrupts[0].value
                    reply = interrupt_value.get("question", "请补充信息")
                    debug_info = f"[追问] {reply}"
                    history.append({"role": "assistant", "content": reply})
                    return history, debug_info, get_panel_snapshot()

        reply = final_state.get("final_response") or "抱歉，我没理解您的意思"

        history.append({"role": "assistant", "content": reply})

        debug_info = (
            f"意图: {final_state.get('intent')} | "
            f"多意图: {'是' if final_state.get('is_complex') else '否'} "
            f"({len(final_state.get('completed_task_ids', []))}/{len(final_state.get('sub_tasks', []))})"
        )
        logger.debug(debug_info)

        return history, debug_info, get_panel_snapshot()

    except Exception as e:
        logger.error(f"Agent 运行失败: {e}", exc_info=True)
        history.append({"role": "assistant", "content": f"系统错误：{e}"})
        return history, f"错误: {e}", get_panel_snapshot()

async def run_agent_stream(                                                                                                        
    user_input: str,                                                                                                               
    history: List[Dict[Optional[str], Optional[str]]],                                                                             
    asr_confidence: float = 1.0,                                                                                                   
    session_id: str = "",                                                                                                          
):                                                                                                                                 
    """                                                                                                                            
    流式运行 Agent，每波 wave_aggregator 输出就 yield 一次回复                                                                     
    """                                                                                                                            
    messages = [{"role": "user", "content": user_input}]
                                                                                                                                   
    thread_id = session_id or str(uuid.uuid4())
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}                                                            
                                                                                                                                   
    try:            
        agent = await get_agent()
        # 获取当前状态                                                                                                              
        snapshot = await agent.aget_state(config)                                                                                                           
        
        if snapshot.next:
            # interrupt 恢复 — 还是用 ainvoke，因为只有一次回复
            final_state = await agent.ainvoke(
                Command(resume=user_input), config=config
            )
            # 检查是否又产生了新的 interrupt
            snapshot = await agent.aget_state(config)
            if snapshot.tasks:
                for task in snapshot.tasks:
                    if task.interrupts:
                        interrupt_value = task.interrupts[0].value
                        reply = interrupt_value.get("question", "请补充信息")
                        yield reply
                        return  # 还有 interrupt，到此结束
            # 没有新 interrupt，yield 最终结果
            reply = final_state.get("final_response") or "抱歉，我没理解您的意思"
            yield reply

        else:
            # 正常流式执行
            initial_state = _build_initial_state(user_input, messages, asr_confidence)
            async for chunk in agent.astream(initial_state, config=config):
                for node_name, state_updates in chunk.items():
                    # logger.info(f"[stream] node={node_name}, value={repr(state_updates)}")
                    # __interrupt__ chunk 是 LangGraph 的 internal chunk，
                    # state_updates 是 tuple (Interrupt(...),)，不是 dict，跳过。
                    # interrupt 的处理统一走 stream 结束后的 aget_state 检查。
                    if node_name == "__interrupt__":
                        continue
                    if not state_updates:
                        continue
                    if not isinstance(state_updates, dict):
                        logger.warning(f"[stream] 跳过非 dict chunk: {node_name} type={type(state_updates).__name__}")
                        continue
                    reply = state_updates.get("final_response", "")
                    if reply:
                        yield reply

            # stream 结束后检查有没有新 interrupt
            snapshot = await agent.aget_state(config)
            if snapshot.tasks:
                for task in snapshot.tasks:
                    if task.interrupts:
                        interrupt_value = task.interrupts[0].value
                        reply = interrupt_value.get("question", "请补充信息")
                        yield reply

    except Exception as e:
        logger.error(f"Agent 运行失败: {e}", exc_info=True)
        yield f"系统错误：{e}"

def get_panel_snapshot():
    s = vehicle_state.snapshot()
    return (
        s["fuel"], s["battery"], s["speed"], s["temperature"], s["mileage"],
        s["tire_status"], s["ac_on"], s["ac_temp"], s["ac_mode"], s["ac_fan_level"],
        s["window_percent"], s["sunroof_percent"], s["music_playing"], s["volume"],
        s["seat_heat_level"], s["light_on"], s["light_brightness"],
    )


def update_vehicle_state(field, value):
    vehicle_state.update({field: value})
    return get_panel_snapshot()


def create_demo():
    with gr.Blocks(title="🚗 智能座舱 Agent Demo", theme=Soft()) as demo:
        gr.Markdown("# 🚗 智能座舱 Agent\n基于 LangGraph + LangChain 构建")

        session_id = gr.State(lambda: str(uuid.uuid4()))

        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(height=500, label="对话")
                with gr.Row():
                    msg_input = gr.Textbox(
                        placeholder="输入车载指令，如：导航去天府广场、开空调、附近加油站...",
                        label="输入指令",
                        scale=4,
                    )
                    send_btn = gr.Button("发送", variant="primary", scale=1)

                with gr.Row():
                    clear_btn = gr.Button("清空对话")
                    asr_slider = gr.Slider(
                        0.3, 1.0, value=1.0, step=0.1,
                        label="模拟ASR置信度（拖低=模拟噪音场景）"
                    )

            with gr.Column(scale=1):
                debug_box = gr.Textbox(label="调试信息", lines=3, interactive=False)

                with gr.Accordion("🚗 车辆状态面板", open=True):
                    gr.Markdown("#### 基础状态")
                    fuel_slider = gr.Slider(0, 100, value=vehicle_state.fuel, step=1, label="油量 (%)")
                    battery_slider = gr.Slider(0, 100, value=vehicle_state.battery, step=1, label="电量 (%)")
                    speed_slider = gr.Slider(0, 200, value=vehicle_state.speed, step=1, label="车速 (km/h)")
                    temp_slider = gr.Slider(-10, 50, value=vehicle_state.temperature, step=0.5, label="车内温度 (°C)")
                    mileage_slider = gr.Number(value=vehicle_state.mileage, label="里程 (km)")
                    tire_dropdown = gr.Dropdown(["正常", "偏低", "偏高"], value=vehicle_state.tire_status, label="胎压状态")

                    gr.Markdown("#### 设备控制")
                    ac_toggle = gr.Checkbox(value=vehicle_state.ac_on, label="空调开关")
                    ac_temp_slider = gr.Slider(16, 32, value=vehicle_state.ac_temp, step=1, label="空调温度 (°C)")
                    ac_mode_dropdown = gr.Dropdown(["auto", "cool", "heat"], value=vehicle_state.ac_mode, label="空调模式")
                    ac_fan_slider = gr.Slider(1, 5, value=vehicle_state.ac_fan_level, step=1, label="风速档位")
                    window_slider = gr.Slider(0, 100, value=vehicle_state.window_percent, step=10, label="车窗开度 (%)")
                    sunroof_slider = gr.Slider(0, 100, value=vehicle_state.sunroof_percent, step=10, label="天窗开度 (%)")
                    music_toggle = gr.Checkbox(value=vehicle_state.music_playing, label="音乐播放")
                    volume_slider = gr.Slider(0, 100, value=vehicle_state.volume, step=1, label="音量")
                    seat_heat_slider = gr.Slider(0, 3, value=vehicle_state.seat_heat_level, step=1, label="座椅加热档位")
                    light_toggle = gr.Checkbox(value=vehicle_state.light_on, label="车内灯")
                    light_brightness_slider = gr.Slider(0, 100, value=vehicle_state.light_brightness, step=5, label="灯光亮度 (%)")

                panel_outputs = [
                    fuel_slider, battery_slider, speed_slider, temp_slider, mileage_slider,
                    tire_dropdown, ac_toggle, ac_temp_slider, ac_mode_dropdown, ac_fan_slider,
                    window_slider, sunroof_slider, music_toggle, volume_slider,
                    seat_heat_slider, light_toggle, light_brightness_slider,
                ]

                panel_inputs = {
                    fuel_slider: "fuel", battery_slider: "battery", speed_slider: "speed",
                    temp_slider: "temperature", mileage_slider: "mileage",
                    tire_dropdown: "tire_status", ac_toggle: "ac_on",
                    ac_temp_slider: "ac_temp", ac_mode_dropdown: "ac_mode",
                    ac_fan_slider: "ac_fan_level", window_slider: "window_percent",
                    sunroof_slider: "sunroof_percent", music_toggle: "music_playing",
                    volume_slider: "volume", seat_heat_slider: "seat_heat_level",
                    light_toggle: "light_on", light_brightness_slider: "light_brightness",
                }

                for comp, field in panel_inputs.items():
                    comp.change(
                        fn=lambda v, f=field: update_vehicle_state(f, v),
                        inputs=[comp],
                        outputs=panel_outputs,
                    )

                gr.Markdown("### 快速测试指令")
                test_cases = [
                    "导航去天府广场", "附近有加油站吗", "开空调", "我有点冷",
                    "关车窗", "还有多少油", "声音大一点", "去机场",
                    "调到22度", "放音乐", "开灯", "舒适驾驶模式",
                ]
                for case in test_cases:
                    gr.Button(case, size="sm").click(
                        fn=lambda x=case: x,
                        outputs=[msg_input]
                    )

        async def submit(msg, history, asr_conf, sid):
            if not msg.strip():
                yield (history, "", "", *get_panel_snapshot())
                return
            history = history or []
            history.append({"role": "user", "content": msg})
            # 先显示用户消息
            yield history, "", "", *get_panel_snapshot()
            # 每收到一次 wave_aggregator 的回复就刷新一次 chatbot
            async for reply in run_agent_stream(msg, history, asr_conf, sid):
                history.append({"role": "assistant", "content": reply})
                yield history, "", "", *get_panel_snapshot()
        # submit_outputs 包含 chatbot 和 debug_box，以及所有面板组件的输出，以便每次提交都能刷新整个界面状态
        # chatbot: 更新对话历史；debug_box: 显示调试信息；panel_outputs: 刷新车辆状态面板（如果有变化）
        submit_outputs = [chatbot, msg_input, debug_box] + panel_outputs
        send_btn.click(submit, [msg_input, chatbot, asr_slider, session_id], submit_outputs)
        msg_input.submit(submit, [msg_input, chatbot, asr_slider, session_id], submit_outputs)
        clear_btn.click(lambda: ([], "", "", *get_panel_snapshot()), outputs=[chatbot, debug_box, msg_input] + panel_outputs)

    return demo


if __name__ == "__main__":
    demo = create_demo()
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
     