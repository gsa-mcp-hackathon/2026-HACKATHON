# mcp-lancelot-beta

A headless [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server, deployed as the Databricks App `mcp-lancelot-beta`, that turns one document (PDF, DOCX, XLSX, HTML, CSV, JSON, YAML, or text) into a Mermaid diagram rendered as a PNG. It is the server-side rebuild of the original "Lancelot Beta" Mermaid diagram generator web app.

**Status:** Phase 1 (startup self-test) is built and approved. Phase 2 (the `generate_diagram` MCP tool at `POST /mcp`) is built and being verified.

Connect an MCP client to `https://mcp-lancelot-beta-7474654188777746.aws.databricksapps.com/mcp` (stateless Streamable HTTP, Databricks OAuth). The single tool, `generate_diagram`, takes exactly one of `data` (text), `fileBase64` + `fileName`, or `workspacePath` (a file in your own `/Users/<you>/` folder), plus optional `diagramType` and `hint`, and returns a PNG plus JSON metadata.

**Known limit:** when another Databricks App (such as `lancelot-client`) calls this server *as a signed-in user*, Databricks forwards the user's identity but not their access token, so `workspacePath` returns `ACCESS_DENIED`; such clients should send files as `fileBase64`. When the other app calls *as its own service principal*, `workspacePath` works, but only for files in that service principal's own `/Users/<application-id>/` folder (see `ARCHITECTURE.md`, invariant 15 and Q3).

## Read first

| Document | What it is |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | The architecture, its invariants, and the review checklist for every change |
| [BUILD_PLAN.md](BUILD_PLAN.md) | Build history, decision log, phase status, verification checklist and results |
| [docs/V19_TRACE_FAILURE_TEST.md](docs/V19_TRACE_FAILURE_TEST.md) | Manual trace-failure test (run only on request) |
| [lib/tools/mermaid/PROMPTS/MCP_REBUILD_GUIDE.md](lib/tools/mermaid/PROMPTS/MCP_REBUILD_GUIDE.md) | Original rebuild spec (superseded where BUILD_PLAN.md corrects it) |
| [SECURITY.md](SECURITY.md), [LICENSE.md](LICENSE.md) | Carried over unchanged from the original app. `SECURITY.md` describes the old browser app; the MCP server's security rules are in [ARCHITECTURE.md section 11](ARCHITECTURE.md#11-security-and-data-handling) |

## How it works

1. Text is extracted from the input (`inputs.mjs` around the original `extractText.mjs`, both in `lib/tools/mermaid/lib/`).
2. An LLM picks the best diagram type (`selection.mjs`), unless the caller names one. Types listed in `diagramPolicy.mjs` (currently TreeView, Treemap, Cynefin) are never offered or accepted; edit that list to change it.
3. The LLM writes Mermaid using the original syntax guides and DHS color rules in `lib/tools/mermaid/PROMPTS/` (`pipeline.mjs`). Models (set by the app's `llm-primary`/`llm-fallback` resources, not in code): `databricks-claude-haiku-4-5`, falling back to `databricks-gpt-5-4-mini` (decision D27).
4. The original server-side renderer (`render.mjs`, `rasterizeWorker.mjs`) produces the PNG; invalid Mermaid gets one LLM repair attempt, and a diagram too large to render (over 8,000 px per side) gets one LLM resize attempt (result shows `resized: true`).
5. Every run is traced to the Unity Catalog volume `users.tom_jacobson.lancelot_traces` (`lib/core/tracer.mjs`; all other modules named here are in `lib/tools/mermaid/lib/`).

On every start the server runs a self-test and writes an HTML report to `/Volumes/users/tom_jacobson/lancelot_traces/latest/startup-report.html` (download it from Catalog Explorer and open it in a browser).

## Repository layout

```text
server.mjs            HTTP entry point, crash guards, startup self-test
app.yaml              Databricks Apps start command and environment mapping
package.json          Dependencies (rendering stack pinned exactly) and test script
lib/core/             Shared by all tools: tracer, Databricks auth (D32)
lib/tools/mermaid/    generate_diagram tool: lib/ (pipeline modules; see ARCHITECTURE.md section 4 for which are verbatim)
                      and PROMPTS/ (prompt text and per-diagram syntax guides, verbatim from the original)
selftest/             Non-sensitive sample documents for the startup self-test
test/                 Unit tests (node:test; plus a Python test for ops/)
ops/                  trace_cleanup.py: 30-day retention for runs/ and client-runs/, run by a scheduled job
                      openfema_load.py: daily OpenFEMA PA load for the Choropleth tool (tables + JSON export to
                      /Volumes/users/tom_jacobson/choropleth_data), run by a scheduled job (D39, D41)
docs/                 Runbooks
```

## Testing

Requires Node.js 22 or later; no npm packages are needed (rendering and Databricks calls are mocked):

```bash
node --test --experimental-test-module-mocks test/*.test.mjs
```

(`npm test` runs the same command.) The ops scripts' tests: `python -m unittest discover -s test -p "test_*.py"`. The deployed app is verified through its startup self-test trace; see ARCHITECTURE.md section 9.

## Deploying

Deploy from this folder through the Databricks Apps API after `databricks apps get mcp-lancelot-beta` shows `RUNNING` with no pending deployment. The full workflow, including the `VERSION.json` stamp and post-deploy verification, is in ARCHITECTURE.md section 12. Commits stay local; nothing is pushed to GitHub.

## License

The Unlicense; see [LICENSE.md](LICENSE.md). Security reporting: see [SECURITY.md](SECURITY.md); security rules for this server: [ARCHITECTURE.md section 11](ARCHITECTURE.md#11-security-and-data-handling).

Data rule: while the app runs with `APP_TRACE_LEVEL=debug`, send it only synthetic or public documents (decision Q6).
