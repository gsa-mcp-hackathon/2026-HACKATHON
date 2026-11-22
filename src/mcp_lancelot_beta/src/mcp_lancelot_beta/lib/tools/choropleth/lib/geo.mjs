// County map geometry, computed on the server (BUILD_PLAN D35, D42). Pure.
//
// Input shapes are lon/lat GeoJSON MultiPolygon coordinates per county
// (choropleth_data/geo/v1/states/<SS>.json). Output is in a fixed viewBox
// (VIEW_W wide): SVG path strings, a shade per county for every view, and a
// seeded position for every project that has a shape to sit in.

export const VIEW_W = 1000;
const PAD = 16;
const H_MIN = 320;
const H_MAX = 760;
export const OUTLIER_R = 6; // screen px; the browser keeps it constant when zooming
export const SHADES = 5; // per color family
const MIN_GAP = 2;
const SEPARATE_ROUNDS = 80;

// ------------------------------------------------------------ seeded random

export function hash32(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i += 1) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// --------------------------------------------------------------- shapes

function lonFor(lon, state) {
  return state === '02' && lon > 0 ? lon - 360 : lon; // Aleutians cross 180 degrees
}

function validRing(ring) {
  return Array.isArray(ring) && ring.length >= 4
    && ring.every((pt) => Array.isArray(pt) && Number.isFinite(pt[0]) && Number.isFinite(pt[1]));
}

// -> [{ fips, name, state, polygons: [[ring lon/lat]...] }]; bad rings are dropped.
export function prepareCounties(geometryByState) {
  const out = [];
  for (const [state, geo] of Object.entries(geometryByState || {})) {
    for (const c of geo.counties || []) {
      if (!c || typeof c.fips !== 'string' || !/^\d{5}$/.test(c.fips) || !Array.isArray(c.polygons)) continue;
      const polygons = c.polygons
        .map((poly) => (Array.isArray(poly) ? poly.filter(validRing).map((ring) => ring.map(([lon, lat]) => [lonFor(lon, state), lat])) : []))
        .filter((poly) => poly.length > 0);
      if (polygons.length) out.push({ fips: c.fips, name: typeof c.name === 'string' ? c.name : c.fips, state, polygons });
    }
  }
  out.sort((a, b) => (a.fips < b.fips ? -1 : a.fips > b.fips ? 1 : 0));
  return out;
}

// Equirectangular, x scaled by cos(mid latitude): adequate at state scale.
// aspect (D50): null = the box follows the state's shape (height H_MIN..H_MAX); [w, h] = the box is
// VIEW_W wide and VIEW_W * h / w tall, and the whole state is fitted inside it, centred.
export function makeProjection(counties, aspect = null) {
  let minLon = Infinity; let maxLon = -Infinity; let minLat = Infinity; let maxLat = -Infinity;
  for (const c of counties) for (const poly of c.polygons) for (const ring of poly) for (const [lon, lat] of ring) {
    if (lon < minLon) minLon = lon; if (lon > maxLon) maxLon = lon;
    if (lat < minLat) minLat = lat; if (lat > maxLat) maxLat = lat;
  }
  if (!Number.isFinite(minLon)) return null;
  const kx = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
  const w = Math.max((maxLon - minLon) * kx, 1e-6);
  const h = Math.max(maxLat - minLat, 1e-6);
  let scale; let height;
  if (aspect) {
    height = Math.round(VIEW_W * aspect[1] / aspect[0]);
    scale = Math.min((VIEW_W - 2 * PAD) / w, (height - 2 * PAD) / h);
  } else {
    scale = (VIEW_W - 2 * PAD) / w;
    height = h * scale + 2 * PAD;
    if (height > H_MAX) { scale = (H_MAX - 2 * PAD) / h; height = H_MAX; }
    height = Math.max(H_MIN, Math.round(height));
  }
  const ox = (VIEW_W - w * scale) / 2;
  const oy = (height - h * scale) / 2;
  return { width: VIEW_W, height, project: ([lon, lat]) => [ox + (lon - minLon) * kx * scale, oy + (maxLat - lat) * scale] };
}

const r1 = (v) => Math.round(v * 10) / 10;

function ringArea(ring) {
  let a = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) a += (ring[j][0] + ring[i][0]) * (ring[j][1] - ring[i][1]);
  return a / 2;
}

function ringCentroid(ring) {
  let a = 0; let cx = 0; let cy = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const f = ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
    a += f; cx += (ring[j][0] + ring[i][0]) * f; cy += (ring[j][1] + ring[i][1]) * f;
  }
  return a === 0 ? [ring[0][0], ring[0][1]] : [cx / (3 * a), cy / (3 * a)];
}

function pointInRings(x, y, rings) {
  let inside = false; // even-odd over every ring, so holes work
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
      const [xi, yi] = ring[i]; const [xj, yj] = ring[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
  }
  return inside;
}

// ------------------------------------------------------------ label point (D45)
// Pole of inaccessibility (the polylabel method): the point inside a polygon farthest from
// its edges, and that distance. Better than the centroid for concave or odd-shaped counties.
function segDist2(px, py, a, b) {
  let x = a[0]; let y = a[1]; let dx = b[0] - x; let dy = b[1] - y;
  if (dx !== 0 || dy !== 0) {
    const t = ((px - x) * dx + (py - y) * dy) / (dx * dx + dy * dy);
    if (t > 1) { x = b[0]; y = b[1]; } else if (t > 0) { x += dx * t; y += dy * t; }
  }
  dx = px - x; dy = py - y;
  return dx * dx + dy * dy;
}
function signedDist(x, y, rings) {
  let min = Infinity;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) min = Math.min(min, segDist2(x, y, ring[i], ring[j]));
  }
  return (pointInRings(x, y, rings) ? 1 : -1) * Math.sqrt(min);
}
// rings: one polygon (outer ring first, then holes), projected. -> [x, y, distance]
export function poleOfInaccessibility(rings, maxCells = 4000) {
  let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
  for (const [x, y] of rings[0]) { if (x < x0) x0 = x; if (y < y0) y0 = y; if (x > x1) x1 = x; if (y > y1) y1 = y; }
  const size = Math.min(x1 - x0, y1 - y0);
  if (!(size > 0)) return [x0, y0, 0];
  const precision = Math.max(x1 - x0, y1 - y0) / 200;
  const cell = (x, y, half) => { const d = signedDist(x, y, rings); return { x, y, half, d, max: d + half * Math.SQRT2 }; };
  const queue = [];
  for (let x = x0; x < x1; x += size) for (let y = y0; y < y1; y += size) queue.push(cell(x + size / 2, y + size / 2, size / 2));
  const [cx, cy] = ringCentroid(rings[0]);
  let best = cell(cx, cy, 0);
  const mid = cell((x0 + x1) / 2, (y0 + y1) / 2, 0);
  if (mid.d > best.d) best = mid;
  let n = queue.length;
  while (queue.length && n < maxCells) {
    let iMax = 0;
    for (let i = 1; i < queue.length; i += 1) if (queue[i].max > queue[iMax].max) iMax = i;
    const c = queue.splice(iMax, 1)[0];
    if (c.d > best.d) best = c;
    if (c.max - best.d <= precision) break; // nothing left can beat the best by more than the precision
    const h = c.half / 2;
    queue.push(cell(c.x - h, c.y - h, h), cell(c.x + h, c.y - h, h), cell(c.x - h, c.y + h, h), cell(c.x + h, c.y + h, h));
    n += 4;
  }
  return [best.x, best.y, Math.max(0, best.d)];
}
// Label point of a county: the pole of its largest polygon. -> [x, y, r] rounded, or null.
export function labelPoint(projectedPolygons) {
  let bestPoly = null; let bestArea = 0;
  for (const poly of projectedPolygons) {
    const a = Math.abs(ringArea(poly[0]));
    if (a > bestArea) { bestArea = a; bestPoly = poly; }
  }
  if (!bestPoly) return null;
  const [x, y, r] = poleOfInaccessibility(bestPoly);
  return [r1(x), r1(y), r1(r)];
}

// A region is something a dot can be placed in: one county, or a whole state.
function makeRegion(projectedPolygons) {
  const rings = projectedPolygons.flat();
  let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
  for (const ring of rings) for (const [x, y] of ring) {
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
  }
  let wsum = 0; let cx = 0; let cy = 0;
  for (const poly of projectedPolygons) {
    const a = Math.abs(ringArea(poly[0]));
    const [px, py] = ringCentroid(poly[0]);
    wsum += a; cx += px * a; cy += py * a;
  }
  const center = wsum > 0 ? [cx / wsum, cy / wsum] : [(x0 + x1) / 2, (y0 + y1) / 2];
  return { rings, bbox: [x0, y0, x1, y1], center, anchor: rings[0][0], contains: (x, y) => pointInRings(x, y, rings) };
}

export function samplePoint(region, rng) {
  const [x0, y0, x1, y1] = region.bbox;
  const [cx, cy] = region.center;
  for (let i = 0; i < 80; i += 1) {
    const ux = x0 + rng() * (x1 - x0);
    const uy = y0 + rng() * (y1 - y0);
    if (!region.contains(ux, uy)) continue;
    const t = 0.25 + 0.75 * rng(); // pull toward the visual center
    const px = cx + (ux - cx) * t;
    const py = cy + (uy - cy) * t;
    return region.contains(px, py) ? [px, py] : [ux, uy];
  }
  return region.contains(cx, cy) ? [cx, cy] : [region.anchor[0], region.anchor[1]];
}

// ------------------------------------------------------- adjacency, shades

// Counties are neighbors when they share at least two boundary vertices.
export function adjacency(counties) {
  const byVertex = new Map();
  counties.forEach((c, idx) => {
    const seen = new Set();
    for (const poly of c.polygons) for (const ring of poly) for (const [lon, lat] of ring) {
      const key = `${Math.round(lon * 1e6)},${Math.round(lat * 1e6)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      if (!byVertex.has(key)) byVertex.set(key, []);
      byVertex.get(key).push(idx);
    }
  });
  const shared = new Map();
  for (const list of byVertex.values()) {
    if (list.length < 2) continue;
    for (let i = 0; i < list.length; i += 1) for (let j = i + 1; j < list.length; j += 1) {
      const k = `${list[i]}|${list[j]}`;
      shared.set(k, (shared.get(k) || 0) + 1);
    }
  }
  const adj = counties.map(() => new Set());
  for (const [k, n] of shared) {
    if (n < 2) continue;
    const [a, b] = k.split('|').map(Number);
    adj[a].add(b); adj[b].add(a);
  }
  return adj;
}

// DSatur on the counties of one family; -> { colors: Map idx->0..k-1, conflicts }
export function colorFamily(members, adj, k = SHADES) {
  const inFamily = new Set(members);
  const colors = new Map();
  let conflicts = 0;
  const degree = (i) => [...adj[i]].filter((n) => inFamily.has(n)).length;
  while (colors.size < members.length) {
    let best = -1; let bestSat = -1; let bestDeg = -1;
    for (const i of members) {
      if (colors.has(i)) continue;
      const sat = new Set([...adj[i]].filter((n) => colors.has(n)).map((n) => colors.get(n))).size;
      const deg = degree(i);
      if (sat > bestSat || (sat === bestSat && deg > bestDeg)) { best = i; bestSat = sat; bestDeg = deg; }
    }
    const used = new Map();
    for (const n of adj[best]) if (colors.has(n)) used.set(colors.get(n), (used.get(colors.get(n)) || 0) + 1);
    let c = -1;
    for (let x = 0; x < k; x += 1) if (!used.has(x)) { c = x; break; }
    if (c === -1) {
      conflicts += 1;
      c = [...Array(k).keys()].sort((a, b) => used.get(a) - used.get(b))[0];
    }
    colors.set(best, c);
  }
  return { colors, conflicts };
}

// -> { shades: [ {view: 'r0'|'g3'} per county ], conflicts }
export function shadeViews(counties, adj, views, countyOutliers) {
  const shades = counties.map(() => ({}));
  let conflicts = 0;
  for (const view of views) {
    const counts = countyOutliers[view] || {};
    const red = []; const grey = [];
    counties.forEach((c, i) => ((counts[c.fips] || 0) > 0 ? red : grey).push(i));
    for (const [family, members] of [['r', red], ['g', grey]]) {
      const res = colorFamily(members, adj);
      conflicts += res.conflicts;
      for (const [i, c] of res.colors) shades[i][view] = `${family}${c}`;
    }
  }
  return { shades, conflicts };
}

// ------------------------------------------------------------- placement

function separate(items, minDist) {
  for (let round = 0; round < SEPARATE_ROUNDS; round += 1) {
    let moved = false;
    for (let i = 0; i < items.length; i += 1) {
      for (let j = i + 1; j < items.length; j += 1) {
        const a = items[i]; const b = items[j];
        let dx = b.x - a.x; let dy = b.y - a.y;
        let d = Math.hypot(dx, dy);
        if (d >= minDist) continue;
        if (d < 1e-6) { const ang = a.rng() * 2 * Math.PI; dx = Math.cos(ang); dy = Math.sin(ang); d = 1; }
        const push = (minDist - Math.hypot(b.x - a.x, b.y - a.y)) / 2 + 0.01;
        const ux = dx / d; const uy = dy / d;
        const ax = a.x - ux * push; const ay = a.y - uy * push;
        const bx = b.x + ux * push; const by = b.y + uy * push;
        if (a.region.contains(ax, ay)) { a.x = ax; a.y = ay; moved = true; }
        if (b.region.contains(bx, by)) { b.x = bx; b.y = by; moved = true; }
      }
    }
    if (!moved) break;
  }
  let overlaps = 0;
  for (let i = 0; i < items.length; i += 1) for (let j = i + 1; j < items.length; j += 1) {
    if (Math.hypot(items[j].x - items[i].x, items[j].y - items[i].y) < minDist - 0.05) overlaps += 1;
  }
  return overlaps;
}

// Bounding box of projected polygons: [minX, minY, maxX, maxY], rounded like the paths.
export function boxOf(polygons) {
  let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
  for (const poly of polygons) for (const ring of poly) for (const [x, y] of ring) {
    if (x < x0) x0 = x; if (y < y0) y0 = y; if (x > x1) x1 = x; if (y > y1) y1 = y;
  }
  return Number.isFinite(x0) ? [r1(x0), r1(y0), r1(x1), r1(y1)] : null;
}

// geometryByState: {SS: geo}; analysis: from analyze(); seedKey: e.g. 'DR-4673'.
export function buildMap({ geometryByState, analysis, seedKey, aspect = null }) {
  const counties = prepareCounties(geometryByState);
  if (!counties.length) return { drawn: false, reason: 'no county shapes are available for this disaster\'s state(s)' };
  const proj = makeProjection(counties, aspect);
  const projected = counties.map((c) => c.polygons.map((poly) => poly.map((ring) => ring.map(proj.project))));
  const regions = projected.map(makeRegion);
  const byFips = new Map(counties.map((c, i) => [c.fips, i]));

  const stateRegions = new Map();
  for (const state of new Set(counties.map((c) => c.state))) {
    stateRegions.set(state, makeRegion(projected.filter((_, i) => counties[i].state === state).flat()));
  }

  const adj = adjacency(counties);
  const { shades, conflicts } = shadeViews(counties, adj, analysis.views, analysis.countyOutliers);

  const positions = new Map();
  const notPlaced = [];
  const outlierItems = [];
  for (const p of analysis.mapped) {
    let region = null; let reason = null;
    if (p.geo === 'COUNTY' && p.countyFips) {
      if (byFips.has(p.countyFips)) region = regions[byFips.get(p.countyFips)];
      else reason = stateRegions.has(p.countyFips.slice(0, 2)) ? 'county not in the shape file' : 'no shapes for this state';
    } else if (p.geo === 'STATEWIDE') {
      region = stateRegions.get(p.stateFips) || null;
      if (!region) reason = 'no shapes for this state';
    } else {
      reason = 'location not mappable';
    }
    if (!region) { notPlaced.push({ key: p.key, reason }); continue; }
    const rng = mulberry32(hash32(`${seedKey}|${p.key}`));
    const [x, y] = samplePoint(region, rng);
    const item = { key: p.key, x, y, region, rng };
    positions.set(p.key, item);
    if (p.outlier) outlierItems.push(item);
  }
  const overlapsRemaining = separate(outlierItems, 2 * OUTLIER_R + MIN_GAP);

  const placed = new Set(analysis.mapped.filter((p) => p.geo === 'COUNTY').map((p) => p.countyFips));
  return {
    drawn: true,
    width: proj.width,
    height: proj.height,
    counties: counties.map((c, i) => ({
      fips: c.fips,
      name: c.name,
      d: projected[i].map((poly) => poly.map((ring) => {
        const pts = [];
        for (const [x, y] of ring) {
          const q = `${r1(x)},${r1(y)}`;
          if (pts[pts.length - 1] !== q) pts.push(q);
        }
        return `M${pts.join('L')}Z`;
      }).join('')).join(''),
      shades: shades[i],
      box: boxOf(projected[i]), // [minX, minY, maxX, maxY] in map units; the widget zooms to fit these
      label: labelPoint(projected[i]), // [x, y, room] in map units: where the county name goes (D45)
    })),
    positions: new Map([...positions].map(([k, it]) => [k, [r1(it.x), r1(it.y)]])),
    notPlaced,
    countiesNotInShapes: [...placed].filter((f) => f && !byFips.has(f)).sort(),
    shadeConflicts: conflicts,
    overlapsRemaining,
    adjacencyPairs: adj.reduce((n, s) => n + s.size, 0) / 2,
  };
}
