#!/usr/bin/env python3
"""
上证指数日历统计：星期效应（周一/周五涨跌）与季末效应
口径：
  涨跌 = 当日收盘 vs 前一交易日收盘（涨跌幅）；另附"收阴/收阳"（收盘 vs 当日开盘）
  星期几按自然星期；节假日休市的那天不计
  季末日 = 每季度最后一个交易日；另看季末最后 5 个交易日累计、下季第 1 个交易日
数据：akshare stock_zh_index_daily("sh000001")（新浪，全历史），保存 data/index/sh000001.csv
用法：python scanner/calendar_stats.py [--fetch]   → experiments/calendar_stats.json
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "index" / "sh000001.csv"
WD = ["周一", "周二", "周三", "周四", "周五"]


def fetch():
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol="sh000001")
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    CSV.parent.mkdir(parents=True, exist_ok=True)
    df[["date", "open", "high", "low", "close", "volume"]].to_csv(CSV, index=False)
    print(f"上证指数 {len(df)} 行 {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")


def load():
    d = pd.read_csv(CSV)
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").reset_index(drop=True)
    d["chg"] = d["close"].pct_change() * 100
    d["body"] = (d["close"] - d["open"]) / d["open"] * 100
    d["wd"] = d["date"].dt.weekday
    d["q"] = d["date"].dt.to_period("Q")
    return d.dropna(subset=["chg"])


def wd_stats(x):
    n = len(x)
    if not n:
        return None
    return {"天数": n, "跌": int((x["chg"] < 0).sum()), "涨": int((x["chg"] > 0).sum()), "平": int((x["chg"] == 0).sum()),
            "下跌占比": round(float((x["chg"] < 0).mean() * 100), 1), "平均涨跌幅": round(float(x["chg"].mean()), 3),
            "收阴天数": int((x["body"] < 0).sum())}


def quarter_end(d):
    rows = []
    for q, g in d.groupby("q"):
        if g["date"].iloc[-1] < q.end_time.normalize() - pd.Timedelta(days=7):
            continue  # 本季度还没结束
        last = g.iloc[-1]
        last5 = float((1 + g["chg"].iloc[-5:] / 100).prod() - 1) * 100
        nxt = d[d["q"] == q + 1]
        rows.append({"季度": str(q), "季末日": last["date"].strftime("%Y-%m-%d"), "季末日涨跌幅": round(float(last["chg"]), 2),
                     "季末5日累计": round(last5, 2), "下季首日涨跌幅": round(float(nxt["chg"].iloc[0]), 2) if len(nxt) else None,
                     "整季涨跌幅": round(float((1 + g["chg"] / 100).prod() - 1) * 100, 2)})
    return pd.DataFrame(rows)


def q_summary(qe):
    def s(col):
        x = qe[col].dropna()
        return {"次数": int(len(x)), "跌": int((x < 0).sum()), "涨": int((x > 0).sum()), "下跌占比": round(float((x < 0).mean() * 100), 1) if len(x) else None,
                "平均": round(float(x.mean()), 2) if len(x) else None}
    out = {"季末日": s("季末日涨跌幅"), "季末5日": s("季末5日累计"), "下季首日": s("下季首日涨跌幅")}
    for k in (1, 2, 3, 4):
        sub = qe[qe["季度"].str.endswith(f"Q{k}")]
        out[f"Q{k}季末日"] = {"次数": int(len(sub)), "跌": int((sub["季末日涨跌幅"] < 0).sum()), "平均": round(float(sub["季末日涨跌幅"].mean()), 2) if len(sub) else None}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    args = ap.parse_args()
    if args.fetch:
        fetch()
    d = load()
    res = {"数据截止": d["date"].iloc[-1].strftime("%Y-%m-%d")}
    y26 = d[d["date"].dt.year == 2026]
    res["2026_星期"] = {WD[k]: wd_stats(y26[y26["wd"] == k]) for k in range(5)}
    res["2026_全部交易日"] = wd_stats(y26)
    res["2026_周一明细"] = [{"日期": r.date.strftime("%m-%d"), "涨跌幅": round(r.chg, 2)} for r in y26[y26["wd"] == 0].itertuples()]
    res["2026_周五明细"] = [{"日期": r.date.strftime("%m-%d"), "涨跌幅": round(r.chg, 2)} for r in y26[y26["wd"] == 4].itertuples()]
    # 历史对照：近 10 年、2005 年以来，看 2026 是否特殊
    for label, start in (("近10年_2016起", "2016-01-01"), ("2005起", "2005-01-01")):
        h = d[(d["date"] >= start) & (d["date"].dt.year < 2026)]
        res[f"{label}_星期"] = {WD[k]: wd_stats(h[h["wd"] == k]) for k in range(5)}
        res[f"{label}_全部"] = wd_stats(h)
        # 每年周一、周五下跌占比，看是否稳定
        yy = {}
        for y, g in h.groupby(h["date"].dt.year):
            yy[int(y)] = {"周一跌%": round(float((g[g['wd'] == 0]['chg'] < 0).mean() * 100), 0), "周五跌%": round(float((g[g['wd'] == 4]['chg'] < 0).mean() * 100), 0)}
        res[f"{label}_逐年"] = yy
    qe = quarter_end(d)
    res["2026_季末"] = qe[qe["季度"].str.startswith("2026")].to_dict("records")
    for label, start in (("近10年_2016起", "2016"), ("2005起", "2005")):
        sub = qe[(qe["季度"] >= start) & (~qe["季度"].str.startswith("2026"))]
        res[f"{label}_季末汇总"] = q_summary(sub)
    res["季末明细_2016起"] = qe[qe["季度"] >= "2016"].to_dict("records")
    out = ROOT / "experiments" / "calendar_stats.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if "明细" not in k and "逐年" not in k}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
