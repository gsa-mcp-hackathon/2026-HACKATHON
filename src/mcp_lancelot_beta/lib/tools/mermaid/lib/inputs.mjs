// Input validation and text extraction (BUILD_PLAN.md sections 3 and 5).
//
// prepareFileInput: the file-bytes path (startup self-test and every mode below).
// prepareInput: the generate_diagram tool's three input modes (Phase 2):
//   data          raw text (JSON, CSV, YAML, Markdown, plain text)
//   fileBase64    base64 file bytes + fileName (extension picks the extractor)
//   workspacePath a workspace file read with the CALLER's forwarded token,
//                 only inside /Users/<x-forwarded-email>/, no service-principal
//                 fallback, no /Volumes (ARCHITECTURE.md invariant 15).
//
// Text extraction itself is the original, unchanged lib/extractText.mjs.
import path from 'node:path';
import { extractText, UnsupportedFileError } from './extractText.mjs';
import { getWorkspaceHost } from '../../../core/databricksAuth.mjs';
import { sha256, withTimeout } from '../../../core/tracer.mjs';

export const MAX_FILE_BYTES = 14 * 1024 * 1024;
export const EXTRACT_TIMEOUT_MS = 10_000;
const TRUNCATION_MARKER = '[... truncated ...]';
const PREVIEW_CHARS = 1_000;

// Extension -> which branch of extractText.mjs handles it (recorded in traces).
const EXTRACTOR_BY_EXTENSION = {
  '.pdf': 'pdf-parse',
  '.docx': 'mammoth',
  '.xlsx': 'exceljs',
  '.html': 'jsdom-html',
  '.htm': 'jsdom-html',
  '.txt': 'text',
  '.md': 'text',
  '.csv': 'text',
  '.json': 'text',
  '.yaml': 'text',
  '.yml': 'text',
};

export const SUPPORTED_EXTENSIONS = Object.keys(EXTRACTOR_BY_EXTENSION);

export class InputError extends Error {
  constructor(code, message, stage = 'input') {
    super(message);
    this.name = 'InputError';
    this.code = code; // INVALID_INPUT | UNSUPPORTED_FILE | EXTRACTION_FAILED | ACCESS_DENIED
    this.stage = stage;
  }
}

export function extractorFor(fileName) {
  return EXTRACTOR_BY_EXTENSION[path.extname(String(fileName || '')).toLowerCase()] || null;
}

// Validates raw file bytes and extracts text.
// Returns { text, input, extract } where `input` and `extract` are trace
// records (content-free except `extract.preview`, which the caller should
// pass through tracer.text()).
export async function prepareFileInput({ buffer, fileName, mimeType = '' }) {
  const input = {
    mode: 'fileBytes',
    fileName: fileName ?? null,
    extension: fileName ? path.extname(fileName).toLowerCase() : null,
    decodedBytes: Buffer.isBuffer(buffer) ? buffer.length : null,
    sha256: Buffer.isBuffer(buffer) && buffer.length ? sha256(buffer) : null,
    validation: 'pending',
  };
  const fail = (code, message, stage = 'input') => {
    input.validation = code;
    const err = new InputError(code, message, stage);
    err.input = input;
    return err;
  };

  if (!fileName || typeof fileName !== 'string') throw fail('INVALID_INPUT', 'fileName is required with file bytes');
  if (!Buffer.isBuffer(buffer)) throw fail('INVALID_INPUT', 'file bytes are missing');
  if (buffer.length === 0) throw fail('INVALID_INPUT', 'file is empty (0 bytes)');
  if (buffer.length > MAX_FILE_BYTES) {
    throw fail('INVALID_INPUT', `file is ${buffer.length} bytes; the limit is ${MAX_FILE_BYTES} bytes`);
  }
  const branch = extractorFor(fileName);
  if (!branch) {
    throw fail('UNSUPPORTED_FILE', `unsupported file type "${input.extension || '(none)'}"; supported: ${SUPPORTED_EXTENSIONS.join(', ')}`);
  }
  input.validation = 'ok';

  const extract = { branch, ms: null, chars: null, truncated: null, preview: null };
  const t0 = Date.now();
  let text;
  try {
    text = await withTimeout(
      extractText({ buffer, originalName: fileName, mimeType }),
      EXTRACT_TIMEOUT_MS,
      `text extraction timed out after ${EXTRACT_TIMEOUT_MS} ms`
    );
  } catch (err) {
    extract.ms = Date.now() - t0;
    const wrapped =
      err instanceof UnsupportedFileError
        ? new InputError('UNSUPPORTED_FILE', err.message, 'extract')
        : new InputError('EXTRACTION_FAILED', `text extraction failed (${branch}): ${err.message}`, 'extract');
    wrapped.input = input;
    wrapped.extract = extract;
    throw wrapped;
  }
  extract.ms = Date.now() - t0;
  text = String(text ?? '');
  extract.chars = text.length;
  extract.truncated = text.trimEnd().endsWith(TRUNCATION_MARKER);
  extract.preview = text.slice(0, PREVIEW_CHARS);
  if (text.trim().length === 0) {
    const err = new InputError('EXTRACTION_FAILED', `no text could be extracted (${branch})`, 'extract');
    err.input = input;
    err.extract = extract;
    throw err;
  }
  return { text, input, extract };
}

// ---------------------------------------------------------------------------
// Phase 2: generate_diagram input modes
// ---------------------------------------------------------------------------

export const INPUT_MODES = ['data', 'fileBase64', 'workspacePath'];
export const WORKSPACE_EXPORT_TIMEOUT_MS = 10_000;

function present(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function inputError(code, message, input, stage = 'input') {
  const err = new InputError(code, message, stage);
  err.input = { ...input, validation: code };
  return err;
}

// Accepts plain base64 or a data URL (data:...;base64,...). Whitespace is ignored.
export function decodeBase64File(fileBase64, input = {}) {
  const clean = String(fileBase64).replace(/^data:[^;,]*;base64,/i, '').replace(/\s+/g, '');
  if (!clean || !/^[A-Za-z0-9+/]+={0,2}$/.test(clean) || clean.length % 4 === 1) {
    throw inputError('INVALID_INPUT', 'fileBase64 is not valid base64', input);
  }
  return Buffer.from(clean, 'base64');
}

// Normalizes a workspace path and enforces the caller's own home folder.
// Returns the path in API form (/Users/<email>/...).
export function scopeWorkspacePath(rawPath, email, input = {}) {
  let p = String(rawPath).trim();
  if (p === '/Volumes' || p.startsWith('/Volumes/')) {
    throw inputError('INVALID_INPUT', '/Volumes paths are not supported; use a workspace file under your own /Users/<you>/ folder', input);
  }
  if (p === '/Workspace' || p.startsWith('/Workspace/')) p = p.slice('/Workspace'.length) || '/';
  if (!p.startsWith('/')) throw inputError('INVALID_INPUT', 'workspacePath must be an absolute path such as /Users/<you>/file.pdf', input);
  const normalized = path.posix.normalize(p).replace(/\/+$/, '');
  if (!present(email)) {
    throw inputError('ACCESS_DENIED', 'Databricks did not forward your identity, so workspace files cannot be read safely', input);
  }
  const home = `/Users/${email.trim()}`;
  const lower = normalized.toLowerCase();
  const homeLower = home.toLowerCase();
  if (lower === homeLower) throw inputError('INVALID_INPUT', 'workspacePath points to your home folder, not a file', input);
  if (!lower.startsWith(`${homeLower}/`)) throw inputError('ACCESS_DENIED', `workspacePath must be inside your own folder ${home}/`, input);
  return normalized;
}

// Reads a workspace file with the caller's forwarded token.
export async function fetchWorkspaceFile(apiPath, userToken, input = {}, timeoutMs = WORKSPACE_EXPORT_TIMEOUT_MS) {
  const host = getWorkspaceHost();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(`${host}/api/2.0/workspace/export?${new URLSearchParams({ path: apiPath, format: 'AUTO' })}`, {
      headers: { Authorization: `Bearer ${userToken}` },
      signal: controller.signal,
    });
  } catch (err) {
    const why = err && err.name === 'AbortError' ? `timed out after ${timeoutMs} ms` : String(err && err.message ? err.message : err);
    throw inputError('EXTRACTION_FAILED', `could not read ${apiPath}: ${why}`, input, 'extract');
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 401 || res.status === 403) {
    throw inputError('ACCESS_DENIED', `the workspace refused access to ${apiPath} (HTTP ${res.status})`, input);
  }
  if (res.status === 404) throw inputError('EXTRACTION_FAILED', `${apiPath} was not found`, input, 'extract');
  if (!res.ok) throw inputError('EXTRACTION_FAILED', `the workspace returned HTTP ${res.status} for ${apiPath}`, input, 'extract');
  let json;
  try {
    json = await res.json();
  } catch {
    json = null;
  }
  if (!json || typeof json.content !== 'string') {
    throw inputError('EXTRACTION_FAILED', `the workspace returned no file content for ${apiPath}`, input, 'extract');
  }
  return Buffer.from(json.content, 'base64');
}

// Validates generate_diagram arguments, reads the input, and extracts text.
// caller = { email, forwardedToken } from the request headers.
// Returns { text, input, extract, buffer }. Throws InputError with `.input`.
export async function prepareInput(args = {}, caller = {}) {
  const given = INPUT_MODES.filter((k) => present(args[k]));
  const base = { mode: given.length === 1 ? given[0] : null, inputsGiven: given };
  if (given.length === 0) {
    throw inputError('INVALID_INPUT', 'provide exactly one input: data (text), fileBase64 with fileName, or workspacePath', base);
  }
  if (given.length > 1) throw inputError('INVALID_INPUT', `provide exactly one input; got ${given.join(', ')}`, base);

  let buffer;
  let fileName;
  const extra = {};
  if (base.mode === 'data') {
    buffer = Buffer.from(args.data, 'utf8');
    fileName = 'data.txt';
  } else if (base.mode === 'fileBase64') {
    if (!present(args.fileName)) throw inputError('INVALID_INPUT', 'fileName is required with fileBase64 (its extension selects the text extractor)', base);
    extra.encodedChars = args.fileBase64.length;
    buffer = decodeBase64File(args.fileBase64, base);
    fileName = path.basename(args.fileName.trim());
  } else {
    const apiPath = scopeWorkspacePath(args.workspacePath, caller.email, base);
    extra.workspacePath = apiPath;
    if (!present(caller.forwardedToken)) {
      throw inputError('ACCESS_DENIED', 'Databricks did not forward your access token, so workspace files cannot be read', { ...base, ...extra });
    }
    buffer = await fetchWorkspaceFile(apiPath, caller.forwardedToken, { ...base, ...extra });
    fileName = path.posix.basename(apiPath);
  }

  try {
    const prepared = await prepareFileInput({ buffer, fileName });
    Object.assign(prepared.input, base, extra, base.mode === 'data' ? { fileName: null, extension: null } : {});
    return { ...prepared, buffer };
  } catch (err) {
    if (err.input) Object.assign(err.input, base, extra);
    throw err;
  }
}
