#!/usr/bin/env python3
"""
黄金专题冻结快照导入（一次性，手动运行）：从原黄金研究台源码读取已发布快照，生成公开静态资产 scanner/assets/gold/。
  - gc_snapshot.json：Yahoo GC=F 日线（只保留日期与收盘）+ 来源、抓取时间、质量审计
  - macro3.json：只保留 DFII10 / DTWEXBGS / DCOILWTICO 三个观测序列；VIXCLS 版权属 Cboe，整列剔除
源目录只读；不复制历史 vintage、原始响应、私人说明。不联网，不自动运行。
用法：python scanner/gold_snapshot.py --source <原研究台目录> [--out scanner/assets/gold]
"""
import argparse
import hashlib
import json
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parent / "assets" / "gold"
MACRO_IDS = ["DFII10", "DTWEXBGS", "DCOILWTICO"]
EXCLUDED = {"VIXCLS": "Cboe 版权数据，未获公开转载许可，公开站不收录其任何数值"}
GOLD_KEYS = ["symbol", "instrument", "currency", "unit", "frequency", "timezone", "sourceName", "sourceUrl",
             "endpoint", "fetchedAt", "asOf", "rawSha256", "methodology"]
SERIES_KEYS = ["id", "name", "unit", "origin", "changeUnit", "transform", "note", "sourceUrl", "fetchedAt", "asOf", "rawSha256"]


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def common_dates(gold_dates, series):
    """黄金记录日中，三个序列都有同日观测的日期（只做覆盖诊断）"""
    sets = [{r["date"] for r in s["observations"]} for s in series]
    return [d for d in gold_dates if all(d in st for st in sets)]


def convert(source: Path, commit: str = ""):
    gold_raw = (source / "dist/data/gold.json").read_bytes()
    macro_raw = (source / "dist/data/macro.json").read_bytes()
    gold, macro = json.loads(gold_raw), json.loads(macro_raw)
    if gold.get("schemaVersion") != 1 or gold.get("symbol") != "GC=F" or gold.get("currency") != "USD":
        raise ValueError("源黄金快照规格不符")
    if macro.get("goldRawSha256") != gold["rawSha256"] or macro.get("goldAsOf") != gold["asOf"]:
        raise ValueError("源宏观快照与黄金快照不匹配")
    origin = {"project": "黄金研究台（原独立站点，归档只读）", "sourceCommit": commit,
              "goldJsonSha256": sha256(gold_raw), "macroJsonSha256": sha256(macro_raw)}

    prices = [{"date": r["date"], "close": r["close"]} for r in gold["prices"]]
    q = gold["quality"]
    gc = {"schemaVersion": 1, **{k: gold[k] for k in GOLD_KEYS}, "frozen": True,
          "quality": {k: q[k] for k in ["rawRows", "validRows", "duplicates", "nullCloseExcluded", "incompleteExcluded",
                                         "weekdayGaps", "largeMoves", "largeMoveThresholdPct", "calendarNote"]},
          "importedFrom": origin,
          "fieldsOmitted": "开高低价与成交量未收录；本页只用收盘价。",
          "prices": prices}
    if len(prices) != q["validRows"] or prices[-1]["date"] != gold["asOf"]:
        raise ValueError("黄金快照统计不一致")

    series = []
    for sid in MACRO_IDS:
        s = next(x for x in macro["series"] if x["id"] == sid)
        out = {k: s[k] for k in SERIES_KEYS}
        out["quality"] = {k: s["quality"][k] for k in ["rawRows", "validRows", "missingDates", "futureExcluded", "duplicates"]}
        out["observations"] = [{"date": r["date"], "value": r["value"]} for r in s["observations"]]
        obs = {r["date"] for r in out["observations"]}
        gd = [p["date"] for p in prices]
        out["sameDateGoldCoverage"] = sum(d in obs for d in gd)
        out["goldDatesWithoutObservation"] = [d for d in gd if d not in obs]
        series.append(out)
    m3 = {"schemaVersion": 2, "seriesIds": MACRO_IDS, "goldAsOf": gold["asOf"], "goldRawSha256": gold["rawSha256"],
          "trainingEligible": False, "frozen": True,
          "alignmentPolicy": macro["alignmentPolicy"], "vintageStatus": macro["vintageStatus"],
          "excludedSeries": [{"id": k, "reason": v} for k, v in EXCLUDED.items()],
          "provenanceNote": "原研究台观察四个序列；公开版只保留三个可公开转载的美联储/EIA 序列（经 FRED），"
                            "共同观测日按这三个序列重新计算。数值、日期与原快照一致，未补值、未修订。",
          "commonObservationDates": common_dates([p["date"] for p in prices], series),
          "goldObservationCount": len(prices), "importedFrom": origin, "series": series}
    return gc, m3


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True)
    ap.add_argument("--commit", default="", help="源仓库提交号，仅记录")
    ap.add_argument("--out", default=str(ASSET_DIR))
    args = ap.parse_args()
    gc, m3 = convert(Path(args.source), args.commit)
    import gold_page
    gold_page.validate_gold(gc)
    gold_page.validate_macro(m3, gc)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, obj in (("gc_snapshot.json", gc), ("macro3.json", m3)):
        (out / name).write_text(dump(obj), encoding="utf-8", newline="\n")
        print(name, sha256((out / name).read_bytes()))


if __name__ == "__main__":
    main()
