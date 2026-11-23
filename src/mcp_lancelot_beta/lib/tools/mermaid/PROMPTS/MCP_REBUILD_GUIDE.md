# Mermaid Diagram Generator ("Lancelot MCP") — Databricks MCP Server MVP Rebuild Guide

This is the complete, from-scratch rebuild specification for converting the Databricks App at `/Workspace/Users/tom.jacobson@hq.dhs.gov/mermaid-diagram-generator` ("Lancelot Beta") into a **headless Model Context Protocol (MCP) Server** deployed as a **Databricks App** (`mcp-mermaid-generator`).

It is engineered specifically so a developer or AI coding agent can implement the MVP step-by-step with zero ambiguity, preserving every hard-won rendering and platform fix from the original application while stripping out the entire web UI and multi-turn chat state.

---

## 0. Role & Directive for the Builder Agent

You are building a **headless Model Context Protocol (MCP) Server** deployed as a **Databricks App** (`mcp-mermaid-generator`).

* **DO NOT** build a React frontend, HTML UI, Vite build pipeline, TypeScript compiler step, Manual Editor, or multi-turn chat session store (`src/*`, `dist/`, `vite.config.ts`, and `lib/sessions.mjs` are completely eliminated).
* **DO** build a pure Node.js (ESM, `"type": "module"`) Express 4 server that exposes **exactly one MCP tool** (`generate_diagram`) over **Stateless Streamable HTTP** at `POST /mcp`.
* **WHAT IT DOES (The Single-Tool MVP):**
  1. A client sends either raw text/JSON (`data`) or a PDF (`pdfBase64` or `workspacePath`) to the `generate_diagram` MCP tool.
  2. With **zero back-and-forth**, the server extracts the text (`lib/extractText.mjs`).
  3. The server calls a Databricks Model Serving LLM (`lib/llm.mjs`) in a flat 2-step sequence:
     * **Step A:** Pick the single best Mermaid diagram type from `DIAGRAM_CATALOG`.
     * **Step B:** Load that diagram type's syntax guide + DHS color palette + orientation rules (`lib/prompts.mjs`) and generate the Mermaid source code.
  4. The server renders the Mermaid code to a **PNG image** server-side (`lib/render.mjs` + child-process `lib/rasterizeWorker.mjs`).
  5. If Mermaid syntax validation fails on Attempt 1, the server feeds the exact syntax error back to the LLM **once** to self-correct and re-renders.
  6. The server returns the finished **PNG image** (`ImageContent`) plus a JSON metadata block (`TextContent`), or a structured error code (`INVALID_INPUT`, `EXTRACTION_FAILED`, `LLM_TIMEOUT`, `RENDER_FAILED`).

* **SOURCE OF TRUTH FOR REUSABLE FILES:** `/Workspace/Users/tom.jacobson@hq.dhs.gov/mermaid-diagram-generator`.

---

## 1. Architecture & File Structure (7 Code Files Total)

The entire MVP consists of **7 `.mjs` files**, `package.json`, `app.yaml`, and the `PROMPTS/` directory.

```text
mcp-mermaid-generator/
├── app.yaml                  # Databricks App runtime config & LLM endpoint bindings
├── package.json              # Pure Node.js ESM dependencies (no React/Vite/TypeScript)
├── server.mjs                # Express 4 + MCP StreamableHTTPServerTransport at POST /mcp
├── PROMPTS/                  # Copy verbatim from original app (DHS colors, orientation, *.md syntax guides)
└── lib/
    ├── databricksAuth.mjs    # Exchanges DATABRICKS_CLIENT_ID/SECRET for Service Principal OAuth token
    ├── extractText.mjs       # Extracts text from PDF buffer, Workspace path, or raw JSON/text string
    ├── prompts.mjs           # DIAGRAM_CATALOG, UNSUPPORTED_DIAGRAM_TYPES, and prompt builder
    ├── llm.mjs               # Two-step LLM pipeline: (1) pick diagram type, (2) write Mermaid + 1 retry
    ├── render.mjs            # jsdom + mermaid + opentype.js SVG renderer (copy verbatim from original app)
    └── rasterizeWorker.mjs   # Child-process @resvg/resvg-js SVG-to-PNG rasterizer (copy verbatim)
```

| File / Folder | Action | Notes |
|---|---|---|
| `PROMPTS/*` | **COPY VERBATIM** | Copy all `.txt` and `.md` files from `/Workspace/Users/tom.jacobson@hq.dhs.gov/mermaid-diagram-generator/PROMPTS/`. |
| `lib/databricksAuth.mjs` | **COPY VERBATIM** | Exchanges auto-injected `DATABRICKS_CLIENT_ID`/`SECRET` for an OAuth token; normalizes `DATABRICKS_HOST`. |
| `lib/prompts.mjs` | **COPY VERBATIM** | Contains `DIAGRAM_CATALOG`, `UNSUPPORTED_DIAGRAM_TYPES`, `findDiagramCatalogEntry`, `diagramCatalogSummary`, and `buildDiagramSyntaxPrompt`. |
| `lib/render.mjs` | **COPY VERBATIM** | Contains the `jsdom` global setup, `opentype.js` text measurement, `htmlLabels: false`, and single-concurrency queue. |
| `lib/rasterizeWorker.mjs` | **COPY VERBATIM** | Child-process `@resvg/resvg-js` PNG rasterizer with bundled `dejavu-fonts-ttf` and pixel size guards. |
| `lib/extractText.mjs` | **WRITE NEW (SIMPLIFIED)** | Handles `data` (JSON/text), `pdfBase64`, and `workspacePath`, plus startup `warmLoadPdfParse()`. |
| `lib/llm.mjs` | **WRITE NEW (SIMPLIFIED)** | Replaces complex multi-turn chat tool loop with a flat 2-step pipeline (`selectBestDiagramType` -> `generateAndRenderMermaid`). |
| `server.mjs` | **WRITE NEW** | Mounts stateless MCP server at `POST /mcp`, health check at `GET /healthz`, and render self-test at `GET /api/selftest-render`. |

---

## 2. Mandatory Databricks Apps & Custom MCP Server Guardrails

1. **App Name Must Start With `mcp-`:**
   When creating/deploying the Databricks App (`databricks apps create`), the app name **must** start with `mcp-` (e.g., `mcp-mermaid-generator`). Databricks AI Playground and Genie Code scan for the `mcp-` prefix to auto-discover Custom MCP Servers.
2. **Host & Port Binding:**
   Bind Express to host `'0.0.0.0'` and port `Number(process.env.DATABRICKS_APP_PORT || 8000)`.
3. **Stateless Streamable HTTP Transport at `/mcp`:**
   * Mount the MCP endpoint at `/mcp`.
   * Use `StreamableHTTPServerTransport({ sessionIdGenerator: undefined })` from `@modelcontextprotocol/sdk/server/streamableHttp.js`.
   * Do **not** use legacy SSE (`SSEServerTransport`) or `stdio`.
   * Instantiate a fresh `McpServer` + `StreamableHTTPServerTransport` per `POST /mcp` request and clean up on `res.on('close')`. This guarantees zero cross-request state corruption and avoids the Databricks Apps proxy connection reset.
4. **Hard 75-Second Outer Deadline (`HARD_OUTER_DEADLINE_MS = 75_000`):**
   The Databricks Apps front-end proxy enforces an empirical ~60–90s connection timeout and resets long connections without a clean HTTP status. The entire `generate_diagram` call (extraction + LLM Step 1 + LLM Step 2 + render + optional retry) must complete or abort cleanly with `LLM_TIMEOUT` before `75_000` ms.
5. **Dual-Mode Auth for `workspacePath` (`x-forwarded-access-token` + Service Principal Fallback):**
   When a user calls the MCP server from Databricks AI Playground or Genie Code, Databricks forwards the user's OAuth token in `req.headers['x-forwarded-access-token']`. If `workspacePath` is used, prefer `req.headers['x-forwarded-access-token']` (On-Behalf-Of user auth) and fall back to `await getAccessToken()` (Service Principal OAuth) if that header is absent.

---

## 3. Configuration Files (`package.json` and `app.yaml`)

### 3.1 `package.json`
Use these exact dependency versions. Do **not** upgrade or swap `mermaid`, `jsdom`, `@resvg/resvg-js`, or `pdf-parse`.

```json
{
  "name": "mcp-mermaid-generator",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "start": "node server.mjs"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.10.2",
    "@resvg/resvg-js": "^2.6.2",
    "dejavu-fonts-ttf": "^2.37.3",
    "express": "^4.19.2",
    "jsdom": "27.3.0",
    "mermaid": "11.17.2",
    "opentype.js": "^1.3.4",
    "pdf-parse": "1.1.1",
    "zod": "^3.23.8"
  }
}
```

### 3.2 `app.yaml`
There is no frontend build step; the container installs dependencies and starts `server.mjs` directly.

```yaml
command:
  - sh
  - -c
  - "npm install && node server.mjs"

env:
  - name: LLM_ENDPOINT_PRIMARY
    valueFrom: llm-primary
  - name: LLM_ENDPOINT_FALLBACK_1
    valueFrom: llm-fallback-1
  - name: LLM_ENDPOINT_FALLBACK_2
    valueFrom: llm-fallback-2

resources:
  - name: llm-primary
    serving_endpoint:
      name: databricks-claude-opus-5
      permission: CAN_QUERY
  - name: llm-fallback-1
    serving_endpoint:
      name: databricks-grok-4-6
      permission: CAN_QUERY
  - name: llm-fallback-2
    serving_endpoint:
      name: databricks-gemini-3-8-flash
      permission: CAN_QUERY
```
*(Note: If the target workspace uses different Foundation Model API endpoint names, update `serving_endpoint.name` accordingly. Note the operational quirk from the original app: in Databricks Apps, resource-name -> serving-endpoint bindings can be sticky across source-only redeploys; if reordering endpoints later, repoint the `env` `valueFrom` references).*

---

## 4. Detailed Module Specifications (`lib/*` and `server.mjs`)

### 4.1 `lib/databricksAuth.mjs` (Copy from Original App)
* Reads `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, and `DATABRICKS_CLIENT_SECRET` from `process.env`.
* **Crucial:** Normalizes `DATABRICKS_HOST` by prepending `https://` if missing (`!/^https?:\/\//i.test(host)`).
* Exports:
  * `getHostUrl()` — returns the normalized base URL (no trailing slash).
  * `getAccessToken()` — exchanges `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` via `POST {host}/oidc/v1/token` (`Content-Type: application/x-www-form-urlencoded`, body `grant_type=client_credentials&scope=all-apis`), caches the token until 60s before expiry, and returns the bearer string.

---

### 4.2 `lib/extractText.mjs` (Simplified Input & PDF Extractor)
Must implement `warmLoadPdfParse()` and `extractInputData()`.

```javascript
// lib/extractText.mjs
import { getHostUrl, getAccessToken } from './databricksAuth.mjs';

export const MAX_EXTRACTED_CHARS = 60_000;

let pdfParseFn = null;

export class InputError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'InputError';
    this.code = code; // 'INVALID_INPUT' | 'EXTRACTION_FAILED'
  }
}

/**
 * MUST be called at server startup BEFORE lib/render.mjs ever runs.
 * Loads pdf-parse's internal module before jsdom installs globalThis.window.
 */
export async function warmLoadPdfParse() {
  if (!pdfParseFn) {
    const mod = await import('pdf-parse/lib/pdf-parse.js');
    pdfParseFn = mod.default ?? mod;
    try {
      await pdfParseFn(Buffer.from('%PDF-1.4\n%%EOF'));
    } catch {
      // Expected dummy buffer failure; module is now warm-loaded in Node cache.
    }
  }
  return pdfParseFn;
}

function truncateText(text) {
  const cleaned = String(text ?? '').trim();
  if (!cleaned) {
    throw new InputError('EXTRACTION_FAILED', 'Extracted content was empty.');
  }
  return cleaned.length > MAX_EXTRACTED_CHARS
    ? cleaned.slice(0, MAX_EXTRACTED_CHARS)
    : cleaned;
}

export async function extractInputData({ data, pdfBase64, workspacePath, userToken }) {
  // 1. Raw data (JSON, CSV, YAML, or plain text)
  if (typeof data === 'string' && data.trim().length > 0) {
    return {
      text: truncateText(data),
      sourceType: 'data'
    };
  }

  // 2. Base64-encoded PDF
  if (typeof pdfBase64 === 'string' && pdfBase64.trim().length > 0) {
    try {
      const cleanBase64 = pdfBase64.replace(/^data:application\/pdf;base64,/i, '').trim();
      const buffer = Buffer.from(cleanBase64, 'base64');
      const parsePdf = await warmLoadPdfParse();
      const parsed = await parsePdf(buffer);
      return {
        text: truncateText(parsed?.text),
        sourceType: 'pdfBase64'
      };
    } catch (err) {
      if (err instanceof InputError) throw err;
      throw new InputError('EXTRACTION_FAILED', `Failed to parse PDF base64: ${err.message}`);
    }
  }

  // 3. Databricks Workspace or Unity Catalog Volumes path
  if (typeof workspacePath === 'string' && workspacePath.trim().length > 0) {
    try {
      const cleanPath = workspacePath.trim();
      const host = getHostUrl();
      const token = userToken || (await getAccessToken());
      let fileBuffer;

      if (cleanPath.startsWith('/Volumes/')) {
        const res = await fetch(`${host}/api/2.0/fs/files${encodeURI(cleanPath)}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (!res.ok) {
          throw new Error(`Files API returned HTTP ${res.status}`);
        }
        fileBuffer = Buffer.from(await res.arrayBuffer());
      } else {
        const url = `${host}/api/2.0/workspace/export?path=${encodeURIComponent(cleanPath)}&format=AUTO`;
        const res = await fetch(url, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (!res.ok) {
          throw new Error(`Workspace export API returned HTTP ${res.status}`);
        }
        const json = await res.json();
        if (!json?.content) {
          throw new Error('Workspace export response missing base64 content.');
        }
        fileBuffer = Buffer.from(json.content, 'base64');
      }

      if (cleanPath.toLowerCase().endsWith('.pdf')) {
        const parsePdf = await warmLoadPdfParse();
        const parsed = await parsePdf(fileBuffer);
        return {
          text: truncateText(parsed?.text),
          sourceType: 'workspacePath:pdf'
        };
      }

      return {
        text: truncateText(fileBuffer.toString('utf8')),
        sourceType: 'workspacePath:text'
      };
    } catch (err) {
      if (err instanceof InputError) throw err;
      throw new InputError('EXTRACTION_FAILED', `Failed to extract workspacePath '${workspacePath}': ${err.message}`);
    }
  }

  throw new InputError(
    'INVALID_INPUT',
    'You must provide at least one non-empty input: "data" (JSON/text), "pdfBase64", or "workspacePath".'
  );
}
```

---

### 4.3 `lib/prompts.mjs` and `PROMPTS/` (Copy Verbatim from Original App)
Copy `lib/prompts.mjs` and the entire `PROMPTS/` folder directly from `/Workspace/Users/tom.jacobson@hq.dhs.gov/mermaid-diagram-generator`.

Key exports in `lib/prompts.mjs` used by `lib/llm.mjs`:
* `INITIAL_INSTRUCTIONS_PROMPT` (or loaded content of `PROMPTS/MDG PROMPT 1 INITIAL INSTRUCTIONS.txt`)
* `DIAGRAM_CATALOG` — explicit `{ name, file, keywords }` array (~30 types).
* `UNSUPPORTED_DIAGRAM_TYPES` — blocks types incompatible with `jsdom` (e.g., `Architecture`, `Mindmap`).
* `findDiagramCatalogEntry(query)` — resolves diagram type name/keyword against supported catalog entries.
* `diagramCatalogSummary()` — human/LLM-readable list of supported diagram types.
* `buildDiagramSyntaxPrompt(diagramName)` — combines `MDG PROMPT 2 MERMAID SYNTAX GUIDELINES.txt` (with `**DiagramNameHere***` and `***InsertSyntaxHelpTextHere***` filled from `PROMPTS/<file>.md`), `MDG PROMPT 3 DHS COLOR PALETTE.txt`, and (for Flowchart, Class diagram, State diagram, ERD, and Requirement diagram) `MDG PROMPT 4 DIAGRAM ORIENTATION.txt`.

---

### 4.4 `lib/render.mjs` and `lib/rasterizeWorker.mjs` (Copy Verbatim from Original App)
Copy both `lib/render.mjs` and `lib/rasterizeWorker.mjs` untouched from `/Workspace/Users/tom.jacobson@hq.dhs.gov/mermaid-diagram-generator/lib/`.

Verify that `lib/render.mjs` exports your render function (e.g., `renderDiagram` or `renderMermaid`) which accepts `{ mermaid, format: 'png' }` and returns the PNG output (either as a `Buffer`, raw base64 string, or `data:image/png;base64,...` URL).

---

### 4.5 `lib/llm.mjs` (Stateless 2-Step LLM + Render Pipeline)
Implements the endpoint fallback chain, the 75-second outer deadline, Step 1 (pick diagram type), and Step 2 (generate Mermaid code + render via `lib/render.mjs` with 1 automatic syntax-repair retry).

```javascript
// lib/llm.mjs
import { getHostUrl, getAccessToken } from './databricksAuth.mjs';
import {
  findDiagramCatalogEntry,
  diagramCatalogSummary,
  buildDiagramSyntaxPrompt
} from './prompts.mjs';
import { renderDiagram } from './render.mjs';

export const REQUEST_TIMEOUT_MS = 30_000;
export const HARD_OUTER_DEADLINE_MS = 75_000;
export const MIN_USEFUL_RETRY_MS = 12_000;

export class PipelineError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'PipelineError';
    this.code = code; // 'LLM_TIMEOUT' | 'RENDER_FAILED'
  }
}

function candidateEndpoints() {
  const list = [
    process.env.LLM_ENDPOINT_PRIMARY,
    process.env.LLM_ENDPOINT_FALLBACK_1,
    process.env.LLM_ENDPOINT_FALLBACK_2
  ].filter((x) => typeof x === 'string' && x.trim().length > 0);
  return list.length > 0 ? list : ['databricks-claude-opus-5'];
}

function extractTextFromChoiceContent(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content
      .filter((part) => part && part.type === 'text' && typeof part.text === 'string')
      .map((part) => part.text)
      .join('\n');
  }
  return '';
}

export function extractMermaidCodeBlock(rawReply) {
  const text = String(rawReply ?? '').trim();
  const fencedMatch = text.match(/```(?:mermaid)?\s*([\s\S]*?)```/i);
  if (fencedMatch && fencedMatch[1].trim()) {
    return fencedMatch[1].trim();
  }
  return text;
}

async function callSingleEndpoint(endpoint, messages, timeoutMs, maxTokens = 2048) {
  const host = getHostUrl();
  const token = await getAccessToken();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${host}/serving-endpoints/${encodeURIComponent(endpoint)}/invocations`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        messages,
        max_tokens: maxTokens,
        temperature: 0.1
      }),
      signal: controller.signal
    });

    if (!res.ok) {
      const errBody = await res.text().catch(() => '');
      throw new Error(`Endpoint ${endpoint} HTTP ${res.status}: ${errBody.slice(0, 300)}`);
    }

    const data = await res.json();
    const rawContent = data?.choices?.[0]?.message?.content;
    const replyText = extractTextFromChoiceContent(rawContent).trim();
    if (!replyText) {
      throw new Error(`Endpoint ${endpoint} returned empty text content.`);
    }
    return replyText;
  } finally {
    clearTimeout(timer);
  }
}

async function callLLMWithFallback(messages, deadlineAt, maxTokens = 2048) {
  const endpoints = candidateEndpoints();
  const errors = [];

  for (const endpoint of endpoints) {
    const remainingMs = deadlineAt - Date.now();
    if (remainingMs < MIN_USEFUL_RETRY_MS) {
      break;
    }
    const perCallTimeout = Math.min(REQUEST_TIMEOUT_MS, remainingMs - 1000);
    try {
      return await callSingleEndpoint(endpoint, messages, perCallTimeout, maxTokens);
    } catch (err) {
      errors.push(`${endpoint}: ${err.message}`);
    }
  }

  throw new PipelineError(
    'LLM_TIMEOUT',
    `All LLM endpoints failed or timed out within budget. Details: ${errors.join(' | ')}`
  );
}

function normalizePngBase64(renderResult) {
  // Handle whichever shape renderDiagram returns (Buffer, data URL string, or { png } object)
  const raw =
    typeof renderResult === 'string'
      ? renderResult
      : renderResult?.png ?? renderResult?.pngBase64 ?? renderResult?.data;

  if (Buffer.isBuffer(raw)) {
    return raw.toString('base64');
  }
  if (typeof raw === 'string' && raw.length > 0) {
    return raw.replace(/^data:image\/png;base64,/i, '').trim();
  }
  throw new Error('Renderer did not return valid PNG data.');
}

export async function generateDiagramFromText({ extractedText, hint }) {
  const deadlineAt = Date.now() + HARD_OUTER_DEADLINE_MS;
  const catalogList = diagramCatalogSummary();

  // STEP 1: Pick the single best Mermaid diagram type
  const selectionMessages = [
    {
      role: 'system',
      content: [
        'You are an expert software and systems diagramming architect.',
        'Given the user input data, choose the SINGLE best Mermaid diagram type from the supported catalog below.',
        'Supported Diagram Catalog:',
        catalogList,
        'Respond ONLY with a valid JSON object matching this exact schema (no markdown fences, no commentary):',
        '{"diagramType": "<Exact Catalog Name>", "rationale": "<One sentence explaining why>"}'
      ].join('\n\n')
    },
    {
      role: 'user',
      content: [
        hint ? `User Hint / Focus: ${hint}` : '',
        'Input Data to Diagram:',
        extractedText
      ]
        .filter(Boolean)
        .join('\n\n')
    }
  ];

  const selectionRaw = await callLLMWithFallback(selectionMessages, deadlineAt, 512);
  let parsedSelection = { diagramType: 'Flowchart', rationale: 'Defaulted to Flowchart.' };
  try {
    const jsonMatch = selectionRaw.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      parsedSelection = JSON.parse(jsonMatch[0]);
    }
  } catch {
    // Fallback to Flowchart if JSON parsing fails
  }

  const catalogEntry =
    findDiagramCatalogEntry(parsedSelection.diagramType) ||
    findDiagramCatalogEntry('Flowchart');

  const chosenTypeName = catalogEntry.name;
  const rationale = parsedSelection.rationale || `Selected ${chosenTypeName} for this data.`;

  // STEP 2: Generate Mermaid code using the exact syntax + DHS color + orientation prompts
  const syntaxSystemPrompt = await buildDiagramSyntaxPrompt(chosenTypeName);
  const generationMessages = [
    {
      role: 'system',
      content: [
        syntaxSystemPrompt,
        'CRITICAL INSTRUCTION: Output ONLY valid Mermaid diagram code inside a single ```mermaid ... ``` code block. Do not include any prose before or after the fenced code block.'
      ].join('\n\n')
    },
    {
      role: 'user',
      content: [
        `Generate a ${chosenTypeName} diagram for the following data.`,
        hint ? `User Hint / Focus: ${hint}` : '',
        'Data:',
        extractedText
      ]
        .filter(Boolean)
        .join('\n\n')
    }
  ];

  const firstReply = await callLLMWithFallback(generationMessages, deadlineAt, 2500);
  let mermaidSource = extractMermaidCodeBlock(firstReply);

  // Attempt 1 Render
  try {
    const renderOut = await renderDiagram({ mermaid: mermaidSource, format: 'png' });
    return {
      pngBase64: normalizePngBase64(renderOut),
      diagramType: chosenTypeName,
      rationale,
      mermaidSource
    };
  } catch (firstRenderErr) {
    // Attempt 2: Self-Correction Retry if time remains
    const remainingMs = deadlineAt - Date.now();
    if (remainingMs < MIN_USEFUL_RETRY_MS) {
      throw new PipelineError(
        'RENDER_FAILED',
        `Mermaid render failed on first attempt and insufficient time remained to self-correct: ${firstRenderErr.message}`
      );
    }

    const repairMessages = [
      ...generationMessages,
      { role: 'assistant', content: '```mermaid\n' + mermaidSource + '\n```' },
      {
        role: 'user',
        content: [
          `The Mermaid renderer rejected your diagram with the following error:`,
          firstRenderErr.message,
          `Fix the syntax error while strictly preserving the ${chosenTypeName} type and DHS color rules. Output ONLY the corrected \`\`\`mermaid ... \`\`\` block.`
        ].join('\n\n')
      }
    ];

    const repairedReply = await callLLMWithFallback(repairMessages, deadlineAt, 2500);
    mermaidSource = extractMermaidCodeBlock(repairedReply);

    try {
      const secondRenderOut = await renderDiagram({ mermaid: mermaidSource, format: 'png' });
      return {
        pngBase64: normalizePngBase64(secondRenderOut),
        diagramType: chosenTypeName,
        rationale,
        mermaidSource
      };
    } catch (secondRenderErr) {
      throw new PipelineError(
        'RENDER_FAILED',
        `Mermaid render failed after self-correction retry: ${secondRenderErr.message}`
      );
    }
  }
}
```

---

### 4.6 `server.mjs` (Express + Stateless Streamable HTTP MCP Endpoint)

```javascript
// server.mjs
import express from 'express';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { z } from 'zod';

import { warmLoadPdfParse, extractInputData } from './lib/extractText.mjs';
import { generateDiagramFromText } from './lib/llm.mjs';
import { renderDiagram } from './lib/render.mjs';

// 1. Process-wide crash guards (Defense-in-depth — see §5.3)
process.on('unhandledRejection', (reason) => {
  console.error('[unhandledRejection]', reason);
});
process.on('uncaughtException', (err) => {
  console.error('[uncaughtException]', err);
});

// 2. CRITICAL: Warm-load pdf-parse BEFORE any request can trigger render.mjs's jsdom global install (§5.1)
await warmLoadPdfParse();

const app = express();
app.use(express.json({ limit: '20mb' }));

/**
 * Factory creating a stateless McpServer instance bound to the current request context.
 */
function createMcpServerForRequest(userForwardedToken) {
  const server = new McpServer({
    name: 'mcp-mermaid-generator',
    version: '1.0.0'
  });

  server.tool(
    'generate_diagram',
    'Ingests raw data (JSON, CSV, YAML, or plain text) or a PDF/document (via base64 or Databricks Workspace/Volumes path), automatically selects the optimal Mermaid diagram type using an LLM, renders it with the DHS color palette, and returns a PNG image.',
    {
      data: z
        .string()
        .optional()
        .describe('Raw text data to diagram (e.g., JSON string, CSV, YAML, or plain text).'),
      pdfBase64: z
        .string()
        .optional()
        .describe('Base64-encoded PDF file bytes (without data:application/pdf;base64, prefix).'),
      workspacePath: z
        .string()
        .optional()
        .describe('Databricks Workspace or Volumes path (e.g., /Workspace/Users/.../doc.pdf or /Volumes/.../data.json).'),
      hint: z
        .string()
        .optional()
        .describe('Optional one-line instruction or focus area (e.g., "Focus on the authentication flow").')
    },
    async ({ data, pdfBase64, workspacePath, hint }) => {
      try {
        const { text: extractedText } = await extractInputData({
          data,
          pdfBase64,
          workspacePath,
          userToken: userForwardedToken
        });

        const result = await generateDiagramFromText({
          extractedText,
          hint
        });

        return {
          content: [
            {
              type: 'image',
              data: result.pngBase64,
              mimeType: 'image/png'
            },
            {
              type: 'text',
              text: JSON.stringify(
                {
                  status: 'OK',
                  diagramType: result.diagramType,
                  rationale: result.rationale,
                  mermaidSource: result.mermaidSource
                },
                null,
                2
              )
            }
          ]
        };
      } catch (err) {
        const errorCode = err?.code || 'RENDER_FAILED';
        return {
          isError: true,
          content: [
            {
              type: 'text',
              text: JSON.stringify(
                {
                  status: 'ERROR',
                  errorCode,
                  message: err?.message || 'Unexpected error during diagram generation.'
                },
                null,
                2
              )
            }
          ]
        };
      }
    }
  );

  return server;
}

// 3. Stateless Streamable HTTP MCP Endpoint (/mcp)
app.post('/mcp', async (req, res) => {
  const userForwardedToken = req.headers['x-forwarded-access-token'];
  const server = createMcpServerForRequest(userForwardedToken);
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: undefined
  });

  res.on('close', () => {
    transport.close().catch(() => {});
    server.close().catch(() => {});
  });

  try {
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (err) {
    console.error('[/mcp error]', err);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: '2.0',
        error: { code: -32603, message: 'Internal MCP server error' },
        id: null
      });
    }
  }
});

// Stateless HTTP MCP does not support standalone GET/DELETE streams
app.get('/mcp', (_req, res) => {
  res.status(405).json({
    jsonrpc: '2.0',
    error: { code: -32000, message: 'Method not allowed. Use POST /mcp.' },
    id: null
  });
});

app.delete('/mcp', (_req, res) => {
  res.status(405).json({
    jsonrpc: '2.0',
    error: { code: -32000, message: 'Method not allowed in stateless MCP mode.' },
    id: null
  });
});

// 4. Health & Diagnostic Self-Test Endpoints
app.get(['/', '/healthz'], (_req, res) => {
  res.json({
    status: 'ok',
    service: 'mcp-mermaid-generator',
    mcpEndpoint: '/mcp',
    tools: ['generate_diagram']
  });
});

app.get('/api/selftest-render', async (_req, res) => {
  try {
    const sample = 'flowchart TD\n  A[MCP Server] --> B[PNG Rendered OK]';
    const out = await renderDiagram({ mermaid: sample, format: 'png' });
    const pngBase64 =
      typeof out === 'string'
        ? out.replace(/^data:image\/png;base64,/i, '')
        : (out?.png ?? out?.pngBase64 ?? '').toString('base64');
    res.json({
      status: 'ok',
      pngBase64Length: pngBase64.length
    });
  } catch (err) {
    res.status(500).json({
      status: 'error',
      message: err.message
    });
  }
});

const port = Number(process.env.DATABRICKS_APP_PORT || 8000);
app.listen(port, '0.0.0.0', () => {
  console.log(`mcp-mermaid-generator listening on http://0.0.0.0:${port}/mcp`);
});
```

---

## 5. Hard-Won Lessons from Original Deployment (DO NOT VIOLATE)

Read this section before modifying any part of `server.mjs`, `lib/extractText.mjs`, `lib/render.mjs`, or `lib/rasterizeWorker.mjs`.

1. **Module Load Order Between `pdf-parse` and `jsdom` (Real, Reproduced Bug):**
   `lib/render.mjs`'s first render installs `jsdom`'s `window` and `document` onto Node's `globalThis` permanently. `pdf-parse`'s bundled UMD `pdf.js` checks `typeof window !== 'undefined'` at **module-load time** to select a browser vs. Node export branch; if `globalThis.window` is already set when `pdf-parse` is imported for the first time, every PDF parse fails with `ReferenceError: PDFJS is not defined`. Calling `await warmLoadPdfParse()` at the top of `server.mjs` startup (before any render can run) prevents this permanently.
2. **`htmlLabels: false` and `<foreignObject>` (Silently Blank Labels):**
   Mermaid defaults to rendering node labels as HTML inside an SVG `<foreignObject>`. The Rust `@resvg/resvg-js` rasterizer silently ignores `<foreignObject>`, producing boxes with invisible/blank text and no error. `lib/render.mjs` sets `htmlLabels: false` both at the top level and inside `flowchart: { htmlLabels: false }` so Mermaid outputs standard SVG `<text>`/`<tspan>` nodes. Never change `htmlLabels` to `true`.
3. **Abandoned Render Promises Can Crash the Process:**
   When a render is wrapped in a timeout race (`Promise.race`), a losing render promise keeps executing in the background. If it later rejects without a `.catch(() => {})` handler attached, Node terminates the process on `unhandledRejection`. Keep the `.catch(() => {})` on the inner render promise in `lib/render.mjs` AND keep the process-level `unhandledRejection`/`uncaughtException` handlers in `server.mjs`.
4. **Native Rust Crashes in `@resvg/resvg-js` Require Child-Process Isolation & Bundled Fonts:**
   The Databricks Apps container has **zero system fonts installed**, and an empty font database with `loadSystemFonts: false` (or an extreme SVG `viewBox` dimension) triggers a native Rust panic/SIGABRT in `@resvg/resvg-js` that no JS `try/catch` can intercept. That is why `lib/rasterizeWorker.mjs` runs in a separate child process, enforces a pixel dimension guard, and explicitly passes the bundled `dejavu-fonts-ttf` font files (`DejaVuSans.ttf`).
5. **Browser Navigation to Non-Root Routes Can Return 401 on Databricks Apps:**
   Navigating directly to `/api/selftest-render` in a fresh browser tab may return `401` at the Databricks edge proxy. To test `/api/selftest-render` from a browser, first open the root app URL `/` (which completes the Databricks OAuth flow), then run `fetch('/api/selftest-render').then(r => r.json()).then(console.log)` in the browser DevTools console.

---

## 6. Step-by-Step Build & Verification Checklist

1. **Scaffold & Copy Reusable Files:**
   * Create the `mcp-mermaid-generator/` folder.
   * Copy `PROMPTS/`, `lib/databricksAuth.mjs`, `lib/prompts.mjs`, `lib/render.mjs`, and `lib/rasterizeWorker.mjs` from `/Workspace/Users/tom.jacobson@hq.dhs.gov/mermaid-diagram-generator`.
2. **Create the New MVP Files:**
   * Create `package.json` (§3.1) and `app.yaml` (§3.2).
   * Create `lib/extractText.mjs` (§4.2), `lib/llm.mjs` (§4.5), and `server.mjs` (§4.6).
3. **Verify Health & Rendering Pipeline:**
   * Run `npm install && node server.mjs`.
   * Verify `GET /healthz` returns `{"status":"ok","service":"mcp-mermaid-generator","mcpEndpoint":"/mcp"}`.
   * Verify `GET /api/selftest-render` returns `{"status":"ok","pngBase64Length":...}` with `pngBase64Length > 1000`.
4. **Verify MCP Protocol (`POST /mcp`):**
   * **Test 1 (Tool Discovery):** Send a JSON-RPC `tools/list` request to `POST /mcp` and verify `generate_diagram` is returned with `data`, `pdfBase64`, `workspacePath`, and `hint` properties.
   * **Test 2 (JSON Input -> PNG Output):** Call `generate_diagram` with `{"data": "{\"service\": \"AuthGateway\", \"steps\": [\"Receive Token\", \"Validate Signature\", \"Forward to API\"]}"}`. Confirm the response contains `content[0].type === "image"`, `content[0].mimeType === "image/png"`, non-empty base64 data (with no `data:image/png;base64,` prefix), and `content[1]` JSON with `"status": "OK"`.
   * **Test 3 (PDF Input -> PNG Output):** Call `generate_diagram` with a valid `pdfBase64` payload. Confirm text extraction succeeds without `ReferenceError: PDFJS is not defined` and returns a valid PNG image.
   * **Test 4 (Error Code Handling):** Call `generate_diagram` with `{}` (empty arguments) and confirm it returns `isError: true` and `"errorCode": "INVALID_INPUT"`.
