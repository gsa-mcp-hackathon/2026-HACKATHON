// The self-contained HTML widget (BUILD_PLAN D35, D36, D42).
//
// buildWidgetData() turns the analysis and map into the page's data JSON;
// buildWidgetHtml() wraps it with the CSS and the browser script. The script
// is the function widgetMain below, serialized with toString(), so it is real,
// parse-checked JavaScript in this module. It makes no network calls (the page
// CSP forbids them), never uses innerHTML, and sets all text with textContent.
import { ALL } from './analysis.mjs';

export const CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:";
export const CAVEATS = [
  'Review indicator on public data. Not a finding of fraud, waste, or abuse.',
  'Amounts are FEMA Grants Manager project figures published on OpenFEMA, not FEMA\'s official financial system of record.',
  'Dot position is not a project location: dots are placed at random inside the project\'s county (or state, for Statewide projects).',
];

const r2 = (v) => (typeof v === 'number' ? Math.round(v * 100) / 100 : null);
const r4 = (v) => (typeof v === 'number' ? Math.round(v * 10000) / 10000 : null);

function outlierRecord(p, map) {
  const pos = map && map.drawn ? map.positions.get(p.key) : null;
  return {
    x: pos ? pos[0] : null, y: pos ? pos[1] : null,
    c: p.category, pw: p.pw, a: p.applicantId ?? null, t: p.title ?? null,
    co: p.county ?? null, f: p.geo === 'COUNTY' ? (p.countyFips ?? null) : null, sw: p.geo === 'STATEWIDE', geo: p.geo ?? null,
    am: r2(p.amount), sg: r4(p.sigma), m: r4(p.multipleOfMean),
  };
}

// Page display options (D46); see DISPLAY_DEFAULTS in inputs.mjs. Defaults = the standard page.
function widgetUi(display) {
  const d = display || {};
  return {
    pauseButton: d.pauseButton !== false,
    pwCard: d.pwCard !== false,
    allCategoriesCard: d.allCategoriesCard !== false,
    legend: d.legendPosition === 'below_map' ? 'below_map' : 'below_cards',
    clickDetails: d.clickDetails === 'modal' ? 'modal' : 'none',
  };
}

// meta: { disasterNumber, states, snapshotDate, newestLastRefresh }; display: parseDisplay() result (optional)
export function buildWidgetData({ analysis, map, meta, display }) {
  const codes = analysis.categories.map((c) => c.code);
  const views = analysis.views.map((id) => {
    if (id === ALL) return { id, outliers: analysis.totals.outliers, description: 'All categories A to G' };
    const c = analysis.categories.find((x) => x.code === id);
    return { id, outliers: c.outliers, description: c.description };
  });
  const categories = {};
  for (const c of analysis.categories) {
    categories[c.code] = { description: c.description, recordCount: c.recordCount, mean: r2(c.mean), stddev: r2(c.stddev), outliers: c.outliers, projects: c.projects };
  }
  const drawn = Boolean(map && map.drawn);
  const baseline = [];
  if (drawn) {
    for (const p of analysis.mapped) {
      if (p.outlier) continue;
      const pos = map.positions.get(p.key);
      if (pos) baseline.push([pos[0], pos[1], codes.indexOf(p.category), p.geo === 'STATEWIDE' ? 1 : 0]);
    }
  }
  let highlight = null;
  const h = analysis.highlight;
  if (h) {
    const pos = drawn && h.onMap ? map.positions.get(h.key) : null;
    highlight = {
      x: pos ? pos[0] : null, y: pos ? pos[1] : null, pw: h.pw, a: h.applicantId, t: h.title, c: h.category,
      cd: h.categoryDescription, co: h.county, f: h.geo === 'COUNTY' ? (h.countyFips ?? null) : null, sw: h.geo === 'STATEWIDE', am: r2(h.amount), sg: r4(h.sigma),
      m: r4(h.multipleOfMean), flagged: h.flagged, onMap: h.onMap, note: h.note,
    };
  }
  const countyNames = drawn ? new Map(map.counties.map((c) => [c.fips, c.name])) : new Map();
  const nameOf = (fips) => analysis.mapped.find((p) => p.countyFips === fips)?.county || countyNames.get(fips) || fips;
  return {
    v: 1,
    title: { disaster: meta.disasterNumber, states: meta.states, snapshotDate: meta.snapshotDate, newestLastRefresh: meta.newestLastRefresh, threshold: analysis.sigmaThreshold },
    views,
    initialView: display && display.initialView === 'all' ? ALL : analysis.initialView,
    ui: widgetUi(display),
    codes,
    categories,
    totals: analysis.totals,
    map: drawn ? {
      w: map.width,
      h: map.height,
      counties: map.counties.map((c) => {
        const o = {};
        for (const view of analysis.views) o[view] = analysis.countyOutliers[view][c.fips] || 0;
        return { n: c.name, f: c.fips, d: c.d, s: c.shades, b: c.box || null, l: c.label || null, o };
      }),
    } : null,
    notice: drawn ? null : `The county map cannot be drawn: ${map && map.reason ? map.reason : 'no county shapes are available'}. Outliers are listed below.`,
    baseline,
    outliers: analysis.outliers.map((p) => outlierRecord(p, map)),
    highlight,
    unmappable: { count: analysis.totals.unmappable, outliers: analysis.totals.unmappableOutliers },
    notPlaced: drawn ? map.notPlaced.length : null,
    countiesNotInShapes: drawn ? map.countiesNotInShapes.map(nameOf) : [],
    // D48: the caveats, boundary source and definition/snapshot line are no longer in the page;
    // they stay in the tool's text summary and structuredContent (caveats, map.boundarySources, snapshotDate).
  };
}

// JSON that is safe inside <script type="application/json">.
export function scriptSafeJson(value) {
  return JSON.stringify(value)
    .replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
}

// Colors (D45): DHS palette only, docs/DHS_COLOR_PALETTE.md. dhs-blue #005288, dhs-blue-15 #d6e3ec,
// dhs-dark-gray #5a5b5d, dhs-dark-gray-70 #2f2f30, dhs-gray #c0c2c4, dhs-gray-60 #929395, dhs-red #c41230,
// dhs-red-70 #660919, dhs-light-blue #0078ae, dhs-light-blue-60 #005b84, dhs-green #5e9732,
// dhs-green-60 #477326; FEMA Disaster Assistance DA-dark-gold #ffbe2e (approved by the user, 2026-11-12).
// Damage categories are grouped by FEMA work type: Emergency work (A, B) gold, Permanent work (C-G) green.
const STYLE = [
  'body{margin:0;font:14px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:#2f2f30;background:#fff}',
  '#app{padding:12px;max-width:1200px;margin:0 auto}',
  'h2{font-size:14px;margin:0 0 6px}.sub{margin:0 0 10px;color:#5a5b5d}',
  '.filter{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}',
  '.view{border:2px solid #005288;background:#fff;color:#2f2f30;border-radius:4px;padding:3px 10px;cursor:pointer;font:inherit}',
  '.view.on{background:#005288;color:#fff}',
  '.view.em{border-color:#ffbe2e}.view.em.on{background:#ffbe2e;color:#2f2f30}',
  '.view.pm{border-color:#477326}.view.pm.on{background:#477326;color:#fff}',
  '.view.ot{border-color:#5a5b5d}.view.ot.on{background:#5a5b5d;color:#fff}',
  '.cards{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 10px}',
  '.card{border:1px solid #c0c2c4;border-radius:6px;padding:8px 10px;min-width:220px;flex:1 1 260px}',
  '.card.flag{border-color:#c41230}.row{display:flex;justify-content:space-between;gap:12px}.k{color:#5a5b5d}.v{text-align:right;overflow-wrap:anywhere}',
  // Dragging the map must never select or highlight text (zoom buttons, county names).
  '.map{position:relative;width:100%;border:1px solid #c0c2c4;border-radius:6px;overflow:hidden;touch-action:none;cursor:grab;background:#fff;-webkit-user-select:none;user-select:none;-webkit-tap-highlight-color:transparent}',
  '.map *{-webkit-user-select:none;user-select:none}',
  '.layer{position:absolute;left:0;top:0;width:100%;height:100%}canvas.layer,.top{pointer-events:none}',
  '.county{stroke:#ffffff;stroke-width:0.8;vector-effect:non-scaling-stroke}.county:hover{stroke:#005288;stroke-width:2}',
  '.top circle{pointer-events:all;cursor:pointer;vector-effect:non-scaling-stroke}',
  '.out{fill:#c41230;stroke:#660919;stroke-width:1.5}.out.sw{fill:none;stroke:#c41230;stroke-width:2.5}',
  '.hl{fill:none;stroke:#005288;stroke-width:3}',
  // Fading halo behind each outlier (CSS only; no script loop). Off for reduced motion and when paused.
  '.top circle.halo{pointer-events:none;fill:#c41230;transform-box:fill-box;transform-origin:center;animation:pulse 1.8s ease-out infinite}',
  '.top circle.halo.sw{fill:none;stroke:#c41230;stroke-width:2}',
  '.top circle.halo.hlh{fill:#005288;animation:pulsehi 1.4s ease-out infinite}',
  '@keyframes pulse{0%{transform:scale(1);opacity:.55}100%{transform:scale(2.6);opacity:0}}',
  '@keyframes pulsehi{0%{transform:scale(1);opacity:.6}100%{transform:scale(3.2);opacity:0}}',
  '.still .top circle.halo{animation:none;opacity:0}',
  '@media (prefers-reduced-motion: reduce){.top circle.halo{animation:none;opacity:0}}',
  '.lbl{fill:#2f2f30;font-weight:600;paint-order:stroke;stroke:#ffffff;stroke-linejoin:round;pointer-events:none}',
  '.zoom{position:absolute;right:8px;top:8px;display:flex;flex-direction:column;gap:4px}',
  '.zoom button{width:56px;padding:3px 0;border:1px solid #5a5b5d;background:#fff;color:#2f2f30;border-radius:4px;cursor:pointer;font:inherit;-webkit-user-select:none;user-select:none;-webkit-tap-highlight-color:transparent}',
  // No focus ring after a mouse click; keyboard focus keeps the ring (Section 508).
  '.zoom button:focus:not(:focus-visible){outline:none}',
  '.tip{position:absolute;max-width:320px;background:#fff;border:1px solid #5a5b5d;border-radius:4px;padding:6px 8px;font-size:12px;box-shadow:0 2px 6px rgba(0,0,0,.2);pointer-events:none}',
  '.tip .t{font-weight:600}',
  '.legend{display:flex;flex-wrap:wrap;gap:14px;margin:6px 0 10px;color:#2f2f30;font-size:12px}',
  '.sw-em,.sw-pm,.sw-none,.sw-dot,.sw-ring,.sw-base,.sw-hl{display:inline-block;width:12px;height:12px;margin-right:4px;vertical-align:-2px}',
  '.sw-em{background:rgba(255,190,46,.55)}.sw-pm{background:rgba(94,151,50,.35)}.sw-none{background:#d6e3ec}',
  '.sw-dot{background:#c41230;border:1px solid #660919;border-radius:50%;width:10px;height:10px}',
  '.sw-ring{border:2px solid #c41230;border-radius:50%;width:8px;height:8px}',
  '.sw-base{background:rgba(0,120,174,.35);border:1px solid rgba(0,91,132,.6);border-radius:50%;width:5px;height:5px;vertical-align:1px}',
  '.sw-hl{border:2px solid #005288;border-radius:50%;width:8px;height:8px}',
  '.notice{padding:10px;border:1px solid #ffbe2e;background:#faf3d1;border-radius:6px}',
  'table{border-collapse:collapse;width:100%;font-size:12px}th,td{border-bottom:1px solid #dedfe0;padding:4px 6px;text-align:left;vertical-align:top}',
  'td.n{text-align:right;white-space:nowrap}.tablebox{margin:12px 0}.caveat{font-size:12px;color:#5a5b5d;margin:4px 0}',
  // D47: the outlier table is a native <details> (keyboard and screen reader support built in), open at load.
  '.tablebox>summary{cursor:pointer;margin:0 0 6px}.tablebox>summary h2{display:inline;margin:0}',
  // Details window (D46, click_details "modal"): inside the map box, never an inner scrollbar; the map grows if needed.
  '.clickable .county{cursor:pointer}',
  '.mback{position:absolute;left:0;top:0;right:0;bottom:0;z-index:5;display:flex;align-items:center;justify-content:center;padding:8px;box-sizing:border-box;background:rgba(0,0,0,.2);cursor:default}',
  '.modal{position:relative;box-sizing:border-box;width:100%;max-width:440px;background:#fff;border:1px solid #5a5b5d;border-radius:6px;padding:12px 14px;box-shadow:0 4px 14px rgba(0,0,0,.3);font-size:13px}',
  '.modal h2{margin:0 28px 8px 0;font-size:15px;color:#005288}.modal .row{padding:2px 0;border-bottom:1px solid #dedfe0}.modal .row:last-child{border-bottom:0}',
  '.modal .mx{position:absolute;right:6px;top:6px;width:28px;height:28px;border:0;background:transparent;color:#2f2f30;font-family:inherit;font-size:20px;line-height:1;cursor:pointer;border-radius:4px}',
  '.modal .mx:hover{background:#d6e3ec}.modal button:focus:not(:focus-visible){outline:none}',
  '.modal .pager{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:8px}',
  '.modal .pager button{border:1px solid #005288;background:#fff;color:#005288;border-radius:4px;padding:2px 10px;cursor:pointer;font:inherit}',
  '.modal .pager button[disabled]{border-color:#c0c2c4;color:#929395;cursor:default}',
  '.modal.flag{border-color:#c41230}',
].join('');

export function buildWidgetHtml(data) {
  return [
    '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
    `<meta http-equiv="Content-Security-Policy" content="${CSP}">`,
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    '<title>FEMA Public Assistance cost outliers</title>',
    `<style>${STYLE}</style></head><body><div id="app"></div>`,
    `<script type="application/json" id="choropleth-data">${scriptSafeJson(data)}</script>`,
    `<script>(${widgetMain.toString()})();</script>`,
    '</body></html>',
  ].join('');
}

// ---------------------------------------------------------------------------
// Browser script. Runs inside the widget page only; uses nothing from Node.
// ---------------------------------------------------------------------------
/* eslint-disable no-var */
export function widgetMain() {
  var data = JSON.parse(document.getElementById('choropleth-data').textContent);
  var SVGNS = 'http://www.w3.org/2000/svg'; // XML namespace name, not a network address
  // D45: county fill = FEMA work type of the county's dominant category in the view.
  var GROUP = { A: 'em', B: 'em', C: 'pm', D: 'pm', E: 'pm', F: 'pm', G: 'pm' };
  var GROUP_NAME = { em: 'Emergency work', pm: 'Permanent work', ot: 'Other' };
  var FILL = { em: ['#ffbe2e', 0.55], pm: ['#5e9732', 0.35], ot: ['#929395', 0.35] };
  var BASE_FILL = '#d6e3ec';
  var R_OUT = 7;
  var R_BASE = 1.8;
  var R_HI = 11;
  var HALO_MAX = 300; // more outliers than this in a view: no halos (the highlight still pulses)
  var LABEL_PX = 12;
  var ALL_VIEW = 'ALL';
  // Button icons for the damage categories (the letter stays in the tooltip, aria-label, cards and table).
  var ICON = { A: '\uD83D\uDE9B', B: '\uD83D\uDC77', C: '\uD83D\uDEE3\uFE0F', D: '\uD83D\uDCA7', E: '\uD83C\uDFE5', F: '\u26A1', G: '\uD83C\uDF33' };
  var app = document.getElementById('app');
  var ui = data.ui || {}; // D46 display options; missing = the standard page
  var MODAL = ui.clickDetails === 'modal';
  var view = data.initialView;
  var thr = data.title.threshold;

  function h(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }
  function s(tag, attrs) {
    var e = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, String(attrs[k])); });
    return e;
  }
  function clear(e) { while (e.firstChild) e.removeChild(e.firstChild); }
  var usd0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
  var usd2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 });
  function none(v) { return v === null || v === undefined; }
  function money(v) { return none(v) ? 'n/a' : usd0.format(v); }
  function money2(v) { return none(v) ? 'n/a' : usd2.format(v); }
  function sig(v) { return none(v) ? 'n/a (no variation)' : v.toFixed(2) + ' \u03c3'; }
  function times(v) { return none(v) ? 'n/a' : v.toFixed(1) + '\u00d7 the mean'; }
  function num(v) { return none(v) ? 'n/a' : Number(v).toLocaleString('en-US'); }
  function where(o) { return o.sw ? 'Statewide' : (o.co || 'County not recorded'); }
  function groupOf(code) { return GROUP[code] || 'ot'; }
  function inView(cat) { return view === ALL_VIEW || cat === view; }
  // fips -> dominant category among the view's outliers (most outliers, then larger total amount, then letter).
  function dominantByCounty() {
    var per = {};
    data.outliers.forEach(function (o) {
      if (!o.f || !inView(o.c)) return;
      var m = per[o.f] || (per[o.f] = {});
      var e = m[o.c] || (m[o.c] = { n: 0, am: 0 });
      e.n += 1; e.am += o.am || 0;
    });
    var out = {};
    Object.keys(per).forEach(function (f) {
      var best = null;
      Object.keys(per[f]).sort().forEach(function (c) {
        var e = per[f][c];
        if (!best || e.n > best.n || (e.n === best.n && e.am > best.am)) best = { c: c, n: e.n, am: e.am };
      });
      out[f] = best.c;
    });
    return out;
  }
  function shortName(n) { return String(n).replace(/\s+(County|Parish|Borough|Census Area|Municipality)$/, ''); }

  var t = data.title;
  var name = 'DR-' + t.disaster + (t.states.length ? '-' + t.states.join('/') : '');
  document.title = name + ' cost outliers'; // document title only; no visible heading (D49)
  // Page order (D49): view buttons, map (or notice), cards, legend, table (last).
  // D46 legend_position "below_map": view buttons, map, legend, cards, table.
  var bar = h('div', 'filter');
  var buttons = {};
  data.views.forEach(function (v) {
    var all = v.id === ALL_VIEW;
    var b = h('button', 'view', (all ? 'All' : (ICON[v.id] || v.id)) + ' (' + v.outliers + ')');
    var label = all ? (v.description || 'All categories') : 'Category ' + v.id + (v.description ? ' \u2013 ' + v.description : '')
      + ' (' + GROUP_NAME[groupOf(v.id)] + ')';
    b.setAttribute('type', 'button');
    b.setAttribute('data-view', v.id);
    b.setAttribute('title', label);
    b.setAttribute('aria-label', label + ', ' + v.outliers + (v.outliers === 1 ? ' outlier' : ' outliers'));
    b.addEventListener('click', function () { setView(v.id); });
    buttons[v.id] = b;
    bar.appendChild(b);
  });
  app.appendChild(bar); // D49: category buttons above the map, always visible with it
  var cards = h('div', 'cards');

  var W = 0; var H = 0;
  var mapWrap = null; var gBase = null; var gTop = null; var canvas = null; var ctx = null; var tip = null;
  var countyEls = [];
  var circles = [];
  var labels = [];
  var z = { k: 1, x: 0, y: 0 };

  function scr() { return (mapWrap && mapWrap.clientWidth ? mapWrap.clientWidth : W) / W || 1; }
  // Pan limit: the centre of the view stays on the map. Looser than "no blank edge" so a
  // county at the edge of the state can still be centred by fitView.
  function clampPan() {
    z.x = Math.min(W / 2, Math.max(W / 2 - W * z.k, z.x));
    z.y = Math.min(H / 2, Math.max(H / 2 - H * z.k, z.y));
  }
  // Auto-fit for a view: union of the boxes of the counties holding its outliers (plus the
  // highlighted PW's county). Dots are not used: their positions are arbitrary. Statewide and
  // unplaced outliers are left out. No county -> whole state (k = 1), as before.
  var FIT_FILL = 0.7; // the fitted counties fill at most 70% of the width or height
  var FIT_MIN = 0.08; // never fit to less than 8% of the map, so one small county keeps context
  var boxByFips = {};
  function fitView() {
    var x0 = Infinity; var y0 = Infinity; var x1 = -Infinity; var y1 = -Infinity;
    function add(o) {
      var b = o && !o.sw && o.f && o.x !== null && inView(o.c) ? boxByFips[o.f] : null;
      if (!b) return;
      x0 = Math.min(x0, b[0]); y0 = Math.min(y0, b[1]); x1 = Math.max(x1, b[2]); y1 = Math.max(y1, b[3]);
    }
    data.outliers.forEach(add);
    add(data.highlight);
    if (!(x1 > x0) || !(y1 > y0)) { z = { k: 1, x: 0, y: 0 }; return; }
    var cx = (x0 + x1) / 2; var cy = (y0 + y1) / 2;
    var bw = Math.max(x1 - x0, W * FIT_MIN); var bh = Math.max(y1 - y0, H * FIT_MIN);
    var k = Math.max(1, Math.min(10, FIT_FILL * Math.min(W / bw, H / bh)));
    z = { k: k, x: W / 2 - cx * k, y: H / 2 - cy * k };
    clampPan();
  }
  function draw() {
    if (!ctx) return;
    var dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
    var cw = mapWrap.clientWidth || W; var ch = mapWrap.clientHeight || H;
    var pw = Math.max(1, Math.round(cw * dpr)); var ph = Math.max(1, Math.round(ch * dpr));
    if (canvas.width !== pw) canvas.width = pw;
    if (canvas.height !== ph) canvas.height = ph;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, pw, ph);
    var sc = scr() * dpr;
    ctx.setTransform(sc * z.k, 0, 0, sc * z.k, sc * z.x, sc * z.y);
    var unit = 1 / (scr() * z.k);
    ctx.fillStyle = 'rgba(0,120,174,0.35)'; // dhs-light-blue
    ctx.strokeStyle = 'rgba(0,91,132,0.6)'; // dhs-light-blue-60
    ctx.lineWidth = unit;
    for (var i = 0; i < data.baseline.length; i += 1) {
      var b = data.baseline[i];
      if (!inView(data.codes[b[2]])) continue;
      ctx.beginPath();
      ctx.arc(b[0], b[1], (b[3] ? 2.2 : R_BASE) * unit, 0, 2 * Math.PI);
      if (!b[3]) ctx.fill();
      ctx.stroke();
    }
  }
  function apply() {
    if (!mapWrap) return;
    var tf = 'translate(' + z.x + ',' + z.y + ') scale(' + z.k + ')';
    gBase.setAttribute('transform', tf);
    gTop.setAttribute('transform', tf);
    var k = z.k * scr();
    circles.forEach(function (c) { c.el.setAttribute('r', String(c.r / k)); });
    // Names keep their screen size; one shows only when it fits its county at this zoom.
    labels.forEach(function (lb) {
      var room = lb.l[2] * k; // screen px from the label point to the nearest edge
      var fits = room * 2 >= LABEL_PX * 1.1 && lb.chars * LABEL_PX * 0.6 <= room * 3.2;
      lb.el.setAttribute('font-size', String(LABEL_PX / k));
      lb.el.setAttribute('stroke-width', String(3 / k));
      lb.el.setAttribute('display', fits ? 'inline' : 'none');
    });
    draw();
  }
  function zoomAt(mx, my, k2) {
    k2 = Math.max(1, Math.min(10, k2));
    z.x = mx - (mx - z.x) * (k2 / z.k);
    z.y = my - (my - z.y) * (k2 / z.k);
    z.k = k2;
    clampPan();
    apply();
  }
  // Tooltip, three lines: title / amount \u00b7 sigma \u00b7 multiple of mean (numbers bold;
  // separators, the sigma sign and words plain) / county \u00b7 category icon + category.
  // Parts are [text, bold] pairs rendered as b/span elements, text set via textContent only.
  function tipLine(parts) {
    var div = h('div');
    parts.forEach(function (p) { div.appendChild(h(p[1] ? 'b' : 'span', null, p[0])); });
    return div;
  }
  function showTip(o, e) {
    clear(tip);
    var dot = [' \u00b7 ', false];
    tip.appendChild(h('div', 't', o.t || '(no title)'));
    tip.appendChild(tipLine([].concat(
      none(o.am) ? [['n/a', false]] : [[usd0.format(o.am), true]],
      [dot],
      none(o.sg) ? [['n/a (no variation)', false]] : [[o.sg.toFixed(2), true], [' \u03c3', false]],
      [dot],
      none(o.m) ? [['n/a', false]] : [[o.m.toFixed(1), true], ['\u00d7 the mean', false]]
    )));
    tip.appendChild(tipLine([[where(o) + ' \u00b7 ' + (ICON[o.c] ? ICON[o.c] + ' ' : '') + 'Category ' + o.c, false]]));
    tip.style.display = 'block';
    moveTip(e);
  }
  function moveTip(e) {
    var r = mapWrap.getBoundingClientRect();
    var x = e.clientX - r.left + 14; var y = e.clientY - r.top + 14;
    if (x > r.width - 330) x = Math.max(4, x - 350);
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }
  function hideTip() { tip.style.display = 'none'; }
  function addHalo(o, r, cls, i) {
    var el = s('circle', { cx: o.x, cy: o.y, r: r, 'class': cls });
    el.style.animationDelay = (-((i * 0.53) % 1.8)).toFixed(2) + 's'; // staggered, so the map shimmers
    gTop.appendChild(el);
    circles.push({ el: el, r: r });
  }
  function addLabel(ce) {
    var name = shortName(ce.c.n);
    var el = s('text', { x: ce.c.l[0], y: ce.c.l[1], 'class': 'lbl', 'text-anchor': 'middle', 'dominant-baseline': 'central' });
    el.textContent = name;
    gTop.appendChild(el);
    labels.push({ el: el, l: ce.c.l, chars: name.length });
  }
  function addDot(o, r, cls) {
    var el = s('circle', { cx: o.x, cy: o.y, r: r, 'class': cls });
    el.choroplethProject = o; // click target lookup (details window)
    el.addEventListener('mouseenter', function (e) { showTip(o, e); });
    el.addEventListener('mousemove', moveTip);
    el.addEventListener('mouseleave', hideTip);
    gTop.appendChild(el);
    circles.push({ el: el, r: r });
  }

  if (data.map) {
    W = data.map.w; H = data.map.h;
    mapWrap = h('div', 'map');
    mapWrap.style.aspectRatio = W + ' / ' + H;
    var box = '0 0 ' + W + ' ' + H;
    if (MODAL) mapWrap.className = 'map clickable';
    var svgBase = s('svg', { viewBox: box, 'class': 'layer', role: 'img', 'aria-label': 'Choropleth map of ' + name });
    // Top-aligned like the canvas, so the layers still match if the map grows for the details window.
    if (MODAL) svgBase.setAttribute('preserveAspectRatio', 'xMidYMin meet');
    gBase = s('g', {});
    data.map.counties.forEach(function (c) {
      if (c.b) boxByFips[c.f] = c.b;
      var p = s('path', { d: c.d, 'class': 'county' });
      p.choroplethCounty = c; // click target lookup (details window)
      var title = s('title', {});
      p.appendChild(title);
      gBase.appendChild(p);
      countyEls.push({ el: p, title: title, c: c });
    });
    svgBase.appendChild(gBase);
    canvas = h('canvas', 'layer');
    ctx = canvas.getContext ? canvas.getContext('2d') : null;
    var svgTop = s('svg', { viewBox: box, 'class': 'layer top' });
    if (MODAL) svgTop.setAttribute('preserveAspectRatio', 'xMidYMin meet');
    gTop = s('g', {});
    svgTop.appendChild(gTop);
    tip = h('div', 'tip');
    tip.style.display = 'none';
    var zoom = h('div', 'zoom');
    [['+', function () { zoomAt(W / 2, H / 2, z.k * 1.5); }], ['\u2212', function () { zoomAt(W / 2, H / 2, z.k / 1.5); }],
      ['Reset', function () { z = { k: 1, x: 0, y: 0 }; apply(); }]].concat(ui.pauseButton === false ? [] : [
      ['Pause', function (b) { // stops the outlier pulse (D45)
        var still = mapWrap.className.indexOf('still') < 0;
        mapWrap.className = (MODAL ? 'map clickable' : 'map') + (still ? ' still' : '');
        b.textContent = still ? 'Play' : 'Pause';
        b.setAttribute('aria-pressed', still ? 'true' : 'false');
      }]]).forEach(function (pair) {
      var b = h('button', null, pair[0]);
      b.setAttribute('type', 'button');
      if (pair[0] === 'Pause') { b.setAttribute('aria-pressed', 'false'); b.setAttribute('title', 'Pause or play the outlier pulse'); }
      b.addEventListener('click', function () { pair[1](b); });
      zoom.appendChild(b);
    });
    [svgBase, canvas, svgTop, zoom, tip].forEach(function (e) { mapWrap.appendChild(e); });
    app.appendChild(mapWrap);

    var legend = h('div', 'legend');
    [['sw-em', 'Most outliers in Emergency work (A, B)'], ['sw-pm', 'Most outliers in Permanent work (C\u2013G)'],
      ['sw-none', 'County with no outliers in this view'], ['sw-dot', MODAL ? 'Outlier (pulses; hover or click for details)' : 'Outlier (pulses; hover for details)'],
      ['sw-ring', 'Statewide outlier'], ['sw-base', 'Project below the threshold'], ['sw-hl', 'Highlighted PW'],
      [null, 'Dot position is not a project location.']].forEach(function (pair) {
      var item = h('span');
      if (pair[0]) item.appendChild(h('span', pair[0]));
      item.appendChild(document.createTextNode(pair[1]));
      legend.appendChild(item);
    });
    // D46 legend_position "below_map": legend directly under the map.
    if (ui.legend === 'below_map') { app.appendChild(legend); legend = null; }

    mapWrap.addEventListener('wheel', function (e) {
      e.preventDefault();
      var r = mapWrap.getBoundingClientRect(); var sc = scr();
      zoomAt((e.clientX - r.left) / sc, (e.clientY - r.top) / sc, z.k * Math.exp(-e.deltaY * 0.002));
    }, { passive: false });
    var drag = null;
    var press = null; // D46: a press that does not move is a click (pointer capture retargets pointerup)
    mapWrap.addEventListener('pointerdown', function (e) {
      if (modal) { // window open: a press outside it closes it; inside, its own buttons work
        if (!inside(e.target, modal.box)) closeModal();
        return;
      }
      press = MODAL ? { target: e.target, x: e.clientX, y: e.clientY } : null;
      if (e.target && e.target.tagName === 'BUTTON') return;
      if (e.preventDefault) e.preventDefault(); // a drag must not start a text selection
      if (typeof window !== 'undefined' && window.getSelection) { var sel = window.getSelection(); if (sel && sel.removeAllRanges) sel.removeAllRanges(); }
      drag = { x: e.clientX, y: e.clientY, zx: z.x, zy: z.y };
      if (mapWrap.setPointerCapture && e.pointerId !== undefined) mapWrap.setPointerCapture(e.pointerId);
    });
    mapWrap.addEventListener('pointermove', function (e) {
      if (!drag) return;
      var sc = scr();
      z.x = drag.zx + (e.clientX - drag.x) / sc;
      z.y = drag.zy + (e.clientY - drag.y) / sc;
      clampPan();
      apply();
    });
    mapWrap.addEventListener('pointerup', function (e) {
      var p = press; press = null;
      if (!p || modal || Math.abs(e.clientX - p.x) > 5 || Math.abs(e.clientY - p.y) > 5) return;
      var tg = p.target;
      if (tg && tg.choroplethProject) openProjects([tg.choroplethProject], null, e);
      else if (tg && tg.choroplethCounty) openCounty(tg.choroplethCounty, e);
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (n) { mapWrap.addEventListener(n, function () { drag = null; if (n !== 'pointerup') press = null; }); });
    if (MODAL && typeof document.addEventListener === 'function') {
      // A press anywhere outside the window (also outside the map) closes it; so does Escape.
      document.addEventListener('pointerdown', function (e) { if (modal && !inside(e.target, mapWrap)) closeModal(); });
      document.addEventListener('keydown', function (e) { if (modal && (e.key === 'Escape' || e.key === 'Esc')) closeModal(); });
    }
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(function () { apply(); }).observe(mapWrap);
    else if (typeof window !== 'undefined') window.addEventListener('resize', apply);
  } else {
    app.appendChild(h('p', 'notice', data.notice));
  }

  // ---- D46 details window (click_details "modal"). Inside the map box; no inner scrollbar:
  // when the window is taller than the map, the map grows (the page height changes) and
  // shrinks back on close.
  var modal = null;
  function inside(node, root) {
    for (var n = node; n; n = n.parentNode) if (n === root) return true;
    return false;
  }
  function detailRows(o) {
    var cat = data.categories[o.c] || {};
    var flagged = o.flagged !== undefined ? o.flagged : (!none(o.sg) && o.sg >= thr);
    return [['Title', o.t || '(no title)'], ['Applicant', o.a || 'n/a'],
      ['Category', o.c + (o.cd || cat.description ? ' \u2013 ' + (o.cd || cat.description) : '')], ['Location', where(o)],
      ['Amount', money2(o.am)], ['\u03c3', sig(o.sg)], ['Multiple of mean', times(o.m)],
      ['Result', flagged ? 'Flagged (' + thr + ' \u03c3 or more)' : 'Not flagged (below ' + thr + ' \u03c3)'],
      ['Category mean', money2(cat.mean)]];
  }
  function fitModal() {
    if (!modal) return;
    mapWrap.style.minHeight = '';
    var need = modal.box.offsetHeight ? modal.box.offsetHeight + 16 : 0;
    if (need > (mapWrap.clientHeight || 0)) mapWrap.style.minHeight = need + 'px';
    apply();
  }
  function renderModal() {
    var m = modal; var box = m.box;
    clear(box);
    var x = h('button', 'mx', '\u00d7');
    x.setAttribute('type', 'button');
    x.setAttribute('aria-label', 'Close');
    x.setAttribute('title', 'Close');
    x.addEventListener('click', closeModal);
    box.appendChild(x);
    var heading = h('h2', null, '');
    heading.setAttribute('id', 'choropleth-modal-title');
    box.appendChild(heading);
    if (!m.items.length) {
      heading.textContent = m.place;
      box.className = 'modal';
      box.appendChild(h('p', null, 'No cost outlier in this county in this view.'));
    } else {
      var o = m.items[m.i];
      heading.textContent = o.pw !== undefined && o.pw !== null ? 'PW ' + o.pw : 'Project details';
      var flagged = o.flagged !== undefined ? o.flagged : true;
      box.className = 'modal' + (flagged ? ' flag' : '');
      detailRows(o).forEach(function (r) {
        var row = h('div', 'row');
        row.appendChild(h('span', 'k', r[0]));
        row.appendChild(h('span', 'v', r[1]));
        box.appendChild(row);
      });
      if (m.items.length > 1) {
        var pager = h('div', 'pager');
        var prev = h('button', null, '\u2039 Previous');
        var next = h('button', null, 'Next \u203a');
        [prev, next].forEach(function (b) { b.setAttribute('type', 'button'); });
        if (m.i === 0) prev.setAttribute('disabled', 'disabled');
        if (m.i === m.items.length - 1) next.setAttribute('disabled', 'disabled');
        prev.addEventListener('click', function () { if (m.i > 0) { m.i -= 1; renderModal(); } });
        next.addEventListener('click', function () { if (m.i < m.items.length - 1) { m.i += 1; renderModal(); } });
        pager.appendChild(prev);
        pager.appendChild(h('span', 'k', (m.i + 1) + ' of ' + m.items.length + (m.place ? ' in ' + m.place : '')));
        pager.appendChild(next);
        box.appendChild(pager);
      }
    }
    fitModal();
    if (x.focus) x.focus({ preventScroll: true }); // never scrolls the host page
  }
  function openProjects(items, place) {
    if (!mapWrap || !MODAL) return;
    if (tip) hideTip();
    var back = h('div', 'mback');
    var box = h('div', 'modal');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-labelledby', 'choropleth-modal-title');
    back.appendChild(box);
    modal = { back: back, box: box, items: items, i: 0, place: place,
      prevFocus: typeof document.activeElement !== 'undefined' ? document.activeElement : null };
    mapWrap.appendChild(back);
    renderModal();
  }
  // A county: its outliers in the current view (largest sigma first), plus the highlighted PW if it is there.
  function openCounty(c) {
    var hl = data.highlight;
    var list = data.outliers.filter(function (o) { return o.f === c.f && inView(o.c); });
    list.sort(function (a, b) { return (b.sg || 0) - (a.sg || 0); });
    if (hl && hl.f === c.f && inView(hl.c) && !list.some(function (o) { return o.pw === hl.pw && o.a === hl.a; })) list.unshift(hl);
    openProjects(list, c.n);
  }
  function closeModal() {
    if (!modal) return;
    var m = modal; modal = null;
    if (m.back.parentNode) m.back.parentNode.removeChild(m.back);
    mapWrap.style.minHeight = '';
    apply();
    if (m.prevFocus && m.prevFocus.focus) m.prevFocus.focus({ preventScroll: true });
  }
  app.appendChild(cards);
  if (legend) app.appendChild(legend); // map legend sits below the summary cards

  // D47: always collapsible, open at load. The summary and the open state persist across view
  // switches; only the title count and the table body are rebuilt.
  var tableBox = h('details', 'tablebox');
  tableBox.setAttribute('open', '');
  tableBox.open = true;
  var tableSummary = h('summary');
  var tableTitle = h('h2', null, '');
  tableSummary.appendChild(tableTitle);
  var tableBody = h('div', 'tablebody');
  tableBox.appendChild(tableSummary);
  tableBox.appendChild(tableBody);
  app.appendChild(tableBox);
  // D48: nothing below the outlier table (no caveats, definition line or location notes). Rows that
  // are not on the map are still marked "(not on map)" in the table; the counts stay in structuredContent.

  function card(title, rows, cls) {
    var c = h('div', 'card' + (cls ? ' ' + cls : ''));
    c.appendChild(h('h2', null, title));
    rows.forEach(function (r) {
      var row = h('div', 'row');
      row.appendChild(h('span', 'k', r[0]));
      row.appendChild(h('span', 'v', r[1]));
      c.appendChild(row);
    });
    cards.appendChild(c);
  }
  function categoryRows(code) {
    var c = data.categories[code] || {};
    return [['Category mean', money2(c.mean)], ['Record count', num(c.recordCount)],
      ['Std. deviation (population)', money2(c.stddev)], ['Outliers', num(c.outliers)]];
  }
  function renderCards() {
    clear(cards);
    var hl = data.highlight;
    if (hl && ui.pwCard === false) {
      // D46 show_pw_card false: no PW card; the PW stays highlighted on the map
    } else if (hl && hl.onMap) {
      card('PW ' + hl.pw + ' (highlighted)', [['Title', hl.t || '(no title)'], ['Applicant', hl.a || 'n/a'],
        ['Category', hl.c + (hl.cd ? ' \u2013 ' + hl.cd : '')], ['Location', where(hl)], ['Amount', money2(hl.am)],
        ['\u03c3', sig(hl.sg)], ['Multiple of mean', times(hl.m)],
        ['Result', hl.flagged ? 'Flagged (' + thr + ' \u03c3 or more)' : 'Not flagged (below ' + thr + ' \u03c3)']]
        .concat(categoryRows(hl.c)), hl.flagged ? 'flag' : '');
    } else if (hl) {
      card('PW ' + hl.pw, [['Note', hl.note]]);
    }
    if (view === ALL_VIEW && ui.allCategoriesCard === false) {
      // D46 show_all_categories_card false: no "All categories A-G" card
    } else if (view === ALL_VIEW) {
      var tt = data.totals;
      card('All categories A\u2013G', [['Projects', num(tt.projectsMapped)], ['Outliers', num(tt.outliers)],
        ['Counties with outliers', num(tt.outlierCounties)], ['Statewide outliers', num(tt.statewideOutliers)],
        ['Categories shown', num(data.views.length - 1)]]);
    } else {
      var c = data.categories[view] || {};
      card('Category ' + view + (c.description ? ' \u2013 ' + c.description : ''), categoryRows(view).concat([['Projects', num(c.projects)]]));
    }
    cards.style.display = cards.firstChild ? '' : 'none'; // no empty gap when every card is off
  }
  function renderTable() {
    clear(tableBody);
    var list = data.outliers.filter(function (o) { return inView(o.c); });
    tableTitle.textContent = 'Outliers in this view (' + list.length + ')';
    if (!list.length) { tableBody.appendChild(h('p', null, 'No project reaches the threshold in this view.')); return; }
    var table = h('table');
    var head = h('tr');
    ['PW', 'Applicant', 'Category', 'Location', 'Amount', '\u03c3', 'Multiple of mean', 'Title'].forEach(function (x) { head.appendChild(h('th', null, x)); });
    table.appendChild(head);
    list.forEach(function (o) {
      var tr = h('tr');
      [[o.pw, 'n'], [o.a || 'n/a'], [o.c], [where(o) + (data.map && o.x === null ? ' (not on map)' : '')], [money2(o.am), 'n'],
        [sig(o.sg), 'n'], [times(o.m), 'n'], [o.t || '(no title)']].forEach(function (cell) { tr.appendChild(h('td', cell[1] || null, cell[0])); });
      table.appendChild(tr);
    });
    tableBody.appendChild(table);
  }
  function setView(v) {
    view = v;
    Object.keys(buttons).forEach(function (k) {
      buttons[k].className = 'view ' + (k === ALL_VIEW ? 'all' : groupOf(k)) + (k === v ? ' on' : '');
      buttons[k].setAttribute('aria-pressed', k === v ? 'true' : 'false');
    });
    if (modal) closeModal();
    if (mapWrap) {
      var dom = dominantByCounty();
      clear(gTop);
      circles = []; // the hover targets are rebuilt once per view switch
      labels = [];
      countyEls.forEach(function (ce) {
        var n = ce.c.o[v] || 0;
        var g = n > 0 ? groupOf(dom[ce.c.f]) : null;
        ce.el.setAttribute('fill', g ? FILL[g][0] : BASE_FILL);
        ce.el.setAttribute('fill-opacity', g ? String(FILL[g][1]) : '1');
        // Section 508: the color is also given in text (tooltip, buttons, table).
        ce.title.textContent = ce.c.n + ': ' + n + (n === 1 ? ' outlier' : ' outliers')
          + (g ? '; most in Category ' + dom[ce.c.f] + ' (' + GROUP_NAME[g] + ')' : '');
        if (n > 0 && ce.c.l) addLabel(ce); // names only for counties with outliers in the view
      });
      var hl = data.highlight;
      var hlOn = hl && hl.x !== null && inView(hl.c);
      var shown = data.outliers.filter(function (o) { return o.x !== null && inView(o.c); });
      if (shown.length <= HALO_MAX) shown.forEach(function (o, i) { addHalo(o, R_OUT, o.sw ? 'halo sw' : 'halo', i); });
      if (hlOn) addHalo(hl, R_HI, 'halo hlh', 0);
      shown.forEach(function (o) { addDot(o, R_OUT, o.sw ? 'out sw' : 'out'); });
      if (hlOn) addDot(hl, R_HI, 'hl');
      if (tip) hideTip();
      fitView(); // each view opens zoomed to its outlier counties; Reset still shows the whole state
    }
    renderCards();
    renderTable();
    apply();
  }
  setView(view);
}
