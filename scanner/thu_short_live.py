#!/usr/bin/env python3
"""
「周四做空」纸面实盘（2026-11-01 与用户确认，从 2026-11-04 周三开始）

依据：2026 年上证/沪深300 周四、周五明显偏弱（见 experiments/thu_short_variants_2026.json）。
      规则是从 2026 年数据里挑出来的（样本内），纸面实盘的意义就是看它在没被挑过的未来是否还成立；用户计划 2027 年按实盘结果再调整。

两条腿，各记一手：
  A. 期货：IF 主力连续，周三收盘价开空 → 周五收盘价平仓
     成本 = 开仓 万0.23 + 平昨 万0.23 + 每边 1 跳(0.2 点)；乘数 300
     若周三到周五之间主力换月（升贴水跳变 >0.5%），平仓盈亏改按沪深300指数同期涨跌折算
  B. 期权：沪深300股指期权 IO，周三收盘买入平值认沽 → 周五收盘卖出
     合约 = 周三沪深300收盘价就近的行权价（50 点一档）；到期月取当月，若本周就是到期周则取次月
     价格优先用新浪的真实日收盘价；拿不到时用 Black-Scholes 估算（隐波 = 前 20 日实际波动 ×1.1），记录里标明来源
     成本 = 每边 1 跳(0.2 点) + 手续费 15 元；乘数 100
节假日：周三休市则本周不做；周五休市则在周五前最后一个交易日收盘平仓。
状态：data/thu_short/state.json；每笔记录 data/thu_short/trades.json
用法：python scanner/thu_short_live.py auto [--date YYYY-MM-DD] [--no-push]
      python scanner/thu_short_live.py probe        # 探测数据源
"""
import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scanner"))
OUT = ROOT / "data" / "thu_short"
CN = timezone(timedelta(hours=8))
START = "2026-11-04"
FEE, TICK, MULT = 0.000023, 0.2, 300
OTICK, OMULT, OFEE, KSTEP, R = 0.2, 100, 15, 50, 0.015
SITE = "https://jayson8199.github.io/futures-signals/"


def now_cn():
    return datetime.now(CN)


# ---------------- 数据 ----------------
def fut_daily():
    import akshare as ak
    end = now_cn().strftime("%Y%m%d")
    start = (now_cn() - timedelta(days=40)).strftime("%Y%m%d")
    df = ak.futures_main_sina(symbol="IF0", start_date=start, end_date=end)
    df = df.rename(columns={"日期": "date", "开盘价": "open", "最高价": "high", "最低价": "low", "收盘价": "close"})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df.set_index("date")


def idx_daily():
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol="sh000300")
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df.set_index("date").iloc[-80:]


def opt_code(expiry: date, K: int):
    return f"io{expiry.strftime('%y%m')}P{K}"


def opt_close(code, day):
    """真实日收盘价（新浪）；失败返回 None"""
    try:
        import akshare as ak
        df = ak.option_cffex_hs300_daily_sina(symbol=code)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df.set_index("date")
        if day in df.index:
            return float(df.loc[day, "close"])
    except Exception as e:
        print(f"[期权行情] {code} 获取失败：{type(e).__name__} {str(e)[:120]}")
    return None


# ---------------- 定价兜底 ----------------
def third_friday(y, m):
    d = date(y, m, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def pick_expiry(fri: date):
    e = third_friday(fri.year, fri.month)
    if e <= fri + timedelta(days=4):
        y, m = (fri.year + (fri.month == 12), fri.month % 12 + 1)
        e = third_friday(y, m)
    return e


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_put(S, K, T, v):
    if T <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (R + v * v / 2) * T) / (v * math.sqrt(T))
    return K * math.exp(-R * T) * ncdf(-(d1 - v * math.sqrt(T))) - S * ncdf(-d1)


# ---------------- 状态 ----------------
def load_state():
    f = OUT / "state.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"start": START, "open": None, "trades": []}


def save_state(st):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def summary(st):
    t = st["trades"]
    s = {"笔数": len(t)}
    for leg, key in (("期货", "fut_pnl"), ("期权", "opt_pnl")):
        xs = [x[key] for x in t if x.get(key) is not None]
        cum, peak, mdd = 0, 0, 0
        for x in xs:
            cum += x
            peak = max(peak, cum)
            mdd = min(mdd, cum - peak)
        s[leg] = {"累计元": round(sum(xs)), "赚钱笔数": sum(1 for x in xs if x > 0), "最大回撤元": round(mdd), "单笔最亏元": round(min(xs)) if xs else 0}
    return s


# ---------------- 开 / 平 ----------------
def do_open(day, F, I, st):
    S = float(I.loc[day, "close"])
    fpx = float(F.loc[day, "close"])
    fri = (pd.Timestamp(day) + pd.Timedelta(days=2)).date()
    exp = pick_expiry(fri)
    K = int(round(S / KSTEP) * KSTEP)
    code = opt_code(exp, K)
    real = opt_close(code, day)
    rv = I["close"].pct_change().iloc[-21:-1].std() * math.sqrt(242)
    iv = float(rv) * 1.1
    T0 = ((exp - pd.Timestamp(day).date()).days) / 365
    model = bs_put(S, K, T0, iv)
    st["open"] = {"open_date": day, "fut_open": fpx, "idx_open": S, "opt_code": code, "K": K, "expiry": exp.isoformat(), "iv_model": round(iv, 4),
                  "opt_open": real if real is not None else round(model, 1), "opt_src_open": "新浪收盘价" if real is not None else "公式估算",
                  "opened_at": now_cn().strftime("%Y-%m-%d %H:%M")}
    o = st["open"]
    msg = (f"【周四做空·纸面实盘】{day}（周三）收盘开仓\n"
           f"A 期货：IF 主力 {fpx:.1f} 开空 1 手（周五收盘平仓）\n"
           f"B 期权：买入 {code}（沪深300 平值认沽，行权价 {K}）1 手，权利金 {o['opt_open']:.1f} 点 = {o['opt_open'] * OMULT:.0f} 元（{o['opt_src_open']}）\n"
           f"沪深300 收盘 {S:.2f}\n纸面记录，非投资建议。{SITE}thushort.html")
    return msg


def do_close(day, F, I, st):
    o = st["open"]
    fpx = float(F.loc[day, "close"])
    S1 = float(I.loc[day, "close"])
    b0 = o["fut_open"] / o["idx_open"] - 1
    b1 = fpx / S1 - 1
    roll = abs(b1 - b0) > 0.005
    move = (S1 / o["idx_open"] - 1) * o["fut_open"] if roll else fpx - o["fut_open"]
    fut_pnl = (-move - o["fut_open"] * FEE * 2 - 2 * TICK) * MULT
    real = opt_close(o["opt_code"], day)
    exp = date.fromisoformat(o["expiry"])
    T1 = ((exp - pd.Timestamp(day).date()).days) / 365
    p1 = real if real is not None else round(bs_put(S1, o["K"], T1, o["iv_model"]), 1)
    src = "新浪收盘价" if real is not None else "公式估算"
    opt_pnl = ((p1 - OTICK) - (o["opt_open"] + OTICK)) * OMULT - OFEE * 2
    tr = {**o, "close_date": day, "fut_close": fpx, "idx_close": S1, "roll_fix": roll, "fut_pnl": round(fut_pnl), "fut_ret_pct": round(-move / o["fut_open"] * 100, 2),
          "opt_close": p1, "opt_src_close": src, "opt_pnl": round(opt_pnl), "opt_ret_pct": round(opt_pnl / (o["opt_open"] * OMULT) * 100, 1),
          "idx_ret_pct": round((S1 / o["idx_open"] - 1) * 100, 2), "closed_at": now_cn().strftime("%Y-%m-%d %H:%M")}
    st["trades"].append(tr)
    st["open"] = None
    s = summary(st)
    msg = (f"【周四做空·纸面实盘】{day} 收盘平仓\n"
           f"沪深300 {o['idx_open']:.2f} → {S1:.2f}（{tr['idx_ret_pct']:+.2f}%）\n"
           f"A 期货：{o['fut_open']:.1f} → {fpx:.1f}，本笔 {'+' if fut_pnl >= 0 else ''}{fut_pnl:,.0f} 元{'（换月，按指数折算）' if roll else ''}\n"
           f"B 期权：{o['opt_code']} {o['opt_open']:.1f} → {p1:.1f}，本笔 {'+' if opt_pnl >= 0 else ''}{opt_pnl:,.0f} 元（{tr['opt_ret_pct']:+.1f}%，{src}）\n"
           f"累计 {s['笔数']} 笔：期货 {s['期货']['累计元']:+,} 元（赚 {s['期货']['赚钱笔数']} 笔），期权 {s['期权']['累计元']:+,} 元（赚 {s['期权']['赚钱笔数']} 笔）\n"
           f"纸面记录，非投资建议。{SITE}thushort.html")
    return msg


def auto(day=None, push=True):
    st = load_state()
    F, I = fut_daily(), idx_daily()
    today = day or now_cn().strftime("%Y-%m-%d")
    if today < st["start"]:
        print(f"{today} 早于起点 {st['start']}，不操作")
        return
    have = today in F.index and today in I.index
    wd = pd.Timestamp(today).weekday()
    msg = None
    if st["open"]:
        # 有持仓：周五收盘平；若周五休市，则在下一次运行时用周五前最后一个交易日平
        od = pd.Timestamp(st["open"]["open_date"])
        fri = (od + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        if have and today == fri:
            msg = do_close(today, F, I, st)
        elif today > fri:
            last = [d for d in F.index if st["open"]["open_date"] < d <= fri and d in I.index]
            if last:
                msg = do_close(last[-1], F, I, st)
        else:
            print(f"持仓中（{st['open']['open_date']} 开），等 {fri} 收盘平仓")
    elif wd == 2 and have and not any(t["open_date"] == today for t in st["trades"]):
        msg = do_open(today, F, I, st)
    else:
        print(f"{today} 无操作（周{'一二三四五六日'[wd]}，当日数据{'已' if have else '未'}到）")
    if msg:
        save_state(st)
        (OUT / "trades.json").write_text(json.dumps(st["trades"], ensure_ascii=False, indent=1), encoding="utf-8")
        print(msg)
        if push:
            try:
                import notify
                print(notify.send_mail(msg.split("\n")[0], msg))
                print(notify.send_wechat(msg.split("\n")[0], msg))
            except Exception as e:
                print(f"推送失败：{e}")


def probe():
    import akshare as ak
    print("akshare", ak.__version__)
    print([f for f in dir(ak) if "option_cffex" in f])
    F, I = fut_daily(), idx_daily()
    print("IF0", F.tail(3).to_dict("index"))
    print("沪深300", I.tail(3)[["open", "close"]].to_dict("index"))
    day = I.index[-1]
    S = float(I.loc[day, "close"])
    fri = (pd.Timestamp(day) + pd.Timedelta(days=2)).date()
    for exp in (pick_expiry(fri), third_friday(fri.year, fri.month)):
        K = int(round(S / KSTEP) * KSTEP)
        for k in (K - 50, K, K + 50):
            code = opt_code(exp, k)
            print(code, opt_close(code, day))
    try:
        lst = ak.option_cffex_hs300_list_sina()
        print("合约列表样例", str(lst)[:400])
    except Exception as e:
        print("合约列表失败", e)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["auto", "probe"])
    ap.add_argument("--date")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()
    if a.cmd == "probe":
        probe()
    else:
        auto(a.date, push=not a.no_push)
