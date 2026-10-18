# CLAUDE.md · 给 Claude 的工作须知

> 任何 Claude 对话（网页版、桌面版、Claude Code）打开这个仓库，先读完这一页再动手。
> 这里只写"规矩和地图"，功能细节看 README.md 和各文件开头的说明。

## 1. 项目是什么

- 国内期货的每日信号扫描 → 日报 → 自动发布到公开网站（GitHub Pages）：
  https://jayson8199.github.io/futures-signals/
- 全自动、无人值守：`.github/workflows/` 里的定时任务在 GitHub Actions 上跑，不依赖任何人的电脑。
- 同一个仓库还顺带承载了**命盘日报**（`mingpan/`），和期货无关，只是复用邮件/微信推送通道。
- 项目主人是用户本人（GitHub 账号 jayson8199）。他不是程序员，用 Windows 11，不熟悉命令行。

## 2. 三条铁律

### 2.1 密钥永远不经 Claude 之手
- 所有密钥都在 GitHub 仓库的 **Settings → Secrets and variables → Actions** 里，由用户亲自填写。
  现有 Secrets：`TUSHARE_TOKEN`、`MAIL_SENDER`、`MAIL_PASSWORD`、`MAIL_RECEIVER`、`PUSHPLUS_TOKEN`、`MINGPAN_PROFILE`。
- 代码只通过**环境变量**读取密钥；不要把密钥写进代码、配置、日志、提交信息或聊天记录，也不要让用户把密钥发到对话里。
- 需要新密钥时：在代码里定好环境变量名，然后告诉用户去上面那个页面自己添加（告诉他点哪里）。
- `MINGPAN_PROFILE` 里是用户的个人出生信息，同样只在 Actions 环境变量里存在，不落盘、不打印。

### 2.2 多个 Claude 对话同时在改这个仓库
用户会同时开好几个对话推进不同部分，大家共用 `main` 分支。为了不互相踩：

| 板块 | 文件 | 归属 |
|---|---|---|
| 每日扫描主流程 | `scanner/scan.py` `run_daily.py` `build_site.py` `stats.py` `macd8.py` `history.py` `backfill.py` `notify.py` `oversold_live.py`；`daily.yml` `notify-test.yml` | 「每日扫描」对话 |
| 加权指数 / K 线形态图 | `scanner/weighted*.py` `chart.py` `chart_page.py` `fetch_long.py`；`weighted-rebuild.yml` `bydate-debug.yml` `trend-data.yml` | 「加权指数 / K 线形态图」对话 |
| 二区定律 | `scanner/erqu_*.py`；`erqu.yml` `erqu-live.yml` | 建它的那个对话 |
| 命盘日报 | `mingpan/` 整个目录；`mingpan-daily.yml` | 「命盘」对话（跑在曼谷电脑上） |
| 实验 / 回测 | `scanner/trend_backtest.py` `season_stats.py` `events_cal.py` `probe_sources.py` `tushare_probe.py`；`probe.yml` `tushare-probe.yml`；`experiments/` | 谁建的谁维护，不确定就问用户 |

- 不是自己板块的文件，默认**不改**。确实要改，先告诉用户，让他去知会另一个对话。
- 改 `daily.yml` 或 `scanner/build_site.py` 之前，**必须先告知用户**，得到同意再动。
- 新功能放**独立文件**、独立 workflow，不往现有文件里硬塞。
- 注意隐藏耦合：`oversold_live.py` 和 `trend_backtest.py` 共用同一段信号代码，改一边会影响另一边。
- 推送前先 `git pull --rebase origin main`（Actions 每天也会往 `main` 提交数据）。
- 禁止 force push、禁止改写历史、禁止删别人的文件。提交前看一眼 `git status`，只提交自己改的东西。

### 2.3 不构成投资建议
- 网站和推送里保留免责声明：程序自动生成，仅供学习交流，不构成投资建议。
- 命盘日报**绝不**给加仓、开仓、做 T、买卖时机之类的建议（见 `mingpan/rules.md` 第五节）。
- Claude 自己也一样：做统计、做公示、讲规则，不替用户决定买卖。

## 3. 仓库地图

目录和每个脚本的一句话说明在 `README.md`，这里只补 README 没写的：

- `data/`：**全部由 Actions 生成**，不要手改。
  `data/YYYY-MM-DD.json` 每日快照；`data/history/` 长期日线；`data/weighted/` `data/weighted_tushare/` 加权指数；
  `data/oversold/` 「跌够久」纸面实盘状态；`data/erqu/` 二区定律记录；`data/long/` 趋势回测长数据。
- `experiments/`：实验输出和探测日志，可以参考，不当正式结论。
- `site/`：`build_site.py` 生成，已 gitignore，不提交；GitHub Pages 由 Actions 部署。
- `mingpan/`：`daily.py` 生成日报并推送，`rules.md` 是解读口径，`profile.json` 只是占位，真实资料在 Secret 里。

## 4. 运行机制速记

- 主流程 `daily.yml`：北京时间工作日 17:05 启动（另有 18:35、19:40 两个备用触发，GitHub 定时常延迟或漏发，主触发已出报告时备用会自动跳过）。
  数据到齐门槛 50/54 个品种，不够则每 10 分钟重扫，最多 10 轮；休市或没更新就静默跳过。
  顺序：扫描 → 续接加权指数 → 跌够久纸面实盘 → 提交数据 → `git pull --rebase` → 生成网站 → 推送邮件/微信。
- 手动跑：GitHub 仓库页 → **Actions** → 选工作流 → **Run workflow**。要用户操作时，就这样一步步告诉他点哪。
- 数据源：主力连续用新浪财经（akshare）；加权指数优先 tushare 第三方代理（`weighted.py` 里的 `TS_URLS`，调用方式同官方 tushare，只是换了 `pro._DataApi__http_url`；备用服务器只有 15000 积分，省着用），没有 token 时退回新浪逐合约。
- 推送：邮件走 QQ 邮箱 SMTP，微信走 PushPlus，代码在 `scanner/notify.py`；改推送先用 `notify-test.yml` 试。
- 命盘日报 `mingpan-daily.yml`：每天曼谷时间 06:43 启动，推到同一套邮件/微信。

## 5. 规则的来源（别"顺手优化"）

- **八种形态**（`scan.py`）和 **MACD 八策略**（`macd8.py`）的判定逻辑与原 Kimi 版完全一致，这是用户的硬要求。要改先问。
- **K 线形态图**（`chart.py`）按《王刚期货交易体系手册》（第二版）的规则标注；手册是用户上课笔记整理的，有疑问问用户，不要自己发明规则。
- **跌够久**纸面实盘参数 2026-10-17 已封存，不再调整。
- **二区定律**来自用户上过的课：先回测验证，再决定要不要正式用。
- **命盘**解读按 `mingpan/rules.md`；改口径要同步改 `daily.py`（文件开头有说明）。

## 6. 本仓库之外（别混进来）

- `futures-dashboard`：用户 Windows 电脑桌面上的本地期货分析系统（Vite + React + FastAPI + AKShare），双击 `start.bat` 启动，**独立文件夹，不在本仓库**。
- 用户常去中国，一次 20 天左右，期间访问受限。需要在国内拉数据或跑脚本时，可以交给他电脑上的 Kimi / ZCode；GitHub Actions 在云上跑，不受影响。

## 7. 提交和沟通

- 提交信息用中文，一句话说清改了什么、为什么（沿用现有风格）。小步提交。
- 和用户说话：中文，先说结论再说细节。要他做事就给"点哪里"的步骤，必要时让他截图。不要让他开 PowerShell、不要甩一堆命令。
- 用户在意成本：涉及付费接口、积分、服务器时先说清花销。
- 做完一件事，一两句话说结果就够，不复述过程。
