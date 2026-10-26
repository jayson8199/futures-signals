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
PO = {frozenset(p) for p in ["子酉", "寅亥", "卯午", "辰丑", "巳申", "未戌"]}
# 六合合出的五行（师傅讲义）：合出喜神才是帮衬，合出忌神是被人情牵着走；午未合火还是土要看八字
HE_WX = {frozenset(k): v for k, v in {"子丑": "土", "寅亥": "木", "卯戌": "火", "辰酉": "金", "巳申": "水"}.items()}
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
# 心态的心理学视角：十神对应的倾向 → 心理学上叫什么、怎么回事、一个有研究支持的具体做法（只管心态和纪律，不给买卖时机）
PSYCH_SCI = {
    "比肩": ("社会比较", "人会不自觉拿自己和别人比，比输了就想追，决定容易被别人的节奏带着走",
             "做决定前写下三条「我自己的理由」，写不出来就先不动"),
    "劫财": ("从众效应", "别人都在做时，大脑会把「大家都这样」当成证据，其实它不是证据",
             "用 24 小时规则：别人拉你做的事，先说「我想一下」，隔一天再答"),
    "正印": ("拖延是情绪问题", "研究发现拖延多半不是懒，而是在躲开做这件事带来的不舒服感",
             "用「如果……就……」的执行意图：比如「如果 10 点到了，我就先做 5 分钟」，开个头比下决心有用"),
    "偏印": ("反思还是反刍", "有新信息时重新想是反思，能让判断更好；没有新信息还在原地打转是反刍，只会更焦虑",
             "每次想推翻时先问一句：我有新信息吗？没有就停；再给思考定个时限，比如 20 分钟，写在纸上而不是在脑子里转"),
    "食神": ("自满和疏忽", "顺的时候大脑会放松警戒，最容易漏掉例行检查",
             "用一张固定的检查清单，顺不顺都照着过一遍"),
    "伤官": ("过度自信", "状态好的时候人会高估自己的判断，容易跳过自己定的规矩",
             "做「事前验尸」：假设这件事已经失败了，写下最可能的三个原因，再决定做不做"),
    "正财": ("短视的损失厌恶", "亏一块钱的难受大约是赚一块钱快乐的两倍，看得越频繁，越容易被难受推着做决定",
             "把看账户的时间固定下来，比如一天一次，其余时间不看"),
    "偏财": ("冷热共情差距", "冷静时的你低估了兴奋时的冲动，兴奋时的你又不记得冷静时的打算",
             "规则在冷静时写好，兴奋时只照做；拿不准就用 10-10-10 问自己：10 分钟、10 个月、10 年后怎么看这件事"),
    "正官": ("不作为偏差", "人怕「做错」胜过怕「没做」，结果该做的事一直不做，其实不做也是一种选择",
             "分清能控制和不能控制的，只为能控制的部分定「够好就行」的标准"),
    "七杀": ("压力下的决策", "压力大时大脑更依赖冲动和习惯，计划能力会下降",
             "先做 1 到 2 分钟「生理叹息」：鼻子连吸两口气，再用嘴慢慢长呼，有研究显示几分钟就能降低紧张，然后再决定"),
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
# 养生具体做法：按当天分量最重的五行，配八段锦对应的式子、一个可以去做的放松，和一个自己能按的穴位
EXERCISE = {
    "金": ("「五劳七伤往后瞧」「攒拳怒目增气力」", "去做个肩颈按摩或推拿",
           "太冲穴（脚背上大脚趾和二脚趾之间往上约两指，疏肝）、风池穴（后脑勺下两侧凹陷，松颈）"),
    "火": ("「摇头摆尾去心火」「背后七颠百病消」", "晚上热水泡脚 15 分钟",
           "内关穴（手腕横纹往上三指、两筋之间，安神）"),
    "土": ("「调理脾胃须单举」「两手托天理三焦」", "饭后散步 15 分钟",
           "足三里（膝盖外侧下四指，健脾胃）"),
    "水": ("「两手攀足固肾腰」「背后七颠百病消」", "早点睡，腰腹注意保暖",
           "涌泉穴（脚底前三分之一凹陷处，睡前按）"),
    "木": ("「两手托天理三焦」「左右开弓似射雕」", "去户外快走半小时",
           "太冲穴（脚背上大脚趾和二脚趾之间往上约两指）"),
}
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


def STAR_CUT(score):
    """星级门槛：按这张命盘两年里的分数分布定（约 17% / 19% / 39% / 15% / 10%）。"""
    return 1 if score <= CUTS[0] else 2 if score <= CUTS[1] else 3 if score < CUTS[2] else 4 if score < CUTS[3] else 5


CUTS = (-4.3, -2.4, 0.5, 2.3)   # 2026-10-25 按梁湘润内核改分后，用 2025-10-26 起两年的分数重定


def wx_group(dm, wx):
    me = GAN_WX[dm]
    if wx == me:
        return "比劫"
    if SHENG[wx] == me:
        return "印"
    if SHENG[me] == wx:
        return "食伤"
    return "财" if KE[me] == wx else "官杀"


def he_wx(pair, month_zhi):
    """六合化出的五行；午未生在夏天（巳午未月）论火，其余论土。"""
    return HE_WX.get(pair) or ("火" if month_zhi in "巳午未" else "土")


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
                "worst": sum(b["stars"] == 1 for b in days),
                "state": season_state(dm, analyse(p, d0 + datetime.timedelta(days=1))["month_gz"][1])}

    cur, new = stats(start, mid), stats(mid, end)
    # 平常水平：前后各半年逐日平均分，用来说这个月、下个月在你自己的一年里算高还是低
    base = sum(analyse(p, date + datetime.timedelta(days=i))["score"] for i in range(-182, 183)) / 365
    for m in (cur, new):
        m["vs"] = ("高于你的平常" if m["mean"] - base >= 0.2 else "低于你的平常" if m["mean"] - base <= -0.2
                   else "和你的平常差不多")
    diff = new["mean"] - cur["mean"]
    # 门槛按这张命盘两年里各月平均分的波动定（各月平均分大多在 -1.8 到 -0.7 之间，波动约 0.25）
    verdict = ("明显转好" if diff >= 0.33 else "略有好转" if diff >= 0.12 else
               "明显转差" if diff <= -0.33 else "略有转差" if diff <= -0.12 else "和这个月差不多")

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
            hw = he_wx(pair, pillars[1][1])
            why.append(f"合{where}，合出{hw}（{xj(hw)}，" + (f"{dom}有人帮衬）" if hw in xi else f"{dom}容易被人情牵着走）"))
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

    def pt(term, plain, pts=None):
        """命盘一栏的一条：术语、白话（含怎么用）、对评分的影响（None 为不计分的底色）。"""
        points.append({"term": term, "plain": plain, "pts": pts})

    def help_or_drain(v):
        return "，这股力量帮你" if v > 0 else "，这股力量耗你" if v < 0 else ""

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
    pt(f"本月{lm}，{lead}当令，你的{me}处在「{state}」",
       "这个月是哪种五行当家，决定你整个月的底气。"
       + ("你底气足，扛得住事。" if state in "旺相" else "你底气弱，整个月以守为主，别逞强。" if state in "囚死"
          else "你底气一般，量力而行。"))
    def gz_desc(gz):
        g1, g2 = ten_god(dm, gz[0])[0], ten_god(dm, CANG[gz[1]][0])[0]
        return f"天干{gz[0]}是你的{g1}（{xj(GAN_WX[gz[0]])}），地支{gz[1]}本气是{g2}（{xj(ZHI_WX[gz[1]])}）"

    if dy:
        pt(f"大运{dy}：{gz_desc(dy)}",
           "大运是这十年的环境。今天的十神要放进这个环境里看。")
        dy_pt = points[-1]
    if ly:
        yg = ten_god(dm, ly[0])[0]
        rel = ("流年天干和大运天干相合，今年把大运的力量拴住了一部分" if dy and frozenset(ly[0] + dy[0]) in GAN_HE else
               "流年天干冲大运天干，今年和这十年的主线在拉扯" if dy and frozenset(ly[0] + dy[0]) in GAN_CHONG else "")
        sui = ("日主去克流年天干，古书叫「日犯岁君」，今年的事要花大力气去接" if KE[GAN_WX[dm]] == GAN_WX[ly[0]] else
               "流年天干来克日主，古书叫「岁伤日干」，压力看着大，实祸较轻" if KE[GAN_WX[ly[0]]] == GAN_WX[dm] else "")
        pt(f"流年{ly}：{gz_desc(ly)}",
           "流年是今年的引动。" + "；".join(x for x in (rel, sui) if x) + ("。" if rel or sui else ""))
    pt(f"天干{gan}是你的{god}（{xj(GAN_WX[gan])}）",
       f"天干是今天摆在明面上的事，主题是{GROUP_THEME[group]}{help_or_drain(sign(GAN_WX[gan]))}。",
       sign(GAN_WX[gan]))
    cang = "、".join(f"{s}{ten_god(dm, s)[0]}" for s in CANG[zhi])
    zpts = sign(ZHI_WX[zhi]) + sum(0.3 * sign(GAN_WX[s]) for s in CANG[zhi][1:])
    pt(f"地支{zhi}属{ZHI_WX[zhi]}（{xj(ZHI_WX[zhi])}），藏{cang}",
       f"地支是今天的底子，主要是{zgod}的力量，管{GROUP_SHORT[zgroup]}{help_or_drain(zpts)}。", zpts)
    good, bad = ADVICE[group]
    extra = {k: [] for k in DOMAINS}
    yi.append(good)
    avoid.append(bad)

    st = stage(dm, zhi)
    score += STAGE_SCORE.get(st, 0)
    pt(f"你（{dm}{me}）在{zhi}是「{st}」",
       f"十二长生看你自己今天的气是强是弱：{STAGE_NOTE[st]}。", STAGE_SCORE.get(st, 0))

    # 天干：流日天干与日主、原局其他天干、大运、流年天干的合冲
    if frozenset(gan + dm) in GAN_CHONG:
        score -= 1
        tags.append("冲身")
        pt(f"流日{gan}冲日主{dm}", f"{god}直接冲着你来，今天压力感明显，遇事多忍一步再回应。", -1)
    elif frozenset(gan + dm) in GAN_HE:
        tags.append("合身")
        pt(f"流日{gan}合日主{dm}", f"合是相互吸引，{GROUP_THEME[group]}方面的人和事会主动找上你，来了先看清再接。", 0)
    he_both, tan_cai = False, False
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
            pt(f"流日{gan}合住{'、'.join(labels)}的{s}（{g2}）", f"被合住就是被绊住、发挥不出来：{msg}。", -0.5 * k)
            tags.append(f"合{g2}")
            # 梁湘润「双边喜忌」：合是两边一起绊住，流日天干自己的力量也打折，只算一次
            own = sign(GAN_WX[gan])
            if own and not he_both:
                he_both = True
                score -= 0.5 * own
                pt(f"{gan}自己也被{s}合住（双边）",
                   f"合是两边互相绊住，不只对方被拴住：今天的{god}（{xj(GAN_WX[gan])}）也有一半力量被{g2}牵走，"
                   + (f"你最需要的这份{GROUP_THEME[group]}会被{GROUP_MEAN[wx_group(dm, GAN_WX[s])]}的事分心，"
                      f"想用它就先把{GROUP_MEAN[wx_group(dm, GAN_WX[s])]}的事放一放。" if own > 0 else
                      f"{GROUP_THEME[group]}带来的消耗今天也轻一些。"), -0.5 * own)
                if own > 0 and wx_group(dm, GAN_WX[s]) == "财" and group == "印":
                    tan_cai = True
                    extra["钱财"].append(f"{gan}被{s}合住（贪财坏印），钱的事今天只记下来，不处理")

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
            # 梁湘润：冲去忌神未必凶。冲到喜用照扣，冲到忌神不扣，闲神按原分值减半
            zw = ZHI_WX[z]
            full = 1.5 if hits_day else 0.7 if natal else 0.5
            cv = -full if zw in xi else 0 if zw in ji else -full / 2
            score += cv
            tags.append(f"冲{z}")
            whom = (f"被冲的{z}属{zw}，是你的忌神：冲掉的是对你不利的东西，变动不一定是坏事，"
                    "有的压力反而会被冲散，所以不扣分；但变动本身要花精力应付。" if zw in ji else
                    f"被冲的{z}属{zw}，是你的喜用：冲伤的是帮你的东西，这一分扣得实在。" if zw in xi else
                    f"被冲的{z}属{zw}，是闲神，只算变动本身，扣一半。")
            pt(f"{zhi}冲{name(z)}", f"冲就是对撞，{domain(z)}方面容易有变动"
               + ("；日支是你自己，今天别拍板大事、别签字。" if hits_day else "，计划留点余地。") + whom, cv)
            if hits_day:
                avoid.append("做重大决定、签字、远行")
                extra["工作"].append("日支被冲，不拍板、不签字")
                extra["家人"].append("日支被冲，和家人有分歧先缓一缓")
            elif "月" in natal:
                extra["工作"].append("冲到工作宫，安排容易变，留好余地")
        elif pair in HE:
            hw = he_wx(pair, pillars[1][1])
            v = (1 if hits_day else 0.5) * sign(hw)
            score += v
            tags.append(f"合{z}")
            if v > 0:
                pt(f"{zhi}与{name(z)}六合，合出{hw}（喜用）",
                   f"合就是相互吸引，合出来的{hw}帮你，{domain(z)}方面有人帮衬、好商量，有事可以今天谈。", v)
                if hits_day:
                    yi.append("和家人、伴侣、合伙人多沟通")
                    extra["家人"].append("日支逢合，和伴侣、家人好商量，有事今天说")
            else:
                pt(f"{zhi}与{name(z)}六合，合出{hw}（{xj(hw)}）",
                   f"合是相互吸引，但合出来的{hw}是你的{xj(hw)}：{domain(z)}方面看着好商量，"
                   "实际容易被人情牵着走，答应别人之前先想清楚自己的底线。", v)
                if hits_day:
                    extra["家人"].append("日支逢合但合出忌神，家人朋友的请求别当场答应")
        if (z != zhi and pair in XING) or (z == zhi and zhi in ZI_XING):
            score -= 0.5
            pt(f"{zhi}{z}相刑", f"刑是互相别扭，{domain(z)}方面容易起摩擦，说话留三分余地。", -0.5)
            avoid.append("说话冲、和人起争执")
            extra["工作"].append(f"{zhi}{z}相刑，说话留三分余地")
        if pair in HAI:
            score -= 0.3
            pt(f"{zhi}{z}相害", f"害是暗中拖累，{domain(z)}方面防暗亏，不轻信、不替人担保。", -0.3)
            avoid.append("轻信他人、替人担保")
            extra["钱财"].append(f"{zhi}{z}相害，不轻信、不替人担保")
        if pair in PO:
            score -= 0.3
            pt(f"{zhi}{z}相破", f"破是把原本好好的事弄出裂缝，{domain(z)}方面谈好的事容易出小变故，关键处落到纸面上。", -0.3)
            avoid.append("口头约定、不留凭据")

    # 三合、三会：流日地支能否和原局、大运、流年、流月凑成局
    for combos, kind in ((SANHE, "三合"), (SANHUI, "三会")):
        for chars, wx in combos:
            if zhi not in chars:
                continue
            have = [c for c in chars if c != zhi and c in zmap]
            grp = wx_group(dm, wx)
            if len(have) == 2:
                full = 2 if kind == "三会" else 1.5
                score += full * sign(wx)
                weight[wx] += full
                tags.append(f"{wx}局")
                pt(f"{zhi}和{name(have[0])}、{name(have[1])}凑成{chars}{kind}{wx}局",
                   f"几个地支拧成一股{wx}的力量，{wx}是你的{grp}，{GROUP_SHORT[grp]}今天被放大{help_or_drain(sign(wx))}。",
                   full * sign(wx))
            elif kind == "三合" and len(have) == 1 and chars[1] in (zhi, have[0]):
                score += 0.5 * sign(wx)
                weight[wx] += 0.5
                pt(f"{zhi}与{name(have[0])}半合{wx}局",
                   f"差一个字没凑齐，{wx}的力量有所加强，{GROUP_SHORT[grp]}多了一些{help_or_drain(sign(wx))}。",
                   0.5 * sign(wx))

    # 十神生态（梁湘润《大流年判例》的十神相互作用）：今天带来的十神和大运这十年的十神放在一起看，
    # 一方要由今天带来（分量 ≥1），另一方今天或大运里有就算。只认对命主有实际意义的几种结构
    wx_of = {wx_group(dm, x): x for x in "木火土金水"}
    env = {wx_group(dm, GAN_WX[dy[0]]), wx_group(dm, GAN_WX[CANG[dy[1]][0]])} if dy else set()

    def today(g):
        return weight[wx_of[g]] >= 1

    def has(g):
        return today(g) or g in env

    def is_ji(g):
        return wx_of[g] in ji

    def is_xi(g):
        return wx_of[g] in xi

    structs = []
    for a_, b_, cond, v, nm, plain in (
            ("官杀", "印", is_ji("官杀") and is_xi("印"), 0.5, "杀印相生",
             "压力上门，印接住：压力经过学习、请教、长辈这一道，转成能用的东西。今天用学、问、写下来化压力，比硬扛省力"),
            ("食伤", "官杀", is_ji("官杀"), 0.3, "食神制杀",
             "压力有本事去对付：靠专业、表达、把事做出来去顶住压力，但做完一两件就停，别把自己掏空"),
            ("食伤", "印", is_ji("食伤") and is_xi("印"), 0.3, "伤官佩印",
             "想法多、话多的时候有印收着：先学再说、先想清楚再出手，才华不会变成口舌"),
            ("比劫", "财", is_ji("财") and is_xi("比劫"), 0.3, "比劫帮身担财",
             "钱和事多，有同伴分担：找信得过的人一起扛，钱的分配先说清楚"),
            ("财", "官杀", is_ji("财") and is_ji("官杀"), -0.5, "财生杀",
             "钱的事变成压力：财去生七杀，账单、贷款、生意上的事今天容易变成心理负担。只守不攻，不添新的财务承诺"),
            ("财", "印", is_ji("财") and is_xi("印") and not tan_cai and not has("比劫"), -0.5, "贪财坏印",
             "钱的事来坏你的印：想静心学习、想清楚的时候容易被钱分心。钱的事只记下来，把整块时间留给想事")):
        if cond and has(a_) and has(b_) and (today(a_) or today(b_)):
            src = "和".join(f"{'今天' if today(g) else '大运'}的{g}" for g in (a_, b_))
            structs.append(nm)
            score += v
            pt(f"十神结构：{nm}（{src}）", plain + "。", v)
            tags.append(nm)

    if dy:
        dy_pt["plain"] += (f"今天凑成了{'、'.join(structs)}，见下面「十神结构」。" if structs
                           else "今天的十神和大运没有凑成特别的结构。")

    # 神煞：分吉神、中性、凶煞。按传统看所临地支的喜忌：吉神临忌神、凶煞临喜神，力量减半
    sha = []
    zxj = xj(ZHI_WX[zhi])

    def add_sha(name, kind, pts, note, use, on_zhi=True):
        hint = ""
        if on_zhi and kind == "吉" and zxj == "忌神":
            pts, hint = pts / 2, "落在忌神上，力量打折"
        elif on_zhi and kind == "凶" and zxj == "喜用":
            pts, hint = pts / 2, "落在喜神上，凶性减轻"
        elif on_zhi and kind == "凶" and zxj == "忌神":
            hint = "落在忌神上，要多当心"
        sha.append({"name": name, "kind": kind, "pts": pts, "note": note, "use": use, "hint": hint})

    if zhi in TIANYI[dm]:
        add_sha("天乙贵人", "吉", 0.5, "遇事有人搭把手", "卡住的事今天开口求人")
        tags.append("贵人")
        yi.append("出门见人、谈事、求助")
        extra["工作"].append("逢天乙贵人，卡住的事可以开口求助")
    if zhi == WENCHANG[dm]:
        add_sha("文昌", "吉", 0, "脑子清楚", "学习、写作、考试")
        tags.append("文昌")
        yi.append("考试、写作、学习")
        extra["学习"].append("逢文昌，脑子清楚，考试、写作都合适")
    if zhi == LU[dm]:
        add_sha("禄神", "吉", 0.5, "心里有底气", "做本职的事")
        tags.append("禄")
    if zhi in {YIMA[_GROUP4[day_zhi]], YIMA[_GROUP4[year_zhi]]}:
        tags.append("驿马")
        if frozenset(zhi + day_zhi) in CHONG:
            add_sha("驿马逢冲", "凶", 0, "奔波难免", "出门注意安全，能不跑就少跑")
            extra["身体"].append("驿马逢冲，出门注意安全")
        else:
            add_sha("驿马", "中", 0, "走动多", "出门办事、拜访")
            yi.append("出行走动")
            extra["工作"].append("逢驿马，适合出门办事")
    if zhi in {TAOHUA[_GROUP4[day_zhi]], TAOHUA[_GROUP4[year_zhi]]}:
        add_sha("桃花", "中", 0, "人缘好，也容易有感情上的牵扯",
                "见人、维护关系，相处和说话有分寸" + ("；落在忌神上，人缘里容易夹着是非" if zxj == "忌神" else ""))
    if zhi in {HUAGAI[_GROUP4[day_zhi]], HUAGAI[_GROUP4[year_zhi]]}:
        add_sha("华盖", "中", 0, "人容易觉得孤单", "独处、研究、读书")
    for table, label, kind, note, use, pts in (
            (JIANGXING, "将星", "吉", "有主见，镇得住场面", "该拿主意的事今天拿", 0),
            (JIESHA, "劫煞", "凶", "防破财、东西被人拿走", "看好财物，不借钱给人", 0),
            (ZAISHA, "灾煞", "凶", "防意外和小伤", "出行、开车慢一点", 0),
            (WANGSHEN, "亡神", "凶", "心思重、容易想多，也防说漏嘴", "说话前想一想，不该说的不说", 0)):
        if zhi in {table[_GROUP4[day_zhi]], table[_GROUP4[year_zhi]]}:
            add_sha(label, kind, pts, note, use)
            if label == "劫煞":
                extra["钱财"].append("逢劫煞，看好财物")
            elif label == "灾煞":
                extra["身体"].append("逢灾煞，出行注意安全")
    if zhi == JINYU[dm]:
        add_sha("金舆", "吉", 0, "有人照应", "出行、办事有人帮")
    if zhi == YANGREN[dm]:
        add_sha("羊刃", "中", 0, "性子急，也更有魄力", "难办的事可以啃，但别冲动、别和人硬碰")
    if zhi in (GUCHEN[year_zhi], GUASU[year_zhi]):
        add_sha("孤辰寡宿", "中", 0, "容易觉得孤单", "独处做事，晚上主动和家人说说话")
    tiao = p.get("tiaohou") or TIAOHOU.get(dm + pillars[1][1])
    if tiao and tiao in (gan, CANG[zhi][0]):
        add_sha("调候", "吉", 0.5, f"见到你命里最需要的{tiao}{GAN_WX[tiao]}，燥气得润", "静下心来想事、定计划", on_zhi=False)
        tags.append("调候")
        extra["身体"].append(f"见{tiao}调候，心容易静下来")
    jishen = [x for x in lunar.getDayJiShen() if x in ("天德", "月德", "天德合", "月德合")]
    if jishen:
        add_sha("、".join(jishen), "吉", 0, "逢凶有解", "办正事", on_zhi=False)
    kong = xunkong(pillars[2])
    if zhi in kong:
        # 梁湘润把空亡当指标读：空掉的是忌神，压力声势大、实祸小；空掉的是喜用，所求容易落空
        if ZHI_WX[zhi] in ji:
            add_sha("空亡", "中", 0, f"{zhi}落在你的空亡（{kong}），今天的{zgod}是空的：压力声势大、实祸小",
                    "觉得被逼到墙角时，先写下真正的损失是多少，多半写不出数字；约定照样多确认一遍", on_zhi=False)
        else:
            add_sha("空亡", "凶", -0.5, f"{zhi}落在你的空亡（{kong}），帮你的东西容易落空，许诺和约定容易落空",
                    "重要的事多确认一遍", on_zhi=False)
        tags.append("空亡")
        extra["工作"].append("落空亡，约定和承诺多确认一遍")
    score += sum(x["pts"] for x in sha)

    # 黄道黑道属择日，不入八字评分（梁湘润：神煞、择日只作指标），黄历一行照列
    # 评分规则（含门槛）2026-10-26 起封存到 2026-12-31，用来和命主每天的实际打分做对照，验证期间不改
    # 门槛按这张命盘两年里的分数分布定（约 17% / 19% / 39% / 15% / 10%），星级是和你自己的平常日子比
    stars = STAR_CUT(score)

    # 把握（梁湘润：最好的批法也只有八成五）：助力和消耗越是一边倒，把握越高；两边打架，把握低
    vals = [x["pts"] for x in points if x["pts"]] + [x["pts"] for x in sha if x["pts"]]
    total = sum(abs(v) for v in vals)
    sure = 5 + round((abs(score) / total if total else 0) * 3.5 * 2) / 2   # 五成到八成五，半成一档

    # 今天的结构一句话：有十神结构先说结构，没有就说天干、地支各是什么十神
    if structs:
        # 挑和今天总分同方向的结构先说：总分为负先说坏结构，为正先说好结构
        sv = {"杀印相生": 1, "食神制杀": 1, "伤官佩印": 1, "比劫帮身担财": 1, "财生杀": -1, "贪财坏印": -1}
        structs.sort(key=lambda x: sv[x] * (1 if score >= 0 else -1), reverse=True)
        gist = {"杀印相生": "压力上门，有印接住：用学、问、写下来化压力，不硬扛，不拍板",
                "食神制杀": "压力上门，靠本事顶住：把事做出来，做完一两件就停",
                "伤官佩印": "想法多，有印收着：先学再说，先想清楚再出手",
                "比劫帮身担财": "钱和事多，有人分担：找信得过的人一起扛",
                "财生杀": "钱的事变成压力：只守不攻，不添新的财务承诺",
                "贪财坏印": "想静心却被钱分心：钱的事只记不办，时间留给想事"}[structs[0]]
    else:
        gist = f"{god}在上、{zgod}在下：{GROUP_THEME[group]}是明面上的事，{GROUP_SHORT[zgroup]}是底子"
    if tan_cai and "贪财坏印" not in structs:
        gist += "；印被财合住，钱的事只记不办"
    # 结构和总分方向相反时（比如有食神制杀但整天压力很重），补一句总的判断，免得只看结构以为是好日子
    gist_agree = bool(structs) and sv[structs[0]] * score >= 0

    heavy = max((w for w in weight if w in ji), key=lambda w: weight[w], default=None)
    body_wx = heavy if heavy and weight[heavy] >= 1.5 else max(weight, key=weight.get)
    body = [HEALTH[body_wx]]
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
        "god": god, "score": score, "stars": stars, "sure": sure, "gist": gist, "structs": structs,
        "gist_agree": gist_agree, "points": points, "sha": sha, "zxj": zxj, "tags": tags,
        "yi": list(dict.fromkeys(yi)), "ji": list(dict.fromkeys(avoid)),
        "body": body, "body_wx": body_wx, "chong_day": frozenset(zhi + day_zhi) in CHONG,
        "psych": PSYCH[god], "weight": weight,
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
    return good, bad, early, night, awake


def review(p, date):
    """当天复盘题里的具体题：好时辰、避开时辰、一个日报没提的对照时辰、当天最重的一条说法。
    返回 [(键, 题目, 选项)]，用来核对日报的具体说法准不准；对照时辰用来看「避开」是不是比平常更容易出事。"""
    a = analyse(p, date)
    good, bad, early, night, awake = hours(p, a["lunar"])
    qs = []
    if good:
        h = good[0]
        qs.append(("good_hour", f"{h['name']}（日报说适合{h['todo']}）", "A 用上了，挺顺　B 用上了，不顺　C 没用上"))
    if bad:
        h = bad[0]
        qs.append(("bad_hour", f"{h['name']}（日报说{h['warn']}）有没有碰上不顺心、摩擦或意外",
                   "A 碰上了　B 没碰上　C 记不清"))
    used = {h["name"] for h in good + bad}
    ctrl = min((r for r in awake if r["name"] not in used), key=lambda r: (abs(r["sc"]), abs(r["idx"] - 6)), default=None)
    if ctrl:
        qs.append(("control_hour", f"{ctrl['name']}（日报没提，用来对照）有没有碰上不顺心、摩擦或意外",
                   "A 碰上了　B 没碰上　C 记不清"))
    rel = [x for x in a["points"] if x["pts"] is not None and not x["term"].startswith(("天干", "地支", "你（"))]
    def short(plain):
        # 去掉开头解释术语的半句和结尾的帮/耗，只留对今天的说法
        body = plain.split("。")[0].split("，这股力量")[0]
        parts = body.split("，")
        return "，".join(parts[1:]) if len(parts) > 1 and parts[0].endswith(("就是对撞", "就是相互吸引", "是互相别扭",
                                                                           "是暗中拖累", "的力量", "没凑齐")) else body

    cands = [(x["pts"], f"{short(x['plain'])}（{x['term']}）") for x in rel]
    cands += [(x["pts"] or (-0.1 if x["kind"] == "凶" else 0.1), f"{x['note']}（{x['name']}）")
              for x in a["sha"] if x["kind"] != "中"]
    if cands:
        neg = [c for c in cands if c[0] < 0]
        pick = min(neg)[1] if neg else max(cands)[1]
        qs.append(("claim", f"日报说「{pick}」，应验了吗", "A 应验了　B 没有　C 说不清"))
    return qs


def sure_text(x):
    n = int(x)
    return "八成五" if x >= 8.5 else "一二三四五六七八九"[n - 1] + "成" + ("半" if x - n else "")


def stars_text(n):
    return "★" * n + "☆" * (5 - n)


def report(p, date):
    a = analyse(p, date)
    lunar = a["lunar"]
    hl_yi = "、".join([x for x in lunar.getDayYi() if x not in SKIP_HUANGLI][:4]) or "诸事平常"
    hl_ji = "、".join([x for x in lunar.getDayJi() if x not in SKIP_HUANGLI][:4]) or "无"
    good_h, bad_h, early_h, night_h, _ = hours(p, lunar)
    reminders = p.get("reminders") or ["传统文化参考，不是预言。"]

    tip = reminders[date.toordinal() % len(reminders)]
    head = [f"**今日：{stars_text(a['stars'])} {STARS[a['stars']]} · 把握约{sure_text(a['sure'])}**", "",
            f"**一句话：{a['gist']}。" + ("" if a["gist_agree"] else GIST[a["stars"]]) + "**", ""]
    L = [f"农历{lunar.getMonthInChinese()}月{lunar.getDayInChinese()} · {a['year_gz']}年 {a['month_gz']}月 "
         f"{a['day_gz']}日" + (f" · 大运{a['dayun']}" if a["dayun"] else ""),
         f"评分 {a['score']:+.1f}（星级是和你自己一年里的日子比）；把握约{sure_text(a['sure'])}"
         "（助力和消耗越一边倒越有把握，两边打架就低；梁湘润说最好的批法也只有八成五）",
         "", "### 一、今天和你的命盘"]
    pts_items = [x for x in a["points"] if x["pts"] is not None]
    gain = sum(x["pts"] for x in pts_items if x["pts"] > 0)
    loss = sum(x["pts"] for x in pts_items if x["pts"] < 0)
    top_g = max(pts_items, key=lambda x: x["pts"], default=None)
    top_l = min(pts_items, key=lambda x: x["pts"], default=None)
    L.append(f"- 先看总账：命盘这一层助力 {gain:+.1f}，消耗 {loss:+.1f}，合计 {gain + loss:+.1f}（神煞另算，黄道吉凶不计分）。"
             + (f"最大的助力是「{top_g['term']}」。" if top_g and top_g["pts"] > 0 else "今天这一层没有明显的助力。")
             + (f"最大的消耗是「{top_l['term']}」。" if top_l and top_l["pts"] < 0 else ""))
    for x in [x for x in a["points"] if x["pts"] is None] + sorted(pts_items, key=lambda x: -abs(x["pts"])):
        tag = "底色" if x["pts"] is None else "±0" if abs(x["pts"]) < 0.05 else f"{x['pts']:+.1f}"
        L.append(f"- 【{tag}】{x['term']}。{x['plain']}")
    if a["sha"]:
        L += ["", f"**神煞**（辅助参考，主次以喜忌为准；今天地支{a['day_gz'][1]}属{ZHI_WX[a['day_gz'][1]]}，是你的{a['zxj']}）"]
        for kind, kname in (("吉", "吉神"), ("中", "中性"), ("凶", "凶煞")):
            for x in (x for x in a["sha"] if x["kind"] == kind):
                w = f"{x['pts']:+.2g} 分" if x["pts"] else "不计分，只作参考"
                L.append(f"- {kname}·{x['name']}（{w}{'，' + x['hint'] if x['hint'] else ''}）：{x['note']}。用法：{x['use']}。")
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
    moves, alt, point = EXERCISE[a["body_wx"]]
    risk, question = a["psych"]
    sci = PSYCH_SCI[a["god"]]
    L += ["", "### 四、身心",
          *[f"- 身体：{x}" for x in a["body"]],
          f"- 动一动：八段锦{moves}，各做 8 次，大约 5 分钟；不想动就{alt}。"
          + ("今天日支被冲，动作放轻放慢，或者干脆选后者。" if a["chong_day"] else ""),
          f"- 按一按：{point}，每处按揉 1 到 2 分钟，有酸胀感就对了。",
          "- 这些是传统养生的做法，不代替看病；哪里一直不舒服，还是去看医生。",
          f"- 心态：{a['god']}日，{risk}。",
          f"- 自检一问：{question}",
          f"- 心理学看：关键词是「{sci[0]}」。{sci[1]}。",
          f"- 试试：{sci[2]}。",
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
                 f"（比起现在的{cur['gz']}月，好日子 {cur['good']}→{new['good']} 天，最差的一星日 {cur['worst']}→{new['worst']} 天，"
                 f"底气{cur['state']}→{new['state']}）")
    L += [f"- 这个月{cur['gz']}：你的木处在「{cur['state']}」；逐日算下来平均分 {cur['mean']:+.1f}"
          f"（你一年的平均是 {mo['base']:+.1f}，{cur['vs']}），"
          f"好日子（4★以上）{cur['good']} 天，差日子（2★以下）{cur['bad']} 天，其中一星日 {cur['worst']} 天。",
          f"- {mo['date'].month}/{mo['date'].day} {mo['jie']}起换成{new['gz']}月：{'；'.join(mo['why'])}。",
          f"- 下个月逐日算下来平均分 {new['mean']:+.1f}（{new['vs']}），好日子 {new['good']} 天，差日子 {new['bad']} 天，其中一星日 {new['worst']} 天。",
          f"- **结论：{mo['verdict']}。{mo['advice']}。**"]

    L += ["", "---", "传统文化参考，不是预言。运气好坏由不得你，怎么应对由你：该做的都做到，结果坦然接受。"]
    title = f"命盘日报 {date.month}/{date.day} 周{WEEK[date.weekday()]} · {a['day_gz']}日 {stars_text(a['stars'])}"
    md = "\n".join(head + L[:2] + [f"本月：{month_line}", "", f"一句话提醒：{tip}"] + L[2:])
    html = layout.page(
        layout.card(date, a, f"{STARS[a['stars']]} · 把握约{sure_text(a['sure'])}",
                    a["gist"] + "。" + ("" if a["gist_agree"] else GIST[a["stars"]]),
                    [f"{h['name']}【{h['level']}】{h['todo']}" for h in ([early_h] if early_h else []) + good_h],
                    [f"{h['name']} {h['warn']}" for h in bad_h], tip,
                    month_line, next_line, f"八段锦{moves}各 8 次；或{alt}"),
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
    ap.add_argument("--date", help="YYYY-MM-DD；默认曼谷时间 18 点前是今天、18 点起是明天（日报前一晚发），--review 默认今天")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不推送")
    ap.add_argument("--html", help="把 HTML 版面另存到这个文件，用来预览")
    ap.add_argument("--review", action="store_true", help="只打印这一天的复盘题（固定五题加当天的具体题），不推送")
    args = ap.parse_args()

    now = datetime.datetime.now(TZ)
    # 日报前一天晚上发：18 点起默认算明天；复盘题问的是今天
    default = now.date() + datetime.timedelta(days=1 if now.hour >= 18 and not args.review else 0)
    date = datetime.date.fromisoformat(args.date) if args.date else default
    for p in load_profiles():
        if args.review:
            qs = review(p, date)
            print(f"**{date.month}/{date.day} 复盘**，回一串像 3BCBA ABBA 的答案（前五个固定题，空格后是今天的具体题）：")
            print("1. 整体：1 很差　2 偏差　3 一般　4 不错　5 很好")
            print("2. 压力：A 很大　B 有一些　C 基本没有")
            print("3. 精力：A 很累或身体不舒服　B 一般　C 精力好")
            print("4. 人际：A 有摩擦或是非　B 平常　C 顺，有人帮忙")
            print("5. 日报：A 有用，照着做了　B 看了，没怎么用上　C 没看")
            for i, (_, q, opts) in enumerate(qs, 6):
                print(f"{i}. {q}：{opts}")
            print("想多说一句就写在最后，比如「3BCBA ABBA 上午开会被批评」。")
            print("KEYS " + "|".join(f"{k}={q}" for k, q, _ in qs))
            continue
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
