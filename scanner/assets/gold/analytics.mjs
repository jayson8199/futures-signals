// 黄金专题纯函数：CSV 校验、历史统计、宏观观测查找、快照校验、风险预算。
// parseCsv / analyze / observe 改编自原黄金研究台 dist/analytics.mjs、dist/macro.mjs（同一作者项目）。
export const MACRO_IDS = ['DFII10', 'DTWEXBGS', 'DCOILWTICO'];
const ISO = /^\d{4}-\d{2}-\d{2}$/;
const isDate = d => typeof d === 'string' && ISO.test(d) && Number.isFinite(Date.parse(d)) && new Date(d).toISOString().slice(0, 10) === d;

export function parseCsv(text, today = new Date().toISOString().slice(0, 10)) {
  const lines = String(text).replace(/^﻿/, '').trim().split(/\r?\n/);
  if (lines.shift().trim().toLowerCase() !== 'date,close') throw Error('表头必须是 date,close');
  if (lines.length < 2 || lines.length > 10000) throw Error('需 2 至 10000 行数据');
  const seen = new Set();
  return lines.map((line, i) => {
    const parts = line.split(','), date = parts[0].trim(), value = parts[1]?.trim(), close = Number(value);
    if (parts.length !== 2 || !isDate(date) || date > today || !value || !Number.isFinite(close) || close <= 0 || seen.has(date))
      throw Error(`第 ${i + 2} 行：日期或价格无效、存在未来日期或日期重复`);
    seen.add(date);
    return { date, close };
  }).sort((a, b) => a.date.localeCompare(b.date));
}

export function analyze(rows) {
  let peak = rows[0].close, maxDrawdown = 0;
  const jumps = [], dates = new Set(rows.map(r => r.date));
  for (let i = 0; i < rows.length; i++) {
    peak = Math.max(peak, rows[i].close);
    maxDrawdown = Math.min(maxDrawdown, rows[i].close / peak - 1);
    if (i) { const v = (rows[i].close / rows[i - 1].close - 1) * 100; if (Math.abs(v) > 8) jumps.push({ date: rows[i].date, changePct: v }); }
  }
  const gaps = [];
  for (let d = new Date(rows[0].date + 'T00:00:00Z'), end = new Date(rows.at(-1).date + 'T00:00:00Z'); d <= end; d.setUTCDate(d.getUTCDate() + 1)) {
    const k = d.toISOString().slice(0, 10);
    if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6 && !dates.has(k)) gaps.push(k);
  }
  const recent = rows.slice(-21), rets = recent.slice(1).map((r, i) => Math.log(r.close / recent[i].close));
  let vol = null;
  if (rets.length === 20) { const mean = rets.reduce((a, b) => a + b, 0) / 20; vol = Math.sqrt(rets.reduce((a, b) => a + (b - mean) ** 2, 0) / 19) * Math.sqrt(252) * 100; }
  return { maxDrawdown: maxDrawdown * 100, volatility: vol, weekdayGaps: gaps, largeMoves: jumps };
}

// 第 k 个记录间隔的历史收益（%），数据不足返回 null
export function periodReturn(rows, k) {
  return rows.length > k ? (rows.at(-1).close / rows.at(-1 - k).close - 1) * 100 : null;
}

// 按观测日期向前查找；不代表该数据当时已发布
export function observe(series, anchor) {
  const rows = series.observations.filter(r => r.date <= anchor);
  if (!rows.length) return null;
  const last = rows.at(-1), base = rows.length > 20 ? rows.at(-21) : null;
  let change = null;
  if (base) {
    if (series.transform === 'bp') change = (last.value - base.value) * 100;
    else if (series.transform === 'diff') change = last.value - base.value;
    else if (base.value !== 0) change = (last.value / base.value - 1) * 100;
  }
  return { date: last.date, value: last.value, baseDate: base?.date ?? null, change,
    ageDays: Math.round((Date.parse(anchor) - Date.parse(last.date)) / 86400000), rows: rows.slice(-61) };
}

export function validGold(g) {
  if (g?.schemaVersion !== 1 || g.symbol !== 'GC=F' || g.currency !== 'USD' || g.frequency !== 'daily' || !Array.isArray(g.prices)) return false;
  if (!/^[0-9a-f]{64}$/.test(g.rawSha256 ?? '') || g.prices.length !== g.quality?.validRows || g.prices.length < 2) return false;
  return g.prices.every((r, i, a) => isDate(r.date) && Number.isFinite(r.close) && r.close > 0 && (i === 0 || r.date > a[i - 1].date))
    && g.prices.at(-1).date === g.asOf;
}

// 严格校验：恰好三个序列、与黄金快照同一原始哈希、共同观测日按黄金日期重新计算后完全一致
export function validMacro(m, gold) {
  if (m?.schemaVersion !== 2 || m.trainingEligible !== false || !gold || m.goldRawSha256 !== gold.rawSha256 || m.goldAsOf !== gold.asOf) return false;
  if (!Array.isArray(m.series) || m.series.length !== 3 || JSON.stringify(m.seriesIds) !== JSON.stringify(MACRO_IDS)) return false;
  if (JSON.stringify(m.series.map(s => s.id)) !== JSON.stringify(MACRO_IDS)) return false;
  const ok = m.series.every(s => s.observations?.length > 20 && s.observations.every((r, i, a) =>
    isDate(r.date) && Number.isFinite(r.value) && r.date <= m.goldAsOf && (i === 0 || r.date > a[i - 1].date)));
  if (!ok) return false;
  const sets = m.series.map(s => new Set(s.observations.map(r => r.date)));
  const common = gold.prices.map(p => p.date).filter(d => sets.every(st => st.has(d)));
  return m.goldObservationCount === gold.prices.length && JSON.stringify(common) === JSON.stringify(m.commonObservationDates);
}

// 手动风险预算的输入范围：金额最多 1 万亿元，每手止损至少 0.01 元，风险比例 0–100%
export const RISK_LIMITS = { maxAmount: 1e12, minLoss: 0.01 };
const DECIMAL = /^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i;
function toNumber(x) {
  if (typeof x === 'number') return x;
  if (typeof x !== 'string') return NaN;
  const t = x.trim();
  return DECIMAL.test(t) ? Number(t) : NaN;  // 空白、十六进制等一律视为无效
}

// 手动风险预算：输入无效或超出范围返回 null；不计手续费、滑点、跳空与保证金
export function riskBudget(capital, riskPct, lossPerLot, used) {
  const v = [capital, riskPct, lossPerLot, used].map(toNumber);
  const [c, r, l, u] = v, M = RISK_LIMITS.maxAmount;
  if (!v.every(Number.isFinite) || c < 0 || c > M || r < 0 || r > 100 || l < RISK_LIMITS.minLoss || l > M || u < 0 || u > M) return null;
  const budget = Math.max(0, c * r / 100 - u), lots = Math.floor(budget / l);
  if (!Number.isFinite(budget) || !Number.isSafeInteger(lots)) return null;
  return { budget, lots };
}
