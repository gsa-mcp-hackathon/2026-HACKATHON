// The generate_diagram MCP tool (ARCHITECTURE.md section 6.1, decision D21).
//
// Transport-free: server.mjs owns the MCP SDK, zod schema, and HTTP; this
// module turns validated arguments + caller identity into an MCP
// CallToolResult and fills the per-call trace. It never throws.
import { prepareInput } from './inputs.mjs';
import { BUDGET_MS, runPipeline } from './pipeline.mjs';
import { sha256 } from '../../../core/tracer.mjs';

export const TOOL_NAME = 'generate_diagram';
export const TOOL_TITLE = 'Generate a Mermaid diagram (PNG)';
export const TOOL_DESCRIPTION = [
  'Turns ONE document into a diagram. Picks the best Mermaid diagram type for the content (or uses diagramType),',
  'writes the Mermaid source with an LLM using DHS color rules, renders it on the server, and returns a PNG image',
  'plus a JSON block (status, runId, diagramType, rationale, mermaidSource, endpointUsed, repaired, resized, truncated, timingsMs).',
  'If the first diagram is too large to render, it is simplified once to fit and resized is true.',
  'Provide exactly one input: data (text, JSON, CSV, YAML, Markdown), fileBase64 together with fileName',
  '(PDF, DOCX, XLSX, HTML, CSV, JSON, YAML, TXT, MD; max 14 MB), or workspacePath (a file inside your own',
  '/Users/<you>/ workspace folder). On failure returns isError with errorCode INVALID_INPUT, UNSUPPORTED_FILE,',
  'ACCESS_DENIED, EXTRACTION_FAILED, LLM_TIMEOUT, LLM_ERROR, or RENDER_FAILED. Takes up to about 70 seconds.',
].join(' ');

// Field descriptions; server.mjs builds the zod schema from these.
export const INPUT_FIELDS = {
  data: 'Document content as text (plain text, Markdown, JSON, CSV, YAML). Use this OR fileBase64 OR workspacePath.',
  fileBase64: 'Document file bytes, base64-encoded (a data: URL prefix is accepted). Requires fileName. Max 14 MB decoded.',
  fileName: 'File name for fileBase64, e.g. plan.pdf. Its extension selects the text extractor.',
  workspacePath: 'Path of a file in your own Databricks workspace folder, e.g. /Workspace/Users/<you>/plan.pdf. Read with your own permissions.',
  diagramType: 'Optional diagram type, e.g. "Flowchart", "Sequence diagram", "ERD", "Gantt". Skips automatic type selection when supported; unsupported or excluded types are ignored and the type is chosen automatically.',
  hint: 'Optional one-line focus, e.g. "show the approval steps only".',
};

export function callerFromHeaders(headers = {}) {
  const pick = (name) => {
    const v = headers[name];
    return typeof v === 'string' && v.trim() ? v.trim() : null;
  };
  return { email: pick('x-forwarded-email'), forwardedToken: pick('x-forwarded-access-token'), user: pick('x-forwarded-user') };
}

function errorResult(body) {
  return { isError: true, content: [{ type: 'text', text: JSON.stringify(body) }] };
}

// args: tool arguments; caller: callerFromHeaders(); tracer: a Tracer('call').
export async function runGenerateDiagram(args = {}, caller = {}, tracer) {
  const t0 = Date.now();
  const deadlineAt = t0 + BUDGET_MS;
  const timingsMs = {};
  const call = {
    budgetMs: BUDGET_MS,
    caller: {
      fieldsPresent: Object.keys(args).filter((k) => args[k] !== undefined && args[k] !== null && args[k] !== ''),
      email: caller.email ? (tracer.debug ? caller.email : `sha256:${sha256(caller.email).slice(0, 16)}`) : null,
      forwardedToken: !!caller.forwardedToken,
    },
    request: {
      diagramType: args.diagramType ?? null,
      hintChars: typeof args.hint === 'string' ? args.hint.length : null,
      hint: tracer.text(args.hint ?? null),
    },
    input: null,
    extract: null,
    pipeline: {},
    response: null,
    timingsMs,
  };
  tracer.trace.call = call;

  try {
    const prepared = await prepareInput(args, caller);
    timingsMs.input = Date.now() - t0;
    call.input = prepared.input;
    call.extract = { ...prepared.extract, preview: tracer.text(prepared.extract.preview) };
    tracer.artifact('input.bin', prepared.buffer);
    tracer.artifact('extracted.txt', prepared.text);

    const tPipe = Date.now();
    const result = await runPipeline({
      text: prepared.text,
      hint: typeof args.hint === 'string' && args.hint.trim() ? args.hint.trim() : null,
      diagramType: typeof args.diagramType === 'string' && args.diagramType.trim() ? args.diagramType.trim() : null,
      deadlineAt,
      tracer,
      record: call.pipeline,
      label: 'call',
    });
    const p = call.pipeline;
    Object.assign(timingsMs, {
      select: p.select?.skipped ? 0 : p.select?.ms ?? null,
      generate: p.generate?.ms ?? null,
      repair: p.repair?.ms ?? null,
      resize: p.resize?.ms ?? null,
      render: p.render.reduce((sum, r) => sum + (r.ms || 0), 0),
      pipeline: Date.now() - tPipe,
      total: Date.now() - t0,
    });

    const meta = {
      status: 'OK',
      runId: tracer.runId,
      diagramType: result.diagramType,
      rationale: result.rationale,
      mermaidSource: result.mermaidSource, // always returned (D19)
      endpointUsed: result.endpointUsed,
      repaired: result.repaired,
      resized: result.resized,
      resize: result.resize, // null, or original/final pixel sizes + a one-line note (D28)
      truncated: !!prepared.extract.truncated,
      width: result.width,
      height: result.height,
      timingsMs,
    };
    const text = JSON.stringify(meta);
    call.response = { status: 'OK', contentTypes: ['image', 'text'], pngBytes: result.pngBytes, width: result.width, height: result.height, textChars: text.length };
    tracer.setOutcome('OK');
    return { content: [{ type: 'image', data: result.pngBase64, mimeType: 'image/png' }, { type: 'text', text }] };
  } catch (err) {
    const errorCode = err && err.code ? err.code : 'INTERNAL_ERROR';
    const stage = err && err.stage ? err.stage : 'unknown';
    if (!call.input && err && err.input) call.input = err.input;
    if (!call.extract && err && err.extract) call.extract = { ...err.extract, preview: tracer.text(err.extract.preview) };
    if (err && err.failures) call.llmFailures = err.failures;
    timingsMs.total = Date.now() - t0;
    if (errorCode === 'INTERNAL_ERROR') console.error(`[tool] ${tracer.runId} unexpected error`, err);
    const body = { status: 'ERROR', runId: tracer.runId, errorCode, message: String(err && err.message ? err.message : err), stage };
    if (err && err.resize) body.resize = err.resize; // too-large diagram that could not be resized (D28)
    call.response = { status: 'ERROR', errorCode, stage, contentTypes: ['text'] };
    call.error = tracer.errorMessage(err);
    tracer.setOutcome(errorCode, errorCode, stage);
    return errorResult(body);
  }
}
