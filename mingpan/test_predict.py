#!/usr/bin/env python3
"""
预测实验和日报版面的自检：python3 test_predict.py（在 mingpan 目录下运行，不推送、不写正式存档，只用临时目录）。
"""
import datetime
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import compose
import daily as D
import experiment as X
import layout
import predict as P

p = D.load_profiles()[0]
TZ = D.TZ
day = datetime.date
ok = []


def check(name, cond, detail=""):
    if not cond:
        sys.exit(f"失败：{name} {detail}")
    ok.append(name)


def at(d, hh, mm=0):
    return datetime.datetime.combine(d, datetime.time(hh, mm), TZ)


# 1. 10/26 回归：命盘小计 -1.8，调候 +0.5，最终 -1.3，3 星（重新算，不是写死的）
d = compose.build(p, day(2026, 10, 26), day(2026, 10, 25))
check("10/26 回归", (round(d["subtotal"], 1), round(d["sha_adj"], 1), round(d["score"], 1), d["stars"]) == (-1.8, 0.5, -1.3, 3),
      (d["subtotal"], d["sha_adj"], d["score"], d["stars"]))

# 2. 零候选、零入选、少于两条不硬凑、冲突信号
year = [P.build(p, day(2026, 10, 28) + datetime.timedelta(days=i)) for i in range(365)]
zero_pick = [r for r in year if not r["predictions"]]
no_cand = [r for r in year if not r["predictions"] and not r["unselected"]]
one = [r for r in year if len(r["predictions"]) == 1 and r["unselected"]]
check("有零入选的日子并写明原因", zero_pick and all(r["none_reason"] for r in zero_pick))
check("零候选的日子", all("都没有对应的信号" in r["none_reason"] for r in no_cand))
check("最多两条", max(len(r["predictions"]) for r in year) <= 2)
check("只有一条时不补第二条", one and all(all(u["net"] < P.THRESHOLD or "主依据" in u["reason"] for u in r["unselected"]) for r in one))
r26 = P.build(p, day(2026, 10, 26))
help26 = next(u for u in r26["unselected"] if u["event"] == "具体外部帮助")
check("冲突信号：相反依据压过门槛就不选", "相反依据" in help26["reason"] and any(s["weight"] < 0 for s in help26["signals"]))
check("每条预测都有完整字段", all(set(x) >= {"id", "event", "expect", "evidence", "occur", "exclude", "question"}
                                 for r in year for x in r["predictions"]))
check("不含出生资料", all(k not in json.dumps(r, ensure_ascii=False) for r in year[:30] for k in ("birth", "出生", "1988")))
check("只用事件库里的六类", {x["event"] for r in year for x in r["predictions"]} <= set(P.EVENTS))

with tempfile.TemporaryDirectory() as tmp:
    log = Path(tmp)
    t = day(2026, 10, 28)
    # 3. 事前保存、同日重发沿用、跨零点算回看
    rec, msg = X.save(p, t, log, at(t - datetime.timedelta(days=1), 21, 37))
    check("前一晚保存为事前", rec["kind"] == "事前", msg)
    rec2, msg2 = X.save(p, t, log, at(t - datetime.timedelta(days=1), 22, 41))
    lines = (log / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    check("重发沿用原记录", len(lines) == 1 and rec2["generated_at"] == rec["generated_at"], msg2)
    t2 = day(2026, 10, 29)
    rec3, _ = X.save(p, t2, log, at(t2, 0, 5))
    check("过了零点才保存记为回看", rec3["kind"] == "回看")
    check("回看有标记", any(f["kind"] == "生成晚了" for f in X._read(log / "flags.jsonl")))
    rec4, _ = X.save(p, t2 - datetime.timedelta(days=1), log, at(t2 - datetime.timedelta(days=2), 23, 59))
    check("23:59 保存第二天的算事前", rec4["kind"] == "事前")
    # 4. 程序变了：只追加更正，原记录照旧算数
    old = P.THRESHOLD
    P.THRESHOLD = 0.5
    first, msg5 = X.save(p, t, log, at(t, 1, 0))
    P.THRESHOLD = old
    kinds = [r["kind"] for r in X.records(log, t)]
    check("内容变了只追加更正", kinds == ["事前", "更正"] and first["kind"] == "事前", msg5)
    check("统计仍用原记录", X.formal(log, t)["fingerprint"] == rec["fingerprint"])

    # 5. 回答：老格式、新格式、格式错误
    okk, m = X.record(p, day(2026, 10, 27), "3BCBA ABBA 上午开会被批评", log)
    rows = (log / "ratings.csv").read_text(encoding="utf-8").splitlines()
    check("老格式照收", okk and rows[0] == ",".join(X.RATING_COLS) and "上午开会被批评" in rows[1], m)
    check("老格式不写观察", not (log / "observations.jsonl").exists())
    n27 = len(D.review(p, day(2026, 10, 27)))
    okk, m = X.record(p, day(2026, 10, 27), "4BCBA ABBA 改了一下", log)
    rows = (log / "ratings.csv").read_text(encoding="utf-8").splitlines()
    check("同一天再答改那一行", okk and len(rows) == 2 and rows[1].startswith("2026-10-27,4"))
    preds28 = X.formal(log, t)["predictions"]
    ans = f"3BCBA AB / 13 / {'A' * len(preds28) or '-'} / BA 下午客户改到周五, 很突然"
    okk, m = X.record(p, t, ans, log)
    obs = X._read(log / "observations.jsonl")[-1]
    check("新格式记录", okk and obs["events"] == ["contact", "friction"] and obs["acted"] == "B" and obs["effect"] == "A"
          and "改到周五" in obs["note"], m)
    check("备注里的逗号换成顿号", "改到周五、 很突然" in (log / "ratings.csv").read_text(encoding="utf-8"))
    bad, m = X.record(p, t, "3BCBA AB / 1x / - / AB", log)
    check("格式错误会说哪一段", not bad and "第二段" in m, m)
    bad, m = X.record(p, t, "3BCBA AB / 1 / AAAA / AB", log)
    check("观察字母数不对会提示", not bad and "第三段" in m, m)

    # 6. 漏答、汇总
    X.flag(t2, "漏发", "21:07 没发出，补发", log)
    t3 = day(2026, 10, 30)
    X.save(p, t3, log, at(t3 - datetime.timedelta(days=1), 21, 37))   # 10/30 存了但没答
    # 8. 发送和保存的核对：日志行原样比对指纹
    def line(tg, fp, mail="邮件已发送", wx="微信已推送"):
        return f"2026-10-28T14:07:31Z {tg} | {mail} | {wx} | 预测 v1 0 条 指纹 {fp} 提交 8ec4014"
    fp28 = X.formal(log, t)["fingerprint"]
    st, _ = X.verify(t, log, line(t, "000000000000"))
    check("指纹不同记为不一致", st == "不一致")
    st, _ = X.verify(t, log, line(t, fp28))
    check("有过不一致，后面再一致也仍算不一致", X.check_status(log, t) == "不一致")
    fp30 = X.formal(log, t3)["fingerprint"]
    st, _ = X.verify(t3, log, line(t3, fp30, "邮件未配置，跳过", "微信未配置，跳过"))
    check("两个渠道都没发出记为未发出", st == "未发出")
    st, _ = X.verify(t3, log, line(t3, fp30, "邮件已发送", "微信失败：Timeout"))
    check("一个渠道发出、指纹相同记为一致", st == "一致" and X.check_status(log, t3) == "一致")
    st, _ = X.verify(t3, log, line(t, fp30))
    check("日志行日期不对记为未核对", st == "未核对")
    check("一致之后再来一次未核对不改结论", X.check_status(log, t3) == "一致")
    t4 = day(2026, 10, 31)
    X.save(p, t4, log, at(t4 - datetime.timedelta(days=1), 21, 37))
    st, _ = X.verify(t4, log, missing="21:07 和备用都没跑")
    check("找不到日志记为未核对", st == "未核对" and X.check_status(log, t4) == "未核对")
    check("没核对的打了标记", any(f["kind"] == "核对未核对" for f in X._read(log / "flags.jsonl")))
    check("保存时记下提交号", X.formal(log, t4).get("commit"))
    # 真跑一次日报（没有推送凭据，两个渠道都跳过），日志行格式要能被 verify 读懂
    env = {k: v for k, v in __import__("os").environ.items() if k not in ("MAIL_SENDER", "PUSHPLUS_TOKEN")}
    env["GITHUB_SHA"] = "abcdef1234567"
    out = subprocess.run([sys.executable, "daily.py", "--date", "2026-10-31", "--send-date", "2026-10-30"],
                         capture_output=True, text=True, env=env, check=True).stdout
    m = X.LOG_RE.search(out)
    check("工作流日志行格式能解析", m and m.group(6) == X.formal(log, t4)["fingerprint"] and m.group(7) == "abcdef1", out)
    st, _ = X.verify(t4, log, out)
    check("没发出时不会被当成一致", st == "未发出")

    s = X.summary(log, day(2026, 10, 27), t4, today=day(2026, 11, 1))
    check("汇总有漏答", "漏答 1 天" in s, s)
    check("只有核对一致的进正式对照", "进正式对照的 1 天" in s and "不一致 1 天" in s and "未发出 1 天" in s, s)
    check("汇总不报准确率", "准确率" not in s and "%" not in s)
    check("没进正式对照的日子，影响也不计入", "因日报做了些什么 0 天" in s, s)
    check("汇总列出回看和漏发", "回看样本，不计入）1 天" in s and "漏发 1 次" in s, s)
    check("汇总分类别带分母", "有预测的日子" in s or "规则" not in s.split("分类别对比")[1].split("\n")[1])

    # 7. 预览不写正式存档：日报各种预览和复盘题都只读
    before = {f.name: f.read_bytes() for f in log.iterdir()}
    for args in (["--date", "2026-10-30", "--dry-run"], ["--date", "2026-10-30", "--wechat"],
                 ["--date", "2026-10-30", "--html", str(Path(tmp) / "x.html")],
                 ["--date", "2026-10-30", "--review", "--log-dir", str(log)]):
        subprocess.run([sys.executable, "daily.py", *args], check=True, capture_output=True)
    after = {f.name: f.read_bytes() for f in log.iterdir() if f.name != "x.html"}
    check("预览不碰存档", before == after)
    P.THRESHOLD = 0.5    # 现算会多出观察，复盘题仍应按事前保存的那份出
    txt, _ = X.review_prompt(p, t, log)
    txt_now, _ = X.review_prompt(p, t, None)
    P.THRESHOLD = old
    check("复盘题用事前保存的那份", "没有事前保存" not in txt and txt.count("观察") < txt_now.count("观察"))

# 8. 微信、邮件、PDF、纯文字一致；日期跟着发送日期变
for i in range(0, 400, 20):
    tgt = day(2025, 11, 1) + datetime.timedelta(days=i)
    d = compose.build(p, tgt, tgt - datetime.timedelta(days=1))
    a = D.analyse(p, tgt)
    w, e, f, t_ = layout.wechat_text(d), layout.email_html(d), layout.pdf_html(d), layout.text(d)
    for x in d["predict"]["predictions"]:
        check(f"{tgt} 观察在四个版本都有", x["name"] in w and x["id"] in e and x["id"] in f and x["id"] in t_)
    if not d["predict"]["predictions"]:
        check(f"{tgt} 零观察四个版本都说明", "没有观察项" in w and "没有观察项" in e and "没有观察项" in f and "没有观察项" in t_)
    check(f"{tgt} 星级一致", d["stars"] == a["stars"] and "★" * a["stars"] + "☆" * (5 - a["stars"]) in w)
    check(f"{tgt} 明日/今日", "明日观察" in w)
    check(f"{tgt} 微信长度", 250 <= len(w) <= 900, len(w))
    check(f"{tgt} 编号连续", "@@NUM@@" not in e and ">01<" in e)
d = compose.build(p, day(2026, 10, 28), day(2026, 10, 28))
check("早上补发写今日观察", "今日观察" in layout.wechat_text(d))
check("没填个人配置时不显示近期关注", "近期关注" not in layout.email_html(d) and "我关心的事" not in layout.email_html(d))
d = compose.build(p, day(2026, 10, 28), day(2026, 10, 27), {"concerns": [{"text": "测试事项"}]})
check("填了才显示近期关注", "近期关注" in layout.email_html(d))

# 9. 措辞：不再出现绝对化说法和把意象当事实
allt = "".join(layout.text(compose.build(p, day(2026, 10, 20) + datetime.timedelta(days=i), day(2026, 10, 19)))
               for i in range(0, 60, 3))
for bad in ("只守不攻", "签约先放一放", "排到下个月", "体力足", "孩子", "工作环境", "穴"):
    check(f"措辞：不含「{bad}」", bad not in allt)

# 10. 规则版本：v1 的记录不变，v2 从 10/29 起收紧「明确沟通摩擦」
check("10/28 仍按 v1，指纹和已保存的一样", P.version_for(day(2026, 10, 28)) == "v1"
      and P.build(p, day(2026, 10, 28))["fingerprint"] == "a42dacf4ac7a")
check("10/29 起用 v2", P.version_for(day(2026, 10, 29)) == "v2" and P.build(p, day(2026, 11, 3))["rule_version"] == "v2")
fr = P.events_for("v2")["friction"]
check("v2 摩擦：礼貌拒绝和一般意见不同不算", "礼貌的拒绝" in fr["exclude"] and "意见不同" in fr["exclude"]
      and "不愉快" not in fr["occur"] and "被当面拒绝" not in fr["occur"])
check("v1 原文保留", "被当面拒绝" in P.events_for("v1")["friction"]["occur"])
txt29, _ = X.review_prompt(p, day(2026, 10, 29))
txt28, _ = X.review_prompt(p, day(2026, 10, 28))
check("复盘题按当天的版本出", "礼貌的拒绝" in txt29 and "礼貌的拒绝" not in txt28)

# 11. 微信可读性：每个元素底色字色成对、字号行距、算/不算分行；文字和原来一样；实际发送函数用的就是它
import contextlib, html as H, io, re
import notify
def wx_text(h):
    return H.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<style>.*?</style>", "", h, flags=re.S)))
for i in range(0, 400, 20):
    tgt = day(2025, 11, 1) + datetime.timedelta(days=i)
    d = compose.build(p, tgt, tgt - datetime.timedelta(days=1))
    h = layout.wechat_html(d)
    n = d["stars"]   # 标题拆成日期干支一行、星级一行，星级行加「n / 5 星 · 等级」，其余逐字照旧
    head = f"【{layout.md(tgt)} 周{d['wd']} · {d['day_gz']}日】" + layout.stars(n) + f"{n} / 5 星 · {d['level']}"
    old = "".join(head if v is None else v if k is None else f"【{k}】{v}" for k, v in layout.wechat_lines(d))
    new = wx_text(h)
    check(f"{tgt} 微信文字和原来一致（算/不算只是分行）", new == old, (new, old))
    tags = re.findall(r"<(p|div|span)\b([^>]*)>", h)
    check(f"{tgt} 每个元素底色字色成对", all("background-color:" in a and ";color:" in a for _, a in tags))
    check(f"{tgt} 不设透明度、不用透明底", "opacity" not in h and "transparent" not in h)
    sizes = [int(x) for x in re.findall(r"font-size:(\d+)px", h)]
    check(f"{tgt} 正文 18px、最小 16px", 18 in sizes and min(sizes) >= 16, sizes)
    check(f"{tgt} 行距 1.75-1.9", "line-height:1.8" in h)
    check(f"{tgt} 星级单独一行、实心空心分开上色", f'class="mp-on" style="background-color:#ffffff;color:{layout.WX_STAR_ON[0]};' in h
          and (n == 5 or f'class="mp-off" style="background-color:#ffffff;color:{layout.WX_STAR_OFF[0]};' in h)
          and "white-space:nowrap" in h and "font-size:26px" in h)
    check(f"{tgt} 深色模式成对换色", "prefers-color-scheme: dark" in h and "background-color:#1c1c1e!important;color:#ececec!important" in h)
    for x in d["predict"]["predictions"]:
        check(f"{tgt} 算/不算分行", re.search(r">算：[^<]*；</p><p[^>]*>不算：", h) is not None)
sent = {}
real = notify.send_wechat, notify.send_mail
notify.send_wechat = lambda t, c, tpl="txt": sent.setdefault("wx", []).append((t, c, tpl)) or "微信已推送"
notify.send_mail = lambda *a: sent.setdefault("mail", []).append(a) or "邮件已发送"
try:
    for argv in (["--date", "2026-10-30", "--send-date", "2026-10-29"], ["--date", "2026-10-30", "--wechat-test"]):
        sys.argv = ["daily.py", *argv]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            D.main()
        sent.setdefault("log", []).append(buf.getvalue())
finally:
    notify.send_wechat, notify.send_mail = real
d30 = compose.build(p, day(2026, 10, 30), day(2026, 10, 29))
check("正式发送用新样式", sent["wx"][0][1] == layout.wechat_html(d30) and sent["wx"][0][2] == "html")
check("测试只发微信、不发邮件", len(sent["wx"]) == 2 and len(sent["mail"]) == 1)
check("测试标题和横幅标「可读性测试」", sent["wx"][1][0].startswith("【可读性测试】") and "可读性测试：10/30" in sent["wx"][1][1])
check("测试样稿按前一晚重算，内容和正式一致", wx_text(sent["wx"][1][1]).endswith(wx_text(layout.wechat_html(d30))))
check("10/30 指纹不变", d30["predict"]["fingerprint"] == "4d5b377d2051" and "4d5b377d2051" in sent["log"][1])
check("测试日志行不会被当成正式发送", X.LOG_RE.search(sent["log"][1]) is None and X.LOG_RE.search(sent["log"][0]) is not None)

print(f"全部通过，共 {len(ok)} 项检查")
