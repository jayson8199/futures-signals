#!/usr/bin/env python3
"""
实验：周四开盘做空、周五收盘平仓（股指期货 + 股指期权买认沽），2026 年
期货：IF/IH/IC/IM 主力连续（data/long + data/history，新浪），周四开盘价开空、周五收盘价平仓
      隔夜持仓，平仓按"平昨"计费；成本 = 开仓万0.23 + 平昨万0.23 + 每边 1 跳滑点
      主力换月若恰好落在周四→周五之间会产生假跳空：用对应现货指数同期涨跌比对，偏差>1% 的周标出并改用指数涨跌
期权：没有 2026 年逐合约历史价格，用 Black-Scholes 估算——
      周四开盘买入平值认沽（当月合约；若本周就是到期周则用次月），周五收盘卖出
      隐含波动率取周三收盘前 20 日已实现波动率 × 1.1（期权隐波通常略高于已实现），持有期间不变
      成本 = 每边 1 跳 + 手续费 15 元/手
      这是模型估算，真实盈亏还取决于当天隐波的实际变化
用法：python scanner/thu_short.py [--year 2026]
"""
import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FUT = {  # 代码: (名称, 合约乘数, 最小变动, 对应指数, 期权代码, 期权乘数, 行权价间距, 期权最小变动)
    "IF0": ("沪深300", 300, 0.2, "sh000300", "IO", 100, 50, 0.2),
    "IH0": ("上证50", 300, 0.2, "sh000016", "HO", 100, 25, 0.2),
    "IC0": ("中证500", 200, 0.2, "sh000905", None, None, None, None),
    "IM0": ("中证1000", 200, 0.2, "sh000852", "MO", 100, 50, 0.2),
}
FEE = 0.000023
R = 0.015


def load_fut(sym):
    parts = [pd.read_csv(ROOT / "data" / d / f"{sym}.csv") for d in ("long", "history") if (ROOT / "data" / d / f"{sym}.csv").exists()]
    df = pd.concat(parts).drop_duplicates("date", keep="last")
    df["date"] = pd.to_datetime(df["date"].astype(str).str[:10])
    return df.sort_values("date").set_index("date")


def load_idx(code):
    df = pd.read_csv(ROOT / "data" / "index" / f"{code}.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def third_friday(y, m):
    d = date(y, m, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def pick_expiry(fri):
    e = third_friday(fri.year, fri.month)
    if e <= fri + timedelta(days=4):  # 本周就是到期周（或已过），换下月
        y, m = (fri.year + (fri.month == 12), fri.month % 12 + 1)
        e = third_friday(y, m)
    return e


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_put(S, K, T, r, v):
    if T <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + v * v / 2) * T) / (v * math.sqrt(T))
    d2 = d1 - v * math.sqrt(T)
    return K * math.exp(-r * T) * ncdf(-d2) - S * ncdf(-d1)


def run(year):
    out = {}
    for sym, (name, mult, tick, icode, ocode, omult, kstep, otick) in FUT.items():
        f = load_fut(sym)
        ix = load_idx(icode)
        ix["rv20"] = ix["close"].pct_change().rolling(20).std() * math.sqrt(242)
        days = f.index[(f.index.year == year)]
        rows = []
        for t in days:
            if t.weekday() != 3:
                continue
            fri = t + pd.Timedelta(days=1)
            if fri not in f.index or t not in ix.index or fri not in ix.index:
                continue
            o, c = float(f.loc[t, "open"]), float(f.loc[fri, "close"])
            fut_ret = (c / o - 1) * 100
            idx_ret = (float(ix.loc[fri, "close"]) / float(ix.loc[t, "open"]) - 1) * 100
            # 换月识别：周四开盘→周五收盘期间升贴水跳变超过 0.5%（正常日内变化远小于此），改用指数涨跌
            b0 = o / float(ix.loc[t, "open"]) - 1
            b1 = c / float(ix.loc[fri, "close"]) - 1
            roll = abs(b1 - b0) > 0.005
            ret_used = idx_ret if roll else fut_ret
            gross_pts = -(ret_used / 100) * o
            cost_pts = o * FEE * 2 + tick * 2
            pnl_yuan = (gross_pts - cost_pts) * mult
            row = {"周四": t.strftime("%m-%d"), "期货周四开": round(o, 1), "期货周五收": round(c, 1), "指数同期%": round(idx_ret, 2),
                   "做空收益%": round(-ret_used, 2), "每手盈亏元": round(pnl_yuan), "换月修正": roll}
            if ocode:
                S0, S1 = float(ix.loc[t, "open"]), float(ix.loc[fri, "close"])
                prev = ix.index[ix.index < t]
                v = float(ix.loc[prev[-1], "rv20"]) * 1.1 if len(prev) else 0.2
                exp = pick_expiry(fri.date())
                T0 = ((exp - t.date()).days + 0.25) / 365
                T1 = ((exp - fri.date()).days) / 365
                K = round(S0 / kstep) * kstep
                p0, p1 = bs_put(S0, K, T0, R, v), bs_put(S1, K, T1, R, v)
                opt_pnl = ((p1 - otick) - (p0 + otick)) * omult - 30
                row.update({"认沽行权价": K, "隐波%": round(v * 100, 1), "到期日": exp.strftime("%m-%d"), "权利金买入": round(p0, 1), "权利金卖出": round(p1, 1),
                            "期权每手盈亏元": round(opt_pnl), "期权收益占权利金%": round(opt_pnl / (p0 * omult) * 100, 1)})
            rows.append(row)
        df = pd.DataFrame(rows)
        margin = float(f[f.index.year == year]["close"].mean()) * mult * 0.12
        s = {"品种": name, "周数": len(df), "做空赚钱周数": int((df["每手盈亏元"] > 0).sum()), "期货累计每手元": int(df["每手盈亏元"].sum()),
             "期货平均每周%": round(df["做空收益%"].mean(), 3), "期货单周最好元": int(df["每手盈亏元"].max()), "期货单周最差元": int(df["每手盈亏元"].min()),
             "累计盈亏占一手保证金%": round(df["每手盈亏元"].sum() / margin * 100, 1), "换月修正周数": int(df["换月修正"].sum())}
        cum, peak, mdd = 0, 0, 0
        for x in df["每手盈亏元"]:
            cum += x
            peak = max(peak, cum)
            mdd = min(mdd, cum - peak)
        s["期货最大回撤元"] = int(mdd)
        if ocode:
            s.update({"期权赚钱周数": int((df["期权每手盈亏元"] > 0).sum()), "期权累计每手元": int(df["期权每手盈亏元"].sum()),
                      "期权平均权利金元": int((df["权利金买入"] * omult).mean()), "期权平均每周收益占权利金%": round(df["期权收益占权利金%"].mean(), 1),
                      "期权单周最好元": int(df["期权每手盈亏元"].max()), "期权单周最差元": int(df["期权每手盈亏元"].min())})
        out[sym] = {"summary": s, "weeks": rows}
    (ROOT / "experiments" / f"thu_short_{year}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return out




def run_hist(y0=2005, y1=2026):
    """逐年回测：指数口径（周四开盘→周五收盘，代表期货去掉升贴水后的收益），2018 年起另附期货实际价格口径；期权按 BS 估算"""
    res = {}
    for sym, (name, mult, tick, icode, ocode, omult, kstep, otick) in FUT.items():
        ix = load_idx(icode)
        ix["rv20"] = ix["close"].pct_change().rolling(20).std() * math.sqrt(242)
        try:
            f = load_fut(sym)
        except Exception:
            f = None
        per = {}
        for t in ix.index[(ix.index.year >= y0) & (ix.index.year <= y1) & (ix.index.weekday == 3)]:
            fri = t + pd.Timedelta(days=1)
            if fri not in ix.index:
                continue
            S0, S1 = float(ix.loc[t, "open"]), float(ix.loc[fri, "close"])
            if S0 <= 0:
                continue
            r = (S1 / S0 - 1) * 100
            cost_pct = (FEE * 2 + 2 * tick / S0) * 100
            y = t.year
            p = per.setdefault(y, {"周数": 0, "下跌周": 0, "做空%": [], "期货%": [], "期权%": []})
            p["周数"] += 1
            p["下跌周"] += int(r < 0)
            p["做空%"].append(-r - cost_pct)
            if f is not None and t in f.index and fri in f.index:
                o, c = float(f.loc[t, "open"]), float(f.loc[fri, "close"])
                b0, b1 = o / S0 - 1, c / S1 - 1
                fr = r if abs(b1 - b0) > 0.005 else (c / o - 1) * 100
                p["期货%"].append(-fr - cost_pct)
            if ocode:
                prev = ix.index[ix.index < t]
                v = float(ix.loc[prev[-1], "rv20"]) * 1.1 if len(prev) and not math.isnan(ix.loc[prev[-1], "rv20"]) else 0.2
                exp = pick_expiry(fri.date())
                T0, T1 = ((exp - t.date()).days + 0.25) / 365, ((exp - fri.date()).days) / 365
                K = round(S0 / kstep) * kstep
                p0, p1 = bs_put(S0, K, T0, R, v), bs_put(S1, K, T1, R, v)
                if p0 > 0:
                    p["期权%"].append(((p1 - otick) - (p0 + otick) - 30 / omult) / p0 * 100)
        rows = {}
        for y, p in sorted(per.items()):
            s = pd.Series(p["做空%"])
            rows[y] = {"周数": p["周数"], "指数下跌周": p["下跌周"], "下跌占比%": round(p["下跌周"] / p["周数"] * 100, 1),
                       "做空每周平均%": round(s.mean(), 3), "做空全年累计%": round(s.sum(), 2),
                       "期货口径全年累计%": round(sum(p["期货%"]), 2) if p["期货%"] else None,
                       "期权每周平均占权利金%": round(sum(p["期权%"]) / len(p["期权%"]), 1) if p["期权%"] else None,
                       "期权赚钱周占比%": round(sum(1 for x in p["期权%"] if x > 0) / len(p["期权%"]) * 100, 0) if p["期权%"] else None}
        res[sym] = {"name": name, "years": rows}
    (ROOT / "experiments" / "thu_short_hist.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--hist", action="store_true")
    a = ap.parse_args()
    if a.hist:
        res = run_hist()
        for k, v in res.items():
            print("==", v["name"])
            for y, r in v["years"].items():
                print(y, r)
    else:
        res = run(a.year)
        for k, v in res.items():
            print(json.dumps(v["summary"], ensure_ascii=False))


def variants(year=2026):
    """同一年内比较不同做法的投入产出：期货（不同进出场时点）与期权（平值认沽 / 虚值认沽 / 熊市价差），
    期权用 BS 估算并加简单偏斜（虚值认沽每虚值 1% 隐波 +1 个点）"""
    out = []
    for sym, (name, mult, tick, icode, ocode, omult, kstep, otick) in FUT.items():
        f = load_fut(sym)
        ix = load_idx(icode)
        ix["rv20"] = ix["close"].pct_change().rolling(20).std() * math.sqrt(242)
        thu = [t for t in f.index if t.year == year and t.weekday() == 3 and (t + pd.Timedelta(days=1)) in f.index and t in ix.index and (t + pd.Timedelta(days=1)) in ix.index]
        def fut_case(label, legs, intraday):
            pnl = []
            for t in thu:
                fri = t + pd.Timedelta(days=1)
                wed = f.index[f.index < t][-1]
                pts = {"wed_c": f.loc[wed, "close"], "thu_o": f.loc[t, "open"], "thu_c": f.loc[t, "close"], "fri_o": f.loc[fri, "open"], "fri_c": f.loc[fri, "close"]}
                i_pts = {"wed_c": ix.loc[ix.index[ix.index < t][-1], "close"], "thu_o": ix.loc[t, "open"], "thu_c": ix.loc[t, "close"], "fri_o": ix.loc[fri, "open"], "fri_c": ix.loc[fri, "close"]}
                a, b = legs
                fa, fb = float(pts[a]), float(pts[b])
                ia, ib = float(i_pts[a]), float(i_pts[b])
                if abs((fb / ib) - (fa / ia)) > 0.005:  # 换月
                    move = (ib / ia - 1) * fa
                else:
                    move = fb - fa
                fee = fa * (FEE + (0.000345 if intraday else FEE))
                pnl.append((-move - fee - 2 * tick) * mult)
            cap = float(f[f.index.year == year]["close"].mean()) * mult * 0.12
            out.append(stat(name, "期货", label, pnl, cap, "一手保证金(12%)"))
        fut_case("周四开盘→周五收盘（隔夜）", ("thu_o", "fri_c"), False)
        fut_case("周三收盘→周五收盘（提前一天）", ("wed_c", "fri_c"), False)
        fut_case("周四开盘→周四收盘（只做日内）", ("thu_o", "thu_c"), True)
        fut_case("周四收盘→周五收盘（只拿隔夜+周五）", ("thu_c", "fri_c"), False)
        if not ocode:
            continue
        def opt_case(label, otm_buy, otm_sell):
            pnl, caps = [], []
            for t in thu:
                fri = t + pd.Timedelta(days=1)
                S0, S1 = float(ix.loc[t, "open"]), float(ix.loc[fri, "close"])
                prev = ix.index[ix.index < t]
                v = float(ix.loc[prev[-1], "rv20"]) * 1.1
                exp = pick_expiry(fri.date())
                T0, T1 = ((exp - t.date()).days + 0.25) / 365, ((exp - fri.date()).days) / 365
                def leg(otm):
                    K = round(S0 * (1 - otm) / kstep) * kstep
                    vv = v + max(0.0, (S0 - K) / S0) * 1.0  # 偏斜：每虚值 1% 加 1 个波动率点
                    return bs_put(S0, K, T0, R, vv), bs_put(S1, K, T1, R, vv)
                b0, b1 = leg(otm_buy)
                net0, net1 = b0, b1
                fees = 15
                if otm_sell is not None:
                    s0, s1 = leg(otm_sell)
                    net0, net1 = b0 - s0, b1 - s1
                    fees = 30
                ticks = 2 * otick * (2 if otm_sell is not None else 1)
                pnl.append((net1 - net0 - ticks) * omult - fees * 2)
                caps.append(net0 * omult)
            out.append(stat(name, "期权", label, pnl, sum(caps) / len(caps), "平均权利金（最大亏损）"))
        opt_case("买平值认沽", 0.0, None)
        opt_case("买虚值 2% 认沽", 0.02, None)
        opt_case("熊市价差：买平值、卖虚值 3% 认沽", 0.0, 0.03)
    (ROOT / "experiments" / f"thu_short_variants_{year}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def stat(name, kind, label, pnl, cap, cap_name):
    s = pd.Series(pnl)
    cum = s.cumsum()
    mdd = float((cum - cum.cummax()).min())
    return {"品种": name, "工具": kind, "做法": label, "次数": int(len(s)), "赚钱次数": int((s > 0).sum()), "累计元": int(s.sum()),
            "单次最大亏损元": int(s.min()), "最大回撤元": int(mdd), "投入资金元": int(cap), "投入口径": cap_name,
            "累计/投入": round(float(s.sum() / cap), 2), "累计/最大回撤": round(float(s.sum() / -mdd), 2) if mdd < 0 else None,
            "每次平均/波动": round(float(s.mean() / s.std()), 2) if s.std() else None}
