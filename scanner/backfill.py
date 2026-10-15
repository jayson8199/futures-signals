#!/usr/bin/env python3
"""
用 data/history/*.csv 回填历史每日 data/<date>.json（八种形态快照），供网站归档页使用。
用法：python scanner/backfill.py --days 60 [--overwrite]
回填文件不含 hist（长期日线已在 history 库中）。
"""
import argparse
import json
from pathlib import Path

import pandas as pd

import history
from scan import SYMBOLS, analyze_df, summarize

ROOT = Path(__file__).resolve().parent.parent


def to_df(rows):
    return pd.DataFrame({"日期": [r["date"] for r in rows], "开盘价": [r["open"] if r["open"] is not None else r["close"] for r in rows],
                         "最高价": [r["high"] if r["high"] is not None else r["close"] for r in rows],
                         "最低价": [r["low"] if r["low"] is not None else r["close"] for r in rows],
                         "收盘价": [r["close"] for r in rows], "成交量": [r["volume"] for r in rows], "持仓量": [r["oi"] for r in rows]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    H = history.load_all()
    all_dates = sorted({r["date"] for rows in H.values() for r in rows})
    targets = all_dates[-args.days:]
    made = 0
    for d in targets:
        out = ROOT / "data" / f"{d}.json"
        if out.exists() and not args.overwrite:
            continue
        results, errors = [], []
        for sym, (name, exch) in SYMBOLS.items():
            rows = [r for r in H.get(sym, []) if r["date"] <= d]
            if not rows or rows[-1]["date"] != d or len(rows) < 21:
                errors.append(sym)
                continue
            r = analyze_df(to_df(rows[-60:]), sym, name, exch)
            if r:
                r.pop("hist", None)
                results.append(r)
            else:
                errors.append(sym)
        if len(results) < 40:
            print(f"跳过 {d}：有效品种 {len(results)}")
            continue
        data = summarize(results, errors, d)
        data["backfilled"] = True
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        made += 1
    print(f"回填完成：{made} 天（目标 {len(targets)} 天，{targets[0]} ~ {targets[-1]}）")


if __name__ == "__main__":
    main()
