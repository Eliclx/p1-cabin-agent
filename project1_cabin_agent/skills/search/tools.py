"""
project1_cabin_agent/skills/search/tools.py
Search Skill 工具层 — 纯 mock（无外部 API 依赖）
"""
import random

# 模拟 POI 数据
_MOCK_POIS = {
    "加油站": [
        {"name": "中石化国贸加油站", "distance_km": 1.2, "rating": 4.1},
        {"name": "中石油朝阳门加油站", "distance_km": 3.8, "rating": 4.0},
        {"name": "壳牌大望路加油站", "distance_km": 5.1, "rating": 4.3},
    ],
    "餐厅": [
        {"name": "全聚德(王府井店)", "distance_km": 5.6, "rating": 3.8, "avg_price": 197},
        {"name": "东来顺(前门店)", "distance_km": 6.3, "rating": 3.8, "avg_price": 146},
        {"name": "大董(南新仓店)", "distance_km": 7.4, "rating": 4.9, "avg_price": 285},
    ],
    "医院": [
        {"name": "北京协和医院", "distance_km": 2.1, "rating": 4.5},
        {"name": "北京同仁医院", "distance_km": 3.5, "rating": 4.3},
    ],
    "停车场": [
        {"name": "国贸停车场", "distance_km": 0.8, "rating": 3.5},
        {"name": "万达停车场", "distance_km": 1.5, "rating": 4.0},
    ],
    "酒店": [
        {"name": "北京国贸大酒店", "distance_km": 2.0, "rating": 4.6, "price": 1200},
        {"name": "如家快捷(朝阳门店)", "distance_km": 3.2, "rating": 3.5, "price": 200},
    ],
    "便利店": [
        {"name": "7-Eleven(建国路)", "distance_km": 0.5, "rating": 4.0},
    ],
    "火锅店": [
        {"name": "海底捞(王府井店)", "distance_km": 4.2, "rating": 4.7, "avg_price": 120},
        {"name": "小龙坎(三里屯店)", "distance_km": 5.8, "rating": 4.5, "avg_price": 100},
    ],
    "川菜馆": [
        {"name": "眉州东坡(国贸店)", "distance_km": 3.1, "rating": 4.2, "avg_price": 80},
    ],
    "春熙路": [
        {"name": "春熙路步行街", "distance_km": 3.0, "rating": 4.8},
    ],
}


def _search_mock(keyword: str, limit: int = 3) -> list[dict]:
    """从 mock 数据中搜索"""
    # 精确匹配
    if keyword in _MOCK_POIS:
        return _MOCK_POIS[keyword][:limit]
    # 模糊匹配
    for k, v in _MOCK_POIS.items():
        if keyword in k or k in keyword:
            return v[:limit]
    return []


def search_poi(keyword: str, category: str = None, radius: float = 5.0, limit: int = 3) -> dict:
    """搜索周边兴趣点。

    keyword: 搜索关键词
    category: 类别过滤（可选）
    radius: 搜索半径(公里)
    limit: 返回数量
    """
    pois = _search_mock(keyword, limit)

    if pois:
        formatted = []
        for p in pois:
            info = {"name": p["name"], "distance": f"{p.get('distance_km','?')}km"}
            if "rating" in p:
                info["rating"] = p["rating"]
            if "avg_price" in p:
                info["avg_price"] = f"¥{p['avg_price']}/人"
            if "price" in p:
                info["price"] = f"¥{p['price']}/晚"
            formatted.append(info)
        return {"status": "success", "keyword": keyword, "results": formatted}

    # fallback
    fallback = [{"name": f"{keyword}（模拟数据）", "distance": "1.0km"}]
    return {"status": "success", "keyword": keyword, "results": fallback}
