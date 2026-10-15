#!/usr/bin/env python3
"""
品种加权指数（文华"加权"口径：全部在市合约按当日持仓量加权）
算法来源：ZCode 实测脚本 fetch_weighted_index.py（2026-10-15），已与主力连续交叉核对。

  price_w = Σ(价格 × 持仓) / Σ持仓     volume = Σ成交量     oi = Σ持仓
  零成交日：合约在 [首行, 末行] 内按交易日历重索引，价格/持仓前向填充、成交量补 0

数据：新浪逐合约日线 akshare.futures_zh_daily_sina(symbol="P2601")，2020 年起完整（2019 及更早有缺口）。
输出：data/weighted/<SYM>.csv（date,open,high,low,close,volume,oi）

用法：
  python scanner/weighted.py --full            # 全量重建（首次，约 54×90 次请求，建议在 Actions 跑）
  python scanner/weighted.py --update          # 每日增量：只拉在市合约，续接最后一天之后
  python scanner/weighted.py --full --symbols P0,Y0
"""
import argparse
import csv
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "weighted"
COLS = ["date", "open", "high", "low", "close", "volume", "oi"]
START = "2020-01-01"
FIRST_YY = 20


def _prefix(sym: str) -> str:
    return sym[:-1] if sym.endswith("0") else sym


def contracts(prefix: str, active_only: bool, today: date | None = None) -> list[str]:
    today = today or date.today()
    last_yy = today.year % 100 + 2
    cs = []
    for yy in range(FIRST_YY, last_yy + 1):
        for m in range(1, 13):
            if active_only and (yy * 100 + m) < (today.year % 100 * 100 + today.month):
                continue
            cs.append(f"{prefix}{yy:02d}{m:02d}")
    return cs


def fetch_contract(sym: str, tries: int = 3) -> pd.DataFrame | None:
    import akshare as ak
    for i in range(tries):
        try:
            df = ak.futures_zh_daily_sina(symbol=sym)
            if df is None or len(df) == 0:
                return None
            return df
        except ValueError as e:
            if "Length mismatch" in str(e):  # 合约不存在 / 未上市
                return None
            time.sleep(1 + 2 * i)
        except Exception:
            time.sleep(1 + 2 * i)
    print(f"  ! {sym} 拉取失败", file=sys.stderr)
    return None


def calendar(prefix: str, start: str) -> pd.DatetimeIndex:
    import akshare as ak
    cal_from = (pd.Timestamp(start) - pd.Timedelta(days=40)).strftime("%Y%m%d")
    cal = ak.futures_main_sina(symbol=f"{prefix}0", start_date=cal_from, end_date=pd.Timestamp.today().strftime("%Y%m%d"))
    return pd.DatetimeIndex(sorted(pd.to_datetime(cal["日期"])))


def weighted(frames: dict[str, pd.DataFrame], cal_idx: pd.DatetimeIndex, start: str) -> pd.DataFrame:
    parts = []
    for sym, df in frames.items():
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"])
        d = d.drop_duplicates("date").set_index("date").sort_index()
        d = d[d.index >= pd.Timestamp(start) - pd.Timedelta(days=40)]
        if d.empty:
            continue
        idx = cal_idx[(cal_idx >= d.index.min()) & (cal_idx <= d.index.max())]
        r = d.reindex(idx)
        for c in ["open", "high", "low", "close", "hold"]:
            r[c] = r[c].ffill()
        no_trade = ~r.index.isin(d.index)
        for c in ["open", "high", "low"]:
            r.loc[no_trade, c] = r.loc[no_trade, "close"]
        r["volume"] = r["volume"].fillna(0)
        r["symbol"] = sym
        parts.append(r.reset_index().rename(columns={"index": "date"}))
    if not parts:
        return pd.DataFrame(columns=COLS).set_index("date")
    allc = pd.concat(parts, ignore_index=True)
    allc = allc[allc["date"] >= pd.Timestamp(start)]
    v = allc[(allc["hold"] > 0) & (allc["close"] > 0)].copy()
    for c in ["open", "high", "low", "close"]:
        v["w_" + c] = v[c] * v["hold"]
    gb = v.groupby("date")
    out = pd.DataFrame({
        "open": gb["w_open"].sum() / gb["hold"].sum(),
        "high": gb["w_high"].sum() / gb["hold"].sum(),
        "low": gb["w_low"].sum() / gb["hold"].sum(),
        "close": gb["w_close"].sum() / gb["hold"].sum(),
        "volume": allc.groupby("date")["volume"].sum(),
        "oi": gb["hold"].sum(),
    }).dropna(subset=["open", "high", "low", "close"])
    out.index.name = "date"
    out = out.round({"open": 2, "high": 2, "low": 2, "close": 2})
    out["volume"] = out["volume"].astype("int64")
    out["oi"] = out["oi"].astype("int64")
    return out


def load_existing(sym: str) -> pd.DataFrame | None:
    p = OUT_DIR / f"{sym}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    return df if len(df) else None


def save(sym: str, df: pd.DataFrame):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.sort_index().reset_index().assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d")).to_csv(OUT_DIR / f"{sym}.csv", index=False)


def build(sym: str, full: bool) -> str:
    prefix = _prefix(sym)
    existing = None if full else load_existing(sym)
    if existing is None:
        full = True
    cs = contracts(prefix, active_only=not full)
    frames = {}
    for c in cs:
        df = fetch_contract(c)
        if df is not None:
            frames[c] = df
    if not frames:
        return f"{sym}: 无合约数据"
    start = START if full else (existing.index.max() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    cal_idx = calendar(prefix, start)
    w = weighted(frames, cal_idx, start)
    if w.empty:
        return f"{sym}: 加权结果为空"
    if full:
        save(sym, w)
        return f"{sym}: 全量 {len(w)} 行 {w.index.min().date()}~{w.index.max().date()}（{len(frames)} 个合约）"
    new = w[w.index > existing.index.max()]
    # 增量时最后几天用在市合约重算，与全量一致（已摘牌合约不再有新行）
    merged = pd.concat([existing[existing.index < w.index.min()], w]).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    save(sym, merged)
    return f"{sym}: 新增 {len(new)} 行，最新 {merged.index.max().date()}"


def main():
    from scan import SYMBOLS
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--symbols", default="")
    a = ap.parse_args()
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()] or list(SYMBOLS)
    ok = 0
    for s in syms:
        try:
            msg = build(s, full=a.full)
            ok += 1
        except Exception as e:
            msg = f"{s}: 失败 {e}"
        print(msg, flush=True)
    print(f"完成 {ok}/{len(syms)}")


if __name__ == "__main__":
    main()
