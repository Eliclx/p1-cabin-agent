"""
project1_cabin_agent/actions/ — Action 信号层

座舱 Agent 的输出分两个通道：
  1. voice_reply — 给用户听的（TTS + 显示）
  2. action — 给硬件执行的（CAN 总线 / 导航模块）

action 信号由 harness 的 format_action() 从 tool_result 提取，
经过 action_registry 校验和标准化后输出。

解耦原则：
  1. 变更频率: action schema 跟硬件协议走，voice_reply 跟 UX 走 → 隔离
  2. 替换可能: 不同车机平台 action 格式不同 → per-domain 声明
  3. 测试独立: action 输出可独立校验（eval sandbox 的验证维度）
  5. 影响范围: 加 action 不改现有 voice_reply 流程

数据流：
  tool_result → harness.format_response() → voice_reply（文字，已有）
  tool_result → harness.format_action()   → action（结构化，新增）
                                       ↓
                               task_result.action
                                       ↓
                            车机 HMI / eval 校验
"""
