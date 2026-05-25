# Climate Domain Knowledge

> 读者：云端 LLM

## 域边界

负责车内环境控制和座舱状态查询：空调、车窗、灯光、座椅、座舱状态。

| 用户输入 | 归你 | 原因 |
|---------|------|------|
| "打开空调" | ✓ | 空调控制 |
| "调到22度" | ✓ | 温度调节 |
| "开窗"/"关窗" | ✓ | 车窗 |
| "开灯"/"关灯" | ✓ | 灯光 |
| "加热座椅" | ✓ | 座椅 |
| "空调多少度" | ✓ | 座舱查询(ac_temp) |
| "车内温度" | ✓ | 座舱查询(cabin_temp) |
| "播放音乐" | ✗ media | 媒体 |
| "导航去..." | ✗ map | 导航 |
| "还有多少油" | ✗ vehicle | 硬车况 |

## 风险控制

- window_control: 行驶中禁止开门(door+open)，开窗需确认
- ac_control: 温度范围16-32°C，风速1-5档

## 工具

ac_control, window_control, light_control, seat_control, cabin_query — 纯 mock。
