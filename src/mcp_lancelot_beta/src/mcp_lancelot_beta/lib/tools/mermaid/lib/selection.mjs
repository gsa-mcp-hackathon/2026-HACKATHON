// Step 1 of the pipeline: pick the single best Mermaid diagram type
// (BUILD_PLAN.md section 4, correction C8).
//
// The model sees PROMPT 1's per-type table (description + "best suited to
// display"), filtered to the types that actually render here and are not
// excluded by lib/diagramPolicy.mjs (D29), and must answer with JSON only. The LLM-call function is passed in by
// pipeline.mjs, so this module does not import pipeline.mjs (no circular
// import, decision D2).
import { INITIAL_INSTRUCTIONS_PROMPT, DIAGRAM_CATALOG } from './prompts.mjs';
import { findAllowedDiagramType, rejectionReason } from './diagramPolicy.mjs';

export const SELECT_MAX_TOKENS = 2048;
export const DEFAULT_DIAGRAM_TYPE = 'Flowchart';

function tableCells(row) {
  return row.split('|').slice(1, -1).map((cell) => cell.trim());
}

// One line per supported diagram type, built from PROMPT 1's table rows.
// Allowed catalog entries missing from the table are appended by name so
// the model is offered exactly the types findAllowedDiagramType accepts.
export function supportedTypeCatalogText() {
  const byFile = new Map(DIAGRAM_CATALOG.map((entry) => [entry.file, entry]));
  const lines = [];
  const seen = new Set();
  for (const row of INITIAL_INSTRUCTIONS_PROMPT.split(/\r?\n/)) {
    if (!row.startsWith('| `')) continue;
    const cells = tableCells(row);
    if (cells.length < 4) continue;
    const entry = byFile.get(cells[0].replace(/`/g, ''));
    if (!entry || !findAllowedDiagramType(entry.name) || seen.has(entry.name)) continue;
    seen.add(entry.name);
    lines.push(`- ${entry.name} [Mermaid: ${cells[1]}]: ${cells[2]} Best suited to display: ${cells[3]}`);
  }
  for (const entry of DIAGRAM_CATALOG) {
    if (!seen.has(entry.name) && findAllowedDiagramType(entry.name)) {
      seen.add(entry.name);
      lines.push(`- ${entry.name}`);
    }
  }
  return { text: lines.join('\n'), count: seen.size };
}

export function buildSelectionMessages(documentText, hint) {
  const { text: catalog } = supportedTypeCatalogText();
  const system = [
    'You are an expert at turning documents into clear diagrams.',
    'Choose the SINGLE best Mermaid diagram type for the document provided by the user, from the supported types listed below.',
    'A good choice is non-trivial (at least 3 discrete steps, components, or items) and matches the structure of the content (process, hierarchy, timeline, relationships, quantities, and so on).',
    'Supported diagram types:',
    catalog,
    'Respond with ONLY a JSON object, no code fences and no other text, in exactly this form:',
    '{"diagramType": "<exact name from the list above>", "rationale": "<one sentence explaining why>"}',
  ].join('\n\n');
  const user = [hint ? `Focus requested by the user: ${hint}` : null, 'Document:', documentText].filter(Boolean).join('\n\n');
  return [
    { role: 'system', content: system },
    { role: 'user', content: user },
  ];
}

// Parses the model's reply. Never throws: an unusable reply defaults to
// Flowchart and says why.
export function parseSelectionReply(reply) {
  const text = String(reply ?? '').trim();
  const unfenced = text.replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/, '').trim();
  const match = unfenced.match(/\{[\s\S]*\}/);
  let parsed = null;
  let parseError = null;
  if (match) {
    try {
      parsed = JSON.parse(match[0]);
    } catch (err) {
      parseError = err.message;
    }
  } else {
    parseError = 'no JSON object found in reply';
  }
  const requestedName = parsed && typeof parsed.diagramType === 'string' ? parsed.diagramType : null;
  const rationale = parsed && typeof parsed.rationale === 'string' ? parsed.rationale : null;
  const entry = requestedName ? findAllowedDiagramType(requestedName) : null;
  if (entry) {
    return { outcome: 'parsed', entry, requestedName, rationale, reason: null };
  }
  return {
    outcome: 'defaulted_to_flowchart',
    entry: findAllowedDiagramType(DEFAULT_DIAGRAM_TYPE),
    requestedName,
    rationale,
    reason:
      parseError ||
      (requestedName
        ? `"${requestedName}" is ${rejectionReason(requestedName) === 'excluded' ? 'an excluded' : 'not a supported'} diagram type`
        : 'reply had no diagramType'),
  };
}

// callLlm({ step, messages, maxTokens, stageCapMs }) -> { text, endpoint, ms, usage }
export async function selectDiagramType({ documentText, hint, callLlm, stageCapMs }) {
  const messages = buildSelectionMessages(documentText, hint);
  const reply = await callLlm({ step: 'select', messages, maxTokens: SELECT_MAX_TOKENS, stageCapMs });
  const parsed = parseSelectionReply(reply.text);
  return { ...parsed, endpoint: reply.endpoint, ms: reply.ms };
}
