"""日报发布回归：隔离临时目录，行情、SMTP、PushPlus全部模拟，不真实发送。"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import notify
import run_daily


def snapshot(day="2026-11-03", count=54):
    return {
        "data_date": day, "valid_count": count, "up_count": count, "down_count": 0,
        "patterns": {"高富帅": {"count": count}, "白富美": {"count": 0}},
        "all_results": [{"symbol": f"S{i}", "date": day} for i in range(count)],
    }


class DailyScanTests(unittest.TestCase):
    def run_scan(self, result=None, existing=None, error=None, date="2026-11-03", force=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            if existing is not None:
                (root / "data" / f"{date}.json").write_text(json.dumps(existing), encoding="utf-8")
            outputs = root / "outputs.txt"
            argv = ["run_daily.py", "--max-rounds", "1", "--interval", "0"]
            if force:
                argv.append("--force")
            with patch.object(run_daily, "ROOT", root), \
                    patch.object(run_daily, "report_date", return_value=date), \
                    patch.object(run_daily, "scan", return_value=result, side_effect=error) as scan, \
                    patch("history.merge_from_data", return_value=0), \
                    patch.object(sys, "argv", argv), \
                    patch.dict(os.environ, {"GITHUB_OUTPUT": str(outputs)}), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = run_daily.main()
            return code, outputs.read_text(), scan.call_count, sorted(p.name for p in (root / "data").glob("*.json"))

    def test_after_midnight_uses_previous_close(self):
        self.assertEqual(run_daily.report_date(datetime(2026, 11, 3, 5, 8)), "2026-11-02")

    def test_monday_morning_uses_friday(self):
        self.assertEqual(run_daily.report_date(datetime(2026, 11, 2, 7)), "2026-10-30")

    def test_weekend_uses_friday(self):
        self.assertEqual(run_daily.report_date(datetime(2026, 11, 1, 18)), "2026-10-30")

    def test_after_close_uses_today(self):
        self.assertEqual(run_daily.report_date(datetime(2026, 11, 3, 17, 5)), "2026-11-03")

    def test_complete_snapshot_publishes(self):
        code, output, calls, files = self.run_scan(snapshot())
        self.assertEqual((code, calls, files), (0, 1, ["2026-11-03.json"]))
        self.assertIn("updated=true", output)

    def test_backup_does_not_rescan_valid_snapshot(self):
        code, output, calls, _ = self.run_scan(existing=snapshot())
        self.assertEqual((code, calls), (0, 0))
        self.assertIn("updated=false", output)

    def test_bad_existing_snapshot_is_not_a_completion_receipt(self):
        code, output, calls, _ = self.run_scan(snapshot(), existing={"bad": True})
        self.assertEqual((code, calls), (0, 1))
        self.assertIn("updated=true", output)

    def test_partial_today_fails_without_publishing(self):
        code, output, _, files = self.run_scan(snapshot(count=49))
        self.assertEqual((code, files), (1, []))
        self.assertIn("updated=false", output)

    def test_fifty_is_existing_minimum(self):
        self.assertEqual(self.run_scan(snapshot(count=50))[0], 0)

    def test_provider_failure_is_not_green_success(self):
        code, output, _, files = self.run_scan(error=RuntimeError("unavailable"))
        self.assertEqual((code, files), (1, []))
        self.assertIn("updated=false", output)

    def test_no_new_date_preserves_old_report(self):
        code, output, _, files = self.run_scan(snapshot("2026-11-02"))
        self.assertEqual((code, files), (0, []))
        self.assertIn("updated=false", output)

    def test_duplicate_symbols_cannot_satisfy_completeness(self):
        data = snapshot()
        data["all_results"][1]["symbol"] = data["all_results"][0]["symbol"]
        self.assertEqual(self.run_scan(data)[0], 1)

    def test_mixed_dates_are_rejected(self):
        data = snapshot()
        data["all_results"][0]["date"] = "2026-11-02"
        self.assertEqual(self.run_scan(data)[0], 1)

    def test_wrong_valid_count_is_rejected(self):
        data = snapshot()
        data["valid_count"] = 100
        self.assertEqual(self.run_scan(data)[0], 1)

    def test_force_still_supports_manual_historical_save(self):
        self.assertEqual(self.run_scan(snapshot("2026-11-02", 40), force=True)[0], 0)


class NotificationTests(unittest.TestCase):
    def run_notify(self, mail="邮件已发送", wechat="微信已推送", day="2026-11-03", exists=True):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            if exists:
                (root / "data" / "2026-11-03.json").write_text(json.dumps(snapshot(day)), encoding="utf-8")
            with patch.object(notify, "ROOT", root), \
                    patch.object(sys, "argv", ["notify.py", "--date", "2026-11-03"]), \
                    patch.object(notify, "build_summary", return_value="isolated test"), \
                    patch.object(notify, "send_mail", return_value=mail) as send_mail, \
                    patch.object(notify, "send_wechat", return_value=wechat) as send_wechat, \
                    contextlib.redirect_stdout(io.StringIO()):
                code = notify.main()
            return code, send_mail.call_count, send_wechat.call_count

    def test_both_channels_success(self):
        self.assertEqual(self.run_notify(), (0, 1, 1))

    def test_mail_failure_still_attempts_wechat_but_fails_job(self):
        self.assertEqual(self.run_notify(mail="邮件失败：SMTPException"), (1, 1, 1))

    def test_wechat_failure_is_not_green_success(self):
        self.assertEqual(self.run_notify(wechat="微信失败：PushPlus未受理"), (1, 1, 1))

    def test_unconfigured_optional_channel_skips(self):
        self.assertEqual(self.run_notify(mail="邮件未配置，跳过"), (0, 1, 1))

    def test_missing_report_never_sends(self):
        self.assertEqual(self.run_notify(exists=False), (1, 0, 0))

    def test_wrong_report_date_never_sends(self):
        self.assertEqual(self.run_notify(day="2026-11-02"), (1, 0, 0))

    def test_pushplus_rejection_does_not_expose_response_or_token(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"code":500,"msg":"private token"}'
        with patch.dict(os.environ, {"PUSHPLUS_TOKEN": "private token"}), \
                patch.object(notify.request, "urlopen", return_value=response):
            self.assertEqual(notify.send_wechat("test", "test"), "微信失败：PushPlus未受理")

    def test_network_error_does_not_log_credentials(self):
        with patch.dict(os.environ, {"PUSHPLUS_TOKEN": "private token"}), \
                patch.object(notify.request, "urlopen", side_effect=RuntimeError("private token")):
            self.assertEqual(notify.send_wechat("test", "test"), "微信失败：RuntimeError")

    def test_smtp_refused_recipient_is_failure(self):
        smtp = MagicMock()
        smtp.__enter__.return_value.sendmail.return_value = {"recipient": (550, b"refused")}
        with patch.dict(os.environ, {"MAIL_SENDER": "sender", "MAIL_PASSWORD": "secret", "MAIL_RECEIVER": "recipient"}), \
                patch.object(notify.smtplib, "SMTP_SSL", return_value=smtp):
            self.assertEqual(notify.send_mail("test", "test"), "邮件失败：收件人被拒绝")

    def test_partial_mail_configuration_is_not_silently_skipped(self):
        with patch.dict(os.environ, {"MAIL_SENDER": "sender"}, clear=True):
            self.assertEqual(notify.send_mail("test", "test"), "邮件失败：配置不完整")


class WorkflowTests(unittest.TestCase):
    def test_notification_runs_after_deployment(self):
        workflow = (Path(__file__).resolve().parent.parent / ".github/workflows/daily.yml").read_text(encoding="utf-8")
        self.assertLess(workflow.index("uses: actions/deploy-pages@"), workflow.index("name: 推送邮件/微信"))
        self.assertNotIn("git pull --rebase origin main || true", workflow)


class ReportDisplayTests(unittest.TestCase):
    def test_exchange_labels_and_observation_title(self):
        import build_site
        from scan import SYMBOLS
        self.assertEqual(len(SYMBOLS), 54)
        self.assertEqual(SYMBOLS["PX0"][1], "郑商所")
        self.assertEqual(SYMBOLS["SH0"][1], "郑商所")
        self.assertEqual(SYMBOLS["EC0"][1], "上期能源")
        root = Path(__file__).resolve().parent.parent
        data = json.loads((root / "data/2026-11-03.json").read_text(encoding="utf-8"))
        original = json.dumps(data, ensure_ascii=False)
        body = build_site.build_report_body(data, None, [data["data_date"]])
        self.assertIn("今日优选 / 抗跌观察", body)
        self.assertNotIn("今日优选信号", body)
        self.assertIn("<td>集运指数</td><td class='muted'>上期能源</td>", body)
        # 展示修正不回写历史扫描原件。
        self.assertEqual(json.dumps(data, ensure_ascii=False), original)


if __name__ == "__main__":
    unittest.main()
