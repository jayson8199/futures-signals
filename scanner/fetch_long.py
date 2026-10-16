#!/usr/bin/env python3
"""拉取 54 个品种主力连续合约的长期日线（新浪，经 akshare），写入 data/long/<SYM>.csv，供趋势跟踪回测使用。
用法：python scanner/fetch_long.py [--start 20180101]
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scanner"))
from scan import SYMBOLS  # noqa: E402

OUT = ROOT / "data" / "long"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20180101")
    args = ap.parse_args()
    import akshare as ak
    OUT.mkdir(parents=True, exist_ok=True)
    end = datetime.now().strftime("%Y%m%d")
    ok = 0
    for sym in SYMBOLS:
        for attempt in range(3):
            try:
                df = ak.futures_main_sina(symbol=sym, start_date=args.start, end_date=end)
                if df is None or df.empty:
                    raise RuntimeError("empty")
                df = df.rename(columns={"日期": "date", "开盘价": "open", "最高价": "high", "最低价": "low", "收盘价": "close", "成交量": "volume", "持仓量": "oi", "动态结算价": "settle"})
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                df = df[["date", "open", "high", "low", "close", "volume", "oi"]].sort_values("date").drop_duplicates("date")
                df.to_csv(OUT / f"{sym}.csv", index=False)
                print(f"{sym} {len(df)} 行 {df['date'].iloc[0]}~{df['date'].iloc[-1]}")
                ok += 1
                break
            except Exception as e:
                print(f"  {sym} 第{attempt + 1}次失败: {e}", file=sys.stderr)
                time.sleep(3 + 3 * attempt)
        time.sleep(0.8)
    print(f"完成 {ok}/{len(SYMBOLS)}")


if __name__ == "__main__":
    main()
