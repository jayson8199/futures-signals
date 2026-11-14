"""
黄金专题与导航枢纽页面，供 build_site.py 调用：
  gold.html        黄金专题（上期所 AU0 最新扫描 + Yahoo GC=F 冻结历史快照 + 三个宏观观测 + CSV 导入 + 风险预算）
  research.html    品种研究入口；strategies.html 策略验证入口；status.html 运行状态（只列实际数据日期与生成时间）
冻结快照在 scanner/assets/gold/（由 gold_snapshot.py 一次性导入），每次建站复制到 site/assets/gold/。
"""
import json
import shutil
from html import escape
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parent / "assets" / "gold"
ASSET_FILES = ["analytics.mjs", "gold.mjs", "gc_snapshot.json", "macro3.json"]
MACRO_IDS = ["DFII10", "DTWEXBGS", "DCOILWTICO"]
ACTIONS_URL = "https://github.com/jayson8199/futures-signals/actions"


def _is_date(d):
    import datetime as dt
    try:
        return isinstance(d, str) and len(d) == 10 and dt.date.fromisoformat(d).isoformat() == d
    except ValueError:
        return False


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def validate_gold(g):
    """GC=F 快照结构校验，不通过抛 ValueError"""
    if g.get("schemaVersion") != 1 or g.get("symbol") != "GC=F" or g.get("currency") != "USD" or g.get("frequency") != "daily":
        raise ValueError("GC=F 快照规格不符")
    p = g.get("prices") or []
    if len(p) < 2 or len(p) != g.get("quality", {}).get("validRows"):
        raise ValueError("GC=F 记录数与质量统计不一致")
    for i, r in enumerate(p):
        if not _is_date(r.get("date")) or not _num(r.get("close")) or r["close"] <= 0 or (i and r["date"] <= p[i - 1]["date"]):
            raise ValueError(f"GC=F 第 {i} 条记录无效或乱序")
    if p[-1]["date"] != g.get("asOf"):
        raise ValueError("GC=F asOf 与最后记录不一致")
    return True


def validate_macro(m, gold):
    """宏观快照严格校验：恰好三个序列、同一黄金原始哈希、共同观测日重新计算一致；不通过抛 ValueError"""
    if m.get("schemaVersion") != 2 or m.get("trainingEligible") is not False:
        raise ValueError("宏观快照版本或训练资格不符")
    if m.get("goldRawSha256") != gold.get("rawSha256") or m.get("goldAsOf") != gold.get("asOf"):
        raise ValueError("宏观快照与黄金快照哈希/日期不匹配")
    series = m.get("series") or []
    if m.get("seriesIds") != MACRO_IDS or [s.get("id") for s in series] != MACRO_IDS:
        raise ValueError("宏观序列必须恰好为 " + "/".join(MACRO_IDS))
    for s in series:
        obs = s.get("observations") or []
        if len(obs) <= 20:
            raise ValueError(f"{s['id']} 观测不足")
        for i, r in enumerate(obs):
            if not _is_date(r.get("date")) or not _num(r.get("value")) or r["date"] > m["goldAsOf"] or (i and r["date"] <= obs[i - 1]["date"]):
                raise ValueError(f"{s['id']} 第 {i} 条观测无效、乱序或晚于黄金快照")
    sets = [{r["date"] for r in s["observations"]} for s in series]
    common = [p["date"] for p in gold["prices"] if all(p["date"] in st for st in sets)]
    if common != m.get("commonObservationDates") or m.get("goldObservationCount") != len(gold["prices"]):
        raise ValueError("共同观测日或黄金记录数与重新计算结果不一致")
    if "VIX" in json.dumps(series, ensure_ascii=False).upper():
        raise ValueError("公开宏观序列中不得含 VIX")
    return True


def load_snapshots(asset_dir=None):
    asset_dir = asset_dir or ASSET_DIR
    gold = json.loads((asset_dir / "gc_snapshot.json").read_text(encoding="utf-8"))
    macro = json.loads((asset_dir / "macro3.json").read_text(encoding="utf-8"))
    validate_gold(gold)
    validate_macro(macro, gold)
    return gold, macro


def copy_assets(out: Path, asset_dir=None):
    """只写 site 下自有子目录 assets/gold/"""
    asset_dir = asset_dir or ASSET_DIR
    dst = out / "assets" / "gold"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ASSET_FILES:
        shutil.copy(asset_dir / name, dst / name)
    return dst


CSS = """
.hub{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px;margin-bottom:12px}
.hub a{display:block;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px 16px;color:var(--ink)}
.hub a:hover{border-color:var(--cyan);text-decoration:none}.hub b{display:block;color:var(--cyan);margin-bottom:4px;font-size:14px}.hub span{color:var(--muted);font-size:12.5px}
.g-split{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
.g-tag{display:inline-block;font-size:11px;padding:1px 8px;border-radius:3px;border:1px solid var(--line2);color:var(--muted);margin-left:6px;font-family:var(--mono)}
.g-kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:10px 0}.g-kpi>div{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:9px 12px;min-width:0}
.g-kpi .k{display:block;font-size:11px;color:var(--muted)}.g-kpi .v{font-size:20px;font-weight:700;font-family:var(--mono);overflow-wrap:anywhere}
.g-row{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px}
.g-btn,.g-up{font:inherit;font-size:12.5px;color:var(--ink);background:var(--panel2);border:1px solid var(--line2);border-radius:4px;padding:5px 11px;cursor:pointer}
.g-btn.on{background:var(--cyan);border-color:var(--cyan);color:var(--panel)}.g-btn:disabled{opacity:.5;cursor:default}
.g-svg{width:100%;height:auto;display:block;margin-top:8px}
.g-leg{display:flex;justify-content:space-between;font-size:11.5px;color:var(--muted);font-family:var(--mono)}
.g-q{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}.g-q>div{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:8px 10px}
.g-q .k{display:block;font-size:11px;color:var(--muted)}.g-q b{font-family:var(--mono);font-size:17px}
.g-small{font-size:12px;color:var(--muted);overflow-wrap:anywhere}.g-small p{margin:4px 0}
.g-note{background:var(--amber-dim);border-left:3px solid var(--amber);padding:9px 12px;border-radius:0 4px 4px 0;font-size:13px;margin-bottom:12px}
.mgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:10px 0}
.mcard{font:inherit;text-align:left;background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:10px 12px;color:var(--ink);cursor:pointer;min-width:0}
.mcard.on{border-color:var(--cyan)}.mcard .k{display:block;font-size:11.5px;color:var(--muted)}.mcard b{display:block;font-size:22px;font-family:var(--mono);margin:4px 0}
.mcard small{display:block;font-size:11.5px;color:var(--muted)}.mcard .delta{color:var(--amber)}
.g-form{display:grid;grid-template-columns:1fr 1fr;gap:10px}.g-form label{font-size:12px;color:var(--muted)}
.g-form input,#m-date{display:block;width:100%;margin-top:4px;font:inherit;font-size:13px;color:var(--ink);background:var(--panel2);border:1px solid var(--line2);border-radius:4px;padding:6px 8px}
#m-date{width:auto;display:inline-block}
.g-tbl table{min-width:0}
@media (max-width:720px){.g-split,.g-form{grid-template-columns:1fr}.g-kpi{grid-template-columns:repeat(2,1fr)}.g-q{grid-template-columns:repeat(2,1fr)}.mgrid{grid-template-columns:1fr}}
"""


def _au0_panel(latest, avail_syms):
    it = next((i for i in (latest or {}).get("all_results", []) if i.get("symbol") == "AU0"), None)
    if not it:
        return "<div class='card'><h3>上期所黄金 AU0 · 每日扫描</h3><div class='muted'>最新日报中没有 AU0 记录。</div></div>"
    pc, hc = it["price_change_pct"], it["hold_change_pct"]
    c = lambda v: "up" if v > 0 else ("down" if v < 0 else "")
    pat = "平盘" if it["pattern"] == "未分类" else it["pattern"]
    link = ("<a href='chart.html?s=AU0'>打开 AU0 K 线形态图 →</a> <span class='g-small'>（K 线图优先用加权指数口径，数值可能与主力连续收盘不同）</span>"
            if "AU0" in avail_syms else "<span class='muted'>K 线图暂无 AU0 数据</span>")
    d = escape(it.get("date") or latest["data_date"])
    return f"""<div class='card'><h3>上期所黄金 AU0 · 每日扫描<span class='g-tag'>人民币元 / 克</span></h3>
<div class='g-kpi'><div><span class='k'>收盘（主力连续）</span><span class='v'>{it['today_close']:g}</span></div>
<div><span class='k'>涨跌</span><span class='v {c(pc)}'>{pc:+.2f}%</span></div>
<div><span class='k'>持仓变化</span><span class='v {c(hc)}'>{hc:+.2f}%</span></div>
<div><span class='k'>八种形态</span><span class='v'>{escape(pat)}</span></div></div>
<div class='g-small'>数据日期 {d} ｜ 来源：新浪财经主力连续（akshare），随每日扫描自动更新 ｜ <a href='reports/{escape(latest['data_date'])}.html'>当日日报</a></div>
<div style='margin-top:6px'>{link}</div></div>"""


def gold_body(latest, avail_syms, gold, macro):
    gq = gold["quality"]
    ex = "；".join(f"{escape(e['id'])}：{escape(e['reason'])}" for e in macro.get("excludedSeries", []))
    return f"""<style>{CSS}</style>
<div class='hd'><div><h1>黄金专题</h1><div class='sub'>上海黄金 AU0（元/克）与纽约黄金 GC=F（美元/盎司）是两个不同品种，分开展示，不换算</div></div></div>
<div class='g-note'>AU0 每个交易日收盘后随日报更新；GC=F 和美国宏观数据是截至 {escape(gold['asOf'])} 的历史快照，不会自动更新。本页不是实时行情，没有预测模型，不构成投资建议。</div>
{_au0_panel(latest, avail_syms)}
<div class='card'><h3 class='blue'>纽约黄金期货 GC=F · 历史快照<span class='g-tag'>USD / 金衡盎司</span></h3>
<div class='g-small' id='g-notice' role='status'>正在载入 GC=F 快照（最近完整日线 {escape(gold['asOf'])}，{gq['validRows']} 条）…</div>
<noscript><div class='muted'>需要启用 JavaScript 才能查看图表。快照最近完整日线 {escape(gold['asOf'])}，最后收盘 {gold['prices'][-1]['close']:.2f} 美元/金衡盎司。</div></noscript>
<div class='g-kpi'><div><span class='k' id='g-price-k'>最近收盘</span><span class='v' id='g-price'>—</span></div>
<div><span class='k'>最近一期</span><span class='v' id='g-change'>—</span></div>
<div><span class='k' id='g-window'>观察周期收益</span><span class='v' id='g-return'>—</span></div>
<div><span class='k'>20 期年化波动 / 最大回撤</span><span class='v'><span id='g-vol'>—</span> / <span id='g-dd'>—</span></span></div></div>
<div class='g-row'><div class='g-row' id='g-periods' role='group' aria-label='观察周期'><button type='button' class='g-btn on' data-n='20'>20 条</button><button type='button' class='g-btn' data-n='60'>60 条</button><button type='button' class='g-btn' data-n='120'>120 条</button></div>
<div class='g-row'><button type='button' class='g-btn on' id='g-real'>恢复 GC=F 快照</button><label class='g-up'>导入价格 CSV<input id='g-file' type='file' accept='.csv,text/csv' hidden></label><button type='button' class='g-btn' id='g-sample'>下载 CSV 示例</button></div></div>
<div class='g-small' id='g-chartlabel'></div>
<svg id='g-chart' class='g-svg' viewBox='0 0 700 240' role='img' aria-label='黄金历史收盘折线图'></svg>
<div class='g-leg'><span id='g-start'></span><span>历史表现 ≠ 未来</span><span id='g-end'></span></div>
<details style='margin-top:10px'><summary>CSV 导入说明</summary><div class='card g-small' style='border-radius:0 0 6px 6px'>第一行 <code>date,close</code>；日期 YYYY-MM-DD，价格为正数，2–10000 行，不能有重复或未来日期，文件不超过 2 MB。只在当前页面内存中计算，不上传、不保存，刷新即消失。请只导入一个标的；导入数据不会与 GC=F 或 AU0 合并。</div></details>
</div>
<div class='g-split'>
<div class='card'><h3>数据来源与质量<span class='g-tag' id='g-badge'>读取中</span></h3><p class='g-small' id='g-prov'></p>
<div class='g-q' id='g-quality'></div><p class='g-small' id='g-method'></p>
<details><summary>异常、缺口与最近记录</summary><div class='card g-small' style='border-radius:0 0 6px 6px'><div id='g-audit'></div>
<div class='tbl g-tbl'><table><thead><tr><th>记录日期</th><th>收盘</th><th>较前条</th></tr></thead><tbody id='g-lastrows'></tbody></table></div></div></details></div>
<div class='card'><h3>多周期历史收益</h3><div class='tbl g-tbl' style='border-radius:6px'><table><thead><tr><th>周期</th><th>历史收益</th><th>起点日期</th></tr></thead><tbody id='g-matrix'></tbody></table></div>
<p class='g-small' style='margin-top:8px'>仅为已发生的历史区间收益。时序切分、样本外检验、交易成本等模型验证未做，本页不提供模型有效性结论。</p>
<details><summary>2026-01-30 异常复核 · 合约口径待确认</summary><div class='card g-small' style='border-radius:0 0 6px 6px'><p>GC=F 从 5,318.3999 跌至 4,745.1001 美元，序列变动 −10.78%。AP 分月报价将 4,745.10 列在四月合约、二月合约为 4,713.90；路透则描述 4,745.10 为二月合约结算价，来源存在冲突。可能为跨月拼接，未取得供应商逐日合约标识，尚不能确认，不能视为同合约收益。处理：保留原价和异常标记，不修正历史数据。</p>
<p><a href='https://finance.yahoo.com/news/bc-gold-futures-150026787.html' target='_blank' rel='noopener'>AP 分月报价</a> · <a href='https://www.reuters.com/world/india/gold-slips-firmer-dollar-set-best-month-since-1980-2026-01-30/' target='_blank' rel='noopener'>路透报道</a></p></div></details></div>
</div>
<div class='card' id='m-section'><h3 class='blue'>宏观观测（美国）<span class='g-tag'>历史快照 · 不是预测</span></h3>
<p class='g-small'>选择观察日，查看截至该日已记录的观测值。观测日期不等于发布日期，历史值可能后来才发布或被修订，不能假设当时已知。</p>
<div class='g-row'><label class='g-small'>观察日期 <input type='date' id='m-date' disabled></label><button type='button' class='g-btn' id='m-latest' disabled>回到 GC=F 最近记录日</button><span id='m-state' class='g-small' role='status'>载入宏观数据…</span></div>
<div class='mgrid' id='m-cards'></div>
<div class='g-row'><b id='m-chart-title' style='font-size:13px'>选择一个指标查看历史</b><span class='g-small'>最近最多 61 条有效观测 · 未插值</span></div>
<svg id='m-chart' class='g-svg' viewBox='0 0 840 220' role='img' aria-label='所选宏观指标历史观测图'></svg>
<div class='g-leg'><span id='m-start'></span><span id='m-unit'></span><span id='m-end'></span></div>
<p id='m-explain' class='g-small' style='margin-top:6px'></p>
<details><summary>数据对齐、缺失与研究限制</summary><div class='card g-small' style='border-radius:0 0 6px 6px'><div id='m-audit'></div><p>未收录：{ex}</p></div></details></div>
<div class='card'><h3>风险预算计算器<span class='g-tag'>手动情景测算</span></h3>
<div class='g-form' id='r-form'><label>账户资金（元）<input id='r-capital' type='number' inputmode='decimal' value='1000000' min='0' max='1000000000000'></label>
<label>风险比例（%）<input id='r-risk' type='number' inputmode='decimal' value='1' min='0' max='100' step='0.1'></label>
<label>每手止损损失（元）<input id='r-loss' type='number' inputmode='decimal' value='5000' min='0.01' max='1000000000000' step='0.01'></label>
<label>已占用风险预算（元）<input id='r-used' type='number' inputmode='decimal' value='0' min='0' max='1000000000000'></label></div>
<div class='g-kpi' style='grid-template-columns:1fr 1fr'><div><span class='k'>剩余风险预算</span><span class='v' id='r-budget'>—</span></div><div><span class='k'>按输入可容纳</span><span class='v' id='r-lots'>—</span></div></div>
<div class='g-small' id='r-msg' role='status'></div>
<div class='g-small'>手数向下取整。只按输入测算，未计手续费、滑点、跳空与保证金限制，不代表建议仓位。输入只在本页内存中，不保存、不上传。</div></div>
<div class='g-small'>数据日期：AU0 见上方；GC=F 截至 {escape(gold['asOf'])}；宏观 {'、'.join(escape(s['id'] + ' ' + s['asOf']) for s in macro['series'])}。</div>
<details style='margin-top:8px'><summary>数据来源与版本</summary><div class='card g-small' style='border-radius:0 0 6px 6px'>
<p>GC=F：{escape(gold['sourceName'])}，抓取于 {escape(gold['fetchedAt'])}，原始响应 SHA-256 {escape(gold['rawSha256'])}。</p>
<p>宏观：FRED（美联储理事会 H.15/H.10、美国 EIA），抓取于 {'、'.join(escape(s['id'] + ' ' + s['fetchedAt']) for s in macro['series'])}。</p>
<p>以上快照导入自原黄金研究台（提交 {escape(gold['importedFrom']['sourceCommit'][:7])}）；该项目的模型研究不在本页展示。</p></div></details>
<script type='module' src='assets/gold/gold.mjs'></script>"""


def unavailable_body(latest, avail_syms, error):
    """冻结快照缺失或校验失败时的 gold.html：保留 AU0 每日扫描，明确说明历史快照暂不可用，不加载脚本与数据"""
    try:
        au0 = _au0_panel(latest, avail_syms)
    except Exception:
        au0 = ""
    return f"""<style>{CSS}</style>
<div class='hd'><div><h1>黄金专题</h1><div class='sub'>上海黄金 AU0（元/克）与纽约黄金 GC=F（美元/盎司）是两个不同品种，分开展示，不换算</div></div></div>
<div class='g-note'>GC=F 历史快照和美国宏观数据暂不可用：本次建站时数据文件缺失或校验未通过，因此没有显示任何 GC=F 或宏观数值，也没有用替代数据。AU0 每日扫描不受影响。</div>
{au0}
<div class='card'><h3 class='blue'>纽约黄金期货 GC=F · 历史快照</h3><div class='muted'>暂不可用。详情见 <a href='status.html'>运行状态</a>。</div>
<details style='margin-top:8px'><summary>技术原因</summary><div class='card g-small' style='border-radius:0 0 6px 6px'>{escape(error)}</div></details></div>"""


# 外部私密面板（Howard Capital Research，需登录）；导航和品种研究卡片共用这一个地址
ETF_PANEL_URL = "https://howard-capital-research.netlify.app/etf-panel.html"


def _hub(cards):
    return "<div class='hub'>" + "".join(f"<a href='{h}'><b>{t}</b><span>{d}</span></a>" for h, t, d in cards) + "</div>"


def research_body():
    return f"""<style>{CSS}</style><div class='hd'><div><h1>品种研究</h1><div class='sub'>按品种和市场环境看数据；各页内容与原来一致，只是集中到这里</div></div></div>
{_hub([("gold.html", "黄金专题", "上期所 AU0 每日扫描 + COMEX GC=F 冻结历史快照、三个美国宏观观测、CSV 导入、风险预算"),
       ("chart.html", "K 线形态图", "54 品种加权指数 K 线，按《王刚期货交易体系手册》规则自动标注"),
       ("macd.html", "MACD 买卖点", "MACD 八策略分策略胜率与最近信号"),
       ("trend.html", "信号趋势", "近 60 个交易日的形态数量与涨跌家数变化"),
       ("macro.html", "宏观时钟", "中国 PMI / CPI / PPI / M2 / Shibor 等，美林时钟中国版"),
       (ETF_PANEL_URL, "ETF 资金面板 🔒", "国家队相关 ETF 成交量监控与资金面板，交易日 15:30（北京时间）后更新；在 Howard Capital Research 站，需登录")])}"""


def strategies_body():
    return f"""<style>{CSS}</style><div class='hd'><div><h1>策略验证</h1><div class='sub'>历史回测与纸面实盘记录；规则与参数按各页说明，未在本次改版中改动</div></div></div>
{_hub([("stats.html", "历史战绩", "八种形态与 MACD 信号的历史胜率统计"),
       ("erqu.html", "二区实盘", "二区定律纸面记录"),
       ("cta.html", "趋势回测", "趋势跟踪回测结果"),
       ("oversold.html", "跌够久实盘", "跌够久纸面实盘（参数 2026-10-17 封存）"),
       ("thushort.html", "周四做空", "周四做空纸面实盘（2026-11-04 起）")])}
<div class='g-small'>纸面记录与回测都不是实盘收益，也不构成投资建议。</div>"""


def status_body(datas, gen_time, gold=None, macro=None, failed=None, snapshot_error=None, extra_rows=None):
    latest = datas[-1]
    errs = latest.get("error_count") or 0
    rows = [("最新日报数据日期", escape(latest["data_date"]), f"<a href='reports/{escape(latest['data_date'])}.html'>查看日报</a>"),
            ("该日报扫描时间", escape(str(latest.get("scan_date", "—"))), "扫描脚本写入的时间"),
            ("有效品种", f"{latest.get('valid_count', '—')} / {latest.get('total_scanned', '—')}",
             f"{errs} 个品种获取失败" if errs else "无获取失败记录"),
            ("已归档交易日", str(len(datas)), f"{escape(datas[0]['data_date'])} 至 {escape(latest['data_date'])}")]
    if gold:
        rows.append(("GC=F 冻结快照", "最近完整日线 " + escape(gold["asOf"]), "抓取 " + escape(gold["fetchedAt"]) + " · 不自动更新"))
    if macro:
        for s in macro["series"]:
            rows.append((f"宏观 {escape(s['id'])}", "最新观测 " + escape(s["asOf"]), "抓取 " + escape(s["fetchedAt"]) + " · 冻结快照"))
    if snapshot_error:
        rows.append(("黄金/宏观快照", "校验未通过", escape(snapshot_error)))
    rows += extra_rows or []  # 调用方已转义（如 research_briefs.status_rows）
    trs = "".join(f"<tr><td style='text-align:left'>{a}</td><td>{b}</td><td style='text-align:left;white-space:normal'>{c}</td></tr>" for a, b, c in rows)
    fail = ("<div class='g-note'>本次建站有页面生成失败：" + "、".join(escape(f) for f in failed) + "（见 Actions 日志）</div>") if failed else ""
    return f"""<style>{CSS}</style><div class='hd'><div><h1>运行状态</h1><div class='sub'>只列本次建站时读到的实际数据日期；数据日期与页面生成时间分开显示</div></div></div>
{fail}<div class='card'><h3>数据日期</h3><div class='tbl' style='border-radius:6px'><table><thead><tr><th style='text-align:left'>项目</th><th>数据日期 / 数量</th><th style='text-align:left'>说明</th></tr></thead><tbody>{trs}</tbody></table></div>
<p class='g-small' style='margin-top:8px'>本页生成时间：{escape(gen_time)}（北京时间）。生成时间晚于数据日期是正常的：休市、数据未更新或定时任务延迟时，网站保留最近一份报告。</p></div>
<div class='card'><h3 class='blue'>定时任务实际运行记录</h3><p style='font-size:13px'>本页不判断任务是否成功。每次运行的真实结果（成功、失败、跳过）请看 GitHub Actions：<a href='{ACTIONS_URL}' target='_blank' rel='noopener'>{ACTIONS_URL}</a></p>
<p class='g-small'>主流程：北京时间工作日 17:05 启动，18:35、19:40 两个备用触发；黄金 GC=F 与美国宏观观测为一次性导入的冻结快照，没有自动更新任务。</p></div>"""
