// V19 fault injection in lib/tracer.mjs (D17). The switch is read once at
// module load, so this file sets the environment before importing.
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { LIB, installFetchQueue } from './helpers.mjs';

mock.module(LIB('databricksAuth.mjs'), { namedExports: { getAccessToken: async () => 'tok', getWorkspaceHost: () => 'https://example.invalid' } });
const net = installFetchQueue();
process.env.TRACE_VOLUME = 'users.tom_jacobson.lancelot_traces';
process.env.APP_TRACE_LEVEL = 'debug';
process.env.TRACE_FAULT_INJECT = 'artifacts/gallery/,report.html';
process.env.TRACE_FAULT_INJECT_UNTIL = new Date(Date.now() + 30 * 60 * 1000).toISOString();
const { faultInjectionConfig, faultInjection, Tracer } = await import(LIB('tracer.mjs'));

test('unset is off and silent', () => {
  const c = faultInjectionConfig({});
  assert.equal(c.active, false);
  assert.equal(c.ignoredReason, null);
});

test('tokens without UNTIL are ignored', () => assert.match(faultInjectionConfig({ TRACE_FAULT_INJECT: 'x' }).ignoredReason, /missing/));
test('a past UNTIL is ignored', () => assert.match(faultInjectionConfig({ TRACE_FAULT_INJECT: 'x', TRACE_FAULT_INJECT_UNTIL: '2020-01-01T00:00:00Z' }).ignoredReason, /past/));
test('an UNTIL more than 2 h ahead is ignored', () => {
  const until = new Date(Date.now() + 3 * 3600e3).toISOString();
  assert.match(faultInjectionConfig({ TRACE_FAULT_INJECT: 'x', TRACE_FAULT_INJECT_UNTIL: until }).ignoredReason, /2 hours/);
});

test('a valid window is active with the given tokens', () => {
  const c = faultInjection();
  assert.equal(c.active, true);
  assert.deepEqual(c.tokens, ['artifacts/gallery/', 'report.html']);
});

test('injected writes fail with no network call; others and trace.json still write', async () => {
  const tr = new Tracer('startup');
  tr.artifact('gallery/flowchart.png', Buffer.from('png'));
  tr.artifact('sample.pdf/output.png', Buffer.from('png'));
  tr.addRunFile('report.html', '<html>', 'text/html');
  tr.addFile('latest/startup-report.html', '<html>', 'text/html');
  tr.addFile('latest/startup-summary.json', '{}', 'application/json');
  net.calls.length = 0;
  const res = await tr.finish();
  assert.equal(res.written, true);
  const failed = tr.writeErrors.map((e) => e.what.split('/').slice(-2).join('/')).sort();
  assert.deepEqual(failed, ['gallery/flowchart.png', 'latest/startup-report.html', `${tr.runId}/report.html`].sort());
  assert.ok(tr.writeErrors.every((e) => e.injected === true));
  const puts = net.calls.filter((c) => c.url.includes('/fs/files/')).map((c) => c.url);
  assert.ok(!puts.some((u) => u.includes('gallery') || u.includes('report.html')));
  assert.ok(puts.some((u) => u.includes('output.png')) && puts.some((u) => u.includes('startup-summary.json')));
  assert.ok(puts.at(-1).endsWith('trace.json?overwrite=true'));
  assert.equal(tr.trace.config.faultInjection.active, true);
});
