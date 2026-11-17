#!/usr/bin/env python3
"""
宏观数据拉取（美林时钟用）：PMI、CPI、PPI、核心 CPI、LPR、存款准备金率 → data/macro/*.csv
在 GitHub Actions 上跑（国内财经站点从那里可达）。每个序列独立 try，拿到多少存多少，日志里列出成败。
CPI/PPI/PMI 用东方财富版（金十 *_yearly 系列已在 akshare 1.20.42 移除，data/macro/*_jin10.csv 是旧快照，不再更新）。
akshare 1.20.4x 把多个函数改了名（2026-11-17 已跟进）：数据来源和返回列不变，只是名字变了。
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
        ("cpi_em", "macro_china_cpi", {}),
        ("ppi_em", "macro_china_ppi", {}),
        ("pmi_em", "macro_china_pmi", {}),
        ("lpr", "interest_rate_lpr_em", {}),  # 原 macro_china_lpr
        ("rrr", "macro_china_reserve_requirement_ratio", {}),
        # 货币 + 信用（泽平宏观改良版时钟）
        ("m2", "macro_china_money_supply_em", {}),  # 原 macro_china_money_supply
        ("shrzgm", "macro_china_social_financing", {}),  # 原 macro_china_shrzgm
        ("shibor3m", "interest_rate_interbank_em", {"market": "上海银行同业拆借市场", "symbol": "Shibor人民币", "indicator": "3月"}),  # 原 rate_interbank
        ("cn_us_yield", "bond_zh_us_yield_em", {"start_date": "20100101"}),  # 原 bond_zh_us_rate
    ]
    for f in dir(ak):  # 核心 CPI：名字里带 core 的都试一遍
        if f.startswith("macro_china") and "core" in f:
            jobs.append((f"corecpi_{f}", f, {}))
    ok = sum(try_fetch(n, f, **kw) for n, f, kw in jobs)
    print(f"完成 {ok}/{len(jobs)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
