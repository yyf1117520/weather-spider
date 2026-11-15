# -*- coding: utf-8 -*-
"""
spider/parser.py —— HTML / JS 解析层
====================================================================
这是整个工具的核心。中国天气网的页面在近几年至少改版过三次，
早期版本的 ``div.todayLeft`` / ``div.todayRight`` 在当前页面上
**已经全部失效**。因此本模块不是"写死一条选择器"，而是实现了
"多策略级联 + 失败降级 + 异常兜底"的解析架构：

    ┌─ 策略 A：新版 #today 结构（2026 现行）
    ├─ 策略 B：新版 #today 的宽松结构（标签层级微调）
    ├─ 策略 C：经典 .todayLeft/.todayRight 结构（旧版页面，向后兼容）
    └─ 策略 D：#7d 七日益预报首日（最后的兜底）

任何一个策略成功即"早退"（early-exit），全部失败则返回带 warnings 的
空对象而不是抛异常——让上层可以选择"跳过该城市"继续跑完其余城市。

同时，本模块还从页内 ``<script>`` 中抽取两份 JSON：
    * ``hour3data``      —— 未来 3 小时粒度的预报序列
    * ``observe24h_data``—— 过去 24 小时逐时实况（温度/湿度/AQI/风向）
这两份数据藏在 JS 里，用正则 + 括号配平的方式提取，比用 BeautifulSoup
解析 <script> 文本更可靠。
"""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from .models import (
    DayForecast,
    Hour3Forecast,
    HourObs,
    PeriodForecast,
    TodayForecast,
    to_float,
    to_int,
)

# 解析策略名称常量：写进 WeatherRecord.parse_strategy，便于统计哪条路径最常用
STRATEGY_NEW = "A:新版#today"
STRATEGY_NEW_LOOSE = "B:新版#today宽松"
STRATEGY_CLASSIC = "C:经典todayLeft/Right"
STRATEGY_7D = "D:#7d首日兜底"


# ===========================================================================
# 通用小工具
# ===========================================================================
def clean(text: Any) -> str:
    """压缩空白、去掉不可见字符，返回干净的字符串。"""
    if text is None:
        return ""
    s = str(text).replace("\xa0", " ").replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def text_of(node) -> str:
    """安全取节点文本。"""
    if node is None:
        return ""
    return clean(node.get_text(" ", strip=True))


def extract_js_object(html: str, var_name: str) -> dict | None:
    """从 HTML 内嵌脚本中提取 ``var <var_name> = {...};`` 的 JSON 对象。

    不用贪婪正则 ``\\{.*\\}``：页面里可能有多个对象，贪婪匹配会跨过
    多个 script 标签导致解析失败。这里用"括号配平 + 字符串状态机"精确截取。
    """
    m = re.search(r"var\s+%s\s*=\s*" % re.escape(var_name), html)
    if not m:
        return None
    i = m.end()
    if i >= len(html) or html[i] != "{":
        return None

    depth = 0
    in_str = False
    quote = ""
    escape = False
    start = i
    for j in range(i, len(html)):
        ch = html[j]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_str = False
            continue
        if ch in "\"'":
            in_str = True
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = html[start:j + 1]
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    # 少数情况下含非法转义，退化为不严格解析
                    try:
                        return json.loads(raw.replace("\\'", "'"))
                    except json.JSONDecodeError:
                        return None
    return None


# ===========================================================================
# 解析器主体
# ===========================================================================
class WeatherParser:
    """把一页 HTML 变成结构化对象。所有方法都不抛异常。"""

    # ------------------------------------------------------------------
    # 城市名
    # ------------------------------------------------------------------
    @staticmethod
    def parse_city_name(html: str, soup: BeautifulSoup | None = None,
                        expect: str = "") -> str:
        """三级回退取城市名：<title> → 面包屑 → 实况 JSON。"""
        m = re.search(r"<title>\s*(.*?)\s*天气预报", html, re.S)
        if m:
            name = clean(m.group(1))
            if name:
                return name

        if soup is not None:
            crumbs = soup.select_one(".crumbs")
            if crumbs:
                links = [clean(a.get_text()) for a in crumbs.find_all("a")]
                links = [x for x in links if x and x != "全国"]
                if links:
                    return links[0]

        obs = extract_js_object(html, "observe24h_data")
        if obs:
            name = clean(obs.get("od", {}).get("od1", ""))
            if name:
                return name

        return expect

    # ------------------------------------------------------------------
    # 更新时间
    # ------------------------------------------------------------------
    @staticmethod
    def parse_update_time(soup: BeautifulSoup) -> str:
        """优先取"预报更新时间"，没有则退回"发布时分"。"""
        node = soup.find("input", id="fc_24h_internal_update_time")
        if node and node.get("value"):
            return clean(node["value"])
        node = soup.find("input", id="update_time")
        if node and node.get("value"):
            return clean(node["value"])
        node = soup.find("input", id="fc_3h_internal_update_time")
        if node and node.get("value"):
            return clean(node["value"])
        return ""

    @staticmethod
    def parse_summary(soup: BeautifulSoup) -> str:
        node = soup.find("input", id="hidden_title")
        return clean(node.get("value")) if node and node.get("value") else ""

    # ------------------------------------------------------------------
    # 单时段（白天/夜间）元素抽取
    # ------------------------------------------------------------------
    @classmethod
    def _period_from_li(cls, li, label: str = "") -> PeriodForecast | None:
        """从新版 ``#today`` 的 <li> 中抽出一个时段预报。

        对应结构（2026 版）::

            <li>
              <h1>15日夜间</h1>
              <big class="jpg80 n07"></big>       <- 图标代码在第二个 class
              <p class="wea" title="小雨">小雨</p>
              <p class="tem"><span>4</span><em>°C</em></p>
              <p class="win"><i class="E"></i><span title="东风">&lt;3级</span></p>
              <p class="sun sunDown"><i></i><span>日落 16:58</span></p>
              <div class="sky"><span class="txt lv3">天空阴沉</span></div>
            </li>
        """
        if li is None:
            return None
        period = PeriodForecast()

        h1 = li.find("h1")
        period.label = label or text_of(h1)

        # --- 天气现象：title 属性最干净，文本作备选 ---
        wea = li.find("p", class_="wea")
        if wea:
            period.weather = clean(wea.get("title")) or text_of(wea)

        # --- 温度：新版是 span(数值) + em(单位) ---
        tem = li.find("p", class_="tem")
        if tem:
            span = tem.find("span")
            period.temp = to_int(text_of(span)) if span else to_int(text_of(tem))

        # --- 风向风力 ---
        win = li.find("p", class_="win")
        if win:
            s = win.find("span")
            if s is not None:
                period.wind_dir = clean(s.get("title")) or ""
                period.wind_level = text_of(s)
            if not period.wind_level:
                # 部分版本把风力写在 <i> 里
                period.wind_level = text_of(win.find("i"))
            if not period.wind_dir:
                i = win.find("i")
                if i and i.get("class"):
                    period.wind_dir = i["class"][0] + "风"

        # --- 日出日落 ---
        sun = li.find("p", class_="sun")
        if sun:
            period.sun_time = text_of(sun)

        # --- 天空状况 ---
        sky = li.find("div", class_="sky")
        if sky:
            txt = sky.find("span", class_="txt")
            period.sky = text_of(txt)

        # --- 图标代码：<big class="jpg80 n07"> 取第二个 class ---
        big = li.find("big")
        if big and big.get("class"):
            for c in big["class"]:
                if re.fullmatch(r"[dn]\d{2}", c):
                    period.icon = c
                    break

        # 完全空白的时段视为解析失败
        if not period.weather and period.temp is None:
            return None
        return period

    # ------------------------------------------------------------------
    # 今日预报（策略级联）
    # ------------------------------------------------------------------
    @classmethod
    def parse_today(cls, html: str, soup: BeautifulSoup,
                    warnings: list[str] | None = None) -> tuple[TodayForecast, str]:
        """解析"今天"板块，返回 (TodayForecast, 命中的策略名)。"""
        warnings = warnings if warnings is not None else []
        today = TodayForecast(
            update_time=cls.parse_update_time(soup),
            summary=cls.parse_summary(soup),
        )

        # ---------- 策略 A：新版 #today div.t > ul > li ----------
        box = soup.find(id="today")
        if box is not None:
            t_div = box.find("div", class_="t")
            lis = (t_div or box).find_all("li", recursive=True)
            periods = [p for p in (cls._period_from_li(li) for li in lis) if p]
            if len(periods) >= 2:
                today.periods = periods[:2]
                return today, STRATEGY_NEW

        # ---------- 策略 B：#today 内任意 li（层级变动时的宽松匹配） ----------
        if box is not None:
            periods = []
            for li in box.find_all("li"):
                p = cls._period_from_li(li)
                if p:
                    periods.append(p)
            if periods:
                today.periods = periods[:2]
                if len(periods) >= 1:
                    return today, STRATEGY_NEW_LOOSE

        # ---------- 策略 C：经典 .todayLeft / .todayRight（旧版页面） ----------
        right = soup.find("div", class_="todayRight")
        if right is not None:
            periods = []
            # 经典结构：<ul><li class="t1"> ... <li class="t2">
            for li in right.find_all("li"):
                p = cls._period_from_li(li)
                if p:
                    periods.append(p)
            if not periods:
                # 经典结构下天气/温度/风是平铺的兄弟 div
                p = PeriodForecast(label="白天")
                tem = right.find("div", class_="tem")
                wea = right.find("div", class_="wea")
                win = right.find("div", class_="win")
                if tem:
                    p.temp = to_int(text_of(tem))
                if wea:
                    p.weather = clean(wea.get("title")) or text_of(wea)
                if win:
                    p.wind_dir = clean(win.get("title")) or ""
                    p.wind_level = text_of(win).replace("\n", " ")
                if p.temp is not None or p.weather:
                    periods.append(p)
            if periods:
                left = soup.find("div", class_="todayLeft")
                today.periods = periods[:2]
                cls._city_from_classic(left, today)
                return today, STRATEGY_CLASSIC

        # ---------- 策略 D：#7d 首日兜底 ----------
        week_box = soup.find(id="7d")
        if week_box is not None:
            lis = week_box.find_all("li")
            if lis:
                p = cls._period_from_week_li(lis[0])
                if p:
                    today.periods = [p]
                    return today, STRATEGY_7D

        warnings.append("未能解析出今日白天/夜间预报")
        return today, ""

    @staticmethod
    def _city_from_classic(left, today: TodayForecast) -> None:
        """经典结构里城市名写在 .todayLeft h3 中，这里仅作占位（不覆盖最终城市名）。"""
        return None

    # ------------------------------------------------------------------
    # 7 日预报
    # ------------------------------------------------------------------
    @classmethod
    def _period_from_week_li(cls, li) -> PeriodForecast | None:
        """把 7 日预报的某一天降级成"一个时段"，用于策略 D 兜底。"""
        day = cls._day_from_week_li(li)
        if day is None:
            return None
        return PeriodForecast(
            label=day.weekday or day.date_label,
            weather=day.weather_day,
            temp=day.temp_high if day.temp_high is not None else day.temp_low,
            wind_dir=day.wind_dir,
            wind_level=day.wind_level,
            icon=day.icon_day,
        )

    @classmethod
    def _day_from_week_li(cls, li) -> DayForecast | None:
        """解析 7 日预报中的一天。

        对应结构（2026 版）::

            <li class="sky skyid lv3 on">
              <h1>15日（今天）</h1>
              <big class="png40 d02"></big>          <- 白天图标
              <big class="png40 n01"></big>          <- 夜间图标
              <p class="wea" title="阴转多云">阴转多云</p>
              <p class="tem"><span>8℃</span>/<i>2℃</i></p>
              <p class="win"><em><span class="E" title="东风"></span></em><i>&lt;3级</i></p>
            </li>
        """
        if li is None:
            return None
        day = DayForecast()

        # --- 标题："15日（今天）" ---
        h1 = li.find("h1")
        title = text_of(h1)
        m = re.match(r"(\d{1,2}日)\s*[（(]?(.*?)[）)]?$", title)
        if m:
            day.date_label = m.group(1)
            day.weekday = m.group(2)
        else:
            day.date_label = title

        # --- 天气：可能是 "阴转多云"，拆成白天/夜间 ---
        wea = li.find("p", class_="wea")
        if wea:
            w = clean(wea.get("title")) or text_of(wea)
            day.weather_day = w
            if "转" in w:
                parts = [x for x in w.split("转") if x]
                if len(parts) >= 2:
                    day.weather_day, day.weather_night = parts[0], parts[1]

        # --- 温度：<span>最高</span>/<i>最低</i>，只给一个元素时按标签判断 ---
        tem = li.find("p", class_="tem")
        if tem:
            span = tem.find("span")
            itag = tem.find("i")
            if span is not None:
                day.temp_high = to_int(text_of(span))
            if itag is not None:
                day.temp_low = to_int(text_of(itag))
            if span is None and itag is None:
                day.temp_high = to_int(text_of(tem))

        # --- 风向风力：可能有两个（转向前后） ---
        win = li.find("p", class_="win")
        if win:
            dirs = [clean(s.get("title")) for s in win.find_all("span") if s.get("title")]
            day.wind_dir = clean("转".join(dict.fromkeys(dirs))) if dirs else ""
            itag = win.find("i")
            day.wind_level = text_of(itag) if itag is not None else ""

        # --- 图标：两个 <big class="png40 xxx">，分别对应白天/夜间 ---
        codes = []
        for big in li.find_all("big"):
            for c in (big.get("class") or []):
                if re.fullmatch(r"[dn]\d{2}", c):
                    codes.append(c)
                    break
        day_codes = [c for c in codes if c.startswith("d")]
        night_codes = [c for c in codes if c.startswith("n")]
        day.icon_day = day_codes[0] if day_codes else ""
        day.icon_night = night_codes[0] if night_codes else ""
        # 傍晚只有夜间图标时，白天天气沿用夜间图标所属现象
        if not codes:
            day.icon_day = ""

        # --- 天空等级：li 的 class 中 lv1~lv4 ---
        for c in (li.get("class") or []):
            if re.fullmatch(r"lv[1-4]", c):
                day.sky_level = c
                break

        if not day.date_label and day.temp_high is None:
            return None
        return day

    @classmethod
    def parse_week(cls, html: str, soup: BeautifulSoup,
                   warnings: list[str] | None = None) -> list[DayForecast]:
        """解析 7 日预报列表。"""
        warnings = warnings if warnings is not None else []
        days: list[DayForecast] = []

        box = soup.find(id="7d")
        lis = []
        if box is not None:
            ul = box.find("ul", class_="t") or box.find("ul")
            if ul is not None:
                lis = ul.find_all("li", recursive=False)
            if not lis:
                lis = box.find_all("li")
        if not lis:
            # 宽松兜底：整页里 class 含 sky 的 li
            lis = soup.select("li.sky")

        for li in lis:
            d = cls._day_from_week_li(li)
            if d is not None:
                days.append(d)

        if not days:
            warnings.append("未能解析出 7 日预报")
        return days[:7]

    # ------------------------------------------------------------------
    # 24 小时实况（页内 JSON）
    # ------------------------------------------------------------------
    @staticmethod
    def parse_obs24(html: str) -> list[HourObs]:
        """解析 ``var observe24h_data = {"od": {...}}``。

        字段含义（对照站点接口反推并交叉验证）::

            od0  观测时间戳，如 202611151800
            od1  城市名称
            od21 小时      od22 温度(℃)      od23 风向角度
            od24 风向      od25 风力等级      od26 降水量(mm)
            od27 相对湿度(%)                 od28 空气质量指数 AQI
        """
        data = extract_js_object(html, "observe24h_data")
        if not data:
            return []
        od = data.get("od") or {}
        rows = od.get("od2") or []
        result: list[HourObs] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            result.append(HourObs(
                hour=clean(r.get("od21")),
                temp=to_float(r.get("od22")),
                wind_degree=to_float(r.get("od23")),
                wind_dir=clean(r.get("od24")),
                wind_level=clean(r.get("od25")),
                rain=to_float(r.get("od26")),
                humidity=to_float(r.get("od27")),
                aqi=to_float(r.get("od28")),
            ))
        return result

    @staticmethod
    def parse_obs_meta(html: str) -> dict[str, str]:
        """实况的元信息：城市名与观测时间。"""
        data = extract_js_object(html, "observe24h_data")
        if not data:
            return {}
        od = data.get("od") or {}
        return {"name": clean(od.get("od1")), "time": clean(od.get("od0"))}

    # ------------------------------------------------------------------
    # 3 小时粒度预报（页内 JSON）
    # ------------------------------------------------------------------
    @staticmethod
    def parse_hour3(html: str) -> tuple[list[Hour3Forecast], list[Hour3Forecast]]:
        """解析 ``var hour3data``。

        返回 (未来 24 小时, 未来 7 天)。每条字符串形如::

            "15日23时,n07,小雨,5℃,东风,<3级,0"
             时间      图标 天气  温度  风向 风力 昼夜标记(1=白天)

        JSON 结构::

            {"1d": [str, ...], "23d": [[str,...],[...]], "7d": [[str,...],...]}
        """
        data = extract_js_object(html, "hour3data")
        if not data:
            return [], []

        def to_obj(s: str) -> Hour3Forecast | None:
            parts = str(s).split(",")
            if len(parts) < 4:
                return None
            obj = Hour3Forecast(
                time_label=clean(parts[0]),
                icon=clean(parts[1]) if len(parts) > 1 else "",
                weather=clean(parts[2]) if len(parts) > 2 else "",
                temp=to_int(parts[3]) if len(parts) > 3 else None,
                wind_dir=clean(parts[4]) if len(parts) > 4 else "",
                wind_level=clean(parts[5]) if len(parts) > 5 else "",
            )
            if len(parts) > 6:
                obj.is_day = to_int(parts[6]) or 0
            return obj

        # 未来 24 小时
        next24: list[Hour3Forecast] = []
        for s in data.get("1d") or []:
            o = to_obj(s)
            if o:
                next24.append(o)

        # 未来 7 天（按天分组的二维数组，展平）
        week: list[Hour3Forecast] = []
        for group in data.get("7d") or []:
            if isinstance(group, list):
                for s in group:
                    o = to_obj(s)
                    if o:
                        week.append(o)
            else:
                o = to_obj(group)
                if o:
                    week.append(o)

        return next24, week

    # ------------------------------------------------------------------
    # 一站式入口
    # ------------------------------------------------------------------
    @classmethod
    def parse_weather_info_simple(cls, html: str) -> dict[str, Any]:
        """简化版 ``parse_weather_info``（返回扁平字典）。

        保留这个"简化 API"有两个用处：
            1. 提供最简可用接口，便于二次开发时快速接入；
            2. 单元测试中作为"最小可用契约"，只要 4 个关键字段即可判定成功。
        """
        soup = BeautifulSoup(html, "lxml")
        warnings: list[str] = []
        today, _ = cls.parse_today(html, soup, warnings)
        period = today.day or (today.periods[0] if today.periods else None)
        return {
            "city": cls.parse_city_name(html, soup),
            "temperature": period.temp if period else None,
            "weather": period.weather if period else "",
            "wind": f"{period.wind_dir} {period.wind_level}".strip() if period else "",
        }
