#!/usr/bin/env python3
"""
趋势跟踪组合回测（54 品种主力连续日线）

信号（多空对称）：
  pattern  八种形态：高富帅(涨·放量·增仓) 做多 / 白富美(跌·放量·增仓) 做空，且价格在 20 日线正确一侧
  best     优选：高富帅中 0<涨幅≤2% 且 2%≤增仓≤5%（空头镜像：白富美中 -2%≤跌幅<0 且增仓 2~5%）
  donchian 经典 20 日突破（基准）：收盘创 20 日新高做多 / 新低做空
离场：
  2×ATR(14) 吊灯跟踪止损（盘中触发按止损价成交）
  或 收盘反向穿越 20 日线（次日开盘离场）
  可选 时间止损：N 天未创持仓新高/新低则离场
仓位：按波动率反向配，每笔风险 = 账户 RISK_PCT，单品种名义上限、板块上限、总名义上限
成本：手续费+滑点按名义 COST_SIDE 每边
用法：python scanner/trend_backtest.py [--data data/long] [--signal pattern|best|donchian|all] [--start 2018-01-01]
"""
import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scanner"))
from scan import SYMBOLS  # noqa: E402

SECTORS = {
    "黑色": ["RB0", "HC0", "SS0", "I0", "J0", "JM0", "SF0", "SM0"],
    "有色": ["CU0", "AL0", "ZN0", "PB0", "NI0", "SN0", "AO0", "BC0"],
    "贵金属": ["AU0", "AG0"],
    "能源": ["SC0", "FU0", "BU0", "LU0", "PG0"],
    "化工": ["EB0", "EG0", "TA0", "PF0", "MA0", "UR0", "SA0", "FG0", "L0", "V0", "PP0", "RU0", "NR0", "SP0"],
    "油脂油料": ["A0", "B0", "M0", "Y0", "P0", "OI0", "RM0"],
    "农产品": ["C0", "CS0", "JD0", "LH0", "AP0", "CF0", "SR0", "CJ0", "PK0"],
    "新能源": ["SI0", "LC0"],
    "股指": ["IF0", "IH0", "IC0", "IM0"],
    "航运": ["EC0"],
}
SECTORS["化工"] += ["PX0", "SH0"]
SECTOR_OF = {s: k for k, v in SECTORS.items() for s in v}

P = dict(
    RISK_PCT=0.005,      # 每笔风险占账户
    ATR_N=14, ATR_K=2.0,  # 吊灯止损
    MA_N=20,
    ENTRY_N=20,           # 突破周期（donchian）
    EXIT_MA=20,           # 离场均线周期
    TIME_STOP=0,          # 0=不用；N 天未创持仓极值则离场
    MAX_SYM=0.15,         # 单品种名义/权益
    MAX_SECTOR=0.45,
    MAX_GROSS=1.5,        # 总名义/权益（杠杆上限）
    COST_SIDE=0.0002,     # 每边 0.02%（手续费约万0.5~1 + 1 跳滑点）
)


def load(data_dir):
    out = {}
    for sym in SYMBOLS:
        f = Path(data_dir) / f"{sym}.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f)
        df = df.rename(columns={"vol": "volume"})
        df["date"] = df["date"].astype(str).str[:10]
        df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date").drop_duplicates("date").reset_index(drop=True)
        if len(df) < 60:
            continue
        out[sym] = df
    return out


def indicators(df):
    d = df.copy()
    d["ma20"] = d["close"].rolling(P["MA_N"]).mean()
    d["ma_exit"] = d["close"].rolling(P["EXIT_MA"]).mean()
    d["vma5"] = d["volume"].rolling(5).mean()
    d["vma20"] = d["volume"].rolling(20).mean()
    d["chg"] = d["close"].pct_change() * 100
    d["oichg"] = d["oi"].pct_change() * 100
    tr = pd.concat([d["high"] - d["low"], (d["high"] - d["close"].shift()).abs(), (d["low"] - d["close"].shift()).abs()], axis=1).max(axis=1)
    d["atr"] = tr.rolling(P["ATR_N"]).mean()
    d["hh20"] = d["close"].rolling(P["ENTRY_N"]).max().shift()
    d["ll20"] = d["close"].rolling(P["ENTRY_N"]).min().shift()
    volup = (d["volume"] > d["vma5"]) & (d["volume"] > d["vma20"])
    gfs = (d["chg"] > 0) & volup & (d["oichg"] > 0)
    bfm = (d["chg"] < 0) & volup & (d["oichg"] > 0)
    d["sig_pattern"] = 0
    d.loc[gfs & (d["close"] > d["ma20"]), "sig_pattern"] = 1
    d.loc[bfm & (d["close"] < d["ma20"]), "sig_pattern"] = -1
    d["sig_best"] = 0
    d.loc[gfs & (d["chg"] <= 2) & (d["oichg"].between(2, 5)), "sig_best"] = 1
    d.loc[bfm & (d["chg"] >= -2) & (d["oichg"].between(2, 5)), "sig_best"] = -1
    d["sig_donchian"] = 0
    d.loc[d["close"] > d["hh20"], "sig_donchian"] = 1
    d.loc[d["close"] < d["ll20"], "sig_donchian"] = -1
    return d


def run(data, signal, start=None, end=None, params=None):
    if params:
        P.update(params)
    ind = {s: indicators(df) for s, df in data.items()}
    dates = sorted(set().union(*[set(d["date"]) for d in ind.values()]))
    if start:
        dates = [x for x in dates if x >= start]
    if end:
        dates = [x for x in dates if x <= end]
    rows = {s: d.set_index("date") for s, d in ind.items()}
    equity = 1.0
    pos = {}      # sym -> dict(side, w, entry, stop, extreme, entry_date, bars, hold_days, since_ext)
    pending = {}  # sym -> side  (次日开盘执行)
    trades, curve = [], []
    sig_col = f"sig_{signal}"
    prev_close = {}
    for dt in dates:
        day_pnl = 0.0
        # 1) 开盘：执行昨日挂单（离场 / 进场）
        for sym, act in list(pending.items()):
            r = rows[sym].loc[dt] if dt in rows[sym].index else None
            if r is None:
                continue
            o = float(r["open"])
            if act == "exit" and sym in pos:
                p = pos.pop(sym)
                ret = p["side"] * (o / prev_close[sym] - 1)
                day_pnl += p["w"] * ret - p["w"] * P["COST_SIDE"]
                trades.append(close_trade(p, dt, o, "ma20"))
            elif act in (1, -1) and sym not in pos:
                atr = float(r["atr"]) if not math.isnan(r["atr"]) else None
                if not atr or atr <= 0:
                    continue
                stop_dist = P["ATR_K"] * atr / o
                w = P["RISK_PCT"] / stop_dist
                w = min(w, P["MAX_SYM"])
                sec = SECTOR_OF.get(sym, "其他")
                sec_w = sum(q["w"] for s2, q in pos.items() if SECTOR_OF.get(s2) == sec)
                gross = sum(q["w"] for q in pos.values())
                w = min(w, max(0.0, P["MAX_SECTOR"] - sec_w), max(0.0, P["MAX_GROSS"] - gross))
                if w < 0.005:
                    continue
                pos[sym] = {"sym": sym, "side": act, "w": w, "entry": o, "entry_date": dt, "stop": o - act * P["ATR_K"] * atr,
                            "extreme": o, "bars": 0, "since_ext": 0, "pnl": -w * P["COST_SIDE"]}
                day_pnl -= w * P["COST_SIDE"]
                prev_close[sym] = o  # 当日从开盘价起算
        pending.clear()
        # 2) 盘中：止损检查；收盘：盯市、更新止损、产生次日指令
        for sym in list(pos.keys()):
            if dt not in rows[sym].index:
                continue
            r = rows[sym].loc[dt]
            p = pos[sym]
            o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            pc = prev_close.get(sym, o)
            hit = (p["side"] == 1 and l <= p["stop"]) or (p["side"] == -1 and h >= p["stop"])
            if hit:
                px = p["stop"] if (p["side"] == 1 and o > p["stop"]) or (p["side"] == -1 and o < p["stop"]) else o  # 跳空直接按开盘
                ret = p["side"] * (px / pc - 1)
                pnl = p["w"] * ret - p["w"] * P["COST_SIDE"]
                day_pnl += pnl
                p["pnl"] += pnl
                trades.append(close_trade(p, dt, px, "stop"))
                pos.pop(sym)
                continue
            ret = p["side"] * (c / pc - 1)
            day_pnl += p["w"] * ret
            p["pnl"] += p["w"] * ret
            p["bars"] += 1
            if (p["side"] == 1 and c > p["extreme"]) or (p["side"] == -1 and c < p["extreme"]):
                p["extreme"], p["since_ext"] = c, 0
            else:
                p["since_ext"] += 1
            atr = float(r["atr"])
            new_stop = p["extreme"] - p["side"] * P["ATR_K"] * atr
            p["stop"] = max(p["stop"], new_stop) if p["side"] == 1 else min(p["stop"], new_stop)
            ma = float(r["ma_exit"])
            if (p["side"] == 1 and c < ma) or (p["side"] == -1 and c > ma) or (P["TIME_STOP"] and p["since_ext"] >= P["TIME_STOP"]):
                pending[sym] = "exit"
        # 3) 收盘：新信号 → 次日开盘进场
        for sym, d in rows.items():
            if dt not in d.index or sym in pos or sym in pending:
                continue
            s = int(d.loc[dt][sig_col]) if not math.isnan(d.loc[dt][sig_col]) else 0
            if s:
                pending[sym] = s
        for sym, d in rows.items():
            if dt in d.index:
                prev_close[sym] = float(d.loc[dt]["close"])
        equity *= (1 + day_pnl)
        curve.append((dt, round(equity, 6), round(day_pnl, 6), len(pos), round(sum(q["w"] for q in pos.values()), 3)))
    # 强平未平仓（仅用于统计）
    for sym, p in pos.items():
        trades.append(close_trade(p, dates[-1], prev_close[sym], "open"))
    return summarize(curve, trades, signal)


def close_trade(p, dt, px, why):
    return {"sym": p["sym"], "name": SYMBOLS[p["sym"]][0], "side": "多" if p["side"] == 1 else "空", "entry_date": p["entry_date"], "exit_date": dt,
            "entry": round(p["entry"], 2), "exit": round(px, 2), "ret_pct": round(p["side"] * (px / p["entry"] - 1) * 100, 2),
            "pnl_pct": round(p["pnl"] * 100, 3), "w": round(p["w"], 3), "bars": p["bars"], "why": why, "sector": SECTOR_OF.get(p["sym"], "其他")}


def summarize(curve, trades, signal):
    eq = [c[1] for c in curve]
    rets = [c[2] for c in curve]
    n = len(eq)
    years = n / 242
    cagr = (eq[-1] ** (1 / years) - 1) * 100 if years > 0 else 0
    mean = sum(rets) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / (n - 1))
    sharpe = mean / sd * math.sqrt(242) if sd else 0
    peak, mdd, dd_start, mdd_span, uw, max_uw = eq[0], 0, 0, ("", ""), 0, 0
    for i, v in enumerate(eq):
        if v >= peak:
            peak, dd_start, uw = v, i, 0
        else:
            uw += 1
            max_uw = max(max_uw, uw)
        dd = v / peak - 1
        if dd < mdd:
            mdd, mdd_span = dd, (curve[dd_start][0], curve[i][0])
    closed = [t for t in trades if t["why"] != "open"]
    wins = [t for t in closed if t["pnl_pct"] > 0]
    losses = [t for t in closed if t["pnl_pct"] <= 0]
    streak = cur = 0
    for t in closed:
        cur = cur + 1 if t["pnl_pct"] <= 0 else 0
        streak = max(streak, cur)
    by_year = {}
    last = {}
    for dt, v, *_ in curve:
        y = dt[:4]
        by_year.setdefault(y, {"start": v})
        by_year[y]["end"] = v
    first_eq = eq[0]
    prev_end = first_eq
    for y in sorted(by_year):
        by_year[y] = round((by_year[y]["end"] / prev_end - 1) * 100, 2)
        prev_end = [c[1] for c in curve if c[0][:4] == y][-1]
    by_sym, by_sec = defaultdict(lambda: {"n": 0, "pnl": 0.0, "wins": 0}), defaultdict(lambda: {"n": 0, "pnl": 0.0, "wins": 0})
    for t in closed:
        for key, bucket in ((t["sym"], by_sym), (t["sector"], by_sec)):
            bucket[key]["n"] += 1
            bucket[key]["pnl"] = round(bucket[key]["pnl"] + t["pnl_pct"], 3)
            bucket[key]["wins"] += 1 if t["pnl_pct"] > 0 else 0
    return {
        "signal": signal, "params": dict(P), "span": [curve[0][0], curve[-1][0]], "days": n,
        "final_equity": round(eq[-1], 4), "total_ret_pct": round((eq[-1] - 1) * 100, 2), "cagr_pct": round(cagr, 2),
        "ann_vol_pct": round(sd * math.sqrt(242) * 100, 2), "sharpe": round(sharpe, 2), "max_dd_pct": round(mdd * 100, 2), "max_dd_span": mdd_span,
        "longest_underwater_days": max_uw,
        "trades": len(closed), "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "avg_win_pct": round(sum(t["pnl_pct"] for t in wins) / len(wins), 3) if wins else 0,
        "avg_loss_pct": round(sum(t["pnl_pct"] for t in losses) / len(losses), 3) if losses else 0,
        "payoff": round(abs(sum(t["pnl_pct"] for t in wins) / len(wins)) / abs(sum(t["pnl_pct"] for t in losses) / len(losses)), 2) if wins and losses else None,
        "avg_hold_days": round(sum(t["bars"] for t in closed) / len(closed), 1) if closed else 0,
        "longest_losing_streak": streak,
        "exit_reasons": {k: sum(1 for t in closed if t["why"] == k) for k in ("stop", "ma20", "time")},
        "by_year": by_year, "by_sector": dict(by_sec), "by_symbol": {k: {**v, "name": SYMBOLS[k][0]} for k, v in by_sym.items()},
        "curve": [(c[0], c[1], c[3], c[4]) for c in curve], "trades_list": trades,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/long")
    ap.add_argument("--signal", default="all")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--time-stop", type=int, default=0)
    ap.add_argument("--entry-n", type=int, default=20)
    ap.add_argument("--ma-n", type=int, default=20)
    ap.add_argument("--exit-ma", type=int, default=20)
    ap.add_argument("--atr-k", type=float, default=2.0)
    ap.add_argument("--out", default="experiments/trend_result.json")
    args = ap.parse_args()
    data = load(ROOT / args.data)
    print(f"载入 {len(data)} 个品种")
    sigs = ["pattern", "best", "donchian"] if args.signal == "all" else [args.signal]
    res = {}
    for s in sigs:
        r = run(data, s, args.start, args.end, {"TIME_STOP": args.time_stop, "ENTRY_N": args.entry_n, "MA_N": args.ma_n, "ATR_K": args.atr_k, "EXIT_MA": args.exit_ma})
        res[s] = r
        print(f"[{s}] {r['span'][0]}~{r['span'][1]} 年化 {r['cagr_pct']}% 波动 {r['ann_vol_pct']}% 夏普 {r['sharpe']} 最大回撤 {r['max_dd_pct']}%（{r['max_dd_span'][0]}~{r['max_dd_span'][1]}）"
              f" 水下最长 {r['longest_underwater_days']} 天 | {r['trades']} 笔 胜率 {r['win_rate']}% 盈亏比 {r['payoff']} 均持 {r['avg_hold_days']} 天 连亏 {r['longest_losing_streak']} | 分年 {r['by_year']}")
    (ROOT / args.out).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print("已写入", args.out)


if __name__ == "__main__":
    main()
