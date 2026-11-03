#!/usr/bin/env python3
"""
每日流水线入口（GitHub Actions 调用）
  1. 扫描 → 等待目标收盘日数据，每 10 分钟重扫，最多 N 轮（新浪日线有 1~3 小时延迟）
  2. 数据到位：写入 data/<date>.json
  3. 休市/尚无目标日数据不写入；获取失败或部分更新不足门槛返回失败，不冒充发布成功。
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
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CN_TZ = ZoneInfo("Asia/Shanghai")


def report_date(now=None):
    """午夜后延迟启动仍检查上一收盘日；工作日不等同于交易所交易日。"""
    now = now or datetime.now(CN_TZ)
    day = now.date()
    if now.hour < 15:
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.isoformat()


def validate_snapshot(data):
    """核对日期和计数，防止已有坏文件让备用任务直接跳过。"""
    day = data["data_date"]
    if datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d") != day:
        raise ValueError("数据日期格式无效")
    rows = data["all_results"]
    symbols = [row["symbol"] for row in rows]
    if (not rows or len(symbols) != len(set(symbols))
            or data["valid_count"] != len(rows)
            or any(row["date"] != day for row in rows)):
        raise ValueError("品种重复、日期混排或有效数量不一致")


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

    if args.max_rounds < 1 or args.interval < 0:
        ap.error("轮数必须至少为1，间隔不能为负数")
    today = report_date()
    print(f"目标收盘日 {today}（北京时间15:00前检查上一工作日；节假日以实际数据为准）")
    done = ROOT / "data" / f"{today}.json"
    if done.exists() and not args.force:
        try:
            saved = json.loads(done.read_text(encoding="utf-8"))
            validate_snapshot(saved)
            if saved["data_date"] != today or saved["valid_count"] < 50:
                raise ValueError("已有快照未达到目标日完整性门槛")
        except (ValueError, KeyError, TypeError):
            print("::warning::已有快照未通过检查，重新扫描，不作为完成凭据")
        else:
            print(f"✅ 目标日 {today} 数据已存在并核验（{done.name}），跳过重复扫描")
            gh_output(updated="false", data_date=today)
            return 0
    tmp = ROOT / ".scan_tmp"
    tmp.mkdir(exist_ok=True)
    data = None
    for rnd in range(1, args.max_rounds + 1):
        print(f"\n===== 第 {rnd}/{args.max_rounds} 轮扫描  北京时间 {datetime.now(CN_TZ):%H:%M} =====")
        try:
            data = scan(tmp)
            validate_snapshot(data)
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
        return 1
    n_today = sum(1 for r in data["all_results"] if r["date"] == today)
    if n_today < 50 and not args.force:
        if n_today:
            print(f"::error::目标日 {today} 仅更新 {n_today} 个品种，未达50个门槛，不发布")
            gh_output(updated="false", data_date=data["data_date"])
            return 1
        print(f"::warning::目标日 {today} 尚无数据（可能休市或提供商未更新；最新 {data['data_date']}），未生成新报告")
        gh_output(updated="false", data_date=data["data_date"])
        return 0

    out = ROOT / "data" / f"{data['data_date']}.json"
    out.parent.mkdir(exist_ok=True)
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
