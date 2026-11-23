// The generate_choropleth MCP tool (BUILD_PLAN D31-D36, D41, D42).
//
// Transport-free like the Mermaid tool: server.mjs owns the MCP SDK, the zod
// schema and HTTP. No LLM calls. Never throws: failures become isError results
// with an errorCode.
import { sha256 } from '../../../core/tracer.mjs';
import { CHOROPLETH_INPUT_FIELDS, ChoroplethError, aspectPair, parseInputs } from './inputs.mjs';
import { dataRoot, loadDeclaration, loadDisaster, loadGeometry } from './data.mjs';
import { ALL, analyze } from './analysis.mjs';
import { buildMap } from './geo.mjs';
import { CAVEATS, buildWidgetData, buildWidgetHtml } from './widget.mjs';
import { buildImageSvg, loadLogo, loadMeasure, pngSize, rasterize } from './image.mjs';

export const CHOROPLETH_TOOL_NAME = 'generate_choropleth';
export const CHOROPLETH_TOOL_TITLE = 'FEMA Public Assistance cost outlier choropleth map (interactive HTML)';
export const CHOROPLETH_TOOL_DESCRIPTION = [
  'For ONE FEMA disaster, finds Public Assistance projects whose amount is sigma_threshold (default 3) or more standard',
  'deviations above the mean of their own damage category (A-G; population standard deviation, as 2026h), using the daily',
  'OpenFEMA snapshot stored in Databricks. Returns (1) a short text summary, (2) a self-contained interactive county choropleth map as',
  'an embedded text/html resource (no network access; embed it with <iframe sandbox="allow-scripts" srcdoc=...>), and',
  '(3) a square 1000x1000 PNG choropleth (image item) of the declaration state\'s counties: deeper red = more PA projects',
  '(categories A-G), solid red = county with a cost outlier, white = no project; under the FEMA logo and the official',
  'declaration title, no legend (logo only when there is no map),',
  'and (4) the figures as JSON (structuredContent, repeated as a text item). Optional pw_number highlights one project and',
  'opens its category. Optional choropleth map display options (initial_view, show_pause_button, show_pw_card, show_all_categories_card,',
  'legend_position, click_details, map_aspect_ratio) change only the interactive page; their defaults keep the standard page.',
  'Makes no LLM calls and writes no numbers itself. Review indicator only: not a finding of fraud,',
  'waste, or abuse. Errors: INVALID_INPUT, DATA_UNAVAILABLE, SNAPSHOT_NOT_FOUND, DISASTER_NOT_LOADED, PW_NOT_FOUND, INTERNAL_ERROR.',
].join(' ');
export { CHOROPLETH_INPUT_FIELDS };
export const CHOROPLETH_ERROR_CODES = ['INVALID_INPUT', 'DATA_UNAVAILABLE', 'SNAPSHOT_NOT_FOUND', 'DISASTER_NOT_LOADED', 'PW_NOT_FOUND', 'INTERNAL_ERROR'];

const fmtInt = (n) => Number(n).toLocaleString('en-US');

function summaryText({ doc, snapshot, analysis, map }) {
  const t = analysis.totals;
  const states = doc.states.length ? doc.states.join('/') : 'state unknown';
  const parts = [
    `DR-${doc.disasterNumber} (${states}), snapshot ${snapshot.date}: ${fmtInt(t.outliers)} cost outlier${t.outliers === 1 ? '' : 's'}`
      + ` (${analysis.sigmaThreshold} sigma or more above their own category mean) among ${fmtInt(t.projectsMapped)} projects in categories A-G;`
      + ` ${fmtInt(t.outliers - t.statewideOutliers - t.unmappableOutliers)} in ${fmtInt(t.outlierCounties)} ${t.outlierCounties === 1 ? 'county' : 'counties'}, ${fmtInt(t.statewideOutliers)} Statewide`
      + (t.unmappableOutliers ? `, ${fmtInt(t.unmappableOutliers)} without a mappable location` : '') + '.',
  ];
  const h = analysis.highlight;
  if (h) {
    parts.push(h.onMap
      ? `PW ${h.pw} (Category ${h.category}): ${h.sigma === null ? 'no sigma (category has no variation)' : `${h.sigma.toFixed(2)} sigma`}, ${h.flagged ? 'flagged' : 'not flagged'}.`
      : `${h.note}.`);
  }
  parts.push(map.drawn ? 'Interactive county map attached.' : `No county map: ${map.reason}; outliers are listed in the widget.`);
  parts.push(CAVEATS[0], CAVEATS[1]);
  return parts.join(' ');
}

// The square image (D44). Never throws: -> { png, info } or { png: null, info: null, error }.
async function buildImage({ doc, geometry, analysis, root, readFile, deps }) {
  const t0 = Date.now();
  try {
    const { decl, error: declError } = await loadDeclaration({ disasterNumber: doc.disasterNumber, root, ...(readFile ? { readFile } : {}) });
    const ss = decl && typeof decl.stateFips === 'string' ? decl.stateFips : null;
    let geo = ss ? geometry.states[ss] || null : null;
    if (ss && !geo) {
      const g = await loadGeometry({ stateFips: [ss], root, ...(readFile ? { readFile } : {}) });
      geo = g.states[ss] || null;
    }
    const title = (decl && typeof decl.title === 'string' && decl.title)
      || `DR-${doc.disasterNumber}${doc.states.length ? `-${doc.states.join('/')}` : ''}`;
    const logo = (deps.loadLogo || loadLogo)();
    const m = deps.measure ? { measure: deps.measure, source: 'injected' } : await loadMeasure();
    const built = buildImageSvg({ title, decl, geo, logo, measure: m.measure, countyProjects: analysis.countyProjects, countyOutliers: analysis.countyOutliers[ALL] });
    const tR = Date.now();
    const png = await (deps.rasterize || rasterize)(built.svg);
    const size = pngSize(png);
    if (!size) throw new Error('the rasterizer did not return a PNG');
    return {
      png,
      info: {
        mimeType: 'image/png', width: size.width, height: size.height, bytes: png.length, sha256: sha256(png),
        mapDrawn: built.mapDrawn, reason: built.reason, title,
        countiesWithProjects: built.counts.countiesWithProjects, outlierCounties: built.counts.outlierCounties,
        projectsDrawn: built.counts.projectsDrawn, maxProjects: built.counts.maxProjects,
        countiesNotInShapes: built.counts.countiesNotInShapes, statewideProjects: analysis.statewideProjects,
        scale: built.scale,
        declaration: decl
          ? { status: decl.status, loadId: decl.loadId ?? null, retrievedAt: decl.retrievedAt ?? null, currentAmendment: decl.currentAmendment ?? null, shapefileUrl: decl.source && decl.source.shapefileUrl ? decl.source.shapefileUrl : null }
          : { status: 'MISSING', error: declError },
        layout: built.layout, fontMeasure: m.source, svgBytes: Buffer.byteLength(built.svg, 'utf8'),
        timingsMs: { total: Date.now() - t0, raster: Date.now() - tR },
      },
    };
  } catch (err) {
    return { png: null, info: null, error: String(err && err.message ? err.message : err).slice(0, 400), ms: Date.now() - t0 };
  }
}

function imageText(image) {
  if (!image.info) return `No square image: ${image.error}.`;
  const i = image.info;
  return i.mapDrawn
    ? `Square image attached (${i.width}x${i.height} PNG): ${i.countiesWithProjects} ${i.countiesWithProjects === 1 ? 'county' : 'counties'} shaded by PA project count (up to ${i.maxProjects} in one county), ${i.outlierCounties} with a cost outlier in solid red, counties with no project white${i.statewideProjects ? `; ${i.statewideProjects} Statewide project${i.statewideProjects === 1 ? '' : 's'} not on the map` : ''}.`
    : `Square image attached (${i.width}x${i.height} PNG) with the FEMA logo only: ${i.reason}.`;
}

function errorResult(body) {
  return { isError: true, content: [{ type: 'text', text: JSON.stringify(body) }] };
}

// deps: { readFile, root } for tests; defaults read the real volume.
export async function runGenerateChoropleth(args = {}, _caller = {}, tracer, deps = {}) {
  const t0 = Date.now();
  const timingsMs = {};
  const call = { tool: CHOROPLETH_TOOL_NAME, request: null, data: null, map: null, response: null, timingsMs };
  tracer.trace.call = call;
  const root = deps.root !== undefined ? deps.root : dataRoot();
  const readFile = deps.readFile;
  try {
    const inputs = parseInputs(args);
    call.request = inputs;
    const loaded = await loadDisaster({ disasterNumber: inputs.disasterNumber, asOf: inputs.asOf, root, ...(readFile ? { readFile } : {}) });
    timingsMs.data = Date.now() - t0;
    const { doc, snapshot } = loaded;
    call.data = { root, snapshot: snapshot.date, loadId: snapshot.loadId, projects: doc.projects.length };

    const stateFips = [...new Set(doc.projects.map((p) => p.stateFips).filter((s) => typeof s === 'string'))].sort();
    const tGeo = Date.now();
    const geometry = await loadGeometry({ stateFips, root, ...(readFile ? { readFile } : {}) });
    // Obsolete FEMA county codes mapped to today's shape (crosswalk rule RECODE, D43).
    const aliases = Object.assign({}, ...Object.values(geometry.states).map((g) => (g.aliases && typeof g.aliases === 'object' ? g.aliases : {})));
    const recoded = doc.projects.filter((p) => p.countyFips && aliases[p.countyFips]).length;
    const mappedDoc = recoded
      ? { ...doc, projects: doc.projects.map((p) => (p.countyFips && aliases[p.countyFips] ? { ...p, femaCountyFips: p.countyFips, countyFips: aliases[p.countyFips] } : p)) }
      : doc;
    const analysis = analyze(mappedDoc, inputs);
    const map = Object.keys(geometry.states).length
      ? buildMap({ geometryByState: geometry.states, analysis, seedKey: `DR-${doc.disasterNumber}`, aspect: aspectPair(inputs.display.mapAspectRatio) })
      : { drawn: false, reason: `no county shapes are stored for state FIPS ${stateFips.join(', ') || '(none)'} yet` };
    timingsMs.map = Date.now() - tGeo;
    call.map = {
      drawn: map.drawn, reason: map.reason ?? null, statesRequested: stateFips, statesWithShapes: Object.keys(geometry.states),
      statesMissing: geometry.missing, shapeErrors: geometry.errors, recodedProjects: recoded, notPlaced: map.drawn ? map.notPlaced.length : null,
      countiesNotInShapes: map.drawn ? map.countiesNotInShapes : null, shadeConflicts: map.shadeConflicts ?? null,
      overlapsRemaining: map.overlapsRemaining ?? null,
    };

    const boundarySources = [...new Set(Object.values(geometry.states).map((g) => g.source).filter((s) => typeof s === 'string'))];
    const meta = { disasterNumber: doc.disasterNumber, states: doc.states, snapshotDate: snapshot.date, newestLastRefresh: doc.newestLastRefresh, boundarySources };
    const tW = Date.now();
    const display = inputs.display;
    const widgetData = buildWidgetData({ analysis, map, meta, display });
    const html = buildWidgetHtml(widgetData);
    timingsMs.widget = Date.now() - tW;
    const tI = Date.now();
    const image = await buildImage({ doc, geometry, analysis, root, readFile, deps });
    timingsMs.image = Date.now() - tI;
    call.image = image.info
      ? { mapDrawn: image.info.mapDrawn, reason: image.info.reason, bytes: image.info.bytes, sha256: image.info.sha256, countiesWithProjects: image.info.countiesWithProjects, outlierCounties: image.info.outlierCounties, maxProjects: image.info.maxProjects, countiesNotInShapes: image.info.countiesNotInShapes, declaration: image.info.declaration, layout: image.info.layout, fontMeasure: image.info.fontMeasure, timingsMs: image.info.timingsMs }
      : { error: image.error };
    timingsMs.total = Date.now() - t0;
    const uri = `ui://lancelot-beta/choropleth/${tracer.runId}.html`;

    const h = analysis.highlight;
    const structured = {
      status: 'OK',
      runId: tracer.runId,
      tool: CHOROPLETH_TOOL_NAME,
      disasterNumber: doc.disasterNumber,
      states: doc.states,
      snapshotDate: snapshot.date,
      loadId: snapshot.loadId,
      latestSnapshot: loaded.manifest.latest,
      newestLastRefresh: doc.newestLastRefresh,
      sigmaThreshold: analysis.sigmaThreshold,
      initialView: widgetData.initialView,
      display,
      totals: analysis.totals,
      categories: analysis.categories.map((c) => ({ code: c.code, description: c.description, recordCount: c.recordCount, mean: c.mean, stddev: c.stddev, projects: c.projects, outliers: c.outliers })),
      highlight: h ? { pw: h.pw, applicantId: h.applicantId, title: h.title, category: h.category, geo: h.geo, county: h.county, amount: h.amount, sigma: h.sigma, multipleOfMean: h.multipleOfMean, flagged: h.flagged, onMap: h.onMap, note: h.note } : null,
      outliers: analysis.outliers.map((p) => ({ pw: p.pw, applicantId: p.applicantId, title: p.title, category: p.category, geo: p.geo, county: p.county, countyFips: p.countyFips, femaCountyFips: p.femaCountyFips ?? p.countyFips, state: p.state, amount: p.amount, sigma: p.sigma, multipleOfMean: p.multipleOfMean })),
      countyOutliers: analysis.countyOutliers[ALL],
      map: { drawn: map.drawn, reason: map.reason ?? null, countiesNotInShapes: map.drawn ? map.countiesNotInShapes : [], notPlaced: map.drawn ? map.notPlaced.length : null, boundarySources },
      widget: { uri, mimeType: 'text/html', bytes: Buffer.byteLength(html, 'utf8'), sha256: sha256(html) },
      image: image.info,
      ...(image.info ? {} : { imageError: image.error }),
      caveats: CAVEATS,
      timingsMs,
    };
    const json = JSON.stringify(structured);
    const contentTypes = image.png ? ['text', 'resource', 'image', 'text'] : ['text', 'resource', 'text'];
    call.response = { status: 'OK', contentTypes, htmlBytes: structured.widget.bytes, outliers: analysis.totals.outliers, mapDrawn: map.drawn, imageBytes: image.png ? image.png.length : null };
    if (tracer.debug) {
      tracer.addRunFile('widget.html', html, 'text/html');
      if (image.png) tracer.addRunFile('image.png', image.png, 'image/png');
    }
    tracer.setOutcome('OK');
    return {
      content: [
        { type: 'text', text: `${summaryText({ doc, snapshot, analysis, map })} ${imageText(image)}` },
        { type: 'resource', resource: { uri, mimeType: 'text/html', text: html } },
        ...(image.png ? [{ type: 'image', data: image.png.toString('base64'), mimeType: 'image/png' }] : []),
        { type: 'text', text: json },
      ],
      structuredContent: structured,
    };
  } catch (err) {
    const known = err instanceof ChoroplethError;
    const errorCode = known ? err.code : 'INTERNAL_ERROR';
    const stage = known ? err.stage : 'unknown';
    timingsMs.total = Date.now() - t0;
    if (!known) console.error(`[choropleth] ${tracer.runId} unexpected error`, err);
    const body = { status: 'ERROR', runId: tracer.runId, tool: CHOROPLETH_TOOL_NAME, errorCode, message: known ? err.message : 'internal error', stage };
    if (known && err.details) body.details = err.details;
    call.response = { status: 'ERROR', errorCode, stage, contentTypes: ['text'] };
    call.error = tracer.errorMessage(err);
    tracer.setOutcome(errorCode, errorCode, stage);
    return errorResult(body);
  }
}
