#!/usr/bin/env python3
"""「方向清单模拟盘」记账，供 sim_page.py 调用。只读 data/history/ 主力连续日线和 data/sim/。
三本账：
- 清单计划单：data/sim/plans.json 里每期给出的开仓/止损/止盈价，按日线核对。
- B 账：机械规则，只做 data/sim/directions.json 允许的方向。
- A 账：同一套机械规则，不看方向全做（对照组）。
核对口径（偏保守）：同一天碰到止损和止盈算止损；开盘已跳到止损外这一单不成立；每笔扣 2 跳成本。
机械规则：前一日收盘在21线上→突破前3根最高+3跳开多；21线下→跌破前3根最低-3跳开空；
止损取前3根另一端和21线中离开仓价近的那个(再让3跳)；每手风险>1000元不开；
目标=2倍风险；浮盈到1倍风险提保本；收盘反穿21线平。
"""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SIM = ROOT / "data" / "sim"
HIST = ROOT / "data" / "history"
UNIVERSE = {"RB0": ("螺纹", 10), "V0": ("PVC", 5), "SA0": ("纯碱", 20), "C0": ("玉米", 10), "M0": ("豆粕", 10)}
START = "2026-11-27"


def _load(name, default):
    p = SIM / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def hist(code):
    d = pd.read_csv(HIST / f"{code}.csv", parse_dates=["date"]).set_index("date")
    d["ma21"] = d.close.rolling(21).mean()
    return d


def plan_book():
    out = []
    for p in _load("plans.json", []):
        d = hist(p["code"])
        bars = d[d.index > p["日期"]]
        long = p["方向"] == "多"; sg = 1 if long else -1
        st = dict(计划=p["id"], 品种=p["品种"], 方向=p["方向"], 状态="待触发", 开仓日="", 开仓价=None, 平仓日="",
                  平仓价=None, 盈亏元=None, 浮动=None, 止损=p["止损"], 止盈=p["止盈"])
        stop = p["止损"]; n = 0; entry = None
        for dt, b in bars.iterrows():
            day = dt.strftime("%Y-%m-%d")
            if entry is None:
                n += 1
                if n > p.get("有效天数", 5):
                    st["状态"] = "作废(没成交)"; break
                for o in p["开仓"]:
                    e = None
                    if long and o["方式"] == "突破" and b.high >= o["价"]:
                        e = max(o["价"], b.open)
                    elif long and o["方式"] == "回踩" and b.low <= o["价"] and b.close >= b.ma21:
                        e = min(o["价"], b.open)
                    elif not long and b.high >= o["价"] and b.close <= p.get("开仓上限", 1e18) and b.open < p.get("开仓上限", 1e18):
                        e = max(o["价"], b.open)
                    if e is not None and ((long and e <= stop) or (not long and e >= stop)):
                        e = None
                    if e is not None:
                        entry = float(e); st.update(状态="持仓", 开仓日=day, 开仓价=entry); break
                if entry is None:
                    continue
            hit_stop = b.low <= stop if long else b.high >= stop
            hit_tp = b.high >= p["止盈"] if long else b.low <= p["止盈"]
            if hit_stop:
                st.update(状态="止损" if stop != entry else "保本出", 平仓日=day, 平仓价=float(stop)); break
            if hit_tp:
                st.update(状态="止盈", 平仓日=day, 平仓价=float(p["止盈"])); break
            if (long and b.high >= p["保本触发"]) or (not long and b.low <= p["保本触发"]):
                stop = entry
            if day != st["开仓日"] and (b.close - b.ma21) * sg < 0:
                st.update(状态="破21线出", 平仓日=day, 平仓价=float(b.close)); break
            st["止损"] = stop
        if st["平仓价"] is not None:
            st["盈亏元"] = round((st["平仓价"] - st["开仓价"]) * sg * p["乘数"] - 2 * p["乘数"])
        elif st["开仓价"] is not None:
            st["浮动"] = round((float(d.close.iloc[-1]) - st["开仓价"]) * sg * p["乘数"])
        out.append(st)
    return out


def mech_books(start=START):
    dirs = _load("directions.json", {})

    def allowed(day, code):
        ks = sorted(k for k in dirs if k <= day)
        return dirs[ks[-1]].get(code, "f") if ks else "f"

    trades = []
    for code, (name, m) in UNIVERSE.items():
        d = hist(code); idx = list(d.index)
        for book in "AB":
            pos = None
            for i in range(25, len(idx)):
                day = idx[i].strftime("%Y-%m-%d")
                if day < start:
                    continue
                b = d.iloc[i]; prev = d.iloc[i - 3:i]; y = d.iloc[i - 1]
                if pos is None:
                    side = "l" if y.close > y.ma21 else "s"
                    if book == "B" and allowed(day, code) != side:
                        continue
                    if side == "l":
                        e = prev.high.max() + 3; stop = round(max(prev.low.min(), y.ma21) - 3)
                        if stop >= e or (e - stop) * m > 1000 or b.high < e or b.open <= stop:
                            continue
                        e = max(e, b.open)
                    else:
                        e = prev.low.min() - 3; stop = round(min(prev.high.max(), y.ma21) + 3)
                        if stop <= e or (stop - e) * m > 1000 or b.low > e or b.open >= stop:
                            continue
                        e = min(e, b.open)
                    sg = 1 if side == "l" else -1; r = abs(e - stop)
                    pos = dict(账本=book, 品种=name, 方向="多" if sg > 0 else "空", 开仓日=day, 开仓价=float(e), 止损=float(stop),
                               止盈=float(round(e + sg * 2 * r)), _r=r, _sg=sg, 平仓日="", 平仓价=None, 状态="持仓", 盈亏元=None, 浮动=None)
                p = pos; sg = p["_sg"]
                hit_stop = b.low <= p["止损"] if sg > 0 else b.high >= p["止损"]
                hit_tp = b.high >= p["止盈"] if sg > 0 else b.low <= p["止盈"]
                out = None
                if hit_stop:
                    out = (p["止损"], "止损" if p["止损"] != p["开仓价"] else "保本出")
                elif hit_tp:
                    out = (p["止盈"], "止盈")
                elif day != p["开仓日"] and (b.close - b.ma21) * sg < 0:
                    out = (float(b.close), "破21线出")
                if out:
                    p.update(平仓日=day, 平仓价=out[0], 状态=out[1], 盈亏元=round((out[0] - p["开仓价"]) * sg * m - 2 * m))
                    trades.append(p); pos = None; continue
                if (b.high - p["开仓价"] if sg > 0 else p["开仓价"] - b.low) >= p["_r"]:
                    p["止损"] = p["开仓价"]
            if pos:
                pos["浮动"] = round((float(d.close.iloc[-1]) - pos["开仓价"]) * pos["_sg"] * m)
                trades.append(pos)
    for t in trades:
        t.pop("_r", None); t.pop("_sg", None)
    return sorted(trades, key=lambda t: (t["账本"], t["开仓日"]))


if __name__ == "__main__":
    for r in plan_book():
        print(r)
    for r in mech_books():
        print(r)
