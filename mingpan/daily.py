#!/usr/bin/env python3
"""
命盘日报：把当天的流日放进「原局 + 大运 + 流年 + 流月」里看，生成日报并经 notify.py 推送。
规则说明见 rules.md。
用法：
  python mingpan/daily.py                       生成今天（曼谷时间）的日报并推送
  python mingpan/daily.py --dry-run             只打印，不推送
  python mingpan/daily.py --date 2026-10-19 --dry-run
仓库是公开的，所以推送时日志里只打印发送结果，不打印正文。
"""
import argparse, datetime, json, os
from pathlib import Path
from zoneinfo import ZoneInfo

from lunar_python import Solar

import layout
import notify

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Bangkok")
WEEK = "一二三四五六日"

GANS, ZHIS = "甲乙丙丁戊己庚辛壬癸", "子丑寅卯辰巳午未申酉戌亥"
GAN_WX = dict(zip(GANS, "木木火火土土金金水水"))
GAN_YANG = {g: i % 2 == 0 for i, g in enumerate(GANS)}
ZHI_WX = dict(zip(ZHIS, "水土木木土火火土金金土水"))
CANG = {"子": "癸", "丑": "己癸辛", "寅": "甲丙戊", "卯": "乙", "辰": "戊乙癸", "巳": "丙庚戊",
        "午": "丁己", "未": "己丁乙", "申": "庚壬戊", "酉": "辛", "戌": "戊辛丁", "亥": "壬甲"}
SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

GAN_HE = {frozenset(p) for p in ["甲己", "乙庚", "丙辛", "丁壬", "戊癸"]}
GAN_CHONG = {frozenset(p) for p in ["甲庚", "乙辛", "丙壬", "丁癸"]}
CHONG = {frozenset(p) for p in ["子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥"]}
HE = {frozenset(p) for p in ["子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未"]}
HAI = {frozenset(p) for p in ["子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌"]}
XING = {frozenset(p) for p in ["寅巳", "巳申", "寅申", "丑戌", "戌未", "丑未", "子卯"]}
ZI_XING = set("辰午酉亥")
SANHE = [("申子辰", "水"), ("亥卯未", "木"), ("寅午戌", "火"), ("巳酉丑", "金")]
SANHUI = [("寅卯辰", "木"), ("巳午未", "火"), ("申酉戌", "金"), ("亥子丑", "水")]

TIANYI = {"甲": "丑未", "戊": "丑未", "庚": "丑未", "乙": "子申", "己": "子申",
          "丙": "亥酉", "丁": "亥酉", "壬": "卯巳", "癸": "卯巳", "辛": "寅午"}
WENCHANG = dict(zip(GANS, "巳午申酉申酉亥子寅卯"))
LU = dict(zip(GANS, "寅卯巳午巳午申酉亥子"))
_GROUP4 = {**dict.fromkeys("申子辰", 0), **dict.fromkeys("寅午戌", 1),
           **dict.fromkeys("巳酉丑", 2), **dict.fromkeys("亥卯未", 3)}
YIMA, TAOHUA, HUAGAI = "寅申亥巳", "酉卯午子", "辰戌丑未"   # 按三合局分组查

# 以下神煞口径借自 jinchenma94/bazi-skill 的 references/shensha-table.md（MIT 许可）
JIANGXING, JIESHA, ZAISHA, WANGSHEN = "子午酉卯", "巳亥寅申", "午子卯酉", "亥巳申寅"   # 同上按三合局分组
JINYU = dict(zip(GANS, "辰巳未申未申戌亥丑寅"))
YANGREN = dict(zip(GANS, "卯寅午巳午巳酉子子亥"))
GUCHEN = {**dict.fromkeys("亥子丑", "寅"), **dict.fromkeys("寅卯辰", "巳"),
          **dict.fromkeys("巳午未", "申"), **dict.fromkeys("申酉戌", "亥")}
GUASU = {**dict.fromkeys("亥子丑", "戌"), **dict.fromkeys("寅卯辰", "丑"),
         **dict.fromkeys("巳午未", "辰"), **dict.fromkeys("申酉戌", "未")}
# 调候用神（《穷通宝鉴》）：日主 + 生月地支 → 第一调候字。思路借自 china-testing/bazi 的 tiaohous 表，这里只收乙木一行
TIAOHOU = {"乙" + z: t for z, t in zip(ZHIS, "丙丙丙丙癸癸癸癸庚癸癸丙")}
# 月令旺相休囚死
SEASON = dict(zip(ZHIS, "水土木木土火火土金金土水"))

CS_START = dict(zip(GANS, "亥午寅酉寅酉巳子申卯"))
STAGES = "长生 沐浴 冠带 临官 帝旺 衰 病 死 墓 绝 胎 养".split()
STAGE_NOTE = {
    "长生": "有生气，适合开个好头", "沐浴": "情绪容易波动、分心", "冠带": "状态在往上走",
    "临官": "有根有力，扛得住事", "帝旺": "日主最有力的一天，精力足，但别把话说满、事做满",
    "衰": "精力回落，稳着来", "病": "体力偏弱，留意身体", "死": "气弱，不宜硬撑",
    "墓": "适合收敛、整理、闭门做事", "绝": "气最弱，少做决定", "胎": "想法多、落地少，适合酝酿",
    "养": "适合休养蓄力",
}
STAGE_SCORE = {"长生": 0.5, "冠带": 0.3, "临官": 0.5, "帝旺": 0.5, "病": -0.5, "死": -0.5, "绝": -0.5}

GROUP_THEME = {"比劫": "同伴与竞争", "印": "贵人、学习与休养", "食伤": "表达、才华，也耗神",
               "财": "钱财与实务", "官杀": "压力、规矩与外部考验"}
ADVICE = {
    "比劫": ("见朋友、谈合作、运动", "借钱给人、和人争利"),
    "印": ("读书学习、拜访长辈和老师、处理文书", "拖延空想"),
    "食伤": ("写东西、做研究、果断处理积压的事", "口舌争执、熬夜耗神"),
    "财": ("记账理财、守住已有的", "大额支出、冒进投机"),
    "官杀": ("低调办事、找人帮忙、守规矩", "硬碰硬、冒风险"),
}
# 宜按领域细分：流日天干十神定每个领域的基调（建议，理由），冲合刑害和神煞再往对应领域里补一句
DOMAINS = ["工作", "钱财", "家人", "身体", "学习"]
DOMAIN_ADVICE = {
    "比劫": {"工作": ("和同事、伙伴碰一碰，分好工一起做，不和人争功", "比劫是同伴，也是竞争"),
             "钱财": ("不借钱给人，不合伙出钱", "比劫主分财"),
             "家人": ("联系兄弟姐妹和老朋友", "比劫是同辈"),
             "身体": ("运动出汗，活动筋骨", "比劫帮身，体力足"),
             "学习": ("找人讨论、一起学", "同伴日，交流比闷头读有收获")},
    "印": {"工作": ("整理资料、写方案、请教前辈，不拍板新项目", "印主思考和文书，不主决断"),
           "钱财": ("记账、核对账户和合同，不添大额开销", "印日心思在内，不在外求财"),
           "家人": ("多陪长辈，听听他们的意见", "印是长辈和庇护"),
           "身体": ("补觉、午休，少熬夜", "印主休养，今天养得回来"),
           "学习": ("读书、上课、做研究", "印日吸收快")},
    "食伤": {"工作": ("写东西、出方案、清掉积压的事，开会少抢话", "食伤主表达和执行，也容易话多惹人"),
             "钱财": ("有想法先记下来，不急着掏钱落实", "食伤生财，但今天是想法多过把握"),
             "家人": ("说话软一点，有不满先放一放", "食伤日口快，容易伤人"),
             "身体": ("早点睡，别熬夜赶工", "食伤泄日主之气，最耗神"),
             "学习": ("把学到的写下来、讲出来", "输出日，讲一遍比看三遍记得牢")},
    "财": {"工作": ("处理具体事务、对数核账，不接超出能力的活", "财是实务，接多了累身"),
           "钱财": ("记账、守住已有的，不追加、不冒进", "财日对钱敏感，容易贪也容易计较"),
           "家人": ("多顾家，家里的开支和伴侣商量着来", "财星主家用和伴侣"),
           "身体": ("按时吃饭，别为事忙到误饭点", "财日事务多，容易顾不上自己"),
           "学习": ("学点实用的，比如理财、管理", "财日适合学能落地的东西")},
    "官杀": {"工作": ("按规矩办事，交代的事先做完，不和上面硬顶", "官杀是压力和规矩"),
             "钱财": ("只守不攻，不签字担保", "官杀日外部压力大，守住就是赚"),
             "家人": ("回家少带情绪，压力找人说说", "压力日容易把火撒在家里"),
             "身体": ("放松肩颈，早睡，别硬扛", "官杀克身，最耗体力"),
             "学习": ("复习、考证，学规则和流程", "官杀主规矩，适合打基础")},
}
# 当天天干十神对应的心理倾向，只用来对照交易纪律，不给买卖时机
PSYCH = {
    "比肩": ("容易跟人较劲，或者听了别人的消息就想跟", "这个决定出自我的规则，还是别人的声音？"),
    "劫财": ("容易从众、跟风，也容易被人借钱或拉去合伙", "如果没人提起，我还会这么做吗？"),
    "正印": ("容易犹豫、拖延，该执行的规则下不了手", "有没有一件该做的事被我一拖再拖？"),
    "偏印": ("想法多、疑心重，容易反复推翻自己", "我是在分析，还是在给不行动找理由？"),
    "食神": ("容易放松、盯得松，觉得没事", "今天该检查的仓位和计划，我看过了吗？"),
    "伤官": ("自信过头，想证明自己，冲动打破规矩", "我想做的事，提前写进过计划吗？"),
    "正财": ("容易计较得失，盯着账面数字转", "看账户的次数，今天能不能少一半？"),
    "偏财": ("容易贪，看到机会就想多搏一把", "这笔钱亏掉，我晚上睡得着吗？"),
    "正官": ("过分谨慎、怕犯错，被规矩捆住", "我是在守规矩，还是在怕？"),
    "七杀": ("压力大，急躁、恐慌，一有波动就想全部动", "我现在是按计划走，还是被情绪推着走？"),
}
HEALTH = {
    "火": "火气偏旺，容易心浮、口干、睡不踏实。少咖啡浓茶，晚上早点放下手机。",
    "土": "土气偏重，容易脾胃不适、身体发沉。吃清淡些，饭后走一走。",
    "金": "金气偏重，金克木，容易肩颈发紧、胸闷、肝气不舒。多拉伸、深呼吸。",
    "水": "水是你的喜神，适合休养、补觉，注意别受凉。",
    "木": "木气来帮身，适合到户外走走、舒展筋骨。",
}
# 八方按后天八卦配五行：震东、巽东南属木，离南火，坤西南、艮东北属土，兑西、乾西北属金，坎北水；用来算命主固定的喜用方位
DIR_WX = {"正东": "木", "东南": "木", "正南": "火", "西南": "土", "正西": "金", "西北": "金", "正北": "水", "东北": "土"}
POS = ["年", "月", "日", "时"]
POS_DOMAIN = {"年": "大环境", "月": "工作环境", "日": "自己和身体", "时": "孩子和后续计划"}
FLOW_DOMAIN = {"大运": "这十年的主线", "流年": "今年的事", "流月": "这个月的事"}
GROUP_SHORT = {"比劫": "同伴和竞争", "印": "贵人和休养", "食伤": "表达和消耗", "财": "钱财和实务", "官杀": "压力和考验"}
STARS = {1: "宜守", 2: "偏弱", 3: "平", 4: "偏旺", 5: "旺"}
GIST = {1: "压力日。守住规矩、少做决定，平安过去就是赢。",
        2: "消耗大于助力。少揽事，把精力留给最重要的一两件。",
        3: "有助力也有消耗，按计划做事就好。",
        4: "助力多于消耗，适合把该推进的事往前推一步。",
        5: "顺的一天，适合见人、谈事、推进重要的事，但别把话说满。"}

# 黄历里丧葬、祭祀类的条目和日常无关，推送时略去
SKIP_HUANGLI = {"入殓", "破土", "启钻", "安葬", "除服", "成服", "移柩", "修坟", "立碑", "谢土",
                "祭祀", "斋醮", "馀事勿取", "诸事不宜"}


def wx_group(dm, wx):
    me = GAN_WX[dm]
    if wx == me:
        return "比劫"
    if SHENG[wx] == me:
        return "印"
    if SHENG[me] == wx:
        return "食伤"
    return "财" if KE[me] == wx else "官杀"


def ten_god(dm, gan):
    group = wx_group(dm, GAN_WX[gan])
    same = GAN_YANG[dm] == GAN_YANG[gan]
    names = {"比劫": ("比肩", "劫财"), "印": ("偏印", "正印"), "食伤": ("食神", "伤官"),
             "财": ("偏财", "正财"), "官杀": ("七杀", "正官")}[group]
    return names[0] if same else names[1], group


def stage(dm, zhi):
    i0, i = ZHIS.index(CS_START[dm]), ZHIS.index(zhi)
    return STAGES[(i - i0) % 12 if GAN_YANG[dm] else (i0 - i) % 12]


def xunkong(gz):
    start = (ZHIS.index(gz[1]) - GANS.index(gz[0])) % 12
    return ZHIS[(start + 10) % 12] + ZHIS[(start + 11) % 12]


def natal_chart(p):
    if p.get("pillars"):
        return p["pillars"]
    y, m, d = map(int, p["birth_date"].split("-"))
    hh, mm = map(int, p["birth_time"].split(":"))
    ec = Solar.fromYmdHms(y, m, d, hh, mm, 0).getLunar().getEightChar()
    return [ec.getYear(), ec.getMonth(), ec.getDay(), ec.getTime()]


def dayun_list(p):
    if p.get("dayun"):
        return p["dayun"]
    if not p.get("birth_date"):
        return []
    y, m, d = map(int, p["birth_date"].split("-"))
    hh, mm = map(int, p["birth_time"].split(":"))
    yun = Solar.fromYmdHms(y, m, d, hh, mm, 0).getLunar().getEightChar().getYun(0 if p.get("gender") == "女" else 1)
    ms = yun.getStartSolar().getMonth()
    return [[x.getGanZhi(), f"{x.getStartYear()}-{ms:02d}"] for x in yun.getDaYun() if x.getGanZhi()]


def current_dayun(p, date):
    cur = None
    for gz, start in dayun_list(p):
        if start <= date.strftime("%Y-%m"):
            cur = gz
    return cur


def lunar_of(date):
    return Solar.fromYmdHms(date.year, date.month, date.day, 12, 0, 0).getLunar()


def season_state(dm, month_zhi):
    """月令下日主的旺相休囚死。"""
    lead, me = SEASON[month_zhi], GAN_WX[dm]
    return ("旺" if me == lead else "相" if SHENG[lead] == me else "休" if SHENG[me] == lead
            else "囚" if KE[me] == lead else "死")


def jie_date(j):
    s = j.getSolar()
    return datetime.date(s.getYear(), s.getMonth(), s.getDay())


def month_outlook(p, date):
    """这个节气月和下个节气月逐日打分对比，加上月柱十神、喜忌、月令底气和与原局的冲合，给出走势结论。"""
    pillars = natal_chart(p)
    dm = pillars[2][0]
    xi, ji = set(p["xi"]), set(p["ji"])
    lunar = lunar_of(date)
    start, nxt = jie_date(lunar.getPrevJie()), lunar.getNextJie()
    mid = jie_date(nxt)
    end = jie_date(lunar_of(mid + datetime.timedelta(days=1)).getNextJie())

    def stats(d0, d1):
        days = [analyse(p, d0 + datetime.timedelta(days=i)) for i in range((d1 - d0).days)]
        return {"gz": analyse(p, d0 + datetime.timedelta(days=1))["month_gz"],
                "mean": sum(b["score"] for b in days) / len(days),
                "good": sum(b["stars"] >= 4 for b in days), "bad": sum(b["stars"] <= 2 for b in days),
                "state": season_state(dm, analyse(p, d0 + datetime.timedelta(days=1))["month_gz"][1])}

    cur, new = stats(start, mid), stats(mid, end)
    # 平常水平：前后各半年逐日平均分，用来说这个月、下个月在你自己的一年里算高还是低
    base = sum(analyse(p, date + datetime.timedelta(days=i))["score"] for i in range(-182, 183)) / 365
    for m in (cur, new):
        m["vs"] = ("高于你的平常" if m["mean"] - base >= 0.25 else "低于你的平常" if m["mean"] - base <= -0.25
                   else "和你的平常差不多")
    diff = new["mean"] - cur["mean"]
    # 门槛按这张命盘两年里各月平均分的波动定（各月平均分大多在 -1.6 到 -0.8 之间）
    verdict = ("明显转好" if diff >= 0.4 else "略有好转" if diff >= 0.15 else
               "明显转差" if diff <= -0.4 else "略有转差" if diff <= -0.15 else "和这个月差不多")

    def xj(wx):
        return "喜用" if wx in xi else "忌神" if wx in ji else "闲神"

    g, z = new["gz"][0], new["gz"][1]
    why = [f"天干{g}是你的{ten_god(dm, g)[0]}（{xj(GAN_WX[g])}），地支{z}本气是你的{ten_god(dm, CANG[z][0])[0]}"
           f"（{xj(ZHI_WX[z])}）",
           f"{SEASON[z]}当令，你的{GAN_WX[dm]}" + (f"仍处在「{new['state']}」" if new["state"] == cur["state"]
                                                  else f"从「{cur['state']}」变成「{new['state']}」")]
    zpos = {}
    for i, x in enumerate(pillars):
        zpos.setdefault(x[1], []).append(POS[i])
    for zz, ps in zpos.items():
        pair, where = frozenset(z + zz), f"原局{'、'.join(ps)}支{zz}"
        dom = "、".join(POS_DOMAIN[x] for x in ps)
        if zz != z and pair in CHONG:
            why.append(f"冲{where}（{dom}有变动）")
        elif pair in HE:
            why.append(f"合{where}（{dom}有人帮衬）")
        elif zz == z and z in ZI_XING:
            why.append(f"和{where}自刑（{dom}方面容易自己跟自己较劲）")
    advice = {"明显转好": "该推进的事可以排到下个月，但照样守住自己定的规矩",
              "略有好转": "压力会松一点，可以稳步推进",
              "和这个月差不多": "节奏不用变，照现在的计划走",
              "略有转差": "要紧的事尽量在交节前办完",
              "明显转差": f"要紧的事尽量在{nxt.getName()}之前办完，进了新月份以守为主"}[verdict]
    return {"jie": nxt.getName(), "date": mid, "cur": cur, "new": new, "verdict": verdict, "base": base,
            "why": why, "advice": advice}


def analyse(p, date):
    pillars = natal_chart(p)
    dm, day_zhi, year_zhi = pillars[2][0], pillars[2][1], pillars[0][1]
    xi, ji = set(p["xi"]), set(p["ji"])
    lunar = lunar_of(date)
    ly, lm, ld = lunar.getYearInGanZhiExact(), lunar.getMonthInGanZhiExact(), lunar.getDayInGanZhi()
    dy = current_dayun(p, date)
    gan, zhi = ld[0], ld[1]

    def sign(wx):
        return 1 if wx in xi else -1 if wx in ji else 0

    def xj(wx):
        return "喜用" if wx in xi else "忌神" if wx in ji else "闲神"

    score, points, tags, yi, avoid = 0.0, [], [], [], []
    weight = {w: 0.0 for w in "木火土金水"}   # 今天流日带来的五行分量，用于身体提醒
    weight[GAN_WX[gan]] += 1
    weight[ZHI_WX[zhi]] += 1
    score += sign(GAN_WX[gan]) + sign(ZHI_WX[zhi])
    for s in CANG[zhi][1:]:
        weight[GAN_WX[s]] += 0.3
        score += 0.3 * sign(GAN_WX[s])

    god, group = ten_god(dm, gan)
    zgod, zgroup = ten_god(dm, CANG[zhi][0])
    lead = SEASON[lm[1]]
    me = GAN_WX[dm]
    state = ("旺" if me == lead else "相" if SHENG[lead] == me else "休" if SHENG[me] == lead
             else "囚" if KE[me] == lead else "死")
    points.append(f"本月{lm}，{lead}当令，你的{me}处在「{state}」，"
                  + ("底气足。" if state in "旺相" else "底气偏弱，整个月宜守。" if state in "囚死" else "底气一般。"))
    points.append(f"天干{gan}是你的{god}（{xj(GAN_WX[gan])}），主{GROUP_THEME[group]}。")
    cang = "、".join(f"{s}{ten_god(dm, s)[0]}" for s in CANG[zhi])
    points.append(f"地支{zhi}属{ZHI_WX[zhi]}（{xj(ZHI_WX[zhi])}），藏{cang}，本气是{zgod}。")
    good, bad = ADVICE[group]
    extra = {k: [] for k in DOMAINS}
    yi.append(good)
    avoid.append(bad)

    st = stage(dm, zhi)
    score += STAGE_SCORE.get(st, 0)
    points.append(f"{dm}木日主在{zhi}为「{st}」，{STAGE_NOTE[st]}。")

    # 天干：流日天干与日主、原局其他天干、大运、流年天干的合冲
    if frozenset(gan + dm) in GAN_CHONG:
        score -= 1
        tags.append("冲身")
        points.append(f"流日{gan}冲日主{dm}，{god}直接冲身，今天压力感会比较明显。")
    elif frozenset(gan + dm) in GAN_HE:
        tags.append("合身")
        points.append(f"流日{gan}合日主{dm}，{GROUP_THEME[group]}方面的人和事主动找上你。")
    stems = {}
    for i in (0, 1, 3):
        stems.setdefault(pillars[i][0], []).append(f"原局{POS[i]}干")
    for label, gz in (("大运", dy), ("流年", ly)):
        if gz:
            stems.setdefault(gz[0], []).append(label)
    for s, labels in stems.items():
        if s != gan and frozenset(gan + s) in GAN_HE:
            g2 = ten_god(dm, s)[0]
            k = sign(GAN_WX[s])
            score -= 0.5 * k
            msg = ("忌神被合住，这方面的压力有所缓解" if k < 0 else
                   "喜神被合住，这份助力今天打了折扣" if k > 0 else "两者相互牵绊")
            points.append(f"流日{gan}合住{'、'.join(labels)}的{s}（{g2}），{msg}。")
            tags.append(f"合{g2}")

    # 地支：流日地支与原局四支、大运、流年、流月地支的冲合刑害
    zmap = {}
    for i in range(4):
        zmap.setdefault(pillars[i][1], []).append(POS[i])
    for label, gz in (("大运", dy), ("流年", ly), ("流月", lm)):
        if gz:
            zmap.setdefault(gz[1], []).append(label)

    def name(z):
        natal = [x for x in zmap[z] if x in POS]
        parts = ([f"原局{'、'.join(natal)}支"] if natal else []) + [x for x in zmap[z] if x not in POS]
        return "、".join(parts) + z

    def domain(z):
        return "、".join(POS_DOMAIN.get(x) or FLOW_DOMAIN[x] for x in zmap[z])

    for z, labels in zmap.items():
        pair, natal = frozenset(zhi + z), [x for x in labels if x in POS]
        hits_day = "日" in labels
        if z != zhi and pair in CHONG:
            score -= 1.5 if hits_day else 0.7 if natal else 0.5
            tags.append(f"冲{z}")
            points.append(f"{zhi}冲{name(z)}：{domain(z)}方面容易有变动。")
            if hits_day:
                avoid.append("做重大决定、签字、远行")
                extra["工作"].append("日支被冲，不拍板、不签字")
                extra["家人"].append("日支被冲，和家人有分歧先缓一缓")
            elif "月" in natal:
                extra["工作"].append("冲到工作宫，安排容易变，留好余地")
        elif pair in HE:
            score += 1 if hits_day else 0.5
            tags.append(f"合{z}")
            points.append(f"{zhi}与{name(z)}六合：{domain(z)}方面有人帮衬，好商量。")
            if hits_day:
                yi.append("和家人、伴侣、合伙人多沟通")
                extra["家人"].append("日支逢合，和伴侣、家人好商量，有事今天说")
        if (z != zhi and pair in XING) or (z == zhi and zhi in ZI_XING):
            score -= 0.5
            points.append(f"{zhi}{z}相刑：{domain(z)}方面容易起摩擦。")
            avoid.append("说话冲、和人起争执")
            extra["工作"].append(f"{zhi}{z}相刑，说话留三分余地")
        if pair in HAI:
            score -= 0.3
            points.append(f"{zhi}{z}相害：{domain(z)}方面提防暗中损耗。")
            avoid.append("轻信他人、替人担保")
            extra["钱财"].append(f"{zhi}{z}相害，不轻信、不替人担保")

    # 三合、三会：流日地支能否和原局、大运、流年、流月凑成局
    for combos, kind in ((SANHE, "三合"), (SANHUI, "三会")):
        for chars, wx in combos:
            if zhi not in chars:
                continue
            have = [c for c in chars if c != zhi and c in zmap]
            grp = wx_group(dm, wx)
            if len(have) == 2:
                score += 1.5 * sign(wx)
                weight[wx] += 1.5
                tags.append(f"{wx}局")
                points.append(f"今天的{zhi}和{name(have[0])}、{name(have[1])}凑成{chars}{kind}{wx}局："
                              f"{wx}是你的{grp}（{xj(wx)}），{GROUP_SHORT[grp]}的分量今天被放大。")
            elif kind == "三合" and len(have) == 1 and chars[1] in (zhi, have[0]):
                score += 0.5 * sign(wx)
                weight[wx] += 0.5
                points.append(f"{zhi}与{name(have[0])}半合{wx}局，{GROUP_SHORT[grp]}的分量有所加强。")

    # 神煞
    n_main = len(points)
    if zhi in TIANYI[dm]:
        score += 1
        tags.append("贵人")
        points.append("今天逢天乙贵人，遇事有人搭把手。")
        yi.append("出门见人、谈事、求助")
        extra["工作"].append("逢天乙贵人，卡住的事可以开口求助")
    if zhi == WENCHANG[dm]:
        tags.append("文昌")
        points.append("今天逢文昌，脑子清楚，适合学习和写作。")
        yi.append("考试、写作、学习")
        extra["学习"].append("逢文昌，脑子清楚，考试、写作都合适")
    if zhi == LU[dm]:
        score += 0.5
        tags.append("禄")
        points.append("今天逢禄神，心里有底气，适合做本职的事。")
    if zhi in {YIMA[_GROUP4[day_zhi]], YIMA[_GROUP4[year_zhi]]}:
        tags.append("驿马")
        if frozenset(zhi + day_zhi) in CHONG:
            points.append("驿马逢冲，奔波难免，出门注意安全。")
            extra["身体"].append("驿马逢冲，出门注意安全")
        else:
            points.append("今天逢驿马，走动多，适合出行办事。")
            yi.append("出行走动")
            extra["工作"].append("逢驿马，适合出门办事")
    if zhi in {TAOHUA[_GROUP4[day_zhi]], TAOHUA[_GROUP4[year_zhi]]}:
        points.append("今天逢桃花，人缘好，也容易有感情上的牵扯。")
    if zhi in {HUAGAI[_GROUP4[day_zhi]], HUAGAI[_GROUP4[year_zhi]]}:
        points.append("今天逢华盖，适合独处、研究、读书，人容易觉得孤单。")
    for table, label, note, pts in (
            (JIANGXING, "将星", "有主见，镇得住场面", 0), (JIESHA, "劫煞", "防破财、东西被人拿走", -0.3),
            (ZAISHA, "灾煞", "防意外和小伤，出行注意安全", -0.3), (WANGSHEN, "亡神", "心思重、容易想多，也防说漏嘴", 0)):
        if zhi in {table[_GROUP4[day_zhi]], table[_GROUP4[year_zhi]]}:
            score += pts
            points.append(f"今天逢{label}，{note}。")
            if label == "劫煞":
                extra["钱财"].append("逢劫煞，看好财物")
            elif label == "灾煞":
                extra["身体"].append("逢灾煞，出行注意安全")
    if zhi == JINYU[dm]:
        points.append("今天逢金舆，有人照应，出行顺。")
    if zhi == YANGREN[dm]:
        points.append("今天逢羊刃，性子急、容易冲动，也更有魄力。")
    if zhi in (GUCHEN[year_zhi], GUASU[year_zhi]):
        points.append("今天逢孤辰寡宿，容易觉得孤单，适合独处做事。")
    tiao = p.get("tiaohou") or TIAOHOU.get(dm + pillars[1][1])
    if tiao and tiao in (gan, CANG[zhi][0]):
        score += 0.5
        tags.append("调候")
        extra["身体"].append(f"见{tiao}调候，心容易静下来")
        points.append(f"今天见{tiao}，这是你命里最需要的调候之{GAN_WX[tiao]}，燥气得润，心容易静下来。")
    jishen = [x for x in lunar.getDayJiShen() if x in ("天德", "月德", "天德合", "月德合")]
    if jishen:
        score += 0.5
        points.append(f"今天是{'、'.join(jishen)}日，逢凶有解，适合办正事。")
    kong = xunkong(pillars[2])
    if zhi in kong:
        score -= 0.5
        tags.append("空亡")
        extra["工作"].append("落空亡，约定和承诺多确认一遍")
        points.append(f"今天的{zhi}落在你的空亡（{kong}），许诺和约定容易落空，重要的事多确认一遍。")

    ts_type = lunar.getDayTianShenType()
    score += 0.3 if ts_type == "黄道" else -0.3
    # 门槛按这张命盘一年里的分数分布定（约 15% / 20% / 40% / 15% / 10%），星级是和你自己的平常日子比
    stars = 1 if score <= -3.9 else 2 if score <= -2.2 else 3 if score < 0.9 else 4 if score < 2.4 else 5

    heavy = max((w for w in weight if w in ji), key=lambda w: weight[w], default=None)
    body = [HEALTH[heavy] if heavy and weight[heavy] >= 1.5 else HEALTH[max(weight, key=weight.get)]]
    if frozenset(zhi + day_zhi) in CHONG:
        body.append("日支是身体宫，今天被冲，留意睡眠和小磕碰。")

    domains = []
    for k in DOMAINS:
        text, why = DOMAIN_ADVICE[group][k]
        if k == "工作":
            why = f"{gan}是你的{god}，{why}"
        domains.append((k, text, why, extra[k]))

    return {
        "domains": domains,
        "lunar": lunar, "year_gz": ly, "month_gz": lm, "day_gz": ld, "dayun": dy,
        "god": god, "score": score, "stars": stars, "points": points[:n_main], "sha": points[n_main:], "tags": tags,
        "yi": list(dict.fromkeys(yi)), "ji": list(dict.fromkeys(avoid)),
        "body": body, "psych": PSYCH[god], "weight": weight,
    }


# 五行按喜忌分两块。忌神不只是坏事：按十神说它的正面用法，再看今天有没有化解它的五行
# （杀印相生、伤官佩印、比劫帮身担财、财能制印、官杀管比劫，都是命理里常用的化忌思路）
GROUP_MEAN = {"比劫": "同伴、帮身", "印": "贵人、学习", "食伤": "表达、执行",
              "财": "钱财、实务", "官杀": "压力、规矩"}
JI_USE = {"食伤": "用来输出：写东西、把想法讲清楚、清掉积压的事；做完一两件就停，别熬夜",
          "财": "用来办实事：对账、收尾，把手上的事落地；只处理已有的，不开新摊子",
          "官杀": "把压力当截止时间，逼自己把该交的事交掉、把规矩守住；不硬扛，累了就停",
          "印": "用来学习和规划，但给自己定好动手的时间，别光想不做",
          "比劫": "用来找人合作分工，但钱和利益先说清楚"}
# 忌神十神 → 化解它的十神，以及今天没来时自己怎么补
JI_FIX = {"官杀": ("印", "杀印相生，压力经它转成助力", "找人请教、先学再做、早点休息"),
          "食伤": ("印", "印能护身、收住耗散", "做完事读会儿书、安静一会儿"),
          "财": ("比劫", "比劫帮身，扛得住事和钱", "事多就找信得过的人分担"),
          "印": ("财", "财能制印，把想法落地", "把想法落成一件具体的事"),
          "比劫": ("官杀", "官杀能管住比劫", "给自己定规矩和时限")}


def wuxing_view(p, a):
    """流日五行按喜、忌分组，每个五行标十神和分量；忌神附正面用法和化解。"""
    dm = natal_chart(p)[2][0]
    w = a["weight"]
    wx_of = {wx_group(dm, x): x for x in "木火土金水"}
    out = {"喜": [], "忌": []}
    for kind, elems in (("喜", p["xi"]), ("忌", p["ji"])):
        for x in elems:
            g = wx_group(dm, x)
            item = {"wx": x, "w": w[x], "group": g, "mean": GROUP_MEAN[g]}
            if kind == "忌" and w[x] > 0:
                fix_g, how, diy = JI_FIX[g]
                fx = wx_of[fix_g]
                item["use"] = JI_USE[g]
                item["fix"] = (f"今天{fx}也在，{how}" if w[fx] >= 1 else
                               f"今天{fx}只来了一点，靠它不够，自己再补：{diy}" if w[fx] > 0 else
                               f"今天{fx}没来，自己补：{diy}")
                if g == "官杀" and w[wx_of["食伤"]] >= 1:
                    item["fix"] += f"；{wx_of['食伤']}也在，可以靠本事和表达把压力化开（食神制杀）"
            out[kind].append(item)
    return out


# 好时辰只在醒着的时段里挑（辰时到亥时，07:00-22:59），夜里的时辰再好也用不上
AWAKE = "辰巳午未申酉戌亥"
# 好时辰适合做什么：按时辰地支本气对日主的十神；逢天乙贵人改成求人谈事
HOUR_TODO = {"比劫": "和同事、朋友商量事，一起干活", "印": "读书、静下来想清楚一件事、请教人",
             "食伤": "写东西、出方案、清掉积压的事", "财": "处理账目和具体事务",
             "官杀": "办正事、交差、处理规矩上的事"}
# 同一天两个好时辰十神相同时，后一个按黄道星换个说法，免得重复
STAR_TODO = {"青龙": "约人见面、谈事", "明堂": "见领导、办公事", "金匮": "处理钱和账目",
             "天德": "办最要紧的正事", "玉堂": "读书、写文书", "司命": "处理日常琐事"}
# 要避开的时辰当心什么：按黄历当时的黑道星
HOUR_WARN = {"朱雀": "容易起口舌，少争论、少表态", "白虎": "防磕碰和意外，开车走路慢一点",
             "天牢": "容易被事困住，别轻易答应人", "玄武": "防丢东西、防被骗",
             "天刑": "容易起冲突，话到嘴边留半句", "勾陈": "容易被琐事缠住，别揽事"}


def hours(p, lunar):
    pillars = natal_chart(p)
    dm, day_zhi = pillars[2][0], pillars[2][1]
    xi, ji = set(p["xi"]), set(p["ji"])
    rows = []
    for idx, t in enumerate(lunar.getTimes()[1:]):   # 丑时到亥时，再加晚子时
        z = t.getGanZhi()[1]
        luck, star = t.getTianShenLuck(), t.getTianShen()
        sc, why = (1 if luck == "吉" else -1), [f"{star}{luck}"]
        wx = ZHI_WX[z]
        if wx in xi:
            sc += 1
            why.append(f"{wx}为喜用")
        elif wx in ji:
            sc -= 1
        chong = frozenset(z + day_zhi) in CHONG
        if chong:
            sc -= 1
            why.append("冲日支")
        noble = z in TIANYI[dm]
        if noble:
            sc += 1
            why.append("贵人时")
        god, group = ten_god(dm, CANG[z][0])
        todo = "求人帮忙、约人谈事" if noble else HOUR_TODO[group]
        warn = "冲日支，别做决定、别签字" if chong else HOUR_WARN.get(star, "少做决定、别冲动")
        rows.append({"sc": sc, "idx": idx, "name": f"{z}时 " + ("23:00-00:59" if z == "子" else f"{t.getMinHm()}-{t.getMaxHm()}"),
                     "why": "，".join(why + [f"{god}时"]), "todo": todo, "warn": warn})
    awake = [r for r in rows if r["name"][0] in AWAKE]
    # 照实标：分数 ≥1 才算「好」；白天一个好的都没有时，才用黄道吉、分数为 0 的时辰补位，标「平」
    good = sorted([r for r in awake if r["sc"] >= 1], key=lambda r: -r["sc"])[:3]
    for r in good:
        r["level"] = "好"
    if len(good) < 2:
        flat = [r for r in awake if r["sc"] == 0 and r["why"].split("，")[0].endswith("吉")]
        for r in flat[:2 - len(good)]:
            r["level"] = "平"
            good.append(r)
    good.sort(key=lambda r: r["idx"])
    used = set()
    for r in good:
        if r["todo"] in used:
            r["todo"] = STAR_TODO[r["why"].split("，")[0][:2]]
        used.add(r["todo"])
    bad = sorted(sorted([r for r in awake if r["sc"] <= -1], key=lambda r: r["sc"])[:2], key=lambda r: r["idx"])
    # 清晨卯时（05-07）是好时辰时单独提一句，早起可用；其余夜里的好时辰只在详细分析里照实列出
    early = next((dict(r, level="好·清晨", todo="早起想事情、定计划") for r in rows
                  if r["name"][0] == "卯" and r["sc"] >= 1), None)
    night = [r["name"] for r in rows if r["name"][0] not in AWAKE and r["sc"] >= 1]
    return good, bad, early, night


def stars_text(n):
    return "★" * n + "☆" * (5 - n)


def report(p, date):
    a = analyse(p, date)
    lunar = a["lunar"]
    hl_yi = "、".join([x for x in lunar.getDayYi() if x not in SKIP_HUANGLI][:4]) or "诸事平常"
    hl_ji = "、".join([x for x in lunar.getDayJi() if x not in SKIP_HUANGLI][:4]) or "无"
    good_h, bad_h, early_h, night_h = hours(p, lunar)
    reminders = p.get("reminders") or ["传统文化参考，不是预言。"]

    tip = reminders[date.toordinal() % len(reminders)]
    head = [f"**今日：{stars_text(a['stars'])} {STARS[a['stars']]}**", "",
            f"**一句话：{GIST[a['stars']]}**", ""]
    L = [f"农历{lunar.getMonthInChinese()}月{lunar.getDayInChinese()} · {a['year_gz']}年 {a['month_gz']}月 "
         f"{a['day_gz']}日" + (f" · 大运{a['dayun']}" if a["dayun"] else ""),
         f"评分 {a['score']:+.1f}（星级是和你自己一年里的日子比）",
         "", "### 一、今天和你的命盘"]
    L += [f"- {x}" for x in a["points"]]
    if a["sha"]:
        L += ["", "**神煞**"] + [f"- {x}" for x in a["sha"]]
    L += ["", "### 二、宜忌"]
    for k, text, why, more in a["domains"]:
        L.append(f"- {k}：{text}（{why}）" + "".join(f"；{m}" for m in more) + "。")
    L += [f"- 忌：{'；'.join(a['ji'])}。",
          f"- 黄历：{lunar.getZhiXing()}日，值{lunar.getDayTianShen()}（{lunar.getDayTianShenType()}），"
          f"{lunar.getXiu()}宿（{lunar.getXiuLuck()}），冲{lunar.getDayChongShengXiao()}，煞{lunar.getDaySha()}。"
          f"宜{hl_yi}；忌{hl_ji}。",
          "", "### 三、时辰与方位（按当地钟点）"]
    if not any(h["level"] == "好" for h in good_h):
        L.append("- 今天 07:00 到 23:00 之间没有真正的好时辰，下面标「平」的只是白天里相对稳的。")
    L += [f"- 【{h['level']}】{h['name']}：{h['todo']}（{h['why']}）。" for h in good_h]
    L += [f"- 【避开】{h['name']}：{h['warn']}（{h['why']}）。" for h in bad_h]
    if night_h:
        L.append(f"- 夜里和清晨也有好时辰：{'、'.join(night_h)}，这些都在睡觉的时段，只照实列出。"
                 + ("卯时早起可以用来想事情、定计划。" if early_h else ""))
    # 方位只用两样：命主固定的喜用方位（长期布置）和当天的阳贵（办事）。喜神、福神、财神只看日干、人人一样，不用
    gui = lunar.getDayPositionYangGuiDesc()
    own = [d for d, x in DIR_WX.items() if x in p["xi"]]
    match = gui in own
    L += [f"- 当天办事看阳贵：{gui}。求人、谈事、拜访，从你出发的地方（家或办公室）看，挑{gui}方向的地点；"
          f"在屋里谈就坐在房间{gui}那一侧。"
          + ("今天正好落在你的喜用方位上，是最好用的一天。" if match else
             f"{gui}不在你的喜用方位上，当天的事照样按它办，长期布置不用跟着改。"),
          f"- 长期布置看喜用方位：{'、'.join(own)}（按八卦配五行，属{'、'.join(p['xi'])}），每天不变。"
          "以房间为准，书桌、办公座位让你坐下时面朝这几个方向。",
          "- 方向不按城市分区，以你当时所在的地方为中心，看真实的东南西北，用手机指南针就能看；在曼谷还是在国内都一样。"
          "方位只是锦上添花，约谁、准备得好不好更重要。"]
    risk, question = a["psych"]
    L += ["", "### 四、身心",
          *[f"- 身体：{x}" for x in a["body"]],
          f"- 心态：{a['god']}日，{risk}。",
          f"- 自检一问：{question}",
          "", "### 五、未来六天"]
    days = [(date, a)]
    for i in range(1, 7):
        d = date + datetime.timedelta(days=i)
        b = analyse(p, d)
        days.append((d, b))
        tag = "·".join([b["god"]] + b["tags"][:2])
        L.append(f"- {d.month}/{d.day} 周{WEEK[d.weekday()]} {b['day_gz']} {stars_text(b['stars'])} {tag}")

    month_days, d = [], date.replace(day=1)
    while d.month == date.month:
        month_days.append((d, a if d == date else analyse(p, d)))
        d += datetime.timedelta(days=1)
    rank = 1 + sum(1 for _, b in month_days if b["score"] > a["score"])
    good = [d for d, b in month_days if b["stars"] >= 4]
    left_good = [f"{d.month}/{d.day}" for d in good if d > date]
    month_line = (f"排第 {rank}/{len(month_days)} 名；好日子（4★以上）{len(good)} 天"
                  + (f"，还剩 {'、'.join(left_good)}" if left_good else "，本月已经过完"))

    jq = lunar.getNextJieQi()
    jd = jq.getSolar()
    left = (datetime.date(jd.getYear(), jd.getMonth(), jd.getDay()) - date).days
    L += ["", "### 节气和下个月", f"- 今天{jq.getName()}。" if left == 0 else
          f"- 下一个节气：{jq.getName()} {jd.getMonth()}/{jd.getDay()}（还有{left}天）。"]
    mo = month_outlook(p, date)
    cur, new = mo["cur"], mo["new"]
    next_line = (f"{mo['date'].month}/{mo['date'].day} {mo['jie']}起入{new['gz']}月：{mo['verdict']}"
                 f"（比起现在的{cur['gz']}月，好日子 {cur['good']}→{new['good']} 天，底气{cur['state']}→{new['state']}）")
    L += [f"- 这个月{cur['gz']}：你的木处在「{cur['state']}」；逐日算下来平均分 {cur['mean']:+.1f}"
          f"（你一年的平均是 {mo['base']:+.1f}，{cur['vs']}），"
          f"好日子（4★以上）{cur['good']} 天，差日子（2★以下）{cur['bad']} 天。",
          f"- {mo['date'].month}/{mo['date'].day} {mo['jie']}起换成{new['gz']}月：{'；'.join(mo['why'])}。",
          f"- 下个月逐日算下来平均分 {new['mean']:+.1f}（{new['vs']}），好日子 {new['good']} 天，差日子 {new['bad']} 天。",
          f"- **结论：{mo['verdict']}。{mo['advice']}。**"]

    L += ["", "---", "传统文化参考，不是预言，事在人为。"]
    title = f"命盘日报 {date.month}/{date.day} 周{WEEK[date.weekday()]} · {a['day_gz']}日 {stars_text(a['stars'])}"
    md = "\n".join(head + L[:2] + [f"本月：{month_line}", "", f"一句话提醒：{tip}"] + L[2:])
    direction = [f"今天求人谈事：挑你所在处{gui}方向的地点，或坐房间{gui}侧（阳贵）"
                 + ("，正合你的喜用方位" if match else ""),
                 f"长期布置：书桌、座位面朝{'、'.join(own)}",
                 "以你所在的地方为中心，用手机指南针看"]
    html = layout.page(
        layout.card(date, a, STARS[a["stars"]], GIST[a["stars"]], a["domains"], a["ji"],
                    [f"{h['name']}【{h['level']}】{h['todo']}" for h in ([early_h] if early_h else []) + good_h],
                    [f"{h['name']} {h['warn']}" for h in bad_h], direction, tip,
                    month_line, next_line),
        layout.wuxing_bars(wuxing_view(p, a)),
        layout.week_calendar(days) + layout.month_calendar(month_days, date),
        notify.md_to_html("\n".join(L)))
    return title, md, html


def load_profiles():
    # 优先用 Secret MINGPAN_PROFILE（JSON），否则用仓库里的 profile.json
    raw = os.environ.get("MINGPAN_PROFILE")
    return json.loads(raw) if raw else json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD，默认今天（曼谷时间）")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不推送")
    ap.add_argument("--html", help="把 HTML 版面另存到这个文件，用来预览")
    args = ap.parse_args()

    date = datetime.date.fromisoformat(args.date) if args.date else datetime.datetime.now(TZ).date()
    for p in load_profiles():
        title, body, html = report(p, date)
        if args.html:
            Path(args.html).write_text(html, encoding="utf-8")
        if args.dry_run:
            print(title + "\n\n" + body)
            continue
        mail, wechat = notify.push(title, body, html=html)
        print(f"{date.isoformat()} | {mail} | {wechat}")


if __name__ == "__main__":
    main()
