#!/usr/bin/env python3
"""
历史战绩统计 & 形态连续天数
数据源：data/history/<SYM>.csv 长期日线库（优先），再合并各日 data.json 的 hist/当日行作为补充。
用与 scan.py 完全相同的规则回算每一天的八种形态，再用之后 1/3/5 个交易日的收盘价算实际涨跌。
MACD 八策略的历史信号与前向收益由 macd8.scan_all 给出，这里只做汇总。
"""
from collections import defaultdict

import history as history_mod
import macd8
from scan import classify_pattern, SYMBOLS

PATTERNS = ["高富帅", "白富美", "上涨乏力", "下跌乏力", "虚涨分歧", "虚跌分歧", "涨势将尽", "跌势将尽"]
EXPECT = {"高富帅": 1, "白富美": -1, "涨势将尽": -1, "跌势将尽": 1}
HORIZONS = (1, 3, 5)


def merge_history(datas):
    """sym -> [(date, close, vol, oi), ...] 升序去重；CSV 库为主，data.json 补充"""
    by_sym = defaultdict(dict)
    for sym, rows in history_mod.load_all().items():
        for r in rows:
            by_sym[sym][r["date"]] = (r["date"], r["close"], r["volume"], r["oi"])
    for d in datas:
        for it in d["all_results"]:
            sym = it["symbol"]
            for row in it.get("hist") or []:
                if len(row) >= 7:
                    by_sym[sym].setdefault(row[0], (row[0], float(row[4]), int(row[5]), int(row[6])))
                elif len(row) == 4:
                    by_sym[sym].setdefault(row[0], (row[0], float(row[1]), int(row[2]), int(row[3])))
            by_sym[sym].setdefault(it["date"], (it["date"], float(it["today_close"]), int(it["today_vol"]), int(it["today_hold"])))
    return {s: [v for _, v in sorted(rows.items())] for s, rows in by_sym.items()}


def daily_patterns(series):
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


def _agg(vals):
    if not vals:
        return None
    n = len(vals)
    return {"n": n, "up_rate": sum(1 for v in vals if v > 0) / n * 100, "avg": sum(vals) / n, "median": sorted(vals)[n // 2]}


def compute(datas):
    hist = merge_history(datas)
    per_sym = {s: daily_patterns(rows) for s, rows in hist.items()}

    moms = defaultdict(list)
    for recs in per_sym.values():
        for r in recs:
            moms[r["date"]].append(r["mom20"])
    weak_day = {}
    for d, ms in moms.items():
        if len(ms) >= 30:
            ms.sort()
            weak_day[d] = ms[len(ms) // 2] < 0

    signals = []
    for s, recs in per_sym.items():
        ser = hist[s]
        for r in recs:
            i = r["idx"]
            fwd = {k: (ser[i + k][1] / r["close"] - 1) * 100 for k in HORIZONS if i + k < len(ser)}
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

    groups = defaultdict(list)
    for sg in signals:
        groups[sg["pattern"]].append(sg)
        if sg["pattern"] == "高富帅" and sg["tag"]:
            for t in sg["tag"].split("+"):
                groups[f"高富帅·{t}"].append(sg)
    table = {}
    for g, items in groups.items():
        base = g.split("·")[0]
        row = {"n_signals": len(items), "expect": EXPECT.get(base, 0)}
        for k in HORIZONS:
            a = _agg([x["fwd"][k] for x in items if k in x["fwd"]])
            if a and row["expect"]:
                a["win_rate"] = a["up_rate"] if row["expect"] > 0 else 100 - a["up_rate"]
            row[k] = a
        table[g] = row

    # 形态连续天数
    streaks = {}
    for s, recs in per_sym.items():
        if recs:
            last = recs[-1]["pattern"]
            n = 0
            for r in reversed(recs):
                if r["pattern"] == last:
                    n += 1
                else:
                    break
            streaks[s] = (recs[-1]["date"], last, n)

    # MACD 八策略：fwd 已按方向调整（正=方向正确）
    H = {s: [{"date": d, "close": c} for d, c, _, _ in rows] for s, rows in hist.items()}
    macd_sigs = macd8.scan_all(H, SYMBOLS)
    macd_table = {}
    by = defaultdict(list)
    for sg in macd_sigs:
        by[sg["strategy"]].append(sg)
        by["多头合计" if sg["direction"] == "多" else "空头合计"].append(sg)
    for g, items in by.items():
        row = {"n_signals": len(items)}
        for k in HORIZONS:
            a = _agg([x["fwd"][k] for x in items if k in x["fwd"]])
            if a:
                a["win_rate"] = a["up_rate"]
            row[k] = a
        macd_table[g] = row
    macd_by_date = defaultdict(list)
    for sg in macd_sigs:
        macd_by_date[sg["date"]].append(sg)

    dates = sorted({r["date"] for recs in per_sym.values() for r in recs})
    return {"signals": signals, "table": table, "streaks": streaks,
            "macd_signals": macd_sigs, "macd_table": macd_table, "macd_by_date": macd_by_date,
            "span": (dates[0], dates[-1]) if dates else None, "n_days": len(dates)}
