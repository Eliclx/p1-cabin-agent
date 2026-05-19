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
    """
    Searches the mock POI dataset for entries matching the given keyword.
    
    Performs an exact-key lookup on the mock dataset first; if no exact key matches, performs a simple fuzzy match by returning the first category whose key is a substring of the keyword or vice versa. Returns up to `limit` POI dictionaries.
    
    Parameters:
        keyword (str): The search keyword used to match dataset keys.
        limit (int): Maximum number of POI entries to return.
    
    Returns:
        list[dict]: A list of POI dictionaries (possibly empty) with at most `limit` items.
    """
    # 精确匹配
    if keyword in _MOCK_POIS:
        return _MOCK_POIS[keyword][:limit]
    # 模糊匹配
    for k, v in _MOCK_POIS.items():
        if keyword in k or k in keyword:
            return v[:limit]
    return []


def search_poi(keyword: str, category: str = None, radius: float = 5.0, limit: int = 3) -> dict:
    """
    Search for nearby points of interest using mock data and return results in a standardized format.
    
    This function queries an internal mock dataset for `keyword` and formats matched POIs into a response object. If no matches are found it returns a single simulated POI entry. The `category` and `radius` parameters are accepted but not used by the mock implementation.
    
    Parameters:
        keyword (str): Search keyword to look up in the mock POI dataset.
        category (str, optional): Category filter (reserved; not applied by the mock).
        radius (float, optional): Search radius in kilometers (reserved; not used).
        limit (int, optional): Maximum number of POIs to return.
    
    Returns:
        dict: A response object with the following keys:
            - "status": Always `"success"` for this mock implementation.
            - "keyword": The original search `keyword`.
            - "results": A list of POI objects. Each POI contains:
                - "name" (str): POI name.
                - "distance" (str): Distance formatted as "<value>km" or "?" if unknown.
                - "rating" (optional, numeric): POI rating when available.
                - "avg_price" (optional, str): Formatted as "¥{value}/人" for per-person prices.
                - "price" (optional, str): Formatted as "¥{value}/晚" for per-night prices.
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
