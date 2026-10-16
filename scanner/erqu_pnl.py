#!/usr/bin/env python3
"""
二区定律「能不能赚钱」回测：把判定变成一笔日内虚拟仓位，算收益而不是对错。

策略（与实盘记录同一套规则）：
  S1  13:35 进场：按"二区+五区修正"后的最终判定，好→做多、坏→做空，13:35 bar 收盘价进场，当日收盘平仓
  S2  10:30 进场：只用二区判定，10:30 bar 收盘价进场，当日收盘平仓（不做修正，持仓更久）
  S3  10:30 进场 + 13:35 反手：二区判定 10:30 进场，若五区修正翻向则 13:35 平仓并反手
对照：
  B1  13:35 进场，方向 = 13:35 价位相对开盘（不看形态）
  B2  10:30 进场，方向 = 10:30 价位相对开盘
  B3  每天 13:35 无脑做多到收盘
指标：平均每笔收益(%)、胜率(严格 >0)、累计收益、最大回撤、年化夏普、不同成本下的净收益。
用法：python scanner/erqu_pnl.py --csv erqu_data/sse_5min.csv --daily experiments/sse_daily.csv
"""
import argparse
import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
Z5_END = "13:35"
COSTS = [0.0, 0.01, 0.03, 0.05]  # 单边成本 %：IF/IH 日内约 0.01-0.03%，ETF 约 0.01%+滑点


def classify_z2(z2):
    a, b = z2.iloc[:3], z2.iloc[3:]
    hh, hl = b["high"].max() > a["high"].max(), b["low"].min() > a["low"].min()
    lh, ll = b["high"].max() < a["high"].max(), b["low"].min() < a["low"].min()
    if hh and hl:
        return "好"
    if lh and ll:
        return "坏"
    c, o = z2.iloc[-1]["close"], z2.iloc[0]["open"]
    return "好" if c > o else ("坏" if c < o else None)


def day_signals(d, official):
    d = d.sort_values("time").copy()
    d["hm"] = d["time"].str[11:16]
    z2 = d[(d["hm"] > "10:00") & (d["hm"] <= "10:30")]
    if len(z2) < 6 or d["hm"].max() < "15:00":
        return None
    z2v = classify_z2(z2)
    if z2v is None:
        return None
    p1030 = float(z2.iloc[-1]["close"])
    upto = d[d["hm"] <= Z5_END]
    z5 = upto[upto["hm"] > "13:00"]
    before = upto[upto["hm"] <= "11:30"]
    if len(z5) == 0:
        return None
    new_low = z5["low"].min() < before["low"].min()
    new_high = z5["high"].max() > before["high"].max()
    final = z2v
    if z2v == "好" and new_low:
        final = "坏"
    elif z2v == "坏" and new_high:
        final = "好"
    p1335 = float(z5.iloc[-1]["close"])
    o = official[0] if official else float(d.iloc[0]["open"])
    c = official[1] if official else float(d.iloc[-1]["close"])
    return {"z2": z2v, "final": final, "p1030": p1030, "p1335": p1335, "open": o, "close": c}


def sgn(v):
    return 1 if v == "好" else -1


def ret(entry, exit_, side):
    return side * (exit_ / entry - 1) * 100


def strategies(r):
    out = {}
    out["S1_13:35进场(二区+修正)"] = (ret(r["p1335"], r["close"], sgn(r["final"])), 1)
    out["S2_10:30进场(仅二区)"] = (ret(r["p1030"], r["close"], sgn(r["z2"])), 1)
    if r["final"] == r["z2"]:
        out["S3_10:30进场+13:35反手"] = (ret(r["p1030"], r["close"], sgn(r["z2"])), 1)
    else:
        out["S3_10:30进场+13:35反手"] = (ret(r["p1030"], r["p1335"], sgn(r["z2"])) + ret(r["p1335"], r["close"], sgn(r["final"])), 2)
    b1 = 1 if r["p1335"] > r["open"] else (-1 if r["p1335"] < r["open"] else 0)
    b2 = 1 if r["p1030"] > r["open"] else (-1 if r["p1030"] < r["open"] else 0)
    out["B1_13:35价位方向"] = (ret(r["p1335"], r["close"], b1) if b1 else None, 1)
    out["B2_10:30价位方向"] = (ret(r["p1030"], r["close"], b2) if b2 else None, 1)
    out["B3_13:35无脑做多"] = (ret(r["p1335"], r["close"], 1), 1)
    return out


def stats(rets, trades_per, cost):
    xs = [x - 2 * cost * n for x, n in zip(rets, trades_per) if x is not None]
    if not xs:
        return None
    n = len(xs)
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else 0
    wins = sum(1 for x in xs if x > 0)
    cum, peak, mdd = 0.0, 0.0, 0.0
    for x in xs:
        cum += x
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    sharpe = mean / sd * math.sqrt(242) if sd else None
    return {"n": n, "avg_pct": round(mean, 4), "win_rate": round(wins / n * 100, 1), "cum_pct": round(cum, 2),
            "max_dd_pct": round(mdd, 2), "sharpe": round(sharpe, 2) if sharpe is not None else None,
            "avg_win": round(sum(x for x in xs if x > 0) / max(wins, 1), 3),
            "avg_loss": round(sum(x for x in xs if x <= 0) / max(n - wins, 1), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--daily")
    args = ap.parse_args()
    df = pd.read_csv(args.csv)
    df["day"] = df["time"].str[:10]
    daily = {}
    if args.daily:
        dd = pd.read_csv(args.daily, encoding="utf-8-sig")
        daily = {str(r["date"])[:10]: (float(r["open"]), float(r["close"])) for _, r in dd.iterrows()}
    rows = []
    for day, d in df.groupby("day"):
        r = day_signals(d, daily.get(day))
        if r:
            r["day"] = day
            r["strats"] = strategies(r)
            rows.append(r)
    names = list(rows[0]["strats"].keys())
    res = {"days": len(rows), "span": [rows[0]["day"], rows[-1]["day"]], "cost_note": "cost = 单边成本%，每笔按双边扣", "all": {}, "by_year": {}, "by_side": {}}

    def block(sub):
        b = {}
        for nm in names:
            b[nm] = {f"cost{c}": stats([r["strats"][nm][0] for r in sub], [r["strats"][nm][1] for r in sub], c) for c in COSTS}
        return b

    res["all"] = block(rows)
    for y in sorted({r["day"][:4] for r in rows}):
        res["by_year"][y] = block([r for r in rows if r["day"].startswith(y)])
    for side in ("好", "坏"):
        sub = [r for r in rows if r["final"] == side]
        res["by_side"][f"S1_final={side}"] = {"n": len(sub), **(stats([r["strats"][names[0]][0] for r in sub], [1] * len(sub), 0.0) or {})}
    # 简表
    print(f"交易日 {len(rows)}（{rows[0]['day']} ~ {rows[-1]['day']}）  单位：%  成本按单边 0.03% 双边扣")
    print(f"{'策略':<28}{'笔数':>5}{'均收益':>8}{'胜率':>7}{'累计':>8}{'最大回撤':>9}{'夏普':>6} | 净(0.03%)累计")
    for nm in names:
        s0, s3 = res["all"][nm]["cost0.0"], res["all"][nm]["cost0.03"]
        print(f"{nm:<28}{s0['n']:>5}{s0['avg_pct']:>8.3f}{s0['win_rate']:>6.1f}%{s0['cum_pct']:>8.1f}{s0['max_dd_pct']:>9.1f}{(s0['sharpe'] or 0):>6.2f} | {s3['cum_pct']:>7.1f}")
    print("\n分年（S1 13:35进场，零成本）：")
    for y, b in res["by_year"].items():
        s = b[names[0]]["cost0.0"]
        print(f"  {y}: n={s['n']} 均{s['avg_pct']:.3f}% 胜率{s['win_rate']}% 累计{s['cum_pct']}% 回撤{s['max_dd_pct']}% 夏普{s['sharpe']}")
    print("\n分方向（S1）：", json.dumps(res["by_side"], ensure_ascii=False))
    out = ROOT / "experiments" / "erqu_pnl.json"
    out.write_text(json.dumps({"result": res, "rows": [{k: v for k, v in r.items() if k != "strats"} | {"S1": r["strats"][names[0]][0]} for r in rows]}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("已写入", out)


if __name__ == "__main__":
    main()
