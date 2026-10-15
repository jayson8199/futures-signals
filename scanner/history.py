#!/usr/bin/env python3
"""
长期日线库 data/history/<SYMBOL>.csv（date,open,high,low,close,volume,oi）
- 初始由 Kimi 交接包的 54 品种 ~270 日数据导入
- 每日扫描后用 data.json 中各品种 hist（近 45 日）合并，保持连续
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HIST_DIR = ROOT / "data" / "history"
COLS = ["date", "open", "high", "low", "close", "volume", "oi"]


def load(symbol: str) -> list[dict]:
    p = HIST_DIR / f"{symbol}.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        rows = []
        for r in csv.DictReader(f):
            rows.append({"date": r["date"], "open": _f(r.get("open")), "high": _f(r.get("high")), "low": _f(r.get("low")),
                         "close": float(r["close"]), "volume": int(float(r["volume"])), "oi": int(float(r["oi"]))})
    rows.sort(key=lambda x: x["date"])
    return rows


def load_all() -> dict[str, list[dict]]:
    return {p.stem: load(p.stem) for p in sorted(HIST_DIR.glob("*.csv"))}


def _f(v):
    try:
        return float(v) if v not in (None, "", "nan") else None
    except ValueError:
        return None


def merge_from_data(data: dict) -> int:
    """把一天 data.json 的 hist 合并进 CSV；返回新增/更新行数"""
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    changed = 0
    for it in data["all_results"]:
        sym = it["symbol"]
        rows = {r["date"]: r for r in load(sym)}
        incoming = []
        for h in it.get("hist") or []:
            if len(h) >= 7:
                incoming.append({"date": h[0], "open": h[1], "high": h[2], "low": h[3], "close": h[4], "volume": h[5], "oi": h[6]})
            elif len(h) == 4:
                incoming.append({"date": h[0], "open": None, "high": None, "low": None, "close": h[1], "volume": h[2], "oi": h[3]})
        if not incoming:
            incoming.append({"date": it["date"], "open": None, "high": None, "low": None,
                             "close": it["today_close"], "volume": it["today_vol"], "oi": it["today_hold"]})
        for r in incoming:
            old = rows.get(r["date"])
            if old != r:
                rows[r["date"]] = r
                changed += 1
        with (HIST_DIR / f"{sym}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            for d in sorted(rows):
                r = rows[d]
                w.writerow({k: ("" if r.get(k) is None else r[k]) for k in COLS})
    return changed
