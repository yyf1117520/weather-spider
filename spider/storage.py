# -*- coding: utf-8 -*-
"""
spider/storage.py —— 数据持久化层
====================================================================
本模块负责把抓取结果落盘，
在基础实现之上做了三点增强：

    1. JSON 中额外写入 ``meta``（抓取时间、城市数、统计信息），
       让数据文件"自解释"，脱离程序也能看懂；
    2. CSV 使用 ``utf-8-sig`` 编码，双击用 Excel 打开中文不乱码；
    3. 增加 Excel（xlsx）多工作表导出：汇总表 + 7 日明细 + 24 小时实况。
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from .models import WeatherRecord


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
def save_to_json(records: Sequence[WeatherRecord], filename: str | Path,
                 session_meta: dict | None = None) -> Path:
    """把抓取结果保存为 JSON。

    Parameters
    ----------
    records : 城市记录列表
    filename : 输出路径
    session_meta : 附加的会话信息（耗时、线程数、统计等）
    """
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "meta": {
            "generator": "中国天气网多城市天气数据采集与可视化系统",
            "version": "2.0",
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "city_count": len(records),
            "success_count": sum(1 for r in records if r.ok),
            **(session_meta or {}),
        },
        "data": [r.to_dict() for r in records],
    }
    with open(path, "w", encoding="utf-8") as f:
        # ensure_ascii=False 保证中文可读；indent=2 便于人工查看
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def load_from_json(filename: str | Path) -> list[dict]:
    """读取 JSON（看板生成、离线分析时使用）。"""
    with open(filename, encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("data", [])


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
SUMMARY_HEADER = [
    "城市", "地区", "城市代码", "日期", "最高温(℃)", "最低温(℃)", "昼夜温差(℃)",
    "天气", "风向风力", "实况温度(℃)", "相对湿度(%)", "空气质量指数",
    "更新时间", "抓取时间",
]


def save_to_csv(records: Sequence[WeatherRecord], filename: str | Path) -> Path:
    """把"每城市一行"的汇总表写成 CSV。"""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_HEADER)
        writer.writeheader()
        for rec in records:
            row = rec.to_flat_row()
            # 只写表头里有的列，缺的补空串
            writer.writerow({k: ("" if row.get(k) is None else row.get(k))
                             for k in SUMMARY_HEADER})
    return path


def save_week_csv(records: Sequence[WeatherRecord], filename: str | Path) -> Path:
    """把 7 日预报表写成 CSV（城市 × 日期 长表），便于透视分析。"""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ["城市", "地区", "日期", "星期", "白天天气", "夜间天气",
              "最高温(℃)", "最低温(℃)", "风向", "风力", "天空等级"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for rec in records:
            for d in rec.week:
                writer.writerow([
                    rec.city, rec.region, d.date_label, d.weekday,
                    d.weather_day, d.weather_night,
                    "" if d.temp_high is None else d.temp_high,
                    "" if d.temp_low is None else d.temp_low,
                    d.wind_dir, d.wind_level, d.sky_level,
                ])
    return path


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def save_to_excel(records: Sequence[WeatherRecord], filename: str | Path) -> Path | None:
    """导出多工作表 Excel。缺少 openpyxl 时返回 None 而不是报错。"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        return None

    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="2F6F9F")
    center = Alignment(horizontal="center", vertical="center")

    def style_sheet(ws, widths):
        for c, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(c)].width = w
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center
        ws.freeze_panes = "A2"

    # --- 工作表 1：城市汇总 ---
    ws = wb.active
    ws.title = "城市汇总"
    ws.append(SUMMARY_HEADER)
    for rec in records:
        row = rec.to_flat_row()
        ws.append(["" if row.get(k) is None else row.get(k) for k in SUMMARY_HEADER])
    style_sheet(ws, [10, 8, 12, 10, 11, 11, 12, 14, 20, 12, 12, 12, 18, 20])

    # --- 工作表 2：7 日预报 ---
    ws2 = wb.create_sheet("7日预报")
    ws2.append(["城市", "地区", "日期", "星期", "白天天气", "夜间天气",
                "最高温(℃)", "最低温(℃)", "风向", "风力"])
    for rec in records:
        for d in rec.week:
            ws2.append([rec.city, rec.region, d.date_label, d.weekday,
                        d.weather_day, d.weather_night, d.temp_high, d.temp_low,
                        d.wind_dir, d.wind_level])
    style_sheet(ws2, [10, 8, 10, 8, 14, 12, 11, 11, 16, 14])

    # --- 工作表 3：24 小时实况 ---
    ws3 = wb.create_sheet("24小时实况")
    ws3.append(["城市", "时刻", "温度(℃)", "相对湿度(%)", "空气质指数", "风向", "风力", "降水(mm)"])
    for rec in records:
        for o in rec.obs24:
            ws3.append([rec.city, o.hour, o.temp, o.humidity, o.aqi,
                        o.wind_dir, o.wind_level, o.rain])
    style_sheet(ws3, [10, 8, 12, 13, 13, 10, 8, 10])

    wb.save(path)
    return path
