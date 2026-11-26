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
.sim .orders{display:flex;flex-direction:column;gap:10px}
.sim .order{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:10px 12px}
.sim .order .nm{font-weight:700;font-size:15px}
.sim .lv{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:6px 0 4px}
.sim .lv div{display:flex;flex-direction:column;min-width:0}
.sim .lv small,.sim .tile small{font-size:11px;color:var(--muted)}
.sim .lv b,.sim .tile b{font-family:var(--mono);font-size:18px;line-height:1.3;white-space:nowrap}
.sim .stop{color:var(--amber)}.sim .tp{color:var(--cyan)}
.sim .how{font-size:12.5px;color:var(--muted)}
.sim .two{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media (max-width:720px){.sim .two{grid-template-columns:1fr}}
.sim .ttl{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.sim .ttl .nm{font-size:16px;font-weight:700}.sim .ttl .pill{margin-left:auto}
.sim .kc svg{display:block;width:100%;height:auto}
.sim .kc text{fill:var(--muted);font-family:var(--mono);font-size:11px}
.sim .kleg{display:flex;flex-wrap:wrap;gap:2px 12px;font-size:11px;color:var(--muted);margin-top:2px}
.sim .kleg i{display:inline-block;width:14px;border-top:2px dashed currentColor;vertical-align:middle;margin-right:4px}
.sim .tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:8px 0}
.sim .tile{background:var(--panel2);border-radius:6px;padding:6px 8px;display:flex;flex-direction:column;min-width:0}
.sim .tile span{font-size:11px;color:var(--muted);line-height:1.3}
.sim .warn{background:var(--amber-dim);color:var(--amber);border-radius:6px;padding:6px 10px;font-size:12.5px}
.sim details{margin-top:8px;border-top:1px solid var(--line);padding-top:6px}
.sim summary{cursor:pointer;color:var(--cyan);font-size:13px}
.sim .why{display:flex;flex-direction:column;gap:6px;margin-top:6px;font-size:13px}
.sim .why h4{font-size:11px;color:var(--muted);font-weight:600}
.sim .src{font-size:11.5px;color:var(--muted)}
.sim .rest .row{padding:8px 0;border-bottom:1px solid var(--line)}
.sim .rest .row:last-child{border-bottom:none}
.sim .rest .hd2{display:flex;align-items:center;gap:8px}
.sim .rest .hd2 .pill{margin-left:auto}
.sim .rest p{font-size:13px;margin-top:2px}
.sim .tw{overflow-x:auto}
.sim .pill.flat{color:var(--muted)}
</style>"""


def esc(x):
    return html.escape(str(x))


def links(src, keys):
    return " · ".join(f"<a href='{esc(src[k][1])}' target='_blank' rel='noopener'>{esc(src[k][0])}</a>" for k in keys if k in src)


def pill(d, txt=None):
    cls = {"l": "up", "s": "down"}.get(d, "flat")
    return f"<span class='pill {cls}'>{esc(txt or DIR[d])}</span>"


def kchart(code, plan, marks):
    """近 40 日 K 线（红涨绿跌）＋21 日线＋计划价位虚线＋成交标记，纯 SVG"""
    d = L.hist(code).tail(40)
    W, H, Lm, R, T, B = 360, 240, 2, 74, 8, 18
    n = len(d); cw = (W - Lm - R) / n
    lines = []
    if plan:
        for o in plan["开仓"]:
            lines.append((o["方式"], o["价"], "var(--ink)"))
        lines.append(("止损", plan["止损"], "var(--amber)"))
        lines.append(("止盈", plan["止盈"], "var(--cyan)"))
    vals = list(d.high) + list(d.low) + [v for _, v, _ in lines] + [m[1] for m in marks]
    lo, hi = min(vals), max(vals); pad = (hi - lo) * .05; lo -= pad; hi += pad
    y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    x = lambda i: Lm + cw * i + cw / 2
    g = []
    for i, b in enumerate(d.itertuples()):
        up = b.close >= b.open; col = "var(--up)" if up else "var(--down)"
        g.append(f"<line x1='{x(i):.1f}' x2='{x(i):.1f}' y1='{y(b.high):.1f}' y2='{y(b.low):.1f}' style='stroke:{col}'/>")
        t = y(max(b.open, b.close)); h = max(1, abs(y(b.open) - y(b.close)))
        g.append(f"<rect x='{x(i) - cw * .36:.1f}' y='{t:.1f}' width='{cw * .72:.1f}' height='{h:.1f}' style='fill:{'var(--panel)' if up else col};stroke:{col}'/>")
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(d.ma21) if pd.notna(v))
    g.append(f"<polyline points='{pts}' style='fill:none;stroke:var(--cyan);stroke-width:1.2;opacity:.5'/>")
    ls = sorted(([nm, v, c, y(v), y(v)] for nm, v, c in lines), key=lambda a: a[3])
    for i in range(1, len(ls)):
        if ls[i][4] - ls[i - 1][4] < 13:
            ls[i][4] = ls[i - 1][4] + 13
    for nm, v, c, yy, ty in ls:
        g.append(f"<line x1='{Lm}' x2='{W - R}' y1='{yy:.1f}' y2='{yy:.1f}' style='stroke:{c};stroke-width:1.4' stroke-dasharray='5 3'/>")
        g.append(f"<text x='{W - R + 4}' y='{ty + 4:.1f}' style='fill:{c}'>{esc(nm)} {v:g}</text>")
    di = {dt.strftime('%Y-%m-%d'): i for i, dt in enumerate(d.index)}
    for day, v, kind, tip in marks:
        if day not in di:
            continue
        xx, yy = x(di[day]), y(v)
        if kind == "in":
            g.append(f"<path d='M{xx - 6:.1f} {yy + 10:.1f}L{xx:.1f} {yy:.1f}L{xx + 6:.1f} {yy + 10:.1f}Z' style='fill:var(--cyan)'><title>{esc(tip)}</title></path>")
        else:
            g.append(f"<path d='M{xx - 5:.1f} {yy - 5:.1f}L{xx + 5:.1f} {yy + 5:.1f}M{xx + 5:.1f} {yy - 5:.1f}L{xx - 5:.1f} {yy + 5:.1f}' style='stroke:var(--ink);stroke-width:2'><title>{esc(tip)}</title></path>")
    for i in (0, n // 2, n - 1):
        g.append(f"<text x='{x(i):.1f}' y='{H - 4}' text-anchor='middle'>{d.index[i].strftime('%m-%d')}</text>")
    return (f"<div class='kc'><svg viewBox='0 0 {W} {H}' role='img' aria-label='近 40 日 K 线和计划价位'>{''.join(g)}</svg></div>"
            "<div class='kleg'><span><i></i>开仓</span><span style='color:var(--amber)'><i></i>止损</span>"
            "<span style='color:var(--cyan)'><i></i>止盈</span><span>▲ 开仓成交 ✕ 平仓 · 淡蓝线 21 日线</span></div>")


def fmt(v):
    return "" if v is None else f"{v:g}"


def money(v):
    return "" if v is None else f"<span class='{'up' if v > 0 else 'down' if v < 0 else ''}'>{v:+,}</span>"


def ledger_html(plans, mech):
    def summ(rows):
        closed = [r for r in rows if r["盈亏元"] is not None]
        return len(closed), sum(r["盈亏元"] for r in closed), sum(1 for r in closed if r["盈亏元"] > 0)
    books = [("清单计划单", plans), ("B 机械规则＋清单方向", [t for t in mech if t["账本"] == "B"]),
             ("A 机械规则全做（对照）", [t for t in mech if t["账本"] == "A"])]
    kp = "".join(f"<div class='kpi'><div class='v {'up' if s > 0 else 'down' if s < 0 else ''}'>{s:+,}</div>"
                 f"<div class='k'>{esc(nm)} · 已平 {n} 笔 · 赚 {w} 笔</div></div>" for nm, rows in books for n, s, w in [summ(rows)])
    rows = []
    for tag, rs in [("清单", [r for r in plans if r["开仓日"]]), ("", mech)]:
        for r in rs:
            rows.append(f"<tr><td>{esc(tag or r['账本'])}</td><td>{esc(r['品种'])}{esc(r['方向'])}</td><td>{r['开仓日']}</td>"
                        f"<td>{r['开仓价']:g}</td><td>{r['止损']:g}</td><td>{r['平仓日']}</td><td>{fmt(r['平仓价'])}</td>"
                        f"<td>{esc(r['状态'])}</td><td>{money(r['盈亏元']) or ('浮 ' + money(r['浮动']) if r['浮动'] is not None else '')}</td></tr>")
    pend = "；".join(f"{r['品种']}{r['方向']}：{r['状态']}" for r in plans if not r["开仓日"])
    return (f"<div class='kpis' style='grid-template-columns:repeat(3,1fr)'>{kp}</div>"
            f"<div class='card'><h3>每一笔</h3>{f'<p class=muted style=font-size:12px>等成交：{esc(pend)}</p>' if pend else ''}"
            "<div class='tw'><table><thead><tr><th>账本</th><th>品种</th><th>开仓日</th><th>开仓价</th><th>止损</th><th>平仓日</th><th>平仓价</th><th>结果</th><th>盈亏(元)</th></tr></thead><tbody>"
            + ("".join(rows) or "<tr><td colspan='9' class='muted'>还没有成交</td></tr>") + "</tbody></table></div>"
            "<p class='muted' style='font-size:12px;margin-top:6px'>按日线核对，偏保守：同一天碰到止损和止盈算止损；开盘跳到止损外这一单不算；每笔扣 2 跳成本。"
            "B 账和 A 账用同一套机械规则，唯一区别是看不看方向清单，比两本账就知道清单有没有用。</p></div>")


def rest_src(r, src):
    parts = ([esc(r["more"])] if r["more"] else []) + ([links(src, r["src"])] if r["src"] else [])
    return f"<p class='src'>{' · '.join(parts)}</p>" if parts else ""


def body():
    L_ = json.loads((L.SIM / "list.json").read_text(encoding="utf-8"))
    src = L_["sources"]
    plans_raw = json.loads((L.SIM / "plans.json").read_text(encoding="utf-8"))
    pb = L.plan_book(); mech = L.mech_books()
    head = (f"<div class='hd'><div><h1>方向清单 · 模拟盘</h1><div class='sub'>{esc(L_['期数'])} ｜ 用于 {L_['日期']} 开盘 ｜ 价格截至 {L_['数据截至']} 收盘 ｜ "
            "每个交易日早上更新方向，账本每次建站自动核对 ｜ 纸面记录，不构成投资建议</div></div></div>")
    orders = "".join(
        f"<div class='order'><div><span class='nm'>{esc(t['n'])}</span> {pill(t['d'], '做多' if t['d'] == 'l' else '做空')} <span class='muted'>1 手</span></div>"
        f"<div class='lv'><div><small>开仓</small><b>{esc(t['entry']['v'])}</b></div><div><small>止损</small><b class='stop'>{esc(t['stop']['v'])}</b></div>"
        f"<div><small>止盈</small><b class='tp'>{esc(t['tp']['v'])}</b></div></div>"
        f"<div class='how'>每手最多亏：{esc(t['risk'])}。{esc(t['how'])}</div></div>" for t in L_["trades"])
    today = (f"<div class='card'><h3>今天的单子</h3><div class='orders'>{orders}</div>"
             f"<p class='muted' style='font-size:12.5px;margin-top:8px'>{esc(L_['今天不开'])}</p></div>")
    m = L_["宏观"]
    macro = (f"<div class='card' style='border-left:3px solid var(--down)'><h3 class='blue'>{esc(m['标题'])}</h3>"
             f"<p style='font-size:13px'>{esc(m['内容'])}</p><p class='src' style='margin-top:4px'>{links(src, m['来源'])}</p></div>")
    cards = []
    for t in L_["trades"]:
        plan = next((p for p in reversed(plans_raw) if p["code"] == t["code"]), None)
        marks = []
        for r in [r for r in pb if r["品种"] == t["n"] and r["开仓日"]] + [r for r in mech if r["账本"] == "B" and r["品种"] == t["n"]]:
            marks.append((r["开仓日"], r["开仓价"], "in", f"{r['品种']}{r['方向']} 开 {r['开仓价']:g}"))
            if r["平仓日"]:
                marks.append((r["平仓日"], r["平仓价"], "out", f"{r['状态']} {r['平仓价']:g}"))
        try:
            chart = kchart(t["code"], plan, marks)
        except Exception as e:  # 图出错不影响页面其他部分
            chart = f"<p class='muted'>K 线图生成失败：{esc(e)}</p>"
        cards.append(
            f"<div class='card'><div class='ttl'><span class='nm'>{esc(t['n'])}</span><span class='muted num'>{esc(t['c'])}</span>{pill(t['d'])}</div>"
            f"<p style='font-size:13px;margin-bottom:6px'>{esc(t['one'])}</p>{chart}"
            f"<div class='tiles'><div class='tile'><small>开仓</small><b>{esc(t['entry']['v'])}</b><span>{esc(t['entry']['sub'])}</span></div>"
            f"<div class='tile'><small>止损</small><b class='stop'>{esc(t['stop']['v'])}</b><span>{esc(t['stop']['sub'])}</span></div>"
            f"<div class='tile'><small>止盈</small><b class='tp'>{esc(t['tp']['v'])}</b><span>{esc(t['tp']['sub'])}</span></div></div>"
            f"<div class='warn'>{esc(t['warn'])}</div>"
            f"<details><summary>开仓依据（基本面＋笔记）</summary><div class='why'>"
            f"<div><h4>基本面</h4><p>{esc(t['fund'])}</p></div><div><h4>笔记里的规则</h4><p>{esc(t['notes'])}</p></div>"
            f"<div><h4>重仓 6 条</h4><p>{esc(t['six'])} · {CONF.get(t['conf'], '')}</p></div>"
            f"<div class='muted num' style='font-size:11.5px'>{esc(t['tech'])}</div><div class='src'>来源：{links(src, t['src'])}</div></div></details></div>")
    rest = "".join(
        f"<div class='row'><div class='hd2'><b>{esc(r['n'])}</b>{pill(r['d'], '偏空·不开' if r['d'] == 's' else '不做')}</div>"
        f"<p>{esc(r['why'])}</p>{rest_src(r, src)}</div>"
        for r in L_["rest"])
    conf = "".join(f"<li>{esc(x)}</li>" for x in L_["把握"])
    return (CSS + "<div class='sim'>" + head + today
            + "<div class='card'><h3>模拟盘账本</h3><p class='muted' style='font-size:12.5px'>2026-11-27 起记，三本账对比。</p></div>"
            + ledger_html(pb, mech) + macro
            + f"<div class='two'>{''.join(cards)}</div>"
            + f"<div class='card rest'><h3>今天不做</h3>{rest}</div>"
            + f"<div class='card'><h3>哪些有把握，哪些没把握</h3><ul style='margin-left:18px;font-size:13px'>{conf}</ul></div></div>")
