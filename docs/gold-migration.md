# 黄金专题迁移（第一版）

把原独立的「黄金研究台」里可公开的描述性功能并入本站，同时把顶部导航收拢为五个栏目。原研究台保持不变（不删除、不跳转），其模型研究与历史版本（vintage）数据管线归档只读，不在本版范围内。

## 模块

| 文件 | 作用 |
|---|---|
| `scanner/gold_page.py` | 生成 `gold.html`（黄金专题）、`research.html`（品种研究入口）、`strategies.html`（策略验证入口）、`status.html`（运行状态）；快照严格校验；每次建站把资产复制到 `site/assets/gold/` |
| `scanner/gold_snapshot.py` | 一次性导入：从原研究台目录读取已发布快照，生成 `scanner/assets/gold/*.json`。不联网、不自动运行 |
| `scanner/assets/gold/analytics.mjs` | 纯函数：CSV 校验、历史统计、宏观观测查找、快照校验（恰好三个序列）、风险预算 |
| `scanner/assets/gold/gold.mjs` | 页面交互：GC=F 折线图（20/60/120 条）、数据来源与质量审计、宏观观测卡片/图表/观察日过滤、CSV 导入与示例下载、风险预算计算器 |
| `scanner/assets/gold/gc_snapshot.json` | Yahoo Finance GC=F 日线冻结快照（只保留日期与收盘），最近完整日线 2026-10-30 |
| `scanner/assets/gold/macro3.json` | FRED 三个序列 DFII10 / DTWEXBGS / DCOILWTICO 冻结快照 |
| `scanner/build_site.py` | 五栏目顶部导航 + 栏目内二级导航；调用 `gold_page`；归档页注明为程序生成的量化日报 |
| `scanner/test_gold_migration.py`、`scanner/test_gold_assets.mjs` | 离线回归测试 |

## 口径

- **两个标的分开**：上期所 AU0（人民币元/克，新浪主力连续，随每日扫描自动更新，链接 `chart.html?s=AU0`）与 COMEX GC=F（美元/金衡盎司，冻结快照）。不合并、不换算。
- **冻结快照**：GC=F 与三个宏观序列是 2026-11-01 抓取后一次性导入的，页面写明数据日期与抓取时间，不自动更新，没有新的抓取任务。
- **VIX 不收录**：原研究台的 VIXCLS 版权属 Cboe，公开站只在 `excludedSeries` 里记录剔除原因，不含任何数值。共同观测日按三个序列重新计算。
- **不做预测**：`trainingEligible` 为 false；页面不显示模型、预测、因子权重。
- **用户输入只在浏览器内存**：导入的 CSV 与风险预算输入不上传、不保存。
- 所有资源都是同源相对路径，没有 iframe 或外部脚本。
- 页面顶部只用简短说明（AU0 每日更新、GC=F 与宏观为历史快照、非实时、无预测模型）；来源、抓取时间、哈希与导入提交放在折叠的「数据来源与版本」里。

## 运行

```bash
cd scanner
python -m unittest test_gold_migration test_daily_delivery   # Python 回归（会在临时目录建站，不改 data/）
node test_gold_assets.mjs [site 目录]                         # 前端纯函数；给出 site 目录时再跑假 DOM 交互检查
python build_site.py --data ../data --out ../site             # 本地建站；gold 页面用 ES module，需用 http 服务打开，不能直接双击
```

更新冻结快照（只在需要换新快照时手动做）：先在原研究台更新并发布快照，然后

```bash
python scanner/gold_snapshot.py --source <原研究台目录> --commit <原研究台提交号>
```

脚本会校验后覆盖 `scanner/assets/gold/*.json`；再跑上面的测试。

## 第一版验收标准

1. `gold.html` 由每日建站生成，显示 AU0 最新数据日期与形态、GC=F 快照日期与来源、三个宏观序列；桌面 1280 与手机 390 宽度可用。
2. 20/60/120 周期切换、观察日过滤、CSV 导入（含错误提示）、示例下载、风险预算（含无效输入提示）可用。
3. 公开资产中没有 VIX 数值、没有私人说明或个人资料。
4. 顶部只有五个栏目，原有页面都能从二级导航到达，旧网址和 `reports/` 历史日报里的 `../` 链接都有效。
5. `status.html` 只显示实际数据日期与生成时间，运行结果指向 GitHub Actions。
6. 多次建站后 `site/assets/gold/` 都在；`data/` 不被修改。快照缺失或校验失败时日报照常生成，`gold.html` 改为「暂不可用」说明页（保留 AU0，不发布 `assets/gold/`，链接仍有效），状态页注明失败。
7. 风险预算只接受十进制数字：金额 0–1 万亿元，风险比例 0–100%，每手止损 0.01 元–1 万亿元；空白、溢出或手数超出安全整数时显示「检查输入」，不会出现 Infinity。

## 回滚范围

只涉及：`scanner/build_site.py` 的导航、归档说明与 `main()` 末尾的黄金段落；新增文件 `scanner/gold_page.py`、`scanner/gold_snapshot.py`、`scanner/assets/gold/`、两个测试、本文档和 README 两行。回滚 = revert 对应提交；不涉及 `data/`、信号计算、推送、策略记录或 workflow。
