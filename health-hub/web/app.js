/* Pebble Health — self-hosted health dashboard for a Pebble watch.
   No dependencies. Every server-provided string reaches the page through
   textContent / setAttribute only; nothing is assigned to innerHTML. */
'use strict';

/* ================================================================== *
 * DOM helpers
 * ================================================================== */
let HUB_CONFIG = {};
const hubUrl = () => HUB_CONFIG.public_url || new URL('./', location.href).href.replace(/\/$/, '');
const sourceLink = label => HUB_CONFIG.source_url ? h('a', {href:HUB_CONFIG.source_url,target:'_blank',rel:'noopener'}, label) : null;

const SVGNS = 'http://www.w3.org/2000/svg';

function build(el, attrs, kids) {
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') el.setAttribute('class', v);
      else if (k === 'text') el.textContent = String(v);
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : String(v));
    }
  }
  const add = c => {
    if (c == null || c === false) return;
    if (Array.isArray(c)) { c.forEach(add); return; }
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  };
  add(kids);
  return el;
}
const h = (tag, attrs, ...kids) => build(document.createElement(tag), attrs, kids);
const s = (tag, attrs, ...kids) => build(document.createElementNS(SVGNS, tag), attrs, kids);

const ICON = {
  today: 'M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z',
  sleep: 'M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z',
  recovery: 'M3 12h4l2-5 3 10 2-5h7',
  training: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  refresh: 'M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7',
  sun: 'M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z',
  moon: 'M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z',
  chev: 'M9 6l6 6-6 6',
  back: 'M15 6l-6 6 6 6',
};
const icon = (name, cls) => s('svg', { viewBox: '0 0 24 24', class: cls, 'aria-hidden': 'true' }, s('path', { d: ICON[name] }));

/* ================================================================== *
 * Formatting
 * ================================================================== */
const LOCALE = undefined; // browser default
const isNum = v => typeof v === 'number' && Number.isFinite(v);
function fmt(v, digits = 0) {
  if (!isNum(v)) return '—';
  return v.toLocaleString(LOCALE, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
function fmtDur(sec, short) {
  if (!isNum(sec)) return '—';
  const m = Math.round(sec / 60), hh = Math.floor(m / 60), mm = m % 60;
  if (short) return hh ? `${hh}h ${String(mm).padStart(2, '0')}m` : `${mm}m`;
  return hh ? `${hh} h ${mm} min` : `${mm} min`;
}
const fmtHours = sec => isNum(sec) ? `${fmt(sec / 3600, 1)} h` : '—';
const fmtClock = ts => isNum(ts) ? new Date(ts * 1000).toLocaleTimeString(LOCALE, { hour: '2-digit', minute: '2-digit' }) : '—';
const fmtDateTime = ts => isNum(ts) ? new Date(ts * 1000).toLocaleString(LOCALE, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—';
function parseISO(iso) { const [y, m, d] = String(iso).split('-').map(Number); return new Date(y, (m || 1) - 1, d || 1); }
function isoOf(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
const fmtDay = (iso, opts = { weekday: 'short', day: 'numeric', month: 'short' }) => parseISO(iso).toLocaleDateString(LOCALE, opts);
const fmtDayShort = iso => parseISO(iso).toLocaleDateString(LOCALE, { day: 'numeric', month: 'short' });
function addDays(iso, n) { const d = parseISO(iso); d.setDate(d.getDate() + n); return isoOf(d); }
function ago(sec) {
  if (!isNum(sec)) return 'never';
  if (sec < 90) return 'just now';
  if (sec < 3600) return `${Math.round(sec / 60)} min ago`;
  if (sec < 86400 * 2) return `${Math.round(sec / 3600)} h ago`;
  return `${Math.round(sec / 86400)} days ago`;
}
const avg = arr => { const v = arr.filter(isNum); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
const sum = arr => { const v = arr.filter(isNum); return v.length ? v.reduce((a, b) => a + b, 0) : null; };
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const cap = str => { const t = String(str ?? ''); return t.charAt(0).toUpperCase() + t.slice(1); };

/* ================================================================== *
 * State
 * ================================================================== */
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
};
const RANGES = [{ days: 7, label: '7 days' }, { days: 28, label: '4 weeks' }, { days: 365, label: '1 year' }];
const S = {
  data: null, daysLoaded: 0, loading: false, error: null,
  fetchedAt: 0, offlineSince: null, range: Number(store.get('ph-range')) || 7,
  account: null, adminUsers: null, accountLoading: false,
};
const API_TOKENS = { tokens: [], scopes: [], loaded: false, secret: null, error: '' };
if (!RANGES.some(r => r.days === S.range)) S.range = 7;
const D = () => S.data || {};
const todayISO = () => (D().recovery && D().recovery.today) || isoOf(new Date());
const nowSec = () => D().now || Math.floor(Date.now() / 1000);

/* ================================================================== *
 * Network
 * ================================================================== */
async function api(path, method, body) {
  const res = await fetch(path, {
    method, headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-PH-Request': '1' },
    body: body ? JSON.stringify(body) : undefined, cache: 'no-store',
  });
  let json = null;
  try { json = await res.json(); } catch (e) { /* not JSON */ }
  if (res.status === 401 && json && json.error === 'login_required') { clearSessionHealth(); window.location.assign('/login'); throw new Error('Login required.'); }
  if (!res.ok) throw new Error((json && (json.error || json.detail)) || `The server answered ${res.status}.`);
  return json;
}

async function load(force) {
  if (S.loading) return;
  const want = clamp(Math.max(42, S.range), 7, 365);
  if (!force && S.data && S.daysLoaded >= want && Date.now() - S.fetchedAt < 60000) return;
  S.loading = true; setBusy(true);
  try {
    const res = await fetch(`api/summary?days=${want}`, { headers: { Accept: 'application/json', 'X-PH-Request': '1' }, cache: 'no-store' });
    if (!res.ok) {
      let msg = `The server answered ${res.status}.`;
      try { const j = await res.json(); if (j && j.error) msg = j.error; } catch (e) { /* ignore */ }
      if (res.status === 401) { clearSessionHealth(); window.location.assign('/login'); return; }
      throw new Error(msg);
    }
    const data = await res.json();
    S.offlineSince = res.headers.get('X-Offline-Fallback') ? Number(res.headers.get('X-Cached-At')) || null : null;
    if (S.offlineSince === null && res.headers.get('X-Offline-Fallback')) S.offlineSince = 0;
    S.data = data; S.daysLoaded = want; S.error = null; S.fetchedAt = Date.now();
  } catch (e) {
    S.error = e.message || 'Could not reach the server.';
    if (S.data) S.offlineSince = S.offlineSince ?? S.fetchedAt;
  } finally {
    S.loading = false; setBusy(false); render();
  }
}

function setBusy(on) {
  const b = document.getElementById('refresh-btn');
  b.classList.toggle('spin', on);
  b.setAttribute('aria-busy', on ? 'true' : 'false');
}

/* ================================================================== *
 * Shared UI pieces
 * ================================================================== */
function swatch() { return h('span', { class: 'swatch', 'aria-hidden': 'true' }); }

/* A card whose heading links to its detail view (stretched link). */
function card(m, title, opts, ...body) {
  const o = opts || {};
  const head = h('div', { class: 'card-head' }, swatch(),
    o.link ? h('h2', null, h('a', { class: 'card-link', href: `#d/${o.link}` }, title)) : h('h2', null, title),
    o.chip || null,
    o.link ? icon('chev', 'chev') : null);
  return h('article', { class: `card${o.link ? ' tappable' : ''}${o.cls ? ' ' + o.cls : ''}`, 'data-m': m }, head, body);
}
function chip(text, kind, title) { return h('span', { class: `chip ${kind || ''}`, title }, text); }
const expChip = () => chip('Experimental', 'exp', 'Not a validated medical measure');

function big(value, unit, none) {
  return h('div', { class: 'big' }, h('span', { class: `v${none ? ' none' : ''}` }, value), unit ? h('span', { class: 'u' }, unit) : null);
}
function stats(items) {
  return h('dl', { class: 'stats' }, items.filter(Boolean).map(([k, v, u]) => {
    const none = v === '—' || v == null;
    return h('div', { class: 'stat' }, h('dt', null, k), h('dd', { class: none ? 'none' : '' }, none ? 'No data' : v, u && !none ? h('small', null, ' ' + u) : null));
  }));
}
function pending(title, text, progress) {
  return h('div', { class: 'pending above' }, h('strong', null, title), text ? h('span', null, text) : null,
    progress ? [h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': progress.of, 'aria-valuenow': progress.n, 'aria-label': progress.label || title },
      h('span', { style: { width: `${clamp(100 * progress.n / Math.max(1, progress.of), 0, 100)}%` } })),
    h('p', { class: 'progress-label' }, `${progress.n} of ${progress.of} ${progress.unit || ''}`.trim())] : null);
}
function info(summary, ...paras) {
  return h('details', { class: 'info' }, h('summary', null, summary || 'How this works'), paras.filter(Boolean).map(p => h('p', null, p)));
}
function missingList(items) {
  if (!items || !items.length) return null;
  return h('ul', { class: 'missing above', 'aria-label': 'Missing inputs' }, items.map(t => h('li', null, humanMissing(t))));
}
/* "hrv: no usable overnight measurement" → "HRV: no usable overnight measurement" */
function humanMissing(t) {
  const str = String(t ?? '');
  const m = str.match(/^([a-z_]+):\s*(.*)$/);
  if (!m) return str;
  return `${COMPONENT_NAMES[m[1]] || cap(m[1].replace(/_/g, ' '))}: ${m[2]}`;
}
const COMPONENT_NAMES = { hrv: 'HRV', resting_hr: 'Resting heart rate', sleep: 'Sleep', training_load: 'Training load', duration: 'Duration', regularity: 'Regularity' };

function rangeSwitch() {
  return h('div', { class: 'seg', role: 'group', 'aria-label': 'Time range' }, RANGES.map(r =>
    h('button', { type: 'button', 'aria-pressed': String(S.range === r.days), onclick: () => setRange(r.days) }, r.label)));
}
function setRange(days) {
  S.range = days; store.set('ph-range', String(days));
  const want = Math.max(42, days);
  if (S.daysLoaded < want) load(true); else render();
}

/* ================================================================== *
 * Charts (inline SVG)
 * ================================================================== */
function dateSpan(n, end) {
  const last = end || todayISO();
  const out = [];
  for (let i = n - 1; i >= 0; i--) out.push(addDays(last, -i));
  return out;
}
function niceMax(v) {
  if (!isNum(v) || v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v))), n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}

/* Group daily points into weeks for the 1-year view so bars stay legible. */
function bucket(dates, getter, mode) {
  if (dates.length <= 60) return dates.map(d => ({ key: d, label: d, ...getter(d) }));
  const out = [];
  for (let i = 0; i < dates.length; i += 7) {
    const chunk = dates.slice(i, i + 7), rows = chunk.map(getter), vals = rows.map(r => r.v).filter(isNum);
    const v = !vals.length ? null : mode === 'sum' ? vals.reduce((a, b) => a + b, 0) : vals.reduce((a, b) => a + b, 0) / vals.length;
    const partial = mode === 'sum' && vals.length > 0 && rows.some(r => !isNum(r.v));
    out.push({ key: chunk[0], label: chunk[0], end: chunk[chunk.length - 1], v, lo: avgOrNull(rows.map(r => r.lo)), hi: avgOrNull(rows.map(r => r.hi)), cls: partial ? 'partial' : undefined, n: vals.length, week: true });
  }
  return out;
}
const avgOrNull = a => avg(a);

function xLabels(items, W, x0, bw, H) {
  const g = [];
  if (!items.length) return g;
  const idx = items.length <= 7 ? items.map((_, i) => i) : [0, Math.floor((items.length - 1) / 2), items.length - 1];
  idx.forEach(i => {
    const it = items[i];
    const daily = items.length <= 7 && !it.week;
    const label = daily ? fmtDay(it.label, { weekday: 'short' }) : fmtDayShort(it.label);
    const anchor = items.length <= 7 ? 'middle' : i === 0 ? 'start' : i === items.length - 1 ? 'end' : 'middle';
    const x = anchor === 'start' ? x0 + i * bw : anchor === 'end' ? x0 + (i + 1) * bw : x0 + (i + .5) * bw;
    g.push(s('text', { x, y: H - 4, 'text-anchor': anchor }, label));
  });
  return g;
}
function tipLabel(it) {
  return it.week ? `Week of ${fmtDayShort(it.key)}` : fmtDay(it.key);
}

/* Bar chart. items: [{key,label,v,cls,lo?}] */
function barChart({ items, W = 340, H = 150, fmtV = v => fmt(v), unit = '', ref, label, max, minBar = 0 }) {
  const top = 10, bottom = 22, left = 30, right = 6, ph = H - top - bottom, pw = W - left - right;
  const vals = items.map(i => i.v).filter(isNum);
  const ymax = niceMax(Math.max(max || 0, ...(vals.length ? vals : [1]), ref ? ref.v : 0));
  const bw = pw / Math.max(1, items.length), gap = items.length > 40 ? 0.5 : Math.min(6, bw * .25);
  const y = v => top + ph - (v / ymax) * ph;
  const kids = [];
  for (let i = 0; i <= 2; i++) {
    const v = ymax * i / 2, yy = y(v);
    kids.push(s('line', { class: `grid${i === 0 ? ' zero' : ''}`, x1: left, x2: W - right, y1: yy, y2: yy }));
    kids.push(s('text', { x: left - 6, y: yy + 3.5, 'text-anchor': 'end' }, fmtAxis(v)));
  }
  items.forEach((it, i) => {
    const x = left + i * bw + gap / 2, w = Math.max(1, bw - gap);
    if (isNum(it.v)) {
      const hgt = Math.max(minBar, ph * it.v / ymax);
      const r = s('rect', { class: `bar${it.cls ? ' ' + it.cls : ''}`, x, y: top + ph - hgt, width: w, height: Math.max(hgt, it.v > 0 ? 1.5 : 0), rx: Math.min(3, w / 3) },
        s('title', null, `${tipLabel(it)}: ${fmtV(it.v)}${unit ? ' ' + unit : ''}${it.note ? ' (' + it.note + ')' : ''}`));
      kids.push(r);
      if (isNum(it.inner) && it.inner > 0) {
        const ih = Math.max(1, ph * it.inner / ymax);
        kids.push(s('rect', { class: 'bar', x, y: top + ph - ih, width: w, height: ih, rx: Math.min(3, w / 3) }, s('title', null, `${tipLabel(it)}: ${fmtV(it.v)} ${unit}, restful ${fmtV(it.inner)}`)));
      }
    } else {
      kids.push(s('rect', { class: 'gapmark', x, y: top + ph - 2, width: w, height: 2 }, s('title', null, `${tipLabel(it)}: ${it.cls === 'rest' ? 'rest day' : 'no data'}`)));
    }
  });
  if (ref && isNum(ref.v)) {
    const yy = y(ref.v);
    kids.push(s('line', { class: 'ref', x1: left, x2: W - right, y1: yy, y2: yy }));
    kids.push(s('text', { class: 'ref-label', x: W - right, y: yy - 4, 'text-anchor': 'end' }, ref.label));
  }
  kids.push(...xLabels(items, W, left, bw, H));
  return s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label || 'Bar chart' }, kids);
}
function fmtAxis(v) {
  if (v >= 10000) return `${fmt(v / 1000, 0)}k`;
  if (v >= 1000) return `${fmt(v / 1000, 1)}k`;
  return fmt(v, v < 10 && v % 1 ? 1 : 0);
}

/* Line chart with gaps, optional usual-range band and optional second series. */
function lineChart({ items, W = 340, H = 150, fmtV = v => fmt(v), unit = '', band, label, alt, dots = true, range, zeroBase }) {
  const top = 10, bottom = 22, left = 30, right = 6, ph = H - top - bottom, pw = W - left - right;
  const all = [];
  items.forEach(i => { all.push(i.v, i.lo, i.hi); if (alt) all.push(i.alt); });
  if (band) all.push(band.lo, band.hi);
  let vals = all.filter(isNum);
  if (!vals.length) vals = [0, 1];
  let lo = range ? range[0] : Math.min(...vals), hi = range ? range[1] : Math.max(...vals);
  if (zeroBase) lo = Math.min(0, lo);
  if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * .12; if (!range) { lo = zeroBase ? lo : lo - pad; hi += pad; }
  const step = niceMax((hi - lo) / 2) / 2 || 1;
  lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
  const bw = pw / Math.max(1, items.length);
  const X = i => left + (i + .5) * bw, Y = v => top + ph - ((v - lo) / (hi - lo)) * ph;
  const kids = [];
  const ticks = [lo, (lo + hi) / 2, hi];
  ticks.forEach((v, i) => {
    kids.push(s('line', { class: `grid${i === 0 ? ' zero' : ''}`, x1: left, x2: W - right, y1: Y(v), y2: Y(v) }));
    kids.push(s('text', { x: left - 6, y: Y(v) + 3.5, 'text-anchor': 'end' }, fmtAxis(v)));
  });
  if (band && isNum(band.lo) && isNum(band.hi)) {
    kids.push(s('rect', { class: 'band', x: left, width: pw, y: Y(band.hi), height: Math.max(1, Y(band.lo) - Y(band.hi)) }, s('title', null, `${band.label || 'Usual range'}: ${fmtV(band.lo)}–${fmtV(band.hi)} ${unit}`)));
  }
  const path = key => {
    let d = '', open = false;
    items.forEach((it, i) => {
      if (isNum(it[key])) { d += `${open && !it.breakBefore ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(it[key]).toFixed(1)}`; open = true; } else open = false;
    });
    return d;
  };
  items.forEach((it, i) => {
    if (isNum(it.lo) && isNum(it.hi)) kids.push(s('line', { x1: X(i), x2: X(i), y1: Y(it.lo), y2: Y(it.hi), stroke: 'var(--mc)', 'stroke-opacity': .35, 'stroke-width': Math.max(2, Math.min(8, bw * .6)), 'stroke-linecap': 'round' }));
  });
  if (alt) { const da = path('alt'); if (da) kids.push(s('path', { class: 'line alt', d: da })); }
  const d = path('v');
  if (d) kids.push(s('path', { class: 'line', d }));
  const showDots = dots && items.length <= 60;
  items.forEach((it, i) => {
    if (isNum(it.v)) {
      const isolated = !isNum((items[i - 1] || {}).v) && !isNum((items[i + 1] || {}).v);
      if (showDots || isolated) kids.push(s('circle', { class: `dot${it.hollow ? ' hollow' : ''}`, cx: X(i), cy: Y(it.v), r: items.length > 30 ? 2.6 : 3.6 }, s('title', null, `${tipLabel(it)}: ${fmtV(it.v)} ${unit}${it.note ? ' (' + it.note + ')' : ''}`)));
    } else if (items.length <= 60) {
      kids.push(s('rect', { class: 'gapmark', x: X(i) - Math.min(4, bw * .35), y: top + ph - 2, width: Math.min(8, bw * .7), height: 2 }, s('title', null, `${tipLabel(it)}: no data`)));
    }
  });
  kids.push(...xLabels(items, W, left, bw, H));
  return s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label || 'Line chart' }, kids);
}

/* Tiny axis-free sparkline for the watch tiles: real gaps stay visible, no grid or labels. */
function sparkline({ items, unit = '', label, fmtV = v => fmt(v), fmtTip, bars, zeroBase = true }) {
  const vals = items.map(i => i.v).filter(isNum);
  if (!vals.length) return null;
  const tip = it => `${fmtTip ? fmtTip(it) : tipLabel(it)}: ${fmtV(it.v)}${unit ? ' ' + unit : ''}${it.note ? ' (' + it.note + ')' : ''}`;
  const W = 120, H = 32, top = 3, ph = H - 2 * top;
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (bars || zeroBase) lo = Math.min(0, lo);
  if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * .15;
  if (!(bars || zeroBase)) lo -= pad;
  hi += pad;
  const bw = W / Math.max(1, items.length);
  const X = i => i * bw + bw / 2, Y = v => top + ph - ((v - lo) / (hi - lo)) * ph;
  const kids = [];
  if (bars) {
    items.forEach((it, i) => {
      const x = i * bw + .75, w = Math.max(1, bw - 1.5);
      if (isNum(it.v)) kids.push(s('rect', { class: `spark-bar${it.cls ? ' ' + it.cls : ''}`, x, y: Y(it.v), width: w, height: Math.max(1.2, top + ph - Y(it.v)), rx: Math.min(1.5, w / 3) }, s('title', null, tip(it))));
      else kids.push(s('rect', { class: 'gapmark', x, y: top + ph - 1.5, width: w, height: 1.5 }, s('title', null, `${fmtTip ? fmtTip(it) : tipLabel(it)}: no data`)));
    });
  } else {
    let d = '', open = false;
    items.forEach((it, i) => { if (isNum(it.v)) { d += `${open ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(it.v).toFixed(1)}`; open = true; } else open = false; });
    if (d) kids.push(s('path', { class: 'spark-line', d }));
    // Dense series (battery observations) draw as a line; dots only where they stay readable.
    if (items.length <= 60) items.forEach((it, i) => {
      if (isNum(it.v)) kids.push(s('circle', { class: 'spark-dot', cx: X(i), cy: Y(it.v), r: 2.2 }, s('title', null, tip(it))));
    });
  }
  return s('svg', { class: 'watch-spark', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label || 'Trend' }, kids);
}

/* Score ring 0–100. */
function ring(score, { size = 120, stroke = 11, sub, label, draw = true } = {}) {
  const r = (size - stroke) / 2 - 1, c = 2 * Math.PI * r, cx = size / 2;
  const kids = [s('circle', { class: 'ring-track', cx, cy: cx, r, 'stroke-width': stroke })];
  if (isNum(score)) {
    const len = c * clamp(score, 0, 100) / 100;
    kids.push(s('circle', {
      class: `ring-val${draw ? ' draw' : ''}`, cx, cy: cx, r, 'stroke-width': stroke,
      'stroke-dasharray': `${len} ${c}`, transform: `rotate(-90 ${cx} ${cx})`, style: `--len:${len}`,
    }));
    kids.push(s('text', { class: 'ring-text', x: cx, y: cx + size * .11, 'text-anchor': 'middle', 'font-size': size * .32 }, String(Math.round(score))));
  } else {
    kids.push(s('circle', { class: 'ring-empty', cx, cy: cx, r, 'stroke-width': 2 }));
    kids.push(s('text', { class: 'ring-text', x: cx, y: cx + size * .09, 'text-anchor': 'middle', 'font-size': size * .26, opacity: .55 }, '—'));
  }
  if (sub) kids.push(s('text', { class: 'ring-sub', x: cx, y: cx + size * .27, 'text-anchor': 'middle' }, sub));
  return s('svg', { viewBox: `0 0 ${size} ${size}`, role: 'img', 'aria-label': label || (isNum(score) ? `Score ${Math.round(score)} of 100` : 'No score') }, kids);
}

/* HRV status gauge: half circle, usual range band, weekly-average needle. */
function hrvGauge(st, W = 240) {
  const H = W * .62, cx = W / 2, cy = H - 14, R = W * .4, sw = W * .07;
  const lo = st.baseline_low_ms, hi = st.baseline_high_ms, wk = st.weekly_rmssd_ms;
  const ready = isNum(lo) && isNum(hi);
  const vals = [lo, hi, wk, st.last_night_rmssd_ms].filter(isNum);
  const dmin = ready ? Math.max(0, Math.min(...vals) - (hi - lo) * 1.1) : 0;
  const dmax = ready ? Math.max(...vals) + (hi - lo) * 1.1 : 1;
  const ang = v => Math.PI * (1 - clamp((v - dmin) / (dmax - dmin), 0, 1));
  const pt = (a, rr) => [cx + rr * Math.cos(a), cy - rr * Math.sin(a)];
  const arc = (a0, a1, rr) => { const [x0, y0] = pt(a0, rr), [x1, y1] = pt(a1, rr); return `M${x0.toFixed(1)} ${y0.toFixed(1)}A${rr} ${rr} 0 0 1 ${x1.toFixed(1)} ${y1.toFixed(1)}`; };
  const kids = [s('path', { d: arc(Math.PI, 0, R), fill: 'none', stroke: 'var(--card-2)', 'stroke-width': sw, 'stroke-linecap': 'round' })];
  if (ready) {
    kids.push(s('path', { d: arc(ang(lo), ang(hi), R), fill: 'none', stroke: 'var(--mc)', 'stroke-opacity': .45, 'stroke-width': sw }, s('title', null, `Usual range ${fmt(lo)}–${fmt(hi)} ms`)));
    [[lo, 'start'], [hi, 'end']].forEach(([v]) => {
      const [x, y] = pt(ang(v), R + sw * .9);
      kids.push(s('text', { x, y: y + 3, 'text-anchor': 'middle' }, fmt(v)));
    });
    if (isNum(wk)) {
      const a = ang(wk), [x0, y0] = pt(a, R - sw * 1.2), [x1, y1] = pt(a, R + sw * .55);
      kids.push(s('line', { x1: x0, y1: y0, x2: x1, y2: y1, stroke: 'var(--ink)', 'stroke-width': 3.5, 'stroke-linecap': 'round' }));
      kids.push(s('text', { class: 'lbl-strong', x: cx, y: cy - 6, 'text-anchor': 'middle', 'font-size': W * .14, style: 'font-family:var(--font-num);font-size:' + (W * .14) + 'px' }, fmt(wk)));
      kids.push(s('text', { x: cx, y: cy + 10, 'text-anchor': 'middle' }, 'ms, 7-night average'));
    }
  } else {
    kids.push(s('path', { d: arc(Math.PI, 0, R), fill: 'none', stroke: 'var(--ink-3)', 'stroke-width': 2, 'stroke-dasharray': '2 6', 'stroke-linecap': 'round' }));
    kids.push(s('text', { x: cx, y: cy - 4, 'text-anchor': 'middle' }, 'Usual range not set yet'));
  }
  const lab = ready ? `HRV gauge: 7-night average ${fmt(wk)} ms, usual range ${fmt(lo)} to ${fmt(hi)} ms` : 'HRV gauge: usual range still being learned';
  return s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': lab, style: 'max-width:300px;margin-inline:auto' }, kids);
}

/* Sleep timing: one row per night, bar from onset to wake on an 18:00→14:00 axis. */
function timingChart(nights, W = 340) {
  const rows = nights.filter(n => isNum(n.onset) && isNum(n.wake));
  const rowH = rows.length > 14 ? 9 : 16, top = 6, bottom = 22, left = 50, right = 8, pw = W - left - right;
  const H = top + bottom + rows.length * rowH;
  const START = 18, SPAN = 20; // hours
  const hourOf = ts => { const d = new Date(ts * 1000); let hr = d.getHours() + d.getMinutes() / 60; if (hr < START - 6) hr += 24; return hr; };
  const X = hr => left + clamp((hr - START) / SPAN, 0, 1) * pw;
  const kids = [];
  [18, 22, 26, 30, 34, 38].forEach(hr => {
    kids.push(s('line', { class: 'grid', x1: X(hr), x2: X(hr), y1: top, y2: H - bottom }));
    kids.push(s('text', { x: X(hr), y: H - 6, 'text-anchor': 'middle' }, `${String(hr % 24).padStart(2, '0')}:00`));
  });
  rows.forEach((n, i) => {
    const y = top + i * rowH;
    let a = hourOf(n.onset), b = a + (n.wake - n.onset) / 3600;
    kids.push(s('rect', { class: 'bar', x: X(a), y: y + 2, width: Math.max(2, X(b) - X(a)), height: rowH - 4, rx: (rowH - 4) / 2 },
      s('title', null, `${fmtDay(n.night)}: ${fmtClock(n.onset)} to ${fmtClock(n.wake)}`)));
    if (rows.length <= 14) kids.push(s('text', { x: left - 6, y: y + rowH / 2 + 3.5, 'text-anchor': 'end' }, fmtDay(n.night, { weekday: 'short', day: 'numeric' })));
  });
  return s('svg', { class: 'chart timing', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Sleep timing per night' }, kids);
}

/* Intraday chart on a 0–24 h axis. points: [{t (hours), v}], bars: true for hourly bars. */
function dayChart({ points, bars, W = 340, H = 150, unit = '', label, fmtV = v => fmt(v), hollow }) {
  const top = 10, bottom = 22, left = 30, right = 6, ph = H - top - bottom, pw = W - left - right;
  const vals = points.map(p => p.v).filter(isNum);
  let lo = bars ? 0 : Math.min(...vals), hi = Math.max(...vals, 1);
  if (!bars) { const pad = Math.max(4, (hi - lo) * .1); lo = Math.max(0, Math.floor((lo - pad) / 10) * 10); hi = Math.ceil((hi + pad) / 10) * 10; }
  else hi = niceMax(hi);
  const X = t => left + (t / 24) * pw, Y = v => top + ph - ((v - lo) / (hi - lo || 1)) * ph;
  const kids = [];
  [lo, (lo + hi) / 2, hi].forEach((v, i) => {
    kids.push(s('line', { class: `grid${i === 0 ? ' zero' : ''}`, x1: left, x2: W - right, y1: Y(v), y2: Y(v) }));
    kids.push(s('text', { x: left - 6, y: Y(v) + 3.5, 'text-anchor': 'end' }, fmtAxis(v)));
  });
  [0, 6, 12, 18, 24].forEach(t => kids.push(s('text', { x: X(t), y: H - 4, 'text-anchor': t === 0 ? 'start' : t === 24 ? 'end' : 'middle' }, `${String(t % 24).padStart(2, '0')}:00`)));
  if (bars) {
    const bw = pw / 24;
    points.forEach(p => { if (isNum(p.v) && p.v > 0) kids.push(s('rect', { class: 'bar', x: X(p.t) + 1, width: bw - 2, y: Y(p.v), height: Y(0) - Y(p.v), rx: 2 }, s('title', null, `${String(p.t).padStart(2, '0')}:00: ${fmtV(p.v)} ${unit}`))); });
  } else {
    let d = '', prev = null;
    points.filter(p => !p.snapshot).forEach(p => {
      d += `${prev !== null && p.t - prev < 6 / 60 ? 'L' : 'M'}${X(p.t).toFixed(1)} ${Y(p.v).toFixed(1)}`; prev = p.t;
    });
    if (d) kids.push(s('path', { class: 'line', d, 'stroke-width': 1.6 }));
    points.forEach(p => {
      const lone = !p.snapshot && !points.some(q => q !== p && !q.snapshot && Math.abs(q.t - p.t) < 6 / 60);
      if (p.snapshot || lone) kids.push(s('circle', { class: `dot${p.snapshot ? ' hollow' : ''}`, cx: X(p.t), cy: Y(p.v), r: 3.2 }, s('title', null, `${hourLabel(p.t)}: ${fmtV(p.v)} ${unit}${p.snapshot ? ' (hourly snapshot)' : ''}`)));
    });
  }
  return s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label || 'Today' }, kids);
}
const hourLabel = t => `${String(Math.floor(t)).padStart(2, '0')}:${String(Math.round((t % 1) * 60)).padStart(2, '0')}`;

function legend(items) {
  return h('div', { class: 'legend' }, items.map(([cls, text]) => h('span', null, h('i', { class: cls }), text)));
}

function stockVariabilityDetail() {
  const model=stockVariability(), all=(model.points||[]).filter(p=>isNum(p.ts)&&isNum(p.value_ms));
  const latest=all.at(-1), context=latest?.context, source=latest?.source;
  const points=all.filter(p=>(context == null || p.context===context)&&(source == null || p.source===source));
  if (!points.length) return null;
  const items=points.map(p=>({key:new Date(p.ts*1000).toISOString().slice(0,10),label:new Date(p.ts*1000).toISOString().slice(0,10),v:p.value_ms}));
  return h('details',{class:'info'},h('summary',null,'Delivered PPI variability diagnostic (not HRV)'),
    h('div',{class:'hrv-proxy-series'},lineChart({items,W:chartW(),H:160,unit:'ms',label:'Delivered pulse variability (unvalidated)',fmtV:v=>fmt(v,1)})),
    h('p',{class:'foot'},'Unvalidated diagnostic of differences between delivered pulse intervals. This is not an HRV approximation: beat order, continuity and missing intervals are unknown. It never feeds readiness or stress.'),
    h('p',{class:'foot'},`Method: ${model.method || 'delivered_ppi_variation_unverified'}; showing ${context || 'the latest'}${source ? ` · ${source}` : ''} series.`));
}

/* ================================================================== *
 * Data accessors
 * ================================================================== */
const rec = () => D().recovery || {};
const stock = () => D().stock_estimates || {};
const stockPulse = () => stock().pulse || {};
const stockStrain = () => stock().strain || {};
function stockStrainFresh(model, now=Date.now()/1000) {
  return isNum(model.score) && isNum(model.measured_at) && now >= model.measured_at && now-model.measured_at <= 36*3600;
}
function readinessNow() {
  const r=rec().readiness || {};
  if (r.formula_version==='readiness-stock-v1' && rec().today!==isoOf(new Date()))
    return {...r,score:null,sleep_based_score:null,status:'stale',reason:'This is a cached earlier day. Refresh for today’s readiness.'};
  return r;
}
const stockVariability = () => stock().variability || {};
const ppiSourceUnverified = () => D().hrv?.quality?.stream === 'batched_ppi_unverified';
const PPI_SOURCE_EXPLANATION = 'Very rough, unvalidated HRV proxy from differences between delivered optical pulse intervals. Batching, unknown beat order and missing intervals may distort the value; it is not verified beat-to-beat RMSSD. Firmware support for consecutive beat timing and gaps should enable a better estimate, which will still need validation. Excluded from readiness and stress.';
const latestPpiProxy = () => (stockVariability().points || []).filter(p=>isNum(p.ts)&&isNum(p.value_ms)).sort((a,b)=>a.ts-b.ts).at(-1);
const BREATH_SOURCE_EXPLANATION = 'No defensible breaths/min approximation is available from the current batched pulse intervals. Their timing and continuity are unknown, so a breathing rhythm cannot be established. We are waiting for beat-timing support, then validation of the breathing estimate. More recordings alone will not resolve this.';
function ppiVariabilityDiagnostic() {
  const latest=latestPpiProxy();
  return latest ? [big(fmt(latest.value_ms,1),'ms · HRV proxy estimate'),
    h('p',{class:'lede'},`Recorded ${fmtDateTime(latest.ts)} · ${latest.context || 'unspecified context'}`),
    h('p',{class:'pending'},PPI_SOURCE_EXPLANATION)]
    : pending('No HRV proxy recording yet',PPI_SOURCE_EXPLANATION);
}
function hrvProxyGraph(span) {
  const all=(stockVariability().points || []).filter(p=>isNum(p.ts)&&isNum(p.value_ms)).sort((a,b)=>a.ts-b.ts);
  const charts=['scheduled','manual'].map(context=>{
    const points=all.filter(p=>p.context===context), items=[];
    const width=span.length>60 ? 7 : 1;
    for (let i=0;i<span.length;i+=width) {
      const dates=span.slice(i,i+width), rows=points.filter(p=>dates.includes(isoOf(new Date(p.ts*1000))));
      const latest=rows.at(-1), comparable=latest ? rows.filter(p=>p.source===latest.source) : [];
      const prior=items.at(-1);
      items.push({key:dates[0],label:dates[0],end:dates.at(-1),week:width>1,
        v:avg(comparable.map(p=>p.value_ms)),source:latest?.source,
        breakBefore:!!prior && prior.source!==latest?.source,
        note:latest ? `${comparable.length} recordings · ${latest.source || 'unknown source'}${rows.length>comparable.length ? ' · latest source only; other versions excluded' : ''}` : undefined});
    }
    if (!items.some(p=>isNum(p.v))) return null;
    const label=context==='scheduled' ? 'Scheduled overnight estimates' : 'Manual estimates';
    const content=[
      lineChart({items,W:chartW(),H:180,unit:'ms',fmtV:v=>fmt(v,1),label:`Unvalidated HRV proxy: ${label.toLowerCase()}, daily means`}),
      legend([['line','Unvalidated HRV proxy estimate'],['gap','No recording']]),
      h('p',{class:'foot'},`Yellow: unreliable delivered-PPI variability, not verified RMSSD. ${context==='scheduled' ? 'Received 02:00, 03:00 and 04:00 recordings contribute to their date’s mean; missing uploads are excluded.' : 'Manual recordings only.'} ${width>1 ? 'Grouped by week. ' : ''}Line breaks mark source changes. Where versions overlap, only the latest source in that period is averaged. Excluded from readiness and stress.`)];
    return context==='manual'
      ? h('details',{class:'info hrv-proxy-series'},h('summary',null,'Manual test estimates'),content)
      : h('div',{class:'hrv-proxy-series'},h('p',{class:'lede'},label),content);
  }).filter(Boolean);
  return charts.length ? charts : null;
}
function monitorExplanation(kind) {
  const diag=D().monitor_observations?.diagnostics?.[kind] || {};
  const labels={beat_continuity_unverified:'Consecutive-beat continuity is unverified',motion_uncalibrated:'Motion calibration has not been validated',motion_unknown:'Motion evidence is missing',quality_insufficient:'Interval quality is insufficient',strict_qualification_missing:'No clear qualified breathing rhythm',reported_hr_missing:'No direct pulse summary',reported_hr_invalid:'Invalid pulse summary'};
  const reasons=Object.entries(diag.exclusion_reasons || {}).map(([key,count])=>`${labels[key] || key.replaceAll('_',' ')} (${count})`).join('; ');
  return `${diag.received ?? 0} recordings received; ${diag.eligible ?? 0} eligible.${reasons ? ' '+reasons+'.' : ''}${diag.last_measured_at ? ' Latest capture: '+fmtDateTime(diag.last_measured_at)+'.' : ''}`;
}
const byNight = (arr, key) => { const m = new Map(); (arr || []).forEach(r => { if (r && r[key]) m.set(r[key], r); }); return m; };
function nightItems(n, key) {
  const m = byNight(rec().nights, 'night');
  return dateSpan(n).map(d => ({ key: d, label: d, v: (m.get(d) || {})[key] ?? null }));
}
function lastNight() { const n = rec().nights || []; return n.length ? n[n.length - 1] : null; }
const isLastNight = n => n && n.night === todayISO();

function obsByLocalDay() {
  const out = new Map();
  (D().observations || []).forEach(o => {
    if (!o || !isNum(o.ts)) return;
    const d = isoOf(new Date(o.ts * 1000));
    if (!out.has(d)) out.set(d, []);
    out.get(d).push(o);
  });
  return out;
}
function todayObs() {
  const today = isoOf(new Date());
  return (obsByLocalDay().get(today) || []).slice().sort((a, b) => a.ts - b.ts);
}
const hourOfTs = ts => { const d = new Date(ts * 1000); return d.getHours() + d.getMinutes() / 60; };
const historyMap = () => byNight(D().history || (D().training || {}).history, 'date');
const wearer = () => { const w = D().wearer; return typeof w === 'string' && w.trim() ? w.trim().slice(0, 60) : ''; };

const HRV_LABEL = {
  balanced: ['Balanced', 'ok'], unbalanced_low: ['Unbalanced, low', 'warn'], unbalanced_high: ['Unbalanced, high', 'warn'],
  low: ['Low', 'bad'], insufficient: ['Not enough nights', ''], baseline_building: ['Building baseline', ''],
};
const hrvLabel = st => HRV_LABEL[st] || [cap(String(st || 'No data').replace(/_/g, ' ')), ''];

function readinessWord(score) {
  if (!isNum(score)) return 'Not enough data';
  if (score >= 75) return 'High';
  if (score >= 55) return 'Moderate';
  if (score >= 35) return 'Low';
  return 'Very low';
}
function sleepWord(score) {
  if (!isNum(score)) return 'No score';
  if (score >= 90) return 'Excellent'; if (score >= 80) return 'Good'; if (score >= 60) return 'Fair'; return 'Poor';
}
const TRAIN_STATUS = { ready: 'Tracking', warming: 'Building baseline' };

/* ================================================================== *
 * Cards
 * ================================================================== */
/* Weight: daily points plus the 7-day trend on the same date spine. */
const signedKg = v => isNum(v) ? `${v > 0 ? '+' : v < 0 ? '−' : '±'}${fmt(Math.abs(v), 1)}` : '—';
function weightItems(span) {
  const m = new Map(((D().weight || {}).entries || []).map(e => [e.date, e]));
  const items = bucket(span, d => ({ v: (m.get(d) || {}).kg ?? null, alt: (m.get(d) || {}).trend_kg ?? null }), 'avg');
  // Weekly buckets (1-year view) keep the trend too.
  return span.length > 60 ? items.map((i, k) => ({ ...i, alt: avg(span.slice(k * 7, k * 7 + 7).map(d => (m.get(d) || {}).trend_kg)) })) : items;
}

const CARDS = {
  fitness() {
    const f = D().fitness;
    if (!f) return null;
    const v = f.vo2max;
    return card('ready', 'Fitness (VO\u2082max)', { chip: chip('Estimate', '', 'Estimated from your profile, not measured in exercise') },
      v ? [big(fmt(v.value, 1), 'mL/kg/min'),
        stats([['Your age', fmt(f.age), 'years'], ['BMI', fmt(v.inputs.bmi, 1)], ['Activity rating', `${v.inputs.pa_rating} of 7`]]),
        info('How this is estimated',
          'VO\u2082max comes from a validated non-exercise model (Jackson et al. 1990) using your age, sex, BMI from your weight trend, and an activity rating from your intensity minutes over the last four weeks. It typically lands within about 15% of a lab test.',
          'Fitness age is hidden until a measured VO\u2082max is available: against population norms, a profile estimate is too uncertain to be useful.',
          'A walking-based estimate from heart rate and pace is not shown: on the Pebble, wrist heart rate during walking often locks onto arm swing.')]
        : pending('Not enough profile data', (f.missing || []).length ? `Missing: ${f.missing.join(', ')}.` : 'Needs age, sex, height and weight.'));
  },

  intensity() {
    const f = D().fitness, it = f && f.intensity;
    if (!it) return null;
    const days = new Map(it.days.map(d => [d.date, d]));
    const items = dateSpan(7).map(d => { const r = days.get(d); return { key: d, label: d, v: r ? r.moderate + 2 * r.vigorous : 0 }; });
    return card('train', 'Intensity minutes', {},
      big(fmt(it.this_week), `of ${it.goal} this week`),
      h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': it.goal, 'aria-valuenow': it.this_week, 'aria-label': 'Weekly intensity minutes' },
        h('span', { style: { width: `${clamp(100 * it.this_week / it.goal, 0, 100)}%` } })),
      barChart({ items, H: 100, unit: 'min', label: 'Intensity minutes, last 7 days' }),
      info('How intensity minutes are counted',
        `Minutes at 64% of your maximum heart rate (${fmt(f.hr_max)} bpm) count as moderate, at 77% as vigorous, and vigorous minutes count double, as in the WHO guideline of 150 minutes a week.`,
        `Minutes where the watch's heart rate matched your step rhythm are left out (${fmt(it.cadence_lock_rejected)} in the last 5 weeks): that is the sensor following arm swing, not your pulse.`));
  },

  energy() {
    const f = D().fitness, e = f && f.energy;
    if (!e) return null;
    return card('steps', 'Energy', {},
      stats([['Resting burn', fmt(e.bmr_kcal), 'kcal/day'], ['Active today', isNum(e.active_kcal_today) ? fmt(e.active_kcal_today) : '—', 'kcal'],
        ['Day total', isNum(e.active_kcal_today) ? fmt(e.bmr_kcal + e.active_kcal_today) : '—', 'kcal']]),
      info('About these numbers', 'Resting burn uses the Mifflin-St Jeor equation from your weight, height, age and sex. Active calories are the watch\'s own figure, which can run high; "total" adds the full day\'s resting burn.'));
  },

  weight() {
    const w = D().weight;
    if (!w || !w.latest) return null;
    const stale = w.days_since_latest > 0;
    return card('weight', 'Weight', { link: 'weight' },
      big(fmt(w.latest.kg, 1), stale ? `kg · ${fmtDayShort(w.latest.date)}` : 'kg today'),
      h('p', {class:'foot'}, h('a', {href:'#d/weight',class:'card-link'}, 'Body fat, muscle and body composition →')),
      stats([['7-day trend', fmt(w.latest.trend_kg, 1), 'kg'], ['Last week', signedKg(w.change_7d_kg), 'kg'], ['Last 4 weeks', signedKg(w.change_28d_kg), 'kg']]),
      ...weightGraph(dateSpan(28), 110, false));
  },
  sleep() {
    const sl = rec().sleep || {}, nights = rec().sleep_nights || [];
    const has = isNum(sl.sleep_s);
    const last = nights[nights.length - 1];
    const word = isNum(sl.score) ? sleepWord(sl.score) : null;
    return card('sleep', 'Sleep', { link: 'sleep', cls: 'span2', chip: sl.status === 'duration_only' ? chip('Duration only', '', sl.reason) : null },
      has ? [
        h('div', { class: 'big' }, h('span', { class: 'v' }, fmtDur(sl.sleep_s, true)), isNum(sl.score) ? h('span', { class: 'u' }, `score ${sl.score}, ${word.toLowerCase()}`) : null),
        stats([['Restful', fmtDur(sl.restful_s, true)], ['Need', fmtDur(sl.need_s, true)],
          last && isNum(last.onset) ? ['Asleep', `${fmtClock(last.onset)}`] : null]),
        barChart({ items: dateSpan(7).map(d => { const n = byNight(nights, 'night').get(d) || {}; return { key: d, label: d, v: isNum(n.sleep_s) ? n.sleep_s / 3600 : null, inner: isNum(n.restful_s) ? n.restful_s / 3600 : null, cls: 'soft' }; }), H: 110, fmtV: v => fmt(v, 1), unit: 'h', ref: isNum(sl.need_s) ? { v: sl.need_s / 3600, label: 'need' } : null, label: 'Sleep per night, last 7 nights' }),
      ] : pending('No sleep recorded for last night', sl.reason || 'Wear the watch to bed; the night appears after the morning sync.'));
  },

  hrv() {
    const st = rec().hrv_status || {};
    const [word, kind] = hrvLabel(st.status);
    const building = st.status === 'baseline_building';
    return card('hrv', 'HRV status', { link: 'hrv', chip: st.provisional ? chip('Provisional', '', st.reason) : expChip() },
      h('p', { class: 'status-word', style: { fontSize: '20px' } }, ppiSourceUnverified() && !isNum(st.last_night_rmssd_ms) ? 'Unvalidated estimate' : word),
      ppiSourceUnverified() && !isNum(st.last_night_rmssd_ms)
        ? ppiVariabilityDiagnostic()
        : building
        ? pending('Learning your usual range', 'HRV is measured by short recordings at night. A usual range needs enough earlier nights.',
          { n: st.baseline_nights || 0, of: st.required_baseline_nights || 14, unit: 'nights', label: 'Baseline nights' })
        : [hrvGauge(st), stats([['Last night', fmt(st.last_night_rmssd_ms), 'ms'], ['Nights this week', isNum(st.nights_this_week) ? `${st.nights_this_week} of 7` : '—']])],
      !building && st.reason ? h('p', { class: 'lede' }, st.reason) : null);
  },

  rhr() {
    const model=stockPulse(), rows=model.points || D().monitor_observations?.nightly_pulse || [], latest=model.latest || rows.at(-1);
    const map=byNight(rows,'night'),items=dateSpan(7).map(day=>({key:day,label:day,v:map.get(day)?.pulse ?? null}));
    const estimated=stock().mode==='stock_firmware_estimates';
    return card('rhr','Overnight pulse',{link:'rhr',chip:estimated?chip('Estimated','', 'Stock-firmware overnight pulse estimate'):expChip()},
      latest ? [big(fmt(latest.pulse,1),'bpm · latest'),h('p',{class:'lede'},`${estimated?'Estimated overnight pulse':'Recorded overnight spot pulse'}${latest.observed_at ? ` · ${fmtDateTime(latest.observed_at)}` : ''}.`),
        estimated && isNum(model.baseline_days) && model.baseline_days < (model.required_days || 3) ? pending('Personal baseline building','Needs three earlier nights plus the current night.',{n:model.baseline_days,of:model.required_days||3,unit:'earlier nights'}) : null,
        lineChart({items,H:100,unit:'bpm',label:'Overnight pulse trend'})] : pending('No overnight pulse estimate',estimated?'Wear the watch overnight; a personal baseline needs three nights.':monitorExplanation('pulse')),
      h('p',{class:'foot'},estimated?'A custom heuristic from stock-firmware overnight pulse summaries. It is not validated resting heart rate; the stock readiness model uses this estimate as labeled.':'Direct pulse observations, separate from HRV qualification. These spot recordings are not validated resting heart rate and do not enter readiness.'));
  },

  breath() {
    const items=nightItems(7,'breaths_per_min'),has=items.some(i=>isNum(i.v)),n=lastNight();
    return card('breath','Breathing rate',{link:'breath',chip:expChip()},has ? [
      big(isLastNight(n) && isNum(n.breaths_per_min) ? fmt(n.breaths_per_min,1) : '—','breaths/min overnight',!(isLastNight(n)&&isNum(n.breaths_per_min))),
      lineChart({items,H:100,unit:'br/min',label:'Qualified overnight breathing estimates'})] : pending(ppiSourceUnverified() ? 'Breathing estimate unavailable' : 'Recording qualification blocked',ppiSourceUnverified() ? BREATH_SOURCE_EXPLANATION : monitorExplanation('breathing')),
      h('p',{class:'foot'},'Requires a usable interval signal, calibrated motion and a clear breathing rhythm. More elapsed nights alone cannot qualify a rejected recording.'));
  },

  stress() {
    const st=D().stress || {}, model=stockStrain(), manual=((D().hrv || {}).analysis || {}).baseline_progress?.manual || {};
    if (stock().mode==='stock_firmware_estimates') {
      const score=model.score, fresh=stockStrainFresh(model);
      return card('stress','Overnight strain',{link:'stress',chip:chip('Estimated','', 'Estimated overnight strain from stock-firmware pulse')}, fresh ? [big(fmt(score),'of 100'),h('p',{class:'lede'},`Measured ${fmtDateTime(model.measured_at)} · ${model.reason || 'Estimated overnight strain.'}`)] : pending('Estimated overnight strain unavailable',model.reason || 'A fresh overnight estimate is needed.'),
        h('p',{class:'foot'},`Personal baseline: ${model.baseline_days ?? 0} of ${model.required_days ?? 3} nights. This is an estimated overnight strain signal, not mental stress.`),
        h('p',{class:'pending above'},'Stock-firmware estimate · low confidence; a longer baseline does not validate the sensor.'));
    }
    const score=st.context==='manual' ? st.experimental_score : null;
    const diag=D().monitor_observations?.diagnostics?.stress || {};
    return card('stress','Daytime stress check',{link:'stress',chip:expChip()},
      isNum(score) ? [big(fmt(score),'of 100'),h('p',{class:'lede'},stressWord(score))] : pending(diag.eligible ? 'Building a comparable baseline' : 'Recording qualification blocked',monitorExplanation('stress')),
      h('p',{class:'foot'},`${diag.received ?? 0} daytime recordings across ${diag.received_manual_days ?? 0} days received. ${manual.adequate_baseline_days ?? 0} / 14 prior comparable qualified days. This is a spot arousal estimate, not continuous stress monitoring.`));
  },
  steps() {
    const st = D().current_activity || {}, lt = {ts:st.ts};
    const fresh = isNum(lt.ts);
    const hourly = hourlySteps(todayObs());
    return card('steps', 'Steps and activity', { link: 'steps' },
      fresh && isNum(st.steps) ? [
        big(fmt(st.steps), 'steps'),
        stats([['Distance', isNum(st.distance_meters) ? fmt(st.distance_meters / 1000, 2) : '—', 'km'], ['Active', isNum(st.active_seconds) ? fmtDur(st.active_seconds, true) : '—'],
          ['Calories', isNum(st.active_kcal) ? fmt(st.active_kcal) : '—', 'active kcal']]),
        h('p', { class: 'lede', style: { fontSize: '13px' } }, `Synced partial-day total as of ${fmtClock(lt.ts)} · ${st.observed_minutes?.steps ?? 0} observed minutes`),
        hourly.some(p => p.v > 0) ? [dayChart({ points: hourly, bars: true, H: 100, unit: 'steps', label: 'Steps per hour today' }), h('p', { class: 'lede', style: { fontSize: '13px' } }, 'Hourly bars count synced minute records only.')] : null,
      ] : pending('No activity reported today yet', isNum(lt.ts) ? `The last report from the watch was ${fmtDateTime(lt.ts)}.` : 'The watch has not reported yet.'));
  },

  heart() {
    const pts = todayObs().filter(o => isNum(o.hr)).map(o => ({ t: hourOfTs(o.ts), v: o.hr, snapshot: !!o.snapshot }));
    const measured = todayObs().filter(o => isNum(o.hr)).at(-1);
    const vals = pts.map(p => p.v);
    return card('heart', 'Heart rate today', { link: 'heart' },
      pts.length ? [
        h('div', { class: 'big' }, h('span', { class: 'v' }, fmt(measured?.hr)), h('span', { class: 'u' }, `bpm at ${fmtClock(measured?.ts)}`)),
        stats([['Lowest', fmt(Math.min(...vals)), 'bpm'], ['Highest', fmt(Math.max(...vals)), 'bpm']]),
        dayChart({ points: pts, H: 110, unit: 'bpm', label: 'Heart rate today' }),
      ] : pending('No heart rate recorded today yet', 'Minute heart rate arrives with the history export; hourly snapshots fill in between.'));
  },

  train() {
    const t = D().training || {}, lt = t.latest || {};
    const hist = historyMap();
    const items = dateSpan(7).map(d => loadItem(d, hist.get(d)));
    const warming = lt.status !== 'ready';
    return card('train', 'Training load', { link: 'train', chip: warming ? chip(TRAIN_STATUS.warming) : null },
      stats([['7-day load', fmt(lt.load7)], ['Acute', fmt(lt.acute, 1)], ['Chronic', fmt(lt.chronic, 1)], ['Form', isNum(lt.form) ? signed(lt.form) : '—']]),
      items.some(i => isNum(i.v)) ? [barChart({ items, H: 100, unit: 'load', label: 'Daily training load, last 7 days' }),
        legend([['', 'Recorded'], ['partial', 'Partly recorded'], ['gap', 'Unknown']])] : null,
      warming ? pending('Fitness and fatigue need history', `Needs 42 consecutive confirmed days to estimate chronic load; ${D().training_ledger?.confirmed_consecutive_days ?? lt.baseline_days ?? 0} finished days so far.`, { n: D().training_ledger?.confirmed_consecutive_days ?? lt.baseline_days ?? 0, of: 42, unit: 'days' }) : null);
  },

  workouts(limit = 3, full) {
    const ws = (D().workouts || (D().training || {}).workouts || []).slice().sort((a, b) => (b.start || 0) - (a.start || 0));
    const shown = full ? ws : ws.slice(0, limit);
    return card('workouts', 'Workouts', { link: full ? null : 'workouts', cls: full ? 'wide' : '' },
      shown.length ? h('ul', { class: 'list above' }, shown.map(workoutRow)) : h('p', { class: 'lede' }, 'No workouts yet. Record one with the watch’s Workout app, or log one here by effort.'),
      h('div', { class: 'btn-row above' }, h('button', { type: 'button', class: 'btn small', onclick: () => openWorkoutForm() }, 'Log a workout'),
        !full && ws.length > limit ? h('a', { class: 'btn small', href: '#d/workouts' }, `All ${ws.length} workouts`) : null));
  },

  calendar() {
    const hist = historyMap(), days = dateSpan(28);
    const known = days.filter(d => ['complete', 'rest'].includes((hist.get(d) || {}).status)).length;
    return card('calendar', 'Recording completeness', { link: 'calendar' },
      h('p', { class: 'lede', style: { marginTop: 0 } }, `${known} of 28 days confirmed. Training load counts only days you confirm.`),
      calendarGrid(days, hist, true));
  },

  device() {
    const d = D(), lt = d.latest || {}, st = lt.status || {}, col = d.collector || {};
    const c=d.collection_health || {}, age=c.transport?.age_seconds, battery=d.watch_battery || {};
    const hr=c.measurements?.heart_rate, rt=battery.runtime_estimate;
    return card('device', 'Collection and sync', { link: 'device' },
      stats([['Server receipt',isNum(age) ? ago(age) : 'Unknown'],
        ['HR measured',isNum(hr?.age_seconds) ? ago(hr.age_seconds) : 'Not recorded'],
        ['Watch battery',isNum(battery.percent) ? `${battery.percent}%` : battery.status==='stale' ? 'Stale' : '—'],
        ['Est. total runtime', rt ? fmtDur(rt.full_charge_hours * 3600, true) : 'Waiting for more data points']]),
      (battery.series || []).length > 1 ? [lineChart({ items: battery.series.map(p => ({ key: isoOf(new Date(p.ts * 1000)), label: isoOf(new Date(p.ts * 1000)), v: p.percent, note: fmtClock(p.ts) })), H: 140, unit: '%', range: [0, 100], dots: false, label: 'Watch battery charge and discharge, last 7 days' }),
        h('p', { class: 'foot' }, 'Every stored reading from direct BLE and watch-app observations; the line joins across periods the watch was off or disconnected.')] : null,
      rt ? h('p', { class: 'foot' }, `Estimated total runtime ${fmtDur(rt.full_charge_hours * 3600, true)} on a full charge · average discharge ${fmt(rt.discharge_rate_per_hour, 2)}%/h from ${fmt(rt.observed_discharge_hours, 1)} h of genuinely observed discharge. Charging and disconnected gaps are excluded; heavy use drains faster than this estimate.`)
        : (battery.series || []).length ? h('p', { class: 'foot' }, 'Estimated total runtime is waiting for more data points: it needs at least 2 hours of genuinely observed discharge (a drop of at least 3%), with charging, time held at full and long disconnects excluded.') : null,
      h('p',{class:'foot'},battery.observed_at ? `Battery measured ${fmtDateTime(battery.observed_at)}${battery.status==='stale' ? ` · Last reading ${battery.last_percent}%; waiting for a fresh observation.` : ''}` : 'No watch battery observation received.'),
      h('p',{class:'foot'},'Upload activity and sensor freshness are separate. Open for stream timestamps, coverage and night collection evidence.'));

  },
};

function signed(v, digits = 1) { return isNum(v) ? (v > 0 ? '+' : v < 0 ? '−' : '') + fmt(Math.abs(v), digits) : '—'; }
function stressWord(score) {
  if (!isNum(score)) return '';
  if (score < 26) return 'Rest level against your own baseline.';
  if (score < 51) return 'Low arousal against your own baseline.';
  if (score < 76) return 'Medium arousal against your own baseline.';
  return 'High arousal against your own baseline.';
}
function hourlySteps(obs) {
  const out = Array.from({ length: 24 }, (_, t) => ({ t, v: 0 }));
  obs.forEach(o => { if (isNum(o.steps) && !o.snapshot) out[new Date(o.ts * 1000).getHours()].v += o.steps; });
  return out;
}
function loadItem(d, row) {
  const r = row || {};
  if (r.status === 'rest') return { key: d, label: d, v: 0, cls: 'rest', note: 'rest day' };
  if (isNum(r.load)) return { key: d, label: d, v: r.load, cls: r.status === 'partial' ? 'partial' : undefined, note: r.status === 'partial' ? 'recorded sessions only' : undefined };
  return { key: d, label: d, v: null };
}

function workoutRow(w) {
  const mins = isNum(w.seconds) ? Math.round(w.seconds / 60) : null;
  const sub = [fmtDateTime(w.start), mins != null ? `${mins} min` : null,
    isNum(w.hr_load) ? `HR load ${fmt(w.hr_load)}` : isNum(w.hr_coverage) && w.hr_coverage < .8 ? `HR coverage ${fmt(w.hr_coverage * 100)}%` : null,
    w.overlap ? 'overlaps another recording' : null].filter(Boolean).join(', ');
  return h('li', { class: w.ignored ? 'ignored' : '' },
    h('span', { class: 't' }, cap(w.kind || 'Workout')),
    h('span', { class: 's' }, sub),
    h('span', { class: 'acts' },
      h('button', { type: 'button', class: 'btn small', onclick: () => openRpe(w), 'aria-label': isNum(w.rpe) ? `Effort ${w.rpe} of 10, change` : 'Add effort' }, isNum(w.rpe) ? `Effort ${fmt(w.rpe)}` : 'Add effort'),
      w.id ? h('button',{type:'button',class:'btn small',onclick:()=>openWorkoutEdit(w)},'Edit') : null,
      w.id ? h('button', { type: 'button', class: 'btn small', onclick: () => toggleIgnore(w) }, w.ignored ? 'Restore' : 'Exclude') : null));
}

/* Month-style grid (Monday first). compact: last 4 weeks with weekday header. */
function calendarGrid(days, hist, compact) {
  const today = todayISO();
  const conf = D().confirmations || {};
  const grid = h('div', { class: 'cal above', role: 'grid', 'aria-label': 'Day recording status' });
  const dows = []; for (let i = 0; i < 7; i++) dows.push(parseISO('2024-01-01').getTime() + i * 86400000); // a Monday
  dows.forEach(t => grid.append(h('div', { class: 'dow', 'aria-hidden': 'true' }, new Date(t).toLocaleDateString(LOCALE, { weekday: 'narrow' }))));
  let lastMonth = null;
  const first = parseISO(days[0]); const lead = (first.getDay() + 6) % 7;
  for (let i = 0; i < lead; i++) grid.append(h('div', { class: 'pad' }));
  days.forEach((d, idx) => {
    const dt = parseISO(d);
    if (!compact && dt.getMonth() !== lastMonth && idx > 0 && dt.getDate() === 1) {
      const rem = (7 - (grid.querySelectorAll('button, .pad').length % 7)) % 7;
      for (let i = 0; i < rem; i++) grid.append(h('div', { class: 'pad' }));
      grid.append(h('p', { class: 'cal-month' }, dt.toLocaleDateString(LOCALE, { month: 'long', year: 'numeric' })));
      const l2 = (dt.getDay() + 6) % 7; for (let i = 0; i < l2; i++) grid.append(h('div', { class: 'pad' }));
    }
    lastMonth = dt.getMonth();
    const row = hist.get(d) || {}, status = row.status || 'unknown';
    const label = { complete: 'complete', rest: 'rest day', partial: 'partly recorded', unknown: 'unknown' }[status] || status;
    grid.append(h('button', {
      type: 'button', class: `${status}${d === today ? ' today' : ''}${conf[d] ? ' confirmed' : ''}`,
      'aria-label': `${fmtDay(d)}: ${label}${conf[d] ? ', confirmed by you' : ''}`, title: `${fmtDay(d)}: ${label}`,
      onclick: () => openDay(d, row),
    }, String(dt.getDate())));
  });
  const wrap = h('div', null, grid, h('div', { class: 'legend cal-legend' },
    [['complete', 'Complete'], ['partial', 'Partly recorded'], ['rest', 'Rest day'], ['unknown', 'Unknown']].map(([c, t]) => h('span', null, h('i', { class: c }), t))));
  return wrap;
}

/* ================================================================== *
 * Today hero — the watch
 * ================================================================== */
function watchHero() {
  const r = readinessNow(), sl = rec().sleep || {}, hs = rec().hrv_status || {}, n = lastNight();
  const d = D(), activity = d.current_activity || {}, battery = d.watch_battery || {};
  const oxygen = d.oxygen || {}, oxygenLatest = oxygen.latest || {};
  const weight = d.weight || {}, weightLatest = weight.latest || {};
  const training = d.training || {}, trainingLatest = training.latest || {};
  const intensity = (d.fitness || {}).intensity || {};
  const sleepByNight = byNight(rec().sleep_nights, 'night');
  const debtNights = dateSpan(7).map(day=>sleepByNight.get(day)).filter(n=>n && isNum(n.sleep_s) && n.sleep_s>=0);
  const debtSeconds = isNum(sl.need_s) && sl.need_s>0 && debtNights.length ? debtNights.reduce((sum,n)=>sum+Math.max(0,sl.need_s-n.sleep_s),0) : null;
  const latestHr = todayObs().filter(o => isNum(o.hr)).at(-1);
  const hr = new Date().getHours();
  const greet = hr < 5 ? 'Good night' : hr < 12 ? 'Good morning' : hr < 18 ? 'Good afternoon' : 'Good evening';
  const name = wearer();
  const score = r.score, stockPulseCurrent=stock().mode==='stock_firmware_estimates' && stockPulse().latest?.night===todayISO();
  const pulse = stockPulseCurrent && isNum(stockPulse().latest?.pulse) ? stockPulse().latest : (isLastNight(n) && isNum(n.resting_hr) ? n : null);
  const pulseValue = pulse && isNum(pulse.pulse) ? `${fmt(pulse.pulse)} bpm` : pulse && isNum(pulse.resting_hr) ? `${fmt(pulse.resting_hr)} bpm` : null;
  const pulseAt = pulse?.observed_at || pulse?.ts;
  const activityAt = activity.observed_at?.steps || activity.ts;
  const batteryValue = isNum(battery.percent) && battery.status !== 'stale' ? `${fmt(battery.percent)}%` : null;
  const readinessValue = isNum(score) ? `${fmt(score)} · ${readinessWord(score)}` : isNum(r.sleep_based_score) ? `${fmt(r.sleep_based_score)} · sleep-only` : null;
  /* Seven-day series feeding the tiny per-tile graphs; gaps stay gaps. */
  const week = dateSpan(7);
  const readinessHist = new Map((rec().readiness_history || []).map(row => [row.day, row]));
  const hrvByNight = byNight(rec().nights, 'night');
  const oxDaily = new Map((oxygen.daily || []).map(row => [row.date, row]));
  const weightByDay = new Map(((d.weight || {}).entries || []).map(e => [e.date, e]));
  const intensityDays = new Map((intensity.days || []).map(row => [row.date, row]));
  const pulseByNight = byNight(stockPulse().points || [], 'night');
  const loadHist = historyMap();
  const spark = {
    ready: sparkline({ items: week.map(day => ({ key: day, label: day, v: (readinessHist.get(day) || {}).readiness?.score ?? null })), unit: 'of 100', label: 'Readiness, last 7 days' }),
    sleep: sparkline({ items: week.map(day => { const n = sleepByNight.get(day); return { key: day, label: day, v: isNum(n?.sleep_s) ? n.sleep_s / 3600 : null }; }), unit: 'h', fmtV: v => fmt(v, 1), label: 'Sleep per night, last 7 nights' }),
    debt: isNum(sl.need_s) ? sparkline({ bars: true, items: week.map(day => { const n = sleepByNight.get(day); return { key: day, label: day, v: isNum(n?.sleep_s) ? Math.max(0, (sl.need_s - n.sleep_s) / 3600) : null }; }), unit: 'h short', fmtV: v => fmt(v, 1), label: 'Nightly sleep shortfall, last 7 nights' }) : null,
    steps: sparkline({ bars: true, zeroBase: true, items: hourlySteps(todayObs()), unit: 'steps', fmtTip: it => `${it.t}:00`, label: 'Steps per hour today' }),
    hr: sparkline({ zeroBase: false, items: todayObs().filter(o => isNum(o.hr)).map(o => ({ key: o.ts, label: o.ts, v: o.hr, ts: o.ts })), unit: 'bpm', fmtTip: it => fmtClock(it.ts), label: 'Heart rate today' }),
    pulse: sparkline({ zeroBase: false, items: week.map(day => { const n = pulseByNight.get(day); return { key: day, label: day, v: isNum(n?.pulse) ? n.pulse : null }; }), unit: 'bpm', label: 'Overnight pulse, last 7 nights' }),
    hrv: sparkline({ zeroBase: false, items: week.map(day => { const n = hrvByNight.get(day); return { key: day, label: day, v: isNum(n?.rmssd_ms) ? n.rmssd_ms : null }; }), unit: 'ms', fmtV: v => fmt(v, 1), label: 'Nightly HRV, last 7 nights' }),
    oxygen: sparkline({ zeroBase: false, items: week.map(day => { const n = oxDaily.get(day); return { key: day, label: day, v: isNum(n?.percent) ? n.percent : null }; }), unit: '%', fmtV: v => fmt(v, 1), label: 'Blood oxygen, last 7 days' }),
    weight: sparkline({ zeroBase: false, items: week.map(day => { const e = weightByDay.get(day); return { key: day, label: day, v: isNum(e?.kg) ? e.kg : null }; }), unit: 'kg', fmtV: v => fmt(v, 1), label: 'Weight, last 7 days' }),
    train: sparkline({ bars: true, items: week.map(day => { const row = loadHist.get(day); return { key: day, label: day, v: isNum(row?.load) ? row.load : null }; }), unit: 'load', fmtV: v => fmt(v, 0), label: 'Daily training load, last 7 days' }),
    intensity: sparkline({ bars: true, items: week.map(day => { const n = intensityDays.get(day); return { key: day, label: day, v: isNum(n?.moderate) || isNum(n?.vigorous) ? (n.moderate || 0) + 2 * (n.vigorous || 0) : null }; }), unit: 'min', label: 'Intensity minutes, last 7 days' }),
    battery: sparkline({ zeroBase: false, items: (battery.series || []).map(p => ({ key: p.ts, label: p.ts, v: p.percent, ts: p.ts })), unit: '%', fmtTip: it => fmtDateTime(it.ts), label: 'Watch battery, last 7 days' }),
  };
  return h('article', { class: 'watch', 'data-m': 'ready' },
    h('div', { class: 'watch-top' },
      h('h1', { class: 'watch-hello' }, name ? `${greet}, ${name}` : greet),
      h('p', { class: 'watch-date' }, new Date().toLocaleDateString(LOCALE, { weekday: 'long', day: 'numeric', month: 'long' }))),
    h('div', { class: 'watch-metrics' },
      watchMetric('ready', 'Readiness', readinessValue, isNum(score) || isNum(r.sleep_based_score) ? 'estimated · today' : 'Not enough data', 'ready', spark.ready),
      watchMetric('sleep', 'Sleep', isNum(sl.sleep_s) ? fmtDur(sl.sleep_s, true) : null, isNum(sl.sleep_s) ? (sl.night ? `night of ${fmtDay(sl.night)}` : 'last night') : 'No overnight reading', 'sleep', spark.sleep),
      watchMetric('sleep', 'Sleep debt', isNum(debtSeconds) ? fmtDur(debtSeconds,true) : null, isNum(debtSeconds) ? `7-night shortfall · ${debtNights.length}/7 recorded · target ${fmtDur(sl.need_s,true)}/night${debtNights.length<7 ? ' · missing nights excluded' : ''}` : 'Needs recorded sleep and a target', 'sleep', spark.debt),
      watchMetric('steps', 'Steps', isNum(activity.steps) ? fmt(activity.steps) : null, isNum(activity.steps) ? `partial · ${activityAt ? fmtClock(activityAt) : 'today'}` : 'No activity yet', 'steps', spark.steps),
      watchMetric('heart', 'Heart rate', latestHr ? `${fmt(latestHr.hr)} bpm` : null, latestHr ? fmtClock(latestHr.ts) : 'No reading today', 'heart', spark.hr),
      watchMetric('heart', stock().mode==='stock_firmware_estimates' ? 'Overnight pulse' : 'Resting HR', pulseValue, pulseAt ? `${stock().mode==='stock_firmware_estimates' ? 'estimated · ' : ''}${fmtDateTime(pulseAt)}` : 'No overnight reading', 'rhr', spark.pulse),
      watchMetric('hrv', ppiSourceUnverified() ? 'HRV proxy estimate' : 'HRV', ppiSourceUnverified() && latestPpiProxy() ? `${fmt(latestPpiProxy().value_ms,1)} ms` : null, ppiSourceUnverified() && latestPpiProxy() ? `unvalidated · ${fmtDateTime(latestPpiProxy().ts)}` : 'Not available yet', 'hrv', spark.hrv),
      watchMetric('oxygen', 'Blood oxygen', isNum(oxygenLatest.percent) ? `${fmt(oxygenLatest.percent, 1)}%` : null, oxygenLatest.ts ? fmtDateTime(oxygenLatest.ts) : 'No samples yet', 'oxygen', spark.oxygen),
      watchMetric('weight', 'Weight', isNum(weightLatest.kg) ? `${fmt(weightLatest.kg, 1)} kg` : null, weightLatest.date ? `measured ${fmtDay(weightLatest.date)}` : 'No dated reading', 'weight', spark.weight),
      watchMetric('train', 'Training load', isNum(trainingLatest.load7) ? fmt(trainingLatest.load7, 1) : null, isNum(trainingLatest.load7) ? '7-day load' : 'Needs history', 'train', spark.train),
      watchMetric('intensity', 'Intensity', isNum(intensity.this_week) ? `${fmt(intensity.this_week)} min` : null, isNum(intensity.this_week) ? 'this week' : 'No weekly total', 'train', spark.intensity),
      watchMetric('device', 'Watch battery', batteryValue, batteryValue ? (battery.observed_at ? fmtDateTime(battery.observed_at) : 'fresh reading') : battery.status === 'stale' ? 'Stale reading' : 'No reading', 'device', spark.battery)));
}
function watchMetric(m, label, value, meta, link, spark) {
  return h('a', { class: `watch-metric${value ? '' : ' is-empty'}`, 'data-m': m, href: `#d/${link || m}`, 'aria-label': `${label}: ${value || meta || 'No data'}`, title: `${label}: ${value || '—'} · ${meta || 'No data'}` },
    h('span', { class: 'watch-metric-label' }, h('i'), label),
    h('strong', { class: 'watch-metric-value' }, value || '—'),
    spark || null,
    h('span', { class: 'watch-metric-meta' }, meta || 'No data'));
}

/* ================================================================== *
 * Detail views
 * ================================================================== */
function chartW() { return window.innerWidth >= 720 ? 640 : 340; }

const WEIGHT_METRICS = [['weight_kg','Weight','kg'], ['body_fat_pct','Body fat','%'], ['muscle_mass_kg','Muscle mass','kg'], ['bone_mass_kg','Bone mass','kg'], ['body_water_pct','Body water','%'], ['fat_mass_kg','Fat mass','kg'], ['fat_free_mass_kg','Fat-free mass','kg'], ['bmi','BMI','']];
function weightGraph(span, height, detailed) {
  const key = S.weightMetric || 'weight_kg';
  const [,label,unit] = WEIGHT_METRICS.find(m => m[0] === key) || WEIGHT_METRICS[0];
  const isWeight = key === 'weight_kg', data = D().composition || {}, person = (data.people || [])[0] || {};
  const metric = (person.metrics || {})[key] || {}, map = new Map((data.measurement_history || []).filter(r => r.key === key).map(r => [r.date,r.value]));
  const items = isWeight ? weightItems(span) : span.map(d => ({key:d,label:d,v:map.get(d) ?? null}));
  const select = h('select', {id:'weight-metric', 'aria-label':'Weight graph metric', style:{width:'100%',minHeight:'44px',font:'inherit',marginBottom:'12px'}, onchange:e => { S.weightMetric=e.target.value; render(); document.getElementById('weight-metric')?.focus({preventScroll:true}); }},
    WEIGHT_METRICS.map(([k,name,u]) => h('option',{value:k,selected:k===key},`${name}${u ? ' ('+u+')' : ''}`)));
  const latest = isWeight ? (D().weight || {}).latest || {} : metric;
  return [h('label',{for:'weight-metric',class:'foot'},'Graph measurement'), select,
    !isWeight ? big(fmt(metric.value,2), unit) : null,
    !isWeight ? h('p',{class:'foot'},metric.date ? `Measured ${metric.date} · connected scale` : 'No verified measurement date') : null,
    items.some(i=>isNum(i.v)) ? lineChart({items,W:detailed?chartW():340,H:height,alt:isWeight,fmtV:v=>fmt(v,1),unit,label:isWeight?'Weight and 7-day trend':`${label} measurements`}) : pending(`No ${label.toLowerCase()} readings in this range`,data.error || 'Measurements appear on the date taken; missing days remain gaps.'),
    isWeight ? legend([['line','Weigh-ins'],['dash','7-day trend']]) : h('p',{class:'foot'},'Connected scale measurements. A single reading appears as a point; trends build with more weigh-ins.'),
    ['fat_mass_kg','fat_free_mass_kg'].includes(key) ? h('p',{class:'foot'},'Calculated from weight and body fat measured on the same date.') : null];
}

function bodyTrendOverview(span) {
  const data = D().composition || {}, person = (data.people || [])[0] || {}, metrics = person.metrics || {};
  const history = data.measurement_history || [];
  const fields = WEIGHT_METRICS.filter(m => ['body_fat_pct','muscle_mass_kg','body_water_pct'].includes(m[0]));
  const mini = fields.map(([key,name,unit]) => {
    const m = metrics[key] || {}, map = new Map(history.filter(r=>r.key===key && isNum(r.value)).map(r=>[r.date,r.value]));
    const dated = [...map].filter(([d])=>d>=span[0] && d<=span[span.length-1]).sort(([a],[b])=>a.localeCompare(b));
    const change = dated.length > 1 ? dated[dated.length-1][1]-dated[0][1] : null;
    const delta = isNum(change) ? `${change>0?'↑':change<0?'↓':'→'} ${fmt(Math.abs(change),2)} ${unit==='%'?'percentage points':unit} in range` : dated.length ? 'Trend building · 1 reading' : 'No readings in range';
    const items = span.map(d=>({key:d,label:d,v:map.get(d)??null}));
    return h('section',{style:{minWidth:'0',padding:'16px 0'},'aria-label':`${name} trend`},
      h('h3',{style:{fontSize:'15px',margin:'0 0 8px'}},name),big(fmt(m.value,2),unit),
      h('p',{class:'foot',style:{margin:'8px 0'}},delta),
      dated.length ? lineChart({items,W:340,H:105,fmtV:v=>fmt(v,1),unit,label:`${name} trend`}) : h('p',{class:'foot'},'Measurements will appear here.'),
      h('p',{class:'foot'},m.date ? `Last measured ${m.date}` : 'Not measured'));
  });
  const remaining = WEIGHT_METRICS.filter(m=>['bone_mass_kg','fat_mass_kg','fat_free_mass_kg','bmi'].includes(m[0]));
  return [h('div',{style:{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(180px,1fr))',gap:'24px',marginTop:'12px',borderTop:'1px solid var(--line)'}},mini),
    h('details',{class:'info'},h('summary',null,'Bone, fat mass, fat-free mass & BMI'),
      h('dl',{class:'stats'},remaining.map(([key,name,unit])=>{const m=metrics[key]||{};return h('div',{class:'stat'},h('dt',null,name),h('dd',null,fmt(m.value,2),unit?h('small',null,` ${unit}`):null),h('p',{class:'foot'},m.date||'Not measured'));}))),
    h('p',{class:'foot'},'Composition changes compare actual measurements in the selected range. More weigh-ins will reveal trends; gaps stay visible.')];
}

function oxygenSetup() {
  const output=h('div',{'aria-live':'polite'});
  return h('details',{class:'info'},h('summary',null,'Connect GravelEx health export'),
    h('p',null,`In GravelEx, open watch settings → Health data export. Use ${hubUrl()} as the server. Create an upload token below, paste it into GravelEx, enable automatic health export, then Save and Sync.`),
    h('p',null,'GravelEx is a full phone app, installed separately as tdgs.gravel. Keep the original Gravel until pairing and sync work. Stop it before moving the watch connection; only one app should manage the watch.'),
    h('p',null,h('a',{href:'download/gravelex'},'Download GravelEx APK'),' · ',sourceLink('Source and update instructions')),
    h('button',{type:'button',class:'btn',onclick:async e=>{const btn=e.currentTarget;btn.disabled=true;try{const pair=await api('api/pair?kind=history','POST');const input=h('input',{type:'password',readOnly:true,value:pair.token,'aria-label':'Gravel history upload token',style:{width:'100%'}});output.replaceChildren(h('p',null,'Upload-only history token. Expires after 30 days without use.'),input,h('button',{class:'btn small',type:'button',onclick:async()=>{try{await navigator.clipboard.writeText(pair.token);toast('Upload token copied');}catch(err){input.type='text';input.focus();input.select();}}},'Copy upload token'));}catch(err){output.replaceChildren(h('p',null,'Could not create an upload token. Try again.'));}finally{btn.disabled=false;}}},'Create upload token'),output);
}

function oxygenCard(detailed=false) {
  const o=D().oxygen||{}, latest=o.latest||{}, daily=new Map((o.daily||[]).map(r=>[r.date,r]));
  const items=dateSpan(detailed?S.range:7).map(d=>{const r=daily.get(d)||{};return {key:d,label:d,v:r.mean??null,lo:r.min??null,hi:r.max??null,note:r.count?`${r.count} spot samples`:''};});
  const measured=isNum(latest.ts)?new Date(latest.ts*1000).toLocaleString():null;
  return card('breath', 'Blood oxygen (SpO₂)', detailed?{chip:expChip(),cls:'wide'}:{chip:expChip(),link:'oxygen'},
    big(fmt(latest.percent,1),'%'),
    h('p',{class:'foot'},measured?`Measured ${measured}`:'Waiting for the first phone-exported measurement'),
    isNum(latest.percent) ? stats([['Samples in range',fmt(o.sample_count)],['Latest device quality',fmt(latest.quality)]]) : pending('No SpO₂ samples received','The watch sends oxygen through its phone data-logging stream. Enable SpO₂ on the watch and install the compatible Gravel export build.'),
    items.some(i=>isNum(i.v))?lineChart({items,W:detailed?chartW():340,H:detailed?200:110,fmtV:v=>fmt(v,1),unit:'%',label:'SpO₂ daily mean and measured range'}):null,
    h('p',{class:'foot'},'Daily mean and observed range from spot readings. Gaps are unknown; not continuous monitoring or a readiness input.'),
    detailed?oxygenSetup():null,
    detailed?info('Measurement limitations',o.note||'Experimental wrist optical readings. No diagnostic interpretation.', 'The device quality byte is retained as reported; its clinical meaning has not been established.'):null,
    detailed&&(o.readings||[]).length?h('details',{class:'info'},h('summary',null,'Recent individual readings'),h('table',null,h('thead',null,h('tr',null,h('th',null,'Measured'),h('th',null,'SpO₂'),h('th',null,'Device quality'))),h('tbody',null,(o.readings||[]).slice(-30).reverse().map(r=>h('tr',null,h('td',null,new Date(r.ts*1000).toLocaleString()),h('td',null,`${fmt(r.percent,1)}%`),h('td',null,fmt(r.quality))))))):null);
}

/* Battery detail chart: time-scaled charge curve over the stored 7-day series.
   Slope colours separate charging, discharging and held stretches; the line
   joins across periods the watch was off or disconnected. */
function batteryChart(series) {
  const W = chartW(), H = 300, top = 14, bottom = 26, left = 34, right = 10;
  const ph = H - top - bottom, pw = W - left - right;
  const t0 = series[0].ts, t1 = Math.max(series[series.length - 1].ts, t0 + 1);
  const X = ts => left + ((ts - t0) / (t1 - t0)) * pw;
  const Y = p => top + ph - (p / 100) * ph;
  const kids = [];
  for (let v = 0; v <= 100; v += 25) {
    kids.push(s('line', { class: `grid${v === 0 ? ' zero' : ''}`, x1: left, x2: W - right, y1: Y(v), y2: Y(v) }));
    kids.push(s('text', { x: left - 6, y: Y(v) + 3.5, 'text-anchor': 'end' }, `${v}%`));
  }
  const midnight = ts => { const d = new Date(ts * 1000); d.setHours(0, 0, 0, 0); return d; };
  for (let d = midnight(t0); d.getTime() <= midnight(t1).getTime(); d.setDate(d.getDate() + 1)) {
    const iso = isoOf(d), ts = Math.floor(d.getTime() / 1000);
    if (ts > t0 && ts < t1) {
      kids.push(s('line', { class: 'grid', x1: X(ts), x2: X(ts), y1: top, y2: top + ph }));
      kids.push(s('text', { x: X(ts), y: H - 6, 'text-anchor': 'middle' }, fmtDayShort(iso)));
    }
  }
  let area = '';
  series.forEach((p, i) => { area += `${i ? 'L' : 'M'}${X(p.ts).toFixed(1)} ${Y(p.percent).toFixed(1)}`; });
  area += `L${X(t1).toFixed(1)} ${top + ph}L${X(t0).toFixed(1)} ${top + ph}Z`;
  kids.push(s('path', { class: 'batt-area', d: area }));
  const pathFor = cls => {
    let d = '', open = false;
    for (let i = 1; i < series.length; i++) {
      const a = series[i - 1], b = series[i];
      const step = b.percent > a.percent ? 'charge' : b.percent < a.percent ? 'drain' : 'hold';
      if (step === cls) {
        d += `${open ? '' : `M${X(a.ts).toFixed(1)} ${Y(a.percent).toFixed(1)}`}L${X(b.ts).toFixed(1)} ${Y(b.percent).toFixed(1)}`;
        open = true;
      } else open = false;
    }
    return d;
  };
  ['charge', 'drain', 'hold'].forEach(cls => { const d = pathFor(cls); if (d) kids.push(s('path', { class: `batt-seg ${cls}`, d })); });
  const dotR = Math.max(1.2, Math.min(2.2, pw / Math.max(1, series.length) / 2));
  series.forEach(p => kids.push(s('circle', { class: 'batt-dot', cx: X(p.ts), cy: Y(p.percent), r: dotR }, s('title', null, `${fmtDateTime(p.ts)}: ${p.percent}%`))));
  const last = series[series.length - 1];
  kids.push(s('circle', { class: 'batt-now', cx: X(last.ts), cy: Y(last.percent), r: 4 }, s('title', null, `${fmtDateTime(last.ts)}: ${last.percent}%`)));
  return s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Watch battery charge and discharge, last 7 days' }, kids);
}

function batteryDetail() {
  const battery = D().watch_battery || {}, series = battery.series || [], rt = battery.runtime_estimate;
  return card('device', 'Battery charge and discharge', { cls: 'wide' },
    series.length > 1 ? batteryChart(series) : pending('No battery history yet', 'Readings appear once the watch reports its battery level through the phone app.'),
    stats([
      ['Watch battery', isNum(battery.percent) ? `${battery.percent}%` : battery.status === 'stale' ? 'Stale' : '—'],
      ['Last reading', battery.observed_at ? fmtDateTime(battery.observed_at) : '—'],
      ['Est. total runtime', rt ? fmtDur(rt.full_charge_hours * 3600, true) : 'Waiting for more data points'],
      ['Avg discharge rate', rt ? fmt(rt.discharge_rate_per_hour, 2) : '—', '%/h'],
      ['Observed discharge', rt ? fmt(rt.observed_discharge_hours, 1) : '—', 'h'],
      ['Stored readings', String(series.length)],
    ]),
    series.length > 1 ? legend([['charge', 'Charging'], ['drain', 'Discharging'], ['hold', 'Held or steady']]) : null,
    h('p', { class: 'foot' }, 'Direct BLE and watch-app readings over the last 7 days. The line joins across periods the watch was off or disconnected; the runtime estimate uses only genuinely observed discharge and excludes charging, time held at full and long gaps.'),
    rt ? h('p', { class: 'foot' }, `Estimated total runtime ${fmtDur(rt.full_charge_hours * 3600, true)} on a full charge from the average observed discharge rate; heavy use drains faster than this estimate.`) : null);
}

const DETAIL = {
  oxygen: {title:"Blood oxygen (SpO₂)",m:"breath",render(){return [oxygenCard(true)];}},
  weight: {
    title: 'Weight', m: 'weight',
    render() {
      const w = D().weight || {}, span = dateSpan(S.range), items = weightItems(span);
      const inRange = (w.entries || []).filter(e => e.date >= span[0]);
      const kgs = inRange.map(e => e.kg);
      const change = inRange.length > 1 ? inRange[inRange.length - 1].trend_kg - inRange[0].trend_kg : null;
      return [card('weight', 'Weight & body composition', { cls: 'wide' },
        big(fmt((w.latest || {}).kg,2),'kg'),
        h('p',{class:'foot'},(w.latest||{}).date ? `Last weighed ${w.latest.date}` : 'No weigh-ins yet'),
        items.some(i=>isNum(i.v)) ? lineChart({items,W:chartW(),H:210,alt:true,fmtV:v=>fmt(v,1),unit:'kg',label:'Weight and 7-day trend'}) : pending('No weigh-ins in range','Choose a longer range to see earlier measurements.'),
        legend([['line','Weigh-ins'],['dash','7-day trend']]),
        stats([['7-reading trend',fmt((w.latest||{}).trend_kg,2),'kg'],['Trend change in range',signedKg(change),'kg'],['Weigh-ins in range',`${kgs.length}`]]),
        ...bodyTrendOverview(span),
        h('details',{class:'info'},h('summary',null,'Explore a measurement in detail'),...weightGraph(span,210,true)),
        info('About these measurements','Scale composition readings take priority on their measurement date; daily weigh-ins fill other dates. The weight trend averages your last seven weigh-ins. Fat and fat-free mass use weight and body fat from matching dates.'))];
    },
  },
  ready: {
    title: 'Readiness', m: 'ready', noRange: true,
    render() {
      const r = readinessNow(), comps = r.components || {}, weights = r.weights || {};
      const names = Object.keys(weights).length ? Object.keys(weights) : ['hrv', 'resting_hr', 'sleep', 'training_load'];
      return [
        card('ready', 'Today', { chip: r.formula_version==='readiness-stock-v1' ? chip('Estimated') : expChip(), cls: 'wide' },
          h('div', { style: { display: 'flex', gap: '18px', alignItems: 'center', flexWrap: 'wrap' } },
            h('div', { style: { width: '128px' } }, ring(isNum(r.score) ? r.score : r.sleep_based_score, { size: 128, stroke: 12, label: isNum(r.score) ? 'Readiness score' : 'Sleep-only guidance' })),
            h('div', { style: { flex: '1', minWidth: '180px' } },
              h('p', { class: 'status-word', style: { fontSize: '22px' } }, isNum(r.score) ? readinessWord(r.score) : isNum(r.sleep_based_score) ? 'Sleep-only guidance' : readinessWord(r.score)),
          h('p', { class: 'lede' }, isNum(r.score) ? (r.formula_version==='readiness-stock-v1' ? 'Estimated stock-firmware readiness from sleep, overnight pulse and training load.' : 'An experimental weighted mix of the inputs below.') : (r.reason || 'Not enough inputs yet.')))),
          h('div', { class: 'comps' }, names.map(k => compRow(r.formula_version==='readiness-stock-v1' && k==='resting_hr' ? 'Overnight pulse estimate' : COMPONENT_NAMES[k] || k, comps[k], weights[k]))),
          h('p',{class:'foot'},`${r.components_count ?? Object.keys(comps).length} of ${r.total_components ?? 4} inputs · ${isNum(r.effective_weight_coverage) ? fmt(r.effective_weight_coverage*100) : '—'}% configured weight covered${r.provisional ? ' · provisional' : ''}`),
          missingList(r.missing),
          info('How readiness works',
            r.formula_version==='readiness-stock-v1' ? 'Stock-firmware readiness uses sleep, overnight pulse and training load with the displayed weights. It is a custom heuristic, not a vendor measurement.' : 'HRV, resting HR and load are compared with personal baselines. Sleep uses duration against your target and timing regularity. The score combines available inputs and remains experimental.',
            r.formula_version==='readiness-stock-v1' ? 'Needs sleep and at least one other available input. With sleep alone, only sleep-only guidance is shown. Missing components are not guessed.' : 'Missing inputs are left out rather than guessed. With fewer than two inputs, or without overnight HRV or sleep, no score is shown.',
            r.method ? `Method: ${r.method}.` : null)),
        readinessHistoryCard(),
      ];
    },
  },

  sleep: {
    title: 'Sleep', m: 'sleep',
    render() {
      const sl = rec().sleep || {}, nights = rec().sleep_nights || [], map = byNight(nights, 'night');
      const span = dateSpan(S.range);
      const items = bucket(span, d => { const n = map.get(d) || {}; return { v: isNum(n.sleep_s) ? n.sleep_s / 3600 : null, inner: isNum(n.restful_s) ? n.restful_s / 3600 : null }; }, 'avg')
        .map(i => ({ ...i, cls: 'soft', inner: i.week ? null : i.inner }));
      const inRange = span.map(d => map.get(d)).filter(Boolean);
      const timed = inRange.filter(n => isNum(n.onset) && isNum(n.wake)).slice(-14);
      return [
        card('sleep', 'Last night', { chip: sl.status === 'experimental' ? expChip() : sl.status === 'duration_only' ? chip('Duration only') : null, cls: 'wide' },
          isNum(sl.sleep_s) ? [
            h('div', { style: { display: 'flex', gap: '18px', alignItems: 'center', flexWrap: 'wrap' } },
              h('div', { style: { width: '112px' } }, ring(sl.score, { size: 112, stroke: 11, label: isNum(sl.score) ? `Sleep score ${sl.score}` : 'No sleep score' })),
              h('div', null, big(fmtDur(sl.sleep_s, true), 'asleep'), h('p', { class: 'lede' }, isNum(sl.score) ? `${sleepWord(sl.score)}. ${sl.reason || ''}` : sl.reason || ''))),
            stats([['Restful', fmtDur(sl.restful_s, true)], ['Sleep need', fmtDur(sl.need_s, true)], ['Timing spread', isNum(sl.regularity_sd_min) ? `±${fmt(sl.regularity_sd_min)}` : '—', 'min']]),
            h('div', { class: 'comps' }, Object.entries(sl.components || {}).map(([k, v]) => compRow(COMPONENT_NAMES[k] || k, { score: v }))),
          ] : pending('No sleep recorded for last night', sl.reason),
          missingList(sl.missing),
          info('How the sleep score works',
            'Duration is compared with your sleep need. Once bed and wake times are known for three nights in a week, the regularity of your timing counts too.',
            'Restful sleep is the watch’s own estimate of quieter sleep. It is not a sleep-stage measurement.')),
        card('sleep', 'Sleep per night', { cls: 'wide' },
          inRange.length ? [
            barChart({ items, W: chartW(), H: 180, fmtV: v => fmt(v, 1), unit: 'h', ref: isNum(sl.need_s) ? { v: sl.need_s / 3600, label: 'need' } : null, label: 'Sleep duration per night' }),
            legend([['soft', 'Asleep'], ['', 'Restful'], ['dash', 'Sleep need'], ['gap', 'No data']]),
            stats([['Average', fmtDur(avg(inRange.map(n => n.sleep_s)), true)], ['Nights recorded', `${inRange.length} of ${span.length}`]]),
          ] : pending('No nights in this range', 'Nights appear here after the watch syncs in the morning.')),
        card('sleep', 'Bed and wake times', { cls: 'wide' },
          timed.length ? [timingChart(timed, chartW()), h('p', { class: 'lede', style: { fontSize: '13px' } }, `Showing the last ${timed.length} nights with known times.`)]
            : pending('No bed and wake times yet', 'Times come from exported sleep sessions. Nights reported only as a daily total have a duration but no timing.')),
      ];
    },
  },

  hrv: {
    title: 'HRV status', m: 'hrv',
    render() {
      const st = rec().hrv_status || {};
      const [word] = hrvLabel(st.status);
      const span = dateSpan(S.range), m = byNight(rec().nights, 'night');
      const items = bucket(span, d => ({ v: (m.get(d) || {}).rmssd_ms ?? null }), 'avg');
      const has = items.some(i => isNum(i.v));
      const pts = ((D().hrv || {}).analysis || {}).points || [];
      const proxyGraph=hrvProxyGraph(span);
      return [
        card('hrv', 'This week', { chip: st.provisional ? chip('Provisional', '', st.reason) : expChip(), cls: 'wide' },
          h('p', { class: 'status-word', style: { fontSize: '22px' } }, ppiSourceUnverified() && !isNum(st.last_night_rmssd_ms) ? 'Unvalidated estimate' : word),
          ppiSourceUnverified() && !isNum(st.last_night_rmssd_ms)
            ? ppiVariabilityDiagnostic()
            : st.status === 'baseline_building'
            ? pending('Learning your usual range', st.reason, { n: st.baseline_nights || 0, of: st.required_baseline_nights || 14, unit: 'nights' })
            : [hrvGauge(st, 280), stats([[st.provisional ? 'Last 3 nights' : '7-night average', fmt(st.weekly_rmssd_ms), 'ms'], ['Usual range', isNum(st.baseline_low_ms) ? `${fmt(st.baseline_low_ms)}–${fmt(st.baseline_high_ms)}` : '—', 'ms'], ['Last night', fmt(st.last_night_rmssd_ms), 'ms'], ['Nights this week', isNum(st.nights_this_week) ? `${st.nights_this_week} of 7` : '—']]), h('p', { class: 'lede' }, st.reason || '')],
          info('How HRV status works',
            'Heart rate variability (RMSSD) is measured in short recordings during the night. The 7-night average is compared with the range that is usual for you.',
            'Balanced means the average sits inside that range. Values outside it are worth noting, not alarming. These recordings are experimental and unvalidated.',
            'Until 14 Pebble nights exist, a provisional status compares your last 3 nights with your earlier Pebble nights, using how much your HRV varied night to night in your earlier imported history.')),
        card('hrv', 'HRV history', { cls: 'wide' },
          has ? [h('div',{class:'hrv-qualified-series'},lineChart({ items, W: chartW(), H: 180, unit: 'ms', band: isNum(st.baseline_low_ms) ? { lo: st.baseline_low_ms, hi: st.baseline_high_ms } : null, label: 'Qualified nightly HRV' }),
            legend([['line', 'Qualified nightly RMSSD'], ['soft', 'Usual range'], ['gap', 'No usable recording']]))]
            : null,
          proxyGraph,
          !has && !proxyGraph ? pending('No recordings in this range', 'Record a watch HRV session to populate the unvalidated proxy trend.') : null),
        spotChecks(pts),
      ];
    },
  },

  rhr: {
    title: 'Overnight spot pulse', m: 'rhr',
    render() {
      const model=stockPulse(), span=dateSpan(S.range),m=byNight(model.points || D().monitor_observations?.nightly_pulse || [],'night');
      const items=bucket(span,d=>({v:m.get(d)?.pulse ?? null}),'avg');
      const vals=span.map(d=>m.get(d)?.pulse);
      const estimated=stock().mode==='stock_firmware_estimates';
      return [card('rhr', estimated?'Overnight pulse estimate':'Recorded overnight spot pulse', { cls: 'wide', chip: estimated?chip('Estimated'):expChip() },
        items.some(i => isNum(i.v)) ? [lineChart({ items, W: chartW(), H: 180, unit: 'bpm', label: 'Recorded overnight spot pulse' }),
          stats([['Average', fmt(avg(vals)), 'bpm'], ['Lowest', fmt(Math.min(...vals.filter(isNum))), 'bpm'], ['Nights', `${vals.filter(isNum).length} of ${span.length}`]])]
          : pending('No overnight pulse in this range',monitorExplanation('pulse')),
        info('About overnight pulse',estimated?'A custom stock-firmware heuristic with three earlier baseline nights plus the current night. It is not validated resting heart rate and does not make clinical claims.':'Median direct pulse summaries from comparable scheduled captures. Actual night dates and gaps are retained. This is not validated resting heart rate and does not qualify readiness.'))];
    },
  },

  breath: {
    title: 'Breathing rate', m: 'breath',
    render() {
      const span = dateSpan(S.range), m = byNight(rec().nights, 'night');
      const items = bucket(span, d => ({ v: (m.get(d) || {}).breaths_per_min ?? null }), 'avg');
      const vals = span.map(d => (m.get(d) || {}).breaths_per_min);
      return [card('breath', 'Overnight breathing rate', { chip: expChip(), cls: 'wide' },
        items.some(i => isNum(i.v)) ? [lineChart({ items, W: chartW(), H: 180, unit: 'br/min', fmtV: v => fmt(v, 1), label: 'Breathing rate per night' }),
          stats([['Average', fmt(avg(vals), 1), 'br/min'], ['Nights', `${vals.filter(isNum).length} of ${span.length}`]])]
          : pending(ppiSourceUnverified() ? 'Breathing estimate unavailable' : 'Recording qualification blocked',ppiSourceUnverified() ? BREATH_SOURCE_EXPLANATION : monitorExplanation('breathing')),
        info('About breathing rate', ppiSourceUnverified() ? BREATH_SOURCE_EXPLANATION : 'An experimental estimate from heart-rate changes associated with breathing during night recordings. Nights with an unclear signal are left blank; this is not a direct respiratory measurement.'))];
    },
  },

  stress: {
    title: 'Stress', m: 'stress', noRange: true,
    render() {
      const st = D().stress || {}, model=stockStrain();
      if (stock().mode==='stock_firmware_estimates') return [card('stress','Estimated overnight strain',{chip:chip('Estimated'),cls:'wide'},
        stockStrainFresh(model) ? [big(fmt(model.score),'of 100'),h('p',{class:'lede'},model.measured_at?`Measured ${fmtDateTime(model.measured_at)}.`:'')] : pending('Estimated overnight strain unavailable',model.reason || 'A fresh estimate is needed.'),
        h('p',{class:'foot'},`${model.baseline_days ?? 0} of ${model.required_days ?? 3} baseline nights · Estimated overnight strain, not mental stress.`),
        info('About this estimate','This custom heuristic uses stock-firmware overnight pulse data and remains separate from the older HRV stress detail.'))];
      const pts = ((D().hrv || {}).analysis || {}).points || [];
      const bp = ((D().hrv || {}).analysis || {}).baseline_progress || {};
      return [
        card('stress', 'Arousal score', { chip: expChip(), cls: 'wide' },
          st.context==='manual' && isNum(st.experimental_score) ? [big(fmt(st.experimental_score), 'of 100'), h('p', { class: 'lede' }, stressWord(st.experimental_score))]
            : pending('Daytime recording status',monitorExplanation('stress')),
          Object.keys(bp).length ? stats(Object.entries(bp).map(([k, v]) => [`${cap(k)} baseline`, `${v.adequate_baseline_days ?? 0} of ${v.required_days ?? 14}`, 'days'])) : null,
          info('How the stress score works',
            'Each daytime spot check is compared with your own earlier spot checks taken in the same way. Lower HRV than usual maps to a higher score.',
            'Movement during a recording spoils it, so those are skipped. This is an experimental estimate of physiological arousal, not a measure of how you feel.')),
        spotChecks(pts),
      ];
    },
  },

  steps: {
    title: 'Steps and activity', m: 'steps',
    render() {
      const byDay = obsByLocalDay(), span = dateSpan(S.range, isoOf(new Date()));
      const items = bucket(span, d => { const o = byDay.get(d); const v = o ? sum(o.filter(x => !x.snapshot).map(x => x.steps)) : null; return { v }; }, 'avg');
      return [CARDS.steps(), card('steps', 'Steps from synced minutes', { cls: 'wide' },
        items.some(i => isNum(i.v)) ? [barChart({ items, W: chartW(), H: 180, unit: 'steps', label: 'Steps per day from minute records' }),
          h('p', { class: 'lede', style: { fontSize: '13.5px' } }, 'Totals add up minute records that reached the server. Days with gaps in the export will read low.')]
          : pending('No minute records in this range', 'Minute steps arrive with the history export from the watch.'))];
    },
  },

  heart: {
    title: 'Heart rate', m: 'heart',
    render() {
      const byDay = obsByLocalDay(), span = dateSpan(S.range, isoOf(new Date()));
      const items = bucket(span, d => {
        const v = (byDay.get(d) || []).map(o => o.hr).filter(isNum);
        return v.length ? { v: avg(v), lo: Math.min(...v), hi: Math.max(...v) } : { v: null };
      }, 'avg');
      return [CARDS.heart(), card('heart', 'Daily range', { cls: 'wide' },
        items.some(i => isNum(i.v)) ? [lineChart({ items, W: chartW(), H: 180, unit: 'bpm', label: 'Daily heart rate range and average' }), legend([['line', 'Average'], ['soft', 'Lowest to highest']])]
          : pending('No heart rate in this range', 'Minute heart rate arrives with the history export.'))];
    },
  },

  train: {
    title: 'Training load', m: 'train',
    render() {
      const t = D().training || {}, lt = t.latest || {}, prof = D().profile || {}, model = D().model || {};
      const hist = historyMap(), span = dateSpan(S.range);
      const items = bucket(span, d => loadItem(d, hist.get(d)), 'sum');
      const acu = bucket(span, d => ({ v: (hist.get(d) || {}).acute ?? null, alt: (hist.get(d) || {}).chronic ?? null }), 'avg')
        .map((i, k) => ({ ...i, alt: span.length > 60 ? avg(span.slice(k * 7, k * 7 + 7).map(d => (hist.get(d) || {}).chronic)) : i.alt }));
      const zones = t.zones || [], zmax = Math.max(1, ...zones.map(z => z.minutes || 0));
      const weeks = (t.weeks || []).slice(-8);
      return [
        card('train', 'Now', { chip: lt.status !== 'ready' ? chip('Building baseline') : null, cls: 'wide' },
          stats([['7-day load', fmt(lt.load7), lt.known_days7 != null ? `${lt.known_days7}/7 days known` : ''], ['Acute', fmt(lt.acute, 1), 'fatigue'], ['Chronic', fmt(lt.chronic, 1), 'fitness'], ['Form', isNum(lt.form) ? signed(lt.form) : '—']]),
          lt.status !== 'ready' ? pending('Chronic load needs six weeks', `Needs 42 consecutive confirmed days; ${D().training_ledger?.confirmed_consecutive_days ?? lt.baseline_days ?? 0} finished days so far. Confirm days in the calendar below.`, { n: D().training_ledger?.confirmed_consecutive_days ?? lt.baseline_days ?? 0, of: 42, unit: 'days' }) : null,
          h('p', { class: 'lede' }, `Load method: ${prof.load_method === 'rpe' ? 'session effort' : 'heart rate'}${isNum(prof.hr_max) ? `, max HR ${prof.hr_max} bpm` : ''}. `, h('a', { href: '#more' }, 'Change')),
          info('How training load works',
            'Each workout gets a load from time in heart-rate zones, or from minutes times your effort rating. Acute load is the last week; chronic load is the last six weeks. Form is chronic minus acute.',
            'Days without a confirmation are unknown, not zero. That keeps an unworn day from looking like a rest day.',
            model.hr ? `Heart-rate model: ${model.hr}.` : null, model.rpe ? `Effort model: ${model.rpe}.` : null)),
        card('train', 'Daily load', { cls: 'wide' },
          barChart({ items, W: chartW(), H: 180, unit: 'load', label: 'Training load per day' }),
          legend([['', 'Recorded'], ['partial', 'Partly recorded'], ['rest', 'Rest day'], ['gap', 'Unknown']])),
        card('train', 'Acute and chronic load', { cls: 'wide' },
          acu.some(i => isNum(i.v) || isNum(i.alt)) ? [lineChart({ items: acu, W: chartW(), H: 170, alt: true, zeroBase: true, label: 'Acute and chronic load' }), legend([['line', 'Acute (7 days)'], ['dash', 'Chronic (42 days)']])]
            : pending('Not enough confirmed days yet', 'These lines appear once enough days are confirmed.')),
        card('train', 'Time in heart-rate zones', {},
          zones.length && zones.some(z => z.minutes > 0) ? h('div', { class: 'zones' }, zones.map(z => h('div', { class: 'zone' },
            h('span', null, z.label), h('span', { class: 'bar' }, h('span', { style: { width: `${100 * (z.minutes || 0) / zmax}%` } })), h('span', { class: 'min' }, `${fmt(z.minutes)} min`))))
            : pending('No zone minutes yet', 'Zone minutes come from workouts with at least 80% heart-rate coverage.'),
          isNum(prof.hr_max) ? h('p', { class: 'lede', style: { fontSize: '13px' } }, `Percent of max heart rate (${prof.hr_max} bpm).`) : null),
        card('train', 'Weekly load', {},
          weeks.length ? barChart({ items: weeks.map(w => ({ key: w.start, label: w.start, v: w.load, cls: w.status === 'partial' || w.unknown_days ? 'partial' : undefined, note: `${w.confirmed_days || 0} confirmed days`, week: true })), H: 140, unit: 'load', label: 'Weekly load' }) : pending('No weeks yet'),
          legend([['', 'Fully confirmed week'], ['partial', 'Week with unknown days']])),
        (t.notes || []).length ? h('p', { class: 'foot' }, t.notes.join(' ')) : null,
      ];
    },
  },

  workouts: { title: 'Workouts', m: 'workouts', noRange: true, render() { return [CARDS.workouts(0, true)]; } },

  calendar: {
    title: 'Recording completeness', m: 'calendar', noRange: true,
    render() {
      const hist = historyMap();
      const keys = [...hist.keys()].sort();
      const days = keys.length ? dateSpan(Math.min(366, Math.max(28, Math.round((parseISO(todayISO()) - parseISO(keys[0])) / 86400000) + 1))) : dateSpan(28);
      return [card('calendar', 'Day by day', { cls: 'wide' },
        h('p', { class: 'lede', style: { marginTop: 0 } }, 'Tap a day to mark it complete (every workout was recorded) or a rest day. Unconfirmed days count as unknown.'),
        calendarGrid(days, hist, false),
        info('Why confirm days?', 'The watch cannot tell a rest day from a day you did not wear it. Confirming lets training load treat the day as known.'))];
    },
  },

  device: { title: 'Watch battery and sync', m: 'device', noRange: true, render() { return [batteryDetail(), ...devicesView()]; } },
};

function compRow(name, comp, weight) {
  const sc = comp && isNum(comp.score) ? comp.score : null;
  return h('div', { class: 'comp-row' },
    h('span', { class: 'name' }, name, isNum(weight) ? h('span', { style: { fontWeight: 400, color: 'var(--ink-3)', fontSize: '13px' } }, ` ${Math.round(weight * 100)}%`) : null),
    h('span', { class: `score${sc == null ? ' none' : ''}` }, sc == null ? 'Missing' : String(Math.round(sc))),
    h('div', { class: `meter${sc == null ? ' empty' : ''}`, 'aria-hidden': 'true' }, sc != null ? h('span', { style: { width: `${clamp(sc, 0, 100)}%` } }) : null, h('i')),
    comp && comp.detail ? h('span', { class: 'detail' }, comp.detail) : null);
}

function spotChecks(pts) {
  pts=pts.filter(point=>point.context==='manual');
  const ok = pts.filter(p => isNum(p.experimental_rmssd_ms));
  const allQuality=(D().hrv || {}).quality || {};
  const q=allQuality.context==='manual' ? allQuality : {};
  return card('hrv', 'Daytime spot checks', { chip: expChip(), cls: 'wide' },
    pts.length ? [
      lineChart({ items: pts.slice(-30).map(p => ({ key: isoOf(new Date(p.ts * 1000)), label: isoOf(new Date(p.ts * 1000)), v: p.experimental_rmssd_ms ?? null, hollow: p.context !== 'scheduled', note: `${fmtClock(p.ts)}, ${p.context || 'manual'}, ${String(p.quality || '').replace(/_/g, ' ')}` })), W: chartW(), H: 160, unit: 'ms', label: 'Recent HRV recordings' }),
      h('p', { class: 'lede', style: { fontSize: '13.5px' } }, `${ok.length} of ${pts.length} recent recordings were clean enough to use. Gaps include recordings excluded by interval quality, missing motion calibration or movement.`),
      isNum(q.experimental_rmssd_ms) ? stats([['Latest', fmt(q.experimental_rmssd_ms, 1), 'ms'], ['Beats kept', isNum(q.retained_fraction) ? `${fmt(q.retained_fraction * 100)}%` : '—'], ['Taken', fmtClock((D().hrv || {}).ts)]]) : null,
    ] : pending('No spot checks yet', 'Open the HRV app on the watch and keep still for three minutes.'));
}

function trainingReviewCard() {
  const ledger=D().training_ledger;
  if (!ledger) return null;
  const controls=[];
  const ack=h('input',{type:'checkbox'}), error=h('p',{class:'sheet-error','aria-live':'polite'});
  const rows=(ledger.days || []).slice().reverse().map(day=>{
    const include=h('input',{type:'checkbox','aria-label':`Review ${day.date}`});
    const status=h('select',{'aria-label':`Confirmation for ${day.date}`},
      ['unknown','complete','rest'].map(value=>h('option',{value,selected:value===(day.confirmation || 'unknown')},cap(value))));
    controls.push({include,status,day});
    return h('li',null,h('span',{class:'t'},`${day.date} · ${day.status}`),
      h('span',{class:'s'},`${day.workouts.length} sessions · HR load ${fmt(day.recorded_hr_load)} · effort load ${fmt(day.recorded_rpe_load)}${isNum(day.hr_coverage_pct) ? ` · HR coverage ${fmt(day.hr_coverage_pct,1)}%` : ''}`),
      (day.blockers || []).length ? h('span',{class:'s'},day.blockers.join('; ')) : null,
      h('span',{class:'acts'},include,status));
  });
  const save=h('button',{class:'btn',type:'button',onclick:async e=>{
    const days=controls.filter(x=>x.include.checked).map(x=>({date:x.day.date,status:x.status.value}));
    if (!days.length || !ack.checked) {error.textContent='Select dates and acknowledge that you reviewed their training history.';return;}
    const button=e.currentTarget;button.disabled=true;error.textContent='';
    try {await api('api/days/batch','POST',{acknowledged:true,days});toast('Reviewed days saved');await load(true);}
    catch (failure) {error.textContent=failure.message;}
    finally {button.disabled=false;}
  }},'Save selected reviews');
  return card('calendar','Training history review',{cls:'wide'},
    stats([['Consecutive finished days',`${ledger.confirmed_consecutive_days} / ${ledger.required_days}`],['Baseline ends',ledger.baseline_end],['Open today',ledger.today.date]]),
    h('p',{class:'lede'},`${ledger.blockers.length} date(s) block a complete 42-day baseline. Missing coverage is not rest; recorded session loads remain useful before the baseline matures.`),
    h('details',{class:'info'},h('summary',null,'Review dates and exact blockers'),h('ul',{class:'list'},rows),
      h('label',null,ack,' I reviewed these dates and know whether all training was recorded.'),error,save));
}

function readinessHistoryCard() {
  const recovery=rec(), current=recovery.readiness || {};
  const rows=recovery.readiness_history || [], byDay=new Map();
  rows.forEach(row=>{if (!byDay.has(row.day)) byDay.set(row.day,row);});
  const history=[...byDay.values()].sort((a,b)=>a.day.localeCompare(b.day));
  const comparable=[];
  if (history.length) {
    const end=recovery.today || history.at(-1).day;
    const last=Date.parse(end+'T00:00:00Z');
    const first=Math.max(Date.parse(history[0].day+'T00:00:00Z'),last-89*86400000);
    for (let stamp=first;stamp<=last;stamp+=86400000) {
      const day=new Date(stamp).toISOString().slice(0,10), row=byDay.get(day);
      comparable.push({key:day,label:day,v:current.comparability_key && row?.comparability_key===current.comparability_key ? row.readiness.score : null});
    }
  }
  return card('ready','Comparable readiness history',{cls:'wide',chip:expChip()},
    comparable.some(row=>isNum(row.v)) ? lineChart({items:comparable,W:chartW(),H:160,label:'Readiness with the same input set and method',unit:'of 100'}) : pending('History building','Snapshots begin when this version is deployed. Missing days are not reconstructed.'),
    h('p',{class:'foot'},'Only snapshots with the current input set and method appear on this line. A changed method or input set leaves a gap.'),
    h('details',{class:'info'},h('summary',null,'Stored snapshot methods'),h('ul',{class:'list'},rows.slice(0,30).map(row=>h('li',null,
      h('span',{class:'t'},`${row.day} · ${fmt(row.readiness.score)}`),h('span',{class:'s'},`${row.readiness.components_count ?? '?'} / 4 inputs · ${row.formula_version} · ${row.comparability_key.slice(0,10)}`))))));
}

function minuteProvenancePanel() {
  const ts=D().collection_health?.measurements?.heart_rate?.measured_at;
  const output=h('div',{'aria-live':'polite'});
  return h('details',{class:'info'},h('summary',null,'Source evidence for the latest HR minute'),
    h('p',{class:'foot'},'Sources are reported by the uploader. Their compatibility priority is a reconciliation policy, not proof of sensor accuracy.'),
    isNum(ts) ? h('button',{class:'btn small',type:'button',onclick:async e=>{
      const button=e.currentTarget;button.disabled=true;
      try {
        const data=await api(`api/provenance/minute?ts=${encodeURIComponent(ts)}`);
        const observations=data.observations || [], byId=new Map(observations.map(x=>[x.id,x]));
        const winner=field=>{
          const id=data.winners?.[field], observation=byId.get(id);
          if (!id) return 'Unknown';
          return observation ? `${observation.source} · ${id.slice(0,10)}` : `Observation ${id.slice(0,10)} (outside recent list)`;
        };
        output.replaceChildren(h('dl',{class:'kv'},kv('Measured',fmtDateTime(ts)),
          kv('HR winner',winner('hr')),kv('Steps winner',winner('steps')),kv('Activity winner',winner('active')),
          kv('Reconciliation',data.algorithm_version || 'Unknown')),
          h('ul',{class:'list'},observations.map(x=>h('li',null,h('span',{class:'t'},`${x.source} · ${x.id.slice(0,10)}`),
            h('span',{class:'s'},`HR ${x.hr ?? 'unknown'} · steps ${x.steps ?? 'unknown'} · activity ${x.active ?? 'unknown'}; first received ${isNum(x.received) ? fmtDateTime(x.received) : 'unknown (legacy baseline)'}`)))),
          h('p',{class:'foot'},'At most 50 observation summaries are shown. Raw batches stay private in the server journal; earlier overwritten source details cannot be recovered.'));
      } catch (error) { output.replaceChildren(h('p',null,'Could not load source evidence. Try again.')); }
      finally {button.disabled=false;}
    }},'Inspect source evidence') : h('p',null,'No stored HR minute to inspect.'),output);
}

function collectionHealthCard() {
  const c=D().collection_health;
  if (!c) return card('device','Collection health',{cls:'wide'},pending('Diagnostics unavailable','Refresh after the server update.'));
  const measurement=(label,key)=>{
    const m=c.measurements?.[key] || {};
    return kv(label,isNum(m.measured_at) ? `${fmtDateTime(m.measured_at)} (${ago(m.age_seconds)})` : 'Not recorded');
  };
  const col=c.collector || {}, transport=c.transport || {}, latest=(c.daily || []).at(-1);
  const warnings=[];
  if (!isNum(transport.last_received)) warnings.push('No upload receipt is stored. Check GravelEx export settings, URL, token and connection test.');
  else if (transport.age_seconds>3*3600) warnings.push('No server receipt for over three hours. Check the phone network and export status; the server cannot tell whether the phone is offline.');
  const hr=c.measurements?.heart_rate || {};
  if (!isNum(hr.measured_at) || hr.age_seconds>3*3600) warnings.push('No recent stored minute HR. Check sensor settings and watch-history transfer. This alone cannot establish whether the watch was worn.');
  if (col.missed_slots>0) warnings.push(`${col.missed_slots} previously advertised night slot(s) have no saved capture here after the 15-minute transfer grace period. Check recorder and transfer status.`);
  const perSource=(c.sources || []).map(x=>h('li',null,
    h('span',{class:'t'},x.source),
    h('span',{class:'s'},`Received ${fmtDateTime(x.last_received)} · report dated ${fmtDateTime(x.last_report_ts)} · ${fmt(x.reports)} reports in ${c.window_days} days`)));
  const coverage=(c.daily || []).slice(-7).map(x=>h('li',null,
    h('span',{class:'t'},x.date),
    h('span',{class:'s'},`${fmt(x.hr_minutes)}/${fmt(x.expected_minutes)} elapsed full minutes with HR${isNum(x.hr_coverage_pct) ? ` (${fmt(x.hr_coverage_pct,1)}%)` : ''}; ${fmt(x.minute_buckets)} buckets stored · ${fmt(x.day_minutes)}-minute local day`)));
  return card('device','Collection health',{cls:'wide'},
    h('p',{class:'lede'},'Receipts show transport activity. Measurement times show what actually reached the history store.'),
    h('dl',{class:'kv'},kv('Server response',fmtDateTime(c.now)),
      kv('Last accepted upload',isNum(transport.last_received) ? `${fmtDateTime(transport.last_received)} (${ago(transport.age_seconds)})` : 'Not recorded'),
      measurement('Minute heart rate','heart_rate'),measurement('Blood oxygen','oxygen'),measurement('Saved HRV capture','hrv'),measurement('Sleep session ended','sleep_end'),
      kv('Last watch snapshot',isNum(c.latest_snapshot?.last_report_ts) ? fmtDateTime(c.latest_snapshot.last_report_ts) : 'Not recorded'),
      kv('Today HR coverage',latest && isNum(latest.hr_coverage_pct) ? `${fmt(latest.hr_coverage_pct,1)}% of elapsed full minutes` : 'Not available'),
      kv('Night schedule evidence',col.schedule_status==='historical_advertised' ? `${fmt(col.expected_due)} advertised slots past grace period; ${fmt(col.stored)} captures matched` : 'Unknown — no usable saved schedule'),
      kv('Watch → phone transfer','Unknown — not reported by the phone'),kv('Pending phone records','Unknown — queue telemetry not yet available')),
    warnings.length ? h('ul',{class:'list'},warnings.map(x=>h('li',null,h('span',{class:'s'},x)))) : null,
    minuteProvenancePanel(),
    h('details',{class:'info'},h('summary',null,'Daily observed-minute coverage'),h('ul',{class:'list'},coverage),
      h('p',{class:'foot'},'Coverage counts sampled timestamp buckets, not continuous HR or wear time. DST days use their actual duration. Missing data never confirms rest.')),
    h('details',{class:'info'},h('summary',null,'Night slot evidence'),
      (col.slots || []).length ? h('ul',{class:'list'},col.slots.map(slot=>h('li',null,
        h('span',{class:'t'},fmtDateTime(slot.scheduled_ts)),h('span',{class:'s'},
          ({saved:'Saved capture matched',missed:'No capture received after grace period',pending:'Transfer grace period still open',unknown:'Uncertain — cancellation or scheduling evidence incomplete'})[slot.status] || 'Unknown'))))
        : h('p',null,'No past advertised slots can be established from stored reports.'),
      h('p',{class:'foot'},'These are historical advertisements. Execution and cancellations are not directly observed; uncertain slots are excluded from missing counts.')),
    h('details',{class:'info'},h('summary',null,'Upload sources'),perSource.length ? h('ul',{class:'list'},perSource) : h('p',null,'No batch reports stored. HRV collector receipts are tracked separately.')),
    h('p',{class:'foot'},'A collector launch is not a saved measurement. A saved capture may still fail HRV quality checks. Empty uploads do not refresh sensor timestamps.'));
}

function devicesView() {
  const d = D(), lt = d.latest || {}, st = lt.status || {}, col = d.collector || {};
  const sched = (d.collector_history || []).find(c => isNum(c.next_wakeup)) || {};
  return [
    collectionHealthCard(),
    card('device', 'HRV recorder', { cls: 'wide' },
      isNum(col.received) ? h('dl', { class: 'kv' },
        kv('Last saved recording',isNum(d.collection_health?.measurements?.hrv?.measured_at) ? fmtDateTime(d.collection_health.measurements.hrv.measured_at) : 'Not recorded'),
        kv('Last recorder status',fmtDateTime(col.ts)),
        kv('Started', col.launch === 'scheduled' ? 'On schedule' : 'By hand'),
        kv('App version', col.collector_version != null ? String(col.collector_version) : '—'),
        sched.nights_enabled != null ? kv('Night recordings', sched.nights_enabled ? 'On' : 'Off') : null,
        isNum(sched.schedule_ok) ? kv('Scheduled slots', `${sched.schedule_ok} armed${sched.schedule_error ? `, error ${sched.schedule_error}` : ''}`) : null,
        isNum(sched.next_wakeup) && sched.next_wakeup > nowSec() ? kv('Next night recording', fmtDateTime(sched.next_wakeup)) : null)
        : pending('The HRV app has not reported yet', 'Install it on the watch and open it once.')),
    card('hrv', 'HRV measurement quality', { cls: 'wide', chip: expChip() },
      d.hrv && d.hrv.quality ? (() => {
        const q=d.hrv.quality, motion=q.motion || {}, delivery=q.delivery || {};
        return [h('p',{class:'lede'},q.stream==='batched_ppi_unverified' ? PPI_SOURCE_EXPLANATION : (motion.reason || 'Interval and motion quality are being checked.')),
          h('dl',{class:'kv'},kv('Taken',fmtDateTime(d.hrv.ts)),
            kv('Eligibility',String(q.status || 'unknown').replace(/_/g,' ')),
            kv('Method',String(q.metric || 'unknown').replace(/_/g,' ')),
            q.stream==='batched_ppi_unverified' ? kv('PPI delivery',`${delivery.event_count ?? delivery.total_delivered ?? 0} readings; ${delivery.batch_groups_exact_same_offset ?? delivery.batch_count ?? 0} multiple-reading arrival groups`) : null,
            q.stream==='batched_ppi_unverified' ? kv('Largest arrival group',`${delivery.max_batch_size ?? 0} readings (arrival timing only)`) : null,
            kv('Firmware / collector',`${motion.firmware || 'unknown'} / ${motion.collector_version ?? 'unknown'}`),
            kv('Motion assessment',String(motion.status || 'unknown').replace(/_/g,' ')),
            kv('Mean movement delta',isNum(motion.normalized_mean) ? `${fmt(motion.normalized_mean,2)} collector units/transition` : 'Unknown'),
            kv('Highest 5-second movement',isNum(motion.max_window_mean) ? `${fmt(motion.max_window_mean,2)} collector units/transition` : 'Not recorded by this collector'),
            kv('Largest movement transition',isNum(motion.max_window_delta) ? `${fmt(motion.max_window_delta,0)} collector units` : 'Not recorded by this collector'),
            kv('Motion coverage',isNum(motion.coverage_fraction) ? `${fmt(motion.coverage_fraction*100)}% of calibrated rate` : 'No matching calibration'),
            kv('Algorithm',q.algorithm_version || 'Legacy')),
          h('p',{class:'foot'},'Motion windows use callback receipt times, not exact sample timestamps. Uncalibrated recordings remain stored for diagnostics and do not contribute to HRV recovery or stress scores. Genuine beat intervals and reconstructed tachograms use separate baselines.')];
      })() : pending('No HRV quality report yet','Open the HRV watch app to save a recording.')),
    card('device', 'Watch apps', { cls: 'wide' },
      h('p', { class: 'lede', style: { marginTop: 0 } }, 'Install these on the watch, then pair each one in the phone app. HRV and History upload to this server; Today only reads the daily summary.'),
      h('ul', { class: 'list' }, [
        ['hrv', 'HRV', 'Night and daytime HRV, resting heart rate and breathing.'],
        ['history', 'History', 'Minute heart rate and steps, sleep sessions and workouts.'],
        ['today', 'Today', 'Readiness, sleep, HRV, resting pulse and training load on the watch. Read-only.'],
      ].map(([kind, name, what]) => h('li', null, h('span', { class: 't' }, name), h('span', { class: 's' }, what),
        h('span', { class: 'acts' }, h('a', { class: 'btn small', href: `download/${kind}`, download: '' }, 'Download'), h('a', { class: 'btn small', href: `pair?kind=${kind}` }, 'Pair')))))),
  ];
}
const kv = (k, v) => [h('dt', null, k), h('dd', null, v)];

/* ================================================================== *
 * Household account and device management
 * ================================================================== */
const USERNAME_RE = /^[a-z0-9][a-z0-9._-]{2,39}$/;
const PASSWORD_MIN = 12;
function accountName(user) { return user?.display_name || user?.username || 'Signed-in user'; }
function accountRole(user) { return user?.role === 'admin' ? 'Administrator' : 'Household member'; }
function accountFailure(error) { return error?.message === 'Login required.' ? error.message : 'Could not save this household change. Try again.'; }
function clearPasswordFields(root) { root?.querySelectorAll('input[type="password"]').forEach(input => { input.value = ''; }); }

async function loadAccount() {
  S.accountLoading = true;
  try {
    const data = await settingsRequest('api/me');
    S.account = data.user || null;
    if (S.account) S.account.devices = Array.isArray(data.devices) ? data.devices : [];
  } catch (error) {
    if (error.message === 'Login required.') throw error;
    S.account = null;
  } finally { S.accountLoading = false; }
}

async function loadAdminUsers() {
  if (!S.account || S.account.role !== 'admin') return [];
  const data = await settingsRequest('api/admin/users');
  S.adminUsers = Array.isArray(data.users) ? data.users : [];
  return S.adminUsers;
}

function ownDevicesCard() {
  const account = S.account, devices = account?.devices || [];
  if (!account) return null;
  const output = h('div', { class: 'above' });
  const renderDevices = () => {
    output.replaceChildren(
      devices.length ? h('ul', { class: 'list' }, devices.map(device => {
        const name = h('input', { type: 'text', maxlength: 80, value: device.name || '', 'aria-label': `Device label for ${device.name || device.id}` });
        const save = h('button', { type: 'button', class: 'btn small' }, 'Save label');
        const toggle = h('button', { type: 'button', class: 'btn small' }, device.active === false ? 'Enable' : 'Disable');
        save.onclick = async () => {
          save.disabled = true;
          try { const data = await settingsRequest(`api/devices/${encodeURIComponent(device.id)}`, 'PATCH', { name: name.value.trim() }); Object.assign(device, data.device || { name: name.value.trim() }); toast('Device label saved'); renderDevices(); }
          catch (error) { toast(accountFailure(error), true); save.disabled = false; }
        };
        toggle.onclick = async () => {
          toggle.disabled = true;
          try { const data = await settingsRequest(`api/devices/${encodeURIComponent(device.id)}`, 'PATCH', { active: device.active === false }); Object.assign(device, data.device || { active: device.active === false }); toast(device.active === false ? 'Device disabled' : 'Device enabled'); renderDevices(); }
          catch (error) { toast(accountFailure(error), true); toggle.disabled = false; }
        };
        const pairLinks = device.active === false ? null : h('div', { class: 'acts' }, ['history', 'hrv', 'today'].map(kind => h('a', { class: 'btn small', href: `pair?kind=${kind}&device=${encodeURIComponent(device.id)}` }, `Pair ${kind.toUpperCase()}`)));
        return h('li', null, h('span', { class: 't' }, device.name || 'Unnamed device'), h('span', { class: 's' }, device.active === false ? 'Disabled' : 'Active'), h('div', { class: 'btn-row' }, name, save, toggle), pairLinks);
      })) : h('p', { class: 'foot' }, 'No devices are registered yet.'),
      h('form', { class: 'above', onsubmit: async event => {
        event.preventDefault(); const input = event.currentTarget.querySelector('input'); const button = event.currentTarget.querySelector('button');
        const name = input.value.trim(); if (!name) return; button.disabled = true;
        try { const data = await settingsRequest('api/devices', 'POST', { name }); if (data.device) devices.push(data.device); input.value = ''; toast('Device added'); renderDevices(); }
        catch (error) { toast(accountFailure(error), true); button.disabled = false; }
      } }, h('label', { class: 'field' }, 'Add a device', h('input', { type: 'text', maxlength: 80, placeholder: 'Watch or phone name', required: true })), h('button', { type: 'submit', class: 'btn' }, 'Add device')),
    );
  };
  renderDevices();
  return card('device', 'Your devices', { cls: 'wide' }, h('p', { class: 'lede' }, `${accountName(account)} · ${accountRole(account)}`), h('p',{class:'foot'},'Pair each watch using its device links below. Disabling a device keeps its history and requires new pairing tokens when enabled again.'), output);
}

function householdCard() {
  if (!S.account || S.account.role !== 'admin') return null;
  const output = h('div', { class: 'above' }, h('p', { class: 'foot' }, 'Loading household members…'));
  const refresh = async () => { try { await loadAdminUsers(); renderUsers(); } catch (error) { output.replaceChildren(h('p', { class: 'sheet-error' }, 'Household members could not be loaded.')); } };
  const renderUsers = () => {
    const users = S.adminUsers || [];
    const rows = users.map(user => {
      const display = h('input', { type: 'text', maxlength: 80, value: user.display_name || '', 'aria-label': `Display name for ${user.username}` });
      const role = h('select', { disabled: user.id === S.account.id, 'aria-label': `Role for ${user.username}` }, ['user', 'admin'].map(value => h('option', { value, selected: user.role === value }, value === 'admin' ? 'Administrator' : 'Member')));
      const active = h('input', { type: 'checkbox', disabled: user.id === S.account.id, checked: user.active !== false, 'aria-label': `Enabled: ${user.username}` });
      const password = h('input', { type: 'password', minlength: PASSWORD_MIN, maxlength: 1024, autocomplete: 'new-password', placeholder: 'New password (optional)', 'aria-label': `Reset password for ${user.username}` });
      const save = h('button', { type: 'button', class: 'btn small' }, 'Save');
      save.onclick = async () => {
        const body = { display_name: display.value.trim(), role: role.value, active: active.checked };
        if (password.value) { if (password.value.length < PASSWORD_MIN) { toast(`Password must be at least ${PASSWORD_MIN} characters.`, true); return; } body.password = password.value; }
        save.disabled = true;
        try { await settingsRequest(`api/admin/users/${encodeURIComponent(user.id)}`, 'PATCH', body); user.display_name = body.display_name; user.role = body.role; user.active = body.active; password.value = ''; toast('Household member saved'); renderUsers(); }
        catch (error) { toast(accountFailure(error), true); save.disabled = false; }
        finally { clearPasswordFields(output); }
      };
      const deviceBox = h('div', { class: 'above' }, h('strong', null, 'Devices'), h('p', { class: 'foot' }, 'Loading devices…'));
      settingsRequest(`api/admin/users/${encodeURIComponent(user.id)}/devices`).then(data => {
        const devices = Array.isArray(data.devices) ? data.devices : [];
        const addDevice = h('form', { class: 'above', onsubmit: async event => {
          event.preventDefault(); const input = event.currentTarget.querySelector('input'); const button = event.currentTarget.querySelector('button'); const name = input.value.trim(); if (!name) return; button.disabled = true;
          try { const result = await settingsRequest(`api/admin/users/${encodeURIComponent(user.id)}/devices`, 'POST', { name }); if (result.device) devices.push(result.device); input.value = ''; toast('Device added'); renderUsers(); }
          catch (error) { toast(accountFailure(error), true); button.disabled = false; }
        } }, h('label', { class: 'field' }, 'Add device', h('input', { type: 'text', maxlength: 80, required: true, placeholder: 'Watch or phone name' })), h('button', { type: 'submit', class: 'btn small' }, 'Add device'));
        deviceBox.replaceChildren(h('strong', null, 'Devices'), devices.length ? h('ul', { class: 'list' }, devices.map(device => {
          const label = h('input', { type: 'text', maxlength: 80, value: device.name || '', 'aria-label': `Device label for ${device.name || device.id}` });
          const enabled = h('input', { type: 'checkbox', checked: device.active !== false, 'aria-label': `Enabled device ${device.name || device.id}` });
          const saveDevice = h('button', { type: 'button', class: 'btn small' }, 'Save device');
          saveDevice.onclick = async () => { saveDevice.disabled = true; try { await settingsRequest(`api/admin/users/${encodeURIComponent(user.id)}/devices/${encodeURIComponent(device.id)}`, 'PATCH', { name: label.value.trim(), active: enabled.checked }); toast('Device saved'); } catch (error) { toast(accountFailure(error), true); saveDevice.disabled = false; } };
          return h('li', null, label, enabled, saveDevice);
        })) : h('p', { class: 'foot' }, 'No devices registered.'), addDevice);
      }).catch(() => {});
      return h('li', null, h('span', { class: 't' }, user.username), h('div', { class: 'form-grid two' }, h('label', { class: 'field' }, 'Display name', display), h('label', { class: 'field' }, 'Role', role)), h('label', { class: 'check' }, active, ' Enabled'), h('label', { class: 'field' }, 'Reset password', password), save, deviceBox);
    });
    const newUsername = h('input', { type: 'text', required: true, minlength: 3, maxlength: 40, pattern: '[a-z0-9._-]{3,40}', autocomplete: 'username', placeholder: 'username' });
    const newDisplay = h('input', { type: 'text', maxlength: 80, placeholder: 'Display name' });
    const newPassword = h('input', { type: 'password', required: true, minlength: PASSWORD_MIN, maxlength: 1024, autocomplete: 'new-password', placeholder: `At least ${PASSWORD_MIN} characters` });
    const create = h('button', { type: 'submit', class: 'btn primary' }, 'Create member');
    output.replaceChildren(h('ul', { class: 'list' }, rows), h('form', { class: 'above', onsubmit: async event => {
      event.preventDefault(); if (!USERNAME_RE.test(newUsername.value) || newPassword.value.length < PASSWORD_MIN) { toast('Use a valid username and a password of at least 12 characters.', true); return; }
      create.disabled = true;
      try { await settingsRequest('api/admin/users', 'POST', { username: newUsername.value, display_name: newDisplay.value.trim(), password: newPassword.value, role: 'user' }); toast('Household member created'); clearPasswordFields(output); await refresh(); }
      catch (error) { toast(accountFailure(error), true); create.disabled = false; }
      finally { newPassword.value = ''; }
    } }, h('h3', null, 'Add household member'), h('div', { class: 'form-grid two' }, h('label', { class: 'field' }, 'Username', newUsername), h('label', { class: 'field' }, 'Display name', newDisplay)), h('label', { class: 'field' }, 'Password', newPassword), create));
  };
  if (S.adminUsers) renderUsers(); else refresh();
  return card('device', 'Household management', { cls: 'wide' }, h('p', { class: 'lede' }, 'Create members, reset passwords, and manage access for this household.'), output);
}

/* ================================================================== *
 * Settings
 * ================================================================== */
function settingsCard() {
  const prof = D().profile || {};
  let method = prof.load_method === 'rpe' ? 'rpe' : 'hr';
  const hrInput = h('input', { type: 'number', inputmode: 'numeric', min: 100, max: 230, step: 1, value: isNum(prof.hr_max) ? prof.hr_max : '', id: 'hrmax', placeholder: 'e.g. 185' });
  const segBtns = [['hr', 'Heart rate'], ['rpe', 'Session effort']].map(([k, t]) =>
    h('button', { type: 'button', 'aria-pressed': String(method === k), onclick: e => { method = k; segBtns.forEach(b => b.setAttribute('aria-pressed', String(b === e.currentTarget))); } }, t));
  const err = h('p', { class: 'sheet-error', role: 'alert', hidden: true });
  const save = h('button', { type: 'submit', class: 'btn primary' }, 'Save profile');
  const form = h('form', { class: 'above', onsubmit: async e => {
    e.preventDefault(); err.hidden = true; save.disabled = true;
    const body = { load_method: method };
    if (hrInput.value.trim()) body.hr_max = Number(hrInput.value);
    try { await api('api/profile', 'PUT', body); toast('Profile saved'); load(true); }
    catch (x) { err.textContent = x.message; err.hidden = false; }
    finally { save.disabled = false; }
  } },
  h('div', { class: 'form-grid two' },
    h('label', { class: 'field', for: 'hrmax' }, 'Maximum heart rate', hrInput, h('span', { class: 'field-hint' }, 'Sets the zones for heart-rate load.')),
    h('div', { class: 'field' }, h('span', { id: 'lm' }, 'Training load from'), h('div', { class: 'seg', role: 'group', 'aria-labelledby': 'lm' }, segBtns))),
  err, h('div', { class: 'btn-row' }, save));
  return card('train', 'Profile', { cls: 'wide' }, form);
}

function clearApiSecret() { API_TOKENS.secret = null; }
function clearSessionHealth(broadcast = true) {
  clearApiSecret(); API_TOKENS.tokens=[]; API_TOKENS.scopes=[]; API_TOKENS.loaded=false;
  S.account=null; S.adminUsers=null; S.accountLoading=false;
  S.data=null; S.daysLoaded=0; S.error=null; S.offlineSince=null;
  document.body.replaceChildren();
  if (broadcast) { try { localStorage.setItem('ph-auth-logout', String(Date.now())); } catch (e) { /* private mode */ } }
}
async function settingsRequest(path, method = 'GET', body) {
  const res = await fetch(path, { method, headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-PH-Request': '1' }, body: body ? JSON.stringify(body) : undefined, cache: 'no-store' });
  let data = null; try { data = await res.json(); } catch (e) { /* safe generic error below */ }
  if (res.status === 401) { clearSessionHealth(); window.location.assign('/login'); throw new Error('Login required.'); }
  if (!res.ok) throw new Error('Settings request failed. Try signing in again.');
  return data || {};
}
function apiTokenMetadata(data) { return data.token_info || data.token_record || data; }
function apiTokensCard() {
  const doc = HUB_CONFIG.api_docs_url ? h('a', { href: HUB_CONFIG.api_docs_url, target: '_blank', rel: 'noopener' }, 'See API documentation') : null;
  if (!API_TOKENS.loaded) settingsRequest('api/settings/api-tokens').then(d=>{API_TOKENS.tokens=d.tokens||[];API_TOKENS.scopes=d.scopes||[];API_TOKENS.loaded=true;render();}).catch(()=>{});
  const name=h('input',{id:'token-name',type:'text',maxlength:80,value:'Home Assistant',required:true});
  const expiry=h('select',{id:'token-expiry'},[['7','7 days'],['30','30 days'],['90','90 days'],['365','365 days'],['never','Never']].map(([v,t])=>h('option',{value:v,selected:v==='90'},t)));
  const scopeIds=['summary:read','history:read','raw:read'];
  const scopes=h('div',{class:'above'},h('span',{class:'field-label'},'Scopes'),scopeIds.map((id,i)=>{const input=h('input',{type:'checkbox',id:`scope-${id}`,value:id,checked:i===0});return h('label',{class:'check',for:`scope-${id}`},input,id==='raw:read'?'raw:read (raw HRV)':id);}));
  const err=h('p',{class:'sheet-error',role:'alert',hidden:true});
  const reveal=h('div',{class:'above',hidden:!API_TOKENS.secret});
  function showSecret(secret, meta) { API_TOKENS.secret=secret; reveal.hidden=false; reveal.replaceChildren(h('p',{class:'lede'},'Copy this token now. It is shown once and is not saved in this browser.'),h('input',{type:'password',readonly:true,value:secret, 'aria-label':'New API token'}),h('button',{type:'button',class:'btn small',onclick:async()=>{try{await navigator.clipboard.writeText(secret);toast('Token copied');}catch(e){}}},'Copy'),h('button',{type:'button',class:'btn small',onclick:()=>{clearApiSecret();reveal.hidden=true;reveal.replaceChildren();}},'Hide')); }
  const create=h('button',{class:'btn primary',type:'submit'},'Create token');
  const form=h('form',{class:'above',onsubmit:async e=>{e.preventDefault();err.hidden=true;create.disabled=true;try{const selected=[...scopes.querySelectorAll('input:checked')].map(x=>x.value);const d=await settingsRequest('api/settings/api-tokens','POST',{name:name.value,scopes:selected,expires_in_days:expiry.value==='never'?null:Number(expiry.value)});const meta=apiTokenMetadata(d);if(d.token)showSecret(d.token,meta);API_TOKENS.tokens=[meta,...API_TOKENS.tokens];}catch(x){err.textContent='Could not create token. Check your sign-in and selected scopes.';err.hidden=false;}finally{create.disabled=false;}}},h('div',{class:'form-grid two'},h('label',{class:'field',for:'token-name'},'Token name',name),h('label',{class:'field',for:'token-expiry'},'Expiry',expiry)),scopes,err,h('div',{class:'btn-row'},create));
  const list=API_TOKENS.tokens.map(t=>h('li',{class:'token-row'},h('strong',null,t.name||'Unnamed token'),h('span',{class:'foot'},`${t.prefix||'token'} · ${(t.scopes||[]).join(', ')} · ${t.revoked_at?'Revoked':t.expires_at?`Expires ${new Date(t.expires_at*1000).toLocaleDateString()}`:'Never expires'}${t.last_used_at?` · Last used ${new Date(t.last_used_at*1000).toLocaleString()}`:''}`),!t.revoked_at?h('button',{type:'button',class:'btn small',onclick:async()=>{try{await settingsRequest(`api/settings/api-tokens/${encodeURIComponent(t.id)}`,'DELETE');API_TOKENS.tokens=API_TOKENS.tokens.filter(x=>x.id!==t.id);render();}catch(e){toast('Could not revoke token');}}},'Revoke'):null));
  if (API_TOKENS.secret) showSecret(API_TOKENS.secret, null);
  return card('device','API access',{cls:'wide'},h('p',{class:'lede'},'Manage read-only tokens for trusted integrations. Sign in to this PH server to manage them.',doc?' ':null,doc),form,reveal,list.length?h('ul',{class:'list'},list):h('p',{class:'foot'},'No API tokens yet.'),h('button',{type:'button',class:'btn small',onclick:async()=>{try{await fetch('/auth/logout',{method:'POST',headers:{'X-PH-Request':'1','Accept':'application/json'}});}finally{clearSessionHealth();window.location.assign('/login');}}},'Sign out'));
}

function themeCard() {
  const cur = store.get('ph-theme') || 'system';
  const btns = [['system', 'Match device'], ['light', 'Light'], ['dark', 'Dark']].map(([k, t]) =>
    h('button', { type: 'button', 'aria-pressed': String(cur === k), onclick: () => { setTheme(k === 'system' ? null : k); render(); } }, t));
  return card('device', 'Appearance', {}, h('div', { class: 'seg above', role: 'group', 'aria-label': 'Theme' }, btns));
}

function setTheme(t) {
  store.set('ph-theme', t);
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  paintThemeButton();
}
const effectiveDark = () => (document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark';
function paintThemeButton() {
  const b = document.getElementById('theme-btn');
  const dark = effectiveDark();
  b.replaceChildren(icon(dark ? 'sun' : 'moon'));
  b.setAttribute('aria-label', dark ? 'Use light theme' : 'Use dark theme');
  b.title = b.getAttribute('aria-label');
}

/* ================================================================== *
 * Dialogs: effort, workout, day status
 * ================================================================== */
const dlg = () => document.getElementById('dialog');
function openSheet(...content) {
  const d = dlg();
  d.replaceChildren(h('div', { class: 'sheet-body' }, content));
  if (typeof d.showModal === 'function') d.showModal(); else d.setAttribute('open', '');
  const f = d.querySelector('input, [aria-pressed="true"], button');
  if (f) f.focus();
}
function closeSheet() { const d = dlg(); if (d.open) d.close(); }

function rpeScale(initial, onPick) {
  let val = isNum(initial) ? Math.round(initial) : null;
  const btns = [];
  for (let i = 1; i <= 10; i++) {
    btns.push(h('button', { type: 'button', 'aria-pressed': String(val === i), 'aria-label': `Effort ${i} of 10`, onclick: e => { val = i; btns.forEach(b => b.setAttribute('aria-pressed', String(b === e.currentTarget))); onPick(i); } }, String(i)));
  }
  return [h('div', { class: 'rpe', role: 'group', 'aria-label': 'Perceived effort from 1 to 10' }, btns), h('div', { class: 'rpe-words', 'aria-hidden': 'true' }, h('span', null, 'Very easy'), h('span', null, 'Maximal'))];
}

function workoutRevisionRequest(w, values) {
  return {...values, operation_id:crypto.randomUUID(), expected_revisions:{[w.id]:w.edit_revision ?? 0},expected_fingerprints:{[w.id]:w.edit_fingerprint}};
}
function openWorkoutEdit(w) {
  const localTime=ts=>{const date=new Date(ts*1000);return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,19);};
  const kind=h('input',{type:'text',maxlength:40,value:w.kind || 'workout'});
  const start=h('input',{type:'datetime-local',step:1,value:localTime(w.start),required:true});
  const minutes=h('input',{type:'number',min:1,max:1440,step:'any',value:w.seconds/60,required:true});
  const split=h('input',{type:'datetime-local',step:1,value:localTime(w.start+Math.floor(w.seconds/2)),required:true});
  const candidates=(D().workouts || []).filter(other=>other.id!==w.id && !other.ignored && !w.ignored && other.start<=w.start+w.seconds && other.start+other.seconds>=w.start);
  const merge=h('select',{'aria-label':'Recording to merge'},h('option',{value:''},'Choose an overlapping or adjacent recording'),candidates.map(other=>h('option',{value:other.id},`${cap(other.kind)} · ${fmtDateTime(other.start)} · ${Math.round(other.seconds/60)} min`)));
  const error=h('p',{class:'sheet-error',role:'alert'});
  const run=async (button,body)=>{
    button.disabled=true;error.textContent='';
    try {await api('api/workout-edits','POST',body);closeSheet();toast('Correction saved; review affected training dates again');await load(true);}
    catch(failure) {error.textContent=failure.message+' Refresh before retrying if this session changed.';button.disabled=false;}
  };
  const save=h('button',{type:'submit',class:'btn primary'},'Save correction');
  const form=h('form',{onsubmit:event=>{event.preventDefault();run(save,workoutRevisionRequest(w,{operation:'edit',id:w.id,type:kind.value.trim(),start:Math.floor(new Date(start.value).getTime()/1000),end:Math.floor(new Date(start.value).getTime()/1000)+Math.round(Number(minutes.value)*60)}));}},
    h('div',{class:'form-grid'},h('label',{class:'field'},'Activity',kind),h('label',{class:'field'},'Started (this browser’s local time)',start),h('label',{class:'field'},'Minutes',minutes)),save);
  const splitButton=h('button',{type:'button',class:'btn',onclick:event=>run(event.currentTarget,workoutRevisionRequest(w,{operation:'split',id:w.id,at:Math.floor(new Date(split.value).getTime()/1000)}))},'Split recording');
  const mergeButton=h('button',{type:'button',class:'btn',onclick:event=>{
    const other=candidates.find(item=>item.id===merge.value);
    if(!other){error.textContent='Choose another recording to merge.';return;}
    run(event.currentTarget,{operation:'merge',operation_id:crypto.randomUUID(),ids:[w.id,other.id],keeper_id:w.id,expected_revisions:{[w.id]:w.edit_revision ?? 0,[other.id]:other.edit_revision ?? 0},expected_fingerprints:{[w.id]:w.edit_fingerprint,[other.id]:other.edit_fingerprint}});
  }},'Merge into this recording');
  openSheet(h('h2',null,'Correct workout'),h('p',null,'Original imports are preserved. Corrections recalculate heart-rate coverage and clear affected day confirmations. Load belongs to the local start date; crossing midnight does not split it automatically.'),form,
    h('details',{class:'info'},h('summary',null,'Split or merge'),h('label',{class:'field'},'Split at (this browser’s local time)',split),splitButton,h('p',null,'A merge uses the combined continuous time span and keeps this recording’s activity and effort. The other recording is excluded.'),merge,mergeButton),error,
    h('div',{class:'btn-row'},h('button',{type:'button',class:'btn',onclick:()=>openWorkoutAudit(w)},'Correction history'),h('button',{type:'button',class:'btn',onclick:closeSheet},'Cancel')));
}
async function openWorkoutAudit(w) {
  const output=h('div',null,'Loading correction history…');
  openSheet(h('h2',null,'Workout correction history'),output,h('button',{type:'button',class:'btn',onclick:closeSheet},'Close'));
  try {
    const response=await api(`api/workout-edits?id=${encodeURIComponent(w.id)}`);
    const rows=response.history || [];
    const describe=record=>`${cap(record.kind)} · ${fmtDateTime(record.start)} · ${fmt(record.seconds/60,1)} min · effort ${fmt(record.rpe)}${record.ignored ? ' · excluded' : ''}`;
    output.replaceChildren(rows.length ? h('ul',{class:'list'},rows.map(row=>{
      const undo=h('button',{type:'button',class:'btn small',onclick:async()=>{
        undo.disabled=true;
        try {await api('api/workout-edits','POST',{operation:'undo',operation_id:crypto.randomUUID(),target_operation_id:row.operation_id,expected_revisions:Object.fromEntries(row.after.map(record=>[record.id,record.edit_revision])),expected_fingerprints:Object.fromEntries(row.after.map(record=>[record.id,record.edit_fingerprint]))});closeSheet();toast('Correction reversed; review affected dates again');await load(true);}
        catch(failure){toast(failure.message,true);undo.disabled=false;}
      }},'Undo this correction');
      return h('li',null,h('span',{class:'t'},`${cap(row.operation)} · ${fmtDateTime(row.observed_at)}`),
        h('p',null,'Before: ',row.before.map(describe).join('; ')),h('p',null,'After: ',row.after.map(describe).join('; ')),undo);
    })) : h('p',null,'No corrections have been saved for this recording.'));
  } catch(failure) {output.textContent=failure.message;}
}

function openRpe(w) {
  let val = isNum(w.rpe) ? Math.round(w.rpe) : null;
  const err = h('p', { class: 'sheet-error', role: 'alert', hidden: true });
  const save = h('button', { type: 'button', class: 'btn primary', disabled: val == null, onclick: async () => {
    save.disabled = true; err.hidden = true;
    try { await api('api/workouts', 'POST', workoutRevisionRequest(w,{id:w.id,rpe:val})); closeSheet(); toast('Effort saved'); load(true); }
    catch (x) { err.textContent = x.message; err.hidden = false; save.disabled = false; }
  } }, 'Save effort');
  openSheet(h('h2', null, 'How hard was it?'),
    h('p', null, `${cap(w.kind || 'Workout')}, ${fmtDateTime(w.start)}${isNum(w.seconds) ? `, ${Math.round(w.seconds / 60)} min` : ''}`),
    rpeScale(val, v => { val = v; save.disabled = false; }), err,
    h('div', { class: 'btn-row' }, save, h('button', { type: 'button', class: 'btn', onclick: closeSheet }, 'Cancel')));
}

async function toggleIgnore(w) {
  try { await api('api/workouts', 'POST', workoutRevisionRequest(w,{id:w.id,ignored:!w.ignored})); toast(w.ignored ? 'Workout restored' : 'Workout excluded'); load(true); }
  catch (x) { toast(x.message, true); }
}

function openWorkoutForm() {
  const operation_id=crypto.randomUUID();
  const now = new Date(); now.setMinutes(now.getMinutes() - 60, 0, 0);
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  let rpe = null;
  const type = h('input', { id: 'w-type', type: 'text', maxlength: 40, value: '', placeholder: 'e.g. run, strength, climbing', autocomplete: 'off' });
  const start = h('input', { id: 'w-start', type: 'datetime-local', value: local, max: new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16), required: true });
  const mins = h('input', { id: 'w-min', type: 'number', inputmode: 'numeric', min: 1, max: 1440, value: 45, required: true });
  const err = h('p', { class: 'sheet-error', role: 'alert', hidden: true });
  const save = h('button', { type: 'submit', class: 'btn primary' }, 'Log workout');
  const form = h('form', { onsubmit: async e => {
    e.preventDefault(); err.hidden = true;
    const ts = Math.floor(new Date(start.value).getTime() / 1000);
    if (!isNum(ts)) { err.textContent = 'Enter when the workout started.'; err.hidden = false; return; }
    if (rpe == null) { err.textContent = 'Pick an effort from 1 to 10.'; err.hidden = false; return; }
    save.disabled = true;
    try { await api('api/workouts', 'POST', {operation_id, type: type.value.trim() || 'workout', start: ts, seconds: Math.round(Number(mins.value) * 60), rpe }); closeSheet(); toast('Workout logged'); load(true); }
    catch (x) { err.textContent = x.message; err.hidden = false; save.disabled = false; }
  } },
  h('h2', null, 'Log a workout'),
  h('p', null, 'For sessions the watch did not record. Load is minutes times effort.'),
  h('div', { class: 'form-grid' },
    h('label', { class: 'field', for: 'w-type' }, 'Activity', type),
    h('div', { class: 'form-grid two' }, h('label', { class: 'field', for: 'w-start' }, 'Started', start), h('label', { class: 'field', for: 'w-min' }, 'Minutes', mins)),
    h('div', { class: 'field' }, h('span', null, 'Effort'), rpeScale(null, v => { rpe = v; }))),
  err, h('div', { class: 'btn-row' }, save, h('button', { type: 'button', class: 'btn', onclick: closeSheet }, 'Cancel')));
  openSheet(form);
}

function openDay(day, row) {
  const conf = (D().confirmations || {})[day];
  const err = h('p', { class: 'sheet-error', role: 'alert', hidden: true });
  const choose = async status => {
    err.hidden = true;
    try { await api('api/days', 'POST', { date: day, day, status }); closeSheet(); toast(status === 'unknown' ? 'Confirmation cleared' : status === 'rest' ? 'Marked as rest day' : 'Marked complete'); load(true); }
    catch (x) { err.textContent = x.message; err.hidden = false; }
  };
  const opt = (status, title, sub) => h('button', { type: 'button', class: 'btn', 'aria-pressed': String(conf === status || (!conf && status === 'unknown')), onclick: () => choose(status) }, title, h('span', null, sub));
  openSheet(h('h2', null, fmtDay(day, { weekday: 'long', day: 'numeric', month: 'long' })),
    h('p', null, isNum(row.load) ? `Recorded load ${fmt(row.load)}.` : 'No workout load recorded.'),
    h('div', { class: 'choice' },
      opt('complete', 'Complete', 'Every workout this day was recorded.'),
      opt('rest', 'Rest day', 'No training at all.'),
      opt('unknown', 'Unknown', 'Not sure, or the watch was off.')),
    err, h('div', { class: 'btn-row' }, h('button', { type: 'button', class: 'btn', onclick: closeSheet }, 'Cancel')));
}

let toastTimer = null;
function toast(msg, isErr) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.toggle('err', !!isErr); t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 3200);
}

/* ================================================================== *
 * Routing and pages
 * ================================================================== */
const TABS = [
  { id: 'today', label: 'Today' }, { id: 'sleep', label: 'Sleep' }, { id: 'recovery', label: 'Recovery' },
  { id: 'training', label: 'Training' }, { id: 'more', label: 'More' },
];
const DETAIL_TAB = { oxygen:'recovery', weight: 'today', ready: 'recovery', sleep: 'sleep', hrv: 'recovery', rhr: 'recovery', breath: 'recovery', stress: 'recovery', steps: 'today', heart: 'today', train: 'training', workouts: 'training', calendar: 'training', device: 'more' };

function route() {
  const raw = decodeURIComponent(location.hash.replace(/^#\/?/, ''));
  if (raw.startsWith('d/')) { const key = raw.slice(2); if (DETAIL[key]) return { detail: key, tab: DETAIL_TAB[key] }; }
  return { tab: TABS.some(t => t.id === raw) ? raw : 'today' };
}

function renderNav(active) {
  const mk = bottom => TABS.map(t => h('a', { href: `#${t.id}`, 'aria-current': t.id === active ? 'page' : null }, icon(t.id), h('span', null, t.label)));
  document.querySelector('.tabs-top').replaceChildren(...mk(false));
  document.querySelector('.tabs-bottom').replaceChildren(...mk(true));
}

function pageHead(title, sub, extra) {
  return h('div', { class: 'page-head' }, h('div', null, h('h1', null, title), sub ? h('p', null, sub) : null), extra || null);
}

/* AI briefing: written nightly from computed facts, numbers checked server-side. */
async function regenerateBriefing(btn) {
  btn.disabled = true; btn.textContent = 'Writing…';
  try {
    const res = await fetch('api/briefing/run', { method: 'POST', headers: { Accept: 'application/json', 'X-PH-Request': '1' } });
    if (res.status === 401) { clearSessionHealth(); window.location.assign('/login'); return; }
    const out = await res.json();
    if (out.status === 'disabled') { toast('No language model is configured on the server.', true); return; }
    toast(out.status === 'busy' ? 'A briefing is already being written.' : 'Writing a new briefing; this takes a minute or two.');
    const before = (D().briefing || {}).created;
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 10000));
      await load(true);
      if ((D().briefing || {}).created !== before) { render(); toast('Briefing updated.'); return; }
    }
  } catch (e) { toast('Could not start the briefing.', true); }
  finally { btn.disabled = false; btn.textContent = 'Regenerate'; }
}

function briefPanel(page, opts = {}) {
  const b = D().briefing, p = b && b.pages && b.pages[page];
  if (!p || !(p.headline || p.summary)) return null;
  if (b.requires_refresh) return card('device','Briefing needs refresh',{cls:'wide'},
    h('p',null,'The saved briefing uses older collection or quality rules. Generate a new briefing before using it as current guidance.'),
    opts.regenerate ? h('button',{class:'btn small',type:'button',onclick:e=>regenerateBriefing(e.currentTarget)},'Regenerate') : h('a',{href:'#more'},'Refresh from More'));
  const age = nowSec() - b.created, stale = age > 30 * 3600;
  const when = stale ? fmtDateTime(b.created) : fmtClock(b.created);
  const btn = opts.regenerate ? h('button', { class: 'btn small', type: 'button', onclick: e => regenerateBriefing(e.currentTarget) }, 'Regenerate') : null;
  return h('article', { class: 'card wide brief', 'data-m': 'ready' },
    h('div', { class: 'card-head' }, swatch(), h('h2', null, 'Briefing'), chip(stale ? 'Out of date' : 'AI', stale ? '' : 'exp', 'Written by a language model from your computed numbers')),
    p.headline ? h('p', { class: 'brief-head' }, p.headline) : null,
    p.summary ? h('p', { class: 'lede' }, p.summary) : null,
    (p.highlights || []).length ? h('ul', { class: 'brief-list' }, p.highlights.map(x => h('li', { class: `tone-${x.tone}` }, h('i', { 'aria-hidden': 'true' }), x.text))) : null,
    p.focus ? h('div', { class: 'brief-focus' }, h('strong', null, 'Focus today'), h('span', null, p.focus)) : null,
    (p.data_notes || []).length ? info('Data notes', ...p.data_notes) : null,
    h('p', { class: 'brief-meta' }, `Written ${when} by ${b.model || 'the language model'} from your numbers. Every number is checked against the data.`, btn ? ' ' : null, btn));
}

const PAGES = {
  today() {
    const section = (title, ...cards) => [h('h2', { class: 'section-title' }, title), h('div', { class: 'feed' }, cards)];
    return [h('div', { class: 'hero-row' }, watchHero(), briefPanel('today')),
      section('Sleep & recovery', CARDS.sleep(), CARDS.hrv(), CARDS.rhr(), oxygenCard(), CARDS.stress()),
      section('Activity', CARDS.steps(), CARDS.intensity(), CARDS.energy(), CARDS.heart(), CARDS.fitness(), CARDS.train(), CARDS.workouts(3)),
      section('Body & device', CARDS.weight(), CARDS.device())];
  },
  sleep() {
    return [pageHead('Sleep', null, rangeSwitch()), h('div', { class: 'feed' }, briefPanel('sleep'), DETAIL.sleep.render())];
  },
  recovery() {
    return [pageHead('Recovery'), h('div', { class: 'feed' }, briefPanel('recovery'), DETAIL.ready.render().filter(n => n.tagName !== 'P'), CARDS.hrv(), CARDS.rhr(), oxygenCard(), CARDS.stress())];
  },
  training() {
    return [pageHead('Training', null, rangeSwitch()), h('div', { class: 'feed' }, briefPanel('training'), trainingReviewCard(), DETAIL.train.render(), CARDS.fitness(), CARDS.intensity(), CARDS.workouts(5), CARDS.calendar())];
  },
  more() {
    return [pageHead('More'), h('div', { class: 'feed' },
      card('device', 'Phone app · GravelEx', {cls:'wide'},
        h('p',{class:'lede'},'Your own Gravel fork: direct HR, steps, sleep, workouts and SpO₂ export. Install updates through Obtainium.'),
        h('p',null,h('a',{class:'btn',href:'download/gravelex'},'Download GravelEx APK')),
        h('p',{class:'foot'},'Keep your existing Gravel installed. Only one app should manage the watch at a time.'),
        h('p',null,h('a',{href:'#d/oxygen'},'Health export setup and token'),' · ',sourceLink('Source and instructions'))),
      briefPanel('more', { regenerate: true }), ownDevicesCard(), householdCard(), devicesView(), settingsCard(), apiTokensCard(), themeCard(),
      card('device', 'About', { cls: 'wide' }, h('p', { class: 'lede', style: { marginTop: 0 } }, 'Pebble Health runs on your own server. Your data stays there. Scores marked experimental come from an unvalidated watch sensor and are for personal interest, not medical use.')))];
  },
};

function render() {
  const main = document.getElementById('main');
  const r = route();
  renderNav(r.tab);
  renderStatus();
  if (!S.data) {
    main.replaceChildren(S.error
      ? h('div', { class: 'error-state' }, h('h1', null, 'Could not load your data'), h('p', null, S.error), h('button', { type: 'button', class: 'btn primary', onclick: () => load(true) }, 'Try again'))
      : h('p', { class: 'loading' }, 'Loading your data…'));
    return;
  }
  let content;
  try {
    if (r.detail) {
      const det = DETAIL[r.detail];
      const back = h('a', { class: 'back', href: `#${r.tab}` }, icon('back'), TABS.find(t => t.id === r.tab).label);
      content = [back, pageHead(det.title, null, det.noRange ? null : rangeSwitch()), h('div', { class: 'feed', 'data-m': det.m }, det.render())];
    } else {
      content = PAGES[r.tab]();
    }
  } catch (e) {
    console.error(e);
    content = [h('div', { class: 'error-state' }, h('h1', null, 'This view could not be drawn'), h('p', null, 'The server sent data in an unexpected shape. Other sections may still work.'))];
  }
  const y = window.scrollY, sameView = main.dataset.view === location.hash;
  main.replaceChildren(...[content].flat(Infinity).filter(Boolean));
  main.dataset.view = location.hash;
  if (sameView) window.scrollTo(0, y);
}

function renderStatus() {
  const line = document.getElementById('sync-line'), banner = document.getElementById('banner');
  const d = S.data;
  if (d) {
    const received=d.collection_health?.transport?.last_received;
    const age=isNum(received) ? Math.max(0,nowSec()-received) : null;
    line.textContent=isNum(age) ? `Server received upload ${ago(age)}` : 'No upload receipt recorded';
    line.classList.toggle('stale', isNum(age) && age > 3 * 3600);
  } else line.textContent = S.error ? 'Offline' : 'Loading…';
  if (S.offlineSince !== null && d) {
    const when = S.offlineSince ? new Date(S.offlineSince).toLocaleString(LOCALE, { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : 'an earlier visit';
    banner.textContent = `Offline – showing data from ${when}.`;
    banner.hidden = false;
  } else banner.hidden = true;
}

/* ================================================================== *
 * Boot
 * ================================================================== */
async function boot() {
  try { HUB_CONFIG = await api('api/config'); } catch (e) { HUB_CONFIG = {}; }
  try { await loadAccount(); } catch (e) { return; }
  document.getElementById('refresh-btn').replaceChildren(icon('refresh'));
  document.getElementById('refresh-btn').addEventListener('click', () => load(true));
  document.getElementById('theme-btn').addEventListener('click', () => { setTheme(effectiveDark() ? 'light' : 'dark'); if (route().tab === 'more') render(); });
  paintThemeButton();
  try { matchMedia('(prefers-color-scheme: dark)').addEventListener('change', paintThemeButton); } catch (e) { /* old Safari */ }
  dlg().addEventListener('click', e => { if (e.target === dlg()) closeSheet(); });
  window.addEventListener('hashchange', () => { clearApiSecret(); clearPasswordFields(document); render(); window.scrollTo(0, 0); document.getElementById('main').focus({ preventScroll: true }); });
  window.addEventListener('beforeunload', clearApiSecret);
  window.addEventListener('storage', e => { if (e.key === 'ph-auth-logout') { clearSessionHealth(false); window.location.assign('/login'); } });
  window.addEventListener('pageshow', e => { if (!e.persisted) return; fetch('api/summary?days=1', { headers: { Accept: 'application/json', 'X-PH-Request': '1' }, cache: 'no-store' }).then(res => { if (res.status === 401) { clearSessionHealth(); window.location.assign('/login'); } }).catch(() => {}); });
  let lastW = window.innerWidth, rt = null;
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { if ((lastW >= 720) !== (window.innerWidth >= 720)) render(); lastW = window.innerWidth; }, 150); });
  window.addEventListener('scroll', () => document.querySelector('.topbar').classList.toggle('scrolled', window.scrollY > 4), { passive: true });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && Date.now() - S.fetchedAt > 60000) load(true); });
  setInterval(() => { if (document.visibilityState === 'visible') load(true); }, 5 * 60000);
  setInterval(renderStatus, 30000);
  window.addEventListener('online', () => load(true));
  render();
  load(true);
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('sw.js', { scope: './' }).catch(e => console.warn('Service worker not registered:', e.message));
  }
}
boot();
