#!/usr/bin/env python3
"""
预测实验的存档、复盘和汇总（预测本身见 predict.py）。

数据不进公开仓库，放在 --log-dir 指定的目录（项目共享文件夹 mingpan/验证/），全部只追加：
  predictions.jsonl   每天的预测，事前保存。字段：generated_at、target、rule_version、kind、fingerprint、全文等
                      kind：事前（目标日期开始前保存，计入统计）/ 回看（目标日期开始后才算的，只展示不计入）
                            / 更正（同一天内容变了，追加一条更正，原来那条照旧算数）
  observations.jsonl  每晚的回答：中立勾选的事件、每条预测的判断、日报的影响、事实备注；同一天再答就追加，以最后一条为准
  ratings.csv         原来的五道固定题加具体题，格式不变（老分析脚本照常能用）
  flags.jsonl         程序故障、漏发等标记
  verifications.jsonl 发送和保存是不是同一份：日报工作流日志里打印「预测版本、条数、指纹、提交」，
                      21:37 的任务把那一行原样交给 verify，和事前保存的指纹比对。结果只有三种：
                      一致（计入正式对照）/ 不一致、未发出、未核对（都排除在正式对照之外，汇总里单列）
存档里只有日期、规则、命理依据和预测文字，没有出生资料，也没有任何密钥。

用法（都在 mingpan 目录下运行）：
  python3 experiment.py save    --date 2026-10-28 --log-dir DIR    事前保存（已存在就沿用，不覆盖）
  python3 experiment.py review  --date 2026-10-28 [--log-dir DIR]  打印当晚复盘题
  python3 experiment.py record  --date 2026-10-28 --answer "3BCBA ABBA / 13 / A / AB 客户改到周五" --log-dir DIR
  python3 experiment.py summary [--days 7 | --all] --log-dir DIR    汇总
  python3 experiment.py flag    --date 2026-10-28 --kind 漏发 --note "21:07 没发出，21:40 补发" --log-dir DIR
  python3 experiment.py verify  --date 2026-10-28 --log-line "2026-10-28 | 邮件已发送 | … 指纹 a42dacf4ac7a 提交 8ec4014" --log-dir DIR
  python3 experiment.py status  --date 2026-10-28 --log-dir DIR    看这一天有没有事前记录、核对结果
  python3 experiment.py verify  --date 2026-10-28 --missing "找不到成功的运行或日志里没有指纹" --log-dir DIR
"""
import argparse
import csv
import subprocess
import datetime
import json
import re
import sys
from pathlib import Path

import daily as D
import predict as P

TZ = D.TZ
OUTCOME = {"A": "发生（自然）", "B": "发生（受阅读影响）", "C": "没发生", "D": "无法判断", "E": "没有相关机会"}
ACTED = {"A": "没有因日报做什么", "B": "因日报做了些什么"}
EFFECT = {"A": "有具体帮助", "B": "没什么影响", "C": "添了担心、反复查看或拖延"}
RATING_COLS = ["date", "overall", "pressure", "energy", "people", "helpful", "good_hour", "bad_hour", "control_hour",
               "claim", "claim_text", "note"]


# ---------- 读写 ----------

def _read(path):
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _append(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def _now():
    return datetime.datetime.now(TZ)


def records(log_dir, target=None):
    rs = _read(Path(log_dir) / "predictions.jsonl")
    return [r for r in rs if target is None or r["target"] == str(target)]


def formal(log_dir, target):
    """这一天算数的那条：事前保存的第一条；没有就是 None。"""
    return next((r for r in records(log_dir, target) if r["kind"] == "事前"), None)


def save(p, target, log_dir, now=None):
    """事前保存。返回 (记录, 说明)。同一天已有就沿用；内容变了只追加更正；目标日期开始后才算的记为回看。"""
    now = now or _now()
    rec = P.build(p, target)
    mine = records(log_dir, target)
    first = next((r for r in mine if r["kind"] in ("事前", "回看")), None)
    if first and first["fingerprint"] == rec["fingerprint"]:
        return first, f"{target} 已经保存过（{first['kind']}，{first['generated_at'][:16]}），沿用原记录"
    late = now >= datetime.datetime.combine(target, datetime.time(0), TZ)
    rec = {"generated_at": now.isoformat(timespec="seconds"), "commit": commit(), **rec}
    if first:
        if any(r["kind"] == "更正" and r["fingerprint"] == rec["fingerprint"] for r in mine):
            return first, f"{target} 的更正已经记过，原记录照旧算数"
        rec.update(kind="更正", supersedes=first["fingerprint"],
                   correction_note="同一目标日期重算结果和原记录不同（程序或规则有变），只追加不覆盖，统计仍用原记录")
        _append(Path(log_dir) / "predictions.jsonl", rec)
        flag(target, "程序变动", f"重算指纹 {rec['fingerprint']} 和原记录 {first['fingerprint']} 不同", log_dir, now)
        return first, f"{target} 重算结果和原记录不同，已追加更正，统计仍用原记录"
    rec["kind"] = "回看" if late else "事前"
    _append(Path(log_dir) / "predictions.jsonl", rec)
    if late:
        flag(target, "生成晚了", f"{rec['generated_at']} 才保存，目标日期已经开始，记为回看样本，不计入统计", log_dir, now)
    return rec, f"{target} 已保存（{rec['kind']}，指纹 {rec['fingerprint']}）"


def commit():
    """当前代码的提交号（短），存进记录，方便和工作流日志里的提交对照。"""
    try:
        return subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=D.ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


LOG_RE = re.compile(r"(\d{4}-\d{2}-\d{2}) \| (.*?) \| (.*?) \| 预测 (v\d+) (\d+) 条 指纹 ([0-9a-f]{12})(?: 提交 (\S+))?")


def verify(target, log_dir, log_line=None, missing=None, now=None):
    """把工作流日志里那一行和事前保存的记录比对，追加一条核对结果。返回 (状态, 说明)。"""
    rec = formal(log_dir, target)
    out = {"date": str(target), "at": (now or _now()).isoformat(timespec="seconds"),
           "saved_fingerprint": rec["fingerprint"] if rec else None, "saved_commit": (rec or {}).get("commit")}
    m = LOG_RE.search(log_line or "")
    if missing or not m:
        out.update(status="未核对", note=missing or "日志行里没找到预测指纹")
    elif m.group(1) != str(target):
        out.update(status="未核对", note=f"日志行说的是 {m.group(1)}，不是 {target}")
    else:
        sent = any(x.endswith(("已发送", "已推送")) for x in (m.group(2).strip(), m.group(3).strip()))
        out.update(sent_version=m.group(4), sent_count=int(m.group(5)), sent_fingerprint=m.group(6),
                   sent_commit=m.group(7), channels=f"{m.group(2).strip()} | {m.group(3).strip()}")
        if not rec:
            out.update(status="未核对", note="没有事前保存的记录可比")
        elif not sent:
            out.update(status="未发出", note="两个渠道都没发出去")
        elif m.group(6) == rec["fingerprint"]:
            out.update(status="一致", note="发送的和事前保存的是同一份")
        else:
            out.update(status="不一致", note="发送的指纹和保存的不同（中间改过代码或规则），这一天排除在正式对照外")
    _append(Path(log_dir) / "verifications.jsonl", out)
    if out["status"] != "一致":
        flag(target, f"核对{out['status']}", out["note"], log_dir, now)
    return out["status"], out["note"]


def check_status(log_dir, target):
    """一天的核对结论：有任何一次不一致就算不一致；否则有一致就算一致；其余按最后一次（未发出 / 未核对）。"""
    vs = [v for v in _read(Path(log_dir) / "verifications.jsonl") if v["date"] == str(target)]
    if any(v["status"] == "不一致" for v in vs):
        return "不一致"
    if any(v["status"] == "一致" for v in vs):
        return "一致"
    return vs[-1]["status"] if vs else "未核对"


def flag(target, kind, note, log_dir, now=None):
    _append(Path(log_dir) / "flags.jsonl", {"date": str(target), "kind": kind, "note": note,
                                            "at": (now or _now()).isoformat(timespec="seconds")})


# ---------- 复盘题 ----------

def day_record(p, target, log_dir=None):
    """复盘用的那条预测：有事前记录用事前记录，否则回看记录，都没有就现算并注明。"""
    if log_dir:
        r = formal(log_dir, target) or next((x for x in records(log_dir, target) if x["kind"] == "回看"), None)
        if r:
            return r
    r = P.build(p, target)
    r["kind"] = "未保存"
    return r


def review_prompt(p, target, log_dir=None):
    """当晚复盘题：老的五题加具体题（格式不变），再加中立勾选、观察判断、日报影响。返回 (文字, KEYS 行)。"""
    qs = D.review(p, target)
    rec = day_record(p, target, log_dir)
    preds = rec["predictions"]
    L = [f"**{target.month}/{target.day} 复盘**，四段用斜杠隔开，像 `3BCBA ABBA / 13 / {'A' * len(preds) or '-'} / AB 一句事实`。"
         "只答第一段也行（老格式照收）。",
         "",
         "**第一段 · 老题**",
         "1. 整体：1 很差　2 偏差　3 一般　4 不错　5 很好",
         "2. 压力：A 很大　B 有一些　C 基本没有",
         "3. 精力：A 很累或身体不舒服　B 一般　C 精力好",
         "4. 人际：A 有摩擦或是非　B 平常　C 顺，有人帮忙",
         "5. 日报：A 有用，照着做了　B 看了，没怎么用上　C 没看"]
    L += [f"{i}. {q}：{opts}" for i, (_, q, opts) in enumerate(qs, 6)]
    L += ["", "**第二段 · 今天实际发生了哪些**（先照实记，别回头看预测）：写数字，可多选；都没有写 0，记不清写 ?"]
    evs = P.events_for(rec["rule_version"])
    L += [f"{i}. {evs[k]['short']}（不算：{evs[k]['exclude']}）" for i, k in enumerate(P.CHECKLIST, 1)]
    L.append("「明显事务压力」不用勾，直接看第 2 题，选 A 就算发生。")
    L += ["", "**第三段 · 对一下观察**（每条一个字母）"]
    if preds:
        L += [f"{x['question']}" for x in preds]
        L.append("因为提前注意了、所以没发生，也选 C；看了日报主动去问、去找而得到的，选 B。")
    else:
        L.append(f"这一天没有观察项：{rec['none_reason']}第三段写 - 就行。")
    if rec["kind"] != "事前":
        L.append(f"（这一天的预测是{'回看样本' if rec['kind'] == '回看' else '现算的，没有事前保存'}，照样记，但不计入统计。）")
    elif check_status(log_dir, target) != "一致":
        L.append(f"（这一天发出去的和事前保存的还没核对上：{check_status(log_dir, target)}。照样记，核对不上就不计入正式对照。）")
    L += ["", "**第四段 · 日报的影响**（两个字母）",
          "① 今天有没有因为日报做了什么：A 没有　B 有",
          "② 效果：A 有具体帮助　B 没什么影响　C 添了担心、反复查看或拖延",
          "最后可以接一句事实，比如「客户临时改到周五」。"]
    keys = "KEYS " + "|".join(f"{k}={q}" for k, q, _ in qs)
    return "\n".join(L), keys


# ---------- 记录回答 ----------

def parse(p, target, raw, log_dir=None):
    """解析回答。返回 (rating 行, observation, 错误列表)。老格式（没有斜杠）只出 rating 行。"""
    errs = []
    s = raw.strip().replace("／", "/").replace("？", "?")
    parts = [x.strip() for x in s.split("/", 3)]
    qs = D.review(p, target)
    m = re.match(r"^([1-5])\s*([ABCabc])([ABCabc])([ABCabc])([ABCabc])(?:\s+([ABCabc]+)(?=\s|$))?\s*(.*)$", parts[0], re.S)
    if not m:
        return None, None, ["第一段要像 3BCBA ABBA：先一个 1 到 5 的数字，再四个 A/B/C 字母，空格后是具体题的字母"]
    spec = (m.group(6) or "").upper()
    if len(spec) > len(qs):
        errs.append(f"具体题只有 {len(qs)} 道，答了 {len(spec)} 个字母")
    head_note = m.group(7).strip()
    row = dict.fromkeys(RATING_COLS, "")
    row.update(date=str(target), overall=m.group(1), pressure=m.group(2).upper(), energy=m.group(3).upper(),
               people=m.group(4).upper(), helpful=m.group(5).upper())
    for (k, q, _), v in zip(qs, spec):
        row[k] = v
    row["claim_text"] = next((q for k, q, _ in qs if k == "claim"), "")
    if len(parts) == 1:
        row["note"] = head_note
        return row, None, errs
    if head_note:
        errs.append(f"第一段多了文字「{head_note}」，事实备注请放在最后")
    if len(parts) < 4:
        errs.append("新格式要四段：老题 / 发生了哪些 / 观察判断 / 影响")
        return row, None, errs
    rec = day_record(p, target, log_dir)
    ev_raw = parts[1].replace(" ", "")
    if ev_raw == "0":
        events = ["none"]
    elif ev_raw == "?":
        events = ["unknown"]
    elif re.fullmatch(r"[1-5]+", ev_raw):
        events = [P.CHECKLIST[int(c) - 1] for c in dict.fromkeys(ev_raw)]
    else:
        errs.append("第二段写 1 到 5 的数字（可多选），都没有写 0，记不清写 ?")
        events = []
    oc = parts[2].replace(" ", "").upper()
    preds = rec["predictions"]
    if not preds:
        if oc not in ("-", ""):
            errs.append("这一天没有观察项，第三段写 - 就行")
        outcomes = {}
    elif len(oc) != len(preds) or any(c not in OUTCOME for c in oc):
        errs.append(f"第三段要 {len(preds)} 个字母（A 到 E），每条观察一个")
        outcomes = {}
    else:
        outcomes = {x["id"]: c for x, c in zip(preds, oc)}
    m4 = re.match(r"^([ABab])\s*([ABCabc])\s*(.*)$", parts[3], re.S)
    if not m4:
        errs.append("第四段先写两个字母：① A 没有 / B 有，② A 有帮助 / B 没影响 / C 添担心")
        acted = effect = note = ""
    else:
        acted, effect, note = m4.group(1).upper(), m4.group(2).upper(), m4.group(3).strip()
    row["note"] = note
    obs = {"date": str(target), "raw": raw, "events": events, "pressure_high": row["pressure"] == "A",
           "rule_version": rec["rule_version"], "prediction_kind": rec["kind"], "fingerprint": rec["fingerprint"],
           "outcomes": outcomes, "acted": acted, "effect": effect, "note": note}
    return row, obs, errs


def upsert_rating(row, log_dir):
    path = Path(log_dir) / "ratings.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8"))) if path.exists() else []
    clean = {k: str(row.get(k, "")).replace(",", "、").replace("\n", " ") for k in RATING_COLS}
    rows = [r for r in rows if r["date"] != clean["date"]] + [clean]
    rows.sort(key=lambda r: r["date"])
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RATING_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def record(p, target, raw, log_dir, now=None):
    row, obs, errs = parse(p, target, raw, log_dir)
    if errs:
        return False, "；".join(errs)
    upsert_rating(row, log_dir)
    if obs:
        obs["recorded_at"] = (now or _now()).isoformat(timespec="seconds")
        _append(Path(log_dir) / "observations.jsonl", obs)
    return True, "已记录" + ("（老格式，只记了第一段）" if not obs else "")


# ---------- 汇总 ----------

def summary(log_dir, start=None, end=None, today=None):
    """汇总：保存了多少、能判断多少、发生没发生、无法判断、无机会、漏答；分类别对比有预测和没预测的日子。
    不算单一准确率，不设及格线。"""
    today = today or _now().date()
    end = end or today - datetime.timedelta(days=1)
    allrec = records(log_dir)
    obs_by = {}
    for o in _read(Path(log_dir) / "observations.jsonl"):
        obs_by[o["date"]] = o           # 同一天以最后一条为准
    rated = {r["date"]: r for r in csv.DictReader((Path(log_dir) / "ratings.csv").open(encoding="utf-8"))} \
        if (Path(log_dir) / "ratings.csv").exists() else {}
    dates = sorted({r["target"] for r in allrec} | set(obs_by))
    if start:
        dates = [d for d in dates if d >= str(start)]
    dates = [d for d in dates if d <= str(end)]
    flags = [f for f in _read(Path(log_dir) / "flags.jsonl") if (not start or f["date"] >= str(start)) and f["date"] <= str(end)]
    L = [f"预测实验汇总（{dates[0] if dates else '-'} 到 {end}，探索性记录，什么也证明不了）"]
    saved = [d for d in dates if any(r["target"] == d and r["kind"] == "事前" for r in allrec)]
    status = {d: check_status(log_dir, d) for d in saved}
    days_formal = [d for d in saved if status[d] == "一致"]
    excluded = {k: [d for d in saved if status[d] == k] for k in ("不一致", "未发出", "未核对")}
    preds = [(d, x) for d in days_formal for x in next(r for r in allrec if r["target"] == d and r["kind"] == "事前")["predictions"]]
    cnt = dict.fromkeys(list(OUTCOME) + ["漏答"], 0)
    for d, x in preds:
        o = obs_by.get(d)
        c = o["outcomes"].get(x["id"]) if o else None
        cnt[c or "漏答"] += 1
    judge = cnt["A"] + cnt["B"] + cnt["C"]
    L.append(f"事前保存 {len(saved)} 天，其中发送和保存核对一致、进正式对照的 {len(days_formal)} 天"
             + "".join(f"；{k} {len(v)} 天（{'、'.join(v[-3:])}）" for k, v in excluded.items() if v)
             + "，没核对一致的都不计入下面的数字。")
    L.append(f"正式对照共 {len(preds)} 条观察（预期发生 {len(preds)} 条，预期不发生 0 条：现有规则没有这类）。")
    L.append(f"能判断 {judge} 条：自然发生 {cnt['A']}，受阅读影响发生 {cnt['B']}，没发生 {cnt['C']}；"
             f"无法判断 {cnt['D']}，没有相关机会 {cnt['E']}，漏答 {cnt['漏答']}。后两类和漏答不算命中也不算落空。")
    L.append("分类别对比（发生天数 / 有效天数；有效天数只算回答了第二段、没写「记不清」的日子；"
             "各规则版本的事件界定不同，分开列）：")
    answered = [d for d in days_formal if d in obs_by and obs_by[d]["events"] and obs_by[d]["events"] != ["unknown"]]
    unknown = sum(1 for d in days_formal if d in obs_by and obs_by[d]["events"] == ["unknown"])
    rec_of = {d: next(r for r in allrec if r["target"] == d and r["kind"] == "事前") for d in days_formal}
    for ver in dict.fromkeys(rec_of[d]["rule_version"] for d in answered):
        vd = [d for d in answered if rec_of[d]["rule_version"] == ver]
        L.append(f"规则 {ver}（{len(vd)} 天）")
        for k, e in P.events_for(ver).items():
            pd = [d for d in vd if any(x["event"] == k for x in rec_of[d]["predictions"])]
            nd = [d for d in vd if d not in pd]

            def happened(d):
                if k == "pressure":
                    return rated.get(d, {}).get("pressure") == "A"
                return k in obs_by[d]["events"]

            L.append(f"- {e['name']}：有预测的日子 {sum(map(happened, pd))}/{len(pd)}，"
                     f"没预测的日子 {sum(map(happened, nd))}/{len(nd)}")
    if unknown:
        L.append(f"第二段写「记不清」的 {unknown} 天，不进上面的分母。")
    obs_in = [obs_by[d] for d in days_formal if d in obs_by]
    L.append("日报的影响（分开记，不和准不准混算）：因日报做了些什么 "
             f"{sum(o['acted'] == 'B' for o in obs_in)} 天；效果：有具体帮助 {sum(o['effect'] == 'A' for o in obs_in)} 天，"
             f"没什么影响 {sum(o['effect'] == 'B' for o in obs_in)} 天，添了担心、反复查看或拖延 {sum(o['effect'] == 'C' for o in obs_in)} 天。")
    late = [r["target"] for r in allrec if r["kind"] == "回看" and r["target"] in dates]
    missed = [d for d in days_formal if d not in obs_by]
    no_save = [d for d in dates if d in obs_by and d not in saved]
    kinds = {}
    for f in flags:
        kinds.setdefault(f["kind"], []).append(f["date"])
    L.append("运行情况：" + "；".join(
        [f"{k} {len(v)} 次（{'、'.join(v[-3:])}）" for k, v in kinds.items() if k != "生成晚了" and not k.startswith("核对")]
        + [f"生成晚了（回看样本，不计入）{len(late)} 天", f"没有事前保存却有回答 {len(no_save)} 天", f"漏答 {len(missed)} 天"]))
    L.append("这一轮是带着日报读的探索记录：看了预测再过一天，本身会影响注意到什么，所以这些数字不能当成验证结论。")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["save", "review", "record", "summary", "flag", "verify", "status"])
    ap.add_argument("--log-line", help="verify：工作流日志里带「指纹」的那一行，原样传进来")
    ap.add_argument("--missing", help="verify：找不到可核对的日志时写原因，这一天记为未核对")
    ap.add_argument("--date")
    ap.add_argument("--log-dir")
    ap.add_argument("--answer")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--kind")
    ap.add_argument("--note", default="")
    args = ap.parse_args()
    now = _now()
    date = datetime.date.fromisoformat(args.date) if args.date else now.date()
    if args.cmd != "review" and not args.log_dir:
        sys.exit("要写存档或读存档，必须用 --log-dir 指定目录")
    p = D.load_profiles()[0]
    if args.cmd == "save":
        rec, msg = save(p, date, args.log_dir, now)
        print(msg)
    elif args.cmd == "review":
        txt, keys = review_prompt(p, date, args.log_dir)
        print(txt)
        print(keys)
    elif args.cmd == "record":
        ok, msg = record(p, date, args.answer or "", args.log_dir, now)
        print(msg)
        if not ok:
            sys.exit(2)
    elif args.cmd == "summary":
        start = None if args.all else now.date() - datetime.timedelta(days=args.days)
        print(summary(args.log_dir, start, today=now.date()))
    elif args.cmd == "status":
        r = formal(args.log_dir, date)
        print(f"{date}：{'有事前记录，指纹 ' + r['fingerprint'] if r else '没有事前记录'}；核对：{check_status(args.log_dir, date)}")
    elif args.cmd == "verify":
        st, msg = verify(date, args.log_dir, args.log_line, args.missing, now)
        print(f"{date} 核对结果：{st}（{msg}）")
    elif args.cmd == "flag":
        flag(date, args.kind or "其他", args.note, args.log_dir, now)
        print("已记标记")


if __name__ == "__main__":
    main()
