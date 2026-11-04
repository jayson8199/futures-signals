"""
AI 研究简报回归测试（离线）：python -m unittest test_research_briefs   （cwd = scanner/）
所有写入都在临时目录；CLI 用假进程模拟，不调用真实 Claude。验收用的合成报告只写临时 accepted 目录，模型标识为 fixture-model。
本机真实草稿（.local-briefs/brief-2026-11-04/）只读校验，存在时才跑。
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_site
import research_briefs as rb

ROOT = Path(__file__).resolve().parent.parent
D = "2026-11-04"
TODAY = date(2026, 11, 4)
CN = ZoneInfo("Asia/Shanghai")
BKK = ZoneInfo("Asia/Bangkok")
NOW = datetime(2026, 11, 4, 22, 0, tzinfo=BKK)
GENUINE = ROOT / ".local-briefs" / f"brief-{D}"
V1_PROMPT_SHA = "eb66f7dc458f8ad0b935ed047fb29a8ef213dc8c4db74ecf6d1f75a4609ac0b4"
RECEIPT = b'{"type":"result","fixture":true}\n'


def tree_hash(folder: Path):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


def good_ai(ev):
    f = {x["fact_id"]: x["value"] for x in ev["facts"]}
    return {
        "summary": [{"text": f"有效品种 {f['cov.valid']} 个，上涨 {f['breadth.up']} 个、下跌 {f['breadth.down']} 个，市场环境为{f['mkt.regime']}。",
                     "evidence_ids": ["cov.valid", "breadth.up", "breadth.down", "mkt.regime"]}],
        "interpretation": [{"text": "下跌品种多于上涨品种，可能说明整体偏弱，这只是假设。", "evidence_ids": ["breadth.up", "breadth.down"]}],
        "uncertainties": [{"text": "快照没有成交结构以外的信息，原因无法判断。", "evidence_ids": ["cov.valid"]}],
        "next_checks": [{"text": "下一交易日 20 日动量中位数是否仍低于零？", "evidence_ids": ["mkt.mom20_median"]}],
    }


def make_report(data_dir, ai=None, gen_at=None, d=D, version=None):
    snap, rel, h = rb.load_snapshot(data_dir, d, date.fromisoformat(d))
    ev = rb.build_evidence(snap, rel, h)
    version = version or rb.PROMPT_VERSION
    return {"schema": rb.REPORT_SCHEMA, "brief_id": f"brief-{d}", "data_date": d, "evidence": ev, "evidence_sha256": rb.sha256_obj(ev),
            "ai": ai or good_ai(ev),
            "generation": {"generated_at": gen_at or f"{d}T16:00:00+08:00", "generator": "claude-code-cli", "cli_version": "fixture",
                           "model": "fixture-model", "prompt_version": version, "prompt_sha256": rb.prompt_sha256(version, ev),
                           "raw_receipt_sha256": hashlib.sha256(RECEIPT).hexdigest()}}


def make_accepted(rep, reviewer="Codex", at=None):
    at = at or f"{rep['data_date']}T16:30:00+08:00"
    return {"schema": rb.ACCEPTED_SCHEMA, "report": rep,
            "review": {"reviewer": reviewer, "reviewed_at": at, "decision": "accepted", "report_sha256": rb.sha256_obj(rep), "note": "fixture"}}


def alive(pid):
    if os.name == "nt":
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(ctypes.c_void_p(h), 0) != 0  # 0 = 已结束
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def wait_dead(pid, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.data = self.t / "data"
        self.data.mkdir()
        for name in (f"{D}.json", "2026-11-03.json"):
            shutil.copy(ROOT / "data" / name, self.data / name)
        self.local = self.t / "local"
        self.acc_dir = self.t / "accepted"

    def tearDown(self):
        self.tmp.cleanup()

    def snap(self, d=D):
        return json.loads((self.data / f"{d}.json").read_text(encoding="utf-8"))

    def write_snap(self, s, name=f"{D}.json"):
        (self.data / name).write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")

    def next_day(self, nxt="2026-11-05"):
        s = self.snap()
        s["data_date"] = s["scan_date"] = nxt
        for r in s["all_results"]:
            r["date"] = nxt
        self.write_snap(s, f"{nxt}.json")


class SnapshotTests(Base):
    def bad(self, mutate=None, raw=None, d=D, today=TODAY):
        if raw is not None:
            (self.data / f"{D}.json").write_text(raw, encoding="utf-8")
        elif mutate:
            s = self.snap()
            mutate(s)
            self.write_snap(s)
        with self.assertRaises(rb.BriefError):
            rb.load_snapshot(self.data, d, today)

    def test_real_snapshot_passes_and_pack_is_deterministic(self):
        p1, ev, new = rb.prepare(D, self.data, self.local, TODAY)
        self.assertTrue(new)
        b1 = p1.read_bytes()
        _, _, new2 = rb.prepare(D, self.data, self.local, TODAY)
        self.assertFalse(new2)
        self.assertEqual(b1, p1.read_bytes())
        ids = [f["fact_id"] for f in ev["facts"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ev["source"]["label"], "本站新浪财经/akshare扫描快照")
        self.assertIsNone(ev["source"]["scan_time"])
        f = {x["fact_id"]: x for x in ev["facts"]}
        s = self.snap()
        self.assertEqual(f["mkt.mom20_median"]["value"], s["market"]["mom20_median"])
        self.assertEqual(f["breadth.up"]["value"], s["up_count"])
        self.assertEqual(f["pat.gfs"]["value"], s["patterns"]["高富帅"]["count"])
        for w in ("FOMC", "CPI", "PMI", "买入", "卖出"):
            self.assertNotIn(w, json.dumps(ev, ensure_ascii=False))

    def test_missing_empty_and_corrupt(self):
        with self.assertRaises(rb.BriefError):
            rb.load_snapshot(self.data, "2026-11-05", TODAY)
        self.bad(raw="")
        self.bad(raw="{not json")
        self.bad(raw='{"a":1,"a":2}')
        self.bad(raw=(self.data / f"{D}.json").read_text(encoding="utf-8").replace('"mom20_median": -2.92', '"mom20_median": NaN'))

    def test_infinity_and_wrong_types(self):
        raw = (self.data / f"{D}.json").read_text(encoding="utf-8")
        self.bad(raw=raw.replace('"price_change_pct": 6.85', '"price_change_pct": Infinity', 1))
        self.bad(lambda s: s["all_results"][0].update(today_close="12453"))
        self.bad(lambda s: s.update(valid_count=True))

    def test_duplicate_symbol(self):
        def dup(s):
            s["all_results"][1]["symbol"] = s["all_results"][0]["symbol"]
        self.bad(dup)

    def test_date_mismatch_and_future(self):
        self.bad(lambda s: s.update(data_date="2026-11-03"))
        self.bad(lambda s: s["all_results"][3].update(date="2026-11-03"))
        self.bad(lambda s: s.update(scan_date="2026-11-03"))
        self.bad(today=date(2026, 11, 3))
        self.bad(d="2026/11/04")
        self.bad(d="../data/2026-11-04")

    def test_future_gate_uses_bangkok_date(self):
        """曼谷 11-04 23:30 = 北京 11-05 00:30：按曼谷日期，11-05 的快照仍是未来日期"""
        self.next_day()
        late = datetime(2026, 11, 4, 23, 30, tzinfo=BKK)
        self.assertEqual(late.astimezone(CN).date(), date(2026, 11, 5))
        with patch.object(rb, "_now", lambda: late):
            with self.assertRaises(rb.BriefError):
                rb.load_snapshot(self.data, "2026-11-05")
            rb.load_snapshot(self.data, D)
        with patch.object(rb, "_now", lambda: datetime(2026, 11, 5, 0, 30, tzinfo=BKK)):
            rb.load_snapshot(self.data, "2026-11-05")

    def test_incomplete_counts(self):
        self.bad(lambda s: s["all_results"].pop())
        self.bad(lambda s: s.update(total_scanned=55))
        self.bad(lambda s: s.update(up_count=s["up_count"] + 1))
        self.bad(lambda s: s["patterns"]["高富帅"].update(count=4))
        self.bad(lambda s: s["patterns"].pop("白富美"))
        self.bad(lambda s: s["market"].update(regime="强势"))

        def small(s):
            s["all_results"] = s["all_results"][:40]
            s.update(valid_count=40, total_scanned=40)
        self.bad(small)

    def test_source_hash_line_endings_and_tamper(self):
        p = self.data / f"{D}.json"
        lf = (ROOT / "data" / f"{D}.json").read_bytes().replace(b"\r\n", b"\n")
        p.write_bytes(lf)
        h_lf = rb.source_sha256(p)
        p.write_bytes(lf.replace(b"\n", b"\r\n"))
        self.assertEqual(h_lf, rb.source_sha256(p))
        p.write_bytes(lf.replace(b'"name": "', b'"name":  "', 1))
        self.assertNotEqual(h_lf, rb.source_sha256(p))

    def test_prepare_never_overwrites_different_pack(self):
        path, _, _ = rb.prepare(D, self.data, self.local, TODAY)
        before = path.read_bytes()
        s = self.snap()
        s["all_results"][0]["name"] = "白银X"
        self.write_snap(s)
        with self.assertRaises(rb.BriefError):
            rb.prepare(D, self.data, self.local, TODAY)
        self.assertEqual(before, path.read_bytes())


class NumberBindingTests(Base):
    """数字必须来自本条引用的事实且符号一致（Codex 复现的反例）"""

    def setUp(self):
        super().setUp()
        snap, rel, h = rb.load_snapshot(self.data, D, TODAY)
        self.ev = rb.build_evidence(snap, rel, h)
        self.f = {x["fact_id"]: x for x in self.ev["facts"]}

    def bad(self, text, ids):
        return rb.check_numbers(text, [self.f[i] for i in ids], D)

    def test_codex_counterexamples_rejected(self):
        self.assertEqual(self.bad("动量中位数为 +2.92%。", ["mkt.mom20_median"]), ["+2.92"])
        self.assertEqual(self.bad("上涨品种数为 30 个。", ["breadth.up"]), ["30"])
        self.assertTrue(self.bad("白银收盘 12453。", ["sym.LU0"]))         # 引用错位：数值属于 AG0
        self.assertTrue(self.bad("动量中位数为 2.92%。", ["mkt.mom20_median"]))  # 负值省略负号
        self.assertTrue(self.bad("低硫燃料油涨 +6.93%。", ["sym.LU0"]))     # 符号翻转
        self.assertTrue(self.bad("上涨品种 24 个。", ["mkt.regime"]))        # 引用的事实没有这个数
        self.assertTrue(self.bad("证据包哈希开头是 06。", ["cov.valid"]))     # 元数据不作数值依据

    def test_labels_calibers_and_signed_values_allowed(self):
        self.assertEqual(self.bad("动量中位数为-2.92%。", ["mkt.mom20_median"]), [])
        self.assertEqual(self.bad("全部品种20日动量中位数为−2.92%。", ["mkt.mom20_median"]), [])
        self.assertEqual(self.bad("中证1000为4.78%，20日动量-9.76%。", ["sym.IM0"]), [])
        self.assertEqual(self.bad("中证500涨+4.69%。", ["sym.IC0"]), [])
        self.assertEqual(self.bad("只展示两端各3个品种。", ["sym.AG0"]), [])
        self.assertEqual(self.bad("双20%强信号品种数为0。", ["sig.strong"]), [])
        self.assertEqual(self.bad("高富帅5个，含中证1000、沪深300。", ["pat.gfs"]), [])

    def test_dates_whitelist_only_data_date(self):
        self.assertEqual(self.bad(f"数据日期 {D} 有效品种 54 个。", ["cov.valid"]), [])
        for t in ("2026-11-05 有效品种 54 个。", "11月5日有效品种 54 个。", "2026年11月3日有效品种 54 个。"):
            self.assertTrue(self.bad(t, ["cov.valid"]), t)

    @unittest.skipUnless((GENUINE / "draft.json").exists(), "本机真实草稿不在")
    def test_genuine_draft_passes_unchanged(self):
        before = tree_hash(GENUINE)
        rep = json.loads((GENUINE / "draft.json").read_text(encoding="utf-8"))
        self.assertEqual(rb.validate_report(rep, ROOT / "data"), "2cca620422be5f0f52e30f7ba112013f86d9ebdf9adc57142a913d679ba549e3")
        self.assertEqual(rep["generation"]["prompt_version"], "brief-prompt/1")
        rb.check_receipt(GENUINE, rep)
        self.assertEqual(before, tree_hash(GENUINE))


class ReportTests(Base):
    def bad_ai(self, mutate):
        rep = make_report(self.data)
        mutate(rep["ai"])
        with self.assertRaises(rb.BriefError):
            rb.validate_report(rep, self.data, NOW)

    def test_good_report_passes(self):
        h = rb.validate_report(make_report(self.data), self.data, NOW)
        self.assertRegex(h, r"^[0-9a-f]{64}$")

    def test_unknown_fact_and_uncited(self):
        self.bad_ai(lambda a: a["summary"][0].update(evidence_ids=["no.such"]))
        self.bad_ai(lambda a: a["interpretation"][0].update(evidence_ids=[]))
        self.bad_ai(lambda a: a["interpretation"][0].pop("evidence_ids"))
        self.bad_ai(lambda a: a["next_checks"][0].update(evidence_ids=["cov.valid", "cov.valid"]))
        self.bad_ai(lambda a: a.update(uncertainties=[]))
        self.bad_ai(lambda a: a["summary"][0].update(evidence_ids=["cov.valid"]))  # 24/30 不在引用事实里

    def test_unknown_or_private_fields(self):
        self.bad_ai(lambda a: a["summary"][0].update(source="news"))
        self.bad_ai(lambda a: a.update(trade_advice=[]))
        for where, key in ((None, "session_id"), ("generation", "total_cost_usd"), ("generation", "account_email"), ("evidence", "user_profile")):
            rep = make_report(self.data)
            (rep[where] if where else rep)[key] = "x"
            with self.assertRaises(rb.BriefError, msg=key):
                rb.validate_report(rep, self.data, NOW)

    def test_script_url_path_and_advice_rejected(self):
        for t in ("快照显示 <script>alert(1)</script> 上涨", "详见 javascript:alert(1) 页面说明", "参考 https://example.com 的新闻报道",
                  "数据见 ../../etc/passwd 文件内容", "白银上涨，建议买入并设置止损", "白银可能继续上涨，可以考虑做多",
                  "上涨品种占比 44% 左右，偏弱", "据 2026-11-05 新闻，原油下跌"):
            self.bad_ai(lambda a, t=t: a["interpretation"][0].update(text=t))

    def test_evidence_and_source_tamper(self):
        rep = make_report(self.data)
        rep["evidence"]["facts"][3]["value"] = 99
        with self.assertRaises(rb.BriefError):
            rb.validate_report(rep, self.data, NOW)
        rep["evidence_sha256"] = rb.sha256_obj(rep["evidence"])  # 连哈希一起改：仍与源快照重新推导不一致
        with self.assertRaises(rb.BriefError):
            rb.validate_report(rep, self.data, NOW)
        rep = make_report(self.data)
        s = self.snap()
        s["all_results"][0]["name"] = "白银X"
        self.write_snap(s)
        with self.assertRaises(rb.BriefError):
            rb.validate_report(rep, self.data, NOW)

    def test_prompt_hash_recomputed(self):
        rep = make_report(self.data)
        rep["generation"]["prompt_sha256"] = "a" * 64
        with self.assertRaisesRegex(rb.BriefError, "提示词哈希"):
            rb.validate_report(rep, self.data, NOW)
        rep = make_report(self.data)
        rep["generation"]["prompt_version"] = "brief-prompt/9"
        with self.assertRaisesRegex(rb.BriefError, "提示词版本"):
            rb.validate_report(rep, self.data, NOW)
        rep = make_report(self.data, version="brief-prompt/1")  # 旧版本按旧提示词重算，明确支持
        rb.validate_report(rep, self.data, NOW)
        rep["generation"]["prompt_sha256"] = rb.prompt_sha256("brief-prompt/2", rep["evidence"])
        with self.assertRaises(rb.BriefError):
            rb.validate_report(rep, self.data, NOW)

    def test_v1_prompt_bytes_frozen(self):
        """首份真实草稿的提示词：由真实快照重新推导的证据包 + v1 提示词，哈希必须仍是生成时记录的值"""
        snap, rel, h = rb.load_snapshot(ROOT / "data", D, TODAY)
        ev = rb.build_evidence(snap, rel, h)
        self.assertEqual(rb.prompt_sha256("brief-prompt/1", ev), V1_PROMPT_SHA)
        self.assertNotEqual(rb.prompt_sha256("brief-prompt/2", ev), V1_PROMPT_SHA)

    def test_generation_time_bangkok_boundaries(self):
        # 北京 11-04 00:30 = 曼谷 11-03 23:30：早于数据日期（曼谷日期）
        for at in ("2026-11-04T00:30:00+08:00", "2026-11-03T20:00:00+08:00", "2026-11-05T09:00:00+08:00", "2026-11-04T19:00:00", "昨天"):
            rep = make_report(self.data, gen_at=at)
            with self.assertRaises(rb.BriefError, msg=at):
                rb.validate_report(rep, self.data, NOW)
        # 北京 11-05 00:30 = 曼谷 11-04 23:30：仍是数据日当天，可以
        late_now = datetime(2026, 11, 5, 1, 0, tzinfo=CN)
        rb.validate_report(make_report(self.data, gen_at="2026-11-05T00:30:00+08:00"), self.data, late_now)
        rb.validate_report(make_report(self.data, gen_at="2026-11-04T01:00:00+07:00"), self.data, NOW)
        self.assertEqual(rb._when("2026-11-04T19:55:56+08:00"), "2026-11-04 18:55")
        rep = make_report(self.data)
        rep["generation"]["model"] = "<b>x</b>"
        with self.assertRaises(rb.BriefError):
            rb.validate_report(rep, self.data, NOW)


class AcceptTests(Base):
    def draft(self, rep, receipt=RECEIPT, sub="local"):
        work = self.t / sub / rep["brief_id"]
        work.mkdir(parents=True, exist_ok=True)
        if receipt is not None:
            (work / "cli-raw-20261104T160000.jsonl").write_bytes(receipt)
        p = work / "draft.json"
        p.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
        return p

    def test_accept_binds_hash_and_refuses_duplicates(self):
        rep = make_report(self.data, gen_at=(datetime.now(BKK) - timedelta(minutes=1)).isoformat(timespec="seconds"))
        draft = self.draft(rep)
        h = rb.sha256_obj(rep)
        with self.assertRaises(rb.BriefError):
            rb.accept(draft, "Codex", "0" * 64, accepted_dir=self.acc_dir, data_dir=self.data)
        with self.assertRaises(rb.BriefError):
            rb.accept(draft, "Claude", h, accepted_dir=self.acc_dir, data_dir=self.data)
        p = rb.accept(draft, "Codex", h, accepted_dir=self.acc_dir, data_dir=self.data)
        self.assertEqual(p.name, f"brief-{D}.json")
        self.assertIn("+07:00", json.loads(p.read_text(encoding="utf-8"))["review"]["reviewed_at"])
        with self.assertRaises(rb.BriefError):
            rb.accept(draft, "Codex", h, accepted_dir=self.acc_dir, data_dir=self.data)
        ok, rej = rb.load_accepted(self.acc_dir, self.data)
        self.assertEqual((len(ok), rej), (1, []))

    def test_accept_requires_matching_local_receipt(self):
        rep = make_report(self.data, gen_at=(datetime.now(BKK) - timedelta(minutes=1)).isoformat(timespec="seconds"))
        for i, receipt in enumerate((None, b"other bytes")):
            draft = self.draft(rep, receipt, sub=f"local{i}")
            with self.assertRaisesRegex(rb.BriefError, "原始回执"):
                rb.accept(draft, "Codex", rb.sha256_obj(rep), accepted_dir=self.acc_dir, data_dir=self.data)
        self.assertFalse(self.acc_dir.exists())

    def load(self, acc, name=f"brief-{D}.json"):
        self.acc_dir.mkdir(exist_ok=True)
        (self.acc_dir / name).write_text(json.dumps(acc, ensure_ascii=False), encoding="utf-8")
        return rb.load_accepted(self.acc_dir, self.data, NOW)

    def test_post_acceptance_edit_rejected(self):
        acc = make_accepted(make_report(self.data))
        acc["report"]["ai"]["interpretation"][0]["text"] = "下跌品种多于上涨品种，可能说明整体偏弱。"
        ok, rej = self.load(acc)
        self.assertEqual(ok, [])
        self.assertIn("哈希", rej[0][1])

    def test_bad_review_records(self):
        cases = [lambda a: a["review"].update(decision="pending"), lambda a: a["review"].update(reviewer="claude-opus"),
                 lambda a: a["review"].update(reviewer=""), lambda a: a["review"].update(reviewed_at="2026-11-04T15:00:00+08:00"),
                 lambda a: a["review"].update(note="<img src=x onerror=alert(1)>"), lambda a: a["review"].update(extra="x"),
                 lambda a: a.update(schema="x"), lambda a: a.pop("review")]
        for i, m in enumerate(cases):
            acc = make_accepted(make_report(self.data))
            m(acc)
            ok, rej = self.load(acc)
            self.assertEqual(ok, [], i)
            self.assertEqual(len(rej), 1, i)

    def test_filename_traversal_and_mismatch(self):
        acc = make_accepted(make_report(self.data))
        ok, rej = self.load(acc, name="brief-2026-11-03.json")
        self.assertEqual(ok, [])
        (self.acc_dir / "brief-2026-11-03.json").unlink()
        ok, rej = self.load(acc, name="..evil.json")
        self.assertEqual(ok, [])
        (self.acc_dir / "..evil.json").unlink()
        (self.acc_dir / "sub").mkdir()
        ok, rej = self.load(acc)
        self.assertEqual(len(ok), 1)
        self.assertEqual(len(rej), 1)

    def test_internal_exception_not_exposed(self):
        with patch.object(rb, "validate_accepted", side_effect=RuntimeError("C:/Users/secret/path")):
            ok, rej = self.load(make_accepted(make_report(self.data)))
        self.assertNotIn("secret", rej[0][1])

    def test_escape_everywhere(self):
        acc = make_accepted(make_report(self.data))
        acc["report_sha256"] = "c" * 64
        acc["report"]["ai"]["summary"][0]["text"] = "<script>alert(1)</script>&"
        acc["review"]["reviewer"] = "<b>Codex</b>"
        acc["report"]["evidence"]["facts"][6]["value"] = "<img src=x>"
        acc["report"]["evidence"]["facts"][3]["label"] = "<i>上涨</i>"
        html = rb.detail_body(acc, D, D) + rb.index_body([acc], D, [("<x>.json", "<bad>")])
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("<b>Codex", html)
        self.assertNotIn("<i>", html)
        self.assertIn("&lt;script&gt;", html)


FAKE = r'''
import json, os, subprocess, sys, time
args = sys.argv[1:]
log = os.environ.get("FAKE_LOG_PATH_FROM_ARGV") or args[0]
args = args[1:]
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": args, "cwd": os.getcwd(), "env": sorted(os.environ)}, ensure_ascii=False) + "\n")
cfg = json.load(open(os.path.join(os.path.dirname(log), "fake_cfg.json"), encoding="utf-8"))
if args[:2] == ["auth", "status"]:
    a = cfg["auth"]
    if a == "fail":
        sys.exit(1)
    if a == "garbage":
        print("not json"); sys.exit(0)
    st = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "email": "x@example.com"}
    if a == "apikey": st["authMethod"] = "apiKey"
    if a == "loggedout": st["loggedIn"] = False
    if a == "bedrock": st["apiProvider"] = "bedrock"
    if a == "missing": st.pop("apiProvider")
    print(json.dumps(st)); sys.exit(0)
mode = cfg["mode"]
if mode == "noread":
    time.sleep(60)
prompt = sys.stdin.buffer.read().decode("utf-8")
with open(os.path.join(os.path.dirname(log), "fake_prompt.txt"), "w", encoding="utf-8") as fh:
    fh.write(prompt)
ai = cfg["ai"]
init = {"type": "system", "subtype": "init", "model": "fake-model-1", "apiKeySource": "none", "tools": [], "mcp_servers": [], "claude_code_version": "0.0-fake"}
res = {"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(ai, ensure_ascii=False), "modelUsage": {"fake-model-1": {}}}
def child():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    open(os.path.join(os.path.dirname(log), "grandchild.pid"), "w").write(str(p.pid))
if mode == "exit":
    sys.stderr.write("boom"); sys.exit(3)
if mode == "sleep":
    time.sleep(60)
if mode == "grandchild":
    child(); time.sleep(60)
if mode == "orphan":
    child()
if mode == "flood":
    chunk = b"x" * 65536
    for _ in range(200):
        sys.stdout.buffer.write(chunk)
    sys.stdout.flush(); time.sleep(60)
if mode == "errflood":
    for _ in range(100):
        sys.stderr.buffer.write(b"e" * 65536)
    time.sleep(60)
if mode == "badjson":
    print("not json"); sys.exit(0)
if mode == "fenced":
    res["result"] = "```json\n" + res["result"] + "\n```"
if mode == "textnotjson":
    res["result"] = "这是一段说明文字"
if mode == "apikey":
    init["apiKeySource"] = "ANTHROPIC_API_KEY"
if mode == "nokeysource":
    init.pop("apiKeySource")
if mode == "tools":
    init["tools"] = ["Bash"]
if mode == "notools":
    init.pop("tools")
if mode == "error":
    res.update(subtype="error_during_execution", is_error=True)
if mode == "noinit":
    init = {"type": "system", "subtype": "other"}
if mode == "modelmismatch":
    res["modelUsage"] = {"other-model": {}}
for ev in (init, res):
    sys.stdout.buffer.write((json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8"))
'''

SECRET_ENV = {"ANTHROPIC_API_KEY": "sk-should-not-pass", "ANTHROPIC_BASE_URL": "http://x", "ANTHROPIC_AUTH_TOKEN": "t",
              "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CONFIG_DIR": "x",
              "AWS_ACCESS_KEY_ID": "a", "GOOGLE_APPLICATION_CREDENTIALS": "g", "AZURE_OPENAI_KEY": "z",
              "TUSHARE_TOKEN": "t", "MAIL_PASSWORD": "m", "PUSHPLUS_TOKEN": "p", "MINGPAN_PROFILE": "secret-birth"}


class GenerateTests(Base):
    def setUp(self):
        super().setUp()
        self.fake = self.t / "fake_claude.py"
        self.fake.write_text(FAKE, encoding="utf-8")
        self.log = self.t / "fake.log"
        rb.prepare(D, self.data, self.local)
        snap, rel, h = rb.load_snapshot(self.data, D)
        self.ev = rb.build_evidence(snap, rel, h)
        self.cfg(mode="ok")
        self.env = patch.dict(os.environ, SECRET_ENV)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def cfg(self, mode="ok", auth="ok", ai=None):
        (self.t / "fake_cfg.json").write_text(json.dumps({"mode": mode, "auth": auth, "ai": ai or good_ai(self.ev)}, ensure_ascii=False), encoding="utf-8")

    def run_gen(self, mode="ok", auth="ok", timeout=20, ai=None):
        self.cfg(mode, auth, ai)
        return rb.generate(D, self.local, self.data, str(self.log), timeout, cmd_prefix=[sys.executable, "-I", str(self.fake)])

    def calls(self):
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []

    def work(self):
        return self.local / f"brief-{D}"

    def no_draft(self):
        self.assertFalse((self.work() / "draft.json").exists())

    def test_success_with_auth_preflight_restricted_flags_and_env_allowlist(self):
        p, h = self.run_gen("ok")
        rep = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(rep["generation"]["model"], "fake-model-1")
        self.assertEqual(rep["generation"]["prompt_version"], "brief-prompt/2")
        self.assertIn("+07:00", rep["generation"]["generated_at"])
        self.assertEqual(rb.validate_report(rep, self.data), h)
        auth, gen = self.calls()
        self.assertEqual(auth["argv"], ["auth", "status", "--json"])
        argv = gen["argv"]
        for flag in ("-p", "--safe-mode", "--restricted", "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands", "--no-chrome"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--mcp-config") + 1], '{"mcpServers":{}}')
        self.assertEqual(argv[argv.index("--permission-prompts") + 1], "none")
        self.assertEqual(argv[argv.index("--system-prompt") + 1], rb.SYSTEM_PROMPT)
        for flag in ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "--add-dir", "--resume", "--continue", "--bare"):
            self.assertNotIn(flag, argv)
        for call in (auth, gen):
            leaked = [k for k in call["env"] if k.upper() in {s.upper() for s in SECRET_ENV} or k.upper().startswith(rb.ENV_DENY_PREFIX)]
            self.assertEqual(leaked, [])
            self.assertTrue({k.upper() for k in call["env"]} <= rb.ENV_ALLOW)
            self.assertFalse(str(Path(call["cwd"]).resolve()).startswith(str(ROOT.resolve())))
        prompt = (self.t / "fake_prompt.txt").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), rep["generation"]["prompt_sha256"])
        self.assertIn('"fact_id": "mkt.mom20_median"', prompt)
        for private in ("MINGPAN", "secret-birth", "catalano", "17310", "CLAUDE.md", "TUSHARE", "x@example.com"):
            self.assertNotIn(private, prompt)
        self.assertNotIn("x@example.com", json.dumps(rep))
        rb.check_receipt(self.work(), rep)
        with self.assertRaises(rb.BriefError):
            self.run_gen("ok")

    def test_auth_preflight_failures_never_send_evidence(self):
        for auth in ("fail", "garbage", "apikey", "loggedout", "bedrock", "missing"):
            self.log.unlink(missing_ok=True)
            with self.assertRaisesRegex(rb.BriefError, "未发送证据包", msg=auth):
                self.run_gen("ok", auth=auth)
            self.assertEqual([c["argv"][:2] for c in self.calls()], [["auth", "status"]], auth)
            self.assertFalse((self.t / "fake_prompt.txt").exists(), auth)
            self.no_draft()
        for err in self.work().glob("generate-error-*.json"):
            self.assertNotIn("x@example.com", err.read_text(encoding="utf-8"))

    def test_fenced_json_accepted(self):
        self.run_gen("fenced")
        self.assertTrue((self.work() / "draft.json").exists())

    def test_failures_leave_no_draft(self):
        for mode in ("exit", "badjson", "textnotjson", "apikey", "nokeysource", "tools", "notools", "error", "noinit", "modelmismatch"):
            with self.assertRaises(rb.BriefError, msg=mode):
                self.run_gen(mode)
            self.no_draft()
        self.assertTrue(list(self.work().glob("generate-error-*.json")))

    def test_timeout_kills_tree_but_not_siblings(self):
        sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # 模拟同机其他会话，不能被误杀
        try:
            with self.assertRaisesRegex(rb.BriefError, "超时"):
                self.run_gen("grandchild", timeout=3)
            gpid = int((self.t / "grandchild.pid").read_text())
            self.assertTrue(wait_dead(gpid), "孙进程遗留")
            self.assertTrue(alive(sentinel.pid))
            self.assertTrue(alive(os.getpid()))
            self.no_draft()
        finally:
            sentinel.kill()
            sentinel.wait()

    def test_child_not_reading_stdin_times_out(self):
        with patch.object(rb, "PROMPTS", {**rb.PROMPTS, rb.PROMPT_VERSION: lambda ev: rb.build_prompt_v2(ev) + "填充" * 200000}):
            t0 = time.time()
            with self.assertRaisesRegex(rb.BriefError, "超时"):
                self.run_gen("noread", timeout=3)
            self.assertLess(time.time() - t0, 30)
        self.no_draft()

    def test_output_flood_bounded(self):
        for mode in ("flood", "errflood"):
            t0 = time.time()
            with self.assertRaisesRegex(rb.BriefError, "上限", msg=mode):
                self.run_gen(mode, timeout=30)
            self.assertLess(time.time() - t0, 25, mode)
            self.no_draft()

    def test_orphan_grandchild_cleaned_after_normal_exit(self):
        self.run_gen("orphan")
        gpid = int((self.t / "grandchild.pid").read_text())
        self.assertTrue(wait_dead(gpid), "正常结束后孙进程遗留")

    def test_model_output_failing_rules_rejected(self):
        bad = good_ai(self.ev)
        bad["interpretation"][0]["evidence_ids"] = ["fake.id"]
        with self.assertRaises(rb.BriefError):
            self.run_gen("ok", ai=bad)
        bad = good_ai(self.ev)
        bad["summary"][0]["text"] = "20日动量中位数为 +2.92%。"
        bad["summary"][0]["evidence_ids"] = ["mkt.mom20_median"]
        with self.assertRaises(rb.BriefError):
            self.run_gen("ok", ai=bad)
        self.no_draft()

    def test_generate_requires_matching_evidence(self):
        s = self.snap()
        s["all_results"][0]["name"] = "白银X"
        self.write_snap(s)
        with self.assertRaises(rb.BriefError):
            self.run_gen("ok")
        self.assertEqual(self.calls(), [])  # 证据不一致时根本不调用 CLI


def build(data, out, acc_dir):
    with patch.object(sys, "argv", ["build_site.py", "--data", str(data), "--out", str(out)]), \
            patch.object(rb, "ACCEPTED_DIR", acc_dir), contextlib.redirect_stdout(io.StringIO()):
        build_site.main()


class SiteTests(Base):
    """用全量 data/ 建站，确认真实空态、旧页面与 data/ 不变；合成验收报告只放临时目录"""

    def setUp(self):
        super().setUp()
        self.full = ROOT / "data"
        self.before = tree_hash(self.full)

    def tearDown(self):
        self.assertEqual(self.before, tree_hash(self.full), "data/ 被修改")
        super().tearDown()

    def accept_fixture(self, d):
        self.acc_dir.mkdir(exist_ok=True)
        acc = make_accepted(make_report(self.data, d=d))
        (self.acc_dir / f"brief-{d}.json").write_text(json.dumps(acc, ensure_ascii=False), encoding="utf-8")

    def page(self, out, name):
        return (out / name).read_text(encoding="utf-8")

    def test_empty_state_when_no_accepted(self):
        out = self.t / "site"
        build(self.full, out, self.acc_dir)
        html = self.page(out, "briefs.html")
        self.assertIn("目前没有已审阅的 AI 简报；可先查看<a href='archive.html'>量化日报</a>。", html)
        self.assertNotIn("模板", html)
        self.assertEqual(list((out / "briefs").iterdir()), [])
        self.assertIn("没有已验收的 AI 简报", self.page(out, "status.html"))
        for name in ("archive.html", "method.html", "index.html", f"reports/{D}.html"):
            self.assertTrue((out / name).exists())
        self.assertIn("程序规则生成", self.page(out, "archive.html"))
        top = re.search(r'<nav class="nav">(.*?)<button', html, re.S).group(1)
        self.assertIn("href='briefs.html'", top)
        sub = re.search(r"<nav class='subnav'.*?</nav>", html, re.S).group(0)
        self.assertEqual(re.findall(r"href='([^']+)'", sub), ["briefs.html", "archive.html", "method.html"])
        for p in sorted(self.full.glob("????-??-??.json")):
            self.assertEqual(p.read_bytes(), (out / "data" / p.name).read_bytes())

    def test_unaccepted_draft_not_published(self):
        draft_dir = self.t / "local" / f"brief-{D}"
        draft_dir.mkdir(parents=True)
        (draft_dir / "draft.json").write_text(json.dumps(make_report(self.data)), encoding="utf-8")
        out = self.t / "site"
        build(self.full, out, self.acc_dir)
        self.assertIn("目前没有已审阅的 AI 简报", self.page(out, "briefs.html"))

    def test_readable_detail_page(self):
        self.accept_fixture(D)
        out = self.t / "site"
        build(self.data, out, self.acc_dir)
        html = self.page(out, f"briefs/brief-{D}.html")
        main, _, tech = html.partition("<details>")
        self.assertIn("<a class='b-ref' href='#f-breadth.up'>上涨品种数</a>", main)
        self.assertNotIn(">breadth.up<", main)
        self.assertNotIn("fixture-model", main)
        self.assertNotIn("source_field", main)
        self.assertNotIn("确定事实表", html)
        self.assertIn("本站快照依据", main)
        self.assertIn("<th>项目</th><th>数值</th></tr>", main)
        self.assertIn("曼谷时间", main)
        self.assertIn("2026-11-04 15:00", main)  # 北京 16:00 = 曼谷 15:00
        self.assertIn("fixture-model", tech)
        self.assertIn("<code>breadth.up</code>", tech)
        for h in re.findall(r"href='(\.\./[^'#]+)'", html):
            self.assertTrue((out / "briefs" / h).resolve().exists(), h)

    def test_current_then_historical_and_rebuild_keeps_brief(self):
        self.accept_fixture(D)
        out = self.t / "site"
        for _ in range(2):  # 两次建站都保留简报，且不重复创建
            build(self.data, out, self.acc_dir)
            self.assertEqual([p.name for p in (out / "briefs").iterdir()], [f"brief-{D}.html"])
        detail = self.page(out, f"briefs/brief-{D}.html")
        self.assertIn(f"当前：这份简报对应最新扫描日期 {D}", detail)
        self.assertIn(f"href='../reports/{D}.html'", detail)
        self.assertIn("当前：最新交易日已有已验收 AI 简报", self.page(out, "status.html"))
        self.next_day()
        with patch.object(rb, "_now", lambda: datetime(2026, 11, 5, 20, 0, tzinfo=BKK)):
            build(self.data, out, self.acc_dir)
        for page in (self.page(out, "briefs.html"), self.page(out, f"briefs/brief-{D}.html")):
            self.assertIn("最新扫描日期 2026-11-05 尚无已验收 AI 简报", page)
            self.assertNotIn("当前：这份简报", page)
        self.assertIn("历史：最新交易日 2026-11-05 尚无已验收 AI 简报", self.page(out, "status.html"))

    def test_old_detail_with_newer_accepted_brief(self):
        """有 11-03、11-04 两份已验收：浏览 11-03 不能声称 11-04 没有简报"""
        self.accept_fixture("2026-11-03")
        self.accept_fixture(D)
        out = self.t / "site"
        build(self.data, out, self.acc_dir)
        old = self.page(out, "briefs/brief-2026-11-03.html")
        self.assertIn("历史简报：对应数据日期 2026-11-03；最新扫描日期 2026-11-04。", old)
        self.assertIn("最新扫描日期已有已验收 AI 简报：<a href='brief-2026-11-04.html'>", old)
        self.assertNotIn("尚无", old)
        self.assertIn(f"当前：这份简报对应最新扫描日期 {D}", self.page(out, "briefs.html"))
        # 再来一天：11-05 没有简报，11-03 页指向较新的 11-04
        self.next_day()
        with patch.object(rb, "_now", lambda: datetime(2026, 11, 5, 20, 0, tzinfo=BKK)):
            build(self.data, out, self.acc_dir)
        old = self.page(out, "briefs/brief-2026-11-03.html")
        self.assertIn("较新的已验收简报是 <a href='brief-2026-11-04.html'>2026-11-04</a>", old)
        self.assertIn("最新扫描日期 2026-11-05 尚无已验收 AI 简报", old)
        idx = self.page(out, "briefs.html")
        self.assertIn("历史简报：对应数据日期 2026-11-04；最新扫描日期 2026-11-05。", idx)
        for h in re.findall(r"href='(brief-[^']+)'", old):
            self.assertTrue((out / "briefs" / h).exists(), h)

    def test_invalid_accepted_keeps_daily_site(self):
        self.acc_dir.mkdir()
        (self.acc_dir / f"brief-{D}.json").write_text("{broken", encoding="utf-8")
        out = self.t / "site"
        build(self.data, out, self.acc_dir)
        html = self.page(out, "briefs.html")
        self.assertIn("目前没有已审阅的 AI 简报", html)
        self.assertIn("未通过校验", html)
        self.assertTrue((out / "index.html").exists())
        self.assertIn("1 份未通过", self.page(out, "status.html"))


class RepoHygieneTests(unittest.TestCase):
    def test_local_dir_ignored_and_no_fixture_in_public_content(self):
        self.assertIn(".local-briefs/", (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
        for p in (ROOT / "briefs").rglob("*.json") if (ROOT / "briefs").exists() else []:
            self.assertNotIn("fixture", p.read_text(encoding="utf-8"), p)


if __name__ == "__main__":
    unittest.main()
