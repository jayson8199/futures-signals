#!/usr/bin/env python3
"""
「二区定律」前瞻实盘记录（上证指数）
三个阶段，每个交易日各跑一次（GitHub 定时 + 备用触发，晚到也没关系：判定只用截止时刻之前的 K 线）：
  judge  ≥10:30 后：用 10:00-10:30 的 5 分钟 K 线判好/坏二区，给出预测（不会跌/不会涨），记录时间戳
  fix    ≥13:35 后：五区(13:00-13:35，比课程多看 5 分钟)是否创 9:30 以来新高/新低 → 修正
  settle ≥15:00 后：用官方开盘/收盘判对错，更新累计
对照组同时记录：A) 10:30 价相对开盘  B) 13:30 价相对开盘  C) 永远"不会跌"
数据：新浪 5 分钟（akshare stock_zh_a_minute），官方开收盘：新浪日线（stock_zh_index_daily），均不需密钥
记录：data/erqu/<date>.json；汇总由 build_site 读取
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "erqu"
CN = ZoneInfo("Asia/Shanghai")
Z5_END = "13:35"  # 五区观察窗口结束（课程口径 13:30，用户要求多看 5 分钟）


def now_cn():
    return datetime.now(CN)


def fetch_5min_today(day: str) -> pd.DataFrame:
    import akshare as ak
    df = ak.stock_zh_a_minute(symbol="sh000001", period="5", adjust="")
    df = df.rename(columns={"day": "time"})
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype(float)
    df = df[df["time"].str[:10] == day].copy()
    df["hm"] = df["time"].str[11:16]
    return df.sort_values("time").reset_index(drop=True)


def fetch_official_daily(day: str):
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol="sh000001")
    df["date"] = df["date"].astype(str)
    r = df[df["date"] == day]
    if r.empty:
        return None
    r = r.iloc[0]
    return float(r["open"]), float(r["close"])


def classify_z2(d: pd.DataFrame):
    z2 = d[(d["hm"] > "10:00") & (d["hm"] <= "10:30")]
    if len(z2) < 6:
        return None, "二区 K 线不足 6 根"
    a, b = z2.iloc[:3], z2.iloc[3:]
    hh, hl = b["high"].max() > a["high"].max(), b["low"].min() > a["low"].min()
    lh, ll = b["high"].max() < a["high"].max(), b["low"].min() < a["low"].min()
    if hh and hl:
        return "好", "后半段高点、低点均抬高"
    if lh and ll:
        return "坏", "后半段高点、低点均走低"
    loose = "好" if z2.iloc[-1]["close"] > z2.iloc[0]["open"] else ("坏" if z2.iloc[-1]["close"] < z2.iloc[0]["open"] else None)
    return loose, "形态模糊，按 10:30 收 vs 10:00 开 判定" if loose else "形态模糊且 10:30 与 10:00 持平，不预测"


def bars_of(d: pd.DataFrame, upto: str):
    x = d[d["hm"] <= upto]
    return [[r["hm"], round(float(r["open"]), 2), round(float(r["high"]), 2), round(float(r["low"]), 2), round(float(r["close"]), 2)] for _, r in x.iterrows()]


def load(day):
    p = OUT / f"{day}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"day": day}


def save(rec):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{rec['day']}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")


def judge(day, force=False):
    rec = load(day)
    if rec.get("z2") and not force:
        print("今日已判定，跳过")
        return rec, False
    d = fetch_5min_today(day)
    if d.empty or d["hm"].max() < "10:30":
        print(f"数据未到 10:30（最新 {d['hm'].max() if not d.empty else '无'}），稍后再试")
        return rec, False
    z2, why = classify_z2(d)
    prov_open = float(d.iloc[0]["open"])
    at1030 = float(d[d["hm"] <= "10:30"].iloc[-1]["close"])
    rec.update({
        "z2": z2 or "无", "z2_reason": why,
        "prediction": {"好": "今天收盘不会跌破开盘", "坏": "今天收盘不会涨过开盘"}.get(z2, "不预测"),
        "open_provisional": prov_open, "price_1030": at1030,
        "baseline_1030": "好" if at1030 > prov_open else ("坏" if at1030 < prov_open else "平"),
        "judged_at": now_cn().strftime("%Y-%m-%d %H:%M"),
        "bars_used_until": "10:30",
        "bars": bars_of(d, "10:30"),
    })
    save(rec)
    return rec, True


def fix(day, force=False):
    rec = load(day)
    if not rec.get("z2"):
        print("尚未做二区判定，先执行 judge")
        return rec, False
    if "fixed" in rec and not force:
        print("今日已做五区检查，跳过")
        return rec, False
    d = fetch_5min_today(day)
    if d.empty or d["hm"].max() < Z5_END:
        print(f"数据未到 {Z5_END}，稍后再试")
        return rec, False
    upto = d[d["hm"] <= Z5_END]
    z5 = upto[upto["hm"] > "13:00"]
    before = upto[upto["hm"] <= "11:30"]
    new_low = bool(len(z5) and z5["low"].min() < before["low"].min())
    new_high = bool(len(z5) and z5["high"].max() > before["high"].max())
    final = rec["z2"]
    fixed = False
    if rec["z2"] == "好" and new_low:
        final, fixed = "坏", True
    elif rec["z2"] == "坏" and new_high:
        final, fixed = "好", True
    at1330 = float(upto.iloc[-1]["close"])
    rec.update({
        "z5_new_low": new_low, "z5_new_high": new_high, "fixed": fixed, "final": final,
        "prediction_final": {"好": "今天收盘不会跌破开盘", "坏": "今天收盘不会涨过开盘"}.get(final, "不预测"),
        "price_1330": at1330,
        "baseline_1330": "好" if at1330 > rec["open_provisional"] else ("坏" if at1330 < rec["open_provisional"] else "平"),
        "fixed_at": now_cn().strftime("%Y-%m-%d %H:%M"),
        "bars": bars_of(d, Z5_END),
        "z5_window": f"13:00-{Z5_END}",
    })
    save(rec)
    return rec, True


LOCK_COST_PCT = 0.027  # 虚拟仓位成本：IF/IH 开仓+收盘锁仓+次日双平（4 腿×万0.23）+4 次滑点，合计约 0.027%


def virtual_pnl(rec):
    """虚拟仓位：仅判「好」日 13:35 做多 1 份指数，收盘锁仓、次日平；判「坏」日空仓（做空仅作参考）。
    收益按 13:35 价 → 官方收盘价 计算，净值扣 LOCK_COST_PCT。"""
    e, c = rec.get("price_1330"), rec.get("close_official")
    if not e or not c or not rec.get("final"):
        return {}
    chg = (c / e - 1) * 100
    if rec["final"] == "好":
        gross = chg
        return {"trade": "多", "pnl_gross_pct": round(gross, 4), "pnl_net_pct": round(gross - LOCK_COST_PCT, 4), "short_ref_pct": None}
    return {"trade": "空仓", "pnl_gross_pct": 0.0, "pnl_net_pct": 0.0, "short_ref_pct": round(-chg - LOCK_COST_PCT, 4)}


def verdict(p, o, c):
    if p == "好":
        return c >= o
    if p == "坏":
        return c <= o
    return None


def settle(day, force=False):
    rec = load(day)
    if not rec.get("z2"):
        print("今日无判定记录")
        return rec, False
    if rec.get("settled") and not force:
        print("今日已结算，跳过")
        return rec, False
    od = fetch_official_daily(day)
    if not od:
        print("官方日线尚未更新，稍后再试")
        return rec, False
    o, c = od
    final = rec.get("final", rec["z2"])
    try:
        d = fetch_5min_today(day)
        if not d.empty:
            rec["bars"] = bars_of(d, "15:00")
    except Exception as e:
        print(f"[警告] 收盘 K 线未能保存：{e}")
    rec.update({
        "open_official": o, "close_official": c,
        "actual": "涨" if c > o else ("跌" if c < o else "平"),
        "correct_z2": verdict(rec["z2"], o, c),
        "correct_final": verdict(final, o, c),
        "correct_b1030": verdict(rec.get("baseline_1030"), o, c),
        "correct_b1330": verdict(rec.get("baseline_1330"), o, c) if rec.get("baseline_1330") else None,
        "correct_always_up": c >= o,
        "settled": True, "settled_at": now_cn().strftime("%Y-%m-%d %H:%M"),
    })
    rec.update(virtual_pnl(rec))
    save(rec)
    return rec, True


def summarize():
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(OUT.glob("????-??-??.json"))]
    done = [r for r in recs if r.get("settled")]

    def rate(key):
        v = [r[key] for r in done if r.get(key) is not None]
        return (round(sum(v) / len(v) * 100, 1), len(v)) if v else (None, 0)
    months = {}
    for r in done:
        m = months.setdefault(r["day"][:7], {"days": 0, "final_ok": 0, "final_bad": 0, "z2_ok": 0, "z2_bad": 0, "b1330_ok": 0, "b1030_ok": 0,
                                             "trades": 0, "trade_wins": 0, "pnl_net": 0.0, "pnl_gross": 0.0})
        m["days"] += 1
        if r.get("trade") == "多":
            m["trades"] += 1
            m["trade_wins"] += 1 if r["pnl_net_pct"] > 0 else 0
            m["pnl_net"] = round(m["pnl_net"] + r["pnl_net_pct"], 4)
            m["pnl_gross"] = round(m["pnl_gross"] + r["pnl_gross_pct"], 4)
        for k, ok, bad in (("correct_final", "final_ok", "final_bad"), ("correct_z2", "z2_ok", "z2_bad")):
            if r.get(k) is True:
                m[ok] += 1
            elif r.get(k) is False:
                m[bad] += 1
        m["b1330_ok"] += 1 if r.get("correct_b1330") else 0
        m["b1030_ok"] += 1 if r.get("correct_b1030") else 0
    trades = [r for r in done if r.get("trade") == "多"]
    curve, cum = [], 0.0
    for r in done:
        cum += r.get("pnl_net_pct", 0.0) or 0.0
        curve.append((r["day"], round(cum, 4)))
    peak, mdd = 0.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v - peak)
    pnl = {"trades": len(trades), "wins": sum(1 for r in trades if r["pnl_net_pct"] > 0),
           "net": round(sum(r["pnl_net_pct"] for r in trades), 4), "gross": round(sum(r["pnl_gross_pct"] for r in trades), 4),
           "max_dd": round(mdd, 4), "curve": curve, "cost": LOCK_COST_PCT}
    return {"days": len(done), "z2": rate("correct_z2"), "final": rate("correct_final"),
            "b1030": rate("correct_b1030"), "b1330": rate("correct_b1330"), "always_up": rate("correct_always_up"),
            "months": months, "pnl": pnl, "records": recs}


def push(title, body):
    sys.path.insert(0, str(ROOT / "scanner"))
    try:
        import notify
        print(notify.send_mail(title, body))
        print(notify.send_wechat(title, body))
    except Exception as e:
        print(f"推送失败：{e}")


def fmt_msg(rec, phase, site):
    s = summarize()
    cur = s["months"].get(rec["day"][:7])
    month_line = f"\n本月截至今天：{cur['days']} 天，对 {cur['final_ok']} 错 {cur['final_bad']}（二区+修正）；二区单独 对 {cur['z2_ok']} 错 {cur['z2_bad']}" if cur else ""
    tail = (f"\n{month_line}\n累计 {s['days']} 天：二区 {s['z2'][0]}% ｜ 二区+五区修正 {s['final'][0]}% ｜ "
            f"对照 10:30价位 {s['b1030'][0]}% ｜ 13:30价位 {s['b1330'][0]}%" if s["days"] else "")
    if phase == "judge":
        return (f"【二区定律·{rec['day']}】10:30 判定：{rec['z2']}二区（{rec['z2_reason']}）\n预测：{rec['prediction']}\n"
                f"开盘(暂) {rec['open_provisional']:.2f} → 10:30 {rec['price_1030']:.2f}\n判定时间 {rec['judged_at']}（只用 10:30 前 K 线）{tail}\n记录：{site}erqu.html")
    if phase == "fix":
        chg = "已修正 → " + rec["final"] if rec["fixed"] else "无修正"
        return (f"【二区定律·{rec['day']}】13:35 五区检查：新高 {'是' if rec['z5_new_high'] else '否'} / 新低 {'是' if rec['z5_new_low'] else '否'}，{chg}\n"
                f"最终预测：{rec['prediction_final']}\n13:30 价 {rec['price_1330']:.2f}{tail}\n记录：{site}erqu.html")
    ok = rec["correct_final"]
    if rec.get("trade") == "多":
        pl = f"\n虚拟仓位：13:35 做多 {rec['price_1330']:.2f} → 收 {rec['close_official']:.2f}，净 {rec['pnl_net_pct']:+.3f}%（已扣锁仓成本）"
    else:
        pl = "\n虚拟仓位：判坏，空仓"
    pn = s.get("pnl", {})
    pl += f"\n本月虚拟净收益 {cur['pnl_net']:+.2f}%（{cur['trades']} 笔）｜累计 {pn.get('net', 0):+.2f}%" if cur else ""
    return (f"【二区定律·{rec['day']}】结算：开 {rec['open_official']:.2f} 收 {rec['close_official']:.2f}（{rec['actual']}）\n"
            f"预测「{rec.get('prediction_final', rec['prediction'])}」→ {'✅ 对' if ok else '❌ 错' if ok is not None else '— 未预测'}"
            f"{pl}{tail}\n记录：{site}erqu.html")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["judge", "fix", "settle", "auto"])
    ap.add_argument("--day", default=now_cn().strftime("%Y-%m-%d"))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--site", default="https://jayson8199.github.io/futures-signals/")
    args = ap.parse_args()
    if now_cn().weekday() >= 5 and args.day == now_cn().strftime("%Y-%m-%d"):
        print("周末，跳过")
        return 0
    phases = [args.phase] if args.phase != "auto" else (
        ["judge", "fix", "settle"] if now_cn().strftime("%H:%M") >= "15:05" else
        ["judge", "fix"] if now_cn().strftime("%H:%M") >= "13:40" else ["judge"])
    changed_any = False
    for ph in phases:
        rec, changed = {"judge": judge, "fix": fix, "settle": settle}[ph](args.day, args.force)
        if changed:
            changed_any = True
            print(json.dumps(rec, ensure_ascii=False, indent=1))
            if not args.no_push:
                push(f"二区定律 {args.day} · {dict(judge='10:30判定', fix='13:35修正', settle='收盘结算')[ph]}", fmt_msg(rec, ph, args.site))
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a") as f:
            f.write(f"changed={'true' if changed_any else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
