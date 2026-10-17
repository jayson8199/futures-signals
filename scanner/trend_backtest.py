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
    EXIT_MA=20,           # 离场均线周期（0=不用）
    STOP_MODE="atr",      # atr=吊灯 ATR 止损；lowN=跟踪最近 N 日最低/最高点；two=两段式（进场前 5 日低点→创 20 日新高后切 N 日低点）
    LOW_N=3,
    TIME_STOP=0,          # 0=不用；N 天未创持仓极值则离场
    MAX_SYM=0.15,         # 单品种名义/权益
    MAX_SECTOR=0.45,
    MAX_GROSS=1.5,        # 总名义/权益（杠杆上限）
    COST_SIDE=0.0002,     # 每边 0.02%（手续费约万0.5~1 + 1 跳滑点）
    ENSO_FILTER=False,
    HOLD_DAYS=0,          # >0：持仓满 N 天强制离场（均值回归用）
    OS_Q=0.10,            # 超跌阈值：60 日收益处于自身历史最低分位    # 厄尔尼诺/拉尼娜方向过滤：相位内相关品种只接多头信号
)
# ENSO 传导链（课堂与常识口径）：厄尔尼诺→东南亚/印度干旱：棕榈油、豆油、菜油、白糖、橡胶、棉花偏多；
# 拉尼娜→南美干旱、澳洲多雨：豆粕、菜粕、豆油、焦煤、焦炭偏多
ENSO_LONG_ONLY = {"nino": ["P0", "Y0", "OI0", "SR0", "RU0", "CF0"], "nina": ["M0", "RM0", "Y0", "JM0", "J0"]}


def load_oni():
    f = ROOT / "data" / "oni.csv"
    if not f.exists():
        return {}
    import csv
    phase = {}
    rows = list(csv.DictReader(open(f, encoding="utf-8")))
    # 用上个月的 ONI（当月初才公布上月值），避免偷看
    prev = None
    for r in rows:
        v = float(r["oni"]) if r["oni"] not in ("", "None") else None
        ph = "neutral"
        if prev is not None:
            ph = "nino" if prev >= 0.5 else ("nina" if prev <= -0.5 else "neutral")
        phase[r["month"]] = ph
        prev = v
    return phase


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
    d["ma_exit"] = d["close"].rolling(max(P["EXIT_MA"], 1)).mean()
    n_ = max(P["LOW_N"], 1)
    d["lowN_incl"] = d["low"].rolling(n_).min()
    d["highN_incl"] = d["high"].rolling(n_).max()
    d["lowN_prev"] = d["lowN_incl"].shift()
    d["highN_prev"] = d["highN_incl"].shift()
    d["low5_prev"] = d["low"].rolling(5).min().shift()
    d["high5_prev"] = d["high"].rolling(5).max().shift()
    d["hh20p"] = d["high"].rolling(20).max().shift()
    d["ll20p"] = d["low"].rolling(20).min().shift()
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
    # MACD 八策略：首发信号日，多=+1 空=-1；叠加形态：3 天内有同向 MACD 信号 且 当日同向 高富帅/白富美
    try:
        import macd8
        rows_ = d[["date", "close"]].to_dict("records")
        d["sig_macd"] = 0
        d["macd_sid"] = 0
        idx = {dt: i for i, dt in enumerate(d["date"])}
        for sg in macd8.scan_series("X", "", "", rows_):
            i = idx[sg["date"]]
            v = 1 if sg["direction"] == "多" else -1
            if d.at[i, "sig_macd"] == 0:
                d.at[i, "sig_macd"] = v
                d.at[i, "macd_sid"] = sg["sid"]
        m = d["sig_macd"]
        recent_long = (m.rolling(3).max() == 1)
        recent_short = (m.rolling(3).min() == -1)
        d["sig_macd_pat"] = 0
        d.loc[recent_long & gfs, "sig_macd_pat"] = 1
        d.loc[recent_short & bfm, "sig_macd_pat"] = -1
    except Exception as e:  # noqa
        d["sig_macd"] = 0
        d["sig_macd_pat"] = 0
    # 超跌均值回归：60 日收益 ≤ 自身历史（扩展窗口，至少 250 天）最低 OS_Q 分位 → 做多；只在跨过阈值当天触发一次
    r60 = d["close"].pct_change(60)
    thr = r60.expanding(min_periods=250).quantile(P["OS_Q"]).shift()
    cond = r60 <= thr
    d["sig_oversold"] = 0
    d.loc[cond & ~cond.shift(fill_value=False), "sig_oversold"] = 1
    # 超跌 + 反转确认：处于超跌状态（60 日收益仍 ≤ 阈值，或刚离开阈值 10 天内）期间，首次出现确认信号时进场
    state = (cond | cond.rolling(10, min_periods=1).max().astype(bool))
    bull_engulf = (d["high"] > d["high"].shift()) & (d["low"] < d["low"].shift()) & (d["close"] > d["open"])          # 1包阳线（不看阴阳的包线+收阳）
    brk5 = d["close"] > d["high"].rolling(5).max().shift()                                                          # 收盘突破 5 日高点
    exhaust = (d["chg"] < 0) & (~volup) & (d["oichg"] < 0)                                                           # 跌势将尽：跌·缩量·减仓
    above_ma5 = d["close"] > d["close"].rolling(5).mean()
    macd_div = d["macd_sid"] == 4 if "macd_sid" in d else pd.Series(False, index=d.index)                           # MACD 双绿柱底背离
    ema12 = d["close"].ewm(span=12, adjust=False).mean(); ema26 = d["close"].ewm(span=26, adjust=False).mean()
    dif_ = ema12 - ema26; dea_ = dif_.ewm(span=9, adjust=False).mean(); hist_ = 2 * (dif_ - dea_)
    macd_red = (hist_ > 0) & (hist_.shift() <= 0)              # MACD 翻红（柱由绿变红）
    macd_up = (hist_ > hist_.shift())                           # 柱子走好（比前一天高）
    vol_oi = volup & (d["oichg"] > 0)
    for nm, conf in (("os_full5", vol_oi & brk5 & (hist_ > 0)), ("os_full20", vol_oi & (d["close"] > d["hh20"]) & (hist_ > 0)), ("os_full5_nomacd", vol_oi & brk5), ("os_gfs", gfs), ("os_macdred", macd_red), ("os_gfs_macd", gfs & (hist_ > 0)), ("os_gfs_macdup", gfs & macd_up), ("os_brk5_macd", brk5 & (hist_ > hist_.shift())), ("os_engulf", bull_engulf), ("os_brk5", brk5), ("os_exhaust", exhaust), ("os_ma5", above_ma5 & ~above_ma5.shift(fill_value=False)), ("os_macddiv", macd_div)):
        trig = state & conf
        # 每个超跌区间只进一次：区间 id = cond 从 False→True 的累计计数
        ep = (cond & ~cond.shift(fill_value=False)).cumsum()
        first = trig & ~trig.groupby(ep).cumsum().shift(fill_value=0).astype(bool)
        d[f"sig_{nm}"] = 0
        d.loc[first & (ep > 0), f"sig_{nm}"] = 1
    # 镜像：涨够久（60 日收益 ≥ 自身历史最高 OS_Q 分位）后，首次 增仓+放量+收盘跌破 5 日低 + MACD 绿柱 → 做空
    thr_hi = r60.expanding(min_periods=250).quantile(1 - P["OS_Q"]).shift()
    cond_hi = r60 >= thr_hi
    state_hi = (cond_hi | cond_hi.rolling(10, min_periods=1).max().astype(bool))
    brkdn5 = d["close"] < d["low"].rolling(5).min().shift()
    ep_hi = (cond_hi & ~cond_hi.shift(fill_value=False)).cumsum()
    for nm, conf in (("ob_full5", vol_oi & brkdn5 & (hist_ < 0)), ("ob_raw", pd.Series(True, index=d.index))):
        trig = state_hi & conf
        first = trig & ~trig.groupby(ep_hi).cumsum().shift(fill_value=0).astype(bool)
        d[f"sig_{nm}"] = 0
        d.loc[first & (ep_hi > 0), f"sig_{nm}"] = -1
    d["sig_donchian"] = 0
    d.loc[d["close"] > d["hh20"], "sig_donchian"] = 1
    d.loc[d["close"] < d["ll20"], "sig_donchian"] = -1
    return d


def run(data, signal, start=None, end=None, params=None):
    if params:
        P.update(params)
    ind = {s: indicators(df) for s, df in data.items()}
    if signal in ("os_sector", "os_sector_brk5"):
        # 板块共振：同板块 ≥2 个品种 10 日内同时处于超跌状态
        state = {}
        for s_, d_ in ind.items():
            r60 = d_["close"].pct_change(60)
            thr = r60.expanding(min_periods=250).quantile(P["OS_Q"]).shift()
            st_ = (r60 <= thr)
            state[s_] = pd.Series(st_.rolling(10, min_periods=1).max().astype(bool).values, index=d_["date"].values)
        for s_, d_ in ind.items():
            sec = SECTOR_OF.get(s_, "其他")
            peers = [state[o] for o in state if o != s_ and SECTOR_OF.get(o, "其他") == sec]
            cnt = pd.Series(0, index=d_["date"].values)
            for pser in peers:
                cnt = cnt.add(pser.reindex(cnt.index).fillna(False).astype(int), fill_value=0)
            base = d_["sig_oversold"] if signal == "os_sector" else d_["sig_os_brk5"]
            d_[f"sig_{signal}"] = (base.values * (cnt.values >= 1)).astype(int)
    if signal in ("os_sector", "os_sector_brk5"):
        for s_, d_ in ind.items():
            pass
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
    oni_phase = load_oni() if P["ENSO_FILTER"] else {}
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
                mode = P["STOP_MODE"]
                if mode == "atr":
                    init_stop = o - act * P["ATR_K"] * atr
                elif mode == "lowN":
                    init_stop = float(r["lowN_prev"]) if act == 1 else float(r["highN_prev"])
                else:  # two
                    init_stop = float(r["low5_prev"]) if act == 1 else float(r["high5_prev"])
                if math.isnan(init_stop):
                    continue
                # 结构止损离得太近时，至少留 0.5 ATR，避免仓位算出天文数字
                if act * (o - init_stop) < 0.5 * atr:
                    init_stop = o - act * 0.5 * atr
                stop_dist = act * (o - init_stop) / o
                w = P["RISK_PCT"] / stop_dist
                w = min(w, P["MAX_SYM"])
                sec = SECTOR_OF.get(sym, "其他")
                sec_w = sum(q["w"] for s2, q in pos.items() if SECTOR_OF.get(s2) == sec)
                gross = sum(q["w"] for q in pos.values())
                w = min(w, max(0.0, P["MAX_SECTOR"] - sec_w), max(0.0, P["MAX_GROSS"] - gross))
                if w < 0.005:
                    continue
                pos[sym] = {"sym": sym, "side": act, "w": w, "entry": o, "entry_date": dt, "stop": init_stop,
                            "extreme": o, "bars": 0, "since_ext": 0, "pnl": -w * P["COST_SIDE"], "stage2": mode != "two"}
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
            mode = P["STOP_MODE"]
            if mode == "two" and not p["stage2"]:
                # 第一段：止损固定在进场前低点，直到收盘突破进场前 20 日高点（"颈线"）
                if (p["side"] == 1 and c > float(r["hh20p"])) or (p["side"] == -1 and c < float(r["ll20p"])):
                    p["stage2"] = True
            if mode == "atr":
                new_stop = p["extreme"] - p["side"] * P["ATR_K"] * atr
            elif p["stage2"]:
                new_stop = float(r["lowN_incl"]) if p["side"] == 1 else float(r["highN_incl"])
            else:
                new_stop = p["stop"]
            p["stop"] = max(p["stop"], new_stop) if p["side"] == 1 else min(p["stop"], new_stop)
            ma = float(r["ma_exit"])
            ma_exit = P["EXIT_MA"] > 0 and ((p["side"] == 1 and c < ma) or (p["side"] == -1 and c > ma))
            if ma_exit or (P["TIME_STOP"] and p["since_ext"] >= P["TIME_STOP"]) or (P["HOLD_DAYS"] and p["bars"] >= P["HOLD_DAYS"]):
                pending[sym] = "exit"
        # 3) 收盘：新信号 → 次日开盘进场
        for sym, d in rows.items():
            if dt not in d.index or sym in pos or sym in pending:
                continue
            s = int(d.loc[dt][sig_col]) if not math.isnan(d.loc[dt][sig_col]) else 0
            if s and P["ENSO_FILTER"]:
                ph = oni_phase.get(dt[:7], "neutral")
                if ph != "neutral" and sym in ENSO_LONG_ONLY[ph] and s == -1:
                    s = 0
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
    ap.add_argument("--stop-mode", default="atr")
    ap.add_argument("--enso", action="store_true")
    ap.add_argument("--hold-days", type=int, default=0)
    ap.add_argument("--os-q", type=float, default=0.10)
    ap.add_argument("--symbols", help="只回测这些品种，逗号分隔")
    ap.add_argument("--low-n", type=int, default=3)
    ap.add_argument("--atr-k", type=float, default=2.0)
    ap.add_argument("--out", default="experiments/trend_result.json")
    args = ap.parse_args()
    data = load(ROOT / args.data)
    if args.symbols:
        keep = set(args.symbols.split(","))
        data = {k: v for k, v in data.items() if k in keep}
    print(f"载入 {len(data)} 个品种")
    sigs = ["pattern", "best", "donchian", "macd", "macd_pat"] if args.signal == "all" else args.signal.split(",")
    res = {}
    for s in sigs:
        r = run(data, s, args.start, args.end, {"TIME_STOP": args.time_stop, "ENTRY_N": args.entry_n, "MA_N": args.ma_n, "ATR_K": args.atr_k, "EXIT_MA": args.exit_ma, "STOP_MODE": args.stop_mode, "LOW_N": args.low_n, "ENSO_FILTER": args.enso, "HOLD_DAYS": args.hold_days, "OS_Q": args.os_q})
        res[s] = r
        print(f"[{s}] {r['span'][0]}~{r['span'][1]} 年化 {r['cagr_pct']}% 波动 {r['ann_vol_pct']}% 夏普 {r['sharpe']} 最大回撤 {r['max_dd_pct']}%（{r['max_dd_span'][0]}~{r['max_dd_span'][1]}）"
              f" 水下最长 {r['longest_underwater_days']} 天 | {r['trades']} 笔 胜率 {r['win_rate']}% 盈亏比 {r['payoff']} 均持 {r['avg_hold_days']} 天 连亏 {r['longest_losing_streak']} | 分年 {r['by_year']}")
    (ROOT / args.out).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print("已写入", args.out)


if __name__ == "__main__":
    main()
