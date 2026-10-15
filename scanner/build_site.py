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
:root{--bg:#f4f5f7;--card:#fff;--ink:#1f2328;--muted:#6b7280;--line:#e5e7eb;--up:#d1322f;--down:#15803d;
--gold:#b45309;--gold-bg:#fff7ed;--accent:#111827;--soft:#f9fafb;--blue:#1d4ed8}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.6}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
.top{background:var(--accent);color:#fff}
.top .in{max-width:1080px;margin:0 auto;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.brand{font-weight:700;font-size:17px;letter-spacing:1px;color:#fff}
.brand small{display:block;font-weight:400;font-size:11px;color:#9ca3af;letter-spacing:0}
.nav a{color:#d1d5db;margin-left:14px;font-size:13px}.nav a.on{color:#fff;font-weight:600}
.wrap{max-width:1080px;margin:0 auto;padding:16px}
.hd{display:flex;align-items:flex-end;justify-content:space-between;gap:10px;flex-wrap:wrap;margin:6px 0 14px}
.hd h1{font-size:22px;letter-spacing:1px}
.hd .sub{color:var(--muted);font-size:12px;margin-top:2px}
.badge{padding:6px 14px;border-radius:6px;font-weight:700;font-size:13px;white-space:nowrap}
.badge.strong{background:#fef2f2;color:var(--up);border:1px solid #fecaca}
.badge.weak{background:#f0fdf4;color:var(--down);border:1px solid #bbf7d0}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.kpi .v{font-size:22px;font-weight:700;line-height:1.2}.kpi .k{color:var(--muted);font-size:11px;margin-top:2px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:12px}
.card h3{font-size:14px;margin-bottom:8px;padding-left:8px;border-left:4px solid var(--accent)}
.card h3.blue{border-left-color:var(--blue)}
.bar-row{display:flex;align-items:center;margin:4px 0;font-size:12px}
.bar-label{width:84px;flex:none}.bar-label.sm{width:64px}
.bar-track{flex:1;background:#eef0f3;border-radius:3px;height:14px;margin:0 8px;overflow:hidden}
.bar-fill{display:block;height:100%;background:#9aa4ae;border-radius:3px}
.bar-fill.red{background:var(--up)}.bar-fill.green{background:var(--down)}
.bar-val{width:52px;text-align:right;flex:none}
.view{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:10px 14px;margin-bottom:12px}
.view b{color:var(--gold)}
.sec{margin-bottom:12px}
.sec-h{display:flex;align-items:baseline;gap:8px;padding:7px 12px;background:var(--soft);border:1px solid var(--line);border-bottom:0;border-radius:8px 8px 0 0;border-left:4px solid var(--accent)}
.sec-h.p-gao{border-left-color:var(--up)}.sec-h.p-bai{border-left-color:var(--down)}.sec-h.p-warn{border-left-color:var(--gold)}.sec-h.p-good{border-left-color:#0891b2}
.sec-t{font-weight:700;font-size:14px}.sec-n{color:var(--muted);font-size:12px}.sec-d{color:#9ca3af;font-size:11px;margin-left:auto}
.tbl{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:0 0 8px 8px}
table{width:100%;border-collapse:collapse;min-width:560px}
th,td{padding:6px 8px;text-align:center;border-bottom:1px solid #f1f3f5;font-size:12.5px;white-space:nowrap}
th{background:#fafbfc;color:var(--muted);font-weight:500;font-size:11px}
tr:last-child td{border-bottom:0}
td.b{font-weight:700}.up{color:var(--up)}.down{color:var(--down)}.muted{color:var(--muted)}
.tag{font-size:10.5px;padding:1px 7px;border-radius:4px;white-space:nowrap;margin-right:3px}
.tag-best{background:#fef2f2;color:var(--up);border:1px solid #fecaca}
.tag-warn{background:#fffbeb;color:var(--gold);border:1px solid #fde68a}
.tag-watch{background:#f3f4f6;color:var(--muted);border:1px solid #e5e7eb}
.best-card{display:inline-block;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;padding:5px 11px;margin:3px 6px 3px 0;font-size:13px}
.ev{margin:4px 0;font-size:13px}.star{color:var(--gold);font-size:11px;margin-right:4px}
.hint{background:#fef2f2;border-left:3px solid var(--up);padding:5px 10px;margin:5px 0;font-size:12.5px;border-radius:0 4px 4px 0}
ul{margin-left:20px}li{margin:3px 0}
details{margin-bottom:10px}summary{cursor:pointer;font-weight:600;padding:8px 12px;background:var(--card);border:1px solid var(--line);border-radius:8px;list-style:none;display:flex;align-items:center;gap:8px}
summary::-webkit-details-marker{display:none}summary::after{content:"展开 ▾";margin-left:auto;font-weight:400;color:var(--muted);font-size:12px}
details[open] summary{border-radius:8px 8px 0 0}details[open] summary::after{content:"收起 ▴"}
details .tbl{border-radius:0 0 8px 8px}
.ft{margin-top:18px;padding-top:10px;border-top:1px solid var(--line);color:var(--muted);font-size:11.5px;line-height:1.9}
.arch{list-style:none;margin:0}.arch li{display:flex;justify-content:space-between;gap:10px;padding:9px 4px;border-bottom:1px solid #f1f3f5;flex-wrap:wrap}
.arch li:last-child{border-bottom:0}.arch .d{font-weight:600;min-width:110px}.arch .m{color:var(--muted);font-size:12px}
.pill{display:inline-block;font-size:11px;padding:1px 8px;border-radius:999px;background:#f3f4f6;color:#374151;margin-left:4px}
.pill.up{background:#fef2f2;color:var(--up)}.pill.down{background:#f0fdf4;color:var(--down)}
.spark{vertical-align:middle}
.status{font-size:12px;color:var(--muted);margin-bottom:10px}
.status .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#16a34a;margin-right:5px}
.status .dot.stale{background:#f59e0b}
.rule{background:var(--soft);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:10px}
.rule h4{font-size:14px;margin-bottom:4px}
code{background:#f3f4f6;padding:1px 5px;border-radius:4px;font-size:12px}
@media (max-width:720px){.kpis{grid-template-columns:repeat(3,1fr)}.grid2{grid-template-columns:1fr}.hd h1{font-size:19px}.nav a{margin-left:10px;font-size:12px}.wrap{padding:12px}table{min-width:520px}summary .sec-d{display:none}}
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
    color = "#d1322f" if closes[-1] >= closes[0] else "#15803d"
    return (f"<svg class='spark' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
            f"<polyline fill='none' stroke='{color}' stroke-width='1.5' points='{pts}'/></svg>")


def layout(title, body, nav_on, root="", desc=""):
    gen = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M")
    nav = [("index.html", "最新日报", "home"), ("archive.html", "历史归档", "archive"),
           ("trend.html", "信号趋势", "trend"), ("macd.html", "MACD买卖点", "macd"), ("stats.html", "历史战绩", "stats"), ("method.html", "方法说明", "method")]
    nav_html = "".join(f"<a href='{root}{h}' class='{'on' if k == nav_on else ''}'>{t}</a>" for h, t, k in nav)
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<meta name="description" content="{desc or '国内期货54品种 量·仓·价三维八种形态每日自动扫描公示'}">
<style>{CSS}</style></head><body>
<div class="top"><div class="in"><a class="brand" href="{root}index.html">{SITE_TITLE}<small>国内期货 54 品种 · 量仓价三维自动扫描 · 每交易日收盘后更新</small></a>
<nav class="nav">{nav_html}</nav></div></div>
<div class="wrap">{body}
<div class="ft">信号判定：量·仓·价三维分类 ｜ 三档标注依据：400天历史回测（13014个信号）｜ 白富美经全年数据验证对后市方向无显著预测力，降级观察 ｜ 数据来源：新浪财经（akshare）｜ 理论参考：北大期货班八种形态<br>
本站内容为程序自动生成，仅供学习交流，不构成任何投资建议。页面生成时间：{gen}（北京时间）</div>
</div></body></html>"""


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
<div class='badge {regime_cls}'>市场环境 · {REGIME_TXT}（20日中位动量 {REGIME_MOM}%）</div></div>
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

    g, b = line(gv, "#d1322f"), line(bv, "#15803d")
    labels = "".join(f"<text x='{xs[i]:.0f}' y='{H - 10}' font-size='10' text-anchor='middle' fill='#6b7280'>{ds[i]['data_date'][5:]}</text>"
                     for i in range(0, n, max(1, n // 8)))
    yl = "".join(f"<text x='{PAD - 6}' y='{H - PAD - k / 4 * (H - 2 * PAD) + 4:.0f}' font-size='10' text-anchor='end' fill='#6b7280'>{mx * k / 4:.0f}</text>"
                 f"<line x1='{PAD}' x2='{W - PAD}' y1='{H - PAD - k / 4 * (H - 2 * PAD):.0f}' y2='{H - PAD - k / 4 * (H - 2 * PAD):.0f}' stroke='#eee'/>" for k in range(5))
    svg1 = f"<svg viewBox='0 0 {W} {H}' width='100%' style='max-width:{W}px'>{yl}{g}{b}{labels}</svg>"

    # 上涨家数占比 + 市场环境
    def ratio(d):
        t = d["up_count"] + d["down_count"]
        return d["up_count"] / t * 100 if t else 50
    pts = " ".join(f"{x:.1f},{H - PAD - ratio(d) / 100 * (H - 2 * PAD):.1f}" for x, d in zip(xs, ds))
    mid = H - PAD - 0.5 * (H - 2 * PAD)
    yl2 = "".join(f"<text x='{PAD - 6}' y='{H - PAD - k / 4 * (H - 2 * PAD) + 4:.0f}' font-size='10' text-anchor='end' fill='#6b7280'>{k * 25}%</text>" for k in range(5))
    regime_marks = "".join(f"<rect x='{x - 3:.0f}' y='{H - PAD + 2}' width='6' height='5' fill='{'#15803d' if (d.get('market') or {}).get('regime') == '弱势' else '#d1322f'}'/>" for x, d in zip(xs, ds))
    svg2 = (f"<svg viewBox='0 0 {W} {H}' width='100%' style='max-width:{W}px'>{yl2}<line x1='{PAD}' x2='{W - PAD}' y1='{mid}' y2='{mid}' stroke='#d1d5db' stroke-dasharray='4 4'/>"
            f"<polyline fill='none' stroke='#1d4ed8' stroke-width='2' points='{pts}'/>{regime_marks}{labels}</svg>")

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
    (out / ".nojekyll").write_text("")
    print(f"网站已生成：{out}  共 {len(datas)} 天，最新 {latest['data_date']}")
    # 事件日历年度维护提醒：FOMC 日期按年硬编码，11 月起若下一年缺失则在日志中警告
    yr = int(latest["data_date"][:4])
    if int(latest["data_date"][5:7]) >= 11 and not any(k.startswith(str(yr + 1)) for k in getattr(events_cal, "FOMC_2026", {})):
        print(f"::warning::events_cal.py 缺少 {yr + 1} 年 FOMC 日期，请在年底前补充")


if __name__ == "__main__":
    main()
