// The Choropleth square image (BUILD_PLAN D44, revised 2026-11-17): a 1000 x 1000
// PNG choropleth of the declaration state's counties, with the FEMA logo left of
// FEMA's official title. Fill per county: solid dhs-red when it has a cost
// outlier; else a dhs-red tint (4 steps, log scale against the busiest county)
// by its number of PA projects in categories A-G; else white. No legend (user,
// 2026-11-17). When there is nothing to draw (no declaration file, no county
// shapes, no county with a project), the title sits at the top and a large logo
// replaces the map; the call is still OK.
//
// Layout and SVG are pure (measure and logo are injected, so tests need no
// packages). Rasterizing runs in our own child process (imageRasterWorker.mjs).
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { prepareCounties } from './geo.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
export const LOGO_PATH = path.join(__dirname, '..', '..', '..', '..', 'assets', 'fema-logo.png');
const WORKER_PATH = path.join(__dirname, 'imageRasterWorker.mjs');

export const SIZE = 1000;
export const MARGIN = 40;
export const LOGO_H = 56;
export const GAP = 16;
export const MAP_GAP = 20;
export const TITLE_MAX = 34;
export const TITLE_MIN_ONE_LINE = 26;
export const TITLE_MIN_TWO_LINES = 18;
export const LINE = 1.2;
const CAP = 0.73; // DejaVu Sans Bold cap height / em, for vertical centering
export const FALLBACK_LOGO_W = 700; // 70% of the image
// DHS palette only (docs/DHS_COLOR_PALETTE.md).
export const OUTLIER = '#c41230'; // dhs-red: county with a cost outlier
export const OUTLIER_STROKE = '#660919'; // dhs-red-70
export const RAMP = ['#f6d9de', '#eebdc5', '#e08493', '#d24b62']; // dhs-red-15, -20, -30, -40: fewer -> more projects
export const NONE = '#ffffff'; // no project
export const BORDER = '#c0c2c4'; // dhs-gray county borders (white counties stay visible)
export const FONT_FAMILY = 'DejaVu Sans';
const RASTER_TIMEOUT_MS = 20000;

export function xmlEscape(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;')
    // XML 1.0 forbids most control characters even when escaped.
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '');
}

// ---------------------------------------------------------------- measure

// Character-count estimate for DejaVu Sans Bold (average advance ~0.69 em).
export function estimateMeasure(text, fontSize) {
  return String(text).length * fontSize * 0.69;
}

let measurePromise = null;
// -> { measure(text, size) -> px, source }. opentype.js + DejaVuSans-Bold.ttf, else the estimate.
export function loadMeasure() {
  if (!measurePromise) {
    measurePromise = (async () => {
      try {
        const { default: opentype } = await import('opentype.js');
        const dir = path.dirname(require.resolve('dejavu-fonts-ttf/package.json'));
        const file = findFile(dir, /^DejaVuSans-Bold\.ttf$/i);
        if (!file) throw new Error('DejaVuSans-Bold.ttf not found');
        const font = opentype.loadSync(file);
        return { measure: (text, size) => font.getAdvanceWidth(String(text), size), source: 'opentype:DejaVuSans-Bold' };
      } catch (err) {
        return { measure: estimateMeasure, source: `estimate (${String(err && err.message ? err.message : err).slice(0, 120)})` };
      }
    })();
  }
  return measurePromise;
}

function findFile(dir, re) {
  const stack = [dir];
  while (stack.length) {
    const d = stack.pop();
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const full = path.join(d, e.name);
      if (e.isDirectory()) stack.push(full);
      else if (re.test(e.name)) return full;
    }
  }
  return null;
}

// ---------------------------------------------------------------- logo

export function pngSize(buf) {
  if (!Buffer.isBuffer(buf) || buf.length < 24 || buf.readUInt32BE(0) !== 0x89504e47 || buf.toString('ascii', 12, 16) !== 'IHDR') return null;
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

let logoCache = null;
// -> { dataUri, width, height, bytes }; throws if the asset is missing.
export function loadLogo(file = LOGO_PATH) {
  if (logoCache && logoCache.file === file) return logoCache.logo;
  const buf = fs.readFileSync(file);
  const size = pngSize(buf);
  if (!size) throw new Error(`${file} is not a PNG`);
  const logo = { dataUri: `data:image/png;base64,${buf.toString('base64')}`, ...size, bytes: buf.length };
  logoCache = { file, logo };
  return logo;
}

// ---------------------------------------------------------------- title layout

function bestSplit(words, measure, size) {
  let best = null;
  for (let i = 1; i < words.length; i += 1) {
    const lines = [words.slice(0, i).join(' '), words.slice(i).join(' ')];
    const w = Math.max(measure(lines[0], size), measure(lines[1], size));
    if (!best || w < best.w) best = { lines, w };
  }
  return best;
}

function ellipsize(text, measure, size, avail) {
  const words = text.split(' ');
  while (words.length > 1 && measure(`${words.join(' ')}\u2026`, size) > avail) words.pop();
  let s = `${words.join(' ')}\u2026`;
  while (s.length > 2 && measure(s, size) > avail) s = `${s.slice(0, -2)}\u2026`;
  return s;
}

// One line from 34 down to 26 px; else two balanced lines from 34 down to 18 px;
// else two lines at 18 px with the second ellipsized.
export function fitTitle(title, measure, avail) {
  const text = String(title || '').replace(/\s+/g, ' ').trim();
  for (let s = TITLE_MAX; s >= TITLE_MIN_ONE_LINE; s -= 1) {
    if (measure(text, s) <= avail) return { fontSize: s, lines: [text], truncated: false };
  }
  const words = text.split(' ');
  if (words.length > 1) {
    for (let s = TITLE_MAX; s >= TITLE_MIN_TWO_LINES; s -= 1) {
      const b = bestSplit(words, measure, s);
      if (b.w <= avail) return { fontSize: s, lines: b.lines, truncated: false };
    }
  }
  const s = TITLE_MIN_TWO_LINES;
  if (words.length === 1) return { fontSize: s, lines: [ellipsize(text, measure, s, avail)], truncated: true };
  // First line as full as fits, the rest ellipsized.
  let i = words.length - 1;
  while (i > 1 && measure(words.slice(0, i).join(' '), s) > avail) i -= 1;
  const first = words.slice(0, i).join(' ');
  return { fontSize: s, lines: [measure(first, s) > avail ? ellipsize(first, measure, s, avail) : first, ellipsize(words.slice(i).join(' '), measure, s, avail)], truncated: true };
}

export function headerLayout(title, measure, logo) {
  const logoW = LOGO_H * (logo.width / logo.height);
  const textX = MARGIN + logoW + GAP;
  const avail = SIZE - MARGIN - textX;
  const t = fitTitle(title, measure, avail);
  const blockH = t.lines.length * t.fontSize * LINE;
  const headerH = Math.max(LOGO_H, blockH);
  return { ...t, logoW, logoH: LOGO_H, textX, avail, blockH, headerH, mapTop: MARGIN + headerH + MAP_GAP };
}

export function fallbackLayout(title, measure) {
  const avail = SIZE - 2 * MARGIN;
  const t = fitTitle(title, measure, avail);
  const blockH = t.lines.length * t.fontSize * LINE;
  return { ...t, avail, blockH, headerH: blockH };
}

const r1 = (v) => Math.round(v * 10) / 10;

// County project count -> ramp step 1..RAMP.length (log scale against the largest count); 0 for none.
export function rampStep(n, max) {
  if (!(n > 0) || !(max > 0)) return 0;
  return Math.min(RAMP.length, Math.max(1, Math.ceil((RAMP.length * Math.log1p(n)) / Math.log1p(max))));
}

function textLines(lines, fontSize, x, top, anchor) {
  const lh = fontSize * LINE;
  return lines.map((line, i) => {
    const y = top + i * lh + (lh + CAP * fontSize) / 2;
    return `<text x="${r1(x)}" y="${r1(y)}" font-family="${FONT_FAMILY}" font-weight="bold" font-size="${fontSize}" fill="#1a1a1a" text-anchor="${anchor}">${xmlEscape(line)}</text>`;
  }).join('');
}

// ---------------------------------------------------------------- map

function lonFor(lon, state) {
  return state === '02' && lon > 0 ? lon - 360 : lon;
}

function validRing(ring) {
  return Array.isArray(ring) && ring.length >= 4 && ring.every((p) => Array.isArray(p) && Number.isFinite(p[0]) && Number.isFinite(p[1]));
}

function extraShapes(extraAreas, state) {
  const out = [];
  for (const a of extraAreas || []) {
    if (!a || !Array.isArray(a.polygons)) continue;
    const polygons = a.polygons
      .map((poly) => (Array.isArray(poly) ? poly.filter(validRing).map((ring) => ring.map(([lon, lat]) => [lonFor(lon, state), lat])) : []))
      .filter((poly) => poly.length);
    if (polygons.length) out.push({ name: typeof a.name === 'string' ? a.name : '', polygons });
  }
  return out;
}

// Equirectangular, x scaled by cos(mid latitude), fitted and centered in the box.
export function fitProjection(shapes, box) {
  let minLon = Infinity; let maxLon = -Infinity; let minLat = Infinity; let maxLat = -Infinity;
  for (const s of shapes) for (const poly of s.polygons) for (const ring of poly) for (const [lon, lat] of ring) {
    if (lon < minLon) minLon = lon; if (lon > maxLon) maxLon = lon;
    if (lat < minLat) minLat = lat; if (lat > maxLat) maxLat = lat;
  }
  if (!Number.isFinite(minLon)) return null;
  const kx = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
  const w = Math.max((maxLon - minLon) * kx, 1e-6);
  const h = Math.max(maxLat - minLat, 1e-6);
  const scale = Math.min(box.w / w, box.h / h);
  const ox = box.x + (box.w - w * scale) / 2;
  const oy = box.y + (box.h - h * scale) / 2;
  return ([lon, lat]) => [ox + (lon - minLon) * kx * scale, oy + (maxLat - lat) * scale];
}

// Rings -> path data, dropping points closer than 0.35 px to the last kept one.
export function pathData(polygons, project) {
  let d = '';
  for (const poly of polygons) {
    for (const ring of poly) {
      let last = null; let n = 0; let part = '';
      for (const pt of ring) {
        const [x, y] = project(pt);
        if (last && Math.abs(x - last[0]) < 0.35 && Math.abs(y - last[1]) < 0.35) continue;
        part += `${n === 0 ? 'M' : 'L'}${r1(x)} ${r1(y)}`;
        last = [x, y]; n += 1;
      }
      if (n >= 3) d += `${part}Z`;
    }
  }
  return d;
}

// Sum a { fips: n } map after the shape crosswalk (obsolete FEMA code -> today's shape).
function byShape(obj, aliases) {
  const m = new Map();
  for (const [f, n] of Object.entries(obj || {})) {
    if (!(n > 0)) continue;
    const k = aliases[f] || f;
    m.set(k, (m.get(k) || 0) + n);
  }
  return m;
}

// decl: the declarations/v1 file or null (title and state); geo: the state's geo/v1 file or null;
// countyProjects / countyOutliers: { countyFips: n } from analysis (projects in categories A-G).
// -> { svg, mapDrawn, reason, title, layout, counts, scale }
export function buildImageSvg({ title, decl, geo, logo, measure, countyProjects = {}, countyOutliers = {} }) {
  const state = decl && decl.stateFips;
  const counties = geo ? prepareCounties({ [state]: geo }) : [];
  const aliases = geo && geo.aliases && typeof geo.aliases === 'object' ? geo.aliases : {};
  const projects = byShape(countyProjects, aliases);
  const outliers = byShape(countyOutliers, aliases);
  const inShapes = new Set(counties.map((c) => c.fips));
  const max = counties.reduce((m, c) => Math.max(m, projects.get(c.fips) || 0), 0);
  const counts = {
    counties: counties.length,
    countiesWithProjects: counties.filter((c) => projects.has(c.fips)).length,
    outlierCounties: counties.filter((c) => outliers.has(c.fips)).length,
    projectsDrawn: counties.reduce((s, c) => s + (projects.get(c.fips) || 0), 0),
    maxProjects: max,
    countiesNotInShapes: [...projects.keys()].filter((f) => !inShapes.has(f)).sort(),
  };

  let reason = null;
  if (!decl) reason = 'no FEMA declaration area file for this disaster';
  else if (decl.status !== 'OK') reason = `the FEMA declaration area file could not be used (${decl.status})`;
  else if (!counties.length) reason = `no county shapes are stored for state FIPS ${state || '(unknown)'}`;
  else if (!counts.countiesWithProjects) reason = 'no PA project in categories A-G is located in a county of this state';

  const head = '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    + `width="${SIZE}" height="${SIZE}" viewBox="0 0 ${SIZE} ${SIZE}"><rect width="${SIZE}" height="${SIZE}" fill="#ffffff"/>`;

  if (reason) {
    const L = fallbackLayout(title, measure);
    const lw = FALLBACK_LOGO_W;
    const lh = lw * (logo.height / logo.width);
    const areaTop = MARGIN + L.headerH + MAP_GAP;
    const ly = areaTop + (SIZE - MARGIN - areaTop - lh) / 2;
    const svg = head + textLines(L.lines, L.fontSize, SIZE / 2, MARGIN, 'middle')
      + `<image x="${r1((SIZE - lw) / 2)}" y="${r1(ly)}" width="${r1(lw)}" height="${r1(lh)}" href="${logo.dataUri}" xlink:href="${logo.dataUri}"/></svg>`;
    return { svg, mapDrawn: false, reason, title, layout: { kind: 'fallback', fontSize: L.fontSize, lines: L.lines.length, truncated: L.truncated }, counts, scale: null };
  }

  const L = headerLayout(title, measure, logo);
  const box = { x: MARGIN, y: L.mapTop, w: SIZE - 2 * MARGIN, h: SIZE - MARGIN - L.mapTop };
  const project = fitProjection(counties, box);
  const fills = [NONE, ...RAMP].map(() => []); // index = ramp step (0 = no project)
  const red = [];
  const steps = RAMP.map((color, i) => ({ step: i + 1, color, min: null, max: null, counties: 0 }));
  for (const c of counties) {
    const p = `<path d="${pathData(c.polygons, project)}"/>`;
    if (outliers.has(c.fips)) { red.push(p); continue; }
    const n = projects.get(c.fips) || 0;
    const k = rampStep(n, max);
    fills[k].push(p);
    if (k) {
      const s = steps[k - 1];
      s.counties += 1;
      s.min = s.min === null ? n : Math.min(s.min, n);
      s.max = s.max === null ? n : Math.max(s.max, n);
    }
  }
  const fillColors = [NONE, ...RAMP];
  const svg = head
    + `<image x="${MARGIN}" y="${r1(MARGIN + (L.headerH - L.logoH) / 2)}" width="${r1(L.logoW)}" height="${L.logoH}" href="${logo.dataUri}" xlink:href="${logo.dataUri}"/>`
    + textLines(L.lines, L.fontSize, L.textX, MARGIN + (L.headerH - L.blockH) / 2, 'start')
    + `<g fill-rule="evenodd" stroke-linejoin="round"><g stroke="${BORDER}" stroke-width="0.75">`
    + fills.map((ps, k) => (ps.length ? `<g fill="${fillColors[k]}">${ps.join('')}</g>` : '')).join('')
    + '</g>'
    + (red.length ? `<g fill="${OUTLIER}" stroke="${OUTLIER_STROKE}" stroke-width="1.5">${red.join('')}</g>` : '')
    + '</g></svg>';
  const scale = {
    kind: 'log', maxProjects: max, outlier: OUTLIER, none: NONE,
    rule: 'solid dhs-red if the county has a cost outlier; else dhs-red tint step ceil(4 * ln(1 + n) / ln(1 + max)) for n PA projects (categories A-G); else white',
    steps,
  };
  return { svg, mapDrawn: true, reason: null, title, layout: { kind: 'map', fontSize: L.fontSize, lines: L.lines.length, truncated: L.truncated, mapTop: r1(L.mapTop) }, counts, scale };
}

// ---------------------------------------------------------------- raster

export function rasterize(svg, { timeoutMs = RASTER_TIMEOUT_MS } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [WORKER_PATH, String(SIZE)], { stdio: ['pipe', 'pipe', 'pipe'] });
    const out = []; const err = [];
    const timer = setTimeout(() => { child.kill('SIGKILL'); }, timeoutMs);
    child.stdout.on('data', (c) => out.push(c));
    child.stderr.on('data', (c) => err.push(c));
    child.on('error', (e) => { clearTimeout(timer); reject(e); });
    child.on('close', (code, signal) => {
      clearTimeout(timer);
      if (signal) return reject(new Error(`image rasterizer killed by ${signal}${signal === 'SIGKILL' ? ` (timeout ${timeoutMs} ms?)` : ''}`));
      if (code !== 0) return reject(new Error(`image rasterizer exited ${code}: ${Buffer.concat(err).toString('utf8').slice(0, 400) || '(no stderr)'}`));
      return resolve(Buffer.concat(out));
    });
    child.stdin.on('error', () => {}); // a dead child surfaces through 'close'
    child.stdin.end(svg, 'utf8');
  });
}
