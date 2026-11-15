# -*- coding: utf-8 -*-
"""
spider/dashboard.py —— 交互式可视化看板生成器
====================================================================
把抓取结果 + 统计分析结果渲染成一个 **单文件、离线可用** 的 HTML 看板：

    * ECharts 5.5 的源码直接内联进 HTML，拷到任何一台电脑双击即可打开，
      不依赖 CDN、不依赖网络（答辩现场断网也能演示）；
    * 数据以 JSON 形式注入，页面内所有图表、表格、结论都由同一份数据驱动，
      与报告中的数字一一对应；
    * 提供城市下拉框，联动切换"7 日趋势"与"24 小时实况"两张时序图；
    * 提供排序表格、深浅色自适应与打印样式。

为什么不用 Jinja2 / 前端框架？
    单文件交付是这里的第一目标。用 ``str.replace`` 占位符即可完成渲染，
    零依赖、零构建步骤，交作业时不会因为"少装了一个包"而跑不起来。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import config
from .analyzer import aqi_level
from .models import WeatherRecord

PLACEHOLDER_ECHARTS = "/*__ECHARTS__*/"
PLACEHOLDER_DATA = "/*__DATA__*/"


# ---------------------------------------------------------------------------
# 数据打包：前端只需要"能直接喂给 ECharts"的形状
# ---------------------------------------------------------------------------
def _pack(records: Sequence[WeatherRecord], result: dict[str, Any],
          meta: dict[str, Any]) -> dict[str, Any]:
    cities = []
    for r in records:
        if not r.ok:
            continue
        lvl, color = aqi_level(r.aqi_now)
        cities.append({
            "city": r.city,
            "region": r.region,
            "code": r.city_code,
            "high": r.today_high,
            "low": r.today_low,
            "range": r.temp_range,
            "weather": r.weather_text,
            "wind": r.wind_text,
            "humidity": r.humidity_now,
            "aqi": None if r.aqi_now is None else round(r.aqi_now),
            "aqiLevel": lvl,
            "aqiColor": color,
            "tempNow": r.temp_now,
            "updated": r.updated_at,
            "week": [
                {
                    "date": d.date_label,
                    "weekday": d.weekday,
                    "high": d.temp_high,
                    "low": d.temp_low,
                    "weather": d.weather_day
                    + (("转" + d.weather_night) if d.weather_night else ""),
                }
                for d in r.week
            ],
            "obs": [
                {"hour": o.hour, "temp": o.temp, "humidity": o.humidity,
                 "aqi": o.aqi}
                for o in reversed(r.obs24)          # 转成时间正序
            ][-24:],
            "warnings": r.warnings,
        })

    # 7 日日期轴：取第一个城市（所有城市日期一致）
    dates = []
    weekdays = []
    if cities and cities[0]["week"]:
        dates = [d["date"] for d in cities[0]["week"]]
        weekdays = [d["weekday"] for d in cities[0]["week"]]

    return {
        "meta": {
            "title": config.APP_NAME,
            "subtitle": config.TAGLINE,
            "site": config.BASE_SITE,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cities": len(records),
            "updated": result["overview"]["update_time"],
            **meta,
        },
        "cities": cities,
        "dates": dates,
        "weekdays": weekdays,
        "analysis": {
            "conclusions": [str(x) for x in result.get("_conclusions", [])],
            "regions": result["regions"],
            "weatherGroup": result["weather"]["group"],
            "airItems": result["air"]["items"],
            "overview": result["overview"],
        },
    }


# ---------------------------------------------------------------------------
# HTML 模板
# ---------------------------------------------------------------------------
TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ · 可视化看板</title>
<style>
:root{
  --bg:#F4F6FA; --card:#FFFFFF; --ink:#1F2733; --ink2:#5A6472; --ink3:#8A94A6;
  --line:#E3E8F0; --hot:#E8543F; --cold:#3E7CB1; --accent:#3D7BF7;
  --shadow:0 1px 2px rgba(20,32,55,.04),0 8px 24px rgba(20,32,55,.07);
  --radius:16px;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--bg); color:var(--ink);
  font-family:"Segoe UI","Microsoft YaHei","PingFang SC",system-ui,-apple-system,sans-serif;
  -webkit-font-smoothing:antialiased;
  padding-bottom:48px;
}
.wrap{max-width:1440px;margin:0 auto;padding:0 22px}

/* ---------- 顶部 ---------- */
.hero{
  position:relative; overflow:hidden; color:#fff;
  background:linear-gradient(120deg,#1B2A4A 0%,#243B6B 42%,#2F5C9E 100%);
  padding:34px 0 30px; margin-bottom:26px;
}
.hero::before,.hero::after{
  content:""; position:absolute; border-radius:50%; filter:blur(60px); opacity:.55;
}
.hero::before{width:420px;height:420px;background:#3D7BF7;top:-190px;right:-80px}
.hero::after{width:340px;height:340px;background:#E8543F;bottom:-220px;left:8%;opacity:.35}
.hero .wrap{position:relative;z-index:2}
.hero h1{margin:0 0 8px; font-size:29px; letter-spacing:.5px; font-weight:700}
.hero .sub{color:#C9D8F5; font-size:14.5px; margin-bottom:18px}
.hero .chips{display:flex; flex-wrap:wrap; gap:10px}
.chip{
  background:rgba(255,255,255,.13); border:1px solid rgba(255,255,255,.2);
  padding:6px 13px; border-radius:999px; font-size:12.5px; color:#EAF1FF;
  backdrop-filter:blur(6px);
}
.chip b{color:#fff; font-weight:600}

/* ---------- KPI ---------- */
.kpis{display:grid; grid-template-columns:repeat(5,1fr); gap:16px; margin-bottom:22px}
.kpi{
  background:var(--card); border-radius:var(--radius); padding:18px 20px;
  box-shadow:var(--shadow); border:1px solid var(--line); position:relative; overflow:hidden;
}
.kpi::after{content:""; position:absolute; left:0; top:0; width:4px; height:100%; background:var(--accent)}
.kpi.hot::after{background:var(--hot)} .kpi.cold::after{background:var(--cold)}
.kpi.warn::after{background:#E8A33D} .kpi.good::after{background:#3AA675}
.kpi .label{font-size:12.5px; color:var(--ink3); margin-bottom:8px}
.kpi .value{font-size:25px; font-weight:700; line-height:1.15; letter-spacing:.3px}
.kpi .value small{font-size:13px; font-weight:500; color:var(--ink2); margin-left:4px}
.kpi .foot{font-size:12px; color:var(--ink3); margin-top:7px}

/* ---------- 卡片网格 ---------- */
.grid{display:grid; grid-template-columns:repeat(12,1fr); gap:18px}
.card{
  background:var(--card); border:1px solid var(--line); border-radius:var(--radius);
  box-shadow:var(--shadow); padding:18px 20px 14px; min-width:0;
}
.card h2{
  margin:0 0 4px; font-size:15.5px; font-weight:650; display:flex; align-items:center; gap:8px;
}
.card h2 .dot{width:7px;height:7px;border-radius:50%;background:var(--accent);display:inline-block}
.card .hint{font-size:12px; color:var(--ink3); margin:0 0 12px}
.span12{grid-column:span 12} .span8{grid-column:span 8} .span6{grid-column:span 6}
.span4{grid-column:span 4} .span3{grid-column:span 3} .span5{grid-column:span 5}
.span7{grid-column:span 7}
.chart{width:100%; height:340px}
.chart.tall{height:420px}
.chart.short{height:290px}

/* ---------- 控件 ---------- */
.toolbar{display:flex; align-items:center; gap:10px; flex-wrap:wrap}
select{
  appearance:none; border:1px solid var(--line); background:#FBFCFE; color:var(--ink);
  padding:7px 32px 7px 12px; border-radius:9px; font-size:13px; cursor:pointer;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%235A6472' stroke-width='2.4'><path d='M6 9l6 6 6-6'/></svg>");
  background-repeat:no-repeat; background-position:right 10px center;
}
select:focus{outline:2px solid rgba(61,123,247,.28); outline-offset:1px}

/* ---------- 结论 ---------- */
.concl{list-style:none; margin:0; padding:0}
.concl li{
  position:relative; padding:9px 0 9px 26px; font-size:13.4px; line-height:1.68;
  color:var(--ink2); border-bottom:1px dashed var(--line);
}
.concl li:last-child{border-bottom:none}
.concl li::before{
  content:counter(c); counter-increment:c; position:absolute; left:0; top:11px;
  width:18px;height:18px;border-radius:50%; background:#EAF1FE; color:var(--accent);
  font-size:11px; font-weight:700; display:flex; align-items:center; justify-content:center;
}
.concl{counter-reset:c}

/* ---------- 表格 ---------- */
.tbl-wrap{overflow:auto; max-height:460px; border-radius:12px; border:1px solid var(--line)}
table{width:100%; border-collapse:collapse; font-size:13px; background:#fff}
thead th{
  position:sticky; top:0; background:#F7F9FC; color:var(--ink2); font-weight:600;
  text-align:left; padding:11px 12px; border-bottom:1px solid var(--line);
  white-space:nowrap; cursor:pointer; user-select:none; font-size:12.5px;
}
thead th:hover{background:#EEF3FB}
tbody td{padding:10px 12px; border-bottom:1px solid #F0F3F8; white-space:nowrap}
tbody tr:hover{background:#F7FAFF}
tbody tr:last-child td{border-bottom:none}
.badge{display:inline-block; padding:2px 9px; border-radius:999px; font-size:11.5px; font-weight:600}
.t-hot{color:var(--hot); font-weight:650}
.t-cold{color:var(--cold); font-weight:650}
.muted{color:var(--ink3)}

/* ---------- 流程条 ---------- */
.flow{display:flex; align-items:center; gap:0; flex-wrap:wrap; margin:2px 0 4px}
.flow .step{
  flex:1; min-width:130px; background:#F7F9FC; border:1px solid var(--line);
  border-radius:11px; padding:11px 14px; text-align:center;
}
.flow .step b{display:block; font-size:13px; margin-bottom:3px}
.flow .step span{font-size:11.5px; color:var(--ink3)}
.flow .arrow{color:#C3CDDC; padding:0 9px; font-size:17px}

footer{color:var(--ink3); font-size:12px; text-align:center; margin-top:30px; line-height:1.9}

@media (max-width:1180px){
  .kpis{grid-template-columns:repeat(3,1fr)}
  .span8,.span7,.span6,.span5,.span4,.span3{grid-column:span 12}
  .chart{height:300px}
}
@media print{
  body{background:#fff} .hero{background:#243B6B !important;-webkit-print-color-adjust:exact}
  .card{box-shadow:none; break-inside:avoid}
}
</style>
</head>
<body>

<header class="hero">
  <div class="wrap">
    <h1 id="h-title">中国天气网多城市天气数据采集与可视化系统</h1>
    <div class="sub" id="h-sub"></div>
    <div class="chips" id="h-chips"></div>
  </div>
</header>

<div class="wrap">
  <section class="kpis" id="kpis"></section>

  <section class="grid">
    <div class="card span12">
      <h2><span class="dot"></span>系统数据流</h2>
      <p class="hint">从 HTTP 请求到可视化呈现的完整链路，对应程序中的四个核心模块</p>
      <div class="flow">
        <div class="step"><b>① HTTP 抓取</b><span>requests · UA 轮换 · 重试 · 缓存</span></div>
        <div class="arrow">→</div>
        <div class="step"><b>② HTML/JS 解析</b><span>BeautifulSoup · 多策略级联 · JSON 抽取</span></div>
        <div class="arrow">→</div>
        <div class="step"><b>③ 结构化与统计</b><span>dataclass · JSON/CSV/Excel · rankings</span></div>
        <div class="arrow">→</div>
        <div class="step"><b>④ 可视化</b><span>ECharts 看板 · matplotlib 图表</span></div>
      </div>
    </div>

    <div class="card span8">
      <h2><span class="dot"></span>多城市今日气温对比</h2>
      <p class="hint">柱形为最高/最低气温，折线为昼夜温差；按最高气温降序排列</p>
      <div id="c-temp" class="chart tall"></div>
    </div>

    <div class="card span4">
      <h2><span class="dot"></span>天气现象构成</h2>
      <p class="hint">按天气大类归并后的城市数量分布</p>
      <div id="c-weather" class="chart tall"></div>
    </div>

    <div class="card span7">
      <h2><span class="dot"></span>未来 7 日气温趋势
        <span class="toolbar" style="margin-left:auto">
          <select id="sel-week"></select>
        </span>
      </h2>
      <p class="hint">阴影区域表示昼夜温差带，可切换城市查看不同气候带的变化形态</p>
      <div id="c-week" class="chart"></div>
    </div>

    <div class="card span5">
      <h2><span class="dot"></span>过去 24 小时实况
        <span class="toolbar" style="margin-left:auto">
          <select id="sel-obs"></select>
        </span>
      </h2>
      <p class="hint">双 Y 轴：左轴温度、右轴相对湿度</p>
      <div id="c-obs" class="chart"></div>
    </div>

    <div class="card span6">
      <h2><span class="dot"></span>空气质量指数（AQI）</h2>
      <p class="hint">颜色代表等级，越靠上空气越差</p>
      <div id="c-aqi" class="chart"></div>
    </div>

    <div class="card span6">
      <h2><span class="dot"></span>分区域平均高温</h2>
      <p class="hint">七大区域的平均最高气温（仅统计有样本的区域）</p>
      <div id="c-region" class="chart"></div>
    </div>

    <div class="card span12">
      <h2><span class="dot"></span>城市 × 日期 最高气温热力图</h2>
      <p class="hint">颜色越暖代表气温越高，可直观看出"南北温差 + 冷空气南下"的过程</p>
      <div id="c-heat" class="chart tall"></div>
    </div>

    <div class="card span12">
      <h2><span class="dot"></span>数据分析结论</h2>
      <p class="hint">由程序自动统计生成，与导出的 JSON / CSV 数据同源</p>
      <ol class="concl" id="concl"></ol>
    </div>

    <div class="card span12">
      <h2><span class="dot"></span>明细数据表</h2>
      <p class="hint">点击表头可排序；数据与 JSON/CSV 输出同源</p>
      <div class="tbl-wrap">
        <table id="tbl">
          <thead><tr>
            <th data-k="city">城市</th>
            <th data-k="region">地区</th>
            <th data-k="weather">天气</th>
            <th data-k="high">最高温</th>
            <th data-k="low">最低温</th>
            <th data-k="range">温差</th>
            <th data-k="wind">风向风力</th>
            <th data-k="humidity">相对湿度</th>
            <th data-k="aqi">AQI</th>
            <th data-k="updated">更新时间</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  </section>

  <footer>
    数据来源：中国天气网 <a href="http://www.weather.com.cn" target="_blank" style="color:#3D7BF7;text-decoration:none">www.weather.com.cn</a>
    · 本页面由程序自动生成，ECharts 已内联，可离线打开<br>
    __FOOTER_INFO__
  </footer>
</div>

<script>/*__ECHARTS__*/</script>
<script>
/*__DATA__*/
</script>
<script>
(function () {
  var D = window.__DASH_DATA__ || {};
  var meta = D.meta || {};
  var cities = D.cities || [];
  var analysis = D.analysis || {};

  /* ---------------- 顶部 ---------------- */
  document.getElementById("h-title").textContent = meta.title || "天气数据可视化看板";
  document.getElementById("h-sub").textContent =
    (meta.subtitle || "") + " · 目标站点 " + (meta.site || "");
  var chips = [
    ["城市样本", (meta.cities || 0) + " 个"],
    ["数据更新", meta.updated || "—"],
    ["生成时间", meta.generated || "—"],
    ["HTTP 请求", (meta.requests || 0) + " 次"],
    ["平均耗时", (meta.elapsed_s || 0) + " s / 全量"]
  ];
  document.getElementById("h-chips").innerHTML = chips.map(function (c) {
    return '<div class="chip">' + c[0] + '：<b>' + c[1] + '</b></div>';
  }).join("");

  /* ---------------- KPI ---------------- */
  var ok = cities.filter(function (c) { return c.high !== null && c.high !== undefined; });
  var byHigh = ok.slice().sort(function (a, b) { return b.high - a.high; });
  var byLow = ok.slice().sort(function (a, b) { return a.low - b.low; });
  var byRange = cities.filter(function (c) { return c.range !== null && c.range !== undefined; })
                     .sort(function (a, b) { return b.range - a.range; });
  var byAqi = cities.filter(function (c) { return c.aqi !== null && c.aqi !== undefined; })
                    .sort(function (a, b) { return b.aqi - a.aqi; });
  var avgHigh = ok.length ? (ok.reduce(function (s, c) { return s + c.high; }, 0) / ok.length) : 0;

  var kpis = [
    { cls: "hot", label: "样本城市平均最高温", value: avgHigh.toFixed(1) + "°C",
      foot: "共 " + cities.length + " 个城市" },
    { cls: "hot", label: "最热城市", value: byHigh.length ? byHigh[0].city : "—",
      foot: byHigh.length ? "最高 " + byHigh[0].high + "℃" : "" },
    { cls: "cold", label: "最冷城市", value: byLow.length ? byLow[0].city : "—",
      foot: byLow.length ? "最低 " + byLow[0].low + "℃" : "" },
    { cls: "warn", label: "昼夜温差最大", value: byRange.length ? byRange[0].city : "—",
      foot: byRange.length ? "温差 " + byRange[0].range + "℃" : "" },
    { cls: "good", label: "空气最好城市", value: byAqi.length ? byAqi[byAqi.length - 1].city : "—",
      foot: byAqi.length ? "AQI " + byAqi[byAqi.length - 1].aqi : "" }
  ];
  document.getElementById("kpis").innerHTML = kpis.map(function (k) {
    return '<div class="kpi ' + k.cls + '"><div class="label">' + k.label + '</div>' +
           '<div class="value">' + k.value + '</div>' +
           '<div class="foot">' + k.foot + '</div></div>';
  }).join("");

  /* ---------------- 结论 ---------------- */
  document.getElementById("concl").innerHTML = (analysis.conclusions || [])
    .map(function (t) { return "<li>" + t + "</li>"; }).join("");

  /* ---------------- 通用样式 ---------------- */
  var C = { hot: "#E8543F", cold: "#3E7CB1", accent: "#3D7BF7",
            ink: "#1F2733", ink2: "#5A6472", grid: "#EEF1F6" };
  var baseGrid = { left: 46, right: 22, top: 42, bottom: 34 };
  function baseOption(extra) {
    var o = {
      animationDuration: 700,
      textStyle: { fontFamily: '"Segoe UI","Microsoft YaHei",sans-serif', color: C.ink2 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" },
                 backgroundColor: "rgba(255,255,255,.96)", borderColor: "#E3E8F0",
                 borderWidth: 1, textStyle: { color: C.ink, fontSize: 12.5 },
                 extraCssText: "box-shadow:0 6px 24px rgba(20,32,55,.12);border-radius:10px;" },
      grid: Object.assign({}, baseGrid)
    };
    return Object.assign(o, extra || {});
  }
  function axisCommon() {
    return {
      axisLine: { lineStyle: { color: "#D8DFEA" } },
      axisTick: { show: false },
      axisLabel: { color: C.ink2, fontSize: 11.5 },
      splitLine: { lineStyle: { color: C.grid } }
    };
  }
  /* 轴配置：公共样式在前、覆盖项在后，避免 axisLabel 被公共样式冲掉 */
  function ax(extra) { return Object.assign({}, axisCommon(), extra || {}); }

  /* ---------------- 1. 气温对比 ---------------- */
  var cTemp = echarts.init(document.getElementById("c-temp"));
  var tCities = byHigh.map(function (c) { return c.city; });
  var tHigh = byHigh.map(function (c) { return c.high; });
  var tLow = byHigh.map(function (c) { return c.low; });
  var tRange = byHigh.map(function (c) { return c.range; });
  cTemp.setOption(baseOption({
    legend: { data: ["最高气温", "最低气温", "昼夜温差"], right: 10, top: 6,
              itemWidth: 12, itemHeight: 12, textStyle: { color: C.ink2, fontSize: 12 } },
    xAxis: ax({ type: "category", data: tCities,
      axisLabel: { color: C.ink2, fontSize: 11, interval: 0,
                   rotate: tCities.length > 10 ? 40 : 0 },
      axisLine: { lineStyle: { color: "#D8DFEA" } }, axisTick: { show: false } }),
    yAxis: ax({ type: "value", name: "℃", nameTextStyle: { color: C.ink2 } }),
    series: [
      { name: "最高气温", type: "bar", data: tHigh, barGap: "10%", barWidth: "30%",
        itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1,
          [{ offset: 0, color: "#F2705B" }, { offset: 1, color: "#E8543F" }]),
          borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: "top", color: C.hot, fontSize: 10.5 } },
      { name: "最低气温", type: "bar", data: tLow, barWidth: "30%",
        itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1,
          [{ offset: 0, color: "#5B9BD5" }, { offset: 1, color: "#3E7CB1" }]),
          borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: tLow.some(function (v) { return v < 0; }) ? "bottom" : "top",
                 color: C.cold, fontSize: 10.5 } },
      { name: "昼夜温差", type: "line", yAxisIndex: 0, data: tRange, smooth: true,
        symbol: "circle", symbolSize: 6, lineStyle: { width: 2, color: "#E8A33D" },
        itemStyle: { color: "#E8A33D" }, z: 5 }
    ]
  }));

  /* ---------------- 2. 天气构成 ---------------- */
  var cW = echarts.init(document.getElementById("c-weather"));
  var wColors = { "晴": "#F5C542", "多云": "#8FB8DE", "阴": "#9AA5B1",
                  "雨": "#4A78B5", "雪": "#B8D8E8", "雾霾": "#B08BB0",
                  "大风": "#7FB3A8", "其他": "#C9C9C9" };
  var wData = (analysis.weatherGroup || []).map(function (g) {
    return { name: g.name, value: g.value, itemStyle: { color: wColors[g.name] || "#C9C9C9" } };
  });
  cW.setOption({
    animationDuration: 800,
    tooltip: { trigger: "item", formatter: "{b}<br/>{c} 个城市（{d}%）",
               backgroundColor: "rgba(255,255,255,.96)", borderColor: "#E3E8F0",
               borderWidth: 1, textStyle: { color: C.ink } },
    legend: { bottom: 4, icon: "circle", itemWidth: 10, itemHeight: 10,
              textStyle: { color: C.ink2, fontSize: 12 } },
    series: [{
      type: "pie", radius: ["42%", "64%"], center: ["50%", "44%"],
      avoidLabelOverlap: true, data: wData, minShowLabelAngle: 3,
      label: {
        formatter: function (p) { return p.name + " " + p.value + "城"; },
        color: C.ink2, fontSize: 11.5, lineHeight: 16, edgeDistance: "2%"
      },
      labelLine: { length: 6, length2: 8, lineStyle: { color: "#C3CDDC" } },
      itemStyle: { borderColor: "#fff", borderWidth: 2 }
    }]
  });

  /* ---------------- 城市下拉框 ---------------- */
  function fillSelect(id) {
    var el = document.getElementById(id);
    el.innerHTML = cities.map(function (c) {
      return '<option value="' + c.city + '">' + c.city + "（" + c.region + "）</option>";
    }).join("");
    return el;
  }
  var selWeek = fillSelect("sel-week");
  var selObs = fillSelect("sel-obs");
  // 默认选中：温差最大的城市，趋势图最好看
  var defaultCity = byRange.length ? byRange[0].city : (cities[0] || {}).city;
  selWeek.value = defaultCity;
  selObs.value = defaultCity;

  /* ---------------- 3. 7 日趋势 ---------------- */
  var cWeek = echarts.init(document.getElementById("c-week"));
  function renderWeek(name) {
    var c = cities.filter(function (x) { return x.city === name; })[0];
    if (!c) return;
    var xs = c.week.map(function (d) { return d.date; });
    var hi = c.week.map(function (d) { return d.high; });
    var lo = c.week.map(function (d) { return d.low; });
    cWeek.setOption(baseOption({
      tooltip: { trigger: "axis", backgroundColor: "rgba(255,255,255,.96)",
        borderColor: "#E3E8F0", borderWidth: 1, textStyle: { color: C.ink },
        formatter: function (ps) {
          var wd = (c.week[ps[0].dataIndex] || {}).weekday || "";
          var s = "<b>" + ps[0].axisValue + (wd ? "（" + wd + "）" : "") + "</b><br/>";
          ps.forEach(function (p) {
            s += p.marker + p.seriesName + "：" + (p.value === null ? "—" : p.value + "℃") + "<br/>";
          });
          return s;
        } },
      legend: { data: ["最高气温", "最低气温"], right: 8, top: 0,
                itemWidth: 12, itemHeight: 12, textStyle: { color: C.ink2, fontSize: 12 } },
      xAxis: ax({ type: "category", data: xs, boundaryGap: false }),
      yAxis: ax({ type: "value", name: "℃", scale: true,
        nameTextStyle: { color: C.ink2 } }),
      series: [
        { name: "最高气温", type: "line", data: hi, smooth: true, symbolSize: 7,
          lineStyle: { width: 2.6, color: C.hot }, itemStyle: { color: C.hot },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1,
            [{ offset: 0, color: "rgba(232,84,63,.28)" }, { offset: 1, color: "rgba(232,84,63,0)" }]) },
          label: { show: true, position: "top", color: C.hot, fontSize: 10.5 } },
        { name: "最低气温", type: "line", data: lo, smooth: true, symbolSize: 7,
          lineStyle: { width: 2.6, color: C.cold }, itemStyle: { color: C.cold },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1,
            [{ offset: 0, color: "rgba(62,124,177,0)" }, { offset: 1, color: "rgba(62,124,177,.26)" }]) },
          label: { show: true, position: "bottom", color: C.cold, fontSize: 10.5 } }
      ]
    }), true);
  }
  renderWeek(defaultCity);
  selWeek.addEventListener("change", function () { renderWeek(selWeek.value); });

  /* ---------------- 4. 24 小时实况 ---------------- */
  var cObs = echarts.init(document.getElementById("c-obs"));
  function renderObs(name) {
    var c = cities.filter(function (x) { return x.city === name; })[0];
    if (!c) return;
    var obs = c.obs.filter(function (o) { return o.temp !== null; });
    var xs = obs.map(function (o) { return o.hour + "时"; });
    cObs.setOption(baseOption({
      tooltip: { trigger: "axis", backgroundColor: "rgba(255,255,255,.96)",
        borderColor: "#E3E8F0", borderWidth: 1, textStyle: { color: C.ink } },
      legend: { data: ["温度", "相对湿度"], right: 8, top: 0, itemWidth: 12,
                itemHeight: 12, textStyle: { color: C.ink2, fontSize: 12 } },
      xAxis: ax({ type: "category", data: xs, boundaryGap: false,
        axisLabel: { color: C.ink2, fontSize: 10.5, interval: 2 } }),
      yAxis: [
        ax({ type: "value", name: "℃", scale: true, nameTextStyle: { color: C.hot } }),
        ax({ type: "value", name: "%", scale: true, splitLine: { show: false },
             nameTextStyle: { color: C.cold } })
      ],
      series: [
        { name: "温度", type: "line", yAxisIndex: 0, data: obs.map(function (o) { return o.temp; }),
          smooth: true, symbolSize: 6, lineStyle: { width: 2.6, color: C.hot },
          itemStyle: { color: C.hot },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1,
            [{ offset: 0, color: "rgba(232,84,63,.24)" }, { offset: 1, color: "rgba(232,84,63,0)" }]) } },
        { name: "相对湿度", type: "line", yAxisIndex: 1,
          data: obs.map(function (o) { return o.humidity; }),
          smooth: true, symbolSize: 5, lineStyle: { width: 2, type: "dashed", color: C.cold },
          itemStyle: { color: C.cold } }
      ]
    }), true);
  }
  renderObs(defaultCity);
  selObs.addEventListener("change", function () { renderObs(selObs.value); });

  /* ---------------- 5. AQI ---------------- */
  var cAqi = echarts.init(document.getElementById("c-aqi"));
  var aqiSorted = byAqi.slice().reverse();
  cAqi.setOption(baseOption({
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" },
      backgroundColor: "rgba(255,255,255,.96)", borderColor: "#E3E8F0", borderWidth: 1,
      textStyle: { color: C.ink },
      formatter: function (ps) {
        var p = ps[0]; var c = aqiSorted[p.dataIndex];
        return "<b>" + p.name + "</b><br/>AQI：" + p.value + "（" + c.aqiLevel + "）";
      } },
    grid: { left: 66, right: 56, top: 16, bottom: 34 },
    xAxis: ax({ type: "value", name: "AQI" }),
    yAxis: ax({ type: "category", data: aqiSorted.map(function (c) { return c.city; }) }),
    series: [{
      type: "bar", barWidth: "58%", data: aqiSorted.map(function (c) {
        return { value: c.aqi, itemStyle: { color: c.aqiColor, borderRadius: [0, 4, 4, 0] } };
      }),
      label: { show: true, position: "right", color: C.ink2, fontSize: 11,
               formatter: function (p) { return p.value + " " + aqiSorted[p.dataIndex].aqiLevel; } },
      markLine: { silent: true, symbol: "none",
        lineStyle: { color: "#C3CDDC", type: "dashed", width: 1 },
        label: { color: "#8A94A6", fontSize: 10, formatter: "良 {c}" },
        data: [{ xAxis: 50 }, { xAxis: 100 }, { xAxis: 150 }] }
    }]
  }));

  /* ---------------- 6. 区域雷达 ---------------- */
  var cReg = echarts.init(document.getElementById("c-region"));
  var regions = (analysis.regions || []).slice();
  if (regions.length >= 3) {
    var maxV = Math.max.apply(null, regions.map(function (r) { return r.avg_high; }));
    var minV = Math.min.apply(null, regions.map(function (r) { return r.avg_high; }));
    cReg.setOption({
      tooltip: { backgroundColor: "rgba(255,255,255,.96)", borderColor: "#E3E8F0",
                 borderWidth: 1, textStyle: { color: C.ink } },
      radar: {
        indicator: regions.map(function (r) {
          return { name: r.region + "\n" + r.avg_high + "℃", max: maxV + 4, min: Math.min(0, minV - 3) };
        }),
        radius: "62%", center: ["50%", "52%"], splitNumber: 4,
        axisName: { color: C.ink2, fontSize: 11.5, lineHeight: 15 },
        splitLine: { lineStyle: { color: C.grid } },
        splitArea: { areaStyle: { color: ["#FBFCFE", "#F5F8FC"] } },
        axisLine: { lineStyle: { color: C.grid } }
      },
      series: [{
        type: "radar", symbolSize: 6,
        data: [{ value: regions.map(function (r) { return r.avg_high; }),
                 name: "平均最高气温",
                 lineStyle: { color: C.hot, width: 2.2 },
                 itemStyle: { color: C.hot },
                 areaStyle: { color: "rgba(232,84,63,.18)" } }]
      }]
    });
  } else {
    cReg.setOption({ title: { text: "样本区域不足 3 个，无法绘制雷达图",
      left: "center", top: "middle", textStyle: { color: C.ink2, fontSize: 13, fontWeight: "normal" } } });
  }

  /* ---------------- 7. 热力图 ---------------- */
  var cHeat = echarts.init(document.getElementById("c-heat"));
  var dates = D.dates || [];
  var heatCities = ok.map(function (c) { return c.city; });
  var heatData = [];
  var heatVals = [];
  heatCities.forEach(function (name, yi) {
    var c = cities.filter(function (x) { return x.city === name; })[0];
    c.week.forEach(function (d, xi) {
      if (d.high === null || d.high === undefined) return;
      heatData.push([xi, yi, d.high]);
      heatVals.push(d.high);
    });
  });
  var vmin = Math.min.apply(null, heatVals), vmax = Math.max.apply(null, heatVals);
  cHeat.setOption({
    animationDuration: 700,
    tooltip: { backgroundColor: "rgba(255,255,255,.96)", borderColor: "#E3E8F0",
      borderWidth: 1, textStyle: { color: C.ink },
      formatter: function (p) {
        return "<b>" + heatCities[p.value[1]] + "</b> · " + dates[p.value[0]] +
               "<br/>最高气温：" + p.value[2] + "℃";
      } },
    grid: { left: 76, right: 30, top: 16, bottom: 58 },
    xAxis: { type: "category", data: dates, splitArea: { show: true },
             axisLabel: { color: C.ink2, fontSize: 11.5 },
             axisLine: { lineStyle: { color: "#D8DFEA" } }, axisTick: { show: false } },
    yAxis: { type: "category", data: heatCities, splitArea: { show: true },
             axisLabel: { color: C.ink2, fontSize: 11.5 },
             axisLine: { lineStyle: { color: "#D8DFEA" } }, axisTick: { show: false } },
    visualMap: {
      min: vmin, max: vmax, calculable: true, orient: "horizontal",
      left: "center", bottom: 4, itemWidth: 12, itemHeight: 100,
      textStyle: { color: C.ink2, fontSize: 11 },
      inRange: { color: ["#2C5F8A", "#5B9BD5", "#CFE3F2", "#FBE2C0", "#F2A65A", "#D64533"] }
    },
    series: [{
      type: "heatmap", data: heatData,
      label: { show: true, color: "#2B3440", fontSize: 10.5 },
      emphasis: { itemStyle: { shadowBlur: 8, shadowColor: "rgba(0,0,0,.25)" } },
      itemStyle: { borderColor: "#fff", borderWidth: 1.5 }
    }]
  });

  /* ---------------- 8. 表格 ---------------- */
  var tbody = document.querySelector("#tbl tbody");
  var sortKey = "high", sortDir = -1;
  function renderTable() {
    var rows = cities.slice().sort(function (a, b) {
      var va = a[sortKey], vb = b[sortKey];
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      if (typeof va === "string") return va.localeCompare(vb, "zh") * sortDir;
      return (va - vb) * sortDir;
    });
    tbody.innerHTML = rows.map(function (c) {
      var aqiHtml = (c.aqi === null || c.aqi === undefined) ? '<span class="muted">—</span>'
        : '<span class="badge" style="background:' + c.aqiColor + ';color:#fff">' +
          c.aqi + " " + c.aqiLevel + "</span>";
      return "<tr>" +
        "<td><b>" + c.city + "</b></td>" +
        "<td>" + c.region + "</td>" +
        "<td>" + (c.weather || "—") + "</td>" +
        '<td class="t-hot">' + (c.high === null ? "—" : c.high + "℃") + "</td>" +
        '<td class="t-cold">' + (c.low === null ? "—" : c.low + "℃") + "</td>" +
        "<td>" + (c.range === null ? "—" : c.range + "℃") + "</td>" +
        "<td>" + (c.wind || "—") + "</td>" +
        "<td>" + (c.humidity === null ? "—" : c.humidity.toFixed(0) + "%") + "</td>" +
        "<td>" + aqiHtml + "</td>" +
        '<td class="muted">' + (c.updated || "—") + "</td>" +
        "</tr>";
    }).join("");
  }
  renderTable();
  document.querySelectorAll("#tbl thead th").forEach(function (th) {
    th.addEventListener("click", function () {
      var k = th.getAttribute("data-k");
      if (k === sortKey) { sortDir = -sortDir; } else { sortKey = k; sortDir = 1; }
      renderTable();
    });
  });

  /* ---------------- 自适应 ---------------- */
  window.addEventListener("resize", function () {
    [cTemp, cW, cWeek, cObs, cAqi, cReg, cHeat].forEach(function (c) { c.resize(); });
  });
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 渲染入口
# ---------------------------------------------------------------------------
def build_dashboard(records: Sequence[WeatherRecord], result: dict[str, Any],
                    meta: dict[str, Any] | None = None,
                    output: str | Path | None = None) -> Path:
    """生成单文件 HTML 看板，返回输出路径。"""
    from .analyzer import summarize_text

    output = Path(output or (config.BASE_DIR / "可视化看板.html"))
    output.parent.mkdir(parents=True, exist_ok=True)

    result = dict(result)
    result["_conclusions"] = summarize_text(result)
    payload = _pack(records, result, meta or {})

    # ECharts 内联（缺失时给出降级提示，页面仍可打开）
    echarts_path = config.VENDOR_DIR / "echarts.min.js"
    if echarts_path.exists():
        echarts_js = echarts_path.read_text(encoding="utf-8", errors="replace")
        echarts_js = echarts_js.replace("</script", "<\\/script")
    else:
        echarts_js = ("document.addEventListener('DOMContentLoaded',function(){"
                      "document.body.insertAdjacentHTML('afterbegin',"
                      "'<div style=\"padding:20px;background:#FFF3CD;color:#8A6D3B\">"
                      "未找到 vendor/echarts.min.js，图表无法渲染。请先下载 ECharts。</div>');});")

    data_js = "window.__DASH_DATA__ = " + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")) + ";"

    html = TEMPLATE.replace("__TITLE__", config.APP_NAME)
    html = html.replace(PLACEHOLDER_ECHARTS, echarts_js)
    html = html.replace(PLACEHOLDER_DATA, data_js)
    html = html.replace(
        "__FOOTER_INFO__",
        f"{config.TAGLINE}｜"
        f"生成于 {datetime.now():%Y-%m-%d %H:%M:%S}")

    output.write_text(html, encoding="utf-8")
    return output
