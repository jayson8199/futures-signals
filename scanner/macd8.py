#!/usr/bin/env python3
"""
期货 MACD 多空八策略（买卖点）——逻辑与 Kimi 版 futures_macd.py 完全一致
多头四策略：1 红柱二次翻红 / 2 绿柱峰后收窄 / 3 零轴回踩拐头 / 4 双绿柱底背离
空头四策略（镜像）：5 绿柱二次翻深 / 6 红柱峰后收窄 / 7 零轴回抽下拐 / 8 双红柱顶背离
阈值相对化：DIF / 收盘价 (%)；"首发"判定：昨日未触发、今日触发
输入：data/history/<SYM>.csv 的收盘价序列
"""
import numpy as np
import pandas as pd

T1, T2, T3, T34 = 0.5, 0.8, 0.5, 0.5
MIN_BARS = 120

STRAT_NAMES = ["策略1-红柱二次翻红(多)", "策略2-绿柱峰后收窄(多)", "策略3-零轴回踩拐头(多)", "策略4-双绿柱底背离(多)",
               "策略5-绿柱二次翻深(空)", "策略6-红柱峰后收窄(空)", "策略7-零轴回抽下拐(空)", "策略8-双红柱顶背离(空)"]
STRAT_SHORT = ["红柱二次翻红", "绿柱峰后收窄", "零轴回踩拐头", "双绿柱底背离", "绿柱二次翻深", "红柱峰后收窄", "零轴回抽下拐", "双红柱顶背离"]
STRAT_DIR = ["多", "多", "多", "多", "空", "空", "空", "空"]
STRAT_MEANING = ["买入/持多：多头动能回调后再度增强", "低吸/加仓：强多头趋势中回调见底收窄", "确认买入：DIF 回踩零轴后重新拐头",
                 "抄底：价创新低而柱不创新低（底背离）", "卖出/开空：空头动能延续", "反弹卖出：强空头趋势中反弹结束",
                 "确认卖出：DIF 回抽零轴后再下拐", "顶部卖出：价创新高而柱不创新高（顶背离）"]


def compute_indicators(closes: pd.Series):
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = 2 * (dif - dea)
    ma5 = closes.rolling(5).mean()
    dif_pct = dif / closes * 100
    return dif.values, dea.values, hist.values, ma5.values, dif_pct.values


def strategy_flags(dif, dea, hist, ma5, dif_pct, closes, i):
    if i < 30:
        return [False] * 8
    d_i, de_i, h_i = dif[i], dea[i], hist[i]
    h_p = hist[i - 1]
    c_i, m_i = closes[i], ma5[i]
    dp_i = dif_pct[i]
    flags = [False] * 8

    if dp_i > T1 and de_i > 0 and h_i > 0 and h_p > 0 and h_i > h_p:
        shrink = 0
        for k in range(i - 1, max(i - 15, 1), -1):
            if hist[k] > 0 and hist[k] < hist[k - 1]:
                shrink += 1
            else:
                break
        if shrink >= 1:
            flags[0] = True

    if dp_i > T2 and de_i > 0 and h_i < 0 and c_i > m_i:
        rg = []
        for k in range(i, -1, -1):
            if hist[k] < 0:
                rg.insert(0, abs(hist[k]))
            else:
                break
        if len(rg) >= 3:
            fp = any(rg[k] > rg[k - 1] and rg[k] > rg[k + 1] for k in range(1, len(rg) - 1))
            if fp and rg[-1] < rg[-2]:
                flags[1] = True

    if -T3 < dp_i < T3 and c_i > m_i and dif[i] > dif[i - 1]:
        if i >= 20 and dif_pct[i - 20] > T34:
            flags[2] = True

    if d_i < 0 and de_i < 0 and c_i > m_i and np.sum(dif_pct[i - 29:i + 1] < 0) >= 20:
        clusters, in_cl, start = [], False, None
        for k in range(i + 1):
            if hist[k] < 0 and not in_cl:
                in_cl, start = True, k
            elif hist[k] >= 0 and in_cl:
                in_cl = False
                clusters.append((start, k - 1))
        if in_cl:
            clusters.append((start, i))
        if len(clusters) >= 2:
            c1, c2 = clusters[-2], clusters[-1]
            if c2[1] - c2[0] >= 1:
                pl1 = min(closes[c1[0]:c1[1] + 1]); pl2 = min(closes[c2[0]:c2[1] + 1])
                hl1 = min(hist[c1[0]:c1[1] + 1]); hl2 = min(hist[c2[0]:c2[1] + 1])
                if pl2 < pl1 and hl2 > hl1:
                    flags[3] = True

    if dp_i < -T1 and de_i < 0 and h_i < 0 and h_p < 0 and h_i < h_p:
        shrink = 0
        for k in range(i - 1, max(i - 15, 1), -1):
            if hist[k] < 0 and hist[k] > hist[k - 1]:
                shrink += 1
            else:
                break
        if shrink >= 1:
            flags[4] = True

    if dp_i < -T2 and de_i < 0 and h_i > 0 and c_i < m_i:
        rr = []
        for k in range(i, -1, -1):
            if hist[k] > 0:
                rr.insert(0, hist[k])
            else:
                break
        if len(rr) >= 3:
            fp = any(rr[k] > rr[k - 1] and rr[k] > rr[k + 1] for k in range(1, len(rr) - 1))
            if fp and rr[-1] < rr[-2]:
                flags[5] = True

    if -T3 < dp_i < T3 and c_i < m_i and dif[i] < dif[i - 1]:
        if i >= 20 and dif_pct[i - 20] < -T34:
            flags[6] = True

    if d_i > 0 and de_i > 0 and c_i < m_i and np.sum(dif_pct[i - 29:i + 1] > 0) >= 20:
        clusters, in_cl, start = [], False, None
        for k in range(i + 1):
            if hist[k] > 0 and not in_cl:
                in_cl, start = True, k
            elif hist[k] <= 0 and in_cl:
                in_cl = False
                clusters.append((start, k - 1))
        if in_cl:
            clusters.append((start, i))
        if len(clusters) >= 2:
            c1, c2 = clusters[-2], clusters[-1]
            if c2[1] - c2[0] >= 1:
                ph1 = max(closes[c1[0]:c1[1] + 1]); ph2 = max(closes[c2[0]:c2[1] + 1])
                hh1 = max(hist[c1[0]:c1[1] + 1]); hh2 = max(hist[c2[0]:c2[1] + 1])
                if ph2 > ph1 and hh2 < hh1:
                    flags[7] = True
    return flags


def scan_series(symbol, name, exchange, rows, since=None):
    """rows: history 行列表（含 date/close）。返回该品种全部首发信号（可按 since 日期过滤），附前向收益"""
    if len(rows) < MIN_BARS + 25:
        return []
    closes = np.array([r["close"] for r in rows], dtype=float)
    dates = [r["date"] for r in rows]
    dif, dea, hist, ma5, dif_pct = compute_indicators(pd.Series(closes))
    n = len(closes)
    out = []
    prev_flags = strategy_flags(dif, dea, hist, ma5, dif_pct, closes, MIN_BARS - 1)
    for i in range(MIN_BARS, n):
        flags = strategy_flags(dif, dea, hist, ma5, dif_pct, closes, i)
        if any(flags) and (since is None or dates[i] >= since):
            for s in range(8):
                if flags[s] and not prev_flags[s]:
                    sign = 1 if STRAT_DIR[s] == "多" else -1
                    fwd = {k: round(sign * (closes[i + k] / closes[i] - 1) * 100, 2) for k in (1, 3, 5) if i + k < n}
                    out.append({"symbol": symbol, "name": name, "exchange": exchange, "sid": s + 1,
                                "strategy": STRAT_NAMES[s], "short": STRAT_SHORT[s], "direction": STRAT_DIR[s],
                                "date": dates[i], "close": round(float(closes[i]), 2),
                                "dif": round(float(dif[i]), 3), "dea": round(float(dea[i]), 3),
                                "hist": round(float(hist[i]), 4), "dif_pct": round(float(dif_pct[i]), 3), "fwd": fwd})
        prev_flags = flags
    return out


def scan_all(history: dict, symbols: dict, since=None):
    sigs = []
    for sym, (name, exch) in symbols.items():
        sigs.extend(scan_series(sym, name, exch, history.get(sym, []), since=since))
    sigs.sort(key=lambda x: (x["date"], x["direction"] != "多", x["sid"]))
    return sigs
