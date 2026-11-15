# -*- coding: utf-8 -*-
"""
spider/analyzer.py —— 统计分析层
====================================================================
对抓取到的多城市数据做二次加工，产出"能直接讲给老师听"的结论：

    * 气温排行   —— 全国最高温/最低温城市、昼夜温差榜
    * 区域对比   —— 七大区平均气温
    * 天气分布   —— 晴/多云/阴/雨/雪 各占多少
    * 空气质量   —— AQI 分级统计与最差城市
    * 湿度对比   —— 干湿两端的城市

所有结果组织成一个 dict（``analyze()`` 的返回值），同时供 matplotlib
绘图、HTML 看板、Word 报告三处消费，保证"三处数字完全一致"。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean
from typing import Any, Sequence

from .models import WeatherRecord

# 空气质量分级（GB 3095-2012），颜色用于图表与看板
AQI_LEVELS: list[tuple[int, str, str]] = [
    (50, "优", "#00e400"),
    (100, "良", "#ffff00"),
    (150, "轻度污染", "#ff7e00"),
    (200, "中度污染", "#ff0000"),
    (300, "重度污染", "#99004c"),
    (10 ** 9, "严重污染", "#7e0023"),
]

# 天气现象归类：把"小雨""中雨""暴雨"等归并到"雨"
WEATHER_GROUPS: list[tuple[str, str]] = [
    ("雪", "雪"),
    ("雨", "雨"),
    ("阴", "阴"),
    ("多云", "多云"),
    ("晴", "晴"),
    ("雾", "雾霾"),
    ("霾", "雾霾"),
    ("沙", "雾霾"),
    ("尘", "雾霾"),
    ("风", "大风"),
]


def aqi_level(aqi: float | None) -> tuple[str, str]:
    """返回 (等级名, 颜色)。"""
    if aqi is None:
        return "无数据", "#cccccc"
    for upper, name, color in AQI_LEVELS:
        if aqi <= upper:
            return name, color
    return "严重污染", "#7e0023"


def weather_group(text: str) -> str:
    """把细分天气现象归并为大类，用于统计分布。"""
    if not text:
        return "未知"
    for key, group in WEATHER_GROUPS:
        if key in text:
            return group
    return "其他"


def _avg(values: Sequence[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(mean(vals), 1) if vals else None


# ---------------------------------------------------------------------------
# 主分析入口
# ---------------------------------------------------------------------------
def analyze(records: Sequence[WeatherRecord]) -> dict[str, Any]:
    """对城市记录做全量统计，返回结构化结论。"""
    valid = [r for r in records if r.ok]

    # ---------- 概览 ----------
    update_times = [r.updated_at for r in records if r.updated_at]
    overview = {
        "city_count": len(records),
        "success_count": len(valid),
        "failed_count": len(records) - len(valid),
        "success_rate": round(len(valid) / len(records) * 100, 1) if records else 0.0,
        "update_time": max(update_times) if update_times else "",
        "avg_high": _avg([r.today_high for r in valid]),
        "avg_low": _avg([r.today_low for r in valid]),
    }

    # ---------- 气温排行 ----------
    with_high = [r for r in valid if r.today_high is not None]
    hottest = sorted(with_high, key=lambda r: r.today_high, reverse=True)[:5]
    coldest = sorted(with_high, key=lambda r: r.today_high)[:5]
    with_range = [r for r in valid if r.temp_range is not None]
    biggest_range = sorted(with_range, key=lambda r: r.temp_range, reverse=True)[:5]

    def brief(r: WeatherRecord) -> dict[str, Any]:
        return {
            "city": r.city,
            "region": r.region,
            "high": r.today_high,
            "low": r.today_low,
            "range": r.temp_range,
            "weather": r.weather_text,
            "wind": r.wind_text,
        }

    temperature = {
        "hottest": [brief(r) for r in hottest],
        "coldest": [brief(r) for r in coldest],
        "biggest_range": [brief(r) for r in biggest_range],
    }

    # ---------- 区域对比 ----------
    region_high: dict[str, list[int]] = defaultdict(list)
    for r in valid:
        if r.today_high is not None:
            region_high[r.region].append(r.today_high)
    regions = [
        {
            "region": reg,
            "avg_high": round(mean(vals), 1),
            "max_high": max(vals),
            "min_high": min(vals),
            "count": len(vals),
        }
        for reg, vals in region_high.items()
    ]
    regions.sort(key=lambda x: x["avg_high"], reverse=True)

    # ---------- 天气现象分布 ----------
    raw_counter: Counter[str] = Counter()
    group_counter: Counter[str] = Counter()
    for r in valid:
        raw_counter[r.weather_text] += 1
        for part in str(r.weather_text).replace("转", "/").split("/"):
            part = part.strip()
            if part:
                group_counter[weather_group(part)] += 1
    weather_dist = {
        "raw": [{"name": k, "value": v} for k, v in raw_counter.most_common()],
        "group": [{"name": k, "value": v} for k, v in group_counter.most_common()],
    }

    # ---------- 空气质量 ----------
    aqi_items = []
    for r in valid:
        aqi = r.aqi_now
        if aqi is None:
            continue
        level, color = aqi_level(aqi)
        aqi_items.append({
            "city": r.city,
            "region": r.region,
            "aqi": round(aqi, 0),
            "level": level,
            "color": color,
        })
    aqi_items.sort(key=lambda x: x["aqi"], reverse=True)
    aqi_dist: Counter[str] = Counter(x["level"] for x in aqi_items)
    air = {
        "items": aqi_items,
        "worst": aqi_items[0] if aqi_items else None,
        "best": aqi_items[-1] if aqi_items else None,
        "avg": _avg([x["aqi"] for x in aqi_items]),
        "distribution": [
            {"name": name, "value": aqi_dist.get(name, 0),
             "color": dict((n, c) for _, n, c in AQI_LEVELS).get(name, "#cccccc")}
            for _, name, _c in AQI_LEVELS if aqi_dist.get(name, 0) > 0
        ],
    }

    # ---------- 湿度 ----------
    humid_items = [
        {"city": r.city, "humidity": r.humidity_now}
        for r in valid if r.humidity_now is not None
    ]
    humid_items.sort(key=lambda x: x["humidity"], reverse=True)
    humidity = {
        "items": humid_items,
        "avg": _avg([x["humidity"] for x in humid_items]),
        "max": humid_items[0] if humid_items else None,
        "min": humid_items[-1] if humid_items else None,
    }

    # ---------- 全国气温分布（直方图用） ----------
    highs = sorted(r.today_high for r in with_high)
    temp_spread = {
        "max": highs[-1] if highs else None,
        "min": highs[0] if highs else None,
        "values": [r.today_high for r in with_high],
    }

    return {
        "overview": overview,
        "temperature": temperature,
        "regions": regions,
        "weather": weather_dist,
        "air": air,
        "humidity": humidity,
        "temp_spread": temp_spread,
        "cities": [brief(r) for r in valid],
    }


# ---------------------------------------------------------------------------
# 文本摘要：直接用于报告"结果分析"段落
# ---------------------------------------------------------------------------
def summarize_text(result: dict[str, Any]) -> list[str]:
    """把统计结果转成若干条中文结论句。"""
    ov = result["overview"]
    lines: list[str] = []

    lines.append(
        f"本次共采集 {ov['city_count']} 个城市，成功 {ov['success_count']} 个，"
        f"成功率 {ov['success_rate']}%；数据更新时间为 {ov['update_time'] or '未知'}。"
    )

    temp = result["temperature"]
    if temp["hottest"]:
        h = temp["hottest"][0]
        c = temp["coldest"][0]
        lines.append(
            f"今日最高气温最高的是 {h['city']}（{h['high']}℃），"
            f"最低的是 {c['city']}（{c['high']}℃），"
            f"全国样本城市平均高温 {ov['avg_high']}℃、平均低温 {ov['avg_low']}℃，"
            f"最高与最低相差 {(h['high'] - c['high']) if h['high'] is not None and c['high'] is not None else '—'}℃。"
        )

    if temp["biggest_range"]:
        b = temp["biggest_range"][0]
        lines.append(
            f"昼夜温差最大的是 {b['city']}，温差达 {b['range']}℃"
            f"（{b['low']}~{b['high']}℃），提示该地区昼夜体感差异显著。"
        )

    if result["regions"]:
        r0 = result["regions"][0]
        r_last = result["regions"][-1]
        lines.append(
            f"从区域看，{r0['region']}平均高温最高（{r0['avg_high']}℃），"
            f"{r_last['region']}最低（{r_last['avg_high']}℃）。"
        )

    if result["weather"]["group"]:
        top = result["weather"]["group"][0]
        lines.append(
            f"天气现象以「{top['name']}」为主，共 {top['value']} 个城市出现，"
            f"占有效样本的主要部分。"
        )

    air = result["air"]
    if air["items"]:
        lines.append(
            f"空气质量方面，AQI 平均值 {air['avg']}，"
            f"最差为 {air['worst']['city']}（AQI {int(air['worst']['aqi'])}，{air['worst']['level']}），"
            f"最好为 {air['best']['city']}（AQI {int(air['best']['aqi'])}，{air['best']['level']}）。"
        )

    hum = result["humidity"]
    if hum["items"]:
        lines.append(
            f"相对湿度平均 {hum['avg']}%，最潮湿为 {hum['max']['city']}（{hum['max']['humidity']}%），"
            f"最干燥为 {hum['min']['city']}（{hum['min']['humidity']}%）。"
        )
    return lines
