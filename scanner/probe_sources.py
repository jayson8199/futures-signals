#!/usr/bin/env python3
"""
数据源可用性探测（实验）：从 GitHub 服务器尝试各交易所官方日报与新浪，记录到 experiments/probe_<date>.json
不影响主流程。用于决定是否把官方数据作为主数据源（可识别主力换月）。
"""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak

ROOT = Path(__file__).resolve().parent.parent
CN_TZ = ZoneInfo("Asia/Shanghai")


def try_call(name, fn):
    t0 = time.time()
    try:
        df = fn()
        n = 0 if df is None else len(df)
        cols = [] if df is None else list(df.columns)[:12]
        return {"source": name, "ok": n > 0, "rows": n, "cols": cols, "secs": round(time.time() - t0, 1)}
    except Exception as e:
        return {"source": name, "ok": False, "error": str(e)[:300], "secs": round(time.time() - t0, 1)}


def main():
    today = datetime.now(CN_TZ)
    # 取最近一个可能的交易日（昨天）做官方日报探测
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    ds = d.strftime("%Y%m%d")
    results = []
    for market in ["SHFE", "DCE", "CZCE", "CFFEX", "GFEX"]:
        results.append(try_call(f"official:{market}:{ds}",
                                lambda m=market: ak.get_futures_daily(start_date=ds, end_date=ds, market=m)))
        time.sleep(1)
    results.append(try_call("sina:RB0", lambda: ak.futures_main_sina(symbol="RB0", start_date="20260901", end_date=today.strftime("%Y%m%d"))))
    results.append(try_call("sina:main_contract_list", lambda: ak.futures_display_main_sina()))
    for r in results:
        print(("✓" if r["ok"] else "✗"), r)
    out = ROOT / "experiments"
    out.mkdir(exist_ok=True)
    (out / f"probe_{today:%Y-%m-%d}.json").write_text(json.dumps(
        {"time": today.isoformat(), "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
