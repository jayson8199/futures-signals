#!/usr/bin/env python3
"""
命盘日报推送：邮件（SMTP SSL，QQ 邮箱）+ 微信（PushPlus）
凭据只从环境变量读取（GitHub Secrets），与 scanner/notify.py 共用同一组：
  MAIL_SENDER / MAIL_PASSWORD / MAIL_RECEIVER / MAIL_SMTP(默认 smtp.qq.com) / PUSHPLUS_TOKEN
未配置的通道自动跳过。
"""
import html
import json
import os
import re
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from urllib import parse, request


def md_to_html(md):
    """日报只用到标题、列表、粗体、分隔线，这里做最小转换给邮件用。"""
    out, in_list = [], False
    for line in md.splitlines():
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(line.strip()))
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{text[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("### "):
            out.append(f"<h3>{text[4:]}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{text[3:]}</h2>")
        elif line.strip() == "---":
            out.append("<hr>")
        elif text:
            out.append(f"<p>{text}</p>")
    if in_list:
        out.append("</ul>")
    return '<div style="font-size:15px;line-height:1.7">' + "\n".join(out) + "</div>"


def send_mail(subject, body, html_body=None):
    sender, pwd, recv = (os.environ.get(k) for k in ("MAIL_SENDER", "MAIL_PASSWORD", "MAIL_RECEIVER"))
    if not (sender and pwd and recv):
        return "邮件未配置，跳过"
    msg = MIMEText(html_body, "html", "utf-8") if html_body else MIMEText(body, "plain", "utf-8")
    msg["From"] = formataddr((str(Header("命盘日报", "utf-8")), sender))
    msg["To"] = recv
    msg["Subject"] = Header(subject, "utf-8")
    try:
        with smtplib.SMTP_SSL(os.environ.get("MAIL_SMTP") or "smtp.qq.com", 465, timeout=30) as s:
            s.login(sender, pwd)
            s.sendmail(sender, [recv], msg.as_string())
        return "邮件已发送"
    except Exception as e:
        return f"邮件失败：{type(e).__name__}"


def send_wechat(title, content, template="txt"):
    token = os.environ.get("PUSHPLUS_TOKEN")
    if not token:
        return "微信未配置，跳过"
    data = parse.urlencode({"token": token, "title": title[:100], "content": content, "template": template}).encode()
    try:
        req = request.Request("https://www.pushplus.plus/send", data=data, method="POST")
        with request.urlopen(req, timeout=30) as r:
            j = json.loads(r.read().decode())
        return "微信已推送" if j.get("code") == 200 else f"PushPlus 返回：{j.get('msg')}"
    except Exception as e:
        return f"微信失败：{type(e).__name__}"


def push(title, body, markdown=False):
    if markdown:
        return send_mail(title, body, md_to_html(body)), send_wechat(title, body, "markdown")
    return send_mail(title, body), send_wechat(title, body)
