// Loads the static prompt text under PROMPTS/ once at process startup, and
// builds the single combined "syntax + color" instructions message the chat
// flow re-sends on every generation/edit turn for whichever diagram type is
// currently active in a session (server.mjs owns that phase/activeDiagramType
// state - this module only knows how to build prompt text from a diagram
// type name).
//
// Root-cause note on DIAGRAM_CATALOG below: PROMPT 2's own stated filename
// rule ("the name of the Markdown file... all lowercase, without spaces,
// and with '.md' at the end") does NOT actually match every real filename
// under PROMPTS/ - e.g. the ER diagram's Mermaid keyword is `erDiagram` but
// its file is `entityRelationshipDiagram.md`; Use case's keyword is
// `usecase-beta` but its file is `usecase.md`; C4's keywords are
// `C4Context`/`C4Container`/etc. but its file is `c4.md`. A mechanical
// lowercase-transform would silently fail to find the right file for these.
// Hardcoding the mapping straight from PROMPT 1's own Doc/keyword table
// (rather than trusting the naive rule) is the only reliable way to resolve
// a diagram type name to its actual syntax-guide file. If PROMPT 1's table
// is ever edited to add/rename a diagram type, this table needs a matching
// manual update.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROMPTS_DIR = path.join(__dirname, '..', 'PROMPTS');

function readPromptFile(filename) {
  return fs.readFileSync(path.join(PROMPTS_DIR, filename), 'utf8');
}

// PROMPT 1's raw text becomes the base of server.mjs's SYSTEM_PROMPT
// (replacing the old hardcoded string entirely, per product decision) - the
// document-analysis/diagram-suggestion instructions live here, editable
// without touching any code, redeploy still required per Databricks Apps'
// immutable-snapshot deployment model.
export const INITIAL_INSTRUCTIONS_PROMPT = readPromptFile('MDG PROMPT 1 INITIAL INSTRUCTIONS.txt');

// Template with two placeholders substituted per-call in
// buildDiagramSyntaxPrompt(): "**DiagramNameHere***" (the resolved diagram
// name) and "***InsertSyntaxHelpTextHere***" (that type's .md content).
const SYNTAX_GUIDELINES_TEMPLATE = readPromptFile('MDG PROMPT 2 MERMAID SYNTAX GUIDELINES.txt');

// Appended after the syntax guidelines, unchanged - same DHS color rules
// for every diagram type.
const COLOR_PALETTE_PROMPT = readPromptFile('MDG PROMPT 3 DHS COLOR PALETTE.txt');

// Appended after the per-type syntax markdown but BEFORE the color-palette
// prompt, and ONLY for diagram types in ORIENTATION_AWARE_DIAGRAM_NAMES
// below - unlike PROMPT 3, this is NOT universal. Root cause this exists:
// a long, mostly-linear flowchart defaulted to LR with no guidance at all,
// which squeezed every node's label to fit the width until the diagram was
// unreadable; switching to TD in the Manual Editor fixed it immediately -
// the model needs a concrete, self-checkable heuristic for this choice
// instead of picking LR out of habit.
const ORIENTATION_GUIDANCE_PROMPT = readPromptFile('MDG PROMPT 4 DIAGRAM ORIENTATION.txt');

// Diagram types with a genuine whole-diagram `direction <LR|TD|TB|BT|RL>`
// statement where defaulting to TD is the actual fix - confirmed by
// actually reading each PROMPTS/*.md's syntax section, not just
// `grep -l "direction"` (which over-counts: Block diagram/Sequence
// diagram/Wardley/C4 only mention arrow direction, not diagram-wide
// orientation, so they're deliberately excluded). Swimlanes and Timeline
// also have a genuine direction statement but are ALSO deliberately
// excluded here - swimlanes already defaults sensibly to TB per its own
// spec, and timeline's natural idiom is conventionally LR/chronological,
// the opposite bias from the fix below. Revisit both separately if they
// show the same squeeze problem in practice.
const ORIENTATION_AWARE_DIAGRAM_NAMES = new Set([
  'Flowchart',
  'Class diagram',
  'State diagram',
  'ERD',
  'Requirement diagram',
]);

// name: human-readable label substituted into PROMPT 2's placeholder and
//   used in chat replies/UI - matches PROMPT 1's own "Diagram type" wording.
// file: exact PROMPTS/*.md filename (see root-cause note above - NOT
//   derivable by a mechanical rule).
// keywords: lowercase strings matched against a resolved model-provided
//   name (see findDiagramCatalogEntry) - includes the Mermaid keyword(s)
//   from PROMPT 1's table plus common casual phrasings.
export const DIAGRAM_CATALOG = [
  { name: 'Agentflow', file: 'agentflow.md', keywords: ['agentflow', 'agentflow-beta'] },
  { name: 'Architecture', file: 'architecture.md', keywords: ['architecture', 'architecture-beta'] },
  { name: 'Block diagram', file: 'block.md', keywords: ['block', 'block diagram'] },
  { name: 'C4', file: 'c4.md', keywords: ['c4', 'c4context', 'c4container', 'c4component', 'c4dynamic', 'c4deployment'] },
  { name: 'Class diagram', file: 'classDiagram.md', keywords: ['classdiagram', 'class diagram', 'class'] },
  { name: 'Cynefin', file: 'cynefin.md', keywords: ['cynefin'] },
  { name: 'ERD', file: 'entityRelationshipDiagram.md', keywords: ['erdiagram', 'erd', 'entity relationship diagram', 'entity relationship'] },
  { name: 'Event Modeling', file: 'eventmodeling.md', keywords: ['eventmodeling', 'event modeling'] },
  { name: 'Flowchart', file: 'flowchart.md', keywords: ['flowchart', 'flow chart'] },
  { name: 'Gantt', file: 'gantt.md', keywords: ['gantt'] },
  { name: 'GitGraph', file: 'gitgraph.md', keywords: ['gitgraph', 'git graph'] },
  { name: 'Ishikawa/Fishbone', file: 'ishikawa.md', keywords: ['ishikawa', 'fishbone'] },
  { name: 'Kanban', file: 'kanban.md', keywords: ['kanban'] },
  { name: 'Mindmap', file: 'mindmap.md', keywords: ['mindmap', 'mind map'] },
  { name: 'Packet diagram', file: 'packet.md', keywords: ['packet', 'packet diagram'] },
  { name: 'Pie/Donut', file: 'pie.md', keywords: ['pie', 'donut', 'pie chart'] },
  { name: 'Quadrant chart', file: 'quadrantChart.md', keywords: ['quadrantchart', 'quadrant chart', 'quadrant'] },
  { name: 'Radar', file: 'radar.md', keywords: ['radar'] },
  { name: 'Railroad', file: 'railroad.md', keywords: ['railroad', 'railroad-ebnf-beta', 'ebnf'] },
  { name: 'Requirement diagram', file: 'requirementDiagram.md', keywords: ['requirementdiagram', 'requirement diagram', 'requirement'] },
  { name: 'Sankey', file: 'sankey.md', keywords: ['sankey', 'sankey-beta'] },
  { name: 'Sequence diagram', file: 'sequenceDiagram.md', keywords: ['sequencediagram', 'sequence diagram', 'sequence'] },
  { name: 'State diagram', file: 'stateDiagram.md', keywords: ['statediagram', 'state diagram', 'state'] },
  { name: 'Swimlanes', file: 'swimlanes.md', keywords: ['swimlane', 'swimlanes', 'swimlane-beta'] },
  { name: 'Timeline', file: 'timeline.md', keywords: ['timeline'] },
  { name: 'TreeView', file: 'treeView.md', keywords: ['treeview', 'tree view', 'tree'] },
  { name: 'Treemap', file: 'treemap.md', keywords: ['treemap', 'tree map'] },
  { name: 'Use case', file: 'usecase.md', keywords: ['usecase', 'use case', 'usecase-beta'] },
  { name: 'User journey', file: 'userJourney.md', keywords: ['userjourney', 'user journey', 'journey'] },
  { name: 'Venn', file: 'venn.md', keywords: ['venn'] },
  { name: 'Wardley map', file: 'wardley.md', keywords: ['wardley', 'wardley map'] },
  { name: 'XY chart', file: 'xyChart.md', keywords: ['xychart', 'xy chart', 'xychart-beta'] },
];

// Registry of diagram types that exist in DIAGRAM_CATALOG (and have a real
// PROMPTS/*.md syntax guide) but are KNOWN not to work in this app's
// rendering environment - a running list rather than one-off exclusions,
// so each future discovery (most of these .md files are untested against
// the actual jsdom+resvg pipeline in lib/render.mjs) is a one-entry
// addition here instead of a new bespoke code path. Each entry documents
// the root cause and how it was confirmed, so a future attempt to
// re-enable one doesn't have to re-diagnose from scratch.
//
// Filtered out at the two choke points below (findDiagramCatalogEntry and
// diagramCatalogSummary) - so neither suggest_diagrams nor
// select_diagram_type can ever resolve/select one, regardless of what the
// model or user types, AND the model never sees it listed as a valid
// option to suggest in the first place. The underlying DIAGRAM_CATALOG
// entry (name/file/keywords) is left in place - re-enabling a type later
// is just deleting its entry here, no catalog surgery required.
export const UNSUPPORTED_DIAGRAM_TYPES = [
  {
    name: 'Architecture',
    reason:
      "Cannot render in this container: Mermaid's architecture-beta layout engine (cytoscape.js-fcose) requires an HTML5 canvas 2D context, which jsdom (this app's DOM shim - see lib/render.mjs) does not implement. Confirmed via a live render_diagram trace: two independent attempts both failed with the identical error 'Could not create canvas of type 2d'.",
    discoveredAt: '2026-09-22',
  },
  {
    name: 'Mindmap',
    reason:
      "Cannot render in this container: Mermaid's mindmap layout engine hits the SAME missing capability as Architecture above - a call to canvas.getContext('2d') (almost certainly for text-metrics measurement, a separate code path from the getBBox/getComputedTextLength stubs in lib/render.mjs that flowchart/C4/etc. actually use), which jsdom does not implement natively. Confirmed via a live render_diagram trace on a real user document: two independent attempts (default mindmap config, then retried with an explicit `layout: tidy-tree` config override) both failed with the identical error 'Could not create canvas of type 2d'.",
    discoveredAt: '2026-09-23',
  },
  {
    name: 'Agentflow',
    reason:
      "Cannot render with the currently installed mermaid version (11.17.2, see package.json) - a DIFFERENT root cause from Architecture/Mindmap above, NOT the canvas-2d gap. mermaid.render() rejects the `agentflow-beta` keyword outright with 'No diagram type detected matching given configuration for text: agentflow-beta ...', meaning this version of mermaid does not register agentflow as a diagram type at all yet. The PROMPTS/agentflow.md syntax guide's own version header is a literal unresolved template placeholder ('v<MERMAID_RELEASE_VERSION>+'), suggesting that doc was sourced from mermaid's docs repo ahead of the actual npm release this app depends on. Confirmed via the systematic /api/selftest-diagram-gallery sweep across all 32 DIAGRAM_CATALOG entries. Revisit if/when the mermaid dependency is upgraded past whatever version actually ships agentflow-beta - this may simply start working with no code change.",
    discoveredAt: '2026-09-23',
  },
  {
    name: 'Use case',
    reason:
      "Cannot render with the currently installed mermaid version (11.17.2) - same version-gap root cause as Agentflow above, NOT the canvas-2d gap. mermaid.render() rejects the `usecase-beta` keyword outright with 'No diagram type detected matching given configuration for text: usecase-beta ...'. Confirmed via the systematic /api/selftest-diagram-gallery sweep across all 32 DIAGRAM_CATALOG entries. Revisit if/when the mermaid dependency is upgraded past whatever version actually ships usecase-beta - this may simply start working with no code change.",
    discoveredAt: '2026-09-23',
  },
];

const UNSUPPORTED_DIAGRAM_NAMES = new Set(UNSUPPORTED_DIAGRAM_TYPES.map((entry) => entry.name));

function isSupportedCatalogEntry(entry) {
  return !!entry && !UNSUPPORTED_DIAGRAM_NAMES.has(entry.name);
}

const markdownCache = new Map();
function readDiagramMarkdown(file) {
  if (!markdownCache.has(file)) {
    markdownCache.set(file, readPromptFile(file));
  }
  return markdownCache.get(file);
}

// Resolves a free-form diagram type name/keyword (from the model's own
// select_diagram_type tool call, or from server.mjs's deterministic
// generate-trigger parsing) to its catalog entry. Exact-name match first
// (case-insensitive), then keyword match - NOT a substring/fuzzy search, so
// this stays predictable; genuinely ambiguous free text from the human user
// is deliberately left to the model (via the select_diagram_type tool)
// rather than guessed here.
export function findDiagramCatalogEntry(name) {
  if (!name) return null;
  const needle = String(name).trim().toLowerCase();
  if (!needle) return null;
  const found =
    DIAGRAM_CATALOG.find((entry) => entry.name.toLowerCase() === needle) ||
    DIAGRAM_CATALOG.find((entry) => entry.keywords.includes(needle)) ||
    null;
  // A type listed in UNSUPPORTED_DIAGRAM_TYPES above is treated as
  // unresolvable here - this is the single choke point every caller
  // (suggest_diagrams, select_diagram_type, and server.mjs's deterministic
  // GENERATE_TRIGGER_PREFIX lookup) goes through, so none of them can ever
  // select one.
  return isSupportedCatalogEntry(found) ? found : null;
}

// Builds the ONE combined message re-sent on every generation/edit turn for
// `diagramTypeName` (product decision: reinforcement every turn, not just
// on first selection, to counter instruction drift over a long
// conversation). PROMPT 2's placeholders are substituted in place and
// PROMPT 3 is appended after - all 3 sources combined into a single string,
// exactly as specified (never sent as 3 separate calls).
// Caps how much of a single attempt's error text gets echoed back into the
// model's own prompt - the full text still lives in session.diagramAttempts
// (server.mjs) for diagnostic purposes; only a truncated summary is
// re-injected here to keep this already-large combined prompt from
// growing unboundedly across several retries on the same diagram type.
const MAX_ATTEMPT_ERROR_CHARS = 200;

// Compact, model-facing summary of this diagram type's own render attempts
// so far this session (session.diagramAttempts, tracked in server.mjs) -
// deliberately per-attempt ONE line (outcome + truncated error), never the
// full previous Mermaid source, for the same prompt-size reason. Returns
// '' when there's no history yet, so a first-ever attempt's prompt is
// unchanged from before this feature existed.
function buildAttemptHistorySummary(diagramName, attemptHistory) {
  if (!attemptHistory || attemptHistory.length === 0) return '';
  const lines = attemptHistory.map((attempt, index) => {
    const when = new Date(attempt.timestamp).toISOString();
    const errorText = attempt.errorSummary
      ? attempt.errorSummary.length > MAX_ATTEMPT_ERROR_CHARS
        ? `${attempt.errorSummary.slice(0, MAX_ATTEMPT_ERROR_CHARS)}...`
        : attempt.errorSummary
      : null;
    const outcomeText =
      attempt.outcome === 'success'
        ? 'SUCCEEDED'
        : attempt.outcome === 'partial'
          ? `RENDERED WITH A CAVEAT (${errorText})`
          : `FAILED (${errorText})`;
    return `${index + 1}. [${when}] ${outcomeText}`;
  });
  return `\n\n---\nYour previous render_diagram attempt(s) for the ${diagramName} diagram this session, most recent last - use this to avoid repeating a mistake you already made, and to know whether a working version already exists:\n${lines.join('\n')}`;
}

// Model-facing reminder of the ORIGINAL numbered suggestion list (recorded
// via the suggest_diagrams tool - session.suggestedDiagrams in server.mjs)
// plus which one is currently active - injected on every turn a diagram is
// active, alongside buildDiagramSyntaxPrompt's output.
//
// Root cause this exists for (2026-09-22): once a diagram type is active,
// the syntax prompt's own "you don't need to reselect" framing dominates,
// and a short reply like a bare "2" gets swallowed as a request to
// re-edit the ACTIVE diagram instead of being recognized as "give me
// suggestion #2" - because the original numbered list only ever existed as
// free text several turns back, easily outweighed by the freshly-repeated
// active-diagram context. Restating it, in structured form, on every turn
// keeps it from getting buried behind the active diagram's own
// reinforcement. `suggestedDiagrams`/`activeDiagramTypeName` are passed in
// rather than looked up here, same reason as buildDiagramSyntaxPrompt: this
// module stays session-agnostic/pure.
export function buildMenuReminder(suggestedDiagrams, activeDiagramTypeName) {
  if (!suggestedDiagrams || suggestedDiagrams.length === 0) return '';
  const lines = suggestedDiagrams.map((s) => {
    const marker = s.diagramType === activeDiagramTypeName ? ' (ACTIVE - currently being generated/edited)' : '';
    return `${s.number}. ${s.name} - ${s.diagramType}${marker}`;
  });
  return `---\nReminder - the diagrams you originally suggested were:\n${lines.join('\n')}\n\nIf the user's next message clearly refers to a DIFFERENT one of these (by number, name, or description) rather than asking to edit/regenerate the ACTIVE one, call select_diagram_type with that diagram type FIRST - do not call render_diagram for the active type in that case. Only treat the message as an edit/regeneration of the active diagram when it does NOT match a different suggestion.`;
}

// `attemptHistory` (optional) is this diagram type's slice of
// session.diagramAttempts (server.mjs) - passed in rather than looked up
// here since this module is deliberately kept session-agnostic/pure.
export function buildDiagramSyntaxPrompt(diagramTypeName, attemptHistory = []) {
  const entry = findDiagramCatalogEntry(diagramTypeName);
  if (!entry) {
    throw new Error(`buildDiagramSyntaxPrompt: unknown diagram type "${diagramTypeName}"`);
  }
  const syntaxMarkdown = readDiagramMarkdown(entry.file);
  const withDiagramName = SYNTAX_GUIDELINES_TEMPLATE.replace('**DiagramNameHere***', entry.name);
  const withSyntaxHelp = withDiagramName.replace('***InsertSyntaxHelpTextHere***', syntaxMarkdown);
  const orientationGuidance = ORIENTATION_AWARE_DIAGRAM_NAMES.has(entry.name) ? `\n\n${ORIENTATION_GUIDANCE_PROMPT}` : '';
  const attemptSummary = buildAttemptHistorySummary(entry.name, attemptHistory);
  return `${withSyntaxHelp}${orientationGuidance}\n\n${COLOR_PALETTE_PROMPT}${attemptSummary}`;
}

export function diagramCatalogSummary() {
  return DIAGRAM_CATALOG.filter(isSupportedCatalogEntry)
    .map((entry) => entry.name)
    .join(', ');
}
