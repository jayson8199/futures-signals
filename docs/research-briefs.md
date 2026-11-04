# AI 研究简报（本机生成，GitHub 发布）

把本站某个交易日的扫描快照整理成小型公开证据包，由本机已登录的 Claude CLI 起草中文研究简报。草稿经独立审阅（Codex）验收后，才出现在网站「研究简报 → AI研究简报」里。量化日报照旧是程序规则生成，和 AI 简报分开展示。

## 工作区约定

- **一台电脑、一个文件夹。** 这台 Windows 电脑是唯一开发环境，源码目录固定为 `C:/Users/17310/Documents/futures-signals-integration`。GitHub Actions 负责定时扫描和发布网站。
- **分工。** Claude 写代码、起草简报；Codex 独立审阅和验收，并负责发布。一次只推进一项。
- **旧系统。** 旧的跨机 AI 投研系统不在本机，只记为“待导入”，本模块不依赖它，也不冒充它。
- 本模块不新增网站、服务、常驻任务或定时任务。简报只在有人手动执行下面的命令时生成。

## 给用户：怎么看、怎么更新

- **看简报：** 网站顶部点「研究简报」，默认就是「AI研究简报」页。旁边的「量化日报」是原来的历史归档，「方法说明」不变。
- 页面开头写着数据日期、生成时间、审阅时间，以及这份简报是不是最新交易日的。如果最新交易日还没有验收过的简报，页面会写「历史简报，最新交易日尚无已验收 AI 简报」。
- **想要新一天的简报：** 告诉 Claude「生成 某日 的 AI 研究简报草稿」，再请 Codex 审阅验收。两步都在本机做，不用开命令行。

## 给维护者：命令

在仓库根目录执行，使用本机 Python 3.12，纯标准库：

```bash
python scanner/research_briefs.py prepare  --date 2026-11-04
python scanner/research_briefs.py generate --date 2026-11-04 [--timeout 300] [--claude <claude.exe>]
python scanner/research_briefs.py validate --date 2026-11-04
python scanner/research_briefs.py accept   --date 2026-11-04 --reviewer Codex --report-sha256 <hash> [--note "..."]
python scanner/research_briefs.py status
python scanner/build_site.py --data data --out site
cd scanner && python -m unittest test_research_briefs test_gold_migration test_daily_delivery
```

各命令说明：

- **prepare**：校验快照并导出证据包，写到 `.local-briefs/<id>/evidence.json`。
- **generate**：调用一次 Claude CLI，写出 `draft.json`；同一日期已有草稿时拒绝再生成。
- **validate**：校验草稿，并打印报告哈希。
- **accept**：审阅者先读草稿，再填入 validate 打印的哈希；会写出 `briefs/accepted/<id>.json`。
- **status**：列出草稿和已验收报告。
- **build_site.py**：建站。只读入通过校验的已验收报告。
- **单元测试**：全部离线；CLI 用假进程模拟。

`.local-briefs/` 已加入 gitignore，里面有证据包、草稿、提示词，以及 CLI 原始回执 `cli-raw-*.jsonl`（含会话信息，只留在本机），都不入库、不发布。只有 `briefs/accepted/` 会入库、上线。合成测试数据只写临时目录。

## 流程与安全边界

1. **prepare 严格校验 `data/<日期>.json`，任何一项不通过都报错退出，不覆盖已有成果：**
   - 文件存在且非空；UTF-8 编码；严格 JSON：拒绝 NaN、Infinity 和重复键。
   - 文件名日期、`data_date` 和逐品种 `date` 三者一致；`scan_date` 不早于数据日期；所有日期都不晚于今天。
   - 品种代码不重复；`valid_count == len(all_results)`，`total_scanned == valid + error`，有效品种至少 50 个（与 daily.yml 门槛一致）。
   - 涨跌家数、强信号数、八种形态的计数和成员，都要与逐品种字段对得上；市场环境要与 20 日动量中位数一致。
   
   如果证据包已存在：内容相同就不动；内容不同则报错，不覆盖。
2. **证据包全部用原值，不计算新指标、不给买卖判断。** 每条事实有固定的 `fact_id`：
   - `cov.valid` / `cov.total` / `cov.errors`：覆盖数量；
   - `breadth.up` / `breadth.down`：涨跌家数；
   - `mkt.mom20_median` / `mkt.regime`：20 日动量中位数和市场环境；
   - `sig.strong`：强信号数；
   - `pat.<形态>`：八种形态计数和成员名；
   - `sym.<代码>`：按 `price_change_pct` 原值取涨幅最大、最小各 3 个品种（同值按代码排序，只用于挑选展示）。
   
   来源写作「本站新浪财经/akshare扫描快照」，并注明未做交易所或第二来源核对。快照只有扫描日期、没有时刻，所以 `scan_time` 为 null。证据包里没有事件日历、宏观数据或新闻。
3. **generate 只把证据包和固定提示词发给模型。** CLI 调用的限制：
   - **先查登录方式。** 发送前先在同样的受限环境里运行官方 `claude auth status --json`，必须同时满足 `loggedIn=true`、`authMethod=claude.ai`、`apiProvider=firstParty`，否则不调用生成、不发送证据包。只读这三个字段，邮箱、组织等其他登录信息不保存、不打印。
   - **调用参数：** `claude --safe-mode --restricted --tools "" --strict-mcp-config --mcp-config {"mcpServers":{}} --no-chrome --disable-slash-commands --no-session-persistence --permission-prompts none --system-prompt <固定> -p --output-format stream-json --verbose`。不用 `--bare`（它会强制 API key），也没有任何跳过权限的参数。
   - **环境变量白名单。** 只传 Windows/POSIX 启动必需的变量（`ENV_ALLOW`）。`ANTHROPIC*`、`CLAUDE*`（含 `CLAUDECODE`、`CLAUDE_CODE_*`）、`AWS_*`、`GOOGLE*`、`AZURE*` 以及 `TUSHARE_TOKEN`、`MAIL_*` 等项目密钥一律不继承。代码不读、不复制登录凭据。
   - **进程边界。** 工作目录是一个空的临时目录，提示词从 stdin 传入，不经过 shell。在 Windows 上，进程以挂起方式创建，先放入专属 Job（设置 KILL_ON_JOB_CLOSE），再恢复运行；在 POSIX 上，进程放在新的进程组里。stdout 最多 4 MB、stderr 最多 256 KB，由后台线程有界读取，stdin 也由后台线程写入。超时、输出超量或进程结束时，只终止这一棵进程树，不影响调用者和其他会话。
   - **返回检查。** init 记录必须明确写出 `apiKeySource == "none"`，`tools` 和 `mcp_servers` 必须是空列表；字段缺失也判为失败。`result.modelUsage` 里要有 init 记录中的同一个模型。
   - **失败处理。** 退出码非零、超时、超量、输出不是 JSON、缺少 init 或 result、`is_error` 不为 false，都判为失败：写 `generate-error-*.json`，原始输出只以 `*.failed.*` 留在本机，不写草稿，不自动重试。CLI 的错误细节不进入任何网页。
   - **模型标识**取自 CLI 返回的 init.model，不猜。
4. **AI 内容（ai）的校验。** 四节为 `summary`、`interpretation`、`uncertainties`、`next_checks`，每节 1 到 3、4 或 5 条（各节上限不同）。每条只有 `text` 和 `evidence_ids` 两个字段：
   - `evidence_ids` 至少 1 个、不重复，且必须是证据包里存在的 fact_id；
   - 文字中不能有尖括号、反引号、斜杠、反斜杠、网址或 `javascript:` 之类的协议、控制字符；
   - 不能出现交易建议类用语，词表见 `BANNED`；
   - **数字绑定到本条引用（`check_numbers`）。** 每条文字里的数字只能来自该条 `evidence_ids` 引用的事实：
     - 数值要符号一致：写了负号的必须是负值，写了正号的必须是正值，不带符号的只能对应非负值，所以负值必须带负号；
     - 也可以是所引用事实的名称、说明里出现的数字，或明确列出的指标口径（`CALIBER_NUMS`：品种事实的「20日」动量和「前 3」个），例如「中证1000」「20日」「各3个」；
     - 日期只允许数据日期本身，其他写法的日期（`11月5日`、`2026年…`、`YYYY-MM-DD`）都会被拒绝；
     - 来源哈希和其他元数据不能作为数值依据。
   - 这项检查只能证明数字有出处，不能证明解释是对的。语义仍由 Codex 逐条审阅。

   网页上的「本站快照依据」由程序根据证据包渲染，模型不复写数值。
5. **accept** 要求审阅者提供自己读过的草稿哈希，并且与草稿当前内容一致。草稿目录里还必须有本机原始回执 `cli-raw-*.jsonl`，其哈希要等于 `generation.raw_receipt_sha256`。审阅者不能为空，也不能是 Claude。同一 brief_id 不重复验收。
6. **建站读入** `briefs/accepted/*.json`。每份逐个校验：
   - 文件名必须是 `brief-YYYY-MM-DD.json`（拒绝路径穿越和子目录）；
   - schema 正确，各层都没有未知或私密字段；
   - `evidence_sha256` 与证据包一致；源文件哈希与 `data/` 现有文件一致；证据包能由源快照重新推导出来；
   - AI 条目合规；`prompt_sha256` 按 `prompt_version` 对应的冻结提示词重新计算后一致（未知版本直接拒绝）；
   - 生成时间按曼谷日期不早于数据日期、不晚于当前时间；审阅时间不早于生成时间；
   - 审阅记录绑定的 `report_sha256` 等于报告当前内容的哈希。
   
   不合格的不发布，只在页面折叠区和 status.html 里列出原因（内部异常只显示类型，不显示细节）；量化日报照常生成。没有合格报告时，页面显示真实的空态，不会用模板补位。所有输出文字都经过 HTML 转义。
7. **当前性。** 每次建站都按两项重新判断：最新快照日期，和本次实际读到的最新已验收简报日期。
   - 报告数据日期等于最新快照日期时，标为「当前」。
   - 否则标为「历史简报：对应数据日期 A；最新扫描日期 B」，后面再接一句：
     - 若 B 已有已验收简报，链接到 B；
     - 若有比 A 新、但不是 B 的已验收简报，链接到那份，并说明 B 尚无；
     - 若这份就是最新的已验收简报，写明 B 尚无已验收 AI 简报。
   
   重建网页不会把旧报告变成今日报告，也不会在已有新报告时声称没有。
8. **页面可读性。** 每条论点下方的「依据」显示事实的中文名称，例如「上涨品种数」，点击可跳到「本站快照依据」表。这张表默认只列「项目 / 数值」，并注明未经交易所核对。fact_id、快照字段、各项哈希、完整模型标识和 CLI 版本都放在折叠的「技术细节」里。

## 时间口径

- `data_date` 是中国期货交易日，沿用快照原值。
- 用户在曼谷，生成时间和审阅时间都按 **Asia/Bangkok** 显示，并标明「曼谷时间」。新写入的记录带 `+07:00`，旧记录的 `+08:00` 原样保留，只在显示时换算。
- 判断“今天、未来日期”用的也是曼谷日期：快照日期不能晚于曼谷今天，生成时间的曼谷日期不能早于数据日期。例如曼谷 11-04 23:30 时，北京已是 11-05 00:30，这时 11-05 的快照仍算未来。
- 网站页脚的“页面生成时间”沿用原站的北京时间，与本模块无关。

## Schema 与哈希语义

- **规范字节** `canonical(obj)`：`json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)` 再做 UTF-8 编码。下面所有内容哈希都是对规范字节取 SHA-256，与文件缩进和换行无关。
- **源文件哈希** `source.sha256`：把文件原始字节中的 CRLF 换成 LF 之后取 SHA-256，等于 git 仓库里的内容。这样 Windows 工作区（`core.autocrlf=true` 会检出成 CRLF）和 Actions（LF）算出的结果相同。2026-11-04 快照的值为 `06e020a65f1ec4ebda12ae7969a30cdbf40970c8404bd5429ca5d1fc2025a8b4`。
- 三个层级：
  - **evidence**（`futures-brief-evidence/1`）：`schema, brief_id, data_date, source{path, sha256, hash_semantics, label, verification, scan_date, scan_time, time_note}, selection_note, facts[{fact_id, group, label, value, unit, source_field, detail?}]`。
  - **report = 草稿**（`futures-brief-report/1`）：`schema, brief_id, data_date, evidence, evidence_sha256, ai{summary, interpretation, uncertainties, next_checks}, generation{generated_at, generator, cli_version, model, prompt_version, prompt_sha256, raw_receipt_sha256}`。
  - **accepted**（`futures-brief-accepted/1`）：`schema, report, review{reviewer, reviewed_at, decision="accepted", report_sha256, note}`。
- **验收绑定。** `review.report_sha256 = sha256(canonical(report))`。验收后只要改动报告里任何字节级内容（文字、引用、证据、生成记录），旧的审阅记录就自动失效。
  - 局限：有仓库写权限的人可以同时改报告和哈希。这种情况要靠 git 历史和 Codex 复验来发现，本模块不做签名。
- **提示词版本。** `PROMPTS` 按版本冻结。`prompt_sha256 = sha256(UTF-8(PROMPTS[prompt_version](evidence)))`，提示词里嵌入的证据包按键排序（`indent=1, sort_keys=True`），所以哈希与证据包在内存中的键顺序无关。
  - `brief-prompt/1`：首份真实草稿（2026-11-04）使用，字节冻结，重算结果为 `eb66f7dc…c0b4`。
  - `brief-prompt/2`：之后新生成时使用，只改了第 2 条规则（数字须来自本条引用、负值带负号）。
  
  系统提示 `SYSTEM_PROMPT` 两版相同。
- `brief_id = brief-<数据日期>`，每个交易日最多一份。

## 回滚范围

涉及的文件：

- 新增：`scanner/research_briefs.py`、`scanner/test_research_briefs.py`、本文档；
- 小改：`scanner/build_site.py`（导航「研究简报」组、归档标题「量化日报」、main 末尾的简报段落）；
- 小改：`scanner/gold_page.py`（`status_body` 增加 `extra_rows` 参数）；
- 小改：`scanner/test_gold_migration.py`（报告页顶部导航期望改为 `../briefs.html`）；
- 小改：README、CLAUDE.md 各一小段，`.gitignore` 一行。

不改 `data/`、信号数学、冻结策略、通知、命盘、workflow。回滚时 revert 对应提交即可。
