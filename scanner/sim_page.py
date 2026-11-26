#!/usr/bin/env python3
"""「方向清单模拟盘」页面（sim.html），供 build_site.py 调用。
内容：data/sim/list.json（每期方向清单，由 Claude 每个交易日早上更新）
账本：scanner/sim_ledger.py 按 data/history/ 主力连续日线自动核对，每次建站都会重算。"""
import html
import json
from pathlib import Path

import pandas as pd

import sim_ledger as L

ROOT = Path(__file__).resolve().parent.parent
DIR = {"l": "只做多", "s": "只做空", "f": "不做"}
CONF = {"h": "把握较高", "m": "把握一般", "l": "把握低", "x": "暂停"}

CSS = """<style>
.sim{max-width:760px;margin:0 auto}
.sim .hd{margin-bottom:6px}
.sim .bg{font-size:13px;color:var(--muted);margin:0 0 14px;line-height:1.7}
.sim .bg b{color:var(--ink);font-weight:600}
.sim .bg a{font-size:12px}
.sim .books{display:grid;grid-template-columns:repeat(3,1fr);background:var(--panel);border:1px solid var(--line);border-radius:6px;margin-bottom:6px}
.sim .books div{padding:10px 12px;min-width:0}
.sim .books div+div{border-left:1px solid var(--line)}
.sim .books b{display:block;font-family:var(--mono);font-size:20px;line-height:1.2}
.sim .books span{font-size:11.5px;color:var(--muted);line-height:1.4;display:block}
.sim .bookline{font-size:12px;color:var(--muted);margin:0 0 18px}
.sim .tw{overflow-x:auto;margin-bottom:18px}
.sim .tw table{background:var(--panel)}
.sim .label{font-size:12px;color:var(--muted);letter-spacing:1px;margin:0 0 8px}
.sim .oc{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin-bottom:14px}
.sim .oh{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.sim .oh .nm{font-size:18px;font-weight:700}
.sim .oh .cd{font-family:var(--mono);color:var(--muted);font-size:12px}
.sim .oh .rk{margin-left:auto;font-size:12px;color:var(--muted)}
.sim .one{font-size:13.5px;margin:4px 0 10px}
.sim .px{display:grid;grid-template-columns:repeat(3,1fr);margin-bottom:6px}
.sim .px div{display:flex;flex-direction:column;min-width:0;padding-right:8px}
.sim .px div+div{border-left:1px solid var(--line);padding-left:12px}
.sim .px small{font-size:11.5px;color:var(--muted)}
.sim .px b{font-family:var(--mono);font-size:22px;line-height:1.25;white-space:nowrap}
.sim .px span{font-size:11.5px;color:var(--muted);line-height:1.35}
.sim .stop{color:var(--amber)}.sim .tp{color:var(--cyan)}
.sim .kc{margin:6px -4px 0}
.sim .kc svg{display:block;width:100%;height:auto}
.sim .kc text{fill:var(--muted);font-family:var(--mono);font-size:11px}
.sim .how{font-size:12.5px;color:var(--muted);margin-top:6px}
.sim .note{font-size:12.5px;color:var(--amber);margin-top:4px}
.sim details{margin-bottom:0}
.sim details summary{cursor:pointer;color:var(--cyan);font-size:13px;margin-top:8px;list-style:none;padding:0;background:none;border:none;border-radius:0;display:block;font-weight:400}
.sim details summary::-webkit-details-marker{display:none}
.sim details summary::after,.sim details[open] summary::after{content:" ›";margin-left:0;font-family:inherit;font-size:inherit}
.sim details[open] summary::after{content:" ⌄"}
.sim .why{display:flex;flex-direction:column;gap:8px;margin-top:8px;font-size:13px;padding-top:8px;border-top:1px dashed var(--line)}
.sim .why h4{font-size:11.5px;color:var(--muted);font-weight:600;margin-bottom:2px}
.sim .src{font-size:11.5px;color:var(--muted)}
.sim .chips{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin-bottom:18px}
.sim .chip{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:8px 10px}
.sim .chip summary{margin:0;color:var(--ink);display:flex;align-items:center;gap:6px;font-size:14px;font-weight:600}
.sim .chip summary::after,.sim .chip[open] summary::after{content:""}
.sim .chip .pill{margin-left:auto;font-size:11px;font-weight:400}
.sim .chip p{font-size:12.5px;color:var(--muted);margin-top:6px;font-weight:400}
.sim .pill.flat{color:var(--muted)}
.sim .foot{font-size:12.5px;color:var(--muted);margin-top:4px}
.sim .bookline{margin-bottom:18px}
</style>"""


def esc(x):
    return html.escape(str(x))


def links(src, keys):
    return " · ".join(f"<a href='{esc(src[k][1])}' target='_blank' rel='noopener'>{esc(src[k][0])}</a>" for k in keys if k in src)


def pill(d, txt=None):
    cls = {"l": "up", "s": "down"}.get(d, "flat")
    return f"<span class='pill {cls}'>{esc(txt or DIR[d])}</span>"


def kchart(code, plan, marks, side="l"):
    """日线 K 线（红涨绿跌）＋计划价位，价位线直接写成白话，赚钱区/亏钱区上色，纯 SVG"""
    d = L.hist(code).tail(40)
    W, H, Lm, R, T, B = 360, 280, 34, 96, 22, 20
    n = len(d); cw = (W - Lm - R) / n
    long = side == "l"
    lines = []
    if plan:
        for o in plan["开仓"]:
            lines.append((f"{'开多' if long else '开空'}（{o['方式']}）", o["价"], "var(--ink)"))
        lines.append(("止损（认赔）", plan["止损"], "var(--amber)"))
        lines.append(("止盈（目标）", plan["止盈"], "var(--cyan)"))
    vals = list(d.high) + list(d.low) + [v for _, v, _ in lines] + [m[1] for m in marks]
    lo, hi = min(vals), max(vals); pad = (hi - lo) * .06; lo -= pad; hi += pad
    y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    x = lambda i: Lm + cw * i + cw / 2
    g = [f"<text x='0' y='12' style='fill:var(--ink);font-size:12px;font-weight:600'>日线 · 最近 40 个交易日</text>"]
    # 价格刻度
    step = (hi - lo) / 4
    for k in range(5):
        v = lo + step * k; yy = y(v)
        g.append(f"<line x1='{Lm}' x2='{W - R}' y1='{yy:.1f}' y2='{yy:.1f}' style='stroke:var(--line)'/>")
        g.append(f"<text x='{Lm - 4}' y='{yy + 4:.1f}' text-anchor='end'>{v:.0f}</text>")
    # 赚钱区 / 亏钱区
    if plan:
        e = plan["开仓"][0]["价"]
        for a_, b_, col, txt in ((e, plan["止盈"], "var(--up)" if long else "var(--down)", "赚钱区"), (e, plan["止损"], "var(--amber)", "亏钱区")):
            y1, y2 = sorted((y(a_), y(b_)))
            g.append(f"<rect x='{Lm}' y='{y1:.1f}' width='{W - R - Lm}' height='{y2 - y1:.1f}' style='fill:{col};opacity:.09'/>")
            if y2 - y1 > 14:
                g.append(f"<text x='{Lm + 4}' y='{(y1 + y2) / 2 + 4:.1f}' style='fill:{col};opacity:.8'>{txt}</text>")
    for i, b in enumerate(d.itertuples()):
        up = b.close >= b.open; col = "var(--up)" if up else "var(--down)"
        g.append(f"<line x1='{x(i):.1f}' x2='{x(i):.1f}' y1='{y(b.high):.1f}' y2='{y(b.low):.1f}' style='stroke:{col}'/>")
        t = y(max(b.open, b.close)); h = max(1, abs(y(b.open) - y(b.close)))
        g.append(f"<rect x='{x(i) - cw * .36:.1f}' y='{t:.1f}' width='{cw * .72:.1f}' height='{h:.1f}' style='fill:{'var(--panel)' if up else col};stroke:{col}'/>")
    ls = sorted(([nm, v, c, y(v), y(v)] for nm, v, c in lines), key=lambda a: a[3])
    for i in range(1, len(ls)):
        if ls[i][4] - ls[i - 1][4] < 14:
            ls[i][4] = ls[i - 1][4] + 14
    for nm, v, c, yy, ty in ls:
        g.append(f"<line x1='{Lm}' x2='{W - R}' y1='{yy:.1f}' y2='{yy:.1f}' style='stroke:{c};stroke-width:1.5' stroke-dasharray='5 3'/>")
        g.append(f"<text x='{W - R + 4}' y='{ty + 4:.1f}' style='fill:{c};font-size:11px'>{esc(nm)} {v:g}</text>")
    last = float(d.close.iloc[-1])
    g.append(f"<text x='{x(n - 1):.1f}' y='{y(last) - 8:.1f}' text-anchor='end' style='fill:var(--ink);font-size:11px'>现价 {last:g}</text>")
    di = {dt.strftime('%Y-%m-%d'): i for i, dt in enumerate(d.index)}
    for day, v, kind, tip in marks:
        if day not in di:
            continue
        xx, yy = x(di[day]), y(v)
        if kind == "in":
            g.append(f"<path d='M{xx - 6:.1f} {yy + 10:.1f}L{xx:.1f} {yy:.1f}L{xx + 6:.1f} {yy + 10:.1f}Z' style='fill:var(--cyan)'><title>{esc(tip)}</title></path>")
        else:
            g.append(f"<path d='M{xx - 5:.1f} {yy - 5:.1f}L{xx + 5:.1f} {yy + 5:.1f}M{xx + 5:.1f} {yy - 5:.1f}L{xx - 5:.1f} {yy + 5:.1f}' style='stroke:var(--ink);stroke-width:2'><title>{esc(tip)}</title></path>")
    for i, anc in ((0, "start"), (n // 2, "middle"), (n - 1, "end")):
        g.append(f"<text x='{x(i):.1f}' y='{H - 4}' text-anchor='{anc}'>{d.index[i].strftime('%m-%d')}</text>")
    return (f"<div class='kc'><svg viewBox='0 0 {W} {H}' role='img' aria-label='日线 K 线和开仓止损止盈价位'>{''.join(g)}</svg></div>"
            "<div class='src'>一根 K 线 = 一天，红涨绿跌。成交后图上会标 ▲ 开仓、✕ 平仓。</div>")


def fmt(v):
    return "" if v is None else f"{v:g}"


def money(v):
    return "" if v is None else f"<span class='{'up' if v > 0 else 'down' if v < 0 else ''}'>{v:+,}</span>"


def ledger_html(plans, mech):
    def summ(rows):
        closed = [r for r in rows if r["盈亏元"] is not None]
        return len(closed), sum(r["盈亏元"] for r in closed)
    books = [("清单计划单", plans), ("B 只做清单方向", [t for t in mech if t["账本"] == "B"]),
             ("A 全做（对照）", [t for t in mech if t["账本"] == "A"])]
    cells = "".join(f"<div><b class='{'up' if v > 0 else 'down' if v < 0 else ''}'>{v:+,}</b><span>{esc(nm)} · 已平 {n} 笔</span></div>"
                    for nm, rows in books for n, v in [summ(rows)])
    rows = []
    for tag, rs in [("清单", [r for r in plans if r["开仓日"]]), ("", mech)]:
        for r in rs:
            rows.append(f"<tr><td>{esc(tag or r['账本'])}</td><td>{esc(r['品种'])}{esc(r['方向'])}</td><td>{r['开仓日'][5:]}</td>"
                        f"<td>{fmt(r['开仓价'])}</td><td>{fmt(r['止损'])}</td><td>{r['平仓日'][5:]}</td><td>{fmt(r['平仓价'])}</td>"
                        f"<td>{esc(r['状态'])}</td><td>{money(r['盈亏元']) or ('浮 ' + money(r['浮动']) if r['浮动'] is not None else '')}</td></tr>")
    table = ("<div class='tw'><table><thead><tr><th>账本</th><th>品种</th><th>开仓</th><th>开仓价</th><th>止损</th><th>平仓</th><th>平仓价</th><th>结果</th><th>盈亏</th></tr></thead><tbody>"
             + "".join(rows) + "</tbody></table></div>") if rows else ""
    line = ("还没有成交，从 11-27 开始记。" if not rows else "") + "B 和 A 用同一套机械规则，区别只在看不看方向清单。按日线核对，同日碰止损和止盈算止损，每笔扣 2 跳成本。"
    return f"<p class='label'>模拟盘账本</p><div class='books'>{cells}</div><p class='bookline'>{line}</p>{table}"


def rest_src(r, src):
    parts = ([esc(r["more"])] if r["more"] else []) + ([links(src, r["src"])] if r["src"] else [])
    return f"<p class='src'>{' · '.join(parts)}</p>" if parts else ""


def body():
    L_ = json.loads((L.SIM / "list.json").read_text(encoding="utf-8"))
    src = L_["sources"]
    plans_raw = json.loads((L.SIM / "plans.json").read_text(encoding="utf-8"))
    pb = L.plan_book(); mech = L.mech_books()
    m = L_["宏观"]
    head = (f"<div class='hd'><div><h1>方向模拟盘</h1><div class='sub'>{esc(L_['期数'])} · {L_['日期'][5:]} 开盘用 · 价格截至 {L_['数据截至'][5:]} 收盘 · 纸面记录，不构成投资建议</div></div></div>"
            f"<p class='bg'><b>{esc(m['标题'])}。</b>{esc(m['内容'])} {links(src, m['来源'])}</p>")
    cards = []
    for t in L_["trades"]:
        plan = next((p for p in reversed(plans_raw) if p["code"] == t["code"]), None)
        marks = []
        for r in [r for r in pb if r["品种"] == t["n"] and r["开仓日"]] + [r for r in mech if r["账本"] == "B" and r["品种"] == t["n"]]:
            marks.append((r["开仓日"], r["开仓价"], "in", f"{r['品种']}{r['方向']} 开 {r['开仓价']:g}"))
            if r["平仓日"]:
                marks.append((r["平仓日"], r["平仓价"], "out", f"{r['状态']} {r['平仓价']:g}"))
        try:
            chart = kchart(t["code"], plan, marks, t["d"])
        except Exception as e:  # 图出错不影响页面其他部分
            chart = f"<p class='muted'>K 线图生成失败：{esc(e)}</p>"
        cards.append(
            f"<div class='oc'><div class='oh'><span class='nm'>{esc(t['n'])}</span><span class='cd'>{esc(t['c'])}</span>{pill(t['d'])}"
            f"<span class='rk'>1 手 · 最多亏 {esc(t['risk'])}</span></div>"
            f"<p class='one'>{esc(t['one'])}</p>"
            f"<div class='px'><div><small>开仓</small><b>{esc(t['entry']['v'])}</b><span>{esc(t['entry']['sub'])}</span></div>"
            f"<div><small>止损</small><b class='stop'>{esc(t['stop']['v'])}</b><span>{esc(t['stop']['sub'])}</span></div>"
            f"<div><small>止盈</small><b class='tp'>{esc(t['tp']['v'])}</b><span>{esc(t['tp']['sub'])}</span></div></div>"
            f"{chart}<p class='how'>{esc(t['how'])}</p><p class='note'>{esc(t['warn'])}</p>"
            f"<details><summary>开仓依据</summary><div class='why'>"
            f"<div><h4>基本面</h4><p>{esc(t['fund'])}</p></div><div><h4>笔记里的规则</h4><p>{esc(t['notes'])}</p></div>"
            f"<div><h4>重仓 6 条</h4><p>{esc(t['six'])} · {CONF.get(t['conf'], '')}</p></div>"
            f"<div class='src'>{esc(t['tech'])}<br>来源：{links(src, t['src'])}</div></div></details></div>")
    chips = "".join(
        f"<details class='chip'><summary>{esc(r['n'])}{pill(r['d'], '偏空不开' if r['d'] == 's' else '不做')}</summary>"
        f"<p>{esc(r['why'])}</p>{rest_src(r, src)}</details>" for r in L_["rest"])
    conf = "".join(f"<li>{esc(x)}</li>" for x in L_["把握"])
    return (CSS + "<div class='sim'>" + head
            + f"<p class='label'>今天的单子</p>{''.join(cards)}"
            + ledger_html(pb, mech)
            + f"<p class='label'>今天不做 · 点开看原因</p><div class='chips'>{chips}</div>"
            + f"<details class='foot'><summary>哪些有把握，哪些没把握</summary><ul style='margin:6px 0 0 18px'>{conf}</ul></details></div>")
