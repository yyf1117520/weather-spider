# -*- coding: utf-8 -*-
"""
main.py —— 命令行入口 / 总控
====================================================================
一次运行完成：抓取 → 解析 → 结构化输出 → 统计分析 → 持久化，
并可选择继续生成图表与可视化看板。

用法示例::

    python main.py                          # 默认 16 个城市
    python main.py --cities 北京 上海 广州    # 指定城市
    python main.py --all                    # 全部 36 个城市
    python main.py --fresh                  # 忽略缓存，强制联网取最新
    python main.py --offline                # 只用本地缓存（断网也能演示）
    python main.py --charts --dashboard     # 同时产出图表与看板
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 保证以 `python main.py` 与 `python -m` 两种方式都能 import 到本目录下的包
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from spider import analyzer, storage, ui
from spider.http_client import WeatherHttpClient
from spider.pipeline import WeatherCrawler


# ---------------------------------------------------------------------------
# 参数
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="中国天气网多城市天气数据采集与可视化系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--cities", nargs="+", metavar="城市",
                   help="指定要抓取的城市名（可多个）")
    g.add_argument("--all", action="store_true", help="抓取代码表内全部城市")
    g.add_argument("--top", type=int, metavar="N", help="抓取前 N 个城市")

    p.add_argument("--workers", type=int, default=config.MAX_WORKERS,
                   help=f"并发线程数（默认 {config.MAX_WORKERS}）")
    p.add_argument("--delay", type=float, default=config.REQUEST_DELAY,
                   help=f"请求间隔秒数（默认 {config.REQUEST_DELAY}）")
    p.add_argument("--timeout", type=float, default=config.TIMEOUT[1],
                   help="单次请求读取超时秒数")
    p.add_argument("--fresh", action="store_true", help="忽略缓存，强制联网")
    p.add_argument("--offline", action="store_true", help="只用本地缓存，不联网")
    p.add_argument("--outdir", default=str(config.DATA_DIR), help="结果输出目录")
    p.add_argument("--no-color", action="store_true", help="关闭彩色输出")
    p.add_argument("--quiet", action="store_true", help="精简输出（只打印表格）")
    p.add_argument("--brief", action="store_true",
                   help="简要模式：省略 TOP5 排行表与区域条形图，其余照常输出")
    p.add_argument("--charts", action="store_true", help="生成 matplotlib 图表")
    p.add_argument("--dashboard", action="store_true", help="生成 HTML 可视化看板")
    p.add_argument("--export-xlsx", action="store_true", help="额外导出 Excel")
    return p


def resolve_cities(args) -> list[str]:
    if args.cities:
        # 允许用户传中文名，也允许直接传 9 位代码
        result = []
        for c in args.cities:
            if c.isdigit() and len(c) == 9:
                name = next((k for k, v in config.CITY_CODES.items() if v == c), c)
                result.append(name)
            else:
                result.append(c)
        return result
    if args.all:
        return list(config.CITY_CODES.keys())
    if args.top:
        # 优先取默认城市表（覆盖七大区域），不足时再补其余城市
        ordered = list(dict.fromkeys(list(config.DEFAULT_CITIES)
                                     + list(config.CITY_CODES.keys())))
        return ordered[: args.top]
    return list(config.DEFAULT_CITIES)


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
def print_banner(total: int, args) -> None:
    brief = getattr(args, "brief", False)
    if not brief:
        print()
    print(ui.banner(
        config.APP_NAME,
        "" if brief else f"{config.TAGLINE} | 目标站点：{config.BASE_SITE}",
        width=84,
        compact=brief,
    ))
    print(ui.colorize(f"  计划抓取 {total} 个城市 · 并发 {args.workers} 线程 · "
                      f"请求间隔 {args.delay}s · 超时 {args.timeout:.0f}s",
                      ui.C.CYAN))
    if not getattr(args, "brief", False):
        print()


def weather_mark(text: str) -> str:
    """给天气现象配一个简单的彩色标记，让表格更直观。"""
    t = text or ""
    if "雪" in t:
        return ui.colorize(t, ui.C.CYAN)
    if "雨" in t:
        return ui.colorize(t, ui.C.BLUE)
    if "晴" in t and "云" not in t:
        return ui.colorize(t, ui.C.YELLOW)
    if "多云" in t:
        return ui.colorize(t, ui.C.WHITE)
    if "阴" in t:
        return ui.colorize(t, ui.C.GREY)
    if "雾" in t or "霾" in t:
        return ui.colorize(t, ui.C.MAGENTA)
    return t


def temp_mark(value: int | None) -> str:
    """按温度区间给颜色：越冷越蓝、越热越红。"""
    if value is None:
        return ui.colorize("—", ui.C.GREY)
    s = f"{value}℃"
    if value <= -10:
        return ui.colorize(s, ui.C.BLUE, ui.C.BOLD)
    if value <= 0:
        return ui.colorize(s, ui.C.BLUE)
    if value <= 10:
        return ui.colorize(s, ui.C.CYAN)
    if value <= 20:
        return ui.colorize(s, ui.C.GREEN)
    if value <= 30:
        return ui.colorize(s, ui.C.YELLOW)
    return ui.colorize(s, ui.C.RED, ui.C.BOLD)


def print_result_table(records, result: dict) -> None:
    print(ui.section("一、多城市天气数据一览（结构化输出）", width=84))
    headers = ["城市", "地区", "天气", "最高", "最低", "温差", "风向风力",
               "湿度", "AQI", "更新时间"]
    aligns = ["left", "center", "left", "right", "right", "right",
              "left", "right", "right", "center"]
    rows = []
    for r in records:
        if not r.ok:
            rows.append([r.city, r.region, ui.colorize("采集失败", ui.C.RED),
                         "—", "—", "—", "—", "—", "—", "—"])
            continue
        aqi = r.aqi_now
        aqi_txt = "—" if aqi is None else str(int(round(aqi)))
        lvl, col = analyzer.aqi_level(aqi)
        if aqi is not None:
            hexcolor = {"优": ui.C.GREEN, "良": ui.C.YELLOW,
                        "轻度污染": ui.C.YELLOW, "中度污染": ui.C.RED,
                        "重度污染": ui.C.MAGENTA, "严重污染": ui.C.RED}.get(lvl, ui.C.GREY)
            aqi_txt = ui.colorize(f"{int(round(aqi))} {lvl[:2]}", hexcolor)
        hum = "—" if r.humidity_now is None else f"{r.humidity_now:.0f}%"
        rows.append([
            ui.colorize(r.city, ui.C.BOLD, ui.C.WHITE), r.region,
            weather_mark(r.weather_text),
            temp_mark(r.today_high), temp_mark(r.today_low),
            "—" if r.temp_range is None else f"{r.temp_range}℃",
            r.wind_text or "—", hum, aqi_txt,
            (r.updated_at or "—")[-5:] if r.updated_at else "—",
        ])
    print(ui.table(headers, rows, aligns))
    if result:
        print(ui.colorize(
            f"  合计 {result['overview']['city_count']} 个城市，"
            f"成功 {result['overview']['success_count']} 个，"
            f"成功率 {result['overview']['success_rate']}%",
            ui.C.GREY))


def print_analysis(result: dict, brief: bool = False) -> None:
    print()
    print(ui.section("二、数据统计分析（自动生成结论）", width=84))
    for i, line in enumerate(analyzer.summarize_text(result), 1):
        wrapped = ui.wrap_text(line, width=98, indent=4)
        for j, seg in enumerate(wrapped):
            head = f"  {ui.colorize(str(i) + '.', ui.C.CYAN)} " if j == 0 else " " * 5
            print(head + seg)

    if brief:
        return

    print()
    print(ui.colorize("  ▸ 最高气温 TOP5", ui.C.BOLD, ui.C.YELLOW))
    rows = []
    for i, item in enumerate(result["temperature"]["hottest"], 1):
        rows.append([f"{i}", item["city"], item["region"], temp_mark(item["high"]),
                     weather_mark(item["weather"])])
    print(ui.table(["#", "城市", "地区", "最高温", "天气"], rows,
                   ["right", "left", "center", "right", "left"]))

    print()
    print(ui.colorize("  ▸ 昼夜温差 TOP5（体感差异最大）", ui.C.BOLD, ui.C.CYAN))
    rows = []
    for i, item in enumerate(result["temperature"]["biggest_range"], 1):
        rows.append([f"{i}", item["city"], f"{item['low']}~{item['high']}℃",
                     f"{item['range']}℃"])
    print(ui.table(["#", "城市", "温度区间", "温差"], rows,
                   ["right", "left", "right", "right"]))

    print()
    print(ui.colorize("  ▸ 分区域平均高温", ui.C.BOLD, ui.C.GREEN))
    regions = result["regions"]
    max_v = max((r["avg_high"] for r in regions), default=1) or 1
    for r in regions:
        avg = r["avg_high"]
        bar_len = max(1, int(avg / max_v * 28)) if avg and avg > 0 else 1
        bar = ui.colorize("█" * bar_len, ui.C.GREEN)
        val = f"{avg}℃"
        cnt = f"({r['count']}城)"
        print("  " + ui.pad(r["region"], 8) + " "
              + ui.pad(val, 7, "right") + "  " + bar + "  "
              + ui.colorize(cnt, ui.C.GREY))


def print_stats(records, crawler, elapsed: float, brief: bool = False) -> None:
    print()
    print(ui.section("三、抓取过程统计", width=84))
    st = crawler.client.stats
    print("  " + ui.kv_line("HTTP 请求", f"{st.requests_total} 次", 14))
    print("  " + ui.kv_line("缓存命中", f"{st.cache_hits} 次", 14))
    print("  " + ui.kv_line("重试次数", f"{st.retries} 次", 14))
    print("  " + ui.kv_line("失败次数", f"{st.failures} 次", 14))
    print("  " + ui.kv_line("下载流量", f"{st.bytes_total / 1024:.1f} KB", 14))
    print("  " + ui.kv_line("平均耗时", f"{st.avg_ms:.0f} ms/请求", 14))
    print("  " + ui.kv_line("总墙钟时间", f"{elapsed:.2f} s", 14))
    if elapsed > 0 and records:
        print("  " + ui.kv_line("吞吐", f"{len(records) / elapsed:.2f} 城市/秒（含缓存）", 14))

    # 解析策略分布：体现"多策略级联"确实生效
    from collections import Counter
    counter = Counter(r.parse_strategy for r in records if r.parse_strategy)
    if counter and not brief:
        print()
        print("  " + ui.colorize("解析策略命中分布：", ui.C.GREY))
        for name, cnt in counter.most_common():
            print(f"    {ui.colorize('·', ui.C.CYAN)} {name:<16} {cnt} 个城市")


def print_files(paths: dict[str, Path]) -> None:
    print()
    print(ui.section("四、结果文件", width=84))
    for label, path in paths.items():
        if path and Path(path).exists():
            size = Path(path).stat().st_size
            unit = f"{size / 1024:.1f} KB" if size > 1024 else f"{size} B"
            print(f"  {ui.colorize('✓', ui.C.GREEN)} {ui.pad(label, 12)} "
                  f"{ui.pad(unit, 10, 'right')}  {ui.colorize(str(path), ui.C.GREY)}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # ---- 终端初始化 ----
    if args.no_color:
        ui.set_color(False)
    else:
        ui.enable_ansi()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    cities = resolve_cities(args)
    unknown = [c for c in cities if config.code_of(c) is None]
    if unknown:
        print(ui.colorize(f"⚠ 未收录城市代码，将跳过：{'、'.join(unknown)}", ui.C.YELLOW))
        cities = [c for c in cities if config.code_of(c) is not None]
    if not cities:
        print(ui.colorize("没有可抓取的城市。", ui.C.RED))
        return 2

    if not args.quiet:
        print_banner(len(cities), args)

    # ---- 客户端 ----
    # 离线模式：缓存永不过期（否则超过 1 小时缓存就失效，"--offline 断网演示"会失败），
    # 同时关闭 robots 检查（不联网，也就没有请求要检查）。
    client = WeatherHttpClient(
        cache_dir=config.RAW_DIR,
        use_cache=not args.fresh,
        ttl=10 ** 9 if args.offline else config.CACHE_TTL,
        delay=0.0 if args.offline else args.delay,
        respect_robots=not args.offline,
        timeout=(5, args.timeout),
    )
    if args.offline:
        client.delay = 0.0

    crawler = WeatherCrawler(client=client, workers=args.workers)

    # ---- 抓取 ----
    print(ui.section("开始抓取", width=84))
    t0 = time.time()
    last_progress = [0.0]

    def on_progress(done, total, rec):
        if args.quiet:
            return
        status = ui.colorize("✓", ui.C.GREEN) if rec.ok else ui.colorize("✗", ui.C.RED)
        msg = f"  {status} [{done:>2}/{total}] {ui.pad(rec.city, 8)} "
        msg += ui.pad(rec.weather_text or "—", 10) + f" {_fmt_pair(rec):<16}"
        msg += ui.colorize(f"{rec.elapsed_ms:>5} ms", ui.C.GREY)
        print(msg)

    try:
        records = crawler.crawl_all(cities, progress=on_progress)
    except KeyboardInterrupt:
        print(ui.colorize("\n已中断。", ui.C.YELLOW))
        return 130
    elapsed = time.time() - t0
    if not args.quiet:
        ok = sum(1 for r in records if r.ok)
        print("  " + ui.progress_bar(len(records), len(records))
              + ui.colorize(f"  成功 {ok}/{len(records)}，用时 {elapsed:.2f}s", ui.C.GREY))
        print()

    # ---- 分析 ----
    result = analyzer.analyze(records)

    if not args.quiet:
        print_result_table(records, result)
        print_analysis(result, brief=args.brief)
        print_stats(records, crawler, elapsed, brief=args.brief)

    # ---- 持久化 ----
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    st = crawler.client.stats
    meta = {
        "elapsed_s": round(elapsed, 2),
        "workers": args.workers,
        "requests": st.requests_total,
        "cache_hits": st.cache_hits,
        "retries": st.retries,
        "failures": st.failures,
        "bytes": st.bytes_total,
    }
    paths: dict[str, Path] = {}
    paths["JSON"] = storage.save_to_json(records, outdir / "weather.json", meta)
    paths["CSV 汇总"] = storage.save_to_csv(records, outdir / "weather.csv")
    paths["CSV 七日"] = storage.save_week_csv(records, outdir / "weather_7d.csv")
    if args.export_xlsx:
        xlsx = storage.save_to_excel(records, outdir / "weather.xlsx")
        if xlsx:
            paths["Excel"] = xlsx

    if args.charts:
        try:
            from spider.visualizer import ChartBuilder
            builder = ChartBuilder(output_dir=config.FIG_DIR)
            figs = builder.build_all(records, result)
            paths["图表目录"] = config.FIG_DIR
            if not args.quiet:
                print(ui.colorize(f"\n  ✓ 已生成 {len(figs)} 张图表 -> {config.FIG_DIR}",
                                  ui.C.GREEN))
        except Exception as exc:  # noqa: BLE001
            print(ui.colorize(f"\n  ✗ 图表生成失败：{exc}", ui.C.RED))

    if args.dashboard:
        try:
            from spider.dashboard import build_dashboard
            html_path = build_dashboard(records, result, meta,
                                        config.BASE_DIR / "可视化看板.html")
            paths["可视化看板"] = html_path
        except Exception as exc:  # noqa: BLE001
            print(ui.colorize(f"\n  ✗ 看板生成失败：{exc}", ui.C.RED))

    if not args.quiet:
        print_files(paths)
        if not args.brief:
            print()
            print(ui.colorize("  提示：如需重新抓取最新数据，加 --fresh 参数；"
                              "断网演示可加 --offline。", ui.C.GREY))
            print()

    crawler.close()
    return 0 if result["overview"]["success_count"] > 0 else 1


def _fmt_pair(rec) -> str:
    """构造 "12℃/4℃ 温差8℃" 这样的短串。"""
    hi = f"{rec.today_high}℃" if rec.today_high is not None else "—"
    lo = f"{rec.today_low}℃" if rec.today_low is not None else "—"
    rng = f"±{rec.temp_range}℃" if rec.temp_range is not None else ""
    return f"{hi}/{lo} {rng}".strip()


if __name__ == "__main__":
    raise SystemExit(main())
