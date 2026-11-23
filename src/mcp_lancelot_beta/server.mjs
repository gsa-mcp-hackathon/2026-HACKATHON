// mcp-lancelot-beta server (BUILD_PLAN.md section 9; ARCHITECTURE.md).
//
// The server:
//   1. installs process-level crash guards,
//   2. warm-loads pdf-parse BEFORE anything can render (guide lesson 5.1),
//   3. serves GET /, /healthz, /health, the stateless MCP endpoint POST /mcp
//      (one tool: generate_diagram), and the /api/selftest-* diagnostics,
//   4. listens on DATABRICKS_APP_PORT, then runs the startup self-test in the
//      background and writes its trace, artifacts, and HTML report to the
//      trace volume (sections 8a/8b).
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import express from 'express';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { z } from 'zod';
// Shared core (D32/D37)
import { getWorkspaceHost } from './lib/core/databricksAuth.mjs';
import { APP_ROOT, Tracer, faultInjection, getFile, putFile, pngInfo, resolveVolumePath, sha256, slug, withTimeout } from './lib/core/tracer.mjs';
// Mermaid tool (generate_diagram) and its startup self-test (D32/D37)
import { INPUT_FIELDS, TOOL_DESCRIPTION, TOOL_NAME, TOOL_TITLE, callerFromHeaders, runGenerateDiagram } from './lib/tools/mermaid/lib/tool.mjs';
import { prepareFileInput } from './lib/tools/mermaid/lib/inputs.mjs';
import { BUDGET_MS, PipelineError, endpointChain, makeLlmCaller, runPipeline } from './lib/tools/mermaid/lib/pipeline.mjs';
import { DIAGRAM_CATALOG, UNSUPPORTED_DIAGRAM_TYPES } from './lib/tools/mermaid/lib/prompts.mjs';
import { EXCLUDED_DIAGRAM_TYPES } from './lib/tools/mermaid/lib/diagramPolicy.mjs';
import { DIAGRAM_TYPE_TEST_SNIPPETS } from './lib/tools/mermaid/lib/diagramTypeTestSnippets.mjs';
import { renderMermaid, ValidationError } from './lib/tools/mermaid/lib/render.mjs';
import { buildStartupReport } from './lib/tools/mermaid/lib/report.mjs';
import { CHOROPLETH_INPUT_FIELDS, CHOROPLETH_TOOL_DESCRIPTION, CHOROPLETH_TOOL_NAME, CHOROPLETH_TOOL_TITLE, runGenerateChoropleth } from './lib/tools/choropleth/lib/tool.mjs';

// 1. Crash guards: a stray rejection from an abandoned render must not take
// down the whole process.
process.on('unhandledRejection', (reason) => {
  console.error('[server] unhandled promise rejection', reason);
});
process.on('uncaughtException', (err) => {
  console.error('[server] uncaught exception', err);
});

// 2. pdf-parse warm-load. render.mjs installs jsdom's window onto globalThis
// on the first render; if pdf-parse's bundled pdf.js loads after that, every
// PDF parse fails with "PDFJS is not defined". Invoking the parser once on a
// dummy buffer forces that load now (copied from the original server.mjs).
const warmLoad = { ok: false, ms: null, error: null };
{
  const t0 = Date.now();
  try {
    const pdfParse = (await import('pdf-parse/lib/pdf-parse.js')).default;
    await pdfParse(Buffer.from('%PDF-1.0\n%%EOF')).catch(() => {});
    warmLoad.ok = true;
  } catch (err) {
    warmLoad.error = String(err && err.message ? err.message : err);
    console.error('[server] pdf-parse warm-load failed - PDF extraction may not work', err);
  }
  warmLoad.ms = Date.now() - t0;
}

const SELFTEST_DIR = path.join(APP_ROOT, 'selftest');
const EXTRACTION_ONLY_FILES = ['sample.docx', 'sample.xlsx', 'sample.json'];
const END_TO_END_FILE = 'sample.pdf';
const PING_TIMEOUT_MS = 20_000;
const PING_MAX_TOKENS = 1024;
const GALLERY_RENDER_TIMEOUT_MS = 40_000;
const SMOKE_SOURCE = 'flowchart TD\n  A[Self-test start] --> B[PNG rendered]';
// Choropleth data volume (D41), from the app resource `choropleth-data`.
const DEFAULT_CHOROPLETH_DATA_VOLUME = 'users.tom_jacobson.choropleth_data';
const CHOROPLETH_SCHEMA_VERSION = 1;

const SERVER_VERSION = '0.2.0';
const MCP_BODY_LIMIT = '20mb'; // base64 of the 14 MB file limit fits

const selftestState = { state: 'pending', mode: null, runId: null, outcome: null, startedAt: null, finishedAt: null, report: null };

// ---------------------------------------------------------------------------
// 3. HTTP
// ---------------------------------------------------------------------------

const app = express();
app.disable('x-powered-by');

function health(_req, res) {
  res.status(200).json({
    status: 'ok',
    service: 'mcp-lancelot-beta',
    phase: 2,
    version: SERVER_VERSION,
    mcpEndpoint: '/mcp',
    tools: TOOLS.map((t) => t.name),
    excludedDiagramTypes: EXCLUDED_DIAGRAM_TYPES.map((t) => t.name), // never offered or accepted (D29)
    pdfWarmLoad: warmLoad.ok,
    selftest: selftestState,
    // Non-null only during a manual V19 run (docs/V19_TRACE_FAILURE_TEST.md).
    faultInjection: faultInjection().tokens.length ? faultInjection() : null,
    traceVolumeEnv: process.env.TRACE_VOLUME ?? null,
  });
}
app.get(['/', '/healthz', '/health'], health);

// --- MCP endpoint (stateless Streamable HTTP; ARCHITECTURE.md invariant 1) ---

function toolInputShape() {
  const field = (key) => z.string().optional().describe(INPUT_FIELDS[key]);
  return {
    data: field('data'),
    fileBase64: field('fileBase64'),
    fileName: field('fileName'),
    workspacePath: field('workspacePath'),
    diagramType: field('diagramType'),
    hint: field('hint'),
  };
}

// generate_choropleth: every field optional and number-or-string, so bad values
// reach the tool and get its own INVALID_INPUT error (inputs.mjs).
function choroplethInputShape() {
  const field = (key) => z.union([z.number(), z.string()]).optional().describe(CHOROPLETH_INPUT_FIELDS[key]);
  return {
    disaster_number: field('disaster_number'),
    pw_number: field('pw_number'),
    applicant_id: z.string().optional().describe(CHOROPLETH_INPUT_FIELDS.applicant_id),
    sigma_threshold: field('sigma_threshold'),
    as_of: z.string().optional().describe(CHOROPLETH_INPUT_FIELDS.as_of),
    // Choropleth map display options (D46); booleans also accepted as "true"/"false".
    initial_view: z.string().optional().describe(CHOROPLETH_INPUT_FIELDS.initial_view),
    show_pause_button: z.union([z.boolean(), z.string()]).optional().describe(CHOROPLETH_INPUT_FIELDS.show_pause_button),
    show_pw_card: z.union([z.boolean(), z.string()]).optional().describe(CHOROPLETH_INPUT_FIELDS.show_pw_card),
    show_all_categories_card: z.union([z.boolean(), z.string()]).optional().describe(CHOROPLETH_INPUT_FIELDS.show_all_categories_card),
    legend_position: z.string().optional().describe(CHOROPLETH_INPUT_FIELDS.legend_position),
    click_details: z.string().optional().describe(CHOROPLETH_INPUT_FIELDS.click_details),
    map_aspect_ratio: z.string().optional().describe(CHOROPLETH_INPUT_FIELDS.map_aspect_ratio),
  };
}

// The tools this server offers, in /health and tools/list order (D42).
const TOOLS = [
  { name: TOOL_NAME, title: TOOL_TITLE, description: TOOL_DESCRIPTION, inputShape: toolInputShape, run: runGenerateDiagram },
  { name: CHOROPLETH_TOOL_NAME, title: CHOROPLETH_TOOL_TITLE, description: CHOROPLETH_TOOL_DESCRIPTION, inputShape: choroplethInputShape, run: runGenerateChoropleth },
];

// A fresh McpServer per request; `tracers` collects the per-call traces so
// they are written only after the HTTP response has closed.
function buildMcpServer(caller, tracers) {
  const server = new McpServer({ name: 'mcp-lancelot-beta', version: SERVER_VERSION });
  for (const tool of TOOLS) {
    const handler = async (args) => {
      const tracer = new Tracer('call');
      tracer.trace.tool = tool.name;
      tracers.push(tracer);
      await tracer.writeStarted();
      console.log(`[mcp] ${tracer.runId} ${tool.name} started`);
      const result = await tool.run(args ?? {}, caller, tracer);
      console.log(`[mcp] ${tracer.runId} ${tool.name} finished: ${tracer.trace.run.outcome} in ${Date.now() - tracer.startedAtMs} ms`);
      return result;
    };
    const config = { title: tool.title, description: tool.description, inputSchema: tool.inputShape() };
    if (typeof server.registerTool === 'function') server.registerTool(tool.name, config, handler);
    else server.tool(tool.name, tool.description, tool.inputShape(), handler);
  }
  return server;
}

function jsonRpcError(res, httpStatus, code, message) {
  res.status(httpStatus).json({ jsonrpc: '2.0', error: { code, message }, id: null });
}

app.post('/mcp', express.json({ limit: MCP_BODY_LIMIT }), async (req, res) => {
  const tracers = [];
  const caller = callerFromHeaders(req.headers);
  let server = null;
  let transport = null;
  res.on('close', () => {
    Promise.resolve().then(() => transport?.close()).catch(() => {});
    Promise.resolve().then(() => server?.close()).catch(() => {});
    for (const tracer of tracers) {
      if (tracer.trace.call) tracer.trace.call.connection = { responseFinished: res.writableFinished, httpStatus: res.statusCode };
      tracer.finish().catch(() => {}); // after the response; never counts against the budget
    }
  });
  try {
    server = buildMcpServer(caller, tracers);
    transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (err) {
    console.error('[mcp] request failed', err);
    if (!res.headersSent) jsonRpcError(res, 500, -32603, 'Internal server error');
  }
});

function mcpMethodNotAllowed(_req, res) {
  res.set('Allow', 'POST');
  jsonRpcError(res, 405, -32000, 'Method not allowed: this MCP server is stateless; send requests with POST /mcp');
}
app.get('/mcp', mcpMethodNotAllowed);
app.delete('/mcp', mcpMethodNotAllowed);

// --- Diagnostics (ARCHITECTURE.md section 6.2). None re-runs the startup self-test (D9). ---

app.get('/api/selftest-render', async (_req, res) => {
  const { png, ...rec } = await renderOnce(SMOKE_SOURCE, GALLERY_RENDER_TIMEOUT_MS);
  res.status(rec.ok ? 200 : 500).json({ status: rec.ok ? 'ok' : 'failed', ...rec });
});

app.get('/api/selftest-diagram-gallery', async (_req, res) => {
  const tracer = new Tracer('gallery'); // in memory only: nothing is written to the volume
  const gallery = await galleryRender(tracer);
  res.json({ status: gallery.supportedFailed === 0 ? 'ok' : 'failed', ...gallery });
});

// TEMPORARY (remove once Q3 is answered): does Databricks forward the caller's
// identity to this app? Reports header NAMES and a workspace/list probe with
// the forwarded token; never returns the token itself.
app.get('/api/selftest-obo-scope', async (req, res) => {
  const caller = callerFromHeaders(req.headers);
  const out = {
    temporary: true,
    forwardedTokenPresent: !!caller.forwardedToken,
    forwardedEmail: caller.email,
    forwardedUser: caller.user,
    forwardedHeaderNames: Object.keys(req.headers).filter((h) => h.startsWith('x-forwarded-')).sort(),
    probe: null,
  };
  if (caller.forwardedToken && caller.email) {
    const probePath = `/Users/${caller.email}`;
    try {
      const r = await fetch(`${getWorkspaceHost()}/api/2.0/workspace/list?${new URLSearchParams({ path: probePath })}`, {
        headers: { Authorization: `Bearer ${caller.forwardedToken}` },
      });
      out.probe = { path: probePath, httpStatus: r.status, ok: r.ok };
    } catch (err) {
      out.probe = { path: probePath, error: errText(err) };
    }
  }
  res.json(out);
});

// Body-parser and other request errors -> JSON-RPC error shape.
app.use((err, _req, res, _next) => {
  if (err && err.type === 'entity.too.large') return jsonRpcError(res, 413, -32600, `request body is larger than ${MCP_BODY_LIMIT}`);
  if (err && err.type === 'entity.parse.failed') return jsonRpcError(res, 400, -32700, 'request body is not valid JSON');
  console.error('[server] request error', err);
  if (!res.headersSent) jsonRpcError(res, 500, -32603, 'Internal server error');
});

const port = Number(process.env.DATABRICKS_APP_PORT) || 8000;
app.listen(port, '0.0.0.0', () => {
  console.log(`[server] mcp-lancelot-beta (phase 1) listening on 0.0.0.0:${port}`);
  // 4. Start the self-test only after listen() succeeded, never awaited by
  // startup, so a slow LLM or render cannot fail the deployment health check.
  setImmediate(() => {
    runStartupSelfTest().catch((err) => {
      selftestState.state = 'crashed';
      console.error('[selftest] crashed', err);
    });
  });
});

// ---------------------------------------------------------------------------
// Startup self-test (section 8a)
// ---------------------------------------------------------------------------

function selftestMode() {
  const v = String(process.env.STARTUP_SELFTEST || 'full').trim().toLowerCase();
  return ['full', 'render', 'off'].includes(v) ? v : 'full';
}

function errText(err) {
  return String(err && err.message ? err.message : err);
}

async function checkVolume(tracer) {
  const result = { ok: false, ms: null, path: null, error: null };
  if (!tracer.runDir) {
    result.error = `trace volume could not be resolved from TRACE_VOLUME=${process.env.TRACE_VOLUME ?? '(unset)'}`;
    return result;
  }
  const filePath = `${tracer.runDir}/volume-check.txt`;
  result.path = filePath;
  const token = crypto.randomBytes(8).toString('hex');
  const t0 = Date.now();
  try {
    await tracer.ensureDir(tracer.runDir);
    await putFile(filePath, `volume check ${token}`, 'text/plain');
    const back = (await getFile(filePath)).toString('utf8');
    result.ok = back === `volume check ${token}`;
    if (!result.ok) result.error = 'read-back content did not match what was written';
  } catch (err) {
    result.error = errText(err);
  }
  result.ms = Date.now() - t0;
  return result;
}

// Non-blocking (D41): proves the service principal can read the Choropleth
// export before the tool exists. Reads manifest.json and the latest index.json.
async function checkChoroplethData() {
  const raw = process.env.CHOROPLETH_DATA_VOLUME || DEFAULT_CHOROPLETH_DATA_VOLUME;
  const root = resolveVolumePath(raw);
  const result = {
    ok: false, ms: null, env: process.env.CHOROPLETH_DATA_VOLUME ?? null, root, schemaVersion: null,
    latest: null, snapshots: null, manifestDisasters: null, indexDisasters: null, error: null,
  };
  if (!root) {
    result.error = `could not resolve a volume path from ${raw}`;
    return result;
  }
  const t0 = Date.now();
  try {
    const manifest = JSON.parse((await getFile(`${root}/manifest.json`)).toString('utf8'));
    const snapshots = Array.isArray(manifest.snapshots) ? manifest.snapshots : [];
    result.schemaVersion = manifest.schemaVersion ?? null;
    result.latest = manifest.latest ?? null;
    result.snapshots = snapshots.length;
    result.manifestDisasters = snapshots.find((s) => s.date === manifest.latest)?.disasters ?? null;
    if (result.latest) {
      const index = JSON.parse((await getFile(`${root}/snapshots/${result.latest}/index.json`)).toString('utf8'));
      result.indexDisasters = Array.isArray(index.disasters) ? index.disasters.length : null;
    }
    result.ok = result.schemaVersion === CHOROPLETH_SCHEMA_VERSION && Boolean(result.latest)
      && result.indexDisasters !== null && result.indexDisasters === result.manifestDisasters;
    if (!result.ok) result.error = 'manifest has no latest snapshot, an unknown schema version, or disagrees with index.json';
  } catch (err) {
    result.error = errText(err);
  }
  result.ms = Date.now() - t0;
  return result;
}

async function pingEndpoints(tracer) {
  const results = [];
  for (const endpoint of endpointChain()) {
    const callLlm = makeLlmCaller({ tracer, deadlineAt: Date.now() + PING_TIMEOUT_MS + 2_000, endpoints: [endpoint], label: 'ping' });
    const t0 = Date.now();
    try {
      const reply = await callLlm({
        step: 'ping',
        messages: [{ role: 'user', content: 'Reply with exactly one word: pong' }],
        maxTokens: PING_MAX_TOKENS,
        stageCapMs: PING_TIMEOUT_MS,
      });
      results.push({ endpoint, ok: true, ms: Date.now() - t0, reply: tracer.text(reply.text.slice(0, 200)), error: null });
    } catch (err) {
      results.push({ endpoint, ok: false, ms: Date.now() - t0, error: tracer.errorMessage(err), errorCode: err.code ?? null });
    }
  }
  if (results.length === 0) results.push({ endpoint: '(none configured)', ok: false, ms: 0, error: 'LLM_ENDPOINT_PRIMARY and LLM_ENDPOINT_FALLBACK are both empty' });
  return results;
}

async function extractionChecks(tracer) {
  const results = [];
  for (const file of EXTRACTION_ONLY_FILES) {
    const rec = { file, ok: false, bytes: null, branch: null, ms: null, chars: null, truncated: null, preview: null, error: null, errorCode: null };
    try {
      const buffer = fs.readFileSync(path.join(SELFTEST_DIR, file));
      rec.bytes = buffer.length;
      const { text, extract } = await prepareFileInput({ buffer, fileName: file });
      Object.assign(rec, { ok: true, branch: extract.branch, ms: extract.ms, chars: extract.chars, truncated: extract.truncated, preview: tracer.text(extract.preview) });
      tracer.artifact(`${file}/extracted.txt`, text);
    } catch (err) {
      rec.error = tracer.errorMessage(err);
      rec.errorCode = err.code || 'EXTRACTION_FAILED';
      rec.branch = err.extract?.branch ?? null;
      rec.ms = err.extract?.ms ?? null;
    }
    results.push(rec);
  }
  return results;
}

async function renderOnce(source, timeoutMs) {
  const t0 = Date.now();
  const rec = { ok: false, outcome: null, ms: null, pngBytes: null, width: null, height: null, error: null, png: null };
  try {
    const result = await withTimeout(renderMermaid({ mermaid: source, format: 'png' }), timeoutMs, `render timed out after ${timeoutMs} ms`);
    if (result.pngFailed || !result.png) {
      rec.outcome = 'png_failed';
      rec.error = result.pngError || 'no PNG returned';
    } else {
      const png = Buffer.from(result.png, 'base64');
      const info = pngInfo(png);
      Object.assign(rec, { ok: true, outcome: 'ok', pngBytes: png.length, width: info?.width ?? null, height: info?.height ?? null, png });
    }
  } catch (err) {
    rec.outcome = err instanceof ValidationError ? 'validation_error' : err && err.isTimeout ? 'timeout' : 'error';
    rec.error = errText(err);
  }
  rec.ms = Date.now() - t0;
  return rec;
}

async function renderSmoke(tracer) {
  const rec = await renderOnce(SMOKE_SOURCE, GALLERY_RENDER_TIMEOUT_MS);
  if (rec.png) tracer.artifact('render-smoke.png', rec.png);
  const { png, ...rest } = rec;
  return { ...rest, error: rec.error ? tracer.errorMessage(rec.error) : null };
}

async function pdfEndToEnd(tracer) {
  const t0 = Date.now();
  const deadlineAt = t0 + BUDGET_MS;
  const out = { ok: false, file: END_TO_END_FILE, budgetMs: BUDGET_MS, totalMs: null, input: null, extract: null, pipeline: {}, result: null, errorCode: null, errorStage: null, error: null };
  try {
    const buffer = fs.readFileSync(path.join(SELFTEST_DIR, END_TO_END_FILE));
    const prepared = await prepareFileInput({ buffer, fileName: END_TO_END_FILE });
    out.input = prepared.input;
    out.extract = { ...prepared.extract, preview: tracer.text(prepared.extract.preview) };
    tracer.artifact(`${END_TO_END_FILE}/extracted.txt`, prepared.text);
    const result = await runPipeline({
      text: prepared.text,
      deadlineAt,
      tracer,
      record: out.pipeline,
      artifactPrefix: `${END_TO_END_FILE}/`,
      label: END_TO_END_FILE,
    });
    out.ok = true;
    out.result = { diagramType: result.diagramType, width: result.width, height: result.height, pngBytes: result.pngBytes, repaired: result.repaired, resized: result.resized, resize: result.resize, endpointUsed: result.endpointUsed };
  } catch (err) {
    out.errorCode = err.code || 'INTERNAL_ERROR';
    out.errorStage = err.stage || 'unknown';
    out.error = tracer.errorMessage(err);
    if (err.input) out.input = err.input;
    if (err.extract) out.extract = { ...err.extract, preview: tracer.text(err.extract.preview) };
    if (err instanceof PipelineError && err.failures) out.llmFailures = err.failures;
  }
  out.totalMs = Date.now() - t0;
  return out;
}

async function galleryRender(tracer) {
  const unsupported = new Set(UNSUPPORTED_DIAGRAM_TYPES.map((u) => u.name));
  const items = [];
  for (const entry of DIAGRAM_CATALOG) {
    const name = entry.name;
    const item = { name, slug: slug(name), knownUnsupported: unsupported.has(name), ok: false, outcome: null, ms: null, pngBytes: null, width: null, height: null, error: null };
    const snippet = DIAGRAM_TYPE_TEST_SNIPPETS[name];
    if (!snippet) {
      item.outcome = 'no_snippet';
      item.error = `no test snippet for "${name}" in diagramTypeTestSnippets.mjs`;
    } else {
      const rec = await renderOnce(snippet, GALLERY_RENDER_TIMEOUT_MS);
      Object.assign(item, { ok: rec.ok, outcome: rec.outcome, ms: rec.ms, pngBytes: rec.pngBytes, width: rec.width, height: rec.height, error: rec.error ? tracer.errorMessage(rec.error) : null });
      if (rec.png) tracer.artifact(`gallery/${item.slug}.png`, rec.png);
    }
    items.push(item);
  }
  const supported = items.filter((i) => !i.knownUnsupported);
  const known = items.filter((i) => i.knownUnsupported);
  return {
    total: items.length,
    passed: items.filter((i) => i.ok).length,
    supportedTotal: supported.length,
    supportedFailed: supported.filter((i) => !i.ok).length,
    knownUnsupportedTotal: known.length,
    knownUnsupportedFailed: known.filter((i) => !i.ok).length,
    items,
  };
}

// Runs generate_choropleth on the real data for a known disaster, in memory
// (the call tracer is never finished, so nothing is written). Reported, not
// blocking (D42): the data and the county shapes are outside this app.
const CHOROPLETH_SELFTEST_DISASTER = 4856;
const CHOROPLETH_SELFTEST_FALLBACK = 3553; // EM-3553-DC: PA Category B only -> logo-only image (D44)
async function choroplethWidgetCheck(tracer) {
  const t0 = Date.now();
  const callTracer = new Tracer('selftest-choropleth');
  const res = await runGenerateChoropleth({ disaster_number: CHOROPLETH_SELFTEST_DISASTER }, {}, callTracer);
  const out = { disaster: CHOROPLETH_SELFTEST_DISASTER, ms: Date.now() - t0 };
  if (res.isError) {
    const body = JSON.parse(res.content[0].text);
    return { ...out, ok: false, errorCode: body.errorCode, error: body.message };
  }
  const sc = res.structuredContent;
  const html = res.content[1].resource.text;
  if (tracer.debug) tracer.artifact(`choropleth/DR-${CHOROPLETH_SELFTEST_DISASTER}.html`, html);
  // D44 square image: the map case above, plus a logo-only fallback (EM-3553: PA Category B only).
  const imageOf = (r) => {
    const item = r.content.find((c) => c.type === 'image');
    const im = r.structuredContent && r.structuredContent.image;
    if (!item || !im) return { ok: false, error: (r.structuredContent && r.structuredContent.imageError) || 'no image item' };
    const png = Buffer.from(item.data, 'base64');
    return { ok: im.width === 1000 && im.height === 1000 && sha256(png) === im.sha256, png, mapDrawn: im.mapDrawn, reason: im.reason, title: im.title, countiesWithProjects: im.countiesWithProjects, outlierCounties: im.outlierCounties, bytes: im.bytes, fontMeasure: im.fontMeasure, layout: im.layout, ms: im.timingsMs };
  };
  const image = imageOf(res);
  const t1 = Date.now();
  const fbRes = await runGenerateChoropleth({ disaster_number: CHOROPLETH_SELFTEST_FALLBACK }, {}, new Tracer('selftest-choropleth'));
  const fallback = fbRes.isError ? { ok: false, error: fbRes.content[0].text.slice(0, 200) } : imageOf(fbRes);
  fallback.ms = Date.now() - t1;
  if (tracer.debug) {
    if (image.png) tracer.artifact(`choropleth/DR-${CHOROPLETH_SELFTEST_DISASTER}.png`, image.png);
    if (fallback.png) tracer.artifact(`choropleth/EM-${CHOROPLETH_SELFTEST_FALLBACK}.png`, fallback.png);
  }
  delete image.png; delete fallback.png;
  return {
    ...out,
    ok: res.content.map((c) => c.type).join() === 'text,resource,image,text' && html.includes('Content-Security-Policy')
      && image.ok && image.mapDrawn === true && fallback.ok && fallback.mapDrawn === false,
    image,
    fallbackImage: { disaster: CHOROPLETH_SELFTEST_FALLBACK, ...fallback },
    snapshotDate: sc.snapshotDate,
    outliers: sc.totals.outliers,
    projects: sc.totals.projectsMapped,
    mapDrawn: sc.map.drawn,
    mapReason: sc.map.reason,
    htmlBytes: sc.widget.bytes,
  };
}

// Machine verdict. The gallery is reported but never blocking (D13).
function verdict(mode, stages) {
  const checks = [];
  if (mode === 'full') {
    checks.push(['volume', stages.volume?.ok]);
    for (const p of stages.pings || []) checks.push([`ping:${p.endpoint}`, p.ok]);
    for (const e of stages.extraction || []) checks.push([`extract:${e.file}`, e.ok]);
  }
  checks.push(['renderSmoke', stages.renderSmoke?.ok]);
  if (mode === 'full') checks.push(['pdf', stages.pdf?.ok]);
  const failed = checks.filter(([, ok]) => !ok).map(([name]) => name);
  return { ok: failed.length === 0, failed };
}

async function runStage(st, name, fn) {
  const t0 = Date.now();
  console.log(`[selftest] stage ${name} started`);
  try {
    st.stages[name] = await fn();
  } catch (err) {
    st.stages[name] = { ok: false, error: errText(err), crashed: true };
  }
  console.log(`[selftest] stage ${name} finished in ${Date.now() - t0} ms`);
}

async function runStartupSelfTest() {
  const mode = selftestMode();
  selftestState.mode = mode;
  if (mode === 'off') {
    selftestState.state = 'off';
    console.log('[selftest] STARTUP_SELFTEST=off; skipping');
    return;
  }
  const tracer = new Tracer('startup');
  Object.assign(selftestState, { state: 'running', runId: tracer.runId, startedAt: tracer.trace.run.startedAt });
  const st = { mode, warmLoad, stages: {} };
  tracer.trace.selftest = st;
  console.log(`[selftest] ${tracer.runId} started (mode=${mode}, level=${tracer.level}, volume=${tracer.volumeRoot})`);
  await tracer.writeStarted();

  if (mode === 'full') {
    await runStage(st, 'volume', () => checkVolume(tracer));
    await runStage(st, 'choroplethData', () => checkChoroplethData()); // reported, not blocking (D41)
    await runStage(st, 'pings', () => pingEndpoints(tracer));
    await runStage(st, 'extraction', () => extractionChecks(tracer));
  }
  await runStage(st, 'renderSmoke', () => renderSmoke(tracer));
  if (mode === 'full') await runStage(st, 'pdf', () => pdfEndToEnd(tracer));
  await runStage(st, 'gallery', () => galleryRender(tracer));
  if (mode === 'full') await runStage(st, 'choroplethWidget', () => choroplethWidgetCheck(tracer)); // reported, not blocking (D42)

  const v = verdict(mode, st.stages);
  st.failedChecks = v.failed;
  tracer.setOutcome(v.ok ? 'OK' : 'FAILED', v.ok ? null : 'SELFTEST_FAILED', v.ok ? null : v.failed[0]);
  tracer.markFinished();

  let reportPath = null;
  if (tracer.debug) {
    try {
      const html = buildStartupReport(tracer);
      tracer.addRunFile('report.html', html, 'text/html');
      tracer.addFile('latest/startup-report.html', html, 'text/html');
      reportPath = `${tracer.runDir}/report.html`;
    } catch (err) {
      tracer.noteWriteError('report.html (build)', err);
    }
  }
  tracer.addFile(
    'latest/startup-summary.json',
    JSON.stringify({ runId: tracer.runId, runDir: tracer.runDir, outcome: tracer.trace.run.outcome, failedChecks: v.failed, startedAt: tracer.trace.run.startedAt, finishedAt: tracer.trace.run.finishedAt, sourceHash: tracer.trace.version.sourceHash, versionFile: tracer.trace.version.versionFile }, null, 2),
    'application/json'
  );

  const written = await tracer.finish();
  // Only advertise the report in /health if its write actually succeeded
  // (review finding R3: V19 Part A showed a path to a report that did not exist).
  const reportWritten = reportPath && !tracer.writeErrors.some((e) => e.what === reportPath);
  Object.assign(selftestState, { state: 'done', outcome: tracer.trace.run.outcome, finishedAt: tracer.trace.run.finishedAt, report: reportWritten ? reportPath : null });
  console.log(`[selftest] ${tracer.runId} finished: outcome=${tracer.trace.run.outcome} failed=[${v.failed.join(', ')}] traceWritten=${written.written} writeErrors=${written.writeErrors ?? 0}`);
}
