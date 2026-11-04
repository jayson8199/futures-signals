// 黄金专题页交互（gold.html）。数据全部来自同目录冻结快照；用户导入的 CSV 与风险输入只留在本页内存，不上传、不保存。
// 交互逻辑改编自原黄金研究台 src/app.mjs，去掉了合成演示数据与模型占位。
import { parseCsv, analyze, periodReturn, observe, validGold, validMacro, riskBudget } from './analytics.mjs';

const $ = s => document.querySelector(s);
const GOLD_URL = new URL('./gc_snapshot.json', import.meta.url);
const MACRO_URL = new URL('./macro3.json', import.meta.url);
let snapshot = null, macroData = null, macroActive = 'DFII10';
let data = [], n = 20, mode = 'loading';

const fmtPct = v => v === null ? '数据不足' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
const cls = v => v === null ? '' : v > 0 ? 'up' : v < 0 ? 'down' : '';
const bj = t => new Date(t).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
function setText(id, t) { $(id).textContent = t; }
function para(t) { const p = document.createElement('p'); p.textContent = t; return p; }

function linePath(rows, key, w, h, x0, y0) {
  let lo = Math.min(...rows.map(r => r[key])), hi = Math.max(...rows.map(r => r[key]));
  const pad = Math.max((hi - lo) * .12, Math.abs(hi) * 1e-4, .01); lo -= pad; hi += pad;
  const pts = rows.map((r, i) => [x0 + i / Math.max(rows.length - 1, 1) * w, y0 + h - (r[key] - lo) / (hi - lo) * h]);
  return { lo, hi, d: pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ') };
}
function grid(lo, hi, w, h, x0, y0, digits) {
  return [0, 1, 2, 3].map(i => { const y = y0 + i * h / 3;
    return `<path d="M${x0} ${y.toFixed(1)}H${x0 + w}" style="stroke:var(--line)" stroke-dasharray="4 6"/><text x="${x0 + w + 8}" y="${(y + 4).toFixed(1)}" font-size="11">${(hi - (hi - lo) * i / 3).toFixed(digits)}</text>`; }).join('');
}

function render() {
  if (!data.length) return;
  const a = data.slice(-(n + 1));
  const { lo, hi, d } = linePath(a, 'close', 620, 200, 12, 20);
  $('#g-chart').innerHTML = grid(lo, hi, 620, 200, 12, 20, 0) +
    `<path d="${d} L632,225 L12,225 Z" style="fill:var(--amber-dim)"/><path d="${d}" fill="none" style="stroke:var(--amber)" stroke-width="2.2"/>`;
  const unit = mode === 'snapshot' ? 'USD / 金衡盎司' : '单位未验证';
  setText('#g-price', data.at(-1).close.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  setText('#g-price-k', `最近收盘 · ${unit} · ${data.at(-1).date}`);
  const r1 = periodReturn(data, 1), rn = periodReturn(data, n);
  setText('#g-change', fmtPct(r1)); $('#g-change').className = 'v ' + cls(r1);
  setText('#g-return', fmtPct(rn)); $('#g-return').className = 'v ' + cls(rn);
  setText('#g-window', `${n} 个日线记录间隔 · 历史收益`);
  setText('#g-start', a[0].date); setText('#g-end', a.at(-1).date);
  setText('#g-chartlabel', mode === 'snapshot' ? `GC=F · ${data.length} 条有效日线 · 历史快照` : `用户导入 ${data.length} 条 · 来源未验证 · 仅当前页面`);
  document.querySelectorAll('#g-periods [data-n]').forEach(b => b.classList.toggle('on', +b.dataset.n === n));
  $('#g-matrix').innerHTML = [20, 60, 120].map(k => { const v = periodReturn(data, k);
    return `<tr><td>${k} 个日线间隔</td><td class="${cls(v)}">${fmtPct(v)}</td><td>${data.length > k ? data.at(-1 - k).date : '—'}</td></tr>`; }).join('');
  renderAudit(); renderMacro();
}

function renderAudit() {
  const stats = analyze(data), q = mode === 'snapshot' ? snapshot.quality : null;
  const gaps = q?.weekdayGaps ?? stats.weekdayGaps, jumps = q?.largeMoves ?? stats.largeMoves;
  setText('#g-dd', stats.maxDrawdown.toFixed(2) + '%');
  setText('#g-vol', stats.volatility === null ? '数据不足' : stats.volatility.toFixed(2) + '%');
  setText('#g-badge', mode === 'snapshot' ? '结构校验通过 · 缺口待核对' : '用户文件 · 来源未验证');
  $('#g-real').classList.toggle('on', mode === 'snapshot');
  const prov = $('#g-prov'); prov.replaceChildren();
  if (mode === 'snapshot') {
    const link = document.createElement('a'); link.href = snapshot.sourceUrl; link.textContent = 'Yahoo Finance · GC=F'; link.target = '_blank'; link.rel = 'noopener';
    prov.append(link, document.createTextNode(` ｜ ${snapshot.instrument}，非现货 XAU/USD，非上期所 AU0 ｜ ${snapshot.unit} ｜ 最近完整日线 ${snapshot.asOf} ｜ 抓取于 ${bj(snapshot.fetchedAt)}（北京时间）`));
    setText('#g-method', `记录时区：${snapshot.timezone}。${snapshot.methodology} 历史快照，不自动更新。`);
  } else {
    prov.textContent = '用户 CSV · 标的、单位与来源均未经核验；只在当前页面内存中计算，刷新即消失，不会与 GC=F 或 AU0 合并。';
    setText('#g-method', '历史收益按记录间隔计算；缺失记录不会用前值填充。');
  }
  $('#g-quality').innerHTML = [['有效记录', data.length, '原始 ' + (q?.rawRows ?? data.length) + ' 条'],
    ['空收盘剔除', q?.nullCloseExcluded.length ?? 0, '不填值、不插值'], ['工作日候选缺口', gaps.length, '可能包含正常休市'],
    ['大幅变动标记', jumps.length, '相邻收盘涨跌幅绝对值 > 8%'], ['重复日期', q?.duplicates ?? 0, '重复直接拒绝载入'],
    ['数据覆盖', data[0].date, '至 ' + data.at(-1).date]]
    .map(x => `<div><span class="k">${x[0]}</span><b>${x[1]}</b><span class="k">${x[2]}</span></div>`).join('');
  const audit = $('#g-audit'); audit.replaceChildren();
  [`工作日缺口（尚未核对交易所日历）：${gaps.join('、') || '无'}`, `空收盘剔除：${q?.nullCloseExcluded.join('、') || '无'}`,
    `当日/未来记录排除：${q?.incompleteExcluded.join('、') || '无'}`,
    `大幅变动（保留原值）：${jumps.map(x => x.date + ' ' + fmtPct(x.changePct)).join('；') || '无'}`,
    '本页数据为供应商单一来源；尚未完成第二来源逐笔比对。']
    .concat(mode === 'snapshot' ? ['原始响应 SHA-256：' + snapshot.rawSha256, '导入自：' + snapshot.importedFrom.project + ' ' + snapshot.importedFrom.sourceCommit] : [])
    .forEach(t => audit.append(para(t)));
  $('#g-lastrows').innerHTML = data.slice(-5).map(r => { const i = data.indexOf(r);
    return `<tr><td>${r.date}</td><td>${r.close.toFixed(2)}</td><td>${i ? fmtPct((r.close / data[i - 1].close - 1) * 100) : '—'}</td></tr>`; }).join('');
}

function clearMacro(msg) {
  macroData = null;
  for (const id of ['#m-cards', '#m-chart', '#m-audit', '#m-explain']) $(id).replaceChildren();
  for (const id of ['#m-start', '#m-end', '#m-unit']) setText(id, '');
  setText('#m-chart-title', '宏观数据尚未载入');
  $('#m-date').disabled = true; $('#m-latest').disabled = true; setText('#m-state', msg);
}

function renderMacro() {
  $('#m-section').hidden = mode !== 'snapshot';
  if (mode !== 'snapshot' || !macroData) return;
  const anchor = $('#m-date').value;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(anchor) || anchor < $('#m-date').min || anchor > $('#m-date').max) {
    setText('#m-state', '请选择黄金历史覆盖范围内的日期。'); $('#m-cards').replaceChildren(); $('#m-chart').replaceChildren();
    setText('#m-explain', '观察日期无效，未展示指标。'); return;
  }
  setText('#m-state', '按观测日期对齐；不代表当日已发布');
  const cards = $('#m-cards'); cards.replaceChildren();
  for (const s of macroData.series) {
    const o = observe(s, anchor), b = document.createElement('button');
    b.type = 'button'; b.className = 'mcard' + (s.id === macroActive ? ' on' : ''); b.setAttribute('aria-pressed', String(s.id === macroActive));
    const k = document.createElement('span'); k.className = 'k'; k.textContent = s.name; b.append(k);
    const v = document.createElement('b'); v.textContent = o ? o.value.toFixed(s.id === 'DTWEXBGS' ? 4 : 2) : '暂无'; b.append(v);
    for (const t of [s.unit, o ? '观测 ' + o.date : '无早于观察日的记录', o ? '距观察日 ' + o.ageDays + ' 个自然日' : '']) { const el = document.createElement('small'); el.textContent = t; b.append(el); }
    const c = document.createElement('small'); c.className = 'delta';
    c.textContent = o && o.change !== null ? '较 20 条观测前 ' + (o.change >= 0 ? '+' : '') + o.change.toFixed(2) + ' ' + s.changeUnit : '20 期变化：数据不足';
    b.append(c); b.onclick = () => { macroActive = s.id; renderMacro(); }; cards.append(b);
  }
  const s = macroData.series.find(x => x.id === macroActive), o = observe(s, anchor);
  setText('#m-chart-title', s.name + ' · ' + s.id); setText('#m-unit', s.unit); $('#m-chart').replaceChildren();
  if (o) {
    const { lo, hi, d } = linePath(o.rows, 'value', 760, 175, 12, 25);
    $('#m-chart').innerHTML = grid(lo, hi, 760, 175, 12, 25, 2) + `<path d="${d}" fill="none" style="stroke:var(--cyan)" stroke-width="2"/>`;
    setText('#m-start', o.rows[0].date); setText('#m-end', o.rows.at(-1).date);
  }
  const ex = $('#m-explain'); ex.replaceChildren();
  const link = document.createElement('a'); link.href = s.sourceUrl; link.textContent = s.origin + ' / FRED ' + s.id; link.target = '_blank'; link.rel = 'noopener';
  ex.append(document.createTextNode(s.note + ' '), link);
  const audit = $('#m-audit'); audit.replaceChildren();
  [`抓取时间：${bj(s.fetchedAt)}（北京时间）。历史快照，不自动更新。最新观测 ${s.asOf}。`,
    `当前指标：${s.quality.validRows} 条有效观测；${s.quality.missingDates.length} 条空值已排除，无填补。`,
    `三个指标与黄金同日皆有观测：${macroData.commonObservationDates.length} / ${macroData.goldObservationCount} 个 GC=F 记录日。仅用于覆盖诊断，不是训练样本数。`,
    '20 期变化以 20 条有效观测为间隔，各指标日期可能不同；利率用基点，其余用百分比。',
    `${macroData.alignmentPolicy} 最新修订版不能代替历史版本；训练资格：未通过。`,
    macroData.provenanceNote,
    '切换观察日只过滤观测日期，不代表该数据当时已公开。未计算 IC、相关性排名、因果效应或预测权重。',
    `所选指标原始响应 SHA-256：${s.rawSha256}`].forEach(t => audit.append(para(t)));
}

async function getJson(url) {
  const r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) throw Error('HTTP ' + r.status);
  return r.json();
}

async function loadSnapshot() {
  $('#g-real').disabled = true; clearMacro('载入宏观数据…');
  try {
    const g = await getJson(GOLD_URL);
    if (!validGold(g)) throw Error('黄金快照结构校验未通过');
    snapshot = g; data = g.prices.map(r => ({ date: r.date, close: r.close })); mode = 'snapshot';
    setText('#g-notice', `GC=F 历史快照：最近完整日线 ${g.asOf}（${bj(g.fetchedAt)} 抓取）。不是实时行情，不会自动更新。`);
    render();
    try {
      const m = await getJson(MACRO_URL);
      if (!validMacro(m, snapshot)) throw Error('宏观文件与黄金快照不匹配或结构无效');
      macroData = m; const dt = $('#m-date');
      dt.disabled = false; $('#m-latest').disabled = false; dt.min = data[0].date; dt.max = g.asOf; dt.value = g.asOf;
      renderMacro();
    } catch (e) { clearMacro('宏观数据加载失败：' + e.message); setText('#m-explain', '未使用任何替代或模拟数据。'); }
  } catch (e) {
    setText('#g-notice', '快照加载失败：' + e.message + '。未使用替代数据；可刷新重试或导入自己的 CSV。'); setText('#g-badge', '加载失败');
  } finally { $('#g-real').disabled = false; }
}

function risk() {
  const r = riskBudget($('#r-capital').value, $('#r-risk').value, $('#r-loss').value, $('#r-used').value);
  if (!r) { setText('#r-budget', '检查输入'); setText('#r-lots', '—'); setText('#r-msg', '请填写数字：资金和已占用 0 至 1 万亿元；风险比例 0–100；每手止损损失 0.01 元至 1 万亿元。'); return; }
  setText('#r-budget', '¥' + r.budget.toLocaleString('zh-CN', { maximumFractionDigits: 2 })); setText('#r-lots', r.lots + ' 手'); setText('#r-msg', '');
}

$('#g-periods').addEventListener('click', e => { if (e.target.dataset.n) { n = +e.target.dataset.n; render(); } });
$('#g-real').addEventListener('click', loadSnapshot);
$('#g-file').addEventListener('change', async e => {
  const f = e.target.files[0];
  try {
    if (!f) return;
    if (f.size > 2000000) throw Error('文件过大，请使用 2 MB 以内 CSV');
    data = parseCsv(await f.text()); mode = 'import';
    setText('#g-notice', '正在查看用户导入的 CSV：只在当前页面内存中计算，不上传、不保存；点「恢复 GC=F 快照」返回。');
    render();
  } catch (err) { setText('#g-notice', 'CSV 未载入：' + err.message + '。当前数据保持不变。'); }
  finally { e.target.value = ''; }
});
$('#g-sample').addEventListener('click', () => {
  const b = new Blob(['date,close\n2026-01-02,2400\n2026-01-05,2410\n2026-01-06,2395\n'], { type: 'text/csv' });
  const url = URL.createObjectURL(b), a = document.createElement('a'); a.href = url; a.download = 'gold_price_example.csv'; a.click(); URL.revokeObjectURL(url);
});
document.querySelectorAll('#r-form input').forEach(el => el.addEventListener('input', risk));
$('#m-date').addEventListener('change', renderMacro);
$('#m-latest').addEventListener('click', () => { if (snapshot && macroData) { $('#m-date').value = snapshot.asOf; renderMacro(); } });
risk();
loadSnapshot();
