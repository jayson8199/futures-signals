#!/usr/bin/env python3
"""
每日流水线入口（GitHub Actions 调用）
  1. 扫描 → 若数据日期 != 今天（北京时间），每 10 分钟重扫，最多 N 轮（新浪日线有 1~3 小时延迟）
  2. 数据到位：写入 data/<date>.json
  3. 若最终仍非当日：判定休市/未更新，不写数据（退出码 0，后续步骤照常重建网站）
用法：python scanner/run_daily.py [--max-rounds 10] [--interval 600] [--force]
  --force：不管日期是否为今天都保存（用于手动补数/测试）
退出时向 $GITHUB_OUTPUT 写 updated=true/false, data_date=...
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CN_TZ = ZoneInfo("Asia/Shanghai")


def scan(tmp_dir: Path) -> dict:
    r = subprocess.run([sys.executable, str(ROOT / "scanner" / "scan.py"), "--out", str(tmp_dir)],
                       text=True, capture_output=True, timeout=1500)
    sys.stdout.write(r.stdout[-6000:])
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-3000:])
        raise RuntimeError("scan.py 失败")
    return json.loads((tmp_dir / "latest.json").read_text(encoding="utf-8"))


def gh_output(**kv):
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            for k, v in kv.items():
                f.write(f"{k}={v}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rounds", type=int, default=10)
    ap.add_argument("--interval", type=int, default=600)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    today = datetime.now(CN_TZ).strftime("%Y-%m-%d")
    done = ROOT / "data" / f"{today}.json"
    if done.exists() and not args.force:
        print(f"✅ 今日 {today} 数据已存在（{done.name}），本次为备用触发，跳过扫描")
        gh_output(updated="false", data_date=today)
        return 0
    tmp = ROOT / ".scan_tmp"
    tmp.mkdir(exist_ok=True)
    data = None
    for rnd in range(1, args.max_rounds + 1):
        print(f"\n===== 第 {rnd}/{args.max_rounds} 轮扫描  北京时间 {datetime.now(CN_TZ):%H:%M} =====")
        try:
            data = scan(tmp)
        except Exception as e:
            print(f"扫描异常：{e}")
            data = None
        # 新浪收盘后按品种陆续更新：必须等到几乎全部品种（≥50/54）都已是今天的日线，才算数据到位，
        # 否则会把一半品种的昨日数据和另一半的今日数据混在一起
        n_today = sum(1 for r in data["all_results"] if r["date"] == today) if data else 0
        if data and data["valid_count"] >= 40 and (n_today >= 50 or args.force):
            break
        if data:
            print(f"今日({today})数据已更新品种 {n_today}/{data['valid_count']}，未达门槛，{args.interval // 60} 分钟后重试")
        if rnd < args.max_rounds:
            time.sleep(args.interval)

    if not data or data["valid_count"] < 40:
        print("❌ 数据获取失败或有效品种过少，本次不更新")
        gh_output(updated="false", data_date="")
        return 0
    n_today = sum(1 for r in data["all_results"] if r["date"] == today)
    if n_today < 50 and not args.force:
        print(f"⏸ 今日休市或新浪数据未更新完全（今日已更新 {n_today} 个，最新数据日期 {data['data_date']}），跳过")
        gh_output(updated="false", data_date=data["data_date"])
        return 0

    out = ROOT / "data" / f"{data['data_date']}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        sys.path.insert(0, str(ROOT / "scanner"))
        import history
        n = history.merge_from_data(data)
        print(f"📚 长期日线库已合并 {n} 行")
    except Exception as e:
        print(f"[警告] 日线库合并失败（不影响报告）：{e}")
    print(f"✅ 已写入 {out.relative_to(ROOT)}  涨{data['up_count']} 跌{data['down_count']} "
          f"高富帅{data['patterns']['高富帅']['count']} 白富美{data['patterns']['白富美']['count']}")
    gh_output(updated="true", data_date=data["data_date"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
