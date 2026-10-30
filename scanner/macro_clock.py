#!/usr/bin/env python3
"""
美林时钟（中国版）：每月判定所处时期，并检验不同通胀口径对商品期货的区分度。

判定（规则在看结果之前定死）：
  增长轴 = 官方制造业 PMI；通胀轴 = PPI 同比 或 CPI 同比（两种口径对比）
  方向：主规则  MA3(t) − MA3(t−3) > 0 为"上行"；敏感性规则  MA3(t) > MA12(t) 为"上行"
  增长↑通胀↓=复苏；增长↑通胀↑=过热；增长↓通胀↑=滞胀；增长↓通胀↓=衰退
检验：
  数据月 t 的 CPI/PPI 最晚 t+1 月 16 日公布（金十历史公布日 8–16 日），PMI 月末公布
  → 第 t 月的判定从 t+1 月 17 日起可用；"错开检验"看 [t+1 月 17 日, t+2 月 17 日) 的收益
  → "同期"看第 t 月本身的收益（不可交易，只用来展示循环论证有多强）
  资产：54 品种中商品部分等权指数、各板块等权、股指（IF 主力连续）
用法：python scanner/macro_clock.py analyze   → experiments/macro_clock_compare.json
      python scanner/macro_clock.py now       → 打印最新判定
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MAC = ROOT / "data" / "macro"
sys.path.insert(0, str(ROOT / "scanner"))

PHASES = ["复苏", "过热", "滞胀", "衰退"]
FIN = {"IF0", "IH0", "IC0", "IM0", "EC0"}
SECT = {
    "黑色": ["RB0", "HC0", "SS0", "I0", "J0", "JM0", "SF0", "SM0"],
    "有色": ["CU0", "AL0", "ZN0", "PB0", "NI0", "SN0", "AO0", "BC0", "SI0", "LC0"],
    "贵金属": ["AU0", "AG0"],
    "能化": ["SC0", "FU0", "BU0", "LU0", "PG0", "EB0", "EG0", "TA0", "PF0", "MA0", "UR0", "SA0", "FG0", "L0", "V0", "PP0", "RU0", "NR0", "SP0", "PX0", "SH0"],
    "农产品": ["A0", "B0", "M0", "Y0", "P0", "OI0", "RM0", "C0", "CS0", "JD0", "LH0", "AP0", "CF0", "SR0", "CJ0", "PK0"],
}


def _month(s):
    return pd.Period(str(s).replace("年", "-").replace("月份", ""), freq="M")


def load_macro():
    pmi = pd.read_csv(MAC / "pmi_em.csv")
    cpi = pd.read_csv(MAC / "cpi_em.csv")
    ppi = pd.read_csv(MAC / "ppi_em.csv")
    m = pd.DataFrame({
        "pmi": pd.Series(pmi["制造业-指数"].values, index=pmi["月份"].map(_month)),
        "cpi": pd.Series(cpi["全国-同比增长"].values, index=cpi["月份"].map(_month)),
        "ppi": pd.Series(ppi["当月同比增长"].values, index=ppi["月份"].map(_month)),
    }).sort_index()
    return m.astype(float)


def direction(x, rule):
    ma3 = x.rolling(3).mean()
    if rule == "ma3_vs_3ago":
        d = ma3 - ma3.shift(3)
    else:  # ma3_vs_ma12
        d = ma3 - x.rolling(12).mean()
    return np.sign(d)


def classify(m, infl, rule):
    g = direction(m["pmi"], rule)
    i = direction(m[infl], rule)
    ph = pd.Series(index=m.index, dtype=object)
    ph[(g > 0) & (i <= 0)] = "复苏"
    ph[(g > 0) & (i > 0)] = "过热"
    ph[(g <= 0) & (i > 0)] = "滞胀"
    ph[(g <= 0) & (i <= 0)] = "衰退"
    ph[g.isna() | i.isna()] = None
    return ph


def load_prices():
    from scan import SYMBOLS
    rets = {}
    for sym in SYMBOLS:
        parts = [pd.read_csv(ROOT / "data" / d / f"{sym}.csv") for d in ("long", "history") if (ROOT / "data" / d / f"{sym}.csv").exists()]
        if not parts:
            continue
        df = pd.concat(parts).drop_duplicates("date", keep="last")
        df["date"] = pd.to_datetime(df["date"].astype(str).str[:10])
        s = df.set_index("date")["close"].sort_index()
        r = s.pct_change()
        r[(r.abs() > 0.15)] = np.nan  # 主力换月跳空等异常，剔除
        rets[sym] = r
    R = pd.DataFrame(rets)
    return R


def window_ret(R, cols, start, end):
    """[start, end) 区间等权组合累计收益（每日等权再连乘）"""
    sub = R.loc[(R.index >= start) & (R.index < end), [c for c in cols if c in R.columns]]
    if sub.empty:
        return np.nan
    daily = sub.mean(axis=1, skipna=True).fillna(0)
    return float((1 + daily).prod() - 1) * 100


def evaluate(m, R, infl, rule):
    ph = classify(m, infl, rule)
    comm = [c for c in R.columns if c not in FIN]
    groups = {"商品等权": comm, **SECT, "股指IF": ["IF0"]}
    rows = []
    first = R.index.min()
    for t, p in ph.items():
        if p is None:
            continue
        # 同期：第 t 月
        s0, e0 = t.start_time, (t + 1).start_time
        # 错开：t+1 月 17 日 → t+2 月 17 日
        s1 = (t + 1).start_time + pd.Timedelta(days=16)
        e1 = (t + 2).start_time + pd.Timedelta(days=16)
        if s0 < first or s1 > R.index.max():
            continue
        row = {"month": str(t), "phase": p}
        for gname, cols in groups.items():
            row[f"{gname}|同期"] = window_ret(R, cols, s0, e0)
            row[f"{gname}|错开"] = window_ret(R, cols, s1, e1) if e1 <= R.index.max() + pd.Timedelta(days=1) else np.nan
        rows.append(row)
    df = pd.DataFrame(rows)
    out = {"n_months": len(df), "span": [df["month"].iloc[0], df["month"].iloc[-1]] if len(df) else None, "by_phase": {}, "spread": {}}
    for mode in ("同期", "错开"):
        for gname in groups:
            col = f"{gname}|{mode}"
            stat = {}
            for p in PHASES:
                x = df.loc[df["phase"] == p, col].dropna()
                stat[p] = {"n": int(len(x)), "avg": round(float(x.mean()), 2) if len(x) else None,
                           "win": round(float((x > 0).mean() * 100), 0) if len(x) else None,
                           "se": round(float(x.std(ddof=1) / math.sqrt(len(x))), 2) if len(x) > 1 else None}
            out["by_phase"][col] = stat
            a, b = df.loc[df["phase"] == "过热", col].dropna(), df.loc[df["phase"] == "衰退", col].dropna()
            if len(a) > 1 and len(b) > 1:
                diff = a.mean() - b.mean()
                se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
                out["spread"][col] = {"过热-衰退": round(float(diff), 2), "t": round(float(diff / se), 2) if se else None}
    out["phase_counts"] = df["phase"].value_counts().to_dict()
    out["months"] = df[["month", "phase", "商品等权|同期", "商品等权|错开", "股指IF|错开"]].round(2).to_dict("records")
    return out


def current(m):
    res = {}
    for infl in ("ppi", "cpi"):
        for rule in ("ma3_vs_3ago", "ma3_vs_ma12"):
            ph = classify(m, infl, rule).dropna()
            res[f"{infl}|{rule}"] = {"month": str(ph.index[-1]), "phase": ph.iloc[-1], "last6": [f"{k}:{v}" for k, v in ph.iloc[-6:].items()]}
    tail = m.iloc[-7:]
    res["latest_values"] = {str(k): {c: (None if pd.isna(v) else round(float(v), 2)) for c, v in r.items()} for k, r in tail.iterrows()}
    return res


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "analyze"
    m = load_macro()
    if cmd == "now":
        print(json.dumps(current(m), ensure_ascii=False, indent=1))
        return
    R = load_prices()
    res = {"note": "错开=按公布日（次月17日起）才可用的真实可交易口径；同期=第t月本身（不可交易，用来看循环论证）", "now": current(m), "results": {}}
    for infl in ("ppi", "cpi"):
        for rule in ("ma3_vs_3ago", "ma3_vs_ma12"):
            res["results"][f"{infl}|{rule}"] = evaluate(m, R, infl, rule)
    (ROOT / "experiments" / "macro_clock_compare.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in res["results"].items():
        print(f"\n=== {k}  {v['n_months']} 个月 {v['span']}  时期分布 {v['phase_counts']}")
        for mode in ("同期", "错开"):
            bp = v["by_phase"][f"商品等权|{mode}"]
            sp = v["spread"].get(f"商品等权|{mode}", {})
            print(f"  商品等权·{mode}: " + "  ".join(f"{p} {bp[p]['avg']:+.2f}%({bp[p]['n']}月,胜{bp[p]['win']:.0f}%)" if bp[p]['avg'] is not None else f"{p} —" for p in PHASES) + f"  | 过热−衰退 {sp.get('过热-衰退')} t={sp.get('t')}")
        bp = v["by_phase"]["股指IF|错开"]
        print("  股指IF·错开:   " + "  ".join(f"{p} {bp[p]['avg']:+.2f}%" if bp[p]['avg'] is not None else f"{p} —" for p in PHASES))
    print("\n当前：", json.dumps(res["now"], ensure_ascii=False)[:900])


if __name__ == "__main__":
    main()
