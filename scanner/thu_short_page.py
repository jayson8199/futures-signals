#!/usr/bin/env python3
"""「周四做空」纸面实盘页面（thushort.html），供 build_site.py 调用。数据：data/thu_short/state.json"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import thu_short_live as L  # noqa: E402


def body():
    st = L.load_state()
    s = L.summary(st)
    t = st["trades"]
    head = ("<div class='hd'><div><h1>周四做空 · 纸面实盘</h1><div class='sub'>每周三收盘开空 → 周五收盘平仓 ｜ A：沪深300 股指期货 IF 一手 ｜ B：沪深300 股指期权 买平值认沽一手 ｜ "
            f"{st['start']} 起 ｜ 纸面记录，不构成投资建议</div></div></div>")
    def money(x):
        return f"{'+' if x > 0 else ''}{x:,.0f}"
    kp = [(money(s["期货"]["累计元"]), "A 期货累计（元）", "up" if s["期货"]["累计元"] > 0 else "down" if s["期货"]["累计元"] < 0 else ""),
          (f"{s['期货']['赚钱笔数']}/{s['笔数']}" if t else "—", "A 赚钱笔数", ""),
          (money(s["期权"]["累计元"]), "B 期权累计（元）", "up" if s["期权"]["累计元"] > 0 else "down" if s["期权"]["累计元"] < 0 else ""),
          (f"{s['期权']['赚钱笔数']}/{s['笔数']}" if t else "—", "B 赚钱笔数", ""),
          (money(s["期货"]["最大回撤元"]), "A 最大回撤（元）", "down" if s["期货"]["最大回撤元"] < 0 else "")]
    kpis = "<div class='kpis'>" + "".join(f"<div class='kpi'><div class='v {c}'>{v}</div><div class='k'>{k}</div></div>" for v, k, c in kp) + "</div>"
    o = st["open"]
    if o:
        now = (f"<div class='card' style='border-left:4px solid var(--cyan)'><h3>当前持仓 · {o['open_date']}（周三）收盘开</h3>"
               f"<div>A 期货：IF 主力 <b>{o['fut_open']:.1f}</b> 空 1 手 ｜ B 期权：<b>{o['opt_code']}</b>（行权价 {o['K']}，到期 {o['expiry']}）买 1 手，权利金 <b>{o['opt_open']:.1f}</b> 点（{o['opt_src_open']}）</div>"
               f"<div class='muted' style='margin-top:6px'>沪深300 开仓时 {o['idx_open']:.2f}，本周五收盘平仓。</div></div>")
    else:
        nxt = "下一个周三收盘" if t else f"{st['start']}（周三）收盘"
        now = f"<div class='card' style='border-left:4px solid var(--amber)'><h3>当前无持仓</h3><div>{nxt}开第{'' if t else '一'}笔。</div></div>"
    curve = ""
    if len(t) >= 2:
        W, H, Lp, Rp, T, B = 900, 200, 60, 12, 12, 24
        a, b = [], []
        ca = cb = 0
        for x in t:
            ca += x["fut_pnl"]
            cb += x["opt_pnl"]
            a.append(ca)
            b.append(cb)
        lo, hi = min(a + b + [0]), max(a + b + [0])
        pad = (hi - lo) * 0.15 or 1000
        lo, hi = lo - pad, hi + pad
        n = len(t)
        px = lambda i: Lp + i * (W - Lp - Rp) / (n - 1)
        py = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
        pa = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(a))
        pb = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(b))
        xl = "".join(f"<text x='{px(i):.1f}' y='{H - 6}' font-size='10' text-anchor='middle' fill='var(--muted)'>{x['close_date'][5:]}</text>" for i, x in enumerate(t) if i % max(1, n // 8) == 0 or i == n - 1)
        curve = (f"<div class='card'><h3>累计盈亏（元，每次一手）</h3><div style='font-size:12px;margin-bottom:4px'><span style='color:var(--cyan)'>━ A 期货</span>　<span style='color:var(--amber)'>━ B 期权</span></div>"
                 f"<svg viewBox='0 0 {W} {H}' width='100%' style='display:block'><line x1='{Lp}' x2='{W - Rp}' y1='{py(0):.1f}' y2='{py(0):.1f}' stroke='var(--muted)'/>"
                 f"<text x='{Lp - 6}' y='{py(0) + 3:.1f}' font-size='10' text-anchor='end' fill='var(--muted)'>0</text>"
                 f"<polyline points='{pa}' fill='none' stroke='var(--cyan)' stroke-width='2'/><polyline points='{pb}' fill='none' stroke='var(--amber)' stroke-width='2'/>{xl}</svg></div>")
    rows = "".join(
        f"<tr><td>{x['open_date'][5:]} → {x['close_date'][5:]}</td><td class='{'down' if x['idx_ret_pct'] < 0 else 'up'}'>{x['idx_ret_pct']:+.2f}%</td>"
        f"<td>{x['fut_open']:.1f} → {x['fut_close']:.1f}{'*' if x['roll_fix'] else ''}</td><td class='{'up' if x['fut_pnl'] > 0 else 'down'}'>{money(x['fut_pnl'])}</td>"
        f"<td>{x['opt_code']}</td><td>{x['opt_open']:.1f} → {x['opt_close']:.1f}</td><td class='{'up' if x['opt_pnl'] > 0 else 'down'}'>{money(x['opt_pnl'])}（{x['opt_ret_pct']:+.0f}%）</td>"
        f"<td class='muted' style='font-size:11px'>{x['opt_src_open']}/{x['opt_src_close']}</td></tr>" for x in reversed(t))
    table = (f"<div class='card'><h3>逐笔记录</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th>周三 → 周五</th><th>沪深300</th><th>A 期货 开→平</th><th>A 盈亏（元）</th>"
             f"<th>B 合约</th><th>B 权利金 开→平</th><th>B 盈亏（元）</th><th>期权价格来源</th></tr></thead><tbody>{rows or '<tr><td colspan=8 class=muted>还没有完成的交易</td></tr>'}</tbody></table></div>"
             "<div class='muted' style='font-size:11.5px;margin-top:6px'>* 周三到周五之间主力合约换月，期货盈亏按沪深300指数同期涨跌折算。期权价格优先用新浪的真实日收盘价，拿不到时用公式估算。</div></div>")
    ref = ""
    try:
        v = json.loads((ROOT / "experiments" / "thu_short_variants_2026.json").read_text(encoding="utf-8"))
        a = next(x for x in v if x["品种"] == "沪深300" and x["做法"].startswith("周三收盘"))
        b = next(x for x in v if x["品种"] == "沪深300" and x["做法"] == "买平值认沽")
        ref = (f"<details><summary>规则来源与回测参考</summary><div class='card' style='border-radius:0 0 8px 8px;font-size:13px;line-height:1.75'>"
               f"2026 年上证指数周四下跌占比 63%、周五 55%，明显高于往年（2005–2025 年分别为 52%、47%）。按 2026 年 1–10 月回测："
               f"A 期货周三收盘→周五收盘 {a['次数']} 周赚 {a['赚钱次数']} 周、累计 {money(a['累计元'])} 元、最大回撤 {money(a['最大回撤元'])} 元；"
               f"B 买平值认沽（周四开盘→周五收盘，公式估算）赚 {b['赚钱次数']} 周、累计 {money(b['累计元'])} 元、平均权利金约 {b['投入资金元']:,} 元。<br>"
               "<b>注意</b>：这条规律是从 2026 年的数据里挑出来的，再用 2026 年回测必然好看；拉长到 2005–2025 年，沪深300 周四做空合计是亏的（见 experiments/thu_short_hist.json）。"
               "纸面实盘的意义就是看它在没被挑过的未来是否还成立，2027 年再按实盘结果调整。<br>"
               "<b>成本</b>：期货开仓、平昨各万分之 0.23 + 每边 1 跳；期权每边 1 跳 + 手续费 15 元。代码：scanner/thu_short_live.py。</div></details>")
    except Exception:
        pass
    return head + kpis + now + curve + table + ref
