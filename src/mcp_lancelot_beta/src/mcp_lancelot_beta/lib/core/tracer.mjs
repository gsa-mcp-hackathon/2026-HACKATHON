// Per-run tracing to a Unity Catalog volume (BUILD_PLAN.md section 8a).
//
// Every run (a startup self-test now; MCP tool calls in Phase 2) gets a
// folder under <volume>/runs/<YYYY-MM-DD>/<runId>/ containing:
//   started.json   - tiny marker written when the run begins
//   trace.json     - full structured trace, written at the end
//   artifacts/...  - copies of inputs, prompts, replies, Mermaid, PNGs
//                    (APP_TRACE_LEVEL=debug only)
//
// Writes go through the Databricks Files API with the app's own service
// principal token. Every write is individually caught: a tracing failure is
// logged and recorded, but can never change a tool result or raise an
// unhandled rejection.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { getAccessToken, getWorkspaceHost } from './databricksAuth.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// This file lives in lib/core/, so the app root is two levels up (D37).
export const APP_ROOT = path.join(__dirname, '..', '..');

const DEFAULT_TRACE_VOLUME = 'users.tom_jacobson.lancelot_traces';
const FILES_API_TIMEOUT_MS = 15_000;
const STARTED_MARKER_TIMEOUT_MS = 2_000;
const WRITE_CONCURRENCY = 4;
const DEBUG_ERROR_CHARS = 4_000;

// ---------------------------------------------------------------------------
// Small utilities shared by the other modules
// ---------------------------------------------------------------------------

export function sha256(data) {
  return crypto.createHash('sha256').update(data).digest('hex');
}

// Races `promise` against a timeout. The losing promise keeps running, so a
// no-op catch is attached first to stop a late rejection from becoming an
// unhandled rejection (guide lesson 5.3).
export function withTimeout(promise, ms, message) {
  promise.catch(() => {});
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      const err = new Error(message || `timed out after ${ms} ms`);
      err.isTimeout = true;
      reject(err);
    }, ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

// Reads width/height from a PNG's IHDR chunk. Returns null if not a PNG.
export function pngInfo(buf) {
  if (!Buffer.isBuffer(buf) || buf.length < 24) return null;
  const signature = '89504e470d0a1a0a';
  if (buf.subarray(0, 8).toString('hex') !== signature) return null;
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20), bytes: buf.length };
}

export function slug(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9.]+/g, '-').replace(/^-+|-+$/g, '') || 'item';
}

export function traceLevel() {
  const v = String(process.env.APP_TRACE_LEVEL || 'debug').trim().toLowerCase();
  return v === 'production' ? 'production' : 'debug';
}

// TRACE_VOLUME comes from the app resource `trace-volume` via valueFrom. The
// exact form it resolves to (full name vs. /Volumes path) is unverified, so
// accept either and record what was used.
export function resolveVolumePath(raw = process.env.TRACE_VOLUME) {
  const value = String(raw || DEFAULT_TRACE_VOLUME).trim().replace(/\/+$/, '');
  if (value.startsWith('/Volumes/')) return value;
  const parts = value.split('.');
  if (parts.length === 3 && parts.every((p) => /^[A-Za-z0-9_-]+$/.test(p))) {
    return `/Volumes/${parts.join('/')}`;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Fault injection for the manual V19 test ONLY (docs/V19_TRACE_FAILURE_TEST.md)
// ---------------------------------------------------------------------------
//
// Never set these in app.yaml. They are supplied only as a one-off
// deployment override when the user explicitly asks for V19 (decision D17).
//   TRACE_FAULT_INJECT        comma-separated path substrings; any trace write
//                             whose volume path contains one of them fails
//                             on purpose, before any network call
//   TRACE_FAULT_INJECT_UNTIL  ISO timestamp, required; must be in the future
//                             and at most 2 hours after process start.
//                             Injection stops by itself once it passes.
// If either rule is not met, injection stays off and the reason is recorded.
const FAULT_INJECT_MAX_WINDOW_MS = 2 * 60 * 60 * 1000;

export function faultInjectionConfig(env = process.env, now = Date.now()) {
  const raw = String(env.TRACE_FAULT_INJECT || '').trim();
  if (!raw) return { active: false, tokens: [], until: null, ignoredReason: null };
  const tokens = raw.split(',').map((t) => t.trim()).filter(Boolean);
  const untilRaw = String(env.TRACE_FAULT_INJECT_UNTIL || '').trim();
  const until = Date.parse(untilRaw);
  const off = (ignoredReason) => ({ active: false, tokens, until: untilRaw || null, ignoredReason });
  if (tokens.length === 0) return off('TRACE_FAULT_INJECT has no path tokens');
  if (!untilRaw || Number.isNaN(until)) return off('TRACE_FAULT_INJECT_UNTIL is missing or not an ISO timestamp');
  if (until <= now) return off('TRACE_FAULT_INJECT_UNTIL is in the past');
  if (until - now > FAULT_INJECT_MAX_WINDOW_MS) return off('TRACE_FAULT_INJECT_UNTIL is more than 2 hours after process start');
  return { active: true, tokens, until: new Date(until).toISOString(), ignoredReason: null };
}

const FAULT_INJECTION = faultInjectionConfig();
if (FAULT_INJECTION.tokens.length) {
  console.warn(
    FAULT_INJECTION.active
      ? `[tracer] V19 FAULT INJECTION ACTIVE until ${FAULT_INJECTION.until}: trace writes matching [${FAULT_INJECTION.tokens.join(', ')}] will fail on purpose`
      : `[tracer] V19 fault injection requested but IGNORED: ${FAULT_INJECTION.ignoredReason}`
  );
}

export function faultInjection() {
  return FAULT_INJECTION;
}

function injectedFaultFor(absPath, now = Date.now()) {
  if (!FAULT_INJECTION.active || now >= Date.parse(FAULT_INJECTION.until)) return null;
  const token = FAULT_INJECTION.tokens.find((t) => absPath.includes(t));
  return token ? `injected fault (V19, TRACE_FAULT_INJECT token "${token}")` : null;
}

export function newRunId(kind) {
  const ts = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
  return `${kind}-${ts}-${crypto.randomBytes(3).toString('hex')}`;
}

function errorText(err) {
  if (err == null) return '';
  if (typeof err === 'string') return err;
  return String(err.message || err);
}

// ---------------------------------------------------------------------------
// Files API (Unity Catalog volumes)
// ---------------------------------------------------------------------------

function encodeVolumePath(p) {
  return p.split('/').map((segment) => encodeURIComponent(segment)).join('/');
}

async function filesApi(method, apiPath, { body, contentType, timeoutMs = FILES_API_TIMEOUT_MS } = {}) {
  const host = getWorkspaceHost();
  const token = await getAccessToken();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = { Authorization: `Bearer ${token}` };
    if (contentType) headers['Content-Type'] = contentType;
    const res = await fetch(`${host}${apiPath}`, { method, headers, body, signal: controller.signal });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      const err = new Error(`Files API ${method} ${res.status}: ${text.slice(0, 300)}`);
      err.status = res.status;
      throw err;
    }
    return res;
  } finally {
    clearTimeout(timer);
  }
}

export async function createDirectory(dirPath) {
  await filesApi('PUT', `/api/2.0/fs/directories${encodeVolumePath(dirPath)}`);
}

export async function putFile(filePath, data, contentType = 'application/octet-stream') {
  const body = Buffer.isBuffer(data) ? data : Buffer.from(String(data), 'utf8');
  await filesApi('PUT', `/api/2.0/fs/files${encodeVolumePath(filePath)}?overwrite=true`, { body, contentType });
}

export async function getFile(filePath) {
  const res = await filesApi('GET', `/api/2.0/fs/files${encodeVolumePath(filePath)}`);
  return Buffer.from(await res.arrayBuffer());
}

// ---------------------------------------------------------------------------
// Version information (which code produced a trace)
// ---------------------------------------------------------------------------

const HASHED_SOURCE_FILES = ['package.json', 'app.yaml', 'server.mjs'];

// sha256 over "<sha256>  <relative path>\n" lines for package.json, app.yaml,
// server.mjs and every lib/**/*.mjs (all subfolders, D37), sorted by path. The agent recomputes the same
// value from the Git tree to match a trace to a commit, even if VERSION.json
// is missing from the deployment.
export function computeSourceHash(root = APP_ROOT) {
  const files = [...HASHED_SOURCE_FILES];
  try {
    const stack = ['lib'];
    while (stack.length) {
      const rel = stack.pop();
      for (const entry of fs.readdirSync(path.join(root, rel), { withFileTypes: true })) {
        const child = `${rel}/${entry.name}`;
        if (entry.isDirectory()) stack.push(child);
        else if (entry.isFile() && entry.name.endsWith('.mjs')) files.push(child);
      }
    }
  } catch {
    // lib/ missing would be reported by the self-test itself
  }
  files.sort();
  const lines = [];
  const missing = [];
  for (const rel of files) {
    try {
      lines.push(`${sha256(fs.readFileSync(path.join(root, rel)))}  ${rel}\n`);
    } catch {
      missing.push(rel);
    }
  }
  return { sourceHash: sha256(lines.join('')), files: files.length, missing };
}

function readVersionFile() {
  try {
    const raw = fs.readFileSync(path.join(APP_ROOT, 'VERSION.json'), 'utf8').trim();
    try {
      return JSON.parse(raw);
    } catch {
      return { raw };
    }
  } catch {
    return null;
  }
}

function installedVersion(pkg) {
  try {
    const p = path.join(APP_ROOT, 'node_modules', ...pkg.split('/'), 'package.json');
    return JSON.parse(fs.readFileSync(p, 'utf8')).version || null;
  } catch {
    return null;
  }
}

export function collectVersion() {
  const packages = {};
  for (const pkg of ['mermaid', 'jsdom', '@resvg/resvg-js', 'pdf-parse', 'opentype.js', 'dejavu-fonts-ttf', 'mammoth', 'exceljs', 'express', '@modelcontextprotocol/sdk', 'zod']) {
    packages[pkg] = installedVersion(pkg);
  }
  return {
    versionFile: readVersionFile(),
    ...computeSourceHash(),
    node: process.version,
    appName: process.env.DATABRICKS_APP_NAME || null,
    packages,
  };
}

// ---------------------------------------------------------------------------
// Tracer
// ---------------------------------------------------------------------------

export class Tracer {
  constructor(kind) {
    this.kind = kind;
    this.level = traceLevel();
    this.runId = newRunId(kind);
    this.startedAtMs = Date.now();
    const startedAt = new Date(this.startedAtMs).toISOString();
    this.volumeRoot = resolveVolumePath();
    this.runDir = this.volumeRoot ? `${this.volumeRoot}/runs/${startedAt.slice(0, 10)}/${this.runId}` : null;
    this.artifacts = new Map(); // relative path (under artifacts/) -> Buffer
    this.extraFiles = []; // { absPath, data, contentType }
    this.llmRecords = []; // full LLM attempt records (kept in memory for the report)
    this.llmSeq = 0;
    this.writeErrors = [];
    this.createdDirs = new Set();
    this.trace = {
      run: { runId: this.runId, kind, startedAt, finishedAt: null, totalMs: null, outcome: null, errorCode: null, errorStage: null },
      version: collectVersion(),
      config: {
        traceLevel: this.level,
        traceVolumeEnv: process.env.TRACE_VOLUME ?? null,
        resolvedVolumePath: this.volumeRoot,
        llmPrimary: process.env.LLM_ENDPOINT_PRIMARY ?? null,
        llmFallback: process.env.LLM_ENDPOINT_FALLBACK ?? null,
        startupSelftest: process.env.STARTUP_SELFTEST ?? null,
        faultInjection: FAULT_INJECTION,
      },
      llm: [],
      tracer: { writeErrors: this.writeErrors },
    };
  }

  get debug() {
    return this.level === 'debug';
  }

  // Content (document text, prompts, rationale, previews) is kept only at debug.
  text(value) {
    return this.debug ? value : undefined;
  }

  // Error messages from the renderer/LLM endpoints can contain document or
  // Mermaid fragments, so at production only their length is kept.
  errorMessage(err) {
    const msg = errorText(err);
    if (this.debug) return msg.slice(0, DEBUG_ERROR_CHARS);
    return msg ? `[redacted: ${msg.length} chars]` : '';
  }

  artifact(relPath, data) {
    if (!this.debug) return;
    let buf;
    if (Buffer.isBuffer(data)) buf = data;
    else if (typeof data === 'string') buf = Buffer.from(data, 'utf8');
    else buf = Buffer.from(JSON.stringify(data, null, 2), 'utf8');
    this.artifacts.set(relPath, buf);
  }

  getArtifact(relPath) {
    return this.artifacts.get(relPath) || null;
  }

  // Records one LLM attempt (successful, failed, skipped, or fallback). The
  // summary goes into trace.json at every level; the full record (request
  // messages, reply or error body) goes to artifacts/llm/ at debug only.
  recordLlm(full) {
    this.llmSeq += 1;
    const n = String(this.llmSeq).padStart(2, '0');
    const file = `llm/${n}-${slug(full.step)}-${slug(full.endpoint || 'none')}.json`;
    const summary = {
      seq: this.llmSeq,
      step: full.step,
      label: full.label ?? null,
      endpoint: full.endpoint ?? null,
      attemptIndex: full.attemptIndex ?? 0,
      fallback: !!full.fallback,
      skipped: !!full.skipped,
      skipReason: full.skipReason ?? null,
      timeoutMs: full.timeoutMs ?? null,
      status: full.status ?? null,
      ms: full.ms ?? null,
      errorClass: full.errorClass ?? null,
      finishReason: full.finishReason ?? null,
      usage: full.usage ?? null,
      replyChars: typeof full.replyText === 'string' ? full.replyText.length : null,
      artifact: this.debug ? file : null,
    };
    this.trace.llm.push(summary);
    if (this.debug) {
      const record = { ...summary, request: full.request ?? null, response: full.response ?? null, replyText: full.replyText ?? null, errorBody: full.errorBody ?? null };
      this.llmRecords.push(record);
      this.artifact(file, record);
    }
    return summary;
  }

  setOutcome(outcome, errorCode = null, errorStage = null) {
    this.trace.run.outcome = outcome;
    this.trace.run.errorCode = errorCode;
    this.trace.run.errorStage = errorStage;
  }

  markFinished() {
    const now = Date.now();
    this.trace.run.finishedAt = new Date(now).toISOString();
    this.trace.run.totalMs = now - this.startedAtMs;
  }

  // Extra files outside this run's folder, e.g. latest/startup-report.html.
  addFile(relativeToVolume, data, contentType) {
    if (!this.volumeRoot) return;
    this.extraFiles.push({ absPath: `${this.volumeRoot}/${relativeToVolume}`, data, contentType });
  }

  // Files inside this run's folder (not under artifacts/), e.g. report.html.
  addRunFile(name, data, contentType) {
    if (!this.runDir) return;
    this.extraFiles.push({ absPath: `${this.runDir}/${name}`, data, contentType });
  }

  noteWriteError(what, err) {
    const entry = { what, error: errorText(err).slice(0, 300), injected: !!(err && err.injected), at: new Date().toISOString() };
    this.writeErrors.push(entry);
    console.error(`[tracer] ${this.runId} write failed: ${what}: ${entry.error}`);
  }

  async ensureDir(dirPath) {
    if (this.createdDirs.has(dirPath)) return;
    await createDirectory(dirPath);
    this.createdDirs.add(dirPath);
  }

  async safeWrite(absPath, data, contentType) {
    try {
      const injected = injectedFaultFor(absPath);
      if (injected) {
        const err = new Error(injected);
        err.injected = true;
        throw err;
      }
      await this.ensureDir(path.posix.dirname(absPath));
      await putFile(absPath, data, contentType);
      return true;
    } catch (err) {
      this.noteWriteError(absPath, err);
      return false;
    }
  }

  async writeStarted() {
    if (!this.runDir) {
      this.noteWriteError('started.json', new Error(`cannot resolve trace volume from TRACE_VOLUME=${process.env.TRACE_VOLUME ?? '(unset)'}`));
      return false;
    }
    const marker = { runId: this.runId, kind: this.kind, startedAt: this.trace.run.startedAt, traceLevel: this.level, sourceHash: this.trace.version.sourceHash };
    try {
      return await withTimeout(this.safeWrite(`${this.runDir}/started.json`, JSON.stringify(marker, null, 2), 'application/json'), STARTED_MARKER_TIMEOUT_MS, 'started.json write timed out');
    } catch (err) {
      this.noteWriteError('started.json', err);
      return false;
    }
  }

  // Writes artifacts and extra files, then trace.json last (so trace.json
  // also records any earlier write failures). Never throws.
  async finish() {
    if (!this.trace.run.finishedAt) this.markFinished();
    if (!this.runDir) {
      console.error(`[tracer] ${this.runId} has no trace volume; trace not written`);
      return { written: false, runDir: null };
    }
    const jobs = [];
    for (const [rel, buf] of this.artifacts) {
      const contentType = rel.endsWith('.png') ? 'image/png' : rel.endsWith('.json') ? 'application/json' : 'text/plain';
      jobs.push({ absPath: `${this.runDir}/artifacts/${rel}`, data: buf, contentType });
    }
    jobs.push(...this.extraFiles);
    let next = 0;
    const worker = async () => {
      while (next < jobs.length) {
        const job = jobs[next++];
        await this.safeWrite(job.absPath, job.data, job.contentType);
      }
    };
    await Promise.all(Array.from({ length: Math.min(WRITE_CONCURRENCY, jobs.length) }, worker));
    this.trace.tracer.artifactCount = this.artifacts.size;
    this.trace.tracer.extraFileCount = this.extraFiles.length;
    const ok = await this.safeWrite(`${this.runDir}/trace.json`, JSON.stringify(this.trace, null, 2), 'application/json');
    return { written: ok, runDir: this.runDir, writeErrors: this.writeErrors.length };
  }
}
