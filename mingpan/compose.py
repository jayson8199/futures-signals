#!/usr/bin/env python3
"""
把 daily.py 的计算结果整理成一份结构化日报（一份数据，微信摘要、邮件正文、PDF 三种版面共用）。

这里只组织文字，不重算分数：星级、分数、各项计分、五行分量、时辰、节气月统计都直接取自
daily.analyse / hours / month_outlook / wuxing_view。事业、财运、感情三栏引用的是当天实际出现的计分项和神煞，
「现实行动」是按十神主题整理的编辑建议，版面上会标明。

日期有三个，分开记：
  target       日报说的是哪一天（干支、星级、建议都按这一天）
  send_date    什么时候发出（前一晚发时比 target 早一天）
  review_date  晚上复盘问的是哪一天，等于 send_date，不随日报往后挪

个人配置（可选，放在 Secret MINGPAN_PERSONAL 的 JSON 里，不进公开仓库；没有就照常生成）：
  {"job": "做什么工作，一句话", "relationship": "有伴 / 单身 / 不填",
   "concerns": [{"text": "关心的事", "due": "2026-11-15"}]}   最多 3 项，due 可省略
"""
import datetime
import re

import daily as D

WEEK = "一二三四五六日"
TEN2GROUP = {"比肩": "比劫", "劫财": "比劫", "偏印": "印", "正印": "印", "食神": "食伤", "伤官": "食伤",
             "偏财": "财", "正财": "财", "七杀": "官杀", "正官": "官杀"}
CAREER_GROUPS = {"官杀", "印", "食伤", "比劫"}
CAREER_STRUCTS = {"杀印相生", "食神制杀", "伤官佩印"}
MONEY_STRUCTS = {"财生杀", "贪财坏印", "比劫帮身担财"}

# 今日行动：一个具体动作，按结构优先，没有结构按天干十神（编辑整理）
STRUCT_ACTION = {
    "杀印相生": "把一个正在卡住的问题写下来，确认下一步需要的信息，找一个人请教",
    "食神制杀": "挑一件最要紧的事做完交出去，做完一两件就停",
    "伤官佩印": "动手或开口之前，先查一份资料、想清楚要点",
    "比劫帮身担财": "把手上一件事分给信得过的人，分工和钱先说清楚",
    "财生杀": "列出近期要付的钱和到期日，不新增财务承诺",
    "贪财坏印": "把钱的事记在一张单子上集中核对，再留出一整块时间想事",
}
GROUP_ACTION = {
    "比劫": "约一位同事或朋友，把一件事分好工",
    "印": "把一个卡住的问题写下来，找一个人请教",
    "食伤": "把一个想法写成一页方案或一段说明",
    "财": "核对一笔收支或一个付款节点",
    "官杀": "先把上面交代的一件事做完交掉",
}
# 七天表里的简短行动提示（编辑整理）
STRUCT_HINT = {"杀印相生": "带问题请教", "食神制杀": "把事做完", "伤官佩印": "先学再说", "比劫帮身担财": "确认分工",
               "财生杀": "不添承诺", "贪财坏印": "钱只核对"}
GROUP_HINT = {"比劫": "找人分工", "印": "写清问题", "食伤": "整理表达", "财": "核对条件", "官杀": "按规矩交差"}
# 我关心的事：今天怎么借主题推进一步
GROUP_STEP = {
    "比劫": "找一个能一起做的人，把分工写下来",
    "印": "写下卡住的一点，找人请教或查资料",
    "食伤": "把进展写成一段说明发给相关的人",
    "财": "核对和这件事有关的钱、成本和期限",
    "官杀": "按期限把最该交的那一步交掉",
}
CAREER_THEME = {
    "杀印相生": "借印化杀：先准备、求教，再推进。",
    "食神制杀": "靠本事顶压力：把事做出来，不硬拼。",
    "伤官佩印": "想法多时有印收着：先想清楚再出手。",
    "比劫": "同伴日：适合分工合作，不争功。",
    "印": "印日：适合准备、学习和请教，不急着拍板。",
    "食伤": "输出日：适合写方案、讲清楚，说话留余地。",
    "财": "实务日：处理具体事务，不接超出能力的活。",
    "官杀": "压力日：按规矩交差，不和上面硬顶。",
}
MONEY_THEME = {
    "财生杀": "钱的事容易变成压力：只守不攻，不添新承诺。",
    "贪财坏印": "财来坏印：钱的事集中核对，不让它占满心思。",
    "比劫帮身担财": "钱和事多，有人分担：分配先说清楚。",
}


def _groups(term):
    return {TEN2GROUP[g] for g in TEN2GROUP if g in term}


def _first(plain):
    """白话说明的第一句，用作简短解释。"""
    return plain.split("。")[0].rstrip("，")


def _cats(x, dm):
    """计分项归到事业 / 财运 / 感情哪一栏（按项目本身的十神和地支，不另加判断）。"""
    t, c = x["term"], set()
    gs = _groups(t)
    if t.startswith("十神结构"):
        nm = t.split("：")[1].split("（")[0]
        return {"事业"} if nm in CAREER_STRUCTS else {"财运"} if nm in MONEY_STRUCTS else set()
    if t.startswith(("天干", "地支")) or "合住" in t or "双边" in t:
        if "双边" in t:
            gs = _groups(x["plain"].split("牵走")[0])
        if "财" in gs:
            c.add("财运")
        if gs & CAREER_GROUPS:
            c.add("事业")
        return c
    on_day = re.search(r"原局[年月时、]*日[年月时、]*支", t) is not None
    if "相刑" in t:
        c.add("事业")
    if "冲" in t:
        c.add("事业")
        if on_day:
            c.add("感情")
    if "六合" in t:
        if on_day:
            c.add("感情")
        elif "月" in t:
            c.add("事业")
    if "相害" in t or "相破" in t:
        c.add("财运")
    if "局" in t and "六合" not in t:
        wx = re.search(r"([木火土金水])局", t)
        if wx:
            g = D.wx_group(dm, wx.group(1))
            c.add("财运" if g == "财" else "事业")
    return c


def _basis(items, limit=4):
    """一栏引用的计分项：十神结构排最前，其余按分值大小，最多 4 条。"""
    return sorted(items, key=lambda x: (not x["term"].startswith("十神结构"), -abs(x["pts"])))[:limit]


def build(p, target, send_date=None, personal=None):
    send_date = send_date or target
    personal = personal or {}
    pillars = D.natal_chart(p)
    dm, day_zhi = pillars[2][0], pillars[2][1]
    a = D.analyse(p, target)
    lunar = a["lunar"]

    scored = [x for x in a["points"] if x["pts"] is not None]
    bases = [x for x in a["points"] if x["pts"] is None]
    gain = sum(x["pts"] for x in scored if x["pts"] > 0)
    loss = sum(x["pts"] for x in scored if x["pts"] < 0)
    sha_adj = sum(x["pts"] for x in a["sha"])
    shas = {x["name"]: x for x in a["sha"]}

    # 今日主线：有十神结构先说结构，一句命理主题 + 一句通俗解释（取自 analyse 的 gist）
    head, _, rest = a["gist"].partition("：")
    struct = a["structs"][0] if a["structs"] else None
    theme = {"name": struct or f"{a['god']}日",
             "line": head,
             "explain": (rest + "。" if rest else "") + ("" if a["gist_agree"] else D.GIST[a["stars"]]),
             "action": STRUCT_ACTION.get(struct) or GROUP_ACTION[D.ten_god(dm, a["day_gz"][0])[1]]}

    group = D.ten_god(dm, a["day_gz"][0])[1]
    dom = {k: (text, why, more) for k, text, why, more in a["domains"]}
    by_cat = {"事业": [], "财运": [], "感情": []}
    for x in scored:
        for c in _cats(x, dm):
            by_cat[c].append(x)

    def basis_text(items, extra=""):
        if not items:
            return extra or "今天这方面没有计分项直接引动。"
        terms = "；".join(f"{x['term']}（{x['pts']:+.1f}）" for x in items)
        top = next((x for x in items if x["term"].startswith("十神结构")), items[0])
        return f"{terms}。{_first(top['plain'])}。" + extra

    # 事业
    ci = _basis(by_cat["事业"])
    cs = next((s for s in a["structs"] if s in CAREER_STRUCTS), None)
    job = (personal.get("job") or "").strip()
    w_text, w_why, w_more = dom["工作"]
    career = {"theme": CAREER_THEME[cs or group],
              "basis": basis_text(ci),
              "action": w_text + "。" + (f"放到你的工作（{job}）里，挑今天最卡的一件来做。" if job else ""),
              "note": "；".join(w_more + ["必要的工作和期限照常推进"]) + "。"}

    # 财运：整理核对和新增承诺分开说
    mi = _basis(by_cat["财运"])
    ms = next((s for s in a["structs"] if s in MONEY_STRUCTS), None)
    caution = bool(ms in ("财生杀", "贪财坏印") or any("合住" in x["term"] and "财" in _groups(x["term"]) for x in mi)
                   or any(("相害" in x["term"] or "相破" in x["term"]) for x in mi) or "劫煞" in shas)
    m_text, m_why, m_more = dom["钱财"]
    if ms:
        m_theme = MONEY_THEME[ms]
    elif any("合住" in x["term"] and "财" in _groups(x["term"]) for x in mi):
        m_theme = "财星被合：先理清账目和条件，守住承诺边界。"
    elif "财" in {group, D.ten_god(dm, D.CANG[a["day_gz"][1]][0])[1]}:
        m_theme = "财星透出：对钱敏感，守住已有的，不冒进。"
    elif mi:
        m_theme = "防暗耗：账目和口头约定落到纸面。"
    else:
        m_theme = "财务方面没有突出的引动，照常记账、核对。"
    money = {"theme": m_theme,
             "basis": basis_text(mi, "逢劫煞（不计分），提示看好财物。" if "劫煞" in shas else ""),
             "action": ("核对一项收支、回款或付款节点，把金额、责任、期限和待确认的条件列清楚。" if caution
                        else m_text + "。"),
             "note": ("整理和核对照常做；新增支出、借贷、担保和签约先放一放，必要的按实际条件判断。" if caution
                      else "；".join(m_more) + "。" if m_more else "已有的付款和期限照常处理。")}

    # 感情：只用原程序已有的依据（桃花、孤辰寡宿、日支的冲合刑）
    li = _basis(by_cat["感情"])
    rel = (personal.get("relationship") or "").strip()
    th = shas.get("桃花")
    gc = shas.get("孤辰寡宿")
    rel_basis = [f"{x['term']}（{x['pts']:+.1f}）" for x in li]
    if th:
        rel_basis.append(f"桃花（{th['note']}，不计分）")
    if gc:
        rel_basis.append(f"孤辰寡宿（{gc['note']}，不计分）")
    if th:
        l_theme = "桃花有互动的意象，相处更重分寸和确认。"
    elif any("冲" in x["term"] for x in li):
        l_theme = "日支被冲，和身边的人有分歧先缓一缓。"
    elif any("六合" in x["term"] and x["pts"] > 0 for x in li):
        l_theme = "日支逢合出喜用，适合和身边的人好好商量。"
    elif any("六合" in x["term"] for x in li):
        l_theme = "日支逢合但合出忌神，别人的请求先想清楚再答应。"
    elif gc:
        l_theme = "容易觉得孤单，主动联系身边的人。"
    else:
        l_theme = "关系方面今天没有突出依据，照常相处。"
    act = {"有伴": "找个时间，和对方说一件具体的需要或一句感谢。",
           "单身": "主动联系一位想见的人，约个时间见面或通话。"}.get(
        rel, "有沟通对象时，说清一个具体需求；暂时没有时，写下自己希望怎样被理解。")
    love = {"theme": l_theme,
            "basis": ("；".join(rel_basis) + "。" if rel_basis else "今天没有桃花、孤辰寡宿，日支也没有冲合刑。"),
            "action": act,
            "note": ((th["use"] + "。") if th else "") + "以对方实际说的为准，不猜心意。"
                    + ("" if rel else "（关系状态没填，这栏不假定单身或有伴。）")}

    # 我关心的事（个人配置，最多 3 项）
    step = GROUP_STEP[group]
    concerns = []
    for c in (personal.get("concerns") or [])[:3]:
        due = c.get("due")
        left = (datetime.date.fromisoformat(due) - target).days if due else None
        concerns.append({"text": c.get("text", ""), "due": due, "left": left,
                         "step": f"借今天「{theme['name']}」的主题：{step}。"})
    missing = [k for k, v in (("工作", job), ("关系状态", rel), ("关心的事", concerns)) if not v]

    # 生活补充：家人、学习、身心（身心只做休息和自我观察，不按五行推断症状、不开穴位）
    f_text, f_why, f_more = dom["家人"]
    s_text, s_why, s_more = dom["学习"]
    b_text, b_why, b_more = dom["身体"]
    risk, question = a["psych"]
    sci = D.PSYCH_SCI[a["god"]]
    moves, alt, _ = D.EXERCISE[a["body_wx"]]
    life = [("家人", f"{f_text}（{f_why}）" + "".join(f"；{m}" for m in f_more) + "。"),
            ("学习", f"{s_text}（{s_why}）" + "".join(f"；{m}" for m in s_more) + "。"),
            ("身心", f"{b_text}（{b_why}）" + "".join(f"；{m}" for m in b_more)
             + f"。按自己的疲劳感安排休息；想活动可以做几式八段锦（比如{moves}）或{alt}。"),
            ("心态", f"{a['god']}日{risk}。自检一问：{question}心理学叫「{sci[0]}」，可以试试：{sci[2]}。")]

    # 未来七天（含目标日）
    week = []
    for i in range(7):
        d = target + datetime.timedelta(days=i)
        b = a if i == 0 else D.analyse(p, d)
        g = D.ten_god(dm, b["day_gz"][0])[1]
        s0 = b["structs"][0] if b["structs"] else None
        others = [t for t in b["tags"] if t not in b["structs"]][:2 if not s0 else 1]
        week.append({"date": d, "wd": WEEK[d.weekday()], "gz": b["day_gz"], "stars": b["stars"], "score": b["score"],
                     "struct": "·".join([b["god"]] + ([s0] if s0 else []) + others),
                     "hint": STRUCT_HINT.get(s0) or GROUP_HINT[g]})

    # 公历月（1 日到月底）和节气月分开统计，区间写明
    mdays, d = [], target.replace(day=1)
    while d.month == target.month:
        mdays.append((d, a if d == target else D.analyse(p, d)))
        d += datetime.timedelta(days=1)
    cal = {"first": mdays[0][0], "last": mdays[-1][0], "days": [(x, b["stars"]) for x, b in mdays],
           "good": sum(b["stars"] >= 4 for _, b in mdays),
           "rank": 1 + sum(1 for _, b in mdays if b["score"] > a["score"]),
           "left_good": [x for x, b in mdays if b["stars"] >= 4 and x > target]}
    mo = D.month_outlook(p, target)
    jq = lunar.getNextJieQi()
    jd = D.jie_date(jq)

    good_h, bad_h, early_h, night_h, _ = D.hours(p, lunar)
    gui = lunar.getDayPositionYangGuiDesc()
    own = [k for k, x in D.DIR_WX.items() if x in p["xi"]]
    hl_yi = "、".join([x for x in lunar.getDayYi() if x not in D.SKIP_HUANGLI][:4]) or "诸事平常"
    hl_ji = "、".join([x for x in lunar.getDayJi() if x not in D.SKIP_HUANGLI][:4]) or "无"

    reminders = p.get("reminders") or []
    short = theme["name"]
    return {
        "target": target, "wd": WEEK[target.weekday()], "send_date": send_date, "review_date": send_date,
        "step_word": "明天" if send_date < target else "今天",
        "lunar_text": f"农历{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}",
        "year_gz": a["year_gz"], "month_gz": a["month_gz"], "day_gz": a["day_gz"], "dayun": a["dayun"],
        "dm": dm, "dm_wx": D.GAN_WX[dm],
        "score": a["score"], "stars": a["stars"], "level": D.STARS[a["stars"]],
        "gain": gain, "loss": loss, "subtotal": gain + loss, "sha_adj": sha_adj,
        "items": sorted(scored, key=lambda x: -abs(x["pts"])), "bases": bases, "sha": a["sha"], "zxj": a["zxj"],
        "theme": theme, "cols": {"事业": career, "财运": money, "感情": love},
        "concerns": concerns, "missing": missing,
        "life": life, "week": week, "cal": cal, "mo": mo,
        "next_jq": (jq.getName(), jd, (jd - target).days),
        "hours": {"good": good_h, "bad": bad_h, "early": early_h, "night": night_h},
        "dirs": {"gui": gui, "own": own, "match": gui in own},
        "huangli": (f"{lunar.getZhiXing()}日，值{lunar.getDayTianShen()}（{lunar.getDayTianShenType()}），"
                    f"{lunar.getXiu()}宿（{lunar.getXiuLuck()}），冲{lunar.getDayChongShengXiao()}，煞{lunar.getDaySha()}；"
                    f"宜{hl_yi}；忌{hl_ji}"),
        "wuxing": D.wuxing_view(p, a), "xi": p["xi"], "ji": p["ji"],
        "reminders": reminders, "tip": reminders[target.toordinal() % len(reminders)] if reminders else "",
        "subject": f"命盘日报 {target.month}/{target.day} 周{WEEK[target.weekday()]} · {'★' * a['stars']} "
                   f"{D.STARS[a['stars']]} · {short}",
    }
