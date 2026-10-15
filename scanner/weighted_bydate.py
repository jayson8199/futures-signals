#!/usr/bin/env python3
"""
加权指数（文华口径）——按交易日全市场拉取版（tushare 代理）

  fut_daily(trade_date=D) 一次返回当日全市场所有期货合约（约 1000 行），
  按品种分组：price_w = Σ(价格×持仓)/Σ持仓，volume = Σ成交量，oi = Σ持仓。
  每天一次请求即可得到 54 个品种当日的加权 K 线；全历史 = 逐日拉取后拼接。

缓存：<cache>/bydate/YYYY/YYYYMMDD.csv（当日全市场原始行，永不变化）
输出：data/weighted/<SYM>.csv（date,open,high,low,close,volume,oi）

用法：
  python scanner/weighted_bydate.py --fetch 2008-01-01 2010-12-31      # 拉取区间（可并行分段）
  python scanner/weighted_bydate.py --assemble                          # 用缓存重算全部品种并写 data/weighted
  python scanner/weighted_bydate.py --update                            # 续接：拉 data/weighted 最后一天之后的交易日并追加
token 从环境变量 TUSHARE_TOKEN 读取。
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "weighted"
TS_URLS = ["https://tl.kaixin8.top/tushare/sdk", "https://datahubco.com/api/tushare"]
CODE_RE = re.compile(r"^([A-Za-z]+)(\d{3,4})\.([A-Z]+)$")
EXCH_MAP = {"SHF": "上期所", "INE": "上期所", "DCE": "大商所", "ZCE": "郑商所", "CFX": "中金所", "GFX": "广期所"}


def connect():
    import tushare as ts
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise SystemExit("缺少 TUSHARE_TOKEN")
    for url in TS_URLS:
        pro = ts.pro_api(token, timeout=90)
        pro._DataApi__http_url = url
        try:
            if len(pro.daily(ts_code="000001.SZ", trade_date="20260930")):
                print(f"数据源：{url}")
                return pro
        except Exception as e:
            print(f"  {url} 连不上: {str(e)[:100]}", file=sys.stderr)
    raise SystemExit("tushare 两个服务器都连不上")


def trade_days(pro, start: str, end: str) -> list[str]:
    """交易日历：用棕榈油主力映射的日期（2007-10 起连续）"""
    m = pro.fut_mapping(ts_code="P.DCE")  # 代理不接受起止日期参数，取全量后本地筛选
    days = sorted(set(m["trade_date"].astype(str)))
    return [d for d in days if start.replace("-", "") <= d <= end.replace("-", "")]


def fetch_day(pro, d: str, cache: Path) -> pd.DataFrame | None:
    f = cache / "bydate" / d[:4] / f"{d}.csv"
    if f.exists():
        return pd.read_csv(f, dtype={"trade_date": str})
    for i in range(4):
        try:
            df = pro.fut_daily(trade_date=d)
            break
        except Exception as e:
            msg = str(e)
            if "upstream_pool_exhausted" in msg or "稍后重试" in msg:
                time.sleep(31); continue
            if "invalid_params" in msg:
                df = None; break
            time.sleep(3 + 3 * i)
    else:
        print(f"  ! {d} 多次失败，跳过", file=sys.stderr)
        return None
    if df is None or len(df) == 0:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("")  # 非交易日/无数据：记空文件避免重拉
        return None
    f.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(f, index=False)
    return df


def day_weighted(df: pd.DataFrame, symbols: dict) -> dict[str, dict]:
    """一天的全市场行 → {SYM: {open,high,low,close,volume,oi}}"""
    out = {}
    if df is None or len(df) == 0:
        return out
    parts = df["ts_code"].str.extract(CODE_RE)
    df = df.assign(prefix=parts[0].str.upper(), exch=parts[2])
    df = df.dropna(subset=["prefix"])
    df["hold"] = pd.to_numeric(df["oi"], errors="coerce").fillna(0)
    df["volume"] = pd.to_numeric(df["vol"], errors="coerce").fillna(0)
    for sym, (name, exch_cn) in symbols.items():
        prefix = sym[:-1]
        g = df[(df["prefix"] == prefix) & (df["exch"].map(EXCH_MAP) == exch_cn)]
        if prefix in ("SC", "LU", "NR", "BC", "EC"):
            g = df[(df["prefix"] == prefix) & (df["exch"] == "INE")]
        g = g[(g["hold"] > 0) & (g["close"] > 0)]
        if g.empty:
            continue
        w = g["hold"].sum()
        out[sym] = {
            "open": round(float((g["open"] * g["hold"]).sum() / w), 2),
            "high": round(float((g["high"] * g["hold"]).sum() / w), 2),
            "low": round(float((g["low"] * g["hold"]).sum() / w), 2),
            "close": round(float((g["close"] * g["hold"]).sum() / w), 2),
            "volume": int(g["volume"].sum()),
            "oi": int(w),
        }
    return out


def assemble(cache: Path, symbols: dict, since: str | None = None) -> dict[str, pd.DataFrame]:
    rows = {s: [] for s in symbols}
    files = sorted((cache / "bydate").glob("*/*.csv"))
    for f in files:
        d = f.stem
        if since and d <= since:
            continue
        if f.stat().st_size == 0:
            continue
        df = pd.read_csv(f, dtype={"trade_date": str})
        for sym, rec in day_weighted(df, symbols).items():
            rows[sym].append({"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", **rec})
    return {s: pd.DataFrame(r) for s, r in rows.items() if r}


def write(sym: str, df: pd.DataFrame, append: bool):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / f"{sym}.csv"
    if append and p.exists():
        old = pd.read_csv(p)
        df = pd.concat([old, df]).drop_duplicates("date", keep="last")
    df.sort_values("date").to_csv(p, index=False)


def main():
    from scan import SYMBOLS
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", nargs=2, metavar=("START", "END"))
    ap.add_argument("--assemble", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--cache", default=str(ROOT / ".cache"))
    a = ap.parse_args()
    cache = Path(a.cache)

    if a.fetch:
        pro = connect()
        days = trade_days(pro, a.fetch[0], a.fetch[1])
        print(f"{a.fetch[0]}~{a.fetch[1]} 交易日 {len(days)} 个")
        n_new = 0
        for i, d in enumerate(days, 1):
            f = cache / "bydate" / d[:4] / f"{d}.csv"
            if f.exists():
                continue
            fetch_day(pro, d, cache); n_new += 1
            if n_new % 50 == 0:
                print(f"  {i}/{len(days)} {d}", flush=True)
        print(f"拉取完成：新增 {n_new} 天")

    if a.assemble:
        res = assemble(cache, SYMBOLS)
        for sym, df in res.items():
            write(sym, df, append=False)
            print(f"{sym}: {len(df)} 行 {df['date'].min()}~{df['date'].max()}")
        print(f"已写出 {len(res)} 个品种")

    if a.update:
        pro = connect()
        last = None
        p = OUT_DIR / "P0.csv"
        if p.exists():
            last = pd.read_csv(p)["date"].max().replace("-", "")
        start = last or "20080101"
        end = pd.Timestamp.today().strftime("%Y%m%d")
        days = [d for d in trade_days(pro, start, end) if d > start]
        print(f"续接：{start} 之后交易日 {len(days)} 个")
        for d in days:
            df = fetch_day(pro, d, cache)
            recs = day_weighted(df, SYMBOLS)
            for sym, rec in recs.items():
                write(sym, pd.DataFrame([{"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", **rec}]), append=True)
            print(f"  {d}: {len(recs)} 个品种", flush=True)


if __name__ == "__main__":
    import traceback
    try:
        main()
    except BaseException:
        tok = os.environ.get("TUSHARE_TOKEN", "").strip()
        msg = traceback.format_exc().replace(tok, "***") if tok else traceback.format_exc()
        print(msg, file=sys.stderr)
        logd = ROOT / "experiments"; logd.mkdir(exist_ok=True)
        (logd / "bydate_error.log").write_text(msg[-4000:], encoding="utf-8")
        raise
