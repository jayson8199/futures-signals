#!/usr/bin/env python3
"""
「跌够久」超跌反转 · 纸面实盘（2026-10-17 定稿，参数封存不再调整）

规则（与 scanner/trend_backtest.py 同一段代码算信号）：
  触发：某品种 60 日收益 ≤ 其自身历史（扩展窗口，≥250 天）最低 10% 分位 → 进入"超跌状态"（含离开阈值后 10 天）
  确认：超跌状态中首次出现  增仓 + 放量(量>5日均&>20日均) + 收盘突破 5 日高点 + MACD 红柱  → 发出买入
  执行：次日开盘价做多；持有 60 个交易日后次日开盘离场；盘中跌破止损即出（止损 = 持仓以来最高收盘 − 6×ATR14）
  仓位：每笔风险 0.5% 账户 / (6×ATR/价) 的名义比例，单品种 ≤15%、同板块 ≤45%、总名义 ≤150%；成本每边 0.02%
  只做多，不做空（镜像做空回测为负）。
状态：data/oversold/state.json；每日记录 data/oversold/daily/<date>.json
用法：python scanner/oversold_live.py run [--date YYYY-MM-DD] [--no-push]
      python scanner/oversold_live.py status
"""
import argparse
import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scanner"))
import trend_backtest as tb  # noqa: E402
from scan import SYMBOLS  # noqa: E402

CN_TZ = timezone(timedelta(hours=8))
OUT = ROOT / "data" / "oversold"
STATE = OUT / "state.json"
SIGNAL = "os_full5"
RULES = dict(RISK_PCT=0.005, ATR_K=6.0, HOLD_DAYS=60, OS_Q=0.10, MAX_SYM=0.15, MAX_SECTOR=0.45, MAX_GROSS=1.5, COST_SIDE=0.0002, EXIT_MA=0, STOP_MODE="atr")
START_DATE = "2026-10-19"  # 纸面实盘起点：此前不产生持仓，只用历史数据算指标


def now_cn():
    return datetime.now(CN_TZ)


def load_series():
    """data/long（2018 起）+ data/history（每日更新）合并，取最新"""
    out = {}
    for sym in SYMBOLS:
        parts = []
        for d in ("long", "history"):
            f = ROOT / "data" / d / f"{sym}.csv"
            if f.exists():
                parts.append(pd.read_csv(f))
        if not parts:
            continue
        df = pd.concat(parts, ignore_index=True)
        df = df.rename(columns={"vol": "volume"})
        df["date"] = df["date"].astype(str).str[:10]
        df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
        if len(df) >= 300:
            out[sym] = df
    return out


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"start": START_DATE, "equity": 1.0, "positions": {}, "pending": {}, "closed": [], "curve": [], "last_date": None, "rules": RULES, "signal": SIGNAL}


def save_state(st):
    OUT.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def build_ind():
    tb.P.update(RULES)
    data = load_series()
    return {s: tb.indicators(df, with_macd=False).set_index("date") for s, df in data.items()}


def run(day=None, push=True, ind=None):
    ind = ind or build_ind()
    all_dates = sorted(set().union(*[set(d.index) for d in ind.values()]))
    day = day or all_dates[-1]
    if day not in all_dates:
        print(f"{day} 无数据")
        return None
    st = load_state()
    if st["last_date"] and day <= st["last_date"]:
        print(f"{day} 已处理（最后处理 {st['last_date']}），跳过")
        return None
    if day < st["start"]:
        print(f"{day} 早于起点 {st['start']}")
        return None
    pos, pending = st["positions"], st["pending"]
    events = []
    day_pnl = 0.0
    P = tb.P
    # 1) 开盘执行昨日指令
    for sym, act in list(pending.items()):
        if sym not in ind or day not in ind[sym].index:
            continue
        r = ind[sym].loc[day]
        o = float(r["open"])
        if act == "exit" and sym in pos:
            p = pos.pop(sym)
            ret = o / p["last_close"] - 1
            pnl = p["w"] * ret - p["w"] * P["COST_SIDE"]
            day_pnl += pnl
            p["pnl"] += pnl
            tr = close_trade(p, day, o, "到期")
            st["closed"].append(tr)
            events.append(f"⏹ {tr['name']} 持满 {p['bars']} 天开盘离场 {o:.2f}，本笔 {tr['ret_pct']:+.2f}%")
        elif act == "enter" and sym not in pos:
            atr = float(r["atr"])
            if math.isnan(atr) or atr <= 0:
                continue
            stop_dist = P["ATR_K"] * atr / o
            w = min(P["RISK_PCT"] / stop_dist, P["MAX_SYM"])
            sec = tb.SECTOR_OF.get(sym, "其他")
            sec_w = sum(q["w"] for s2, q in pos.items() if tb.SECTOR_OF.get(s2) == sec)
            gross = sum(q["w"] for q in pos.values())
            w = min(w, max(0.0, P["MAX_SECTOR"] - sec_w), max(0.0, P["MAX_GROSS"] - gross))
            if w < 0.005:
                events.append(f"✖ {SYMBOLS[sym][0]} 触及仓位上限，放弃")
                continue
            pos[sym] = {"sym": sym, "name": SYMBOLS[sym][0], "w": round(w, 4), "entry": o, "entry_date": day, "stop": o - P["ATR_K"] * atr,
                        "extreme": o, "bars": 0, "pnl": -w * P["COST_SIDE"], "last_close": o, "signal_date": pending.get(f"{sym}__sigdate", "")}
            day_pnl -= w * P["COST_SIDE"]
            events.append(f"▶ {SYMBOLS[sym][0]} 开盘做多 {o:.2f}，名义 {w * 100:.1f}%，初始止损 {pos[sym]['stop']:.2f}")
    pending.clear()
    # 2) 持仓：止损 / 盯市 / 到期
    for sym in list(pos.keys()):
        if sym not in ind or day not in ind[sym].index:
            continue
        r = ind[sym].loc[day]
        p = pos[sym]
        o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
        pc = p["last_close"]
        if l <= p["stop"]:
            px = p["stop"] if o > p["stop"] else o
            pnl = p["w"] * (px / pc - 1) - p["w"] * P["COST_SIDE"]
            day_pnl += pnl
            p["pnl"] += pnl
            tr = close_trade(p, day, px, "止损")
            st["closed"].append(tr)
            pos.pop(sym)
            events.append(f"⛔ {tr['name']} 触发止损 {px:.2f}，本笔 {tr['ret_pct']:+.2f}%")
            continue
        day_pnl += p["w"] * (c / pc - 1)
        p["pnl"] += p["w"] * (c / pc - 1)
        p["last_close"] = c
        p["bars"] += 1
        if c > p["extreme"]:
            p["extreme"] = c
        p["stop"] = max(p["stop"], p["extreme"] - P["ATR_K"] * float(r["atr"]))
        p["cur_ret_pct"] = round((c / p["entry"] - 1) * 100, 2)
        if p["bars"] >= P["HOLD_DAYS"]:
            pending[sym] = "exit"
            events.append(f"⏰ {p['name']} 已持 {p['bars']} 天，明日开盘离场")
    # 3) 新信号 → 明日开盘进场
    signals_today, watch = [], []
    for sym, d in ind.items():
        if day not in d.index:
            continue
        r = d.loc[day]
        if sym in pos or sym in pending:
            continue
        if int(r[f"sig_{SIGNAL}"]) == 1:
            pending[sym] = "enter"
            pending[f"{sym}__sigdate"] = day
            signals_today.append(sym)
            events.append(f"🔔 {SYMBOLS[sym][0]} 超跌后出现确认（增仓·放量·破5日高·MACD红），明日开盘买入")
        # 观察池：当前仍处于超跌状态（60 日收益 ≤ 自身历史最低 10% 分位）、尚未出现确认
        r60s = d["close"].pct_change(60)
        thr = r60s.expanding(min_periods=250).quantile(P["OS_Q"]).shift()
        v, t = r60s.loc[day], thr.loc[day]
        if not (math.isnan(v) or math.isnan(t)) and v <= t:
            watch.append({"sym": sym, "name": SYMBOLS[sym][0], "r60": round(v * 100, 1), "thr": round(t * 100, 1)})
    st["pending"] = pending
    st["equity"] = round(st["equity"] * (1 + day_pnl), 6)
    gross = round(sum(q["w"] for q in pos.values()), 3)
    st["curve"].append([day, st["equity"], len(pos), gross])
    st["last_date"] = day
    save_state(st)
    rec = {"day": day, "equity": st["equity"], "day_pnl_pct": round(day_pnl * 100, 3), "positions": list(pos.values()), "pending": {k: v for k, v in pending.items() if "__" not in k},
           "signals": signals_today, "watch": watch, "events": events, "run_at": now_cn().strftime("%Y-%m-%d %H:%M")}
    (OUT / "daily").mkdir(parents=True, exist_ok=True)
    (OUT / "daily" / f"{day}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    msg = fmt_msg(rec, st)
    print(msg)
    if push and (events or signals_today):
        try:
            import notify
            print(notify.send_mail(f"【跌够久实盘·{day}】{len(signals_today)} 个新信号，{len(pos)} 个持仓", msg))
            print(notify.send_wechat(f"跌够久实盘 {day}", msg))
        except Exception as e:
            print(f"推送失败：{e}")
    return rec


def snapshot(ind=None):
    """只读：最新一天的超跌观察池与当日确认信号（不改状态，供网页在尚无记录时展示）"""
    ind = ind or build_ind()
    P = tb.P
    day = max(d.index.max() for d in ind.values())
    watch, confirmed = [], []
    for sym, d in ind.items():
        if day not in d.index:
            continue
        r60s = d["close"].pct_change(60)
        thr = r60s.expanding(min_periods=250).quantile(P["OS_Q"]).shift()
        v, t = r60s.loc[day], thr.loc[day]
        if not (math.isnan(v) or math.isnan(t)) and v <= t:
            watch.append({"sym": sym, "name": SYMBOLS[sym][0], "r60": round(v * 100, 1), "thr": round(t * 100, 1), "close": float(d.loc[day, "close"])})
        if int(d.loc[day, f"sig_{SIGNAL}"]) == 1:
            confirmed.append({"sym": sym, "name": SYMBOLS[sym][0], "close": float(d.loc[day, "close"])})
    watch.sort(key=lambda w: w["r60"])
    return {"day": day, "watch": watch, "confirmed": confirmed}


def close_trade(p, day, px, why):
    return {"sym": p["sym"], "name": p["name"], "entry_date": p["entry_date"], "exit_date": day, "entry": round(p["entry"], 2), "exit": round(px, 2),
            "ret_pct": round((px / p["entry"] - 1) * 100, 2), "pnl_pct": round(p["pnl"] * 100, 3), "w": p["w"], "bars": p["bars"], "why": why}


def fmt_msg(rec, st):
    lines = [f"【跌够久·超跌反转 纸面实盘】{rec['day']}", f"净值 {st['equity']:.4f}（今日 {rec['day_pnl_pct']:+.2f}%）｜持仓 {len(rec['positions'])} 个，名义 {sum(p['w'] for p in rec['positions']) * 100:.0f}%"]
    if rec["events"]:
        lines += ["", "今日动作："] + rec["events"]
    if rec["positions"]:
        lines += ["", "持仓："] + [f"  {p['name']} 多 {p['entry']:.2f}→{p['last_close']:.2f} {p.get('cur_ret_pct', 0):+.2f}%，第 {p['bars']}/60 天，止损 {p['stop']:.2f}" for p in rec["positions"]]
    if rec["watch"]:
        lines += ["", "超跌观察池（等确认）：" + "、".join(f"{w['name']}({w['r60']}%)" for w in rec["watch"][:12])]
    closed = st["closed"]
    if closed:
        wins = sum(1 for t in closed if t["pnl_pct"] > 0)
        lines += ["", f"累计已平 {len(closed)} 笔，胜 {wins}，净值 {st['equity']:.4f}"]
    lines.append("规则已封存：超跌(60日跌幅≤自身历史最低10%)→增仓+放量+破5日高+MACD红→次日开盘买，持60日，止损6ATR。纸面记录，非投资建议。")
    lines.append("页面：https://jayson8199.github.io/futures-signals/oversold.html")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "status", "catchup"])
    ap.add_argument("--date")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()
    if args.cmd == "status":
        st = load_state()
        print(json.dumps({k: v for k, v in st.items() if k not in ("curve", "closed")}, ensure_ascii=False, indent=1))
        return
    if args.cmd == "catchup":
        # 从 start 到最新，按日依次处理（用于补跑漏掉的日子）
        ind = build_ind()
        dates = sorted(set().union(*[set(df.index) for df in ind.values()]))
        st = load_state()
        for d in dates:
            if d >= st["start"] and (not st["last_date"] or d > st["last_date"]):
                run(d, push=False, ind=ind)
                st = load_state()
        return
    run(args.date, push=not args.no_push)


if __name__ == "__main__":
    main()
