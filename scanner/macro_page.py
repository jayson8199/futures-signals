#!/usr/bin/env python3
"""
宏观时钟页面（美林时钟 · 中国版）：供 build_site.py 调用
  banner_html(root)  → 每页顶部一条横幅，显示当前时期
  macro_body()       → 「宏观时钟」整页
口径（2026-10-30 与用户确认）：主表盘 PPI + PMI；旁边并列 CPI + PMI、货币(Shibor 3M) + 信用(M2)。
定位：背景参考，不是交易信号（三种口径对商品后续收益的区分度均不显著，见 experiments/macro_clock_compare.json）。
数据：data/macro/（macro.yml 每月 1、16 日更新）；判定与回测逻辑在 scanner/macro_clock.py。
"""
import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
import macro_clock as mc  # noqa: E402

PH_COLOR = {"复苏": "#2f80ed", "过热": "#e5484d", "滞胀": "#d9822b", "衰退": "#6b7a90"}
HANDBOOK = [  # 《王刚期货交易体系手册》2.2 表 2，原文照录
    ("衰退", "衰退期", "债券＞现金＞股票＞商品", "央行降息降准"),
    ("复苏", "复苏期", "股票＞债券＞现金＞商品", "（笔记注：2025 年可能是衰退后期与复苏前期）"),
    ("过热", "过热期", "商品＞股票＞现金＞债券", "央行加息"),
    ("滞胀", "滞胀期", "现金＞商品＞债券＞股票", "——"),
]
VIEWS = [("ppi", "PPI + PMI", "主口径"), ("cpi", "CPI + PMI", "对照"), ("mc:shibor3m:m2", "货币 + 信用", "对照")]
RULE = "ma3_vs_3ago"


def _phase_series(m, key):
    if key.startswith("mc:"):
        _, a, b = key.split(":")
        return mc.classify_mc(m, a, b, RULE)
    return mc.classify(m, key, RULE)


@lru_cache(maxsize=1)
def state():
    m = mc.load_macro()
    out = {"views": []}
    for key, label, role in VIEWS:
        ph = _phase_series(m, key).dropna()
        if ph.empty:
            continue
        cur = ph.iloc[-1]
        n = 0
        for v in reversed(ph.tolist()):
            if v != cur:
                break
            n += 1
        out["views"].append({"key": key, "label": label, "role": role, "phase": cur, "month": str(ph.index[-1]), "months_in": n,
                             "hist": [(str(k), v) for k, v in ph.iloc[-24:].items()]})
    g = mc.direction(m["pmi"], RULE)
    gi = m["pmi"].rolling(3).mean() - m["pmi"].rolling(3).mean().shift(3)
    ii = m["ppi"].rolling(3).mean() - m["ppi"].rolling(3).mean().shift(3)
    traj = pd.DataFrame({"g": gi, "i": ii}).dropna().iloc[-24:]
    out["traj"] = [(str(k), float(r.g), float(r.i)) for k, r in traj.iterrows()]
    cols = [c for c in ("pmi", "ppi", "cpi", "shibor3m", "m2") if c in m]
    out["table"] = m[cols].iloc[-13:]
    try:
        out["cmp"] = json.loads((ROOT / "experiments" / "macro_clock_compare.json").read_text(encoding="utf-8"))
    except Exception:
        out["cmp"] = None
    del g
    return out


def _pill(ph, big=False):
    c = PH_COLOR.get(ph, "#888")
    fs = "15px" if big else "12px"
    return f"<span style='display:inline-block;background:{c};color:#fff;border-radius:999px;padding:{'3px 12px' if big else '1px 9px'};font-size:{fs};font-weight:600'>{ph}期</span>"


def banner_html(root=""):
    try:
        st = state()
    except Exception:
        return ""
    if not st["views"]:
        return ""
    main = st["views"][0]
    others = st["views"][1:]
    agree = all(v["phase"] == main["phase"] for v in others)
    oth = " ｜ ".join(f"{v['label']}：{v['phase']}期" for v in others)
    return (f"<a href='{root}macro.html' style='display:flex;flex-wrap:wrap;align-items:center;gap:8px;text-decoration:none;color:var(--ink);"
            f"background:var(--panel);border:1px solid var(--line);border-left:4px solid {PH_COLOR.get(main['phase'], '#888')};border-radius:8px;padding:8px 14px;margin-bottom:12px;font-size:13px'>"
            f"<b>宏观时钟</b>{_pill(main['phase'])}<span class='muted'>PPI 口径 · 已持续 {main['months_in']} 个月 · 依据 {main['month']} 数据</span>"
            f"<span class='muted'>｜ {oth}{'（三个口径一致）' if agree else '（口径有分歧）'}</span>"
            f"<span class='muted' style='margin-left:auto'>背景参考，非交易信号 →</span></a>")


def _clock_svg(st):
    """四象限轨迹图：横轴=增长动量（PMI 3 月均值较 3 个月前），纵轴=通胀动量（PPI 同比 3 月均值较 3 个月前）"""
    W, H, P = 420, 420, 36
    tr = st["traj"]
    if not tr:
        return ""
    gx = max(abs(x[1]) for x in tr) * 1.25 or 1
    iy = max(abs(x[2]) for x in tr) * 1.25 or 1
    X = lambda v: P + (v + gx) / (2 * gx) * (W - 2 * P)
    Y = lambda v: H - P - (v + iy) / (2 * iy) * (H - 2 * P)
    cx, cy = X(0), Y(0)
    q = [("过热", X(gx) - 8, P + 18, "end"), ("滞胀", P + 8, P + 18, "start"), ("衰退", P + 8, H - P - 8, "start"), ("复苏", X(gx) - 8, H - P - 8, "end")]
    bg = (f"<rect x='{cx}' y='{P}' width='{W - P - cx}' height='{cy - P}' fill='{PH_COLOR['过热']}' opacity='.07'/>"
          f"<rect x='{P}' y='{P}' width='{cx - P}' height='{cy - P}' fill='{PH_COLOR['滞胀']}' opacity='.07'/>"
          f"<rect x='{P}' y='{cy}' width='{cx - P}' height='{H - P - cy}' fill='{PH_COLOR['衰退']}' opacity='.07'/>"
          f"<rect x='{cx}' y='{cy}' width='{W - P - cx}' height='{H - P - cy}' fill='{PH_COLOR['复苏']}' opacity='.07'/>")
    labels = "".join(f"<text x='{x}' y='{y}' text-anchor='{a}' font-size='15' font-weight='700' fill='{PH_COLOR[n]}'>{n}期</text>" for n, x, y, a in q)
    axes = (f"<line x1='{P}' x2='{W - P}' y1='{cy}' y2='{cy}' stroke='var(--muted)'/><line x1='{cx}' x2='{cx}' y1='{P}' y2='{H - P}' stroke='var(--muted)'/>"
            f"<text x='{W - P}' y='{cy - 6}' text-anchor='end' font-size='11' fill='var(--muted)'>增长加速 →</text>"
            f"<text x='{P}' y='{cy - 6}' font-size='11' fill='var(--muted)'>← 增长放缓</text>"
            f"<text x='{cx + 6}' y='{P - 8}' font-size='11' fill='var(--muted)'>↑ 通胀(PPI)上行</text>"
            f"<text x='{cx + 6}' y='{H - P + 22}' font-size='11' fill='var(--muted)'>↓ 通胀(PPI)下行</text>")
    pts = " ".join(f"{X(g):.1f},{Y(i):.1f}" for _, g, i in tr)
    n = len(tr)
    dots = "".join(f"<circle cx='{X(g):.1f}' cy='{Y(i):.1f}' r='{3 if k < n - 1 else 7}' fill='{'var(--ink)' if k < n - 1 else PH_COLOR[st['views'][0]['phase']]}' opacity='{0.25 + 0.75 * k / max(n - 1, 1):.2f}'/>" for k, (_, g, i) in enumerate(tr))
    lab = "".join(f"<text x='{X(g) + 8:.1f}' y='{Y(i) - 6:.1f}' font-size='10' fill='var(--muted)'>{d[2:]}</text>" for k, (d, g, i) in enumerate(tr) if k in (0, n - 1) or k % 6 == 0)
    return (f"<svg viewBox='0 0 {W} {H + 10}' width='100%' style='max-width:440px;display:block;margin:auto'>{bg}{axes}{labels}"
            f"<polyline points='{pts}' fill='none' stroke='var(--muted)' stroke-width='1.2' opacity='.6'/>{dots}{lab}</svg>")


def macro_body():
    st = state()
    if not st["views"]:
        return "<div class='card'>宏观数据尚未就绪。</div>"
    main = st["views"][0]
    others = st["views"][1:]
    agree = all(v["phase"] == main["phase"] for v in others)
    head = ("<div class='hd'><div><h1>宏观时钟 · 美林时钟中国版</h1><div class='sub'>依据《王刚期货交易体系手册》2.2 节 ｜ 主口径 PPI + 制造业 PMI ｜ 数据每月 1 日、16 日自动更新 ｜ "
            "<b>背景参考，不是交易信号</b></div></div></div>")
    t = st["table"]
    last = t.iloc[-1]
    prev3 = t.iloc[-4] if len(t) >= 4 else t.iloc[0]
    why = (f"制造业 PMI 近 3 个月均值 {t['pmi'].iloc[-3:].mean():.1f}，较再前 3 个月 {t['pmi'].iloc[-6:-3].mean():.1f} "
           f"{'上升' if t['pmi'].iloc[-3:].mean() > t['pmi'].iloc[-6:-3].mean() else '下降'}；"
           f"PPI 同比近 3 个月均值 {t['ppi'].iloc[-3:].mean():.1f}%，较再前 3 个月 {t['ppi'].iloc[-6:-3].mean():.1f}% "
           f"{'上升' if t['ppi'].iloc[-3:].mean() > t['ppi'].iloc[-6:-3].mean() else '下降'}。")
    view_cards = "".join(
        f"<div style='flex:1;min-width:180px;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:10px 12px'>"
        f"<div class='muted' style='font-size:12px'>{v['label']} · {v['role']}</div><div style='margin:6px 0'>{_pill(v['phase'], True)}</div>"
        f"<div class='muted' style='font-size:12px'>已持续 {v['months_in']} 个月 · 依据 {v['month']} 数据</div></div>" for v in st["views"])
    gap = "" if agree else ("<div style='margin-top:10px;font-size:13px'><b>口径分歧：</b>" + "；".join(f"{v['label']} 判为{v['phase']}期" for v in st["views"]) +
                            "。PPI 与 CPI 方向相反时，通常意味着上游涨价没有传导到消费端（工业品价格升、居民物价不动）。</div>")
    hero = (f"<div class='grid2'><div class='card'><h3>现在：{main['phase']}期</h3>{_clock_svg(st)}"
            f"<div class='muted' style='font-size:11.5px;text-align:center;margin-top:4px'>点 = 每个月的位置（近 24 个月，颜色越深越新，最大的点是最新）</div></div>"
            f"<div class='card'><h3>判定依据</h3><div style='font-size:14px;line-height:1.7'>{why}</div>"
            f"<div style='display:flex;gap:10px;flex-wrap:wrap;margin-top:12px'>{view_cards}</div>{gap}"
            f"<div class='muted' style='font-size:11.5px;margin-top:10px'>{main['month']} 的 CPI/PPI 于次月中旬公布，所以这里的判定从那时起才"
            f"\"已知\"。判定规则：3 个月均值与再前 3 个月比较，上升/下降。增长↑通胀↓=复苏，增长↑通胀↑=过热，增长↓通胀↑=滞胀，增长↓通胀↓=衰退。"
            f"货币+信用口径：Shibor 3M 下行=货币宽松，M2 同比上行=信用宽松；宽货币紧信用=衰退，双宽=复苏，紧货币宽信用=过热，双紧=滞胀。</div></div></div>")
    hb = "".join(f"<tr style='{('background:' + PH_COLOR[k] + '22;font-weight:600') if k == main['phase'] else ''}'><td>{'▶ ' if k == main['phase'] else ''}{name}</td>"
                 f"<td style='text-align:left'>{order}</td><td style='text-align:left' class='muted'>{sig}</td></tr>" for k, name, order, sig in HANDBOOK)
    handbook = ("<div class='card'><h3>手册 2.2 · 美林时钟四阶段（当前行高亮）</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th>阶段</th><th style='text-align:left'>资产优劣排序</th><th style='text-align:left'>信号</th></tr></thead>"
                f"<tbody>{hb}</tbody></table></div><div class='muted' style='font-size:11.5px;margin-top:6px'>手册原文：不同经济周期阶段，选择的标的类型不同。周期长度不固定，通常为 3–5 年，实际时长受经济政策、外部冲击等因素影响。</div></div>")
    # 指标表
    def arrow(col, i):
        if i < 1:
            return ""
        a, b = t[col].iloc[i], t[col].iloc[i - 1]
        if pd.isna(a) or pd.isna(b):
            return ""
        return "<span class='muted'>↑</span>" if a > b else ("<span class='muted'>↓</span>" if a < b else "")
    names = {"pmi": "制造业 PMI", "ppi": "PPI 同比 %", "cpi": "CPI 同比 %", "shibor3m": "Shibor 3M %", "m2": "M2 同比 %"}
    trs = "".join("<tr><td>" + str(idx) + "</td>" + "".join(f"<td>{'' if pd.isna(t[c].iloc[i]) else f'{t[c].iloc[i]:.2f}' if c == 'shibor3m' else f'{t[c].iloc[i]:.1f}'} {arrow(c, i)}</td>" for c in t.columns) + "</tr>"
                  for i, idx in reversed(list(enumerate(t.index))))
    ind = (f"<div class='card'><h3>指标（近 13 个月）</h3><div class='tbl' style='border-radius:8px'><table><thead><tr><th>月份</th>{''.join(f'<th>{names[c]}</th>' for c in t.columns)}</tr></thead><tbody>{trs}</tbody></table></div></div>")
    # 历史统计
    hist = ""
    cmp_ = st["cmp"]
    if cmp_:
        R = cmp_["results"]
        k_main = f"ppi|{RULE}"
        groups = ["商品等权", "黑色", "有色", "贵金属", "能化", "农产品", "股指IF"]
        rows = ""
        for g in groups:
            bp = R[k_main]["by_phase"].get(f"{g}|错开")
            if not bp:
                continue
            cells = "".join(
                f"<td style='{('background:' + PH_COLOR[p] + '22;font-weight:600') if p == main['phase'] else ''}' class='{'up' if (bp[p]['avg'] or 0) > 0 else 'down'}'>{bp[p]['avg']:+.2f}%<span class='muted' style='font-size:11px'> ({bp[p]['n']}月)</span></td>"
                if bp[p]["avg"] is not None else "<td>—</td>" for p in mc.PHASES)
            rows += f"<tr><td>{g}</td>{cells}</tr>"
        vrows = ""
        for key, label in ((f"ppi|{RULE}", "PPI + PMI（主口径）"), (f"cpi|{RULE}", "CPI + PMI"), (f"mc:shibor3m:m2|{RULE}", "货币(Shibor) + 信用(M2)"), (f"mc:shibor3m:tsf12|{RULE}", "货币(Shibor) + 信用(社融)")):
            if key not in R:
                continue
            bp = R[key]["by_phase"]["商品等权|错开"]
            sp = R[key]["spread"].get("商品等权|错开", {})
            vrows += ("<tr><td style='text-align:left'>" + label + "</td>" + "".join(f"<td>{bp[p]['avg']:+.2f}%</td>" if bp[p]["avg"] is not None else "<td>—</td>" for p in mc.PHASES)
                      + f"<td>{sp.get('过热-衰退', 0):+.2f}%</td><td>{sp.get('t', '—')}</td></tr>")
        span = R[k_main]["span"]
        hist = (f"<div class='card'><h3>历史上各时期之后一个月，商品怎么走（PPI 口径，{span[0]} ~ {span[1]}）</h3>"
                f"<div class='tbl' style='border-radius:8px'><table><thead><tr><th>品类</th>{''.join(f'<th>{p}期</th>' for p in mc.PHASES)}</tr></thead><tbody>{rows}</tbody></table></div>"
                "<div class='muted' style='font-size:11.5px;margin-top:6px'>每个月的判定从次月 17 日起才算已知（CPI/PPI 最晚 16 日公布），统计的是之后一个月的等权平均收益。高亮列 = 当前时期。</div>"
                f"<h4 style='margin:14px 0 6px'>四种口径对比：商品等权指数</h4><div class='tbl' style='border-radius:8px'><table><thead><tr><th style='text-align:left'>口径</th>{''.join(f'<th>{p}期</th>' for p in mc.PHASES)}<th>过热−衰退</th><th>t 值</th></tr></thead><tbody>{vrows}</tbody></table></div>"
                "<div style='font-size:13px;line-height:1.7;margin-top:10px'><b>结论：</b>四种口径的 t 值都不到 1（要到 2 左右才算可靠），即"
                "<b>历史上不同时期之后商品的涨跌差异，和随机分组分不开</b>。PPI 口径方向与教科书一致（衰退期商品最弱），CPI 口径则是复苏期商品最好；"
                "各口径下\"滞胀期\"商品都偏强，多半是倒因为果（商品大涨推高了通胀和利率）。所以本页只作宏观背景，不作为开平仓依据。</div></div>")
    research = ("<details><summary>相关研究（为什么美林时钟在中国只能当参考）</summary><div class='card' style='border-radius:0 0 8px 8px;font-size:13px;line-height:1.75'>"
                "<b>泽平宏观（2021）</b>：用 2002–2020 年中国数据检验经典美林时钟，准确率约 40%（美国同法为 88%）；商品在过热期最好只在 50% 的时候成立。"
                "原因包括央行多目标、供给侧改革等政策驱动行情、2012 年后经济波动收窄。改良版改用货币 + 信用划分，整体准确率 73%，但商品仅 57%。"
                "<a href='https://www.thepaper.cn/newsDetail_forward_11042732' target='_blank' rel='noopener'>原文</a><br>"
                "<b>上海证券基金评价研究中心（2022）</b>：以 PMI 等合成增长 + CPI 划分，中国商品最好的是复苏期而非过热期；各时期两两差异多不显著。"
                "<a href='https://pdf.dfcfw.com/pdf/H3_AP202207151576165879_1.pdf' target='_blank' rel='noopener'>原文</a><br>"
                "<b>香港金管局（2008）</b>：价格冲击从上游到下游逐级减弱，生产者价格反应快而大，消费者价格反应慢而小——这是 PPI 与 CPI 经常背离的原因。"
                "<a href='https://www.hkma.gov.hk/media/eng/publication-and-research/research/china-economic-issues/CEI_200801.pdf' target='_blank' rel='noopener'>原文</a><br>"
                "<span class='muted'>数据来源：国家统计局 PMI/CPI/PPI、人民银行 M2、全国银行间同业拆借中心 Shibor（经 akshare）。代码：scanner/macro_clock.py、scanner/macro_page.py。</span></div></details>")
    return head + hero + handbook + hist + ind + research
