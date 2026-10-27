#!/usr/bin/env python3
"""
今日预测实验（待验证）：每天从流日和原局、大运、流年、流月的结构里，挑 0 到 2 个第二天能核对的事件。

只是一组事先写死的假设，用来事后对照，不是结论，不参与评分和星级。规则带版本号，版本一旦启用就不改；
要改就新开一个版本，从启用日以后的日期生效，已经保存过的预测不重算。

流程：命盘结构（规则里的信号）→ 候选事件 → 按强度和优先级挑选 → 事先写死的发生和排除标准 → 当晚复盘对应一题。
信号的命理含义出自传统书目（见每条规则的 source）；「这个信号对应哪一类可核对的事件」是本项目自己的操作化定义，
不是古书原话，所以整个实验都标「待验证」。

只预测六类事件，不预测投资、彩票、疾病、灾祸，也不预测别人的心意。
v1 没有「预期不发生」的规则：没有明确依据就不写「不会发生」，所以每条预测的 expect 都是「发生」。
"""
import hashlib
import json

import daily as D

RULE_VERSION = "v1"
RULE_EFFECTIVE = "2026-10-28"   # v1 从这天的目标日期起用
THRESHOLD = 1.5                  # 净强度到这个数才入选
MAX_PICKS = 2

# 事件库：名称、发生标准、排除标准、复盘里的短说法。顺序就是同分时的优先级：
# 越靠前的越好核对、和星级（已经在固定题里验证）重叠越少；压力和第 2 题重合，放最后
EVENTS = {
    "help": {"name": "具体外部帮助",
             "occur": "别人给了能用的东西：资料、介绍人、实际搭手，或帮你解决了一个具体问题",
             "exclude": "点赞、客气的鼓励、你付钱买的服务",
             "short": "别人给了具体帮助"},
    "friction": {"name": "明确沟通摩擦",
                 "occur": "和人有明确的争执、指责、被当面拒绝或说话不愉快，能指出是哪一句、哪件事",
                 "exclude": "正常讨论里的分歧、自己猜对方语气、网上看到的争吵",
                 "short": "明确的沟通摩擦"},
    "contact": {"name": "非工作主动联系",
                "occur": "有人主动来找你（消息、电话或见面），内容和工作无关",
                "exclude": "群消息、工作通知、广告推销、对你先发的消息的回复",
                "short": "非工作的主动联系"},
    "reschedule": {"name": "外部导致的改期或临时任务",
                   "occur": "别人改了约好的时间或安排，或临时塞给你一件当天要处理的事",
                   "exclude": "你自己拖延、自己改计划",
                   "short": "别人造成的改期或临时任务"},
    "money": {"name": "计划外财务事项",
              "occur": "出现事先不知道的收款、付款、账单、退款、罚款，或有人开口借钱",
              "exclude": "已知的账单、你自己计划内或临时起意的消费",
              "short": "计划外的钱的事"},
    "pressure": {"name": "明显事务压力",
                 "occur": "当晚复盘第 2 题（压力）选 A「很大」",
                 "exclude": "第 2 题选 B「有一些」或 C「基本没有」",
                 "short": "明显的事务压力（看第 2 题）"},
}
CHECKLIST = ["contact", "help", "friction", "reschedule", "money"]   # 复盘时中立勾选的五类；压力直接用第 2 题

SRC = {
    "taohua": "神煞桃花（咸池）传统主人缘，《三命通会·论咸池》",
    "liuhe_day": "六合主相互吸引（《三命通会·论支元六合》）；日支是自己和身边最亲近的人",
    "hes": "流日天干合日主，传统读作人和事主动找上门（天干五合）",
    "bijie": "比肩、劫财是同辈、朋友（《子平真诠》论十神）",
    "guchen": "孤辰寡宿传统主孤单少往来（《三命通会·论孤辰寡宿》）",
    "huagai": "华盖传统主孤高、喜独处（《三命通会·论华盖》）",
    "tianyi": "天乙贵人主遇事有人相助（《三命通会·论天乙贵人》）",
    "yin": "印是生我者，主庇护、长辈、贵人（《子平真诠·论印绶》）",
    "shayin": "杀印相生：压力经印转化，常读作有人指点、有人接（梁湘润《大流年判例》十神生态）",
    "liuhe_xi": "六合合出喜用，传统读作有人帮衬、好商量",
    "yin_he": "印被合住（双边）：这份助力今天被牵走一半（梁湘润双边喜忌）",
    "kong_xi": "喜用落空亡，传统读作所求容易落空（梁湘润论空亡）",
    "xing": "刑主不和、相互别扭（《三命通会·论刑》）",
    "chong_day": "日支被冲：自己和最亲近的关系受对撞（《三命通会·论冲击》）",
    "shangguan": "伤官主口舌、锋芒（《子平真诠·论伤官》）",
    "chong_dm": "流日天干冲日主：直接冲着自己来",
    "he_day_xi": "日支逢合且合出喜用，关系偏和顺",
    "yima": "驿马主走动、变动（《三命通会·论驿马》）",
    "chong_month": "冲月支：月柱是提纲和门户，传统读作环境、安排的变动",
    "po": "破主好好的事出裂缝（六破）",
    "jiecai": "劫财主分财、夺财（《子平真诠·论建禄月劫》）",
    "jiesha": "劫煞传统主破财、财物被拿走（《三命通会·论劫煞亡神》）",
    "caisha": "财生杀、贪财坏印：钱的事变成压力或分心（十神生态）",
    "hai": "害主暗中拖累、暗亏（六害）",
    "guansha": "官杀是克我者，主压力、规矩（《子平真诠·论偏官》）",
    "guansha_ju": "地支凑成官杀局，压力被放大",
    "star1": "当天总评 1 星（宜守），是整张命盘一年里压力最大的一档",
    "zhi_guansha": "地支本气是官杀",
    "zhisha": "杀印相生、食神制杀：压力有承接或有本事去对付",
}


def _signals(p, a):
    """返回 [(事件, 规则名, 权重, 依据文字)]，权重为负的是相反依据。"""
    pillars = D.natal_chart(p)
    dm, day_zhi, month_zhi = pillars[2][0], pillars[2][1], pillars[1][1]
    gan, zhi = a["day_gz"][0], a["day_gz"][1]
    group = D.ten_god(dm, gan)[1]
    zgroup = D.ten_god(dm, D.CANG[zhi][0])[1]
    sha = {x["name"]: x for x in a["sha"]}
    terms = [x for x in a["points"] if x["pts"] is not None]

    def term(*keys):
        x = next((x for x in terms if all(k in x["term"] for k in keys)), None)
        return f"{x['term']}（计分 {x['pts']:+.1f}）" if x else ""

    def sha_txt(n):
        return f"{n}（神煞，{'计分 %+.1f' % sha[n]['pts'] if sha[n]['pts'] else '不计分'}）"

    xi = set(p["xi"])
    out = []

    def add(ev, rule, w, ev_text):
        out.append((ev, rule, w, ev_text))

    # 非工作主动联系
    if "桃花" in sha:
        add("contact", "taohua", 1.0, sha_txt("桃花"))
    pair_day = frozenset(zhi + day_zhi)
    if pair_day in D.HE:
        add("contact", "liuhe_day", 1.0, term(f"{zhi}与原局", "日支", "六合") or f"{zhi}与日支{day_zhi}六合")
    if "合身" in a["tags"]:
        add("contact", "hes", 1.0, f"流日{gan}合日主{dm}")
    if group == "比劫":
        add("contact", "bijie", 0.5, term(f"天干{gan}是你的"))
    if "孤辰寡宿" in sha:
        add("contact", "guchen", -0.5, sha_txt("孤辰寡宿"))
    if "华盖" in sha:
        add("contact", "huagai", -0.5, sha_txt("华盖"))

    # 具体外部帮助
    if "天乙贵人" in sha:
        add("help", "tianyi", 1.0, sha_txt("天乙贵人"))
    if group == "印" and D.GAN_WX[gan] in xi:
        add("help", "yin", 1.0, term(f"天干{gan}是你的"))
    if "杀印相生" in a["structs"]:
        add("help", "shayin", 0.5, term("杀印相生"))
    xi_he = [x for x in terms if "六合" in x["term"] and x["pts"] > 0]
    if xi_he:
        add("help", "liuhe_xi", 0.5, f"{xi_he[0]['term']}（计分 {xi_he[0]['pts']:+.1f}）")
    if group == "印" and any(x["term"].startswith(f"{gan}自己也被") for x in terms):
        add("help", "yin_he", -1.0, term(f"{gan}自己也被"))
    if "空亡" in sha and sha["空亡"]["kind"] == "凶":
        add("help", "kong_xi", -1.0, sha_txt("空亡"))

    # 明确沟通摩擦
    xing = [x for x in terms if "相刑" in x["term"]]
    if xing:
        add("friction", "xing", 1.0, "；".join(f"{x['term']}（计分 {x['pts']:+.1f}）" for x in xing))
    if a["chong_day"]:
        add("friction", "chong_day", 1.0, term(f"{zhi}冲", "日") or f"{zhi}冲日支{day_zhi}")
    if a["god"] == "伤官":
        add("friction", "shangguan", 0.5, term(f"天干{gan}是你的"))
    if "冲身" in a["tags"]:
        add("friction", "chong_dm", 1.0, term(f"流日{gan}冲日主"))
    if pair_day in D.HE and D.he_wx(pair_day, month_zhi) in xi:
        add("friction", "he_day_xi", -0.5, term(f"{zhi}与原局", "日支", "六合"))

    # 外部导致的改期或临时任务
    if "驿马" in a["tags"]:
        n = "驿马逢冲" if "驿马逢冲" in sha else "驿马"
        add("reschedule", "yima", 1.0, sha_txt(n))
    if frozenset(zhi + month_zhi) in D.CHONG:
        add("reschedule", "chong_month", 1.0, term(f"{zhi}冲", "月") or f"{zhi}冲月支{month_zhi}")
    po = [x for x in terms if "相破" in x["term"]]
    if po:
        add("reschedule", "po", 0.5, f"{po[0]['term']}（计分 {po[0]['pts']:+.1f}）")

    # 计划外财务事项
    if a["god"] == "劫财":
        add("money", "jiecai", 1.0, term(f"天干{gan}是你的"))
    if "劫煞" in sha:
        add("money", "jiesha", 1.0, sha_txt("劫煞"))
    cs = [s for s in a["structs"] if s in ("财生杀", "贪财坏印")]
    if cs:
        add("money", "caisha", 0.5, term(cs[0]))
    hai = [x for x in terms if "相害" in x["term"]]
    if hai:
        add("money", "hai", 0.5, f"{hai[0]['term']}（计分 {hai[0]['pts']:+.1f}）")

    # 明显事务压力
    gs_wx = next(w for w in "木火土金水" if D.wx_group(dm, w) == "官杀")
    if group == "官杀" and gs_wx in p["ji"]:
        add("pressure", "guansha", 1.0, term(f"天干{gan}是你的"))
    ju = [x for x in terms if f"{gs_wx}局" in x["term"] and "凑成" in x["term"]]
    if ju and gs_wx in p["ji"]:
        add("pressure", "guansha_ju", 1.0, f"{ju[0]['term']}（计分 {ju[0]['pts']:+.1f}）")
    if a["stars"] == 1:
        add("pressure", "star1", 1.0, f"总评 {a['score']:+.1f}，1 星")
    if zgroup == "官杀" and gs_wx in p["ji"]:
        add("pressure", "zhi_guansha", 0.5, term(f"地支{zhi}属"))
    zs = [s for s in a["structs"] if s in ("杀印相生", "食神制杀")]
    if zs:
        add("pressure", "zhisha", -0.5, term(zs[0]))
    return out


def build(p, target, a=None):
    """当天的预测：picks（0 到 2 条）、unselected（没入选的候选和原因）、none_reason。纯计算，不读写文件。"""
    a = a or D.analyse(p, target)
    sig = _signals(p, a)
    cands = []
    for i, key in enumerate(EVENTS):
        mine = [s for s in sig if s[0] == key]
        if not mine:
            continue
        pro = [s for s in mine if s[2] > 0]
        con = [s for s in mine if s[2] < 0]
        net = round(sum(s[2] for s in mine), 2)
        cands.append({"event": key, "order": i, "net": net, "pro": pro, "con": con})
    cands.sort(key=lambda c: (-c["net"], c["order"]))
    picks, unselected = [], []
    for c in cands:
        ok = c["net"] >= THRESHOLD and any(s[2] >= 1 for s in c["pro"])
        if ok and len(picks) < MAX_PICKS:
            picks.append(c)
            continue
        if not c["pro"]:
            why = "只有相反依据"
        elif c["net"] < THRESHOLD:
            why = (f"有相反依据（{'；'.join(s[3] for s in c['con'])}），净强度 {c['net']:.1f} 不到门槛 {THRESHOLD}"
                   if c["con"] else f"净强度 {c['net']:.1f} 不到门槛 {THRESHOLD}")
        elif not any(s[2] >= 1 for s in c["pro"]):
            why = "只有辅助依据，没有主依据"
        else:
            why = f"已选满 {MAX_PICKS} 条，强度或优先级排在后面"
        unselected.append({"event": key_name(c["event"]), "net": c["net"], "reason": why,
                           "signals": [_sig_dict(s) for s in c["pro"] + c["con"]]})
    preds = []
    for n, c in enumerate(picks, 1):
        e = EVENTS[c["event"]]
        preds.append({
            "id": f"{target:%Y%m%d}-{RULE_VERSION}-{n}", "n": n, "event": c["event"], "name": e["name"],
            "expect": "发生", "net": c["net"],
            "evidence": [_sig_dict(s) for s in c["pro"] + c["con"]],
            "occur": e["occur"], "exclude": e["exclude"],
            "question": f"观察{n}「{e['short']}」：A 发生了　B 发生了，但是看了日报后自己促成的　C 没发生　"
                        "D 无法判断　E 没有相关机会",
        })
    none_reason = ""
    if not preds:
        none_reason = ("这一天六类事件都没有对应的信号。" if not cands else
                       f"有 {len(cands)} 个候选，都没达到入选条件（净强度 ≥{THRESHOLD}，且至少一条主依据），不硬凑。")
    rec = {"target": target.isoformat(), "rule_version": RULE_VERSION, "threshold": THRESHOLD,
           "predictions": preds, "unselected": unselected, "none_reason": none_reason}
    rec["text"] = text(rec)
    rec["fingerprint"] = fingerprint(rec)
    return rec


def key_name(k):
    return EVENTS[k]["name"]


def _sig_dict(s):
    return {"rule": s[1], "weight": s[2], "basis": s[3], "source": SRC[s[1]]}


def text(rec):
    """预测的完整文字（存档、邮件、PDF 共用）。"""
    L = [f"预测实验（待验证）· 规则 {rec['rule_version']} · 目标日期 {rec['target']}"]
    if not rec["predictions"]:
        L.append("没有观察项。" + rec["none_reason"])
    for x in rec["predictions"]:
        L.append(f"观察{x['n']}（{x['id']}）：{x['name']}，预期发生，净强度 {x['net']:.1f}")
        L += [f"  {'依据' if s['weight'] > 0 else '相反依据'}（权重 {s['weight']:+.1f}）：{s['basis']}｜{s['source']}"
              for s in x["evidence"]]
        L.append(f"  算发生：{x['occur']}")
        L.append(f"  不算：{x['exclude']}")
    if rec["unselected"]:
        L.append("没入选的候选：" + "；".join(f"{u['event']}（{u['reason']}）" for u in rec["unselected"]))
    return "\n".join(L)


def fingerprint(rec):
    """预测内容的指纹（不含生成时间），工作流日志里只打印它，用来核对发出去的和保存的是同一份。"""
    body = json.dumps({k: rec[k] for k in ("target", "rule_version", "predictions", "unselected")},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:12]
