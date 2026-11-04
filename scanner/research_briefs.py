#!/usr/bin/env python3
"""
本机 AI 研究简报：本站每日扫描快照 → 公开证据包 → 本机已登录 Claude CLI 起草 → 独立审阅 accept → 建站读入。
用法（在仓库根目录运行，日期为数据日期）：
  python scanner/research_briefs.py prepare  --date 2026-11-04     # 校验快照，导出证据包到 .local-briefs/
  python scanner/research_briefs.py generate --date 2026-11-04     # 调用 Claude CLI 生成草稿（每个日期只生成一次）
  python scanner/research_briefs.py validate --date 2026-11-04     # 校验草稿，打印报告哈希
  python scanner/research_briefs.py accept   --date 2026-11-04 --reviewer Codex --report-sha256 <validate 打印的哈希>
  python scanner/research_briefs.py status                         # 列出草稿与已验收报告
草稿、CLI 原始回执只在 .local-briefs/（已 gitignore）；已验收报告在 briefs/accepted/，建站时由 build_pages() 重新校验后发布。
schema、哈希语义和校验规则见 docs/research-briefs.md。纯标准库。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

USER_TZ = ZoneInfo("Asia/Bangkok")  # 用户所在时区：生成/审阅时点与"今天/未来"门禁都按曼谷时间；data_date 仍是中国交易日
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LOCAL_DIR = ROOT / ".local-briefs"
ACCEPTED_DIR = ROOT / "briefs" / "accepted"
DEFAULT_CLAUDE = "D:/npm-global/node_modules/@anthropic-ai/claude-code/bin/claude.exe"

EVIDENCE_SCHEMA = "futures-brief-evidence/1"
REPORT_SCHEMA = "futures-brief-report/1"
ACCEPTED_SCHEMA = "futures-brief-accepted/1"
SOURCE_LABEL = "本站新浪财经/akshare扫描快照"
VERIFICATION = "未做交易所或第二来源核对；数值为本站扫描原值"
TIME_NOTE = "快照只记录扫描日期，没有精确扫描时刻"
MIN_VALID = 50  # 与 daily.yml 数据到齐门槛一致
PATTERNS = ["高富帅", "白富美", "上涨乏力", "下跌乏力", "虚涨分歧", "虚跌分歧", "涨势将尽", "跌势将尽"]
PAT_IDS = dict(zip(PATTERNS, ["gfs", "bfm", "szfl", "xdfl", "xzfq", "xdfq", "zsjj", "dsjj"]))
PICK_N = 3
SECTIONS = [("summary", "摘要", 1, 3), ("interpretation", "AI 解读", 1, 5), ("uncertainties", "仍不确定", 1, 4), ("next_checks", "下次需核对的问题", 1, 4)]
BANNED = ["买入", "卖出", "开仓", "加仓", "建仓", "平仓", "止损", "止盈", "抄底", "逢低", "逢高", "做多", "做空",
          "推荐", "建议", "目标价", "胜率", "仓位", "必然", "稳赚", "策略有效"]
BAD_TEXT = re.compile(r"[<>`/\\]|https?:|www\.|javascript:|vbscript:|data:|file:", re.I)
BRIEF_ID = re.compile(r"^brief-(\d{4}-\d{2}-\d{2})$")
FACT_ID = re.compile(r"^[a-z]+\.[A-Za-z0-9_]+$")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-\[\]]{0,79}$")
REVIEWER = re.compile(r"^[A-Za-z0-9_\- \u4e00-\u9fff]{1,40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
CLOCK_SKEW = timedelta(minutes=10)


class BriefError(ValueError):
    pass


# ---------- 规范化与哈希 ----------
def canonical(obj):
    """规范字节：UTF-8、键排序、无空白、禁止 NaN/Infinity。所有内容哈希都基于它"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_obj(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def source_sha256(path):
    """源文件哈希：原始字节把 CRLF 统一成 LF 后取 SHA-256（= git 仓库内内容，Windows 与 Actions 一致）"""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _reject_constant(c):
    raise BriefError(f"JSON 含非法数值 {c}")


def _no_dup_keys(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise BriefError(f"JSON 键重复：{k}")
        d[k] = v
    return d


def strict_loads(text):
    try:
        return json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_no_dup_keys)
    except json.JSONDecodeError as e:
        raise BriefError(f"JSON 格式错误：{e}") from None


def _write_atomic(path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _dump(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _now():
    return datetime.now(USER_TZ)


def _is_date(s):
    try:
        return isinstance(s, str) and date.fromisoformat(s).isoformat() == s
    except ValueError:
        return False


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _ts(s, what):
    """带时区的 ISO 时间"""
    try:
        t = datetime.fromisoformat(s) if isinstance(s, str) else None
    except ValueError:
        t = None
    if t is None or t.tzinfo is None:
        raise BriefError(f"{what} 不是带时区的 ISO 时间")
    return t


def _keys(obj, required, what, optional=()):
    if not isinstance(obj, dict):
        raise BriefError(f"{what} 不是对象")
    extra = set(obj) - set(required) - set(optional)
    missing = set(required) - set(obj)
    if extra:
        raise BriefError(f"{what} 含未知字段：{sorted(extra)}")
    if missing:
        raise BriefError(f"{what} 缺少字段：{sorted(missing)}")


def brief_id_for(d):
    if not _is_date(d):
        raise BriefError(f"日期格式无效：{d!r}")
    return f"brief-{d}"


# ---------- 快照校验与证据包 ----------
def load_snapshot(data_dir, d, today=None):
    """读取并严格校验 data/<d>.json；返回 (快照, 源相对路径, 源哈希)"""
    brief_id_for(d)
    today = today or _now().date()
    path = Path(data_dir) / f"{d}.json"
    if not path.is_file():
        raise BriefError(f"快照不存在：data/{d}.json")
    raw = path.read_bytes()
    if not raw.strip():
        raise BriefError("快照为空文件")
    try:
        snap = strict_loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise BriefError("快照不是 UTF-8") from None
    req = ["scan_date", "data_date", "market", "total_scanned", "valid_count", "error_count", "up_count", "down_count",
           "strong_count", "patterns", "all_results"]
    if not isinstance(snap, dict) or any(k not in snap for k in req):
        raise BriefError("快照缺少必需字段")
    dd, sd = snap["data_date"], snap["scan_date"]
    if dd != d:
        raise BriefError(f"快照 data_date={dd!r} 与文件名日期 {d} 不一致")
    if not _is_date(sd) or sd < dd:
        raise BriefError(f"scan_date={sd!r} 无效或早于数据日期")
    if date.fromisoformat(dd) > today or date.fromisoformat(sd) > today:
        raise BriefError("快照日期晚于今天（未来日期）")
    for k in ["total_scanned", "valid_count", "error_count", "up_count", "down_count", "strong_count"]:
        if not _int(snap[k]):
            raise BriefError(f"{k} 不是非负整数")
    res = snap["all_results"]
    if not isinstance(res, list) or not res:
        raise BriefError("all_results 为空")
    if snap["valid_count"] != len(res) or snap["total_scanned"] != snap["valid_count"] + snap["error_count"]:
        raise BriefError("品种数量不一致（valid/total/error 与 all_results）")
    if snap["valid_count"] < MIN_VALID:
        raise BriefError(f"有效品种 {snap['valid_count']} 少于门槛 {MIN_VALID}，数据不完整")
    seen = set()
    for i, r in enumerate(res):
        if not isinstance(r, dict):
            raise BriefError(f"all_results[{i}] 不是对象")
        sym = r.get("symbol")
        if not isinstance(sym, str) or not re.fullmatch(r"[A-Z]{1,3}0", sym):
            raise BriefError(f"all_results[{i}] 品种代码无效")
        if sym in seen:
            raise BriefError(f"品种重复：{sym}")
        seen.add(sym)
        if r.get("date") != dd:
            raise BriefError(f"{sym} 的日期 {r.get('date')!r} 与数据日期不一致")
        for k in ["today_close", "prev_close", "price_change_pct", "hold_change_pct", "mom20", "today_hold", "prev_hold", "today_vol"]:
            if not _num(r.get(k)):
                raise BriefError(f"{sym}.{k} 不是有限数值")
        for k in ["name", "exchange"]:
            if not isinstance(r.get(k), str) or not r[k]:
                raise BriefError(f"{sym}.{k} 缺失")
        if r.get("pattern") not in PATTERNS + ["未分类"]:
            raise BriefError(f"{sym}.pattern 未知")
        dims = r.get("dims")
        if not isinstance(dims, dict) or not all(isinstance(dims.get(k), str) for k in ("price", "vol", "hold")):
            raise BriefError(f"{sym}.dims 无效")
    if snap["up_count"] != sum(r["price_change_pct"] > 0 for r in res) or snap["down_count"] != sum(r["price_change_pct"] < 0 for r in res):
        raise BriefError("涨跌家数与逐品种涨跌幅不一致")
    if snap["strong_count"] != sum(r.get("is_strong") is True for r in res):
        raise BriefError("强信号数与逐品种标记不一致")
    pats = snap["patterns"]
    if not isinstance(pats, dict) or set(pats) != set(PATTERNS):
        raise BriefError("patterns 必须恰好为八种形态")
    for p in PATTERNS:
        v = pats[p]
        items = v.get("items") if isinstance(v, dict) else None
        if not isinstance(items, list) or not _int(v.get("count")) or v["count"] != len(items):
            raise BriefError(f"形态 {p} 计数无效")
        if sorted(i.get("symbol") for i in items) != sorted(r["symbol"] for r in res if r["pattern"] == p):
            raise BriefError(f"形态 {p} 成员与逐品种形态不一致")
    m = snap["market"]
    if not isinstance(m, dict) or not _num(m.get("mom20_median")) or m.get("regime") not in ("强势", "弱势"):
        raise BriefError("market 字段无效")
    if (m["mom20_median"] < 0) != (m["regime"] == "弱势"):
        raise BriefError("市场环境与 20 日动量中位数不一致")
    return snap, f"data/{d}.json", source_sha256(path)


def _fact(fid, group, label, value, unit, field, **extra):
    return {"fact_id": fid, "group": group, "label": label, "value": value, "unit": unit, "source_field": field, **extra}


def build_evidence(snap, rel, src_hash):
    """证据包：全部取快照原值，不计算新指标、不给买卖判断；fact_id 固定"""
    d = snap["data_date"]
    m = snap["market"]
    facts = [
        _fact("cov.valid", "coverage", "有效品种数", snap["valid_count"], "个", "valid_count"),
        _fact("cov.total", "coverage", "扫描品种数", snap["total_scanned"], "个", "total_scanned"),
        _fact("cov.errors", "coverage", "获取失败品种数", snap["error_count"], "个", "error_count"),
        _fact("breadth.up", "breadth", "上涨品种数", snap["up_count"], "个", "up_count"),
        _fact("breadth.down", "breadth", "下跌品种数", snap["down_count"], "个", "down_count"),
        _fact("mkt.mom20_median", "market", "全部品种 20 日动量中位数", m["mom20_median"], "%", "market.mom20_median"),
        _fact("mkt.regime", "market", "市场环境（中位数<0 为弱势）", m["regime"], None, "market.regime"),
        _fact("sig.strong", "signal", "双20%强信号品种数", snap["strong_count"], "个", "strong_count"),
    ]
    for p in PATTERNS:
        v = snap["patterns"][p]
        names = "、".join(f"{i.get('name')}" for i in v["items"]) or "无"
        facts.append(_fact(f"pat.{PAT_IDS[p]}", "pattern", f"形态「{p}」品种数", v["count"], "个",
                           f"patterns.{p}.count", detail=names))
    res = sorted(snap["all_results"], key=lambda r: r["symbol"])
    ups = sorted(res, key=lambda r: -r["price_change_pct"])[:PICK_N]
    downs = sorted(res, key=lambda r: r["price_change_pct"])[:PICK_N]
    for sel, rows in ((f"涨跌幅最大前{PICK_N}", ups), (f"涨跌幅最小前{PICK_N}", downs)):
        for r in rows:
            dims = r["dims"]
            facts.append(_fact(
                f"sym.{r['symbol']}", "symbol", f"{r['name']} {r['symbol']}（{r['exchange']}）",
                {"today_close": r["today_close"], "price_change_pct": r["price_change_pct"], "hold_change_pct": r["hold_change_pct"],
                 "mom20": r["mom20"], "pattern": r["pattern"], "dims": f"{dims['price']}·{dims['vol']}·{dims['hold']}"},
                None, f"all_results[symbol={r['symbol']}]", detail=sel))
    return {
        "schema": EVIDENCE_SCHEMA,
        "brief_id": brief_id_for(d),
        "data_date": d,
        "source": {"path": rel, "sha256": src_hash, "hash_semantics": "sha256(file bytes with CRLF->LF)",
                   "label": SOURCE_LABEL, "verification": VERIFICATION, "scan_date": snap["scan_date"], "scan_time": None,
                   "time_note": TIME_NOTE},
        "selection_note": f"品种事实按 price_change_pct 原值取最大与最小各 {PICK_N} 个（同值按代码排序），只用于挑选展示，不是信号",
        "facts": facts,
    }


SYM_KEYS = ["today_close", "price_change_pct", "hold_change_pct", "mom20", "pattern", "dims"]


def validate_evidence(ev):
    _keys(ev, ["schema", "brief_id", "data_date", "source", "selection_note", "facts"], "证据包")
    if ev["schema"] != EVIDENCE_SCHEMA:
        raise BriefError("证据包 schema 不符")
    m = BRIEF_ID.match(ev["brief_id"] if isinstance(ev["brief_id"], str) else "")
    if not m or m.group(1) != ev["data_date"] or not _is_date(ev["data_date"]):
        raise BriefError("证据包 brief_id 与数据日期不一致")
    src = ev["source"]
    _keys(src, ["path", "sha256", "hash_semantics", "label", "verification", "scan_date", "scan_time", "time_note"], "证据包 source")
    if src["path"] != f"data/{ev['data_date']}.json":
        raise BriefError("证据包来源路径无效")
    if not isinstance(src["sha256"], str) or not HEX64.match(src["sha256"]):
        raise BriefError("证据包来源哈希格式无效")
    ids = set()
    for f in ev["facts"] if isinstance(ev["facts"], list) else [None]:
        _keys(f, ["fact_id", "group", "label", "value", "unit", "source_field"], "事实", optional=["detail"])
        if not isinstance(f["fact_id"], str) or not FACT_ID.match(f["fact_id"]) or f["fact_id"] in ids:
            raise BriefError(f"fact_id 无效或重复：{f['fact_id']!r}")
        ids.add(f["fact_id"])
        v = f["value"]
        if isinstance(v, dict):
            _keys(v, SYM_KEYS, f"事实 {f['fact_id']} 数值")
        elif not (_num(v) or isinstance(v, str)):
            raise BriefError(f"事实 {f['fact_id']} 数值类型无效")
    if not ids:
        raise BriefError("证据包没有事实")
    return ids


def prepare(d, data_dir=DATA_DIR, local_dir=LOCAL_DIR, today=None):
    snap, rel, h = load_snapshot(data_dir, d, today)
    ev = build_evidence(snap, rel, h)
    validate_evidence(ev)
    path = Path(local_dir) / ev["brief_id"] / "evidence.json"
    if path.exists():
        try:
            old = strict_loads(path.read_text(encoding="utf-8"))
        except BriefError:
            old = None
        if old == ev:
            return path, ev, False
        raise BriefError(f"{path} 已存在且内容不同（源快照可能已变化）；不覆盖。确认后手动删除该目录再 prepare")
    _write_atomic(path, _dump(ev))
    return path, ev, True


# ---------- 草稿校验 ----------
NUM_RE = re.compile(r"(?<![\d.])([+\-−－＋]?)(\d+(?:\.\d+)?)")
MINUS = "-−－"
DATE_RE = re.compile(r"\d{4}\s*[-年./]\s*\d{1,2}\s*[-月./]\s*\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*日")
# 引用某类事实时额外允许的指标口径数字：品种事实含「20日动量」，且是按涨跌幅挑选的前 PICK_N 个
CALIBER_NUMS = {"symbol": ("20", str(PICK_N))}


def _dec(x):
    return Decimal(repr(x)) if isinstance(x, float) else Decimal(x)


def fact_numbers(f):
    """一条事实的 (有符号数值集合, 标签/说明/口径中的无符号数字集合)；不含来源哈希等元数据"""
    v = f["value"]
    vals = [v[k] for k in ("today_close", "price_change_pct", "hold_change_pct", "mom20")] if isinstance(v, dict) else [v]
    values = {_dec(x) for x in vals if _num(x)}
    words = f["label"] + " " + (f.get("detail") or "")
    labels = {Decimal(x) for x in re.findall(r"\d+(?:\.\d+)?", words)} | {Decimal(x) for x in CALIBER_NUMS.get(f["group"], ())}
    return values, labels


def check_numbers(text, cited, data_date):
    """文字里的每个数字必须来自本条引用的事实，返回不合规的片段列表：
    - 数值要符号一致：写了负号的必须是负值，写了正号的必须是正值，不带符号的只能对应非负值（负值必须带负号）；
    - 或者是引用事实标签/说明/口径里的数字（如 中证1000、20日、前3）；
    - 日期只允许数据日期本身（显式白名单），其他日期一律不合规。"""
    t = text.replace(data_date, " ")
    m = DATE_RE.search(t)
    if m:
        return [m.group(0)]
    values, labels = set(), set()
    for f in cited:
        v, lb = fact_numbers(f)
        values |= v
        labels |= lb
    bad = []
    for m in NUM_RE.finditer(t):
        sign, n = m.group(1), Decimal(m.group(2))
        if sign and sign in MINUS:
            ok = n != 0 and -n in values
        elif sign:
            ok = n > 0 and n in values
        else:
            ok = n in values or n in labels
        if not ok:
            bad.append(m.group(0))
    return bad


def validate_ai(ai, ev):
    facts = {f["fact_id"]: f for f in ev["facts"]}
    _keys(ai, [k for k, *_ in SECTIONS], "AI 草稿")
    for key, title, lo, hi in SECTIONS:
        items = ai[key]
        if not isinstance(items, list) or not lo <= len(items) <= hi:
            raise BriefError(f"「{title}」条目数应为 {lo}–{hi}")
        for j, it in enumerate(items):
            where = f"「{title}」第 {j + 1} 条"
            _keys(it, ["text", "evidence_ids"], where)
            t, refs = it["text"], it["evidence_ids"]
            if not isinstance(t, str) or not 4 <= len(t.strip()) <= 300 or t != t.strip():
                raise BriefError(f"{where} 文字为空、过长或首尾有空白")
            if BAD_TEXT.search(t) or any(ord(c) < 32 for c in t):
                raise BriefError(f"{where} 含网址、HTML 或控制字符")
            bad = [w for w in BANNED if w in t]
            if bad:
                raise BriefError(f"{where} 含交易建议类用语：{bad}")
            if not isinstance(refs, list) or not 1 <= len(refs) <= 8 or len(set(refs)) != len(refs) or not all(isinstance(r, str) for r in refs):
                raise BriefError(f"{where} 未引用证据或引用格式无效")
            unknown = [r for r in refs if r not in facts]
            if unknown:
                raise BriefError(f"{where} 引用了不存在的 fact_id：{unknown}")
            extra = check_numbers(t, [facts[r] for r in refs], ev["data_date"])
            if extra:
                raise BriefError(f"{where} 含本条引用事实以外的数字、符号不符或其他日期：{extra}")


def validate_report(rep, data_dir=DATA_DIR, now=None):
    """草稿/报告校验：结构、证据包与源快照重新推导一致、AI 条目、生成记录（含提示词哈希重算）。返回报告哈希"""
    now = now or _now()
    _keys(rep, ["schema", "brief_id", "data_date", "evidence", "evidence_sha256", "ai", "generation"], "报告")
    if rep["schema"] != REPORT_SCHEMA:
        raise BriefError("报告 schema 不符")
    ev = rep["evidence"]
    validate_evidence(ev)
    if rep["brief_id"] != ev["brief_id"] or rep["data_date"] != ev["data_date"]:
        raise BriefError("报告与证据包的 brief_id / 数据日期不一致")
    if rep["evidence_sha256"] != sha256_obj(ev):
        raise BriefError("证据包哈希不符（证据被改动）")
    snap, rel, h = load_snapshot(data_dir, rep["data_date"], today=now.astimezone(USER_TZ).date())
    if h != ev["source"]["sha256"]:
        raise BriefError("源快照哈希与证据包记录不一致（源文件已变化）")
    if build_evidence(snap, rel, h) != ev:
        raise BriefError("证据包与源快照重新推导结果不一致")
    validate_ai(rep["ai"], ev)
    g = rep["generation"]
    _keys(g, ["generated_at", "generator", "cli_version", "model", "prompt_version", "prompt_sha256", "raw_receipt_sha256"], "生成记录")
    t = _ts(g["generated_at"], "生成时间")
    if t.astimezone(USER_TZ).date().isoformat() < rep["data_date"] or t > now + CLOCK_SKEW:
        raise BriefError("生成时间早于数据日期（曼谷日期）或晚于当前时间")
    if g["generator"] != "claude-code-cli":
        raise BriefError("生成记录 generator 不符")
    if g["prompt_version"] not in PROMPTS:
        raise BriefError(f"不支持的提示词版本：{g['prompt_version']!r}")
    if g["prompt_sha256"] != prompt_sha256(g["prompt_version"], ev):
        raise BriefError("提示词哈希与按证据包重新生成的提示词不一致")
    if not isinstance(g["model"], str) or not MODEL_ID.match(g["model"]):
        raise BriefError("生成记录模型标识无效")
    if not isinstance(g["cli_version"], str) or not re.fullmatch(r"[0-9A-Za-z.\- ()]{1,60}", g["cli_version"]):
        raise BriefError("生成记录 CLI 版本无效")
    if not isinstance(g["raw_receipt_sha256"], str) or not HEX64.match(g["raw_receipt_sha256"]):
        raise BriefError("生成记录 raw_receipt_sha256 格式无效")
    return sha256_obj(rep)


def validate_accepted(acc, data_dir=DATA_DIR, now=None, filename=None):
    now = now or _now()
    _keys(acc, ["schema", "report", "review"], "已验收报告")
    if acc["schema"] != ACCEPTED_SCHEMA:
        raise BriefError("已验收报告 schema 不符")
    h = validate_report(acc["report"], data_dir, now)
    if filename is not None and filename != f"{acc['report']['brief_id']}.json":
        raise BriefError("文件名与 brief_id 不一致")
    r = acc["review"]
    _keys(r, ["reviewer", "reviewed_at", "decision", "report_sha256", "note"], "审阅记录")
    if r["decision"] != "accepted":
        raise BriefError("审阅结论不是 accepted")
    if r["report_sha256"] != h:
        raise BriefError("审阅绑定的报告哈希与报告内容不一致（验收后被改动）")
    if not isinstance(r["reviewer"], str) or not REVIEWER.match(r["reviewer"]) or "claude" in r["reviewer"].lower():
        raise BriefError("审阅者无效（不能为空，也不能是生成方 Claude）")
    if not isinstance(r["note"], str) or len(r["note"]) > 300 or BAD_TEXT.search(r["note"]):
        raise BriefError("审阅备注无效")
    rt = _ts(r["reviewed_at"], "审阅时间")
    if rt < _ts(acc["report"]["generation"]["generated_at"], "生成时间") or rt > now + CLOCK_SKEW:
        raise BriefError("审阅时间早于生成时间或晚于当前时间")
    return h


# ---------- 提示词（按版本冻结；validate 会按版本重算哈希） ----------
SYSTEM_PROMPT = ("你是期货研究简报的起草助手。你只能使用用户消息里给出的证据包，不能使用任何外部知识、新闻、宏观事件、其他价格或日期。"
                 "你没有任何工具。只输出一个 JSON 对象，不要输出任何其他文字。")
_V1_SOURCE = "本站新浪财经/akshare扫描快照"
_V1_VERIFICATION = "未做交易所或第二来源核对；数值为本站扫描原值"
_V1_BANNED = ("买入", "卖出", "开仓", "加仓", "建仓", "平仓", "止损", "止盈", "抄底", "逢低", "逢高", "做多", "做空",
              "推荐", "建议", "目标价", "胜率", "仓位", "必然", "稳赚", "策略有效")
_V1_RULE2 = "2. 只能使用证据包里出现过的数字；不要计算新数字（比例、差值、百分比都不要算），不要写证据包里没有的日期或价格。可以用\"多于\"\"少于\"做比较。"
_V2_RULE2 = ("2. 每条 text 里的数字只能来自该条 evidence_ids 引用的事实：数值照抄原值，负值必须带负号（如 -2.92%）；"
             "可以使用所引用事实名称里的数字（如 中证1000、20日）。不要计算新数字（比例、差值、百分比都不要算），不要写日期。可以用\"多于\"\"少于\"做比较。")


def _prompt(ev, rule2):
    """证据包按键排序嵌入（首份真实生成读的是按键排序写出的 evidence.json，字节与此一致），哈希与内存中键顺序无关"""
    return f"""下面是本站一个交易日的扫描证据包（来源：{_V1_SOURCE}，{_V1_VERIFICATION}）。请据此起草一份中文研究简报草稿，交由独立审阅者审阅。

输出要求：只输出严格 JSON（UTF-8，不要 Markdown 代码块），格式为
{{"summary":[条目], "interpretation":[条目], "uncertainties":[条目], "next_checks":[条目]}}
条目格式：{{"text":"一句中文", "evidence_ids":["证据包中的 fact_id"]}}
- summary（摘要）：1–3 条，只复述证据显示了什么。
- interpretation（AI 解读）：2–4 条，是对证据的解释或假设，用"可能""或许"等措辞，不得声称因果已确定。
- uncertainties（仍不确定）：2–4 条，说明这份证据回答不了什么。
- next_checks（下次需核对的问题）：2–4 条，写成问句，说明下次应核对哪些数据。
规则：
1. 每个条目引用 1–6 个 evidence_ids，必须是证据包里存在的 fact_id。
{rule2}
3. 不提新闻、政策、宏观数据、库存、天气、外盘等证据包以外的信息，不把变化归因于具体事件。
4. 不给任何交易或投资建议，不评价策略是否有效。以下词语一律不要出现（包括免责声明里）：{"、".join(_V1_BANNED)}。
5. 不写网址、HTML、代码、反斜杠或斜杠。每条 text 不超过 120 个汉字。
6. 不需要免责声明，网站会另外加。

证据包：
{json.dumps(ev, ensure_ascii=False, indent=1, sort_keys=True)}
"""


def build_prompt_v1(ev):
    """2026-11-04 首份真实草稿使用的提示词，字节不可再改"""
    return _prompt(ev, _V1_RULE2)


def build_prompt_v2(ev):
    """v2 只改第 2 条：数字须来自本条引用的事实、负值带负号"""
    return _prompt(ev, _V2_RULE2)


PROMPTS = {"brief-prompt/1": build_prompt_v1, "brief-prompt/2": build_prompt_v2}
PROMPT_VERSION = "brief-prompt/2"  # 新生成使用的版本
build_prompt = build_prompt_v1     # 兼容旧调用


def prompt_sha256(version, ev):
    return hashlib.sha256(PROMPTS[version](ev).encode("utf-8")).hexdigest()


# ---------- 子进程：环境白名单、有界管道、只结束自己的进程树 ----------
ENV_ALLOW = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
             "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES",
             "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432", "SYSTEMDRIVE", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
             "OS", "USERNAME", "USERDOMAIN", "COMPUTERNAME", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER"}
ENV_DENY_PREFIX = ("ANTHROPIC", "CLAUDE", "AWS_", "GOOGLE", "GCLOUD", "AZURE", "VERTEX", "BEDROCK", "FOUNDRY")
MAX_STDOUT = 4 * 1024 * 1024
MAX_STDERR = 256 * 1024


def child_env(src=None):
    """只传 Windows/POSIX 启动必需的变量；ANTHROPIC_*、CLAUDE*（含 CLAUDECODE、CLAUDE_CODE_*）、云厂商与项目密钥一律不继承"""
    src = os.environ if src is None else src
    return {k: v for k, v in src.items() if k.upper() in ENV_ALLOW and not k.upper().startswith(ENV_DENY_PREFIX)}


def _win_job():
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObject 失败")
    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        k32.CloseHandle(job)
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject 失败")
    return k32, ntdll, job


def run_bounded(cmd, data, timeout, cwd, env, max_out=MAX_STDOUT, max_err=MAX_STDERR):
    """启动一个子进程并有界读写：Windows 下以挂起方式创建、放入专属 Job（关闭即结束整棵树）后再恢复；POSIX 下新建进程组。
    超时、输出超量或进程结束后，只终止这一棵进程树（不会影响调用者或其他会话）。返回 (退出码, stdout, stderr)"""
    win = os.name == "nt"
    kw = {}
    if win:
        k32, ntdll, job = _win_job()
        kw["creationflags"] = 0x00000004 | 0x08000000  # CREATE_SUSPENDED | CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env, shell=False, **kw)
    except OSError as e:
        if win:
            k32.CloseHandle(job)
        raise BriefError(f"无法启动 CLI：{e.strerror or type(e).__name__}") from None
    if win:
        h = int(p._handle)
        if not k32.AssignProcessToJobObject(job, h):
            k32.TerminateProcess(h, 1)
            p.wait()
            k32.CloseHandle(job)
            raise BriefError("无法把 CLI 进程放入 Job，已终止")
        ntdll.NtResumeProcess(h)

    def kill_tree():
        if win:
            k32.TerminateJobObject(job, 1)
        else:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    bufs, over = {"out": [], "err": []}, threading.Event()

    def reader(stream, cap, key):
        n = 0
        try:
            while True:
                chunk = stream.read1(65536)
                if not chunk:
                    break
                n += len(chunk)
                if n > cap:
                    over.set()
                    break
                bufs[key].append(chunk)
        except (OSError, ValueError):
            pass

    def writer():
        try:
            p.stdin.write(data)
            p.stdin.close()
        except (OSError, ValueError):
            pass

    threads = [threading.Thread(target=reader, args=(p.stdout, max_out, "out"), daemon=True),
               threading.Thread(target=reader, args=(p.stderr, max_err, "err"), daemon=True),
               threading.Thread(target=writer, daemon=True)]
    for t in threads:
        t.start()
    deadline, reason = time.monotonic() + timeout, None
    try:
        while p.poll() is None:
            if over.is_set():
                reason = "CLI 输出超过上限，已终止"
                break
            if time.monotonic() > deadline:
                reason = f"CLI 超时（{timeout} 秒），已终止"
                break
            time.sleep(0.05)
    finally:
        kill_tree()  # 正常退出时也清理遗留的孙进程
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        for t in threads:
            t.join(timeout=5)
        for s in (p.stdin, p.stdout, p.stderr):
            try:
                s.close()
            except (OSError, ValueError):
                pass
        if win:
            k32.CloseHandle(job)
    if reason is None and over.is_set():
        reason = "CLI 输出超过上限"
    if reason:
        raise BriefError(reason)
    return p.returncode, b"".join(bufs["out"]), b"".join(bufs["err"])


# ---------- 调用 Claude CLI ----------
def claude_cmd(claude):
    return [claude, "--safe-mode", "--restricted", "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--no-chrome", "--disable-slash-commands", "--no-session-persistence", "--permission-prompts", "none",
            "--system-prompt", SYSTEM_PROMPT, "-p", "--output-format", "stream-json", "--verbose"]


def check_auth(claude, cwd, env, cmd_prefix=None, timeout=60):
    """发送证据包之前：官方 auth status 必须是已登录的 claude.ai 订阅（firstParty）。只读取这三个字段，不保存其他登录信息"""
    rc, out, _ = run_bounded((cmd_prefix or []) + [claude, "auth", "status", "--json"], b"", timeout, cwd, env, max_out=64 * 1024)
    if rc != 0:
        raise BriefError("登录状态检查失败（auth status 退出码非零），未发送证据包")
    try:
        j = json.loads(out.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BriefError("登录状态输出无法解析，未发送证据包") from None
    if not (isinstance(j, dict) and j.get("loggedIn") is True and j.get("authMethod") == "claude.ai" and j.get("apiProvider") == "firstParty"):
        raise BriefError("CLI 不是已登录的 claude.ai 订阅（firstParty），未发送证据包")


def parse_cli_output(stdout):
    """解析 stream-json：init 必须明确 apiKeySource=none、工具与 MCP 为空列表；result 必须成功。返回 (模型标识, CLI 版本, 结果文本)"""
    init = result = None
    for n, line in enumerate(stdout.splitlines(), 1):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            raise BriefError(f"CLI 输出第 {n} 行不是 JSON") from None
        if not isinstance(ev, dict):
            raise BriefError(f"CLI 输出第 {n} 行不是对象")
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            init = ev
        elif ev.get("type") == "result":
            result = ev
    if init is None or result is None:
        raise BriefError("CLI 输出缺少 init 或 result 记录")
    if init.get("apiKeySource") != "none":
        raise BriefError("CLI 未明确报告订阅登录（apiKeySource 不是 none），按规定拒绝")
    if init.get("tools") != [] or init.get("mcp_servers") != []:
        raise BriefError("CLI 会话启用了工具或 MCP（或未报告），按规定拒绝")
    if result.get("subtype") != "success" or result.get("is_error") is not False:
        raise BriefError("CLI 返回失败")
    model = init.get("model")
    if not isinstance(model, str) or not MODEL_ID.match(model):
        raise BriefError("CLI 未返回有效模型标识")
    usage = result.get("modelUsage")
    if isinstance(usage, dict) and usage and model not in usage:
        raise BriefError("CLI init 与 result 的模型标识不一致")
    text = result.get("result")
    if not isinstance(text, str) or not text.strip():
        raise BriefError("CLI 结果文本为空")
    return model, str(init.get("claude_code_version") or "unknown"), text


def parse_ai_text(text):
    t = text.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", t, re.S)
    if m:
        t = m.group(1)
    obj = strict_loads(t)
    if not isinstance(obj, dict):
        raise BriefError("模型输出不是 JSON 对象")
    return obj


def generate(d, local_dir=LOCAL_DIR, data_dir=DATA_DIR, claude=DEFAULT_CLAUDE, timeout=300, cmd_prefix=None):
    """一次生成：先查登录方式，再调用一次 CLI；失败写 generate-error-*.json 并抛错，不写草稿；已有草稿时拒绝重复生成"""
    bid = brief_id_for(d)
    work = Path(local_dir) / bid
    ev_path, draft_path = work / "evidence.json", work / "draft.json"
    if draft_path.exists():
        raise BriefError(f"{draft_path} 已存在，不重复生成")
    if not ev_path.is_file():
        raise BriefError("还没有证据包，请先 prepare")
    ev = strict_loads(ev_path.read_text(encoding="utf-8"))
    validate_evidence(ev)
    snap, rel, h = load_snapshot(data_dir, d)
    if build_evidence(snap, rel, h) != ev:
        raise BriefError("证据包与当前源快照不一致，请重新 prepare")
    prompt = PROMPTS[PROMPT_VERSION](ev)
    stamp = _now().strftime("%Y%m%dT%H%M%S")
    env = child_env()
    stdout = stderr = b""
    try:
        with tempfile.TemporaryDirectory(prefix="brief-cli-") as cwd:  # 空目录：不让 CLI 读到仓库或用户资料
            check_auth(claude, cwd, env, cmd_prefix)
            rc, stdout, stderr = run_bounded((cmd_prefix or []) + claude_cmd(claude), prompt.encode("utf-8"), timeout, cwd, env)
            if rc != 0:
                raise BriefError(f"CLI 退出码 {rc}")
        model, ver, text = parse_cli_output(stdout.decode("utf-8", errors="strict"))
        ai = parse_ai_text(text)
        validate_ai(ai, ev)
        rep = {"schema": REPORT_SCHEMA, "brief_id": bid, "data_date": d, "evidence": ev, "evidence_sha256": sha256_obj(ev), "ai": ai,
               "generation": {"generated_at": _now().isoformat(timespec="seconds"), "generator": "claude-code-cli",
                              "cli_version": ver, "model": model, "prompt_version": PROMPT_VERSION,
                              "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                              "raw_receipt_sha256": hashlib.sha256(stdout).hexdigest()}}
        h = validate_report(rep, data_dir)
    except (BriefError, UnicodeDecodeError) as e:
        work.mkdir(parents=True, exist_ok=True)
        if stdout or stderr:  # 原始输出只留本机忽略目录，不打印、不进网页
            (work / f"cli-raw-{stamp}.failed.jsonl").write_bytes(stdout)
            (work / f"cli-stderr-{stamp}.failed.log").write_bytes(stderr)
        msg = str(e) if isinstance(e, BriefError) else "CLI 输出不是 UTF-8"
        _write_atomic(work / f"generate-error-{stamp}.json", _dump({"at": _now().isoformat(timespec="seconds"), "error": msg}))
        raise BriefError(msg) from None
    (work / f"cli-raw-{stamp}.jsonl").write_bytes(stdout)  # CLI 原始回执只留本机忽略目录
    (work / f"cli-stderr-{stamp}.log").write_bytes(stderr)
    (work / f"prompt-{stamp}.txt").write_bytes(prompt.encode("utf-8"))  # 原字节，可按 prompt_sha256 复核
    _write_atomic(draft_path, _dump(rep))
    return draft_path, h


def check_receipt(work, rep):
    """本机草稿目录里必须有哈希与 generation.raw_receipt_sha256 一致的 CLI 原始回执（失败回执不算）"""
    want = rep["generation"]["raw_receipt_sha256"]
    for p in sorted(Path(work).glob("cli-raw-*.jsonl")):
        if not p.name.endswith(".failed.jsonl") and hashlib.sha256(p.read_bytes()).hexdigest() == want:
            return p
    raise BriefError("本机原始回执缺失或哈希与生成记录不一致")


def accept(draft_path, reviewer, report_sha256, note="", accepted_dir=ACCEPTED_DIR, data_dir=DATA_DIR):
    """审阅通过：审阅者必须给出自己审过的草稿哈希；本机原始回执须一致；已存在的验收文件不覆盖"""
    rep = strict_loads(Path(draft_path).read_text(encoding="utf-8"))
    h = validate_report(rep, data_dir)
    if report_sha256 != h:
        raise BriefError(f"给出的哈希与草稿当前内容不一致（当前 {h}）")
    check_receipt(Path(draft_path).parent, rep)
    acc = {"schema": ACCEPTED_SCHEMA, "report": rep,
           "review": {"reviewer": reviewer, "reviewed_at": _now().isoformat(timespec="seconds"), "decision": "accepted",
                      "report_sha256": h, "note": note}}
    validate_accepted(acc, data_dir)
    path = Path(accepted_dir) / f"{rep['brief_id']}.json"
    if path.exists():
        raise BriefError(f"{path} 已存在，不重复验收")
    _write_atomic(path, _dump(acc))
    return path


def load_accepted(accepted_dir=None, data_dir=None, now=None):
    """读入已验收报告：逐个严格校验，不合格的列入 rejected，不影响其他。返回 (按日期降序的报告列表, [(文件名, 原因)])"""
    ok, rejected, seen = [], [], set()
    data_dir = data_dir or DATA_DIR
    d = Path(accepted_dir or ACCEPTED_DIR)
    if not d.is_dir():
        return ok, rejected
    for p in sorted(d.iterdir()):
        name = p.name
        try:
            if not p.is_file() or p.is_symlink() or not name.endswith(".json") or not BRIEF_ID.match(name[:-5]):
                raise BriefError("不是 brief-YYYY-MM-DD.json 文件")
            acc = strict_loads(p.read_text(encoding="utf-8"))
            h = validate_accepted(acc, data_dir, now, filename=name)
            bid = acc["report"]["brief_id"]
            if bid in seen:
                raise BriefError("brief_id 重复")
            seen.add(bid)
            ok.append({**acc, "report_sha256": h})
        except BriefError as e:
            rejected.append((name, str(e)))
        except Exception as e:  # 任何异常都只淘汰这一份；公开页面不展示内部异常细节
            rejected.append((name, f"读取或校验出错（{type(e).__name__}）"))
    ok.sort(key=lambda a: a["report"]["data_date"], reverse=True)
    return ok, rejected


# ---------- 网页 ----------
CSS = """
.b-note{background:var(--amber-dim);border-left:3px solid var(--amber);padding:9px 12px;border-radius:0 4px 4px 0;font-size:13px;margin-bottom:12px}
.b-ok{background:var(--cyan-dim);border-left:3px solid var(--cyan);padding:9px 12px;border-radius:0 4px 4px 0;font-size:13px;margin-bottom:12px}
.b-meta{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}.b-meta>div{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:9px 12px;min-width:0}
.b-meta .k{display:block;font-size:11px;color:var(--muted)}.b-meta .v{font-size:13.5px;font-weight:600;overflow-wrap:anywhere}
.b-list li{list-style:none;padding:8px 0;border-bottom:1px solid var(--line)}.b-list li:last-child{border-bottom:0}
.b-item{margin:6px 0 10px;line-height:1.7}.b-ref{display:inline-block;font-size:11.5px;padding:0 6px;margin:2px 3px 0 0;border:1px solid var(--line2);border-radius:3px;color:var(--muted);line-height:1.6}
.b-tag{display:inline-block;font-size:11px;padding:1px 8px;border-radius:3px;border:1px solid var(--line2);color:var(--muted);margin-left:6px}
.b-small{font-size:12px;color:var(--muted);overflow-wrap:anywhere}.b-small p{margin:4px 0}
.b-facts table{min-width:0}.b-facts td{white-space:normal;text-align:left}.b-facts td:first-child{min-width:9em}
.b-facts tr[id]{scroll-margin-top:90px}.b-facts tr[id]:target td{background:var(--cyan-dim)}
@media (max-width:720px){.b-meta{grid-template-columns:1fr 1fr}.b-facts tr[id]{scroll-margin-top:150px}}
"""
DISCLAIMER = "AI 解读是对证据的解释或假设，不是交易建议，也不评价任何策略是否有效。程序自动生成并经审阅，仅供学习交流，不构成投资建议。"
TZ_NOTE = "曼谷时间"


def _fmt_val(f):
    v = f["value"]
    if isinstance(v, dict):
        return (f"收盘 {v['today_close']:g} ｜ 涨跌 {v['price_change_pct']:+.2f}% ｜ 持仓变化 {v['hold_change_pct']:+.2f}% ｜ "
                f"20日动量 {v['mom20']:+.2f}% ｜ 形态 {escape(str(v['pattern']))}（{escape(str(v['dims']))}）")
    return escape(f"{v:g}" if _num(v) else str(v)) + (escape(f["unit"]) if isinstance(f.get("unit"), str) else "")


def _currency(rep_date, latest_date, newest_accepted, link_prefix):
    """当前性提示。newest_accepted 是本次建站实际读到的最新已验收简报日期，只按它下结论"""
    if rep_date == latest_date:
        return True, f"当前：这份简报对应最新扫描日期 {escape(latest_date)}。"
    msg = f"历史简报：对应数据日期 {escape(rep_date)}；最新扫描日期 {escape(latest_date)}。"
    if newest_accepted == latest_date:
        return False, msg + f"最新扫描日期已有已验收 AI 简报：<a href='{link_prefix}brief-{escape(latest_date)}.html'>查看 {escape(latest_date)}</a>。"
    if newest_accepted and newest_accepted > rep_date:
        msg += f"较新的已验收简报是 <a href='{link_prefix}brief-{escape(newest_accepted)}.html'>{escape(newest_accepted)}</a>；"
    return False, msg + f"最新扫描日期 {escape(latest_date)} 尚无已验收 AI 简报。"


def _when(s):
    return escape(_ts(s, "时间").astimezone(USER_TZ).strftime("%Y-%m-%d %H:%M"))


def detail_body(acc, latest_date, newest_accepted=None):
    rep, rv = acc["report"], acc["review"]
    ev, g = rep["evidence"], rep["generation"]
    cur, msg = _currency(rep["data_date"], latest_date, newest_accepted or rep["data_date"], "")
    facts = {f["fact_id"]: f for f in ev["facts"]}

    def items(key):
        out = ""
        for it in rep["ai"][key]:
            refs = "".join(f"<a class='b-ref' href='#f-{escape(r)}'>{escape(facts[r]['label']) if r in facts else escape(r)}</a>"
                           for r in it["evidence_ids"])
            out += f"<li class='b-item'>{escape(it['text'])}<br><span class='b-small'>依据：</span>{refs}</li>"
        return f"<ul style='padding-left:18px'>{out}</ul>"

    secs = "".join(
        f"<div class='card'><h3>{escape(title)}{'<span class=b-tag>解释/假设，不是交易建议</span>' if key == 'interpretation' else ''}</h3>{items(key)}</div>"
        for key, title, *_ in SECTIONS)
    rows = "".join(f"<tr id='f-{escape(fid)}'><td>{escape(f['label'])}"
                   f"{('<br><span class=b-small>' + escape(f['detail']) + '</span>') if f.get('detail') else ''}</td>"
                   f"<td>{_fmt_val(f)}</td></tr>" for fid, f in facts.items())
    tech = "".join(f"<tr><td>{escape(f['label'])}</td><td><code>{escape(fid)}</code></td><td>{escape(f['source_field'])}</td></tr>"
                   for fid, f in facts.items())
    src = ev["source"]
    d = escape(rep["data_date"])
    return f"""<style>{CSS}</style>
<div class='hd'><div><h1>AI 研究简报 · {d}</h1><div class='sub'>由本机 Claude 根据本站扫描快照起草，经独立审阅后发布；数值以下方「本站快照依据」为准</div></div></div>
<div class='{'b-ok' if cur else 'b-note'}'>{msg}</div>
<div class='b-meta'><div><span class='k'>数据日期（交易日）</span><span class='v'>{d}</span></div>
<div><span class='k'>生成时间（{TZ_NOTE}）</span><span class='v'>{_when(g['generated_at'])} · Claude 起草</span></div>
<div><span class='k'>审阅时间（{TZ_NOTE}）</span><span class='v'>{_when(rv['reviewed_at'])} · {escape(rv['reviewer'])}</span></div>
<div><span class='k'>来源范围</span><span class='v'>仅本站扫描快照，{len(facts)} 项</span></div></div>
<div class='b-note'>{escape(DISCLAIMER)} 数值来自本站扫描快照，{escape(src['verification'])}；不含新闻、宏观或事件信息。</div>
{secs}
<div class='card b-facts'><h3>本站快照依据<span class='b-tag'>程序从快照原值列出，不经模型改写；未经交易所核对</span></h3>
<div class='tbl' style='border-radius:6px'><table><thead><tr><th>项目</th><th>数值</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class='b-small' style='margin-top:6px'>{escape(ev['selection_note'].replace('price_change_pct', '涨跌幅'))}。当日完整量化日报（程序规则生成）：<a href='../reports/{d}.html'>{d} 日报</a></p></div>
<details><summary>技术细节（来源文件、哈希、模型）</summary><div class='card b-small' style='border-radius:0 0 6px 6px'>
<p>来源：{escape(src['label'])}，文件 {escape(src['path'])}，SHA-256（CRLF 统一为 LF 后）{escape(src['sha256'])}；扫描日期 {escape(src['scan_date'])}，{escape(src['time_note'])}。</p>
<p>证据包 SHA-256 {escape(rep['evidence_sha256'])}；报告 SHA-256 {escape(acc['report_sha256'])}；提示词 {escape(g['prompt_version'])}，SHA-256 {escape(g['prompt_sha256'])}。</p>
<p>生成：{escape(g['generator'])} {escape(g['cli_version'])}，模型标识 {escape(g['model'])}（取自 CLI 返回）。审阅：{escape(rv['reviewer'])}，审阅记录绑定上面的报告哈希。{('备注：' + escape(rv['note'])) if rv['note'] else ''}</p>
<div class='tbl b-facts' style='border-radius:6px'><table><thead><tr><th>项目</th><th>fact_id</th><th>快照字段</th></tr></thead><tbody>{tech}</tbody></table></div></div></details>
<p class='b-small' style='margin-top:10px'><a href='../briefs.html'>← 全部 AI 研究简报</a></p>"""


def index_body(accs, latest_date, rejected):
    rej = (f"<details><summary>有 {len(rejected)} 份报告未通过校验，未发布</summary><div class='card b-small' style='border-radius:0 0 6px 6px'>"
           + "".join(f"<p>{escape(n)}：{escape(r)}</p>" for n, r in rejected) + "</div></details>") if rejected else ""
    head = """<style>""" + CSS + """</style><div class='hd'><div><h1>AI 研究简报</h1><div class='sub'>由本机 Claude 根据本站扫描快照起草，经独立审阅后发布；与程序规则生成的量化日报分开</div></div></div>"""
    if not accs:
        return (head + "<div class='b-note'>目前没有已审阅的 AI 简报；可先查看<a href='archive.html'>量化日报</a>。</div>"
                f"{rej}<p class='b-small'>{escape(DISCLAIMER)}</p>")
    newest = accs[0]["report"]["data_date"]
    cur, msg = _currency(newest, latest_date, newest, "briefs/")
    lis = "".join(
        f"<li><a href='briefs/{escape(a['report']['brief_id'])}.html'><b>{escape(a['report']['data_date'])}</b> AI 研究简报</a>"
        f"<div class='b-small'>生成 {_when(a['report']['generation']['generated_at'])} ｜ 审阅 {_when(a['review']['reviewed_at'])}（{escape(a['review']['reviewer'])}） ｜ "
        f"{TZ_NOTE} ｜ 来源：本站扫描快照</div>"
        f"<div class='b-small'>{escape(a['report']['ai']['summary'][0]['text'])}</div></li>" for a in accs)
    return (head + f"<div class='{'b-ok' if cur else 'b-note'}'>{msg}</div><div class='card'><ul class='b-list'>{lis}</ul></div>{rej}"
            f"<p class='b-small'>{escape(DISCLAIMER)}</p>")


def build_pages(out, layout, latest_date, data_dir=None, accepted_dir=None, site_title=""):
    """写 briefs.html 与 briefs/<id>.html；返回状态信息供 status.html 使用"""
    accs, rejected = load_accepted(accepted_dir, data_dir)
    out = Path(out)
    shutil.rmtree(out / "briefs", ignore_errors=True)
    (out / "briefs").mkdir(parents=True)
    newest = accs[0]["report"]["data_date"] if accs else None
    for a in accs:
        bid = a["report"]["brief_id"]
        (out / "briefs" / f"{bid}.html").write_text(
            layout(f"AI 研究简报 {a['report']['data_date']} · {site_title}", detail_body(a, latest_date, newest), "briefs", root="../"),
            encoding="utf-8")
    (out / "briefs.html").write_text(layout(f"AI 研究简报 · {site_title}", index_body(accs, latest_date, rejected), "briefs"), encoding="utf-8")
    return {"count": len(accs), "latest": newest, "current": newest == latest_date, "rejected": rejected}


def status_rows(info, latest_date):
    """status.html 的 AI 简报行：(项目, 数据日期, 说明)，已转义"""
    if info is None:
        return [("AI 研究简报", "生成失败", "本次建站未能读取 AI 简报，见 Actions 日志")]
    if not info["latest"]:
        val, note = "无", "没有已验收的 AI 简报"
    elif info["current"]:
        val, note = escape(info["latest"]), "当前：最新交易日已有已验收 AI 简报"
    else:
        val, note = escape(info["latest"]), f"历史：最新交易日 {escape(latest_date)} 尚无已验收 AI 简报"
    rows = [("AI 研究简报（最近已验收）", val, note + f" · 共 {info['count']} 份")]
    if info["rejected"]:
        rows.append(("AI 研究简报校验", f"{len(info['rejected'])} 份未通过", "未发布；原因见 AI 研究简报页"))
    return rows


# ---------- 命令行 ----------
def main(argv=None):
    ap = argparse.ArgumentParser(description="本机 AI 研究简报")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("prepare", "generate", "validate", "accept"):
        s = sub.add_parser(name)
        s.add_argument("--date", required=True, help="数据日期 YYYY-MM-DD")
        s.add_argument("--data", default=str(DATA_DIR))
        s.add_argument("--local", default=str(LOCAL_DIR))
        if name == "generate":
            s.add_argument("--claude", default=DEFAULT_CLAUDE)
            s.add_argument("--timeout", type=int, default=300)
        if name == "accept":
            s.add_argument("--reviewer", required=True)
            s.add_argument("--report-sha256", required=True)
            s.add_argument("--note", default="")
            s.add_argument("--accepted", default=str(ACCEPTED_DIR))
    s = sub.add_parser("status")
    s.add_argument("--data", default=str(DATA_DIR))
    s.add_argument("--local", default=str(LOCAL_DIR))
    s.add_argument("--accepted", default=str(ACCEPTED_DIR))
    a = ap.parse_args(argv)
    try:
        if a.cmd == "prepare":
            p, ev, new = prepare(a.date, a.data, a.local)
            print(f"{'已写入' if new else '已存在且一致，未改动'}：{p}\n事实 {len(ev['facts'])} 条；源哈希 {ev['source']['sha256']}")
        elif a.cmd == "generate":
            p, h = generate(a.date, a.local, a.data, a.claude, a.timeout)
            print(f"草稿已写入：{p}\n报告 SHA-256：{h}\n状态：待审阅（未发布）")
        elif a.cmd == "validate":
            p = Path(a.local) / brief_id_for(a.date) / "draft.json"
            rep = strict_loads(p.read_text(encoding="utf-8"))
            h = validate_report(rep, a.data)
            rc = check_receipt(p.parent, rep)
            print(f"草稿校验通过：{p}\n报告 SHA-256：{h}\n提示词 {rep['generation']['prompt_version']} 哈希重算一致；原始回执一致：{rc.name}")
        elif a.cmd == "accept":
            p = accept(Path(a.local) / brief_id_for(a.date) / "draft.json", a.reviewer, a.report_sha256, a.note, a.accepted, a.data)
            print(f"已验收：{p}")
        else:
            accs, rej = load_accepted(a.accepted, a.data)
            for x in accs:
                print(f"已验收 {x['report']['brief_id']}  审阅 {x['review']['reviewer']} {x['review']['reviewed_at']}")
            for n, r in rej:
                print(f"未通过 {n}：{r}")
            loc = Path(a.local)
            for dft in sorted(loc.glob("brief-*/draft.json")) if loc.is_dir() else []:
                bid = dft.parent.name
                done = any(x["report"]["brief_id"] == bid for x in accs)
                print(f"草稿 {bid}：{'已验收' if done else '待审阅'}")
            if not accs and not rej:
                print("没有已验收报告")
    except (BriefError, OSError) as e:
        print(f"失败：{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
