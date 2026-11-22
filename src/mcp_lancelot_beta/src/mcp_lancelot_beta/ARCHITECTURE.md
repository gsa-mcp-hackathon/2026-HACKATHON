# mcp-lancelot-beta — Architecture

Status: reviewed 2026-11-05, after Phase 1 approval and the V19 run, before Phase 2. Updated the same day for the pre-Phase 2 housekeeping (committed tests, README, `/health` fix; section 15). Updated 2026-11-06 for the multi-tool expansion (`BUILD_PLAN.md` D30–D36): invariants 1, 2, 4, 14 rewritten, 19 added; the second tool, Choropleth, is **Planned** (not built). Updated 2026-11-12 for `BUILD_PLAN.md` D44 (**Planned**, not built): the Choropleth tool also returns a square PNG of the disaster's affected counties; invariants 3, 4, 14, 19 and sections 4.1, 4.3, 15 amended. Updated again 2026-11-12: the Choropleth tool (D37–D43) is now documented as **Built** (sections 1, 3, 4, 5.5, 6.2, 6.5, 7.1, 9, 11, 15).

This document is the reference for **what the architecture is and the rules that keep it that way**. Use it before every change: if a change breaks a rule in section 3 or alters a contract in section 6, it is an architecture change and needs a recorded decision first (section 14).

Related documents:

| Document | Role |
|---|---|
| `ARCHITECTURE.md` (this file) | The architecture, its invariants, and the review checklist |
| `BUILD_PLAN.md` | Build history, decision log (Q1–Q8, D1–D44), phase status, verification checklist (V1–V21), run results |
| `lib/tools/mermaid/PROMPTS/MCP_REBUILD_GUIDE.md` | The original rebuild spec. Superseded wherever `BUILD_PLAN.md` corrects it (corrections C1–C13) |
| `docs/V19_TRACE_FAILURE_TEST.md` | Manual, on-request-only trace-failure test |
| `SECURITY.md`, `LICENSE.md` | Carried over unchanged from the original app (decision Q4) |

Status labels used below: **Built** (deployed and verified), **Phase 2** (agreed, not built yet), **Planned** (decided in `BUILD_PLAN.md`, design not final, not built).

---

## 1. What the system is

A headless **Model Context Protocol (MCP) server** running as the Databricks App `mcp-lancelot-beta`. A client sends one document; the server picks a Mermaid diagram type, has an LLM write Mermaid source, renders it to PNG on the server, and returns the PNG. There is no user interface and no conversation state: the calling client (AI Playground, Genie Code, an agent, or a future web front end) owns the conversation.

**Expanding (2026-11-06, D30–D36):** the server is becoming a multi-tool MCP server of specialized visualization tools (goal: a dozen or more). The second tool, `generate_choropleth` (**Built**, D42, D43; deployed, startup self-test OK), returns a self-contained, interactive county map of FEMA Public Assistance cost outliers for one disaster, as an HTML widget the caller embeds in its own page. All map code is ours, with no third-party JavaScript (D42 replaced the original D3.js plan). It reads JSON files that the daily OpenFEMA load job exports to the volume `choropleth_data` (D41; it never queries tables), plus county shapes from the yearly Census boundary job (D43), and makes no LLM calls. Tool code is kept in separate folders and never shared between tools.

It is a rebuild of the original "Lancelot Beta" web app (`/Workspace/Users/tom.jacobson@hq.dhs.gov/mermaid-diagram-generator`, read-only reference copy). The rebuild keeps the original's server-side modules unchanged and drops everything client-side (React UI, Manual Editor, in-browser Mermaid, chat sessions).

```text
 MCP client (AI Playground / Genie Code / agent / lancelot-client)
        |  POST /mcp  generate_diagram(...) | generate_choropleth(...)
        v
 +------------------------- Databricks App: mcp-lancelot-beta --------------------------+
 |  server.mjs (Express)                                                                |
 |    inputs.mjs ---> extractText.mjs (verbatim)                                        |
 |    pipeline.mjs --> selection.mjs --> prompts.mjs + PROMPTS/ (verbatim)              |
 |         |                                                                            |
 |         +--> Model Serving: databricks-claude-haiku-4-5 -> databricks-gpt-5-4-mini   |
 |         +--> render.mjs (verbatim, jsdom + mermaid) --> rasterizeWorker.mjs (child)  |
 |    tracer.mjs ---> Files API ---> UC volume users.tom_jacobson.lancelot_traces       |
 |    report.mjs (startup HTML report)                                                  |
 |                                                                                      |
 |    choropleth/tool.mjs --> inputs, data, analysis, geo, widget (no LLM, no SQL)      |
 |         data.mjs ---> Files API ---> UC volume users.tom_jacobson.choropleth_data    |
 +--------------------------------------------------------------------------------------+
        ^ snapshots/<date>/ (daily, ops/openfema_load.py)   ^ geo/v1/ (yearly, ops/county_boundaries_load.py)
```

## 2. Platform resources

| Resource | Value | Notes |
|---|---|---|
| App | `mcp-lancelot-beta` | The `mcp-` prefix lets AI Playground discover it. Name is permanent |
| URL | `https://mcp-lancelot-beta-7474654188777746.aws.databricksapps.com` | Behind Databricks OAuth |
| Source folder | `/Workspace/Users/tom.jacobson@hq.dhs.gov/lancelot-beta` | Git folder, branch `main`. The folder name is unrelated to the deleted `lancelot-beta` app |
| Service principal | `app-2vrjmx mcp-lancelot-beta` (client ID `f225bec3-b066-4d07-bfd4-21f6994830fe`) | Used for LLM calls and trace writes |
| Resource `llm-primary` | `databricks-claude-haiku-4-5`, `CAN_QUERY` (D27) | Primary for every LLM step |
| Resource `llm-fallback` | `databricks-gpt-5-4-mini`, `CAN_QUERY` (D27) | Only fallback |
| Resource `trace-volume` | `users.tom_jacobson.lancelot_traces`, `WRITE_VOLUME` | All traces, artifacts, reports |
| Resource `choropleth-data` | `users.tom_jacobson.choropleth_data`, `READ_VOLUME` (D41) | Choropleth data as JSON files exported by the load job (`manifest.json`, `snapshots/<date>/`); env `CHOROPLETH_DATA_VOLUME`. The app has no table grants and no SQL warehouse (D40 table resources removed; no warehouse available) |
| User authorization scope | `workspace.workspace:read` | Only for `workspacePath` input (Phase 2) |
| Compute | MEDIUM | |

Resources live on the app (configured through the Apps API/UI), not in `app.yaml`. `app.yaml` only maps them to environment variables with `valueFrom`.

---

## 3. Architectural invariants

These are the rules. Each is backed by a decision or a confirmed failure; the reference is in brackets.

**Shape**
1. **Many tools, one registry, stateless.** The server exposes a set of MCP tools, each in its own folder (`lib/tools/<tool>/`, layout approved in D32, moved in D37) and registered in one place; tools share only the core (server, tracer, request budget, registry) and never import from each other. Built: `generate_diagram`, `generate_choropleth` (D42). Adding a tool needs a recorded decision (section 14). Every request is independent: no sessions, no stored conversation, no per-user state in memory. In Phase 2 a fresh `McpServer` + `StreamableHTTPServerTransport({ sessionIdGenerator: undefined })` is created per `POST /mcp` and closed on `res.on('close')`. [guide §2, plan §8]
2. **Headless server; tools may return browser widgets.** The server has no UI of its own and no static front end, and nothing from the original `src/`, `dist/`, `public/`, Vite, or `lib/sessions.mjs` comes back [plan §7]. A tool may return a self-contained HTML widget that runs in the caller's browser (Choropleth, D31, D36); the server never hosts widgets on a route. [D30]
3. **Server-side rendering only.** Mermaid is rendered by `lib/tools/mermaid/lib/render.mjs` (jsdom + mermaid) and rasterized by `lib/tools/mermaid/lib/rasterizeWorker.mjs` in a child process. No Chromium/Puppeteer (cannot launch in the Apps container). The Choropleth PNG (Planned, D44) is an SVG rasterized with `@resvg/resvg-js` in the Choropleth tool's own child-process worker, for the same native-crash isolation; it never imports the Mermaid worker (invariant 1). [original render.mjs, D44]
4. **Each tool declares its output type.** `generate_diagram`: PNG only; no SVG is returned or saved (D10), and a PNG rasterization failure is `RENDER_FAILED`, never a fallback to SVG (Q2). `generate_choropleth`: one self-contained HTML widget as an MCP embedded resource, plus a text summary and its data JSON (D36); Planned (D44): always also one 1000x1000 PNG of the disaster's affected counties as an MCP `image` content item, described in the JSON as `image` (`uri` `ui://lancelot-beta/choropleth/<runId>.png`, `mimeType`, `width`, `height`, `bytes`, `sha256`, `mapDrawn`, `reason`). Widget and image are always returned together, inline; no URL or volume path is returned for either (the `ui://` URIs are labels, not fetchable). If the map cannot be drawn the PNG is the FEMA-logo fallback and the call is still `OK`; `image: null` only if rasterizing itself fails. [D30, D44]

**Reuse**
5. **Verbatim modules stay verbatim.** `lib/tools/mermaid/lib/render.mjs`, `rasterizeWorker.mjs`, `prompts.mjs`, `extractText.mjs`, `diagramTypeTestSnippets.mjs`, `lib/core/databricksAuth.mjs`, all 36 prompt files in `lib/tools/mermaid/PROMPTS/`, `LICENSE.md`, `SECURITY.md` are byte-identical copies of the original. Wrap or call them; do not edit them (section 4.2).
6. **Prompts are data.** All Mermaid LLM-facing instructions come from `lib/tools/mermaid/PROMPTS/` through `prompts.mjs` (`buildDiagramSyntaxPrompt`, `INITIAL_INSTRUCTIONS_PROMPT`, `DIAGRAM_CATALOG`). New code may add short output-format rules (for example "one fenced mermaid block") but must not duplicate or rewrite the prompt content.

**Model use**
7. **Fixed two-endpoint chain, model-agnostic code.** Primary, then fallback, for every step including type selection (D25). Currently Claude Haiku 4.5, then GPT-5.4 Mini (D27, replacing Gemini 3.8 Flash and Grok 4.6). No Opus, no third endpoint (D1). Endpoint names come only from `LLM_ENDPOINT_PRIMARY` / `LLM_ENDPOINT_FALLBACK` (D3); no code may name a model. Avoid reasoning models whose hidden reasoning can exhaust `max_tokens` (Grok finding, D26).
8. **No `temperature`.** Gemini 3.8 Flash rejected it with HTTP 400 (first Phase 1 deploy). The request is `{ messages, max_tokens }`; any new model must be checked with it, and no sampling parameters may be added without testing both endpoints.
9. **Retry rules.** Fall through to the fallback only on timeout, network error, bad JSON, empty reply, 429, or 5xx. Any other 4xx is a configuration error: stop with `LLM_ERROR`. One syntax-only repair attempt, and only when the renderer throws `ValidationError`. [plan §4]

**Time**
10. **One request-wide deadline of 70 s**, covering extraction, selection, generation, rendering, and repair (the Apps proxy resets connections at roughly 60–90 s). Every stage is capped from the remaining budget (section 5.3). Tracing never consumes this budget.

**Observability**
11. **Every run is traced to the volume**, every LLM attempt is recorded (including failed, skipped, and fallback attempts), and the agent can verify a deployment from the trace alone, without app logs or calling the app URL. [plan §8a]
12. **Tracing never changes a result.** Every trace write is individually caught; a trace failure is logged and recorded but never alters the tool result and never becomes an unhandled rejection. Proven by V19 (2026-11-05).
13. **Content is traced only at `debug`.** At `production`, traces hold metadata only: no document text, prompts, replies, Mermaid, rationale, or previews, and error messages are reduced to their length (D6).

**Security**
14. **All document- and source-derived content is untrusted**, including LLM output (prompt injection) and OpenFEMA free text such as project titles. Mermaid rendering uses `securityLevel: 'strict'`, `htmlLabels: false`, and strips `%%{...}%%` directives; the startup HTML report escapes everything and contains no JavaScript or external links. Widgets may contain JavaScript **only** from this repository (D42: no third-party JavaScript; the Choropleth script is `widgetMain` in `widget.mjs`, serialized with `toString()`), with no CDN and no network access (Content-Security-Policy `default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:`); embedded data is JSON-escaped (`<`, `>`, `&`, U+2028, U+2029) and all text is set with `textContent`, never `innerHTML` (D30, D36). Server-built SVG (Choropleth PNG, D44) XML-escapes every text node, including the OpenFEMA declaration title, and references no external files (the logo is embedded from the bundled `assets/fema-logo.png`).
15. **User files are read as the user, inside the user's home only** (Phase 2). `workspacePath` uses the forwarded user token, restricted to `/Users/<x-forwarded-email>/`, with no service-principal fallback and no `/Volumes` input (C6, C7). **Known limit (Q3, answered 2026-11-05):** when another Databricks App calls this server *as a signed-in user* (passing on that user's token), Databricks forwards the user's identity (`x-forwarded-email`, `x-forwarded-user`) but not `x-forwarded-access-token`, so `workspacePath` returns `ACCESS_DENIED` by design; such clients send files as `fileBase64`. When the other app calls *as its own service principal*, both the identity (the service principal's application ID) and a token are forwarded, so `workspacePath` works for files in that service principal's own `/Users/<application-id>/` folder, and never anyone else's.

**Operations**
16. **Deploy only through the Apps API**, after `apps get` confirms `RUNNING` with no pending deployment. Settings changes always send the full app body (section 7.3).
17. **Never push to GitHub.** Commits and tags are local only.
18. **Manual tests stay manual.** V19 runs only on the user's explicit request (D17); the human review gate before a new phase is mandatory (D11).

**Data**
19. **No invented data.** Every number and place a tool shows comes from loaded source rows, computed in code or SQL, never by an LLM (D33, D34). Choropleth locations are county only; no addresses, geocoding, or guessed coordinates (D35). Dot positions inside a county are arbitrary and the widget says so. The Choropleth PNG (D44) highlights only counties FEMA designated in the disaster's declaration file (`gis.fema.gov/maps/dec_<n>.zip`, loaded by the daily job), with Individual Assistance or any PA category other than B (blank or PA Category B only = not affected); tribal areas without a county code use FEMA's own outlines. Its title is FEMA's official declaration title, never an LLM- or hand-written name.

---

## 4. Components

### 4.1 File map

Folder layout (D32, moved by D37 on 2026-11-06): **`lib/core/`** = shared by all tools (`tracer.mjs`, `databricksAuth.mjs`); **`lib/tools/mermaid/lib/`** = the `generate_diagram` tool's modules; **`lib/tools/mermaid/PROMPTS/`** = its prompt files (the verbatim `prompts.mjs` reads `../PROMPTS` relative to itself, which is why the modules sit one level down in `lib/`). Future tools get `lib/tools/<tool>/`. `server.mjs`, `selftest/`, `test/`, and `ops/` stay at the root. Older decision records in `BUILD_PLAN.md` use the pre-move paths.

| File | Status | Responsibility | Must not |
|---|---|---|---|
| `server.mjs` | Built (Phase 1 + Phase 2 endpoint) | Process crash guards, pdf-parse warm-load, HTTP routes, MCP SDK wiring (zod schema, per-request `McpServer` + transport), diagnostics routes, startup self-test orchestration | Contain pipeline or tool logic or prompt text; block `listen()` on the self-test |
| `lib/tools/mermaid/lib/tool.mjs` | Built (D21) | The `generate_diagram` tool: arguments + caller identity -> MCP result; fills the per-call trace; never throws | Import the MCP SDK, zod, or express |
| `lib/tools/mermaid/lib/inputs.mjs` | Built | Input validation (`data`, `fileBase64` + `fileName`, `workspacePath`, file bytes), size limits, home-folder scoping, workspace read with the user token, extractor selection, extraction timeout, truncation flag | Call LLMs or render; read user files with the service principal |
| `lib/tools/mermaid/lib/selection.mjs` | Built | Step 1: type selection prompt from PROMPT 1's table (allowed types only), reply parsing with Flowchart default | Import `pipeline.mjs` (receives `callLlm` as a parameter) |
| `lib/tools/mermaid/lib/diagramPolicy.mjs` | Built (D29) | `EXCLUDED_DIAGRAM_TYPES` (types we choose never to use: TreeView, Treemap, Cynefin) and `findAllowedDiagramType`, the single check every type choice goes through (selection list, model reply, caller's `diagramType`) | Edit `prompts.mjs`; name a type that is not in `DIAGRAM_CATALOG` (a test fails) |
| `lib/tools/mermaid/lib/pipeline.mjs` | Built | 70 s budget, LLM client with fallback, Step 2 generation, render, single repair, single resize retry (D28), `PipelineError` | Write files; know about HTTP/MCP |
| `lib/tools/choropleth/lib/tool.mjs` | Built (D42) | The `generate_choropleth` tool: arguments -> MCP result (text summary, embedded `text/html` widget, JSON as `structuredContent` and a second text item); applies county-code aliases (D43 `RECODE`) before analysis; fills the per-call trace; never throws | Import the MCP SDK, zod, or express; call an LLM; import `lib/tools/mermaid/` |
| `lib/tools/choropleth/lib/inputs.mjs` | Built | Input parsing (`disaster_number`, `pw_number`, `applicant_id`, `sigma_threshold` 1–10 default 3, `as_of`, and the D46 display options via `parseDisplay`/`DISPLAY_DEFAULTS`), `ChoroplethError`; pure | Read data |
| `lib/tools/choropleth/lib/data.mjs` | Built (D41) | Reads `manifest.json`, the disaster file, and `geo/v1/states/<SS>.json` from `CHOROPLETH_DATA_VOLUME` with the service principal; snapshot selection; `DATA_UNAVAILABLE` / `SNAPSHOT_NOT_FOUND` / `DISASTER_NOT_LOADED` | Read a snapshot not listed in the manifest; query tables |
| `lib/tools/choropleth/lib/analysis.mjs` | Built | Applies the sigma threshold to precomputed sigma (population stddev per category, D34), views per category, county outlier counts, PW highlight (`PW_NOT_FOUND`); pure | Compute numbers the gold tables already hold differently |
| `lib/tools/choropleth/lib/geo.mjs` | Built (D42) | Projection, SVG paths, county adjacency, DSatur shading (5 shades per color family), seeded dot placement; pure | Place a dot outside a shape |
| `lib/tools/choropleth/lib/widget.mjs` | Built (D42) | Widget data JSON and the self-contained HTML (CSP, browser script `widgetMain`; D46 display options as `data.ui`, D47 collapsible outlier table; since D48 no caveats, definition line or location notes in the page) | Use `innerHTML`, external URLs, or third-party JavaScript |
| `lib/core/tracer.mjs` | Built (core) | Volume writes (Files API), trace levels, redaction, LLM attempt records, version and source hash (all `lib/**/*.mjs`, D37), V19 fault injection | Import anything from `lib/tools/`; throw from any write path |
| `lib/tools/mermaid/lib/report.mjs` | Built | Startup HTML report from a tracer instance | Import anything; emit `<script>` or external URLs; output unescaped content |
| `lib/tools/mermaid/lib/render.mjs` | Verbatim | Mermaid to SVG (jsdom) and PNG (child process), validation, timeouts, concurrency | (do not edit) |
| `lib/tools/mermaid/lib/rasterizeWorker.mjs` | Verbatim | resvg PNG rasterization in an isolated child process, bundled DejaVu fonts | (do not edit) |
| `lib/tools/mermaid/lib/prompts.mjs` | Verbatim | Loads `lib/tools/mermaid/PROMPTS/`, `DIAGRAM_CATALOG` (32 types), `UNSUPPORTED_DIAGRAM_TYPES` (4), prompt builders | (do not edit) |
| `lib/tools/mermaid/lib/extractText.mjs` | Verbatim | PDF, DOCX, XLSX, HTML, CSV, JSON, YAML, TXT, MD extraction, 60,000-char truncation | (do not edit) |
| `lib/core/databricksAuth.mjs` | Verbatim (core) | Service-principal OAuth token (`getAccessToken`), host normalization (`getWorkspaceHost`) | (do not edit) |
| `lib/tools/mermaid/lib/diagramTypeTestSnippets.mjs` | Verbatim | One minimal snippet per catalog type, for the gallery | (do not edit) |
| `lib/tools/mermaid/PROMPTS/` | Verbatim (36 files) + `MCP_REBUILD_GUIDE.md` | Prompt text and per-type syntax guides | Be reformatted; `MDG PROMPT 2` and `3` keep CRLF line endings |
| `selftest/` | Built | Non-sensitive sample inputs (`sample.pdf` end to end; `.docx`, `.xlsx`, `.json` extraction only) | Contain real or sensitive documents |
| `test/` | Built | Unit tests (`node:test`): `selection`, `tracer`, `report`, `pipeline`, `fault-injection`, `tool`, `inputs`, `diagramPolicy`, `choropleth` (injected fake `readFile`, no volume), shared `helpers.mjs` (its `LIB()` maps a module name to `lib/core/` or `lib/tools/mermaid/lib/`); plus `test_trace_cleanup.py`, `test_openfema_load.py`, and `test_county_boundaries_load.py` (Python `unittest`, no Spark or network) for `ops/`. No npm packages needed | Call real endpoints or the real volume; depend on test order across files |
| `ops/trace_cleanup.py` | Built | Trace retention (Q7): deletes `runs/<YYYY-MM-DD>` folders older than 30 days. Run by the scheduled job in section 11, not by the app | Touch anything outside `runs/<YYYY-MM-DD>/`; be imported by the app |
| `ops/openfema_load.py` | Built (D39, D41) | Choropleth data: daily OpenFEMA PA load into `users.tom_jacobson.openfema_pa_*` (bronze, silver, category stats gold, projects gold, load log), then a JSON export per disaster to the volume `choropleth_data` with `manifest.json` written last; checks, gate, same-day replace, 90-day retention. Run by the job `mcp-lancelot-beta OpenFEMA load` (section 11), not by the app | Call an LLM; write outside its five tables and the `choropleth_data` volume; mark a snapshot SUCCEEDED before every check passes; be imported by the app |
| `ops/county_boundaries_load.py` | Built (D43) | County shapes: Census Cartographic Boundary counties (2025, 1:5M; CT from 2021) into `census_boundaries` (raw zips + provenance), Delta `census_county_boundaries`, `census_fema_county_crosswalk`, `census_boundaries_load_log`, then `choropleth_data/geo/v1/states/<SS>.json` with `geo/v1/manifest.json` written last. Standard library only (own zip/shapefile/dBASE readers); SQL with parameter markers. Run by the job `mcp-lancelot-beta county boundaries load` (section 11), not by the app | Use GDAL or pip packages; change the pinned vintage without a reviewed decision; be imported by the app |
| `README.md` | Built | Entry point: what the server is, links to the other documents, test and deploy commands | Duplicate the rules in this file |
| `docs/` | Built | Runbooks (`V19_TRACE_FAILURE_TEST.md`) | |
| `app.yaml` | Built | Start command and env mapping | Contain resources, secrets, or V19 settings |
| `package.json` | Built | Dependencies (section 8) | Gain a `build` script or front-end packages |
| `assets/fema-logo.png` | Added 2026-11-12 (D44, used once built) | FEMA/DHS logo for the Choropleth PNG header and fallback (2048x724 RGBA, transparent, 305,669 bytes); DHS use approved per the user | Be fetched at run time, re-colored, or cropped; be used outside the Choropleth PNG without a decision |
| `VERSION.json` | Generated, gitignored | Commit stamp written before each deploy | Be committed |

### 4.2 Verbatim modules: how to change them

They carry the original's hard-won fixes (render load order, font bundling, bbox measurement, label centering, native-crash isolation, pdf-parse import path). If one truly must change:

1. Record a decision in `BUILD_PLAN.md` §11 with the reason and the evidence (trace or test).
2. Change the copy in `lancelot-beta`; never edit the reference folder `mermaid-diagram-generator`.
3. Prefer wrapping (a new module that calls it) over editing.
4. After the change, the gallery and the `sample.pdf` run must still pass, and the user reviews the report.

Verification method for byte-identity: compare file sizes with `GET /api/2.0/workspace/list` against the reference copy. Do not rely on `git diff --no-index` from inside the Git folder: it hid a CRLF difference once.

### 4.3 Allowed dependencies

```text
server.mjs  -> tool, tracer, inputs, pipeline, prompts, diagramTypeTestSnippets, render, report, databricksAuth,
               choropleth/tool, express, @modelcontextprotocol/sdk, zod
tool        -> inputs, pipeline, tracer      (no SDK, zod, or express: testable without npm packages)
pipeline    -> databricksAuth, prompts, render, selection, tracer
selection   -> prompts                      (never pipeline: callLlm is injected)
inputs      -> extractText, databricksAuth, tracer
tracer      -> databricksAuth               (never pipeline, render, inputs)
report      -> (nothing)

choropleth/tool     -> inputs, data, analysis, geo, widget, tracer (sha256)
choropleth/data     -> inputs, tracer (getFile, resolveVolumePath)
choropleth/analysis -> inputs
choropleth/widget   -> analysis
choropleth/geo, choropleth/inputs -> (nothing)
choropleth/image (Built, D44) -> geo (Choropleth), imageRasterWorker (child process), @resvg/resvg-js, dejavu-fonts-ttf, opentype.js, assets/fema-logo.png
                                   (packages and the asset only; never lib/tools/mermaid/)
```

Module names above are within their folder: `tracer` and `databricksAuth` are in `lib/core/`; `choropleth/<x>` is `lib/tools/choropleth/lib/<x>.mjs`; all others in `lib/tools/mermaid/lib/`. **Folder rule (D32):** a tool may import `lib/core/`; `lib/core/` never imports from `lib/tools/`; one tool never imports another tool's folder. `server.mjs` may import from core and from each tool's entry modules.

New modules follow the same direction: HTTP layer on top, pipeline in the middle, tracer and verbatim modules at the bottom. No cycles.

---

## 5. Runtime behavior

### 5.1 Startup sequence (Built)

1. Register `unhandledRejection` / `uncaughtException` handlers (log, do not exit).
2. **pdf-parse warm-load before anything can render**: invoke `pdf-parse/lib/pdf-parse.js` on a dummy buffer. `render.mjs` installs jsdom's `window` onto `globalThis` on first render; if pdf.js loads after that, every PDF fails with `PDFJS is not defined`. Order is mandatory.
3. `listen()` on `0.0.0.0:${DATABRICKS_APP_PORT || 8000}`.
4. Only then, in the background (`setImmediate`, never awaited), the startup self-test (section 9.2).

### 5.2 Request pipeline (pipeline Built; MCP entry Phase 2)

```text
input validation + extraction (inputs.mjs, <= 10 s)
  -> diagramType given and supported?  yes: skip selection
                                       no:  select (selection.mjs)
  -> generate Mermaid (buildDiagramSyntaxPrompt + output rule)
  -> render attempt 1
       ok                -> PNG
       ValidationError   -> repair once (if >= 20 s left) -> render attempt 2 -> PNG or RENDER_FAILED
       pngFailed, too large ("too large to rasterize safely (~WxHpx, max 8000px per side)")
                         -> resize once (if >= 20 s left; model told the size, the % to cut and
                            not much more, to show fewer items (shorter labels do not help),
                            a rough content-line target; same type) -> render again
                            -> PNG (resized: true) or RENDER_FAILED (stage rasterize)   (D28)
       pngFailed, other  -> RENDER_FAILED (stage rasterize), no repair
       timeout           -> RENDER_FAILED
```

### 5.3 Time budget

| Constant | Value | Where |
|---|---|---|
| Request budget `BUDGET_MS` | 70,000 ms | `pipeline.mjs` |
| Extraction `EXTRACT_TIMEOUT_MS` | 10,000 ms | `inputs.mjs` |
| Selection cap `SELECT_CAP_MS` | 12,000 ms | `pipeline.mjs` |
| Generation cap | min(45,000 ms, remaining − 25,000 ms); abort if < 5,000 ms | `pipeline.mjs` |
| Render cap `RENDER_CAP_MS` | min(40,000 ms, remaining) | `pipeline.mjs` |
| Repair only if remaining ≥ | 20,000 ms | `pipeline.mjs` |
| Fallback skipped if remaining < | 12,000 ms | `pipeline.mjs` |
| Renderer internal | 20 s SVG + 20 s PNG, 2 PNG attempts, 1 concurrent SVG render | `render.mjs` (verbatim) |
| Token limits | select 2,048; generate/repair 8,192; ping 1,024 | `selection.mjs`, `pipeline.mjs`, `server.mjs` |

Rule: any new stage takes its time from the same `deadlineAt`, never a fresh timer. Renders are serialized (shared jsdom globals), so queue wait counts against the budget.

### 5.4 Input limits

Maximum decoded file 14 MB (`generate_diagram`); supported extensions `.pdf .docx .xlsx .html .htm .txt .md .csv .json .yaml .yml`; extracted text truncated at 60,000 characters by `extractText.mjs` (recorded as `truncated: true`); Mermaid source maximum 20,000 characters (`render.mjs`); raster maximum 8,000 px per side.

### 5.5 Choropleth request flow (Built)

```text
parseInputs -> loadDisaster (manifest -> snapshot -> disaster file)
            -> loadGeometry (state files for the disaster's state FIPS; missing states recorded)
            -> apply county-code aliases (D43 RECODE) -> analyze (threshold, views, highlight)
            -> buildMap (or map.drawn: false with reason when no shapes) -> buildWidgetHtml -> result
```

No LLM, no SQL, no network beyond the Files API. It does not take a slice of the 70 s request budget (section 5.3) yet: typical runs take about 1 s (self-test `choroplethWidget` on DR-4856: 1,078 ms, 2026-11-12). A missing county shape is never an error: the widget still shows the filter, cards, and outlier table, and marks those rows "(not on map)"; when no county map can be drawn at all, a notice takes the map's place.

---

## 6. Contracts

Changing any of these is an architecture change (section 14).

### 6.1 Tool `generate_diagram` (Built, `lib/tools/mermaid/lib/tool.mjs`)

Inputs: exactly one of `data` (text), `fileBase64` + `fileName`, or `workspacePath`; optional `diagramType` (skips selection when it resolves to a supported type) and `hint`. No `pdfBase64` alias (Q1).

Success: `ImageContent` (`image/png`, base64 without data-URL prefix) plus `TextContent` JSON `{ status: "OK", runId, diagramType, rationale, mermaidSource, endpointUsed, repaired, resized, resize, truncated, width, height, timingsMs }` (`resize` is null, or `{ originalWidth, originalHeight, maxPx, finalWidth, finalHeight, note }` when the diagram was simplified to fit, D28). All arguments are optional strings in the schema; the "exactly one input" rule is enforced by `lib/tools/mermaid/lib/inputs.mjs`.

Errors: `isError: true` with `{ status: "ERROR", runId, errorCode, message, stage }`.

| Code | Meaning |
|---|---|
| `INVALID_INPUT` | No input, more than one input, missing `fileName`, empty or oversize file, `/Volumes` path |
| `UNSUPPORTED_FILE` | Extension or content not supported by `extractText.mjs` |
| `ACCESS_DENIED` | `workspacePath` outside the caller's home, identity not forwarded, or 401/403 from the workspace |
| `EXTRACTION_FAILED` | Parse failure, timeout, or empty text |
| `LLM_TIMEOUT` | Budget exhausted during an LLM step |
| `LLM_ERROR` | Non-timeout LLM failure on all endpoints, or a configuration 4xx |
| `RENDER_FAILED` | Invalid Mermaid after the one repair, no time left to repair, diagram still too large after the one resize (or no time left to resize; error JSON includes `resize` sizes), or PNG rasterization failed |
| `INTERNAL_ERROR` | Unexpected server bug (anything without its own code); logged to stdout with the runId |

There is no partial-success response. `mermaidSource` is always included on success (R6): it is the caller's own diagram and lets clients edit or re-render it.

### 6.2 HTTP routes

| Route | Status |
|---|---|
| `GET /`, `GET /healthz`, `GET /health` | Built. Payload: `status`, `service`, `phase: 2`, `version`, `mcpEndpoint: "/mcp"`, `tools: ["generate_diagram", "generate_choropleth"]`, `pdfWarmLoad`, `selftest` state, `faultInjection`, `traceVolumeEnv`. `selftest.report` is set only when the report write succeeded |
| `POST /mcp` | Built. Stateless Streamable HTTP, JSON responses (`enableJsonResponse: true`), body limit 20 MB; 413/400 come back as JSON-RPC errors |
| `GET`/`DELETE /mcp` -> 405 | Built |
| `GET /api/selftest-render`, `GET /api/selftest-diagram-gallery` | Built. In memory only; nothing written to the volume |
| `GET /api/selftest-obo-scope` | Built, temporary until Q3 is answered. Returns forwarded header names, identity presence, and a `workspace/list` probe with the forwarded token; never the token |

No route may re-run the startup self-test (D9).

### 6.3 Trace layout and schema

```text
/Volumes/users/tom_jacobson/lancelot_traces/
├── latest/startup-report.html     overwritten each startup (debug)
├── latest/startup-summary.json    pointer to the newest startup run
└── runs/<YYYY-MM-DD>/<runId>/     runId = <startup|call>-<UTC timestamp>-<6 hex>
    ├── started.json               written first (survives a crash)
    ├── trace.json                 written last (records earlier write failures)
    ├── report.html                startup runs, debug only
    └── artifacts/                 debug only
        ├── llm/<nn>-<step>-<endpoint>.json   every attempt: request, reply or error body
        ├── <file>/extracted.txt, attempt1.mmd, attempt2.mmd, output.png
        └── gallery/<type>.png
```

`trace.json` sections: `run`, `version` (VERSION.json, source hash, Node and package versions), `config` (trace level, endpoints, resolved volume path, fault injection), `llm` (one summary per attempt), stage records (`selftest` for startup runs; input, extract, select, generate, repair, render, response for calls), `tracer.writeErrors`. Field names are relied on by the agent's verification queries; rename only with a decision.

### 6.4 Startup report

One self-contained HTML file (§8b, D14–D16): section 0 is the `sample.pdf` PNG (or a large ❌ with stage and error), then summary, 32-type gallery grid, PDF run with every LLM attempt, extraction checks, pings and volume check, write errors. Inline CSS, data-URI images, `<details>` sections, no JavaScript, no external URLs, everything escaped, debug only.

### 6.5 Tool `generate_choropleth` (Built, `lib/tools/choropleth/lib/tool.mjs`)

Inputs (all optional strings or numbers in the zod schema; rules enforced by `inputs.mjs`): `disaster_number` (required, 1–99999), `pw_number` (highlight one project and open its category), `applicant_id` (only with `pw_number`, when a PW number exists for more than one applicant), `sigma_threshold` (1–10, default 3), `as_of` (`YYYY-MM-DD`, default the manifest's latest snapshot). Display options (D46; the defaults keep the standard page, other values are `INVALID_INPUT`): `initial_view` `pw_category` (default) or `all`; `show_pause_button`, `show_pw_card`, `show_all_categories_card` (boolean or `"true"`/`"false"`, default true); `legend_position` `below_cards` (default) or `below_map`; `click_details` `none` (default) or `modal` (click a dot or county for a details window inside the map); `map_aspect_ratio` (D50) one of `1:1`, `16:9`, `4:3`, `5:3`, `9:16`, `3:4`, `3:5` (width:height; the map box is 1000 wide and 1000 × h / w tall, the whole state fitted inside, centred; default: the box follows the state's shape, 1000 × 320–760).

Widget page, top to bottom (D49, no visible title; the hidden document `<title>` stays): category buttons, map (or the no-map notice), summary cards, legend (or the legend directly under the map with `legend_position: below_map`), and last the "Outliers in this view" table, a `<details>` element that opens expanded and can always be collapsed (D47). Nothing is shown below the table (D48): caveats, boundary source, snapshot dates and location counts are only in the text summary and `structuredContent`.

Success, in this order: `TextContent` summary (outlier counts, highlight, map note, first two caveats); an embedded resource `{ uri: "ui://lancelot-beta/choropleth/<runId>.html", mimeType: "text/html", text: <html> }` (the URI is a label, not fetchable; embed with `<iframe sandbox="allow-scripts" srcdoc=...>`); `TextContent` JSON, also returned as `structuredContent`: `{ status: "OK", runId, tool, disasterNumber, states, snapshotDate, loadId, latestSnapshot, newestLastRefresh, sigmaThreshold, initialView, display, totals, categories, highlight, outliers, countyOutliers, map: { drawn, reason, countiesNotInShapes, notPlaced, boundarySources }, widget: { uri, mimeType, bytes, sha256 }, caveats, timingsMs }`. Each outlier carries both `countyFips` (shape) and `femaCountyFips` (as published). D44 (Built): a third item, `{ type: "image", mimeType: "image/png", data }` (1000x1000), sits between the resource and the JSON, and `structuredContent.image = { mimeType, width, height, bytes, sha256, mapDrawn, reason, title, affectedCounties, affectedDrawn, affectedNotInShapes, extraAreas, declaration, rule, layout, fontMeasure, svgBytes, timingsMs }`; if rasterizing fails the item is left out, `image` is null and `imageError` says why (the call stays OK).

Errors: `isError: true` with `{ status: "ERROR", runId, tool, errorCode, message, stage, details? }`.

| Code | Meaning |
|---|---|
| `INVALID_INPUT` | Missing or malformed input, value out of range, `applicant_id` without `pw_number` |
| `DATA_UNAVAILABLE` | Volume not configured, manifest unreadable or unknown format, no latest snapshot, disaster file does not match the manifest's load |
| `SNAPSHOT_NOT_FOUND` | `as_of` not in the manifest; `details.available` lists the dates |
| `DISASTER_NOT_LOADED` | No PA projects for the disaster in that snapshot |
| `PW_NOT_FOUND` | `pw_number` (with `applicant_id`, if given) not in the disaster |
| `INTERNAL_ERROR` | Unexpected bug; logged to stdout with the runId |

Trace: `trace.call = { tool, request, data (root, snapshot, loadId, projects), map (states requested/with shapes/missing, shape errors, recoded projects, not placed, counties not in shapes, shade conflicts, overlaps remaining), response, timingsMs, error }`; at `debug` the widget is stored as `runs/<date>/<runId>/widget.html` (run folder, not `artifacts/`).

---

## 7. Configuration

### 7.1 Environment variables

| Variable | Source | Values |
|---|---|---|
| `LLM_ENDPOINT_PRIMARY` | `valueFrom: llm-primary` | `databricks-claude-haiku-4-5` |
| `LLM_ENDPOINT_FALLBACK` | `valueFrom: llm-fallback` | `databricks-gpt-5-4-mini` |
| `TRACE_VOLUME` | `valueFrom: trace-volume` | Resolves to `/Volumes/users/tom_jacobson/lancelot_traces`; the tracer also accepts the `catalog.schema.volume` form |
| `CHOROPLETH_DATA_VOLUME` | `valueFrom: choropleth-data` | Resolves to `/Volumes/users/tom_jacobson/choropleth_data` (D41); default `users.tom_jacobson.choropleth_data` if unset |
| `APP_TRACE_LEVEL` | `app.yaml` | `debug` through Phase 2 testing, then `production` before first real use (R7, Q6) |
| `STARTUP_SELFTEST` | `app.yaml` | `full` through Phase 2 testing, then `render` (R7); `off` also valid |
| `TRACE_FAULT_INJECT`, `TRACE_FAULT_INJECT_UNTIL` | One-off deployment override only | V19 only; never in `app.yaml` (D17) |
| `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`, `DATABRICKS_APP_PORT`, `DATABRICKS_APP_NAME` | Injected by the platform | Never set by hand |

### 7.2 `app.yaml` rules

`command: ["node", "server.mjs"]` (Apps runs `npm install` automatically); `env` entries only. No `resources:` block, no secrets, no build step.

### 7.3 Changing app settings

`PATCH /api/2.0/apps/mcp-lancelot-beta` resets fields that are omitted: it cleared `description` and `user_api_scopes` once. Always send `name`, `description`, `user_api_scopes`, and the full `resources` list together, then re-read the app to confirm. Keep resource names aligned with the endpoint or volume they point to.

---

## 8. Dependencies

| Package | Version | Rule |
|---|---|---|
| `mermaid` | `11.17.2` exact | The unsupported-type list was measured against it. Upgrade only with a full gallery run and user review; types may start or stop working |
| `jsdom` | `27.3.0` exact | Tied to render.mjs's globals approach |
| `pdf-parse` | `1.1.1` exact | The internal-module import and warm-load fix depend on this version |
| `@resvg/resvg-js` | `2.6.2` exact | Native crash history |
| `opentype.js` | `1.3.4` exact | Text measurement |
| `dejavu-fonts-ttf` | `2.37.3` exact | Bundled fonts (the container has none) |
| `mammoth`, `exceljs`, `express` | caret ranges | `extractText.mjs` and HTTP |
| `@modelcontextprotocol/sdk` | `1.32.2` exact | Pinned (D22) to the version the first Phase 2 deploy installed (startup run `startup-20261105T162930Z-1e80b6`). `server.mjs` uses `registerTool` when present, else `tool` |
| `zod` | `3.25.76` exact | Pinned with the SDK (D22); tool input schema |

No front-end, build-tool, or headless-browser packages. There is no lockfile yet (no npm in the notebook environment); the trace records installed versions, so drift is visible.

---

## 9. Observability and verification

### 9.1 Tracer rules

* `started.json` first (2 s cap), `trace.json` last, artifacts in between with concurrency 4; each write individually caught.
* For MCP calls (Phase 2), the full trace is written after the response is sent.
* `runId` is returned to the caller on success and error.
* Version identity: `version.versionFile.commit` (from `VERSION.json`) and `version.sourceHash` (sha256 over `package.json`, `app.yaml`, `server.mjs`, `lib/**/*.mjs`, D37). The agent recomputes `sourceHash` locally with `computeSourceHash()` to match a trace to a commit.
* Console logs are structural only (runId, stage, endpoint, status, timings) at every trace level.

### 9.2 Startup self-test (Built)

Runs on every process start in mode `full`: volume write/read check, ping both endpoints, extraction-only checks of `sample.docx`, `.xlsx`, `.json`, a smoke render, `sample.pdf` end to end through the same pipeline as real calls, then the 32-type gallery. Machine verdict = volume + pings + extractions + smoke render + PDF; gallery failures are reported but never blocking (D13). Choropleth stages, reported but never blocking: `choroplethData` (`full` only, right after the volume check; reads `manifest.json` and the latest index with the service principal, D41) and `choroplethWidget` (`full` only, last; runs `generate_choropleth` on DR-4856 in memory, at `debug` stores `artifacts/choropleth/DR-4856.html`, D42). Ends with `trace.json`, the report, and `latest/` copies.

### 9.3 Agent verification loop

1. Commit; write `VERSION.json`; compute the expected `sourceHash`.
2. `apps get` -> deploy via the Apps API -> poll the deployment to `SUCCEEDED`.
3. Poll `latest/startup-summary.json` until `sourceHash` matches; read `trace.json` and artifacts.
4. Judge machine checks; then the human gate where required.

### 9.4 Test layers

| Layer | How |
|---|---|
| Syntax | `node --check` on every module |
| Unit (committed, `test/`) | `npm test` = `node --test --experimental-test-module-mocks test/*.test.mjs`. 40 tests in 5 files (2026-11-05): selection (8), tracer (10), report (6), pipeline (10, with `render.mjs`, `databricksAuth.mjs`, and `fetch` mocked), fault injection (6). Each file runs in its own process, so environment set at import time does not leak between files |
| Deployed | Startup self-test trace (automatic on every deploy) |
| Unit, count 2026-11-12 | 9 files, 93 `test(...)` calls: choropleth 13, diagramPolicy 6, fault-injection 6, inputs 18, pipeline 19, report 6, selection 8, tool 7, tracer 10. **Node tests have not been run since D41** (`node` is not executable on job compute and interactive compute was down), so the Choropleth tests are committed but unproven |
| Ops (Python) | `python -m unittest discover -s test -p "test_*.py"`: `test_trace_cleanup.py` (8), `test_openfema_load.py` (25, D41), `test_county_boundaries_load.py` (14, D43); the load tests also run as one-off jobs because a job has no `__file__` |
| Human | Report review gate before each new phase (D11); PNG correctness is only confirmed by the user |
| Manual | V19, on explicit request only (D17) |

Rules: every behavior change in a built module comes with a test in `test/`; the suite must pass before every commit that touches `lib/` or `server.mjs`; tests never reach real endpoints, the real volume, or the network.

### 9.5 What Databricks records on its own

AI Gateway usage tracking on both endpoints records request metadata (requester, time, status, tokens) in `system.serving.endpoint_usage` (no prompts or replies; the user currently lacks access). Inference tables are not enabled. Prompts and replies exist only in this app's traces.

---

## 10. Rendering rules

* `render.mjs` is the only renderer. Call `renderMermaid({ mermaid, format: 'png' })`; it returns `{ png: <base64> }` or `{ pngFailed, pngError, svg }`, and throws `ValidationError` for bad Mermaid.
* Distinguish the two failures: `ValidationError` = the Mermaid is wrong (one LLM repair allowed); `pngFailed` = the rasterizer failed on valid Mermaid (no repair, `RENDER_FAILED` at `rasterize`). Exception (D28): a size-limit `pngFailed` gets one resize retry. "Too large" is measured on the rendered PNG (the renderer's 8,000 px per side), never estimated from Mermaid text; `parseTooLarge` relies on the exact wording in the verbatim `render.mjs`, which is pinned by a test. Known limit (open issue OI1, deferred): very long inputs can still end in `RENDER_FAILED`; possible fix is steering type selection toward types that suit long inputs.
* `ValidationError` does not set `err.name`; detect it with `instanceof`.
* Keep `htmlLabels: false` and `securityLevel: 'strict'`; never let diagram input change them (directives are stripped).
* Allowed types (D29): 25. Of the 32 catalog types, 4 cannot render (below) and 3 are excluded by choice in `lib/tools/mermaid/lib/diagramPolicy.mjs` (TreeView, Treemap, Cynefin). Excluded types are never listed for the model, a reply naming one defaults to Flowchart, and a caller's `diagramType` naming one is ignored (selection runs; trace `select.requestedRejected: "excluded"`). They still render, so the startup gallery keeps checking them. Supported (renderable) types: 28 of 32 catalog types. Architecture and Mindmap need a canvas (jsdom has none); Agentflow and Use case are not in mermaid 11.17.2. `findDiagramCatalogEntry` refuses unsupported types; only the gallery renders them, to re-check.
* Line breaks in node labels: watch whether LLM output uses literal `\n`; confirm visually in the report.

---

## 11. Security and data handling

* Untrusted input end to end (invariant 14). Report content always escaped; no `<script>`, no external `src`/`href`.
* Trace levels (D6): `debug` stores copies of documents, prompts, replies, Mermaid, and PNGs; `production` stores none of them. Self-test inputs are non-sensitive Pokémon content.
* **Data location (Q6, decided):** traces live in the `users` catalog, owned by `yvan.aquino@databricks.com`. Rule: only synthetic or public documents may be processed while `APP_TRACE_LEVEL=debug`; the app must be on `production` before any real document is sent to it (R7 sets when that switch happens).
* **Choropleth data load (D36, D39):** the job `mcp-lancelot-beta OpenFEMA load` (ID `603958303601756`) runs `ops/openfema_load.py` daily at 04:00 UTC on serverless compute as the user, one run at a time, one retry after 10 minutes, failure email to the user. Source is public OpenFEMA data; silver and gold keep only whitelisted fields (no obligation fields, `hash`, or Grants Manager IDs). The app reads only the exported files in `choropleth_data` (D41), never the tables, and only snapshots listed in `manifest.json`, which the job writes last after the load log says `SUCCEEDED`. A non-blocking startup self-test stage (`choroplethData`) reads the manifest and latest index with the app's service principal (2026-11-12: OK, latest `2026-11-12`, 7 snapshots, 357 disasters).
* **County boundaries load (D43):** the job `mcp-lancelot-beta county boundaries load` (ID `126560609586632`) runs `ops/county_boundaries_load.py` yearly (1 June 06:00 UTC) plus manual runs, on serverless compute, fetching public-domain Census files from www2.census.gov (or from `census_boundaries/upload/` with `--source-dir`). Every FEMA county code must resolve through the crosswalk or the load fails; the vintage is a pinned parameter.
* **Retention (Q7, decided and implemented):** run folders are kept 30 days. The job `mcp-lancelot-beta trace cleanup` (ID `637032316790620`) runs `ops/trace_cleanup.py` daily at 03:00 UTC on serverless compute, as the volume owner, one run at a time, with failure emails to the owner. It deletes only `<subdir>/<YYYY-MM-DD>` folders, where `<subdir>` is `runs` (server traces) or `client-runs` (`lancelot-client` results, client decision D11; added 2026-11-05), whose date is more than 30 days before today (UTC); `latest/`, `client-runs/latest/`, files, and folders with other names are never touched, and no other top-level folder can be selected. `--dry-run` lists without deleting. Verified 2026-11-05 with a dry run and a real run against a seeded `runs/2000-01-01` folder, and again after adding `client-runs` (dry run `656218103216507`, real run `936725244259066`: deleted only seeded `2000-01-01` folders in both). Volume files never expire on their own, so do not disable the job without a replacement.
* Identity: LLM calls and trace writes use the service principal; user files (Phase 2) use only the forwarded user token, home-folder scoped (invariant 15). Never log or trace tokens.
* Least privilege: one user scope (`workspace.workspace:read`); add `files` only if `/Volumes` input is ever approved.
* **Where these rules live (R5, decided):** `SECURITY.md` is kept unchanged from the original app (Q4) and describes the old browser app; this section is the security reference for the MCP server, and `README.md` points here.

---

## 12. Deployment and change workflow

1. Edit with workspace file tools (`createAsset` + `editAsset`), never shell writes.
2. Verify: `node --check` on changed files and `npm test` (all tests pass).
3. Commit locally with a message that names the reason; never push.
4. Write `VERSION.json`; compute `sourceHash`.
5. `apps get` (must be `RUNNING`, no pending deployment) -> `POST /api/2.0/apps/mcp-lancelot-beta/deployments` with `source_code_path` and `mode: SNAPSHOT` (the CLI `apps deploy` is blocked by guardrails).
6. Verify via the trace (section 9.3).
7. Record results and decisions in `BUILD_PLAN.md`; tag phase milestones (`phase1-approved` -> `ac85f0a`).

One-off environment overrides on a deployment (`env_vars`) are reserved for V19 and need the user's explicit authorization; the next normal deploy returns to `app.yaml`.

---

## 13. Environment constraints (known, verified)

| Constraint | Consequence |
|---|---|
| Agent cannot read app logs (`getAppsLogs` OAuth exchange fails) | Traces in the volume are the agent's only runtime evidence |
| Agent cannot call the app URL | Verification through the startup self-test; Q3 and V11/V12 need the user |
| `databricks apps deploy` CLI blocked | Deploy through the Apps API |
| `createAsset` appends `.py` to extensionless names | Generated files need an extension (`VERSION.json`) |
| Workspace delete is blocked for the agent | The user deletes stray files |
| Serverless notebook has Node 22 but no npm | Modules needing npm packages are tested with module mocks or after deploy |
| No catalog allows creating a schema | Traces live in the user's own schema `users.tom_jacobson` |
| Notebook compute is sometimes slow to accept commands | Retry once; it is not an app problem |

---

## 14. Change control

**Needs a recorded decision in `BUILD_PLAN.md` §11 before implementing:**
* Anything that breaks an invariant in section 3.
* Any change to a contract in section 6 (tool inputs/outputs, error codes, routes, trace schema, report structure).
* Editing a verbatim module or prompt file.
* Changing endpoints, the fallback chain, the time budget, or token limits.
* Changing a pinned dependency version.
* Adding app resources or user scopes.
* Adding a tool, or changing a tool's output type (invariants 1 and 4).
* Changing a Choropleth table, its schema, or the load job (`BUILD_PLAN.md` D36).
* Changing trace levels, data location, or what is stored at `production`.
* Making a manual test automatic, or removing a human gate.

**Does not need a decision:** refactors inside a built module that keep its contract, new trace fields (additive), new self-test checks that are non-blocking, documentation fixes.

### Review checklist (use for every change)

- [ ] `npm test` passes; new behavior has a test in `test/`
- [ ] Tool code stays in its own folder; no imports between tools; stateless; no UI routes; widget JavaScript only from pinned bundled libraries, no network access
- [ ] Verbatim modules and `lib/tools/mermaid/PROMPTS/` untouched (or a decision exists)
- [ ] Import directions match section 4.3; no cycles
- [ ] All model calls go through `makeLlmCaller`; no `temperature`; retry rules unchanged
- [ ] New work takes its time from the request `deadlineAt`
- [ ] Every new LLM attempt, stage, and failure appears in the trace; content only via `tracer.text()` / `tracer.errorMessage()`
- [ ] No trace write can throw or change a result
- [ ] Untrusted content escaped in any HTML; no new route re-runs the self-test
- [ ] `app.yaml` holds only `command` and `env`; no fault-injection settings
- [ ] Deployed through the Apps API; startup trace `OK` with the matching `sourceHash`
- [ ] `BUILD_PLAN.md` updated (decisions, results); commit local only

---

## 15. Review findings and open items (2026-11-05)

### Resolved

| # | Finding | Resolution |
|---|---|---|
| R1 | `README.md` was still the original GSA Python template | Rewritten for this server: purpose, status, document map, how it works, layout, test and deploy commands |
| R2 | Unit and mock tests had only run as scratch scripts | Committed under `test/` (40 tests, 5 files, all passing); `npm test` script added; rules in section 9.4 |
| R3 | `/health` `selftest.report` showed a path even when the report write failed | Fixed in `server.mjs`: set only when the report write succeeded. Takes effect on the next deploy |

### Decided by the user (2026-11-05)

The user accepted the reviewer's recommendation on all five. Recorded in `BUILD_PLAN.md` §11 (Q6, Q7, D18–D20).

| # | Question | Decision | Follow-up |
|---|---|---|---|
| Q6 | Is `debug`-level data acceptable in the `users` catalog (owned by `yvan.aquino@databricks.com`)? | Only synthetic or public documents may be processed at `debug`. Switch to `production` before any real document | Rule in section 11; enforced together with R7 |
| Q7 | How long to keep run folders? | 30 days, deleted by a small scheduled job | Done 2026-11-05: job `637032316790620`, daily 03:00 UTC (section 11) |
| R5 | Where do the MCP server's security rules live? | `SECURITY.md` stays unchanged (Q4); section 11 of this file is the MCP security reference; `README.md` points to it | Done: pointer added to `README.md` |
| R6 | Should the Phase 2 response include `mermaidSource`? | Yes, always (section 6.1) | Implement in Phase 2 |
| R7 | When to scale back the startup self-test? | Keep `STARTUP_SELFTEST=full` + `APP_TRACE_LEVEL=debug` through Phase 2 testing; switch to `render` + `production` before first real use | `app.yaml` change at the end of Phase 2 testing |

### Multi-tool expansion (2026-11-06)

Recorded in `BUILD_PLAN.md` §11 D30–D36. D30 changed invariants 1, 2, 4, 14 (above) and D36 added invariant 19. The Choropleth design (source, inputs, widget, delivery, storage, refresh, sanitization) is in D34–D36, amended by D41 (volume files instead of SQL), D42 (no third-party JavaScript) and D43 (Census county shapes). **Built and documented 2026-11-12:** contract in section 6.5, files in 4.1, flow in 5.5. Last startup check: run `startup-20261112T164149Z-3a902f` OK (`choroplethData` and `choroplethWidget` both ok). Its `VERSION.json` still says commit `ee775aa`, although `7fe0c73` (widget layout) was committed three minutes before that start; stamp `VERSION.json` on the next deploy so the trace names the right commit. The D32 folder layout (`lib/core/`, `lib/tools/<tool>/`) was approved by the user on 2026-11-06 and the move was done the same day (D37): file map (4.1), allowed imports (4.3), and verbatim-module paths (invariants 3, 5, 6) updated; the verbatim files moved as a group into `lib/tools/mermaid/lib/` (and `lib/core/` for `databricksAuth.mjs`) and stayed byte-identical.

### Choropleth square image (2026-11-12)

Recorded in `BUILD_PLAN.md` §11 **D44** (**Built and deployed 2026-11-12**, commit `cca15fd`; see D44 for where the build differs from the plan: separate `declarations/v1` files, no image `uri`). Changes the Choropleth output type (invariant 4, so a decision was required by section 14) and the load job (section 14, D36): after each snapshot the job runs `ops/declarations_load.py`, which writes each disaster's official title and FEMA declaration designations to `choropleth_data/declarations/v1/`. Decided by the user: affected = Individual Assistance or any PA category other than B (bare `PA` counts); title = FEMA's official declaration title; header logo left of the title (title may wrap to two lines, map shrinks); fallback = centered logo in place of the map, call still `OK`; DHS logo use approved. No new packages, resources, or scopes. Contract: section 6.5 (`image` content item, `structuredContent.image`); files: `lib/tools/choropleth/lib/image.mjs`, `imageRasterWorker.mjs`, `ops/declarations_load.py`.

### Deferred by design

| # | Item | When |
|---|---|---|
| Q3 | Are identity headers (`x-forwarded-access-token`, `x-forwarded-email`) forwarded on MCP calls? | **Answered 2026-11-05 for app-to-app calls; the user-token case is accepted as a known limit.** Evidence from `lancelot-client`, both checked against the server's own traces. *Signed-in user (Mode A):* runs `client-20261105T190541Z-1b2318` and `client-20261105T195134Z-28ff7f`: C2 shows `x-forwarded-email`, `x-forwarded-user`, `x-forwarded-preferred-username` but `forwardedTokenPresent: false`; every call trace records `forwardedToken: false`; V11 returns `ACCESS_DENIED` (traces `call-20261105T190705Z-ca9276`, `call-20261105T195312Z-948fff`). Adding `workspace.workspace:read` to the client made the server's proxy reject the user token (401; run `client-20261105T192743Z-1dce3c`), so that was reverted. *Client service principal (Mode B):* run `client-20261105T195350Z-0979a5`: C2 shows `forwardedTokenPresent: true`, email = application ID `433aae0e-6618-4cc8-8e6d-2f789c30363d`, `workspace/list` probe of its own folder 200; every call trace records `forwardedToken: true`; V11 OK reading `/Users/433aae0e-…/lancelot-client/sample.pdf` (trace `call-20261105T195619Z-0ea33b`); V12 still `ACCESS_DENIED`. Result: the token is missing only for user-token app-to-app calls. **Not tested:** direct human connections (AI Playground, Genie Code); `/api/selftest-obo-scope` stays until that is checked or the user drops it |
| R4 | No `package-lock.json` (no npm in the notebook environment) | Interim, reviewer's proposal: exact pins for the rendering stack plus installed versions recorded in every trace. Generate and commit a lockfile if npm becomes available |
