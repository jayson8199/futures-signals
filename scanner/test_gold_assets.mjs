// 黄金专题前端回归（离线，不需要浏览器）。
// 用法：node scanner/test_gold_assets.mjs [已生成的 site 目录]   —— 给出 site 时额外用假 DOM 跑一遍 gold.html 的交互脚本
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const assetDir = path.join(here, 'assets', 'gold');
const A = await import(pathToFileURL(path.join(assetDir, 'analytics.mjs')));
const readJson = f => JSON.parse(fs.readFileSync(path.join(assetDir, f), 'utf8'));

// CSV 校验
const rows = A.parseCsv('date,close\n2026-01-05,80\n2026-01-02,100', '2026-11-04');
assert.equal(rows[0].close, 100);
const st = A.analyze(rows);
assert.ok(Math.abs(st.maxDrawdown + 20) < 1e-8); assert.equal(st.volatility, null); assert.equal(st.largeMoves.length, 1);
assert.equal(A.analyze(A.parseCsv('date,close\n2026-01-02,100\n2026-01-06,100', '2026-11-04')).weekdayGaps[0], '2026-01-05');
for (const bad of ['date,price\n2026-01-02,1\n2026-01-05,2', 'date,close\n2026-01-02,100', 'date,close\n2026-01-02,100\n2026-01-02,90',
  'date,close\n2026-02-30,100\n2026-03-03,90', 'date,close\n2026-01-02,-1\n2026-01-05,90', 'date,close\n2026-01-02,0\n2026-01-05,90',
  'date,close\n2026-11-05,1\n2026-11-06,2', 'date,close\n2026-01-02,1,3\n2026-01-05,2', 'date,close\n2026-01-02,abc\n2026-01-05,2',
  'date,close\n2026-01-02,\n2026-01-05,2', 'date,close\n26-01-02,1\n2026-01-05,2'])
  assert.throws(() => A.parseCsv(bad, '2026-11-04'), undefined, bad);
assert.ok(Math.abs(A.periodReturn(rows, 1) + 20) < 1e-9); assert.equal(A.periodReturn(rows, 2), null);

// 风险预算：无效输入返回 null
assert.deepEqual(A.riskBudget('1000000', '1', '5000', '0'), { budget: 10000, lots: 2 });
assert.deepEqual(A.riskBudget(100000, 1, 400, 2000), { budget: 0, lots: 0 });
assert.deepEqual(A.riskBudget('1000000', '2', '5000', '0'), { budget: 20000, lots: 4 });
assert.deepEqual(A.riskBudget(' 1000000 ', '1', '5000', '0'), { budget: 10000, lots: 2 });  // 首尾空白可接受
assert.deepEqual(A.riskBudget('1e6', '1', '5e3', '0'), { budget: 10000, lots: 2 });       // 浏览器 number 输入可给出指数写法
// 上限边界：1 万亿元 × 100% ÷ 0.01 元 = 1e14 手，仍是安全整数
assert.deepEqual(A.riskBudget('1e12', '100', '0.01', '0'), { budget: 1e12, lots: 1e14 });
assert.ok(Number.isSafeInteger(A.riskBudget('1e12', '100', '0.01', '0').lots));
assert.deepEqual(A.riskBudget('1e12', '100', '1e12', '1e12'), { budget: 0, lots: 0 });
assert.deepEqual(A.riskBudget('1000000', '0', '5000', '0'), { budget: 0, lots: 0 });
assert.deepEqual(A.riskBudget('1000000', '100', '5000', '0'), { budget: 1000000, lots: 200 });
for (const bad of [['', 1, 5000, 0], ['abc', 1, 5000, 0], [-1, 1, 5000, 0], [1e6, -0.1, 5000, 0], [1e6, 100.1, 5000, 0],
  [1e6, 1, 0, 0], [1e6, 1, -5, 0], [1e6, 1, 5000, -1], [1e6, 1, Infinity, 0], [null, 1, 5000, 0],
  // 溢出与不安全整数（Codex 复现的 Infinity 手）
  ['1e308', '100', '1', '0'], ['1000000', '1', '1e-300', '0'], ['1e12', '100', '0.009', '0'], ['1.0000001e12', '1', '5000', '0'],
  ['1e6', '1', '5000', '1.0000001e12'], ['1e6', '1', '1.0000001e12', '0'], ['1e400', '1', '5000', '0'], [Number.MAX_VALUE, 100, 1, 0],
  // 空白与非十进制写法
  [' ', '1', '5000', '0'], ['1000000', '	', '5000', '0'], ['1000000', '1', '  ', '0'], ['1000000', '1', '5000', ' '],
  ['0x10', '1', '5000', '0'], ['1,000', '1', '5000', '0'], ['Infinity', '1', '5000', '0'], ['NaN', '1', '5000', '0'], [undefined, 1, 5000, 0], [true, 1, 5000, 0]])
  assert.equal(A.riskBudget(...bad), null, JSON.stringify(bad));

// 快照校验：恰好三个序列 + 哈希一致 + 共同日期重新计算
const gold = readJson('gc_snapshot.json'), macro = readJson('macro3.json');
assert.ok(A.validGold(gold)); assert.ok(A.validMacro(macro, gold));
const clone = o => JSON.parse(JSON.stringify(o));
const mut = [
  m => { m.goldRawSha256 = '0'.repeat(64); },
  m => { m.goldAsOf = '2026-10-29'; },
  m => { m.trainingEligible = true; },
  m => { m.series.push({ ...clone(m.series[0]), id: 'VIXCLS' }); },
  m => { m.seriesIds = [...m.seriesIds, 'VIXCLS']; },
  m => { m.series.pop(); },
  m => { m.series.reverse(); },
  m => { m.commonObservationDates.pop(); },
  m => { m.goldObservationCount += 1; },
  m => { m.series[0].observations.push({ date: '2026-11-02', value: 1 }); },
  m => { m.series[1].observations[5].value = 'x'; },
  m => { m.schemaVersion = 1; },
];
mut.forEach((f, i) => { const m = clone(macro); f(m); assert.equal(A.validMacro(m, gold), false, 'mutation ' + i); });
assert.equal(A.validMacro(macro, { ...gold, rawSha256: 'f'.repeat(64) }), false);
const g2 = clone(gold); g2.prices.pop(); assert.equal(A.validGold(g2), false);
for (const m of macro.series) assert.ok(!JSON.stringify(m).toUpperCase().includes('VIX'));

// observe：单位换算与日期边界
const ob = Array.from({ length: 21 }, (_, i) => ({ date: new Date(Date.UTC(2026, 0, i + 1)).toISOString().slice(0, 10), value: 1 + i * .01 }));
const s = { observations: ob, transform: 'bp' };
assert.equal(A.observe(s, '2025-12-31'), null); assert.ok(Math.abs(A.observe(s, '2026-01-21').change - 20) < 1e-8);
assert.equal(A.observe(s, '2026-01-20').change, null); assert.equal(A.observe(s, '2026-01-22').ageDays, 1);
console.log('gold analytics: CSV / risk / exact-3 macro validator / observe passed');

// 假 DOM 跑交互脚本（使用 site 内已复制的资产）
const site = process.argv[2];
if (site) {
  const html = fs.readFileSync(path.join(site, 'gold.html'), 'utf8');
  assert.ok(html.includes("<script type='module' src='assets/gold/gold.mjs'></script>"));
  async function runPage(fault) {
    const els = new Map();
    const el = (tag = 'div') => ({ tag, textContent: '', innerHTML: '', value: '', className: '', hidden: false, disabled: false, children: [], dataset: {},
      classList: { toggle() {} }, setAttribute() {}, addEventListener(t, f) { this['on' + t] = f; },
      replaceChildren(...v) { this.children = v; this.innerHTML = ''; this.textContent = ''; }, append(...v) { this.children.push(...v); }, click() { this.onclick?.(); } });
    for (const m of html.matchAll(/\bid='([^']+)'/g)) els.set('#' + m[1], el());
    for (const [k, v] of Object.entries({ 'r-capital': '1000000', 'r-risk': '1', 'r-loss': '5000', 'r-used': '0' })) els.get('#' + k).value = v;
    globalThis.document = { querySelector(q) { assert.ok(els.has(q), 'missing ' + q); return els.get(q); },
      querySelectorAll(q) { return q === '#r-form input' ? ['#r-capital', '#r-risk', '#r-loss', '#r-used'].map(k => els.get(k)) : []; },
      createElement: el, createTextNode: t => ({ textContent: t }) };
    globalThis.fetch = async url => {
      const u = new URL(url); assert.equal(u.protocol, 'file:'); // 同源相对路径解析，不访问网络
      const v = JSON.parse(fs.readFileSync(fileURLToPath(u), 'utf8'));
      if (fault && u.pathname.endsWith('macro3.json')) v.goldRawSha256 = '0'.repeat(64);
      return { ok: true, json: async () => v };
    };
    await import(pathToFileURL(path.join(site, 'assets', 'gold', 'gold.mjs')) + '?run=' + (fault || 'ok'));
    for (let i = 0; i < 5; i++) await new Promise(r => setImmediate(r));
    return els;
  }
  let e = await runPage();
  assert.equal(e.get('#g-price').textContent, gold.prices.at(-1).close.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  assert.match(e.get('#g-notice').textContent, /历史快照/);
  assert.doesNotMatch(e.get('#g-notice').textContent, /实时更新|自动刷新/);
  assert.equal(e.get('#r-budget').textContent, '¥10,000'); assert.equal(e.get('#r-lots').textContent, '2 手');
  assert.equal(e.get('#m-cards').children.length, 3);
  assert.equal(e.get('#m-date').value, gold.asOf);
  e.get('#g-periods').onclick({ target: { dataset: { n: '120' } } });
  assert.equal(e.get('#g-window').textContent, '120 个日线记录间隔 · 历史收益');
  e.get('#r-loss').value = '0'; e.get('#r-loss').oninput();
  assert.equal(e.get('#r-budget').textContent, '检查输入');
  for (const [cap, rk, loss, used] of [['1e308', '100', '5000', '0'], ['1000000', '1', '1e-300', '0'], [' ', '1', '5000', '0']]) {
    e.get('#r-capital').value = cap; e.get('#r-risk').value = rk; e.get('#r-loss').value = loss; e.get('#r-used').value = used; e.get('#r-capital').oninput();
    assert.equal(e.get('#r-budget').textContent, '检查输入'); assert.equal(e.get('#r-lots').textContent, '—');
    assert.doesNotMatch(e.get('#r-lots').textContent + e.get('#r-budget').textContent, /Infinity|NaN/);
  }
  e.get('#r-capital').value = '1000000'; e.get('#r-risk').value = '2'; e.get('#r-loss').value = '5000'; e.get('#r-used').value = '0'; e.get('#r-risk').oninput();
  assert.equal(e.get('#r-lots').textContent, '4 手');
  e.get('#m-date').value = '2000-01-01'; e.get('#m-date').onchange();
  assert.equal(e.get('#m-cards').children.length, 0);
  e = await runPage('hash');
  assert.match(e.get('#m-state').textContent, /宏观数据加载失败/);
  assert.equal(e.get('#m-cards').children.length, 0);
  assert.equal(e.get('#g-price').textContent !== '—', true);
  console.log('gold page DOM smoke (snapshot load, 20/60/120, risk invalid input, date filter, macro hash mismatch) passed');
}
