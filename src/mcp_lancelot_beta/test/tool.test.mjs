// lib/tool.mjs runGenerateDiagram: MCP result shape, error codes, per-call trace.
// render.mjs, extractText.mjs, databricksAuth.mjs, and fetch are mocked.
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { LIB, installFetchQueue, selectReply, mermaidReply } from './helpers.mjs';

class ValidationError extends Error {}
class UnsupportedFileError extends Error {}
const PNG_B64 = Buffer.from('89504e470d0a1a0a0000000d49484452000000640000003208020000', 'hex').toString('base64');
mock.module(LIB('render.mjs'), { namedExports: { ValidationError, renderMermaid: async () => ({ png: PNG_B64 }) } });
mock.module(LIB('extractText.mjs'), { namedExports: { UnsupportedFileError, extractText: async ({ buffer }) => buffer.toString('utf8') } });
mock.module(LIB('databricksAuth.mjs'), { namedExports: { getAccessToken: async () => 'tok', getWorkspaceHost: () => 'https://example.invalid' } });
process.env.LLM_ENDPOINT_PRIMARY = 'gemini';
process.env.LLM_ENDPOINT_FALLBACK = 'grok';
process.env.TRACE_VOLUME = 'users.tom_jacobson.lancelot_traces';
const net = installFetchQueue();
const { runGenerateDiagram, callerFromHeaders, TOOL_NAME, INPUT_FIELDS } = await import(LIB('tool.mjs'));
const { Tracer } = await import(LIB('tracer.mjs'));

const caller = { email: 'me@hq.dhs.gov', forwardedToken: 'user-token' };
const queue = (...items) => {
  net.queue.length = 0;
  net.queue.push(...items);
};
const meta = (result) => JSON.parse(result.content.find((c) => c.type === 'text').text);

test('tool name and documented inputs', () => {
  assert.equal(TOOL_NAME, 'generate_diagram');
  assert.deepEqual(Object.keys(INPUT_FIELDS).sort(), ['data', 'diagramType', 'fileBase64', 'fileName', 'hint', 'workspacePath']);
});

test('callerFromHeaders reads the forwarded identity headers', () => {
  assert.deepEqual(callerFromHeaders({ 'x-forwarded-email': ' a@b.gov ', 'x-forwarded-access-token': 't' }), { email: 'a@b.gov', forwardedToken: 't', user: null });
});

test('success: PNG image + OK metadata (mermaidSource always included)', async () => {
  process.env.APP_TRACE_LEVEL = 'debug';
  queue(selectReply('Flowchart'), mermaidReply('flowchart TD\nA-->B'));
  const tracer = new Tracer('call');
  const result = await runGenerateDiagram({ data: 'a then b then c' }, caller, tracer);
  assert.ok(!result.isError);
  assert.deepEqual(result.content.map((c) => c.type), ['image', 'text']);
  assert.equal(result.content[0].mimeType, 'image/png');
  assert.equal(result.content[0].data, PNG_B64);
  const m = meta(result);
  assert.equal(m.status, 'OK');
  assert.equal(m.runId, tracer.runId);
  assert.match(m.runId, /^call-/);
  assert.equal(m.diagramType, 'Flowchart');
  assert.equal(m.rationale, 'because');
  assert.equal(m.mermaidSource, 'flowchart TD\nA-->B');
  assert.equal(m.repaired, false);
  assert.equal(m.truncated, false);
  assert.ok(m.timingsMs.total >= 0);
  assert.equal(tracer.trace.run.outcome, 'OK');
  assert.equal(tracer.trace.call.response.status, 'OK');
  assert.ok(tracer.artifacts.has('input.bin') && tracer.artifacts.has('extracted.txt') && tracer.artifacts.has('output.png'));
});

test('diagramType skips selection', async () => {
  queue(mermaidReply('sequenceDiagram\nA->>B: hi'));
  const tracer = new Tracer('call');
  const m = meta(await runGenerateDiagram({ data: 'x', diagramType: 'Sequence diagram' }, caller, tracer));
  assert.equal(m.diagramType, 'Sequence diagram');
  assert.equal(m.timingsMs.select, 0);
  assert.deepEqual(tracer.trace.llm.map((l) => l.step), ['generate']);
});

test('invalid input: isError with INVALID_INPUT, stage input, no LLM call', async () => {
  queue();
  const tracer = new Tracer('call');
  const result = await runGenerateDiagram({}, caller, tracer);
  assert.equal(result.isError, true);
  const m = meta(result);
  assert.equal(m.status, 'ERROR');
  assert.equal(m.errorCode, 'INVALID_INPUT');
  assert.equal(m.stage, 'input');
  assert.equal(m.runId, tracer.runId);
  assert.equal(tracer.trace.llm.length, 0);
  assert.equal(tracer.trace.run.outcome, 'INVALID_INPUT');
});

test('LLM configuration error surfaces as LLM_ERROR', async () => {
  queue({ status: 400, body: 'bad request' });
  const tracer = new Tracer('call');
  const m = meta(await runGenerateDiagram({ data: 'x' }, caller, tracer));
  assert.equal(m.errorCode, 'LLM_ERROR');
  assert.equal(m.stage, 'select');
});

test('production level: email hashed, hint not stored, rationale still returned to the caller', async () => {
  process.env.APP_TRACE_LEVEL = 'production';
  try {
    queue(selectReply('Flowchart'), mermaidReply('flowchart TD\nA-->B'));
    const tracer = new Tracer('call');
    const m = meta(await runGenerateDiagram({ data: 'secret doc', hint: 'secret hint' }, caller, tracer));
    assert.equal(m.rationale, 'because');
    assert.match(tracer.trace.call.caller.email, /^sha256:[0-9a-f]{16}$/);
    const traceText = JSON.stringify(tracer.trace);
    for (const s of ['secret doc', 'secret hint', 'me@hq.dhs.gov', 'because']) assert.ok(!traceText.includes(s), s);
    assert.equal(tracer.artifacts.size, 0);
  } finally {
    process.env.APP_TRACE_LEVEL = 'debug';
  }
});
