# Vehicle Domain Knowledge

> 读者：云端 LLM
> 定位：域知识补充

## 域边界

负责硬车况查询：油量、电量、胎压、里程、车速。

| 用户输入 | 归你 | 原因 |
|---------|------|------|
| "还有多少油" | ✓ | 硬车况查询 |
| "胎压怎么样" | ✓ | 硬车况查询 |
| "电量还剩多少" | ✓ | 硬车况查询 |
| "车速多少" | ✓ | 硬车况查询 |
| "里程多少" | ✓ | 硬车况查询 |
| "空调多少度" | ✗ climate | 座舱查询，归 climate/cabin_query |
| "舒适模式" | ✗ 编排层 | 场景联动，跨域编排 macro，Phase 3 处理 |
| "打开空调" | ✗ climate | 空调控制 |

**vehicle vs climate 边界：**
- 油量/电量/胎压/里程/车速 → 机械状态 → vehicle
- 空调温度/车内温度/湿度 → 座舱环境 → climate

## Intent 说明

| Intent | 说明 | 关键 Slot |
|--------|------|-----------|
| `query_vehicle_status` | 查询车辆硬状态（只读） | items(fuel/battery/tire/mileage/speed) |

## 风险控制

- query_vehicle_status: 纯读操作，无风险
- items 不在合法集合时 fallback 到云端

## 工具

- query_vehicle_status: 查车辆硬状态 mock（油量/电量/胎压/里程/车速）
