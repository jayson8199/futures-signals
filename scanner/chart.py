#!/usr/bin/env python3
"""
K 线图页数据：按《王刚期货交易体系手册（第二版）》的规则，对 data/history/<SYM>.csv 逐根计算
  - 均线 MA5/10/20/60、MACD(8,21,6)（手册 5.2：一堵 MACD=8.21.6）、RSI14（手册 1.2：80/20 过滤）
  - 蜡烛形态（手册 1.2 日本蜡烛图；4.4 穿头破脚/太上皇）：吞没、乌云、刺透、锤子、上吊、射星、倒锤、十字、三白兵、三黑鸦
  - 包线（手册 5.9）：1包/2包/3包，不看阴阳；3包为调整结束信号之一（4.5）
  - 量仓价八种形态（手册 2.3）：高富帅/白富美 与 ±20% 增减仓日（2.3 增减仓量化规则）
  - 趋势状态（手册 4.1 道氏 + 均线）：趋势多头 / 趋势空头 / 震荡观望，状态切换处打标
  - 摆动高低点（为后续波浪与三步判断顶底做准备）
输出 site/chart/<SYM>.json 与 chart.html。纯规则、无拟合，便于日后按手册逐条校对。
"""
import json
from pathlib import Path

import history

# ---------- 指标 ----------

def sma(xs, n):
    out = [None] * len(xs)
    s = 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(xs, n):
    out = [None] * len(xs)
    k = 2 / (n + 1)
    e = None
    for i, x in enumerate(xs):
        e = x if e is None else x * k + e * (1 - k)
        out[i] = e
    return out


def macd(closes, fast=8, slow=21, sig=6):
    ef, es = ema(closes, fast), ema(closes, slow)
    dif = [a - b for a, b in zip(ef, es)]
    dea = ema(dif, sig)
    bar = [2 * (a - b) for a, b in zip(dif, dea)]
    return dif, dea, bar


def rsi(closes, n=14):
    out = [None] * len(closes)
    gain = loss = 0.0
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        g, l = max(d, 0), max(-d, 0)
        if i <= n:
            gain += g; loss += l
            if i == n:
                ag, al = gain / n, loss / n
                out[i] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
        else:
            ag = (ag * (n - 1) + g) / n
            al = (al * (n - 1) + l) / n
            out[i] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


# ---------- 蜡烛形态 ----------

def _trend_before(closes, i, n=5):
    """前 n 根的方向：+1 上涨、-1 下跌、0 不明（用于区分锤子/上吊、射星/倒锤）"""
    if i < n:
        return 0
    a, b = closes[i - n], closes[i - 1]
    if b > a * 1.01:
        return 1
    if b < a * 0.99:
        return -1
    return 0


def candle_patterns(rows):
    """返回 [(i, 名称, 方向 'bull'/'bear', 说明)]"""
    out = []
    o = [r["open"] for r in rows]; h = [r["high"] for r in rows]
    l = [r["low"] for r in rows]; c = [r["close"] for r in rows]
    for i in range(2, len(rows)):
        if None in (o[i], h[i], l[i]):
            continue
        body = abs(c[i] - o[i]); rng = h[i] - l[i]
        if rng <= 0:
            continue
        up_sh = h[i] - max(o[i], c[i]); lo_sh = min(o[i], c[i]) - l[i]
        t = _trend_before(c, i)
        pb = abs(c[i - 1] - o[i - 1])
        # 吞没 / 穿头破脚（手册 4.4：后者将前者实体全部包容在内，不含影线；阴阳相反）
        if pb > 0 and body > pb and ((c[i] > o[i] and c[i - 1] < o[i - 1] and o[i] <= c[i - 1] and c[i] >= o[i - 1])):
            out.append((i, "吞没", "bull", "阳线实体包住前一根阴线实体（看涨吞没 / 穿头破脚）"))
        elif pb > 0 and body > pb and ((c[i] < o[i] and c[i - 1] > o[i - 1] and o[i] >= c[i - 1] and c[i] <= o[i - 1])):
            out.append((i, "穿头破脚", "bear", "阴线实体包住前一根阳线实体（看跌吞没 / 太上皇）"))
        # 乌云盖顶 / 刺透
        elif t == 1 and c[i - 1] > o[i - 1] and o[i] > h[i - 1] and c[i] < (o[i - 1] + c[i - 1]) / 2 and c[i] > o[i - 1]:
            out.append((i, "乌云", "bear", "高开后收在前阳线实体中点之下"))
        elif t == -1 and c[i - 1] < o[i - 1] and o[i] < l[i - 1] and c[i] > (o[i - 1] + c[i - 1]) / 2 and c[i] < o[i - 1]:
            out.append((i, "刺透", "bull", "低开后收在前阴线实体中点之上"))
        # 锤子 / 上吊 / 射星 / 倒锤（实体小，一侧影线 ≥ 2 倍实体，另一侧很短）
        elif body <= rng * 0.35 and lo_sh >= 2 * max(body, rng * 0.05) and up_sh <= rng * 0.15:
            if t == -1:
                out.append((i, "锤子", "bull", "下跌后长下影小实体"))
            elif t == 1:
                out.append((i, "上吊", "bear", "上涨后长下影小实体，需次日确认"))
        elif body <= rng * 0.35 and up_sh >= 2 * max(body, rng * 0.05) and lo_sh <= rng * 0.15:
            if t == 1:
                out.append((i, "射星", "bear", "上涨后长上影小实体"))
            elif t == -1:
                out.append((i, "倒锤", "bull", "下跌后长上影小实体，需次日确认"))
        # 十字星（实体 < 8% 振幅）只在趋势明显时标
        elif body <= rng * 0.08 and t != 0 and rng > 0:
            out.append((i, "十字", "bear" if t == 1 else "bull", "多空平衡，趋势可能停顿"))
        # 三白兵 / 三黑鸦
        if i >= 2 and all(c[k] > o[k] for k in (i - 2, i - 1, i)) and c[i] > c[i - 1] > c[i - 2] \
                and all(o[k] > o[k - 1] for k in (i - 1, i)) and all(abs(c[k] - o[k]) > (h[k] - l[k]) * 0.5 for k in (i - 2, i - 1, i)):
            out.append((i, "红三兵", "bull", "连续三根实体阳线、逐步抬高"))
        if i >= 2 and all(c[k] < o[k] for k in (i - 2, i - 1, i)) and c[i] < c[i - 1] < c[i - 2] \
                and all(o[k] < o[k - 1] for k in (i - 1, i)) and all(abs(c[k] - o[k]) > (h[k] - l[k]) * 0.5 for k in (i - 2, i - 1, i)):
            out.append((i, "三黑鸦", "bear", "连续三根实体阴线、逐步压低"))
    return out


def baoxian(rows):
    """包线（手册 5.9，不看阴阳）：第 N+1 根的高低把前 N 根全部包住。返回 [(i, N)]，只记最大的 N（1..3）"""
    out = []
    for i in range(1, len(rows)):
        best = 0
        for n in (1, 2, 3):
            if i - n < 0:
                break
            hi = max(r["high"] for r in rows[i - n:i]); lo = min(r["low"] for r in rows[i - n:i])
            if rows[i]["high"] >= hi and rows[i]["low"] <= lo and (rows[i]["high"] - rows[i]["low"]) > 0:
                best = n
        if best:
            out.append((i, best))
    return out


# ---------- 量仓价与趋势 ----------

def vol_oi_marks(rows):
    """高富帅 / 白富美（手册 2.3，沿用 scan.py 判定：放量=高于 5 日和 20 日均量；仓 ±）与 ±20% 增减仓日"""
    out = []
    vols = [r["volume"] for r in rows]
    v5, v20 = sma(vols, 5), sma(vols, 20)
    for i in range(20, len(rows)):
        r, p = rows[i], rows[i - 1]
        if not p["oi"] or not p["close"]:
            continue
        chg = (r["close"] - p["close"]) / p["close"] * 100
        oi_chg = (r["oi"] - p["oi"]) / p["oi"] * 100
        vol_up = r["volume"] > v5[i - 1] and r["volume"] > v20[i - 1]
        tag = None
        if chg > 0 and vol_up and oi_chg > 0:
            tag = "高富帅"
        elif chg < 0 and vol_up and oi_chg > 0:
            tag = "白富美"
        if abs(oi_chg) >= 20:
            out.append((i, f"{'增' if oi_chg > 0 else '减'}仓{abs(oi_chg):.0f}%", "oi", "手册 2.3：一两天内增减仓 20%，会有大行情"))
        if tag and r["volume"] >= v20[i - 1] * 1.2 and oi_chg >= 20:
            out.append((i, tag + "★", "bull" if tag == "高富帅" else "bear", "量仓双 20%：强信号"))
        elif tag:
            out.append((i, tag, "bull" if tag == "高富帅" else "bear", "增仓·放量·" + ("上涨" if chg > 0 else "下跌")))
    return out


def regimes(closes, ma5, ma20, ma60, dif, dea):
    """每日趋势状态：多头=MA5>MA20>MA60 且 DIF>DEA；空头=相反；其余震荡观望。返回每日状态与切换点"""
    st = []
    for i in range(len(closes)):
        if ma60[i] is None:
            st.append(None); continue
        if ma5[i] > ma20[i] > ma60[i] and closes[i] > ma20[i] and dif[i] > dea[i]:
            st.append("趋势多头")
        elif ma5[i] < ma20[i] < ma60[i] and closes[i] < ma20[i] and dif[i] < dea[i]:
            st.append("趋势空头")
        else:
            st.append("震荡观望")
    # 去抖：新状态连续保持 3 天才算切换（标在新状态的第一天）
    changes = []
    last = None
    i = 0
    while i < len(st):
        s = st[i]
        if s and s != last and all(st[j] == s for j in range(i, min(i + 3, len(st)))) and i + 3 <= len(st):
            changes.append(i)
            last = s
            i += 3
        else:
            i += 1
    return st, changes


def swings(rows, k=5):
    """摆动高低点：k 根左右都不更高/更低。返回 [(i, 'H'/'L', price)]，去掉连续同类（保留更极端者）"""
    pts = []
    n = len(rows)
    for i in range(k, n - k):
        hi = rows[i]["high"]; lo = rows[i]["low"]
        if all(hi >= rows[j]["high"] for j in range(i - k, i + k + 1) if j != i):
            pts.append([i, "H", hi])
        elif all(lo <= rows[j]["low"] for j in range(i - k, i + k + 1) if j != i):
            pts.append([i, "L", lo])
    out = []
    for p in pts:
        if out and out[-1][1] == p[1]:
            if (p[1] == "H" and p[2] > out[-1][2]) or (p[1] == "L" and p[2] < out[-1][2]):
                out[-1] = p
        else:
            out.append(p)
    return out


# ---------- 汇总 ----------

def analyze(symbol, rows):
    rows = [r for r in rows if r["open"] is not None and r["high"] is not None and r["low"] is not None]
    if len(rows) < 30:
        return None
    closes = [r["close"] for r in rows]
    ma5, ma10, ma20, ma60 = sma(closes, 5), sma(closes, 10), sma(closes, 20), sma(closes, 60)
    dif, dea, bar = macd(closes)
    rs = rsi(closes)
    st, changes = regimes(closes, ma5, ma20, ma60, dif, dea)
    marks = []
    for i, name, side, desc in candle_patterns(rows):
        marks.append({"i": i, "t": name, "k": "candle", "s": side, "d": desc})
    for i, n in baoxian(rows):
        if n >= 2:
            marks.append({"i": i, "t": f"{n}包", "k": "bao", "s": "bull" if rows[i]["close"] >= rows[i]["open"] else "bear",
                          "d": f"第 {n + 1} 根包住前 {n} 根（手册 5.9，不看阴阳）" + ("；三包为调整结束信号" if n == 3 else "")})
    for i, name, side, desc in vol_oi_marks(rows):
        marks.append({"i": i, "t": name, "k": "voloi", "s": side, "d": desc})
    for i in changes:
        marks.append({"i": i, "t": st[i], "k": "regime", "s": {"趋势多头": "bull", "趋势空头": "bear"}.get(st[i], "flat"),
                      "d": "MA5/20/60 排列 + DIF 与 DEA 位置 + 收盘与 MA20 关系"})
    r = lambda v: None if v is None else round(v, 2)
    return {
        "symbol": symbol,
        "dates": [x["date"] for x in rows],
        "ohlc": [[x["open"], x["close"], x["low"], x["high"]] for x in rows],
        "vol": [x["volume"] for x in rows],
        "oi": [x["oi"] for x in rows],
        "ma5": [r(v) for v in ma5], "ma10": [r(v) for v in ma10], "ma20": [r(v) for v in ma20], "ma60": [r(v) for v in ma60],
        "dif": [r(v) for v in dif], "dea": [r(v) for v in dea], "macd": [r(v) for v in bar],
        "rsi": [r(v) for v in rs],
        "regime": st,
        "swings": swings(rows),
        "marks": marks,
    }


def build(out_dir: Path, symbols: dict):
    """生成 site/chart/*.json 与 index；返回可用品种列表"""
    d = out_dir / "chart"
    d.mkdir(parents=True, exist_ok=True)
    avail = []
    import csv as _csv
    for sym, (name, exch) in symbols.items():
        res = analyze(sym, history.load(sym))
        if not res:
            continue
        res["name"] = name; res["exchange"] = exch; res["kind"] = "主力连续"
        (d / f"{sym}.json").write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        has_w = False
        wp = history.ROOT / "data" / "weighted" / f"{sym}.csv"
        if wp.exists():
            with wp.open(encoding="utf-8") as f:
                rows = [{"date": r["date"], "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
                         "close": float(r["close"]), "volume": int(float(r["volume"])), "oi": int(float(r["oi"]))} for r in _csv.DictReader(f)]
            resw = analyze(sym, rows)
            if resw:
                resw["name"] = name; resw["exchange"] = exch; resw["kind"] = "加权"
                (d / f"{sym}_w.json").write_text(json.dumps(resw, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                has_w = True
        avail.append({"symbol": sym, "name": name, "exchange": exch, "last": res["dates"][-1],
                      "regime": res["regime"][-1], "n": len(res["dates"]), "weighted": has_w})
    (d / "index.json").write_text(json.dumps(avail, ensure_ascii=False), encoding="utf-8")
    return avail


if __name__ == "__main__":
    import sys
    from scan import SYMBOLS
    sym = sys.argv[1] if len(sys.argv) > 1 else "P0"
    res = analyze(sym, history.load(sym))
    print(sym, len(res["dates"]), "bars;", len(res["marks"]), "marks")
    for m in res["marks"][-25:]:
        print(res["dates"][m["i"]], m["k"], m["t"], "-", m["d"])
