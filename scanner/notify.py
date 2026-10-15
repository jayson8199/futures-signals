#!/usr/bin/env python3
"""
每日推送：邮件（SMTP SSL，QQ 邮箱）+ 微信（PushPlus）
凭据只从环境变量读取（GitHub Secrets）：
  MAIL_SENDER / MAIL_PASSWORD / MAIL_RECEIVER / MAIL_SMTP(默认 smtp.qq.com) / PUSHPLUS_TOKEN
用法：python scanner/notify.py --date 2026-10-15 [--site-url https://...]
未配置的通道自动跳过，推送失败不影响流水线（退出码恒为 0）。
"""
import argparse
import json
import os
import smtplib
import sys
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from urllib import parse, request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scanner"))
import history  # noqa: E402
import macd8  # noqa: E402
from scan import SYMBOLS  # noqa: E402

LONG_PATS, SHORT_PATS = {"高富帅", "跌势将尽"}, {"白富美", "涨势将尽"}


def build_summary(data, site_url):
    D = data["data_date"]
    mkt = data.get("market") or {}
    P = data["patterns"]
    lines = [f"📅 {D} ｜ 市场环境：{mkt.get('regime', '')}市（20日中位动量 {mkt.get('mom20_median', '--')}%）",
             f"涨 {data['up_count']} / 跌 {data['down_count']} ｜ 双20%强信号 {data['strong_count']} 个", ""]

    weak = mkt.get("regime") == "弱势"
    gao = P["高富帅"]["items"]
    if gao:
        def tag(i):
            pc, hc = i["price_change_pct"], i["hold_change_pct"]
            t = "⚠️追高" if pc > 3 else ("⭐⭐优选" if 0 < pc <= 2 and 2 <= hc <= 5 else "")
            return (t + ("🛡" if weak else "")) or ""
        lines.append(f"👑 高富帅 {len(gao)} 个：" + "、".join(f"{i['name']}{tag(i)}" for i in gao))
    else:
        lines.append("👑 高富帅：无")
    bai = P["白富美"]["items"]
    lines.append(f"💎 白富美 {len(bai)} 个（降级观察）：" + ("、".join(i["name"] for i in bai) if bai else "无"))
    warn = sorted(P["涨势将尽"]["items"], key=lambda x: x["hold_change_pct"])[:5]
    if warn:
        lines.append("🍂 警惕（涨势将尽）：" + "、".join(i["name"] for i in warn))

    # MACD 买卖点 + 双重共振
    H = history.load_all()
    sigs = [s for s in macd8.scan_all(H, SYMBOLS, since=D) if s["date"] == D]
    pat = {i["symbol"]: i["pattern"] for i in data["all_results"]}
    lines.append("")
    if sigs:
        lines.append(f"📈 MACD 买卖点 {len(sigs)} 个：")
        for s in sigs:
            p = pat.get(s["symbol"], "")
            res = "⚡共振" if (s["direction"] == "多" and p in LONG_PATS) or (s["direction"] == "空" and p in SHORT_PATS) else ""
            lines.append(f"  [{s['direction']}] {s['name']} · {s['short']}（形态：{p}）{res}")
    else:
        lines.append("📈 MACD 买卖点：今日无首发信号")

    if gao or bai:
        lines.append("")
        lines.append("弱势市：关注抗跌型高富帅，避开追高。" if weak else "强势市：高富帅顺势为主，避开涨幅>3%的追高品种。")
    lines += ["", f"完整报告：{site_url}", f"历史战绩：{site_url}stats.html", "", "（程序自动生成，仅供学习交流，不构成投资建议）"]
    return "\n".join(lines)


def send_mail(subject, body):
    sender, pwd, recv = os.environ.get("MAIL_SENDER"), os.environ.get("MAIL_PASSWORD"), os.environ.get("MAIL_RECEIVER")
    if not (sender and pwd and recv):
        return "邮件未配置，跳过"
    host = os.environ.get("MAIL_SMTP", "smtp.qq.com")
    msg = MIMEMultipart()
    msg["From"] = formataddr((str(Header("期货信号站", "utf-8")), sender))
    msg["To"] = recv
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        with smtplib.SMTP_SSL(host, 465, timeout=30) as s:
            s.login(sender, pwd)
            s.sendmail(sender, [recv], msg.as_string())
        return "邮件已发送"
    except Exception as e:
        return f"邮件失败：{e}"


def send_wechat(title, content):
    token = os.environ.get("PUSHPLUS_TOKEN")
    if not token:
        return "微信未配置，跳过"
    data = parse.urlencode({"token": token, "title": title[:100], "content": content, "template": "txt"}).encode()
    try:
        with request.urlopen(request.Request("https://www.pushplus.plus/send", data=data, method="POST"), timeout=30) as r:
            j = json.loads(r.read().decode())
        return "微信已推送" if j.get("code") == 200 else f"PushPlus 返回：{j.get('msg', j)}"
    except Exception as e:
        return f"微信失败：{e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--site-url", default="https://jayson8199.github.io/futures-signals/")
    args = ap.parse_args()
    f = ROOT / "data" / f"{args.date}.json"
    if not f.exists():
        print(f"无 {f.name}，不推送")
        return 0
    data = json.loads(f.read_text(encoding="utf-8"))
    body = build_summary(data, args.site_url)
    title = f"期货信号日报 {args.date}｜👑{data['patterns']['高富帅']['count']} 💎{data['patterns']['白富美']['count']}"
    print(body)
    print("---")
    print(send_mail(title, body))
    print(send_wechat(title, body))
    return 0


if __name__ == "__main__":
    sys.exit(main())
