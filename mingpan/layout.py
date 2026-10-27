#!/usr/bin/env python3
"""
命盘日报的三种版面，都从 compose.build 得到的同一份数据渲染：
  wechat_html / wechat_text  微信摘要（PushPlus html 模板，约 350-600 字，不用宽表格）
  email_html                 邮件完整版（样式写在行内，兼容邮件客户端，手机上单栏阅读）
  pdf_html                   PDF 版（同一套栏目，分四页：前两页日用，后两页依据；本地用 Chromium 转 PDF）
  text                       纯文字版，--dry-run 打印用
栏目顺序按 2026-10-26 个人日报融合样稿：速览 → 事业财运感情 → 近期关注（没填就不显示）→ 预测实验 → 生活补充
→ 未来七天 → 晚间回顾
→ 运年月背景 → 流日计分 → 五行 → 神煞调候 → 时辰方位 → 节气和下月。
"""
import datetime
import html
import re

WX_COLOR = {"木": "#3a8f5c", "火": "#d9534f", "土": "#b8862b", "金": "#9a8a5a", "水": "#2f6db5"}
STAR_COLOR = {1: "#c0392b", 2: "#e67e22", 3: "#7f8c8d", 4: "#27ae60", 5: "#1e8449"}
ACCENT = "#2e6b55"
DISCLAIMER = "传统文化参考，不是预言，也不构成任何投资建议。现实的事以事实、期限和自己的判断为准。"


def esc(s):
    return html.escape(str(s))


def stars(n):
    return "★" * n + "☆" * (5 - n)


def md(d):
    return f"{d.month}/{d.day}"


def head_line(d):
    return f"{md(d['target'])} 周{d['wd']} · {d['year_gz']}年 {d['month_gz']}月 {d['day_gz']}日"


# ---------- 公用小块 ----------

def h2(num, title, sub=""):   # num 不用了，编号由 _number 按顺序补
    return (f'<div style="margin:16px 0 6px;font-size:17px;font-weight:bold;color:#222">'
            f'<span style="color:{ACCENT};margin-right:8px">@@NUM@@</span>{esc(title)}'
            + (f'<span style="font-size:12px;font-weight:normal;color:#888;margin-left:8px">{esc(sub)}</span>' if sub else "")
            + '</div>')


def box(inner, border="#e3e8e5", bg="#fff"):
    return (f'<div style="border:1px solid {border};border-radius:10px;background:{bg};'
            f'padding:12px 14px;margin:0 0 10px">{inner}</div>')


def label_row(label, text, color="#555"):
    return (f'<div style="margin:5px 0;font-size:14px;line-height:1.65;color:#222">'
            f'<b style="color:{color}">{esc(label)}</b>　{esc(text)}</div>')


def note(text):
    return f'<div style="font-size:12px;color:#888;line-height:1.6;margin:4px 0 0">{esc(text)}</div>'


def table(head, rows, widths=None, small=False):
    fs = "12px" if small else "13px"
    th = "".join(f'<th style="text-align:left;padding:6px 6px;font-weight:bold;color:#555;background:#eef3f0;'
                 f'font-size:{fs}{";width:" + widths[i] if widths and widths[i] else ""}">{esc(h)}</th>'
                 for i, h in enumerate(head))
    tr = "".join("<tr>" + "".join(f'<td style="padding:6px 6px;border-bottom:1px solid #eee;font-size:{fs};'
                                  f'line-height:1.5;vertical-align:top">{c}</td>' for c in r) + "</tr>" for r in rows)
    return f'<table style="width:100%;border-collapse:collapse;margin:0 0 6px">{"<tr>" + th + "</tr>"}{tr}</table>'


# ---------- 各栏目 ----------

def s_overview(d):
    t = d["theme"]
    c = STAR_COLOR[d["stars"]]
    tip = (f'<div style="font-size:12px;color:#666;margin-top:10px;padding-top:8px;border-top:1px dashed #cfd9d4">'
           f'个人设置 · 长期提醒：{esc(d["tip"])}</div>') if d["tip"] else ""
    return box(
        f'<div style="font-size:13px;color:#666">{esc(head_line(d))}　{esc(d["lunar_text"])}</div>'
        f'<div style="font-size:24px;color:{c};margin:6px 0 2px;letter-spacing:2px">{stars(d["stars"])}'
        f'<span style="font-size:16px;letter-spacing:0;margin-left:8px">{d["stars"]}/5 · {esc(d["level"])}</span>'
        f'<span style="font-size:12px;color:#888;letter-spacing:0;margin-left:8px">和你自己一年里的日子比</span></div>'
        f'<div style="font-size:16px;font-weight:bold;margin:8px 0 4px">今日主线：{esc(t["name"])}，{esc(t["line"])}。</div>'
        f'<div style="font-size:14px;line-height:1.65;color:#333">{esc(t["explain"])}</div>'
        f'<div style="font-size:14px;line-height:1.65;margin-top:8px"><b style="color:{ACCENT}">今日行动</b>　{esc(t["action"])}。</div>'
        + tip, border="#cfe0d7", bg="#f4f8f6")


def s_cols(d):
    out = [h2("", "事业 · 财运 · 感情", "先看解读，再落到行动")]
    for key, letter, title in (("事业", "A", "事业与工作"), ("财运", "B", "财运与财务"), ("感情", "C", "感情与关系")):
        x = d["cols"][key]
        out.append(box(
            f'<div style="font-size:15px;font-weight:bold"><span style="color:{ACCENT};margin-right:6px">{letter}</span>{title}</div>'
            f'<div style="font-size:14px;font-weight:bold;color:#333;margin:6px 0 4px">{esc(x["theme"])}</div>'
            + label_row("命理解读", x["basis"]) + label_row("现实行动", x["action"], ACCENT) + label_row("留意", x["note"])))
    out.append(note("「命理解读」引用的是当天实际计分的项目和神煞（括号里是分值）；「现实行动」是编辑整理的建议，不是推算结果。计分明细见后面。"))
    return "".join(out)


def s_concerns(d):
    if not d["concerns"]:
        return ""
    rows = []
    for c in d["concerns"]:
        due = (f"（期限 {c['due']}，还有 {c['left']} 天）" if c["left"] is not None and c["left"] >= 0 else
               f"（期限 {c['due']}，已过）" if c["due"] else "")
        rows.append(label_row("当前事项", c["text"] + due) + label_row("今天的一步", c["step"], ACCENT))
    return h2("", "近期关注", "来自个人配置，不由命盘推出") + box("".join(rows))


def s_predict(d):
    r, w = d["predict"], d["obs_word"]
    out = [h2("", "预测实验（待验证）", f"规则 {r['rule_version']} · 不参与评分 · 事后对照用")]
    if not r["predictions"]:
        out.append(box(label_row(w, "这一天没有观察项。" + r["none_reason"])))
    for x in r["predictions"]:
        ev = "".join(f'<div style="font-size:13px;line-height:1.6;color:#333;margin:2px 0">'
                     f'{"依据" if s["weight"] > 0 else "相反依据"}（权重 {s["weight"]:+.1f}）：{esc(s["basis"])}'
                     f'<span style="color:#888">｜{esc(s["source"])}</span></div>' for s in x["evidence"])
        out.append(box(
            f'<div style="font-size:15px;font-weight:bold"><span style="color:{ACCENT};margin-right:6px">{w}{x["n"]}</span>'
            f'{esc(x["name"])}<span style="font-size:12px;font-weight:normal;color:#888;margin-left:8px">'
            f'预期发生 · 净强度 {x["net"]:.1f} · {esc(x["id"])}</span></div>'
            + label_row("算发生", x["occur"], ACCENT) + label_row("不算", x["exclude"]) + ev))
    if r["unselected"]:
        out.append(note("没入选的候选：" + "；".join(f"{u['event']}（{u['reason']}）" for u in r["unselected"]) + "。"))
    out.append(note(f"入选条件事先写死：净强度 ≥{r['threshold']} 且至少一条主依据（权重 1），最多两条，不够不凑。"
                    "命理含义出自所注书目，「对应哪类事件」是本项目自己的定义，没有验证过；不预测投资、疾病、灾祸和别人的心意。"))
    return "".join(out)


def s_life(d):
    return h2("", "生活补充", "家人、学习、身心") + box("".join(label_row(k, v) for k, v in d["life"])) + note(
        "身心只做休息、活动和自我观察的提醒，不按五行推断症状，不代替看医生。")


def s_week(d):
    rows = [[f"<b>{md(w['date'])}</b> 周{w['wd']}", esc(w["gz"]),
             f'<span style="color:{STAR_COLOR[w["stars"]]}">{w["stars"]}★</span>', esc(w["struct"]), esc(w["hint"])]
            for w in d["week"]]
    return (h2("", "未来七天", "干支、星级、结构都是程序算的") +
            table(["日期", "干支", "星级", "结构", "行动提示"], rows, ["21%", "11%", "10%", "38%", "20%"], small=True)
            + note("行动提示是编辑整理的，不是新的推算；星级是和自己平常日子比的相对评价，不能代替事实和期限的判断。"))


def s_review(d):
    r = d["review_date"]
    return (h2("", "晚间回顾", f"复盘问的是 {md(r)} 当天") + box(
        label_row("怎么答", f"{md(r)} 晚上 21:37 在对话里发复盘题，四段用斜杠隔开，一两分钟："
                            "老题字母 / 当天实际发生了哪几类（数字）/ 每条观察一个字母 / 日报的影响两个字母，最后可接一句事实。"
                            "只答第一段也照收。")
        + label_row("先记事实", "第二段先照实勾当天发生了什么，再对观察；因为提前注意而没发生的算「没发生」，"
                              "看了日报主动去问而得到的算「受阅读影响」。")))


def s_background(d):
    rows = []
    for x in d["bases"]:
        layer = x["term"].split("：")[0] if "：" in x["term"] else x["term"].split("，")[0]
        rows.append([f"<b>{esc(layer)}</b>", esc(x["term"].split("：", 1)[1] if "：" in x["term"] else x["term"])
                     + "<br>" + f'<span style="color:#666">{esc(x["plain"])}</span>'])
    return h2("", "运、年、月的背景", "底色，不计分") + table(["层次", "解释"], rows, ["24%", "76%"])


def brief(plain, n=34):
    """计分表里的解释摘要：白话第一句，去掉帮/耗的尾巴，太长截断（全文在事业财运感情和纯文字版里）。"""
    s = re.sub(r"，这股力量(帮|耗)你", "", plain.split("。")[0])
    return s if len(s) <= n else s[:n] + "…"


def s_score(d):
    rows = [[f"{i:02d}", esc(x["term"]),
             f'<b style="color:{"#1e8449" if x["pts"] > 0 else "#c0392b" if x["pts"] < 0 else "#888"}">{x["pts"]:+.1f}</b>',
             esc(brief(x["plain"]))]
            for i, x in enumerate(d["items"], 1)]
    sha = [x for x in d["sha"] if x["pts"]]
    tot = box(
        f'<div style="font-size:14px;line-height:1.8"><b>命盘层：</b>助力 {d["gain"]:+.1f}，消耗 {d["loss"]:+.1f}，'
        f'小计 {d["subtotal"]:+.1f}<br><b>神煞调整：</b>'
        + ("、".join(f"{esc(x['name'])} {x['pts']:+.1f}" for x in sha) or "无") + f'（合计 {d["sha_adj"]:+.1f}）<br>'
        f'<b>最终评分 {d["score"]:+.1f}，对应 {d["stars"]} 星（{esc(d["level"])}）</b>；黄道黑道不计分。</div>',
        border="#cfe0d7", bg="#f4f8f6")
    return (h2("", "流日计分明细", f"{d['day_gz']}日 · {d['dm']}{d['dm_wx']}日主")
            + table(["#", "计分项", "分值", "解释摘要"], rows, ["6%", "38%", "10%", "46%"], small=True) + tot)


def s_wuxing(d):
    view = d["wuxing"]
    top = max(3.0, max(i["w"] for k in view for i in view[k]))
    rows = []
    for kind in ("喜", "忌"):
        for i in view[kind]:
            pct = round(i["w"] / top * 100)
            rows.append(
                f'<tr><td style="width:22px;font-size:14px;color:{WX_COLOR[i["wx"]]};font-weight:bold">{i["wx"]}</td>'
                f'<td style="width:110px;font-size:12px;color:#666">{esc(i["group"])} · {"喜用" if kind == "喜" else "忌神"}</td>'
                f'<td><div style="background:#f0f0f0;border-radius:4px;height:10px">'
                f'<div style="background:{WX_COLOR[i["wx"]]};width:{pct}%;height:10px;border-radius:4px"></div></div></td>'
                f'<td style="width:34px;text-align:right;font-size:12px;color:#555">{i["w"]:.1f}</td></tr>')
            if i.get("use"):
                rows.append(f'<tr><td></td><td colspan="3" style="font-size:12px;color:#444;line-height:1.5;padding:0 0 6px">'
                            f'用好它：{esc(i["use"])}。化解：{esc(i["fix"])}。</td></tr>')
    return (h2("", "流日五行分量", "天干、地支本气各 1，藏干 0.3，成局另加")
            + f'<table style="width:100%;border-collapse:separate;border-spacing:0 4px">{"".join(rows)}</table>'
            + note("这是今天带来的五行有多少，零就是没来；它和上面的总评分不是一回事，总分还要看冲合刑害、长生和结构。"))


def s_sha(d):
    kinds = {"吉": "吉神", "中": "中性", "凶": "凶煞"}
    rows = []
    for x in sorted(d["sha"], key=lambda x: "吉中凶".index(x["kind"])):
        w = f"计分 {x['pts']:+.2g}" if x["pts"] else "不计分，只作参考"
        rows.append(label_row(f"{kinds[x['kind']]} · {x['name']}（{w}{'，' + x['hint'] if x['hint'] else ''}）",
                              f"{x['note']}。用法：{x['use']}。"))
    hl = label_row("黄历（择日，不计分）", d["huangli"] + "。")
    return (h2("", "神煞与调候", f"以喜忌为主，神煞为辅；今天地支是你的{d['zxj']}")
            + box("".join(rows) + hl if rows else hl))


def s_hours(d):
    h = d["hours"]
    rows = []
    if not any(x["level"] == "好" for x in h["good"]):
        rows.append(["—", "说明", "07:00 到 23:00 之间没有真正的好时辰，下面标「平」的只是白天相对稳的"])
    rows += [[esc(x["name"]), x["level"], esc(f"{x['todo']}（{x['why']}）")] for x in h["good"]]
    rows += [[esc(x["name"]), "留意", esc(f"{x['warn']}（{x['why']}）")] for x in h["bad"]]
    if h["night"]:
        rows.append([esc("、".join(h["night"])), "夜里较好", "在睡觉的时段，只照实列出，不建议为此熬夜或早起"])
    dr = d["dirs"]
    dirs = (f"当天办事看阳贵：{dr['gui']}" + ("，正好落在你的喜用方位上" if dr["match"] else "") +
            f"；长期布置看喜用方位：{'、'.join(dr['own'])}。以你当时所在的地方为中心，看真实方向，只作文化参考；"
            "约谁、时间地点仍按期限、方便和对方安排。")
    return (h2("", "时辰与方位", "按目标日期当天的当地钟点")
            + table(["时辰", "分类", "内容"], rows, ["30%", "14%", "56%"], small=True)
            + label_row("方位", dirs)
            + note("时辰按钟点直接取，程序没有按经纬度或时区换算真太阳时；人在哪里就按当地钟点看。"))


def s_month(d):
    mo, cal = d["mo"], d["cal"]
    cur, new = mo["cur"], mo["new"]
    jn, jd, left = d["next_jq"]
    end_cur = mo["date"] - datetime.timedelta(days=1)
    end_new = mo["end"] - datetime.timedelta(days=1)
    cells = ['<td></td>'] * cal["days"][0][0].weekday()
    for x, s in cal["days"]:
        border = "2px solid #222" if x == d["target"] else "2px solid transparent"
        cells.append(f'<td style="text-align:center;padding:0"><div style="background:{STAR_COLOR[s]};color:#fff;'
                     f'border:{border};border-radius:4px;font-size:11px;line-height:16px">{x.day}</div></td>')
    cells += ['<td></td>'] * (-len(cells) % 7)
    grid = "".join("<tr>" + "".join(cells[i:i + 7]) + "</tr>" for i in range(0, len(cells), 7))
    wk = "".join(f'<td style="text-align:center;font-size:11px;color:#888">{w}</td>' for w in "一二三四五六日")
    left_good = "、".join(md(x) for x in cal["left_good"]) or "无"
    return (h2("", "节气和下个月", "节气月和公历月分开算")
            + box(
                label_row("下一个节气", f"{jn} {md(jd)}" + ("（就是今天）" if left == 0 else f"（还有 {left} 天）"))
                + label_row(f"这个节气月 {cur['gz']}",
                            f"{mo['prev_jie']} {md(mo['start'])} 到 {md(end_cur)}：你的{d['dm_wx']}处在「{cur['state']}」，"
                            f"平均分 {cur['mean']:+.1f}（一年平均 {mo['base']:+.1f}，{cur['vs']}），"
                            f"好日子（4★以上）{cur['good']} 天，差日子（2★以下）{cur['bad']} 天，一星日 {cur['worst']} 天。")
                + label_row(f"下个节气月 {new['gz']}",
                            f"{mo['jie']} {md(mo['date'])} 到 {md(end_new)}：{'；'.join(mo['why'])}。平均分 {new['mean']:+.1f}"
                            f"（{new['vs']}），好日子 {new['good']} 天，差日子 {new['bad']} 天，一星日 {new['worst']} 天。")
                + label_row("结论", f"{mo['verdict']}。{mo['advice']}。", ACCENT)
                + label_row(f"公历 {d['target'].month} 月",
                            f"{md(cal['first'])} 到 {md(cal['last'])} 共 {len(cal['days'])} 天：好日子 {cal['good']} 天，"
                            f"{md(d['target'])} 排第 {cal['rank']}；之后的好日子：{left_good}。"))
            + '<table style="width:100%;max-width:320px;border-collapse:separate;border-spacing:2px;table-layout:fixed">'
            + f"<tr>{wk}</tr>{grid}</table>"
            + note("节气月从交节那天算起，和公历月起止不同，所以好日子天数不一样。" + DISCLAIMER))


# ---------- 整页 ----------

PAGES = [  # PDF 分页：前两页日用，后两页依据
    ("今天怎么用", ["s_overview", "s_cols"]),
    ("把命理提示接上日常", ["s_concerns", "s_predict", "s_life", "s_week", "s_review"]),
    ("命盘底色与计分", ["s_background", "s_score", "s_wuxing"]),
    ("神煞、时辰与月度", ["s_sha", "s_hours", "s_month"]),
]


def _sections(d, names):
    return "".join(globals()[n](d) for n in names)


def _number(page):
    """按实际出现的顺序给栏目编号（01、02…），没显示的栏目不占号。"""
    n = iter(range(1, 100))
    return re.sub("@@NUM@@", lambda m: f"{next(n):02d}", page)


def email_html(d):
    body = _number("".join(_sections(d, names) for _, names in PAGES))
    sent = (f"{md(d['send_date'])} 晚上发出，说的是 {md(d['target'])} 这一天" if d["send_date"] < d["target"]
            else f"说的是 {md(d['target'])} 这一天")
    return ('<div style="font-family:-apple-system,BlinkMacSystemFont,\'PingFang SC\',\'Microsoft YaHei\',sans-serif;'
            'max-width:600px;margin:0 auto;padding:6px;color:#222;background:#fafafa">'
            f'<div style="font-size:12px;color:#888;margin:0 0 6px">个人命盘日报 · {esc(sent)}</div>'
            f'{body}</div>')


def pdf_html(d):
    pages = []
    for i, (title, names) in enumerate(PAGES):
        pages.append(
            f'<section style="{"page-break-before:always;" if i else ""}">'
            f'<div style="display:flex;justify-content:space-between;font-size:12px;color:{ACCENT};'
            f'border-bottom:1px solid #cfe0d7;padding-bottom:4px;margin-bottom:10px"><b>个人命盘日报</b>'
            f'<span>{d["target"].isoformat()} · 周{d["wd"]} · {esc(d["day_gz"])}日</span></div>'
            f'<div style="font-size:22px;font-weight:bold;margin:4px 0 2px">{esc(title)}</div>'
            f'{_sections(d, names)}</section>')
    return ('<!doctype html><html><head><meta charset="utf-8"><style>'
            '@page{size:A4;margin:14mm 13mm 16mm}body{font-family:"Noto Sans CJK SC","WenQuanYi Zen Hei",'
            '"PingFang SC","Microsoft YaHei",sans-serif;color:#222;margin:0}section{zoom:0.86}'
            'table,tr,.box{page-break-inside:avoid}</style></head><body>'
            + _number("".join(pages)) + FIT_JS + '</body></html>')


# 每页内容太长时把这一页整体缩小一点，保证四页（页面宽度按 A4 版心 695px 排版，高度上限约 990px）
FIT_JS = ('<script>for(const s of document.querySelectorAll("section")){let z=0.86;'
          'while(s.getBoundingClientRect().height>990&&z>0.6){z-=0.02;s.style.zoom=z;}}</script>')


def wechat_lines(d):
    t, c = d["theme"], d["cols"]
    step = (f"{d['concerns'][0]['text']}：{d['concerns'][0]['step']}" if d["concerns"] else t["action"] + "。")
    r = d["review_date"]
    return [
        (f"{md(d['target'])} 周{d['wd']} · {d['day_gz']}日 · {stars(d['stars'])} {d['level']}", None),
        ("今日主线", f"{t['name']}：{t['line']}。{t['explain']}"),
        ("事业", f"{c['事业']['theme']}行动：{c['事业']['action']}"),
        ("财运", f"{c['财运']['theme']}要做：{c['财运']['action']}"),
        ("感情", f"{c['感情']['theme']}{c['感情']['action']}"),
        (f"{d['step_word']}的一步", step),
    ] + obs_lines(d) + [
        ("回顾提示", f"今晚复盘问的是 {md(r)} 当天，题目在对话里发，四段斜杠隔开，一两分钟。"),
        (None, "完整依据、计分和七天预览见邮件。传统文化参考，不是预言。"),
    ]


def obs_lines(d):
    r, w = d["predict"], d["obs_word"]
    if not r["predictions"]:
        return [(w, "没有观察项：没有依据达到入选条件，不硬凑（待验证的实验）。")]
    return [(f"{w}{x['n']}", f"{x['name']}。算：{x['occur']}；不算：{x['exclude']}（待验证）")
            for x in r["predictions"]]


def wechat_html(d):
    out = []
    for k, v in wechat_lines(d):
        if v is None:
            out.append(f'<p style="font-size:16px;font-weight:bold;color:{STAR_COLOR[d["stars"]]};margin:0 0 8px">【{esc(k)}】</p>')
        elif k is None:
            out.append(f'<p style="font-size:12px;color:#888;margin:10px 0 0">{esc(v)}</p>')
        else:
            out.append(f'<p style="font-size:15px;line-height:1.7;margin:0 0 8px"><b>【{esc(k)}】</b>{esc(v)}</p>')
    return '<div style="font-family:sans-serif;color:#222">' + "".join(out) + "</div>"


def wechat_text(d):
    return "\n".join(f"【{k}】" if v is None else v if k is None else f"【{k}】{v}" for k, v in wechat_lines(d))


def text(d):
    """纯文字版：--dry-run 打印、定时任务读取用。栏目和数值与邮件一致。"""
    t, c, h, mo, cal = d["theme"], d["cols"], d["hours"], d["mo"], d["cal"]
    L = [f"{head_line(d)} · {d['lunar_text']}" + (f" · 大运{d['dayun']}" if d["dayun"] else ""),
         f"{stars(d['stars'])} {d['stars']}/5 {d['level']}　评分 {d['score']:+.1f}"
         f"（命盘小计 {d['subtotal']:+.1f}，神煞 {d['sha_adj']:+.1f}）",
         f"今日主线：{t['name']}，{t['line']}。{t['explain']}", f"今日行动：{t['action']}。"]
    if d["tip"]:
        L.append(f"个人设置 · 长期提醒：{d['tip']}")
    for k in ("事业", "财运", "感情"):
        x = c[k]
        L += ["", f"## {k}：{x['theme']}", f"- 命理解读：{x['basis']}", f"- 现实行动：{x['action']}", f"- 留意：{x['note']}"]
    if d["concerns"]:
        L += ["", "## 近期关注"] + [f"- {x['text']}" + (f"（期限 {x['due']}）" if x["due"] else "") + f"：{x['step']}"
                                 for x in d["concerns"]]
    L += ["", f"## {d['obs_word']}（预测实验，待验证）", d["predict"]["text"]]
    L += ["", "## 生活补充"] + [f"- {k}：{v}" for k, v in d["life"]]
    L += ["", "## 未来七天"] + [f"- {md(w['date'])} 周{w['wd']} {w['gz']} {stars(w['stars'])} {w['struct']}　提示：{w['hint']}"
                               for w in d["week"]]
    L += ["", f"## 晚间回顾：{md(d['review_date'])} 晚上 21:37 发当天复盘题"]
    L += ["", "## 运、年、月的背景"] + [f"- {x['term']}。{x['plain']}" for x in d["bases"]]
    L += ["", "## 流日计分"] + [f"- {x['pts']:+.1f} {x['term']}" for x in d["items"]]
    L += [f"- 助力 {d['gain']:+.1f}，消耗 {d['loss']:+.1f}，小计 {d['subtotal']:+.1f}；神煞 {d['sha_adj']:+.1f}；"
          f"最终 {d['score']:+.1f}，{d['stars']} 星"]
    L += ["", "## 五行分量"] + [f"- {i['wx']}（{i['group']}，{k}）{i['w']:.1f}" for k in ("喜", "忌") for i in d["wuxing"][k]]
    L += ["", "## 神煞与调候"] + [f"- {x['name']}（{'计分 %+.2g' % x['pts'] if x['pts'] else '不计分'}）：{x['note']}。用法：{x['use']}。"
                                for x in d["sha"]] + [f"- 黄历（不计分）：{d['huangli']}"]
    L += ["", "## 时辰与方位（当地钟点）"]
    if not any(x["level"] == "好" for x in h["good"]):
        L.append("- 07:00 到 23:00 之间没有真正的好时辰，标「平」的只是相对稳的")
    L += [f"- 【{x['level']}】{x['name']}：{x['todo']}（{x['why']}）" for x in h["good"]]
    L += [f"- 【留意】{x['name']}：{x['warn']}（{x['why']}）" for x in h["bad"]]
    if h["night"]:
        L.append(f"- 夜里较好：{'、'.join(h['night'])}（只照实列出，不建议熬夜）")
    L.append(f"- 阳贵：{d['dirs']['gui']}；喜用方位：{'、'.join(d['dirs']['own'])}")
    jn, jd, left = d["next_jq"]
    L += ["", "## 节气和下个月",
          f"- 下一个节气：{jn} {md(jd)}（还有 {left} 天）",
          f"- 节气月 {mo['cur']['gz']}（{md(mo['start'])} 起）：平均 {mo['cur']['mean']:+.1f}，好日子 {mo['cur']['good']} 天",
          f"- 节气月 {mo['new']['gz']}（{md(mo['date'])} 起）：平均 {mo['new']['mean']:+.1f}，好日子 {mo['new']['good']} 天",
          f"- 结论：{mo['verdict']}。{mo['advice']}。",
          f"- 公历 {d['target'].month} 月（{md(cal['first'])}–{md(cal['last'])}）：好日子 {cal['good']} 天，"
          f"{md(d['target'])} 排第 {cal['rank']}",
          "", DISCLAIMER]
    return "\n".join(L)
