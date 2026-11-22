# Decision log

Decisions not covered by the brief. Newest last.

* **D1 (2026-11-05) MCP SDK 2.3.0, not the 1.x API in the brief.** The latest `mcp` is 2.3.0. It has no
  `streamablehttp_client(url, headers=...)`; it uses `mcp.client.streamable_http.streamable_http_client(url,
  http_client=httpx2.AsyncClient(...))` and snake_case fields (`is_error`, `mime_type`, `input_schema`). The client
  builds its own `httpx2.AsyncClient` with the Bearer header, 130 s read / 15 s connect timeouts, and a response hook
  that records HTTP statuses. `terminate_on_close=False` because the stateless server answers DELETE with 405.
  Verified against a local `MCPServer` (stateless, JSON responses) returning image + text content.
* **D2 (2026-11-05) Versions pinned up front** to what the code was written and tested with: mcp 2.3.0, httpx2 2.16.0,
  databricks-sdk 0.122.0, streamlit 1.66.1, requests 2.32.5 (Python 3.12 test env). The installed versions are also
  recorded in every `result.json` (`versions`).
* **D3 (2026-11-05) V7 split into V7a (docx) and V7b (xlsx)** so each call has its own record, PNG and server runId.
* **D4 (2026-11-05) V11 path.** The `apps` scope cannot write to a user's folder. Mode A uses
  `/Users/<caller email>/lancelot-client/samples/sample.pdf`; that exists only for the owner (this source folder).
  For other users V11 is `SKIP` with `SETUP_MISSING` and is not called. Mode B uploads `sample.pdf` to
  `/Users/<sp application id>/lancelot-client/sample.pdf` as the service principal first. (User approved.)
* **D5 (2026-11-05) V12 path.** Mode A as the owner: `/Users/lancelot-v12-other-user@example.invalid/sample.pdf`
  (a folder that is not the caller's). Any other caller (including Mode B): the owner's real
  `/Users/tom.jacobson@hq.dhs.gov/lancelot-client/samples/sample.pdf`.
* **D6 (2026-11-05) Trace matching (T1).** The server sets `run.outcome = "OK"` on success and `run.outcome =
  <errorCode>` on error (lib/tool.mjs). The trace is written after the HTTP response, so the client retries a missing
  trace after 3, 6 and 10 s. Try-it calls get the same check.
* **D7 (2026-11-05) C2 verdict** is `INFO` when the route answers 200 (the content is informational), `FAIL` otherwise.
* **D8 (2026-11-05) Mode A acceptance check** is `GET /health` with the user token, without following redirects; any
  non-200 is recorded in `authFinding` (status and redirect host only) and the app falls back to Mode B.
* **D9 (2026-11-05) Incremental writes.** `result.json` is rewritten after each case (`finishedAt: null` until done), so
  an interrupted run still leaves a partial result. PNGs are written as soon as a case returns one.
* **D10 (2026-11-05) Samples.** The binary samples and `sample.json` are copied by the user in the workspace UI
  (editing tools only write text files). Missing samples make the dependent cases `FAIL` with "sample missing".
* **D11 (2026-11-05) client-runs retention: 30 days.** First documented only. Later the same day the server project
  extended its existing job "mcp-lancelot-beta trace cleanup" (637032316790620, daily 03:00 UTC) so
  `ops/trace_cleanup.py` cleans `runs/` and `client-runs/` by default. Verified from run 936725244259066 (task run
  62939564124852, SUCCESS): `client-runs/: 3 day folder(s) total, 1 expired, 1 kept`, `left alone: ['latest']`,
  deleted the seeded `client-runs/2000-01-01`. No separate client job: it would duplicate this one.
* **D12 (2026-11-05) Git: local-only repository.** `lancelot-client` was first created as a plain workspace folder.
  Later on 2026-11-05 it was put under Git with `git init -b main` in place (user's choice): no remote, never push.
  Everything is committed, including the synthetic/public Pokemon samples (~350 KB).
* **D13 (2026-11-05) Small additions beyond the suggested layout, recorded after review:** `client/runner.py` (glue
  between auth, suite and storage), a Connection page, and `STREAMLIT_BROWSER_GATHER_USAGE_STATS=false` in `app.yaml`
  (turns off Streamlit's browser usage telemetry; the brief only specified `command`).
* **D14 (2026-11-05) TEMPORARY scope experiment.** First suite run (client-20261105T190541Z-1b2318) in Mode A:
  C2 `forwardedTokenPresent=false`, V11 `ACCESS_DENIED` ("did not forward your access token"). To test whether the
  client's scope is the cause, `user_api_scopes` was changed from `["apps"]` to `["apps", "workspace.workspace:read"]`
  (PATCH with description and the full resources list). This goes beyond the brief's least-privilege rule; revert to
  `["apps"]` if C2/V11 do not change.
  **Outcome (2026-11-05):** run client-20261105T192743Z-1dce3c after re-consent: the server's sign-in proxy answered
  **401** to the user token on `/health` (Mode A probe) and `/mcp`. With `["apps"]` alone the same user had been
  accepted. The extra scope did not get the token forwarded; it stopped the token being accepted at all. The client
  fell back to Mode B, which also got 401 on all 16 cases because the client service principal did not yet have
  CAN_USE on mcp-lancelot-beta. **Reverted** to `["apps"]` at 19:38Z (PATCH with description and full resources;
  effective scopes back to apps + iam defaults). User must sign in again so the narrower token is issued.
* **D15 (2026-11-05) "Force Mode B (service principal)" sidebar switch** (requested by the user). Skips Mode A
  entirely: the user token is not probed or sent; `authFinding.forcedModeB = true`, the auth note says Mode B was
  forced, and `authFinding.userTokenForwarded` still records whether a user token arrived. Per browser session.
  Observation from try-it run client-20261105T192939Z-e48b52 (Mode B, after CAN_USE was granted): the server trace
  shows `caller.email = 433aae0e-...` (the SP application id) and `caller.forwardedToken = true`, so in Mode B the
  server does receive a forwarded token; V11 in Mode B may therefore pass against the SP's own uploaded file.
* **D16 (2026-11-05) Full dependency lock (code review M4).** `requirements.txt` now pins the whole closure (55
  packages), resolved for Python 3.11 / Linux x86_64 from `requirements.in`; re-resolving the lock gives the identical
  set. Changes from the earlier build: `requests` 2.32.5 -> 2.34.2 (pip-audit: PYSEC-2026-2275, fixed in 2.33.0);
  `fastapi==0.162.0` added, unused by the app, to replace the runtime's preinstalled fastapi 0.115, which requires
  starlette<0.39 and conflicted with starlette 1.10. pip-audit on the lock: no known vulnerabilities. Hashes
  (`--require-hashes`) were not added: one wrong wheel tag on the Apps image would break the build. Each run records
  `requirementsSha256` and `pinsMatchInstalled`. The deployment scan findings could not be read here (the findings
  API returns 403 "not enabled for this workspace"); they are listed on the app's Security tab (needs CAN MANAGE).
  That scan checks source code only, not dependencies.
* **D17 (2026-11-05) Code review Low findings.** L2 auth decision cached 5 min per session, fresh at run start, one
  WorkspaceClient per process. L3 settings in `client/config.py` + `app.yaml`. L4 only ordinary exceptions and
  cancellation are recorded; interrupts and exits propagate. L5 typed `NotFound`. L6 message policy (see README
  "Recorded data"). L7 14 MB upload limit before upload, 4,000,000-character paste limit. L8 `sha256Of`. L9 `callMs`
  + `timingNotes`. L10 tests 24 -> 47 (in-process MCP server, try_it, V11 setup, AppTest). L11 result.json retry +
  `result.write-error.json`. L1 (`.git` deployed) is open: there is no documented ignore file for workspace-source
  deploys, and the fix (moving the app into a subfolder, or moving the git directory) changes the repo layout. The
  user decided not to address L1 at this time, so `.git/` stays in each deployment snapshot. Not changed, by the
  user's decision: C1, M1-M3 and L1.
* **D18 (2026-11-06) Second server tool, `generate_choropleth` (server D42).** C1 now requires `/health` tools ==
  `["generate_diagram", "generate_choropleth"]` and V4 requires exactly those two tools with their inputs, so the
  old one-tool server fails both. `mcp_client.call_tool(token, name, args)` serves both tools; `parse_call_result`
  takes the first text item that is a JSON object as `meta` (the choropleth tool puts a plain-language summary
  first) and also returns `resources` and `structuredContent`. New cases M1-M6 (map cases; not the code review's
  Medium findings of the same names): M1 DR-4856 + PW 2 and M2 DR-4673 (number sent as a string) must be OK with a
  drawn map, the highlighted PW, and a `ui://` text/html widget that has the CSP and no external URL; M3-M6 must
  return DISASTER_NOT_LOADED, SNAPSHOT_NOT_FOUND, INVALID_INPUT (sigma 0.5) and PW_NOT_FOUND with no widget.
  Outlier counts are recorded but not fixed, because the data reloads daily. The widget HTML is not stored (it holds
  project titles); only its size, SHA-256, URI, CSP flag and any external URLs. T1 checks traces for V and M cases.
  Tests 47 -> 49.
* **D19 (2026-11-06) Show the map widgets inline for review (user request; replaces D18's "HTML not stored").**
  The data is public OpenFEMA project data. Each M case that returns a widget keeps its HTML in `SuiteRun.widgets`;
  it is written as `<case>.widget.html` next to `result.json` (the record gets `widget.file`), and `result.json`
  itself still holds only the checks. The Test suite page shows every widget right after the results table with
  `st.iframe` (fixed 1100 px, scrolls), followed by a feedback form: rating (Works as expected / Works, with
  problems / Does not work) and a comment, saved to `<run>/feedback/<case>-<UTC stamp>.json` with the server
  runId, arguments, widget SHA-256 and the signed-in reviewer's email. `st.iframe` runs the HTML with scripts and
  same-origin access to the client page; that is accepted because the HTML is this server's own tool output (no
  LLM in generate_choropleth, data text set with textContent) and it carries its own CSP `default-src 'none'`.
  `report.html` keeps its no-script, no-link rule and names each widget file by path. Tests 49 -> 51.
* **D20 (2026-11-06) Try It - FEMA page (user request).** Sidebar pages are now Test suite, Try It - Mermaid
  (the old Try it), Try It - FEMA and Connection. `runner.try_fema` makes one generate_choropleth call and writes a
  `try-fema` run (result.json, report.html, TRY.widget.html; never latest/). Verdicts: an OK map is checked with
  the suite's M-case checks (disaster, highlighted PW, mapDrawn, CSP, no external URLs); a known error code is
  INFO, not FAIL, because it can be the right answer to the input; anything else is FAIL. Presets are seven
  disasters checked on 2026-11-06, each covering a different map case. `parse_call_result` now also returns
  non-JSON text items (`texts`) so the page can show the tool's summary. Results live in session state (last 10)
  so the feedback form and frame-height slider do not lose the map on rerun. Tests 51 -> 54.
* **Fix (2026-11-09) project counts.** `apply_choropleth` read `totals.projects`, which the server never sends; it
  now reads the server's `analysis.totals` names: `projects` = `projectsAll`, plus `projectsMapped`, `unmappable`,
  `outlierCounties`, `statewideOutliers`. The test fake server had copied the wrong name, which hid the bug; it now
  uses the server's shape. Case summaries show `projects=N (mapped M)`.
* **D21 (2026-11-12) C2 and V11 removed (user).** Both required the signed-in user's token to reach the server
  through this client app (C2 probed for it, V11 read the caller's own folder with it). They failed in every Mode A run
  since 2026-11-05 (C2 `forwardedTokenPresent=false`, V11 `ACCESS_DENIED`), and the user ruled they must never pass:
  one app forwarding a user's token to another would be a security violation. Removed: both cases, `ev_obo`,
  `SuiteDeps.prepare_v11`, `runner.make_prepare_v11` (including the Mode B upload to the service principal's folder),
  and their tests (suite cases 22 -> 20; tests 54 -> 49). V12 (another user's folder must be `ACCESS_DENIED`) stays.
  `OWNER_V11_PATH` stays in config because V12 uses it when the caller is not the owner. The Connection page button
  that calls `/api/selftest-obo-scope` is not part of the suite and was left as is.
