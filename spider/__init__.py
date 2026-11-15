# -*- coding: utf-8 -*-
"""spider 包：中国天气网多城市数据采集与可视化。"""

from .models import (
    DayForecast,
    Hour3Forecast,
    HourObs,
    PeriodForecast,
    TodayForecast,
    WeatherRecord,
)
from .http_client import FetchError, RobotsDisallowed, WeatherHttpClient
from .parser import WeatherParser
from .pipeline import WeatherCrawler

__all__ = [
    "DayForecast", "Hour3Forecast", "HourObs", "PeriodForecast",
    "TodayForecast", "WeatherRecord",
    "FetchError", "RobotsDisallowed", "WeatherHttpClient",
    "WeatherParser", "WeatherCrawler",
]

__version__ = "2.0"
