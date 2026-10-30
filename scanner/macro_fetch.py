#!/usr/bin/env python3
"""
宏观数据拉取（美林时钟用）：PMI、CPI、PPI、核心 CPI、LPR、存款准备金率 → data/macro/*.csv
在 GitHub Actions 上跑（国内财经站点从那里可达）。每个序列独立 try，拿到多少存多少，日志里列出成败。
优先用金十（*_yearly 系列），因为它带"公布日期"，回测时能严格按公布日错开；东方财富版本作备份。
用法：python scanner/macro_fetch.py
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "macro"


def try_fetch(name, fn_name, **kw):
    import akshare as ak
    fn = getattr(ak, fn_name, None)
    if fn is None:
        print(f"[缺] {name}: akshare 没有 {fn_name}")
        return False
    try:
        df = fn(**kw)
        if df is None or len(df) == 0:
            print(f"[空] {name}: {fn_name}")
            return False
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"[好] {name}: {fn_name} {len(df)} 行，列 {list(df.columns)[:8]}，首行 {df.iloc[0].tolist()[:4]}，末行 {df.iloc[-1].tolist()[:4]}")
        return True
    except Exception as e:
        print(f"[错] {name}: {fn_name} {type(e).__name__}: {str(e)[:150]}")
        return False


def main():
    import akshare as ak
    OUT.mkdir(parents=True, exist_ok=True)
    print("akshare", ak.__version__)
    print("可用的 CPI/PPI/PMI 相关函数：", [f for f in dir(ak) if f.startswith("macro_china") and any(k in f for k in ("cpi", "ppi", "pmi", "core", "lpr", "reserve"))])
    jobs = [
        ("cpi_jin10", "macro_china_cpi_yearly", {}),
        ("ppi_jin10", "macro_china_ppi_yearly", {}),
        ("pmi_jin10", "macro_china_pmi_yearly", {}),
        ("cpi_em", "macro_china_cpi", {}),
        ("ppi_em", "macro_china_ppi", {}),
        ("pmi_em", "macro_china_pmi", {}),
        ("lpr", "macro_china_lpr", {}),
        ("rrr", "macro_china_reserve_requirement_ratio", {}),
    ]
    for f in dir(ak):  # 核心 CPI：名字里带 core 的都试一遍
        if f.startswith("macro_china") and "core" in f:
            jobs.append((f"corecpi_{f}", f, {}))
    ok = sum(try_fetch(n, f, **kw) for n, f, kw in jobs)
    print(f"完成 {ok}/{len(jobs)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
