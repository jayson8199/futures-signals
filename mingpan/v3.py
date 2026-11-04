#!/usr/bin/env python3
"""
命盘日报 v3 新增（2026-11-04 起）：四项只做呈现，不改任何计分、星级、栏目和每日预测实验。
规则来自命主交付的 v3 spec（ZCode 按 2013-2026 逐年回测写定），数值照抄，口径见 rules.md 第十一节。

  A 年度作战路标：2027-2033 姿态表 + 首屏「今年姿态」一行（静态表，按立春换年）
  B 国库水位：近 10 个流日（目标日和前 9 天）的五行分量，W = Σ(水+木) − Σ(火+土)；
              分量复用 daily.analyse 的 weight（天干、地支本气各 1，余气各 0.3）
  C 个人专属旗标：流日干支查表（甲、戊、丙日，辰戌、巳亥日）
  D 年度预测实验台账：2028/2029/2030/2032 预注册，事先写死，年末对账；单独存档，不进每日对照

D 的存档和对账（数据放项目共享文件夹 mingpan/验证/，不进公开仓库，只追加）：
  python3 v3.py annual save    --log-dir DIR                        保存预注册（已存过就沿用，内容变了报错）
  python3 v3.py annual record  --year 2028 --result 发生 [--note "…"] --log-dir DIR
                               结果只收 发生 / 没发生 / 说不清；对账日之前要加 --early 才收
  python3 v3.py annual summary --log-dir DIR
"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

import daily as D

TAG = "v3 新增"

# ---------- A 年度作战路标 ----------
DOCTRINE = "辛酉运（2023–2033）七杀常驻，好比敌军扎营十年：火土流年防守，水木流年进攻。星级是单日尺度，本层是年度尺度，互不替代。"
# 年 → (表里的干支栏, 姿态, 一句话)。照 spec 原文；2030 那句按命主 11-04 的答复定（见 rules.md 第十一节）
ROADMAP = {
    2027: ("丁未", "平·养", "食神在岗木库微根，养身体"),
    2028: ("戊申", "小攻", "申=壬水长生+戊财；跨猴通行证上岗年"),
    2029: ("己酉", "纯守", "又一酉，巳酉金加重，不折腾"),
    2030: ("庚戌", "变动年·慎", "辰戌冲开库=资产大变动；运无水源——只收不扩，不加新的大额承诺"),
    2031: ("辛亥", "转暖", "亥水到位（巳亥冲仍在）"),
    2032: ("壬子", "十年最亮", "壬透+子水，憋了十年的事放行"),
    2033: ("交壬戌", "换挡", "前五年壬水进攻，后五年戌土收手"),
}
FIRE_EARTH, WATER_WOOD = set("火土"), set("水木")


def ganzhi_year(date, year_gz):
    """流年按立春换：目标日的流年干支对应的公历年（立春前还算上一年）。"""
    for y in (date.year, date.year - 1):
        if "甲乙丙丁戊己庚辛壬癸"[(y - 4) % 10] + "子丑寅卯辰巳午未申酉戌亥"[(y - 4) % 12] == year_gz:
            return y
    return date.year


def year_posture(p, date, year_gz):
    """首屏一行：表内年份照表；辛酉运内的表外年份按总纲推（火土防守、水木进攻），并写明是推的。"""
    y = ganzhi_year(date, year_gz)
    g, z = D.GAN_WX[year_gz[0]], D.ZHI_WX[year_gz[1]]
    if y in ROADMAP:
        gz, pos, line = ROADMAP[y]
        if y == 2033:   # 交运月份取命盘资料里的大运表
            nxt = next((m for gz2, m in p.get("dayun", []) if gz2 == "壬戌"), None)
            line += f"（{nxt} 交壬戌运）" if nxt else ""
        return {"year": y, "gz": year_gz, "posture": pos, "line": line, "short": line, "source": "表"}
    if 2023 <= y <= 2033:
        if {g, z} <= FIRE_EARTH:
            pos, why = "防守", f"天干{year_gz[0]}{g}、地支{year_gz[1]}{z}都是火土"
        elif {g, z} <= WATER_WOOD:
            pos, why = "进攻", f"天干{year_gz[0]}{g}、地支{year_gz[1]}{z}都是水木"
        else:
            pos, why = "攻守参半", f"天干{year_gz[0]}{g}、地支{year_gz[1]}{z}，火土和水木各占一边"
        return {"year": y, "gz": year_gz, "posture": pos,
                "line": f"{year_gz}年{why}，按总纲「火土流年防守，水木流年进攻」推（表里没有这一年）",
                "short": f"{''.join(sorted({g, z}))}年，按总纲推（表里没有这一年）", "source": "总纲推"}
    line = "v3 年度路标只覆盖辛酉运和交壬戌那一年（到 2033）"
    return {"year": y, "gz": year_gz, "posture": "表外", "line": line, "short": line, "source": "表外"}


# ---------- B 国库水位 ----------
WINDOW = 10
FULL, DRY = 0.5, -0.5
# 标签照 spec；解释按命主 11-04 的答复写成精力和资源的存量，不写仓位（rules.md 第五节：绝不给加仓建议）
LEVEL_TEXT = {
    "满仓": "近十天水木（你的印和比劫）的补给多过火土的消耗，体有存量：可以多做事、多见人",
    "平": "近十天补给和消耗大致相抵，照常安排",
    "枯水": "近十天火土的消耗连续多过水木的补给，存量在往下走：只守，事情量力、留出余量",
}

LEVEL_SHORT = {"满仓": "补给多过消耗，可以多做事、多见人", "平": "补给和消耗相抵，照常安排", "枯水": "消耗连续多过补给，只守，量力留余量"}


def water_level(p, target, a=None, window=WINDOW):
    """近 window 个流日（目标日和前 window-1 天）：W = Σ(水+木) − Σ(火+土)，分量取 daily.analyse 的 weight。"""
    days = []
    for k in range(window - 1, -1, -1):
        d = target - datetime.timedelta(days=k)
        w = (a if k == 0 and a else D.analyse(p, d))["weight"]
        days.append((d, w["水"] + w["木"], w["火"] + w["土"]))
    plus = sum(x[1] for x in days)
    minus = sum(x[2] for x in days)
    W = round(plus - minus, 2)
    label = "满仓" if W > FULL else "枯水" if W < DRY else "平"
    return {"W": W, "label": label, "text": LEVEL_TEXT[label], "short": LEVEL_SHORT[label], "plus": round(plus, 2), "minus": round(minus, 2),
            "start": days[0][0], "end": target, "window": window,
            "days": [(d, round(x - y, 2)) for d, x, y in days]}


# ---------- C 个人专属旗标 ----------
# 流日天干 / 地支 → (旗标, 行动语, 依据)。照 spec；戊日「逢癸事」和巳亥行动语按命主 11-04 的答复写
GAN_FLAGS = {
    "甲": ("藤萝系甲·贵人日", "主动请教、找平台、见重要人物", "2014/2024 两个甲年全部正分（已验证）"),
    "戊": ("戊癸合·药被夺", "求人、文书、证件类的事（癸是你的偏印）避开当天，或落到纸面", "2023 癸卯应验"),
    "丙": ("丙辛合·水龙头被拧", "不做需要长期补给的决定，防热闹中失资源", "2026 应验"),
}
ZHI_FLAGS = {
    "辰": ("库门动", "资产、置业、库存类事项有异动信号，留意变化、先核对再动", "2015/2018/2024 三次应验"),
    "戌": ("库门动", "资产、置业、库存类事项有异动信号，留意变化、先核对再动", "2015/2018/2024 三次应验"),
    "巳": ("冲激", "巳冲你的日支亥：拍板、签字前多核对条件", "已在报中（冲日支已计分）"),
    "亥": ("冲激", "亥冲你的月支和时支巳：工作安排易被打乱，留出余量", "已在报中（冲月支、时支已计分）"),
}


def flags(day_gz):
    out = []
    if day_gz[0] in GAN_FLAGS:
        out.append(dict(zip(("name", "action", "basis"), GAN_FLAGS[day_gz[0]]), hit=f"天干{day_gz[0]}"))
    if day_gz[1] in ZHI_FLAGS:
        out.append(dict(zip(("name", "action", "basis"), ZHI_FLAGS[day_gz[1]]), hit=f"地支{day_gz[1]}"))
    return out


# ---------- D 年度预测实验台账 ----------
ANNUAL_VERSION = "年度 v1"
REGISTERED = "2026-11-04"
ANNUAL = [   # 预注册：事先写死，年末对账，不凑数
    {"year": 2028, "gz": "戊申", "claim": "有小额进账或资源到位", "basis": "申=水源+财", "check": "2028-12-31"},
    {"year": 2029, "gz": "己酉", "claim": "明显压力/竞争加剧", "basis": "酉杀加重", "check": "2029-12-31"},
    {"year": 2030, "gz": "庚戌", "claim": "资产或大额支出变动", "basis": "辰戌冲库", "check": "2030-12-31"},
    {"year": 2032, "gz": "壬子", "claim": "全年体感明显回暖", "basis": "壬透+子水", "check": "2032-12-31"},
]
RESULTS = ("发生", "没发生", "说不清")


def annual_fingerprint():
    body = json.dumps({"version": ANNUAL_VERSION, "registered": REGISTERED, "items": ANNUAL},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:12]


def annual_view(target):
    rows = []
    for x in ANNUAL:
        check = datetime.date.fromisoformat(x["check"])
        state = "待对账" if target <= check else "到期，待记录"
        rows.append({**x, "state": state, "left": (check - target).days})
    return {"version": ANNUAL_VERSION, "registered": REGISTERED, "fingerprint": annual_fingerprint(), "rows": rows}


def _jsonl(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


def _append(path, rec):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def annual_save(log_dir):
    path = Path(log_dir) / "annual_predictions.jsonl"
    old = _jsonl(path)
    fp = annual_fingerprint()
    if old:
        if old[0]["fingerprint"] != fp:
            sys.exit(f"已存的预注册（指纹 {old[0]['fingerprint']}）和代码里的（{fp}）不一样：预注册不改，要改须开新版本。")
        print(f"已存过（{old[0]['saved_at']}，指纹 {fp}），沿用原记录。")
        return
    import experiment
    rec = {"saved_at": datetime.datetime.now(D.TZ).isoformat(timespec="seconds"), "version": ANNUAL_VERSION,
           "registered": REGISTERED, "fingerprint": fp, "commit": experiment.commit(), "items": ANNUAL}
    _append(path, rec)
    print(f"已保存年度预注册 {len(ANNUAL)} 条，指纹 {fp}。")


def annual_record(log_dir, year, result, note="", early=False):
    if result not in RESULTS:
        sys.exit(f"结果只收：{' / '.join(RESULTS)}")
    item = next((x for x in ANNUAL if x["year"] == year), None)
    if not item:
        sys.exit(f"{year} 年没有预注册的预测（只有 {', '.join(str(x['year']) for x in ANNUAL)}）。")
    if not _jsonl(Path(log_dir) / "annual_predictions.jsonl"):
        sys.exit("还没保存预注册，先运行 annual save。")
    today = datetime.datetime.now(D.TZ).date()
    if today < datetime.date.fromisoformat(item["check"]) - datetime.timedelta(days=30) and not early:
        sys.exit(f"{year} 年的对账日是 {item['check']}，现在记太早；确实要提前记加 --early。")
    path = Path(log_dir) / "annual_observations.jsonl"
    if any(r["year"] == year for r in _jsonl(path)):
        sys.exit(f"{year} 年已经记过，年度台账只记一次，不覆盖。")
    _append(path, {"recorded_at": datetime.datetime.now(D.TZ).isoformat(timespec="seconds"), "year": year,
                   "claim": item["claim"], "result": result, "note": note, "early": early,
                   "fingerprint": annual_fingerprint()})
    print(f"{year}：{item['claim']} → {result}")


def annual_summary(log_dir):
    obs = {r["year"]: r for r in _jsonl(Path(log_dir) / "annual_observations.jsonl")}
    saved = _jsonl(Path(log_dir) / "annual_predictions.jsonl")
    print(f"年度预测实验台账 {ANNUAL_VERSION}（预注册 {REGISTERED}，指纹 {annual_fingerprint()}，"
          + (f"已保存 {saved[0]['saved_at']}）" if saved else "还没保存）"))
    for x in ANNUAL:
        r = obs.get(x["year"])
        print(f"- {x['year']} {x['gz']}：{x['claim']}（{x['basis']}）→ "
              + (f"{r['result']}" + (f"，{r['note']}" if r["note"] else "") if r else f"待对账（{x['check']}）"))
    done = [r["result"] for r in obs.values()]
    print(f"已对账 {len(done)} / {len(ANNUAL)}：" + "，".join(f"{k} {done.count(k)}" for k in RESULTS) + "。不算准确率，条数太少。")


def build(p, target, a):
    """给 compose 用：四项 v3 新增的数据，都不参与评分。"""
    return {"tag": TAG, "doctrine": DOCTRINE,
            "posture": year_posture(p, target, a["year_gz"]),
            "roadmap": [(y, *v) for y, v in ROADMAP.items()],
            "water": water_level(p, target, a),
            "flags": flags(a["day_gz"]),
            "annual": annual_view(target)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["annual"])
    ap.add_argument("action", choices=["save", "record", "summary"])
    ap.add_argument("--log-dir", required=True)
    ap.add_argument("--year", type=int)
    ap.add_argument("--result")
    ap.add_argument("--note", default="")
    ap.add_argument("--early", action="store_true")
    a = ap.parse_args()
    if a.action == "save":
        annual_save(a.log_dir)
    elif a.action == "record":
        annual_record(a.log_dir, a.year, a.result, a.note, a.early)
    else:
        annual_summary(a.log_dir)


if __name__ == "__main__":
    main()
