"""真实天气 → 游戏天气。

链路：IP 定位（ip-api.com） → wttr.in 查天气 → 映射到 game Weather 四档。
任何一步失败都静默 fallback：返回 None，调用方保持当前天气不变。
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

GameWeather = Literal["clear", "cloudy", "rain", "storm"]

# wttr.in WMO 天气码 → 游戏天气
# https://wttr.in/:help 里的 weather_condition_codes
_WMO_TO_GAME: dict[int, GameWeather] = {
    # 晴
    113: "clear",
    # 局部多云 / 多云
    116: "cloudy", 119: "cloudy", 122: "cloudy",
    # 雾/霾
    143: "cloudy", 248: "cloudy", 260: "cloudy",
    # 毛毛雨
    176: "rain", 179: "rain", 182: "rain", 185: "rain",
    263: "rain", 266: "rain", 281: "rain", 284: "rain",
    293: "rain", 296: "rain", 299: "rain", 302: "rain",
    305: "rain", 308: "rain",
    # 冻雨 / 冰雹
    311: "rain", 314: "rain", 317: "rain", 320: "rain",
    # 暴雨 / 雷暴 / 大雨
    353: "rain", 356: "storm", 359: "storm",
    362: "rain", 365: "rain", 368: "rain", 371: "storm", 374: "rain", 377: "rain",
    386: "storm", 389: "storm", 392: "storm", 395: "storm",
    # 雪（岛上当作 rain）
    227: "rain", 230: "rain", 323: "rain", 326: "rain",
    329: "rain", 332: "rain", 335: "rain", 338: "rain",
    350: "rain",
}


async def _get_city_from_ip() -> str:
    """用 ip-api.com 的免费接口获取当前出口 IP 所在城市，失败返回 '深圳'。"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get("http://ip-api.com/json/?fields=city,status&lang=zh-CN")
            data = r.json()
            if data.get("status") == "success" and data.get("city"):
                return data["city"]
    except Exception as e:
        logger.debug("IP 定位失败: %s", e)
    return "深圳"


async def _get_weather_code(city: str) -> int | None:
    """向 wttr.in 查 WMO 天气码，失败返回 None。"""
    try:
        url = f"https://wttr.in/{city}?format=j1"
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers={"Accept": "application/json"})
            data = r.json()
            code = int(
                data["current_condition"][0]["weatherCode"]
            )
            return code
    except Exception as e:
        logger.debug("wttr.in 查询失败（city=%s）: %s", city, e)
        return None


async def fetch_real_weather() -> GameWeather | None:
    """完整链路：IP 定位 → 天气查询 → 映射。任何失败返回 None。"""
    city = await _get_city_from_ip()
    logger.info("[weather] 定位城市: %s", city)
    code = await _get_weather_code(city)
    if code is None:
        return None
    game_weather = _WMO_TO_GAME.get(code)
    if game_weather is None:
        # 未知码：用简单规则兜底
        if code >= 380:
            game_weather = "storm"
        elif code >= 290:
            game_weather = "rain"
        elif code >= 115:
            game_weather = "cloudy"
        else:
            game_weather = "clear"
    logger.info("[weather] WMO %d → %s（城市：%s）", code, game_weather, city)
    return game_weather
