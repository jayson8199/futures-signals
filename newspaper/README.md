# 晨读报

用户的个人每日报纸：每天早上由 Claude 定时任务搜集新闻、按“事实 → 谁得利谁受损 → 底层逻辑 → 对你意味着什么”拆解，并入期货扫描摘要和生活提醒，排成一页，推送到微信。

- 生成：Claude 定时任务「晨读报·每日出报」（曼谷时间每天 06:47），不在本仓库里跑代码。
- 版式：`newspaper/template.html`，只用行内样式（PushPlus/微信会过滤 `<style>`）。
- 推送：`.github/workflows/newspaper-push.yml`，PushPlus html 模板，复用 Secret `PUSHPLUS_TOKEN`。
- 隐私：本仓库和网站是公开的。报纸正文（含生活提醒等个人内容）**不提交到仓库、不发布到 GitHub Pages**，只经 workflow 输入直接发到微信；仓库里只放模板和说明。
- 归属：本目录和 `newspaper-push.yml` 归「晨读报」对话维护。
