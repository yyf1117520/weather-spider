# -*- coding: utf-8 -*-
"""
spider/models.py —— 数据模型层
====================================================================
用 dataclass 描述"一份天气数据长什么样"，让后续所有模块（存储、分析、
绘图、看板）都面向同一套字段读写，避免到处写 dict['xxx'] 造成拼写错误。

层次关系：
    WeatherRecord  —— 一个城市的完整抓取结果
      ├── today     : TodayForecast   今日/明日分段预报
      ├── week      : list[DayForecast]  未来 7 天逐日预报
      ├── hours3    : list[Hour3Forecast] 未来 3 小时粒度的预报序列
      └── obs24     : list[HourObs]    过去 24 小时逐时实况
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def to_int(text: Any) -> int | None:
    """把 "12"、"12℃"、"-3℃"、"8.2" 之类文本安全转成整数，失败返回 None。"""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(round(text))
    s = str(text).strip().replace("℃", "").replace("°C", "").replace("°", "")
    try:
        return int(round(float(s)))
    except (TypeError, ValueError):
        return None


def to_float(text: Any) -> float | None:
    """把文本安全转成浮点数，失败返回 None。"""
    if text is None:
        return None
    try:
        return float(str(text).strip().replace("℃", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 分段预报（白天 / 夜间）
# ---------------------------------------------------------------------------
@dataclass
class PeriodForecast:
    """今日或明日某一个时段（白天/夜间）的预报。"""

    label: str = ""            # 例如 "15日白天"
    weather: str = ""          # 天气现象，例如 "小雨"、"阴"
    temp: int | None = None    # 该时段温度（℃）
    wind_dir: str = ""         # 风向，例如 "东风"
    wind_level: str = ""       # 风力，例如 "<3级"
    sun_time: str = ""         # 日出 / 日落时刻
    icon: str = ""             # 天气图标代码，例如 "d02" / "n07"
    sky: str = ""              # 天空状况描述，例如 "天空阴沉"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TodayForecast:
    """weather1d 页面的"今天"板块：最多两段（夜/昼）。"""

    update_time: str = ""      # 页面发布时间，例如 "2026-11-15 18:00"
    summary: str = ""          # 隐藏域摘要，例如 "11月15日20时 周日  小雨转阴  4/8°C"
    periods: list[PeriodForecast] = field(default_factory=list)

    # ---- 便捷属性：按标签区分白天段与夜间段 -------------------------------
    def _pick(self, keyword: str) -> PeriodForecast | None:
        for p in self.periods:
            if keyword in p.label:
                return p
        return None

    @property
    def day(self) -> PeriodForecast | None:
        return self._pick("白天")

    @property
    def night(self) -> PeriodForecast | None:
        return self._pick("夜间")

    def to_dict(self) -> dict[str, Any]:
        return {
            "update_time": self.update_time,
            "summary": self.summary,
            "day": self.day.to_dict() if self.day else None,
            "night": self.night.to_dict() if self.night else None,
        }


# ---------------------------------------------------------------------------
# 逐日预报（7 天）
# ---------------------------------------------------------------------------
@dataclass
class DayForecast:
    """未来 7 天中某一天的预报。"""

    date_label: str = ""       # "15日"
    weekday: str = ""          # "今天" / "明天" / "周三"
    weather_day: str = ""      # 白天天气
    weather_night: str = ""    # 夜间天气（若页面只给"阴转多云"则为空）
    temp_high: int | None = None
    temp_low: int | None = None
    wind_dir: str = ""         # 风向，可能含两个（"东风转北风"）
    wind_level: str = ""       # 风力，可能含两个（"3-4级转<3级"）
    sky_level: str = ""        # 天空等级 class，例如 "lv3"
    icon_day: str = ""         # 白天图标代码
    icon_night: str = ""       # 夜间图标代码

    @property
    def full_date(self) -> str:
        """用于图表的短标签："11-15"。"""
        return self.date_label.replace("日", "")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 3 小时粒度预报
# ---------------------------------------------------------------------------
@dataclass
class Hour3Forecast:
    """hour3data 中的一条：时间,图标,天气,温度,风向,风力,昼夜标记。"""

    time_label: str = ""       # "15日23时"
    icon: str = ""
    weather: str = ""
    temp: int | None = None
    wind_dir: str = ""
    wind_level: str = ""
    is_day: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 24 小时实况观测
# ---------------------------------------------------------------------------
@dataclass
class HourObs:
    """observe24h_data 中的一条逐时实况。"""

    hour: str = ""             # "18"
    temp: float | None = None  # 温度（℃，保留一位小数）
    humidity: float | None = None  # 相对湿度（%）
    aqi: float | None = None   # 空气质量指数
    wind_dir: str = ""         # 风向
    wind_level: str = ""       # 风力等级
    wind_degree: float | None = None  # 风向角度（0~360）
    rain: float | None = None  # 降水量

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 单城市完整记录
# ---------------------------------------------------------------------------
@dataclass
class WeatherRecord:
    """一个城市的全部抓取结果，也是 JSON/CSV 序列化的最小单元。"""

    city: str = ""
    city_code: str = ""
    region: str = ""
    url_1d: str = ""
    url_7d: str = ""
    fetched_at: str = ""                     # 抓取时刻（本地时间）
    updated_at: str = ""                     # 站点数据更新时间
    today: TodayForecast = field(default_factory=TodayForecast)
    week: list[DayForecast] = field(default_factory=list)
    hours3: list[Hour3Forecast] = field(default_factory=list)       # 未来 24 小时
    hours3_week: list[Hour3Forecast] = field(default_factory=list)  # 未来 7 天
    obs24: list[HourObs] = field(default_factory=list)
    # 抓取过程元信息：用于报告里说明"健壮性"
    parse_strategy: str = ""                 # 命中的解析策略名
    elapsed_ms: int = 0
    warnings: list[str] = field(default_factory=list)

    # ---- 派生指标：供排行、图表、看板直接使用 ---------------------------
    @property
    def today_high(self) -> int | None:
        """今日最高温：优先取 7 日预报首日，其次取今天白天段。"""
        if self.week and self.week[0].temp_high is not None:
            return self.week[0].temp_high
        return self.today.day.temp if self.today.day else None

    @property
    def today_low(self) -> int | None:
        if self.week and self.week[0].temp_low is not None:
            return self.week[0].temp_low
        return self.today.night.temp if self.today.night else None

    @property
    def temp_range(self) -> int | None:
        """昼夜温差。"""
        if self.today_high is None or self.today_low is None:
            return None
        return self.today_high - self.today_low

    @property
    def weather_text(self) -> str:
        """今日天气现象的合并文本，例如 "小雨转阴"。"""
        parts = []
        if self.week and self.week[0].weather_day:
            parts.append(self.week[0].weather_day)
            if self.week[0].weather_night:
                parts.append(self.week[0].weather_night)
        elif self.today.day:
            parts.append(self.today.day.weather)
            if self.today.night:
                parts.append(self.today.night.weather)
        # 去重："小雨/小雨" -> "小雨"
        uniq: list[str] = []
        for p in parts:
            if p and p not in uniq:
                uniq.append(p)
        return "转".join(uniq)

    @property
    def wind_text(self) -> str:
        if self.week and self.week[0].wind_dir:
            return f"{self.week[0].wind_dir} {self.week[0].wind_level}".strip()
        if self.today.day:
            return f"{self.today.day.wind_dir} {self.today.day.wind_level}".strip()
        return ""

    def _latest_obs(self, attr: str) -> float | None:
        """取实况序列中"最近一个有值"的观测。

        站点各字段的更新频率并不一致：AQI（od28）常常比温度晚一个小时才公布，
        当前整点的 od28 会是空串。这里按时间从新到旧找第一个非空值，
        而不是简单地取列表首条，避免整列 AQI 变成空。
        """
        for obs in self.obs24:
            value = getattr(obs, attr, None)
            if value is not None:
                return value
        return None

    @property
    def humidity_now(self) -> float | None:
        """最新的有效相对湿度（%）——列表首条即最新。"""
        return self._latest_obs("humidity")

    @property
    def aqi_now(self) -> float | None:
        """最新的有效空气质量指数；当前整点未公布时回退到上一整点。"""
        return self._latest_obs("aqi")

    @property
    def temp_now(self) -> float | None:
        """最新的有效实况温度（℃）。"""
        return self._latest_obs("temp")

    @property
    def ok(self) -> bool:
        """是否拿到了可用的核心数据（温度或 7 日预报）。"""
        return self.today_high is not None or bool(self.week)

    def to_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的普通字典（含派生字段，方便前端直接用）。"""
        return {
            "city": self.city,
            "city_code": self.city_code,
            "region": self.region,
            "url_1d": self.url_1d,
            "url_7d": self.url_7d,
            "fetched_at": self.fetched_at,
            "updated_at": self.updated_at,
            "today": self.today.to_dict(),
            "week": [d.to_dict() for d in self.week],
            "hours3": [h.to_dict() for h in self.hours3],
            "hours3_week": [h.to_dict() for h in self.hours3_week],
            "obs24": [o.to_dict() for o in self.obs24],
            "derived": {
                "today_high": self.today_high,
                "today_low": self.today_low,
                "temp_range": self.temp_range,
                "weather_text": self.weather_text,
                "wind_text": self.wind_text,
                "temp_now": self.temp_now,
                "humidity_now": self.humidity_now,
                "aqi_now": self.aqi_now,
                "ok": self.ok,
            },
            "meta": {
                "parse_strategy": self.parse_strategy,
                "elapsed_ms": self.elapsed_ms,
                "warnings": self.warnings,
            },
        }

    # ---- 扁平化：供 CSV / Excel 使用 -----------------------------------
    def to_flat_row(self) -> dict[str, Any]:
        """每个城市一行，便于用 Excel 直接观察。"""
        return {
            "城市": self.city,
            "地区": self.region,
            "城市代码": self.city_code,
            "日期": self.week[0].date_label if self.week else "",
            "最高温(℃)": self.today_high,
            "最低温(℃)": self.today_low,
            "昼夜温差(℃)": self.temp_range,
            "天气": self.weather_text,
            "风向风力": self.wind_text,
            "实况温度(℃)": self.temp_now,
            "相对湿度(%)": self.humidity_now,
            "空气质量指数": self.aqi_now,
            "更新时间": self.updated_at,
            "抓取时间": self.fetched_at,
        }
