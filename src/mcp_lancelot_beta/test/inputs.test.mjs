// lib/inputs.mjs prepareInput: the three generate_diagram input modes and the
// workspacePath security rules (ARCHITECTURE.md invariant 15).
// extractText.mjs (needs npm packages) and databricksAuth.mjs are mocked.
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { LIB } from './helpers.mjs';

class UnsupportedFileError extends Error {}
mock.module(LIB('extractText.mjs'), {
  namedExports: { UnsupportedFileError, extractText: async ({ buffer }) => buffer.toString('utf8') },
});
mock.module(LIB('databricksAuth.mjs'), { namedExports: { getAccessToken: async () => 'sp-token', getWorkspaceHost: () => 'https://example.invalid' } });
const { prepareInput, scopeWorkspacePath } = await import(LIB('inputs.mjs'));

const ME = 'me@hq.dhs.gov';
const caller = { email: ME, forwardedToken: 'user-token' };
const rejectsWith = (promise, code, re) => assert.rejects(promise, (e) => e.code === code && (!re || re.test(e.message)) && !!e.input);

let exportCalls = [];
function mockExport(status, body) {
  exportCalls = [];
  globalThis.fetch = async (url, opts) => {
    exportCalls.push({ url: String(url), auth: opts?.headers?.Authorization });
    return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });
  };
}

test('no input is INVALID_INPUT', () => rejectsWith(prepareInput({}, caller), 'INVALID_INPUT', /exactly one/));
test('two inputs are INVALID_INPUT', () => rejectsWith(prepareInput({ data: 'x', workspacePath: '/Users/me/a.pdf' }, caller), 'INVALID_INPUT', /data, workspacePath/));
test('whitespace-only data counts as no input', () => rejectsWith(prepareInput({ data: '   ' }, caller), 'INVALID_INPUT'));

test('data: text goes through the text extractor', async () => {
  const r = await prepareInput({ data: 'step one -> step two' }, caller);
  assert.equal(r.text, 'step one -> step two');
  assert.equal(r.input.mode, 'data');
  assert.equal(r.input.fileName, null);
  assert.equal(r.extract.branch, 'text');
});

test('fileBase64 with a data: URL prefix and fileName', async () => {
  const b64 = Buffer.from('hello pdf text').toString('base64');
  const r = await prepareInput({ fileBase64: `data:application/pdf;base64,${b64}`, fileName: 'C:\\docs\\..\\plan.pdf' }, caller);
  assert.equal(r.text, 'hello pdf text');
  assert.equal(r.input.mode, 'fileBase64');
  assert.equal(r.extract.branch, 'pdf-parse');
  assert.ok(r.input.encodedChars > 0);
});

test('fileBase64 without fileName is INVALID_INPUT', () => rejectsWith(prepareInput({ fileBase64: 'aGk=' }, caller), 'INVALID_INPUT', /fileName is required/));
test('invalid base64 is INVALID_INPUT', () => rejectsWith(prepareInput({ fileBase64: 'not base64!!', fileName: 'a.pdf' }, caller), 'INVALID_INPUT', /not valid base64/));
test('unsupported extension is UNSUPPORTED_FILE', () => rejectsWith(prepareInput({ fileBase64: 'aGk=', fileName: 'a.exe' }, caller), 'UNSUPPORTED_FILE'));

test('scope: /Workspace prefix stripped, path normalized', () => {
  assert.equal(scopeWorkspacePath(`/Workspace/Users/${ME}/a/./b/../plan.pdf`, ME), `/Users/${ME}/a/plan.pdf`);
});
test('scope: /Volumes is INVALID_INPUT', () => assert.throws(() => scopeWorkspacePath('/Volumes/c/s/v/a.pdf', ME), (e) => e.code === 'INVALID_INPUT'));
test('scope: another user is ACCESS_DENIED', () => assert.throws(() => scopeWorkspacePath('/Users/other@hq.dhs.gov/a.pdf', ME), (e) => e.code === 'ACCESS_DENIED'));
test('scope: ../ traversal out of home is ACCESS_DENIED', () => assert.throws(() => scopeWorkspacePath(`/Users/${ME}/../other@hq.dhs.gov/a.pdf`, ME), (e) => e.code === 'ACCESS_DENIED'));
test('scope: prefix look-alike is ACCESS_DENIED', () => assert.throws(() => scopeWorkspacePath(`/Users/${ME}x/a.pdf`, ME), (e) => e.code === 'ACCESS_DENIED'));
test('scope: the home folder itself is INVALID_INPUT', () => assert.throws(() => scopeWorkspacePath(`/Users/${ME}/`, ME), (e) => e.code === 'INVALID_INPUT'));

test('workspacePath without forwarded identity is ACCESS_DENIED', () => rejectsWith(prepareInput({ workspacePath: `/Users/${ME}/a.pdf` }, {}), 'ACCESS_DENIED', /identity/));
test('workspacePath without forwarded token is ACCESS_DENIED', () => rejectsWith(prepareInput({ workspacePath: `/Users/${ME}/a.pdf` }, { email: ME }), 'ACCESS_DENIED', /token/));

test('workspacePath reads with the USER token and extracts', async () => {
  mockExport(200, { content: Buffer.from('from workspace').toString('base64') });
  const r = await prepareInput({ workspacePath: `/Workspace/Users/${ME}/notes.md` }, caller);
  assert.equal(r.text, 'from workspace');
  assert.equal(r.input.mode, 'workspacePath');
  assert.equal(r.input.workspacePath, `/Users/${ME}/notes.md`);
  assert.equal(exportCalls.length, 1);
  assert.equal(exportCalls[0].auth, 'Bearer user-token');
  assert.ok(exportCalls[0].url.includes(encodeURIComponent(`/Users/${ME}/notes.md`)));
});

test('workspace 403 is ACCESS_DENIED; 404 is EXTRACTION_FAILED', async () => {
  mockExport(403, 'denied');
  await rejectsWith(prepareInput({ workspacePath: `/Users/${ME}/a.pdf` }, caller), 'ACCESS_DENIED', /HTTP 403/);
  mockExport(404, 'missing');
  await rejectsWith(prepareInput({ workspacePath: `/Users/${ME}/a.pdf` }, caller), 'EXTRACTION_FAILED', /not found/);
});
