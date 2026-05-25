# Climate Domain Knowledge

> 读者：云端 LLM
> 定位：域知识补充

## 域边界

负责车内环境控制和座舱状态查询：空调、车窗、灯光、座椅、座舱状态。

| 用户输入 | 归你 | 原因 |
|---------|------|------|
| "打开空调" | ✓ | 空调控制 |
| "调到22度" | ✓ | 温度调节 |
| "开窗"/"关窗" | ✓ | 车窗 |
| "开灯"/"关灯" | ✓ | 灯光 |
| "加热座椅" | ✓ | 座椅 |
| "空调多少度" | ✓ | 座舱查询(cabin_query) |
| "车内温度" | ✓ | 座舱查询(cabin_query) |
| "太热了"/"冷死了" | ✓ | 要操作→ac_control, 不是cabin_query |
| "播放音乐" | ✗ media | 媒体 |
| "导航去..." | ✗ map | 导航 |
| "还有多少油" | ✗ vehicle | 硬车况 |

**cabin_query vs ac_control 边界：**
- "空调多少度""车内温度" → 问状态 → cabin_query（只读）
- "太热了""冷死了""打开空调" → 要操作 → ac_control（写操作）
- 判断标准：用户是想**知道**还是想**改变**

## Intent 说明

| Intent | 说明 | 关键 Slot |
|--------|------|-----------|
| `ac_control` | 空调控制（开关/调温/调风/模式） | action*(on/off/adjust), temperature(16-32), mode(cool/heat/auto), fan_level(1-5) |
| `window_control` | 车窗/天窗/车门控制 | target*(window/sunroof/door), action*(open/close/adjust), percent(0-100) |
| `light_control` | 车内灯光控制 | action*(on/off/adjust), target(cabin/reading/ambient), brightness(0-100) |
| `seat_control` | 座椅加热/通风控制 | action*(heat_on/heat_off/ventilate_on/ventilate_off), heat_level(1-3) |
| `cabin_query` | 座舱状态查询（只读） | items(ac_temp/cabin_temp/humidity) |

## 风险控制

- window_control: 行驶中禁止开门(door+open)，开窗需确认
- ac_control: 温度范围16-32°C，风速1-5档
- cabin_query: 纯读操作，无风险

## 工具

ac_control, window_control, light_control, seat_control, cabin_query — 纯 mock。
