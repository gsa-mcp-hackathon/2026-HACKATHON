// lib/tracer.mjs: utilities, trace levels, LLM records, write behavior.
// Run with --experimental-test-module-mocks (see package.json "test").
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { LIB, makePng, installFetchQueue } from './helpers.mjs';

mock.module(LIB('databricksAuth.mjs'), { namedExports: { getAccessToken: async () => 'tok', getWorkspaceHost: () => 'https://example.invalid' } });
const net = installFetchQueue();
process.env.TRACE_VOLUME = 'users.tom_jacobson.lancelot_traces';
delete process.env.TRACE_FAULT_INJECT;
const { resolveVolumePath, pngInfo, slug, computeSourceHash, Tracer, withTimeout, faultInjection } = await import(LIB('tracer.mjs'));

test('volume path from full name, from /Volumes path, rejects junk', () => {
  assert.equal(resolveVolumePath('users.tom_jacobson.lancelot_traces'), '/Volumes/users/tom_jacobson/lancelot_traces');
  assert.equal(resolveVolumePath('/Volumes/users/tom_jacobson/lancelot_traces/'), '/Volumes/users/tom_jacobson/lancelot_traces');
  assert.equal(resolveVolumePath('not a volume'), null);
});

test('pngInfo reads IHDR and rejects non-PNG', () => {
  assert.deepEqual(pngInfo(makePng(3, 2)).width, 3);
  assert.equal(pngInfo(makePng(3, 2)).height, 2);
  assert.equal(pngInfo(Buffer.from('hello world, not a png')), null);
});

test('slug', () => assert.equal(slug('Ishikawa/Fishbone'), 'ishikawa-fishbone'));

test('source hash covers package.json, app.yaml, server.mjs, lib/**/*.mjs', () => {
  const h = computeSourceHash();
  assert.equal(h.missing.length, 0);
  assert.ok(h.files >= 16); // 3 root files + 2 core + 11 Mermaid modules (D37)
  assert.match(h.sourceHash, /^[0-9a-f]{64}$/);
});

test('fault injection is inert when unset', () => {
  assert.deepEqual(faultInjection(), { active: false, tokens: [], until: null, ignoredReason: null });
});

test('production level redacts content and errors', () => {
  process.env.APP_TRACE_LEVEL = 'production';
  const tr = new Tracer('startup');
  assert.equal(tr.errorMessage(new Error('secret doc text')), '[redacted: 15 chars]');
  assert.equal(tr.text('doc'), undefined);
  tr.artifact('x.txt', 'doc');
  assert.equal(tr.artifacts.size, 0);
  const s = tr.recordLlm({ step: 'select', endpoint: 'gemini', status: 200, ms: 5, request: { messages: [{ role: 'user', content: 'secret' }] }, replyText: 'secret' });
  assert.equal(s.artifact, null);
  assert.equal(tr.llmRecords.length, 0);
  assert.ok(!JSON.stringify(tr.trace).includes('secret'));
});

test('debug level keeps full LLM records, including error bodies', () => {
  process.env.APP_TRACE_LEVEL = 'debug';
  const tr = new Tracer('startup');
  assert.match(tr.runDir, /^\/Volumes\/users\/tom_jacobson\/lancelot_traces\/runs\/\d{4}-\d{2}-\d{2}\/startup-\d{8}T\d{6}Z-[0-9a-f]{6}$/);
  tr.recordLlm({ step: 'generate', endpoint: 'databricks-gemini-3-8-flash', status: 500, ms: 9, errorClass: 'http_500', errorBody: 'boom' });
  assert.equal(tr.llmRecords.length, 1);
  assert.equal(tr.llmRecords[0].errorBody, 'boom');
  assert.ok(tr.artifacts.has('llm/01-generate-databricks-gemini-3-8-flash.json'));
});

test('withTimeout rejects with isTimeout', async () => {
  await assert.rejects(withTimeout(new Promise((r) => setTimeout(r, 500)), 20, 'x'), (e) => e.isTimeout === true);
});

test('finish() writes artifacts and extra files, then trace.json last', async () => {
  process.env.APP_TRACE_LEVEL = 'debug';
  const tr = new Tracer('startup');
  tr.artifact('sample.pdf/output.png', makePng(3, 2));
  tr.addRunFile('report.html', '<html>', 'text/html');
  net.calls.length = 0;
  const res = await tr.finish();
  assert.equal(res.written, true);
  const puts = net.calls.filter((c) => c.url.includes('/fs/files/')).map((c) => c.url);
  assert.ok(puts.some((u) => u.includes('output.png')) && puts.some((u) => u.includes('report.html')));
  assert.ok(puts.at(-1).endsWith('trace.json?overwrite=true'));
});

test('a failing write is recorded and never throws', async () => {
  const saved = globalThis.fetch;
  globalThis.fetch = async (url) => (String(url).includes('output.png') ? new Response('denied', { status: 403 }) : new Response('', { status: 200 }));
  try {
    const tr = new Tracer('startup');
    tr.artifact('sample.pdf/output.png', makePng(3, 2));
    const res = await tr.finish();
    assert.equal(res.written, true);
    assert.equal(tr.writeErrors.length, 1);
    assert.match(tr.writeErrors[0].error, /403/);
    assert.equal(tr.writeErrors[0].injected, false);
  } finally {
    globalThis.fetch = saved;
  }
});
