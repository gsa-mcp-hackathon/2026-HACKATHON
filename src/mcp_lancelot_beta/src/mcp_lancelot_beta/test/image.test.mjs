// generate_choropleth square image (BUILD_PLAN D44): title layout, SVG for the
// map and the logo-only fallback, and the MCP result. Rasterizing is faked (no
// @resvg/resvg-js here); the deployed startup self-test renders real PNGs.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const M = (name) => new URL(`../lib/tools/choropleth/lib/${name}`, import.meta.url).href;
const I = await import(M('image.mjs'));
const { runGenerateChoropleth } = await import(M('tool.mjs'));

const LIVE = '/Volumes/users/tom_jacobson/choropleth_data';
const measure = I.estimateMeasure;
const LOGO = { dataUri: 'data:image/png;base64,AAAA', width: 2048, height: 724 };

function fakePng(w = 1000, h = 1000) {
  const b = Buffer.alloc(33);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(b, 0);
  b.writeUInt32BE(13, 8); b.write('IHDR', 12, 'ascii'); b.writeUInt32BE(w, 16); b.writeUInt32BE(h, 20);
  return b;
}
const sq = (x, y, s = 1) => [[[[x, y], [x + s, y], [x + s, y + s], [x, y + s], [x, y]]]];
const GEO = { schemaVersion: 1, stateFips: '12', counties: [1, 2, 3, 4].map((i) => ({ fips: `1200${i}`, name: `C${i}`, polygons: sq(-82 + i, 28) })), aliases: { 12099: '12004' } };
function decl(over = {}) {
  return { schemaVersion: 1, disasterNumber: 9999, status: 'OK', stateFips: '12', title: 'DR-9999-FL Hurricane Test', affectedFips: ['12001', '12002'], extraAreas: [], ...over };
}
const paths = (svg, color) => {
  const m = svg.match(new RegExp(`<g fill="${color}"[^>]*>(.*?)</g>`));
  return m ? (m[1].match(/<path /g) || []).length : 0;
};

test('title: one line at 34 px down to 26 px, then two balanced lines, then ellipsis', () => {
  const L = I.headerLayout('DR-4673-FL Hurricane Ian', measure, LOGO);
  assert.equal(L.fontSize, 34); assert.equal(L.lines.length, 1);
  assert.ok(Math.abs(L.logoW - 56 * 2048 / 724) < 1e-9);
  assert.equal(L.headerH, 56); // one 34 px line (40.8 px) is shorter than the 56 px logo
  const long = I.headerLayout('DR-4856-CA Wildfires and Straight-line Winds', measure, LOGO);
  assert.ok(long.fontSize >= 26 && long.fontSize <= 34);
  const two = I.headerLayout('DR-4861-WV Severe Storm, Straight-line Winds, Flooding, Landslides, and Mudslides', measure, LOGO);
  assert.equal(two.lines.length, 2);
  assert.ok(two.lines.every((l) => measure(l, two.fontSize) <= two.avail));
  assert.equal(two.lines.join(' '), 'DR-4861-WV Severe Storm, Straight-line Winds, Flooding, Landslides, and Mudslides');
  // a taller header shrinks the map: map top = margin + header + gap
  for (const x of [L, long, two]) assert.equal(x.mapTop, 40 + x.headerH + 20);
  assert.ok(long.headerH > L.headerH && long.mapTop > L.mapTop);
  const huge = I.fitTitle(Array(60).fill('Word').join(' '), measure, 700);
  assert.equal(huge.truncated, true);
  assert.equal(huge.lines.length, 2);
  assert.ok(huge.lines[1].endsWith('\u2026'));
  assert.ok(huge.lines.every((l) => measure(l, huge.fontSize) <= 700));
});

test('rampStep: log scale 1..4 against the busiest county, 0 for none', () => {
  assert.equal(I.RAMP.length, 4);
  assert.deepEqual([0, 1, 2, 5, 20, 100].map((n) => I.rampStep(n, 100)), [0, 1, 1, 2, 3, 4]);
  assert.equal(I.rampStep(1, 1), 4);
  assert.equal(I.rampStep(3, 0), 0);
  for (let n = 1; n < 200; n += 1) assert.ok(I.rampStep(n, 200) <= I.rampStep(n + 1, 200)); // never darker for fewer
});

test('map: outlier solid red, tint by project count, white for none, aliases, 1000x1000, escaped title', () => {
  // 12001: 1 project; 12002: 100 projects; 12099 -> 12004 by alias: 3 projects, one an outlier; 12003: none.
  const r = I.buildImageSvg({ title: 'DR-1-XX A <b>&</b> "test"', decl: decl({ extraAreas: [{ name: 'Tribe', polygons: sq(-80.5, 28.2, 0.3) }] }), geo: GEO, logo: LOGO, measure, countyProjects: { 12001: 1, 12002: 100, 12099: 3, 99001: 4 }, countyOutliers: { 12099: 1 } });
  assert.equal(r.mapDrawn, true);
  assert.equal(r.reason, null);
  assert.match(r.svg, /^<svg [^>]*width="1000" height="1000" viewBox="0 0 1000 1000"/);
  assert.equal(paths(r.svg, I.OUTLIER), 1); // 12004 (via alias), outlier beats its count
  assert.match(r.svg, new RegExp(`<g fill="${I.OUTLIER}" stroke="${I.OUTLIER_STROKE}"`));
  assert.equal(paths(r.svg, I.NONE), 1); // 12003
  assert.equal(paths(r.svg, I.RAMP[0]), 1); // 12001, 1 project
  assert.equal(paths(r.svg, I.RAMP[3]), 1); // 12002, the busiest
  assert.equal((r.svg.match(/<path /g) || []).length, 4); // tribal areas are not drawn
  assert.ok(!r.svg.includes('#c62828') && !r.svg.includes('#e6e6e6'));
  assert.deepEqual([r.counts.countiesWithProjects, r.counts.outlierCounties, r.counts.maxProjects, r.counts.projectsDrawn], [3, 1, 100, 104]);
  assert.deepEqual(r.counts.countiesNotInShapes, ['99001']);
  assert.deepEqual(r.scale.steps.map((s) => [s.counties, s.min, s.max]), [[1, 1, 1], [0, null, null], [0, null, null], [1, 100, 100]]);
  assert.ok(r.svg.includes('DR-1-XX A &lt;b&gt;&amp;&lt;/b&gt; &quot;test&quot;'));
  assert.ok(!r.svg.includes('<b>'));
  assert.ok(!/legend/i.test(r.svg));
  // every coordinate stays inside the margins
  for (const [, x, y] of r.svg.matchAll(/[ML](-?[\d.]+) (-?[\d.]+)/g)) {
    assert.ok(+x >= 39.9 && +x <= 960.1 && +y >= r.layout.mapTop - 0.1 && +y <= 960.1, `${x},${y}`);
  }
});

test('fallback: logo replaces the map, title centered, call reasons', () => {
  const cases = [
    [{ decl: null, geo: GEO }, /no FEMA declaration area file/],
    [{ decl: decl({ status: 'PARSE_FAILED' }), geo: GEO }, /could not be used \(PARSE_FAILED\)/],
    [{ decl: decl(), geo: null }, /no county shapes are stored for state FIPS 12/],
    [{ decl: decl(), geo: GEO, countyProjects: {} }, /no PA project in categories A-G is located in a county of this state/],
    [{ decl: decl(), geo: GEO, countyProjects: { 99001: 3 } }, /no PA project/],
  ];
  for (const [inp, re] of cases) {
    const r = I.buildImageSvg({ title: 'EM-3553-DC 59th Presidential Inauguration', logo: LOGO, measure, countyProjects: { 12001: 2 }, ...inp });
    assert.equal(r.mapDrawn, false);
    assert.match(r.reason, re);
    assert.match(r.svg, /text-anchor="middle"/);
    assert.match(r.svg, /<image x="150" [^>]*width="700"/);
    assert.ok(!r.svg.includes('<path'));
  }
});

test('MCP result: image item after the widget, structured.image matches the PNG', async () => {
  const readFile = async (p) => { try { return fs.readFileSync(p); } catch (e) { const err = new Error(String(e)); err.status = e.code === 'ENOENT' ? 404 : 500; throw err; } };
  const files = []; const tracer = { runId: 'r1', debug: true, trace: {}, setOutcome() {}, errorMessage: String, addRunFile: (n, d) => files.push([n, d]) };
  const png = fakePng();
  let svgSeen = null;
  const res = await runGenerateChoropleth({ disaster_number: 4673 }, {}, tracer, { readFile, root: LIVE, measure, loadLogo: () => LOGO, rasterize: async (svg) => { svgSeen = svg; return png; } });
  assert.equal(res.isError, undefined);
  assert.deepEqual(res.content.map((c) => c.type), ['text', 'resource', 'image', 'text']);
  assert.equal(res.content[2].mimeType, 'image/png');
  assert.deepEqual(Buffer.from(res.content[2].data, 'base64'), png);
  const im = res.structuredContent.image;
  assert.equal(im.sha256, (await import('node:crypto')).createHash('sha256').update(png).digest('hex'));
  assert.deepEqual([im.width, im.height, im.mapDrawn, im.title], [1000, 1000, true, 'DR-4673-FL Hurricane Ian']);
  assert.deepEqual([im.countiesWithProjects, im.outlierCounties, im.maxProjects, im.statewideProjects], [47, 11, 640, 361]);
  assert.equal(im.outlierCounties, res.structuredContent.totals.outlierCounties);
  assert.equal(JSON.parse(res.content[3].text).image.sha256, im.sha256);
  assert.match(res.content[0].text, /Square image attached \(1000x1000 PNG\): 47 counties shaded by PA project count \(up to 640 in one county\), 11 with a cost outlier in solid red, counties with no project white; 361 Statewide projects not on the map\./);
  assert.ok(svgSeen.includes('Hurricane Ian'));
  assert.equal(paths(svgSeen, I.OUTLIER), 11);
  assert.deepEqual(files.map((f) => f[0]), ['widget.html', 'image.png']);
  assert.deepEqual(tracer.trace.call.response.contentTypes, ['text', 'resource', 'image', 'text']);
});

test('the four D44 preview disasters: counties with projects, outlier counties, busiest county (live volume)', async () => {
  const readFile = async (p) => { try { return fs.readFileSync(p); } catch (e) { const err = new Error(String(e)); err.status = e.code === 'ENOENT' ? 404 : 500; throw err; } };
  // latest snapshot as of 2026-11-17; checked against a direct count of the snapshot projects (A-G, COUNTY)
  const want = { 4856: [1, 1, 262], 4673: [47, 11, 640], 4671: [78, 18, 148], 4611: [34, 8, 441] };
  for (const [n, exp] of Object.entries(want)) {
    const tracer = { runId: `p${n}`, debug: false, trace: {}, setOutcome() {}, errorMessage: String, addRunFile() {} };
    const res = await runGenerateChoropleth({ disaster_number: Number(n) }, {}, tracer, { readFile, root: LIVE, measure, loadLogo: () => LOGO, rasterize: async () => fakePng() });
    const im = res.structuredContent.image;
    assert.equal(im.mapDrawn, true, n);
    assert.deepEqual([im.countiesWithProjects, im.outlierCounties, im.maxProjects], exp, n);
    assert.deepEqual(im.countiesNotInShapes, [], n);
  }
});

test('EM-3553 (Statewide projects only) keeps the logo-only image (live volume)', async () => {
  const readFile = async (p) => { try { return fs.readFileSync(p); } catch (e) { const err = new Error(String(e)); err.status = e.code === 'ENOENT' ? 404 : 500; throw err; } };
  const tracer = { runId: 'em', debug: false, trace: {}, setOutcome() {}, errorMessage: String, addRunFile() {} };
  const res = await runGenerateChoropleth({ disaster_number: 3553 }, {}, tracer, { readFile, root: LIVE, measure, loadLogo: () => LOGO, rasterize: async () => fakePng() });
  assert.equal(res.structuredContent.image.mapDrawn, false);
  assert.match(res.structuredContent.image.reason, /no PA project in categories A-G is located in a county/);
});

test('a rasterizer failure leaves the call OK with image null and imageError', async () => {
  const readFile = async (p) => { try { return fs.readFileSync(p); } catch (e) { const err = new Error(String(e)); err.status = e.code === 'ENOENT' ? 404 : 500; throw err; } };
  const tracer = { runId: 'r2', debug: false, trace: {}, setOutcome() {}, errorMessage: String, addRunFile() {} };
  const res = await runGenerateChoropleth({ disaster_number: 4856 }, {}, tracer, { readFile, root: LIVE, measure, loadLogo: () => LOGO, rasterize: async () => { throw new Error('boom'); } });
  assert.equal(res.isError, undefined);
  assert.deepEqual(res.content.map((c) => c.type), ['text', 'resource', 'text']);
  assert.equal(res.structuredContent.image, null);
  assert.match(res.structuredContent.imageError, /boom/);
  assert.match(res.content[0].text, /No square image: boom\./);
});

test('pngSize and the committed logo asset', () => {
  assert.deepEqual(I.pngSize(fakePng(3, 4)), { width: 3, height: 4 });
  assert.equal(I.pngSize(Buffer.from('nope')), null);
  const logo = I.loadLogo();
  assert.deepEqual([logo.width, logo.height], [2048, 724]);
  assert.ok(logo.dataUri.startsWith('data:image/png;base64,iVBOR'));
});
