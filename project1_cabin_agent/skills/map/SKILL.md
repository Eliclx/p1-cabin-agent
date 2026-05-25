# Map Domain Knowledge

> 读者：云端 LLM
> 定位：域知识补充

## 域边界

负责地图相关功能：导航、POI搜索、地图信息查询、天气。

| 用户输入 | 归你 | 原因 |
|---------|------|------|
| "导航去天府广场" | ✓ | 导航 |
| "附近加油站" | ✓ | POI 搜索 |
| "换一条路" | ✓ | 导航 (reroute) |
| "前面堵不堵" | ✓ | 路况查询 |
| "现在在哪儿" | ✓ | 位置查询 |
| "今天天气怎么样" | ✓ | 天气查询 |
| "明天成都多少度" | ✓ | 天气查询 |
| "开空调" | ✗ climate | 空调控制 |
| "放音乐" | ✗ media | 媒体 |

## Intent 说明

| Intent | 说明 | 关键 Slot |
|--------|------|-----------|
| `navigate` | 路线规划/导航 | destination(必填), strategy(可选) |
| `search_poi` | 搜索附近 POI | keyword(必填), radius(可选) |
| `map_query` | 地图信息查询 (位置/距离/路况/ETA) | query_type, target |
| `weather` | 天气查询 | city, date |

## 风险控制

- navigate: 需确认目的地，高风险目的地（医院等）二次确认
- search_poi: radius 默认 3000m，超过 10km 需确认

## 工具

- navigate / search_poi / map_query: 高德 API (amap)
- weather: mock 数据
