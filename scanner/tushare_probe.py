#!/usr/bin/env python3
"""
tushare 数据包（第三方代理）期货接口探测。
token 从环境变量 TUSHARE_TOKEN 读取（GitHub Secrets 注入），代码与日志中不出现 token。
用法：python scanner/tushare_probe.py --out experiments/tushare_probe.md
"""
import argparse
import os
import sys
import time
from datetime import datetime

import pandas as pd

URLS = ["https://tl.kaixin8.top/tushare/sdk", "https://datahubco.com/api/tushare"]
CONNECT_ERRORS: list[str] = []


def connect():
    import tushare as ts
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise SystemExit("缺少 TUSHARE_TOKEN")
    for url in URLS:
        pro = ts.pro_api(token, timeout=120)
        pro._DataApi__http_url = url
        try:
            df = pro.daily(ts_code="000001.SZ", trade_date="20260930")
            if df is not None and len(df):
                return pro, url
        except Exception as e:
            print(f"{url} 连通失败: {str(e)[:200]}")
            CONNECT_ERRORS.append(f"{url}: {str(e)[:300]}")
    raise SystemExit("两个服务器都连不上：\n" + "\n".join(CONNECT_ERRORS))


def probe(pro, name, fn):
    t = time.time()
    try:
        df = fn()
        if df is None or len(df) == 0:
            return [name, "空", 0, "", "", ""]
        dcol = next((c for c in ("trade_date", "list_date", "date") if c in df.columns), None)
        lo = hi = ""
        if dcol:
            s = df[dcol].astype(str)
            lo, hi = s.min(), s.max()
        return [name, "通", len(df), lo, hi, ",".join(df.columns[:12]) + ("…" if len(df.columns) > 12 else "")]
    except Exception as e:
        return [name, "错", 0, "", "", str(e)[:160].replace("\n", " ")]
    finally:
        time.sleep(0.4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="experiments/tushare_probe.md")
    ap.add_argument("--pull", action="store_true", help="若单合约可用，拉取棕榈油 2015 年起全部合约并算加权")
    a = ap.parse_args()
    pro, url = connect()
    rows = []
    for ex in ["DCE", "CZCE", "SHFE", "CFFEX", "GFEX", "INE"]:
        rows.append(probe(pro, f"fut_basic {ex}", lambda ex=ex: pro.fut_basic(exchange=ex, fut_type="1")))
    for code in ["P.DCE", "PL.DCE", "P9999.DCE", "P8888.DCE"]:
        rows.append(probe(pro, f"fut_daily {code}", lambda c=code: pro.fut_daily(ts_code=c, start_date="20100101")))
    for code in ["P2601.DCE", "P1701.DCE", "P1501.DCE", "P1201.DCE", "P0901.DCE"]:
        rows.append(probe(pro, f"fut_daily {code}", lambda c=code: pro.fut_daily(ts_code=c)))
    rows.append(probe(pro, "fut_mapping P.DCE", lambda: pro.fut_mapping(ts_code="P.DCE")))
    rows.append(probe(pro, "fut_holding P 20261014", lambda: pro.fut_holding(symbol="P", trade_date="20261014")))
    rows.append(probe(pro, "fut_wsr P 20261014", lambda: pro.fut_wsr(symbol="P", trade_date="20261014")))
    rows.append(probe(pro, "fut_settle P2601.DCE", lambda: pro.fut_settle(ts_code="P2601.DCE")))
    rows.append(probe(pro, "fut_weekly_detail P", lambda: pro.fut_weekly_detail(prd="P", start_week="202601")))

    md = [f"# tushare 数据包期货接口探测\n", f"- 时间：{datetime.now():%Y-%m-%d %H:%M}（UTC）", f"- 服务器：{url}\n",
          "| 接口 | 状态 | 行数 | 最早 | 最晚 | 字段 / 报错 |", "|---|---|---|---|---|---|"]
    for r in rows:
        md.append("| " + " | ".join(str(x) for x in r) + " |")

    def flush():
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        open(a.out, "w", encoding="utf-8").write("\n".join(md) + "\n")
    flush()
    single_ok = any(r[0].startswith("fut_daily P2601") and r[1] == "通" for r in rows)
    if a.pull and single_ok:
      try:
          basic = pro.fut_basic(exchange="DCE", fut_type="1")
          codes = sorted(c for c in basic["ts_code"] if c.startswith("P") and c[1].isdigit() and c.endswith(".DCE"))
          basic = basic.set_index("ts_code")
          codes = [c for c in codes if str(basic.loc[c].get("delist_date", "99999999") or "99999999") >= "20150101"]
          os.makedirs("experiments/tushare_cache/P", exist_ok=True)
          frames = {}
          for c in codes:
              try:
                  df = pro.fut_daily(ts_code=c)
                  time.sleep(0.3)
              except Exception as e:
                  md.append(f"- {c} 拉取失败：{str(e)[:80]}"); continue
              if df is None or len(df) == 0:
                  continue
              df.to_csv(f"experiments/tushare_cache/P/{c}.csv", index=False)
              frames[c] = df
          md.append(f"\n## 棕榈油全合约拉取：{len(frames)}/{len(codes)} 个合约")
          if frames:
              sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
              import weighted as W
              conv = {}
              for c, df in frames.items():
                  d = df.rename(columns={"trade_date": "date", "vol": "volume", "oi": "hold"})
                  d["date"] = pd.to_datetime(d["date"], format="%Y%m%d")
                  conv[c] = d[["date", "open", "high", "low", "close", "volume", "hold"]]
              allidx = pd.DatetimeIndex(sorted(set(pd.concat([d["date"] for d in conv.values()]))))
              out = W.weighted(conv, allidx, "2015-01-01")
              os.makedirs("data/weighted_tushare", exist_ok=True)
              out.reset_index().assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d")).to_csv("data/weighted_tushare/P0.csv", index=False)
              md.append(f"- 加权指数 data/weighted_tushare/P0.csv：{len(out)} 行，{out.index.min().date()} ~ {out.index.max().date()}")
              sina = "data/weighted/P0.csv"
              if os.path.exists(sina):
                  s = pd.read_csv(sina, parse_dates=["date"]).set_index("date")["close"]
                  both = pd.concat([out["close"].rename("ts"), s.rename("sina")], axis=1).dropna()
                  err = ((both["ts"] - both["sina"]).abs() / both["sina"]).mean() * 100
                  md.append(f"- 与新浪版加权对比（{len(both)} 个共同交易日）：平均相对误差 {err:.3f}%")
      except Exception as e:
          md.append(f"\n- 拉取阶段出错：{str(e)[:300]}")
    flush()
    print("\n".join(md))


def _safe(msg: str) -> str:
    tok = os.environ.get("TUSHARE_TOKEN", "").strip()
    return msg.replace(tok, "***") if tok else msg


if __name__ == "__main__":
    import traceback
    try:
        main()
    except BaseException as e:  # 连不上/缺 token 也要把原因写进结果文件
        os.makedirs("experiments", exist_ok=True)
        with open("experiments/tushare_probe.md", "w", encoding="utf-8") as f:
            f.write(f"# tushare 数据包期货接口探测\n\n- 时间：{datetime.now():%Y-%m-%d %H:%M}（UTC）\n- 结果：**失败**\n\n```\n"
                    + _safe(traceback.format_exc())[-3000:] + "\n```\n")
        raise
