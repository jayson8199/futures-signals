# 期货八种形态日报 · 自动公示站

每个交易日收盘后自动扫描国内 5 大交易所 54 个期货品种的主力连续合约，按「量·仓·价」三维分类为八种形态，生成日报并发布到 GitHub Pages。

## 运行方式（全自动，无人值守）

| 时间（北京） | 动作 |
|---|---|
| 工作日 16:40 | GitHub Actions 启动，拉取新浪财经日线（akshare） |
| 数据未更新 | 每 10 分钟重扫，最多 10 轮（最晚约 18:30） |
| 数据到位 | 写入 `data/YYYY-MM-DD.json` → 重建网站 → 部署 Pages |
| 休市/未更新 | 自动跳过，不产生错误报告 |

手动触发：GitHub 仓库 → Actions → 「每日扫描并发布」→ Run workflow。

## 目录

```
scanner/scan.py        扫描与八种形态判定（逻辑与原 Kimi 版完全一致）
scanner/run_daily.py   每日流水线：重试、休市保护、写数据
scanner/build_site.py  静态网站生成（首页/历史/趋势/方法说明/公开 JSON）
scanner/events_cal.py  财经事件日历（离线硬编码，每年需更新 FOMC 日期）
data/                  每日扫描结果（JSON，公开）
.github/workflows/     定时任务
```

## 本地运行

```bash
pip install -r scanner/requirements.txt
python scanner/scan.py --out data          # 需能访问新浪财经
python scanner/build_site.py               # 生成 site/
```

免责声明：本项目内容为程序自动生成，仅供学习交流，不构成投资建议。
