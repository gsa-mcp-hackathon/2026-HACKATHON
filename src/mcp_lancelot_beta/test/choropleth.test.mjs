// generate_choropleth (BUILD_PLAN D34-D36, D41, D42): inputs, data errors,
// outlier math on the real export, geometry, the HTML page and its browser
// script (run in a small fake DOM; no network, no npm packages).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const M = (name) => new URL(`../lib/tools/choropleth/lib/${name}`, import.meta.url).href;
const { parseInputs } = await import(M('inputs.mjs'));
const { loadDisaster, loadGeometry } = await import(M('data.mjs'));
const { analyze } = await import(M('analysis.mjs'));
const { adjacency, colorFamily, prepareCounties, buildMap, samplePoint, mulberry32, poleOfInaccessibility, labelPoint } = await import(M('geo.mjs'));
const { CSP, buildWidgetData, buildWidgetHtml, scriptSafeJson } = await import(M('widget.mjs'));

test('label point (D45): inside odd shapes, in the largest part, with the room to the edge', () => {
  const inside = (x, y, ring) => { let s = false; for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) { const [xi, yi] = ring[i]; const [xj, yj] = ring[j]; if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) s = !s; } return s; };
  // U shape made of 3-wide strips: the biggest circle sits in a bottom corner, radius 3*sqrt2/(1+sqrt2) = 1.757
  const U = [[0, 0], [10, 0], [10, 10], [7, 10], [7, 3], [3, 3], [3, 10], [0, 10], [0, 0]];
  const [ux, uy, ur] = poleOfInaccessibility([U]);
  assert.ok(inside(ux, uy, U));
  const best = (3 * Math.SQRT2) / (1 + Math.SQRT2);
  assert.ok(ur <= best + 1e-9 && ur >= best - 0.06, `room ${ur}`); // within the precision (1/200 of the size)
  // C shape whose centroid is outside the shape
  const C = [[0, 0], [10, 0], [10, 2], [2, 2], [2, 8], [10, 8], [10, 10], [0, 10], [0, 0]];
  const [cx, cy] = poleOfInaccessibility([C]);
  assert.ok(inside(cx, cy, C));
  assert.equal(inside(5.4, 5, C), false); // where a centroid would land
  // multipart county: the label goes in the larger island
  const big = [[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]; const small = [[30, 0], [32, 0], [32, 2], [30, 2], [30, 0]];
  const [lx, ly, lr] = labelPoint([[small], [big]]);
  assert.ok(lx > 9 && lx < 11 && ly > 9 && ly < 11 && lr > 9.5, JSON.stringify([lx, ly, lr]));
  assert.equal(labelPoint([]), null);
});

test('widget CSS (D45): DHS colors, pulse off for reduced motion and when paused, no fonts or URLs', () => {
  const html = buildWidgetHtml({ v: 1 });
  const css = html.match(/<style>([\s\S]*?)<\/style>/)[1];
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)\{\.top circle\.halo\{animation:none;opacity:0\}\}/);
  assert.match(css, /\.still \.top circle\.halo\{animation:none;opacity:0\}/);
  assert.match(css, /@keyframes pulse\{/);
  assert.doesNotMatch(css, /@font-face|url\(/);
  const allowed = new Set(['#ffffff', '#005288', '#d6e3ec', '#5a5b5d', '#2f2f30', '#c0c2c4', '#dedfe0', '#929395', '#c41230', '#660919',
    '#0078ae', '#005b84', '#5e9732', '#477326', '#ffbe2e', '#faf3d1']);
  const used = new Set((css.match(/#[0-9a-f]{6}\b/gi) || []).map((x) => x.toLowerCase()));
  for (const c of used) assert.ok(allowed.has(c), `not a DHS palette color: ${c}`);
  const rgba = (css.match(/rgba\((\d+),(\d+),(\d+),/g) || []).map((x) => x.slice(5, -1));
  for (const c of rgba) assert.ok(['255,190,46', '94,151,50', '0,120,174', '0,91,132', '0,0,0'].includes(c), `rgba not on the palette: ${c}`);
});
const { runGenerateChoropleth, CHOROPLETH_TOOL_NAME } = await import(M('tool.mjs'));

const ROOT = '/v';
const LIVE = '/Volumes/users/tom_jacobson/choropleth_data';

// ------------------------------------------------------------- fixtures

function notFound(p) { const e = new Error(`not found ${p}`); e.status = 404; return e; }
function fakeFs(files) {
  return async (p) => { if (!(p in files)) throw notFound(p); return Buffer.from(typeof files[p] === 'string' ? files[p] : JSON.stringify(files[p])); };
}
const sq = (x, y, s = 1) => [[[[x, y], [x + s, y], [x + s, y + s], [x, y + s], [x, y]]]];
// 3x3 grid of counties 12001..12009 (row by row), lon -82..-79, lat 27..30
const GRID = Array.from({ length: 9 }, (_, i) => ({ fips: `120${String(i + 1).padStart(2, '0')}`, name: `County ${i + 1}`, polygons: sq(-82 + (i % 3), 27 + Math.floor(i / 3)) }));
const GEO_FL = { schemaVersion: 1, stateFips: '12', source: 'test grid', counties: GRID };

function project(pw, category, amount, sigma, geo = 'COUNTY', countyFips = '12005', extra = {}) {
  return { pw, applicantId: `000-${pw}-00`, title: `Project ${pw}`, category, status: 'Active', size: 'Large', state: 'FL', stateFips: '12', countyFips: geo === 'COUNTY' ? countyFips : null, county: geo === 'COUNTY' ? `County ${Number(countyFips.slice(3))}` : geo === 'STATEWIDE' ? 'Statewide' : null, geo, amount, sigma, multipleOfMean: amount / 100, ...extra };
}
function doc(projects, overrides = {}) {
  return {
    schemaVersion: 1, snapshotDate: '2026-11-06', loadId: 'L1', disasterNumber: 9999, declarationDate: '2024-01-01', states: ['FL'],
    newestLastRefresh: '2026-07-24T15:07:02Z',
    categories: [{ code: 'A', description: 'Debris Removal', recordCount: 4, mean: 100, stddev: 10, totalAmount: 400 }, { code: 'E', description: 'Public Buildings', recordCount: 2, mean: 50, stddev: 5, totalAmount: 100 }, { code: 'Z', description: 'Management Costs', recordCount: 1, mean: 7, stddev: 0, totalAmount: 7 }],
    projects, ...overrides,
  };
}
const PROJECTS = [
  project(1, 'A', 150, 5.0, 'COUNTY', '12005'),
  project(2, 'A', 130, 3.0, 'COUNTY', '12001'), // exactly at the threshold: an outlier
  project(3, 'A', 120, 2.99, 'COUNTY', '12005'),
  project(4, 'A', 90, null, 'STATEWIDE'),
  project(5, 'E', 80, 4.2, 'STATEWIDE'),
  project(6, 'E', 70, 1.0, 'UNMAPPABLE'),
  project(7, 'Z', 7, null, 'STATEWIDE'),
  project(8, 'E', 60, 3.5, 'COUNTY', '12099'), // county code with no shape
];
function files(extra = {}) {
  return {
    [`${ROOT}/manifest.json`]: { schemaVersion: 1, latest: '2026-11-06', declarationsSince: '2021-01-01', snapshots: [{ date: '2026-11-06', loadId: 'L1' }, { date: '2026-11-05', loadId: 'L0' }] },
    [`${ROOT}/snapshots/2026-11-06/disasters/9999.json`]: doc(PROJECTS),
    [`${ROOT}/snapshots/2026-11-05/disasters/9999.json`]: doc(PROJECTS.slice(0, 3), { loadId: 'L0', snapshotDate: '2026-11-05' }),
    [`${ROOT}/geo/v1/states/12.json`]: GEO_FL,
    ...extra,
  };
}
function fakeTracer() {
  return { runId: 'call-20261106T000000Z-abc123', debug: false, trace: {}, outcome: null, setOutcome(o) { this.outcome = o; }, errorMessage: (e) => String(e && e.message ? e.message : e), addRunFile() {} };
}
async function run(args, fsFiles = files()) {
  const tracer = fakeTracer();
  const res = await runGenerateChoropleth(args, {}, tracer, { readFile: fakeFs(fsFiles), root: ROOT });
  return { res, tracer };
}
const errorOf = (res) => JSON.parse(res.content[0].text);

// ------------------------------------------------------------- fake DOM

class El {
  constructor(tag, ns = null) {
    this.tagName = tag.toUpperCase(); this.ns = ns; this.children = []; this.attrs = {}; this.listeners = {}; this.style = {};
    this.className = ''; this.text = ''; this.parentNode = null; this.width = 0; this.height = 0;
    this.clientWidth = tag === 'div' ? 1000 : 0; this.clientHeight = tag === 'div' ? 600 : 0;
  }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  removeChild(c) { this.children.splice(this.children.indexOf(c), 1); c.parentNode = null; return c; }
  get firstChild() { return this.children[0] || null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(n, f) { (this.listeners[n] ||= []).push(f); }
  fire(n, e = {}) { for (const f of this.listeners[n] || []) f({ target: this, preventDefault() {}, clientX: 0, clientY: 0, ...e }); }
  set textContent(v) { this.children = []; this.text = String(v); }
  get textContent() { return this.text + this.children.map((c) => c.textContent).join(''); }
  set innerHTML(_v) { throw new Error('innerHTML must not be used'); }
  getContext() { const calls = { arc: 0 }; this.ctxCalls = calls; return { setTransform() {}, clearRect() {}, beginPath() {}, arc() { calls.arc += 1; }, fill() {}, stroke() {} }; }
  getBoundingClientRect() { return { left: 0, top: 0, width: 1000, height: 600 }; }
  all(pred, out = []) { if (pred(this)) out.push(this); for (const c of this.children) if (c instanceof El) c.all(pred, out); return out; }
}
function runPage(html) {
  const json = html.match(/<script type="application\/json" id="choropleth-data">([\s\S]*?)<\/script>/)[1];
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const app = new El('div');
  const document = {
    title: '',
    createElement: (t) => new El(t),
    createElementNS: (ns, t) => new El(t, ns),
    createTextNode: (t) => { const e = new El('#text'); e.text = String(t); return e; },
    getElementById: (id) => (id === 'app' ? app : id === 'choropleth-data' ? { textContent: json } : null),
  };
  vm.runInNewContext(script, { document, window: { devicePixelRatio: 1, addEventListener() {} }, Intl, ResizeObserver: undefined });
  return { app, document };
}
const byTag = (root, tag) => root.all((e) => e.tagName === tag.toUpperCase());
const buttonsOf = (app) => byTag(app, 'button');
const pageDataOf = (html) => JSON.parse(html.match(/<script type="application\/json" id="choropleth-data">([\s\S]*?)<\/script>/)[1]);
// [x, y, k] of the map transform (base layer)
const zoomOf = (app) => byTag(app, 'g')[0].attrs.transform.match(/translate\(([-\d.e+]+),([-\d.e+]+)\) scale\(([\d.e+]+)\)/).slice(1).map(Number);
const near = (a, b, eps = 1e-6) => Math.abs(a - b) < eps;
const viewButton = (app, id) => buttonsOf(app).find((b) => b.getAttribute('data-view') === (id === 'All' ? 'ALL' : id));

// ---------------------------------------------------------------- inputs

test('inputs: defaults, coercion and every rejection is INVALID_INPUT', () => {
  const display = { initialView: 'pw_category', pauseButton: true, pwCard: true, allCategoriesCard: true, legendPosition: 'below_cards', clickDetails: 'none', mapAspectRatio: null };
  assert.deepEqual(parseInputs({ disaster_number: 4673 }), { disasterNumber: 4673, pwNumber: null, applicantId: null, sigmaThreshold: 3, asOf: null, display });
  assert.deepEqual(parseInputs({ disaster_number: '4856', pw_number: '2', applicant_id: ' 037-UZ1M2-00 ', sigma_threshold: '2.5', as_of: '2026-11-06' }),
    { disasterNumber: 4856, pwNumber: 2, applicantId: '037-UZ1M2-00', sigmaThreshold: 2.5, asOf: '2026-11-06', display });
  // D46 choropleth map display options
  assert.deepEqual(parseInputs({ disaster_number: 1, initial_view: ' ALL ', show_pause_button: false, show_pw_card: 'false', show_all_categories_card: 'FALSE', legend_position: 'below_map', click_details: 'modal' }).display,
    { initialView: 'all', pauseButton: false, pwCard: false, allCategoriesCard: false, legendPosition: 'below_map', clickDetails: 'modal', mapAspectRatio: null });
  // D50: exactly the seven map box shapes
  for (const r of ['1:1', '16:9', '4:3', '5:3', '9:16', '3:4', '3:5']) {
    assert.equal(parseInputs({ disaster_number: 1, map_aspect_ratio: ` ${r} ` }).display.mapAspectRatio, r);
  }
  for (const bad of [{ initial_view: 'X' }, { show_pause_button: 'no' }, { show_pw_card: 0 }, { legend_position: 'top' }, { click_details: true },
    { map_aspect_ratio: '2:1' }, { map_aspect_ratio: '16x9' }, { map_aspect_ratio: '16 : 9' }, { map_aspect_ratio: '32:18' }, { map_aspect_ratio: 1.78 }, { map_aspect_ratio: 'auto' }]) {
    assert.throws(() => parseInputs({ disaster_number: 1, ...bad }), (e) => e.code === 'INVALID_INPUT', JSON.stringify(bad));
  }
  for (const bad of [{}, { disaster_number: 'DR-4673' }, { disaster_number: 0 }, { disaster_number: 46.5 }, { disaster_number: 4673, sigma_threshold: 0.5 },
    { disaster_number: 4673, sigma_threshold: 11 }, { disaster_number: 4673, sigma_threshold: 'NaN' }, { disaster_number: 4673, as_of: '2026-02-30' },
    { disaster_number: 4673, as_of: '11/06/2026' }, { disaster_number: 4673, applicant_id: 'x' }, { disaster_number: 4673, pw_number: 1, applicant_id: '<b>' }, null]) {
    assert.throws(() => parseInputs(bad), (e) => e.code === 'INVALID_INPUT', JSON.stringify(bad));
  }
});

// ------------------------------------------------------------ data errors

test('data: missing manifest, unknown as_of, missing disaster, mismatched load', async () => {
  await assert.rejects(loadDisaster({ disasterNumber: 9999, readFile: fakeFs({}), root: ROOT }), (e) => e.code === 'DATA_UNAVAILABLE');
  await assert.rejects(loadDisaster({ disasterNumber: 9999, asOf: '2026-01-01', readFile: fakeFs(files()), root: ROOT }),
    (e) => e.code === 'SNAPSHOT_NOT_FOUND' && e.details.available.join() === '2026-11-06,2026-11-05');
  await assert.rejects(loadDisaster({ disasterNumber: 1, readFile: fakeFs(files()), root: ROOT }), (e) => e.code === 'DISASTER_NOT_LOADED' && /since 2021-01-01/.test(e.message));
  const bad = files({ [`${ROOT}/snapshots/2026-11-06/disasters/9999.json`]: doc(PROJECTS, { loadId: 'OTHER' }) });
  await assert.rejects(loadDisaster({ disasterNumber: 9999, readFile: fakeFs(bad), root: ROOT }), (e) => e.code === 'DATA_UNAVAILABLE');
  const older = await loadDisaster({ disasterNumber: 9999, asOf: '2026-11-05', readFile: fakeFs(files()), root: ROOT });
  assert.equal(older.doc.projects.length, 3);
  const geo = await loadGeometry({ stateFips: ['12', '06', 'xx'], readFile: fakeFs(files()), root: ROOT });
  assert.deepEqual([Object.keys(geo.states), geo.missing], [['12'], ['06']]);
});

// ---------------------------------------------------------------- analysis

test('analysis: threshold is inclusive, Z is off the map, counts per view', () => {
  const a = analyze(doc(PROJECTS), { sigmaThreshold: 3 });
  assert.deepEqual(a.outliers.map((p) => p.pw), [1, 5, 8, 2]); // sorted by sigma
  assert.deepEqual(a.views, ['ALL', 'A', 'E']);
  assert.deepEqual(a.countyOutliers.ALL, { 12005: 1, 12001: 1, 12099: 1 });
  assert.deepEqual(a.countyOutliers.A, { 12005: 1, 12001: 1 });
  assert.equal(a.statewideOutliers.E, 1);
  assert.deepEqual(a.totals, { projectsAll: 8, projectsMapped: 7, outliers: 4, outlierCounties: 3, statewideOutliers: 1, unmappable: 1, unmappableOutliers: 0 });
  assert.equal(a.initialView, 'ALL');
  const hz = analyze(doc(PROJECTS), { sigmaThreshold: 3, pwNumber: 7 });
  assert.equal(hz.highlight.onMap, false);
  assert.equal(hz.highlight.note, 'PW 7 is Category Z (Management Costs), not shown on this map');
  const he = analyze(doc(PROJECTS), { sigmaThreshold: 4.5, pwNumber: 5 });
  assert.deepEqual([he.initialView, he.highlight.flagged], ['E', false]);
  assert.throws(() => analyze(doc(PROJECTS), { sigmaThreshold: 3, pwNumber: 404 }), (e) => e.code === 'PW_NOT_FOUND');
  const twice = doc([...PROJECTS, { ...PROJECTS[0], applicantId: '999-X-00' }]);
  assert.throws(() => analyze(twice, { sigmaThreshold: 3, pwNumber: 1 }), (e) => e.code === 'INVALID_INPUT' && /add applicant_id/.test(e.message));
  assert.equal(analyze(twice, { sigmaThreshold: 3, pwNumber: 1, applicantId: '999-X-00' }).highlight.applicantId, '999-X-00');
});

// Pinned to one snapshot so daily OpenFEMA growth does not break the counts below.
// Snapshots are kept 90 days; after that this test skips (pick a newer date and re-measure).
const PINNED = '2026-11-12';
const live = fs.existsSync(`${LIVE}/snapshots/${PINNED}/disasters/4673.json`);
test('analysis on the real export matches the live OpenFEMA measurement in D35', { skip: !live && `export snapshot ${PINNED} not available here` }, () => {
  const read = (dn) => JSON.parse(fs.readFileSync(`${LIVE}/snapshots/${PINNED}/disasters/${dn}.json`, 'utf8'));
  const d4673 = read(4673);
  const a = analyze(d4673, { sigmaThreshold: 3, pwNumber: 4902 });
  const name = (f) => d4673.projects.find((p) => p.countyFips === f).county;
  assert.equal(a.totals.projectsMapped, 3609); // snapshot 2026-11-12 (was 3606 on 2026-11-06)
  assert.equal(a.totals.outliers, 47);
  assert.equal(a.totals.outlierCounties, 11);
  assert.equal(a.statewideOutliers.ALL, 10);
  const all = Object.fromEntries(Object.entries(a.countyOutliers.ALL).map(([f, n]) => [name(f), n]));
  assert.equal(all['Lee County'], 17);
  assert.equal(all['Charlotte County'], 5);
  assert.equal(a.countyOutliers.E['12071'], 10); // Lee, E
  assert.deepEqual(a.outliers.filter((p) => p.category === 'C').map((p) => (p.geo === 'STATEWIDE' ? 'Statewide' : p.county)).sort(), ['Charlotte County', 'DeSoto County', 'Statewide']);
  assert.deepEqual([a.initialView, a.highlight.flagged, Math.round(a.highlight.sigma * 1e4) / 1e4], ['C', true, 9.7053]);
  const b = analyze(read(4856), { sigmaThreshold: 3 });
  assert.deepEqual([b.totals.projectsMapped, b.totals.outliers, b.statewideOutliers.ALL, b.countyOutliers.ALL['06037']], [295, 5, 1, 4]);
});

// ---------------------------------------------------------------- geometry

test('geometry: neighbors share an edge, never a shade; dots stay inside; layout is seeded', () => {
  const counties = prepareCounties({ 12: GEO_FL });
  const adj = adjacency(counties);
  assert.deepEqual([...adj[4]].sort(), [1, 3, 5, 7]); // center square: 4 edge neighbors, corners excluded
  const { colors, conflicts } = colorFamily([...counties.keys()], adj);
  assert.equal(conflicts, 0);
  for (let i = 0; i < counties.length; i += 1) for (const n of adj[i]) assert.notEqual(colors.get(i), colors.get(n));
  const a = analyze(doc(PROJECTS), { sigmaThreshold: 3 });
  const m1 = buildMap({ geometryByState: { 12: GEO_FL }, analysis: a, seedKey: 'DR-9999' });
  const m2 = buildMap({ geometryByState: { 12: GEO_FL }, analysis: a, seedKey: 'DR-9999' });
  assert.deepEqual([...m1.positions], [...m2.positions]);
  assert.equal(m1.drawn, true);
  assert.deepEqual(m1.countiesNotInShapes, ['12099']);
  assert.deepEqual(m1.notPlaced.map((n) => n.reason).sort(), ['county not in the shape file', 'location not mappable']);
  for (const c of m1.counties) for (const view of a.views) assert.match(c.shades[view], /^[rg][0-4]$/);
  assert.match(m1.counties.find((c) => c.fips === '12005').shades.ALL, /^r/);
  assert.match(m1.counties.find((c) => c.fips === '12009').shades.ALL, /^g/);
  // county 12005 is the center square: its dots land inside it
  const [x0, y0, x1, y1] = [m1.width / 3, 0, (2 * m1.width) / 3, m1.height].map((v, i) => v); // loose bounds by column
  const p1 = m1.positions.get('1|000-1-00|A');
  assert.ok(p1[0] > x0 && p1[0] < x1 && p1[1] > y0 && p1[1] < y1);
  const region = { bbox: [0, 0, 10, 10], center: [5, 5], anchor: [0, 0], contains: (x, y) => x > 2 && x < 8 && y > 2 && y < 8 };
  const rng = mulberry32(7);
  for (let i = 0; i < 200; i += 1) { const [x, y] = samplePoint(region, rng); assert.ok(region.contains(x, y)); }
  assert.equal(m1.overlapsRemaining, 0);
});

// ---------------------------------------------------------------- the page

test('page: CSP, escaped data, no network, no innerHTML', async () => {
  const evil = '</script><img src=x onerror=alert(1)> & \u2028';
  const { res } = await run({ disaster_number: 9999, pw_number: 1 }, files({ [`${ROOT}/snapshots/2026-11-06/disasters/9999.json`]: doc(PROJECTS.map((p) => (p.pw === 1 ? { ...p, title: evil } : p))) }));
  const html = res.content[1].resource.text;
  assert.ok(html.includes(`<meta http-equiv="Content-Security-Policy" content="${CSP}">`));
  assert.equal((html.match(/<\/script>/g) || []).length, 2, 'only the two real closing tags');
  assert.ok(!html.includes('<img'));
  const withoutNs = html.replaceAll('http://www.w3.org/2000/svg', '');
  assert.doesNotMatch(withoutNs, /https?:\/\//);
  // the data block holds the (escaped, inert) title text; check the markup and script around it
  const code = html.replace(/<script type="application\/json" id="choropleth-data">[\s\S]*?<\/script>/, '');
  assert.doesNotMatch(code, /\ssrc=|<link|<iframe|innerHTML|fetch\(|XMLHttpRequest|WebSocket|EventSource|import\(|sendBeacon/);
  assert.equal(scriptSafeJson({ t: evil }).includes('<'), false);
  const { app } = runPage(html);
  const cell = byTag(app, 'td').find((td) => td.text === evil);
  assert.ok(cell, 'the title is shown as literal text');
});

test('page: map, views, hover, zoom (browser script in a fake DOM)', async () => {
  const { res } = await run({ disaster_number: 9999, pw_number: 1 });
  const { app, document } = runPage(res.content[1].resource.text);
  assert.equal(document.title, 'DR-9999-FL cost outliers');
  assert.deepEqual(buttonsOf(app).filter((b) => b.className.startsWith('view')).map((b) => b.textContent), ['All (4)', '\u{1F69B} (2)', '\u{1F3E5} (2)']);
  assert.match(viewButton(app, 'A').getAttribute('title'), /^Category A/);
  // D49 page order: view buttons, map, cards, legend, table; no visible title.
  const order = app.children.map((c) => c.className || c.tagName);
  assert.deepEqual(order, ['filter', 'map', 'cards', 'legend', 'tablebox']);
  assert.equal(byTag(app, 'h1').length, 0);
  assert.ok(!app.all((e) => /cost outliers/.test(e.text || '')).length, 'no visible title text'); // only the hidden document <title> keeps it
  // D48: the outlier table is last, even with 1 unmappable project and 1 county without a shape here
  assert.equal(order[order.length - 1], 'tablebox');
  assert.ok(!order.includes('sub'));
  assert.doesNotMatch(res.content[1].resource.text.replace(/<script type="application\/json"[\s\S]*?<\/script>/, ''), /no mappable location|no county shape/);
  assert.deepEqual(res.structuredContent.map.countiesNotInShapes, ['12099']); // still reported to the caller
  const html0 = res.content[1].resource.text;
  assert.doesNotMatch(html0, /Review indicator on public data|Grants Manager project figures|placed at random inside|County boundaries:|own damage category|FEMA data last refreshed/);
  assert.ok(res.structuredContent.caveats.length >= 3, 'caveats stay in structuredContent');
  assert.match(res.content[0].text, /Not a finding of fraud/, 'and in the text summary');
  assert.equal(viewButton(app, 'A').getAttribute('aria-pressed'), 'true'); // opens on the PW's category
  assert.equal(byTag(app, 'path').length, 9);
  const circles = () => byTag(app, 'circle').filter((c) => !c.attrs.class.startsWith('halo'));
  const halos = () => byTag(app, 'circle').filter((c) => c.attrs.class.startsWith('halo'));
  assert.equal(circles().length, 3); // two A outliers + the highlight ring
  // D45: one fading halo behind every outlier and the highlight, drawn before (under) the dots, staggered
  assert.deepEqual(halos().map((c) => c.attrs.class), ['halo', 'halo', 'halo hlh']);
  const gTopKids = byTag(app, 'g')[1].children.map((c) => c.attrs.class);
  assert.ok(gTopKids.lastIndexOf('halo hlh') < gTopKids.indexOf('out'));
  assert.notEqual(halos()[0].style.animationDelay, halos()[1].style.animationDelay);
  // D45: names only in counties with outliers in the view, without the count, and not over the dots
  const labels = () => byTag(app, 'text').filter((t) => t.attrs.class === 'lbl');
  const pd0 = pageDataOf(res.content[1].resource.text);
  const withOutliersA = pd0.map.counties.filter((c) => c.o.A > 0).map((c) => c.n.replace(/ County$/, '')).sort();
  assert.deepEqual(labels().map((t) => t.textContent).sort(), withOutliersA);
  assert.ok(labels().every((t) => !/outlier|:/.test(t.textContent)));
  assert.ok(gTopKids.lastIndexOf('lbl') < gTopKids.indexOf('halo'));
  // D45: county fill = work type of the dominant category (A = Emergency work, gold)
  const fillOf = (f) => byTag(app, 'path').find((p) => p.children[0].textContent.startsWith(pd0.map.counties.find((c) => c.f === f).n + ':'));
  assert.equal(fillOf('12005').attrs.fill, '#ffbe2e');
  assert.match(fillOf('12005').children[0].textContent, /most in Category A \(Emergency work\)/);
  assert.equal(fillOf('12009').attrs.fill, '#d6e3ec'); // no outliers in view A
  assert.match(viewButton(app, 'A').className, /\bem\b/);
  assert.match(viewButton(app, 'E').className, /\bpm\b/);
  assert.match(viewButton(app, 'E').getAttribute('title'), /\(Permanent work\)$/);
  // D45: Pause stops the pulse (class on the map), Play restarts it
  const pause = buttonsOf(app).find((b) => b.textContent === 'Pause');
  const mapEl = app.all((e) => e.className.startsWith('map'))[0];
  pause.fire('click');
  assert.equal(mapEl.className, 'map still');
  assert.equal(pause.textContent, 'Play');
  assert.equal(pause.getAttribute('aria-pressed'), 'true');
  pause.fire('click');
  assert.equal(mapEl.className, 'map');
  // auto-fit: view A = union of the boxes of counties 12001 and 12005, centred, 70% fill
  const pd = pageDataOf(res.content[1].resource.text);
  const box = (f) => pd.map.counties.find((c) => c.f === f).b;
  const [b1, b5] = [box('12001'), box('12005')];
  const u = [Math.min(b1[0], b5[0]), Math.min(b1[1], b5[1]), Math.max(b1[2], b5[2]), Math.max(b1[3], b5[3])];
  const [zx, zy, zk] = zoomOf(app);
  assert.ok(near(zk, Math.max(1, Math.min(10, 0.7 * Math.min(pd.map.w / (u[2] - u[0]), pd.map.h / (u[3] - u[1]))))));
  assert.ok(near(zx + zk * (u[0] + u[2]) / 2, pd.map.w / 2) && near(zy + zk * (u[1] + u[3]) / 2, pd.map.h / 2), 'outlier counties are centred');
  viewButton(app, 'E').fire('click'); // E outliers: one Statewide, one with no county shape -> whole state
  assert.deepEqual(zoomOf(app), [0, 0, 1]);
  viewButton(app, 'All').fire('click');
  assert.equal(circles().length, 4); // 4 outliers, one has no shape (12099), + highlight
  assert.equal(circles().filter((c) => c.attrs.class === 'out sw').length, 1);
  const rowsInTable = () => byTag(app, 'tr').length - 1;
  assert.equal(rowsInTable(), 4);
  assert.ok(byTag(app, 'td').some((td) => td.text === 'County 99 (not on map)'));
  const tinted = byTag(app, 'path').filter((p) => p.attrs.fill !== '#d6e3ec');
  assert.equal(tinted.length, 2); // 12001 and 12005 have outliers; 12099 has no shape
  viewButton(app, 'E').fire('click');
  assert.equal(rowsInTable(), 2);
  // hover
  viewButton(app, 'All').fire('click');
  const dot = circles().find((c) => c.attrs.class === 'out');
  dot.fire('mouseenter', { clientX: 100, clientY: 100 });
  const tip = app.all((e) => e.className === 'tip')[0];
  assert.equal(tip.style.display, 'block');
  // Tooltip: title / amount · sigma · multiple of mean / county · icon + category.
  assert.equal(tip.children.length, 3);
  assert.doesNotMatch(tip.textContent, /Dot position|PW |applicant/);
  const [, nums, place] = tip.children;
  const boldParts = nums.children.filter((c) => c.tagName === 'B').map((c) => c.textContent);
  assert.equal(boldParts.length, 3, 'amount, sigma and multiple are bold');
  assert.ok(boldParts.every((b) => /^\$?[0-9][0-9.,]*$/.test(b)), 'only numbers are bold: ' + boldParts.join('|'));
  const plainParts = nums.children.filter((c) => c.tagName !== 'B').map((c) => c.textContent);
  assert.deepEqual(plainParts, [' \u00b7 ', ' \u03c3', ' \u00b7 ', '\u00d7 the mean'], 'separators, sigma sign and words stay plain');
  assert.match(nums.textContent, /^\$[0-9,]+ \u00b7 [0-9.]+ \u03c3 \u00b7 [0-9.]+\u00d7 the mean$/);
  assert.match(place.textContent, /^.+ \u00b7 \S+ Category [A-G]$/u);
  dot.fire('mouseleave');
  assert.equal(tip.style.display, 'none');
  // zoom keeps dots the same size on screen
  const g = byTag(app, 'g')[1];
  const k0 = zoomOf(app)[2]; // the view opens auto-fitted, so k0 may be above 1
  const r0 = Number(dot.attrs.r);
  const map = app.all((e) => e.className === 'map')[0];
  map.fire('wheel', { deltaY: -400, clientX: 500, clientY: 300 });
  const k = Number(g.attrs.transform.match(/scale\(([\d.]+)\)/)[1]);
  assert.ok(k > k0 && k <= 10);
  const dotNow = circles().find((c) => c.attrs.class === 'out');
  assert.ok(Math.abs(Number(dotNow.attrs.r) * k - r0 * k0) < 1e-9); // same size on screen
  for (let i = 0; i < 20; i += 1) map.fire('wheel', { deltaY: -400, clientX: 500, clientY: 300 });
  assert.equal(g.attrs.transform.match(/scale\(([\d.]+)\)/)[1], '10');
  buttonsOf(app).find((b) => b.textContent === 'Reset').fire('click');
  assert.equal(g.attrs.transform, 'translate(0,0) scale(1)');
});

test('page display options (D46): All first, no Pause, no PW or All card, legend under the map, click details window', async () => {
  const opts = { disaster_number: 9999, pw_number: 1, initial_view: 'all', show_pause_button: false, show_pw_card: false, show_all_categories_card: false, legend_position: 'below_map', click_details: 'modal' };
  const { res } = await run(opts);
  assert.equal(res.structuredContent.initialView, 'ALL');
  assert.equal(res.structuredContent.display.clickDetails, 'modal');
  const { app } = runPage(res.content[1].resource.text);
  assert.equal(viewButton(app, 'All').getAttribute('aria-pressed'), 'true');
  assert.ok(!buttonsOf(app).some((b) => b.textContent === 'Pause' || b.textContent === 'Play'));
  const order = app.children.map((c) => c.className || c.tagName);
  assert.deepEqual(order, ['filter', 'map clickable', 'legend', 'cards', 'tablebox']);
  const cards = app.children[3];
  assert.equal(cards.children.length, 0);
  assert.equal(cards.style.display, 'none');
  assert.doesNotMatch(app.textContent, /PW 1 \(highlighted\)|All categories A\u2013G/);
  const circles = byTag(app, 'circle').filter((c) => !c.attrs.class.startsWith('halo'));
  assert.ok(circles.some((c) => c.attrs.class === 'hl'), 'the PW is still highlighted');
  const map = app.all((e) => e.className === 'map clickable')[0];
  const back = () => map.children.find((c) => c.className === 'mback');
  // click on an outlier dot -> window with the project details
  const dot = circles.find((c) => c.attrs.class === 'out');
  map.fire('pointerdown', { target: dot, clientX: 50, clientY: 50 });
  map.fire('pointerup', { clientX: 51, clientY: 50 });
  assert.ok(back(), 'window opened');
  const box = back().children[0];
  assert.equal(box.getAttribute('role'), 'dialog');
  const keys = box.children.filter((c) => c.className === 'row').map((r) => r.children[0].textContent);
  assert.deepEqual(keys, ['Title', 'Applicant', 'Category', 'Location', 'Amount', '\u03c3', 'Multiple of mean', 'Result', 'Category mean']);
  assert.match(box.textContent, /Flagged \(3 \u03c3 or more\)/);
  assert.match(box.textContent, /\$[0-9,]+\.[0-9]{2}/);
  // the X closes it
  box.children.find((c) => c.className === 'mx').fire('click');
  assert.equal(back(), undefined);
  // a drag does not open it
  map.fire('pointerdown', { target: dot, clientX: 50, clientY: 50 });
  map.fire('pointerup', { clientX: 90, clientY: 50 });
  assert.equal(back(), undefined);
  // click on a county with outliers; a press outside the window (on the backdrop) closes it
  const pd = pageDataOf(res.content[1].resource.text);
  const county = byTag(app, 'path').find((p) => p.choroplethCounty && p.choroplethCounty.f === '12005');
  map.fire('pointerdown', { target: county });
  map.fire('pointerup', {});
  assert.ok(back());
  assert.match(back().children[0].textContent, new RegExp(pd.map.counties.find((c) => c.f === '12005').n));
  map.fire('pointerdown', { target: back() });
  assert.equal(back(), undefined);
  assert.equal(map.style.minHeight, '');
  // county with no outliers
  const quiet = byTag(app, 'path').find((p) => p.choroplethCounty && p.choroplethCounty.f === '12009');
  map.fire('pointerdown', { target: quiet }); map.fire('pointerup', {});
  assert.match(back().children[0].textContent, /No cost outlier/);
  viewButton(app, 'A').fire('click'); // switching the view closes it
  assert.equal(back(), undefined);
});

test('page (D50): map_aspect_ratio sets the map box shape and the whole state fits inside, centred', async () => {
  const base = await run({ disaster_number: 9999 });
  const auto = pageDataOf(base.res.content[1].resource.text).map;
  assert.equal(base.res.structuredContent.display.mapAspectRatio, null);
  const unionOf = (m) => m.counties.reduce((u, c) => [Math.min(u[0], c.b[0]), Math.min(u[1], c.b[1]), Math.max(u[2], c.b[2]), Math.max(u[3], c.b[3])], [Infinity, Infinity, -Infinity, -Infinity]);
  const ua = unionOf(auto);
  for (const r of ['1:1', '16:9', '4:3', '5:3', '9:16', '3:4', '3:5']) {
    const [rw, rh] = r.split(':').map(Number);
    const { res } = await run({ disaster_number: 9999, map_aspect_ratio: r });
    assert.equal(res.structuredContent.display.mapAspectRatio, r);
    const pd = pageDataOf(res.content[1].resource.text);
    const { w, h } = pd.map;
    assert.deepEqual([w, h], [1000, Math.round(1000 * rh / rw)], r);
    const { app } = runPage(res.content[1].resource.text);
    const box = app.children.find((c) => /^map/.test(c.className));
    assert.equal(box.style.aspectRatio, `${w} / ${h}`, r);
    const u = unionOf(pd.map);
    assert.ok(u[0] >= 15.9 && u[1] >= 15.9 && u[2] <= w - 15.9 && u[3] <= h - 15.9, `${r}: the whole state is inside the box (16 padding)`);
    assert.ok(Math.abs((u[0] + u[2]) / 2 - w / 2) < 0.6 && Math.abs((u[1] + u[3]) / 2 - h / 2) < 0.6, `${r}: centred`);
    assert.ok(Math.abs(u[0] - 16) < 0.6 || Math.abs(u[1] - 16) < 0.6, `${r}: as large as fits (touches the padding on one axis)`);
    // same shape as the automatic layout, only scaled: width/height of the state unchanged in proportion
    assert.ok(Math.abs((u[2] - u[0]) / (u[3] - u[1]) - (ua[2] - ua[0]) / (ua[3] - ua[1])) < 0.02, `${r}: state not stretched`);
    assert.deepEqual(res.structuredContent.image && [res.structuredContent.image.width, res.structuredContent.image.height], base.res.structuredContent.image && [1000, 1000], 'the PNG stays square');
  }
});

test('page (D47): "Outliers in this view" is always collapsible and opens expanded', async () => {
  for (const args of [{ disaster_number: 9999, pw_number: 1 }, { disaster_number: 9999, pw_number: 1, initial_view: 'all', click_details: 'modal', legend_position: 'below_map' }]) {
    const { res } = await run(args);
    const { app } = runPage(res.content[1].resource.text);
    const box = byTag(app, 'details').find((d) => d.className === 'tablebox');
    assert.ok(box, 'a details element');
    assert.equal(box.getAttribute('open'), '');
    assert.equal(box.open, true);
    const [summary, body] = box.children;
    assert.equal(summary.tagName, 'SUMMARY');
    assert.match(summary.textContent, /^Outliers in this view \(\d+\)$/);
    assert.ok(byTag(body, 'table').length === 1);
    // the user collapses it; a view switch keeps it collapsed and updates the count
    box.open = false;
    viewButton(app, 'E').fire('click');
    assert.equal(box.open, false);
    assert.equal(box.children[0], summary);
    assert.equal(summary.textContent, 'Outliers in this view (2)');
    assert.equal(byTag(app, 'tr').length - 1, 2);
  }
});

test('page defaults keep the standard page: no click window', async () => {
  const { res } = await run({ disaster_number: 9999, pw_number: 1 });
  const { app } = runPage(res.content[1].resource.text);
  const map = app.all((e) => e.className === 'map')[0];
  const dot = byTag(app, 'circle').find((c) => c.attrs.class === 'out');
  map.fire('pointerdown', { target: dot }); map.fire('pointerup', {});
  assert.ok(!map.children.some((c) => c.className === 'mback'));
  assert.ok(app.textContent.includes('PW 1'));
});

test('page auto-fit: one outlier is centred on its county; Statewide outliers do not move the fit', async () => {
  const one = PROJECTS.map((p) => (p.pw === 2 ? { ...p, sigma: 1 } : p)); // PW 2 drops below the threshold
  const withSw = [...one, project(9, 'A', 140, 4.0, 'STATEWIDE')]; // view A: PW 1 in 12005 + Statewide PW 9
  const { res } = await run({ disaster_number: 9999 }, files({ [`${ROOT}/snapshots/2026-11-06/disasters/9999.json`]: doc(withSw) }));
  const html = res.content[1].resource.text;
  const pd = pageDataOf(html);
  const { app } = runPage(html);
  assert.equal(pd.initialView, 'ALL');
  viewButton(app, 'A').fire('click');
  assert.equal(byTag(app, 'circle').filter((c) => c.attrs.class === 'out sw').length, 1); // the Statewide ring is drawn ...
  const b = pd.map.counties.find((c) => c.f === '12005').b;
  const [zx, zy, zk] = zoomOf(app); // ... but the fit is the one county only
  const bw = Math.max(b[2] - b[0], pd.map.w * 0.08); const bh = Math.max(b[3] - b[1], pd.map.h * 0.08);
  assert.ok(near(zk, Math.max(1, Math.min(10, 0.7 * Math.min(pd.map.w / bw, pd.map.h / bh)))));
  assert.ok(zk > 1);
  assert.ok(near(zx + zk * (b[0] + b[2]) / 2, pd.map.w / 2) && near(zy + zk * (b[1] + b[3]) / 2, pd.map.h / 2), 'the county is centred');
  buttonsOf(app).find((x) => x.textContent === 'Reset').fire('click');
  assert.deepEqual(zoomOf(app), [0, 0, 1]); // Reset = whole state
});

test('page without county shapes: notice, no map, outliers still listed', async () => {
  const noGeo = files();
  delete noGeo[`${ROOT}/geo/v1/states/12.json`];
  const { res, tracer } = await run({ disaster_number: 9999 }, noGeo);
  assert.equal(res.structuredContent.map.drawn, false);
  assert.match(res.content[0].text, /No county map: no county shapes are stored for state FIPS 12 yet/);
  const { app } = runPage(res.content[1].resource.text);
  assert.equal(byTag(app, 'svg').length, 0);
  assert.match(app.all((e) => e.className === 'notice')[0].text, /cannot be drawn/);
  assert.deepEqual(app.children.map((c) => c.className || c.tagName), ['filter', 'notice', 'cards', 'tablebox']); // D49: buttons first
  assert.equal(byTag(app, 'tr').length - 1, 4);
  assert.equal(tracer.trace.call.map.statesMissing[0], '12');
});

test('shape aliases (crosswalk RECODE) move an obsolete FEMA code onto today\'s county', async () => {
  const geo = { ...GEO_FL, aliases: { 12099: '12009' }, source: 'test boundaries 2025' };
  const { res, tracer } = await run({ disaster_number: 9999 }, files({ [`${ROOT}/geo/v1/states/12.json`]: geo }));
  assert.equal(tracer.trace.call.map.recodedProjects, 1);
  assert.deepEqual(res.structuredContent.map.countiesNotInShapes, []);
  const p8 = res.structuredContent.outliers.find((o) => o.pw === 8);
  assert.deepEqual([p8.countyFips, p8.femaCountyFips], ['12009', '12099']);
  assert.equal(res.structuredContent.countyOutliers['12009'], 1);
  assert.deepEqual(res.structuredContent.map.boundarySources, ['test boundaries 2025']);
  assert.doesNotMatch(res.content[1].resource.text, /County boundaries:/); // D48: not in the page
});

test('real export and real county shapes render in the page script', { skip: !(live && fs.existsSync(`${LIVE}/geo/v1/states/06.json`)) && 'shapes not mounted here' }, async () => {
  const readFile = async (p) => { try { return fs.readFileSync(p); } catch (e) { const err = new Error(String(e)); err.status = e.code === 'ENOENT' ? 404 : 500; throw err; } };
  const tracer = fakeTracer();
  const res = await runGenerateChoropleth({ disaster_number: 4856, pw_number: 2 }, {}, tracer, { readFile, root: LIVE });
  assert.equal(res.structuredContent.map.drawn, true);
  const ca = JSON.parse(fs.readFileSync(`${LIVE}/geo/v1/states/06.json`, 'utf8'));
  const { app } = runPage(res.content[1].resource.text);
  assert.equal(byTag(app, 'path').length, ca.counties.length); // 58 California counties
  viewButton(app, 'All').fire('click');
  assert.equal(byTag(app, 'circle').filter((c) => !c.attrs.class.startsWith('halo')).length, 5 + 1); // 5 outliers + highlight ring
  assert.equal(byTag(app, 'circle').filter((c) => c.attrs.class.startsWith('halo')).length, 5 + 1);
  const la = byTag(app, 'path').find((p) => p.children[0].textContent.startsWith('Los Angeles County'));
  assert.ok(['#ffbe2e', '#5e9732'].includes(la.attrs.fill));
  assert.deepEqual(byTag(app, 'text').map((t) => t.textContent), ['Los Angeles']);
  assert.equal(tracer.trace.call.map.shadeConflicts, 0);
});

// ---------------------------------------------------------------- the tool

test('tool: result shape and error results', async () => {
  const { res, tracer } = await run({ disaster_number: 9999, pw_number: 2, sigma_threshold: 3 });
  assert.equal(res.isError, undefined);
  assert.deepEqual(res.content.map((c) => c.type), ['text', 'resource', 'text']);
  assert.equal(res.content[1].resource.mimeType, 'text/html');
  assert.equal(res.content[1].resource.uri, 'ui://lancelot-beta/choropleth/call-20261106T000000Z-abc123.html');
  const sc = res.structuredContent;
  assert.deepEqual(JSON.parse(res.content[2].text), sc);
  assert.deepEqual([sc.status, sc.tool, sc.totals.outliers, sc.highlight.pw, sc.highlight.flagged], ['OK', CHOROPLETH_TOOL_NAME, 4, 2, true]);
  assert.ok(!JSON.stringify(sc).includes('<!DOCTYPE'), 'no HTML in the JSON');
  assert.equal(tracer.outcome, 'OK');
  for (const [args, code] of [[{}, 'INVALID_INPUT'], [{ disaster_number: 1 }, 'DISASTER_NOT_LOADED'], [{ disaster_number: 9999, as_of: '2020-01-01' }, 'SNAPSHOT_NOT_FOUND'],
    [{ disaster_number: 9999, pw_number: 404 }, 'PW_NOT_FOUND']]) {
    const r = await run(args);
    assert.equal(r.res.isError, true);
    assert.equal(errorOf(r.res).errorCode, code);
    assert.equal(r.tracer.outcome, code);
  }
  const broken = await runGenerateChoropleth({ disaster_number: 9999 }, {}, fakeTracer(), { readFile: async () => { throw new Error('boom'); }, root: ROOT });
  assert.equal(errorOf(broken).errorCode, 'DATA_UNAVAILABLE');
});

test('tool: widget data never carries banned fields', async () => {
  const { res } = await run({ disaster_number: 9999 });
  const html = res.content[1].resource.text;
  for (const banned of ['hash', 'gmProjectId', 'federalShareObligated', 'totalObligated', 'coordinates', 'location_note']) assert.ok(!html.includes(banned), banned);
  const data = buildWidgetData({ analysis: analyze(doc(PROJECTS), { sigmaThreshold: 3 }), map: { drawn: false, reason: 'x' }, meta: { disasterNumber: 9999, states: ['FL'], snapshotDate: '2026-11-06', newestLastRefresh: null } });
  assert.equal(data.map, null);
  assert.ok(buildWidgetHtml(data).length < 100_000);
});
