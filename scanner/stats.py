#!/usr/bin/env python3
"""
历史战绩统计 & 形态连续天数
思路：把所有 data/*.json 里每个品种的 hist（日期/收盘/成交量/持仓）合并成连续日线，
      用与 scan.py 完全相同的规则回算每一天的形态，再用之后 1/3/5 个交易日的收盘价算实际涨跌。
"""
from collections import defaultdict

from scan import classify_pattern, SYMBOLS

PATTERNS = ["高富帅", "白富美", "上涨乏力", "下跌乏力", "虚涨分歧", "虚跌分歧", "涨势将尽", "跌势将尽"]
# 有明确方向预期的形态：+1 预期上涨，-1 预期下跌
EXPECT = {"高富帅": 1, "白富美": -1, "涨势将尽": -1, "跌势将尽": 1}
HORIZONS = (1, 3, 5)


def merge_history(datas):
    """sym -> [(date, close, vol, oi), ...] 按日期升序去重"""
    by_sym = defaultdict(dict)
    for d in datas:
        for it in d["all_results"]:
            sym = it["symbol"]
            for row in it.get("hist") or []:
                by_sym[sym][row[0]] = (row[0], float(row[1]), int(row[2]), int(row[3]))
            # 没有 hist 的旧数据也能贡献当天一行
            by_sym[sym].setdefault(it["date"], (it["date"], float(it["today_close"]), int(it["today_vol"]), int(it["today_hold"])))
    return {s: [v for _, v in sorted(rows.items())] for s, rows in by_sym.items()}


def daily_patterns(series):
    """对一条日线序列逐日回算形态，返回 [{date, pattern, pc, hc, vr, close, idx}]"""
    out = []
    for i in range(20, len(series)):
        d, close, vol, oi = series[i]
        _, pclose, _, poi = series[i - 1]
        vols = [r[2] for r in series[i - 19:i + 1]]
        vol_5ma = int(sum(vols[-5:]) / 5)
        vol_20ma = int(sum(vols) / 20)
        pc = (close - pclose) / pclose * 100 if pclose > 0 else 0.0
        hc = (oi - poi) / poi * 100 if poi > 0 else 0.0
        pat = classify_pattern(pc, vol, vol_5ma, vol_20ma, hc)
        mom20 = (close / series[i - 20][1] - 1) * 100 if series[i - 20][1] > 0 else 0.0
        out.append({"date": d, "pattern": pat, "pc": pc, "hc": hc, "close": close, "idx": i, "mom20": mom20})
    return out


def compute(datas):
    """返回 {signals: [...], table: {...}, streaks: {sym: n}, span: (first,last), n_days}"""
    hist = merge_history(datas)
    per_sym = {s: daily_patterns(rows) for s, rows in hist.items()}
    series_by_sym = hist

    # 每日市场环境（用于抗跌先锋标注）：当日有效品种 mom20 中位数
    moms = defaultdict(list)
    for s, recs in per_sym.items():
        for r in recs:
            moms[r["date"]].append(r["mom20"])
    weak_day = {}
    for d, ms in moms.items():
        if len(ms) >= 30:
            ms.sort()
            weak_day[d] = ms[len(ms) // 2] < 0

    signals = []
    for s, recs in per_sym.items():
        ser = series_by_sym[s]
        for r in recs:
            i = r["idx"]
            fwd = {}
            for k in HORIZONS:
                if i + k < len(ser):
                    fwd[k] = (ser[i + k][1] / r["close"] - 1) * 100
            tag = ""
            if r["pattern"] == "高富帅":
                if r["pc"] > 3:
                    tag = "追高"
                elif 0 < r["pc"] <= 2 and 2 <= r["hc"] <= 5:
                    tag = "优选"
                if weak_day.get(r["date"]):
                    tag = (tag + "+" if tag else "") + "抗跌"
            signals.append({"symbol": s, "name": SYMBOLS.get(s, (s,))[0], "date": r["date"], "pattern": r["pattern"],
                            "tag": tag, "pc": r["pc"], "hc": r["hc"], "fwd": fwd})

    # 汇总表：按形态（含标注细分）× 周期
    groups = defaultdict(list)
    for sg in signals:
        groups[sg["pattern"]].append(sg)
        if sg["pattern"] == "高富帅" and sg["tag"]:
            for t in sg["tag"].split("+"):
                groups[f"高富帅·{t}"].append(sg)

    def agg(items, k):
        vals = [x["fwd"][k] for x in items if k in x["fwd"]]
        if not vals:
            return None
        n = len(vals)
        up = sum(1 for v in vals if v > 0)
        return {"n": n, "up_rate": up / n * 100, "avg": sum(vals) / n,
                "median": sorted(vals)[n // 2]}

    table = {}
    for g, items in groups.items():
        base = g.split("·")[0]
        row = {"n_signals": len(items), "expect": EXPECT.get(base, 0)}
        for k in HORIZONS:
            a = agg(items, k)
            if a and row["expect"]:
                a["win_rate"] = a["up_rate"] if row["expect"] > 0 else 100 - a["up_rate"]
            row[k] = a
        table[g] = row

    # 连续天数：最新日期起向前数同形态
    streaks = {}
    for s, recs in per_sym.items():
        if not recs:
            continue
        last = recs[-1]["pattern"]
        n = 0
        for r in reversed(recs):
            if r["pattern"] == last:
                n += 1
            else:
                break
        streaks[s] = (recs[-1]["date"], last, n)

    dates = sorted({r["date"] for recs in per_sym.values() for r in recs})
    return {"signals": signals, "table": table, "streaks": streaks,
            "span": (dates[0], dates[-1]) if dates else None, "n_days": len(dates)}
