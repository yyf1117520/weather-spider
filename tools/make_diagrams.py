# -*- coding: utf-8 -*-
"""
tools/make_diagrams.py —— 生成报告用的示意图
====================================================================
用 matplotlib 画两张"结构类"示意图（它们不是数据图，而是设计图）：

    * 图 A：系统分层架构图  —— 展示四层结构与模块依赖
    * 图 B：单城市数据流图  —— 展示一次抓取从 URL 到入库的完整路径

之所以用代码画而不是截图，是因为矢量风格的示意图更清晰、可复现，
且配色与其余数据图表保持一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#1F2733"
INK2 = "#5A6472"
GRID = "#CBD2DC"


def box(ax, x, y, w, h, title, sub="", fc="#FFFFFF", ec="#3D7BF7", tc=None, fs=11):
    patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.018",
                           linewidth=1.6, edgecolor=ec, facecolor=fc, zorder=3)
    ax.add_patch(patch)
    color = tc or INK
    if sub:
        ax.text(x + w / 2, y + h * 0.63, title, ha="center", va="center",
                fontsize=fs, fontweight="bold", color=color, zorder=4)
        ax.text(x + w / 2, y + h * 0.28, sub, ha="center", va="center",
                fontsize=fs - 2.6, color=INK2, zorder=4)
    else:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center",
                fontsize=fs, fontweight="bold", color=color, zorder=4)


def arrow(ax, p1, p2, color="#8A94A6", style="-|>", lw=1.5, ls="-"):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle=style, mutation_scale=13,
                                 linewidth=lw, color=color, linestyle=ls,
                                 shrinkA=2, shrinkB=2, zorder=2))


# ---------------------------------------------------------------------------
# 图 A：分层架构
# ---------------------------------------------------------------------------
def draw_architecture() -> Path:
    fig, ax = plt.subplots(figsize=(10.6, 6.6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # 四条横向分层带
    layers = [
        (0.795, "应用层 / 表现层", "#EEF4FF", "#C9DBFF"),
        (0.585, "业务层（统计·图表·看板）", "#FFF3EC", "#FFD9C4"),
        (0.375, "解析层（HTML / 内嵌 JSON）", "#EFFAF3", "#C6EBD6"),
        (0.165, "采集层（HTTP 请求）", "#F4F1FB", "#DCD3F0"),
    ]
    for y, name, fc, ec in layers:
        band = FancyBboxPatch((0.02, y), 0.96, 0.163,
                              boxstyle="round,pad=0.004,rounding_size=0.012",
                              linewidth=1.2, edgecolor=ec, facecolor=fc, zorder=1)
        ax.add_patch(band)
        ax.text(0.033, y + 0.140, name, ha="left", va="center",
                fontsize=10, color=INK2, fontweight="bold", zorder=5)

    # 应用层
    box(ax, 0.045, 0.812, 0.20, 0.098, "命令行 (main.py)", "argparse · 进度 · 汇总输出",
        ec="#3D7BF7", fs=11)
    box(ax, 0.275, 0.812, 0.20, 0.098, "数据导出", "JSON · CSV · Excel", ec="#3D7BF7", fs=11)
    box(ax, 0.505, 0.812, 0.20, 0.098, "交互式看板", "ECharts 单文件 HTML", ec="#3D7BF7", fs=11)
    box(ax, 0.735, 0.812, 0.23, 0.098, "静态图表", "matplotlib 8 张 PNG", ec="#3D7BF7", fs=11)

    # 业务层
    box(ax, 0.045, 0.602, 0.29, 0.098, "analyzer（统计分析）",
        "排行 · 区域 · 天气分布 · AQI 分级", ec="#E8543F", fs=11)
    box(ax, 0.365, 0.602, 0.29, 0.098, "visualizer / dashboard",
        "图表与看板渲染", ec="#E8543F", fs=11)
    box(ax, 0.685, 0.602, 0.28, 0.098, "storage（持久化）",
        "JSON · CSV · Excel", ec="#E8543F", fs=11)

    # 解析层
    box(ax, 0.045, 0.392, 0.29, 0.098, "WeatherParser",
        "4 条策略级联 · 失败降级", ec="#3AA675", fs=11)
    box(ax, 0.365, 0.392, 0.29, 0.098, "extract_js_object",
        "括号配平抽取内嵌 JSON", ec="#3AA675", fs=11)
    box(ax, 0.685, 0.392, 0.28, 0.098, "models 数据模型",
        "dataclass · 派生指标", ec="#3AA675", fs=11)

    # 采集层
    box(ax, 0.045, 0.182, 0.29, 0.098, "WeatherHttpClient",
        "Session · UA 轮换 · 重试", ec="#7D6B9E", fs=11)
    box(ax, 0.365, 0.182, 0.29, 0.098, "缓存 / 限速 / robots",
        "TTL 缓存 · 随机延迟", ec="#7D6B9E", fs=11)
    box(ax, 0.685, 0.182, 0.28, 0.098, "pipeline（并发调度）",
        "ThreadPool · 失败隔离", ec="#7D6B9E", fs=11)

    # 数据源与产物
    box(ax, 0.30, 0.015, 0.40, 0.085,
        "中国天气网  weather1d / weather 页面",
        "HTML + 内嵌 JS 变量（hour3data / observe24h_data）",
        fc="#1F2733", ec="#1F2733", tc="#FFFFFF", fs=10.5)

    # 层间箭头
    arrow(ax, (0.19, 0.182), (0.19, 0.392))
    arrow(ax, (0.51, 0.182), (0.51, 0.392))
    arrow(ax, (0.825, 0.182), (0.825, 0.392))
    arrow(ax, (0.19, 0.392), (0.19, 0.602))
    arrow(ax, (0.825, 0.392), (0.825, 0.602))
    arrow(ax, (0.51, 0.602), (0.51, 0.812))
    arrow(ax, (0.19, 0.602), (0.19, 0.812))
    arrow(ax, (0.825, 0.602), (0.825, 0.812))
    arrow(ax, (0.50, 0.100), (0.19, 0.182), ls="--")
    arrow(ax, (0.50, 0.100), (0.51, 0.182), ls="--")

    ax.text(0.5, 0.995, "系统分层架构", ha="center", va="top",
            fontsize=15, fontweight="bold", color=INK)
    fig.text(0.99, 0.005, "实线：数据/控制流　虚线：数据来源",
             ha="right", va="bottom", fontsize=8.5, color="#8A94A6")
    path = OUT / "fig00_系统架构.png"
    fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# 图 B：单城市抓取数据流
# ---------------------------------------------------------------------------
def draw_dataflow() -> Path:
    fig, ax = plt.subplots(figsize=(10.6, 5.2))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    steps = [
        ("城市名\n→ 城市代码", "config 映射表"),
        ("构造 URL", "weather1d/weather"),
        ("HTTP GET", "Session + UA"),
        ("编码判定", "meta→utf-8"),
        ("策略级联解析", "A→B→C→D"),
        ("补全与清洗", "昼夜温度互补"),
        ("派生指标", "温差/天气/风力"),
        ("持久化", "JSON/CSV/XLSX"),
    ]
    n = len(steps)
    x0, w, gap = 0.012, 0.109, 0.012
    y = 0.56
    for i, (title, sub) in enumerate(steps):
        x = x0 + i * (w + gap)
        fc = "#F7FAFF" if i % 2 == 0 else "#FFFFFF"
        box(ax, x, y, w, 0.26, title, sub, fc=fc, ec="#3D7BF7", fs=9.2)
        if i < n - 1:
            arrow(ax, (x + w, y + 0.13), (x + w + gap, y + 0.13), lw=1.3)

    # 三条设计要点（放在下方，避免拥挤的连线）
    notes = [
        ("#E8A33D", "缓存命中", "TTL 内直接读本地 HTML，跳过网络请求"),
        ("#E8543F", "失败重试", "超时/5xx 按 1s→2s→4s 指数退避，最多 3 次"),
        ("#3AA675", "策略级联", "A→B→C→D 逐级尝试，命中即早退，全失败记警告"),
    ]
    for i, (color, tag, text) in enumerate(notes):
        ny = 0.34 - i * 0.115
        dot = FancyBboxPatch((0.05, ny + 0.012), 0.010, 0.030,
                             boxstyle="round,pad=0.001,rounding_size=0.004",
                             linewidth=0, facecolor=color, zorder=4)
        ax.add_patch(dot)
        ax.text(0.072, ny + 0.027, tag, ha="left", va="center",
                fontsize=10, fontweight="bold", color=color, zorder=4)
        ax.text(0.175, ny + 0.027, text, ha="left", va="center",
                fontsize=9.6, color=INK2, zorder=4)

    ax.text(0.5, 0.95, "单城市抓取数据流", ha="center", va="center",
            fontsize=15, fontweight="bold", color=INK)
    ax.text(0.5, 0.885, "并发执行 16 条这样的流水线；任一城市失败不影响其余城市",
            ha="center", va="center", fontsize=10, color=INK2)
    fig.text(0.99, 0.005, "图中 8 个环节与 spider/ 包内模块一一对应",
             ha="right", va="bottom", fontsize=8.5, color="#8A94A6")
    path = OUT / "fig00b_数据流.png"
    fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


if __name__ == "__main__":
    a = draw_architecture()
    b = draw_dataflow()
    print("OK", a.name, a.stat().st_size // 1024, "KB")
    print("OK", b.name, b.stat().st_size // 1024, "KB")
