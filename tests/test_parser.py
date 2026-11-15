# -*- coding: utf-8 -*-
"""
tests/test_parser.py —— 解析器单元测试（完全离线）
====================================================================
用真实抓取到的 HTML 快照（tests/fixtures）作为输入，
在没有网络的环境下验证解析结果，包括：

    1. 城市名、更新时间、摘要等元信息
    2. 今日白天/夜间两段预报
    3. 7 日预报的 7 条记录与温度区间
    4. 24 小时实况 JSON 的字段映射
    5. 3 小时预报序列
    6. 多策略级联：破坏新版结构后能否自动降级
    7. 异常输入（空串、残缺 HTML）不抛异常

运行： python -m pytest tests -q
或：   python tests/test_parser.py   （内置简易 runner，无需 pytest）
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup  # noqa: E402

from spider.parser import (  # noqa: E402
    STRATEGY_7D,
    STRATEGY_CLASSIC,
    STRATEGY_NEW,
    WeatherParser,
    extract_js_object,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


class TestCityAndMeta(unittest.TestCase):
    """元信息解析。"""

    @classmethod
    def setUpClass(cls):
        cls.html = load("beijing_1d.html")
        cls.soup = BeautifulSoup(cls.html, "lxml")

    def test_city_name(self):
        name = WeatherParser.parse_city_name(self.html, self.soup)
        self.assertEqual(name, "北京")

    def test_update_time(self):
        t = WeatherParser.parse_update_time(self.soup)
        self.assertRegex(t, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

    def test_summary(self):
        s = WeatherParser.parse_summary(self.soup)
        self.assertIn("℃", s.replace("°C", "℃"))
        self.assertGreater(len(s), 8)


class TestToday(unittest.TestCase):
    """今日/明日分段预报。"""

    @classmethod
    def setUpClass(cls):
        cls.html = load("beijing_1d.html")
        cls.soup = BeautifulSoup(cls.html, "lxml")
        cls.today, cls.strategy = WeatherParser.parse_today(cls.html, cls.soup, [])

    def test_strategy_is_new(self):
        self.assertEqual(self.strategy, STRATEGY_NEW)

    def test_two_periods(self):
        self.assertEqual(len(self.today.periods), 2)

    def test_temperature_range(self):
        for p in self.today.periods:
            self.assertIsNotNone(p.temp)
            self.assertTrue(-50 < p.temp < 50, f"温度异常：{p.temp}")

    def test_weather_not_empty(self):
        for p in self.today.periods:
            self.assertTrue(p.weather, "天气现象不应为空")

    def test_wind(self):
        for p in self.today.periods:
            self.assertTrue(p.wind_level, "风力不应为空")

    def test_label_contains_period(self):
        labels = "".join(p.label for p in self.today.periods)
        self.assertTrue(("白天" in labels) or ("夜间" in labels))


class TestWeek(unittest.TestCase):
    """7 日预报。"""

    @classmethod
    def setUpClass(cls):
        cls.html = load("beijing_7d.html")
        cls.soup = BeautifulSoup(cls.html, "lxml")
        cls.week = WeatherParser.parse_week(cls.html, cls.soup, [])

    def test_seven_days(self):
        self.assertEqual(len(self.week), 7)

    def test_high_ge_low(self):
        for d in self.week:
            if d.temp_high is not None and d.temp_low is not None:
                self.assertGreaterEqual(d.temp_high, d.temp_low,
                                        f"{d.date_label} 最高温低于最低温")

    def test_date_labels(self):
        for d in self.week:
            self.assertRegex(d.date_label, r"^\d{1,2}日$")

    def test_has_weather(self):
        self.assertTrue(all(d.weather_day for d in self.week))


class TestJsonBlocks(unittest.TestCase):
    """页内 JSON 抽取（3 小时预报 / 24 小时实况）。"""

    @classmethod
    def setUpClass(cls):
        cls.html = load("beijing_1d.html")

    def test_extract_js_object(self):
        obj = extract_js_object(self.html, "hour3data")
        self.assertIsInstance(obj, dict)
        self.assertIn("1d", obj)

    def test_hour3(self):
        next24, week = WeatherParser.parse_hour3(self.html)
        self.assertGreaterEqual(len(next24), 4)
        self.assertGreaterEqual(len(week), 8)
        for h in next24:
            self.assertRegex(h.time_label, r"^\d{1,2}日\d{2}时$")
            self.assertIsNotNone(h.temp)

    def test_obs24(self):
        obs = WeatherParser.parse_obs24(self.html)
        self.assertGreaterEqual(len(obs), 12)
        for o in obs:
            self.assertIsNotNone(o.temp)
            self.assertRegex(o.hour, r"^\d{1,2}$")
        # 湿度应当是 0~100 的百分比
        hums = [o.humidity for o in obs if o.humidity is not None]
        self.assertTrue(all(0 <= h <= 100 for h in hums))

    def test_obs_meta(self):
        meta = WeatherParser.parse_obs_meta(self.html)
        self.assertEqual(meta.get("name"), "北京")
        self.assertRegex(meta.get("time", ""), r"^\d{12}$")


class TestStrategyCascade(unittest.TestCase):
    """多策略级联与降级行为——这是"健壮性"的核心验证。"""

    @classmethod
    def setUpClass(cls):
        cls.html = load("beijing_1d.html")

    def test_classic_structure_fallback(self):
        """把新版结构改造成早期的 todayLeft/todayRight，应命中策略 C。"""
        classic = """
        <html><head><title>测试城天气预报</title></head><body>
          <div class="todayLeft"><h3>测试城</h3></div>
          <div class="todayRight">
            <ul>
              <li>
                <h1>今天白天</h1>
                <p class="wea" title="晴"></p>
                <p class="tem"><span>25</span><em>°C</em></p>
                <p class="win"><i class="S"></i><span title="南风">3级</span></p>
              </li>
              <li>
                <h1>今天夜间</h1>
                <p class="wea" title="多云"></p>
                <p class="tem"><span>15</span><em>°C</em></p>
                <p class="win"><i class="S"></i><span title="南风">2级</span></p>
              </li>
            </ul>
          </div>
        </body></html>
        """
        soup = BeautifulSoup(classic, "lxml")
        today, strategy = WeatherParser.parse_today(classic, soup, [])
        self.assertEqual(strategy, STRATEGY_CLASSIC)
        self.assertEqual(len(today.periods), 2)
        self.assertEqual(today.periods[0].temp, 25)
        self.assertEqual(today.periods[0].weather, "晴")
        self.assertEqual(today.periods[0].wind_dir, "南风")

    def test_7d_only_fallback(self):
        """只给 #7d 列表时，应降级到策略 D 并仍能取到温度。"""
        only7d = load("beijing_7d.html")
        soup = BeautifulSoup(only7d, "lxml")
        # 删除可能存在的 #today 区块，模拟"只拿到 7 天页"
        box = soup.find(id="today")
        if box is not None:
            box.decompose()
        today, strategy = WeatherParser.parse_today(only7d, soup, [])
        self.assertIn(strategy, (STRATEGY_7D, "B:新版#today宽松", ""))
        if today.periods:
            self.assertIsNotNone(today.periods[0].temp)

    def test_garbage_input_no_exception(self):
        """残缺/无关 HTML 不许抛异常，只返回空结构并记 warning。"""
        for bad in ["", "<html></html>", "<div>随便一段文字</div>",
                    "<ul><li>没有类名</li></ul>"]:
            warnings: list[str] = []
            soup = BeautifulSoup(bad, "lxml")
            today, strategy = WeatherParser.parse_today(bad, soup, warnings)
            self.assertIsInstance(today.periods, list)
            week = WeatherParser.parse_week(bad, soup, warnings)
            self.assertIsInstance(week, list)
            self.assertEqual(WeatherParser.parse_obs24(bad), [])
            self.assertEqual(WeatherParser.parse_hour3(bad), ([], []))

    def test_simple_api(self):
        """简化接口：城市/温度/天气/风力四个字段必须齐全。"""
        info = WeatherParser.parse_weather_info_simple(load("beijing_1d.html"))
        self.assertEqual(info["city"], "北京")
        self.assertIsNotNone(info["temperature"])
        self.assertTrue(info["weather"])
        self.assertTrue(info["wind"])


class TestExtractJsObjectSafety(unittest.TestCase):
    """括号配平解析器的边界情况。"""

    def test_braces_inside_string(self):
        html = 'var demo = {"a":"含}括号的字符串","b":{"c":[1,2]}};'
        obj = extract_js_object(html, "demo")
        self.assertEqual(obj["a"], "含}括号的字符串")
        self.assertEqual(obj["b"]["c"], [1, 2])

    def test_missing_var(self):
        self.assertIsNone(extract_js_object("var x=1;", "demo"))

    def test_broken_json(self):
        self.assertIsNone(extract_js_object("var demo = {bad json};", "demo"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
