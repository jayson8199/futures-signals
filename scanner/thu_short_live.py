#!/usr/bin/env python3
"""
「周四做空」纸面实盘（2026-11-01 与用户确认，从 2026-11-04 周三开始）

依据：2026 年上证/沪深300 周四、周五明显偏弱（见 experiments/thu_short_variants_2026.json）。
      规则是从 2026 年数据里挑出来的（样本内），纸面实盘的意义就是看它在没被挑过的未来是否还成立；用户计划 2027 年按实盘结果再调整。

每周三收盘开、周五收盘平，每条腿各记一手：
  A. 期货 IF：IF 主力连续收盘价开空 → 周五收盘价平仓
     成本 = 开仓 万0.23 + 平昨 万0.23 + 每边 1 跳(0.2 点)；乘数 300
     若周三到周五之间主力换月（升贴水跳变 >0.5%），平仓盈亏改按沪深300指数同期涨跌折算
     止损：浮亏达到一手保证金（按 12%）的 50%，即 IF 比开仓价上涨 6%，按该价 + 1 跳止损（周四、周五日最高价判断）
  B. 期权 IO（沪深300）、C. 期权 HO（上证50）：周三收盘买入平值认沽 → 周五收盘卖出
     合约 = 标的指数周三收盘价最近的行权价（2500–5000 点区间 50 点一档）；到期月取当月，若本周五就是到期日（每月第三个周五）则取次月
     价格优先用新浪真实日收盘价，拿不到时用 Black-Scholes 估算（隐波 = 前 20 日实际波动 ×1.1），记录里标明来源
     成本 = 每边 1 跳(0.2 点) + 手续费 15 元；乘数 100
     止损：周四、周五任一天该认沽的最低价 ≤ 买入价 × 50%，按 买入价×50% − 1 跳 卖出（拿不到最低价时用指数最高价按公式估算）
节假日：周三休市则本周不做；周五休市则在周五前最后一个交易日收盘平仓（周一兜底运行）。
预告：周三 14:50 前后由 Claude 定时任务触发 thu-short-live.yml 的 preview，按实时点位微信推送"本周拟买合约"，供真实下单的人收盘前操作；纸面记账仍以收盘价为准。
状态：data/thu_short/state.json；逐笔 data/thu_short/trades.json
用法：python scanner/thu_short_live.py auto|preview|probe [--date YYYY-MM-DD] [--no-push]
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
SITE = "https://jayson8199.github.io/futures-signals/"

FEE, TICK, MULT = 0.000023, 0.2, 300
MARGIN, STOP = 0.12, 0.5
FUT_STOP_PCT = STOP * MARGIN
OTICK, OMULT, OFEE, KSTEP, R = 0.2, 100, 15, 50, 0.015
OPTS = {  # 腿名: (中文名, 标的指数代码, 新浪合约前缀, akshare 日线函数名, 实时函数名)
    "IO": ("沪深300", "sh000300", "io", "option_cffex_hs300_daily_sina", "option_cffex_hs300_spot_sina"),
    "HO": ("上证50", "sh000016", "ho", "option_cffex_sz50_daily_sina", "option_cffex_sz50_spot_sina"),
}
LEG_TAG = {"IF": "A", "IO": "B", "HO": "C"}


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


def idx_daily(code):
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol=code)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df.set_index("date").iloc[-80:]


_OPT_CACHE = {}


def opt_bars(leg, code):
    if code not in _OPT_CACHE:
        try:
            import akshare as ak
            df = getattr(ak, OPTS[leg][3])(symbol=code)
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            _OPT_CACHE[code] = df.set_index("date")
        except Exception as e:
            print(f"[期权行情] {code} 获取失败：{type(e).__name__} {str(e)[:120]}")
            _OPT_CACHE[code] = None
    return _OPT_CACHE[code]


def opt_px(leg, code, day, col="close"):
    df = opt_bars(leg, code)
    if df is not None and day in df.index and col in df.columns:
        return float(df.loc[day, col])
    return None


# ---------------- 合约与定价 ----------------
def third_friday(y, m):
    d = date(y, m, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def pick_expiry(fri: date):
    e = third_friday(fri.year, fri.month)
    if e <= fri + timedelta(days=4):
        y, m = (fri.year + (fri.month == 12), fri.month % 12 + 1)
        e = third_friday(y, m)
    return e


def contract(leg, S, wed: date):
    fri = wed + timedelta(days=2)
    exp = pick_expiry(fri)
    K = int(round(S / KSTEP) * KSTEP)
    return exp, K, f"{OPTS[leg][2]}{exp.strftime('%y%m')}P{K}", f"{leg}{exp.strftime('%y%m')}-P-{K}"


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
    (OUT / "trades.json").write_text(json.dumps(st["trades"], ensure_ascii=False, indent=1), encoding="utf-8")


LEGS = ["IF"] + list(OPTS)


def summary(st):
    t = st["trades"]
    s = {"笔数": len(t)}
    for leg in LEGS:
        xs = [x["legs"][leg]["pnl"] for x in t if leg in x.get("legs", {})]
        cum, peak, mdd = 0, 0, 0
        for x in xs:
            cum += x
            peak = max(peak, cum)
            mdd = min(mdd, cum - peak)
        s[leg] = {"笔数": len(xs), "累计元": round(sum(xs)), "赚钱笔数": sum(1 for x in xs if x > 0), "最大回撤元": round(mdd), "单笔最亏元": round(min(xs)) if xs else 0}
    return s


# ---------------- 开 / 平 ----------------
def do_open(day, F, IX, st):
    wed = pd.Timestamp(day).date()
    o = {"open_date": day, "opened_at": now_cn().strftime("%Y-%m-%d %H:%M"), "legs": {}}
    fpx = float(F.loc[day, "close"])
    o["legs"]["IF"] = {"name": "IF 沪深300 期货", "open": fpx, "idx_open": float(IX["IO"].loc[day, "close"]), "stop": round(fpx * (1 + FUT_STOP_PCT), 1)}
    lines = [f"【周四做空·纸面实盘】{day}（周三）收盘开仓",
             f"A 期货：IF 主力 {fpx:.1f} 开空 1 手，止损价 {o['legs']['IF']['stop']:.1f}（亏掉一手保证金的一半）"]
    for leg, (cn, *_r) in OPTS.items():
        I = IX[leg]
        S = float(I.loc[day, "close"])
        exp, K, code, ex_code = contract(leg, S, wed)
        real = opt_px(leg, code, day)
        rv = I["close"].pct_change().iloc[-21:-1].std() * math.sqrt(242)
        iv = float(rv) * 1.1
        p0 = real if real is not None else round(bs_put(S, K, ((exp - wed).days) / 365, iv), 1)
        o["legs"][leg] = {"name": f"{leg} {cn}平值认沽", "code": code, "ex_code": ex_code, "K": K, "expiry": exp.isoformat(), "idx_open": S, "iv_model": round(iv, 4),
                          "open": p0, "src_open": "新浪收盘价" if real is not None else "公式估算", "stop": round(p0 * (1 - STOP), 1)}
        lines.append(f"{LEG_TAG[leg]} 期权：买入 {ex_code}（{cn}收盘 {S:.2f}）1 手，权利金 {p0:.1f} 点 = {p0 * OMULT:,.0f} 元（{o['legs'][leg]['src_open']}），止损价 {o['legs'][leg]['stop']:.1f}")
    lines.append(f"周五收盘平仓。纸面记录，非投资建议。{SITE}thushort.html")
    st["open"] = o
    return "\n".join(lines)


def do_close(day, F, IX, st):
    o = st["open"]
    res = {"open_date": o["open_date"], "close_date": day, "closed_at": now_cn().strftime("%Y-%m-%d %H:%M"), "legs": {}}
    lines = [f"【周四做空·纸面实盘】{day} 收盘平仓"]
    a = o["legs"]["IF"]
    S0, S1 = a["idx_open"], float(IX["IO"].loc[day, "close"])
    fpx = float(F.loc[day, "close"])
    roll = abs((fpx / S1 - 1) - (a["open"] / S0 - 1)) > 0.005
    move = (S1 / S0 - 1) * a["open"] if roll else fpx - a["open"]
    stop_day = None
    for d in [x for x in F.index if o["open_date"] < x <= day]:
        if "high" in F.columns and float(F.loc[d, "high"]) >= a["stop"]:
            stop_day, fpx = d, a["stop"] + TICK
            move = fpx - a["open"]
            break
    pnl = (-move - a["open"] * FEE * 2 - 2 * TICK) * MULT
    res["legs"]["IF"] = {**a, "close": round(fpx, 1), "idx_close": S1, "roll_fix": roll, "stop_day": stop_day, "pnl": round(pnl), "ret_pct": round(-move / a["open"] * 100, 2)}
    lines.append(f"A 期货 IF：{a['open']:.1f} → {fpx:.1f}{'（触发止损）' if stop_day else '（换月，按指数折算）' if roll else ''}，本笔 {pnl:+,.0f} 元")
    for leg, (cn, *_r) in OPTS.items():
        b = o["legs"][leg]
        I = IX[leg]
        exp = date.fromisoformat(b["expiry"])
        S1 = float(I.loc[day, "close"])
        real = opt_px(leg, b["code"], day)
        p1 = real if real is not None else round(bs_put(S1, b["K"], ((exp - pd.Timestamp(day).date()).days) / 365, b["iv_model"]), 1)
        src = "新浪收盘价" if real is not None else "公式估算"
        sd = None
        for d in [x for x in I.index if o["open_date"] < x <= day]:
            lo = opt_px(leg, b["code"], d, "low")
            lsrc = "新浪最低价"
            if lo is None:
                lo = bs_put(float(I.loc[d, "high"]), b["K"], ((exp - pd.Timestamp(d).date()).days) / 365, b["iv_model"])
                lsrc = "公式估算"
            if lo <= b["stop"]:
                sd, p1, src = d, round(b["stop"] - OTICK, 1), f"止损（{d[5:]} {lsrc} {lo:.1f}）"
                break
        pnl = ((p1 if sd else p1 - OTICK) - (b["open"] + OTICK)) * OMULT - OFEE * 2
        res["legs"][leg] = {**b, "close": p1, "src_close": src, "stop_day": sd, "idx_close": S1, "idx_ret_pct": round((S1 / b["idx_open"] - 1) * 100, 2),
                            "pnl": round(pnl), "ret_pct": round(pnl / (b["open"] * OMULT) * 100, 1)}
        lines.append(f"{LEG_TAG[leg]} 期权 {b['ex_code']}：{b['open']:.1f} → {p1:.1f}{'（触发 50% 止损）' if sd else ''}，本笔 {pnl:+,.0f} 元（{res['legs'][leg]['ret_pct']:+.0f}%，{src}）｜{cn} {b['idx_open']:.2f} → {S1:.2f}")
    st["trades"].append(res)
    st["open"] = None
    s = summary(st)
    lines.append("累计 " + "；".join(f"{k} {s[k]['累计元']:+,} 元（赚 {s[k]['赚钱笔数']}/{s[k]['笔数']}）" for k in LEGS))
    lines.append(f"纸面记录，非投资建议。{SITE}thushort.html")
    return "\n".join(lines)


def push(msg):
    try:
        import notify
        print(notify.send_mail(msg.split("\n")[0], msg))
        print(notify.send_wechat(msg.split("\n")[0], msg))
    except Exception as e:
        print(f"推送失败：{e}")


def auto(day=None, push_msg=True):
    st = load_state()
    F = fut_daily()
    IX = {leg: idx_daily(v[1]) for leg, v in OPTS.items()}
    today = day or now_cn().strftime("%Y-%m-%d")
    if today < st["start"]:
        print(f"{today} 早于起点 {st['start']}，不操作")
        return
    have = today in F.index and all(today in IX[k].index for k in IX)
    wd = pd.Timestamp(today).weekday()
    msg = None
    if st["open"]:
        fri = (pd.Timestamp(st["open"]["open_date"]) + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        if have and today == fri:
            msg = do_close(today, F, IX, st)
        elif today > fri:
            last = [d for d in F.index if st["open"]["open_date"] < d <= fri and all(d in IX[k].index for k in IX)]
            if last:
                msg = do_close(last[-1], F, IX, st)
        else:
            print(f"持仓中（{st['open']['open_date']} 开），等 {fri} 收盘平仓")
    elif wd == 2 and have and not any(t["open_date"] == today for t in st["trades"]):
        msg = do_open(today, F, IX, st)
    else:
        print(f"{today} 无操作（周{'一二三四五六日'[wd]}，当日数据{'已' if have else '未'}到）")
    if msg:
        save_state(st)
        print(msg)
        if push_msg:
            push(msg)


def preview(push_msg=True, force=False):
    """周三盘中预告：按实时点位推送本周拟买合约（供真实下单参考；纸面记账以收盘价为准）"""
    import akshare as ak
    today = now_cn()
    if not force and (today.weekday() != 2 or today.strftime("%Y-%m-%d") < START):
        print("非周三或未到起点，不预告")
        return
    spot = ak.stock_zh_index_spot_sina()
    wed = today.date() + timedelta(days=(2 - today.weekday()) % 7)
    lines = [f"【周四做空·预告】{today.strftime('%m-%d %H:%M')} 按实时点位，今天收盘前拟开仓："]
    for leg, (cn, icode, pre, _d, spot_fn) in OPTS.items():
        row = spot[spot["代码"] == icode]
        if row.empty:
            lines.append(f"{cn}：实时点位没取到")
            continue
        S = float(row["最新价"].iloc[0])
        exp, K, code, ex_code = contract(leg, S, wed)
        px = ""
        try:
            t = getattr(ak, spot_fn)(symbol=f"{pre}{exp.strftime('%y%m')}")
            r = t[t["行权价"].astype(float) == K]
            if not r.empty:
                px = f"，认沽最新价 {float(r['看跌合约-最新价'].iloc[0]):.1f}（一手约 {float(r['看跌合约-最新价'].iloc[0]) * OMULT:,.0f} 元，止损价约 {float(r['看跌合约-最新价'].iloc[0]) * (1 - STOP):.1f}）"
        except Exception as e:
            print(f"实时期权报价失败：{e}")
        lines.append(f"{LEG_TAG[leg]} {cn} 现在 {S:.2f} → 买 {ex_code}{px}")
    lines.append("A IF 主力收盘前开空 1 手，止损约开仓价 +6%。")
    lines.append("收盘前最后几分钟点位变动，行权价可能差一档，按下单时最近的行权价即可；止损可在券商 App 设条件单。纸面记账以收盘价为准，非投资建议。")
    msg = "\n".join(lines)
    print(msg)
    if push_msg:
        push(msg)


def probe():
    import akshare as ak
    print("akshare", ak.__version__)
    for leg, (cn, icode, pre, dfn, sfn) in OPTS.items():
        I = idx_daily(icode)
        day = I.index[-1]
        S = float(I.loc[day, "close"])
        exp, K, code, ex = contract(leg, S, (pd.Timestamp(day) - pd.Timedelta(days=2)).date())
        for k in (K - 50, K, K + 50):
            c = f"{pre}{exp.strftime('%y%m')}P{k}"
            print(leg, c, "close", opt_px(leg, c, day), "low", opt_px(leg, c, day, "low"))
        try:
            t = getattr(ak, sfn)(symbol=f"{pre}{exp.strftime('%y%m')}")
            print(leg, "实时报价列", list(t.columns), len(t))
        except Exception as e:
            print(leg, "实时报价失败", e)
    try:
        sp = ak.stock_zh_index_spot_sina()
        print("指数实时", sp[sp["代码"].isin(["sh000300", "sh000016"])][["代码", "名称", "最新价"]].to_dict("records"))
    except Exception as e:
        print("指数实时失败", e)
    try:
        preview(push_msg=False, force=True)
    except Exception as e:
        print("预告试跑失败", e)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["auto", "preview", "probe"])
    ap.add_argument("--date")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()
    if a.cmd == "probe":
        probe()
    elif a.cmd == "preview":
        preview(not a.no_push)
    else:
        auto(a.date, not a.no_push)
