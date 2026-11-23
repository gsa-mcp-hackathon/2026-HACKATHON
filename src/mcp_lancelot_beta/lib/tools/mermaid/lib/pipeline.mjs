// The stateless diagram pipeline (BUILD_PLAN.md sections 4 and 5):
//   select type (unless given) -> write Mermaid -> render PNG
//   -> one syntax-only repair if the renderer rejects the Mermaid
//   -> one resize retry if the PNG would exceed the renderer's size limit (D28).
//
// One request-wide deadline covers every stage. Every LLM attempt,
// including failed, skipped, and fallback attempts, is recorded through the
// tracer (section 8a).
import { getAccessToken, getWorkspaceHost } from '../../../core/databricksAuth.mjs';
import { buildDiagramSyntaxPrompt } from './prompts.mjs';
import { findAllowedDiagramType, rejectionReason } from './diagramPolicy.mjs';
import { renderMermaid, ValidationError } from './render.mjs';
import { selectDiagramType } from './selection.mjs';
import { pngInfo, sha256, withTimeout } from '../../../core/tracer.mjs';

export const BUDGET_MS = 70_000;
export const SELECT_CAP_MS = 12_000;
export const GENERATE_CAP_MS = 45_000;
export const GENERATE_RESERVE_MS = 25_000; // left for rendering (+ possible repair) after generation
export const RENDER_CAP_MS = 40_000;
export const REPAIR_MIN_REMAINING_MS = 20_000;
export const MIN_FALLBACK_MS = 12_000;
export const GENERATE_MAX_TOKENS = 8192;
const REPAIR_ERROR_CHARS = 500;
// Aim 10% under the renderer's limit so one resize attempt usually fits.
const RESIZE_MARGIN = 0.9;
// Exact wording of the size check in the verbatim lib/render.mjs (svgToPng).
const TOO_LARGE_RE = /too large to rasterize safely \(~(\d+)x(\d+)px, max (\d+)px per side\)/;

const OUTPUT_INSTRUCTION =
  'CRITICAL OUTPUT RULE: Output ONLY the Mermaid diagram source in a single fenced code block that starts with ```mermaid and ends with ```. Do not write any prose before or after the code block.';

export class PipelineError extends Error {
  constructor(code, stage, message, extra = {}) {
    super(message);
    this.name = 'PipelineError';
    this.code = code; // LLM_TIMEOUT | LLM_ERROR | RENDER_FAILED
    this.stage = stage;
    Object.assign(this, extra);
  }
}

export function endpointChain() {
  return [process.env.LLM_ENDPOINT_PRIMARY, process.env.LLM_ENDPOINT_FALLBACK]
    .map((value) => (typeof value === 'string' ? value.trim() : ''))
    .filter(Boolean);
}

// Chat `content` may be a string or an array of typed blocks (reasoning
// models). Keep only user-facing text blocks.
export function replyText(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content
      .filter((part) => part && part.type === 'text' && typeof part.text === 'string')
      .map((part) => part.text)
      .join('\n');
  }
  return '';
}

async function invokeEndpoint(endpoint, body, timeoutMs) {
  const t0 = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const host = getWorkspaceHost();
    const token = await getAccessToken();
    const res = await fetch(`${host}/serving-endpoints/${encodeURIComponent(endpoint)}/invocations`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const rawText = await res.text();
    let json = null;
    try {
      json = rawText ? JSON.parse(rawText) : null;
    } catch {
      json = null;
    }
    return { status: res.status, ok: res.ok, json, rawText, ms: Date.now() - t0, errorClass: res.ok && !json ? 'bad_json' : null };
  } catch (err) {
    const errorClass = err && err.name === 'AbortError' ? 'timeout' : 'network';
    return { status: null, ok: false, json: null, rawText: String(err && err.message ? err.message : err), ms: Date.now() - t0, errorClass };
  } finally {
    clearTimeout(timer);
  }
}

// Returns callLlm({ step, messages, maxTokens, stageCapMs }) that walks the
// endpoint chain (LLM_ENDPOINT_PRIMARY -> LLM_ENDPOINT_FALLBACK; model-agnostic,
// D25). Falls through only on timeout,
// network error, bad JSON, empty reply, 429, or 5xx; any other HTTP error is
// a configuration problem and stops with LLM_ERROR.
export function makeLlmCaller({ tracer, deadlineAt, endpoints = endpointChain(), label = null }) {
  return async function callLlm({ step, messages, maxTokens, stageCapMs }) {
    if (endpoints.length === 0) {
      throw new PipelineError('LLM_ERROR', step, 'no LLM endpoints configured (LLM_ENDPOINT_PRIMARY / LLM_ENDPOINT_FALLBACK are empty)');
    }
    const failures = [];
    for (let i = 0; i < endpoints.length; i += 1) {
      const endpoint = endpoints[i];
      const remaining = deadlineAt - Date.now();
      if (i > 0 && remaining < MIN_FALLBACK_MS) {
        const skipReason = `only ${Math.max(0, remaining)} ms left in the request budget (minimum ${MIN_FALLBACK_MS} ms for a fallback)`;
        tracer?.recordLlm({ step, label, endpoint, attemptIndex: i, fallback: true, skipped: true, skipReason, errorClass: 'skipped_budget' });
        failures.push({ endpoint, errorClass: 'skipped_budget' });
        continue;
      }
      if (remaining <= 1_000) {
        failures.push({ endpoint, errorClass: 'budget_exhausted' });
        break;
      }
      const timeoutMs = Math.max(1_000, Math.min(stageCapMs ?? remaining, remaining - 1_000));
      // No `temperature` or other sampling parameters: databricks-gemini-3-8-flash
      // rejected `temperature` with HTTP 400 (first Phase 1 startup trace,
      // 2026-11-04). `{ messages, max_tokens }` is verified with Gemini 3.8 Flash,
      // Grok 4.6, Claude Haiku 4.5, and GPT-5.4 Mini (model-compare, 2026-11-05).
      const body = { messages, max_tokens: maxTokens };
      const r = await invokeEndpoint(endpoint, body, timeoutMs);
      const choice = r.json?.choices?.[0];
      const text = r.ok && r.json ? replyText(choice?.message?.content).trim() : '';
      let errorClass = r.errorClass;
      if (!errorClass && !r.ok) errorClass = `http_${r.status}`;
      if (!errorClass && !text) errorClass = 'empty_reply';
      tracer?.recordLlm({
        step,
        label,
        endpoint,
        attemptIndex: i,
        fallback: i > 0,
        timeoutMs,
        status: r.status,
        ms: r.ms,
        errorClass,
        finishReason: choice?.finish_reason ?? null,
        usage: r.json?.usage ?? null,
        request: body,
        response: r.json,
        replyText: text || null,
        errorBody: errorClass ? r.rawText : null,
      });
      if (!errorClass) return { text, endpoint, ms: r.ms, usage: r.json?.usage ?? null };
      failures.push({ endpoint, errorClass, status: r.status });
      const retryable = ['timeout', 'network', 'bad_json', 'empty_reply'].includes(errorClass) || r.status === 429 || (r.status ?? 0) >= 500;
      if (!retryable) {
        throw new PipelineError('LLM_ERROR', step, `endpoint ${endpoint} rejected the request (HTTP ${r.status})`, { failures });
      }
    }
    const timedOut = deadlineAt - Date.now() <= 1_000 || failures.every((f) => ['timeout', 'skipped_budget', 'budget_exhausted'].includes(f.errorClass));
    throw new PipelineError(timedOut ? 'LLM_TIMEOUT' : 'LLM_ERROR', step, `all LLM endpoints failed for step "${step}": ${failures.map((f) => `${f.endpoint}=${f.errorClass}`).join(', ')}`, { failures });
  };
}

// Pulls the Mermaid source out of a model reply.
export function extractMermaid(reply) {
  const text = String(reply ?? '');
  const fenced = text.match(/```[ \t]*mermaid[^\n]*\n([\s\S]*?)```/i) || text.match(/```[^\n]*\n([\s\S]*?)```/);
  if (fenced && fenced[1].trim()) return { source: fenced[1].trim(), fenced: true };
  return { source: text.trim(), fenced: false };
}

// Deterministic fixes for Mermaid mistakes the models repeat and the one repair step does not
// fix (client case V9, 2026-11-06). Returns { source, fixes } where fixes lists what changed.
// - Invisible "blank" characters that are not whitespace to Mermaid's lexers (U+2800 braille
//   blank, U+3164 Hangul filler) become spaces; zero-width ones (U+200B, U+FEFF) are removed.
//   Seen: "title\u2800Pokemon Trainer's First Week" -> "Expecting 'taskData', got 'NEWLINE'".
// - User journey: section and title text may not contain ':' ';' '#' (the journey lexer reads
//   ':' as the start of task data). "section Day 1: Getting Started" -> "section Day 1 - Getting
//   Started". Task lines ("name: score: actors") are left alone.
const BLANK_LIKE = /[\u2800\u3164]/g;
const ZERO_WIDTH = /[\u200B\uFEFF]/g;

export function diagramKeyword(source) {
  const lines = String(source ?? '').split('\n');
  let i = 0;
  if (lines[0]?.trim() === '---') {
    const end = lines.findIndex((l, j) => j > 0 && l.trim() === '---');
    i = end > 0 ? end + 1 : 0;
  }
  for (; i < lines.length; i++) {
    const t = lines[i].trim();
    if (!t || t.startsWith('%%')) continue;
    return t.split(/[\s:{]/)[0].toLowerCase();
  }
  return null;
}

export function fixKnownSyntax(source) {
  const fixes = [];
  let text = String(source ?? '');
  const blanks = (text.match(BLANK_LIKE) || []).length;
  const zeros = (text.match(ZERO_WIDTH) || []).length;
  if (blanks) { text = text.replace(BLANK_LIKE, ' '); fixes.push({ rule: 'blank-like-to-space', count: blanks }); }
  if (zeros) { text = text.replace(ZERO_WIDTH, ''); fixes.push({ rule: 'zero-width-removed', count: zeros }); }
  if (diagramKeyword(text) === 'journey') {
    let sections = 0;
    let titles = 0;
    text = text.split('\n').map((line) => {
      const s = line.match(/^(\s*section\s+)(.*)$/);
      if (s && /[:;#]/.test(s[2])) {
        sections++;
        const rest = s[2].replace(/\s*:\s*$/, '').replace(/\s*:\s*/g, ' - ').replace(/;/g, ',').replace(/#/g, '').replace(/\s{2,}/g, ' ').trim();
        return s[1] + rest;
      }
      const t = line.match(/^(\s*title\s+)(.*)$/);
      if (t && /[;#]/.test(t[2])) {
        titles++;
        return t[1] + t[2].replace(/;/g, ',').replace(/#/g, '').replace(/\s{2,}/g, ' ').trim();
      }
      return line;
    }).join('\n');
    if (sections) fixes.push({ rule: 'journey-section-punctuation', count: sections });
    if (titles) fixes.push({ rule: 'journey-title-punctuation', count: titles });
  }
  return { source: text, fixes };
}

// Reads the PNG size the renderer refused (D28). Returns { width, height, maxPx } or null.
export function parseTooLarge(message) {
  const m = TOO_LARGE_RE.exec(String(message ?? ''));
  if (!m) return null;
  const [width, height, maxPx] = m.slice(1).map(Number);
  return width > 0 && height > 0 && maxPx > 0 ? { width, height, maxPx } : null;
}

// Lines that describe diagram content: not blank, not %% comments or
// directives, not front matter, not styling. Only a rough guide for the
// model (D28 amendment); "too big" is still measured on the PNG.
const STYLE_LINE_RE = /^(classDef|class|style|linkStyle|accTitle|accDescr)\b/;
export function countContentLines(source) {
  const lines = String(source ?? '').split(/\r?\n/).map((l) => l.trim());
  let i = 0;
  if (lines[0] === '---') {
    const end = lines.indexOf('---', 1);
    i = end > 0 ? end + 1 : 0;
  }
  return lines.slice(i).filter((l) => l && !l.startsWith('%%') && !STYLE_LINE_RE.test(l)).length;
}

// The follow-up instruction for the one resize attempt (D28, tightened):
// measured size, the cut needed (and not much more), that size comes from
// the number of items rather than label length, a rough line-count target,
// same diagram type.
export function resizeInstruction(typeName, { width, height, maxPx }, source = '') {
  const factor = (maxPx / Math.max(width, height)) * RESIZE_MARGIN;
  // Round first so floating-point noise (e.g. 20.000000000000004) does not add a percent.
  const cutPct = Math.min(90, Math.max(10, Math.ceil(Number(((1 - factor) * 100).toFixed(6)))));
  const side = height >= width ? 'height' : 'width';
  const lines = countContentLines(source);
  const targetLines = Math.max(3, Math.floor(lines * (1 - cutPct / 100)));
  return [
    `The rendered diagram is too large: about ${width} x ${height} px, but the maximum is ${maxPx} px per side.`,
    `Make it fit: reduce its ${side} by at least ${cutPct}%, but not much more than that. Keep as much of the content as fits.`,
    'The size comes from how many items, rows, and nodes the diagram has. Shortening labels or text alone will NOT make it fit: show fewer items. Merge closely related items, group minor details into one summary item, or keep only the most important ones. Changing the layout direction (for example top-down to left-right) can also help if this diagram type supports it.',
    lines >= 10 ? `As a rough guide, your diagram has about ${lines} content lines; aim for about ${targetLines}. The rendered size is what counts.` : null,
    `Keep the ${typeName} diagram type and the DHS color rules.`,
    OUTPUT_INSTRUCTION,
  ]
    .filter(Boolean)
    .join('\n\n');
}

async function renderAttempt(attempt, source, deadlineAt, tracer) {
  const record = { attempt, ms: null, outcome: null, error: null, pngBytes: null, width: null, height: null, pngSha256: null };
  const capMs = Math.min(RENDER_CAP_MS, deadlineAt - Date.now());
  const t0 = Date.now();
  if (capMs < 1_000) {
    record.outcome = 'timeout';
    record.error = 'no time left in the request budget to render';
    record.ms = 0;
    return { record, png: null, errorMessage: record.error };
  }
  try {
    const result = await withTimeout(renderMermaid({ mermaid: source, format: 'png' }), capMs, `render timed out after ${capMs} ms`);
    record.ms = Date.now() - t0;
    if (result.pngFailed || !result.png) {
      record.outcome = 'png_failed';
      record.error = tracer ? tracer.errorMessage(result.pngError || 'no PNG returned') : result.pngError;
      return { record, png: null, errorMessage: result.pngError || 'no PNG returned' };
    }
    const png = Buffer.from(result.png, 'base64');
    const info = pngInfo(png);
    record.outcome = 'ok';
    record.pngBytes = png.length;
    record.width = info?.width ?? null;
    record.height = info?.height ?? null;
    record.pngSha256 = sha256(png);
    return { record, png, errorMessage: null };
  } catch (err) {
    record.ms = Date.now() - t0;
    record.outcome = err instanceof ValidationError ? 'validation_error' : err && err.isTimeout ? 'timeout' : 'error';
    record.error = tracer ? tracer.errorMessage(err) : String(err?.message || err);
    return { record, png: null, errorMessage: String(err?.message || err) };
  }
}

// Runs the pipeline on already-extracted text.
// `record` is filled in as stages complete, so callers keep partial data
// even when this throws. Artifacts go under `artifactPrefix` (debug only).
export async function runPipeline({ text, hint = null, diagramType = null, deadlineAt, tracer = null, record = {}, artifactPrefix = '', label = null }) {
  const keep = (value) => (tracer ? tracer.text(value) : value);
  const callLlm = makeLlmCaller({ tracer, deadlineAt, label });
  record.select = null;
  record.generate = null;
  record.repair = null;
  record.resize = null;
  record.render = [];

  // Step 1: diagram type
  // `rationale` is returned to the caller as-is; the trace copy goes through keep().
  let rationale = null;
  // A requested type that is unsupported or excluded (D29) is ignored and the
  // type is chosen automatically; the trace records why.
  let entry = diagramType ? findAllowedDiagramType(diagramType) : null;
  const requestedRejected = diagramType && !entry ? rejectionReason(diagramType) : null;
  if (entry) {
    record.select = { skipped: true, requested: diagramType, chosen: entry.name };
  } else {
    const remaining = deadlineAt - Date.now();
    const sel = await selectDiagramType({ documentText: text, hint, callLlm, stageCapMs: Math.min(SELECT_CAP_MS, remaining) });
    entry = sel.entry;
    rationale = sel.rationale ?? null;
    record.select = {
      skipped: false,
      requested: diagramType,
      requestedRejected,
      outcome: sel.outcome,
      chosen: entry.name,
      modelSaid: sel.requestedName,
      reason: sel.reason,
      rationale: keep(sel.rationale),
      endpoint: sel.endpoint,
      ms: sel.ms,
    };
  }

  // Step 2: write Mermaid
  const messages = [
    { role: 'system', content: `${buildDiagramSyntaxPrompt(entry.name)}\n\n${OUTPUT_INSTRUCTION}` },
    {
      role: 'user',
      content: [`Generate a ${entry.name} diagram for the following document.`, hint ? `Focus requested by the user: ${hint}` : null, 'Document:', text]
        .filter(Boolean)
        .join('\n\n'),
    },
  ];
  const genCap = Math.min(GENERATE_CAP_MS, deadlineAt - Date.now() - GENERATE_RESERVE_MS);
  if (genCap < 5_000) {
    throw new PipelineError('LLM_TIMEOUT', 'generate', `not enough time left to generate (${genCap} ms after reserving ${GENERATE_RESERVE_MS} ms for rendering)`);
  }
  const gen = await callLlm({ step: 'generate', messages, maxTokens: GENERATE_MAX_TOKENS, stageCapMs: genCap });
  // Model output -> what is rendered. Fixes are recorded; the model's raw text is kept as
  // attemptN.raw.mmd when a fix changed it.
  const prepare = (raw, step, n) => {
    const f = fixKnownSyntax(raw);
    if (f.fixes.length) {
      (record.syntaxFixes ||= []).push({ step, fixes: f.fixes, rawSha256: sha256(raw) });
      tracer?.artifact(`${artifactPrefix}attempt${n}.raw.mmd`, raw);
    }
    return f.source;
  };
  let { source: genRaw, fenced } = extractMermaid(gen.text);
  let source = prepare(genRaw, 'generate', 1);
  record.generate = { endpoint: gen.endpoint, ms: gen.ms, fenced, mermaidChars: source.length, mermaidSha256: sha256(source) };
  tracer?.artifact(`${artifactPrefix}attempt1.mmd`, source);

  // Step 3: render (+ one syntax-only repair)
  let attempt = await renderAttempt(1, source, deadlineAt, tracer);
  record.render.push(attempt.record);
  let repaired = false;
  let endpointUsed = gen.endpoint;

  if (attempt.record.outcome === 'validation_error') {
    const remaining = deadlineAt - Date.now();
    if (remaining < REPAIR_MIN_REMAINING_MS) {
      throw new PipelineError('RENDER_FAILED', 'render', `Mermaid was rejected and only ${remaining} ms remain (repair needs ${REPAIR_MIN_REMAINING_MS} ms)`, { mermaidSource: keep(source) });
    }
    const repairMessages = [
      ...messages,
      { role: 'assistant', content: `\`\`\`mermaid\n${source}\n\`\`\`` },
      {
        role: 'user',
        content: [
          'The Mermaid renderer rejected your diagram with this error:',
          attempt.errorMessage.slice(0, REPAIR_ERROR_CHARS),
          `Fix the error while keeping the ${entry.name} diagram type and the DHS color rules. ${OUTPUT_INSTRUCTION}`,
        ].join('\n\n'),
      },
    ];
    const rep = await callLlm({ step: 'repair', messages: repairMessages, maxTokens: GENERATE_MAX_TOKENS, stageCapMs: Math.min(GENERATE_CAP_MS, remaining - 10_000) });
    const fixed = extractMermaid(rep.text);
    source = prepare(fixed.source, 'repair', 2);
    repaired = true;
    endpointUsed = rep.endpoint;
    record.repair = { endpoint: rep.endpoint, ms: rep.ms, fenced: fixed.fenced, mermaidChars: source.length, mermaidSha256: sha256(source) };
    tracer?.artifact(`${artifactPrefix}attempt2.mmd`, source);
    attempt = await renderAttempt(2, source, deadlineAt, tracer);
    record.render.push(attempt.record);
  }

  // Step 4: one resize retry (D28). "Too big" is measured on the rendered PNG
  // (exact for every diagram type), not guessed from the Mermaid text.
  let resize = null;
  const tooLarge = attempt.record.outcome === 'png_failed' ? parseTooLarge(attempt.errorMessage) : null;
  if (tooLarge) {
    resize = { originalWidth: tooLarge.width, originalHeight: tooLarge.height, maxPx: tooLarge.maxPx };
    const remaining = deadlineAt - Date.now();
    if (remaining < REPAIR_MIN_REMAINING_MS) {
      throw new PipelineError(
        'RENDER_FAILED',
        'rasterize',
        `diagram too large (~${tooLarge.width}x${tooLarge.height}px, max ${tooLarge.maxPx}px per side) and only ${remaining} ms remain for a resize attempt (needs ${REPAIR_MIN_REMAINING_MS} ms)`,
        { mermaidSource: keep(source), pngError: keep(attempt.errorMessage), resize }
      );
    }
    const resizeMessages = [
      ...messages,
      { role: 'assistant', content: `\`\`\`mermaid\n${source}\n\`\`\`` },
      { role: 'user', content: resizeInstruction(entry.name, tooLarge, source) },
    ];
    const rs = await callLlm({ step: 'resize', messages: resizeMessages, maxTokens: GENERATE_MAX_TOKENS, stageCapMs: Math.min(GENERATE_CAP_MS, remaining - 10_000) });
    const fixed = extractMermaid(rs.text);
    const linesBefore = countContentLines(source);
    const n = record.render.length + 1;
    source = prepare(fixed.source, 'resize', n);
    endpointUsed = rs.endpoint;
    record.resize = { endpoint: rs.endpoint, ms: rs.ms, fenced: fixed.fenced, mermaidChars: source.length, mermaidSha256: sha256(source), contentLinesBefore: linesBefore, contentLinesAfter: countContentLines(source), ...resize };
    tracer?.artifact(`${artifactPrefix}attempt${n}.mmd`, source);
    attempt = await renderAttempt(n, source, deadlineAt, tracer);
    record.render.push(attempt.record);
  }

  const outcome = attempt.record.outcome;
  if (outcome !== 'ok') {
    const stage = outcome === 'png_failed' ? 'rasterize' : 'render';
    let why = `render outcome: ${outcome}`;
    if (resize) why = `diagram still could not be rendered after one resize attempt (${outcome})`;
    else if (outcome === 'validation_error' && repaired) why = 'Mermaid was still rejected after one repair attempt';
    throw new PipelineError('RENDER_FAILED', stage, `${why}: ${attempt.errorMessage}`, {
      mermaidSource: keep(source),
      pngError: outcome === 'png_failed' ? keep(attempt.errorMessage) : undefined,
      resize: resize ?? undefined,
    });
  }
  if (resize) {
    Object.assign(resize, {
      finalWidth: attempt.record.width,
      finalHeight: attempt.record.height,
      note: `Diagram was simplified to fit: the first version would have been about ${resize.originalWidth} x ${resize.originalHeight} px (max ${resize.maxPx} px per side); the final image is ${attempt.record.width} x ${attempt.record.height} px.`,
    });
  }

  tracer?.artifact(`${artifactPrefix}output.png`, attempt.png);
  return {
    png: attempt.png,
    pngBase64: attempt.png.toString('base64'),
    width: attempt.record.width,
    height: attempt.record.height,
    pngBytes: attempt.record.pngBytes,
    diagramType: entry.name,
    rationale,
    mermaidSource: source,
    endpointUsed,
    repaired,
    resized: !!resize,
    resize,
  };
}
