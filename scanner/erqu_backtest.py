#!/usr/bin/env python3
"""
「二区定律」独立回测（上证指数 5 分钟数据，经 akshare/东方财富）
时段分区：一区 9:30-10:00，二区 10:00-10:30，三区 10:30-11:00，四区 11:00-11:30，五区 13:00-13:30
判定：
  好二区 = 二区后半段(10:15-10:30)的高点和低点都高于前半段(10:00-10:15)（低点抬高、高点抬高，V/W 底形态）
  坏二区 = 后半段高点和低点都低于前半段
  其余 = 模糊（用备用口径：10:30 收 vs 10:00 开 的方向）
预测：好二区 → 今天收盘 ≥ 开盘（"不会跌"）；坏二区 → 收盘 ≤ 开盘（"不会涨"）
五区修正：好二区但五区创 9:30-13:30 新低 → 改判坏；坏二区但五区创新高 → 改判好
基线：A) 永远预测"收盘与 10:30 相对开盘同向"  B) 抛硬币 50%
用法：python scanner/erqu_backtest.py [--start 20240101] [--end 20241231] [--csv path(离线)]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def fetch(start, end):
    import akshare as ak
    df = ak.index_zh_a_hist_min_em(symbol="000001", period="5", start_date=f"{start[:4]}-{start[4:6]}-{start[6:]} 09:30:00",
                                   end_date=f"{end[:4]}-{end[4:6]}-{end[6:]} 15:00:00")
    df = df.rename(columns={"时间": "time", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low"})
    return df[["time", "open", "close", "high", "low"]]


def classify_day(d):
    """d: 一天的 5 分钟 bar DataFrame（time 为 bar 结束时间字符串 HH:MM）"""
    d = d.copy()
    d["hm"] = d["time"].str[11:16]
    z2 = d[(d["hm"] > "10:00") & (d["hm"] <= "10:30")]
    if len(z2) < 5:
        return None
    a, b = z2.iloc[:3], z2.iloc[3:]          # 10:00-10:15 vs 10:15-10:30
    hh = b["high"].max() > a["high"].max()
    hl = b["low"].min() > a["low"].min()
    lh = b["high"].max() < a["high"].max()
    ll = b["low"].min() < a["low"].min()
    if hh and hl:
        strict = "好"
    elif lh and ll:
        strict = "坏"
    else:
        strict = "模糊"
    loose = "好" if z2.iloc[-1]["close"] > z2.iloc[0]["open"] else ("坏" if z2.iloc[-1]["close"] < z2.iloc[0]["open"] else "模糊")

    day_open = d.iloc[0]["open"]
    day_close = d.iloc[-1]["close"]
    z1to4 = d[d["hm"] <= "11:30"]
    z5 = d[(d["hm"] > "13:00") & (d["hm"] <= "13:30")]
    new_low5 = len(z5) > 0 and z5["low"].min() < z1to4["low"].min()
    new_high5 = len(z5) > 0 and z5["high"].max() > z1to4["high"].max()
    at1030 = z2.iloc[-1]["close"]
    return {"open": float(day_open), "close": float(day_close), "strict": strict, "loose": loose,
            "new_low5": bool(new_low5), "new_high5": bool(new_high5), "at1030": float(at1030)}


def verdict(pred, o, c):
    """pred 好: 不会跌 → c>=o 算对；坏: 不会涨 → c<=o 算对"""
    if pred == "好":
        return c >= o
    if pred == "坏":
        return c <= o
    return None


def evaluate(rows):
    out = {}
    for mode in ("strict", "loose"):
        for fix in (False, True):
            n = ok = flat = 0
            for r in rows:
                p = r[mode]
                if p == "模糊":
                    # 严格口径模糊时退回宽松口径（课程"每天都有预测"）
                    p = r["loose"] if mode == "strict" else p
                    if p == "模糊":
                        continue
                if fix:
                    if p == "好" and r["new_low5"]:
                        p = "坏"
                    elif p == "坏" and r["new_high5"]:
                        p = "好"
                v = verdict(p, r["open"], r["close"])
                if v is None:
                    continue
                n += 1
                ok += int(v)
                flat += int(r["close"] == r["open"])
            out[f"{mode}{'+五区修正' if fix else ''}"] = {"n": n, "correct": ok, "acc": round(ok / n * 100, 2) if n else None, "flat_days": flat}
    # 基线 A：10:30 相对开盘的方向 → 预测收盘同向（同样用"不会跌/不会涨"宽松判对）
    n = ok = 0
    for r in rows:
        p = "好" if r["at1030"] > r["open"] else ("坏" if r["at1030"] < r["open"] else None)
        if p is None:
            continue
        n += 1
        ok += int(verdict(p, r["open"], r["close"]))
    out["基线A_10:30相对开盘同向"] = {"n": n, "correct": ok, "acc": round(ok / n * 100, 2) if n else None}
    # 基线 B：永远预测"不会跌"
    n = len(rows)
    ok = sum(1 for r in rows if r["close"] >= r["open"])
    out["基线B_永远说不会跌"] = {"n": n, "correct": ok, "acc": round(ok / n * 100, 2) if n else None}
    # 严格口径下"涨/跌"硬判（收盘严格高于/低于开盘才算对，平盘算错）
    n = ok = 0
    for r in rows:
        p = r["strict"] if r["strict"] != "模糊" else r["loose"]
        if p == "模糊":
            continue
        n += 1
        ok += int((r["close"] > r["open"]) if p == "好" else (r["close"] < r["open"]))
    out["strict_硬判(平盘算错)"] = {"n": n, "correct": ok, "acc": round(ok / n * 100, 2) if n else None}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20240101")
    ap.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--csv")
    ap.add_argument("--daily", help="日线 CSV（date,open,high,low,close），用官方开盘价/收盘价替代分钟线首末值")
    args = ap.parse_args()
    if args.csv:
        df = pd.read_csv(args.csv)
    else:
        df = fetch(args.start, args.end)
        out_dir = ROOT / "experiments"
        out_dir.mkdir(exist_ok=True)
        df.to_csv(out_dir / "sse_5min.csv", index=False)
    df["day"] = df["time"].str[:10]
    daily = {}
    if args.daily:
        dd = pd.read_csv(args.daily)
        daily = {str(r["date"])[:10]: (float(r["open"]), float(r["close"])) for _, r in dd.iterrows()}
    rows = []
    for day, d in df.groupby("day"):
        r = classify_day(d.sort_values("time"))
        if r:
            r["day"] = day
            if day in daily:
                r["open"], r["close"] = daily[day]
            rows.append(r)
    print(f"交易日 {len(rows)} 天，{rows[0]['day']} ~ {rows[-1]['day']}")
    res = {"days": len(rows), "span": [rows[0]["day"], rows[-1]["day"]], "by_year": {}, "all": evaluate(rows)}
    for y in sorted({r["day"][:4] for r in rows}):
        res["by_year"][y] = evaluate([r for r in rows if r["day"].startswith(y)])
    dist = {}
    for r in rows:
        dist[r["strict"]] = dist.get(r["strict"], 0) + 1
    res["strict_distribution"] = dist
    print(json.dumps(res, ensure_ascii=False, indent=1))
    (ROOT / "experiments" / "erqu_result.json").write_text(json.dumps({"result": res, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
