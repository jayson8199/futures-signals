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
        elif pair in HE:
            score += 1 if hits_day else 0.5
            tags.append(f"合{z}")
            points.append(f"{zhi}与{name(z)}六合：{domain(z)}方面有人帮衬，好商量。")
            if hits_day:
                yi.append("和家人、伴侣、合伙人多沟通")
        if (z != zhi and pair in XING) or (z == zhi and zhi in ZI_XING):
            score -= 0.5
            points.append(f"{zhi}{z}相刑：{domain(z)}方面容易起摩擦。")
            avoid.append("说话冲、和人起争执")
        if pair in HAI:
            score -= 0.3
            points.append(f"{zhi}{z}相害：{domain(z)}方面提防暗中损耗。")
            avoid.append("轻信他人、替人担保")

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
    if zhi == WENCHANG[dm]:
        tags.append("文昌")
        points.append("今天逢文昌，脑子清楚，适合学习和写作。")
        yi.append("考试、写作、学习")
    if zhi == LU[dm]:
        score += 0.5
        tags.append("禄")
        points.append("今天逢禄神，心里有底气，适合做本职的事。")
    if zhi in {YIMA[_GROUP4[day_zhi]], YIMA[_GROUP4[year_zhi]]}:
        tags.append("驿马")
        if frozenset(zhi + day_zhi) in CHONG:
            points.append("驿马逢冲，奔波难免，出门注意安全。")
        else:
            points.append("今天逢驿马，走动多，适合出行办事。")
            yi.append("出行走动")
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
        points.append(f"今天见{tiao}，这是你命里最需要的调候之{GAN_WX[tiao]}，燥气得润，心容易静下来。")
    jishen = [x for x in lunar.getDayJiShen() if x in ("天德", "月德", "天德合", "月德合")]
    if jishen:
        score += 0.5
        points.append(f"今天是{'、'.join(jishen)}日，逢凶有解，适合办正事。")
    kong = xunkong(pillars[2])
    if zhi in kong:
        score -= 0.5
        tags.append("空亡")
        points.append(f"今天的{zhi}落在你的空亡（{kong}），许诺和约定容易落空，重要的事多确认一遍。")

    ts_type = lunar.getDayTianShenType()
    score += 0.3 if ts_type == "黄道" else -0.3
    # 门槛按这张命盘一年里的分数分布定（约 15% / 20% / 40% / 15% / 10%），星级是和你自己的平常日子比
    stars = 1 if score <= -3.9 else 2 if score <= -2.2 else 3 if score < 0.9 else 4 if score < 2.4 else 5

    heavy = max((w for w in weight if w in ji), key=lambda w: weight[w], default=None)
    body = [HEALTH[heavy] if heavy and weight[heavy] >= 1.5 else HEALTH[max(weight, key=weight.get)]]
    if frozenset(zhi + day_zhi) in CHONG:
        body.append("日支是身体宫，今天被冲，留意睡眠和小磕碰。")

    return {
        "lunar": lunar, "year_gz": ly, "month_gz": lm, "day_gz": ld, "dayun": dy,
        "god": god, "score": score, "stars": stars, "points": points[:n_main], "sha": points[n_main:], "tags": tags,
        "yi": list(dict.fromkeys(yi)), "ji": list(dict.fromkeys(avoid)),
        "body": body, "psych": PSYCH[god], "weight": weight,
    }


def hours(p, lunar):
    pillars = natal_chart(p)
    dm, day_zhi = pillars[2][0], pillars[2][1]
    xi, ji = set(p["xi"]), set(p["ji"])
    rows = []
    for idx, t in enumerate(lunar.getTimes()[1:]):   # 丑时到亥时，再加晚子时
        z = t.getGanZhi()[1]
        luck = t.getTianShenLuck()
        sc, why = (1 if luck == "吉" else -1), [f"{t.getTianShen()}{luck}"]
        wx = ZHI_WX[z]
        if wx in xi:
            sc += 1
            why.append(f"{wx}为喜用")
        elif wx in ji:
            sc -= 1
        if frozenset(z + day_zhi) in CHONG:
            sc -= 1
            why.append("冲日支")
        if z in TIANYI[dm]:
            sc += 1
            why.append("贵人时")
        rng = "23:00-00:59" if z == "子" else f"{t.getMinHm()}-{t.getMaxHm()}"
        rows.append((sc, idx, f"{z}时 {rng}（{'，'.join(why)}）"))
    good = sorted(sorted([r for r in rows if r[0] >= 1], key=lambda r: -r[0])[:3], key=lambda r: r[1])
    bad = sorted(sorted([r for r in rows if r[0] <= -1], key=lambda r: r[0])[:2], key=lambda r: r[1])
    return [r[2] for r in good], [r[2] for r in bad]


def stars_text(n):
    return "★" * n + "☆" * (5 - n)


def report(p, date):
    a = analyse(p, date)
    lunar = a["lunar"]
    hl_yi = "、".join([x for x in lunar.getDayYi() if x not in SKIP_HUANGLI][:4]) or "诸事平常"
    hl_ji = "、".join([x for x in lunar.getDayJi() if x not in SKIP_HUANGLI][:4]) or "无"
    good_h, bad_h = hours(p, lunar)
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
    L += ["", "### 二、宜忌",
          f"- 宜：{'；'.join(a['yi'])}。",
          f"- 忌：{'；'.join(a['ji'])}。",
          f"- 黄历：{lunar.getZhiXing()}日，值{lunar.getDayTianShen()}（{lunar.getDayTianShenType()}），"
          f"{lunar.getXiu()}宿（{lunar.getXiuLuck()}），冲{lunar.getDayChongShengXiao()}，煞{lunar.getDaySha()}。"
          f"宜{hl_yi}；忌{hl_ji}。",
          "", "### 三、时辰与方位（按当地钟点）"]
    if good_h:
        L.append("- 适合谈事、做决定：" + "；".join(good_h))
    if bad_h:
        L.append("- 少做决定、别冲动：" + "；".join(bad_h))
    L.append(f"- 方位：喜神{lunar.getDayPositionXiDesc()}，财神{lunar.getDayPositionCaiDesc()}，"
             f"福神{lunar.getDayPositionFuDesc()}，阳贵{lunar.getDayPositionYangGuiDesc()}。")
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

    jq = lunar.getNextJieQi()
    jd = jq.getSolar()
    left = (datetime.date(jd.getYear(), jd.getMonth(), jd.getDay()) - date).days
    L += ["", "### 节气", f"- 今天{jq.getName()}。" if left == 0 else
          f"- 下一个节气：{jq.getName()} {jd.getMonth()}/{jd.getDay()}（还有{left}天）。"]
    jie = lunar.getNextJie()
    js = jie.getSolar()
    jdate = datetime.date(js.getYear(), js.getMonth(), js.getDay())
    if (jdate - date).days <= 7:
        nm = lunar_of(jdate + datetime.timedelta(days=1)).getMonthInGanZhiExact()
        L.append(f"- {jie.getName()}交节后换成{nm}月，{nm}对你是{ten_god(natal_chart(p)[2][0], nm[0])[0]}月，节奏会跟着变。")

    L += ["", "---", "传统文化参考，不是预言，事在人为。"]
    title = f"命盘日报 {date.month}/{date.day} 周{WEEK[date.weekday()]} · {a['day_gz']}日 {stars_text(a['stars'])}"
    md = "\n".join(head + L[:2] + ["", f"一句话提醒：{tip}"] + L[2:])
    direction = f"阳贵{lunar.getDayPositionYangGuiDesc()}，喜神{lunar.getDayPositionXiDesc()}"
    html = layout.page(
        layout.card(date, a, STARS[a["stars"]], GIST[a["stars"]], a["yi"], a["ji"],
                    [h.split("（")[0] for h in good_h], [h.split("（")[0] for h in bad_h], direction, tip),
        layout.wuxing_bars(a["weight"], set(p["xi"]), set(p["ji"])),
        layout.week_calendar(days),
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
