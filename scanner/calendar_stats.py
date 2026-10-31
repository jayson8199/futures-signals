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


INDICES = {"sh000001": "上证指数", "sh000300": "沪深300", "sh000016": "上证50", "sh000905": "中证500", "sh000852": "中证1000"}


def fetch():
    import akshare as ak
    CSV.parent.mkdir(parents=True, exist_ok=True)
    for code, name in INDICES.items():
        try:
            df = ak.stock_zh_index_daily(symbol=code)
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df[["date", "open", "high", "low", "close", "volume"]].to_csv(CSV.parent / f"{code}.csv", index=False)
            print(f"{name} {len(df)} 行 {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
        except Exception as e:
            print(f"{name} 失败：{e}")


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
    ap.add_argument("--rules", action="store_true", help="只跑规律大比较")
    args = ap.parse_args()
    if args.fetch:
        fetch()
    if args.rules:
        for r in rules_compare():
            print(r)
        return
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


# ---------------- 规律大比较（2026-11-01 加） ----------------
def rules_compare():
    """把各种日历规律放在一起比：每条规律算 上涨/下跌 概率、和同周期基准相比的偏离（z 值）、
    2005–2014 / 2015–2025 / 2026 三段是否方向一致、2005–2025 中有几年方向成立。"""
    import math
    d = pd.read_csv(CSV)
    d["date"] = pd.to_datetime(d["date"])
    d = d[d["date"] >= "2004-06-01"].sort_values("date").reset_index(drop=True)
    d["wd"] = d["date"].dt.weekday
    d["gapdays"] = (d["date"] - d["date"].shift()).dt.days
    d["ym"] = d["date"].dt.to_period("M")
    d["q"] = d["date"].dt.to_period("Q")
    C, O = d["close"].values, d["open"].values
    n = len(d)
    rules = []  # (类别, 名称, 事件列表[(date, ret%)], 基准口径)

    def add(cat, name, idx_pairs, base):
        ev = []
        for a, b, kind in idx_pairs:  # 从 a 的 kind(open/prevclose) 到 b 的收盘
            if a < 1 or b >= n:
                continue
            start = O[a] if kind == "open" else C[a - 1]
            ev.append((d["date"].iloc[b], (C[b] / start - 1) * 100))
        rules.append((cat, name, ev, base))

    WD = ["周一", "周二", "周三", "周四", "周五"]
    for k in range(5):
        idx = d.index[d["wd"] == k]
        add("单日涨跌（收盘 vs 前收）", WD[k], [(i, i, "prev") for i in idx], "1d")
        add("单日阴阳（收盘 vs 当天开盘）", WD[k], [(i, i, "open") for i in idx], "intra")
    # 连续两天：X 开盘 → 次日收盘（两天都是同一周相邻交易日）
    for k in range(4):
        idx = [i for i in d.index[d["wd"] == k] if i + 1 < n and d["wd"].iloc[i + 1] == k + 1 and d["gapdays"].iloc[i + 1] == 1]
        add("两天（前天开盘 → 次日收盘）", f"{WD[k]}开→{WD[k + 1]}收", [(i, i + 1, "open") for i in idx], "2d_open")
    # 整周
    wk = d.groupby(d["date"].dt.to_period("W"))
    add("整周", "周一开盘→周五收盘", [(g.index[0], g.index[-1], "open") for _, g in wk if g["wd"].iloc[0] == 0 and g["wd"].iloc[-1] == 4], "week_open")
    add("整周", "上周五收盘→本周五收盘", [(g.index[0], g.index[-1], "prev") for _, g in wk if g["wd"].iloc[-1] == 4], "week")
    # 月初月末
    mg = list(d.groupby("ym"))
    add("月份位置", "每月第 1 个交易日", [(g.index[0], g.index[0], "prev") for _, g in mg], "1d")
    add("月份位置", "每月前 3 个交易日", [(g.index[0], g.index[min(2, len(g) - 1)], "prev") for _, g in mg], "3d")
    add("月份位置", "每月最后 1 个交易日", [(g.index[-1], g.index[-1], "prev") for _, g in mg], "1d")
    add("月份位置", "每月最后 3 个交易日", [(g.index[-3], g.index[-1], "prev") for _, g in mg if len(g) >= 3], "3d")
    # 季末
    qg = list(d.groupby("q"))
    add("季度", "季末最后 1 个交易日", [(g.index[-1], g.index[-1], "prev") for _, g in qg], "1d")
    add("季度", "季末最后 5 个交易日", [(g.index[-5], g.index[-1], "prev") for _, g in qg if len(g) >= 5], "5d")
    add("季度", "新季度第 1 个交易日", [(g.index[0], g.index[0], "prev") for _, g in qg], "1d")
    # 节假日
    post = d.index[d["gapdays"] >= 5]
    add("节假日", "长假（休市≥5天）后第 1 天", [(i, i, "prev") for i in post], "1d")
    add("节假日", "长假前最后 1 天", [(i - 1, i - 1, "prev") for i in post if i - 1 >= 1], "1d")
    add("节假日", "长假前最后 3 天", [(i - 3, i - 1, "prev") for i in post if i - 3 >= 1], "3d")
    # 自然月（整月）
    for m in range(1, 13):
        add("自然月（整月涨跌）", f"{m} 月", [(g.index[0], g.index[-1], "prev") for p, g in mg if p.month == m], "month")

    # 基准：同长度的任意区间的上涨概率（2005–2025）
    base_p = {}
    r1 = pd.Series(C).pct_change()
    def up_rate(series):
        s = series[(d["date"] >= "2005-01-01") & (d["date"] < "2026-01-01")].dropna()
        return float((s > 0).mean())
    base_p["1d"] = up_rate(r1)
    base_p["intra"] = up_rate(pd.Series(C / O - 1))
    base_p["2d_open"] = up_rate(pd.Series(C) / pd.Series(O).shift(1) - 1)
    base_p["3d"] = up_rate(pd.Series(C).pct_change(3))
    base_p["5d"] = up_rate(pd.Series(C).pct_change(5))
    base_p["week"] = base_p["5d"]
    base_p["week_open"] = up_rate(pd.Series(C) / pd.Series(O).shift(4) - 1)
    base_p["month"] = up_rate(pd.Series(C).pct_change(21))

    out = []
    for cat, name, ev, base in rules:
        e = pd.DataFrame(ev, columns=["date", "ret"])
        def seg(a, b):
            s = e[(e["date"] >= a) & (e["date"] < b)]["ret"]
            return s
        full = seg("2005-01-01", "2026-01-01")
        if len(full) < 10:
            continue
        p_up = float((full > 0).mean())
        p0 = base_p[base]
        z = (p_up - p0) / math.sqrt(p0 * (1 - p0) / len(full))
        direction = "涨" if p_up >= p0 else "跌"
        def rate(s):
            return round(float((s > 0).mean() * 100), 1) if len(s) else None
        a, b, c = seg("2005-01-01", "2015-01-01"), seg("2015-01-01", "2026-01-01"), seg("2026-01-01", "2027-01-01")
        years_ok, years_n = 0, 0
        for y, g in full.groupby(e.loc[full.index, "date"].dt.year):
            if len(g) == 0:
                continue
            years_n += 1
            r = (g > 0).mean()
            years_ok += int((r > p0) if direction == "涨" else (r < p0))
        out.append({"类别": cat, "规律": name, "样本": int(len(full)), "上涨概率": round(p_up * 100, 1), "基准上涨概率": round(p0 * 100, 1),
                    "偏向": direction, "偏离": round((p_up - p0) * 100, 1), "z": round(z, 2), "平均涨跌%": round(float(full.mean()), 3),
                    "2005-14上涨%": rate(a), "2015-25上涨%": rate(b), "2026上涨%": rate(c), "2026样本": int(len(c)),
                    "方向成立年数": f"{years_ok}/{years_n}"})
    out.sort(key=lambda r: -abs(r["z"]))
    (ROOT / "experiments" / "calendar_rules.json").write_text(json.dumps({"rules": out, "base": {k: round(v * 100, 1) for k, v in base_p.items()},
                                                                       "note": "z 为与同周期基准上涨概率之差的二项检验统计量；共比较 %d 条规律，|z|>3 才较可信（多重比较）" % len(out)},
                                                                      ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    main()
