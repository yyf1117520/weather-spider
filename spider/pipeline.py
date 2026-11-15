# -*- coding: utf-8 -*-
"""
spider/pipeline.py —— 抓取调度层
====================================================================
把 抓取(http_client) → 解析(parser) → 组装(models) 串成一条流水线，
并负责多城市并发、单城市失败隔离、结果校验与合并。

设计要点：
  * **失败隔离**：任一城市抓取/解析失败只影响自己，不影响其他城市；
  * **并发抓取**：ThreadPoolExecutor + 有界线程数，配合客户端内的限速，
    在"快"与"不对站点造成压力"之间取得平衡；
  * **数据补全**：7 日预报首日有时缺"最高温"（当天最高温已过），
    用 1 日页的白天时段温度补上，保证表格完整；
  * **可观测**：每个城市记录耗时、命中策略、告警信息，便于写进报告。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable, Iterable

from bs4 import BeautifulSoup

import config
from .http_client import FetchError, RobotsDisallowed, WeatherHttpClient
from .models import WeatherRecord
from .parser import WeatherParser


class WeatherCrawler:
    """多城市天气抓取流水线。"""

    def __init__(
        self,
        client: WeatherHttpClient | None = None,
        workers: int = config.MAX_WORKERS,
        logger=None,
    ) -> None:
        self.client = client or WeatherHttpClient(logger=logger)
        self.workers = max(1, workers)
        self.log = logger

    # ------------------------------------------------------------------
    # 单城市
    # ------------------------------------------------------------------
    def crawl_city(self, city: str) -> WeatherRecord:
        """抓取并解析一个城市，永不抛异常（失败信息写进 warnings）。"""
        started = time.time()
        record = WeatherRecord(city=city, region=config.region_of(city))
        code = config.code_of(city)
        if not code:
            record.warnings.append(f"未收录该城市代码：{city}")
            record.elapsed_ms = int((time.time() - started) * 1000)
            return record

        record.city_code = code
        record.url_1d = config.URL_TEMPLATE_1D.format(code=code)
        record.url_7d = config.URL_TEMPLATE_7D.format(code=code)
        record.fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ---------- 1) 抓"今天"页 ----------
        html_1d = ""
        try:
            html_1d = self.client.fetch(record.url_1d)
        except RobotsDisallowed as exc:
            record.warnings.append(f"robots 限制：{exc}")
            record.elapsed_ms = int((time.time() - started) * 1000)
            return record
        except FetchError as exc:
            record.warnings.append(f"今天页抓取失败：{exc}")

        if html_1d:
            soup = BeautifulSoup(html_1d, "lxml")

            # 城市名校验：确认拿到的确实是目标城市的页面
            name = WeatherParser.parse_city_name(html_1d, soup, expect=city)
            if name and name != city:
                record.warnings.append(f"城市名不一致：期望 {city}，页面为 {name}")
                # 若页面城市名与代码表不符，说明代码表有误，仍以配置名为准展示
            record.city = city

            record.today, record.parse_strategy = WeatherParser.parse_today(
                html_1d, soup, record.warnings)
            record.updated_at = record.today.update_time

            record.obs24 = WeatherParser.parse_obs24(html_1d)
            record.hours3, record.hours3_week = WeatherParser.parse_hour3(html_1d)

        # ---------- 2) 抓"7 天"页 ----------
        try:
            html_7d = self.client.fetch(record.url_7d)
        except (FetchError, RobotsDisallowed) as exc:
            html_7d = ""
            record.warnings.append(f"7天页抓取失败：{exc}")

        if html_7d:
            soup7 = BeautifulSoup(html_7d, "lxml")
            record.week = WeatherParser.parse_week(html_7d, soup7, record.warnings)
            if not record.updated_at:
                record.updated_at = WeatherParser.parse_update_time(soup7)

        # ---------- 3) 数据补全 ----------
        self._complete(record)
        self._quality_check(record)

        record.elapsed_ms = int((time.time() - started) * 1000)
        if self.log:
            flag = "OK " if record.ok else "FAIL"
            self.log.info("[%s] %-6s %s  高温%s 低温%s  %dms",
                          flag, record.city, record.weather_text,
                          record.today_high, record.today_low, record.elapsed_ms)
        return record

    @staticmethod
    def _complete(record: WeatherRecord) -> None:
        """补齐 7 日预报首日缺失的温度，并让 today 与 week 首日互相印证。"""
        day0 = record.week[0] if record.week else None
        today_day = record.today.day
        today_night = record.today.night

        if day0 is not None:
            # "今天"一栏在傍晚只显示夜间温度，最高温从 1 日页白天段补
            if day0.temp_high is None and today_day and today_day.temp is not None:
                day0.temp_high = today_day.temp
            if day0.temp_low is None and today_night and today_night.temp is not None:
                day0.temp_low = today_night.temp
            # 反过来：1 日页白天天气缺失时用 7 日页补
            if today_day is not None and not today_day.weather:
                today_day.weather = day0.weather_day
            if today_night is not None and not today_night.weather:
                today_night.weather = day0.weather_night or day0.weather_day

        # 极端兜底：没有 7 日页时，用 1 日页的昼/夜温度撑起首日
        if day0 is None and (today_day or today_night):
            from .models import DayForecast
            fake = DayForecast(date_label=datetime.now().strftime("%d日").lstrip("0"),
                               weekday="今天")
            fake.temp_high = today_day.temp if today_day else None
            fake.temp_low = today_night.temp if today_night else None
            fake.weather_day = today_day.weather if today_day else ""
            fake.weather_night = today_night.weather if today_night else ""
            fake.wind_dir = today_day.wind_dir if today_day else ""
            fake.wind_level = today_day.wind_level if today_day else ""
            record.week = [fake]

    @staticmethod
    def _quality_check(record: WeatherRecord) -> None:
        """数据质量校验：把可疑之处记进 warnings，而不是悄悄删掉。

        真实站点的实况序列偶尔会出现"相邻整点温度跳变十几度"的异常值，
        本系统选择 **保留原始数据 + 记录告警**，既保证数据可追溯，
        又让使用者能一眼看出哪些点需要人工复核。
        """
        obs = record.obs24
        jumps = 0
        for a, b in zip(obs, obs[1:]):
            if a.temp is not None and b.temp is not None and abs(a.temp - b.temp) > 8:
                jumps += 1
        if jumps:
            record.warnings.append(
                f"实况温度序列存在 {jumps} 处相邻整点跳变超过 8℃（疑似源数据异常，已保留原值）")

        # 校验：最高温必须不低于最低温（发现错位则交换底层字段）
        if (record.today_high is not None and record.today_low is not None
                and record.today_high < record.today_low):
            record.warnings.append(
                f"最高温({record.today_high})低于最低温({record.today_low})，疑似解析错位，已交换")
            day0 = record.week[0] if record.week else None
            if day0 is not None:
                day0.temp_high, day0.temp_low = day0.temp_low, day0.temp_high

    # ------------------------------------------------------------------
    # 多城市
    # ------------------------------------------------------------------
    def crawl_all(
        self,
        cities: Iterable[str],
        progress: Callable[[int, int, WeatherRecord], None] | None = None,
    ) -> list[WeatherRecord]:
        """并发抓取多个城市，返回按配置顺序排列的结果列表。"""
        city_list = list(dict.fromkeys(c for c in cities if c))
        total = len(city_list)
        results: dict[str, WeatherRecord] = {}

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(self.crawl_city, c): c for c in city_list}
            for done, fut in enumerate(as_completed(futures), 1):
                city = futures[fut]
                try:
                    rec = fut.result()
                except Exception as exc:  # noqa: BLE001  兜底，保证不中断
                    rec = WeatherRecord(city=city, region=config.region_of(city))
                    rec.warnings.append(f"未捕获异常：{exc}")
                results[city] = rec
                if progress:
                    progress(done, total, rec)

        # 保持与输入相同的顺序，便于输出稳定
        return [results[c] for c in city_list]

    def close(self) -> None:
        self.client.close()
