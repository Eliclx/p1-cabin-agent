# Vehicle Domain Knowledge

> 读者：云端 LLM

## 域边界

负责车况查询和场景联动。

| 用户输入 | 归你 | 原因 |
|---------|------|------|
| "还有多少油" | ✓ | 车况查询 |
| "胎压怎么样" | ✓ | 车况查询 |
| "空调多少度" | ✓ | 查空调设定温度 |
| "舒适模式" | ✓ | 场景联动 |
| "休息模式" | ✓ | 场景联动 |
| "打开空调" | ✗ climate | 空调控制 |
| "调低温度" | ✗ climate | 温度调节 |

## 工具

- query_vehicle_status: 查车辆状态 mock
- activate_scene: 场景联动 mock（操作 vehicle_state）
