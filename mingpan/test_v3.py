#!/usr/bin/env python3
"""v3 新增四项的自检：python3 test_v3.py。只查呈现数据，不碰评分。"""
import datetime, json, tempfile, subprocess, sys
from pathlib import Path

import daily as D
import v3 as V

p = json.loads((Path(__file__).parent / "profile.json").read_text(encoding="utf-8"))[0]
n = 0


def ok(cond, msg):
    global n
    n += 1
    if not cond:
        sys.exit("不通过：" + msg)


d = datetime.date
# A：立春换年、表内照表、表外按总纲推、2033 带交运月
ok(V.year_posture(p, d(2027, 2, 3), "丙午")["posture"] == "防守", "2027 立春前仍是丙午年，按总纲防守")
ok(V.year_posture(p, d(2027, 2, 5), "丁未")["posture"] == "平·养", "2027 丁未照表")
ok(V.year_posture(p, d(2026, 11, 5), "丙午")["source"] == "总纲推", "2026 表外要写明是推的")
ok("2033-11" in V.year_posture(p, d(2033, 6, 1), "癸丑")["line"], "2033 写交运月")
ok(V.year_posture(p, d(2034, 6, 1), "甲寅")["posture"] == "表外", "2034 以后不推")
# B：W 等于逐日分量相加，门槛 ±0.5
w = V.water_level(p, d(2026, 11, 5))
manual = 0
for k in range(10):
    x = D.analyse(p, d(2026, 11, 5) - datetime.timedelta(days=k))["weight"]
    manual += x["水"] + x["木"] - x["火"] - x["土"]
ok(abs(w["W"] - round(manual, 2)) < 1e-9 and w["start"] == d(2026, 10, 27), "W 按目标日和前 9 天相加")
ok(w["label"] == "枯水", "11-05 W<-0.5 是枯水")
# C：查表
ok([f["name"] for f in V.flags("丙戌")] == ["丙辛合·水龙头被拧", "库门动"], "丙戌两个旗标")
ok([f["name"] for f in V.flags("甲申")] == ["藤萝系甲·贵人日"], "甲日贵人")
ok([f["name"] for f in V.flags("戊子")] == ["戊癸合·药被夺"], "戊日")
ok([f["name"] for f in V.flags("丁亥")] == ["冲激"] and V.flags("癸未") == [], "亥冲激、癸未无")
# D：保存一次、内容不变才沿用、结果只收三种、只记一次
with tempfile.TemporaryDirectory() as t:
    run = lambda *a: subprocess.run([sys.executable, "v3.py", "annual", *a, "--log-dir", t], capture_output=True, text=True,
                                    cwd=Path(__file__).parent)
    ok(run("record", "--year", "2028", "--result", "发生", "--early").returncode != 0, "没保存不能记")
    ok(run("save").returncode == 0 and "沿用" in run("save").stdout, "重复保存沿用")
    ok(run("record", "--year", "2028", "--result", "发生").returncode != 0, "对账日前不加 --early 不收")
    ok(run("record", "--year", "2028", "--result", "准", "--early").returncode != 0, "结果只收三种")
    ok(run("record", "--year", "2027", "--result", "发生", "--early").returncode != 0, "没预注册的年份不收")
    ok(run("record", "--year", "2028", "--result", "发生", "--early").returncode == 0, "提前记加 --early")
    ok(run("record", "--year", "2028", "--result", "没发生", "--early").returncode != 0, "只记一次")
    ok("已对账 1 / 4" in run("summary").stdout, "汇总")
# 不动评分：v3 只往 compose 结果里加一个键
import compose
b = compose.build(p, d(2026, 11, 5), d(2026, 11, 4))
ok(b["score"] == D.analyse(p, d(2026, 11, 5))["score"] and "v3" in b, "评分不变")
print(f"全部通过，共 {n} 项检查")
