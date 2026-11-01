#!/usr/bin/env python3
"""
预测实验的存档、复盘和汇总（预测本身见 predict.py）。

数据不进公开仓库，放在 --log-dir 指定的目录（项目共享文件夹 mingpan/验证/），全部只追加：
  predictions.jsonl   每天的预测，事前保存。字段：generated_at、target、rule_version、kind、fingerprint、全文等
                      kind：事前（目标日期开始前保存，计入统计）/ 回看（目标日期开始后才算的，只展示不计入）
                            / 更正（同一天内容变了，追加一条更正，原来那条照旧算数）
  observations.jsonl  每晚的回答：中立勾选的事件（第 6 题）、每条预测的判断（7、8）、日报的影响（9、10）、事实备注；
                      补答时追加一条合并后的完整记录，以最后一条为准；没答的题留空，不当「没发生」
  ratings.csv         原来的五道固定题加具体题（11-14），列不变；整体 A-E 存成 1-5；没答的留空
  flags.jsonl         程序故障、漏发等标记
  verifications.jsonl 发送和保存是不是同一份：日报工作流日志里打印「预测版本、条数、指纹、提交」，
                      21:37 的任务把那一行原样交给 verify，和事前保存的指纹比对。结果只有三种：
                      一致（计入正式对照）/ 不一致、未发出、未核对（都排除在正式对照之外，汇总里单列）
存档里只有日期、规则、命理依据和预测文字，没有出生资料，也没有任何密钥。

用法（都在 mingpan 目录下运行）：
  python3 experiment.py save    --date 2026-10-28 --log-dir DIR    事前保存（已存在就沿用，不覆盖）
  python3 experiment.py review  --date 2026-10-28 [--log-dir DIR]  打印当晚复盘题
  python3 experiment.py record  --date 2026-10-28 --answer "1C 2B 3A 4B 5B 6D 7A 9A 10B 备注：客户改到周五" --log-dir DIR
                               逐题回答（题号+选项，可只答一部分以后补；补答不覆盖已记的题，冲突报错，要改加 --correct）；
                               老格式「3BCBA ABBA / 13 / A / AB」照收
  python3 experiment.py check   --date 2026-10-28 --answer "…" [--log-dir DIR]  只解析、念给命主确认，不写任何东西
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
import unicodedata
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


# 逐题选择题（2026-11-01 起）：题号固定，回「题号+选项」，像 1C 2B 6AD；老的「3BCBA ABBA / 13 / A / AB」照收。
# 1-5 基础题，6 实际发生了哪些（多选），7、8 当天事前观察（没有就不答），9、10 日报的影响，11-14 选答（时辰和命理细项）。
BASIC = [("overall", "整体感受", [("A", "很差"), ("B", "偏差"), ("C", "一般"), ("D", "不错"), ("E", "很好")]),
         ("pressure", "压力", [("A", "很大"), ("B", "有一些"), ("C", "基本没有")]),
         ("energy", "精力", [("A", "很累或身体不舒服"), ("B", "一般"), ("C", "精力好")]),
         ("people", "人际", [("A", "有摩擦或是非"), ("B", "平常"), ("C", "顺，有人帮忙")]),
         ("helpful", "日报", [("A", "有用，照着做了"), ("B", "看了，没怎么用上"), ("C", "没看")])]
# 第 6 题选项对应 predict.CHECKLIST 的顺序；例子只解释标准，不是说今天发生过
EVENT_EXAMPLE = {"contact": "老朋友来电问近况算；群消息、广告、工作通知不算",
                 "help": "有人发来有用的资料算；点赞、客套话、付钱买的服务不算",
                 "friction": "为金额、期限明确争执或被明确指责算；礼貌的拒绝、一般意见不同、只是觉得语气不好不算",
                 "reschedule": "对方临时改约、临时塞来当天要办的事算；自己拖延、自己改计划不算",
                 "money": "计划外的退款、罚款、有人开口借钱算；已知账单、自己的消费不算"}
EXAMPLE_BY_VERSION = {"v1": {"friction": "明确争执、被当面拒绝、说话不愉快算；正常讨论的分歧、猜对方语气不算"}}   # 按存档的规则版本
EV_NONE, EV_UNKNOWN = "F", "G"
OUTCOME_OPTS = [("A", "发生了，自然发生的"),
                ("B", "发生了，是看了日报后自己行动促成的（例：看了日报主动约人谈，对方才给了资料）"),
                ("C", "没发生（提前注意了所以没发生，也选 C）"), ("D", "说不清"),
                ("E", "没有相关机会（例：今天整天没碰上相关的人和事）")]
Q_EVENTS, Q_OBS, Q_ACTED, Q_EFFECT = 6, (7, 8), 9, 10
SPEC_KEYS = ["good_hour", "bad_hour", "control_hour", "claim"]          # 11-14
Q_SPEC = {k: n for n, k in enumerate(SPEC_KEYS, 11)}
OLD_RE = re.compile(r"^([1-5])\s*([ABCabc])([ABCabc])([ABCabc])([ABCabc])(?:\s+([ABCabc]+)(?=\s|$))?\s*(.*)$", re.S)


def questions(p, target, log_dir=None):
    """这一天的题目表（题号固定）。返回 (题目列表, 当天预测记录, 具体题)。没有的题 available=False。"""
    rec = day_record(p, target, log_dir)
    spec = {k: (q, opts) for k, q, opts in D.review(p, target)}
    evs = P.events_for(rec["rule_version"])
    qs = [dict(n=n, key=k, title=t, opts=o, multi=False, available=True) for n, (k, t, o) in enumerate(BASIC, 1)]
    ex = {**EVENT_EXAMPLE, **EXAMPLE_BY_VERSION.get(rec["rule_version"], {})}
    opts = [("ABCDE"[i], f"{evs[k]['short']}（例：{ex[k]}）") for i, k in enumerate(P.CHECKLIST)]
    qs.append(dict(n=Q_EVENTS, key="events", title="今天实际发生了哪些（多选，字母连写，如 6AD；先照实记，别回头看预测）",
                   opts=opts + [(EV_NONE, "以上都没有"), (EV_UNKNOWN, "记不清")], multi=True, available=True))
    preds = rec["predictions"]
    for i, n in enumerate(Q_OBS):
        x = preds[i] if i < len(preds) else None
        qs.append(dict(n=n, key=x["id"] if x else f"obs{i + 1}", pred=x, opts=OUTCOME_OPTS, multi=False,
                       available=bool(x), title=f"观察{i + 1}「{evs[x['event']]['short']}」" if x else ""))
    qs.append(dict(n=Q_ACTED, key="acted", title="今天有没有因为日报做了什么", multi=False, available=True,
                   opts=[("A", "没有"), ("B", "有（例：照日报先把账核了一遍）")]))
    qs.append(dict(n=Q_EFFECT, key="effect", title="日报对你的效果", multi=False, available=True,
                   opts=[("A", "有具体帮助"), ("B", "没什么影响"), ("C", "添了担心、反复查看或拖延")]))
    for k in SPEC_KEYS:
        q, o = spec.get(k, ("", ""))
        qs.append(dict(n=Q_SPEC[k], key=k, title=q, multi=False, available=bool(q), optional=True,
                       opts=[(x[0], x[2:]) for x in o.split("　") if x]))
    return qs, rec, spec


def review_prompt(p, target, log_dir=None):
    """当晚复盘题：逐题编号、每个选项一行。返回 (文字, KEYS 行)。只读，不写存档。"""
    qs, rec, spec = questions(p, target, log_dir)
    preds = rec["predictions"]

    def block(q):
        return ["", f"**{q['n']}. {q['title']}**"] + [f"- {a} {t}" for a, t in q["opts"]]

    L = [f"**{target.month}/{target.day} 复盘**（选择题）回复题号加选项，例如 `1C 2B 3A`，多选题字母连写如 `6AD`；"
         "可以换行，大小写、中文标点都行。先答前 5 题也可以，其余可稍后补。", "", "**—— 基础题 ——**"]
    for q in qs[:5]:
        L += block(q)
    L += ["", "**—— 实际发生 ——**（例子只是解释标准，不是说今天发生过）"] + block(qs[5])
    L += ["", "**—— 对一下观察 ——**（当天事前保存的观察，每条选一个）"]
    if preds:
        for q in qs[6:8]:
            if q["available"]:
                L += block(q)
        if len(preds) < 2:
            L += ["", "（第 8 题这一天没有，不用答。）"]
    else:
        L.append(f"这一天没有观察项：{rec['none_reason']}第 7、8 题不用答。")
    if rec["kind"] != "事前":
        L.append(f"（这一天的预测是{'回看样本' if rec['kind'] == '回看' else '现算的，没有事前保存'}，照样记，但不计入统计。）")
    elif check_status(log_dir, target) != "一致":
        L.append(f"（这一天发出去的和事前保存的还没核对上：{check_status(log_dir, target)}。照样记，核对不上就不计入正式对照。）")
    L += ["", "**—— 日报的影响 ——**"] + block(qs[8]) + block(qs[9])
    L += ["", "**—— 选答 ——**（时辰和命理细项，可以稍后补）"]
    for q in qs[10:]:
        L += block(q) if q["available"] else ["", f"**{q['n']}.** 这一天没有这题。"]
    L += ["", "最后可以写「备注：一句事实」，比如「备注：客户临时改到周五」。"]
    keys = "KEYS " + "|".join(f"{k}={spec[k][0]}" for k in SPEC_KEYS if k in spec)
    return "\n".join(L), keys


# ---------- 记录回答 ----------

def _old_to_new(qs, rec, s):
    """老格式（3BCBA ABBA，或加三段斜杠）换成逐题答案字符串；返回 (字符串, 错误)。"""
    parts = [x.strip() for x in s.replace("／", "/").split("/", 3)]
    m = OLD_RE.match(parts[0])
    if not m:
        return None, ["第一段要像 3BCBA ABBA：先一个 1 到 5 的数字，再四个 A/B/C 字母，空格后是具体题的字母"]
    errs = []
    toks = [f"1{'ABCDE'[int(m.group(1)) - 1]}"] + [f"{n}{m.group(n)}" for n in range(2, 6)]
    spec_keys = [q["key"] for q in qs[10:] if q["available"]]
    spec = (m.group(6) or "").upper()
    if len(spec) > len(spec_keys):
        errs.append(f"具体题只有 {len(spec_keys)} 道，答了 {len(spec)} 个字母")
    toks += [f"{Q_SPEC[k]}{v}" for k, v in zip(spec_keys, spec)]
    note = m.group(7).strip()
    if len(parts) > 1:
        if note:
            errs.append(f"第一段多了文字「{note}」，事实备注请放在最后")
        if len(parts) < 4:
            return None, errs + ["新格式要四段：老题 / 发生了哪些 / 观察判断 / 影响"]
        ev = parts[1].replace(" ", "").replace("？", "?")
        if ev == "0":
            toks.append(f"{Q_EVENTS}{EV_NONE}")
        elif ev == "?":
            toks.append(f"{Q_EVENTS}{EV_UNKNOWN}")
        elif re.fullmatch(r"[1-5]+", ev):
            toks.append(f"{Q_EVENTS}" + "".join("ABCDE"[int(c) - 1] for c in dict.fromkeys(ev)))
        else:
            errs.append("第二段写 1 到 5 的数字（可多选），都没有写 0，记不清写 ?")
        oc, preds = parts[2].replace(" ", "").upper(), rec["predictions"]
        if not preds:
            if oc not in ("-", ""):
                errs.append("这一天没有观察项，第三段写 - 就行")
        elif len(oc) != len(preds) or any(c not in OUTCOME for c in oc):
            errs.append(f"第三段要 {len(preds)} 个字母（A 到 E），每条观察一个")
        else:
            toks += [f"{n}{c}" for n, c in zip(Q_OBS, oc)]
        m4 = re.match(r"^([ABab])\s*([ABCabc])\s*(.*)$", parts[3], re.S)
        if not m4:
            errs.append("第四段先写两个字母：① A 没有 / B 有，② A 有帮助 / B 没影响 / C 添担心")
        else:
            toks += [f"{Q_ACTED}{m4.group(1).upper()}", f"{Q_EFFECT}{m4.group(2).upper()}"]
            note = m4.group(3).strip()
    return " ".join(toks) + (f" 备注：{note}" if note else ""), errs


DATE_RE = re.compile(r"^\s*(?:(\d{4})\s*[-/.年]\s*)?(\d{1,2})\s*[/月.-]\s*(\d{1,2})\s*[日号]?\s*(?:复盘)?[:：，,\s]")


def parse(p, target, raw, log_dir=None):
    """解析回答（逐题格式或老格式）。返回 (答案 {题号: 字母}, 备注, 错误列表, 题目表, 预测记录)。不写任何东西。"""
    qs, rec, _ = questions(p, target, log_dir)
    raw_body, raw_note = (re.split(r"备注\s*[:：]?", raw or "", maxsplit=1) + [None])[:2]
    s = unicodedata.normalize("NFKC", raw_body).strip()     # 备注原样保留，只把答案部分的全角字母、数字换成半角
    if not s and not raw_note:
        return {}, "", ["回答是空的"], qs, rec
    if OLD_RE.match(s.split("/")[0].strip()):
        s, errs = _old_to_new(qs, rec, s)
        if s is None:
            return {}, "", errs, qs, rec
    else:
        errs = []
    m = DATE_RE.match(s + " ")
    if m:
        y = int(m.group(1)) if m.group(1) else target.year
        try:
            d = datetime.date(y, int(m.group(2)), int(m.group(3)))
        except ValueError:
            d = None
        if d != target:
            errs.append(f"回答里写的日期是 {m.group(0).strip()}，要记的是 {target.month}/{target.day}，请确认是哪一天")
        s = s[m.end() - 1:] if m.end() <= len(s) else ""
    body, note = (re.split(r"备注\s*[:：]?", s, maxsplit=1) + [""])[:2]
    if raw_note is not None:
        note = raw_note
    body = re.sub(r"[第题]", " ", body)
    body = re.sub(r"[,，。.;；、:：!！\s]+", " ", body).upper()
    byn = {q["n"]: q for q in qs}
    ans, spans = {}, []
    for m in re.finditer(r"(\d{1,2})\s*([A-Z](?:\s*[A-Z])*)", body):
        spans.append(m.span())
        n, v = int(m.group(1)), re.sub(r"\s", "", m.group(2))
        q = byn.get(n)
        if not q:
            errs.append(f"没有第 {n} 题（题号是 1 到 14）")
            continue
        if not q["available"]:
            errs.append(f"这一天没有第 {n} 题（{'当天只有 ' + str(len(rec['predictions'])) + ' 条观察' if n in Q_OBS else '当天没有这道选答题'}）")
            continue
        valid = [a for a, _ in q["opts"]]
        bad = [c for c in v if c not in valid]
        if bad:
            errs.append(f"第 {n} 题没有选项 {''.join(bad)}（可选 {valid[0]}–{valid[-1]}）")
            continue
        v = "".join(dict.fromkeys(v)) if q["multi"] else v
        if not q["multi"] and len(v) > 1:
            errs.append(f"第 {n} 题只能选一个，写了 {v}")
            continue
        if q["multi"] and len(v) > 1 and (EV_NONE in v or EV_UNKNOWN in v):
            errs.append(f"第 {n} 题选了 {EV_NONE}（都没有）或 {EV_UNKNOWN}（记不清）就不能再选别的")
            continue
        if n in ans and ans[n] != v:
            errs.append(f"第 {n} 题写了两次（{ans[n]} 和 {v}），请只留一个")
            continue
        ans[n] = v
    rest = body
    for a, b in reversed(spans):
        rest = rest[:a] + " " + rest[b:]
    if rest.strip():
        errs.append(f"看不懂「{rest.strip()}」：每题写题号加字母，如 1C；一句事实请写在「备注：」后面")
    if not ans and not note.strip() and not errs:
        errs.append("没找到任何答案，要写成题号加字母，如 1C 2B")
    return ans, note.strip(), errs, qs, rec


def existing(p, target, log_dir, qs=None, rec=None):
    """存档里这一天已经记下的答案，换成 {题号: 字母} 和备注。"""
    if qs is None:
        qs, rec, _ = questions(p, target, log_dir)
    out, note = {}, ""
    path = Path(log_dir) / "ratings.csv"
    row = next((r for r in csv.DictReader(path.open(encoding="utf-8")) if r["date"] == str(target)), None) \
        if path.exists() else None
    if row:
        if row.get("overall"):
            out[1] = "ABCDE"[int(row["overall"]) - 1]
        for n, (k, _, _) in enumerate(BASIC[1:], 2):
            if row.get(k):
                out[n] = row[k]
        for k, n in Q_SPEC.items():
            if row.get(k):
                out[n] = row[k]
        note = row.get("note", "")
    obs = [o for o in _read(Path(log_dir) / "observations.jsonl") if o["date"] == str(target)]
    if obs:
        o = obs[-1]
        ev = o.get("events") or []
        if ev == ["none"]:
            out[Q_EVENTS] = EV_NONE
        elif ev == ["unknown"]:
            out[Q_EVENTS] = EV_UNKNOWN
        elif ev:
            out[Q_EVENTS] = "".join("ABCDE"[P.CHECKLIST.index(k)] for k in ev)
        for q in qs[6:8]:
            if q["available"] and o.get("outcomes", {}).get(q["key"]):
                out[q["n"]] = o["outcomes"][q["key"]]
        if o.get("acted"):
            out[Q_ACTED] = o["acted"]
        if o.get("effect"):
            out[Q_EFFECT] = o["effect"]
        note = o.get("note") or note
    return out, note


SHORT = {Q_EVENTS: "实际发生", Q_ACTED: "因日报做了什么", Q_EFFECT: "日报的效果", 11: "好时辰", 12: "避开时辰",
         13: "对照时辰", 14: "最重的一条说法"}


def describe(qs, ans, note=""):
    """把答案逐题念出来，方便确认；没答的列出题号。"""
    L = []
    for q in qs:
        if q["n"] in ans:
            opt = dict(q["opts"])
            L.append(f"{q['n']}. {SHORT.get(q['n'], q['title'])}：" + "、".join(f"{c} {opt[c].split('（')[0]}" for c in ans[q["n"]]))
    todo = [str(q["n"]) for q in qs if q["available"] and q["n"] not in ans]
    if note:
        L.append(f"备注：{note}")
    L.append("还没答：" + ("、".join(todo) if todo else "无") + ("（其中 11 以后是选答）" if any(int(x) > 10 for x in todo) else ""))
    return "\n".join(L)


def build_rows(target, qs, rec, ans, note, raw):
    """合并后的答案换成 ratings.csv 一行和 observations 一条（没答 6-10 题就不出观察记录）。缺答留空，不当「没发生」。"""
    row = dict.fromkeys(RATING_COLS, "")
    row.update(date=str(target), note=note)
    if 1 in ans:
        row["overall"] = str("ABCDE".index(ans[1]) + 1)
    for n, (k, _, _) in enumerate(BASIC[1:], 2):
        row[k] = ans.get(n, "")
    for k, n in Q_SPEC.items():
        row[k] = ans.get(n, "")
    row["claim_text"] = next((q["title"] for q in qs if q["key"] == "claim"), "")
    if not any(n in ans for n in range(Q_EVENTS, Q_EFFECT + 1)):
        return row, None
    ev = ans.get(Q_EVENTS, "")
    events = (["none"] if ev == EV_NONE else ["unknown"] if ev == EV_UNKNOWN
              else [P.CHECKLIST["ABCDE".index(c)] for c in ev])
    obs = {"date": str(target), "raw": raw, "format": "逐题", "answered": sorted(ans), "events": events,
           "pressure_high": ans.get(2) == "A" if 2 in ans else None,
           "rule_version": rec["rule_version"], "prediction_kind": rec["kind"], "fingerprint": rec["fingerprint"],
           "outcomes": {q["key"]: ans[q["n"]] for q in qs[6:8] if q["available"] and q["n"] in ans},
           "acted": ans.get(Q_ACTED, ""), "effect": ans.get(Q_EFFECT, ""), "note": note}
    return row, obs


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


def check(p, target, raw, log_dir=None):
    """只解析、合并、念出来，不写任何东西（给命主确认用，也给预览用）。返回 (能不能记, 文字)。"""
    ans, note, errs, qs, rec = parse(p, target, raw, log_dir)
    if errs:
        return False, "；".join(errs)
    old, old_note = existing(p, target, log_dir, qs, rec) if log_dir else ({}, "")
    return True, describe(qs, {**old, **ans}, note or old_note)


def record(p, target, raw, log_dir, now=None, correct=False):
    """记下回答。可以只答一部分、以后补：补答只加没答过的题；和已记的答案冲突就报错，除非 correct=True（命主明确说要改）。"""
    ans, note, errs, qs, rec = parse(p, target, raw, log_dir)
    if errs:
        return False, "；".join(errs)
    old, old_note = existing(p, target, log_dir, qs, rec)
    clash = [f"第 {n} 题已经记过 {old[n]}，这次写的是 {v}" for n, v in sorted(ans.items()) if n in old and old[n] != v]
    if clash and not correct:
        return False, "；".join(clash) + "。要改的话请明确说改哪题，没改的题不动"
    merged = {**old, **ans}
    note = old_note if not note or note == old_note else (f"{old_note}；{note}" if old_note and not correct else note)
    row, obs = build_rows(target, qs, rec, merged, note, raw)
    upsert_rating(row, log_dir)
    if obs and (any(n in ans for n in range(Q_EVENTS, Q_EFFECT + 1)) or note != old_note):
        obs["recorded_at"] = (now or _now()).isoformat(timespec="seconds")
        _append(Path(log_dir) / "observations.jsonl", obs)
    return True, "已记录。\n" + describe(qs, merged, note)


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
    L.append("分类别对比（发生天数 / 有效天数；五类事实只算第 6 题答了 A–E 或 F（都没有）、没选 G（记不清）的日子；"
             "明显事务压力只看第 2 题，答了 A/B/C 的日子才进分母，A「很大」算发生；没答的不进分母；"
             "各规则版本的事件界定不同，分开列）：")
    ev_ok = [d for d in days_formal if d in obs_by and obs_by[d]["events"] and obs_by[d]["events"] != ["unknown"]]
    pr_ok = [d for d in days_formal if rated.get(d, {}).get("pressure") in ("A", "B", "C")]
    unknown = sum(1 for d in days_formal if d in obs_by and obs_by[d]["events"] == ["unknown"])
    rec_of = {d: next(r for r in allrec if r["target"] == d and r["kind"] == "事前") for d in days_formal}
    for ver in dict.fromkeys(rec_of[d]["rule_version"] for d in sorted(ev_ok + pr_ok)):
        ve = [d for d in ev_ok if rec_of[d]["rule_version"] == ver]
        vp = [d for d in pr_ok if rec_of[d]["rule_version"] == ver]
        L.append(f"规则 {ver}（第 6 题有效 {len(ve)} 天，第 2 题有效 {len(vp)} 天）")
        for k, e in P.events_for(ver).items():
            vd = vp if k == "pressure" else ve
            pd = [d for d in vd if any(x["event"] == k for x in rec_of[d]["predictions"])]
            nd = [d for d in vd if d not in pd]

            def happened(d):
                if k == "pressure":
                    return rated[d]["pressure"] == "A"
                return k in obs_by[d]["events"]

            L.append(f"- {e['name']}：有预测的日子 {sum(map(happened, pd))}/{len(pd)}，"
                     f"没预测的日子 {sum(map(happened, nd))}/{len(nd)}")
    if unknown:
        L.append(f"第 6 题选「记不清」的 {unknown} 天，不进五类事实的分母。")
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
    ap.add_argument("cmd", choices=["save", "review", "record", "check", "summary", "flag", "verify", "status"])
    ap.add_argument("--correct", action="store_true", help="record：命主明确要改已记的答案时才用")
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
    if args.cmd not in ("review", "check") and not args.log_dir:
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
        ok, msg = record(p, date, args.answer or "", args.log_dir, now, args.correct)
        print(msg)
        if not ok:
            sys.exit(2)
    elif args.cmd == "check":
        ok, msg = check(p, date, args.answer or "", args.log_dir)
        print(("可以记：\n" if ok else "有问题：") + msg)
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
