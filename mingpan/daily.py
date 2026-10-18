#!/usr/bin/env python3
"""
命盘日报：算出今天相对命盘的流日信息，按 rules.md 的规则生成正文，经 notify.py 推送。
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

import notify

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Bangkok")

GAN_WX = dict(zip("甲乙丙丁戊己庚辛壬癸", "木木火火土土金金水水"))
GAN_YANG = {g: i % 2 == 0 for i, g in enumerate("甲乙丙丁戊己庚辛壬癸")}
ZHI_WX = dict(zip("子丑寅卯辰巳午未申酉戌亥", "水土木木土火火土金金土水"))
SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

CHONG = {frozenset(p) for p in ["子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥"]}
HE = {frozenset(p) for p in ["子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未"]}
HAI = {frozenset(p) for p in ["子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌"]}
XING = {frozenset(p) for p in ["寅巳", "巳申", "寅申", "丑戌", "戌未", "丑未", "子卯"]}
TIANYI = {"甲": "丑未", "戊": "丑未", "庚": "丑未", "乙": "子申", "己": "子申",
          "丙": "亥酉", "丁": "亥酉", "壬": "卯巳", "癸": "卯巳", "辛": "寅午"}
YIMA = {"申": "寅", "子": "寅", "辰": "寅", "寅": "申", "午": "申", "戌": "申",
        "巳": "亥", "酉": "亥", "丑": "亥", "亥": "巳", "卯": "巳", "未": "巳"}
WENCHANG = dict(zip("甲乙丙丁戊己庚辛壬癸", "巳午申酉申酉亥子寅卯"))

# 黄历里丧葬、祭祀类的条目和日常无关，推送时略去
SKIP_HUANGLI = {"入殓", "破土", "启钻", "安葬", "除服", "成服", "移柩", "修坟", "立碑", "谢土",
                "祭祀", "斋醮", "馀事勿取", "诸事不宜"}

ADVICE = {
    "比劫": ("帮身", "见朋友、谈合作、运动", "借钱给人、和人争利"),
    "印": ("生身", "读书学习、拜访长辈和老师、处理文书", "拖延空想"),
    "食伤": ("泄身", "写东西、做研究、果断处理积压的事", "口舌争执、熬夜耗神"),
    "财": ("耗身", "记账理财、守住已有的", "大额支出、冒进投机"),
    "官杀": ("克身", "低调办事、找人帮忙、守规矩", "硬碰硬、冒风险"),
}


def ten_god(day_master, gan):
    me, other = GAN_WX[day_master], GAN_WX[gan]
    same = GAN_YANG[day_master] == GAN_YANG[gan]
    if other == me:
        return ("比肩" if same else "劫财"), "比劫"
    if SHENG[other] == me:
        return ("偏印" if same else "正印"), "印"
    if SHENG[me] == other:
        return ("食神" if same else "伤官"), "食伤"
    if KE[me] == other:
        return ("偏财" if same else "正财"), "财"
    return ("七杀" if same else "正官"), "官杀"


def natal_chart(p):
    if p.get("pillars"):
        return p["pillars"]
    y, m, d = map(int, p["birth_date"].split("-"))
    hh, mm = map(int, p["birth_time"].split(":"))
    ec = Solar.fromYmdHms(y, m, d, hh, mm, 0).getLunar().getEightChar()
    return [ec.getYear(), ec.getMonth(), ec.getDay(), ec.getTime()]


def today_info(date):
    lunar = Solar.fromYmdHms(date.year, date.month, date.day, 8, 0, 0).getLunar()
    return {
        "lunar": f"农历{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}",
        "day_gz": lunar.getDayInGanZhi(),
        "huangli_yi": lunar.getDayYi(),
        "huangli_ji": lunar.getDayJi(),
        "xishen": lunar.getDayPositionXiDesc(),
        "yanggui": lunar.getDayPositionYangGuiDesc(),
    }


def analyse(p, t):
    pillars = natal_chart(p)
    dm, day_zhi = pillars[2][0], pillars[2][1]
    natal_zhi = [x[1] for x in pillars]
    gan, zhi = t["day_gz"][0], t["day_gz"][1]
    god, group = ten_god(dm, gan)
    xi, ji = set(p["xi"]), set(p["ji"])

    score, notes, yi, avoid = 0, [], [], []
    for wx in (GAN_WX[gan], ZHI_WX[zhi]):
        score += 1 if wx in xi else -1 if wx in ji else 0

    effect, good, bad = ADVICE[group]
    notes.append(f"{gan}是你的{god}，主{effect}")
    yi.append(good)
    avoid.append(bad)

    pair = frozenset(zhi + day_zhi)
    if pair in CHONG:
        score -= 1
        notes.append(f"{zhi}冲你的日支{day_zhi}，心绪容易起伏")
        avoid.append("做重大决定、远行")
    elif pair in HE:
        score += 1
        notes.append(f"{zhi}和你的日支{day_zhi}相合，身边有人帮衬")
        yi.append("和家人、伴侣、合伙人多沟通")
    for z in sorted(set(natal_zhi) - {day_zhi}):
        if frozenset(zhi + z) in CHONG:
            notes.append(f"{zhi}冲原局{z}，事情多变动")
    if any(frozenset(zhi + z) in XING for z in natal_zhi):
        avoid.append("说话冲、和人起争执")
    if any(frozenset(zhi + z) in HAI for z in natal_zhi):
        avoid.append("轻信他人")

    if zhi in TIANYI[dm]:
        score += 1
        notes.append("今天逢天乙贵人")
        yi.append("出门见人、谈事、求助")
    if zhi == YIMA[day_zhi]:
        if pair in CHONG:
            notes.append("驿马逢冲，奔波难免，出门注意安全")
        else:
            yi.append("出行走动")
    if zhi == WENCHANG[dm]:
        yi.append("考试、写作、学习")

    level = "旺" if score >= 2 else "弱" if score <= -1 else "平"
    return {"level": level, "notes": notes, "yi": yi, "ji": avoid}


def template_text(p, t, a, date):
    reminders = p.get("reminders") or ["传统文化参考，不是预言。"]
    tip = reminders[date.toordinal() % len(reminders)]
    hl_yi = "、".join([x for x in t["huangli_yi"] if x not in SKIP_HUANGLI][:4]) or "诸事平常"
    hl_ji = "、".join([x for x in t["huangli_ji"] if x not in SKIP_HUANGLI][:4]) or "无"
    lines = [
        f"【{p['name']}】",
        f"今日概况：{t['day_gz']}日，整体{a['level']}。" + "；".join(a["notes"]) + "。",
        f"宜：{'；'.join(a['yi'])}。",
        f"忌：{'；'.join(a['ji'])}。",
        f"贵人方位：喜神{t['xishen']}，阳贵{t['yanggui']}。黄历宜{hl_yi}，忌{hl_ji}。",
        f"一句话提醒：{tip}",
    ]
    return "\n".join(lines)


def load_profiles():
    # 优先用 Secret MINGPAN_PROFILE（JSON），否则用仓库里的 profile.json
    raw = os.environ.get("MINGPAN_PROFILE")
    return json.loads(raw) if raw else json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD，默认今天（曼谷时间）")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不推送")
    args = ap.parse_args()

    date = datetime.date.fromisoformat(args.date) if args.date else datetime.datetime.now(TZ).date()
    t = today_info(date)
    body = "\n\n".join(template_text(p, t, analyse(p, t), date) for p in load_profiles())
    title = f"命盘日报 {date.isoformat()}（{t['lunar']} · {t['day_gz']}日）"
    if args.dry_run:
        print(title + "\n\n" + body)
        return
    mail, wechat = notify.push(title, body)
    print(f"{date.isoformat()} {t['day_gz']}日 | {mail} | {wechat}")


if __name__ == "__main__":
    main()
