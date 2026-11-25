/* Pebble Health — desktop layout: responsive charts, the Today board and the
   focus pages (Sleep, Recovery, Training, Heart, Body).
   Loaded before app.js and holds declarations only: every function here calls
   app.js helpers (h, s, card, D, …) at render time, never while loading. */
'use strict';

/* ================================================================== *
 * Responsive charts
 * ================================================================== */
/* Chart functions draw into a fixed viewBox. responsive() remembers how a
   chart was drawn and redraws it at the width it actually occupies, so text
   stays at its CSS size (11px) in narrow tiles and wide cards alike. */
const chartRO = typeof ResizeObserver === 'function' ? new ResizeObserver(entries => {
  for (const e of entries) {
    const el = e.target;
    if (!el.isConnected || !el._redraw) continue;
    const w = Math.round(e.contentRect.width);
    if (w < 60 || Math.abs(w - el._vbW) < 3) continue;
    const next = el._redraw(w);
    if (!next) continue;
    chartRO.unobserve(el);
    el.replaceWith(next);
  }
}) : null;

/* key: the width property of an options argument; null: the argument is the width itself. */
function responsive(fn, argIndex = 0, key = 'W') {
  const wrapped = (...args) => {
    const svg = fn(...args);
    if (!(svg instanceof SVGSVGElement)) return svg;
    svg._vbW = svg.viewBox.baseVal.width;
    svg._redraw = w => {
      const a = args.slice();
      a[argIndex] = key ? { ...(a[argIndex] || {}), [key]: w } : w;
      return wrapped(...a);
    };
    if (chartRO) chartRO.observe(svg);
    return svg;
  };
  return wrapped;
}
/* Charts from the previous view must not stay observed after a re-render. */
function resetCharts() { if (chartRO) chartRO.disconnect(); }

/* ================================================================== *
 * Small helpers
 * ================================================================== */
const median = arr => { const v = arr.filter(isNum).sort((a, b) => a - b); if (!v.length) return null; const m = v.length >> 1; return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2; };
const quantile = (sorted, q) => sorted.length ? sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(q * (sorted.length - 1))))] : null;
const localMidnight = (date = new Date()) => { const d = new Date(date); d.setHours(0, 0, 0, 0); return Math.floor(d.getTime() / 1000); };
const isoMidnight = iso => Math.floor(parseISO(iso).getTime() / 1000);
/* Clock time as minutes, with evening times before morning ones (for medians of bedtimes). */
const eveningMin = ts => { const d = new Date(ts * 1000); const m = d.getHours() * 60 + d.getMinutes(); return m < 12 * 60 ? m + 1440 : m; };
const dayMin = ts => { const d = new Date(ts * 1000); return d.getHours() * 60 + d.getMinutes(); };
const clockOfMin = m => isNum(m) ? `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(Math.round(m % 60) % 60).padStart(2, '0')}` : '—';
function signedDur(sec) { if (!isNum(sec)) return '—'; return `${sec >= 0 ? '+' : '−'}${fmtDur(Math.abs(sec), true)}`; }

function kpi(m, label, value, sub, href) {
  const kids = [h('span', { class: 'kpi-l' }, h('i'), label), h('strong', { class: `kpi-v${value == null || value === '—' ? ' none' : ''}` }, value ?? '—'), sub ? h('span', { class: 'kpi-s' }, sub) : null];
  return href ? h('a', { class: 'kpi', 'data-m': m, href }, kids) : h('div', { class: 'kpi', 'data-m': m }, kids);
}
const kpis = (...items) => h('div', { class: 'kpis' }, items.filter(Boolean));
function miniKv(label, value, note) {
  return h('div', { class: 'mk' }, h('span', { class: 'mk-l' }, label), h('strong', { class: 'mk-v' }, value ?? '—'), note ? h('span', { class: 'mk-n' }, note) : null);
}
function bar(value, max, label) {
  return h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': max, 'aria-valuenow': value, 'aria-label': label },
    h('span', { style: { width: `${clamp(100 * (value || 0) / Math.max(1, max), 0, 100)}%` } }));
}
/* Detail cards are built full width; focus pages pair some of them side by side. */
const half = el => { if (el && el.classList) el.classList.remove('wide'); return el; };
const wide = el => { if (el && el.classList) el.classList.add('wide'); return el; };
function focusPage(title, headExtra, top, main, side) {
  return [pageHead(title, null, headExtra), top || null,
    h('div', { class: 'focus' }, h('div', { class: 'focus-main' }, main), h('aside', { class: 'focus-side' }, side))];
}

/* ================================================================== *
 * Lazily loaded long-range and intraday data
 * ================================================================== */
const YEAR = { items: null, at: 0, loading: false, error: null };
async function loadYear() {
  if (YEAR.loading || Date.now() - YEAR.at < 15 * 60000) return;
  YEAR.loading = true;
  try { YEAR.items = (await api('api/daily')).items || []; YEAR.error = null; }
  catch (e) { YEAR.error = e.message; }
  finally { YEAR.at = Date.now(); YEAR.loading = false; const r = route(); if (!r.detail && ['today', 'heart'].includes(r.tab)) render(); }
}
const INTRA = {};
async function loadIntraday(day) {
  const cur = INTRA[day], ttl = day === serverToday() ? 120000 : 3600000;
  if (cur && (cur.loading || Date.now() - cur.at < ttl)) return;
  INTRA[day] = { ...(cur || {}), loading: true, at: Date.now() };
  try { INTRA[day] = { data: await api(`api/intraday?date=${encodeURIComponent(day)}`), at: Date.now() }; }
  catch (e) { INTRA[day] = { ...(INTRA[day] || {}), error: e.message, loading: false, at: Date.now() }; }
  const r = route(); if (!r.detail && r.tab === 'heart') render();
}

/* ================================================================== *
 * Day ribbon: a time-aligned swim-lane view of one stretch of time
 * ================================================================== */
/* obs: [{ts,hr,steps,snapshot}] · sleep: [{intervals:[[a,b]], restful, gaps, label, title}]
   Lanes keep real gaps: no reading means nothing is drawn. */
function dayRibbonRaw({ W = 900, t0, t1, obs = [], sleep = [], workouts = [], stress = [], spo2 = [], hrH = 120, now = nowSec(), label = 'Day timeline' }) {
  const L = 78, R = 12, pw = W - L - R, span = t1 - t0;
  const X = ts => L + (clamp(ts, t0, t1) - t0) / span * pw;
  const y = { sleep: 26, work: 54, hr: 78 };
  y.steps = y.hr + hrH + 12; y.stress = y.steps + 46; y.spo2 = y.stress + 18;
  const H = y.spo2 + 18;
  const kids = [];
  const lane = (text, yy) => kids.push(s('text', { class: 'lane-l', x: 0, y: yy }, text));
  lane('Sleep', y.sleep + 14); lane('Activity', y.work + 12); lane('Heart', y.hr + 24); lane('Steps', y.steps + 24); lane('Stress', y.stress + 9); lane('SpO₂', y.spo2 + 9);

  // Hour grid with a stronger line and weekday at each midnight.
  const perHour = pw / (span / 3600), stepH = [1, 2, 3, 4, 6, 12].find(n => n * perHour >= 46) || 12;
  const first = new Date(t0 * 1000); first.setMinutes(0, 0, 0);
  for (let t = Math.ceil(first.getTime() / 1000 / 3600) * 3600; t <= t1; t += 3600) {
    const d = new Date(t * 1000), hr = d.getHours();
    if (hr % stepH) continue;
    const x = X(t), midnight = hr === 0;
    kids.push(s('line', { class: `grid${midnight ? ' zero' : ''}`, x1: x, x2: x, y1: 18, y2: H - 2 }));
    kids.push(s('text', { x, y: 12, 'text-anchor': x < L + 14 ? 'start' : x > W - R - 14 ? 'end' : 'middle', class: midnight ? 'lbl-strong' : null },
      midnight ? d.toLocaleDateString(LOCALE, { weekday: 'short' }) : `${String(hr).padStart(2, '0')}:00`));
  }
  if (now < t1) kids.push(s('rect', { class: 'rib-future', x: X(now), y: 18, width: Math.max(0, X(t1) - X(now)), height: H - 20 }));

  // Sleep lane: asleep (soft), restful (solid), recorded gaps (hatched).
  sleep.forEach(n => {
    (n.intervals || []).forEach(([a, b]) => { if (b > t0 && a < t1) kids.push(s('rect', { class: `rib-sleep${n.nap ? ' nap' : ''}`, x: X(a), y: y.sleep, width: Math.max(1.5, X(b) - X(a)), height: 20, rx: 5 }, s('title', null, n.title))); });
    (n.restful || []).forEach(([a, b]) => { if (b > t0 && a < t1) kids.push(s('rect', { class: 'rib-restful', x: X(a), y: y.sleep + 3, width: Math.max(1.5, X(b) - X(a)), height: 14, rx: 3 }, s('title', null, `Restful ${fmtClock(a)}–${fmtClock(b)}`))); });
    (n.gaps || []).forEach(([a, b]) => { if (b > t0 && a < t1) kids.push(s('rect', { class: 'rib-gap', x: X(a), y: y.sleep, width: Math.max(1.5, X(b) - X(a)), height: 20 }, s('title', null, `Not recorded ${fmtClock(a)}–${fmtClock(b)}`))); });
    const all = (n.intervals || []).filter(([a, b]) => b > t0 && a < t1);
    if (all.length && n.label) {
      const a = X(all[0][0]), b = X(all.at(-1)[1]);
      if (b - a > 70) kids.push(s('text', { class: 'rib-in', x: (a + b) / 2, y: y.sleep + 14, 'text-anchor': 'middle' }, n.label));
    }
  });

  // Workouts lane.
  let labelEnd = -1;
  workouts.slice().sort((p, q) => p.start - q.start).forEach(w => {
    const a = w.start, b = w.start + (w.seconds || 0);
    if (!(b > t0 && a < t1)) return;
    const x0 = X(a), x1 = Math.max(X(b), x0 + 3);
    kids.push(s('rect', { class: 'rib-work', x: x0, y: y.work, width: x1 - x0, height: 16, rx: 4 },
      s('title', null, `${cap(w.kind || 'Workout')} · ${fmtClock(a)}–${fmtClock(b)} · ${activitySource(w)}`)));
    // Phone and watch often record the same session; label only the first of overlapping blocks.
    if (x1 - x0 > 46 && x0 > labelEnd) { kids.push(s('text', { class: 'rib-in', x: x0 + 5, y: y.work + 12 }, cap(w.kind || 'Workout'))); labelEnd = x1; }
  });

  // Heart rate lane with moderate/vigorous zone bands from the profile maximum.
  const hrPts = obs.filter(o => isNum(o.hr) && o.ts >= t0 && o.ts <= t1).sort((a, b) => a.ts - b.ts);
  const hrMax = D().profile?.hr_max;
  const vals = hrPts.map(p => p.hr);
  let lo = vals.length ? Math.min(...vals) : 50, hi = vals.length ? Math.max(...vals) : 120;
  lo = Math.max(30, Math.floor((lo - 6) / 10) * 10); hi = Math.ceil((Math.max(hi, lo + 40) + 6) / 10) * 10;
  const Y = v => y.hr + hrH - (clamp(v, lo, hi) - lo) / (hi - lo) * hrH;
  if (isNum(hrMax)) {
    [[.64, .77, 'moderate'], [.77, 9, 'vigorous']].forEach(([a, b, cls]) => {
      const va = hrMax * a, vb = Math.min(hrMax * b, hi);
      if (va >= hi) return;
      kids.push(s('rect', { class: `rib-zone ${cls}`, x: L, width: pw, y: Y(vb), height: Math.max(0, Y(Math.max(va, lo)) - Y(vb)) }, s('title', null, `${cap(cls)} zone from ${fmt(va)} bpm (${Math.round(a * 100)}% of max ${hrMax})`)));
      kids.push(s('text', { class: 'zone-l', x: W - R - 4, y: Y(vb) + 11, 'text-anchor': 'end' }, cls));
    });
  }
  [lo, (lo + hi) / 2, hi].forEach((v, i) => {
    kids.push(s('line', { class: `grid${i === 0 ? ' zero' : ''}`, x1: L, x2: W - R, y1: Y(v), y2: Y(v) }));
    kids.push(s('text', { x: L - 6, y: Y(v) + (i === 2 ? 9 : 3.5), 'text-anchor': 'end' }, fmt(v)));
  });
  if (hrPts.length) {
    drawSeries(kids, seriesPaths(hrPts.map(p => ({ ...p, v: p.hr })), 'v', i => X(hrPts[i].ts), Y,
      (a, b) => a.snapshot || b.snapshot || b.ts - a.ts > 360), 'line rib-hr');
    hrPts.filter(p => p.snapshot).forEach(p => kids.push(s('circle', { class: 'dot hollow', cx: X(p.ts), cy: Y(p.hr), r: 2.6 })));
    const minP = hrPts.reduce((m, p) => p.hr < m.hr ? p : m), maxP = hrPts.reduce((m, p) => p.hr > m.hr ? p : m);
    [[minP, 14], [maxP, -7]].forEach(([p, dy]) => {
      kids.push(s('circle', { class: 'dot', cx: X(p.ts), cy: Y(p.hr), r: 3.4 }, s('title', null, `${fmtClock(p.ts)}: ${p.hr} bpm`)));
      kids.push(s('text', { class: 'lbl-strong', x: X(p.ts), y: Y(p.hr) + dy, 'text-anchor': 'middle' }, String(p.hr)));
    });
  } else kids.push(s('text', { x: L + pw / 2, y: y.hr + hrH / 2, 'text-anchor': 'middle' }, 'No heart rate recorded in this period'));

  // Steps per 15 minutes.
  const buckets = new Map();
  obs.forEach(o => { if (!o.snapshot && isNum(o.steps) && o.steps > 0 && o.ts >= t0 && o.ts < t1) { const k = t0 + Math.floor((o.ts - t0) / 900) * 900; buckets.set(k, (buckets.get(k) || 0) + o.steps); } });
  const smax = niceMax(Math.max(100, ...buckets.values()));
  const bw = Math.max(1, pw * 900 / span - 1);
  buckets.forEach((v, k) => {
    const hh = Math.max(1.5, v / smax * 36);
    kids.push(s('rect', { class: 'rib-steps', x: X(k), y: y.steps + 38 - hh, width: bw, height: hh, rx: Math.min(2, bw / 3) }, s('title', null, `${fmtClock(k)}–${fmtClock(k + 900)}: ${fmt(v)} steps`)));
  });
  kids.push(s('line', { class: 'grid zero', x1: L, x2: W - R, y1: y.steps + 38, y2: y.steps + 38 }));
  kids.push(s('text', { x: L - 6, y: y.steps + 9, 'text-anchor': 'end' }, fmtAxis(smax)));

  // Stress heat strip (15-minute estimates) and SpO2 spot readings.
  const sw = Math.max(1, pw * 900 / span);
  stress.forEach(p => { if (isNum(p.score) && p.ts >= t0 && p.ts < t1) kids.push(s('rect', { class: 'rib-stress', x: X(p.ts), y: y.stress, width: sw, height: 10, style: `opacity:${(.18 + .82 * clamp(p.score, 0, 100) / 100).toFixed(2)}` }, s('title', null, `${fmtClock(p.ts)}: estimated stress ${fmt(p.score)} / 100`))); });
  kids.push(s('rect', { class: 'rib-track', x: L, y: y.stress, width: pw, height: 10, rx: 2 }));
  spo2.forEach(r => { if (isNum(r.percent) && r.ts >= t0 && r.ts < t1) kids.push(s('circle', { class: 'rib-spo2', cx: X(r.ts), cy: y.spo2 + 6, r: 4 }, s('title', null, `${fmtClock(r.ts)}: SpO₂ ${fmt(r.percent, 1)}%`))); });

  if (now >= t0 && now <= t1) {
    kids.push(s('line', { class: 'rib-now', x1: X(now), x2: X(now), y1: 16, y2: H - 2 }));
    kids.push(s('text', { class: 'rib-now-l', x: X(now) + 4, y: 24 }, 'now'));
  }

  // Hover read-out: one crosshair and a small panel with every lane's value.
  const cross = s('line', { class: 'rib-cross', x1: 0, x2: 0, y1: 18, y2: H - 2, visibility: 'hidden' });
  const tipBg = s('rect', { class: 'rib-tip-bg', rx: 8, width: 150, height: 10 });
  const tipText = s('text', { class: 'rib-tip' });
  const tip = s('g', { visibility: 'hidden', 'pointer-events': 'none' }, tipBg, tipText);
  const hit = s('rect', { class: 'hit', x: L, y: 18, width: pw, height: H - 20 });
  const near = (arr, ts, within, key = 'ts') => { let best = null, bd = within; arr.forEach(p => { const dd = Math.abs(p[key] - ts); if (dd <= bd) { bd = dd; best = p; } }); return best; };
  const at = ts => {
    const out = [fmtClock(ts)];
    const p = near(hrPts, ts, 300); if (p) out.push(`Heart rate ${p.hr} bpm`);
    const k = t0 + Math.floor((ts - t0) / 900) * 900; if (buckets.get(k)) out.push(`${fmt(buckets.get(k))} steps / 15 min`);
    const st = stress.find(q => ts >= q.ts && ts < q.ts + 900 && isNum(q.score)); if (st) out.push(`Stress ${fmt(st.score)} / 100 (est.)`);
    const ox = near(spo2, ts, 900); if (ox) out.push(`SpO₂ ${fmt(ox.percent, 1)}%`);
    if (sleep.some(n => (n.intervals || []).some(([a, b]) => ts >= a && ts < b))) out.push('Asleep');
    const w = workouts.find(q => ts >= q.start && ts < q.start + (q.seconds || 0)); if (w) out.push(`${cap(w.kind || 'Workout')} · click to open`);
    return { lines: out, workout: w };
  };
  const svg = s('svg', { class: 'chart ribbon', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label }, kids, cross, hit, tip);
  hit.addEventListener('mousemove', e => {
    const m = svg.getScreenCTM(); if (!m) return;
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
    const ts = t0 + (pt.x - L) / pw * span, info = at(ts);
    cross.setAttribute('x1', pt.x); cross.setAttribute('x2', pt.x); cross.setAttribute('visibility', 'visible');
    tipText.replaceChildren(...info.lines.map((line, i) => s('tspan', { x: 10, dy: i ? 15 : 0, class: i ? null : 'lbl-strong' }, line)));
    const tw = 170, th = 12 + info.lines.length * 15, tx = pt.x + tw + 14 > W ? pt.x - tw - 10 : pt.x + 10;
    tipBg.setAttribute('width', tw); tipBg.setAttribute('height', th);
    tipText.setAttribute('y', 18);
    tip.setAttribute('transform', `translate(${tx},${clamp(pt.y - th / 2, 18, H - th - 2)})`);
    tip.setAttribute('visibility', 'visible');
    hit.style.cursor = info.workout ? 'pointer' : 'crosshair';
  });
  hit.addEventListener('mouseleave', () => { cross.setAttribute('visibility', 'hidden'); tip.setAttribute('visibility', 'hidden'); });
  hit.addEventListener('click', e => {
    const m = svg.getScreenCTM(); if (!m) return;
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
    const w = at(t0 + (pt.x - L) / pw * span).workout;
    if (w) openActivity(w);
  });
  return svg;
}
const dayRibbon = responsive(dayRibbonRaw);
const ribbonLegend = () => h('div', { class: 'legend rib-legend' },
  [['rib-sleep', 'Asleep'], ['rib-restful', 'Restful'], ['rib-work', 'Workout'], ['rib-hr', 'Heart rate'], ['rib-steps', 'Steps / 15 min'], ['rib-stress', 'Stress (est.)'], ['rib-spo2', 'SpO₂']]
    .map(([c, t]) => h('span', null, h('i', { class: c }), t)));

function summarySleepLanes() {
  return (rec().sleep_nights || []).map(n => ({
    intervals: (n.sleep_intervals || []).length ? n.sleep_intervals : isNum(n.onset) && isNum(n.wake) ? [[n.onset, n.wake]] : [],
    restful: n.restful_intervals || [], gaps: n.recorded_gaps || [],
    label: isNum(n.sleep_s) ? `${fmtDur(n.sleep_s, true)} asleep` : null,
    title: `Night of ${fmtDay(n.night)}: ${fmtClock(n.onset)}–${fmtClock(n.wake)}, ${fmtDur(n.sleep_s, true)} asleep, ${fmtDur(n.restful_s, true)} restful`,
  }));
}
const liveWorkouts = () => (D().workouts || []).filter(w => !w.ignored && isNum(w.start));
/* Phone and watch often record the same session. Overlapping recordings count
   once, represented by the phone recording (it carries distance and route). */
function sessions(ws) {
  const groups = [];
  ws.slice().sort((a, b) => a.start - b.start).forEach(w => {
    const g = groups.at(-1), end = w.start + (w.seconds || 0);
    if (g && w.start < g.end) { g.items.push(w); g.end = Math.max(g.end, end); }
    else groups.push({ items: [w], end });
  });
  return groups.map(g => g.items.find(w => w.source === 'phone') || g.items[0]);
}

/* ================================================================== *
 * Trend sparkline with the usual band (baseline tiles)
 * ================================================================== */
function trendSparkRaw({ items, band, W = 240, H = 46, fmtV = v => fmt(v), unit = '', label = 'Trend' }) {
  const vals = items.map(i => i.v).filter(isNum);
  const all = vals.concat(band ? band.filter(isNum) : []);
  if (!vals.length) return null;
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * .14; lo -= pad; hi += pad;
  const bw = W / Math.max(1, items.length);
  const X = i => (i + .5) * bw, Y = v => 4 + (H - 8) * (1 - (v - lo) / (hi - lo));
  const kids = [];
  if (band && isNum(band[0]) && isNum(band[1])) kids.push(s('rect', { class: 'band', x: 0, width: W, y: Y(band[1]), height: Math.max(1, Y(band[0]) - Y(band[1])) }, s('title', null, `Usual range ${fmtV(band[0])}–${fmtV(band[1])} ${unit}`)));
  drawSeries(kids, seriesPaths(items, 'v', X, Y));
  items.forEach((it, i) => { if (isNum(it.v)) kids.push(s('circle', { class: i === items.length - 1 || i === items.map(x => isNum(x.v)).lastIndexOf(true) ? 'dot last' : 'dot tiny', cx: X(i), cy: Y(it.v), r: i === items.map(x => isNum(x.v)).lastIndexOf(true) ? 3.4 : 1.6 }, s('title', null, `${tipLabel(it)}: ${fmtV(it.v)} ${unit}`))); });
  return s('svg', { class: 'chart spark', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label }, kids);
}
const trendSpark = responsive(trendSparkRaw);

/* ================================================================== *
 * Today board
 * ================================================================== */
function todayBoard() {
  loadYear();
  return h('div', { class: 'board today-board' },
    statusStrip(),
    ribbonCard(), readinessPanel(),
    sleepVital(), recoveryVital(), activityVital(),
    baselineTiles(),
    trainingMini(), latestActivityMini(), yearCard(),
    insightsStrip());
}

function statusStrip() {
  const d = D(), name = wearer(), hr = new Date().getHours();
  const greet = hr < 5 ? 'Good night' : hr < 12 ? 'Good morning' : hr < 18 ? 'Good afternoon' : 'Good evening';
  const received = d.collection_health?.transport?.last_received, age = isNum(received) ? Math.max(0, nowSec() - received) : null;
  const bat = d.watch_battery || {}, rt = bat.runtime_estimate, fresh = isNum(bat.percent) && bat.status !== 'stale';
  const left = fresh && rt ? rt.full_charge_hours * bat.percent / 100 : null;
  const cov = (d.collection_health?.daily || []).at(-1);
  const p = d.briefing?.pages?.today;
  const pill = (m, label, value, title, href) => h(href ? 'a' : 'span', { class: 'pill', 'data-m': m, title, href }, h('i'), h('span', { class: 'pill-l' }, label), h('strong', null, value));
  return h('section', { class: 'strip c12', 'aria-label': 'Status' },
    h('div', { class: 'strip-row' },
      h('div', { class: 'strip-hello' }, h('h1', null, name ? `${greet}, ${name}` : greet),
        h('p', null, new Date().toLocaleDateString(LOCALE, { weekday: 'long', day: 'numeric', month: 'long' }))),
      h('div', { class: 'strip-pills' },
        pill('device', 'Upload', isNum(age) ? ago(age) : 'none', 'Last upload accepted by the server', '#d/device'),
        pill('device', 'Battery', fresh ? `${fmt(bat.percent)}%${isNum(left) ? ` · ~${fmt(left / 24, 0)} d left` : ''}` : bat.status === 'stale' ? 'stale' : '—',
          isNum(left) ? `Estimated from ${fmt(rt.observed_discharge_hours, 0)} h of observed discharge; heavy use drains faster.` : 'Watch battery', '#d/device'),
        pill('heart', 'HR coverage', cov && isNum(cov.hr_coverage_pct) ? `${fmt(cov.hr_coverage_pct)}%` : '—', 'Share of elapsed minutes today with a stored heart rate', '#d/device'))),
    p && p.headline ? h('details', { class: 'strip-brief' },
      h('summary', null, chip('AI', 'exp', 'Written by a language model from your computed numbers'), h('span', { class: 'strip-head' }, p.headline), h('span', { class: 'strip-more' }, 'Full briefing')),
      briefPanel('today')) : null);
}

function ribbonCard() {
  const d = D(), t0 = localMidnight() - 6 * 3600;
  return card('heart', 'Last night and today', { cls: 'c8 compact ribbon-card', chip: h('a', { class: 'chip above', href: '#heart' }, 'Heart rate detail') },
    dayRibbon({ W: 900, t0, t1: t0 + 30 * 3600, obs: d.observations || [], sleep: summarySleepLanes(), workouts: liveWorkouts(),
      stress: d.daytime_stress?.points || [], spo2: d.oxygen?.readings || [], hrH: 200, label: 'Timeline from 18:00 yesterday to midnight tonight' }),
    ribbonLegend());
}

function readinessPanel() {
  const r = readinessNow(), comps = r.components || {}, weights = r.weights || {};
  const names = Object.keys(weights).length ? Object.keys(weights) : ['hrv', 'resting_hr', 'sleep', 'training_load'];
  const score = isNum(r.score) ? r.score : r.sleep_based_score;
  const p = D().briefing?.pages?.today;
  const stockV = r.formula_version === 'readiness-stock-v1';
  return card('ready', 'Readiness', { cls: 'c4 compact ready-panel', link: 'ready', chip: stockV ? chip('Estimated') : r.provisional ? chip('Provisional', '', r.reason) : expChip() },
    h('div', { class: 'ready-top' },
      h('div', { class: 'ready-ring' }, ring(score, { size: 118, stroke: 11, sub: isNum(r.score) ? readinessWord(r.score) : isNum(r.sleep_based_score) ? 'sleep only' : null, label: isNum(score) ? `Readiness ${Math.round(score)}` : 'No readiness' })),
      h('div', { class: 'comps tight' }, names.map(k => compRow(stockV && k === 'resting_hr' ? 'Overnight pulse' : COMPONENT_NAMES[k] || k, comps[k], weights[k])))),
    p && p.focus ? h('div', { class: 'brief-focus' }, h('strong', null, 'Focus today'), h('span', null, p.focus))
      : h('p', { class: 'foot' }, r.reason || ''),
    (p?.highlights || []).length ? h('ul', { class: 'brief-list tight' }, p.highlights.slice(0, 2).map(x => h('li', { class: `tone-${x.tone}` }, h('i', { 'aria-hidden': 'true' }), x.text))) : null);
}

function sleepVital() {
  const sl = rec().sleep || {}, nights = rec().sleep_nights || [], map = byNight(nights, 'night');
  const last = map.get(todayISO()) || null;
  const prior = dateSpan(15).slice(0, -1).map(d => map.get(d)).filter(n => n && isNum(n.onset) && isNum(n.wake));
  const usualOn = median(prior.map(n => eveningMin(n.onset))), usualUp = median(prior.map(n => dayMin(n.wake)));
  const items = dateSpan(14).map(d => { const n = map.get(d) || {}; return { key: d, label: d, v: isNum(n.sleep_s) ? n.sleep_s / 3600 : null, inner: isNum(n.restful_s) ? n.restful_s / 3600 : null, cls: 'soft' }; });
  const vsNeed = isNum(sl.sleep_s) && isNum(sl.need_s) ? sl.sleep_s - sl.need_s : null;
  return card('sleep', 'Sleep', { cls: 'c4 compact', link: 'sleep', chip: sl.status === 'duration_only' ? chip('Duration only', '', sl.reason) : isNum(sl.score) ? chip(`Score ${sl.score}`, '', sl.reason) : null },
    isNum(sl.sleep_s) ? [
      h('div', { class: 'vital-top' }, big(fmtDur(sl.sleep_s, true), isNum(vsNeed) ? `${signedDur(vsNeed)} vs need` : 'asleep'),
        isNum(sl.score) ? h('span', { class: 'status-word' }, sleepWord(sl.score)) : null),
      h('div', { class: 'mks' },
        miniKv('Bed', last && isNum(last.onset) ? fmtClock(last.onset) : '—', isNum(usualOn) ? `usual ${clockOfMin(usualOn)}` : null),
        miniKv('Up', last && isNum(last.wake) ? fmtClock(last.wake) : '—', isNum(usualUp) ? `usual ${clockOfMin(usualUp)}` : null),
        miniKv('Restful', isNum(sl.restful_s) && sl.sleep_s ? `${fmt(100 * sl.restful_s / sl.sleep_s)}%` : '—', fmtDur(sl.restful_s, true)),
        miniKv('Timing spread', isNum(sl.regularity_sd_min) ? `±${fmt(sl.regularity_sd_min)} min` : '—', 'this week')),
      barChart({ items, H: 150, fmtV: v => fmt(v, 1), unit: 'h', ref: isNum(sl.need_s) ? { v: sl.need_s / 3600, label: 'need' } : null, label: 'Sleep per night, last 14 nights' }),
    ] : pending('No sleep recorded for last night', sl.reason || 'Wear the watch to bed; the night appears after the morning sync.'));
}

function vrow(m, label, value, note, items, href, opts = {}) {
  const sp = items && items.some(i => isNum(i.v)) ? trendSpark({ items, W: 110, H: 30, band: opts.band, unit: opts.unit, fmtV: opts.fmtV, label: `${label}, recent nights` }) : h('span', { class: 'vrow-nosp' });
  return h('a', { class: 'vrow', 'data-m': m, href },
    h('span', { class: 'vrow-l' }, h('i'), h('span', null, label, note ? h('small', null, note) : null)),
    sp, h('strong', { class: `vrow-v${value ? '' : ' none'}` }, value || '—'));
}

function recoveryVital() {
  const st = rec().hrv_status || {}, nights = byNight(rec().nights, 'night'), span = dateSpan(14);
  const [word] = hrvLabel(st.status);
  const proxy = ppiSourceUnverified() && !isNum(st.last_night_rmssd_ms);
  const hrvVal = proxy ? (latestPpiProxy() ? `${fmt(latestPpiProxy().value_ms, 1)} ms` : null) : isNum(st.last_night_rmssd_ms) ? `${fmt(st.last_night_rmssd_ms)} ms` : null;
  const hrvNote = proxy ? 'unvalidated proxy' : `${word}${isNum(st.baseline_low_ms) ? ` · usual ${fmt(st.baseline_low_ms)}–${fmt(st.baseline_high_ms)}` : ''}${st.comparable_series?.metric === 'ppi_rmssd_estimate' ? ' · estimate' : ''}`;
  const stockMode = stock().mode === 'stock_firmware_estimates';
  const pulseRows = stockPulse().points || D().monitor_observations?.nightly_pulse || [];
  const pulseMap = byNight(pulseRows, 'night'), pl = stockPulse().latest || pulseRows.at(-1);
  const sp = (D().sleep_pulse || []).find(n => n.night === todayISO());
  const spMap = byNight(D().sleep_pulse || [], 'night');
  const strain = stockStrain(), strainFresh = stockMode && stockStrainFresh(strain);
  const ds = daytimeStressNow(), dsDays = new Map((ds.daily || []).map(x => [x.date, x]));
  const ox = new Map((D().oxygen?.daily || []).map(r => [r.date, r])), oxToday = ox.get(todayISO());
  return card('hrv', 'Recovery signals', { cls: 'c4 compact', link: null },
    h('div', { class: 'vrows' },
      vrow('hrv', 'HRV last night', hrvVal, hrvNote, span.map(d => ({ key: d, label: d, v: nights.get(d)?.rmssd_ms ?? null })), '#d/hrv',
        { band: isNum(st.baseline_low_ms) ? [st.baseline_low_ms, st.baseline_high_ms] : null, unit: 'ms' }),
      vrow('rhr', 'Overnight pulse', pl && isNum(pl.pulse) ? `${fmt(pl.pulse, 1)} bpm` : null, stockMode ? 'stock estimate' : 'spot pulse', span.map(d => ({ key: d, label: d, v: pulseMap.get(d)?.pulse ?? null })), '#d/rhr', { unit: 'bpm' }),
      vrow('heart', 'Pulse during sleep', sp && isNum(sp.pulse) ? `${fmt(sp.pulse, 1)} bpm` : null, sp ? `${sp.samples} samples` : 'waiting for sleep pulse', span.map(d => ({ key: d, label: d, v: spMap.get(d)?.pulse ?? null })), '#sleep', { unit: 'bpm' }),
      vrow('breath', 'SpO₂ overnight', oxToday && isNum(oxToday.mean) ? `${fmt(oxToday.mean, 1)}%` : null, oxToday ? `low ${fmt(oxToday.min)}% · ${oxToday.count} readings` : 'no readings today', span.map(d => ({ key: d, label: d, v: ox.get(d)?.mean ?? null })), '#d/oxygen', { unit: '%', fmtV: v => fmt(v, 1) }),
      stockMode ? vrow('stress', 'Overnight strain', strainFresh ? `${fmt(strain.score)} / 100` : null, 'estimate, not mental stress', null, '#d/stress') : null,
      vrow('stress', 'Daytime stress', isNum(ds.score ?? ds.today?.score) ? `${fmt(ds.score ?? ds.today.score)} / 100` : null, isNum(ds.score) ? `estimate · ${fmtClock(ds.measured_at)}` : daytimeStressReason(ds), span.map(d => ({ key: d, label: d, v: dsDays.get(d)?.score ?? null })), '#d/stress', { unit: '/100' })));
}

function activityVital() {
  const a = D().current_activity || {}, f = D().fitness || {}, it = f.intensity || {};
  const usual = D().insights?.metrics?.steps?.baseline_median;
  const hourly = hourlySteps(todayObs());
  const est = D().insights?.steps_today_estimate;
  const burn = isNum(a.active_kcal) && isNum(a.resting_kcal) ? a.active_kcal + a.resting_kcal : null;
  return card('steps', 'Activity today', { cls: 'c4 compact', link: 'steps' },
    isNum(a.steps) ? [
      h('div', { class: 'vital-top' }, big(fmt(a.steps), 'steps'),
        isNum(usual) ? h('span', { class: 'foot' }, `${fmt(100 * a.steps / usual)}% of your usual ${fmt(usual)}`) : null),
      isNum(usual) ? bar(a.steps, usual, 'Steps against your usual day') : null,
      h('div', { class: 'mks' },
        miniKv('Distance', isNum(a.distance_meters) ? `${fmt(a.distance_meters / 1000, 1)} km` : '—'),
        miniKv('Active', isNum(a.active_seconds) ? fmtDur(a.active_seconds, true) : '—'),
        miniKv('Burn', isNum(burn) ? `${fmt(burn)} kcal` : '—', isNum(a.active_kcal) ? `${fmt(a.active_kcal)} active` : null),
        miniKv('Intensity', isNum(it.this_week) ? `${fmt(it.this_week)} / ${fmt(it.goal)}` : '—', 'min this week')),
      hourly.some(p => p.v > 0) ? dayChart({ points: hourly, bars: true, H: 130, unit: 'steps', label: 'Steps per hour today' }) : null,
      est?.status === 'available' ? h('p', { class: 'foot' }, `Typical full day from here: about ${fmt(est.estimate)} steps (±${fmt(est.typical_error_steps)}).`) : null,
    ] : pending('No activity reported today yet', 'Steps appear after the next upload from the phone.'));
}

/* Recent 7-day median against the earlier 28-day median and its middle 80%.
   Server insights supply this for most metrics; SpO2 and stress are computed
   the same way here from the daily series. */
function baselineTiles() {
  const d = D(), ins = d.insights?.metrics || {}, today = todayISO(), yesterday = addDays(today, -1);
  const dm = dailyMap(), nights = byNight(rec().nights, 'night'), sn = byNight(rec().sleep_nights, 'night');
  const pulse = byNight(stockPulse().points || d.monitor_observations?.nightly_pulse || [], 'night');
  const weight = new Map((d.weight?.entries || []).map(e => [e.date, e.kg]));
  const ox = new Map((d.oxygen?.daily || []).map(r => [r.date, r.mean]));
  const ds = new Map((d.daytime_stress?.daily || []).map(r => [r.date, r.score]));
  const DEFS = [
    { m: 'steps', label: 'Steps', href: '#d/steps', ins: 'steps', good: 1, end: yesterday, get: x => dm.get(x)?.steps },
    { m: 'sleep', label: 'Sleep', href: '#sleep', ins: 'sleep_minutes', good: 1, end: today, get: x => isNum(sn.get(x)?.sleep_s) ? sn.get(x).sleep_s / 60 : null, f: v => fmtDur(v * 60, true), fd: v => fmtDur(Math.abs(v) * 60, true) },
    { m: 'hrv', label: 'HRV', href: '#d/hrv', ins: 'rmssd_ms', good: 1, end: today, unit: 'ms', get: x => nights.get(x)?.rmssd_ms, est: true },
    { m: 'rhr', label: 'Overnight pulse', href: '#d/rhr', ins: 'overnight_pulse', good: -1, end: today, unit: 'bpm', get: x => pulse.get(x)?.pulse, f: v => fmt(v, 1), est: true },
    { m: 'train', label: 'Active minutes', href: '#d/steps', ins: 'active_minutes', good: 1, end: yesterday, unit: 'min', get: x => dm.get(x)?.active_minutes },
    { m: 'weight', label: 'Weight', href: '#body', ins: 'weight_kg', good: 0, end: today, unit: 'kg', get: x => weight.get(x), f: v => fmt(v, 1) },
    { m: 'breath', label: 'SpO₂', href: '#d/oxygen', good: 1, end: today, unit: '%', get: x => ox.get(x), f: v => fmt(v, 1), est: true },
    { m: 'stress', label: 'Daytime stress', href: '#d/stress', good: -1, end: today, unit: '/100', get: x => ds.get(x), est: true },
  ];
  return DEFS.map(def => {
    const f = def.f || (v => fmt(v)), fd = def.fd || (v => (def.f || (x => fmt(x)))(Math.abs(v)));
    const days = dateSpan(28, def.end), items = days.map(x => ({ key: x, label: x, v: def.get(x) ?? null }));
    let recent, base, band, nRecent, nBase;
    const srv = def.ins && ins[def.ins];
    if (srv && (isNum(srv.recent_median) || isNum(srv.baseline_median))) {
      recent = srv.recent_median; base = srv.baseline_median; band = srv.baseline_middle_80_pct; nRecent = srv.recent_days; nBase = srv.baseline_days;
    } else {
      const all = dateSpan(35, def.end).map(x => def.get(x));
      const rv = all.slice(-7).filter(isNum), bv = all.slice(0, -7).filter(isNum).sort((a, b) => a - b);
      recent = rv.length >= 3 ? median(rv) : null; nRecent = rv.length; nBase = bv.length;
      base = bv.length >= 7 ? median(bv) : null; band = bv.length >= 7 ? [quantile(bv, .1), quantile(bv, .9)] : null;
    }
    const diff = isNum(recent) && isNum(base) ? recent - base : null;
    const outside = isNum(recent) && band && isNum(band[0]) && isNum(band[1]) && (recent < band[0] || recent > band[1]);
    const dir = isNum(diff) && Math.abs(diff) > 1e-9 ? Math.sign(diff) : 0;
    const tone = !isNum(diff) ? 'none' : !outside || !def.good ? 'flat' : dir === def.good ? 'up' : 'down';
    const arrow = dir > 0 ? '↑' : dir < 0 ? '↓' : '→';
    return h('a', { class: `card compact tile c3 tone-${tone}`, 'data-m': def.m, href: def.href, title: `${def.label}: median of the last 7 recorded days (${nRecent ?? 0}) against the earlier 28 days (${nBase ?? 0}). The band is the middle 80% of those earlier days.` },
      h('div', { class: 'tile-head' }, h('i'), h('span', null, def.label), def.est ? h('span', { class: 'tile-est' }, 'est.') : null),
      h('div', { class: 'tile-row' },
        h('strong', { class: `tile-v${isNum(recent) ? '' : ' none'}` }, isNum(recent) ? f(recent) : '—', isNum(recent) && def.unit ? h('small', null, ` ${def.unit}`) : null),
        h('span', { class: 'tile-d' }, isNum(diff) ? `${arrow} ${fd(diff)}${def.unit && def.unit !== '/100' ? ' ' + def.unit : ''}` : 'baseline building')),
      trendSpark({ items, band, W: 260, H: 42, fmtV: f, unit: def.unit || '', label: `${def.label}, last 28 days` }) || h('div', { class: 'tile-nodata' }, 'No readings in the last 4 weeks'),
      h('div', { class: 'tile-foot' }, isNum(diff) ? (outside ? 'outside your usual range' : 'within your usual range') : `${nBase ?? 0} earlier days so far`, ' · 7-day median'));
  });
}

function trainingMini() {
  const t = D().training || {}, lt = t.latest || {}, it = D().fitness?.intensity || {}, zones = t.zones || [];
  const zmax = Math.max(1, ...zones.map(z => z.minutes || 0));
  const week = sessions(liveWorkouts().filter(w => w.start >= nowSec() - 7 * 86400));
  const confirmed = D().training_ledger?.confirmed_consecutive_days ?? lt.baseline_days ?? 0;
  return card('train', 'Training', { cls: 'c3 compact', link: 'train', chip: lt.status !== 'ready' ? chip('Building baseline') : null },
    h('div', { class: 'mks' },
      miniKv('Intensity', isNum(it.this_week) ? `${fmt(it.this_week)} min` : '—', isNum(it.goal) ? `of ${fmt(it.goal)} this week` : null),
      miniKv('Sessions', String(week.length), 'last 7 days'),
      miniKv('Time', fmtDur(week.reduce((a, w) => a + (w.seconds || 0), 0), true), 'last 7 days'),
      miniKv('7-day load', isNum(lt.load7) ? fmt(lt.load7) : '—', lt.status === 'ready' ? `form ${signed(lt.form)}` : `${confirmed} / 42 days`)),
    isNum(it.goal) ? bar(it.this_week, it.goal, 'Weekly intensity minutes') : null,
    zones.some(z => z.minutes > 0) ? h('div', { class: 'zones tight above' }, h('p', { class: 'foot' }, 'Time in heart-rate zones · recorded workouts'),
      zones.map(z => h('div', { class: 'zone' }, h('span', null, z.label), h('span', { class: 'bar' }, h('span', { style: { width: `${100 * (z.minutes || 0) / zmax}%` } })), h('span', { class: 'min' }, `${fmt(z.minutes)} min`)))) : null);
}

function latestActivityMini() {
  const rows = sessions(liveWorkouts().filter(w => w.start <= nowSec())).reverse();
  const latest = rows[0];
  if (!latest) return card('workouts', 'Latest activity', { cls: 'c3 compact', link: 'workouts' }, pending('No workouts yet', 'Record one with the watch or phone.'));
  const hrPts = (D().observations || []).filter(o => isNum(o.hr) && o.ts >= latest.start && o.ts <= latest.start + (latest.seconds || 0))
    .map(o => ({ key: o.ts, label: o.ts, ts: o.ts, v: o.hr }));
  const others = rows.slice(1, 4);
  return card('workouts', 'Latest activity', { cls: 'c3 compact' },
    h('div', { class: 'vital-top' }, h('h3', { class: 'act-name' }, cap(latest.kind || 'Workout')),
      h('button', { type: 'button', class: 'btn small above', onclick: () => openActivity(latest) }, 'Open')),
    h('p', { class: 'foot' }, `${fmtDateTime(latest.start)} · ${activitySource(latest)}`),
    h('div', { class: 'mks' },
      miniKv('Duration', activityDuration(latest.active_seconds ?? latest.seconds)),
      miniKv('Distance', isNum(latest.distance_m) ? `${fmt(latest.distance_m / 1000, 2)} km` : '—'),
      miniKv('Avg HR', hrPts.length ? `${fmt(avg(hrPts.map(p => p.v)))} bpm` : '—', hrPts.length ? `max ${fmt(Math.max(...hrPts.map(p => p.v)))}` : null),
      miniKv('Effort', isNum(latest.rpe) ? `${fmt(latest.rpe)}/10` : '—', isNum(latest.hr_load) ? `HR load ${fmt(latest.hr_load)}` : null)),
    hrPts.length > 5 ? lineChart({ items: hrPts, H: 80, unit: 'bpm', dots: false, label: 'Heart rate during the activity' }) : null,
    others.length ? h('ul', { class: 'mini-list above' }, others.map(w => h('li', null,
      h('button', { type: 'button', class: 'linkish', onclick: () => openActivity(w) }, cap(w.kind || 'Workout')),
      h('span', null, `${fmtDay(isoInTz(new Date(w.start * 1000)), { weekday: 'short', day: 'numeric' })} · ${activityDuration(w.seconds)}`)))) : null,
    h('a', { class: 'foot-link above', href: '#d/workouts' }, 'All workouts →'));
}

/* ---------- year heatmap ---------- */
const HEAT = {
  steps: { label: 'Steps', m: 'steps', get: r => r.steps, f: v => fmt(v), unit: 'steps' },
  active: { label: 'Active min', m: 'train', get: r => r.active_minutes, f: v => fmt(v), unit: 'min' },
  rhr: { label: 'Resting HR', m: 'heart', get: r => r.resting_hr, f: v => fmt(v), unit: 'bpm' },
};
function heatmapRaw({ items, metric, W = 520, onPick }) {
  const def = HEAT[metric] || HEAT.steps;
  const top = 16, gap = 2, left = 0;
  const first = parseISO(items[0].date), lead = (first.getDay() + 6) % 7;
  const cols = Math.ceil((items.length + lead) / 7);
  const cell = Math.max(4, Math.min(16, Math.floor((W - left) / cols) - gap));
  const H = top + 7 * (cell + gap);
  const vals = items.map(def.get).filter(isNum).sort((a, b) => a - b);
  const qs = [.2, .4, .6, .8].map(q => quantile(vals, q));
  const level = v => !isNum(v) ? 0 : 1 + qs.filter(q => v > q).length;
  const kids = [];
  let lastMonth = -1;
  items.forEach((r, i) => {
    const k = i + lead, col = Math.floor(k / 7), row = k % 7;
    const x = left + col * (cell + gap), y = top + row * (cell + gap);
    const dt = parseISO(r.date);
    if (row === 0 || i === 0) {
      if (dt.getMonth() !== lastMonth && dt.getDate() <= 7) { kids.push(s('text', { x, y: 10 }, dt.toLocaleDateString(LOCALE, { month: 'short' }))); }
      lastMonth = dt.getMonth();
    }
    const v = def.get(r), lv = level(v);
    const rect = s('rect', { class: `hm l${lv}`, x, y, width: cell, height: cell, rx: Math.min(3, cell / 4) },
      s('title', null, `${fmtDay(r.date)}: ${isNum(v) ? `${def.f(v)} ${def.unit}` : 'no data'}`));
    if (onPick && isNum(v)) { rect.style.cursor = 'pointer'; rect.addEventListener('click', () => onPick(r.date)); }
    kids.push(rect);
  });
  return s('svg', { class: 'chart heatmap', viewBox: `0 0 ${Math.max(W, cols * (cell + gap))} ${H}`, role: 'img', 'aria-label': `${def.label} per day over the last year` }, kids);
}
const heatmap = responsive(heatmapRaw);
function yearCard() {
  const metric = HEAT[store.get('ph-heat')] ? store.get('ph-heat') : 'steps', def = HEAT[metric];
  const items = YEAR.items;
  const vals = (items || []).map(r => ({ d: r.date, v: def.get(r) })).filter(x => isNum(x.v));
  const best = vals.length ? vals.reduce((m, x) => (metric === 'rhr' ? x.v < m.v : x.v > m.v) ? x : m) : null;
  const seg = h('div', { class: 'seg small above', role: 'group', 'aria-label': 'Heatmap metric' }, Object.entries(HEAT).map(([k, x]) =>
    h('button', { type: 'button', 'aria-pressed': String(k === metric), onclick: () => { store.set('ph-heat', k); render(); } }, x.label)));
  return card(def.m, 'Your year', { cls: 'c6 compact year-card', chip: seg },
    items && items.length ? [
      heatmap({ items, metric, W: 620, onPick: day => { S.heartDay = day; location.hash = '#heart'; } }),
      h('div', { class: 'mks' },
        miniKv('Days recorded', `${vals.length}`, `of ${items.length}`),
        miniKv('Average', vals.length ? def.f(avg(vals.map(x => x.v))) : '—', def.unit),
        miniKv(metric === 'rhr' ? 'Lowest' : 'Best day', best ? def.f(best.v) : '—', best ? fmtDayShort(best.d) : null)),
      h('p', { class: 'foot' }, 'Darker is higher, relative to your own year. Click a day to open it on the Heart page.'),
    ] : YEAR.error ? pending('Year view unavailable', YEAR.error) : h('p', { class: 'loading' }, 'Loading the year…'));
}

function insightsStrip() {
  const r = D().insights, c = D().collection_health || {};
  if (!r) return null;
  const cov = r.coverage_last_7_days || {}, goal = r.weekly_intensity_goal, links = (r.associations || []).filter(a => a.status === 'exploratory_pattern');
  const facts = [
    ['steps', 'Minute coverage', `${fmt(cov.minute_coverage_pct)}%`, 'last 7 days'],
    ['sleep', 'Nights recorded', `${cov.recorded_sleep_nights ?? '—'} / 7`, 'last 7 days'],
    ['train', 'Confirmed training days', `${cov.confirmed_load_days ?? '—'} / 7`, 'needed for load'],
    goal ? ['train', 'Intensity to go', `${fmt(goal.remaining_to_record)} min`, goal.remaining_to_record > 0 ? `${fmt(goal.even_split_minutes)} min/day to Sunday` : 'weekly goal met'] : null,
    ['ready', 'Patterns found', String(links.length), links.length ? links.slice(0, 1).map(l => `${r.metrics[l.predictor]?.label} ↔ ${String(r.metrics[l.outcome]?.label || '').toLowerCase()}`)[0] : 'none passed the checks'],
    ['device', 'Sources', String((c.sources || []).length), 'uploading'],
  ].filter(Boolean);
  return h('section', { class: 'facts c12', 'aria-label': 'Patterns and coverage' },
    facts.map(([m, l, v, n]) => kpi(m, l, v, n)),
    h('a', { class: 'btn small facts-more', href: '#d/patterns' }, 'Patterns and planning →'));
}

/* ================================================================== *
 * Focus-page charts
 * ================================================================== */
/* One row per night on an evening-to-noon axis: asleep, restful and gaps. */
function sleepNightsRaw({ nights, W = 640, need }) {
  const rows = nights.filter(n => isNum(n.onset) && isNum(n.wake));
  const rowH = rows.length > 16 ? 12 : 20, top = 6, bottom = 22, left = 58, right = 8, pw = W - left - right;
  const H = top + bottom + rows.length * rowH;
  const SPAN = 16 * 3600;
  const kids = [];
  const base = n => isoMidnight(n.night) - 4 * 3600;
  const X = (n, ts) => left + clamp((ts - base(n)) / SPAN, 0, 1) * pw;
  for (let hr = 0; hr <= 16; hr += 2) {
    const x = left + hr / 16 * pw;
    kids.push(s('line', { class: `grid${hr === 4 ? ' zero' : ''}`, x1: x, x2: x, y1: top, y2: H - bottom }));
    kids.push(s('text', { x, y: H - 6, 'text-anchor': 'middle' }, `${String((20 + hr) % 24).padStart(2, '0')}:00`));
  }
  const on = median(rows.map(n => n.onset - base(n))), off = median(rows.map(n => n.wake - base(n)));
  rows.forEach((n, i) => {
    const y = top + i * rowH, bh = rowH - 5;
    const ivs = (n.sleep_intervals || []).length ? n.sleep_intervals : [[n.onset, n.wake]];
    ivs.forEach(([a, b]) => kids.push(s('rect', { class: 'rib-sleep', x: X(n, a), y: y + 2, width: Math.max(1.5, X(n, b) - X(n, a)), height: bh, rx: bh / 2.5 },
      s('title', null, `${fmtDay(n.night)}: ${fmtClock(n.onset)}–${fmtClock(n.wake)} · ${fmtDur(n.sleep_s, true)} asleep · ${fmtDur(n.restful_s, true)} restful`))));
    (n.restful_intervals || []).forEach(([a, b]) => kids.push(s('rect', { class: 'rib-restful', x: X(n, a), y: y + 4, width: Math.max(1, X(n, b) - X(n, a)), height: bh - 4, rx: 2 })));
    (n.recorded_gaps || []).forEach(([a, b]) => kids.push(s('rect', { class: 'rib-gap', x: X(n, a), y: y + 2, width: Math.max(1, X(n, b) - X(n, a)), height: bh })));
    kids.push(s('text', { x: left - 6, y: y + rowH / 2 + 3.5, 'text-anchor': 'end' }, fmtDay(n.night, { weekday: 'short', day: 'numeric' })));
    if (isNum(need) && isNum(n.sleep_s) && rowH >= 16) kids.push(s('text', { class: n.sleep_s >= need ? 'lbl-strong' : null, x: Math.min(X(n, n.wake) + 6, W - right - 36), y: y + rowH / 2 + 3.5 }, fmtDur(n.sleep_s, true)));
  });
  [[on, 'usual bedtime'], [off, 'usual wake']].forEach(([v, t]) => {
    if (!isNum(v)) return;
    const x = left + clamp(v / SPAN, 0, 1) * pw;
    kids.push(s('line', { class: 'ref', x1: x, x2: x, y1: top, y2: H - bottom }, s('title', null, `${t}: ${clockOfMin((v / 60 + 20 * 60) % 1440)}`)));
  });
  return s('svg', { class: 'chart nights', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Sleep timing, restful periods and gaps per night' }, kids);
}
const sleepNightsChart = responsive(sleepNightsRaw);

function scatterRaw({ points, W = 420, H = 220, xf = v => fmt(v, 1), yf = v => fmt(v), xLabel, yLabel, label }) {
  const top = 10, bottom = 34, left = 40, right = 10, pw = W - left - right, ph = H - top - bottom;
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const pad = (a, b) => { const d = (b - a) || 1; return [a - d * .1, b + d * .1]; };
  const [x0, x1] = pad(Math.min(...xs), Math.max(...xs)), [y0, y1] = pad(Math.min(...ys), Math.max(...ys));
  const X = v => left + (v - x0) / (x1 - x0) * pw, Y = v => top + ph - (v - y0) / (y1 - y0) * ph;
  const kids = [];
  [y0, (y0 + y1) / 2, y1].forEach((v, i) => { kids.push(s('line', { class: `grid${i ? '' : ' zero'}`, x1: left, x2: W - right, y1: Y(v), y2: Y(v) })); kids.push(s('text', { x: left - 6, y: Y(v) + 3.5, 'text-anchor': 'end' }, yf(v))); });
  [x0, (x0 + x1) / 2, x1].forEach(v => kids.push(s('text', { x: X(v), y: H - 18, 'text-anchor': 'middle' }, xf(v))));
  if (xLabel) kids.push(s('text', { x: left + pw / 2, y: H - 3, 'text-anchor': 'middle' }, xLabel));
  if (yLabel) kids.push(s('text', { x: left, y: top - 1 }, ''));
  points.forEach(p => kids.push(s('circle', { class: `dot${p.last ? ' last' : ''}`, cx: X(p.x), cy: Y(p.y), r: p.last ? 5 : 3.6, style: p.last ? null : 'opacity:.7' }, s('title', null, p.title))));
  return s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label || 'Scatter plot' }, kids);
}
const scatterChart = responsive(scatterRaw);

/* ================================================================== *
 * Focus pages
 * ================================================================== */
function sleepFocus() {
  const sl = rec().sleep || {}, nights = rec().sleep_nights || [], map = byNight(nights, 'night');
  const span = dateSpan(S.range), inRange = span.map(d => map.get(d)).filter(Boolean);
  const timed = inRange.filter(n => isNum(n.onset) && isNum(n.wake)).slice(-30);
  const avgS = avg(inRange.map(n => n.sleep_s));
  const restShare = avg(inRange.map(n => isNum(n.restful_s) && n.sleep_s ? n.restful_s / n.sleep_s : null));
  const det = DETAIL.sleep.render();
  return focusPage('Sleep', rangeSwitch(),
    kpis(kpi('sleep', 'Last night', isNum(sl.sleep_s) ? fmtDur(sl.sleep_s, true) : '—', isNum(sl.score) ? `score ${sl.score} · ${sleepWord(sl.score).toLowerCase()}` : null),
      kpi('sleep', `Average · ${RANGES.find(r => r.days === S.range)?.label || ''}`, isNum(avgS) ? fmtDur(avgS, true) : '—', isNum(avgS) && isNum(sl.need_s) ? `${signedDur(avgS - sl.need_s)} vs need` : null),
      kpi('sleep', 'Usual bedtime', clockOfMin(median(timed.map(n => eveningMin(n.onset)))), `wake ${clockOfMin(median(timed.map(n => dayMin(n.wake))))}`),
      kpi('sleep', 'Timing spread', isNum(sl.regularity_sd_min) ? `±${fmt(sl.regularity_sd_min)} min` : '—', 'this week'),
      kpi('sleep', 'Restful share', isNum(restShare) ? `${fmt(restShare * 100)}%` : '—', 'watch estimate, not stages'),
      kpi('sleep', 'Nights recorded', `${inRange.length} / ${span.length}`, null)),
    [card('sleep', 'Night by night', { cls: 'wide', chip: chip(`${timed.length} nights`) },
      timed.length ? [sleepNightsChart({ nights: timed, W: 900, need: sl.need_s }),
        legend([['rib-sleep', 'Asleep'], ['rib-restful', 'Restful'], ['rib-gap', 'Not recorded'], ['dash', 'Usual bed and wake time']])]
        : pending('No bed and wake times yet', 'Times come from exported sleep sessions.')),
    half(det[1]), half(sleepPulseCard())],
    [briefPanel('sleep', { regenerate: true }), det[0]]);
}

function recoveryFocus() {
  const r = readinessNow(), st = rec().hrv_status || {}, ds = daytimeStressNow();
  const sn = byNight(rec().sleep_nights, 'night');
  const pts = (rec().nights || []).filter(n => isNum(n.rmssd_ms) && isNum(sn.get(n.night)?.sleep_s))
    .map((n, i, a) => ({ x: sn.get(n.night).sleep_s / 3600, y: n.rmssd_ms, last: i === a.length - 1, title: `${fmtDay(n.night)}: ${fmtDur(sn.get(n.night).sleep_s, true)} asleep, HRV ${fmt(n.rmssd_ms, 1)} ms` }));
  const ox = (D().oxygen?.daily || []).find(x => x.date === todayISO());
  const ready = DETAIL.ready.render();
  const hrv = DETAIL.hrv.render();
  return focusPage('Recovery', rangeSwitch(),
    kpis(kpi('ready', 'Readiness', isNum(r.score) ? fmt(r.score) : '—', isNum(r.score) ? readinessWord(r.score) : r.reason, '#d/ready'),
      kpi('hrv', 'HRV status', hrvLabel(st.status)[0], isNum(st.weekly_rmssd_ms) ? `${fmt(st.weekly_rmssd_ms, 1)} ms 7-night avg` : null, '#d/hrv'),
      kpi('hrv', 'HRV last night', isNum(st.last_night_rmssd_ms) ? `${fmt(st.last_night_rmssd_ms)} ms` : '—', isNum(st.baseline_low_ms) ? `usual ${fmt(st.baseline_low_ms)}–${fmt(st.baseline_high_ms)}` : null, '#d/hrv'),
      kpi('rhr', 'Overnight pulse', isNum(stockPulse().latest?.pulse) ? `${fmt(stockPulse().latest.pulse, 1)} bpm` : '—', 'estimate', '#d/rhr'),
      kpi('breath', 'SpO₂ overnight', ox ? `${fmt(ox.mean, 1)}%` : '—', ox ? `low ${fmt(ox.min)}%` : null, '#d/oxygen'),
      kpi('stress', 'Stress today', isNum(ds.today?.score) ? `${fmt(ds.today.score)} / 100` : '—', 'quiet-pulse estimate', '#d/stress')),
    [half(ready[0]),
      pts.length >= 4 ? card('hrv', 'HRV against sleep duration', { chip: chip('Exploratory') },
        scatterChart({ points: pts, W: 420, H: 220, xf: v => `${fmt(v, 1)} h`, xLabel: 'Hours asleep', label: 'Nightly HRV against hours asleep' }),
        h('p', { class: 'foot' }, `${pts.length} nights. The ringed point is the latest. A pattern here is a correlation in your own data, not a cause.`)) : null,
      hrv[1], half(ready[1]), half(DETAIL.rhr.render()[0])],
    [briefPanel('recovery'), oxygenCard(), CARDS.stress()]);
}

function trainingFocus() {
  const t = D().training || {}, lt = t.latest || {}, it = D().fitness?.intensity || {}, f = D().fitness || {};
  const week = sessions(liveWorkouts().filter(w => w.start >= nowSec() - 7 * 86400));
  const det = DETAIL.train.render().filter(n => n && n.tagName !== 'P');
  return focusPage('Training', [rangeSwitch(), h('a', { class: 'btn primary', href: '/planner.html' }, 'Workout planner')],
    kpis(kpi('train', 'Intensity this week', isNum(it.this_week) ? `${fmt(it.this_week)} min` : '—', isNum(it.goal) ? `goal ${fmt(it.goal)}` : null),
      kpi('train', 'Sessions', String(week.length), 'last 7 days', '#d/workouts'),
      kpi('train', 'Active time', fmtDur(week.reduce((a, w) => a + (w.seconds || 0), 0), true), 'last 7 days'),
      kpi('train', '7-day load', isNum(lt.load7) ? fmt(lt.load7) : '—', lt.status === 'ready' ? `form ${signed(lt.form)}` : 'baseline building'),
      kpi('ready', 'VO₂max', isNum(f.vo2max?.value) ? fmt(f.vo2max.value, 1) : '—', 'profile estimate')),
    [...det.map(half), CARDS.intensity(), wide(CARDS.workouts(8))],
    [briefPanel('training'), trainingReviewCard(), CARDS.calendar(), CARDS.fitness()]);
}

function heartFocus() {
  const today = serverToday(), day = S.heartDay && S.heartDay <= today ? S.heartDay : today;
  loadIntraday(day); loadYear();
  const st = INTRA[day] || {}, data = st.data;
  const pts = data ? data.points.map(p => ({ ts: p.ts, hr: p.hr, steps: p.steps })) : [];
  const hrs = pts.map(p => p.hr).filter(isNum);
  const yrow = (YEAR.items || []).find(r => r.date === day) || dailyMap().get(day) || {};
  const go = n => { S.heartDay = addDays(day, n) > today ? today : addDays(day, n); render(); };
  const picker = h('div', { class: 'daypick' },
    h('button', { type: 'button', class: 'btn small', 'aria-label': 'Previous day', onclick: () => go(-1) }, '‹'),
    h('input', { type: 'date', value: day, max: today, 'aria-label': 'Day', onchange: e => { if (e.target.value) { S.heartDay = e.target.value; render(); } } }),
    h('button', { type: 'button', class: 'btn small', 'aria-label': 'Next day', disabled: day >= today, onclick: () => go(1) }, '›'),
    day !== today ? h('button', { type: 'button', class: 'btn small', onclick: () => { S.heartDay = null; render(); } }, 'Today') : null);
  const t0 = isoMidnight(day), t1 = isoMidnight(addDays(day, 1));
  const sleep = data ? (data.sleep || []).map(x => ({ intervals: [[x.start, x.start + x.seconds]], nap: x.kind === 'nap', label: `${x.kind === 'nap' ? 'Nap' : 'Sleep'} ${fmtDur(x.seconds, true)}`, title: `${cap(x.kind || 'sleep')} ${fmtClock(x.start)}–${fmtClock(x.start + x.seconds)}` })) : [];
  const hrMax = D().profile?.hr_max;
  const bins = [];
  if (hrs.length) { const lo = Math.floor(Math.min(...hrs) / 10) * 10, hi = Math.ceil((Math.max(...hrs) + 1) / 10) * 10; for (let b = lo; b < hi; b += 10) bins.push({ key: b, label: `${b}`, v: hrs.filter(v => v >= b && v < b + 10).length, note: `${b}–${b + 9} bpm` }); }
  const yItems = (YEAR.items || []).slice(-S.range).map(r => ({ key: r.date, label: r.date, v: r.resting_hr }));
  const dItems = bucket(dateSpan(S.range, today), dd => { const r = (YEAR.items || []).find(x => x.date === dd) || dailyMap().get(dd); return r && isNum(r.hr_avg) ? { v: r.hr_avg, lo: r.hr_min, hi: r.hr_max } : { v: null }; }, 'avg');
  return focusPage('Heart', [picker, rangeSwitch()],
    kpis(kpi('heart', 'Average', hrs.length ? `${fmt(avg(hrs))} bpm` : '—', fmtDay(day)),
      kpi('heart', 'Lowest', hrs.length ? `${fmt(Math.min(...hrs))} bpm` : '—', null),
      kpi('heart', 'Highest', hrs.length ? `${fmt(Math.max(...hrs))} bpm` : '—', isNum(hrMax) && hrs.length ? `${fmt(100 * Math.max(...hrs) / hrMax)}% of max` : null),
      kpi('heart', 'Resting (00–06)', isNum(yrow.resting_hr) ? `${fmt(yrow.resting_hr)} bpm` : '—', '10th percentile'),
      kpi('heart', 'Minutes with HR', fmt(hrs.length), `of ${fmt(pts.length)} stored`),
      kpi('steps', 'Steps', isNum(yrow.steps) ? fmt(yrow.steps) : '—', isNum(yrow.active_minutes) ? `${fmt(yrow.active_minutes)} active min` : null)),
    [card('heart', `Minute by minute · ${fmtDay(day)}`, { cls: 'wide' },
      data ? [dayRibbon({ W: 1000, t0, t1, obs: pts, sleep, workouts: liveWorkouts(), stress: D().daytime_stress?.points || [], spo2: D().oxygen?.readings || [], hrH: 200, label: `Heart rate and activity on ${fmtDay(day)}` }), ribbonLegend()]
        : st.error ? pending('Could not load this day', st.error) : h('p', { class: 'loading' }, 'Loading the day…')),
      card('heart', 'Daily range', { cls: 'wide' }, dItems.some(i => isNum(i.v)) ? [lineChart({ items: dItems, W: 900, H: 180, unit: 'bpm', label: 'Daily heart rate range and average' }), legend([['line', 'Average'], ['soft', 'Lowest to highest']])] : pending('No heart rate in this range')),
      card('heart', 'Resting heart rate', {}, yItems.some(i => isNum(i.v)) ? [lineChart({ items: yItems, H: 170, unit: 'bpm', label: 'Resting heart rate per day' }), h('p', { class: 'foot' }, '10th percentile of 00:00–06:00 minute readings, needs 20 readings. Not a validated resting heart rate.')] : YEAR.items ? pending('No overnight minute readings') : h('p', { class: 'loading' }, 'Loading…')),
      card('heart', 'Minutes per heart-rate band', {}, bins.length ? barChart({ items: bins, H: 170, unit: 'min', label: 'Minutes in each 10 bpm band' }) : pending('No heart rate this day'))],
    [CARDS.heart(), CARDS.rhr(), info('About minute heart rate', 'Minute heart rate is the watch’s optical reading as exported by the phone. Gaps are periods with no reading; they are never filled in.', 'The zone bands in the timeline use 64% and 77% of your maximum heart rate, as for intensity minutes.')]);
}

function bodyFocus() {
  const w = D().weight || {}, f = D().fitness || {};
  return focusPage('Body', rangeSwitch(),
    kpis(kpi('weight', 'Weight', isNum(w.latest?.kg) ? `${fmt(w.latest.kg, 1)} kg` : '—', w.latest?.date ? fmtDayShort(w.latest.date) : null),
      kpi('weight', 'Trend', isNum(w.latest?.trend_kg) ? `${fmt(w.latest.trend_kg, 1)} kg` : '—', '7-reading average'),
      kpi('weight', 'Last week', `${signedKg(w.change_7d_kg)} kg`, null),
      kpi('weight', 'Last 4 weeks', `${signedKg(w.change_28d_kg)} kg`, null),
      kpi('ready', 'VO₂max', isNum(f.vo2max?.value) ? fmt(f.vo2max.value, 1) : '—', 'profile estimate'),
      kpi('steps', 'Resting burn', isNum(f.energy?.bmr_kcal) ? `${fmt(f.energy.bmr_kcal)} kcal` : '—', 'per day, estimated')),
    DETAIL.weight.render(),
    [CARDS.fitness(), CARDS.energy()]);
}
