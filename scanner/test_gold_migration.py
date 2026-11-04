"""黄金专题迁移回归：离线，用仓库真实 data/ 在全新临时目录建站，不联网、不推送、不改 data/。
运行：cd scanner && python -m unittest test_gold_migration"""
import contextlib
import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_site
import gold_page
import gold_snapshot

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path(os.environ.get("GOLD_SOURCE", ROOT.parent / "gold-observatory-migration-source"))
OLD_PAGES = ["index.html", "archive.html", "trend.html", "macd.html", "chart.html", "stats.html", "erqu.html", "cta.html",
             "oversold.html", "thushort.html", "macro.html", "method.html"]
NODE = shutil.which("node") or (r"C:\Program Files\nodejs\node.exe" if Path(r"C:\Program Files\nodejs\node.exe").exists() else None)


def tree_hash(folder: Path):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


def build(out: Path, rebuild=False):
    # build_site.main 会整体替换输出目录：测试只用临时目录下自建的 site 路径
    assert rebuild or not out.exists(), "测试只写全新的 site 路径"
    with patch.object(sys, "argv", ["build_site.py", "--data", str(ROOT / "data"), "--out", str(out)]), \
            contextlib.redirect_stdout(io.StringIO()) as log:
        build_site.main()
    return log.getvalue()


class ValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gold, cls.macro = gold_page.load_snapshots()

    def bad(self, mutate, gold=None):
        m = copy.deepcopy(self.macro)
        mutate(m)
        with self.assertRaises(ValueError):
            gold_page.validate_macro(m, gold or self.gold)

    def test_real_snapshots_pass(self):
        self.assertTrue(gold_page.validate_macro(self.macro, self.gold))
        self.assertEqual([s["id"] for s in self.macro["series"]], ["DFII10", "DTWEXBGS", "DCOILWTICO"])
        self.assertIs(self.macro["trainingEligible"], False)

    def test_fourth_series_rejected(self):
        self.bad(lambda m: m["series"].append(dict(copy.deepcopy(m["series"][0]), id="VIXCLS")))
        self.bad(lambda m: m["seriesIds"].append("VIXCLS"))

    def test_missing_or_reordered_series_rejected(self):
        self.bad(lambda m: m["series"].pop())
        self.bad(lambda m: m["series"].reverse())

    def test_mismatched_hash_rejected(self):
        self.bad(lambda m: m.update(goldRawSha256="0" * 64))
        self.bad(lambda m: None, gold=dict(self.gold, rawSha256="f" * 64))
        self.bad(lambda m: m.update(goldAsOf="2026-10-29"))

    def test_common_dates_recomputed(self):
        self.bad(lambda m: m["commonObservationDates"].pop())
        self.bad(lambda m: m.update(goldObservationCount=m["goldObservationCount"] + 1))

    def test_training_and_future_observation_rejected(self):
        self.bad(lambda m: m.update(trainingEligible=True))
        self.bad(lambda m: m["series"][0]["observations"].append({"date": "2026-11-02", "value": 1.0}))
        self.bad(lambda m: m["series"][2]["observations"][3].update(value=float("nan")))
        self.bad(lambda m: m["series"][1]["observations"][3].update(date="2026-02-30"))

    def test_gold_validator(self):
        g = copy.deepcopy(self.gold)
        g["prices"].pop()
        with self.assertRaises(ValueError):
            gold_page.validate_gold(g)
        g = copy.deepcopy(self.gold)
        g["prices"][10]["close"] = -1
        with self.assertRaises(ValueError):
            gold_page.validate_gold(g)

    def test_no_vix_values_and_no_private_text_in_public_assets(self):
        for name in gold_page.ASSET_FILES:
            text = (gold_page.ASSET_DIR / name).read_text(encoding="utf-8")
            for word in ("Copyright Cboe", "私人研究", "HOWARD", "Howard", "Private"):
                self.assertFalse(word in text, f"{name} 含 {word}")
        for s in self.macro["series"]:
            self.assertNotIn("VIX", json.dumps(s, ensure_ascii=False).upper())
        self.assertEqual([e["id"] for e in self.macro["excludedSeries"]], ["VIXCLS"])
        self.assertEqual(set(self.macro["excludedSeries"][0]), {"id", "reason"})  # 只记录剔除原因，不含任何数值

    @unittest.skipUnless((SOURCE / "dist/data/macro.json").exists(), "原研究台源码不在本机")
    def test_importer_reproduces_committed_assets(self):
        gc, m3 = gold_snapshot.convert(SOURCE, self.gold["importedFrom"]["sourceCommit"])
        self.assertEqual(gold_snapshot.dump(gc), (gold_page.ASSET_DIR / "gc_snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(gold_snapshot.dump(m3), (gold_page.ASSET_DIR / "macro3.json").read_text(encoding="utf-8"))
        src = json.loads((SOURCE / "dist/data/macro.json").read_text(encoding="utf-8"))
        for s in m3["series"]:  # 数值与原快照逐条一致
            orig = next(x for x in src["series"] if x["id"] == s["id"])
            self.assertEqual(s["observations"], orig["observations"])
            self.assertEqual(s["rawSha256"], orig["rawSha256"])


class SiteBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data_before = tree_hash(ROOT / "data")
        cls.site = Path(cls.tmp.name) / "site"
        cls.log = build(cls.site)
        cls.latest = json.loads((cls.site / "data" / "latest.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def page(self, name):
        return (self.site / name).read_text(encoding="utf-8")

    def test_old_urls_and_new_pages_exist(self):
        for name in OLD_PAGES + ["gold.html", "research.html", "strategies.html", "status.html"]:
            self.assertTrue((self.site / name).exists(), name)
        self.assertTrue((self.site / "reports" / f"{self.latest['data_date']}.html").exists())

    def test_five_top_entries_and_every_old_page_in_secondary_nav(self):
        self.assertEqual([g[1] for g in build_site.NAV_GROUPS], ["今日总览", "品种研究", "策略验证", "研究简报", "运行状态"])
        linked = {h for g in build_site.NAV_GROUPS for h, _, _ in g[3]}
        self.assertTrue(set(OLD_PAGES) <= linked)
        top = re.search(r'<nav class="nav">(.*?)<button', self.page("gold.html"), re.S).group(1)
        self.assertEqual(len(re.findall(r"<a ", top)), 5)
        self.assertIn("class='subnav'", self.page("gold.html"))

    def test_all_internal_links_resolve_including_reports(self):
        pages = list(self.site.glob("*.html")) + [self.site / "reports" / f"{self.latest['data_date']}.html"]
        for page in pages:
            for href in re.findall(r"""(?:href|src)=['"]([^'"]+)['"]""", page.read_text(encoding="utf-8")):
                if href.startswith(("http://", "https://", "#", "mailto:", "javascript:")):
                    continue
                target = (page.parent / href.split("?")[0].split("#")[0]).resolve()
                self.assertTrue(target.exists(), f"{page.name} → {href}")
        report = (self.site / "reports" / f"{self.latest['data_date']}.html").read_text(encoding="utf-8")
        for h in ("../index.html", "../research.html", "../strategies.html", "../briefs.html", "../status.html"):
            self.assertIn(f"href='{h}'", report)

    def test_gold_page_from_actual_data(self):
        html = self.page("gold.html")
        au0 = next(i for i in self.latest["all_results"] if i["symbol"] == "AU0")
        self.assertIn(f"数据日期 {au0['date']}", html)
        self.assertIn("chart.html?s=AU0", html)
        self.assertIn(f"{au0['today_close']:g}", html)
        self.assertIn("人民币元 / 克", html)
        self.assertIn("USD / 金衡盎司", html)
        self.assertIn("最近完整日线 2026-10-30", html)
        self.assertIn("<script type='module' src='assets/gold/gold.mjs'></script>", html)
        self.assertNotIn("<iframe", html)
        for word in ("XGBoost", "已训练", "实时行情：", "自动更新中", "HOWARD"):
            self.assertNotIn(word, html)

    def test_status_page_separates_data_date_and_build_time(self):
        html = self.page("status.html")
        self.assertIn(self.latest["data_date"], html)
        self.assertIn("本页生成时间", html)
        self.assertIn("https://github.com/jayson8199/futures-signals/actions", html)
        self.assertIn("最近完整日线 2026-10-30", html)
        for word in ("任务成功", "运行成功", "全部正常"):
            self.assertNotIn(word, html)

    def test_archive_labelled_as_programmatic_reports(self):
        self.assertIn("不是人工或 AI 撰写", self.page("archive.html"))

    def test_assets_survive_repeated_build_and_data_unchanged(self):
        first = tree_hash(self.site / "assets" / "gold")
        self.assertEqual(first, {n: hashlib.sha256((gold_page.ASSET_DIR / n).read_bytes()).hexdigest() for n in gold_page.ASSET_FILES})
        with tempfile.TemporaryDirectory() as t:
            again = Path(t) / "site"
            build(again)
            shutil.rmtree(again / "assets" / "gold")  # 模拟产物缺失，在同一自有路径重建后应重新出现
            build(again, rebuild=True)
            self.assertEqual(tree_hash(again / "assets" / "gold"), first)
            self.assertTrue((again / "gold.html").exists())
        self.assertEqual(tree_hash(ROOT / "data"), self.data_before)

    def test_no_vix_in_site_assets(self):
        for p in (self.site / "assets" / "gold").glob("*.json"):
            obj = json.loads(p.read_text(encoding="utf-8"))
            for s in obj.get("series", []):
                self.assertNotEqual(s["id"], "VIXCLS")
            self.assertNotIn("Copyright Cboe", p.read_text(encoding="utf-8"))

    def broken_build(self, breakage):
        """在临时资产副本上制造故障后建站，返回 site 路径；故障只影响副本"""
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        assets = Path(t) / "assets"
        shutil.copytree(gold_page.ASSET_DIR, assets)
        breakage(assets)
        site = Path(t) / "site"
        with patch.object(gold_page, "ASSET_DIR", assets):
            build(site)
        return site

    def assert_unavailable(self, site):
        self.assertTrue((site / "index.html").exists())
        html = (site / "gold.html").read_text(encoding="utf-8")  # 导航链接不能变成死链
        self.assertIn("GC=F 历史快照和美国宏观数据暂不可用", html)
        self.assertIn("chart.html?s=AU0", html)                    # AU0 每日扫描照常显示
        self.assertNotIn("assets/gold/gold.mjs", html)             # 不加载脚本与快照
        self.assertNotIn("最近完整日线", html)
        self.assertFalse((site / "assets" / "gold").exists())      # 不发布未通过校验的快照
        status = (site / "status.html").read_text(encoding="utf-8")
        self.assertIn("校验未通过", status)
        self.assertIn("页面生成失败：gold.html", status)
        for page in (site / "gold.html", site / "status.html"):
            for href in re.findall(r"""(?:href|src)=['"]([^'"]+)['"]""", page.read_text(encoding="utf-8")):
                if not href.startswith(("http://", "https://", "#")):
                    self.assertTrue((site / href.split("?")[0]).exists(), f"{page.name} → {href}")

    def test_mismatched_hash_gives_unavailable_page(self):
        def corrupt(a):
            m = json.loads((a / "macro3.json").read_text(encoding="utf-8"))
            m["goldRawSha256"] = "0" * 64
            (a / "macro3.json").write_text(json.dumps(m), encoding="utf-8")
        self.assert_unavailable(self.broken_build(corrupt))

    def test_missing_snapshot_file_gives_unavailable_page(self):
        self.assert_unavailable(self.broken_build(lambda a: (a / "macro3.json").unlink()))

    def test_invalid_json_gives_unavailable_page(self):
        self.assert_unavailable(self.broken_build(lambda a: (a / "gc_snapshot.json").write_text("{", encoding="utf-8")))

    def test_missing_script_after_partial_copy_gives_unavailable_page(self):
        self.assert_unavailable(self.broken_build(lambda a: (a / "gold.mjs").unlink()))

    def test_user_facing_copy_is_short_and_provenance_collapsed(self):
        html = self.page("gold.html")
        note = re.search(r"<div class='g-note'>(.*?)</div>", html, re.S).group(1)
        for word in ("vintage", "归档只读", "发布范围", "管线", "SHA", "提交"):
            self.assertNotIn(word, note)
        for word in ("不是实时行情", "没有预测模型", "不会自动更新", "2026-10-30"):
            self.assertIn(word, note)
        gold, _ = gold_page.load_snapshots()
        for secret in (gold["rawSha256"], gold["importedFrom"]["sourceCommit"][:7]):
            i = html.index(secret)
            self.assertGreater(html.rfind("<details", 0, i), html.rfind("</details>", 0, i), secret + " 应在折叠区内")

    @unittest.skipUnless(NODE, "未安装 Node")
    def test_frontend_node_suite_against_built_site(self):
        r = subprocess.run([NODE, str(Path(__file__).with_name("test_gold_assets.mjs")), str(self.site)],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
