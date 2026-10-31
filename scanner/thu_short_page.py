#!/usr/bin/env python3
"""「周四做空」纸面实盘页面（thushort.html），供 build_site.py 调用。数据：data/thu_short/state.json"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import thu_short_live as L  # noqa: E402

LEG_NAME = {"IF": "A 期货 IF 沪深300", "IO": "B 期权 IO 沪深300 认沽", "HO": "C 期权 HO 上证50 认沽"}
LEG_COLOR = {"IF": "var(--cyan)", "IO": "var(--amber)", "HO": "#8b5cf6"}


def money(x):
    return f"{'+' if x > 0 else ''}{x:,.0f}"


def body():
    st = L.load_state()
    s = L.summary(st)
    t = st["trades"]
    head = ("<div class='hd'><div><h1>周四做空 · 纸面实盘</h1><div class='sub'>每周三收盘开 → 周五收盘平 ｜ A：IF 期货空一手（亏损达保证金 50% 止损）｜ "
            "B：IO 沪深300 平值认沽一手 ｜ C：HO 上证50 平值认沽一手（期权权利金亏 50% 止损）｜ "
            f"{st['start']} 起 ｜ 纸面记录，不构成投资建议</div></div></div>")
    kp = []
    for leg in L.LEGS:
        x = s[leg]
        kp.append((money(x["累计元"]), f"{LEG_NAME[leg]} 累计（元）", "up" if x["累计元"] > 0 else "down" if x["累计元"] < 0 else ""))
    kp.append((f"{s['笔数']}", "已完成周数", ""))
    kpis = "<div class='kpis'>" + "".join(f"<div class='kpi'><div class='v {c}'>{v}</div><div class='k'>{k}</div></div>" for v, k, c in kp) + "</div>"
    o = st["open"]
    if o:
        items = []
        a = o["legs"]["IF"]
        items.append(f"<li>A 期货：IF 主力 <b>{a['open']:.1f}</b> 空 1 手，止损价 {a['stop']:.1f}</li>")
        for leg in L.OPTS:
            b = o["legs"][leg]
            items.append(f"<li>{L.LEG_TAG[leg]} 期权：<b>{b['ex_code']}</b> 买 1 手，权利金 <b>{b['open']:.1f}</b> 点（{b['src_open']}），止损价 {b['stop']:.1f}，到期 {b['expiry']}</li>")
        now = (f"<div class='card' style='border-left:4px solid var(--cyan)'><h3>当前持仓 · {o['open_date']}（周三）收盘开，本周五收盘平</h3><ul style='margin:6px 0 0 18px;padding:0'>{''.join(items)}</ul></div>")
    else:
        nxt = "下一个周三收盘" if t else f"{st['start']}（周三）收盘"
        now = (f"<div class='card' style='border-left:4px solid var(--amber)'><h3>当前无持仓</h3><div>{nxt}开仓。周三 14:50 左右会先微信推送一次预告（按当时点位的拟买合约），方便收盘前下单。</div></div>")
    curve = ""
    if len(t) >= 2:
        W, H, Lp, Rp, T, B = 900, 200, 64, 12, 12, 24
        series = {}
        for leg in L.LEGS:
            c, arr = 0, []
            for x in t:
                c += x["legs"].get(leg, {}).get("pnl", 0)
                arr.append(c)
            series[leg] = arr
        allv = [v for a in series.values() for v in a] + [0]
        lo, hi = min(allv), max(allv)
        pad = (hi - lo) * 0.15 or 1000
        lo, hi = lo - pad, hi + pad
        n = len(t)
        px = lambda i: Lp + i * (W - Lp - Rp) / (n - 1)
        py = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
        lines = "".join(f"<polyline points='{' '.join(f'{px(i):.1f},{py(v):.1f}' for i, v in enumerate(a))}' fill='none' stroke='{LEG_COLOR[leg]}' stroke-width='2'/>" for leg, a in series.items())
        xl = "".join(f"<text x='{px(i):.1f}' y='{H - 6}' font-size='10' text-anchor='middle' fill='var(--muted)'>{x['close_date'][5:]}</text>" for i, x in enumerate(t) if i % max(1, n // 8) == 0 or i == n - 1)
        legend = "　".join(f"<span style='color:{LEG_COLOR[leg]}'>━ {LEG_NAME[leg]}</span>" for leg in L.LEGS)
        curve = (f"<div class='card'><h3>累计盈亏（元，每条腿一手）</h3><div style='font-size:12px;margin-bottom:4px'>{legend}</div>"
                 f"<svg viewBox='0 0 {W} {H}' width='100%' style='display:block'><line x1='{Lp}' x2='{W - Rp}' y1='{py(0):.1f}' y2='{py(0):.1f}' stroke='var(--muted)'/>"
                 f"<text x='{Lp - 6}' y='{py(0) + 3:.1f}' font-size='10' text-anchor='end' fill='var(--muted)'>0</text>{lines}{xl}</svg></div>")
    rows = ""
    for x in reversed(t):
        a = x["legs"]["IF"]
        cells = [f"<td>{x['open_date'][5:]} → {x['close_date'][5:]}</td>",
                 f"<td>{a['open']:.1f} → {a['close']:.1f}{'（止损）' if a.get('stop_day') else '*' if a.get('roll_fix') else ''}</td><td class='{'up' if a['pnl'] > 0 else 'down'}'>{money(a['pnl'])}</td>"]
        for leg in L.OPTS:
            b = x["legs"].get(leg)
            if not b:
                cells.append("<td>—</td><td>—</td>")
                continue
            cells.append(f"<td>{b['ex_code']}<br><span class='muted' style='font-size:11px'>{b['open']:.1f} → {b['close']:.1f}{'（止损）' if b.get('stop_day') else ''}</span></td>"
                         f"<td class='{'up' if b['pnl'] > 0 else 'down'}'>{money(b['pnl'])}<br><span class='muted' style='font-size:11px'>{b['ret_pct']:+.0f}%</span></td>")
        rows += "<tr>" + "".join(cells) + "</tr>"
    table = (f"<div class='card'><h3>逐笔记录</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th>周三 → 周五</th><th>A IF 开→平</th><th>A 盈亏</th>"
             f"<th>B IO 合约 / 权利金</th><th>B 盈亏</th><th>C HO 合约 / 权利金</th><th>C 盈亏</th></tr></thead><tbody>{rows or '<tr><td colspan=7 class=muted>还没有完成的交易</td></tr>'}</tbody></table></div>"
             "<div class='muted' style='font-size:11.5px;margin-top:6px'>* 周三到周五之间主力合约换月，期货盈亏按沪深300指数同期涨跌折算。期权价格优先用新浪真实日收盘价，拿不到时用公式估算。"
             "期权 50% 止损：周四、周五任一天最低价跌到买入价一半即按止损价卖出；期货止损：浮亏达一手保证金（按 12%）的一半，即 IF 比开仓价涨 6%。</div></div>")
    ref = ""
    try:
        v = json.loads((ROOT / "experiments" / "thu_short_variants_2026.json").read_text(encoding="utf-8"))
        a = next(x for x in v if x["品种"] == "沪深300" and x["做法"].startswith("周三收盘"))
        b = next(x for x in v if x["品种"] == "沪深300" and x["做法"] == "买平值认沽")
        c = next(x for x in v if x["品种"] == "上证50" and x["做法"] == "买平值认沽")
        ref = (f"<details><summary>规则来源与回测参考</summary><div class='card' style='border-radius:0 0 8px 8px;font-size:13px;line-height:1.75'>"
               f"2026 年上证指数周四下跌占比 63%、周五 55%，明显高于往年（2005–2025 年分别为 52%、47%）。按 2026 年 1–10 月回测（每次一手）："
               f"A IF 周三收盘→周五收盘 {a['次数']} 周赚 {a['赚钱次数']} 周、累计 {money(a['累计元'])} 元；"
               f"B IO 买平值认沽累计 {money(b['累计元'])} 元；C HO 买平值认沽累计 {money(c['累计元'])} 元（期权为周四开盘→周五收盘、公式估算）。<br>"
               "<b>注意</b>：这条规律是从 2026 年的数据里挑出来的，再用 2026 年回测必然好看；拉长到 2005–2025 年，沪深300、上证50 周四做空合计是亏的（见 experiments/thu_short_hist.json）。"
               "另外，真实期权价格明显高于回测里的公式估算（例如 10 月 30 日 HO2611-P-2750 收盘 54.4 点，公式估约 30 点），权利金更贵意味着回测收益可能被高估。"
               "纸面实盘的意义就是看它在没被挑过的未来是否还成立，2027 年再按实盘结果调整。<br>"
               "<b>成本</b>：期货开仓、平昨各万分之 0.23 + 每边 1 跳；期权每边 1 跳 + 手续费 15 元。代码：scanner/thu_short_live.py。</div></details>")
    except Exception:
        pass
    return head + kpis + now + curve + table + ref
