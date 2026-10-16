#!/usr/bin/env python3
"""
静态网站生成器：读取 data/*.json → 生成 site/（首页=最新日报、历史归档、每日报告页、方法说明、趋势页、公开 JSON）
用法：python scanner/build_site.py --data data --out site [--base-url https://xxx.github.io/futures-signals]
"""
import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import events_cal
import stats as stats_mod
import macd8
import chart as chart_mod
import chart_page
from scan import SYMBOLS

CN_TZ = ZoneInfo("Asia/Shanghai")
SITE_TITLE = "期货八种形态日报"

SECTOR = {
    "RB0": "黑色", "HC0": "黑色", "SS0": "黑色", "I0": "黑色", "J0": "黑色", "JM0": "黑色", "SF0": "黑色", "SM0": "黑色",
    "CU0": "有色", "AL0": "有色", "ZN0": "有色", "PB0": "有色", "NI0": "有色", "SN0": "有色",
    "AU0": "贵金属", "AG0": "贵金属",
    "SC0": "能化", "FU0": "能化", "BU0": "能化", "LU0": "能化", "TA0": "能化", "MA0": "能化", "EG0": "能化",
    "EB0": "能化", "V0": "能化", "L0": "能化", "PP0": "能化", "PG0": "能化", "RU0": "能化", "NR0": "能化",
    "SP0": "能化", "PF0": "能化", "PX0": "能化", "SH0": "能化", "SA0": "能化", "FG0": "能化", "UR0": "能化",
    "M0": "农产品", "Y0": "农产品", "P0": "农产品", "OI0": "农产品", "RM0": "农产品", "C0": "农产品",
    "SR0": "农产品", "CF0": "农产品", "AP0": "农产品", "PK0": "农产品",
    "IF0": "股指", "IH0": "股指", "IC0": "股指", "IM0": "股指", "EC0": "股指",
    "SI0": "新能源", "LC0": "新能源",
}
PATTERNS = ["高富帅", "白富美", "上涨乏力", "下跌乏力", "虚涨分歧", "虚跌分歧", "涨势将尽", "跌势将尽"]
PAT_DESC = {
    "高富帅": "增仓·放量·上涨｜强上涨信号", "白富美": "增仓·放量·下跌｜历史胜率47%，降级观察",
    "上涨乏力": "上涨·放量·减仓｜老多头获利了结", "下跌乏力": "下跌·放量·减仓｜老空头获利了结",
    "虚涨分歧": "上涨·缩量·增仓｜或为高位开空", "虚跌分歧": "下跌·缩量·增仓｜或为低位抄底",
    "涨势将尽": "上涨·缩量·减仓｜多头力量衰退", "跌势将尽": "下跌·缩量·减仓｜抛压衰竭",
}
PAT_ICON = {"高富帅": "👑", "白富美": "💎", "上涨乏力": "⚡", "下跌乏力": "🌊",
            "虚涨分歧": "🔶", "虚跌分歧": "🔷", "涨势将尽": "🍂", "跌势将尽": "🌱"}
PAT_CLASS = {"高富帅": "p-gao", "白富美": "p-bai", "上涨乏力": "p-n", "下跌乏力": "p-n",
             "虚涨分歧": "p-n", "虚跌分歧": "p-n", "涨势将尽": "p-warn", "跌势将尽": "p-good"}
EVENT_PAT = {"高富帅", "白富美", "虚涨分歧", "虚跌分歧", "涨势将尽", "跌势将尽"}

CSS = """
:root{--bg:#f3f5f8;--panel:#ffffff;--panel2:#f4f6f9;--line:#e3e7ee;--line2:#cfd6e0;--ink:#1c2230;--muted:#6b7585;--dim:#a3adbb;
--up:#d8323a;--down:#178a4c;--amber:#b4680a;--cyan:#0b6fb8;--cyan-dim:rgba(11,111,184,.08);--up-dim:rgba(216,50,58,.08);--down-dim:rgba(23,138,76,.09);--amber-dim:rgba(180,104,10,.1);
--grid:rgba(11,111,184,.06);--glow-up:none;--glow-down:none;--glow-cyan:none;--glow-amber:none;--mark:#1c2230;--topbg:rgba(255,255,255,.88);--hover:rgba(11,111,184,.05)}
:root[data-theme="dark"]{--bg:#070b12;--panel:#0d141f;--panel2:#111a27;--line:#1b2636;--line2:#263348;--ink:#d9e1ec;--muted:#7f8da1;--dim:#55627a;
--up:#ff5a5f;--down:#2fd27a;--amber:#f2b544;--cyan:#4cc9f0;--cyan-dim:rgba(76,201,240,.14);--up-dim:rgba(255,90,95,.12);--down-dim:rgba(47,210,122,.12);--amber-dim:rgba(242,181,68,.13);
--grid:rgba(76,201,240,.035);--glow-up:0 0 10px rgba(255,90,95,.45);--glow-down:0 0 10px rgba(47,210,122,.45);--glow-cyan:0 0 8px #4cc9f0;--glow-amber:0 0 8px #f2b544;--mark:#fff;--topbg:rgba(7,11,18,.9);--hover:rgba(76,201,240,.04)}
:root{--sans:-apple-system,"PingFang SC","Microsoft YaHei","Noto Sans CJK SC","Segoe UI",Roboto,sans-serif}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}:root[data-theme="dark"]{color-scheme:dark}
body{font-family:var(--sans);background:var(--bg);color:var(--ink);font-size:14px;line-height:1.6;
background-image:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);background-size:28px 28px;background-attachment:fixed}
a{color:var(--cyan);text-decoration:none}a:hover{text-decoration:underline}
.num,td,.kpi .v,.bar-val,.badge,.pill,.tag,.hd .sub,.status,.ft{font-family:var(--mono);font-variant-numeric:tabular-nums}
td{font-family:var(--mono)}
.top{background:var(--topbg);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
.top .in{max-width:1120px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.brand{font-weight:700;font-size:16px;letter-spacing:1px;color:var(--ink);font-family:var(--mono)}
.brand::before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--down);box-shadow:var(--glow-down);margin-right:9px;vertical-align:1px;animation:pulse 2.4s ease-in-out infinite}
.brand small{display:block;font-weight:400;font-size:11px;color:var(--muted);letter-spacing:0;font-family:var(--sans);margin-left:17px}
.nav a{color:var(--muted);margin-left:16px;font-size:13px;padding:4px 0;border-bottom:1px solid transparent}
.nav button{margin-left:16px;font:inherit;font-size:12px;color:var(--muted);background:var(--panel2);border:1px solid var(--line2);border-radius:4px;padding:3px 9px;cursor:pointer;font-family:var(--mono)}.nav button:hover{color:var(--ink)}.nav a.on{color:var(--cyan);border-bottom-color:var(--cyan)}.nav a:hover{color:var(--ink);text-decoration:none}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}
.wrap{max-width:1120px;margin:0 auto;padding:18px 16px}
.hd{display:flex;align-items:flex-end;justify-content:space-between;gap:10px;flex-wrap:wrap;margin:4px 0 14px}
.hd h1{font-size:22px;letter-spacing:.5px;font-family:var(--mono);font-weight:600}
.hd .sub{color:var(--muted);font-size:12px;margin-top:4px}
.badge{padding:7px 14px;border-radius:4px;font-weight:600;font-size:12.5px;white-space:nowrap;border:1px solid}
.badge.strong{background:var(--up-dim);color:var(--up);border-color:rgba(255,90,95,.4);box-shadow:var(--glow-up)}
.badge.weak{background:var(--down-dim);color:var(--down);border-color:rgba(47,210,122,.4);box-shadow:var(--glow-down)}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-bottom:12px}
.kpi{background:var(--panel);padding:12px 14px}
.kpi .v{font-size:26px;font-weight:600;line-height:1.1;letter-spacing:-.5px}.kpi .k{color:var(--muted);font-size:11px;margin-top:4px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px 16px;margin-bottom:12px}
.card h3{font-size:13px;margin-bottom:10px;color:var(--ink);font-weight:600;display:flex;align-items:center;gap:8px}
.card h3::before{content:"";width:3px;height:14px;background:var(--cyan);box-shadow:var(--glow-cyan)}
.card h3.blue::before{background:var(--amber);box-shadow:var(--glow-amber)}
.bar-row{display:flex;align-items:center;margin:5px 0;font-size:12px}
.bar-label{width:88px;flex:none;color:var(--ink)}.bar-label.sm{width:64px}
.bar-track{flex:1;background:var(--panel2);height:12px;margin:0 10px;position:relative;border:1px solid var(--line);
background-image:repeating-linear-gradient(90deg,transparent 0 5px,var(--bg) 5px 6px)}
.bar-fill{display:block;height:100%;background:var(--dim)}
.bar-fill.red{background:var(--up);box-shadow:var(--glow-up)}.bar-fill.green{background:var(--down);box-shadow:var(--glow-down)}
.bar-val{width:56px;text-align:right;flex:none;color:var(--ink)}
.view{background:var(--panel);border:1px solid var(--line2);border-left:3px solid var(--amber);border-radius:4px;padding:12px 16px;margin-bottom:12px;font-family:var(--mono);font-size:13px;line-height:1.75}
.view b{color:var(--amber)}
.view::after{content:"▌";color:var(--amber);animation:blink 1.1s steps(1) infinite;margin-left:2px}
.sec{margin-bottom:12px}
.sec-h{display:flex;align-items:baseline;gap:8px;padding:8px 12px;background:var(--panel2);border:1px solid var(--line);border-bottom:0;border-radius:6px 6px 0 0;border-left:3px solid var(--dim)}
.sec-h.p-gao{border-left-color:var(--up)}.sec-h.p-bai{border-left-color:var(--down)}.sec-h.p-warn{border-left-color:var(--amber)}.sec-h.p-good{border-left-color:var(--cyan)}
.sec-t{font-weight:600;font-size:14px}.sec-n{color:var(--muted);font-size:12px;font-family:var(--mono)}.sec-d{color:var(--dim);font-size:11px;margin-left:auto}
.tbl{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:0 0 6px 6px}
table{width:100%;border-collapse:collapse;min-width:560px}
th,td{padding:7px 9px;text-align:center;border-bottom:1px solid var(--line);font-size:12.5px;white-space:nowrap}
th{background:var(--panel2);color:var(--muted);font-weight:500;font-size:11px;font-family:var(--sans)}
tr:last-child td{border-bottom:0}
tbody tr:hover td{background:var(--hover)}
td.b{font-weight:600}.up{color:var(--up)}.down{color:var(--down)}.muted{color:var(--muted)}
.tag{font-size:10.5px;padding:1px 7px;border-radius:3px;white-space:nowrap;margin-right:3px;border:1px solid}
.tag-best{background:var(--up-dim);color:var(--up);border-color:rgba(255,90,95,.4)}
.tag-warn{background:var(--amber-dim);color:var(--amber);border-color:rgba(242,181,68,.4)}
.tag-watch{background:var(--panel2);color:var(--muted);border-color:var(--line2)}
.best-card{display:inline-block;background:var(--up-dim);border:1px solid rgba(255,90,95,.35);border-radius:4px;padding:5px 11px;margin:3px 6px 3px 0;font-size:13px;font-family:var(--mono)}
.ev{margin:4px 0;font-size:13px}.star{color:var(--amber);font-size:11px;margin-right:4px}
.hint{background:var(--up-dim);border-left:3px solid var(--up);padding:5px 10px;margin:5px 0;font-size:12.5px;border-radius:0 4px 4px 0}
ul{margin-left:20px}li{margin:3px 0}
details{margin-bottom:10px}summary{cursor:pointer;font-weight:600;padding:9px 12px;background:var(--panel);border:1px solid var(--line);border-radius:6px;list-style:none;display:flex;align-items:center;gap:8px}
summary::-webkit-details-marker{display:none}summary::after{content:"[+]";margin-left:auto;font-weight:400;color:var(--cyan);font-size:12px;font-family:var(--mono)}
details[open] summary{border-radius:6px 6px 0 0}details[open] summary::after{content:"[−]"}
details .tbl{border-radius:0 0 6px 6px}
.ft{margin-top:20px;padding-top:12px;border-top:1px solid var(--line);color:var(--dim);font-size:11px;line-height:1.9}
.arch{list-style:none;margin:0}.arch li{display:flex;justify-content:space-between;gap:10px;padding:10px 4px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.arch li:last-child{border-bottom:0}.arch .d{font-weight:600;min-width:110px;font-family:var(--mono)}.arch .m{color:var(--muted);font-size:12px}
.pill{display:inline-block;font-size:11px;padding:1px 8px;border-radius:3px;background:var(--panel2);color:var(--muted);margin-left:4px;border:1px solid var(--line2)}
.pill.up{background:var(--up-dim);color:var(--up);border-color:rgba(255,90,95,.35)}.pill.down{background:var(--down-dim);color:var(--down);border-color:rgba(47,210,122,.35)}
.spark{vertical-align:middle}
.status{font-size:12px;color:var(--muted);margin-bottom:10px}
.status .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--down);box-shadow:var(--glow-down);margin-right:5px}
.status .dot.stale{background:var(--amber);box-shadow:var(--glow-amber)}
.rule{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px 16px;margin-bottom:10px}
.rule h4{font-size:14px;margin-bottom:6px;color:var(--cyan);font-family:var(--mono)}
code{background:var(--panel2);padding:1px 6px;border-radius:3px;font-size:12px;font-family:var(--mono);color:var(--amber)}
.today{background:var(--panel);border:1px solid var(--line2);border-left:4px solid var(--cyan);border-radius:8px;padding:14px 18px;margin-bottom:12px}
.today-h{font-family:var(--mono);font-size:13px;color:var(--muted);margin-bottom:8px}
.today-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.today-cell{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:10px 12px}
.today-k{font-size:11px;color:var(--muted);font-family:var(--mono)}.today-v{font-size:22px;font-weight:700;line-height:1.2;margin:2px 0}.today-s{font-size:12.5px;color:var(--ink)}
@media (max-width:720px){.today-grid{grid-template-columns:1fr}}
.pnl-row{border-top:1px dashed var(--line2);padding-top:8px;margin-top:4px}
.pnl-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:10px}.pnl-kpis>div{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:8px 10px}.pnl-kpis .k{display:block;font-size:11px;color:var(--muted);font-family:var(--mono)}.pnl-kpis b{font-size:20px;font-family:var(--mono)}
@media (max-width:720px){.pnl-kpis{grid-template-columns:repeat(2,1fr)}}
.score{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
.score-l,.score-r{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px 18px}
.score-t{color:var(--muted);font-size:12px;font-family:var(--mono)}
.score-big{font-family:var(--mono);font-size:56px;font-weight:700;line-height:1.1;margin:6px 0 2px;letter-spacing:-1px}
.score-sep{font-size:18px;color:var(--muted);margin:0 14px 0 6px;font-weight:500}
.score-sub{color:var(--muted);font-size:12px;margin-bottom:12px}
.score-row{display:flex;gap:8px;align-items:baseline;font-size:13px;padding:5px 0;border-top:1px solid var(--line)}.score-row span{color:var(--muted);width:120px}.score-row b{font-family:var(--mono);font-size:15px}
.cal-head{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;font-size:11px;color:var(--muted);text-align:center;margin-bottom:4px}
.cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}
.cal-cell{aspect-ratio:1.3;border-radius:5px;background:var(--panel2);border:1px solid var(--line);display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:var(--mono);font-size:11px;color:var(--muted)}
.cal-cell .m{font-size:15px;font-weight:700;line-height:1}
.cal-cell.ok{background:var(--down-dim);border-color:rgba(47,210,122,.5);color:var(--down)}.cal-cell.bad{background:var(--up-dim);border-color:rgba(255,90,95,.5);color:var(--up)}
.cal-cell.pend{border-color:var(--amber);color:var(--amber)}.cal-cell.bf{border-style:dashed}.cal-legend i.bf{border-style:dashed;border-color:var(--muted)}.cal-cell.wk{opacity:.35}.cal-cell.future{opacity:.5;border-style:dashed}.cal-cell.empty{border:0;background:transparent}
.cal-legend{font-size:11px;color:var(--muted);margin-top:8px}.cal-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 10px;vertical-align:-1px;border:1px solid var(--line)}
.cal-legend i.ok{background:var(--down)}.cal-legend i.bad{background:var(--up)}.cal-legend i.pend{border-color:var(--amber)}.cal-legend i.none{background:var(--panel2)}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px}
.step{position:relative;padding:10px 12px 10px 26px;border:1px solid var(--line);border-radius:6px;background:var(--panel2);font-size:12.5px;line-height:1.6}
.step-dot{position:absolute;left:10px;top:14px;width:8px;height:8px;border-radius:50%;background:var(--dim)}
.step.done .step-dot{background:var(--cyan);box-shadow:var(--glow-cyan)}.step.ok .step-dot{background:var(--down)}.step.bad .step-dot{background:var(--up)}
.step-t{font-weight:600;margin-bottom:2px}.step.wait{opacity:.6}
@media (max-width:720px){.score{grid-template-columns:1fr}.steps{grid-template-columns:1fr}.score-big{font-size:44px}}
.gauge{display:flex;align-items:center;gap:10px;font-family:var(--mono);font-size:11px;color:var(--muted);margin-top:6px}
.gauge .track{position:relative;flex:1;max-width:260px;height:6px;background:linear-gradient(90deg,var(--down) 0,var(--panel2) 50%,var(--up) 100%);border-radius:3px;opacity:.9}
.gauge .mark{position:absolute;top:-4px;width:2px;height:14px;background:var(--mark);box-shadow:var(--glow-cyan);transform:translateX(-1px)}
.gauge .tick{position:absolute;top:-2px;left:50%;width:1px;height:10px;background:var(--dim)}
svg text{fill:var(--muted)}
:focus-visible{outline:2px solid var(--cyan);outline-offset:2px}
@media (prefers-reduced-motion:reduce){.brand::before,.view::after{animation:none}}
@media (max-width:720px){.kpis{grid-template-columns:repeat(3,1fr)}.grid2{grid-template-columns:1fr}.hd h1{font-size:18px}.nav a{margin-left:10px;font-size:12px}.wrap{padding:12px}table{min-width:520px}summary .sec-d{display:none}.kpi .v{font-size:22px}body{background-attachment:scroll}}
"""


def cls(v):
    return "up" if v > 0 else ("down" if v < 0 else "")


def s(v, p=2):
    return f"{v:+.{p}f}%"


def pat_disp(p):
    return "平盘" if p == "未分类" else p


def spark(closes, w=72, h=20):
    if not closes or len(closes) < 3:
        return ""
    lo, hi = min(closes), max(closes)
    rng = (hi - lo) or 1
    pts = " ".join(f"{i * w / (len(closes) - 1):.1f},{h - 2 - (c - lo) / rng * (h - 4):.1f}" for i, c in enumerate(closes))
    color = "#ff5a5f" if closes[-1] >= closes[0] else "#2fd27a"
    return (f"<svg class='spark' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
            f"<polyline fill='none' stroke='{color}' stroke-width='1.5' points='{pts}'/></svg>")


def layout(title, body, nav_on, root="", desc=""):
    gen = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M")
    nav = [("index.html", "最新日报", "home"), ("archive.html", "历史归档", "archive"),
           ("trend.html", "信号趋势", "trend"), ("macd.html", "MACD买卖点", "macd"), ("chart.html", "K线形态图", "chart"), ("stats.html", "历史战绩", "stats"), ("erqu.html", "二区实盘", "erqu"), ("cta.html", "趋势回测", "cta"), ("method.html", "方法说明", "method")]
    nav_html = "".join(f"<a href='{root}{h}' class='{'on' if k == nav_on else ''}'>{t}</a>" for h, t, k in nav)
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#070b12"><title>{title}</title>
<meta name="description" content="{desc or '国内期货54品种 量·仓·价三维八种形态每日自动扫描公示'}">
<script>(function(){{try{{var t=localStorage.getItem('theme');if(t==='dark')document.documentElement.setAttribute('data-theme','dark');}}catch(e){{}}}})();</script>
<style>{CSS}</style></head><body>
<div class="top"><div class="in"><a class="brand" href="{root}index.html">{SITE_TITLE}<small>国内期货 54 品种 · 量仓价三维自动扫描 · 每交易日收盘后更新</small></a>
<nav class="nav">{nav_html}<button type="button" id="themeBtn" aria-label="切换深浅色">深色</button></nav></div></div>
<div class="wrap">{body}
<div class="ft">信号判定：量·仓·价三维分类 ｜ 三档标注依据：400天历史回测（13014个信号）｜ 白富美经全年数据验证对后市方向无显著预测力，降级观察 ｜ 数据来源：新浪财经（akshare）｜ 理论参考：北大期货班八种形态<br>
本站内容为程序自动生成，仅供学习交流，不构成任何投资建议。页面生成时间：{gen}（北京时间）</div>
</div>
<script>(function(){{var b=document.getElementById('themeBtn'),h=document.documentElement;function sync(){{b.textContent=h.getAttribute('data-theme')==='dark'?'浅色':'深色';}}sync();
b.addEventListener('click',function(){{var d=h.getAttribute('data-theme')==='dark';if(d)h.removeAttribute('data-theme');else h.setAttribute('data-theme','dark');try{{localStorage.setItem('theme',d?'light':'dark');}}catch(e){{}}sync();}});}})();</script>
</body></html>"""


def build_report_body(data, prev, dates_sorted, root="", streaks=None, macd=None):
    streaks = streaks or {}
    macd = macd or []
    D = data["data_date"]
    allr = data["all_results"]
    up_c, down_c, strong = data["up_count"], data["down_count"], data["strong_count"]
    by_name = {i["name"]: i for i in allr}

    market = data.get("market") or {}
    mom = market.get("mom20_median")
    if mom is None:
        REGIME_TXT, REGIME_MOM, regime_cls, weak_market = "数据积累中", "--", "strong", False
    else:
        weak_market = market.get("regime") == "弱势"
        REGIME_TXT = "弱势市" if weak_market else "强势市"
        REGIME_MOM = f"{mom:+.2f}"
        regime_cls = "weak" if weak_market else "strong"

    gauge_pct = 50.0 if mom is None else max(0.0, min(100.0, (mom + 10) / 20 * 100))

    def gao_tags(it):
        pc, hc = it["price_change_pct"], it["hold_change_pct"]
        tags = []
        if weak_market:
            tags.append(("best", "🛡抗跌先锋"))
        if pc > 3:
            tags.append(("warn", "⚠️追高"))
        elif 0 < pc <= 2 and 2 <= hc <= 5:
            tags.append(("best", "⭐⭐优选"))
        return tags

    # 共振主线
    sec_pat = {}
    for it in allr:
        if it["pattern"] in ("高富帅", "白富美"):
            sec_pat.setdefault((SECTOR.get(it["symbol"], "其他"), it["pattern"]), []).append(it["name"])
    res_lines = [f"{sec} {pat}×{len(ns)}：{'、'.join(ns[:4])}" for (sec, pat), ns in sec_pat.items() if len(ns) >= 2]
    resonance = "；".join(res_lines) if res_lines else "今日无明显板块共振，多为孤立信号。"

    warn_items = sorted(data["patterns"]["涨势将尽"]["items"], key=lambda x: x["hold_change_pct"])[:5]
    warn_txt = "、".join(f"{i['name']}({s(i['price_change_pct'], 1)}/减仓{s(i['hold_change_pct'], 1)})" for i in warn_items) or "今日无"

    watch = []
    for i in data["patterns"]["虚涨分歧"]["items"]:
        if i["hold_change_pct"] >= 5:
            vr = i["today_vol"] / max(i["vol_20ma"], 1)
            watch.append(f"{i['name']} 增仓{s(i['hold_change_pct'], 1)}但量比仅{vr:.2f}，明日补量则转高富帅，持续缩量防冲高回落")
    watch = watch[:4]

    # 与上一交易日对比
    new_sig, exit_sig, prev_date = [], [], None
    if prev:
        prev_date = prev["data_date"]
        pm = {i["symbol"]: i["pattern"] for i in prev["all_results"]}
        for i in allr:
            p = pm.get(i["symbol"])
            if p and p != i["pattern"]:
                if i["pattern"] in ("高富帅", "白富美") and p not in ("高富帅", "白富美"):
                    new_sig.append(f"{i['name']}：{pat_disp(p)} → {i['pattern']}")
                if p in ("高富帅", "白富美") and i["pattern"] not in ("高富帅", "白富美"):
                    exit_sig.append(f"{i['name']}：{p} → {pat_disp(i['pattern'])}")

    # 事件
    today_ev = events_cal.get_events(D)
    upcoming = events_cal.get_upcoming(D, 7)
    monthly = events_cal.get_monthly_notes(D)
    hints = []
    for e in today_ev:
        for nm in [x for x in str(e.get("impact", "")).replace("，", "、").split("、") if x]:
            it = by_name.get(nm)
            if it and it["pattern"] in EVENT_PAT:
                hints.append(f"{nm} 今日恰为「{it['pattern']}」，事件落地或成方向引爆点")

    def ev_line(e):
        d = f"<span class='muted'>{e['date']} </span>" if e.get("date") else ""
        return (f"<div class='ev'><span class='star'>{'★' * e.get('imp', 1)}</span>{d}"
                f"<b>{e.get('time', '')}</b> {e.get('name', '')} <span class='muted'>（影响：{e.get('impact', '')}）</span></div>")

    events_html = "".join(ev_line(e) for e in today_ev) or "<div class='muted'>今日无关键事件</div>"
    hints_html = "".join(f"<div class='hint'>🎯 {h}</div>" for h in hints[:6])
    if len(hints) > 6:
        hints_html += f"<div class='muted' style='font-size:12px'>另有 {len(hints) - 6} 个相关品种，见各形态明细</div>"
    up_html = "".join(ev_line(e) for e in upcoming) or "<div class='muted'>未来7天暂无重磅事件</div>"
    mon_html = "".join(f"<div class='ev muted'>· {n}</div>" for n in monthly)

    maxc = max(data["patterns"][p]["count"] for p in PATTERNS) or 1
    dist_html = ""
    for p in PATTERNS:
        c = data["patterns"][p]["count"]
        fc = {"高富帅": "bar-fill red", "白富美": "bar-fill green"}.get(p, "bar-fill")
        dist_html += (f"<div class='bar-row'><span class='bar-label'>{PAT_ICON[p]} {p}</span>"
                      f"<span class='bar-track'><span class='{fc}' style='width:{c / maxc * 100:.0f}%'></span></span>"
                      f"<span class='bar-val'>{c}</span></div>")

    top10 = sorted(allr, key=lambda x: x["price_change_pct"], reverse=True)[:10]
    maxg = top10[0]["price_change_pct"] if top10 and top10[0]["price_change_pct"] > 0 else 1
    top_html = ""
    for i in top10:
        w = max(i["price_change_pct"], 0) / maxg * 100
        top_html += (f"<div class='bar-row'><span class='bar-label sm'>{i['name']}</span>"
                     f"<span class='bar-track'><span class='bar-fill red' style='width:{w:.0f}%'></span></span>"
                     f"<span class='bar-val {cls(i['price_change_pct'])}'>{s(i['price_change_pct'], 1)}</span></div>")

    has_spark = any(it.get("closes20") for it in allr)

    def detail_table(p):
        cols = ("<th>代码</th><th>品种</th><th>交易所</th><th>收盘</th><th>涨跌</th><th>持仓变化</th><th>量比</th>"
                "<th>成交量</th><th>5日均量</th><th>20日均量</th>" + ("<th>近20日</th>" if has_spark else "") + "<th>标注</th>")
        body = ""
        for it in data["patterns"][p]["items"]:
            vr = it["today_vol"] / max(it["vol_20ma"], 1)
            tags = gao_tags(it) if p == "高富帅" else ([("watch", "观察名单")] if p == "白富美" else [])
            if it.get("is_strong"):
                tags.append(("best", "⭐双20%"))
            st = streaks.get(it["symbol"])
            if st and st[0] == D and st[1] == p and st[2] >= 2:
                tags.append(("watch", f"连续{st[2]}天"))
            tag_html = "".join(f"<span class='tag tag-{c}'>{t}</span>" for c, t in tags)
            body += (f"<tr><td class='b'>{it['symbol']}</td><td>{it['name']}</td><td class='muted'>{it['exchange']}</td>"
                     f"<td>{it['today_close']:g}</td>"
                     f"<td class='{cls(it['price_change_pct'])} b'>{s(it['price_change_pct'], 1)}</td>"
                     f"<td class='{cls(it['hold_change_pct'])}'>{s(it['hold_change_pct'], 1)}</td>"
                     f"<td class='{'up' if vr >= 1 else 'muted'}'>{vr:.2f}</td>"
                     f"<td>{it['today_vol'] / 10000:.1f}万</td><td>{it['vol_5ma'] / 10000:.1f}万</td><td>{it['vol_20ma'] / 10000:.1f}万</td>"
                     + (f"<td>{spark(it.get('closes20'))}</td>" if has_spark else "") + f"<td>{tag_html}</td></tr>")
        if not body:
            body = f"<tr><td colspan='{12 if has_spark else 11}' class='muted'>今日无</td></tr>"
        return f"<div class='tbl'><table><thead><tr>{cols}</tr></thead><tbody>{body}</tbody></table></div>"

    def section(p):
        return (f"<div class='sec'><div class='sec-h {PAT_CLASS[p]}'><span>{PAT_ICON[p]}</span><span class='sec-t'>{p}</span>"
                f"<span class='sec-n'>{data['patterns'][p]['count']} 个</span><span class='sec-d'>{PAT_DESC[p]}</span></div>{detail_table(p)}</div>")

    other_sections = "".join(
        f"<details><summary>{PAT_ICON[p]} {p} <span class='sec-n'>{data['patterns'][p]['count']} 个</span>"
        f"<span class='sec-d'>{PAT_DESC[p]}</span></summary>{detail_table(p)}</details>"
        for p in PATTERNS[2:])

    ranked = sorted(allr, key=lambda x: x["hold_change_pct"], reverse=True)
    full_rows = "".join(
        f"<tr><td class='muted'>{n}</td><td class='b'>{it['symbol']}</td><td>{it['name']}</td><td class='muted'>{SECTOR.get(it['symbol'], '')}</td>"
        f"<td>{pat_disp(it['pattern'])}</td><td>{it['today_close']:g}</td>"
        f"<td class='{cls(it['price_change_pct'])}'>{s(it['price_change_pct'], 1)}</td>"
        f"<td class='{cls(it['hold_change_pct'])}'>{s(it['hold_change_pct'], 1)}</td>"
        f"<td>{it['today_vol'] / max(it['vol_20ma'], 1):.2f}</td><td class='{cls(it.get('mom20', 0))}'>{s(it.get('mom20', 0), 1)}</td></tr>"
        for n, it in enumerate(ranked, 1))
    full_table = ("<div class='tbl' style='border-radius:8px'><table><thead><tr><th>#</th><th>代码</th><th>品种</th><th>板块</th><th>形态</th><th>收盘</th>"
                  "<th>涨跌</th><th>持仓变化</th><th>量比</th><th>20日动量</th></tr></thead><tbody>" + full_rows + "</tbody></table></div>")

    best_items = [it for it in data["patterns"]["高富帅"]["items"] if any("优选" in t or "抗跌" in t for _, t in gao_tags(it))]
    best_html = "".join(f"<span class='best-card'>{it['name']} <b class='up'>{s(it['price_change_pct'], 1)}</b> 增仓{s(it['hold_change_pct'], 1)}</span>"
                        for it in best_items) or "<span class='muted'>今日无⭐⭐优选信号</span>"

    # MACD 八策略买卖点（当日首发信号）+ 与形态的共振/冲突
    pat_by_sym = {i["symbol"]: i for i in allr}
    LONG_PATS, SHORT_PATS = {"高富帅", "跌势将尽"}, {"白富美", "涨势将尽"}
    macd_rows, n_res = "", 0
    for sg in macd:
        it = pat_by_sym.get(sg["symbol"])
        pat = it["pattern"] if it else "—"
        agree = (sg["direction"] == "多" and pat in LONG_PATS) or (sg["direction"] == "空" and pat in SHORT_PATS)
        conflict = (sg["direction"] == "多" and pat in SHORT_PATS) or (sg["direction"] == "空" and pat in LONG_PATS)
        n_res += agree
        res_tag = ("<span class='tag tag-best'>⚡双重共振</span>" if agree else
                   "<span class='tag tag-warn'>形态相反</span>" if conflict else "")
        dcls = "up" if sg["direction"] == "多" else "down"
        macd_rows += (f"<tr><td class='b {dcls}'>{sg['direction']}</td><td class='b'>{sg['symbol']}</td><td>{sg['name']}</td>"
                      f"<td style='text-align:left'>{sg['sid']}·{sg['short']}<div class='muted' style='font-size:10.5px'>{macd8.STRAT_MEANING[sg['sid'] - 1]}</div></td>"
                      f"<td>{sg['close']:g}</td><td class='{cls(sg['dif_pct'])}'>{sg['dif_pct']:+.2f}%</td>"
                      f"<td>{pat_disp(pat)}</td><td>{res_tag}</td></tr>")
    n_long = sum(1 for x in macd if x["direction"] == "多")
    macd_html = (f"<div class='card'><h3 class='blue'>MACD 八策略买卖点（今日首发 {len(macd)} 个：多 {n_long} / 空 {len(macd) - n_long}，双重共振 {n_res}）</h3>"
                 + (f"<div class='tbl' style='border-radius:8px'><table><thead><tr><th>方向</th><th>代码</th><th>品种</th><th style='text-align:left'>策略</th>"
                    f"<th>收盘</th><th>DIF偏离</th><th>今日形态</th><th>共振</th></tr></thead><tbody>{macd_rows}</tbody></table></div>"
                    if macd_rows else "<div class='muted'>今日无首发买卖点信号</div>")
                 + "<div class='muted' style='font-size:11.5px;margin-top:6px'>首发=昨日未触发、今日触发；双重共振=买卖点方向与量仓价形态方向一致（多↔高富帅/跌势将尽，空↔白富美/涨势将尽）。"
                   "回测提示：空头四策略历史表现弱，详见「历史战绩」。</div></div>")

    # 上/下一交易日导航
    idx = dates_sorted.index(D) if D in dates_sorted else -1
    prev_link = f"<a href='{root}reports/{dates_sorted[idx - 1]}.html'>← {dates_sorted[idx - 1]}</a>" if idx > 0 else ""
    next_link = f"<a href='{root}reports/{dates_sorted[idx + 1]}.html'>{dates_sorted[idx + 1]} →</a>" if 0 <= idx < len(dates_sorted) - 1 else ""

    stale_note = ""
    if data.get("backfilled"):
        stale_note += "<div class='status'><span class='dot stale'></span>本日为回填数据：由 2026-10-15 抓取的历史日线按同一规则重算，换月品种的持仓变化可能与当日实时快照略有出入。</div>"
    if data.get("error_count"):
        stale_note += f"<div class='status'><span class='dot stale'></span>本日 {data['error_count']} 个品种数据获取失败（{'、'.join(data.get('errors', []))}），未纳入统计。</div>"

    principles = """<b>选择标的</b>：高富帅=新资金涌入选多点；白富美=新资金做空选空点；底部三角形有大行情；岛型反转常规3-5天。<br>
<b>判断趋势</b>：破趋势线→反弹不创新高→破颈线；震荡用摆动指数，趋势用均线。<br>
<b>仓位管理</b>：固定风险比率2-5%按损定量；金字塔加码每次加上一次的60-80%；破加→回加→再破加。<br>
<b>止损止盈</b>：止损位坚决不变、止盈位随时调整；破21线平、破颈线全平；连拉3-5大阳3根跑一半5根全平仓；时间止损波段3天分钟8根K线。<br>
<b>目标测算</b>：第一目标位=原形态高度一倍；管道线目标加2-3根管道线；不吃鱼头鱼尾只吃2.5根线。"""

    return f"""
<div class='hd'><div><h1>期货八种形态日报 · {D}</h1>
<div class='sub'>数据日期 {D} ｜ {data['valid_count']}/{data['total_scanned']} 品种有效 ｜ 量比基准：5日/20日均量 ｜ 扫描时间 {data.get('scan_date', '')}
 &nbsp; {prev_link} &nbsp; {next_link} &nbsp; <a href='{root}data/{D}.json'>原始数据 JSON</a></div></div>
<div><div class='badge {regime_cls}'>市场环境 {REGIME_TXT} ｜ 20日中位动量 {REGIME_MOM}%</div>
<div class='gauge'><span>-10%</span><span class='track'><span class='tick'></span><span class='mark' style='left:{gauge_pct:.1f}%'></span></span><span>+10%</span></div></div></div>
{stale_note}
<div class='kpis'>
<div class='kpi'><div class='v up'>{up_c}</div><div class='k'>上涨家数</div></div>
<div class='kpi'><div class='v down'>{down_c}</div><div class='k'>下跌家数</div></div>
<div class='kpi'><div class='v'>{strong}</div><div class='k'>双20%强信号</div></div>
<div class='kpi'><div class='v'>{len(best_items)}</div><div class='k'>⭐⭐优选/抗跌</div></div>
<div class='kpi'><div class='v'>{len(macd)}</div><div class='k'>MACD买卖点</div></div>
</div>
<div class='view'><b>大势判断：</b>今日 {up_c} 涨 {down_c} 跌，双20%强信号 {strong} 个，{'资金进攻力度强，顺势为主。' if up_c > down_c else '空方占优，防守为主。'}{resonance}</div>
<div class='grid2'><div class='card'><h3>八形态分布</h3>{dist_html}</div><div class='card'><h3>涨幅 TOP 10</h3>{top_html}</div></div>

<div class='card'><h3 class='blue'>⭐⭐ 今日优选信号</h3><div>{best_html}</div>
<div class='muted' style='font-size:11.5px;margin-top:6px'>优选标准：涨幅0~2% 且 增仓2~5%（400天回测5日胜率55.1%）；涨幅&gt;3%为⚠️追高（次日胜率仅44%）；弱势市里的高富帅为🛡抗跌先锋（胜率58%）</div></div>
{macd_html}
{section("高富帅")}{section("白富美")}
<div class='grid2'>
<div class='card'><h3>警惕名单（涨势将尽）</h3><ul><li>{warn_txt}</li><li class='muted'>价格与量仓背离时「最终还是看量」——这些品种追涨风险最大，持仓者准备反手。</li></ul></div>
<div class='card'><h3 class='blue'>明日观察点</h3><ul>{"".join(f"<li>{w}</li>" for w in watch) or "<li class='muted'>无特殊观察点</li>"}</ul></div>
</div>
<div class='grid2'>
<div class='card'><h3>关键事件预警（引爆点）</h3><b style='font-size:12.5px'>今日关键事件（{D}）</b>{events_html}{hints_html}
<b style='font-size:12.5px;display:block;margin-top:8px'>未来7天重磅事件</b>{up_html}{f"<b style='font-size:12.5px;display:block;margin-top:8px'>本月提醒</b>{mon_html}" if mon_html else ""}</div>
<div class='card'><h3>形态变化（vs 上一交易日 {prev_date or '—'}）</h3>
<b style='font-size:12.5px'>新出现强信号</b>{"".join(f"<div class='ev'>🆕 {x}</div>" for x in new_sig) or "<div class='muted'>无</div>"}
<b style='font-size:12.5px;display:block;margin-top:8px'>退出强信号</b>{"".join(f"<div class='ev'>↩︎ {x}</div>" for x in exit_sig) or "<div class='muted'>无</div>"}</div>
</div>
<div class='card'><h3>其余六种形态详情</h3>{other_sections}</div>
<details><summary>全品种总表（{len(ranked)} 个，按持仓变化排序）</summary>{full_table}</details>
<details><summary>北大期货班交易原则</summary><div class='card' style='border-radius:0 0 8px 8px;line-height:2'>{principles}</div></details>
"""


def archive_body(datas, macd_by_date=None):
    macd_by_date = macd_by_date or {}
    rows = ""
    for d in sorted(datas, key=lambda x: x["data_date"], reverse=True):
        D = d["data_date"]
        gao = d["patterns"]["高富帅"]["count"]
        bai = d["patterns"]["白富美"]["count"]
        gao_names = "、".join(i["name"] for i in d["patterns"]["高富帅"]["items"][:5])
        regime = (d.get("market") or {}).get("regime", "")
        rows += (f"<li><span class='d'><a href='reports/{D}.html'>{D}</a></span>"
                 f"<span>涨 <b class='up'>{d['up_count']}</b> 跌 <b class='down'>{d['down_count']}</b>"
                 f"<span class='pill up'>👑 {gao}</span><span class='pill down'>💎 {bai}</span><span class='pill'>MACD {len(macd_by_date.get(D, []))}</span>{f'<span class=pill>{regime}市</span>' if regime else ''}</span>"
                 f"<span class='m'>{gao_names or '无高富帅'}</span><span class='m'><a href='data/{D}.json'>JSON</a></span></li>")
    return f"<div class='hd'><div><h1>历史归档</h1><div class='sub'>共 {len(datas)} 个交易日 ｜ 点击日期查看当日完整报告</div></div></div><div class='card'><ul class='arch'>{rows}</ul></div>"


def trend_body(datas):
    ds = sorted(datas, key=lambda x: x["data_date"])[-60:]
    if len(ds) < 2:
        return "<div class='hd'><h1>信号趋势</h1></div><div class='card muted'>数据不足两天，趋势图将在积累数据后自动出现。</div>"
    W, H, PAD = 900, 260, 36
    n = len(ds)
    xs = [PAD + i * (W - 2 * PAD) / (n - 1) for i in range(n)]

    gv = [d["patterns"]["高富帅"]["count"] for d in ds]
    bv = [d["patterns"]["白富美"]["count"] for d in ds]
    mx = max(max(gv), max(bv), 1)

    def line(vals, color):
        pts = " ".join(f"{x:.1f},{H - PAD - v / mx * (H - 2 * PAD):.1f}" for x, v in zip(xs, vals))
        dots = "".join(f"<circle cx='{x:.1f}' cy='{H - PAD - v / mx * (H - 2 * PAD):.1f}' r='3' fill='{color}'/>" for x, v in zip(xs, vals))
        return f"<polyline fill='none' stroke='{color}' stroke-width='2' points='{pts}'/>{dots}"

    g, b = line(gv, "#ff5a5f"), line(bv, "#2fd27a")
    labels = "".join(f"<text x='{xs[i]:.0f}' y='{H - 10}' font-size='10' text-anchor='middle' fill='#6b7280'>{ds[i]['data_date'][5:]}</text>"
                     for i in range(0, n, max(1, n // 8)))
    yl = "".join(f"<text x='{PAD - 6}' y='{H - PAD - k / 4 * (H - 2 * PAD) + 4:.0f}' font-size='10' text-anchor='end' fill='#6b7280'>{mx * k / 4:.0f}</text>"
                 f"<line x1='{PAD}' x2='{W - PAD}' y1='{H - PAD - k / 4 * (H - 2 * PAD):.0f}' y2='{H - PAD - k / 4 * (H - 2 * PAD):.0f}' stroke='#1b2636'/>" for k in range(5))
    svg1 = f"<svg viewBox='0 0 {W} {H}' width='100%' style='max-width:{W}px'>{yl}{g}{b}{labels}</svg>"

    # 上涨家数占比 + 市场环境
    def ratio(d):
        t = d["up_count"] + d["down_count"]
        return d["up_count"] / t * 100 if t else 50
    pts = " ".join(f"{x:.1f},{H - PAD - ratio(d) / 100 * (H - 2 * PAD):.1f}" for x, d in zip(xs, ds))
    mid = H - PAD - 0.5 * (H - 2 * PAD)
    yl2 = "".join(f"<text x='{PAD - 6}' y='{H - PAD - k / 4 * (H - 2 * PAD) + 4:.0f}' font-size='10' text-anchor='end' fill='#6b7280'>{k * 25}%</text>" for k in range(5))
    regime_marks = "".join(f"<rect x='{x - 3:.0f}' y='{H - PAD + 2}' width='6' height='5' fill='{'#2fd27a' if (d.get('market') or {}).get('regime') == '弱势' else '#ff5a5f'}'/>" for x, d in zip(xs, ds))
    svg2 = (f"<svg viewBox='0 0 {W} {H}' width='100%' style='max-width:{W}px'>{yl2}<line x1='{PAD}' x2='{W - PAD}' y1='{mid}' y2='{mid}' stroke='#55627a' stroke-dasharray='4 4'/>"
            f"<polyline fill='none' stroke='#4cc9f0' stroke-width='2' points='{pts}'/>{regime_marks}{labels}</svg>")

    # 最近连续出现高富帅的品种
    streak = {}
    for d in ds[-10:]:
        for it in d["patterns"]["高富帅"]["items"]:
            streak[it["name"]] = streak.get(it["name"], 0) + 1
    top = sorted(streak.items(), key=lambda kv: -kv[1])[:12]
    freq = "".join(f"<span class='best-card'>{k} <b>{v}</b> 次</span>" for k, v in top) or "<span class='muted'>无</span>"
    return f"""<div class='hd'><div><h1>信号趋势</h1><div class='sub'>最近 {n} 个交易日</div></div></div>
<div class='card'><h3>每日 👑高富帅（红）/ 💎白富美（绿）数量</h3>{svg1}</div>
<div class='card'><h3>上涨家数占比（蓝线）与市场环境（底部色块：红=强势市，绿=弱势市）</h3>{svg2}</div>
<div class='card'><h3>最近 10 个交易日出现「高富帅」次数最多的品种</h3>{freq}</div>"""


def stats_body(st):
    if not st["span"] or st["n_days"] < 3:
        return ("<div class='hd'><div><h1>历史战绩</h1></div></div><div class='card'><p class='muted'>数据积累中：网站上线后每日自动累积，"
                "有 3 个以上交易日的回算数据后此页自动出现统计。</p></div>")
    t = st["table"]
    order = ["高富帅", "高富帅·优选", "高富帅·抗跌", "高富帅·追高", "白富美", "涨势将尽", "跌势将尽",
             "上涨乏力", "下跌乏力", "虚涨分歧", "虚跌分歧"]

    def cell(a, expect):
        if not a:
            return "<td class='muted'>—</td><td class='muted'>—</td>"
        rate = a.get("win_rate", a["up_rate"])
        c = "up" if (a["avg"] > 0) else "down"
        lab = f"{rate:.0f}%" if expect else f"{a['up_rate']:.0f}%↑"
        return f"<td class='b'>{lab}<span class='muted' style='font-weight:400;font-size:10.5px'> /{a['n']}</span></td><td class='{c}'>{a['avg']:+.2f}%</td>"

    rows = ""
    for g in order:
        if g not in t:
            continue
        r = t[g]
        exp = {1: "预期涨", -1: "预期跌"}.get(r["expect"], "无方向")
        rows += (f"<tr><td class='b' style='text-align:left'>{g}</td><td class='muted'>{exp}</td><td>{r['n_signals']}</td>"
                 + "".join(cell(r.get(k), r["expect"]) for k in (1, 3, 5)) + "</tr>")
    head = ("<tr><th style='text-align:left'>形态 / 标注</th><th>方向</th><th>信号数</th>"
            "<th>1日 正确率/样本</th><th>1日 均收益</th><th>3日 正确率/样本</th><th>3日 均收益</th><th>5日 正确率/样本</th><th>5日 均收益</th></tr>")

    # 最近信号明细（高富帅/白富美，最近 60 条，含后续表现）
    recent = [x for x in st["signals"] if x["pattern"] in ("高富帅", "白富美")]
    recent.sort(key=lambda x: x["date"], reverse=True)
    det = ""
    for x in recent[:60]:
        def f(k):
            v = x["fwd"].get(k)
            return f"<td class='{cls(v)}'>{v:+.2f}%</td>" if v is not None else "<td class='muted'>待定</td>"
        det += (f"<tr><td>{x['date']}</td><td class='b'>{x['name']}</td><td>{x['pattern']}</td><td class='muted'>{x['tag'] or ''}</td>"
                f"<td class='{cls(x['pc'])}'>{x['pc']:+.2f}%</td><td class='{cls(x['hc'])}'>{x['hc']:+.2f}%</td>{f(1)}{f(3)}{f(5)}</tr>")
    return f"""<div class='hd'><div><h1>历史战绩</h1><div class='sub'>回算区间 {st['span'][0]} ~ {st['span'][1]}（{st['n_days']} 个交易日）｜ 规则与每日报告完全相同 ｜ 每日自动更新</div></div></div>
<div class='view'><b>怎么读：</b>"正确率"= 信号发出后第 N 个交易日收盘相对信号日收盘，方向与形态预期一致的比例（高富帅/跌势将尽预期涨，白富美/涨势将尽预期跌）；无方向预期的形态只给"上涨占比↑"。均收益为简单算术平均，未计手续费与滑点。样本少于 30 时参考意义有限。</div>
<div class='card'><h3>按形态统计</h3><div class='tbl' style='border-radius:8px'><table><thead>{head}</thead><tbody>{rows}</tbody></table></div></div>
<div class='card'><h3>MACD 八策略</h3><p style='font-size:13px'>买卖点策略的分策略胜率与最近信号明细见 <a href='macd.html'>MACD买卖点</a> 页。</p></div>
<div class='card'><h3>最近 60 条强信号及后续表现</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th>日期</th><th>品种</th><th>形态</th><th>标注</th><th>当日涨跌</th><th>持仓变化</th><th>后1日</th><th>后3日</th><th>后5日</th></tr></thead><tbody>{det or "<tr><td colspan=9 class=muted>暂无</td></tr>"}</tbody></table></div></div>
<p class='muted' style='font-size:11.5px'>说明：历史形态由长期日线库（新浪主力连续，2026-10-15 起每日续接）按同一规则回算得到；新浪会在主力换月后重新拼接历史序列，因此回算结果与当日快照可能有少量出入。历史形态由各日保存的品种简史（收盘/成交量/持仓）按同一规则回算得到，主力连续合约换月期间的持仓跳变会带来噪音；本页仅为规则自检，不构成投资建议。</p>"""


def macd_body(st, latest_date):
    sigs = sorted(st["macd_signals"], key=lambda x: (x["date"], x["direction"] != "多", x["sid"]), reverse=True)
    recent_dates = sorted({x["date"] for x in sigs}, reverse=True)[:20]
    recent = [x for x in sigs if x["date"] in set(recent_dates)]
    rows = ""
    for x in recent:
        def f(k):
            v = x["fwd"].get(k)
            return f"<td class='{cls(v)}'>{v:+.2f}%</td>" if v is not None else "<td class='muted'>待定</td>"
        dcls = "up" if x["direction"] == "多" else "down"
        rows += (f"<tr><td>{x['date']}</td><td class='b {dcls}'>{x['direction']}</td><td class='b'>{x['name']}</td>"
                 f"<td style='text-align:left'>{x['sid']}·{x['short']}</td><td>{x['close']:g}</td><td class='{cls(x['dif_pct'])}'>{x['dif_pct']:+.2f}%</td>{f(1)}{f(3)}{f(5)}</tr>")
    rules = "".join(
        f"<tr><td class='b {'up' if macd8.STRAT_DIR[i] == '多' else 'down'}'>{macd8.STRAT_DIR[i]}</td><td style='text-align:left'><b>{i + 1}. {macd8.STRAT_SHORT[i]}</b></td>"
        f"<td style='text-align:left;white-space:normal'>{macd8.STRAT_MEANING[i]}</td></tr>" for i in range(8))
    t = st["macd_table"]
    def cell(a):
        if not a:
            return "<td class='muted'>—</td><td class='muted'>—</td>"
        return (f"<td class='b'>{a['win_rate']:.0f}%<span class='muted' style='font-weight:400;font-size:10.5px'> /{a['n']}</span></td>"
                f"<td class='{'up' if a['avg'] > 0 else 'down'}'>{a['avg']:+.2f}%</td>")
    order = [macd8.STRAT_NAMES[i] for i in range(4)] + ["多头合计"] + [macd8.STRAT_NAMES[i] for i in range(4, 8)] + ["空头合计"]
    srows = "".join(f"<tr class='{'b' if g.endswith('合计') else ''}'><td style='text-align:left'>{g}</td><td>{t[g]['n_signals']}</td>"
                    + "".join(cell(t[g].get(k)) for k in (1, 3, 5)) + "</tr>" for g in order if g in t)
    return f"""<div class='hd'><div><h1>MACD 八策略买卖点</h1><div class='sub'>54 品种主力连续日线 ｜ 4 多 4 空镜像策略 ｜ 首发信号（昨日未触发、今日触发）｜ 每日与形态报告同步更新</div></div></div>
<div class='view'><b>指标口径：</b>EMA12−EMA26=DIF，DIF 的 9 日 EMA=DEA，MACD 柱=2×(DIF−DEA)；所有阈值用 DIF/收盘价 的相对偏离度（T1=0.5%、T2=0.8%、零轴带 ±0.5%），以适配不同价格量级的品种。</div>
<div class='card'><h3>八个策略</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th>方向</th><th style='text-align:left'>策略</th><th style='text-align:left'>含义</th></tr></thead><tbody>{rules}</tbody></table></div></div>
<div class='card'><h3>历史表现（按信号方向持有，正=方向正确；回算区间 {st['span'][0]} ~ {st['span'][1]}）</h3>
<div class='tbl' style='border-radius:8px'><table><thead><tr><th style='text-align:left'>策略</th><th>信号数</th><th>1日 胜率/样本</th><th>1日 均收益</th><th>3日 胜率/样本</th><th>3日 均收益</th><th>5日 胜率/样本</th><th>5日 均收益</th></tr></thead><tbody>{srows}</tbody></table></div>
<div class='muted' style='font-size:11.5px;margin-top:6px'>均收益已按方向折算（空头信号价格下跌记为正收益），未计手续费与滑点。样本少于 30 时参考意义有限。</div></div>
<div class='card'><h3>最近 20 个交易日的全部首发信号（{len(recent)} 条）</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th>日期</th><th>方向</th><th>品种</th><th style='text-align:left'>策略</th><th>收盘</th><th>DIF偏离</th><th>后1日</th><th>后3日</th><th>后5日</th></tr></thead><tbody>{rows or "<tr><td colspan=9 class=muted>暂无</td></tr>"}</tbody></table></div></div>"""


def erqu_body():
    import calendar as _cal
    from datetime import datetime as _dt
    import erqu_live
    s = erqu_live.summarize()
    recs = sorted(s["records"], key=lambda r: r["day"], reverse=True)
    by_day = {r["day"]: r for r in recs}
    today = _dt.now(CN_TZ)
    cur_m = today.strftime("%Y-%m")
    cm = s["months"].get(cur_m, {"days": 0, "final_ok": 0, "final_bad": 0, "z2_ok": 0, "z2_bad": 0, "b1330_ok": 0, "b1030_ok": 0, "trades": 0, "trade_wins": 0, "pnl_net": 0.0, "pnl_gross": 0.0})
    pn = s.get("pnl", {"trades": 0, "wins": 0, "net": 0.0, "gross": 0.0, "max_dd": 0.0, "curve": [], "cost": 0.027})

    # ---- 本月记分牌 + 日历格 ----
    y, m = today.year, today.month
    first_wd, ndays = _cal.monthrange(y, m)
    cells = ""
    for _ in range(first_wd):
        cells += "<div class='cal-cell empty'></div>"
    for dnum in range(1, ndays + 1):
        ds = f"{y:04d}-{m:02d}-{dnum:02d}"
        wd = (first_wd + dnum - 1) % 7
        r = by_day.get(ds)
        if wd >= 5:
            cls_ = "wk"
            txt = ""
        elif r and r.get("settled"):
            cls_ = ("ok" if r["correct_final"] else "bad") + (" bf" if r.get("backfilled") else "")
            txt = "✓" if r["correct_final"] else "✗"
        elif r:
            cls_ = "pend"
            txt = "…"
        elif ds <= today.strftime("%Y-%m-%d"):
            cls_ = "none"
            txt = ""
        else:
            cls_ = "future"
            txt = ""
        cells += f"<div class='cal-cell {cls_}' title='{ds}'><span class='d'>{dnum}</span><span class='m'>{txt}</span></div>"
    cal_html = ("<div class='cal'><div class='cal-head'>" + "".join(f"<span>{w}</span>" for w in "一二三四五六日") + "</div>"
                f"<div class='cal-grid'>{cells}</div></div>")
    n_bf = sum(1 for r in recs if r["day"].startswith(cur_m) and r.get("backfilled"))
    total = cm["final_ok"] + cm["final_bad"]
    rate_m = f"{cm['final_ok'] / total * 100:.0f}%" if total else "—"
    score_html = f"""<div class='score'>
<div class='score-l'><div class='score-t'>{y} 年 {m} 月 · 截至今天</div>
<div class='score-big'><span class='up'>{cm['final_ok']}</span><span class='score-sep'>对</span><span class='down'>{cm['final_bad']}</span><span class='score-sep'>错</span></div>
<div class='score-sub'>二区+五区修正 ｜ 正确率 {rate_m} ｜ 已结算 {cm['days']} 个交易日{f"（含回填 {n_bf} 天，虚线框）" if n_bf else ""}</div>
<div class='score-row'><span>二区单独</span><b class='up'>{cm['z2_ok']}</b> 对 <b class='down'>{cm['z2_bad']}</b> 错</div>
<div class='score-row'><span>对照 13:30 价位</span><b>{cm['b1330_ok']}</b> 对 <b>{cm['days'] - cm['b1330_ok']}</b> 错</div>
<div class='score-row'><span>对照 10:30 价位</span><b>{cm['b1030_ok']}</b> 对 <b>{cm['days'] - cm['b1030_ok']}</b> 错</div>
<div class='score-row pnl-row'><span>虚拟仓位本月净收益</span><b class='{'up' if cm['pnl_net'] > 0 else 'down' if cm['pnl_net'] < 0 else ''}'>{cm['pnl_net']:+.2f}%</b> <span class='muted'>{cm['trades']} 笔 · 赢 {cm['trade_wins']}</span></div></div>
<div class='score-r'>{cal_html}<div class='cal-legend'><i class='ok'></i>判对 <i class='bad'></i>判错 <i class='pend'></i>进行中 <i class='none'></i>无记录 <i class='bf'></i>回填（用历史数据按同一规则重算，非当场判定）</div></div></div>"""

    # ---- 今日/最新一天：分时图 + 阶段时间线 ----
    latest = recs[0] if recs else None
    chart_html = ""
    if latest and latest.get("bars"):
        bars = latest["bars"]
        W, H, L, R, T, B = 900, 260, 46, 12, 14, 30
        slots = [f"{h:02d}:{mm:02d}" for h in (9, 10, 11) for mm in range(0, 60, 5) if (h == 9 and mm >= 35) or h == 10 or (h == 11 and mm <= 30)]
        slots += [f"{h:02d}:{mm:02d}" for h in (13, 14) for mm in range(5, 60, 5)] + ["14:00", "15:00"]
        slots = sorted(set(slots))
        xi = {hm: i for i, hm in enumerate(slots)}
        n = len(slots)
        xs = lambda hm: L + xi.get(hm, 0) * (W - L - R) / (n - 1)
        op = latest.get("open_official", latest.get("open_provisional"))
        vals = [b[4] for b in bars] + [op]
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.15 or 1
        lo, hi = lo - pad, hi + pad
        ys = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
        def zone(a, b, label, color):
            return (f"<rect x='{xs(a):.1f}' y='{T}' width='{xs(b) - xs(a):.1f}' height='{H - T - B}' fill='{color}' opacity='.12'/>"
                    f"<text x='{(xs(a) + xs(b)) / 2:.1f}' y='{T + 12}' font-size='10' text-anchor='middle' fill='{color}'>{label}</text>")
        zones = zone("10:05", "10:30", "二区", "#4cc9f0") + zone("13:05", "13:30", "五区", "#f2b544")
        pts = " ".join(f"{xs(b[0]):.1f},{ys(b[4]):.1f}" for b in bars)
        line_color = "#ff5a5f" if bars[-1][4] >= op else "#2fd27a"
        openline = f"<line x1='{L}' x2='{W - R}' y1='{ys(op):.1f}' y2='{ys(op):.1f}' stroke='#9aa4ae' stroke-dasharray='4 4'/><text x='{W - R}' y='{ys(op) - 4:.1f}' font-size='10' text-anchor='end' fill='#9aa4ae'>开盘 {op:.2f}</text>"
        marks = ""
        for hm, key, lab in (("10:30", "price_1030", "10:30 判定"), ("13:30", "price_1330", "13:30 修正")):
            if latest.get(key):
                marks += f"<circle cx='{xs(hm):.1f}' cy='{ys(latest[key]):.1f}' r='4' fill='#fff' stroke='#1c2230' stroke-width='1.5'/><text x='{xs(hm):.1f}' y='{ys(latest[key]) - 9:.1f}' font-size='10' text-anchor='middle' fill='var(--ink)'>{lab}</text>"
        xlabels = "".join(f"<text x='{xs(hm):.1f}' y='{H - 10}' font-size='10' text-anchor='middle' fill='#6b7585'>{hm}</text>" for hm in ("09:35", "10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00") if hm in xi)
        ylabels = "".join(f"<text x='{L - 6}' y='{ys(v) + 4:.1f}' font-size='10' text-anchor='end' fill='#6b7585'>{v:.0f}</text>" for v in (lo + pad, (lo + hi) / 2, hi - pad))
        svg = f"<svg viewBox='0 0 {W} {H}' width='100%' style='max-width:{W}px;display:block'>{zones}{openline}<polyline fill='none' stroke='{line_color}' stroke-width='2' points='{pts}'/>{marks}{xlabels}{ylabels}</svg>"
        def step(done, title, body, state):
            return f"<div class='step {state}'><div class='step-dot'></div><div class='step-t'>{title}</div><div class='step-b'>{body}</div></div>"
        st1 = step(True, "10:30 判定", f"<b>{latest.get('z2', '')}二区</b> · {latest.get('z2_reason', '')}<br>预测：{latest.get('prediction', '')}<br><span class='muted'>{latest.get('judged_at', '')[11:]}</span>", "done" if latest.get("z2") else "wait")
        if "fixed" in latest:
            st2 = step(True, "13:35 五区", f"新高 {'是' if latest['z5_new_high'] else '否'} / 新低 {'是' if latest['z5_new_low'] else '否'} → <b>{'修正为 ' + latest['final'] if latest['fixed'] else '维持 ' + latest['final']}</b><br>最终预测：{latest['prediction_final']}<br><span class='muted'>{latest.get('fixed_at', '')[11:]}</span>", "done")
        else:
            st2 = step(False, "13:35 五区", "等待…", "wait")
        if latest.get("settled"):
            ok = latest["correct_final"]
            st3 = step(True, "收盘结算", f"开 {latest['open_official']:.2f} → 收 {latest['close_official']:.2f}（{latest['actual']}）<br><b class='{'up' if ok else 'down'}'>{'✅ 判对' if ok else '❌ 判错' if ok is not None else '未预测'}</b>（二区单独：{'对' if latest['correct_z2'] else '错'}）<br><span class='muted'>{latest.get('settled_at', '')[11:]}</span>", "done " + ("ok" if ok else "bad"))
        else:
            st3 = step(False, "收盘结算", "等待 15:00 后…", "wait")
        chart_html = f"<div class='card'><h3>最新交易日 {latest['day']} · 上证指数分时（5 分钟）</h3>{svg}<div class='steps'>{st1}{st2}{st3}</div></div>"

    # ---- 累计对比条 ----
    def bar(label, t, color):
        v = t[0] or 0
        return (f"<div class='bar-row'><span class='bar-label' style='width:150px'>{label}</span><span class='bar-track'><span class='bar-fill' style='width:{v:.0f}%;background:{color}'></span></span>"
                f"<span class='bar-val'>{t[0] if t[0] is not None else '—'}%</span></div>")
    cmp_html = ("<div class='card'><h3>累计正确率（前瞻实盘，自 " + (recs[-1]["day"] if recs else "—") + f" 起 {s['days']} 天）</h3>"
                + bar("二区判定（10:30）", s["z2"], "var(--cyan)") + bar("二区 + 五区修正", s["final"], "var(--amber)")
                + bar("对照：10:30 价位 vs 开盘", s["b1030"], "var(--dim)") + bar("对照：13:30 价位 vs 开盘", s["b1330"], "var(--dim)")
                + "<div class='muted' style='font-size:11.5px;margin-top:8px'>回测参考（2023-01~2026-10，914 天，五区到 13:35）：二区 63.4%，二区+修正 73.7%；对照 10:30 价位 71.2%、13:30 价位 82.4%。课程宣称 2024 年 87.96%，同期回测 73.5%。</div></div>")

    # ---- 虚拟仓位卡片 ----
    curve = pn.get("curve", [])
    if len(curve) >= 2:
        W, H, L, R, T, B = 900, 150, 50, 12, 12, 24
        vals = [v for _, v in curve]
        lo, hi = min(vals + [0]), max(vals + [0])
        pad = (hi - lo) * 0.2 or 0.5
        lo, hi = lo - pad, hi + pad
        n = len(curve)
        px = lambda i: L + i * (W - L - R) / (n - 1)
        py = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
        pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, (_, v) in enumerate(curve))
        area = f"{px(0):.1f},{py(0):.1f} " + pts + f" {px(n - 1):.1f},{py(0):.1f}"
        last = curve[-1][1]
        grid = "".join(f"<line x1='{L}' x2='{W - R}' y1='{py(g):.1f}' y2='{py(g):.1f}' stroke='var(--line)' stroke-dasharray='2 3'/><text x='{L - 6}' y='{py(g) + 3:.1f}' font-size='10' text-anchor='end' fill='var(--muted)'>{g:+.1f}%</text>"
                       for g in sorted({round(lo + (hi - lo) * k / 4, 2) for k in range(5)} | {0.0}) if abs(g) < 1e-9 or abs(py(g) - py(0)) > 12)
        xl = "".join(f"<text x='{px(i):.1f}' y='{H - 6}' font-size='10' text-anchor='middle' fill='var(--muted)'>{d[5:]}</text>" for i, (d, _) in enumerate(curve) if i % max(1, n // 8) == 0 or i == n - 1)
        col = "var(--up)" if last >= 0 else "var(--down)"
        curve_svg = (f"<svg viewBox='0 0 {W} {H}' width='100%' style='display:block'>{grid}<line x1='{L}' x2='{W - R}' y1='{py(0):.1f}' y2='{py(0):.1f}' stroke='var(--muted)'/>"
                     f"<polygon points='{area}' fill='{col}' opacity='.12'/><polyline points='{pts}' fill='none' stroke='{col}' stroke-width='2'/>"
                     f"<circle cx='{px(n - 1):.1f}' cy='{py(last):.1f}' r='3.5' fill='{col}'/>{xl}</svg>")
    else:
        curve_svg = "<div class='muted'>结算满两天后显示净值曲线</div>"
    wr = f"{pn['wins'] / pn['trades'] * 100:.0f}%" if pn.get("trades") else "—"
    pnl_html = (f"<div class='card'><h3>虚拟仓位 · 只做多、锁仓次日平（累计 {pn.get('trades', 0)} 笔）</h3>"
                f"<div class='pnl-kpis'><div><span class='k'>累计净收益</span><b class='{'up' if pn.get('net', 0) > 0 else 'down' if pn.get('net', 0) < 0 else ''}'>{pn.get('net', 0):+.2f}%</b></div>"
                f"<div><span class='k'>毛收益</span><b>{pn.get('gross', 0):+.2f}%</b></div><div><span class='k'>胜率</span><b>{wr}</b></div><div><span class='k'>最大回撤</span><b class='down'>{pn.get('max_dd', 0):.2f}%</b></div></div>"
                f"{curve_svg}"
                f"<div class='muted' style='font-size:11.5px;margin-top:8px'>规则：最终判「好」的日子 13:35 以当时价做多 1 份上证指数，收盘锁仓、次日平仓；判「坏」空仓（回测显示做空没有优势）。每笔扣成本 {pn.get('cost', 0.027)}%（股指期货 4 腿手续费 + 滑点估算），不加杠杆。回测 2023-01~2026-10：471 笔，平均每笔 +0.047%，胜率 58%，净累计约 +9.5%。这是纸面记录，不是交易建议。</div></div>")

    # ---- 按月 + 逐日 ----
    mrows = "".join(f"<tr><td>{mm}</td><td>{v['days']}</td><td class='up'>{v['final_ok']}</td><td class='down'>{v['final_bad']}</td>"
                    f"<td class='b'>{round(v['final_ok'] / v['days'] * 100, 1) if v['days'] else '—'}%</td><td class='up'>{v['z2_ok']}</td><td class='down'>{v['z2_bad']}</td>"
                    f"<td>{v['b1030_ok']}</td><td>{v['b1330_ok']}</td><td class='{'up' if v.get('pnl_net', 0) > 0 else 'down' if v.get('pnl_net', 0) < 0 else ''}'>{v.get('pnl_net', 0):+.2f}%</td><td>{v.get('trades', 0)}</td></tr>" for mm, v in sorted(s["months"].items(), reverse=True))
    month_table = (f"<div class='card'><h3>按月统计</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th>月份</th><th>天数</th><th>修正后 对</th><th>修正后 错</th><th>修正后 正确率</th>"
                   f"<th>二区 对</th><th>二区 错</th><th>对照10:30 对</th><th>对照13:30 对</th><th>虚拟净收益</th><th>笔数</th></tr></thead><tbody>{mrows}</tbody></table></div></div>" if mrows else "")

    def mark(v):
        return "<span class='up'>✅</span>" if v is True else ("<span class='down'>❌</span>" if v is False else "<span class='muted'>—</span>")
    rows = ""
    for r in recs:
        rows += (f"<tr><td>{r['day']}</td><td class='b'>{r.get('z2', '')}</td><td class='muted' style='text-align:left;white-space:normal'>{r.get('z2_reason', '')}</td>"
                 f"<td>{'是' if r.get('fixed') else ('否' if 'fixed' in r else '待')}</td><td class='b'>{r.get('final', r.get('z2', ''))}</td>"
                 f"<td style='text-align:left'>{r.get('prediction_final', r.get('prediction', ''))}</td>"
                 f"<td>{(str(round(r['open_official'], 2)) + ' / ' + str(round(r['close_official'], 2))) if r.get('settled') else '待收盘'}</td>"
                 f"<td class='{'up' if r.get('actual') == '涨' else 'down' if r.get('actual') == '跌' else ''}'>{r.get('actual', '')}</td>"
                 f"<td>{mark(r.get('correct_z2'))}</td><td>{mark(r.get('correct_final'))}</td><td>{mark(r.get('correct_b1030'))}</td><td>{mark(r.get('correct_b1330'))}</td>"
                 f"<td class='muted' style='font-size:11px'>{r.get('judged_at', '')[11:]}/{r.get('fixed_at', '')[11:]}/{r.get('settled_at', '')[11:]}</td></tr>")
    detail = (f"<details><summary>逐日记录（{len(recs)} 天）</summary><div class='tbl'><table><thead><tr><th>日期</th><th>二区</th><th style='text-align:left'>依据</th><th>五区修正</th><th>最终</th><th style='text-align:left'>预测</th><th>官方 开/收</th><th>实际</th><th>二区</th><th>修正后</th><th>对照10:30</th><th>对照13:30</th><th>虚拟盈亏</th><th>判定/修正/结算</th></tr></thead><tbody>{rows or '<tr><td colspan=14 class=muted>尚无记录</td></tr>'}</tbody></table></div></details>")

    # ---- 今日判定（页面最上方的实盘状态牌）----
    tstr = today.strftime("%Y-%m-%d")
    tr = by_day.get(tstr)
    if tr:
        z2c = "up" if tr.get("z2") == "好" else "down"
        parts = [f"<div class='today-k'>10:30 判定</div><div class='today-v {z2c}'>{tr.get('z2','')}二区</div><div class='today-s'>{tr.get('prediction','')}</div>"]
        if "fixed" in tr:
            fc = "up" if tr["final"] == "好" else "down"
            parts.append(f"<div class='today-k'>13:35 五区</div><div class='today-v {fc}'>{'修正为 ' + tr['final'] if tr['fixed'] else '维持 ' + tr['final']}</div><div class='today-s'>{tr['prediction_final']}</div>")
        else:
            parts.append("<div class='today-k'>13:35 五区</div><div class='today-v muted'>等待</div><div class='today-s'>13:35 后检查是否创新高/新低</div>")
        if tr.get("settled"):
            ok = tr["correct_final"]
            parts.append(f"<div class='today-k'>收盘结算</div><div class='today-v {'up' if ok else 'down'}'>{'判对' if ok else '判错'}</div><div class='today-s'>开 {tr['open_official']:.2f} → 收 {tr['close_official']:.2f}（{tr['actual']}）</div>")
        else:
            parts.append("<div class='today-k'>收盘结算</div><div class='today-v muted'>等待</div><div class='today-s'>15:00 后用官方开收盘判对错</div>")
        today_html = f"<div class='today'><div class='today-h'>今日实盘 · {tstr}{'（晚判，用 10:30 前 K 线）' if tr.get('judged_at','')[11:13] not in ('10','11') and not tr.get('backfilled') else ''}</div><div class='today-grid'>{''.join(f'<div class=today-cell>{x}</div>' for x in parts)}</div></div>"
    else:
        wd = today.weekday()
        msg = "今天是周末，下一个交易日 10:30 后出现判定" if wd >= 5 else ("今日判定将在 10:30 后出现" if today.strftime("%H:%M") < "10:35" else "今日暂无记录（休市或数据未更新）")
        today_html = f"<div class='today'><div class='today-h'>今日实盘 · {tstr}</div><div class='muted' style='padding:6px 0'>{msg}</div></div>"

    return f"""<div class='hd'><div><h1>二区定律 · 前瞻实盘记录</h1><div class='sub'>上证指数 ｜ 每个交易日 10:30 当场判定并推送、13:35 五区修正、收盘结算 ｜ 判定只用截止时刻之前的 K 线，事后不改</div></div></div>
{today_html}
{score_html}
{chart_html}
{cmp_html}
{pnl_html}
{month_table}
<details><summary>规则说明</summary><div class='card' style='border-radius:0 0 8px 8px'>好二区 = 10:15–10:30 的高点和低点都高于 10:00–10:15（低点抬高、高点抬高）；坏二区相反；形态模糊时按 10:30 收 vs 10:00 开。好二区 → 预测"收盘不会跌破开盘"，坏二区 → "不会涨过开盘"（收平算对）。五区（13:00–13:35，比课程口径多看 5 分钟）创 9:30 以来新低则好改坏，创新高则坏改好。对照组不看任何形态，只看当时价格在开盘价哪一侧。全部判定自动执行，数据来源新浪财经。</div></details>
{detail}"""


def cta_body():
    import json as _json
    exp = Path(__file__).resolve().parent.parent / "experiments"
    files = [("pattern", "形态信号（高富帅/白富美 + 20日线）", exp / "trend_result.json"), ("best", "优选信号", exp / "trend_result.json"),
             ("donchian", "20日突破（基准）", exp / "trend_result.json"), ("d55", "55日突破 / 20日线离场", exp / "trend_d_55_20.json"),
             ("d100", "100日突破 / 50日线离场", exp / "trend_d_100_50.json"),
             ("macd", "MACD 八策略（任一首发信号）", exp / "trend_macd.json"), ("macd_pat", "MACD 信号 + 3 日内形态确认", exp / "trend_macd.json")]
    res = []
    for key, label, f in files:
        if not f.exists():
            continue
        j = _json.loads(f.read_text(encoding="utf-8"))
        r = j.get(key) or (j.get("donchian") if key.startswith("d") else None)
        if r:
            res.append((label, r))
    if not res:
        return "<div class='card'>趋势回测结果尚未生成。</div>"

    def kpi(v, k, cls=""):
        return f"<div class='kpi'><div class='v {cls}'>{v}</div><div class='k'>{k}</div></div>"
    head = ("<div class='hd'><div><h1>趋势跟踪 · 组合回测</h1><div class='sub'>54 个品种主力连续日线 2018-01 ~ 今 ｜ 多空对称 ｜ 2×ATR 跟踪止损 + 均线离场 ｜ 波动率配仓、单品种 15%、板块 45%、总名义 150% ｜ 每边成本 0.02%</div></div></div>")
    rows = "".join(f"<tr><td style='text-align:left'>{lb}</td><td class='{'up' if r['cagr_pct'] > 0 else 'down'}'>{r['cagr_pct']:+.2f}%</td><td>{r['ann_vol_pct']:.1f}%</td><td class='b'>{r['sharpe']}</td>"
                   f"<td class='down'>{r['max_dd_pct']:.1f}%</td><td>{r['max_dd_span'][0][:7]}~{r['max_dd_span'][1][:7]}</td><td>{r['longest_underwater_days']}</td><td>{r['trades']}</td><td>{r['win_rate']}%</td><td>{r['payoff']}</td><td>{r['avg_hold_days']}</td><td>{r['longest_losing_streak']}</td></tr>" for lb, r in res)
    table = ("<div class='card'><h3>五种配置对比（全样本）</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th style='text-align:left'>配置</th><th>年化</th><th>年化波动</th><th>夏普</th><th>最大回撤</th><th>回撤区间</th><th>水下最长(天)</th><th>笔数</th><th>胜率</th><th>盈亏比</th><th>均持(天)</th><th>最长连亏</th></tr></thead>"
             f"<tbody>{rows}</tbody></table></div></div>")
    years = sorted({y for _, r in res for y in r["by_year"]})
    yrows = "".join(f"<tr><td style='text-align:left'>{lb}</td>" + "".join(f"<td class='{'up' if r['by_year'].get(y, 0) > 0 else 'down'}'>{r['by_year'].get(y, 0):+.1f}%</td>" for y in years) + "</tr>" for lb, r in res)
    ytable = (f"<div class='card'><h3>分年收益</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th style='text-align:left'>配置</th>{''.join(f'<th>{y}</th>' for y in years)}</tr></thead><tbody>{yrows}</tbody></table></div></div>")
    # 净值曲线
    W, H, L, R, T, B = 900, 300, 50, 12, 14, 28
    colors = ["var(--cyan)", "var(--amber)", "var(--dim)", "var(--up)", "var(--down)", "#8b5cf6", "#0ea5e9"]
    allv = [v for _, r in res for _, v, *_ in r["curve"]]
    lo, hi = min(allv) * 0.98, max(allv) * 1.02
    base = res[0][1]["curve"]
    n = len(base)
    px = lambda i: L + i * (W - L - R) / (n - 1)
    py = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    lines, legend = "", ""
    for (lb, r), col in zip(res, colors):
        c = r["curve"]
        m = len(c)
        pts = " ".join(f"{L + i * (W - L - R) / (m - 1):.1f},{py(v):.1f}" for i, (_, v, *_) in enumerate(c))
        lines += f"<polyline points='{pts}' fill='none' stroke='{col}' stroke-width='1.6'/>"
        legend += f"<span style='display:inline-flex;align-items:center;gap:5px;margin-right:14px;font-size:12px'><i style='width:14px;height:3px;background:{col};display:inline-block'></i>{lb}</span>"
    grid = "".join(f"<line x1='{L}' x2='{W - R}' y1='{py(g):.1f}' y2='{py(g):.1f}' stroke='var(--line)' stroke-dasharray='2 3'/><text x='{L - 6}' y='{py(g) + 3:.1f}' font-size='10' text-anchor='end' fill='var(--muted)'>{g:.2f}</text>" for g in [round(lo + (hi - lo) * k / 5, 2) for k in range(6)])
    xl = "".join(f"<text x='{px(i):.1f}' y='{H - 8}' font-size='10' text-anchor='middle' fill='var(--muted)'>{d[:4]}</text>" for i, (d, *_) in enumerate(base) if i == 0 or d[:4] != base[i - 1][0][:4])
    curve = f"<div class='card'><h3>净值曲线（起点 1.00）</h3><div style='margin-bottom:6px'>{legend}</div><svg viewBox='0 0 {W} {H}' width='100%' style='display:block'>{grid}<line x1='{L}' x2='{W - R}' y1='{py(1):.1f}' y2='{py(1):.1f}' stroke='var(--muted)'/>{lines}{xl}</svg></div>"
    # 板块 / 品种（基准配置）
    bench = next((r for lb, r in res if "20日突破" in lb), res[0][1])
    sec = sorted(bench["by_sector"].items(), key=lambda kv: -kv[1]["pnl"])
    srows = "".join(f"<tr><td style='text-align:left'>{k}</td><td>{v['n']}</td><td>{round(v['wins'] / v['n'] * 100, 1) if v['n'] else 0}%</td><td class='{'up' if v['pnl'] > 0 else 'down'}'>{v['pnl']:+.1f}%</td></tr>" for k, v in sec)
    syms = sorted(bench["by_symbol"].items(), key=lambda kv: -kv[1]["pnl"])
    top = "".join(f"<tr><td style='text-align:left'>{v['name']} {k[:-1]}</td><td>{v['n']}</td><td class='{'up' if v['pnl'] > 0 else 'down'}'>{v['pnl']:+.1f}%</td></tr>" for k, v in syms[:8])
    bot = "".join(f"<tr><td style='text-align:left'>{v['name']} {k[:-1]}</td><td>{v['n']}</td><td class='{'up' if v['pnl'] > 0 else 'down'}'>{v['pnl']:+.1f}%</td></tr>" for k, v in syms[-8:])
    brk = (f"<div class='grid2'><div class='card'><h3>按板块（20日突破基准，累计贡献）</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th style='text-align:left'>板块</th><th>笔数</th><th>胜率</th><th>累计贡献</th></tr></thead><tbody>{srows}</tbody></table></div></div>"
           f"<div class='card'><h3>贡献最大 / 最小的品种</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th style='text-align:left'>品种</th><th>笔数</th><th>累计贡献</th></tr></thead><tbody>{top}<tr><td colspan=3 class='muted'>···</td></tr>{bot}</tbody></table></div></div></div>")
    verdict = ("<div class='card' style='border-left:4px solid var(--amber)'><h3>结论（研究记录，不构成投资建议）</h3>"
               "<p>1. 五种配置 2018 年以来年化都在 -1% ~ +3% 之间，夏普 0.0~0.3，<b>达不到「夏普 0.8、回撤 20% 以内」的门槛</b>。</p>"
               "<p>2. 所有配置都在 <b>2022 年 7 月见顶后进入长达约三年的回撤</b>，水下最长 1029 天——这与国内商品 CTA 行业 2022 下半年至 2024 年的普遍低迷一致，是趋势类策略的共同经历，不是某个信号的问题。</p>"
               "<p>3. 形态信号（高富帅/白富美）作为趋势进场<b>并不优于</b>最朴素的 20 日突破；优选过滤降低了波动和回撤，但收益同样薄。</p>"
               "<p>4. 典型形态：胜率 30~37%，盈亏比约 2，最长连亏 18~29 笔，平均持仓 7~20 天。即便在好年份（2020、2026），也要先熬过大量小亏。</p>"
               "<p>5. <b>MACD 八策略</b>：全部信号合起来做趋势进场，年化 -5.6%，是所有配置里最差的；叠加形态确认后笔数减四成、亏损减半（-2.1%），说明形态确实过滤掉了一部分坏信号，但没有把它变成正的。逐个看，只有「双绿柱底背离」略好于无条件做多，其余与随机无异。</p>"
               "<p>6. 数据局限：主力连续合约在换月时有价格跳空，未做复权，会产生虚假信号和止损，<b>对结果有一定负面偏差</b>；真实合约级数据下表现可能略好，但不足以改变量级。</p>"
               "<p class='muted' style='font-size:12px'>回测脚本 scanner/trend_backtest.py，数据 data/long/，结果 experiments/trend_result*.json，可复现。</p></div>")
    ev_f = exp / "macd8_event.json"
    ev_html = ""
    if ev_f.exists():
        ev = _json.loads(ev_f.read_text(encoding="utf-8"))
        def cell(v, base):
            m, w = v
            return f"<td class='{'up' if m > base else 'down'}'>{m:+.2f}% / {w:.0f}%</td>"
        erows = "".join(f"<tr><td style='text-align:left'>{sid}. {v['name']}</td><td>{v['dir']}</td><td>{v['n']}</td>{cell(v['fwd5'], 0.116 if v['dir'] == '多' else -0.116)}{cell(v['fwd10'], 0.234 if v['dir'] == '多' else -0.234)}{cell(v['fwd20'], 0.478 if v['dir'] == '多' else -0.478)}</tr>" for sid, v in sorted(ev.items(), key=lambda kv: int(kv[0])))
        ev_html = ("<div class='card'><h3>MACD 八策略 · 单独看每一个（2018 年起，信号后 N 日方向收益 / 胜率）</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th style='text-align:left'>策略</th><th>方向</th><th>次数</th><th>5 日</th><th>10 日</th><th>20 日</th></tr></thead>"
                   f"<tbody>{erows}</tbody></table></div><div class='muted' style='font-size:11.5px;margin-top:8px'>对照：同期随便挑一天做多，5/10/20 日平均 +0.12% / +0.23% / +0.48%，胜率约 51%（商品整体上行漂移）；做空则取负。红色 = 好于对照，绿色 = 差于对照。只有 4 号「双绿柱底背离」略好于无条件做多；四个空头策略都没有跑赢「什么都不做」。</div></div>")
    night_html = night_section(exp)
    return head + table + curve + ytable + ev_html + night_html + brk + verdict


def night_section(exp):
    """2026-10-17 夜间补充：结构止损 / 超跌均值回归 / ENSO 过滤 / 季节性"""
    import json as _json
    f = exp / "night_results.json"
    if not f.exists():
        return ""
    R = _json.loads(f.read_text(encoding="utf-8"))

    def trow(label, r, first=None):
        c = f"<td style='text-align:left'>{first}</td>" if first is not None else ""
        return (f"<tr>{c}<td style='text-align:left'>{label}</td><td class='{'up' if r['cagr_pct'] > 0 else 'down'}'>{r['cagr_pct']:+.2f}%</td><td>{r['ann_vol_pct']:.1f}%</td><td class='b'>{r['sharpe']}</td>"
                f"<td class='down'>{r['max_dd_pct']:.1f}%</td><td>{r['longest_underwater_days']}</td><td>{r['trades']}</td><td>{r['win_rate']}%</td><td>{r['payoff']}</td><td>{r['avg_hold_days']}</td></tr>")
    th = "<th>年化</th><th>波动</th><th>夏普</th><th>最大回撤</th><th>水下最长(天)</th><th>笔数</th><th>胜率</th><th>盈亏比</th><th>均持(天)</th>"
    # 1 结构止损
    rows = "".join(trow(r["stop"], r, r["signal"]) for r in R["stops"])
    stops = (f"<div class='card'><h3>止损方式对比：ATR 吊灯 vs 结构止损（跟踪 N 日低点 / 两段式）</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th style='text-align:left'>信号</th><th style='text-align:left'>止损方式</th>{th}</tr></thead><tbody>{rows}</tbody></table></div>"
             "<div class='muted' style='font-size:11.5px;margin-top:8px'>均不用均线离场，只比止损。「跟踪 1 日低点」= 止损上移到昨天最低价：笔数翻倍、年化 -5%，是所有方式里最差的；N=10 与 2×ATR 吊灯基本等价。两段式（第一段固定在进场前 5 日低点，收盘创 20 日新高后切换为跟踪 N 日低点）与 ATR 相当，没有额外优势。结论：止损留的空间要和品种波动匹配，太紧会把趋势单震出去；用哪种结构差别不大。</div></div>")
    # 2 跌够久
    rows = "".join(trow(r["cfg"], r) for r in R["oversold"])
    oby = R["oversold_by_year"]
    yrows = "".join(f"<tr><td>{y}</td><td>{v['n']}</td><td class='{'up' if v['cond_avg'] > v['base_avg'] else 'down'}'>{v['cond_avg']:+.2f}% / {v['cond_win']:.0f}%</td><td>{v['base_avg']:+.2f}% / {v['base_win']:.0f}%</td><td class='b'>{v['cond_avg'] - v['base_avg']:+.2f}</td></tr>" for y, v in oby.items())
    os_ = R["season"]["oversold"]
    dm = R["season"]["down_months"]
    dmrows = "".join(f"<tr><td style='text-align:left'>{k}</td><td>{v['下月']['n']}</td><td class='{'up' if v['下月']['avg'] > 0.45 else ''}'>{v['下月']['avg']:+.2f}% / {v['下月']['win']}%</td><td class='{'up' if v.get('后3月') and v['后3月']['avg'] > 1.4 else ''}'>{(str(v['后3月']['avg']) + '% / ' + str(v['后3月']['win']) + '%') if v.get('后3月') else '—'}</td></tr>" for k, v in dm.items())
    over = (f"<div class='card' style='border-left:4px solid var(--up)'><h3>「跌够久」均值回归 —— 今晚唯一在每一年都成立的东西</h3>"
            f"<div class='grid2'><div><h4 style='margin:4px 0 6px'>事件统计：60 日跌幅处于该品种自身历史最低 10% 之后</h4><div class='tbl' style='border-radius:8px'><table><thead><tr><th>条件</th><th>后 20 日</th><th>后 60 日</th></tr></thead><tbody>"
            f"<tr><td style='text-align:left'>超跌后</td><td class='up'>{os_['60日跌幅处于历史最低10%']['后20日']['avg']:+.2f}% / 胜率 {os_['60日跌幅处于历史最低10%']['后20日']['win']}%</td><td class='up'>{os_['60日跌幅处于历史最低10%']['后60日']['avg']:+.2f}% / 胜率 {os_['60日跌幅处于历史最低10%']['后60日']['win']}%</td></tr>"
            f"<tr><td style='text-align:left'>无条件（任意一天）</td><td>{os_['无条件']['后20日']['avg']:+.2f}% / {os_['无条件']['后20日']['win']}%</td><td>{os_['无条件']['后60日']['avg']:+.2f}% / {os_['无条件']['后60日']['win']}%</td></tr></tbody></table></div>"
            f"<h4 style='margin:12px 0 6px'>连续下跌 N 个月之后</h4><div class='tbl' style='border-radius:8px'><table><thead><tr><th style='text-align:left'>条件</th><th>次数</th><th>下月 均值/胜率</th><th>后 3 月</th></tr></thead><tbody>{dmrows}</tbody></table></div></div>"
            f"<div><h4 style='margin:4px 0 6px'>分年检验（超跌后 60 日 vs 无条件 60 日）</h4><div class='tbl' style='border-radius:8px'><table><thead><tr><th>年</th><th>事件数</th><th>超跌后</th><th>无条件</th><th>差</th></tr></thead><tbody>{yrows}</tbody></table></div>"
            "<div class='muted' style='font-size:11.5px;margin-top:6px'>事件按天统计、高度重叠（一次超跌会连续多天满足条件），真实独立样本远少于表中数字；但 2019–2026 每一年超跌后都好于无条件，这是今晚所有检验里最一致的结果。</div></div></div>"
            f"<h4 style='margin:14px 0 6px'>做成策略：只做多，超跌当天触发一次，次日开盘进场，持有满 N 天离场</h4><div class='tbl' style='border-radius:8px'><table><thead><tr><th style='text-align:left'>配置</th>{th}</tr></thead><tbody>{rows}</tbody></table></div>"
            "<div class='muted' style='font-size:11.5px;margin-top:8px'>关键发现：止损越紧越差。3×ATR 止损把近半数单子在反弹前打掉（均持仅 22 天）；放宽到 6×ATR，夏普 0.68、回撤 -13.7%、胜率 54%、九年里只有 2022 年小亏——是今晚所有配置里最好的，也是唯一一个在震荡年份（2023–2024）仍为正的。这类策略的本质是接下跌中的品种，必须用小仓位（波动率配仓已把单品种权重压得很低）、靠时间而不是靠止损来控制风险。年化看起来只有 4% 是因为仓位很轻（年化波动 6%），按风险等比例放大到 12% 波动约对应年化 8%、回撤 -27%。</div></div>")
    # 3 ENSO
    rows = "".join(trow(r["cfg"], r) for r in R["enso"])
    enso = (f"<div class='card'><h3>厄尔尼诺 / 拉尼娜方向过滤（NOAA ONI，用上月值，±0.5℃ 阈值）</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th style='text-align:left'>配置</th>{th}</tr></thead><tbody>{rows}</tbody></table></div>"
            "<div class='muted' style='font-size:11.5px;margin-top:8px'>规则：厄尔尼诺期间 棕榈油/豆油/菜油/白糖/橡胶/棉花 只接多头信号；拉尼娜期间 豆粕/菜粕/豆油/焦煤/焦炭 只接多头信号；其余不变。结果：对 20 日突破有改善（相关品种年化 -1.9% → -0.1%，回撤 -21% → -15%；全组合 2.7% → 4.8%），对优选信号无改善。2018 年以来只经历了 5 段厄尔尼诺/拉尼娜，样本极少，只能说「方向上支持」，不能算证据。2026 年 6 月后 ONI 尚未发布，按 5 月值（+1.0，厄尔尼诺）顺延。</div></div>")
    # 4 季节性
    so = R["season"]["season_oos"]
    cal = R["season"]["seasonality"]["calendar_avg_all"]
    calrow = "".join(f"<td class='{'up' if v > 0 else 'down'}'>{v:+.1f}%</td>" for m, v in sorted(cal.items(), key=lambda kv: int(kv[0])))
    season = (f"<div class='card'><h3>季节性：样本外基本不成立</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th style='text-align:left'>检验（2018–2022 选月份，2023 起检验）</th><th>月数</th><th>月均收益</th><th>胜率</th></tr></thead><tbody>"
              + "".join(f"<tr><td style='text-align:left'>{k}</td><td>{v['n']}</td><td class='{'up' if v['avg'] > 0 else 'down'}'>{v['avg']:+.2f}%</td><td>{v['win']}%</td></tr>" for k, v in so.items())
              + f"</tbody></table></div><div class='tbl' style='border-radius:8px;margin-top:8px'><table><thead><tr><th>全品种自然月平均</th>{''.join(f'<th>{m}月</th>' for m in range(1, 13))}</tr></thead><tbody><tr><td></td>{calrow}</tr></tbody></table></div>"
              "<div class='muted' style='font-size:11.5px;margin-top:8px'>用前五年每个品种最好的两个月做多、最差的两个月做空，之后三年多：做多月平均 +0.51%（和无条件 +0.26% 差别不大），做空月反而亏。单个品种 9 年只有 9 个样本，季节性在这个数据量上分不清是规律还是巧合。全品种看，1 月、7 月、12 月偏强，10 月偏弱，与春节前备货、国庆后去库的常识一致，但幅度不足以单独交易。</div></div>")
    return "<div class='hd' style='margin-top:18px'><div><h2 style='margin:0;font-size:18px'>补充检验（2026-10-17 夜）：止损结构 · 跌够久 · 厄尔尼诺 · 季节性</h2></div></div>" + over + stops + enso + season


def method_body():
    rows = "".join(
        f"<tr><td>{PAT_ICON[p]} {p}</td><td>{PAT_DESC[p].split('｜')[0]}</td><td style='white-space:normal;text-align:left'>{PAT_DESC[p].split('｜')[1]}</td></tr>" for p in PATTERNS)
    return f"""<div class='hd'><div><h1>方法说明</h1><div class='sub'>本站全部内容由程序按固定规则自动生成，无人工干预</div></div></div>
<div class='rule'><h4>1. 扫描范围</h4>国内五大期货交易所（上期所、大商所、郑商所、中金所、广期所）共 54 个品种的<b>主力连续合约</b>日线数据，来源为新浪财经（经 akshare 获取），无需密钥。每个交易日收盘后、新浪日线更新后（通常 17:00–18:30）自动运行。</div>
<div class='rule'><h4>2. 三个判定维度（每日收盘后计算）</h4>
<b>价格方向</b>：<code>涨跌幅 = (今收 − 昨收) / 昨收</code>，&gt;0 上涨，&lt;0 下跌。<br>
<b>量能状态</b>：今日成交量 <b>同时</b> 大于 5 日均量和 20 日均量 → 放量；否则 → 缩量。<br>
<b>持仓方向</b>：<code>持仓变化 = (今持仓 − 昨持仓) / 昨持仓</code>，&gt;0 增仓，&lt;0 减仓。</div>
<div class='rule'><h4>3. 八种形态（三维组合）</h4><div class='tbl' style='border-radius:8px'><table><thead><tr><th>形态</th><th>价·量·仓</th><th>含义</th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='rule'><h4>4. 附加标注</h4>
<b>⭐双20%强信号</b>：持仓单日变化 ≥20% 且 成交量 ≥ 20日均量×1.2（极少触发）。<br>
<b>⭐⭐优选</b>：高富帅中 0%&lt;涨幅≤2% 且 2%≤增仓≤5%（400天回测5日胜率55.1%）。<br>
<b>⚠️追高</b>：高富帅中涨幅&gt;3%（次日胜率仅44%）。<br>
<b>🛡抗跌先锋</b>：弱势市中仍为高富帅的品种（胜率58%）。<br>
<b>市场环境</b>：全部品种 20 日动量的中位数 &lt;0 为弱势市，否则强势市。<br>
<b>板块共振</b>：同板块 ≥2 个品种同日出现高富帅或白富美。</div>
<div class='rule'><h4>5. MACD 八策略买卖点</h4>与形态报告并行的第二套信号：基于日线收盘价的 MACD（12,26,9）判定 4 个多头买点（红柱二次翻红、绿柱峰后收窄、零轴回踩拐头、双绿柱底背离）与 4 个镜像空头卖点，只报"首发"（昨日未触发、今日触发）。详细规则与历史胜率见「MACD买卖点」页。两套信号方向一致时在日报中标注"双重共振"。</div>
<div class='rule'><h4>6. 数据与免责</h4>成交量、持仓量以交易所正式日线为准；节假日自动跳过。原始数据按日公开（每份报告页右上角「原始数据 JSON」）。本站仅供学习交流，不构成任何投资建议。</div>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="site")
    args = ap.parse_args()
    data_dir, out = Path(args.data), Path(args.out)

    files = sorted(p for p in data_dir.glob("????-??-??.json"))
    datas = []
    for p in files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("all_results"):
                datas.append(d)
        except Exception as e:
            print(f"跳过 {p.name}: {e}")
    if not datas:
        raise SystemExit("没有可用数据")
    datas.sort(key=lambda d: d["data_date"])
    dates = [d["data_date"] for d in datas]

    if out.exists():
        shutil.rmtree(out)
    (out / "reports").mkdir(parents=True)
    (out / "data").mkdir()
    for p in files:
        shutil.copy(p, out / "data" / p.name)
    latest = datas[-1]
    (out / "data" / "latest.json").write_text(json.dumps(latest, ensure_ascii=False), encoding="utf-8")
    (out / "data" / "index.json").write_text(json.dumps(
        [{"date": d["data_date"], "up": d["up_count"], "down": d["down_count"],
          "gao": d["patterns"]["高富帅"]["count"], "bai": d["patterns"]["白富美"]["count"],
          "regime": (d.get("market") or {}).get("regime")} for d in datas], ensure_ascii=False), encoding="utf-8")

    st = stats_mod.compute(datas)
    for i, d in enumerate(datas):
        prev = datas[i - 1] if i > 0 else None
        body = build_report_body(d, prev, dates, root="../", streaks=st["streaks"] if i == len(datas) - 1 else None,
                                 macd=st["macd_by_date"].get(d["data_date"], []))
        (out / "reports" / f"{d['data_date']}.html").write_text(
            layout(f"{SITE_TITLE} {d['data_date']}", body, "home", root="../"), encoding="utf-8")
    body = build_report_body(latest, datas[-2] if len(datas) > 1 else None, dates, root="", streaks=st["streaks"],
                             macd=st["macd_by_date"].get(latest["data_date"], []))
    (out / "index.html").write_text(layout(f"{SITE_TITLE} · 最新 {latest['data_date']}", body, "home"), encoding="utf-8")
    (out / "archive.html").write_text(layout(f"历史归档 · {SITE_TITLE}", archive_body(datas, st["macd_by_date"]), "archive"), encoding="utf-8")
    (out / "trend.html").write_text(layout(f"信号趋势 · {SITE_TITLE}", trend_body(datas), "trend"), encoding="utf-8")
    (out / "macd.html").write_text(layout(f"MACD买卖点 · {SITE_TITLE}", macd_body(st, latest["data_date"]), "macd"), encoding="utf-8")
    (out / "stats.html").write_text(layout(f"历史战绩 · {SITE_TITLE}", stats_body(st), "stats"), encoding="utf-8")
    (out / "method.html").write_text(layout(f"方法说明 · {SITE_TITLE}", method_body(), "method"), encoding="utf-8")
    (out / "erqu.html").write_text(layout(f"二区实盘 · {SITE_TITLE}", erqu_body(), "erqu"), encoding="utf-8")
    (out / "cta.html").write_text(layout(f"趋势回测 · {SITE_TITLE}", cta_body(), "cta"), encoding="utf-8")
    # K 线形态图：逐品种 JSON + 页面 + 本地 echarts
    avail = chart_mod.build(out, SYMBOLS)
    (out / "assets").mkdir(exist_ok=True)
    shutil.copy(Path(__file__).resolve().parent / "assets" / "echarts.min.js", out / "assets" / "echarts.min.js")
    (out / "chart.html").write_text(layout(f"K线形态图 · {SITE_TITLE}", chart_page.body(avail, SECTOR), "chart",
                                           desc="按王刚期货交易体系手册规则自动标注蜡烛形态、包线、量仓信号与趋势状态的交互 K 线图"), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    print(f"网站已生成：{out}  共 {len(datas)} 天，最新 {latest['data_date']}")
    # 事件日历年度维护提醒：FOMC 日期按年硬编码，11 月起若下一年缺失则在日志中警告
    yr = int(latest["data_date"][:4])
    if int(latest["data_date"][5:7]) >= 11 and not any(k.startswith(str(yr + 1)) for k in getattr(events_cal, "FOMC_2026", {})):
        print(f"::warning::events_cal.py 缺少 {yr + 1} 年 FOMC 日期，请在年底前补充")


if __name__ == "__main__":
    main()
