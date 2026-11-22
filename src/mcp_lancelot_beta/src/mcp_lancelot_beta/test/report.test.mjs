// lib/report.mjs: structure, section 0, escaping, no script or external URLs.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { makePng } from './helpers.mjs';

process.env.TRACE_VOLUME = 'users.tom_jacobson.lancelot_traces';
process.env.APP_TRACE_LEVEL = 'debug';
const { Tracer } = await import('../lib/core/tracer.mjs');
const { buildStartupReport } = await import('../lib/tools/mermaid/lib/report.mjs');

const png = makePng(3, 2);

function mockTracer() {
  const tr = new Tracer('startup');
  tr.trace.selftest = {
    mode: 'full',
    stages: {
      volume: { ok: true, ms: 120, path: `${tr.runDir}/volume-check.txt` },
      pings: [
        { endpoint: 'databricks-gemini-3-8-flash', ok: true, ms: 800, reply: 'pong' },
        { endpoint: 'databricks-grok-4-6', ok: false, ms: 20000, error: 'timeout' },
      ],
      extraction: [{ file: 'sample.docx', ok: true, branch: 'mammoth', ms: 40, chars: 22794, truncated: false, preview: '<img src=x onerror=alert(1)>' }],
      renderSmoke: { ok: true, ms: 900 },
      pdf: {
        ok: true, totalMs: 23000, budgetMs: 70000,
        input: { fileName: 'sample.pdf', decodedBytes: 282423, sha256: 'ab' },
        extract: { branch: 'pdf-parse', chars: 6000, ms: 300, truncated: false },
        pipeline: {
          select: { skipped: false, outcome: 'parsed', chosen: 'Flowchart', modelSaid: 'Flowchart', rationale: 'tree <b>' },
          generate: { endpoint: 'databricks-gemini-3-8-flash', ms: 9000, fenced: true, mermaidChars: 400 },
          render: [{ attempt: 1, outcome: 'ok', ms: 1500, pngBytes: png.length, width: 3, height: 2 }],
        },
        result: { diagramType: 'Flowchart', width: 3, height: 2, pngBytes: png.length, repaired: false, endpointUsed: 'databricks-gemini-3-8-flash' },
      },
      gallery: {
        total: 2, passed: 1, supportedTotal: 1, supportedFailed: 0, knownUnsupportedTotal: 1, knownUnsupportedFailed: 1,
        items: [
          { name: 'Flowchart', slug: 'flowchart', ok: true, ms: 500, width: 3, height: 2 },
          { name: 'Mindmap', slug: 'mindmap', knownUnsupported: true, ok: false, outcome: 'validation_error', ms: 30, error: 'Could not create canvas of type 2d' },
        ],
      },
    },
  };
  tr.artifact('sample.pdf/output.png', png);
  tr.artifact('gallery/flowchart.png', png);
  tr.artifact('sample.pdf/attempt1.mmd', 'flowchart TD\nA-->B </pre><script>alert(1)</script>');
  tr.setOutcome('FAILED', 'SELFTEST_FAILED', 'ping:databricks-grok-4-6');
  tr.markFinished();
  return tr;
}

const section = (html, n) => html.slice(html.indexOf(`<h2>${n}. `), html.indexOf(`<h2>${n + 1}. `));

test('no script and no external src/href', () => {
  const html = buildStartupReport(mockTracer());
  assert.ok(!/<script/i.test(html));
  assert.ok(!/(src|href)\s*=\s*["']?https?:/i.test(html));
});

test('untrusted content is escaped', () => {
  const html = buildStartupReport(mockTracer());
  assert.ok(html.includes('&lt;/pre&gt;&lt;script&gt;'));
  assert.ok(html.includes('&lt;img src=x onerror'));
  assert.ok(!html.includes('<img src=x'));
});

test('sections 0 to 6 are present', () => {
  const html = buildStartupReport(mockTracer());
  for (let i = 0; i <= 6; i += 1) assert.ok(html.includes(`<h2>${i}. `), `section ${i}`);
});

test('section 0 shows the sample.pdf PNG', () => {
  const s0 = section(buildStartupReport(mockTracer()), 0);
  assert.ok(s0.includes(`data:image/png;base64,${png.toString('base64')}`));
});

test('gallery marks known-unsupported types', () => {
  assert.ok(buildStartupReport(mockTracer()).includes('\u274c known unsupported'));
});

test('section 0 shows a large failure marker when there is no PNG', () => {
  const tr = mockTracer();
  tr.trace.selftest.stages.pdf = { ok: false, errorCode: 'RENDER_FAILED', errorStage: 'render', error: 'Parse error on line 3', totalMs: 41000, pipeline: {} };
  const s0 = section(buildStartupReport(tr), 0);
  assert.ok(s0.includes('No PNG was produced') && s0.includes('RENDER_FAILED') && s0.includes('render'));
});
