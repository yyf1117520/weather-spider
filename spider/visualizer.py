# -*- coding: utf-8 -*-
"""
spider/visualizer.py —— 静态图表生成层（matplotlib）
====================================================================
为汇报与文档提供"图文并茂"的图片素材。共 8 张图，覆盖三个层次：

    单变量分布   —— 气温排行、天气现象构成
    多变量对比   —— 城市高低温分组柱、AQI 分级、区域雷达
    时间序列     —— 7 日气温趋势、24 小时实况双轴
    二维关系     —— 城市 × 日期 气温热力图

统一的美术规范（配色、字号、边距、来源脚注）写在 ``_setup`` 里，
保证 8 张图风格一致，放进同一份报告不会"花"。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import matplotlib
matplotlib.use("Agg")                      # 无界面后端，服务器/命令行也能出图
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch

import config
from .analyzer import aqi_level
from .models import WeatherRecord

# ---------------------------------------------------------------------------
# 美术规范
# ---------------------------------------------------------------------------
PALETTE = {
    "hot": "#E8543F",       # 高温 / 暖色
    "warm": "#F2A65A",
    "cold": "#3E7CB1",      # 低温 / 冷色
    "cool": "#7FB3D5",
    "green": "#4C9F70",
    "purple": "#7D6B9E",
    "grey": "#8A94A6",
    "grid": "#E6E9EF",
    "text": "#2B3440",
    "bg": "#FFFFFF",
}

# 天气现象 -> 颜色（与看板保持一致）
WEATHER_COLORS = {
    "晴": "#F5C542",
    "多云": "#8FB8DE",
    "阴": "#9AA5B1",
    "雨": "#4A78B5",
    "雪": "#B8D8E8",
    "雾霾": "#B08BB0",
    "大风": "#7FB3A8",
    "其他": "#C9C9C9",
    "未知": "#DDDDDD",
}


def _setup() -> None:
    """全局 rcParams：中文字体、字号、无负号乱码、无上右框线。"""
    plt.rcParams.update({
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "font.family": "sans-serif",
        "axes.unicode_minus": False,       # 负号正常显示
        "figure.facecolor": PALETTE["bg"],
        "axes.facecolor": PALETTE["bg"],
        "axes.edgecolor": "#CBD2DC",
        "axes.labelcolor": PALETTE["text"],
        "text.color": PALETTE["text"],
        "xtick.color": "#5A6472",
        "ytick.color": "#5A6472",
        "axes.grid": True,
        "grid.color": PALETTE["grid"],
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.size": 11,
        "axes.titlesize": 15,
        "figure.dpi": 100,
        "savefig.dpi": 160,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.25,
    })


def _footer(fig, text: str = "数据来源：中国天气网 www.weather.com.cn") -> None:
    """统一在右下角标明数据来源（放在坐标轴下方，避免压住刻度标签）。"""
    fig.text(0.99, -0.035, text, ha="right", va="top",
             fontsize=8.5, color=PALETTE["grey"])


def _int_ticks(ax, axis: str = "y") -> None:
    """温度轴强制整数刻度，避免出现 32.5 / 27.5 这类别扭的标签。"""
    from matplotlib.ticker import MaxNLocator
    if axis in ("y", "both"):
        ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=7))
    if axis in ("x", "both"):
        ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=8))


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=PALETTE["bg"])
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# 图表构建器
# ---------------------------------------------------------------------------
class ChartBuilder:
    """把抓取结果渲染成一组 PNG 图表。"""

    def __init__(self, output_dir: str | Path = config.FIG_DIR) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        _setup()
        self.figures: list[dict[str, str]] = []

    def _register(self, path: Path, number: int, title: str, desc: str) -> None:
        self.figures.append({
            "path": str(path),
            "number": f"图{number}",
            "title": title,
            "desc": desc,
        })

    # ------------------------------------------------------------------
    def build_all(self, records: Sequence[WeatherRecord],
                  result: dict[str, Any]) -> list[dict[str, str]]:
        """生成全部图表，返回 [{path, number, title, desc}, ...]。"""
        valid = [r for r in records if r.ok]
        if not valid:
            return []

        builders = [
            (self.fig_temperature_compare, "多城市今日气温对比"),
            (self.fig_temperature_ranking, "最高气温排行"),
            (self.fig_week_trend, "未来 7 天气温趋势"),
            (self.fig_hourly_observation, "24 小时实况曲线"),
            (self.fig_weather_pie, "天气现象构成"),
            (self.fig_aqi_bar, "空气质量指数对比"),
            (self.fig_region_radar, "分区域气温特征"),
            (self.fig_city_heatmap, "城市×日期气温热力图"),
        ]
        for idx, (fn, _name) in enumerate(builders, 1):
            try:
                path = fn(records, result)
                if path:
                    self._register(path, idx, fn.__doc__.strip().split("\n")[0], "")
            except Exception as exc:  # noqa: BLE001  单张图失败不影响其余
                print(f"  [图表] {fn.__name__} 生成失败：{exc}")
        return self.figures

    # ------------------------------------------------------------------
    # 图 1：多城市最高/最低气温分组柱状图
    # ------------------------------------------------------------------
    def fig_temperature_compare(self, records, result) -> Path | None:
        """多城市今日最高温 / 最低温分组柱状对比（按高温降序）。"""
        valid = [r for r in records if r.ok and r.today_high is not None]
        if not valid:
            return None
        valid = sorted(valid, key=lambda r: (r.today_high if r.today_high is not None else -99),
                       reverse=True)
        cities = [r.city for r in valid]
        highs = [r.today_high if r.today_high is not None else 0 for r in valid]
        lows = [r.today_low if r.today_low is not None else 0 for r in valid]

        fig, ax = plt.subplots(figsize=(max(9, len(cities) * 0.72), 5.2))
        x = np.arange(len(cities))
        w = 0.36
        b1 = ax.bar(x - w / 2, highs, w, label="最高气温", color=PALETTE["hot"],
                    edgecolor="white", linewidth=0.8, zorder=3)
        b2 = ax.bar(x + w / 2, lows, w, label="最低气温", color=PALETTE["cold"],
                    edgecolor="white", linewidth=0.8, zorder=3)

        # 数值标签放在柱顶（负温时放在柱底）
        for bars, vals in ((b1, highs), (b2, lows)):
            for rect, v in zip(bars, vals):
                y = rect.get_height()
                offset = 3 if y >= 0 else -3
                va = "bottom" if y >= 0 else "top"
                ax.annotate(f"{v}°", (rect.get_x() + rect.get_width() / 2, y),
                            textcoords="offset points", xytext=(0, offset),
                            ha="center", va=va, fontsize=9, color="#39424E")

        ax.axhline(0, color="#B0B8C4", linewidth=1)
        ax.set_xticks(x)
        ax.set_xticklabels(cities, rotation=45 if len(cities) > 10 else 0,
                           ha="right" if len(cities) > 10 else "center")
        ax.set_ylabel("温度（℃）")
        ax.set_title(f"多城市今日气温对比（{len(cities)} 城，按最高温降序）",
                     pad=14, fontweight="bold")
        ax.legend(frameon=False, ncol=2, loc="upper right")
        ax.margins(y=0.16)
        _int_ticks(ax)
        _footer(fig)
        return _save(fig, self.output_dir / "fig01_气温对比.png")

    # ------------------------------------------------------------------
    # 图 2：最高气温横向排行榜（渐变色）
    # ------------------------------------------------------------------
    def fig_temperature_ranking(self, records, result) -> Path | None:
        """最高气温排行榜（横向条形，颜色随温度由冷到暖渐变）。"""
        valid = sorted([r for r in records if r.ok and r.today_high is not None],
                       key=lambda r: r.today_high)
        if not valid:
            return None
        cities = [r.city for r in valid]
        temps = [r.today_high for r in valid]

        cmap = LinearSegmentedColormap.from_list(
            "temp", [PALETTE["cold"], PALETTE["cool"], PALETTE["warm"], PALETTE["hot"]])
        tmin, tmax = min(temps), max(temps)
        norm = [(t - tmin) / (tmax - tmin) if tmax > tmin else 0.5 for t in temps]
        colors = [cmap(n) for n in norm]

        fig, ax = plt.subplots(figsize=(9, max(4.2, len(cities) * 0.42)))
        bars = ax.barh(cities, temps, color=colors, edgecolor="white",
                       linewidth=1.0, height=0.68, zorder=3)
        for rect, t in zip(bars, temps):
            ax.text(rect.get_width() + (0.4 if t >= 0 else -0.4), rect.get_y() + rect.get_height() / 2,
                    f"{t}℃", va="center", ha="left" if t >= 0 else "right",
                    fontsize=10, fontweight="bold", color="#39424E")
        ax.axvline(0, color="#B0B8C4", linewidth=1)
        ax.set_xlabel("今日最高气温（℃）")
        ax.set_title("全国样本城市最高气温排行", pad=14, fontweight="bold")
        ax.grid(axis="y", visible=False)
        ax.margins(x=0.12)
        _footer(fig)
        return _save(fig, self.output_dir / "fig02_气温排行.png")

    # ------------------------------------------------------------------
    # 图 3：7 日气温趋势
    # ------------------------------------------------------------------
    def fig_week_trend(self, records, result) -> Path | None:
        """代表城市未来 7 日最高/最低气温趋势与温差带。"""
        valid = [r for r in records if r.ok and len(r.week) >= 3]
        if not valid:
            return None

        # 选气温跨度最大的 4 个城市，趋势差异最明显
        picks = sorted(valid, key=lambda r: (r.today_high or -99), reverse=True)
        picks = picks[:2] + [r for r in reversed(picks) if r not in picks[:2]][:2]
        seen, uniq = set(), []
        for r in picks:
            if r.city not in seen:
                seen.add(r.city)
                uniq.append(r)
        picks = uniq[:4]

        fig, axes = plt.subplots(1, len(picks), figsize=(4.5 * len(picks), 4.6),
                                 sharey=False)
        if len(picks) == 1:
            axes = [axes]
        for ax, rec in zip(axes, picks):
            labels = [d.date_label for d in rec.week]
            hi = [d.temp_high if d.temp_high is not None else np.nan for d in rec.week]
            lo = [d.temp_low if d.temp_low is not None else np.nan for d in rec.week]
            x = np.arange(len(labels))
            ax.fill_between(x, lo, hi, color=PALETTE["warm"], alpha=0.18,
                            label="昼夜温差带")
            ax.plot(x, hi, "-o", color=PALETTE["hot"], linewidth=2.2,
                    markersize=6, label="最高气温", zorder=3)
            ax.plot(x, lo, "-o", color=PALETTE["cold"], linewidth=2.2,
                    markersize=6, label="最低气温", zorder=3)
            for xi, v in zip(x, hi):
                if not np.isnan(v):
                    ax.annotate(f"{int(v)}", (xi, v), textcoords="offset points",
                                xytext=(0, 9), ha="center", fontsize=8.5,
                                color=PALETTE["hot"])
            for xi, v in zip(x, lo):
                if not np.isnan(v):
                    ax.annotate(f"{int(v)}", (xi, v), textcoords="offset points",
                                xytext=(0, -14), ha="center", fontsize=8.5,
                                color=PALETTE["cold"])
            ax.set_xticks(x)
            ax.set_xticklabels(labels, fontsize=9)
            ax.set_title(f"{rec.city}", fontsize=13, fontweight="bold")
            ax.set_ylabel("温度（℃）")
            ax.margins(y=0.22)
            _int_ticks(ax)
        axes[0].legend(frameon=False, fontsize=9, loc="upper left")
        fig.suptitle("代表城市未来 7 日气温趋势", fontsize=15, fontweight="bold", y=1.02)
        _footer(fig)
        return _save(fig, self.output_dir / "fig03_七日趋势.png")

    # ------------------------------------------------------------------
    # 图 4：24 小时实况双轴
    # ------------------------------------------------------------------
    def fig_hourly_observation(self, records, result) -> Path | None:
        """代表城市 24 小时温度/湿度实况双轴曲线。"""
        valid = [r for r in records if len(r.obs24) >= 8]
        if not valid:
            return None
        # 取"温度变化幅度最大"的城市，曲线最有看头
        rec = max(valid, key=lambda r: (
            max((o.temp for o in r.obs24 if o.temp is not None), default=0)
            - min((o.temp for o in r.obs24 if o.temp is not None), default=0)))
        # 页面按时间倒序返回，反转成时间正序；末尾与开头可能同为"18 时"，
        # 只保留最近 24 个整点，保证横轴标签唯一
        obs = list(reversed(rec.obs24))[-24:]
        hours = [f"{o.hour:>2}时" for o in obs]
        temps = [o.temp for o in obs]
        hums = [o.humidity for o in obs]

        fig, ax1 = plt.subplots(figsize=(10, 4.8))
        ax2 = ax1.twinx()

        ax1.plot(hours, temps, "-", color=PALETTE["hot"], linewidth=2.4,
                 marker="o", markersize=4.5, label="温度", zorder=3)
        ax1.fill_between(range(len(hours)), temps, min(t for t in temps if t is not None),
                         color=PALETTE["hot"], alpha=0.10)
        ax2.plot(hours, hums, "--", color=PALETTE["cold"], linewidth=1.9,
                 marker="s", markersize=3.6, label="相对湿度", zorder=3)

        ax1.set_xlabel("观测时刻（时）")
        ax1.set_ylabel("温度（℃）", color=PALETTE["hot"])
        ax2.set_ylabel("相对湿度（%）", color=PALETTE["cold"])
        ax2.grid(False)
        ax1.tick_params(axis="x", labelsize=9)
        ax1.set_xticks(range(len(hours)))
        ax1.set_xticklabels(hours, rotation=45, ha="right", fontsize=9)
        ax2.yaxis.set_major_locator(plt.MaxNLocator(integer=True, nbins=7))
        ax1.set_title(f"{rec.city} · 过去 24 小时实况（数据更新 {rec.updated_at}）",
                      pad=14, fontweight="bold")

        # 标注最高/最低温；图例位置根据峰值位置自适应，避免遮挡
        legend_loc = "upper right"
        if any(t is not None for t in temps):
            arr = [(i, t) for i, t in enumerate(temps) if t is not None]
            hi = max(arr, key=lambda z: z[1])
            lo = min(arr, key=lambda z: z[1])
            for (i, v), tag, color in ((hi, "最高", PALETTE["hot"]), (lo, "最低", PALETTE["cold"])):
                ax1.annotate(f"{tag} {v}℃", (i, v), textcoords="offset points",
                             xytext=(0, 14 if tag == "最高" else -20), ha="center",
                             fontsize=9, color=color, fontweight="bold")
            # 峰值落在右半区时把图例移到左侧
            if hi[0] > len(temps) * 0.55:
                legend_loc = "upper left"

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, frameon=False,
                   loc=legend_loc, ncol=2, fontsize=9.5)
        ax1.margins(y=0.20)
        _int_ticks(ax1)
        _footer(fig)
        return _save(fig, self.output_dir / "fig04_24小时实况.png")

    # ------------------------------------------------------------------
    # 图 5：天气现象环形图
    # ------------------------------------------------------------------
    def fig_weather_pie(self, records, result) -> Path | None:
        """样本城市天气现象构成（环形图 + 中心汇总）。"""
        groups = result.get("weather", {}).get("group", [])
        if not groups:
            return None
        names = [g["name"] for g in groups]
        values = [g["value"] for g in groups]
        colors = [WEATHER_COLORS.get(n, PALETTE["grey"]) for n in names]

        fig, ax = plt.subplots(figsize=(7.6, 5.6))
        wedges, _texts, autotexts = ax.pie(
            values, labels=None, colors=colors, autopct="%1.0f%%",
            startangle=90, counterclock=False,
            wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 2},
            pctdistance=0.79,
        )
        for t in autotexts:
            t.set_fontsize(10)
            t.set_color("#39424E")
            t.set_fontweight("bold")

        total = sum(values)
        ax.text(0, 0.08, str(total), ha="center", va="center",
                fontsize=30, fontweight="bold", color=PALETTE["text"])
        ax.text(0, -0.16, "城市·天气现象", ha="center", va="center",
                fontsize=10, color=PALETTE["grey"])

        legend_labels = [f"{n}  {v} 城" for n, v in zip(names, values)]
        ax.legend(wedges, legend_labels, loc="center left",
                  bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=10.5)
        ax.set_title("样本城市天气现象构成", pad=18, fontweight="bold")
        ax.set_aspect("equal")
        _footer(fig)
        return _save(fig, self.output_dir / "fig05_天气构成.png")

    # ------------------------------------------------------------------
    # 图 6：AQI 对比
    # ------------------------------------------------------------------
    def fig_aqi_bar(self, records, result) -> Path | None:
        """各城市空气质量指数（AQI）对比与分级阈值线。"""
        items = result.get("air", {}).get("items", [])
        if not items:
            return None
        items = sorted(items, key=lambda x: x["aqi"])
        cities = [x["city"] for x in items]
        aqis = [x["aqi"] for x in items]
        colors = [x["color"] for x in items]

        fig, ax = plt.subplots(figsize=(9, max(4.2, len(cities) * 0.40)))
        bars = ax.barh(cities, aqis, color=colors, edgecolor="#5A6472",
                       linewidth=0.7, height=0.66, zorder=3)
        for rect, v, x in zip(bars, aqis, items):
            ax.text(rect.get_width() + max(aqis) * 0.015,
                    rect.get_y() + rect.get_height() / 2,
                    f"{int(v)} {x['level']}", va="center", fontsize=9, color="#39424E")

        # 分级阈值参考线（标签放在底部，避免压住条形）
        ymin = -0.6
        for threshold, label in ((50, "优"), (100, "良"), (150, "轻度"), (200, "中度")):
            if max(aqis) > threshold:
                ax.axvline(threshold, color="#9AA5B1", linestyle=":", linewidth=1.2, zorder=1)
                ax.text(threshold, ymin + 0.05, f" {label}线 {threshold}",
                        fontsize=8, color=PALETTE["grey"], va="bottom", ha="left")

        legend = [Patch(facecolor=c, edgecolor="white", label=n)
                  for _, n, c in [
                      (50, "优", "#00b050"), (100, "良", "#e0c000"),
                      (150, "轻度污染", "#ed7d31"), (200, "中度污染", "#ff0000"),
                      (300, "重度污染", "#99004c")]]
        ax.legend(handles=legend, frameon=False, fontsize=9,
                  loc="lower right", title="空气质量等级", title_fontsize=9)
        ax.set_xlabel("空气质量指数 AQI（数值越大空气越差）")
        ax.set_title("样本城市空气质量指数对比", pad=14, fontweight="bold")
        ax.grid(axis="y", visible=False)
        ax.margins(x=0.16)
        _footer(fig)
        return _save(fig, self.output_dir / "fig06_空气质量.png")

    # ------------------------------------------------------------------
    # 图 7：区域雷达图
    # ------------------------------------------------------------------
    def fig_region_radar(self, records, result) -> Path | None:
        """七大区平均最高气温雷达图。"""
        regions = result.get("regions", [])
        if len(regions) < 3:
            return None
        labels = [r["region"] for r in regions]
        values = [r["avg_high"] for r in regions]

        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        angles += angles[:1]
        vals = values + values[:1]

        fig, ax = plt.subplots(figsize=(6.4, 5.8), subplot_kw={"polar": True})
        ax.plot(angles, vals, color=PALETTE["hot"], linewidth=2.2)
        ax.fill(angles, vals, color=PALETTE["hot"], alpha=0.18)
        ax.scatter(angles[:-1], values, color=PALETTE["hot"], s=42, zorder=4)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels([f"{l}\n{v}℃" for l, v in zip(labels, values)], fontsize=10)
        ax.set_title("分区域平均最高气温", pad=26, fontweight="bold")
        ax.grid(color=PALETTE["grid"])
        ax.set_facecolor("#FAFBFD")
        _footer(fig)
        return _save(fig, self.output_dir / "fig07_区域雷达.png")

    # ------------------------------------------------------------------
    # 图 8：城市 × 日期 热力图
    # ------------------------------------------------------------------
    def fig_city_heatmap(self, records, result) -> Path | None:
        """城市 × 日期 最高气温热力图（一眼看出冷暖格局）。"""
        valid = [r for r in records if r.ok and len(r.week) >= 3]
        if len(valid) < 2:
            return None
        n_days = max(len(r.week) for r in valid)
        cities = [r.city for r in valid]
        matrix = np.full((len(valid), n_days), np.nan)
        for i, rec in enumerate(valid):
            for j, d in enumerate(rec.week[:n_days]):
                if d.temp_high is not None:
                    matrix[i, j] = d.temp_high
        day_labels = [d.date_label for d in valid[0].week[:n_days]]

        fig, ax = plt.subplots(figsize=(max(8, n_days * 1.15), max(4.6, len(cities) * 0.42)))
        cmap = LinearSegmentedColormap.from_list(
            "t", ["#2C5F8A", "#5B9BD5", "#CFE3F2", "#FBE2C0", "#F2A65A", "#D64533"])
        im = ax.imshow(matrix, cmap=cmap, aspect="auto")

        ax.set_xticks(np.arange(n_days))
        ax.set_xticklabels(day_labels, fontsize=10)
        ax.set_yticks(np.arange(len(cities)))
        ax.set_yticklabels(cities, fontsize=10)
        ax.grid(False)

        # 单元格内标注温度：按色块亮度自动选深字/白字，保证对比度
        for i in range(len(cities)):
            for j in range(n_days):
                v = matrix[i, j]
                if np.isnan(v):
                    continue
                r, g, b, _a = cmap(im.norm(v))
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                ax.text(j, i, f"{int(v)}", ha="center", va="center", fontsize=9,
                        color="white" if lum < 0.55 else "#2B3440")

        cbar = fig.colorbar(im, ax=ax, pad=0.02, fraction=0.035)
        cbar.set_label("最高气温（℃）", fontsize=10)
        cbar.outline.set_visible(False)
        ax.set_title("城市×日期 最高气温热力图", pad=14, fontweight="bold")
        _footer(fig)
        return _save(fig, self.output_dir / "fig08_气温热力图.png")
