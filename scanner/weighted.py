#!/usr/bin/env python3
"""
品种加权指数（文华"加权"口径：全部在市合约按当日持仓量加权）

  price_w = Σ(价格 × 持仓) / Σ持仓     volume = Σ成交量     oi = Σ持仓
  零成交日：合约在 [首行, 末行] 内按交易日历重索引，价格/持仓前向填充、成交量补 0

数据源（--source）：
  tushare  第三方代理（token 从环境变量 TUSHARE_TOKEN 读取），单合约日线自 2008 年起；默认（有 token 时）
  sina     新浪逐合约（akshare.futures_zh_daily_sina），2020 年起完整；无 token 时回退
两者在 2020 年后的共同交易日上平均相对误差 0.002%（experiments/tushare_probe.md）。

输出：data/weighted/<SYM>.csv（date,open,high,low,close,volume,oi）
合约缓存：<cache>/<prefix>/<合约>.csv（已摘牌合约永不变化，重跑直接复用）

用法：
  python scanner/weighted.py --full              # 全量重建（首次）
  python scanner/weighted.py --update            # 每日增量：只拉在市合约，续接最后一天之后
  python scanner/weighted.py --full --symbols P0,Y0 --source sina
"""
import argparse
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "weighted"
COLS = ["date", "open", "high", "low", "close", "volume", "oi"]
START = {"tushare": "2008-01-01", "sina": "2020-01-01"}
FIRST_YY = {"tushare": 8, "sina": 20}
TS_URLS = ["https://tl.kaixin8.top/tushare/sdk", "https://datahubco.com/api/tushare"]
INE = {"SC", "LU", "NR", "BC", "EC"}
TS_SUFFIX = {"上期所": "SHF", "大商所": "DCE", "郑商所": "ZCE", "中金所": "CFX", "广期所": "GFX"}


def _prefix(sym: str) -> str:
    return sym[:-1] if sym.endswith("0") else sym


def contracts(prefix: str, source: str, active_only: bool, today: date | None = None) -> list[str]:
    today = today or date.today()
    last_yy = today.year % 100 + 2
    cs = []
    for yy in range(FIRST_YY[source], last_yy + 1):
        for m in range(1, 13):
            if active_only and (yy * 100 + m) < (today.year % 100 * 100 + today.month):
                continue
            cs.append(f"{prefix}{yy:02d}{m:02d}")
    return cs


# ---------- 数据源 ----------

class Sina:
    name = "sina"

    def fetch(self, prefix: str, exch: str, code: str) -> pd.DataFrame | None:
        import akshare as ak
        for i in range(3):
            try:
                df = ak.futures_zh_daily_sina(symbol=code)
                if df is None or len(df) == 0:
                    return None
                return df[["date", "open", "high", "low", "close", "volume", "hold"]]
            except ValueError as e:
                if "Length mismatch" in str(e):
                    return None
                time.sleep(1 + 2 * i)
            except Exception:
                time.sleep(1 + 2 * i)
        raise RuntimeError(f"{code} 拉取失败")

    def calendar(self, prefix: str, start: str) -> pd.DatetimeIndex:
        import akshare as ak
        cal_from = (pd.Timestamp(start) - pd.Timedelta(days=40)).strftime("%Y%m%d")
        cal = ak.futures_main_sina(symbol=f"{prefix}0", start_date=cal_from, end_date=pd.Timestamp.today().strftime("%Y%m%d"))
        return pd.DatetimeIndex(sorted(pd.to_datetime(cal["日期"])))


class Tushare:
    name = "tushare"

    def __init__(self):
        import tushare as ts
        token = os.environ.get("TUSHARE_TOKEN", "").strip()
        if not token:
            raise RuntimeError("缺少 TUSHARE_TOKEN")
        self.pro = None
        for url in TS_URLS:
            pro = ts.pro_api(token, timeout=120)
            pro._DataApi__http_url = url
            try:
                if len(pro.daily(ts_code="000001.SZ", trade_date="20260930")):
                    self.pro = pro; self.url = url; break
            except Exception as e:
                print(f"  {url} 连不上: {str(e)[:100]}", file=sys.stderr)
        if self.pro is None:
            raise RuntimeError("tushare 两个服务器都连不上")

    @staticmethod
    def ts_code(prefix: str, exch: str, code: str) -> str:
        suf = "INE" if prefix in INE else TS_SUFFIX.get(exch, "DCE")
        return f"{code}.{suf}"

    def fetch(self, prefix: str, exch: str, code: str) -> pd.DataFrame | None:
        tc = self.ts_code(prefix, exch, code)
        for i in range(5):
            try:
                df = self.pro.fut_daily(ts_code=tc)
                time.sleep(0.4)
                if df is None or len(df) == 0:
                    return None
                d = df.rename(columns={"trade_date": "date", "vol": "volume", "oi": "hold"})
                d["date"] = pd.to_datetime(d["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
                return d[["date", "open", "high", "low", "close", "volume", "hold"]].sort_values("date")
            except Exception as e:
                msg = str(e)
                if "invalid_params" in msg:
                    return None
                if "upstream_pool_exhausted" in msg or "稍后重试" in msg:
                    time.sleep(31); continue
                time.sleep(3 + 3 * i)
        raise RuntimeError(f"{tc} 多次失败")

    def calendar(self, prefix: str, start: str) -> pd.DatetimeIndex:
        return None  # 用合约自身日期并集作日历（见 weighted）


# ---------- 计算 ----------

def weighted(frames: dict[str, pd.DataFrame], cal_idx: pd.DatetimeIndex | None, start: str) -> pd.DataFrame:
    prepared = {}
    for sym, df in frames.items():
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"])
        d = d.drop_duplicates("date").set_index("date").sort_index()
        d = d[d.index >= pd.Timestamp(start) - pd.Timedelta(days=40)]
        if not d.empty:
            prepared[sym] = d
    if not prepared:
        return pd.DataFrame(columns=COLS[1:]).rename_axis("date")
    if cal_idx is None:
        cal_idx = pd.DatetimeIndex(sorted(set().union(*[set(d.index) for d in prepared.values()])))
    parts = []
    for sym, d in prepared.items():
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


def build(sym: str, exch: str, src, full: bool, cache_dir: Path) -> str:
    prefix = _prefix(sym)
    existing = None if full else load_existing(sym)
    if existing is None:
        full = True
    cdir = cache_dir / src.name / prefix
    cdir.mkdir(parents=True, exist_ok=True)
    empty_file = cdir / "_empty.txt"
    empty = set(empty_file.read_text().split()) if empty_file.exists() else set()
    today = date.today()
    cs = contracts(prefix, src.name, active_only=not full, today=today)
    frames, fetched = {}, 0
    for c in cs:
        yymm = int(c[len(prefix):])
        active = yymm >= (today.year % 100 * 100 + today.month - 1)
        cache = cdir / f"{c}.csv"
        if cache.exists() and not active:          # 已摘牌合约：缓存永久有效
            frames[c] = pd.read_csv(cache); continue
        if c in empty and not active:
            continue
        df = src.fetch(prefix, exch, c)
        fetched += 1
        if df is None or len(df) == 0:
            empty.add(c); empty_file.write_text("\n".join(sorted(empty))); continue
        df.to_csv(cache, index=False)
        frames[c] = df
    if not frames and exch == "郑商所" and src.name == "tushare" and full:
        # 郑商所合约代码若为三位年月（如 CF601），改用三位码再试
        for c in cs:
            c3 = prefix + c[len(prefix) + 1:]
            df = src.fetch(prefix, exch, c3); fetched += 1
            if df is not None and len(df):
                df.to_csv(cdir / f"{c}.csv", index=False); frames[c] = df
    if not frames:
        return f"{sym}: 无合约数据（请求 {fetched} 次）"
    start = START[src.name] if full else (existing.index.max() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    w = weighted(frames, src.calendar(prefix, start), start)
    if w.empty:
        return f"{sym}: 加权结果为空"
    if full:
        save(sym, w)
        return f"{sym}: 全量 {len(w)} 行 {w.index.min().date()}~{w.index.max().date()}（{len(frames)} 合约，请求 {fetched} 次）"
    new = w[w.index > existing.index.max()]
    merged = pd.concat([existing[existing.index < w.index.min()], w]).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    save(sym, merged)
    return f"{sym}: 新增 {len(new)} 行，最新 {merged.index.max().date()}（请求 {fetched} 次）"


def main():
    from scan import SYMBOLS
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--source", default="auto", choices=["auto", "tushare", "sina"])
    ap.add_argument("--cache", default=str(ROOT / ".cache" / "contracts"))
    a = ap.parse_args()
    source = a.source
    if source == "auto":
        source = "tushare" if os.environ.get("TUSHARE_TOKEN") else "sina"
    src = Tushare() if source == "tushare" else Sina()
    print(f"数据源：{src.name}" + (f"（{src.url}）" if hasattr(src, "url") else ""))
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()] or list(SYMBOLS)
    ok = 0
    for s in syms:
        try:
            msg = build(s, SYMBOLS[s][1], src, full=a.full, cache_dir=Path(a.cache))
            ok += 1
        except Exception as e:
            msg = f"{s}: 失败 {str(e)[:200]}"
        print(msg, flush=True)
    print(f"完成 {ok}/{len(syms)}")


if __name__ == "__main__":
    main()
