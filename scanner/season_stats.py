#!/usr/bin/env python3
"""
时间维度统计：季节性 与 "跌够久"均值回归（54 品种，data/long）
1) 季节性：按自然月统计收益。训练期 2018-2022 选出每个品种最好/最差的 2 个月，检验期 2023- 看是否仍然成立（样本外）。
2) 跌够久：A) 连续下跌 N 个月后的下个月/3 个月收益；B) 60 日收益处于该品种历史最低 10% 时，之后 20/60 日收益。都与无条件对比。
输出 experiments/season_result.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scanner"))
from scan import SYMBOLS  # noqa: E402


def load():
    out = {}
    for sym in SYMBOLS:
        f = ROOT / "data" / "long" / f"{sym}.csv"
        if f.exists():
            d = pd.read_csv(f)
            d["date"] = pd.to_datetime(d["date"])
            out[sym] = d.set_index("date").sort_index()
    return out


def monthly(d):
    m = d["close"].resample("ME").last()
    return (m.pct_change() * 100).dropna()


def main():
    data = load()
    res = {"seasonality": {}, "season_oos": {}, "down_months": {}, "oversold": {}}
    # ---- 季节性 ----
    train_end = pd.Timestamp("2022-12-31")
    all_m = []
    oos_long, oos_short, oos_all = [], [], []
    per_sym = {}
    for sym, d in data.items():
        r = monthly(d)
        if len(r) < 60:
            continue
        df = pd.DataFrame({"r": r, "m": r.index.month, "y": r.index.year})
        all_m.append(df.assign(sym=sym))
        tr = df[df.index <= train_end].groupby("m")["r"].mean()
        if len(tr) < 12:
            continue
        best = tr.nlargest(2).index.tolist()
        worst = tr.nsmallest(2).index.tolist()
        te = df[df.index > train_end]
        lo = te[te["m"].isin(best)]["r"]
        sh = -te[te["m"].isin(worst)]["r"]
        oos_long += lo.tolist()
        oos_short += sh.tolist()
        oos_all += te["r"].tolist()
        per_sym[sym] = {"name": SYMBOLS[sym][0], "best_months": best, "worst_months": worst,
                        "train_best_avg": round(float(tr.loc[best].mean()), 2), "train_worst_avg": round(float(tr.loc[worst].mean()), 2),
                        "oos_best_avg": round(float(lo.mean()), 2) if len(lo) else None, "oos_worst_avg": round(float(te[te['m'].isin(worst)]['r'].mean()), 2) if len(sh) else None,
                        "oos_n": int(len(lo))}
    big = pd.concat(all_m)
    res["seasonality"]["calendar_avg_all"] = {int(k): round(float(v), 2) for k, v in big.groupby("m")["r"].mean().items()}
    res["seasonality"]["per_symbol"] = per_sym

    def st(x):
        x = np.array(x)
        return {"n": int(len(x)), "avg": round(float(x.mean()), 2), "win": round(float((x > 0).mean() * 100), 1)} if len(x) else None
    res["season_oos"] = {"做多训练期最好2个月": st(oos_long), "做空训练期最差2个月": st(oos_short), "无条件做多(检验期全部月份)": st(oos_all)}

    # ---- 连续下跌 N 个月 ----
    for N in (2, 3, 4, 5):
        nxt1, nxt3, base1 = [], [], []
        for sym, d in data.items():
            r = monthly(d).values
            for i in range(N, len(r) - 3):
                base1.append(r[i])
                if all(r[i - k] < 0 for k in range(1, N + 1)):
                    nxt1.append(r[i])
                    nxt3.append(float(np.prod(1 + r[i:i + 3] / 100) - 1) * 100)
        res["down_months"][f"连跌{N}月"] = {"下月": st(nxt1), "后3月": st(nxt3)}
    res["down_months"]["无条件(任意月)"] = {"下月": st(base1)}

    # ---- 60 日收益处于历史最低 10% ----
    f20, f60, b20, b60 = [], [], [], []
    for sym, d in data.items():
        c = d["close"].values
        if len(c) < 400:
            continue
        r60 = pd.Series(c).pct_change(60)
        for i in range(250, len(c) - 60):
            hist = r60.iloc[60:i]
            b20.append((c[i + 20] / c[i] - 1) * 100)
            b60.append((c[i + 60] / c[i] - 1) * 100)
            if r60.iloc[i] <= hist.quantile(0.1):
                f20.append((c[i + 20] / c[i] - 1) * 100)
                f60.append((c[i + 60] / c[i] - 1) * 100)
    res["oversold"] = {"60日跌幅处于历史最低10%": {"后20日": st(f20), "后60日": st(f60)}, "无条件": {"后20日": st(b20), "后60日": st(b60)}}
    (ROOT / "experiments" / "season_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "seasonality"}, ensure_ascii=False, indent=1))
    print("全品种自然月平均：", res["seasonality"]["calendar_avg_all"])


if __name__ == "__main__":
    main()
