#!/usr/bin/env python3
"""
期货八种形态扫描器（量·仓·价三维分类）
逻辑与 Kimi 版 scan.py 完全一致，仅增加：
  - 每品种拉取失败自动重试
  - 命令行参数：--out 输出目录（写入 <date>.json 与 latest.json）
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

CN_TZ = ZoneInfo("Asia/Shanghai")

# 品种配置：代码 -> (名称, 交易所)
SYMBOLS = {
    # 上期所
    "RB0": ("螺纹钢", "上期所"), "HC0": ("热轧卷板", "上期所"), "SS0": ("不锈钢", "上期所"),
    "CU0": ("沪铜", "上期所"), "AL0": ("沪铝", "上期所"), "ZN0": ("沪锌", "上期所"),
    "PB0": ("沪铅", "上期所"), "NI0": ("沪镍", "上期所"), "SN0": ("沪锡", "上期所"),
    "AU0": ("黄金", "上期所"), "AG0": ("白银", "上期所"), "FU0": ("燃料油", "上期所"),
    "BU0": ("沥青", "上期所"), "SC0": ("原油", "上期所"), "LU0": ("低硫燃料油", "上期所"),
    "RU0": ("天然橡胶", "上期所"), "NR0": ("20号胶", "上期所"), "SP0": ("纸浆", "上期所"),
    # 大商所
    "I0": ("铁矿石", "大商所"), "J0": ("焦炭", "大商所"), "JM0": ("焦煤", "大商所"),
    "M0": ("豆粕", "大商所"), "Y0": ("豆油", "大商所"), "P0": ("棕榈油", "大商所"),
    "C0": ("玉米", "大商所"), "L0": ("塑料", "大商所"), "PP0": ("聚丙烯", "大商所"),
    "V0": ("PVC", "大商所"), "EG0": ("乙二醇", "大商所"), "EB0": ("苯乙烯", "大商所"),
    "PG0": ("液化石油气", "大商所"),
    # 郑商所
    "TA0": ("PTA", "郑商所"), "MA0": ("甲醇", "郑商所"), "FG0": ("玻璃", "郑商所"),
    "SA0": ("纯碱", "郑商所"), "UR0": ("尿素", "郑商所"), "SR0": ("白糖", "郑商所"),
    "CF0": ("棉花", "郑商所"), "OI0": ("菜油", "郑商所"), "RM0": ("菜粕", "郑商所"),
    "AP0": ("苹果", "郑商所"), "PK0": ("花生", "郑商所"), "PF0": ("短纤", "郑商所"),
    "SF0": ("硅铁", "郑商所"), "SM0": ("锰硅", "郑商所"),
    # 中金所
    "IF0": ("沪深300", "中金所"), "IH0": ("上证50", "中金所"),
    "IC0": ("中证500", "中金所"), "IM0": ("中证1000", "中金所"),
    # 广期所
    "SI0": ("工业硅", "广期所"), "LC0": ("碳酸锂", "广期所"), "PX0": ("对二甲苯", "广期所"),
    "SH0": ("烧碱", "广期所"), "EC0": ("集运指数", "广期所"),
}

PATTERNS = {
    "高富帅": {"label": "增仓·放量·上涨", "desc": "新资金大量涌入，多头主动进攻，趋势大概率延续",
               "emoji": "🏆", "color": "gold", "dims": {"price": "up", "vol": "up", "hold": "up"}},
    "白富美": {"label": "增仓·放量·下跌", "desc": "新资金进入做空，空头主动打压，下跌趋势确认",
               "emoji": "💎", "color": "purple", "dims": {"price": "down", "vol": "up", "hold": "up"}},
    "上涨乏力": {"label": "上涨·放量·减仓", "desc": "老多头获利了结，新多头接盘意愿不强，警惕反转",
                 "emoji": "⚠️", "color": "orange", "dims": {"price": "up", "vol": "up", "hold": "down"}},
    "下跌乏力": {"label": "下跌·放量·减仓", "desc": "老空头获利了结，新空头入场意愿不强，跌势或暂缓",
                 "emoji": "🛑", "color": "cyan", "dims": {"price": "down", "vol": "up", "hold": "down"}},
    "虚涨分歧": {"label": "上涨·缩量·增仓", "desc": "或为空方在高位开空，多空分歧显著加大，需观望",
                 "emoji": "🔶", "color": "yellow", "dims": {"price": "up", "vol": "down", "hold": "up"}},
    "虚跌分歧": {"label": "下跌·缩量·增仓", "desc": "或为多头在低位抄底，多空分歧加剧，趋势不明朗",
                 "emoji": "🔷", "color": "blue", "dims": {"price": "down", "vol": "down", "hold": "up"}},
    "涨势将尽": {"label": "上涨·缩量·减仓", "desc": "多头力量明显衰退，市场缺乏新方向，趋势大概率结束",
                 "emoji": "📉", "color": "gray", "dims": {"price": "up", "vol": "down", "hold": "down"}},
    "跌势将尽": {"label": "下跌·缩量·减仓", "desc": "空头力量衰退，抛压减小，市场或迎来反转契机",
                 "emoji": "📈", "color": "green", "dims": {"price": "down", "vol": "down", "hold": "down"}},
}


def fetch_data(symbol: str, days: int = 60, retries: int = 3) -> pd.DataFrame | None:
    """获取期货主力连续合约最近 N 天日K线数据（新浪财经，经 akshare）"""
    import akshare as ak

    end_date = datetime.now(CN_TZ)
    start_date = end_date - timedelta(days=days + 15)
    last_err = None
    for attempt in range(retries):
        try:
            df = ak.futures_main_sina(
                symbol=symbol,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
            if df is None or df.empty:
                return None
            return df.sort_values("日期").reset_index(drop=True)
        except Exception as e:  # 网络抖动等
            last_err = e
            time.sleep(2 + 3 * attempt)
    print(f"  [警告] {symbol} 数据获取失败: {last_err}", file=sys.stderr)
    return None


def classify_pattern(price_change_pct, today_vol, vol_5ma, vol_20ma, hold_change_pct) -> str:
    is_up = price_change_pct > 0
    is_down = price_change_pct < 0
    is_vol_up = today_vol > vol_5ma and today_vol > vol_20ma
    is_vol_down = not is_vol_up
    is_hold_up = hold_change_pct > 0
    is_hold_down = hold_change_pct < 0

    if is_up and is_vol_up and is_hold_up:
        return "高富帅"
    if is_down and is_vol_up and is_hold_up:
        return "白富美"
    if is_up and is_vol_up and is_hold_down:
        return "上涨乏力"
    if is_down and is_vol_up and is_hold_down:
        return "下跌乏力"
    if is_up and is_vol_down and is_hold_up:
        return "虚涨分歧"
    if is_down and is_vol_down and is_hold_up:
        return "虚跌分歧"
    if is_up and is_vol_down and is_hold_down:
        return "涨势将尽"
    if is_down and is_vol_down and is_hold_down:
        return "跌势将尽"
    return "未分类"


def analyze_df(df: pd.DataFrame, symbol: str, name: str, exchange: str) -> dict | None:
    """由日K DataFrame 计算单品种结果（纯函数，便于离线测试）"""
    if df is None or len(df) < 21:
        return None
    today_row, prev_row = df.iloc[-1], df.iloc[-2]

    today_hold = int(today_row["持仓量"])
    prev_hold = int(prev_row["持仓量"])
    today_vol = int(today_row["成交量"])
    today_close = float(today_row["收盘价"])
    prev_close = float(prev_row["收盘价"])
    vol_5ma = int(df["成交量"].iloc[-5:].mean())
    vol_20ma = int(df["成交量"].iloc[-20:].mean())

    hold_change_pct = (today_hold - prev_hold) / prev_hold * 100 if prev_hold > 0 else 0.0
    price_change_pct = (today_close - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
    mom20 = 0.0
    if float(df["收盘价"].iloc[-21]) > 0:
        mom20 = (today_close / float(df["收盘价"].iloc[-21]) - 1) * 100

    pattern = classify_pattern(price_change_pct, today_vol, vol_5ma, vol_20ma, hold_change_pct)
    is_hold_20p = abs(hold_change_pct) >= 20.0
    is_vol_20p = today_vol >= vol_20ma * 1.2

    # 近 20 日收盘序列（网页迷你走势图用）
    closes = [round(float(x), 2) for x in df["收盘价"].iloc[-20:]]
    # 近 45 日 (日期, 收盘, 成交量, 持仓) 简史：用于回算历史形态、胜率统计与连续天数
    tail = df.iloc[-45:]
    hist = [[str(r["日期"]), round(float(r["收盘价"]), 2), int(r["成交量"]), int(r["持仓量"])]
            for _, r in tail.iterrows()]

    return {
        "symbol": symbol, "name": name, "exchange": exchange,
        "date": str(today_row["日期"]),
        "today_hold": today_hold, "prev_hold": prev_hold,
        "hold_change_pct": round(hold_change_pct, 2),
        "hold_change_amount": today_hold - prev_hold,
        "today_vol": today_vol, "vol_5ma": vol_5ma, "vol_20ma": vol_20ma,
        "today_close": round(today_close, 2), "prev_close": round(prev_close, 2),
        "price_change_pct": round(price_change_pct, 2),
        "mom20": round(mom20, 2),
        "pattern": pattern,
        "is_strong": is_hold_20p and is_vol_20p,
        "is_hold_20p": is_hold_20p, "is_vol_20p": is_vol_20p,
        "closes20": closes,
        "hist": hist,
        "dims": {
            "price": "上涨" if price_change_pct > 0 else "下跌" if price_change_pct < 0 else "平盘",
            "vol": "放量" if today_vol > vol_5ma and today_vol > vol_20ma else "缩量",
            "hold": "增仓" if hold_change_pct > 0 else "减仓" if hold_change_pct < 0 else "持平",
        },
    }


def analyze_symbol(symbol, name, exchange):
    return analyze_df(fetch_data(symbol, days=60), symbol, name, exchange)


def summarize(all_results: list, errors: list, scan_date: str) -> dict:
    """由单品种结果列表组装完整 data.json（与 Kimi 版字段一致）
    日期不是多数日期的滞后品种会被剔除并计入 errors（避免新旧数据混排）"""
    if all_results:
        cnt = {}
        for r in all_results:
            cnt[r["date"]] = cnt.get(r["date"], 0) + 1
        major = max(cnt.items(), key=lambda kv: kv[1])[0]
        stale = [r["symbol"] for r in all_results if r["date"] != major]
        if stale:
            errors = list(errors) + [f"{s}(滞后)" for s in stale]
            all_results = [r for r in all_results if r["date"] == major]
    all_results = sorted(all_results, key=lambda x: x["hold_change_pct"], reverse=True)
    pattern_groups = {n: [] for n in PATTERNS}
    for r in all_results:
        if r["pattern"] in pattern_groups:
            pattern_groups[r["pattern"]].append(r)

    # 数据日期取多数品种的日期（防个别品种滞后）
    if all_results:
        dates = {}
        for r in all_results:
            dates[r["date"]] = dates.get(r["date"], 0) + 1
        data_date = max(dates.items(), key=lambda kv: kv[1])[0]
    else:
        data_date = scan_date

    moms = sorted(r["mom20"] for r in all_results)
    mom_median = moms[len(moms) // 2] if moms else 0.0

    return {
        "scan_date": scan_date,
        "data_date": data_date,
        "market": {"mom20_median": round(mom_median, 2), "regime": "弱势" if mom_median < 0 else "强势"},
        "strategy": "八种形态",
        "total_scanned": len(SYMBOLS),
        "valid_count": len(all_results),
        "error_count": len(errors),
        "errors": errors,
        "up_count": sum(1 for r in all_results if r["price_change_pct"] > 0),
        "down_count": sum(1 for r in all_results if r["price_change_pct"] < 0),
        "strong_count": sum(1 for r in all_results if r["is_strong"]),
        "strong_gao_count": sum(1 for r in all_results if r["pattern"] == "高富帅" and r["is_strong"]),
        "strong_bai_count": sum(1 for r in all_results if r["pattern"] == "白富美" and r["is_strong"]),
        "patterns": {
            n: {**info, "count": len(pattern_groups[n]), "items": pattern_groups[n]}
            for n, info in PATTERNS.items()
        },
        "all_results": all_results,
    }


def scan_all() -> dict:
    scan_date = datetime.now(CN_TZ).strftime("%Y-%m-%d")
    results, errors = [], []
    print(f"开始扫描 {len(SYMBOLS)} 个品种...")
    for symbol, (name, exchange) in SYMBOLS.items():
        r = analyze_symbol(symbol, name, exchange)
        if r:
            print(f"  ✓ {symbol:4s} {name:6s} {r['date']} {r['pattern']} 持仓{r['hold_change_pct']:+.2f}% 价格{r['price_change_pct']:+.2f}%")
            results.append(r)
        else:
            print(f"  ✗ {symbol} 数据不足或获取失败")
            errors.append(symbol)
        time.sleep(0.3)  # 轻微限速，避免被新浪限流
    return summarize(results, errors, scan_date)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data", help="输出目录")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    data = scan_all()
    (out / "latest.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n扫描日期 {data['scan_date']} ｜ 数据日期 {data['data_date']} ｜ 有效 {data['valid_count']}/{data['total_scanned']} ｜ "
          f"涨 {data['up_count']} 跌 {data['down_count']} ｜ 市场 {data['market']['regime']}({data['market']['mom20_median']}%)")
    for n in PATTERNS:
        print(f"  {PATTERNS[n]['emoji']} {n}: {data['patterns'][n]['count']}")


if __name__ == "__main__":
    main()
