# Media Domain Knowledge

> 读者：云端 LLM
> 定位：域知识补充

## 域边界

负责媒体播放控制，包括播放/暂停/切歌/搜索/音量。

| 用户输入 | 归你 | 原因 |
|---------|------|------|
| "放歌"/"放音乐" | ✓ | 媒体播放 |
| "声音大一点"/"小一点" | ✓ | 音量调节 |
| "播放周杰伦" | ✓ | 媒体搜索 |
| "下一首"/"上一首" | ✓ | 切歌 |
| "暂停"/"别放了" | ✓ | 暂停播放 |
| "调低温度" | ✗ climate | 空调 |
| "打开车窗" | ✗ climate | 车窗 |

## Intent 说明

| Intent | 说明 | 关键 Slot |
|--------|------|-----------|
| `media_control` | 媒体播放控制（播放/暂停/切歌/搜索/音量） | action*(play/pause/next/previous/search/volume_up/volume_down/set_volume), query(搜索关键词), volume(0-100) |

## 风险控制

- media_control: 无高风险操作
- 音量 set_volume 超过 90 时建议确认

## 工具

media_control: 无外部 API 依赖，操作 vehicle_state mock。
